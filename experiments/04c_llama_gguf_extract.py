"""實驗 04c：GGUF Llama 本地抽取（llama-cpp-python，不需要 gated HF access）。

使用 QuantFactory/Llama-3.2-Taiwan-Legal-3B-Instruct-GGUF Q4_K_M，
與 gpt-5-mini batch 結果對比。

用法（在 home_wsl）：
    python experiments/04c_llama_gguf_extract.py --n 50
    python experiments/04c_llama_gguf_extract.py  # 全量
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

GGUF_PATH = "/home/mrfrog/models/Llama-3.2-Taiwan-Legal-3B-Instruct.Q4_K_M.gguf"

SYSTEM_PROMPT = (
    "你是台灣法律判決書分析助理。請從判決書中抽取結構化要素，只輸出 JSON，不要其他說明。"
)

USER_TEMPLATE = """判決書：

【主文】{main}

【事實】{facts}

【理由（前1500字）】{reasoning}

請以 JSON 格式回傳以下欄位：
{{
  "verdict": "有罪/無罪/不受理/緩刑/免刑/駁回/其他/不明",
  "sentence": "刑度如有期徒刑3月，無則 null",
  "compensation": 賠償金額整數或 null,
  "subjective": "故意/過失/不明",
  "facts_summary": "100-150字事實摘要"
}}"""


def load_llama(gguf_path: str, n_gpu_layers: int = -1):
    from llama_cpp import Llama
    print(f"載入 GGUF 模型：{gguf_path}")
    llm = Llama(
        model_path=gguf_path,
        n_ctx=4096,
        n_gpu_layers=n_gpu_layers,  # -1 = 全部放 GPU
        verbose=False,
    )
    print("載入完成")
    return llm


def extract_one(record: dict, llm) -> dict:
    main = (record.get("main") or "")[:400]
    facts = (record.get("facts") or "")[:1500]
    reasoning = (record.get("reasoning") or "")[:1500]

    prompt = USER_TEMPLATE.format(
        main=main or "(無)",
        facts=facts or "(無)",
        reasoning=reasoning or "(無)",
    )

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ]

    output = llm.create_chat_completion(
        messages=messages,
        max_tokens=512,
        temperature=0.1,
        response_format={"type": "json_object"},
    )
    text = output["choices"][0]["message"]["content"].strip()

    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return {"error": "parse_failed", "raw": text[:200]}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=None)
    parser.add_argument("--corpus", default="/home/mrfrog/data/processed/corpus.jsonl")
    parser.add_argument("--segmented", default="/home/mrfrog/data/processed/segmented.jsonl")
    parser.add_argument("--out", default="/home/mrfrog/data/processed/llama_gguf_extract.jsonl")
    parser.add_argument("--gguf", default=GGUF_PATH)
    args = parser.parse_args()

    # 讀 corpus
    records = []
    with open(args.corpus, encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))

    # 讀切段結果
    seg_map: dict[str, dict] = {}
    seg_path = Path(args.segmented)
    if seg_path.exists():
        with seg_path.open(encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                seg_map[d["jid"]] = d

    # 合併切段
    for rec in records:
        seg = seg_map.get(rec["jid"], {})
        rec["main"] = seg.get("main", "")
        rec["facts"] = seg.get("facts", "")
        rec["reasoning"] = seg.get("reasoning", "")

    if args.n:
        random.seed(42)
        records = random.sample(records, min(args.n, len(records)))
        print(f"評估模式：{len(records)} 筆")
    else:
        print(f"全量：{len(records):,} 筆")

    llm = load_llama(args.gguf)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    ok = fail = 0
    with out_path.open("w", encoding="utf-8") as fout:
        for i, rec in enumerate(records):
            result = extract_one(rec, llm)
            if "error" not in result:
                ok += 1
            else:
                fail += 1
            fout.write(json.dumps({"jid": rec["jid"], "llama": result}, ensure_ascii=False) + "\n")

            if (i + 1) % 10 == 0:
                print(f"  {i+1}/{len(records)}  ok={ok} fail={fail}")

    print(f"\n完成：ok={ok}  fail={fail}")
    print(f"輸出：{out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
