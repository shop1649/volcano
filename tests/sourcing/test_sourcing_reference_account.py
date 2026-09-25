"""The reference channel itself is never a source (clearly labelled SYNTHETIC fixtures; no network).

``ref trace`` writes an ``account`` row to warehouse/exclusions.jsonl naming the reference channel
({kind: account, platform: youtube, handle, channel_url, channel_ids}).  A candidate uploaded by that channel
(its own upload or its re-upload of someone's clip -- either way the reference's edit) must be excluded by
``exclusions.check`` / ``warehouse.upsert`` and refused by ``episode validate``."""
from __future__ import annotations

import json

from shortkit.sourcing import exclusions as X
from shortkit.sourcing import warehouse as wh

ACCOUNT = {"kind": "account", "platform": "youtube", "handle": "@joshuamagazine",
           "channel_url": "https://youtube.com/@joshuamagazine", "channel_ids": ["UC_SYNTHETIC_REF_CHANNEL0"],
           "reason": "레퍼런스 채널 자체", "added_by": "shortkit ref trace"}


def _item(pid, **kw):
    base = {"platform": "youtube", "platform_id": pid, "url": f"https://www.youtube.com/watch?v={pid}",
            "title": "synthetic fixture", "uploader": "someone else", "uploader_id": "@someoneelse",
            "uploader_url": "https://www.youtube.com/@someoneelse", "channel": "someone else", "views": None}
    base.update(kw)
    return base


def test_account_rule_matches_handle_id_and_url(proj):
    ents = [ACCOUNT]
    assert X.check_account({"platform": "youtube", "uploader_id": "@JoshuaMagazine"}, ents)["excluded"] is True
    assert X.check_account({"platform": "youtube", "uploader": "x", "uploader_url":
                            "https://www.youtube.com/channel/UC_SYNTHETIC_REF_CHANNEL0"}, ents)["excluded"] is True
    assert X.check_account({"platform": "youtube", "channel_url": "https://m.youtube.com/@joshuamagazine/"},
                           ents)["excluded"] is True
    assert X.check_account({"platform": "youtube", "uploader_id": "@joshuamagazine_fan"}, ents) is None
    assert X.check_account({"platform": "youtube", "uploader_id": "@someoneelse"}, ents) is None


def test_check_and_upsert_exclude_reference_channel_uploads(proj):
    (proj / "warehouse/exclusions.jsonl").write_text(json.dumps(ACCOUNT, ensure_ascii=False) + "\n")
    r = X.check(_item("AAAAAAAAAA1", uploader_id="@joshuamagazine"))
    assert r["excluded"] is True and r["method"] == "account"
    wh.upsert([_item("AAAAAAAAAA1", uploader="Joshua Magazine", uploader_id="@joshuamagazine"),
               _item("BBBBBBBBBB2")])
    recs = {x["platform_id"]: x for x in wh.load()}
    assert recs["AAAAAAAAAA1"]["status"] == "excluded"
    assert recs["AAAAAAAAAA1"]["reference_overlap"]["method"] == "account"
    assert recs["BBBBBBBBBB2"]["status"] == "candidate"


def test_validate_refuses_reference_channel_source(proj):
    """``episode validate`` re-checks the rule on every run (the row may be added after intake)."""
    from shortkit.edit.validate import reference_account_hit

    rec = {"id": "youtube_AAAAAAAAAA1", "platform": "youtube", "uploader_id": "@joshuamagazine",
           "status": "selected", "reference_overlap": {"excluded": False}}
    assert reference_account_hit(rec) is None
    (proj / "warehouse/exclusions.jsonl").write_text(json.dumps(ACCOUNT, ensure_ascii=False) + "\n")
    assert reference_account_hit(rec)["excluded"] is True
