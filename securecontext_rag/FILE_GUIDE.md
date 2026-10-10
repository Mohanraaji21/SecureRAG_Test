# File Guide

Every file in the repository, what it does, and which report section it implements.

## Root

| File | Purpose |
|---|---|
| `requirements.txt` | Phase 1 (AI core) Python dependencies |
| `requirements-api.txt` | Phase 2 (FastAPI layer) Python dependencies, on top of Phase 1's |
| `pyproject.toml` | pytest config (adds repo root to `pythonpath` so `core`/`api`/`eval` import cleanly) |
| `.env.example` | Template for environment configuration (copy to `.env`) |
| `cli.py` | Standalone Phase 1 CLI — runs the pipeline with no web server involved (`python cli.py scan ...`) |
| `README.md` | Phase 1 documentation |
| `README_PHASE2.md` | Phase 2 documentation |
| `INDEX.md` | Documentation entry point / reading order |
| `FILE_GUIDE.md` | This file |
| `HOW_IT_WORKS.md` | End-to-end data flow walkthrough |
| `RUNNING.md` | Step-by-step setup and run instructions |
| `data/cwe_seed.json` | Starter knowledge base: 8 CWEs, each with a definition + a vuln-fix pair (report §4.2.2, §5.6) |

## `core/` — Phase 1: AI Core (report Tier 1, §4.2.1–4.2.3)

No FastAPI/SQLAlchemy imports anywhere in this package — it's a standalone library.

| File | Purpose | Report section |
|---|---|---|
| `core/__init__.py` | Package docstring/version | — |
| `core/schemas/models.py` | Pydantic contracts: `Finding`, `KnowledgeItem`, `RetrievedEvidence`, `Verdict`, `ScanRun`, plus enums (`VerdictLabel`, `ReviewerDecision`, `Severity`). This is the Tier1↔Tier2 JSON contract. | Appendix A.2, A.3; §4.6 "decoupled interface contract" |
| `core/schemas/__init__.py` | Re-exports the above for `from core.schemas import Finding` convenience | — |
| `core/sast/semgrep_runner.py` | Runs `semgrep --json` as a subprocess, parses results into `Finding` objects; `parse_semgrep_json` is separated from `run_semgrep` so parsing is unit-testable without a real Semgrep binary | §4.2.1 |
| `core/retrieval/kb_builder.py` | Loads `data/cwe_seed.json` into `KnowledgeItem` objects; `add_vuln_fix_pair` for extending the KB programmatically | §4.2.2, §1.1.1 |
| `core/retrieval/faiss_index.py` | `KnowledgeIndex`: builds/queries a FAISS `IndexFlatIP` (cosine similarity via normalized inner product) over knowledge-item embeddings. CWE-filtered retrieval per §4.6. `SentenceTransformerEmbedder` is the production embedder; tests substitute a fake one. | §4.2.2, §4.6 |
| `core/adjudication/prompts.py` | `build_adjudication_prompt` — the CWE-specific prompt, populated with a real finding + retrieved evidence | Appendix A.1 |
| `core/adjudication/ollama_client.py` | `OllamaClient.adjudicate()` — calls local Ollama, parses structured JSON (tolerant of prose-wrapped JSON), and implements **fail-open**: any network error, timeout, or malformed output returns a `needs_review` verdict rather than raising or dropping the finding | §4.2.3, §4.6 |
| `core/calibration/temperature_scaling.py` | `TemperatureScaler` — fits a scalar temperature on labeled data (NLL minimization via `scipy.optimize.minimize_scalar`), converts raw → calibrated confidence. Unfitted = identity, so the pipeline works before enough labeled data exists. | §3.2.1, §4.2.3 |
| `core/calibration/metrics.py` | `expected_calibration_error` (binned ECE) and `reliability_diagram_data` (per-bin confidence/accuracy for Figure 5.2-style plotting) | §3.2.1, §5.1, Figure 5.2 |
| `core/pipeline.py` | `TriagePipeline` — orchestrates retrieval → adjudication → calibration per finding (`process_finding`), and Semgrep → pipeline end-to-end (`run_on_repo`). Enforces per-finding processing and a last-resort fail-open guard around the whole per-finding flow. | §4.3, §4.6 |

## `eval/` — Evaluation harness

| File | Purpose | Report section |
|---|---|---|
| `eval/run_owasp_benchmark.py` | Scores a saved `ScanRun` against ground-truth labels: Precision/Recall/F1/False-Positive-Rate/ECE. `match_labels_by_location` handles matching an external benchmark's labels by `(file_path, line)` when finding IDs don't align. CLI usable directly (`python eval/run_owasp_benchmark.py --scan-run-json ... --labels-json ...`). | §5.1–5.3 |

## `api/` — Phase 2: FastAPI Application Layer (report Tier 2, §4.2.4–4.2.5)

| File | Purpose | Report section |
|---|---|---|
| `api/main.py` | FastAPI app; mounts all routers; `lifespan` calls `init_db()` on startup; `/health` endpoint | §4.2.4 |
| `api/config.py` | `Settings` (pydantic-settings) — all config via `SCR_*` env vars / `.env`: DB URL, API key, Ollama URL/model, embedding model, webhook secret | §4.2.4 |
| `api/auth.py` | `require_api_key` dependency — single shared-key auth on mutating endpoints | §4.2.4 "authenticating requests" |
| `api/db/models.py` | SQLAlchemy ORM: `ScanRunORM`, `FindingORM`, `VerdictORM`, `ReviewerDecisionORM` — column names match Appendix A.3 exactly, with clearly-commented operational additions (status tracking, raw Semgrep fields, etc.) | Appendix A.3, §4.2.4 |
| `api/db/session.py` | SQLAlchemy engine/session factory; `init_db()` (creates tables); `get_db()` (FastAPI dependency) — dialect-agnostic, so the same code runs against SQL Server or SQLite depending on `DATABASE_URL` | §4.2.4 |
| `api/schemas/api_schemas.py` | API-facing Pydantic request/response models (`ScanRequest`, `ScanRunDetail`, `FindingOut`, `VerdictOut`, `ReviewRequest`, `CalibrationMetricsOut`, ...) | §4.2.4 |
| `api/services/scan_service.py` | `get_pipeline()` — builds and caches a `TriagePipeline` (Phase 1, imported directly). `run_scan_and_persist()` — the background-task function used by `POST /scans`: runs Semgrep + adjudication, writes `FindingORM`/`VerdictORM` rows, updates `ScanRunORM.Status`. `checkout_and_run_scan_and_persist()` — the webhook's entry point: checks out the PR first, then delegates to `run_scan_and_persist` | §4.2.4, §4.3, §4.2.5 |
| `api/routers/scans.py` | `POST /scans` (trigger, API-key protected), `GET /scans` (list), `GET /scans/{id}` (detail) | §4.2.4 |
| `api/routers/findings.py` | `GET /findings` (confidence-ranked, filterable by `scan_id`/`min_confidence`/`cwe_id`), `GET /findings/{id}` | §4.2.5 "confidence-ranked findings" |
| `api/routers/verdicts.py` | `GET /verdicts/{id}`, `POST /verdicts/{id}/review` (reviewer feedback capture, API-key protected), `GET /verdicts/{id}/reviews` | §4.2.4/§4.2.5 "reviewer feedback capture" |
| `api/routers/metrics.py` | `GET /metrics/calibration` — computes ECE + reliability diagram from verdicts with `confirmed`/`overruled` reviewer decisions as ground truth | §3.2.1, Figure 5.2 |
| `api/routers/webhooks.py` | `POST /webhooks/github` — HMAC-signature-verified GitHub webhook; on `pull_request` events, checks out the PR's head commit (via `git_checkout.py`) and triggers a scan automatically | §4.2.5, §1.4 (stretch goal, now complete) |
| `api/services/git_checkout.py` | `ensure_pr_checkout()` — clones (or fetches+checks out, if already cloned) a PR's head commit via `git` subprocess calls, so the webhook needs no manual checkout step | §4.2.5 |

## `tests/` — Phase 1 unit tests (22 tests, all passing)

| File | Covers |
|---|---|
| `tests/test_semgrep_runner.py` | JSON parsing: CWE extraction, severity mapping, empty results |
| `tests/test_faiss_index.py` | Index build, CWE-filtered query, item text roundtrip — uses a deterministic fake embedder (no model download needed) |
| `tests/test_ollama_client.py` | JSON parsing (clean / prose-wrapped / garbage), happy-path adjudication, fail-open on connection error, fail-open on malformed output |
| `tests/test_calibration.py` | Identity behaviour when unfitted, temperature fitting reduces overconfidence, ECE on perfectly/poorly calibrated data, reliability diagram shape |
| `tests/test_pipeline.py` | Single-finding processing, independent per-finding processing, fail-open on an orchestration-level crash, eval harness scoring |

## `tests_api/` — Phase 2 API tests (11 tests, all passing)

| File | Covers |
|---|---|
| `tests_api/test_api.py` | Health check, API-key enforcement, full scan→findings→review→calibration-metrics flow (pipeline mocked, real SQLite DB), 404 handling, invalid review-decision rejection. Uses an isolated temp SQLite file so it never touches your dev/production DB. |
| `tests_api/test_webhooks.py` | Signature verification (missing/invalid/valid), event and action filtering, and the full checkout→scan flow with `git` itself mocked (no real network clone needed to test the logic). |

## `frontend/` — Static dashboard (no build step)

| File | Purpose |
|---|---|
| `frontend/index.html` | Page structure: Scans / Findings / Calibration views, trigger-scan form, review modal |
| `frontend/style.css` | All styling — dark data-dense console look, CSS custom properties for theming |
| `frontend/app.js` | All behavior — `fetch()` calls to the API, rendering, view switching, review modal logic |

See `docs/04_FRONTEND.md` for the full breakdown.

## `docs/` — Final-stage consolidated documentation

| File | Purpose |
|---|---|
| `docs/00_INDEX.md` | Entry point and reading order for everything below |
| `docs/01_ARCHITECTURE.md` | System diagram, two-tier design, request lifecycle |
| `docs/02_SETUP_AND_EXECUTION.md` | Complete install → run → use steps, including the frontend |
| `docs/03_API_REFERENCE.md` | Every endpoint, request/response shapes |
| `docs/04_FRONTEND.md` | Frontend architecture and how to extend it |
| `docs/05_GITHUB_WEBHOOK_SETUP.md` | How the webhook activates and how to configure it on a real repo |
| `docs/06_TESTING_AND_VERIFICATION.md` | Automated suite + manual end-to-end walkthrough |
| `docs/PRIMARY_ALGORITHM.md`, `docs/HOW_IT_WORKS.md`, `docs/FILE_GUIDE.md` | Copies of the root-level deep-dive docs, for a self-contained `docs/` folder |
