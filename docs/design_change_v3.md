# 設計變更 v3：dense/sparse 分流檢索 + 法條入 BM25（regex）

> 決策日期：2026-06-11
> 對應 code：src/lcr/extract/regex_extractor.py、src/lcr/retrieval/indexer.py、experiments/05_build_index.py
> 對應設計：design_v1 第 3.2 節（雙路檢索）、第 8 節（法條用 BM25 不 embed）、NyayaRAG

---

## 1. 問題：法條從未進入檢索

review 既有管線發現一個落差：

- GPT 抽取的 `facts_summary` 是「不含法條引用」的白話摘要（schema 明文要求）。
- 舊 indexer 的 `_select_text` 把 **dense 與 sparse 餵同一份 facts_summary**。
- 結果：BM25 拿到的也是沒有法條的白話摘要 → **法條號碼從未被任何檢索路徑使用**。
- 這使 design_v1 第 3.2 節「BM25 用法條號碼查全文」與 NyayaRAG「檢索加入法條 +15%」的核心設計形同未實作。

法條原料其實一直都在 segmented.jsonl 的事實/理由段（原文含「刑法第185條之4」等），只是在抽取階段被洗掉、又沒被索引層接上。

---

## 2. 決策：dense 與 sparse 餵不同文字

| 路徑 | 索引文字 | 理由 |
|------|---------|------|
| Dense（BGE-M3 向量）| `facts_summary`（白話事實摘要）| 與使用者口語 query 抽象層級一致，語意比對最準。法條是符號非語意，**不進 dense**（design_v1 第 8 節已定）|
| Sparse（BM25）| `facts_summary + 案由title + 法條號` | BM25 是精確 token 比對，法條號（固定字串）最適合，補上後對齊 NyayaRAG |

法條清單同時寫入 ChromaDB metadata（`articles` 欄位），供前端顯示與 citation grounding 驗證。

---

## 3. 法條抽取：regex 不用 LLM

- **用 regex（regex_extractor.extract_articles），不重抽 GPT、零額外花費。**
- 對齊 design_v1 第 4 節 L2：「法條號用 regex 抽，固定格式不交給 LLM」。
- 法條號是固定格式，regex 比 LLM 準（不會抽錯號碼），且符合 citation grounding（法條由規則精確比對、不讓 LLM 自由生成，避免 13-21% 引用幻覺）。
- 正在跑的 GPT batch 抽 `facts_summary`（給 dense 用），與法條兩條線互不衝突，那批費用不浪費。

### 3.1 regex 收乾淨（白名單法律名）

舊 `_LAW_ARTICLE_RE` 用貪婪比對（第X條前任意 2-20 字當法律名），在真實判決抽出大量殘字雜訊
（如「亦因社會秩序維護法 20」「維護法並無類似刑法 85」「按公民政治權利公約 11」）。

改為**白名單法律名**（_LAW_NAMES，台灣刑事常見法律），依長度排序避免子字串截斷，
並支援「之N」（刑法 185-4）與「同法第X條」沿用前一法律名。

實測（同一筆 STEM,108,店秩易,25）：
- 修復前：`['亦因社會秩序維護法 20','公約及...施行法 2','刑法 85','同法 20','按公民政治權利公約 11','維護法並無類似刑法 85',...]`（髒）
- 修復後：`['刑法 85','社會秩序維護法 20','社會秩序維護法 32','社會秩序維護法 45']`（乾淨去重）

新增單元測試：subarticle（之N）、same_law（同法）、no_noise（殘字不該出現），共 20 tests pass。

---

## 4. 受影響檔案

| 檔案 | 異動 |
|------|------|
| `src/lcr/extract/regex_extractor.py` | extract_articles 改白名單版、支援之N/同法、去雜訊 |
| `src/lcr/retrieval/indexer.py` | `_select_text` 拆為 `_dense_text`（純摘要）/ `_sparse_text`（摘要+案由+法條）；dense metadata 加 articles |
| `experiments/05_build_index.py` | load_records 時 regex 抽法條塞入 record["articles"] |
| `tests/test_regex_extractor.py` | 補去雜訊 / 之N / 同法測試 |

---

## 5. 待驗證（下一步）

- 重建索引（05）後，跑檢索消融確認「BM25 加法條」是否真的提升（對齊 NyayaRAG 預期 +10~15%）。
- 此即 design_v1 Week 2 消融實驗「是否加法條」那一列，現在才真正可被執行。
