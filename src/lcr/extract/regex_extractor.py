"""regex 抽取層：法條、賠償金額、判決關鍵詞。

純規則，0 成本，適合大批量預處理。
設計依據：docs/data_design_v1.md 第 3 節，四層抽取架構第一層。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 法條 regex
# ---------------------------------------------------------------------------

# 台灣法條引用格式：
#   刑法第284條  刑法第 284 條  民法第184條第1項
#   刑事訴訟法第303條  道路交通管理處罰條例第62條
_LAW_ARTICLE_RE = re.compile(
    r"(?:中華民國)?(?P<law>[^\s第，。；、「」【】\d]{2,20}?)"
    r"第\s*(?P<article>\d+(?:-\d+)?)\s*條"
    r"(?:第\s*(?P<para>\d+)\s*項)?",
    re.UNICODE,
)

# 主文中的法條（格式較簡短）
_SHORT_ARTICLE_RE = re.compile(
    r"(?:刑法|民法|刑事訴訟法|民事訴訟法|道路交通管理處罰條例"
    r"|著作權法|毒品危害防制條例|社會秩序維護法)"
    r"\s*第?\s*(\d+(?:-\d+)?)\s*條",
    re.UNICODE,
)


def extract_articles(text: str) -> list[str]:
    """從文本中抽取所有法條引用，回傳去重後的清單。

    格式：「刑法284」「民法184-1」（略去第/條方便比對）
    """
    results: set[str] = set()

    for m in _LAW_ARTICLE_RE.finditer(text):
        law = m.group("law").strip()
        article = m.group("article")
        # 過濾明顯噪音（法律名稱不應包含數字或超短）
        if len(law) < 2 or any(c.isdigit() for c in law):
            continue
        results.add(f"{law} {article}")

    for m in _SHORT_ARTICLE_RE.finditer(text):
        # 這個 pattern 的第一個 group 是 law name，需從 match 重組
        full = m.group(0)
        art = m.group(1)
        law_name = full[: full.index(art) - 1].replace("第", "").replace(" ", "").strip()
        if law_name:
            results.add(f"{law_name} {art}")

    return sorted(results)


# ---------------------------------------------------------------------------
# 賠償金額 regex
# ---------------------------------------------------------------------------

_AMOUNT_RE = re.compile(
    r"(?:賠償|給付|支付|連帶賠償|判給|應給付|應賠償)"
    r"[^新台幣元萬千百\d]*"
    r"(?:新台幣|新臺幣|台幣|臺幣)?\s*"
    r"(?P<amount>[\d,]+(?:\.\d+)?)\s*"
    r"(?:元|萬元|千元)",
    re.UNICODE,
)

_AMOUNT_NORMALIZE = re.compile(r"[,\s]")


def extract_compensation(text: str) -> int | None:
    """從文本抽取最大的賠償金額（元），無則回傳 None。

    多筆取最大值（通常是總額）。
    """
    amounts: list[float] = []
    for m in _AMOUNT_RE.finditer(text):
        raw = _AMOUNT_NORMALIZE.sub("", m.group("amount"))
        try:
            val = float(raw)
        except ValueError:
            continue
        # 處理「萬元」單位
        if "萬元" in m.group(0):
            val *= 10000
        amounts.append(val)

    return int(max(amounts)) if amounts else None


# ---------------------------------------------------------------------------
# 判決結果關鍵詞（主文段正則）
# ---------------------------------------------------------------------------

_VERDICT_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("不受理",   re.compile(r"公訴不受理|自訴不受理|不受理")),
    ("無罪",     re.compile(r"無罪")),
    ("免刑",     re.compile(r"免除其刑|免刑")),
    ("緩刑",     re.compile(r"緩刑\s*\d+\s*年|緩刑")),
    ("有罪",     re.compile(r"處有期徒刑|處拘役|處罰金|論罪科刑")),
    ("駁回",     re.compile(r"駁回")),
    ("和解",     re.compile(r"成立和解|調解成立")),
]


def extract_verdict(main_text: str) -> str | None:
    """從主文段抽取判決結果分類。

    依優先序比對，回傳第一個命中的類別；找不到回傳 None。
    """
    for label, pat in _VERDICT_PATTERNS:
        if pat.search(main_text):
            return label
    return None


# ---------------------------------------------------------------------------
# 刑度 regex
# ---------------------------------------------------------------------------

_NUM = r"[\d零一二三四五六七八九十百千壹貳參肆伍陸柒捌玖拾佰仟]+"

_SENTENCE_RE = re.compile(
    r"處(?P<sentence>"
    r"有期徒刑\s*" + _NUM + r"\s*[年月日]"
    r"|拘役\s*" + _NUM + r"\s*日"
    r"|罰金新?台?幣?\s*[\d,]+\s*元"
    r")",
    re.UNICODE,
)


def extract_sentence(main_text: str) -> str | None:
    """從主文段抽取刑度（第一筆）。"""
    m = _SENTENCE_RE.search(main_text)
    return m.group("sentence").strip() if m else None


# ---------------------------------------------------------------------------
# 整合入口
# ---------------------------------------------------------------------------


@dataclass
class RegexResult:
    """regex 層抽取結果。"""
    articles: list[str] = field(default_factory=list)
    compensation: int | None = None
    verdict: str | None = None
    sentence: str | None = None


def extract_all(
    *,
    main: str = "",
    facts: str = "",
    reasoning: str = "",
) -> RegexResult:
    """對三段文字執行 regex 全量抽取。

    Args:
        main: 主文段（判決結果、刑度）
        facts: 事實段（少用）
        reasoning: 理由段（法條最多）
    """
    full_text = "\n".join([main, facts, reasoning])
    return RegexResult(
        articles=extract_articles(full_text),
        compensation=extract_compensation(full_text),
        verdict=extract_verdict(main) if main else extract_verdict(full_text),
        sentence=extract_sentence(main) if main else extract_sentence(full_text),
    )
