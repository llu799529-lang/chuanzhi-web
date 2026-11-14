"""DeepSeek 切换后的 llm.py 行为：JSON 模式自动降级、占位 Key、429 提示、用量估算接口。

全部离线：`_request` 被替换，不会发出任何网络请求，也不会消耗任何额度。
"""
import copy
import io
import json
import urllib.error

import pytest

import config
import llm

_REAL_LLM_AVAILABLE = llm.llm_available      # 在 autouse 夹具打补丁之前取到真实函数；不用 reload（会重置模块状态）


class Resp:
    def __init__(self, payload):
        self.payload, self.closed = payload, False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.closed = True
        return False

    def read(self):
        return json.dumps(self.payload).encode()

    def close(self):
        self.closed = True


def answer(text):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


@pytest.fixture(autouse=True)
def offline(monkeypatch):
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "_FAIL_COUNT", 0)
    monkeypatch.setattr(llm, "_SWITCHED_AT", 0.0)
    monkeypatch.setattr(llm, "_log_usage", lambda *a: None)
    monkeypatch.setattr(llm, "_UNSUPPORTED", set())
    monkeypatch.setattr(config, "LLM_MODEL", "m")
    monkeypatch.setattr(config, "LLM_VISION_MODEL", "m")
    monkeypatch.setattr(config, "LLM_FALLBACK_MODEL", "m")
    monkeypatch.setattr(config, "LLM_JSON_MODE", "auto")
    monkeypatch.setattr(config, "LLM_ALLOW_PAID_FALLBACK", False)


def _http_error(code, body):
    return urllib.error.HTTPError("https://x", code, "err", {}, io.BytesIO(json.dumps(body).encode()))


def test_chat_json_requests_json_object_mode(monkeypatch):
    bodies = []
    monkeypatch.setattr(llm, "_request", lambda body, timeout, stream=False: bodies.append(copy.deepcopy(body)) or Resp(answer('{"a": 1}')))
    assert llm.chat_json("sys", "user") == {"a": 1}
    assert bodies[0]["response_format"] == {"type": "json_object"}


def test_json_mode_rejected_with_400_is_disabled_and_retried_once(monkeypatch):
    bodies = []

    def request(body, timeout, stream=False):
        bodies.append(copy.deepcopy(body))
        if "response_format" in body:
            raise _http_error(400, {"error": {"code": "InvalidParameter", "message": "response_format not supported"}})
        return Resp(answer('{"a": 1}'))

    monkeypatch.setattr(llm, "_request", request)
    assert llm.chat_json("sys", "user") == {"a": 1}
    assert ["response_format" in b for b in bodies] == [True, False]
    assert llm._UNSUPPORTED == {"response_format"}       # 只去掉被点名的参数，thinking 等照常发送
    assert llm._FAIL_COUNT == 0                 # 400 不计入熔断
    llm.chat_json("sys", "again")
    assert "response_format" not in bodies[-1]   # 之后不再发送


def test_json_mode_can_be_disabled_by_config(monkeypatch):
    monkeypatch.setattr(config, "LLM_JSON_MODE", "off")
    bodies = []
    monkeypatch.setattr(llm, "_request", lambda body, timeout, stream=False: bodies.append(copy.deepcopy(body)) or Resp(answer('{"a": 1}')))
    llm.chat_json("sys", "user")
    assert "response_format" not in bodies[0]


def test_tool_calls_and_plain_chat_never_send_json_mode(monkeypatch):
    bodies = []
    monkeypatch.setattr(llm, "_request", lambda body, timeout, stream=False: bodies.append(copy.deepcopy(body)) or Resp(answer("ok")))
    llm.chat([{"role": "user", "content": "hi"}])
    llm.chat([{"role": "user", "content": "hi"}], tools=[{"type": "function", "function": {"name": "x"}}], json_mode=True)
    assert all("response_format" not in b for b in bodies)


def test_non_400_errors_are_not_swallowed_by_json_mode_retry(monkeypatch):
    monkeypatch.setattr(llm, "_request", lambda *a, **k: (_ for _ in ()).throw(_http_error(500, {"error": {"code": "InternalError", "message": "boom"}})))
    with pytest.raises(RuntimeError, match="HTTP 500"):
        llm.chat_json("sys", "user")


@pytest.mark.parametrize("key,usable", [
    ("", False), ("x", False), ("ark-xxxxxxxxxxxxxxxxxxxxxxxx", False), ("sk-your-key-here", False),
    ("ark-1234abcd-5678", True), ("0a1b2c3d-4e5f-6789-abcd-ef0123456789", True),
])
def test_placeholder_keys_do_not_count_as_configured(monkeypatch, key, usable):
    monkeypatch.setattr(config, "LLM_API_KEY", key)
    assert _REAL_LLM_AVAILABLE() is usable


@pytest.mark.parametrize("code,upstream,expect", [
    (429, "QuotaExceeded", "额度已用尽"),
    (429, "RateLimitExceeded.EndpointRPMExceeded", "限流"),
    (403, "AccountOverdueError", "欠费"),
    (429, "", "限流或额度已用尽"),
    (400, "SetLimitExceeded", "用量上限"),
])
def test_http_errors_are_translated_to_actionable_text(code, upstream, expect):
    err = _http_error(code, {"error": {"code": upstream, "message": "raw"}})
    assert expect in llm._describe_http_error(err)
