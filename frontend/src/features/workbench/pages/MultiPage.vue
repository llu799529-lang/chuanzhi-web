<script setup lang="ts">
/**
 * 多模态综合分析：历史记录（眼底/化验/症状）交叉解读。
 * 气泡流版式沿用 app.html 的 mma 组件；首次进入自动分析，支持强制刷新。
 */
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { api, ApiError } from "@/lib/api";
import { esc } from "@/lib/icons";
import { useRecordsStore } from "@/stores/records";
import type { PageKey } from "@/stores/workbench";
import { labReportStore } from "@/lib/labReport";

const props = defineProps<{ active: boolean }>();
const emit = defineEmits<{ go: [page: PageKey] }>();
const rec = useRecordsStore();

interface Finding {
  severity: "crit" | "warn" | "info";
  label: string;
  title: string;
  text: string;
  data?: { k: string; v: string; cls?: string }[];
  when?: string;
  when_cls?: string;
  advice?: string[];
  acts?: { t: string; a: string; primary?: boolean }[];
}
interface MultiResult {
  intro: string;
  findings: Finding[];
}

const STAGES = [
  { h: "正在汇总你的筛查记录", p: "整理眼底、化验、症状三项数据的时间线与异常项…" },
  { h: "正在交叉比对指标", p: "把化验异常与眼底分级、症状主诉做关联，识别关键风险链…" },
  { h: "正在生成分级建议", p: "按严重程度排序，给每条发现配建议与就诊科室，约还需几秒…" },
];

const loading = ref(false);
const loadingStage = ref(0);
const result = ref<MultiResult | null>(null);
const error = ref("");
const loaded = ref(false);
let rotTimer: number | undefined;
let cacheSig = "";
onBeforeUnmount(() => window.clearInterval(rotTimer));

const AV: Record<string, string> = { crit: "red", warn: "yellow", info: "blue" };

const subText = computed(() => {
  if (result.value?.findings?.length) {
    const n = new Date();
    const p = (x: number) => String(x).padStart(2, "0");
    return `AI 助手逐条解读 · ${n.getFullYear()}-${p(n.getMonth() + 1)}-${p(n.getDate())} 生成 · 已结合 ${rec.records.length} 条真实记录`;
  }
  return "AI 助手逐条解读 · 眼底、化验、症状三项数据交叉分析";
});

/** 富文本清洗：只放行 <b>/<strong>（后端已清洗，这里再兜一道） */
function rich(v: string): string {
  return esc(v)
    .replace(/&lt;b&gt;/g, "<b>")
    .replace(/&lt;\/b&gt;/g, "</b>")
    .replace(/&lt;strong&gt;/g, "<strong>")
    .replace(/&lt;\/strong&gt;/g, "</strong>");
}

async function analyze(force = false) {
  if (loading.value) return;
  const labDetail = labReportStore.get()?.report ?? null;
  const signature = () => JSON.stringify([rec.records.map((r) => r.id), labReportStore.get()?.report ?? null]);
  const sig = signature();
  if (!force && loaded.value && sig === cacheSig) return;

  loading.value = true;
  error.value = "";
  loadingStage.value = 0;
  window.clearInterval(rotTimer);
  rotTimer = window.setInterval(() => {
    loadingStage.value = Math.min(loadingStage.value + 1, STAGES.length - 1);
  }, 2600);
  try {
    if (!rec.loaded) await rec.load();
    const data = await api<MultiResult>("/api/ai/multimodal", { method: "POST", body: { lab_detail: labDetail } });
    result.value = data;
    loaded.value = true;
    cacheSig = JSON.stringify([rec.records.map((r) => r.id), labDetail]);
  } catch (e) {
    error.value =
      e instanceof ApiError && e.code === "UNAVAILABLE"
        ? "大模型未启用：请配置 ARK_API_KEY 后重试"
        : (e as Error).message || "分析失败";
  } finally {
    window.clearInterval(rotTimer);
    loading.value = false;
  }
}

/** 动作码 → 页面：与原生版 mma 的行为对齐（能跳的跳，能力型给出提示） */
const ACT_ROUTES: Record<string, PageKey> = {
  oct: "eye",
  fundus: "eye",
  sx: "symptom",
  lab: "lab",
  glucose: "lab",
  history: "history",
  hospital: "hospital",
  uacr: "hospital",
  whatUacr: "hospital",
};

function onAct(a: string) {
  const page = ACT_ROUTES[a];
  if (page) emit("go", page);
}

watch(
  () => props.active,
  (on) => {
    if (on) void analyze();
  },
  { immediate: true },
);
</script>

<template>
  <div class="page-t">
    <div>
      <h1 class="engrave">多模态综合分析</h1>
      <p>{{ subText }}</p>
    </div>
    <div class="right">
      <button class="btn-silver" type="button" :disabled="loading" @click="analyze(true)">
        <svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 3-6.7L3 8" /><path d="M3 4v4h4" /><path d="M12 7.5v4.8l3 2" /></svg>
        <span>{{ loading ? "分析中…" : "结合最新记录刷新" }}</span>
      </button>
    </div>
  </div>

  <div class="mma">
    <div class="mma-frame mt-silver">
      <div class="mma-body">
        <!-- 加载态：轮换阶段提示 -->
        <div v-if="loading" class="mma-msg info">
          <div class="mma-av blue"><div class="mma-dia"></div></div>
          <div class="mma-bubble">
            <div class="lbl">正在分析</div>
            <h4>{{ STAGES[loadingStage].h }}</h4>
            <p>{{ STAGES[loadingStage].p }}</p>
            <div class="typing" style="margin-top: 10px"><i></i><i></i><i></i></div>
          </div>
        </div>

        <!-- 错误态 -->
        <div v-else-if="error" class="mma-msg warn">
          <div class="mma-av yellow"><div class="mma-dia"></div></div>
          <div class="mma-bubble">
            <div class="lbl">提示</div>
            <h4>暂时无法完成综合分析</h4>
            <p>{{ error }}</p>
            <div class="mma-act"><button class="primary" type="button" @click="analyze(true)">重试</button></div>
          </div>
        </div>

        <template v-else-if="result">
          <!-- 开场 -->
          <div class="mma-msg info">
            <div class="mma-av blue"><div class="mma-dia"></div></div>
            <div class="mma-bubble">
              <div class="lbl">开场</div>
              <h4>我综合分析了你最近的记录</h4>
              <p v-html="rich(result.intro || '已结合你的真实筛查记录完成交叉分析，下面按重要性逐条说明。')"></p>
            </div>
          </div>

          <!-- 发现 -->
          <div v-for="(f, i) in result.findings" :key="i" class="mma-msg" :class="f.severity">
            <div class="mma-av" :class="AV[f.severity] || 'blue'"><div class="mma-dia"></div></div>
            <div class="mma-bubble">
              <div class="lbl">{{ f.label }}</div>
              <h4>{{ f.title }}</h4>
              <p v-html="rich(f.text)"></p>

              <div v-if="f.data?.length" class="mma-data">
                <div v-for="(r, j) in f.data" :key="j" class="r">
                  <span class="k">{{ r.k }}</span>
                  <span class="v" :class="r.cls && r.cls !== 'dim' ? r.cls : ''" :style="r.cls === 'dim' ? { color: 'var(--faint)' } : undefined">
                    {{ r.v }}
                  </span>
                </div>
              </div>

              <div v-if="f.advice?.length" class="mma-adv">
                <div class="head">
                  <b>建议</b>
                  <span v-if="f.when" class="when" :class="f.when_cls">{{ f.when }}</span>
                </div>
                <ul>
                  <li v-for="(a, j) in f.advice" :key="j" v-html="rich(a)"></li>
                </ul>
              </div>

              <div v-if="f.acts?.length" class="mma-act">
                <button
                  v-for="(a, j) in f.acts"
                  :key="j"
                  type="button"
                  :class="{ primary: a.primary }"
                  @click="onAct(a.a)"
                >
                  {{ a.t }}
                </button>
              </div>
            </div>
          </div>

          <div class="mma-disc">
            ⚠ 本结论由眼底、化验、症状三项数据交叉分析生成，仅为筛查参考，<strong>不是诊断</strong>，不构成治疗建议，需医生最终确认。如出现突发剧烈头痛、意识模糊、胸痛、视力骤降等情况，请立即拨打 120。
          </div>
        </template>

        <!-- 空态：没有记录 -->
        <div v-else class="mma-msg info">
          <div class="mma-av blue"><div class="mma-dia"></div></div>
          <div class="mma-bubble">
            <div class="lbl">开场</div>
            <h4>还没有可交叉分析的记录</h4>
            <p>先完成一次眼底筛查、化验单识别或症状分诊，我就能把它们串起来给你一份综合结论。</p>
            <div class="mma-act">
              <button class="primary" type="button" @click="emit('go', 'eye')">去做眼底筛查</button>
              <button type="button" @click="emit('go', 'symptom')">描述症状</button>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>
