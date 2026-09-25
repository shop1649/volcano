"""Production-measurement basis (latest-100 members only), channel-level presence items, measured per-video
count limits, native-resolution coordinates with an explicit target canvas, and region evidence times
(review findings S1-03, S1-07, S1-09, S1-12, S1-18).  All analysis files are SYNTHETIC."""
from __future__ import annotations

import json

import pytest

from shortkit.reference import aggregate as A
from shortkit.reference import manual as MAN
from shortkit.util.jsonio import append_jsonl, write_json

from test_rv_classify_aggregate import make_video, write_snapshot

P = "presets/joshuamagazine"


def _items(root) -> dict:
    out = {}
    for f in (root / P / "measurements").glob("*.json"):
        for it in json.loads(f.read_text("utf-8"))["items"]:
            out[it["key"]] = it
    return out


def test_aggregate_uses_only_snapshot_members(proj):
    """S1-03: an analysed high-view video outside the snapshot (title 200 px) must not move the p50 (80 px)."""
    make_video(proj, "s0000xxxxxx", 30, 2.0)
    make_video(proj, "s0120xxxxxx", 30, 2.0)
    for vid, size in (("s0000xxxxxx", 40), ("s0120xxxxxx", 100)):      # 540x960 -> x2 on the canvas
        lay = json.loads((proj / P / "analysis" / vid / "layout.json").read_text("utf-8"))
        lay["roles"]["title"]["size_px"] = size
        write_json(proj / P / "analysis" / vid / "layout.json", lay)
    write_snapshot(proj, [("s0000xxxxxx", 10)])
    write_json(proj / P / "reference/high_views.json", {"status": "ok", "videos": [
        {"video_id": "s0120xxxxxx", "view_count": 2_000_000, "in_latest100": False}], "unverified": []})
    r = A.aggregate("joshuamagazine")
    it = _items(proj)["text.roles.title.size_px"]
    assert it["status"] == "measured" and it["value"] == 80.0 and it["overall"]["n"] == 1
    assert [e["video_id"] for e in it["evidence"]] == ["s0000xxxxxx"]
    assert r["excluded_non_snapshot"] == ["s0120xxxxxx"]
    basis = json.loads((proj / P / "measurements/visual_text.json").read_text("utf-8"))["basis"]
    assert basis["excluded_non_snapshot"] == ["s0120xxxxxx"] and basis["video_ids"] == ["s0000xxxxxx"]
    # an explicit --set high_views run cannot smuggle the outside video in either
    A.aggregate("joshuamagazine", ids=["s0120xxxxxx"])
    assert _items(proj)["text.roles.title.size_px"]["status"] == "unmeasured"


def test_manual_observations_outside_snapshot_are_ignored(proj):
    """S1-03: manual-aggregate accepted high_views videos; only snapshot members count now."""
    write_snapshot(proj, [("s0000xxxxxx", 10)])
    write_json(proj / P / "reference/high_views.json", {"status": "ok", "videos": [
        {"video_id": "s0120xxxxxx", "view_count": 2_000_000, "kind": "short"}], "unverified": []})
    (proj / P / "manual_observations.csv").write_text(
        "video_id,t,key,value,observed_by,watched,note\n"
        "s0120xxxxxx,1.0,text.tone.emoji,yes,tester,yes,SYNTHETIC\n", encoding="utf-8")
    MAN.aggregate_manual("joshuamagazine")
    man = json.loads((proj / P / "measurements/manual.json").read_text("utf-8"))
    it = next(i for i in man["items"] if i["key"] == "text.tone.emoji")
    assert it["status"] == "unmeasured"
    assert man["rows_ignored"][0]["video_id"] == "s0120xxxxxx" and "스냅샷" in man["rows_ignored"][0]["reason"]


def _presence_videos(proj):
    """3 SYNTHETIC members with known per-video tri-states."""
    ids = ["p1", "p2", "p3"]
    write_snapshot(proj, [(v, 10) for v in ids])
    for v in ids:
        make_video(proj, v, 30, 2.0)
    # p1: zoom present, freeze absent (make_video default); p2: zoom absent + freeze present x3; p3: no motion.json
    m2 = json.loads((proj / P / "analysis/p2/motion.json").read_text("utf-8"))
    m2["events"] = [{"t": t, "end": t + 0.6, "type": "freeze", "hold_s": 0.6, "value": 0.6} for t in (3.0, 9.0, 15.0)]
    m2["presence"] = {"zoom": "absent", "freeze": "present", "speed": "unmeasured", "flash": "present"}
    write_json(proj / P / "analysis/p2/motion.json", m2)
    (proj / P / "analysis/p3/motion.json").unlink()
    write_json(proj / P / "formats.yaml", {"status": "measured", "assignments": {"p1": "F1", "p2": "F1", "p3": "F2"}})
    return ids


def test_channel_presence_items_are_tri_state_with_counts(proj):
    """S1-07: presence.* items with overall + by_format n / n_present / share; unmeasured with a blocker."""
    _presence_videos(proj)
    A.aggregate("joshuamagazine")
    it = _items(proj)
    z = it["presence.zoom"]
    assert z["status"] == "measured" and z["value"] == "present"
    assert z["overall"] == {"n": 2, "n_present": 1, "n_absent": 1, "n_unmeasured": 1, "share": 0.5, "value": "present"}
    assert z["by_format"]["F1"]["n"] == 2 and z["by_format"]["F2"]["n"] == 0 and z["by_format"]["F2"]["value"] is None
    assert z["evidence"][0] == {"video_id": "p1", "t": 2.0, "value": "present", "frame": None}
    fz = it["presence.freeze"]
    assert fz["value"] == "present" and fz["overall"]["n_present"] == 1 and fz["overall"]["n_absent"] == 1
    cf = it["presence.crossfade"]                       # make_video: shots presence crossfade absent (3 videos)
    assert cf["value"] == "absent" and cf["overall"]["n"] == 3 and cf["overall"]["share"] == 0.0
    sp = it["presence.speed_change"]                    # frame-duplication detector: never 'absent'
    assert sp["status"] == "unmeasured" and sp["value"] is None and sp["blocker"]
    dec = it["presence.decorations"]                    # experimental detector cannot confirm absence
    assert dec["status"] == "unmeasured" and "사람 관찰" in dec["blocker"]
    for k in A.PRESENCE_VISUAL_KEYS:
        assert k in it and it[k]["unit"] == "tri_state"


def test_presence_decorations_from_watched_observation(proj):
    _presence_videos(proj)
    (proj / P / "manual_observations.csv").write_text(
        "video_id,t,key,value,observed_by,watched,note\n"
        "p2,4.5,decorations.arrow.color,#FF0000,tester,yes,SYNTHETIC\n", encoding="utf-8")
    A.aggregate("joshuamagazine")
    dec = _items(proj)["presence.decorations"]
    assert dec["status"] == "measured" and dec["value"] == "present" and dec["evidence"][0]["t"] == 4.5


def test_presence_all_unmeasured_without_snapshot(proj):
    write_json(proj / P / "reference/latest100.json", {"status": "blocked", "blocker": "SYNTHETIC 403",
                                                       "captured_at": "2026-09-24T00:00:00+00:00", "videos": []})
    A.aggregate("joshuamagazine")
    for k in A.PRESENCE_VISUAL_KEYS:
        it = _items(proj)[k]
        assert it["status"] == "unmeasured" and "SYNTHETIC 403" in it["blocker"], k


def test_freeze_count_and_consecutive_zoom_are_measured_p90(proj):
    """S1-12: motion.freeze.max_per_video = p90 of per-video freeze counts; motion.zoom.max_consecutive = p90 of
    the longest run of consecutive shots that zoom."""
    ids = [f"z{i}" for i in range(5)]
    write_snapshot(proj, [(v, 10) for v in ids])
    runs = [0, 1, 1, 2, 3]
    for i, v in enumerate(ids):
        make_video(proj, v, 30, 2.0)
        sh = {"video_id": v, "resolution": [540, 960], "duration": 30.0, "presence": {"cut": "present"},
              "cuts": [{"t": float(t), "type": "cut", "score": 0.9} for t in range(3, 30, 3)]}   # shots [0,3) [3,6) ...
        write_json(proj / P / "analysis" / v / "shots.json", sh)
        zooms = [{"t": 3.0 * k + 0.5, "end": 3.0 * k + 1.0, "type": "zoom_in", "scale_to": 1.2, "dur_s": 0.5}
                 for k in range(runs[i])]
        if i == 4:
            zooms.append({"t": 20.0, "end": 20.5, "type": "zoom_in", "scale_to": 1.2, "dur_s": 0.5})   # separate run
        fz = [{"t": 25.0 + 0.1 * k, "end": 25.5, "type": "freeze", "hold_s": 0.5} for k in range(i)]
        write_json(proj / P / "analysis" / v / "motion.json", {
            "video_id": v, "resolution": [540, 960], "duration": 30.0, "events": zooms + fz,
            "presence": {"zoom": "present" if zooms else "absent", "freeze": "present" if fz else "absent",
                         "speed": "unmeasured", "flash": "absent"}})
    A.aggregate("joshuamagazine")
    it = _items(proj)
    import numpy as np
    zc = it["motion.zoom.max_consecutive"]
    assert zc["status"] == "measured" and zc["value_rule"] == "p90" and zc["overall"]["n"] == 5
    assert zc["value"] == int(round(float(np.percentile(runs, 90))))
    ev = {e["video_id"]: e for e in zc["evidence"]}
    assert ev["z0"]["value"] == 0 and ev["z4"]["value"] == 3
    fr = it["motion.freeze.max_per_video"]
    assert fr["status"] == "measured" and fr["value"] == int(round(float(np.percentile([0, 1, 2, 3, 4], 90))))
    assert fr["overall"]["n"] == 5 and fr["unit"] == "count"


def test_count_limits_unmeasured_without_presence(proj):
    write_snapshot(proj, [("q1", 10)])
    make_video(proj, "q1", 30, 2.0)
    m = json.loads((proj / P / "analysis/q1/motion.json").read_text("utf-8"))
    m["presence"] = {}
    write_json(proj / P / "analysis/q1/motion.json", m)
    A.aggregate("joshuamagazine")
    it = _items(proj)
    assert it["motion.freeze.max_per_video"]["status"] == "unmeasured"
    assert it["motion.zoom.max_consecutive"]["status"] == "unmeasured"


def test_coordinates_keep_native_resolution_and_scale_to_measured_canvas(proj):
    """S1-09: when canvas.width/height are measured (720x1280 downloads) coordinates are scaled to THAT canvas,
    with the native values kept and scaled_to recorded."""
    ids = ["c1", "c2"]
    write_snapshot(proj, [(v, 10) for v in ids])
    for v in ids:
        make_video(proj, v, 30, 2.0)                   # analysis at 540x960, title size 40, region y=300
        append_jsonl(proj / P / "reference/downloads.jsonl",
                     {"video_id": v, "path": f"{P}/reference/videos/{v}.mp4", "sha256": "0" * 64, "format_id": "136+140",
                      "width": 720, "height": 1280, "fps": 30.0, "requested_format": "bv*+ba/b sort=res:1080"})
    A.aggregate("joshuamagazine")
    it = _items(proj)
    assert it["canvas.width"]["value"] == 720 and it["canvas.height"]["value"] == 1280
    t = it["text.roles.title.size_px"]
    assert t["resolution"] == [720, 1280] and t["scaled_to"]["source"] == "measured"
    assert t["value"] == pytest.approx(40 * 1280 / 960, abs=0.01)
    assert t["native"]["by_resolution"]["540x960"]["p50"] == 40
    y = it["canvas.video_region.y"]
    assert y["value"] == 400 and y["native"]["by_resolution"]["540x960"]["p50"] == 300
    sm = it["canvas.safe_margin.top"]
    assert sm["scaled_to"]["resolution"] == [720, 1280] and "540x960" in sm["native"]["by_resolution"]
    basis = json.loads((proj / P / "measurements/visual_canvas.json").read_text("utf-8"))["basis"]
    assert basis["scaled_to"]["source"] == "measured" and basis["canvas_resolution"] == [720, 1280]


def test_coordinates_scaled_to_preset_canvas_when_canvas_unmeasured(proj):
    write_snapshot(proj, [("d1", 10)])
    make_video(proj, "d1", 30, 2.0)
    A.aggregate("joshuamagazine")
    t = _items(proj)["text.roles.title.size_px"]
    assert t["resolution"] == [1080, 1920] and t["scaled_to"]["source"].startswith("preset")
    assert t["value"] == 80.0 and t["native"]["by_resolution"]["540x960"]["p50"] == 40


def test_region_and_background_evidence_have_a_time(proj):
    """S1-18: canvas.video_region.* / canvas.background.* evidence carries a representative time (and the note
    why); the frame is saved when the file exists (analysis-time path tested in test_rv_analyzers)."""
    write_snapshot(proj, [("e1", 10)])
    make_video(proj, "e1", 30, 2.0)
    A.aggregate("joshuamagazine")
    it = _items(proj)
    for k in ("canvas.video_region.x", "canvas.video_region.y", "canvas.background.type", "canvas.background.color"):
        ev = it[k]["evidence"][0]
        assert ev["t"] == 15.0, (k, ev)                  # middle of the 30 s span
        assert "대표 시각" in ev["note"] and "영상 파일 없음" in ev["note"]
