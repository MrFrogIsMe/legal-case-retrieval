"""API v1 request/response schema（pydantic）。對應 docs/api_v1.md。"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, description="口語事由")
    top_k: int = Field(5, ge=1, le=20, description="回傳案例數")
    rewrite: bool = Field(True, description="是否 LLM 改寫口語 query（提升召回）")


class CaseItem(BaseModel):
    jid: str
    title: str
    court: str
    year: str
    articles: list[str]
    kind: str
    score: float


class SearchResponse(BaseModel):
    query: str
    rewritten: bool
    cases: list[CaseItem]
    disclaimer: str


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
