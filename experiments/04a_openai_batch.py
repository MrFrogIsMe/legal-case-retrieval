"""實驗 04a：OpenAI Batch 抽取。

流程：
  1. 從 corpus.jsonl 讀取 metadata
  2. 回讀原始 JFULL + 切段結果（segmented.jsonl）
  3. 建立 batch .jsonl → 上傳 → 提交
  4. 輪詢完成 → 下載結果到 gpt_extract.jsonl

用法（在 repo 根目錄）：
  # 先跑 50 筆測試
  LCR_DATASET_ROOT=... LCR_PROCESSED_DIR=... \
    uv run python experiments/04a_openai_batch.py --n 50

  # 全量（約 35k 筆，費用 ~$8 USD，Batch 折半後 ~$4）
  LCR_DATASET_ROOT=... LCR_PROCESSED_DIR=... \
    uv run python experiments/04a_openai_batch.py

  # 查詢已有 batch 狀態（不重新提交）
  uv run python experiments/04a_openai_batch.py --batch-id batch_xxx

費用估算（gpt-5-mini，Batch 折半）：
  每筆輸入約 1,500 token，輸出約 300 token
  35k 筆 → input $0.25/1M * 0.5 * 52.5M = $6.6
         → output $2/1M * 0.5 * 10.5M = $10.5
  合計約 $8-12 USD（視全文長度而定）
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lcr.config import settings  # noqa: E402
from lcr.extract.openai_extractor import (  # noqa: E402
    create_batch_file,
    download_results,
    poll_batch,
    submit_batch,
)


def load_corpus_with_segments(
    corpus_path: Path,
    segmented_path: Path | None,
    dataset_root: Path,
    n: int | None = None,
    seed: int = 42,
) -> list[dict]:
    """讀取 corpus + 切段結果，合併成完整 record。"""
    # 讀 corpus
    records = []
    with corpus_path.open(encoding="utf-8") as f:
        for line in f:
            records.append(json.loads(line))

    # 讀 segmented（若有）
    seg_map: dict[str, dict] = {}
    if segmented_path and segmented_path.exists():
        with segmented_path.open(encoding="utf-8") as f:
            for line in f:
                d = json.loads(line)
                seg_map[d["jid"]] = d
        print(f"載入切段結果：{len(seg_map):,} 筆")

    # 合併
    merged = []
    for rec in records:
        jid = rec["jid"]
        seg = seg_map.get(jid, {})
        merged_rec = {**rec}
        merged_rec["main"] = seg.get("main", "")
        merged_rec["facts"] = seg.get("facts", "")
        merged_rec["reasoning"] = seg.get("reasoning", "")

        # 若沒有切段結果，回讀 JFULL 前 3000 字當 reasoning
        if not merged_rec["reasoning"] and rec.get("source_path"):
            src = dataset_root / rec["source_path"]
            try:
                with src.open(encoding="utf-8") as fp:
                    d = json.loads(fp.read(), strict=False)
                merged_rec["reasoning"] = d.get("JFULL", "")[:3000]
            except (OSError, ValueError):
                pass

        merged.append(merged_rec)

    if n:
        random.seed(seed)
        merged = random.sample(merged, min(n, len(merged)))
        print(f"抽樣：{len(merged)} 筆")
    else:
        print(f"全量：{len(merged):,} 筆")

    return merged


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=None, help="只跑 N 筆（測試用）")
    parser.add_argument("--batch-id", default=None, help="已有 batch_id，跳過提交直接查詢")
    parser.add_argument("--download-only", action="store_true", help="只下載結果不輪詢")
    args = parser.parse_args()

    processed = settings.processed_dir
    dataset_root = settings.dataset_root

    corpus_path = processed / "corpus.jsonl"
    segmented_path = processed / "segmented.jsonl"
    batch_requests_path = processed / "batch_requests.jsonl"
    batch_id_path = processed / "batch_id.txt"
    out_path = processed / "gpt_extract.jsonl"

    if not settings.openai_api_key:
        print("[錯誤] OPENAI_API_KEY 未設定，請在 .env 加入")
        return 1

    # --- 查詢既有 batch ---
    # 只有當沒有指定 --n（即非測試模式）時，才自動讀取已有的 batch_id.txt
    batch_id = args.batch_id
    if not batch_id and not args.n and batch_id_path.exists():
        batch_id = batch_id_path.read_text().strip()
        print(f"讀取已有 batch_id：{batch_id}")

    if batch_id and args.download_only:
        n = download_results(batch_id, out_path)
        print(f"下載完成：{n} 筆 → {out_path}")
        return 0

    if batch_id:
        print(f"輪詢 batch：{batch_id}")
        batch = poll_batch(batch_id, poll_interval=30)
        if batch["status"] == "completed":
            n = download_results(batch_id, out_path)
            print(f"完成：{n} 筆 → {out_path}")
        else:
            print(f"Batch 狀態：{batch['status']}")
        return 0

    # --- 新提交 ---
    print("載入語料...")
    records = load_corpus_with_segments(
        corpus_path, segmented_path, dataset_root, n=args.n
    )

    print(f"建立 batch 請求檔 → {batch_requests_path}")
    count = create_batch_file(records, batch_requests_path)
    print(f"  請求筆數：{count:,}")

    # 費用估算
    est_input_tokens = count * 1500
    est_output_tokens = count * 300
    est_cost = (est_input_tokens / 1e6 * 0.25 + est_output_tokens / 1e6 * 2.0) * 0.5
    print(f"  費用估算（Batch 折半）：${est_cost:.2f} USD")

    # 自動確認提交，不需互動（全量也自動確認，適合背景跑）
    confirm = "y"
    if confirm != "y":
        print("取消")
        return 0

    batch_id = submit_batch(batch_requests_path)
    batch_id_path.write_text(batch_id)
    print(f"batch_id 已存到：{batch_id_path}")
    print("可用以下指令查詢進度：")
    print(f"  uv run python experiments/04a_openai_batch.py --batch-id {batch_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
