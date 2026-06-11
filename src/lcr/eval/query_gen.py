"""合成評估集：口語 query 生成（gemini-3.5-flash via OpenAI 相容閘道）。

對齊 docs/design_v1.md 第 5.1 節：
  從篩選後子集隨機抽 ~50 份判決，對每份用 LLM 生成 2-3 個
  「法律門外漢可能會問的口語事由」，得到 (query, relevant_jid) 對。

設計重點：
  - 扮演「不懂法律術語的當事人」，只描述發生什麼事，不准用法條/罪名
  - 一份判決生成 2-3 個不同角度的口語 query，提升評估集多樣性
  - 回傳嚴格 JSON，並對 markdown fenced code block 做容錯解析
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache

from openai import OpenAI

from lcr.config import settings

_SYSTEM_PROMPT = (
    "你是一個完全不懂法律的台灣一般民眾。你只會用日常口語描述「發生了什麼事」，"
    "絕對不會使用法律術語（例如：過失、故意、業務過失、損害賠償、刑法第X條、"
    "公共危險、肇事逃逸這類詞彙都不准出現）。"
    "你會用像是在跟朋友抱怨或問路人的語氣描述事件。"
)

_USER_TEMPLATE = """以下是一份台灣法院判決書的「事實摘要」。

請你想像自己是這起事件的當事人（但完全不懂法律），
針對「同一件事」，用不同的口吻與切入點，產生 {n} 個口語化的查詢句。

要求：
1. 每句都是一個人會拿去搜尋「過去類似案子怎麼判」的自然口語問題。
2. 嚴禁出現任何法律術語、罪名、法條號碼。
3. 只描述事件經過與想知道的事（例如賠多少、會怎樣），不要自己下判斷。
4. 每句 15-40 字，彼此角度要不同（例如一句重在經過、一句重在賠償、一句重在後果）。

事實摘要：
{facts}

請只回傳 JSON，格式如下（不要任何其他文字）：
{{"queries": ["...", "...", "..."]}}"""

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL)
_OBJ_RE = re.compile(r"\{.*\}", re.DOTALL)


@dataclass
class QueryGenResult:
    """單筆判決的 query 生成結果。"""

    jid: str
    queries: list[str]
    raw: str = ""
    error: str = ""


@lru_cache(maxsize=1)
def _client() -> OpenAI:
    """建立指向 gemini 閘道的 OpenAI client（lazy，單例）。"""
    if not settings.gemini_api_key or not settings.gemini_base_url:
        raise RuntimeError(
            "缺少 LCR_GEMINI_API_KEY 或 LCR_GEMINI_BASE_URL，請於 .env 設定"
        )
    return OpenAI(
        api_key=settings.gemini_api_key,
        base_url=settings.gemini_base_url,
    )


def _parse_queries(content: str) -> list[str]:
    """從模型回應抽出 queries 陣列，對 markdown fence / 雜訊做容錯。"""
    if not content:
        return []

    # 1. 優先抓 fenced code block 內容
    m = _FENCE_RE.search(content)
    candidate = m.group(1) if m else content

    # 2. 抓第一個 {...} 物件
    m2 = _OBJ_RE.search(candidate)
    if m2:
        candidate = m2.group(0)

    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        return []

    queries = obj.get("queries", []) if isinstance(obj, dict) else []
    # 去空白、去重、保序
    seen: set[str] = set()
    cleaned: list[str] = []
    for q in queries:
        if not isinstance(q, str):
            continue
        q = q.strip()
        if q and q not in seen:
            seen.add(q)
            cleaned.append(q)
    return cleaned


def generate_queries(
    jid: str,
    facts: str,
    n: int = 3,
    max_facts_chars: int = 1500,
) -> QueryGenResult:
    """對單份判決事實段生成 n 個口語 query。

    回傳 QueryGenResult；失敗時 queries 為空、error 帶訊息（呼叫端決定是否跳過）。
    """
    facts = (facts or "").strip()
    if not facts:
        return QueryGenResult(jid=jid, queries=[], error="empty_facts")

    user_msg = _USER_TEMPLATE.format(n=n, facts=facts[:max_facts_chars])

    try:
        resp = _client().chat.completions.create(
            model=settings.eval_model,
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
            max_tokens=settings.eval_max_tokens,
        )
    except Exception as e:  # noqa: BLE001 — 呼叫端要靠 error 欄位決定跳過
        return QueryGenResult(jid=jid, queries=[], error=f"{type(e).__name__}: {e}")

    content = resp.choices[0].message.content or ""
    queries = _parse_queries(content)
    if not queries:
        return QueryGenResult(
            jid=jid, queries=[], raw=content, error="parse_failed_or_empty"
        )
    return QueryGenResult(jid=jid, queries=queries[:n], raw=content)
