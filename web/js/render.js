// 渲染層：純函式，輸入資料、輸出 HTML 字串；不碰 fetch、不持有狀態。
// 介面分層對應 docs/product_v1.md 第 3 節。
import { esc, formatTWD, formatCount, formatPercent, confidenceLabel } from "./format.js";

const COLLECTED_LABELS = {
  incident_type: "事件類型",
  damage: "損害",
  injury: "是否受傷",
  hit_and_run: "是否離開現場",
  fault: "主觀要素",
};

const SEGMENT_NAMES = { main: "主文", facts: "事實", reasoning: "理由" };

function confChip(level, { prefix = true } = {}) {
  const known = ["high", "medium", "low"].includes(level);
  const cls = known ? ` conf-${level}` : "";
  return `<span class="conf${cls}">${prefix ? "信心：" : ""}${esc(confidenceLabel(level))}</span>`;
}

function articleTags(articles) {
  return (articles ?? [])
    .map((a) => `<span class="tag">${esc(a)}</span>`)
    .join("");
}

/* ---------- 對話（第 0 層） ---------- */

export function renderChatUser(text) {
  return `<li class="turn turn-user">
  <p class="turn-role">你</p>
  <div class="turn-body">${esc(text)}</div>
</li>`;
}

export function renderChatNote(text) {
  return `<li class="turn">
  <p class="turn-role">系統</p>
  <div class="turn-body turn-note">${esc(text)}</div>
</li>`;
}

function collectedTags(collected) {
  if (!collected) return "";
  const items = Object.entries(collected)
    .filter(([, value]) => value !== null && value !== undefined && value !== "")
    .map(([key, value]) => {
      const label = COLLECTED_LABELS[key] ?? key;
      const display = value === true ? "是" : value === false ? "否" : String(value);
      return `<span class="tag">${esc(label)}：${esc(display)}</span>`;
    });
  if (!items.length) return "";
  return `<div class="collected"><span class="turn-note">已掌握：</span>${items.join("")}</div>`;
}

export function renderChatSystem({ question, reason, collected, quickReplies }) {
  const quickButtons = (quickReplies ?? [])
    .map(
      (option) =>
        `<button type="button" class="chip quick-reply" data-reply="${esc(option.label)}">${esc(option.label)}</button>`,
    )
    .join("");
  return `<li class="turn turn-system">
  <p class="turn-role">系統</p>
  <div class="turn-body">
    <p>${esc(question)}</p>
    ${reason ? `<details class="why"><summary>為什麼問這個？</summary><p>${esc(reason)}</p></details>` : ""}
    ${collectedTags(collected)}
    <div class="quick">
      ${quickButtons}
      <button type="button" class="linklike" data-action="skip-clarify">跳過追問，直接檢索</button>
    </div>
  </div>
</li>`;
}

/* ---------- 載入與錯誤 ---------- */

export function renderSearching() {
  return `<div class="report report-loading" role="status">
  <p class="searching-line">
    <span class="searching-dot" aria-hidden="true"></span>
    <span id="searching-step">正在理解事由…</span>
  </p>
  <div class="skel" aria-hidden="true">
    <span class="w40"></span><span class="w80"></span><span class="w60"></span><span class="w80"></span>
  </div>
</div>`;
}

export function renderDetailLoading() {
  return `<div class="skel" role="status" aria-label="載入中">
  <span class="w60"></span><span class="w80"></span>
</div>`;
}

export function renderInlineError(message) {
  return `<div class="notice notice-warn" role="alert">${esc(message)}</div>`;
}

export function renderSearchError(message, hintHtml) {
  return `<div class="report">
  <div class="notice notice-warn" role="alert"><strong>檢索失敗：</strong>${esc(message)}${hintHtml ? `<br>${hintHtml}` : ""}</div>
  <button type="button" class="btn btn-small" id="btn-retry">重試</button>
</div>`;
}

/* ---------- 檢索報告（第 1–2 層） ---------- */

export function renderReport(data, opts = {}) {
  const cases = data.cases ?? [];
  const metaBits = [
    `<p class="report-kicker">檢索報告</p>`,
    opts.reportNo ? `<p class="report-no mono">編號 ${esc(opts.reportNo)}</p>` : "",
    opts.rocDate ? `<p class="report-date">${esc(opts.rocDate)}</p>` : "",
    opts.mock
      ? `<span class="tag tag-mock" title="目前讀取 mock 資料；切換真實後端見 web/js/config.js">示意資料</span>`
      : "",
  ]
    .filter(Boolean)
    .join("");
  return `<article class="report">
  <header class="report-head">
    <div class="report-meta">${metaBits}</div>
    <h2 id="report-title" tabindex="-1">與您事由相似的判決</h2>
    <p class="report-query">事由：「${esc(data.query)}」</p>
    <span class="stamp" aria-hidden="true">非法律建議</span>
  </header>
  ${data.disclaimer ? `<div class="notice notice-note" role="note"><strong>使用前請了解：</strong>${esc(data.disclaimer)}</div>` : ""}
  <div class="report-part">${renderAnalysis(data.analysis)}</div>
  <div class="report-part">${renderStats(data.stats)}</div>
  <div class="report-part">
    <h3><span class="part-no">三</span>相似案例</h3>
    ${renderCaseToolbar(cases)}
    <div id="case-list">${renderCaseList(cases, cases.length)}</div>
  </div>
  <details class="trace-box" id="trace-box">
    <summary><span class="part-no">四</span>檢索過程：系統怎麼找到這些案例</summary>
    <div id="trace-body"></div>
  </details>
</article>`;
}

function renderAnalysis(analysis) {
  const heading = `<h3><span class="part-no">一</span>法律分析</h3>`;
  if (!analysis) return `${heading}<p class="turn-note">本次檢索未回傳法律分析。</p>`;
  const rows = (analysis.possible_articles ?? [])
    .map(
      (a) =>
        `<tr><td class="mono">${esc(a.code)}</td><td>${esc(a.name)}</td><td>${esc(a.note)}</td></tr>`,
    )
    .join("");
  return `${heading}
<dl class="kv">
  <div><dt>案件類型</dt><dd>${esc(analysis.case_type)}</dd></div>
  <div><dt>主觀要素</dt><dd>${esc(analysis.subjective)}</dd></div>
  <div><dt>刑事與民事</dt><dd>${esc(analysis.criminal_vs_civil)}</dd></div>
</dl>
<div class="analysis-articles">
  <h4>可能涉及的法條</h4>
  <div class="table-scroll">
    <table class="table">
      <thead><tr><th>法條</th><th>罪名</th><th>說明</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>
  </div>
</div>`;
}

function renderStats(stats) {
  const heading = `<h3><span class="part-no">二</span>判決結果統計</h3>`;
  if (!stats) return `${heading}<p class="turn-note">本次檢索未回傳統計。</p>`;
  const bars = (stats.verdict_distribution ?? [])
    .map(
      (d, i) => `<div class="bar-row">
  <span class="bar-label">${esc(d.label)}</span>
  <span class="bar-track"><span class="bar-fill" style="width:${Math.round((d.ratio ?? 0) * 100)}%;animation-delay:${i * 70}ms"></span></span>
  <span class="bar-value">${formatCount(d.count)} 件（${formatPercent(d.ratio)}）</span>
</div>`,
    )
    .join("");
  const range = stats.compensation_range;
  const rangeHtml = range
    ? `<h4>賠償金額（判決書有載明者）</h4>
<div class="stat-row">
  <div class="stat"><div class="stat-label">最低</div><div class="stat-value">${esc(formatTWD(range.min) ?? "—")}</div></div>
  <div class="stat stat-median"><div class="stat-label">中位數</div><div class="stat-value">${esc(formatTWD(range.median) ?? "—")}</div></div>
  <div class="stat"><div class="stat-label">最高</div><div class="stat-value">${esc(formatTWD(range.max) ?? "—")}</div></div>
</div>`
    : "";
  return `${heading}
<p>與您的事由相似的判決共 <strong>${formatCount(stats.total_similar)}</strong> 件，結果分布：</p>
<div class="bars">${bars}</div>
${rangeHtml}
<p class="footnote">統計樣本為本次檢索的相似案件，非全國統計；資料存在選擇性偏差，詳見<a href="#about">「關於本系統」</a>。</p>`;
}

function renderCaseToolbar(cases) {
  const verdicts = [...new Set(cases.map((c) => c.verdict).filter(Boolean))];
  const chips = verdicts
    .map(
      (v) =>
        `<button type="button" class="chip verdict-chip" data-verdict="${esc(v)}" aria-pressed="false">${esc(v)}</button>`,
    )
    .join("");
  return `<div class="case-toolbar">
  <label>排序
    <select id="case-sort">
      <option value="similarity">相似度（高至低）</option>
      <option value="year">年份（新至舊）</option>
      <option value="compensation">賠償金額（高至低）</option>
    </select>
  </label>
  <div class="verdict-filter" role="group" aria-label="依判決結果篩選">
    <span class="filter-label">篩選判決：</span>
    ${chips}
  </div>
</div>`;
}

export function renderCaseList(visibleCases, totalCount) {
  const head = `<p class="case-count">顯示 ${visibleCases.length}／${totalCount} 件</p>`;
  if (!visibleCases.length) {
    return `${head}<p class="turn-note">沒有符合篩選的案例，請調整條件。</p>`;
  }
  return head + visibleCases.map((c, i) => renderCaseCard(c, i)).join("");
}

function renderCaseCard(c, index) {
  const pct = Math.round((c.similarity ?? 0) * 100);
  const no = String(index + 1).padStart(2, "0");
  return `<article class="case-card" data-jid="${esc(c.jid)}">
  <header class="case-head">
    <span class="case-no mono" aria-hidden="true">${no}</span>
    <div class="case-id">
      <h4 class="case-title">${esc(c.title)}</h4>
      <p class="case-court">${esc(c.court)}・${esc(c.date_display)}</p>
    </div>
    <span class="badge">${esc(c.verdict)}</span>
  </header>
  <div class="case-body">
    <div class="case-main">
      <p class="case-facts">${esc(c.facts_summary)}</p>
      <div class="case-articles">${articleTags(c.cited_articles)}</div>
    </div>
    <dl class="case-data">
      <div><dt>刑度</dt><dd>${esc(c.sentence ?? "—")}</dd></div>
      <div><dt>賠償</dt><dd>${esc(formatTWD(c.compensation) ?? "未載明")}</dd></div>
      <div><dt>相似度</dt><dd><span class="meter" aria-hidden="true"><span style="width:${pct}%"></span></span><span class="mono">${pct}%</span></dd></div>
      <div><dt>抽取信心</dt><dd>${confChip(c.confidence, { prefix: false })}</dd></div>
    </dl>
  </div>
  <div class="case-actions">
    <button type="button" class="btn btn-small btn-expand" aria-expanded="false">展開詳情與原文</button>
    <span class="case-jid mono">${esc(c.jid)}</span>
  </div>
  <div class="case-detail" hidden></div>
</article>`;
}

/* ---------- 案例詳情（第 3 層） ---------- */

function findFragment(sourceText, haystack) {
  const candidates = [sourceText, ...sourceText.split(/\.{3}|…/)]
    .flatMap((s) => [s.trim(), s.trim().replace(/[。；，、]+$/, "")])
    .filter((s) => s.length >= 4)
    .sort((a, b) => b.length - a.length);
  return candidates.find((c) => haystack.includes(c)) ?? null;
}

function markSegment(text, citations, segmentKey) {
  let html = esc(text);
  for (const cite of citations ?? []) {
    if (cite.source_segment !== segmentKey || !cite.source_text) continue;
    const fragment = findFragment(cite.source_text, text);
    if (!fragment) continue;
    const cls = cite.verified ? "cite-ok" : "cite-warn";
    html = html.replace(esc(fragment), `<mark class="${cls}">${esc(fragment)}</mark>`);
  }
  return html;
}

function renderComparison(comparison) {
  if (!comparison?.length) return "";
  const rows = comparison
    .map(
      (r) => `<tr>
  <td>${esc(r.aspect)}</td>
  <td>${esc(r.user)}</td>
  <td>${esc(r.case)}</td>
  <td>${r.match ? '<span class="conf conf-high">相同</span>' : '<span class="conf conf-low">不同</span>'}</td>
</tr>`,
    )
    .join("");
  return `<h5>你的情況與本案對比</h5>
<div class="table-scroll">
  <table class="table">
    <thead><tr><th>面向</th><th>你的情況</th><th>本案</th><th>異同</th></tr></thead>
    <tbody>${rows}</tbody>
  </table>
</div>`;
}

function renderExtracted(extracted, confidence) {
  if (!extracted) return "";
  return `<h5>抽取要素</h5>
<dl class="kv">
  <div><dt>事實摘要</dt><dd>${esc(extracted.facts_summary ?? "—")}</dd></div>
  <div><dt>判決結果</dt><dd>${esc(extracted.verdict ?? "—")} ${confChip(confidence?.verdict)}</dd></div>
  <div><dt>刑度</dt><dd>${esc(extracted.sentence ?? "—")}</dd></div>
  <div><dt>賠償</dt><dd>${esc(formatTWD(extracted.compensation) ?? "—")} ${confChip(confidence?.compensation)}</dd></div>
  <div><dt>引用法條</dt><dd>${articleTags(extracted.cited_articles)}</dd></div>
  <div><dt>關鍵因素</dt><dd>${esc((extracted.key_factors ?? []).join("、") || "—")}</dd></div>
  <div><dt>整體</dt><dd>${confChip(confidence?.overall)}</dd></div>
</dl>`;
}

function renderCitations(citations) {
  if (!citations?.length) return "";
  const items = citations
    .map(
      (c) => `<figure class="cite ${c.verified ? "" : "cite-x"}">
  <p class="cite-claim">${esc(c.claim)}
    ${c.verified ? '<span class="conf conf-high">已對應原文</span>' : '<span class="conf conf-low">未能於原文驗證</span>'}
  </p>
  <blockquote>${esc(c.source_text)}</blockquote>
  <figcaption>出處：${esc(SEGMENT_NAMES[c.source_segment] ?? c.source_segment)}段${c.article ? `・${esc(c.article)}` : ""}</figcaption>
</figure>`,
    )
    .join("");
  return `<h5>引用依據</h5>${items}`;
}

function renderSegments(segments, citations) {
  if (!segments) return "";
  const blocks = Object.entries(SEGMENT_NAMES)
    .filter(([key]) => segments[key])
    .map(
      ([key, name]) => `<section class="seg">
  <h6>${name}</h6>
  <p>${markSegment(segments[key], citations, key)}</p>
</section>`,
    )
    .join("");
  return `<h5>判決原文（節錄）</h5>
<p class="footnote">標記說明：<mark class="cite-ok">黃底</mark>為系統結論的原文依據；<mark class="cite-warn">紅底</mark>為系統宣稱的依據但驗證未通過，請以原文為準。</p>
${blocks}`;
}

export function renderCaseDetail(detail) {
  return [
    renderComparison(detail.comparison),
    renderExtracted(detail.extracted, detail.confidence),
    renderCitations(detail.citations),
    renderSegments(detail.segments, detail.citations),
  ]
    .filter(Boolean)
    .join("");
}

/* ---------- 檢索過程（方向 D） ---------- */

export function renderTraceList(trace) {
  const items = (trace ?? [])
    .map(
      (t) => `<li>
  <span class="trace-step">${esc(t.step)}</span>
  <div>
    <p class="trace-name">${esc(t.name)}</p>
    <p class="trace-detail">${esc(t.detail)}</p>
  </div>
</li>`,
    )
    .join("");
  return `<ol class="trace">${items}</ol>
<p class="footnote">步驟與參數對應系統實作（src/lcr/retrieval），詳見 docs/design_v1.md。</p>`;
}
