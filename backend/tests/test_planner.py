"""Agent 的规划（plan）与自检（reflect）。

自检要证明的不是「永远显示通过」，而是它**真的能抓到问题**——所以每一项都有一条会触发警告的负例，
并且用正例证明它不会误报（比如「高血压 2 级」「3 级医院」不能被当成 DR 分级）。
全部是纯函数 / 假 LLM，不联网。
"""
import json

import pytest

import agent2
import planner
import safety


def S(**kw):
    """最小会话状态。"""
    base = {"image": None, "analysis": None, "kb": None, "kb_calls": 0, "history": None,
            "hospital": None, "safety": [], "used": []}
    base.update(kw)
    return base


def status(refl, cid):
    return next(c["status"] for c in refl["checks"] if c["id"] == cid)


# ---------------------------------------------------------------- 规划
def test_plan_for_text_symptom_requires_kb_and_ends_with_report_and_reflect():
    p = planner.make_plan("咳嗽三天，有点黄痰")
    tools = [x["tool"] for x in p["steps"]]
    assert p["source"] == "rule" and p["intent"] == "symptom"
    assert tools[0] == "search_kb" and tools[-2:] == ["report", "reflect"]
    assert next(x for x in p["steps"] if x["tool"] == "search_kb")["required"] is True
    assert "analyze_image" not in tools and "规则规划" in p["note"]


def test_plan_for_image_starts_with_optional_ask_then_history_and_image_analysis():
    tools = [x["tool"] for x in planner.make_plan("", has_image=True)["steps"]]
    assert tools[:3] == ["ask_user", "get_history", "analyze_image"]
    assert "ask_user" not in [x["tool"] for x in planner.make_plan("", has_image=True, can_ask=False)["steps"]]


@pytest.mark.parametrize("text,nav", [
    ("附近有哪些眼科医院", True), ("我应该挂什么科", True), ("请问哪家医院看皮肤科比较好", True),
    ("头晕三天，附近哪家医院", False), ("咳嗽三天", False), ("", False),
])
def test_navigation_only_detection(text, nav):
    assert planner.is_navigation_only(text) is nav


def test_navigation_plan_is_just_hospital_then_report():
    p = planner.make_plan("附近有哪些眼科医院")
    assert p["intent"] == "navigation" and [x["tool"] for x in p["steps"]][0] == "find_hospital"
    assert "search_kb" not in [x["tool"] for x in p["steps"]]


def test_plan_mentions_red_flag_review_first_when_rules_hit():
    flags = safety.detect("胸口有点疼，上楼时更明显")
    p = planner.make_plan("胸口有点疼，上楼时更明显", flags=flags)
    assert p["steps"][0]["tool"] == "safety_gate" and "橙色" in p["steps"][0]["why"]


def test_plan_steps_are_numbered_consecutively():
    steps = planner.make_plan("头晕", has_image=False)["steps"]
    assert [x["n"] for x in steps] == list(range(1, len(steps) + 1))


# ---------------------------------------------------------------- 自检：每项一条负例 + 一条正例
def test_clean_report_passes():
    r = planner.reflect(S(kb=[{"x": 1}], kb_calls=1), "建议先到呼吸内科就诊，观察症状变化，持续加重请及时就医。")
    assert r["verdict"] == "pass" and r["source"] == "rule" and "addendum" not in r
    assert status(r, "evidence") == "ok" and status(r, "overreach") == "ok"


def test_evidence_warns_when_text_symptom_never_searched_kb():
    r = planner.reflect(S(), "建议到全科门诊就诊。")
    assert status(r, "evidence") == "warn" and r["verdict"] == "attention"


def test_evidence_warns_when_image_uploaded_but_no_analysis():
    r = planner.reflect(S(image=b"x", kb_calls=1), "你的眼底没有问题。")
    assert status(r, "evidence") == "warn" and "图像分析" in next(c["detail"] for c in r["checks"] if c["id"] == "evidence")


def test_navigation_request_does_not_need_kb():
    r = planner.reflect(S(hospital={"dept": "眼科", "result": "x"}), "可以去市第一人民医院眼科。")
    assert status(r, "evidence") == "ok"


@pytest.mark.parametrize("text,expected", [
    ("你的眼底是DR 4级，建议尽快就诊", {4}),
    ("糖网分级为3级，属于重度非增殖期", {3}),
    ("较上次的1级上升到2级的糖尿病视网膜病变", {1, 2}),
    ("合并高血压2级，需要控制血压", set()),
    ("建议去3级医院眼科就诊", set()),
    ("2周内复查，每3个月随访", set()),
])
def test_mentioned_grades_only_counts_fundus_context(text, expected):
    assert planner.mentioned_grades(text) == expected


def test_grade_warns_when_report_contradicts_the_analysis():
    s = S(kb_calls=1, analysis={"kind": "fundus", "level": 1, "urgency": "green"})
    r = planner.reflect(s, "你的眼底属于 DR 4 级，需要立即治疗。")
    assert status(r, "grade") == "warn"
    detail = next(c["detail"] for c in r["checks"] if c["id"] == "grade")
    assert "4" in detail and "1" in detail


def test_grade_ok_when_matches_analysis_or_history():
    s = S(kb_calls=1, analysis={"kind": "fundus", "level": 2, "urgency": "yellow"}, history=[{"level": 1}])
    assert status(planner.reflect(s, "较上次的1级上升到DR 2级，建议3个月内复查。"), "grade") == "ok"


def test_grade_warns_when_report_invents_a_grade_with_no_basis():
    r = planner.reflect(S(kb_calls=1), "你的糖网病变是2级。")
    assert status(r, "grade") == "warn" and "没有眼底分析" in next(c["detail"] for c in r["checks"] if c["id"] == "grade")


def test_red_flag_fails_when_text_never_tells_user_to_seek_care_and_adds_addendum():
    flags = safety.detect("胸口有点疼，上楼时更明显")
    r = planner.reflect(S(kb_calls=1, safety=flags, analysis={"kind": "symptom", "urgency": "orange"}), "多休息，注意饮食。")
    assert status(r, "red_flag") == "fail" and r["verdict"] == "attention"
    assert "胸痛" in r["addendum"] and "不依赖大模型" in r["addendum"] and "24 小时" in r["addendum"]


@pytest.mark.parametrize("plain", ["医生会帮助你，先观察一周。", "不用去医院，休息就好。", "建议一周后到门诊就诊。"])
def test_red_flag_requires_timely_care_not_just_a_care_word(plain):
    flags = safety.detect("胸口有点疼，上楼时更明显")
    r = planner.reflect(S(kb_calls=1, safety=flags, analysis={"kind": "symptom", "urgency": "orange"}), plain)
    assert status(r, "red_flag") == "fail"
    assert "addendum" in r


def test_red_flag_ok_when_text_mentions_care():
    flags = safety.detect("胸口有点疼，上楼时更明显")
    r = planner.reflect(S(kb_calls=1, safety=flags, analysis={"kind": "symptom", "urgency": "orange"}), "建议尽快到心内科就诊。")
    assert status(r, "red_flag") == "ok" and "addendum" not in r


def test_urgency_fails_when_analysis_is_below_rule_floor():
    flags = safety.detect("胸口有点疼，上楼时更明显")
    lab = {"kind": "lab", "urgency": "green", "department": "全科"}      # 化验单分析不受症状托底影响
    r = planner.reflect(S(kb_calls=1, safety=flags, analysis=lab, image=b"x"), "化验单大致正常，建议就医复查。")
    assert status(r, "urgency") == "fail" and "紧急度偏低" in r["addendum"]


def test_urgency_ok_when_not_below_floor():
    flags = safety.detect("胸口有点疼，上楼时更明显")
    r = planner.reflect(S(kb_calls=1, safety=flags, analysis={"kind": "symptom", "urgency": "red"}), "请尽快就医。")
    assert status(r, "urgency") == "ok"


@pytest.mark.parametrize("plain", ["你已确诊为糖尿病视网膜病变。", "保证治愈，无需就医。", "每天2片，每次500mg。"])
def test_overreach_fails_on_diagnosis_cure_promises_and_dosage(plain):
    assert status(planner.reflect(S(kb_calls=1), plain), "overreach") == "fail"


def test_grounding_is_informational_and_labeled_as_lower_bound():
    r = planner.reflect(S(kb_calls=1), "建议到心内科就诊，做心电图检查。其他情况请观察。")
    g = next(c for c in r["checks"] if c["id"] == "grounding")
    assert g["status"] in ("info", "warn") and "下界" in g["detail"] and "不是正确率" in g["detail"]


def test_reflect_never_mutates_report_or_state():
    s = S(kb_calls=1, kb=[{"a": 1}], safety=safety.detect("胸口有点疼，上楼时更明显"))
    snapshot = json.dumps({k: v for k, v in s.items() if k != "safety"}, default=str, sort_keys=True)
    plain = "多休息。"
    planner.reflect(s, plain)
    assert plain == "多休息。" and json.dumps({k: v for k, v in s.items() if k != "safety"}, default=str, sort_keys=True) == snapshot


def test_summary_counts_add_up():
    r = planner.reflect(S(kb_calls=1), "建议就诊。")
    sm = r["summary"]
    assert sm["total"] == len(r["checks"]) == sm["ok"] + sm["info"] + sm["attention"]


# ---------------------------------------------------------------- 接入 agent2：事件顺序与 final 载荷
def _events(chunks):
    out = []
    for block in "".join(chunks).split("\n\n"):
        if not block.strip():
            continue
        ev, data = "message", ""
        for line in block.split("\n"):
            if line.startswith("event:"):
                ev = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].lstrip()
        out.append((ev, json.loads(data) if data else {}))
    return out


def _fake(available=True, text="建议先到呼吸内科就诊。"):
    class L:
        @staticmethod
        def llm_available():
            return available

        @staticmethod
        def chat(messages, **kw):
            return {"content": "ok", "tool_calls": []}

        @staticmethod
        def stream_chat(messages, **kw):
            yield text
    return L


def test_online_flow_emits_plan_first_then_reflect_before_final(monkeypatch):
    monkeypatch.setattr(agent2, "llm", _fake())
    agent2.reset("plan_user")
    evs = _events(agent2.stream("plan_user", "咳嗽三天，有点黄痰", None, "image/jpeg"))
    names = [e for e, _ in evs]
    assert names.count("plan") == 1 and names[0] == "plan"
    assert names.index("reflect") < names.index("final") and names.index("token") < names.index("reflect")
    final = dict(evs)["final"]
    assert final["reflection"]["verdict"] in ("pass", "attention") and final["reflection"]["source"] == "rule"
    plan = dict(evs)["plan"]
    assert plan["source"] == "rule" and plan["steps"][0]["tool"] == "search_kb"


def test_plan_is_emitted_once_per_session_not_on_every_turn(monkeypatch):
    class Ask(_fake()):
        n = 0

        @staticmethod
        def chat(messages, **kw):
            Ask.n += 1
            if Ask.n == 1:
                return {"content": "", "tool_calls": [{"id": "c1", "function": {"name": "ask_user", "arguments": json.dumps(
                    {"question": "糖尿病多少年了？", "chips": ["5年"]})}}]}
            return {"content": "ok", "tool_calls": []}

    monkeypatch.setattr(agent2, "llm", Ask)
    agent2.reset("plan_user2")
    first = [e for e, _ in _events(agent2.stream("plan_user2", "最近眼睛有点模糊", None, "image/jpeg"))]
    second = [e for e, _ in _events(agent2.stream("plan_user2", "5年了", None, "image/jpeg"))]
    assert first.count("plan") == 1 and "plan" not in second


def test_greeting_gets_neither_plan_nor_reflection(monkeypatch):
    monkeypatch.setattr(agent2, "llm", _fake())
    agent2.reset("plan_user3")
    assert [e for e, _ in _events(agent2.stream("plan_user3", "你好", None, "image/jpeg"))] == ["final"]


def test_emergency_gate_short_circuit_has_no_plan_or_reflect(monkeypatch):
    monkeypatch.setattr(agent2, "llm", _fake())
    agent2.reset("plan_user4")
    names = [e for e, _ in _events(agent2.stream("plan_user4", "突然呕血，血流不止", None, "image/jpeg"))]
    assert "plan" not in names and "reflect" not in names and "final" in names


def test_offline_flow_also_plans_and_reflects(monkeypatch):
    monkeypatch.setattr(agent2, "llm", _fake(available=False))
    agent2.reset("plan_user5")
    evs = _events(agent2.stream("plan_user5", "头晕两天，晨起明显", None, "image/jpeg"))
    names = [e for e, _ in evs]
    assert names[0] == "plan" and names.index("reflect") < names.index("final")
    assert dict(evs)["final"]["reflection"]["checks"]


def test_reflection_failure_never_breaks_the_report(monkeypatch):
    monkeypatch.setattr(agent2, "llm", _fake())
    monkeypatch.setattr(agent2.planner, "reflect", lambda s, p: (_ for _ in ()).throw(RuntimeError("boom")))
    agent2.reset("plan_user6")
    evs = _events(agent2.stream("plan_user6", "咳嗽三天，有点黄痰", None, "image/jpeg"))
    names = [e for e, _ in evs]
    assert "final" in names and "error" not in names and "reflect" not in names
    assert "reflection" not in dict(evs)["final"]
