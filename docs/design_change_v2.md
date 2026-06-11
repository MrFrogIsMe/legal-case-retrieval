# 設計變更 v2：收斂至「地方法院一審刑事」單一範圍

> 決策日期：2026-06-11
> 取代：design_change_v1.md 的「刑民分流 schema」（v1 廢棄，理由見下）
> 對應更新：data_design_v1.md、design_v1.md 均已改為只刑事

---

## 1. 決策

專案範圍由「刑事 + 民事」**收斂為「僅地方法院一審刑事」**：

- 完全排除民事（1,074,639 筆）
- 完全排除高等法院（二審）、最高法院（三審）
- 只保留地方法院一審、民國 105-114 年、排除程序性（JCASE 含「聲」等）

理由詳見 data_design_v1.md 第 1、3 節（語意聚焦、避免一案三吃冗餘、貼近使用者焦慮）。

---

## 2. 資料現況盤點（2026-06-11 實測）

home_wsl:/home/mrfrog/data/processed/

| 檔案 | 筆數 | 狀態 | 說明 |
|------|------|------|------|
| corpus.jsonl | 8,244 | ✅ 已對齊新範圍 | 全 criminal、全地院、無「聲」、105-114 年（分層抽樣 CAP=50） |
| segmented.jsonl | 35,268 | ❌ 舊版（刑民混） | 與新 corpus 僅 5,534 筆交集 |
| gpt_extract_all.jsonl | 35,268 | ❌ 舊版（刑民混） | 與新 corpus 僅 5,534 筆交集 |

**關鍵：新 corpus 的 8,244 筆中有 2,710 筆是舊資料完全沒有的**（新篩選+分層 seed 新抽進來），
無法靠「過濾舊檔」沿用 → segment 與 GPT 抽取都必須對新 corpus 全量重跑。

---

## 3. 需要重跑的項目

| 步驟 | 腳本 | 動作 | 預估 |
|------|------|------|------|
| 切段 | `experiments/02_segment.py --input corpus` | 重跑（吃新 corpus 8,244 筆）| < 1 分鐘 |
| GPT 抽取 | `experiments/04a_openai_batch.py` | 重跑（只刑事 schema，8,244 筆）| Batch 數十分鐘，費用 ~$1-2 |
| 建索引 | `experiments/05_build_index.py` | 待上兩步完成後跑 | 約 30-60 分鐘（GPU）|

重跑後三檔筆數應一致為 8,244。

---

## 4. 需要調整的 code

| 檔案 | 問題 | 調整 |
|------|------|------|
| `experiments/03_build_corpus.py` | working tree 改成只刑事但**未 commit**（風險：僅存 home_wsl）| 提交為正式版；PER_TITLE_CAP 對齊產生 corpus 的值（50）|
| `src/lcr/data/filter.py` | 仍含大量民事程序排除邏輯（死碼）| 保留 `is_criminal_procedural`/`is_district_court`/`is_year_in_range`；民事函式標記 deprecated 或移除 |
| `src/lcr/extract/schemas.py` | 民事 schema 已無用 | 保留不影響（get_schema 對 criminal 正確）；可標記 deprecated |
| `src/lcr/retrieval/kind_classifier.py` | infer_kind 回傳 both/civil 已無意義 | 簡化或移除（搜尋永遠 criminal）|
| `src/lcr/retrieval/searcher.py` | kind_filter 參數預設 both | 預設改 criminal；或保留參數但實務上單一 collection |
| `experiments/06_make_evalset.py` | MIN_FACTS_LEN=60 濾不掉程序性殘留 | 加 JCASE 程序性過濾（雖 corpus 已乾淨，防呆）|

---

## 5. v1 刑民分流 schema 廢棄理由

design_change_v1.md 為了民事 76.9% 佔比而拆雙 schema。
範圍收斂為純刑事後，民事 schema 與 kind 分流邏輯全部失去意義，故 v1 廢棄。
刑事 schema（CRIMINAL_SCHEMA）續用。

---

## 6. 建議執行順序

1. 先把 03_build_corpus.py（只刑事版）commit + push，消除「關鍵 code 只在 working tree」風險。
2. 重跑 02_segment（快、免費）。
3. 重跑 04a GPT 抽取（只刑事 8,244 筆）。
4. 三檔對齊後，再做檢索消融實驗（評估集 06 + 評估 07 + 索引參數化）。
