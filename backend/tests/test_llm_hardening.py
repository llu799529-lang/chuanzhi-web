"""Offline contract tests for the outgoing LLM boundary and stream lifecycle."""
import asyncio
import copy
import io
import json
import urllib.error

import pytest

import config
import llm


class Response:
    def __init__(self, data=None, lines=()):
        self.data = data
        self.lines = lines
        self.closed = False

    def read(self):
        return json.dumps(self.data).encode()

    def __iter__(self):
        for line in self.lines:
            if isinstance(line, BaseException):
                raise line
            yield line

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def event(payload):
    return ("data: " + json.dumps(payload) + "\n\n").encode()


def delta(text, finish_reason=None):
    return event({"choices": [{"delta": {"content": text}, "finish_reason": finish_reason}]})


def answer(text="ok"):
    return {"choices": [{"message": {"role": "assistant", "content": text}}]}


@pytest.fixture(autouse=True)
def offline_llm(monkeypatch):
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "_FAIL_COUNT", 0)
    monkeypatch.setattr(llm, "_SWITCHED_AT", 0.0)
    monkeypatch.setattr(config, "LLM_MODEL", "primary")
    monkeypatch.setattr(config, "LLM_VISION_MODEL", "vision")
    monkeypatch.setattr(config, "LLM_FALLBACK_MODEL", "fallback")
    monkeypatch.setattr(config, "LLM_ALLOW_PAID_FALLBACK", False)
    monkeypatch.setattr(config, "LLM_THINKING", "off")
    monkeypatch.setattr(config, "LLM_PROVIDER", "ark")
    monkeypatch.setattr(llm, "_log_usage", lambda *args: None)

    def no_network(*args, **kwargs):
        raise AssertionError("Tests must not send real model requests")

    monkeypatch.setattr(llm.urllib.request, "urlopen", no_network)


def capture_requests(monkeypatch, *responses):
    requests = []
    remaining = iter(responses)

    def request(body, timeout, stream=False):
        requests.append((copy.deepcopy(body), timeout, stream))
        response = next(remaining)
        if isinstance(response, BaseException):
            raise response
        return response

    monkeypatch.setattr(llm, "_request", request)
    return requests


@pytest.mark.parametrize("stream", [False, True])
def test_boundary_masks_text_and_json_without_touching_inputs_or_images(monkeypatch, stream):
    image = {"type": "image_url", "image_url": {
        "url": "data:image/jpeg;base64,AA13800138000AA", "detail": "high"}}
    messages = [
        {"role": "system", "content": "联系 someone@example.com"},
        {"role": "user", "content": [
            {"type": "text", "text": "13800138000 110101199003071234"}, image]},
        {"role": "assistant", "content": None, "tool_calls": [{
            "id": "call-1", "type": "function", "function": {
                "name": "lookup", "arguments": json.dumps({"phone": 13800138000,
                "email": "someone@example.com", "nested": [{"id": "110101199003071234"}],
                "age": 42, "enabled": True})}}]},
        {"role": "tool", "tool_call_id": "call-1", "content":
         '{"phone":13800138000,"note":"someone@example.com"}'},
    ]
    original = copy.deepcopy(messages)
    response = Response(lines=[delta("ok"), b"data: [DONE]\n\n"]) if stream else Response(answer())
    requests = capture_requests(monkeypatch, response)
    if stream:
        assert list(llm.stream_chat(messages)) == ["ok"]
    else:
        assert llm.chat(messages)["content"] == "ok"
    sent = requests[0][0]["messages"]
    assert sent[0]["content"] == "联系 [邮箱]"
    assert sent[1]["content"][0]["text"] == "[手机号] [身份证]"
    assert sent[1]["content"][1] == image
    args = json.loads(sent[2]["tool_calls"][0]["function"]["arguments"])
    assert args == {"phone": "[手机号]", "email": "[邮箱]", "nested": [{"id": "[身份证]"}],
                    "age": 42, "enabled": True}
    assert json.loads(sent[3]["content"]) == {"phone": "[手机号]", "note": "[邮箱]"}
    assert messages == original
    assert response.closed


def test_legacy_function_arguments_are_masked_as_valid_json(monkeypatch):
    requests = capture_requests(monkeypatch, Response(answer()))
    llm.chat([{"role": "assistant", "content": None, "function_call": {
        "name": "lookup", "arguments": '{"phone":13800138000}'}}])
    assert json.loads(requests[0][0]["messages"][0]["function_call"]["arguments"]) == {
        "phone": "[手机号]"}


def test_fallback_success_keeps_primary_failures_and_uses_own_parameters(monkeypatch):
    monkeypatch.setattr(config, "LLM_ALLOW_PAID_FALLBACK", True)
    requests = capture_requests(monkeypatch, OSError("offline"), Response(answer()))
    assert llm.chat([{"role": "user", "content": "hi"}])["content"] == "ok"
    assert llm._FAIL_COUNT == 1
    assert requests[0][0]["thinking"] == {"type": "disabled"}
    assert "thinking" not in requests[1][0]
    assert [r[0]["model"] for r in requests] == ["primary", "fallback"]


@pytest.mark.parametrize("successful", [False, True])
def test_vision_requests_do_not_change_primary_breaker(monkeypatch, successful):
    monkeypatch.setattr(llm, "_FAIL_COUNT", 2)
    response = Response(answer()) if successful else OSError("vision unavailable")
    capture_requests(monkeypatch, response)
    messages = [{"role": "user", "content": [{"type": "image_url", "image_url": {"url": "image"}}]}]
    if successful:
        llm.chat(messages)
    else:
        with pytest.raises(RuntimeError, match="vision unavailable"):
            llm.chat(messages)
    assert llm._FAIL_COUNT == 2


def test_open_breaker_cannot_select_paid_model_when_disabled(monkeypatch):
    monkeypatch.setattr(llm, "_FAIL_COUNT", llm._FAIL_THRESHOLD)
    monkeypatch.setattr(llm, "_SWITCHED_AT", llm.time.time())
    assert llm._pick_model([]) == "primary"


def test_cooldown_failure_reopens_breaker_and_primary_success_resets_it(monkeypatch):
    monkeypatch.setattr(config, "LLM_ALLOW_PAID_FALLBACK", True)
    now = [1000.0]
    monkeypatch.setattr(llm.time, "time", lambda: now[0])
    monkeypatch.setattr(llm, "_FAIL_COUNT", llm._FAIL_THRESHOLD)
    monkeypatch.setattr(llm, "_SWITCHED_AT", 1.0)
    assert llm._pick_model([]) == "primary"
    capture_requests(monkeypatch, OSError("offline"), Response(answer()))
    llm.chat([])
    assert llm._pick_model([]) == "fallback"
    now[0] += llm._SWITCH_COOLDOWN + 1
    assert llm._pick_model([]) == "primary"
    capture_requests(monkeypatch, Response(answer()))
    llm.chat([])
    assert llm._FAIL_COUNT == 0


@pytest.mark.parametrize("mode", ["off", "on", "auto"])
def test_thinking_is_only_sent_to_supported_primary_model(monkeypatch, mode):
    monkeypatch.setattr(config, "LLM_THINKING", mode)
    assert llm._thinking_payload("vision") == {}
    assert llm._thinking_payload("fallback") == {}


@pytest.mark.parametrize("data", [None, [], {}, {"choices": []}, {"choices": [None]},
    {"choices": [{"message": "wrong"}]}, {"choices": [{"message": {"content": 7}}]},
    {"choices": [{"message": {"content": None}}]}, {"error": {"message": "upstream denied"}}])
def test_chat_rejects_invalid_upstream_shape_with_clear_error(monkeypatch, data):
    response = Response(data)
    capture_requests(monkeypatch, response)
    with pytest.raises(RuntimeError, match="(?i)(response|upstream|模型|上游)"):
        llm.chat([])
    assert response.closed
    assert llm._FAIL_COUNT == 1


def test_chat_accepts_tool_call_only_response(monkeypatch):
    message = {"role": "assistant", "content": None, "tool_calls": [{
        "id": "call-1", "type": "function", "function": {"name": "lookup", "arguments": "{}"}}]}
    capture_requests(monkeypatch, Response({"choices": [{"message": message}]}))
    assert llm.chat([]) == message


@pytest.mark.parametrize("text", ["[]", '[{"answer": 1}]', "true", '"text"', "42", "null",
    '"not an object: {}"'])
def test_chat_json_repairs_non_object_output_once(monkeypatch, text):
    outputs = iter([text, '{"answer": 1}'])
    prompts = []

    def chat_text(messages, **kwargs):
        prompts.append(messages)
        return next(outputs)

    monkeypatch.setattr(llm, "chat_text", chat_text)
    assert llm.chat_json("system", "question") == {"answer": 1}
    assert len(prompts) == 2


def test_chat_json_rejects_array_after_repair(monkeypatch):
    calls = []
    monkeypatch.setattr(llm, "chat_text", lambda *args, **kwargs: calls.append(args) or "[]")
    with pytest.raises(ValueError, match="(?i)(object|对象)"):
        llm.chat_json("system", "question")
    assert len(calls) == 2


@pytest.mark.parametrize("lines", [
    [], [delta("partial")], [b"data: not-json\n\n"], [event([])],
    [event({"error": {"message": "upstream denied"}})],
    [b"event: error\n", b'data: {"message":"denied"}\n\n'],
    [event({"choices": [{"delta": {"content": 7}}]})],
    [event({"choices": "wrong"})], [event({"choices": [None]})],
    [event({"choices": [{"delta": "wrong"}]})], [delta("partial"), OSError("connection lost")],
])
def test_stream_errors_are_not_silent_success(monkeypatch, lines):
    response = Response(lines=lines)
    capture_requests(monkeypatch, response)
    with pytest.raises(RuntimeError):
        list(llm.stream_chat([]))
    assert response.closed
    assert llm._FAIL_COUNT == 1


@pytest.mark.parametrize("terminator", [b"data: [DONE]\n\n", delta(None, "stop")])
def test_stream_accepts_completion_and_usage_only_chunk(monkeypatch, terminator):
    usage = {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}
    recorded = []
    monkeypatch.setattr(llm, "_log_usage", lambda *args: recorded.append(args))
    response = Response(lines=[b": heartbeat\n", delta("ok"),
        event({"choices": [], "usage": usage}), terminator])
    capture_requests(monkeypatch, response)
    assert list(llm.stream_chat([], username="user")) == ["ok"]
    assert recorded == [("primary", usage, "user")]
    assert response.closed


def test_stream_requests_usage_and_uses_configured_timeout(monkeypatch):
    requests = capture_requests(monkeypatch, Response(lines=[b"data: [DONE]\n\n"]))
    list(llm.stream_chat([]))
    assert requests[0][1] == config.LLM_TIMEOUT_SECONDS
    assert requests[0][0]["stream_options"] == {"include_usage": True}


def test_unknown_provider_omits_stream_options(monkeypatch):
    monkeypatch.setattr(config, "LLM_PROVIDER", "custom")
    requests = capture_requests(monkeypatch, Response(lines=[b"data: [DONE]\n\n"]))
    list(llm.stream_chat([], timeout=17))
    assert requests[0][1] == 17
    assert "stream_options" not in requests[0][0]


@pytest.mark.parametrize("failure", [OSError("cannot open"),
    Response(lines=[event({"error": {"message": "denied"}})])])
def test_stream_can_fallback_before_first_visible_token(monkeypatch, failure):
    monkeypatch.setattr(config, "LLM_ALLOW_PAID_FALLBACK", True)
    fallback = Response(lines=[delta("ok"), b"data: [DONE]\n\n"])
    requests = capture_requests(monkeypatch, failure, fallback)
    assert list(llm.stream_chat([])) == ["ok"]
    assert [r[0]["model"] for r in requests] == ["primary", "fallback"]
    assert "thinking" not in requests[1][0]
    assert llm._FAIL_COUNT == 1
    assert fallback.closed
    if isinstance(failure, Response):
        assert failure.closed


def test_stream_does_not_retry_after_visible_output(monkeypatch):
    monkeypatch.setattr(config, "LLM_ALLOW_PAID_FALLBACK", True)
    response = Response(lines=[delta("partial"), OSError("interrupted")])
    requests = capture_requests(monkeypatch, response)
    stream = llm.stream_chat([])
    assert next(stream) == "partial"
    with pytest.raises(RuntimeError, match="interrupted"):
        next(stream)
    assert len(requests) == 1
    assert response.closed


@pytest.mark.parametrize("cancel", [False, True])
def test_stream_cancellation_closes_response_without_changing_breaker(monkeypatch, cancel):
    monkeypatch.setattr(llm, "_FAIL_COUNT", 2)
    response = Response(lines=[delta("partial"), asyncio.CancelledError()])
    capture_requests(monkeypatch, response)
    stream = llm.stream_chat([])
    assert next(stream) == "partial"
    if cancel:
        with pytest.raises(asyncio.CancelledError):
            next(stream)
    else:
        stream.close()
    assert response.closed
    assert llm._FAIL_COUNT == 2


def test_stream_fallback_success_does_not_clear_open_breaker(monkeypatch):
    monkeypatch.setattr(config, "LLM_ALLOW_PAID_FALLBACK", True)
    monkeypatch.setattr(llm, "_FAIL_COUNT", llm._FAIL_THRESHOLD)
    monkeypatch.setattr(llm, "_SWITCHED_AT", llm.time.time())
    requests = capture_requests(monkeypatch, Response(lines=[delta("ok"), b"data: [DONE]\n\n"]))
    assert list(llm.stream_chat([])) == ["ok"]
    assert requests[0][0]["model"] == "fallback"
    assert llm._FAIL_COUNT == llm._FAIL_THRESHOLD


@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize("allow_fallback", [False, True])
def test_http_error_response_is_closed_even_when_falling_back(monkeypatch, stream, allow_fallback):
    monkeypatch.setattr(config, "LLM_ALLOW_PAID_FALLBACK", allow_fallback)
    body = io.BytesIO(b'{"error":{"code":"RateLimitExceeded","message":"limited"}}')
    failure = urllib.error.HTTPError("https://offline.invalid", 429, "limited", {}, body)
    fallback = Response(lines=[delta("ok"), b"data: [DONE]\n\n"]) if stream else Response(answer())
    capture_requests(monkeypatch, failure, fallback)
    def call():
        return list(llm.stream_chat([])) if stream else llm.chat([])
    if allow_fallback:
        call()
    else:
        with pytest.raises(RuntimeError, match="HTTP 429"):
            call()
    assert body.closed


@pytest.mark.parametrize("stream", [False, True])
def test_repeated_primary_failures_open_breaker_despite_fallback_success(monkeypatch, stream):
    monkeypatch.setattr(config, "LLM_ALLOW_PAID_FALLBACK", True)
    responses = []
    for _ in range(llm._FAIL_THRESHOLD):
        responses.append(OSError("primary down"))
        responses.append(Response(lines=[delta("ok"), b"data: [DONE]\n\n"]) if stream else Response(answer()))
    requests = capture_requests(monkeypatch, *responses)
    for _ in range(llm._FAIL_THRESHOLD):
        list(llm.stream_chat([])) if stream else llm.chat([])
    assert len(requests) == 2 * llm._FAIL_THRESHOLD
    assert llm._pick_model([]) == "fallback"


def test_stream_accepts_usage_after_finish_reason_and_multiline_data(monkeypatch):
    usage = {"total_tokens": 6}
    recorded = []
    monkeypatch.setattr(llm, "_log_usage", lambda *args: recorded.append(args))
    response = Response(lines=[b'data: {"choices": [\n',
        b'data: {"delta": {"content": "ok"}}]}\n', b"\n",
        event({"choices": [{"finish_reason": "stop", "delta": None}]}),
        event({"usage": usage})])
    capture_requests(monkeypatch, response)
    assert list(llm.stream_chat([])) == ["ok"]
    assert recorded == [("primary", usage, None)]
    assert response.closed


@pytest.mark.parametrize("calls", ["wrong", [None], [{"id": "call-1", "function": {"name": "lookup"}}]])
def test_invalid_tool_call_shape_fails_before_consumers(monkeypatch, calls):
    capture_requests(monkeypatch, Response({"choices": [{"message": {"content": None, "tool_calls": calls}}]}))
    with pytest.raises(RuntimeError, match="upstream LLM response"):
        llm.chat([])


def test_stream_preserves_unicode_line_separators_inside_json_text(monkeypatch):
    text = "first\u2028second\u0085third"
    payload = json.dumps({"choices": [{"delta": {"content": text}}]}, ensure_ascii=False)
    response = Response(lines=[("data: " + payload + "\r\n").encode(), b"\r\n", b"data: [DONE]\n\n"])
    capture_requests(monkeypatch, response)
    assert list(llm.stream_chat([])) == [text]
    assert response.closed


@pytest.mark.parametrize("reason", ["length", "content_filter", "tool_calls", "function_call"])
def test_stream_rejects_incomplete_report_without_retry_after_visible_content(monkeypatch, reason):
    monkeypatch.setattr(config, "LLM_ALLOW_PAID_FALLBACK", True)
    response = Response(lines=[delta("partial report"), delta(None, reason), b"data: [DONE]\n\n"])
    requests = capture_requests(monkeypatch, response)
    stream = llm.stream_chat([])
    assert next(stream) == "partial report"
    with pytest.raises(RuntimeError, match="did not finish normally"):
        next(stream)
    assert len(requests) == 1
    assert llm._FAIL_COUNT == 1
    assert response.closed
