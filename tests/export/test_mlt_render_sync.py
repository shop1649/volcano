"""Slow: melt render of an exported MLT vs an INDEPENDENT reference master (export_fixtures.render_master)
for the renderer features added after the first exporter version:

  * Zoom.recenter (cover clamp engaging mid-zoom -> per-frame affine keyframes)
  * flash Transition.scope = 'canvas' (the whole frame flashes, not only the video region)
  * read_audio channel convention: mono SFX / speech are at unity on both channels in the master;
    melt upmixes mono at -3.01 dB, compensated in the export (per-second level diff <= 1 dB)

Negative controls: the same IR exported WITHOUT recenter must fail the per-second video check where
the zoom is held, and a region-scope flash leaves the top of the frame black at the flash peak.
"""
from __future__ import annotations

import copy
import shutil

import numpy as np
import pytest

import export_fixtures as ef
from shortkit.edit import verify_project

pytestmark = [pytest.mark.slow,
              pytest.mark.skipif(verify_project.find_melt() is None, reason="melt not installed")]

EID = "test-export-sync"


def _ir():
    r = ef.build_resolved(EID)
    for c in r.clips:
        if c.zoom:
            c.zoom.recenter = True
    r.clips[0].zoom.center_src = (1500.0, 300.0)          # far from the centre: cover clamp engages
    r.clips[1].transition_in.scope = "canvas"
    return r


@pytest.fixture(scope="module")
def sync_master(root_dir):
    import os

    old = os.environ.get("SHORTKIT_ROOT")
    os.environ["SHORTKIT_ROOT"] = str(root_dir)
    try:
        r = _ir()
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


def _frame(path, t, W=360):
    from shortkit.util.media import read_frames

    return read_frames(path, [t], width=W)[0].astype(np.float32)


def test_recenter_canvas_flash_mono_audio_match_master(root, sync_master):
    from shortkit.edit import export_mlt
    from shortkit.util.jsonio import read_json

    r = _ir()
    ef.write_ass(root, r)
    proj = root / "episodes" / EID / "project"
    shutil.rmtree(proj, ignore_errors=True)
    out, dec = export_mlt.export_with_decisions(r, proj)
    assert {z["clip"]: z["mode"] for z in dec["zoom_keyframes"]}["c1"] == "per_frame"
    assert dec["flashes"][0]["scope"] == "canvas"
    assert dec["foreground_limiter"]["status"] == "없음"
    v = verify_project.verify(r, sync_master["path"], out)
    assert v["status"] == "pass", (v.get("why"), v.get("global"))
    for row in v["rows"]:
        assert row["ssim_mean"] >= 0.95, row
        assert row["audio"] == "pass" and abs(row["level_diff_db"]) <= 1.0, row
    # flash peak at 2.0 s: the WHOLE frame is white in the master and in the melt render
    melt = root / read_json(proj / "verify.json")["melt"]["output"]
    top_master = _frame(sync_master["path"], 2.0)[:200].mean()
    top_melt = _frame(melt, 2.0)[:200].mean()
    assert top_master > 240 and top_melt > 240, (top_master, top_melt)


def test_negative_controls_recenter_off_and_region_flash(root, sync_master):
    from shortkit.edit import export_mlt
    from shortkit.util.jsonio import read_json

    r = copy.deepcopy(_ir())
    for c in r.clips:
        if c.zoom:
            c.zoom.recenter = False
    r.clips[1].transition_in.scope = "region"
    ef.write_ass(root, r)
    proj = root / "episodes" / EID / "project"
    shutil.rmtree(proj, ignore_errors=True)
    out, _ = export_mlt.export_with_decisions(r, proj)
    v = verify_project.verify(r, sync_master["path"], out)
    assert v["status"] == "fail"
    rows = {row["sec"]: row for row in v["rows"]}
    assert rows[1]["video"] == "fail"                       # 1.0-2.0 s: zoom held, recenter placement differs
    melt = root / read_json(proj / "verify.json")["melt"]["output"]
    assert _frame(melt, 2.0)[:200].mean() < 60             # region flash: background above the region stays dark
