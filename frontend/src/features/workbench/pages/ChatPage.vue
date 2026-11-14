<script setup lang="ts">
/**
 * Agent 助手：SSE 流式对话（原生 Function Calling）+ 右侧实时扫描面板 + 决策轨迹。
 * 版式沿用 app.html 的 chat 布局；事件流由 useAgentStream 解析后落到响应式状态。
 */
import { computed, nextTick, onMounted, onBeforeUnmount, ref, watch } from "vue";
import { useAuthStore } from "@/stores/auth";
import { useRecordsStore } from "@/stores/records";
import { useAgentStream, type AgentEvent } from "@/composables/useAgentStream";
import { api } from "@/lib/api";
import { esc } from "@/lib/icons";
import { fundusPairStore, fundusStore, normalizeFundus, makeThumb, makeView } from "@/lib/fundus";
import { formatChatText, splitFinal, reportActs, AGENT_TOOL_DESC } from "@/lib/agentReport";
import { planLine, reflectTrace, repairTrace } from "@/lib/agentEvents";
import type { TraceItem, ToolState } from "@/lib/agentEvents";
import { liveCheckLabel, useHealth } from "@/composables/useHealth";
import AgentTrace from "../components/AgentTrace.vue";
import type { ReportAct } from "@/lib/agentReport";
import { labReportStore } from "@/lib/labReport";
import { useWorkbenchStore, type PageKey } from "@/stores/workbench";

const props = defineProps<{ active: boolean }>();
const emit = defineEmits<{ go: [page: PageKey, dept?: string] }>();

const auth = useAuthStore();
const rec = useRecordsStore();
const { busy, phase, stream, reset } = useAgentStream();

/* ---------------- 消息流 ---------------- */
interface Msg {
  id: number;
  role: "me" | "ai";
  kind: "bubble" | "photo" | "think" | "ask" | "typing";
  html?: string;
  text?: string;
  src?: string;
  /** 流式累积文本（收到 token 后持续追加） */
  streamText?: string;
  chips?: string[];
  hint?: string;
  answered?: boolean;
  badge?: string;
  starter?: boolean;
  /** 报告底部的动作按钮，渲染在气泡外（与旧版 .acts 位置一致） */
  acts?: ReportAct[];
}
let seq = 0;
const messages = ref<Msg[]>([]);
const streamEl = ref<HTMLDivElement | null>(null);
const input = ref("");
const fileEl = ref<HTMLInputElement | null>(null);
const textEl = ref<HTMLTextAreaElement | null>(null);
const pendingFile = ref<File | null>(null);
const pendingSrc = ref("");
const listening = ref(false);

/* ---------------- 右侧扫描面板 ---------------- */
const DEFAULT_STEPS = ["图像预处理", "质量检查", "模型推理", "热力图", "详细报告"];
const scan = ref({
  badge: "STANDBY",
  running: false,
  split: false,
  retina: "",
  hud: "DR 0–4",
  progress: 0,
  steps: DEFAULT_STEPS.map((t) => ({ text: t, state: "todo" as "todo" | "run" | "done" })),
  elapsed: "–",
  state: "等待上传",
  result: null as null | { v: string; s: string },
  lesions: [] as { type: string; count: number }[],
  model: "EfficientNet-B3",
  trainK: "训练集",
  trainV: "DR 合并集 5,096 张",
  aucK: "QWK",
  aucV: "0.896",
  live: "未实测",
  liveOk: null as boolean | null,
});

/* ---------------- 决策轨迹 ---------------- */
const trace = ref<TraceItem[]>([]);
const tools = ref<ToolState[]>([]);
let traceSeq = 0;

const TOOL_DESC = AGENT_TOOL_DESC;
let sendVersion = 0;
let toolNo = 0;
let panelTimer: number | undefined;

function stopPanelTimer() {
  window.clearInterval(panelTimer);
  panelTimer = undefined;
}
onBeforeUnmount(stopPanelTimer);

function pushTrace(type: TraceItem["type"], icon: string, label: string, text: string) {
  trace.value.push({ id: ++traceSeq, type, icon, label, text });
  if (trace.value.length > 14) trace.value.shift();
}

/* ---------------- 工具函数 ---------------- */
async function scrollBottom() {
  await nextTick();
  const el = streamEl.value;
  if (el) el.scrollTop = el.scrollHeight;
}

function pushMsg(m: Omit<Msg, "id">) {
  const msg: Msg = { ...m, id: ++seq };
  messages.value.push(msg);
  void scrollBottom();
  return msg;
}

const aiAvatar = computed(() => "AI");

function welcome() {
  messages.value = [];
  trace.value = [];
  tools.value = Object.entries(TOOL_DESC).map(([name, desc]) => ({ name, desc, called: false }));
  resetPanel();
  pushMsg({
    role: "ai",
    kind: "bubble",
    starter: true,
    html:
      "<p>你好，我是 <strong>医导</strong>——你的 AI 分诊导航助手。</p>" +
      "<p>上传一张眼底彩照或化验单，右侧面板会展示<strong>实时扫描过程</strong>，完成后我将给出详细报告与就诊建议；也可以直接描述症状。</p>" +
      '<div class="chat-upload-cta" id="welcomeUploadCta" data-upload="true" role="button" tabindex="0"><div class="icon"><svg viewBox="0 0 24 24"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M17 8l-5-5-5 5M12 3v12"/></svg></div><div class="t"><b>点击上传图片开始扫描</b><span>支持眼底彩照 · 化验单 · 检查报告</span></div></div>',
  });
}

function resetPanel() {
  stopPanelTimer();
  scan.value = {
    ...scan.value,
    badge: "STANDBY",
    running: false,
    split: false,
    retina: "",
    hud: "DR 0–4",
    progress: 0,
    steps: DEFAULT_STEPS.map((t) => ({ text: t, state: "todo" })),
    elapsed: "–",
    state: "等待上传",
    result: null,
    lesions: [],
  };
}

/** Progress follows actual tool events; elapsed time stops on every terminal state. */
function runPanel(img: string, hud: string) {
  stopPanelTimer();
  scan.value.running = true;
  scan.value.badge = "SCANNING";
  scan.value.split = !!img;
  scan.value.retina = img;
  scan.value.hud = hud;
  scan.value.result = null;
  scan.value.lesions = [];
  scan.value.steps = ["决策规划", "工具调用", "结果观察", "风险测算", "综合报告"]
    .map((text, i) => ({ text, state: i === 0 ? "run" : "todo" }));
  scan.value.progress = 5;
  scan.value.state = "处理中…";
  const t0 = Date.now();
  scan.value.elapsed = "0.0s";
  panelTimer = window.setInterval(() => {
    scan.value.elapsed = `${((Date.now() - t0) / 1000).toFixed(1)}s`;
  }, 100);
}

function advancePanel(index: number) {
  scan.value.steps = scan.value.steps.map((step, i) => ({
    ...step, state: i < index ? "done" : i === index ? "run" : "todo",
  }));
  scan.value.progress = Math.max(scan.value.progress, Math.round((index + 0.4) / 5 * 100));
}

function finishPanel(level: number | null, urgency: string, lesions: { type: string; count: number }[]) {
  stopPanelTimer();
  scan.value.split = false;
  scan.value.steps = scan.value.steps.map((s) => ({ ...s, state: "done" }));
  scan.value.progress = 100;
  scan.value.badge = "DONE";
  scan.value.running = false;
  scan.value.state = "分析完成";
  scan.value.lesions = lesions;
  scan.value.result = {
    v: level != null ? `DR ${level} 级` : urgency === "red" ? "建议尽快就诊" : "已完成分析",
    s: "可在左侧对话中查看完整解读",
  };
}

function failPanel(msg: string) {
  stopPanelTimer();
  scan.value.split = false;
  scan.value.running = false;
  scan.value.badge = "ERROR";
  scan.value.state = msg.slice(0, 24);
}

/* ---------------- 发送 ---------------- */
interface ReplyContext {
  replyId?: number;
  imageSrc: string;
  fileName: string;
}

function setReply(
  typing: Msg,
  context: ReplyContext,
  html: string,
  streamText?: string,
  acts?: ReportAct[],
) {
  const id = context.replyId ?? typing.id;
  const index = messages.value.findIndex((message) => message.id === id);
  const message = { role: "ai" as const, kind: "bubble" as const, html, streamText, acts };
  if (index >= 0) {
    messages.value[index] = { ...message, id };
    context.replyId = id;
  } else {
    context.replyId = pushMsg(message).id;
  }
}

async function send(text?: string, file?: File | null) {
  const content = (text ?? input.value).trim();
  const upload = file ?? pendingFile.value;
  if ((!content && !upload) || busy.value) return;
  const version = ++sendVersion;
  toolNo = 0;
  input.value = "";
  pendingFile.value = null;
  const context: ReplyContext = { imageSrc: "", fileName: upload?.name || "" };
  if (content) pushMsg({ role: "me", kind: "bubble", html: `<p>${esc(content).replace(/\n/g, "<br>")}</p>` });
  if (upload) {
    context.imageSrc = pendingSrc.value || (await fileToDataUrl(upload));
    if (version !== sendVersion) return;
    pendingSrc.value = "";
    pushMsg({ role: "me", kind: "photo", src: context.imageSrc, badge: "SCANNING" });
  }
  runPanel(context.imageSrc, upload ? "多模态分析" : "分诊分析");
  const typing = pushMsg({ role: "ai", kind: "typing" });
  await stream(content, upload ?? null, (event: AgentEvent) => {
    if (version === sendVersion) handleEvent(event, typing, context);
  });
  if (version !== sendVersion) return;
  const index = messages.value.findIndex((message) => message.id === typing.id);
  if (index >= 0 && messages.value[index].kind === "typing") removeMsg(typing.id);
  stopPanelTimer();
  rec.refreshSoon();
}

function handleEvent(ev: AgentEvent, typing: Msg, context: ReplyContext) {
  switch (ev.event) {
    case "plan": {
      // 规则规划（source=rule）：展示预期工作流。插在「正在输入」之前而不是替换它，
      // 否则计划一出现、等待模型决策的这段时间就没有任何忙碌提示。
      const line = planLine(ev.data);
      if (!line) break;
      const planMsg: Msg = {
        id: ++seq,
        role: "ai",
        kind: "think",
        html: `<div class="step-lbl">Plan · 任务规划（规则）</div><div class="reasoning">${esc(line)}</div>`,
      };
      const at = messages.value.findIndex((m) => m.id === typing.id);
      messages.value.splice(at >= 0 ? at : messages.value.length, 0, planMsg);
      pushTrace("plan", "P", "Plan", line);
      break;
    }
    case "reflect": {
      pushTrace("reflect", "R", "Reflect", reflectTrace(ev.data).text);
      break;
    }
    case "repair": {
      const r = repairTrace(ev.data);
      pushTrace("repair", "F", "Repair", r.text);
      if (!r.done) scan.value.state = "自检发现问题，正在修正…";
      break;
    }
    case "thought": {
      removeMsg(typing.id);
      advancePanel(0);
      const step = Number(ev.data.step ?? 0);
      const text = String(ev.data.text ?? "");
      pushMsg({
        role: "ai",
        kind: "think",
        html: `<div class="step-lbl">Thought · 第 ${step} 步</div><div class="reasoning">${esc(text)}</div>`,
      });
      pushTrace("think", String(step), "Thought", text);
      break;
    }
    case "tool_start": {
      const name = String(ev.data.name ?? "");
      advancePanel(String(ev.data.name) === "calc_risk" ? 3 : 1);
      const t = tools.value.find((x) => x.name === name);
      if (t) t.called = true;
      pushTrace("act", name.slice(0, 2).toUpperCase(), "Action", name);
      break;
    }
    case "tool_result": {
      const name = String(ev.data.name ?? "");
      advancePanel(2);
      // 与旧版 addToolCard 一致：序号徽标 + 结果截断 160 字（纯文本，靠 pre-wrap 保留换行）
      const result = String(ev.data.result ?? "").slice(0, 160);
      toolNo += 1;
      pushMsg({ role: "ai", kind: "bubble", html:
        `<div class="tool-card"><div class="call"><span class="tool-ic">${toolNo}</span>${esc(TOOL_DESC[name] || name)}</div>` +
        `<div class="result${ev.data.warn ? " warn" : ""}"><span class="ck">✓</span> ${esc(result)}</div></div>` });
      pushTrace("obs", "✓", "Observation", `${name} → ${result}`);
      break;
    }
    case "token": {
      advancePanel(4);
      const previous = messages.value.find((message) => message.id === context.replyId)?.streamText || "";
      const text = previous + String(ev.data.text ?? "");
      setReply(typing, context, formatChatText(text), text);
      break;
    }
    case "ask": {
      stopPanelTimer();
      scan.value.running = false;
      scan.value.split = false;
      scan.value.badge = "WAIT INFO";
      scan.value.state = "等待补充信息";
      const tool = tools.value.find((item) => item.name === "ask_user");
      if (tool) tool.called = true;
      removeMsg(typing.id);
      pushMsg({
        role: "ai",
        kind: "ask",
        html: `<p>为了判断更准，先确认一个关键信息（不想答可以跳过）：</p>
          <div class="ask-card"><div class="q-num">补充信息</div>
          <div class="q-tx">${esc(ev.data.question ?? "")}</div>
          ${ev.data.hint ? `<div class="q-hint">${esc(ev.data.hint)}</div>` : ""}</div>`,
        chips: (ev.data.chips as string[]) ?? [],
      });
      pushTrace("ask", "?", "Ask", String(ev.data.question ?? ""));
      break;
    }
    case "final": {
      const kind = String(ev.data.kind ?? "");
      // 有结构化卡片时，模型写的大白话综合报告不再被卡片整个替换掉：文字留作一个气泡（带 [n] 引用上标），卡片另起一个。
      const { prose, card } = splitFinal(ev.data);
      if (prose) {
        setReply(typing, context, prose, String(ev.data.plain ?? ""));
        pushMsg({ role: "ai", kind: "bubble", html: card, acts: reportActs(ev.data) });
      } else {
        setReply(typing, context, card, undefined, reportActs(ev.data));
      }
      if (kind === "chat") {
        resetPanel();
        break;
      }
      pushTrace("done", "✓", "Done", "已生成综合报告");
      const data = (ev.data.data ?? {}) as Record<string, unknown>;
      const level = typeof data.level === "number" ? data.level : null;
      const lesions = Array.isArray(data.lesions)
        ? (data.lesions as { type: string; count?: number }[]).map((l) => ({ type: l.type, count: l.count ?? 0 })) : [];
      finishPanel(level, String(data.urgency ?? "green"), lesions);
      scan.value.result = {
        v: kind === "fundus" ? `DR ${level} 级` : String(data.department || data.dept || "分析完成"),
        s: String(data.urgency_label || data.urg || "可在左侧查看详细报告"),
      };
      if (context.imageSrc) {
        const photo = [...messages.value].reverse().find((m) => m.kind === "photo" && m.src === context.imageSrc);
        if (photo) photo.badge = kind === "fundus" ? `DR ${level} 级` : kind === "lab" ? `${data.abnormal_count ?? 0} 项异常` : "已分析";
      }
      if (kind === "lab") {
        labReportStore.set(data, { previewUrl: context.imageSrc, fileName: context.fileName, source: "chat" });
      }
      if (kind === "fundus" && typeof data.level === "number") {
        void (async () => {
          const [thumb, view] = await Promise.all([makeThumb(context.imageSrc), makeView(context.imageSrc)]);
          fundusStore.set(normalizeFundus(data as never, "chat", {
            thumbnail: thumb.url, viewImage: view.url, fileDim: thumb.dim, fileName: context.fileName || "Agent助手上传眼底图",
          }));
          fundusPairStore.set(null);          // 眼底页显示最新的一次结果：这份单眼报告取代之前的双眼结论
        })();
      }
      break;
    }
    case "error": {
      removeMsg(typing.id);
      pushMsg({
        role: "ai",
        kind: "bubble",
        html: `<p style="color:var(--red)">${esc(ev.data.message ?? "分析失败")}</p>`,
      });
      failPanel(String(ev.data.message ?? "分析失败"));
      break;
    }
    default:
      break;
  }
  void scrollBottom();
}

function removeMsg(id: number) {
  const i = messages.value.findIndex((m) => m.id === id);
  if (i >= 0) messages.value.splice(i, 1);
}

function fileToDataUrl(f: File): Promise<string> {
  return new Promise((resolve) => {
    const fr = new FileReader();
    fr.onload = () => resolve(String(fr.result));
    fr.onerror = () => resolve("");
    fr.readAsDataURL(f);
  });
}

function onPick(e: Event) {
  const f = (e.target as HTMLInputElement).files?.[0];
  if (f) {
    pendingFile.value = f;
    void fileToDataUrl(f).then((src) => {
      pendingSrc.value = src;
      void send("", f);
    });
  }
  (e.target as HTMLInputElement).value = "";
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    void send();
  }
}

function onStreamClick(e: MouseEvent) {
  if ((e.target as HTMLElement).closest("[data-upload]")) { fileEl.value?.click(); return; }
  const btn = (e.target as HTMLElement).closest<HTMLButtonElement>("[data-go]");
  // 只有用户真的点了才跳。带 data-dept 的（来自医院导航）把科室一并交出去，
  // 医院页据此按本次结论排序，而不是沿用上次选的科室。
  if (btn && ["eye", "lab", "symptom", "history", "hospital"].includes(btn.dataset.go || ""))
    emit("go", btn.dataset.go as PageKey, btn.dataset.dept || "");
}

function chooseChip(m: Msg, chip: string) {
  if (m.answered || busy.value) return;
  m.answered = true;
  void send(chip);
}

async function newChat() {
  ++sendVersion;
  stopPanelTimer();
  try {
    await reset();
    welcome();
    rec.refreshSoon();
  } catch (error) {
    const message = error instanceof Error ? error.message : "重置失败，请重试";
    pushMsg({ role: "ai", kind: "bubble", html: `<p style="color:var(--red)">${esc(message)}</p>` });
    failPanel(message);
  }
}

/* 语音输入：Web Speech API（与原生版一致，浏览器不支持时提示） */
interface SpeechAlt {
  0: { transcript: string };
}
interface SpeechResult {
  resultIndex: number;
  results: { length: number; [i: number]: SpeechAlt };
}
interface SpeechRec {
  lang: string;
  interimResults: boolean;
  start(): void;
  onresult: ((ev: SpeechResult) => void) | null;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
}

function toggleVoice() {
  const SR = (window as unknown as { webkitSpeechRecognition?: new () => SpeechRec })
    .webkitSpeechRecognition;
  if (!SR) {
    pushMsg({ role: "ai", kind: "bubble", html: "<p>当前浏览器不支持语音识别，建议使用 Chrome / Edge。</p>" });
    return;
  }
  const r = new SR();
  r.lang = "zh-CN";
  r.interimResults = false;
  r.onresult = (ev: SpeechResult) => {
    let t = "";
    for (let i = ev.resultIndex; i < ev.results.length; i++) t += ev.results[i][0].transcript;
    input.value = `${input.value}${t}`;
  };
  r.onstart = () => (listening.value = true);
  r.onend = () => (listening.value = false);
  r.onerror = () => (listening.value = false);
  r.start();
}

/** 健康信息：模型名 / 能力标签（右侧面板信息区） */
// 模型名到展示名的映射。2026-10-24 起默认模型是 DeepSeek-V4-Flash 正式版（见 backend/config.py，有免费额度）。
// 映射表同时保留经济版与旧 GLM 条目，.env 切换模型时仍显示得对。
// 不写成 if 链是因为模型 id 带日期后缀，改天换版本就失效；表里没有的 ID 原样显示。
const MODEL_LABEL: Record<string, string> = {
  "deepseek-v4-flash-ga-260731": "DeepSeek-V4-Flash",
  "deepseek-v4-1-flash-economy-261017": "DeepSeek-V4.1-Flash 经济版",
  "glm-5-2-260617": "GLM-5.2",
  "glm-5-3-flash-260828": "GLM-5.3-Flash",
};
onMounted(welcome);

// 健康信息走 vue-query：带缓存与去重，页面来回切换不重复请求；拿不到不影响对话。
const health = useHealth();
watch(
  () => health.data.value,
  (h) => {
    if (!h) return;
    const live = liveCheckLabel(h.live_check);
    scan.value.live = live.text;
    scan.value.liveOk = live.ok;
    if (h.llm_enabled === false) {
      // 没有可用的大模型：如实显示离线规则模式，不再写「大模型在线」。
      scan.value.model = "规则引擎（离线）";
      scan.value.trainK = "能力";
      scan.value.trainV = "知识库检索 + 红旗规则";
      scan.value.aucK = "推理";
      scan.value.aucV = "离线模式";
    } else {
      scan.value.model = (h.llm_model && MODEL_LABEL[h.llm_model]) || h.llm_model || "大模型";
      scan.value.trainK = "能力";
      scan.value.trainV = "多模态 · 图片 + 文字";
      scan.value.aucK = "推理";
      scan.value.aucV = "大模型在线";
    }
  },
  { immediate: true },
);

watch(
  () => props.active,
  (on) => {
    if (!on) return;
    void scrollBottom();
    // 使用指南里点了示例问题：填进输入框，由用户决定是否发送（不替用户调用模型）
    const t = useWorkbenchStore().takeText("chat");
    if (t) input.value = t;
  },
);
</script>

<template>
  <div class="chat-main">
    <div class="cchat">
      <div class="chat-body">
        <div ref="streamEl" class="stream" role="log" aria-live="polite" aria-relevant="additions" aria-label="对话消息" @click="onStreamClick">
          <div v-for="m in messages" :key="m.id" :class="['msg', m.role === 'me' ? 'me' : 'ai']">
            <div v-if="m.role === 'me'" class="user-avatar">{{ auth.initial }}</div>
            <div v-else class="gem-avatar"><div class="dia"></div></div>

            <div class="msg-content">
              <template v-if="m.kind === 'photo'">
                <div class="msg-bubble" style="padding: 0; background: transparent; box-shadow: none">
                  <div class="msg-photo">
                    <img :src="m.src" alt="待分析图片" />
                    <span class="meta">{{ m.badge }}</span>
                  </div>
                </div>
              </template>

              <template v-else-if="m.kind === 'typing'">
                <div class="msg-bubble"><div class="typing" role="status" aria-label="AI 正在思考"><i></i><i></i><i></i></div></div>
              </template>

              <template v-else-if="m.kind === 'think'">
                <div class="think-bubble" role="note" v-html="m.html"></div>
              </template>

              <template v-else-if="m.kind === 'ask'">
                <div class="msg-bubble">
                  <div v-html="m.html"></div>
                  <div class="ask-card" style="margin-top: 0; border: none; padding: 0">
                    <div class="chips" style="margin-top: 10px">
                      <button
                        v-for="c in m.chips"
                        :key="c"
                        class="ask-chip"
                        type="button"
                        :disabled="m.answered"
                        @click="chooseChip(m, c)"
                      >
                        {{ c }}
                      </button>
                    </div>
                  </div>
                </div>
              </template>

              <template v-else>
                <div class="msg-bubble" v-html="m.html"></div>
                <div v-if="m.starter" class="chat-chips">
                  <button class="chip" type="button" title="打开眼底筛查页" @click="emit('go', 'eye')">演示 · 眼底图</button>
                  <button class="chip" type="button" title="打开化验单报告页" @click="emit('go', 'lab')">演示 · 化验单</button>
                  <button class="chip" type="button" @click="input = '最近三天头晕，早上起床时明显，没有呕吐'; send()">头晕三天该看什么科？</button>
                </div>
                <div v-if="m.acts && m.acts.length" class="acts">
                  <button
                    v-for="(a, i) in m.acts"
                    :key="i"
                    class="ma-btn"
                    :class="{ primary: i === 0 }"
                    type="button"
                    :data-go="a.a"
                    :data-dept="a.dept || ''"
                  >
                    {{ a.t }}
                  </button>
                </div>
              </template>
            </div>
          </div>
        </div>
      </div>

      <div class="chat-input">
        <input ref="fileEl" type="file" accept="image/*" hidden @change="onPick" />
        <div class="input-inner">
          <button class="attach" type="button" title="上传照片" aria-label="上传照片" @click="fileEl?.click()">＋</button>
          <button
            class="attach voice"
            type="button"
            :class="{ recording: listening }"
            title="语音输入"
            aria-label="语音输入（按一下开始或停止）"
            :aria-pressed="listening"
            style="font-size: 18px; line-height: 34px"
            @click="toggleVoice"
          >
            🎤
          </button>
          <textarea
            ref="textEl"
            v-model="input"
            aria-label="对话输入框，可上传图片做扫描，或直接描述症状"
            placeholder="上传图片扫描，或描述症状…（也可按住麦克风说话）"
            rows="1"
            @keydown="onKeydown"
          ></textarea>
          <button class="send" type="button" title="发送" aria-label="发送" :disabled="busy" @click="send()">
            <svg viewBox="0 0 24 24"><path d="M12 19V5M5 12l7-7 7 7" /></svg>
          </button>
        </div>
        <p class="chat-hint">
          AI 输出仅为筛查参考，不是诊断，需医生确认 · 急症请拨打 120<button class="chat-reset" type="button" @click="newChat">
            新对话
          </button>
        </p>
      </div>
    </div>

    <aside class="panel">
      <div class="panel-title">
        实时扫描 <span class="badge" :class="{ done: scan.badge === 'DONE' }"><i></i>{{ scan.badge }}</span>
      </div>

      <div class="scan-panel" :class="{ live: scan.running }">
        <div class="retina" :style="scan.retina ? { backgroundImage: `url(${scan.retina})` } : undefined"></div>
        <div class="grid-ov"></div>
        <div v-show="scan.split" class="sl"></div>
        <div class="cn tl"></div><div class="cn tr"></div><div class="cn bl"></div><div class="cn br"></div>
        <div class="hud"><i></i>{{ scan.hud }}</div>
      </div>

      <div class="prog">
        <div class="track"><i :style="{ width: `${scan.progress}%` }"></i></div>
        <div class="pct">{{ scan.progress }}%</div>
      </div>

      <div class="steps">
        <div v-for="(s, i) in scan.steps" :key="i" class="s" :class="s.state">
          <span class="ck">{{ s.state === "done" ? "✓" : s.state === "run" ? "•" : "·" }}</span>{{ s.text }}
        </div>
      </div>

      <div class="info">
        <div class="row"><span class="k">模型</span><span class="v">{{ scan.model }}</span></div>
        <div class="row"><span class="k">{{ scan.trainK }}</span><span class="v">{{ scan.trainV }}</span></div>
        <div class="row"><span class="k">{{ scan.aucK }}</span><span class="v hl">{{ scan.aucV }}</span></div>
        <div class="row" title="backend/evals/live_smoke.py 的最近一次真实接口测试">
          <span class="k">实测</span><span class="v" :class="{ hl: scan.liveOk === true }">{{ scan.live }}</span>
        </div>
        <div class="row"><span class="k">耗时</span><span class="v">{{ scan.elapsed }}</span></div>
        <div class="row"><span class="k">状态</span><span class="v">{{ scan.state }}</span></div>
      </div>

      <div v-if="scan.result" class="panel-result">
        <div class="lbl">当前判断</div>
        <div class="v">{{ scan.result.v }}</div>
        <div class="s">{{ scan.result.s }}</div>
      </div>

      <div v-if="scan.lesions.length" class="info">
        <div class="lt">病灶图例</div>
        <div v-for="(l, i) in scan.lesions.slice(0, 4)" :key="i" class="row">
          <span class="k"><i class="sw" :style="{ background: ['#FF9F0A', '#FF453A', '#FFD60A', '#8CC6FF'][i % 4] }"></i>{{ l.type }}</span>
          <span class="v">{{ l.count }} 处</span>
        </div>
      </div>

      <AgentTrace :trace="trace" :tools="tools" :phase="phase" />
    </aside>
  </div>
</template>
