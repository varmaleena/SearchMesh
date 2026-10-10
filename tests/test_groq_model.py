import pytest
from unittest.mock import patch
from searchmesh import groq_model


def test_planner_validates_queries_and_preserves_task():
    with patch.object(groq_model,"complete",return_value='{"queries":["one","two","three"]}') as call:
        assert groq_model.plan("Bengaluru workshops",["price","location","reviews"])==["one","two","three"]
        assert "Bengaluru workshops" in call.call_args.args[0][1]["content"]
    with patch.object(groq_model,"complete",return_value='{"queries":["one"]}'):
        with pytest.raises(ValueError):groq_model.plan("task",["a","b","c"])


def test_synthesis_passes_evidence_ids_and_urls():
    evidence=[{"response_id":"response-1","sources":[{"title":"Official","url":"https://example.com/source","snippet":"Evidence text"}]}]
    with patch.object(groq_model,"complete",return_value="Answer") as call:
        assert groq_model.synthesize("task",evidence)=="Answer"
        payload=call.call_args.args[0][1]["content"]
        assert "response-1" in payload and "https://example.com/source" in payload


def test_automatic_planner_retries_invalid_structure_once():
    with patch.object(groq_model, "_automatic_plan_once", side_effect=[ValueError("invalid"), {"tasks": []}]) as call:
        assert groq_model.automatic_plan("question") == {"tasks": []}
        assert call.call_count == 2
    with patch.object(groq_model, "_automatic_plan_once", side_effect=ValueError("invalid")) as call:
        with pytest.raises(ValueError, match="after two attempts"):
            groq_model.automatic_plan("question")
        assert call.call_count == 2


def test_public_error_does_not_expose_arbitrary_exception_text():
    assert "private-value" not in groq_model.public_error(RuntimeError("private-value"))
    assert "HTTP 429" in groq_model.public_error(RuntimeError("Groq request failed (HTTP 429)"))
