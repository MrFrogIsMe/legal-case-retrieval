"""API 端點測試（合約）：用 fake searcher/store 注入，不依賴 GPU/索引。

驗證 docs/api_v1.md 契約：response 結構、欄位、錯誤碼。
clarify 的 LLM 層被 monkeypatch 成固定回應，測規則分流而非 LLM 輸出。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import clarify as C
from app import main as M


class _FakeSearcher:
    """假檢索器：回固定 search_pipeline 結果。"""

    def search_pipeline(self, query, top_k=5, rewrite=True, **kw):
        return [
            {
                "jid": "A",
                "title": "過失傷害",
                "court": "臺灣宜蘭地方法院",
                "jyear": "106",
                "articles": "刑法 284 刑事訴訟法 303",
                "kind": "criminal",
                "score": 0.82,
            },
            {
                "jid": "B",
                "title": "過失傷害",
                "court": "臺灣台北地方法院",
                "jyear": "107",
                "articles": "刑法 284",
                "kind": "criminal",
                "score": 0.71,
            },
        ][:top_k]


class _FakeStore:
    """假資料倉。"""

    _ext = {
        "A": {"verdict": "公訴不受理", "sentence": None, "compensation": None,
              "subjective": "過失", "facts_summary": "被告駕車不慎擦撞前車，告訴人受傷後撤回告訴"},
        "B": {"verdict": "有罪", "sentence": "拘役30日", "compensation": 8000,
              "subjective": "過失", "facts_summary": "摘要B"},
    }
    _meta = {
        "A": {"title": "過失傷害", "court": "臺灣宜蘭地方法院", "jyear": "106",
              "jdate": "20171110", "kind": "criminal"},
        "B": {"title": "過失傷害", "court": "臺灣台北地方法院", "jyear": "107",
              "jdate": "20180101", "kind": "criminal"},
    }
    _seg = {
        "A": {"main": "公訴不受理。", "facts": "被告駕車不慎擦撞。",
              "reasoning": "核被告所為，係犯刑法第284條之罪，惟告訴人撤回告訴，"
                           "依刑事訴訟法第303條諭知不受理。"},
    }

    def get_extract(self, jid):
        return self._ext.get(jid, {})

    def get_meta(self, jid):
        return self._meta.get(jid, {})

    def get_segments(self, jid):
        return self._seg.get(jid, {"main": "", "facts": "", "reasoning": ""})

    def date_display(self, jid):
        return "民國 106 年 11 月 10 日"

    def has(self, jid):
        return jid in self._meta

    def stats(self, case_type=None, year_from=None, year_to=None):
        return {
            "total": 218,
            "verdict_distribution": [
                {"label": "不受理", "count": 131, "ratio": 0.6},
                {"label": "有罪", "count": 87, "ratio": 0.4},
            ],
            "compensation_range": {"min": 3000, "median": 8000, "max": 35000,
                                   "currency": "TWD"},
            "by_year": [{"year": 106, "count": 100}, {"year": 107, "count": 118}],
        }


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(M, "get_searcher", lambda: _FakeSearcher())
    monkeypatch.setattr(M, "get_store", lambda: _FakeStore())
    # health 端點直接走 get_searcher().chroma_collection → fake 沒有，回 not loaded（可接受）
    return TestClient(M.app, raise_server_exceptions=True)


# --- /search ---------------------------------------------------------------


def test_search_contract(client):
    r = client.post("/api/v1/search", json={"query": "我開車不小心撞傷人", "top_k": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "我開車不小心撞傷人"
    assert "analysis" in body and "stats" in body and "cases" in body
    assert body["disclaimer"]
    # case 完整欄位
    c0 = body["cases"][0]
    for k in ["jid", "title", "court", "facts_summary", "verdict",
              "cited_articles", "similarity", "confidence", "date_display"]:
        assert k in c0
    assert c0["cited_articles"] == ["刑法 284", "刑事訴訟法 303"]
    assert c0["facts_summary"].startswith("被告")
    # analysis
    assert body["analysis"]["case_type"] == "過失傷害"
    assert body["analysis"]["subjective"] == "過失"
    # stats
    assert body["stats"]["total_similar"] == 218
    assert body["stats"]["compensation_range"]["median"] == 8000


def test_search_empty_query_400(client):
    r = client.post("/api/v1/search", json={"query": "   "})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "INVALID_QUERY"


# --- /case/{jid} -----------------------------------------------------------


def test_case_detail_contract(client):
    r = client.get("/api/v1/case/A", params={"query": "我開車不小心撞傷人"})
    assert r.status_code == 200
    body = r.json()
    assert body["jid"] == "A"
    assert body["segments"]["reasoning"]
    assert body["extracted"]["verdict"] == "公訴不受理"
    # cited_articles 由 regex 從 reasoning 原文抽
    assert "刑法 284" in body["extracted"]["cited_articles"]
    # citations grounding：284 應 verified（原文有刑法第284條）
    art_cites = {c["article"]: c for c in body["citations"] if c["article"]}
    assert art_cites["刑法 284"]["verified"] is True
    # comparison（帶 query 才有）
    assert len(body["comparison"]) == 3
    assert body["confidence"]["overall"] in ("high", "medium", "low")


def test_case_detail_no_query_no_comparison(client):
    r = client.get("/api/v1/case/A")
    assert r.status_code == 200
    assert r.json()["comparison"] == []


def test_case_not_found_404(client):
    r = client.get("/api/v1/case/ZZZ")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "CASE_NOT_FOUND"


# --- /clarify --------------------------------------------------------------


def test_clarify_ready(client):
    r = client.post("/api/v1/clarify", json={
        "messages": [{"role": "user", "content": "我開車不小心撞傷人，對方有受傷"}]
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ready_to_search"] is True
    assert body["next_question"] is None


def test_clarify_needs_more(client, monkeypatch):
    monkeypatch.setattr(
        C, "next_question", lambda slot, hist: ("請問發生什麼事？", "需釐清事件類型")
    )
    r = client.post("/api/v1/clarify", json={
        "messages": [{"role": "user", "content": "我想查一些東西"}]
    })
    assert r.status_code == 200
    body = r.json()
    assert body["ready_to_search"] is False
    assert body["next_question"]
    assert "collected" in body


# --- /search/trace ---------------------------------------------------------


def test_trace_contract(client):
    r = client.post("/api/v1/search/trace", json={"query": "酒駕", "rewrite": True})
    assert r.status_code == 200
    trace = r.json()["trace"]
    assert len(trace) >= 4
    assert all("step" in s and "name" in s and "detail" in s for s in trace)


def test_trace_empty_query_400(client):
    r = client.post("/api/v1/search/trace", json={"query": ""})
    # pydantic min_length=1 → 422
    assert r.status_code in (400, 422)


# --- /stats ----------------------------------------------------------------


def test_stats_contract(client):
    r = client.get("/api/v1/stats", params={"case_type": "過失傷害"})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 218
    assert body["case_type"] == "過失傷害"
    assert body["verdict_distribution"][0]["label"] == "不受理"
    assert len(body["by_year"]) == 2
