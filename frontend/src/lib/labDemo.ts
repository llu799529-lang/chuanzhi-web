/**
 * 化验单「一键识别」示例：与眼底示例同一思路（见 fundusDemo.ts）——评委没有化验单也能体验识别链路。
 * 示例为合成化验单（不含任何真实患者信息），按文件上传到 /api/ai/image，与自行上传走同一接口；
 * 识别调用在线视觉模型，未配置模型时页面会如实提示不可用，而不是展示假结果。
 */
import { fetchFile } from "@/lib/api";

export const LAB_SAMPLE = {
  url: "/samples/lab-sample.png",
  file: "示例_合成化验单.png",
  title: "示例化验单（合成）",
  note: "含空腹血糖、糖化血红蛋白等项目；不含真实患者信息",
} as const;

export function loadLabSample(): Promise<File> {
  return fetchFile(LAB_SAMPLE.url, LAB_SAMPLE.file, "image/png");
}
