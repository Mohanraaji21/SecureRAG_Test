"""
CWE-specific adjudication prompt (report Appendix A.1), following
ZeroFalse's and Vul-RAG's finding that CWE-specialized prompting
outperforms generic prompting (section 4.2.3, 4.6).
"""

from __future__ import annotations

from core.schemas.models import Finding, RetrievedEvidence

_CWE_NAMES = {
    "CWE-89": "SQL Injection",
    "CWE-79": "Cross-Site Scripting",
    "CWE-78": "OS Command Injection",
    "CWE-798": "Use of Hard-coded Credentials",
    "CWE-502": "Deserialization of Untrusted Data",
    "CWE-22": "Path Traversal",
    "CWE-327": "Use of a Broken or Risky Cryptographic Algorithm",
    "CWE-611": "XML External Entity Reference",
}

SYSTEM_PREAMBLE = (
    "You are a precise, conservative security code reviewer. You will be "
    "given a static-analysis finding plus retrieved reference knowledge. "
    "Respond with ONLY a single JSON object -- no prose, no markdown fences."
)


def cwe_name_for(cwe_id: str | None) -> str:
    if not cwe_id:
        return "Unknown Vulnerability Class"
    return _CWE_NAMES.get(cwe_id, cwe_id)


def build_adjudication_prompt(
    finding: Finding,
    evidence: list[RetrievedEvidence],
    evidence_texts: dict[str, str],
) -> str:
    """Builds the CWE-specific adjudication prompt exactly per Appendix A.1's
    template, populated with a real finding and its retrieved evidence."""
    cwe_id = finding.cwe_id or "UNKNOWN"
    cwe_name = cwe_name_for(finding.cwe_id)

    retrieved_definition = next(
        (evidence_texts.get(e.knowledge_item_id, "") for e in evidence), ""
    )
    retrieved_fix_pairs = [
        evidence_texts.get(e.knowledge_item_id, "") for e in evidence
    ]
    retrieved_fix_block = (
        "\n".join(f"- {t}" for t in retrieved_fix_pairs) or "(no closely matching evidence retrieved)"
    )

    return f"""{SYSTEM_PREAMBLE}

You are a security code reviewer specializing in {cwe_id} ({cwe_name}).
Finding: {finding.message}
File: {finding.file_path}, Line: {finding.line}
Code snippet:
{finding.code_snippet}

Retrieved knowledge: {retrieved_definition or "(none retrieved)"}
Retrieved similar fix(es):
{retrieved_fix_block}

Task: Determine whether this finding is a true positive or false positive.
Return structured JSON: {{ "verdict": "true_positive" | "false_positive" | "needs_review", "raw_confidence": <float 0-1>, "justification": "<string>", "cited_evidence_id": "<knowledge_item_id or empty string>" }}
"""
