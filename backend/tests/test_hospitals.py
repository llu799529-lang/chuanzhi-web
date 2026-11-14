"""医院检索服务（hospitals.py）：三处调用方（HTTP / Agent / MCP）共用的唯一实现。

全部离线：`urlopen` 被替换，不会发出任何请求；Key 是占位值，且测试会断言它**不出现在日志与结果里**。
"""
import json

import pytest

import agent2
import config
import hospitals


class FakeResp:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return json.dumps(self.payload).encode()


POIS = {"status": "1", "pois": [
    {"name": "市第一人民医院眼科", "address": "中山路1号", "tel": "0411-111;0411-222", "type": "医疗保健服务;综合医院;三级甲等医院",
     "location": "121.60,38.91", "distance": "1850"},
    {"name": "爱尔眼科医院", "address": "解放路8号", "type": "医疗保健服务;专科医院", "location": "bad,loc"},
    "not-a-dict",
]}


@pytest.fixture()
def with_key(monkeypatch):
    monkeypatch.setattr(config, "AMAP_API_KEY", "TEST-KEY-12345")


def _serve(monkeypatch, payload=None, exc=None):
    urls = []

    def fake(url, timeout=0):
        urls.append(url)
        if exc:
            raise exc
        return FakeResp(payload)

    monkeypatch.setattr(hospitals.urllib.request, "urlopen", fake)
    return urls


# ---------------------------------------------------------------- 演示数据与排序
def test_demo_ranking_puts_matches_first_then_by_distance():
    ranked = hospitals.rank_demo_hospitals("眼科")
    assert "眼科" in ranked[0]["name"]
    rest = [h["distance_km"] for h in ranked if not hospitals.matches_department(h, "眼科")]
    assert rest == sorted(rest)


@pytest.mark.parametrize("dept", ["眼科", "皮肤科", "儿科", "全科", "精神心理科", "口腔科", "妇产科"])
def test_every_common_department_has_a_first_hit(dept):
    assert hospitals.matches_department(hospitals.rank_demo_hospitals(dept)[0], dept)


def test_empty_department_sorts_by_distance_only():
    d = [h["distance_km"] for h in hospitals.rank_demo_hospitals("")]
    assert d == sorted(d)


def test_matching_ignores_ke_suffix_in_both_directions():
    h = {"depts": ["全科门诊"]}
    assert hospitals.matches_department(h, "全科") and not hospitals.matches_department(h, "")


def test_ranking_does_not_mutate_the_shared_demo_list():
    before = [h["name"] for h in hospitals.DEMO_HOSPITALS]
    hospitals.rank_demo_hospitals("皮肤科")
    assert [h["name"] for h in hospitals.DEMO_HOSPITALS] == before


# ---------------------------------------------------------------- URL 与解析
def test_text_search_omits_city_params_when_city_is_empty(with_key):
    url = hospitals.build_amap_url("眼科")
    assert "city=" not in url and "citylimit" not in url and "place/text" in url


def test_text_search_with_city_limits_to_that_city(with_key):
    url = hospitals.build_amap_url("眼科", city="大连")
    assert "citylimit=true" in url and "%E5%A4%A7%E8%BF%9E" in url


def test_coordinates_switch_to_around_search(with_key):
    url = hospitals.build_amap_url("眼科", lat=38.9, lng=121.6)
    assert "place/around" in url and "location=121.6,38.9" in url and "city" not in url


def test_parse_pois_is_defensive_and_derives_level_and_distance():
    out = hospitals.parse_pois(POIS)
    assert len(out) == 2                                   # 非 dict 的条目被丢弃
    assert out[0]["level"] == "三级甲等" and out[0]["distance_km"] == 1.9 and out[0]["tel"] == "0411-111"
    assert out[0]["location"] == {"lng": 121.6, "lat": 38.91}
    assert out[1]["location"] is None and out[1]["distance_km"] is None and out[1]["level"] == "专科医院"


@pytest.mark.parametrize("bad", [{}, {"pois": None}, {"pois": []}, {"pois": [{"distance": "abc", "location": ""}]}])
def test_parse_pois_never_raises(bad):
    assert isinstance(hospitals.parse_pois(bad), list)


# ---------------------------------------------------------------- search()
def test_without_key_returns_demo_data_and_does_not_touch_the_network(monkeypatch):
    monkeypatch.setattr(config, "AMAP_API_KEY", "")
    urls = _serve(monkeypatch, exc=AssertionError("不应联网"))
    res = hospitals.search("眼科")
    assert res.is_demo and not res.fell_back and res.error is None and urls == []


def test_with_key_uses_real_pois(with_key, monkeypatch):
    urls = _serve(monkeypatch, POIS)
    res = hospitals.search("眼科", city="大连")
    assert res.source == "amap" and len(res.hospitals) == 2 and len(urls) == 1


def test_failure_falls_back_to_demo_and_records_a_scrubbed_reason(with_key, monkeypatch):
    _serve(monkeypatch, exc=OSError("connect failed: https://restapi.amap.com/...key=TEST-KEY-12345"))
    res = hospitals.search("眼科", fallback_to_demo=True)
    assert res.is_demo and res.fell_back and res.error == "OSError"
    assert "TEST-KEY" not in str(res.error)


def test_failure_without_fallback_returns_empty_amap_result_with_error(with_key, monkeypatch):
    _serve(monkeypatch, exc=OSError("boom"))
    res = hospitals.search("眼科", fallback_to_demo=False)
    assert res.source == "amap" and res.hospitals == [] and res.error == "OSError" and not res.fell_back


def test_amap_status_zero_is_treated_as_an_error(with_key, monkeypatch):
    _serve(monkeypatch, {"status": "0", "info": "INVALID_USER_KEY"})
    res = hospitals.search("眼科", fallback_to_demo=False)
    assert res.hospitals == [] and "INVALID_USER_KEY" in res.error


def test_empty_result_falls_back_when_allowed(with_key, monkeypatch):
    _serve(monkeypatch, {"status": "1", "pois": []})
    assert hospitals.search("眼科", fallback_to_demo=True).fell_back is True
    assert hospitals.search("眼科", fallback_to_demo=False).hospitals == []


def test_api_key_is_never_logged(with_key, monkeypatch):
    import guardrails
    logged = []
    monkeypatch.setattr(guardrails, "log_event", lambda event, **kw: logged.append((event, kw)))
    _serve(monkeypatch, exc=OSError("key=TEST-KEY-12345"))
    hospitals.search("眼科")
    assert logged and "TEST-KEY" not in json.dumps(logged, ensure_ascii=False)


# ---------------------------------------------------------------- Agent 适配器：文本必须诚实
def test_agent_demo_text_forbids_inventing_distance(monkeypatch):
    monkeypatch.setattr(config, "AMAP_API_KEY", "")
    r = agent2._find_hospital({"department": "眼科"})
    assert "演示数据" in r["result"] and "不得声称" in r["result"] and "km" not in r["result"].lower() and r["warn"] is False


def test_agent_real_result_states_that_there_is_no_distance(with_key, monkeypatch):
    _serve(monkeypatch, POIS)
    r = agent2._find_hospital({"department": "眼科", "city": "大连"})
    assert "不要编造距离" in r["result"] and "大连市内" in r["result"] and "市第一人民医院眼科" in r["result"]


def test_agent_failure_is_reported_honestly_not_replaced_by_demo_data(with_key, monkeypatch):
    _serve(monkeypatch, exc=OSError("down"))
    r = agent2._find_hospital({"department": "眼科"})
    assert r["warn"] is True and "没有查到" in r["result"] and "演示数据" not in r["result"]


def test_agent_no_result_message(with_key, monkeypatch):
    _serve(monkeypatch, {"status": "1", "pois": []})
    r = agent2._find_hospital({"department": "眼科", "city": "某地"})
    assert r["warn"] is True and "未在某地检索到" in r["result"]


def test_agent_module_no_longer_imports_main():
    """分层：Agent（服务层）不得为了拿演示数据而反向依赖入口层 main。"""
    import inspect
    assert "import main" not in inspect.getsource(agent2)
