"""Behavior tests for the quiz-generation UI handler."""


def test_generate_quiz_ui_renders_questions_without_answer_key(monkeypatch):
    import app

    calls = {}

    def fake_generate(doc_id, topic=None, n=5):
        calls.update(doc_id=doc_id, topic=topic, n=n)
        return {
            "quiz": {
                "quiz_id": "quiz-1",
                "doc_id": doc_id,
                "topic": topic,
                "n": 1,
                "questions": [{
                    "id": "q1",
                    "question": "Which method is used?",
                    "options": ["A. Attention", "B. Pooling", "C. Sorting", "D. Hashing"],
                }],
            },
            "key": {"answers": {"q1": {"correct": 0, "explanation": "private"}}},
            "issues": [],
        }

    monkeypatch.setattr(app, "generate_quiz_backend", fake_generate)

    output, status, quiz_id = app.generate_quiz_ui("week2", "attention", 1)

    assert calls == {"doc_id": "week2", "topic": "attention", "n": 1}
    assert quiz_id == "quiz-1"
    assert "Which method is used?" in output
    assert "A. Attention" in output
    assert "correct" not in output.lower()
    assert "week2" in status


def test_generate_quiz_ui_requires_a_document_without_backend_call(monkeypatch):
    import app

    def fail_if_called(*args, **kwargs):
        raise AssertionError("backend must not run without a document")

    monkeypatch.setattr(app, "generate_quiz_backend", fail_if_called)

    output, status, quiz_id = app.generate_quiz_ui(None, "attention", 5)

    assert output == ""
    assert status
    assert "select a document" in status.lower()
    assert quiz_id == ""
