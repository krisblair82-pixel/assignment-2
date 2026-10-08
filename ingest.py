"""Ingestion pipeline: course materials -> text index + page/slide images.

Pipeline per file:
  1. Render every PDF page / PPTX slide to an image (preserves the ORIGINAL
     page/slide for visual evidence; rendered to renders/pages/).
  2. Parse each page image via the document parsing service (9005, dots.mocr)
     into structured text (tables->HTML, formulas->LaTeX, headings kept).
     (--dry-run skips network calls and uses embedded text where available.)
  3. Chunk with langchain-text-splitters, keeping {doc_id, page/slide, section}.
  4. Write index/index.json (chunks + page records) and results/inventory_*.json.

Idempotent: re-running overwrites the index. Formats: see ACCEPTED_EXTENSIONS.
"""
import argparse
import glob
import json
import os
import re
import sys
import time

from config import INDEX_DIR, MATERIALS_DIR, RESULTS_DIR, RENDERS_DIR, ensure_configured

# Formats the app accepts/explains in the UI
ACCEPTED_EXTENSIONS = {
    ".pdf": "PDF documents (slides, papers) - text + page images",
    ".pptx": "PowerPoint slides - text + slide images",
    ".docx": "Word documents - text with section anchors",
    ".txt": "Plain text",
    ".md": "Markdown notes",
    ".png": "Standalone image (slide screenshot, diagram)",
    ".jpg": "Standalone image (slide screenshot, diagram)",
    ".jpeg": "Standalone image (slide screenshot, diagram)",
}

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


# ---------------------------------------------------------------- renderers

def render_pdf_pages(pdf_path: str, out_dir: str, dpi: int = 150) -> list[dict]:
    """Render every PDF page to PNG. Returns [{page, image_path, embedded_text}]."""
    import fitz  # pymupdf

    pages = []
    doc = fitz.open(pdf_path)
    base = os.path.splitext(os.path.basename(pdf_path))[0]
    for i, page in enumerate(doc, start=1):
        pix = page.get_pixmap(dpi=dpi)
        img = os.path.join(out_dir, f"{base}_p{i:03d}.png")
        pix.save(img)
        pages.append({"page": i, "image_path": img,
                      "embedded_text": page.get_text().strip()})
    doc.close()
    return pages


def find_soffice() -> str | None:
    """Locate LibreOffice (used to render PPTX/DOCX to PDF)."""
    candidates = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/usr/bin/soffice", "/opt/libreoffice/program/soffice",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def render_pptx_slides(pptx_path: str, out_dir: str) -> tuple[list[dict], str | None]:
    """Slide text via python-pptx; slide images via LibreOffice -> PDF -> render.
    Returns (slides, warning) where slides have {slide, text, image_path?}."""
    from pptx import Presentation

    prs = Presentation(pptx_path)
    slides = []
    for i, slide in enumerate(prs.slides, start=1):
        text_parts = []
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    t = "".join(run.text for run in para.runs).strip()
                    if t:
                        text_parts.append(t)
        slides.append({"slide": i, "text": "\n".join(text_parts), "image_path": None})

    soffice = find_soffice()
    warning = None
    if soffice is None:
        warning = "LibreOffice not found - slide images will be skipped (text indexed only)."
        return slides, warning

    base = os.path.splitext(os.path.basename(pptx_path))[0]
    pdf_path = os.path.join(out_dir, f"{base}.pdf")
    import subprocess
    subprocess.run([soffice, "--headless", "--convert-to", "pdf",
                    "--outdir", out_dir, pptx_path], check=True, timeout=300,
                   capture_output=True)
    if os.path.exists(pdf_path):
        page_imgs = render_pdf_pages(pdf_path, out_dir)
        for slide, page in zip(slides, page_imgs):
            slide["image_path"] = page["image_path"]
    return slides, warning


def extract_docx_sections(docx_path: str) -> list[dict]:
    """DOCX -> sections with heading anchors (docx has no natural pages)."""
    from docx import Document

    doc = Document(docx_path)
    section, blocks = "Intro", []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        if para.style and para.style.name and para.style.name.lower().startswith("heading"):
            section = text
        blocks.append({"section": section, "text": text})
    return blocks


# ---------------------------------------------------------------- parsing

def parse_page_text(image_path: str, parser, dry_run: bool) -> str:
    """Page image -> structured text via 9005; dry-run falls back to nothing."""
    if dry_run:
        return ""
    try:
        return parser.parse_page(image_path)
    except Exception as e:  # noqa: BLE001 - one bad page must not kill the run
        print(f"  [warn] parse failed for {os.path.basename(image_path)}: {e}")
        return ""


# ---------------------------------------------------------------- chunking

def chunk_texts(blocks: list[dict], doc_id: str, source_kind: str) -> list[dict]:
    """Chunk parsed page/section text, keeping source metadata."""
    from langchain_text_splitters import RecursiveCharacterTextSplitter

    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)
    chunks = []
    for b in blocks:
        text = (b.get("text") or "").strip()
        if not text:
            continue
        for i, piece in enumerate(splitter.split_text(text)):
            chunks.append({
                "doc_id": doc_id,
                "kind": source_kind,          # page | slide | section | image
                "page": b.get("page"),
                "slide": b.get("slide"),
                "section": b.get("section"),
                "chunk_idx": i,
                "text": piece,
            })
    return chunks


def slugify(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


# ---------------------------------------------------------------- pipeline

def ingest(materials_dir: str, dry_run: bool = False) -> dict:
    os.makedirs(RENDERS_DIR, exist_ok=True)
    os.makedirs(INDEX_DIR, exist_ok=True)
    os.makedirs(RESULTS_DIR, exist_ok=True)

    parser = None
    if not dry_run:
        from services import Parser
        parser = Parser()

    files = sorted(glob.glob(os.path.join(materials_dir, "**", "*"), recursive=True))
    files = [f for f in files if os.path.isfile(f)
             and os.path.splitext(f)[1].lower() in ACCEPTED_EXTENSIONS]

    inventory = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                 "dry_run": dry_run, "files": []}
    all_chunks, pages = [], []
    unsupported = []

    for f in files:
        ext = os.path.splitext(f)[1].lower()
        doc_id = slugify(os.path.relpath(f, materials_dir))
        print(f"\n== {os.path.basename(f)}  ({ext})")
        entry = {"file": os.path.basename(f), "doc_id": doc_id, "format": ext,
                 "pages": 0, "chunks": 0, "images": 0, "warning": None}
        try:
            if ext == ".pdf":
                rendered = render_pdf_pages(f, RENDERS_DIR)
                blocks = []
                for r in rendered:
                    text = parse_page_text(r["image_path"], parser, dry_run) or r["embedded_text"]
                    blocks.append({"page": r["page"], "text": text})
                    pages.append({"doc_id": doc_id, "page": r["page"],
                                  "image_path": r["image_path"]})
                entry["pages"] = len(rendered)
                entry["images"] = len(rendered)
                chunks = chunk_texts(blocks, doc_id, "page")
            elif ext == ".pptx":
                slides, warning = render_pptx_slides(f, RENDERS_DIR)
                entry["warning"] = warning
                blocks = []
                for s in slides:
                    text = s["text"]
                    if s["image_path"] and not dry_run:
                        parsed = parse_page_text(s["image_path"], parser, dry_run)
                        text = parsed or text
                    blocks.append({"slide": s["slide"], "text": text})
                    if s["image_path"]:
                        pages.append({"doc_id": doc_id, "slide": s["slide"],
                                      "image_path": s["image_path"]})
                entry["pages"] = len(slides)
                entry["images"] = sum(1 for s in slides if s["image_path"])
                chunks = chunk_texts(blocks, doc_id, "slide")
            elif ext == ".docx":
                blocks = extract_docx_sections(f)
                entry["pages"] = len(blocks)
                chunks = chunk_texts(blocks, doc_id, "section")
            elif ext in (".txt", ".md"):
                with open(f, encoding="utf-8", errors="replace") as fh:
                    chunks = chunk_texts([{"text": fh.read(), "section": None}], doc_id, "section")
                entry["pages"] = 1
            else:  # standalone images (.png/.jpg/.jpeg)
                if not dry_run:
                    parsed = parse_page_text(f, parser, dry_run)
                else:
                    parsed = ""
                rel = os.path.relpath(f, REPO_ROOT)
                pages.append({"doc_id": doc_id, "page": 1, "image_path": f})
                if parsed:
                    chunks = chunk_texts([{"page": 1, "text": parsed}], doc_id, "image")
                else:
                    chunks = []
                entry["pages"] = 1
                entry["images"] = 1

            entry["chunks"] = len(chunks)
            all_chunks.extend(chunks)
            inventory["files"].append(entry)
            print(f"  pages/sections: {entry['pages']}  chunks: {entry['chunks']}  images: {entry['images']}")
        except Exception as e:  # noqa: BLE001
            entry["error"] = str(e)[:200]
            inventory["files"].append(entry)
            print(f"  FAILED: {e}")

    # write index + inventory (results/ is committed evidence; index/ is regenerable)
    index_path = os.path.join(INDEX_DIR, "index.json")
    with open(index_path, "w", encoding="utf-8") as fh:
        json.dump({"chunks": all_chunks, "pages": pages}, fh, indent=1)
    inv_path = os.path.join(RESULTS_DIR, f"inventory_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(inv_path, "w", encoding="utf-8") as fh:
        json.dump(inventory, fh, indent=1)

    print(f"\n{'='*60}")
    print(f"files processed : {len(inventory['files'])}")
    print(f"total chunks    : {len(all_chunks)}")
    print(f"page images     : {len(pages)}")
    print(f"index           : {index_path}")
    print(f"inventory       : {inv_path}")
    return inventory


def main():
    ap = argparse.ArgumentParser(description="Ingest course materials into the index.")
    ap.add_argument("--materials", default=MATERIALS_DIR, help="folder with course files")
    ap.add_argument("--dry-run", action="store_true",
                    help="inventory + page rendering only (no network calls)")
    args = ap.parse_args()

    if not os.path.isdir(args.materials):
        print(f"no materials folder at {args.materials} - drop course files there "
              f"and re-run. Accepted: {', '.join(sorted(ACCEPTED_EXTENSIONS))}")
        sys.exit(1)

    if not args.dry_run:
        ensure_configured()
    ingest(args.materials, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
