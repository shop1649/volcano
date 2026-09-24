"""Slow: export + melt-verify the pipeline test episode made by the edit/render modules
(episodes/test-pipeline-001: real resolve -> render.py master).  Skipped when it does not exist.
Writes only under episodes/test-export-pipeline/ (removed afterwards; the verify render goes to
its build/ folder, which is git-ignored and removed too)."""
from __future__ import annotations

import shutil

import pytest

from shortkit import paths
from shortkit.edit import verify_project

pytestmark = [pytest.mark.slow,
              pytest.mark.skipif(verify_project.find_melt() is None, reason="melt not installed")]


def test_pipeline_episode_project_matches_render_py_master(monkeypatch):
    from shortkit.edit import project_readme
    from shortkit.util.jsonio import read_json

    monkeypatch.delenv("SHORTKIT_ROOT", raising=False)
    root = paths.project_root()
    rj = root / "episodes/test-pipeline-001/build/resolved.json"
    if not rj.is_file():
        pytest.skip("episodes/test-pipeline-001 not built")
    r = project_readme.load_resolved("test-pipeline-001")
    if not paths.absp(r.output_path).is_file():
        pytest.skip("pipeline master MP4 not rendered")
    work = root / "episodes/test-export-pipeline"
    out_dir = work / "project"
    try:
        s = project_readme.export_project(r, out_dir=out_dir, verify=True)
        assert not s["errors"], s["errors"]
        v = read_json(out_dir / "verify.json")
        assert v["status"] == "pass", (v.get("why"), v.get("global"))
        assert all(row["ssim_mean"] >= 0.90 for row in v["rows"])
    finally:
        shutil.rmtree(work, ignore_errors=True)
