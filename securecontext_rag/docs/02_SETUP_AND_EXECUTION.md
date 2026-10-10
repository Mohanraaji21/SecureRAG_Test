# Setup and Execution — Every Step, Start to Finish

This is the complete, step-by-step path from an empty machine to a
running system with the dashboard open in your browser.

---

## 1. Prerequisites

| # | Tool | Why | Required for... |
|---|---|---|---|
| 1 | Python 3.11+ | Everything is Python | Always |
| 2 | pip / venv | Package management | Always |
| 3 | Git | Checking out repos to scan; required by the webhook's git-checkout step | Real scans, webhook |
| 4 | Semgrep | Produces the static-analysis findings the pipeline adjudicates | Real scans |
| 5 | Ollama + a pulled model | Runs the local LLM that adjudicates findings | Real scans |
| 6 | SQL Server + ODBC Driver 18 | Production persistence (matches SSMS) | Production only — SQLite needs none of this |
| 7 | A modern browser | Runs the dashboard | Using the frontend |

**You do not need #3–6 to run the automated test suite** — it's fully
mocked. You need all of them for a real, end-to-end scan against real
code with a real LLM.

### Install commands

```bash
# 1-2: Python (verify, install if missing)
python3 --version
pip3 --version

# 3: Git
git --version

# 4: Semgrep
pip install semgrep
semgrep --version

# 5: Ollama
curl -fsSL https://ollama.com/install.sh | sh     # Linux
# macOS: brew install ollama
# Windows: download installer from https://ollama.com/download
ollama serve
ollama pull qwen2.5-coder:7b
ollama list
```

### SQL Server (optional — skip for local dev/testing)

- Install SQL Server (Developer/Express) and create a database via SSMS
  (Object Explorer → right-click **Databases** → **New Database**).
- Install **ODBC Driver 18 for SQL Server** on the machine running the
  API (separate from SSMS, which is just the GUI client):
  ```bash
  # Linux:
  sudo apt-get update
  sudo apt-get install -y unixodbc unixodbc-dev
  # then install Microsoft's msodbcsql18 package per their distro instructions
  ```
  Windows usually has this pre-installed; otherwise get it from
  Microsoft's ODBC driver download page.

---

## 2. Project setup

```bash
# Unzip the project, then:
cd securecontext_rag

python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate

pip install -r requirements.txt -r requirements-api.txt

cp .env.example .env
```

Edit `.env`:
```ini
# Local dev default — zero setup:
SCR_DATABASE_URL=sqlite:///./securecontext_rag.db

# Change to a real secret:
SCR_API_KEY=my-local-dev-key-123

# Match whatever you pulled with `ollama pull`:
SCR_OLLAMA_MODEL=qwen2.5-coder:7b

# Only needed if you'll test the GitHub webhook (docs/05):
SCR_GITHUB_WEBHOOK_SECRET=my-webhook-secret
```

For SQL Server instead of SQLite, change `SCR_DATABASE_URL` to:
```ini
SCR_DATABASE_URL=mssql+pyodbc://<user>:<password>@<host>:1433/<database>?driver=ODBC+Driver+18+for+SQL+Server&TrustServerCertificate=yes
```

No migration step is needed — tables are created automatically on
startup.

---

## 3. Run the automated test suite (sanity check)

```bash
pytest
```
Expected: `33 passed` (22 AI-core tests, 6 API tests, 5 webhook tests).
This runs with zero external services — everything is mocked. **Do this
before anything else** — it proves the code itself is correct,
independent of your local Semgrep/Ollama/SQL Server setup.

---

## 4. Start the application

```bash
uvicorn api.main:app --reload
```
You should see:
```
INFO:     Uvicorn running on http://127.0.0.1:8000
INFO:     Application startup complete.
```

Leave this running. Open a new terminal for anything else.

---

## 5. Open the dashboard

In your browser:
```
http://127.0.0.1:8000/
```
This redirects to `/ui/` and loads the dashboard — a left-rail
navigation (Scans / Findings / Calibration) with a main panel.

1. Paste your `SCR_API_KEY` value into the **API key** field in the
   sidebar (needed for triggering scans and submitting reviews — read-only
   views work without it).
2. The connection indicator under the API key field should read
   **● connected** within a few seconds (it polls `/health`).

If you'd rather skip the UI and drive everything via HTTP directly,
`http://127.0.0.1:8000/docs` is the interactive Swagger UI, and
`docs/06_TESTING_AND_VERIFICATION.md` has a full `curl` walkthrough.

---

## 6. Trigger your first scan

**From the dashboard:** go to the **Scans** tab, fill in:
- **Repo path** — an absolute path on the *server's* filesystem to scan
  (not your browser's machine). For a first test, you can point it at the
  project's own folder, e.g. `/home/you/securecontext_rag`.
- **Repo name** — any label, e.g. `self-test/securecontext-rag`.
- **PR #** — optional.

Click **Trigger scan**. It appears in the Scans table with status
`pending`, moving to `running`, then `completed` (click **Refresh**).

**First scan will be slow** — the embedding model downloads on first use,
and every finding makes a real LLM call. Subsequent scans are fast.

Once `completed`, go to the **Findings** tab, select the scan from the
dropdown, and you'll see confidence-ranked findings with justifications
and evidence citations. Click **Review verdict** on any finding to
confirm/overrule it. Then check the **Calibration** tab — once you've
reviewed at least one verdict, it shows a real Expected Calibration Error
number and a reliability diagram.

---

## 7. (Optional) Set up the GitHub webhook for automatic scans

Covered in full in `docs/05_GITHUB_WEBHOOK_SETUP.md`. Short version: this
is for *automatic* scanning when a PR opens on a real GitHub repo,
instead of manually clicking "Trigger scan." It requires a publicly
reachable deployment of this app and a real GitHub repository — it is
**not** needed to use, test, or demo the system locally.

---

## 8. Stopping / restarting

`Ctrl+C` in the `uvicorn` terminal stops the server. Your data persists
in `securecontext_rag.db` (SQLite) or your SQL Server database between
restarts — nothing is lost. Deactivate the virtual environment with
`deactivate` when you're done.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `pytest` doesn't say `33 passed` | Fix this first — re-run `pip install -r requirements.txt -r requirements-api.txt` inside the activated venv |
| `uvicorn: command not found` | Venv not activated, or `requirements-api.txt` not installed |
| Dashboard loads but shows "● unreachable" | The API server isn't running, or you're opening the HTML file directly instead of via `http://127.0.0.1:8000/ui/` (it must be served by FastAPI, not opened as a local file, so `fetch()` calls work) |
| Scan `Status` becomes `failed` | Check the scan's `ErrorMessage` in the dashboard or via `GET /scans/{id}` — almost always Semgrep not installed or Ollama not running |
| Every finding is `needs_review` with a "Fail-open fallback" message | Ollama isn't reachable — check `ollama serve` is running and `SCR_OLLAMA_URL`/`SCR_OLLAMA_MODEL` in `.env` are correct |
| `401 Unauthorized` triggering a scan or submitting a review | Missing/incorrect API key in the dashboard's sidebar field, or wrong `X-API-Key` header if using `curl` |
| `libodbc.so.2: cannot open shared object file` (Linux, SQL Server only) | `sudo apt-get install -y unixodbc` plus Microsoft's `msodbcsql18` package |
