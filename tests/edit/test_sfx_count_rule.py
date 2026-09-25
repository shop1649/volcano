"""SFX count rule of ``episode validate`` (SYNTHETIC catalogs and per-video event files, temp project root).

* only catalog types of class edit_sfx (+ intentional_silence when the plan has silences) are counted;
  onsite_sound types are the reference footage's own sound (never counted, never placeable);
* allowed = [floor(p10), ceil(p90)] of the observed per-video counts, OR a count observed in at least one
  reference video of the format (the catalog's per-video counts, written into sfx_events.json)."""
from __future__ import annotations

import json

import yaml

from .conftest import codes
from .test_validate import run

VIDS = ["v1", "v2", "v3", "v4", "v5"]


def _pst(vals):
    from shortkit.util.stats import pstats

    return pstats(vals)


def _write(root, per_type: dict, classes: dict, formats: dict | None = None, lower_bound=(), embed=False,
           tamper: str | None = None):
    """per_type: {type_id: [count per video in VIDS]}.  Writes sfx_catalog.json whose statistics are computed
    from these counts (as ref sfx-catalog does), the per-video sfx_events.json with the type ids written back,
    and formats.yaml assignments."""
    formats = formats or {v: "F1" for v in VIDS}
    types = []
    for tid, counts in per_type.items():
        by_fmt: dict[str, list] = {}
        for v, c in zip(VIDS, counts):
            by_fmt.setdefault(formats[v], []).append(c)
        pvc = {"overall": _pst(counts), "by_format": {f: _pst(cs) for f, cs in by_fmt.items()}}
        if lower_bound:
            pvc["lower_bound_videos"] = list(lower_bound)
        if embed:
            pvc["videos"] = dict(zip(VIDS, counts))
        types.append({"type_id": tid, "class": classes[tid], "per_video_count": pvc})
    cat = {"schema": "shortkit.sfx_catalog/1", "preset_id": "joshuamagazine-v1", "status": "measured",
           "basis": {"videos": VIDS, "n_videos": len(VIDS)}, "types": types}
    pdir = root / "presets/joshuamagazine"
    (pdir / "sfx_catalog.json").write_text(json.dumps(cat))
    for i, v in enumerate(VIDS):
        evs = []
        for tid, counts in per_type.items():
            n = counts[i] + (1 if tamper == tid and i == 0 else 0)
            evs += [{"id": f"{tid}{k}", "t": 1.0 + k, "type_id": tid, "class": classes[tid]} for k in range(n)]
        d = pdir / "analysis" / v / "audio"
        d.mkdir(parents=True, exist_ok=True)
        (d / "sfx_events.json").write_text(json.dumps({"video_id": v, "status": "measured", "events": evs,
                                                       "catalog": {"file": "presets/joshuamagazine/sfx_catalog.json"}}))
    fy = yaml.safe_load((pdir / "formats.yaml").read_text(encoding="utf-8"))
    fy["assignments"] = dict(formats)
    fy["table"] = [{"format_id": f, "videos": [v for v in VIDS if formats[v] == f]} for f in sorted(set(formats.values()))]
    (pdir / "formats.yaml").write_text(yaml.safe_dump(fy, allow_unicode=True), encoding="utf-8")


def _msgs(iss, code):
    return [i["message_ko"] for i in iss if i["code"] == code]


def test_onsite_sound_types_are_not_counted_and_not_placeable(root, plan):
    """The mockloop failure: an onsite type with p10 0.4 made a plan without it fail ('0개 … 0.4..1.6 밖')."""
    _write(root, {"pop": [1, 1, 1, 1, 1], "onsite_04": [0, 1, 1, 1, 2]}, {"pop": "edit_sfx", "onsite_04": "onsite_sound"})
    iss = run(root, plan)
    assert not any("onsite_04" in m for m in _msgs(iss, "sfx_count_range")), iss
    assert "sfx_count_range" not in codes(iss) and "sfx_total_range" not in codes(iss)
    plan["sfx"][0]["type"] = "onsite_04"
    assert "sfx_type_onsite" in codes(run(root, plan), "error")


def test_floor_p10_ceil_p90_range(root, plan):
    # pop counts [1,2,2,2,3] -> p10 1.4, p90 2.6 -> allowed [1, 3]; the plan has 1 pop
    _write(root, {"pop": [1, 2, 2, 2, 3]}, {"pop": "edit_sfx"})
    assert "sfx_count_range" not in codes(run(root, plan))
    from shortkit.edit.validate import allowed_count_range

    assert allowed_count_range({"p10": 1.4, "p90": 2.6}) == (1, 3)
    assert allowed_count_range({"p10": 2.0, "p90": 4.0}) == (2, 4)       # integral quantiles stay closed


def test_count_observed_in_a_reference_video_is_accepted_outside_the_quantile_range(root, plan):
    # pop [0,3,3,3,3]: p10 1.2 -> allowed [1, 3], yet v1 really has 0 pops
    # ding [5,1,1,1,1]: p90 3.4 -> allowed [1, 4], yet v1 really has 5 dings
    _write(root, {"pop": [0, 3, 3, 3, 3], "ding": [5, 1, 1, 1, 1]}, {"pop": "edit_sfx", "ding": "edit_sfx"})
    plan["sfx"] = []                                           # 0 pop: outside [1, 3] but observed in v1
    plan["sfx"] += [{"id": f"d{k}", "type": "ding", "t": 0.5 + k, "event": {"t": 0.5 + k, "desc": "튀어나옴", "kind": "appear"},
                     "file": "assets/test/generated/edit_fixture/pop.wav"} for k in range(5)]  # 5 ding: outside [1, 4], observed in v1
    iss = run(root, plan)
    assert "sfx_count_range" not in codes(iss), [i for i in iss if i["code"].startswith("sfx_count")]
    plan["sfx"] = plan["sfx"][:2]                                # 2 ding: inside [1, 4]; 0 pop observed
    assert "sfx_count_range" not in codes(run(root, plan))


def test_count_neither_in_range_nor_observed_is_an_error(root, plan):
    _write(root, {"pop": [2, 3, 3, 3, 5]}, {"pop": "edit_sfx"})   # p10 2.4 -> [2, 5]; observed {2,3,5}
    iss = run(root, plan)                                          # 1 pop
    assert "sfx_count_range" in codes(iss, "error")
    assert any("[2, 5]" in m and "[2, 3, 5]" in m for m in _msgs(iss, "sfx_count_range")), iss


def test_count_only_seen_in_lower_bound_videos_warns(root, plan):
    _write(root, {"pop": [1, 3, 3, 3, 3]}, {"pop": "edit_sfx"}, lower_bound=["v1"])   # p10 1.8 -> [1, 3]: 1 inside
    assert "sfx_count_lower_bound" not in codes(run(root, plan))
    _write(root, {"pop": [0, 3, 3, 3, 3]}, {"pop": "edit_sfx"}, lower_bound=["v1"])   # [1, 3]; 0 seen only in v1
    plan["sfx"] = []
    iss = run(root, plan)
    assert "sfx_count_range" not in codes(iss, "error") and "sfx_count_lower_bound" in codes(iss, "warn")


def test_by_format_range_uses_only_that_formats_videos(root, plan):
    fm = {"v1": "F2", "v2": "F1", "v3": "F1", "v4": "F1", "v5": "F1"}
    _write(root, {"pop": [1, 3, 3, 3, 3]}, {"pop": "edit_sfx"}, formats=fm)
    plan["format_id"] = "F1"                                        # F1: [3,3,3,3] -> [3,3]; the 1 is F2's
    assert "sfx_count_range" in codes(run(root, plan), "error")
    plan["format_id"] = "F2"
    assert "sfx_count_range" not in codes(run(root, plan))


def test_silence_type_counted_only_when_the_plan_has_silences(root, plan):
    _write(root, {"pop": [1, 1, 1, 1, 1], "silence_cut": [1, 2, 2, 2, 2]}, {"pop": "edit_sfx", "silence_cut": "intentional_silence"})
    iss = run(root, plan)                                           # no silences in the plan -> not counted
    assert not any("silence_cut" in m for m in _msgs(iss, "sfx_count_range")) and "sfx_total_range" not in codes(iss)
    plan["bgm"]["silences"] = [{"start": 3.0, "end": 3.4}, {"start": 4.0, "end": 4.3}, {"start": 4.8, "end": 5.0},
                               {"start": 5.2, "end": 5.4}]          # 4 silences: outside [1, 2], never observed
    iss = run(root, plan)
    assert any("silence_cut" in m for m in _msgs(iss, "sfx_count_range")), iss
    plan["bgm"]["silences"] = plan["bgm"]["silences"][:2]
    iss = run(root, plan)
    assert "sfx_count_range" not in codes(iss) and "sfx_total_range" not in codes(iss)   # totals [3,3,3,3,2]+... fit


def test_total_counts_only_added_effects(root, plan):
    # onsite sounds inflate the per-video totals if counted: totals of edit_sfx only are [1,1,1,1,1]
    _write(root, {"pop": [1, 1, 1, 1, 1], "onsite_x": [4, 4, 5, 5, 6]}, {"pop": "edit_sfx", "onsite_x": "onsite_sound"})
    assert "sfx_total_range" not in codes(run(root, plan))
    plan["sfx"].append({"id": "fx2", "type": "pop", "t": 3.0, "event": {"t": 3.0, "desc": "또 나타남", "kind": "appear"},
                        "file": "assets/test/generated/edit_fixture/pop.wav"})
    iss = run(root, plan)
    assert "sfx_total_range" in codes(iss, "error") and "sfx_count_range" in codes(iss, "error")


def test_per_video_counts_that_do_not_reproduce_the_catalog_are_not_used(root, plan):
    _write(root, {"pop": [0, 3, 3, 3, 3]}, {"pop": "edit_sfx"}, tamper="pop")    # v1 file says 1, catalog says 0
    plan["sfx"] = []
    iss = run(root, plan)
    assert "sfx_observed_counts_unavailable" in codes(iss, "warn")
    assert "sfx_count_range" in codes(iss, "error")                 # range only: 0 outside [1, 3]


def test_catalog_embedded_per_video_counts_are_preferred(root, plan):
    _write(root, {"pop": [0, 3, 3, 3, 3]}, {"pop": "edit_sfx"}, embed=True, tamper="pop")
    plan["sfx"] = []
    iss = run(root, plan)
    assert "sfx_observed_counts_unavailable" not in codes(iss) and "sfx_count_range" not in codes(iss)


def test_plan_silence_without_a_catalog_silence_type_is_out_of_range(root, plan):
    _write(root, {"pop": [1, 1, 1, 1, 1]}, {"pop": "edit_sfx"})
    plan["bgm"]["silences"] = [{"start": 3.0, "end": 3.4}]
    iss = run(root, plan)
    assert "sfx_silence_unobserved" in codes(iss, "error") and "sfx_total_range" not in codes(iss)
