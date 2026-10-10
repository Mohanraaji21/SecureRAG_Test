"""
LLM adjudication engine (report section 4.2.3).

Calls a locally hosted, open-weight LLM via Ollama's HTTP API -- following
SecureFixAgent's on-device deployment model for privacy and reproducibility
-- and parses its structured JSON response into the Appendix A.2 schema.

Malformed/unparseable LLM output, timeouts, or connection failures never
raise out of `adjudicate()`: they return a `needs_review` verdict with
`fail_open=True` (section 4.6's fail-open safety design), so infrastructure
failure never silently suppresses a real finding.
"""

from __future__ import annotations

import json
import re

import httpx

from core.adjudication.prompts import build_adjudication_prompt
from core.schemas.models import (
    CitedEvidence,
    Finding,
    RetrievedEvidence,
    Verdict,
    VerdictLabel,
)

DEFAULT_OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen2.5-coder:7b"

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


class OllamaClient:
    def __init__(
        self,
        base_url: str = DEFAULT_OLLAMA_URL,
        model: str = DEFAULT_MODEL,
        timeout_seconds: float = 60.0,
    ):
        self.base_url = base_url
        self.model = model
        self.timeout_seconds = timeout_seconds

    def _call_model(self, prompt: str) -> str:
        """Raises httpx exceptions on network failure -- caught by the
        caller (`adjudicate`) to implement fail-open behaviour."""
        response = httpx.post(
            self.base_url,
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
                "options": {"temperature": 0.1},
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        data = response.json()
        return data.get("response", "")

    def adjudicate(
        self,
        finding: Finding,
        evidence: list[RetrievedEvidence],
        evidence_texts: dict[str, str],
    ) -> Verdict:
        prompt = build_adjudication_prompt(finding, evidence, evidence_texts)

        try:
            raw_text = self._call_model(prompt)
        except (httpx.HTTPError, httpx.TimeoutException) as exc:
            return _fail_open_verdict(
                finding, reason=f"LLM call failed: {exc}", model=self.model
            )

        parsed = _parse_llm_json(raw_text)
        if parsed is None:
            return _fail_open_verdict(
                finding,
                reason="LLM returned unparseable/malformed JSON output",
                model=self.model,
            )

        try:
            verdict_label = VerdictLabel(parsed.get("verdict", "needs_review"))
        except ValueError:
            verdict_label = VerdictLabel.NEEDS_REVIEW

        raw_confidence = parsed.get("raw_confidence", 0.5)
        try:
            raw_confidence = float(raw_confidence)
        except (TypeError, ValueError):
            raw_confidence = 0.5
        raw_confidence = min(max(raw_confidence, 0.0), 1.0)

        cited_id = parsed.get("cited_evidence_id") or ""
        cited_evidence = []
        if cited_id:
            matching = next((e for e in evidence if e.knowledge_item_id == cited_id), None)
            if matching:
                cited_evidence.append(CitedEvidence(source=matching.source, id=cited_id))

        return Verdict(
            finding_id=finding.finding_id,
            cwe_id=finding.cwe_id,
            verdict=verdict_label,
            raw_confidence=raw_confidence,
            justification=parsed.get("justification", ""),
            cited_evidence=cited_evidence,
            model_used=self.model,
            fail_open=False,
        )


def _parse_llm_json(raw_text: str) -> dict | None:
    """LLMs occasionally wrap JSON in markdown fences or prose despite
    instructions; try a strict parse first, then extract the first
    top-level {...} block as a fallback."""
    raw_text = raw_text.strip()
    try:
        return json.loads(raw_text)
    except json.JSONDecodeError:
        pass

    match = _JSON_OBJECT_RE.search(raw_text)
    if match:
        try:
            return json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _fail_open_verdict(finding: Finding, reason: str, model: str) -> Verdict:
    """Section 4.6 fail-open design: retain the finding as needs_review
    rather than silently dropping it, with a low confidence and a
    justification that explains *why* it wasn't adjudicated."""
    return Verdict(
        finding_id=finding.finding_id,
        cwe_id=finding.cwe_id,
        verdict=VerdictLabel.NEEDS_REVIEW,
        raw_confidence=0.0,
        justification=f"Fail-open fallback: {reason}. Routed to manual review.",
        cited_evidence=[],
        model_used=model,
        fail_open=True,
    )
