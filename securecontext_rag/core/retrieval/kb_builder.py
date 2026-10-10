"""
Knowledge base construction (report section 4.2.2 / 1.1.1).

Loads CWE definitions and vulnerability-fix pairs into `KnowledgeItem`
objects. Per section 4.6, retrieval is knowledge-level, not code-level:
these items are distilled descriptions/patterns, not raw scanned code.

The bundled `data/cwe_seed.json` is a small starter set (original short
summaries written for this project, not copied from MITRE's CWE text) so
Phase 1 is runnable offline. `load_from_json` also accepts a
larger/custom knowledge base file in the same shape, e.g. one exported
from the full MITRE CWE feed, for production use.
"""

from __future__ import annotations

import json
from pathlib import Path

from core.schemas.models import KnowledgeItem

_DEFAULT_SEED_PATH = Path(__file__).resolve().parents[2] / "data" / "cwe_seed.json"


def load_from_json(path: str | Path | None = None) -> list[KnowledgeItem]:
    path = Path(path) if path else _DEFAULT_SEED_PATH
    with open(path, "r", encoding="utf-8") as f:
        raw_items = json.load(f)
    return [KnowledgeItem(**item) for item in raw_items]


def add_vuln_fix_pair(
    items: list[KnowledgeItem],
    cwe_id: str,
    title: str,
    text: str,
) -> list[KnowledgeItem]:
    """Appends a new historical vulnerability-fix pair to an in-memory KB
    (e.g. one mined later from a curated CVE repository per section 5.1)."""
    items.append(
        KnowledgeItem(cwe_id=cwe_id, kind="vuln_fix_pair", title=title, text=text)
    )
    return items
