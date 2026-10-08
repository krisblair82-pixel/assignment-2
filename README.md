# MBAX 6418 — Assignment 2: Course Assistant

Build a course assistant that answers questions and generates practice quizzes using **course materials**.

## What it is
- **Hybrid RAG** over the course materials: keyword search (bm25) + **text embeddings** + **visual embeddings** (page/slide images), kept in **separate text and visual indexes**, combined with fused ranking and a **multimodal reranker**.
- **Grounded answers**: every answer cites its source (document + page/slide/section) with a real excerpt or the original page image. Missing information is acknowledged — never invented.
- **Practice quizzes**: choose a course material (optional topic filter) → multiple-choice quiz with fixed answer key, scores, and explanations tied back to the sources.

## Class services used (do NOT use port 9000 for this app — reserved for Hermes)
| Port | Service | Model |
|---|---|---|
| 9001 | Vision LLM (chat/completions) | cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit |
| 9002 | Text embeddings (POST /v1/embeddings, dim 2048) | nvidia/Nemotron-3-Embed-1B-BF16 |
| 9003 | Visual embeddings (POST /embeddings — no `/v1`, dim 2048) | Qwen/Qwen3-VL-Embedding-2B |
| 9004 | Multimodal rerank (POST /v1/rerank) | Qwen/Qwen3-VL-Reranker-2B |
| 9005 | Document parsing (dots.mocr) | dots.mocr |

## Security
- Secrets live **only** in a local, gitignored `.env` (copy `config.example` → `.env` and fill real values).
- A **pre-commit secret scanner** (`scripts/scan_secrets.sh`, wired via `core.hooksPath`) blocks any commit containing a value from `.env` or a known secret pattern.
- Nothing secret may appear in code, the UI, logs, errors, screenshots, docs, test results, or issues/PRs.

## Repo setup (one-time)
```bash
git config core.hooksPath scripts/hooks   # activate the secret scanner
python -m venv .venv && source .venv/bin/activate   # (Windows: .venv\Scripts\activate)
pip install -r requirements.txt           # pending
cp config.example .env                    # fill in the real class API key
```

## Status
Scaffolding: repo plumbing + connectivity verified (see `connectivity_report.md`). Build tasks tracked as GitHub issues (no owners assigned — team picks them up).

## Quick start (current skeleton)
```bash
python -m venv .venv && .venv\Scripts\activate   # (or: uv venv .venv)
pip install -r requirements.txt
cp config.example .env                            # fill in the real class API key

python probe_services.py    # connectivity check for 9001-9005 (scrubbed)
python smoke.py             # live smoke test: embed / rerank / chat / parse
python ingest.py --dry-run  # inventory + page rendering, no network calls
python ingest.py            # full ingest once materials/ has course files
```

## Result files (committed evidence)
- `connectivity_report.md` — initial service probes (routes + quirks found)
- `results/smoke_*.json` — live smoke test results, timestamped
- `results/inventory_*.json` — per-file ingest inventory, timestamped

## Known open items (honest status)
- 9003 (visual embeddings) server went down during the skeleton smoke test; text+image embedding clients are schema-verified but the image path needs one end-to-end re-check when the server returns. 9002/9004/9005/9001 all pass live.
- Visual-embedding request containing an image may have contributed to the 9003 crash — we are keeping image payloads small and will retest carefully.
