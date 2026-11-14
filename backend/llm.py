"""火山方舟大模型统一调用接口（OpenAI 兼容协议）。

v2 增强（对应「大模型集成质量」）：
  - chat() 返回完整 message（含 tool_calls），支持原生 Function Calling
  - stream_chat() SSE 流式生成器（Ark stream=true），逐 token yield
  - 用量计量：每次调用 token 数入库 llm_usage（成本估算见 pricing.py）
  - 主备模型熔断：主模型连续失败 3 次切备用模型，5 分钟冷却

v4（2026-10-24）默认模型改为 DeepSeek-V4-Flash 正式版（deepseek-v4-flash-ga-260731，有免费额度）：
  - 文本/视觉/兜底默认指向同一 ID，路由逻辑仍保留：V4-Flash 是否接受图片输入尚未实测，
    若带图请求被上游拒绝，在 .env 里把 ARK_VISION_MODEL 指向支持图片的模型
    （如经济版 deepseek-v4-1-flash-economy-261017）即可，不用改代码；
  - 付费兜底默认关闭：额度耗尽时由上层走离线规则，而不是悄悄换更贵的模型；
  - chat_json 默认带 response_format=json_object（上游 400 时自动关闭并重试，见 _send）；
  - 429/额度类错误翻译成人话（见 _describe_http_error），便于一眼看出是额度还是限流。

v5（2026-10-29）按方舟 Chat API 文档补齐两件事：
  - **可选参数协商**：`thinking` / `reasoning_effort` / `response_format` / `prompt_cache_key` / `stream_options`
    都是「模型支持才有用」的参数。正式版文档没写清支持哪些，所以不猜：先发，上游 400 且错误信息点名了
    某个参数（点不出名就把可选参数全去掉）→ 去掉重试一次 → **重试成功才**记入 `_UNSUPPORTED`，之后不再发送。
    最多多花一次请求，而且只在进程里第一次遇到时花。`runtime_info()` 把协商结果暴露给 /api/health。
  - **上下文缓存**：缓存命中价是输入价的 1/50（经济版闲时 0.016 vs 0.8 元/百万 tokens），最小命中长度 128 tokens。
    Agent 每一轮都重发「系统提示 + 工具定义 + 之前的对话」，天然是长且稳定的前缀。请求带上由系统提示
    （与工具名）哈希出的 `prompt_cache_key`，让同前缀的请求路由到同一份缓存；`usage.prompt_tokens_details.cached_tokens`
    入库，用量页按缓存价计费并显示命中率。键只由系统提示决定，不含任何用户数据。

路由判据只有一条：消息里有没有 `image_url`。路由错了的后果是两个方向都难看
（把图发给纯文本模型 = 400；把纯文字发给更贵的模型 = 白花钱且没人发现）。
"""
import copy
import hashlib
import json
import re
import time
import urllib.request

import config
import db
import guardrails
from llm_protocol import describe_http_error as _describe_http_error
from llm_protocol import rejected_optional_fields as _rejected_optional_fields
from llm_protocol import usage_numbers

_FAIL_COUNT = 0
_FAIL_THRESHOLD = 3
_SWITCHED_AT = 0.0
_SWITCH_COOLDOWN = 300  # 切到备用模型后 5 分钟内不切回


def _is_placeholder_key(key: str) -> bool:
    """`.env.example` 里的占位符（ark-xxxx…）或明显太短的值，不算「已配置」。

    否则复制示例文件忘了改 Key，会表现为每次请求都 401，而不是干净地走离线模式。
    """
    k = (key or "").strip().lower()
    if k.startswith("ark-"):
        k = k[4:]
    return len(k) < 8 or set(k) <= {"x"} or "your" in k or "你的" in k


def llm_available() -> bool:
    return bool(config.LLM_API_KEY) and not _is_placeholder_key(config.LLM_API_KEY)


def _has_image(messages: list) -> bool:
    """消息里有没有图片。

    判据是 content 是不是 list 且含 `image_url` 分片——这是 OpenAI 多模态协议
    的形状，`chat_json()` 就是这么拼的。不看 mime、不看文件、不看调用方心情：
    只看**这条请求实际带了什么**，因为路由错了的后果是两个方向都难看
    （把图发给纯文本模型 = 直接 400；把纯文字发给收费模型 = 白花钱）。
    """
    for m in messages or []:
        content = m.get("content")
        if isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "image_url":
                    return True
    return False


def _pick_model(messages: list | None = None) -> str:
    """按模态 + 熔断状态选模型。

    顺序刻意这样排：
      1. 带图 → 必须 multimodal，没得选（收费也得用，否则功能不可用）；
      2. 熔断中且允许付费兜底 → 用兜底模型，因为免费额度可能耗尽了；
      3. 其余 → 免费文本模型。
    第一优先级是图片：熔断状态下也不能把图片发给纯文本模型。
    """
    if messages is not None and _has_image(messages):
        return config.LLM_VISION_MODEL
    if (config.LLM_ALLOW_PAID_FALLBACK and _FAIL_COUNT >= _FAIL_THRESHOLD
            and (time.time() - _SWITCHED_AT) < _SWITCH_COOLDOWN):
        return config.LLM_FALLBACK_MODEL
    return config.LLM_MODEL


def _mark_fail() -> None:
    global _FAIL_COUNT, _SWITCHED_AT
    _FAIL_COUNT += 1
    if (_FAIL_COUNT == _FAIL_THRESHOLD
            or (_FAIL_COUNT > _FAIL_THRESHOLD and time.time() - _SWITCHED_AT >= _SWITCH_COOLDOWN)):
        _SWITCHED_AT = time.time()


def _mark_ok() -> None:
    global _FAIL_COUNT
    _FAIL_COUNT = 0


def _mask_json_value(value):
    """Mask JSON leaves before serialization, including numeric identifiers."""
    if isinstance(value, dict):
        return {guardrails.mask_pii(key): _mask_json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask_json_value(item) for item in value]
    if isinstance(value, str):
        return guardrails.mask_pii(value)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        masked = guardrails.mask_pii(str(value))
        return masked if masked != str(value) else value
    return value


def _mask_text(text: str) -> str:
    # Replacing an unquoted numeric phone inside JSON would make invalid JSON.
    try:
        value = json.loads(text)
    except (ValueError, TypeError):
        return guardrails.mask_pii(text)
    masked = _mask_json_value(value)
    return text if masked == value else json.dumps(masked, ensure_ascii=False)


def _outgoing_messages(messages: list) -> list:
    """Copy and mask textual fields only. Image bytes/URLs are not OCR-redacted."""
    result = copy.deepcopy(messages)
    for message in result:
        content = message.get("content")
        if isinstance(content, str):
            message["content"] = _mask_text(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and part.get("type") == "text" and isinstance(part.get("text"), str):
                    part["text"] = _mask_text(part["text"])
        functions = [call.get("function") for call in message.get("tool_calls") or [] if isinstance(call, dict)]
        functions.append(message.get("function_call"))
        for function in functions:
            if isinstance(function, dict) and isinstance(function.get("arguments"), str):
                function["arguments"] = _mask_text(function["arguments"])
    return result


def _can_fallback(model: str, messages: list) -> bool:
    return (config.LLM_ALLOW_PAID_FALLBACK and model != config.LLM_FALLBACK_MODEL
            and not _has_image(messages))


def _is_primary(model: str, messages: list) -> bool:
    return model == config.LLM_MODEL and not _has_image(messages)


def _response_message(data) -> dict:
    """Reject broken upstream contracts before consumers access message fields."""
    if not isinstance(data, dict):
        raise ValueError("Invalid upstream LLM response: expected an object")
    if data.get("error"):
        raise ValueError("Upstream LLM response contains an error")
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise ValueError("Invalid upstream LLM response: missing choices")
    message = choices[0].get("message")
    if not isinstance(message, dict):
        raise ValueError("Invalid upstream LLM response: missing message")
    content = message.get("content")
    calls = message.get("tool_calls")
    if content is not None and not isinstance(content, str):
        raise ValueError("Invalid upstream LLM response: content must be text")
    if calls is not None:
        if not isinstance(calls, list):
            raise ValueError("Invalid upstream LLM response: tool_calls must be a list")
        for call in calls:
            function = call.get("function") if isinstance(call, dict) else None
            if (not isinstance(function, dict) or not isinstance(call.get("id"), str)
                    or not isinstance(function.get("name"), str)
                    or not isinstance(function.get("arguments"), str)):
                raise ValueError("Invalid upstream LLM response: malformed tool call")
    if content is None and not calls:
        raise ValueError("Invalid upstream LLM response: no content or tool calls")
    return message


_USAGE_HOOKS: list = []


def add_usage_hook(fn) -> None:
    """订阅每次调用的用量（实测脚本用它统计 token 与缓存命中，不必去改私有函数）。钩子出错不影响调用。"""
    _USAGE_HOOKS.append(fn)


def remove_usage_hook(fn) -> None:
    if fn in _USAGE_HOOKS:
        _USAGE_HOOKS.remove(fn)


def _log_usage(model: str, usage: dict, username: str | None = None) -> None:
    """写用量表。失败不能中断对话，但**必须留痕**。

    原来这里是 `except Exception: pass`。问题在于 /api/usage 会把这张表
    的和当成「本月调用次数与成本」显示给用户——写失败被静默吞掉，用户
    看到的就是一个偏低的数字，而他没有任何办法知道它偏低。
    「不影响主流程」和「装作没发生」是两件事。
    """
    u = usage_numbers(usage)
    for hook in list(_USAGE_HOOKS):
        try:
            hook(model, u)
        except Exception:
            pass
    try:
        with db.get_conn() as conn:
            conn.execute(
                "INSERT INTO llm_usage (model, prompt_tokens, completion_tokens, total_tokens, created_at, username,"
                " cached_tokens, reasoning_tokens) VALUES (?,?,?,?,?,?,?,?)",
                (model, u["prompt_tokens"], u["completion_tokens"], u["total_tokens"], db.now(), username,
                 u["cached_tokens"], u["reasoning_tokens"]),
            )
    except Exception as e:
        try:
            import guardrails
            guardrails.log_event("llm.usage.persist_failed", model=model,
                                 user=username, error=f"{type(e).__name__}: {e}")
        except Exception:
            # 连日志都写不了就只能放弃；再抛会打断正在进行的对话
            pass


_REQUESTS = [0]          # 进程启动以来实际发出的请求数（含协商重试），实测脚本据此守住调用预算


def _request(body: dict, timeout: int, stream: bool = False):
    _REQUESTS[0] += 1
    req = urllib.request.Request(
        f"{config.LLM_BASE_URL}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {config.LLM_API_KEY}"},
    )
    return urllib.request.urlopen(req, timeout=timeout)  # 流式时调用方负责关闭


def _thinking_payload(model: str, structured: bool = False) -> dict:
    """是否给这次请求带 thinking 开关（DeepSeek-V4.1 与 GLM-5.x 的方舟接口同名参数 thinking.type）。

    只对主模型（LLM_MODEL）生效：推理型模型默认先输出一大段思考，对「按 schema 出 JSON」
    「选哪个工具」这类结构化动作完全没必要付这笔 token 与延迟，所以默认关。
    （GLM-5.2 上的实测：关思考 5.1s / 44 tokens，开思考 8.2s / 345 tokens。）

    `structured=True` 留给以后「JSON 任务关、自由文本开」的调法；
    现在 auto 模式下也一律关——本项目里连最终报告也是「把工具结果翻成大白话」。
    """
    if model != config.LLM_MODEL:
        return {}
    mode = getattr(config, "LLM_THINKING", "off")
    effort = getattr(config, "LLM_REASONING_EFFORT", "")
    if mode == "omit":          # 上游不认 thinking 参数（400）时用：完全不发送该字段
        return {}
    if mode == "on" or (mode == "auto" and not structured):
        out: dict = {"thinking": {"type": "enabled"}}
        if effort in ("low", "medium", "high"):
            out["reasoning_effort"] = effort
        return out
    return {"thinking": {"type": "disabled"}}


def _cache_payload(messages: list, tools: list | None = None) -> dict:
    """缓存路由键：只由系统提示（与工具名）决定——同一类请求共享前缀，路由到同一份缓存。不含用户数据。"""
    if getattr(config, "LLM_PROMPT_CACHE", "auto") == "off" or not messages:
        return {}
    first = messages[0]
    if not isinstance(first, dict) or first.get("role") != "system" or not isinstance(first.get("content"), str):
        return {}
    h = hashlib.sha1(first["content"].encode("utf-8"))
    for t in tools or []:
        h.update(str((t.get("function") or {}).get("name", "")).encode("utf-8"))
    return {"prompt_cache_key": "mt-" + h.hexdigest()[:16]}


# ---------------------------------------------------------------- 可选参数协商（判断逻辑在 llm_protocol）
_UNSUPPORTED: set[str] = set()      # 上游明确不认、本进程内不再发送的参数


def _send(body: dict, timeout: int, stream: bool = False):
    """发请求（已知不支持的参数先去掉）；可选参数被 400 拒绝时去掉重试一次，**重试成功才**记为不支持。"""
    body = {k: v for k, v in body.items() if k not in _UNSUPPORTED}
    try:
        return _request(body, timeout, stream=stream)
    except Exception as e:
        drop = _rejected_optional_fields(e, body)
        if not drop:
            raise
        try:
            e.close()  # type: ignore[attr-defined]
        except Exception:
            pass
        resp = _request({k: v for k, v in body.items() if k not in drop}, timeout, stream=stream)
        _UNSUPPORTED.update(drop)
        guardrails.log_event("llm.optional_params.disabled", model=body.get("model"), fields=sorted(drop))
        return resp


def runtime_info() -> dict:
    """协商与熔断的运行时状态（/api/health 展示，便于一眼看出「这个模型不认哪些参数」）。"""
    return {"unsupported_params": sorted(_UNSUPPORTED), "requests_since_start": _REQUESTS[0],
            "breaker_open": _FAIL_COUNT >= _FAIL_THRESHOLD}


def _post_chat(body: dict, timeout: int) -> dict:
    with _send(body, timeout) as resp:
        return json.loads(resp.read())


def chat(messages: list, model: str | None = None, temperature: float = 0.2,
         max_tokens: int = 4096, timeout: int = config.LLM_TIMEOUT_SECONDS, tools: list | None = None,
         username: str | None = None, json_mode: bool = False) -> dict:
    """调用 Chat Completions，返回完整 message dict（含 content / tool_calls）。

    支持 OpenAI 兼容的 tools 参数（原生 Function Calling）。失败计数达阈值切备用模型。
    超时默认取 config.LLM_TIMEOUT_SECONDS（45s）而不是写死 120s：
    一次 Agent 最多 6 轮，每轮 120s 的话最坏要等 12 分钟，用户早关了页面。
    v1 里所有调用方都显式传了 timeout，所以这里改默认值不影响现有行为。
    """
    if not llm_available():
        raise RuntimeError("ARK_API_KEY 环境变量未设置，无法调用大模型")
    outgoing = _outgoing_messages(messages)
    m = model or _pick_model(messages)
    for attempt in range(2):
        body = {"model": m, "messages": outgoing, "temperature": temperature, "max_tokens": max_tokens}
        body.update(_thinking_payload(m))
        body.update(_cache_payload(outgoing, tools))
        if tools:
            body.update(tools=tools, tool_choice="auto")
        elif json_mode and getattr(config, "LLM_JSON_MODE", "auto") != "off":
            body["response_format"] = {"type": "json_object"}
        try:
            data = _post_chat(body, timeout)
            message = _response_message(data)
            if _is_primary(m, messages):
                _mark_ok()
            if isinstance(data.get("usage"), dict):
                _log_usage(m, data["usage"], username)
            return message
        except Exception as e:
            if _is_primary(m, messages):
                _mark_fail()
            detail = _describe_http_error(e)
            if attempt == 0 and _can_fallback(m, messages):
                guardrails.log_event("llm.fallback", model=m, fallback=config.LLM_FALLBACK_MODEL,
                                     error_type=type(e).__name__)
                m = config.LLM_FALLBACK_MODEL
                continue
            raise RuntimeError(detail) from e


def chat_text(messages: list, **kw) -> str:
    return chat(messages, **kw).get("content") or ""


def _sse_events(response):
    """Read SSE fields, including multiline data and an optional event type."""
    data = []
    event_type = ""
    for raw in response:
        # SSE only uses CR/LF separators; str.splitlines also splits legal JSON
        # string characters such as U+2028 and would corrupt their content.
        lines = re.split(r"\r\n|\r|\n", raw.decode("utf-8"))
        if lines[-1] == "":
            lines.pop()
        for line in lines:
            if not line:
                if data or event_type:
                    yield event_type, "\n".join(data)
                data, event_type = [], ""
            elif line.startswith("data:"):
                data.append(line[5:].lstrip(" "))
            elif line.startswith("event:"):
                event_type = line[6:].strip()
    if data or event_type:
        yield event_type, "\n".join(data)


def stream_chat(messages: list, model: str | None = None, temperature: float = 0.2,
                max_tokens: int = 4096, timeout: int = config.LLM_TIMEOUT_SECONDS,
                username: str | None = None):
    """SSE 流式调用，逐 chunk yield content delta 字符串。"""
    if not llm_available():
        raise RuntimeError("ARK_API_KEY 环境变量未设置，无法调用大模型")
    outgoing = _outgoing_messages(messages)
    m = model or _pick_model(messages)
    visible_output = False
    for attempt in range(2):
        body = {"model": m, "messages": outgoing, "temperature": temperature,
                "max_tokens": max_tokens, "stream": True}
        body.update(_thinking_payload(m))
        body.update(_cache_payload(outgoing))
        if getattr(config, "LLM_PROVIDER", "").lower() in {"ark", "openai"}:
            body["stream_options"] = {"include_usage": True}
        resp = None
        finished = False
        try:
            resp = _send(body, timeout, stream=True)
            for event_type, payload in _sse_events(resp):
                if event_type == "error":
                    raise ValueError("Upstream LLM stream error event")
                if not payload:
                    continue
                if payload.strip() == "[DONE]":
                    finished = True
                    break
                chunk = json.loads(payload)
                if not isinstance(chunk, dict) or chunk.get("error"):
                    raise ValueError("Invalid upstream LLM stream response or error")
                choices = chunk.get("choices", [] if isinstance(chunk.get("usage"), dict) else None)
                if not isinstance(choices, list):
                    raise ValueError("Invalid upstream LLM stream choices")
                if choices:
                    choice = choices[0]
                    if not isinstance(choice, dict):
                        raise ValueError("Invalid upstream LLM stream choice")
                    reason = choice.get("finish_reason")
                    delta = choice.get("delta")
                    if delta is None and reason is not None:
                        delta = {}
                    if not isinstance(delta, dict):
                        raise ValueError("Invalid upstream LLM stream delta")
                    content = delta.get("content")
                    if content is not None and not isinstance(content, str):
                        raise ValueError("Invalid upstream LLM stream content")
                    if content:
                        visible_output = True
                        yield content
                    if reason is not None:
                        if reason != "stop":
                            raise ValueError("Upstream LLM stream did not finish normally")
                        finished = True
                if isinstance(chunk.get("usage"), dict):
                    _log_usage(m, chunk["usage"], username)
            if not finished:
                raise ValueError("Upstream LLM stream ended before completion")
            if _is_primary(m, messages):
                _mark_ok()
            return
        except Exception as e:
            if _is_primary(m, messages):
                _mark_fail()
            detail = _describe_http_error(e)
            if attempt == 0 and not visible_output and _can_fallback(m, messages):
                guardrails.log_event("llm.stream.fallback", model=m, fallback=config.LLM_FALLBACK_MODEL,
                                     error_type=type(e).__name__)
                m = config.LLM_FALLBACK_MODEL
                continue
            raise RuntimeError(detail) from e
        finally:
            if resp is not None:
                try:
                    resp.close()
                except Exception:
                    pass


def chat_json(system_prompt: str, user_prompt: str, image_b64: str | None = None,
              mime: str = "image/jpeg", temperature: float = 0.2,
              max_tokens: int = 4096, username: str | None = None) -> dict:
    """调用大模型并解析为 dict：自动剥离代码围栏、提取首个 JSON 对象；失败重试一次。"""
    prompt = user_prompt
    last_err: ValueError | None = None
    for attempt in range(2):
        content: list | str = [{"type": "text", "text": prompt}]
        if image_b64:
            content.append({"type": "image_url",
                            "image_url": {"url": f"data:{mime};base64,{image_b64}"}})
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content},
        ]
        text = chat_text(messages, temperature=temperature, max_tokens=max_tokens, username=username,
                         json_mode=True)
        try:
            result = extract_json(text)
            if not isinstance(result, dict):
                raise ValueError("模型输出必须是 JSON 对象")
            return result
        except ValueError as e:
            last_err = e
            if attempt == 1:
                raise
            prompt = user_prompt + "\n\n重要：只输出一个合法的 JSON 对象，不要包含任何解释文字或代码围栏。"
    raise last_err  # pragma: no cover


def extract_json(text: str):
    """先解析完整 JSON；若包含解释文字，再扫描首个对象/数组。"""
    if not text or not text.strip():
        raise ValueError("模型返回为空")
    cleaned = re.sub(r"```[a-zA-Z]*\s*", "", text).replace("```", "").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    decoder = json.JSONDecoder()
    for i, ch in enumerate(cleaned):
        if ch in "{[":
            try:
                obj, _ = decoder.raw_decode(cleaned[i:])
                return obj
            except json.JSONDecodeError:
                continue
    raise ValueError("模型输出中未找到 JSON")
