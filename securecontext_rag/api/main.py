"""
SecureContext-RAG API gateway (report section 4.2.4), Tier 2 of the
two-tier architecture (section 4.1). Run with:

    uvicorn api.main:app --reload

See README_PHASE2.md for full setup instructions.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.db.session import init_db
from api.routers import findings, metrics, scans, verdicts, webhooks

FRONTEND_DIR = Path(__file__).resolve().parents[1] / "frontend"

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="SecureContext-RAG API",
    description=(
        "Retrieval-augmented, confidence-calibrated vulnerability triage "
        "API. Single entry point for scan requests, confidence-ranked "
        "findings, reviewer feedback, and calibration metrics."
    ),
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health", tags=["health"])
def health() -> dict:
    return {"status": "ok"}


app.include_router(scans.router)
app.include_router(findings.router)
app.include_router(verdicts.router)
app.include_router(metrics.router)
app.include_router(webhooks.router)


@app.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse(url="/ui/")


# Static dashboard (plain HTML/CSS/JS, no build step) -- served directly by
# FastAPI so the whole stack, frontend included, stays Python-only. Mounted
# last so it never shadows the API routes above.
if FRONTEND_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="ui")
