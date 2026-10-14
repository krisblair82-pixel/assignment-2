"""Repeatable retrieval and grounded-answer evaluation runner.

Usage:
    python run_evals.py
    python run_evals.py --limit 3 --output-dir results

The report stores locations and pass/fail metrics, not raw model output or
credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import time

from answers import ask
from config import INDEX_DIR, RESULTS_DIR
from retrieval import retrieve

DEFAULT_EVAL_PATH = os.path.join(RESULTS_DIR, "eval_questions.json")


def load_eval_set(path: str) -> dict:
    with open(path, encoding="utf-8") as handle:
        data = json.load(handle)
    questions = data.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("evaluation set must contain a non-empty questions list")
    ids = [q.get("id") for q in questions]
    if any(not isinstance(item, dict) for item in questions) or len(set(ids)) != len(ids):
        raise ValueError("evaluation questions must be objects with unique IDs")
    return data


def _location(item: dict) -> tuple:
    return item.get("doc_id"), item.get("page"), item.get("slide")


def _expected_hit(expected: list[dict], retrieved: list[dict]) -> bool:
    if not expected:
        return not retrieved
    locations = {_location(item) for item in retrieved}
    return any(
        any(
            (source.get("slide") is None or source.get("slide") == item.get("slide"))
            and (source.get("page") is None or source.get("page") == item.get("page"))
            and (source.get("doc_id") is None or source.get("doc_id") == item.get("doc_id"))
            for item in retrieved
        )
        for source in expected
    )


def evaluate_case(case: dict, index_path: str) -> dict:
    question = case["question"]
    doc_filter = case.get("doc_filter")
    evidence = retrieve(question, doc_filter=doc_filter, k=8, index_path=index_path)
    retrieved = evidence.get("text_chunks", []) + evidence.get("pages", [])
    expected_sources = case.get("expected_sources", [])
    retrieval_hit = _expected_hit(expected_sources, retrieved)

    result = ask(question, doc_filter=doc_filter, index_path=index_path)
    answer_text = (result.get("answer") or "").strip()
    normalized = answer_text.upper()
    expected_not_covered = case.get("expected_answer") == "NOT_COVERED"
    returned_not_covered = normalized == "NOT_COVERED" or normalized.startswith("NOT_COVERED ")
    schema_issues = result.get("validation", {}).get("schema_issues", [])
    answer_grounded = not schema_issues and (
        (expected_not_covered and returned_not_covered and not result.get("sources"))
        or (not expected_not_covered and result.get("covered") and bool(result.get("sources")))
    )

    return {
        "id": case["id"],
        "question": question,
        "retrieval": {
            "source_hit": retrieval_hit,
            "legs": evidence.get("legs", {}),
            "locations": [_location(item) for item in retrieved],
        },
        "answer": {
            "covered": bool(result.get("covered")),
            "returned_not_covered": returned_not_covered,
            "expected_not_covered": expected_not_covered,
            "grounded": answer_grounded,
            "source_locations": [_location(item) for item in result.get("sources", [])],
            "schema_issue_count": len(schema_issues),
        },
    }


def run_evals(eval_path: str = DEFAULT_EVAL_PATH,
              index_path: str | None = None,
              output_dir: str = RESULTS_DIR,
              limit: int | None = None) -> tuple[str, dict]:
    data = load_eval_set(eval_path)
    index_path = index_path or os.path.join(INDEX_DIR, "index.json")
    cases = data["questions"][:limit] if limit else data["questions"]
    results = [evaluate_case(case, index_path) for case in cases]
    summary = {
        "cases": len(results),
        "retrieval_hits": sum(item["retrieval"]["source_hit"] for item in results),
        "grounded_answers": sum(item["answer"]["grounded"] for item in results),
        "not_covered_cases": sum(item["answer"].get("expected_not_covered", False) for item in results),
        "not_covered_passes": sum(
            item["answer"].get("expected_not_covered", False)
            and item["answer"].get("returned_not_covered", False)
            and item["answer"].get("grounded", False)
            for item in results
        ),
    }
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "eval_set": os.path.basename(eval_path),
        "index": os.path.basename(index_path),
        "summary": summary,
        "results": results,
    }
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, f"eval_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    return output_path, report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run retrieval and grounded-answer evaluations")
    parser.add_argument("--eval-set", default=DEFAULT_EVAL_PATH)
    parser.add_argument("--index", default=os.path.join(INDEX_DIR, "index.json"))
    parser.add_argument("--output-dir", default=RESULTS_DIR)
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args()
    output_path, report = run_evals(args.eval_set, args.index, args.output_dir, args.limit)
    print(f"saved: {output_path}")
    print(json.dumps(report["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
