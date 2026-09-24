"""pytest fixtures for sourcing tests (helpers live in sourcing_fixtures.py)."""
from __future__ import annotations
import sys as _sys_for_helpers
from pathlib import Path as _Path_for_helpers
_HERE_FOR_HELPERS = str(_Path_for_helpers(__file__).resolve().parent)  # bare-name helper modules of this test dir
if _HERE_FOR_HELPERS not in _sys_for_helpers.path:
    _sys_for_helpers.path.insert(0, _HERE_FOR_HELPERS)

import shutil
import subprocess

import pytest

from sourcing_fixtures import REPO, VIDEO, FakeNet, _cut


@pytest.fixture
def proj(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    shutil.copy(REPO / "shortkit.root", root / "shortkit.root")
    (root / "warehouse").mkdir()
    shutil.copy(REPO / "warehouse" / "queries.yaml", root / "warehouse" / "queries.yaml")
    monkeypatch.setenv("SHORTKIT_ROOT", str(root))
    return root


@pytest.fixture
def net(monkeypatch):
    from shortkit.sourcing import platforms

    fake = FakeNet()
    monkeypatch.setattr(platforms, "ytdlp_extract", fake.ytdlp_extract)
    monkeypatch.setattr(platforms, "http_get_json", fake.http_get_json)
    monkeypatch.setattr(platforms, "ytdlp_download", fake.ytdlp_download)
    return fake


@pytest.fixture(scope="session")
def tiny_clip(tmp_path_factory):
    """2-second 320x568 synthetic clip (ffmpeg testsrc2) for download bookkeeping tests."""
    out = tmp_path_factory.mktemp("clips") / "tiny.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x568:r=15:d=2",
                    "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(out)], check=True)
    return out


@pytest.fixture(scope="session")
def clips(tmp_path_factory):
    """Candidate clips derived from the CC-BY Intel sample videos (assets/test/generated/video)."""
    if not (VIDEO / "classroom.mp4").is_file():
        pytest.skip("test videos missing: run `python -m shortkit testassets fetch-video`")
    d = tmp_path_factory.mktemp("cands")
    return {
        # same recording as the "reference": trimmed, scaled down, re-encoded
        "class_reencode": _cut(VIDEO / "classroom.mp4", d / "class_reencode.mp4", 4, 8, "scale=640:-2"),
        # same recording reposted as a 9:16 Short: blurred background, mirrored foreground
        "class_vertical": _cut(VIDEO / "classroom.mp4", d / "class_vertical.mp4", 8, 6,
                               "[0:v]scale=540:960:force_original_aspect_ratio=increase,crop=540:960,boxblur=20[bg];"
                               "[0:v]scale=540:-2,hflip[fg];[bg][fg]overlay=0:(H-h)/2"),
        # a different recording
        "head_pose": _cut(VIDEO / "head-pose-face-detection-female-and-male.mp4", d / "head_pose.mp4", 5, 8,
                          "scale=640:-2"),
    }
