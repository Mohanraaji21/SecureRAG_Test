# Architecture

## System diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Browser (any device)                        │
│                    Static dashboard: index.html / style.css / app.js │
└───────────────────────────────┬───────────────────────────────────┘
                                  │  fetch() calls to the JSON API
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      FastAPI application (api/)                      │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌─────────┐ ┌──────────┐ │
│  │  /scans   │ │ /findings │ │ /verdicts │ │/metrics │ │/webhooks │ │
│  └─────┬─────┘ └─────┬─────┘ └─────┬─────┘ └────┬────┘ └────┬─────┘ │
│        │             │             │            │           │       │
│        └─────────────┴──────┬──────┴────────────┴───────────┘       │
│                              ▼                                       │
│              api/services/scan_service.py (orchestration)            │
│              api/services/git_checkout.py (webhook checkouts)        │
│                              │                                       │
│              ┌───────────────┴───────────────┐                       │
│              ▼                                ▼                       │
│   core/ (Phase 1 AI core,          api/db/ (SQLAlchemy ORM)          │
│   imported directly as a library)             │                       │
└──────────────┬──────────────────────────────┬─┘                       │
               │                              ▼                       │
               │                    SQL Server (prod) / SQLite (dev)   │
               ▼                                                       │
   ┌───────────────────────┐    ┌──────────────┐    ┌────────────────┐│
   │ Semgrep (subprocess)  │    │ Ollama (HTTP)│    │ git (subprocess)││
   └───────────────────────┘    └──────────────┘    └────────────────┘│
                                                                        │
         External trigger: GitHub webhook on pull_request events ─────┘
```

## The two tiers (and now three surfaces)

The report's original design is a two-tier architecture: an AI core
(Tier 1) and an application layer (Tier 2). This implementation adds a
third surface — the frontend — but it doesn't add a third *tier* in the
architectural sense: the frontend has no logic of its own beyond
rendering API responses and collecting form input. All actual decision-
making still happens in exactly two places:

1. **Tier 1 — AI Core (`core/`)**: Semgrep orchestration, FAISS
   retrieval, LLM adjudication, confidence calibration. Pure Python,
   zero web-framework dependencies, independently testable and runnable
   via `cli.py`.
2. **Tier 2 — Application Layer (`api/`)**: FastAPI routes, SQLAlchemy
   persistence, background task scheduling, auth, the GitHub webhook.
   Imports Tier 1 directly as a Python library (not a subprocess, not a
   network call) — see `api/services/scan_service.py::get_pipeline()`.

The frontend (`frontend/`) is a **presentation surface on top of Tier 2**,
not a new tier: it holds no business logic, makes no decisions about
findings or verdicts, and would be trivially replaceable by any other
client (a CLI, a mobile app, `curl`) without touching either tier.

## Request lifecycle, end to end

1. **Trigger** — either a human clicks "Trigger scan" in the dashboard
   (→ `POST /scans`), or GitHub sends a `pull_request` webhook event
   (→ `POST /webhooks/github`, which additionally runs a git checkout
   first — see `docs/05_GITHUB_WEBHOOK_SETUP.md`).
2. **Record + respond** — a `ScanRunORM` row is created with
   `Status="pending"`, committed, and the HTTP response returns
   immediately with the `scan_run_id`. The actual work happens in a
   `BackgroundTask`, so the caller is never blocked on LLM latency.
3. **Run the AI core** — `TriagePipeline` (Tier 1) runs Semgrep, then
   processes each finding independently: retrieve → adjudicate →
   calibrate (see `docs/PRIMARY_ALGORITHM.md` for the full mechanics of
   this step).
4. **Persist** — every `Finding` and `Verdict` becomes a row in
   `Findings`/`Verdicts`; `ScanRunORM.Status` becomes `completed` (or
   `failed`, with `ErrorMessage` set, on any exception).
5. **Review** — the dashboard (or any API client) fetches
   `GET /findings?scan_id=...`, confidence-ranked, and a developer
   confirms/overrules each verdict via `POST /verdicts/{id}/review`.
6. **Measure** — `GET /metrics/calibration` computes Expected Calibration
   Error from accumulated reviewer decisions, closing the loop described
   in the report's Figure 3.1.

## Why FastAPI + SQLAlchemy instead of ASP.NET Core + EF Core

This is a **prototype validation** of the report's original architecture
(§4.7 of the Review 1 report, as updated), not a replacement for it. The
design decisions — four-table schema, JSON verdict contract, CWE-specific
prompting, fail-open safety — are all preserved exactly; only the
application-framework implementation language changed, so the whole
system (core + API + now frontend) could be built, tested, and iterated
on in one language during this prototyping stage.

## Why persistence is SQLAlchemy-over-SQL-Server, not something SQL-Server-specific

SQLAlchemy is a database-agnostic ORM; the exact same model definitions
in `api/db/models.py` work against SQL Server (`mssql+pyodbc://...`) or
SQLite (`sqlite:///...`), controlled purely by the `DATABASE_URL`
environment variable — no code branches. This is why local development
and the automated test suite use SQLite (zero setup) while production
targets SQL Server (matching your SSMS environment) with no code changes
required to switch between them.

## Fault isolation summary

Three independent layers keep a single bad finding, a down LLM, or a
failed git clone from ever corrupting a whole scan or crashing the app:

1. **Per-finding independence** — `TriagePipeline.run_on_findings` loops
   over findings with no shared state; one finding's failure can't affect
   another's processing.
2. **Fail-open adjudication** — any LLM network error or malformed output
   degrades that one finding to a `needs_review` verdict rather than
   raising.
3. **Scan-level failure containment** — if checkout, Semgrep, or anything
   else in the pipeline raises unexpectedly, `ScanRunORM.Status` becomes
   `"failed"` with a specific `ErrorMessage`, rather than leaving the scan
   stuck or crashing the background task worker.

Full detail on all three in `docs/PRIMARY_ALGORITHM.md` §6.
