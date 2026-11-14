"""Offline regression tests for model-output normalization and evidence retention."""
import json

import pytest

import ai_analysis
import guardrails


@pytest.fixture()
def kb_hits(monkeypatch):
    hits = [{
        "score": 20.0,
        "matched": ["fixture symptom"],
        "entry": {
            "id": "fixture-entry",
            "category": "fixture category",
            "dept": "fixture department",
            "urgency": "yellow",
            "diseases": [{"name": "fixture direction", "feature": "fixture feature"}],
            "tests": ["fixture test"],
            "reds": ["fixture warning"],
        },
    }]
    monkeypatch.setattr(ai_analysis.rag, "retrieve", lambda *args, **kwargs: hits)
    monkeypatch.setattr(guardrails, "log_event", lambda *args, **kwargs: None)
    return hits


def _valid_symptom():
    return {
        "hits": ["fixture symptom"],
        "echo": "fixture echo",
        "dept": "fixture department",
        "urg": "黄色 · fixture urgency",
        "alt": "fixture alternative",
        "suspects": [["fixture direction", 35, "fixture support"]],
        "tests": ["fixture test"],
        "prep": ["fixture preparation"],
        "reds": ["fixture warning"],
    }


@pytest.mark.parametrize("payload", [
    [],
    None,
    {**_valid_symptom(), "suspects": 5},
    {**_valid_symptom(), "hits": 4},
    {**_valid_symptom(), "tests": "not a list"},
    {**_valid_symptom(), "prep": {}},
    {**_valid_symptom(), "reds": [{"unexpected": "object"}]},
    {**_valid_symptom(), "dept": []},
    {**_valid_symptom(), "suspects": [["fixture direction", float("nan"), ""]]},
    {**_valid_symptom(), "suspects": [{"name": "fixture direction", "pct": float("inf")}]},
    {**_valid_symptom(), "suspects": [["fixture direction", "unknown", ""]]},
])
def test_invalid_symptom_output_degrades_with_retrieved_evidence(monkeypatch, kb_hits, payload):
    monkeypatch.setattr(ai_analysis.llm, "chat_json", lambda *args, **kwargs: payload)

    result = ai_analysis.analyze_symptom("fixture query", "fixture user")

    assert result["degraded"] is True
    assert result["dept"] == kb_hits[0]["entry"]["dept"]
    assert result["tests"] == ["fixture test"]
    assert result["reds"] == ["fixture warning"]
    assert result["kb_hits"] == ai_analysis.rag.refs_payload(kb_hits)
    json.dumps(result, allow_nan=False)


def test_model_error_retains_retrieved_references(monkeypatch, kb_hits):
    def unavailable(*args, **kwargs):
        raise TimeoutError("offline fixture")

    monkeypatch.setattr(ai_analysis.llm, "chat_json", unavailable)

    result = ai_analysis.analyze_symptom("fixture query")

    assert result["degraded"] is True
    assert result["kb_hits"] == ai_analysis.rag.refs_payload(kb_hits)
    json.dumps(result, allow_nan=False)


def test_valid_symptom_output_preserves_existing_contract(monkeypatch, kb_hits):
    payload = _valid_symptom()
    monkeypatch.setattr(ai_analysis.llm, "chat_json", lambda *args, **kwargs: payload)

    result = ai_analysis.analyze_symptom("fixture query", "fixture user")

    assert result["degraded"] is False
    assert result["kind"] == "symptom"
    assert result["urgency"] == "yellow"
    for key, value in payload.items():
        assert result[key] == value
    assert result["kb_hits"] == ai_analysis.rag.refs_payload(kb_hits)
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("raw, expected", [(0, 0.0), (12.3, 12.3), (63.2, 63.2), (98.1, 98.1)])
def test_lab_confidence_is_not_inflated_by_report_completeness(raw, expected):
    result = ai_analysis._norm_lab({
        "confidence": raw,
        "patient": {"gender": "男", "age": 40},
        "sampled_at": "fixture sampled time",
        "reported_at": "fixture reported time",
        "items": [{"name": "fixture item", "value": "1", "flag": "normal"}],
    })

    assert result["confidence"] == expected


@pytest.mark.parametrize("raw", [None, "unknown", float("nan"), float("inf"), float("-inf"), True])
def test_unusable_lab_confidence_is_unknown(raw):
    result = ai_analysis._norm_lab({"confidence": raw})

    assert result["confidence"] is None
    json.dumps(result, allow_nan=False)


def test_missing_lab_confidence_is_unknown():
    assert ai_analysis._norm_lab({})["confidence"] is None


@pytest.mark.parametrize("reported", [99, -1, "invalid", float("nan"), float("inf")])
def test_lab_abnormal_count_is_derived_from_returned_items(reported):
    result = ai_analysis._norm_lab({
        "abnormal_count": reported,
        "items": [
            {"name": "fixture high", "flag": "high"},
            {"name": "fixture low", "flag": "low"},
            {"name": "fixture normal", "flag": "normal"},
            {"name": "fixture invalid flag", "flag": "unexpected"},
            {"flag": "high"},
        ],
    })

    assert result["abnormal_count"] == 2
    assert len(result["items"]) == 4
    json.dumps(result, allow_nan=False)


def test_empty_lab_report_cannot_have_abnormal_items():
    result = ai_analysis._norm_lab({"items": [], "abnormal_count": 99})

    assert result["abnormal_count"] == 0


def test_lab_abnormal_count_counts_only_visible_normalized_items():
    result = ai_analysis._norm_lab({
        "items": [{"name": f"fixture {i}", "flag": "high"} for i in range(15)],
        "abnormal_count": 15,
    })

    assert result["abnormal_count"] == len(result["items"]) == 12
