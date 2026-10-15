"""Tests for the repeatable evaluation runner."""


def test_evaluate_case_checks_retrieval_and_grounded_answer(monkeypatch):
    import run_evals

    case = {
        "id": "q01",
        "question": "What is tested?",
        "doc_filter": "week2.pptx",
        "expected_sources": [{"slide": 4, "modality": "text", "terms": ["Free"]}],
    }

    monkeypatch.setattr(
        run_evals,
        "retrieve",
        lambda *args, **kwargs: {
            "text_chunks": [{"doc_id": "week2.pptx", "slide": 4}],
            "pages": [],
            "legs": {"bm25": 1, "text_dense": 1, "visual": 0, "rerank": 1},
        },
    )
    monkeypatch.setattr(
        run_evals,
        "ask",
        lambda *args, **kwargs: {
            "covered": True,
            "answer": "Free to download.",
            "sources": [{"doc_id": "week2.pptx", "slide": 4, "excerpt": "Free to download."}],
            "validation": {"schema_issues": []},
        },
    )

    result = run_evals.evaluate_case(case, "index.json")

    assert result["id"] == "q01"
    assert result["retrieval"]["source_hit"] is True
    assert result["answer"]["covered"] is True
    assert result["answer"]["grounded"] is True


def test_evaluate_case_passes_selected_retrieval_mode_to_answer(monkeypatch):
    import run_evals

    seen = {}
    monkeypatch.setattr(run_evals, "retrieve", lambda *args, **kwargs: {
        "text_chunks": [], "pages": [], "legs": {}
    })

    def fake_ask(*args, **kwargs):
        seen["enabled_legs"] = kwargs.get("enabled_legs")
        return {"covered": False, "answer": "NOT_COVERED", "sources": [],
                "validation": {"schema_issues": []}}

    monkeypatch.setattr(run_evals, "ask", fake_ask)
    run_evals.evaluate_case({"id": "q", "question": "Q",
                             "expected_sources": [],
                             "expected_answer": "NOT_COVERED"},
                            "index.json", enabled_legs={"bm25"})
    assert seen["enabled_legs"] == {"bm25"}


def test_evaluate_case_records_answer_correctness_and_source_support(monkeypatch):
    import run_evals

    monkeypatch.setattr(run_evals, "retrieve", lambda *args, **kwargs: {
        "text_chunks": [{"doc_id": "week2.pptx", "slide": 4,
                          "text": "Free to download and reproducible private."}],
        "pages": [], "legs": {}
    })
    monkeypatch.setattr(run_evals, "ask", lambda *args, **kwargs: {
        "covered": True,
        "answer": "Open weights are free to download, reproducible, and private.",
        "sources": [{"doc_id": "week2.pptx", "slide": 4,
                     "excerpt": "Free to download and reproducible private."}],
        "validation": {"schema_issues": []},
    })

    result = run_evals.evaluate_case({
        "id": "q", "question": "What are open weights?",
        "expected_sources": [{"slide": 4}],
        "required_answer_terms": ["free to download", "reproducible", "private"],
    }, "index.json")

    assert result["answer"]["correct"] is True
    assert result["answer"]["sources_supported"] is True


def test_evaluate_case_accepts_expected_not_covered(monkeypatch):
    import run_evals

    case = {
        "id": "q12",
        "question": "Unknown?",
        "expected_sources": [],
        "expected_answer": "NOT_COVERED",
    }
    monkeypatch.setattr(run_evals, "retrieve", lambda *args, **kwargs: {
        "text_chunks": [], "pages": [], "legs": {}
    })
    monkeypatch.setattr(run_evals, "ask", lambda *args, **kwargs: {
        "covered": False,
        "answer": "NOT_COVERED",
        "sources": [],
        "validation": {"schema_issues": []},
    })

    result = run_evals.evaluate_case(case, "index.json")

    assert result["retrieval"]["source_hit"] is True
    assert result["answer"]["expected_not_covered"] is True
    assert result["answer"]["grounded"] is True


def test_run_evals_writes_timestamped_artifact(monkeypatch, tmp_path):
    import run_evals

    monkeypatch.setattr(run_evals, "load_eval_set", lambda path: {
        "schema_version": 1,
        "questions": [{"id": "q1", "question": "Q", "expected_sources": []}],
    })
    monkeypatch.setattr(run_evals, "evaluate_case",
                        lambda case, index_path, enabled_legs=None: {
        "id": case["id"],
        "retrieval": {"source_hit": True},
        "answer": {"grounded": True},
    })

    output_path, report = run_evals.run_evals("eval.json", "index.json", str(tmp_path))

    assert output_path.startswith(str(tmp_path))
    assert output_path.endswith(".json")
    assert report["summary"]["cases"] == 1


def test_run_comparison_writes_both_modes(monkeypatch, tmp_path):
    import run_evals

    calls = []

    def fake_run(eval_path, index_path, output_dir, limit, mode):
        calls.append(mode)
        return f"{mode}.json", {"summary": {"mode": mode, "cases": 2}}

    monkeypatch.setattr(run_evals, "run_evals", fake_run)
    output_path, report = run_evals.run_comparison(
        "eval.json", "index.json", str(tmp_path)
    )

    assert calls == ["hybrid", "keyword"]
    assert output_path.startswith(str(tmp_path))
    assert output_path.endswith(".json")
    assert report["modes"] == ["hybrid", "keyword"]
    assert report["runs"]["hybrid"]["summary"]["mode"] == "hybrid"
    assert report["runs"]["keyword"]["summary"]["mode"] == "keyword"


def test_readme_documents_one_command_evaluation_invocation():
    from pathlib import Path

    readme = Path(__file__).resolve().parents[1] / "README.md"

    assert "python run_evals.py" in readme.read_text(encoding="utf-8")
