"""S5-04: an uncredited re-upload of an old viral clip must not be labelled recent / original by the uploader.

All platform data here is SYNTHETIC (hand-written dicts shaped like yt-dlp info fields); no network."""
from __future__ import annotations

import datetime as dt
import json

from shortkit.sourcing import score, warehouse
from shortkit.sourcing.cli import select_candidate


def _ago(days: float) -> str:
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).replace(microsecond=0).isoformat()


QUALITY = {"measured_at": _ago(0), "width": 1080, "height": 1920, "bpp": 0.06, "sharpness_lapvar_p50": 300.0}


def _tiktok(**kw) -> dict:
    """SYNTHETIC TikTok item: uploader viralclips_daily, uploaded 3 days ago, no credit in the description."""
    it = {"platform": "tiktok", "platform_id": "7400000000000000001",
          "url": "https://www.tiktok.com/@viralclips_daily/video/7400000000000000001", "title": "wait for it 😱",
          "description": "wait for it #fyp #viral", "uploader": "viralclips_daily", "uploader_id": "viralclips_daily",
          "views": 2_300_000, "views_source": "platform_metadata", "views_field": "view_count",
          "published_at": _ago(3), "width": 1080, "height": 1920, "duration": 21.0,
          "_item_access": {"platform_status": "ok", "note": ""}}
    it.update(kw)
    return it


def _review(**kw) -> dict:
    r = {"watched_by": "tester", "watched_at": _ago(0), "intensity": 4, "reversal": 4, "format_fit": 4,
         "notes": "TikTok watermark @realcreator2019 visible; clip looks like the 2019 viral", "watermark": "present"}
    r.update(kw)
    return r


def test_watermark_of_another_account_marks_repost_and_blocks_recent(proj):
    """The finding's repro: watermark hint '@realcreator2019' != uploader.  Before: original_author =
    viralclips_daily, reposter None, recency 'recent', selection_reason '게시 3일 전(최근 ...)'."""
    rec = warehouse.build_record(_tiktok())
    rec["quality"] = {**QUALITY, "watermark_hint": {"status": "present", "texts": [
        {"corner": "top_left", "text": "@realcreator2019", "frames": 4}]}}
    rec["reference_overlap"] = {"excluded": False, "method": "phash", "distance": 30}
    rec["reviews"] = [_review()]
    warehouse.save([rec])
    ok, got, msgs = select_candidate(rec["id"], by="tester")
    assert not ok, msgs                                            # recency is 못 잼 now
    assert any("recency" in m and "재업로드" in m for m in msgs)
    assert got["reposter"] == "viralclips_daily"
    assert got["original_author"] == "@realcreator2019" and "watermark" in got["original_author_basis"]
    s = score.compute_scores(got)
    assert s["recency_label"] == "unknown" and s["recency"] is None
    # accepted knowingly -> the reason says re-upload, never '최근'
    ok, got, msgs = select_candidate(rec["id"], by="tester", accept=["recency"], reason="원본 게시일 확인 중")
    assert ok, msgs
    assert "(최근," not in got["selection_reason"] and "재업로드로 보이며 원본 게시일 모름" in got["selection_reason"]
    assert "재업로더 viralclips_daily" in got["selection_reason"]


def test_clean_detect_watermark_record_is_repost_evidence(proj):
    sha = "ab" * 32
    (proj / "warehouse/overlays").mkdir(parents=True)
    (proj / f"warehouse/overlays/{sha}.json").write_text(json.dumps({
        "schema": "shortkit.overlays/1", "algo": "shortkit.clean.detect/2", "source": {"sha256": sha},
        "overlays": [{"id": "ov1", "kind": "watermark", "text": "TikTok\n@realcreator2019", "corner": "top_left",
                      "rect": {"x": 0, "y": 0, "w": 10, "h": 10}, "start": 0, "end": 5}]}))
    rec = warehouse.build_record(_tiktok())
    rec["sha256"] = sha
    warehouse.refresh_scores(rec)
    assert rec["reposter"] == "viralclips_daily" and rec["original_author"] == "@realcreator2019"
    ev = rec["repost_evidence"][0]
    assert ev["same_as_uploader"] is False and ev["sources"] == ["clean_detect:ov1"]
    assert rec["scores"]["recency_label"] == "unknown"
    # the original's publish date (from a review) decides: 2019 -> old
    rec["original_published_at"] = "2019-06-01"
    warehouse.refresh_scores(rec)
    assert rec["scores"]["recency_label"] == "old"


def test_own_watermark_is_not_repost_and_ocr_variants_match(proj):
    for text in ("@viralclips_daily", "@viralclips daily", "@viralc1ips_daily"):
        rec = warehouse.build_record(_tiktok())
        rec["quality"] = {**QUALITY, "watermark_hint": {"status": "present", "texts": [
            {"corner": "top_left", "text": text, "frames": 4}]}}
        warehouse.refresh_scores(rec)
        assert rec["reposter"] is None, text
        assert rec["repost_evidence"][0]["same_as_uploader"] is True


def test_recent_needs_reviewer_to_confirm_original_upload(proj):
    rec = warehouse.build_record(_tiktok(uploader="cam_owner", uploader_id="cam_owner",
                                         url="https://www.tiktok.com/@cam_owner/video/7400000000000000001"))
    r = score.recency_for(rec)
    assert r["label"] == "unknown" and r["basis"] == "recent_upload_originality_unconfirmed"
    assert r["upload_age_days"] is not None and 2.5 < r["upload_age_days"] < 3.5
    rec["reviews"] = [_review(notes="원본 계정 확인, 이전 업로드 없음", watermark="absent", original_upload="yes")]
    warehouse.refresh_scores(rec)
    assert rec["scores"]["recency_label"] == "recent" and rec["reposter"] is None
    txt = score.selection_reason(rec, score.compute_scores(rec))
    assert "최근, 검토자가 원본 업로드로 확인" in txt
    # reviewer says it is a re-upload (no watermark, no credit): re-upload, original author unknown
    rec["reviews"].append(_review(notes="2019년 영상 재업로드", watermark="absent", original_upload="no"))
    warehouse.refresh_scores(rec)
    assert rec["reposter"] == "cam_owner" and rec["original_author"] is None
    assert "review_not_original" in rec["original_author_basis"] and rec["scores"]["recency_label"] == "unknown"
    # an old upload is old whatever the answer
    old = warehouse.build_record(_tiktok(published_at=_ago(900)))
    assert score.recency_for(old)["label"] == "old"


def test_reviewer_yes_overrides_watermark_but_not_a_description_credit(proj):
    rec = warehouse.build_record(_tiktok())
    rec["reviews"] = [_review(watermark_handle="@realcreator2019", original_upload="yes",
                              notes="워터마크는 같은 사람의 예전 계정, 원본 업로드 확인")]
    warehouse.refresh_scores(rec)
    assert rec["reposter"] is None and "review_original_upload" in rec["original_author_basis"]
    assert rec["scores"]["recency_label"] == "recent"
    credited = warehouse.build_record(_tiktok(description="credit: @realcreator2019"))
    credited["reviews"] = [_review(original_upload="yes")]
    warehouse.refresh_scores(credited)
    assert credited["reposter"] == "viralclips_daily" and credited["scores"]["recency_label"] == "unknown"


def test_cli_review_original_upload_and_watermark_handle(proj, capsys):
    from shortkit.cli import main

    rec = warehouse.build_record(_tiktok())
    warehouse.save([rec])
    cid = rec["id"]
    assert main(["source", "review", cid, "--watched-by", "tester", "--intensity", "4", "--reversal", "4",
                 "--format-fit", "4", "--notes", "워터마크 @realcreator2019", "--watermark-handle", "@realcreator2019",
                 "--original-upload", "no"]) == 0
    out = capsys.readouterr().out
    assert "재업로드: 원본 게시일 모름" in out and "재업로더 viralclips_daily" in out
    got = warehouse.get(cid)
    assert got["reviews"][-1]["original_upload"] == "no" and got["reviews"][-1]["watermark_handle"] == "@realcreator2019"
    assert got["original_author"] == "@realcreator2019" and got["scores"]["recency_label"] == "unknown"
