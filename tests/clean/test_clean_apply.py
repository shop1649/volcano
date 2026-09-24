"""inpaint_video / apply_clean / residual verification on the dirty test source."""
from __future__ import annotations

import json

import pytest

from shortkit import paths
from shortkit.clean.apply import apply_clean, cache_path, ffmpeg_clean_filters, inpaint_video, normalize_rects
from shortkit.clean.verify import map_through_clean, overlay_times, residual_score, source_rect_to_canvas, verify_doc
from shortkit.util.media import ffmpeg, probe


def _decoded_frames(p) -> int:
    from shortkit.util.media import run

    raw = run(["ffmpeg", "-v", "error", "-i", str(p), "-map", "0:v:0", "-f", "rawvideo", "-pix_fmt", "gray",
               "-s", "16x16", "-"]).stdout
    return len(raw) // 256


def test_normalize_and_filters_pure():
    n = normalize_rects([{"x": -5.2, "y": 3.7, "w": 50.1, "h": 20, "start": 1, "end": None, "reason": "r"}], 100, 50)
    assert n == [{"x": 0, "y": 3, "w": 45, "h": 21, "start": 1.0, "end": None}]
    fc = ffmpeg_clean_filters({"crop": {"x": 10, "y": 0, "w": 80, "h": 40},
                               "delogo": [{"x": 0, "y": 0, "w": 20, "h": 10, "start": 1.0, "end": 2.0}],
                               "blur": [{"x": 30, "y": 10, "w": 20, "h": 20, "start": None, "end": None}]}, 100, 50)
    assert "delogo=x=1:y=1" in fc and "between(t,1.0000,2.0000)" in fc and "boxblur" in fc and "crop=80:40:10:0" in fc


def test_rect_mapping_pure():
    assert map_through_clean({"x": 0, "y": 0, "w": 50, "h": 50}, {"crop": {"x": 100, "y": 0, "w": 500, "h": 300}}) is None
    assert map_through_clean({"x": 120, "y": 10, "w": 50, "h": 50},
                             {"crop": {"x": 100, "y": 0, "w": 500, "h": 300}}) == {"x": 20, "y": 10, "w": 50, "h": 50}
    clip = {"src_size": (1920, 1080), "crop": None, "region": {"x": 0, "y": 656, "w": 1080, "h": 608}, "fit": "cover"}
    r = source_rect_to_canvas({"x": 0, "y": 0, "w": 192, "h": 108}, clip)
    assert abs(r["y"] - 656) < 1e-6 and abs(r["h"] - 60.8) < 0.2


@pytest.mark.slow
def test_filters_run_on_tiny_clip(clean_root):
    src = clean_root / "assets/test/generated/tiny.mp4"
    ffmpeg(["-f", "lavfi", "-i", "testsrc=size=320x180:rate=10:duration=2", "-f", "lavfi", "-i",
            "sine=frequency=440:duration=2", "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", src])
    clean = {"crop": {"x": 16, "y": 9, "w": 288, "h": 162}, "inpaint": [],
             "delogo": [{"x": 10, "y": 10, "w": 40, "h": 20, "start": 0.5, "end": 1.5}],
             "blur": [{"x": 200, "y": 100, "w": 60, "h": 40, "start": None, "end": None}]}
    res = apply_clean(src, clean, clean_root / "assets/test/generated/tiny_clean.mp4", threads=1)
    info = probe(paths.absp(res["out"]))
    assert (info.width, info.height) == (288, 162) and info.has_audio


@pytest.mark.slow
def test_inpaint_removes_watermark_and_subtitle(dirty_doc, dirty_short, clean_root):
    ovs = {o["kind"]: o for o in dirty_doc["overlays"]}
    wm, sub = ovs["watermark"], ovs["burned_subtitle"]
    rects = [{**wm["rect"], "start": None, "end": None}, {**sub["rect"], "start": sub["start"], "end": sub["end"]}]
    t_wm = [1.0, 4.0, 7.0]
    t_sub = overlay_times(sub, 3)
    # before: both overlays are present in the source
    before_wm = residual_score(dirty_short, wm["rect"], wm["template"], t_wm, wm["text"])
    before_sub = residual_score(dirty_short, sub["rect"], sub["template"], t_sub, sub["text"])
    assert before_wm["residual"] is True and before_sub["residual"] is True
    src_info = probe(dirty_short)
    n_frames = _decoded_frames(dirty_short)   # stream-copy trim keeps a few frames past 8 s
    out = cache_path(dirty_short, rects)
    res = inpaint_video(dirty_short, rects, out, threads=2)
    assert res["frames"] == n_frames and res["audio"] == "copy"
    assert res["per_rect"][0]["telea"] == res["frames"]           # whole-clip static mark: spatial restoration
    assert res["per_rect"][1]["frames"] == pytest.approx((sub["end"] - sub["start"]) * 30, abs=2)
    assert res["per_rect"][1]["plate"] > 0                          # static background: clean plate used
    after_wm = residual_score(out, wm["rect"], wm["template"], t_wm, wm["text"])
    after_sub = residual_score(out, sub["rect"], sub["template"], t_sub, sub["text"])
    assert after_wm["residual"] is False and after_sub["residual"] is False, (after_wm, after_sub)
    info = probe(out)
    assert info.has_audio and (info.width, info.height) == (1920, 1080) and abs(info.duration - src_info.duration) < 0.1
    # cache hit + stored metadata has no absolute paths
    assert inpaint_video(dirty_short, rects, out, threads=2)["cached"] is True
    meta = json.loads(out.with_name(out.name + ".json").read_text())
    assert meta["out"].startswith("warehouse/cache/clean/") and "/tmp/" not in json.dumps(meta)


@pytest.mark.slow
def test_apply_clean_crop_plus_inpaint_verified(dirty_doc, dirty_short, clean_root):
    from shortkit.clean.strategy import plan_clean

    face = {"status": "measured", "resolution": [1920, 1080],
            "protected": [{"label": "face", "x": 480, "y": 480, "w": 120, "h": 120, "start": 0, "end": 20}]}
    plan = plan_clean(dirty_doc, region_aspect=1080 / 608, fit="cover", faces=face)
    clean = plan["clean"]
    assert clean["crop"] is not None and clean["inpaint"]
    out = clean_root / "assets/test/generated/dirty_first8_clean.mp4"
    res = apply_clean(dirty_short, clean, out, threads=2)
    info = probe(out)
    assert (info.width, info.height) == (clean["crop"]["w"], clean["crop"]["h"]) and info.has_audio
    d8 = dict(dirty_doc)
    d8["overlays"] = [dict(o, end=min(o["end"], 8.0)) for o in dirty_doc["overlays"]]
    ver = verify_doc(out, d8, clean=clean)
    assert not ver["residual_any"] and not ver["unmeasured"], ver
    assert {r["how"] for r in ver["rows"]} == {"removed_by_crop", "pixels"}
    assert res["steps"][0]["op"] == "inpaint"
