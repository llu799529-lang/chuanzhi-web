/**
 * 工作台会话状态：当前页面、搜索、跨页请求。
 * 页面切换沿用 app.html 的 data-page 语义（chat / work / eye / lab / symptom / multi / history / hospital / guide）。
 */
import { defineStore } from "pinia";
import { computed, ref, watch } from "vue";
import { useAuthStore } from "@/stores/auth";

export type PageKey = "chat" | "work" | "eye" | "lab" | "symptom" | "multi" | "history" | "hospital" | "guide";

export const PAGE_META: Record<PageKey, { parent: string; label: string }> = {
  chat: { parent: "Agent助手", label: "AI 扫描分诊" },
  work: { parent: "工作台", label: "工作台" },
  eye: { parent: "眼底筛查", label: "眼底筛查" },
  lab: { parent: "化验单", label: "化验单" },
  symptom: { parent: "症状分诊", label: "症状分诊" },
  multi: { parent: "多模态综合分析", label: "多模态综合分析" },
  history: { parent: "历史记录", label: "历史记录" },
  hospital: { parent: "附近医院", label: "附近医院" },
  guide: { parent: "使用指南", label: "使用指南" },
};

/**
 * 跨页请求：工作台 / 使用指南上的按钮把「要做的事」交给目标页。
 *   demo   打开眼底页或化验单页并运行示例
 *   fresh  打开上传视图（不显示上一次的报告）
 *   pair   打开眼底页并运行双眼示例（示例 A 右眼 + 示例 B 左眼）
 *   file   打开眼底页并分析拖到工作台上传框里的照片
 *   text   把示例文字填进目标页的输入框（不自动提交）
 * take 语义：目标页消费后立即清空，避免下次进入又自动触发。
 */
export type IntentKind = "demo" | "fresh" | "text" | "pair" | "file";
export interface Intent {
  page: PageKey;
  kind: IntentKind;
  text: string;
  file?: File;
}

export const useWorkbenchStore = defineStore("workbench", () => {
  const page = ref<PageKey>("chat");
  const searchOpen = ref(false);
  // 分诊结论 → 医院页的科室传递。
  //
  // 修的是一个断链：症状页分诊出「神经内科」，用户点「找附近医院 →」，
  // 医院页却按 localStorage 里默认的「眼科」展示。科室这个信息在跳转时被丢掉了。
  // 医院页消费后必须清空（take 语义），否则用户下次从侧边栏直接进医院页，
  // 会被上一次的分诊科室"粘住"，同样是一个错误答案。
  const pendingDept = ref("");
  const intent = ref<Intent | null>(null);
  const auth = useAuthStore();
  watch(() => auth.token, () => {
    page.value = "chat";
    searchOpen.value = false;
    pendingDept.value = "";
    intent.value = null;
  }, { flush: "sync" });

  const parent = computed(() => PAGE_META[page.value].parent);
  const crumb = computed(() => PAGE_META[page.value].label);

  function go(next: PageKey) {
    page.value = next;
  }

  function goWithDept(next: PageKey, dept: string) {
    pendingDept.value = (dept || "").trim();
    page.value = next;
  }

  function takeDept(): string {
    const d = pendingDept.value;
    pendingDept.value = "";
    return d;
  }

  function request(target: PageKey, kind: IntentKind, text = "", file?: File) {
    intent.value = { page: target, kind, text, file };
  }

  function take(target: PageKey, kind: IntentKind): Intent | null {
    const i = intent.value;
    if (!i || i.page !== target || i.kind !== kind) return null;
    intent.value = null;
    return i;
  }

  /** 「用示例体验」：默认眼底页（评审建议的上传演示），化验单页同样支持 */
  function requestDemo(target: "eye" | "lab" = "eye") {
    request(target, "demo");
  }

  function takeDemo(target: "eye" | "lab" = "eye"): boolean {
    return take(target, "demo") !== null;
  }

  function prefill(target: PageKey, text: string) {
    request(target, "text", text);
  }

  function takeText(target: PageKey): string {
    return take(target, "text")?.text ?? "";
  }

  return {
    page, parent, crumb, searchOpen, pendingDept, intent,
    go, goWithDept, takeDept, request, take, requestDemo, takeDemo, prefill, takeText,
  };
});
