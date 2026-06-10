"""Embedding 索引與 BM25 索引建立器。

使用 BAAI/bge-m3 做稠密向量（dense embedding），
搭配 BM25 做稀疏檢索（sparse retrieval），
結果存於 ChromaDB。

設計依據：docs/design_v1.md 第 5 節
"""

from __future__ import annotations

import json
from pathlib import Path

import bm25s
from FlagEmbedding import BGEM3FlagModel


class Indexer:
    """雙路索引建立器（BGE-M3 + BM25）。"""

    def __init__(
        self,
        chroma_dir: Path,
        bm25_dir: Path,
        model_id: str = "BAAI/bge-m3",
        use_gpu: bool = True,
    ):
        self.chroma_dir = chroma_dir
        self.bm25_dir = bm25_dir
        self.model_id = model_id
        self.use_gpu = use_gpu

        self._model = None

    @property
    def model(self) -> BGEM3FlagModel:
        """Lazy load BGE-M3 模型。"""
        if self._model is None:
            print(f"載入 BGE-M3 模型：{self.model_id} (use_gpu={self.use_gpu})")
            self._model = BGEM3FlagModel(
                self.model_id,
                use_fp16=self.use_gpu,
            )
        return self._model

    def build_dense_index(
        self,
        records: list[dict],
        collection_name: str = "legal_cases",
    ):
        """建立 ChromaDB 稠密向量索引。"""
        import chromadb

        print(f"初始化 ChromaDB (Persistent: {self.chroma_dir})")
        client = chromadb.PersistentClient(path=str(self.chroma_dir))

        # 取得或建立 collection
        # BGE-M3 預設維度為 1024
        collection = client.get_or_create_collection(
            name=collection_name,
            metadata={"hnsw:space": "cosine"},
        )

        print(f"計算 {len(records):,} 筆判決的事實段 Embedding...")
        # 選段策略（design_change_v1.md）：優先 facts -> reasoning -> title
        texts = []
        ids = []
        metadatas = []

        for r in records:
            text = r.get("facts") or r.get("reasoning") or r.get("title") or ""
            # BGE-M3 支援 8192 token，但事實段一般 < 2000 字，截取前 4000 字節省空間
            text = text[:4000].strip()
            if not text:
                continue

            texts.append(text)
            ids.append(r["jid"])
            # metadata 存少數過濾/展示欄位即可，大欄位（如摘要）放 sqlite，節省向量庫空間
            metadatas.append({
                "jid": r["jid"],
                "kind": r.get("kind", "criminal"),
                "court": r.get("court", ""),
                "jyear": r.get("jyear", ""),
            })

        # 分批 embed，防止 GPU 記憶體溢出
        batch_size = 128
        for i in range(0, len(texts), batch_size):
            b_texts = texts[i : i + batch_size]
            b_ids = ids[i : i + batch_size]
            b_metadatas = metadatas[i : i + batch_size]

            # BGE-M3 encode 回傳 dict，取 dense embedding
            embeddings = self.model.encode(
                b_texts,
                batch_size=batch_size,
                max_length=1024,  # 限制最大長度
            )["dense_vecs"]

            # 轉為 list[list[float]] 格式相容 ChromaDB
            embeddings_list = embeddings.tolist()

            collection.add(
                embeddings=embeddings_list,
                documents=b_texts,
                metadatas=b_metadatas,
                ids=b_ids,
            )
            print(f"  已索引：{min(i + batch_size, len(texts)):,}/{len(texts):,}")

        print("ChromaDB 稠密索引建立完成")

    def build_sparse_index(self, records: list[dict]):
        """建立 BM25s 稀疏文字索引（使用純 Python 極速實現）。"""
        import jieba

        print("建立 BM25 稀疏索引...")
        texts = []
        jids = []

        for r in records:
            text = r.get("facts") or r.get("reasoning") or r.get("title") or ""
            text = text[:4000].strip()
            if not text:
                continue

            # 使用結巴分詞
            words = list(jieba.cut(text))
            texts.append(words)
            jids.append(r["jid"])

        # 建立 BM25 模式
        retriever = bm25s.BM25(corpus=texts)
        retriever.index(bm25s.tokenize(texts, show_progress=False))

        # 儲存
        self.bm25_dir.mkdir(parents=True, exist_ok=True)
        retriever.save(str(self.bm25_dir), corpus=texts)

        # 儲存 ID 映射
        id_path = self.bm25_dir / "ids.json"
        with id_path.open("w", encoding="utf-8") as f:
            json.dump(jids, f, ensure_ascii=False)

        print(f"BM25 索引建立完成 → {self.bm25_dir}")
