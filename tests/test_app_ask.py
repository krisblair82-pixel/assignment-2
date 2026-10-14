"""Behavior tests for the grounded-answer UI handler."""


def test_answer_question_calls_grounded_backend_and_formats_source(monkeypatch):
    import app

    calls = {}

    def fake_ask(question, doc_filter=None):
        calls.update(question=question, doc_filter=doc_filter)
        return {
            "answer": "Transformers use attention.",
            "covered": True,
            "sources": [{
                "doc_id": "week2",
                "page": None,
                "slide": 12,
                "section": "Attention",
                "excerpt": "Attention weighs the importance of tokens.",
            }],
        }

    monkeypatch.setattr(app, "grounded_ask", fake_ask)

    answer, status, evidence = app.answer_question("What is attention?", "week2")

    assert calls == {"question": "What is attention?", "doc_filter": "week2"}
    assert answer == "Transformers use attention."
    assert "week2" in status
    assert "slide 12" in status
    assert "Attention weighs the importance of tokens." in status
    assert evidence == []


def test_answer_question_rejects_blank_question_without_backend_call(monkeypatch):
    import app

    def fail_if_called(*args, **kwargs):
        raise AssertionError("backend must not run for a blank question")

    monkeypatch.setattr(app, "grounded_ask", fail_if_called)

    answer, status, evidence = app.answer_question("  ", None)

    assert answer == ""
    assert "enter a question" in status.lower()
    assert evidence == []
