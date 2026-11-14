"""分诊映射：DR 分级 0-4 → 科室 / 紧急度。这是「方案有效性」的核心断言。"""
import pytest

from triage import triage_fundus


@pytest.mark.parametrize("level,expect_urgency", [
    (0, "green"), (1, "green"), (2, "yellow"), (3, "orange"), (4, "red"),
])
def test_level_to_urgency(level, expect_urgency):
    """五级分级必须单调递增地映射到五档紧急度，不允许出现跨级跳变。"""
    out = triage_fundus(level, 0.8)
    assert out["urgency"] == expect_urgency, f"level {level} 应映射到 {expect_urgency}，实际 {out['urgency']}"


def test_all_levels_have_department():
    for level in range(5):
        out = triage_fundus(level, 0.9)
        assert out["department"], f"level {level} 缺少科室"
        assert out["level_name"], f"level {level} 缺少分级文案"


def test_critical_level_needs_immediate_visit():
    """增殖期（4 级）必须给「立即就诊」语义，这是临床红线。"""
    out = triage_fundus(4, 0.95)
    text = str(out)
    assert "立即" in text, "4 级必须包含「立即就诊」提示"


def test_low_level_is_routine():
    """0 级不应出现任何「急诊/立即」措辞，避免过度医疗。"""
    out = triage_fundus(0, 0.99)
    text = str(out)
    assert "急诊" not in text


# ---------------------------------------------------------------- 边界保守升级
#
# 这组用例守的是一条临床安全线：**行动建议可以保守，但分级数字不能失真**。
# 3 级 recall 0.577 的短板决定了必须有兜底；兜底方式是「就诊时限按更严重走」，
# 而不是「把 2 级写成 3 级」——后者会让报告与模型输出对不上，等于造假。


def test_borderline_escalates_urgency_but_keeps_level():
    """2/3 级概率接近时：level 仍是 2，但就诊时限按 3 级走。"""
    out = triage_fundus(2, 0.48, [0.01, 0.03, 0.48, 0.44, 0.04])
    assert out["level"] == 2                     # 结论不改
    assert out["level_name"].startswith("中度")   # 名称不改
    assert out["urgency"] == "orange"            # 建议按 3 级
    assert out["borderline"] is True
    assert out["escalated_to"] == 3
    assert "边界提示" in out["doctor_summary"]


def test_clear_case_does_not_escalate():
    """概率差距明显时不升级——保守策略不能变成「人人都升一级」的噪声源。"""
    out = triage_fundus(2, 0.85, [0.0, 0.05, 0.85, 0.08, 0.02])
    assert out["urgency"] == "yellow"
    assert out["borderline"] is False
    assert out["escalated_to"] is None


def test_borderline_gap_boundary_is_strict():
    """概率差恰好等于阈值时不升级（判据是 < 而不是 <=），避免阈值抖动。"""
    out = triage_fundus(2, 0.50, [0.0, 0.0, 0.50, 0.38, 0.12])
    assert out["borderline"] is False


def test_level4_never_escalates():
    """4 级已是最高级，不能再往上顶（越界会 KeyError，这里守住）。"""
    out = triage_fundus(4, 0.51, [0.01, 0.02, 0.03, 0.43, 0.51])
    assert out["urgency"] == "red"
    assert out["escalated_to"] is None


def test_no_probs_keeps_legacy_behavior():
    """不传 probs（老调用方 / MCP 外部调用）行为完全不变。"""
    out = triage_fundus(3, 0.8)
    assert out["urgency"] == "orange"
    assert out["borderline"] is False
