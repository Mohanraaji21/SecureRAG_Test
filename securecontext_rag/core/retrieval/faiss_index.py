"""
Retrieval-augmented knowledge subsystem (report section 4.2.2).

Builds and queries a FAISS index over KnowledgeItem embeddings. Follows
Vul-RAG's finding that knowledge-level retrieval outperforms code-level
retrieval (section 4.6): the query combines the finding's code snippet
with its CWE id / rule message ("combined query of code content and
extracted functional semantics" per 4.2.2), but what's indexed is always
distilled knowledge text, never raw repository code.

The embedding backend is pluggable via the `Embedder` protocol so unit
tests can run with a fast deterministic fake embedder instead of
downloading a real sentence-transformers model.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from core.schemas.models import Finding, KnowledgeItem, RetrievedEvidence


class Embedder(Protocol):
    """Anything with an `encode(texts) -> np.ndarray[N, D]` method works,
    which matches sentence-transformers' SentenceTransformer.encode API."""

    def encode(self, texts: list[str]) -> np.ndarray: ...


class SentenceTransformerEmbedder:
    """Default production embedder. Imports sentence-transformers lazily
    so the rest of the package works even if it isn't installed yet."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer  # lazy import

        self._model = SentenceTransformer(model_name)

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.asarray(
            self._model.encode(texts, normalize_embeddings=True), dtype="float32"
        )


@dataclass
class KnowledgeIndex:
    """Wraps a FAISS index alongside the KnowledgeItems it was built from,
    so query results can be mapped back to full item text and metadata."""

    items: list[KnowledgeItem]
    embedder: Embedder
    _index: "faiss.Index"  # noqa: F821 - faiss imported lazily below

    @classmethod
    def build(cls, items: list[KnowledgeItem], embedder: Embedder) -> "KnowledgeIndex":
        import faiss  # lazy import so faiss is only required when used

        if not items:
            raise ValueError("cannot build a KnowledgeIndex from an empty item list")

        texts = [f"{item.title}. {item.text}" for item in items]
        vectors = embedder.encode(texts)
        dim = vectors.shape[1]

        # Inner product over normalized vectors == cosine similarity.
        index = faiss.IndexFlatIP(dim)
        index.add(vectors)

        return cls(items=items, embedder=embedder, _index=index)

    def save(self, dir_path: str | Path) -> None:
        import faiss
        import json

        dir_path = Path(dir_path)
        dir_path.mkdir(parents=True, exist_ok=True)
        faiss.write_index(self._index, str(dir_path / "index.faiss"))
        with open(dir_path / "items.json", "w", encoding="utf-8") as f:
            json.dump([item.model_dump() for item in self.items], f)

    @classmethod
    def load(cls, dir_path: str | Path, embedder: Embedder) -> "KnowledgeIndex":
        import faiss
        import json

        dir_path = Path(dir_path)
        index = faiss.read_index(str(dir_path / "index.faiss"))
        with open(dir_path / "items.json", "r", encoding="utf-8") as f:
            raw_items = json.load(f)
        items = [KnowledgeItem(**item) for item in raw_items]
        return cls(items=items, embedder=embedder, _index=index)

    def query(
        self,
        finding: Finding,
        top_k: int = 3,
        cwe_filter: bool = True,
    ) -> list[RetrievedEvidence]:
        """Combined query of code content + functional semantics (rule
        message, CWE id) per section 4.2.2. If `cwe_filter` is True and the
        finding carries a CWE id, results are restricted to knowledge items
        tagged with that same CWE id -- this is the CWE-specific retrieval
        called for in section 4.6."""
        query_text = f"{finding.message} CWE:{finding.cwe_id or 'unknown'}\n{finding.code_snippet}"
        query_vec = self.embedder.encode([query_text])

        # Over-fetch, then filter by CWE, since FAISS itself is unfiltered.
        k = min(top_k * 5, len(self.items)) if cwe_filter else min(top_k, len(self.items))
        scores, indices = self._index.search(query_vec, k)

        results: list[RetrievedEvidence] = []
        for score, idx in zip(scores[0], indices[0]):
            if idx < 0:
                continue
            item = self.items[idx]
            if cwe_filter and finding.cwe_id and item.cwe_id != finding.cwe_id:
                continue
            results.append(
                RetrievedEvidence(
                    source=f"{item.cwe_id} {item.title}",
                    knowledge_item_id=item.item_id,
                    similarity_score=float(score),
                )
            )
            if len(results) >= top_k:
                break

        return results

    def get_item_text(self, item_id: str) -> str | None:
        for item in self.items:
            if item.item_id == item_id:
                return item.text
        return None
