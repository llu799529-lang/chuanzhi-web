import { beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { PAGE_META, useWorkbenchStore } from "@/stores/workbench";
import { useAuthStore } from "@/stores/auth";
import { fundusStore } from "@/lib/fundus";
import { AGENT_SAMPLES, SYMPTOM_SAMPLES } from "@/lib/guide";

const KEYS = ["mt_token", "mt_username", "mt.labReport", "mt_fundus_report_v6", "mt_fundus_report_v7"];

function memoryStorage(): Storage {
  const m = new Map<string, string>();
  return {
    get length() {
      return m.size;
    },
    clear: () => m.clear(),
    getItem: (k: string) => (m.has(k) ? (m.get(k) as string) : null),
    key: (i: number) => [...m.keys()][i] ?? null,
    removeItem: (k: string) => void m.delete(k),
    setItem: (k: string, v: string) => void m.set(k, String(v)),
  };
}

beforeEach(() => {
  vi.stubGlobal("localStorage", memoryStorage());
  for (const k of KEYS) localStorage.removeItem(k);
  setActivePinia(createPinia());
});

describe("跨页请求（工作台 / 使用指南 → 目标页）", () => {
  it("示例请求只被对应页面消费一次", () => {
    const wb = useWorkbenchStore();
    wb.requestDemo("lab");
    expect(wb.takeDemo("eye")).toBe(false);
    expect(wb.takeDemo("lab")).toBe(true);
    expect(wb.takeDemo("lab")).toBe(false);
    wb.requestDemo();
    expect(wb.takeDemo()).toBe(true);
  });

  it("示例文字只交给目标页，取走后清空", () => {
    const wb = useWorkbenchStore();
    wb.prefill("symptom", "头晕三天");
    expect(wb.takeText("chat")).toBe("");
    expect(wb.takeText("symptom")).toBe("头晕三天");
    expect(wb.takeText("symptom")).toBe("");
  });

  it("换账号时清掉未消费的请求", () => {
    const wb = useWorkbenchStore();
    wb.request("eye", "fresh");
    useAuthStore().save({ token: "t-new", username: "someone" });
    expect(wb.take("eye", "fresh")).toBe(null);
  });

  it("导航包含使用指南，示例数量正确", () => {
    expect(PAGE_META.guide.label).toBe("使用指南");
    expect(SYMPTOM_SAMPLES.filter((s) => s.red).length).toBe(1);
    expect(AGENT_SAMPLES.length).toBe(3);
  });
});

describe("眼底报告缓存按账号隔离（新用户不能看到别人的眼底图）", () => {
  it("只读得到自己账号的报告", () => {
    const auth = useAuthStore();
    auth.save({ token: "t1", username: "alice" });
    fundusStore.set({ id: "r-alice" } as never);
    expect(JSON.stringify(fundusStore.get())).toBe(JSON.stringify({ id: "r-alice" }));
    localStorage.setItem("mt_username", "bob");      // 同一浏览器换成另一个账号
    expect(fundusStore.get()).toBe(null);
  });

  it("换账号登录、退出登录都会清掉报告缓存", () => {
    const auth = useAuthStore();
    auth.save({ token: "t1", username: "alice" });
    fundusStore.set({ id: "r-alice" } as never);
    auth.save({ token: "t2", username: "bob" });
    expect(!localStorage.getItem("mt_fundus_report_v7")).toBe(true);
    fundusStore.set({ id: "r-bob" } as never);
    auth.clear();
    expect(!localStorage.getItem("mt_fundus_report_v7")).toBe(true);
  });

  it("旧版不分账号的缓存直接丢弃", () => {
    useAuthStore().save({ token: "t1", username: "alice" });
    localStorage.setItem("mt_fundus_report_v6", JSON.stringify({ id: "old" }));
    expect(fundusStore.get()).toBe(null);
    expect(!localStorage.getItem("mt_fundus_report_v6")).toBe(true);
  });
});
