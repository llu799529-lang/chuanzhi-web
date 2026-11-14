"""眼底图像质量检测的回归测试。

这些用例都来自实测：先拿真实眼底图和构造图跑一遍，看指标落在哪，
再把边界写死。阈值不是拍脑袋定的，改动阈值前先跑这组测试。
"""
import io
import pathlib

import pytest
from PIL import Image, ImageFilter

import quality_check
from triage import triage_fundus

SHOTS = pathlib.Path(__file__).resolve().parent.parent.parent / "_shots"
REAL = SHOTS / "fundus_real.jpg"


def _enc(im: Image.Image) -> bytes:
    b = io.BytesIO()
    im.save(b, format="PNG")
    return b.getvalue()


@pytest.fixture(scope="module")
def base_image() -> Image.Image:
    if not REAL.exists():
        pytest.skip("缺少真实眼底样图 _shots/fundus_real.jpg")
    return Image.open(REAL).convert("RGB")


# ---------------------------------------------------------------- 应通过
def test_real_fundus_passes(base_image):
    """真实眼底图必须判「可评估」，不能把好图挡在外面。"""
    r = quality_check.assess(REAL.read_bytes())
    assert r["quality"] == "可评估", r["reasons"]
    assert r["retake"] is False


# ---------------------------------------------------------------- 应拦截
def test_flat_gray_is_not_evaluable():
    """纯灰图：实测模型会给 DR 0 级 26% 置信，必须在这里拦下。"""
    r = quality_check.assess(_enc(Image.new("RGB", (300, 300), (128, 128, 128))))
    assert r["quality"] == "不可评估"
    assert r["retake"] is True
    assert len(r["reasons"]) == 1, "硬失败只报根因，不要堆三条让人不知道该改哪个"


def test_pure_black():
    r = quality_check.assess(_enc(Image.new("RGB", (300, 300), (0, 0, 0))))
    assert r["quality"] == "不可评估"


def test_heavy_blur(base_image):
    """重度模糊：色散和清晰度同时塌，判不可评估。"""
    r = quality_check.assess(_enc(base_image.filter(ImageFilter.GaussianBlur(12))))
    assert r["quality"] == "不可评估"


def test_overexposed(base_image):
    """过曝会把边缘裁成硬边，拉普拉斯方差反而升高——不能靠 sharpness 判。

    实测 2.2 倍曝光后 sharpness=2097（比原图 2171 只低一点），
    但 98% 像素饱和。判据必须是「高亮 + 饱和像素占比」。
    """
    r = quality_check.assess(_enc(base_image.point(lambda x: min(255, x * 2.2))))
    assert r["quality"] == "不可评估"
    assert any("过曝" in s for s in r["reasons"])


def test_darkened_still_gives_report(base_image):
    """明显偏暗但不至于全黑：判「质量偏低」，仍给结论，只提示重拍。

    这里刻意不判死——用户手上可能只有这一张，不给结论等于什么都不给。
    """
    r = quality_check.assess(_enc(base_image.point(lambda x: x * 0.25)))
    assert r["quality"] in ("质量偏低", "不可评估")
    assert r["retake"] is True
    assert any(("过暗" in s) or ("色彩" in s) for s in r["reasons"])


def test_broken_bytes():
    r = quality_check.assess(b"not an image at all")
    assert r["quality"] == "不可评估"
    assert r["retake"] is True


# ---------------------------------------------------------------- 与分诊联动
def test_triage_summary_warns_on_bad_quality():
    """质量不达标必须写进 doctor_summary，不能只藏在字段里。"""
    bad = triage_fundus(0, 0.26, quality="不可评估")
    assert "图像质量提示" in bad["doctor_summary"]
    assert "重新拍摄" in bad["doctor_summary"]

    good = triage_fundus(0, 0.26, quality="可评估")
    assert "图像质量提示" not in good["doctor_summary"]


def test_triage_keeps_level_and_name():
    """质量提示不能改动分级数字——level/level_name 永远是模型原始输出。"""
    from triage import DR_LEVELS
    bad = triage_fundus(2, 0.9, quality="不可评估")
    assert bad["level"] == 2
    assert bad["level_name"] == DR_LEVELS[2]["name"], "不能因为质量差就把分级改名或降级"


def test_no_borderline_escalation_on_unusable_image():
    """废图不做边界升级。

    实测踩到过：纯灰图的概率分布也是「陡的」，gap 恰好小于 0.12，
    于是报告里出现了「已按更保守的 1 级时限建议就诊」——用一张噪声图的
    top1/top2 差值去改行动建议，比不给建议更糟。
    """
    probs = [0.30, 0.25, 0.20, 0.15, 0.10]   # gap = 0.05 < BORDERLINE_GAP
    bad = triage_fundus(0, 0.30, probs, quality="不可评估")
    assert bad["borderline"] is False
    assert bad["escalated_to"] is None

    # 同一组概率，质量正常时仍应触发边界保守升级
    ok = triage_fundus(0, 0.30, probs, quality="可评估")
    assert ok["borderline"] is True
    assert ok["escalated_to"] == 1
