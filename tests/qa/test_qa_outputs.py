"""Regression tests for the output checks of wave 5 (every preset style key has an output check).

All media here are SYNTHETIC renders with known values, drawn with the production renderer's own functions
(tests/qa/qa_outsynth.py, tests/reference_visual/mockfx.py): captions with a drop shadow / a box / a slide_up entrance
and quote marks / a colour glyph, an arrow decoration, a flash with each scope, a zoom with each recenter rule, a
contain / cover fit over a blurred background, BGM ramps (ducking, intentional silence) and kept-original fades.
Nothing here is reference-channel data; no external platform is contacted.
"""
from __future__ import annotations

import dataclasses
import json
import shutil
from types import SimpleNamespace

import numpy as np
import pytest

from shortkit import config, paths
from shortkit.qa import checks

from .qa_outsynth import EMOJI_DISK, GEN, clip, media_ctx, probe_caption_items, render_captions, render_clips
from .test_qa_review_d import P, REAL_ROOT, _builder, temp_root  # noqa: F401  (temp_root: pytest fixture)

FPS = 30.0


def _all_measured(b):
    b.reference_of = lambda ks: ({k: "SYNTHETIC-measured" for k in ks} if ks else None, [], [])
    return b


def _rows(b) -> dict:
    return {r["row_id"]: r for r in b.rows}


def _set(b, values: dict):
    """Effective preset values for a builder (SYNTHETIC; as if measured)."""
    orig = b.pget
    b.pget = lambda k, default=None: values[k] if k in values else orig(k, default)
    return b


# ============================================================================ captions (shadow, box, slide, quotes, emoji)
@pytest.fixture(scope="module")
def caps_out(tmp_path_factory):
    d = tmp_path_factory.mktemp("capout")
    mp4, caps = render_captions(d / "caps.mp4")
    ctx = media_ctx(mp4, captions=caps)
    return ctx, {c.id: c for c in caps}, probe_caption_items(ctx)


def test_drop_shadow_is_measured_in_the_output(caps_out):
    ctx, caps, meas = caps_out
    m = meas["sh"]
    ls = checks.line_style_summary(m)
    assert ls["shadow_px"] == pytest.approx(5.0, abs=checks.SHADOW_TOL_PX)
    assert checks._cdist(ls["shadow_color"], "#2040C0") <= checks.TOL["color_rgb"]
    obs, exp, keys, notes, ok = checks._style_extras(caps["sh"], m, "situation")
    assert ok and {"text.roles.situation.shadow_px", "text.roles.situation.shadow_color"} <= set(keys)
    # the plan without a shadow: the output's shadow is a difference
    no_sh = dataclasses.replace(caps["sh"], shadow_px=0.0)
    assert checks._style_extras(no_sh, m, "situation")[4] is False
    # a caption without a drop shadow over the same background reads 0 (no lower-right asymmetry)
    assert checks.line_style_summary(meas["ns"])["shadow_px"] == 0.0
    assert checks._style_extras(caps["ns"], meas["ns"], "description")[4] is True
    # the yellow dialogue line (5 px black outline, no shadow, grey texture) reads 0 as well.  Before the shared
    # estimator its fill was taken to be the black outline (reference.textboxes._resolve_fill_side now picks the
    # enclosed yellow ink) and the line read 못 잼 -- that was a mis-measurement, not a dark background.
    dl = checks.line_style_summary(meas["dl"])
    assert dl["shadow_px"] == 0.0
    assert all(checks._cdist(ln["color"], "#FFE400") <= checks.TOL["color_rgb"]
               for ln in meas["dl"]["line_style"]["lines"])
    # over a dark background a dark shadow is invisible: 못 잼 (shared estimator; the row then leaves the key out)
    from shortkit.util.textmeasure import drop_shadow
    ln = meas["sh"]["line_style"]["lines"][0]
    assert ln["shadow"]["status"] == "measured"
    dark = drop_shadow(np.zeros((40, 40, 3), np.uint8), np.eye(40, dtype=bool), (20, 20, 20))
    assert dark["status"] == "unmeasured" and dark["shadow_px"] is None


def test_reference_and_qa_share_one_shadow_estimator(caps_out, monkeypatch):
    """The reference analyzer's line measurement (reference.textboxes.measure_line) and QA read the drop shadow with the
    SAME estimator (shortkit.util.textmeasure.drop_shadow).  The old reference function ended its search at k=1 (that
    ring lies inside the dilated ink) and returned 0 for the 5 px shadow drawn here; it is gone."""
    from shortkit.qa import probes_text
    from shortkit.qa.probes_video import grab
    from shortkit.reference import textboxes as tb
    from shortkit.util import textmeasure

    assert not hasattr(tb, "_shadow") and not hasattr(probes_text, "drop_shadow")
    ctx, caps, meas = caps_out
    x, y, w, h = (int(round(v)) for v in meas["sh"]["line_boxes"][0])
    b = (x - 5, y - 5, w + 10, h + 10)
    crop, org = tb._crop_with_pad(grab(ctx.mp4, 1.0), b, max(10, b[3]))
    m = tb.measure_line(crop, (b[0] - org[0], b[1] - org[1], b[2], b[3]))
    assert m["shadow"]["algo"] == textmeasure.SHADOW_ALGO and m["shadow"]["status"] == "measured"
    assert m["shadow_px"] == pytest.approx(5.0, abs=checks.SHADOW_TOL_PX)
    assert checks._cdist(m["shadow_color"], "#2040C0") <= checks.TOL["color_rgb"]
    # QA's line record is that same estimator's record: spy on the shared function
    calls = []
    real = textmeasure.drop_shadow
    monkeypatch.setattr(textmeasure, "drop_shadow", lambda *a, **k: calls.append(1) or real(*a, **k))
    cap = caps["sh"]
    loc = {"line_boxes": meas["sh"]["line_boxes"]}
    rec = probes_text.caption_line_styles(grab(ctx.mp4, 1.0), cap, loc)
    assert calls, "QA must measure the shadow through shortkit.util.textmeasure.drop_shadow"
    ln = rec["lines"][0]
    assert ln["shadow"]["algo"] == textmeasure.SHADOW_ALGO
    assert ln["shadow_px"] == pytest.approx(5.0, abs=checks.SHADOW_TOL_PX)


def test_box_padding_and_colour_are_measured_in_the_output(caps_out):
    ctx, caps, meas = caps_out
    m = meas["bx"]
    bo = checks.line_style_summary(m)["box"]
    assert bo["present"] == "present"
    assert bo["pad_fill_x"] == pytest.approx(14, abs=checks.PAD_TOL_PX)
    assert bo["pad_fill_y"] == pytest.approx(8, abs=checks.PAD_TOL_PX)
    bc = m["box_color"]
    assert bc["status"] == "measured" and checks._cdist(bc["color"], "#183050") <= checks.TOL["color_rgb"]
    assert bc["alpha"] == pytest.approx(0.7, abs=0.1)
    obs, exp, keys, notes, ok = checks._style_extras(caps["bx"], m, "speaker")
    assert ok, notes
    assert {"text.roles.speaker.box.pad_x", "text.roles.speaker.box.pad_y", "text.roles.speaker.box.color"} <= set(keys)
    wrong = dataclasses.replace(caps["bx"], box=dict(caps["bx"].box, pad_x=30, color="#FF0000"))
    assert checks._style_extras(wrong, m, "speaker")[4] is False


def test_role_style_reference_row_compares_shadow_and_box_keys(caps_out):
    ctx, caps, meas = caps_out
    b = _all_measured(_builder())
    b = _set(b, {"text.roles.speaker.box.enabled": True, "text.roles.speaker.box.pad_x": 14,
                 "text.roles.speaker.box.pad_y": 8, "text.roles.speaker.box.color": "#183050",
                 "text.roles.speaker.box.alpha": 0.7, "text.roles.speaker.color": "#FFFFFF",
                 "text.roles.speaker.outline_px": 0, "text.roles.speaker.shadow_px": 0})
    m = dict(meas["bx"], found=True)
    na = checks.role_not_applicable(b, "speaker", [caps["bx"]])
    checks._style_ref_row(b, "speaker", [m], [caps["bx"]], na)
    r = _rows(b)["caption.style:speaker_ref"]
    assert r["status"] == "same", r
    assert {"text.roles.speaker.box.pad_x", "text.roles.speaker.box.pad_y", "text.roles.speaker.box.color"} <= set(r["keys"])
    b = _all_measured(_builder())
    b = _set(b, {"text.roles.situation.shadow_px": 0, "text.roles.situation.color": "#FFFFFF"})
    checks._style_ref_row(b, "situation", [dict(meas["sh"], found=True)], [caps["sh"]],
                          checks.role_not_applicable(b, "situation", [caps["sh"]]))
    r = _rows(b)["caption.style:situation_ref"]
    assert "text.roles.situation.shadow_px" in r["keys"] and r["status"] == "different"   # 5 px shadow vs reference 0


def test_slide_up_start_offset_is_measured_from_the_first_frames(caps_out):
    ctx, caps, meas = caps_out
    m = meas["dl"]
    mo = m["motion_in_obs"]
    assert mo["type"] == "slide_up" and mo["offset_px"] == pytest.approx(40, abs=3)
    assert mo["dur_s"] == pytest.approx(0.2, abs=1.5 / FPS) and m["onset"] == pytest.approx(1.0, abs=1.0 / FPS)
    b = _builder()
    checks._motion_rows(b, caps["dl"], m, "dialogue", "[dl]", {}, 1.0 / FPS)
    r = _rows(b)["caption.motion:dl"]
    assert r["status"] == "same" and "text.roles.dialogue.motion_in.offset_px" in r["keys"]
    far = dataclasses.replace(caps["dl"], motion_in=dict(caps["dl"].motion_in, offset_px=80))
    b = _builder()
    checks._motion_rows(b, far, m, "dialogue", "[dl]", {}, 1.0 / FPS)
    assert _rows(b)["caption.motion:dl"]["status"] == "different"


def test_slide_offset_applies_only_to_slide_up_roles():
    b = _builder()
    b = _set(b, {"text.roles.dialogue.motion_in.type": "slide_up", "text.roles.situation.motion_in.type": "pop"})
    assert "text.roles.dialogue.motion_in.offset_px" not in checks.role_not_applicable(b, "dialogue", [])
    assert "text.roles.situation.motion_in.offset_px" in checks.role_not_applicable(b, "situation", [])
    # one vocabulary: the reference analyzer also writes 'slide_up' (reference.textboxes.slide_kind); QA keeps no
    # alias.  A measured non-upward slide is not the renderer's slide_up (resolve refuses it), so its offset is not
    # the slide_up offset.
    assert not hasattr(checks, "_mi_type")
    b = _set(_builder(), {"text.roles.dialogue.motion_in.type": "slide_down"})
    assert "text.roles.dialogue.motion_in.offset_px" in checks.role_not_applicable(b, "dialogue", [])


def test_quote_marks_by_glyph_shape(caps_out):
    ctx, caps, meas = caps_out
    q = meas["dl"]["quote_marks"]["shape"]
    assert q["open"]["glyph"] == '"' and q["close"]["glyph"] == '"'
    b = _builder()
    b.ctx.resolved.captions = [caps["dl"]]
    checks._quote_rows(b, {"dl": meas["dl"]})
    rows = _rows(b)
    assert rows["caption.quote:dl"]["status"] == "same"
    assert rows["caption.quote:dl"]["keys"] == ["text.roles.dialogue.quote_marks"]
    # a plan without quote marks: the drawn quotes differ
    b = _builder()
    b.ctx.resolved.captions = [dataclasses.replace(caps["dl"], text="잠깐만요 진짜요?")]
    checks._quote_rows(b, {"dl": meas["dl"]})
    assert _rows(b)["caption.quote:dl"]["status"] == "different"


def test_quote_reference_row_reads_the_pair():
    b = _all_measured(_builder())
    cap = SimpleNamespace(id="d", role="dialogue", text='"네"')
    b.ctx.resolved.captions = [cap]
    m = {"found": True, "quote_marks": {"shape": {"status": "measured", "open": {"present": True, "glyph": '"'},
                                                  "close": {"present": True, "glyph": '"'}}}}
    for pq, st in ((['"', '"'], "same"), ([], "different"), (["“", "”"], "different")):
        b.rows = []
        _set(b, {"text.roles.dialogue.quote_marks": pq})
        checks._quote_rows(b, {"d": m})
        assert _rows(b)["caption.quote:dialogue_ref"]["status"] == st, pq


def test_colour_glyph_in_a_caption_is_detected(caps_out):
    ctx, caps, meas = caps_out
    assert meas["rx"]["emoji"]["n_blobs"] >= 1
    x = meas["rx"]["emoji"]["blobs"][0]["bbox"]
    assert abs(x[0] - EMOJI_DISK["x"]) <= 4 and abs(x[1] - EMOJI_DISK["y"]) <= 4
    for cid in ("sh", "ns", "bx", "dl"):
        assert meas[cid]["emoji"]["status"] == "measured" and meas[cid]["emoji"]["n_blobs"] == 0, cid
    b = _builder()
    b.ctx.resolved.captions = list(caps.values())
    checks._emoji_rows(b, meas)
    rows = _rows(b)
    assert rows["caption.tone:emoji"]["status"] == "different"            # 'rx' has no emoji in its plan text
    b = _all_measured(_builder())
    b.ctx.resolved.captions = list(caps.values())
    _set(b, {"text.tone.emoji": False})
    checks._emoji_rows(b, meas)
    assert _rows(b)["caption.tone:emoji_ref"]["status"] == "different"
    b = _all_measured(_builder())
    b.ctx.resolved.captions = [caps["sh"], caps["dl"]]
    _set(b, {"text.tone.emoji": False})
    checks._emoji_rows(b, {k: meas[k] for k in ("sh", "dl")})
    rows = _rows(b)
    assert rows["caption.tone:emoji"]["status"] == "same" and rows["caption.tone:emoji_ref"]["status"] == "same"
    assert rows["caption.tone:emoji_ref"]["keys"] == ["text.tone.emoji"]


# ============================================================================ dialogue lead
def test_dialogue_lead_is_measured_against_the_output_speech():
    cap = SimpleNamespace(id="d", role="dialogue", start=2.0, end=4.0)
    meas = {"d": {"onset": 2.1, "offset": 4.0, "found": True}}
    leads = checks.dialogue_leads([cap], meas, {"status": "measured", "spans": [[1.9, 3.5]]})
    # lead_s = speech onset - caption start: the caption shows 0.2 s AFTER the line starts -> -0.2
    assert leads[0]["lead_s"] == pytest.approx(-0.2) and leads[0]["speech_onset"] == pytest.approx(1.9)
    assert checks.dialogue_leads([cap], meas, {"status": "measured", "spans": [[5.0, 6.0]]})[0].get("lead_s") is None
    probes = {"audio": {"originals": {"voice_out": {"speech": {"status": "measured", "spans": [[1.9, 3.5]]}}}}}
    for lead, st in ((-0.2, "same"), (0.0, "different"), (0.2, "different")):
        b = _set(_all_measured(_builder()), {"text.roles.dialogue.timing.lead_s": lead})
        checks._lead_ref_row(b, [cap], meas, probes, 1.0 / FPS)
        r = _rows(b)["caption.timing:dialogue_lead_ref"]
        assert r["status"] == st and r["keys"] == ["text.roles.dialogue.timing.lead_s"]
    b = _all_measured(_builder())
    checks._lead_ref_row(b, [cap], meas, {"audio": {}}, 1.0 / FPS)
    assert _rows(b)["caption.timing:dialogue_lead_ref"]["status"] == "unmeasured"


def test_dialogue_lead_same_case_as_reference_and_resolve():
    """The synthetic case shared with tests/edit/test_motion_lead_semantics.py (resolve) and
    tests/reference_visual/test_rv_slide_lead.py (analyzer): the line is heard at 3.0 s, the caption shows at 2.8 s
    -> lead_s = +0.2 (the caption appears before the line).  QA reads it with the analyzer's own function."""
    from shortkit.reference.textboxes import dialogue_lead

    cap = SimpleNamespace(id="d", role="dialogue", start=2.8, end=4.4)
    meas = {"d": {"onset": 2.8, "offset": 4.4, "found": True}}
    sp = {"status": "measured", "spans": [[3.0, 4.0]]}
    lead = checks.dialogue_leads([cap], meas, sp)[0]
    assert lead["lead_s"] == pytest.approx(0.2) and lead["speech_onset"] == pytest.approx(3.0)
    assert lead["lead_s"] == pytest.approx(dialogue_lead(2.8, 4.4, [(3.0, 4.0)])[0])
    probes = {"audio": {"originals": {"voice_out": {"speech": sp}}}}
    for pv, st in ((0.2, "same"), (-0.2, "different")):     # -0.2 = the old (caption start - onset) sign
        b = _set(_all_measured(_builder()), {"text.roles.dialogue.timing.lead_s": pv})
        checks._lead_ref_row(b, [cap], meas, probes, 1.0 / FPS)
        assert _rows(b)["caption.timing:dialogue_lead_ref"]["status"] == st


def test_lead_does_not_apply_to_other_roles_by_definition():
    b = _builder()
    na = checks.role_not_applicable(b, "situation", [])
    assert "text.roles.situation.timing.lead_s" in na and "정의" in na["text.roles.situation.timing.lead_s"]
    assert "text.roles.dialogue.timing.lead_s" not in checks.role_not_applicable(b, "dialogue", [])
    # a non-zero lead on a non-dialogue role is not silently dropped: the timing row carries it as 못 잼
    b = _set(_all_measured(_builder()), {"text.roles.situation.timing.lead_s": 0.3})
    assert "text.roles.situation.timing.lead_s" not in checks.role_not_applicable(b, "situation", [])


# ============================================================================ arrow geometry
@pytest.fixture(scope="module")
def arrow_out(tmp_path_factory):
    from tests.reference_visual import mockfx

    d = tmp_path_factory.mktemp("arrow")
    deco = {"kind": "arrow", "start": 0.5, "end": 2.5, "keyframes": [{"t": 0.5, "x": 200, "y": 420, "rotation": 30}],
            "blink_hz": 0.0, "style": {"color": "#FF2A2A", "size_px": 110, "outline_px": 4, "outline_color": "#FFFFFF",
                                       "head_len_ratio": 0.4, "head_width_ratio": 0.7, "shaft_width_ratio": 0.22}}
    mp4 = mockfx.build_decoration_mock(d / "arrow.mp4", [deco], total=3.0, tmp=d)
    from shortkit.edit.ir import Decoration

    dd = Decoration(id="a1", kind="arrow", start=0.5, end=2.5, keyframes=deco["keyframes"], blink_hz=0.0, style=deco["style"])
    return media_ctx(mp4, decorations=[dd]), dd


def test_arrow_geometry_is_measured_with_the_reference_detector(arrow_out):
    from shortkit.qa.probes_video import ARROW_OUTLINE_TOL_PX, ARROW_RATIO_TOL, analyze_arrow_geometry

    ctx, d = arrow_out
    ag = analyze_arrow_geometry(ctx)["items"][0]
    assert ag["status"] == "measured"
    for k in ("head_len_ratio", "head_width_ratio", "shaft_width_ratio"):
        assert ag[k] == pytest.approx(d.style[k], abs=ARROW_RATIO_TOL), k
    assert ag["outline_px"] == pytest.approx(4, abs=ARROW_OUTLINE_TOL_PX)
    assert checks._cdist(ag["outline_color"], "#FFFFFF") <= checks.TOL["color_rgb"]
    b = _builder()
    obs, keys, notes, ok = checks._deco_style(b, d, {"color_obs": "#FF2A2A"}, ag)
    assert ok, notes
    assert {f"decorations.arrow.{k}" for k in ("head_len_ratio", "head_width_ratio", "shaft_width_ratio", "outline_px",
                                               "outline_color")} <= set(keys)
    wrong = dataclasses.replace(d, style=dict(d.style, head_len_ratio=0.25, outline_px=10))
    assert checks._deco_style(b, wrong, {"color_obs": "#FF2A2A"}, ag)[3] is False


# ============================================================================ flash scope
@pytest.fixture(scope="module", params=["region", "canvas"])
def flash_out(request, tmp_path_factory):
    from shortkit.edit.ir import Clip, Rect, Transition
    from tests.reference_visual import mockfx

    d = tmp_path_factory.mktemp(f"flash_{request.param}")
    mp4, truth = mockfx.build_flash_mock(d / "flash.mp4", request.param)
    rx, ry, rw, rh = mockfx.FLASH_REGION
    c = Clip(id="b", source_id="s", source_path="x.mp4", src_in=0.0, src_out=1.0, speed=1.0, out_start=1.0, out_end=2.0,
             region=Rect(rx, ry, rw, rh), fit="cover", src_size=(rw, rh),
             transition_in=Transition("flash", 0.2, "#FFFFFF", scope=request.param))
    return media_ctx(mp4, clips=[c]), c, request.param


def test_flash_scope_is_measured_in_the_output(flash_out):
    from shortkit.qa.probes_video import flash_scope

    ctx, c, scope = flash_out
    fs = flash_scope(ctx, c, {"t": 0.9, "peak_t": 1.0, "color": "#FFFFFF"})
    assert fs["status"] == "measured" and fs["scope"] == scope, fs
    # the transition row carries the scope key and judges it against the plan
    bd = {"clip_id": "b", "expected": {"type": "flash", "t": 1.0, "dur": 0.2, "color": "#FFFFFF", "scope": scope},
          "observed": {"type": "flash", "t": 0.9, "dur": 0.2, "color": "#FFFFFF", "scope_obs": fs},
          "type_ok": True, "timing_ok": True}
    other = "canvas" if scope == "region" else "region"
    for exp_scope, st in ((scope, "same"), (other, "different")):
        b = _set(_builder(), {"motion.transitions.flash.scope": exp_scope, "motion.transitions.flash.color": "#FFFFFF",
                              "motion.transitions.flash.dur_s": 0.2})
        b.ctx.resolved.clips = [c]
        bd2 = json.loads(json.dumps(bd))
        bd2["expected"]["scope"] = exp_scope
        checks.rows_video(b, {"video": {"transitions": {"boundaries": [bd2], "unexpected": []}}})
        r = _rows(b)["video.transitions:b"]
        assert r["status"] == st and "motion.transitions.flash.scope" in r["keys"]


# ============================================================================ zoom recenter
@pytest.fixture(scope="module", params=[False, True])
def zoom_out(request, tmp_path_factory):
    from tests.reference_visual import mockfx

    d = tmp_path_factory.mktemp(f"zoom_{request.param}")
    total = 1.8
    mp4, _truth = mockfx.build_zoom_mock(d / "zoom.mp4", "out", request.param, total=total)
    c = mockfx.zoom_clip("out", request.param, total=total)
    ctx = media_ctx(mp4, clips=[c], canvas={"width": mockfx.W, "height": mockfx.H, "fps": 30,
                                            "background": {"type": "color", "color": "#1E2A5A"}})
    return ctx, c, request.param


def test_zoom_fixed_point_follows_the_renderer_rule(zoom_out):
    from shortkit.qa.probes_video import analyze_zoom, scan

    ctx, c, recenter = zoom_out
    z = analyze_zoom(ctx, scan(ctx, width=540))["clips"][0]
    ro = z["recenter_obs"]
    assert ro["status"] == "measured" and ro["recenter"] is recenter, ro
    b = _set(_builder(), {"motion.zoom.recenter": recenter})
    b.ctx.resolved.clips = [c]
    checks.rows_video(b, {"video": {"zoom": {"clips": [z], "max_consecutive_measured": 1}}})
    r = _rows(b)["video.zoom:z"]
    assert "motion.zoom.recenter" in r["keys"] and r["observed"]["recenter"] is recenter
    flipped = dataclasses.replace(c, zoom=dataclasses.replace(c.zoom, recenter=not recenter))
    b = _builder()
    b.ctx.resolved.clips = [flipped]
    z2 = dict(z, expected=dict(z["expected"]))
    checks.rows_video(b, {"video": {"zoom": {"clips": [z2], "max_consecutive_measured": 1}}})
    assert _rows(b)["video.zoom:z"]["status"] == "different"


def test_rule_fixed_point_is_the_renderer_geometry():
    from tests.reference_visual import mockfx
    from shortkit.qa.probes_video import rule_fixed_point

    c = mockfx.zoom_clip("linear", False)
    rx, ry, rw, rh = mockfx.ZOOM_REGION
    fp = rule_fixed_point(c, 0.5, 1.0)
    assert fp == pytest.approx([rx + 126.0, ry + 270.0], abs=0.5)    # centre_src (336, 270) in the cover-fit region
    fp2 = rule_fixed_point(dataclasses.replace(c, zoom=dataclasses.replace(c.zoom, recenter=True)), 0.5, 1.0)
    assert abs(fp2[0] - fp[0]) > 20


# ============================================================================ video-region fit and background blur
@pytest.fixture(scope="module")
def fit_out(tmp_path_factory):
    from shortkit.edit.ir import Rect

    d = tmp_path_factory.mktemp("fit")
    canvas = {"width": 360, "height": 640, "fps": 30, "background": {"type": "blur_source", "color": "#000000",
                                                                     "blur_sigma": 24.0}}
    region = (0.0, 220.0, 360.0, 202.0)
    src = f"{GEN}/video/classroom.mp4"
    if not paths.absp(src).is_file():
        pytest.skip(f"{src} missing (python -m shortkit.testassets)")
    crop = Rect(240.0, 0.0, 1440.0, 1080.0)                             # a 4:3 picture in a 16:9 region
    c1 = clip("c1", src, 20.0, 0.0, 1.5, region, fit="contain", crop=crop)
    c2 = clip("c2", src, 23.0, 1.5, 3.0, region, fit="cover", crop=crop)
    mp4 = render_clips(d / "fit.mp4", [c1, c2], canvas, 3.0)
    return media_ctx(mp4, clips=[c1, c2], canvas=canvas), c1, c2


def test_fit_and_background_blur_are_measured_in_the_output(fit_out):
    from shortkit.qa.probes_video import analyze_canvas_geometry

    ctx, c1, c2 = fit_out
    cg = analyze_canvas_geometry(ctx)
    fits = {f["clip_id"]: f for f in cg["fit"]}
    assert fits["c1"]["status"] == "measured" and fits["c1"]["fit"] == "contain", fits["c1"]
    assert fits["c2"]["status"] == "measured" and fits["c2"]["fit"] == "cover", fits["c2"]
    bl = cg["blur"]
    assert bl["status"] == "measured" and bl["sigma"] == pytest.approx(24.0, abs=checks._blur_tol(24.0)), bl
    b = _set(_builder(), {"canvas.video_region.fit": "contain", "canvas.background.blur_sigma": 24.0})
    b.ctx.resolved.clips = [c1, c2]
    b.ctx.resolved.canvas = ctx.resolved.canvas
    checks._rows_canvas_geometry(b, {"video": {"canvas_geometry": cg}})
    rows = _rows(b)
    assert rows["canvas.video_region:fit"]["status"] == "same"
    assert rows["canvas.background:blur"]["status"] == "same"
    assert rows["canvas.background:blur"]["keys"] == ["canvas.background.blur_sigma"]
    # a plan whose clip is cover where the output shows contain
    b = _builder()
    b.ctx.resolved.clips = [dataclasses.replace(c1, fit="cover"), c2]
    b.ctx.resolved.canvas = dict(ctx.resolved.canvas, background=dict(ctx.resolved.canvas["background"], blur_sigma=60.0))
    cg2 = json.loads(json.dumps(cg))
    cg2["fit"][0]["expected"] = "cover"
    checks._rows_canvas_geometry(b, {"video": {"canvas_geometry": cg2}})
    rows = _rows(b)
    assert rows["canvas.video_region:fit"]["status"] == "different"
    assert rows["canvas.background:blur"]["status"] == "different"


def test_blur_sigma_does_not_apply_to_a_colour_background():
    b = _set(_builder(), {"canvas.background.type": "color"})
    b.ctx.resolved.canvas = {"background": {"type": "color", "color": "#000000"}}
    checks._rows_canvas_geometry(b, {"video": {"canvas_geometry": {"fit": [], "blur": None}}})
    assert "canvas.background:blur" not in _rows(b)


# ============================================================================ audio: BGM level and ramps, kept fades
SR = 22050


def _music(seconds: float) -> np.ndarray:
    from shortkit.reference.separation import load_mono

    x = load_mono(REAL_ROOT / GEN / "music_bed_a.wav", SR)
    return x[int(10 * SR):int((10 + seconds) * SR)].astype(np.float32)


def _env(att: float, rel: float, fade: float) -> list:
    return [[0.0, 0.0], [2.0 - att, 0.0], [2.0, -10.0], [3.5, -10.0], [3.5 + rel, 0.0], [4.5 - fade, 0.0], [4.5, -120.0],
            [5.0, -120.0], [5.0 + fade, 0.0], [7.0, 0.0]]


def _bgm_ctx(env):
    bgm = SimpleNamespace(envelope=env, silences=[[4.5, 5.0]], duck_ranges=[[2.0, 3.5]], fade_in_s=0.0, fade_out_s=0.0,
                          gain_db=0.0)
    ctx = SimpleNamespace(resolved=SimpleNamespace(audio=SimpleNamespace(bgm=bgm, originals=[], sfx=[])))
    return ctx


def test_ducking_and_silence_ramps_are_read_with_the_reference_functions():
    from shortkit.edit.render import envelope_gain
    from shortkit.qa.probes_audio import bgm_ramps

    y = _music(7.0)
    planned = _env(0.08, 0.3, 0.05)
    speech = [[2.0, 3.5]]
    rng = np.random.default_rng(0)
    for att, rel, fade, st in ((0.08, 0.3, 0.05, "same"), (0.3, 0.6, 0.15, "different")):
        out_sig = y * envelope_gain(_env(att, rel, fade), len(y), SR) + rng.normal(0, 1e-4, len(y)).astype(np.float32)
        rp = bgm_ramps(_bgm_ctx(planned), out_sig.astype(np.float32), y, SR, speech)
        seg = rp["ducking"]["per_segment"][0]
        if st == "same":
            assert seg["attack_s"] == pytest.approx(seg["planned_reading"]["attack_s"], abs=0.01)
            assert seg["release_s"] == pytest.approx(seg["planned_reading"]["release_s"], abs=0.02)
            sil = rp["silences"]["items"][0]["observed"]
            assert sil["into"]["fade_s"] == pytest.approx(0.05, abs=0.01) and sil["out_of"]["fade_s"] == pytest.approx(0.05, abs=0.01)
        b = _builder()
        b.ctx.resolved.audio = _bgm_ctx(planned).resolved.audio
        checks._rows_bgm_ramps(b, {"ramps": rp})
        rows = _rows(b)
        assert rows["audio.ducking:ramps0"]["status"] == st, rows["audio.ducking:ramps0"]
        assert rows["audio.silence:ramps0"]["status"] == st, rows["audio.silence:ramps0"]
        assert set(rows["audio.ducking:ramps0"]["keys"]) == {"audio.ducking.attack_s", "audio.ducking.release_s"}
        assert rows["audio.silence:ramps0"]["keys"] == ["audio.silence.fade_s"]
        assert {"audio.ducking:ramps_ref", "audio.silence:fade_ref"} <= set(rows)


def test_kept_original_edge_fades_are_read_with_the_reference_function():
    from shortkit.qa.probes_audio import original_ramps

    rng = np.random.default_rng(1)
    n = int(5.0 * SR)
    x = np.zeros(n, np.float32)
    a, c = int(1.5 * SR), int(3.5 * SR)
    for fade, st in ((0.04, "same"), (0.2, "different")):
        g = np.zeros(n, np.float32)
        g[a:c] = 1.0
        k = int(fade * SR)
        g[a:a + k] = np.linspace(0, 1, k, endpoint=False)
        g[c - k:c] = np.linspace(1, 0, k)
        x = (rng.normal(0, 0.1, n) * g).astype(np.float32)          # stationary room tone kept 1.5-3.5 s
        o = SimpleNamespace(clip_id="c", out_start=1.5, out_end=3.5, fade_s=0.04)
        ctx = SimpleNamespace(resolved=SimpleNamespace(audio=SimpleNamespace(originals=[o])))
        rp = original_ramps(ctx, x, SR)
        e = rp["items"][0]["edges"]
        assert [x_["status"] for x_ in e] == ["measured", "measured"], e
        assert all(abs(x_["fade_s"] - fade) <= checks._ramp_tol(fade) for x_ in e), e
        b = _set(_builder(), {"audio.original.fade_s": 0.04})
        b.ctx.resolved.audio = SimpleNamespace(originals=[o], sfx=[], bgm=None)
        checks._rows_original_ramps(b, {"ramps": rp})
        r = _rows(b)["audio.original:fade0"]
        assert r["status"] == st and (r["keys"] == ["audio.original.fade_s"])


def test_bgm_level_at_programme_loudness():
    from shortkit.qa.probes_audio import bgm_level_obs

    lv = bgm_level_obs(-0.3, -14.0, -14.5)
    assert lv["level_db"] == pytest.approx(0.2)
    for gain, st in ((0.0, "same"), (-6.0, "different")):
        b = _builder()
        checks._rows_bgm_level(b, SimpleNamespace(gain_db=gain), {"level": lv})
        rows = _rows(b)
        assert rows["audio.bgm:level"]["status"] == st and rows["audio.bgm:level"]["required"] is True
        assert "audio.bgm:level_ref" in rows
    b = _builder()
    checks._rows_bgm_level(b, SimpleNamespace(gain_db=0.0), {"level": bgm_level_obs(None, -14.0, -14.5)})
    assert _rows(b)["audio.bgm:level"]["status"] == "unmeasured"


# ============================================================================ structure p50
def test_structure_rows_read_p50_and_report_the_median_position():
    o = {"duration": 25.0}
    r = checks._KeyReads({"structure.duration_s.p10": 10, "structure.duration_s.p50": 20, "structure.duration_s.p90": 30})
    assert checks._in_distribution(o, "duration", r, "structure.duration_s") is True
    assert r.read == {"structure.duration_s.p10", "structure.duration_s.p50", "structure.duration_s.p90"}
    assert o["vs_reference_median"]["side"] == "중앙값 위" and o["vs_reference_median"]["diff"] == pytest.approx(5.0)
    assert checks._in_distribution({"duration": 35.0}, "duration", r, "structure.duration_s") is False
    bad = {"structure.duration_s.p10": 10, "structure.duration_s.p50": 40, "structure.duration_s.p90": 30}
    assert checks._in_distribution({"duration": 20.0}, "duration", bad, "structure.duration_s") is None
    b = _all_measured(_builder())
    _set(b, {"structure.cuts_per_10s.p10": 1.0, "structure.cuts_per_10s.p50": 2.0, "structure.cuts_per_10s.p90": 4.0,
             "structure.shot_len_s.p10": 1.0, "structure.shot_len_s.p50": 2.5, "structure.shot_len_s.p90": 5.0})
    video = {"transitions": {"boundaries": [{"observed": {"type": "cut", "t": 3.0}}, {"observed": {"type": "cut", "t": 6.0}}],
                             "unexpected": []}}
    checks._rows_cut_structure(b, {"video": video})
    rows = _rows(b)
    assert rows["structure.cuts:rate_ref"]["status"] == "same"
    assert "structure.cuts_per_10s.p50" in rows["structure.cuts:rate_ref"]["keys"]
    assert rows["structure.cuts:rate_ref"]["observed"]["vs_reference_median"]["p50"] == 2.0
    assert "structure.shot_len_s.p50" in rows["structure.cuts:shot_len_ref"]["keys"]


# ============================================================================ (a) partial SFX catalog
def test_partial_catalog_types_detections(temp_root):
    from shortkit.qa.probes_audio import classify_sfx_detections
    from shortkit.util.jsonio import read_json, write_json

    from .test_qa_finish import _catalog_with_centroids

    (temp_root / GEN / "sfx").mkdir(parents=True, exist_ok=True)
    for f in ("whoosh", "ding"):
        shutil.copy(REAL_ROOT / GEN / "sfx" / f"{f}.wav", temp_root / GEN / "sfx" / f"{f}.wav")
    _catalog_with_centroids(temp_root, {"cat_whoosh": f"{GEN}/sfx/whoosh.wav", "cat_ding": f"{GEN}/sfx/ding.wav"})
    cp = temp_root / P / "sfx_catalog.json"
    cat = read_json(cp)
    cat.update(status="partial", column_status={"per_video_count": "measured", "emotion": "unmeasured"})
    write_json(cp, cat)
    ctx = SimpleNamespace(preset=config.load_preset("joshuamagazine"))
    dets = [{"t": 1.0, "type": "x", "file": f"{GEN}/sfx/whoosh.wav"}]
    s = classify_sfx_detections(ctx, dets)
    assert s["status"] == "measured" and s["catalog_status"] == "partial"
    assert dets[0]["catalog_type"]["type_id"] == "cat_whoosh"
    # per-video counts only lower bounds: not usable
    cat["column_status"]["per_video_count"] = "lower_bound"
    write_json(cp, cat)
    dets = [{"t": 1.0, "type": "x", "file": f"{GEN}/sfx/whoosh.wav"}]
    assert classify_sfx_detections(ctx, dets)["status"] == "unmeasured"


# ============================================================================ (b) first-caption roles: one definition
def test_first_caption_roles_are_the_aggregate_tuple():
    from shortkit.reference import aggregate

    assert checks.FIRST_CAPTION_EXCLUDED_ROLES is aggregate.FIRST_CAPTION_EXCLUDED_ROLES
    src = (REAL_ROOT / "shortkit/reference/classify.py").read_text(encoding="utf-8")
    assert "FIRST_CAPTION_EXCLUDED_ROLES" in src and '("title", "description", "identity_mark", "unknown")' not in src


# ============================================================================ (c) identity templates manifest
def _manifest(root, **kw):
    from shortkit.util.jsonio import read_json, write_json

    d = root / P / "reference" / "identity_templates"
    d.mkdir(parents=True, exist_ok=True)
    snap = (read_json(root / P / "reference" / "latest100.json") or {}).get("captured_at")
    m = {"schema": "shortkit.identity_templates/1", "status": "measured", "blocker": None, "source_snapshot": snap,
         "templates": [], "review": [], "generated_by": "shortkit ref identity-templates"}
    m.update(kw)
    write_json(d / "manifest.json", m)
    return d


def test_logo_template_row_reads_the_identity_templates_manifest(temp_root):
    b = _builder(mode="test")
    tdir = b.pget("identity_exclusions.logo_templates_dir")
    _manifest(temp_root)
    r = checks._logo_template_check(b.ctx, tdir)
    assert r["status"] == "same" and "templates: []" in r["note"]
    _manifest(temp_root, status="partial", blocker="영상 2편 못 받음")
    r = checks._logo_template_check(b.ctx, tdir)
    assert r["status"] == "unmeasured" and r["required"] is True and "영상 2편 못 받음" in r["note"]
    _manifest(temp_root, source_snapshot="1999-01-01T00:00:00+00:00")
    r = checks._logo_template_check(b.ctx, tdir)
    assert r["status"] == "unmeasured" and r["required"] is True and "stale" in r["note"]
    # a measured manifest with a template that the output reproduces -> different
    import cv2

    tiny = temp_root / "episodes" / "e" / "out.mp4"
    d = _manifest(temp_root, templates=[{"id": "logo1", "file": "logo1.png"}])
    img = np.full((40, 40), 255, np.uint8)
    img[10:30, 10:30] = 0
    cv2.imwrite(str(d / "logo1.png"), img)
    frame = np.full((96, 64, 3), 255, np.uint8)
    frame[20:40, 20:40] = 0
    from .qa_outsynth import write_frames

    write_frames(tiny, (frame for _ in range(60)), 64, 96)
    b.ctx.mp4 = tiny
    b.ctx.info = SimpleNamespace(duration=2.0, width=64, height=96, fps=30.0)
    r = checks._logo_template_check(b.ctx, tdir)
    assert r["status"] == "different" and r["observed"]["hits"]


# ============================================================================ declarations
NOT_QA_BY_DESIGN = {"text.tone.sentence_end_examples", "structure.duration_s.n", "structure.cuts_per_10s.n",
                    "structure.shot_len_s.n"}   # writing guide (meta) / sample counts (measurement metadata)


def test_every_style_key_except_meta_has_an_output_check(temp_root):
    config.sync_registry("joshuamagazine", access_logs=[])
    res = config.audit("joshuamagazine", production=False)
    assert set(res["no_qa"]) <= NOT_QA_BY_DESIGN, sorted(set(res["no_qa"]) - NOT_QA_BY_DESIGN)
    decl = {k for v in checks.declarations().values() for k in v}
    assert not (decl & NOT_QA_BY_DESIGN)
