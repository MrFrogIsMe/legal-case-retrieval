// 純函式：跳脫與格式化，無 DOM 依賴

export function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

export function formatTWD(amount) {
  if (amount == null) return null;
  return `${Number(amount).toLocaleString("zh-TW")} 元`;
}

export function formatCount(n) {
  return Number(n ?? 0).toLocaleString("zh-TW");
}

export function formatPercent(ratio) {
  return `${Math.round((ratio ?? 0) * 100)}%`;
}

const CONFIDENCE_LABELS = { high: "高", medium: "中", low: "低" };

export function confidenceLabel(level) {
  return CONFIDENCE_LABELS[level] ?? String(level ?? "—");
}
