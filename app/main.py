"""FastAPI 後端 v1：法律判決類案搜尋。

對應 docs/api_v1.md、docs/roadmap_v1.md 工程階段。
本階段實作核心端點：/health、/search（接 searcher.search_pipeline）。
clarify/trace/stats/case 詳情留待後續。

啟動（home_wsl，索引在 LCR_INDEX_DIR）：
    LCR_PROCESSED_DIR=/home/mrfrog/data/processed \\
    LCR_INDEX_DIR=/home/mrfrog/data/index \\
    PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \\
      uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from app.schemas import (  # noqa: E402
    CaseItem,
    HealthResponse,
    SearchRequest,
    SearchResponse,
)
from lcr.config import settings  # noqa: E402
from lcr.retrieval.searcher import Searcher  # noqa: E402

_DISCLAIMER = (
    "本系統為類案檢索工具，非法律建議。所列為地方法院一審刑事判決，"
    "過去案例不代表您的案件結果；純財損情況刑事上多不起訴，責任主要落在民事。"
)

app = FastAPI(title="Legal Case Retrieval API", version="v1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 開發期放寬；上線改填前端網域
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Searcher 單例（lazy）---
_searcher: Searcher | None = None


def _index_dir() -> Path:
    if os.environ.get("LCR_INDEX_DIR"):
        return Path(os.environ["LCR_INDEX_DIR"])
    return Path(str(settings.processed_dir).replace("processed", "index"))


def get_searcher() -> Searcher:
    global _searcher
    if _searcher is None:
        idx = _index_dir()
        _searcher = Searcher(
            chroma_dir=idx / "chroma",
            bm25_dir=idx / "bm25",
            use_gpu=True,
        )
    return _searcher


def _pair_articles(arts_str: str) -> list[str]:
    """metadata 的 "法名 條號 法名 條號" 還原為 ["法名 條號", ...]。"""
    toks = arts_str.split() if arts_str else []
    out, i = [], 0
    while i < len(toks) - 1:
        law, num = toks[i], toks[i + 1]
        if any(c.isdigit() for c in num):
            out.append(f"{law} {num}")
            i += 2
        else:
            i += 1
    return out


@app.get("/api/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """健康檢查 + 索引是否就緒。"""
    loaded = False
    count = 0
    try:
        col = get_searcher().chroma_collection
        count = col.count()
        loaded = count > 0
    except Exception:
        loaded = False
    return HealthResponse(
        status="ok", version="v1", index_loaded=loaded, case_count=count
    )


@app.post("/api/v1/search", response_model=SearchResponse)
def search(req: SearchRequest):
    """主搜尋：口語事由 → rewrite + hybrid + rerank → top-k 案例。"""
    if not req.query.strip():
        return JSONResponse(
            status_code=400,
            content={"error": {"code": "INVALID_QUERY",
                                "message": "query 欄位不可為空", "detail": None}},
        )
    try:
        s = get_searcher()
        raw = s.search_pipeline(
            req.query, top_k=req.top_k, rewrite=req.rewrite
        )
    except Exception as e:  # noqa: BLE001
        return JSONResponse(
            status_code=500,
            content={"error": {"code": "INTERNAL_ERROR",
                                "message": "檢索異常", "detail": str(e)[:200]}},
        )

    cases = [
        CaseItem(
            jid=r["jid"],
            title=r["title"],
            court=r["court"],
            year=str(r["jyear"]),
            articles=_pair_articles(r["articles"]),
            kind=r["kind"],
            score=r["score"],
        )
        for r in raw
    ]
    return SearchResponse(
        query=req.query, rewritten=req.rewrite, cases=cases, disclaimer=_DISCLAIMER
    )
