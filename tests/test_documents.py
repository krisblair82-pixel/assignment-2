"""Offline tests for in-app document management (requirement 1a).

Network-calling pieces (9005 parsing, chroma/bm25 rebuild) are monkeypatched;
index.json merge/filter logic and deduplication run for real.
"""
import json

import documents


def _write_index(tmp_path, chunks, pages):
    import os
    os.makedirs(tmp_path / "index", exist_ok=True)
    path = tmp_path / "index" / "index.json"
    path.write_text(json.dumps({"chunks": chunks, "pages": pages}), encoding="utf-8")
    return path


def _setup(monkeypatch, tmp_path):
    """Point config paths at tmp dirs and stub network calls."""
    monkeypatch.setattr(documents, "ensure_configured", lambda: None)
    mats = tmp_path / "materials"
    renders = tmp_path / "renders"
    results = tmp_path / "results"
    index = tmp_path / "index"
    mats.mkdir(); renders.mkdir(); results.mkdir(); index.mkdir()
    monkeypatch.setattr(documents, "MATERIALS_DIR", str(mats))
    monkeypatch.setattr(documents, "RENDERS_DIR", str(renders))
    monkeypatch.setattr(documents, "RESULTS_DIR", str(results))
    monkeypatch.setattr(documents, "INDEX_DIR", str(index))
    _write_index(tmp_path, [], [])

    def fake_process_file(f, parser, dry_run):
        import os
        doc_id = documents.slugify(os.path.relpath(f, str(mats)))
        return ([{"doc_id": doc_id, "page": 1, "slide": None, "section": None,
                  "chunk_idx": 0, "text": "Sample content for " + doc_id}],
                [{"doc_id": doc_id, "page": 1, "slide": None,
                  "image_path": f}],
                {"pages": 1, "chunks": 1, "images": 1, "warning": None})

    monkeypatch.setattr(documents, "process_file", fake_process_file)

    def fake_build_index(*args, **kwargs):
        return {"chunks": 1, "pages": 1, "bm25": True, "text_dense": True,
                "visual": False, "built_at": "test"}

    monkeypatch.setattr("retrieval.build_index", fake_build_index)
    return mats


def test_dedup_same_file_twice(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    src = tmp_path / "notes.md"
    src.write_text("hello world", encoding="utf-8")

    ok1, msg1, doc_id = documents.add_document(str(src), orig_name="notes.md",
                                               rebuild=False)
    ok2, msg2, doc_id2 = documents.add_document(str(src), orig_name="notes.md",
                                                rebuild=False)
    assert ok1 and ok2
    assert "Already uploaded" in msg2
    assert doc_id == doc_id2
    data = documents._load_index()
    assert len(data["chunks"]) == 1  # not duplicated


def test_same_content_different_name_deduped(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    a = tmp_path / "a.txt"
    b = tmp_path / "copy.txt"
    a.write_text("identical payload", encoding="utf-8")
    b.write_text("identical payload", encoding="utf-8")

    ok1, _, _ = documents.add_document(str(a), orig_name="a.txt", rebuild=False)
    ok2, msg2, _ = documents.add_document(str(b), orig_name="copy.txt", rebuild=False)
    assert ok1 and ok2
    assert "Already uploaded" in msg2
    data = documents._load_index()
    assert len(data["chunks"]) == 1


def test_same_name_different_content_refused(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    a = tmp_path / "file.txt"
    a.write_text("version one", encoding="utf-8")
    documents.add_document(str(a), orig_name="file.txt", rebuild=False)
    a.write_text("version two - different bytes", encoding="utf-8")
    ok, msg, _ = documents.add_document(str(a), orig_name="file.txt", rebuild=False)
    assert not ok
    assert "different content" in msg


def test_unsupported_format_refused(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    bad = tmp_path / "evil.exe"
    bad.write_bytes(b"MZ....")
    ok, msg, _ = documents.add_document(str(bad), orig_name="evil.exe", rebuild=False)
    assert not ok
    assert "Unsupported format" in msg
    assert len(documents._load_index()["chunks"]) == 0


def test_remove_document_cleans_index_and_files(monkeypatch, tmp_path):
    mats = _setup(monkeypatch, tmp_path)
    one = tmp_path / "week2.md"
    two = tmp_path / "syllabus.md"
    one.write_text("llm fundamentals content", encoding="utf-8")
    two.write_text("grading policy content", encoding="utf-8")
    documents.add_document(str(one), orig_name="week2.md", rebuild=False)
    documents.add_document(str(two), orig_name="syllabus.md", rebuild=False)

    data = documents._load_index()
    assert len(data["chunks"]) == 2
    # Simulate a rendered image for week2 so cleanup is exercised.
    import os
    render = os.path.join(documents.RENDERS_DIR, "week2_p001.png")
    with open(render, "w") as f:
        f.write("png")

    target = [c["doc_id"] for c in data["chunks"]
              if c["doc_id"] == "week2.md"][0]
    ok, msg = documents.remove_document(target, rebuild=False)
    assert ok
    assert "Removed" in msg
    data = documents._load_index()
    assert [c["doc_id"] for c in data["chunks"]] == ["syllabus.md"]
    assert not os.path.exists(render)
    removed_file = os.path.join(str(mats), "week2.md")
    assert not os.path.exists(removed_file)
    assert os.path.exists(os.path.join(str(mats), "syllabus.md"))


def test_remove_unknown_document(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    ok, msg = documents.remove_document("does_not_exist.pdf", rebuild=False)
    assert not ok
    assert "not found" in msg


def test_list_documents_reports_counts(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    src = tmp_path / "notes.md"
    src.write_text("hello", encoding="utf-8")
    documents.add_document(str(src), orig_name="notes.md", rebuild=False)
    docs = documents.list_documents()
    assert len(docs) == 1
    assert docs[0]["chunks"] == 1
    assert docs[0]["present"] is True
