/**
 * Agent SSE 流式 composable（TS 版，平移自 app.js 的流式处理逻辑）。
 * 通过 fetch + ReadableStream 解析 text/event-stream，逐事件回调。
 * 事件：thought / tool_start / tool_result / token / ask / final / error
 */
import { getCurrentScope, onScopeDispose, ref } from "vue";
import { API_BASE, authHeaders, errorFromResponse, notifyIfUnauthorized } from "@/lib/api";

export interface AgentEvent {
  event: string;
  data: Record<string, unknown>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

export function parseSSE(block: string): AgentEvent | null {
  const lines = block.split(/\r?\n/);
  const ev: AgentEvent = { event: "message", data: {} };
  const dataLines: string[] = [];
  for (const line of lines) {
    if (line.startsWith("event:")) ev.event = line.slice(6).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice(5).trim());
  }
  if (!dataLines.length) return null;
  const raw = dataLines.join("\n");
  try {
    const data: unknown = JSON.parse(raw);
    ev.data = isRecord(data) ? data : { raw };
  } catch {
    ev.data = { raw };
  }
  return ev;
}

/** 与 lib/api 同一套错误解析：带 code / Retry-After，登录过期时触发全局跳转。 */
async function responseError(path: string, response: Response, fallback: string): Promise<Error> {
  const err = await errorFromResponse(response, fallback);
  notifyIfUnauthorized(path, err);
  return err;
}

const STREAM_PATH = "/api/agent/chat/stream";
const RESET_PATH = "/api/agent/reset";

interface RequestState {
  controller: AbortController;
  reader?: ReadableStreamDefaultReader<Uint8Array>;
}

export function useAgentStream() {
  const busy = ref(false);
  const phase = ref<"idle" | "running" | "asking" | "done" | "error">("idle");
  let active: RequestState | null = null;
  let resetPromise: Promise<void> | null = null;
  let disposed = false;

  function isCurrent(request: RequestState): boolean {
    return !disposed && active === request && !request.controller.signal.aborted;
  }

  function finish(request: RequestState) {
    if (active !== request) return;
    active = null;
    busy.value = false;
  }

  function cancelActive() {
    const request = active;
    // 先失效再取消：abort/read 的后续回调不能改写新请求的状态。
    active = null;
    if (!request) return;
    request.controller.abort();
    void request.reader?.cancel().catch(() => undefined);
  }

  if (getCurrentScope()) {
    onScopeDispose(() => {
      disposed = true;
      cancelActive();
      busy.value = false;
    });
  }

  async function stream(
    text: string,
    file: File | null,
    onEvent: (ev: AgentEvent) => void,
  ): Promise<void> {
    if (disposed || active) return;
    const request: RequestState = { controller: new AbortController() };
    active = request;
    busy.value = true;
    phase.value = "running";
    let reachedEOF = false;
    try {
      const fd = new FormData();
      fd.append("text", text);
      if (file) fd.append("file", file, file.name || "upload.png");
      const resp = await fetch(`${API_BASE}${STREAM_PATH}`, {
        method: "POST",
        headers: authHeaders(),
        body: fd,
        signal: request.controller.signal,
      });
      if (!isCurrent(request)) {
        void resp.body?.cancel().catch(() => undefined);
        return;
      }
      if (!resp.ok || !resp.body) {
        throw await responseError(STREAM_PATH, resp, "流式接口错误");
      }
      const reader = request.reader = resp.body.getReader();
      const decoder = new TextDecoder("utf-8");
      let buf = "";
      let terminal = false;

      function dispatch(block: string) {
        if (!isCurrent(request) || terminal) return;
        const ev = parseSSE(block);
        if (!ev) return;
        if (["ask", "final", "error"].includes(ev.event) && "raw" in ev.data) {
          throw new Error("分析结果格式错误，请重试。");
        }
        if (ev.event === "ask") { phase.value = "asking"; terminal = true; }
        if (ev.event === "final") { phase.value = "done"; terminal = true; }
        if (ev.event === "error") { phase.value = "error"; terminal = true; }
        onEvent(ev);
      }

      while (isCurrent(request)) {
        const { done, value } = await reader.read();
        if (!isCurrent(request)) return;
        reachedEOF = done;
        buf += done ? decoder.decode() : decoder.decode(value, { stream: true });
        // 保留尚未完成的分隔符，兼容 CR/LF 与 UTF-8 字符跨网络块拆分。
        const parts = buf.split(/\r?\n\r?\n/);
        buf = parts.pop() ?? "";
        for (const block of parts) dispatch(block);
        if (done) {
          if (buf) dispatch(buf);
          if (isCurrent(request) && !terminal) throw new Error("连接已中断，未收到完整分析结果，请重试。");
          break;
        }
      }
    } catch (e) {
      if (!isCurrent(request)) return;
      phase.value = "error";
      onEvent({ event: "error", data: { message: e instanceof Error && e.message ? e.message : "网络错误" } });
    } finally {
      if (request.reader) {
        if (isCurrent(request) && !reachedEOF) {
          void request.reader.cancel().catch(() => undefined);
        }
        request.reader.releaseLock();
      }
      finish(request);
    }
  }

  /** 新对话：先中止旧流。仅服务端重置成功后，调用者才能清空聊天。 */
  function reset(): Promise<void> {
    if (disposed) return Promise.reject(new Error("页面已关闭"));
    if (resetPromise) return resetPromise;
    cancelActive();
    const request: RequestState = { controller: new AbortController() };
    active = request;
    busy.value = true;
    resetPromise = (async () => {
      try {
        const resp = await fetch(`${API_BASE}${RESET_PATH}`, {
          method: "POST",
          headers: authHeaders(),
          signal: request.controller.signal,
        });
        if (!isCurrent(request)) throw new Error("重置已取消");
        if (!resp.ok) throw await responseError(RESET_PATH, resp, "重置失败");
        phase.value = "idle";
      } catch (e) {
        if (isCurrent(request)) phase.value = "error";
        throw e;
      } finally {
        finish(request);
      }
    })().finally(() => { resetPromise = null; });
    return resetPromise;
  }

  return { busy, phase, stream, reset };
}
