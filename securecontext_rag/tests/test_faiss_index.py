import numpy as np
import pytest

from core.retrieval.faiss_index import KnowledgeIndex
from core.retrieval.kb_builder import load_from_json
from core.schemas.models import Finding


class FakeEmbedder:
    """Deterministic bag-of-words embedder so tests don't need to download
    a real sentence-transformers model. Maps each text to a fixed-size
    vector based on which of a small vocabulary of tokens it contains."""

    VOCAB = [
        "sql", "injection", "query", "concatenat", "xss", "script",
        "html", "command", "shell", "subprocess", "hardcod", "secret",
        "credential", "pickle", "deserializ", "path", "traversal",
        "hash", "crypto", "xml", "entity",
    ]

    def encode(self, texts: list[str]) -> np.ndarray:
        vectors = []
        for text in texts:
            lowered = text.lower()
            vec = np.array(
                [1.0 if token in lowered else 0.0 for token in self.VOCAB],
                dtype="float32",
            )
            norm = np.linalg.norm(vec)
            vectors.append(vec / norm if norm > 0 else vec)
        return np.stack(vectors)


@pytest.fixture
def index() -> KnowledgeIndex:
    items = load_from_json()
    return KnowledgeIndex.build(items, FakeEmbedder())


def test_build_index_from_seed_kb(index: KnowledgeIndex):
    assert len(index.items) > 0


def test_query_returns_cwe_matching_evidence(index: KnowledgeIndex):
    finding = Finding(
        rule_id="test-rule",
        cwe_id="CWE-89",
        file_path="app.py",
        line=10,
        message="SQL injection via string concatenation in query",
        code_snippet='query = "SELECT * FROM t WHERE id=" + x',
    )
    results = index.query(finding, top_k=2)
    assert len(results) > 0
    for r in results:
        assert r.source.startswith("CWE-89")


def test_query_cwe_filter_excludes_other_cwes(index: KnowledgeIndex):
    finding = Finding(
        rule_id="test-rule",
        cwe_id="CWE-611",
        file_path="parser.py",
        line=1,
        message="XML external entity",
        code_snippet="etree.parse(user_input)",
    )
    results = index.query(finding, top_k=3, cwe_filter=True)
    for r in results:
        assert r.source.startswith("CWE-611")


def test_get_item_text_roundtrip(index: KnowledgeIndex):
    item = index.items[0]
    assert index.get_item_text(item.item_id) == item.text
    assert index.get_item_text("nonexistent-id") is None
