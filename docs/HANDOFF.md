# 交接文件：legal-case-retrieval 完成系統

> 撰寫日期：2026-06-12
> 目的：交接給下一個 agent，完成「法律判決類案搜尋系統」剩餘工作
> 當前 main：含純刑事檢索管線 + 法條 BM25 + 81,644 索引 + 完整檢索消融 + FastAPI 核心端點

---

## 0. 必讀（動手前）

依序讀這幾份，建立全貌：
1. `AGENT.md` — 專案索引與結構
2. `docs/design_v1.md` — 系統技術設計（檢索/抽取/評估/法律地雷）
3. `docs/design_change_v2.md` — **範圍已收斂為「地院一審純刑事」**（重要！民事/二三審全排除）
4. `docs/design_change_v3.md` — dense/sparse 分流 + 法條入 BM25
5. `docs/product_v1.md` — 產品形態與介面分層
6. `docs/api_v1.md` — 前後端 API 契約
7. `docs/roadmap_v1.md` — 開發階段規劃
8. `experiments/results/07_retrieval_ablation.md`、`11_relaxed_eval.md` — 檢索實驗結論（報告核心）

---

## 1. 環境（home_wsl，務必照做）

- **資料/索引在 home_wsl**，不在本機 mac。`ssh home_wsl`，repo 在 `~/code/legal-case-retrieval`。
- **uv 路徑**：`~/.local/bin/uv`（非互動 shell 的 PATH 沒有 uv）。
- **跑檢索/索引/chromadb 必加環境變數**：`PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python`（否則 chromadb import 報 protobuf TypeError）。
- **BGE-M3 黃金版本組合**（已釘 pyproject + uv.lock，勿亂升）：
  - torch 2.4.1+cu121 / torchvision 0.19.1 / transformers 4.49.0 / FlagEmbedding 1.3.4
  - 太新會撞 torchvision::nms / dtype / transformers v5 錯誤。不要追 cu13。
- **GPU**：RTX 3060 Ti 8GB。embed batch=128 約用 5.5GB（安全）。
- **長任務一律 tmux 背景跑**（SSH 易斷）。範例見本檔第 5 節。
- **⚠️ ssh home_wsl 跑 git 前先確認當前分支**（曾誤在 main commit；git pull rebase 在錯分支會接錯）。

### 環境變數（.env 在 repo 根，走 config 模組讀，勿直接讀 env）
- `LCR_PROCESSED_DIR=/home/mrfrog/data/processed`
- `LCR_INDEX_DIR=/home/mrfrog/data/index`
- `LCR_OPENAI_API_KEY`（gpt-5-mini 抽取用）
- `LCR_GEMINI_API_KEY` / `LCR_GEMINI_BASE_URL`（評估集 + HyDE 改寫，走 rdsec 閘道 OpenAI 相容介面，gemini-3.5-flash 是推理模型，max_tokens 須 ≥4096）

---

## 2. 資料現況（已完成，三檔對齊 81,644 筆）

`/home/mrfrog/data/processed/`：
- `corpus.jsonl` — 81,644 筆地院一審純刑事（105-114 年，排程序性）
- `segmented.jsonl` — 切段（main/facts/reasoning）
- `gpt_extract_all.jsonl` — gpt-5-mini 抽取（verdict/sentence/compensation/subjective/facts_summary）
- `eval.jsonl` — 150 對合成評估集（gemini 口語 query）
- `legal_terms.json` — 案由→法條→特徵詞術語表（123 案由）
- `hyde_rewrites.jsonl` — query 改寫快取
- `*.bak` — 舊混版備份（勿用）

`/home/mrfrog/data/index/`：
- `chroma/` — ChromaDB dense（BGE-M3，81,644 筆，collection: legal_cases）
- `bm25/` — BM25s sparse（含法條號）

**注意**：data 目錄在 .gitignore，不進版控。索引重建約 30 分（GPU）。

---

## 3. 已完成（main 上可用）

### 檢索核心（`src/lcr/retrieval/`）
- `indexer.py`：dense（facts_summary）/ sparse（摘要+案由+法條號）分流，recreate 防殘留
- `searcher.py`：dense_search / sparse_search / hybrid_search(RRF) / hybrid_rerank(bge-reranker) / **search_pipeline**（最佳組合）
- `search_pipeline(query, top_k, rewrite, ...)`：rewrite + hybrid + rerank，回結構化 dict

### 法律術語（`src/lcr/`）
- `extract/regex_extractor.py`：白名單法條抽取（去雜訊）
- `eval/query_gen.py`：gemini 生成評估集 query
- `eval/hyde.py`：query 改寫 3 策略（A rewrite 最佳，C 受控生成待修案由預判）
- `eval/text_clean.py`：embed 文字清洗（實驗證明無顯著效果，僅供參考）

### API（`app/`）
- `main.py`：FastAPI，`GET /api/v1/health`、`POST /api/v1/search`（已實機驗證）
- `schemas.py`：pydantic 契約

### 實驗腳本（`experiments/`）
- 03 建語料 / 04a GPT抽取 / 05 建索引 / 06 評估集 / 07 消融 / 08 清洗對照 / 09 術語表 / 10 HyDE / 11 寬鬆相關性

### 關鍵實驗結論
- 嚴格 single-relevant：rerank 最佳但僅 R@5 0.173（任務本質難）
- **寬鬆相關性（同案由/同法條，匹配類案檢索本質）：rewrite+rerank R@5 0.933**
- 否證：清洗 embed 無效、嚴格尺規追高方向錯
- 最佳線上管線 = query 改寫 + dense + rerank

---

## 4. 待完成（下一個 agent 的工作，依優先序）

### 4.1 補齊 API 端點（對照 api_v1.md）
- `GET /api/v1/case/{jid}`：案例詳情（segments 原文 + extracted + citations + comparison）
  - 需回讀 segmented.jsonl 取三段原文，citation grounding 驗證法條是否真在原文
- `POST /api/v1/clarify`：對話追問（LLM 判斷缺哪些要件，回 next_question）
- `GET /api/v1/stats`：群體統計（verdict 分布、compensation range、by_year）
  - 可從 gpt_extract_all.jsonl 聚合
- `POST /api/v1/search/trace`：推理過程（agent 思考鏈）
- `/search` response 補 analysis（法條/過失故意/刑民）、stats、每案 facts_summary/verdict/sentence

### 4.2 部署（roadmap 第 4 節，路線 B）
- Dockerfile（python:3.12-slim + uv sync --frozen）
- docker-compose：api + nginx，chroma volume 掛載（索引不打進 image）
- .github/workflows/ci.yml：uv sync + ruff + pytest + docker build
- 檢索品質回歸測試（用 eval.jsonl 確保 Recall 不退步）

### 4.3 可選的研究增強
- HyDE 策略 C：案由預判改用 dense top-1（現用字串比對會猜錯）
- 要素抽取可信度實驗（roadmap Week 3）：純 LLM vs LLM+規則 準確率/幻覺率
- 整合 `docs/experiment_results.md`（roadmap Week 4 報告）

### 4.4 拆前後端 repo（roadmap 第 1 節）
- API 穩定後，前端拆到 legal-case-web，本 repo 專注後端

---

## 5. 常用指令範例（home_wsl）

```bash
# 啟動 API server（tmux 背景）
ssh home_wsl
cd ~/code/legal-case-retrieval
tmux new-session -d -s api 'LCR_PROCESSED_DIR=/home/mrfrog/data/processed \
  LCR_INDEX_DIR=/home/mrfrog/data/index PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
  ~/.local/bin/uv run uvicorn app.main:app --host 0.0.0.0 --port 8000'
curl -s localhost:8000/api/v1/health
curl -s -X POST localhost:8000/api/v1/search -H 'Content-Type: application/json' \
  -d '{"query":"我朋友酒駕被抓","top_k":3,"rewrite":false}'

# 重建索引（GPU，約 30 分）
tmux new-session -d -s idx 'LCR_DATASET_ROOT=/home/mrfrog/code/lawundry_test/Dataset \
  LCR_PROCESSED_DIR=/home/mrfrog/data/processed LCR_INDEX_DIR=/home/mrfrog/data/index \
  PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
  ~/.local/bin/uv run python experiments/05_build_index.py'

# 跑測試
uv run pytest          # 56 passed
uv run ruff check .    # 注意：04a/probe/test_filter 有約 20 既有 lint 債（非阻斷）
```

---

## 6. 規範（務必遵守）

- Python 一律 uv（uv run / uv add），依賴權威來源 pyproject.toml，同步 requirements.txt
- 每個任務開新分支（feat/... 或 fix/...），**不在 main 開發**
- Conventional Commits，commit message 一行英文，無 AI 簽名
- pull --rebase，merge 前確認分支，PR 描述含 commit history 分析
- 設計決策寫 docs/，AGENT.md 補索引
- 系統定位「類案檢索工具」非法律建議；禁止個案預測；資料偏差須揭露
- 破壞性操作（rm/reset --hard）前確認備份；不代刪資料目錄
- 繁體中文回覆

---

## 7. 已知坑

- chromadb 不加 PROTOCOL_BUFFERS env → protobuf TypeError
- torch 升 2.12 → torchvision/transformers 全炸（已釘穩定版勿動）
- gemini-3.5-flash 是推理模型，max_tokens<4096 → content=None
- ChromaDB get_or_create 不清舊資料 → 重建索引務必 recreate=True
- 中文人名 regex 清洗會誤傷常用字（已棄用）
- ssh 單行帶 `&& echo` 接 tmux 有時 exit 255 → 拆成獨立指令或用 scp 腳本檔
