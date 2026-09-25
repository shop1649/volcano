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
    # the fingerprint is the sourcing module's own keyframe hashing (identical to candidate hashing)
    from shortkit.sourcing import exclusions as X
    reg = r["region"]
    kf = X.keyframe_hashes(proj / P / f"reference/videos/{vid}.mp4", n=T.N_KEYFRAMES, variants=False,
                           region=reg and {k: reg[k] for k in ("x", "y", "w", "h")})
    assert [k["phash"] for k in kf] == r["phash"] and [k["t"] for k in kf] == r["frame_times"]
    assert "grayscale" in r["method"] and r["added_by"] == T.ADDED_BY
    sa = json.loads((proj / "warehouse/source_accounts.json").read_text("utf-8"))
    assert sa["status"] == "measured" and sa["blocker"] is None
    top = {(a["platform"], a["handle"]): a for a in sa["accounts"]}
    assert top[("tiktok", "@real_uploader_1")]["count"] == 1
    assert top[("tiktok", "@real_uploader_1")]["url"] == "https://www.tiktok.com/@real_uploader_1"
    assert top[("tiktok", "@real_uploader_1")]["evidence"][0]["ref_video_id"] == vid
    assert top[("reddit", "r/SyntheticVideos")]["url"] == "https://www.reddit.com/r/SyntheticVideos"
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


def test_subset_trace_keeps_earlier_accounts(ref_video):
    """Tracing another video later must not drop accounts found earlier (built from all trace.json)."""
    proj, vid = ref_video
    T.trace("joshuamagazine", [vid], do_ocr=False, lens=False)
    write_json(proj / P / "reference/meta/other000001.json", {"video_id": "other000001",
                                                               "description": "출처: instagram @second_source"})
    out = T.trace("joshuamagazine", ["other000001"], do_ocr=False, lens=False)
    accs = {a["handle"] for a in out["accounts"]}
    assert {"@real_uploader_1", "@second_source"} <= accs and out["videos_traced"] == 2
    ig = next(a for a in out["accounts"] if a["handle"] == "@second_source")
    assert ig["platform"] == "instagram" and ig["verified_by_text"] is True and ig["url"] is None


BLOCKED_SNAPSHOT = {"status": "blocked", "captured_at": "2026-09-24T00:00:00+00:00", "method": "yt-dlp SYNTHETIC",
                    "blocker": "SYNTHETIC: Tunnel connection failed: 403 Forbidden", "videos": [], "n": 0}


def test_no_videos_writes_unmeasured_with_collect_blocker(proj):
    """Blocked `ref collect` -> nothing to trace -> an explicit 못 잼 file carrying the collect blocker
    (nothing invented), which the sourcing side reads as 미확보(못 잼)."""
    write_json(proj / P / "reference/latest100.json", BLOCKED_SNAPSHOT)
    out = T.trace("joshuamagazine", [], do_ocr=False)
    sa = json.loads((proj / "warehouse/source_accounts.json").read_text("utf-8"))
    assert out["status"] == sa["status"] == "unmeasured" and out["traced_now"] == 0
    assert "Tunnel connection failed: 403 Forbidden" in sa["blocker"] and "2026-09-24" in sa["blocker"]
    assert sa["accounts"] == [] and sa["keywords"] == [] and sa["traced_at"]
    from shortkit.sourcing import keywords
    ref = keywords.reference_derived()
    assert ref["status"] == "unmeasured" and ref["queries"] == [] and ref["accounts"] == []
    assert "403 Forbidden" in ref["note"]
    # nothing traced -> no footage / URL rows; the only row is the reference channel itself, which comes from
    # the preset (the user-given channel), not from any traced data
    ex = [json.loads(x) for x in (proj / "warehouse/exclusions.jsonl").read_text("utf-8").splitlines() if x.strip()]
    assert [e["kind"] for e in ex] == ["account"] and ex[0]["handle"] == "@joshuamagazine"


def test_source_accounts_shape_is_read_by_sourcing(ref_video):
    """The written file follows the agreed shape exactly and sourcing.keywords.reference_derived()
    turns it into reference-derived queries/accounts."""
    proj, vid = ref_video
    T.trace("joshuamagazine", [vid], do_ocr=False, lens=False)
    sa = json.loads((proj / "warehouse/source_accounts.json").read_text("utf-8"))
    assert {"status", "blocker", "traced_at", "accounts", "keywords"} <= set(sa)
    for a in sa["accounts"]:
        assert {"platform", "handle", "url", "count", "evidence", "verified_by_text"} <= set(a)
        assert isinstance(a["count"], int) and a["count"] >= 1
        assert all({"ref_video_id", "t"} <= set(e) for e in a["evidence"])
    for k in sa["keywords"]:
        assert {"keyword", "platforms", "count", "evidence"} <= set(k) and isinstance(k["platforms"], list)
        assert all({"ref_video_id", "t"} <= set(e) for e in k["evidence"])
    kw = next(k for k in sa["keywords"] if k["keyword"] == "교실")
    assert kw["platforms"] == ["reddit", "tiktok"]            # source platforms credited in the same video
    from shortkit.sourcing import keywords
    ref = keywords.reference_derived()
    assert ref["status"] == "measured"
    assert {q["query"] for q in ref["queries"]} >= {"교실", "반전"}
    qs = {q["query"]: q for q in ref["accounts"]}
    assert qs["https://www.tiktok.com/@real_uploader_1"]["platforms"] == ["tiktok"]
    assert qs["https://www.reddit.com/r/SyntheticVideos"]["platforms"] == ["reddit"]
    assert qs["@another.source"]["evidence"][0]["ref_video_id"] == vid
    assert all(q["origin"] == "reference_derived_account" for q in ref["accounts"])


def test_measured_file_not_downgraded(ref_video):
    proj, vid = ref_video
    T.trace("joshuamagazine", [vid], do_ocr=False, lens=False)
    shutil.rmtree(proj / P / "analysis")
    out = T.trace("joshuamagazine", [], do_ocr=False)
    sa = json.loads((proj / "warehouse/source_accounts.json").read_text("utf-8"))
    assert sa["status"] == "measured" and out.get("kept_existing") is True


def test_transcript_keywords_when_file_exists(proj):
    """SYNTHETIC transcript file in the agreed place (analysis/<id>/audio/transcript.json)."""
    vid = "trvid000001"
    write_json(proj / P / f"analysis/{vid}/audio/transcript.json",
               {"segments": [{"text": "고양이 가 냉장고 위로 점프"}, {"text": "고양이 가 떨어졌다 냉장고"}]})
    k = T.transcript_keywords("joshuamagazine", vid)
    assert k["status"] == "measured" and k["keywords"][:2] == ["고양이", "냉장고"]
    assert T.transcript_keywords("joshuamagazine", "nofile00001")["status"] == "unmeasured"


@pytest.mark.slow
def test_trace_with_ocr_records_watermark_account_with_time(ref_video):
    """Full trace (OCR on): the burned-in @fake_repost watermark of the SYNTHETIC dirty source becomes an
    unverified account whose evidence carries the reference video time."""
    proj, vid = ref_video
    T.trace("joshuamagazine", [vid], do_ocr=True, lens=False)
    sa = json.loads((proj / "warehouse/source_accounts.json").read_text("utf-8"))
    wm = [a for a in sa["accounts"] if any(e["kind"] == "watermark_ocr" for e in a["evidence"])]
    hits = [a for a in wm if "fakerepost".startswith(T._norm(a["handle"])) and len(T._norm(a["handle"])) >= 7]
    assert hits, sa["accounts"]
    a = hits[0]
    assert a["verified_by_text"] is False and a["url"] is None
    assert all(isinstance(e["t"], (int, float)) and e["ref_video_id"] == vid for e in a["evidence"])
    assert sa["coverage"].get("watermark_ocr") == 1 and sa["coverage"].get("description") == 1
