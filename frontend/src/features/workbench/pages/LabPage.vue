<script setup lang="ts">
/**
 * 化验单：上传 → /api/ai/image → 结构化指标表 / AI 解读 / 分诊建议。
 * 版式沿用 app.html 的 l6 报告组件（样式零改动）。
 */
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { useAuthStore } from "@/stores/auth";
import { useRecordsStore } from "@/stores/records";
import { upload as uploadFile } from "@/lib/api";
import { LAB_SAMPLE, loadLabSample } from "@/lib/labDemo";
import { LAB_CATEGORIES, labCategory, labReportStore, type LabReport, type LabMeta } from "@/lib/labReport";
import { reportIcon } from "@/lib/reportIcons";
import { fmtFull } from "@/lib/fundus";
import { useWorkbenchStore, type PageKey } from "@/stores/workbench";

const emit = defineEmits<{ go: [page: PageKey, dept?: string] }>();
const props = defineProps<{ active: boolean }>();
const rec = useRecordsStore();
const auth = useAuthStore();
let alive = true;
onBeforeUnmount(() => { alive = false; });

const busy = ref(false);
const error = ref("");
const report = ref<LabReport | null>(null);
const meta = ref<LabMeta>({});
const docOpen = ref(false);
const copied = ref(false);
const previewUrl = ref("");
const fileEl = ref<HTMLInputElement | null>(null);
const dropEl = ref<HTMLDivElement | null>(null);
const dragOver = ref(false);

const abnormal = computed(() =>
  (report.value?.items ?? []).filter((i) => i.flag === "high" || i.flag === "low"),
);
const count = computed(() => report.value?.items?.length ?? 0);
const checks = computed(() => (report.value?.items ?? []).filter((i) => i.check?.text));
const abnormalCount = computed(() => report.value?.abnormal_count ?? abnormal.value.length);
const urgencyClass = computed(() => ({ green: "good", yellow: "warn", orange: "warn", red: "bad" }[report.value?.urgency ?? ""] ?? ""));
const tagClass = computed(() => ({ green: "green", yellow: "orange", orange: "orange", red: "red" }[report.value?.urgency ?? ""] ?? "orange"));
const groups = computed(() => [...LAB_CATEGORIES.map((c) => c.name), "其他"].map((name) => ({ name, items: (report.value?.items ?? []).filter((it) => labCategory(it.name) === name) })).filter((g) => g.items.length));
const judgments = computed(() => report.value?.judgments?.length ? report.value.judgments.map((j) => ({ q: j.q || ({ high: "重点关注", mid: "需要关注", low: "一般关注" }[j.level ?? ""] ?? "关注"), a: j.a ?? j.text ?? "" })) : (report.value?.explains ?? []).map((j) => ({ q: j.name ?? "关注", a: j.text ?? "" })));
const reportTitle = computed(() => report.value?.report_title || "检验报告");
const analyzedAt = computed(() => report.value?.timestamp || meta.value.analyzedAt);
const sourceLabel = computed(() => meta.value.source === "chat" ? "Agent助手" : "化验单页");
const sourceLine = computed(() => (meta.value.fileName || "化验单") + (meta.value.fileSize ? " · " + fileSize(meta.value.fileSize) : "") + " · 识别时间 " + fmtFull(analyzedAt.value || "") + (meta.value.elapsedMs ? " · 耗时 " + (meta.value.elapsedMs / 1000).toFixed(1) + "s" : "") + " · 来源 " + sourceLabel.value);
function fileSize(n: number): string { return n >= 1048576 ? (n / 1048576).toFixed(1) + "MB" : Math.round(n / 1024) + "KB"; }
const doctorSummary = computed(() => {
  const d = report.value;
  if (!d) return "";
  return ["════════════════════════════════", "  MedTriage · 化验单识别摘要（给医生）", "════════════════════════════════", "", "【基本信息】",
    ...(d.patient?.gender || d.patient?.age != null ? ["- 患者：" + (d.patient.gender || "未识别") + " / " + (d.patient.age ?? "未识别") + " 岁"] : []),
    "- 报告类型：" + reportTitle.value,
    ...(d.sampled_at ? ["- 采样时间：" + d.sampled_at] : []), ...(d.reported_at ? ["- 报告时间：" + d.reported_at] : []),
    ...(d.confidence != null ? ["- OCR 置信度：" + d.confidence + "%"] : []),
    "", "【指标概览】", "- 共识别 " + count.value + " 项，其中 " + abnormalCount.value + " 项异常，" + (count.value - abnormalCount.value) + " 项正常", "", "【异常指标明细】",
    ...(abnormal.value.length ? abnormal.value.map((it) => "- " + it.name + "：" + it.value + (it.unit ? " " + it.unit : "") + "（参考 " + (it.ref || "–") + "）" + (it.flag === "high" ? "↑ 偏高" : "↓ 偏低")) : ["- 未发现异常指标"]),
    ...(checks.value.length ? ["", "【需对照原单核对】", ...checks.value.map((it) => "- " + it.name + "：" + (it.check?.text ?? ""))] : []),
    "", "【AI 通俗解读】", ...(judgments.value.length ? judgments.value.flatMap((j, i) => [(i + 1) + ". 问：" + j.q, "   答：" + j.a]) : ["- 暂无解读"]), "", "【分诊与随访建议】",
    "- 建议科室：" + (d.department || "全科") + "（" + (d.urgency_label || d.urgency || "–") + "）",
    ...(d.followup ? ["- 随访时限：" + d.followup] : []), ...(d.advice ?? []).map((a) => "- " + a), "", "──────────────────────────────",
    "识别时间：" + fmtFull(analyzedAt.value || "") + " · 来自：" + sourceLabel.value,
    "⚠ 以上是 AI 自动识别的参考结果，不是医生诊断，看病请以医生为准。"].join("\n");
});
async function copySummary() {
  try { await navigator.clipboard.writeText(doctorSummary.value); copied.value = true; }
  catch { copied.value = false; }
}
function exportReport() {
  if (!report.value) return;
  const data = { ...report.value, analyzed_at: analyzedAt.value, source: meta.value.source, file_name: meta.value.fileName };
  const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json;charset=utf-8" }));
  const a = document.createElement("a"); a.href = url; a.download = "MedTriage_化验单_" + reportTitle.value.replace(/[\\/:*?"<>|]/g, "_") + ".json";
  a.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * 从 Agent 助手同步过来的报告（旧版 window.MTSyncLabFromChat 的等价实现）。
 * 只在本次还没上传过时接管，避免覆盖用户在当前页刚传的那张。
 */
watch(() => props.active, (active) => {
  if (!active || busy.value) return;
  const saved = labReportStore.get();
  if (!saved || !saved.report?.items?.length) return;
  report.value = saved.report;
  meta.value = saved.meta;
  if (saved.meta.previewUrl) previewUrl.value = saved.meta.previewUrl;
}, { immediate: true });

async function upload(file: File) {
  if (!file || busy.value) return;
  const requestToken = auth.token;
  const started = performance.now();
  busy.value = true;
  error.value = "";
  previewUrl.value = URL.createObjectURL(file);
  try {
    const data = await uploadFile<LabReport>("/api/ai/image", file, "识别失败");
    if (!alive || auth.token !== requestToken) return;
    if (data.kind === "fundus") {
      throw new Error("识别到的是眼底彩照，请到「眼底筛查」上传以获得 DR 分级报告");
    }
    if (data.kind === "other") {
      throw new Error("未能识别为化验单，请上传清晰的检验报告照片");
    }
    report.value = data;
    meta.value = { previewUrl: previewUrl.value, fileName: file.name, fileSize: file.size, source: "lab", analyzedAt: new Date().toISOString(), elapsedMs: performance.now() - started };
    labReportStore.set(data, meta.value);
    rec.refreshSoon();
  } catch (e) {
    error.value = (e as Error).message;
  } finally {
    busy.value = false;
  }
}

const loadingSample = ref(false);

/** 示例化验单：与手动上传走同一个 upload()，只是文件来自 public/samples。 */
async function runLabSample() {
  if (busy.value || loadingSample.value) return;
  loadingSample.value = true;
  error.value = "";
  try {
    const file = await loadLabSample();
    loadingSample.value = false;
    await upload(file);
  } catch (e) {
    error.value = (e as Error).message || "示例化验单加载失败";
  } finally {
    loadingSample.value = false;
  }
}

function onPick(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  if (f) void upload(f);
}

function onDrop(e: DragEvent) {
  dragOver.value = false;
  const f = e.dataTransfer?.files?.[0];
  if (f) void upload(f);
}

// 从工作台 / 使用指南点「用示例化验单体验」进来：直接跑示例（take 语义，只触发一次）
const wbStore = useWorkbenchStore();
watch(
  () => props.active,
  (on) => {
    if (!on || !wbStore.takeDemo("lab")) return;
    report.value = null;
    void runLabSample();
  },
  { immediate: true },
);
</script>

<template>
  <div class="page-t">
    <div><h1 class="engrave">化验单识别报告</h1><p>OCR 结构化 · 全部检验项目 · 异常项标红 · AI 通俗解读</p></div>
    <div class="right">
      <button class="btn-silver" type="button" @click="emit('go', 'history')"><svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 4v4h4"/><path d="M12 7.5v4.8l3 2"/></svg><span>识别历史</span></button>
      <button class="btn-metal" type="button" v-show="report" @click="fileEl?.click()"><svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/></svg><span>上传新化验单</span></button>
    </div>
  </div>
  <input ref="fileEl" type="file" accept="image/*" hidden @change="onPick" />
  <div v-show="!report" class="plate l6-empty">
    <div ref="dropEl" class="drop" :class="{ over: dragOver }" @click="fileEl?.click()" @dragover.prevent="dragOver = true" @dragleave.prevent="dragOver = false" @drop.prevent="onDrop">
      <div class="bigic"><svg viewBox="0 0 24 24"><path d="M14 2.5H7.5a2 2 0 0 0-2 2v15a2 2 0 0 0 2 2h9a2 2 0 0 0 2-2V8z"/><path d="M14 2.5V8h4.5"/><path d="M9 13.5h6M9 17h4"/></svg></div>
      <b>{{ busy ? "正在识别化验单…" : "上传化验单" }}</b><span>JPG / PNG · 支持血常规、生化、甲功、凝血、糖化等</span>
      <div class="fmts"><i>血常规</i><i>生化</i><i>甲功</i><i>凝血</i></div>
    </div>
    <div class="l6-empty-hint">上传化验单照片后，AI 会识别全部指标、标出异常项并给出通俗解读；Agent助手识别的化验单也会自动同步到这里。</div>
  </div>
  <div v-if="error" class="l6-empty-hint" role="alert" style="color:var(--red)">{{ error }}</div>
  <div v-if="!report && !busy" class="eye-demo lab-demo">
    <div class="eye-demo-h">
      <b>没有化验单？用示例试一试</b>
      <span>合成化验单，不含真实患者信息；识别调用在线视觉模型，约需 10～30 秒</span>
    </div>
    <div class="eye-demo-list">
      <button type="button" class="eye-demo-card" :disabled="loadingSample" @click="runLabSample">
        <img class="sq" :src="LAB_SAMPLE.url" :alt="LAB_SAMPLE.title" />
        <span><b>{{ LAB_SAMPLE.title }}</b><em>{{ LAB_SAMPLE.note }}</em></span>
        <i>一键识别 →</i>
      </button>
    </div>
  </div>
  <div v-if="report" class="l6" id="labReport">
    <div class="plate l6-main">
      <div class="l6-head">
        <div class="l6-top">
          <div class="l6-thumb"><img v-if="previewUrl" :src="previewUrl" alt="化验单缩略图"/><div class="badge">识别完成</div></div>
          <div class="l6-hinfo">
            <h2>{{ reportTitle }} · 完整报告</h2>
            <div class="sub"><template v-if="report.sampled_at">{{ reportTitle }} · {{ report.sampled_at }}<br/></template><template v-if="report.patient?.gender || report.patient?.age != null">患者 · {{ report.patient.gender || '–' }} · {{ report.patient.age ?? '–' }} 岁<br/></template>{{ sourceLine }}</div>
            <div class="tags"><i class="green">识别完成</i><i v-if="report.confidence != null">OCR 置信度 {{ report.confidence }}%</i><i v-else>大模型视觉</i><i :class="abnormalCount ? tagClass : 'green'">{{ abnormalCount ? abnormalCount + ' 项异常' : '未见异常' }}</i><i>{{ count }} 项指标</i><i :class="tagClass">{{ report.urgency_label || report.urgency || '–' }}</i></div>
          </div>
          <div class="l6-badge"><div class="lbl">异常项</div><div class="v" :class="abnormalCount ? (report.urgency === 'red' ? 'bad' : 'warn') : ''">{{ abnormalCount }}</div><div class="s">共 {{ count }} 项</div></div>
        </div>
        <div class="l6-meta">
          <div class="item"><div class="k">报告类型</div><div class="v">{{ reportTitle }}</div></div>
          <div class="item"><div class="k">识别方式</div><div class="v">大模型 · OCR</div></div>
          <div class="item"><div class="k">{{ report.sampled_at ? '采样时间' : '识别时间' }}</div><div class="v">{{ report.sampled_at || fmtFull(analyzedAt || '') }}</div></div>
          <div class="item"><div class="k">{{ report.reported_at ? '报告时间' : '涉及分类' }}</div><div class="v">{{ report.reported_at || groups.length + ' 类' }}</div></div>
        </div>
      </div>
      <div class="l6-body">
        <div class="l6-strip">
          <div class="item"><div class="v">{{ count }}</div><div class="k">识别指标</div></div>
          <div class="item"><div class="v" :class="abnormalCount ? 'warn' : ''">{{ abnormalCount }}</div><div class="k">异常项</div></div>
          <div class="item"><div class="v">{{ count - abnormalCount }}</div><div class="k">正常项</div></div>
          <div class="item"><div class="v hl">{{ report.confidence != null ? report.confidence + '%' : '–' }}</div><div class="k">{{ report.confidence != null ? 'OCR 置信度' : '识别引擎' }}</div></div>
          <div class="item"><div class="v">{{ groups.length }}</div><div class="k">涉及分类</div></div>
        </div>
        <div class="l6-sec">
          <div class="h">结构化指标 <span class="sub">{{ count }} 项 · {{ abnormalCount }} 项异常</span></div>
          <div v-if="checks.length" class="l6-chk-banner">⚠ 有 {{ checks.length }} 项识别结果与单位、参考范围或人体可能范围对不上，已标黄：请对照化验单原件核对这些数字，确认前不要据此调整用药。</div>
          <table class="l6-table"><thead><tr><th>指标</th><th>结果</th><th>参考范围</th><th>状态</th></tr></thead><tbody>
            <template v-for="group in groups" :key="group.name">
              <tr class="cat-head"><td colspan="4">{{ group.name }}</td></tr>
              <template v-for="(it, i) in group.items" :key="`${group.name}-${i}`"><tr :class="{ abn: it.flag === 'high' || it.flag === 'low', chk: !!it.check }">
                <td>{{ it.name }}</td><td><span class="l6-val" :class="it.flag">{{ it.value }}</span><span v-if="it.unit" class="l6-unit">{{ it.unit }}</span></td>
                <td><span v-if="it.ref" class="l6-ref">{{ it.ref }}</span><template v-else>–</template></td>
                <td><span class="l6-tag" :class="it.flag">{{ it.flag === 'high' ? '↑ 偏高' : it.flag === 'low' ? '↓ 偏低' : '正常' }}</span><span v-if="it.check" class="l6-tag chk" :title="it.check.text">请核对</span></td>
              </tr><tr v-if="it.check" class="l6-chk-row"><td colspan="4">⚠ {{ it.check.text }}</td></tr></template>
            </template>
            <tr v-if="!count"><td colspan="4" style="text-align:center;padding:24px;color:var(--faint)">未识别到指标</td></tr>
          </tbody></table>
        </div>
        <div class="l6-sec" v-if="judgments.length"><div class="h">AI 通俗解读 <span class="sub">按重要性排序</span></div><div><div v-for="(j, i) in judgments" :key="i" class="l6-explain"><div class="q">{{ j.q }}</div><div class="a">{{ j.a }}</div></div></div></div>
        <div class="l6-sec"><div class="h">分诊与随访建议</div><ul class="l6-adv"><li><strong>建议科室：</strong>{{ report.department || '全科' }}（{{ report.urgency_label || report.urgency || '–' }}）</li><li v-if="report.followup"><strong>随访节奏：</strong>{{ report.followup }}</li><li v-for="(a, i) in report.advice" :key="i">{{ a }}</li></ul></div>
        <div class="l6-sign"><div class="item">报告类型<b>{{ reportTitle }}</b></div><div class="item">识别方式<b>大模型视觉</b></div><div class="item">识别时间<b>{{ fmtFull(analyzedAt || '') }}</b></div></div>
        <div class="l6-warn">⚠ 本报告仅为筛查参考，<strong>不是诊断</strong>，不构成治疗建议，需医生确认。</div>
      </div>
    </div>
    <div class="l6-side">
      <div class="plate l6-card"><div class="ttl">原图预览</div><div class="l6-preview"><img v-if="previewUrl" :src="previewUrl" alt="化验单原图"/><span class="p-stamp">识别完成</span></div></div>
      <div class="plate l6-card"><div class="ttl">关键指标</div><div>
        <div class="l6-row"><span class="k">识别指标</span><span class="v">{{ count }} 项</span></div>
        <div class="l6-row"><span class="k">异常项</span><span class="v" :class="urgencyClass">{{ abnormalCount }} 项</span></div>
        <div class="l6-row"><span class="k">正常项</span><span class="v">{{ count - abnormalCount }} 项</span></div>
        <div class="l6-row" v-if="report.confidence != null"><span class="k">OCR 置信度</span><span class="v hl">{{ report.confidence }}%</span></div>
        <div class="l6-row"><span class="k">报告类型</span><span class="v">{{ reportTitle }}</span></div>
        <div class="l6-row"><span class="k">建议科室</span><span class="v">{{ report.department || '全科' }}</span></div>
        <div class="l6-row"><span class="k">紧急程度</span><span class="v" :class="urgencyClass">{{ report.urgency_label || report.urgency || '–' }}</span></div>
      </div></div>
      <div class="plate l6-card" v-if="abnormal.length"><div class="ttl">异常项摘要</div><div><div v-for="(it, i) in abnormal" :key="i" class="l6-row"><span class="k">{{ it.name }}</span><span class="v" :class="it.flag === 'high' ? 'warn' : ''">{{ it.value }}{{ it.unit ? ' ' + it.unit : '' }}{{ it.flag === 'high' ? ' ↑' : ' ↓' }}</span></div></div></div>
      <div class="plate l6-card l6-acts-card"><div class="ttl">操作</div><div class="l6-acts">
        <button class="r6-btn primary" type="button" @click="exportReport"><span style="display:contents" v-html="reportIcon('pdf', 'lab')"></span>导出结构化结果</button>
        <button class="r6-btn" type="button" @click="docOpen = true; copied = false"><span style="display:contents" v-html="reportIcon('doc', 'lab')"></span>生成给医生的摘要</button>
        <button class="r6-btn" type="button" @click="emit('go', 'hospital', report.department || '')"><span style="display:contents" v-html="reportIcon('pin', 'lab')"></span>查找附近{{ report.department || '全科' }}</button>
        <button class="r6-btn" type="button" @click="emit('go', 'history')"><span style="display:contents" v-html="reportIcon('doc', 'lab-history')"></span>查看历史化验</button>
      </div></div>
    </div>
  </div>
  <div v-if="docOpen" class="r6-modal" role="dialog" aria-modal="true" aria-label="化验单给医生的摘要" @keydown.esc="docOpen = false"><div class="r6-modal-mask" @click="docOpen = false"></div><div class="r6-modal-body r6-doc-modal"><div class="r6-modal-head"><b>给医生的摘要</b><span>可直接复制发给接诊医生</span><button type="button" aria-label="关闭化验摘要" @click="docOpen = false">✕</button></div><div class="r6-doc-body">{{ doctorSummary }}</div><div class="r6-doc-foot"><span class="r6-doc-hint">{{ copied ? '已复制到剪贴板' : '数据来自本次 AI 识别（' + sourceLabel + '）· 可直接复制' }}</span><button class="r6-btn primary" type="button" @click="copySummary">复制摘要</button></div></div></div>
</template>
