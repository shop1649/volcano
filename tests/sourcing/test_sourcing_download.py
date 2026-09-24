"""Download bookkeeping with a fake yt-dlp (no network): provenance on success, honest failure records."""
from __future__ import annotations

from sourcing_fixtures import BLOCKED_TEXT, FakeDownloadError, load_fixture

from shortkit.sourcing import download, warehouse
from shortkit.util.hashing import sha256_file


def _seed(ids):
    warehouse.upsert([{"platform": "youtube", "platform_id": i, "url": f"https://www.youtube.com/watch?v={i}",
                       "views": None, "views_source": "unavailable",
                       "_item_access": {"platform_status": "ok", "note": ""}} for i in ids])


def test_download_success_records_provenance(proj, net, tiny_clip):
    _seed(["SYNTHdl0001"])
    info = load_fixture("yt_info_SYNTHaaaa01.json")
    info.update({"id": "SYNTHdl0001", "webpage_url": "https://www.youtube.com/watch?v=SYNTHdl0001",
                 "format_id": "137+140", "ext": "mp4", "vcodec": "avc1.640028", "acodec": "mp4a.40.2", "tbr": 2500.0})
    net.downloads["https://www.youtube.com/watch?v=SYNTHdl0001"] = {"file": str(tiny_clip), "info": info}
    r = download.download("youtube_SYNTHdl0001", measure=False)
    assert r["ok"] and r["path"] == "warehouse/sources/youtube_SYNTHdl0001.mp4"
    rec = warehouse.get("youtube_SYNTHdl0001")
    f = proj / rec["download_path"]
    assert f.is_file() and rec["sha256"] == sha256_file(f)
    assert rec["download"]["status"] == "ok" and rec["download"]["format"]["format_id"] == "137+140"
    assert rec["download"]["probe"]["width"] == 320
    # metadata carried by the download refreshed the views (with a check time), likes stay separate
    assert rec["views"] == 1520000 and rec["views_checked_at"] and rec["likes"] == 88000
    assert str(proj) not in (proj / "warehouse" / "candidates.jsonl").read_text()


def test_blocked_download_is_recorded_and_others_continue(proj, net, tiny_clip):
    _seed(["SYNTHdl0002", "SYNTHdl0003"])
    net.downloads["https://www.youtube.com/watch?v=SYNTHdl0002"] = FakeDownloadError(BLOCKED_TEXT)
    net.downloads["https://www.youtube.com/watch?v=SYNTHdl0003"] = {"file": str(tiny_clip), "info": {
        "id": "SYNTHdl0003"}}
    res = download.download_many(["youtube_SYNTHdl0002", "youtube_SYNTHdl0003", "youtube_missing"],
                                 measure=False)
    assert [r["ok"] for r in res] == [False, True, False]
    assert res[0]["status"] == "blocked" and "403" in res[0]["error"]
    assert res[2]["status"] == "missing"
    bad = warehouse.get("youtube_SYNTHdl0002")
    assert bad["download"]["status"] == "failed" and bad["download"]["platform_status"] == "blocked"
    assert bad["download_path"] is None and bad["sha256"] is None and bad["status"] == "candidate"
    assert bad["access"]["platform_status"] == "blocked"
    assert not (proj / "warehouse" / "sources" / "youtube_SYNTHdl0002.mp4").exists()


def test_excluded_candidate_is_not_downloaded(proj, net):
    _seed(["SYNTHdl0004"])
    rec = warehouse.get("youtube_SYNTHdl0004")
    warehouse.apply_overlap(rec, {"excluded": True, "matched_ref_video_id": "R", "method": "url"})
    warehouse.put(rec)
    r = download.download("youtube_SYNTHdl0004")
    assert not r["ok"] and r["status"] == "refused" and net.calls == []
