// 環境開關集中於此（docs/api_v1.md 第 8 節）：
// USE_MOCK=true 讀 repo 內 mock/*.json；false 改打 API_BASE 的真實後端。
export const USE_MOCK = true;

export const API_BASE = "/api/v1";

export const MOCK_BASE = new URL("../../mock/", import.meta.url).href;

// mock 模式的模擬延遲，讓載入狀態可被看見
export const MOCK_DELAY_MS = 400;
