"""Source tracing: description credits, watermark OCR, Lens keyframes, exclusions record format.

Descriptions and snapshot entries are SYNTHETIC.  The "reference video" is the locally generated
dirty_source.mp4 (Intel CC-BY clip + a fake ``@fake_repost`` watermark), never channel data.
"""
from __future__ import annotations

import csv
import json
import re
import shutil
from pathlib import Path

import pytest

from shortkit.reference import trace_sources as T
from shortkit.util.jsonio import write_json

REPO = Path(__file__).resolve().parents[2]
DIRTY = REPO / "assets/test/generated/dirty_source.mp4"
P = "presets/joshuamagazine"

DESC = """SYNTHETIC 설명
영상 출처: 틱톡 @real_uploader_1
원본 https://www.tiktok.com/@real_uploader_1/video/7412345678901234567
via https://www.reddit.com/r/SyntheticVideos/comments/abc/
cr. @another.source
구독 부탁! @joshuamagazine
#교실 #반전"""


def test_parse_description_and_urls():
    own = {"joshuamagazine"}
    d = T.parse_description(DESC, own)
    accs = {(a["platform"], a["account"]) for a in d["accounts"]}
    assert ("tiktok", "@real_uploader_1") in accs
    assert ("reddit", "r/SyntheticVideos") in accs
    assert any(a == "@another.source" for _, a in accs)
    assert not any("joshuamagazine" in a for _, a in accs)          # the channel itself is never a source
    assert d["hashtags"] == ["교실", "반전"]
    assert T.platform_of_url("https://www.instagram.com/reel/Cxyz/") == ("instagram", None)
    assert T.platform_of_url("https://instagram.com/some.user/") == ("instagram", "@some.user")
    assert T.platform_of_url("https://x.com/someone/status/1") == ("x", "@someone")
    assert T.platform_of_url("https://youtube.com/@chan/shorts") == ("youtube", "@chan")


@pytest.fixture()
def ref_video(proj):
    if not DIRTY.is_file():
        pytest.skip("dirty_source.mp4 missing: python -m shortkit testassets dirty-source")
    vid = "refvid00001"
    vdir = proj / P / "reference/videos"
    vdir.mkdir(parents=True)
    shutil.copy(DIRTY, vdir / f"{vid}.mp4")
    write_json(proj / P / "reference/meta" / f"{vid}.json", {"video_id": vid, "description": DESC})
    write_json(proj / P / "reference/latest100.json", {
        "status": "ok", "captured_at": "SYNTHETIC", "videos": [{"rank": 1, "video_id": vid, "title": "SYNTHETIC",
                                                                 "url": f"https://www.youtube.com/watch?v={vid}"}]})
    write_json(proj / P / f"analysis/{vid}/shots.json", {"video_id": vid, "cuts": [],
                                                           "shots": [{"start": 0.0, "end": 10.0},
                                                                     {"start": 10.0, "end": 20.0}]})
    return proj, vid


def test_trace_writes_exclusions_and_accounts(ref_video):
    proj, vid = ref_video
    out = T.trace("joshuamagazine", [vid], do_ocr=False)
    rows = [json.loads(x) for x in (proj / "warehouse/exclusions.jsonl").read_text("utf-8").splitlines()]
    ref = [r for r in rows if r["kind"] == "reference_footage"]
    assert len(ref) == 1
    r = ref[0]
    for k in ("ref_video_id", "ref_url", "original_urls", "phash", "frame_times", "added_at", "added_by"):
        assert k in r
    assert r["ref_video_id"] == vid and r["ref_url"].endswith(vid)
    assert len(r["phash"]) >= 10 and all(re.fullmatch(r"[0-9a-f]{16}", h) for h in r["phash"])
    assert len(r["frame_times"]) == len(r["phash"])
    assert "https://www.tiktok.com/@real_uploader_1/video/7412345678901234567" in r["original_urls"]
    urls = {x["url"] for x in rows if x["kind"] == "url"}
    assert f"https://www.youtube.com/watch?v={vid}" in urls
    assert all({"url", "reason", "added_at", "added_by"} <= set(x) for x in rows if x["kind"] == "url")
    # the hashes identify the same footage: re-hash a few frames of the raw clip and compare
    import imagehash
    from PIL import Image

    from shortkit.util.media import read_frames
    fr = read_frames(proj / P / f"reference/videos/{vid}.mp4", [r["frame_times"][3]])[0]
    h = imagehash.phash(Image.fromarray(fr))
    assert h - imagehash.hex_to_hash(r["phash"][3]) <= 10
    sa = json.loads((proj / "warehouse/source_accounts.json").read_text("utf-8"))
    top = {(a["platform"], a["account"]): a for a in sa["accounts"]}
    assert top[("tiktok", "@real_uploader_1")]["frequency"] == 1
    assert top[("tiktok", "@real_uploader_1")]["evidence"][0]["video_id"] == vid
    assert {k["keyword"] for k in sa["keywords"]} >= {"교실", "반전"}
    lens = proj / P / f"analysis/{vid}/lens"
    assert (lens / "lens_queries.md").is_file() and len(list(lens.glob("*.jpg"))) >= 2
    assert "수동" in (lens / "lens_queries.md").read_text("utf-8")
    trace_json = json.loads((proj / P / f"analysis/{vid}/trace.json").read_text("utf-8"))
    assert trace_json["transcript"]["status"] == "unmeasured"
    # running again adds nothing new (idempotent)
    n = len(rows)
    T.trace("joshuamagazine", [vid], do_ocr=False)
    assert len((proj / "warehouse/exclusions.jsonl").read_text("utf-8").splitlines()) == n
    # a Lens result signed by the person who searched is read back as a traced original
    res = lens / "lens_results.csv"
    rows_csv = list(csv.DictReader(res.open(encoding="utf-8")))
    rows_csv[0].update({"original_url": "https://www.instagram.com/found.user/", "checked_by": "tester",
                        "checked_at": "2026-09-24"})
    rows_csv[1]["original_url"] = "https://www.instagram.com/unchecked/"       # no checked_by -> ignored
    with res.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=T.LENS_HEADER)
        w.writeheader()
        w.writerows(rows_csv)
    T.trace("joshuamagazine", [vid], do_ocr=False)
    urls = {json.loads(x).get("url") for x in (proj / "warehouse/exclusions.jsonl").read_text("utf-8").splitlines()}
    assert "https://www.instagram.com/found.user/" in urls and "https://www.instagram.com/unchecked/" not in urls
    _ = out


@pytest.mark.slow
def test_watermark_ocr_finds_handle():
    if not DIRTY.is_file():
        pytest.skip("dirty_source.mp4 missing")
    from shortkit.util.media import probe
    info = probe(DIRTY)
    region = {"x": 0, "y": 0, "w": info.width, "h": info.height}
    wm = T.ocr_watermarks(DIRTY, region, fps=0.5, own={"joshuamagazine"})
    # stated tolerance: OCR may drop trailing characters or the underscore of a small watermark,
    # so a reading counts when its normalized form is a >= 7-character prefix of the truth
    truth = "fakerepost"
    hits = [w for w in wm if truth.startswith(T._norm(w["account"])) and len(T._norm(w["account"])) >= 7]
    assert hits, wm
    assert all(w["verified"] is False and w["variants"] for w in wm)
    assert all(len(w["frames"]) >= 2 or w["conf"] >= 70 for w in wm)
    assert max(len(h["frames"]) for h in hits) >= 3
