"""附近医院（高德 POI；未配置 Key 或检索失败时回落演示数据，并如实标注）。"""
from __future__ import annotations

from fastapi import APIRouter

import config
import hospitals

router = APIRouter(prefix="/api", tags=["navigation"])


@router.get("/hospitals")
def nearby_hospitals(department: str = "眼科", lat: float | None = None, lng: float | None = None, city: str = ""):
    """演示数据按 `department` **真的重排**（以前无论什么科室都回同一组顺序，页面却写着「适合 X 优先」）。"""
    result = hospitals.search(department, lat, lng, city, fallback_to_demo=True)
    body = {"source": result.source, "department": department, "hospitals": result.hospitals,
            "amap_js_key": config.AMAP_JS_KEY, "amap_js_sec": config.AMAP_JS_SEC}
    if result.fell_back:
        # 想查真实数据却降级了：告诉前端，别把演示数据当成「附近真实医院」
        body["fallback_reason"] = result.error or "no_result"
    return body
