import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { useAuthStore } from "@/stores/auth";
import { useRecordsStore } from "@/stores/records";
import { useWorkbenchStore } from "@/stores/workbench";
import { labReportStore } from "@/lib/labReport";

beforeEach(() => {
  const data = new Map<string, string>();
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => data.get(k) ?? null,
    setItem: (k: string, v: string) => data.set(k, v),
    removeItem: (k: string) => data.delete(k),
  });
  setActivePinia(createPinia());
});
afterEach(() => vi.unstubAllGlobals());

describe("account isolation", () => {
  it("clears history, usage and pending department when signing out", () => {
    const auth = useAuthStore();
    auth.save({ username: "alice", token: "alice-token" });
    const rec = useRecordsStore();
    const wb = useWorkbenchStore();
    rec.records = [{ id: 1, input_type: "化验单", level: null, department: "内分泌科", urgency: "yellow", summary: "Alice private report", created_at: "2026-10-29" }];
    rec.loaded = true;
    rec.usage.month_used = 12;
    wb.goWithDept("hospital", "内分泌科");
    auth.clear();
    expect(rec.records).toEqual([]);
    expect(rec.loaded).toBe(false);
    expect(rec.usage.month_used).toBe(0);
    expect(wb.pendingDept).toBe("");
    expect(wb.page).toBe("chat");
  });

  it("ignores a previous account's response arriving after a new login", async () => {
    const auth = useAuthStore();
    auth.save({ username: "alice", token: "alice-token" });
    const rec = useRecordsStore();
    let finish!: (v: Response) => void;
    vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise<Response>((resolve) => { finish = resolve; })));
    const pending = rec.load();
    auth.clear();
    auth.save({ username: "bob", token: "bob-token" });
    finish(new Response(JSON.stringify({ records: [{ id: 1, summary: "Alice private report" }], usage: { month_used: 12, month_quota: 200 } })));
    await pending;
    expect(rec.records).toEqual([]);
    expect(rec.loaded).toBe(false);
    expect(rec.usage.month_used).toBe(0);
  });

  it("does not expose persisted lab details to another account or trust an unowned legacy report", () => {
    const auth = useAuthStore();
    auth.save({ username: "alice", token: "alice-token" });
    labReportStore.set({ items: [{ name: "HbA1c", value: 8.2, unit: "%" }] });
    expect(labReportStore.get()?.report.items?.[0].value).toBe(8.2);
    auth.save({ username: "bob", token: "bob-token" });
    expect(labReportStore.get()).toBeNull();
    localStorage.setItem("mt.labReport", JSON.stringify({ report: { items: [{ name: "private", value: 9 }] }, meta: {} }));
    expect(labReportStore.get()).toBeNull();
  });
});
