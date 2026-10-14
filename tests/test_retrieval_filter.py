"""Offline regression for document-restricted keyword retrieval."""
import json

import bm25s

import retrieval


def test_doc_filter_applies_to_keyword_results(monkeypatch, tmp_path):
    chunks = [
        {"doc_id": "other.md", "text": "secret topic", "page": None,
         "slide": None, "section": None, "chunk_idx": 0},
        {"doc_id": "wanted.md", "text": "desired topic", "page": None,
         "slide": None, "section": None, "chunk_idx": 0},
    ]
    path = tmp_path / "index.json"
    path.write_text(json.dumps({"chunks": chunks, "pages": []}), encoding="utf-8")
    bm25_dir = tmp_path / "bm25"
    bm25 = bm25s.BM25()
    texts = [c["text"] for c in chunks]
    bm25.index(bm25s.tokenize(texts, stopwords="en"))
    bm25.save(str(bm25_dir), corpus=texts)

    monkeypatch.setattr(retrieval, "BM25_DIR", str(bm25_dir))
    monkeypatch.setattr(retrieval, "CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setattr(retrieval, "ensure_configured", lambda: None)
    result = retrieval.retrieve("secret topic", doc_filter="wanted.md", k=2,
                                index_path=str(path))
    assert all(c["doc_id"] == "wanted.md" for c in result["text_chunks"])


def test_keyword_only_mode_disables_dense_legs(monkeypatch, tmp_path):
    """Issue #5 baseline: enabled_legs={'bm25'} must skip dense/visual legs
    without touching chroma (Pure-Python bm25 only)."""
    import json

    import bm25s

    import retrieval

    chunks = [
        {"doc_id": "other.md", "text": "secret topic", "page": None,
         "slide": None, "section": None, "chunk_idx": 0},
        {"doc_id": "wanted.md", "text": "desired topic", "page": None,
         "slide": None, "section": None, "chunk_idx": 0},
    ]
    path = tmp_path / "index.json"
    path.write_text(json.dumps({"chunks": chunks, "pages": []}), encoding="utf-8")
    bm25_dir = tmp_path / "bm25"
    bm25 = bm25s.BM25()
    texts = [c["text"] for c in chunks]
    bm25.index(bm25s.tokenize(texts, stopwords="en"))
    bm25.save(str(bm25_dir), corpus=texts)

    monkeypatch.setattr(retrieval, "BM25_DIR", str(bm25_dir))
    monkeypatch.setattr(retrieval, "CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setattr(retrieval, "ensure_configured", lambda: None)
    result = retrieval.retrieve("secret topic", k=2, index_path=str(path),
                                enabled_legs={"bm25"})
    assert result["legs"]["bm25"] > 0
    assert result["legs"]["text_dense"] == 0
    assert result["legs"]["visual"] == 0
    assert result["legs"]["rerank"] == 0


def test_unknown_leg_raises(monkeypatch, tmp_path):
    import json

    import retrieval

    path = tmp_path / "index.json"
    path.write_text(json.dumps({"chunks": [], "pages": []}), encoding="utf-8")
    monkeypatch.setattr(retrieval, "BM25_DIR", str(tmp_path / "bm25"))
    monkeypatch.setattr(retrieval, "CHROMA_DIR", str(tmp_path / "chroma"))
    monkeypatch.setattr(retrieval, "ensure_configured", lambda: None)
    try:
        retrieval.retrieve("anything", index_path=str(path),
                           enabled_legs={"bogus"})
    except ValueError as exc:
        assert "unknown legs" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for unknown leg")
