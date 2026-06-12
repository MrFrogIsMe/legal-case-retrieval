// 流程層：持有狀態、串接 api 與 render、綁定事件。
// 流程：輸入事由 → clarify 追問（可跳過）→ search 報告 → 詳情與檢索過程 lazy 載入。
import * as api from "./api.js";
import * as ui from "./render.js";
import { USE_MOCK } from "./config.js";
import { formatCount } from "./format.js";

const els = {
  healthChip: document.getElementById("health-chip"),
  examples: document.getElementById("examples"),
  chat: document.getElementById("chat"),
  chatLog: document.getElementById("chat-log"),
  askForm: document.getElementById("ask-form"),
  queryInput: document.getElementById("query-input"),
  btnSubmit: document.getElementById("btn-submit"),
  btnAdvanced: document.getElementById("btn-advanced"),
  advancedPanel: document.getElementById("advanced-panel"),
  btnReset: document.getElementById("btn-reset"),
  results: document.getElementById("results"),
};

// 追問的快速回覆規則表：比對問題文字，附上對應的要件補丁
const QUICK_REPLY_RULES = [
  {
    test: /受傷/,
    options: [
      { label: "有人受傷", patch: { injury: true } },
      { label: "沒有人受傷", patch: { injury: false } },
    ],
  },
  {
    test: /逃逸|離開現場/,
    options: [
      { label: "有留在現場", patch: { hit_and_run: false } },
      { label: "當下離開了", patch: { hit_and_run: true } },
    ],
  },
  {
    test: /和解/,
    options: [
      { label: "已和解", patch: {} },
      { label: "尚未和解", patch: {} },
    ],
  },
];

const SEARCH_STEPS = [
  "正在理解事由…",
  "正在推斷可能法條…",
  "正在比對判決資料庫…",
  "正在重排與彙整結果…",
];

const DEFAULT_TITLE = document.title;

const state = {
  messages: [],
  collected: null,
  patches: {},
  clarifying: false,
  pending: false,
  lastQuery: "",
  lastSearchArgs: null,
  searchData: null,
  lastQuick: [],
  view: { sort: "similarity", verdicts: new Set() },
  detailCache: new Map(),
  traceLoaded: false,
  searchTicker: null,
};

const DEFAULT_PLACEHOLDER = els.queryInput.placeholder;

function setPending(on) {
  state.pending = on;
  els.btnSubmit.disabled = on;
  els.askForm.setAttribute("aria-busy", String(on));
}

function autoGrowInput() {
  const el = els.queryInput;
  el.style.height = "auto";
  const next = Math.min(el.scrollHeight + 2, 240);
  el.style.height = `${next}px`;
  el.style.overflowY = el.scrollHeight + 2 > 240 ? "auto" : "hidden";
}

function startSearchTicker() {
  stopSearchTicker();
  let i = 0;
  state.searchTicker = setInterval(() => {
    const el = document.getElementById("searching-step");
    if (!el) return;
    i = (i + 1) % SEARCH_STEPS.length;
    el.textContent = SEARCH_STEPS[i];
  }, 340);
}

function stopSearchTicker() {
  if (state.searchTicker) {
    clearInterval(state.searchTicker);
    state.searchTicker = null;
  }
}

function rocNow() {
  const d = new Date();
  const pad = (n) => String(n).padStart(2, "0");
  return {
    reportNo: `${d.getFullYear() - 1911}${pad(d.getMonth() + 1)}${pad(d.getDate())}-${pad(d.getHours())}${pad(d.getMinutes())}`,
    rocDate: `中華民國 ${d.getFullYear() - 1911} 年 ${d.getMonth() + 1} 月 ${d.getDate()} 日`,
  };
}

function mergedCollected() {
  if (!state.collected && !Object.keys(state.patches).length) return null;
  return { ...(state.collected ?? {}), ...state.patches };
}

function composeQuery() {
  const parts = state.messages
    .filter((m) => m.role === "user")
    .map((m) => m.content.trim())
    .filter(Boolean);
  return [...new Set(parts)].join("；");
}

function quickRepliesFor(question) {
  if (!question) return [];
  const rule = QUICK_REPLY_RULES.find((r) => r.test.test(question));
  return rule?.options ?? [];
}

function appendTurn(html) {
  els.chatLog.insertAdjacentHTML("beforeend", html);
  els.chat.hidden = false;
  els.chatLog.lastElementChild?.scrollIntoView({ block: "nearest" });
}

function disableQuickButtons() {
  els.chatLog.querySelectorAll(".quick button").forEach((b) => {
    b.disabled = true;
  });
}

function resetConversation() {
  state.messages = [];
  state.collected = null;
  state.patches = {};
  state.clarifying = false;
  state.searchData = null;
  state.lastQuick = [];
  state.view = { sort: "similarity", verdicts: new Set() };
  state.detailCache.clear();
  state.traceLoaded = false;
  stopSearchTicker();
  els.chatLog.innerHTML = "";
  els.chat.hidden = true;
  els.results.hidden = true;
  els.results.innerHTML = "";
  els.queryInput.placeholder = DEFAULT_PLACEHOLDER;
  document.title = DEFAULT_TITLE;
  history.replaceState(null, "", location.pathname);
}

async function submitText(text) {
  if (state.pending) return;
  if (!state.clarifying) resetConversation();
  state.messages.push({ role: "user", content: text });
  disableQuickButtons();
  appendTurn(ui.renderChatUser(text));
  els.queryInput.value = "";
  autoGrowInput();
  await runClarify();
}

async function runClarify() {
  setPending(true);
  try {
    const res = await api.postClarify({ messages: state.messages });
    state.collected = { ...(state.collected ?? {}), ...(res.collected ?? {}) };
    if (res.ready_to_search) {
      state.clarifying = false;
      appendTurn(ui.renderChatNote("資訊足夠了，開始檢索相似案例。"));
      await runSearch(composeQuery(), { collected: mergedCollected() });
    } else {
      state.clarifying = true;
      state.lastQuick = quickRepliesFor(res.next_question);
      appendTurn(
        ui.renderChatSystem({
          question: res.next_question,
          reason: res.reason,
          collected: mergedCollected(),
          quickReplies: state.lastQuick,
        }),
      );
      els.queryInput.placeholder = "回答上面的問題，或補充更多細節";
      els.queryInput.focus();
    }
  } catch (err) {
    state.clarifying = false;
    appendTurn(ui.renderChatNote(`追問暫時無法使用（${err.message}），改為直接檢索。`));
    await runSearch(composeQuery(), { collected: mergedCollected() });
  } finally {
    setPending(false);
  }
}

function fileHint() {
  if (location.protocol !== "file:") return "";
  return "請在 repo 根目錄執行 <code>uv run python -m http.server 8080</code>，再開啟 <code>http://localhost:8080/web/</code>。";
}

async function runSearch(query, { collected = null, filters = null } = {}) {
  state.lastQuery = query;
  state.lastSearchArgs = { query, collected, filters };
  els.results.hidden = false;
  els.results.innerHTML = ui.renderSearching();
  startSearchTicker();
  els.results.scrollIntoView({ block: "start" });
  setPending(true);
  try {
    const data = await api.postSearch({ query, collected, filters, top_k: 5 });
    state.searchData = data;
    state.view = { sort: "similarity", verdicts: new Set() };
    state.detailCache.clear();
    state.traceLoaded = false;
    els.results.innerHTML = ui.renderReport(data, { ...rocNow(), mock: USE_MOCK });
    bindTraceBox();
    document.getElementById("report-title")?.focus();
    const short = query.length > 14 ? `${query.slice(0, 14)}…` : query;
    document.title = `「${short}」檢索報告｜類案檢索`;
    history.replaceState(null, "", `?q=${encodeURIComponent(query)}`);
  } catch (err) {
    els.results.innerHTML = ui.renderSearchError(err.message, fileHint());
  } finally {
    stopSearchTicker();
    setPending(false);
  }
}

function applyView(cases) {
  let out = [...cases];
  const { verdicts, sort } = state.view;
  if (verdicts.size) out = out.filter((c) => verdicts.has(c.verdict));
  const comparators = {
    similarity: (a, b) => (b.similarity ?? 0) - (a.similarity ?? 0),
    year: (a, b) => String(b.date ?? "").localeCompare(String(a.date ?? "")),
    compensation: (a, b) => (b.compensation ?? -1) - (a.compensation ?? -1),
  };
  out.sort(comparators[sort] ?? comparators.similarity);
  return out;
}

function rerenderCaseList() {
  const cases = state.searchData?.cases ?? [];
  const listEl = document.getElementById("case-list");
  if (!listEl) return;
  listEl.innerHTML = ui.renderCaseList(applyView(cases), cases.length);
}

async function toggleDetail(btn) {
  const card = btn.closest(".case-card");
  const jid = card?.dataset.jid;
  const panel = card?.querySelector(".case-detail");
  if (!jid || !panel) return;
  if (!panel.hidden) {
    panel.hidden = true;
    btn.setAttribute("aria-expanded", "false");
    btn.textContent = "展開詳情與原文";
    return;
  }
  panel.hidden = false;
  btn.setAttribute("aria-expanded", "true");
  btn.textContent = "收合詳情";
  if (state.detailCache.has(jid)) {
    panel.innerHTML = state.detailCache.get(jid);
    return;
  }
  panel.innerHTML = ui.renderDetailLoading();
  try {
    const meta = state.searchData?.cases.find((c) => c.jid === jid) ?? {};
    const detail = await api.fetchCase(jid, {
      query: state.lastQuery,
      meta: { title: meta.title, court: meta.court, date_display: meta.date_display },
    });
    const html = ui.renderCaseDetail(detail);
    state.detailCache.set(jid, html);
    panel.innerHTML = html;
    panel.firstElementChild?.scrollIntoView({ block: "nearest" });
  } catch (err) {
    panel.innerHTML = ui.renderInlineError(`詳情載入失敗：${err.message}`);
  }
}

async function loadTrace() {
  state.traceLoaded = true;
  const body = document.getElementById("trace-body");
  if (!body) return;
  body.innerHTML = ui.renderDetailLoading();
  try {
    const data = await api.postTrace({ query: state.lastQuery, collected: mergedCollected() });
    body.innerHTML = ui.renderTraceList(data.trace);
  } catch (err) {
    state.traceLoaded = false;
    body.innerHTML = ui.renderInlineError(`檢索過程載入失敗：${err.message}`);
  }
}

function bindTraceBox() {
  const box = document.getElementById("trace-box");
  box?.addEventListener("toggle", () => {
    if (box.open && !state.traceLoaded) loadTrace();
  });
}

/* ---------- 事件綁定 ---------- */

els.askForm.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = els.queryInput.value.trim();
  if (!text) {
    els.queryInput.focus();
    return;
  }
  submitText(text);
});

els.queryInput.addEventListener("input", autoGrowInput);

els.queryInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    els.askForm.requestSubmit();
  }
});

els.examples.addEventListener("click", (e) => {
  const btn = e.target.closest("[data-example]");
  if (!btn || state.pending) return;
  resetConversation();
  els.queryInput.value = btn.dataset.example;
  autoGrowInput();
  submitText(btn.dataset.example);
});

els.btnReset.addEventListener("click", () => {
  resetConversation();
  els.queryInput.value = "";
  autoGrowInput();
  els.queryInput.focus();
});

els.btnAdvanced.addEventListener("click", () => {
  const open = els.advancedPanel.hidden;
  els.advancedPanel.hidden = !open;
  els.btnAdvanced.setAttribute("aria-expanded", String(open));
  if (open) document.getElementById("adv-article").focus();
});

document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !els.advancedPanel.hidden) {
    els.advancedPanel.hidden = true;
    els.btnAdvanced.setAttribute("aria-expanded", "false");
    els.btnAdvanced.focus();
  }
});

els.advancedPanel.addEventListener("submit", (e) => {
  e.preventDefault();
  if (state.pending) return;
  const article = document.getElementById("adv-article").value.trim();
  const caseTitle = document.getElementById("adv-title").value;
  const yearFrom = parseInt(document.getElementById("adv-year-from").value, 10) || null;
  const yearTo = parseInt(document.getElementById("adv-year-to").value, 10) || null;
  const verdictTypes = [...els.advancedPanel.querySelectorAll("input[type=checkbox]:checked")].map(
    (c) => c.value,
  );
  const query = [caseTitle, article].filter(Boolean).join(" ") || els.queryInput.value.trim();
  if (!query) {
    document.getElementById("adv-article").focus();
    return;
  }
  resetConversation();
  runSearch(query, {
    filters: { year_from: yearFrom, year_to: yearTo, courts: [], verdict_types: verdictTypes },
  });
});

els.chatLog.addEventListener("click", (e) => {
  const reply = e.target.closest(".quick-reply");
  if (reply && !state.pending) {
    const option = state.lastQuick.find((o) => o.label === reply.dataset.reply);
    if (option) Object.assign(state.patches, option.patch);
    reply.setAttribute("aria-pressed", "true");
    submitText(reply.dataset.reply);
    return;
  }
  const skip = e.target.closest('[data-action="skip-clarify"]');
  if (skip && !state.pending) {
    disableQuickButtons();
    state.clarifying = false;
    appendTurn(ui.renderChatNote("跳過追問，直接檢索。"));
    runSearch(composeQuery(), { collected: mergedCollected() });
  }
});

els.results.addEventListener("click", (e) => {
  if (e.target.closest("#btn-retry") && state.lastSearchArgs) {
    const { query, collected, filters } = state.lastSearchArgs;
    runSearch(query, { collected, filters });
    return;
  }
  const expand = e.target.closest(".btn-expand");
  if (expand) {
    toggleDetail(expand);
    return;
  }
  const chip = e.target.closest(".verdict-chip");
  if (chip) {
    const verdict = chip.dataset.verdict;
    const pressed = chip.getAttribute("aria-pressed") === "true";
    chip.setAttribute("aria-pressed", String(!pressed));
    if (pressed) state.view.verdicts.delete(verdict);
    else state.view.verdicts.add(verdict);
    rerenderCaseList();
  }
});

els.results.addEventListener("change", (e) => {
  if (e.target.id === "case-sort") {
    state.view.sort = e.target.value;
    rerenderCaseList();
  }
});

/* ---------- 初始化 ---------- */

async function initHealth() {
  try {
    const h = await api.fetchHealth();
    els.healthChip.textContent = `資料庫 ${formatCount(h.case_count)} 件判決`;
    if (USE_MOCK) {
      els.healthChip.title = "目前讀取 mock 資料；切換真實後端見 web/js/config.js";
    }
    els.healthChip.hidden = false;
  } catch {
    // 資料來源離線時不顯示狀態籤
  }
}

function initFromUrl() {
  const q = new URLSearchParams(location.search).get("q");
  if (!q) return;
  els.queryInput.value = q;
  autoGrowInput();
  runSearch(q);
}

initHealth();
initFromUrl();
