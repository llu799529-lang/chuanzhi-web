<script setup lang="ts">
/**
 * 工作台首页：真实统计 + 上传入口 + 四张卡片（最近记录 / 快捷入口 / 新手指南 / 附近医院）。
 *
 * 四张卡片排成两行两列：同一行等高、两列对齐，不再出现左下角空一块。
 * 附近医院只显示高德地图的真实检索结果（浏览器 JS API，按当前位置）。以前没有 Web 服务 Key 时
 * 显示后端的演示医院（「XX区眼科专科医院」），实测反馈像假数据——现在宁可显示「定位并查看」按钮。
 */
import { computed, onMounted, ref } from "vue";
import { api } from "@/lib/api";
import { svg } from "@/lib/icons";
import { recordRowHtml } from "@/lib/recordRow";
import { distTxt, findNearbyHospitals, levelTag, nearbyCache, type AmapConf, type Poi } from "@/lib/amap";
import { SYMPTOM_SAMPLES } from "@/lib/guide";
import { useRecordsStore } from "@/stores/records";
import { useWorkbenchStore, type PageKey } from "@/stores/workbench";

const emit = defineEmits<{ go: [page: PageKey] }>();
const wb = useWorkbenchStore();
const rec = useRecordsStore();

/** 评审建议「增加眼底图片上传演示」：一键进入眼底页并用示例图走完整流程。 */
function openFundusDemo() {
  wb.requestDemo("eye");
  emit("go", "eye");
}
function openLabDemo() {
  wb.requestDemo("lab");
  emit("go", "lab");
}
// 上传框：点击进入眼底页；拖进来的照片直接交给眼底页分析（以前写着「拖拽上传」，拖进来却什么也不发生）
const dropOver = ref(false);
const dropMsg = ref("");
function onDrop(e: DragEvent) {
  dropOver.value = false;
  const f = e.dataTransfer?.files?.[0];
  if (!f) return;
  if (f.type && !f.type.startsWith("image/")) {
    dropMsg.value = "只支持 JPG / PNG 图片；化验单请从下方「化验单」入口上传";
    return;
  }
  dropMsg.value = "";
  wb.request("eye", "file", "", f);
  emit("go", "eye");
}
function openSymptomSample() {
  wb.prefill("symptom", SYMPTOM_SAMPLES[0].text);
  emit("go", "symptom");
}

const FEATURES: { ic: string; t: string; s: string; p: PageKey }[] = [
  { ic: "eye", t: "眼底筛查", s: "DR 分级 · 热力图", p: "eye" },
  { ic: "lab", t: "化验单", s: "异常标红 · 通俗解释", p: "lab" },
  { ic: "chat", t: "症状分诊", s: "疑似方向 Top 3", p: "symptom" },
  { ic: "pin", t: "医院推荐", s: "按科室与距离", p: "hospital" },
];

const stats = computed(() => {
  const list = rec.records;
  const eye = list.filter((r) => r.input_type === "眼底彩照").length;
  const lab = list.filter((r) => r.input_type === "化验单").length;
  const sx = list.filter((r) => r.input_type === "症状描述").length;
  const urgent = list.filter((r) => r.urgency === "orange" || r.urgency === "red").length;
  const used = rec.usage.month_used;
  const quota = rec.usage.month_quota || 200;
  return [
    { k: "真实记录", v: String(list.length), u: "条", s: `眼底 ${eye} · 化验 ${lab} · 症状 ${sx}` },
    { k: "需复诊", v: String(urgent), u: "份", s: urgent ? "含橙色 / 红色记录" : "暂无紧急" },
    { k: "眼底模型", v: "EfficientNet", u: "-B3", s: "DR 0–4 级 · Grad-CAM 热力图" },
    { k: "本月用量", v: String(used), u: `/${quota}`, s: `${rec.usagePct}% · 剩 ${quota - used} 次` },
  ];
});

const recentHtml = computed(() => rec.records.slice(0, 4).map(recordRowHtml).join(""));

// ---------------------------------------------------------------- 附近医院（高德真实检索）
type HospState = "idle" | "loading" | "ok" | "error";
const hospState = ref<HospState>("idle");
const hospMsg = ref("");
const hospList = ref<Poi[]>([]);
const hospApprox = ref(false);

function showNearby(pois: Poi[], approximate: boolean) {
  hospList.value = pois.slice(0, 4);
  hospApprox.value = approximate;
  if (pois.length) {
    hospState.value = "ok";
  } else {
    hospState.value = "error";
    hospMsg.value = "附近没有检索到医院，可以到「附近医院」页放大地图查看";
  }
}

async function loadNearby() {
  if (hospState.value === "loading") return;
  hospState.value = "loading";
  try {
    const conf = await api<AmapConf>("/api/hospitals");
    const r = await findNearbyHospitals(conf);
    showNearby(r.pois, r.approximate);
  } catch (e) {
    hospState.value = "error";
    hospMsg.value = (e as Error).message || "附近医院检索失败";
  }
}

/** 浏览器已经授权过定位才自动检索；没授权就等用户点按钮，不在工作台一打开就弹定位授权框 */
async function geoGranted(): Promise<boolean> {
  try {
    const st = await navigator.permissions?.query({ name: "geolocation" as PermissionName });
    return st?.state === "granted";
  } catch {
    return false;
  }
}

function hospSub(h: Poi): string {
  return [levelTag(h.type, h.name), h.address].filter(Boolean).join(" · ");
}

onMounted(async () => {
  void rec.load().catch(() => undefined);
  const cached = nearbyCache.get();
  if (cached) {
    showNearby(cached.pois, cached.approximate);
    return;
  }
  if (await geoGranted()) void loadNearby();
});
</script>

<template>
  <div class="page-t">
    <div>
      <h1 class="engrave">工作台</h1>
      <p>上传报告，获取分诊建议与附近医院</p>
    </div>
  </div>

  <div class="stat-row">
    <div v-for="s in stats" :key="s.k" class="stat plate">
      <div class="k">{{ s.k }}</div>
      <div class="v mt-text">{{ s.v }}<em>{{ s.u }}</em></div>
      <div class="s">{{ s.s }}</div>
    </div>
  </div>

  <div
    class="drop"
    :class="{ over: dropOver }"
    style="margin-bottom: 16px"
    @click="emit('go', 'eye')"
    @dragover.prevent="dropOver = true"
    @dragleave.prevent="dropOver = false"
    @drop.prevent="onDrop"
  >
    <div class="bigic">
      <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" /></svg>
    </div>
    <b>拖拽或点击上传眼底彩照</b>
    <span>{{ dropMsg || "拖进来直接分析 · 双眼筛查与专业阅片在眼底页 · 化验单、症状请走下方快捷入口" }}</span>
    <div class="fmts"><i>JPG</i><i>PNG</i></div>
    <button type="button" class="drop-demo" @click.stop="openFundusDemo">没有眼底照片？用示例图体验 →</button>
  </div>

  <div class="wp-grid">
    <section class="plate wp-card">
      <div class="sec-h">
        <h3>最近记录</h3>
        <a style="cursor: pointer" @click="emit('go', 'history')">全部 →</a>
      </div>
      <div v-if="rec.records.length" class="reclist wp-rec" @click="emit('go', 'history')" v-html="recentHtml"></div>
      <div v-else class="wp-empty">
        <span class="ic-plate" v-html="svg('xray')"></span>
        <b>还没有筛查记录</b>
        <span>上传眼底照片、化验单或描述症状后，结果会按时间出现在这里</span>
        <button type="button" class="wp-btn ghost" @click="emit('go', 'guide')">先看使用指南</button>
      </div>
    </section>

    <section class="plate wp-card">
      <div class="sec-h"><h3>快捷入口</h3></div>
      <div class="fgrid">
        <div v-for="f in FEATURES" :key="f.t" class="fcard plate" @click="emit('go', f.p)">
          <div class="ic-plate" v-html="svg(f.ic)"></div>
          <b>{{ f.t }}</b><span>{{ f.s }}</span>
        </div>
      </div>
    </section>

    <section class="plate wp-card">
      <div class="sec-h">
        <h3>新手指南</h3>
        <a style="cursor: pointer" @click="emit('go', 'guide')">完整指南 →</a>
      </div>
      <div class="wp-guide">
        <button type="button" @click="openFundusDemo">
          <span class="ic-plate" v-html="svg('eye')"></span>
          <span class="t"><b>眼底图上传演示</b><em>用示例图走一遍：上传 → 质量检查 → 分级 → 报告</em></span>
          <i aria-hidden="true">›</i>
        </button>
        <button type="button" @click="openLabDemo">
          <span class="ic-plate" v-html="svg('lab')"></span>
          <span class="t"><b>化验单识别示例</b><em>合成化验单，在线视觉模型识别约 10～30 秒</em></span>
          <i aria-hidden="true">›</i>
        </button>
        <button type="button" @click="openSymptomSample">
          <span class="ic-plate" v-html="svg('chat')"></span>
          <span class="t"><b>症状描述示例</b><em>把一段示例描述填进症状分诊，提交与否由你决定</em></span>
          <i aria-hidden="true">›</i>
        </button>
      </div>
    </section>

    <section class="plate wp-card">
      <div class="sec-h">
        <h3>附近医院</h3>
        <a style="cursor: pointer" @click="emit('go', 'hospital')">地图 →</a>
      </div>
      <template v-if="hospState === 'ok'">
        <div class="wp-hosp">
          <div v-for="h in hospList" :key="h.name + h.address" class="hosp" @click="emit('go', 'hospital')">
            <div class="i"><b>{{ h.name }}</b><span>{{ hospSub(h) }}</span></div>
            <div class="d">{{ distTxt(h.distance) }}</div>
          </div>
        </div>
        <p class="wp-foot">{{ hospApprox ? "未取得精确定位：距离按所在城市中心估算" : "按当前位置实时检索 · 数据来自高德地图" }}</p>
      </template>
      <div v-else class="wp-empty">
        <span class="ic-plate" v-html="svg('pin')"></span>
        <template v-if="hospState === 'loading'">
          <b>正在定位并检索…</b><span>首次使用时浏览器会询问是否允许定位</span>
        </template>
        <template v-else-if="hospState === 'error'">
          <b>暂时没查到</b><span>{{ hospMsg }}</span>
        </template>
        <template v-else>
          <b>查看你附近的医院</b><span>定位只在浏览器里交给高德地图检索，不会上传到本系统</span>
        </template>
        <button v-if="hospState !== 'loading'" type="button" class="wp-btn" @click="loadNearby">
          {{ hospState === "error" ? "重新检索" : "定位并查看" }}
        </button>
      </div>
    </section>
  </div>
</template>
