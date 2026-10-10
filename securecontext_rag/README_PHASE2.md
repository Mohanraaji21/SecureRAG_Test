# SecureContext-RAG — Phase 2: FastAPI Application Layer

Tier 2 of the two-tier architecture (report §4.1): the API gateway,
persistence, reviewer feedback capture, calibration metrics, and (stretch
goal) GitHub webhook — all in Python/FastAPI, replacing the report's
original ASP.NET Core + SQL Server proposal for the *application
framework* while **keeping SQL Server itself** as the database, per your
SSMS setup.

## Architecture

```
   Semgrep / Ollama (external processes)
              |
   core/  <-- Phase 1 AI core (imported as a library, not shelled out to)
              |
   api/services/scan_service.py   <-- bridges core pipeline output to ORM rows
              |
   api/db/models.py (SQLAlchemy)  <-- ScanRuns / Findings / Verdicts / ReviewerDecisions
              |
   SQL Server (via pyodbc)  or  SQLite (dev/test default)
              ^
   api/routers/*.py  <-- FastAPI endpoints
              ^
   api/main.py  <-- FastAPI app, mounts routers
```

The decoupled-interface-contract principle from report §4.6 is preserved:
`core/` has zero FastAPI/SQLAlchemy imports and can be tested, run, or
swapped independently (see `README.md` for Phase 1 alone).

## Endpoints

| Method | Path                          | Auth | Purpose |
|--------|-------------------------------|------|---------|
| GET    | `/health`                     | none | liveness check |
| POST   | `/scans`                      | API key | trigger a scan (background task) |
| GET    | `/scans`                      | none | list scan runs |
| GET    | `/scans/{id}`                 | none | scan run detail with findings + verdicts |
| GET    | `/findings`                   | none | confidence-ranked findings (filters: `scan_id`, `min_confidence`, `cwe_id`) |
| GET    | `/findings/{id}`              | none | single finding detail |
| GET    | `/verdicts/{id}`               | none | single verdict detail |
| POST   | `/verdicts/{id}/review`        | API key | reviewer feedback capture |
| GET    | `/verdicts/{id}/reviews`       | none | review history for a verdict |
| GET    | `/metrics/calibration`         | none | ECE + reliability diagram from reviewed verdicts |
| POST   | `/webhooks/github`             | HMAC signature | CI/CD trigger — clones the PR's head commit automatically and scans it (§4.2.5) |

A static dashboard is also served at `/ui/` (FastAPI's `StaticFiles`, no
build step, no non-Python runtime) — see `docs/04_FRONTEND.md`.

Interactive OpenAPI docs are auto-served at `/docs` when the app is running
— this **is** the "documented, versioned JSON schema" report §4.6 calls
for as the Tier1/Tier2 interface contract.

## Connecting to SQL Server (SSMS)

1. Confirm SQL Server is reachable (Developer/Express edition is fine) and
   note: server host, port (default 1433), database name, and either SQL
   auth (username/password) or that you'll use Windows/Integrated auth.
2. Create the target database in SSMS if it doesn't exist yet (Object
   Explorer → right-click Databases → New Database → e.g. `SecureContextRag`).
3. Install the **ODBC Driver 18 for SQL Server** on the machine running
   the FastAPI app (this is separate from SSMS — SSMS is just the GUI):
   - Windows: usually already present, or download from Microsoft's ODBC driver page.
   - Linux: see Microsoft's `msodbcsql18` package instructions for your distro.
4. Set `SCR_DATABASE_URL` (see `.env.example`) to:
   ```
   mssql+pyodbc://<user>:<password>@<host>:1433/<database>?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes
   ```
   For Windows Integrated (trusted) auth instead of SQL auth:
   ```
   mssql+pyodbc://<host>:1433/<database>?driver=ODBC+Driver+18+for+SQL+Server&trusted_connection=yes&TrustServerCertificate=yes
   ```
5. Start the app — `init_db()` runs `Base.metadata.create_all()` on
   startup and creates the four tables (`ScanRuns`, `Findings`, `Verdicts`,
   `ReviewerDecisions`) if they don't exist. Open SSMS afterward and you'll
   see them under the database's Tables node.

**Current limitation, stated plainly:** table creation uses
`metadata.create_all()`, not Alembic migrations. That's fine while the
schema is still settling (matches the report's "design draft" framing of
Appendix A.3 at this stage) but **before any schema change that must
preserve production data**, introduce Alembic (`pip install alembic`,
`alembic init`, point `env.py` at `api.db.models.Base.metadata`) rather
than relying on `create_all`, which only adds missing tables — it never
alters existing ones.

## Local dev without SQL Server

Leave `SCR_DATABASE_URL` unset (defaults to `sqlite:///./securecontext_rag.db`)
to run and test everything with zero external DB setup. All 28 tests in
`tests/` + `tests_api/` run this way.

## Running

See **RUNNING.md** for the full step-by-step. Short version:

```bash
pip install -r requirements.txt -r requirements-api.txt
cp .env.example .env   # edit SCR_DATABASE_URL, SCR_API_KEY, etc.
uvicorn api.main:app --reload
# -> http://127.0.0.1:8000/docs
```

## Background task execution

`POST /scans` uses FastAPI's built-in `BackgroundTasks` — simplest option
that fits this project's scope (report §5.6 lists CI/CD scope creep as a
medium-high risk; a task queue is unnecessary complexity for a semester
case study). It runs in-process, after the response is sent. For scans
much longer than typical HTTP timeouts, or to survive an app restart
mid-scan, upgrading to Celery/RQ with a Redis broker is a documented,
isolated future change — only `api/services/scan_service.py`'s call site
would need to change, not the routers or DB models.

## What Phase 2 deliberately does not do yet

- No Alembic migrations (see limitation note above).
- No OAuth2/JWT — a single shared API key (`api/auth.py`) matches the
  report's scope; swapping in a real auth scheme only touches that one file.
- No rate limiting / request throttling on the Ollama-calling scan path.

These are all straightforward, scoped extensions — flagged here rather
than silently built in, so the codebase matches exactly what's been
tested (28/28 passing) and what's still a documented next step.
