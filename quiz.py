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
    "excerpts ([SRC n: doc=..., page=..., slide=..., section=...]) and labeled "
    "original slide/page images. For visual details, inspect the image itself.\n"
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
    """Document chunks, optionally restricted to a topic phrase."""
    doc_chunks = [c for c in chunks if c.get("doc_id") == doc_id]
    if not doc_chunks:
        return [], []
    if not topic:
        return doc_chunks, doc_chunks
    tok = topic.lower()
    matched = [c for c in doc_chunks
               if tok in (c.get("text") or "").lower()
               or tok in (c.get("section") or "").lower()]
    return matched, doc_chunks


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
    data = _load_index(index_path)
    chunks = data.get("chunks", [])
    pages = data.get("pages", [])
    available = sorted({c.get("doc_id") for c in chunks})
    selected, doc_chunks = _topic_chunks(chunks, doc_id, topic)
    if not doc_chunks:
        raise SystemExit(f"no chunks for doc '{doc_id}' in {index_path} "
                         f"- available docs: {available}")
    if topic and not selected:
        raise ValueError("topic has no matching excerpts in the selected document")

    content = []
    provided_chunks = selected[:8]
    for i, c in enumerate(provided_chunks, 1):
        label = (f"[SRC {i}: doc={c['doc_id']}, page={c.get('page')}, "
                 f"slide={c.get('slide')}, section={c.get('section')}]")
        content.append({"type": "text", "text": f"{label}\n{c['text']}"})
    attached_pages = []
    for page in pages:
        if len(attached_pages) >= 2:
            break
        if (page.get("doc_id") == doc_id and page.get("image_path")
                and os.path.isfile(page["image_path"])
                and any(c.get("page") == page.get("page")
                        and c.get("slide") == page.get("slide")
                        for c in provided_chunks)):
            attached_pages.append(page)
            content.append({"type": "text", "text":
                            f"[IMAGE: doc={doc_id}, page={page.get('page')}, "
                            f"slide={page.get('slide')}]"})
            content.append(ChatClient.image_part(page["image_path"]))
    content.append({"type": "text",
                    "text": f"Create {n} multiple-choice questions from these excerpts and images."})
    messages = [{"role": "system", "content": QUIZ_SYSTEM},
                {"role": "user", "content": content}]

    client = ChatClient()
    raw_qs = []
    for budget in (MAX_TOKENS, MAX_TOKENS * 3):
        data = _extract_json(client.complete(messages, max_tokens=budget))
        if isinstance(data, dict) and isinstance(data.get("questions"), list):
            raw_qs = data["questions"]
            if raw_qs:
                break
    if not raw_qs:
        raise ValueError("Could not generate a valid quiz from the selected material.")

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
        chunk = _resolve_source(src, provided_chunks) if isinstance(src, dict) else None
        image = None
        if chunk is None and isinstance(src, dict):
            # Screenshot facts can be absent from extracted text. Only accept
            # the exact original image actually supplied to the model.
            image = next((p for p in attached_pages
                          if src.get("doc_id") == p.get("doc_id")
                          and (src.get("page") is not None or src.get("slide") is not None)
                          and (src.get("page") is None or src["page"] == p.get("page"))
                          and (src.get("slide") is None or src["slide"] == p.get("slide"))), None)
        if chunk is None and image is None:
            issues.append(f"item {i}: source not grounded")
            continue
        if chunk is None:
            source = {"doc_id": doc_id, "page": image.get("page"),
                      "slide": image.get("slide"), "section": None,
                      "excerpt": "[Original page/slide image]",
                      "image_path": image["image_path"]}
        else:
            attached = next((p for p in attached_pages
                             if p.get("page") == chunk.get("page")
                             and p.get("slide") == chunk.get("slide")), None)
            if attached is None:
                excerpt = src.get("excerpt")
                if (not isinstance(excerpt, str) or not excerpt.strip()
                        or excerpt.strip() not in chunk["text"]):
                    issues.append(f"item {i}: citation needs indexed text or an attached image")
                    continue
            source = {"doc_id": chunk["doc_id"], "page": chunk.get("page"),
                      "slide": chunk.get("slide"), "section": chunk.get("section"),
                      "excerpt": chunk["text"][:300]}
            if attached is not None:
                source["image_path"] = attached["image_path"]
        valid.append({"id": q.get("id") or f"q{len(valid)+1}", "question": question,
                      "options": options, "idx": idx, "explanation": explanation,
                      "source": source})

    valid = valid[:n]
    if not valid:
        raise ValueError("Could not generate a valid quiz from the selected material.")
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
        submitted = (isinstance(student, int) and not isinstance(student, bool)
                     and 0 <= student < len(q["options"]))
        ok = submitted and student == ka["correct"]
        n_correct += 1 if ok else 0
        entry = {"id": qid, "question": q["question"], "options": q["options"],
                 "student": student, "ok": ok}
        if submitted or reveal:
            entry["correct"] = ka["correct"]
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
            if "correct" in e:
                print(f"  {mark}{e['id']}: student={e['student']} correct={e['correct']}")
            else:
                print(f"  {mark}{e['id']}: unanswered (answer hidden)")
            if args.reveal:
                print(f"      explanation: {e['explanation']}")
                src = e.get("source") or {}
                loc = (f"doc={src.get('doc_id')} page={src.get('page')} "
                       f"slide={src.get('slide')} sec={src.get('section')}")
                print(f"      source: {loc} :: {(src.get('excerpt') or '')[:100]}")
                if src.get("image_path"):
                    print(f"      original image: {src['image_path']}")


if __name__ == "__main__":
    main()
