"""candidates.jsonl / search_log.jsonl records (CONTRACT §9) with SYNTHETIC platform data."""
from __future__ import annotations

import json

from sourcing_fixtures import BLOCKED_TEXT, FakeDownloadError, load_fixture

from shortkit.sourcing import warehouse
from shortkit.sourcing.platforms import reddit, youtube
from shortkit.util.jsonio import read_jsonl

SECTION9 = {"id", "platform", "url", "title", "original_author", "original_url", "reposter", "keywords", "views",
            "views_checked_at", "views_source", "likes", "published_at", "first_seen_at", "duration", "width",
            "height", "download_path", "sha256", "reference_overlap", "scores", "selection_reason", "status",
            "access"}


def _item(**kw):
    base = {"platform": "youtube", "platform_id": "SYNTHzzzz09", "url": "https://www.youtube.com/watch?v=SYNTHzzzz09",
            "title": "t", "description": None, "uploader": "Up", "views": None, "views_source": "unavailable",
            "likes": None, "published_at": "2026-09-01T00:00:00+00:00", "_item_access": {"platform_status": "ok",
                                                                                        "note": ""}}
    base.update(kw)
    return base


def test_record_has_contract_fields_and_relative_paths(proj):
    ids = warehouse.upsert([_item(views=10, views_source="platform_metadata", likes=3)], keywords=["q"])
    rec = warehouse.get(ids["new"][0])
    assert SECTION9 <= set(rec)
    assert set(rec["reference_overlap"]) >= {"excluded", "matched_video_id", "method", "distance"}
    assert set(rec["scores"]) >= {"recency", "intensity", "reversal", "quality", "format_fit", "total"}
    assert rec["access"]["platform_status"] == "ok"
    raw = (proj / "warehouse" / "candidates.jsonl").read_text()
    assert str(proj) not in raw


def test_upsert_by_platform_and_id(proj):
    a = warehouse.upsert([_item(views=100, views_source="platform_metadata", likes=7)], keywords=["q1"],
                         now="2026-09-20T00:00:00+00:00")
    assert a["new"] == ["youtube_SYNTHzzzz09"]
    b = warehouse.upsert([_item(views=250, views_source="platform_metadata", likes=9, title="new title")],
                         keywords=["q2"], now="2026-09-22T00:00:00+00:00")
    assert b == {"new": [], "updated": ["youtube_SYNTHzzzz09"]}
    rows = warehouse.load()
    assert len(rows) == 1
    r = rows[0]
    assert r["first_seen_at"] == "2026-09-20T00:00:00+00:00"
    assert r["views"] == 250 and r["views_checked_at"] == "2026-09-22T00:00:00+00:00"
    assert [h["views"] for h in r["views_history"]] == [100, 250]
    assert r["keywords"] == ["q1", "q2"] and r["title"] == "new title"
    # a later fetch WITHOUT views keeps the confirmed value and its check date
    warehouse.upsert([_item(views=None, likes=11)], now="2026-09-23T00:00:00+00:00")
    r = warehouse.load()[0]
    assert r["views"] == 250 and r["views_checked_at"] == "2026-09-22T00:00:00+00:00" and r["likes"] == 11
    # same platform_id on another platform is another candidate
    warehouse.upsert([_item(platform="tiktok")])
    assert len(warehouse.load()) == 2


def test_likes_and_reddit_score_never_become_views(proj, net):
    warehouse.upsert([_item(views=None, likes=123456)])
    r = warehouse.load()[0]
    assert r["views"] is None and r["views_source"] == "unavailable" and r["likes"] == 123456
    net.json[reddit.SEARCH_URL + "*"] = load_fixture("reddit_search.json")
    res = reddit.search("x", limit=10)
    warehouse.upsert(res.candidates, keywords=["x"])
    for rec in warehouse.load():
        if rec["platform"] == "reddit":
            assert rec["views"] is None and rec["views_source"] == "unavailable"
            assert rec["reddit_score"] is not None and rec["reddit_score"] != rec["views"]
            assert rec["views_history"] == []


def test_credits_original_author_vs_reposter(proj, net):
    net.extract["ytsearch2:cats"] = load_fixture("yt_search_flat.json")
    net.extract["https://www.youtube.com/shorts/SYNTHaaaa01"] = load_fixture("yt_info_SYNTHaaaa01.json")
    net.extract["https://www.youtube.com/watch?v=SYNTHbbbb02"] = load_fixture("yt_info_SYNTHbbbb02.json")
    res = youtube.search("cats", limit=2)
    warehouse.upsert(res.candidates)
    a = warehouse.get("youtube_SYNTHaaaa01")
    assert a["original_author"] == "@orig_cam_kr" and a["original_author_basis"] == "description_credit"
    assert a["reposter"] == "Repost Hub"
    b = warehouse.get("youtube_SYNTHbbbb02")
    assert b["original_author"] == "Cam Owner" and b["reposter"] is None
    assert b["original_author_basis"].startswith("uploader")


def test_extract_credits_patterns():
    cr = warehouse.extract_credits("영상 출처: https://example.org/v/1 thanks", "credit: @CamGuy / via @middle_acct")
    kinds = {(c["kind"], c["value"]) for c in cr}
    assert ("출처", "https://example.org/v/1") in kinds
    assert ("credit", "@CamGuy") in kinds and ("via", "@middle_acct") in kinds
    assert not any(c["kind"] == "mention" and c["value"].lower() == "@camguy" for c in cr)
    au = warehouse.authorship({"uploader": "reup"}, warehouse.extract_credits("filmed by @owner1"))
    assert au["original_author"] == "@owner1" and au["reposter"] == "reup"
    weak = warehouse.authorship({"uploader": "reup"}, warehouse.extract_credits("lol @only_one"))
    assert weak["original_author"] == "@only_one" and "약한" in weak["original_author_basis"]
    self_credit = warehouse.authorship({"uploader": "owner1"}, warehouse.extract_credits("credit: @owner1"))
    assert self_credit["reposter"] is None


def test_blocked_search_is_logged_and_other_platforms_continue(proj, net):
    net.extract["ytsearch3:cats"] = FakeDownloadError(BLOCKED_TEXT)
    net.json[reddit.SEARCH_URL + "*"] = load_fixture("reddit_search.json")
    rows = warehouse.run_search("cats", ["youtube", "reddit", "instagram"], limit=3, note="unit test")
    by = {r["platform"]: r for r in rows}
    assert by["youtube"]["access"]["platform_status"] == "blocked" and by["youtube"]["result_count"] == 0
    assert "Tunnel connection failed: 403" in by["youtube"]["access"]["note"]
    assert by["reddit"]["access"]["platform_status"] == "ok" and by["reddit"]["result_count"] == 3
    assert by["instagram"]["access"]["platform_status"] == "login_required"
    log = read_jsonl(proj / "warehouse" / "search_log.jsonl")
    assert [r["platform"] for r in log] == ["youtube", "reddit", "instagram"]
    for r in log:
        assert {"at", "platform", "query", "result_count", "access"} <= set(r)
        assert r["query"] == "cats" and r["note"] == "unit test"
    assert all(c["platform"] == "reddit" for c in warehouse.load())


def test_intake_url_blocked_makes_honest_stub(proj, net):
    net.extract["https://www.youtube.com/shorts/SYNTHeeee05"] = FakeDownloadError(BLOCKED_TEXT)
    rec, row = warehouse.intake_url("https://www.youtube.com/shorts/SYNTHeeee05", keywords=["manual"])
    assert rec["id"] == "youtube_SYNTHeeee05"
    assert rec["views"] is None and rec["views_source"] == "unavailable"
    assert rec["access"]["platform_status"] == "blocked"
    assert row["kind"] == "manual_intake" and row["access"]["platform_status"] == "blocked"


def test_url_exclusion_rule_at_intake(proj, net):
    (proj / "warehouse" / "exclusions.jsonl").write_text(json.dumps(
        {"kind": "url", "url": "https://youtu.be/SYNTHaaaa01", "reason": "reference uses this", "added_at": "x",
         "added_by": "test"}) + "\n")
    net.extract["ytsearch1:cats"] = {"entries": [load_fixture("yt_search_flat.json")["entries"][0]]}
    net.extract["https://www.youtube.com/shorts/SYNTHaaaa01"] = load_fixture("yt_info_SYNTHaaaa01.json")
    warehouse.run_search("cats", ["youtube"], limit=1)
    rec = warehouse.get("youtube_SYNTHaaaa01")
    assert rec["status"] == "excluded"
    assert rec["reference_overlap"]["excluded"] is True and rec["reference_overlap"]["method"] == "url"
