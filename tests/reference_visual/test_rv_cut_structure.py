"""S2QA-15: `ref aggregate` emits structure.cuts_per_10s / structure.shot_len_s ({p10,p50,p90,n}, overall and by format)
from shots.json of the fixed snapshot's members.

All analysis files are SYNTHETIC (hand-written in the documented shots.json format, docs/CONTRACT.md section 11) with
known cut times, so the expected per-video values and statistics are exact.
"""
from __future__ import annotations

import csv
import json

import pytest
import yaml

from shortkit.reference import aggregate as A
from shortkit.reference import classify as K
from shortkit.util.jsonio import write_json
from shortkit.util.stats import pstats

P = "presets/joshuamagazine"
LEAVES = ("p10", "p50", "p90", "n")
EXTRA = {"flash": {"dur": 0.2, "color": "#FFFFFF"}, "crossfade": {"dur": 0.5}}     # as shots.py writes them


def shots(root, vid, dur, cuts, presence=None, note=None):
    """SYNTHETIC shots.json: cuts = [(t, type)]."""
    doc = {"video_id": vid, "resolution": [540, 960], "fps": 30, "duration": dur,
           "cuts": [{"t": t, "type": typ, "score": 0.9, **EXTRA.get(typ, {})} for t, typ in cuts], "shots": [],
           "presence": presence or {"cut": "present", "flash": "absent", "crossfade": "absent"}}
    if note:
        doc["note"] = note
    write_json(root / P / "analysis" / vid / "shots.json", doc)


def snapshot(root, vids_durs):
    write_json(root / P / "reference/latest100.json", {
        "schema": "shortkit.ref_snapshot/1", "status": "ok", "captured_at": "2026-01-01T00:00:00+00:00",
        "method": "SYNTHETIC", "videos": [{"rank": i + 1, "video_id": v, "url": f"https://www.youtube.com/watch?v={v}",
                                           "title": f"SYNTHETIC {v}", "duration": d, "view_count": 10 * (i + 1),
                                           "published_at": None, "kind": "short"}
                                          for i, (v, d) in enumerate(vids_durs)]})


def labels(root, rows):
    with (root / P / "format_labels.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=K.LABEL_HEADER)
        w.writeheader()
        for vid, st in rows:
            w.writerow({"video_id": vid, "intro_type": "", "structure_type": st, "notes": "",
                        "labeled_by": "tester(watched)", "watched": "yes"})


def items_of(root) -> dict:
    d = json.loads((root / P / "measurements/visual_structure.json").read_text("utf-8"))
    return {it["key"]: it for it in d["items"]}


# expected per-video values (see the fixture): rate = transitions / duration * 10, shot length = median gap incl.
# the first and the last shot
RATE = {"vidA000001": 1.5, "vidB000001": 1.0, "vidC000001": 0.0, "vidD000001": 2.5}
SHOT = {"vidA000001": 5.0, "vidB000001": 4.0, "vidC000001": 10.0, "vidD000001": 3.0}


@pytest.fixture()
def cutvids(proj):
    root = proj
    shots(root, "vidA000001", 20.0, [(5.0, "cut"), (10.0, "cut"), (15.0, "cut")])                  # shots 5,5,5,5
    # t=0 and t=duration are not transitions; flash and crossfade are (QA counts them too) -> shots 2,2,6,20
    shots(root, "vidB000001", 30.0, [(0.0, "cut"), (2.0, "cut"), (4.0, "flash"), (10.0, "crossfade"), (30.0, "cut")],
          presence={"cut": "present", "flash": "present", "crossfade": "present"})
    shots(root, "vidC000001", 10.0, [], presence={"cut": "absent", "flash": "absent", "crossfade": "absent"})  # 1 shot
    shots(root, "vidD000001", 12.0, [(3.0, "cut"), (6.0, "cut"), (9.0, "cut")])                    # shots 3,3,3,3
    # partial analysis (analysed 10 s of a 30 s video) -> left out, with the reason
    shots(root, "vidE000001", 10.0, [(5.0, "cut")])
    # too few frames -> cuts not measured -> left out
    shots(root, "vidG000001", 0.1, [], presence={k: "unmeasured" for k in ("cut", "flash", "crossfade")},
          note="프레임 부족")
    # analysed but NOT a snapshot member -> never enters a value
    shots(root, "vidOUT00001", 10.0, [(1.0, "cut"), (2.0, "cut"), (3.0, "cut"), (4.0, "cut")])
    snapshot(root, [("vidA000001", 20.0), ("vidB000001", 30.0), ("vidC000001", 10.0), ("vidD000001", 12.0),
                    ("vidE000001", 30.0), ("vidG000001", 15.0)])
    labels(root, [("vidA000001", "setup-reveal"), ("vidB000001", "setup-reveal"), ("vidC000001", "list"),
                  ("vidD000001", "list")])
    K.build("joshuamagazine")
    return root


def test_cut_structure_items_overall_and_by_format(cutvids):
    A.aggregate("joshuamagazine")
    it = items_of(cutvids)
    fy = yaml.safe_load((cutvids / P / "formats.yaml").read_text("utf-8"))
    f_of = fy["assignments"]
    for base, per in (("structure.cuts_per_10s", RATE), ("structure.shot_len_s", SHOT)):
        want = pstats(per.values(), 3)
        byf = {}
        for v, x in per.items():
            byf.setdefault(f_of[v], []).append(x)
        for leaf in LEAVES:
            x = it[f"{base}.{leaf}"]
            assert x["status"] == "measured" and x["blocker"] is None, (base, leaf)
            assert x["overall"] == {k: want[k] for k in ("n", "p10", "p50", "p90")}
            assert x["value"] == (want["n"] if leaf == "n" else want[leaf])
            for fmt, vals in byf.items():
                fw = pstats(vals, 3)
                assert {k: x["by_format"][fmt][k] for k in ("n", "p10", "p50", "p90")} == fw
                assert x["by_format"][fmt]["value"] == (fw["n"] if leaf == "n" else fw[leaf])
            b = x["basis"]
            assert set(b["per_video"]) == set(per)                    # snapshot members measured over their full length
            assert {e["video_id"] for e in b["excluded"]} == {"vidE000001", "vidG000001"}
            assert "부분 분석" in next(e["reason"] for e in b["excluded"] if e["video_id"] == "vidE000001")
            assert b["transition_types"] == {"cut": 7, "flash": 1, "crossfade": 1}
            assert {e["video_id"] for e in x["evidence"]} <= set(per)
    assert it["structure.cuts_per_10s.p50"]["unit"] == "cuts/10s" and it["structure.shot_len_s.p50"]["unit"] == "s"
    assert it["structure.cuts_per_10s.n"]["value"] == 4 and it["structure.cuts_per_10s.n"]["by_format"]
    pv = it["structure.shot_len_s.p50"]["basis"]["per_video"]
    assert pv["vidB000001"] == {"format_id": f_of["vidB000001"], "duration": 30.0, "n_transitions": 3,
                                "cuts_per_10s": 1.0, "shot_len_median_s": 4.0, "n_shots": 4}
    # the video outside the snapshot never enters a value
    d = json.loads((cutvids / P / "measurements/visual_structure.json").read_text("utf-8"))
    assert "vidOUT00001" in d["basis"]["excluded_non_snapshot"]


def test_cut_structure_reaches_the_preset_and_registry(cutvids):
    """measurement -> measured.yaml (per format) -> Preset.get -> registry status measured."""
    from shortkit import config
    from shortkit.preset_cli import apply_measurements

    A.aggregate("joshuamagazine")
    apply_measurements("joshuamagazine")
    fy = yaml.safe_load((cutvids / P / "formats.yaml").read_text("utf-8"))
    f_list = fy["assignments"]["vidC000001"]
    pr = config.load_preset("joshuamagazine", f_list)
    assert pr.origin("structure.cuts_per_10s.p10") == "measured"
    assert pr.get("structure.cuts_per_10s.p10") == pstats([0.0, 2.5], 3)["p10"]
    assert pr.get("structure.shot_len_s.p90") == pstats([10.0, 3.0], 3)["p90"]
    assert pr.get("structure.shot_len_s.n") == 2
    reg = config.sync_registry("joshuamagazine", access_logs=[], qa_declarations={})
    for leaf in LEAVES:
        for base in ("structure.cuts_per_10s", "structure.shot_len_s"):
            e = reg["entries"][f"{base}.{leaf}"]
            assert e["status"] == "measured" and e["measurement"]["by_format"], (base, leaf)


def test_cut_structure_unmeasured_without_reference(proj):
    write_json(proj / P / "reference/latest100.json", {"status": "blocked", "blocker": "SYNTHETIC 403",
                                                       "captured_at": "x", "method": "yt-dlp", "videos": []})
    shots(proj, "vidA000001", 20.0, [(5.0, "cut")])        # analysed, but there is no fixed snapshot
    A.aggregate("joshuamagazine")
    it = items_of(proj)
    for base in ("structure.cuts_per_10s", "structure.shot_len_s"):
        for leaf in LEAVES:
            x = it[f"{base}.{leaf}"]
            assert x["status"] == "unmeasured" and x["value"] is None and x["overall"]["n"] == 0
            assert "SYNTHETIC 403" in x["blocker"] or "차단" in x["blocker"]


def test_cut_structure_unmeasured_when_no_full_length_shots(proj):
    """Snapshot members analysed, but only partially: never a guessed value, the reason is recorded."""
    snapshot(proj, [("vidE000001", 30.0)])
    shots(proj, "vidE000001", 10.0, [(5.0, "cut")])
    A.aggregate("joshuamagazine")
    x = items_of(proj)["structure.cuts_per_10s.p50"]
    assert x["status"] == "unmeasured" and x["value"] is None
    assert "부분 분석" in x["blocker"] and "vidE000001" in x["blocker"]


def test_cut_structure_rows_definition():
    """Unit check of the per-video definition shared with QA structure.cuts (grid.our_cuts): every cut / flash /
    crossfade strictly inside (0, duration); shot lengths include the first and the last shot."""
    vids = {"v": {"format_id": None, "shots": {"duration": 8.0, "presence": {"cut": "present"},
                                              "cuts": [{"t": 2.0, "type": "cut"}, {"t": 3.0, "type": "flash"},
                                                       {"t": 8.0, "type": "cut"}, {"t": None, "type": "cut"}]}}}
    r = A.cut_structure_rows(vids, {"v": 8.0})
    assert r["rate"][0]["value"] == 2.5 and r["shot_len"][0]["value"] == 2.0     # shots 2, 1, 5 -> median 2
    assert r["pooled_shot_len"] == [2.0, 1.0, 5.0] and not r["excluded"]


def test_first_caption_excluded_roles_is_the_shared_definition(proj):
    """structure.first_caption_at_s leaves out exactly A.FIRST_CAPTION_EXCLUDED_ROLES (the name episode validate and QA
    import): a title / description / identity mark / unknown line starting earlier never becomes the first caption."""
    assert A.FIRST_CAPTION_EXCLUDED_ROLES == ("title", "description", "identity_mark", "unknown")
    snapshot(proj, [("vidA000001", 20.0)])
    shots(proj, "vidA000001", 20.0, [(5.0, "cut")])
    items = [{"start": 0.0, "end": 20.0, "role": r, "text": "SYNTHETIC", "bbox": [0, 0, 10, 10]}
             for r in A.FIRST_CAPTION_EXCLUDED_ROLES]
    items.append({"start": 1.25, "end": 3.0, "role": "situation", "text": "모여 있다", "bbox": [0, 900, 10, 10]})
    write_json(proj / P / "analysis/vidA000001/captions.json", {"video_id": "vidA000001", "resolution": [540, 960],
                                                                "items": items})
    A.aggregate("joshuamagazine")
    assert items_of(proj)["structure.first_caption_at_s"]["value"] == 1.25
