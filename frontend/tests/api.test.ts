import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { api, ApiError, errorFromResponse, setUnauthorizedHandler, upload } from "@/lib/api";

function json(body: unknown, status = 200, headers: Record<string, string> = {}) {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json", ...headers } });
}

beforeEach(() => {
  vi.stubGlobal("localStorage", { getItem: () => "tok-123", setItem: () => undefined, removeItem: () => undefined });
  setActivePinia(createPinia());
});

afterEach(() => {
  setUnauthorizedHandler(null);
  vi.unstubAllGlobals();
});

describe("errorFromResponse", () => {
  it("把后端统一错误体变成带 code 与 Retry-After 的 ApiError", async () => {
    const e = await errorFromResponse(json({ detail: "操作过快，请 2 秒后再试", code: "RATE_LIMITED" }, 429, { "Retry-After": "2" }));
    expect(e).toBeInstanceOf(ApiError);
    expect(e.message).toBe("操作过快，请 2 秒后再试");
    expect(e.code).toBe("RATE_LIMITED");
    expect(e.retryAfter).toBe(2);
    expect(e.isRateLimited).toBe(true);
  });

  it("detail 不是字符串（旧版 422 的对象数组）时用兜底文案，不显示 [object Object]", async () => {
    const e = await errorFromResponse(json({ detail: [{ loc: ["body", "text"], msg: "field required" }] }, 422), "提交失败");
    expect(e.message).toBe("提交失败（422）");
    expect(e.retryAfter).toBeNull();
  });

  it("响应体不是 JSON 也不抛二次异常", async () => {
    const e = await errorFromResponse(new Response("<html>bad gateway</html>", { status: 502 }), "分析失败");
    expect(e.message).toBe("分析失败（502）");
    expect(e.code).toBe("");
  });
});

describe("api()", () => {
  it("带上登录头，普通对象按 JSON 发送", async () => {
    const fetchMock = vi.fn().mockResolvedValue(json({ ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await api("/api/ai/symptom", { method: "POST", body: { text: "头晕" } });
    const [, init] = fetchMock.mock.calls[0];
    expect(init.headers.Authorization).toBe("Bearer tok-123");
    expect(init.headers["Content-Type"]).toBe("application/json");
    expect(init.body).toBe(JSON.stringify({ text: "头晕" }));
  });

  it("业务接口 401 触发「登录过期」处理器", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "登录已过期，请重新登录", code: "UNAUTHORIZED" }, 401)));
    const onExpired = vi.fn();
    setUnauthorizedHandler(onExpired);
    await expect(api("/api/records")).rejects.toBeInstanceOf(ApiError);
    expect(onExpired).toHaveBeenCalledTimes(1);
  });

  it("登录接口的 401 是密码错误，不能把人踢回登录页", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(json({ detail: "用户名或密码不正确", code: "UNAUTHORIZED" }, 401)));
    const onExpired = vi.fn();
    setUnauthorizedHandler(onExpired);
    await expect(api("/api/auth/login", { method: "POST", body: {} })).rejects.toBeInstanceOf(ApiError);
    expect(onExpired).toHaveBeenCalledTimes(0);
  });
});

describe("upload()", () => {
  it("用 FormData 发文件、不设 Content-Type（让浏览器带 boundary），失败时用调用方的兜底文案", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response("", { status: 500 }));
    vi.stubGlobal("fetch", fetchMock);
    const file = new File([new Uint8Array([1, 2, 3])], "eye.png", { type: "image/png" });
    let err: unknown;
    try { await upload("/api/fundus/analyze", file, "分析失败"); } catch (e) { err = e; }
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/api/fundus/analyze");
    expect(init.body instanceof FormData).toBe(true);
    expect(init.headers["Content-Type"]).toBeUndefined();
    expect(init.headers.Authorization).toBe("Bearer tok-123");
    expect((err as ApiError).message).toBe("分析失败（500）");
  });
});
