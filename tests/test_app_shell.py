"""Smoke tests for the Gradio application shell."""


def test_create_app_returns_course_assistant_interface():
    from app import create_app

    app = create_app()

    assert app is not None
    assert app.title == "MBAX 6418 Course Assistant"


def test_app_shell_has_question_and_quiz_sections():
    from app import create_app

    app = create_app()
    labels = [component.label for component in app.blocks.values()
              if getattr(component, "label", None)]

    assert "Question" in labels
    assert "Document" in labels
    assert "Topic filter" in labels
    assert "Quiz questions" in labels


def test_app_shell_explains_accepted_material_formats():
    from app import ACCEPTED_FORMATS, create_app

    rendered_values = [getattr(component, "value", "")
                       for component in create_app().blocks.values()]

    assert "PDF" in ACCEPTED_FORMATS
    assert ".pptx" in ACCEPTED_FORMATS
    assert ".docx" in ACCEPTED_FORMATS
    assert ACCEPTED_FORMATS in rendered_values


def test_document_handlers_update_dropdown_choices_not_values(monkeypatch):
    import app

    monkeypatch.setattr(app, "_available_documents",
                        lambda: ["week2.pptx", "week3.pptx"])
    monkeypatch.setattr(app, "_docs_table", lambda: [])

    status, table, ask_update, quiz_update = app.add_documents_ui(None)

    assert status == "No file selected."
    assert table == []
    assert ask_update["choices"] == ["week2.pptx", "week3.pptx"]
    assert ask_update["value"] == "week2.pptx"
    assert quiz_update["choices"] == ask_update["choices"]


def test_batch_document_upload_rebuilds_search_once(monkeypatch):
    import app

    rebuilds = []
    added = []

    def fake_add(path, orig_name=None, rebuild=True):
        added.append((orig_name, rebuild))
        return True, f"Added {orig_name}", orig_name

    monkeypatch.setattr(app.documents, "add_document", fake_add)
    monkeypatch.setattr(app.documents, "_rebuild_indexes",
                        lambda: rebuilds.append(True))
    monkeypatch.setattr(app, "_available_documents",
                        lambda: ["one.txt", "two.txt"])
    monkeypatch.setattr(app, "_docs_table", lambda: [])

    status, _, _, _ = app.add_documents_ui([
        {"name": "one.txt", "orig_name": "one.txt"},
        {"name": "two.txt", "orig_name": "two.txt"},
    ])

    assert added == [("one.txt", False), ("two.txt", False)]
    assert rebuilds == [True]
    assert "batch upload" in status.lower()
