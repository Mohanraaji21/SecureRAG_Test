# Testing and Verification

Two levels: the automated test suite (proves the *code* is correct,
runs in ~2 seconds, no external services) and a manual end-to-end
walkthrough (proves the *running system* works, needs Semgrep + Ollama).

## 1. Automated test suite

```bash
pytest
```
Expected: **`33 passed`**.

| Suite | Count | What it covers |
|---|---|---|
| `tests/` | 22 | AI core: Semgrep JSON parsing, FAISS retrieval + CWE filtering, LLM client parsing + fail-open behavior, temperature-scaling calibration math, ECE computation, full pipeline orchestration |
| `tests_api/test_api.py` | 6 | API: health check, auth enforcement, full scan→findings→review→metrics flow, 404s, input validation |
| `tests_api/test_webhooks.py` | 5 | Webhook: signature verification (valid/invalid/missing), event/action filtering, full checkout→scan flow with git mocked |

All three suites run against mocks (fake Semgrep output, fake LLM
responses, a fake git checkout) and a throwaway SQLite database — so this
passes even on a machine with no Semgrep, no Ollama, no SQL Server, no
internet access. **If this doesn't say `33 passed`, something is wrong
with the installation, not with your Semgrep/Ollama/SQL Server setup** —
fix this first.

Run just one suite:
```bash
pytest tests/ -v              # AI core only, verbose
pytest tests_api/ -v          # API + webhook only, verbose
```

## 2. Manual end-to-end walkthrough (the real system)

This proves Semgrep, FAISS, Ollama, calibration, persistence, and the
frontend all genuinely work together — not just that the code is
internally consistent.

### Via the dashboard (recommended — no curl needed)

1. `uvicorn api.main:app --reload`, then open `http://127.0.0.1:8000/`.
2. Paste your API key into the sidebar. Confirm **● connected** appears.
3. **Scans tab** → fill in a real repo path on the server (e.g. the
   project's own folder) → **Trigger scan**. Watch it move from
   `pending` to `completed` (click Refresh).
4. **Findings tab** → select the scan → confirm real findings appear,
   each with a verdict badge, a confidence bar, and a justification that
   reads like a real explanation (not an empty/error string).
5. Click **Review verdict** on one → confirm or overrule it.
6. **Calibration tab** → confirm `Expected Calibration Error` is now a
   real number (not `—`) and the reliability diagram shows at least one
   row.

If all six steps work, the entire system — frontend, API, AI core,
database — is proven to function end to end.

### Via curl (if you prefer, or are scripting this)

```bash
# 1. Health
curl http://127.0.0.1:8000/health

# 2. Trigger a scan
curl -X POST http://127.0.0.1:8000/scans \
  -H "X-API-Key: <your key>" -H "Content-Type: application/json" \
  -d '{"repo_path": "/path/to/repo", "repo_name": "self-test/repo"}'
# -> note the "Id" field as SCAN_ID

# 3. Poll until Status is "completed"
curl http://127.0.0.1:8000/scans/SCAN_ID

# 4. See findings
curl "http://127.0.0.1:8000/findings?scan_id=SCAN_ID"
# -> note a "verdict.Id" as VERDICT_ID

# 5. Submit a review
curl -X POST http://127.0.0.1:8000/verdicts/VERDICT_ID/review \
  -H "X-API-Key: <your key>" -H "Content-Type: application/json" \
  -d '{"reviewer_id": "you", "decision": "confirmed"}'

# 6. Check calibration
curl http://127.0.0.1:8000/metrics/calibration
```

### Testing the GitHub webhook specifically

See `docs/05_GITHUB_WEBHOOK_SETUP.md` — short answer: `pytest
tests_api/test_webhooks.py -v` proves the logic with no GitHub account
needed; that doc also has a `curl`-based way to exercise a real git clone
against a real public repo without setting up actual webhook delivery, if
you want to go one level more "real" than the mocked tests.

## 3. What "working" looks like vs. what a failure looks like

| Signal | Means |
|---|---|
| Scan `Status` reaches `completed`, findings have real justifications | ✅ Everything working |
| Scan `Status` becomes `failed` | ❌ Check `ErrorMessage` — almost always Semgrep or Ollama unreachable |
| Findings all show `needs_review` with "Fail-open fallback: LLM call failed..." | ❌ Ollama specifically isn't reachable (Semgrep worked, since findings exist at all) |
| Findings all show `needs_review` with "Fail-open fallback: ...malformed JSON..." | ⚠️ Ollama is reachable but the model isn't following the JSON format instruction well — try a different/larger model |
| `401` on trigger/review | ❌ API key mismatch between the dashboard/curl and `.env`'s `SCR_API_KEY` |
| Dashboard shows "● unreachable" | ❌ API server isn't running, or you opened the HTML file directly instead of via the server |

## 4. Verifying the SQL Server path specifically (if configured)

After a successful scan with `SCR_DATABASE_URL` pointed at SQL Server:
open SSMS → connect → expand your database → **Tables** → you should see
`ScanRuns`, `Findings`, `Verdicts`, `ReviewerDecisions` with real rows.
Right-click any table → "Select Top 1000 Rows" to inspect directly.
