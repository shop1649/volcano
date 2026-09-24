"""Logo residual from overlay PROVENANCE, end to end on the synthetic dirty source.

assets/test/generated/dirty_source.mp4 (SYNTHETIC test media: fake '@fake_repost' watermark top-left
for the whole clip + burned-in English subtitle 'WAIT FOR IT...' at 2-6 s) is scanned by the real
`python -m shortkit clean plan --source ...` (detect -> faces -> plan) in a throw-away project root,
which writes warehouse/overlays/<sha256>.json.  Two tiny episodes are rendered by the production
renderer (shortkit.edit.resolve + shortkit.edit.render) from the SAME source segment:

  test-qa-prov-raw    no cleaning                 -> every recorded overlay 'different'
  test-qa-prov-clean  the `clean plan` clean block -> every recorded overlay 'same'

and QA looks for the recorded overlays in the final MP4 (clean.verify.residual_score with rects
mapped by clean.verify.source_rect_to_canvas).  The record's own unmeasured checks (text-free static
logo check in a single static shot) must reach the report as 못 잼.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

REAL_ROOT = Path(__file__).resolve().parents[2]
DIRTY = REAL_ROOT / "assets/test/generated/dirty_source.mp4"
CASC = REAL_ROOT / "warehouse/cache/models/haarcascades"


def _plan(ep: str, sha: str, clean: dict | None, protected: list | None) -> dict:
    src = {"id": "dirty", "path": "assets/test/generated/dirty_source.mp4", "sha256": sha, "warehouse_id": None,
           "has_embedded_music": True,
           "clean": clean or {"crop": None, "delogo": [], "inpaint": [], "blur": []}}
    if protected:
        src["protected"] = protected
    return {"schema": "shortkit.plan/1", "episode_id": ep, "preset_id": "joshuamagazine-v1",
            "format_id": "UNCLASSIFIED", "mode": "test",
            "notes": "SYNTHETIC provenance test episode (tests/qa/test_qa_provenance.py)",
            "sources": [src],
            # source 1.0-5.0 s: the watermark (whole clip) and the subtitle (2.0-6.03 s) are both on screen
            "timeline": [{"id": "s1", "source": "dirty", "src_in": 1.0, "src_out": 5.0}],
            "captions": [], "sfx": []}


@pytest.fixture(scope="module")
def prov_root(tmp_path_factory):
    if not DIRTY.is_file():
        pytest.skip("assets/test/generated/dirty_source.mp4 missing (python -m shortkit testassets dirty-source)")
    root = tmp_path_factory.mktemp("provproj")
    shutil.copy(REAL_ROOT / "shortkit.root", root / "shortkit.root")
    shutil.copytree(REAL_ROOT / "presets" / "joshuamagazine", root / "presets" / "joshuamagazine",
                    ignore=shutil.ignore_patterns("videos", "frames", "stems", "*.wav", "*.mp4", "analysis"))
    (root / "assets/test/generated").mkdir(parents=True)
    shutil.copy(DIRTY, root / "assets/test/generated/dirty_source.mp4")
    if CASC.is_dir():
        shutil.copytree(CASC, root / "warehouse/cache/models/haarcascades")
    mp = pytest.MonkeyPatch()
    mp.setenv("SHORTKIT_ROOT", str(root))
    env = dict(os.environ, SHORTKIT_ROOT=str(root), PYTHONPATH=str(REAL_ROOT), OMP_THREAD_LIMIT="1")
    r = subprocess.run([sys.executable, "-m", "shortkit", "clean", "plan", "--source",
                        "assets/test/generated/dirty_source.mp4"], cwd=root, env=env, capture_output=True, text=True,
                       timeout=1500)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
    from shortkit.util.hashing import sha256_file

    sha = sha256_file(root / "assets/test/generated/dirty_source.mp4")
    cplan = json.loads((root / f"warehouse/overlays/{sha}.plan.json").read_text())
    doc = json.loads((root / f"warehouse/overlays/{sha}.json").read_text())
    from shortkit.edit.render import render
    from shortkit.edit.resolve import resolve_episode
    from shortkit.qa.report import run_and_write
    from shortkit.util.jsonio import write_yaml

    reps = {}
    for ep, clean, prot in (("test-qa-prov-raw", None, None),
                            ("test-qa-prov-clean", cplan["clean"], cplan.get("protected"))):
        write_yaml(root / "episodes" / ep / "plan.yaml", _plan(ep, sha, clean, prot))
        render(resolve_episode(ep))
        reps[ep] = run_and_write(ep, only=["clean.residual"], recheck_others=False, quiet=True)
    yield {"root": root, "sha": sha, "doc": doc, "clean_plan": cplan, "stdout": r.stdout, "reps": reps}
    mp.undo()


def _prov_rows(rep, sha_src="dirty"):
    return [r for r in rep["rows"] if r["row_id"].startswith(f"clean.residual:prov:{sha_src}:")]


def test_clean_plan_recorded_both_overlays(prov_root):
    kinds = sorted(o["kind"] for o in prov_root["doc"]["overlays"])
    assert kinds == ["burned_subtitle", "watermark"], prov_root["doc"]["overlays"]
    assert "clean:" in prov_root["stdout"]


def test_uncleaned_render_leaves_every_recorded_overlay(prov_root):
    rows = [r for r in _prov_rows(prov_root["reps"]["test-qa-prov-raw"]) if "@" in r["row_id"]]
    ids = sorted(r["row_id"].split(":")[3].split("@")[0] for r in rows)
    assert ids == sorted(o["id"] for o in prov_root["doc"]["overlays"]), [r["row_id"] for r in rows]
    for r in rows:
        assert r["status"] == "different", (r["row_id"], r["observed"], r["note"])
        assert r["observed"]["how"] == "pixels" and r["observed"]["mapping"] == "clean.verify.source_rect_to_canvas"
        assert r["observed"]["resolution_out"] == [1080, 1920]
        assert r["expected"]["resolution_src"] == [1920, 1080]
        # the recorded times are inside the clip's use of the overlay's source range
        assert r["expected"]["src_range_used"][0] >= 1.0 and r["expected"]["src_range_used"][1] <= 5.0


def test_clean_block_render_leaves_nothing(prov_root):
    rows = [r for r in _prov_rows(prov_root["reps"]["test-qa-prov-clean"]) if "@" in r["row_id"]]
    assert len(rows) == len(prov_root["doc"]["overlays"])
    for r in rows:
        assert r["status"] == "same", (r["row_id"], r["observed"], r["note"])
    # the per-op check of the plan's own clean ops (inpaint) must compare against the ORIGINAL source,
    # not the inpainted intermediate the clip plays from (that comparison would always "find" it)
    ops = [r for r in prov_root["reps"]["test-qa-prov-clean"]["rows"] if r["row_id"].startswith("clean.residual:s1#")]
    assert ops and all(r["status"] == "same" for r in ops), [(r["row_id"], r["observed"]) for r in ops]
    hows = {r["row_id"].split(":")[3].split("@")[0]: r["observed"]["how"] for r in rows}
    cl = prov_root["clean_plan"]["clean"]
    for o in prov_root["doc"]["overlays"]:
        rr, c = o["rect"], cl.get("crop")
        outside = c and (rr["x"] + rr["w"] <= c["x"] or rr["y"] + rr["h"] <= c["y"] or
                         rr["x"] >= c["x"] + c["w"] or rr["y"] >= c["y"] + c["h"])
        assert hows[o["id"]] == ("removed_by_crop" if outside else "pixels"), (o, cl)


def test_record_unmeasured_checks_carried_as_mot_jaem(prov_root):
    doc = prov_root["doc"]
    sg = (doc.get("checks") or {}).get("static_graphics") or {}
    for ep in ("test-qa-prov-raw", "test-qa-prov-clean"):
        rows = {r["row_id"]: r for r in _prov_rows(prov_root["reps"][ep])}
        if sg.get("status") != "measured":
            r = rows["clean.residual:prov:dirty:static_graphics"]
            assert r["status"] == "unmeasured" and r["required"] is True
            assert "못 잼" in r["note"] or "구분할 수 없음" in r["note"]
        corner_rows = [k for k in rows if ":corner:" in k]
        um = [n for n, c in (doc.get("corners") or {}).items() if "unmeasured" in (c.get("text"), c.get("graphic"))]
        if ep == "test-qa-prov-raw":           # nothing cropped: every unmeasured corner is on screen
            assert sorted(k.split(":corner:")[1] for k in corner_rows) == sorted(um)
        assert all(rows[k]["status"] == "unmeasured" for k in corner_rows)
