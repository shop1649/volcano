"""Visual analyzers vs. a SYNTHETIC mock reference with known ground truth (mockref.py).

Stated tolerances (mock is 540x960 @ 30 fps; px are in that resolution):
  video region edges ±4 px; background color RGB distance ≤ 20
  text bbox edges ±3 px; size (libass Fontsize and em px) ±8 %; fill color RGB distance ≤ 25; highlight ≤ 40
  outline_px ±1.0 px; box alpha ±0.1, box pad ±3 px
  appear / disappear time ±0.07 s (2 frames); motion_in/out duration ±0.05 s; pop scale_from ±0.06
  (reaction: ±0.1 because the first 1/30 s frame is already part-way through a 0.1 s pop)
  line_spacing ±0.06; OCR text similarity ≥ 0.6 (difflib ratio on Hangul jamo (NFD), spaces ignored:
  one wrong vowel in a one-syllable reaction must not count as a totally different text)
  cut time ±0.05 s; flash inside its truth window; crossfade start ±0.1 s, duration ±0.1 s
  zoom start/end ±0.07 s, scale ±0.05; freeze start ±0.1 s, hold ±0.1 s; speed start ±0.1 s, factor ±0.1
"""
from __future__ import annotations

import difflib
import json
import unicodedata

import numpy as np
import pytest

from shortkit.reference.common import color_dist, detect_video_region

pytestmark = pytest.mark.slow


@pytest.fixture(scope="module")
def analyzed(mock_truth, tmp_path_factory):
    """Run `shortkit ref analyze` once on the mock inside a temporary project root."""
    import os
    import shutil
    from pathlib import Path

    truth, mp4 = mock_truth
    repo = Path(__file__).resolve().parents[2]
    root = tmp_path_factory.mktemp("proj_an")
    shutil.copy(repo / "shortkit.root", root / "shortkit.root")
    (root / "presets/joshuamagazine").mkdir(parents=True)
    shutil.copy(repo / "presets/joshuamagazine/preset.yaml", root / "presets/joshuamagazine/preset.yaml")
    old = os.environ.get("SHORTKIT_ROOT")
    os.environ["SHORTKIT_ROOT"] = str(root)
    try:
        from shortkit.cli import main
        rc = main(["ref", "analyze", "--video", str(mp4), "--id", "mockref_a"])
        assert rc == 0
        adir = root / "presets/joshuamagazine/analysis/mockref_a"
        out = {n: json.loads((adir / f"{n}.json").read_text("utf-8")) for n in ("captions", "layout", "shots", "motion")}
        out["root"] = root
        yield truth, out
    finally:
        if old is None:
            os.environ.pop("SHORTKIT_ROOT", None)
        else:
            os.environ["SHORTKIT_ROOT"] = old


def _iou(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0, min(ay + ah, by + bh) - max(ay, by))
    u = aw * ah + bw * bh - ix * iy
    return ix * iy / u if u else 0


def _match(items, ev):
    cands = [(it, _iou(it["bbox"], ev["bbox"])) for it in items
             if min(it["end"], ev["end"]) - max(it["start"], ev["start"]) > 0.2]
    it, iou = max(cands, key=lambda c: c[1])
    assert iou > 0.5, (ev["id"], iou)
    return it


def test_layout_region_and_background(analyzed):
    truth, out = analyzed
    lay = out["layout"]
    assert lay["resolution"] == truth["resolution"]
    for k in ("x", "y", "w", "h"):
        assert abs(lay["video_region"][k] - truth["video_region"][k]) <= 4, k
    assert lay["background"] == "color"
    assert color_dist(lay["background_color"], truth["background"]["color"]) <= 20


def test_caption_items_roles_geometry_style(analyzed):
    truth, out = analyzed
    items = out["captions"]["items"]
    assert out["captions"]["resolution"] == [540, 960]
    matched = set()
    for ev in truth["events"]:
        it = _match(items, ev)
        matched.add(it["id"])
        st = it["style"]
        assert it["role"] == ev["role"], (ev["id"], it["role"], it["role_reason"])
        x, y, w, h = it["bbox"]
        tx, ty, tw, th = ev["bbox"]
        assert abs(x - tx) <= 3 and abs(y - ty) <= 3 and abs(x + w - tx - tw) <= 3 and abs(y + h - ty - th) <= 3, \
            (ev["id"], it["bbox"], ev["bbox"])
        # mock "size" is the libass Fontsize; preset size_px is the em size (renderer convention)
        assert st["ass_fontsize"] == pytest.approx(ev["size"], rel=0.08), ev["id"]
        fpe = st["size_calibration"]["fontsize_per_em"]
        assert st["size_px"] == pytest.approx(ev["size"] / fpe, rel=0.08), ev["id"]
        assert color_dist(st["color"], ev["color"]) <= 25, (ev["id"], st["color"])
        if ev["highlight"]:
            assert st["highlight_color"] and color_dist(st["highlight_color"], ev["highlight"]) <= 40
        else:
            assert st["highlight_color"] is None, ev["id"]
        if ev["outline"] is not None:
            assert st["outline_visibility"] == "visible"
            assert st["outline_px"] == pytest.approx(ev["outline"], abs=1.0), ev["id"]
        else:
            assert st["outline_px"] is None and st["outline_visibility"] == "indistinguishable"
        if ev["box"]:
            b = st["box"]
            assert b["present"] == "present"
            assert b["alpha"] == pytest.approx(ev["box_alpha"], abs=0.1)
            assert color_dist(b["color"], ev["box_color"]) <= 40
            assert abs(b["pad_x"] - ev["pad_x"]) <= 3 and abs(b["pad_y"] - ev["pad_y"]) <= 3
        else:
            assert st["box"]["present"] == "absent", ev["id"]
        a = unicodedata.normalize("NFD", "".join(it["text"].split()))
        b = unicodedata.normalize("NFD", "".join(ev["plain"].split()))
        assert difflib.SequenceMatcher(None, a, b).ratio() >= 0.6, (it["text"], ev["plain"])
        if ev.get("lines"):
            assert st["n_lines"] == ev["lines"]
            if ev.get("line_pitch"):
                assert st["line_spacing"] == pytest.approx(ev["line_pitch"] / (ev["size"] / fpe), abs=0.09)
    # nothing else was reported as a caption (footage texture was rejected)
    assert len(matched) == len(items), [i["text"] for i in items if i["id"] not in matched]


def test_caption_timing_and_motion(analyzed):
    truth, out = analyzed
    items = out["captions"]["items"]
    for ev in truth["events"]:
        it = _match(items, ev)
        assert it["start"] == pytest.approx(ev["start"], abs=0.07), ev["id"]
        assert it["end"] == pytest.approx(ev["end"], abs=0.07), ev["id"]
        mi = it["style"]["motion_in"]
        if ev["start"] == 0.0:
            assert it["motion_in"] == "unmeasured"      # already on screen at frame 0: not observable
            continue
        assert it["motion_in"] == ev["motion_in"], (ev["id"], mi)
        if ev["motion_in"] in ("pop", "fade"):
            assert mi["dur_s"] == pytest.approx(ev["motion_dur"], abs=0.05), (ev["id"], mi)
        if ev["motion_in"] == "pop":
            tol = 0.1 if ev["scale_from"] > 1 else 0.06
            assert mi["scale_from"] == pytest.approx(ev["scale_from"], abs=tol), (ev["id"], mi)
        # the mock only fades the speaker label out; everything else disappears at once
        exp_out = "fade" if ev["role"] == "speaker" else ("unmeasured" if ev["end"] >= 9.0 else "none")
        assert it["motion_out"] == exp_out, (ev["id"], it["style"]["motion_out"])


def test_layout_roles_summary(analyzed):
    truth, out = analyzed
    roles = out["layout"]["roles"]
    assert set(roles) == {"title", "description", "situation", "speaker", "dialogue", "reaction"}
    assert roles["title"]["persist"] == "whole_video"
    assert roles["situation"]["persist"] == "timed"
    assert roles["situation"]["motion_in"]["type"] == "pop"
    assert roles["situation"]["max_lines"] == 2
    assert roles["situation"]["align"] == "center"
    assert roles["situation"]["valign"] == "middle"      # libass \an5: the block grows both ways
    assert roles["speaker"]["box"]["present"] == "present"
    assert roles["title"]["highlight_presence"] == "present"
    assert out["captions"]["presence"]["reaction"] == "present"


def test_shots(analyzed):
    truth, out = analyzed
    cuts = out["shots"]["cuts"]
    assert [c["type"] for c in cuts] == ["cut", "flash", "crossfade"], cuts
    assert cuts[0]["t"] == pytest.approx(3.0, abs=0.05)
    lo, hi = truth["cuts"][1]["window"]
    assert lo <= cuts[1]["t"] <= hi and cuts[1]["t"] + cuts[1]["dur"] <= hi + 0.05
    assert cuts[2]["t"] == pytest.approx(6.8, abs=0.1) and cuts[2]["dur"] == pytest.approx(0.4, abs=0.1)
    assert out["shots"]["presence"] == {"cut": "present", "flash": "present", "crossfade": "present"}


def test_motion(analyzed):
    truth, out = analyzed
    ev = out["motion"]["events"]
    z = [e for e in ev if e["type"].startswith("zoom")]
    f = [e for e in ev if e["type"] == "freeze"]
    s = [e for e in ev if e["type"] == "speed"]
    assert len(z) == 1 and z[0]["type"] == "zoom_in"
    assert z[0]["t"] == pytest.approx(1.0, abs=0.07) and z[0]["end"] == pytest.approx(1.5, abs=0.07)
    assert z[0]["scale_to"] == pytest.approx(1.3, abs=0.05)
    assert len(f) == 1 and f[0]["t"] == pytest.approx(4.0, abs=0.1) and f[0]["hold_s"] == pytest.approx(0.6, abs=0.1)
    assert len(s) == 1 and s[0]["t"] == pytest.approx(8.0, abs=0.1) and s[0]["factor"] == pytest.approx(0.5, abs=0.1)
    assert out["motion"]["presence"] == {"zoom": "present", "freeze": "present", "speed": "present",
                                         "flash": "present"}
    # the mock zoom is zoompan's linear ramp about the frame centre: ease = linear; a zoom about the
    # centre looks the same with and without recenter -> no recenter observation
    fit = z[0]["ease_fit"]
    assert fit["ease"] == "linear" and fit["dur_s"] == pytest.approx(0.5, abs=0.07), fit
    assert z[0]["recenter_fit"]["class"] == "centre" and z[0]["recenter_fit"]["recenter"] is None
    # the mock's white flash (ffmpeg fade inside the footage band) covers the video region only
    fl = [e for e in ev if e["type"] == "flash"]
    assert len(fl) == 1 and fl[0]["scope"] == "region"
    assert out["shots"]["cuts"][1]["scope"]["value"] == "region"
    # no arrow / circle / box in the mock (yellow dialogue and cyan reaction captions are masked)
    assert out["motion"]["decorations"]["items"] == [], out["motion"]["decorations"]


def test_aggregate_single_mock_video_scaled_to_canvas(analyzed, monkeypatch):
    truth, out = analyzed
    monkeypatch.setenv("SHORTKIT_ROOT", str(out["root"]))
    from shortkit.reference.aggregate import aggregate
    r = aggregate("joshuamagazine")
    assert r["videos"] == 1
    items = {}
    for f in (out["root"] / "presets/joshuamagazine/measurements").glob("visual_*.json"):
        d = json.loads(f.read_text("utf-8"))
        assert d["schema"] == "shortkit.measurement/1"
        for it in d["items"]:
            items[it["key"]] = it
    t = items["text.roles.title.size_px"]
    assert t["status"] == "measured" and t["resolution"] == [1080, 1920]
    # Fontsize 40 at 540x960 -> x2 = Fontsize 80 -> em px = 80 / (winAscent+winDescent)/unitsPerEm
    from shortkit.edit.captions import resolve_font as _rf
    fpe = _rf("Noto Sans CJK KR Black").face.win_sum / _rf("Noto Sans CJK KR Black").face.units_per_em
    assert t["value"] == pytest.approx(80 / fpe, rel=0.08)
    assert items["canvas.video_region.y"]["value"] == pytest.approx(600, abs=8)
    assert items["canvas.background.type"]["value"] == "color"
    assert items["motion.zoom.scale_to"]["value"] == pytest.approx(1.3, abs=0.05)
    assert items["motion.freeze.hold_s"]["value"] == pytest.approx(0.6, abs=0.1)
    assert items["text.roles.speaker.box.alpha"]["value"] == pytest.approx(0.6, abs=0.1)
    assert items["text.roles.situation.motion_in.type"]["value"] == "pop"
    # no format labels -> no by_format split, and unmeasurable keys say why
    assert items["text.roles.situation.size_px"]["by_format"] == {}
    assert items["canvas.video_region.fit"]["status"] == "unmeasured" and items["canvas.video_region.fit"]["blocker"]
    assert items["text.roles.situation.timing.lead_s"]["status"] == "unmeasured"
    # emitters added for keys that had no measurement path
    assert items["motion.zoom.ease"]["value"] == "linear"
    assert items["motion.zoom.recenter"]["status"] == "unmeasured"          # centre zoom: no observation
    assert items["motion.transitions.flash.scope"]["value"] == "region"
    assert items["text.roles.dialogue.quote_marks"]["value"] == ["“", "”"]
    sm = items["canvas.safe_margin.left"]
    assert sm["status"] == "measured" and sm["resolution"] == [1080, 1920]
    # leftmost caption ink in the mock: the situation line (x=175 at 540 wide) -> 350 at 1080
    left_truth = min(e["bbox"][0] for e in truth["events"])
    assert sm["value"] == pytest.approx(2 * left_truth, abs=8)
    top_truth = min(e["bbox"][1] for e in truth["events"])
    assert items["canvas.safe_margin.top"]["value"] == pytest.approx(2 * top_truth, abs=8)
    # no snapshot / downloads in this fixture: the canvas size cannot be measured
    assert items["canvas.width"]["status"] == "unmeasured" and items["canvas.width"]["blocker"]
    ev = items["text.roles.title.size_px"]["evidence"][0]
    assert ev["video_id"] == "mockref_a" and ev["frame"].startswith("presets/joshuamagazine/analysis/mockref_a/frames/")


def test_blur_background_region(mock_truth):
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    import mockref
    t = mockref.build_blur_mock(Path(__file__).resolve().parents[2] / "assets/test/generated/reference_visual",
                                Path(__file__).resolve().parents[2] / "assets/test/generated/video")
    reg = detect_video_region(Path(__file__).resolve().parents[2] / "assets/test/generated/reference_visual/mockref_blur.mp4")
    assert reg["background"] == "blur_source"
    for k in ("y", "h"):
        assert abs(reg["video_region"][k] - t["video_region"][k]) <= 8, (k, reg)


def test_calibration_refuses_unknown_font():
    from shortkit.reference.textboxes import calibrate_font
    assert calibrate_font("Definitely Not A Font 123") is None
    c = calibrate_font("Noto Sans CJK KR Bold")
    if c is not None:       # when the font exists, libass must have rendered exactly that face
        assert c["verified_face"] and c["libass_name"]
    _ = np


def test_hd_upload_same_structure(mock_truth, tmp_path, monkeypatch):
    """Same mock at 1080x1920: roles identical, sizes x2 within ±8 %, timing within 2 frames."""
    import shutil
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).parent))
    import mockref
    repo = Path(__file__).resolve().parents[2]
    truth, hd = mockref.build_hd_mock(repo / "assets/test/generated/reference_visual", repo / "assets/test/generated/video")
    root = tmp_path / "hd"
    (root / "presets/joshuamagazine").mkdir(parents=True)
    shutil.copy(repo / "shortkit.root", root / "shortkit.root")
    shutil.copy(repo / "presets/joshuamagazine/preset.yaml", root / "presets/joshuamagazine/preset.yaml")
    monkeypatch.setenv("SHORTKIT_ROOT", str(root))
    from shortkit.cli import main
    assert main(["ref", "analyze", "--video", str(hd), "--id", "mockhd", "--only", "text"]) == 0
    cap = json.loads((root / "presets/joshuamagazine/analysis/mockhd/captions.json").read_text("utf-8"))
    assert cap["resolution"] == [1080, 1920]
    items = cap["items"]
    for ev in truth["events"]:
        ev2 = dict(ev, bbox=[v * 2 for v in ev["bbox"]])
        it = _match(items, ev2)
        assert it["role"] == ev["role"], (ev["id"], it["role"])
        assert it["style"]["ass_fontsize"] == pytest.approx(2 * ev["size"], rel=0.08), ev["id"]
        assert it["start"] == pytest.approx(ev["start"], abs=0.07) and it["end"] == pytest.approx(ev["end"], abs=0.07)
    assert len(items) == len(truth["events"])


def test_caption_entering_with_a_cut(tmp_path):
    """A caption that appears on the same frame as a hard cut: start = cut, motion_in = none."""
    import subprocess
    from pathlib import Path

    from shortkit.reference import shots, textboxes
    repo = Path(__file__).resolve().parents[2]
    V = repo / "assets/test/generated/video"
    if not (V / "classroom.mp4").is_file():
        pytest.skip("Intel sample clips missing")
    ass = tmp_path / "c.ass"
    ass.write_text("[Script Info]\nScriptType: v4.00+\nPlayResX: 540\nPlayResY: 960\n\n[V4+ Styles]\n"
                   "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
                   "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
                   "Alignment, MarginL, MarginR, MarginV, Encoding\n"
                   "Style: S,Noto Sans CJK KR Black,34,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,"
                   "1,3,0,5,10,10,10,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, "
                   "Effect, Text\nDialogue: 0,0:00:01.50,0:00:03.00,S,,0,0,0,,{\\pos(270,450)}컷과 함께 나온다\n",
                   encoding="utf-8")
    mp4 = tmp_path / "cutcap.mp4"   # SYNTHETIC: two Intel clips + one libass caption starting at the cut
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "2", "-t", "1.5", "-i", str(V / "classroom.mp4"), "-ss", "8",
                    "-t", "1.5", "-i", str(V / "people-detection.mp4"), "-filter_complex",
                    "[0:v]fps=30,scale=540:960,setsar=1[a];[1:v]fps=30,scale=540:960,setsar=1[b];"
                    f"[a][b]concat=n=2:v=1:a=0,format=yuv420p,ass={ass}[o]", "-map", "[o]", "-t", "3",
                    "-c:v", "libx264", "-preset", "veryfast", str(mp4)], check=True)
    reg = {"video_region": None}
    sh = shots.analyze(mp4, "cutcap", region=reg, out_dir=tmp_path)
    assert [c["type"] for c in sh["cuts"]] == ["cut"] and sh["cuts"][0]["t"] == pytest.approx(1.5, abs=0.04)
    cap, _ = textboxes.analyze(mp4, "cutcap", region=reg, out_dir=tmp_path, save_frames=False)
    assert len(cap["items"]) == 1
    it = cap["items"][0]
    assert it["start"] == pytest.approx(1.5, abs=0.04) and it["motion_in"] == "none"
