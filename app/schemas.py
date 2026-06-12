"""API v1 request/response schema（pydantic）。對應 docs/api_v1.md。"""
from __future__ import annotations

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 共用
# ---------------------------------------------------------------------------


class ArticleHint(BaseModel):
    code: str
    name: str
    note: str = ""


class CaseItem(BaseModel):
    """/search 案例卡片（對齊 api_v1.md 第 2 節 case 物件）。"""

    jid: str
    title: str
    court: str
    year: int | str
    date: str = ""
    date_display: str = ""
    facts_summary: str = ""
    verdict: str | None = None
    sentence: str | None = None
    compensation: int | None = None
    cited_articles: list[str] = Field(default_factory=list)
    similarity: float = 0.0
    confidence: str = "low"
    # 保留舊欄位相容（v1「只增不改名」承諾）
    kind: str = "criminal"


class Analysis(BaseModel):
    case_type: str = ""
    subjective: str = ""
    possible_articles: list[ArticleHint] = Field(default_factory=list)
    criminal_vs_civil: str = ""


class VerdictBucket(BaseModel):
    label: str
    count: int
    ratio: float


class CompensationRange(BaseModel):
    min: int
    median: int
    max: int
    currency: str = "TWD"


class SearchStats(BaseModel):
    total_similar: int = 0
    verdict_distribution: list[VerdictBucket] = Field(default_factory=list)
    compensation_range: CompensationRange | None = None


# ---------------------------------------------------------------------------
# /search
# ---------------------------------------------------------------------------


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="口語事由")
    top_k: int = Field(5, ge=1, le=20, description="回傳案例數")
    rewrite: bool = Field(True, description="是否 LLM 改寫口語 query（提升召回）")


class SearchResponse(BaseModel):
    query: str
    rewritten: bool
    analysis: Analysis
    stats: SearchStats
    cases: list[CaseItem]
    disclaimer: str


# ---------------------------------------------------------------------------
# /case/{jid}
# ---------------------------------------------------------------------------


class Segments(BaseModel):
    main: str = ""
    facts: str = ""
    reasoning: str = ""


class Extracted(BaseModel):
    facts_summary: str = ""
    verdict: str | None = None
    sentence: str | None = None
    compensation: int | None = None
    subjective: str = ""
    cited_articles: list[str] = Field(default_factory=list)


class Citation(BaseModel):
    claim: str
    source_segment: str
    source_text: str
    article: str | None = None
    verified: bool


class ComparisonRow(BaseModel):
    aspect: str
    user: str
    case: str
    match: bool


class CaseConfidence(BaseModel):
    verdict: str = "low"
    compensation: str = "low"
    overall: str = "low"


class CaseDetailResponse(BaseModel):
    jid: str
    title: str
    court: str
    date_display: str
    segments: Segments
    extracted: Extracted
    citations: list[Citation] = Field(default_factory=list)
    comparison: list[ComparisonRow] = Field(default_factory=list)
    confidence: CaseConfidence


# ---------------------------------------------------------------------------
# /clarify
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    role: str
    content: str


class ClarifyRequest(BaseModel):
    session_id: str | None = None
    messages: list[ChatMessage] = Field(..., min_length=1)


class ClarifyResponse(BaseModel):
    session_id: str | None = None
    ready_to_search: bool
    next_question: str | None = None
    reason: str = ""
    collected: dict


# ---------------------------------------------------------------------------
# /search/trace
# ---------------------------------------------------------------------------


class TraceRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(5, ge=1, le=20)
    rewrite: bool = True


class TraceStep(BaseModel):
    step: int
    name: str
    detail: str


class TraceResponse(BaseModel):
    trace: list[TraceStep]


# ---------------------------------------------------------------------------
# /stats
# ---------------------------------------------------------------------------


class YearBucket(BaseModel):
    year: int
    count: int


class StatsResponse(BaseModel):
    case_type: str | None = None
    total: int
    verdict_distribution: list[VerdictBucket] = Field(default_factory=list)
    compensation_range: CompensationRange | None = None
    by_year: list[YearBucket] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# /health & error
# ---------------------------------------------------------------------------


class HealthResponse(BaseModel):
    status: str
    version: str
    index_loaded: bool
    case_count: int


class ErrorBody(BaseModel):
    code: str
    message: str
    detail: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
