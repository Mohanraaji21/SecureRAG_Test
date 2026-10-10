# SecureContext-RAG — Documentation Index

This codebase implements the Review 1 report's SecureContext-RAG system
as a **fully Python** application — AI core, FastAPI backend, and a
static-file frontend — with persistence targeting **SQL Server**
(matching your SSMS setup) via SQLAlchemy + pyodbc, or SQLite for local
dev.

## ⭐ Start here: [docs/00_INDEX.md](./docs/00_INDEX.md)

The `docs/` folder is the complete, current, final-stage documentation:
architecture, full setup (including the frontend), API reference,
frontend guide, GitHub webhook setup, and a testing/verification guide —
plus the deep-dive algorithm and file-guide docs also linked below.

## Files in this root folder

1. **[README.md](./README.md)** — Phase 1 (AI core) overview.
2. **[README_PHASE2.md](./README_PHASE2.md)** — Phase 2 (FastAPI + SQL Server) overview.
3. **[FILE_GUIDE.md](./FILE_GUIDE.md)** — every file, one line each (also in `docs/`).
4. **[HOW_IT_WORKS.md](./HOW_IT_WORKS.md)** — request-to-response data flow (also in `docs/`).
5. **[RUNNING.md](./RUNNING.md)** — original Phase 2 run instructions; superseded by `docs/02_SETUP_AND_EXECUTION.md`, which additionally covers the frontend.

## One-paragraph summary

A `POST /scans` request triggers a background task that runs Semgrep over
a checked-out repo, retrieves CWE-matched knowledge from a FAISS index for
each finding, sends each finding + retrieved evidence to a local Ollama
LLM using a CWE-specific prompt, calibrates the model's raw confidence via
temperature scaling, and persists every `Finding` and `Verdict` to SQL
Server. `GET /findings` returns them confidence-ranked; `POST
/verdicts/{id}/review` lets a developer confirm or overrule a verdict,
and `GET /metrics/calibration` reports Expected Calibration Error (ECE)
computed against those reviewer decisions — closing the loop described in
the report's Figure 3.1.
