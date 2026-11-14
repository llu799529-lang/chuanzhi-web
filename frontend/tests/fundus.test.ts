import { describe, expect, it } from "vitest";
import { daysBetween, fmtSize, normalizeFundus } from "@/lib/fundus";

/**
 * normalizeFundus 是「接口返回 → 报告视图」的唯一转换点。
 * 三个入口（眼底筛查页 / Agent 助手 / 历史）共用它，所以这里的任何
 * 归一化错误会在三个页面上同时出现。只测纯逻辑，不碰 DOM。
 */
describe("normalizeFundus", () => {
  it("置信度小于 1 时按百分比换算", () => {
    const r = normalizeFundus({ level: 2, confidence: 0.876 }, "eye");
    expect(r.confidence).toBe(87.6);
  });

  it("置信度已大于 1 时原样保留", () => {
    const r = normalizeFundus({ level: 2, confidence: 87.6 }, "eye");
    expect(r.confidence).toBe(87.6);
  });

  it("没有置信度时从概率分布里取对应等级", () => {
    const r = normalizeFundus({ level: 3, probabilities: [5, 10, 15, 62, 8] }, "eye");
    expect(r.confidence).toBeCloseTo(62, 1);
  });

  it("病灶字符串被拆成结构化列表", () => {
    const r = normalizeFundus({ level: 2, lesions: "微血管瘤、点状出血，硬性渗出" }, "eye");
    expect(r.lesions.map((l) => l.type)).toEqual(["微血管瘤", "点状出血", "硬性渗出"]);
  });

  it("「未检出」不产生任何病灶条目", () => {
    const r = normalizeFundus({ level: 0, lesions: "未检出明显病灶" }, "eye");
    expect(r.lesions).toEqual([]);
  });

  it("没给标准明细时按等级补齐 6 级标准", () => {
    const r = normalizeFundus({ level: 2 }, "eye");
    expect(r.criteria.filter((c) => c.hit).length).toBe(2);
    expect(r.criteria.some((c) => !c.hit)).toBe(true);
  });

  it("两个入口对 engine 的判定不同但都有值", () => {
    expect(normalizeFundus({ level: 1, mode: "model" }, "eye").engine).toContain("EfficientNet");
    expect(normalizeFundus({ level: 1, engine: "local" }, "chat").engine).toContain("EfficientNet");
    // 演示模式不能伪装成本地模型
    expect(normalizeFundus({ level: 1 }, "eye").mode).toBe("demo");
  });

  it("meta 里的文件名/尺寸/耗时被带进报告", () => {
    const r = normalizeFundus({ level: 1 }, "eye", {
      fileName: "fundus.png",
      fileSize: 2048,
      elapsedMs: 312,
    });
    expect(r.fileName).toBe("fundus.png");
    expect(r.fileSize).toBe(2048);
    expect(r.elapsedMs).toBe(312);
  });
});

describe("格式化工具", () => {
  it("fmtSize 按量级切单位", () => {
    expect(fmtSize(2048)).toBe("2 KB");
    expect(fmtSize(5 * 1024 * 1024)).toBe("5.0 MB");
    expect(fmtSize(null)).toBe("");
    expect(fmtSize(undefined)).toBe("");
  });

  it("daysBetween 计算整日差", () => {
    expect(daysBetween("2026-10-01", "2026-10-18")).toBe(17);
  });

  it("daysBetween 遇到无法解析的值返回 null 而不是 NaN", () => {
    expect(daysBetween("", "2026-10-18")).toBeNull();
    expect(daysBetween("2026-10-01", "坏数据")).toBeNull();
  });
});
