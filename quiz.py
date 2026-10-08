"""Quiz generator (issue #4).

Flow: student picks a document (doc_id) + optional topic filter
  -> that document's chunks are pulled from the index
  -> the vision LLM (9001) writes N multiple-choice questions grounded in
     those excerpts (options + explanation + source citation)
  -> validation + grounding (sources must resolve to the document's chunks)
  -> TWO artifacts:
       quiz_<id>.json      : public - questions + options only (NO answers)
       quiz_key_<id>.json  : hidden - fixed answer key + explanations + sources
  -> scoring uses the stored key; explanations are revealed on request only.

CLI:
  python quiz.py generate --doc DOC_ID [--topic "phrase"] [-n 5] [--save]
  python quiz.py score <quiz.json> <key.json> '{"q1":0,"q2":2,...}' [--reveal]
  python quiz.py docs [--index PATH]     # list available documents
"""
import argparse
import json
import os
import re
import time

from config import INDEX_DIR, RESULTS_DIR, ensure_configured
from retrieval import _load_index
from services import ChatClient
from answers import _extract_json, _resolve_source

MAX_TOKENS = 3000

QUIZ_SYSTEM = (
    "You create multiple-choice practice quizzes from course material excerpts.\n"
    "Rules:\n"
    "1. Base every question and the correct answer ONLY on the provided labeled "
    "excerpts ([SRC n: doc=..., page=..., slide=..., section=...]).\n"
    "2. Each question has EXACTLY 4 options; exactly one is correct.\n"
    "3. Distractors are plausible but clearly wrong per the excerpts.\n"
    "4. The explanation must cite the source as a JSON object with doc_id, page, "
    "slide, section and a short verbatim excerpt.\n"
    "5. Return ONE JSON object:\n"
    '{"questions": [{"id": "q1", "question": "...", "options": ["A. ...", "B. ...", "C. ...", "D. ..."], '
    '"correct": "A", "explanation": "...", "source": {"doc_id": "...", "page": 1, '
    '"slide": null, "section": "...", "excerpt": "..."}}]}'
)


def _topic_chunks(chunks: list[dict], doc_id: str, topic: str | None):
    """Document chunks, optionally restricted to a topic phrase; falls back to
    the whole document (with a note) when nothing matches the topic."""
    doc_chunks = [c for c in chunks if c.get("doc_id") == doc_id]
    if not doc_chunks:
        return [], []
    if not topic:
        return doc_chunks, doc_chunks
    tok = topic.lower()
    matched = [c for c in doc_chunks
               if tok in (c.get("text") or "").lower()
               or tok in (c.get("section") or "").lower()]
    return (matched or doc_chunks), doc_chunks


def _correct_index(correct, options) -> int | None:
    """Accept 'A'/'A.'/0..3 -> option index."""
    if isinstance(correct, bool):
        return None
    if isinstance(correct, int) and 0 <= correct < len(options):
        return correct
    if isinstance(correct, str):
        s = correct.strip().upper()
        m = re.match(r"^([A-D])", s)
        if m:
            return ord(m.group(1)) - ord("A")
        if s.isdigit() and 0 <= int(s) < len(options):
            return int(s)
    return None


def generate_quiz(doc_id: str, topic: str | None = None, n: int = 5,
                  index_path: str | None = None, save: bool = True) -> dict:
    ensure_configured()
    index_path = index_path or os.path.join(INDEX_DIR, "index.json")
    chunks = _load_index(index_path).get("chunks", [])
    available = sorted({c.get("doc_id") for c in chunks})
    selected, doc_chunks = _topic_chunks(chunks, doc_id, topic)
    if not doc_chunks:
        raise SystemExit(f"no chunks for doc '{doc_id}' in {index_path} "
                         f"- available docs: {available}")

    content = []
    for i, c in enumerate(selected[:8], 1):
        label = (f"[SRC {i}: doc={c['doc_id']}, page={c.get('page')}, "
                 f"slide={c.get('slide')}, section={c.get('section')}]")
        content.append({"type": "text", "text": f"{label}\n{c['text']}"})
    content.append({"type": "text",
                    "text": f"Create {n} multiple-choice questions from these excerpts."})
    messages = [{"role": "system", "content": QUIZ_SYSTEM},
                {"role": "user", "content": content}]

    raw = ChatClient().complete(messages, max_tokens=MAX_TOKENS)
    data = _extract_json(raw) or {}
    raw_qs = data.get("questions") or []

    valid, issues = [], []
    for i, q in enumerate(raw_qs):
        if not isinstance(q, dict):
            issues.append(f"item {i}: not an object")
            continue
        question = q.get("question")
        options = q.get("options")
        correct, explanation = q.get("correct"), q.get("explanation")
        src = q.get("source")
        if not question or not isinstance(options, list) or len(options) != 4:
            issues.append(f"item {i}: question/options malformed")
            continue
        idx = _correct_index(correct, options)
        if idx is None:
            issues.append(f"item {i}: 'correct' not resolvable ({correct!r})")
            continue
        if not explanation:
            issues.append(f"item {i}: missing explanation")
            continue
        chunk = _resolve_source(src, doc_chunks) if isinstance(src, dict) else None
        if chunk is None:
            issues.append(f"item {i}: source not grounded {src!r}")
            continue
        valid.append({"id": q.get("id") or f"q{len(valid)+1}", "question": question,
                      "options": options, "idx": idx, "explanation": explanation,
                      "source": {"doc_id": chunk["doc_id"], "page": chunk.get("page"),
                                 "slide": chunk.get("slide"),
                                 "section": chunk.get("section"),
                                 "excerpt": chunk["text"][:300]}})

    valid = valid[:n]
    quiz_id = time.strftime("%Y%m%d_%H%M%S")
    quiz = {"quiz_id": quiz_id, "doc_id": doc_id, "topic": topic, "n": len(valid),
            "questions": [{"id": q["id"], "question": q["question"],
                           "options": q["options"]} for q in valid]}
    key = {"quiz_id": quiz_id,
           "answers": {q["id"]: {"correct": q["idx"], "explanation": q["explanation"],
                                 "source": q["source"]} for q in valid}}

    paths = {}
    if save:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        qp = os.path.join(RESULTS_DIR, f"quiz_{quiz_id}.json")
        kp = os.path.join(RESULTS_DIR, f"quiz_key_{quiz_id}.json")
        with open(qp, "w", encoding="utf-8") as f:
            json.dump(quiz, f, indent=1)
        with open(kp, "w", encoding="utf-8") as f:
            json.dump(key, f, indent=1)
        paths = {"quiz": qp, "key": kp}
    return {"quiz": quiz, "key": key, "issues": issues, "paths": paths}


def score_quiz(quiz: dict, key: dict, answers: dict, reveal: bool = False) -> dict:
    """answers: {qid: option_index}. Returns per-question results + totals."""
    qs = {q["id"]: q for q in quiz.get("questions", [])}
    key_ans = key.get("answers", {})
    per, n_correct = [], 0
    for qid, q in qs.items():
        ka = key_ans.get(qid)
        if ka is None:
            continue
        student = answers.get(qid)
        ok = (student is not None and isinstance(student, int)
              and student == ka["correct"])
        n_correct += 1 if ok else 0
        entry = {"id": qid, "question": q["question"], "options": q["options"],
                 "student": student, "correct": ka["correct"], "ok": ok}
        if reveal:
            entry["explanation"] = ka["explanation"]
            entry["source"] = ka["source"]
        per.append(entry)
    return {"quiz_id": quiz.get("quiz_id"), "score": n_correct,
            "total": len(qs), "pct": round(100 * n_correct / len(qs), 1) if qs else 0.0,
            "per_question": per}


def main():
    ap = argparse.ArgumentParser(description="Practice quiz generator")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("docs", help="list available documents in the index")
    d.add_argument("--index", default=os.path.join(INDEX_DIR, "index.json"))

    g = sub.add_parser("generate", help="create a quiz from a document")
    g.add_argument("--doc", required=True, help="doc_id to quiz on")
    g.add_argument("--topic", default=None, help="optional topic phrase filter")
    g.add_argument("-n", type=int, default=5)
    g.add_argument("--index", default=os.path.join(INDEX_DIR, "index.json"))
    g.add_argument("--no-save", action="store_true")

    s = sub.add_parser("score", help="score answers against the stored key")
    s.add_argument("quiz_file")
    s.add_argument("key_file")
    s.add_argument("answers_json", help='e.g. \'{"q1":0,"q2":2}\'')
    s.add_argument("--reveal", action="store_true", help="show explanations + sources")

    args = ap.parse_args()

    if args.cmd == "docs":
        chunks = _load_index(args.index).get("chunks", [])
        docs = sorted({c.get("doc_id") for c in chunks})
        print("available docs:", docs)
    elif args.cmd == "generate":
        result = generate_quiz(args.doc, topic=args.topic, n=args.n,
                               index_path=args.index, save=not args.no_save)
        quiz = result["quiz"]
        print(f"\nQUIZ {quiz['quiz_id']}  doc={quiz['doc_id']}  topic={quiz['topic']}  "
              f"questions={quiz['n']}")
        for q in quiz["questions"]:
            print(f"\n{q['id']}. {q['question']}")
            for opt in q["options"]:
                print(f"   {opt}")
        if result["issues"]:
            print(f"\nvalidation notes ({len(result['issues'])}): "
                  f"{result['issues'][:4]}")
        if result["paths"]:
            print(f"\nsaved: quiz -> {result['paths']['quiz']}")
            print(f"       key  -> {result['paths']['key']}  (NOT shown - hidden by design)")
    else:
        with open(args.quiz_file, encoding="utf-8") as f:
            quiz = json.load(f)
        with open(args.key_file, encoding="utf-8") as f:
            key = json.load(f)
        answers = json.loads(args.answers_json)
        res = score_quiz(quiz, key, answers, reveal=args.reveal)
        print(f"score: {res['score']}/{res['total']} ({res['pct']}%)")
        for e in res["per_question"]:
            mark = "OK " if e["ok"] else "XX "
            print(f"  {mark}{e['id']}: student={e['student']} correct={e['correct']}")
            if args.reveal:
                print(f"      explanation: {e['explanation']}")
                src = e.get("source") or {}
                loc = f"doc={src.get('doc_id')} page={src.get('page')} sec={src.get('section')}"
                print(f"      source: {loc} :: {(src.get('excerpt') or '')[:100]}")


if __name__ == "__main__":
    main()
