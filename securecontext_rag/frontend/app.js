/* SecureContext-RAG dashboard — vanilla JS, talks directly to the FastAPI
 * backend's JSON endpoints. No build step, no framework: this file is
 * served as-is by FastAPI's StaticFiles mount (see api/main.py).
 */

const API_BASE = ""; // same origin as the page

const state = {
  scans: [],
  findings: [],
  pendingReviewVerdictId: null,
};

// ---------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------
function apiKey() {
  return document.getElementById("apiKey").value.trim();
}

async function api(path, { method = "GET", body, auth = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) headers["X-API-Key"] = apiKey();

  const res = await fetch(API_BASE + path, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });

  if (!res.ok) {
    let detail = res.statusText;
    try {
      const err = await res.json();
      detail = err.detail || JSON.stringify(err);
    } catch (_) {}
    throw new Error(`${res.status}: ${detail}`);
  }
  if (res.status === 204) return null;
  return res.json();
}

// ---------------------------------------------------------------------
// Toast
// ---------------------------------------------------------------------
let toastTimer = null;
function showToast(message, isError = false) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.style.borderColor = isError ? "var(--bad)" : "var(--border)";
  el.classList.add("is-visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("is-visible"), 3500);
}

// ---------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------
function switchView(viewName) {
  document.querySelectorAll(".nav-item").forEach((btn) => {
    btn.classList.toggle("is-active", btn.dataset.view === viewName);
  });
  document.querySelectorAll(".view").forEach((section) => {
    section.classList.toggle("is-active", section.id === `view-${viewName}`);
  });
  if (viewName === "scans") loadScans();
  if (viewName === "findings") loadFindings();
  if (viewName === "metrics") loadMetrics();
}

document.querySelectorAll(".nav-item").forEach((btn) => {
  btn.addEventListener("click", () => switchView(btn.dataset.view));
});

// ---------------------------------------------------------------------
// Connection check
// ---------------------------------------------------------------------
async function checkConnection() {
  const el = document.getElementById("connStatus");
  try {
    await api("/health");
    el.textContent = "● connected";
    el.className = "conn-status ok";
  } catch (e) {
    el.textContent = "● unreachable";
    el.className = "conn-status bad";
  }
}

// ---------------------------------------------------------------------
// Scans view
// ---------------------------------------------------------------------
const STATUS_LABEL = { pending: "pending", running: "running", completed: "completed", failed: "failed" };

function formatTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

async function loadScans() {
  const table = document.getElementById("scansTable");
  try {
    state.scans = await api("/scans");
  } catch (e) {
    showToast(`Could not load scans: ${e.message}`, true);
    return;
  }

  const rows = state.scans
    .map(
      (s) => `
      <div class="table-row">
        <div>${escapeHtml(s.RepoName)}</div>
        <div>${s.PRNumber ?? "—"}</div>
        <div><span class="status-pill status-${s.Status}">${STATUS_LABEL[s.Status] || s.Status}</span></div>
        <div>${formatTime(s.TriggeredAt)}</div>
        <div><button class="btn-ghost" data-scan-id="${s.Id}" data-action="view-scan">View</button></div>
      </div>`
    )
    .join("");

  table.innerHTML =
    `<div class="table-row table-head"><div>Repo</div><div>PR</div><div>Status</div><div>Triggered</div><div></div></div>` +
    (rows || `<div class="table-empty">No scans yet — trigger one above.</div>`);

  table.querySelectorAll('[data-action="view-scan"]').forEach((btn) => {
    btn.addEventListener("click", () => {
      document.getElementById("filterScan").value = btn.dataset.scanId;
      switchView("findings");
    });
  });

  // Keep the findings-filter scan dropdown in sync
  const sel = document.getElementById("filterScan");
  const current = sel.value;
  sel.innerHTML =
    `<option value="">All scans</option>` +
    state.scans.map((s) => `<option value="${s.Id}">${escapeHtml(s.RepoName)} (${s.Status})</option>`).join("");
  sel.value = current;
}

document.getElementById("refreshScans").addEventListener("click", loadScans);

document.getElementById("triggerForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  const repo_path = document.getElementById("repoPath").value.trim();
  const repo_name = document.getElementById("repoName").value.trim();
  const prRaw = document.getElementById("prNumber").value.trim();

  if (!apiKey()) {
    showToast("Enter your API key in the sidebar first.", true);
    return;
  }

  try {
    await api("/scans", {
      method: "POST",
      auth: true,
      body: {
        repo_path,
        repo_name,
        pr_number: prRaw ? parseInt(prRaw, 10) : null,
      },
    });
    showToast("Scan triggered — running in the background.");
    document.getElementById("triggerForm").reset();
    loadScans();
  } catch (err) {
    showToast(`Could not trigger scan: ${err.message}`, true);
  }
});

// ---------------------------------------------------------------------
// Findings view
// ---------------------------------------------------------------------
function escapeHtml(str) {
  if (str == null) return "";
  return String(str).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

async function loadFindings() {
  const scanId = document.getElementById("filterScan").value;
  const minConf = document.getElementById("filterConfidence").value;
  const cwe = document.getElementById("filterCwe").value.trim();

  const params = new URLSearchParams();
  if (scanId) params.set("scan_id", scanId);
  if (minConf) params.set("min_confidence", minConf);
  if (cwe) params.set("cwe_id", cwe);

  const list = document.getElementById("findingsList");
  try {
    state.findings = await api(`/findings?${params.toString()}`);
  } catch (e) {
    showToast(`Could not load findings: ${e.message}`, true);
    return;
  }

  if (!state.findings.length) {
    list.innerHTML = `<div class="table-empty">No findings match these filters yet.</div>`;
    return;
  }

  list.innerHTML = state.findings
    .map((f) => {
      const v = f.verdict;
      const confPct = v && v.CalibratedConfidence != null ? Math.round(v.CalibratedConfidence * 100) : null;
      return `
      <div class="finding-row">
        <div class="finding-top">
          <div>
            <p class="finding-title">${escapeHtml(f.Message)}</p>
            <div class="finding-loc">${escapeHtml(f.FilePath)}:${f.Line} · ${escapeHtml(f.CweId || "no CWE")} · ${escapeHtml(f.RuleId)}</div>
          </div>
          ${v ? `<span class="verdict-badge verdict-${v.Verdict}">${v.Verdict.replace("_", " ")}</span>` : `<span class="verdict-badge verdict-needs_review">unadjudicated</span>`}
        </div>
        ${
          confPct != null
            ? `<div class="confidence-bar-track"><div class="confidence-bar-fill" style="width:${confPct}%"></div></div>
               <div class="finding-loc">Calibrated confidence: ${confPct}%${v.FailOpen ? " · fail-open" : ""}</div>`
            : ""
        }
        ${v && v.Justification ? `<p class="finding-justification">${escapeHtml(v.Justification)}</p>` : ""}
        <pre class="finding-code">${escapeHtml(f.CodeSnippet)}</pre>
        <div class="finding-actions">
          ${v ? `<button class="btn-ghost" data-action="review" data-verdict-id="${v.Id}" data-summary="${escapeHtml(f.FilePath)}:${f.Line}">Review verdict</button>` : ""}
        </div>
      </div>`;
    })
    .join("");

  list.querySelectorAll('[data-action="review"]').forEach((btn) => {
    btn.addEventListener("click", () => openReviewModal(btn.dataset.verdictId, btn.dataset.summary));
  });
}

document.getElementById("applyFilters").addEventListener("click", loadFindings);

// ---------------------------------------------------------------------
// Review modal
// ---------------------------------------------------------------------
let selectedDecision = null;

function openReviewModal(verdictId, summary) {
  state.pendingReviewVerdictId = verdictId;
  selectedDecision = null;
  document.getElementById("reviewFindingSummary").textContent = summary;
  document.getElementById("reviewerId").value = "";
  document.getElementById("reviewNote").value = "";
  document.querySelectorAll(".decision-btn").forEach((b) => b.classList.remove("is-selected"));
  document.getElementById("reviewBackdrop").classList.add("is-open");
}

function closeReviewModal() {
  document.getElementById("reviewBackdrop").classList.remove("is-open");
}

document.getElementById("closeReview").addEventListener("click", closeReviewModal);
document.getElementById("reviewBackdrop").addEventListener("click", (e) => {
  if (e.target.id === "reviewBackdrop") closeReviewModal();
});

document.querySelectorAll(".decision-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    selectedDecision = btn.dataset.decision;
    document.querySelectorAll(".decision-btn").forEach((b) => b.classList.remove("is-selected"));
    btn.classList.add("is-selected");
  });
});

document.getElementById("submitReview").addEventListener("click", async () => {
  if (!apiKey()) {
    showToast("Enter your API key in the sidebar first.", true);
    return;
  }
  if (!selectedDecision) {
    showToast("Pick a decision first.", true);
    return;
  }
  const reviewerId = document.getElementById("reviewerId").value.trim() || "anonymous";
  const note = document.getElementById("reviewNote").value.trim() || null;

  try {
    await api(`/verdicts/${state.pendingReviewVerdictId}/review`, {
      method: "POST",
      auth: true,
      body: { reviewer_id: reviewerId, decision: selectedDecision, note },
    });
    showToast("Review submitted.");
    closeReviewModal();
    loadFindings();
  } catch (err) {
    showToast(`Could not submit review: ${err.message}`, true);
  }
});

// ---------------------------------------------------------------------
// Metrics view
// ---------------------------------------------------------------------
async function loadMetrics() {
  let data;
  try {
    data = await api("/metrics/calibration");
  } catch (e) {
    showToast(`Could not load metrics: ${e.message}`, true);
    return;
  }

  document.getElementById("metricEce").textContent =
    data.expected_calibration_error != null ? data.expected_calibration_error.toFixed(3) : "—";
  document.getElementById("metricN").textContent = data.n_reviewed_verdicts;

  const chart = document.getElementById("reliabilityChart");
  if (!data.reliability_diagram || !data.reliability_diagram.length) {
    chart.innerHTML = `<div class="table-empty">No reviewed verdicts yet — confirm or overrule a finding to populate this.</div>`;
    return;
  }

  chart.innerHTML = data.reliability_diagram
    .filter((bin) => bin.count > 0)
    .map((bin) => {
      const [lo, hi] = bin.bin_range;
      const accPct = Math.round((bin.accuracy ?? 0) * 100);
      const confPct = Math.round((bin.avg_confidence ?? 0) * 100);
      return `
      <div class="reliability-row">
        <div class="mono">${lo.toFixed(1)}–${hi.toFixed(1)}</div>
        <div class="reliability-bar-track">
          <div class="reliability-bar-fill" style="width:${accPct}%"></div>
          <div class="reliability-bar-marker" style="left:${confPct}%"></div>
        </div>
        <div class="mono">n=${bin.count}</div>
      </div>`;
    })
    .join("");
}

// ---------------------------------------------------------------------
// Boot
// ---------------------------------------------------------------------
checkConnection();
loadScans();
setInterval(checkConnection, 15000);
