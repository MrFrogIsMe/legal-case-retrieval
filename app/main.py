"""FastAPI 後端 v1：法律判決類案搜尋。

對應 docs/api_v1.md、docs/roadmap_v1.md 工程階段。
端點：/health、/search、/case/{jid}、/clarify、/search/trace、/stats。

資料策略（docs/api_v1.md 補完）：
  - 檢索走 Searcher.search_pipeline（rewrite + hybrid + rerank）。
  - 抽取欄位（verdict/sentence/compensation/facts_summary）與原文三段不在
    chroma metadata，改由 CaseStore 提供（extract 全量常駐 + segmented lazy 讀）。

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
from urllib.parse import unquote

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from app import analysis as A  # noqa: E402
from app import clarify as C  # noqa: E402
from app.schemas import (  # noqa: E402
    Analysis,
    CaseConfidence,
    CaseDetailResponse,
    CaseItem,
    Citation,
    ClarifyRequest,
    ClarifyResponse,
    ComparisonRow,
    CompensationRange,
    Extracted,
    HealthResponse,
    SearchRequest,
    SearchResponse,
    SearchStats,
    Segments,
    StatsResponse,
    TraceRequest,
    TraceResponse,
    TraceStep,
    VerdictBucket,
    YearBucket,
)
from lcr.config import settings  # noqa: E402
from lcr.extract.regex_extractor import extract_articles  # noqa: E402
from lcr.retrieval.case_store import CaseStore  # noqa: E402
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

# --- 單例（lazy）---
_searcher: Searcher | None = None
_store: CaseStore | None = None


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


def get_store() -> CaseStore:
    global _store
    if _store is None:
        _store = CaseStore().load()
    return _store


def _err(status: int, code: str, message: str, detail: str | None = None):
    return JSONResponse(
        status_code=status,
        content={"error": {"code": code, "message": message, "detail": detail}},
    )


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


def _case_item(r: dict, store: CaseStore) -> CaseItem:
    """檢索結果 dict + CaseStore 抽取欄位 → 完整 CaseItem。"""
    jid = r["jid"]
    ext = store.get_extract(jid)
    meta = store.get_meta(jid)
    return CaseItem(
        jid=jid,
        title=r.get("title") or meta.get("title", ""),
        court=r.get("court") or meta.get("court", ""),
        year=r.get("jyear") or meta.get("jyear", ""),
        date=meta.get("jdate", ""),
        date_display=store.date_display(jid),
        facts_summary=ext.get("facts_summary", ""),
        verdict=ext.get("verdict") or None,
        sentence=ext.get("sentence"),
        compensation=ext.get("compensation"),
        cited_articles=_pair_articles(r.get("articles", "")),
        similarity=r.get("score", 0.0),
        confidence=A.confidence_for(ext),
        kind=r.get("kind", "criminal"),
    )


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


@app.get("/api/v1/health", response_model=HealthResponse)
def health() -> HealthResponse:
    loaded = False
    count = 0
    try:
        col = get_searcher().chroma_collection
        count = col.count()
        loaded = count > 0
    except Exception:  # noqa: BLE001
        loaded = False
    return HealthResponse(
        status="ok", version="v1", index_loaded=loaded, case_count=count
    )


# ---------------------------------------------------------------------------
# /search
# ---------------------------------------------------------------------------


@app.post("/api/v1/search", response_model=SearchResponse)
def search(req: SearchRequest):
    if not req.query.strip():
        return _err(400, "INVALID_QUERY", "query 欄位不可為空")
    try:
        s = get_searcher()
        raw = s.search_pipeline(req.query, top_k=req.top_k, rewrite=req.rewrite)
    except Exception as e:  # noqa: BLE001
        return _err(500, "INTERNAL_ERROR", "檢索異常", str(e)[:200])

    store = get_store()
    cases = [_case_item(r, store) for r in raw]

    # analysis（query 推斷 + 檢索結果案由）
    analysis_dict = A.build_analysis(
        req.query, [{"title": c.title} for c in cases]
    )
    analysis = Analysis(**analysis_dict)

    # stats：以檢索結果最常見案由聚合（群體統計，呼應方向 C）
    has_case_type = analysis.case_type and "（" not in analysis.case_type
    case_type = analysis.case_type if has_case_type else None
    st = store.stats(case_type=case_type)
    stats = SearchStats(
        total_similar=st["total"],
        verdict_distribution=[VerdictBucket(**b) for b in st["verdict_distribution"]],
        compensation_range=(
            CompensationRange(**st["compensation_range"])
            if st["compensation_range"] else None
        ),
    )

    return SearchResponse(
        query=req.query,
        rewritten=req.rewrite,
        analysis=analysis,
        stats=stats,
        cases=cases,
        disclaimer=_DISCLAIMER,
    )


# ---------------------------------------------------------------------------
# /case/{jid}
# ---------------------------------------------------------------------------


@app.get("/api/v1/case/{jid:path}", response_model=CaseDetailResponse)
def case_detail(jid: str, query: str | None = None):
    jid = unquote(jid)
    store = get_store()
    if not store.has(jid):
        return _err(404, "CASE_NOT_FOUND", f"找不到判決：{jid}")

    meta = store.get_meta(jid)
    ext = store.get_extract(jid)
    segments = store.get_segments(jid)

    # cited_articles：以 regex 從原文精確抽（citation grounding 用）
    full = "\n".join([segments["main"], segments["facts"], segments["reasoning"]])
    cited = extract_articles(full) if full.strip() else []

    extracted = Extracted(
        facts_summary=ext.get("facts_summary", ""),
        verdict=ext.get("verdict") or None,
        sentence=ext.get("sentence"),
        compensation=ext.get("compensation"),
        subjective=ext.get("subjective", ""),
        cited_articles=cited,
    )

    citations = [Citation(**c) for c in A.ground_citations(segments, ext, cited)]

    comparison = []
    if query:
        comparison = [
            ComparisonRow(**row) for row in A.build_comparison(query, ext)
        ]

    conf_overall = A.confidence_for(ext)
    confidence = CaseConfidence(
        verdict="high" if ext.get("verdict") else "low",
        compensation="medium" if ext.get("compensation") else "low",
        overall=conf_overall,
    )

    return CaseDetailResponse(
        jid=jid,
        title=meta.get("title", ""),
        court=meta.get("court", ""),
        date_display=store.date_display(jid),
        segments=Segments(**segments),
        extracted=extracted,
        citations=citations,
        comparison=comparison,
        confidence=confidence,
    )


# ---------------------------------------------------------------------------
# /clarify
# ---------------------------------------------------------------------------


@app.post("/api/v1/clarify", response_model=ClarifyResponse)
def clarify(req: ClarifyRequest):
    messages = [{"role": m.role, "content": m.content} for m in req.messages]
    result = A.check_collected(messages)
    collected = result["collected"]
    missing = result["missing_slots"]

    if not missing:
        return ClarifyResponse(
            session_id=req.session_id,
            ready_to_search=True,
            next_question=None,
            reason="關鍵要件已蒐集足夠，可進行檢索",
            collected=collected,
        )

    slot = missing[0]
    history_text = " ".join(
        m.content for m in req.messages if m.role == "user"
    )
    q, reason = C.next_question(slot, history_text)
    return ClarifyResponse(
        session_id=req.session_id,
        ready_to_search=False,
        next_question=q,
        reason=reason,
        collected=collected,
    )


# ---------------------------------------------------------------------------
# /search/trace
# ---------------------------------------------------------------------------


@app.post("/api/v1/search/trace", response_model=TraceResponse)
def search_trace(req: TraceRequest):
    if not req.query.strip():
        return _err(400, "INVALID_QUERY", "query 欄位不可為空")
    # trace 只需反映管線步驟，不必真跑檢索（前端展開才打，省成本）
    steps = A.build_trace(req.query, [None] * req.top_k, req.rewrite)
    return TraceResponse(trace=[TraceStep(**s) for s in steps])


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------


@app.get("/api/v1/stats", response_model=StatsResponse)
def stats(
    case_type: str | None = None,
    year_from: int | None = None,
    year_to: int | None = None,
):
    store = get_store()
    st = store.stats(case_type=case_type, year_from=year_from, year_to=year_to)
    return StatsResponse(
        case_type=case_type,
        total=st["total"],
        verdict_distribution=[VerdictBucket(**b) for b in st["verdict_distribution"]],
        compensation_range=(
            CompensationRange(**st["compensation_range"])
            if st["compensation_range"] else None
        ),
        by_year=[YearBucket(**y) for y in st["by_year"]],
    )


# ---------------------------------------------------------------------------
# 靜態前端（web/）與 mock 資料
# ---------------------------------------------------------------------------
# 前端為純靜態頁（web/，組員 spaces-lalala 開發），same-origin 打 /api/v1。
# 掛在 API 路由之後，不影響任何 /api/v1 端點。
# - /web   → web/        （index.html + js/css，USE_MOCK=false 時直打上方端點）
# - /mock  → mock/       （USE_MOCK=true 時前端讀此處 JSON，離線展示用）
# 上線走 nginx 反代時，靜態檔可改由 nginx 直接 serve；此處保證單跑 uvicorn 也能用。
_REPO_ROOT = Path(__file__).resolve().parent.parent
_WEB_DIR = _REPO_ROOT / "web"
_MOCK_DIR = _REPO_ROOT / "mock"

if _MOCK_DIR.is_dir():
    app.mount("/mock", StaticFiles(directory=_MOCK_DIR), name="mock")
if _WEB_DIR.is_dir():
    app.mount("/web", StaticFiles(directory=_WEB_DIR, html=True), name="web")
