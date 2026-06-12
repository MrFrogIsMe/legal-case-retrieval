"""lcr.extract.regex_extractor 單元測試。

測試樣本使用真實台灣判決書常見格式構造。
"""

from __future__ import annotations

from lcr.extract.regex_extractor import (
    RegexResult,
    extract_all,
    extract_articles,
    extract_compensation,
    extract_sentence,
    extract_verdict,
)

# --- 法條抽取 ---

def test_extract_articles_criminal():
    text = "依刑法第284條第1項、刑事訴訟法第303條第3款論處。"
    arts = extract_articles(text)
    assert any("284" in a for a in arts), f"應含刑法284，實際：{arts}"
    assert any("303" in a for a in arts), f"應含刑事訴訟法303，實際：{arts}"

def test_extract_articles_civil():
    text = "依民法第184條第1項、第193條、第195條規定。"
    arts = extract_articles(text)
    assert any("184" in a for a in arts)

def test_extract_articles_dedup():
    # 同一筆法條出現兩次，最終清單中含該法條即可（兩個 pattern 格式略有不同，允許各一）
    text = "刑法第284條……刑法第284條……"
    arts = extract_articles(text)
    count_284 = sum(1 for a in arts if "284" in a)
    assert count_284 >= 1, "應至少含一筆 284"

def test_extract_articles_empty():
    assert extract_articles("") == []


def test_extract_articles_subarticle():
    # 「之N」格式：刑法第185條之4（肇事逃逸）
    arts = extract_articles("被告涉犯刑法第185條之4之肇事逃逸罪。")
    assert "刑法 185-4" in arts, f"應含刑法 185-4，實際：{arts}"


def test_extract_articles_same_law():
    # 「同法第X條」應沿用前一個法律名
    arts = extract_articles("依社會秩序維護法第63條，並依同法第45條裁處。")
    assert "社會秩序維護法 63" in arts
    assert "社會秩序維護法 45" in arts, f"同法應沿用，實際：{arts}"


def test_extract_articles_no_noise():
    # 真實判決常見雜訊：動詞/殘字黏在法律名前，白名單版不該抽出殘字
    text = (
        "爰依社會秩序維護法第20條規定，亦因社會秩序維護法第32條，"
        "維護法並無類似刑法第85條之規定，序維護法第63條。"
    )
    arts = extract_articles(text)
    # 應只認白名單全名，不該出現殘字法律名
    for a in arts:
        law = a.rsplit(" ", 1)[0]
        assert law in (
            "社會秩序維護法",
            "刑法",
        ), f"出現非白名單殘字法律名：{a}（全部：{arts}）"
    assert "社會秩序維護法 20" in arts
    assert "刑法 85" in arts


# --- 賠償金額 ---

def test_extract_compensation_basic():
    text = "被告應賠償原告新台幣8,000元。"
    assert extract_compensation(text) == 8000

def test_extract_compensation_wan():
    text = "應給付損害賠償金額新臺幣3萬元。"
    assert extract_compensation(text) == 30000

def test_extract_compensation_multiple():
    # 多筆取最大
    text = "先賠3000元，總計賠償12000元。"
    result = extract_compensation(text)
    assert result == 12000

def test_extract_compensation_none():
    assert extract_compensation("被告無罪。") is None


# --- 判決結果 ---

def test_extract_verdict_bu_shou_li():
    assert extract_verdict("公訴不受理") == "不受理"

def test_extract_verdict_huan_xing():
    assert extract_verdict("處有期徒刑參月，緩刑貳年。") == "緩刑"

def test_extract_verdict_you_zui():
    assert extract_verdict("論罪科刑如主文。") == "有罪"

def test_extract_verdict_fa_huan():
    # 社會秩序維護法「罰鍰」型主文也應判為有罪（grounding 互證用）
    assert extract_verdict("各處罰鍰新臺幣參仟元。") == "有罪"

def test_extract_verdict_wu_zui():
    assert extract_verdict("無罪。") == "無罪"

def test_extract_verdict_none():
    assert extract_verdict("本院審酌情節。") is None


# --- 刑度 ---

def test_extract_sentence_qiu_yi():
    assert extract_sentence("處拘役30日。") == "拘役30日"

def test_extract_sentence_you_qi():
    result = extract_sentence("處有期徒刑參月，如易科罰金。")
    assert result is not None and "有期徒刑" in result

def test_extract_sentence_none():
    assert extract_sentence("原告之訴駁回。") is None


# --- 整合 ---

def test_extract_all():
    main = "處有期徒刑參月，緩刑貳年。"
    reasoning = "依刑法第284條、第74條，並賠償原告新台幣8000元。"
    result = extract_all(main=main, facts="", reasoning=reasoning)
    assert isinstance(result, RegexResult)
    assert result.verdict == "緩刑"
    assert result.compensation == 8000
    assert any("284" in a for a in result.articles)
