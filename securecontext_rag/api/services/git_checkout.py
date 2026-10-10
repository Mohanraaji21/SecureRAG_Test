"""
Git checkout for webhook-triggered scans (report §4.2.5 CI/CD integration).

This closes the gap explicitly documented in an earlier version of
api/routers/webhooks.py: rather than assuming a repo is already checked
out at a conventional path, this module actually clones (or updates) the
PR's head commit so a GitHub webhook goes end-to-end with no manual setup.

Checkouts are cached per (repo, PR) under `checkouts/` and updated with a
fetch+checkout rather than a fresh clone on subsequent pushes to the same
PR, since PRs are typically pushed to multiple times before merge.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger("securecontext_rag.api.git_checkout")

DEFAULT_CHECKOUTS_ROOT = Path("checkouts")
GIT_TIMEOUT_SECONDS = 120


class GitCheckoutError(RuntimeError):
    pass


def _run_git(args: list[str], cwd: str | Path | None = None) -> None:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=GIT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise GitCheckoutError(f"git {' '.join(args)} timed out after {GIT_TIMEOUT_SECONDS}s") from exc

    if proc.returncode != 0:
        raise GitCheckoutError(f"git {' '.join(args)} failed: {proc.stderr.strip()[:2000]}")


def _safe_dir_name(repo_full_name: str) -> str:
    # "acme-org/webapp" -> "acme-org__webapp" (keep it one filesystem-safe segment)
    return repo_full_name.replace("/", "__")


def ensure_pr_checkout(
    repo_full_name: str,
    pr_number: int,
    clone_url: str,
    head_sha: str | None = None,
    checkouts_root: Path = DEFAULT_CHECKOUTS_ROOT,
) -> Path:
    """Ensures a local checkout of the given PR's head commit exists on
    disk, cloning fresh or updating an existing checkout as needed.
    Returns the local path Semgrep should then scan.

    Raises GitCheckoutError (never a bare subprocess exception) on any
    git failure, so the caller can route it into the same fail-open
    ScanRun.Status = "failed" handling as a pipeline error.
    """
    target = checkouts_root / _safe_dir_name(repo_full_name) / str(pr_number)

    if target.exists() and (target / ".git").exists():
        logger.info("Updating existing checkout at %s", target)
        _run_git(["fetch", "--depth", "50", "origin"], cwd=target)
        ref = head_sha or "origin/HEAD"
        _run_git(["checkout", "--force", ref], cwd=target)
    else:
        logger.info("Cloning %s (PR #%s) into %s", repo_full_name, pr_number, target)
        target.parent.mkdir(parents=True, exist_ok=True)
        _run_git(["clone", "--depth", "50", clone_url, str(target)])
        if head_sha:
            # Shallow clones don't always carry every PR head commit by
            # default; fetch it explicitly before checking it out.
            _run_git(["fetch", "--depth", "50", "origin", head_sha], cwd=target)
            _run_git(["checkout", "--force", head_sha], cwd=target)

    return target
