/**
 * 眼底报告模型：接口原始返回 → 视图模型（平移自 app.js 的 normalizeFundusReport）。
 * 三个入口（眼底筛查页 / Agent助手 / 历史）共用同一份归一化，保证报告字段一致。
 */
export const DR_LONG = [
  "无明显视网膜病变",
  "轻度非增殖期糖网（NPDR）",
  "中度非增殖期糖网（NPDR）",
  "重度非增殖期糖网（NPDR）",
  "增殖期糖网（PDR）",
];

export const R6_STD = [
  { hit: "视网膜结构清晰，未见微血管瘤、出血或渗出", name: "未见明显病灶" },
  { hit: "仅见散在微血管瘤，未见出血 / 渗出", name: "微血管瘤" },
  { hit: "微血管瘤合并视网膜点状出血 / 硬性渗出", name: "微血管瘤 + 出血 / 渗出" },
  { hit: "出现 4 象限广泛出血、静脉串珠样改变或明显视网膜内微血管异常（IRMA）", name: "广泛出血 / 静脉串珠 / IRMA" },
  { hit: "出现新生血管、玻璃体 / 视网膜前出血或纤维增殖膜", name: "新生血管 / 增殖期改变" },
];

export interface RawFundus {
  level: number;
  level_label?: string;
  level_label_long?: string;
  level_name?: string;
  confidence?: number;
  probabilities?: (number | { level?: number; probability?: number })[];
  heatmap?: string;
  heatmap_layer?: string;
  heatmap_status?: string;
  image_quality?: string;
  quality_reasons?: string[];
  retake?: boolean;
  escalated_to?: number | null;
  eye?: string;
  lesions?: string | { type: string; count?: number; desc?: string; loc?: string }[];
  criteria?: { hit: boolean; text: string }[];
  department?: string;
  urgency?: "green" | "yellow" | "orange" | "red";
  urgency_label?: string;
  advice?: string;
  followup?: string;
  pre_visit_notes?: string[];
  advice_list?: string[];
  red_flags?: string[];
  reds?: string[];
  doctor_summary?: string;
  summary?: string;
  mode?: string;
  engine?: string;
  timestamp?: string;
  disclaimer?: string;
}

export interface Lesion {
  type: string;
  count: number | null;
  desc: string;
  loc: string;
}

export interface Crit {
  hit: boolean;
  text: string;
}

export interface FundusReport {
  source: "eye" | "chat";
  level: number;
  levelLabel: string;
  confidence: number | null;
  heatmap: string | null;
  /** 0～4 级各自的概率（百分数）；旧报告没有 */
  probs: number[] | null;
  /** 透明热力层：专业阅片里叠在增强 / 无赤光图上；旧报告没有 */
  heatLayer: string | null;
  heatStatus: string;
  /** 专业阅片用的原图（长边不超过 1400 像素）；旧报告只有缩略图 */
  viewImage: string | null;
  /** 图像质量：可评估 / 质量偏低 / 不可评估（旧报告为空串） */
  quality: string;
  qualityReasons: string[];
  retake: boolean;
  /** 边界病例：按更保守的这一级给出就诊时限 */
  escalatedTo: number | null;
  /** 双眼筛查时是哪只眼 */
  eye: "right" | "left" | null;
  thumbnail: string | null;
  fileName: string;
  fileDim: string | null;
  fileSize: number | null;
  analyzedAt: string;
  elapsedMs: number | null;
  mode: string;
  engine: string;
  lesions: Lesion[];
  criteria: Crit[];
  department: string;
  urgency: string;
  urgencyLabel: string;
  advice: string;
  preVisitNotes: string[] | null;
  redFlags: string[] | null;
  doctorSummary: string;
  summary: string;
  disclaimer?: string;
}

export interface EyeMeta {
  thumbnail?: string | null;
  viewImage?: string | null;
  fileDim?: string | null;
  fileName?: string;
  fileSize?: number | null;
  elapsedMs?: number | null;
  analyzedAt?: string;
}

export function normalizeFundus(raw: RawFundus, source: "eye" | "chat", meta: EyeMeta = {}): FundusReport {
  const level = raw.level;
  let probs: { p: number }[] = [];
  if (raw.probabilities?.length) {
    const first = raw.probabilities[0];
    probs = raw.probabilities.map((p) =>
      typeof p === "object" ? { p: (p.probability ?? 0) * 100 } : { p: p as number },
    );
    void first;
  }
  let conf: number | null = null;
  if (raw.confidence != null) conf = raw.confidence <= 1 ? raw.confidence * 100 : raw.confidence;
  else if (probs[level]) conf = probs[level].p;
  conf = conf == null ? null : Math.round(conf * 10) / 10;

  let lesions: Lesion[] = [];
  if (Array.isArray(raw.lesions) && raw.lesions.length) {
    lesions = raw.lesions.map((l) => ({
      type: l.type,
      count: l.count ?? null,
      desc: l.desc || "",
      loc: l.loc || "",
    }));
  } else if (typeof raw.lesions === "string" && raw.lesions && !raw.lesions.includes("未检出")) {
    lesions = raw.lesions
      .split(/[、,，;；]/)
      .map((s) => s.trim())
      .filter(Boolean)
      .map((t) => ({ type: t, count: null, desc: "", loc: "" }));
  }

  let mode: string;
  let engine: string;
  if (source === "eye") {
    mode = raw.mode || "demo";
    engine =
      raw.mode === "model" ? "EfficientNet-B3 本地模型" : raw.mode === "llm" ? "大模型视觉分析" : "演示模式";
  } else {
    mode = raw.engine === "local" ? "model" : "llm";
    engine = raw.engine === "local" ? "EfficientNet-B3 本地模型" : "大模型视觉分析";
  }

  let criteria: Crit[];
  if (Array.isArray(raw.criteria) && raw.criteria.length) {
    criteria = raw.criteria.map((c) => ({ hit: !!c.hit, text: c.text }));
  } else {
    criteria = [];
    for (let i = 1; i <= level; i++) criteria.push({ hit: true, text: `符合 ${i} 级标准：${R6_STD[i].hit}` });
    for (let j = level + 1; j <= 4 && j <= level + 3; j++) {
      criteria.push({ hit: false, text: `未见 ${R6_STD[j].name}（${j} 级及以上标准）` });
    }
    if (!criteria.length) criteria.push({ hit: true, text: R6_STD[0].hit });
  }

  const levelLabel = raw.level_label_long || raw.level_label || raw.level_name || DR_LONG[level] || "";
  let doctorSummary = raw.doctor_summary;
  if (!doctorSummary) {
    doctorSummary =
      `筛查结果：DR ${level} 级（${levelLabel}），模型置信度 ${conf == null ? "–" : conf.toFixed(1) + "%"}` +
      `。主要可疑征象：${
        lesions.length
          ? lesions.map((l) => l.type + (l.count ? `×${l.count}` : "")).join("、")
          : "未检出明显病灶"
      }。建议转诊科室：${raw.department || "眼科"}，随访建议：${raw.advice || raw.followup || "遵医嘱复查"}。`;
  }

  return {
    source,
    level,
    levelLabel,
    confidence: conf,
    heatmap: raw.heatmap || null,
    probs: probs.length === 5 ? probs.map((x) => Math.round(x.p * 10) / 10) : null,
    heatLayer: raw.heatmap_layer || null,
    heatStatus: raw.heatmap_status || "",
    viewImage: meta.viewImage || null,
    quality: raw.image_quality || "",
    qualityReasons: Array.isArray(raw.quality_reasons) ? raw.quality_reasons.map(String) : [],
    retake: !!raw.retake,
    escalatedTo: typeof raw.escalated_to === "number" ? raw.escalated_to : null,
    eye: raw.eye === "right" || raw.eye === "left" ? raw.eye : null,
    thumbnail: meta.thumbnail || null,
    fileName: meta.fileName || "眼底彩照",
    fileDim: meta.fileDim || null,
    fileSize: meta.fileSize ?? null,
    analyzedAt: raw.timestamp || meta.analyzedAt || localNow(),
    elapsedMs: meta.elapsedMs ?? null,
    mode,
    engine,
    lesions,
    criteria,
    department: raw.department || "眼科",
    urgency: raw.urgency || "green",
    urgencyLabel: raw.urgency_label || "常规",
    advice: raw.advice || raw.followup || "",
    preVisitNotes: raw.pre_visit_notes || (Array.isArray(raw.advice_list) ? raw.advice_list : null),
    redFlags: raw.red_flags || (Array.isArray(raw.reds) ? raw.reds : null),
    doctorSummary,
    summary: raw.summary || "",
    disclaimer: raw.disclaimer,
  };
}

/** 本地时间串（与后端 timestamp 同格式），避免 UTC 偏移 */
export function localNow(): string {
  const d = new Date();
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

export function fmtFull(iso: string | null | undefined): string {
  if (!iso) return "–";
  const d = new Date(String(iso).replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return String(iso);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function fmtSize(bytes: number | null | undefined): string {
  if (!bytes) return "";
  return bytes > 1024 * 1024 ? `${(bytes / 1024 / 1024).toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`;
}

export function daysBetween(a: string, b: string): number | null {
  const da = new Date(String(a).replace(" ", "T"));
  const db = new Date(String(b).replace(" ", "T"));
  if (Number.isNaN(da.getTime()) || Number.isNaN(db.getTime())) return null;
  return Math.max(0, Math.round((db.getTime() - da.getTime()) / 86400000));
}

/** 原图 → 缩略图 dataURL（控制体积，报告头展示用） */
export function makeThumb(src: string): Promise<{ url: string | null; dim: string | null }> {
  return new Promise((resolve) => {
    if (!src) return resolve({ url: null, dim: null });
    const img = new Image();
    img.onload = () => {
      try {
        const c = document.createElement("canvas");
        const s = Math.min(1, 256 / Math.max(img.width, img.height));
        c.width = Math.max(1, Math.round(img.width * s));
        c.height = Math.max(1, Math.round(img.height * s));
        c.getContext("2d")?.drawImage(img, 0, 0, c.width, c.height);
        resolve({ url: c.toDataURL("image/jpeg", 0.82), dim: `${img.width}×${img.height}` });
      } catch {
        resolve({ url: null, dim: `${img.width}×${img.height}` });
      }
    };
    img.onerror = () => resolve({ url: null, dim: null });
    img.src = src;
  });
}

/** 专业阅片用的图：长边不超过 maxSide，JPEG 0.9。原图可能有几千像素，浏览器里做增强与本地保存都太重。 */
export function makeView(src: string, maxSide = 1400): Promise<{ url: string | null }> {
  return new Promise((resolve) => {
    if (!src) return resolve({ url: null });
    const img = new Image();
    img.onload = () => {
      try {
        const s = Math.min(1, maxSide / Math.max(img.width, img.height));
        const c = document.createElement("canvas");
        c.width = Math.max(1, Math.round(img.width * s));
        c.height = Math.max(1, Math.round(img.height * s));
        c.getContext("2d")?.drawImage(img, 0, 0, c.width, c.height);
        resolve({ url: c.toDataURL("image/jpeg", 0.9) });
      } catch {
        resolve({ url: null });
      }
    };
    img.onerror = () => resolve({ url: null });
    img.src = src;
  });
}

const STORE_KEY = "mt_fundus_report_v7";
const PAIR_KEY = "mt_fundus_pair_v1";
/** 旧版缓存不区分账号：同一浏览器换个账号登录，会看到上一个人的眼底图（实测反馈）。读到就删。 */
const LEGACY_KEYS = ["mt_fundus_report_v6"];

/** 当前登录的账号：登录时 auth store 写入、退出时删除（直接读存储，避免这个工具模块依赖 Pinia 是否已激活） */
function currentUser(): string {
  try {
    return localStorage.getItem("mt_username") || "";
  } catch {
    return "";
  }
}

/** 存不下时逐级瘦身：先去掉阅片大图，再去掉热力图 */
function slim(r: FundusReport, level: number): FundusReport {
  if (level <= 0) return r;
  const s = { ...r, viewImage: null };
  return level === 1 ? s : { ...s, heatmap: null, heatLayer: null };
}

function load<T>(key: string): T | null {
  try {
    for (const k of LEGACY_KEYS) localStorage.removeItem(k);
    const owner = currentUser();
    const raw = localStorage.getItem(key);
    if (!owner || !raw) return null;
    const saved = JSON.parse(raw) as { owner?: string; report?: T };
    return saved.owner === owner && saved.report ? saved.report : null;
  } catch {
    return null;
  }
}

function save<T>(key: string, value: T | null, shrink: (v: T, level: number) => T): void {
  try {
    if (!value) {
      localStorage.removeItem(key);
      return;
    }
    const owner = currentUser();
    if (!owner) return;
    for (let level = 0; level <= 2; level++) {
      try {
        localStorage.setItem(key, JSON.stringify({ owner, report: shrink(value, level) }));
        return;
      } catch {
        /* 超出存储上限：瘦身后再试 */
      }
    }
  } catch {
    /* 彻底写不进去就只在内存里用 */
  }
}

/** 报告持久化：刷新页面后仍能看到**本账号**上一次的结果；换账号、退出登录后不再显示 */
export const fundusStore = {
  get(): FundusReport | null {
    return load<FundusReport>(STORE_KEY);
  },
  set(r: FundusReport | null) {
    save(STORE_KEY, r, slim);
  },
};

export interface FundusPair {
  right: FundusReport;
  left: FundusReport;
}

/** 双眼筛查结果（同样按账号隔离）。与单眼报告只保留最新的一种：保存一种时调用方清掉另一种。 */
export const fundusPairStore = {
  get(): FundusPair | null {
    const p = load<FundusPair>(PAIR_KEY);
    return p && p.right && p.left ? p : null;
  },
  set(p: FundusPair | null) {
    save(PAIR_KEY, p, (v, level) => ({ right: slim(v.right, level), left: slim(v.left, level) }));
  },
};
