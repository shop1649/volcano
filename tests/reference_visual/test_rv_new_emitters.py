"""Emitters added for the keys that had no measurement path: canvas size/fps, safe margins, dialogue
quote marks, zoom ease / recenter, flash scope (aggregation side).

All analysis files, snapshots and download records here are SYNTHETIC, hand-written in the
documented formats with known values, so the expected statistics are exact.  The analyzers that
produce the per-event fields (motion.fit_ease / classify_recenter, shots.flash_scope,
motion.detect_decorations) are checked against renderer-drawn mocks in test_rv_effects.py.
"""
from __future__ import annotations

import json

import pytest

from shortkit.reference import aggregate as A
from shortkit.reference.textboxes import quote_pair
from shortkit.util.jsonio import append_jsonl, write_json

P = "presets/joshuamagazine"
FMT = "presets/joshuamagazine/formats.yaml"


def _snapshot(root, vids, kinds=None, status="ok"):
    write_json(root / P / "reference/latest100.json", {
        "schema": "shortkit.ref_snapshot/1", "status": status, "captured_at": "2026-01-01T00:00:00+00:00",
        "method": "SYNTHETIC", "blocker": None if status == "ok" else "SYNTHETIC: 403 Forbidden",
        "videos": [{"rank": i + 1, "video_id": v, "title": f"SYNTHETIC {v}", "duration": 30.0, "view_count": 1000,
                    "kind": (kinds or {}).get(v, "short")} for i, v in enumerate(vids)]})


def _formats(root, assign):
    import yaml
    (root / FMT).write_text(yaml.safe_dump({"status": "measured", "assignments": assign}), encoding="utf-8")


def _items(root) -> dict:
    out = {}
    for f in (root / P / "measurements").glob("*.json"):
        for it in json.loads(f.read_text("utf-8"))["items"]:
            out[it["key"]] = it
    return out


def _video(root, vid, res=(540, 960), captions=None, motion=None, shots=None):
    d = root / P / "analysis" / vid
    write_json(d / "captions.json", {"video_id": vid, "resolution": list(res), "duration": 30.0,
                                     "items": captions or []})
    write_json(d / "motion.json", motion or {"video_id": vid, "resolution": list(res), "events": [],
                                             "presence": {}})
    write_json(d / "shots.json", shots or {"video_id": vid, "resolution": list(res), "duration": 30.0, "cuts": [],
                                           "presence": {}})
    write_json(d / "layout.json", {"video_id": vid, "resolution": list(res), "video_region": None,
                                   "background": "unmeasured", "roles": {}})


def _cap(role, bbox, text="자막", start=1.0, box_bbox=None, t_rep=None):
    st = {"box": {"present": "present", "bbox": box_bbox} if box_bbox else {"present": "absent"}}
    return {"id": f"c{bbox[0]}{bbox[1]}", "start": start, "end": start + 1.0, "role": role, "text": text, "bbox": bbox,
            "style": st, "t_rep": t_rep if t_rep is not None else start + 0.5, "frame": None,
            "role_reason": "SYNTHETIC"}


# ============================================================================= canvas size / fps
def _dl(root, vid, w, h, fps, fmt="bv*[width<=1080]+ba", **kw):
    append_jsonl(root / P / "reference/downloads.jsonl",
                 {"video_id": vid, "path": f"{P}/reference/videos/{vid}.mp4", "sha256": "0" * 64, "format_id": "137+140",
                  "width": w, "height": h, "fps": fps, "requested_format": fmt, **kw})


def test_download_cap_issue():
    assert A.download_cap_issue({"requested_format": None, "width": 608, "height": 1080}) is None
    # the current `ref download` format caps the HEIGHT: a portrait Short comes as 608x1080 / 480x854
    assert "짧은 변" in A.download_cap_issue({"requested_format": "bv*[height<=1080][ext=mp4]+ba",
                                             "width": 608, "height": 1080})
    assert A.download_cap_issue({"requested_format": "b[height<=1080]", "width": 480, "height": 854})
    # a short-side (width) cap at full HD on a portrait Short: accepted (the cap may bind -> noted)
    assert A.download_cap_issue({"requested_format": "bv*[width<=1080]+ba", "width": 1080, "height": 1920}) is None
    assert A.download_cap_note({"requested_format": "bv*[width<=1080]+ba", "width": 1080, "height": 1920})
    # landscape: a cap that cannot bind (next rung 1044 < 1080) is fine; one that binds below full HD is not
    assert A.download_cap_issue({"requested_format": "b[height<=1080]", "width": 1280, "height": 720}) is None
    assert A.download_cap_issue({"requested_format": "b[height<=720]", "width": 1280, "height": 720})


def test_canvas_size_fps_mode_by_format_and_capped_rows_excluded(proj):
    vids = ["v1", "v2", "v3", "v4", "v5", "vlong"]
    _snapshot(proj, vids, kinds={"vlong": "video"})
    _formats(proj, {"v1": "F1", "v2": "F1", "v3": "F2", "v4": "F2"})
    _dl(proj, "v1", 1080, 1920, 30.0)
    _dl(proj, "v2", 1080, 1920, 30.0)
    _dl(proj, "v3", 720, 1280, 29.97)
    _dl(proj, "v3", 1080, 1920, 60.0)             # the LATEST record of a video wins
    _dl(proj, "v4", 480, 854, 30.0, fmt="bv*[height<=1080][ext=mp4]+ba")    # capped portrait -> excluded
    _dl(proj, "vlong", 1920, 1080, 25.0)          # long-form upload: not a Short -> not counted
    # v5 not downloaded
    A.aggregate("joshuamagazine")
    it = _items(proj)
    w, h, f = it["canvas.width"], it["canvas.height"], it["canvas.fps"]
    assert w["status"] == h["status"] == f["status"] == "measured"
    assert w["value"] == 1080 and h["value"] == 1920 and w["value_rule"] == "mode"
    assert w["overall"]["n"] == 3 and w["overall"]["p50"] == 1080
    assert f["value"] == 30.0 and f["overall"]["n"] == 3
    assert w["by_format"]["F1"]["value"] == 1080 and w["by_format"]["F1"]["n"] == 2
    assert f["by_format"]["F2"]["value"] == 60.0
    assert [e["video_id"] for e in w["excluded"]] == ["v4"] and "짧은 변" in w["excluded"][0]["reason"]
    assert w["aspect"]["mode"] == "9:16"
    assert {e["video_id"] for e in w["evidence"]} == {"v1", "v2", "v3"}
    assert all(e["t"] == 0.0 for e in w["evidence"])
    assert "resolution[0]" in w["method"]          # coordinate mapping rule is explained


def test_canvas_size_all_capped_is_unmeasured_with_download_blocker(proj):
    _snapshot(proj, ["v1"])
    _dl(proj, "v1", 480, 854, 30.0, fmt="bv*[height<=1080][ext=mp4]+ba")
    A.aggregate("joshuamagazine")
    it = _items(proj)["canvas.width"]
    assert it["status"] == "unmeasured" and it["value"] is None
    assert "height<=1080" in it["blocker"] and "다시 받아야" in it["blocker"]


def test_canvas_size_blocked_snapshot_carries_collect_blocker(proj):
    _snapshot(proj, [], status="blocked")
    A.aggregate("joshuamagazine")
    for k in ("canvas.width", "canvas.height", "canvas.fps"):
        it = _items(proj)[k]
        assert it["status"] == "unmeasured" and "SYNTHETIC: 403 Forbidden" in it["blocker"], k


# ============================================================================= safe margins
def test_safe_margin_p10_from_caption_extents_scaled_to_canvas(proj):
    ids = [f"m{i}" for i in range(5)]
    _snapshot(proj, ids)
    for i, vid in enumerate(ids):
        # 540x960 videos; the left margin of video i = 20 + 5*i px; right: title at 500 wide from x=20
        caps = [_cap("title", [20 + 5 * i, 100, 480, 40], "제목"),
                _cap("situation", [100, 700 + i, 300, 30], "상황"),
                _cap("identity_mark", [0, 0, 540, 20], "조슈아매거진"),         # not a caption style: ignored
                _cap("unknown", [0, 940, 540, 20], "???")]                       # unassigned role: ignored
        if i == 0:   # a boxed speaker label: the box (not the ink) sets the bottom margin
            caps.append(_cap("speaker", [200, 800, 60, 20], "선생님", box_bbox=[190, 790, 80, 60], t_rep=3.25))
        _video(proj, vid, captions=caps)
    A.aggregate("joshuamagazine")
    it = _items(proj)
    left = it["canvas.safe_margin.left"]
    assert left["status"] == "measured" and left["resolution"] == [1080, 1920] and left["value_rule"] == "p10"
    vals = sorted(2 * (20 + 5 * i) for i in range(5))           # x2: 540 -> 1080
    import numpy as np
    assert left["value"] == pytest.approx(float(np.percentile(vals, 10)), abs=0.05)
    assert left["overall"]["n"] == 5
    top = it["canvas.safe_margin.top"]
    assert top["value"] == pytest.approx(200.0)                  # title y=100 -> 200 at 1920
    bottom = it["canvas.safe_margin.bottom"]
    # bottom margin per video: 960 - (730 + i) (situation), video 0: box bottom 850 -> 110
    bv = sorted([2 * 110.0] + [2 * (960 - (730 + i)) for i in range(1, 5)])
    assert bottom["value"] == pytest.approx(float(np.percentile(bv, 10)), abs=0.05)
    ev0 = next(e for e in bottom["evidence"] if e["video_id"] == "m0")
    assert ev0["t"] == 3.25 and "speaker" in ev0["note"]


def test_safe_margin_other_aspect_not_mapped(proj):
    _snapshot(proj, ["sq"])
    _video(proj, "sq", res=(1080, 1080), captions=[_cap("title", [10, 10, 100, 40])])
    A.aggregate("joshuamagazine")
    it = _items(proj)["canvas.safe_margin.left"]
    assert it["status"] == "unmeasured" and it["blocker"]


# ============================================================================= quote marks
def test_quote_pair():
    assert quote_pair("“진짜 왔어?”") == {"kind": "pair", "open": "“", "close": "”"}
    assert quote_pair('"왔어"\n"진짜?"')["kind"] == "pair"
    assert quote_pair("왔어?")["kind"] == "none"
    assert quote_pair("“왔어?")["kind"] == "partial"
    assert quote_pair("「왔어」") == {"kind": "pair", "open": "「", "close": "」"}


def test_dialogue_quote_marks_mode_pairs_none_and_partial(proj):
    ids = ["q1", "q2", "q3", "q4"]
    _snapshot(proj, ids)
    _formats(proj, {"q1": "F1", "q2": "F1", "q3": "F2", "q4": "F2"})
    _video(proj, "q1", captions=[_cap("dialogue", [100, 700, 300, 30], "“왔어?”", 1.0),
                                 _cap("dialogue", [100, 700, 300, 30], "“진짜?”", 3.0),
                                 _cap("dialogue", [100, 700, 300, 30], "“뭐야", 5.0)])      # partial: ignored
    _video(proj, "q2", captions=[_cap("dialogue", [100, 700, 300, 30], "“가자”", 2.0)])
    _video(proj, "q3", captions=[_cap("dialogue", [100, 700, 300, 30], "그만해", 2.0),
                                 _cap("dialogue", [100, 700, 300, 30], "하지 마", 4.0)])
    _video(proj, "q4", captions=[_cap("situation", [100, 700, 300, 30], "“인용” 아님", 2.0)])   # not dialogue
    A.aggregate("joshuamagazine")
    it = _items(proj)["text.roles.dialogue.quote_marks"]
    assert it["status"] == "measured"
    assert it["value"] == ["“", "”"]
    assert it["overall"]["n"] == 3 and it["overall"]["counts"] == {"“…”": 2, "none": 1}
    assert it["by_format"]["F1"]["value"] == ["“", "”"]
    assert it["by_format"]["F2"]["value"] == []                  # observed: no quote marks
    assert it["partial_items_excluded"] == 1
    assert {e["video_id"] for e in it["evidence"]} == {"q1", "q2", "q3"}
    ev = next(e for e in it["evidence"] if e["video_id"] == "q3")
    assert ev["value"] == [] and ev["t"] == 2.5


# ============================================================================= zoom ease / recenter / flash scope
def _zoom(t, ease, recenter, dur_s=0.3, fit_dur=0.5):
    return {"t": t, "end": t + dur_s, "type": "zoom_in", "value": 1.3, "scale_to": 1.3, "dur_s": dur_s, "kind": "ramp",
            "ease_fit": {"ease": ease, "best": ease or "linear", "dur_s": fit_dur},
            "recenter_fit": {"recenter": recenter, "class": {True: "moves", False: "stays", None: "centre"}[recenter]}}


def _flash(t, scope):
    return {"t": t, "type": "flash", "score": 0.5, "dur": 0.1, "color": "#FFFFFF", "scope": {"value": scope}}


def test_zoom_ease_recenter_flash_scope_items(proj):
    ids = ["z1", "z2", "z3", "z4"]
    _snapshot(proj, ids)
    _formats(proj, {"z1": "F1", "z2": "F1", "z3": "F2", "z4": "F2"})
    mot = {
        "z1": [_zoom(1.0, "out", False), _zoom(4.0, "out", None), _zoom(8.0, None, None)],
        "z2": [_zoom(2.0, "out", True), _zoom(5.0, "inout", True)],
        "z3": [_zoom(2.0, "linear", False, fit_dur=0.4)],
        "z4": [_zoom(2.0, None, None)],                                # nothing decided
    }
    fl = {"z1": [_flash(3.0, "region")], "z2": [_flash(3.0, "canvas"), _flash(6.0, "canvas")],
          "z3": [_flash(3.0, None)], "z4": []}
    for vid in ids:
        _video(proj, vid, motion={"video_id": vid, "resolution": [540, 960], "events": mot[vid], "presence": {}},
               shots={"video_id": vid, "resolution": [540, 960], "duration": 30.0, "cuts": fl[vid], "presence": {}})
    A.aggregate("joshuamagazine")
    it = _items(proj)
    ease = it["motion.zoom.ease"]
    assert ease["status"] == "measured" and ease["value"] == "out"
    assert ease["overall"]["counts"] == {"out": 2, "linear": 1}      # per-video modes (z2 tie -> first observed)
    assert ease["by_format"]["F2"]["value"] == "linear"
    assert ease["basis"]["zoom_events"] == 7 and ease["basis"]["ease_decided"] == 5
    ev = {e["video_id"]: e for e in ease["evidence"]}
    assert ev["z1"]["t"] == 1.0 and ev["z2"]["t"] == 2.0
    rc = it["motion.zoom.recenter"]
    assert rc["status"] == "measured" and rc["overall"]["counts"] == {False: 2, True: 1} or \
        rc["overall"]["counts"] == {"false": 2, "true": 1}
    assert rc["value"] is False
    sc = it["motion.transitions.flash.scope"]
    assert sc["status"] == "measured" and sc["overall"]["counts"] == {"region": 1, "canvas": 1}
    assert sc["value"] in ("region", "canvas")
    assert sc["by_format"]["F1"]["n"] == 2
    # fitted full ease duration replaces the threshold run length for decided events
    dur = it["motion.zoom.dur_s"]
    assert dur["status"] == "measured"
    assert sorted(e["value"] for e in dur["evidence"]) == [0.3, 0.4, 0.5, 0.5]


def test_new_visual_keys_unmeasured_with_reasons_when_no_events(proj):
    _snapshot(proj, ["n1"])
    _video(proj, "n1")
    A.aggregate("joshuamagazine")
    it = _items(proj)
    for k in ("motion.zoom.ease", "motion.zoom.recenter", "motion.transitions.flash.scope",
              "text.roles.dialogue.quote_marks"):
        assert it[k]["status"] == "unmeasured" and it[k]["blocker"] and it[k]["value"] is None, k
