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
        print(f"讀取已有 batch_id：\n{batch_id}")

    if batch_id:
        batch_ids = [bid.strip() for bid in batch_id.replace(",", "\n").split("\n") if bid.strip()]
        print(f"\n--- 發現共有 {len(batch_ids)} 個批次任務，開始查詢狀態 ---")
        
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)
        
        completed_ids = []
        pending_ids = []
        
        for idx, bid in enumerate(batch_ids, 1):
            try:
                b = client.batches.retrieve(bid)
                status = b.status
                counts = b.request_counts
                print(
                    f"  Chunk {idx}/{len(batch_ids)}: {bid} "
                    f"[{status}] total={counts.total} "
                    f"completed={counts.completed} failed={counts.failed}"
                )
                if status == "completed":
                    completed_ids.append(bid)
                else:
                    pending_ids.append(bid)
            except Exception as e:
                print(f"  查詢 Chunk {idx} ({bid}) 失敗：{e}")
        
        if completed_ids:
            print(f"\n--- 開始下載並合併 {len(completed_ids)} 個已完成的批次 ---")
            temp_records = {}
            
            # 如果原本的 gpt_extract.jsonl 已經有資料，先讀進來 (去重保留)
            if out_path.exists():
                try:
                    with out_path.open(encoding="utf-8") as fin:
                        for line in fin:
                            if line.strip():
                                d = json.loads(line)
                                temp_records[d["jid"]] = d["gpt"]
                    print(f"  載入原有已下載紀錄：{len(temp_records):,} 筆")
                except Exception:
                    pass
            
            # 下載各完成批次並存入字典
            for bid in completed_ids:
                b = client.batches.retrieve(bid)
                if b.output_file_id:
                    print(f"  下載 {bid}...")
                    try:
                        content = client.files.content(b.output_file_id)
                        chunk_count = 0
                        for line in content.text.splitlines():
                            if not line.strip():
                                continue
                            result = json.loads(line)
                            custom_id = result.get("custom_id", "")
                            try:
                                body = result["response"]["body"]
                                extracted = json.loads(body["choices"][0]["message"]["content"])
                            except Exception as e:
                                extracted = {"error": str(e)}
                            temp_records[custom_id] = extracted
                            chunk_count += 1
                        print(f"    成功解析：{chunk_count:,} 筆")
                    except Exception as e:
                        print(f"    下載/解析 {bid} 失敗：{e}")
            
            # 寫回檔案
            with out_path.open("w", encoding="utf-8") as fout:
                for jid, gpt in temp_records.items():
                    fout.write(json.dumps({"jid": jid, "gpt": gpt}, ensure_ascii=False) + "\n")
            print(f"下載合併完成！當前共計：{len(temp_records):,} 筆 ➔ {out_path}")
        
        if pending_ids:
            print(f"\n還有 {len(pending_ids)} 個批次任務仍在執行中。")
            print("建議稍後再重新執行本腳本進行下載。")
        else:
            print("\n恭喜！所有批次任務都已下載合併完成！")
            
        return 0

    # --- 新提交 ---
    print("載入語料...")
    records = load_corpus_with_segments(
        corpus_path, segmented_path, dataset_root, n=args.n
    )

    MAX_BATCH_SIZE_MB = 150  # OpenAI 上限 200MB，保守設 150MB

    print(f"建立 batch 請求檔 → {batch_requests_path}")
    count = create_batch_file(records, batch_requests_path)
    print(f"  請求筆數：{count:,}")

    # 費用估算
    est_input_tokens = count * 1500
    est_output_tokens = count * 300
    est_cost = (est_input_tokens / 1e6 * 0.25 + est_output_tokens / 1e6 * 2.0) * 0.5
    print(f"  費用估算（Batch 折半）：${est_cost:.2f} USD")

    file_size_mb = batch_requests_path.stat().st_size / 1024 / 1024
    print(f"  批次檔大小：{file_size_mb:.1f} MB")

    # 自動確認提交
    if file_size_mb > MAX_BATCH_SIZE_MB:
        # 超過限制，自動拆批
        n_chunks = int(file_size_mb / MAX_BATCH_SIZE_MB) + 1
        chunk_size = len(records) // n_chunks + 1
        print(
            f"  超過 {MAX_BATCH_SIZE_MB}MB 限制，"
            f"自動拆成 {n_chunks} 個 sub-batch（每批 ~{chunk_size} 筆）"
        )

        batch_ids = []
        for i in range(n_chunks):
            chunk = records[i * chunk_size: (i + 1) * chunk_size]
            if not chunk:
                break
            chunk_path = processed / f"batch_requests_chunk{i}.jsonl"
            create_batch_file(chunk, chunk_path)
            print(f"  提交 chunk {i+1}/{n_chunks}（{len(chunk)} 筆）...")
            bid = submit_batch(chunk_path)
            batch_ids.append(bid)

        # 儲存所有 batch_id
        all_ids = "\n".join(batch_ids)
        batch_id_path.write_text(all_ids)
        print(f"\n所有 batch_id 已存到：{batch_id_path}")
        for bid in batch_ids:
            print(f"  {bid}")
        print("可用以下指令個別查詢進度：")
        print("  uv run python experiments/04a_openai_batch.py --batch-id <batch_id>")
    else:
        batch_id = submit_batch(batch_requests_path)
        batch_id_path.write_text(batch_id)
        print(f"batch_id 已存到：{batch_id_path}")
        print(f"  uv run python experiments/04a_openai_batch.py --batch-id {batch_id}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
