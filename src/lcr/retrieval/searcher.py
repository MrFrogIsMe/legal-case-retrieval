"""雙路混合檢索（Hybrid）+ 互惠排名融合（RRF）。

將 BGE-M3 稠密向量檢索與 BM25s 稀疏文字檢索結合。
RRF 融合後選配 bge-reranker-v2-m3 精細化重排。

設計依據：docs/design_v1.md 第 5.3 節
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    import bm25s
    from FlagEmbedding import BGEM3FlagModel


class Searcher:
    """雙路混合檢索器（BGE-M3 dense + BM25s sparse + RRF）。"""

    def __init__(
        self,
        chroma_dir: Path,
        bm25_dir: Path,
        model_id: str = "BAAI/bge-m3",
        reranker_id: str = "BAAI/bge-reranker-v2-m3",
        collection_name: str = "legal_cases",
        use_gpu: bool = True,
    ):
        self.chroma_dir = Path(chroma_dir)
        self.bm25_dir = Path(bm25_dir)
        self.model_id = model_id
        self.reranker_id = reranker_id
        self.collection_name = collection_name
        self.use_gpu = use_gpu

        self._model: BGEM3FlagModel | None = None
        self._reranker = None
        self._chroma_client = None
        self._collection = None
        self._bm25: bm25s.BM25 | None = None
        self._bm25_ids: list[str] | None = None

    @property
    def model(self) -> BGEM3FlagModel:
        from FlagEmbedding import BGEM3FlagModel
        if self._model is None:
            self._model = BGEM3FlagModel(self.model_id, use_fp16=self.use_gpu)
        return self._model

    @property
    def reranker(self):
        """Lazy load bge-reranker-v2-m3。"""
        from FlagEmbedding import FlagReranker
        if self._reranker is None:
            self._reranker = FlagReranker(self.reranker_id, use_fp16=self.use_gpu)
        return self._reranker

    @property
    def chroma_collection(self):
        import chromadb
        if self._chroma_client is None:
            self._chroma_client = chromadb.PersistentClient(path=str(self.chroma_dir))
            self._collection = self._chroma_client.get_collection(self.collection_name)
        return self._collection

    def _load_bm25(self) -> tuple[bm25s.BM25, list[str]]:
        import bm25s
        if self._bm25 is None:
            # load_corpus=False：不需要 corpus，只需要 index 做 score 計算
            self._bm25 = bm25s.BM25.load(str(self.bm25_dir), load_corpus=False)
            with (self.bm25_dir / "ids.json").open(encoding="utf-8") as f:
                self._bm25_ids = json.load(f)
        return self._bm25, self._bm25_ids  # type: ignore[return-value]

    def dense_search(
        self,
        query_text: str,
        top_k: int = 50,
        kind_filter: Literal["criminal", "civil", "both"] = "criminal",
    ) -> list[tuple[str, float]]:
        """BGE-M3 向量檢索，回傳 [(jid, similarity), ...]。"""
        query_emb = self.model.encode(
            [query_text], max_length=1024
        )["dense_vecs"][0].tolist()

        where = {}
        if kind_filter != "both":
            where["kind"] = kind_filter

        results = self.chroma_collection.query(
            query_embeddings=[query_emb],
            n_results=top_k,
            where=where if where else None,
        )

        output: list[tuple[str, float]] = []
        if results and results["ids"]:
            for jid, dist in zip(results["ids"][0], results["distances"][0]):
                output.append((jid, 1.0 - dist))  # cosine dist → similarity
        return output

    def sparse_search(
        self,
        query_text: str,
        top_k: int = 50,
        kind_filter: Literal["criminal", "civil", "both"] = "criminal",
    ) -> list[tuple[str, float]]:
        """BM25s 稀疏文字檢索，回傳 [(jid, score), ...]。"""
        import bm25s
        retriever, bm25_ids = self._load_bm25()
        query_tokens = bm25s.tokenize([query_text], show_progress=False)
        results, scores = retriever.retrieve(query_tokens, k=min(top_k, len(bm25_ids)))

        output: list[tuple[str, float]] = []
        for idx, score in zip(results[0], scores[0]):
            # load_corpus=False 時，results 是 doc index（整數）
            jid = bm25_ids[int(idx)]
            output.append((jid, float(score)))
        return output

    def hybrid_search(
        self,
        query_text: str,
        top_k: int = 5,
        rrf_k: int = 60,
        kind_filter: Literal["criminal", "civil", "both"] = "criminal",
    ) -> list[tuple[str, float]]:
        """RRF 混合檢索（dense + sparse → 融合）。"""
        dense = self.dense_search(query_text, top_k=50, kind_filter=kind_filter)
        sparse = self.sparse_search(query_text, top_k=50, kind_filter=kind_filter)
        fused = rrf_fusion(dense, sparse, k=rrf_k, top_n=top_k)
        return fused

    def hybrid_rerank(
        self,
        query_text: str,
        top_k: int = 5,
        candidate_n: int = 20,
        rrf_k: int = 60,
        kind_filter: Literal["criminal", "civil", "both"] = "criminal",
    ) -> list[tuple[str, float]]:
        """Hybrid 取 candidate_n 候選 → bge-reranker 重排 → top_k。

        對齊 design_v1 第 3.2 節 D（reranking）。
        候選池靠 hybrid（RRF）召回，reranker 用 (query, document) 交互打分精排。
        """
        # 1. hybrid 召回候選
        candidates = self.hybrid_search(
            query_text, top_k=candidate_n, rrf_k=rrf_k, kind_filter=kind_filter
        )
        if not candidates:
            return []
        cand_jids = [jid for jid, _ in candidates]

        # 2. 從 ChromaDB 撈候選的 document 文字
        got = self.chroma_collection.get(ids=cand_jids, include=["documents"])
        doc_map = dict(zip(got["ids"], got["documents"]))

        # 3. reranker 對 (query, doc) 打分
        pairs = [[query_text, doc_map.get(jid, "")] for jid in cand_jids]
        scores = self.reranker.compute_score(pairs, normalize=True)
        if not isinstance(scores, list):
            scores = [scores]

        # 4. 依 rerank 分數排序取 top_k
        ranked = sorted(zip(cand_jids, scores), key=lambda x: -x[1])
        return ranked[:top_k]


def rrf_fusion(
    dense_results: list[tuple[str, float]],
    sparse_results: list[tuple[str, float]],
    k: int = 60,
    top_n: int = 20,
) -> list[tuple[str, float]]:
    """互惠排名融合（RRF）。

    RRF_Score(d) = Σ 1 / (k + rank(d))
    """
    rrf_scores: dict[str, float] = {}

    for rank, (jid, _) in enumerate(dense_results):
        rrf_scores[jid] = rrf_scores.get(jid, 0.0) + 1.0 / (k + rank + 1)

    for rank, (jid, _) in enumerate(sparse_results):
        rrf_scores[jid] = rrf_scores.get(jid, 0.0) + 1.0 / (k + rank + 1)

    return sorted(rrf_scores.items(), key=lambda x: -x[1])[:top_n]
