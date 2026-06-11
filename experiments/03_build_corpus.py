"""實驗 03：建立通用語料庫（刑事 + 民事，排除程序性，分層抽樣）。

策略詳見 docs/data_design_v1.md。

流程：
  1. 遍歷 Dataset/ 下所有刑事 + 民事資料夾（民國 100 年後）
  2. 第一刀：排除程序性案件（見 lcr.data.filter）
  3. 收集候選，依案由(JTITLE)分桶
  4. 第二刀：每桶最多 200 筆隨機抽樣（seed=42）
  5. 輸出 data/processed/corpus.jsonl + 統計報告

用法（repo 根目錄；建議 tmux，處理量大）：
    LCR_DATASET_ROOT=/home/mrfrog/code/lawundry_test/Dataset \\
      uv run python experiments/03_build_corpus.py
"""

from __future__ import annotations

import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lcr.config import settings  # noqa: E402
from lcr.data.filter import (  # noqa: E402
    is_district_court,
    is_procedural,
    is_year_in_range,
)

PER_TITLE_CAP = 999999  # 設為極大值，不做任何案由上限篩選，保留全量近10年地院刑事案件（81,644 筆）
RANDOM_SEED = 42
MIN_YEAR = 105  # 民國 105 年
MAX_YEAR = 114  # 民國 114 年


def iter_all_files(dataset_root: Path):
    """產生 (path, court_name, kind) for 刑事。

    kind: "criminal"
    資料結構：Dataset/<院別>刑事/<年月批次>/<判決>.json
    """
    for court_dir in dataset_root.iterdir():
        if not court_dir.is_dir():
            continue
        name = court_dir.name
        if name.endswith("刑事"):
            kind = "criminal"
            court_name = name.removesuffix("刑事")
        else:
            continue  # 跳過民事、行政/懲戒等

        for batch in court_dir.iterdir():
            if not batch.is_dir():
                continue
            for f in batch.iterdir():
                if f.suffix == ".json":
                    yield f, court_name, kind


def main() -> int:
    dataset_root = settings.dataset_root
    if not dataset_root.exists():
        print(f"[錯誤] 找不到資料根目錄：{dataset_root}")
        print("請設定 LCR_DATASET_ROOT 環境變數。")
        return 1

    settings.ensure_dirs()
    random.seed(RANDOM_SEED)

    # --- Phase 1：遍歷 + 第一刀排除，依案由分桶 ---
    buckets: defaultdict[str, list[dict]] = defaultdict(list)

    total = 0
    skip_year = 0       # 年份不符
    skip_procedural = 0 # 程序性
    skip_court = 0      # 非地方法院
    read_fail = 0
    candidate = 0

    print("Phase 1：遍歷 + 排除...")
    for path, court_name, kind in iter_all_files(dataset_root):
        total += 1

        if not is_district_court(court_name):
            skip_court += 1
            continue

        try:
            with path.open(encoding="utf-8") as fp:
                d = json.loads(fp.read(), strict=False)
        except (OSError, UnicodeDecodeError, ValueError):
            read_fail += 1
            continue

        jyear = d.get("JYEAR", "")
        if not is_year_in_range(jyear, MIN_YEAR, MAX_YEAR):
            skip_year += 1
            continue

        title = d.get("JTITLE", "")
        jcase = d.get("JCASE", "")

        if is_procedural(kind, jcase, title):
            skip_procedural += 1
            continue

        candidate += 1
        buckets[title].append({
            "jid": d.get("JID", ""),
            "title": title,
            "jcase": jcase,
            "jyear": jyear,
            "jdate": d.get("JDATE", ""),
            "court": court_name,
            "kind": kind,
            "jfull": d.get("JFULL", ""),
            "source_path": str(path.relative_to(dataset_root)),
        })

        if total % 100_000 == 0:
            print(f"  掃描 {total:,} / 候選 {candidate:,} / 桶數 {len(buckets):,}")

    print("\n Phase 1 完成")
    print(f"  總掃描：{total:,}")
    print(f"  跳過（非地方法院）：{skip_court:,}")
    print(f"  跳過（年份 <{MIN_YEAR}）：{skip_year:,}")
    print(f"  跳過（程序性）：{skip_procedural:,}")
    print(f"  讀檔失敗：{read_fail:,}")
    print(f"  候選案件：{candidate:,}（{len(buckets):,} 種案由）")

    # --- Phase 2：分層抽樣 ---
    print(f"\nPhase 2：分層抽樣（每案由上限 {PER_TITLE_CAP} 筆）...")
    out_path = settings.processed_dir / "corpus.jsonl"
    kept = 0
    kind_counter: Counter[str] = Counter()
    title_counter: Counter[str] = Counter()
    sampled_buckets = 0
    full_buckets = 0

    with out_path.open("w", encoding="utf-8") as fout:
        for title, records in buckets.items():
            if len(records) > PER_TITLE_CAP:
                selected = random.sample(records, PER_TITLE_CAP)
                sampled_buckets += 1
            else:
                selected = records
                full_buckets += 1

            for rec in selected:
                # 寫出時不含 jfull（corpus.jsonl 是 metadata index）
                # jfull 需要時從 source_path 回讀，節省空間
                out_rec = {k: v for k, v in rec.items() if k != "jfull"}
                fout.write(json.dumps(out_rec, ensure_ascii=False) + "\n")
                kept += 1
                kind_counter[rec["kind"]] += 1
                title_counter[title] += 1

    # --- 統計報告 ---
    print("\n" + "=" * 55)
    print(f"最終語料庫：{kept:,} 筆")
    print(f"  刑事：{kind_counter['criminal']:,}")
    print(f"  民事：{kind_counter['civil']:,}")
    print(f"輸出：{out_path}")
    print(f"\n案由桶：{len(buckets):,} 種")
    print(f"  截頂（>200 筆，抽樣）：{sampled_buckets:,} 種")
    print(f"  完整保留（<=200 筆）：{full_buckets:,} 種")

    print("\n--- 刑事 Top 15 案由 ---")
    crim_titles = Counter({
        t: c for t, c in title_counter.items()
        if any(r["kind"] == "criminal" for r in buckets[t][:1])
    })
    for t, c in crim_titles.most_common(15):
        total_in_bucket = len(buckets[t])
        print(f"  {t}: {c} (原 {total_in_bucket:,})")

    print("\n--- 民事 Top 15 案由 ---")
    civil_titles = Counter({
        t: c for t, c in title_counter.items()
        if any(r["kind"] == "civil" for r in buckets[t][:1])
    })
    for t, c in civil_titles.most_common(15):
        total_in_bucket = len(buckets[t])
        print(f"  {t}: {c} (原 {total_in_bucket:,})")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
