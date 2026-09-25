"""SFX catalog over SYNTHETIC analysed videos: clustering, edit vs onsite, silence type, stats."""
from __future__ import annotations

import json

import pytest

from .conftest import PRESET, no_abs_paths
import synthref as S
from shortkit.reference import sfx_catalog as C
from shortkit.reference.sfx_events import sfx_events_path

VIDS = ["synv1", "synv2", "synv3", "synv4"]


def _name_of(project_env, vid, t):
    tr = project_env["truths"][vid]
    cands = [(x["name"], abs(x["t"] - t)) for x in tr["sfx"]] + [(f"knock{x['seed']}", abs(x["t"] - t))
                                                                 for x in tr["onsite"]]
    n, d = min(cands, key=lambda z: z[1])
    return n if d <= 0.05 else None


@pytest.fixture
def catalog(project_env):
    return C.build_catalog(PRESET, video_ids=VIDS)


def _members(project_env, type_id):
    out = []
    for vid in VIDS:
        d = json.loads(sfx_events_path(PRESET, vid).read_text())
        for e in d["events"]:
            if e.get("type_id") == type_id:
                out.append((vid, e["t"], _name_of(project_env, vid, e["t"])))
    return out


@pytest.mark.slow
def test_same_sfx_grouped_across_videos_and_classified_edit(project_env, catalog):
    # every video analysed, but no watched emotion labels (and synv4 has no visual analysis) -> partial, not measured
    assert catalog["status"] == "partial" and catalog["basis"]["n_videos"] == 4
    assert catalog["column_status"]["per_video_count"] == "measured" and catalog["counts_are_lower_bounds"] is False
    assert catalog["basis"]["separator"] == "oracle(test-double)"
    edit = [t for t in catalog["types"] if t["class"] == "edit_sfx"]
    names_by_type = {}
    for t in edit:
        mem = _members(project_env, t["type_id"])
        names = {n for _, _, n in mem}
        assert len(names) == 1, (t["type_id"], mem)                     # cluster purity
        names_by_type[names.pop()] = t
    for name in ("pop", "whoosh", "ding", "boom"):
        assert name in names_by_type, names_by_type.keys()
        assert names_by_type[name]["n_videos"] >= 3                     # grouped across >= 3 videos
        ex = names_by_type[name]["examples"]
        assert len(ex) == 3 and len({e["video_id"] for e in ex}) == 3
    # the unique on-site knocks are never classified as edit SFX
    for t in edit:
        assert not any((n or "").startswith("knock") for _, _, n in _members(project_env, t["type_id"]))
    onsite = [t for t in catalog["types"] if t["class"] == "onsite_sound"]
    knock_types = {t["type_id"] for t in onsite for _, _, n in _members(project_env, t["type_id"])
                   if (n or "").startswith("knock")}
    assert knock_types


@pytest.mark.slow
def test_silence_type(catalog):
    sil = [t for t in catalog["types"] if t["class"] == "intentional_silence"]
    assert len(sil) == 1
    s = sil[0]
    assert s["type_id"] == "silence_cut" and s["n_events"] == 2 and s["n_videos"] == 2
    assert 0.5 <= s["duration_s"]["p50"] <= 0.75
    assert s["per_video_count"]["overall"] == {"n": 4, "p10": 0.0, "p50": 0.5, "p90": 1.0}


@pytest.mark.slow
def test_type_stats(project_env, catalog):
    pop = next(t for t in catalog["types"] if t["class"] == "edit_sfx"
               and {n for _, _, n in _members(project_env, t["type_id"])} == {"pop"})
    pvc = pop["per_video_count"]
    assert pvc["overall"]["n"] == 4 and set(pvc["by_format"]) == {"F1", "F2"}
    # synv1..3 have synthetic captions (pop -> 'situation' caption with motion_in pop just before)
    assert pop["prev_caption_role"]["mode"] == "situation"
    assert pop["screen_event"]["mode"] == "text_pop"
    assert pop["screen_event"]["n"] == 3                               # synv4 has no visual analysis -> not counted
    assert 0.0 <= pop["offset_to_event_s"]["p50"] <= 0.1
    assert pop["emotion"]["status"] == "unmeasured" and pop["emotion"]["n"] == 0
    assert "감정 못 잼" in pop["placement_rule"] and "text_pop" in pop["placement_rule"]
    assert pop["gain_db_rel_mix"]["n"] == pop["n_events"]
    assert pop["label_source"].startswith("acoustic_descriptor")
    assert pop["fingerprint"]["centroid"] == f"presets/{PRESET}/sfx_fp/{pop['type_id']}.npy"
    ding = next(t for t in catalog["types"] if t["class"] == "edit_sfx"
                and {n for _, _, n in _members(project_env, t["type_id"])} == {"ding"})
    assert ding["screen_event"]["mode"] == "zoom_in"
    assert ding["prev_caption_role"]["mode"] == "reaction"
    assert not no_abs_paths(catalog, project_env["root"])


@pytest.mark.slow
def test_emotion_only_from_watched_labels(project_env):
    root = project_env["root"]
    lab = root / "presets" / PRESET / "sfx_emotion_labels.csv"
    try:
        lab.write_text("video_id,t,emotion,labeled_by\nsynv1,2.0,surprise,tester-who-watched\n"
                       "synv2,3.0,surprise,tester-who-watched\nsynv3,1.5,funny,\n", encoding="utf-8")
        cat = C.build_catalog(PRESET, video_ids=VIDS, write=False)
        pop = next(t for t in cat["types"] if t["class"] == "edit_sfx" and t["screen_event"]["mode"] == "text_pop")
        # 2 of the 4 pop events labelled by someone who watched -> the column is only partly measured
        assert pop["emotion"]["status"] == "partial" and pop["emotion"]["n_missing"] == 2
        assert pop["columns"]["emotion"] == "partial" and pop["type_id"] in cat["unmeasured_columns"]["emotion"]
        assert pop["emotion"]["counts"] == {"surprise": 2}              # unlabeled-by row ignored
    finally:
        lab.unlink(missing_ok=True)


def test_no_analyzed_videos_is_unmeasured(tmp_project):
    cat = C.build_catalog(PRESET)                                       # no snapshot at all here
    assert cat["status"] == "unmeasured" and cat["types"] == [] and cat["blocker"]
    cat2 = C.build_catalog(PRESET, video_ids=["a", "b"])        # no snapshot: nothing is a production member
    assert cat2["status"] == "unmeasured" and cat2["basis"]["excluded_non_snapshot"] == ["a", "b"]
    S.write_snapshot(tmp_project, ["a", "b"])
    cat2 = C.build_catalog(PRESET, video_ids=["a", "b", "old_hv"])  # SYNTHETIC ids; old_hv is not a member
    assert cat2["status"] == "unmeasured" and cat2["basis"]["missing"] == ["a", "b"]
    assert cat2["basis"]["excluded_non_snapshot"] == ["old_hv"]
    saved = json.loads((tmp_project / "presets/joshuamagazine/sfx_catalog.json").read_text())
    assert saved["status"] == "unmeasured" and saved["schema"] == "shortkit.sfx_catalog/1"


def test_newest_from_snapshot(tmp_project):
    snap = tmp_project / "presets/joshuamagazine/reference/latest100.json"
    snap.parent.mkdir(parents=True, exist_ok=True)
    rows = [{"rank": i + 1, "video_id": f"v{i:03d}", "published_at": f"2026-09-{(i % 28) + 1:02d}",
             "kind": "short" if i % 5 else "video"} for i in range(60)]
    snap.write_text(json.dumps({"videos": rows}), encoding="utf-8")
    ids, n, blocker = C.newest_video_ids(PRESET, 10)
    assert n == 10 and len(ids) == 10 and blocker is None
    kinds = {r["video_id"]: r["kind"] for r in rows}
    assert all(kinds[v] == "short" for v in ids)
    dates = {r["video_id"]: r["published_at"] for r in rows}
    assert [dates[v] for v in ids] == sorted([dates[v] for v in ids], reverse=True)
    ids50, n50, _ = C.newest_video_ids(PRESET)                         # preset reference.sfx_catalog_latest_n
    assert n50 == 50 and len(ids50) == 48                              # only 48 shorts exist in the fixture
    cat = C.build_catalog(PRESET)
    assert cat["status"] == "unmeasured" and cat["basis"]["target_n"] == 50
    assert len(cat["basis"]["missing"]) == 48


def test_blocked_snapshot_blocker_is_surfaced(tmp_project):
    snap = tmp_project / "presets/joshuamagazine/reference/latest100.json"
    snap.parent.mkdir(parents=True, exist_ok=True)
    snap.write_text(json.dumps({"status": "blocked", "blocker": "403 Forbidden (network policy)", "videos": []}),
                    encoding="utf-8")
    cat = C.build_catalog(PRESET)
    assert cat["status"] == "unmeasured" and "403" in cat["blocker"] and cat["types"] == []


@pytest.mark.slow
def test_type_ids_stable_across_rebuilds(project_env):
    """Rebuilding the catalog (e.g. with fewer/more videos) keeps the ids of types that still exist."""
    full = C.build_catalog(PRESET, video_ids=VIDS)
    ids_full = {t["type_id"]: t["examples"][0] for t in full["types"] if t["class"] == "edit_sfx"}
    part = C.build_catalog(PRESET, video_ids=["synv2", "synv3", "synv4"])
    again = C.build_catalog(PRESET, video_ids=VIDS)
    ids_again = {t["type_id"]: t["examples"][0] for t in again["types"] if t["class"] == "edit_sfx"}
    assert ids_full == ids_again
    names_full = {t["type_id"]: t["label"] for t in full["types"]}
    for t in part["types"]:
        if t["type_id"] in names_full and t["class"] == "edit_sfx":
            assert t["label"].split(" (")[0] == names_full[t["type_id"]].split(" (")[0]


# ----------------------------------------------------------------------------- required columns / per-video counts
def _label_every_event(project_env, vids, emotion="surprise"):
    """SYNTHETIC emotion labels for EVERY catalogued event (as if someone watched every video)."""
    root = project_env["root"]
    lab = root / "presets" / PRESET / "sfx_emotion_labels.csv"
    rows = ["video_id,t,emotion,labeled_by"]
    for vid in vids:
        for e in json.loads(sfx_events_path(PRESET, vid).read_text())["events"]:
            rows.append(f"{vid},{float(e['t']):.3f},{emotion},tester-who-watched(SYNTHETIC)")
    lab.write_text("\n".join(rows) + "\n", encoding="utf-8")
    return lab


@pytest.mark.slow
def test_catalog_is_not_measured_while_a_required_column_is_unmeasured(project_env):
    """User: 종류마다 '종류 / 편당 개수 / 직전 자막 종류 / 화면 사건 / 감정 / 자리 규칙 / 표본 3편' — a catalog whose
    emotion column (no watched labels) or screen-event column (synv4 has no visual analysis) is unmeasured for a type
    is 'partial', never 'measured'."""
    cat = C.build_catalog(PRESET, video_ids=VIDS, write=False)
    assert cat["status"] == "partial" and cat["blocker"]
    assert set(cat["unmeasured_columns"]["emotion"]) == {t["type_id"] for t in cat["types"]}
    assert "감정" in cat["blocker"]
    for t in cat["types"]:
        assert t["columns"]["emotion"] == "unmeasured" and t["columns"]["per_video_count"] == "measured"
    assert cat["column_status"]["emotion"] == "unmeasured" and cat["column_status"]["per_video_count"] == "measured"


@pytest.mark.slow
def test_catalog_measured_only_when_every_column_is_measured(project_env):
    vids = ["synv1", "synv2", "synv3"]                    # all three have SYNTHETIC visual analysis files
    C.build_catalog(PRESET, video_ids=vids)               # assigns type ids (the label template lists them)
    lab = _label_every_event(project_env, vids)
    try:
        cat = C.build_catalog(PRESET, video_ids=vids, write=False)
        assert cat["status"] == "measured" and cat["blocker"] is None, cat.get("unmeasured_columns")
        assert cat["unmeasured_columns"] == {}
        assert all(t["emotion"]["mode"] == "surprise" for t in cat["types"])
        # one type loses its labels -> partial again
        rows = lab.read_text(encoding="utf-8").splitlines()
        first = next(t for t in cat["types"] if t["class"] == "edit_sfx")
        drop = {(e["video_id"], e["t"]) for e in _events_of(first["type_id"], vids)}
        keep = [rows[0]] + [r for r in rows[1:] if (r.split(",")[0], round(float(r.split(",")[1]), 3)) not in drop]
        lab.write_text("\n".join(keep) + "\n", encoding="utf-8")
        cat2 = C.build_catalog(PRESET, video_ids=vids, write=False)
        assert cat2["status"] == "partial" and cat2["unmeasured_columns"] == {"emotion": [first["type_id"]]}
    finally:
        lab.unlink(missing_ok=True)
        C.build_catalog(PRESET, video_ids=VIDS)


def _events_of(type_id, vids):
    out = []
    for vid in vids:
        for e in json.loads(sfx_events_path(PRESET, vid).read_text())["events"]:
            if e.get("type_id") == type_id:
                out.append({"video_id": vid, "t": round(float(e["t"]), 3)})
    return out


@pytest.mark.slow
def test_per_video_counts_and_totals_are_stored(project_env, catalog):
    """per_video_count.videos {video_id: count} (zeros included) reproduces the type's statistics, and the catalog
    stores the per-video total of the counted class (edit_sfx) with its statistics -- episode validate reads both."""
    from shortkit.util.stats import pstats_by_group

    fmts = C.video_formats(PRESET)
    for t in catalog["types"]:
        pv = t["per_video_count"]["videos"]
        assert set(pv) == set(VIDS) and sum(pv.values()) == t["n_events"]
        st = pstats_by_group([{"format_id": fmts.get(v), "count": c} for v, c in pv.items()], "count")
        assert st["overall"] == t["per_video_count"]["overall"] and st["by_format"] == t["per_video_count"]["by_format"]
        assert pv == {v: len([m for m in _members(project_env, t["type_id"]) if m[0] == v]) for v in VIDS}
    tot = catalog["per_video_total"]
    assert tot["classes"] == ["edit_sfx"]
    edit = [t for t in catalog["types"] if t["class"] == "edit_sfx"]
    assert tot["videos"] == {v: sum(t["per_video_count"]["videos"][v] for t in edit) for v in VIDS}
    st = pstats_by_group([{"format_id": fmts.get(v), "count": c} for v, c in tot["videos"].items()], "count")
    assert tot["overall"] == st["overall"] and tot["by_format"] == st["by_format"]
    inc = catalog["per_video_total_incl_silence"]
    assert inc["classes"] == ["edit_sfx", "intentional_silence"]
    sil = next(t for t in catalog["types"] if t["class"] == "intentional_silence")
    assert inc["videos"] == {v: tot["videos"][v] + sil["per_video_count"]["videos"][v] for v in VIDS}
