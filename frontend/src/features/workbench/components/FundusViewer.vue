<script setup lang="ts">
/**
 * 专业阅片：在报告页放大查看眼底照片。
 *   底图：原图 / 增强（亮度 CLAHE）/ 无赤光（绿色通道 CLAHE），算法见 lib/fundusImage.ts；
 *   叠加：Grad-CAM 热力层，强度可调；可左右并排对照（放大镜两边同步）。
 * 全部在浏览器里处理：不上传、不调用模型，也不改变分级结果。
 */
import { computed, onBeforeUnmount, onMounted, ref } from "vue";
import { enhance, redFree } from "@/lib/fundusImage";

type Base = "orig" | "enh" | "rf";
interface Layer {
  src: string;
  opacity: number;
}
interface LensBox {
  x: number;
  y: number;
  bw: number;
  bh: number;
  bx: number;
  by: number;
}

const props = defineProps<{
  image: string | null; // 原图（dataURL）
  heatLayer: string | null; // 透明热力层（base64 PNG）
  heatmap: string | null; // 与原图混合好的热力图（base64 PNG；旧报告只有这个）
  heat?: boolean; // 打开时是否叠加热力图（「查看热力图」入口为 true）
  lowRes?: boolean; // 原图只有缓存里的缩略图
  demo?: boolean; // 演示模式：热力图是模拟的
  title?: string;
}>();
const emit = defineEmits<{ close: [] }>();

const BASES: { k: Base; t: string; d: string }[] = [
  { k: "orig", t: "原图", d: "上传的原始照片。" },
  { k: "enh", t: "增强", d: "对亮度做局部对比度均衡（CLAHE），颜色不变：渗出、出血点更容易看清。" },
  { k: "rf", t: "无赤光", d: "只看绿色通道：出血、微血管瘤和血管呈深色、对比最强，是眼科找微小病灶的常用看法。" },
];
const LENS = 180;

const base = ref<Base>("orig");
const heatOn = ref(!!props.heat && !!(props.heatLayer || props.heatmap));
const alpha = ref(60);
const split = ref(false);
const lensOn = ref(true);
const zoom = ref(2.5);
const urls = ref<Record<"orig" | "enh" | "rf" | "layer" | "blend", string | null>>({
  orig: null,
  enh: null,
  rf: null,
  layer: null,
  blend: null,
});
const natural = ref({ w: 1, h: 1 });
const processing = ref(false);
const failed = ref("");
const lens = ref<LensBox[] | null>(null);
const paneEls: HTMLElement[] = [];
const owned: string[] = [];

const hasHeat = computed(() => !!(urls.value.layer || urls.value.blend));
/** 只有混合好的热力图（没有单独的热力层）时，热力图只能叠在原图上 */
const blendOnly = computed(() => !urls.value.layer && !!urls.value.blend);
const baseInfo = computed(() => BASES.find((b) => b.k === base.value) ?? BASES[0]);

function baseLayer(): Layer {
  const src = (base.value !== "orig" && urls.value[base.value]) || urls.value.orig || urls.value.blend || "";
  return { src, opacity: 1 };
}
function heatLayers(): Layer[] {
  const src = urls.value.layer || urls.value.blend;
  return src ? [{ src, opacity: alpha.value / 100 }] : [];
}
const panes = computed<Layer[][]>(() => {
  const b = baseLayer();
  if (split.value && hasHeat.value) return [[b], [b, ...heatLayers()]];
  return [heatOn.value ? [b, ...heatLayers()] : [b]];
});

function setBase(k: Base) {
  if (k !== "orig" && !urls.value[k]) return; // 还没算好
  base.value = k;
  if (blendOnly.value && k !== "orig") {
    heatOn.value = false;
    split.value = false;
  }
}
function onHeatChange() {
  if (heatOn.value && blendOnly.value) base.value = "orig";
}
function toggleSplit() {
  if (!hasHeat.value) return;
  split.value = !split.value;
  if (split.value && blendOnly.value) base.value = "orig";
  lens.value = null;
}
function toggleLens() {
  lensOn.value = !lensOn.value;
  if (!lensOn.value) lens.value = null;
}

function setPane(el: unknown, i: number) {
  if (el && typeof (el as HTMLElement).getBoundingClientRect === "function") paneEls[i] = el as HTMLElement;
}
function fitOf(el: HTMLElement) {
  const r = el.getBoundingClientRect();
  const s = Math.min(r.width / natural.value.w, r.height / natural.value.h);
  const dw = natural.value.w * s;
  const dh = natural.value.h * s;
  return { r, dw, dh, ox: (r.width - dw) / 2, oy: (r.height - dh) / 2 };
}
/** 放大镜：在哪个窗格移动都按同一个图像位置计算，并排时两边同步 */
function onPointer(e: PointerEvent) {
  if (!lensOn.value) return;
  const f = fitOf(e.currentTarget as HTMLElement);
  const u = (e.clientX - f.r.left - f.ox) / f.dw;
  const v = (e.clientY - f.r.top - f.oy) / f.dh;
  if (u < 0 || u > 1 || v < 0 || v > 1) {
    lens.value = null;
    return;
  }
  const z = zoom.value;
  const half = LENS / 2;
  lens.value = panes.value.map((_, i) => {
    const p = paneEls[i] ? fitOf(paneEls[i]) : f;
    return {
      x: p.ox + u * p.dw - half,
      y: p.oy + v * p.dh - half,
      bw: p.dw * z,
      bh: p.dh * z,
      bx: half - u * p.dw * z,
      by: half - v * p.dh * z,
    };
  });
}

/**
 * dataURL → blob: 地址。放大镜每次移动都要重设背景图：直接用几 MB 的 dataURL 当 CSS 背景会让每一帧都很卡。
 * 本地解码，不发网络请求（前端只允许 lib/api.ts 发请求，见 tests/structure.test.ts）。
 */
function toBlobUrl(src: string): string {
  const m = /^data:([^;,]+)?;base64,/.exec(src);
  if (!m) return src;
  const bin = atob(src.slice(m[0].length));
  const bytes = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i);
  const u = URL.createObjectURL(new Blob([bytes], { type: m[1] || "image/png" }));
  owned.push(u);
  return u;
}
function loadImg(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("图片加载失败"));
    img.src = src;
  });
}
function canvasUrl(c: HTMLCanvasElement): Promise<string | null> {
  return new Promise((resolve) =>
    c.toBlob(
      (b) => {
        if (!b) return resolve(null);
        const u = URL.createObjectURL(b);
        owned.push(u);
        resolve(u);
      },
      "image/jpeg",
      0.92,
    ),
  );
}
async function buildViews(img: HTMLImageElement) {
  processing.value = true;
  await new Promise((r) => setTimeout(r, 40)); // 先把弹窗画出来，再做像素计算
  try {
    const w = img.naturalWidth;
    const h = img.naturalHeight;
    const c = document.createElement("canvas");
    c.width = w;
    c.height = h;
    const g = c.getContext("2d", { willReadFrequently: true });
    if (!g) return;
    g.drawImage(img, 0, 0);
    const src = g.getImageData(0, 0, w, h).data;
    for (const [k, fn] of [
      ["enh", enhance],
      ["rf", redFree],
    ] as const) {
      const out = g.createImageData(w, h);
      out.data.set(fn(src, w, h));
      g.putImageData(out, 0, 0);
      urls.value[k] = await canvasUrl(c);
    }
  } finally {
    processing.value = false;
  }
}

async function saveView() {
  const layers = panes.value[panes.value.length - 1];
  const imgs = await Promise.all(layers.map((l) => loadImg(l.src)));
  const c = document.createElement("canvas");
  c.width = natural.value.w;
  c.height = natural.value.h;
  const g = c.getContext("2d");
  if (!g) return;
  imgs.forEach((im, i) => {
    g.globalAlpha = layers[i].opacity;
    g.drawImage(im, 0, 0, c.width, c.height);
  });
  const a = document.createElement("a");
  a.href = c.toDataURL("image/png");
  a.download = `MedTriage_阅片_${baseInfo.value.t}${layers.length > 1 ? "_热力图" : ""}.png`;
  a.click();
}

function onKey(e: KeyboardEvent) {
  if (e.key === "Escape") {
    emit("close");
    return;
  }
  if (e.target instanceof HTMLInputElement) return; // 滑杆聚焦时让方向键正常工作
  const k = e.key.toLowerCase();
  if (k === "1" || k === "2" || k === "3") setBase(BASES[Number(k) - 1].k);
  else if (k === "h" && hasHeat.value) {
    heatOn.value = !heatOn.value;
    onHeatChange();
  } else if (k === "s") toggleSplit();
  else if (k === "m") toggleLens();
}

onMounted(async () => {
  window.addEventListener("keydown", onKey);
  try {
    if (props.heatLayer) urls.value.layer = toBlobUrl(`data:image/png;base64,${props.heatLayer}`);
    if (props.heatmap) urls.value.blend = toBlobUrl(`data:image/png;base64,${props.heatmap}`);
    if (props.image) urls.value.orig = toBlobUrl(props.image);
    const first = urls.value.orig || urls.value.blend;
    if (!first) return;
    const img = await loadImg(first);
    natural.value = { w: img.naturalWidth, h: img.naturalHeight };
    if (urls.value.orig) await buildViews(img);
  } catch {
    failed.value = "增强与无赤光视图生成失败，仍可查看原图与热力图。";
  }
});
onBeforeUnmount(() => {
  window.removeEventListener("keydown", onKey);
  owned.forEach((u) => URL.revokeObjectURL(u));
});
</script>

<template>
  <div class="fv" role="dialog" aria-modal="true" aria-label="专业阅片">
    <div class="fv-mask" @click="emit('close')"></div>
    <div class="fv-box">
      <header class="fv-head">
        <div class="fv-title"><b>专业阅片</b><span v-if="title">{{ title }}</span></div>
        <span class="fv-keys">1 / 2 / 3 切换底图 · H 热力图 · S 并排 · M 放大镜 · Esc 关闭</span>
        <button type="button" class="fv-x" aria-label="关闭" @click="emit('close')">✕</button>
      </header>
      <div class="fv-bar">
        <div class="fv-seg" role="group" aria-label="底图">
          <button
            v-for="(b, i) in BASES"
            :key="b.k"
            type="button"
            :class="{ on: base === b.k }"
            :aria-pressed="base === b.k"
            :disabled="b.k !== 'orig' && !urls[b.k]"
            @click="setBase(b.k)"
          >
            <i>{{ i + 1 }}</i>{{ b.t }}
          </button>
        </div>
        <label class="fv-chk" :class="{ off: !hasHeat }">
          <input v-model="heatOn" type="checkbox" :disabled="!hasHeat" @change="onHeatChange" />热力图
        </label>
        <label v-if="hasHeat && (heatOn || split)" class="fv-range">
          强度<input v-model.number="alpha" type="range" min="10" max="100" step="5" /><b>{{ alpha }}%</b>
        </label>
        <button type="button" class="fv-tog" :class="{ on: split }" :disabled="!hasHeat" @click="toggleSplit">并排对照</button>
        <span class="fv-sp"></span>
        <button type="button" class="fv-tog" :class="{ on: lensOn }" @click="toggleLens">放大镜</button>
        <label v-if="lensOn" class="fv-range sm">
          倍数<input v-model.number="zoom" type="range" min="1.5" max="5" step="0.5" /><b>{{ zoom }}×</b>
        </label>
        <button type="button" class="fv-tog" @click="saveView">保存当前视图</button>
      </div>
      <div class="fv-stage" :class="{ split: panes.length > 1 }" @pointerleave="lens = null">
        <div
          v-for="(layers, pi) in panes"
          :key="pi"
          :ref="(el) => setPane(el, pi)"
          class="fv-pane"
          @pointermove="onPointer"
          @pointerdown="onPointer"
        >
          <img v-for="(l, li) in layers" :key="li" :src="l.src" :style="{ opacity: l.opacity }" alt="" draggable="false" />
          <span v-if="panes.length > 1" class="fv-tag">{{ pi === 0 ? baseInfo.t : `${baseInfo.t} + 热力图` }}</span>
          <div v-if="lens && lens[pi]" class="fv-lens" :style="{ left: `${lens[pi].x}px`, top: `${lens[pi].y}px` }">
            <i
              v-for="(l, li) in layers"
              :key="li"
              :style="{
                backgroundImage: `url(${l.src})`,
                backgroundSize: `${lens[pi].bw}px ${lens[pi].bh}px`,
                backgroundPosition: `${lens[pi].bx}px ${lens[pi].by}px`,
                opacity: l.opacity,
              }"
            ></i>
          </div>
        </div>
        <div v-if="processing" class="fv-busy">正在生成增强与无赤光视图…</div>
      </div>
      <footer class="fv-foot">
        <span><b>{{ baseInfo.t }}</b>：{{ baseInfo.d }}</span>
        <span v-if="hasHeat && (heatOn || split)">热力图：暖色是模型做出这一分级时最关注的区域，帮助理解模型依据，不等于病灶边界。</span>
        <span v-if="demo && (heatOn || split)" class="warn">当前是演示模式：热力图是模拟的，不是模型输出。</span>
        <span v-if="lowRes" class="warn">这份报告只保存了缩略图，放大后会比较模糊；重新上传可以得到清晰大图。</span>
        <span v-if="failed" class="warn">{{ failed }}</span>
        <span class="dim">{{ natural.w > 1 ? `${natural.w}×${natural.h}` : "" }}</span>
      </footer>
    </div>
  </div>
</template>

<style scoped>
.fv { position: fixed; inset: 0; z-index: 1200; display: grid; place-items: center; padding: 20px; }
.fv-mask { position: absolute; inset: 0; background: rgba(6, 14, 26, 0.72); backdrop-filter: blur(3px); }
.fv-box { position: relative; width: min(1180px, 100%); height: min(860px, 100%); display: flex; flex-direction: column;
  border-radius: 18px; overflow: hidden; background: #f7fafd; box-shadow: 0 30px 80px -20px rgba(0, 0, 0, 0.55); }
.fv-head { display: flex; align-items: center; gap: 14px; padding: 14px 18px; border-bottom: 1px solid rgba(10, 31, 53, 0.08); }
.fv-title { display: flex; align-items: baseline; gap: 10px; min-width: 0; }
.fv-title b { font-size: 15px; color: #0a1f35; }
.fv-title span { font-size: 12px; color: #6b8299; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.fv-keys { margin-left: auto; font-size: 11px; color: #8a9db0; }
.fv-x { border: 0; background: rgba(10, 31, 53, 0.06); width: 30px; height: 30px; border-radius: 9px; cursor: pointer; font-size: 13px; color: #3a4e66; }
.fv-bar { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; padding: 10px 18px; border-bottom: 1px solid rgba(10, 31, 53, 0.06); }
.fv-seg { display: inline-flex; padding: 3px; border-radius: 11px; background: rgba(10, 31, 53, 0.06); }
.fv-seg button { border: 0; background: none; padding: 6px 13px; border-radius: 8px; font-family: inherit; font-size: 12.5px; font-weight: 600;
  color: #3a4e66; cursor: pointer; }
.fv-seg button i { font-style: normal; font-size: 10px; color: #9fb0c2; margin-right: 5px; }
.fv-seg button.on { background: #fff; color: #0a3d6b; box-shadow: 0 2px 6px rgba(10, 31, 53, 0.12); }
.fv-seg button:disabled { opacity: 0.4; cursor: not-allowed; }
.fv-chk, .fv-range { display: inline-flex; align-items: center; gap: 7px; font-size: 12px; font-weight: 600; color: #3a4e66; }
.fv-chk.off { opacity: 0.45; }
.fv-range input { width: 110px; }
.fv-range.sm input { width: 80px; }
.fv-range b { min-width: 34px; font-variant-numeric: tabular-nums; color: #0a3d6b; }
.fv-tog { border: 1px solid rgba(10, 31, 53, 0.12); background: #fff; padding: 6px 12px; border-radius: 9px; font-family: inherit;
  font-size: 12px; font-weight: 600; color: #3a4e66; cursor: pointer; }
.fv-tog.on { background: #0a3d6b; border-color: #0a3d6b; color: #fff; }
.fv-tog:disabled { opacity: 0.4; cursor: not-allowed; }
.fv-sp { flex: 1; }
.fv-stage { position: relative; flex: 1; min-height: 0; display: grid; grid-template-columns: 1fr; gap: 8px; padding: 10px;
  background: radial-gradient(circle at 50% 40%, #142233, #070d15 75%); }
.fv-stage.split { grid-template-columns: 1fr 1fr; }
.fv-pane { position: relative; min-width: 0; min-height: 0; overflow: hidden; border-radius: 12px; cursor: crosshair; touch-action: none; }
.fv-pane img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: contain; user-select: none; pointer-events: none; }
.fv-tag { position: absolute; top: 10px; left: 10px; z-index: 2; padding: 3px 9px; border-radius: 100px; font-size: 11px; font-weight: 600;
  color: #fff; background: rgba(0, 0, 0, 0.45); }
.fv-lens { position: absolute; z-index: 3; width: 180px; height: 180px; border-radius: 50%; overflow: hidden; pointer-events: none;
  background: #000; box-shadow: 0 0 0 2px rgba(255, 255, 255, 0.92), 0 12px 32px rgba(0, 0, 0, 0.55); }
.fv-lens i { position: absolute; inset: 0; background-repeat: no-repeat; }
.fv-busy { position: absolute; left: 50%; bottom: 18px; transform: translateX(-50%); padding: 6px 14px; border-radius: 100px;
  font-size: 12px; color: #dce8f4; background: rgba(0, 0, 0, 0.5); }
.fv-foot { display: flex; flex-wrap: wrap; gap: 6px 16px; padding: 10px 18px 12px; font-size: 11.5px; line-height: 1.6; color: #4d6075; }
.fv-foot b { color: #0a1f35; }
.fv-foot .warn { color: #a05a00; }
.fv-foot .dim { margin-left: auto; color: #9fb0c2; font-variant-numeric: tabular-nums; }
@media (max-width: 760px) {
  .fv { padding: 0; }
  .fv-box { height: 100%; border-radius: 0; }
  .fv-keys { display: none; }
  .fv-stage.split { grid-template-columns: 1fr; grid-template-rows: 1fr 1fr; }
}
</style>
