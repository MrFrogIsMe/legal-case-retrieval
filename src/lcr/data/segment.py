"""判決書 JFULL 結構切段。

依 experiments/probe_segments.py 的實測，台灣刑事判決書有兩種結構：
  - 通常判決：主文 → 事實(或犯罪事實) → 理由
  - 簡易判決：主文 → 事實及理由（合併段）

切段策略（以「主文」為穩定錨點，95% 出現）：
  1. 找出各標記在文中的位置
  2. 依出現順序，相鄰標記之間即為該段內容
  3. 「事實及理由」視為同時填入 facts 與 reasoning（合併段）
  4. 找不到任何中段/理由標記 → fallback：facts/reasoning 留空，標記 incomplete

回傳 Segments，含 is_complete 旗標供下游判斷品質。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 標記 → 行首獨立標題的 regex（容許全形/半形空白穿插，如「主  文」「事  實」）
_MARKER_NAMES = [
    "主文",
    "犯罪事實",
    "事實及理由",
    "事實",
    "理由",
]


def _build_marker_regex(name: str) -> re.Pattern[str]:
    # 標題多為獨立一行、字間有空白：[換行][空白]主[空白]文[空白][換行]
    spaced = r"[\u3000\s]*".join(list(name))
    return re.compile(r"[\r\n][\u3000\s]*" + spaced + r"[\u3000\s]*(?=[\r\n])")


_MARKER_RE = {name: _build_marker_regex(name) for name in _MARKER_NAMES}


@dataclass
class Segments:
    """切段結果。"""

    main: str = ""  # 主文
    facts: str = ""  # 事實 / 犯罪事實 / 事實及理由
    reasoning: str = ""  # 理由 / 事實及理由
    is_complete: bool = False  # 主文 + (事實或理由) 皆非空
    layout: str = "unknown"  # 結構類型：three_part / merged / partial / none


def _find_markers(text: str) -> list[tuple[int, int, str]]:
    """找出所有標記位置，回傳 (start, end, name)，依出現順序排序。

    注意：「事實及理由」與「事實」會重疊命中，需去重——
    若某位置已被較長的「事實及理由」涵蓋，則不再記「事實」。
    """
    hits: list[tuple[int, int, str]] = []
    for name, pat in _MARKER_RE.items():
        for m in pat.finditer(text):
            hits.append((m.start(), m.end(), name))
    hits.sort()

    # 去重：移除被前一個標記區間涵蓋的較短標記（事實 vs 事實及理由）
    deduped: list[tuple[int, int, str]] = []
    for h in hits:
        if deduped and h[0] < deduped[-1][1]:
            # 重疊：保留較長者（事實及理由 > 事實）
            if (h[1] - h[0]) > (deduped[-1][1] - deduped[-1][0]):
                deduped[-1] = h
            continue
        deduped.append(h)
    return deduped


def segment(jfull: str) -> Segments:
    """將判決全文切成主文/事實/理由三段。"""
    if not jfull:
        return Segments(layout="none")

    markers = _find_markers(jfull)
    if not markers:
        # 無任何標記，全文塞 reasoning 當 fallback
        return Segments(reasoning=jfull.strip(), layout="none")

    # 依序切出每個標記到下一個標記之間的內容
    spans: dict[str, str] = {}
    for i, (_start, end, name) in enumerate(markers):
        next_start = markers[i + 1][0] if i + 1 < len(markers) else len(jfull)
        content = jfull[end:next_start].strip()
        # 同名標記只取第一次（罕見重複）
        spans.setdefault(name, content)

    seg = Segments()
    seg.main = spans.get("主文", "")

    if "事實及理由" in spans:
        # 簡易判決合併段：同時作為 facts 與 reasoning
        merged = spans["事實及理由"]
        seg.facts = merged
        seg.reasoning = merged
        seg.layout = "merged"
    else:
        seg.facts = spans.get("犯罪事實", "") or spans.get("事實", "")
        seg.reasoning = spans.get("理由", "")
        if seg.facts and seg.reasoning:
            seg.layout = "three_part"
        elif seg.main and (seg.facts or seg.reasoning):
            seg.layout = "partial"
        else:
            seg.layout = "partial"

    seg.is_complete = bool(seg.main) and bool(seg.facts or seg.reasoning)
    return seg


def is_sheng_yi(*, jcase: str, title: str) -> bool:
    """是否為聲明異議類（程序案件，非事故實體判決，應排除）。

    依 probe 結果：JCASE 含『聲』或案由含『聲明異議』。
    """
    return "聲" in jcase or "聲明異議" in title
