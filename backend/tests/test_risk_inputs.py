"""Risk rules must use observed facts and distinguish unsupported input."""
import agent
import agent2


def state(text):
    s = agent2._new()
    s['messages'].append({'role': 'user', 'content': text})
    return s


def test_v2_risk_reads_user_facts():
    r = agent._calc_risk(state('糖尿病病程10年，糖化血红蛋白8.2%，最近视力模糊'))
    assert r['score'] == 8
    assert len(r['reasons']) == 3


def test_unrelated_symptoms_do_not_receive_diabetic_low_risk():
    r = agent._calc_risk(state('肚子痛'))
    assert r['risk'] == '待评估'
    assert not r['assessable']


def test_negated_risk_factors_are_not_counted():
    r = agent._calc_risk(state('没有高血压，没有高血脂，视力没有下降'))
    assert r['score'] == 0


def test_arbitrary_years_and_percent_are_not_diabetes_measurements():
    r = agent._calc_risk(state('头晕10年，报告完成80%'))
    assert r['score'] == 0 and not r['assessable']


def test_negated_diabetes_duration_is_not_used():
    r = agent._calc_risk(state('没有糖尿病10年，最近视力没有下降'))
    assert r['score'] == 0 and not r['assessable']


def test_question_wording_is_not_a_positive_finding():
    s = agent2._new()
    s['collected'] = [('是否有高血压或高血脂？', '跳过')]
    r = agent._calc_risk(s)
    assert r['score'] == 0 and not r['assessable']


# ---- 共用评分函数 agent.score_risk（Agent 与 MCP 共用同一份实现）----
def test_score_risk_returns_pending_not_low_when_nothing_is_known():
    r = agent.score_risk()
    assert r["risk"] == "待评估" and r["assessable"] is False and "不能据此判断低风险" in r["reasons"][0]


def test_score_risk_thresholds_and_reasons():
    assert agent.score_risk(years=12, hba1c=8.4, level=3)["risk"] == "高"
    mid = agent.score_risk(years=6, hba1c=7.2)
    assert mid["risk"] == "中" and mid["score"] == 4
    up = agent.score_risk(level=3, prev_level=1)
    assert any("上升" in x for x in up["reasons"]) and up["score"] == 3 + 2
    better = agent.score_risk(level=1, prev_level=3)
    assert any("好转" in x for x in better["reasons"]) and better["score"] == 0


def test_score_risk_sudden_vision_change_is_an_acute_signal():
    r = agent.score_risk(vision_change=True, vision_sudden=True)
    assert r["score"] == 4 and "视力突发变化（急症信号）" in r["reasons"]


def test_mcp_style_arguments_map_to_the_same_rules():
    """mcp_server.calc_risk 的参数映射（0 = 未提供；dr_level < 0 = 无分级）。mcp SDK 未安装时无法导入该模块，这里复现映射。"""
    def mcp_like(diabetes_years, hba1c, vision_change, hypertension, dr_level, prev_dr_level=-1):
        return agent.score_risk(
            years=diabetes_years or None, hba1c=hba1c or None,
            vision_change=bool(vision_change), hypertension=bool(hypertension),
            level=dr_level if dr_level >= 0 else None, prev_level=prev_dr_level if prev_dr_level >= 0 else None)
    assert mcp_like(0, 0, False, False, -1)["risk"] == "待评估"      # 原 MCP 实现这里会返回「低」
    assert mcp_like(10, 8.0, True, True, 2, 1)["risk"] == "高"
