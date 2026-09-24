"""Fixtures for tests/export (helpers in export_fixtures.py).

A session-scoped temporary project root holds copies of the test media (assets/test/generated:
CC-BY Intel sample clips + synthetic audio); every test sets SHORTKIT_ROOT to it via monkeypatch.
The reference master is rendered once per session by the independent numpy+ffmpeg renderer in
export_fixtures.py (never by the exporter under test).
"""
from __future__ import annotations

import os
import shutil

import pytest

import export_fixtures as ef


@pytest.fixture(scope="session")
def root_dir(tmp_path_factory):
    if not ef.have_media():
        pytest.skip("test media missing: run `python -m shortkit testassets synth|fetch-video|dirty-source`")
    return ef.make_root(tmp_path_factory.mktemp("export_root"))


@pytest.fixture
def root(root_dir, monkeypatch):
    monkeypatch.setenv("SHORTKIT_ROOT", str(root_dir))
    return root_dir


@pytest.fixture
def resolved(root):
    r = ef.build_resolved()
    ef.write_ass(root, r)
    return r


@pytest.fixture
def fresh_project(root, resolved):
    """Empty project folder for the fixture episode (build/ keeps the ASS and render report)."""
    d = root / "episodes" / resolved.episode_id / "project"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    return d


@pytest.fixture(scope="session")
def master(root_dir):
    """Reference master MP4 + build/render_report.json for the fixture episode (rendered once)."""
    old = os.environ.get("SHORTKIT_ROOT")
    os.environ["SHORTKIT_ROOT"] = str(root_dir)
    try:
        r = ef.build_resolved()
        ef.write_ass(root_dir, r)
        out = root_dir / r.output_path
        loud = ef.render_master(root_dir, r, out)
        ef.write_render_report(root_dir, r, loud)
        return {"path": out, "loudness": loud}
    finally:
        if old is None:
            os.environ.pop("SHORTKIT_ROOT", None)
        else:
            os.environ["SHORTKIT_ROOT"] = old
