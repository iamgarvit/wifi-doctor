"""Retrieval, fusion, and the KB-backed code tables. BM25-only: no downloads."""

from __future__ import annotations

import pytest

from wifi_doctor.retrieval import (
    DEFAULT_KB_DIR,
    load_chunks,
    load_code_table,
    tokenize,
)


def test_tokenizer_keeps_underscored_identifiers_whole():
    assert "status_code" in tokenize("what does status_code=17 mean")


def test_chunks_cover_every_document():
    chunks = load_chunks()
    docs = {p.stem for p in DEFAULT_KB_DIR.glob("*.md")}
    assert {c.doc_id for c in chunks} == docs
    assert len(chunks) > len(docs), "documents should be split into sections"
    assert all(c.text.strip() for c in chunks)


def test_bm25_only_mode_reports_its_backend(kb):
    assert kb.backend == "bm25"
    assert kb.model_name is None


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("4-way handshake failed but the signal is strong", "wrong-password"),
        ("no DHCPOFFERS received and no IP address", "dhcp"),
        ("what does association status_code 17 mean", "status-codes"),
        ("CTRL-EVENT-EAP-FAILURE enterprise network", "eap"),
    ],
)
def test_search_finds_the_relevant_document(kb, query, expected):
    hits = kb.search(query, k=4)
    assert any(expected in h.chunk.doc_id for h in hits), [h.chunk.label for h in hits]


def test_search_respects_k_and_is_deterministic(kb):
    a = kb.search("beacon loss weak signal", k=3)
    b = kb.search("beacon loss weak signal", k=3)
    assert len(a) == 3
    assert [h.chunk.label for h in a] == [h.chunk.label for h in b]


def test_empty_query_returns_nothing(kb):
    assert kb.search("   ", k=3) == []


def test_snippets_are_bounded(kb):
    for h in kb.search("roaming", k=3):
        assert len(h.snippet(200)) <= 201


def test_reason_and_status_tables_are_distinct_and_populated():
    reason = load_code_table("reason")
    status = load_code_table("status")
    assert reason[15] != status[15]
    assert len(reason) >= 15 and len(status) >= 15
    assert status[0].lower().startswith("success")


def test_code_table_rejects_a_bad_kind():
    with pytest.raises(ValueError, match="reason"):
        load_code_table("banana")


def test_kb_contains_no_test_log(dev_cases):
    """The knowledge base must not leak evaluation data into the prompt."""
    blob = "\n".join(p.read_text() for p in DEFAULT_KB_DIR.glob("*.md"))
    for case in dev_cases[:10]:
        for line in case["log"].split("\n")[:40]:
            assert line not in blob


def test_backend_reports_bm25_when_the_encoder_is_missing(monkeypatch, tmp_path):
    """A cached matrix without a query encoder must not be called 'hybrid'."""
    import numpy as np

    from wifi_doctor.retrieval import KnowledgeBase as KB

    kb = KB(cache_dir=tmp_path, use_embeddings=False)
    kb._matrix = np.zeros((len(kb.chunks), 4), dtype=np.float32)
    assert kb._model is None
    assert kb.backend == "bm25"
    assert kb.search("handshake", k=2)  # and it still answers, lexically
