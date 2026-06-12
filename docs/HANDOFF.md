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
- `main.py`：FastAPI，6 端點全實作（health/search/case/clarify/trace/stats），已實機驗證
- `schemas.py`：pydantic 契約（analysis/stats/完整 case/case 詳情/clarify/trace/stats）
- `analysis.py`：純函式（法條/主觀推斷、citation grounding、對比表、trace、clarify 規則）
- `clarify.py`：clarify 的 LLM 層（最簡，缺要件才呼叫一次 gemini，失敗退回固定句）

### 資料倉（`src/lcr/retrieval/case_store.py`）
- `CaseStore`：extract 全量常駐 + segmented byte-offset lazy 讀 + stats 聚合（lru_cache）
- 不重建索引即補齊 search 完整欄位 / case 詳情 / stats（chroma metadata 缺的欄位）

### 部署 / CI（已就緒）
- `Dockerfile`：python:3.12-slim + uv sync --frozen（含 retrieval），索引走 volume
- `docker-compose.yml`：api + (選用 nginx)，索引/processed 唯讀掛載，GPU 區塊可選
- `.dockerignore` / `.github/workflows/ci.yml`（lint-test + docker-build 兩 job）
- `experiments/12_regression_recall.py`：用 eval.jsonl 把關 Recall@5（門檻 0.80，
  抽樣 40 題實測 0.925 PASS）

### 實驗腳本（`experiments/`）
- 03 建語料 / 04a GPT抽取 / 05 建索引 / 06 評估集 / 07 消融 / 08 清洗對照 / 09 術語表 / 10 HyDE / 11 寬鬆相關性 / 12 檢索回歸把關

### 關鍵實驗結論
- 嚴格 single-relevant：rerank 最佳但僅 R@5 0.173（任務本質難）
- **寬鬆相關性（同案由/同法條，匹配類案檢索本質）：rewrite+rerank R@5 0.933**
- 否證：清洗 embed 無效、嚴格尺規追高方向錯
- 最佳線上管線 = query 改寫 + dense + rerank

---

## 4. 待完成（下一個 agent 的工作，依優先序）

### 4.1 API 端點 — ✅ 已全部完成（feat/api-endpoints-v1）
6 端點皆上線並實機驗證：health/search/case/clarify/trace/stats。
詳見 `docs/api_v1.md` 第 9 節與「實作備註」、本檔第 3 節。
- search 已補 analysis（法條/過失故意/刑民）+ stats + 每案完整欄位
- case/{jid} 已含 segments 原文 + extracted + citations(regex 交叉驗證) + comparison
- clarify 規則層 + 最簡 LLM；trace 結構化模板；stats 全量聚合（CaseStore）

### 4.2 部署 — ✅ 已就緒（feat/api-endpoints-v1）
Dockerfile / docker-compose.yml / .dockerignore / CI（ci.yml）/ 檢索回歸（exp 12）皆完成。
剩餘可選項：
- ✅ nginx 反代設定檔（`deploy/nginx.conf`，compose 已啟用 nginx 服務）
- self-hosted GPU runner 上把 exp 12 接進 CI（GitHub 雲端 runner 無 GPU，目前手動跑）
- docker build 實機驗證：CI docker-build job 已實證可成功建 image（含 torch cu121，約 15 分）

### 4.3 可選的研究增強
- ✅ analysis 法條 hint 改資料驅動：讀 `app/data/legal_terms.json`（81k 判決抽出的
  案由→top_articles），命中案由回高頻實體法條（過濾程序法、正規化法名）；
  命不中或無檔退回內建白名單（zero-data fallback）
- ✅ citation grounding 強化：`extract_verdict` 認得「罰鍰/沒入」，社會秩序維護法
  「罰鍰」型 verdict 現可被 regex 互證
- HyDE 策略 C（尚未做）：案由預判改用 dense top-1（現用字串比對會猜錯）
- 要素抽取可信度實驗（尚未做，roadmap Week 3）：純 LLM vs LLM+規則 準確率/幻覺率
- 整合 `docs/experiment_results.md`（尚未做，roadmap Week 4 報告）

### 4.4 拆前後端 repo（roadmap 第 1 節，尚未做）
- API 已穩定，前端可拆到 legal-case-web，本 repo 專注後端

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
uv run --extra dev --extra api pytest   # 92 passed（含 API/CaseStore/analysis 34 新測試）
uv run ruff check .    # 注意：04a/probe/test_filter 有約 20 既有 lint 債（非阻斷）

# 檢索品質回歸把關（需 GPU + 索引）
LCR_PROCESSED_DIR=/home/mrfrog/data/processed LCR_INDEX_DIR=/home/mrfrog/data/index \
  PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
  uv run python -u experiments/12_regression_recall.py --threshold 0.80 --sample 40
# → [PASS] Recall@5 0.925 >= 0.80（exit 0）

# Docker 部署（索引/processed 走 volume，不打進 image）
#   主機備妥 ./data/index 與 ./data/processed 後：
docker compose up -d --build
curl http://localhost:8000/api/v1/health
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
