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


def _location_matches(expected: dict, actual: dict) -> bool:
    return ((expected.get("slide") is None or expected.get("slide") == actual.get("slide"))
            and (expected.get("page") is None or expected.get("page") == actual.get("page"))
            and (expected.get("doc_id") is None or expected.get("doc_id") == actual.get("doc_id")))


def _sources_supported(expected: list[dict], sources: list[dict], expected_not_covered: bool) -> bool:
    if expected_not_covered:
        return not sources
    return bool(expected) and any(
        _location_matches(item, source)
        for item in expected for source in sources
    )


def evaluate_case(case: dict, index_path: str,
                  enabled_legs: set | None = None) -> dict:
    question = case["question"]
    doc_filter = case.get("doc_filter")
    started = time.perf_counter()
    evidence = retrieve(question, doc_filter=doc_filter, k=8, index_path=index_path,
                        enabled_legs=enabled_legs)
    retrieved = evidence.get("text_chunks", []) + evidence.get("pages", [])
    expected_sources = case.get("expected_sources", [])
    retrieval_hit = _expected_hit(expected_sources, retrieved)

    result = ask(question, doc_filter=doc_filter, index_path=index_path,
                 enabled_legs=enabled_legs)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    answer_text = (result.get("answer") or "").strip()
    normalized = answer_text.upper()
    expected_not_covered = case.get("expected_answer") == "NOT_COVERED"
    returned_not_covered = normalized == "NOT_COVERED" or normalized.startswith("NOT_COVERED ")
    schema_issues = result.get("validation", {}).get("schema_issues", [])
    required_terms = [str(term).lower() for term in case.get("required_answer_terms", [])]
    answer_correct = ((expected_not_covered and returned_not_covered)
                      or (not expected_not_covered and not returned_not_covered
                          and all(term in answer_text.lower() for term in required_terms)))
    sources_supported = _sources_supported(expected_sources, result.get("sources", []),
                                           expected_not_covered)
    answer_grounded = not schema_issues and (
        (expected_not_covered and returned_not_covered and not result.get("sources"))
        or (not expected_not_covered and result.get("covered") and bool(result.get("sources")))
    )

    return {
        "id": case["id"],
        "question": question,
        "elapsed_ms": elapsed_ms,
        "retrieval": {
            "source_hit": retrieval_hit,
            "legs": evidence.get("legs", {}),
            "locations": [_location(item) for item in retrieved],
        },
        "answer": {
            "covered": bool(result.get("covered")),
            "returned_not_covered": returned_not_covered,
            "expected_not_covered": expected_not_covered,
            "correct": answer_correct,
            "sources_supported": sources_supported,
            "grounded": answer_grounded,
            "source_locations": [_location(item) for item in result.get("sources", [])],
            "schema_issue_count": len(schema_issues),
        },
    }


def run_evals(eval_path: str = DEFAULT_EVAL_PATH,
              index_path: str | None = None,
              output_dir: str = RESULTS_DIR,
              limit: int | None = None,
              mode: str = "hybrid") -> tuple[str, dict]:
    """mode='hybrid' runs all legs; mode='keyword' is the issue-#5 baseline
    (bm25 keyword search only, no dense/visual/rerank)."""
    data = load_eval_set(eval_path)
    index_path = index_path or os.path.join(INDEX_DIR, "index.json")
    enabled_legs = None if mode == "hybrid" else {"bm25"}
    cases = data["questions"][:limit] if limit else data["questions"]
    started_all = time.perf_counter()
    results = [evaluate_case(case, index_path, enabled_legs=enabled_legs)
               for case in cases]
    total_ms = round((time.perf_counter() - started_all) * 1000, 1)
    summary = {
        "mode": mode,
        "cases": len(results),
        "retrieval_hits": sum(item["retrieval"]["source_hit"] for item in results),
        "grounded_answers": sum(item["answer"]["grounded"] for item in results),
        "correct_answers": sum(item["answer"].get("correct", False) for item in results),
        "supported_sources": sum(item["answer"].get("sources_supported", False) for item in results),
        "not_covered_cases": sum(item["answer"].get("expected_not_covered", False) for item in results),
        "not_covered_passes": sum(
            item["answer"].get("expected_not_covered", False)
            and item["answer"].get("returned_not_covered", False)
            and item["answer"].get("grounded", False)
            for item in results
        ),
        "total_time_ms": total_ms,
        "avg_time_ms": round(total_ms / len(results), 1) if results else 0.0,
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


def run_comparison(eval_path: str = DEFAULT_EVAL_PATH,
                   index_path: str | None = None,
                   output_dir: str = RESULTS_DIR,
                   limit: int | None = None) -> tuple[str, dict]:
    """Run hybrid and keyword-only evaluations and save one comparison report."""
    hybrid_path, hybrid = run_evals(eval_path, index_path, output_dir, limit,
                                    mode="hybrid")
    keyword_path, keyword = run_evals(eval_path, index_path, output_dir, limit,
                                      mode="keyword")
    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "eval_set": os.path.basename(eval_path),
        "index": os.path.basename(index_path or os.path.join(INDEX_DIR, "index.json")),
        "modes": ["hybrid", "keyword"],
        "runs": {
            "hybrid": {"path": os.path.basename(hybrid_path),
                        "summary": hybrid["summary"]},
            "keyword": {"path": os.path.basename(keyword_path),
                         "summary": keyword["summary"]},
        },
    }
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(
        output_dir, f"comparison_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2)
    return output_path, report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run retrieval and grounded-answer evaluations")
    parser.add_argument("--eval-set", default=DEFAULT_EVAL_PATH)
    parser.add_argument("--index", default=os.path.join(INDEX_DIR, "index.json"))
    parser.add_argument("--output-dir", default=RESULTS_DIR)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--mode", choices=["hybrid", "keyword"], default="hybrid",
                        help="hybrid = all legs; keyword = bm25-only baseline (issue #5)")
    parser.add_argument("--compare", action="store_true",
                        help="run hybrid and keyword modes and save comparison_*.json")
    args = parser.parse_args()
    if args.compare:
        output_path, report = run_comparison(args.eval_set, args.index, args.output_dir,
                                             args.limit)
        print(f"saved: {output_path}")
        print(json.dumps({mode: report["runs"][mode]["summary"]
                          for mode in report["modes"]}, sort_keys=True))
        return
    output_path, report = run_evals(args.eval_set, args.index, args.output_dir,
                                    args.limit, mode=args.mode)
    print(f"saved: {output_path}")
    print(json.dumps(report["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
