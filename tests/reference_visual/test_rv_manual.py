"""Manual observation path (manual_observations.csv -> measurements/manual.json) and the merge with
the automatic decoration detector.  Every snapshot / observation / analysis file here is SYNTHETIC
(observer names like 'SYNTHETIC-A' are placeholders, not people who watched anything).
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
import yaml

from shortkit import config
from shortkit.reference import manual as MAN
from shortkit.util.jsonio import read_yaml, write_json

P = "presets/joshuamagazine"
REPO = Path(__file__).resolve().parents[2]
BLOCKER = "SYNTHETIC: Tunnel connection failed: 403 Forbidden"


def _snapshot(root, vids, status="ok", kinds=None):
    write_json(root / P / "reference/latest100.json", {
        "schema": "shortkit.ref_snapshot/1", "status": status, "captured_at": "2026-01-01T00:00:00+00:00",
        "method": "SYNTHETIC", "blocker": None if status == "ok" else BLOCKER,
        "videos": [{"rank": i + 1, "video_id": v, "title": f"SYNTHETIC {v}", "duration": 30.0,
                    "kind": (kinds or {}).get(v, "short")} for i, v in enumerate(vids)]})


def _rows(root, rows):
    with (root / P / MAN.CSV_NAME).open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=MAN.MANUAL_HEADER)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in MAN.MANUAL_HEADER})


def _res(root, vid, res=(540, 960)):
    write_json(root / P / "analysis" / vid / "captions.json", {"video_id": vid, "resolution": list(res), "items": []})


def _obs(vid, key, value, t=1.0, by="SYNTHETIC-A", watched="yes", note=""):
    return {"video_id": vid, "t": t, "key": key, "value": value, "observed_by": by, "watched": watched, "note": note}


def _manual(root) -> dict:
    d = json.loads((root / P / "measurements/manual.json").read_text("utf-8"))
    assert d["schema"] == "shortkit.measurement/1" and d["group"] == "manual"
    return d


def test_template_header_and_keys_are_preset_style_keys():
    hdr = (REPO / P / MAN.CSV_NAME).read_text("utf-8").splitlines()
    assert hdr[0] == ",".join(MAN.MANUAL_HEADER) and len([h for h in hdr if h.strip()]) == 1   # header only
    base = config.flatten(read_yaml(REPO / P / "preset.yaml"))
    for k in MAN.MANUAL_KEYS:
        assert k in base, k
        assert config.classify_key(k) is None, k       # style keys, not meta/infra/rule


def test_only_watched_rows_with_observer_count(proj):
    _snapshot(proj, ["a", "b", "c", "long1"], kinds={"long1": "video"})
    for v in ("a", "b", "c", "long1"):
        _res(proj, v)
    _rows(proj, [
        _obs("a", "decorations.circle.color", "#ff2a2a", 2.0),
        _obs("b", "decorations.circle.color", "#FE2B2B", 3.0),
        _obs("c", "decorations.circle.color", "#FF2A2A", watched="no"),          # not watched -> ignored
        _obs("c", "decorations.circle.color", "#00FF00", by=""),                 # no observer -> ignored
        _obs("zz", "decorations.circle.color", "#00FF00"),                        # not in the snapshot
        _obs("a", "text.roles.title.size_px", "80"),                              # automatic key: not manual
        _obs("a", "decorations.circle.stroke_px", "thick"),                       # not a number
        _obs("a", "cover.source", "thumbnail"),                                   # not an allowed value
        _obs("a", "decorations.box.blink_hz", "2", t=""),                         # no evidence time
        _obs("long1", "decorations.circle.color", "#00FF00"),                     # long-form upload
    ])
    MAN.aggregate_manual("joshuamagazine")
    d = _manual(proj)
    assert d["rows_used"] == 2 and len(d["rows_ignored"]) == 8
    reasons = " ".join(r["reason"] for r in d["rows_ignored"])
    for w in ("watched", "observed_by", "스냅샷", "수동 관찰 대상 키가 아님", "숫자가 아님", "허용 값", "t(근거 시각", "긴 영상"):
        assert w in reasons, w
    it = {i["key"]: i for i in d["items"]}["decorations.circle.color"]
    from shortkit.reference.common import color_dist
    assert it["status"] == "measured" and color_dist(it["value"], "#FF2A2A") <= 2 and it["overall"]["n"] == 2
    assert {(e["video_id"], e["t"], e["observed_by"], e["source"]) for e in it["evidence"]} == \
        {("a", 2.0, "SYNTHETIC-A", "manual"), ("b", 3.0, "SYNTHETIC-A", "manual")}


def test_numeric_px_scaled_by_video_resolution_and_stats_by_format(proj):
    ids = ["v1", "v2", "v3", "v4"]
    _snapshot(proj, ids)
    (proj / P / "formats.yaml").write_text(yaml.safe_dump({"assignments": {"v1": "F1", "v2": "F1", "v3": "F2"}}),
                                           encoding="utf-8")
    _res(proj, "v1", (540, 960))
    _res(proj, "v2", (1080, 1920))
    _res(proj, "v3", (540, 960))
    _res(proj, "v4", (1080, 1080))                                                # other aspect: px cannot be mapped
    _rows(proj, [
        _obs("v1", "decorations.box.stroke_px", "4", 1.0),        # 540 wide -> x2 = 8
        _obs("v1", "decorations.box.stroke_px", "5", 2.0),        # same video: per-video median (4.5 -> 9)
        _obs("v2", "decorations.box.stroke_px", "10", 1.5),       # already canvas size -> 10
        _obs("v3", "decorations.box.stroke_px", "6", 1.5),        # -> 12
        _obs("v4", "decorations.box.stroke_px", "6", 1.5),        # not scaled -> not counted
        _obs("v1", "decorations.box.blink_hz", "2", 1.0),
        _obs("v3", "decorations.box.blink_hz", "0", 1.0),
        _obs("v1", "text.tone.emoji", "no", 5.0),
        _obs("v2", "text.tone.emoji", "예", 6.0),
        _obs("v3", "text.tone.emoji", "no", 7.0),
        _obs("v1", "cover.text_role", "title", 0.0),
    ])
    MAN.aggregate_manual("joshuamagazine")
    d = _manual(proj)
    items = {i["key"]: i for i in d["items"]}
    st = items["decorations.box.stroke_px"]
    assert st["status"] == "measured" and st["resolution"] == [1080, 1920] and st["unit"] == "px"
    assert st["overall"] == {"n": 3, "p10": pytest.approx(9.2), "p50": 10.0, "p90": pytest.approx(11.6)}
    assert st["value"] == 10.0 and st["by_format"]["F1"]["n"] == 2 and st["by_format"]["F2"]["value"] == 12.0
    assert d["px_rows_not_scaled"] == [{"video_id": "v4", "key": "decorations.box.stroke_px",
                                        "reason": "영상 해상도를 모르거나 캔버스와 종횡비가 다름"}]
    assert len([e for e in st["evidence"] if e["video_id"] == "v1"]) == 2       # evidence = the rows
    bl = items["decorations.box.blink_hz"]
    assert bl["overall"]["n"] == 2 and bl["value"] == 1.0
    em = items["text.tone.emoji"]
    assert em["value"] is False and em["overall"]["counts"] == {False: 2, True: 1} or \
        em["overall"]["counts"] == {"false": 2, "true": 1}
    assert items["cover.text_role"]["value"] == "title"
    assert items["cover.source"]["status"] == "unmeasured" and "manual_observations.csv" in items["cover.source"]["blocker"]


def test_auto_decorations_fill_videos_without_manual_rows(proj):
    _snapshot(proj, ["d1", "d2"])
    for vid, color, stroke in (("d1", "#FF2A2A", 5.0), ("d2", "#FFE400", 4.0)):
        write_json(proj / P / "analysis" / vid / "motion.json", {
            "video_id": vid, "resolution": [540, 960], "events": [],
            "decorations": {"status": "experimental", "items": [
                {"kind": "circle", "t": 1.0, "end": 2.0, "frame_t": 1.5, "color": color, "stroke_px": stroke,
                 "blink_hz": 0.0}]}})
    # a person watched d2 and saw a thicker ring: the manual row wins for d2 only
    _rows(proj, [_obs("d2", "decorations.circle.stroke_px", "6", 1.5, by="SYNTHETIC-B")])
    MAN.aggregate_manual("joshuamagazine")
    items = {i["key"]: i for i in _manual(proj)["items"]}
    st = items["decorations.circle.stroke_px"]
    assert st["status"] == "measured" and st["sources"] == {"auto": 1, "manual": 1}
    assert sorted(e["value"] for e in st["evidence"]) == [5.0, 6.0]           # raw (video px) values
    assert st["overall"]["p50"] == pytest.approx((10.0 + 12.0) / 2)            # scaled x2 to the canvas
    src = {e["video_id"]: e["source"] for e in st["evidence"]}
    assert src == {"d1": "auto", "d2": "manual"}
    bl = items["decorations.circle.blink_hz"]
    assert bl["status"] == "measured" and bl["value"] == 0.0 and bl["sources"] == {"auto": 2}
    assert items["decorations.arrow.size_px"]["status"] == "unmeasured"


def test_blocked_snapshot_every_manual_item_unmeasured_with_collect_blocker(proj):
    _snapshot(proj, [], status="blocked")
    _rows(proj, [_obs("a", "cover.source", "first_frame")])
    MAN.aggregate_manual("joshuamagazine")
    d = _manual(proj)
    assert len(d["items"]) == len(MAN.MANUAL_KEYS)
    for it in d["items"]:
        assert it["status"] == "unmeasured" and it["value"] is None and it["evidence"] == [], it["key"]
        assert BLOCKER in it["blocker"], it


def test_cli_and_registry_and_no_key_emitted_twice(proj):
    from shortkit.cli import main
    _snapshot(proj, ["a"])
    _res(proj, "a")
    _rows(proj, [_obs("a", "cover.source", "first_frame", 0.0)])
    assert main(["ref", "aggregate"]) == 0                 # also refreshes manual.json
    assert main(["ref", "manual-aggregate"]) == 0
    keys: dict[str, str] = {}
    for f in sorted((proj / P / "measurements").glob("*.json")):
        for it in json.loads(f.read_text("utf-8"))["items"]:
            assert it["key"] not in keys, f"{it['key']} emitted by {keys.get(it['key'])} and {f.name}"
            keys[it["key"]] = f.name
    assert keys["decorations.arrow.color"] == "manual.json" and keys["canvas.width"] == "visual_canvas.json"
    import inspect
    kw = {"discover": False} if "discover" in inspect.signature(config.sync_registry).parameters else {}
    reg = config.sync_registry("joshuamagazine", access_logs=[], qa_declarations={}, **kw)
    e = reg["entries"]["cover.source"]
    assert e["status"] == "measured" and e["measurement"]["file"].endswith("measurements/manual.json")
    assert e["evidence"][0]["video_id"] == "a" and e["evidence"][0]["t"] == 0.0
    assert reg["entries"]["decorations.box.color"]["status"] == "unmeasured"
