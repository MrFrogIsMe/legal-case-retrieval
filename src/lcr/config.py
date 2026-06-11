"""集中設定模組。

所有路徑、參數、環境變數一律透過此模組存取，
其他程式不得直接讀 os.environ 或 .env。
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """專案設定。可由環境變數或 .env 覆寫（前綴 LCR_）。"""

    model_config = SettingsConfigDict(
        env_prefix="LCR_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- 資料路徑 ---
    # 原始判決資料根目錄。本機開發可指向同步下來的副本或 sshfs 掛載點。
    # 透過 LCR_DATASET_ROOT 覆寫（務必用絕對路徑）。
    dataset_root: Path = Path("data/raw")
    # 處理後產物（篩選、切段、抽取結果）；建議設為絕對路徑。
    # 透過 LCR_PROCESSED_DIR 覆寫。
    processed_dir: Path = Path("data/processed")

    # --- LLM 設定 ---
    # 讀取 LCR_OPENAI_API_KEY（.env 設定），或直接設 OPENAI_API_KEY 搭配 alias
    openai_api_key: str = ""
    openai_model: str = "gpt-5-mini"
    openai_batch_model: str = "gpt-5-mini"

    # 本地 Llama（home_wsl）
    llama_model_id: str = "lianghsun/Llama-3.2-Taiwan-Legal-3B-Instruct"

    # --- 評估集生成 LLM（OpenAI 相容閘道）---
    # 用於合成評估集的口語 query 生成（experiments/06_make_evalset.py）。
    # 與要素抽取（gpt-5-mini）分離，方便獨立替換評估模型。
    # 走公司內部 AI 閘道（OpenAI 相容介面），base_url 結尾為 /v1。
    # key 與 base_url 來源：.env 的 LCR_GEMINI_API_KEY / LCR_GEMINI_BASE_URL。
    gemini_api_key: str = ""
    gemini_base_url: str = ""
    eval_model: str = "gemini-3.5-flash"
    eval_max_tokens: int = 1024

    # --- 子集篩選參數（舊版，保留相容性）---
    # 目標案由關鍵字（出現在 JTITLE 即視為候選）
    target_title_keywords: tuple[str, ...] = (
        "過失傷害",
        "業務過失",
        "過失致死",
        "過失致人於死",
        "公共危險",
    )
    # 目標案件類別前綴（JCASE，交通相關）
    target_case_prefixes: tuple[str, ...] = ("交易", "交訴", "交簡", "交聲", "交附民", "交抗")
    # 只取地方法院（院名包含「地方法院」），排除最高法院等
    district_court_only: bool = True

    def ensure_dirs(self) -> None:
        """建立輸出目錄（若不存在）。"""
        self.processed_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()
