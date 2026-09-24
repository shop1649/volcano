"""Fixtures for shortkit.clean tests.

Every test runs against a temporary project root (``SHORTKIT_ROOT``) that holds copies of the
test media, so nothing is written into the real warehouse.  Expensive steps (detection, face
detection, the synthetic overlay clip) are computed once per session.
"""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

REAL_ROOT = Path(__file__).resolve().parents[2]
GEN = REAL_ROOT / "assets/test/generated"


def _need(p: Path) -> Path:
    if not p.is_file():
        pytest.skip(f"test media missing: {p.relative_to(REAL_ROOT)} (run `python -m shortkit testassets ...`)")
    return p


@pytest.fixture(scope="session")
def clean_root(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("cleanproj")
    shutil.copyfile(REAL_ROOT / "shortkit.root", root / "shortkit.root")
    (root / "presets/joshuamagazine").mkdir(parents=True)
    shutil.copyfile(REAL_ROOT / "presets/joshuamagazine/preset.yaml", root / "presets/joshuamagazine/preset.yaml")
    g = root / "assets/test/generated"
    (g / "video").mkdir(parents=True)
    for name in ("dirty_source.mp4", "dirty_source.truth.json"):
        if (GEN / name).is_file():
            shutil.copyfile(GEN / name, g / name)
    for name in ("classroom.mp4", "people-detection.mp4"):
        if (GEN / "video" / name).is_file():
            shutil.copyfile(GEN / "video" / name, g / "video" / name)
    casc = REAL_ROOT / "warehouse/cache/models/haarcascades"
    if casc.is_dir():
        shutil.copytree(casc, root / "warehouse/cache/models/haarcascades")
    return root


@pytest.fixture(autouse=True)
def _use_clean_root(clean_root, monkeypatch):
    monkeypatch.setenv("SHORTKIT_ROOT", str(clean_root))
    yield


@pytest.fixture(scope="session")
def env_root(clean_root):
    """Context manager factory for session-scoped fixtures that need SHORTKIT_ROOT."""
    def ctx():
        mp = pytest.MonkeyPatch.context()
        m = mp.__enter__()
        m.setenv("SHORTKIT_ROOT", str(clean_root))
        return mp
    return ctx


@pytest.fixture(scope="session")
def dirty(clean_root) -> Path:
    return _need(clean_root / "assets/test/generated/dirty_source.mp4")


@pytest.fixture(scope="session")
def truth(clean_root) -> dict:
    import json

    return json.loads(_need(clean_root / "assets/test/generated/dirty_source.truth.json").read_text())


@pytest.fixture(scope="session")
def dirty_doc(dirty, env_root) -> dict:
    from shortkit.clean.detect import detect_overlays

    mp = env_root()
    try:
        return detect_overlays(dirty)
    finally:
        mp.__exit__(None, None, None)


@pytest.fixture(scope="session")
def dirty_short(dirty, clean_root) -> Path:
    """First 8 s of the dirty source (stream copy: same pixels, same source times)."""
    from shortkit.util.media import ffmpeg

    out = clean_root / "assets/test/generated/dirty_first8.mp4"
    if not out.exists():
        ffmpeg(["-i", dirty, "-t", "8", "-c", "copy", out])
    return out


@pytest.fixture(scope="session")
def cascades_ok(env_root) -> bool:
    from shortkit.clean.faces import fetch_cascades, find_cascade

    mp = env_root()
    try:
        if find_cascade("frontal") is None:
            fetch_cascades()
        return find_cascade("frontal") is not None and find_cascade("profile") is not None
    finally:
        mp.__exit__(None, None, None)


@pytest.fixture(scope="session")
def dirty_faces(dirty, env_root, cascades_ok) -> dict:
    if not cascades_ok:
        pytest.skip("Haar cascade files unavailable (clean fetch-models failed)")
    from shortkit.clean.faces import detect_faces

    mp = env_root()
    try:
        return detect_faces(dirty, sample_fps=0.25, max_samples=5)
    finally:
        mp.__exit__(None, None, None)
