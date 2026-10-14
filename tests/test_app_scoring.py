"""Behavior tests for quiz submission and scoring."""


def test_score_quiz_ui_scores_submitted_answers_without_revealing_unanswered_key(monkeypatch):
    import app

    app._QUIZ_SESSIONS["quiz-1"] = {
        "quiz": {
            "quiz_id": "quiz-1",
            "questions": [
                {"id": "q1", "question": "First?", "options": ["A", "B", "C", "D"]},
                {"id": "q2", "question": "Second?", "options": ["A", "B", "C", "D"]},
            ],
        },
        "key": {
            "answers": {
                "q1": {"correct": 0, "explanation": "first explanation", "source": {}},
                "q2": {"correct": 1, "explanation": "second explanation", "source": {}},
            }
        },
    }

    score, status = app.score_quiz_ui("quiz-1", '{"q1": 0}', False)

    assert "1/2" in score
    assert "q1" in score
    assert "q2" in score
    assert "second explanation" not in score
    assert "scored" in status.lower()


def test_score_quiz_ui_reveals_explanations_only_when_requested():
    import app

    score, status = app.score_quiz_ui("quiz-1", '{"q1": 0, "q2": 1}', True)

    assert "2/2" in score
    assert "second explanation" in score
    assert "revealed" in status.lower()


def test_score_quiz_ui_rejects_unknown_or_invalid_submission():
    import app

    score, status = app.score_quiz_ui("missing", "{}", False)

    assert score == ""
    assert "generate a quiz" in status.lower()
