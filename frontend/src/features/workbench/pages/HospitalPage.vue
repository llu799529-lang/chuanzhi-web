<script setup lang="ts">
/** 附近医院：高德地图 + 周边检索 + 科室重排（首次进入页面时懒加载 SDK） */
import { computed, onMounted, ref, watch } from "vue";
import { api } from "@/lib/api";
import { matchDept } from "@/lib/dept";
import { useWorkbenchStore } from "@/stores/workbench";
import {
  DEPT_OPTIONS,
  deptHit,
  distTxt,
  genIntro,
  hospitalProfile,
  levelTag,
  loadAmapScript,
  navUrl,
  nearbyCache,
  setupMap,
  sortPois,
  type AmapConf,
  type MapController,
  type Poi,
} from "@/lib/amap";

const props = defineProps<{ active: boolean }>();

const wb = useWorkbenchStore();
const DEPT_KEY = "mt_triage_dept";
const dept = ref(localStorage.getItem(DEPT_KEY) || "眼科");
const loading = ref(true);
const tip = ref("正在定位并检索附近医院…");
// 地图 SDK 不可用时的独立状态：卡片列表照常渲染，只是画布区改为说明文案，
// 不能让它空白（无 Key 时 loadAmapScript 直接 resolve(null)，容器里什么都不画）。
const mapUnavailable = ref(false);
const mapNotice = ref("");
const live = ref(false);
const allPois = ref<Poi[]>([]);
const selected = ref(0);
const boxEl = ref<HTMLDivElement | null>(null);
let controller: MapController | null = null;
let started = false;

const ranked = computed(() => sortPois(allPois.value, dept.value).slice(0, 15));

const cards = computed(() =>
  ranked.value.map((p, i) => {
    const info = hospitalProfile(p.name, p.type, p.depts);
    const hit = deptHit(info.depts, p.name, dept.value);
    return {
      i,
      poi: p,
      level: levelTag(p.type, p.name),
      intro: genIntro(p.name, levelTag(p.type, p.name), info),
      chips: info.depts.map((d, j) => ({ text: d, hit: j === hit, key: `${p.name}-${d}-${j}` })),
      dist: distTxt(p.distance),
      tel: p.tel && /\d/.test(p.tel) ? p.tel.split(";")[0] : "",
      // 未命中的排在后面，明确标一下，别让用户以为它也能接这个科
      noDept: hit < 0,
    };
  }),
);

// 命中数量。原来这里只写「N 家 · 适合 X 优先」，一个科室都没命中时
// 那句话就是假的：列表顺序完全没变，用户却以为已经按科室筛过。
const hitCount = computed(
  () =>
    ranked.value.filter(
      (p) => deptHit(hospitalProfile(p.name, p.type, p.depts).depts, p.name, dept.value) >= 0,
    ).length,
);

const countTip = computed(() => {
  const n = ranked.value.length;
  if (!n) return tip.value;
  // 命中数为 0 时不能再说「适合 X 优先」——列表顺序其实没变，
  // 用户会以为筛选生效了。区分「开设」和「未明确开设」两种事实。
  if (!hitCount.value) return `${n} 家 · 均未明确开设${dept.value}，按距离排序`;
  return `${n} 家 · ${hitCount.value} 家开设${dept.value}`;
});

/** 地图 SDK 不可用时的真实数据入口：高德网页按关键词检索（不需要本系统的 Key） */
const amapSearchUrl = computed(
  () => `https://uri.amap.com/search?keyword=${encodeURIComponent(`${dept.value} 医院`)}&src=medtriage&callnative=0`,
);
function draw() {
  controller?.draw(ranked.value, dept.value, (i) => select(i));
}

function select(i: number) {
  selected.value = i;
  controller?.focus(ranked.value, i);
}

function onDeptChange() {
  localStorage.setItem(DEPT_KEY, dept.value);
  selected.value = 0;
  draw();
}

function fail(msg: string) {
  loading.value = false;
  tip.value = msg;
}

async function ensure() {
  if (started) return;
  started = true;
  try {
    const conf = await api<AmapConf>("/api/hospitals");
    const hasKey = !!(conf.amap_js_key || "").trim();
    const AMap = await loadAmapScript(conf.amap_js_key || "", conf.amap_js_sec || "");
    if (!AMap) {
      // 无地图 SDK：不拿演示医院凑数（实测反馈「XX 医院是什么假数据」）；画布区说明原因，并给高德网页检索入口
      allPois.value = [];
      live.value = false;
      loading.value = false;
      mapUnavailable.value = true;
      mapNotice.value = hasKey
        ? "地图 SDK 加载失败：请检查网络，或确认高德 JS API Key 的域名白名单是否包含 127.0.0.1"
        : "地图未启用：请在项目根目录 .env 中填入 AMAP_JS_KEY 后重启服务（申请地址 console.amap.com）";
      tip.value = "地图未启用";
      return;
    }
    if (!boxEl.value) return;
    controller = await setupMap(
      boxEl.value,
      AMap,
      (pois) => {
        allPois.value = pois;
        nearbyCache.set(pois);
        live.value = true;
        loading.value = false;
        draw();
      },
      (msg) => fail(msg),
    );
  } catch (e) {
    allPois.value = [];
    loading.value = false;
    fail((e as Error).message || "医院数据加载失败");
  }
}

function goNav(p: Poi) {
  const url = navUrl(p);
  if (url) window.open(url, "_blank");
}

function call(tel: string) {
  location.href = `tel:${tel}`;
}

// 挂载与「切到本页」合并成一个 immediate watch：原来 onMounted + watch 各调一次
// ensure()，首次进入会重复触发（ensure 里有 started 守卫所以不出错，但属于冗余）。
function adoptPendingDept() {
  const d = wb.takeDept();
  if (!d) return;
  // 分诊/眼底/化验单给的是「神经内科」这类自由文本，而医院页存的是
  // 「眼科 / 全科」这类**选项名**。归一化逻辑放在 lib/dept.ts 里，
  // 那里有表驱动测试（匹配不上 / 匹配错了 两种失败都要钉住）。
  dept.value = matchDept(d, DEPT_OPTIONS);
  localStorage.setItem(DEPT_KEY, dept.value);
  selected.value = 0;
  if (!mapUnavailable.value) draw();
}

watch(
  () => props.active,
  (on) => {
    if (!on) return;
    adoptPendingDept();
    void ensure();
  },
  { immediate: true },
);
</script>

<template>
  <div class="page-t">
    <div>
      <h1 class="engrave">附近医院</h1>
      <p>根据建议科室与当前位置，推荐附近可接诊的医院</p>
    </div>
  </div>

  <div class="map-shell">
    <div ref="boxEl" class="map-canvas" :class="{ live }">
      <div v-if="loading" class="map-loading"><span class="dot-pulse"></span>正在定位并检索附近医院…</div>
      <div v-else-if="mapUnavailable" class="map-fallback">
        <svg viewBox="0 0 24 24" width="34" height="34" aria-hidden="true">
          <path
            d="M12 21s7-5.6 7-11a7 7 0 1 0-14 0c0 5.4 7 11 7 11Z"
            fill="none"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linejoin="round"
          />
          <circle cx="12" cy="10" r="2.6" fill="none" stroke="currentColor" stroke-width="1.4" />
        </svg>
        <p class="map-fallback-t">地图暂不可用</p>
        <p class="map-fallback-d">{{ mapNotice }}</p>
        <a class="map-fallback-btn" :href="amapSearchUrl" target="_blank" rel="noopener">在高德地图中搜索附近的{{ dept }}医院</a>
      </div>
      <div v-else-if="!allPois.length" class="map-loading">{{ tip }}</div>
    </div>

    <div class="hosp-detail">
      <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 4px; gap: 8px">
        <div class="dept-pick">
          <span class="cap2">就诊科室</span>
          <select v-model="dept" aria-label="选择就诊科室" @change="onDeptChange">
            <option v-for="d in DEPT_OPTIONS" :key="d" :value="d">{{ d }}</option>
          </select>
        </div>
        <div style="font-size: 11.5px; color: var(--muted)">{{ countTip }}</div>
      </div>

      <div>
        <div v-if="!cards.length" class="hosp-skeleton">{{ loading ? "正在获取附近医院…" : mapUnavailable ? "地图服务未启用，暂无医院列表" : tip }}</div>
        <div
          v-for="c in cards"
          :key="c.i"
          class="hosp-card"
          :class="{ sel: selected === c.i }"
          @click="select(c.i)"
        >
          <div class="h">
            <div class="idx">{{ c.i + 1 }}</div>
            <b>{{ c.poi.name }}</b>
            <div class="dist">{{ c.dist }}</div>
          </div>
          <div class="tags">
            <i>{{ c.level }}</i>
            <i v-if="c.noDept" style="opacity: 0.75">未明确开设{{ dept }}</i>
          </div>
          <div class="intro">{{ c.intro }}</div>
          <div class="depts">
            <span class="cap">特色科室</span>
            <i v-for="ch in c.chips" :key="ch.key" :class="{ hit: ch.hit }">{{ ch.hit ? "✓ " : "" }}{{ ch.text }}</i>
          </div>
          <div class="addr">{{ c.poi.address || "暂无地址信息" }}</div>
          <div class="actions">
            <button class="primary" type="button" @click.stop="goNav(c.poi)">导航前往</button>
            <button v-if="c.tel" type="button" @click.stop="call(c.tel)">电话</button>
          </div>
        </div>
      </div>
    </div>
  </div>

  <div class="disclaimer" style="margin-top: 16px">
    位置与医院数据来自高德开放平台；「适合科室」为规则推断，仅供参考。
  </div>
</template>
