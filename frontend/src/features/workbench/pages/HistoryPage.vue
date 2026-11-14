<script setup lang="ts">
/** 历史记录：真实 /api/records，按类型筛选（替代原版静态占位） */
import { computed, ref } from "vue";
import { svg, esc } from "@/lib/icons";
import { useRecordsStore, fmtTime, URG_TEXT, type MedRecord } from "@/stores/records";
import type { PageKey } from "@/stores/workbench";

const emit = defineEmits<{ go: [page: PageKey] }>();
const rec = useRecordsStore();

type Tab = "all" | "eye" | "lab" | "symptom" | "recheck";
const tab = ref<Tab>("all");

const tabs = computed(() => [
  { key: "all" as Tab, label: `全部 · ${rec.records.length}` },
  { key: "eye" as Tab, label: `眼底筛查 · ${rec.eyeRecords.length}` },
  { key: "lab" as Tab, label: `化验单 · ${rec.labRecords.length}` },
  { key: "symptom" as Tab, label: `症状分诊 · ${rec.symptomRecords.length}` },
  { key: "recheck" as Tab, label: `需复查 · ${rec.recheckRecords.length}` },
]);

const rows = computed<MedRecord[]>(() => {
  switch (tab.value) {
    case "eye":
      return rec.eyeRecords;
    case "lab":
      return rec.labRecords;
    case "symptom":
      return rec.symptomRecords;
    case "recheck":
      return rec.recheckRecords;
    default:
      return rec.records;
  }
});

function rowHtml(r: MedRecord): string {
  return (
    '<div class="hist-row">' +
    `<div class="c1"><div class="fic">${svg("eye")}</div>` +
    `<div class="m"><b>${esc(r.input_type)}筛查记录</b>` +
    `<span>ID · MT-${String(r.id).padStart(4, "0")}</span></div></div>` +
    `<div class="c">${esc(r.input_type)}</div>` +
    `<div class="c">${esc(r.department)}</div>` +
    `<div class="c res"><span class="gem ${r.urgency || "green"}"></span>` +
    `${r.level != null ? `${r.level} 级` : esc(URG_TEXT[r.urgency] ?? "–")}</div>` +
    `<div class="c">${esc(fmtTime(r.created_at))}</div></div>`
  );
}

const rowsHtml = computed(() =>
  rows.value.length
    ? rows.value.map(rowHtml).join("")
    : '<div class="hist-row"><div class="c" style="grid-column:1/-1;text-align:center;padding:34px 0;color:var(--faint);font-size:12.5px;">暂无历史记录</div></div>',
);
</script>

<template>
  <div class="page-t">
    <div>
      <h1 class="engrave">历史记录</h1>
      <p>全部筛查与分诊记录，按时间倒序</p>
    </div>
  </div>
  <div class="hist-tabs">
    <button
      v-for="t in tabs"
      :key="t.key"
      class="hist-tab"
      :class="{ on: tab === t.key }"
      @click="tab = t.key"
    >
      {{ t.label }}
    </button>
  </div>
  <div class="hist-table">
    <div class="hist-row head">
      <div>记录</div><div>类型</div><div>科室</div><div>紧急程度</div><div>时间</div>
    </div>
    <div v-html="rowsHtml"></div>
  </div>
</template>
