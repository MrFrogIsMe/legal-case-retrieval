"""探查判決書 JFULL 的分段標記模式，供切段 regex 設計。

讀 subset.jsonl，依 source_path 回讀原始 JSON，統計各種分段標記的出現情況，
並針對不同案件類型（交易/交訴/交簡/交聲）各印幾份樣本的結構。
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

DATASET_ROOT = Path("/home/mrfrog/code/lawundry_test/Dataset")
SUBSET = Path("data/processed/subset.jsonl")

# 候選分段標記（判決書常見）
MARKERS = ["主文", "事實", "犯罪事實", "理由", "事實及理由", "事實及理由要領", "犯罪事實及證據"]

# 各標記的「正規行首」樣態：判決書中標題常獨立成段，前後有空白/全形空格
# 例：「    主  文」「    事  實」「    理  由」
marker_patterns = {
    m: re.compile(r"[\r\n][\u3000\s]*" + r"[\u3000\s]*".join(list(m)) + r"[\u3000\s]*[\r\n]")
    for m in MARKERS
}


def load_full(source_path: str) -> dict | None:
    p = DATASET_ROOT / source_path
    try:
        with p.open(encoding="utf-8") as fp:
            return json.load(fp)
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return None


def main() -> int:
    if not SUBSET.exists():
        print(f"找不到 {SUBSET}")
        return 1

    records = [json.loads(line) for line in SUBSET.open(encoding="utf-8")]
    print(f"子集總數：{len(records):,}")

    # 案由 / JCASE 分布（含聲明異議辨識）
    sheng_yi = sum(
        1 for r in records if "聲" in r["jcase"] or "聲明異議" in r["title"]
    )
    print(f"聲明異議類（JCASE 含『聲』或案由含『聲明異議』）：{sheng_yi:,}")
    print(f"排除聲明異議後：{len(records) - sheng_yi:,}")

    # 對非聲明異議類抽樣，統計分段標記出現率
    import random

    random.seed(42)
    sample = random.sample(
        [r for r in records if "聲" not in r["jcase"] and "聲明異議" not in r["title"]],
        min(2000, len(records)),
    )

    marker_hit = Counter()
    by_jcase_struct = {}  # jcase -> Counter of 標記組合
    samples_by_type = {}  # jcase prefix -> 一份樣本的標記順序

    loaded = 0
    for r in sample:
        d = load_full(r["source_path"])
        if not d:
            continue
        loaded += 1
        jfull = d.get("JFULL", "")
        present = []
        for m, pat in marker_patterns.items():
            if pat.search(jfull):
                marker_hit[m] += 1
                present.append(m)

        jcase = r["jcase"]
        key = tuple(sorted(present))
        by_jcase_struct.setdefault(jcase, Counter())[key] += 1

        # 收集各類型一份樣本（標記在文中的出現順序）
        prefix = jcase
        if prefix not in samples_by_type and present:
            order = sorted(present, key=lambda m: marker_patterns[m].search(jfull).start())
            samples_by_type[prefix] = {
                "jid": r["jid"],
                "title": r["title"],
                "order": order,
                "len": len(jfull),
            }

    print(f"\n實際讀取：{loaded:,} 份")
    print("\n=== 各分段標記出現率 ===")
    for m, c in marker_hit.most_common():
        print(f"  {m}: {c:,} ({c / loaded * 100:.1f}%)")

    print("\n=== 各 JCASE 的標記組合（前幾名）===")
    for jcase in sorted(by_jcase_struct, key=lambda k: -sum(by_jcase_struct[k].values()))[:8]:
        total = sum(by_jcase_struct[jcase].values())
        print(f"\n  [{jcase}] 共 {total} 份")
        for combo, c in by_jcase_struct[jcase].most_common(4):
            print(f"    {list(combo)}: {c}")

    print("\n=== 各類型樣本的標記順序 ===")
    for prefix, info in list(samples_by_type.items())[:12]:
        print(f"  [{prefix}] {info['title']} (len={info['len']}) → {info['order']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
