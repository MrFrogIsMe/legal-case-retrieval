"""實驗 11：寬鬆相關性評估（同案由 / 共享主要法條算相關）。

動機：實驗 07/10 顯示，在「single-relevant（只有原本那篇算對）」尺規下，
任何讓 query 更標準化的手段（HyDE 改寫）都會傷命中率——因為標準化讓 query
平均靠近一群相似判決。但「類案檢索」的真實目標是「找一批相似案件」，
非「找指定那篇」。故改用寬鬆相關性，使評估尺規匹配任務本質。

relevant 判定（任一成立即算命中）：
  - 候選與 ground-truth 同案由（title）
  - 候選與 ground-truth 共享至少一條「主要實體法條」（排除刑訴等程序法）

比較 baseline / A rewrite / B hyde / hybrid_rerank 在寬鬆尺規下的 Recall@5 / MRR@10。

用法（home_wsl）：
    LCR_PROCESSED_DIR=... LCR_INDEX_DIR=... PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \\
      ~/.local/bin/uv run python -u experiments/11_relaxed_eval.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lcr.config import settings  # noqa: E402
from lcr.retrieval.searcher import Searcher  # noqa: E402

# 程序法（不算「主要實體法條」，避免大家都引刑訴而誤判相關）
_PROC_LAWS = ("刑事訴訟法", "民事訴訟法", "行政罰法")


def main_articles(arts_str: str) -> set[str]:
    """從 metadata articles 字串取實體法條集合（去程序法）。

    articles 在 metadata 是空白分隔的 "法名 條號 法名 條號"，兩兩配對還原。
    """
    out = set()
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
    processed = settings.processed_dir
    index_dir = Path(os.environ.get("LCR_INDEX_DIR", str(processed).replace("processed", "index")))
    pairs = [json.loads(line) for line in (processed / "eval.jsonl").open(encoding="utf-8")]

    # 載入改寫快取（10 產生）
    rewrites = {}
    rc = processed / "hyde_rewrites.jsonl"
    if rc.exists():
        for line in rc.open(encoding="utf-8"):
            d = json.loads(line)
            rewrites[d["query"]] = d

    s = Searcher(
        chroma_dir=index_dir / "chroma",
        bm25_dir=index_dir / "bm25",
        use_gpu=True,
    )
    col = s.chroma_collection

    # 預取所有 relevant_jid 的 title/articles（ground truth 端）
    rel_jids = list({p["relevant_jid"] for p in pairs})
    gt = col.get(ids=rel_jids, include=["metadatas"])
    gt_meta = {m["jid"]: m for m in gt["metadatas"]}

    def is_relevant(cand_meta: dict, gt_jid: str) -> bool:
        if cand_meta["jid"] == gt_jid:
            return True
        g = gt_meta.get(gt_jid, {})
        # 同案由
        if cand_meta.get("title") and cand_meta["title"] == g.get("title"):
            return True
        # 共享主要法條
        ca = main_articles(cand_meta.get("articles", ""))
        ga = main_articles(g.get("articles", ""))
        return bool(ca & ga)

    def eval_variant(key: str | None, method: str = "dense"):
        r5s = mrrs = 0.0
        for p in pairs:
            q = p["query"] if key is None else rewrites.get(p["query"], {}).get(key, p["query"])
            if method == "dense":
                res = s.dense_search(q, top_k=10)
            elif method == "rerank":
                res = s.hybrid_rerank(q, top_k=10, candidate_n=20)
            cand_ids = [j for j, _ in res]
            # 撈候選 metadata
            if not cand_ids:
                continue
            cm = col.get(ids=cand_ids, include=["metadatas"])
            meta_map = {m["jid"]: m for m in cm["metadatas"]}
            rels = [is_relevant(meta_map.get(j, {"jid": j}), p["relevant_jid"]) for j in cand_ids]
            if any(rels[:5]):
                r5s += 1
            for i, ok in enumerate(rels[:10], 1):
                if ok:
                    mrrs += 1.0 / i
                    break
        n = len(pairs)
        return r5s / n, mrrs / n

    rows = []
    print("評估 baseline(dense) ...")
    rows.append(("baseline 口語 (dense)", *eval_variant(None, "dense")))
    print("評估 A rewrite(dense) ...")
    rows.append(("A rewrite (dense)", *eval_variant("A", "dense")))
    print("評估 B hyde(dense) ...")
    rows.append(("B hyde (dense)", *eval_variant("B", "dense")))
    print("評估 baseline(hybrid_rerank) ...")
    rows.append(("baseline (rerank)", *eval_variant(None, "rerank")))
    print("評估 A rewrite(rerank) ...")
    rows.append(("A rewrite (rerank)", *eval_variant("A", "rerank")))

    print("\n" + "=" * 60)
    print(f"{'策略 (寬鬆相關性)':<26}{'Recall@5':>14}{'MRR@10':>14}")
    print("-" * 60)
    for name, r5, mrr in rows:
        print(f"{name:<26}{r5:>14.3f}{mrr:>14.3f}")
    print("=" * 60)
    print("相關性定義：同案由 或 共享主要實體法條（排除刑訴/民訴程序法）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
