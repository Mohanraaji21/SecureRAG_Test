# SecureContext-RAG — Documentation

This `docs/` folder is the complete reference for the project: what it
is, how every piece works, how to install and run it, and how to prove
it's working. The whole stack — AI core, API, persistence, **and the
frontend** — is implemented entirely in Python plus plain HTML/CSS/JS
served by that same Python backend. There is no Node.js, no separate
frontend build step, and no non-Python runtime anywhere in this project.

## Read in this order

| # | File | What's in it |
|---|---|---|
| 1 | **[01_ARCHITECTURE.md](./01_ARCHITECTURE.md)** | The big picture: two-tier design, every subsystem, how data flows from a scan request to a reviewed verdict |
| 2 | **[02_SETUP_AND_EXECUTION.md](./02_SETUP_AND_EXECUTION.md)** | Every prerequisite, every install command, every step to get the whole system (backend + frontend) running from zero |
| 3 | **[03_API_REFERENCE.md](./03_API_REFERENCE.md)** | Every endpoint: method, path, auth, request/response shape, example |
| 4 | **[04_FRONTEND.md](./04_FRONTEND.md)** | How the dashboard works, its pages, how it talks to the API, how to modify it |
| 5 | **[05_GITHUB_WEBHOOK_SETUP.md](./05_GITHUB_WEBHOOK_SETUP.md)** | How the CI/CD webhook activates, how to point a real GitHub repo at it, what happens on each PR event |
| 6 | **[06_TESTING_AND_VERIFICATION.md](./06_TESTING_AND_VERIFICATION.md)** | How to prove the app works — automated test suite plus a manual end-to-end walkthrough |
| 7 | **[PRIMARY_ALGORITHM.md](./PRIMARY_ALGORITHM.md)** | Deep dive into the actual retrieval/adjudication/calibration algorithm, with the math |
| 8 | **[HOW_IT_WORKS.md](./HOW_IT_WORKS.md)** | A narrower, code-level walkthrough of one scan's data flow, file-by-file |
| 9 | **[FILE_GUIDE.md](./FILE_GUIDE.md)** | Every single file in the repository, one line each, cross-referenced to report sections |

## One-paragraph summary

A developer (or an automated GitHub PR event) triggers a scan. A Python
pipeline runs Semgrep, retrieves CWE-matched security knowledge from a
local FAISS index, asks a local LLM (via Ollama) to adjudicate each
finding using that retrieved evidence, and calibrates the model's
confidence against historical accuracy. Results land in SQL Server (or
SQLite for local dev) through a FastAPI backend, which a static HTML/JS
dashboard — served by that same backend — displays as a confidence-ranked
list. A developer reviews each verdict in the dashboard; that feedback
both closes the loop for future calibration and is immediately visible as
an Expected Calibration Error metric.

## Is the backend "completely Python"?

Yes — this was a specific goal of this project stage, and it's true at
every layer:

| Layer | Technology | Language |
|---|---|---|
| AI core (static analysis orchestration, retrieval, adjudication, calibration) | Custom Python (`core/`) | Python |
| API server | FastAPI (`api/`) | Python |
| Persistence | SQLAlchemy ORM → SQL Server or SQLite | Python (SQL Server itself is the DB engine, not application code) |
| Frontend | Static HTML/CSS/vanilla JS, served by FastAPI's `StaticFiles` | HTML/CSS/JS by necessity (a browser can't run Python), but **no Node.js, no npm, no JS build step, no JS framework** — it's hand-written, zero-dependency, and served directly by the Python backend |
| Background task execution | FastAPI `BackgroundTasks` | Python |
| CI/CD webhook + git checkout | `subprocess` calls to the `git` binary | Python orchestrating a system tool, same as how it orchestrates Semgrep |

The only non-Python processes the system talks to are external tools it
was always going to need regardless of application-layer language choice:
**Semgrep** (static analysis engine), **Ollama** (LLM runtime), **git**
(for webhook checkouts), and **SQL Server** (the database engine). None
of those are part of "the backend" in the sense of application code —
they're infrastructure the Python backend calls out to, exactly the way
an ASP.NET Core backend would also have called out to Semgrep/Ollama/git/
SQL Server as external processes.
