"""Offline evaluator contracts; all generated reports and fixture data live in tmp."""
import hashlib
import json
from pathlib import Path

import pytest

import rag
from evals import run_blind


class LocalEmbedding:
    def embed(self, documents):
        return iter([[1.0, 0.0] for _ in documents])


@pytest.fixture
def evaluation(monkeypatch, tmp_path):
    data = {
        "_doc": ["历史独立盲测集声明"],
        "metric": "recall@3",
        "batches": [{"batch": "A", "round": 1, "contaminated": True,
                     "queries": [{"query": "头晕", "expect": ["头晕"]}]}],
    }
    dataset = tmp_path / "queries.json"
    dataset.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    kb = tmp_path / "knowledge_base.json"
    kb.write_text(json.dumps({"entries": [{"category": "头晕", "keywords": ["头晕"]}]}), encoding="utf-8")
    monkeypatch.setattr(run_blind, "BLIND_PATH", str(dataset))
    monkeypatch.setattr(run_blind, "OUT_PATH", str(tmp_path / "report.json"))
    monkeypatch.setattr(rag, "_KB_PATH", kb)
    monkeypatch.setattr(rag, "_ENTRIES", [])
    monkeypatch.setattr(rag, "_VEC_OK", None)
    monkeypatch.setattr(rag, "_VEC_MODEL", None)
    monkeypatch.setattr(rag, "_VEC_INDEX", [])
    monkeypatch.setattr(rag, "_RAW_TEXT_CACHE", {})
    monkeypatch.setenv("RAG_VECTOR", "0")
    return dataset, kb


def enable_local_vectors(monkeypatch):
    # Populate lexical features without importing or downloading any vector model.
    rag._load()
    monkeypatch.setenv("RAG_VECTOR", "1")
    monkeypatch.setattr(rag, "_VEC_OK", True)
    monkeypatch.setattr(rag, "_VEC_MODEL", LocalEmbedding())
    monkeypatch.setattr(rag, "_VEC_INDEX", [(entry, [1.0, 0.0]) for entry in rag._ENTRIES])


def test_disabled_vectors_do_not_claim_a_valid_ablation(evaluation, capsys):
    report = run_blind.run()

    assert report["ablation"]["valid"] is False
    assert report["summary"]["vec_delta"] is None
    assert report["batches"][0]["vec_delta"] is None
    vector = report["ablation"]["vector"]["before"]
    assert vector["requested"] is False
    assert vector["runtime_enabled"] is False
    assert vector["index_valid"] is False
    assert report["summary"]["full"]["recall_at_3"] == 1.0
    output = capsys.readouterr().out
    assert "消融无效" in output
    assert "N/A" in output


def test_metrics_use_first_relevant_rank_and_weight_summary(monkeypatch, evaluation):
    dataset, _ = evaluation
    data = json.loads(dataset.read_text(encoding="utf-8"))
    data["batches"] = [
        {"batch": "A", "round": 1, "queries": [{"query": "q1", "expect": ["目标"]}]},
        {"batch": "B", "round": 2, "queries": [
            {"query": query, "expect": ["目标"]} for query in ("q2", "q3", "q4")
        ]},
    ]
    dataset.write_text(json.dumps(data), encoding="utf-8")
    rankings = {"q1": ["目标", "目标"], "q2": ["其他", "目标"],
                "q3": ["其他", "无关", "目标"], "q4": []}
    monkeypatch.setattr(rag, "retrieve", lambda query, top_k: [
        {"entry": {"category": category}} for category in rankings[query]
    ])

    report = run_blind.run()

    summary = report["summary"]["full"]
    assert summary["hit_at_1"] == 0.25
    assert summary["mrr_at_3"] == 0.458
    assert summary["recall_at_3"] == 0.75
    rows = [row for batch in report["batches"] for row in batch["full"]["rows"]]
    assert [row["rank"] for row in rows] == [1, 2, 3, None]
    assert [row["hit"] for row in rows] == [True, True, True, False]
    assert report["batches"][1]["full"]["mrr_at_3"] == 0.278


def test_report_marks_regression_and_fingerprints_unchanged_inputs(evaluation):
    dataset, kb = evaluation
    before = {path: path.read_bytes() for path in (dataset, kb)}

    report = run_blind.run()

    assert report["evaluation"]["purpose"] == "regression"
    assert report["evaluation"]["independent_holdout"] is False
    assert "调优" in report["evaluation"]["reason"]
    assert report["batches"][0]["contaminated"] is True
    assert report["provenance"]["dataset_sha256"] == hashlib.sha256(before[dataset]).hexdigest()
    assert report["provenance"]["kb_sha256"] == hashlib.sha256(before[kb]).hexdigest()
    for name, path in {"rag.py": rag.__file__, "run_blind.py": run_blind.__file__}.items():
        assert report["provenance"]["code_sha256"][name] == hashlib.sha256(Path(path).read_bytes()).hexdigest()
    assert all(path.read_bytes() == content for path, content in before.items())
    assert json.loads(Path(run_blind.OUT_PATH).read_text(encoding="utf-8")) == report


def test_effective_vectors_allow_numeric_delta_and_restore_model(monkeypatch, evaluation):
    enable_local_vectors(monkeypatch)
    original_model = rag._VEC_MODEL

    report = run_blind.run()

    assert report["ablation"]["valid"] is True
    assert report["ablation"]["queries_succeeded"] == 1
    assert report["ablation"]["vector"]["before"]["index_valid"] is True
    assert report["summary"]["vec_delta"] == 0.0
    assert rag._VEC_OK is True
    assert rag._VEC_MODEL is original_model


@pytest.mark.parametrize("failure", ["unavailable", "missing_index", "partial_index", "nan_index", "query_error", "query_dimension"])
def test_failed_vector_channel_invalidates_ablation(monkeypatch, evaluation, failure):
    enable_local_vectors(monkeypatch)
    if failure == "unavailable":
        monkeypatch.setattr(rag, "_VEC_OK", False)
    elif failure == "missing_index":
        monkeypatch.setattr(rag, "_VEC_INDEX", [])
    elif failure == "partial_index":
        monkeypatch.setattr(rag, "_VEC_INDEX", rag._VEC_INDEX * 2)
    elif failure == "nan_index":
        monkeypatch.setattr(rag, "_VEC_INDEX", [(rag._ENTRIES[0], [float("nan"), 0.0])])
    else:
        class BrokenEmbedding:
            def embed(self, documents):
                if failure == "query_dimension":
                    yield [1.0]
                else:
                    raise RuntimeError("offline embedding failure")
        monkeypatch.setattr(rag, "_VEC_MODEL", BrokenEmbedding())
    original_model = rag._VEC_MODEL

    report = run_blind.run()

    assert report["ablation"]["valid"] is False
    assert report["ablation"]["reasons"]
    assert report["summary"]["vec_delta"] is None
    assert rag._VEC_MODEL is original_model
    if failure.startswith("query_"):
        assert report["ablation"]["queries_failed"] == 1


def test_empty_selection_is_not_valid_ablation(evaluation):
    report = run_blind.run(only_batch="missing")

    assert report["ablation"]["valid"] is False
    assert report["summary"]["vec_delta"] is None
    assert report["summary"]["full"]["hit_at_1"] == 0.0
    assert report["summary"]["full"]["mrr_at_3"] == 0.0


def test_no_vec_context_restores_flag_on_failure(monkeypatch):
    monkeypatch.setattr(rag, "_VEC_OK", True)

    def fail():
        assert rag._VEC_OK is False
        raise RuntimeError("evaluation failed")

    with pytest.raises(RuntimeError, match="evaluation failed"):
        run_blind._with_vec_disabled(fail)
    assert rag._VEC_OK is True
