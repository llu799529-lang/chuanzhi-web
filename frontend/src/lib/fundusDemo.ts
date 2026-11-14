/**
 * 眼底「上传演示」——回应预赛评审意见「建议增加眼底图片上传演示」。
 *
 * 1. 内置示例图：没有眼底照片的评委 / 用户也能一键体验。示例图按「文件」上传，与用户自己选图
 *    调用的是同一个接口（/api/fundus/analyze），不是预先算好的报告。
 * 2. 处理步骤可视化：按服务端实际处理顺序展示五步。前两步按时间推进，停在「本地模型分级」
 *    等真实响应，响应回来才全部标记完成——不提前宣布结果。
 */
import { fetchFile } from "@/lib/api";

export interface FundusSample {
  id: string;
  url: string;
  file: string;
  title: string;
  note: string;
}

export const FUNDUS_SAMPLES: readonly FundusSample[] = [
  { id: "clear", url: "/samples/fundus-sample.jpg", file: "示例A_眼底彩照.jpg",
    title: "示例 A · 眼底彩照", note: "真实眼底彩照，走完整分级与热力图流程" },
  { id: "blurry", url: "/samples/fundus-blurry.jpg", file: "示例B_失焦照片.jpg",
    title: "示例 B · 失焦照片", note: "同一张图人为模糊，演示质量评估与「建议重拍」" },
];

export const PIPELINE_STEPS = [
  { t: "上传与校验", d: "格式 · ≤20MB · 图像可解码" },
  { t: "图像质量评估", d: "曝光 · 清晰度 · 视野" },
  { t: "本地模型分级", d: "EfficientNet-B3 · 翻转 TTA" },
  { t: "Grad-CAM 热力图", d: "标出影响分级的区域" },
  { t: "分诊与报告", d: "边界病例保守升级 · 建议科室" },
] as const;

const HOLD_AT = 2; // 「本地模型分级」：没有真实响应之前不越过这一步
const STEP_MS = 600;

/** 当前步骤序号；done=true 表示真实响应已返回，全部完成。 */
export function pipelineStage(elapsedMs: number, done: boolean): number {
  if (done) return PIPELINE_STEPS.length;
  return Math.min(HOLD_AT, Math.max(0, Math.floor(elapsedMs / STEP_MS)));
}

export function stepState(i: number, stage: number): "done" | "run" | "" {
  return i < stage ? "done" : i === stage ? "run" : "";
}

/** 把示例图读成 File，交给与手动上传相同的分析函数。 */
export function loadSample(s: FundusSample): Promise<File> {
  return fetchFile(s.url, s.file, "image/jpeg");
}
