"""筛查编排层（screening.py）：以前只能经由 FastAPI 接口测试的四条业务流程，现在可以直接测。

全部离线：假分析器 / 假大模型，临时数据库（conftest），不联网、不耗额度。
重点锁住这次统一实现时顺带修掉的三个不一致（见 screening.py 顶部表格）。
"""
import io
import uuid

import pytest
from PIL import Image

import ai_analysis
import errors
import llm
import records
import screening

OK_SHOT = {"quality": "可评估", "reasons": [], "retake": False, "metrics": {}}
BAD_SHOT = {"quality": "不可评估", "reasons": ["过暗"], "retake": True, "metrics": {}}
# 1 级与 2 级概率差 0.02 < BORDERLINE_GAP：可评估时应按 2 级（黄色）时限保守建议
BORDER_PROBS = [0.05, 0.40, 0.38, 0.10, 0.07]


def _png() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (64, 64), (120, 40, 40)).save(buf, format="PNG")
    return buf.getvalue()


def _user(prefix="scr") -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


class FakeAnalyzer:
    def __init__(self, probs, heatmap_fails=False, demo=False):
        self.probs, self.heatmap_fails, self.is_demo = probs, heatmap_fails, demo

    def analyze(self, data):
        return {"probabilities": self.probs, "level": max(range(5), key=lambda i: self.probs[i])}

    def make_heatmap(self, data, level):
        if self.heatmap_fails:
            raise RuntimeError("CAM failed")
        return b"PNG"


# ---------------------------------------------------------------- 眼底
def test_fundus_report_in_demo_mode_is_complete_and_recorded(monkeypatch):
    monkeypatch.setattr(screening, "analyzer", FakeAnalyzer([0.8, 0.1, 0.05, 0.03, 0.02], demo=True))
    monkeypatch.setattr(llm, "llm_available", lambda: False)
    u = _user()
    rep = screening.fundus_report(_png(), "image/png", u)
    assert rep["mode"] == "demo" and rep["heatmap_status"] == "demo" and rep["heatmap"]
    assert abs(sum(p["probability"] for p in rep["probabilities"]) - 1) < 1e-3
    assert rep["disclaimer"] and rep["pre_visit_notes"] and rep["image_quality"]
    row = records.recent(u, 1)[0]
    assert row["input_type"] == "眼底彩照" and row["level"] == rep["level"]


def test_fundus_report_never_fakes_a_heatmap_when_grad_cam_fails(monkeypatch):
    monkeypatch.setattr(screening, "analyzer", FakeAnalyzer([0.8, 0.1, 0.05, 0.03, 0.02], heatmap_fails=True))
    rep = screening.fundus_report(_png(), "image/png", _user())
    assert rep["mode"] == "model" and rep["heatmap"] == "" and rep["heatmap_status"] == "unavailable"


def test_fundus_report_rejects_a_non_fundus_image_identified_by_the_model(monkeypatch):
    monkeypatch.setattr(screening, "analyzer", FakeAnalyzer([0.8, 0.1, 0.05, 0.03, 0.02], demo=True))
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(ai_analysis, "analyze_image", lambda *a, **k: {"kind": "lab"})
    with pytest.raises(errors.BadRequest):
        screening.fundus_report(_png(), "image/png", _user())


def test_fundus_report_falls_back_to_local_demo_when_the_model_call_fails(monkeypatch):
    monkeypatch.setattr(screening, "analyzer", FakeAnalyzer([0.8, 0.1, 0.05, 0.03, 0.02], demo=True))
    monkeypatch.setattr(llm, "llm_available", lambda: True)

    def boom(*a, **k):
        raise RuntimeError("HTTP 429 quota")
    monkeypatch.setattr(ai_analysis, "analyze_image", boom)
    rep = screening.fundus_report(_png(), "image/png", _user())
    assert rep["mode"] == "demo" and "ai_summary" not in rep


@pytest.mark.parametrize("shot,urgency,borderline", [(OK_SHOT, "yellow", True), (BAD_SHOT, "green", False)])
def test_grade_local_always_passes_probabilities_and_quality_to_triage(monkeypatch, shot, urgency, borderline):
    """MCP 旧实现漏传概率（边界病例不升级）、Agent 旧实现漏传质量（糊图也升级）——两种都不能再发生。"""
    monkeypatch.setattr(screening, "analyzer", FakeAnalyzer(BORDER_PROBS))
    g = screening.grade_local(_png(), shot)
    assert g["level"] == 1 and g["triage"]["urgency"] == urgency and g["triage"]["borderline"] is borderline


def test_apply_local_model_overrides_the_llm_grade_with_the_trained_model(monkeypatch):
    monkeypatch.setattr(screening, "analyzer", FakeAnalyzer([0.02, 0.03, 0.05, 0.1, 0.8]))
    monkeypatch.setattr(screening, "assess_image_quality", lambda b: OK_SHOT)
    d = screening.apply_local_model({"kind": "fundus", "level": 1, "level_label_long": "轻度"}, _png())
    assert d["level"] == 4 and d["engine"] == "local" and d["urgency"] == "red" and d["image_quality"] == "可评估"


def test_apply_local_model_leaves_non_fundus_results_alone():
    lab = {"kind": "lab", "report_title": "血常规"}
    assert screening.apply_local_model(dict(lab), _png()) == lab


def test_apply_local_model_without_weights_keeps_the_llm_grade_but_adds_quality(monkeypatch):
    monkeypatch.setattr(screening, "analyzer", FakeAnalyzer([1, 0, 0, 0, 0], demo=True))
    d = screening.apply_local_model({"kind": "fundus", "level": 2}, _png())
    assert d["level"] == 2 and d["engine"] == "llm" and "image_quality" in d


# ---------------------------------------------------------------- 任意图片
def test_image_report_wraps_model_failure_as_upstream_error(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("timeout")
    monkeypatch.setattr(ai_analysis, "analyze_image", boom)
    with pytest.raises(errors.Upstream):
        screening.image_report(_png(), "image/png", _user())


def test_image_report_other_kind_is_returned_but_not_recorded(monkeypatch):
    monkeypatch.setattr(ai_analysis, "analyze_image", lambda *a, **k: {"kind": "other", "summary": "风景照"})
    u = _user()
    out = screening.image_report(_png(), "image/png", u)
    assert out["kind"] == "other" and out["disclaimer"] and records.recent(u) == []


def test_image_report_lab_is_recorded_with_personal_details_masked(monkeypatch):
    monkeypatch.setattr(ai_analysis, "analyze_image", lambda *a, **k: {
        "kind": "lab", "report_title": "张三 13800001111 血常规", "abnormal_count": 2,
        "department": "血液科", "urgency": "yellow", "urgency_label": "关注"})
    u = _user()
    screening.image_report(_png(), "image/png", u)
    row = records.recent(u, 1)[0]
    assert row["input_type"] == "化验单" and "13800001111" not in row["summary"] and "2 项异常" in row["summary"]


# ---------------------------------------------------------------- 症状
def test_finalize_symptom_floors_urgency_scans_output_and_records(monkeypatch):
    card = {"kind": "symptom", "hits": ["胸痛"], "echo": "胸痛 13900001111", "dept": "全科", "urg": "绿色",
            "alt": "", "suspects": [], "tests": [], "prep": [], "reds": [], "urgency": "green", "degraded": False}
    u = _user()
    out = screening.finalize_symptom(card, "胸口疼，出了一身冷汗，放射到左肩", u)
    assert out["urgency"] == "red" and out["safety"]["raised"] is True
    assert out["guard"] in ("pass", "review") and "verification" in out and out["disclaimer"]
    row = records.recent(u, 1)[0]
    assert row["urgency"] == "red" and "13900001111" not in row["summary"]


def test_symptom_fallback_uses_the_knowledge_base_only_when_asked():
    with_kb = screening.symptom_fallback("咳嗽三天，有点黄痰", "model timeout", kb_query="咳嗽三天，有点黄痰")
    blind = screening.symptom_fallback("咳嗽三天，有点黄痰", "RuntimeError")
    assert with_kb["degraded"] and blind["degraded"]
    assert with_kb.get("kb_hits") and not blind.get("kb_hits")


# ---------------------------------------------------------------- 多模态综合
def test_multimodal_without_any_record_is_a_bad_request():
    with pytest.raises(errors.BadRequest):
        screening.multimodal_report(_user("mm_empty"), None)


def test_multimodal_is_cached_and_the_cached_answer_is_still_scanned(monkeypatch):
    calls = []

    def fake(history, lab):
        calls.append(len(history))
        return {"intro": "保证治愈", "findings": []}
    monkeypatch.setattr(ai_analysis, "analyze_multimodal", fake)
    u = _user("mm")
    records.save(u, {"kind": "symptom", "echo": "头晕"})
    first = screening.multimodal_report(u, None)
    second = screening.multimodal_report(u, None)
    assert calls == [1]                                         # 第二次没有再调模型
    assert "cached" not in first and second["cached"] is True
    assert first["guard"] == second["guard"] == "review"        # 旧实现命中缓存时漏了越界扫描


def test_multimodal_model_failure_is_an_upstream_error(monkeypatch):
    def boom(history, lab):
        raise RuntimeError("quota")
    monkeypatch.setattr(ai_analysis, "analyze_multimodal", boom)
    with pytest.raises(errors.Upstream):
        screening.multimodal_report(_user("mm_fail"), {"WBC": 12})
