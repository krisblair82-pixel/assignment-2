"""Grounded answer generation (issue #3).

Pipeline:
  retrieve evidence (text chunks + page images via retrieval.retrieve)
  -> prompt the vision LLM (9001) with that evidence (page images attached
     when the visual leg produced any)
  -> parse structured JSON {answer, sources[]}
  -> schema validation + GROUNDING CHECK: every cited source must resolve to a
     real indexed chunk; the reported excerpt is copied from the index, never
     from the model (fabricated citations cannot pass).

CLI:
  python answers.py ask "question" [--doc DOC_ID] [--index PATH] [--save]
"""
import argparse
import base64
import json
import os
import re
import time

from config import INDEX_DIR, RESULTS_DIR, ensure_configured
from retrieval import retrieve, _load_index
from services import ChatClient

SYSTEM_PROMPT = (
    "You are a course assistant that answers questions using ONLY the provided "
    "course material excerpts and images.\n"
    "Rules:\n"
    "1. Base every claim on the provided evidence. Excerpts are labeled "
    "[SRC n: doc=..., page=..., slide=..., section=...].\n"
    "2. If the materials do not cover the question, set the answer field to "
    "exactly \"NOT_COVERED\" and return an empty sources list.\n"
    "3. Return ONE JSON object with exactly two fields:\n"
    '{"answer": "<your answer>", "sources": [{"doc_id": "...", "page": <int or null>, '
    '"slide": <int or null>, "section": "...", "excerpt": "<short verbatim quote>"}]}\n'
    "4. The excerpt must be a short, verbatim quote from the cited source.\n"
    "5. Never invent facts, numbers, or sources."
)

MAX_TOKENS = 2400  # reasoning field + JSON answer need room; content can be null on tiny budgets


def _data_uri(path: str) -> str:
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode("ascii")
    ext = os.path.splitext(path)[1].lstrip(".").lower() or "png"
    return f"data:image/{ext};base64,{b64}"


def build_messages(text_chunks: list[dict], pages: list[dict], question: str) -> list[dict]:
    """System prompt + user content with labeled excerpts and page images."""
    content = []
    for i, c in enumerate(text_chunks[:6], 1):
        label = (f"[SRC {i}: doc={c['doc_id']}, page={c['page']}, "
                 f"slide={c['slide']}, section={c['section']}]")
        content.append({"type": "text", "text": f"{label}\n{c['text']}"})
    if pages:
        content.append({"type": "text",
                        "text": "The following original page/slide image(s) are "
                                "also evidence; cite them in sources with their "
                                "doc_id/page when you use them."})
        for p in pages[:2]:
            content.append({"type": "image_url",
                            "image_url": {"url": _data_uri(p["image_path"])}})
    content.append({"type": "text", "text": f"Question: {question}"})
    return [{"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content}]


def _extract_json(text: str) -> dict | None:
    """Pull the first balanced {...} JSON object out of the model's reply
    (tolerates markdown fences, prose, trailing text)."""
    t = re.sub(r"```(?:json)?", "", text).strip()
    start = t.find("{")
    if start == -1:
        return None
    depth, in_str, esc = 0, False, False
    for i in range(start, len(t)):
        ch = t[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(t[start:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _resolve_source(src: dict, chunks: list[dict]) -> dict | None:
    """Resolve a model-cited source to a real indexed chunk; returns the chunk
    or None. The excerpt is taken from the index so it cannot be fabricated."""
    doc_id = src.get("doc_id")
    if not doc_id:
        return None
    cands = [c for c in chunks if c.get("doc_id") == doc_id]
    if src.get("page") is not None:
        exact = [c for c in cands if c.get("page") == src.get("page")]
        if exact:
            cands = exact
    if src.get("slide") is not None:
        exact = [c for c in cands if c.get("slide") == src.get("slide")]
        if exact:
            cands = exact
    if src.get("section"):
        exact = [c for c in cands if c.get("section") == src.get("section")]
        if exact:
            cands = exact
    if len(cands) > 1:
        # several chunks share the location: use the model's excerpt (tokens)
        # to pick the most-likely one - disambiguation only, never content trust
        ex_tokens = set(re.findall(r"[A-Za-z0-9'%]+", (src.get("excerpt") or "").lower()))
        if ex_tokens:
            def _overlap(c):
                ct = set(re.findall(r"[A-Za-z0-9'%]+", c["text"].lower()))
                return len(ex_tokens & ct)
            best = max(cands, key=_overlap)
            if _overlap(best) > 0:
                cands = [best]
    return cands[0] if cands else None


def ground(data: dict | None, chunks: list[dict]) -> tuple[dict | None, list[str]]:
    """Schema validation + grounding. Returns (clean_result, issues)."""
    issues = []
    if not isinstance(data, dict):
        return None, ["model output was not a JSON object"]
    answer = data.get("answer")
    sources = data.get("sources")
    if not isinstance(answer, str) or not answer.strip():
        issues.append("answer missing or not a string")
    if not isinstance(sources, list):
        issues.append("sources missing or not a list")
    kept = []
    for s in (sources if isinstance(sources, list) else []):
        if not isinstance(s, dict):
            issues.append("source entry is not an object")
            continue
        chunk = _resolve_source(s, chunks)
        if chunk is None:
            issues.append(f"source not found in index: {s!r}")
            continue
        kept.append({"doc_id": chunk["doc_id"], "page": chunk.get("page"),
                     "slide": chunk.get("slide"), "section": chunk.get("section"),
                     "excerpt": chunk["text"][:300]})
    norm = (answer or "").strip().upper()
    covered = norm != "NOT_COVERED" and "NOT COVERED" not in norm
    return {"answer": answer, "sources": kept}, issues


def ask(question: str, doc_filter: str | None = None,
        index_path: str | None = None) -> dict:
    ensure_configured()
    index_path = index_path or os.path.join(INDEX_DIR, "index.json")
    ev = retrieve(question, doc_filter=doc_filter, k=8, index_path=index_path)
    text_chunks, pages = ev["text_chunks"], ev["pages"]

    if not text_chunks and not pages:
        return {"question": question, "covered": False, "answer":
                "NOT_COVERED (no evidence retrieved - is the index built?)",
                "sources": [], "legs": ev["legs"], "validation": {
                    "schema_issues": [], "dropped_sources": [],
                    "note": "no evidence to answer from"}}

    messages = build_messages(text_chunks, pages, question)
    chat = ChatClient()
    raw = chat.complete(messages, max_tokens=MAX_TOKENS)
    data = _extract_json(raw)
    result, issues = ground(data, _load_index(index_path).get("chunks", []))
    if result is None:
        result = {"answer": "NOT_COVERED (could not parse a structured answer)",
                  "sources": []}
        covered = False
    else:
        covered = result["answer"].strip().upper() != "NOT_COVERED"

    return {"question": question, "doc_filter": doc_filter, "covered": covered,
            "answer": result["answer"], "sources": result["sources"],
            "legs": ev["legs"], "pages_used": len(pages),
            "validation": {"schema_issues": issues, "dropped_sources":
                           [i for i in issues if "not found in index" in i]},
            "raw_model_output": raw[:400]}


def main():
    ap = argparse.ArgumentParser(description="Grounded Q&A from course materials "
                                             "(python answers.py 'your question' --save)")
    ap.add_argument("question", help="the question to answer from the materials")
    ap.add_argument("--doc", default=None, help="restrict evidence to one doc_id")
    ap.add_argument("--index", default=os.path.join(INDEX_DIR, "index.json"))
    ap.add_argument("--save", action="store_true", help="save results under results/")
    args = ap.parse_args()

    out = ask(args.question, doc_filter=args.doc, index_path=args.index)
    print(f"covered: {out['covered']}   legs: {out['legs']}   pages_used: {out['pages_used']}")
    print(f"\nANSWER: {out['answer']}\n")
    for s in out["sources"]:
        loc = f"doc={s['doc_id']} page={s['page']} slide={s['slide']} sec={s['section']}"
        print(f"  source [{loc}] :: {s['excerpt'][:110]}")
    if out["validation"]["schema_issues"]:
        print(f"\nvalidation notes: {out['validation']['schema_issues'][:5]}")
    if args.save:
        os.makedirs(RESULTS_DIR, exist_ok=True)
        path = os.path.join(RESULTS_DIR, f"answer_{time.strftime('%Y%m%d_%H%M%S')}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1)
        print(f"\nsaved -> {path}")


if __name__ == "__main__":
    main()
