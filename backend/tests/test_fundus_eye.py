"""双眼联合筛查的后端部分 + 本地模型改写分级后的文字一致性。"""
import pathlib
import types

import records
import screening

SAMPLE = pathlib.Path(__file__).resolve().parents[2] / "frontend/public/samples/fundus-sample.jpg"


def test_eye_label_goes_into_payload_and_record(monkeypatch):
    monkeypatch.setattr(screening.llm, "llm_available", lambda *a, **k: False)
    out = screening.fundus_report(SAMPLE.read_bytes(), "image/jpeg", "eye_user_r", eye="right")
    assert out["eye"] == "right"
    assert records.recent("eye_user_r", 1)[0]["summary"].startswith("右眼")
    plain = screening.fundus_report(SAMPLE.read_bytes(), "image/jpeg", "eye_user_n")
    assert "eye" not in plain and not records.recent("eye_user_n", 1)[0]["summary"].startswith(("右眼", "左眼"))


def test_local_model_override_drops_the_llm_grade_text(monkeypatch):
    """Agent 上传眼底图：大模型看图估 2 级，本地模型判 4 级。分级依据不能还写着「符合中度非增殖期表现」。"""
    tri = {"level_name": "增殖期糖网（PDR）", "department": "眼科", "urgency": "red", "urgency_label": "紧急"}
    monkeypatch.setattr(screening, "analyzer", types.SimpleNamespace(is_demo=False))
    monkeypatch.setattr(screening, "assess_image_quality",
                        lambda b: {"quality": "可评估", "reasons": [], "retake": False, "metrics": {}})
    monkeypatch.setattr(screening, "grade_local",
                        lambda b, shot=None: {"level": 4, "probs": [0.05, 0.05, 0.2, 0.25, 0.45], "triage": tri})
    analysis = {"kind": "fundus", "level": 2, "summary": "黄斑区大量硬性渗出，符合中度非增殖期表现",
                "criteria": [{"hit": True, "text": "符合中度非增殖期表现"}]}
    out = screening.apply_local_model(analysis, b"x")
    assert out["level"] == 4 and out["criteria"] == [] and out["llm_level"] == 2
    assert "以本地模型为准" in out["summary"]
    same = screening.apply_local_model({"kind": "fundus", "level": 4, "summary": "s", "criteria": [{"hit": True, "text": "t"}]}, b"x")
    assert same["criteria"] and "llm_level" not in same


def test_gradcam_is_pasted_onto_the_region_the_model_actually_saw():
    """模型只看中心裁剪区域：热区要贴回那块区域，而不是拉伸铺满整张图（宽图偏差最明显）。"""
    import io

    from PIL import Image

    import fundus
    x0, y0, x1, y1 = fundus.cam_box(640, 427, 300)
    assert (x1 - x0) == (y1 - y0) and abs((x1 - x0) - 427 * 300 / int(300 * 1.14)) <= 1 and abs((x0 + x1) / 2 - 320) <= 1
    cam = Image.new("L", (10, 10), 0)
    cam.putpixel((0, 0), 255)                                  # 只有模型输入左上角最热
    _, layer = fundus.render_cam(Image.new("RGB", (900, 600), (120, 60, 30)), cam, blur=2)
    alpha = Image.open(io.BytesIO(layer)).getchannel("A")
    W, H = alpha.size
    bx0, by0, bx1, by1 = fundus.cam_box(W, H)
    hot = max((alpha.getpixel((x, y)), x, y) for x in range(0, W, 2) for y in range(0, H, 2))
    assert hot[0] > 100 and bx0 <= hot[1] <= bx0 + (bx1 - bx0) // 5 and by0 <= hot[2] <= by0 + (by1 - by0) // 5
    assert alpha.getpixel((2, 2)) == 0                          # 裁剪区域外完全透明


def test_report_carries_a_transparent_heat_layer(monkeypatch):
    monkeypatch.setattr(screening.llm, "llm_available", lambda *a, **k: False)
    out = screening.fundus_report(SAMPLE.read_bytes(), "image/jpeg", "eye_user_layer")
    assert out["heatmap"] and out["heatmap_layer"] and out["heatmap_layer"] != out["heatmap"]
