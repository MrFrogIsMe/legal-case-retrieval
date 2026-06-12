# AGENT.md — 專案索引

法律判決類案搜尋系統（生成式 AI 的人文導論期末專題）

從口語事由出發，於台灣刑事判決書中檢索事實相似的歷史案例，
彙整呈現「過去法院怎麼判、賠償範圍、為什麼」。#Law #RAG #刑法

## 文件清單（docs/）

- `docs/design_v1.md` — 系統初版設計（技術）。新成員先讀這份。內容包含：
  - 專題目標與系統定位（類案檢索工具，非法律建議）
  - 資料分析（53 萬刑事判決實測、選擇性偏差等真實數字）
  - 系統架構（離線預處理 + 線上查詢兩階段）
  - 四層可驗證要素抽取管線（Outlines + regex + 一致性投票 + NLI）
  - RAG 架構（BGE-M3 + BM25 + RRF + bge-reranker）
  - 評估設計（合成評估集、Recall@5/MRR、消融實驗、RAGAS）
  - 可信度與法律正當性（citation grounding、4 個法律地雷）
  - 可引用文獻地圖（9 篇論文對應設計決策）

- `docs/product_v1.md` — 產品設計。最終形態、功能清單、介面分層、使用者需求。
  - 四方向介面（A 對話引導 / B 案例對比 / C 結果儀表板 / D 透明推理）疊成單頁
  - 三種 Persona，以漸進揭露同時兼顧門外漢與法律基礎使用者
  - 對應後端 API 端點與開發優先級

- `docs/roadmap_v1.md` — 開發路線圖。從實驗到部署的階段、時程、repo 策略。
  - repo 策略（實驗單 repo → 工程拆前後端）
  - 實驗階段 3-4 週規劃（資料管線 / 檢索實驗 / 抽取可信度 / 評估報告）
  - 工程與部署（路線 B：FastAPI + docker-compose + nginx + GitHub Actions CI/CD + Test）

- `docs/api_v1.md` — API 規格（前後端契約）。6 個端點完整 request/response schema、
  錯誤格式、前端 mock 開發指引。**6 端點皆已實作並實機驗證**（見第 9 節實作備註）。
  - 對應 mock 資料在 `mock/`（見 `mock/README.md`）

- `docs/data_design_v1.md` — 資料設計。子集篩選策略與排除規則完整記錄。
  - 時間篩選（民國 105-114 年）
  - 第一刀：程序性案件排除規則（刑事 + 民事，含 JCASE/案由清單）
  - 第二刀：分層抽樣（50 筆/案由，保留多樣性）
  - 不納入說明（行政、懲戒、最高法院、104 年前）

- `docs/design_change_v1.md` — 設計變更記錄：刑民分流 schema。（已被 v2 廢棄）
  - 觸發原因：GPT batch 50 筆評估，verdict 54% 回「其他」
  - 方案 B：刑事/民事各自 schema（schemas.py）
  - 搜尋時 kind 判斷邏輯（kind_classifier.py）
  - 受影響檔案清單

- `docs/design_change_v2.md` — 設計變更：收斂至「僅地方法院一審刑事」。
  - 排除民事、二三審；資料現況盤點與需重跑/調整清單；v1 刑民分流廢棄理由

- `docs/design_change_v3.md` — 設計變更：dense/sparse 分流 + 法條入 BM25（regex）。
  - dense 餵純事實摘要、sparse 餵摘要+案由+法條號；法條用 regex 不用 LLM；白名單去雜訊

- `docs/HANDOFF.md` — 交接文件。環境/資料現況/已完成/待完成/常用指令/已知坑。
  - 接手者先讀這份 + design_change_v2（純刑事收斂）

## 資料

- 來源：司法院開放資料（opendata.judicial.gov.tw）
- 位置：`ssh home_wsl:/home/mrfrog/code/lawundry_test/Dataset`
- 規模：刑事判決 53 萬筆；目標子集（過失傷害/公共危險/肇逃）約 10 萬筆

## 開發規範

- 系統定位為「類案檢索工具」，非法律建議；禁止對個案做預測。
- 資料有選擇性偏差：純財損（如僅後照鏡損壞）在刑事上多不起訴，須主動揭露。
- Python 一律用 uv（`uv run`、`uv add`），依賴權威來源為 pyproject.toml。
- 每個任務開新分支（feat/... 或 fix/...），不在 main 開發。
- Conventional Commits，commit message 一行英文寫重點。

## 專案結構

```
src/lcr/            核心可重用模組（實驗 + 工程階段共用）
  config.py         集中設定（路徑、參數，禁止他處直接讀 env）
  data/filter.py    子集篩選純邏輯（刑民通用，含程序性排除）
  data/segment.py   判決書結構切段（主文/事實/理由）
  extract/
    schemas.py      刑事 / 民事要素抽取 schema（分開定義）
    regex_extractor.py  regex 層（法條、金額、判決結果）
    openai_extractor.py OpenAI Batch API 抽取（gpt-5-mini）
  retrieval/
    kind_classifier.py  從事由推斷 criminal/civil/both
    indexer.py      BGE-M3 dense + BM25s sparse 索引建立
    searcher.py     混合檢索 + RRF 融合 + search_pipeline（最佳線上管線）
    case_store.py   案例資料倉（extract 常駐 + segmented lazy 讀 + stats 聚合）
app/                FastAPI 後端（工程階段）
  main.py           6 端點（health/search/case/clarify/trace/stats）
  schemas.py        pydantic 請求/回應契約
  analysis.py       業務純函式（法條推斷、citation grounding、對比、trace、clarify 規則）
  clarify.py        clarify 的 LLM 層（最簡，gemini gateway）
  data/legal_terms.json  案由→法條→特徵詞術語表（資料驅動法條推斷，隨碼進 image）
experiments/        實驗腳本（跑一次產數據，可拋棄）
  NN_xxx.py         依序編號（12 為檢索品質回歸把關）
  results/          各實驗結果筆記（.md）
tests/              pytest 單元測試（92 passed）
data/               原始與處理產物（gitignore，不進版控）
mock/               前端 mock 資料
docs/               設計文件
Dockerfile          生產映像（uv + FastAPI，索引走 volume）
docker-compose.yml  部署編排（api + 選用 nginx）
.github/workflows/ci.yml  CI（lint-test + docker-build）
```

### 實驗階段執行

資料在 `home_wsl`，於該機 tmux 中跑（量大、SSH 易斷）：

```bash
LCR_DATASET_ROOT=/home/mrfrog/code/lawundry_test/Dataset \
LCR_PROCESSED_DIR=/home/mrfrog/data/processed \
  uv run python experiments/03_build_corpus.py
```

注意：務必用絕對路徑覆寫 LCR_DATASET_ROOT 和 LCR_PROCESSED_DIR，
避免從不同 cwd 啟動時輸出到錯誤位置。

## 文件慣例

- 專案架構、流程、設計決策一律寫在 docs/。
- 新設計文件命名 `<type>_v<number>.md`（如 design_v2.md），並在本檔補上連結與一句話摘要。
