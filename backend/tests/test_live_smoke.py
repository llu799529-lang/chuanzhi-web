"""evals/live_smoke.py 的离线测试：假传输模拟上游，验证「省额度」的承诺真的成立。

不发网络请求、不耗额度。锁住的承诺：
  · 正常情况恰好 6 次请求（不测图片 5 次）；
  · 第一个探针失败立即停止，后面的一次都不发；
  · 请求数到硬上限立即停止（参数协商的重试也算）；
  · 上游不认的参数会出现在报告与 .env 建议里；
  · 报告里没有 API Key、没有模型返回的全文。
"""
import importlib.util
import io
import json
import urllib.error

import pytest

import config
import llm

_spec = importlib.util.spec_from_file_location("live_smoke", __import__("pathlib").Path(__file__).resolve().parent.parent / "evals" / "live_smoke.py")
smoke_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(smoke_mod)

SECRET = "0a1b2c3d-4e5f-6789-abcd-ef0123456789"
SYMPTOM_JSON = {"hits": ["头晕"], "echo": "晨起头晕两天", "dept": "神经内科", "urg": "黄色 · 建议 1–2 周内就诊",
                "alt": "", "suspects": [["良性阵发性位置性眩晕", 45, "体位改变诱发"]], "tests": ["前庭功能检查"],
                "prep": ["记录发作时间"], "reds": []}
FUNDUS_JSON = {"kind": "fundus", "level": 1, "probabilities": [20, 50, 20, 7, 3], "lesions": [], "summary": "x",
               "department": "眼科", "urgency": "green", "urgency_label": "常规"}


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


class Stream:
    def __iter__(self):
        yield b'data: {"choices":[{"delta":{"content":"\xe7\xb3\x96\xe7\xbd\x91\xe6\x98\xaf\xe7\x9c\xbc\xe5\xba\x95\xe7\x97\x85"},"finish_reason":"stop"}]}\n\n'
        yield b'data: {"choices":[],"usage":{"prompt_tokens":20,"completion_tokens":10,"total_tokens":30}}\n\n'
        yield b"data: [DONE]\n\n"

    def close(self):
        pass


def msg(content=None, calls=None, usage=None):
    m = {"role": "assistant", "content": content}
    if calls:
        m["tool_calls"] = calls
    out = {"choices": [{"message": m}]}
    out["usage"] = usage or {"prompt_tokens": 50, "completion_tokens": 5, "total_tokens": 55}
    return out


def has_image(body):
    return any(isinstance(m.get("content"), list) and any(p.get("type") == "image_url" for p in m["content"])
               for m in body["messages"])


def upstream(reject=None, fail_first=False):
    """按请求内容返回合理的假响应。reject(body) 返回非空字符串时以 400 拒绝。"""
    sent = []

    def request(body, timeout, stream=False):
        llm._REQUESTS[0] += 1                      # 真实 _request 会计数；替身也必须计数，预算逻辑才可测
        sent.append(json.loads(json.dumps(body)))
        if fail_first:
            raise urllib.error.HTTPError("https://x", 401, "x", {}, io.BytesIO(
                json.dumps({"error": {"code": "AuthenticationError", "message": "bad key"}}).encode()))
        why = reject(body) if reject else ""
        if why:
            raise urllib.error.HTTPError("https://x", 400, "x", {}, io.BytesIO(
                json.dumps({"error": {"code": "InvalidParameter", "message": why}}).encode()))
        if stream:
            return Stream()
        if has_image(body):
            return Resp(msg(json.dumps(FUNDUS_JSON)))
        if body.get("tools"):
            if body["max_tokens"] == 16:          # 缓存探针：同前缀第二次
                return Resp(msg("ok", usage={"prompt_tokens": 1500, "completion_tokens": 3, "total_tokens": 1503,
                                             "prompt_tokens_details": {"cached_tokens": 1408}}))
            return Resp(msg(None, calls=[{"id": "c1", "type": "function", "function": {
                "name": "search_kb", "arguments": json.dumps({"query": "咳嗽 黄痰"}, ensure_ascii=False)}}]))
        if body["messages"][0]["role"] == "system":
            return Resp(msg(json.dumps(SYMPTOM_JSON, ensure_ascii=False)))
        return Resp(msg("收到"))
    return sent, request


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "LLM_API_KEY", SECRET)
    monkeypatch.setattr(config, "LLM_MODEL", "deepseek-v4-flash-ga-260731")
    monkeypatch.setattr(config, "LLM_VISION_MODEL", "deepseek-v4-flash-ga-260731")
    monkeypatch.setattr(config, "LLM_FALLBACK_MODEL", "deepseek-v4-flash-ga-260731")
    monkeypatch.setattr(config, "LLM_ALLOW_PAID_FALLBACK", False)
    monkeypatch.setattr(config, "LLM_THINKING", "off")
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(llm, "_FAIL_COUNT", 0)
    monkeypatch.setattr(llm, "_UNSUPPORTED", set())
    monkeypatch.setattr(llm, "_USAGE_HOOKS", [])
    monkeypatch.setattr(smoke_mod, "REPORT", tmp_path / "report.json")


def run(monkeypatch, *args, **up):
    sent, request = upstream(**up)
    monkeypatch.setattr(llm, "_request", request)
    code = smoke_mod.main(list(args))
    return code, sent, json.loads(smoke_mod.REPORT.read_text(encoding="utf-8"))


def test_happy_path_uses_exactly_the_planned_six_requests(monkeypatch):
    code, sent, rep = run(monkeypatch)
    assert code == 0 and len(sent) == 6 and rep["requests"] == 6
    assert rep["passed"] == rep["total"] == 5 and rep["stopped"] == ""
    assert rep["results"]["tools"]["tool_calls"] == ["search_kb"]
    assert rep["results"]["cache"]["cache_hit"] is True and rep["tokens"]["cached_tokens"] == 1408
    assert rep["results"]["stream"]["usage_reported"] is True and rep["results"]["image"]["kind"] == "fundus"
    assert rep["suggested_env"] == []


def test_no_image_saves_the_most_expensive_call(monkeypatch):
    code, sent, rep = run(monkeypatch, "--no-image")
    assert code == 0 and len(sent) == 5 and "image" not in rep["results"]
    assert not any(has_image(b) for b in sent)


def test_first_failure_stops_everything(monkeypatch):
    code, sent, rep = run(monkeypatch, fail_first=True)
    assert code == 1 and len(sent) == 1 and list(rep["results"]) == ["text"]
    assert "API Key 无效" in rep["results"]["text"]["error"] and rep["stopped"]


def test_rejected_parameters_are_reported_and_turned_into_env_advice(monkeypatch):
    code, sent, rep = run(monkeypatch, reject=lambda b: "thinking is not supported" if "thinking" in b else "")
    assert rep["unsupported_params"] == ["thinking"] and len(sent) == 7          # 只多一次协商重试
    assert any(t.startswith("LLM_THINKING=omit") for t in rep["suggested_env"])


def test_hard_cap_stops_before_overspending(monkeypatch):
    code, sent, rep = run(monkeypatch, "--cap", "3")
    assert len(sent) <= 3 and "上限" in rep["stopped"] and code == 1


def test_image_rejection_suggests_a_vision_model(monkeypatch):
    code, sent, rep = run(monkeypatch, reject=lambda b: "image input is not supported" if has_image(b) else "")
    assert rep["results"]["image"]["ok"] is False
    assert any(t.startswith("ARK_VISION_MODEL=") for t in rep["suggested_env"])


def test_report_never_contains_the_key_or_full_model_output(monkeypatch):
    _, _, rep = run(monkeypatch)
    raw = json.dumps(rep, ensure_ascii=False)
    assert SECRET not in raw and "良性阵发性位置性眩晕" not in raw


def test_dry_run_sends_nothing(monkeypatch):
    sent, request = upstream()
    monkeypatch.setattr(llm, "_request", request)
    assert smoke_mod.main(["--dry-run"]) == 0 and sent == []


def test_paid_fallback_is_forced_off_even_if_env_enabled_it(monkeypatch):
    monkeypatch.setattr(config, "LLM_ALLOW_PAID_FALLBACK", True)
    run(monkeypatch, "--no-image")
    assert config.LLM_ALLOW_PAID_FALLBACK is False
