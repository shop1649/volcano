"""Session setup shared by every test area.

Many tests use the generated test media in assets/test/generated/.  In a freshly restored preset that folder does
not exist yet, so the session creates what it can (all synthetic assets need no network) and, if the CC-BY sample
clips cannot be fetched, skips the tests that need them with a clear reason instead of crashing.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
GEN = ROOT / "assets" / "test" / "generated"
VIDEO_MARKERS = ("assets/test/generated/video", "classroom", "head-pose", "people-detection", "face-demographics",
                 "dirty_source", "classroom_voice")
_STATE: dict[str, str | None] = {"videos_missing": None}


def _run(*args: str) -> bool:
    env = dict(os.environ)
    env.setdefault("OMP_THREAD_LIMIT", "1")
    r = subprocess.run([sys.executable, "-m", "shortkit", *args], cwd=ROOT, env=env, capture_output=True, text=True)
    return r.returncode == 0


def pytest_sessionstart(session):
    if os.environ.get("SHORTKIT_TEST_NO_AUTOGEN"):
        return
    if not (GEN / "manifest.json").exists() or not (GEN / "sfx").is_dir():
        _run("testassets", "synth")
    videos = GEN / "video"
    if not (videos.is_dir() and any(videos.glob("*.mp4"))):
        local = os.environ.get("SHORTKIT_TESTVIDEO_DIR")
        _run("testassets", "fetch-video", *(["--local-dir", local] if local else []))
    if videos.is_dir() and any(videos.glob("*.mp4")):
        if not (GEN / "classroom_voice.mp4").exists():
            _run("episode", "test-source")
        if not (GEN / "dirty_source.mp4").exists():
            _run("testassets", "dirty-source")
    else:
        _STATE["videos_missing"] = ("CC-BY 테스트 영상을 받지 못함(네트워크/LFS). `python -m shortkit testassets fetch-video "
                                    "--local-dir <intel sample-videos 폴더>` 또는 SHORTKIT_TESTVIDEO_DIR 지정 후 다시 실행")


def pytest_collection_modifyitems(config, items):
    reason = _STATE.get("videos_missing")
    if not reason:
        return
    cache: dict[str, bool] = {}
    for it in items:
        f = str(it.fspath)
        if f not in cache:
            try:
                src = Path(f).read_text(encoding="utf-8")
            except OSError:
                src = ""
            cache[f] = any(m in src for m in VIDEO_MARKERS)
        if cache[f]:
            it.add_marker(pytest.mark.skip(reason=reason))
