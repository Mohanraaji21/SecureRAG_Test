# GitHub Webhook — Setup and Activation

## Do you need this?

**No, not to use, test, or demo the system.** `POST /scans` (manually, or
via the dashboard's "Trigger scan" button) is the complete, normal way to
run a scan. This document is only relevant if you specifically want
scans to fire *automatically* whenever a pull request opens or updates on
a real GitHub repository, with no one manually clicking anything.

## What it does now (this is newly completed)

Earlier in this project, the webhook endpoint existed but assumed the
PR's code was already checked out at a conventional filesystem path —
someone or something else had to put it there first. **That gap is now
closed**: `api/services/git_checkout.py` performs the actual `git clone`
(or `git fetch` + `checkout` if a prior checkout for that PR already
exists) before the scan runs, using the `clone_url` and head commit SHA
GitHub includes in the webhook payload. No manual checkout step, no
shared volume convention required.

## How it activates, step by step

1. **A pull request is opened, synchronized (new commits pushed), or
   reopened** on a GitHub repository that has this webhook configured.
2. **GitHub sends a signed HTTP POST** to your server's
   `/webhooks/github` endpoint, with:
   - header `X-GitHub-Event: pull_request`
   - header `X-Hub-Signature-256: sha256=<hmac>` — an HMAC-SHA256 of the
     raw request body, keyed with the webhook secret you configured
   - a JSON body containing `action`, `number` (PR number), `repository`,
     and `pull_request.head.{sha, repo.clone_url}`
3. **Signature verification** (`api/routers/webhooks.py::_verify_signature`):
   recomputes the HMAC using `SCR_GITHUB_WEBHOOK_SECRET` from your `.env`
   and compares with `hmac.compare_digest` (constant-time, to avoid
   timing attacks). Mismatch → `401`, nothing else happens.
4. **Event/action filtering**: only `pull_request` events with
   `action` in `opened`/`synchronize`/`reopened` proceed; everything else
   returns `200 {"status": "ignored", ...}` (so GitHub doesn't see this as
   a failure and doesn't retry/disable the webhook).
5. **A `ScanRun` row is created** (`Status="pending"`) and the response
   is sent back to GitHub immediately with the `scan_run_id`.
6. **In the background**: `checkout_and_run_scan_and_persist`
   (`api/services/scan_service.py`) clones/updates the PR's head commit
   into `checkouts/<repo>__<name>/<pr_number>/`, then runs the exact same
   pipeline `POST /scans` does against that checkout.
7. **Result**: `GET /scans/{scan_run_id}` (or the dashboard) shows the
   same confidence-ranked findings as a manually triggered scan, with no
   further action needed.

## Setting it up on a real repository

You need a **publicly reachable deployment** of this app (GitHub's
servers must be able to reach your `/webhooks/github` URL over the
internet — `http://127.0.0.1:8000` on your laptop won't work unless
you tunnel it, e.g. with `ngrok` for testing).

1. Set a real secret in your `.env`:
   ```ini
   SCR_GITHUB_WEBHOOK_SECRET=a-long-random-string-only-you-and-github-know
   ```
2. In the GitHub repository: **Settings → Webhooks → Add webhook**
   - **Payload URL:** `https://your-deployed-host/webhooks/github`
   - **Content type:** `application/json`
   - **Secret:** the same string as `SCR_GITHUB_WEBHOOK_SECRET`
   - **Which events:** "Let me select individual events" → check
     **Pull requests** only (no need to subscribe to everything)
3. Open (or push to) a pull request on that repo. Check **Settings →
   Webhooks → [your webhook] → Recent Deliveries** in GitHub to see the
   request and response — a green checkmark with `200` means it worked.
4. Confirm on your server: `GET /scans` should show a new scan run for
   that PR, moving through `pending → running → completed`.

## Does this require creating a GitHub PR yourself to test it?

Only if you want to test the **real, live, GitHub-hosted** path end to
end. For everything else:
- **Local, no GitHub needed at all:** `tests_api/test_webhooks.py` tests
  the entire webhook logic (signature verification, event filtering, the
  checkout-then-scan flow) with `git` itself mocked — run `pytest` and
  these pass with zero network access, zero GitHub account, zero real PR.
- **Manually simulate a webhook call without GitHub:** you can `curl`
  `/webhooks/github` yourself with a hand-crafted payload and a correctly
  computed signature, if you want to see it work against a *real* git
  clone (not mocked) without needing an actual GitHub PR:
  ```python
  import hmac, hashlib, json
  secret = "your-SCR_GITHUB_WEBHOOK_SECRET-value"
  payload = {
      "action": "opened", "number": 1,
      "repository": {"full_name": "octocat/Hello-World", "clone_url": "https://github.com/octocat/Hello-World.git"},
      "pull_request": {"head": {"sha": "7fd1a60b01f91b314f59955a4e4d4e80d8edf11",
                                 "repo": {"clone_url": "https://github.com/octocat/Hello-World.git"}}}
  }
  body = json.dumps(payload).encode()
  sig = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
  print(sig)  # use this as the X-Hub-Signature-256 header value
  ```
  ```bash
  curl -X POST http://127.0.0.1:8000/webhooks/github \
    -H "Content-Type: application/json" \
    -H "X-GitHub-Event: pull_request" \
    -H "X-Hub-Signature-256: <paste sig from above>" \
    -d '<paste the same JSON payload>'
  ```
  This hits a real public repo (`octocat/Hello-World`, GitHub's own demo
  repo) so the git clone genuinely succeeds — a good way to prove the
  checkout + scan flow works without setting up webhook delivery at all.

## Known limitations

- **Shallow clones** (`--depth 50`) are used for speed; if a PR's head
  commit is older than the last 50 commits on its branch, the explicit
  `git fetch origin <sha>` step in `git_checkout.py` handles fetching it
  specifically, but very large/old histories could still be slow on first
  checkout.
- **No concurrency control** on checkouts — two webhook deliveries for
  the same PR arriving at nearly the same time could race on the same
  checkout directory. Low risk in practice (GitHub doesn't typically
  double-deliver), but worth knowing if you see odd behavior under rapid
  repeated pushes to one PR.
- **Private repositories** need the `clone_url` to work with
  authentication (e.g. a deploy key or token baked into the clone URL, or
  an SSH-based clone URL with a configured key) — this isn't set up by
  default; see `api/services/git_checkout.py::ensure_pr_checkout` if you
  need to add auth to the clone step.
