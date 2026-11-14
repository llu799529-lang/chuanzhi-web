"""统一错误体 `{detail, code}`：前端只认这一种形状。需要 Web 框架（CI 上是真实 FastAPI）。"""
import io
import uuid

from PIL import Image


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_validation_error_is_a_readable_sentence_with_a_code(client):
    r = client.post("/api/auth/login", json={"username": "only-name"})
    assert r.status_code == 422
    d = r.json()
    assert d["code"] == "UNPROCESSABLE" and isinstance(d["detail"], str) and "password" in d["detail"]
    assert d["errors"] and all(isinstance(e["msg"], str) for e in d["errors"])


def test_rate_limit_response_carries_code_and_retry_after(client, token, monkeypatch):
    import ai_analysis
    monkeypatch.setattr(ai_analysis, "analyze_symptom", lambda text, username=None: ai_analysis._rule_based_symptom(text, [], "test"))
    first = client.post("/api/ai/symptom", json={"text": "头晕两天"}, headers=_h(token))
    second = client.post("/api/ai/symptom", json={"text": "头晕两天"}, headers=_h(token))
    assert first.status_code == 200 and second.status_code == 429
    assert second.json()["code"] == "RATE_LIMITED" and int(second.headers["Retry-After"]) >= 1


def test_oversized_upload_has_its_own_code(client, token):
    import config
    big = b"\x89PNG\r\n\x1a\n" + b"\x00" * (config.MAX_UPLOAD_BYTES + 10)
    r = client.post("/api/fundus/analyze", files={"file": ("x.png", big, "image/png")}, headers=_h(token))
    assert r.status_code == 413 and r.json()["code"] == "PAYLOAD_TOO_LARGE"


def test_vision_endpoint_is_rate_limited_now(client, token, monkeypatch):
    """/api/ai/image 调的是最贵的视觉模型，以前没有限流。"""
    import ai_analysis
    import llm
    monkeypatch.setattr(llm, "llm_available", lambda: True)
    monkeypatch.setattr(ai_analysis, "analyze_image", lambda *a, **k: {"kind": "other", "summary": "x"})
    buf = io.BytesIO()
    Image.new("RGB", (32, 32)).save(buf, format="PNG")
    files = {"file": ("a.png", buf.getvalue(), "image/png")}
    assert client.post("/api/ai/image", files=files, headers=_h(token)).status_code == 200
    assert client.post("/api/ai/image", files=files, headers=_h(token)).status_code == 429


def test_symptom_text_length_is_bounded_like_the_agent(client, token):
    r = client.post("/api/ai/symptom", json={"text": "头" * 20001}, headers=_h(token))
    assert r.status_code == 400 and r.json()["code"] == "BAD_REQUEST"


def test_register_trims_the_username(client):
    name = "  sp" + uuid.uuid4().hex[:6] + "  "
    r = client.post("/api/auth/register", json={"username": name, "password": "abc123456"})
    assert r.status_code == 200 and r.json()["username"] == name.strip()
    assert client.post("/api/auth/login", json={"username": name.strip(), "password": "abc123456"}).status_code == 200


def test_health_reports_live_check_honestly(client, tmp_path, monkeypatch):
    """没跑过实测就是 None（页面显示「未实测」）；跑过就给摘要，不带模型输出全文。"""
    import json as _json

    from api.routes import system
    monkeypatch.setattr(system, "LIVE_REPORT", tmp_path / "none.json")
    assert client.get("/api/health").json()["live_check"] is None
    rep = {"at": "2026-10-29T10:00:00", "model": "m", "passed": 4, "total": 5, "requests": 6,
           "unsupported_params": ["thinking"], "results": {"text": {"ok": True}, "image": {"ok": False},
                                                            "cache": {"ok": True, "cache_hit": True}}}
    (tmp_path / "r.json").write_text(_json.dumps(rep), encoding="utf-8")
    monkeypatch.setattr(system, "LIVE_REPORT", tmp_path / "r.json")
    lc = client.get("/api/health").json()["live_check"]
    assert lc["passed"] == 4 and lc["probes"] == {"text": True, "image": False, "cache": True} and lc["cache_hit"]
