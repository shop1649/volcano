"""S5-08: step 1 of the cleaning order (use a clean original) must be reachable through the CLI.

SYNTHETIC warehouse records only (no network, no media)."""
from __future__ import annotations

import pytest

from shortkit.cli import main
from shortkit.sourcing import warehouse


def _item(pf, pid, url, **kw):
    it = {"platform": pf, "platform_id": pid, "url": url, "title": "t", "uploader": "reup_hub",
          "published_at": "2026-09-20T00:00:00+00:00", "_item_access": {"platform_status": "ok", "note": ""}}
    it.update(kw)
    return it


@pytest.fixture
def pair(proj):
    dirty = warehouse.build_record(_item("tiktok", "7411111111111111111",
                                         "https://www.tiktok.com/@reup_hub/video/7411111111111111111"))
    dirty.update(download_path="warehouse/sources/tiktok_7411111111111111111.mp4", sha256="d" * 64)
    clean = warehouse.build_record(_item("youtube", "SYNTHorig01", "https://www.youtube.com/shorts/SYNTHorig01",
                                         uploader="orig_cam"))
    warehouse.save([dirty, clean])
    return dirty["id"], clean["id"]


def test_link_original_records_alternate_and_next_steps(pair, capsys):
    d, c = pair
    assert main(["source", "link-original", d, c, "--by", "tester", "--note", "두 영상 모두 봄, 같은 장면"]) == 0
    out = capsys.readouterr().out
    assert f"source download {c}" in out and "clean plan" in out and f"source select {c}" in out
    dirty, clean = warehouse.get(d), warehouse.get(c)
    assert dirty["alternates"][0]["id"] == c and dirty["alternates"][0]["linked_by"] == "tester"
    assert clean["alternate_of"] == [d]
    # clean plan's lookup resolves the linked record's file and hash once it is downloaded
    from shortkit.clean.cli import find_alternates

    clean["download_path"], clean["sha256"] = "warehouse/sources/youtube_SYNTHorig01.mp4", "c" * 64
    rows = [r if r["id"] != c else clean for r in warehouse.load()]
    warehouse.save(rows)
    alts = find_alternates("d" * 64)
    assert alts == [{"warehouse_id": c, "path": "warehouse/sources/youtube_SYNTHorig01.mp4", "sha256": "c" * 64,
                     "status": "candidate", "linked_by": "tester"}]
    # linking again does not duplicate; --unlink removes
    assert main(["source", "link-original", d, c, "--by", "tester", "--note", "다시"]) == 0
    assert len(warehouse.get(d)["alternates"]) == 1
    assert main(["source", "link-original", d, c, "--by", "tester", "--note", "잘못 연결", "--unlink"]) == 0
    assert warehouse.get(d)["alternates"] == [] and warehouse.get(c)["alternate_of"] == []


def test_link_original_refusals(pair, capsys):
    d, c = pair
    assert main(["source", "link-original", d, d, "--by", "t", "--note", "x"]) == 1
    assert main(["source", "link-original", d, c, "--by", "t", "--note", "  "]) == 1
    with pytest.raises(SystemExit):
        main(["source", "link-original", d, c, "--note", "x"])          # --by is required
    rec = warehouse.get(c)
    warehouse.apply_overlap(rec, {"excluded": True, "matched_ref_video_id": "REF1", "method": "phash", "distance": 2})
    warehouse.put(rec)
    assert main(["source", "link-original", d, c, "--by", "t", "--note", "x"]) == 1
    assert "레퍼런스" in capsys.readouterr().out
    assert main(["source", "link-original", d, "nope_1", "--by", "t", "--note", "x"]) == 1


def _doc(sha):
    return {"source": {"sha256": sha}, "overlays": [{"id": "ov1", "kind": "watermark", "text": "@orig_cam"}]}


def test_clean_plan_suggests_how_to_get_the_original(pair):
    from shortkit.clean.cli import original_suggestions

    d, c = pair
    # original URL in the dirty record and that item already in the warehouse -> link it
    rec = warehouse.get(d)
    rec["original_url"] = "https://youtu.be/SYNTHorig01"
    warehouse.put(rec)
    tips = original_suggestions("d" * 64, _doc("d" * 64))
    assert any(f"source link-original {d} {c}" in t for t in tips), tips
    # original URL not in the warehouse yet -> add-url first
    rec["original_url"] = "https://www.instagram.com/reel/SYNTHnotyet/"
    warehouse.put(rec)
    tips = original_suggestions("d" * 64, _doc("d" * 64))
    assert any("source add-url https://www.instagram.com/reel/SYNTHnotyet/" in t for t in tips), tips
    # no overlays -> nothing to suggest; a file outside the warehouse -> register it first
    assert original_suggestions("d" * 64, {"overlays": []}) == []
    assert any("add-url" in t for t in original_suggestions("0" * 64, _doc("0" * 64)))
    # once an original is linked, no suggestion
    warehouse.link_original(d, c, by="t", note="same")
    assert original_suggestions("d" * 64, _doc("d" * 64)) == []
