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
        # macOS
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
        # Homebrew (macOS / Linux)
        "/opt/homebrew/bin/soffice", "/usr/local/bin/soffice",
    ]
    for c in candidates:
        if os.path.exists(c):
            return c
    return None


def _run_applescript(script: str, timeout: int = 240) -> None:
    """Run an osascript snippet; raise RuntimeError on failure."""
    import subprocess
    proc = subprocess.run(["osascript", "-e", script], capture_output=True,
                          text=True, timeout=timeout)
    if proc.returncode != 0:
        raise RuntimeError(f"osascript failed: {proc.stderr.strip()[:300]}")


def _keynote_convert_pptx_to_pdf(pptx_path: str, out_pdf: str) -> bool:
    """Render a PPTX to PDF through Keynote (macOS only).

    Keynote is a GUI app: this briefly launches it and may flash on screen.
    Returns True on success, False if Keynote is unavailable.
    """
    import subprocess
    if os.name == "nt":
        return False
    try:
        subprocess.run(["osascript", "-e", "tell application \"System Events\" to get name of every application process whose name is \"Keynote\""],
                       capture_output=True, timeout=30)
    except Exception:  # noqa: BLE001
        pass
    if not os.path.exists("/Applications/Keynote.app"):
        return False
    script = (
        'tell application "Keynote"\n'
        f'  set theDoc to open POSIX file "{pptx_path}"\n'
        "  delay 3\n"
        f'  export theDoc to POSIX file "{out_pdf}" as PDF\n'
        "  close theDoc saving no\n"
        "end tell"
    )
    try:
        _run_applescript(script, timeout=300)
        return os.path.isfile(out_pdf) and os.path.getsize(out_pdf) > 0
    except Exception:  # noqa: BLE001
        return False


def _macos_powerpoint_convert_pptx_to_pdf(pptx_path: str, out_pdf: str) -> bool:
    """Render a PPTX to PDF through Microsoft PowerPoint for Mac.

    Same caveats as Keynote: the app briefly launches. Returns False when
    PowerPoint is unavailable or the conversion fails.
    """
    import subprocess
    if os.name == "nt":
        return False
    probe = subprocess.run(
        ["osascript", "-e",
         'tell application "System Events" to get name of every application process whose name is "Microsoft PowerPoint"'],
        capture_output=True, timeout=30, text=True)
    if probe.returncode != 0 or "Microsoft PowerPoint" not in probe.stdout:
        return False
    script = (
        'tell application "Microsoft PowerPoint"\n'
        f'  open POSIX file "{pptx_path}"\n'
        "  delay 3\n"
        "  set thePres to active presentation\n"
        f'  save thePres in POSIX file "{out_pdf}" as save as PDF\n'
        "  close thePres\n"
        "end tell"
    )
    try:
        _run_applescript(script, timeout=300)
        return os.path.isfile(out_pdf) and os.path.getsize(out_pdf) > 0
    except Exception:  # noqa: BLE001
        return False



def render_pptx_slides(pptx_path: str, out_dir: str) -> tuple[list[dict], str | None]:
    """Slide text via python-pptx; images via LibreOffice, PowerPoint, or Keynote.
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
    base = os.path.splitext(os.path.basename(pptx_path))[0]
    if soffice is None and os.name == "nt":
        try:
            import win32com.client
            app = win32com.client.DispatchEx("PowerPoint.Application")
            deck = None
            try:
                deck = app.Presentations.Open(os.path.abspath(pptx_path),
                                              ReadOnly=True, WithWindow=False)
                if deck.Slides.Count != len(slides):
                    raise RuntimeError("PowerPoint rendered a different slide count")
                for i, slide in enumerate(deck.Slides, start=1):
                    img = os.path.abspath(os.path.join(out_dir, f"{base}_p{i:03d}.png"))
                    slide.Export(img, "PNG", 1280, 720)
                    if not os.path.isfile(img) or os.path.getsize(img) == 0:
                        raise RuntimeError(f"PowerPoint did not render slide {i}")
                    slides[i-1]["image_path"] = img
            finally:
                if deck is not None:
                    deck.Close()
                app.Quit()
            return slides, None
        except ImportError:
            return slides, "LibreOffice absent and pywin32 unavailable - text only."
        except Exception:  # COM may be installed even when PowerPoint is not usable
            for slide in slides:
                slide["image_path"] = None
            return slides, "PowerPoint rendering failed - text only."
    if soffice is None:
        # macOS fallbacks: Keynote first, then Microsoft PowerPoint.
        pdf_path = os.path.join(out_dir, f"{base}.pdf")
        converted = (_keynote_convert_pptx_to_pdf(pptx_path, pdf_path)
                     or _macos_powerpoint_convert_pptx_to_pdf(pptx_path, pdf_path))
        if converted and os.path.exists(pdf_path):
            page_imgs = render_pdf_pages(pdf_path, out_dir)
            if len(page_imgs) == len(slides):
                for slide, page in zip(slides, page_imgs):
                    slide["image_path"] = page["image_path"]
                return slides, "Rendered via Keynote/PowerPoint (macOS); LibreOffice recommended for headless use."
            os.remove(pdf_path)
        return slides, ("No LibreOffice/PowerPoint/Keynote available - text only. "
                        "Export the deck to PDF manually for slide images.")

    pdf_path = os.path.join(out_dir, f"{base}.pdf")
    import subprocess
    subprocess.run([soffice, "--headless", "--convert-to", "pdf",
                    "--outdir", out_dir, pptx_path], check=True, timeout=300,
                   capture_output=True)
    if os.path.exists(pdf_path):
        page_imgs = render_pdf_pages(pdf_path, out_dir)
        if len(page_imgs) != len(slides):
            raise RuntimeError("PDF rendering produced a different slide count")
        for slide, page in zip(slides, page_imgs):
            slide["image_path"] = page["image_path"]
    return slides, None


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

def process_file(f: str, parser, dry_run: bool) -> tuple[list[dict], list[dict], dict]:
    """Process ONE course file -> (chunks, pages, inventory_entry).

    Extracted from ingest() so the app's document management (documents.py)
    can add a single uploaded file without re-processing the whole library.
    """
    ext = os.path.splitext(f)[1].lower()
    doc_id = slugify(os.path.relpath(f, MATERIALS_DIR))
    print(f"\n== {os.path.basename(f)}  ({ext})")
    entry = {"file": os.path.basename(f), "doc_id": doc_id, "format": ext,
             "pages": 0, "chunks": 0, "images": 0, "warning": None}
    chunks, pages = [], []
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
        parsed = parse_page_text(f, parser, dry_run) if not dry_run else ""
        pages.append({"doc_id": doc_id, "page": 1, "image_path": f})
        if parsed:
            chunks = chunk_texts([{"page": 1, "text": parsed}], doc_id, "image")
        entry["pages"] = 1
        entry["images"] = 1

    entry["chunks"] = len(chunks)
    print(f"  pages/sections: {entry['pages']}  chunks: {entry['chunks']}  images: {entry['images']}")
    return chunks, pages, entry


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
        try:
            chunks, page_list, entry = process_file(f, parser, dry_run)
            all_chunks.extend(chunks)
            pages.extend(page_list)
            inventory["files"].append(entry)
        except Exception as e:  # noqa: BLE001
            entry = {"file": os.path.basename(f),
                     "doc_id": slugify(os.path.relpath(f, materials_dir)),
                     "format": os.path.splitext(f)[1].lower(),
                     "error": str(e)[:200]}
            inventory["files"].append(entry)
            print(f"== {os.path.basename(f)} FAILED: {e}")

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
