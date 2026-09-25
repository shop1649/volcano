"""Reference-only report over every >= threshold video, and the 'high views fully analysed' stage status
(review findings S1-01 stage part, S1-14, S4-10, S5-02 coverage).  All files are SYNTHETIC."""
from __future__ import annotations

import json

from shortkit.reference import aggregate as A
from shortkit.reference import high_views as HV
from shortkit.util.jsonio import append_jsonl, write_json

from test_rv_classify_aggregate import make_video, write_snapshot

P = "presets/joshuamagazine"


def _hv(proj, vids, unverified=(), status="ok"):
    write_json(proj / P / "reference/high_views.json", {
        "status": status, "threshold": 800_000, "checked_at": "2026-09-25T00:00:00+00:00",
        "videos": [{"video_id": v, "url": f"https://www.youtube.com/watch?v={v}", "view_count": 900_000 + i,
                    "view_count_checked_at": "2026-09-25T00:00:00+00:00", "kind": "short"} for i, v in enumerate(vids)],
        "unverified": [{"video_id": u, "view_count_approx": 800_000, "reason": "SYNTHETIC 메타데이터 실패"}
                       for u in unverified]})


def _full(proj, vid):
    """Every analysis step done for vid (SYNTHETIC files)."""
    make_video(proj, vid, 30, 2.0)
    (proj / P / "reference/videos").mkdir(parents=True, exist_ok=True)
    (proj / P / "reference/videos" / f"{vid}.mp4").write_bytes(b"SYNTHETIC")
    a = proj / P / "analysis" / vid / "audio"
    write_json(a / "bgm.json", {"video_id": vid, "status": "unmeasured", "presence": "present"})
    write_json(a / "original.json", {"video_id": vid, "original_audio": {"presence": "absent"},
                                     "ducking": {"presence": "absent"}})
    write_json(a / "sfx_events.json", {"video_id": vid, "status": "partial", "unmeasured_coverage": {"intervals": [[1, 2]]},
                                       "events": [{"t": 3.0, "class": "edit_sfx"}, {"t": 5.0, "class": "edit_sfx"}]})
    write_json(proj / P / "analysis" / vid / "trace.json", {"video_id": vid, "accounts_found": [
        {"platform": "tiktok", "account": "@src_x"}], "original_urls": [], "sources_examined": ["description"],
        "phash_count": 12})
    append_jsonl(proj / "warehouse/exclusions.jsonl", {"kind": "reference_footage", "ref_video_id": vid,
                                                       "phash": ["0" * 16] * 12, "frame_times": [0.0] * 12})


def test_stage_needs_every_high_view_video_downloaded_and_analysed(proj):
    write_snapshot(proj, [("s0000xxxxxx", 900_000)])
    _hv(proj, ["s0000xxxxxx", "s0120xxxxxx"])
    _full(proj, "s0000xxxxxx")
    make_video(proj, "s0120xxxxxx", 45, 3.0)            # outside the snapshot: only visually analysed so far
    rep = HV.build_report("joshuamagazine")
    assert rep["status"] == "unmeasured"
    assert rep["missing"] == {"downloaded": ["s0120xxxxxx"], "visual": [], "audio": ["s0120xxxxxx"],
                              "trace": ["s0120xxxxxx"]}
    row = HV.stage_status("joshuamagazine")
    assert row["status"] == "unmeasured" and row["state"] == "open" and "영상 받기 1/2" in row["evidence"]
    by = {r["video_id"]: r for r in rep["videos"]}
    assert by["s0120xxxxxx"]["in_latest100"] is False and by["s0120xxxxxx"]["structure"]["duration_s"] == 30.0
    assert by["s0000xxxxxx"]["audio"]["sfx"]["n_sfx"] == 2 and by["s0000xxxxxx"]["audio"]["sfx"]["counts_are_lower_bounds"]
    assert by["s0000xxxxxx"]["credits"]["accounts"] == ["tiktok:@src_x"]
    md = (proj / P / "reference/high_views_report.md").read_text("utf-8")
    assert "참고" in md and "s0120xxxxxx" in md and "`shortkit ref audio-analyze --set high_views`" in md
    # completing the chain for the outside video makes the stage measured
    _full(proj, "s0120xxxxxx")
    rep = HV.build_report("joshuamagazine")
    assert rep["status"] == "measured" and rep["blocker"] is None
    assert HV.stage_status("joshuamagazine")["state"] == "resolved"
    # ... and the report is reference-only: production measurements still use the snapshot member only
    A.aggregate("joshuamagazine")
    vt = json.loads((proj / P / "measurements/visual_text.json").read_text("utf-8"))
    assert vt["basis"]["video_ids"] == ["s0000xxxxxx"] and vt["basis"]["excluded_non_snapshot"] == ["s0120xxxxxx"]


def test_unverified_or_blocked_list_is_never_fully_analysed(proj):
    """The S1-01 case: status ok, zero exact videos, but an unverified candidate -> NOT measured."""
    write_snapshot(proj, [("s0000xxxxxx", 10)])
    _hv(proj, [], unverified=["s0120xxxxxx"])
    rep = HV.build_report("joshuamagazine")
    assert rep["status"] == "unmeasured" and "s0120xxxxxx" in rep["blocker"]
    write_json(proj / P / "reference/high_views.json", {"status": "blocked", "blocker": "SYNTHETIC 403", "videos": [],
                                                        "unverified": []})
    row = HV.stage_status("joshuamagazine")
    assert row["status"] == "unmeasured" and row["state"] == "blocked_network"


def test_complete_empty_list_is_measured(proj):
    write_snapshot(proj, [("s0000xxxxxx", 10)])
    _hv(proj, [])
    assert HV.build_report("joshuamagazine")["status"] == "measured"
