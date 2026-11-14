<script setup lang="ts">
/**
 * 使用指南：每类上传怎么做、传什么样的图、结果怎么看。
 * 页面上的按钮只做两件事：跳到对应页面，或把示例交给对应页面（示例图 / 示例文字，take 语义只用一次）。
 * 示例文字只填进输入框、不自动提交——是否调用大模型由用户决定。
 */
import { onBeforeUnmount, ref, watch } from "vue";
import { svg } from "@/lib/icons";
import { FUNDUS_SAMPLES } from "@/lib/fundusDemo";
import { LAB_SAMPLE } from "@/lib/labDemo";
import { AGENT_SAMPLES, SYMPTOM_SAMPLES } from "@/lib/guide";
import { useWorkbenchStore, type PageKey } from "@/stores/workbench";

const props = defineProps<{ active: boolean }>();
const emit = defineEmits<{ go: [page: PageKey] }>();
const wb = useWorkbenchStore();

const SAMPLE_A = FUNDUS_SAMPLES[0];
const SAMPLE_B = FUNDUS_SAMPLES[1];

const ICON = {
  agent:
    '<svg viewBox="0 0 24 24"><path d="M12 3.2l1.8 5 5 1.8-5 1.8-1.8 5-1.8-5-5-1.8 5-1.8z"/><path d="M18.6 14.6l.9 2.4 2.4.9-2.4.9-.9 2.4-.9-2.4-2.4-.9 2.4-.9z"/></svg>',
  multi:
    '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="8" height="8" rx="2"/><rect x="13" y="13" width="8" height="8" rx="2"/><path d="M15.5 3.5l5 5M20.5 3.5l-5 5M3.5 15.5l5 5M8.5 15.5l-5 5"/></svg>',
  history:
    '<svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 4v4h4"/><path d="M12 7.5v4.8l3 2"/></svg>',
};

const QUICK = [
  { id: "g-eye", icon: svg("eye"), t: "眼底筛查", s: "上传眼底彩照，得到 DR 分级与热力图" },
  { id: "g-lab", icon: svg("lab"), t: "化验单识别", s: "拍照上传化验单，异常指标标红并解释" },
  { id: "g-sx", icon: svg("chat"), t: "症状分诊", s: "描述哪里不舒服，给出科室与紧急程度" },
  { id: "g-agent", icon: ICON.agent, t: "Agent 助手", s: "一句话提问，自动调用合适的工具" },
];

/** 眼底上传演示：四个画面循环播放（流程示意，不是任何一张图的真实结果；真实流程用「示例图跑一遍」） */
const DEMO = [
  { t: "选择照片", d: "把眼底彩照拖进上传框，或点击选择文件；没有照片可以直接用示例 A。" },
  { t: "质量检查", d: "先检查清晰度、亮度与视野。失焦、过暗的照片会提示重拍，不硬给结论。" },
  { t: "模型分级", d: "本地 EfficientNet-B3 给出 DR 0–4 级各自的概率，边界病例按更严重的一级提醒。" },
  { t: "阅读报告", d: "热力图标出模型关注的区域，报告给出复查时间、建议科室和给医生的摘要；「专业阅片」可切换增强、无赤光视图并用放大镜查看。" },
];
const STEP_MS = 2800;
const step = ref(0);
const playing = ref(false);
let timer: ReturnType<typeof setInterval> | null = null;
const reduceMotion =
  typeof window !== "undefined" && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches;

function stop() {
  if (timer) clearInterval(timer);
  timer = null;
  playing.value = false;
}
function play() {
  stop();
  playing.value = true;
  timer = setInterval(() => {
    step.value = (step.value + 1) % DEMO.length;
  }, STEP_MS);
}
function pick(i: number) {
  stop();
  step.value = i;
}
function toggle() {
  if (playing.value) stop();
  else play();
}
watch(
  () => props.active,
  (on) => {
    if (on && !reduceMotion) play();
    else stop();
  },
  { immediate: true },
);
onBeforeUnmount(stop);

// 分级示意条：只表达「五个等级各有一个概率」，长度是画出来的示意，不是任何一张图的结果
const BARS = [
  { k: "0 级", w: 8 },
  { k: "1 级", w: 14 },
  { k: "2 级", w: 62 },
  { k: "3 级", w: 12 },
  { k: "4 级", w: 4 },
];
const FIVE = [
  { t: "部位", s: "哪里不舒服" },
  { t: "时间", s: "什么时候开始、持续多久" },
  { t: "程度", s: "轻重、是否越来越重" },
  { t: "伴随", s: "还有哪些不适" },
  { t: "既往", s: "慢病、用药、过敏" },
];
const MORE: { icon: string; t: string; s: string; p: PageKey }[] = [
  { icon: ICON.multi, t: "多模态综合分析", s: "把眼底、化验、症状记录放在一起看趋势与关联", p: "multi" },
  { icon: ICON.history, t: "历史记录", s: "每次筛查都保存在自己的账号里，可按类型筛选回看", p: "history" },
  { icon: svg("pin"), t: "附近医院", s: "按当前位置在地图上找医院，并按建议科室排序", p: "hospital" },
];

function to(page: PageKey) {
  emit("go", page);
}
function runEyeDemo() {
  wb.requestDemo("eye");
  to("eye");
}
function runPairDemo() {
  wb.request("eye", "pair");
  to("eye");
}
function openEyeUpload() {
  wb.request("eye", "fresh");
  to("eye");
}
function runLabDemo() {
  wb.requestDemo("lab");
  to("lab");
}
function fillSymptom(text: string) {
  wb.prefill("symptom", text);
  to("symptom");
}
function askAgent(text: string) {
  wb.prefill("chat", text);
  to("chat");
}

const root = ref<HTMLElement | null>(null);
function jump(id: string) {
  root.value?.querySelector(`#${id}`)?.scrollIntoView({ behavior: "smooth", block: "start" });
}
</script>

<template>
  <div ref="root" class="gd">
    <div class="page-t">
      <div>
        <h1 class="engrave">使用指南</h1>
        <p>三分钟上手：怎么传、传什么样的图、结果怎么看。下面的按钮会直接带你到对应页面。</p>
      </div>
    </div>

    <div class="gd-quick">
      <button v-for="q in QUICK" :key="q.id" type="button" class="gd-q plate" @click="jump(q.id)">
        <span class="ic-plate" v-html="q.icon"></span>
        <b>{{ q.t }}</b>
        <span>{{ q.s }}</span>
        <em>看步骤 ↓</em>
      </button>
    </div>

    <!-- 01 眼底 -->
    <section id="g-eye" class="gd-sec plate">
      <header class="gd-h">
        <span class="gd-no">01</span>
        <div>
          <h2>眼底图上传演示</h2>
          <p>从选图到看报告共四步。左边是流程动画，右边可以用示例图把真实流程跑一遍。</p>
        </div>
      </header>
      <div class="gd-eye">
        <div>
          <div class="gd-stage">
            <span class="gd-chip">流程示意 · 非真实结果</span>
            <Transition name="gd-fade" mode="out-in">
              <div :key="step" class="gd-scene">
                <div v-if="step === 0" class="gd-drop">
                  <svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12" /></svg>
                  <b>拖拽或点击上传</b>
                  <span>JPG / PNG · 不超过 20 MB</span>
                  <img class="gd-fly" :src="SAMPLE_A.url" alt="" />
                  <svg class="gd-cursor" viewBox="0 0 24 24"><path d="M5 3l14 8-6.2 1.6L9.6 19z" /></svg>
                </div>
                <div v-else-if="step === 1" class="gd-qc">
                  <div class="gd-eyeimg"><img :src="SAMPLE_A.url" alt="" /><i class="gd-scan"></i></div>
                  <ul>
                    <li style="--d: 0.2s">清晰度<b>✓</b></li>
                    <li style="--d: 0.6s">亮度<b>✓</b></li>
                    <li style="--d: 1s">视野完整<b>✓</b></li>
                  </ul>
                </div>
                <div v-else-if="step === 2" class="gd-bars">
                  <div class="gd-model">EfficientNet-B3 · 本地推理</div>
                  <div
                    v-for="(b, i) in BARS"
                    :key="b.k"
                    class="gd-bar"
                    :style="{ '--w': b.w + '%', '--d': i * 0.12 + 's' }"
                  >
                    <span>{{ b.k }}</span><i></i>
                  </div>
                </div>
                <div v-else class="gd-rep">
                  <div class="gd-eyeimg"><img :src="SAMPLE_A.url" alt="" /><i class="gd-heat"></i></div>
                  <div class="gd-rep-lines">
                    <p><b>DR 分级</b><span>等级与置信度</span></p>
                    <p><b>热力图</b><span>模型关注的区域</span></p>
                    <p><b>复查建议</b><span>多久复查、挂什么科</span></p>
                    <p><b>给医生的摘要</b><span>就诊时直接出示</span></p>
                  </div>
                </div>
              </div>
            </Transition>
          </div>
          <div class="gd-prog" aria-hidden="true">
            <i v-for="(s, i) in DEMO" :key="s.t" :class="{ on: i === step, done: i < step, run: playing && i === step }"></i>
          </div>
        </div>
        <div class="gd-eye-side">
          <ol class="gd-steps">
            <li v-for="(s, i) in DEMO" :key="s.t" :class="{ on: i === step }" @click="pick(i)">
              <span class="n">{{ i + 1 }}</span>
              <div><b>{{ s.t }}</b><p>{{ s.d }}</p></div>
            </li>
          </ol>
          <div class="gd-acts">
            <button type="button" class="gd-btn" @click="runEyeDemo">▶ 用示例图跑一遍真实流程</button>
            <button type="button" class="gd-btn ghost" @click="openEyeUpload">上传我的眼底照片</button>
            <button type="button" class="gd-btn ghost" @click="runPairDemo">双眼筛查示例</button>
            <button type="button" class="gd-link" @click="toggle">{{ playing ? "暂停动画" : "播放动画" }}</button>
          </div>
        </div>
      </div>
      <div class="gd-tips">
        <div class="gd-req">
          <h4>什么样的照片能用</h4>
          <ul>
            <li>眼底照相机拍的<b>眼底彩照</b>：圆形视野，能看到视盘和黄斑</li>
            <li>对焦清晰、亮度均匀；一次上传一只眼</li>
            <li>JPG 或 PNG，不超过 20 MB；手机翻拍屏幕容易反光、出摩尔纹</li>
            <li>两只眼都拍了？选「双眼筛查」，系统按较重的一只眼给建议</li>
          </ul>
        </div>
        <figure class="gd-cmp ok">
          <img :src="SAMPLE_A.url" alt="示例 A：清晰的眼底彩照" />
          <figcaption><b>示例 A · 可评估</b>视野完整、对焦清晰</figcaption>
        </figure>
        <figure class="gd-cmp bad">
          <img :src="SAMPLE_B.url" alt="示例 B：失焦的眼底照片" />
          <figcaption><b>示例 B · 建议重拍</b>失焦模糊，系统会提示重拍</figcaption>
        </figure>
      </div>
    </section>

    <!-- 02 化验单 -->
    <section id="g-lab" class="gd-sec plate">
      <header class="gd-h">
        <span class="gd-no">02</span>
        <div>
          <h2>化验单上传</h2>
          <p>拍清楚整张单子，系统识别出每一项指标，异常的标红并用大白话解释。</p>
        </div>
      </header>
      <div class="gd-two">
        <figure class="gd-labimg">
          <img :src="LAB_SAMPLE.url" :alt="LAB_SAMPLE.title" />
          <figcaption>{{ LAB_SAMPLE.title }}：{{ LAB_SAMPLE.note }}</figcaption>
        </figure>
        <div>
          <ol class="gd-mini">
            <li><b>拍照</b>化验单平放，四个角都拍进来；光线均匀，不要有阴影和反光。</li>
            <li><b>上传</b>进入「化验单」页，拖入或点击上传 JPG / PNG。</li>
            <li><b>核对</b>结果按「指标、结果、参考范围、状态」列出，请对照原单核对数字与单位。</li>
          </ol>
          <p class="gd-note">识别调用在线视觉模型，需要联网，约 10～30 秒。</p>
          <div class="gd-acts">
            <button type="button" class="gd-btn" @click="runLabDemo">用示例化验单体验</button>
            <button type="button" class="gd-btn ghost" @click="to('lab')">去上传化验单</button>
          </div>
        </div>
      </div>
    </section>

    <!-- 03 症状 -->
    <section id="g-sx" class="gd-sec plate">
      <header class="gd-h">
        <span class="gd-no">03</span>
        <div>
          <h2>症状描述</h2>
          <p>说清楚下面五件事，分诊会更准。点示例会填进输入框，由你决定是否提交。</p>
        </div>
      </header>
      <div class="gd-five">
        <div v-for="f in FIVE" :key="f.t"><b>{{ f.t }}</b><span>{{ f.s }}</span></div>
      </div>
      <div class="gd-chips">
        <button
          v-for="s in SYMPTOM_SAMPLES"
          :key="s.label"
          type="button"
          :class="{ red: s.red }"
          @click="fillSymptom(s.text)"
        >
          <b>{{ s.label }}</b>{{ s.text }}
        </button>
      </div>
      <p class="gd-note">命中胸痛、呼吸困难、突然看不清等急症信号时，系统直接给出急症指引并列出规则依据，这一步不调用大模型。</p>
    </section>

    <!-- 04 Agent -->
    <section id="g-agent" class="gd-sec plate">
      <header class="gd-h">
        <span class="gd-no">04</span>
        <div>
          <h2>Agent 助手</h2>
          <p>像聊天一样提问；也可以在对话里直接上传图片，系统会自己判断是眼底照片还是化验单。</p>
        </div>
      </header>
      <div class="gd-chips">
        <button v-for="q in AGENT_SAMPLES" :key="q" type="button" @click="askAgent(q)"><b>问一问</b>{{ q }}</button>
      </div>
      <p class="gd-note">回答句末的 [1]、[2] 是知识库引用，点开可以看到来源与核实链接。</p>
    </section>

    <!-- 05 结果与就医 -->
    <section class="gd-sec plate">
      <header class="gd-h">
        <span class="gd-no">05</span>
        <div>
          <h2>看结果与就医</h2>
          <p>做过的筛查都保存在自己的账号里：可以放在一起看，也可以直接找医院。</p>
        </div>
      </header>
      <div class="gd-more">
        <button v-for="m in MORE" :key="m.p" type="button" class="plate" @click="to(m.p)">
          <span class="ic-plate" v-html="m.icon"></span>
          <span><b>{{ m.t }}</b><span>{{ m.s }}</span></span>
        </button>
      </div>
    </section>

    <div class="gd-safe">
      <b>安全提示</b>出现胸痛、呼吸困难、突然看不见、一侧肢体无力等情况，请立即拨打 120。本系统只做筛查参考，不能替代医生诊断。
    </div>
  </div>
</template>

<style scoped>
.gd { display: flex; flex-direction: column; gap: 16px; padding-bottom: 24px; }
.gd-quick { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 12px; }
.gd-q { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; padding: 16px; border: 0; border-radius: 15px;
  text-align: left; cursor: pointer; font-family: inherit; color: var(--ink); transition: transform 0.22s; }
.gd-q:hover { transform: translateY(-2px); }
.gd-q .ic-plate { width: 36px; height: 36px; border-radius: 11px; margin-bottom: 8px; }
.gd-q b { font-size: 13.5px; font-weight: 600; }
.gd-q span { font-size: 11.5px; color: var(--muted); line-height: 1.6; }
.gd-q em { margin-top: 6px; font-style: normal; font-size: 11px; font-weight: 600; color: var(--blue); }

.gd-sec { padding: 20px 20px 18px; scroll-margin-top: 16px; }
.gd-h { display: flex; gap: 14px; align-items: flex-start; margin-bottom: 16px; }
.gd-no { flex: none; font: 700 12px/1 "SF Mono", Menlo, monospace; letter-spacing: 0.04em; color: var(--blue);
  background: rgba(10, 132, 255, 0.08); border-radius: 8px; padding: 7px 8px; }
.gd-h h2 { margin: 0 0 4px; font-size: 16px; font-weight: 700; letter-spacing: -0.01em; color: var(--ink); }
.gd-h p { margin: 0; font-size: 12px; color: var(--muted); line-height: 1.7; }

/* ---- 眼底演示舞台 ---- */
.gd-eye { display: grid; grid-template-columns: minmax(0, 1.15fr) minmax(0, 1fr); gap: 22px; align-items: start; }
.gd-stage { position: relative; height: 280px; border-radius: 16px; overflow: hidden;
  background: radial-gradient(120% 90% at 20% 0%, #f5faff 0%, #e4eff9 55%, #d3e4f4 100%);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.85), inset 0 -24px 40px -30px rgba(40, 90, 140, 0.3); }
.gd-chip { position: absolute; top: 12px; left: 12px; z-index: 2; font-size: 10.5px; font-weight: 600; letter-spacing: 0.06em;
  color: #4a6a88; background: rgba(255, 255, 255, 0.78); border: 1px solid rgba(255, 255, 255, 0.9); border-radius: 100px; padding: 4px 10px; }
.gd-scene { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; padding: 40px 24px 20px; }

.gd-drop { position: relative; width: 78%; height: 78%; border: 2px dashed rgba(70, 120, 170, 0.45); border-radius: 16px;
  background: rgba(255, 255, 255, 0.55); display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 6px; color: #3d6285; }
.gd-drop > svg:first-child { width: 30px; height: 30px; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round;
  stroke-linejoin: round; margin-bottom: 4px; }
.gd-drop > svg:first-child, .gd-drop > b, .gd-drop > span { animation: gd-dim 1.9s ease both; }
.gd-drop b { font-size: 13px; }
.gd-drop span { font-size: 11px; color: var(--muted); }
.gd-fly { position: absolute; left: 50%; top: 50%; width: 84px; height: 84px; border-radius: 50%; object-fit: cover;
  box-shadow: 0 12px 26px -12px rgba(20, 50, 90, 0.6), 0 0 0 3px rgba(255, 255, 255, 0.85);
  transform: translate(-50%, -50%); animation: gd-fly 1.9s cubic-bezier(0.25, 0.8, 0.3, 1) both; }
.gd-cursor { position: absolute; left: 50%; top: 50%; width: 22px; height: 22px; margin: 22px 0 0 26px; fill: #fff; stroke: #24425e;
  stroke-width: 1.4; stroke-linejoin: round; animation: gd-fly-c 1.9s cubic-bezier(0.25, 0.8, 0.3, 1) both; }
@keyframes gd-fly {
  from { left: 108%; top: 112%; opacity: 0; transform: translate(-50%, -50%) scale(0.85) rotate(10deg); }
  25% { opacity: 1; }
  to { left: 50%; top: 50%; opacity: 1; transform: translate(-50%, -50%) scale(1) rotate(0); }
}
@keyframes gd-fly-c {
  from { left: 108%; top: 112%; opacity: 0; }
  25% { opacity: 1; }
  80% { left: 50%; top: 50%; opacity: 1; }
  to { left: 50%; top: 50%; opacity: 0; }
}
@keyframes gd-dim { 0%, 55% { opacity: 1; } 100% { opacity: 0.18; } }

.gd-qc { display: flex; align-items: center; gap: 28px; }
.gd-eyeimg { position: relative; width: 150px; height: 150px; flex: none; border-radius: 50%; overflow: hidden;
  box-shadow: 0 14px 30px -14px rgba(20, 50, 90, 0.6), 0 0 0 4px rgba(255, 255, 255, 0.75); }
.gd-eyeimg img { width: 100%; height: 100%; object-fit: cover; display: block; }
.gd-scan { position: absolute; left: 0; right: 0; top: -30%; height: 30%;
  background: linear-gradient(180deg, rgba(120, 200, 255, 0) 0%, rgba(120, 200, 255, 0.5) 85%, rgba(255, 255, 255, 0.9) 100%);
  animation: gd-scan 1.6s ease-in-out infinite; }
@keyframes gd-scan { from { top: -30%; } to { top: 100%; } }
.gd-qc ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; }
.gd-qc li { display: flex; align-items: center; justify-content: space-between; gap: 18px; min-width: 150px; padding: 9px 12px;
  border-radius: 10px; background: rgba(255, 255, 255, 0.8); font-size: 12.5px; font-weight: 600; color: var(--ink2);
  opacity: 0; animation: gd-in 0.45s ease forwards; animation-delay: var(--d); }
.gd-qc li b { color: #1f9d55; }
@keyframes gd-in { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: none; } }

.gd-bars { width: 80%; display: flex; flex-direction: column; gap: 9px; }
.gd-model { align-self: flex-start; font-size: 11px; font-weight: 600; color: #3d6285; background: rgba(255, 255, 255, 0.78);
  border-radius: 8px; padding: 4px 9px; margin-bottom: 4px; }
.gd-bar { display: grid; grid-template-columns: 42px 1fr; align-items: center; gap: 10px; font-size: 11.5px; font-weight: 600; color: var(--ink2); }
.gd-bar i { position: relative; height: 12px; border-radius: 6px; overflow: hidden; background: rgba(255, 255, 255, 0.7); }
.gd-bar i::after { content: ""; position: absolute; left: 0; top: 0; bottom: 0; width: var(--w); border-radius: 6px;
  background: linear-gradient(90deg, #4f8ec2, #2a5d8f); transform-origin: left; animation: gd-grow 0.9s cubic-bezier(0.3, 0.8, 0.3, 1) both;
  animation-delay: var(--d); }
@keyframes gd-grow { from { transform: scaleX(0); } to { transform: scaleX(1); } }

.gd-rep { display: flex; align-items: center; gap: 24px; }
.gd-heat { position: absolute; inset: 0; mix-blend-mode: screen; animation: gd-in 0.8s ease both;
  background: radial-gradient(26% 22% at 58% 46%, rgba(255, 70, 40, 0.8), rgba(255, 190, 60, 0.45) 55%, rgba(80, 160, 255, 0) 100%),
    radial-gradient(16% 14% at 36% 62%, rgba(255, 170, 40, 0.6), rgba(255, 200, 60, 0) 100%); }
.gd-rep-lines { display: flex; flex-direction: column; gap: 8px; }
.gd-rep-lines p { margin: 0; display: flex; flex-direction: column; padding: 7px 12px; border-radius: 10px;
  background: rgba(255, 255, 255, 0.8); opacity: 0; animation: gd-in 0.45s ease forwards; }
.gd-rep-lines p:nth-child(2) { animation-delay: 0.15s; }
.gd-rep-lines p:nth-child(3) { animation-delay: 0.3s; }
.gd-rep-lines p:nth-child(4) { animation-delay: 0.45s; }
.gd-rep-lines b { font-size: 12px; color: var(--ink); }
.gd-rep-lines span { font-size: 10.5px; color: var(--muted); }

.gd-prog { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; margin-top: 10px; }
.gd-prog i { position: relative; height: 4px; border-radius: 2px; overflow: hidden; background: rgba(70, 120, 170, 0.18); }
.gd-prog i.done::after, .gd-prog i.on::after { content: ""; position: absolute; inset: 0; background: var(--blue); transform-origin: left; }
.gd-prog i.run::after { animation: gd-grow 2.8s linear both; }

.gd-steps { list-style: none; margin: 0 0 14px; padding: 0; display: flex; flex-direction: column; gap: 4px; }
.gd-steps li { display: flex; gap: 12px; padding: 10px 12px; border-radius: 12px; cursor: pointer; transition: background 0.2s; }
.gd-steps li:hover { background: rgba(10, 132, 255, 0.05); }
.gd-steps li.on { background: rgba(10, 132, 255, 0.09); }
.gd-steps .n { flex: none; width: 24px; height: 24px; border-radius: 50%; display: grid; place-items: center; font-size: 12px;
  font-weight: 700; color: var(--blue); background: rgba(10, 132, 255, 0.1); transition: all 0.2s; }
.gd-steps li.on .n { color: #fff; background: var(--blue); }
.gd-steps b { font-size: 13px; color: var(--ink); }
.gd-steps p { margin: 2px 0 0; font-size: 11.5px; color: var(--muted); line-height: 1.65; }

.gd-acts { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
.gd-btn { border: 0; border-radius: 11px; padding: 9px 16px; font-family: inherit; font-size: 12.5px; font-weight: 600; color: #fff;
  cursor: pointer; background: linear-gradient(135deg, #2a5d8f, #4f8ec2); box-shadow: 0 8px 18px -10px rgba(30, 80, 140, 0.7);
  transition: transform 0.2s; }
.gd-btn:hover { transform: translateY(-1px); }
.gd-btn.ghost { color: var(--blue-d); background: rgba(255, 255, 255, 0.82); box-shadow: inset 0 0 0 1px rgba(70, 120, 170, 0.25); }
.gd-link { border: 0; background: none; font-family: inherit; font-size: 12px; color: var(--muted); cursor: pointer;
  text-decoration: underline; text-underline-offset: 3px; }

.gd-tips { display: grid; grid-template-columns: minmax(0, 1.6fr) minmax(0, 1fr) minmax(0, 1fr); gap: 14px; margin-top: 18px;
  padding-top: 16px; border-top: 0.5px solid var(--line2); align-items: center; }
.gd-req h4 { margin: 0 0 6px; font-size: 13px; color: var(--ink); }
.gd-req ul { margin: 0; padding-left: 18px; font-size: 12px; color: var(--ink2); line-height: 1.9; }
.gd-cmp { margin: 0; display: flex; gap: 12px; align-items: center; padding: 10px; border-radius: 12px; background: rgba(255, 255, 255, 0.6); }
.gd-cmp img { width: 64px; height: 64px; flex: none; border-radius: 50%; object-fit: cover; }
.gd-cmp figcaption { font-size: 11.5px; color: var(--muted); line-height: 1.6; }
.gd-cmp figcaption b { display: block; font-size: 12.5px; }
.gd-cmp.ok b { color: #1f8a4c; }
.gd-cmp.bad b { color: #b4532a; }

.gd-two { display: grid; grid-template-columns: 220px minmax(0, 1fr); gap: 22px; align-items: start; }
.gd-labimg { margin: 0; }
.gd-labimg img { display: block; width: 100%; border-radius: 12px; background: #fff; box-shadow: 0 12px 28px -16px rgba(20, 50, 90, 0.55); }
.gd-labimg figcaption { margin-top: 8px; font-size: 11px; color: var(--muted); line-height: 1.6; }
.gd-mini { list-style: none; margin: 0 0 6px; padding: 0; counter-reset: gm; display: flex; flex-direction: column; gap: 10px; }
.gd-mini li { counter-increment: gm; position: relative; padding-left: 34px; font-size: 12.5px; color: var(--ink2); line-height: 1.7; }
.gd-mini li::before { content: counter(gm); position: absolute; left: 0; top: 1px; width: 22px; height: 22px; border-radius: 50%;
  display: grid; place-items: center; font-size: 11.5px; font-weight: 700; color: var(--blue); background: rgba(10, 132, 255, 0.1); }
.gd-mini b { margin-right: 6px; color: var(--ink); }
.gd-note { margin: 8px 0 12px; font-size: 11.5px; color: var(--muted); line-height: 1.7; }

.gd-five { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; margin-bottom: 14px; }
.gd-five div { display: flex; flex-direction: column; gap: 3px; padding: 12px; border-radius: 12px; background: rgba(10, 132, 255, 0.05); }
.gd-five b { font-size: 13px; color: var(--blue-d); }
.gd-five span { font-size: 11px; color: var(--muted); }
.gd-chips { display: flex; flex-direction: column; gap: 8px; }
.gd-chips button { text-align: left; border: 0; cursor: pointer; padding: 10px 14px; border-radius: 12px; background: rgba(255, 255, 255, 0.72);
  box-shadow: inset 0 0 0 1px rgba(70, 120, 170, 0.18); font-family: inherit; font-size: 12.5px; color: var(--ink2); line-height: 1.6;
  transition: background 0.2s, box-shadow 0.2s; }
.gd-chips button:hover { background: #fff; box-shadow: inset 0 0 0 1px rgba(70, 120, 170, 0.4); }
.gd-chips button b { display: inline-block; margin-right: 10px; padding: 2px 8px; border-radius: 6px; font-size: 11px; color: var(--blue);
  background: rgba(10, 132, 255, 0.08); }
.gd-chips button.red b { color: #b42318; background: rgba(217, 45, 32, 0.08); }

.gd-more { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
.gd-more button { display: flex; gap: 12px; align-items: flex-start; padding: 14px; border: 0; border-radius: 14px; cursor: pointer;
  text-align: left; font-family: inherit; transition: transform 0.22s; }
.gd-more button:hover { transform: translateY(-2px); }
.gd-more .ic-plate { width: 34px; height: 34px; flex: none; border-radius: 10px; }
.gd-more b { display: block; margin-bottom: 3px; font-size: 13px; color: var(--ink); }
.gd-more span span { font-size: 11.5px; color: var(--muted); line-height: 1.6; }

.gd-safe { padding: 12px 16px; border-radius: 12px; background: rgba(255, 236, 232, 0.78); box-shadow: inset 0 0 0 1px rgba(217, 80, 64, 0.18);
  font-size: 12px; color: #8a3328; line-height: 1.7; }
.gd-safe b { margin-right: 8px; color: #a8241d; }

.gd-fade-enter-active, .gd-fade-leave-active { transition: opacity 0.25s ease; }
.gd-fade-enter-from, .gd-fade-leave-to { opacity: 0; }

@media (max-width: 1100px) {
  .gd-quick { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .gd-eye { grid-template-columns: 1fr; }
  .gd-tips { grid-template-columns: 1fr 1fr; }
  .gd-req { grid-column: 1 / -1; }
  .gd-five { grid-template-columns: repeat(3, minmax(0, 1fr)); }
}
@media (max-width: 640px) {
  .gd-quick, .gd-more, .gd-two, .gd-tips { grid-template-columns: 1fr; }
  .gd-five { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .gd-stage { height: 240px; }
  .gd-eyeimg { width: 120px; height: 120px; }
}
@media (prefers-reduced-motion: reduce) {
  .gd-fly, .gd-cursor, .gd-scan, .gd-qc li, .gd-bar i::after, .gd-rep-lines p, .gd-heat, .gd-prog i.run::after,
  .gd-drop > svg:first-child, .gd-drop > b, .gd-drop > span { animation: none !important; opacity: 1; }
  .gd-cursor { display: none; }
}
</style>
