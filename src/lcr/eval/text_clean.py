"""embed 文字清洗：移除檢索雜訊（人名/日期/法條/案號/金額/地址）。

目的：dense 語意向量應聚焦「行為事實」，而非人名、日期、法條號等
query 端絕不會出現的符號雜訊。清洗後再 embed，拉近口語 query 與文件的語意距離。

這是 docs/design_change_v3.md「dense 只放語意」的延伸：
原本 facts_summary 是「給人看的摘要」，含人名/法條/日期，作為檢索標的有雜訊。
本模組產生「檢索友善」版本供 dense embedding 消融對照。

設計依據：design_v1 第 8 節（法條不進 dense）、第 1.2 節（跨口語↔術語鴻溝）。
"""

from __future__ import annotations

import re

# 民國日期：(民國)106年9月29日13時10分 / 112年11月13日約22時
_DATE_RE = re.compile(
    r"(民國)?\d{2,3}年\d{1,2}月\d{1,2}日(\s*(約)?\d{1,2}時(許|\d{1,2}分)?)?"
)

# 法條（含串接「及第X條」「、第X條」）：社會秩序維護法第87條第2款及第45條第1項
_LAW_RE = re.compile(
    r"(依|按|違反|涉犯|犯|論以)?"
    r"[\u4e00-\u9fa5]{2,12}(法|條例|辦法)"
    r"第\d+條(之\d+)?(第\d+項)?(第\d+款)?"
    r"(([及、]|並依|或)第\d+條(之\d+)?(第\d+項)?(第\d+款)?)*"
)

# 金額：311,910元 / 新臺幣5000元 / 300元
_AMOUNT_RE = re.compile(r"(新?[臺台]?幣)?[\d,]+\s*元")

# 案號殘留：第30屆 等保留（屬事實），但純案號如 108年度交訴字第5號 去除
_CASENO_RE = re.compile(r"\d{2,3}年度[\u4e00-\u9fa5]{1,6}字第\d+號")

# 收尾：清掉孤立標點與重複連接詞
_DANGLING = re.compile(r"[，、；。]\s*(?=[，、；。])")
_DUP_YU = re.compile(r"於\s*於")
_MULTI_PUNCT = re.compile(r"[，、]{2,}")
_LEAD_PUNCT = re.compile(r"^[，、；。\s]+")


def clean_for_embedding(text: str) -> str:
    """清洗 facts_summary 供 dense embedding：去日期/法條/金額/案號。

    註：刻意「不」做人名移除——中文人名與常用字高度重疊（程/陳/方/林…），
    純 regex 必然誤傷（如「過程平和」→「過X和」），誤傷比雜訊更傷語意。
    人名對 BGE-M3 語意向量影響小，故保留。
    """
    if not text:
        return ""
    t = text
    t = _CASENO_RE.sub("", t)
    t = _LAW_RE.sub("", t)
    t = _DATE_RE.sub("", t)
    t = _AMOUNT_RE.sub("", t)
    # 收尾整理
    t = _DUP_YU.sub("於", t)
    t = _MULTI_PUNCT.sub("，", t)
    t = _DANGLING.sub("", t)
    t = _LEAD_PUNCT.sub("", t)
    t = re.sub(r"\s+", "", t)
    return t.strip()
