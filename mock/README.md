# Mock 資料

後端未完成前，前端可直接讀這些 JSON 開發。完整 schema 見 `docs/api_v1.md`。

| 檔案 | 對應端點 | 用途 |
|------|---------|------|
| `clarify.json` | POST /api/v1/clarify | 對話追問（方向 A，第 0 層） |
| `search.json` | POST /api/v1/search | 主搜尋：analysis + stats + 案例列表（第 1-2 層） |
| `case.json` | GET /api/v1/case/{jid} | 案例詳情 + citation + 對比表（方向 B，第 3 層） |
| `trace.json` | POST /api/v1/search/trace | 推理過程（方向 D） |
| `stats.json` | GET /api/v1/stats | 群體統計（方向 C 圖表） |
| `health.json` | GET /api/v1/health | 健康檢查 |

## 建議用法

前端 API 層加 `USE_MOCK` 開關：true 讀本地 JSON，false 打真實後端。
這些 mock 涵蓋 product_v1.md 第 3 節所有介面分層，可先把 UI 跑通。

## 契約穩定性

api_v1.md 的欄位「只增不改名」。破壞性變更會升 api_v2，並同步更新此處 mock。
後端上線後以 FastAPI `/docs`（OpenAPI）為最終真實來源。
