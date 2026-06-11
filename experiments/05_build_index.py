"""實驗 05：建立雙路向量索引（BGE-M3 + BM25s）。

輸入：
  data/processed/segmented.jsonl   — 切段後的事實/主文/理由
  data/processed/gpt_extract.jsonl — GPT 要素抽取結果（摘要/verdict 等）
  data/processed/corpus.jsonl      — 元數據（kind/court/jyear）

輸出：
  data/index/chroma/     — ChromaDB 稠密向量索引（BGE-M3 1024-d）
  data/index/bm25/       — BM25s 稀疏文字索引

用法（home_wsl，建議 tmux）：
    LCR_DATASET_ROOT=... LCR_PROCESSED_DIR=/home/mrfrog/data/processed \\
    LCR_INDEX_DIR=/home/mrfrog/data/index \\
      uv run python experiments/05_build_index.py

備注：
  - BGE-M3 約 2.3GB，首次下載需時
  - 35k 筆 embedding 在 RTX 3060 Ti 8GB 約 30-60 分鐘
  - BM25s 建索引通常 < 2 分鐘
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lcr.config import settings  # noqa: E402
from lcr.extract.regex_extractor import extract_articles  # noqa: E402
from lcr.retrieval.indexer import Indexer  # noqa: E402


def load_records(
    corpus_path: Path,
    segmented_path: Path,
    extract_path: Path,
) -> list[dict]:
    """合併三份資料，以 jid 為 key。"""
    # 1. corpus（元數據）
    corpus: dict[str, dict] = {}
    with corpus_path.open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            corpus[d["jid"]] = d

    # 2. segmented（事實/主文/理由段）
    seg: dict[str, dict] = {}
    if segmented_path.exists():
        with segmented_path.open(encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                seg[d["jid"]] = d
        print(f"切段結果：{len(seg):,} 筆")
    else:
        print(f"[警告] segmented.jsonl 不存在：{segmented_path}，將使用空段落")

    # 3. GPT 抽取（事實摘要等）
    gpt: dict[str, dict] = {}
    if extract_path.exists():
        with extract_path.open(encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                if "error" not in d.get("gpt", {}):
                    gpt[d["jid"]] = d["gpt"]
        print(f"GPT 抽取結果：{len(gpt):,} 筆")
    else:
        print(f"[警告] gpt_extract.jsonl 不存在：{extract_path}，facts_summary 將為空")

    # 4. 合併
    records = []
    for jid, meta in corpus.items():
        s = seg.get(jid, {})
        g = gpt.get(jid, {})

        # 法條：regex 從原始切段文字抽（不靠 LLM，免費且精確），供 BM25 與 metadata
        full_text = "\n".join([
            s.get("main", ""), s.get("facts", ""), s.get("reasoning", "")
        ])
        articles = extract_articles(full_text) if full_text.strip() else []

        records.append({
            "jid": jid,
            "kind": meta.get("kind", "criminal"),
            "title": meta.get("title", ""),
            "court": meta.get("court", ""),
            "jyear": str(meta.get("jyear", "")),
            "jdate": meta.get("jdate", ""),
            # 選段：優先 facts_summary（GPT 摘要）> 原始 facts 段 > reasoning > title
            "facts": g.get("facts_summary") or s.get("facts") or s.get("reasoning") or "",
            "reasoning": s.get("reasoning", ""),
            "main": s.get("main", ""),
            # 法條（regex 抽）
            "articles": articles,
            # 抽取欄位
            "verdict": g.get("verdict", ""),
            "sentence": g.get("sentence"),
            "compensation": g.get("compensation"),
            "subjective": g.get("subjective", ""),
            "dispute_type": g.get("dispute_type", ""),
        })

    print(f"合併後語料：{len(records):,} 筆")
    return records


def main() -> int:
    processed = settings.processed_dir
    index_dir = Path(str(processed).replace("processed", "index"))
    # 支援 LCR_INDEX_DIR 覆寫
    import os
    if os.environ.get("LCR_INDEX_DIR"):
        index_dir = Path(os.environ["LCR_INDEX_DIR"])

    chroma_dir = index_dir / "chroma"
    bm25_dir = index_dir / "bm25"

    corpus_path = processed / "corpus.jsonl"
    segmented_path = processed / "segmented.jsonl"
    # 優先用全量 GPT 抽取，fallback 到舊版測試結果
    extract_path = processed / "gpt_extract_all.jsonl"
    if not extract_path.exists():
        extract_path = processed / "gpt_extract.jsonl"
        if extract_path.exists():
            print(f"[警告] gpt_extract_all.jsonl 不存在，使用 {extract_path}")

    if not corpus_path.exists():
        print(f"[錯誤] 找不到 corpus.jsonl：{corpus_path}")
        return 1

    # 載入並合併
    records = load_records(corpus_path, segmented_path, extract_path)

    # 建立索引
    indexer = Indexer(
        chroma_dir=chroma_dir,
        bm25_dir=bm25_dir,
        use_gpu=True,
    )

    print("\n=== Phase 1：BM25s 稀疏索引 ===")
    indexer.build_sparse_index(records)

    print("\n=== Phase 2：BGE-M3 稠密索引 ===")
    # 8GB 顯存（RTX 3060 Ti）跑 BGE-M3 fp16，實測 batch=32 僅用 2.6GB、batch=128
    # 仍安全，較大 batch 可減少 kernel overhead 加速。OOM 時用 LCR_EMBED_BATCH 調小。
    embed_batch = int(os.environ.get("LCR_EMBED_BATCH", "128"))
    indexer.build_dense_index(
        records, collection_name="legal_cases", batch_size=embed_batch
    )

    print("\n=== 完成 ===")
    print(f"  ChromaDB：{chroma_dir}")
    print(f"  BM25s：   {bm25_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
