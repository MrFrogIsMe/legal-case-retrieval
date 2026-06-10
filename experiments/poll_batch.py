"""GPT 全量 batch 輪詢 + 下載合併腳本。

在 home_wsl 上執行：
    cd /home/mrfrog/code/legal-case-retrieval
    ~/.local/bin/uv run python -u experiments/poll_batch.py
"""
from __future__ import annotations

import datetime
import json
import time
from pathlib import Path

from openai import OpenAI

from lcr.config import settings

BATCH_IDS = [
    "batch_6a2960ac7a84819098c124b9ebc7a100",
    "batch_6a2960dea508819097f5bb29ff2e0036",
]
OUT_PATH = Path("/home/mrfrog/data/processed/gpt_extract_all.jsonl")


def main() -> None:
    client = OpenAI(api_key=settings.openai_api_key)

    print("=== 輪詢開始 ===", flush=True)
    while True:
        done = True
        for bid in BATCH_IDS:
            b = client.batches.retrieve(bid)
            ts = datetime.datetime.now().strftime("%H:%M")
            c = b.request_counts
            print(
                f"[{ts}] {bid[-10:]}: {b.status} "
                f"{c.completed}/{c.total} fail={c.failed}",
                flush=True,
            )
            if b.status not in ("completed", "failed", "expired"):
                done = False
        if done:
            break
        time.sleep(60)

    print("\n=== 下載合併中 ===", flush=True)
    ok = fail = 0
    with OUT_PATH.open("w", encoding="utf-8") as fout:
        for bid in BATCH_IDS:
            b = client.batches.retrieve(bid)
            if not b.output_file_id:
                print(f"  [{bid[-10:]}] 無 output_file_id，狀態={b.status}")
                continue
            content = client.files.content(b.output_file_id)
            for line in content.text.splitlines():
                if not line.strip():
                    continue
                raw = json.loads(line)
                jid = raw.get("custom_id", "")
                try:
                    extracted = json.loads(
                        raw["response"]["body"]["choices"][0]["message"]["content"]
                    )
                    fout.write(
                        json.dumps({"jid": jid, "gpt": extracted}, ensure_ascii=False)
                        + "\n"
                    )
                    ok += 1
                except Exception as e:
                    fout.write(
                        json.dumps(
                            {"jid": jid, "gpt": {"error": str(e)}},
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
                    fail += 1

    print(f"\n完成：ok={ok:,}  fail={fail:,}", flush=True)
    print(f"輸出：{OUT_PATH}", flush=True)


if __name__ == "__main__":
    main()
