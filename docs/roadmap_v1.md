# 開發路線圖 v1：從實驗到部署

> 對應文件：`docs/design_v1.md`（技術）、`docs/product_v1.md`（產品）
> 本文件聚焦「開發階段、時程、repo 策略、部署（路線 B 完整工程）」

---

## 1. Repo 策略

階段性拆分，不一開始就分：

```
現在 ~ 實驗階段：單一 repo（legal-case-retrieval）
  實驗、資料處理、RAG 核心都在這，你一人主導

進入工程階段：拆兩個 repo
  legal-case-retrieval  後端 / API（你負責）
  legal-case-web        前端（組員負責）
  透過 REST API 對接，各自獨立部署
```

- 為何分：前後端技術棧不同（Python vs JS/TS），CI/依賴會打架；組員不碰你的 RAG
- 為何不早分：實驗階段 API 規格未定，太早分前端沒東西可接
- 拆分時機：你的 API 能穩定回傳 top-5 案例 JSON 後
- 關鍵交付物：API 規格（FastAPI 自動生成的 `/docs` 即可當合約）

---

## 2. 實驗階段（單 repo，3-4 週）

目的：**不是做出能用的系統，而是用數據證明設計決策正確**。這是課程報告核心。

### Week 1：資料管線

| 任務 | 產出 | 驗收 |
|------|------|------|
| 子集篩選 | 1-3 萬筆目標案件 | 數量、案由分布統計 |
| 結構切段 | 主文/事實/理由 | 切段成功率 > 85%，fallback |
| 要素抽取（離線） | 結構化 JSON 資料庫 | 抽樣人工檢查正確率 |

### Week 2：檢索實驗（核心 contribution）

| 實驗 | 對照組 | 預期效果 | 目的 |
|------|--------|---------|------|
| Chunking 策略 | 全文 vs 事實段 vs 摘要 | 事實段最佳 | 驗證「用事實查」 |
| 檢索方法 | Dense vs BM25 vs Hybrid | Hybrid 最佳 | 證明混合檢索 |
| 是否加法條 | 純事由 vs 事由+法條 | +10~15% | 對齊 NyayaRAG |
| Rerank | 有 vs 無 | +5~15 NDCG | 證明重排價值 |

預期目標數字：Recall@5 > 0.6、MRR > 0.4、Hybrid 比單一方法高 10%+。

### Week 3：要素抽取 + 可信度實驗

| 實驗 | 對照 | 預期 |
|------|------|------|
| 抽取方法 | 純 LLM vs LLM+規則 | 規則混合幻覺率更低 |
| Citation 驗證 | 計算引用幻覺率 | 量化可信度 |

對應課程「可信度/解釋性」人文主題，報告亮點。

### Week 4：整合評估報告

消融結果整理成 `docs/experiment_results.md`，每個設計決策有數據支撐。

### 實驗階段工程要求（刻意從簡）

**不碰部署、不碰前端、不過度工程化。**
用 Jupyter / Python script 跑實驗，結果存 CSV/JSON，不需要 API 或容器。
唯一目標是產出數據與結論。

---

## 3. 工程階段（雙 repo 並行，2-3 週）

### 後端技術選型

| 元件 | 選擇 | 理由 |
|------|------|------|
| Web 框架 | FastAPI | async、自動 OpenAPI 文件 |
| ASGI server | uvicorn | FastAPI 標配 |
| Vector DB | ChromaDB（persistent） | 延用實驗階段 |
| LLM 呼叫 | 抽成 service 層 | 方便換模型 |
| 套件管理 | uv | 專案規範 |
| 設定管理 | pydantic-settings 讀 .env | 不硬編碼金鑰 |

### API 端點（見 product_v1.md 第 5 節）

```
POST /api/v1/clarify        對話追問
POST /api/v1/search         主搜尋（cases + stats + analysis）
GET  /api/v1/case/{jid}     案例詳情 + citation（lazy load）
POST /api/v1/search/trace   推理過程
GET  /api/v1/stats          群體統計
GET  /api/v1/health         健康檢查
```

---

## 4. 部署：路線 B 完整工程

```
docker-compose：FastAPI + ChromaDB + nginx 反向代理
前端：組員部署 Vercel / Netlify，打後端 API（設好 CORS）
CI/CD：GitHub Actions
  push        → 跑 test + lint + docker build
  merge main  → build image + 部署
```

### 容器化（Dockerfile 重點）

```dockerfile
FROM python:3.12-slim
RUN pip install uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
COPY . .
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

注意：向量索引（ChromaDB 資料）很大，**不要打進 image**，用 volume 掛載或啟動時下載。

### docker-compose 結構

```
services:
  api:     FastAPI + uvicorn，掛載 chroma volume
  nginx:   反向代理 + 靜態資源 + TLS 終結
volumes:
  chroma_data:  向量索引持久化
```

### CI/CD（.github/workflows/ci.yml）

```yaml
on: [push, pull_request]
jobs:
  test:
    - uv sync
    - uv run ruff check .      # lint
    - uv run pytest            # test
    - docker build .           # 確認可 build
  deploy:                      # 僅 merge main
    - build & push image
    - 部署到主機
```

### Test 策略

| 層級 | 測什麼 | 工具 |
|------|--------|------|
| 單元 | 切段 regex、要素抽取、RRF 邏輯 | pytest |
| 整合 | API endpoint 回傳格式 | pytest + httpx |
| 檢索品質 | 評估集 Recall@5 不退步（回歸測試） | 自寫 script |

重點：**檢索品質回歸測試**——保留實驗階段評估集，每次改檢索都跑一次確保沒改爛。
RAG 系統特有測試，寫進報告是亮點。

---

## 5. 整體時程

```
實驗階段（單 repo）          3-4 週
  Week 1  資料管線
  Week 2  檢索實驗
  Week 3  抽取 + 可信度實驗
  Week 4  整合評估報告
        ↓ 拆 repo，API 規格定案
工程階段（雙 repo 並行）      2-3 週
  你：FastAPI 後端 + 容器化 + CI/CD
  組員：前端 + 串 API
整合 + demo                  1 週
```

---

## 6. 提醒

1. 實驗與工程分清楚：實驗階段別碰部署，工程階段別再改演算法。
2. API 規格是前後端合約，越早定好，組員越早並行。
3. 評估集是寶，從實驗用到工程回歸測試，別丟。
4. 課程報告價值在實驗數據，不在 UI 多炫。消融表格做扎實最重要。
