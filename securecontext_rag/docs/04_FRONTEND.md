# Frontend

A static dashboard — plain HTML, CSS, and vanilla JavaScript — served
directly by the FastAPI backend. There is no build step, no bundler, no
npm install, no JavaScript framework, and no Node.js process involved at
any point. The browser loads three files; those files call the same JSON
API described in `docs/03_API_REFERENCE.md` with `fetch()`.

## Why static files, not React/Vue/etc.

Three pages talking to five endpoints doesn't need a framework's state
management or component system, and adding one would introduce the exact
non-Python build tooling this project stage was explicitly trying to
avoid. `api/main.py` mounts the `frontend/` folder with FastAPI's
built-in `StaticFiles`:

```python
app.mount("/ui", StaticFiles(directory="frontend", html=True), name="ui")
```

`GET /` redirects to `/ui/`, which serves `frontend/index.html`.

## Files

| File | Purpose |
|---|---|
| `frontend/index.html` | Page structure: a left nav rail (Scans / Findings / Calibration), one `<section>` per view, a trigger-scan form, a findings list, a reliability-diagram panel, and a review modal |
| `frontend/style.css` | All styling. Dark, data-dense "ops console" look (not a generic SaaS-card template) — flat hairline-bordered rows, a single amber accent color used functionally (confidence bars, pending status), monospace used only where the content actually is code/CWE-ids/JSON |
| `frontend/app.js` | All behavior: API calls, view switching, rendering, the review modal, polling the connection status |

## How it talks to the backend

`app.js` has one small `api()` helper that wraps `fetch()`:
```js
async function api(path, { method = "GET", body, auth = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (auth) headers["X-API-Key"] = apiKey();
  const res = await fetch(path, { method, headers, body: body && JSON.stringify(body) });
  if (!res.ok) throw new Error(...);
  return res.json();
}
```
Because the dashboard is served from the same FastAPI app it's calling
(`/ui/...` and `/scans`, `/findings`, etc. share an origin), there's no
CORS configuration needed and API calls use relative paths.

The API key is read from a plain `<input type="password">` in the
sidebar at call time — it is **not** persisted to `localStorage` or
`sessionStorage`; it lives only in that input field for the lifetime of
the page load. You re-enter it if you refresh. This is a deliberate
simplicity/security tradeoff appropriate for a local/internal tool; see
"Extending" below if you want to change that.

## The three views

### Scans
- A form to trigger a scan (`POST /scans`): repo path, repo name,
  optional PR number.
- A table of all scan runs with live-ish status (`GET /scans`, manual
  **Refresh** button — there's no auto-polling of in-progress scans by
  design, to avoid hammering the API; refresh manually or re-visit the tab).
- Clicking **View** on a scan jumps to the Findings view pre-filtered to
  that scan.

### Findings
- Filter bar: scan (dropdown, populated from the Scans view), minimum
  confidence, CWE id.
- Each finding renders as a card: file:line, CWE id, rule id, a
  color-coded verdict badge (true_positive / false_positive /
  needs_review), a confidence bar, the LLM's justification text, and the
  raw code snippet.
- **Review verdict** opens a modal to confirm/overrule/mark-unsure,
  with an optional note (`POST /verdicts/{id}/review`).

### Calibration
- Two headline numbers: Expected Calibration Error and the count of
  reviewed verdicts it's based on (`GET /metrics/calibration`).
- A reliability diagram: one row per confidence bucket, a bar showing
  actual accuracy in that bucket with a marker at the average predicted
  confidence — visually, the marker and the end of the bar should align
  for a well-calibrated bucket.

## Responsive behavior

Below 760px width, the left rail collapses to a horizontal bar and the
findings table's grid stacks to a single column — see the
`@media (max-width: 760px)` block in `style.css`. `prefers-reduced-motion`
is respected (the one CSS transition, the toast notification, is disabled).

## Extending it

- **Add a view:** add a `<button class="nav-item" data-view="X">` in the
  rail, a `<section id="view-X">` in `<main>`, and a `loadX()` function
  called from `switchView()` in `app.js`.
- **Persist the API key across reloads:** swap the plain variable read in
  `apiKey()` for `sessionStorage`, with a `try/catch` around both the read
  and the write (sessionStorage can throw in some browser privacy modes).
- **Auto-refresh in-progress scans:** add a `setInterval(loadScans, 3000)`
  guarded to only run while on the Scans view and only while any scan's
  status is `pending`/`running` — not added by default to avoid
  unnecessary polling once everything's settled.
- **Swap the color palette:** everything is driven by the CSS custom
  properties at the top of `style.css` (`--bg`, `--accent`, etc.) — change
  those, nothing else.
