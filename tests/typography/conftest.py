"""Fixtures for the typography (font identification) tests.

All caption images in these tests are SYNTHETIC: rendered here from the manifest's OFL fonts
and degraded with the same ffmpeg pipeline the ceiling uses.  No reference-channel pixels.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]


def _manifest_ready() -> list[str]:
    from shortkit import fonts

    missing = []
    for e in fonts.manifest_entries("acquirable"):
        p, state = fonts._manifest_file_state(e)
        if state != "ok":
            missing.append(e["name"])
    return missing


@pytest.fixture(scope="session")
def fonts_ready():
    """Manifest fonts present in assets/fonts (sha256-verified); fetch them if needed."""
    from shortkit import fonts

    missing = _manifest_ready()
    if missing:
        fonts.fetch_all(local_dir=os.environ.get("SHORTKIT_FONT_CACHE"), names=missing)
        missing = _manifest_ready()
    if missing:
        pytest.skip(f"manifest fonts unavailable (network?): {missing}")
    return True


@pytest.fixture
def tmp_root(tmp_path, monkeypatch, fonts_ready):
    """Temporary project root: preset + font manifest + copies of the verified font files."""
    from shortkit import fonts

    root = tmp_path / "proj"
    (root / "presets" / "joshuamagazine").mkdir(parents=True)
    (root / "assets" / "fonts").mkdir(parents=True)
    shutil.copy(REPO / "shortkit.root", root / "shortkit.root")
    shutil.copy(REPO / "presets" / "joshuamagazine" / "preset.yaml", root / "presets" / "joshuamagazine" / "preset.yaml")
    shutil.copy(REPO / "assets" / "fonts" / "manifest.yaml", root / "assets" / "fonts" / "manifest.yaml")
    for f in (REPO / "assets" / "fonts").iterdir():
        if f.suffix.lower() in (".ttf", ".otf", ".ttc"):
            shutil.copy(f, root / "assets" / "fonts" / f.name)
    monkeypatch.setenv("SHORTKIT_ROOT", str(root))
    fonts.clear_caches()
    yield root
    fonts.clear_caches()
