import httpx
import pytest

from core.adjudication.ollama_client import OllamaClient, _parse_llm_json
from core.schemas.models import Finding, VerdictLabel

FINDING = Finding(
    rule_id="test-rule",
    cwe_id="CWE-89",
    file_path="app.py",
    line=10,
    message="Possible SQL injection",
    code_snippet='query = "SELECT * FROM t WHERE id=" + x',
)


def test_parse_llm_json_clean():
    raw = '{"verdict": "true_positive", "raw_confidence": 0.9, "justification": "x", "cited_evidence_id": "abc"}'
    parsed = _parse_llm_json(raw)
    assert parsed["verdict"] == "true_positive"


def test_parse_llm_json_wrapped_in_prose():
    raw = 'Here is my answer:\n{"verdict": "false_positive", "raw_confidence": 0.3, "justification": "y", "cited_evidence_id": ""}\nHope that helps!'
    parsed = _parse_llm_json(raw)
    assert parsed["verdict"] == "false_positive"


def test_parse_llm_json_garbage_returns_none():
    assert _parse_llm_json("not json at all") is None


def test_adjudicate_happy_path(monkeypatch):
    client = OllamaClient()

    def fake_call(self, prompt):
        return '{"verdict": "true_positive", "raw_confidence": 0.85, "justification": "matches known SQLi pattern", "cited_evidence_id": "kb-1"}'

    monkeypatch.setattr(OllamaClient, "_call_model", fake_call)

    from core.schemas.models import RetrievedEvidence

    evidence = [RetrievedEvidence(source="CWE-89 SQL Injection", knowledge_item_id="kb-1", similarity_score=0.9)]
    verdict = client.adjudicate(FINDING, evidence, {"kb-1": "SQL injection knowledge text"})

    assert verdict.verdict == VerdictLabel.TRUE_POSITIVE
    assert verdict.raw_confidence == 0.85
    assert verdict.fail_open is False
    assert len(verdict.cited_evidence) == 1


def test_adjudicate_fails_open_on_connection_error(monkeypatch):
    client = OllamaClient()

    def fake_call(self, prompt):
        raise httpx.ConnectError("connection refused", request=httpx.Request("POST", "http://x"))

    monkeypatch.setattr(OllamaClient, "_call_model", fake_call)

    verdict = client.adjudicate(FINDING, [], {})
    assert verdict.verdict == VerdictLabel.NEEDS_REVIEW
    assert verdict.fail_open is True
    assert verdict.raw_confidence == 0.0


def test_adjudicate_fails_open_on_malformed_json(monkeypatch):
    client = OllamaClient()

    def fake_call(self, prompt):
        return "I refuse to output JSON today."

    monkeypatch.setattr(OllamaClient, "_call_model", fake_call)

    verdict = client.adjudicate(FINDING, [], {})
    assert verdict.verdict == VerdictLabel.NEEDS_REVIEW
    assert verdict.fail_open is True
