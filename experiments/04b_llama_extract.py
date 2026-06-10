"""Llama-3.2-Taiwan-Legal-3B 本地抽取腳本。

在 home_wsl（RTX 3060 Ti 8GB）上執行，不需要 API key。
輸出與 openai_extractor 相同格式，方便後續對比。

用法（在 home_wsl 上）：
    python experiments/04b_llama_extract.py --n 50   # 先跑 50 筆評估
    python experiments/04b_llama_extract.py          # 全量

依賴（在 home_wsl 上安裝）：
    pip install transformers accelerate torch
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

LLAMA_MODEL_ID = "benchang1110/Qwen2.5-Taiwan-3B-Instruct"  # 免審核，繁體中文，3B

# 若 lianghsun gated 通過審核，改回：
# LLAMA_MODEL_ID = "lianghsun/Llama-3.2-Taiwan-Legal-3B-Instruct"

SYSTEM_PROMPT = """你是台灣法律判決書分析助理。請從判決書內容中抽取結構化要素，
以 JSON 格式回傳。只輸出 JSON，不要其他說明。"""

USER_TEMPLATE = """判決書內容：

【主文】
{main}

【事實】
{facts}

【理由摘錄（前2000字）】
{reasoning}

請以 JSON 回傳以下欄位：
{{
  "verdict": "有罪/無罪/不受理/緩刑/免刑/駁回/其他/不明",
  "sentence": "刑度或 null",
  "compensation": 賠償金額整數或 null,
  "subjective": "故意/過失/不明",
  "facts_summary": "100-150字事實摘要"
}}"""


def load_model():
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    print(f"載入模型：{LLAMA_MODEL_ID}")
    tokenizer = AutoTokenizer.from_pretrained(LLAMA_MODEL_ID)
    model = AutoModelForCausalLM.from_pretrained(
        LLAMA_MODEL_ID,
        torch_dtype=torch.float16,
        device_map="auto",
    )
    model.eval()
    print("模型載入完成")
    return model, tokenizer


def extract_one(record: dict, model, tokenizer) -> dict:
    """對單筆判決做抽取，回傳解析後的 dict。"""
    import torch

    main = (record.get("main") or "")[:500]
    facts = (record.get("facts") or "")[:2000]
    reasoning = (record.get("reasoning") or "")[:2000]

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": USER_TEMPLATE.format(
                main=main or "(無主文段)",
                facts=facts or "(無事實段)",
                reasoning=reasoning or "(無理由段)",
            ),
        },
    ]

    # transformers v5 breaking change:
    # apply_chat_template 現在回傳 BatchEncoding（非 tensor），要用 ** 解包
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
    )
    model_inputs = tokenizer([text], return_tensors="pt").to(model.device)

    with torch.no_grad():
        output = model.generate(
            **model_inputs,
            max_new_tokens=512,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
        )

    new_tokens = output[0][model_inputs["input_ids"].shape[1]:]
    text_out = tokenizer.decode(new_tokens, skip_special_tokens=True).strip()

    # 嘗試解析 JSON
    try:
        start = text_out.index("{")
        end = text_out.rindex("}") + 1
        return json.loads(text_out[start:end])
    except (ValueError, json.JSONDecodeError):
        return {"error": "parse_failed", "raw": text_out[:200]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=None, help="只跑前 N 筆（評估用）")
    parser.add_argument(
        "--corpus",
        default="/home/mrfrog/data/processed/corpus.jsonl",
        help="corpus.jsonl 路徑",
    )
    parser.add_argument(
        "--jfull-root",
        default="/home/mrfrog/code/lawundry_test/Dataset",
        help="原始資料集根目錄（用於讀取 JFULL）",
    )
    parser.add_argument(
        "--out",
        default="/home/mrfrog/data/processed/llama_extract.jsonl",
        help="輸出路徑",
    )
    args = parser.parse_args()

    corpus_path = Path(args.corpus)
    dataset_root = Path(args.jfull_root)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # 讀取 corpus（metadata only），回讀 JFULL 做切段
    records = []
    with corpus_path.open(encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))

    if args.n:
        import random
        random.seed(42)
        records = random.sample(records, min(args.n, len(records)))
        print(f"評估模式：隨機抽 {len(records)} 筆")
    else:
        print(f"全量模式：{len(records):,} 筆")

    model, tokenizer = load_model()

    ok = 0
    fail = 0
    with out_path.open("w", encoding="utf-8") as fout:
        for i, rec in enumerate(records):
            # 回讀 JFULL 並切段（簡易版，直接讀全文）
            src = dataset_root / rec["source_path"]
            try:
                with src.open(encoding="utf-8") as fp:
                    d = json.loads(fp.read(), strict=False)
                jfull = d.get("JFULL", "")
            except (OSError, ValueError):
                jfull = ""

            # 用已有的切段結果（若有）
            rec["main"] = rec.get("main", "")
            rec["facts"] = rec.get("facts", "")
            rec["reasoning"] = rec.get("reasoning", jfull[:3000])

            result = extract_one(rec, model, tokenizer)

            if "error" not in result:
                ok += 1
            else:
                fail += 1

            fout.write(
                json.dumps(
                    {"jid": rec["jid"], "llama": result},
                    ensure_ascii=False,
                )
                + "\n"
            )

            if (i + 1) % 10 == 0:
                print(f"  進度：{i+1}/{len(records)}  成功：{ok}  失敗：{fail}")

    print(f"\n完成：{ok} 成功 / {fail} 失敗")
    print(f"輸出：{out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
