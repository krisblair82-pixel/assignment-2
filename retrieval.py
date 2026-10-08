"""Hybrid retrieval: keyword (bm25s) + text embeddings (9002) + visual embeddings (9003).

Separate text and visual indexes (per assignment spec):
  - chromadb collection `text_chunks` : one vector per text chunk (9002)
  - chromadb collection `pages`       : one vector per page/slide image (9003, visual)
  - bm25s index over chunk text       : sparse keyword search

Query flow:  bm25 + dense text + visual -> RRF fusion (text and page lists kept
separate) -> multimodal rerank of the fused text candidates via 9004.

CLI:
  python retrieval.py build [--index index/index.json] [--force]
  python retrieval.py query "your question" [--doc DOC_ID] [--k 8]
"""
import argparse
import json
import os
import time

import chromadb

import bm25s

from config import INDEX_DIR, RESULTS_DIR, ensure_configured
from services import Reranker, TextEmbedder, VisualEmbedder

CHROMA_DIR = os.path.join(INDEX_DIR, "chroma")
BM25_DIR = os.path.join(INDEX_DIR, "bm25")
TEXT_COLLECTION = "text_chunks"
PAGES_COLLECTION = "pages"
RRF_K = 60  # standard RRF constant


def _meta(**kw) -> dict:
    """chromadb metadata: drop None values (None is not a valid MetadataValue)."""
    out = {}
    for k, v in kw.items():
        if v is None:
            continue
        if k in ("page", "slide", "chunk_idx") and isinstance(v, (int, float)) and not isinstance(v, bool):
            v = int(v)
        out[k] = v
    return out


def _load_index(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ------------------------------------------------------------------ build

def build_index(index_path: str, force: bool = False) -> dict:
    ensure_configured()
    data = _load_index(index_path)
    chunks, pages = data.get("chunks", []), data.get("pages", [])
    print(f"index source: {index_path}  ({len(chunks)} chunks, {len(pages)} pages)")

    os.makedirs(CHROMA_DIR, exist_ok=True)
    os.makedirs(BM25_DIR, exist_ok=True)
    client = chromadb.PersistentClient(path=CHROMA_DIR)

    # ---- text side: bm25 + dense ----
    texts = [c["text"] for c in chunks]
    docs = [f"{c.get('doc_id')}|p{c.get('page')}|s{c.get('slide')}|{c.get('section')}" for c in chunks]

    bm25 = bm25s.BM25()
    if texts:
        print(f"tokenizing {len(texts)} chunks for bm25 ...")
        corpus_tokens = bm25s.tokenize(texts, stopwords="en")
        bm25.index(corpus_tokens)
        bm25.save(BM25_DIR, corpus=texts)
        print(f"bm25 index saved -> {BM25_DIR}")
    else:
        print("no text chunks - skipping bm25")

    text_col = client.get_or_create_collection(TEXT_COLLECTION,
                                               metadata={"hnsw:space": "cosine"})
    if force:
        try:
            client.delete_collection(TEXT_COLLECTION)
            text_col = client.create_collection(TEXT_COLLECTION,
                                                metadata={"hnsw:space": "cosine"})
        except Exception:  # noqa: BLE001
            pass

    if chunks:
        embedder = TextEmbedder()
        vecs = embedder.embed(texts)
        ids = [f"t{i}" for i in range(len(chunks))]
        metas = [_meta(doc_id=c.get("doc_id"), page=c.get("page"),
                       slide=c.get("slide"), section=c.get("section"),
                       chunk_idx=c.get("chunk_idx")) for c in chunks]
        text_col.add(ids=ids, embeddings=vecs, metadatas=metas, documents=texts)
        print(f"text index: {len(vecs)} chunks @ dim {len(vecs[0])} -> chromadb '{TEXT_COLLECTION}'")

    # ---- visual side: 9003 embeddings of page/slide images ----
    pages_col = client.get_or_create_collection(PAGES_COLLECTION,
                                                metadata={"hnsw:space": "cosine"})
    if force:
        try:
            client.delete_collection(PAGES_COLLECTION)
            pages_col = client.create_collection(PAGES_COLLECTION,
                                                 metadata={"hnsw:space": "cosine"})
        except Exception:  # noqa: BLE001
            pass
    visual_ok = False
    if pages and all(os.path.exists(p["image_path"]) for p in pages):
        embedder = VisualEmbedder()
        try:
            # embed each page image + its doc/page label as paired text
            img_paths = [p["image_path"] for p in pages]
            labels = [f"{p.get('doc_id')} page {p.get('page')} slide {p.get('slide', '')}".strip()
                      for p in pages]
            vecs = embedder.embed(texts=labels, images=img_paths)
            ids = [f"p{i}" for i in range(len(pages))]
            metas = [_meta(doc_id=p.get("doc_id"), page=p.get("page"),
                           slide=p.get("slide"),
                           image_path=p["image_path"], label=labels[i])
                     for i, p in enumerate(pages)]
            pages_col.add(ids=ids, embeddings=vecs, metadatas=metas)
            print(f"visual index: {len(vecs)} page embeddings @ dim {len(vecs[0])} -> '{PAGES_COLLECTION}'")
            visual_ok = True
        except Exception as e:  # noqa: BLE001
            print(f"[warn] visual embeddings failed ({type(e).__name__}: {e}) - "
                  f"text-only index built; re-run when 9003 is back")
    elif pages:
        missing = [p["image_path"] for p in pages if not os.path.exists(p["image_path"])][:3]
        print(f"[warn] skipping visual index - {len(missing)} missing images: {missing}")

    summary = {"built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
               "chunks": len(chunks), "pages": len(pages),
               "bm25": bool(texts), "text_dense": bool(chunks), "visual": visual_ok}
    return summary


# ------------------------------------------------------------------ query

def _rrf_rank(lists_of_ids: list[list[str]]) -> list[tuple[str, float]]:
    """Ranked-list fusion: score(id) = sum over lists of 1/(RRF_K + rank)."""
    scores: dict[str, float] = {}
    for ranked in lists_of_ids:
        for rank, cid in enumerate(ranked):
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


def retrieve(query: str, doc_filter: str | None = None, k: int = 8,
             index_path: str = None) -> dict:
    """Hybrid retrieval. Returns {'text_chunks': [...], 'pages': [...]} with
    fused/reranked ordering and metadata. Resilient: any leg may fail and the
    others still return (the caller sees which legs contributed)."""
    ensure_configured()
    index_path = index_path or os.path.join(INDEX_DIR, "index.json")
    data = _load_index(index_path) if os.path.exists(index_path) else {"chunks": [], "pages": []}
    if not data.get("chunks") and not data.get("pages"):
        print(f"[warn] index file '{index_path}' has no chunks/pages - did you run "
              f"'python retrieval.py build --index {index_path}' after ingesting?")
    chunks, pages = data.get("chunks", []), data.get("pages", [])
    client = chromadb.PersistentClient(path=CHROMA_DIR)
    legs = {"bm25": 0, "text_dense": 0, "visual": 0, "rerank": 0}

    try:
        text_col = client.get_collection(TEXT_COLLECTION)
    except Exception:  # noqa: BLE001
        text_col = None

    # ---- leg 1: bm25 ----
    bm25_hits: list[str] = []
    try:
        bm25 = bm25s.BM25.load(BM25_DIR, load_corpus=False)
        scores, results = bm25.retrieve(bm25s.tokenize([query], stopwords="en"), k=k)
        idxs = results[0].tolist()
        bm25_hits = [f"t{i}" for i in idxs if i < len(chunks)]
        legs["bm25"] = len(bm25_hits)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] bm25 leg failed: {type(e).__name__}: {e}")

    # ---- leg 2: dense text ----
    dense_text_hits: list[str] = []
    if text_col is not None and chunks:
        try:
            qv = TextEmbedder().embed([query])[0]
            where = {"doc_id": doc_filter} if doc_filter else None
            res = text_col.query(query_embeddings=[qv], n_results=k, where=where)
            dense_text_hits = res["ids"][0]
            legs["text_dense"] = len(dense_text_hits)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] dense-text leg failed: {type(e).__name__}: {e}")

    # ---- leg 3: visual ----
    page_hits: list[str] = []
    try:
        pages_col = client.get_collection(PAGES_COLLECTION)
        if pages_col.count() > 0:
            qv = VisualEmbedder().embed(texts=[query])[0]
            where = {"doc_id": doc_filter} if doc_filter else None
            res = pages_col.query(query_embeddings=[qv], n_results=k, where=where)
            page_hits = res["ids"][0]
            legs["visual"] = len(page_hits)
    except Exception as e:  # noqa: BLE001
        print(f"[warn] visual leg failed: {type(e).__name__}: {e}")

    # ---- fusion (RRF) + rerank ----
    fused = _rrf_rank([bm25_hits, dense_text_hits])
    top_text_ids = [cid for cid, _ in fused[:k]]
    page_ids = page_hits  # single leg: keep as-is

    reranked: list[str] = top_text_ids
    if top_text_ids and chunks:
        try:
            id_to_text = {f"t{i}": c["text"] for i, c in enumerate(chunks)}
            docs = [id_to_text[cid] for cid in top_text_ids if cid in id_to_text]
            if docs:
                rr = Reranker().rerank(query, docs)
                ordered = [top_text_ids[r["index"]] for r in rr[:k]]
                reranked = [cid for cid in ordered if cid in id_to_text]
                legs["rerank"] = len(reranked)
        except Exception as e:  # noqa: BLE001
            print(f"[warn] rerank leg failed: {type(e).__name__}: {e}")

    # ---- assemble results ----
    id_to_chunk = {f"t{i}": c for i, c in enumerate(chunks)}
    id_to_page = {f"p{i}": p for i, p in enumerate(pages)}
    out_text = []
    for cid in reranked:
        c = id_to_chunk.get(cid)
        if c:
            out_text.append({"chunk_id": cid, "doc_id": c.get("doc_id"),
                             "page": c.get("page"), "slide": c.get("slide"),
                             "section": c.get("section"), "text": c["text"]})
    out_pages = []
    for pid in page_ids:
        p = id_to_page.get(pid)
        if p:
            out_pages.append({"page_id": pid, "doc_id": p.get("doc_id"),
                              "page": p.get("page"), "slide": p.get("slide"),
                              "image_path": p.get("image_path"), "label": p.get("label")})
    return {"query": query, "doc_filter": doc_filter, "legs": legs,
            "text_chunks": out_text, "pages": out_pages}


# ------------------------------------------------------------------ CLI

def main():
    ap = argparse.ArgumentParser(description="Hybrid retrieval (bm25 + text + visual + rerank)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="build indexes from index/index.json")
    b.add_argument("--index", default=os.path.join(INDEX_DIR, "index.json"))
    b.add_argument("--force", action="store_true", help="rebuild collections from scratch")

    q = sub.add_parser("query", help="retrieve evidence for a question")
    q.add_argument("question")
    q.add_argument("--doc", default=None, help="restrict to one doc_id (topic filter)")
    q.add_argument("--k", type=int, default=8)
    q.add_argument("--index", default=os.path.join(INDEX_DIR, "index.json"))
    q.add_argument("--save", action="store_true", help="save results under results/")

    args = ap.parse_args()
    if args.cmd == "build":
        summary = build_index(args.index, force=args.force)
        print(json.dumps(summary, indent=1))
    else:
        out = retrieve(args.question, doc_filter=args.doc, k=args.k, index_path=args.index)
        print(f"legs: {out['legs']}")
        print(f"\ntop {len(out['text_chunks'])} text chunks:")
        for i, c in enumerate(out["text_chunks"], 1):
            loc = f"doc={c['doc_id']} page={c['page']} slide={c['slide']} sec={c['section']}"
            print(f"  {i}. [{loc}] {c['text'][:110]}")
        if out["pages"]:
            print(f"\ntop {len(out['pages'])} page images:")
            for i, p in enumerate(out["pages"], 1):
                print(f"  {i}. doc={p['doc_id']} page={p['page']} slide={p['slide']} -> {p['image_path']}")
        else:
            print("\nno page-image candidates (visual leg empty - 9003 may be down)")
        if args.save:
            os.makedirs(RESULTS_DIR, exist_ok=True)
            path = os.path.join(RESULTS_DIR, f"retrieval_{time.strftime('%Y%m%d_%H%M%S')}.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump(out, f, indent=1)
            print(f"\nsaved -> {path}")


if __name__ == "__main__":
    main()
