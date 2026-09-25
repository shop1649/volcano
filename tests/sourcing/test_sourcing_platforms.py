"""Platform adapters against SYNTHETIC fixtures (documented yt-dlp / Reddit field names)."""
from __future__ import annotations

import urllib.parse

from sourcing_fixtures import BLOCKED_TEXT, FakeDownloadError, load_fixture

from shortkit.sourcing import platforms
from shortkit.sourcing.platforms import instagram, reddit, tiktok, youtube


def _yt(net, blocked_item=True):
    net.extract["ytsearch3:cats"] = load_fixture("yt_search_flat.json")
    net.extract["ytsearchdate3:cats"] = load_fixture("yt_search_flat.json")
    net.extract["https://www.youtube.com/shorts/SYNTHaaaa01"] = load_fixture("yt_info_SYNTHaaaa01.json")
    net.extract["https://www.youtube.com/watch?v=SYNTHbbbb02"] = load_fixture("yt_info_SYNTHbbbb02.json")
    net.extract["https://www.youtube.com/watch?v=SYNTHcccc03"] = FakeDownloadError(BLOCKED_TEXT)


def test_youtube_search_views_and_likes_separate(net):
    _yt(net)
    res = youtube.search("cats", limit=3)
    assert res.access["platform_status"] == "ok"
    assert res.request == "ytsearch3:cats"
    by = {c["platform_id"]: c for c in res.candidates}
    a = by["SYNTHaaaa01"]
    assert a["views"] == 1520000 and a["views_source"] == "platform_metadata" and a["views_field"] == "view_count"
    assert a["likes"] == 88000
    assert a["published_at"].startswith("2026-09-2") and a["published_at_source"] == "timestamp"
    assert (a["width"], a["height"], a["duration"]) == (1080, 1920, 31.0)
    # B: metadata has likes but no view_count -> views unknown, likes NOT used
    b = by["SYNTHbbbb02"]
    assert b["views"] is None and b["views_source"] == "unavailable" and b["likes"] == 5000
    assert b["published_at"] == "2024-01-01" and b["published_at_source"] == "upload_date"


def test_youtube_listing_view_count_not_trusted_when_item_fails(net):
    _yt(net)
    res = youtube.search("cats", limit=3)
    c = {x["platform_id"]: x for x in res.candidates}["SYNTHcccc03"]
    assert c["views"] is None and c["views_source"] == "unavailable"
    assert res.item_errors and res.item_errors[0]["platform_status"] == "blocked"
    # the approximate listing value (999 on entry A's listing) is never the stored views
    assert {x["platform_id"]: x for x in res.candidates}["SYNTHaaaa01"]["views"] == 1520000


def test_youtube_recent_uses_date_sorted_search(net):
    _yt(net)
    res = youtube.search("cats", limit=3, recent_only=True)
    assert res.request == "ytsearchdate3:cats"


def test_youtube_search_blocked(net):
    net.extract["ytsearch5:cats"] = FakeDownloadError(BLOCKED_TEXT)
    res = youtube.search("cats", limit=5)
    assert res.access["platform_status"] == "blocked"
    assert "Tunnel connection failed: 403" in res.access["note"]
    assert res.candidates == []


def test_tiktok_request_forms():
    assert tiktok.build_request("Funny Cats") == ("hashtag", "https://www.tiktok.com/tag/funnycats")
    assert tiktok.build_request("#고양이 영상")[0] == "hashtag"
    assert tiktok.build_request("@some.user") == ("user", "https://www.tiktok.com/@some.user")
    assert tiktok.build_request("https://www.tiktok.com/@a/video/123")[0] == "url"
    assert tiktok.build_request("https://vm.tiktok.com/ZMabc/")[0] == "url"


def test_tiktok_views_from_play_count_only(net):
    net.extract["https://www.tiktok.com/tag/synthetictag"] = load_fixture("tiktok_tag_flat.json")
    for i in ("7400000000000000001", "7400000000000000002"):
        info = load_fixture(f"tiktok_info_{i}.json")
        net.extract[info["webpage_url"]] = info
    res = tiktok.search("synthetic tag", limit=5)
    assert res.access["platform_status"] == "ok"
    by = {c["platform_id"]: c for c in res.candidates}
    one = by["7400000000000000001"]
    assert one["views"] == 2300000 and one["views_field"] == "play_count" and one["likes"] == 410000
    two = by["7400000000000000002"]
    assert two["views"] is None and two["likes"] == 77000     # likes never become views
    # yt-dlp marks tiktok:tag as not working in the installed version -> recorded as a note
    assert any("tiktok:tag" in n for n in res.notes) or platforms.extractor_status(
        "https://www.tiktok.com/tag/x")[1] is not False


def test_instagram_hashtag_needs_login_without_network(net):
    res = instagram.search("#cats", limit=5)
    assert res.access["platform_status"] == "login_required"
    assert "local.yaml" in res.access["note"]
    assert net.calls == []                                   # no request was made


def test_instagram_hashtag_with_cookies_calls_extractor(net, proj):
    (proj / "cookies_ig.txt").write_text("# Netscape HTTP Cookie File (synthetic)\n")
    (proj / "local.yaml").write_text("sourcing:\n  cookies:\n    instagram: cookies_ig.txt\n")
    net.extract["https://www.instagram.com/explore/tags/cats/"] = {"_type": "playlist", "entries": [
        {"_type": "url", "id": "C0SYNTHrl01", "url": "https://www.instagram.com/reel/C0SYNTHrl01/"}]}
    net.extract["https://www.instagram.com/reel/C0SYNTHrl01/"] = load_fixture("instagram_reel_info.json")
    res = instagram.search("cats", limit=3)
    assert res.access["platform_status"] == "ok"
    assert net.calls[0][3] and net.calls[0][3].endswith("cookies_ig.txt")
    c = res.candidates[0]
    assert c["views"] is None and c["likes"] == 45000 and c["views_source"] == "unavailable"


def test_instagram_reel_url_without_login(net):
    net.extract["https://www.instagram.com/reel/C0SYNTHrl01/"] = load_fixture("instagram_reel_info.json")
    res = instagram.search("https://www.instagram.com/reel/C0SYNTHrl01/", limit=1)
    assert res.mode == "url" and res.access["platform_status"] == "ok"


def test_reddit_video_posts_views_null_and_score_separate(net):
    net.json[reddit.SEARCH_URL + "*"] = load_fixture("reddit_search.json")
    res = reddit.search("cats", limit=10)
    assert res.access["platform_status"] == "ok"
    kind, url, headers = net.calls[0]
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
    assert q["sort"] == ["top"] and q["t"] == ["month"] and q["q"] == ["cats"]
    assert "shortkit" in headers["User-Agent"]
    ids = [c["platform_id"] for c in res.candidates]
    assert ids == ["syn001", "syn002", "syn005"]              # text/image posts dropped
    for c in res.candidates:
        assert c["views"] is None and c["views_source"] == "unavailable"
        assert c["likes"] is None
    by = {c["platform_id"]: c for c in res.candidates}
    assert by["syn001"]["reddit_score"] == 45210
    assert by["syn005"]["reddit_score"] == 321               # hypothetical view_count=123456 ignored
    assert (by["syn001"]["width"], by["syn001"]["height"], by["syn001"]["duration"]) == (720, 1280, 27.0)
    assert by["syn002"]["original_url"] == "https://www.youtube.com/watch?v=SYNTHdddd04"
    assert by["syn005"]["original_author_hint"]["name"] == "first_poster"


def test_reddit_recent_query_and_blocked(net):
    net.json[reddit.SEARCH_URL + "*"] = OSError("<urlopen error Tunnel connection failed: 403 Forbidden>")
    res = reddit.search("cats", limit=3, recent_only=True)
    assert res.access["platform_status"] == "blocked"
    q = urllib.parse.parse_qs(urllib.parse.urlsplit(net.calls[0][1]).query)
    assert q["sort"] == ["new"] and q["t"] == ["week"]


def test_classify_error():
    assert platforms.classify_error(FakeDownloadError(BLOCKED_TEXT))["platform_status"] == "blocked"
    assert platforms.classify_error("HTTP Error 403: Forbidden")["platform_status"] == "blocked"
    li = platforms.classify_error("ERROR: [youtube] x: Sign in to confirm you're not a bot. Use --cookies")
    assert li["platform_status"] == "login_required"
    ig = platforms.classify_error("ERROR: [Instagram] x: Requested content is not available, rate-limit reached "
                                  "or login required")
    assert ig["platform_status"] == "login_required"
    other = platforms.classify_error(ValueError("boom"))
    assert other["platform_status"] == "error" and "boom" in other["note"]


def test_url_key_equality():
    k = platforms.url_key
    assert k("https://youtu.be/SYNTHaaaa01?t=3") == k("https://www.youtube.com/shorts/SYNTHaaaa01") \
        == k("https://m.youtube.com/watch?v=SYNTHaaaa01&feature=share") == "youtube:SYNTHaaaa01"
    assert k("https://www.tiktok.com/@a/video/123?lang=en") == "tiktok:123"
    assert k("https://www.instagram.com/reel/ABC/") == k("https://instagram.com/p/ABC") == "instagram:ABC"
    assert k("https://old.reddit.com/r/x/comments/abc12/t/") == "reddit:abc12"
    # not an 11-char video id -> no truncation into a wrong id
    assert k("https://www.youtube.com/shorts/SYNTHaaaa01X") == "youtube.com/shorts/SYNTHaaaa01X"


def test_scrub_keeps_urls_removes_machine_paths(proj):
    t = platforms.scrub(f"ffmpeg -i {proj}/warehouse/sources/a.mp4 /home/bob/x /tmp/y.mp4 "
                        "https://example.com/home/page https://x.org/tmp/v")
    assert str(proj) not in t and "/home/bob" not in t and "/tmp/y.mp4" not in t
    assert "warehouse/sources/a.mp4" in t
    assert "https://example.com/home/page" in t and "https://x.org/tmp/v" in t


def test_empty_listing_from_broken_extractor_is_error_not_ok(net, proj, monkeypatch, capsys):
    """S5-12: tiktok:tag / instagram:user are marked not working by yt-dlp; an EMPTY listing from them is not
    'ok, 0 results' (SYNTHETIC empty listings; extractor status forced so the test does not depend on the
    installed yt-dlp version)."""
    from shortkit.cli import main
    from shortkit.sourcing import warehouse
    from shortkit.util.jsonio import read_jsonl

    monkeypatch.setattr(platforms, "extractor_status", lambda url: (
        ("tiktok:tag", False) if "/tag/" in url else ("instagram:user", False) if "instagram.com/some" in url
        else ("x", True)))
    net.extract["https://www.tiktok.com/tag/funnycats"] = {"_type": "playlist", "entries": []}
    res = tiktok.search("funny cats", limit=5)
    assert res.access["platform_status"] == "error"
    assert "tiktok:tag" in res.access["note"] and "@계정" in res.access["note"] and "add-url" in res.access["note"]
    (proj / "cookies_ig.txt").write_text("# Netscape HTTP Cookie File (synthetic)\n")
    (proj / "local.yaml").write_text("sourcing:\n  cookies:\n    instagram: cookies_ig.txt\n")
    net.extract["https://www.instagram.com/some.user/"] = {"_type": "playlist", "entries": []}
    res = instagram.search("@some.user", limit=5)
    assert res.access["platform_status"] == "error" and "instagram:user" in res.access["note"]
    # a working extractor with an empty listing is a real 'ok, 0 results'
    net.extract["https://www.tiktok.com/@nobody"] = {"_type": "playlist", "entries": []}
    assert tiktok.search("@nobody", limit=5).access["platform_status"] == "ok"
    # CLI: not counted as success; the search log says error
    assert main(["source", "search", "-q", "funny cats", "--platform", "tiktok"]) == 1
    out = capsys.readouterr().out
    assert "오류" in out and "결과 0건" in out
    log = read_jsonl(proj / "warehouse" / "search_log.jsonl")
    assert log[-1]["access"]["platform_status"] == "error"
    assert warehouse.read_log("tiktok")[-1]["result_count"] == 0
