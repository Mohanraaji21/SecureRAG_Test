# How It Works — End-to-End Data Flow

This walks through exactly what happens for one scan, from the API call
to a reviewer closing the loop, with report-section references and the
specific file/function responsible for each step.

## 1. A scan is triggered

```
POST /scans
{ "repo_path": "/path/to/checked/out/repo", "repo_name": "org/repo", "pr_number": 42 }
Header: X-API-Key: <your key>
```

**`api/routers/scans.py::create_scan`**
1. `require_api_key` dependency checks the header.
2. A `ScanRunORM` row is created with `Status="pending"` and committed —
   so the client gets a `scan_run_id` back immediately.
3. `background_tasks.add_task(run_scan_and_persist, ...)` schedules the
   real work to run *after* the HTTP response is sent.

The client can poll `GET /scans/{id}` from this point on to watch
`Status` move from `pending → running → completed` (or `failed`).

## 2. The background task runs the AI core pipeline

**`api/services/scan_service.py::run_scan_and_persist`**

1. Opens its own DB session (background tasks outlive the request's session).
2. Sets `Status="running"`.
3. Calls `get_pipeline()` — a cached `TriagePipeline` (report Tier 1):
   - `SentenceTransformerEmbedder` loads the embedding model (first call only).
   - `KnowledgeIndex.build()` embeds every item in `data/cwe_seed.json` into a FAISS `IndexFlatIP`.
   - `OllamaClient` is constructed (no network call yet — just config).
4. Calls `run_semgrep(repo_path, config)` → **`core/sast/semgrep_runner.py`**:
   - Shells out to `semgrep --json --config auto <repo_path>`.
   - Parses each result into a `Finding` (file, line, rule_id, CWE id,
     severity, message, code snippet). *(Report §4.2.1.)*

## 3. Each finding is adjudicated independently

**`core/pipeline.py::TriagePipeline.run_on_findings`** loops over
findings, calling `process_finding` for each one — deliberately **not** a
single batched LLM call, per report §4.6's "per-finding, not monolithic,
processing" principle. One bad finding can't corrupt another's verdict.

For each `Finding`, `process_finding` does:

**a) Retrieval — `core/retrieval/faiss_index.py::KnowledgeIndex.query`**
- Builds a combined query string: the finding's message + CWE id + code
  snippet (report §4.2.2: "combined query of code content and extracted
  functional semantics").
- Embeds it, searches the FAISS index, over-fetches candidates, then
  **filters to only knowledge items tagged with the same CWE id** as the
  finding (report §4.6: CWE-specific, knowledge-level retrieval) —
  returning the top-k as `RetrievedEvidence` (source label, knowledge
  item id, similarity score).

**b) Adjudication — `core/adjudication/ollama_client.py::OllamaClient.adjudicate`**
- `core/adjudication/prompts.py::build_adjudication_prompt` fills the
  Appendix A.1 template with the finding, its CWE, and the retrieved
  evidence text.
- POSTs to Ollama's `/api/generate` with `format: "json"` and low
  temperature (0.1, for adjudication consistency).
- Parses the response: strict `json.loads` first, then a regex fallback
  that extracts the first `{...}` block if the model wrapped its answer in
  prose despite instructions.
- **Fail-open (report §4.6):** if the HTTP call fails/times out, or the
  response can't be parsed into valid JSON, `adjudicate()` returns a
  `Verdict` with `verdict="needs_review"`, `raw_confidence=0.0`,
  `fail_open=True`, and a justification explaining why — **the finding is
  never silently dropped.**

**c) Calibration — `core/calibration/temperature_scaling.py::TemperatureScaler.calibrate`**
- Converts the LLM's raw confidence to a calibrated confidence via the
  fitted temperature (or passes through unchanged if no temperature has
  been fitted yet — see step 6).

**d) Orchestration-level fail-open — `core/pipeline.py`**
- The entire a–c sequence is wrapped in a `try/except` in
  `process_finding`; any unexpected exception (not just LLM/network
  errors) also degrades to a `needs_review` verdict rather than crashing
  the whole scan or silently omitting a finding.

## 4. Results are persisted

Back in **`run_scan_and_persist`**, for every `(Finding, Verdict)` pair:
- A `FindingORM` row is created (`Findings` table) — including the raw
  Semgrep fields plus `RawVerdict` (the verdict label, for quick filtering
  without a join).
- A `VerdictORM` row is created (`Verdicts` table), linked via
  `FindingId` — `CalibratedConfidence`, `Justification`,
  `CitedEvidenceJson` (a JSON-encoded list of which knowledge item(s)
  drove the decision — report §3.2.2's "retrieval-attribution-aware
  explanation").

On success, `ScanRunORM.Status` becomes `"completed"` and `CompletedAt` is
set. On any exception during this whole process, the transaction is
rolled back and `Status` becomes `"failed"` with `ErrorMessage` populated
— so a crash never leaves a scan silently stuck at `"running"` forever.

## 5. A developer reviews the confidence-ranked findings

```
GET /findings?scan_id=<id>&min_confidence=0.7
```

**`api/routers/findings.py::list_findings`** joins each `Finding` to its
`Verdict`, optionally filters by `scan_id`/`cwe_id`/`min_confidence`, and
sorts by `CalibratedConfidence` descending (unadjudicated findings sort
last) — this is the "confidence-ranked findings" dashboard data described
in report §4.2.5.

Each `FindingOut` includes the nested `VerdictOut`, which includes
`Justification` and (via `CitedEvidenceJson`, decoded on read) which
retrieved CWE definition or fix pattern the LLM cited — the
developer-facing trust signal from report §3.2.2.

## 6. Reviewer feedback closes the loop

```
POST /verdicts/{verdict_id}/review
{ "reviewer_id": "alice", "decision": "confirmed" }
```

**`api/routers/verdicts.py::submit_review`** creates a
`ReviewerDecisionORM` row (`confirmed` / `overruled` / `unsure`). This is
the human-feedback capture from report §1.1.5/§4.2.4, "stores that
feedback for future calibration refinement."

### Using that feedback

- **Immediately:** `GET /metrics/calibration` (`api/routers/metrics.py`)
  treats `confirmed` decisions as "the verdict was correct" and
  `overruled` as "the verdict was wrong," and computes
  `expected_calibration_error` + a reliability-diagram breakdown
  (`core/calibration/metrics.py`) over all reviewed verdicts — this is
  Figure 5.2's methodology, now computed from real (once you have
  reviews) rather than illustrative data.
- **Periodically (manual step, not automated in Phase 2):** export
  `(raw_confidence, was_correct)` pairs from reviewed verdicts and call
  `TemperatureScaler().fit(...)` (see `README.md`) to refit the
  temperature parameter as more labeled data accumulates, then update
  `get_pipeline()` in `api/services/scan_service.py` to load the fitted
  scaler instead of constructing a fresh (identity) one. This refit loop
  is intentionally left as a manual/scriptable step rather than fully
  automated — matching the case study's scope (report §5.6 doesn't list
  automated online calibration as in-scope).

## Summary diagram

```
POST /scans ──► ScanRunORM(pending) ──► [background task starts]
                                              │
                                    run_semgrep(repo_path)
                                              │
                                     [Finding, Finding, ...]
                                              │
                         for each Finding (independently):
                              │
                    KnowledgeIndex.query()  ──► RetrievedEvidence[]
                              │
                    OllamaClient.adjudicate() ──► Verdict (fail-open on any failure)
                              │
                    TemperatureScaler.calibrate() ──► calibrated_confidence
                              │
                    FindingORM + VerdictORM persisted
                                              │
                                   ScanRunORM.Status = completed
                                              │
GET /findings?scan_id=... ◄── confidence-ranked list with cited evidence
                                              │
POST /verdicts/{id}/review ──► ReviewerDecisionORM
                                              │
GET /metrics/calibration ◄── ECE + reliability diagram from reviewed verdicts
```
