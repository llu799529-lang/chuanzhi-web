"""不同新账号共享服务器 AI 能力，记录按账号隔离；不请求真实模型。"""
import io
import uuid

from PIL import Image


def test_new_accounts_can_access_image_service_without_a_username_allowlist(client, monkeypatch):
    import llm
    import screening

    monkeypatch.setattr(llm, "llm_available", lambda: True)
    seen = []

    def image_report(data, mime, username):
        seen.append(username)
        return {"kind": "lab", "items": [], "department": "内分泌科"}

    monkeypatch.setattr(screening, "image_report", image_report)
    image = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(image, "PNG")
    names = ["judge_" + uuid.uuid4().hex[:8] for _ in range(2)]
    for name in names:
        registration = client.post("/api/auth/register", json={"username": name, "password": "judge123456"})
        assert registration.status_code == 200
        headers = {"Authorization": "Bearer " + registration.json()["token"]}
        response = client.post("/api/ai/image", headers=headers,
                               files={"file": ("sample.png", image.getvalue(), "image/png")})
        assert response.status_code == 200
        assert client.get("/api/records", headers=headers).json()["records"] == []
    assert seen == names
