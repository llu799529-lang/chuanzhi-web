import { describe, expect, it } from "vitest";
import { parseSSE } from "@/composables/useAgentStream";

/**
 * SSE 解析是流式 Agent 的唯一入口：后端每推错一个字节，这里就是第一个
 * 能发现的地方。手写解析容易在三种边界上翻车，所以逐条锁住：
 *   1. data 里含换行（多行 data: 需要拼回一个 JSON）
 *   2. 事件名与数据之间有空行
 *   3. 后端推了非 JSON（降级提示），不能抛异常把整个流打断
 */
describe("parseSSE", () => {
  it("解析 event + data", () => {
    const ev = parseSSE('event: token\ndata: {"text": "你好"}');
    expect(ev).not.toBeNull();
    expect(ev!.event).toBe("token");
    expect(ev!.data).toEqual({ text: "你好" });
  });

  it("多行 data 拼接后再解析", () => {
    const ev = parseSSE('event: final\ndata: {"a": 1,\ndata: "b": 2}');
    expect(ev!.event).toBe("final");
    expect(ev!.data).toEqual({ a: 1, b: 2 });
  });

  it("没有 data 行时返回 null", () => {
    expect(parseSSE("event: token")).toBeNull();
    expect(parseSSE("")).toBeNull();
  });

  it("非 JSON 的 data 退化为 raw，不抛异常", () => {
    const ev = parseSSE("event: error\ndata: 服务暂时不可用");
    expect(ev!.event).toBe("error");
    expect(ev!.data).toEqual({ raw: "服务暂时不可用" });
  });

  it("缺少 event 名时按 message 处理", () => {
    const ev = parseSSE('data: {"x": 1}');
    expect(ev!.event).toBe("message");
    expect(ev!.data).toEqual({ x: 1 });
  });

  it("中文与 emoji 不被截断", () => {
    const ev = parseSSE('event: token\ndata: {"text": "胸口闷🫀"}');
    expect((ev!.data as { text: string }).text).toBe("胸口闷🫀");
  });

  it("兼容 CRLF 多行数据", () => {
    expect(parseSSE('event: final\r\ndata: {"a": 1,\r\ndata: "b": 2}'))
      .toEqual({ event: "final", data: { a: 1, b: 2 } });
  });

  it.each(["null", "[]", '"text"', "42", "true"])(
    "非对象 JSON %s 降级为 raw，保持消费者的数据契约",
    (raw) => {
      expect(parseSSE(`event: token\ndata: ${raw}`))
        .toEqual({ event: "token", data: { raw } });
    },
  );
});
