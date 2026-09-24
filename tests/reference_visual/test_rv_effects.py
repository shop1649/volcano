"""Effect analyzers vs. SYNTHETIC mocks drawn with the production renderer's own conventions
(mockfx.py): zoom ease / recenter (resolve.src_to_region), flash scope (render.py flash overlay),
decorations (captions.decoration_events burned by libass).

Stated tolerances (540x960 @ 30 fps; px in that resolution):
  zoom: ease class exact; fitted start +-0.05 s, duration +-0.06 s, scale_to +-0.03; recenter class exact
  flash scope class exact
  decorations: kind exact; colour RGB distance <= 12; ring stroke +-1.0 px; arrow length +-3 %, ratios +-0.03,
  outline +-1.0 px; blink_hz +-3 %; start/end +-2 frames
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

import mockfx
from shortkit.reference import motion, shots
from shortkit.reference.common import color_dist

REPO = Path(__file__).resolve().parents[2]
GEN = REPO / "assets" / "test" / "generated" / "reference_visual" / "fx"


def test_ease_curve_is_the_renderer_ease():
    from shortkit.edit.resolve import ease
    u = np.linspace(-0.2, 1.2, 57)
    for kind in motion.EASES:
        assert np.allclose(motion.ease_curve(u, kind), [ease(float(x), kind) for x in u], atol=1e-12), kind


def test_fit_ease_recovers_each_curve_and_refuses_noise():
    fps = 30.0
    ts = np.arange(0, 1.6, 1 / fps)
    for kind in motion.EASES:
        z = 1.0 + 0.3 * motion.ease_curve((ts - 0.5) / 0.5, kind)
        f = motion.fit_ease(ts, z, fps, sign=1)
        assert f["ease"] == kind, (kind, f)
        assert f["t0"] == pytest.approx(0.5, abs=0.02) and f["dur_s"] == pytest.approx(0.5, abs=0.03)
        assert f["scale_to"] == pytest.approx(1.3, abs=0.005)
    rng = np.random.default_rng(1)
    f = motion.fit_ease(ts, 1.0 + 0.01 * rng.standard_normal(len(ts)), fps)
    assert f is None or f["ease"] is None


@pytest.mark.slow
@pytest.mark.parametrize("ease", ["linear", "in", "out", "inout"])
@pytest.mark.parametrize("recenter", [False, True])
def test_zoom_ease_and_recenter_on_renderer_mock(ease, recenter, tmp_path):
    mp4, truth = mockfx.build_zoom_mock(GEN / f"zoom_{ease}_{int(recenter)}.mp4", ease, recenter)
    res = motion.analyze(mp4, "fxzoom", region={"video_region": truth["region"]}, out_dir=tmp_path, shots={},
                         captions={}, decorations=False)
    z = [e for e in res["events"] if e["type"] == "zoom_in"]
    assert len(z) == 1, res["events"]
    fit = z[0]["ease_fit"]
    assert fit["ease"] == ease, fit
    assert fit["t0"] == pytest.approx(truth["start"], abs=0.05)
    assert fit["dur_s"] == pytest.approx(truth["dur"], abs=0.06)
    assert fit["scale_to"] == pytest.approx(truth["scale_to"], abs=0.03)
    rc = z[0]["recenter_fit"]
    assert rc["recenter"] is recenter and rc["class"] == ("moves" if recenter else "stays"), rc
    if not recenter:
        # renderer recenter=false: the zoom centre stays where the target is (source x 336 -> region x 126)
        assert rc["fixed_point"][0] == pytest.approx(126, abs=20) and rc["fixed_point"][1] == pytest.approx(480, abs=20)


@pytest.mark.slow
def test_zoom_about_the_centre_is_not_an_observation(tmp_path):
    mp4, truth = mockfx.build_zoom_mock(GEN / "zoom_centre.mp4", "out", True, center_src=(480.0, 270.0))
    res = motion.analyze(mp4, "fxzoomc", region={"video_region": truth["region"]}, out_dir=tmp_path, shots={},
                         captions={}, decorations=False)
    z = [e for e in res["events"] if e["type"] == "zoom_in"]
    assert len(z) == 1 and z[0]["recenter_fit"]["class"] == "centre" and z[0]["recenter_fit"]["recenter"] is None


@pytest.mark.slow
@pytest.mark.parametrize("scope", ["region", "canvas"])
def test_flash_scope_on_renderer_mock(scope, tmp_path):
    mp4, truth = mockfx.build_flash_mock(GEN / f"flash_{scope}.mp4", scope)
    res = shots.analyze(mp4, "fxflash", region={"video_region": truth["region"]}, out_dir=tmp_path)
    fl = [c for c in res["cuts"] if c["type"] == "flash"]
    assert len(fl) == 1, res["cuts"]
    assert fl[0]["scope"]["value"] == scope, fl[0]["scope"]


@pytest.mark.slow
def test_flash_scope_full_frame_footage_is_unmeasured(tmp_path):
    mp4, truth = mockfx.build_flash_mock(GEN / "flash_canvas.mp4", "canvas")
    res = shots.analyze(mp4, "fxflash", region={"video_region": None}, out_dir=tmp_path)
    fl = [c for c in res["cuts"] if c["type"] == "flash"]
    assert fl and fl[0]["scope"]["value"] is None and fl[0]["scope"]["note"]


def test_blink_from_presence():
    fps = 30.0
    on = ([True] * 5 + [False] * 5) * 6 + [True] * 5              # 3 Hz, 50 % duty
    b = motion.blink_from_presence(on, fps)
    assert b["blink_hz"] == pytest.approx(3.0, rel=0.01) and b["duty"] == pytest.approx(0.5, abs=0.01)
    steady = [True] * 40
    steady[20] = False                                             # a 1-frame dropout is noise, not a blink
    assert motion.blink_from_presence(steady, fps)["blink_hz"] == 0.0


DECOS = [
    {"kind": "arrow", "start": 0.5, "end": 2.5, "keyframes": [{"t": 0.5, "x": 150, "y": 420, "rotation": 0}],
     "blink_hz": 0.0, "style": {"color": "#FF2A2A", "size_px": 90, "outline_px": 4, "outline_color": "#FFFFFF",
                                "head_len_ratio": 0.45, "head_width_ratio": 0.62, "shaft_width_ratio": 0.24}},
    {"kind": "circle", "start": 1.0, "end": 3.5, "keyframes": [{"t": 1.0, "x": 380, "y": 450, "w": 120, "h": 100}],
     "blink_hz": 2.0, "style": {"color": "#FFE400", "stroke_px": 6}},
    {"kind": "box", "start": 0.3, "end": 3.0, "keyframes": [{"t": 0.3, "x": 270, "y": 800, "w": 200, "h": 110}],
     "blink_hz": 0.0, "style": {"color": "#2AFF5A", "stroke_px": 8}},
]
DECOS2 = [
    {"kind": "arrow", "start": 0.4, "end": 3.0, "keyframes": [{"t": 0.4, "x": 300, "y": 450, "rotation": 135}],
     "blink_hz": 3.0, "style": {"color": "#FF2A2A", "size_px": 110, "outline_px": 0, "outline_color": "#FFFFFF",
                                "head_len_ratio": 0.4, "head_width_ratio": 0.7, "shaft_width_ratio": 0.2}},
    {"kind": "arrow", "start": 0.5, "end": 3.5,
     "keyframes": [{"t": 0.5, "x": 100, "y": 780, "rotation": 270}, {"t": 3.5, "x": 160, "y": 800, "rotation": 270}],
     "blink_hz": 0.0, "style": {"color": "#FFE400", "size_px": 80, "outline_px": 3, "outline_color": "#000000",
                                "head_len_ratio": 0.45, "head_width_ratio": 0.62, "shaft_width_ratio": 0.24}},
    {"kind": "box", "start": 1.0, "end": 3.8, "keyframes": [{"t": 1.0, "x": 400, "y": 700, "w": 150, "h": 120}],
     "blink_hz": 1.5, "style": {"color": "#FF2A2A", "stroke_px": 10}},
]


def _check(found: dict, truth: dict):
    st = truth["style"]
    assert found["kind"] == truth["kind"]
    assert color_dist(found["color"], st["color"]) <= 12, (found["color"], st["color"])
    assert found["blink_hz"] == pytest.approx(truth["blink_hz"], rel=0.03, abs=0.01), found
    assert found["t"] == pytest.approx(truth["start"], abs=2 / 30)
    if truth["kind"] in ("circle", "box"):
        assert found["stroke_px"] == pytest.approx(st["stroke_px"], abs=1.0), found
        kf = truth["keyframes"][0]
        assert found["outer_size"][0] == pytest.approx(max(kf["w"], kf["h"]), abs=3)
        assert found["outer_size"][1] == pytest.approx(min(kf["w"], kf["h"]), abs=3)
    else:
        assert found["size_px"] == pytest.approx(st["size_px"], rel=0.03), found
        for k in ("head_len_ratio", "head_width_ratio", "shaft_width_ratio"):
            assert found[k] == pytest.approx(st[k], abs=0.03), (k, found)
        if st["outline_px"]:
            assert found["outline_px"] == pytest.approx(st["outline_px"], abs=1.0), found
            assert color_dist(found["outline_color"], st["outline_color"]) <= 20
        else:
            assert found["outline_px"] == 0.0
        rot = truth["keyframes"][0]["rotation"]
        assert min(abs(found["rotation_deg"] - rot), 360 - abs(found["rotation_deg"] - rot)) <= 3


@pytest.mark.slow
@pytest.mark.parametrize("name,decos", [("deco_a", DECOS), ("deco_b", DECOS2)])
def test_decorations_on_renderer_mock(name, decos, tmp_path):
    mp4 = mockfx.build_decoration_mock(GEN / f"{name}.mp4", decos, total=4.0, tmp=tmp_path)
    r = motion.detect_decorations(mp4)
    assert r["resolution"] == [540, 960] and r["status"] == "experimental"
    items = r["items"]
    assert len(items) == len(decos), items
    for d in decos:
        same = [it for it in items if it["kind"] == d["kind"]]
        assert same, (d["kind"], items)
        _check(min(same, key=lambda it: color_dist(it["color"], d["style"]["color"])), d)


@pytest.mark.slow
def test_no_decorations_on_footage_without_them(tmp_path):
    base = mockfx.write_video(tmp_path / "plain.mp4", mockfx.footage_frames(3.0))
    assert motion.detect_decorations(base)["items"] == []
    mock = REPO / "assets/test/generated/reference_visual/mockref_a.mp4"
    tj = mock.with_name("mockref_a.truth.json")
    if mock.is_file() and tj.is_file():   # captions (yellow dialogue, cyan reaction) must not become decorations
        import json
        truth = json.loads(tj.read_text("utf-8"))
        caps = {"items": [{"bbox": e["bbox"], "start": e["start"], "end": e["end"], "style": {}}
                          for e in truth["events"]]}
        assert motion.detect_decorations(mock, captions=caps)["items"] == []
