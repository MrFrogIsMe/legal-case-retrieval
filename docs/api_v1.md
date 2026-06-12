# API 規格 v1：法律判決類案搜尋系統

> 對應文件：`docs/product_v1.md`（產品）、`docs/design_v1.md`（技術）
> 本文件是**前後端契約**。前端可依此用 mock data 先行開發，不需等後端完成。
> 後端以 FastAPI 實作，上線後 `/docs` 會自動生成可互動的 OpenAPI 文件。

---

## 0. 通用約定

- Base URL：`/api/v1`
- 所有 request/response 皆為 `application/json; charset=utf-8`
- 時間格式：ISO 8601（`2024-04-14`）
- 判決日期沿用資料原始格式 `YYYYMMDD`（字串），另提供格式化欄位
- 金額單位：新臺幣（元），整數；無法確定時為 `null`
- 信心分數 `confidence`：浮點數 0.0–1.0，或字串標籤 `high` / `medium` / `low`
- 錯誤回應統一格式（見第 7 節）

### 跨域（CORS）

後端需允許前端網域（開發期 `http://localhost:*`，上線後填組員的 Vercel/Netlify 網域）。

---

## 1. POST /api/v1/clarify — 對話追問（方向 A）

對話式引導。使用者描述事由後，系統判斷是否需要追問關鍵要件（有無受傷、有無逃逸等），
回傳下一個該問的問題；若資訊已足夠則回傳 `ready_to_search: true`。

### Request

```json
{
  "session_id": "可選，前端產生的對話識別碼，用於多輪追問",
  "messages": [
    { "role": "user", "content": "我開車不小心擦撞到路邊停的貨車" }
  ]
}
```

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| session_id | string | 否 | 多輪對話識別，後端可用於暫存上下文 |
| messages | array | 是 | 對話歷史，role 為 `user` 或 `assistant` |

### Response

```json
{
  "session_id": "abc123",
  "ready_to_search": false,
  "next_question": "了解。請問這次事故有人受傷嗎？",
  "reason": "是否有人受傷會決定刑事責任類型（過失傷害 vs 純財損）",
  "collected": {
    "incident_type": "車輛碰撞",
    "damage": "財物（後照鏡）",
    "injury": null,
    "hit_and_run": null,
    "fault": "過失"
  }
}
```

| 欄位 | 型別 | 說明 |
|------|------|------|
| ready_to_search | boolean | true 表示資訊足夠，前端可改打 `/search` |
| next_question | string\|null | 下一個追問；ready 時為 null |
| reason | string | 為何追問此項（可顯示給使用者，呼應透明性） |
| collected | object | 目前已蒐集的要件，欄位值未知時為 null |

當 `ready_to_search: true` 時，`collected` 即可作為 `/search` 的結構化輸入。

---

## 2. POST /api/v1/search — 主搜尋

核心端點。一次回傳「法律分析 + 群體統計 + 案例列表」，前端控制揭露節奏（首屏快）。

### Request

```json
{
  "query": "我開車不小心擦撞到路邊停的貨車，後照鏡壞了，沒有人受傷",
  "collected": {
    "incident_type": "車輛碰撞",
    "damage": "財物（後照鏡）",
    "injury": false,
    "hit_and_run": false,
    "fault": "過失"
  },
  "filters": {
    "year_from": null,
    "year_to": null,
    "courts": [],
    "verdict_types": []
  },
  "top_k": 5
}
```

| 欄位 | 型別 | 必填 | 說明 |
|------|------|------|------|
| query | string | 是 | 口語事由（原始文字） |
| collected | object | 否 | clarify 蒐集的結構化要件，有則提升精準度 |
| filters | object | 否 | 進階篩選（Persona 2），預設不限 |
| top_k | int | 否 | 回傳案例數，預設 5 |

filters 子欄位：`year_from`/`year_to`（int），`courts`（string[]），`verdict_types`（string[]，如 `["不受理","緩刑","拘役"]`）。

### Response

```json
{
  "query": "我開車不小心擦撞...",
  "analysis": {
    "case_type": "過失毀損 / 可能涉過失傷害",
    "subjective": "過失",
    "possible_articles": [
      { "code": "刑法 354", "name": "毀損罪", "note": "須故意，過失毀損不罰" },
      { "code": "刑法 284", "name": "過失傷害", "note": "若有人受傷則適用" }
    ],
    "criminal_vs_civil": "純財物損壞刑事多不起訴，責任主要落在民事賠償"
  },
  "stats": {
    "total_similar": 218,
    "verdict_distribution": [
      { "label": "不受理", "count": 131, "ratio": 0.60 },
      { "label": "緩刑", "count": 65, "ratio": 0.30 },
      { "label": "拘役易科罰金", "count": 22, "ratio": 0.10 }
    ],
    "compensation_range": { "min": 3000, "median": 8000, "max": 35000, "currency": "TWD" }
  },
  "cases": [
    {
      "jid": "ILDM,95,交易,34,20060414,1",
      "title": "過失傷害",
      "court": "臺灣宜蘭地方法院",
      "year": 95,
      "date": "20060414",
      "date_display": "民國 95 年 4 月 14 日",
      "facts_summary": "被告駕車行駛中，不慎擦撞前方停放車輛...",
      "verdict": "公訴不受理",
      "sentence": null,
      "compensation": null,
      "cited_articles": ["刑法 284", "刑事訴訟法 303"],
      "similarity": 0.82,
      "confidence": "high"
    }
  ],
  "disclaimer": "本系統為類案檢索工具，非法律建議。所列案例為刑事判決，您描述的情況若無人受傷，刑事上通常不會起訴；過去案例不代表您的案件結果。"
}
```

| 區塊 | 對應產品方向 | 說明 |
|------|------|------|
| analysis | — | 法律分析（法條、過失/故意、刑民） |
| stats | 方向 C 儀表板 | 群體統計，前端畫圖表 |
| cases | 案例列表 | top-k 案例卡片，詳情另打 `/case/{jid}` |
| disclaimer | 免責揭露 | 必顯示，扣人文主題 |

case 物件欄位：

| 欄位 | 型別 | 說明 |
|------|------|------|
| jid | string | 判決唯一識別碼，作為 `/case/{jid}` 的 key |
| title | string | 案由（JTITLE） |
| court | string | 法院 |
| year / date / date_display | int/string/string | 年度 / 原始日期 / 格式化 |
| facts_summary | string | 事實摘要（LLM 抽取） |
| verdict | string | 判決結果（有罪/無罪/不受理…） |
| sentence | string\|null | 刑度（拘役/有期徒刑/罰金），無則 null |
| compensation | int\|null | 賠償金額，無則 null |
| cited_articles | string[] | 引用法條（regex 精確抽取） |
| similarity | float | 檢索相似度 0–1 |
| confidence | string | 抽取信心 high/medium/low |

---

## 3. GET /api/v1/case/{jid} — 案例詳情（第 3 層，lazy load）

點開案例卡片才呼叫。回傳對比表、citation 高亮、信心分數、完整法條。
較重（需回原文比對），前端展開時才載入。

### Path 參數

| 參數 | 型別 | 說明 |
|------|------|------|
| jid | string | URL-encoded 判決識別碼 |

### Query 參數（可選）

| 參數 | 型別 | 說明 |
|------|------|------|
| query | string | 使用者原始事由，用於產生「你的情況 vs 本案」對比表（方向 B） |

### Response

```json
{
  "jid": "ILDM,95,交易,34,20060414,1",
  "title": "過失傷害",
  "court": "臺灣宜蘭地方法院",
  "date_display": "民國 95 年 4 月 14 日",
  "segments": {
    "main": "主文段全文...",
    "facts": "事實段全文...",
    "reasoning": "理由段全文..."
  },
  "extracted": {
    "facts_summary": "被告駕車...",
    "verdict": "公訴不受理",
    "sentence": null,
    "compensation": null,
    "cited_articles": ["刑法 284", "刑事訴訟法 303"],
    "key_factors": ["告訴乃論", "撤回告訴"]
  },
  "citations": [
    {
      "claim": "本案以公訴不受理收場",
      "source_segment": "reasoning",
      "source_text": "茲據告訴人...於本院訊問時均撤回告訴...",
      "article": "刑事訴訟法 303",
      "verified": true
    }
  ],
  "comparison": [
    { "aspect": "主觀要素", "user": "過失", "case": "過失", "match": true },
    { "aspect": "損害類型", "user": "財損", "case": "財損+受傷", "match": false },
    { "aspect": "肇事逃逸", "user": "無", "case": "無", "match": true }
  ],
  "confidence": {
    "verdict": "high",
    "compensation": "low",
    "overall": "medium"
  }
}
```

| 區塊 | 對應 | 說明 |
|------|------|------|
| segments | — | 切段後的原文三段 |
| extracted | — | 結構化抽取結果 |
| citations | 方向 B + 可信度 | 每個結論的原文依據；`verified:false` 前端標紅 |
| comparison | 方向 B | 你的情況 vs 本案對比表；需帶 query 才有 |
| confidence | — | 欄位級信心分數 |

---

## 4. POST /api/v1/search/trace — 推理過程（方向 D，展開才打）

回傳 agent 的思考鏈，給「看 AI 怎麼想的」折疊面板。預設不打，使用者展開才呼叫。

### Request

同 `/search`（query + collected）。

### Response

```json
{
  "trace": [
    { "step": 1, "name": "理解事由", "detail": "財物損壞、過失、無人受傷" },
    { "step": 2, "name": "推斷法條", "detail": "刑法 354 毀損(須故意，過失不罰)；若受傷則 284" },
    { "step": 3, "name": "檢索策略", "detail": "改查過失傷害/公共危險相鄰案件，BM25 比對法條號" },
    { "step": 4, "name": "混合檢索", "detail": "Dense(BGE-M3) + BM25 → RRF(k=60) → top-20" },
    { "step": 5, "name": "重排", "detail": "bge-reranker-v2-m3 → top-5" }
  ]
}
```

| 欄位 | 型別 | 說明 |
|------|------|------|
| trace | array | 依序的推理步驟，每步含 step/name/detail |

---

## 5. GET /api/v1/stats — 群體統計（方向 C）

獨立統計端點。`/search` 已內含 stats，此端點用於「不帶搜尋只看某案由類別統計」或前端圖表頁。

### Query 參數

| 參數 | 型別 | 說明 |
|------|------|------|
| case_type | string | 案由類別，如 `過失傷害` |
| year_from / year_to | int | 年度範圍（可選） |

### Response

```json
{
  "case_type": "過失傷害",
  "total": 4821,
  "verdict_distribution": [
    { "label": "不受理", "count": 2892, "ratio": 0.60 },
    { "label": "緩刑", "count": 1446, "ratio": 0.30 },
    { "label": "拘役易科罰金", "count": 483, "ratio": 0.10 }
  ],
  "compensation_range": { "min": 3000, "median": 8000, "max": 120000, "currency": "TWD" },
  "by_year": [
    { "year": 94, "count": 312 },
    { "year": 95, "count": 358 }
  ]
}
```

---

## 6. GET /api/v1/health — 健康檢查

部署與 CI 必備。

### Response

```json
{ "status": "ok", "version": "v1", "index_loaded": true, "case_count": 23184 }
```

---

## 7. 錯誤回應格式

所有錯誤統一：

```json
{
  "error": {
    "code": "INVALID_QUERY",
    "message": "query 欄位不可為空",
    "detail": null
  }
}
```

| HTTP 狀態 | code | 情境 |
|-----------|------|------|
| 400 | INVALID_QUERY | 請求參數錯誤 |
| 404 | CASE_NOT_FOUND | jid 不存在 |
| 422 | VALIDATION_ERROR | schema 驗證失敗（FastAPI 預設） |
| 429 | RATE_LIMITED | 呼叫過於頻繁 |
| 500 | INTERNAL_ERROR | 後端/LLM/檢索異常 |
| 503 | INDEX_NOT_READY | 向量索引尚未載入 |

---

## 8. 前端 Mock 開發指引

後端未完成前，前端可用本節 mock 資料開發。

### 建議做法

1. 把第 1–6 節的 Response 範例存成靜態 JSON（如 `mock/search.json`、`mock/case.json`）
2. 前端 API 層加一個 `USE_MOCK` 開關：true 時讀本地 JSON，false 時打真實後端
3. 介面分層（product_v1.md 第 3 節）全部可用 mock 跑通：
   - 第 0 層對話 → `mock/clarify.json`
   - 第 1 層總覽 + 第 2 層列表 → `mock/search.json`
   - 第 3 層詳情 → `mock/case.json`
   - 方向 D 面板 → `mock/trace.json`
   - 方向 C 圖表 → `mock/stats.json`

### 契約穩定性承諾

- 本文件 v1 的欄位「只增不改名」；若需破壞性變更，升 `api_v2.md` 並保留 v1
- 後端上線後以 FastAPI 自動生成的 `/docs`（OpenAPI）為最終真實來源，應與本文件一致

---

## 9. 端點總覽

> 實作狀態（feat/api-endpoints-v1 起全部上線；`app/main.py`）：6 個端點皆已實作並於
> home_wsl 實機驗證。資料來源策略見下方備註。

| 端點 | 方法 | 用途 | 產品對應 | 載入時機 | 狀態 |
|------|------|------|---------|---------|------|
| /api/v1/clarify | POST | 對話追問 | 方向 A | 表層 | ✅ |
| /api/v1/search | POST | 主搜尋 | 列表+analysis+stats | 首屏 | ✅ |
| /api/v1/case/{jid} | GET | 案例詳情+citation | 方向 B、第 3 層 | 點開 lazy | ✅ |
| /api/v1/search/trace | POST | 推理過程 | 方向 D | 展開才打 | ✅ |
| /api/v1/stats | GET | 群體統計 | 方向 C | 圖表頁 | ✅ |
| /api/v1/health | GET | 健康檢查 | — | 部署/CI | ✅ |

### 實作備註（資料來源）

- 檢索走 `Searcher.search_pipeline`（rewrite + hybrid + rerank，實驗 11 最佳組合）。
- 抽取欄位（verdict/sentence/compensation/facts_summary）與原文三段**不在 ChromaDB
  metadata**（建索引時只存 jid/kind/court/jyear/title/articles），改由
  `CaseStore`（`src/lcr/retrieval/case_store.py`）提供：
  - gpt_extract_all.jsonl 全量常駐（81k 筆，數十 MB）。
  - segmented.jsonl 用 byte-offset 索引 lazy 讀單行（避免數百 MB 進記憶體）。
  - /stats 在 CaseStore 內以 lru_cache 做全量 group-by 聚合。
  此策略不必重建索引即可補齊所有端點（最小改動）。
- `/case` 的 `cited_articles` 由 regex 從原文精確抽；citation grounding 對 verdict
  採「regex 從主文段獨立重判，與 LLM 標籤一致才標 verified」的交叉驗證。
  限制：社會秩序維護法「罰鍰」型主文目前 regex 未涵蓋，該類 verdict 不互證（誠實揭露）。
- `/clarify` 規則層先判已蒐集要件與缺漏；缺要件時呼叫一次 LLM 產生自然追問句
  （gemini gateway，失敗退回固定句），要件足夠則直接 ready_to_search。
- `/search/trace` 為反映真實管線的結構化步驟模板（非每次呼叫 LLM）。
- `/search` 的 CaseItem 在 api 契約上「只增不改名」原則下保留舊欄位 `kind`/`score`
  之外，新增 facts_summary/verdict/sentence/compensation/cited_articles/similarity/
  confidence/date_display 等完整欄位。

---

## 10. 前端整合與靜態服務

組員（spaces-lalala）開發的靜態前端已整合進本 repo 的 `web/`（純 HTML + CSS +
原生 ES modules，無建置步驟、無外部依賴）。前端 same-origin 打 `/api/v1`，
因此後端只要同源 serve 前端即可，免 CORS、單跑 uvicorn 就能展示完整系統。

### 服務方式（`app/main.py`）

在所有 `/api/v1` 路由註冊**之後**掛兩個 `StaticFiles` mount（不影響任何 API 端點）：

| 路徑 | 來源目錄 | 用途 |
|------|---------|------|
| `/web` | `web/`（`html=True`） | 前端頁面：index.html + js/css |
| `/mock` | `mock/` | `USE_MOCK=true` 時前端讀此處 JSON（離線展示） |

前端 `web/js/config.js` 的 `MOCK_BASE = ../../mock/` 從 `/web/js/` 解析為 `/mock/`，
與後端 mount 對齊。兩個 mount 皆做存在性檢查（目錄不存在則略過），不影響 CI/測試。

### 啟動與切換

- 開發期單跑：`uv run --extra api uvicorn app.main:app --port 8000`，
  開 <http://localhost:8000/web/>。
- 切真實後端：`web/js/config.js` 將 `USE_MOCK = false`（`API_BASE` 已是 `/api/v1`，
  同源不需改），UI 層零改動。

### 端點對齊（無缺漏）

前端 `web/js/api.js` 呼叫的端點全部對齊後端既有實作：
`fetchHealth→/health`、`postClarify→/clarify`、`postSearch→/search`、
`fetchCase→/case/{jid}?query=`、`postTrace→/search/trace`。
`/stats` 後端有實作、前端目前未獨立呼叫（`/search` 回傳已內含 stats），非缺漏。

### 部署備註（nginx）

上線走 nginx 反代時，靜態檔可改由 nginx 直接 serve（加 `/web/`、`/mock/` location
指向掛載目錄）以減少 API 進程負載；本節的 FastAPI mount 為 fallback，
保證單跑 uvicorn（無 nginx）也能用。
