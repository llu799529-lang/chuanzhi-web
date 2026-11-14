"""可选参数协商 · 上下文缓存路由键 · 用量（含缓存命中）解析。

全部离线：`_request` 被替换，不发任何网络请求、不消耗额度。
动机：正式版模型的文档没写清它认哪些可选参数（thinking / response_format / prompt_cache_key …），
猜错一个就是每次请求 400。这里锁住「最多多花一次请求、而且只在确实被拒时才停发」。
"""
import copy
import io
import json
import urllib.error

import pytest

import config
import db
import llm
import llm_protocol


class Resp:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self.payload).encode()

    def close(self):
        pass


def answer(text="ok", usage=None):
    out = {"choices": [{"message": {"role": "assistant", "content": text}}]}
    if usage:
        out["usage"] = usage
    return out


def http_error(code, message):
    body = json.dumps({"error": {"code": "InvalidParameter", "message": message}}).encode()
    return urllib.error.HTTPError("https://offline.invalid", code, "err", {}, io.BytesIO(body))


SYSTEM = [{"role": "system", "content": "你是分诊助手。" * 40}, {"role": "user", "content": "头晕"}]


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "_FAIL_COUNT", 0)
    monkeypatch.setattr(llm, "_UNSUPPORTED", set())
    monkeypatch.setattr(llm, "_log_usage", lambda *a: None)
    monkeypatch.setattr(config, "LLM_MODEL", "m")
    monkeypatch.setattr(config, "LLM_VISION_MODEL", "m")
    monkeypatch.setattr(config, "LLM_FALLBACK_MODEL", "m")
    monkeypatch.setattr(config, "LLM_ALLOW_PAID_FALLBACK", False)
    monkeypatch.setattr(config, "LLM_THINKING", "off")
    monkeypatch.setattr(config, "LLM_JSON_MODE", "auto")
    monkeypatch.setattr(config, "LLM_PROMPT_CACHE", "auto")


def scripted(monkeypatch, reject):
    """reject(body) 返回错误信息就 400，否则成功。返回发出的请求体列表。"""
    bodies = []

    def request(body, timeout, stream=False):
        bodies.append(copy.deepcopy(body))
        msg = reject(body)
        if msg:
            raise http_error(400, msg)
        return Resp(answer('{"a": 1}'))
    monkeypatch.setattr(llm, "_request", request)
    return bodies


# ---------------------------------------------------------------- 协商
def test_a_named_parameter_is_dropped_and_never_sent_again(monkeypatch):
    bodies = scripted(monkeypatch, lambda b: "unknown field: thinking" if "thinking" in b else "")
    llm.chat(SYSTEM)
    llm.chat(SYSTEM)
    assert ["thinking" in b for b in bodies] == [True, False, False]   # 第一次被拒 → 重试 → 之后不再发
    assert llm._UNSUPPORTED == {"thinking"} and "prompt_cache_key" in bodies[-1]


def test_thinking_rejection_also_stops_reasoning_effort(monkeypatch):
    monkeypatch.setattr(config, "LLM_THINKING", "on")
    monkeypatch.setattr(config, "LLM_REASONING_EFFORT", "high")
    bodies = scripted(monkeypatch, lambda b: "thinking is not supported for this model" if "thinking" in b else "")
    llm.chat(SYSTEM)
    assert "reasoning_effort" not in bodies[-1] and {"thinking", "reasoning_effort"} <= llm._UNSUPPORTED


def test_an_unnamed_400_drops_all_optional_parameters_once(monkeypatch):
    bodies = scripted(monkeypatch, lambda b: "InvalidParameter" if any(f in b for f in llm_protocol.OPTIONAL_FIELDS) else "")
    llm.chat_json("sys" * 50, "user")
    assert len(bodies) == 2 and not any(f in bodies[1] for f in llm_protocol.OPTIONAL_FIELDS)
    assert llm.runtime_info()["unsupported_params"] == sorted({"thinking", "response_format", "prompt_cache_key"})


def test_a_400_unrelated_to_optional_parameters_marks_nothing(monkeypatch):
    """比如图片太大：去掉可选参数重试仍然 400 → 原样报错，不能把正常参数误判成不支持。"""
    bodies = scripted(monkeypatch, lambda b: "image too large")
    with pytest.raises(RuntimeError, match="HTTP 400"):
        llm.chat(SYSTEM)
    assert len(bodies) == 2 and llm._UNSUPPORTED == set()


def test_non_400_errors_are_never_negotiated(monkeypatch):
    calls = []

    def request(body, timeout, stream=False):
        calls.append(1)
        raise http_error(429, "thinking rate limited")
    monkeypatch.setattr(llm, "_request", request)
    with pytest.raises(RuntimeError):
        llm.chat(SYSTEM)
    assert calls == [1] and llm._UNSUPPORTED == set()


def test_streaming_requests_negotiate_too(monkeypatch):
    class Stream:
        def __iter__(self):
            yield b'data: {"choices":[{"delta":{"content":"hi"},"finish_reason":"stop"}]}\n\n'
            yield b"data: [DONE]\n\n"

        def close(self):
            pass
    bodies = []

    def request(body, timeout, stream=False):
        bodies.append(copy.deepcopy(body))
        if "stream_options" in body:
            raise http_error(400, "stream_options is not supported")
        return Stream()
    monkeypatch.setattr(llm, "_request", request)
    assert "".join(llm.stream_chat(SYSTEM)) == "hi"
    assert llm._UNSUPPORTED == {"stream_options"} and len(bodies) == 2


def test_the_error_body_is_still_translated_after_negotiation_read_it(monkeypatch):
    e = http_error(400, "boom")
    assert llm_protocol.error_text(e) == llm_protocol.error_text(e)              # 读一次、缓存在异常上
    assert "boom" in llm._describe_http_error(e)


# ---------------------------------------------------------------- 缓存路由键
def test_cache_key_depends_only_on_the_system_prompt_and_tool_names():
    a = llm._cache_payload([{"role": "system", "content": "S"}, {"role": "user", "content": "张三 13800001111"}])
    b = llm._cache_payload([{"role": "system", "content": "S"}, {"role": "user", "content": "完全不同的问题"}])
    c = llm._cache_payload([{"role": "system", "content": "S2"}, {"role": "user", "content": "x"}])
    t = llm._cache_payload([{"role": "system", "content": "S"}], tools=[{"function": {"name": "search_kb"}}])
    assert a == b and a != c and a != t
    assert a["prompt_cache_key"].startswith("mt-") and "1380000" not in a["prompt_cache_key"]


def test_no_system_prompt_or_config_off_means_no_cache_key(monkeypatch):
    assert llm._cache_payload([{"role": "user", "content": "x"}]) == {}
    monkeypatch.setattr(config, "LLM_PROMPT_CACHE", "off")
    assert llm._cache_payload([{"role": "system", "content": "S"}]) == {}


def test_agent_system_prompt_is_a_stable_cacheable_prefix():
    """缓存要命中，前缀必须稳定且 ≥128 tokens：每个会话的第一条消息就是同一个常量系统提示，不拼用户数据。"""
    import agent2
    assert len(agent2.system_prompt()) >= 400                # 中文约 1 字 ≈ 1 token，远超 128 的最小命中长度
    a, b = agent2._new(), agent2._new()
    # 同一部署（是否配置高德 Web 服务 Key）下系统提示是固定文本：每个会话的第一条消息完全相同
    assert a["messages"][0] == b["messages"][0] == {"role": "system", "content": agent2.system_prompt()}
    assert llm._cache_payload(a["messages"], agent2.TOOLS) == llm._cache_payload(b["messages"], agent2.TOOLS)


# ---------------------------------------------------------------- 用量
def test_usage_numbers_read_cached_and_reasoning_tokens_and_tolerate_garbage():
    u = llm_protocol.usage_numbers({"prompt_tokens": 1200, "completion_tokens": 80, "total_tokens": 1280,
                           "prompt_tokens_details": {"cached_tokens": 1024},
                           "completion_tokens_details": {"reasoning_tokens": 30}})
    assert u == {"prompt_tokens": 1200, "completion_tokens": 80, "total_tokens": 1280,
                 "cached_tokens": 1024, "reasoning_tokens": 30}
    assert llm_protocol.usage_numbers({"prompt_tokens": "x", "prompt_tokens_details": None})["cached_tokens"] == 0


def test_usage_hooks_see_every_call_and_cannot_break_it(monkeypatch):
    monkeypatch.undo()                                        # 用真实 _log_usage（写临时库）
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "_UNSUPPORTED", set())
    seen = []

    def bad(model, u):
        raise RuntimeError("hook bug")
    llm.add_usage_hook(lambda m, u: seen.append(u))
    llm.add_usage_hook(bad)
    try:
        monkeypatch.setattr(llm, "_request", lambda body, timeout, stream=False: Resp(answer("ok", {
            "prompt_tokens": 300, "completion_tokens": 5, "total_tokens": 305, "prompt_tokens_details": {"cached_tokens": 256}})))
        assert llm.chat(SYSTEM, username="hook_user")["content"] == "ok"
    finally:
        llm._USAGE_HOOKS.clear()
    assert seen and seen[0]["cached_tokens"] == 256
    with db.get_conn() as conn:
        row = conn.execute("SELECT cached_tokens FROM llm_usage WHERE username = 'hook_user'").fetchone()
    assert row["cached_tokens"] == 256


def test_old_databases_get_the_new_columns_without_losing_rows(tmp_path, monkeypatch):
    import sqlite3
    path = tmp_path / "medtriage.db"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE llm_usage (id INTEGER PRIMARY KEY, model TEXT, prompt_tokens INTEGER,"
                     " completion_tokens INTEGER, total_tokens INTEGER, created_at TEXT NOT NULL, username TEXT)")
        conn.execute("INSERT INTO llm_usage (model, prompt_tokens, created_at) VALUES ('old', 5, '2026-01-01')")
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    db.init_db()
    db.init_db()                                                # 幂等：第二次不报 duplicate column
    with db.get_conn() as conn:
        row = conn.execute("SELECT model, prompt_tokens, cached_tokens FROM llm_usage").fetchone()
    assert (row["model"], row["prompt_tokens"], row["cached_tokens"]) == ("old", 5, 0)
