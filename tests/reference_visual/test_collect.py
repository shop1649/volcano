"""Channel collection with SYNTHETIC yt-dlp info dicts / SYNTHETIC YouTube Data API responses.

Nothing here talks to YouTube (blocked on this machine); ``yt_dlp.YoutubeDL.extract_info`` is
monkeypatched to return hand-made info dicts shaped like yt-dlp's documented output
(``entries`` of a tab with ``id``/``title``/``view_count``; per-video ``timestamp``,
``upload_date``, ``duration``, ``view_count``, ``description``).
"""
from __future__ import annotations

import json

import pytest
import yt_dlp

from shortkit.reference import collect as C

BASE_TS = 1_780_000_000  # SYNTHETIC epoch


def synthetic_channel(n_shorts=120, n_videos=30):
    """SYNTHETIC channel: shorts published every 6 h, long videos every 2 days (interleaved)."""
    vids = {}
    for i in range(n_shorts):
        vid = f"s{i:04d}xxxxxx"[:11]
        vids[vid] = {"tab": "shorts", "ts": BASE_TS - i * 6 * 3600, "views": 1_000_000 - i * 5_000,
                     "duration": 30 + i % 40}
    for i in range(n_videos):
        vid = f"v{i:04d}yyyyyy"[:11]
        vids[vid] = {"tab": "videos", "ts": BASE_TS - i * 48 * 3600 - 3 * 3600, "views": 900_000 - i * 50_000,
                     "duration": 300 + i}
    return vids


def install_fake_ytdlp(monkeypatch, vids, fail_ids=(), block=False, calls=None):
    def fake_extract_info(self, url, download=False, *a, **kw):
        if calls is not None:
            calls.append(url)
        if block:
            raise yt_dlp.utils.DownloadError(
                "ERROR: [youtube:tab] synthetic: Unable to download API page: ('Unable to connect to proxy', "
                "OSError('Tunnel connection failed: 403 Forbidden'))")
        for tab in ("shorts", "videos"):
            if url.endswith("/" + tab):
                ents = sorted(((v, d) for v, d in vids.items() if d["tab"] == tab), key=lambda x: -x[1]["ts"])
                return {"_type": "playlist", "id": "UC_SYNTHETIC", "entries": [
                    {"_type": "url", "ie_key": "Youtube", "id": v, "title": f"SYNTHETIC {v}",
                     "url": f"https://www.youtube.com/shorts/{v}", "view_count": round(d["views"], -4)}
                    for v, d in ents]}
        vid = url.split("v=")[-1]
        if vid in fail_ids:
            raise yt_dlp.utils.DownloadError(f"ERROR: [youtube] {vid}: Video unavailable")
        d = vids[vid]
        import datetime as dt
        ud = dt.datetime.fromtimestamp(d["ts"], dt.timezone.utc).strftime("%Y%m%d")
        return {"id": vid, "title": f"SYNTHETIC title {vid}", "timestamp": d["ts"], "upload_date": ud,
                "duration": d["duration"], "view_count": d["views"],
                "description": f"SYNTHETIC 출처: tiktok @src_{vid[:3]}\nhttps://www.tiktok.com/@src_{vid[:3]}/video/1",
                "tags": ["synthetic"], "channel": "SYNTHETIC"}

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", fake_extract_info)


def _read(proj, name):
    return json.loads((proj / "presets/joshuamagazine/reference" / f"{name}.json").read_text(encoding="utf-8"))


def test_latest100_ordering_and_high_views(proj, monkeypatch):
    vids = synthetic_channel()
    install_fake_ytdlp(monkeypatch, vids)
    r = C.collect("joshuamagazine", method="ytdlp")
    assert r["status"] == "ok" and r["exit_code"] == 0
    snap = _read(proj, "latest100")
    assert snap["status"] == "ok" and snap["n"] == 100 and len(snap["videos"]) == 100
    expected = sorted(vids, key=lambda v: -vids[v]["ts"])[:100]
    assert [v["video_id"] for v in snap["videos"]] == expected
    assert [v["rank"] for v in snap["videos"]] == list(range(1, 101))
    ts = [v["published_at"] for v in snap["videos"]]
    assert ts == sorted(ts, reverse=True)
    first = snap["videos"][0]
    for k in ("video_id", "url", "title", "published_at", "upload_date", "duration", "view_count",
              "view_count_checked_at", "kind"):
        assert k in first
    assert {v["kind"] for v in snap["videos"]} == {"short", "video"}
    # high views: exact view counts >= 800k only
    hv = _read(proj, "high_views")
    assert hv["threshold"] == 800_000
    exp_hv = {v for v, d in vids.items() if d["views"] >= 800_000
              and (v in expected or True)}
    got = {v["video_id"] for v in hv["videos"]}
    assert all(v["view_count"] >= 800_000 for v in hv["videos"])
    assert all(v["view_count_checked_at"] for v in hv["videos"])
    # videos that only have approximate (flat) counts are listed separately, never as exact
    fetched = set(expected) | {v for v, d in vids.items() if d["tab"] == "videos"}
    assert got == {v for v in exp_hv if v in fetched}
    assert all(u["video_id"] not in got for u in hv["unverified"])
    # per-video metadata for trace
    meta = json.loads((proj / f"presets/joshuamagazine/reference/meta/{expected[0]}.json").read_text("utf-8"))
    assert "출처" in meta["description"]
    allv = _read(proj, "all_videos")
    assert allv["n"] == len(vids)
    assert all(v["in_latest100"] == (v["video_id"] in expected) for v in allv["videos"])


def test_snapshot_is_fixed_unless_refresh(proj, monkeypatch):
    vids = synthetic_channel()
    install_fake_ytdlp(monkeypatch, vids)
    C.collect("joshuamagazine", method="ytdlp")
    first = _read(proj, "latest100")
    # the channel uploads 5 new shorts; views change
    for i in range(5):
        vids[f"n{i:04d}zzzzzz"[:11]] = {"tab": "shorts", "ts": BASE_TS + (i + 1) * 3600, "views": 10, "duration": 20}
    r = C.collect("joshuamagazine", method="ytdlp")
    assert r["status"] == "kept"
    assert _read(proj, "latest100") == first            # baseline untouched
    allv = _read(proj, "all_videos")
    assert allv["n"] == len(vids)                          # reference listing refreshed
    # latest100 wins on conflicts in all_videos
    snap_v = {v["video_id"]: v for v in first["videos"]}
    for v in allv["videos"]:
        if v["video_id"] in snap_v:
            assert v["view_count"] == snap_v[v["video_id"]]["view_count"]
    r = C.collect("joshuamagazine", method="ytdlp", refresh_snapshot=True)
    new = _read(proj, "latest100")
    assert new["videos"][0]["video_id"].startswith("n0004")
    replaced = list((proj / "presets/joshuamagazine/reference").glob("latest100.replaced_*.json"))
    assert len(replaced) == 1


def test_blocked_records_block_and_keeps_ok_snapshot(proj, monkeypatch):
    install_fake_ytdlp(monkeypatch, {}, block=True)
    r = C.collect("joshuamagazine", method="ytdlp")
    assert r["status"] == "blocked" and r["exit_code"] != 0
    snap = _read(proj, "latest100")
    assert snap["status"] == "blocked" and snap["videos"] == [] and "403" in snap["blocker"]
    assert _read(proj, "high_views")["status"] == "blocked"
    # an ok snapshot is never replaced by a blocked attempt, even with --refresh-snapshot
    vids = synthetic_channel(10, 2)
    install_fake_ytdlp(monkeypatch, vids)
    C.collect("joshuamagazine", method="ytdlp")
    ok = _read(proj, "latest100")
    assert ok["status"] == "ok"
    install_fake_ytdlp(monkeypatch, vids, block=True)
    r = C.collect("joshuamagazine", method="ytdlp", refresh_snapshot=True)
    assert r["status"] == "blocked"
    assert _read(proj, "latest100") == ok
    log = (proj / "presets/joshuamagazine/reference/collect_log.jsonl").read_text("utf-8").splitlines()
    assert [json.loads(x)["status"] for x in log] == ["blocked", "ok", "blocked"]


def test_partial_when_metadata_fails(proj, monkeypatch):
    vids = synthetic_channel(20, 0)
    bad = sorted(vids)[:2]
    install_fake_ytdlp(monkeypatch, vids, fail_ids=bad)
    r = C.collect("joshuamagazine", method="ytdlp")
    snap = _read(proj, "latest100")
    assert snap["status"] == "partial" and "메타데이터 실패" in snap["blocker"]
    assert all(v["video_id"] not in bad for v in snap["videos"])
    assert r["exit_code"] != 0


def test_api_path_with_synthetic_responses(proj, monkeypatch):
    """SYNTHETIC YouTube Data API v3 responses (channels -> playlistItems -> videos)."""
    monkeypatch.setenv("YOUTUBE_API_KEY", "SYNTHETIC-KEY")
    items = [(f"a{i:04d}bbbbbb"[:11], f"2026-09-{20 - i // 5:02d}T{10 + i % 5:02d}:00:00Z", 1_200_000 - i * 100_000,
              "PT45S" if i % 3 else "PT4M2S") for i in range(12)]
    calls = []

    def getter(url):
        calls.append(url)
        assert "key=SYNTHETIC-KEY" in url
        if "/channels?" in url:
            return {"items": [{"id": "UC_SYN", "contentDetails": {"relatedPlaylists": {"uploads": "UU_SYN"}}}]}
        if "/playlistItems?" in url:
            if "pageToken=P2" in url:
                page, tok = items[6:], None
            else:
                page, tok = items[:6], "P2"
            return {"items": [{"contentDetails": {"videoId": v, "videoPublishedAt": p}} for v, p, _, _ in page],
                    **({"nextPageToken": tok} if tok else {})}
        if "/videos?" in url:
            ids = url.split("id=")[1].split("&")[0].replace("%2C", ",").split(",")
            return {"items": [{"id": v, "snippet": {"title": f"SYNTHETIC {v}", "description": "SYNTHETIC",
                                                    "publishedAt": p},
                               "contentDetails": {"duration": d}, "statistics": {"viewCount": str(vc)}}
                              for v, p, vc, d in items if v in ids]}
        raise AssertionError(url)

    r = C.collect("joshuamagazine", method="auto", api_getter=getter)
    assert r["status"] == "ok"
    snap = _read(proj, "latest100")
    assert snap["method"].startswith("youtube-data-api-v3")
    pubs = [v["published_at"] for v in snap["videos"]]
    assert pubs == sorted(pubs, reverse=True) and len(pubs) == 12
    by = {v["video_id"]: v for v in snap["videos"]}
    assert by[items[1][0]]["duration"] == 45 and by[items[0][0]]["duration"] == 242
    assert by[items[1][0]]["kind"] == "short" and by[items[0][0]]["kind"] == "video"
    hv = _read(proj, "high_views")
    assert {v["video_id"] for v in hv["videos"]} == {v for v, _, vc, _ in items if vc >= 800_000}


def test_iso_duration_and_error_classes():
    assert C.iso8601_duration("PT1M2S") == 62
    assert C.iso8601_duration("PT1H") == 3600
    assert C.iso8601_duration("P1DT2S") == 86402
    assert C.classify_error("Tunnel connection failed: 403 Forbidden") == "blocked"
    assert C.classify_error("This channel does not have a videos tab") == "tab_absent"
    assert C.classify_error("Video unavailable") == "error"


def test_cli_collect_blocked_exit_code(proj, monkeypatch):
    install_fake_ytdlp(monkeypatch, {}, block=True)
    from shortkit.cli import main
    assert main(["ref", "collect", "--method", "ytdlp"]) == 3


@pytest.mark.parametrize("tab_absent", [True])
def test_missing_videos_tab_is_not_a_block(proj, monkeypatch, tab_absent):
    vids = synthetic_channel(5, 0)
    install_fake_ytdlp(monkeypatch, vids)
    orig = yt_dlp.YoutubeDL.extract_info

    def with_absent(self, url, download=False, *a, **kw):
        if url.endswith("/videos"):
            raise yt_dlp.utils.DownloadError("ERROR: [youtube:tab] SYNTHETIC: This channel does not have a videos tab")
        return orig(self, url, download)

    monkeypatch.setattr(yt_dlp.YoutubeDL, "extract_info", with_absent)
    r = C.collect("joshuamagazine", method="ytdlp")
    snap = _read(proj, "latest100")
    assert snap["status"] == "ok" and snap["tabs"]["videos"]["status"] == "tab_absent"
    assert "5편뿐" in " ".join(snap["notes"])
    assert r["exit_code"] == 0
