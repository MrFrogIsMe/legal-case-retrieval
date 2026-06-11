"""實驗 07：檢索消融評估（Recall@5 / MRR）。

對齊 docs/design_v1.md 第 5.2 節。

讀 eval.jsonl（06 產出的 query→relevant_jid 對），對每個 query 跑三種檢索策略，
計算命中指標，輸出消融對照表。

消融組別（皆用現有索引，不重建）：
  - Dense only：純 BGE-M3 語意向量
  - BM25 only：純稀疏（含法條號 + 案由）
  - Hybrid RRF：dense + sparse 融合

指標：
  - Recall@5：relevant_jid 是否落在 top-5
  - MRR@10：首個命中的倒數排名平均（top-10 內）

用法（home_wsl）：
    LCR_PROCESSED_DIR=/home/mrfrog/data/processed \\
    LCR_INDEX_DIR=/home/mrfrog/data/index \\
    PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \\
      ~/.local/bin/uv run python -u experiments/07_eval.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lcr.config import settings  # noqa: E402
from lcr.retrieval.searcher import Searcher  # noqa: E402


def load_evalset(path: Path) -> list[dict]:
    pairs = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            if line.strip():
                pairs.append(json.loads(line))
    return pairs


def recall_at_k(ranked_jids: list[str], relevant: str, k: int) -> float:
    return 1.0 if relevant in ranked_jids[:k] else 0.0


def reciprocal_rank(ranked_jids: list[str], relevant: str, k: int = 10) -> float:
    for i, jid in enumerate(ranked_jids[:k], 1):
        if jid == relevant:
            return 1.0 / i
    return 0.0


def evaluate(searcher: Searcher, pairs: list[dict], method: str) -> dict:
    """對一組 query 跑指定檢索法，回傳平均指標。"""
    r5_sum = 0.0
    mrr_sum = 0.0
    n = len(pairs)

    for p in pairs:
        q = p["query"]
        relevant = p["relevant_jid"]

        if method == "dense":
            results = searcher.dense_search(q, top_k=10)
        elif method == "bm25":
            results = searcher.sparse_search(q, top_k=10)
        elif method == "hybrid":
            results = searcher.hybrid_search(q, top_k=10)
        elif method == "hybrid_rerank":
            results = searcher.hybrid_rerank(q, top_k=10, candidate_n=20)
        else:
            raise ValueError(method)

        ranked = [jid for jid, _ in results]
        r5_sum += recall_at_k(ranked, relevant, 5)
        mrr_sum += reciprocal_rank(ranked, relevant, 10)

    return {
        "method": method,
        "n": n,
        "recall@5": r5_sum / n if n else 0.0,
        "mrr@10": mrr_sum / n if n else 0.0,
    }


def main() -> int:
    processed = settings.processed_dir
    index_dir = Path(os.environ.get("LCR_INDEX_DIR", str(processed).replace("processed", "index")))
    eval_path = processed / "eval.jsonl"

    if not eval_path.exists():
        print(f"[錯誤] 找不到 eval.jsonl：{eval_path}（先跑 06_make_evalset.py）")
        return 1

    pairs = load_evalset(eval_path)
    print(f"評估集：{len(pairs)} 個 (query, relevant_jid) 對\n")

    searcher = Searcher(
        chroma_dir=index_dir / "chroma",
        bm25_dir=index_dir / "bm25",
        use_gpu=True,
    )

    results = []
    for method in ("dense", "bm25", "hybrid", "hybrid_rerank"):
        print(f"跑 {method} ...")
        results.append(evaluate(searcher, pairs, method))

    # 輸出對照表
    print("\n" + "=" * 52)
    print(f"{'方法':<14}{'N':>6}{'Recall@5':>12}{'MRR@10':>12}")
    print("-" * 52)
    for r in results:
        print(
            f"{r['method']:<14}{r['n']:>6}"
            f"{r['recall@5']:>12.3f}{r['mrr@10']:>12.3f}"
        )
    print("=" * 52)

    # 寫結果 md
    try:
        lines = [
            "# 實驗 07：檢索消融評估結果\n",
            f"\n評估集：{len(pairs)} 對（eval.jsonl，gemini 生成口語 query）\n",
            "\n| 方法 | N | Recall@5 | MRR@10 |",
            "\n|------|---|----------|--------|",
        ]
        for r in results:
            lines.append(
                f"\n| {r['method']} | {r['n']} | {r['recall@5']:.3f} | {r['mrr@10']:.3f} |"
            )
        result_path = processed / "07_eval_result.md"
        result_path.write_text("".join(lines), encoding="utf-8")
        print(f"\n結果寫入：{result_path}")
    except Exception as e:
        print(f"[警告] 寫結果檔失敗：{e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
