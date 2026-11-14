"""红旗规则的循证依据：登记的来源必须真实存在于已核实的文献登记表，且为高可信度。"""
import json
import pathlib

import safety

_REG = json.loads((pathlib.Path(__file__).resolve().parent.parent / "kb_sources.json").read_text(encoding="utf-8"))
_RAW = _REG["sources"] if isinstance(_REG, dict) else _REG
SOURCES = dict(_RAW.items()) if isinstance(_RAW, dict) else {s["id"]: s for s in _RAW}


def test_every_rule_is_listed_exactly_once():
    assert set(safety.RULE_BASIS) == {r.id for r in safety.RULES}


def test_every_cited_basis_is_a_registered_high_confidence_source():
    cited = {sid for ids in safety.RULE_BASIS.values() for sid in ids} | set(safety.GLUCOSE_BASIS)
    missing = sorted(sid for sid in cited if sid not in SOURCES)
    weak = sorted(sid for sid in cited if sid in SOURCES and SOURCES[sid].get("confidence") != "high")
    assert not missing and not weak, (missing, weak)


def test_coverage_does_not_silently_shrink():
    covered = [r.id for r in safety.RULES if safety.RULE_BASIS[r.id]]
    assert len(covered) >= 17, covered


def test_detected_flags_carry_their_basis():
    flags = safety.detect("我胸口疼，出了一身冷汗，还放射到左肩")
    assert "chestpain_cn_2019" in safety.basis_ids(flags)
    assert safety.basis_ids(safety.detect("空腹血糖 2.6，手在发抖出冷汗")) == ["dm_cn_2024"]


def test_symptom_card_lists_the_basis_of_its_red_flags():
    import screening
    card = {"kind": "symptom", "hits": [], "echo": "胸痛", "dept": "全科", "urg": "绿色", "alt": "", "suspects": [],
            "tests": [], "prep": [], "reds": [], "urgency": "green", "degraded": False}
    out = screening.finalize_symptom(card, "我胸口疼，出了一身冷汗，还放射到左肩", "basis_user")
    basis = out["safety"]["basis"]
    assert any("胸痛" in b["title"] for b in basis) and all(b["url"].startswith("http") for b in basis)


def test_benign_text_has_no_basis_and_no_safety_block():
    import screening
    card = {"kind": "symptom", "hits": [], "echo": "头晕", "dept": "神经内科", "urg": "黄色", "alt": "", "suspects": [],
            "tests": [], "prep": [], "reds": [], "urgency": "yellow", "degraded": False}
    assert "safety" not in screening.finalize_symptom(card, "头晕两天，晨起明显", "basis_user2")


def test_agent_emergency_final_carries_the_basis():
    import json

    import agent2
    agent2.reset("basis_agent")
    blocks = "".join(agent2.stream("basis_agent", "我胸口疼，出了一身冷汗，还放射到左肩", None, "image/jpeg")).split("\n\n")
    final = next(json.loads(b.split("data:", 1)[1]) for b in blocks if b.startswith("event: final"))
    assert final["engine"] == "safety_gate" and any("胸痛" in b["title"] for b in final["safety_basis"])


def test_mcp_red_flag_tool_lists_the_basis():
    import importlib.util
    if importlib.util.find_spec("mcp") is None:          # 未安装 mcp SDK 的环境（mcp_server 导入时会直接退出）只跳过这一条
        return
    import mcp_server
    out = mcp_server.check_red_flags("我胸口疼，出了一身冷汗，还放射到左肩")
    assert out["emergency"] and any("胸痛" in b["title"] for b in out["basis"])
    assert mcp_server.check_red_flags("头晕两天，晨起明显")["basis"] == []
