// @vitest-environment jsdom
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { createApp, h, nextTick, ref } from "vue";
import MultiPage from "@/features/workbench/pages/MultiPage.vue";
import LabPage from "@/features/workbench/pages/LabPage.vue";
import { useAuthStore } from "@/stores/auth";
import { useRecordsStore } from "@/stores/records";
import { labReportStore } from "@/lib/labReport";

let dispose: (() => void) | undefined;
beforeEach(() => {
  const data = new Map<string, string>();
  vi.stubGlobal("localStorage", { getItem: (k: string) => data.get(k) ?? null, setItem: (k: string, v: string) => data.set(k, v), removeItem: (k: string) => data.delete(k) });
  setActivePinia(createPinia());
  useAuthStore().save({ username: "alice", token: "alice-token" });
  useRecordsStore().loaded = true;
});
afterEach(() => { dispose?.(); dispose = undefined; vi.unstubAllGlobals(); });

it("sends full lab values to the real page request and invalidates the result after a new lab report", async () => {
  const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(new Response(JSON.stringify({ intro: "报告", findings: [] }))));
  vi.stubGlobal("fetch", fetchMock);
  const lab = { items: [{ name: "HbA1c", value: 8.2, unit: "%", ref: "4-6", flag: "high" }] };
  labReportStore.set(lab);
  const active = ref(true);
  const app = createApp({ render: () => h(MultiPage, { active: active.value }) });
  const root = document.createElement("div");
  app.mount(root); dispose = () => app.unmount();
  await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
  expect(JSON.parse(fetchMock.mock.calls[0][1].body).lab_detail).toEqual(lab);
  await vi.waitFor(() => expect(root.querySelector("button")?.disabled).toBe(false));
  active.value = false; await nextTick();
  labReportStore.set({ ...lab, items: [{ ...lab.items[0], value: 9.1 }] });
  active.value = true; await nextTick();
  await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(2));
  expect(JSON.parse(fetchMock.mock.calls[1][1].body).lab_detail.items[0].value).toBe(9.1);
});

it("shows a report received in chat after the lab page was already mounted", async () => {
  const active = ref(false);
  const root = document.createElement("div");
  const app = createApp({ render: () => h(LabPage, { active: active.value }) });
  app.mount(root); dispose = () => app.unmount();
  labReportStore.set({ report_title: "HbA1c 新报告", items: [{ name: "糖化血红蛋白", value: 8.2, unit: "%" }] });
  active.value = true; await nextTick();
  expect(root.textContent).toContain("HbA1c 新报告");
});

it("restores the original lab report sections and renders actual judgments without changing values", async () => {
  const raw = {
    kind: "lab", report_title: "生化检查", confidence: 23.4, abnormal_count: 1,
    sampled_at: "2026-10-28 08:30", reported_at: "2026-10-28 11:20",
    items: [{ name: "血糖", value: 0, unit: "mmol/L", ref: "3.9–6.1", flag: "low" }, { name: "ALT", value: "24", unit: "U/L", ref: "7–40", flag: "normal" }],
    judgments: [{ q: "原始问题", a: "原始回答，不添加新结论", level: "mid" }],
    department: "内分泌科", urgency: "yellow", urgency_label: "黄色", followup: "原始随访建议", advice: ["原始就诊准备"],
  };
  const before = JSON.stringify(raw);
  labReportStore.set(raw);
  const root = document.createElement("div");
  const app = createApp(LabPage, { active: true });
  app.mount(root); dispose = () => app.unmount();
  await nextTick();
  expect(root.querySelectorAll(".l6-strip > .item")).toHaveLength(5);
  expect(root.querySelectorAll(".l6-meta > .item")).toHaveLength(4);
  expect(root.querySelectorAll(".l6-table .cat-head")).toHaveLength(2);
  expect(root.querySelector(".l6-explain .q")?.textContent).toBe("原始问题");
  expect(root.querySelector(".l6-explain .a")?.textContent).toBe("原始回答，不添加新结论");
  expect(root.querySelector(".l6-val.low")?.textContent).toBe("0");
  expect(root.querySelectorAll(".l6-acts button")).toHaveLength(4);
  expect(root.querySelector(".l6-sign")).not.toBeNull();
  expect(root.textContent).toContain("23.4%");
  expect(root.textContent).toContain("原始随访建议");
  expect(JSON.stringify(raw)).toBe(before);
  expect(JSON.stringify(labReportStore.get()?.report)).toBe(before);
});

it("does not save an old account's pending lab upload into the new account", async () => {
  vi.stubGlobal("URL", class extends URL { static createObjectURL() { return "blob:lab-test"; } });
  let finish!: (r: Response) => void;
  vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise<Response>((resolve) => { finish = resolve; })));
  const root = document.createElement("div");
  const app = createApp(LabPage, { active: true });
  app.mount(root);
  const input = root.querySelector<HTMLInputElement>('input[type="file"]')!;
  Object.defineProperty(input, "files", { value: [new File(["test"], "lab.png", { type: "image/png" })] });
  input.dispatchEvent(new Event("change", { bubbles: true }));
  useAuthStore().clear();
  app.unmount();
  useAuthStore().save({ username: "bob", token: "bob-token" });
  finish(new Response(JSON.stringify({ kind: "lab", report_title: "Alice private report", items: [{ name: "HbA1c", value: 8.2 }] })));
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(labReportStore.get()).toBeNull();
});
