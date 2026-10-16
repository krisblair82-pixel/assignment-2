# Independent student acceptance checklist

## Scope and requirement sources

This is a manual acceptance plan, not an execution record. Every case starts as **NOT TESTED**. Results belong in `acceptance-report.md`.

The mapping uses the original GitHub issues #1–#8 and the requirement descriptions recorded by the group. The original instructor handout is not included here; verify the mapping against that handout before claiming rubric completion. Requirement 1a (in-app document management) and 2a (original visual evidence) are identified in the project documentation. Issue numbers below are project traceability IDs, not invented rubric numbers.

| Original issue | Scope | Acceptance cases |
|---|---|---|
| #1 | Ingestion, source metadata, original page/slide images | A01, A02, A03 |
| #2 | Keyword/text/visual retrieval, separate indexes, combining results, reranking | A03, A09 |
| #3 | Structured grounded answers, valid citations, missing information | A03, A06, A07 |
| #4 | Material/topic selection, fixed hidden quiz key, scoring, explanations | A04, A05 |
| #5 | Reproducible hybrid-versus-keyword comparison | A09 |
| #6 | Automated checks and repeatable evaluation evidence | A09 (evidence audit only; not a replacement for tests) |
| #7 | Student UI, accepted formats, safe errors, evidence panel | A01–A08 |
| #8 | Reproducible setup, evidence-backed findings, limitations | A08, A09 and the report |

## Preconditions and safe execution

- This document authorizes no execution. Obtain approval before launching, uploading, deleting, changing service configuration, or calling class services.
- Test a recorded commit in an isolated local runtime. Do not use a teammate's active materials/indexes or production data. Keep existing contribution branches untouched.
- Record OS, Python and dependency versions, browser, material inventory and content hashes, index provenance, and relevant office converter availability. Never record credentials or sensitive endpoint values.
- Use two permitted, distinct small documents (A and B), a permitted slide deck with a known visual page, an exact duplicate of A, an unsupported file, and a malformed document. Record exact filenames, prompts, expected facts and page/slide locations before execution.
- Establish a known-good baseline. For service-failure testing, use only an approved local fault-injection method; never stop or reconfigure shared class services. If safe isolation is unavailable, mark the case BLOCKED when attempted.
- Save sanitized evidence only after execution and review. Do not publish answer keys, browser authorization headers, local `.env`, full network captures, copyrighted materials, or sensitive paths. Use minimal redacted observations/screenshots.
- A missing prerequisite does not turn an unattempted case into a result. Keep it NOT TESTED until a reviewer attempts and records the blocker.

## Manual cases

### A01 — Upload and selection (issues #1, #7; requirement 1a)
1. Record the empty/baseline material chooser and inventory.
2. In Course materials, upload document A and document B through the UI.
3. Wait for completion; inspect the material table and both question/quiz choosers.
4. Select A, ask a pre-recorded question unique to A, and request a quiz from A.
5. Check saved inventory and source metadata against the original document.
**Expected:** accepted formats are explained; completion/errors are understandable; each document appears once, is selectable, and has correct source locations. PDF/slide inputs preserve their original page/slide images. Text-only formats are honestly identified. A-selected content does not cite B.
**Evidence:** sanitized before/after observations, material IDs, inventory reference, exact prompt and cited location. **Initial status: NOT TESTED.**

### A02 — Repeated uploads and removal (issues #1, #7; requirement 1a)
1. Upload A again unchanged; then upload the identical bytes under another filename.
2. Try different contents under A's existing filename; record the message and resulting inventory.
3. Remove A in the UI; verify table and both choosers refresh.
4. Start a new question and quiz interaction that would require A; refresh/reopen the browser and repeat the availability check. Confirm B still works.
**Expected:** duplicates do not create extra indexed entries; name/content collisions do not silently overwrite A. Removal prevents new retrieval/quiz selection from using A, removes its indexed evidence, and does not affect B. Distinguish historical displayed answers from newly generated answers.
**Evidence:** inventory counts before/after, messages, new-response citations, and refresh behavior. **Initial status: NOT TESTED.**

### A03 — Visual evidence, citation fidelity and document isolation (issues #2, #3, #7; requirement 2a)
1. Select the known deck and ask a recorded visual question whose answer requires examining a chart, diagram or meme, rather than only the title.
2. Compare every factual answer claim, source excerpt and displayed original image with the source slide/page.
3. Ask a text question with a known answer location and inspect document/page/slide/section references.
4. Select B and ask about a fact or image unique to A; inspect both the answer and image gallery.
**Expected:** correct original image and source location accompany visual answers; excerpts match the source; unsupported visual details are not invented. Filtering to B must not attach or cite A's evidence. A real citation alone is not proof that a claim is supported.
**Evidence:** exact prompts, selected material, minimal answer excerpts, expected/actual source locations and redacted visual comparison. **Initial status: NOT TESTED.**

### A04 — Quiz generation, hidden solutions and deterministic scoring (issues #4, #7)
1. Select A and a topic known to exist; generate a small quiz.
2. Before answering, inspect visible controls and browser-delivered data for premature answer/solution disclosure without saving raw payloads.
3. Leave one question unanswered; submit the others with independently checked answers from the source. Record the exact selections.
4. Verify total and per-question scores; submit identical selections again.
5. Explicitly reveal explanations and compare their citations with the source.
**Expected:** questions respect material/topic selection; unanswered solutions remain hidden until requested; scores match source-verified answers and remain stable across repeated submissions; revealed explanations cite the appropriate material and image where relevant. No credentials appear in browser-visible data.
**Evidence:** public questions, submitted choices, independently calculated expected score, displayed score and redacted source references. Do not commit private key files. **Initial status: NOT TESTED.**

### A05 — Quiz reset and independent student sessions (issues #4, #7)
1. Generate and partially answer a quiz in one browser session.
2. Generate a new quiz with another document/topic; check for retained selections, scores or explanations.
3. Open a separate private browser session, generate another quiz, and interleave scoring in both sessions.
**Expected:** the current quiz uses its own fixed key; prior selections do not silently answer a new quiz; scores/solutions and student state do not leak between independent sessions.
**Evidence:** session labels (not tokens), action sequence, selected materials, visible reset behavior and scores. **Initial status: NOT TESTED.**

### A06 — Missing information and unsupported topics (issues #3, #4, #7)
1. Ask a question absent from all supplied material; record the exact wording.
2. Select B and ask about a fact known only to A.
3. Request a quiz topic absent from the selected material.
4. Follow with a supported question/topic.
**Expected:** the assistant acknowledges missing information without fabricated facts or citations; absent topics do not silently generate an unrelated quiz; subsequent supported interactions work.
**Evidence:** prompts, material filters, refusals/messages, source lists and recovery observation. **Initial status: NOT TESTED.**

### A07 — Failure, safe errors and recovery (issues #3, #7)
1. Submit an unsupported file and a malformed document separately; inspect UI and inventory afterward.
2. Using the approved isolated method, make one required service unavailable during an interaction. Record which service role was affected, not private URLs.
3. Inspect visible messages and sanitized local diagnostics for credential leakage, misleading success or stale evidence.
4. Restore the isolated test configuration and repeat a valid interaction.
**Expected:** errors are safe and actionable, with no raw secrets or traceback exposure to students; failed work is not presented as successful; degraded retrieval is distinguishable from complete success; a later valid interaction recovers. No shared service is disrupted.
**Evidence:** fault method, safe message excerpts, state before/after and recovery sequence. **Initial status: NOT TESTED.**

### A08 — Student usability and setup clarity (issues #7, #8)
1. From the documented prerequisites, record any ambiguous or missing setup instructions without assuming teammate-specific files exist.
2. Complete question, quiz and material-selection workflows using keyboard-only navigation.
3. Inspect light/dark presentation and a narrow browser viewport; read source labels and view a slide image.
4. Observe feedback during a slow operation and after validation errors.
**Expected:** controls and focus order are understandable; quiz choices and actions are usable without JSON entry; evidence is legible; loading/completion states are visible; documentation identifies required local materials, configuration and indexes honestly.
**Evidence:** browser/viewport, navigation sequence, specific control labels and reproducible usability defects. This is not a formal accessibility certification. **Initial status: NOT TESTED.**

### A09 — Retrieval/comparison evidence and submission traceability (issues #2, #5, #6, #8)
1. Record the exact code revision and corpus/index identity for each artifact used in the submission.
2. Inspect evidence for keyword, dense-text and image retrieval, separate text/image indexes, result combination and candidate reranking. Explicitly distinguish text-only reranking from image-content reranking.
3. Trace each reported comparison metric to raw runs using the same questions and index; verify selected retrieval mode reaches answer generation and document any additional image evidence supplied by other paths.
4. Distinguish location/schema checks from independent semantic correctness. Verify claimed automated test counts refer to the recorded revision/environment.
5. Record stale, contradictory or missing evidence as findings. Do not rerun evaluations as part of this audit without separate approval.
**Expected:** claims accurately describe the implemented pipeline and evidence; historical reports are not presented as fresh independent tests; unsupported requirement interpretations are flagged for clarification.
**Evidence:** commit IDs, artifact paths and exact fields/claims reconciled. Existing teammate results are audit inputs, never independent execution observations. **Initial status: NOT TESTED.**

## Outcome rules

- **NOT TESTED:** no independent execution/audit yet.
- **PASS:** all expected outcomes observed with sufficient evidence.
- **FAIL:** an expected outcome contradicted; record exact reproduction and impact.
- **BLOCKED:** attempted but an identified prerequisite prevents a conclusion; record what was and was not attempted.

Do not infer overall acceptance from automated test success, screenshots alone, or this checklist's existence. Track partial steps explicitly and do not call a partially verified case PASS.
