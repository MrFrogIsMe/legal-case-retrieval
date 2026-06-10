"""OpenAI Batch API 抽取層。

使用 gpt-5-mini + Batch API（省 50%）做語意類要素抽取。
刑事/民事使用不同 schema（詳見 schemas.py）。

Batch API 流程：
  1. 建立 .jsonl 請求檔 → upload → create batch
  2. 輪詢 batch 狀態（通常幾分鐘到幾小時）
  3. 下載結果 → 解析 → 合併回 corpus

詳見 experiments/04a_openai_batch.py、docs/design_change_v1.md。
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from openai import OpenAI

from lcr.config import settings
from lcr.extract.schemas import SYSTEM_PROMPT, get_schema, get_user_template


def build_batch_request(record: dict, custom_id: str) -> dict:
    """建立單筆 batch request 物件，依 kind 選對應 schema。"""
    kind = record.get("kind", "criminal")
    reasoning = (record.get("reasoning") or "")[:3000]
    facts = (record.get("facts") or "")[:2000]
    main = (record.get("main") or "")[:500]

    user_msg = get_user_template(kind).format(
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
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": f"judgment_extraction_{kind}",
                    "strict": True,
                    "schema": get_schema(kind),
                },
            },
            "max_completion_tokens": 2048,  # 調為 low 後，2048 足夠
            "reasoning_effort": "low",     # 限制推理強度為 low 以節省費用與時間
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
