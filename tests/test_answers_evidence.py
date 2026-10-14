"""Offline regression tests for real-slide answer evidence and refusals."""
import json
from pathlib import Path

import answers


class FakeChat:
    def __init__(self, reply):
        self.reply = reply

    def complete(self, messages, max_tokens=None):
        return self.reply


def setup_answer(monkeypatch, tmp_path, reply, cited_slide=34):
    doc = "week-2.pptx"
    chunk = {"doc_id": doc, "page": None, "slide": cited_slide,
             "section": None, "text": "Security? Never heard of it..."}
    images = []
    for slide in (34, 30, 12):
        path = tmp_path / f"slide-{slide}.png"
        path.write_bytes(b"image data")
        images.append({"doc_id": doc, "page": None, "slide": slide,
                       "image_path": str(path)})
    evidence = {"text_chunks": [chunk], "pages": images,
                "legs": {"bm25": 1, "text_dense": 1, "visual": 3, "rerank": 1}}
    monkeypatch.setattr(answers, "ensure_configured", lambda: None)
    monkeypatch.setattr(answers, "retrieve", lambda *args, **kwargs: evidence)
    monkeypatch.setattr(answers, "_load_index", lambda *args: {"chunks": [chunk]})
    monkeypatch.setattr(answers, "ChatClient", lambda: FakeChat(reply))
    return images


def test_visual_citation_includes_original_attached_slide(monkeypatch, tmp_path):
    reply = json.dumps({"answer": "The creator came under attack.",
                        "sources": [{"doc_id": "week-2.pptx", "slide": 34,
                                     "page": None, "section": None,
                                     "excerpt": "Security?"}]})
    images = setup_answer(monkeypatch, tmp_path, reply)
    result = answers.ask("What do the screenshots show?", index_path="synthetic.json")
    assert result["sources"][0]["image_path"] == images[0]["image_path"]
    assert Path(result["sources"][0]["image_path"]).is_file()


def test_duplicate_citations_of_same_slide_are_collapsed(monkeypatch, tmp_path):
    citation = {"doc_id": "week-2.pptx", "slide": 34, "page": None,
                "excerpt": "Security?"}
    setup_answer(monkeypatch, tmp_path, json.dumps({
        "answer": "The slide shows a security incident.",
        "sources": [citation, citation, citation]}))
    result = answers.ask("What happened?", index_path="synthetic.json")
    assert len(result["sources"]) == 1
    assert result["sources"][0]["slide"] == 34


def test_images_used_counts_only_images_sent_to_model(monkeypatch, tmp_path):
    setup_answer(monkeypatch, tmp_path, 'NOT_COVERED')
    result = answers.ask("Unrelated?", index_path="synthetic.json")
    # the top text chunk cites slide 34 -> its image is attached first, then
    # the visual hits fill the cap of 3
    assert result["pages_used"] == 3


def test_no_evidence_reports_zero_images(monkeypatch):
    monkeypatch.setattr(answers, "ensure_configured", lambda: None)
    monkeypatch.setattr(answers, "retrieve", lambda *args, **kwargs: {
        "text_chunks": [], "pages": [], "legs": {}})
    result = answers.ask("Absent?", index_path="synthetic.json")
    assert result["covered"] is False
    assert result["pages_used"] == 0


def test_plain_not_covered_is_a_clean_refusal(monkeypatch, tmp_path):
    setup_answer(monkeypatch, tmp_path, "\n\nNOT_COVERED")
    result = answers.ask("When is Assignment 3 due?", index_path="synthetic.json")
    assert result["answer"] == "NOT_COVERED"
    assert result["covered"] is False
    assert result["sources"] == []
    assert result["validation"]["schema_issues"] == []


def test_missing_answer_fails_closed_instead_of_crashing(monkeypatch, tmp_path):
    setup_answer(monkeypatch, tmp_path, '{"sources": []}')
    result = answers.ask("What does the slide say?", index_path="synthetic.json")
    assert result["covered"] is False
    assert result["answer"].startswith("NOT_COVERED")
    assert result["validation"]["schema_issues"]


def test_claim_without_valid_citation_fails_closed(monkeypatch, tmp_path):
    reply = json.dumps({"answer": "The deadline is Friday.",
                        "sources": [{"doc_id": "week-2.pptx", "slide": 99,
                                     "excerpt": "Friday"}]})
    setup_answer(monkeypatch, tmp_path, reply)
    result = answers.ask("What is the deadline?", index_path="synthetic.json")
    assert result["covered"] is False
    assert result["sources"] == []
    assert result["validation"]["dropped_sources"]


def test_doc_only_citation_without_matching_excerpt_is_rejected(monkeypatch, tmp_path):
    reply = json.dumps({"answer": "A made-up claim.",
                        "sources": [{"doc_id": "week-2.pptx", "section": "",
                                     "excerpt": "something never stated"}]})
    setup_answer(monkeypatch, tmp_path, reply)
    result = answers.ask("What does it say?", index_path="synthetic.json")
    assert result["covered"] is False
    assert result["sources"] == []


def test_numeric_excerpt_is_rejected_without_crashing(monkeypatch, tmp_path):
    reply = json.dumps({"answer": "A made-up claim.",
                        "sources": [{"doc_id": "week-2.pptx", "section": "",
                                     "excerpt": 123}]})
    setup_answer(monkeypatch, tmp_path, reply)
    result = answers.ask("What does it say?", index_path="synthetic.json")
    assert result["covered"] is False
    assert result["sources"] == []


def test_not_covered_discards_model_supplied_sources(monkeypatch, tmp_path):
    reply = json.dumps({"answer": "NOT_COVERED",
                        "sources": [{"doc_id": "week-2.pptx", "slide": 34,
                                     "excerpt": "Security?"}]})
    setup_answer(monkeypatch, tmp_path, reply)
    result = answers.ask("Unknown?", index_path="synthetic.json")
    assert result["covered"] is False
    assert result["sources"] == []


def test_image_prompt_labels_each_slide(monkeypatch, tmp_path):
    images = setup_answer(monkeypatch, tmp_path, "NOT_COVERED")
    messages = answers.build_messages([], images, "What does this show?")
    parts = messages[1]["content"]
    assert len([p for p in parts if p["type"] == "image_url"]) == 2
    assert any(p["type"] == "text" and "slide=34" in p["text"] for p in parts)
    assert any(p["type"] == "text" and "slide=30" in p["text"] for p in parts)
    assert not any(p["type"] == "text" and "slide=12" in p["text"] for p in parts)


def test_cited_slide_gets_its_own_retrieved_image_not_another_slide(monkeypatch, tmp_path):
    """Requirement 2a: a source citing slide 12 is shown slide 12's ORIGINAL
    image when that image is a retrieved candidate - and never the image of a
    different slide (no mislabeling)."""
    reply = json.dumps({"answer": "The source mentions security.",
                        "sources": [{"doc_id": "week-2.pptx", "slide": 12,
                                     "page": None, "excerpt": "Security?"}]})
    images = setup_answer(monkeypatch, tmp_path, reply, cited_slide=12)
    result = answers.ask("What does this show?", index_path="synthetic.json")
    assert result["sources"][0]["image_path"] == str(tmp_path / "slide-12.png")
    assert result["sources"][0]["image_path"] != images[0]["image_path"]  # not slide 34


def test_image_only_slide_uses_its_image_not_another_slide_text(monkeypatch, tmp_path):
    reply = json.dumps({"answer": "The image depicts a warning.",
                        "sources": [{"doc_id": "week-2.pptx", "slide": 34,
                                     "page": None, "excerpt": "warning"}]})
    images = setup_answer(monkeypatch, tmp_path, reply, cited_slide=12)
    result = answers.ask("What is shown in the screenshot?", index_path="synthetic.json")
    assert len(result["sources"]) == 1
    assert result["sources"][0]["slide"] == 34
    assert result["sources"][0]["image_path"] == images[0]["image_path"]
    assert "Security? Never heard" not in result["sources"][0]["excerpt"]


class SequenceChat:
    """FakeChat that returns a list of replies in order and counts calls."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = 0

    def complete(self, messages, max_tokens=None):
        reply = self.replies[min(self.calls, len(self.replies) - 1)]
        self.calls += 1
        return reply


def _setup_topic_chunk(monkeypatch, tmp_path, chunk, images):
    """Evidence with a custom chunk; returns the SequenceChat instance."""
    evidence = {"text_chunks": [chunk], "pages": images,
                "legs": {"bm25": 1, "text_dense": 1, "visual": len(images),
                         "rerank": 1}}
    monkeypatch.setattr(answers, "ensure_configured", lambda: None)
    monkeypatch.setattr(answers, "retrieve", lambda *args, **kwargs: evidence)
    monkeypatch.setattr(answers, "_load_index", lambda *args: {"chunks": [chunk]})
    chat = SequenceChat(["NOT_COVERED"])
    monkeypatch.setattr(answers, "ChatClient", lambda: chat)
    return chat


def test_not_covered_with_matching_evidence_retries_once(monkeypatch, tmp_path):
    """Flaky-boundary guard: when the evidence clearly matches the question,
    a NOT_COVERED first answer triggers EXACTLY ONE retry, and a grounded
    second answer is kept."""
    doc = "week-2.pptx"
    chunk = {"doc_id": doc, "page": None, "slide": 34, "section": None,
             "text": "Vibe coding on prod requires review, security and testing."}
    images = [{"doc_id": doc, "page": None, "slide": 34,
               "image_path": str(tmp_path / "slide-34.png")}]
    (tmp_path / "slide-34.png").write_bytes(b"png")
    chat = _setup_topic_chunk(monkeypatch, tmp_path, chunk, images)
    chat.replies = [
        "NOT_COVERED",
        json.dumps({"answer": "The meme slide is 34.",
                    "sources": [{"doc_id": doc, "slide": 34,
                                 "excerpt": "Vibe coding on prod"}]}),
    ]
    result = answers.ask("Vibe coding on prod meme slide?",
                         index_path="synthetic.json")
    assert chat.calls == 2
    assert result["covered"] is True
    assert result["sources"][0]["slide"] == 34


def test_uncovered_question_does_not_retry(monkeypatch, tmp_path):
    """A genuinely uncovered question (no keyword overlap with the evidence)
    stays a clean NOT_COVERED with a single model call."""
    doc = "week-2.pptx"
    chunk = {"doc_id": doc, "page": None, "slide": 34, "section": None,
             "text": "Security? Never heard of it... API keys maxed out."}
    images = [{"doc_id": doc, "page": None, "slide": 34,
               "image_path": str(tmp_path / "slide-34.png")}]
    (tmp_path / "slide-34.png").write_bytes(b"png")
    chat = _setup_topic_chunk(monkeypatch, tmp_path, chunk, images)
    result = answers.ask("What was the instructor's favorite programming "
                         "language in high school?", index_path="synthetic.json")
    assert chat.calls == 1  # no retry
    assert result["covered"] is False
    assert result["answer"] == "NOT_COVERED"


def test_cli_shows_image_evidence_path(monkeypatch, capsys, tmp_path):
    path = str(tmp_path / "slide-34.png")
    monkeypatch.setattr(answers, "ask", lambda *args, **kwargs: {
        "covered": True, "legs": {}, "pages_used": 1, "answer": "Supported",
        "sources": [{"doc_id": "week-2.pptx", "page": None, "slide": 34,
                     "section": None, "excerpt": "Title", "image_path": path}],
        "validation": {"schema_issues": []}})
    monkeypatch.setattr("sys.argv", ["answers.py", "What happened?"])
    answers.main()
    assert path in capsys.readouterr().out
