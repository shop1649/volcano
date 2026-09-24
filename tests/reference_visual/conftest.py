"""Fixtures for the reference-visual tests.

Every test that writes project files runs in a temporary project root (``shortkit.root`` marker
copied, ``SHORTKIT_ROOT`` set) holding a copy of the joshuamagazine preset.  Mock reference
videos are SYNTHETIC (see mockref.py) and cached under assets/test/generated/reference_visual/.
"""
from __future__ import annotations
import sys as _sys_for_helpers
from pathlib import Path as _Path_for_helpers
_HERE_FOR_HELPERS = str(_Path_for_helpers(__file__).resolve().parent)  # bare-name helper modules of this test dir
if _HERE_FOR_HELPERS not in _sys_for_helpers.path:
    _sys_for_helpers.path.insert(0, _HERE_FOR_HELPERS)

import shutil
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))

import mockref  # noqa: E402

GEN = REPO / "assets" / "test" / "generated"
MOCK_DIR = GEN / "reference_visual"
VIDEO_DIR = GEN / "video"


@pytest.fixture()
def proj(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    shutil.copy(REPO / "shortkit.root", root / "shortkit.root")
    pdir = root / "presets" / "joshuamagazine"
    pdir.mkdir(parents=True)
    shutil.copy(REPO / "presets" / "joshuamagazine" / "preset.yaml", pdir / "preset.yaml")
    (root / "warehouse").mkdir()
    monkeypatch.setenv("SHORTKIT_ROOT", str(root))
    monkeypatch.chdir(root)
    return root


@pytest.fixture(scope="session")
def mock_truth():
    if not (VIDEO_DIR / "classroom.mp4").is_file():
        pytest.skip("Intel sample clips missing: python -m shortkit testassets fetch-video --local-dir ...")
    t = mockref.build_mock(MOCK_DIR, VIDEO_DIR)
    return t, MOCK_DIR / "mockref_a.mp4"
