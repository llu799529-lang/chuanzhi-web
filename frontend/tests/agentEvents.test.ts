import { describe, expect, it } from "vitest";
import { planLine, reflectTrace, repairTrace } from "@/lib/agentEvents";

describe("planLine", () => {
  it("joins numbered steps with arrows", () => {
    expect(planLine({ steps: [{ n: 1, label: "检索知识库" }, { n: 2, label: "进展风险评估" }, { n: 3, label: "生成综合报告" }] }))
      .toBe("1. 检索知识库 → 2. 进展风险评估 → 3. 生成综合报告");
  });
  it("numbers steps itself when the backend omitted n; unlabeled steps are dropped before numbering (so shown numbers stay consecutive)", () => {
    expect(planLine({ steps: [{ label: "A" }, { n: 9 }, { label: "B" }] })).toBe("1. A → 2. B");
    expect(planLine({ steps: [{ n: 4, label: "A" }, { label: "B" }] })).toBe("4. A → 2. B");   // 后端给了 n 就信后端
  });
  it.each([undefined, null, {}, { steps: "x" }, { steps: [] }, 42, "plan"])("returns empty string for %j", (v) => {
    expect(planLine(v)).toBe("");
  });
});

describe("reflectTrace", () => {
  it("lists only the checks that need attention", () => {
    const r = reflectTrace({ checks: [
      { label: "必要证据", status: "ok" }, { label: "红旗提示", status: "fail" },
      { label: "分级数字一致", status: "warn" }, { label: "知识库落点", status: "info" },
    ] });
    expect(r).toEqual({ text: "4 项核查，2 项需留意：红旗提示、分级数字一致", total: 4, attention: 2 });
  });
  it("says there is nothing to note when everything passes (info counts as fine)", () => {
    expect(reflectTrace({ checks: [{ label: "x", status: "ok" }, { label: "y", status: "info" }] }))
      .toEqual({ text: "2 项核查，无异常", total: 2, attention: 0 });
  });
  it("never throws on malformed input", () => {
    expect(reflectTrace(null).total).toBe(0);
    expect(reflectTrace({ checks: [null, 1, "x", { status: "warn" }] }).total).toBe(0);   // 没有 label 的不算
  });
});

describe("repairTrace", () => {
  it("start stage names the reasons", () => {
    expect(repairTrace({ stage: "start", reasons: ["红旗提示", "越界表述"] }))
      .toEqual({ text: "自检发现「红旗提示、越界表述」，正在带着具体问题重写一次…", done: false, accepted: null });
  });
  it("done stage reports acceptance with the before/after counts", () => {
    expect(repairTrace({ stage: "done", accepted: true, before: 2, after: 0 }))
      .toEqual({ text: "重写后复检通过（需留意项 2 → 0）", done: true, accepted: true });
  });
  it("a rejected rewrite says the draft was kept", () => {
    const r = repairTrace({ stage: "done", accepted: false, before: 1, after: 1 });
    expect(r.accepted).toBe(false);
    expect(r.text).toContain("保留原文");
  });
  it("treats a missing stage as start and tolerates missing counts", () => {
    expect(repairTrace({}).done).toBe(false);
    expect(repairTrace({ stage: "done", accepted: true }).text).toBe("重写后复检通过");
  });
});
