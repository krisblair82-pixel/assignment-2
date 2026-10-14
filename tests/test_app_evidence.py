"""Behavior tests for answer evidence-image rendering."""


def test_answer_question_returns_verified_original_images(monkeypatch, tmp_path):
    import app

    image = tmp_path / "slide-12.png"
    image.write_bytes(b"not a real image, but an existing evidence path")

    def fake_ask(question, doc_filter=None):
        return {
            "answer": "Attention weighs token importance.",
            "covered": True,
            "sources": [{
                "doc_id": "week2",
                "slide": 12,
                "page": None,
                "section": "Attention",
                "excerpt": "Attention weighs token importance.",
                "image_path": str(image),
            }],
        }

    monkeypatch.setattr(app, "grounded_ask", fake_ask)

    answer, status, evidence = app.answer_question("What is attention?", "week2")

    assert answer == "Attention weighs token importance."
    assert "slide 12" in status
    assert evidence == [str(image)]


def test_answer_question_does_not_return_missing_evidence_paths(monkeypatch):
    import app

    def fake_ask(question, doc_filter=None):
        return {
            "answer": "A grounded answer.",
            "covered": True,
            "sources": [{"doc_id": "week2", "slide": 12, "image_path": "missing.png"}],
        }

    monkeypatch.setattr(app, "grounded_ask", fake_ask)

    answer, status, evidence = app.answer_question("Question", "week2")

    assert answer == "A grounded answer."
    assert evidence == []
