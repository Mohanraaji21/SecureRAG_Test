"""SecureContext-RAG AI Core (Tier 1).

A retrieval-augmented, confidence-calibrated vulnerability triage pipeline:
Semgrep -> FAISS knowledge retrieval -> LLM adjudication (Ollama) -> calibration.

This package has no web-framework dependency. It is designed to be imported
by the Phase 2 FastAPI application layer, or run standalone via cli.py.
"""

__version__ = "0.1.0"
