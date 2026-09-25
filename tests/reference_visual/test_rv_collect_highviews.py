"""High-view completeness, fresh view counts and fixed partial snapshots (review findings S1-01, S1-02,
S1-05) -- all with SYNTHETIC yt-dlp info dicts (nothing here talks to YouTube)."""
from __future__ import annotations

import json

import yt_dlp

from shortkit.reference import collect as C
from shortkit.reference.common import resolve_ids

from test_rv_collect import BASE_TS, install_fake_ytdlp, synthetic_channel


def _read(proj, name):
    return json.loads((proj / "presets/joshuamagazine/reference" / f"{name}.json").read_text(encoding="utf-8"))


def shorts_channel(n=150, views=None):
    """SYNTHETIC shorts-only channel, one upload every 6 h; default 10k views each."""
    views = views or {}
    return {f"s{i:04d}xxxxxx"[:11]: {"tab": "shorts", "ts": BASE_TS - i * 6 * 3600, "views": views.get(i, 10_000),
                                      "duration": 30} for i in range(n)}


def test_high_view_video_outside_latest100_is_exact_and_downloadable(proj, monkeypatch):
    """S1-01: an old short with 2,000,000 views (rank 121) must be in high_views.videos (exact count from its
    own metadata), get meta/<id>.json for tracing, and be resolvable for `ref download --set high_views`."""
    vids = shorts_channel(150, {120: 2_000_000})
    install_fake_ytdlp(monkeypatch, vids)
    r = C.collect("joshuamagazine", method="ytdlp")
    old = "s0120xxxxxx"
    hv = _read(proj, "high_views")
    assert [v["video_id"] for v in hv["videos"]] == [old]
    assert hv["videos"][0]["view_count"] == 2_000_000 and hv["videos"][0]["in_latest100"] is False
    assert hv["unverified"] == [] and hv["status"] == "ok" and r["exit_code"] == 0 and r["n_high"] == 1
    assert (proj / f"presets/joshuamagazine/reference/meta/{old}.json").is_file()
    assert resolve_ids("joshuamagazine", set_name="high_views") == [old]
    assert resolve_ids("joshuamagazine", set_name="high_views_outside") == [old]
    assert old not in {v["video_id"] for v in _read(proj, "latest100")["videos"]}


def test_high_view_candidate_without_metadata_is_unverified_not_ok(proj, monkeypatch):
    vids = shorts_channel(150, {120: 2_000_000})
    install_fake_ytdlp(monkeypatch, vids, fail_ids=("s0120xxxxxx",))
    r = C.collect("joshuamagazine", method="ytdlp")
    hv = _read(proj, "high_views")
    assert hv["videos"] == [] and hv["status"] == "partial"
    assert [u["video_id"] for u in hv["unverified"]] == ["s0120xxxxxx"]
    assert "메타데이터 조회 실패" in hv["unverified"][0]["reason"] and "s0120xxxxxx" in hv["blocker"]
    assert r["exit_code"] == 4
    assert _read(proj, "latest100")["status"] == "ok"      # the snapshot itself is complete


def test_view_counts_are_fresh_and_snapshot_member_passing_threshold_is_high(proj, monkeypatch):
    """S1-02: a snapshot member with 700k views at capture time that later passes 800k must enter high_views
    with its current count; all_videos keeps the snapshot's count apart."""
    vids = shorts_channel(120, {10: 700_000})
    install_fake_ytdlp(monkeypatch, vids)
    C.collect("joshuamagazine", method="ytdlp")
    x = "s0010xxxxxx"
    assert _read(proj, "high_views")["videos"] == []
    for i in range(100):                                   # 100 newer uploads push X out of the newest 100
        vids[f"n{i:04d}zzzzzz"[:11]] = {"tab": "shorts", "ts": BASE_TS + (i + 1) * 3600, "views": 5, "duration": 20}
    vids[x]["views"] = 1_500_000
    r = C.collect("joshuamagazine", method="ytdlp")
    assert r["status"] == "kept"
    hv = _read(proj, "high_views")
    assert [(v["video_id"], v["view_count"]) for v in hv["videos"]] == [(x, 1_500_000)]
    assert hv["videos"][0]["in_latest100"] is True and hv["videos"][0]["view_count_at_snapshot"] == 700_000
    row = next(v for v in _read(proj, "all_videos")["videos"] if v["video_id"] == x)
    assert row["view_count"] == 1_500_000 and row["view_count_source"] == "video_metadata"
    assert row["view_count_at_snapshot"] == 700_000
    assert row["published_at"] == next(v for v in _read(proj, "latest100")["videos"] if v["video_id"] == x)["published_at"]


def test_partial_snapshot_is_fixed_then_completed_in_place(proj, monkeypatch):
    """S1-05: a partial snapshot is a fixed baseline (never silently replaced), records its missing members
    with the reason, and is completed as of its own capture time once the member can be read."""
    vids = synthetic_channel(120, 30)                      # shorts AND long videos, interleaved
    bad = "s0005xxxxxx"
    install_fake_ytdlp(monkeypatch, vids, fail_ids=(bad,))
    r1 = C.collect("joshuamagazine", method="ytdlp")
    s1 = _read(proj, "latest100")
    assert s1["status"] == "partial" and r1["exit_code"] == 4
    assert [m["video_id"] for m in s1["missing_members"]] == [bad]
    assert "unavailable" in s1["missing_members"][0]["error"].lower() and s1["missing_members"][0]["tab_rank"] == 6
    assert len(s1["videos"]) == 100 and bad not in {v["video_id"] for v in s1["videos"]}
    capture = sorted(vids, key=lambda v: -vids[v]["ts"])[:101]          # the 101st filled the missing slot
    assert [v["video_id"] for v in s1["videos"]] == [v for v in capture if v != bad]
    # 5 new uploads; the member still fails -> the SAME snapshot is kept (still partial)
    for i in range(5):
        vids[f"n{i:04d}zzzzzz"[:11]] = {"tab": "shorts", "ts": BASE_TS + (i + 1) * 3600, "views": 5, "duration": 20}
    r2 = C.collect("joshuamagazine", method="ytdlp")
    s2 = _read(proj, "latest100")
    assert r2["status"] == "kept" and s2["captured_at"] == s1["captured_at"] and s2["status"] == "partial"
    assert [v["video_id"] for v in s2["videos"]] == [v["video_id"] for v in s1["videos"]]
    # the member becomes readable -> completed in place, membership as of the original capture time
    install_fake_ytdlp(monkeypatch, vids)
    r3 = C.collect("joshuamagazine", method="ytdlp")
    s3 = _read(proj, "latest100")
    assert r3["status"] == "kept" and s3["status"] == "ok" and s3["captured_at"] == s1["captured_at"]
    ids = [v["video_id"] for v in s3["videos"]]
    assert ids == capture[:100] and bad in ids and not any(v.startswith("n") for v in ids)
    assert [v["rank"] for v in s3["videos"]] == list(range(1, 101))
    assert s3["completions"][-1]["recovered"] == [bad] and s3["completions"][-1]["dropped"] == [capture[100]]
    assert list((proj / "presets/joshuamagazine/reference").glob("latest100.completed_*.json"))
    assert r3["exit_code"] == 0


def test_refresh_archives_a_partial_snapshot(proj, monkeypatch):
    vids = shorts_channel(110)
    install_fake_ytdlp(monkeypatch, vids, fail_ids=("s0003xxxxxx",))
    C.collect("joshuamagazine", method="ytdlp")
    install_fake_ytdlp(monkeypatch, vids)
    C.collect("joshuamagazine", method="ytdlp", refresh_snapshot=True)
    arch = list((proj / "presets/joshuamagazine/reference").glob("latest100.replaced_*.json"))
    assert len(arch) == 1 and json.loads(arch[0].read_text("utf-8"))["status"] == "partial"
    assert _read(proj, "latest100")["status"] == "ok"


def test_metadata_is_not_fetched_for_far_below_threshold_entries(proj, monkeypatch):
    calls: list[str] = []
    vids = shorts_channel(150)
    install_fake_ytdlp(monkeypatch, vids, calls=calls)
    C.collect("joshuamagazine", method="ytdlp")
    per_video = [u for u in calls if "watch?v=" in u]
    assert len(per_video) == 100                         # 10k flat counts: no high-view candidates
    _ = yt_dlp
