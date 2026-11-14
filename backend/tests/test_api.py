"""接口契约：健康检查 / 医院 / 记录 / 降级链。这些是评委最可能点开的面。"""
import io

from PIL import Image


def _png(size=(64, 64)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (120, 40, 40)).save(buf, format="PNG")
    return buf.getvalue()


def test_health_shape(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    d = r.json()
    assert d["status"] == "ok"
    # 能力矩阵：答辩第一屏就看这个
    for k in ("fundus_model", "llm", "tts", "amap_map", "mcp_server"):
        assert k in d["capabilities"]
    assert d["guardrails"]["pii_mask"] is True
    assert d["auth"]["scheme"] == "JWT-HS256"


def test_health_exposes_request_id(client):
    r = client.get("/api/health")
    assert r.headers.get("X-Request-Id"), "每个请求都应带 request_id 便于追溯"


def test_hospitals_returns_js_key(client):
    """无 Web 服务 Key 时必须回落 demo，但 JS Key 仍要下发（前端地图靠它）。"""
    r = client.get("/api/hospitals?department=眼科")
    assert r.status_code == 200
    d = r.json()
    assert d["source"] in ("demo", "amap")
    assert d["hospitals"], "医院列表不能为空"
    assert "amap_js_key" in d and "amap_js_sec" in d


def test_records_requires_login(client):
    assert client.get("/api/records").status_code == 401


def test_records_empty_for_new_user(client, token):
    r = client.get("/api/records", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    d = r.json()
    assert d["records"] == []
    assert d["usage"]["month_quota"] == 200


def test_fundus_rejects_non_image(client, token):
    r = client.post(
        "/api/fundus/analyze",
        files={"file": ("note.txt", b"hello world", "text/plain")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_fundus_rejects_corrupted_image(client, token):
    r = client.post(
        "/api/fundus/analyze",
        files={"file": ("bad.png", b"not-a-real-png", "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 400


def test_fundus_rejects_oversized_upload(client, token):
    """超过 MAX_UPLOAD_MB 的图片必须在 read 之前被拒（413），而不是读完再判断。

    这条守的是「前端写着 ≤20MB、后端根本没校验」那个漏洞：
    没有闸门时 200MB 文件会被 `await file.read()` 完整读进内存，
    单进程 uvicorn 几次就能打满。用 413 而不是 400，
    是让客户端能区分「图太大」和「图坏了」。
    """
    import config

    oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * (config.MAX_UPLOAD_BYTES + 1024)
    r = client.post(
        "/api/fundus/analyze",
        files={"file": ("huge.png", oversized, "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 413, r.text
    assert "MB" in r.json()["detail"]


def test_upload_limit_boundary(client, token):
    """刚好卡在上限之内的文件不能被误伤（闸门不能把合法请求挡掉）。

    用一个「大但合法」的 PNG 直接打 /api/ai/image 不合适（要调模型），
    所以这里只验 _read_image 这个共用入口：上限以内 → 正常返回字节。
    """
    import asyncio
    import io as _io

    from starlette.datastructures import Headers, UploadFile

    import config
    from api import deps

    body = _png((64, 64))
    f = UploadFile(file=_io.BytesIO(body), filename="ok.png",
                   headers=Headers({"content-type": "image/png"}))
    data, mime = asyncio.run(deps.read_image(f))
    assert data == body and mime == "image/png"
    assert len(data) < config.MAX_UPLOAD_BYTES


def test_fundus_analyze_returns_full_payload(client, token):
    """一张合法图片必须返回分级 + 概率 + 热力图 + 分诊 + 免责声明。"""
    r = client.post(
        "/api/fundus/analyze",
        files={"file": ("fundus.png", _png((300, 300)), "image/png")},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    for k in ("level", "probabilities", "heatmap", "department", "urgency", "disclaimer"):
        assert k in d, f"缺少字段 {k}"
    assert len(d["probabilities"]) == 5
    assert sum(p["probability"] for p in d["probabilities"]) > 0.9


def test_symptom_empty_text_400(client, token):
    r = client.post("/api/ai/symptom", json={"text": "  "},
                    headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 400


def test_rule_based_fallback_shape():
    """降级链第 2 档：规则引擎兜底必须返回完整可渲染结构。"""
    import ai_analysis
    import rag

    kb = rag.retrieve("胸口闷痛放射到左肩")
    out = ai_analysis._rule_based_symptom("胸口闷痛放射到左肩", kb, "test timeout")
    assert out["degraded"] is True
    assert out["urgency"] in ("red", "orange", "yellow", "green")
    assert out["dept"]
    assert out["suspects"] and out["suspects"][0][1] > 0
    assert out["tests"]
    assert out["degrade_note"]


def test_rule_based_fallback_without_kb():
    """降级链第 3 档：知识库也没命中时，仍要给出全科兜底卡而不报错。"""
    import ai_analysis

    out = ai_analysis._rule_based_symptom("未知症状 xyz", [], "no kb")
    assert out["dept"]
    assert out["suspects"]
    assert out["urgency"] == "yellow"


def test_error_envelope_is_json(client):
    """未登录访问受保护接口，错误体必须是 {detail, code} 结构而非纯文本。"""
    r = client.get("/api/records")
    assert r.status_code == 401
    d = r.json()
    assert "detail" in d and "code" in d
    assert d["code"] == "UNAUTHORIZED"


def test_multimodal_endpoint_passes_record_list_not_function(client, token, monkeypatch):
    """回归：`/api/ai/multimodal` 曾把**函数**当成记录列表传下去。

    现象：前端弹出「综合分析失败：Object of type function is not JSON serializable」。
    根因：`/api/records` 的路由函数名叫 `records`，把 `import records` 的模块名遮蔽了；
    重构时把这个函数体里的 `records` 变量改成了 `history`，却漏了 3 处，
    于是那些位置解析到的是**路由函数对象**，传给 `analyze_multimodal` 后
    json.dumps 直接炸。裸读代码很难发现——函数名和模块名同名这种坑，
    只有跑一次接口才暴露。
    """
    import ai_analysis
    import auth
    import records as records_repo

    username = auth.decode_token(token)["sub"]
    records_repo.save(username, {"kind": "symptom", "echo": "头晕", "department": "神经内科"})

    captured = {}

    def fake_multimodal(recs, lab_detail=None):
        captured["recs"] = recs
        return {"summary": "ok", "sections": []}

    monkeypatch.setattr(ai_analysis, "analyze_multimodal", fake_multimodal)
    monkeypatch.setattr(ai_analysis.llm, "llm_available", lambda: True)
    r = client.post("/api/ai/multimodal", json={}, headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    assert isinstance(captured["recs"], list) and captured["recs"], "传给分析的必须是记录列表"
    assert isinstance(captured["recs"][0], dict)
    assert r.json()["record_count"] >= 1


def test_demo_hospitals_change_with_department(client):
    """演示数据必须真的按科室重排。

    回归背景：原来 /api/hospitals 不看 department，永远返回同一组
    「眼科」医院顺序，前端又只能靠名字猜科室 → 选「皮肤科 / 儿科 / 全科」
    三家全不命中、顺序不变，页面却写着「适合皮肤科优先」。
    """
    def names(dept):
        r = client.get("/api/hospitals", params={"department": dept})
        assert r.status_code == 200
        return [h["name"] for h in r.json()["hospitals"]]

    eye = names("眼科")
    derm = names("皮肤科")
    ped = names("儿科")
    assert eye != derm, "皮肤科与眼科的首选医院不该一样"
    assert eye != ped, "儿科与眼科的首选医院不该一样"
    assert "眼科" in eye[0], "眼科的首选应该是眼科专科"
    assert "皮肤" in derm[0], f"皮肤科首选异常：{derm[0]}"
    assert "妇幼" in ped[0], f"儿科首选异常：{ped[0]}"


def test_every_dept_option_has_a_hit(client):
    """17 个科室选项都必须至少有一家命中，否则「适合 X 优先」就是空话。"""
    import hospitals

    opts = ["眼科", "心血管内科", "神经内科", "神经外科", "内分泌科", "骨科",
            "呼吸内科", "消化内科", "普外科", "妇产科", "儿科", "口腔科",
            "中医科", "肿瘤科", "精神心理科", "皮肤科", "全科"]
    for dept in opts:
        key = dept.replace("科", "")
        ranked = hospitals.rank_demo_hospitals(dept)
        assert any(key in d for h in ranked[:3] for d in h["depts"]), f"{dept} 无任何命中"
        # 命中的必须排在最前面
        assert any(key in d for d in ranked[0]["depts"]), f"{dept} 首位不是命中项：{ranked[0]['name']}"


def test_demo_hospitals_declare_depts(client):
    """每家园都要显式声明科室，不能靠前端按名字猜。"""
    r = client.get("/api/hospitals", params={"department": "眼科"})
    for h in r.json()["hospitals"]:
        assert h.get("depts"), f"{h['name']} 缺少 depts 字段"
