"""regex 抽取層：法條、賠償金額、判決關鍵詞。

純規則，0 成本，適合大批量預處理。
設計依據：docs/data_design_v1.md 第 3 節，四層抽取架構第一層。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# 法條 regex（白名單法律名，避免貪婪比對抓進殘字／動詞）
# ---------------------------------------------------------------------------

# 台灣刑事判決常見法律名白名單（依字數長者優先，避免「社會秩序維護法」被「維護法」截斷）
_LAW_NAMES: tuple[str, ...] = (
    "中華民國刑法",
    "刑法",
    "刑事訴訟法",
    "少年事件處理法",
    "兒童及少年性剝削防制條例",
    "道路交通管理處罰條例",
    "毒品危害防制條例",
    "槍砲彈藥刀械管制條例",
    "社會秩序維護法",
    "家庭暴力防治法",
    "性騷擾防治法",
    "個人資料保護法",
    "著作權法",
    "商標法",
    "藥事法",
    "廢棄物清理法",
    "森林法",
    "稅捐稽徵法",
    "公職人員選舉罷免法",
    "貪污治罪條例",
    "組織犯罪防制條例",
    "洗錢防制法",
    "銀行法",
    "證券交易法",
    "公司法",
    "爆竹煙火管理條例",
    "行政罰法",
    "民法",
    "民事訴訟法",
)

# 依長度由長至短排序，確保「社會秩序維護法」優先於「維護法」「民法」等子字串
_LAW_NAMES_SORTED = sorted(_LAW_NAMES, key=len, reverse=True)
_LAW_ALT = "|".join(re.escape(n) for n in _LAW_NAMES_SORTED)

# 完整引用：<白名單法律名> 第 X 條 [之N] [第N項]
#   例：刑法第185條之4、社會秩序維護法第63條第1項、道路交通管理處罰條例第62條
_LAW_ARTICLE_RE = re.compile(
    r"(?P<law>" + _LAW_ALT + r")"
    r"第\s*(?P<article>\d+)\s*條"
    r"(?:\s*之\s*(?P<sub>\d+))?",
    re.UNICODE,
)

# 「同法第X條」：沿用上一個出現的法律名（理由段常見）
_SAME_LAW_RE = re.compile(r"同法第\s*(?P<article>\d+)\s*條(?:\s*之\s*(?P<sub>\d+))?")


def _fmt(law: str, article: str, sub: str | None) -> str:
    """格式化為「刑法 185-4」便於 BM25 精確比對。"""
    art = f"{article}-{sub}" if sub else article
    return f"{law} {art}"


def extract_articles(text: str) -> list[str]:
    """從文本抽取所有法條引用，回傳去重後排序清單。

    僅認白名單法律名（見 _LAW_NAMES），避免把動詞／殘字當法律名。
    格式：「刑法 185-4」「社會秩序維護法 63」（去「第/條」便於比對）。
    並處理「同法第X條」沿用前一個法律名。
    """
    results: set[str] = set()
    last_law: str | None = None

    # 依出現位置掃描，才能讓「同法」正確沿用前一個法律名
    matches = []
    for m in _LAW_ARTICLE_RE.finditer(text):
        matches.append((m.start(), "named", m))
    for m in _SAME_LAW_RE.finditer(text):
        matches.append((m.start(), "same", m))
    matches.sort(key=lambda x: x[0])

    for _pos, kind, m in matches:
        if kind == "named":
            law = m.group("law")
            last_law = law
            results.add(_fmt(law, m.group("article"), m.group("sub")))
        elif kind == "same" and last_law:
            results.add(_fmt(last_law, m.group("article"), m.group("sub")))

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
