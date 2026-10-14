"""Gradio application for the MBAX 6418 course assistant."""
from __future__ import annotations

import json
import os

import gradio as gr

from answers import ask as grounded_ask
from config import INDEX_DIR
from quiz import generate_quiz as generate_quiz_backend, score_quiz as score_quiz_backend


TITLE = "MBAX 6418 Course Assistant"
ACCEPTED_FORMATS = (
    "**Accepted course-material formats:** PDF, PowerPoint (`.pptx`, `.ppt`), "
    "Word (`.docx`), and plain text (`.txt`). Add files to the local "
    "`materials/` folder and run ingestion before using the assistant."
)
_QUIZ_SESSIONS: dict[str, dict] = {}


def _available_documents(index_path: str | None = None) -> list[str]:
    """Return indexed document IDs without requiring a live model service."""
    path = index_path or os.path.join(INDEX_DIR, "index.json")
    if not os.path.isfile(path):
        return []
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return []
    return sorted({chunk.get("doc_id") for chunk in data.get("chunks", [])
                   if chunk.get("doc_id")})


def _format_sources(sources: list[dict]) -> str:
    """Render verified source locations and excerpts for the answer panel."""
    if not sources:
        return "No verified sources were returned."
    lines = ["**Verified sources:**"]
    for source in sources:
        location = [f"doc `{source.get('doc_id', 'unknown')}`"]
        if source.get("page") is not None:
            location.append(f"page {source['page']}")
        if source.get("slide") is not None:
            location.append(f"slide {source['slide']}")
        if source.get("section"):
            location.append(f"section `{source['section']}`")
        lines.append(f"- {', '.join(location)}")
        if source.get("excerpt"):
            lines.append(f"  > {source['excerpt']}")
    return "\n".join(lines)


def answer_question(question: str, document: str | None = None) -> tuple[str, str, list[str]]:
    """Answer one UI question through the grounded backend."""
    if not isinstance(question, str) or not question.strip():
        return "", "Please enter a question before clicking Ask.", []
    try:
        result = grounded_ask(question.strip(), doc_filter=document or None)
    except Exception:
        # Do not expose backend details, credentials, or raw service errors in
        # the browser. The CLI remains the place for local diagnostics.
        return "", "Unable to answer this question. Check the local index and configuration.", []

    answer = result.get("answer", "NOT_COVERED")
    status = _format_sources(result.get("sources", []))
    evidence = [source["image_path"] for source in result.get("sources", [])
                if isinstance(source.get("image_path"), str)
                and os.path.isfile(source["image_path"])]
    if not result.get("covered", False):
        status = f"**Coverage:** The indexed materials do not verify an answer.\n\n{status}"
    return answer, status, evidence


def _format_quiz(quiz: dict) -> str:
    """Render only the public quiz artifact; never render its private key."""
    lines = [f"### Practice quiz — `{quiz.get('doc_id', 'selected document')}`"]
    if quiz.get("topic"):
        lines.append(f"**Topic:** {quiz['topic']}")
    lines.append("")
    for number, question in enumerate(quiz.get("questions", []), 1):
        lines.append(f"**{number}. {question.get('question', '')}**")
        lines.extend(f"- {option}" for option in question.get("options", []))
        lines.append("")
    return "\n".join(lines).strip()


def generate_quiz_ui(document: str | None, topic: str | None,
                     question_count: int | float = 5) -> tuple[str, str, str]:
    """Generate and render a quiz while keeping its answer key private."""
    if not document:
        return "", "Please select a document before generating a quiz.", ""
    try:
        count = max(1, min(10, int(question_count)))
        result = generate_quiz_backend(
            document,
            topic=topic.strip() if isinstance(topic, str) and topic.strip() else None,
            n=count,
        )
    except Exception:
        # Keep credentials, prompts, and backend details out of browser output.
        return "", "Unable to generate this quiz. Check the local index and configuration.", ""

    quiz = result.get("quiz", {})
    questions = quiz.get("questions", [])
    quiz_id = quiz.get("quiz_id", "")
    if quiz_id:
        # Keep the key server-side; only the opaque quiz ID enters Gradio state.
        _QUIZ_SESSIONS[quiz_id] = {"quiz": quiz, "key": result.get("key", {})}
    status = f"Generated {len(questions)} question(s) from `{document}`. Answers remain hidden."
    if result.get("issues"):
        status += " Some model-generated items were omitted during validation."
    return _format_quiz(quiz), status, quiz_id


def _format_score(result: dict, reveal: bool) -> str:
    """Render score details, revealing solutions only when requested."""
    lines = [f"### Score: {result['score']}/{result['total']} ({result['pct']}%)", ""]
    for item in result.get("per_question", []):
        mark = "Correct" if item.get("ok") else "Incorrect"
        lines.append(f"- **{item['id']} — {mark}**")
        if item.get("student") is None:
            lines.append("  - Unanswered")
        if reveal and item.get("explanation"):
            lines.append(f"  - Explanation: {item['explanation']}")
            source = item.get("source") or {}
            location = [f"doc `{source.get('doc_id', 'unknown')}`"]
            if source.get("page") is not None:
                location.append(f"page {source['page']}")
            if source.get("slide") is not None:
                location.append(f"slide {source['slide']}")
            lines.append(f"  - Source: {', '.join(location)}")
    return "\n".join(lines)


def score_quiz_ui(quiz_id: str | None, answers_json: str,
                  reveal: bool = False) -> tuple[str, str]:
    """Score JSON answers against a server-side key."""
    session = _QUIZ_SESSIONS.get(quiz_id or "")
    if session is None:
        return "", "Generate a quiz before submitting answers."
    try:
        answers = json.loads(answers_json or "{}")
        if not isinstance(answers, dict):
            raise ValueError
        result = score_quiz_backend(session["quiz"], session["key"], answers, reveal=reveal)
    except (TypeError, ValueError, json.JSONDecodeError):
        return "", "Enter answers as a JSON object such as `{\"q1\": 0}`."
    status = "Scored submission."
    if reveal:
        status += " Solutions and explanations were revealed."
    else:
        status += " Solutions remain hidden for unanswered questions."
    return _format_score(result, reveal), status


def create_app() -> gr.Blocks:
    """Build and return the course-assistant interface."""
    with gr.Blocks(title=TITLE) as app:
        gr.Markdown(
            "# MBAX 6418 Course Assistant\n"
            "Ask grounded questions or create a practice quiz from indexed "
            "course materials."
        )
        gr.Markdown(ACCEPTED_FORMATS)

        with gr.Tab("Ask a question"):
            question = gr.Textbox(
                label="Question",
                placeholder="Ask a question about the course materials...",
                lines=3,
            )
            document = gr.Dropdown(
                choices=_available_documents(),
                label="Document",
                info="Leave blank to search all indexed documents.",
            )
            ask_button = gr.Button("Ask", variant="primary")
            answer = gr.Markdown(label="Answer")
            ask_status = gr.Markdown()
            evidence = gr.Gallery(
                label="Original page/slide evidence",
                columns=2,
                height="auto",
            )
            ask_button.click(
                fn=answer_question,
                inputs=[question, document],
                outputs=[answer, ask_status, evidence],
            )

        with gr.Tab("Practice quiz"):
            quiz_document = gr.Dropdown(
                choices=_available_documents(),
                label="Document",
            )
            topic = gr.Textbox(
                label="Topic filter",
                placeholder="Optional topic or phrase",
            )
            quiz_questions = gr.Slider(
                minimum=1,
                maximum=10,
                value=5,
                step=1,
                label="Quiz questions",
            )
            quiz_button = gr.Button("Generate quiz", variant="primary")
            quiz_output = gr.Markdown()
            quiz_status = gr.Markdown()
            quiz_id_state = gr.State("")
            quiz_button.click(
                fn=generate_quiz_ui,
                inputs=[quiz_document, topic, quiz_questions],
                outputs=[quiz_output, quiz_status, quiz_id_state],
            )

            answers_json = gr.Textbox(
                label="Your answers (JSON)",
                placeholder='Example: {"q1": 0, "q2": 2}',
                lines=2,
            )
            reveal = gr.Checkbox(label="Reveal solutions and explanations", value=False)
            score_button = gr.Button("Submit answers")
            score_output = gr.Markdown()
            score_status = gr.Markdown()
            score_button.click(
                fn=score_quiz_ui,
                inputs=[quiz_id_state, answers_json, reveal],
                outputs=[score_output, score_status],
            )

        gr.Markdown(
            "**Status:** Grounded question answering is connected. Quiz "
            "generation is connected; scoring will be connected next."
        )

    return app


if __name__ == "__main__":
    create_app().launch()
