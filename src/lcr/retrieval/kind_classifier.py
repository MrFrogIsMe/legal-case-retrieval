"""搜尋時的 kind 判斷：從使用者事由推斷要搜刑事、民事、或兩者。

設計依據：docs/design_change_v1.md 第 3 節
"""

from __future__ import annotations

from typing import Literal

KindType = Literal["criminal", "civil", "both"]

_CRIMINAL_KW: tuple[str, ...] = (
    "罪", "起訴", "刑責", "判刑", "坐牢", "傷人", "竊盜", "詐騙",
    "毒品", "強盜", "殺人", "傷害", "公共危險",
)

_CIVIL_KW: tuple[str, ...] = (
    "賠償", "求償", "損失", "退款", "給付", "違約",
    "返還", "損害", "侵權", "補償",
)


def infer_kind(
    query: str,
    collected: dict | None = None,
) -> KindType:
    """從使用者事由推斷要搜哪種判決。

    DEPRECATED（design_change_v2）：專案已收斂為純刑事，搜尋永遠為
    criminal，本函式的 civil/both 分支已無實際用途，保留僅為相容既有測試。

    Args:
        query:     使用者口語事由
        collected: clarify 蒐集的結構化要件（可選）

    Returns:
        "criminal" | "civil" | "both"
    """
    if collected is None:
        collected = {}

    has_injury = collected.get("injury") is True
    pure_property = (
        collected.get("injury") is False
        and collected.get("damage") is not None
    )

    has_criminal_kw = any(kw in query for kw in _CRIMINAL_KW)
    has_civil_kw = any(kw in query for kw in _CIVIL_KW)

    if has_criminal_kw and not pure_property:
        return "criminal"
    if pure_property or (has_civil_kw and not has_criminal_kw):
        return "civil"
    if has_injury:
        return "both"
    return "both"
