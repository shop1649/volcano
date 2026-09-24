"""`shortkit source ...` end-to-end in a temp project root with a fake (blocked / synthetic) network."""
from __future__ import annotations

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
