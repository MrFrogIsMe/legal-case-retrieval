"""API 業務邏輯純函式：法律分析、citation grounding、對比表、推理鏈、要件檢查。

全部設計為「不依賴大模型 / 不依賴網路」的純函式（clarify 的 LLM 判斷除外，
另放 clarify_llm），方便獨立單元測試當合約。

對應 docs/api_v1.md：
  - build_analysis      → /search 的 analysis 區塊
  - confidence_for      → case 抽取信心 high/medium/low
  - ground_citations    → /case 的 citations（驗證法條/結論是否真在原文）
  - build_comparison    → /case 的 comparison（你的情況 vs 本案）
  - build_trace         → /search/trace 推理鏈（模板，非每次 LLM）
  - check_collected     → /clarify 規則層：判斷缺哪些要件
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

# ---------------------------------------------------------------------------
# 法條知識
# ---------------------------------------------------------------------------
#
# 法條推斷採「資料驅動為主、內建白名單為輔」：
#   1. 主來源：app/data/legal_terms.json（experiments/09 從 81k 判決抽出的
#      案由→top_articles→top_terms 術語表）。用 top_terms 命中案由 → 回該案由
#      高頻法條（資料驅動，反映真實判決分布）。
#   2. 退路：命不中術語表（或檔案缺）時退回 _FALLBACK_HINTS（手寫最小白名單），
#      確保無資料環境（CI / 本機測試）仍可推斷、且不需外部檔。
#
# 法條 code 的可讀名稱/註記由 _ARTICLE_META 補（術語表只有 code）。

_TERMS_PATH = Path(__file__).resolve().parent / "data" / "legal_terms.json"

# 常見法條 code → (name, note)，給資料驅動結果補可讀說明（找不到則留空）
_ARTICLE_META: dict[str, tuple[str, str]] = {
    "刑法 185-3": ("不能安全駕駛罪", "公共危險，吐氣酒精濃度達每公升0.25毫克以上即成立"),
    "刑法 185-4": ("肇事逃逸罪", "駕駛動力交通工具發生事故致人傷亡而逃逸"),
    "刑法 284": ("過失傷害罪", "告訴乃論，撤回告訴可不受理"),
    "刑法 276": ("過失致死罪", "非告訴乃論"),
    "刑法 277": ("傷害罪", "告訴乃論"),
    "刑法 354": ("毀損罪", "須故意，過失毀損不罰"),
    "刑法 320": ("竊盜罪", "意圖為自己或第三人不法所有"),
    "刑法 339": ("詐欺罪", "以詐術使人陷於錯誤而交付財物"),
    "毒品危害防制條例 10": ("施用毒品罪", "依毒品分級量刑"),
    "社會秩序維護法 87": ("妨害安寧秩序", "互相鬥毆等，處罰鍰"),
    "社會秩序維護法 45": ("裁處程序", "由簡易庭裁定"),
}

# 退路白名單：關鍵詞 → 法條 code（命不中術語表時用，zero-data fallback）
_FALLBACK_HINTS: list[tuple[tuple[str, ...], tuple[str, ...]]] = [
    (("酒駕", "酒後駕車", "酒後", "喝酒", "喝了酒", "飲酒", "不能安全駕駛",
      "吐氣", "酒精濃度"), ("刑法 185-3",)),
    (("肇事逃逸", "肇逃"), ("刑法 185-4",)),
    (("過失傷害", "撞傷", "受傷", "車禍"), ("刑法 284",)),
    (("過失致死", "致死", "死亡"), ("刑法 276",)),
    (("毀損", "弄壞", "砸", "破壞"), ("刑法 354",)),
    (("竊盜", "偷", "行竊"), ("刑法 320",)),
    (("詐欺", "詐騙", "騙"), ("刑法 339",)),
    (("傷害", "毆打", "打人", "鬥毆"), ("刑法 277",)),
    (("毒品", "施用", "持有毒品"), ("毒品危害防制條例 10",)),
]

# 主觀要素關鍵詞
_INTENT_HINTS = ("故意", "蓄意", "明知", "基於")
_NEGLIGENCE_HINTS = ("過失", "不慎", "不小心", "未注意", "疏忽")

# 程序法（非實體罪名，對使用者無意義，從 analysis 法條建議中過濾）
_PROC_LAWS = ("刑事訴訟法", "民事訴訟法", "行政罰法")


def _is_substantive(code: str) -> bool:
    """是否為實體法條（排除刑訴/民訴等程序法）。"""
    return not any(p in code for p in _PROC_LAWS)


@lru_cache(maxsize=1)
def _load_terms() -> dict:
    """載入資料驅動術語表（案由→top_articles/top_terms）。缺檔則回空 dict。"""
    if _TERMS_PATH.exists():
        try:
            return json.loads(_TERMS_PATH.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001  壞檔不阻斷，退回 fallback
            return {}
    return {}


def _article_dict(code: str) -> dict:
    """法條 code → {code, name, note}（name/note 取自 _ARTICLE_META）。"""
    name, note = _ARTICLE_META.get(code, ("", ""))
    return {"code": code, "name": name, "note": note}


def _norm_code(code: str) -> str:
    """正規化法條 code 供去重：「中華民國刑法 339」與「刑法 339」視為同條。"""
    return code.replace("中華民國刑法", "刑法").strip()


def infer_subjective(query: str) -> str:
    """從口語事由粗略推主觀要素（故意/過失/不確定）。"""
    if any(k in query for k in _NEGLIGENCE_HINTS):
        return "過失"
    if any(k in query for k in _INTENT_HINTS):
        return "故意"
    return "不確定"


def _match_case_type(query: str) -> tuple[str, dict] | tuple[None, None]:
    """用術語表 top_terms + 案由名比對 query，回最佳命中案由與其資料。

    純字串比對（不呼叫 LLM）；命中數相同時取資料筆數（count）較多者。
    """
    terms = _load_terms()
    best, best_hit, best_count = None, 0, 0
    for title, info in terms.items():
        hit = sum(1 for t in info.get("top_terms", []) if t and t in query)
        if any(c in query for c in title):
            hit += 1
        cnt = info.get("count", 0)
        if hit > best_hit or (hit == best_hit and hit > 0 and cnt > best_count):
            best, best_hit, best_count = title, hit, cnt
    if best and best_hit > 0:
        return best, terms[best]
    return None, None


def infer_articles(query: str, top_n: int = 3) -> list[dict]:
    """從口語事由推斷可能法條（資料驅動為主，白名單為輔）。

    1. 術語表命中案由 → 取該案由 top_articles 前 top_n（資料驅動）。
    2. 命不中 → 退回 _FALLBACK_HINTS 關鍵詞比對。
    回 [{code, name, note}, ...]，去重保序。
    """
    out: list[dict] = []
    seen: set[str] = set()

    _title, info = _match_case_type(query)
    if info:
        for code in info.get("top_articles", []):
            norm = _norm_code(code)
            if code and _is_substantive(code) and norm not in seen:
                out.append(_article_dict(norm))
                seen.add(norm)
            if len(out) >= top_n:
                break

    if not out:  # 退路：白名單關鍵詞
        for keywords, codes in _FALLBACK_HINTS:
            if any(k in query for k in keywords):
                for code in codes:
                    norm = _norm_code(code)
                    if norm not in seen:
                        out.append(_article_dict(norm))
                        seen.add(norm)
    return out


def build_analysis(query: str, cases: list[dict]) -> dict:
    """組 /search 的 analysis 區塊（法條/過失故意/刑民）。

    case_type 取檢索結果中最常見的案由（title）作為佐證，
    法條結合 query 推斷 + 檢索結果引用的法條。
    """
    subjective = infer_subjective(query)
    possible = infer_articles(query)

    # case_type：用檢索 top 案由
    titles = [c.get("title", "") for c in cases if c.get("title")]
    case_type = ""
    if titles:
        from collections import Counter

        case_type = Counter(titles).most_common(1)[0][0]

    # 刑民提示
    criminal_vs_civil = (
        "本系統僅收地方法院一審刑事判決。純財物損壞刑事多不起訴，"
        "責任主要落在民事賠償；涉人身傷亡則可能成立過失傷害/致死等刑責。"
    )
    return {
        "case_type": case_type or "（依檢索結果判斷）",
        "subjective": subjective,
        "possible_articles": possible,
        "criminal_vs_civil": criminal_vs_civil,
    }


# ---------------------------------------------------------------------------
# 抽取信心分數
# ---------------------------------------------------------------------------


def confidence_for(extract: dict) -> str:
    """依抽取結果完整度給 high/medium/low。

    verdict + facts_summary 齊全 → high；缺一 → medium；都缺 → low。
    """
    has_verdict = bool(extract.get("verdict"))
    has_summary = bool(extract.get("facts_summary"))
    if has_verdict and has_summary:
        return "high"
    if has_verdict or has_summary:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# Citation grounding：驗證結論/法條是否真在原文
# ---------------------------------------------------------------------------


def _find_snippet(text: str, needle: str, ctx: int = 40) -> str | None:
    """在 text 找 needle，回傳前後 ctx 字的片段；找不到回 None。"""
    idx = text.find(needle)
    if idx < 0:
        return None
    start = max(0, idx - ctx)
    end = min(len(text), idx + len(needle) + ctx)
    return text[start:end].replace("\n", " ").strip()


def _article_to_text_form(article: str) -> str:
    """「刑法 185-4」→ 用於原文比對的形式「刑法第185條之4」。"""
    parts = article.split()
    if len(parts) != 2:
        return article
    law, num = parts
    if "-" in num:
        a, sub = num.split("-", 1)
        return f"{law}第{a}條之{sub}"
    return f"{law}第{num}條"


def ground_citations(
    segments: dict, extract: dict, cited_articles: list[str]
) -> list[dict]:
    """為每個結論/法條找原文依據，標記 verified。

    1. verdict：在 main 段找該判決關鍵詞。
    2. 每個 cited_article：在三段全文找「法名第X條(之N)」是否出現。
    """
    full = "\n".join(
        [segments.get("main", ""), segments.get("facts", ""), segments.get("reasoning", "")]
    )
    citations: list[dict] = []

    verdict = extract.get("verdict")
    if verdict:
        main = segments.get("main", "")
        # verdict 是 LLM 歸納的分類標籤，未必字面出現於原文。
        # 改用 regex 從主文段獨立重判：規則與 LLM 結果一致 → 視為已驗證（互證）。
        from lcr.extract.regex_extractor import extract_verdict

        regex_verdict = extract_verdict(main) if main else None
        verified = regex_verdict is not None and regex_verdict == verdict
        # 片段：取主文段開頭供前端顯示判決結果出處
        snip = (main[:120].replace("\n", " ").strip()) if main else ""
        claim = f"本案判決結果為「{verdict}」（規則自主文段重判：{regex_verdict or '未判出'}）"
        citations.append({
            "claim": claim,
            "source_segment": "main",
            "source_text": snip,
            "article": None,
            "verified": verified,
        })

    for art in cited_articles:
        text_form = _article_to_text_form(art)
        snip = _find_snippet(full, text_form)
        # 退一步用 regex 形式「法名」+「條號」分別比對
        verified = snip is not None
        if not verified:
            law = art.split()[0] if art.split() else art
            num = art.split()[-1].split("-")[0] if art.split() else ""
            if law in full and num and f"第{num}條" in full:
                verified = True
                snip = _find_snippet(full, f"第{num}條")
        citations.append({
            "claim": f"本案引用 {art}",
            "source_segment": "reasoning",
            "source_text": snip or "",
            "article": art,
            "verified": verified,
        })
    return citations


# ---------------------------------------------------------------------------
# 對比表：你的情況 vs 本案
# ---------------------------------------------------------------------------


def build_comparison(query: str, extract: dict) -> list[dict]:
    """產生「你的情況 vs 本案」對比表（需 query）。

    比對三面向：主觀要素、是否涉傷亡、肇事逃逸。
    口語 query 的要件用關鍵詞粗判；本案用抽取/摘要關鍵詞。
    """
    summary = extract.get("facts_summary", "") or ""
    subj_case = extract.get("subjective", "") or ""

    user_subj = infer_subjective(query)
    case_subj = subj_case or ("過失" if any(k in summary for k in _NEGLIGENCE_HINTS) else (
        "故意" if any(k in summary for k in _INTENT_HINTS) else "不明"))

    def _injury(text: str) -> str:
        if any(k in text for k in ("死亡", "致死")):
            return "致死"
        if any(k in text for k in ("受傷", "傷害", "撞傷")):
            return "有人受傷"
        return "無人受傷/財損"

    def _hitrun(text: str) -> str:
        return "有" if any(k in text for k in ("逃逸", "肇逃", "逃離")) else "無"

    rows = [
        {
            "aspect": "主觀要素",
            "user": user_subj,
            "case": case_subj,
            "match": user_subj == case_subj and user_subj != "不確定",
        },
        {
            "aspect": "傷亡情形",
            "user": _injury(query),
            "case": _injury(summary),
            "match": _injury(query) == _injury(summary),
        },
        {
            "aspect": "肇事逃逸",
            "user": _hitrun(query),
            "case": _hitrun(summary),
            "match": _hitrun(query) == _hitrun(summary),
        },
    ]
    return rows


# ---------------------------------------------------------------------------
# 推理鏈（trace）：結構化模板，反映實際管線（rewrite→hybrid→rerank）
# ---------------------------------------------------------------------------


def build_trace(query: str, cases: list[dict], rewrite: bool) -> list[dict]:
    """產生推理鏈步驟，反映 search_pipeline 真實流程（非杜撰）。"""
    subjective = infer_subjective(query)
    arts = infer_articles(query)
    art_str = "；".join(f"{a['code']} {a['name']}（{a['note']}）" for a in arts) or "依檢索結果判斷"

    steps = [
        {"step": 1, "name": "理解事由",
         "detail": f"主觀要素推斷：{subjective}；口語事由：{query[:60]}"},
        {"step": 2, "name": "推斷法條", "detail": art_str},
    ]
    if rewrite:
        steps.append({
            "step": 3, "name": "Query 改寫",
            "detail": "口語 → 接近判決書『犯罪事實』段的法律事實描述（gemini，提升召回）",
        })
    steps.append({
        "step": len(steps) + 1, "name": "混合檢索",
        "detail": "Dense(BGE-M3 facts) + BM25(摘要+案由+法條號) → RRF(k=60) → top-20 候選",
    })
    steps.append({
        "step": len(steps) + 1, "name": "重排",
        "detail": f"bge-reranker-v2-m3 對 (query, doc) 交互打分 → top-{len(cases)}",
    })
    return steps


# ---------------------------------------------------------------------------
# clarify 規則層：判斷缺哪些關鍵要件
# ---------------------------------------------------------------------------

# 刑事類案檢索需要的關鍵要件，及其口語偵測關鍵詞
_REQUIRED_SLOTS: list[tuple[str, str, tuple[str, ...]]] = [
    ("incident_type", "事件類型", ("車", "酒", "打", "偷", "騙", "毒", "撞", "毀")),
    ("injury", "是否有人受傷", ("受傷", "沒受傷", "無人受傷", "死亡", "輕傷", "重傷", "沒人")),
    ("fault", "故意或過失", _INTENT_HINTS + _NEGLIGENCE_HINTS),
]


def check_collected(messages: list[dict]) -> dict:
    """規則層：從對話歷史粗判已蒐集要件與缺漏。

    回 {collected, missing_slots}。供 clarify_llm 決定追問哪一項，
    或在規則已足夠時直接 ready。
    """
    text = " ".join(
        m.get("content", "") for m in messages if m.get("role") == "user"
    )
    collected: dict = {
        "incident_type": None,
        "injury": None,
        "hit_and_run": None,
        "fault": None,
    }
    if any(k in text for k in ("車", "撞", "酒駕", "肇事")):
        collected["incident_type"] = "交通/車輛"
    elif any(k in text for k in ("打", "毆", "鬥毆")):
        collected["incident_type"] = "人身衝突"
    elif any(k in text for k in ("偷", "竊")):
        collected["incident_type"] = "竊盜"
    elif any(k in text for k in ("騙", "詐")):
        collected["incident_type"] = "詐欺"

    if any(k in text for k in ("受傷", "輕傷", "重傷", "死亡")):
        collected["injury"] = True
    elif any(k in text for k in ("沒受傷", "無人受傷", "沒人受傷", "沒有人受傷")):
        collected["injury"] = False

    if any(k in text for k in ("逃逸", "肇逃", "逃離", "跑掉")):
        collected["hit_and_run"] = True
    elif any(k in text for k in ("沒逃", "留在現場", "報警")):
        collected["hit_and_run"] = False

    if any(k in text for k in _NEGLIGENCE_HINTS):
        collected["fault"] = "過失"
    elif any(k in text for k in _INTENT_HINTS):
        collected["fault"] = "故意"

    missing = []
    if collected["incident_type"] is None:
        missing.append("incident_type")
    if collected["injury"] is None:
        missing.append("injury")
    if collected["fault"] is None:
        missing.append("fault")
    return {"collected": collected, "missing_slots": missing}
