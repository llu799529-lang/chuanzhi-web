"""知识库「参考依据」：登记表质量、与知识库同步、展示串、以及人工核实时发现的错误不得复发。

这些测试不联网：它们检查的是登记表**本身的内部一致性与诚实度**（证据数量、置信度、无占位文字、不写 medium），
而不是文献是否真实存在——后者需要联网，已在核实时完成，证据链接都在 kb_sources.json 里，可随时复核。
"""
import copy
import importlib.util
import json
from pathlib import Path

import rag

BACKEND = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("build_kb_sources", BACKEND / "evals" / "build_kb_sources.py")
bks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(bks)

REG = json.loads((BACKEND / "kb_sources.json").read_text(encoding="utf-8"))
KB = json.loads((BACKEND / "knowledge_base.json").read_text(encoding="utf-8"))
ENTRY = {e["id"]: e for e in KB["entries"]}


def test_registry_is_internally_valid():
    assert bks.validate(REG, KB) == []


def test_knowledge_base_is_in_sync_with_registry():
    """手改了知识库的 source 字段、或改了登记表没重新生成，这里会红。修复：python evals/build_kb_sources.py"""
    assert bks.check_sync(REG, KB) == []


def test_apply_is_idempotent():
    once = bks.apply(REG, copy.deepcopy(KB))
    twice = bks.apply(REG, copy.deepcopy(once))
    assert once == twice


def test_every_high_source_has_at_least_two_distinct_evidence_links():
    for sid, s in REG["sources"].items():
        if s["confidence"] == "high":
            assert len(set(s["evidence"])) >= 2, sid
            assert all(u.startswith("http") for u in s["evidence"]), sid


def test_medium_sources_are_registered_but_never_written_to_the_kb():
    mediums = {sid for sid, s in REG["sources"].items() if s["confidence"] != "high"}
    assert mediums, "目前应当还有待二次核实的 medium 来源（没有的话，请更新这条测试）"
    written = {i for e in KB["entries"] for i in e.get("source_ids", [])}
    assert not (mediums & written)


def test_source_strings_have_no_placeholder_or_hedging_text():
    banned = ("检索结果", "未确认", "待核对", "待核实", "以原文为准", "未核实")
    for e in KB["entries"]:
        for text in e.get("source", []):
            assert not any(b in text for b in banned), (e["id"], text)
            assert text.startswith("《") or text[:1].isascii(), (e["id"], text)


def test_sources_and_ids_are_parallel_lists_and_ids_exist():
    for e in KB["entries"]:
        assert len(e.get("source", [])) == len(e.get("source_ids", [])), e["id"]
        for sid in e.get("source_ids", []):
            assert sid in REG["sources"] and REG["sources"][sid]["confidence"] == "high"


def test_coverage_is_reported_honestly_and_blank_entries_stay_blank():
    st = bks.stats(REG, KB)
    assert st["with_source"] + st["without_source"] == st["total"] == len(KB["entries"])
    assert st["with_source"] >= 85                       # 当前 94；明显下降说明有人撤掉了出处
    for kid in st["without_ids"]:
        assert not ENTRY[kid].get("source") and not ENTRY[kid].get("source_ids"), kid
    assert str(st["with_source"]) in KB["source_note"] and str(st["without_source"]) in KB["source_note"]


def test_source_note_states_the_limits():
    note = KB["source_note"]
    for phrase in ("主题级", "并非逐条核对", "未经临床医生评审", "不编造出处"):
        assert phrase in note, phrase


def test_each_source_with_limited_scope_keeps_its_scope_text():
    """只覆盖条目一部分疾病的来源，登记表里必须写明范围，不能悄悄当作全覆盖。"""
    for sid in ("lymphoma_nhc_2022", "cua_cn_2022", "tmd_splint_2025", "migraine_cn_2022", "hyperk_cn", "dm_neuropathy_cn_2021"):
        s = REG["sources"][sid]
        assert s.get("scope") or s.get("note"), sid


# ---- 人工核实时发现并纠正的错误，不得复发 ----
def test_stroke_entry_cites_the_2023_acute_ischemic_stroke_guideline():
    titles = " ".join(ENTRY["K24"]["source"])
    assert "急性缺血性卒中诊治指南2023" in titles and "脑卒中诊治指南" not in titles


def test_diabetes_entries_cite_the_2024_guideline_without_the_old_type2_name():
    for kid in ("K19", "K29"):
        assert any("中国糖尿病防治指南（2024版）" in s for s in ENTRY[kid]["source"]), kid
        assert not any("中国2型糖尿病防治指南" in s for s in ENTRY[kid]["source"]), kid


def test_chest_pain_consensus_is_attributed_to_the_right_society():
    s = REG["sources"]["chestpain_cn_2019"]
    assert "中华医学会急诊医学分会" in s["issuer"] and "中国医师协会" not in s["issuer"]
    assert "中华急诊医学杂志" in s["citation"]


def test_hemoptysis_consensus_is_not_attributed_to_the_cma_respiratory_society():
    s = REG["sources"]["hemoptysis_bj_2020"]
    assert "北京医师协会" in s["issuer"] and "中华医学会" not in s["issuer"]


def test_androgenetic_alopecia_citation_is_the_clinical_dermatology_journal():
    s = REG["sources"]["aga_cma_derm"]
    assert "临床皮肤科杂志" in s["citation"] and "中华皮肤科杂志" not in s["citation"]


def test_facial_palsy_source_is_the_2016_guideline_not_the_2022_nerve_repair_one():
    s = REG["sources"]["facial_palsy_cn_2016"]
    assert s["year"] == 2016 and "神经修复" not in s["title"]


def test_hematuria_has_no_source_because_the_cua_book_has_no_hematuria_chapter():
    assert "cua_cn_2022" not in REG["map"].get("K78", [])
    assert not ENTRY["K78"].get("source")
    assert "没有独立的“血尿”章节" in REG["sources"]["cua_cn_2022"]["scope"]


def test_entries_whose_only_candidates_were_single_site_or_blog_stay_blank():
    for kid in ("K34", "K96", "K100", "K67"):
        assert not ENTRY[kid].get("source"), kid


def test_superseded_flu_plan_is_not_used():
    assert "flu_nhc_2020" not in REG["map"].get("K08", [])
    assert "flu_nhc_2025" in ENTRY["K08"]["source_ids"]


# ---- display() ----
def test_display_omits_unknown_issuer_and_year():
    assert bks.display({"title": "某指南", "issuer": "（署名未确认）", "year": None}) == "《某指南》"
    assert bks.display({"title": "某指南", "issuer": "某学会", "year": 2022}) == "《某指南》（某学会；2022）"
    assert bks.display({"title": "Some Guideline", "issuer": "AAO", "year": 2012}) == "Some Guideline（AAO；2012）"


def test_validate_catches_the_mistakes_it_exists_to_catch():
    bad = copy.deepcopy(REG)
    bad["sources"]["dr_cn_2022"]["evidence"] = ["https://only-one.example"]
    bad["sources"]["icdr_2003"]["evidence"] = ["not a url", "https://ok.example"]
    bad["map"]["K01"].append("does_not_exist")
    bad["map"]["K999"] = ["dr_cn_2022"]
    errs = " | ".join(bks.validate(bad, KB))
    assert "dr_cn_2022" in errs and "至少需要 2" in errs
    assert "不是有效 URL" in errs and "未登记的来源" in errs and "不存在的知识库条目" in errs


def test_check_sync_catches_a_hand_edit():
    tampered = copy.deepcopy(KB)
    tampered["entries"][0]["source"] = ["《凭记忆写的指南》（某学会；2020）"]
    assert any("不同步" in e for e in bks.check_sync(REG, tampered))


# ---- 接入检索：出处进入提示词与前端载荷 ----
def test_sources_reach_prompt_context_and_frontend_payload():
    hits = rag.retrieve("糖尿病视网膜病变 增殖期", top_k=3)
    assert hits and any(h["entry"].get("source") for h in hits)
    ctx = rag.format_context(hits)
    assert "参考依据：" in ctx and "糖尿病视网膜病变" in ctx
    payload = rag.refs_payload(hits)
    assert all("source" in r for r in payload) and any(r["source"] for r in payload)


def test_entries_without_sources_do_not_print_an_empty_reference_line():
    hit = {"entry": {"category": "测试", "dept": "全科", "diseases": [], "tests": [], "reds": []}, "matched": ["x"]}
    assert "参考依据" not in rag.format_context([hit])
