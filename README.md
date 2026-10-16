# MBAX 6418 — Assignment 2: Course Assistant

A course assistant that answers questions and generates practice quizzes from course materials (slides, syllabus, readings). Built with **hybrid RAG**: keyword search (bm25s) + dense-text retrieval fused with RRF and text-only reranking, alongside separately ranked visual embeddings over page/slide images. Answer generation receives text evidence and original slide images; citation validation checks indexed locations, not semantic correctness.

## What it does

| Feature | How it works |
|---|---|
| **Ask grounded questions** | Separate text/visual indexes → RRF of keyword + dense-text results → text-only reranking; visual results remain separate. A vision LLM receives text and images and returns `{answer, sources[]}`. Schema and indexed source locations are checked; semantic support still needs review. Missing evidence is intended to yield `NOT_COVERED`. |
| **Show slide evidence** | Retrieved page/slide images are displayed in a gallery next to the answer, labeled with document name and page/slide number. The user can also ask the app to describe/explain slide content, including diagrams and charts. |
| **Practice quizzes** | Pick a document (optional topic filter) → an N-question multiple-choice quiz grounded in that material's chunks and images. The answer key stays server-side (`quiz_key_*.json`, gitignored); students see scores immediately, and solutions/explanations with sources only after answering or on explicit request. |
| **Manage materials in-app** | Add/remove documents through the UI (requirement 1a). Uploads are deduplicated by filename and content hash; removing a document also removes its chunks, page images, and index entries, so later answers never rely on removed material. |

## Architecture

![Architecture diagram](assets/architecture.svg)

The pipeline, matching the diagram:

1. **Document preparation** — uploaded files are rendered to a PNG per page/slide (PyMuPDF for PDF; LibreOffice, macOS Keynote/PowerPoint, or Windows PowerPoint COM for PPTX), parsed into structured text by the class document-parsing service (9005), and chunked with `langchain-text-splitters` (800 chars, 100 overlap) while preserving `doc_id` + page/slide/section.
2. **Indexing** — text chunks go into **bm25s** (keyword) and ChromaDB `text_chunks` (9002 text embeddings, dim 2048); page/slide images go into a **separate** ChromaDB `pages` collection (9003 visual embeddings, dim 2048). `index/index.json` is the source of truth and is regenerable.
3. **Query** — `retrieval.py` combines only BM25 and dense-text rankings with RRF (k=60), then sends text strings to the 9004 reranking service. Visual candidates retain their separate ranking; they are neither RRF-fused nor image-content reranked. `answers.py` combines the text and image evidence for the 9001 vision LLM. It prioritizes indexed images matching the top text locations, then fills remaining slots from visual results and other indexed pages, capped at three images. This image attachment path also operates in keyword-only mode when text evidence is retrieved; keyword-only does not mean image-free generation.
4. **Validation** — the model must return `{answer, sources[]}`. `answers.py` checks the schema and resolves citations to indexed text evidence or verifies their document/page/slide against attached source images. Text excerpts come from indexed chunks; image-only citations may have an empty excerpt. These checks verify source identity, not semantic correctness. `NOT_COVERED` handles model refusals and fallback cases such as missing evidence, an unparseable structured answer or an answer without verified sources; an evidence-overlap heuristic may trigger one retry.

## Class services (do NOT use port 9000 — reserved for Hermes)

| Port | Service | Model | Used for |
|---|---|---|---|
| 9001 | Vision LLM (`/v1/chat/completions`) | cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit | answers, quiz generation |
| 9002 | Text embeddings (`/v1/embeddings`, dim 2048) | nvidia/Nemotron-3-Embed-1B-BF16 | text chunks + query vectors |
| 9003 | Visual embeddings (`/embeddings` — no `/v1` prefix, dim 2048) | Qwen/Qwen3-VL-Embedding-2B | slide/page images |
| 9004 | Reranking service (`/v1/rerank`) | Qwen/Qwen3-VL-Reranker-2B | text-only inputs; re-order fused text candidates, not images |
| 9005 | Document parsing (`/chat/completions`, dots.mocr) | dots.mocr | page image → layout JSON |

All calls are server-side. **Port 9000 is reserved for the Hermes agent and must not be used by this app.** Service clients live in `services.py`; they scrub error messages so the API key never appears in logs, the UI, or error output.

## Setup

Requirements: **Python 3.11+** (or later), and — only for direct PowerPoint uploads — **LibreOffice** (recommended) or PowerPoint/Keynote (macOS). See *Supported formats* below.

```bash
# 1. Clone
git clone https://github.com/krisblair82-pixel/assignment-2.git
cd assignment-2

# 2. Virtual environment + dependencies
python -m venv .venv            # or: uv venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

If you use `uv` instead of `pip`, install into the environment with
`UV_LINK_MODE=copy uv pip install --python .venv/Scripts/python.exe -r requirements.txt`
on Windows when the repository is inside OneDrive or another cloud-synced
folder. This avoids a Windows hardlink error; on macOS/Linux use the equivalent
`.venv/bin/python` path.

```bash
# 3. Configure the class API key (NEVER commit this file)
cp config.example .env
#    edit .env and set CLASS_API_KEY=<your real class key>
#    .env is gitignored; config.example holds dummy values only

# 4. Activate the pre-commit secret scanner (blocks any commit containing
#    a value from .env or a known secret pattern)
git config core.hooksPath scripts/hooks

# 5. Verify connectivity, then add materials
#    Create materials/ and drop your course files there (the folder is
#    gitignored — copyrighted material stays out of the repo), or upload
#    them in-app via the Course materials tab.
python probe_services.py        # checks all 5 services (scrubbed output)
python smoke.py                 # live smoke: embed / rerank / chat / parse
python ingest.py                # parse + chunk everything in materials/
python retrieval.py build       # build bm25 + text + visual indexes
python run_evals.py             # 16-question hybrid evaluation
python run_evals.py --compare  # hybrid vs keyword-only; saves comparison_*.json
```

### Endpoint configuration

Copy `config.example` to `.env` and set the shared `CLASS_API_KEY` locally. The
service URLs are configured independently with `LLM_BASE`, `TEXT_EMBED_BASE`,
`VISUAL_EMBED_BASE`, `RERANK_BASE`, and `PARSE_BASE`. The example points to the
class services at `dobolyi.com`; use equivalent private/tunnel URLs only when
your class setup requires them. Do not change the app to use port 9000: that
port is reserved for Hermes. `VISUAL_EMBED_BASE` intentionally includes `/v1`
in the example because the client posts to its `/embeddings` route without a
second `/v1` prefix.

### Supplying API keys without committing them

- All keys live in a local **`.env`** file (gitignored via `.gitignore`, and enforced by the pre-commit scanner in `scripts/hooks`).
- `config.example` contains **dummy values only** — never put real keys there.
- The app reads `.env` through `config.py`; base URLs point at `dobolyi.com` by default (edit to `localhost` only if you tunnel the ports).
- Keys must never appear in code, the UI, logs, errors, screenshots, docs, test results, or GitHub issues/PRs — the secret scanner fails the commit if one does.

## Launching the app

```bash
python app.py          # opens http://127.0.0.1:7860
```

Three tabs:

1. **Ask a question** — optional document filter; the answer panel shows verified sources with real excerpts, and a gallery shows the original page/slide images that support the answer.
2. **Practice quiz** — pick a document (+ optional topic phrase), choose 1–10 questions, click one answer choice per question, get scored, then reveal solutions/explanations with sources when ready.
3. **Course materials** — add files (multiple at once) or remove documents. Adding runs parsing + indexing for that file; removing deletes the file, its chunks, page images, and index entries, then rebuilds search indexes.

To add documents, open **Course materials**, choose one or more supported files,
and click **Add files**. Uploads are deduplicated; a repeated upload is reported
without creating duplicate chunks. To remove a document, select its `doc_id`
and click **Remove selected document**. The app deletes the source file, rendered
images, chunks, and index entries, then rebuilds search indexes. New uploads
require the parsing and embedding services to be available.

### Supported formats and PowerPoint conversion

| Format | Notes |
|---|---|
| `.pdf` | text + page images (best supported) |
| `.pptx` | text via python-pptx; slide images via **LibreOffice** (recommended, headless) — or on macOS via **Keynote**/**PowerPoint** (opens briefly), or Windows PowerPoint COM |
| `.docx` | text with heading sections |
| `.txt` / `.md` | plain text |
| `.png` / `.jpg` / `.jpeg` | standalone image (queried visually) |

If no converter is available, ingestion warns and indexes the deck **text-only**; the manual workaround is exporting the deck to PDF (acceptable per the assignment) and uploading the PDF instead.

## Testing

```bash
python -m pytest -q        # test suite; 64 test functions found by static inspection (see tests/)
python run_evals.py        # hybrid: full retrieval + grounded answers over the 16-question set
python run_evals.py --mode keyword   # issue #5 baseline: bm25 keyword search only
```

Existing automated checks cover adding/removing files (dedupe, index cleanup, batch uploads), answering text and image questions, quiz generation/scoring, missing-information handling, repeated uploads, unavailable services and secret scanning. Many workflow checks use mocks; their presence is not proof of browser/live end-to-end behavior or a passing run at the reviewed revision. Saved evaluations and light/dark screenshots are team evidence, not new independent tests. Fresh-copy deployment, conversion fidelity (including Windows COM and macOS Keynote), browser behavior and readability remain unverified by the A09 documentation audit — see *Limitations*.

Screenshots are reproducible: `python -m playwright install chromium && python scripts/capture_screenshots.py` (requires the app running; re-generates `assets/screenshots/*.png`).

## Evaluation results and design comparison (issue #5)

Historical question set: 16 questions in `results/eval_questions.json`, covering Week 2 text/visuals (including the **Vibe Coding on "Prod"** meme), Week 3, the syllabus and an unanswerable question. The table below traces to `results/eval_20261014_142255.json` and `results/eval_20261014_142424.json`, referenced by `results/comparison_20261015_verified.json`. These are historical reports, not the latest focused runs or proof of a controlled comparison. The older runner did not preserve keyword mode through answer generation; the exact execution revision and index contents were not recorded. Earlier reports also document page/slide expectation changes as the materials switched formats.

**Historical reports labeled hybrid and keyword, 16 questions (baseline validity unverified):**

| Metric | Hybrid | Keyword-only baseline |
|---|---|---|
| Retrieval source-hit | 15/16 | 15/16 |
| Grounded answers | 16/16 | 15/16 |
| NOT_COVERED handled correctly | 1/1 | 1/1 |
| Total time | 136.5s | 88.8s |
| Avg time per question | 8530 ms | 5547 ms |

Per-question retrieval source hits (hybrid then keyword):

| Question | Hybrid hit | Hybrid time | Keyword hit | Keyword time |
|---|---|---|---|---|
| q01_open_weights | ✅ | 8.5s | ✅ | 9.4s |
| q02_training_data | ✅ | 5.6s | ✅ | 4.5s |
| q03_model_size | ✅ | 10.7s | ✅ | 9.1s |
| q04_context_window | ✅ | 6.4s | ✅ | 4.7s |
| q05_prompt_caching | ✅ | 9.2s | ✅ | 4.8s |
| q06_quantization | ✅ | 6.8s | ✅ | 4.1s |
| q07_moe | ✅ | 5.4s | ✅ | 4.5s |
| q08_vibe_vs_agentic | ✅ | 8.4s | ✅ | 5.6s |
| q09_interface_choice | ✅ | 5.3s | ✅ | 3.5s |
| q10_mcp_visual | ✅ | 8.9s | ✅ | 5.0s |
| q11_open_closed_visual | ✅ | 6.5s | ✅ | 4.9s |
| q12_not_covered | n/a | 5.5s | n/a | 4.1s |
| q13_meme_prod | ✅ | 27.8s | ✅ | 10.3s |
| q14_syllabus_grading | ✅ | 9.9s | ✅ | 4.9s |
| q15_syllabus_office_hours | ✅ | 6.4s | ✅ | 4.7s |
| q16_week3_prompts | ✅ | 5.2s | ✅ | 4.4s |

**Interpretation limits:** the saved reports record equal retrieval-location hits (15/16), grounded flags of 16/16 versus 15/16 and lower elapsed time in the run labeled keyword. They do not establish that keyword-only answer retrieval caused the q14 difference or that hybrid uniquely supplied images. The historical mode-propagation defect and missing execution provenance prevent those causal conclusions. Even with corrected mode propagation, `answers.py` can attach indexed slide images in keyword-only mode. These historical figures are retained as evidence of earlier runs, not as a validated basis for selecting the design.

Regression: `scripts/make_comparison_table.py` regenerates these tables from the latest transcripts (`python scripts/make_comparison_table.py`).

## Focused QA evaluation and design comparison

The original 16-question regression evaluation remains in `results/eval_questions.json`. The focused QA/comparison set requested for this assignment is `results/eval_questions_qa.json`; its two raw run reports and comparison summary are committed under `results/`.

### Focused 8-question set

The focused question-set metadata declares these two course files, and both run reports name `index.json`. This is the recorded corpus claim, not independent verification of identical index contents:

- `MBAX_6418_-_Week_2_-_LLM_Fundamentals_v2.pptx`
- `MBAX_6418_-_Week_3_-_Prompt_Engineering_v1.pptx`

The syllabus question is intentionally included, but `MBAX_6418_Syllabus_Fall_2026.pdf` was not present in the local index. It therefore tests **missing-file refusal, not syllabus answer quality**. Answering a question from an available syllabus still requires separate evaluation; this focused set does not establish that part of the rubric.

| ID | Question | Expected evidence |
|---|---|---|
| qa01 | What are two characteristics of open-weight LLMs? | Week 2 slide 4 text |
| qa02 | What tradeoffs should be considered when choosing model size? | Week 2 slide 6 text |
| qa03 | How does prompt caching improve performance across requests? | Week 2 slide 12 text |
| qa04 | What add-ons can MCP interfaces access? | Week 2 slide 42 visual/text slide |
| qa05 | Find the Vibe Coding on “Prod” meme: slide, format, and wording. | Week 2 slide 33 visual meme |
| qa06 | What non-text content can prompts contain? | Week 3 slide 4 text |
| qa07 | According to the syllabus, what percentage of the final grade comes from quizzes? | Expected `NOT_COVERED`; syllabus missing locally |
| qa08 | What was the instructor’s favorite programming language in high school? | Expected `NOT_COVERED`; not in the materials |

“Correct” is an automated required-term check (or a `NOT_COVERED` response, including the accepted explanatory suffix). “Sources supported” means at least one returned source matches an expected location; for uncovered questions it means no source was returned. Neither metric independently verifies semantic support or actual image use. “Correct missing-information refusals” additionally requires the grounded/schema-valid flag. Latency includes the initial retrieval check and answer generation, which performs another retrieval; it is not UI-only response time.

### Hybrid versus keyword-only on the same set

The current hybrid configuration uses BM25 + dense-text retrieval with text-only reranking and a separate visual retrieval leg. Keyword mode selects BM25 only for retrieval, but answer generation can still attach indexed images. In the reviewed code, `run_evals.py` forwards the selected mode to `answers.py`, which forwards it to retrieval. That code inspection does not establish the exact executable revision used for the saved runs; see provenance below.

| Metric | Hybrid | Keyword-only |
|---|---:|---:|
| Correct answers | 8/8 | 7/8 |
| Sources supported | 8/8 | 8/8 |
| Grounded/schema-valid answers | 7/8 | 8/8 |
| Expected missing-information cases | 2 | 2 |
| Correct missing-information refusals | 1/2 | 2/2 |
| Total time | 46.51s | 33.10s |
| Average time/question | 5.81s | 4.14s |

| ID | Hybrid correctness / source / time | Keyword correctness / source / time |
|---|---|---|
| qa01 open weights | ✅ / ✅ / 8.41s | ✅ / ✅ / 3.47s |
| qa02 model size | ✅ / ✅ / 7.74s | ✅ / ✅ / 3.91s |
| qa03 prompt caching | ✅ / ✅ / 6.91s | ❌ / ✅ / 3.45s |
| qa04 MCP visual | ✅ / ✅ / 4.74s | ✅ / ✅ / 2.42s |
| qa05 Vibe Coding meme | ✅ / ✅ / 5.76s | ✅ / ✅ / 4.00s |
| qa06 Week 3 prompts | ✅ / ✅ / 5.17s | ✅ / ✅ / 2.97s |
| qa07 missing syllabus | ✅ / ✅ / 1.55s | ✅ / ✅ / 0.01s |
| qa08 unknown fact | ✅ / ✅ / 6.23s | ✅ / ✅ / 12.86s |

### Interpretation and decision

The provisional choice is to keep the **hybrid pipeline** for its additional dense-text and visual retrieval paths. In the saved focused reports, hybrid passes the required-term checks on all six answerable questions, including both labeled visual, while keyword misses the prompt-caching detail and records lower total latency. This supports further investigation, not a causal quality claim: location matches and term checks do not prove image use or semantic correctness. Keyword mode skips visual embedding retrieval and reranking, but can still receive original slide images through the shared answer-generation path. Team review of source fidelity and a provenance-complete comparison remain necessary.

The hybrid run had one schema-validation failure on the deliberately uncovered high-school-programming-language question even though the answer content correctly refused to answer. This is recorded as a limitation rather than counted as a successful grounded answer. The app still failed closed and did not invent a fact. The missing syllabus question was correctly refused by both approaches because the syllabus file is absent from the local index; the percentage cannot be reported until that course file is added and indexed.

The raw, scrubbed evidence is `results/comparison_20261015_104050.json`, with per-mode reports `results/eval_20261015_104017.json` and `results/eval_20261015_104050.json`. Re-run with:

```bash
python run_evals.py --compare --eval-set results/eval_questions_qa.json
```


### Evaluation provenance and limits

All paths below are relative to `results/`; timestamps are the saved `generated_at` values, with no timezone recorded.

| Evidence | Saved timestamp | Evaluation set / index label |
|---|---|---|
| `eval_20261014_142255.json` (hybrid) | 2026-10-14 14:22:55 | `eval_questions.json` / `index.json` |
| `eval_20261014_142424.json` (keyword) | 2026-10-14 14:24:24 | `eval_questions.json` / `index.json` |
| `comparison_20261015_verified.json` | 2026-10-14 14:24:24 | References the two historical reports above; filename date is not the run date |
| `eval_20261015_104017.json` (hybrid) | 2026-10-15 10:40:17 | `eval_questions_qa.json` / `index.json` |
| `eval_20261015_104050.json` (keyword) | 2026-10-15 10:40:50 | `eval_questions_qa.json` / `index.json` |
| `comparison_20261015_104050.json` | 2026-10-15 10:40:50 | References the two focused reports above |

The documentation audit inspected repository revision `86914dedf9b64c47318f5a767ef5a246aa150af4`; **this is not a recorded evaluation execution SHA**. The reports do not record code revision, corpus/index hashes, dependency versions, hardware or service configuration. Matching index filenames do not prove identical contents. The focused question set names the Week 2/Week 3 PPTX files and explicitly marks the syllabus absent; the saved reports do not independently establish the complete corpus. They store flags, locations and timings, not full answer text or attached-image traces, so independent semantic regrading and image-use verification remain outstanding. No evaluations were rerun for these documentation corrections.


## Known limitations and failures investigated

(Written up from the actual runs — see commit history and `results/`.)

- **Slide rendering needs a local office suite.** LibreOffice is the robust headless path; macOS falls back to Keynote/PowerPoint which briefly open a GUI window, and decks upload text-only if neither is present. Manual PDF export is the documented workaround.
- **Visual retrieval quality depends on the 9003 service.** Image-carrying candidates are kept separate from the reranked text list; the reranker currently scores text-only document strings (the service's verified input shape).
- **Large decks are slow in the UI.** Parsing a 40+ slide deck through 9005 takes minutes (one call per page); uploads show a status message rather than a progress bar.
- **`index/` is regenerable, not authoritative.** Removing a document rebuilds bm25 + chroma from `index/index.json`; a corrupted index dir is fixed by re-running `ingest.py` + `retrieval.py build`.
- **Reasoning-model quirk (9001).** The chat model emits a `reasoning` field that can consume the token budget; clients double the budget and retry once when `content` comes back empty.
- **Boundary questions were occasionally flaky (fixed).** The meme question (q13) previously sometimes returned `NOT_COVERED` because the model never received the slide it was asked about (image attachments followed visual rankings, which disagreed with the text evidence). The answer pipeline now attaches the original page images matching the top text evidence first (cap 3), and adds a one-shot retry guard when the model says `NOT_COVERED` while the top evidence clearly matches the question. Verified: the meme question was covered on 4/4 fresh runs and quotes the meme text; genuinely uncovered questions still return a clean `NOT_COVERED` with a single model call. Single-call variance may still occasionally surface with unusual phrasing; the app always fails closed rather than inventing.
- **Port 9000 is off-limits.** Reserved for Hermes; this app only uses 9001–9005 (per the connectivity report `connectivity_report.md`).

## Security notes

- API key lives in gitignored `.env`; examples use dummy values.
- Pre-commit hook `scripts/hooks/pre-commit` runs `scripts/scan_secrets.sh`, which scans staged content for `.env` values and secret patterns.
- Browser UI shows scrubbed error messages only; CLI scripts print scrubbed diagnostics.
- Quiz answer keys (`results/quiz_key_*.json`) are gitignored and never rendered by the UI.
- Course materials (`materials/`) are gitignored — they are copyrighted and stay out of the repository.

## Repository map

| File | Purpose |
|---|---|
| `app.py` | Gradio interface (Ask / Practice quiz / Course materials) |
| `services.py` | Class API clients (9001–9005), scrubbed errors |
| `ingest.py` | Render → parse → chunk pipeline; per-file `process_file()` |
| `retrieval.py` | bm25 + dense text + visual retrieval; RRF fusion; rerank; selectable legs |
| `answers.py` | Grounded answer generation + source/grounding validation |
| `quiz.py` | Quiz generation (public quiz + hidden key) and scoring |
| `documents.py` | In-app add/remove of materials (dedupe, index cleanup) |
| `run_evals.py` | 16-question eval suite, hybrid vs keyword baseline, timings |
| `probe_services.py` / `smoke.py` | Connectivity and live-service smoke checks |
| `config.py` / `config.example` | `.env` loading (dummy values in example) |
| `scripts/scan_secrets.sh` | Pre-commit secret scanner |
| `tests/` | Unit + end-to-end tests |
| `results/` | Committed evidence: eval transcripts, smoke reports, inventories |
| `assets/architecture.svg` | Architecture diagram (embedded above) |

## Glossary

- **RAG (Retrieval-Augmented Generation)** — fetching relevant source text/images first, then asking the model to answer using only that evidence.
- **Hybrid retrieval** — combining multiple search methods (here: keyword + text embeddings + visual embeddings) instead of relying on one.
- **Embedding** — a dense numeric vector that captures meaning; similar texts/images get similar vectors.
- **Visual embedding** — an embedding computed from an image (here, a page/slide render) so images can be searched by meaning.
- **BM25 / bm25s** — classic keyword ranking (term-frequency statistics); `bm25s` is a fast Python implementation.
- **ChromaDB** — the vector database used here to store and search embeddings (text chunks and page images live in separate collections).
- **RRF (Reciprocal Rank Fusion)** — merging ranked lists from different search methods by their ranks.
- **Reranker** — a model that re-scores candidate passages against the query for a more accurate final ordering.
- **Chunk** — a slice of a document's text (~800 chars here) that is embedded and searched independently.
- **Grounding** — ensuring the answer's claims and citations trace back to the actual source material.
- **NOT_COVERED** — the app's structured way of saying the materials cannot answer the question.
- **doc_id** — a document's stable identifier in the index (slugified relative path, e.g. `MBAX_6418_Syllabus_Fall_2026.pdf`).
- **Answer key** — the correct-answer map for a quiz; kept out of the app UI and out of git.
- **Issue** — a tracked task or bug report on GitHub with its own discussion thread, assignees, and checklists (this project's tasks are tracked as issues, e.g. this README).
- **Branch** — a separate line of commits that lets you change code without touching `main`.
- **Pull request (PR)** — a proposed change delivered on a branch, discussed and reviewed by teammates, then merged.
- **Review** — reading a teammate's issue/PR carefully to catch problems before the change lands.

## Team workflow

Substantial tasks are tracked as GitHub issues with completion checklists; work lands via branches and pull requests (see the issues and PR history). Everyone on the team reviews a teammate's work before merging. Screenshots: an answer with a supporting slide image and quiz feedback with sources are included in this README (see below).

## Screenshots

**Grounded answer with the original supporting slide image** — the required Week 2 "Vibe Coding on Prod" meme test: the app identifies slide 33, verifies the source, and shows the actual slide (with the Boromir "One does not simply…" meme) in the evidence gallery.

![Answer with original slide image](assets/screenshots/answer_meme_slide.png)

**Quiz feedback with sources** — after submitting answers, scores match the fixed answer key; solutions stay hidden until the student requests them, then explanations appear with verified source references (document + page/slide).

![Quiz feedback with sources](assets/screenshots/quiz_feedback_sources.png)

**Course materials tab** — in-app document management (add/remove, dedupe, index cleanup).

![Course materials tab](assets/screenshots/materials_tab.png)

**Light and dark modes** — the Gradio default theme follows the system color scheme; both were checked for readability of text, controls, and source images (`assets/screenshots/ask_tab_light.png` and `ask_tab_dark.png`). No readability issues found; the slide images render identically in both themes.

Light|Dark
---|---
![Light](assets/screenshots/ask_tab_light.png)|![Dark](assets/screenshots/ask_tab_dark.png)
