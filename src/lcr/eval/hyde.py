"""HyDE / query 改寫：把口語事由轉成接近判決書的法律事實描述。

三策略（供消融對照，回答「哪種 prompt 最能得出精準法律用詞」）：
  A rewrite     ：zero-shot 改寫成法律事實描述
  B hyde        ：生成一段「假設判決事實段」（HyDE, Gao 2022）
  C controlled  ：先判案由 → 餵該案由的真實法條/特徵詞 → 受控生成（防腦補）

策略 C 的法律術語來自 experiments/09 學到的 legal_terms.json（資料驅動）。

LLM 走 gemini-3.5-flash（同評估集生成，見 lcr.eval.query_gen 的 client）。
"""
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from openai import OpenAI

from lcr.config import settings

_REWRITE_SYS = (
    "你是台灣刑事法律助理。使用者會用口語描述一起事件，"
    "請把它改寫成接近判決書『犯罪事實』段的正式法律事實描述，"
    "使用法律用語，但不要杜撰原描述沒有的細節（人名、日期、金額一律不要編）。"
    "只輸出改寫後的一段文字，不要解釋。"
)

_HYDE_SYS = (
    "你是台灣刑事法官。使用者會用口語描述一起事件，"
    "請你想像並撰寫一段該事件可能對應的判決書『犯罪事實與理由』段落，"
    "文體、用語要像真實判決書（例如『被告基於...之犯意』『核其所為，係犯...』）。"
    "不要杜撰具體人名、日期、金額。只輸出該段落。"
)

_CONTROLLED_SYS = (
    "你是台灣刑事法律助理。使用者用口語描述事件，"
    "已知此事件最可能屬於案由「{title}」，該類案件判決常引用法條：{articles}，"
    "常見法律用語：{terms}。"
    "請用上述真實法律用語，把使用者的口語改寫成接近判決書的事實描述。"
    "只能使用貼近上述用語的表達，不要杜撰人名/日期/金額。只輸出改寫文字。"
)


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    if not settings.gemini_api_key or not settings.gemini_base_url:
        raise RuntimeError("缺少 LCR_GEMINI_API_KEY / LCR_GEMINI_BASE_URL")
    return OpenAI(api_key=settings.gemini_api_key, base_url=settings.gemini_base_url)


@lru_cache(maxsize=1)
def _term_map() -> dict:
    p = settings.processed_dir / "legal_terms.json"
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def _chat(system: str, user: str) -> str:
    resp = _client().chat.completions.create(
        model=settings.eval_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        max_tokens=settings.eval_max_tokens,
    )
    return (resp.choices[0].message.content or "").strip()


def _guess_title(query: str) -> tuple[str, dict] | tuple[None, None]:
    """用術語表特徵詞粗略命中案由（純字串比對，不額外呼叫 LLM）。"""
    tm = _term_map()
    best, best_hit = None, 0
    for title, info in tm.items():
        hit = sum(1 for t in info.get("top_terms", []) if t in query)
        # 案由名本身出現也加分
        if any(c in query for c in title):
            hit += 1
        if hit > best_hit:
            best, best_hit = title, hit
    if best:
        return best, tm[best]
    return None, None


def rewrite(query: str) -> str:
    """策略 A：zero-shot 改寫。"""
    return _chat(_REWRITE_SYS, f"口語描述：{query}")


def hyde(query: str) -> str:
    """策略 B：生成假設判決段。"""
    return _chat(_HYDE_SYS, f"口語描述：{query}")


def controlled(query: str) -> str:
    """策略 C：受控生成（餵案由真實術語）。命不中案由則退回策略 A。"""
    title, info = _guess_title(query)
    if not title:
        return rewrite(query)
    sys_prompt = _CONTROLLED_SYS.format(
        title=title,
        articles="、".join(info.get("top_articles", [])[:5]),
        terms="、".join(info.get("top_terms", [])[:10]),
    )
    return _chat(sys_prompt, f"口語描述：{query}")
