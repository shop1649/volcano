"""Fixtures for the reference-audio tests.

All media used here is SYNTHETIC (see synthref.py): known ground truth built from
assets/test/generated.  The ORACLE separator is a test double (demucs is not installed here).
Every test that writes files does so inside a temporary project root (SHORTKIT_ROOT).
"""
from __future__ import annotations
import sys as _sys_for_helpers
from pathlib import Path as _Path_for_helpers
_HERE_FOR_HELPERS = str(_Path_for_helpers(__file__).resolve().parent)  # bare-name helper modules of this test dir
if _HERE_FOR_HELPERS not in _sys_for_helpers.path:
    _sys_for_helpers.path.insert(0, _HERE_FOR_HELPERS)

import os
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[1]))

import synthref as S  # noqa: E402

PRESET = "joshuamagazine"


def _skip_if_no_assets():
    miss = S.require_assets()
    if miss:
        pytest.skip("test assets missing (run `python -m shortkit testassets synth`): " + ", ".join(miss))


@pytest.fixture(scope="session")
def synth_project(tmp_path_factory):
    """Temp project with a clean-music library, 4 synthetic reference videos, oracle stems and the
    full per-video analysis already run (bgm -> original -> sfx-events), plus synthetic visual
    analysis files for the catalog.  Returns a dict with root, truths and results."""
    _skip_if_no_assets()
    root = tmp_path_factory.mktemp("skproj")
    S.make_project(root)
    mp = pytest.MonkeyPatch()
    mp.setenv("SHORTKIT_ROOT", str(root))
    from shortkit.reference import audio_bgm, audio_original, separation, sfx_events
    from shortkit.util.jsonio import read_yaml, write_json, write_yaml

    lib = S.make_library(root)
    bank = S.sfx_bank()
    oracle = S.OracleSeparator()
    truths, results = {}, {}
    for spec in S.DEFAULT_SPECS:
        d = S.build(spec, lib, bank, root)
        vp = root / "presets" / PRESET / "reference" / "videos" / f"{spec.video_id}.wav"
        S._write(vp, d["mix"])
        oracle.add(vp, d)
        st = separation.separate_reference(PRESET, spec.video_id, separator=oracle)
        b = audio_bgm.analyze_bgm(PRESET, spec.video_id, stems=st)
        ctx = audio_original.load_context(PRESET, spec.video_id, stems=st)
        o = audio_original.analyze_original(PRESET, spec.video_id, ctx=ctx)
        e = sfx_events.analyze_sfx_events(PRESET, spec.video_id, ctx=ctx)
        truths[spec.video_id] = d["truth"] | {"format_id": spec.format_id}
        results[spec.video_id] = {"bgm": b, "original": o, "sfx": e}
    S.write_snapshot(root, [s.video_id for s in S.DEFAULT_SPECS])
    # formats + SYNTHETIC visual analysis files (captions/shots/motion) for the catalog
    fy = root / "presets" / PRESET / "formats.yaml"
    fd = read_yaml(fy, {}) or {}
    fd["assignments"] = {s.video_id: s.format_id for s in S.DEFAULT_SPECS}
    write_yaml(fy, fd)
    A = root / "presets" / PRESET / "analysis"
    res = [1080, 1920]
    write_json(A / "synv1/captions.json", {"video_id": "synv1", "resolution": res, "label": S.SYNTHETIC_LABEL, "items": [
        {"start": 1.95, "end": 3.0, "role": "situation", "text": "t", "bbox": [0, 0, 1, 1], "motion_in": "pop"},
        {"start": 7.5, "end": 8.5, "role": "reaction", "text": "t", "bbox": [0, 0, 1, 1], "motion_in": "none"}]})
    write_json(A / "synv1/shots.json", {"video_id": "synv1", "resolution": res, "fps": 30, "duration": 20,
                                         "label": S.SYNTHETIC_LABEL, "cuts": [{"t": 4.95, "type": "cut", "score": 1}]})
    write_json(A / "synv1/motion.json", {"video_id": "synv1", "resolution": res, "label": S.SYNTHETIC_LABEL,
                                          "events": [{"t": 8.05, "end": 8.4, "type": "zoom_in", "value": 1.2}]})
    write_json(A / "synv2/captions.json", {"video_id": "synv2", "resolution": res, "label": S.SYNTHETIC_LABEL, "items": [
        {"start": 2.95, "end": 4.0, "role": "situation", "text": "t", "bbox": [0, 0, 1, 1], "motion_in": "pop"},
        {"start": 12.0, "end": 13.0, "role": "reaction", "text": "t", "bbox": [0, 0, 1, 1], "motion_in": "none"}]})
    write_json(A / "synv2/motion.json", {"video_id": "synv2", "resolution": res, "label": S.SYNTHETIC_LABEL,
                                          "events": [{"t": 12.55, "end": 13.0, "type": "zoom_in", "value": 1.2}]})
    write_json(A / "synv3/captions.json", {"video_id": "synv3", "resolution": res, "label": S.SYNTHETIC_LABEL, "items": [
        {"start": 1.45, "end": 2.5, "role": "situation", "text": "t", "bbox": [0, 0, 1, 1], "motion_in": "pop"}]})
    # restore SHORTKIT_ROOT before handing the project out: tests get it per test through ``project_env``;
    # left set for the whole session it pointed every LATER test directory (tests/typography looks fonts up
    # under the project root) at this temp project -> 'font not found' when the suites run together
    mp.undo()
    yield {"root": root, "lib": lib, "bank": bank, "oracle": oracle, "truths": truths, "results": results}


@pytest.fixture
def project_env(synth_project, monkeypatch):
    """Per-test: make sure SHORTKIT_ROOT points at the synthetic project."""
    monkeypatch.setenv("SHORTKIT_ROOT", str(synth_project["root"]))
    return synth_project


@pytest.fixture
def tmp_project(tmp_path, monkeypatch):
    """A fresh empty temp project (marker + preset copy)."""
    _skip_if_no_assets()
    S.make_project(tmp_path)
    monkeypatch.setenv("SHORTKIT_ROOT", str(tmp_path))
    return tmp_path


def no_abs_paths(obj, root: Path) -> list[str]:
    """Strings inside a stored json/yaml object that look like absolute paths."""
    bad = []

    def walk(o):
        if isinstance(o, dict):
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
        elif isinstance(o, str):
            if o.startswith("/") or str(root) in o or os.path.expanduser("~") in o:
                bad.append(o)

    walk(obj)
    return bad
