/**
 * 双眼联合筛查：左右眼各一张眼底彩照，分别分级后合成患者层面的结论。
 *
 * 规则（与糖网筛查的通行做法一致）：
 *  1. 按两眼中较重的一只眼给出转诊科室与复查时限；分级相同时取紧急程度更高的一只。
 *     「较重」用单眼报告保守升级后的级别（边界病例已按更高一级给时限）。
 *  2. 照片不可评估（失焦、过暗、视野不全）的眼不参与分级——不可评估不等于正常：
 *     提示重拍，无法重拍时到眼科检查；整体紧急程度至少为「黄色」。
 *  3. 两眼分级相差 2 级及以上时，提醒就诊时告诉医生两眼的差异。
 */
import type { FundusReport } from "@/lib/fundus";
import type { Urgency } from "@/stores/records";

export type EyeSide = "right" | "left";
export const SIDES: EyeSide[] = ["right", "left"];
export const EYE_CN: Record<EyeSide, string> = { right: "右眼", left: "左眼" };
export const EYE_CODE: Record<EyeSide, string> = { right: "OD", left: "OS" };

const RANK: Record<Urgency, number> = { green: 0, yellow: 1, orange: 2, red: 3 };
/** 合成结论被「另一只眼不可评估」抬高紧急程度时用的文字（单眼报告自带的文字优先） */
const URG_DESC: Record<Urgency, string> = { green: "常规复查", yellow: "尽快就诊", orange: "优先就诊", red: "立即就诊" };

function urgencyOf(r: FundusReport): Urgency {
  return (r.urgency in RANK ? r.urgency : "green") as Urgency;
}

export interface BilateralResult {
  /** 可评估的眼数：0 / 1 / 2 */
  gradable: number;
  /** 决定结论的那只眼；两眼都不可评估时为 null */
  worse: EyeSide | null;
  level: number | null;
  urgency: Urgency;
  urgencyLabel: string;
  department: string;
  advice: string;
  headline: string;
  notes: string[];
}

/** 能否据此分级：只有「不可评估」的照片排除；「质量偏低」照常分级，另提示可能有偏差 */
export function isGradable(r: FundusReport): boolean {
  return r.quality !== "不可评估";
}

function effective(r: FundusReport): number {
  return Math.max(r.level, r.escalatedTo ?? r.level);
}

export function combineEyes(right: FundusReport, left: FundusReport): BilateralResult {
  const eyes: [EyeSide, FundusReport][] = [
    ["right", right],
    ["left", left],
  ];
  const ok = eyes.filter(([, r]) => isGradable(r));
  const bad = eyes.filter(([, r]) => !isGradable(r));
  const notes: string[] = [];
  for (const [s, r] of bad) {
    const reasons = r.qualityReasons ?? [];
    const why = reasons.length ? `（${reasons.slice(0, 2).join("、")}）` : "";
    notes.push(`${EYE_CN[s]}照片不可评估${why}：请重拍；无法拍到清晰照片时请到眼科检查——不可评估不等于正常。`);
  }
  if (!ok.length) {
    return {
      gradable: 0,
      worse: null,
      level: null,
      urgency: "yellow",
      urgencyLabel: URG_DESC.yellow,
      department: "眼科",
      advice: "两眼都需要重拍；无法拍到清晰照片时，请尽快到眼科做散瞳眼底检查。",
      headline: "两眼照片都不可评估，暂时不能给出分级",
      notes,
    };
  }
  const sorted = [...ok].sort(
    ([, a], [, b]) => effective(b) - effective(a) || RANK[urgencyOf(b)] - RANK[urgencyOf(a)],
  );
  const [ws, w] = sorted[0];
  let urgency = ok.reduce<Urgency>((m, [, r]) => (RANK[urgencyOf(r)] > RANK[m] ? urgencyOf(r) : m), "green");
  if (bad.length && RANK[urgency] < RANK.yellow) urgency = "yellow";
  let headline: string;
  if (sorted.length === 2) {
    const [, other] = sorted[1];
    headline =
      w.level === other.level && effective(w) === effective(other)
        ? `两眼均为 DR ${w.level} 级（${w.levelLabel}）`
        : `按较重的${EYE_CN[ws]}给出建议：DR ${w.level} 级（${w.levelLabel}）`;
    const diff = Math.abs(w.level - other.level);
    if (diff >= 2) notes.push(`两眼分级相差 ${diff} 级，就诊时请把两眼的差异告诉医生。`);
  } else {
    headline = `${EYE_CN[ws]} DR ${w.level} 级（${w.levelLabel}）；${EYE_CN[bad[0][0]]}需要重拍`;
  }
  for (const [s, r] of ok) {
    if (r.escalatedTo != null && r.escalatedTo > r.level) {
      notes.push(`${EYE_CN[s]}处在 ${r.level} 级与 ${r.escalatedTo} 级的边界，已按更保守的 ${r.escalatedTo} 级时限建议。`);
    }
    if (r.quality === "质量偏低") notes.push(`${EYE_CN[s]}照片质量偏低，分级可能有偏差，条件允许时建议重拍。`);
  }
  return {
    gradable: ok.length,
    worse: ws,
    level: w.level,
    urgency,
    urgencyLabel: urgency === urgencyOf(w) ? w.urgencyLabel : URG_DESC[urgency],
    department: w.department,
    advice: w.advice,
    headline,
    notes,
  };
}

/** 给医生的双眼摘要（纯文本，可直接复制） */
export function pairSummary(right: FundusReport, left: FundusReport): string {
  const b = combineEyes(right, left);
  const line = (s: EyeSide, r: FundusReport) =>
    `- ${EYE_CN[s]}（${EYE_CODE[s]}）：` +
    (isGradable(r) ? `DR ${r.level} 级（${r.levelLabel}）` : `照片不可评估（模型给出 ${r.level} 级，仅供参考）`) +
    `，置信度 ${r.confidence == null ? "–" : r.confidence.toFixed(1) + "%"}，图像质量 ${r.quality || "–"}`;
  return [
    "MedTriage · 双眼眼底筛查摘要（给医生）",
    `- 结论：${b.headline}`,
    `- 紧急程度：${b.urgencyLabel}；建议科室：${b.department}`,
    ...(b.advice ? [`- 复查 / 就诊：${b.advice}`] : []),
    line("right", right),
    line("left", left),
    ...b.notes.map((n) => `- 提示：${n}`),
    "⚠ 以上为 AI 筛查参考，不是诊断，请以眼科医生检查为准。",
  ].join("\n");
}
