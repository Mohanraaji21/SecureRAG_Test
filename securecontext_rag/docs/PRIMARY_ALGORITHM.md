# SecureContext-RAG — The Primary Algorithm

This document explains, in depth, the actual algorithm the system runs —
not just what each module does, but *how* it does it: the math, the
control flow, the decision rules, and why each choice was made. If
`HOW_IT_WORKS.md` (from the codebase docs) is the map, this is the engine
manual.

---

## 1. The algorithm in one sentence

For every candidate finding a static analyzer produces, retrieve the
most relevant piece of security knowledge for that finding's specific
vulnerability class, ask a language model to judge the finding *using
that retrieved knowledge as grounding*, and then correct the model's own
stated confidence so that it actually means what it says — all while
guaranteeing that no finding is ever silently discarded, even when a step
fails.

That's four algorithms chained together, run independently per finding:

```
Finding ──► [Retrieval] ──► [Prompt Construction] ──► [LLM Adjudication] ──► [Calibration] ──► Verdict
                                                              │
                                                     (any failure here)
                                                              ▼
                                                    fail-open "needs_review"
```

The rest of this document walks through each stage in detail, in the
order data actually flows through the code.

---

## 2. Stage 0 — Candidate Generation (Semgrep)

**What it is:** not itself a novel algorithm — Semgrep is an existing
pattern-matching static analyzer — but it's the algorithm's *input
source*, so its output shape matters.

**What happens:** Semgrep runs its rule engine (AST pattern matching
against a rule registry) over the target repository and emits a JSON
array of matches. Each match is parsed into a `Finding`:

```
Finding = {
  rule_id, cwe_id, file_path, line, end_line,
  severity, message, code_snippet
}
```

**Key algorithmic detail — CWE extraction:** Semgrep rules attach CWE
metadata inconsistently (sometimes a list, sometimes a string, sometimes
absent). The parser normalizes this:
```
cwe_raw = result.extra.metadata.cwe
if cwe_raw is a list: cwe_raw = cwe_raw[0] if non-empty else None
cwe_id = cwe_raw.split(":")[0].strip()   # "CWE-89: SQL Injection" -> "CWE-89"
```
This normalized `cwe_id` is the single most important field for
everything downstream — it's the key the retrieval algorithm filters on.

Findings with no `cwe_id` still flow through the pipeline; retrieval
simply falls back to unfiltered similarity search for them (see §3.3).

---

## 3. Stage 1 — Retrieval Algorithm (Knowledge-Level RAG)

This is the first of the two genuinely algorithmic stages. The design
choice it embodies — **retrieve distilled knowledge, not raw code, and
filter by CWE before ranking** — is the system's core novelty relative to
naive RAG-for-code approaches.

### 3.1 The knowledge base

A knowledge base is a flat list of `KnowledgeItem`s:
```
KnowledgeItem = { item_id, cwe_id, kind, title, text }
```
where `kind` is either `cwe_definition` (what the vulnerability class
*is*) or `vuln_fix_pair` (a concrete before/after code pattern showing
how a specific instance was fixed). Both are indexed identically — the
distinction is metadata for the LLM's benefit, not a structural
difference in the algorithm.

### 3.2 Building the index

Each item is embedded and inserted into a FAISS flat index:

```
for item in knowledge_base:
    text_to_embed = f"{item.title}. {item.text}"
    vector[item] = embedder.encode(text_to_embed)    # e.g. 384-dim for MiniLM

index = FAISS.IndexFlatIP(dimension)                  # Inner-Product index
index.add(all_vectors)
```

**Why inner product, and why it equals cosine similarity here:** the
embedder is called with `normalize_embeddings=True`, so every vector has
unit length (‖v‖ = 1). For unit vectors, the dot product *is* the cosine
similarity:
```
cos(a, b) = (a · b) / (‖a‖ ‖b‖) = a · b        when ‖a‖ = ‖b‖ = 1
```
So `IndexFlatIP` — which is just brute-force dot-product search — gives
exact cosine-similarity ranking without needing a separate normalization
step at query time, as long as query vectors are also normalized (they
are, using the same embedder call).

`IndexFlatIP` is exhaustive (O(n) per query, comparing against every
stored vector) rather than an approximate index (e.g. HNSW/IVF). This is
a deliberate choice: the knowledge base is small (tens to low hundreds of
items, not millions), so exact search is both fast enough and removes an
entire class of approximate-nearest-neighbor tuning risk. This would need
revisiting if the knowledge base grew into the tens of thousands of items.

### 3.3 The query algorithm — this is the important part

Retrieval is **not** "embed the code snippet and find nearest
neighbors." It's a two-stage algorithm: *combined-query embedding* +
*post-hoc CWE filtering*.

**Step A — Combined query construction.** The query text deliberately
fuses three signals, not just raw code:
```
query_text = f"{finding.message} CWE:{finding.cwe_id}\n{finding.code_snippet}"
```
This matters because raw code snippets are often too short, too
syntax-specific, or too idiomatic to embed meaningfully close to a
*conceptual* knowledge-base entry written in prose. Prepending the
human-readable rule message and the CWE tag gives the embedder semantic
anchors that a bare code fragment lacks.

**Step B — Over-fetch, then filter (not filter-then-rank).**
```
k_search = min(top_k * 5, len(knowledge_base))     # over-fetch by 5x
scores, indices = index.search(query_vector, k_search)

results = []
for score, idx in zip(scores, indices):
    item = knowledge_base[idx]
    if finding.cwe_id and item.cwe_id != finding.cwe_id:
        continue                                     # reject: wrong CWE
    results.append(RetrievedEvidence(item, score))
    if len(results) == top_k:
        break
return results
```
**Why over-fetch instead of a true metadata-filtered vector search:**
FAISS's flat index has no native attribute filtering — it only ranks by
similarity. If the top-K nearest neighbors by embedding similarity happen
to belong to unrelated CWEs (which happens: a "hardcoded secret" snippet
can be embedding-close to a "weak crypto" snippet because both mention
keys/passwords), a naive top-K-then-filter would return too few or zero
CWE-correct results. Over-fetching 5x the requested count before
filtering makes it very likely enough same-CWE candidates exist in the
larger pool, at the cost of a slightly larger but still trivial search.

**Step C — Graceful degradation.** If `finding.cwe_id` is `None` (Semgrep
didn't provide one), the `if` condition never rejects anything — the
algorithm silently degrades to unfiltered top-K similarity search rather
than returning nothing. This is a deliberate fallback, not an oversight.

### 3.4 Complexity

For a knowledge base of size *n*, embedding dimension *d*, and request
for top-*k* evidence: embedding the query is O(model inference, ~constant
per call); the FAISS search is O(n·d) (brute-force dot product against
every stored vector); the filter loop is O(5k). Total: dominated by O(n·d),
which is why this only stays cheap while *n* stays small (§3.2).

---

## 4. Stage 2 — Adjudication Algorithm (CWE-Specific Prompting + Robust Parsing)

### 4.1 Prompt construction algorithm

The prompt is built deterministically from four inputs: the finding, its
CWE id, the single most-relevant retrieved definition, and the full list
of retrieved fix-pattern texts:

```
cwe_name = CWE_NAME_LOOKUP.get(finding.cwe_id, finding.cwe_id)
retrieved_definition = evidence_texts[evidence[0].knowledge_item_id]  if evidence else ""
retrieved_fix_block  = "\n".join(f"- {evidence_texts[e.knowledge_item_id]}" for e in evidence)

prompt = TEMPLATE.format(
    cwe_id=finding.cwe_id, cwe_name=cwe_name,
    message=finding.message, file=finding.file_path, line=finding.line,
    code=finding.code_snippet,
    retrieved_definition=retrieved_definition,
    retrieved_fix_block=retrieved_fix_block,
)
```

The template explicitly frames the model as *"a security code reviewer
specializing in {cwe_id} ({cwe_name})"* — this is the CWE-specific (as
opposed to generic vulnerability-reviewer) prompting strategy. The model
is instructed to output **only** a JSON object matching a fixed schema:
```json
{ "verdict": "true_positive" | "false_positive" | "needs_review",
  "raw_confidence": <float 0-1>,
  "justification": "<string>",
  "cited_evidence_id": "<knowledge_item_id or empty string>" }
```

The LLM call itself uses `temperature=0.1` (near-deterministic decoding)
and Ollama's `format: "json"` constrained-generation mode — both chosen
to minimize the rate of malformed output before the parsing algorithm
below even has to run.

### 4.2 Robust structured-output parsing algorithm

LLMs, even when instructed and constrained, occasionally wrap their JSON
in prose or markdown fences. The parser handles this with a two-attempt
algorithm:

```
def parse_llm_json(raw_text):
    raw_text = raw_text.strip()
    try:
        return json.loads(raw_text)                      # attempt 1: strict
    except JSONDecodeError:
        pass

    match = regex.search(r'\{.*\}', raw_text, DOTALL)      # attempt 2: extract
    if match:
        try:
            return json.loads(match.group(0))
        except JSONDecodeError:
            return None
    return None
```

Attempt 1 is the fast path for well-behaved output. Attempt 2 is a greedy
regex that finds the first `{` through the last `}` in the response and
retries parsing just that substring — this recovers cases like
`"Here's my answer:\n{...}\nHope that helps!"`. If both attempts fail,
the function returns `None`, which the caller treats as an unconditional
trigger for fail-open behavior (§4.3) — there is no third attempt or
best-effort partial parse, by design: a partially-recovered verdict is
worse than an honest "I couldn't adjudicate this."

### 4.3 The fail-open decision algorithm

This is arguably the single most important control-flow rule in the
system. `adjudicate()` is structured so that **every possible failure
path converges on the same safe output**, never an exception and never a
dropped finding:

```
def adjudicate(finding, evidence, evidence_texts):
    prompt = build_prompt(finding, evidence, evidence_texts)

    try:
        raw_text = call_llm(prompt)
    except (HTTPError, TimeoutException) as e:
        return fail_open_verdict(finding, reason=f"LLM call failed: {e}")   # path 1

    parsed = parse_llm_json(raw_text)
    if parsed is None:
        return fail_open_verdict(finding, reason="malformed JSON output")     # path 2

    verdict_label = try_parse_enum(parsed.get("verdict"), default=NEEDS_REVIEW)  # path 3 (silent degrade)
    raw_confidence = clamp(try_parse_float(parsed.get("raw_confidence"), default=0.5), 0.0, 1.0)

    return Verdict(verdict=verdict_label, raw_confidence=raw_confidence, ...)     # normal path
```

where:
```
def fail_open_verdict(finding, reason):
    return Verdict(
        verdict = NEEDS_REVIEW,
        raw_confidence = 0.0,
        justification = f"Fail-open fallback: {reason}. Routed to manual review.",
        fail_open = True,
    )
```

Notice the asymmetry: a *network/infrastructure* failure (path 1) and a
*malformed-output* failure (path 2) both hard-fail to `needs_review`
immediately. But an *unrecognized verdict string* or *unparseable
confidence number* (path 3) — where the JSON itself was valid, just one
field was off-schema — degrades that one field only (to `needs_review` /
`0.5` respectively) rather than discarding the whole response, since the
`justification` and `cited_evidence` are often still usable even if
`verdict` was mistyped.

**A second, outer fail-open layer** wraps this whole function call inside
`TriagePipeline.process_finding` (§6), so even a bug in the orchestration
code itself — not just LLM/parsing failures — still degrades to
`needs_review` rather than crashing the batch. This is intentional
defense in depth: two independent layers, each catching a different class
of failure, both converging on the same safe default.

---

## 5. Stage 3 — Calibration Algorithm (Temperature Scaling)

This is the second genuinely algorithmic stage, and the system's core
evaluation novelty: LLMs are known to be systematically overconfident,
and this stage corrects for that with a principled, fittable
transformation rather than an ad-hoc discount.

### 5.1 The mathematical model

Treat the LLM's `raw_confidence` p ∈ (0, 1) as an implied probability of
being correct. Temperature scaling assumes the model's *true* calibration
error is a single global miscalibration in logit space, correctable by
one scalar parameter *T* > 0:

**Step 1 — convert probability to logit** (inverse sigmoid):
```
logit(p) = ln( p / (1 − p) )
```

**Step 2 — divide by temperature:**
```
z' = logit(p) / T
```

**Step 3 — convert back to a probability** (sigmoid):
```
calibrated(p) = σ(z') = 1 / (1 + e^(−z'))
```

**Interpretation of T:**
- `T = 1` → identity transform, no correction (used before any fitting
  has happened — see §5.3).
- `T > 1` → *flattens* the logit toward 0, pulling all probabilities
  toward 0.5. This is what happens to an **overconfident** model: its
  extreme 0.95's and 0.02's get pulled toward the middle, closer to its
  true (lower) discriminative power.
- `T < 1` → *sharpens* the logit away from 0, pushing probabilities
  toward 0 or 1. This would correct an **underconfident** model.

### 5.2 Fitting T — Maximum Likelihood via Negative Log-Likelihood minimization

Given a validation set of *(raw_confidence, was_correct)* pairs, the
algorithm finds the single T that makes the calibrated confidences best
predict actual correctness, by minimizing binary cross-entropy (NLL):

```
NLL(T) = − (1/N) Σ [ yᵢ · ln(σ(logit(pᵢ)/T)) + (1 − yᵢ) · ln(1 − σ(logit(pᵢ)/T)) ]
```
where `yᵢ ∈ {0, 1}` is whether verdict *i* was actually correct (from
reviewer feedback) and `pᵢ` is that verdict's raw confidence.

This is a **one-dimensional, smooth, unimodal-in-practice** optimization
problem, so the implementation uses `scipy.optimize.minimize_scalar` with
`method="bounded"` over `T ∈ [0.01, 50.0]` — bounded rather than
unconstrained because T ≤ 0 is undefined (division by zero or negative
logit flip) and extremely large T values have negligible practical
difference from T = 50 (everything collapses toward 0.5 anyway).

```
def fit(raw_confidences, correct):
    logits = logit(raw_confidences)
    def nll(T):
        if T <= 1e-3: return inf
        probs = clip(sigmoid(logits / T), eps, 1 - eps)   # clip avoids log(0)
        return -mean(correct*log(probs) + (1-correct)*log(1-probs))
    result = minimize_scalar(nll, bounds=(0.01, 50.0), method="bounded")
    self.temperature = result.x
```

### 5.3 Why identity-by-default matters algorithmically

`TemperatureScaler()` initializes `T = 1.0` and only changes after an
explicit `.fit()` call. This means the calibration stage is a **no-op
pass-through** until enough reviewer-labeled data exists to fit it
meaningfully — the pipeline is fully functional (just uncalibrated) from
day one, and calibration quality only ever improves monotonically as more
reviewer feedback accumulates. There is no "cold start failure" state.

### 5.4 The Expected Calibration Error (ECE) algorithm

ECE is the metric used to *measure* how well-calibrated the (possibly
just-fitted) confidences are — it's the evaluation counterpart to the
temperature-scaling correction above. Binned ECE algorithm:

```
def ECE(confidences, correct, n_bins=10):
    bin_edges = linspace(0, 1, n_bins + 1)          # e.g. [0, .1, .2, ..., 1.0]
    ece = 0
    for (lo, hi) in consecutive_pairs(bin_edges):
        in_bin = (confidences > lo) & (confidences <= hi)
        if lo == 0: in_bin |= (confidences == 0)      # include exact 0.0 in first bin
        count = sum(in_bin)
        if count == 0: continue
        bin_confidence = mean(confidences[in_bin])     # avg predicted confidence in this bin
        bin_accuracy   = mean(correct[in_bin])          # actual fraction correct in this bin
        ece += (count / N) * |bin_confidence − bin_accuracy|
    return ece
```

**Intuition:** partition predictions into 10 confidence buckets. A
perfectly calibrated model has, within each bucket, average confidence ≈
actual accuracy (e.g. among all verdicts the model said it was "85%
confident" about, roughly 85% should be right). ECE is the
sample-weighted average gap between confidence and accuracy across all
buckets — 0 is perfect, larger values indicate worse
over/under-confidence.

---

## 6. Stage 4 — The Master Orchestration Algorithm

Everything above is composed per-finding by `TriagePipeline`, with three
layers of fault isolation:

```
def process_finding(finding):                              # LAYER 3: outer guard
    try:
        evidence = knowledge_index.query(finding, top_k=3)     # Stage 1
        evidence_texts = {e.id: knowledge_index.get_text(e.id) for e in evidence}

        verdict = llm_client.adjudicate(finding, evidence, evidence_texts)  # Stage 2
                                                                # (LAYER 2 fail-open is INSIDE adjudicate())

        verdict.calibrated_confidence = calibrator.calibrate(verdict.raw_confidence)  # Stage 3
        return verdict

    except Exception:                                        # catches anything Stage 1/3 might raise,
        return fail_open_verdict(finding, reason="unexpected pipeline error")  # or a bug in orchestration itself
```

```
def run_on_findings(findings):                              # LAYER 1: independence guarantee
    return [process_finding(f) for f in findings]              # each finding is a fully separate call —
                                                                # no shared mutable state, no early-exit-on-error
```

**Why three layers, not one try/except around everything:**
- **Layer 1** (the loop in `run_on_findings`) guarantees findings are
  processed *independently* — a Python-level exception in finding #3
  can't prevent findings #4 through #N from being processed, because
  there's no shared control flow between iterations beyond the list
  comprehension itself.
- **Layer 2** (inside `adjudicate()`, §4.3) handles the *expected,
  anticipated* failure modes specific to talking to an LLM: network
  errors, timeouts, malformed JSON. These get specific, informative
  `justification` messages naming the exact cause.
- **Layer 3** (the outer `try/except` in `process_finding`) is a
  catch-all for *anything else* — a bug in retrieval, a schema mismatch,
  an out-of-memory error in the embedder, anything unforeseen. It
  guarantees the *function's contract* ("always returns a Verdict, never
  raises") holds even for failure modes the implementation didn't
  specifically anticipate.

This three-layer structure is what makes the report's "fail-open safety"
principle (§4.6) actually airtight rather than just handling the obvious
cases.

---

## 7. Worked numeric example

To make §5's math concrete, here's an actual run through the numbers.

**Setup:** Ten reviewed verdicts came back from the LLM all at
`raw_confidence = 0.95`, but only 6 of them were actually confirmed
correct by reviewers (60% true accuracy) — a classic overconfidence
pattern.

**Fitting T:**
- `logit(0.95) = ln(0.95/0.05) = ln(19) ≈ 2.944`
- The optimizer searches for T minimizing NLL given `yᵢ` = [1,1,1,1,1,1,0,0,0,0]
  (in some order) and this fixed logit for all ten. Solving numerically
  lands at approximately **T ≈ 7.2** for this data (the exact value
  depends on the optimizer's convergence, but this magnitude is
  representative of the unit test in `tests/test_calibration.py`, which
  asserts T > 1 and the calibrated value lands within 0.08 of the true
  0.6 rate).

**Applying it:**
- `z' = 2.944 / 7.2 ≈ 0.409`
- `calibrated = σ(0.409) = 1 / (1 + e^(−0.409)) ≈ 0.601`

So a raw 0.95 confidence gets corrected down to ≈0.60 — matching the
observed 60% true accuracy almost exactly. This is temperature scaling
doing its job: it learned that *this particular pattern of raw
confidence* (0.95 on this class of finding) historically corresponds to
being right about 60% of the time, and adjusts future 0.95's accordingly.

**ECE before vs. after, on this same batch:**
- *Before calibration* (using raw 0.95 directly as the confidence):
  all ten predictions fall in the [0.9, 1.0] bin, average confidence
  0.95, average accuracy 0.60 → `ECE = 1.0 × |0.95 − 0.60| = 0.35`.
- *After calibration* (using the corrected ≈0.60):
  all ten predictions fall in the [0.5, 0.6] or [0.6, 0.7] bin (depending
  on exact rounding), average confidence ≈0.60, average accuracy 0.60 →
  `ECE ≈ 1.0 × |0.60 − 0.60| ≈ 0.0`.

This is exactly the behavior `tests/test_calibration.py::test_ece_detects_overconfidence`
and `test_fit_reduces_overconfidence` assert programmatically.

---

## 8. Why this specific algorithm, not alternatives (design rationale)

| Choice made | Alternative considered | Why this one |
|---|---|---|
| Exact flat FAISS index (`IndexFlatIP`) | Approximate index (HNSW, IVF) | Knowledge base is small; exact search is fast enough and avoids ANN recall-tuning risk |
| Over-fetch-then-filter for CWE matching | A vector DB with native metadata filtering | FAISS has no built-in filtering; over-fetching is a simple, effective workaround at this scale |
| Combined query (message + CWE + code) | Embedding raw code snippet only | Vul-RAG's finding (cited in the report) that knowledge-level retrieval beats code-level; bare code embeds poorly against prose knowledge |
| Temperature scaling (1 global parameter) | Per-CWE temperatures, Platt scaling, conformal prediction | Simplest model that still corrects systematic overconfidence; needs the least labeled data to fit reliably; conformal prediction explicitly noted in the report as a future fallback if this proves too coarse |
| Three-layer fail-open | Single top-level try/except | Each layer catches a functionally different failure class with a different appropriate response/message; collapsing to one layer would lose the specific, actionable `justification` text |
| Per-finding processing (not batched) | One LLM call with all findings in one prompt | Isolates failures to a single finding; keeps prompts small and focused (better adjudication quality per finding); trades off total LLM call count for reliability and precision |

---

## 9. Where this lives in the code

| Algorithm stage | File | Function/class |
|---|---|---|
| Candidate generation | `core/sast/semgrep_runner.py` | `run_semgrep`, `parse_semgrep_json` |
| Retrieval | `core/retrieval/faiss_index.py` | `KnowledgeIndex.build`, `KnowledgeIndex.query` |
| Prompt construction | `core/adjudication/prompts.py` | `build_adjudication_prompt` |
| LLM call + parsing + fail-open | `core/adjudication/ollama_client.py` | `OllamaClient.adjudicate`, `_parse_llm_json`, `_fail_open_verdict` |
| Calibration fitting | `core/calibration/temperature_scaling.py` | `TemperatureScaler.fit`, `.calibrate` |
| ECE / reliability diagram | `core/calibration/metrics.py` | `expected_calibration_error`, `reliability_diagram_data` |
| Master orchestration | `core/pipeline.py` | `TriagePipeline.process_finding`, `.run_on_findings` |
