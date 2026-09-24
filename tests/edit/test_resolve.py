"""Resolve timing math, geometry and IR round-trip."""
from __future__ import annotations

import pytest

from .conftest import load_preset, write_plan


def ctx_for(root, plan):
    from shortkit.edit.resolve import resolve_context

    write_plan(root, plan)
    return resolve_context(plan, load_preset())


def test_output_timing_speed_freeze_crossfade(root, plan):
    plan["timeline"][0]["speed"] = 0.5            # 2.0 s of source -> 4.0 s
    c = ctx_for(root, plan)
    assert not c.errors, c.errors
    s1, s2, s3 = c.resolved.clips
    assert (s1.out_start, s1.out_end) == (0.0, 4.0)
    assert s2.out_start == 4.0 and s2.freeze.out_start == pytest.approx(5.0) and s2.out_end == pytest.approx(5.5)
    assert s2.transition_in.type == "flash" and s2.transition_in.dur == pytest.approx(0.12)   # preset default
    assert s3.out_start == pytest.approx(5.5 - 0.25) and s3.out_end == pytest.approx(5.25 + 2.5)
    assert c.resolved.duration == pytest.approx(7.75)


def test_mid_freeze_src_t(root, plan):
    plan["timeline"][1]["freeze"] = {"at": "src_t", "src_t": 3.0, "hold": 0.4}
    c = ctx_for(root, plan)
    from shortkit.edit.resolve import src_time_at, src_to_out_time

    s2 = c.resolved.clips[1]
    assert s2.freeze.out_start == pytest.approx(2.0 + 0.5)
    assert s2.out_end == pytest.approx(2.0 + 1.0 + 0.4)
    assert src_time_at(s2, 0.25) == pytest.approx(2.75)
    assert src_time_at(s2, 0.6) == pytest.approx(3.0)          # holding
    assert src_time_at(s2, 1.0) == pytest.approx(3.1)          # continues after the hold
    assert src_to_out_time(s2, 3.2) == pytest.approx(2.0 + 0.7 + 0.4)


def test_preset_defaults_for_zoom_and_transitions(root, plan):
    plan["timeline"][0]["zoom"] = {"center": [160, 90], "start": 0.5}
    del plan["timeline"][2]["transition_in"]["dur"]
    c = ctx_for(root, plan)
    z = c.resolved.clips[0].zoom
    pr = load_preset()
    assert z.scale_to == pr.get("motion.zoom.scale_to") and z.dur == pr.get("motion.zoom.dur_s")
    assert z.ease == pr.get("motion.zoom.ease")
    assert c.resolved.clips[2].transition_in.dur == pr.get("motion.transitions.crossfade.dur_s")


def test_zoom_is_smooth_and_eased(root, plan):
    from shortkit.edit.resolve import ease, src_to_region, zoom_scale

    plan["timeline"][0]["zoom"] = {"center": [160, 90], "start": 0.5, "dur": 0.4, "ease": "inout", "scale_to": 1.5}
    clip = ctx_for(root, plan).resolved.clips[0]
    us = [i / 300 for i in range(0, 600)]
    zs = [zoom_scale(clip, u) for u in us]
    assert zs[0] == 1.0 and zs[-1] == pytest.approx(1.5)
    assert all(b >= a - 1e-12 for a, b in zip(zs, zs[1:]))                    # monotonic
    assert max(abs(b - a) for a, b in zip(zs, zs[1:])) < 0.02                 # no jumps at 300 Hz
    assert ease(0.5, "inout") == pytest.approx(0.5) and ease(0.5, "out") > 0.5 > ease(0.5, "in")
    # the zoom centre stays fixed on screen
    s0, tx0, ty0 = src_to_region(clip, 0.0)
    s1, tx1, ty1 = src_to_region(clip, 2.0)
    p0 = (tx0 + s0 * 160, ty0 + s0 * 90)
    p1 = (tx1 + s1 * 160, ty1 + s1 * 90)
    assert p0 == pytest.approx(p1)
    assert s1 / s0 == pytest.approx(1.5)


def test_region_fit_cover_and_mapping(root, plan):
    from shortkit.edit.resolve import base_fit, map_src_rect

    c = ctx_for(root, plan)
    clip = c.resolved.clips[0]
    assert (clip.region.x, clip.region.y, clip.region.w, clip.region.h) == (0, 656, 1080, 608)
    s, ox, oy = base_fit(clip)
    assert s == pytest.approx(max(1080 / 320, 608 / 180))
    m = map_src_rect(clip, 0.0, {"x": 0, "y": 0, "w": 320, "h": 180})
    assert m == pytest.approx((0, 656, 1080, 608), abs=0.01)     # cover fills the region, clipped to it


def test_crop_changes_fit(root, plan):
    from shortkit.edit.resolve import base_fit

    plan["sources"][0]["clean"]["crop"] = {"x": 0, "y": 30, "w": 320, "h": 120}
    clip = ctx_for(root, plan).resolved.clips[0]
    s, ox, oy = base_fit(clip)
    assert s == pytest.approx(max(1080 / 320, 608 / 120))


def test_inpaint_without_clean_module_is_an_error(root, plan, monkeypatch):
    import builtins

    real = builtins.__import__

    def fake(name, *a, **k):
        if name.endswith("clean.apply") or (a and a[2] and "apply" in (a[2] or ()) and "clean" in name):
            raise ImportError("simulated")
        return real(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake)
    plan["sources"][0]["clean"]["inpaint"] = [{"x": 1, "y": 1, "w": 20, "h": 10}]
    c = ctx_for(root, plan)
    assert "inpaint_unavailable" in {i["code"] for i in c.errors}


def test_ir_roundtrip_and_paths_relative(root, plan):
    from shortkit.edit.ir import ResolvedEdit
    from shortkit.edit.resolve import resolve_episode

    write_plan(root, plan)
    r = resolve_episode("t1")
    d = r.to_dict()
    r2 = ResolvedEdit.from_dict(d)
    assert r2.to_dict() == d
    import json

    txt = json.dumps(d, ensure_ascii=False)
    assert str(root) not in txt                  # no absolute paths stored
    b = root / "episodes/t1/build"
    for f in ("resolved.json", "captions.ass", "preset_access.json", "caption_layout.json"):
        assert (b / f).is_file()
    acc = json.loads((b / "preset_access.json").read_text())
    # every key under text.roles.<role> the renderer supports is read through the preset
    for k in ("size_px", "line_spacing", "outline_px", "box.alpha", "motion_in.scale_from", "timing.lead_s",
              "shadow_color", "bold", "persist", "max_chars_per_line"):
        assert f"text.roles.situation.{k}" in acc["reads"], k
    callers = acc["reads"]["text.roles.situation.size_px"]
    # (outside the repo root config.py reports only the file name)
    assert callers and all(c.split("/")[-1].startswith("resolve.py:read_role_style") for c in callers), callers
    assert r.provisional_keys and "canvas.width" in r.provisional_keys


def test_resolve_episode_refuses_errors(root, plan):
    from shortkit.edit.resolve import ResolveError, resolve_episode

    plan["sfx"][0]["event"]["kind"] = "cut"
    write_plan(root, plan)
    with pytest.raises(ResolveError) as e:
        resolve_episode("t1")
    assert "sfx_cut_event" in {i["code"] for i in e.value.issues}
    assert not (root / "episodes/t1/build/resolved.json").exists()


def test_whole_video_title_and_dialogue_quotes(root, plan):
    plan["captions"][0]["end"] = 1.0
    plan["captions"].append({"id": "c_d", "role": "dialogue", "text": "안녕", "start": 2.2, "end": 3.0,
                             "grounding": {"kind": "heard"}})
    r = ctx_for(root, plan).resolved
    t = next(c for c in r.captions if c.role == "title")
    assert t.end == pytest.approx(r.duration)          # persist: whole_video
    d = next(c for c in r.captions if c.role == "dialogue")
    q = load_preset().get("text.roles.dialogue.quote_marks")
    assert d.text == f"{q[0]}안녕{q[1]}"


@pytest.mark.slow
def test_inpaint_produces_cleaned_intermediate(root, plan):
    """clean.inpaint -> shortkit.clean.apply.inpaint_video -> warehouse/cache/clean/, clip points at it."""
    pytest.importorskip("shortkit.clean.apply")
    from shortkit.edit.resolve import resolve_episode

    plan["sources"][0]["clean"]["inpaint"] = [{"x": 10, "y": 10, "w": 50, "h": 20, "start": 0.0, "end": 4.0}]
    plan["timeline"] = plan["timeline"][:1]
    plan["captions"] = plan["captions"][1:]
    write_plan(root, plan)
    r = resolve_episode("t1")
    c = r.clips[0]
    # the cleaner's own cache naming (warehouse/cache/clean/<source sha256>_<ops hash>.mp4), not an ad-hoc name
    from shortkit import paths
    from shortkit.clean.apply import cache_path

    exp = paths.relp(cache_path(root / plan["sources"][0]["path"], plan["sources"][0]["clean"]["inpaint"]))
    assert c.source_path == exp and exp.startswith(f"warehouse/cache/clean/{plan['sources'][0]['sha256']}_")
    assert (root / c.source_path).is_file() and (root / (c.source_path + ".json")).is_file()
    assert c.inpaint and c.inpaint[0].w == 50
    # a second resolve reuses the cached intermediate (same path, file untouched)
    mtime = (root / c.source_path).stat().st_mtime_ns
    assert resolve_episode("t1").clips[0].source_path == exp and (root / exp).stat().st_mtime_ns == mtime
