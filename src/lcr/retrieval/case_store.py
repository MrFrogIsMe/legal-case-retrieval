"""案例資料倉（CaseStore）：供 API 端點查 jid → 抽取結果 / 原文 / 統計。

設計依據：docs/api_v1.md（/search 補欄位、/case/{jid} 詳情、/stats 群體統計）

為何不重建索引塞進 ChromaDB metadata：
  - chroma metadata 僅存 jid/kind/court/jyear/title/articles（建索引時的決策）。
  - verdict/sentence/compensation/facts_summary 在 gpt_extract_all.jsonl；
    原文三段在 segmented.jsonl。
  - /stats 本質是「全量 group-by 聚合」，chroma 不適合做聚合；重建索引幫助有限。
  - 故走資料倉：抽取結果全量進記憶體（81k 筆輕量），原文用行偏移 lazy 讀，
    不動已驗證的索引（最小改動）。

記憶體預算：
  - gpt_extract_all（81k × ~5 欄位短字串）數十 MB，可全量常駐。
  - segmented（81k × 三段原文，數百 MB）→ 只建 jid→byte offset 索引，
    /case/{jid} 需要時才 seek 讀單行。
"""

from __future__ import annotations

import json
from collections import Counter
from functools import lru_cache
from pathlib import Path

from lcr.config import settings

# 民國年 → 月份顯示用
_CN_NUM = "〇一二三四五六七八九"


def _roc_date_display(jdate: str) -> str:
    """20171110 → 民國 106 年 11 月 10 日。jdate 為西元 YYYYMMDD 字串。"""
    s = str(jdate or "").strip()
    if len(s) != 8 or not s.isdigit():
        return s
    year = int(s[:4]) - 1911
    month = int(s[4:6])
    day = int(s[6:8])
    return f"民國 {year} 年 {month} 月 {day} 日"


class CaseStore:
    """案例資料倉：抽取結果常駐 + 原文 lazy 讀 + 統計聚合。"""

    def __init__(
        self,
        processed_dir: Path | None = None,
        corpus_name: str = "corpus.jsonl",
        segmented_name: str = "segmented.jsonl",
        extract_name: str = "gpt_extract_all.jsonl",
    ):
        self.processed_dir = Path(processed_dir or settings.processed_dir)
        self.corpus_path = self.processed_dir / corpus_name
        self.segmented_path = self.processed_dir / segmented_name
        self.extract_path = self.processed_dir / extract_name

        # jid → {title, court, jyear, jdate, kind}
        self._meta: dict[str, dict] = {}
        # jid → {verdict, sentence, compensation, subjective, facts_summary}
        self._extract: dict[str, dict] = {}
        # jid → byte offset（segmented.jsonl 內該筆所在行的起始位元組）
        self._seg_offset: dict[str, int] = {}
        self._loaded = False

    # --- 載入 ---------------------------------------------------------------

    def load(self) -> CaseStore:
        """載入 meta + extract（全量）與 segmented 行偏移索引（lazy 讀用）。"""
        if self._loaded:
            return self
        self._load_meta()
        self._load_extract()
        self._build_segmented_offsets()
        self._loaded = True
        return self

    def _load_meta(self) -> None:
        if not self.corpus_path.exists():
            return
        with self.corpus_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                self._meta[d["jid"]] = {
                    "title": d.get("title", ""),
                    "court": d.get("court", ""),
                    "jyear": str(d.get("jyear", "")),
                    "jdate": str(d.get("jdate", "")),
                    "kind": d.get("kind", "criminal"),
                }

    def _load_extract(self) -> None:
        if not self.extract_path.exists():
            return
        with self.extract_path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                g = d.get("gpt", {})
                if "error" in g:
                    continue
                self._extract[d["jid"]] = {
                    "verdict": g.get("verdict") or "",
                    "sentence": g.get("sentence"),
                    "compensation": g.get("compensation"),
                    "subjective": g.get("subjective") or "",
                    "facts_summary": g.get("facts_summary") or "",
                }

    def _build_segmented_offsets(self) -> None:
        """建 jid → byte offset 索引，供 /case 詳情 lazy 讀單行原文。"""
        if not self.segmented_path.exists():
            return
        # 以位元組模式逐行掃，記錄每行起始 offset
        with self.segmented_path.open("rb") as f:
            offset = 0
            for raw in f:
                try:
                    d = json.loads(raw)
                    jid = d.get("jid")
                    if jid:
                        self._seg_offset[jid] = offset
                except Exception:  # noqa: BLE001  壞行跳過，不阻斷
                    pass
                offset += len(raw)

    # --- 查詢 ---------------------------------------------------------------

    @property
    def case_count(self) -> int:
        return len(self._meta) or len(self._extract)

    def get_meta(self, jid: str) -> dict:
        return self._meta.get(jid, {})

    def get_extract(self, jid: str) -> dict:
        return self._extract.get(jid, {})

    def get_segments(self, jid: str) -> dict:
        """lazy 讀 segmented.jsonl 單行，回三段原文。找不到回空段。"""
        off = self._seg_offset.get(jid)
        if off is None:
            return {"main": "", "facts": "", "reasoning": ""}
        with self.segmented_path.open("rb") as f:
            f.seek(off)
            raw = f.readline()
        try:
            d = json.loads(raw)
        except Exception:  # noqa: BLE001
            return {"main": "", "facts": "", "reasoning": ""}
        return {
            "main": d.get("main", "") or "",
            "facts": d.get("facts", "") or "",
            "reasoning": d.get("reasoning", "") or "",
        }

    def date_display(self, jid: str) -> str:
        return _roc_date_display(self.get_meta(jid).get("jdate", ""))

    def has(self, jid: str) -> bool:
        return jid in self._meta or jid in self._extract or jid in self._seg_offset

    # --- 統計聚合 -----------------------------------------------------------

    def stats(
        self,
        case_type: str | None = None,
        year_from: int | None = None,
        year_to: int | None = None,
    ) -> dict:
        """群體統計：verdict 分布 / compensation range / by_year。

        case_type：以子字串比對案由（title），None 表全量。
        year_from/year_to：民國年範圍（含端點）。
        """
        return self._stats_cached(case_type or "", year_from, year_to)

    @lru_cache(maxsize=64)
    def _stats_cached(
        self, case_type: str, year_from: int | None, year_to: int | None
    ) -> dict:
        verdict_counter: Counter[str] = Counter()
        comps: list[int] = []
        year_counter: Counter[int] = Counter()
        total = 0

        for jid, meta in self._meta.items():
            title = meta.get("title", "")
            if case_type and case_type not in title:
                continue
            try:
                jyear = int(meta.get("jyear") or 0)
            except (ValueError, TypeError):
                jyear = 0
            if year_from is not None and jyear < year_from:
                continue
            if year_to is not None and jyear > year_to:
                continue

            total += 1
            ext = self._extract.get(jid, {})
            v = ext.get("verdict") or "未知"
            verdict_counter[v] += 1
            comp = ext.get("compensation")
            if isinstance(comp, (int, float)) and comp > 0:
                comps.append(int(comp))
            if jyear:
                year_counter[jyear] += 1

        verdict_distribution = [
            {
                "label": label,
                "count": cnt,
                "ratio": round(cnt / total, 4) if total else 0.0,
            }
            for label, cnt in verdict_counter.most_common()
        ]
        comp_range = None
        if comps:
            comps_sorted = sorted(comps)
            mid = len(comps_sorted) // 2
            median = (
                comps_sorted[mid]
                if len(comps_sorted) % 2
                else (comps_sorted[mid - 1] + comps_sorted[mid]) // 2
            )
            comp_range = {
                "min": comps_sorted[0],
                "median": median,
                "max": comps_sorted[-1],
                "currency": "TWD",
            }
        by_year = [
            {"year": y, "count": c} for y, c in sorted(year_counter.items())
        ]
        return {
            "total": total,
            "verdict_distribution": verdict_distribution,
            "compensation_range": comp_range,
            "by_year": by_year,
        }
