"""与方舟 Chat API 协议打交道的纯函数：用量解析、错误翻译、可选参数协商的判断。

从 llm.py 拆出来的原因：llm.py 负责「发请求、熔断、路由、流式」这些有状态的事；
这里只是「看一眼响应 / 错误，给出结论」，没有状态、不依赖任何内部模块，单独测试更直接。
（`tests/test_architecture.py` 的单文件 600 行上限在 llm.py 加入参数协商后被撞到，于是按职责拆开，而不是提高上限。）
"""
from __future__ import annotations

import json

# 「模型支持才有用」的可选参数。上游 400 时只在这些参数里找该去掉的，绝不动必填参数。
OPTIONAL_FIELDS = ("thinking", "reasoning_effort", "response_format", "prompt_cache_key", "stream_options")


def usage_numbers(usage: dict) -> dict:
    """把上游 usage 规范成五个整数。缓存与思考 token 在 *_details 里，旧模型没有这两个字段时记 0。"""
    def num(v):
        try:
            return max(int(v or 0), 0)
        except (TypeError, ValueError):
            return 0
    pd = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), dict) else {}
    cd = usage.get("completion_tokens_details") if isinstance(usage.get("completion_tokens_details"), dict) else {}
    return {"prompt_tokens": num(usage.get("prompt_tokens")), "completion_tokens": num(usage.get("completion_tokens")),
            "total_tokens": num(usage.get("total_tokens")), "cached_tokens": num(pd.get("cached_tokens")),
            "reasoning_tokens": num(cd.get("reasoning_tokens"))}


def error_text(e: Exception) -> str:
    """HTTPError 的响应体只能读一次：读出来挂在异常上，协商与错误翻译共用。"""
    cached = getattr(e, "_mt_body", None)
    if cached is not None:
        return cached
    try:
        raw = e.read(4096).decode("utf-8", "replace")  # type: ignore[attr-defined]
    except Exception:
        raw = ""
    try:
        e._mt_body = raw  # type: ignore[attr-defined]
    except Exception:
        pass
    return raw


def rejected_optional_fields(e: Exception, body: dict) -> list[str]:
    """400 时判断该去掉哪些可选参数：错误信息点名的优先；点不出名就全部去掉（成本最多一次重试）。"""
    present = [f for f in OPTIONAL_FIELDS if f in body]
    if getattr(e, "code", None) != 400 or not present:
        return []
    text = error_text(e).lower()
    named = [f for f in present if f in text]
    drop = named or present
    if "thinking" in drop and "reasoning_effort" in body and "reasoning_effort" not in drop:
        drop.append("reasoning_effort")
    return drop


def describe_http_error(e: Exception) -> str:
    """把上游 HTTP 错误翻成人能看懂的一句话。

    为什么要翻：`HTTP Error 403: Forbidden` 在日志里出现时，看的人第一反应是
    「权限配置错了」，要翻半天代码。而方舟的 403 实际最常见的原因是**账户欠费**
    （body 里写着 AccountOverdueError）。把 body 里的 code 提出来，
    一眼就知道该去充值还是该改 Key。
    """
    code = getattr(e, "code", None)
    if code is None:
        return f"{type(e).__name__}: {e}"
    try:
        raw = error_text(e)
        body = json.loads(raw)
        err = body.get("error") or {}
        upstream = err.get("code") or err.get("type") or ""
        msg = err.get("message") or raw[:200]
    except Exception:
        upstream, msg = "", ""
    finally:
        try:
            e.close()  # type: ignore[attr-defined]
        except Exception:
            pass
    hints = {
        "AccountOverdueError": "账户欠费，请到火山方舟控制台充值",
        "AuthenticationError": "API Key 无效或已过期",
        "InvalidApiKey": "API Key 无效或已过期",
        "ModelNotOpen": "该模型未在控制台开通",
        "ModelAccountNotOpen": "该模型未在控制台开通",
        "RateLimitExceeded": "触发上游限流（RPM/TPM），稍后重试",
        "QuotaExceeded": "额度已用尽（免费额度/资源包），请充值或等待重置",
        "SetLimitExceeded": "已触发账户设置的用量上限（安全体验模式），请到控制台调整",
        "ServerOverloaded": "上游服务繁忙，稍后重试",
    }
    hint = hints.get(upstream, "")
    if not hint:
        hint = next((v for k, v in hints.items() if upstream.startswith(k)), "")
    head = f"HTTP {code}"
    if upstream:
        head += f" {upstream}"
    if hint:
        return f"{head}：{hint}"
    if code == 429:
        return f"{head}：触发限流或额度已用尽（{msg}）" if msg else f"{head}：触发限流或额度已用尽"
    return f"{head}：{msg}"
