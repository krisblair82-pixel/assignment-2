"""End-to-end ingestion contract tests using synthetic, non-course materials."""
import json
from pathlib import Path

import ingest


def test_synthetic_pptx_ingestion_preserves_slide_evidence_and_is_idempotent(
    monkeypatch, tmp_path
):
    materials = tmp_path / "materials"
    materials.mkdir()
    deck_path = materials / "synthetic.pptx"
    deck_path.write_bytes(b"synthetic placeholder")

    renders = tmp_path / "renders"
    index_dir = tmp_path / "index"
    results = tmp_path / "results"
    monkeypatch.setattr(ingest, "RENDERS_DIR", str(renders))
    monkeypatch.setattr(ingest, "INDEX_DIR", str(index_dir))
    monkeypatch.setattr(ingest, "RESULTS_DIR", str(results))

    image_paths = []

    def fake_render(path, out_dir):
        slides = []
        for number in (1, 2):
            image = Path(out_dir) / f"synthetic_p{number:03d}.png"
            image.parent.mkdir(parents=True, exist_ok=True)
            image.write_bytes(f"slide {number}".encode())
            image_paths.append(str(image))
            slides.append({
                "slide": number,
                "text": f"Synthetic slide {number}",
                "image_path": str(image),
            })
        return slides, None

    monkeypatch.setattr(ingest, "render_pptx_slides", fake_render)

    first = ingest.ingest(str(materials), dry_run=True)
    index_path = index_dir / "index.json"
    first_index = json.loads(index_path.read_text(encoding="utf-8"))

    second = ingest.ingest(str(materials), dry_run=True)
    second_index = json.loads(index_path.read_text(encoding="utf-8"))

    assert first["files"][0]["pages"] == 2
    assert first["files"][0]["chunks"] == 2
    assert first["files"][0]["images"] == 2
    assert second["files"][0]["pages"] == 2
    assert second["files"][0]["chunks"] == 2
    assert second["files"][0]["images"] == 2
    assert first_index == second_index

    assert len(first_index["chunks"]) == 2
    assert len(first_index["pages"]) == 2
    assert {chunk["slide"] for chunk in first_index["chunks"]} == {1, 2}
    assert all(chunk["doc_id"] == "synthetic.pptx" for chunk in first_index["chunks"])
    assert all(page["doc_id"] == "synthetic.pptx" for page in first_index["pages"])
    assert all(Path(page["image_path"]).is_file() for page in first_index["pages"])
    assert len(image_paths) == 4

    assert second["files"][0]["warning"] is None
