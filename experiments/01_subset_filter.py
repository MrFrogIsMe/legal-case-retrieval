"""實驗 01：子集篩選。

遍歷原始刑事判決，套用 lcr.data.filter 規則，輸出：
  1. data/processed/subset.jsonl  — 篩選後的案件（每行一筆，含 metadata）
  2. 終端統計報告（總數、命中數、案由分布、JCASE 分布）

用法（在 repo 根目錄）：
    uv run python experiments/01_subset_filter.py
    LCR_DATASET_ROOT=/path/to/Dataset uv run python experiments/01_subset_filter.py

長跑建議在 tmux 中執行（資料量大）。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lcr.config import settings  # noqa: E402
from lcr.data.filter import criteria_from_settings, should_keep  # noqa: E402


def iter_criminal_files(dataset_root: Path):
    """產生所有刑事庭資料夾下的 JSON 路徑，並回傳 (path, court_name)。

    資料結構（兩層）：
        Dataset/<院別>刑事/<年月批次>/<判決>.json
    例如：Dataset/臺灣士林地方法院刑事/200104/SLDM,...,1.json
    """
    for court in dataset_root.iterdir():
        if not court.is_dir() or not court.name.endswith("刑事"):
            continue
        court_name = court.name.removesuffix("刑事")
        for batch in court.iterdir():
            if not batch.is_dir():
                continue
            for f in batch.iterdir():
                if f.suffix == ".json":
                    yield f, court_name


def main() -> int:
    dataset_root = settings.dataset_root
    if not dataset_root.exists():
        print(f"[錯誤] 找不到資料根目錄：{dataset_root}")
        print("請設定 LCR_DATASET_ROOT 環境變數指向 Dataset 路徑。")
        return 1

    settings.ensure_dirs()
    criteria = criteria_from_settings(settings)
    out_path = settings.processed_dir / "subset.jsonl"

    total = 0
    kept = 0
    title_counter: Counter[str] = Counter()
    jcase_counter: Counter[str] = Counter()
    court_counter: Counter[str] = Counter()

    with out_path.open("w", encoding="utf-8") as out:
        for path, court_name in iter_criminal_files(dataset_root):
            total += 1
            # json.load 需關閉 strict，否則判決全文常有控制字元未跳脫
            with path.open(encoding="utf-8") as fp:
                d = json.loads(fp.read(), strict=False)

            title = d.get("JTITLE", "")
            jcase = d.get("JCASE", "")
            full_court = court_name if "地方法院" in court_name else court_name

            if not should_keep(
                title=title, jcase=jcase, court_name=court_name, criteria=criteria
            ):
                continue

            kept += 1
            title_counter[title] += 1
            jcase_counter[jcase] += 1
            court_counter[full_court] += 1

            record = {
                "jid": d.get("JID", ""),
                "title": title,
                "jcase": jcase,
                "jno": d.get("JNO", ""),
                "jyear": d.get("JYEAR", ""),
                "jdate": d.get("JDATE", ""),
                "court": court_name,
                "source_path": str(path.relative_to(dataset_root)),
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")

            if total % 50000 == 0:
                print(f"  進度：掃描 {total:,} / 命中 {kept:,}")

    # --- 統計報告 ---
    print("\n" + "=" * 50)
    print(f"掃描刑事判決總數：{total:,}")
    print(f"命中子集數量：{kept:,}  ({kept / total * 100:.1f}%)" if total else "無資料")
    print(f"輸出：{out_path}")

    print("\n--- Top 15 案由 ---")
    for t, c in title_counter.most_common(15):
        print(f"  {t}: {c:,}")

    print("\n--- JCASE 分布 ---")
    for jc, c in jcase_counter.most_common(15):
        print(f"  {jc}: {c:,}")

    print(f"\n--- 法院數：{len(court_counter)} ---")
    for ct, c in court_counter.most_common(10):
        print(f"  {ct}: {c:,}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
