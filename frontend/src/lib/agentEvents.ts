/**
 * Agent SSE 事件 → 展示文案的纯函数。
 *
 * 为什么单独抽出来：ChatPage 是 700 行的组件，事件解释逻辑混在 switch 里既不能单测、也没法复用。
 * 这里只做「数据 → 一行文字」，不碰 DOM、不碰状态，所以可以在 Node 里直接测。
 *
 * 所有输入都按「不可信」处理（后端可能是旧版本、字段可能缺失）：缺字段返回空串/安全默认值，绝不抛异常。
 */

export interface TraceItem {
  id: number;
  type: "think" | "ask" | "act" | "obs" | "done" | "plan" | "reflect" | "repair";
  icon: string;
  label: string;
  text: string;
}

export interface ToolState {
  name: string;
  desc: string;
  called: boolean;
}

type Rec = Record<string, unknown>;

const rec = (v: unknown): Rec => (v !== null && typeof v === "object" && !Array.isArray(v) ? (v as Rec) : {});
const arr = (v: unknown): unknown[] => (Array.isArray(v) ? v : []);
const str = (v: unknown): string => (typeof v === "string" ? v : typeof v === "number" ? String(v) : "");
const isBad = (status: unknown) => status === "warn" || status === "fail";

/** 规划事件：「1. 检索知识库 → 2. 进展风险评估 → …」。没有可展示的步骤时返回空串。 */
export function planLine(data: unknown): string {
  return arr(rec(data).steps)
    .map(rec)
    .filter((s) => str(s.label))
    .map((s, i) => `${str(s.n) || i + 1}. ${str(s.label)}`)
    .join(" → ");
}

export interface ReflectTrace {
  text: string;
  total: number;
  attention: number;
}

/** 自检事件：「6 项核查，1 项需留意：红旗提示」。 */
export function reflectTrace(data: unknown): ReflectTrace {
  const checks = arr(rec(data).checks).map(rec).filter((c) => str(c.label));
  const bad = checks.filter((c) => isBad(c.status));
  const text = bad.length
    ? `${checks.length} 项核查，${bad.length} 项需留意：${bad.map((c) => str(c.label)).join("、")}`
    : `${checks.length} 项核查，无异常`;
  return { text, total: checks.length, attention: bad.length };
}

export interface RepairTrace {
  text: string;
  /** start 阶段为 false；done 阶段为 true */
  done: boolean;
  /** done 阶段：重写是否被采用；start 阶段为 null */
  accepted: boolean | null;
}

/** 修复事件（start / done 两个阶段）。 */
export function repairTrace(data: unknown): RepairTrace {
  const d = rec(data);
  const reasons = arr(d.reasons).map(str).filter(Boolean);
  if (d.stage !== "done") {
    return { text: `自检发现「${reasons.join("、") || "问题"}」，正在带着具体问题重写一次…`, done: false, accepted: null };
  }
  const before = typeof d.before === "number" ? d.before : null;
  const after = typeof d.after === "number" ? d.after : null;
  const delta = before !== null && after !== null ? `（需留意项 ${before} → ${after}）` : "";
  return d.accepted === true
    ? { text: `重写后复检通过${delta}`, done: true, accepted: true }
    : { text: `重写没有改善${delta}，保留原文并追加规则提示`, done: true, accepted: false };
}
