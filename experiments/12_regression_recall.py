"""實驗 12：檢索品質回歸測試（CI/部署前把關，docs/roadmap_v1.md 第 4 節）。

用 eval.jsonl 在「寬鬆相關性」尺規（同案由 / 共享主要實體法條，沿用實驗 11）下，
量測最佳線上管線的 Recall@5。低於門檻則 exit 1，供 self-hosted CI 或部署前手動把關，
確保改動（如索引重建、searcher 調整）沒讓檢索品質退步。

預設用 hybrid_rerank（不 rewrite）：穩定、不依賴 LLM，可重現；
帶 --rewrite 則測含 LLM 改寫的完整管線（較慢，需 gemini gateway）。

用法（home_wsl，需 GPU + 索引）：
    LCR_PROCESSED_DIR=/home/mrfrog/data/processed \\
    LCR_INDEX_DIR=/home/mrfrog/data/index \\
    PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \\
      ~/.local/bin/uv run python -u experiments/12_regression_recall.py \\
        --threshold 0.80 --sample 60

退出碼：0 = 通過（R@5 >= threshold），1 = 退步。
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lcr.config import settings  # noqa: E402
from lcr.retrieval.searcher import Searcher  # noqa: E402

# 程序法不算「主要實體法條」（沿用實驗 11 尺規）
_PROC_LAWS = ("刑事訴訟法", "民事訴訟法", "行政罰法")


def main_articles(arts_str: str) -> set[str]:
    out: set[str] = set()
    toks = arts_str.split() if arts_str else []
    i = 0
    while i < len(toks) - 1:
        law, num = toks[i], toks[i + 1]
        if any(c.isdigit() or c == "-" for c in num):
            if not any(p in law for p in _PROC_LAWS):
                out.add(f"{law} {num}")
            i += 2
        else:
            i += 1
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.80,
                    help="Recall@5 通過門檻（低於則 exit 1）")
    ap.add_argument("--sample", type=int, default=0,
                    help="抽樣題數（0=全量 150 題）；加速回歸用")
    ap.add_argument("--rewrite", action="store_true",
                    help="測含 LLM 改寫的完整管線（較慢，需 gemini gateway）")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    processed = settings.processed_dir
    index_dir = Path(
        os.environ.get("LCR_INDEX_DIR", str(processed).replace("processed", "index"))
    )
    pairs = [
        json.loads(line)
        for line in (processed / "eval.jsonl").open(encoding="utf-8")
    ]
    if args.sample and args.sample < len(pairs):
        random.seed(args.seed)
        pairs = random.sample(pairs, args.sample)

    s = Searcher(
        chroma_dir=index_dir / "chroma",
        bm25_dir=index_dir / "bm25",
        use_gpu=True,
    )
    col = s.chroma_collection

    rel_jids = list({p["relevant_jid"] for p in pairs})
    gt = col.get(ids=rel_jids, include=["metadatas"])
    gt_meta = {m["jid"]: m for m in gt["metadatas"]}

    def is_relevant(cand_meta: dict, gt_jid: str) -> bool:
        if cand_meta.get("jid") == gt_jid:
            return True
        g = gt_meta.get(gt_jid, {})
        if cand_meta.get("title") and cand_meta["title"] == g.get("title"):
            return True
        ca = main_articles(cand_meta.get("articles", ""))
        ga = main_articles(g.get("articles", ""))
        return bool(ca & ga)

    hits = 0
    n = len(pairs)
    for idx, p in enumerate(pairs, 1):
        if args.rewrite:
            res = s.search_pipeline(p["query"], top_k=5, rewrite=True)
            cand_ids = [r["jid"] for r in res]
        else:
            ranked = s.hybrid_rerank(p["query"], top_k=5, candidate_n=20)
            cand_ids = [j for j, _ in ranked]
        if not cand_ids:
            continue
        cm = col.get(ids=cand_ids, include=["metadatas"])
        meta_map = {m["jid"]: m for m in cm["metadatas"]}
        rels = [
            is_relevant(meta_map.get(j, {"jid": j}), p["relevant_jid"])
            for j in cand_ids
        ]
        if any(rels):
            hits += 1
        if idx % 20 == 0:
            print(f"  進度 {idx}/{n} ...", flush=True)

    recall = hits / n if n else 0.0
    mode = "search_pipeline(rewrite+rerank)" if args.rewrite else "hybrid_rerank"
    print("\n" + "=" * 56)
    print(f"檢索回歸  模式={mode}")
    print(f"題數={n}  Recall@5={recall:.3f}  門檻={args.threshold:.3f}")
    print("相關性：同案由 或 共享主要實體法條（排除程序法）")
    print("=" * 56)

    if recall < args.threshold:
        print(f"[FAIL] Recall@5 {recall:.3f} < 門檻 {args.threshold:.3f}：檢索品質退步！")
        return 1
    print(f"[PASS] Recall@5 {recall:.3f} >= 門檻 {args.threshold:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
