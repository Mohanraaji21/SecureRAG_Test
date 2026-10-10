# Running SecureContext-RAG — Step by Step

## 1. Prerequisites

Install (see `README.md` for the Ollama one-liners):

- Python 3.11+
- Git
- Semgrep: `pip install semgrep`
- Ollama, running, with a model pulled: `ollama pull qwen2.5-coder:7b`
- (Production only) SQL Server reachable + ODBC Driver 18 for SQL Server
  installed on the machine running the app — see `README_PHASE2.md` →
  "Connecting to SQL Server"

## 2. Clone/unzip the project and install Python dependencies

```bash
cd securecontext_rag
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt -r requirements-api.txt
```

## 3. Configure

```bash
cp .env.example .env
```

Edit `.env`:
- For local dev with **zero DB setup**, leave `SCR_DATABASE_URL` as the
  SQLite default (or comment it out entirely).
- For **SQL Server**, uncomment and fill in the `mssql+pyodbc://...` line
  (see `README_PHASE2.md` for the exact connection-string forms for SQL
  auth vs. Windows Integrated auth).
- Set `SCR_API_KEY` to a real secret (it protects `POST /scans` and
  `POST /verdicts/{id}/review`).
- Confirm `SCR_OLLAMA_MODEL` matches the model you pulled.

## 4. Run the test suites (no Semgrep/Ollama/SQL Server needed for this step)

```bash
pytest tests/ -v        # Phase 1: 22 tests
pytest tests_api/ -v    # Phase 2: 6 tests
pytest -v               # everything: 28 tests
```

Both suites run entirely against mocks/fakes/a throwaway SQLite file — if
these pass, the logic is sound independent of whether your local
Semgrep/Ollama/SQL Server are reachable yet.

## 5. Start the API

```bash
uvicorn api.main:app --reload
```

- API: http://127.0.0.1:8000
- Interactive docs (try requests from the browser): http://127.0.0.1:8000/docs
- On startup, tables are created automatically in whichever database
  `SCR_DATABASE_URL` points to.

## 6. Trigger a real scan

Point `repo_path` at an actual checked-out repo on the same machine (or
container/volume) the API is running on:

```bash
curl -X POST http://127.0.0.1:8000/scans \
  -H "X-API-Key: <your SCR_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"repo_path": "/path/to/some/repo", "repo_name": "org/repo", "pr_number": 1}'
```

Response:
```json
{"Id": "…", "RepoName": "org/repo", "PRNumber": 1, "Status": "pending", ...}
```

Note the `Id` — that's your `scan_run_id`.

**First scan will be slow**: `sentence-transformers` downloads the
embedding model on first use, and each finding makes a real Ollama call.
Subsequent scans reuse the cached pipeline (`get_pipeline()` is
`lru_cache`d per process).

## 7. Poll for completion and view results

```bash
curl http://127.0.0.1:8000/scans/<scan_run_id>
```

Watch `"Status"` go from `"pending"` → `"running"` → `"completed"` (or
`"failed"` with an `"ErrorMessage"` — check that the Semgrep binary and
Ollama are both reachable if you see this).

Once completed:

```bash
curl "http://127.0.0.1:8000/findings?scan_id=<scan_run_id>"
```

Findings come back confidence-ranked, each with a nested `verdict`
(justification, calibrated confidence, cited evidence).

## 8. Submit reviewer feedback

```bash
curl -X POST http://127.0.0.1:8000/verdicts/<verdict_id>/review \
  -H "X-API-Key: <your SCR_API_KEY>" \
  -H "Content-Type: application/json" \
  -d '{"reviewer_id": "your-name", "decision": "confirmed"}'
```

`decision` must be one of `confirmed`, `overruled`, `unsure`.

## 9. Check calibration metrics

```bash
curl http://127.0.0.1:8000/metrics/calibration
```

Returns `null` for `expected_calibration_error` until at least one
verdict has a `confirmed`/`overruled` review — ECE needs ground truth.

## 10. Verify data landed in SQL Server (if you configured it)

Open SSMS → connect to your server → expand the database → **Tables** →
you should see `ScanRuns`, `Findings`, `Verdicts`, `ReviewerDecisions`.
Right-click any table → "Select Top 1000 Rows" to inspect data directly.

## 11. Running the OWASP benchmark evaluation (optional, standalone)

This is separate from the API — it scores a saved `ScanRun` JSON against
labeled ground truth (report §5.1–5.3):

```bash
python cli.py scan /path/to/owasp/benchmark/checkout --repo-name owasp/benchmark --out scan_result.json
python eval/run_owasp_benchmark.py --scan-run-json scan_result.json --labels-json my_labels.json
```

You'll need to download the OWASP Benchmark v1.2 corpus separately
(report citation [12]) and produce a `my_labels.json` in the shape:
```json
[{"finding_id": "...", "ground_truth_is_vulnerable": true}, ...]
```
or use `match_labels_by_location` if matching by `(file_path, line)`
against an external label format instead.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `SemgrepNotInstalledError` | `pip install semgrep`, confirm `semgrep --version` works in the same shell/venv the app runs in |
| Scan `Status` becomes `"failed"` with a connection-refused-style `ErrorMessage` | Ollama isn't running — `ollama serve`, or wrong `SCR_OLLAMA_URL` |
| `libodbc.so.2: cannot open shared object file` (Linux) when using SQL Server | Install `unixodbc` + Microsoft's `msodbcsql18` package (system-level, not pip) |
| Every finding comes back `needs_review` with `fail_open: true` | Check the `Justification` field — it states the exact fail-open reason (LLM timeout, malformed JSON, etc.) |
| `401` on `POST /scans` or `POST /verdicts/{id}/review` | Missing/incorrect `X-API-Key` header |
