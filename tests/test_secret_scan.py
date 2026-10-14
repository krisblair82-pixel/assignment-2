"""Regression tests for the staged-file secret scanner."""
from __future__ import annotations

import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCANNER = ROOT / "scripts" / "scan_secrets.sh"


def _scan(path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(SCANNER), str(path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def test_secret_scanner_blocks_planted_github_token(tmp_path):
    planted = tmp_path / "planted.txt"
    planted.write_text("token=ghp_" + "A" * 24, encoding="utf-8")

    result = _scan(planted)

    assert result.returncode == 1
    assert "SECRET SCAN FAIL" in result.stderr


def test_secret_scanner_allows_non_secret_text(tmp_path):
    safe = tmp_path / "safe.txt"
    safe.write_text("This is ordinary evaluation evidence.\n", encoding="utf-8")

    result = _scan(safe)

    assert result.returncode == 0
    assert result.stderr == ""
