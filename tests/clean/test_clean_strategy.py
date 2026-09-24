"""Cleaning strategy: order (clean original -> crop -> local restoration), never crop a protected region.

Overlay/face documents in the fast tests are SYNTHETIC dicts (not detections of real footage).
"""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from shortkit.clean.strategy import (CleanPolicy, _disjoint, parse_aspect, plan_clean, protected_with_margin,
                                     region_from_preset, validate_crop)

W, H = 1920, 1080
ASPECT = 1080 / 608
REAL_ROOT = Path(__file__).resolve().parents[2]


def ov(i, kind, x, y, w, h, start=0.0, end=20.0, static=True, text=None):
    return {"id": f"ov{i}", "kind": kind, "rect": {"x": x, "y": y, "w": w, "h": h}, "resolution": [W, H],
            "start": start, "end": end, "static": static, "text": text, "confidence": 0.9, "corner": None, "band": None}


def doc(overlays, text_status="measured", graphic_status="measured", sha="a" * 64):
    return {"schema": "shortkit.overlays/1", "source": {"path": "warehouse/sources/x.mp4", "sha256": sha,
                                                        "resolution": [W, H], "duration": 20.0},
            "overlays": overlays, "checks": {"text_overlays": {"status": text_status},
                                             "static_graphics": {"status": graphic_status, "reason": "test"}}}


def faces(rects, status="measured"):
    return {"status": status, "resolution": [W, H],
            "protected": [{"label": "face", "x": x, "y": y, "w": w, "h": h, "start": 0.0, "end": 20.0}
                          for x, y, w, h in rects]}


def assert_crop_safe(plan, prot_rects):
    c = plan["clean"]["crop"]
    if c is None:
        return
    for p in protected_with_margin([{"x": x, "y": y, "w": w, "h": h} for x, y, w, h in prot_rects], W, H,
                                   CleanPolicy().protected_margin_frac):
        assert c["x"] <= p["x"] + 0.5 and c["y"] <= p["y"] + 0.5
        assert c["x"] + c["w"] >= p["x"] + p["w"] - 0.5 and c["y"] + c["h"] >= p["y"] + p["h"] - 0.5, (c, p)
    assert abs(c["w"] / c["h"] / ASPECT - 1) <= 0.01


def test_crop_removes_corner_watermark_when_safe():
    d = doc([ov(1, "watermark", 16, 14, 190, 44, text="@x")])
    plan = plan_clean(d, region_aspect=ASPECT, fit="cover", faces=faces([(800, 400, 150, 150)]))
    c = plan["clean"]["crop"]
    assert c is not None and _disjoint(c, d["overlays"][0]["rect"])
    assert plan["clean"]["inpaint"] == [] and plan["decisions"][-1]["action"] == "crop"
    assert_crop_safe(plan, [(800, 400, 150, 150)])


def test_crop_never_cuts_a_face_picks_other_side():
    # a face right under the watermark: cutting the top would cut it, cutting the left side is fine
    face = (300, 50, 130, 130)
    d = doc([ov(1, "watermark", 16, 14, 190, 44)])
    plan = plan_clean(d, region_aspect=ASPECT, fit="cover", faces=faces([face]))
    assert plan["clean"]["crop"] is not None
    assert plan["clean"]["crop"]["x"] >= 16 + 190            # cut from the left
    assert_crop_safe(plan, [face])


def test_face_in_every_direction_forces_local_restoration():
    face_top_left = (0, 60, 140, 140)       # blocks the top cut (y) and the left cut (x) of the watermark
    d = doc([ov(1, "watermark", 150, 14, 190, 44)])
    plan = plan_clean(d, region_aspect=ASPECT, fit="cover", faces=faces([face_top_left, (1500, 800, 200, 200)]))
    assert plan["clean"]["crop"] is None
    assert len(plan["clean"]["inpaint"]) == 1
    assert any(dd["action"] == "crop_rejected" for dd in plan["decisions"])


def test_faces_unmeasured_forbids_crop():
    d = doc([ov(1, "watermark", 16, 14, 190, 44)])
    plan = plan_clean(d, region_aspect=ASPECT, fit="cover", faces={"status": "unmeasured", "protected": []})
    assert plan["clean"]["crop"] is None and plan["clean"]["inpaint"]
    assert any("못 잼" in r for r in plan["rationale"])


def test_alternate_clean_original_comes_first():
    d = doc([ov(1, "watermark", 16, 14, 190, 44)])
    alt_doc = doc([], sha="b" * 64)
    alt = {"path": "warehouse/sources/alt.mp4", "sha256": "b" * 64, "warehouse_id": "yt_alt", "overlays": alt_doc,
           "faces": faces([])}
    plan = plan_clean(d, region_aspect=ASPECT, fit="cover", faces=faces([]), alternates=[alt])
    assert plan["replace_source"]["sha256"] == "b" * 64
    assert plan["clean"]["crop"] is None and not plan["clean"]["inpaint"]
    assert plan["decisions"][0]["action"] == "alternate"


def test_alternate_with_same_overlay_or_unchecked_is_not_used():
    d = doc([ov(1, "watermark", 16, 14, 190, 44)])
    dirty_alt = doc([ov(1, "watermark", 18, 15, 188, 44)], sha="c" * 64)
    unchecked = {"path": "warehouse/sources/alt2.mp4", "sha256": "d" * 64, "overlays": None}
    plan = plan_clean(d, region_aspect=ASPECT, fit="cover", faces=faces([]),
                      alternates=[{"path": "a.mp4", "sha256": "c" * 64, "overlays": dirty_alt}, unchecked])
    assert plan["replace_source"] is None
    assert any("못 잼" in r for r in plan["rationale"])


def test_restoration_choice_delogo_inpaint_blur_and_timing():
    ovs = [ov(1, "logo", 900, 500, 60, 60),                                   # small static logo, mid-frame
           ov(2, "burned_subtitle", 700, 700, 500, 60, start=2.0, end=6.0),  # mid-frame subtitle, timed
           ov(3, "source_overlay", 400, 300, 900, 400)]                      # huge -> blur
    plan = plan_clean(doc(ovs), region_aspect=ASPECT, fit="cover", faces=faces([]))
    c = plan["clean"]
    assert c["crop"] is None
    assert len(c["delogo"]) == 1 and c["delogo"][0]["start"] is None
    assert len(c["inpaint"]) == 1 and c["inpaint"][0]["start"] == 2.0 and c["inpaint"][0]["end"] == 6.0
    assert len(c["blur"]) == 1
    assert {d["action"] for d in plan["decisions"]} >= {"delogo", "inpaint", "blur"}


def test_validate_crop_rejects_face_cut_and_wrong_aspect():
    prot = [{"label": "face", "x": 100, "y": 20, "w": 120, "h": 120}]
    bad = validate_crop({"x": 0, "y": 80, "w": 1776, "h": 1000}, W, H, protected=prot, region_aspect=ASPECT, fit="cover")
    assert not bad["ok"] and any("보호" in r for r in bad["reasons"])
    wrong = validate_crop({"x": 0, "y": 0, "w": 1000, "h": 1000}, W, H, protected=[], region_aspect=ASPECT, fit="cover")
    assert not wrong["ok"]


def test_random_plans_never_cut_protected():
    rng = random.Random(1234)
    for _ in range(300):
        n_o = rng.randint(1, 4)
        ovs = []
        for i in range(n_o):
            w, h = rng.randint(40, 400), rng.randint(20, 120)
            ovs.append(ov(i + 1, rng.choice(["watermark", "burned_subtitle", "logo"]), rng.randint(0, W - w),
                          rng.randint(0, H - h), w, h))
        fr = []
        for _ in range(rng.randint(0, 4)):
            s = rng.randint(40, 300)
            fr.append((rng.randint(0, W - s), rng.randint(0, H - s), s, s))
        aspect = rng.choice([ASPECT, 16 / 9, 4 / 3, 1.0, 9 / 16])
        fit = rng.choice(["cover", "contain"])
        plan = plan_clean(doc(ovs), region_aspect=aspect, fit=fit, faces=faces(fr))
        c = plan["clean"]["crop"]
        if c is not None:
            v = validate_crop(c, W, H, protected=[{"x": x, "y": y, "w": w, "h": h} for x, y, w, h in fr],
                              region_aspect=aspect, fit=fit)
            assert v["ok"], (v, c, fr)
        # every overlay is handled by exactly one action
        handled = {d["overlay_id"] for d in plan["decisions"] if d["action"] in ("crop", "delogo", "inpaint", "blur")}
        assert handled == {o["id"] for o in ovs}


def test_plan_block_is_schema_valid():
    import jsonschema

    schema = json.loads((REAL_ROOT / "shortkit/schema/plan.schema.json").read_text())
    src_schema = dict(schema["properties"]["sources"]["items"])
    src_schema["$defs"] = schema["$defs"]
    ovs = [ov(1, "watermark", 16, 14, 190, 44), ov(2, "burned_subtitle", 700, 950, 500, 60, start=2.0, end=6.0),
           ov(3, "logo", 900, 500, 60, 60)]
    plan = plan_clean(doc(ovs), region_aspect=ASPECT, fit="cover", faces=faces([(800, 300, 150, 150)]))
    entry = {"id": "s1", "path": "warehouse/sources/x.mp4", "clean": plan["clean"], "protected": plan["protected"]}
    jsonschema.validate(entry, src_schema)


def test_region_from_preset_reads_through_tracked_get(clean_root):
    from shortkit.config import load_preset

    pr = load_preset("joshuamagazine")
    reg = region_from_preset(pr)
    assert abs(reg["aspect"] - 1080 / 608) < 1e-9 and reg["fit"] in ("cover", "contain")
    reads = pr.log.to_dict()
    assert any("shortkit/clean/strategy.py:region_from_preset" in c or "strategy.py:region_from_preset" in c
               for c in reads["canvas.video_region.w"])


def test_parse_aspect():
    assert abs(parse_aspect("1080:608") - 1080 / 608) < 1e-12
    assert parse_aspect("16/9") == 16 / 9 and parse_aspect(1.5) == 1.5


@pytest.mark.slow
def test_dirty_source_plan_keeps_every_detected_face(dirty_doc, dirty_faces):
    plan = plan_clean(dirty_doc, region_aspect=ASPECT, fit="cover", faces=dirty_faces)
    prot = [(p["x"], p["y"], p["w"], p["h"]) for p in dirty_faces["protected"]]
    assert dirty_faces["status"] == "measured" and prot
    assert_crop_safe(plan, prot)
    handled = {d["overlay_id"] for d in plan["decisions"] if d["action"] in ("crop", "delogo", "inpaint", "blur")}
    assert handled == {o["id"] for o in dirty_doc["overlays"]}


def test_plan_status_never_complete_when_something_is_unmeasured():
    ovs = [ov(1, "watermark", 16, 14, 190, 44)]
    ok = plan_clean(doc(ovs), region_aspect=ASPECT, fit="cover", faces=faces([]))
    assert ok["status"] == "complete"
    for d in (doc(ovs, graphic_status="unmeasured"), doc(ovs, graphic_status="partial"), doc(ovs, text_status="unmeasured")):
        p = plan_clean(d, region_aspect=ASPECT, fit="cover", faces=faces([]))
        assert p["status"] == "needs_review" and p["review_reasons"]
