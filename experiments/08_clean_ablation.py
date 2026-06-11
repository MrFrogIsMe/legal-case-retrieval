"""消融：清洗 embed 文字 vs 原始，比較 dense Recall@5/MRR。

建一個「清洗後」的 dense collection（legal_cases_cleaned），與原始 legal_cases 對照。
用同一份 eval.jsonl 跑兩者，輸出 Recall@5/MRR 差異。

用法（home_wsl）：
    LCR_PROCESSED_DIR=/home/mrfrog/data/processed \\
    LCR_INDEX_DIR=/home/mrfrog/data/index \\
    PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \\
      ~/.local/bin/uv run python -u experiments/08_clean_ablation.py
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import importlib.util  # noqa: E402

from lcr.config import settings  # noqa: E402
from lcr.eval.text_clean import clean_for_embedding  # noqa: E402
from lcr.retrieval.indexer import Indexer  # noqa: E402

# 重用 05 的 load_records
_spec = importlib.util.spec_from_file_location(
    "bi05", str(Path(__file__).resolve().parent / "05_build_index.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def recall_mrr(ranked, relevant, k5=5, k10=10):
    r5 = 1.0 if relevant in ranked[:k5] else 0.0
    mrr = 0.0
    for i, j in enumerate(ranked[:k10], 1):
        if j == relevant:
            mrr = 1.0 / i
            break
    return r5, mrr


def main() -> int:
    processed = settings.processed_dir
    index_dir = Path(os.environ.get("LCR_INDEX_DIR", str(processed).replace("processed", "index")))

    records = _mod.load_records(
        processed / "corpus.jsonl",
        processed / "segmented.jsonl",
        processed / "gpt_extract_all.jsonl",
    )
    # 對每筆 facts 做清洗版（另存 facts_clean），原 facts 不動
    for r in records:
        r["facts_clean"] = clean_for_embedding(r.get("facts", ""))

    # 建清洗後 collection：暫時把 facts 換成 facts_clean 再 build
    indexer = Indexer(
        chroma_dir=index_dir / "chroma",
        bm25_dir=index_dir / "bm25",
        use_gpu=True,
    )
    cleaned_records = []
    for r in records:
        rr = dict(r)
        rr["facts"] = r["facts_clean"]  # dense 取 facts → 用清洗版
        cleaned_records.append(rr)

    print("=== 建清洗後 dense collection: legal_cases_cleaned ===")
    indexer.build_dense_index(
        cleaned_records, collection_name="legal_cases_cleaned",
        batch_size=128, recreate=True,
    )

    # 評估：對照 legal_cases（原始）vs legal_cases_cleaned（清洗）
    from lcr.retrieval.searcher import Searcher
    pairs = [json.loads(line) for line in (processed / "eval.jsonl").open(encoding="utf-8")]

    def eval_collection(coll_name):
        s = Searcher(
            chroma_dir=index_dir / "chroma",
            bm25_dir=index_dir / "bm25",
            collection_name=coll_name,
            use_gpu=True,
        )
        r5s = mrrs = 0.0
        for p in pairs:
            res = s.dense_search(p["query"], top_k=10)
            ranked = [j for j, _ in res]
            r5, mrr = recall_mrr(ranked, p["relevant_jid"])
            r5s += r5
            mrrs += mrr
        n = len(pairs)
        return r5s / n, mrrs / n

    print("\n評估原始 collection ...")
    o5, omrr = eval_collection("legal_cases")
    print("評估清洗 collection ...")
    c5, cmrr = eval_collection("legal_cases_cleaned")

    print("\n" + "=" * 56)
    print(f"{'dense embed':<22}{'Recall@5':>14}{'MRR@10':>14}")
    print("-" * 56)
    print(f"{'原始 facts_summary':<22}{o5:>14.3f}{omrr:>14.3f}")
    print(f"{'清洗後(去日期法條金額)':<22}{c5:>14.3f}{cmrr:>14.3f}")
    print("-" * 56)
    print(f"{'差異 Δ':<22}{c5-o5:>+14.3f}{cmrr-omrr:>+14.3f}")
    print("=" * 56)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
