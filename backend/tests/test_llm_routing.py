"""模型路由的回归测试。

背景
----
路由判据只有一条：消息里有没有 `image_url`。
  · 带图的请求发给纯文本模型 → 上游直接 400，眼底/化验单功能全挂；
  · 纯文本的请求发给更贵的模型 → 不报错，只是白花钱，**而且没人会发现**。
第二个更危险，所以路由要钉死，而不是靠读代码确认。

2026-10-24 起默认三个模型 ID 相同（DeepSeek-V4.1-Flash 经济版同时接受文本与图片），
但路由逻辑仍保留，可以在 .env 里把 ARK_VISION_MODEL 拆成别的多模态模型。
下面用**互不相同的占位名**验证路由，再单独断言默认配置，避免「默认值恰好相同」掩盖路由错误。
"""
import pytest

import config
import llm


@pytest.fixture(autouse=True)
def split_models(monkeypatch):
    monkeypatch.setattr(config, "LLM_MODEL", "text-model")
    monkeypatch.setattr(config, "LLM_VISION_MODEL", "vision-model")
    monkeypatch.setattr(config, "LLM_FALLBACK_MODEL", "fallback-model")
    monkeypatch.setattr(config, "LLM_ALLOW_PAID_FALLBACK", True)


def _text_msgs():
    return [{"role": "user", "content": "胸痛放射到左肩"}]


def _image_msgs():
    return [{"role": "user", "content": [
        {"type": "text", "text": "帮我看看这张图"},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,AAAA"}},
    ]}]


def test_has_image_detects_openai_multimodal_shape():
    assert llm._has_image(_image_msgs()) is True
    assert llm._has_image(_text_msgs()) is False
    # system 里夹一个 list 但不是图片分片，不能误判
    assert llm._has_image([{"role": "system", "content": [{"type": "text", "text": "x"}]}]) is False
    assert llm._has_image([]) is False


def test_text_goes_to_text_model(monkeypatch):
    monkeypatch.setattr(llm, "_FAIL_COUNT", 0)
    assert llm._pick_model(_text_msgs()) == "text-model"


def test_image_goes_to_vision_model(monkeypatch):
    """带图必须走视觉模型，否则可能上游 400。"""
    monkeypatch.setattr(llm, "_FAIL_COUNT", 0)
    assert llm._pick_model(_image_msgs()) == "vision-model"


def test_image_beats_circuit_breaker(monkeypatch):
    """熔断状态下也不能把图片发给纯文本模型。优先级是「模态 > 熔断」。"""
    monkeypatch.setattr(llm, "_FAIL_COUNT", llm._FAIL_THRESHOLD)
    monkeypatch.setattr(llm, "_SWITCHED_AT", llm.time.time())
    assert llm._pick_model(_image_msgs()) == "vision-model"
    # 同样在熔断期，纯文本在「允许付费兜底」时切到兜底模型
    assert llm._pick_model(_text_msgs()) == "fallback-model"


def test_fallback_disabled_when_paid_not_allowed(monkeypatch):
    """LLM_ALLOW_PAID_FALLBACK=0 时，失败就该报错，不能偷偷换模型。"""
    monkeypatch.setattr(config, "LLM_ALLOW_PAID_FALLBACK", False)

    def _fail(*a, **kw):
        raise OSError("network down")

    monkeypatch.setattr(llm, "_request", _fail)
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    with pytest.raises(RuntimeError, match="network down|OSError"):
        llm.chat(_text_msgs())


def test_thinking_switch_only_for_primary_model():
    """thinking 只对主模型加；拆成别的视觉模型时，不把可能不认识的字段甩过去。"""
    assert llm._thinking_payload(config.LLM_MODEL) == {"thinking": {"type": "disabled"}}
    assert llm._thinking_payload(config.LLM_VISION_MODEL) == {}


def test_thinking_can_be_turned_on(monkeypatch):
    monkeypatch.setattr(config, "LLM_THINKING", "on")
    assert llm._thinking_payload(config.LLM_MODEL) == {"thinking": {"type": "enabled"}}


def test_thinking_omit_sends_nothing(monkeypatch):
    """上游不认 thinking 参数时的出口：LLM_THINKING=omit 完全不发送该字段。"""
    monkeypatch.setattr(config, "LLM_THINKING", "omit")
    assert llm._thinking_payload(config.LLM_MODEL) == {}


def test_reasoning_effort_only_sent_when_thinking_is_on(monkeypatch):
    monkeypatch.setattr(config, "LLM_REASONING_EFFORT", "high")
    assert llm._thinking_payload(config.LLM_MODEL) == {"thinking": {"type": "disabled"}}
    monkeypatch.setattr(config, "LLM_THINKING", "on")
    assert llm._thinking_payload(config.LLM_MODEL) == {"thinking": {"type": "enabled"}, "reasoning_effort": "high"}
    monkeypatch.setattr(config, "LLM_REASONING_EFFORT", "bogus")
    assert llm._thinking_payload(config.LLM_MODEL) == {"thinking": {"type": "enabled"}}


# ---- 默认配置（2026-10-24：DeepSeek-V4-Flash 正式版，有免费额度）----
def _fresh_config():
    """在**独立的模块对象**里重新执行 config.py 读取默认值。

    绝不能 importlib.reload(config)：conftest 把 config.DATA_DIR 指向了临时库，
    重载会把它还原成真实目录，之后的测试就会写进真正的 medtriage.db。
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location("config_fresh_for_test", config.__file__)
    fresh = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fresh)
    return fresh


def test_defaults_keep_text_model_and_separate_verified_vision_model(monkeypatch):
    for k in ("ARK_MODEL", "ARK_VISION_MODEL", "ARK_FALLBACK_MODEL", "LLM_ALLOW_PAID_FALLBACK", "ARK_TEXT_MODEL"):
        monkeypatch.delenv(k, raising=False)
    fresh = _fresh_config()
    assert fresh.LLM_MODEL == "deepseek-v4-flash-ga-260731"                  # 有免费额度的正式版，不是付费的经济版
    assert fresh.LLM_VISION_MODEL == "deepseek-v4-1-flash-economy-261017"  # 实测化验单识别通过；文本保持正式版
    assert fresh.LLM_FALLBACK_MODEL == fresh.LLM_MODEL
    assert fresh.LLM_ALLOW_PAID_FALLBACK is False           # 额度紧张时不悄悄换更贵的模型
    assert "*" not in fresh.CORS_ORIGINS


def test_env_can_split_vision_model_out(monkeypatch):
    monkeypatch.setenv("ARK_VISION_MODEL", "some-vision-model")
    monkeypatch.delenv("ARK_MODEL", raising=False)
    fresh = _fresh_config()
    assert fresh.LLM_VISION_MODEL == "some-vision-model" and fresh.LLM_MODEL != fresh.LLM_VISION_MODEL


def test_configured_cors_is_not_wildcard_by_default(monkeypatch):
    monkeypatch.delenv("CORS_ORIGINS", raising=False)
    assert "*" not in _fresh_config().CORS_ORIGINS
    monkeypatch.setenv("CORS_ORIGINS", "https://a.example, https://b.example")
    assert _fresh_config().CORS_ORIGINS == ["https://a.example", "https://b.example"]
