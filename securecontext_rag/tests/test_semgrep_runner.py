from core.sast.semgrep_runner import parse_semgrep_json
from core.schemas.models import Severity

SAMPLE_SEMGREP_OUTPUT = {
    "results": [
        {
            "check_id": "python.lang.security.sql-injection",
            "path": "app/db.py",
            "start": {"line": 42},
            "end": {"line": 42},
            "extra": {
                "message": "Untrusted input concatenated into SQL query",
                "severity": "ERROR",
                "lines": 'query = "SELECT * FROM users WHERE id = " + user_id',
                "metadata": {"cwe": ["CWE-89: Improper Neutralization of Special Elements"]},
            },
        },
        {
            "check_id": "python.lang.security.hardcoded-secret",
            "path": "app/config.py",
            "start": {"line": 5},
            "end": {"line": 5},
            "extra": {
                "message": "Hard-coded API key",
                "severity": "WARNING",
                "lines": 'API_KEY = "sk-live-abc123"',
                "metadata": {},
            },
        },
    ]
}


def test_parse_semgrep_json_extracts_findings():
    findings = parse_semgrep_json(SAMPLE_SEMGREP_OUTPUT)
    assert len(findings) == 2

    first = findings[0]
    assert first.rule_id == "python.lang.security.sql-injection"
    assert first.cwe_id == "CWE-89"
    assert first.file_path == "app/db.py"
    assert first.line == 42
    assert first.severity == Severity.ERROR


def test_parse_semgrep_json_handles_missing_cwe_metadata():
    findings = parse_semgrep_json(SAMPLE_SEMGREP_OUTPUT)
    second = findings[1]
    assert second.cwe_id is None
    assert second.severity == Severity.WARNING


def test_parse_semgrep_json_empty_results():
    assert parse_semgrep_json({"results": []}) == []
