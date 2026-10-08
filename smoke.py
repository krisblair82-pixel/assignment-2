"""Smoke test for the class service clients (services.py).

Runs real requests against 9001-9005 with a tiny synthetic page image
(no course materials needed). Results saved to results/smoke_*.json.
Usage: python smoke.py
"""
import json
import os
import time
import urllib.request  # used by synthetic-page helper

from config import RESULTS_DIR, ensure_configured
from services import Parser, TextEmbedder, VisualEmbedder, Reranker, ChatClient


def make_synthetic_page(path: str) -> None:
    """Render a 1-page PDF with text + a simple bar chart, then rasterize it."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 90), "MBAX 6418 Sample Chart Page", fontsize=18)
    page.insert_text((72, 130), "Quarterly sales grew 12% in Q3.", fontsize=12)
    bars = [(100, 300), (180, 400), (260, 350), (340, 450)]  # x, height
    page.draw_rect(fitz.Rect(80, 550, 140, 550 - 120), fill=(0.2, 0.4, 0.9))
    page.draw_rect(fitz.Rect(160, 550, 220, 550 - 160), fill=(0.2, 0.4, 0.9))
    page.draw_rect(fitz.Rect(240, 550, 300, 550 - 140), fill=(0.2, 0.4, 0.9))
    page.draw_rect(fitz.Rect(320, 550, 380, 550 - 180), fill=(0.2, 0.4, 0.9))
    pix = page.get_pixmap(dpi=150)   # rasterize, then save as PNG
    pix.save(path)
    doc.close()


def main() -> dict:
    ensure_configured()
    results = {"generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "checks": []}

    def check(name, fn):
        # every check runs under try/except so one dead service can't abort the run
        try:
            ok, detail = fn()
        except Exception as e:  # noqa: BLE001
            ok, detail = False, f"{type(e).__name__}: {e}"
        results["checks"].append({"name": name, "ok": bool(ok), "detail": str(detail)[:200]})
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}: {detail}")

    print("== 9002 text embeddings ==")
    te = TextEmbedder()

    def _text_embed():
        vecs = te.embed(["quarterly sales growth"])
        return len(vecs) == 1 and len(vecs[0]) == 2048, f"dim={len(vecs[0]) if vecs else 0}"
    check("text embed", _text_embed)

    print("== 9003 visual embeddings (text input) ==")
    ve = VisualEmbedder()

    def _vis_text_embed():
        vvecs = ve.embed(texts=["a bar chart of quarterly sales"])
        return len(vvecs) == 1 and len(vvecs[0]) == 2048, f"dim={len(vvecs[0]) if vvecs else 0}"
    check("visual embed (text)", _vis_text_embed)

    print("== 9004 multimodal rerank ==")
    rr = Reranker()

    def _rerank():
        ranked = rr.rerank("sales grew 12 percent in the third quarter", [
            {"text": "the company issued a press release"},
            {"text": "quarterly sales grew 12% in Q3, driven by the new product line"},
            {"text": "welcome to the course"},
        ])
        top_text = (ranked[0].get("document") or {}).get("text", "") if ranked else ""
        return bool(ranked) and "12%" in top_text, f"top={top_text[:60]}"
    check("rerank top-1 relevant", _rerank)

    print("== 9001 vision LLM ==")
    chat = ChatClient()

    def _chat():
        ans = chat.complete([{"role": "user", "content": "Reply with exactly: OK"}], max_tokens=64)
        return ans.strip() == "OK", repr(ans.strip()[:40])
    check("chat content", _chat)

    print("== 9005 document parsing (synthetic page) ==")
    png = os.path.join(RESULTS_DIR, "smoke_synthetic_page.png")
    make_synthetic_page(png)
    parser = Parser()

    def _parse():
        parsed = parser.parse_page(png)
        results["parsed_sample"] = parsed[:500]
        return len(parsed.strip()) > 10, f"{len(parsed)} chars"
    check("parse synthetic page", _parse)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    out = os.path.join(RESULTS_DIR, f"smoke_{time.strftime('%Y%m%d_%H%M%S')}.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=1)
    n_pass = sum(1 for c in results["checks"] if c["ok"])
    print(f"\n{n_pass}/{len(results['checks'])} checks passed -> {out}")
    return results


if __name__ == "__main__":
    main()
