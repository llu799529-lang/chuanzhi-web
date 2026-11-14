<script setup lang="ts">
/**
 * 决策轨迹 + 工具箱（Agent 助手右侧面板的下半部分）。
 *
 * 纯展示组件：数据全部来自 props，没有自己的状态、不发请求。从 ChatPage（700+ 行）抽出，
 * 好处是 ChatPage 只管「事件 → 状态」，这里只管「状态 → 画面」，两边都能单独理解。
 * 样式沿用 workbench.css 里的全局类（tr-item / ag-tool），所以抽出来没有视觉变化。
 */
import { computed } from "vue";
import type { TraceItem, ToolState } from "@/lib/agentEvents";

type Phase = "idle" | "running" | "asking" | "done" | "error";

const props = defineProps<{
  trace: TraceItem[];
  tools: ToolState[];
  phase: Phase;
}>();

const badge = computed(() =>
  props.phase === "done" ? "DONE" : props.phase === "asking" ? "WAIT INFO" : props.phase === "error" ? "ERROR" : "RUNNING",
);
const calledCount = computed(() => props.tools.filter((t) => t.called).length);
</script>

<template>
  <section v-if="trace.length" class="agent-side" aria-label="Agent 决策轨迹">
    <div class="panel-title">
      决策轨迹 <span class="badge" :class="{ done: phase === 'done' }"><i></i>{{ badge }}</span>
    </div>
    <ol class="plate ag-trace" aria-live="polite" aria-relevant="additions" style="list-style: none; margin: 0">
      <li v-for="t in trace" :key="t.id" class="tr-item" :class="t.type">
        <div class="no" aria-hidden="true">{{ t.icon }}</div>
        <div class="body">
          <div class="lbl">{{ t.label }}</div>
          <div class="tx">{{ t.text }}</div>
        </div>
      </li>
    </ol>
    <div class="plate ag-tools">
      <div class="hd"><span>工具箱</span><span class="cnt">{{ calledCount }} / {{ tools.length }} 已调</span></div>
      <div v-for="(t, i) in tools" :key="t.name" class="ag-tool" :class="{ called: t.called }">
        <div class="ic" aria-hidden="true">{{ i + 1 }}</div>
        <div class="body"><b>{{ t.name }}</b><span>{{ t.desc }}</span></div>
        <span class="st">{{ t.called ? "已调" : "待命" }}</span>
      </div>
    </div>
  </section>
</template>
