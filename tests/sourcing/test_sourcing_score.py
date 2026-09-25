"""Views ranking, recency labels, review-gated selection."""
from __future__ import annotations

import datetime as dt

import pytest

from shortkit.sourcing import score, warehouse
from shortkit.sourcing.cli import select_candidate

NOW = dt.datetime(2026, 9, 24, 12, 0, tzinfo=dt.timezone.utc)


def _iso(days_ago: float) -> str:
    return (NOW - dt.timedelta(days=days_ago)).replace(microsecond=0).isoformat()


def _c(cid, platform="youtube", views=None, src=None, **kw):
    c = {"id": cid, "platform": platform, "views": views,
         "views_source": src or ("platform_metadata" if views is not None else "unavailable"),
         "views_checked_at": _iso(0) if views is not None else None, "first_seen_at": kw.pop("seen", _iso(1)),
         "status": "candidate"}
    c.update(kw)
    return c


def test_rank_by_confirmed_views_unknown_after_and_flagged():
    cands = [_c("y_low", views=10), _c("y_unk1", seen=_iso(3)), _c("y_high", views=5_000_000),
             _c("y_unk2", seen=_iso(1)), _c("y_fake", views=999_999_999, src="unavailable"),
             _c("r1", platform="reddit", reddit_score=99999), _c("t1", platform="tiktok", views=7)]
    rows = score.rank_by_views(cands)
    yt = [r for r in rows if r["platform"] == "youtube"]
    assert [r["id"] for r in yt] == ["y_high", "y_low", "y_unk1", "y_fake", "y_unk2"]
    assert [r["rank"] for r in yt][:2] == [1, 2]
    for r in yt[2:]:
        assert r["rank"] is None and "views_unknown" in r["flags"] and r["views"] is None
    # views without platform_metadata source are not "confirmed" (never ranked above real counts)
    assert next(r for r in yt if r["id"] == "y_fake")["rank"] is None
    rd = [r for r in rows if r["platform"] == "reddit"]
    assert rd[0]["rank"] is None and "reddit_score_is_not_views" in rd[0]["flags"]
    # ranks restart per platform
    assert next(r for r in rows if r["id"] == "t1")["rank"] == 1


def test_recency_labels_old_viral_is_never_recent():
    old = score.recency(_iso(400), checked_at=NOW.isoformat(), days=30)
    assert old["label"] == "old" and old["score"] == 0.0
    fresh = score.recency(_iso(3), checked_at=NOW.isoformat(), days=30)
    assert fresh["label"] == "recent" and fresh["age_days"] == pytest.approx(3.0)
    unk = score.recency(None, checked_at=NOW.isoformat())
    assert unk["label"] == "unknown" and unk["score"] is None
    date_only = score.recency("2026-09-20", checked_at=NOW.isoformat(), days=30)
    assert date_only["label"] == "recent"
    # an old viral record: huge views, first seen today -> still 'old'
    c = _c("viral", views=80_000_000, published_at=_iso(700), seen=_iso(0))
    s = score.compute_scores(c, checked_at=NOW.isoformat())
    assert s["recency_label"] == "old"


def _good_review(**kw):
    # original_upload: the reviewer answered "this is the original upload" (needed before 'recent', S5-04)
    r = {"watched_by": "tester", "watched_at": _iso(0), "intensity": 4, "reversal": 3, "format_fit": 5,
         "notes": "3초에 차가 미끄러지고 8초에 반전", "watermark": "absent", "original_upload": "yes"}
    r.update(kw)
    return r


def _cand(**kw):
    c = warehouse.build_record({"platform": "youtube", "platform_id": "SYNTHsel001",
                                "url": "https://www.youtube.com/watch?v=SYNTHsel001", "title": "t",
                                "uploader": "u", "views": 1234567, "views_source": "platform_metadata",
                                "views_field": "view_count", "likes": 4321,
                                "published_at": (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=5))
                                .replace(microsecond=0).isoformat(),
                                "width": 1080, "height": 1920, "duration": 30.0,
                                "_item_access": {"platform_status": "ok", "note": ""}})
    c.update(kw)
    return c


def test_select_refuses_without_review(proj):
    warehouse.save([_cand()])
    ok, rec, msgs = select_candidate("youtube_SYNTHsel001", accept=["reference_overlap", "quality"], reason="x")
    assert not ok and rec["status"] == "candidate"
    assert any("못 잼" in m and "검토" in m for m in msgs)
    assert score.compute_scores(rec)["intensity"] is None
    assert set(score.compute_scores(rec)["unmeasured"]) >= {"intensity", "reversal", "format_fit"}


def test_select_refuses_incomplete_review(proj):
    warehouse.save([_cand(reviews=[_good_review(watched_by=""), _good_review(notes=" ")])])
    ok, _, msgs = select_candidate("youtube_SYNTHsel001", accept=["reference_overlap", "quality"], reason="x")
    assert not ok and any("watched_by" in m or "notes" in m for m in msgs)


def test_select_needs_explicit_acceptance_of_unmeasured_items(proj):
    warehouse.save([_cand(reviews=[_good_review()])])
    ok, _, msgs = select_candidate("youtube_SYNTHsel001")
    assert not ok
    assert any("reference_overlap" in m for m in msgs) and any("quality" in m for m in msgs)
    ok, _, msgs = select_candidate("youtube_SYNTHsel001", accept=["reference_overlap", "quality"])
    assert not ok and any("사유" in m for m in msgs)            # reason is mandatory
    ok, rec, msgs = select_candidate("youtube_SYNTHsel001", by="tester", accept=["reference_overlap", "quality"],
                                     reason="레퍼런스 지문 미확보 상태에서 테스트")
    assert ok and rec["status"] == "selected"
    reason = rec["selection_reason"]
    assert "1,234,567" in reason and "tester" in reason and "좋아요 4,321(조회수와 별개)" in reason
    assert "레퍼런스 중복 여부 못 잼" in reason and "못 잼 항목을 알고 선택" in reason
    assert rec["scores"]["total"] is None                      # quality unmeasured -> no total
    assert [a["key"] for a in rec["selection"]["accepted_unmeasured"]] == ["reference_overlap", "quality"]


def test_excluded_can_never_be_selected(proj):
    c = _cand(reviews=[_good_review()])
    warehouse.apply_overlap(c, {"excluded": True, "matched_ref_video_id": "REF1", "method": "phash", "distance": 2})
    warehouse.save([c])
    ok, rec, msgs = select_candidate("youtube_SYNTHsel001", accept=["reference_overlap", "quality", "recency"],
                                     reason="x")
    assert not ok and rec["status"] == "excluded"
    assert any("같은 녹화" in m for m in msgs)


def test_total_only_when_everything_measured():
    c = _cand(reviews=[_good_review()], quality={"measured_at": _iso(0), "width": 1080, "height": 1920,
                                                 "bpp": 0.06, "sharpness_lapvar_p50": 300.0})
    c["reference_overlap"] = {"excluded": False, "method": "phash", "distance": 25}
    s = score.compute_scores(c)
    assert s["unmeasured"] == [] and s["total"] is not None and 0 < s["total"] <= 1
    assert s["quality"] == 1.0
    q = score.quality_score(_cand())
    assert q["score"] is None and {"bitrate", "sharpness"} <= set(q["unmeasured"])
    # reviewer says watermark present -> penalty
    c2 = _cand(reviews=[_good_review(watermark="present")], quality=c["quality"])
    assert score.quality_score(c2)["score"] == pytest.approx(score.WATERMARK_FACTOR)


def test_selection_reason_mentions_reddit_score_is_not_views():
    c = {"platform": "reddit", "views": None, "views_source": "unavailable", "reddit_score": 4521,
         "published_at": _iso(2), "reference_overlap": {"excluded": None}}
    s = score.compute_scores(c, checked_at=NOW.isoformat())
    txt = score.selection_reason(c, s)
    assert "조회수 확인 불가" in txt and "Reddit 점수 4521(조회수 아님)" in txt


def test_repost_recency_needs_original_date():
    # re-uploaded 2 days ago by a reposter, original unknown -> NOT recent
    c = {"published_at": _iso(2), "reposter": "reup_channel", "original_author": "@owner", "url": "u"}
    r = score.recency_for(c, checked_at=NOW.isoformat(), days=30)
    assert r["label"] == "unknown" and r["score"] is None and r["basis"] == "repost_without_original_date"
    old = score.recency_for({**c, "original_published_at": _iso(900)}, checked_at=NOW.isoformat(), days=30)
    assert old["label"] == "old" and old["basis"] == "original_published_at"
    fresh = score.recency_for({**c, "original_published_at": _iso(5)}, checked_at=NOW.isoformat(), days=30)
    assert fresh["label"] == "recent"
    ext = score.recency_for({"published_at": _iso(1), "url": "https://reddit.com/x",
                             "original_url": "https://youtube.com/watch?v=abc"}, checked_at=NOW.isoformat())
    assert ext["label"] == "unknown"


def test_status_guards_cannot_be_bypassed(proj):
    c = _cand()
    with pytest.raises(warehouse.SelectionError):
        warehouse.set_status(c, "selected", "x", "bypass attempt")
    with pytest.raises(warehouse.SelectionError):
        warehouse.set_status(c, "used", "x", "not selected")
    c2 = _cand(reviews=[_good_review()])
    warehouse.apply_overlap(c2, {"excluded": True, "matched_ref_video_id": "R", "method": "url"})
    with pytest.raises(warehouse.SelectionError):
        warehouse.set_status(c2, "selected", "x", "excluded")


def test_mark_used_after_select(proj):
    c = _cand(reviews=[_good_review()], reference_overlap={"excluded": False, "method": "phash", "distance": 30},
              quality={"measured_at": _iso(0), "width": 1080, "height": 1920, "bpp": 0.06,
                       "sharpness_lapvar_p50": 300.0})
    warehouse.save([c])
    with pytest.raises(warehouse.SelectionError):
        warehouse.mark_used(c["id"], "ep01")
    ok, rec, msgs = warehouse.select(c["id"], by="tester")
    assert ok, msgs
    assert rec["scores"]["total"] is not None and "종합" in rec["selection_reason"]
    used = warehouse.mark_used(c["id"], "ep01", by="tester")
    assert used["status"] == "used" and used["used_in"] == ["ep01"]


def test_cli_review_original_date_and_format_id(proj, capsys):
    from shortkit.cli import main

    warehouse.save([_cand(reposter="reup", original_author="@owner")])
    cid = "youtube_SYNTHsel001"
    assert main(["source", "review", cid, "--watched-by", "tester", "--intensity", "4", "--reversal", "4",
                 "--format-fit", "4", "--notes", "봤음", "--original-published-at", "not-a-date"]) == 1
    assert main(["source", "review", cid, "--watched-by", "tester", "--intensity", "4", "--reversal", "4",
                 "--format-fit", "4", "--notes", "봤음", "--format-id", "F1",
                 "--original-published-at", "2020-05-01"]) == 0
    out = capsys.readouterr().out
    assert "포맷 id" in out                                   # unverifiable format id is reported, not assumed
    rec = warehouse.get(cid)
    assert rec["original_published_at"] == "2020-05-01" and rec["scores"]["recency_label"] == "old"


def test_format_facts_use_reference_duration_distribution(proj):
    d = proj / "presets" / "fmt"
    d.mkdir(parents=True)
    (d / "preset.yaml").write_text("preset_id: fmt-v1\nstructure:\n  duration_s: {n: 12, p10: 20.0, p50: 31.0, "
                                   "p90: 44.0}\n")
    short = score.format_facts({"duration": 12.0, "width": 1080, "height": 1920}, "fmt")
    assert short["duration_enough"] is False and short["orientation"] == "vertical"
    assert short["reference_duration"]["p10"] == 20.0
    ok = score.format_facts({"duration": 25.0, "width": 1920, "height": 1080}, "fmt")
    assert ok["duration_enough"] is True
    missing = score.format_facts({"duration": 25.0}, "does-not-exist")
    assert missing["duration_enough"] is None
