"""Values that used to be hard-coded in the renderer are preset keys read through the preset
(arrow geometry, flash scope, blur strength, zoom recenter); library-root tokens; IR compatibility."""
from __future__ import annotations

import json
import math

import numpy as np
import pytest
import yaml

from conftest import codes, load_preset, set_preset, write_plan


def _resolve(root, plan):
    from shortkit.edit.resolve import resolve_episode

    write_plan(root, plan)
    r = resolve_episode("t1")
    acc = json.loads((root / "episodes/t1/build/preset_access.json").read_text())["reads"]
    return r, acc


# ----------------------------------------------------------------------------- preset keys
def test_new_render_keys_are_read_through_the_preset(root, plan):
    plan["timeline"][0]["zoom"] = {"center": [160, 90], "start": 0.2}
    plan["decorations"] = [{"id": "d1", "kind": "arrow", "start": 0.5, "end": 1.5,
                            "keyframes": [{"t": 0.0, "x": 300, "y": 900}]}]
    r, acc = _resolve(root, plan)
    for k in ("decorations.arrow.head_len_ratio", "decorations.arrow.head_width_ratio",
              "decorations.arrow.shaft_width_ratio", "motion.transitions.flash.scope", "motion.zoom.recenter",
              "render.clean.blur_sigma_ratio", "audio.loudness.max_limiter_db"):
        assert k in acc and acc[k], k
    pr = load_preset()
    assert r.clips[0].blur_sigma_ratio == pr.get("render.clean.blur_sigma_ratio")
    assert r.clips[1].transition_in.scope == pr.get("motion.transitions.flash.scope")
    assert r.clips[0].zoom.recenter is pr.get("motion.zoom.recenter")
    st = r.decorations[0].style
    assert st["head_len_ratio"] == pr.get("decorations.arrow.head_len_ratio")
    # unmeasured style keys show up as provisional (못 잼); the limiter rule does not
    # render.clean.blur_sigma_ratio is a render parameter of our cleaning step (category rule, not provisional)
    assert "motion.zoom.recenter" in r.provisional_keys and "render.clean.blur_sigma_ratio" not in r.provisional_keys
    assert pr.origin("render.clean.blur_sigma_ratio") == "rule"
    assert "audio.loudness.max_limiter_db" not in r.provisional_keys


def test_arrow_geometry_follows_preset(root, plan):
    from shortkit.edit.captions import deco_shape

    plan["decorations"] = [{"id": "d1", "kind": "arrow", "start": 0.5, "end": 1.5,
                            "keyframes": [{"t": 0.0, "x": 300, "y": 900}]}]
    set_preset(root, "decorations.arrow.head_len_ratio", 0.3)
    r, _ = _resolve(root, plan)
    d = r.decorations[0]
    polys, tip = deco_shape("arrow", d.keyframes[0], d.style)
    L = float(load_preset().get("decorations.arrow.size_px"))
    ys = sorted({round(y, 3) for _, y in polys[0]})
    assert tip == (300.0, 900.0) and ys[0] == pytest.approx(900 - L) and 900 - 0.3 * L in ys
    with pytest.raises(ValueError):
        deco_shape("arrow", d.keyframes[0], {k: v for k, v in d.style.items() if k != "shaft_width_ratio"})
    p = root / "presets/joshuamagazine/preset.yaml"
    y = yaml.safe_load(p.read_text())
    del y["decorations"]["arrow"]["head_width_ratio"]
    p.write_text(yaml.safe_dump(y, allow_unicode=True, sort_keys=False))
    from shortkit.edit.validate import validate

    assert "deco_key_missing" in codes(validate(plan, load_preset()), "error")


@pytest.mark.parametrize("scope", ["region", "canvas"])
def test_flash_scope(root, plan, scope):
    from shortkit.edit.render import Compositor

    set_preset(root, "motion.transitions.flash.scope", scope)
    r, _ = _resolve(root, plan)
    c2 = r.clips[1]
    assert c2.transition_in.type == "flash" and c2.transition_in.scope == scope
    comp = Compositor(r)
    try:
        fr = comp.frame(int(round(c2.out_start * r.canvas["fps"])))       # flash peak (alpha 1)
    finally:
        comp.close()
    vr = r.canvas["video_region"]
    assert fr[int(vr["y"] + vr["h"] / 2), int(vr["w"] / 2)].min() > 240           # region always flashes
    outside = fr[int(vr["y"]) - 100, 20]
    assert (outside.min() > 240) if scope == "canvas" else (outside.max() < 20)
    set_preset(root, "motion.transitions.flash.scope", "everywhere")
    from shortkit.edit.validate import validate

    assert "flash_scope" in codes(validate(plan, load_preset()), "error")


def test_blur_strength_from_ir(root, plan):
    from shortkit.edit import render

    plan["sources"][0]["clean"]["blur"] = [{"x": 10, "y": 10, "w": 60, "h": 30}]
    set_preset(root, "render.clean.blur_sigma_ratio", 0.25)
    r, _ = _resolve(root, plan)
    c = r.clips[0]
    assert c.blur_sigma_ratio == 0.25 and render.blur_sigma_src(c, c.blur[0]) == pytest.approx(15.0)
    c.blur_sigma_ratio = None                                          # an IR resolved before the key existed
    with pytest.raises(render.RenderError):
        render.blur_sigma_src(c, c.blur[0])


def test_zoom_recenter(root, plan):
    from shortkit.edit.resolve import ease, src_to_region

    plan["timeline"][0]["zoom"] = {"center": [170, 90], "start": 0.2, "dur": 0.5, "scale_to": 1.25}
    r, _ = _resolve(root, plan)
    c = r.clips[0]
    R = c.region

    def where(u):
        s, tx, ty = src_to_region(c, u)
        return s * 170 + tx, s * 90 + ty
    fixed = where(0.0)
    assert where(0.45) == pytest.approx(fixed) and where(2.0) == pytest.approx(fixed)   # recenter false (preset)
    c.zoom.recenter = True
    assert where(0.0) == pytest.approx(fixed)
    assert where(1.0) == pytest.approx((R.w / 2, R.h / 2))                              # ends at the region centre
    mid = where(0.45)
    w = ease(0.5, c.zoom.ease)
    assert mid == pytest.approx((fixed[0] + (R.w / 2 - fixed[0]) * w, fixed[1] + (R.h / 2 - fixed[1]) * w))
    # cover fit: the zoomed picture keeps covering the region even when the centre is near an edge
    c.zoom.center_src = (5.0, 5.0)
    s, tx, ty = src_to_region(c, 1.0)
    assert tx <= 1e-9 and ty <= 1e-9 and tx + s * c.src_size[0] >= R.w - 1e-6 and ty + s * c.src_size[1] >= R.h - 1e-6


def test_ease_curves_are_cubic():
    from shortkit.edit.resolve import ease

    assert ease(0.5, "in") == pytest.approx(0.125) and ease(0.5, "out") == pytest.approx(0.875)
    assert ease(0.25, "inout") == pytest.approx(4 * 0.25 ** 3) and ease(0.75, "inout") == pytest.approx(1 - 0.5 ** 3 / 2)
    assert ease(0.3, "linear") == pytest.approx(0.3)


# ----------------------------------------------------------------------------- IR compatibility
def test_ir_new_fields_and_old_files(root, plan):
    from shortkit.edit.ir import ResolvedEdit

    plan["captions"].append({"id": "c_k", "role": "speaker", "text": "사람", "start": 0.5, "end": 1.5, "pos": [540, 1500],
                             "grounding": {"kind": "seen", "source": "a", "src_t": 1.0}})
    plan["timeline"][0]["zoom"] = {"center": [160, 90], "start": 0.2}
    r, _ = _resolve(root, plan)
    pr = load_preset()
    cap = next(c for c in r.captions if c.id == "c_s")
    assert cap.line_spacing == pr.get("text.roles.situation.line_spacing")
    assert cap.shadow_color == pr.get("text.roles.situation.shadow_color") and cap.weight >= 600
    assert len(cap.lines_pos) == len(cap.lines) and all(len(p) == 2 for p in cap.lines_pos)
    assert r.audio.bgm.loop is False and r.audio.max_limiter_db == pr.get("audio.loudness.max_limiter_db")
    spk = next(c for c in r.captions if c.id == "c_k")
    x, y, w, h = spk.box["rect"]                               # box = libass ink bbox + pad (integer px)
    assert all(float(v).is_integer() for v in (x, y, w, h))
    assert x == spk.bbox.x - round(spk.box["pad_x"]) and w == spk.bbox.w + 2 * round(spk.box["pad_x"])
    d = json.loads(json.dumps(r.to_dict()))
    assert ResolvedEdit.from_dict(d).to_dict() == r.to_dict()
    # an old resolved.json (before these optional fields) still loads, with defaults
    for c in d["clips"]:
        c.pop("blur_sigma_ratio", None)
        c["transition_in"].pop("scope", None)
        if c.get("zoom"):
            c["zoom"].pop("recenter", None)
    for c in d["captions"]:
        for k in ("line_spacing", "shadow_color", "weight", "lines_pos"):
            c.pop(k, None)
    d["audio"]["bgm"].pop("loop", None)
    d["audio"].pop("max_limiter_db", None)
    d["audio"].pop("loudness_tolerance_lu", None)
    old = ResolvedEdit.from_dict(d)
    assert old.clips[1].transition_in.scope == "region" and old.clips[0].zoom.recenter is False
    assert old.captions[0].lines_pos == [] and old.captions[0].weight is None and old.audio.bgm.loop is False
    assert old.audio.max_limiter_db is None and old.clips[0].blur_sigma_ratio is None


# ----------------------------------------------------------------------------- library tokens
def test_sfx_library_token(root):
    from shortkit.edit import sfxmap

    lib = root / "assets/library/sfx"
    lib.mkdir(parents=True)
    (lib / "w.wav").write_bytes(b"RIFF")
    (root / "local.yaml").write_text(yaml.safe_dump({"sfx_library_root": str(lib)}))
    p = root / "presets/joshuamagazine/sfx_map.yaml"
    p.write_text("preset_id: joshuamagazine-v1\nlibrary_root: $sfx_library_root\ntypes:\n"
                 "  whoosh: {status: have, file: $sfx_library_root/w.wav}\n  boom: {status: have, file: w.wav}\n")
    pr = load_preset()
    assert sfxmap.lookup(pr, "whoosh")["file"] == "assets/library/sfx/w.wav"
    assert sfxmap.lookup(pr, "boom")["file"] == "assets/library/sfx/w.wav"        # relative to a token root
    (root / "local.yaml").write_text("{}\n")                                     # token root not configured
    assert sfxmap.lookup(pr, "whoosh")["file"] is None and sfxmap.lookup(pr, "whoosh")["note"]


def test_music_library_token_and_track_id_entries(root, plan):
    import shutil

    from shortkit.edit.audio import lookup_track

    lib = root / "assets/library/music_user"
    lib.mkdir(parents=True)
    shutil.copy(root / "assets/test/generated/edit_fixture/bgm.wav", lib / "song.wav")
    (root / "local.yaml").write_text(yaml.safe_dump({"music_library_root": str(lib)}))
    # README.md format: a list of entries keyed track_id, file relative to the library folder
    (lib / "index.yaml").write_text("tracks:\n  - {track_id: song_orig, file: song.wav, title: 합성, version: original}\n"
                                    "  - {track_id: song_tok, file: $music_library_root/song.wav, version: original}\n")
    assert lookup_track("song_orig")[0] == "assets/library/music_user/song.wav"
    assert lookup_track("song_tok")[0] == "assets/library/music_user/song.wav"
    assert lookup_track("song_orig")[1]["title"] == "합성"
    assert lookup_track("nope") == (None, {})
    # the preset track id resolves through the same lookup
    set_preset(root, "audio.bgm.track_id", "song_orig")
    plan["bgm"] = {"enabled": True, "path": None, "silences": []}
    r, _ = _resolve(root, plan)
    assert r.audio.bgm.path == "assets/library/music_user/song.wav" and r.audio.bgm.track_id == "song_orig"
