# 法律判決類案搜尋系統 (Legal Case Retrieval, RAG)

> 國立政治大學「生成式 AI 的人文導論」期末專題專案。
> 本系統專門針對「台灣地方法院一審刑事案件」進行語意相似類案檢索與法律要素抽取，旨在協助非法律專業的民眾從口語敘述出發，快速對照歷史判決、刑度中位數分佈、賠償金額區間，並直觀理解 AI 的推理透明鏈。

---

## 🚀 系統架構亮點

1. **81,644 筆真實地方法院刑事判決**：
   完全排除複雜的民事與冗餘的二三審判決。專注於事實描述最豐富的地方法院一審刑事判決（民國 105-114 年，近 10 年），保證事故事實的多樣性與精準相似度匹配。
2. **黃金檢索管線 (R@5 = 93.3%)**：
   採用 **口語 Query 改寫 (Gemini) + 混合檢索 (BGE-M3 Dense + 關鍵法條 BM25s Sparse) + 重排序 (BGE-Reranker-v2-m3)**，在 150 題合成測試集上實測寬鬆相關性 Recall@5 達 **93.3%**。
3. **四層可驗證抽取與防幻覺 (Citation Grounding)**：
   利用 `gpt-5-mini` 結構化約束解碼（Structured Output）批次抽取，輔以正則表達式交叉驗證。每個案件詳情皆提供「主文/事實/理由」三段式切分，並將法律結論與原文比對進行誠實標記。
4. **前後端完全解耦與開箱即用 Mock 模式**：
   前端採用純靜態（HTML + CSS + 原生 ES Modules）設計，無任何建置步驟。內建 Mock 數據模式，一鍵即可跑通對話、搜尋、圖表與詳情面板。

---

## 📦 專案目錄結構

*   `web/` — 純靜態前端展示頁（免編譯，開箱即用，預設為 Mock 模式）。
*   `mock/` — 內建 API 靜態回傳資料（支援無後端時的前端完整互動）。
*   `app/` — FastAPI 後端服務（路由、Pydantic 契約、主控邏輯）。
*   `src/lcr/` — 核心 Python RAG 套件：
    *   `retrieval/` — 檢索器（ChromaDB/BM25s/Reranker）、資料倉（CaseStore）。
    *   `extract/` — 正則與 LLM 結構化要素抽取。
    *   `eval/` — 檢索消融評估、Query 改寫與 HyDE。
*   `docs/` — 系統設計文件集：
    *   `docs/api_v1.md` — 前後端 API 規格契約（本 README 之依據）。
    *   `docs/design_v1.md` — 技術與消融實驗設計。
    *   `docs/design_change_v2.md` — 純刑事化收斂決策。
    *   `docs/product_v1.md` — 產品形態與四方向單頁介面。
*   `experiments/` — 數據處理、向量化與消融實驗腳本。

---

## 🛠️ 快速開始（三種啟動方案）

根據您的需求與開發環境，選擇最適合的啟動方案：

### 【方案一】零後端依賴：前端 Mock 模式（最推薦，1 秒即用）
如果您只想美化 UI、設計圖表或測試對話流程，**完全不需要跑 Python 或下載資料庫**。

1.  Git clone 本專案到您的電腦。
2.  確認 `web/js/config.js` 的第三行已開啟：
    ```javascript
    export const USE_MOCK = true; // 開啟 Mock 模式
    ```
3.  在您的專案根目錄下啟動一個靜態網頁伺服器：
    *   **VS Code**：右鍵點擊 `web/index.html`，選擇 **「Open with Live Server」**。
    *   **Python (一鍵啟動)**：
        ```bash
        python3 -m http.server 8000
        ```
4.  打開瀏覽器連至 `http://localhost:8000/web/`，整套系統包含對話追問、圖表渲染、案例列表與推理鏈面板即可流暢互動！

---

### 【方案二】SSH Tunnel 工作流：連接遠端真實後端（免佔本機效能）
若您的 WSL/GPU 伺服器正在執行真實的 FastAPI 服務，但您的本機前端想直接串接：

1.  **在伺服器背景啟動服務 (tmux)**：
    ```bash
    ssh home_wsl
    cd ~/code/legal-case-retrieval
    
    # 使用 tmux 確保連線中斷時服務不中斷
    LCR_PROCESSED_DIR=/home/mrfrog/data/processed \
    LCR_INDEX_DIR=/home/mrfrog/data/index \
    PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
      tmux new-session -d -s apisrv '~/.local/bin/uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 > /tmp/apisrv.log 2>&1'
    ```
2.  **在本機 Mac 建立 SSH 通道（轉發 8000 埠口）**：
    在您的 Mac 終端機執行下行並保持視窗開啟：
    ```bash
    ssh -N -L 8000:127.0.0.1:8000 home_wsl
    ```
3.  **前端切換為實體後端**：
    將 `web/js/config.js` 改為：
    ```javascript
    export const USE_MOCK = false; // 關閉 Mock，連上實體後端！
    export const API_BASE = "/api/v1";
    ```
4.  在本機 Mac 打開 `http://localhost:8000/web/`，即可直接點擊網頁，查詢伺服器上 **81,644 筆真實判決** 與 BGE-M3 RAG 後端！

---

### 【方案三】本機完整啟動：下載 81,644 筆預建索引與後端執行
若您想在自己的本機完整複製整套 RAG 後端（包括 Chroma 向量庫與全文切段資料）：

#### 1. 取得並解壓預建資料 (1.3 GB 壓縮檔，解壓後 2.5 GB)
在您的 Mac 終端機中，下載伺服器打包好的資料並解壓至專案目錄：
```bash
# 從伺服器下載壓縮檔到 Downloads 夾
scp home_wsl:/home/mrfrog/lcr_runtime_data.tar.gz ~/Downloads/

# 將資料解壓至您的專案根目錄
cd /path/to/legal-case-retrieval
tar -xzvf ~/Downloads/lcr_runtime_data.tar.gz
```
這會在專案下自動生成 `./data/processed/`（含 `segmented.jsonl`, `gpt_extract_all.jsonl` 等）及 `./data/index/`（含 ChromaDB 與 BM25 向量檔案）。

#### 2. 設定您的 .env 檔案
在專案根目錄下建立 `.env` 檔案並設定金鑰（供口語改寫與引導追問 LLM 使用）：
```env
LCR_OPENAI_API_KEY=your-openai-key-here
LCR_GEMINI_API_KEY=your-gemini-key-here
LCR_GEMINI_BASE_URL=https://api.rdsec.trendmicro.com/prod/aiendpoint/v1
```

#### 3. 一鍵啟動後端

*   **方法 A：使用 Docker Compose（極推薦，免裝任何本機 Python 依賴）**
    ```bash
    docker compose up -d --build
    ```
    *(Docker 會自動安裝 PyTorch 與 ChromaDB。若無 GPU，將自動且安全地 fallback 至 CPU 執行)*
    
*   **方法 B：使用本機 Python (uv)**
    ```bash
    # 同步本機虛擬環境（載入 api、retrieval 與 dev 依賴）
    uv sync --extra retrieval --extra api
    
    # 啟動 Uvicorn 後端
    LCR_PROCESSED_DIR=./data/processed \
    LCR_INDEX_DIR=./data/index \
    PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
      uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
    ```

#### 4. 切換前端 API 連線
將 `web/js/config.js` 改為 `export const USE_MOCK = false;`，即可以 127.0.0.1 本地端連線進行最真實的法律檢索與抽取！

---

## 📡 API 介面規格對齊（`docs/api_v1.md`）

後端啟動後，本系統將完全對齊前後端 API 契約，提供以下 6 個標準端點：

| 端點 | 方法 | 產品對應區塊 | 說明 |
| :--- | :--- | :--- | :--- |
| `/api/v1/health` | `GET` | 系統狀態標籤 | 檢查系統是否 ok、向量索引載入狀態與案源總數。 |
| `/api/v1/clarify` | `POST` | A. 引導式對話追問 | 輸入口語事由，判斷並追問核心要件，回傳 `ready_to_search: true`。 |
| `/api/v1/search` | `POST` | B. 相似案例 + C. 儀表板 | 輸入口語，回傳法律預分析、統計數據（刑期/賠償區間）與案例列表。 |
| `/api/v1/case/{jid}`| `GET` | 第 3 層. 案例展開詳情 | 輸入 `jid`，回傳三段全文、可信度引用（Citation）以及對比表格。 |
| `/api/v1/search/trace`|`POST` | D. 透明推理思考鏈 | 展示 Agent 的每一步檢索決策、Dense/Sparse 分數及法條推導。 |
| `/api/v1/stats` | `GET` | C. 獨立統計面板 | 依案由、年度獨立拉取過去法院判決結果分佈與刑期中位數。 |

---

## 🤝 貢獻與開發指南

本專案是一個兼具人文關懷與嚴謹工程架構的法律輔助工具。在開發或修改程式碼時，請遵守以下規範：
1.  **測試為王**：修改任何功能前，請在專案根目錄下執行 `uv run pytest`，確保 97 項測試（涵蓋 API 契約、篩選條件、正則抽取與資料倉）全數 Pass。
2.  **不直接在 Main 開發**：開立新分支（如 `feat/...` 或 `fix/...`），並在 Squash Merge 前保持 Working tree 乾淨。
3.  **人文反思精神**：在 UI 設計與回傳中，務必誠實揭露系統極限與「選擇性偏差」（如：純財損車禍在刑事中多不起訴，刑事資料庫將無此案源之說明），落實 AI 解釋性。

---
*國立政治大學 1142 生成式 AI 的人文導論期末專題。*
