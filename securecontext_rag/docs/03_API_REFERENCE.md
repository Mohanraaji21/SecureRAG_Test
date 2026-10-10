# API Reference

Base URL (local dev): `http://127.0.0.1:8000`. Interactive, always-current
docs are auto-served at `/docs` (Swagger UI) and `/redoc` while the app is
running — this file is a human-readable companion to that, not a
replacement for it.

Auth: endpoints marked **🔒** require an `X-API-Key` header matching
`SCR_API_KEY` from your `.env`. Everything else is open (no auth) — read
access to findings/scans/metrics is intentionally unauthenticated in this
prototype; see `docs/01_ARCHITECTURE.md` for the auth design note.

---

## `GET /health`
Liveness check.
```
→ 200 { "status": "ok" }
```

---

## `POST /scans` 🔒
Triggers a scan as a background task. Returns immediately with the scan
run in `pending` status.

**Request body:**
```json
{
  "repo_path": "/absolute/path/on/the/server",
  "repo_name": "acme-org/webapp",
  "pr_number": 42
}
```
`pr_number` is optional.

**Response (200):**
```json
{
  "Id": "7c9e2c3a-4b8b-4a3a-9e2a-1f6d2a0c9b31",
  "RepoName": "acme-org/webapp",
  "PRNumber": 42,
  "TriggeredAt": "2026-09-27T05:10:02Z",
  "Status": "pending",
  "ErrorMessage": null,
  "CompletedAt": null
}
```

---

## `GET /scans`
Lists all scan runs, newest first.
```
→ 200 [ { ...ScanRunSummary }, ... ]
```

---

## `GET /scans/{scan_run_id}`
Full detail of one scan: status plus, once complete, every finding and
its verdict.
```
→ 200 {
  "Id": "...", "RepoName": "...", "Status": "completed", ...,
  "findings": [
    {
      "Id": "...", "RuleId": "...", "CweId": "CWE-89", "FilePath": "...",
      "Line": 47, "Message": "...", "CodeSnippet": "...",
      "verdict": {
        "Id": "...", "Verdict": "true_positive", "RawConfidence": 0.91,
        "CalibratedConfidence": 0.84, "Justification": "...", "FailOpen": false
      }
    }
  ]
}
→ 404 if scan_run_id doesn't exist
```

---

## `GET /findings`
Confidence-ranked findings (unadjudicated findings sort last).

**Query params (all optional):**
| Param | Type | Effect |
|---|---|---|
| `scan_id` | string | restrict to one scan run |
| `min_confidence` | float 0–1 | only findings with calibrated confidence ≥ this |
| `cwe_id` | string | e.g. `CWE-89` |

```
→ 200 [ { ...FindingOut with nested verdict }, ... ]
```

## `GET /findings/{finding_id}`
Single finding detail.
```
→ 200 { ...FindingOut }
→ 404 if not found
```

---

## `GET /verdicts/{verdict_id}`
Single verdict detail.
```
→ 200 { "Id": "...", "Verdict": "true_positive", "CalibratedConfidence": 0.84, ... }
→ 404 if not found
```

## `POST /verdicts/{verdict_id}/review` 🔒
Records a reviewer's decision — this is the human-feedback-capture step
that feeds the calibration metric.

**Request body:**
```json
{ "reviewer_id": "priya.k", "decision": "confirmed", "note": "optional" }
```
`decision` must be exactly one of: `confirmed`, `overruled`, `unsure`.

```
→ 200 { "Id": "...", "VerdictId": "...", "ReviewerId": "priya.k", "Decision": "confirmed", "DecidedAt": "...", "Note": "..." }
→ 404 if verdict_id doesn't exist
→ 422 if decision isn't one of the three allowed values
```

## `GET /verdicts/{verdict_id}/reviews`
Full review history for one verdict (if reviewed more than once).
```
→ 200 [ { ...ReviewerDecisionOut }, ... ]
```

---

## `GET /metrics/calibration`
Expected Calibration Error + reliability diagram, computed from verdicts
with a `confirmed`/`overruled` reviewer decision as ground truth.
`unsure` decisions and unreviewed verdicts are excluded (ECE needs a
binary correctness label).

**Query params:** `scan_id` (optional) — restrict to one scan.

```
→ 200 {
  "n_reviewed_verdicts": 12,
  "expected_calibration_error": 0.16,
  "reliability_diagram": [
    { "bin_range": [0.8, 0.9], "avg_confidence": 0.84, "accuracy": 0.9, "count": 10 }
  ]
}
```
`expected_calibration_error` and `reliability_diagram` are both `null`
until at least one verdict has been reviewed.

---

## `POST /webhooks/github`
GitHub Actions webhook receiver. Not protected by `X-API-Key` — instead
verified via `X-Hub-Signature-256` (HMAC-SHA256 over the raw body, using
`SCR_GITHUB_WEBHOOK_SECRET`). Full setup instructions in
`docs/05_GITHUB_WEBHOOK_SETUP.md`.

- Only handles `X-GitHub-Event: pull_request` with
  `action` in `opened`/`synchronize`/`reopened`; everything else returns
  `{"status": "ignored", ...}` with `200`.
- On a handled event: clones/updates the PR's head commit, creates a
  `ScanRun`, and runs the same pipeline as `POST /scans`.

```
→ 200 { "status": "scan_triggered", "scan_run_id": "..." }
→ 200 { "status": "ignored", "reason": "..." }
→ 401 on missing/invalid signature
→ 422 if the payload is missing repository/PR info
```

---

## Error shape

All errors follow FastAPI's standard shape:
```json
{ "detail": "human-readable message" }
```
with the appropriate HTTP status code (`401`, `404`, `422`, etc.).
