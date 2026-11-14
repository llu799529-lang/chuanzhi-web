<script setup lang="ts">
/**
 * 眼底筛查：上传 → EfficientNet-B3 / 大模型 → DR 分级 + 病灶明细 + Grad-CAM 热力图。
 * 版式沿用 app.html 的 r6 报告组件；三个数据来源（本页 / Agent助手 / 本地缓存）共用同一视图模型。
 *
 * 三种视图：上传（单眼 / 双眼）· 单眼报告 · 双眼结论（点某只眼进入它的完整报告）。
 * 报告里的「专业阅片」（增强 / 无赤光 / 热力图叠加 / 并排对照 / 放大镜）在 components/FundusViewer.vue。
 */
import { computed, onMounted, ref, watch } from "vue";
import FundusViewer from "@/features/workbench/components/FundusViewer.vue";
import { useRecordsStore } from "@/stores/records";
import { ApiError, upload } from "@/lib/api";
import { FUNDUS_SAMPLES, PIPELINE_STEPS, loadSample, pipelineStage, stepState, type FundusSample } from "@/lib/fundusDemo";
import { EYE_CN, EYE_CODE, SIDES, combineEyes, isGradable, pairSummary, type EyeSide } from "@/lib/bilateral";
import { recordRowHtml } from "@/lib/recordRow";
import { reportIcon } from "@/lib/reportIcons";
import {
  DR_LONG,
  fundusPairStore,
  fundusStore,
  makeThumb,
  makeView,
  normalizeFundus,
  fmtFull,
  fmtSize,
  daysBetween,
  localNow,
  type FundusPair,
  type FundusReport,
  type RawFundus,
} from "@/lib/fundus";
import { useWorkbenchStore, type PageKey } from "@/stores/workbench";

const props = defineProps<{ active: boolean }>();
const emit = defineEmits<{ go: [page: PageKey, dept?: string] }>();
const rec = useRecordsStore();
const wb = useWorkbenchStore();

const report = ref<FundusReport | null>(null);
const pair = ref<FundusPair | null>(null); // 双眼结论：两份单眼报告
const viewEye = ref<EyeSide | null>(null); // 从双眼结论点进了哪只眼的完整报告
const mode = ref<"single" | "pair">("single");
const pairFiles = ref<Record<EyeSide, File | null>>({ right: null, left: null });
const pairPreview = ref<Record<EyeSide, string>>({ right: "", left: "" });
const pairStep = ref<EyeSide | null>(null); // 双眼分析进行到哪只眼
const pairOver = ref<EyeSide | null>(null);
const pickSide = ref<EyeSide>("right");
const busy = ref(false);
const dragOver = ref(false);
const preview = ref<string | null>(null); // 上传演示：分析期间显示所选图片
const stage = ref(0); // 当前处理步骤，见 lib/fundusDemo
const loadingSample = ref(false);
const error = ref("");
const fileEl = ref<HTMLInputElement | null>(null);
const pairEl = ref<HTMLInputElement | null>(null);
const viewerOpen = ref(false);
const viewerHeat = ref(false);
const docOpen = ref(false);
const docCopied = ref(false);
const pairCopied = ref(false);

/**
 * 恢复本账号最新的结果。单眼报告与双眼结论只保留最新的一种；
 * 在 Agent 助手里新分析了眼底图时，存储里的单眼报告比页面上显示的新，切回本页要换成它。
 */
function restore() {
  const saved = fundusStore.get();
  if (saved && saved.analyzedAt !== report.value?.analyzedAt) {
    report.value = saved;
    pair.value = null;
    viewEye.value = null;
    return;
  }
  if (!report.value && !pair.value) pair.value = fundusPairStore.get();
}
onMounted(restore);

const LES_COLORS = ["#FF9F0A", "#FF453A", "#FFD60A", "#8CC6FF"];
const totalCount = computed(() => {
  let total = 0;
  let has = false;
  for (const l of report.value?.lesions ?? []) {
    if (l.count) {
      total += l.count;
      has = true;
    }
  }
  return { total, has };
});
const lesionSub = computed(() => {
  if (!report.value) return "";
  return totalCount.value.has ? `共 ${totalCount.value.total} 处` : `共 ${report.value.lesions.length} 类征象`;
});
/** 历史对比：双眼筛查只和同一只眼的上次结果比；单眼报告跳过同一次双眼筛查里的另一只眼 */
const prevRecord = computed(() => {
  const r = report.value;
  if (!r) return null;
  const cur = String(r.analyzedAt).replace("T", " ");
  const curMs = Date.parse(cur.replace(" ", "T"));
  const tag = r.eye ? `${EYE_CN[r.eye]} · ` : "";
  return (
    rec.eyeRecords.find((x) => {
      const t = String(x.created_at).replace("T", " ");
      if (x.level == null || !(t < cur)) return false;
      const sum = x.summary || "";
      if (tag) return sum.startsWith(tag);
      const near = curMs - Date.parse(t.replace(" ", "T")) < 120_000;
      return !(near && /^(右眼|左眼) · /.test(sum));
    }) ?? null
  );
});
const compare = computed(() => {
  const p = prevRecord.value;
  if (!p || !report.value || p.level == null) {
    return { last: "首次记录", lastLevel: "–", delta: "–", days: "–", cls: "" };
  }
  const delta = report.value.level - p.level;
  const days = daysBetween(p.created_at, report.value.analyzedAt);
  return {
    last: fmtFull(p.created_at).slice(0, 10),
    lastLevel: `DR ${p.level} 级`,
    delta: `${delta > 0 ? "+" : ""}${delta} 级`,
    days: days == null ? "–" : `${days} 天`,
    cls: delta > 0 ? "bad" : delta < 0 ? "good" : "",
  };
});
const urgencyCls = computed(
  () => ({ green: "good", yellow: "warn", orange: "warn", red: "bad" })[report.value?.urgency ?? ""] ?? "",
);
const lesionUrgencyCls = computed(() => {
  const r = report.value;
  if (!r || !r.lesions.length) return "good";
  return r.level >= 2 ? "warn" : "";
});
const QUALITY_CLS: Record<string, string> = { 可评估: "good", 质量偏低: "warn", 不可评估: "bad" };
const qualityCls = computed(() => QUALITY_CLS[report.value?.quality ?? ""] ?? "");
const qualityWhy = computed(() => {
  const why = report.value?.qualityReasons ?? [];
  return why.length ? `（${why.join("、")}）` : "";
});

function fmtConf(c: number | null): string {
  return c == null ? "–" : `${c.toFixed(1)}%`;
}

function readDataUrl(file: File): Promise<string | null> {
  return new Promise((resolve) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result));
    fr.onerror = () => resolve(null);
    fr.readAsDataURL(file);
  });
}

/** 上传一张：先显示所选图片，按服务端处理顺序推进步骤；最后一步等真实响应返回才完成 */
async function runPipeline(file: File, eye: EyeSide | null): Promise<FundusReport> {
  const dataUrl = await readDataUrl(file);
  preview.value = dataUrl;
  const t0 = Date.now();
  stage.value = pipelineStage(0, false);
  const timer = window.setInterval(() => (stage.value = pipelineStage(Date.now() - t0, false)), 200);
  const path = "/api/fundus/analyze" + (eye ? `?eye=${eye}` : "");
  try {
    let raw: RawFundus;
    try {
      raw = await upload<RawFundus>(path, file, "分析失败");
    } catch (e) {
      // 双眼连续上传可能碰上「同一接口最短间隔」限流：按服务器给的秒数等一下，再试一次
      if (!(e instanceof ApiError) || !e.isRateLimited || (e.retryAfter ?? 0) > 10) throw e;
      await new Promise((r) => setTimeout(r, ((e.retryAfter ?? 2) + 0.3) * 1000));
      raw = await upload<RawFundus>(path, file, "分析失败");
    }
    stage.value = pipelineStage(Date.now() - t0, true);
    const [thumb, view] = await Promise.all([makeThumb(dataUrl ?? ""), makeView(dataUrl ?? "")]);
    return normalizeFundus(raw, "eye", {
      thumbnail: thumb.url,
      viewImage: view.url,
      fileName: file.name,
      fileSize: file.size,
      fileDim: thumb.dim,
      elapsedMs: Date.now() - t0,
    });
  } finally {
    window.clearInterval(timer);
    preview.value = null;
  }
}

async function analyze(file: File) {
  if (!file || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const r = await runPipeline(file, null);
    report.value = r;
    pair.value = null;
    viewEye.value = null;
    fundusStore.set(r);
    fundusPairStore.set(null);
    rec.refreshSoon();
  } catch (e) {
    error.value = (e as Error).message || "分析失败，请重试";
  } finally {
    busy.value = false;
  }
}

/** 双眼联合筛查：右眼、左眼依次分级（同一接口、同一模型），完成后合成患者层面的结论 */
async function analyzePair() {
  const files = pairFiles.value;
  if (!files.right || !files.left || busy.value) return;
  busy.value = true;
  error.value = "";
  const done: Partial<Record<EyeSide, FundusReport>> = {};
  try {
    for (const side of SIDES) {
      pairStep.value = side;
      done[side] = await runPipeline(files[side] as File, side);
    }
    const result: FundusPair = { right: done.right as FundusReport, left: done.left as FundusReport };
    pair.value = result;
    report.value = null;
    viewEye.value = null;
    fundusPairStore.set(result);
    fundusStore.set(null);
    clearPairInputs();
    rec.refreshSoon();
  } catch (e) {
    const side = pairStep.value;
    error.value = `${side ? EYE_CN[side] : ""}分析失败：${(e as Error).message || "请重试"}`;
  } finally {
    busy.value = false;
    pairStep.value = null;
  }
}

function clearPairInputs() {
  pairFiles.value = { right: null, left: null };
  pairPreview.value = { right: "", left: "" };
}
async function setPairFile(side: EyeSide, f: File | null | undefined) {
  if (!f) return;
  if (f.type && !f.type.startsWith("image/")) {
    error.value = "请选择 JPG / PNG 格式的眼底彩照";
    return;
  }
  error.value = "";
  pairFiles.value = { ...pairFiles.value, [side]: f };
  const thumb = await makeThumb((await readDataUrl(f)) ?? "");
  pairPreview.value = { ...pairPreview.value, [side]: thumb.url ?? "" };
}
function pickPair(side: EyeSide) {
  pickSide.value = side;
  pairEl.value?.click();
}
function onPairPick(e: Event) {
  const input = e.target as HTMLInputElement;
  void setPairFile(pickSide.value, input.files?.[0]);
  input.value = "";
}
function onPairDrop(side: EyeSide, e: DragEvent) {
  pairOver.value = null;
  void setPairFile(side, e.dataTransfer?.files?.[0]);
}

/** 内置示例图：与手动上传走同一个流程，只是文件来自 public/samples。 */
async function runSample(s: FundusSample) {
  if (busy.value || loadingSample.value) return;
  newScan();
  mode.value = "single";
  loadingSample.value = true;
  try {
    const file = await loadSample(s);
    loadingSample.value = false;
    await analyze(file);
  } catch (e) {
    error.value = (e as Error).message || "示例图加载失败";
  } finally {
    loadingSample.value = false;
  }
}
/** 双眼示例：示例 A 放右眼、示例 B（同一张图人为失焦）放左眼，演示「一只眼不可评估」时怎么给结论 */
async function runPairDemo() {
  if (busy.value || loadingSample.value) return;
  newScan();
  mode.value = "pair";
  loadingSample.value = true;
  try {
    const [a, b] = await Promise.all([loadSample(FUNDUS_SAMPLES[0]), loadSample(FUNDUS_SAMPLES[1])]);
    await Promise.all([setPairFile("right", a), setPairFile("left", b)]);
    loadingSample.value = false;
    await analyzePair();
  } catch (e) {
    error.value = (e as Error).message || "示例图加载失败";
  } finally {
    loadingSample.value = false;
  }
}
function onPick(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  if (f) void analyze(f);
  (e.target as HTMLInputElement).value = "";
}
function onDrop(e: DragEvent) {
  dragOver.value = false;
  const f = e.dataTransfer?.files?.[0];
  if (f) void analyze(f);
}
function newScan() {
  report.value = null;
  pair.value = null;
  viewEye.value = null;
  viewerOpen.value = false;
  fundusStore.set(null);
  fundusPairStore.set(null);
  clearPairInputs();
  error.value = "";
}
/** 报告页右上角「上传演示」：用示例 A 把上传 → 分析的全过程再走一遍（评审建议的上传演示） */
function replayDemo() {
  void runSample(FUNDUS_SAMPLES[0]);
}

const bi = computed(() => (pair.value ? combineEyes(pair.value.right, pair.value.left) : null));
const pairEyes = computed(() => {
  const p = pair.value;
  return p ? SIDES.map((side) => ({ side, r: p[side], ok: isGradable(p[side]) })) : [];
});
function openEye(side: EyeSide) {
  if (!pair.value) return;
  report.value = pair.value[side];
  viewEye.value = side;
  error.value = "";
}
function backToPair() {
  report.value = null;
  viewEye.value = null;
  viewerOpen.value = false;
  error.value = "";
}
async function copyPair() {
  const p = pair.value;
  if (!p) return;
  try {
    await navigator.clipboard.writeText(pairSummary(p.right, p.left));
    pairCopied.value = true;
  } catch {
    error.value = "复制失败，请手动选中文字";
  }
}

function openViewer(heat: boolean) {
  if (!report.value) return;
  viewerHeat.value = heat;
  viewerOpen.value = true;
}
function openHeat() {
  if (!report.value?.heatmap) {
    error.value = "本次报告没有热力图（演示模式或模型未返回），可以在「专业阅片」里查看增强与无赤光视图。";
    return;
  }
  openViewer(true);
}
function openDoc() {
  docCopied.value = false;
  docOpen.value = true;
}
async function copyDoc() {
  const text = report.value?.doctorSummary ?? "";
  try {
    await navigator.clipboard.writeText(text);
    docCopied.value = true;
  } catch {
    error.value = "复制失败，请手动选中摘要文字";
  }
}
/** 报告标题去掉扩展名 */
const titleName = computed(() => (report.value?.fileName ?? "眼底彩照").replace(/\.[^.]+$/, ""));
const viewerTitle = computed(() => {
  const r = report.value;
  if (!r) return "";
  return [r.eye ? `${EYE_CN[r.eye]}（${EYE_CODE[r.eye]}）` : "", `DR ${r.level} 级`, r.fileName].filter(Boolean).join(" · ");
});
/** 历史列表（空状态里的筛查历史） */
const historyHtml = computed(() =>
  rec.records.length
    ? rec.records.slice(0, 6).map(recordRowHtml).join("")
    : '<div class="rec-empty">暂无记录——完成首次筛查后<br>可在此回看分级与分诊结果</div>',
);

/** 导出 PDF：沿用原版的打印样式（body.mt-print 只保留眼底报告页） */
function printReport() {
  document.body.classList.add("mt-print");
  const done = () => {
    document.body.classList.remove("mt-print");
    window.removeEventListener("afterprint", done);
  };
  window.addEventListener("afterprint", done);
  window.print();
  setTimeout(done, 1500);
}

// 页面切到前台：工作台 / 使用指南的示例请求优先；否则恢复本账号上次的结果并刷新记录
watch(
  () => props.active,
  (on) => {
    if (!on) return;
    if (wb.takeDemo()) {
      void runSample(FUNDUS_SAMPLES[0]);
      return;
    }
    const dropped = wb.take("eye", "file")?.file;
    if (dropped) {
      // 工作台上传框里拖进来的照片：直接按单眼分析
      newScan();
      mode.value = "single";
      void analyze(dropped);
      return;
    }
    if (wb.take("eye", "pair")) {
      void runPairDemo();
      return;
    }
    if (wb.take("eye", "fresh")) {
      // 使用指南「上传我的眼底照片」：显示上传框（上一次的结果仍保存在本账号里，下次进入照常恢复）
      report.value = null;
      pair.value = null;
      viewEye.value = null;
      error.value = "";
      return;
    }
    restore();
    void rec.load().catch(() => undefined);
  },
  { immediate: true },
);
</script>

<template>
  <div class="page-t">
    <div>
      <h1 class="engrave">眼底筛查</h1>
      <p>完整分析报告 · 含分级依据、病灶明细、分诊建议；支持双眼筛查与专业阅片</p>
    </div>
    <div v-show="report || pair" class="eye-head-acts">
      <button v-if="viewEye" class="btn-silver" type="button" @click="backToPair">
        <svg viewBox="0 0 24 24"><path d="M15 5l-7 7 7 7" /></svg>
        <span>返回双眼结论</span>
      </button>
      <button class="btn-silver" type="button" :disabled="busy" title="用示例 A 把上传与分析流程重新演示一遍" @click="replayDemo">
        <svg viewBox="0 0 24 24"><path d="M8 5.5v13l10.5-6.5z" /></svg>
        <span>上传演示</span>
      </button>
      <button class="btn-silver" type="button" @click="newScan">
        <svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>
        <span>新筛查</span>
      </button>
    </div>
  </div>

  <input ref="fileEl" type="file" accept="image/*" hidden @change="onPick" />
  <input ref="pairEl" type="file" accept="image/*" hidden @change="onPairPick" />

  <!-- 空状态：单眼 / 双眼上传 + 示例 + 筛查历史 -->
  <div v-show="!report && !pair" class="plate r6-empty">
    <div class="eye-mode" role="tablist" aria-label="筛查方式">
      <button type="button" role="tab" :aria-selected="mode === 'single'" :class="{ on: mode === 'single' }" :disabled="busy" @click="mode = 'single'">
        <b>单眼筛查</b><span>上传一张眼底彩照</span>
      </button>
      <button type="button" role="tab" :aria-selected="mode === 'pair'" :class="{ on: mode === 'pair' }" :disabled="busy" @click="mode = 'pair'">
        <b>双眼筛查</b><span>左右眼各一张，按较重的一只眼给建议</span>
      </button>
    </div>

    <div v-if="busy" class="eye-run" role="status" aria-live="polite">
      <div class="eye-run-img">
        <img v-if="preview" :src="preview" alt="正在分析的眼底彩照" />
        <i class="eye-run-scan" aria-hidden="true"></i>
        <span v-if="pairStep" class="eye-run-eye">{{ EYE_CN[pairStep] }} {{ EYE_CODE[pairStep] }}</span>
      </div>
      <ol class="eye-run-steps">
        <li v-for="(s, i) in PIPELINE_STEPS" :key="s.t" :class="stepState(i, stage)">
          <span class="ck">{{ stepState(i, stage) === "done" ? "✓" : i + 1 }}</span><b>{{ s.t }}</b><em>{{ s.d }}</em>
        </li>
      </ol>
      <div class="eye-run-note">
        <template v-if="pairStep">正在分析{{ EYE_CN[pairStep] }}（{{ pairStep === "right" ? 1 : 2 }} / 2）。</template>步骤按服务端实际处理顺序展示，结果返回后才标记完成；实际耗时见报告中的「耗时」。
      </div>
    </div>
    <div
      v-else-if="mode === 'single'"
      class="drop"
      :class="{ over: dragOver }"
      @click="fileEl?.click()"
      @dragover.prevent="dragOver = true"
      @dragleave.prevent="dragOver = false"
      @drop.prevent="onDrop"
    >
      <div class="bigic">
        <svg viewBox="0 0 24 24"><path d="M2.5 12S5.8 5.5 12 5.5 21.5 12 21.5 12 18.2 18.5 12 18.5 2.5 12 2.5 12z" /><circle cx="12" cy="12" r="3" /></svg>
      </div>
      <b>上传眼底彩照</b>
      <span>JPG / PNG · 建议免散瞳眼底彩照 · ≤ 20MB</span>
      <div class="fmts"><i>JPG</i><i>PNG</i></div>
    </div>
    <div v-else class="eye-pair">
      <div class="eye-pair-slots">
        <div
          v-for="side in SIDES"
          :key="side"
          class="eye-slot"
          :class="{ over: pairOver === side, has: !!pairFiles[side] }"
          role="button"
          tabindex="0"
          :aria-label="`选择${EYE_CN[side]}眼底彩照`"
          @click="pickPair(side)"
          @keydown.enter.prevent="pickPair(side)"
          @dragover.prevent="pairOver = side"
          @dragleave.prevent="pairOver = null"
          @drop.prevent="onPairDrop(side, $event)"
        >
          <div class="eye-slot-h"><b>{{ EYE_CN[side] }}</b><span>{{ EYE_CODE[side] }}</span></div>
          <img v-if="pairPreview[side]" :src="pairPreview[side]" :alt="`${EYE_CN[side]}眼底彩照`" />
          <div v-else class="eye-slot-empty">
            <svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14" /></svg>
            <span>点击或拖入{{ EYE_CN[side] }}照片</span>
          </div>
          <em>{{ pairFiles[side]?.name || "JPG / PNG · ≤ 20MB" }}</em>
        </div>
      </div>
      <button type="button" class="eye-pair-go" :disabled="!pairFiles.right || !pairFiles.left" @click="analyzePair">
        {{ pairFiles.right && pairFiles.left ? "开始双眼筛查" : `还差${pairFiles.right ? "左眼" : "右眼"}照片` }}
      </button>
      <p class="eye-pair-tip">
        两张照片依次用本机模型分级，完成后按较重的一只眼给出复查与转诊建议；照片不可评估的眼会单独提示重拍，不会当成正常。
      </p>
    </div>

    <div class="r6-empty-hint">
      报告生成后会以标准筛查报告版式呈现；在Agent助手上传眼底图完成的分析，也会自动同步到这里。
    </div>
    <div v-if="error" class="r6-empty-hint" style="color: var(--red)">{{ error }}</div>

    <div v-show="!busy" class="eye-demo">
      <div class="eye-demo-h">
        <b>没有眼底照片？用示例图体验完整流程</b>
        <span>示例图与自行上传走同一接口：校验 → 质量评估 → 本地模型分级 → Grad-CAM → 分诊报告</span>
      </div>
      <div class="eye-demo-list">
        <button
          v-for="s in FUNDUS_SAMPLES"
          :key="s.id"
          type="button"
          class="eye-demo-card"
          :disabled="loadingSample"
          @click="runSample(s)"
        >
          <img :src="s.url" :alt="s.title" />
          <span><b>{{ s.title }}</b><em>{{ s.note }}</em></span>
          <i>一键分析 →</i>
        </button>
        <button type="button" class="eye-demo-card pair" :disabled="loadingSample" @click="runPairDemo">
          <span class="eye-demo-pair"><img :src="FUNDUS_SAMPLES[0].url" alt="" /><img :src="FUNDUS_SAMPLES[1].url" alt="" /></span>
          <span><b>双眼示例</b><em>示例 A 放右眼、示例 B（失焦）放左眼，演示一只眼不可评估时怎么给结论</em></span>
          <i>一键分析 →</i>
        </button>
      </div>
    </div>

    <div class="sec-h" style="margin-top: 22px">
      <h3>筛查历史</h3>
      <a style="cursor: pointer" @click="emit('go', 'history')">全部 →</a>
    </div>
    <div class="reclist" v-html="historyHtml"></div>
  </div>

  <!-- 双眼结论 -->
  <div v-if="pair && !report && bi" class="eye-bi">
    <div class="plate eye-bi-main">
      <div class="eye-bi-top">
        <div>
          <div class="lbl">双眼筛查结论</div>
          <h2>{{ bi.headline }}</h2>
        </div>
        <span class="eye-bi-urg" :class="bi.urgency">{{ bi.urgencyLabel }}</span>
      </div>
      <ul class="r6-adv">
        <li><strong>建议科室：</strong>{{ bi.department }}</li>
        <li v-if="bi.advice"><strong>复查 / 就诊：</strong>{{ bi.advice }}</li>
        <li v-for="(n, i) in bi.notes" :key="i" class="warn">{{ n }}</li>
      </ul>
      <div class="eye-bi-rule">
        判断规则：按两眼中较重的一只眼给出转诊与复查建议（糖网筛查的通行做法）；照片不可评估的眼不参与分级，需要重拍或到眼科检查。本结论仅为筛查参考，不是诊断。
      </div>
      <div v-if="error" class="r6-err">{{ error }}</div>
      <div class="eye-bi-acts">
        <button class="r6-btn primary" type="button" @click="emit('go', 'hospital', bi.department)">
          <span style="display: contents" v-html="reportIcon('pin', 'eye')"></span>查找附近{{ bi.department }}
        </button>
        <button class="r6-btn" type="button" @click="copyPair">
          <span style="display: contents" v-html="reportIcon('doc', 'eye')"></span>{{ pairCopied ? "已复制双眼摘要" : "复制给医生的双眼摘要" }}
        </button>
      </div>
    </div>
    <div class="eye-bi-eyes">
      <div v-for="e in pairEyes" :key="e.side" class="plate eye-bi-eye" :class="{ worse: bi.worse === e.side, bad: !e.ok }">
        <div class="eye-bi-eh">
          <b>{{ EYE_CN[e.side] }}</b><span>{{ EYE_CODE[e.side] }}</span>
          <em v-if="bi.worse === e.side">决定结论</em>
          <em v-else-if="!e.ok" class="bad">需要重拍</em>
        </div>
        <img v-if="e.r.thumbnail" :src="e.r.thumbnail" :alt="`${EYE_CN[e.side]}眼底彩照`" />
        <div class="eye-bi-grade">{{ e.ok ? `DR ${e.r.level} 级` : "不可评估" }}</div>
        <div class="eye-bi-sub">
          {{ e.ok ? e.r.levelLabel : `模型给出 ${e.r.level} 级，照片不可评估，仅供参考` }}<br />
          置信度 {{ fmtConf(e.r.confidence) }} · 图像质量 {{ e.r.quality || "–" }}
        </div>
        <button class="r6-btn" type="button" @click="openEye(e.side)">查看{{ EYE_CN[e.side] }}完整报告 →</button>
      </div>
    </div>
  </div>

  <!-- 报告主体 -->
  <div v-if="report" class="r6">
    <div class="plate r6-main">
      <div class="r6-head">
        <button type="button" class="r6-thumb" title="打开专业阅片" @click="openViewer(false)">
          <img v-if="report.thumbnail" :src="report.thumbnail" alt="眼底彩照缩略图" />
          <div v-else class="retina"></div>
          <div class="r6-badge">分析完成</div>
        </button>
        <div class="r6-hinfo">
          <h2>眼底筛查报告 · {{ report.eye ? `${EYE_CN[report.eye]} · ` : "" }}{{ titleName }}</h2>
          <div class="r6-meta">
            {{ report.fileName }}<template v-if="report.fileDim || report.fileSize">
              · {{ [report.fileDim, fmtSize(report.fileSize)].filter(Boolean).join(" · ") }}</template><br />
            分析时间 {{ fmtFull(report.analyzedAt) }}<template v-if="report.elapsedMs">
              · 耗时 {{ (report.elapsedMs / 1000).toFixed(1) }}s</template>
            · 来源 {{ report.source === "eye" ? "眼底筛查页" : "Agent助手" }}
          </div>
          <div class="r6-tags">
            <i class="green">分析完成</i>
            <i v-if="report.eye" class="eye-tag">{{ EYE_CN[report.eye] }} {{ EYE_CODE[report.eye] }}</i>
            <i>{{ report.engine }}</i>
            <i v-if="report.mode === 'model'">Grad-CAM</i>
          </div>
        </div>
      </div>
      <div v-if="error" class="r6-err">{{ error }}</div>
      <div class="r6-hero">
        <div class="lbl">DR 分级结果</div>
        <div class="grade">{{ report.level }} 级 · {{ report.levelLabel || DR_LONG[report.level] }}</div>
        <div class="desc">
          按国际 DR 分级标准（ICDR），本级别{{
            report.level === 0 ? "提示未见明显糖尿病视网膜病变。" : "提示视网膜已出现上述级别的血管病变征象。"
          }}{{ report.summary ? ` ${report.summary}` : "" }}
        </div>
        <div class="conf">
          置信度 {{ fmtConf(report.confidence) }} ·
          {{ report.engine.replace(" 本地模型", "").replace(" 视觉模型", "") }}
          <template v-if="report.quality"> · 图像质量 {{ report.quality }}</template>
        </div>
      </div>
      <div v-if="report.escalatedTo != null && report.escalatedTo > report.level" class="r6-border">
        <b>边界提示</b>：模型对 {{ report.level }} 级与 {{ report.escalatedTo }} 级的判断很接近，分级数字保持模型原始输出，就诊时限已按更保守的
        {{ report.escalatedTo }} 级给出。
      </div>
      <div v-if="report.quality === '不可评估'" class="r6-retake">
        <b>照片质量不足以可靠分级{{ qualityWhy }}</b>：建议重拍；无法重拍时请到眼科检查。上面的分级仅供参考，不代表眼底正常。
      </div>
      <div v-else-if="report.quality === '质量偏低'" class="r6-retake soft">
        照片质量偏低{{ qualityWhy }}，分级可能有偏差，条件允许时建议重拍。
      </div>

      <div v-if="report.probs" class="r6-sec">
        <div class="h">各级概率 <span class="sub">模型输出 · 看它在哪两级之间犹豫</span></div>
        <div class="r6-probs">
          <div v-for="(p, i) in report.probs" :key="i" class="r6-prob" :class="{ on: i === report.level }">
            <span class="k">{{ i }} 级</span><i><b :style="{ width: `${Math.max(1.5, Math.min(100, p))}%` }"></b></i><span class="v">{{ p.toFixed(1) }}%</span>
          </div>
        </div>
      </div>

      <div class="r6-sec">
        <div class="h">专业阅片 <span class="sub">增强 · 无赤光 · 热力图叠加 · 并排对照 · 放大镜</span></div>
        <button type="button" class="r6-pro" @click="openViewer(false)">
          <span class="r6-pro-imgs">
            <img v-if="report.viewImage || report.thumbnail" :src="report.viewImage || report.thumbnail || ''" alt="" />
            <img v-if="report.heatmap" :src="`data:image/png;base64,${report.heatmap}`" alt="" />
          </span>
          <span class="r6-pro-t">
            <b>放大查看眼底细节</b>
            <em>切换增强 / 无赤光视图，叠加热力图并调节强度，与原图并排对照，放大镜随鼠标移动。图像处理在本机完成，不改变分级结果。</em>
          </span>
          <i>打开 →</i>
        </button>
      </div>

      <div class="r6-sec">
        <div class="h">病灶明细 <span class="sub">{{ lesionSub }}</span></div>
        <div>
          <template v-if="report.lesions.length">
            <div v-for="(l, i) in report.lesions" :key="i" class="r6-lesion">
              <div class="dot" :style="{ background: LES_COLORS[i % 4] }"></div>
              <div class="body">
                <b>{{ l.type }}{{ l.count ? ` ${l.count} 处` : "" }}</b>
                <span>
                  {{ l.desc || (l.loc ? `位于 ${l.loc}` : "检出征象，具体分布以热力图定位为准")
                  }}{{ l.loc && l.desc ? `（${l.loc}）` : "" }}
                </span>
              </div>
            </div>
          </template>
          <div v-else class="r6-lesion">
            <div class="dot" style="background: #30d158"></div>
            <div class="body">
              <b>未检出明显病灶</b><span>模型未发现可疑征象，建议按常规节奏复查</span>
            </div>
          </div>
        </div>
      </div>

      <div class="r6-sec">
        <div class="h">分级依据 <span class="sub">ICDR 国际标准</span></div>
        <div>
          <div v-for="(c, i) in report.criteria" :key="i" class="r6-crit" :class="c.hit ? 'ok' : 'no'">
            <span class="ck">{{ c.hit ? "✓" : "–" }}</span>
            <span class="tx"><strong v-if="c.hit">{{ c.text }}</strong><template v-else>{{ c.text }}</template></span>
          </div>
        </div>
      </div>

      <div class="r6-sec">
        <div class="h">分诊与随访建议</div>
        <ul class="r6-adv">
          <li><strong>建议科室：</strong>{{ report.department }}（{{ report.urgencyLabel }}）</li>
          <li v-if="report.advice"><strong>随访节奏：</strong>{{ report.advice }}</li>
          <li v-for="(p, i) in report.preVisitNotes ?? []" :key="`p${i}`">{{ p }}</li>
          <li v-if="report.redFlags?.length" class="warn">
            <strong>如出现以下情况改为急诊：</strong>{{ report.redFlags.join("、") }}
          </li>
        </ul>
      </div>

      <div class="r6-warn">
        ⚠ 本报告仅为筛查参考，<strong>不是诊断</strong>，不构成治疗建议，不给药物剂量，不建议自行停药或换药。所有结果需眼科医生确认。
      </div>
    </div>

    <div class="r6-side">
      <div class="plate r6-card">
        <div class="ttl">关键指标</div>
        <div>
          <div class="r6-row"><span class="k">DR 分级</span><span class="v hl">{{ report.level }} 级</span></div>
          <div class="r6-row"><span class="k">置信度</span><span class="v">{{ fmtConf(report.confidence) }}</span></div>
          <div class="r6-row">
            <span class="k">图像质量</span><span class="v" :class="qualityCls">{{ report.quality || "–" }}</span>
          </div>
          <div class="r6-row">
            <span class="k">{{ totalCount.has ? "病灶数" : "病灶征象" }}</span>
            <span class="v" :class="lesionUrgencyCls">
              {{ totalCount.has ? `${totalCount.total} 处` : `${report.lesions.length} 类` }}
            </span>
          </div>
          <div class="r6-row">
            <span class="k">紧急程度</span><span class="v" :class="urgencyCls">{{ report.urgencyLabel }}</span>
          </div>
          <div class="r6-row">
            <span class="k">{{ report.elapsedMs ? "分析耗时" : "分析模式" }}</span>
            <span class="v">{{ report.elapsedMs ? `${(report.elapsedMs / 1000).toFixed(1)}s` : report.engine }}</span>
          </div>
        </div>
      </div>
      <div class="plate r6-card">
        <div class="ttl">历史对比{{ report.eye ? `（${EYE_CN[report.eye]}）` : "" }}</div>
        <div>
          <div class="r6-row"><span class="k">上次筛查</span><span class="v">{{ compare.last }}</span></div>
          <div class="r6-row"><span class="k">上次分级</span><span class="v">{{ compare.lastLevel }}</span></div>
          <div class="r6-row"><span class="k">分级变化</span><span class="v" :class="compare.cls">{{ compare.delta }}</span></div>
          <div class="r6-row"><span class="k">间隔时间</span><span class="v">{{ compare.days }}</span></div>
        </div>
      </div>
    </div>
  </div>

  <!-- 操作区 -->
  <div v-if="report" class="plate r6-card r6-acts-card">
    <div class="ttl">操作</div>
    <div class="r6-acts">
      <button class="r6-btn primary" type="button" @click="openViewer(false)"><span style="display:contents" v-html="reportIcon('heat', 'eye')"></span>专业阅片</button>
      <button class="r6-btn" type="button" @click="openHeat"><span style="display:contents" v-html="reportIcon('heat', 'eye')"></span>查看热力图</button>
      <button class="r6-btn" type="button" @click="printReport"><span style="display:contents" v-html="reportIcon('pdf', 'eye')"></span>导出 PDF 报告</button>
      <button class="r6-btn" type="button" @click="openDoc"><span style="display:contents" v-html="reportIcon('doc', 'eye')"></span>生成给医生的摘要</button>
      <button class="r6-btn" type="button" @click="emit('go', 'hospital', report?.department || '')"><span style="display:contents" v-html="reportIcon('pin', 'eye')"></span>查找附近{{ report?.department || '眼科' }}</button>
    </div>
  </div>

  <FundusViewer
    v-if="viewerOpen && report"
    :key="`${report.analyzedAt}-${report.eye ?? ''}-${viewerHeat}`"
    :image="report.viewImage || report.thumbnail"
    :heat-layer="report.heatLayer"
    :heatmap="report.heatmap"
    :heat="viewerHeat"
    :low-res="!report.viewImage"
    :demo="report.mode === 'demo' || report.heatStatus === 'demo'"
    :title="viewerTitle"
    @close="viewerOpen = false"
  />

  <div v-if="docOpen" class="r6-modal">
    <div class="r6-modal-mask" @click="docOpen = false"></div>
    <div class="r6-modal-body r6-doc-modal">
      <div class="r6-modal-head">
        <b>给医生的摘要</b>
        <span>可直接复制发给接诊医生</span>
        <button type="button" @click="docOpen = false">✕</button>
      </div>
      <div class="r6-doc-body">{{ report?.doctorSummary }}</div>
      <div class="r6-doc-foot">
        <span class="r6-doc-hint">{{ docCopied ? "已复制到剪贴板" : `生成时间 ${localNow()}` }}</span>
        <button class="r6-btn primary" type="button" @click="copyDoc">复制摘要</button>
      </div>
    </div>
  </div>
</template>
