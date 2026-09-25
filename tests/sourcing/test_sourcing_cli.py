"""`shortkit source ...` end-to-end in a temp project root with a fake (blocked / synthetic) network."""
from __future__ import annotations

import json

import pytest
from sourcing_fixtures import BLOCKED_TEXT, GEN, FakeDownloadError, load_fixture

from shortkit.cli import main
from shortkit.sourcing import score, warehouse
from shortkit.sourcing.platforms import reddit


def test_search_blocked_list_and_log(proj, net, capsys):
    net.extract["ytsearch2:cats"] = FakeDownloadError(BLOCKED_TEXT)
    net.json[reddit.SEARCH_URL + "*"] = load_fixture("reddit_search.json")
    rc = main(["source", "search", "--query", "cats", "--platform", "youtube", "reddit", "--limit", "2"])
    out = capsys.readouterr().out
    assert rc == 0                                         # reddit answered
    assert "[youtube] 'cats' → 접속: 차단됨, 결과 0건" in out and "Tunnel connection failed" in out
    assert "[reddit] 'cats' → 접속: 접속됨, 결과 2건" in out
    assert main(["source", "list"]) == 0
    out = capsys.readouterr().out
    assert "== reddit" in out and "Reddit 비공개" in out and "조회수 아님" in out
    assert main(["source", "log"]) == 0
    out = capsys.readouterr().out
    assert "youtube" in out and "차단됨" in out and "reddit" in out


def test_search_all_blocked_exit_code(proj, net, capsys):
    net.extract["ytsearch1:cats"] = FakeDownloadError(BLOCKED_TEXT)
    assert main(["source", "search", "-q", "cats", "--platform", "youtube", "--limit", "1"]) == 1


def test_queries_show_reference_derived_unmeasured(proj, capsys):
    assert main(["source", "queries"]) == 0
    assert "미확보(못 잼)" in capsys.readouterr().out
    assert main(["source", "queries", "--add", "dashcam", "--platform", "youtube", "--by", "tester"]) == 0
    out = capsys.readouterr().out
    assert "사용자 검색어 추가: dashcam" in out and "[사용자 검색어] 1개" in out


def test_review_argument_validation(proj, capsys):
    warehouse.upsert([{"platform": "reddit", "platform_id": "abc", "url": "https://www.reddit.com/r/x/comments/abc/",
                       "views": None, "views_source": "unavailable",
                       "_item_access": {"platform_status": "ok", "note": ""}}])
    with pytest.raises(SystemExit):
        main(["source", "review", "reddit_abc", "--watched-by", "a", "--intensity", "7", "--reversal", "1",
              "--format-fit", "1", "--notes", "x"])
    assert main(["source", "review", "reddit_abc", "--watched-by", " ", "--intensity", "3", "--reversal", "1",
                 "--format-fit", "1", "--notes", "x"]) == 1
    assert "watched_by" in capsys.readouterr().out
    assert score.review_of(warehouse.get("reddit_abc")) is None


@pytest.mark.slow
def test_manual_intake_review_select_flow(proj, net, clips, capsys):
    url = "https://www.youtube.com/shorts/SYNTHman001"
    net.extract[url] = FakeDownloadError(BLOCKED_TEXT)
    assert main(["source", "add-url", url, "--file", str(clips["head_pose"]), "--keyword", "manual"]) == 0
    out = capsys.readouterr().out
    assert "차단됨" in out and "warehouse/sources/youtube_SYNTHman001.mp4" in out
    cid = "youtube_SYNTHman001"
    assert main(["source", "select", cid]) == 1
    assert "검토" in capsys.readouterr().out
    assert main(["source", "review", cid, "--watched-by", "tester", "--intensity", "2", "--reversal", "1",
                 "--format-fit", "2", "--notes", "고정 카메라 인물 정면, 사건 없음", "--watermark", "absent"]) == 0
    capsys.readouterr()
    assert main(["source", "select", cid]) == 1             # overlap/recency unmeasured, not accepted
    out = capsys.readouterr().out
    assert "reference_overlap" in out and "recency" in out
    assert main(["source", "select", cid, "--by", "tester", "--accept-unmeasured", "reference_overlap,recency",
                 "--reason", "테스트: 레퍼런스 지문·게시일 미확보"]) == 0
    rec = warehouse.get(cid)
    assert rec["status"] == "selected" and "게시일 모름" in rec["selection_reason"]
    assert rec["quality"]["width"] == 640
    assert main(["source", "exclude-check", str(clips["head_pose"])]) == 4    # no fingerprints -> 못 잼
    assert "못 잼" in capsys.readouterr().out


@pytest.mark.slow
def test_watermark_hint_on_dirty_source():
    f = GEN / "dirty_source.mp4"
    if not f.is_file():
        pytest.skip("run `shortkit testassets dirty-source`")
    h = score.watermark_hint(f)
    assert h["status"] == "present"
    assert any(t["corner"] == "top_left" and "fake" in t["text"].lower() for t in h["texts"])


def test_list_views_limit_is_per_platform(proj, capsys):
    """S5-10: 60 Instagram candidates must not push the YouTube ranking out of the default view (SYNTHETIC)."""
    rows = []
    for i in range(60):
        rows.append(warehouse.build_record({"platform": "instagram", "platform_id": f"SYNTHig{i:03d}",
                                            "url": f"https://www.instagram.com/reel/SYNTHig{i:03d}/",
                                            "views": 1000 + i, "views_source": "platform_metadata",
                                            "_item_access": {"platform_status": "ok", "note": ""}}))
    for i in range(5):
        rows.append(warehouse.build_record({"platform": "youtube", "platform_id": f"SYNTHyt{i:04d}",
                                            "url": f"https://www.youtube.com/shorts/SYNTHyt{i:04d}",
                                            "views": 9_000_000 + i, "views_source": "platform_metadata",
                                            "_item_access": {"platform_status": "ok", "note": ""}}))
    warehouse.save(rows)
    assert main(["source", "list", "--sort", "views"]) == 0
    out = capsys.readouterr().out
    assert "== instagram" in out and "== youtube" in out
    assert "youtube_SYNTHyt0004" in out and "instagram 후보 10건 더 있음" in out
    assert main(["source", "list", "--sort", "views", "--limit", "3", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert sum(1 for d in data if d["id"].startswith("youtube_")) == 3
    assert sum(1 for d in data if d["id"].startswith("instagram_")) == 3
    assert [d["rank"] for d in data if d["id"].startswith("youtube_")] == [1, 2, 3]


def test_add_url_blocked_keeps_url_handle_and_manual_provenance(proj, net, tiny_clip, capsys):
    """S5-11: the fallback route for a blocked platform must store the provenance a person knows
    (SYNTHETIC URL; the platform call fails with the recorded proxy-block text)."""
    url = "https://www.tiktok.com/@somecreator/video/7412345678901234567"
    net.extract[url] = FakeDownloadError(BLOCKED_TEXT)
    assert main(["source", "add-url", url, "--file", str(tiny_clip)]) == 0
    out = capsys.readouterr().out
    assert "차단됨" in out
    rec = warehouse.get("tiktok_7412345678901234567")
    # before: uploader None, original_author None, basis 'unknown(메타데이터 없음)'
    assert rec["uploader"] == "@somecreator" and rec["extra"]["uploader_source"] == "url_path"
    assert rec["original_author"] == "@somecreator" and rec["original_author_basis"].startswith("uploader(")
    # manual provenance needs a named observer
    assert main(["source", "add-url", url, "--original-author", "@realcam"]) == 2
    assert main(["source", "add-url", url, "--views", "1200000"]) == 2              # no observer
    assert main(["source", "add-url", url, "--observed-by", "tester", "--views", "1200000"]) == 2  # no date
    capsys.readouterr()
    assert main(["source", "add-url", url, "--observed-by", "tester", "--original-author", "@realcam",
                 "--original-url", "https://www.instagram.com/reel/SYNTHorig9/", "--published-at", "2026-09-20",
                 "--original-published-at", "2021-03-02", "--views", "1200000", "--views-checked-at", "2026-09-25",
                 "--note", "브라우저로 게시 페이지를 직접 봄"]) == 0
    out = capsys.readouterr().out
    rec = warehouse.get("tiktok_7412345678901234567")
    assert rec["views"] is None and rec["views_source"] == "unavailable"        # platform-only field untouched
    assert rec["views_manual"] == {"views": 1200000, "checked_at": "2026-09-25", "observed_by": "tester",
                                   "where": url, "note": "사람이 직접 본 조회수(플랫폼 메타데이터 아님)"}
    assert rec["original_author"] == "@realcam" and rec["original_author_basis"] == "manual_observation(tester)"
    assert rec["reposter"] == "@somecreator" and rec["original_url"].endswith("SYNTHorig9/")
    assert rec["published_at"] == "2026-09-20" and rec["published_at_source"] == "manual_observation:tester"
    assert rec["scores"]["recency_label"] == "old"                            # judged by the original's 2021 date
    assert rec["manual_provenance"][-1]["by"] == "tester" and rec["download_path"]   # file link kept
    assert "1,200,000 (2026-09-25 수동)" in out
    rows = score.rank_by_views(warehouse.load())
    assert rows[0]["rank"] == 1 and rows[0]["flags"] == ["views_manual_observation"]
    # a later blocked re-intake does not wipe what is known
    assert main(["source", "add-url", url]) == 0
    assert warehouse.get("tiktok_7412345678901234567")["original_author"] == "@realcam"


def test_handle_from_url_forms():
    from shortkit.sourcing.platforms import handle_from_url

    assert handle_from_url("https://www.tiktok.com/@some.creator/video/1") == "@some.creator"
    assert handle_from_url("https://www.youtube.com/@CamOwner/shorts") == "@CamOwner"
    assert handle_from_url("https://www.youtube.com/shorts/SYNTHaaaa01") is None
    assert handle_from_url("https://www.instagram.com/cam_owner/reel/C0SYNTH/") == "@cam_owner"
    assert handle_from_url("https://www.instagram.com/reel/C0SYNTH/") is None
    assert handle_from_url("https://www.reddit.com/user/someone/") == "u/someone"
    assert handle_from_url("https://www.reddit.com/r/videos/comments/abc/x/") is None
