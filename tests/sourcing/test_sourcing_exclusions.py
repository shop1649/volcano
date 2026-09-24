"""Reference-footage exclusion: the same RECORDING is excluded, a different one is not.

Media: CC-BY Intel sample clips in assets/test/generated/video (classroom.mp4 plays the role of
"reference footage"; candidates are derived from it or from another clip).
"""
from __future__ import annotations

import json

import pytest
from sourcing_fixtures import VIDEO

from shortkit.sourcing import download, exclusions, warehouse
from shortkit.sourcing.cli import select_candidate


@pytest.fixture(scope="module")
def ref_entry():
    if not (VIDEO / "classroom.mp4").is_file():
        pytest.skip("test videos missing")
    kf = exclusions.keyframe_hashes(VIDEO / "classroom.mp4", n=30, variants=False)
    return {"kind": "reference_footage", "ref_video_id": "REF_classroom", "ref_url": "https://youtu.be/SYNTHref001",
            "original_urls": ["https://www.tiktok.com/@origin/video/111"], "phash": [k["phash"] for k in kf],
            "frame_times": [k["t"] for k in kf], "added_at": "2026-09-24T00:00:00+00:00", "added_by": "test"}


@pytest.mark.slow
def test_reencoded_scaled_copy_is_excluded(ref_entry, clips):
    r = exclusions.check(video_path=clips["class_reencode"], entries=[ref_entry])
    assert r["excluded"] is True and r["matched_ref_video_id"] == "REF_classroom"
    assert r["matched_keyframes"] >= exclusions.MIN_MATCH_KEYFRAMES and r["distance"] <= exclusions.PHASH_MAX_DIST


@pytest.mark.slow
def test_vertical_mirrored_repost_is_excluded(ref_entry, clips):
    r = exclusions.check(video_path=clips["class_vertical"], entries=[ref_entry])
    assert r["excluded"] is True


@pytest.mark.slow
def test_different_recording_is_not_excluded(ref_entry, clips):
    r = exclusions.check(video_path=clips["head_pose"], entries=[ref_entry])
    assert r["excluded"] is False and r["matched_keyframes"] < exclusions.MIN_MATCH_KEYFRAMES
    assert r["distance"] > exclusions.PHASH_MAX_DIST


URL_ENTRY = {"kind": "reference_footage", "ref_video_id": "REF_classroom", "ref_url": "https://youtu.be/SYNTHref001",
             "original_urls": ["https://www.tiktok.com/@origin/video/111"], "phash": ["0" * 16],
             "frame_times": [0.0], "added_at": "2026-09-24T00:00:00+00:00", "added_by": "test"}


def test_url_rules():
    hit = exclusions.check({"url": "https://www.youtube.com/shorts/SYNTHref001"}, entries=[URL_ENTRY])
    assert hit["excluded"] is True and hit["method"] == "url"
    hit2 = exclusions.check({"url": "https://reddit.com/r/x/comments/zz/", "original_url":
                             "https://www.tiktok.com/@origin/video/111?lang=ko"}, entries=[URL_ENTRY])
    assert hit2["excluded"] is True and hit2["matched_ref_video_id"] == "REF_classroom"
    rule = {"kind": "url", "url": "https://www.instagram.com/reel/ABCdef/", "reason": "r", "added_at": "x",
            "added_by": "t"}
    assert exclusions.check({"url": "https://instagram.com/p/ABCdef"}, entries=[rule])["excluded"] is True
    miss = exclusions.check({"url": "https://www.youtube.com/watch?v=SYNTHothr01"}, entries=[URL_ENTRY])
    assert miss["excluded"] is None                 # no file/keyframes -> 못 잼, not "different"


def test_no_fingerprints_is_unmeasured(tiny_clip):
    r = exclusions.check({"url": "https://www.youtube.com/watch?v=SYNTHothr01"}, video_path=tiny_clip, entries=[])
    assert r["excluded"] is None and "못 잼" in r["note"] and r["method"] == "url_only"


@pytest.mark.slow
def test_register_and_candidate_flow(proj, clips):
    """exclude-add (register reference) -> manual intake with a file -> excluded -> select refused."""
    e = exclusions.add_reference_footage(VIDEO / "classroom.mp4", "REF_classroom", n_frames=20, added_by="test")
    assert len(e["phash"]) >= 10 and all(len(h) == 16 for h in e["phash"])
    stored = json.loads((proj / "warehouse" / "exclusions.jsonl").read_text().splitlines()[0])
    assert stored["kind"] == "reference_footage" and stored["ref_video_id"] == "REF_classroom"
    warehouse.upsert([{"platform": "youtube", "platform_id": "SYNTHcopy01", "url":
                       "https://www.youtube.com/watch?v=SYNTHcopy01", "views": None,
                       "views_source": "unavailable", "_item_access": {"platform_status": "blocked", "note": "x"}},
                      {"platform": "youtube", "platform_id": "SYNTHdiff01", "url":
                       "https://www.youtube.com/watch?v=SYNTHdiff01", "views": None,
                       "views_source": "unavailable", "_item_access": {"platform_status": "blocked", "note": "x"}}])
    same = download.attach_local_file("youtube_SYNTHcopy01", clips["class_reencode"], measure=True)
    assert same["status"] == "excluded" and same["reference_overlap"]["excluded"] is True
    assert same["download_path"] == "warehouse/sources/youtube_SYNTHcopy01.mp4"
    diff = download.attach_local_file("youtube_SYNTHdiff01", clips["head_pose"], measure=False)
    assert diff["status"] == "candidate" and diff["reference_overlap"]["excluded"] is False
    warehouse.put({**warehouse.get("youtube_SYNTHcopy01"), "reviews": [
        {"watched_by": "t", "notes": "n", "intensity": 3, "reversal": 3, "format_fit": 3}]})
    ok, _, msgs = select_candidate("youtube_SYNTHcopy01", accept=["recency", "quality", "reference_overlap"],
                                   reason="x")
    assert not ok and any("같은 녹화" in m for m in msgs)
    assert str(proj) not in (proj / "warehouse" / "candidates.jsonl").read_text()


@pytest.mark.slow
def test_reference_short_region_crop(tmp_path, clips):
    """A reference Short shows the footage inside a region with title/caption areas around it: hashing only
    the stored region (with its resolution) makes the raw source footage match."""
    import subprocess

    ref_short = tmp_path / "ref_short.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", "2", "-t", "8", "-i", str(VIDEO / "classroom.mp4"),
                    "-filter_complex",
                    "color=c=0x1a3050:s=540x960:r=15:d=8[bg];[0:v]scale=540:-2[fg];[bg][fg]overlay=0:300:shortest=1,"
                    "drawbox=x=40:y=90:w=460:h=150:color=white:t=fill,drawbox=x=60:y=680:w=420:h=90:color=yellow:t=fill",
                    "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", str(ref_short)], check=True)
    ex = tmp_path / "ex.jsonl"
    e = exclusions.add_reference_footage(ref_short, "REF_short", region={"x": 0, "y": 300, "w": 540, "h": 304},
                                         n_frames=16, path=ex)
    assert e["region"]["resolution"] == [540, 960]
    r = exclusions.check(video_path=clips["class_reencode"], entries=exclusions.load(ex))
    assert r["excluded"] is True and r["matched_ref_video_id"] == "REF_short"
    r2 = exclusions.check(video_path=clips["head_pose"], entries=exclusions.load(ex))
    assert r2["excluded"] is False
