"""内联引用（citations.py）、参考文献登记表读取（sources.py）、以及 Agent 的「自检 → 修复」闭环。

全部离线：假 LLM；不联网、不消耗额度。重点是负例——引用必须**可校验**、修复不能让报告变差。
"""
import json

import pytest

import agent2
import citations
import rag
import sources


def hits_for(query, k=3):
    return rag.retrieve(query, top_k=k)


# ---------------------------------------------------------------- sources.py
def test_registry_exposes_only_high_confidence_sources_and_verify_links():
    d = sources.describe(["dr_cn_2022", "hyperk_cn", "no_such_id"])
    assert [x["id"] for x in d] == ["dr_cn_2022"]               # medium 与未登记的都被丢弃
    assert d[0]["verify_url"].startswith("http") and "糖尿病视网膜病变" in d[0]["title"]


def test_placeholder_issuer_and_citation_are_blanked_not_shown():
    d = sources.describe(["hypothyroid_cn_2017"])               # issuer 写的是「（检索结果未明确…）」
    assert d and d[0]["issuer"] == ""


def test_registry_is_found_regardless_of_where_the_database_directory_points():
    """登记表跟随代码目录，不跟随数据目录：数据库换到别处（测试临时目录 / 部署挂载卷）不能影响它。"""
    import config
    assert config.DATA_DIR != config.BASE_DIR                      # conftest 已把 DATA_DIR 指到临时目录
    assert sources._REG_PATH.parent == config.BASE_DIR
    assert sources.registry()["sources"]


# ---------------------------------------------------------------- 证据编号
def test_evidence_numbering_matches_format_context_numbering():
    hits = hits_for("糖尿病视网膜病变 增殖期")
    ev = citations.from_hits(hits)
    ctx = rag.format_context(hits)
    assert [e.n for e in ev] == list(range(1, len(hits) + 1))
    for e in ev:
        assert f"[{e.n}] {e.category}" in ctx, "给模型看的 [n] 与证据编号必须同源"


def test_evidence_carries_registry_sources_for_the_entry():
    ev = citations.from_hits(hits_for("糖尿病视网膜病变 增殖期"))
    pub = ev[0].public()
    assert pub["sources"] and all(s["verify_url"].startswith("http") for s in pub["sources"])


def test_from_hits_and_from_refs_agree():
    hits = hits_for("咳嗽三天，有点黄痰")
    a = citations.from_hits(hits)
    b = citations.from_refs(rag.refs_payload(hits))
    assert [(e.n, e.entry_id) for e in a] == [(e.n, e.entry_id) for e in b]


def test_empty_inputs_give_empty_evidence():
    assert citations.from_hits([]) == [] and citations.from_hits(None) == [] and citations.from_refs(None) == []
    assert citations.prompt_rules([]) == ""


def test_prompt_rules_bound_the_valid_range():
    ev = citations.from_hits(hits_for("咳嗽三天，有点黄痰", 2))
    assert f"[1]–[{len(ev)}]" in citations.prompt_rules(ev) and "不要编造编号" in citations.prompt_rules(ev)


# ---------------------------------------------------------------- 编号校验
def _ev(n=2):
    return citations.from_hits(hits_for("咳嗽三天，有点黄痰", n))


@pytest.mark.parametrize("raw,expected", [
    ("建议到呼吸内科[1]。", [1]), ("建议到呼吸内科［1］。", [1]), ("建议【2】。", [2]),
    ("两处依据[1,2]", [1, 2]), ("两处依据[1、2]", [1, 2]), ("[a] [12345] [] 没有编号", []),
])
def test_markers_recognizes_bracket_variants_only(raw, expected):
    assert citations.markers(raw) == expected


def test_sanitize_removes_out_of_range_numbers_and_reports_them():
    text, invalid = citations.sanitize("先去呼吸内科[1]，再做胸片[9]。", _ev(2))
    assert text == "先去呼吸内科[1]，再做胸片。" and invalid == [9]


def test_sanitize_splits_mixed_groups_and_folds_duplicates():
    text, invalid = citations.sanitize("依据[1,7,1]，另见[2][2]。", _ev(2))
    assert text == "依据[1]，另见[2]。" and invalid == [7]


def test_sanitize_with_no_evidence_strips_every_marker():
    text, invalid = citations.sanitize("建议就诊[1][2]。", [])
    assert "[" not in text and invalid == [1, 2]


def test_sanitize_normalizes_fullwidth_brackets():
    assert citations.sanitize("建议［1］。", _ev(2))[0] == "建议[1]。"


def test_analyze_reports_cited_invalid_and_support():
    ev = _ev(2)
    cit = citations.analyze("到呼吸内科就诊[1]，做胸片[1]。多喝水[2]。随便说[9]。", ev)
    assert cit["cited"] == [1, 2] and cit["invalid"] == [9] and cit["evidence_n"] == len(ev)
    assert "[9]" not in cit["text"]
    assert cit["support"]["checked"] >= 2


def test_support_flags_cited_sentences_with_no_term_from_the_cited_entry():
    ev = _ev(2)
    cit = citations.analyze("今天天气不错，适合散步[1]。", ev)
    assert cit["support"]["checked"] == 1 and cit["support"]["supported"] == 0
    assert cit["support"]["unsupported"][0]["n"] == 1
    assert "天气" in cit["support"]["unsupported"][0]["sentence"]


def test_support_accepts_a_sentence_that_uses_the_entrys_own_terms():
    ev = citations.from_hits(hits_for("糖尿病视网膜病变 增殖期", 1))
    dept = rag.all_entries()
    entry = next(e for e in dept if e["id"] == ev[0].entry_id)
    term = entry["tests"][0].split("·")[0].strip(" +")
    cit = citations.analyze(f"建议做{term}[1]。", ev)
    assert cit["support"]["supported"] == 1


def test_analyze_without_markers_does_not_claim_any_support():
    cit = citations.analyze("建议尽快就诊。", _ev(2))
    assert cit["cited"] == [] and cit["support"]["checked"] == 0


# ---------------------------------------------------------------- Agent：在线路径
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


def _llm(draft, revised=None, available=True, chat_raises=False, seen=None):
    """chat 第 1 次：不调工具；之后（若有）是 repair 的重写。stream_chat 吐出 draft。"""
    calls = {"chat": 0}

    class L:
        @staticmethod
        def llm_available():
            return available

        @staticmethod
        def chat(messages, **kw):
            calls["chat"] += 1
            if calls["chat"] == 1:
                return {"content": "ok", "tool_calls": []}
            if seen is not None:
                seen.append(messages)
            if chat_raises:
                raise RuntimeError("HTTP 429 QuotaExceeded")
            return {"content": revised or "", "tool_calls": []}

        @staticmethod
        def stream_chat(messages, **kw):
            if seen is not None:
                seen.append(("final_prompt", messages[-1]["content"]))
            yield draft

    L.calls = calls
    return L


def run(user, text):
    agent2.reset(user)
    return _events(agent2.stream(user, text, None, "image/jpeg"))


def test_final_prompt_contains_numbered_evidence_and_citation_rules(monkeypatch):
    seen = []
    monkeypatch.setattr(agent2, "llm", _llm("建议到呼吸内科就诊[1]。", seen=seen))
    run("cite_u1", "咳嗽三天，有点黄痰")
    prompt = next(m[1] for m in seen if isinstance(m, tuple))
    assert prompt.startswith("请基于以下工具结果") and "引用规则" in prompt and "[1]" in prompt


def test_final_carries_citations_with_verifiable_sources(monkeypatch):
    monkeypatch.setattr(agent2, "llm", _llm("建议先到呼吸内科就诊[1]，必要时做胸片检查[1]。"))
    final = dict(run("cite_u2", "咳嗽三天，有点黄痰"))["final"]
    c = final["citations"]
    assert c["cited"] == [1] and c["invalid_removed"] == []
    ev1 = next(e for e in c["evidence"] if e["n"] == 1)
    assert ev1["cited"] is True and ev1["category"]
    assert any(e["cited"] is False for e in c["evidence"]) or len(c["evidence"]) == 1


def test_invented_citation_numbers_are_removed_from_the_final_text(monkeypatch):
    monkeypatch.setattr(agent2, "llm", _llm("建议到呼吸内科就诊[1]，也可能是别的病[8]。"))
    final = dict(run("cite_u3", "咳嗽三天，有点黄痰"))["final"]
    assert "[8]" not in final["plain"] and "[1]" in final["plain"]
    assert final["citations"]["invalid_removed"] == [8]
    cit_check = next(c for c in final["reflection"]["checks"] if c["id"] == "citation")
    assert cit_check["status"] == "info" and "清除了不存在的编号 8" in cit_check["detail"]


def test_citation_check_is_informational_and_never_triggers_a_repair(monkeypatch):
    llm = _llm("建议就诊，没有任何引用。")
    monkeypatch.setattr(agent2, "llm", llm)
    evs = run("cite_u4", "咳嗽三天，有点黄痰")
    assert "repair" not in [e for e, _ in evs] and llm.calls["chat"] == 1


def test_no_evidence_means_no_citation_payload_and_no_rules(monkeypatch):
    seen = []
    monkeypatch.setattr(agent2, "llm", _llm("附近可以去市第一人民医院。", seen=seen))
    final = dict(run("cite_u5", "附近有哪些眼科医院"))["final"]
    prompt = next(m[1] for m in seen if isinstance(m, tuple))
    assert "引用规则" not in prompt and "citations" not in final


# ---------------------------------------------------------------- Agent：自检 → 修复
RED_NO_CARE = "多休息，注意饮食，别太累。"                     # 胸痛但没有任何就医提示
RED_FIXED = "你的描述里有胸痛，建议尽快到心内科就诊，持续加重请及时就医[1]。"


def test_repair_is_attempted_when_flagged_report_never_tells_user_to_seek_care(monkeypatch):
    seen = []
    llm = _llm(RED_NO_CARE, revised=RED_FIXED, seen=seen)
    monkeypatch.setattr(agent2, "llm", llm)
    evs = run("rep_u1", "胸口有点疼，上楼时更明显")
    names = [e for e, _ in evs]
    assert names.count("repair") == 2 and names.index("repair") < names.index("reflect") < names.index("final")
    start, done = [d for e, d in evs if e == "repair"]
    assert start["stage"] == "start" and "红旗提示" in start["reasons"]
    assert done["stage"] == "done" and done["accepted"] is True and done["after"] < done["before"]
    final = dict(evs)["final"]
    assert final["plain"] == RED_FIXED and final["repair"]["accepted"] is True
    assert llm.calls["chat"] == 2                                   # 只多了一次调用
    critique = [m for m in seen if isinstance(m, list)][0][-1]["content"]
    assert "红旗提示" in critique and "不要新增" in critique


def test_a_repair_that_makes_things_worse_is_rejected_and_the_draft_is_kept(monkeypatch):
    bad_revision = "你已确诊为冠心病，建议处方：每天2片药。"      # 引入越界表述 + 仍无就医提示
    monkeypatch.setattr(agent2, "llm", _llm(RED_NO_CARE, revised=bad_revision))
    evs = run("rep_u2", "胸口有点疼，上楼时更明显")
    final = dict(evs)["final"]
    done = [d for e, d in evs if e == "repair"][-1]
    assert done["accepted"] is False
    assert final["plain"] == RED_NO_CARE and "确诊为" not in final["plain"]
    assert "addendum" in final["reflection"]                         # 规则补充提示兜底


def test_repair_that_fixes_nothing_is_also_rejected(monkeypatch):
    monkeypatch.setattr(agent2, "llm", _llm(RED_NO_CARE, revised="还是多休息吧。"))
    done = [d for e, d in run("rep_u3", "胸口有点疼，上楼时更明显") if e == "repair"][-1]
    assert done["accepted"] is False and done["after"] == done["before"]


def test_repair_failure_never_breaks_the_report(monkeypatch):
    monkeypatch.setattr(agent2, "llm", _llm(RED_NO_CARE, chat_raises=True))
    evs = run("rep_u4", "胸口有点疼，上楼时更明显")
    final = dict(evs)["final"]
    assert "error" not in [e for e, _ in evs] and final["plain"] == RED_NO_CARE
    assert [d for e, d in evs if e == "repair"][-1]["accepted"] is False


def test_empty_rewrite_is_treated_as_no_rewrite(monkeypatch):
    monkeypatch.setattr(agent2, "llm", _llm(RED_NO_CARE, revised="   "))
    assert [d for e, d in run("rep_u5", "胸口有点疼，上楼时更明显") if e == "repair"][-1]["accepted"] is False


def test_overreach_in_the_draft_can_be_repaired(monkeypatch):
    monkeypatch.setattr(agent2, "llm", _llm("你确诊为支气管炎，保证治愈。", revised="可能与支气管炎方向相关，建议到呼吸内科就诊[1]。"))
    evs = run("rep_u6", "咳嗽三天，有点黄痰")
    start = [d for e, d in evs if e == "repair"][0]
    assert "越界表述" in start["reasons"]
    assert dict(evs)["final"]["repair"]["accepted"] is True


def test_clean_report_makes_zero_extra_calls(monkeypatch):
    llm = _llm("建议到呼吸内科就诊，持续加重请及时就医[1]。")
    monkeypatch.setattr(agent2, "llm", llm)
    evs = run("rep_u7", "咳嗽三天，有点黄痰")
    assert llm.calls["chat"] == 1 and "repair" not in [e for e, _ in evs] and "repair" not in dict(evs)["final"]


def test_urgency_and_evidence_problems_are_not_repairable_by_rewriting():
    refl = {"checks": [{"id": "urgency", "status": "fail", "label": "x", "detail": "y"},
                       {"id": "evidence", "status": "warn", "label": "x", "detail": "y"}]}
    import planner
    assert planner.repairable(refl) == []


def test_repair_is_skipped_when_the_model_is_unavailable(monkeypatch):
    """在线路径走到这里说明模型刚刚还在线；但离线路径（规则报告）绝不应尝试调用模型。"""
    monkeypatch.setattr(agent2, "llm", _llm(RED_NO_CARE, available=False))
    evs = run("rep_u8", "胸口有点疼，上楼时更明显")
    assert "repair" not in [e for e, _ in evs] and dict(evs)["final"]["offline"] is True


# ---------------------------------------------------------------- Agent：离线路径的引用是确定性的
def test_offline_report_cites_the_entry_it_actually_used(monkeypatch):
    monkeypatch.setattr(agent2, "llm", _llm("", available=False))
    final = dict(run("off_cite", "咳嗽三天，有点黄痰"))["final"]
    assert final["offline"] and "[1]" in final["plain"]
    ev1 = final["citations"]["evidence"][0]
    assert ev1["n"] == 1 and ev1["cited"] is True
    card = final["data"]
    assert card["dept"]
    top = rag.retrieve("咳嗽三天，有点黄痰", top_k=3)[0]["entry"]
    assert ev1["id"] == top["id"]                       # [1] 就是卡片所依据的那条


def test_offline_report_without_any_kb_hit_has_no_citations(monkeypatch):
    monkeypatch.setattr(agent2, "llm", _llm("", available=False))
    final = dict(run("off_nocite", "asdfgh qwerty"))["final"]
    assert "citations" not in final and "[1]" not in final["plain"]


def test_offline_citation_check_is_listed_in_reflection(monkeypatch):
    monkeypatch.setattr(agent2, "llm", _llm("", available=False))
    final = dict(run("off_refl", "咳嗽三天，有点黄痰"))["final"]
    c = next(x for x in final["reflection"]["checks"] if x["id"] == "citation")
    assert c["status"] == "info" and "引用了 1/" in c["detail"]


def test_symptom_card_kb_hits_now_carry_entry_id_and_sources():
    refs = rag.refs_payload(hits_for("糖尿病视网膜病变 增殖期"))
    assert all(r["id"] for r in refs) and any(r["source_ids"] for r in refs)
