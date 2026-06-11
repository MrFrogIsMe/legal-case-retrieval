"""Embedding 索引與 BM25 索引建立器。

使用 BAAI/bge-m3 做稠密向量（dense embedding），
搭配 BM25s 做稀疏檢索（sparse retrieval），
結果分別存於 ChromaDB（dense）和本地 BM25s 檔案（sparse）。

設計依據：docs/design_v1.md 第 5 節、docs/design_change_v1.md
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from FlagEmbedding import BGEM3FlagModel


def _dense_text(r: dict) -> str:
    """Dense（語意向量）用文字：純事實摘要，與口語 query 抽象層級一致。

    依據 design_v1 第 8 節：法條不進 dense embedding（符號非語意，會稀釋事實語意），
    法條改走 BM25 精確比對。
    """
    text = r.get("facts") or r.get("reasoning") or r.get("title") or ""
    return text[:4000].strip()


def _sparse_text(r: dict, include_articles: bool = True) -> str:
    """Sparse（BM25 精確比對）用文字：事實摘要 + 案由 [+ 法條號]。

    法條號（如「刑法 185-4」）是固定字串，最適合 BM25 token 比對，
    補上後才能對齊 NyayaRAG「檢索加入法條」的設計（design_v1 第 3.2 節 B-2）。

    include_articles=False：不摻法條，供「加法條 vs 不加法條」消融對照組使用。
    """
    parts = [
        r.get("facts") or r.get("reasoning") or "",
        r.get("title") or "",
    ]
    if include_articles:
        parts.append(" ".join(r.get("articles") or []))
    return " ".join(p for p in parts if p).strip()[:4000]


class Indexer:
    """雙路索引建立器（BGE-M3 + BM25s）。"""

    def __init__(
        self,
        chroma_dir: Path,
        bm25_dir: Path,
        model_id: str = "BAAI/bge-m3",
        use_gpu: bool = True,
    ):
        self.chroma_dir = Path(chroma_dir)
        self.bm25_dir = Path(bm25_dir)
        self.model_id = model_id
        self.use_gpu = use_gpu
        self._model: BGEM3FlagModel | None = None

    @property
    def model(self) -> BGEM3FlagModel:
        """Lazy load BGE-M3。"""
        from FlagEmbedding import BGEM3FlagModel
        if self._model is None:
            print(f"載入 BGE-M3：{self.model_id}  use_fp16={self.use_gpu}")
            self._model = BGEM3FlagModel(self.model_id, use_fp16=self.use_gpu)
        return self._model

    def build_dense_index(
        self,
        records: list[dict],
        collection_name: str = "legal_cases",
        batch_size: int = 128,
        recreate: bool = True,
    ) -> None:
        """建立 ChromaDB 稠密向量索引。

        recreate=True（預設）：建索引前先刪除同名舊 collection，避免上一批
        殘留資料（如已廢棄的民事筆）污染——get_or_create 不會清舊資料，
        upsert 只覆蓋同 jid，不同 jid 的舊筆會殘留。
        """
        import chromadb

        # 準備文本
        texts, ids, metadatas = [], [], []
        for r in records:
            text = _dense_text(r)
            if not text:
                continue
            texts.append(text)
            ids.append(r["jid"])
            metadatas.append({
                "jid": r["jid"],
                "kind": r.get("kind", "criminal"),
                "court": r.get("court", ""),
                "jyear": str(r.get("jyear", "")),
                "title": r.get("title", ""),
                # 法條清單（regex 抽，供前端顯示與 citation grounding）
                "articles": " ".join(r.get("articles") or []),
            })

        print(f"初始化 ChromaDB → {self.chroma_dir}")
        client = chromadb.PersistentClient(path=str(self.chroma_dir))
        if recreate:
            try:
                client.delete_collection(collection_name)
                print(f"  已刪除舊 collection「{collection_name}」（乾淨重建）")
            except Exception:
                pass  # 不存在則略過
        collection = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        # 分批 embed & upsert（防 OOM）
        print(f"計算 {len(texts):,} 筆 BGE-M3 embedding（batch={batch_size}）...")
        for i in range(0, len(texts), batch_size):
            b_texts = texts[i: i + batch_size]
            b_ids = ids[i: i + batch_size]
            b_meta = metadatas[i: i + batch_size]

            result = self.model.encode(
                b_texts, batch_size=batch_size, max_length=1024
            )
            embs = result["dense_vecs"].tolist()

            # upsert（冪等，重跑不重複）
            collection.upsert(
                embeddings=embs,
                documents=b_texts,
                metadatas=b_meta,
                ids=b_ids,
            )
            print(f"  dense: {min(i + batch_size, len(texts)):,}/{len(texts):,}")

        print(f"ChromaDB 稠密索引完成（collection: {collection_name}）")

    def build_sparse_index(
        self,
        records: list[dict],
        include_articles: bool = True,
    ) -> None:
        """建立 BM25s 稀疏索引（內建中文 tokenizer，不需 jieba）。

        include_articles=False：建不含法條的對照索引（消融用）。
        """
        import bm25s
        print(f"建立 BM25s 稀疏索引（含法條={include_articles}）...")
        corpus_texts = []
        jids = []

        for r in records:
            text = _sparse_text(r, include_articles=include_articles)
            if not text:
                continue
            corpus_texts.append(text)
            jids.append(r["jid"])

        # bm25s 內建 tokenizer（支援中文，word-level）
        corpus_tokens = bm25s.tokenize(corpus_texts, show_progress=False)

        retriever = bm25s.BM25()
        retriever.index(corpus_tokens)

        self.bm25_dir.mkdir(parents=True, exist_ok=True)
        retriever.save(str(self.bm25_dir), corpus=corpus_tokens)

        # 儲存 jid 對應表（idx → jid）
        with (self.bm25_dir / "ids.json").open("w", encoding="utf-8") as f:
            json.dump(jids, f, ensure_ascii=False)

        print(f"BM25s 稀疏索引完成 → {self.bm25_dir}（{len(jids):,} 筆）")
