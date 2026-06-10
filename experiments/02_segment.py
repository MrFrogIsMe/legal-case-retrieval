"""實驗 02：結構切段。

讀 subset.jsonl，排除聲明異議類，對每筆回讀 JFULL 做結構切段，輸出：
  1. data/processed/segmented.jsonl — 每行含 jid/metadata + main/facts/reasoning + layout
  2. 終端統計：排除數、layout 分布、完整率

用法（repo 根目錄；資料在 home_wsl，建議 tmux）：
    LCR_DATASET_ROOT=/home/mrfrog/code/lawundry_test/Dataset \
      uv run python experiments/02_segment.py
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lcr.config import settings  # noqa: E402
from lcr.data.segment import is_sheng_yi, segment  # noqa: E402


def main() -> int:
    subset_path = settings.processed_dir / "subset.jsonl"
    if not subset_path.exists():
        print(f"[錯誤] 找不到 {subset_path}，請先跑 01_subset_filter.py")
        return 1

    dataset_root = settings.dataset_root
    if not dataset_root.exists():
        print(f"[錯誤] 找不到資料根目錄：{dataset_root}")
        return 1

    out_path = settings.processed_dir / "segmented.jsonl"

    total = 0
    excluded_sheng_yi = 0
    read_fail = 0
    kept = 0
    layout_counter: Counter[str] = Counter()
    complete = 0

    with subset_path.open(encoding="utf-8") as fin, out_path.open(
        "w", encoding="utf-8"
    ) as fout:
        for line in fin:
            total += 1
            r = json.loads(line)

            if is_sheng_yi(jcase=r["jcase"], title=r["title"]):
                excluded_sheng_yi += 1
                continue

            src = dataset_root / r["source_path"]
            with src.open(encoding="utf-8") as fp:
                d = json.loads(fp.read(), strict=False)

            seg = segment(d.get("JFULL", ""))
            layout_counter[seg.layout] += 1
            if seg.is_complete:
                complete += 1

            kept += 1
            fout.write(
                json.dumps(
                    {
                        "jid": r["jid"],
                        "title": r["title"],
                        "jcase": r["jcase"],
                        "court": r["court"],
                        "jdate": r["jdate"],
                        "main": seg.main,
                        "facts": seg.facts,
                        "reasoning": seg.reasoning,
                        "layout": seg.layout,
                        "is_complete": seg.is_complete,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    print("\n" + "=" * 50)
    print(f"子集輸入：{total:,}")
    print(f"排除聲明異議：{excluded_sheng_yi:,}")
    print(f"讀檔失敗：{read_fail:,}")
    print(f"切段輸出：{kept:,}")
    print(f"輸出：{out_path}")

    print("\n--- layout 分布 ---")
    for lay, c in layout_counter.most_common():
        print(f"  {lay}: {c:,} ({c / kept * 100:.1f}%)")

    print(f"\n--- 完整率（主文+事實或理由）：{complete:,} / {kept:,} "
          f"({complete / kept * 100:.1f}%) ---")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
