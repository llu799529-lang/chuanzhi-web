import { existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { FUNDUS_SAMPLES, PIPELINE_STEPS, loadSample, pipelineStage, stepState } from "@/lib/fundusDemo";
import { LAB_SAMPLE, loadLabSample } from "@/lib/labDemo";

const PUBLIC = fileURLToPath(new URL("../public/", import.meta.url));

describe("眼底上传演示", () => {
  beforeEach(() => {
    vi.stubGlobal("localStorage", { getItem: () => "", setItem: () => undefined, removeItem: () => undefined });
    setActivePinia(createPinia());
  });
  afterEach(() => vi.unstubAllGlobals());

  it("每张示例图都真实存在于 public/（构建后由同一服务静态托管）", () => {
    for (const s of FUNDUS_SAMPLES) {
      expect(s.url.startsWith("/samples/")).toBe(true);
      expect(existsSync(PUBLIC + s.url.slice(1))).toBe(true);
    }
  });

  it("步骤按时间推进，但停在「本地模型分级」等待真实响应，不提前宣布完成", () => {
    expect(pipelineStage(0, false)).toBe(0);
    expect(pipelineStage(650, false)).toBe(1);
    expect(pipelineStage(60_000, false)).toBe(2);
    expect(pipelineStage(5, true)).toBe(PIPELINE_STEPS.length);
    expect([0, 1, 2, 3].map((i) => stepState(i, 2))).toEqual(["done", "done", "run", ""]);
  });

  it("示例图按文件上传：与用户自己选图走同一个分析函数", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(new Blob([new Uint8Array([1, 2, 3])], { type: "image/jpeg" }))));
    const f = await loadSample(FUNDUS_SAMPLES[0]);
    expect(f.name).toBe(FUNDUS_SAMPLES[0].file);
    expect(f.size).toBe(3);
  });

  it("示例图加载失败时明确报错，而不是静默", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("", { status: 404 })));
    await expect(loadSample(FUNDUS_SAMPLES[0])).rejects.toThrow();
  });
});

describe("化验单示例", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("示例化验单存在于 public/，并按文件上传（与自行上传同一接口）", async () => {
    expect(existsSync(PUBLIC + LAB_SAMPLE.url.slice(1))).toBe(true);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(new Blob([new Uint8Array([9, 9])], { type: "image/png" }))));
    const f = await loadLabSample();
    expect(f.name).toBe(LAB_SAMPLE.file);
    expect(f.type).toBe("image/png");
  });
});
