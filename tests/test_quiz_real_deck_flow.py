"""Offline regressions for quiz behavior observed on the Week 2 deck."""
import json

import pytest

import quiz


DOC = "week2.pptx"
CHUNK = {"doc_id": DOC, "page": None, "slide": 12, "section": None,
         "text": "Prompt caching reuses the KV cache across requests."}


def _model_reply():
    return json.dumps({"questions": [{"id": "q1", "question": "What can be reused?",
                                      "options": ["A. The KV cache", "B. Audio", "C. Video", "D. Nothing"],
                                      "correct": "A", "explanation": "The KV cache is reused.",
                                      "source": {"doc_id": DOC, "slide": 12,
                                                 "excerpt": "KV cache"}}]})


def test_malformed_response_retries_with_more_room(monkeypatch):
    monkeypatch.setattr(quiz, "_load_index", lambda path: {"chunks": [CHUNK], "pages": []})
    calls = []

    class Client:
        def complete(self, messages, max_tokens):
            calls.append(max_tokens)
            return "```json\n{\"questions\": [" if len(calls) == 1 else _model_reply()

    monkeypatch.setattr(quiz, "ChatClient", Client)
    result = quiz.generate_quiz(DOC, n=1, save=False)
    assert result["quiz"]["n"] == 1
    assert calls == [quiz.MAX_TOKENS, quiz.MAX_TOKENS * 3]


def test_repeated_malformed_response_is_not_silent_success(monkeypatch):
    monkeypatch.setattr(quiz, "_load_index", lambda path: {"chunks": [CHUNK], "pages": []})

    class Client:
        def complete(self, messages, max_tokens):
            return "unparseable"

    monkeypatch.setattr(quiz, "ChatClient", Client)
    with pytest.raises(ValueError, match="valid quiz"):
        quiz.generate_quiz(DOC, n=1, save=False)


def test_unanswered_question_does_not_expose_answer_before_request():
    public = {"quiz_id": "probe", "questions": [{"id": "q1", "question": "Q?",
                                                  "options": ["A", "B", "C", "D"]}]}
    key = {"answers": {"q1": {"correct": 2, "explanation": "Why",
                              "source": {"doc_id": DOC, "slide": 12}}}}
    blind = quiz.score_quiz(public, key, {}, reveal=False)["per_question"][0]
    assert "correct" not in blind
    assert "explanation" not in blind
    assert "source" not in blind
    answered = quiz.score_quiz(public, key, {"q1": 0}, reveal=False)["per_question"][0]
    assert answered["correct"] == 2
    revealed = quiz.score_quiz(public, key, {}, reveal=True)["per_question"][0]
    assert revealed["correct"] == 2
    assert revealed["explanation"] == "Why"


def test_unknown_topic_does_not_quiz_entire_document(monkeypatch):
    monkeypatch.setattr(quiz, "_load_index", lambda path: {"chunks": [CHUNK], "pages": []})
    with pytest.raises(ValueError, match="topic.*no matching"):
        quiz.generate_quiz(DOC, topic="does not exist", n=1, save=False)


def test_visual_quiz_attaches_and_cites_original_slide(monkeypatch, tmp_path):
    slide = {**CHUNK, "slide": 34, "text": "Security? Never heard of it. How it started; how it is going."}
    image = tmp_path / "slide34.png"
    image.write_bytes(b"image bytes")
    monkeypatch.setattr(quiz, "_load_index", lambda path: {
        "chunks": [slide],
        "pages": [{"doc_id": DOC, "slide": 34, "image_path": str(image)}]})
    seen = []
    real_image_part = quiz.ChatClient.image_part

    class Client:
        image_part = staticmethod(real_image_part)

        def complete(self, messages, max_tokens):
            seen.extend(messages[1]["content"])
            return json.dumps({"questions": [{"id": "q1", "question": "What changed in the screenshots?",
                                             "options": ["A. Security", "B. Size", "C. Cost", "D. Speed"],
                                             "correct": "A", "explanation": "Visible in the slide image.",
                                             "source": {"doc_id": DOC, "slide": 34}}]})

    monkeypatch.setattr(quiz, "ChatClient", Client)
    result = quiz.generate_quiz(DOC, topic="Security?", n=1, save=False)
    assert any(part["type"] == "image_url" for part in seen)
    assert any("slide=34" in part.get("text", "") for part in seen)
    assert result["key"]["answers"]["q1"]["source"]["image_path"] == str(image)
    assert "image_path" not in json.dumps(result["quiz"])


def test_visual_citation_can_use_attached_image_without_matching_text(monkeypatch, tmp_path):
    slide = {**CHUNK, "slide": 34, "text": "Security? Never heard of it."}
    image = tmp_path / "slide34.png"
    image.write_bytes(b"image bytes")
    monkeypatch.setattr(quiz, "_load_index", lambda path: {
        "chunks": [slide], "pages": [{"doc_id": DOC, "slide": 34, "image_path": str(image)}]})
    real_image_part = quiz.ChatClient.image_part

    class Client:
        image_part = staticmethod(real_image_part)

        def complete(self, messages, max_tokens):
            return json.dumps({"questions": [{"id": "q1", "question": "What is pictured?",
                                             "options": ["A. A warning", "B. A chart", "C. A form", "D. A map"],
                                             "correct": "A", "explanation": "The attached slide depicts a warning.",
                                             "source": {"doc_id": DOC, "slide": 34,
                                                        "section": "Screenshot", "excerpt": "Not indexed text"}}]})

    monkeypatch.setattr(quiz, "ChatClient", Client)
    result = quiz.generate_quiz(DOC, topic="Security?", n=1, save=False)
    source = result["key"]["answers"]["q1"]["source"]
    assert source["slide"] == 34
    assert source["image_path"] == str(image)
    assert "Not indexed text" not in json.dumps(source)


def test_unattached_later_slide_cannot_validate_screenshot_quote(monkeypatch, tmp_path):
    chunks = [{**CHUNK, "slide": slide,
               "text": f"Slide {slide} title only"} for slide in (1, 2, 34)]
    pages = []
    for slide in (1, 2, 34):
        image = tmp_path / f"slide{slide}.png"
        image.write_bytes(b"image bytes")
        pages.append({"doc_id": DOC, "slide": slide, "image_path": str(image)})
    monkeypatch.setattr(quiz, "_load_index", lambda path: {"chunks": chunks, "pages": pages})
    real_image_part = quiz.ChatClient.image_part
    seen = []

    class Client:
        image_part = staticmethod(real_image_part)

        def complete(self, messages, max_tokens):
            seen.extend(messages[1]["content"])
            return json.dumps({"questions": [{"id": "q1", "question": "What does the screenshot say?",
                                             "options": ["A. API keys", "B. Caching", "C. Scaling", "D. Cost"],
                                             "correct": "A", "explanation": "The screenshot mentions API keys.",
                                             "source": {"doc_id": DOC, "slide": 34,
                                                        "excerpt": "API keys exhausted"}}]})

    monkeypatch.setattr(quiz, "ChatClient", Client)
    with pytest.raises(ValueError, match="valid quiz"):
        quiz.generate_quiz(DOC, n=1, save=False)
    assert not any(part.get("text", "").startswith("[IMAGE:")
                   and "slide=34" in part["text"] for part in seen)


def test_unattached_later_slide_allows_exact_text_quote(monkeypatch, tmp_path):
    chunks = [{**CHUNK, "slide": slide,
               "text": f"Slide {slide} title only"} for slide in (1, 2, 34)]
    pages = []
    for slide in (1, 2, 34):
        image = tmp_path / f"slide{slide}.png"
        image.write_bytes(b"image bytes")
        pages.append({"doc_id": DOC, "slide": slide, "image_path": str(image)})
    monkeypatch.setattr(quiz, "_load_index", lambda path: {"chunks": chunks, "pages": pages})
    real_image_part = quiz.ChatClient.image_part

    class Client:
        image_part = staticmethod(real_image_part)

        def complete(self, messages, max_tokens):
            return json.dumps({"questions": [{"id": "q1", "question": "What is slide 34 titled?",
                                             "options": ["A. Slide 34 title only", "B. No title", "C. Slide 1", "D. Slide 2"],
                                             "correct": "A", "explanation": "The provided text states the title.",
                                             "source": {"doc_id": DOC, "slide": 34,
                                                        "excerpt": "Slide 34 title only"}}]})

    monkeypatch.setattr(quiz, "ChatClient", Client)
    result = quiz.generate_quiz(DOC, n=1, save=False)
    source = result["key"]["answers"]["q1"]["source"]
    assert source["slide"] == 34
    assert "image_path" not in source


def test_visual_citation_cannot_substitute_a_different_slide(monkeypatch, tmp_path):
    image = tmp_path / "slide12.png"
    image.write_bytes(b"image bytes")
    monkeypatch.setattr(quiz, "_load_index", lambda path: {
        "chunks": [CHUNK], "pages": [{"doc_id": DOC, "slide": 12, "image_path": str(image)}]})
    real_image_part = quiz.ChatClient.image_part

    class Client:
        image_part = staticmethod(real_image_part)

        def complete(self, messages, max_tokens):
            bad = json.loads(_model_reply())
            bad["questions"][0]["source"] = {"doc_id": DOC, "slide": 13}
            return json.dumps(bad)

    monkeypatch.setattr(quiz, "ChatClient", Client)
    with pytest.raises(ValueError, match="valid quiz"):
        quiz.generate_quiz(DOC, topic="Prompt caching", n=1, save=False)


def test_score_cli_reveal_shows_original_image_path(monkeypatch, tmp_path, capsys):
    public = {"quiz_id": "visual", "questions": [{"id": "q1", "question": "Q?",
                                                   "options": ["A", "B", "C", "D"]}]}
    key = {"answers": {"q1": {"correct": 0, "explanation": "Shown on slide.",
                              "source": {"doc_id": DOC, "slide": 34,
                                         "excerpt": "[Original page/slide image]",
                                         "image_path": str(tmp_path / "slide34.png")}}}}
    qp, kp = tmp_path / "quiz.json", tmp_path / "key.json"
    qp.write_text(json.dumps(public), encoding="utf-8")
    kp.write_text(json.dumps(key), encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["quiz.py", "score", str(qp), str(kp), "{}", "--reveal"])
    quiz.main()
    assert str(tmp_path / "slide34.png") in capsys.readouterr().out
