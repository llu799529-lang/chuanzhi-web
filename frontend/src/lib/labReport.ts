/**
 * 化验单报告的跨页面同步。
 *
 * 场景：在 ChatPage 里上传化验单，Agent 出报告后要把结果送到「化验单」页，
 * 否则用户得再传一次同一张图。旧版靠 window.MTSyncLabFromChat + localStorage，
 * 这里换成同构的 store，key 与旧版保持一致，两个前端可以互读。
 */

import { useAuthStore } from "@/stores/auth";

export interface LabItem {
  name: string;
  value: string | number;
  unit?: string;
  ref?: string;
  flag?: string; // high / low / normal
  /** 数值核验：与单位 / 参考范围 / 人体可能范围对不上时由后端标注（backend/lab_check.py） */
  check?: { level?: string; kind?: string; text?: string };
}

export interface LabExplain {
  name?: string;
  text?: string;
  level?: string;
}

export interface LabJudgment {
  q?: string;
  a?: string;
  text?: string;
  level?: string;
  tag?: string;
}

export interface LabReport {
  kind?: string;
  report_title?: string;
  patient?: { gender?: string; age?: string | number };
  sampled_at?: string;
  reported_at?: string;
  confidence?: number | null;
  items?: LabItem[];
  abnormal_count?: number;
  /** 需要对照原单核对的项数 */
  value_checks?: number;
  explains?: LabExplain[];
  judgments?: LabJudgment[];
  followup?: string;
  timestamp?: string;
  advice?: string[];
  department?: string;
  urgency?: string;
  urgency_label?: string;
  disclaimer?: string;
}

/** 报告来源的附带信息：缩略图、文件名、来自哪一页。 */
export interface LabMeta {
  previewUrl?: string;
  fileName?: string;
  source?: "chat" | "lab";
  analyzedAt?: string;
  fileSize?: number;
  elapsedMs?: number;
}

/** 原版 l6 的展示分类；只决定分组，不修改识别结果。 */
export const LAB_CATEGORIES = [
  { name: "血糖相关", keys: ["血糖", "GLU", "糖化", "HbA1c", "胰岛素", "C肽", "餐后"] },
  { name: "血脂相关", keys: ["胆固醇", "甘油三酯", "脂蛋白", "LDL", "HDL", "TC", "TG", "Apo", "载脂蛋白"] },
  { name: "肝功能", keys: ["转氨酶", "ALT", "AST", "GGT", "胆红素", "白蛋白", "ALB", "ALP", "TBIL", "DBIL"] },
  { name: "肾功能", keys: ["肌酐", "尿素", "尿酸", "eGFR", "GFR", "BUN", "UA", "胱抑素", "微量白蛋白"] },
  { name: "血常规", keys: ["白细胞", "红细胞", "血红蛋白", "血小板", "压积", "MCV", "MCH", "MCHC", "WBC", "RBC", "Hb", "PLT", "HCT", "中性", "淋巴", "单核", "嗜"] },
  { name: "电解质", keys: ["钾", "钠", "氯", "钙", "磷", "镁", "CO2"] },
  { name: "凝血", keys: ["凝血", "PT", "APTT", "INR", "D-二聚体", "纤维蛋白", "FDP"] },
  { name: "甲功", keys: ["T3", "T4", "TSH", "FT3", "FT4", "甲状腺"] },
  { name: "炎症标志", keys: ["CRP", "C反应", "血沉", "ESR", "降钙素原", "PCT", "白介素"] },
  { name: "肿瘤标志", keys: ["AFP", "CEA", "CA", "PSA", "肿瘤", "糖类抗原"] },
];

export function labCategory(name: string): string {
  return LAB_CATEGORIES.find((cat) => cat.keys.some((key) => name.includes(key)))?.name ?? "其他";
}

export interface LabRecord {
  owner: string;
  report: LabReport;
  meta: LabMeta;
}

const STORE_KEY = "mt.labReport";

function isRecord(v: unknown): v is Record<string, unknown> {
  return v !== null && typeof v === "object" && !Array.isArray(v);
}

export const labReportStore = {
  get(): LabRecord | null {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (!raw) return null;
      const parsed: unknown = JSON.parse(raw);
      if (!isRecord(parsed) || !isRecord(parsed.report)) return null;
      const owner = useAuthStore().username;
      if (!owner || parsed.owner !== owner) return null;
      return {
        owner,
        report: parsed.report as unknown as LabReport,
        meta: isRecord(parsed.meta) ? (parsed.meta as unknown as LabMeta) : {},
      };
    } catch {
      return null;
    }
  },

  set(report: unknown, meta: LabMeta = {}): void {
    if (!isRecord(report) || !Object.keys(report).length) return;
    const owner = useAuthStore().username;
    if (!owner) return;
    const record: LabRecord = {
      owner,
      report: report as unknown as LabReport,
      meta: { analyzedAt: new Date().toISOString(), ...meta },
    };
    try {
      localStorage.setItem(STORE_KEY, JSON.stringify(record));
    } catch {
      /* 缩略图过大导致超限：丢掉图再存一次 */
      try {
        localStorage.setItem(
          STORE_KEY,
          JSON.stringify({ ...record, meta: { ...record.meta, previewUrl: "" } }),
        );
      } catch {
        /* 彻底写不进去就只留在本次会话里 */
      }
    }
  },

  clear(): void {
    try {
      localStorage.removeItem(STORE_KEY);
    } catch {
      /* ignore */
    }
  },
};
