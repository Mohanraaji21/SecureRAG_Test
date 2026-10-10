# SecureContext-RAG — Phase 1: AI Core

Retrieval-augmented, confidence-calibrated vulnerability triage pipeline
(Semgrep → FAISS knowledge retrieval → LLM adjudication via Ollama →
temperature-scaling calibration), implemented as a standalone Python
package with no web-framework dependency, per the Review 1 report's
phased build order (§4.6: AI core first, application layer second).

## Layout

```
core/
  schemas/models.py        Pydantic contracts (Finding, Verdict, ScanRun, ...) -- Appendix A.2/A.3
  sast/semgrep_runner.py   §4.2.1 Semgrep wrapper
  retrieval/
    kb_builder.py          §4.2.2 knowledge base loading
    faiss_index.py         §4.2.2 FAISS index build/query (knowledge-level, CWE-filtered)
  adjudication/
    prompts.py             Appendix A.1 CWE-specific prompt template
    ollama_client.py        §4.2.3 LLM call + fail-open parsing
  calibration/
    temperature_scaling.py §3.2.1/§4.2.3 calibration layer
    metrics.py              ECE + reliability diagram data
  pipeline.py               §4.3/§4.6 per-finding orchestrator
data/cwe_seed.json          Starter knowledge base (8 common CWEs, definitions + fix pairs)
eval/run_owasp_benchmark.py §5.1-5.3 evaluation harness (P/R/F1/FPR/ECE)
cli.py                      Standalone CLI: `python cli.py scan <repo_path> --repo-name ...`
tests/                      22 unit tests, all passing, fully mocked (no live Semgrep/Ollama needed)
```

## Installing prerequisites

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

You additionally need, installed separately on your machine (not pip packages):

- **Semgrep binary** reachable on PATH — `pip install semgrep` covers this too, or use a native install.
- **Ollama**, running locally, with a model pulled:
  ```bash
  ollama pull qwen2.5-coder:7b
  ollama serve   # usually auto-started by the installer
  ```
  If you use a different model, pass `--model <name>` to `cli.py` or construct
  `OllamaClient(model="...")` directly.

## Running the tests

```bash
pytest -v
```

All 22 tests pass using mocked Semgrep JSON fixtures, a fake deterministic
embedder, and a mocked Ollama HTTP call — so the suite runs with zero
external services. This validates the *logic* (parsing, retrieval
filtering, fail-open behaviour, calibration math) independent of whether
Semgrep/Ollama are installed in a given environment.

## Running the real pipeline end-to-end

Once Semgrep and Ollama are installed and running:

```bash
python cli.py scan /path/to/target/repo --repo-name my-org/my-repo
```

This will:
1. Run Semgrep over the repo, producing `Finding` objects.
2. Build a FAISS index from `data/cwe_seed.json` using
   `sentence-transformers/all-MiniLM-L6-v2` (downloaded on first run).
3. For each finding, retrieve CWE-matched evidence and call Ollama with
   the Appendix A.1 prompt.
4. Apply (identity, until fitted) temperature-scaling calibration.
5. Print a `ScanRun` JSON (matches the Appendix A.3-derived schema) to stdout.

## Fitting the calibrator on labeled data

```python
from core.calibration.temperature_scaling import TemperatureScaler
import numpy as np

scaler = TemperatureScaler().fit(raw_confidences, correct)  # both np arrays
scaler.calibrate(0.9)  # -> calibrated confidence
```

`eval/run_owasp_benchmark.py` shows the scoring side (P/R/F1/FPR/ECE) once
you have a `ScanRun` and a ground-truth label file. It does not bundle the
OWASP Benchmark Java corpus itself — download that separately per the
report's citation [12] (https://owasp.org/www-project-benchmark/).

## Extending the knowledge base

`data/cwe_seed.json` currently covers 8 common CWEs (SQLi, XSS, command
injection, hard-coded credentials, insecure deserialization, path
traversal, weak crypto, XXE) as a working starter set. Extend it with more
CWE definitions and mined vulnerability-fix pairs (§5.6's KB-construction
risk mitigation: "bootstrapped from public CWE/CVE sources"), following
the same `{cwe_id, kind, title, text}` shape — `kb_builder.load_from_json`
accepts any file in this shape.

## What's deliberately not in Phase 1

- No database / persistence — that's Tier 2 (Phase 2, FastAPI + SQL Server).
- No API server — `cli.py` and direct Python imports are the only entry points.
- No conformal-prediction calibration — noted in the report (§5.6) as a
  fallback if temperature scaling proves too coarse; `TemperatureScaler`
  is structured so a second `Calibrator` implementation can be added later
  without touching `pipeline.py`'s call site.
- No GitHub Actions webhook — that's Tier 2's CI/CD integration (§4.2.5).

## Next: Phase 2

Phase 2 will build a FastAPI application layer on top of this package
(imported as a library, not shelled out to), with:
- SQLAlchemy models mirroring Appendix A.3, targeting **SQL Server** via
  `pyodbc`/ODBC Driver 18 (per your SSMS setup) instead of the report's
  original ASP.NET Core + EF Core.
- `POST /scans`, `GET /findings`, `POST /verdicts/{id}/review` endpoints.
- Background task execution for scans, API-key auth, and (stretch) a
  GitHub Actions webhook receiver.
