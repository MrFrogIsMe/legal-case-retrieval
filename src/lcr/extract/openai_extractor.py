"""OpenAI Batch API 抽取層。

使用 gpt-5-mini + Batch API（省 50%）做語意類要素抽取：
  - 判決結果（有罪/無罪/不受理/緩刑/免刑/駁回）
  - 刑度（有期徒刑 X 月/拘役 X 日/罰金 X 元）
  - 賠償金額（整數，無則 null）
  - 主觀要素（故意/過失/不明）
  - 事實摘要（100-150 字繁體中文）

Batch API 流程：
  1. 建立 .jsonl 請求檔 → upload → create batch
  2. 輪詢 batch 狀態（通常 < 24h，實際幾分鐘到幾小時）
  3. 下載結果 → 解析 → 合併回 corpus

詳見 experiments/04a_openai_batch.py。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from openai import OpenAI

from lcr.config import settings

EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["有罪", "無罪", "不受理", "緩刑", "免刑", "駁回", "其他", "不明"],
            "description": "判決結果",
        },
        "sentence": {
            "type": ["string", "null"],
            "description": "刑度，如「有期徒刑3月」「拘役30日」「罰金1萬元」，無則 null",
        },
        "compensation": {
            "type": ["integer", "null"],
            "description": "賠償或給付金額（新台幣元，整數），無則 null",
        },
        "subjective": {
            "type": "string",
            "enum": ["故意", "過失", "不明"],
            "description": "主觀要素",
        },
        "facts_summary": {
            "type": "string",
            "description": "事實摘要，100-150 字繁體中文白話，不含法條引用",
        },
    },
    "required": ["verdict", "sentence", "compensation", "subjective", "facts_summary"],
    "additionalProperties": False,
}

_SYSTEM_PROMPT = """你是台灣法律判決書分析助理。請從以下判決書內容中抽取結構化要素，
以 JSON 格式回傳，嚴格遵守 schema，不要編造原文沒有的內容。"""

_USER_TEMPLATE = """以下是判決書內容（已切段）：

【主文】
{main}

【事實】
{facts}

【理由摘錄】
{reasoning}

請抽取以下欄位（若無法確定填「不明」或 null）：
- verdict: 判決結果
- sentence: 刑度（無則 null）
- compensation: 賠償金額（整數元，無則 null）
- subjective: 主觀要素（故意/過失/不明）
- facts_summary: 事實摘要 100-150 字"""


def build_batch_request(record: dict, custom_id: str) -> dict:
    """建立單筆 batch request 物件。"""
    # 理由段可能很長，截取前 3000 字節省 token
    reasoning = (record.get("reasoning") or "")[:3000]
    facts = (record.get("facts") or "")[:2000]
    main = (record.get("main") or "")[:500]

    user_msg = _USER_TEMPLATE.format(
        main=main or "(無主文段)",
        facts=facts or "(無事實段)",
        reasoning=reasoning or "(無理由段)",
    )

    return {
        "custom_id": custom_id,
        "method": "POST",
        "url": "/v1/chat/completions",
        "body": {
            "model": settings.openai_batch_model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "judgment_extraction",
                    "strict": True,
                    "schema": EXTRACTION_SCHEMA,
                },
            },
            "max_tokens": 512,
            "temperature": 0,
        },
    }


def create_batch_file(
    records: list[dict],
    out_path: Path,
    id_field: str = "jid",
) -> int:
    """將 records 轉成 batch .jsonl 檔，回傳寫入筆數。"""
    count = 0
    with out_path.open("w", encoding="utf-8") as f:
        for rec in records:
            custom_id = rec.get(id_field, str(count))
            req = build_batch_request(rec, custom_id)
            f.write(json.dumps(req, ensure_ascii=False) + "\n")
            count += 1
    return count


def submit_batch(batch_file: Path) -> str:
    """上傳 batch 檔案並提交，回傳 batch_id。"""
    client = OpenAI(api_key=settings.openai_api_key)

    with batch_file.open("rb") as f:
        uploaded = client.files.create(file=f, purpose="batch")

    batch = client.batches.create(
        input_file_id=uploaded.id,
        endpoint="/v1/chat/completions",
        completion_window="24h",
    )
    print(f"Batch 提交成功：{batch.id}  狀態：{batch.status}")
    return batch.id


def poll_batch(batch_id: str, poll_interval: int = 60) -> dict:
    """輪詢 batch 完成，回傳 batch 物件（含 output_file_id）。"""
    client = OpenAI(api_key=settings.openai_api_key)
    while True:
        batch = client.batches.retrieve(batch_id)
        status = batch.status
        counts = batch.request_counts
        print(
            f"  [{status}] total={counts.total} "
            f"completed={counts.completed} failed={counts.failed}"
        )
        if status in ("completed", "failed", "expired", "cancelled"):
            return batch.model_dump()
        time.sleep(poll_interval)


def download_results(batch_id: str, out_path: Path) -> int:
    """下載 batch 結果，回傳成功解析筆數。

    輸出格式：每行 {"jid": ..., "gpt": {...抽取結果...}}
    """
    client = OpenAI(api_key=settings.openai_api_key)
    batch = client.batches.retrieve(batch_id)

    if not batch.output_file_id:
        print(f"Batch {batch_id} 無輸出（狀態：{batch.status}）")
        return 0

    content = client.files.content(batch.output_file_id)
    count = 0
    with out_path.open("w", encoding="utf-8") as f:
        for line in content.text.splitlines():
            if not line.strip():
                continue
            result = json.loads(line)
            custom_id = result.get("custom_id", "")
            try:
                body = result["response"]["body"]
                extracted = json.loads(body["choices"][0]["message"]["content"])
            except (KeyError, json.JSONDecodeError) as e:
                extracted = {"error": str(e)}

            f.write(
                json.dumps(
                    {"jid": custom_id, "gpt": extracted},
                    ensure_ascii=False,
                )
                + "\n"
            )
            count += 1

    return count
