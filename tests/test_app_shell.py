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
