"""實驗 06：建立合成評估集（口語 query → relevant_jid）。

對齊 docs/design_v1.md 第 5.1 節。

流程：
  1. 讀 gpt_extract_all.jsonl（facts_summary）+ corpus.jsonl（kind/title）
  2. 分層抽樣（刑事/民事按比例），跳過事實摘要過短的程序性案件
  3. 對每份判決用 gemini-3.5-flash 生成 2-3 個口語 query
  4. 輸出 eval.jsonl，每行 {query, relevant_jid, kind, title, facts_summary}

用法（home_wsl，建議 tmux；資料在該機）：
    LCR_PROCESSED_DIR=/home/mrfrog/data/processed \\
      ~/.local/bin/uv run python experiments/06_make_evalset.py --n 50

    # 先 smoke test 3 筆
    LCR_PROCESSED_DIR=/home/mrfrog/data/processed \\
      ~/.local/bin/uv run python experiments/06_make_evalset.py --n 3

備注：
  - gemini-3.5-flash 為推理模型，eval_max_tokens 已設 4096（見 config）
  - 每份判決約 1-3 秒，50 份約 2-3 分鐘
  - 失敗（parse_failed/empty）的判決會跳過並計數，不中斷
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lcr.config import settings  # noqa: E402
from lcr.eval.query_gen import generate_queries  # noqa: E402

# 事實摘要短於此長度者多為程序性案件（聲請駁回等），不適合當類案查詢標的
MIN_FACTS_LEN = 60


def load_candidates(processed: Path) -> list[dict]:
    """合併 corpus（kind/title）+ gpt_extract_all（facts_summary），回傳候選清單。"""
    corpus: dict[str, dict] = {}
    with (processed / "corpus.jsonl").open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            corpus[d["jid"]] = d

    candidates: list[dict] = []
    with (processed / "gpt_extract_all.jsonl").open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            g = d.get("gpt", {})
            if not isinstance(g, dict) or "error" in g:
                continue
            facts = (g.get("facts_summary") or "").strip()
            if len(facts) < MIN_FACTS_LEN:
                continue
            meta = corpus.get(d["jid"], {})
            candidates.append({
                "jid": d["jid"],
                "kind": meta.get("kind", "criminal"),
                "title": meta.get("title", ""),
                "facts_summary": facts,
            })
    return candidates


def stratified_sample(
    candidates: list[dict], n: int, seed: int = 42
) -> list[dict]:
    """依 kind 比例分層抽樣 n 份。"""
    rng = random.Random(seed)
    by_kind: dict[str, list[dict]] = {}
    for c in candidates:
        by_kind.setdefault(c["kind"], []).append(c)

    total = len(candidates)
    sampled: list[dict] = []
    for kind, items in by_kind.items():
        quota = max(1, round(n * len(items) / total))
        rng.shuffle(items)
        sampled.extend(items[:quota])

    rng.shuffle(sampled)
    return sampled[:n]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=50, help="抽樣判決份數")
    parser.add_argument("--per-doc", type=int, default=3, help="每份判決生成 query 數")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    processed = settings.processed_dir
    if not (processed / "gpt_extract_all.jsonl").exists():
        print(f"[錯誤] 找不到 gpt_extract_all.jsonl：{processed}")
        return 1

    print(f"載入候選（事實摘要 >= {MIN_FACTS_LEN} 字）...")
    candidates = load_candidates(processed)
    print(f"  候選總數：{len(candidates):,}")
    kc = Counter(c["kind"] for c in candidates)
    print(f"  kind 分布：{dict(kc)}")

    sampled = stratified_sample(candidates, args.n, seed=args.seed)
    print(f"抽樣 {len(sampled)} 份（刑民按比例）")

    out_path = processed / "eval.jsonl"
    pairs = 0
    failed = 0
    sk = Counter(c["kind"] for c in sampled)

    with out_path.open("w", encoding="utf-8") as fout:
        for i, c in enumerate(sampled, 1):
            res = generate_queries(
                jid=c["jid"], facts=c["facts_summary"], n=args.per_doc
            )
            if res.error or not res.queries:
                failed += 1
                print(f"  [{i}/{len(sampled)}] {c['jid']} 失敗：{res.error}")
                continue
            for q in res.queries:
                fout.write(json.dumps({
                    "query": q,
                    "relevant_jid": c["jid"],
                    "kind": c["kind"],
                    "title": c["title"],
                    "facts_summary": c["facts_summary"],
                }, ensure_ascii=False) + "\n")
                pairs += 1
            print(f"  [{i}/{len(sampled)}] {c['jid']} → {len(res.queries)} queries")

    print("\n" + "=" * 50)
    print(f"抽樣判決：{len(sampled)}（{dict(sk)}）")
    print(f"失敗跳過：{failed}")
    print(f"產出 (query, relevant_jid) 對：{pairs}")
    print(f"輸出：{out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
