"""Create the Assignment-2 GitHub issues with completion checks (no assignees).

Reads the GitHub token from ~/.git-credentials. Never prints it.
Usage: python create_issues.py
"""
import json
import os
import re
import urllib.request

TOKEN = ""
with open(os.path.expanduser("~/.git-credentials")) as f:
    m = re.search(r"https://[^:]+:([^@]+)@github\.com", f.read())
    if m:
        TOKEN = m.group(1)
if not TOKEN:
    raise SystemExit("no token found in ~/.git-credentials")

REPO = "krisblair82-pixel/assignment-2"

issues = [
    (
        "Ingestion pipeline: parse course materials, preserve text + page/slide images",
        """**Goal:** Ingest course materials (PDF slides, syllabus, other Canvas files) into a structured index that preserves **both text and original page/slide images**.

**Steps**
- Render each PDF page / PPTX slide to an image (pymupdf locally; LibreOffice for PPTX if available)
- Send each page image to the **document parsing service (9005, dots.mocr)** to extract structured text (tables -> HTML, formulas -> LaTeX)
- Chunk with langchain-text-splitters, keeping source metadata `{doc_id, page/slide, section}`
- Produce a per-file inventory (accepted formats, pages parsed, text + image preserved)

**Completion checks**
- [ ] Every file in `materials/` yields an index entry with both text and a page/slide image
- [ ] Every chunk carries `{doc_id, page/slide, section}` and clean text (no OCR garbage)
- [ ] Inventory report saved under `results/` (per-file page counts)
- [ ] `python ingest.py` runs end-to-end in one command and is idempotent (safe to re-run)

**Evidence:** saved inventory + a sample page render.""",
    ),
    (
        "Hybrid retrieval: keyword + text embeddings + visual embeddings, separate indexes, fusion + multimodal rerank",
        """**Goal:** Retrieve the best evidence (text **and** images) for a query using all three retrievers, combined and reranked.

**Steps**
- bm25s keyword index over text chunks
- Text embeddings via **9002 (Nemotron-3-Embed-1B)** stored in chromadb collection `text_chunks`
- Visual embeddings via **9003 (Qwen3-VL-Embedding-2B)** stored in a **separate** chromadb collection `pages` (one vector per page/slide image)
- Fuse candidate lists (RRF) and rerank with **9004 (Qwen3-VL-Reranker-2B, POST /v1/rerank)**

**Completion checks**
- [ ] Text and visual indexes are separate collections (per assignment spec)
- [ ] A query returns a combined candidate list (text chunks + page images)
- [ ] Reranked order saved under `results/` for every probe query
- [ ] Smoke test: a question about a known chart/diagram retrieves the correct page image

**Evidence:** saved retrieval output; the systematic comparison lives in the eval issue.""",
    ),
    (
        "Grounded answer generation: structured {answer, sources} with validation",
        """**Goal:** Answer questions from the retrieved evidence with the **vision LLM (9001)**, returning structured JSON with separate `answer` and `sources` fields — never inventing answers or citations.

**Steps**
- Prompt supplies evidence text + relevant page images; require JSON output with `answer` and `sources[]`
- Schema validation, then a **grounding check**: every cited source must exist in the index and its excerpt must match the indexed text exactly
- Out-of-materials questions -> explicit "not covered by the materials" response
- Chart/diagram questions answered **from the actual page image** (vision), not just surrounding text

**Completion checks**
- [ ] Response validates against the JSON schema (`answer`: str, `sources`: list of {doc, page, section, excerpt})
- [ ] Grounding check passes 100% on the eval set (no fabricated citations)
- [ ] Missing information is acknowledged, not invented
- [ ] Visual questions use the page image as input to the model
- [ ] No credential appears in any prompt, output, log, or UI

**Evidence:** saved Q&A transcript with validated sources.""",
    ),
    (
        "Quiz generator: material chooser + topic filter, MCQs, fixed hidden answer key, scores, explanations",
        """**Goal:** Generate practice quizzes from a chosen course material (optional topic filter) — multiple choice, with scores and explanations. **Answer key fixed; solutions hidden** until the student answers or requests them.

**Steps**
- Student picks a document (dropdown) + optional topic filter
- Generate MCQs from that document's chunks via **9001**
- Store the answer key separately from the quiz display; never render it by default
- Score answers (per-question + total), show explanations citing sources

**Completion checks**
- [ ] Quiz generated from the selected document only (filter applied when given)
- [ ] Answer key is fixed at generation time and stored; solutions hidden until answer/request
- [ ] Scoring is deterministic and correct (verified against the stored key)
- [ ] Every explanation cites document + page/slide/section (with image when relevant)

**Evidence:** saved quiz JSON + a scored student attempt.""",
    ),
    (
        "Design comparison: hybrid retrieval vs keyword-only baseline",
        """**Goal:** Measure the value of the hybrid design (keyword + text embeddings + visual embeddings + rerank) against a keyword-only baseline on a gold question set; results saved so claims are verified.

**Steps**
- Build a gold set of ~20 questions with known answer sources (mix of text and visual/chart questions)
- Run both variants over the identical gold set with a single command
- Metrics: recall@k of the correct text source, recall@k of the correct page image, and answer groundedness (per the grounding check)

**Completion checks**
- [ ] Gold set saved under `results/` with expected sources labeled
- [ ] Both variants runnable via one command; results timestamped to `results/comparison_*.json`
- [ ] Findings summary: where hybrid wins (e.g. visual questions), where keyword alone is sufficient

**Evidence:** saved results + short findings writeup (feeds the README).""",
    ),
    (
        "Automated checks + repeatable eval harness",
        """**Goal:** Repeatable automated checks so the repo's claims are reproducible: unit tests + a single eval runner.

**Steps**
- pytest suite: chunk metadata integrity; retrieval hits expected source; JSON schema + grounding validation; sanitized error output; secret-scan test (planted credential blocks the commit)
- `run_evals.py`: re-runs retriever + answer evals and writes timestamped results into `results/`

**Completion checks**
- [ ] `pytest` passes from a clean checkout
- [ ] `python run_evals.py` produces timestamped artifacts under `results/`
- [ ] Secret-scan test proves a planted credential is blocked before commit
- [ ] One-command invocation documented in README

**Evidence:** pytest output + `results/` artifacts.""",
    ),
    (
        "Gradio app + security hardening",
        """**Goal:** Student-facing interface: choose a course material, ask questions, generate quizzes — with an evidence panel and sanitized everything.

**Steps**
- Dropdown of indexed materials + optional topic filter
- Chat tab: answer + sources (document, page/slide/section, excerpt) and the **original page image** when relevant
- Quiz tab: generate / answer / score / explanations; key never visible until answered or requested
- UI explains accepted file formats
- Errors: generic user-facing messages; details only in a local scrubbed log; no key in UI, console, or anything sent to the browser

**Completion checks**
- [ ] Material chooser + topic filter work
- [ ] Answer panel shows document, page/slide/section, excerpt, and image evidence
- [ ] Quiz flow works end-to-end; answer key hidden until answered/requested
- [ ] Accepted formats explained in the UI
- [ ] No credential appears in UI, logs, or browser-visible payloads (reviewed in code + screenshot check)
- [ ] `python app.py` starts the app against the class endpoints

**Evidence:** screenshots + a session transcript.""",
    ),
    (
        "README: setup, screenshots, findings, limitations, glossary",
        """**Goal:** Final documentation satisfying the assignment rubric, with honest "tested vs not-yet-checked" statements.

**Steps**
- Setup: copy `config.example` -> `.env` (dummy values only), install deps, run app
- Screenshots: chat with sources, quiz flow
- Findings reference saved results (`results/`) — numbers verified, not eyeballed
- Limitations section: what was not tested (large PDFs, video, non-English, etc.)
- Glossary of unfamiliar terms (RAG, embeddings, bm25, chromadb, rerank, RRF, grounding, plus git workflow terms: issue, branch, PR, review)

**Completion checks**
- [ ] Setup instructions work from a clean clone with only dummy config
- [ ] Screenshots committed and referenced
- [ ] Every number in Findings traces to a saved artifact
- [ ] Tested-vs-unchecked table present and honest
- [ ] Glossary present

**Evidence:** rendered README + screenshots.""",
    ),
]

created = []
for title, body in issues:
    payload = json.dumps({"title": title, "body": body}).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/issues", data=payload, method="POST"
    )
    req.add_header("Authorization", f"token {TOKEN}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.loads(r.read())
            created.append((d["number"], d["html_url"]))
            print(f"created #{d['number']}: {d['title'][:70]}")
    except Exception as e:
        print("FAILED:", title[:60], "->", e)

print(f"\ncreated {len(created)}/{len(issues)} issues")
