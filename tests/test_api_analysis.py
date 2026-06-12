"""app.analysis 純函式單元測試（不依賴大模型/網路）。"""

from __future__ import annotations

from app import analysis as A


def test_infer_subjective():
    assert A.infer_subjective("我不小心撞到人") == "過失"
    assert A.infer_subjective("他故意打我") == "故意"
    assert A.infer_subjective("發生了一件事") == "不確定"


def test_infer_articles_drunk_driving():
    arts = A.infer_articles("我朋友酒駕被抓")
    codes = [a["code"] for a in arts]
    assert "刑法 185-4" in codes


def test_infer_articles_dedup():
    # 酒駕 + 肇事逃逸 都映射 185-4，應去重
    arts = A.infer_articles("酒駕又肇事逃逸")
    codes = [a["code"] for a in arts]
    assert codes.count("刑法 185-4") == 1


def test_build_analysis_uses_top_title():
    cases = [{"title": "過失傷害"}, {"title": "過失傷害"}, {"title": "毀損"}]
    out = A.build_analysis("我開車不小心撞傷人", cases)
    assert out["case_type"] == "過失傷害"
    assert out["subjective"] == "過失"
    assert "criminal_vs_civil" in out


def test_confidence_for():
    assert A.confidence_for({"verdict": "有罪", "facts_summary": "x"}) == "high"
    assert A.confidence_for({"verdict": "有罪"}) == "medium"
    assert A.confidence_for({}) == "low"


def test_article_to_text_form():
    assert A._article_to_text_form("刑法 185-4") == "刑法第185條之4"
    assert A._article_to_text_form("刑法 354") == "刑法第354條"


def test_ground_citations_verified():
    segments = {
        "main": "主文：被告犯不能安全駕駛罪，處有期徒刑3月。",
        "facts": "",
        "reasoning": "核被告所為，係犯刑法第185條之4之罪。",
    }
    extract = {"verdict": "有罪"}
    cites = A.ground_citations(segments, extract, ["刑法 185-4"])
    # verdict + article 各一
    by_art = {c["article"]: c for c in cites if c["article"]}
    assert by_art["刑法 185-4"]["verified"] is True


def test_ground_citations_unverified_article():
    segments = {"main": "主文", "facts": "", "reasoning": "無相關法條"}
    cites = A.ground_citations(segments, {"verdict": "有罪"}, ["刑法 999"])
    by_art = {c["article"]: c for c in cites if c["article"]}
    assert by_art["刑法 999"]["verified"] is False


def test_ground_citations_verdict_label_not_literal_but_regex_matches():
    # verdict 標籤「有罪」未字面出現，但主文有「處有期徒刑」→ regex 重判為有罪 → verified
    segments = {"main": "被告甲犯傷害罪，處有期徒刑參月。", "facts": "", "reasoning": ""}
    cites = A.ground_citations(segments, {"verdict": "有罪"}, [])
    verdict_cite = [c for c in cites if c["article"] is None][0]
    assert verdict_cite["verified"] is True
    assert verdict_cite["source_segment"] == "main"


def test_ground_citations_verdict_mismatch_unverified():
    # 主文判出「無罪」但 LLM 標「有罪」→ 規則與 LLM 不一致 → 不驗證
    segments = {"main": "被告無罪。", "facts": "", "reasoning": ""}
    cites = A.ground_citations(segments, {"verdict": "有罪"}, [])
    verdict_cite = [c for c in cites if c["article"] is None][0]
    assert verdict_cite["verified"] is False


def test_build_comparison_match():
    rows = A.build_comparison(
        "我開車不小心撞傷人", {"subjective": "過失", "facts_summary": "被告駕車不慎撞傷告訴人受傷"}
    )
    aspects = {r["aspect"]: r for r in rows}
    assert aspects["主觀要素"]["match"] is True
    assert aspects["傷亡情形"]["match"] is True


def test_build_trace_with_rewrite():
    steps = A.build_trace("酒駕", [None] * 5, rewrite=True)
    names = [s["name"] for s in steps]
    assert "Query 改寫" in names
    assert "混合檢索" in names
    assert "重排" in names
    # step 編號連續
    assert [s["step"] for s in steps] == list(range(1, len(steps) + 1))


def test_build_trace_without_rewrite():
    steps = A.build_trace("酒駕", [None] * 5, rewrite=False)
    names = [s["name"] for s in steps]
    assert "Query 改寫" not in names


def test_check_collected_complete():
    msgs = [{"role": "user", "content": "我開車不小心撞傷人，對方有受傷"}]
    out = A.check_collected(msgs)
    assert out["collected"]["fault"] == "過失"
    assert out["collected"]["injury"] is True
    assert "incident_type" not in out["missing_slots"]


def test_check_collected_missing():
    msgs = [{"role": "user", "content": "發生了一件糾紛"}]
    out = A.check_collected(msgs)
    assert len(out["missing_slots"]) > 0
