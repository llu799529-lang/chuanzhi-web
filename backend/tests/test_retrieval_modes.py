"""BM25 与检索模式（baseline / rerank / fuse）。

分三层测试：
  1. bm25.py 是纯函数——用手算得出的小例子验证数学（IDF、饱和、长度归一、RRF）；
  2. rag.retrieve 的模式开关——不变量：baseline 不变、rerank 不加候选、fuse 额外候选有上限、未知模式回落、负例保持为空；
  3. 评测脚本与「默认模式由数据决定」的约束。
"""
import json
import math
from pathlib import Path

import pytest

import bm25
import rag

EVALS = Path(__file__).resolve().parent.parent / "evals"


# ---------------------------------------------------------------- bm25 数学
DOCS = [["胸痛", "胸闷", "心悸"], ["胸痛"], ["头晕", "眩晕", "耳石"], ["头晕"] * 3]


def test_idf_is_positive_and_rarer_terms_weigh_more():
    m = bm25.BM25(DOCS)
    assert all(v > 0 for v in m.idf.values())
    assert m.idf["耳石"] > m.idf["胸痛"]                      # 只在 1 篇出现 vs 在 2 篇出现


def test_idf_matches_the_lucene_formula_by_hand():
    m = bm25.BM25(DOCS)
    n, df = 4, 2
    assert m.idf["胸痛"] == pytest.approx(math.log(1 + (n - df + 0.5) / (df + 0.5)))


def test_term_frequency_saturates():
    """同一个词出现 1 次 → 3 次，得分增长有上限（k1 饱和），不会线性爆炸。"""
    m = bm25.BM25([["头晕"], ["头晕"] * 3, ["头晕"] * 30, ["胸痛"]])
    s = m.score(["头晕"])
    assert s[0] < s[1] < s[2] and (s[2] - s[1]) < (s[1] - s[0]) * 3
    assert s[2] < m.idf["头晕"] * (m.k1 + 1) + 1e-9


def test_longer_documents_are_penalized_for_the_same_match():
    m = bm25.BM25([["胸痛"], ["胸痛"] + ["无关"] * 20, ["别的"]])
    s = m.score(["胸痛"])
    assert s[0] > s[1] > 0 and s[2] == 0


def test_query_duplicates_do_not_inflate_the_score():
    m = bm25.BM25(DOCS)
    assert m.score(["胸痛", "胸痛", "胸痛"]) == m.score(["胸痛"])


def test_unknown_terms_and_empty_inputs_score_zero_without_raising():
    m = bm25.BM25(DOCS)
    assert m.score(["不存在"]) == [0.0] * 4 and m.score([]) == [0.0] * 4
    empty = bm25.BM25([])
    assert empty.score(["x"]) == [] and empty.rank(["x"]) == []


def test_rank_is_stable_and_drops_zero_scores():
    m = bm25.BM25([["a"], ["a"], ["b"]])
    assert m.rank(["a"]) == [(0, m.score(["a"])[0]), (1, m.score(["a"])[1])]
    assert [i for i, _ in m.rank(["a"])] == [0, 1]           # 同分按下标，结果稳定可复现


def test_rrf_rewards_agreement_between_rankings():
    fused = bm25.rrf([[1, 2, 3], [1, 3, 2]])
    assert fused[1] == pytest.approx(2 / 61)                       # 两路都排第 1
    assert fused[2] == pytest.approx(1 / 62 + 1 / 63)              # 手算：排第 2 与第 3
    assert fused[3] == pytest.approx(fused[2])                     # 对称，所以相等
    assert fused[1] > fused[2]
    assert bm25.rrf([[1, 2], [2, 1]])[1] == pytest.approx(bm25.rrf([[1, 2], [2, 1]])[2])   # 互相矛盾 → 打平
    assert bm25.rrf([]) == {}


# ---------------------------------------------------------------- 模式不变量
QUERIES = ["咳嗽三天，有点黄痰", "两只手指头发麻，晚上更厉害", "尿完还想尿，还带点烧灼感", "胸口闷痛，有时放射到左肩",
           "最近总头晕，起床时天旋地转", "体重莫名其妙涨了八斤"]


def ids(res):
    return [r["entry"]["id"] for r in res]


@pytest.mark.parametrize("q", QUERIES)
def test_baseline_mode_is_identical_to_the_default(q):
    assert ids(rag.retrieve(q, 3)) == ids(rag.retrieve(q, 3, mode="baseline"))


@pytest.mark.parametrize("q", QUERIES)
def test_rerank_never_adds_candidates_beyond_the_baseline_pool(q):
    pool = set(ids(rag.retrieve(q, 50, mode="baseline")))
    assert set(ids(rag.retrieve(q, 50, mode="rerank"))) == pool          # 同一批候选，只是换了顺序


@pytest.mark.parametrize("q", QUERIES)
def test_fuse_adds_at_most_the_configured_number_of_extra_candidates(q):
    pool = set(ids(rag.retrieve(q, 50, mode="baseline")))
    got = rag.retrieve(q, 50, mode="fuse")
    extra = [r for r in got if r["entry"]["id"] not in pool]
    assert len(extra) <= rag.FUSE_MAX_EXTRA and all(r.get("bm25_only") for r in extra)
    assert pool <= set(ids(got))


@pytest.mark.parametrize("mode", ["", "BM25", "nonsense", None])
def test_unknown_mode_falls_back_to_baseline_instead_of_raising(mode):
    q = QUERIES[0]
    assert ids(rag.retrieve(q, 3, mode=mode)) == ids(rag.retrieve(q, 3, mode="baseline"))


def test_environment_variable_selects_the_mode(monkeypatch):
    q = "两只手指头发麻，晚上更厉害"
    monkeypatch.setenv("RAG_MODE", "rerank")
    assert ids(rag.retrieve(q, 3)) == ids(rag.retrieve(q, 3, mode="rerank"))
    monkeypatch.setenv("RAG_MODE", "garbage")
    assert ids(rag.retrieve(q, 3)) == ids(rag.retrieve(q, 3, mode="baseline"))


@pytest.mark.parametrize("mode", ["baseline", "rerank", "fuse"])
@pytest.mark.parametrize("q", ["今天天气怎么样", "asdfgh qwerty", "你好", "", "   "])
def test_non_medical_input_still_recalls_nothing_in_every_mode(mode, q):
    assert rag.retrieve(q, 3, mode=mode) == []


@pytest.mark.parametrize("mode", ["rerank", "fuse"])
def test_results_keep_the_documented_shape_in_every_mode(mode):
    for r in rag.retrieve("咳嗽三天，有点黄痰", 3, mode=mode):
        assert {"score", "matched", "entry"} <= set(r) and r["entry"]["id"]


def test_rerank_can_improve_the_top_rank_on_a_known_case():
    """评测里 rerank 把「手指发麻」的正确条目从第 2 提到第 1；锁住这个已知行为，防止悄悄退化。"""
    base = ids(rag.retrieve("两只手指头发麻，晚上更厉害", 3, mode="baseline"))
    rer = ids(rag.retrieve("两只手指头发麻，晚上更厉害", 3, mode="rerank"))
    assert rer.index("K84") < base.index("K84")


def test_bm25_index_covers_every_entry_and_whole_term_tokens_are_used():
    rag._load()
    assert rag._INDEX.ensure(rag._ENTRIES).n == len(rag._ENTRIES)
    toks = rag._INDEX.query_tokens(rag._ENTRIES, "我最近胸闷还有心悸")
    assert "胸闷" in toks and "心悸" in toks          # 整词 token 只在查询里真的出现时才加


def test_bm25_tokens_drop_function_bigrams_and_cross_punctuation_fragments():
    toks = rag._INDEX.tokens("腰闪了一下，说话含糊")
    assert "一下" not in toks and "下说" not in toks and "含糊" in toks


# ---------------------------------------------------------------- 评测与「默认由数据决定」
def test_heldout_set_v2_declares_it_was_written_before_running_and_must_not_be_tuned_on():
    v2 = json.loads((EVALS / "blind_queries_v2.json").read_text(encoding="utf-8"))
    assert "运行任何检索之前" in v2["_meta"] and "不得" in v2["_meta"]
    assert len(v2["queries"]) >= 60 and len(v2["negatives"]["queries"]) >= 10
    assert all(q["query"] and q["expect"] for q in v2["queries"])


def test_heldout_queries_do_not_duplicate_the_older_evaluation_sets():
    v2 = {q["query"] for q in json.loads((EVALS / "blind_queries_v2.json").read_text(encoding="utf-8"))["queries"]}
    old = {it["query"] for b in json.loads((EVALS / "blind_queries.json").read_text(encoding="utf-8"))["batches"] for it in b["queries"]}
    old |= {q["query"] for q in json.loads((EVALS / "golden_queries.json").read_text(encoding="utf-8"))["queries"]}
    assert not (v2 & old)


def test_default_mode_is_baseline_unless_the_committed_report_adopted_another():
    """默认模式必须由评测数据决定：要切到 rerank/fuse，先让 run_retrieval_compare.py 的 verdict 判为可采用。"""
    rep = json.loads((EVALS / "retrieval_compare.json").read_text(encoding="utf-8"))
    mode = rag.RAG_MODE_DEFAULT
    assert mode == "baseline" or rep["verdict"][mode]["adopt"] is True


def test_comparison_script_runs_offline_and_is_consistent_with_the_committed_report():
    import importlib.util
    spec = importlib.util.spec_from_file_location("run_retrieval_compare", EVALS / "run_retrieval_compare.py")
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.path.insert(0, str(EVALS))
    spec.loader.exec_module(mod)
    fresh = mod.run()
    committed = json.loads((EVALS / "retrieval_compare.json").read_text(encoding="utf-8"))
    assert fresh["modes"] == committed["modes"], "检索逻辑或知识库变了：请重新运行 python evals/run_retrieval_compare.py 并更新报告"
    for k in ("golden", "blind_v1", "blind_v2"):
        assert fresh["modes"]["baseline"][k]["n"] == committed["modes"]["baseline"][k]["n"]


def test_adoption_rule_is_conservative():
    """采用判据是运行前写好的：留出集不能退步、回归集不能下降、不能新增误召回。"""
    import importlib.util
    import inspect
    spec = importlib.util.spec_from_file_location("run_retrieval_compare2", EVALS / "run_retrieval_compare.py")
    mod = importlib.util.module_from_spec(spec)
    import sys
    sys.path.insert(0, str(EVALS))
    spec.loader.exec_module(mod)
    src = inspect.getsource(mod.run)
    for clause in ('v2_hit3_delta"] >= 0', 'v2_mrr_delta"] > 0', 'extra_false_recalls"] <= 0', 'regression_hit3_delta"] >= 0'):
        assert clause in src



def test_bm25_index_is_rebuilt_when_the_entry_list_is_replaced(monkeypatch):
    """回归：别的测试把 rag._ENTRIES 换成重新加载的另一批对象后，旧索引的下标会悄悄指向错误条目。"""
    rag._load()
    first = rag._INDEX.ensure(rag._ENTRIES)
    clones = [dict(e) for e in rag._ENTRIES]              # 内容相同、对象不同
    monkeypatch.setattr(rag, "_ENTRIES", clones)
    second = rag._INDEX.ensure(rag._ENTRIES)
    assert second is not first and rag._INDEX.owner == tuple(id(e) for e in clones)
    assert ids(rag.retrieve("两只手指头发麻，晚上更厉害", 3, mode="rerank"))[0] == "K84"


def test_rerank_stays_correct_after_the_entry_list_is_reloaded(monkeypatch):
    rag._load()
    monkeypatch.setattr(rag, "_ENTRIES", [])
    rag._load()                                           # 与 test_eval_hardening 的夹具做法一致
    got = rag.retrieve("两只手指头发麻，晚上更厉害", 3, mode="rerank")
    assert got and got[0]["entry"] is rag._ENTRIES[[e["id"] for e in rag._ENTRIES].index(got[0]["entry"]["id"])]



# ---- EntryIndex 脱离 rag 独立可测（分词规则由调用方注入）
def _tiny_index():
    import re
    ents = [{"id": "A", "category": "胸痛", "dept": "心内科", "keywords": ["胸痛", "胸闷"], "diseases": [{"name": "心绞痛"}]},
            {"id": "B", "category": "头晕", "dept": "神经内科", "keywords": ["头晕", "眩晕"], "diseases": [{"name": "耳石症"}]},
            {"id": "C", "category": "咳嗽", "dept": "呼吸内科", "keywords": ["咳嗽"], "diseases": []}]
    return bm25.EntryIndex(re.compile(r"[，。\s]+"), {"一下"}), ents


def test_entry_index_ranks_the_matching_entry_first_without_touching_rag():
    idx, ents = _tiny_index()
    ranked = idx.ensure(ents).rank(idx.query_tokens(ents, "我胸闷，还有点胸痛"))
    assert ranked and ranked[0][0] == 0


def test_entry_index_apply_is_a_noop_for_baseline_and_empty_inputs():
    idx, ents = _tiny_index()
    res = [{"entry": ents[1], "score": 5, "matched": []}]
    assert idx.apply(res, ents, "头晕", "baseline") is res
    assert idx.apply([], ents, "头晕", "rerank") == [] and idx.apply(res, [], "头晕", "rerank") is res


def test_entry_index_rerank_keeps_baseline_order_when_the_evidence_is_a_tie():
    """B：baseline 第 1、BM25 无命中；A：baseline 第 2、BM25 第 1。两路各给一个第 1 和一个第 2 → RRF 平局 → 保持 baseline。
    即「证据只有 1:1 时不推翻 baseline」——重排是保守的。"""
    idx, ents = _tiny_index()
    res = [{"entry": ents[1], "score": 9, "matched": []}, {"entry": ents[0], "score": 8, "matched": []}]
    out = idx.apply(res, ents, "胸闷胸痛", "rerank")
    assert [r["entry"]["id"] for r in out] == ["B", "A"]


def test_entry_index_rerank_promotes_an_entry_that_bm25_clearly_prefers():
    """baseline 把 A 排在最后（第 3），BM25 把它排第 1：两路 (3→1) 对 (1,2) 的总分，A 超过 C 与 B 中 BM25 没命中的那条。"""
    idx, ents = _tiny_index()
    res = [{"entry": ents[2], "score": 9, "matched": []}, {"entry": ents[1], "score": 8, "matched": []},
           {"entry": ents[0], "score": 7, "matched": []}]
    out = [r["entry"]["id"] for r in idx.apply(res, ents, "胸闷胸痛", "rerank")]
    assert out.index("A") < out.index("B") and set(out) == {"A", "B", "C"}
