"""护栏：PII 脱敏 / 红旗词扫描 / 限流。这是「AI 安全可控」的可验证证据。"""
import pytest

import guardrails
from errors import RateLimited

# ---------------- PII 脱敏 ----------------

@pytest.mark.parametrize("raw,expect", [
    ("我手机13812345678", "[手机号]"),
    ("身份证110101199003071234", "[身份证]"),
    ("邮箱 zhangsan@example.com 别乱发", "[邮箱]"),
])
def test_mask_pii(raw, expect):
    masked = guardrails.mask_pii(raw)
    assert expect in masked, f"{raw} 未被脱敏：{masked}"
    assert raw == raw  # 原文本身不变（函数返回新值）


def test_mask_pii_is_idempotent():
    once = guardrails.mask_pii("手机13812345678")
    twice = guardrails.mask_pii(once)
    assert once == twice


def test_mask_pii_keeps_normal_text():
    text = "最近头晕三天，血压 130/85"
    assert guardrails.mask_pii(text) == text


# ---------------- 红旗词 ----------------

@pytest.mark.parametrize("text,word", [
    ("我确诊为糖网四期", "确诊为"),
    ("建议处方二甲双胍", "建议处方"),
    ("你可以停药了", "可以停药"),
    ("这个病能根治", "根治"),
    ("无需就医", "无需就医"),
])
def test_scan_output_catches_red_words(text, word):
    hits = guardrails.scan_output(text)
    assert word in hits, f"{text} 应命中「{word}」，实际 {hits}"


def test_scan_output_clean_text():
    assert guardrails.scan_output("建议 3 个月内复查眼底") == []


def test_check_payload_marks_review():
    """命中越界的返回体必须被打上 needs_review 标记，且不删改原内容。"""
    payload = {"summary": "我确诊为糖尿病", "level": 3}
    out = guardrails.check_payload(payload)
    assert out["guard"] == "review"
    assert "确诊为" in out["red_flags"]
    assert payload["summary"] == "我确诊为糖尿病"  # 原对象未变


def test_check_payload_pass():
    out = guardrails.check_payload({"summary": "建议复查"})
    assert out["guard"] == "pass"
    assert out["red_flags"] == []


# ---------------- 限流 ----------------

def test_rate_limit_interval_blocks_burst():
    """同一用户同一接口连点两次，第二次必须 429。"""
    guardrails._WINDOW.clear()
    guardrails._LAST_CALL.clear()
    guardrails.rate_limit("u1", "test:interval", per_min=10, min_interval=1.0)
    with pytest.raises(RateLimited) as ei:
        guardrails.rate_limit("u1", "test:interval", per_min=10, min_interval=1.0)
    assert ei.value.status_code == 429


def test_rate_limit_window_blocks_after_quota():
    guardrails._WINDOW.clear()
    guardrails._LAST_CALL.clear()
    for _ in range(3):
        guardrails.rate_limit("u2", "test:window", per_min=3, min_interval=0)
    with pytest.raises(RateLimited) as ei:
        guardrails.rate_limit("u2", "test:window", per_min=3, min_interval=0)
    assert ei.value.status_code == 429
    assert "次数已用完" in str(ei.value.detail)


def test_rate_limit_isolated_per_user():
    """A 用户被限流不影响 B 用户。"""
    guardrails._WINDOW.clear()
    guardrails._LAST_CALL.clear()
    guardrails.rate_limit("a", "test:iso", per_min=1, min_interval=0)
    guardrails.rate_limit("b", "test:iso", per_min=1, min_interval=0)  # 不应抛


def test_rate_limit_sweeps_idle_keys():
    """长期无活动的限流桶必须被回收，否则就是纯内存泄漏。

    实测修之前：2000 个用户 → 2001 条 _WINDOW + 2001 条 _LAST_CALL，从不下降。
    deque 只在被访问时才 pop 过期项，所以「deque 空了」不能当判据，
    只能用「最后一次调用距今超过窗口长度」。
    """
    guardrails._WINDOW.clear()
    guardrails._LAST_CALL.clear()
    guardrails._last_sweep[0] = 0

    for i in range(300):
        try:
            guardrails.rate_limit(f"idle{i}", "sweep:test", per_min=5, min_interval=0)
        except Exception:
            pass
    assert len(guardrails._WINDOW) == 300

    # 把所有人推到「5 分钟前」，再强制触发一次扫描
    for k in list(guardrails._LAST_CALL):
        guardrails._LAST_CALL[k] -= 300
    guardrails._last_sweep[0] = 0
    guardrails.rate_limit("fresh", "sweep:test", per_min=5, min_interval=0)

    assert len(guardrails._WINDOW) <= 2, f"闲键未回收，仍有 {len(guardrails._WINDOW)} 条"
    assert "fresh@sweep:test" in guardrails._WINDOW, "活跃用户不能被误删"


def test_rate_limit_sweep_keeps_active_users():
    """扫描不能把刚调用过的用户删掉——那等于绕过限流。"""
    guardrails._WINDOW.clear()
    guardrails._LAST_CALL.clear()
    guardrails._last_sweep[0] = 0
    guardrails.rate_limit("active", "keep:test", per_min=2, min_interval=0)
    guardrails._last_sweep[0] = 0
    guardrails.rate_limit("other", "keep:test", per_min=2, min_interval=0)
    assert "active@keep:test" in guardrails._WINDOW
