"""實驗 10：HyDE query 改寫對 dense 檢索的提升（baseline vs A vs B）。

對 eval.jsonl 的口語 query 做 A(rewrite)/B(hyde) 改寫，各跑 dense 檢索，
比 baseline（原始口語）的 Recall@5 / MRR@10。

改寫結果存 data/processed/hyde_rewrites.jsonl（避免重跑重複呼叫 LLM）。

用法（home_wsl）：
    LCR_PROCESSED_DIR=/home/mrfrog/data/processed \\
    LCR_INDEX_DIR=/home/mrfrog/data/index \\
    PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \\
      ~/.local/bin/uv run python -u experiments/10_hyde_ablation.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lcr.config import settings  # noqa: E402
from lcr.eval import hyde  # noqa: E402
from lcr.retrieval.searcher import Searcher  # noqa: E402


def recall_mrr(ranked, relevant):
    r5 = 1.0 if relevant in ranked[:5] else 0.0
    mrr = 0.0
    for i, j in enumerate(ranked[:10], 1):
        if j == relevant:
            mrr = 1.0 / i
            break
    return r5, mrr


def main() -> int:
    processed = settings.processed_dir
    index_dir = Path(os.environ.get("LCR_INDEX_DIR", str(processed).replace("processed", "index")))
    pairs = [json.loads(line) for line in (processed / "eval.jsonl").open(encoding="utf-8")]

    # 1. 產生（或載入快取）A/B 改寫
    cache_path = processed / "hyde_rewrites.jsonl"
    rewrites: dict[str, dict] = {}
    if cache_path.exists():
        for line in cache_path.open(encoding="utf-8"):
            d = json.loads(line)
            rewrites[d["query"]] = d
        print(f"載入快取改寫：{len(rewrites)} 筆")

    new = 0
    with cache_path.open("a", encoding="utf-8") as fout:
        for i, p in enumerate(pairs, 1):
            q = p["query"]
            if q in rewrites:
                continue
            rec = {"query": q, "A": hyde.rewrite(q), "B": hyde.hyde(q)}
            rewrites[q] = rec
            fout.write(json.dumps(rec, ensure_ascii=False) + "\n")
            new += 1
            if i % 20 == 0:
                print(f"  改寫進度 {i}/{len(pairs)}")
    print(f"新改寫 {new} 筆，總計 {len(rewrites)} 筆")

    # 2. 檢索評估
    s = Searcher(
        chroma_dir=index_dir / "chroma",
        bm25_dir=index_dir / "bm25",
        use_gpu=True,
    )

    def eval_variant(key: str | None):
        r5s = mrrs = 0.0
        for p in pairs:
            q = p["query"] if key is None else rewrites[p["query"]][key]
            ranked = [j for j, _ in s.dense_search(q, top_k=10)]
            r5, mrr = recall_mrr(ranked, p["relevant_jid"])
            r5s += r5
            mrrs += mrr
        n = len(pairs)
        return r5s / n, mrrs / n

    print("\n評估 baseline（口語）...")
    b5, bmrr = eval_variant(None)
    print("評估 A（rewrite）...")
    a5, amrr = eval_variant("A")
    print("評估 B（hyde）...")
    h5, hmrr = eval_variant("B")

    print("\n" + "=" * 56)
    print(f"{'query 策略':<22}{'Recall@5':>14}{'MRR@10':>14}")
    print("-" * 56)
    print(f"{'baseline 口語':<22}{b5:>14.3f}{bmrr:>14.3f}")
    print(f"{'A rewrite':<22}{a5:>14.3f}{amrr:>14.3f}")
    print(f"{'B hyde 假判決':<22}{h5:>14.3f}{hmrr:>14.3f}")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
