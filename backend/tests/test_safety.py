"""确定性红旗闸门（safety.py）的测试。

三类断言：
  1. 每条规则自带的 example 必须命中自己（规则表自检，防止改正则时悄悄失效）；
  2. 否定 / 既往 / 已缓解 / 良性文本不能误报（把正常人吓成急诊同样是事故）；
  3. 托底只升不降、幂等；急症短路不调用大模型。
"""
import json
from pathlib import Path

import pytest

import safety

EVALS = Path(__file__).resolve().parent.parent / "evals"


@pytest.mark.parametrize("rule", safety.RULES, ids=lambda r: r.id)
def test_every_rule_example_hits_its_own_rule(rule):
    ids = {f.id for f in safety.detect(rule.example)}
    assert rule.id in ids, f"{rule.id} 的示例未命中自己：{rule.example!r} → {ids}"


def test_rule_ids_unique_and_severities_valid():
    ids = [r.id for r in safety.RULES]
    assert len(ids) == len(set(ids))
    assert {r.severity for r in safety.RULES} <= {safety.EMERGENCY, safety.URGENT}


@pytest.mark.parametrize("text", [
    "没有胸痛，只是有点头晕", "以前有过胸痛，现在没事", "胸痛已经没有了", "无明显胸闷", "否认胸痛",
    "有无胸痛？", "并没有呼吸困难", "不曾晕倒", "去年有过一次晕厥", "排除卒中",
    "笑死我了", "食物中毒拉肚子", "眼皮抽搐好几天", "对花粉过敏，鼻子痒",
    "餐后2小时血糖 7.8", "空腹血糖 6.1，糖化8.2", "血糖控制得不错", "血糖测了3次",
    "头晕两天，晨起明显", "咳嗽三天有点黄痰", "最近胃痛反酸", "腰酸背痛，睡不好",
    "我想挂眼科，附近有哪些医院", "糖尿病十年，视力慢慢变模糊", "", "   ",
])
def test_negated_historical_or_benign_text_does_not_flag(text):
    assert safety.detect(text) == [], text


@pytest.mark.parametrize("text,rule,severity", [
    ("我爸突然说话含糊，嘴角歪了", "stroke", safety.EMERGENCY),
    ("最近说话有点含糊", "stroke", safety.URGENT),            # 没有「突然」只到橙色
    ("胸口有点疼，上楼时更明显", "chest_pain", safety.URGENT),  # 单独胸痛只到橙色
    ("胸口疼，出了一身冷汗，放射到左肩", "acs", safety.EMERGENCY),
    ("没有发烧，但是呼吸困难，很厉害", "dyspnea", safety.EMERGENCY),
    ("他刚才晕倒了，醒来后还在胡言乱语", "syncope", safety.URGENT),
    ("视力突然下降，眼前一块黑影", "eye_emergency", safety.EMERGENCY),
    ("我不想活了", "self_harm", safety.EMERGENCY),
    ("怀孕30周，阴道出血", "pregnancy", safety.EMERGENCY),
    ("孩子误服了一把药片", "poison_trauma", safety.EMERGENCY),
    ("血糖22.4，恶心呕吐", "glucose", safety.EMERGENCY),
    ("血糖2.6，出冷汗", "glucose", safety.EMERGENCY),
    ("血糖 600 mg/dL", "glucose", safety.EMERGENCY),       # 数值过大按 mg/dL 理解
    ("这两天解黑便，人有点乏力", "bleeding_urgent", safety.URGENT),
])
def test_expected_flags_and_severity(text, rule, severity):
    got = {f.id: f.severity for f in safety.detect(text)}
    assert got.get(rule) == severity, (text, got)


def test_strong_rule_supersedes_weak_duplicate():
    ids = {f.id for f in safety.detect("胸口疼，出了一身冷汗，放射到左肩")}
    assert "acs" in ids and "chest_pain" not in ids


def test_emergencies_sorted_first():
    flags = safety.detect("最近有点胸闷，今天突然说话含糊嘴角歪了")
    assert flags[0].severity == safety.EMERGENCY


def test_negation_does_not_leak_across_clauses():
    # 「没有发烧」的否定不能吞掉后一句的「呼吸困难」
    assert safety.has_emergency(safety.detect("没有发烧，突然呼吸困难，嘴唇发紫"))


def test_evidence_is_returned_and_short():
    f = safety.detect("突然呕血，血流不止")[0]
    assert f.evidence and len(f.evidence) <= 40


def test_prompt_note_states_floor():
    assert "红色" in safety.prompt_note(safety.detect("突然呕血"))
    assert "橙色" in safety.prompt_note(safety.detect("胸口有点疼"))
    assert safety.prompt_note([]) == ""


def _card(urgency="yellow", dept="全科"):
    return {"kind": "symptom", "urgency": urgency, "urg": "黄色 · 建议 1 周内就诊", "dept": dept,
            "alt": "", "reds": ["原有红旗"], "suspects": [["a", 40, ""]]}


def test_apply_floor_only_raises_never_lowers():
    red = safety.apply_floor(_card("green"), safety.detect("突然呕血"))
    assert red["urgency"] == "red" and "120" in red["urg"] and red["safety"]["raised"] is True
    # 模型已经给了红色，规则只有橙色：不能被压低
    kept = safety.apply_floor(_card("red"), safety.detect("胸口有点疼"))
    assert kept["urgency"] == "red" and kept["safety"]["raised"] is False


def test_apply_floor_is_idempotent_and_keeps_old_reds():
    flags = safety.detect("突然呕血")
    once = safety.apply_floor(_card("green"), flags)
    snapshot = json.dumps(once, ensure_ascii=False, sort_keys=True)
    twice = safety.apply_floor(once, flags)
    assert json.dumps(twice, ensure_ascii=False, sort_keys=True) == snapshot
    assert "原有红旗" in twice["reds"]


def test_apply_floor_without_flags_is_noop():
    c = _card("green")
    before = json.dumps(c, sort_keys=True)
    assert json.dumps(safety.apply_floor(c, []), sort_keys=True) == before


def test_apply_floor_ignores_non_symptom_cards():
    fundus = {"kind": "fundus", "urgency": "green"}
    assert safety.apply_floor(fundus, safety.detect("突然呕血")) == {"kind": "fundus", "urgency": "green"}


def test_emergency_card_has_no_fabricated_probabilities():
    flags = safety.detect("我爸突然说话含糊，嘴角歪了")
    card = safety.emergency_symptom_card("x", flags)
    assert card["urgency"] == "red" and card["suspects"] == []        # 不编造百分比
    assert card["source"] == "safety_gate" and "未调用大模型" in card["safety_note"]
    assert any("120" in p for p in card["prep"])


def test_emergency_plain_text_mentions_120_and_not_diagnosis():
    text = safety.emergency_plain(safety.detect("突然呕血"))
    assert "120" in text and "不是诊断" in text


# ---- 接入 analyze_symptom：红旗短路不调模型；橙色托底；模型挂了仍有红旗 ----
def test_analyze_symptom_short_circuits_emergency_without_calling_model(monkeypatch):
    import ai_analysis

    def boom(*a, **k):
        raise AssertionError("急症不应调用大模型")

    monkeypatch.setattr(ai_analysis.llm, "chat_json", boom)
    card = ai_analysis.analyze_symptom("我爸突然说话含糊，嘴角歪了")
    assert card["urgency"] == "red" and card["source"] == "safety_gate"


def test_analyze_symptom_floors_orange_even_if_model_says_green(monkeypatch):
    import ai_analysis
    monkeypatch.setattr(ai_analysis.llm, "chat_json", lambda *a, **k: {
        "hits": ["胸痛"], "echo": "胸痛", "dept": "全科", "urg": "绿色 · 可择期门诊", "alt": "",
        "suspects": [["肋间神经痛", 60, "x"]], "tests": ["心电图 · 评估"], "prep": ["p"], "reds": []})
    card = ai_analysis.analyze_symptom("胸口有点疼，上楼时更明显")
    assert card["urgency"] == "orange" and card["safety"]["raised"] is True
    assert any("胸痛" in r for r in card["reds"])


def test_analyze_symptom_keeps_flag_when_model_is_down(monkeypatch):
    import ai_analysis

    def down(*a, **k):
        raise RuntimeError("HTTP 429 QuotaExceeded")

    monkeypatch.setattr(ai_analysis.llm, "chat_json", down)
    card = ai_analysis.analyze_symptom("胸口有点疼，上楼时更明显")
    assert card["degraded"] is True and card["urgency"] in ("orange", "red")


def test_benign_symptom_text_is_not_raised(monkeypatch):
    import ai_analysis
    monkeypatch.setattr(ai_analysis.llm, "chat_json", lambda *a, **k: {
        "hits": ["头晕"], "echo": "头晕", "dept": "神经内科", "urg": "黄色 · 建议 1 周内就诊", "alt": "",
        "suspects": [["BPPV", 50, "x"]], "tests": ["前庭功能 · x"], "prep": ["p"], "reds": []})
    card = ai_analysis.analyze_symptom("头晕两天，晨起明显")
    assert card["urgency"] == "yellow" and "safety" not in card


# ---- 误报哨兵：评测语料里的「红色」命中必须是真急症 ----
def test_red_hits_on_existing_eval_corpus_are_all_real_emergencies():
    gold = json.loads((EVALS / "golden_queries.json").read_text(encoding="utf-8"))["queries"]
    blind = json.loads((EVALS / "blind_queries.json").read_text(encoding="utf-8"))
    qs = [q.get("q") or q.get("query") for q in gold if isinstance(q, dict)]
    for b in blind.get("batches", []):
        qs += [(i.get("q") or i.get("query")) for i in (b.get("queries") or b.get("items") or []) if isinstance(i, dict)]
    qs = [q for q in qs if q]
    assert len(qs) >= 100
    reds = [(q, [f.id for f in safety.detect(q) if f.severity == safety.EMERGENCY]) for q in qs]
    reds = [(q, ids) for q, ids in reds if ids]
    # 当前语料里命中红色的 7 条都是胸痛放射/卒中/雷击样头痛/视力骤降/呕血这类真急症
    assert 4 <= len(reds) <= 14, reds
    benign_markers = ("头晕两天", "咳嗽", "皮疹", "便秘", "失眠")
    assert not [q for q, _ in reds if any(m in q for m in benign_markers)], reds
