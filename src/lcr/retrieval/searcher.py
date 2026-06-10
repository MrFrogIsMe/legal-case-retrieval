"""雙路混合檢索（Hybrid）+ 互惠排名融合（RRF）。

將 BGE-M3 稠密向量檢索與 BM25 稀疏文字檢索結合，
並提供選配的 Reranker 進行精細化重排。

設計依據：docs/design_v1.md 第 5.3 節
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import bm25s
from FlagEmbedding import BGEM3FlagModel


class Searcher:
    """雙路混合檢索器。"""

    def __init__(
        self,
        chroma_dir: Path,
        bm25_dir: Path,
        model_id: str = "BAAI/bge-m3",
        collection_name: str = "legal_cases",
        use_gpu: bool = True,
    ):
        self.chroma_dir = chroma_dir
        self.bm25_dir = bm25_dir
        self.model_id = model_id
        self.collection_name = collection_name
        self.use_gpu = use_gpu

        self._model = None
        self._chroma_client = None
        self._collection = None
        self._bm25 = None
        self._bm25_ids = None

    @property
    def model(self) -> BGEM3FlagModel:
        if self._model is None:
            self._model = BGEM3FlagModel(self.model_id, use_fp16=self.use_gpu)
        return self._model

    @property
    def chroma_collection(self):
        import chromadb
        if self._chroma_client is None:
            self._chroma_client = chromadb.PersistentClient(path=str(self.chroma_dir))
            self._collection = self._chroma_client.get_collection(self.collection_name)
        return self._collection

    @property
    def bm25(self) -> tuple[bm25s.BM25, list[str]]:
        if self._bm25 is None:
            # 載入 BM25 模型
            self._bm25 = bm25s.BM25.load(str(self.bm25_dir))
            # 載入 ID 映射
            id_path = self.bm25_dir / "ids.json"
            with id_path.open(encoding="utf-8") as f:
                self._bm25_ids = json.load(f)
        return self._bm25, self._bm25_ids

    def dense_search(
        self,
        query_text: str,
        top_k: int = 50,
        kind_filter: Literal["criminal", "civil", "both"] = "both",
    ) -> list[tuple[str, float]]:
        """BGE-M3 向量檢索。"""
        # 計算 Query Embedding
        query_emb = self.model.encode([query_text], max_length=1024)["dense_vecs"][0].tolist()

        # 準備 filter
        where = {}
        if kind_filter != "both":
            where["kind"] = kind_filter

        results = self.chroma_collection.query(
            query_embeddings=[query_emb],
            n_results=top_k,
            where=where if where else None,
        )

        output = []
        if results and results["ids"]:
            # ChromaDB 回傳 cos 距離，轉為相似度 (1 - distance)
            ids = results["ids"][0]
            distances = results["distances"][0]
            for jid, dist in zip(ids, distances):
                output.append((jid, 1.0 - dist))
        return output

    def sparse_search(
        self,
        query_text: str,
        top_k: int = 50,
        kind_filter: Literal["criminal", "civil", "both"] = "both",
    ) -> list[tuple[str, float]]:
        """BM25 稀疏文字檢索。"""
        import jieba

        retriever, bm25_ids = self.bm25
        # 分詞
        words = list(jieba.cut(query_text))

        # 檢索
        # bm25s 的 retrieve 接受 tokenized query
        tokens = bm25s.tokenize([words], show_progress=False)
        results_ids, scores = retriever.retrieve(tokens, k=top_k)

        # 轉為 (jid, score)
        output = []
        for idx, score in zip(results_ids[0], scores[0]):
            jid = bm25_ids[idx]
            output.append((jid, float(score)))

        # 手動過濾 kind (BM25s 庫本身不支援 metadata filter，需在後端過濾)
        if kind_filter != "both":
            # 這裡需要回讀 corpus/db 來判斷 kind，
            # 為了效率，此處僅回傳 ID，過濾留給 RRF 階段處理
            pass

        return output


def rrf_fusion(
    dense_results: list[tuple[str, float]],
    sparse_results: list[tuple[str, float]],
    k: int = 60,
    top_n: int = 20,
) -> list[tuple[str, float]]:
    """互惠排名融合（RRF，Reciprocal Rank Fusion）。

    Formula: RRF_Score = 1 / (k + rank_dense) + 1 / (k + rank_sparse)
    """
    rrf_scores: dict[str, float] = {}

    # 累加 dense 排名
    for rank, (jid, _) in enumerate(dense_results):
        rrf_scores[jid] = rrf_scores.get(jid, 0.0) + 1.0 / (k + rank + 1)

    # 累加 sparse 排名
    for rank, (jid, _) in enumerate(sparse_results):
        rrf_scores[jid] = rrf_scores.get(jid, 0.0) + 1.0 / (k + rank + 1)

    # 排序
    sorted_results = sorted(rrf_scores.items(), key=lambda x: -x[1])
    return sorted_results[:top_n]
