import { beforeEach, describe, expect, it, vi } from "vitest";
import { QueryClient } from "@tanstack/vue-query";
import { createPinia, setActivePinia } from "pinia";
import { HEALTH_KEY, healthQueryOptions, liveCheckLabel } from "@/composables/useHealth";

describe("healthQueryOptions", () => {
  beforeEach(() => setActivePinia(createPinia()));

  it("has a stable key and a cache window, and does not refetch on window focus", () => {
    const o = healthQueryOptions();
    expect(o.queryKey).toEqual(["health"]);
    expect(HEALTH_KEY).toEqual(["health"]);
    expect(o.staleTime).toBeGreaterThanOrEqual(30_000);
    expect(o.refetchOnWindowFocus).toBe(false);
    expect(o.retry).toBeLessThanOrEqual(1);
  });

  it("fetches /api/health once and serves the second read from cache", async () => {
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ llm_enabled: false, llm_model: null }) });
    vi.stubGlobal("fetch", fetchMock);
    const client = new QueryClient();
    const a = await client.fetchQuery(healthQueryOptions());
    const b = await client.fetchQuery(healthQueryOptions());
    expect(a).toEqual({ llm_enabled: false, llm_model: null });
    expect(b).toEqual(a);
    expect(fetchMock).toHaveBeenCalledTimes(1);               // 第二次命中缓存
    expect(String(fetchMock.mock.calls[0][0])).toContain("/api/health");
  });

  it("surfaces a failed request as a rejected query instead of hanging", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503, json: async () => ({ detail: "down" }) }));
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    await expect(client.fetchQuery({ ...healthQueryOptions(), retry: false })).rejects.toThrow();
  });
});

describe("liveCheckLabel", () => {
  it("没跑过实测就如实写「未实测」", () => {
    expect(liveCheckLabel(null)).toEqual({ text: "未实测", ok: null });
    expect(liveCheckLabel({ passed: 0, total: 0 })).toEqual({ text: "未实测", ok: null });
  });

  it("跑过就给通过数、日期与没通过的能力（缓存未命中不算失败）", () => {
    const lc = { at: "2026-10-29T10:00:00", passed: 4, total: 5,
      probes: { text: true, json: true, tools: true, stream: true, image: false, cache: false } };
    expect(liveCheckLabel(lc)).toEqual({ text: "4/5 通过 · 2026-10-29 · 未通过：图片", ok: false });
    expect(liveCheckLabel({ ...lc, passed: 5, probes: { text: true } }).ok).toBe(true);
  });
});
