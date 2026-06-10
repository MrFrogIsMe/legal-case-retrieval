"""lcr.retrieval (indexer & searcher) 整合測試。

使用臨時目錄，驗證雙路索引（BGE-M3 + BM25）建立與 RRF 融合檢索流程。
"""

from __future__ import annotations

import pytest
from lcr.retrieval.indexer import Indexer
from lcr.retrieval.searcher import Searcher, rrf_fusion

RECORDS = [
    {
        "jid": "TEST,101",
        "title": "過失傷害",
        "kind": "criminal",
        "court": "臺北地院",
        "jyear": "110",
        "facts": "被告甲○○駕車不慎擦撞前方告訴人車輛，致告訴人乙○○受傷。",
    },
    {
        "jid": "TEST,102",
        "title": "損害賠償",
        "kind": "civil",
        "court": "士林地院",
        "jyear": "111",
        "facts": "被告不慎擦撞原告停放路邊之貨車，致其後照鏡損壞，原告求償新台幣8,000元。",
    },
]


@pytest.fixture
def temp_dirs(tmp_path):
    chroma_dir = tmp_path / "chroma"
    bm25_dir = tmp_path / "bm25"
    return chroma_dir, bm25_dir


def test_indexer_and_searcher_flow(temp_dirs):
    chroma_dir, bm25_dir = temp_dirs

    # 1. 建立索引 (BGE-M3 設為使用 CPU 避免測試時佔用 GPU)
    # 本地測試使用最小模型或 mock 以節省時間，但因為 BGE-M3 是本地輕量，直接跑
    indexer = Indexer(
        chroma_dir=chroma_dir,
        bm25_dir=bm25_dir,
        use_gpu=False,
    )
    indexer.build_dense_index(RECORDS, collection_name="test_cases")
    indexer.build_sparse_index(RECORDS)

    assert (bm25_dir / "ids.json").exists()

    # 2. 檢索
    searcher = Searcher(
        chroma_dir=chroma_dir,
        bm25_dir=bm25_dir,
        collection_name="test_cases",
        use_gpu=False,
    )

    # 測試向量檢索
    dense_res = searcher.dense_search("車禍後照鏡壞了賠償", top_k=2)
    assert len(dense_res) >= 1
    # 最相關的應該是 TEST,102 (後照鏡損壞)
    assert dense_res[0][0] == "TEST,102"

    # 測試 BM25 檢索
    sparse_res = searcher.sparse_search("擦撞 貨車", top_k=2)
    assert len(sparse_res) >= 1
    assert sparse_res[0][0] == "TEST,102"


def test_rrf_fusion():
    dense = [("A", 0.9), ("B", 0.8), ("C", 0.7)]
    sparse = [("B", 15.0), ("A", 12.0), ("D", 8.0)]

    # RRF 融合
    # A 在 dense 排名 1，sparse 排名 2
    # B 在 dense 排名 2，sparse 排名 1
    # 兩者分數應極接近或相等
    fused = rrf_fusion(dense, sparse, k=60, top_n=2)
    assert len(fused) == 2
    assert fused[0][0] in ("A", "B")
