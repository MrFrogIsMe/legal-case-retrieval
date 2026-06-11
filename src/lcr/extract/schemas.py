"""刑事 / 民事要素抽取 schema 定義。

設計依據：docs/design_change_v1.md
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# 刑事 schema
# ---------------------------------------------------------------------------

CRIMINAL_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["有罪", "無罪", "不受理", "緩刑", "免刑", "不明"],
            "description": "刑事判決結果",
        },
        "sentence": {
            "type": ["string", "null"],
            "description": "刑度，如「有期徒刑3月」「拘役30日」「罰金1萬元」，無則 null",
        },
        "compensation": {
            "type": ["integer", "null"],
            "description": "附帶民事賠償金額（新台幣元，整數），無則 null",
        },
        "subjective": {
            "type": "string",
            "enum": ["故意", "過失", "不明"],
            "description": "犯罪主觀要素",
        },
        "facts_summary": {
            "type": "string",
            "description": "事實摘要，100-150 字繁體中文白話，不含法條引用",
        },
    },
    "required": ["verdict", "sentence", "compensation", "subjective", "facts_summary"],
    "additionalProperties": False,
}

CRIMINAL_USER_TEMPLATE = """以下是刑事判決書內容（已切段）：

【主文】
{main}

【事實】
{facts}

【理由摘錄】
{reasoning}

請抽取以下欄位（若無法確定填「不明」或 null）：
- verdict: 判決結果（有罪/無罪/不受理/緩刑/免刑/不明）
- sentence: 刑度（無則 null）
- compensation: 附帶民事賠償金額（整數元，無則 null）
- subjective: 主觀要素（故意/過失/不明）
- facts_summary: 事實摘要 100-150 字"""

# ---------------------------------------------------------------------------
# 民事 schema
# ---------------------------------------------------------------------------

# DEPRECATED（design_change_v2）：專案收斂為純刑事，民事 schema 不再使用，保留不刪以維持相容。
CIVIL_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "enum": ["原告勝訴", "原告敗訴", "部分勝訴", "調解成立", "駁回", "不明"],
            "description": "民事判決結果",
        },
        "compensation": {
            "type": ["integer", "null"],
            "description": "判賠金額（新台幣元，整數），無則 null",
        },
        "dispute_type": {
            "type": "string",
            "enum": ["損害賠償", "債務清償", "所有權", "契約", "侵權行為", "其他"],
            "description": "民事爭議類型",
        },
        "facts_summary": {
            "type": "string",
            "description": "事實摘要，100-150 字繁體中文白話，不含法條引用",
        },
    },
    "required": ["verdict", "compensation", "dispute_type", "facts_summary"],
    "additionalProperties": False,
}

# DEPRECATED（design_change_v2）：專案收斂為純刑事，民事 template 不再使用，保留不刪以維持相容。
CIVIL_USER_TEMPLATE = """以下是民事判決書內容（已切段）：

【主文】
{main}

【事實】
{facts}

【理由摘錄】
{reasoning}

請抽取以下欄位（若無法確定填「不明」或 null）：
- verdict: 判決結果（原告勝訴/原告敗訴/部分勝訴/調解成立/駁回/不明）
- compensation: 判賠金額（整數元，無則 null）
- dispute_type: 爭議類型（損害賠償/債務清償/所有權/契約/侵權行為/其他）
- facts_summary: 事實摘要 100-150 字"""

# ---------------------------------------------------------------------------
# 依 kind 取 schema / template
# ---------------------------------------------------------------------------

SCHEMAS = {
    "criminal": CRIMINAL_SCHEMA,
    "civil": CIVIL_SCHEMA,
}

USER_TEMPLATES = {
    "criminal": CRIMINAL_USER_TEMPLATE,
    "civil": CIVIL_USER_TEMPLATE,
}

SYSTEM_PROMPT = (
    "你是台灣法律判決書分析助理。請從以下判決書內容中抽取結構化要素，"
    "以 JSON 格式回傳，嚴格遵守 schema，不要編造原文沒有的內容。"
)


def get_schema(kind: str) -> dict:
    """依 kind（criminal/civil）取對應 schema。未知 kind 預設刑事。"""
    return SCHEMAS.get(kind, CRIMINAL_SCHEMA)


def get_user_template(kind: str) -> str:
    """依 kind 取對應 user prompt template。"""
    return USER_TEMPLATES.get(kind, CRIMINAL_USER_TEMPLATE)
