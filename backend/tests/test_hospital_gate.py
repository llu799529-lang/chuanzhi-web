"""没有高德 Web 服务 Key 时，不能把演示医院当结果给用户看。

实测反馈：Agent 调用「附近医院检索」后，把「【演示数据】后端未配置高德 Web 服务 Key……」原样展示给用户；
工作台也列出「XX区眼科专科医院」。现在：Agent 不提供这个工具、提示词不提它、离线导航只给「查看附近医院」按钮
（页面地图用浏览器 JS API 按位置实时检索），MCP 如实返回不可用。
"""
import json
import pathlib
import re

import agent2
import config
import hospitals
import planner
import safety
import tool_specs


def _names(tools):
    return [t["function"]["name"] for t in tools]


def test_agent_tools_follow_web_key(monkeypatch):
    names = _names(tool_specs.agent_tools(False))
    assert "find_hospital" not in names and {"search_kb", "calc_risk", "analyze_image"} <= set(names)
    assert "find_hospital" in _names(tool_specs.agent_tools(True))
    monkeypatch.setattr(config, "AMAP_API_KEY", "")
    assert hospitals.web_search_enabled() is False
    monkeypatch.setattr(config, "AMAP_API_KEY", "web-key-for-test")
    assert hospitals.web_search_enabled() is True


def test_system_prompt_drops_hospital_tool_without_web_key(monkeypatch):
    monkeypatch.setattr(config, "AMAP_API_KEY", "")
    prompt = agent2.system_prompt()
    assert "find_hospital" not in prompt and "查看附近医院" in prompt
    assert "\n\n工具参数易错点" in prompt and "6. 纯文字症状场景中" in prompt     # 其余规则原样保留
    monkeypatch.setattr(config, "AMAP_API_KEY", "web-key-for-test")
    assert agent2.system_prompt() == agent2.SYSTEM


def test_plan_has_no_hospital_step_without_web_key():
    for text in ("附近有哪些眼科医院", "头晕三天，该去哪家医院看"):
        assert "find_hospital" not in [x["tool"] for x in planner.make_plan(text, hospital_search=False)["steps"]]
    assert "find_hospital" in [x["tool"] for x in planner.make_plan("附近有哪些眼科医院")["steps"]]


def test_offline_navigation_gives_map_button_not_demo_hospitals(monkeypatch):
    monkeypatch.setattr(config, "AMAP_API_KEY", "")
    monkeypatch.setattr(agent2.llm, "llm_available", lambda *a, **k: False)
    agent2.reset("nav_no_web_key")
    out = "".join(agent2.stream("nav_no_web_key", "头晕三天，该去哪家医院看", None, "image/jpeg"))
    assert "演示数据" not in out and "XX" not in out and '"find_hospital"' not in out
    final = next(json.loads(b.split("data:", 1)[1]) for b in out.split("\n\n") if b.startswith("event: final"))
    assert any(a.get("a") == "hospital" for a in final.get("acts") or []), final.get("acts")


def test_mcp_hospital_tool_never_returns_demo_data(monkeypatch):
    import importlib.util
    if importlib.util.find_spec("mcp") is None:          # 未安装 mcp SDK 的环境只跳过这一条
        return
    import mcp_server
    monkeypatch.setattr(config, "AMAP_API_KEY", "")
    out = mcp_server.find_hospital("眼科")
    assert out["source"] == "unavailable" and out["hospitals"] == []


def test_guide_symptom_samples_agree_with_red_flag_rules():
    """使用指南里的症状示例：红旗示例必须命中急症规则，其余示例不能命中（否则演示会误导）。"""
    src = (pathlib.Path(__file__).resolve().parents[2] / "frontend/src/lib/guide.ts").read_text(encoding="utf-8")
    rows = re.findall(r'\{ label: "([^"]+)", text: "([^"]+)"(, red: true)? \}', src)
    assert len(rows) == 3
    for label, text, red in rows:
        assert safety.has_emergency(safety.detect(text)) == bool(red), label
