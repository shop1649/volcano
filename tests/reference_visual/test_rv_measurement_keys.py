"""Measurement items written by `ref aggregate`: format, blocker propagation, and key coverage.

Every key a measurement file emits must be a leaf key of presets/joshuamagazine/preset.yaml (else
`shortkit preset sync` silently drops it and the measurement never reaches production), and must be
a style key (not a meta / infra / rule key).  All snapshot data here is SYNTHETIC.
"""
from __future__ import annotations

import json

from shortkit import config
from shortkit.reference import aggregate as A
from shortkit.util.jsonio import read_yaml, write_json

P = "presets/joshuamagazine"
ITEM_FIELDS = {"key", "status", "value", "unit", "resolution", "overall", "by_format", "evidence", "method",
               "measured_at", "blocker"}
COLLECT_BLOCKER = "SYNTHETIC: Tunnel connection failed: 403 Forbidden"


def _items(proj) -> list[dict]:
    out = []
    for f in sorted((proj / P / "measurements").glob("visual_*.json")):
        d = json.loads(f.read_text("utf-8"))
        assert d["schema"] == "shortkit.measurement/1" and d["group"] == f.stem
        out += d["items"]
    return out


def test_blocked_collect_makes_every_item_unmeasured_with_the_collect_blocker(proj):
    write_json(proj / P / "reference/latest100.json", {"status": "blocked", "blocker": COLLECT_BLOCKER,
                                                       "captured_at": "2026-09-24T00:00:00+00:00",
                                                       "method": "yt-dlp SYNTHETIC", "videos": [], "n": 0})
    r = A.aggregate("joshuamagazine")
    assert r["videos"] == 0
    items = _items(proj)
    assert len(items) > 100
    for it in items:
        assert ITEM_FIELDS <= set(it), it["key"]
        assert it["status"] == "unmeasured" and it["value"] is None and it["evidence"] == [], it["key"]
        assert it["overall"]["n"] == 0 and it["by_format"] == {}, it["key"]
        assert COLLECT_BLOCKER in it["blocker"] and "2026-09-24" in it["blocker"], it
    for f in (proj / P / "measurements").glob("visual_*.json"):
        d = json.loads(f.read_text("utf-8"))
        assert d["source_snapshot_status"] == "blocked"


def test_every_emitted_key_is_a_preset_style_key(proj):
    A.aggregate("joshuamagazine")
    base = config.flatten(read_yaml(proj / P / "preset.yaml"))
    keys = [it["key"] for it in _items(proj)]
    assert len(keys) == len(set(keys))
    missing = [k for k in keys if k not in base]
    assert not missing, f"measurement keys with no preset key: {missing}"
    non_style = [k for k in keys if config.classify_key(k)]
    assert not non_style, f"measurement keys that are meta/infra/rule keys: {non_style}"
    # and the registry picks every one of them up
    reg = config.sync_registry("joshuamagazine", access_logs=[], qa_declarations={})
    for k in keys:
        e = reg["entries"][k]
        assert e["status"] == "unmeasured" and e.get("blocker"), k
