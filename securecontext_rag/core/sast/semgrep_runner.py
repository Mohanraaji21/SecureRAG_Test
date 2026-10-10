"""
Static analysis and candidate generation subsystem (report section 4.2.1).

Runs Semgrep over a repository (or a diff) and parses its structured JSON
output into `Finding` objects. Semgrep was selected, per the report, for
producing structured JSON suitable for automated downstream processing.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from core.schemas.models import Finding, Severity

_SEVERITY_MAP = {
    "INFO": Severity.INFO,
    "WARNING": Severity.WARNING,
    "ERROR": Severity.ERROR,
}


class SemgrepNotInstalledError(RuntimeError):
    pass


class SemgrepExecutionError(RuntimeError):
    pass


def is_semgrep_available() -> bool:
    return shutil.which("semgrep") is not None


def _extract_cwe_id(result: dict) -> str | None:
    """Semgrep rules may attach CWE metadata as a list like ['CWE-89: ...']
    or a single string; normalize to a bare 'CWE-89' id."""
    metadata = result.get("extra", {}).get("metadata", {})
    cwe = metadata.get("cwe")
    if not cwe:
        return None
    if isinstance(cwe, list):
        cwe = cwe[0] if cwe else None
    if not cwe:
        return None
    # "CWE-89: Improper Neutralization..." -> "CWE-89"
    return str(cwe).split(":")[0].strip()


def parse_semgrep_json(raw_output: dict) -> list[Finding]:
    """Pure parsing function (no subprocess), kept separate so it's easily
    unit-testable against a fixture without invoking the real binary."""
    findings: list[Finding] = []
    for result in raw_output.get("results", []):
        start = result.get("start", {})
        end = result.get("end", {})
        severity_raw = result.get("extra", {}).get("severity", "WARNING")
        findings.append(
            Finding(
                rule_id=result.get("check_id", "unknown-rule"),
                cwe_id=_extract_cwe_id(result),
                file_path=result.get("path", "unknown"),
                line=start.get("line", 0),
                end_line=end.get("line"),
                severity=_SEVERITY_MAP.get(severity_raw, Severity.WARNING),
                message=result.get("extra", {}).get("message", ""),
                code_snippet=result.get("extra", {}).get("lines", ""),
            )
        )
    return findings


def run_semgrep(
    target_path: str | Path,
    config: str = "auto",
    timeout_seconds: int = 300,
) -> list[Finding]:
    """Runs `semgrep --json --config <config> <target_path>` and returns
    parsed Finding objects.

    Raises SemgrepNotInstalledError if the binary is missing, and
    SemgrepExecutionError on a non-zero exit that isn't semgrep's normal
    "findings present" exit code.
    """
    if not is_semgrep_available():
        raise SemgrepNotInstalledError(
            "semgrep executable not found on PATH. Install with "
            "`pip install semgrep` (see README prerequisites)."
        )

    target_path = str(target_path)
    cmd = ["semgrep", "--json", "--config", config, target_path]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise SemgrepExecutionError(f"semgrep timed out after {timeout_seconds}s") from exc

    # Semgrep exits 1 when findings are present -- that's not an error for us.
    if proc.returncode not in (0, 1):
        raise SemgrepExecutionError(
            f"semgrep exited with code {proc.returncode}: {proc.stderr[:2000]}"
        )

    try:
        raw = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        raise SemgrepExecutionError(f"could not parse semgrep JSON output: {exc}") from exc

    return parse_semgrep_json(raw)
