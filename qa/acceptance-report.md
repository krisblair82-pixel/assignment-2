# Independent student acceptance report

## Current disposition

**NOT TESTED — preparation only. No independent acceptance results exist yet.**

The application has not been launched for this review. No services have been contacted, materials uploaded, indexes built, or evaluations executed. No teammate result is adopted as an independent observation.

## Revision and environment record

| Field | Recorded value |
|---|---|
| Repository | Shared Assignment 2 repository, `krisblair82-pixel/assignment-2` |
| Review branch | `qa/final-acceptance-review` |
| Review worktree | `C:\Users\combs\assignment-2-qa` |
| Preparation baseline | `86914dedf9b64c47318f5a767ef5a246aa150af4` — fetched `origin/main` when this worktree was created |
| Git commit actually tested | **None — NOT TESTED**. Record the exact execution revision before testing. |
| Preparation host | Windows 11; manual browser environment not yet verified |
| Application Python / dependency versions | NOT RECORDED for this worktree; no environment installed or application execution performed |
| Browser / version / viewport | NOT RECORDED |
| Test operator / execution time / timezone | NOT RECORDED — no execution |
| Corpus identity / permitted source files / hashes | NOT VERIFIED; never include full copyrighted source files |
| Index provenance / image availability | NOT VERIFIED |
| Office converter, if needed | NOT VERIFIED |
| Local configuration / service availability | NOT VERIFIED; record presence/validation only, never credentials or sensitive URLs |
| Isolation and approved fault-injection method | NOT ESTABLISHED |
| Evidence storage | Not created. Record sanitized relative references when evidence is collected. |

The existing `fix/offline-eval-tests` worktree is separate. Its earlier test results and uncommitted corrections are not a verification of this baseline. Do not import or overwrite those changes as part of acceptance reporting.

## Requirement-mapped results

Steps and expected outcomes are defined in [acceptance-checklist.md](acceptance-checklist.md).

| Case | Requirement mapping | Status | Actual independent observations | Evidence | Findings / blocker |
|---|---|---|---|---|---|
| A01 Upload and selection | #1, #7; requirement 1a | NOT TESTED | None; not executed | None collected | Prerequisites not yet assessed |
| A02 Repeated uploads and removal | #1, #7; requirement 1a | NOT TESTED | None; not executed | None collected | Prerequisites not yet assessed |
| A03 Visual fidelity and document isolation | #2, #3, #7; requirement 2a | NOT TESTED | None; not executed | None collected | Prerequisites not yet assessed |
| A04 Quiz solutions and scoring | #4, #7 | NOT TESTED | None; not executed | None collected | Prerequisites not yet assessed |
| A05 Quiz reset and independent sessions | #4, #7 | NOT TESTED | None; not executed | None collected | Prerequisites not yet assessed |
| A06 Missing information and topics | #3, #4, #7 | NOT TESTED | None; not executed | None collected | Prerequisites not yet assessed |
| A07 Failure and recovery | #3, #7 | NOT TESTED | None; not executed | None collected | Safe fault-injection method not established |
| A08 Student usability and setup clarity | #7, #8 | NOT TESTED | None; not executed | None collected | Browser/environment not yet recorded |
| A09 Retrieval and submission traceability audit | Instructor PDF: Build; 4a; Evaluate, Document, and Submit | BLOCKED | Confirmed documentation contradictions corrected locally; original audit FAIL retained below as history | Evidence and correction follow-up below | Execution provenance, semantic/image evidence and team confirmation remain unverified |

### A09 — Submission Evidence Audit

- **Reviewer / time / revision:** Hermes, 2026-10-15 23:29 MDT; committed `HEAD` = local `origin/main` = `86914dedf9b64c47318f5a767ef5a246aa150af4`, branch `qa/final-acceptance-review`. Inspected committed blobs, not original-worktree changes. No remote freshness check or fetch; this is the latest locally available committed revision.
- **Authoritative rubric:** `C:\Users\combs\Downloads\MBAX 6418 Assignment 2.pdf`, read directly. Applied “Build,” “Test the app thoroughly,” and “Evaluate, Document, and Submit.” The preparation-only statements elsewhere in this report remain unchanged by scope; this section supersedes them for A09 only. A01–A08 remain NOT TESTED.
- **Present:** Python application modules; `requirements.txt`; dummy configuration instructions and `config.example`; README installation/configuration/launch, supported formats/conversion, material management, question/quiz and test instructions; embedded `assets/architecture.svg`; `assets/screenshots/answer_meme_slide.png` and `quiz_feedback_sources.png` (committed PNGs, both 1280×1000); additional light/dark screenshots; `results/eval_questions_qa.json`, evaluation/comparison reports, inventories and documented failures/limitations. SVG XML parses. Screenshot existence/format is verified, not visible content or source fidelity.
- **Numbers traced:** README's focused comparison matches `results/comparison_20261015_104050.json` and its raw reports `eval_20261015_104017.json` / `eval_20261015_104050.json`: hybrid/keyword correctness **8/8 vs 7/8**, source-location support **8/8 vs 8/8**, grounded/schema-valid **7/8 vs 8/8**, valid missing-information outcomes **1/2 vs 2/2**, total **46.51s vs 33.10s**. Recounted per-case flags and inspected per-case timing. Hybrid qa08 correctly refuses but has one schema issue; this explains the differing correctness/grounding totals. The historical 16-case table and per-question times also trace to `eval_20261014_142255.json` / `eval_20261014_142424.json` via `comparison_20261015_verified.json`; matching arithmetic does not establish experimental validity.
- **FAIL — pipeline/interpretation contradictions:** `retrieval.py:retrieve` fuses only BM25 and dense-text rankings; visual candidates remain separate. `services.py:Reranker.rerank` sends text strings, not images. README/diagram wording implies all three are RRF-fused. `answers.py:ask` also attaches indexed images matching text evidence (and fills remaining image slots from indexed pages), even in keyword mode. Therefore README claims that the baseline cannot supply original image evidence are unsupported. Current `run_evals.py:evaluate_case` forwards mode to `ask`, but the older PR #16 merge revision did not; historical baseline conclusions need qualification rather than being treated as corrected evidence.
- **Evaluation/provenance gaps:** The focused set has eight questions, two labeled visual including the meme, and missing-information cases. Its syllabus question is a missing-file refusal, not verification of syllabus answer quality; the older 16-case set includes syllabus questions but is not the required 5–10-question focused set. Reports identify only `index.json`/evaluation filenames and timestamps, without code SHA, corpus/index hashes or run environment. Same-corpus identity and exact execution revision cannot be independently established. “Correct” is term matching; “sources supported” checks expected locations, not semantic support or image use. Saved evaluation reports omit full answers, preventing an independent semantic regrade from these reports alone.
- **Testing/setup concerns:** Static parsing finds 64 test functions, consistent with README's count, but this is not evidence of 64 passing tests at this revision. Mocked workflow checks do not prove browser/live end-to-end behavior. README's setup shell block contains un-commented explanatory prose beginning “If you use `uv`,” so copying the block verbatim is unsafe. Fresh-copy deployment, conversion fidelity, manual workflows/light-dark readability and source correctness require separate verification.
- **Team/submission confirmation:** Meaningful individual contributions and peer reviews, team-written interpretation, fresh-copy teammate check, instructor repository access and the final Canvas link remain unverified. No comprehensive secret/history audit was performed; configuration examples and scanner presence do not prove absence of leaked keys.
- **Execution limitation:** No app, tests, ingestion or evaluation was run. Two screenshot-inspection tool requests attempted an image-analysis service and failed with HTTP 401; no visual result was obtained. This was outside the no-endpoint restriction; no retry was made. No class service was invoked. Only this A09 record was edited; no unrelated gap was fixed.
- **Original audit outcome: FAIL (before documentation corrections).** Required artifact categories were present and reported arithmetic was traceable, but documentation contradictions prevented passing A09. See the follow-up below for current status.

#### A09 documentation correction follow-up

- **Scope / revision:** Local text inspection and corrections against `86914dedf9b64c47318f5a767ef5a246aa150af4` plus the uncommitted documentation edits. This is an inspection baseline, not an evaluation execution SHA. Earlier A09 observations above are retained as history; this follow-up supersedes their documentation-defect status only.
- **Reconfirmed from code:** `retrieval.py:224–239` fuses BM25/dense-text only and reranks text strings; `services.py:204–211` sends no image inputs to the reranker. `answers.py:213–256` preserves retrieval mode but independently attaches indexed images, including in keyword mode. `run_evals.py:70–118` uses term/location/schema checks and saves no complete answers or image-attachment trace. The historical runner at `883c20a2d4da4fea02fb2f353b68897bf55c367d` omitted mode when calling `ask`; this establishes the old code defect, not the execution SHA of any saved run.
- **Corrected:** README overview, architecture, comparison descriptions and interpretation now distinguish text fusion/reranking from separate visual ranking and shared image attachment. Existing SVG labels were edited in place, without regeneration or layout changes. Historical baseline causal claims were withdrawn. The focused syllabus case explicitly tests missing-file refusal, leaving syllabus answer quality unverified. Setup prose now sits outside shell fences. Test-function presence is distinguished from passing execution and browser testing.
- **Provenance:** README now lists exact comparison/run paths, saved timestamps and evaluation-set/index labels. It distinguishes the historical comparison file's name from its recorded run date, identifies corpus filenames as question-set metadata, and explicitly leaves missing execution SHA, corpus/index hashes, environment and timezone unknown. Saved results and numeric tables were not changed.
- **Verification / limits:** Local text and XML checks only; no application/test/evaluation execution, installation, ingestion, screenshot analysis or endpoint requests in this correction task. Screenshot contents, rendered SVG readability, source semantics, image use in saved runs, exact same-index execution and fresh-copy deployment remain unverified. Team contribution/review, instructor access and Canvas submission still require team confirmation. The rubric's multimodal-reranking requirement is not demonstrated by text-only reranking; accurately documenting that limitation does not resolve implementation compliance.
- **Final citation/refusal wording correction:** Rechecked `answers.py:141–188, 222–228, 258–301`. README validation now covers indexed text and attached-image source identity, including image-only citations, without implying semantic correctness. The existing SVG labels now describe schema/text-image source checks as not semantic proof and describe `NOT_COVERED` as refusal/fallback handling with a possible retry. Only wording was changed; the diagram was not regenerated and no execution results were added.
- **Current outcome: BLOCKED, not PASS.** Confirmed documentation contradictions are corrected, but A09 cannot be fully accepted without missing provenance and independent semantic/visual evidence. A01–A08 and all material outside A09 were left unchanged; no unrelated application gap was fixed.

## Execution record template

For each case, append a record here only after attempting it:

- **Case / operator / time / tested Git SHA:**
- **Environment and corpus/index identifiers:**
- **Prerequisites actually satisfied:**
- **Exact input and ordered actions:**
- **Expected outcome:**
- **Actual observation for each step:**
- **Sanitized evidence references:**
- **PASS / FAIL / BLOCKED and reason:**
- **Unexecuted steps / reproducibility limitations:**
- **Finding severity and student impact, if any:**

Do not include API keys, private quiz-key files, session tokens, authentication headers, unredacted network captures, or sensitive configuration values.

## Findings

None recorded. This means **no independent testing has occurred**, not that the application has no defects.

## Limitations and acceptance decision

- All cases remain NOT TESTED; this report cannot establish readiness for students.
- The mapping uses original issue descriptions and group documentation. Verify against the instructor's original assignment handout before claiming rubric coverage.
- Existing automated tests and teammate reports provide background, not substitutes for this review's browser observations, semantic source checks or evidence audit.
- Service availability, nondeterministic model outputs, corpus differences and dependency versions may affect reproducibility; record them when executing.
- Live testing, ingestion, service-failure simulation and evidence capture require separate authorization. Do not disrupt shared class services.
- No overall acceptance decision has been made. Report unmet or untested criteria explicitly rather than averaging them into a passing score.
