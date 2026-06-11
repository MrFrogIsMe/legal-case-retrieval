"""通用判決篩選邏輯：程序性案件排除 + 年份過濾。

設計依據：docs/data_design_v1.md
適用範圍：刑事 + 民事，通用類案檢索。

本模組只放純邏輯（可單元測試、工程階段可重用），不負責 I/O 遍歷。
遍歷與統計輸出在 experiments/03_build_corpus.py。
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 程序性案件排除規則（詳細說明見 docs/data_design_v1.md 第 3 節）
# ---------------------------------------------------------------------------

# 刑事：JCASE 含以下字元 → 程序性
_CRIMINAL_PROCEDURAL_JCASE_CHARS: frozenset[str] = frozenset(["聲"])

# 刑事：案由完全符合以下 → 程序性
_CRIMINAL_PROCEDURAL_TITLES: frozenset[str] = frozenset([
    "定應執行刑",
    "宣告沒收",
    "聲明異議",
])

# 民事：JCASE 完全符合以下 → 程序性
_CIVIL_PROCEDURAL_JCASES: frozenset[str] = frozenset([
    "司促",   # 支付命令（司法促請）
    "司票",   # 本票裁定
    "除",     # 除權判決
    "補",     # 補充判決
    "消債更", # 消費者債務更生
    "聲",     # 聲請事件
    "台聲",
    "台抗",   # 抗告
])

# 民事：案由含以下字串 → 程序性（純金錢催收或程序命令）
_CIVIL_PROCEDURAL_TITLE_PATTERNS: tuple[str, ...] = (
    "支付命令",
    "本票裁定",
    "除權判決",
    "公示催告",
    "公示送達",
    "確定訴訟費用",
    "更生事件",
    # 純金錢催收（給付 + 金融/電信商品）
    "給付信用卡",
    "給付簽帳卡",
    "給付電信費",
    "給付票款",
    "返還信用卡",
    "清償信用卡",
    "清償借款",
    "清償債務",
    "返還借款",
)

# 民事：即使命中上面的 pattern，只要同時含以下關鍵字 → 保留（有實體爭議）
_CIVIL_RETAIN_OVERRIDE: tuple[str, ...] = (
    "損害賠償",
    "侵權行為",
    "遷讓",
    "分割",
    "離婚",
    "監護",
    "扶養",
    "不當得利",
    "工程款",
    "貨款",
)


def is_criminal_procedural(jcase: str, title: str) -> bool:
    """刑事：是否為程序性案件（應排除）。"""
    if any(ch in jcase for ch in _CRIMINAL_PROCEDURAL_JCASE_CHARS):
        return True
    if title in _CRIMINAL_PROCEDURAL_TITLES:
        return True
    return False


def is_civil_procedural(jcase: str, title: str) -> bool:
    """民事：是否為程序性案件（應排除）。"""
    if jcase in _CIVIL_PROCEDURAL_JCASES:
        return True
    if any(pat in title for pat in _CIVIL_PROCEDURAL_TITLE_PATTERNS):
        # 若同時有實體爭議關鍵字，保留
        if any(kw in title for kw in _CIVIL_RETAIN_OVERRIDE):
            return False
        return True
    return False


def is_procedural(kind: str, jcase: str, title: str) -> bool:
    """統一入口：判斷任一類別的案件是否為程序性。

    Args:
        kind: "criminal" 或 "civil"
        jcase: JCASE 欄位
        title: JTITLE 欄位
    """
    if kind == "criminal":
        return is_criminal_procedural(jcase, title)
    elif kind == "civil":
        return is_civil_procedural(jcase, title)
    return False


# ---------------------------------------------------------------------------
# 年份過濾
# ---------------------------------------------------------------------------

def is_year_in_range(jyear: str, min_year: int = 105, max_year: int = 114) -> bool:
    """民國年是否在範圍內（預設 105-114，即 2016-2025 年）。"""
    try:
        y = int(jyear)
        return min_year <= y <= max_year
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# 法院類型
# ---------------------------------------------------------------------------

def is_district_court(court_name: str) -> bool:
    """是否為地方法院（含簡易庭）。排除最高法院、高等法院。"""
    return "地方法院" in court_name or "簡易庭" in court_name


# ---------------------------------------------------------------------------
# 子集篩選相容性邏輯（用於 01_subset_filter.py）
# ---------------------------------------------------------------------------

class FilterCriteria:
    def __init__(self, settings):
        self.target_title_keywords = settings.target_title_keywords
        self.target_case_prefixes = settings.target_case_prefixes
        self.district_court_only = settings.district_court_only

def criteria_from_settings(settings) -> FilterCriteria:
    return FilterCriteria(settings)

def should_keep(title: str, jcase: str, court_name: str, criteria: FilterCriteria) -> bool:
    # 1. 排除程序性
    if is_criminal_procedural(jcase, title):
        return False
    # 2. 地方法院過濾
    if criteria.district_court_only and not is_district_court(court_name):
        return False
    # 3. 案由關鍵字或案號前綴過濾
    has_title_kw = any(kw in title for kw in criteria.target_title_keywords)
    has_case_prefix = any(jcase.startswith(pre) for pre in criteria.target_case_prefixes)
    return has_title_kw or has_case_prefix
