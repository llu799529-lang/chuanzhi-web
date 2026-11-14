/**
 * 工作台数据仓储（Pinia）：历史记录 / 用量 / 报告缓存。
 * 与原生版 app.js 的全局状态一对一映射，组件只读这里，避免各自拉接口导致不一致。
 */
import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";
import { api } from "@/lib/api";
import { useAuthStore } from "@/stores/auth";

export type Urgency = "green" | "yellow" | "orange" | "red";

export interface MedRecord {
  id: number;
  input_type: string;
  level: number | null;
  department: string;
  urgency: Urgency;
  summary: string;
  created_at: string;
}

export interface Usage {
  month_used: number;
  month_quota: number;
}

export const URG_TEXT: Record<Urgency, string> = {
  green: "常规",
  yellow: "黄色",
  orange: "橙色",
  red: "红色",
};

export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso.replace(" ", "T"));
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export const useRecordsStore = defineStore("records", () => {
  const auth = useAuthStore();
  const records = ref<MedRecord[]>([]);
  const usage = ref<Usage>({ month_used: 0, month_quota: 200 });
  const loaded = ref(false);
  const loading = ref(false);
  let generation = 0;

  watch(() => auth.token, () => {
    generation++;
    records.value = [];
    usage.value = { month_used: 0, month_quota: 200 };
    loaded.value = false;
    loading.value = false;
  }, { flush: "sync" });

  const eyeRecords = computed(() => records.value.filter((r) => r.input_type.includes("眼底")));
  const labRecords = computed(() => records.value.filter((r) => r.input_type.includes("化验")));
  const symptomRecords = computed(() => records.value.filter((r) => r.input_type.includes("症状")));
  const recheckRecords = computed(() =>
    records.value.filter((r) => r.urgency === "orange" || r.urgency === "red"),
  );

  const usagePct = computed(() => {
    const q = usage.value.month_quota || 200;
    return Math.min(100, Math.round((usage.value.month_used / q) * 1000) / 10);
  });

  async function load(force = false) {
    if (loading.value) return;
    if (loaded.value && !force) return;
    loading.value = true;
    const requestGeneration = generation;
    try {
      const data = await api<{ records: MedRecord[]; usage: Usage }>("/api/records");
      if (requestGeneration !== generation) return;
      records.value = data.records || [];
      if (data.usage) usage.value = data.usage;
      loaded.value = true;
    } finally {
      if (requestGeneration === generation) loading.value = false;
    }
  }

  /** 后端插入新记录后调用：静默刷新，不阻塞当前交互 */
  function refreshSoon() {
    loaded.value = false;
    void load(true).catch(() => undefined);
  }

  return { records, usage, loaded, loading, eyeRecords, labRecords, symptomRecords, recheckRecords, usagePct, load, refreshSoon };
});
