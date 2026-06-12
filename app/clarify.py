"""clarify 對話追問的 LLM 層（最簡實作）。

規則層（app.analysis.check_collected）先粗判已蒐集要件與缺漏；
本層只在「仍缺要件」時呼叫一次 LLM 產生自然的追問句，並給理由。
若要件已足夠 → 直接 ready_to_search，不呼叫 LLM。
LLM 失敗 → 退回規則化的固定追問句（不阻斷）。

LLM 走 gemini gateway（同 lcr.eval.hyde 的 client 模式）。
"""

from __future__ import annotations

from functools import lru_cache

from lcr.config import settings

# 缺漏要件 → 規則化備援追問句（LLM 不可用時用）
_FALLBACK_Q: dict[str, tuple[str, str]] = {
    "incident_type": (
        "方便描述一下發生什麼事嗎？例如車禍、衝突、財物糾紛等。",
        "事件類型決定可能適用的刑事法條",
    ),
    "injury": (
        "請問這次事件有人受傷嗎？",
        "是否有人受傷會決定刑事責任類型（過失傷害 vs 純財損）",
    ),
    "fault": (
        "這件事是不小心造成的，還是有意為之？",
        "故意或過失是刑事責任的核心要件，影響適用法條與量刑",
    ),
}

_CLARIFY_SYS = (
    "你是台灣刑事類案檢索系統的對話助理。使用者描述一起事件，"
    "系統需要釐清關鍵要件以便檢索類似判決。"
    "請針對指定的『缺漏要件』，用一句自然、口語、友善的繁體中文向使用者提問，"
    "不要法律說教、不要列點、不要解釋，只輸出那一句問句。"
)


@lru_cache(maxsize=1)
def _client():
    from openai import OpenAI

    if not settings.gemini_api_key or not settings.gemini_base_url:
        raise RuntimeError("缺少 LCR_GEMINI_API_KEY / LCR_GEMINI_BASE_URL")
    return OpenAI(api_key=settings.gemini_api_key, base_url=settings.gemini_base_url)


_SLOT_LABEL = {
    "incident_type": "事件類型（發生什麼事）",
    "injury": "是否有人受傷",
    "fault": "故意還是過失",
}


def next_question(slot: str, history_text: str) -> tuple[str, str]:
    """為缺漏要件產生 (追問句, 理由)。LLM 失敗退回固定句。"""
    fallback_q, reason = _FALLBACK_Q.get(
        slot, ("可以再多描述一點細節嗎？", "補充細節有助於找到更相似的判決")
    )
    try:
        resp = _client().chat.completions.create(
            model=settings.eval_model,
            messages=[
                {"role": "system", "content": _CLARIFY_SYS},
                {
                    "role": "user",
                    "content": (
                        f"使用者目前的描述：{history_text}\n"
                        f"缺漏要件：{_SLOT_LABEL.get(slot, slot)}\n"
                        "請用一句話追問這個要件。"
                    ),
                },
            ],
            max_tokens=settings.eval_max_tokens,
        )
        q = (resp.choices[0].message.content or "").strip()
        if q:
            return q, reason
    except Exception:  # noqa: BLE001  LLM 不可用 → 用備援句
        pass
    return fallback_q, reason
