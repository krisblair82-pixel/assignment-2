"""Build the README comparison tables from the latest hybrid + keyword eval
transcripts (results/eval_*.json). Reads the two most recent files that have
'mode' keys, prints markdown for the README.
"""
import glob
import json
import os

RESULTS = os.path.join(os.path.dirname(__file__), "..", "results")


def latest(mode: str) -> dict:
    files = [f for f in glob.glob(os.path.join(RESULTS, "eval_*.json"))]
    cands = []
    for f in files:
        try:
            d = json.load(open(f))
        except Exception:
            continue
        if d.get("summary", {}).get("mode") == mode:
            cands.append((os.path.getmtime(f), f, d))
    if not cands:
        raise SystemExit(f"no eval transcript for mode={mode}")
    cands.sort()
    return cands[-1][2]


def main() -> None:
    hybrid = latest("hybrid")
    keyword = latest("keyword")
    hs, ks = hybrid["summary"], keyword["summary"]
    print("**Design comparison: hybrid (all legs + rerank) vs keyword-only baseline (bm25) "
          "— 16 questions, same files (results/eval_*.json, latest runs).**\n")
    print("| Metric | Hybrid | Keyword-only baseline |")
    print("|---|---|---|")
    print(f"| Retrieval source-hit | {hs['retrieval_hits']}/{hs['cases']} | {ks['retrieval_hits']}/{ks['cases']} |")
    print(f"| Grounded answers | {hs['grounded_answers']}/{hs['cases']} | {ks['grounded_answers']}/{ks['cases']} |")
    print(f"| NOT_COVERED handled correctly | {hs['not_covered_passes']}/{hs['not_covered_cases']} | {ks['not_covered_passes']}/{ks['not_covered_cases']} |")
    print(f"| Total time | {hs['total_time_ms']/1000:.1f}s | {ks['total_time_ms']/1000:.1f}s |")
    print(f"| Avg time per question | {hs['avg_time_ms']} ms | {ks['avg_time_ms']} ms |")
    print(f"| Runs (timestamped) | {hybrid.get('generated_at')} | {keyword.get('generated_at')} |\n")
    print("Per-question retrieval source hits (hybrid then keyword):\n")
    print("| Question | Hybrid hit | Hybrid time | Keyword hit | Keyword time |")
    print("|---|---|---|---|---|")
    by_id_k = {r["id"]: r for r in keyword["results"]}
    for r in hybrid["results"]:
        k = by_id_k.get(r["id"], {})
        print(f"| {r['id']} | {r['retrieval']['source_hit']} | {r['elapsed_ms']} ms | "
              f"{k.get('retrieval', {}).get('source_hit', '?')} | {k.get('elapsed_ms', '?')} ms |")


if __name__ == "__main__":
    main()
