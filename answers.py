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
  python answers.py "question" [--doc DOC_ID] [--index PATH] [--save]
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
                        "text": "The following original page/slide images are "
                                "evidence. Cite their doc_id and page/slide "
                                "when you use them."})
        for p in pages[:2]:
            content.append({"type": "text",
                            "text": (f"[IMAGE: doc={p['doc_id']}, page={p.get('page')}, "
                                     f"slide={p.get('slide')}]")})
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
    if not isinstance(doc_id, str) or not doc_id:
        return None
    if src.get("excerpt") is not None and not isinstance(src["excerpt"], str):
        return None
    cands = [c for c in chunks if c.get("doc_id") == doc_id]
    if (src.get("page") is None and src.get("slide") is None
            and not src.get("section")):
        excerpt = (src.get("excerpt") or "").strip()
        if not excerpt:
            return None
        cands = [c for c in cands if excerpt in c["text"]]
    if src.get("page") is not None:
        cands = [c for c in cands if c.get("page") == src["page"]]
    if src.get("slide") is not None:
        cands = [c for c in cands if c.get("slide") == src["slide"]]
    if src.get("section"):
        cands = [c for c in cands if c.get("section") == src["section"]]
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


def ground(data: dict | None, chunks: list[dict],
           images: list[dict] | None = None) -> tuple[dict | None, list[str]]:
    """Schema validation + grounding. Returns (clean_result, issues)."""
    issues = []
    images = images or []
    if not isinstance(data, dict):
        return None, ["model output was not a JSON object"]
    answer = data.get("answer")
    sources = data.get("sources")
    if not isinstance(answer, str) or not answer.strip():
        issues.append("answer missing or not a string")
    if not isinstance(sources, list):
        issues.append("sources missing or not a list")
    if issues:
        return None, issues
    if answer.strip().upper() == "NOT_COVERED":
        return {"answer": "NOT_COVERED", "sources": []}, issues
    kept = []
    seen_sources = set()
    for s in (sources if isinstance(sources, list) else []):
        if not isinstance(s, dict):
            issues.append("source entry is not an object")
            continue
        chunk = _resolve_source(s, chunks)
        if chunk is not None:
            citation = {"doc_id": chunk["doc_id"], "page": chunk.get("page"),
                        "slide": chunk.get("slide"), "section": chunk.get("section"),
                        "excerpt": chunk["text"][:300]}
        else:
            image = next((p for p in images
                          if s.get("doc_id") == p.get("doc_id")
                          and (s.get("page") is not None or s.get("slide") is not None)
                          and s.get("page") == p.get("page")
                          and s.get("slide") == p.get("slide")), None)
            if image is None:
                issues.append(f"source not found in index: {s!r}")
                continue
            citation = {"doc_id": image["doc_id"], "page": image.get("page"),
                        "slide": image.get("slide"), "section": None,
                        "excerpt": "", "image_path": image["image_path"]}
        key = (citation["doc_id"], citation["page"], citation["slide"],
               citation["section"], citation["excerpt"])
        if key not in seen_sources:
            kept.append(citation)
            seen_sources.add(key)
    norm = (answer or "").strip().upper()
    covered = norm != "NOT_COVERED" and "NOT COVERED" not in norm
    return {"answer": answer, "sources": kept}, issues


def _evidence_strongly_matches(question: str, chunks: list[dict]) -> bool:
    """Boundary guard: are the top chunks actually on-topic for the question?

    Uses a simple keyword-overlap heuristic (>= 2 shared tokens of length >= 3)
    so a NOT_COVERED model answer gets ONE retry when the evidence clearly
    matches, while genuinely uncovered questions (no overlap) stay untouched.
    """
    q_tokens = set(re.findall(r"[a-z0-9']{3,}", question.lower()))
    if not q_tokens:
        return False
    for c in chunks[:3]:
        c_tokens = set(re.findall(r"[a-z0-9']{3,}", (c.get("text") or "").lower()))
        if len(q_tokens & c_tokens) >= 2:
            return True
    return False


RETRY_NUDGE = ("The evidence provided above contains relevant material for "
               "this question. Review it again and answer from it if it covers "
               "the question.")


def ask(question: str, doc_filter: str | None = None,
        index_path: str | None = None) -> dict:
    ensure_configured()
    index_path = index_path or os.path.join(INDEX_DIR, "index.json")
    ev = retrieve(question, doc_filter=doc_filter, k=8, index_path=index_path)
    text_chunks, pages = ev["text_chunks"], ev["pages"]

    if not text_chunks and not pages:
        return {"question": question, "covered": False, "answer":
                "NOT_COVERED (no evidence retrieved - is the index built?)",
                "sources": [], "legs": ev["legs"], "pages_used": 0,
                "validation": {
                    "schema_issues": [], "dropped_sources": [],
                    "note": "no evidence to answer from"}}

    index_data = _load_index(index_path)
    indexed_pages = index_data.get("pages", [])

    # Attach the ORIGINAL page/slide images that correspond to the TOP text
    # evidence (requirement 2a + meme test): the model must SEE the slide it
    # is asked about. Visual ranking and text ranking can disagree, so the
    # pages matching the top text chunks come first, then the top visual
    # hits fill the remaining slots (cap 3 images - keeps output stable).
    top_locs = [(c.get("doc_id"), c.get("page"), c.get("slide"))
                for c in text_chunks[:3]]
    matched = []
    # Visual retrieval can rank a different page above the page identified by
    # text retrieval. Pull matching original images from the index as a
    # fallback so the model always sees the slide supporting the top text
    # evidence (especially important for named meme/chart/diagram slides).
    page_candidates = list(pages)
    for indexed in indexed_pages:
        if indexed not in page_candidates:
            page_candidates.append(indexed)
    for loc in top_locs:
        for p in page_candidates:
            if ((p.get("doc_id"), p.get("page"), p.get("slide")) == loc
                    and p not in matched):
                matched.append(p)
                break
    attached_pages = (matched + [p for p in page_candidates if p not in matched])[:3]
    messages = build_messages(text_chunks, attached_pages, question)
    chat = ChatClient()
    raw = chat.complete(messages, max_tokens=MAX_TOKENS)
    data = ({"answer": "NOT_COVERED", "sources": []}
            if raw.strip().upper() == "NOT_COVERED" else _extract_json(raw))
    result, issues = ground(data, index_data.get("chunks", []),
                            images=attached_pages)
    if result is None:
        result = {"answer": "NOT_COVERED (could not parse a structured answer)",
                  "sources": []}
        covered = False
    else:
        covered = result["answer"].strip().upper() != "NOT_COVERED"
        if covered and not result["sources"]:
            issues.append("answer had no verified sources")
            result = {"answer": "NOT_COVERED (answer had no verified sources)",
                      "sources": []}
            covered = False

    # Flaky-boundary guard: the reasoning model occasionally answers
    # NOT_COVERED even when the retrieved evidence clearly matches the
    # question. Retry ONCE (with a neutral nudge) only when the top evidence
    # shares >= 2 keyword tokens with the question - so the meme/meme-adjacent
    # questions are reliable, while truly uncovered questions stay NOT_COVERED.
    if not covered and _evidence_strongly_matches(question, text_chunks):
        retry_messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": [
                {"type": "text",
                 "text": "Your previous answer was NOT_COVERED. " + RETRY_NUDGE},
                *messages[1]["content"],
            ]},
        ]
        raw2 = chat.complete(retry_messages, max_tokens=MAX_TOKENS)
        data2 = ({"answer": "NOT_COVERED", "sources": []}
                 if raw2.strip().upper() == "NOT_COVERED" else _extract_json(raw2))
        result2, issues2 = ground(data2, index_data.get("chunks", []),
                                  images=attached_pages)
        if result2 is not None:
            covered2 = result2["answer"].strip().upper() != "NOT_COVERED"
            if covered2 and result2["sources"]:
                result, issues, covered = result2, issues + issues2, True
                raw = f"{raw}\n--- retry ---\n{raw2}"

    for source in result["sources"]:
        # Gallery matching (requirement 2a): find the ORIGINAL page/slide image
        # for every verified source across ALL retrieved page candidates, not
        # just the pages the model saw - so the answer is shown alongside the
        # actual slide that supports it.
        for page in page_candidates:
            if (source["doc_id"] == page["doc_id"]
                    and source.get("page") == page.get("page")
                    and source.get("slide") == page.get("slide")):
                source["image_path"] = page["image_path"]
                break

    return {"question": question, "doc_filter": doc_filter, "covered": covered,
            "answer": result["answer"], "sources": result["sources"],
            "legs": ev["legs"], "pages_used": len(attached_pages),
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
        if s.get("image_path"):
            print(f"    original slide image: {s['image_path']}")
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
