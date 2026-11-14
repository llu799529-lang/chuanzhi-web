/**
 * 服务健康状态（/api/health）：这个项目里 TanStack Query 的第一个真实用法。
 *
 * 分工约定：服务器状态（可缓存、可过期、要去重）走 vue-query；纯客户端状态（当前对话、面板进度）走 Pinia / ref。
 * 之前 main.ts 注册了 VueQueryPlugin 但没有任何地方用它——依赖装了、能力没用上。
 *
 * `healthQueryOptions` 单独导出是为了可测：不用起 Vue 组件，直接 `queryClient.fetchQuery(healthQueryOptions())`。
 */
import { useQuery } from "@tanstack/vue-query";
import { api } from "@/lib/api";

export interface LiveCheck {
  at?: string;
  model?: string;
  passed?: number;
  total?: number;
  unsupported_params?: string[];
  probes?: Record<string, boolean>;
  cache_hit?: boolean;
}

export interface Health {
  llm_vision_model?: string | null;
  status?: string;
  llm_enabled?: boolean;
  llm_model?: string | null;
  fundus_mode?: string;
  capabilities?: Record<string, boolean>;
  /** 最近一次真实接口冒烟测试（backend/evals/live_smoke.py）；没跑过为 null */
  live_check?: LiveCheck | null;
}

const PROBE_LABEL: Record<string, string> = {
  text: "文本", json: "结构化", tools: "工具调用", stream: "流式", image: "图片", cache: "缓存",
};

/**
 * 「实测」一行的文案：没跑过就写「未实测」，跑过就写通过数、日期与没通过的能力。
 * 刻意不写成「已验证」之类的笼统说法——评委看到的必须是能对上报告文件的具体数字。
 */
export function liveCheckLabel(lc: LiveCheck | null | undefined): { text: string; ok: boolean | null } {
  if (!lc || typeof lc.passed !== "number" || typeof lc.total !== "number" || !lc.total) {
    return { text: "未实测", ok: null };
  }
  const day = (lc.at || "").slice(0, 10);
  const failed = Object.entries(lc.probes || {})
    .filter(([k, v]) => !v && k !== "cache")
    .map(([k]) => PROBE_LABEL[k] || k);
  const tail = failed.length ? ` · 未通过：${failed.join("、")}` : "";
  return { text: `${lc.passed}/${lc.total} 通过${day ? ` · ${day}` : ""}${tail}`, ok: lc.passed === lc.total };
}

export const HEALTH_KEY = ["health"] as const;

export function healthQueryOptions() {
  return {
    queryKey: HEALTH_KEY,
    queryFn: () => api<Health>("/api/health"),
    // 模型是否在线几分钟内不会变；页面切换来回时不重复请求
    staleTime: 60_000,
    // 健康信息拿不到不影响对话，不值得反复重试拖慢界面
    retry: 1,
    refetchOnWindowFocus: false,
  } as const;
}

export function useHealth() {
  return useQuery(healthQueryOptions());
}
