"""In-app document management (assignment requirement 1a).

Users add and remove course materials through the app:
  - add_document(): copy an uploaded file into materials/, run the single-file
    ingestion pipeline (9005 parse -> text chunks + page images), and merge
    the result into index/index.json. Loading the same file twice does NOT
    duplicate it (checked by filename AND content hash).
  - remove_document(): delete the source file, drop its chunks/pages from
    index/index.json, delete its rendered slide/page images, then rebuild the
    search collections so later answers never rely on removed material.

The searchable index (chroma + bm25) is rebuilt with retrieval.build_index()
after each change; pass rebuild=False to defer (used by tests, or when many
files are added in one batch).

CLI:
  python documents.py list
  python documents.py add <file> [--no-rebuild]
  python documents.py remove <doc_id> [--no-rebuild]
"""
import argparse
import glob
import hashlib
import json
import os
import re
import shutil
import time

from config import (INDEX_DIR, MATERIALS_DIR, RENDERS_DIR, RESULTS_DIR,
                    ensure_configured)
from ingest import ACCEPTED_EXTENSIONS, process_file, slugify


def _index_path() -> str:
    return os.path.join(INDEX_DIR, "index.json")


def _load_index() -> dict:
    path = _index_path()
    if os.path.isfile(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {"chunks": [], "pages": []}


def _save_index(data: dict) -> str:
    os.makedirs(INDEX_DIR, exist_ok=True)
    path = _index_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    return path


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def list_documents() -> list[dict]:
    """Indexed documents with file, pages, chunks and image counts."""
    data = _load_index()
    chunks, pages = data.get("chunks", []), data.get("pages", [])
    by_doc: dict[str, dict] = {}
    for c in chunks:
        d = by_doc.setdefault(c["doc_id"], {"doc_id": c["doc_id"], "chunks": 0,
                                            "pages": 0, "images": 0, "file": None})
        d["chunks"] += 1
        if c.get("page") is not None or c.get("slide") is not None:
            d["pages"] = max(d["pages"], int(c.get("page") or 0),
                             int(c.get("slide") or 0))
    for p in pages:
        d = by_doc.setdefault(p["doc_id"], {"doc_id": p["doc_id"], "chunks": 0,
                                            "pages": 0, "images": 0, "file": None})
        d["images"] += 1
    for d in by_doc.values():
        src = _find_source_file(d["doc_id"])
        d["file"] = os.path.basename(src) if src else None
        d["present"] = src is not None
    return sorted(by_doc.values(), key=lambda d: d["doc_id"])


def _find_source_file(doc_id: str) -> str | None:
    """Reverse slugify: locate the materials/ file whose doc_id matches."""
    for f in sorted(glob.glob(os.path.join(MATERIALS_DIR, "**", "*"),
                              recursive=True)):
        if os.path.isfile(f) and slugify(os.path.relpath(f, MATERIALS_DIR)) == doc_id:
            return f
    return None


def _safe_name(orig_name: str) -> str:
    name = os.path.basename((orig_name or "").replace("\\", "/"))
    name = re.sub(r"[^\w.\- ()]", "_", name).strip(" .")
    return name or "upload.bin"


def add_document(upload_path: str, orig_name: str | None = None,
                 rebuild: bool = True) -> tuple[bool, str, str | None]:
    """Add one uploaded file. Returns (ok, message, doc_id).

    Dedup: same filename or same content hash already in materials/ -> skip.
    """
    ensure_configured()
    name = _safe_name(orig_name or os.path.basename(upload_path))
    ext = os.path.splitext(name)[1].lower()
    if ext not in ACCEPTED_EXTENSIONS:
        supported = ", ".join(sorted(ACCEPTED_EXTENSIONS))
        return False, f"Unsupported format '{ext or name}'. Accepted: {supported}.", None

    os.makedirs(MATERIALS_DIR, exist_ok=True)
    destination = os.path.join(MATERIALS_DIR, name)
    hash_new = _sha256(upload_path)

    # Duplicate check: identical filename AND identical content, or same content.
    for existing in sorted(glob.glob(os.path.join(MATERIALS_DIR, "*"))):
        if not os.path.isfile(existing):
            continue
        if os.path.basename(existing).lower() == name.lower() and \
                _sha256(existing) == hash_new:
            doc_id = slugify(os.path.relpath(existing, MATERIALS_DIR))
            return True, f"Already uploaded (identical file) - no duplicate added.", doc_id
        if os.path.basename(existing).lower() == name.lower() and \
                _sha256(existing) != hash_new:
            return False, ("A file with this name already exists but has "
                           "different content. Rename your file and try again."), None
    for existing in sorted(glob.glob(os.path.join(MATERIALS_DIR, "*"))):
        if os.path.isfile(existing) and _sha256(existing) == hash_new:
            doc_id = slugify(os.path.relpath(existing, MATERIALS_DIR))
            return True, f"Already uploaded (same content) - no duplicate added.", doc_id

    shutil.copy2(upload_path, destination)
    doc_id = slugify(os.path.relpath(destination, MATERIALS_DIR))

    # Parse/process the single file (network calls: 9005 per page).
    from services import Parser
    try:
        chunks, pages, entry = process_file(destination, Parser(), dry_run=False)
    except Exception as e:  # noqa: BLE001
        os.remove(destination)
        return False, f"Failed to process '{name}': {e}", None

    data = _load_index()
    data.setdefault("chunks", []).extend(chunks)
    data.setdefault("pages", []).extend(pages)
    _save_index(data)
    message = (f"Added '{name}' ({entry['pages']} pages/slides, "
               f"{len(chunks)} chunks, {len(pages)} images).")
    if entry.get("warning"):
        message += f" Note: {entry['warning']}"
    if rebuild:
        _rebuild_indexes()
        message += " Search index rebuilt."
    return True, message, doc_id


def remove_document(doc_id: str, rebuild: bool = True) -> tuple[bool, str]:
    """Remove a document and ALL of its searchable content."""
    source = _find_source_file(doc_id)
    if source is None:
        return False, f"Document '{doc_id}' not found in materials/."

    data = _load_index()
    before_c = len(data.get("chunks", []))
    before_p = len(data.get("pages", []))
    data["chunks"] = [c for c in data.get("chunks", []) if c.get("doc_id") != doc_id]
    data["pages"] = [p for p in data.get("pages", []) if p.get("doc_id") != doc_id]
    removed_c = before_c - len(data["chunks"])
    removed_p = before_p - len(data["pages"])
    _save_index(data)

    # Delete rendered page/slide images for this document.
    base = os.path.splitext(os.path.basename(source))[0]
    removed_imgs = 0
    for img in glob.glob(os.path.join(RENDERS_DIR, f"{base}_*.png")) + \
               glob.glob(os.path.join(RENDERS_DIR, f"{base}.pdf")):
        try:
            os.remove(img)
            removed_imgs += 1
        except OSError:
            pass

    os.remove(source)
    if rebuild:
        _rebuild_indexes()

    message = (f"Removed '{doc_id}' (source file, {removed_c} chunks, "
               f"{removed_p} page images{', ' + str(removed_imgs) + ' rendered files' if removed_imgs > 0 else ''}).")
    if rebuild:
        message += " Search index rebuilt - removed content is no longer searchable."
    return True, message


def _rebuild_indexes() -> dict:
    """Rebuild chroma + bm25 from index/index.json (needs 9002/9003)."""
    from retrieval import build_index
    summary = build_index(os.path.join(INDEX_DIR, "index.json"), force=True)
    stamp = time.strftime("%Y%m%d_%H%M%S")
    path = os.path.join(RESULTS_DIR, f"index_rebuild_{stamp}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=1)
    return summary


# ------------------------------------------------------------------ CLI

def main() -> None:
    ap = argparse.ArgumentParser(description="Manage course materials (req 1a)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="list indexed documents")

    a = sub.add_parser("add", help="add a material file")
    a.add_argument("file")
    a.add_argument("--no-rebuild", action="store_true")

    r = sub.add_parser("remove", help="remove a document by doc_id")
    r.add_argument("doc_id")
    r.add_argument("--no-rebuild", action="store_true")

    args = ap.parse_args()
    if args.cmd == "list":
        docs = list_documents()
        if not docs:
            print("no documents indexed yet - ingest some materials first")
            return
        width = max(len(d["doc_id"]) for d in docs)
        for d in docs:
            print(f"{d['doc_id']:<{width}}  pages~{d['pages']:>3}  "
                  f"chunks {d['chunks']:>4}  images {d['images']:>3}  present={d['present']}")
    elif args.cmd == "add":
        ok, message, doc_id = add_document(args.file, rebuild=not args.no_rebuild)
        print(("OK   " if ok else "FAIL ") + message + (f"  doc_id={doc_id}" if doc_id else ""))
    else:
        ok, message = remove_document(args.doc_id, rebuild=not args.no_rebuild)
        print(("OK   " if ok else "FAIL ") + message)


if __name__ == "__main__":
    main()
