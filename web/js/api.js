// 資料層：唯一碰 fetch 的地方，介面對齊 docs/api_v1.md。
// mock 分支模擬真實後端的行為差異（延遲、clarify 輪次），UI 層不需分辨。
import { USE_MOCK, API_BASE, MOCK_BASE, MOCK_DELAY_MS } from "./config.js";

export class ApiError extends Error {
  constructor(message, code, status) {
    super(message);
    this.code = code;
    this.status = status;
  }
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

async function request(url, options) {
  let res;
  try {
    res = await fetch(url, options);
  } catch {
    throw new ApiError("無法連線到資料來源", "NETWORK", 0);
  }
  if (!res.ok) {
    let code = `HTTP_${res.status}`;
    let message = `請求失敗（${res.status}）`;
    try {
      const body = await res.json();
      if (body?.error) {
        code = body.error.code ?? code;
        message = body.error.message ?? message;
      }
    } catch {
      // 非 JSON 錯誤體，維持預設訊息
    }
    throw new ApiError(message, code, res.status);
  }
  return res.json();
}

async function mock(file) {
  await sleep(MOCK_DELAY_MS);
  return request(new URL(file, MOCK_BASE));
}

const get = (path) => request(`${API_BASE}${path}`);

const post = (path, body) =>
  request(`${API_BASE}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });

export function fetchHealth() {
  return USE_MOCK ? mock("health.json") : get("/health");
}

export async function postClarify({ sessionId, messages }) {
  if (!USE_MOCK) return post("/clarify", { session_id: sessionId, messages });
  const data = await mock("clarify.json");
  const userTurns = messages.filter((m) => m.role === "user").length;
  // mock 只有一題追問：第二輪起視為資訊足夠
  if (userTurns < 2) return data;
  return { ...data, ready_to_search: true, next_question: null };
}

export async function postSearch(payload) {
  if (!USE_MOCK) return post("/search", payload);
  const data = await mock("search.json");
  return { ...data, query: payload.query };
}

export async function fetchCase(jid, { query, meta } = {}) {
  if (!USE_MOCK) {
    const qs = query ? `?query=${encodeURIComponent(query)}` : "";
    return get(`/case/${encodeURIComponent(jid)}${qs}`);
  }
  // mock 僅一份詳情樣本：以卡片中繼資料覆寫表頭欄位，原文段落為示意
  const data = await mock("case.json");
  return { ...data, ...meta, jid };
}

export function postTrace(payload) {
  return USE_MOCK ? mock("trace.json") : post("/search/trace", payload);
}
