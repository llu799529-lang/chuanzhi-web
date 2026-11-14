"""医院检索服务：演示数据、高德 POI 检索、科室匹配。**全项目唯一实现。**

为什么单独成模块
----------------
原来同一件事有三份实现：`main.py`（/api/hospitals）、`agent2.py`（Agent 的 find_hospital 工具）、
`mcp_server.py`（MCP 的 find_hospital）。三份的参数不一致，并且各自带 bug：
  · MCP 版和 main 版在 city 为空时仍拼出 `&city=&citylimit=true`，高德对「空城市 + 限定」的行为不可控；
  · agent2 为了拿到演示数据，运行时 `import main`——服务层反向依赖了入口层，形成循环依赖。
现在三处都调用这里，入口层（main / MCP）和 Agent 都只是它的适配器。

两条诚实原则（都来自真实事故，见 agent2 的历史注释）：
  1. 没有定位就**不给距离**：演示数据里的 distance_km 只供排序，Agent 文本里不得出现；
  2. 演示数据必须按科室**真的重排**，而不是返回同一组顺序再让页面写「适合 X 优先」。
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

import config
import guardrails

DEMO_HOSPITALS: list[dict] = [
    {"name": "市第一人民医院", "distance_km": 1.8, "level": "三甲",
     "address": "演示数据：XX区XX路1号", "phone": "0XX-88880000",
     "depts": ["心血管内科", "神经内科", "消化内科", "呼吸内科", "骨科", "普外科"]},
    {"name": "市中心医院", "distance_km": 3.5, "level": "三甲",
     "address": "演示数据：XX区XX路88号", "phone": "0XX-66660000",
     "depts": ["急诊医学", "心血管内科", "神经外科", "内分泌科", "妇产科", "肿瘤科"]},
    {"name": "XX区眼科专科医院", "distance_km": 5.2, "level": "专科",
     "address": "演示数据：XX区XX路120号", "phone": "0XX-55550000",
     "depts": ["眼科", "眼底病", "白内障", "青光眼"]},
    {"name": "XX区妇幼保健院", "distance_km": 2.6, "level": "专科",
     "address": "演示数据：XX区XX路22号", "phone": "0XX-77770000",
     "depts": ["妇产科", "儿科", "新生儿科"]},
    {"name": "XX区口腔医院", "distance_km": 4.1, "level": "专科",
     "address": "演示数据：XX区XX路45号", "phone": "0XX-44440000",
     "depts": ["口腔科", "口腔外科", "正畸科"]},
    {"name": "XX区中医医院", "distance_km": 3.0, "level": "二级",
     "address": "演示数据：XX区XX路66号", "phone": "0XX-33330000",
     "depts": ["中医科", "针灸推拿", "康复理疗"]},
    {"name": "XX区精神卫生中心", "distance_km": 6.8, "level": "专科",
     "address": "演示数据：XX区XX路9号", "phone": "0XX-22220000",
     "depts": ["精神心理科", "睡眠医学科", "神经内科"]},
    {"name": "XX区皮肤病医院", "distance_km": 4.9, "level": "专科",
     "address": "演示数据：XX区XX路31号", "phone": "0XX-11110000",
     "depts": ["皮肤科", "医学美容"]},
    {"name": "XX社区卫生服务中心", "distance_km": 0.8, "level": "社区",
     "address": "演示数据：XX区XX街5号", "phone": "0XX-99990000",
     "depts": ["全科", "全科门诊", "慢病随访", "预防保健"]},
]

AMAP_TIMEOUT = 8
AMAP_HOSPITAL_TYPE = "090100"      # 高德 POI 分类：医疗保健服务-综合医院


def _dept_key(department: str) -> str:
    return (department or "").strip().replace("科", "")


def matches_department(hospital: dict, department: str) -> bool:
    """医院是否开设该科室。两侧都去「科」：全科 vs 全科门诊、儿科 vs 新生儿科 这类写法差异。"""
    key = _dept_key(department)
    if not key:
        return False
    return any(key in d.replace("科", "") or d.replace("科", "") in key for d in hospital.get("depts", []))


def rank_demo_hospitals(department: str) -> list[dict]:
    """演示数据按科室重排：命中的排前面，其余按距离。

    与前端 sortPois 的语义保持一致（命中优先 → 距离次之），这样即使前端拿不到地图 SDK、
    直接渲染这份列表，顺序也是对的。不做「只返回命中的」截断：用户仍需要看到附近的备选医院
    （比如皮肤科可以去社区做初筛），前端依据 depts 自己判断命中数并如实展示。
    """
    if not _dept_key(department):
        return sorted(DEMO_HOSPITALS, key=lambda h: h["distance_km"])
    # sorted 是稳定排序，距离相同的保持原始顺序
    return sorted(DEMO_HOSPITALS, key=lambda h: (0 if matches_department(h, department) else 1, h["distance_km"]))


def amap_level(text: str) -> str:
    if "三级甲等" in text or "三甲" in text:
        return "三级甲等"
    if "三级" in text:
        return "三级医院"
    if "二级" in text:
        return "二级医院"
    if "专科" in text:
        return "专科医院"
    if "社区" in text:
        return "社区医院"
    return "综合医院"


def build_amap_url(department: str, lat: float | None = None, lng: float | None = None, city: str = "") -> str:
    """拼高德 Web 服务 POI 检索 URL。纯函数，便于测试，且**日志里绝不输出它**（含 key）。

    有坐标走 around（按距离，返回 distance）；否则 text。`city` 为空时**不带** city / citylimit 参数。
    """
    kw = urllib.parse.quote(f"{department} 医院")
    key = config.AMAP_API_KEY
    if lat is not None and lng is not None:
        return (f"https://restapi.amap.com/v3/place/around?location={lng},{lat}"
                f"&keywords={kw}&types={AMAP_HOSPITAL_TYPE}&radius=10000&offset=20&page=1"
                f"&key={key}&extensions=all")
    city_part = f"&city={urllib.parse.quote(city)}&citylimit=true" if city else ""
    return (f"https://restapi.amap.com/v3/place/text?keywords={kw}&types={AMAP_HOSPITAL_TYPE}"
            f"{city_part}&offset=20&page=1&key={key}&extensions=all")


def parse_pois(data: dict, limit: int = 15) -> list[dict]:
    """高德响应 → 统一医院结构。容忍缺字段与畸形坐标，不抛异常。"""
    out: list[dict] = []
    for p in (data.get("pois") or [])[:limit]:
        if not isinstance(p, dict):
            continue
        lnglat = (p.get("location") or "").split(",")
        loc = None
        if len(lnglat) == 2:
            try:
                loc = {"lng": float(lnglat[0]), "lat": float(lnglat[1])}
            except ValueError:
                loc = None
        try:
            dist = round(float(p["distance"]) / 1000, 1) if p.get("distance") else None
        except (TypeError, ValueError):
            dist = None
        tel = (p.get("tel") or "")
        tel = tel if isinstance(tel, str) else ""
        out.append({
            "name": p.get("name", "") or "",
            "address": p.get("address", "") if isinstance(p.get("address"), str) else "",
            "tel": tel.split(";")[0],
            "type": p.get("type", "") or "",
            "level": amap_level((p.get("type") or "") + (p.get("name") or "")),
            "distance_km": dist,
            "location": loc,
        })
    return out


@dataclass
class SearchResult:
    """一次检索的结果。`source` 是实际数据来源，调用方据此如实标注，不要自己猜。"""
    source: str                                   # "amap" | "demo"
    hospitals: list[dict] = field(default_factory=list)
    error: str | None = None                      # amap 检索失败的原因（已脱敏，不含 key）
    fell_back: bool = False                       # 想用 amap 但降级到了演示数据

    @property
    def is_demo(self) -> bool:
        return self.source == "demo"


def web_search_enabled() -> bool:
    """是否配置了高德 **Web 服务** Key（后端 REST 检索 POI）。

    没有时：Agent 不提供医院检索工具，MCP 如实返回不可用，都不拿演示医院凑数。
    页面上的地图用的是另一个 JS API Key，在浏览器里按用户位置实时检索，不受这里影响。
    """
    return bool(config.AMAP_API_KEY)


def search(department: str, lat: float | None = None, lng: float | None = None, city: str = "",
           fallback_to_demo: bool = True) -> SearchResult:
    """统一入口。

    无 AMAP_API_KEY → 演示数据（source=demo）。
    有 Key：成功且有结果 → amap；失败或无结果 → `fallback_to_demo=True` 时降级演示数据（fell_back=True），
    否则返回空列表并带 error（Agent 需要把「没查到」如实告诉用户，不能悄悄换成演示数据）。
    """
    if not config.AMAP_API_KEY:
        return SearchResult("demo", rank_demo_hospitals(department))
    error = None
    hospitals: list[dict] = []
    try:
        with urllib.request.urlopen(build_amap_url(department, lat, lng, city), timeout=AMAP_TIMEOUT) as resp:
            data = json.loads(resp.read())
        if str(data.get("status", "1")) == "0":
            error = f"高德返回错误：{data.get('info') or data.get('infocode') or 'unknown'}"
        else:
            hospitals = parse_pois(data)
    except Exception as e:
        # 异常文本可能带请求 URL（含 key）——只记类型，不记内容
        error = f"{type(e).__name__}"
        guardrails.log_event("hospitals.amap.failed", error_type=type(e).__name__)
    if hospitals:
        return SearchResult("amap", hospitals)
    if fallback_to_demo:
        return SearchResult("demo", rank_demo_hospitals(department), error=error, fell_back=True)
    return SearchResult("amap", [], error=error)
