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

    result = app.generate_quiz_ui("week2", "attention", 1)
    output, status, quiz_id, *radio_updates = result

    assert calls == {"doc_id": "week2", "topic": "attention", "n": 1}
    assert quiz_id == "quiz-1"
    assert "Which method is used?" in output
    assert "A. Attention" in output
    assert "correct" not in output.lower()
    assert "week2" in status
    assert radio_updates[0]["choices"] == [
        "A. Attention", "B. Pooling", "C. Sorting", "D. Hashing"
    ]
    assert radio_updates[0]["visible"] is True
    assert radio_updates[1]["visible"] is False


def test_generate_quiz_ui_requires_a_document_without_backend_call(monkeypatch):
    import app

    def fail_if_called(*args, **kwargs):
        raise AssertionError("backend must not run without a document")

    monkeypatch.setattr(app, "generate_quiz_backend", fail_if_called)

    output, status, quiz_id, *radio_updates = app.generate_quiz_ui(None, "attention", 5)

    assert output == ""
    assert status
    assert "select a document" in status.lower()
    assert quiz_id == ""
    assert all(update["visible"] is False for update in radio_updates)


def test_clickable_quiz_answers_are_converted_to_server_side_submission(monkeypatch):
    import app

    app._QUIZ_SESSIONS["quiz-click"] = {
        "quiz": {"quiz_id": "quiz-click", "questions": [
            {"id": "q1", "question": "First?", "options": ["A", "B", "C", "D"]},
            {"id": "q2", "question": "Second?", "options": ["A", "B", "C", "D"]},
        ]},
        "key": {"answers": {
            "q1": {"correct": 0, "explanation": "one", "source": {}},
            "q2": {"correct": 1, "explanation": "two", "source": {}},
        }},
    }

    score, status = app.score_clickable_quiz_ui("quiz-click", "A", "B", *([None] * 8), False)

    assert "2/2" in score
    assert "scored" in status.lower()
