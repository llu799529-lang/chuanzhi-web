"""预赛评审意见「建议增加眼底图片上传演示」：内置示例图必须真的能走通 上传 → 质量评估 → 分级 → 报告。

示例图放在 frontend/public/samples，构建后由同一服务静态托管；前端按「文件」把它上传到 /api/fundus/analyze，
与用户自己选图走同一条链路。这里锁住两件事：图真的在、而且行为与卡片上写的说明一致。
"""
import pathlib

import pytest

import llm
import quality_check
import records
import screening

ROOT = pathlib.Path(__file__).resolve().parents[2]
SAMPLES = ROOT / "frontend" / "public" / "samples"


def test_clear_sample_is_the_original_project_image_byte_for_byte():
    assert (SAMPLES / "fundus-sample.jpg").read_bytes() == (ROOT / "演示素材" / "01_眼底示例.jpg").read_bytes()


@pytest.mark.parametrize("name,quality,retake", [("fundus-sample.jpg", "可评估", False), ("fundus-blurry.jpg", "不可评估", True)])
def test_quality_gate_behaves_as_the_card_says(name, quality, retake):
    q = quality_check.assess((SAMPLES / name).read_bytes())
    assert q["quality"] == quality and q["retake"] is retake


def test_clear_sample_runs_the_full_fundus_pipeline(monkeypatch):
    monkeypatch.setattr(llm, "llm_available", lambda: False)
    rep = screening.fundus_report((SAMPLES / "fundus-sample.jpg").read_bytes(), "image/jpeg", "demo_sample_user")
    assert len(rep["probabilities"]) == 5 and rep["department"] and rep["heatmap_status"] in ("demo", "gradcam")
    assert records.recent("demo_sample_user", 1)[0]["input_type"] == "眼底彩照"


def test_blurry_sample_report_tells_the_user_to_retake(monkeypatch):
    monkeypatch.setattr(llm, "llm_available", lambda: False)
    rep = screening.fundus_report((SAMPLES / "fundus-blurry.jpg").read_bytes(), "image/jpeg", "demo_sample_user")
    assert rep["retake"] is True and "重新拍摄" in rep["doctor_summary"]


def test_lab_sample_is_the_projects_synthetic_lab_sheet_and_a_valid_upload():
    import io

    from PIL import Image
    data = (SAMPLES / "lab-sample.png").read_bytes()
    assert data == (ROOT / "演示素材" / "02_合成化验单.png").read_bytes()
    Image.open(io.BytesIO(data)).verify()
    assert len(data) < 20 * 1024 * 1024
