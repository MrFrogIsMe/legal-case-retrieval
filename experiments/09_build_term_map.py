"""實驗 09：從語料學「案由 → 法條 + 特徵詞」法律術語表。

目的：為 HyDE 策略 C（受控生成）提供彈藥——從 81,644 判決自動學每個案由
的典型法條與特徵術語，讓 query 改寫被真實語料約束、不靠 LLM 腦補。

輸出：data/processed/legal_terms.json
  { 案由: { "count": N, "top_articles": [...], "top_terms": [...] } }

用法（home_wsl）：
    LCR_PROCESSED_DIR=/home/mrfrog/data/processed \\
      ~/.local/bin/uv run python -u experiments/09_build_term_map.py
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from lcr.config import settings  # noqa: E402
from lcr.extract.regex_extractor import extract_articles  # noqa: E402

MIN_CASES = 30  # 案由至少 30 筆才建術語（少於此統計不穩）
TOP_ARTICLES = 5
TOP_TERMS = 12

# 中文 2-4 字詞粗略切分（facts_summary 已是書面語，用 bigram 近似關鍵詞）
def _tokenize(text: str) -> list[str]:
    """抽中文 bigram + trigram 作為候選關鍵詞。"""
    text = re.sub(r"[^\u4e00-\u9fa5]", "", text)
    toks = []
    for n in (2, 3):
        for i in range(len(text) - n + 1):
            toks.append(text[i : i + n])
    return toks
# 停用詞（判決書高頻但無區辨力）
_STOP = {
    "被告", "被害", "法院", "認定", "行為", "事實", "證據", "判決", "裁定", "如主",
    "主文", "民國", "新臺", "臺幣", "經查", "本件", "被移", "移送", "處分", "受處",
    "違反", "規定", "情節", "如下", "所為", "犯行", "審理", "辯護", "公訴", "起訴",
}


def main() -> int:
    processed = settings.processed_dir

    # 載入 corpus(案由) + segmented(原文供抽法條) + gpt(facts_summary)
    title_of: dict[str, str] = {}
    with (processed / "corpus.jsonl").open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            title_of[d["jid"]] = d.get("title", "")

    seg_text: dict[str, str] = {}
    with (processed / "segmented.jsonl").open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            seg_text[d["jid"]] = (
                d.get("main", "") + d.get("facts", "") + d.get("reasoning", "")
            )

    fs_of: dict[str, str] = {}
    with (processed / "gpt_extract_all.jsonl").open(encoding="utf-8") as f:
        for line in f:
            d = json.loads(line)
            g = d.get("gpt", {})
            if isinstance(g, dict):
                fs_of[d["jid"]] = g.get("facts_summary", "") or ""

    # 依案由分組
    by_title: dict[str, list[str]] = defaultdict(list)
    for jid, t in title_of.items():
        by_title[t].append(jid)

    # 全域詞頻（算 IDF 用）
    doc_freq: Counter[str] = Counter()
    title_terms: dict[str, Counter] = {}
    title_articles: dict[str, Counter] = {}

    for title, jids in by_title.items():
        if len(jids) < MIN_CASES:
            continue
        tc: Counter[str] = Counter()
        ac: Counter[str] = Counter()
        for jid in jids:
            # 法條（從原文抽）
            for a in extract_articles(seg_text.get(jid, "")):
                ac[a] += 1
            # 特徵詞（從 facts_summary）
            toks = set(_tokenize(fs_of.get(jid, "")))
            for tok in toks:
                if tok not in _STOP:
                    tc[tok] += 1
                    doc_freq[tok] += 1
        title_terms[title] = tc
        title_articles[title] = ac

    n_titles = len(title_terms)
    # TF-IDF 選特徵詞：tf(案由內出現比例) * idf(跨案由稀有度)
    term_map: dict[str, dict] = {}
    for title, tc in title_terms.items():
        n = len(by_title[title])
        scored = []
        for tok, cnt in tc.items():
            tf = cnt / n
            n_titles_with = sum(1 for t2 in title_terms if title_terms[t2].get(tok))
            idf = math.log(n_titles / (1 + n_titles_with))
            scored.append((tok, tf * idf))
        top_terms = [t for t, _ in sorted(scored, key=lambda x: -x[1])[:TOP_TERMS]]
        top_arts = [a for a, _ in title_articles[title].most_common(TOP_ARTICLES)]
        term_map[title] = {
            "count": n,
            "top_articles": top_arts,
            "top_terms": top_terms,
        }

    out = processed / "legal_terms.json"
    out.write_text(json.dumps(term_map, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"術語表建立完成：{len(term_map)} 案由 → {out}")
    # 印幾個範例
    for t in ("公共危險", "過失傷害", "妨害名譽", "竊盜"):
        if t in term_map:
            m = term_map[t]
            print(f"\n[{t}] ({m['count']}筆)")
            print(f"  法條: {m['top_articles']}")
            print(f"  特徵詞: {m['top_terms']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
