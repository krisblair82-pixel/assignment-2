"""Gradio application for the MBAX 6418 course assistant."""
from __future__ import annotations

import json
import os

import gradio as gr

from answers import ask as grounded_ask
from config import INDEX_DIR


TITLE = "MBAX 6418 Course Assistant"


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


def answer_question(question: str, document: str | None = None) -> tuple[str, str]:
    """Answer one UI question through the grounded backend."""
    if not isinstance(question, str) or not question.strip():
        return "", "Please enter a question before clicking Ask."
    try:
        result = grounded_ask(question.strip(), doc_filter=document or None)
    except Exception:
        # Do not expose backend details, credentials, or raw service errors in
        # the browser. The CLI remains the place for local diagnostics.
        return "", "Unable to answer this question. Check the local index and configuration."

    answer = result.get("answer", "NOT_COVERED")
    status = _format_sources(result.get("sources", []))
    if not result.get("covered", False):
        status = f"**Coverage:** The indexed materials do not verify an answer.\n\n{status}"
    return answer, status


def create_app() -> gr.Blocks:
    """Build and return the course-assistant interface."""
    with gr.Blocks(title=TITLE) as app:
        gr.Markdown(
            "# MBAX 6418 Course Assistant\n"
            "Ask grounded questions or create a practice quiz from indexed "
            "course materials."
        )

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
            ask_button.click(
                fn=answer_question,
                inputs=[question, document],
                outputs=[answer, ask_status],
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
            quiz_button.click(
                fn=None,
                inputs=[quiz_document, topic, quiz_questions],
                outputs=[quiz_output, quiz_status],
            )

        gr.Markdown(
            "**Status:** Grounded question answering is connected. Quiz "
            "generation will be connected next."
        )

    return app


if __name__ == "__main__":
    create_app().launch()
