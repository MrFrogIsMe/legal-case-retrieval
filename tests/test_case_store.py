"""CaseStore 單元測試：用臨時 jsonl，不依賴 home_wsl 真資料。"""

from __future__ import annotations

import json

import pytest

from lcr.retrieval.case_store import CaseStore, _roc_date_display


@pytest.fixture
def store(tmp_path):
    corpus = tmp_path / "corpus.jsonl"
    seg = tmp_path / "segmented.jsonl"
    ext = tmp_path / "gpt_extract_all.jsonl"

    corpus.write_text(
        "\n".join(
            json.dumps(d, ensure_ascii=False)
            for d in [
                {"jid": "A", "title": "過失傷害", "court": "臺灣宜蘭地方法院",
                 "jyear": 106, "jdate": "20171110", "kind": "criminal"},
                {"jid": "B", "title": "過失傷害", "court": "臺灣台北地方法院",
                 "jyear": 107, "jdate": "20180101", "kind": "criminal"},
                {"jid": "C", "title": "毀損", "court": "臺灣台中地方法院",
                 "jyear": 106, "jdate": "20170505", "kind": "criminal"},
            ]
        ),
        encoding="utf-8",
    )
    seg.write_text(
        "\n".join(
            json.dumps(d, ensure_ascii=False)
            for d in [
                {"jid": "A", "main": "主文A", "facts": "事實A", "reasoning": "理由A"},
                {"jid": "B", "main": "主文B", "facts": "事實B", "reasoning": "理由B"},
                {"jid": "C", "main": "主文C", "facts": "事實C", "reasoning": "理由C"},
            ]
        ),
        encoding="utf-8",
    )
    ext.write_text(
        "\n".join(
            json.dumps(d, ensure_ascii=False)
            for d in [
                {"jid": "A", "gpt": {"verdict": "有罪", "sentence": "拘役30日",
                                     "compensation": 8000, "subjective": "過失",
                                     "facts_summary": "摘要A"}},
                {"jid": "B", "gpt": {"verdict": "不受理", "sentence": None,
                                     "compensation": None, "subjective": "過失",
                                     "facts_summary": "摘要B"}},
                {"jid": "C", "gpt": {"verdict": "有罪", "sentence": "罰金3000元",
                                     "compensation": 12000, "subjective": "故意",
                                     "facts_summary": "摘要C"}},
            ]
        ),
        encoding="utf-8",
    )
    return CaseStore(processed_dir=tmp_path).load()


def test_roc_date_display():
    assert _roc_date_display("20171110") == "民國 106 年 11 月 10 日"
    assert _roc_date_display("bad") == "bad"


def test_case_count(store):
    assert store.case_count == 3


def test_get_extract(store):
    e = store.get_extract("A")
    assert e["verdict"] == "有罪"
    assert e["compensation"] == 8000


def test_get_segments_lazy(store):
    seg = store.get_segments("B")
    assert seg["main"] == "主文B"
    assert seg["reasoning"] == "理由B"


def test_get_segments_missing(store):
    seg = store.get_segments("ZZZ")
    assert seg == {"main": "", "facts": "", "reasoning": ""}


def test_date_display(store):
    assert store.date_display("A") == "民國 106 年 11 月 10 日"


def test_has(store):
    assert store.has("A")
    assert not store.has("nope")


def test_stats_all(store):
    st = store.stats()
    assert st["total"] == 3
    labels = {b["label"]: b["count"] for b in st["verdict_distribution"]}
    assert labels["有罪"] == 2
    assert labels["不受理"] == 1
    # compensation: 8000, 12000 → median 10000
    assert st["compensation_range"]["min"] == 8000
    assert st["compensation_range"]["max"] == 12000


def test_stats_filtered_by_case_type(store):
    st = store.stats(case_type="毀損")
    assert st["total"] == 1


def test_stats_filtered_by_year(store):
    st = store.stats(year_from=107, year_to=107)
    assert st["total"] == 1


def test_stats_by_year(store):
    st = store.stats()
    years = {y["year"]: y["count"] for y in st["by_year"]}
    assert years[106] == 2
    assert years[107] == 1
