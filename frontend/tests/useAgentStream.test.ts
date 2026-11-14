import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createPinia, setActivePinia } from "pinia";
import { effectScope, type EffectScope } from "vue";
import { useAgentStream, type AgentEvent } from "@/composables/useAgentStream";

const encoder = new TextEncoder();
const scopes: EffectScope[] = [];

function createAgent() {
  const scope = effectScope();
  scopes.push(scope);
  return { agent: scope.run(() => useAgentStream())!, scope };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; });
  return { promise, resolve, reject };
}

function openResponse() {
  let controller!: ReadableStreamDefaultController<Uint8Array>;
  const cancel = vi.fn();
  const body = new ReadableStream<Uint8Array>({
    start(value) { controller = value; },
    cancel,
  });
  return { body, controller, cancel, response: new Response(body) };
}

function responseWithChunks(chunks: Uint8Array[]) {
  return new Response(new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(chunk));
      controller.close();
    },
  }));
}

beforeEach(() => {
  vi.stubGlobal("localStorage", { getItem: () => "test-token" });
  setActivePinia(createPinia());
});

afterEach(() => {
  scopes.splice(0).forEach((scope) => scope.stop());
  vi.unstubAllGlobals();
});

describe("useAgentStream framing", () => {
  it.each(["null", "[]", "broken"])("损坏的终止帧 %s 不应报告成功", async (data) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(responseWithChunks([
      encoder.encode(`event: final\ndata: ${data}\n\n`),
    ])));
    const { agent } = createAgent();
    const seen: AgentEvent[] = [];
    await agent.stream("", null, (event) => seen.push(event));
    expect(agent.phase.value).toBe("error");
    expect(seen.some((event) => event.event === "final")).toBe(false);
  });

  it("重复终止帧只生成一份报告", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(responseWithChunks([
      encoder.encode('event: final\ndata: {"plain":"结论"}\n\nevent: final\ndata: {"plain":"重复"}\n\n'),
    ])));
    const { agent } = createAgent();
    const onEvent = vi.fn();
    await agent.stream("", null, onEvent);
    expect(onEvent).toHaveBeenCalledTimes(1);
  });
  it.each(["\n", "\r\n"])("逐字节读取 %j 帧，保留中文并交付 EOF 末帧", async (newline) => {
    const payload = [
      ': heartbeat', '',
      'event: token', 'data: {"text":"胸口闷🫀"}', '',
      'event: final', 'data: {"plain":"请补充症状"}',
    ].join(newline);
    const bytes = encoder.encode(payload);
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(responseWithChunks(
      Array.from(bytes, (byte) => Uint8Array.of(byte)),
    )));
    const { agent } = createAgent();
    const events: AgentEvent[] = [];

    await agent.stream("症状", null, (event) => events.push(event));

    expect(events).toEqual([
      { event: "token", data: { text: "胸口闷🫀" } },
      { event: "final", data: { plain: "请补充症状" } },
    ]);
    expect(agent.phase.value).toBe("done");
    expect(agent.busy.value).toBe(false);
  });

  it("EOF 刷新解码器中的残余字节并报告缺少终止事件", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(responseWithChunks([
      encoder.encode("event: token\ndata: "), Uint8Array.of(0xe4, 0xb8),
    ])));
    const { agent } = createAgent();
    const events: AgentEvent[] = [];

    await agent.stream("", null, (event) => events.push(event));

    expect(events[0]).toEqual({ event: "token", data: { raw: "�" } });
    expect(events[1]).toMatchObject({ event: "error", data: { message: expect.stringContaining("中断") } });
    expect(agent.phase.value).toBe("error");
  });

  it("正常 EOF 缺少 ask/final/error 时不能冒充分析完成", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(responseWithChunks([
      encoder.encode('event: token\ndata: {"text":"部分结果"}\n\n'),
    ])));
    const { agent } = createAgent();
    const onEvent = vi.fn();

    await agent.stream("", null, onEvent);

    expect(agent.phase.value).toBe("error");
    expect(onEvent).toHaveBeenLastCalledWith({ event: "error", data: { message: expect.stringContaining("中断") } });
    expect(agent.busy.value).toBe(false);
  });

  it.each([
    ["ask", "asking"], ["final", "done"], ["error", "error"],
  ])("保留 %s 事件与对应状态 %s", async (event, phase) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(responseWithChunks([
      encoder.encode(`event: ${event}\ndata: {"message":"原始内容"}\n\n`),
    ])));
    const { agent } = createAgent();
    const onEvent = vi.fn();

    await agent.stream("", null, onEvent);

    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onEvent).toHaveBeenCalledWith({ event, data: { message: "原始内容" } });
    expect(agent.phase.value).toBe(phase);
  });

  it("同一块中的多个事件按顺序发送，非对象 data 不破坏消费者", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(responseWithChunks([
      encoder.encode('event: token\ndata: null\n\nevent: final\ndata: {"plain":"完成"}\n\n'),
    ])));
    const { agent } = createAgent();
    const seen: unknown[] = [];

    await agent.stream("", null, (event) => seen.push(event.data.raw ?? event.data.plain));

    expect(seen).toEqual(["null", "完成"]);
    expect(agent.phase.value).toBe("done");
  });

  it("非对象 HTTP 错误体仍提供明确的状态错误", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("null", { status: 503 })));
    const { agent } = createAgent();
    const onEvent = vi.fn();

    await agent.stream("", null, onEvent);

    expect(onEvent).toHaveBeenCalledTimes(1);
    expect(onEvent).toHaveBeenCalledWith({ event: "error", data: { message: "流式接口错误（503）" } });
  });

  it("网络异常缺少描述时保留默认错误提示", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error()));
    const { agent } = createAgent();
    const onEvent = vi.fn();

    await agent.stream("", null, onEvent);

    expect(onEvent).toHaveBeenCalledWith({ event: "error", data: { message: "网络错误" } });
    expect(agent.phase.value).toBe("error");
    expect(agent.busy.value).toBe(false);
  });
});

describe("useAgentStream lifecycle", () => {
  it("同一次重置进行中重复点击共享结果，不重复请求", async () => {
    const pending = deferred<Response>();
    const fetch = vi.fn().mockReturnValue(pending.promise);
    vi.stubGlobal("fetch", fetch);
    const { agent } = createAgent();

    const first = agent.reset();
    const second = agent.reset();

    expect(fetch).toHaveBeenCalledTimes(1);
    pending.resolve(new Response("{}"));
    await Promise.all([first, second]);
    expect(agent.phase.value).toBe("idle");
  });

  it("回调内重置后丢弃同一网络块中的旧事件", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(responseWithChunks([
      encoder.encode('event: token\ndata: {"text":"旧片段"}\n\nevent: final\ndata: {}\n\n'),
    ])).mockResolvedValueOnce(new Response("{}")));
    const { agent } = createAgent();
    const events: string[] = [];
    let resetting: Promise<void> | undefined;

    await agent.stream("", null, (event) => {
      events.push(event.event);
      if (event.event === "token") resetting = agent.reset();
    });
    await resetting;

    expect(events).toEqual(["token"]);
    expect(agent.phase.value).toBe("idle");
  });

  it("活动请求期间不重复提交分析", async () => {
    const pending = deferred<Response>();
    const fetch = vi.fn().mockReturnValue(pending.promise);
    vi.stubGlobal("fetch", fetch);
    const { agent } = createAgent();
    const first = agent.stream("第一条", null, vi.fn());

    const duplicate = agent.stream("重复", null, vi.fn());

    expect(fetch).toHaveBeenCalledTimes(1);
    pending.resolve(responseWithChunks([encoder.encode('event: final\ndata: {}\n\n')]));
    await Promise.all([first, duplicate]);
  });

  it("reset 先中止 fetch 和 reader，再清空服务端会话", async () => {
    const active = openResponse();
    let signal!: AbortSignal;
    let resetObserved: unknown[] = [];
    const fetch = vi.fn().mockImplementation((_url, init: RequestInit) => {
      if (fetch.mock.calls.length === 1) {
        signal = init.signal as AbortSignal;
        return Promise.resolve(active.response);
      }
      resetObserved = [signal?.aborted, active.cancel.mock.calls.length];
      return Promise.resolve(new Response("{}"));
    });
    vi.stubGlobal("fetch", fetch);
    const { agent } = createAgent();
    const onEvent = vi.fn();
    const stream = agent.stream("", null, onEvent);
    await vi.waitFor(() => expect(active.body.locked).toBe(true));

    const resetting = agent.reset();
    expect(resetObserved).toEqual([true, 1]);
    await resetting;
    await stream;

    expect(agent.phase.value).toBe("idle");
    expect(agent.busy.value).toBe(false);
    expect(onEvent).not.toHaveBeenCalled();
    expect(active.body.locked).toBe(false);
  });

  it("重置期间保持 busy，阻止旧 finally 解锁或新分析抢先提交", async () => {
    const active = openResponse();
    const reset = deferred<Response>();
    const fetch = vi.fn().mockResolvedValueOnce(active.response).mockReturnValueOnce(reset.promise);
    vi.stubGlobal("fetch", fetch);
    const { agent } = createAgent();
    const stream = agent.stream("", null, vi.fn());
    await vi.waitFor(() => expect(active.body.locked).toBe(true));

    const resetting = agent.reset();
    expect(active.cancel).toHaveBeenCalledTimes(1);
    await stream;
    expect(agent.busy.value).toBe(true);
    await agent.stream("新分析", null, vi.fn());
    expect(fetch).toHaveBeenCalledTimes(2);
    reset.resolve(new Response("{}"));
    await resetting;
    expect(agent.busy.value).toBe(false);
  });

  it.each(["resolve", "reject"] as const)("旧请求延迟 %s 不污染重置后的新流", async (settle) => {
    const old = deferred<Response>();
    const newer = openResponse();
    const fetch = vi.fn().mockReturnValueOnce(old.promise)
      .mockResolvedValueOnce(new Response("{}"))
      .mockResolvedValueOnce(newer.response);
    vi.stubGlobal("fetch", fetch);
    const { agent } = createAgent();
    const oldEvents = vi.fn();
    const oldStream = agent.stream("旧请求", null, oldEvents);
    await agent.reset();
    const newEvents = vi.fn();
    const newStream = agent.stream("新请求", null, newEvents);
    await vi.waitFor(() => expect(newer.body.locked).toBe(true));

    if (settle === "resolve") old.resolve(responseWithChunks([encoder.encode('event: final\ndata: {}\n\n')]));
    else old.reject(new Error("旧请求异常"));
    await oldStream;

    expect(oldEvents).not.toHaveBeenCalled();
    expect(agent.phase.value).toBe("running");
    expect(agent.busy.value).toBe(true);
    newer.controller.enqueue(encoder.encode('event: final\ndata: {"plain":"新结果"}\n\n'));
    newer.controller.close();
    await newStream;
    expect(newEvents).toHaveBeenCalledTimes(1);
    expect(newEvents).toHaveBeenCalledWith({ event: "final", data: { plain: "新结果" } });
  });

  it("作用域销毁时中止请求、取消读取并丢弃后续回调", async () => {
    const active = openResponse();
    const fetch = vi.fn().mockResolvedValue(active.response);
    vi.stubGlobal("fetch", fetch);
    const { agent, scope } = createAgent();
    const onEvent = vi.fn();
    const stream = agent.stream("", null, onEvent);
    await vi.waitFor(() => expect(active.body.locked).toBe(true));

    scope.stop();
    expect((fetch.mock.calls[0][1] as RequestInit).signal?.aborted).toBe(true);
    expect(active.cancel).toHaveBeenCalledTimes(1);
    await stream;
    expect(active.body.locked).toBe(false);
    expect(agent.busy.value).toBe(false);
    expect(onEvent).not.toHaveBeenCalled();
  });

  it.each(["http", "network"])("reset %s 失败会拒绝，调用者不能误清空聊天", async (mode) => {
    vi.stubGlobal("fetch", mode === "http"
      ? vi.fn().mockResolvedValue(new Response('{"detail":"重置暂时不可用"}', { status: 503 }))
      : vi.fn().mockRejectedValue(new Error("网络断开")));
    const { agent } = createAgent();
    const clearChat = vi.fn();

    await expect(agent.reset().then(clearChat)).rejects.toThrow(mode === "http" ? "重置暂时不可用" : "网络断开");

    expect(clearChat).not.toHaveBeenCalled();
    expect(agent.phase.value).toBe("error");
    expect(agent.busy.value).toBe(false);
  });
});
