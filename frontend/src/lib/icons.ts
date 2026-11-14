/** 图标库：与 frontend/js/app.js 的 ICONS 完全一致（内联 SVG 片段） */
export const ICONS: Record<string, string> = {
  eye: '<path d="M2.5 12S5.8 5.5 12 5.5 21.5 12 21.5 12 18.2 18.5 12 18.5 2.5 12 2.5 12z"/><circle cx="12" cy="12" r="3"/>',
  lab: '<path d="M14 2.5H7.5a2 2 0 0 0-2 2v15a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V8z"/><path d="M14 2.5V8h4.5"/><path d="M9 13.5h6M9 17h4"/>',
  xray: '<rect x="3.5" y="3.5" width="17" height="17" rx="2.5"/><path d="M3.5 12h17M12 3.5v17"/>',
  chat: '<path d="M20 11.5a7.5 7.5 0 0 1-11 6.6L4.5 20l1.4-4.2A7.5 7.5 0 1 1 20 11.5z"/><path d="M9 11h.01M12 11h.01M15 11h.01"/>',
  pin: '<path d="M12 21.5s7-6.5 7-11.5a7 7 0 1 0-14 0c0 5 7 11.5 7 11.5z"/><circle cx="12" cy="10" r="2.5"/>',
};

export function svg(k: string): string {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.85" stroke-linecap="round" stroke-linejoin="round">${ICONS[k] ?? ""}</svg>`;
}

/** HTML 转义（用于 v-html 中插值用户/接口文本） */
export function esc(v: unknown): string {
  return String(v ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}
