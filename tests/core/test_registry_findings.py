"""Regression tests for the registry / preset-layer review findings (S1-07, S1-09, S1-10, S1-12, S1-15, S1-16,
S1-19, S2QA-07).

Every test runs in its own temporary project root with a copy of the joshuamagazine preset.  All measurement
files, access logs, plans and library entries written here are CLEARLY LABELLED SYNTHETIC FIXTURES
("synthetic_fixture": true) -- no reference video was measured."""
from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
import yaml

from shortkit import config, paths

P = "presets/joshuamagazine"


@pytest.fixture()
def proj(tmp_path, monkeypatch):
    repo = paths.project_root()
    root = tmp_path / "proj"
    root.mkdir()
    shutil.copy(repo / "shortkit.root", root / "shortkit.root")
    shutil.copytree(repo / P, root / P, ignore=shutil.ignore_patterns("analysis", "videos", "access_logs",
                                                                       "measured.yaml", "settings_registry.yaml"))
    (root / "warehouse").mkdir()
    (root / "episodes").mkdir()
    (root / "assets/library/music").mkdir(parents=True)
    monkeypatch.setenv("SHORTKIT_ROOT", str(root))
    monkeypatch.chdir(root)
    return root


def snap_at(root: Path) -> str:
    return json.loads((root / P / "reference/latest100.json").read_text("utf-8"))["captured_at"]


def meas(root: Path, name: str, items: list[dict], **hdr) -> Path:
    """SYNTHETIC measurement file of this preset's fixed snapshot (unless hdr overrides it)."""
    body = {"schema": "shortkit.measurement/1", "group": name, "preset_id": "joshuamagazine-v1",
            "source_snapshot": snap_at(root), "synthetic_fixture": True}
    body.update(hdr)
    body = {k: v for k, v in body.items() if v is not None}
    body["items"] = items
    f = root / P / "measurements" / f"{name}.json"
    f.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    return f


def item(key, value, **kw):
    return {"key": key, "status": "measured", "value": value, "overall": {"n": 3}, "by_format": {}, **kw}


def apply():
    from shortkit import preset_cli

    return preset_cli.apply_measurements("joshuamagazine")


def sync(**kw):
    kw.setdefault("qa_declarations", {})
    return config.sync_registry("joshuamagazine", **kw)["entries"]


# ----------------------------------------------------------------------------- S1-09 coordinates + resolution
def test_apply_rescales_px_items_to_the_measured_canvas(proj):
    meas(proj, "zz_synth_canvas", [item("canvas.width", 720, unit="px", resolution=None),
                                   item("canvas.height", 1280, unit="px", resolution=None)])
    stored_at = {"resolution": [1080, 1920], "source": "preset (provisional)"}
    meas(proj, "zz_synth_text", [
        item("text.roles.title.anchor.x", 540.0, unit="px", resolution=[1080, 1920], scaled_to=stored_at,
             by_format={"F1": {"n": 2, "value": 540.0}}),
        item("text.roles.title.anchor.y", 330.0, unit="px", resolution=[1080, 1920], scaled_to=stored_at),
        item("text.roles.title.size_px", 90.0, unit="px", resolution=[1080, 1920], scaled_to=stored_at),
        # stored at another aspect ratio: cannot be placed on the canvas -> not applied (stays provisional)
        item("text.roles.title.outline_px", 8.0, unit="px", resolution=[1080, 1350])])
    r = apply()
    pr = config.load_preset("joshuamagazine")
    assert pr.canvas_resolution() == [720, 1280]
    assert pr.peek("text.roles.title.anchor.x") == 360.0          # centre stays the centre
    assert pr.peek("text.roles.title.anchor.y") == pytest.approx(220.0)
    assert pr.peek("text.roles.title.size_px") == 60.0
    assert config.load_preset("joshuamagazine", "F1").peek("text.roles.title.anchor.x") == 360.0
    my = yaml.safe_load((proj / P / "measured.yaml").read_text("utf-8"))
    assert my["canvas_resolution"] == [720, 1280]
    assert {x["key"] for x in r["rescaled"]} >= {"text.roles.title.anchor.x", "text.roles.title.size_px"}
    assert [x["key"] for x in r["not_applied"]] == ["text.roles.title.outline_px"]
    assert pr.origin("text.roles.title.outline_px") == "provisional"
    ent = sync(access_logs=[], discover=False)
    assert ent["text.roles.title.outline_px"]["resolution_state"] == "apply_pending"
    assert ent["text.roles.title.anchor.x"]["value_resolution"] == [720, 1280]
    assert "text.roles.title.outline_px" in config.audit("joshuamagazine", production=True)["unmeasured"]
    # the effective canvas moves after apply (requested change): measured px values are in the old space
    (proj / P / "requested_changes.yaml").write_text(yaml.safe_dump(
        {"preset_id": "joshuamagazine-v1", "changes": {"canvas": {"width": 1080, "height": 1920}}}), encoding="utf-8")
    ent = sync(access_logs=[], discover=False)
    assert ent["text.roles.title.anchor.x"]["resolution_state"] == "apply_pending"
    apply()                                                        # re-placed on the effective canvas
    assert config.load_preset("joshuamagazine").peek("text.roles.title.anchor.x") == 540.0
    assert sync(access_logs=[], discover=False)["text.roles.title.anchor.x"]["resolution_state"] == "resolved"


def test_format_does_not_inherit_an_explicitly_unmeasured_value(proj):
    meas(proj, "zz_synth_font", [item("text.roles.title.font_name", "Noto Sans CJK KR Bold", unit=None,
                                      by_format={"F1": {"n": 4, "value": "Noto Sans CJK KR Bold", "verdict": "identical"},
                                                 "F2": {"n": 2, "value": None, "verdict": "similar"}})])
    meas(proj, "zz_synth_presence", [item("presence.zoom", "present", unit="tri_state",
                                          by_format={"F1": {"n": 3, "value": "present"},
                                                     "F2": {"n": 0, "value": None}})])
    apply()
    base_font = yaml.safe_load((proj / P / "preset.yaml").read_text("utf-8"))["text"]["roles"]["title"]["font_name"]
    f1, f2 = config.load_preset("joshuamagazine", "F1"), config.load_preset("joshuamagazine", "F2")
    assert f1.peek("text.roles.title.font_name") == "Noto Sans CJK KR Bold" and f1.origin("text.roles.title.font_name") == "measured"
    assert f2.peek("text.roles.title.font_name") == base_font
    assert f2.origin("text.roles.title.font_name") == "provisional"
    assert "text.roles.title.font_name" in f2.unmeasured_keys()
    assert f2.origin("presence.zoom") == "provisional" and f2.peek("presence.zoom") == "unmeasured"
    assert f1.peek("presence.zoom") == "present"
    # a format that has no entry at all still uses the channel value
    assert config.load_preset("joshuamagazine", "F3").origin("text.roles.title.font_name") == "measured"


# ----------------------------------------------------------------------------- S1-10 inapplicable keys / routes
def test_keys_that_do_not_apply_given_measured_values_are_not_unmeasured(proj):
    meas(proj, "zz_synth_vis", [item("text.roles.title.box.enabled", False),
                                item("canvas.background.type", "color")])
    apply()
    ent = sync(access_logs=[], discover=False)
    for k in ("text.roles.title.box.color", "text.roles.title.box.alpha", "text.roles.title.box.pad_x",
              "canvas.background.blur_sigma"):
        e = ent[k]
        assert e["status"] == "not_applicable_given" and e["resolution_state"] == "resolved", k
        assert e["not_applicable"]["given"] in ("text.roles.title.box.enabled", "canvas.background.type")
        assert e["not_applicable"]["given_origin"] == "measured"
    assert ent["text.roles.title.box.color"]["not_applicable"]["given_value"] is False
    # the box of a role whose box.enabled is NOT measured stays 못 잼
    assert ent["text.roles.speaker.box.color"]["status"] == "unmeasured"
    # lead_s is defined only for dialogue (speech onset); other roles hold the neutral 0
    assert ent["text.roles.title.timing.lead_s"]["status"] == "not_applicable_given"
    assert ent["text.roles.dialogue.timing.lead_s"]["status"] == "unmeasured"
    pr = config.load_preset("joshuamagazine")
    un = pr.unmeasured_keys()                          # QA gate P1 uses this list
    assert "text.roles.title.box.color" not in un and "canvas.background.blur_sigma" not in un
    assert "text.roles.speaker.box.color" in un
    au = config.audit("joshuamagazine", production=True)
    assert "text.roles.title.box.color" not in au["unmeasured"]
    assert "text.roles.title.box.color" in au["not_applicable_given"]


def test_nonzero_lead_s_of_a_non_dialogue_role_is_still_used(proj):
    f = proj / P / "preset.yaml"
    d = yaml.safe_load(f.read_text("utf-8"))
    d["text"]["roles"]["title"]["timing"]["lead_s"] = 0.3            # resolve applies it -> it matters
    f.write_text(yaml.safe_dump(d, allow_unicode=True), encoding="utf-8")
    ent = sync(access_logs=[], discover=False)
    assert ent["text.roles.title.timing.lead_s"]["status"] == "unmeasured"


def test_resolution_state_is_derived_from_the_blocker_not_a_sticky_default(proj):
    from shortkit.reference.manual import MANUAL_KEYS

    ent = sync(access_logs=[], discover=False)        # snapshot is blocked in this copy
    fit = ent["canvas.video_region.fit"]
    assert fit["measurement_route"]["route"] == "manual_observation" and fit["measurement_route"]["how"]
    assert fit["resolution_state"] == ("blocked_network" if "canvas.video_region.fit" in MANUAL_KEYS else "no_method")
    assert ent["text.roles.title.size_px"]["resolution_state"] == "blocked_network"
    # an OK snapshot: states follow the real blocker of each key
    sf = proj / P / "reference/latest100.json"
    s = json.loads(sf.read_text("utf-8"))
    s["status"] = "ok"
    sf.write_text(json.dumps(s), encoding="utf-8")
    meas(proj, "zz_synth_cases", [{"key": "text.roles.title.box.color", "status": "unmeasured", "value": None,
                                   "blocker": "'title': 박스 사례 없음"},
                                  {"key": "audio.bgm.title", "status": "unmeasured", "value": None,
                                   "blocker": "BGM 식별 안 됨"}])
    for f in (proj / P / "measurements").glob("*.json"):       # older files of the blocked copy: other snapshot
        if not f.name.startswith("zz_"):
            f.unlink()
    ent = sync(access_logs=[], discover=False)
    assert ent["text.roles.title.box.color"]["resolution_state"] == "insufficient_data"
    assert ent["audio.bgm.title"]["resolution_state"] == "open_user_asset"       # empty music library
    assert ent["text.roles.title.size_px"]["resolution_state"] == "no_emitter"
    dec = ent["decorations.arrow.color"]
    assert dec["measurement_route"]["route"] == "manual_observation"
    assert dec["resolution_state"] == "no_emitter" or dec["resolution_state"] == "needs_manual_observation"


# ----------------------------------------------------------------------------- S1-12 count limits
def test_count_limits_are_measured_styles_not_rules(proj):
    for k in ("motion.freeze.max_per_video", "motion.zoom.max_consecutive"):
        assert config.classify_key(k) is None
    ent = sync(access_logs=[], discover=False)
    e = ent["motion.freeze.max_per_video"]
    assert e["status"] == "unmeasured" and "임시값" in e["impact_if_unmeasured"]
    meas(proj, "zz_synth_motion", [item("motion.freeze.max_per_video", 3, unit="count", value_rule="p90")])
    apply()
    assert sync(access_logs=[], discover=False)["motion.freeze.max_per_video"]["status"] == "measured"
    assert config.load_preset("joshuamagazine").peek("motion.freeze.max_per_video") == 3


# ----------------------------------------------------------------------------- S1-07 presence (있다/없다/못 잼)
def test_presence_is_recorded_tristate_overall_and_per_format(proj):
    from shortkit import preset_cli

    ent = sync(access_logs=[], discover=False)
    for k in ("presence.zoom", "presence.freeze", "presence.flash", "presence.crossfade", "presence.bgm",
              "presence.original_audio", "presence.ducking"):
        assert ent[k]["status"] == "unmeasured" and ent[k]["impact_if_unmeasured"], k
    meas(proj, "zz_synth_presence", [
        item("presence.zoom", "present", unit="tri_state", overall={"n": 3, "n_present": 2},
             by_format={"F1": {"n": 2, "value": "present"}, "F2": {"n": 0, "value": None}}),
        item("presence.flash", "absent", unit="tri_state", overall={"n": 3, "n_present": 0},
             by_format={"F1": {"n": 2, "value": "absent"}, "F2": {"n": 1, "value": "absent"}})])
    apply()
    ent = sync(access_logs=[], discover=False)
    assert ent["presence.flash"]["status"] == "measured"
    # the reference never flashes -> the flash style keys do not apply
    assert ent["motion.transitions.flash.dur_s"]["status"] == "not_applicable_given"
    md = preset_cli.write_unresolved("joshuamagazine").read_text("utf-8")
    assert "있다/없다/못 잼" in md
    row = next(ln for ln in md.splitlines() if ln.startswith("| `presence.zoom`"))
    assert row.split("|")[2].strip() == "있다" and row.split("|")[3].strip() == "있다" and row.split("|")[4].strip() == "못 잼"
    row = next(ln for ln in md.splitlines() if ln.startswith("| `presence.bgm`"))
    assert row.split("|")[2].strip() == "못 잼"


# ----------------------------------------------------------------------------- S1-15 stage table
def test_stage_table_reads_the_effective_preset_and_stage_evaluators(proj, monkeypatch):
    from shortkit import preset_cli
    from shortkit.reference import high_views, trace_sources

    monkeypatch.setattr(high_views, "stage_status", lambda p: {"item": "HV", "status": "unmeasured", "impact": "i",
                                                              "state": "open", "evidence": "from-high_views"})
    monkeypatch.setattr(trace_sources, "stage_status", lambda p: {"item": "TR", "status": "unmeasured", "impact": "i",
                                                                 "state": "open", "evidence": "from-trace_sources"})
    meas(proj, "zz_synth_audio", [item("audio.bgm.track_id", "song_a")])
    apply()
    st = {s["item"]: s for s in preset_cli._stage_blockers("joshuamagazine")}
    assert st["HV"]["evidence"] == "from-high_views" and st["TR"]["evidence"] == "from-trace_sources"
    bgm = next(s for k, s in st.items() if k.startswith("BGM"))
    assert "song_a" in bgm["evidence"] and "track_id=null" not in bgm["evidence"]
    assert bgm["status"] == "unmeasured" and "title" in bgm["evidence"]         # version/section still 못 잼
    # every identity key measured + the clean file in the library -> measured / resolved
    (proj / "assets/library/music/song_a.wav").write_bytes(b"RIFF synthetic fixture")
    (proj / "assets/library/music/index.yaml").write_text(yaml.safe_dump(
        {"tracks": {"song_a": {"path": "assets/library/music/song_a.wav", "title": "Song A", "version": "original",
                               "synthetic_fixture": True}}}), encoding="utf-8")
    meas(proj, "zz_synth_audio", [item("audio.bgm.track_id", "song_a"), item("audio.bgm.title", "Song A"),
                                  item("audio.bgm.version", "original"), item("audio.bgm.tempo_ratio", 1.0),
                                  item("audio.bgm.section_start_s", 12.0)])
    roles = list(yaml.safe_load((proj / P / "preset.yaml").read_text("utf-8"))["text"]["roles"])
    meas(proj, "zz_synth_fonts", [item(f"text.roles.{r}.font_name", "Noto Sans CJK KR Bold") for r in roles])
    apply()
    st = {s["item"]: s for s in preset_cli._stage_blockers("joshuamagazine")}
    bgm = next(s for k, s in st.items() if k.startswith("BGM"))
    assert (bgm["status"], bgm["state"]) == ("measured", "resolved")
    font = next(s for k, s in st.items() if k.startswith("글꼴"))
    assert (font["status"], font["state"]) == ("measured", "resolved")
    # BGM measured absent in the reference
    meas(proj, "zz_synth_presence", [item("presence.bgm", "absent", unit="tri_state")])
    apply()
    bgm = next(s for s in preset_cli._stage_blockers("joshuamagazine") if s["item"].startswith("BGM"))
    assert bgm["status"] == "absent" and bgm["state"] == "resolved"


# ----------------------------------------------------------------------------- S1-16 tracked code links
def _log(root, ep, cmd, reads, callers=None, saved_at="2026-09-25T00:00:00+00:00"):
    f = root / "episodes" / ep / "build" / f"preset_access_{cmd}.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    body = {"preset_id": "joshuamagazine-v1", "format_id": None, "saved_at": saved_at, "reads": reads,
            "synthetic_fixture": True}
    if callers is not None:
        body["callers"] = callers
    f.write_text(json.dumps(body), encoding="utf-8")
    return f


def test_code_links_are_rebuilt_only_from_the_tracked_archive(proj):
    code = proj / "shortkit/edit/fake_reader.py"
    code.parent.mkdir(parents=True)
    code.write_text("def reader(pr):\n    return pr.get('text.tone.register')\n", encoding="utf-8")
    link = "shortkit/edit/fake_reader.py:reader"
    _log(proj, "t1", "validate", {"text.tone.register": [link]})
    ent = sync()
    assert ent["text.tone.register"]["code"] == [link]
    arch = proj / P / "access_logs/t1__build__preset_access_validate.json"
    assert arch.is_file() and json.loads(arch.read_text())["callers"][link]["fp"]
    # a link injected into the registry (never seen in a log) is NOT carried over
    rf = config.registry_path("joshuamagazine")
    reg = yaml.safe_load(rf.read_text("utf-8"))
    reg["entries"]["text.tone.sentence_end_examples"]["code"] = [link]
    rf.write_text(yaml.safe_dump(reg, allow_unicode=True), encoding="utf-8")
    ent = sync()
    assert ent["text.tone.sentence_end_examples"]["code"] == []
    # fresh clone: episodes/*/build is not tracked -> the same links come from the archive
    shutil.rmtree(proj / "episodes/t1")
    ent2 = sync()
    assert ent2["text.tone.register"]["code"] == [link]
    assert "episodes/t1/build/preset_access_validate.json" in yaml.safe_load(rf.read_text("utf-8"))["access_logs"]
    # the function changes after the read was recorded: stale, not a link (the audit sees no code)
    code.write_text("def reader(pr):\n    return None\n", encoding="utf-8")
    ent3 = sync()
    assert ent3["text.tone.register"]["code"] == []
    assert ent3["text.tone.register"]["code_stale"][0]["state"] == "stale"
    au = config.audit("joshuamagazine", production=False)
    assert "text.tone.register" in au["no_code"] and "text.tone.register" in au["stale_code"]
    # a re-run with the current code (fingerprint recorded at save time) re-links it
    _log(proj, "t1", "validate", {"text.tone.register": [link]},
         callers={link: {"fp": config.code_fingerprint(link)}}, saved_at="2026-09-26T00:00:00+00:00")
    assert sync()["text.tone.register"]["code"] == [link]
    # the function is removed: dead link dropped
    code.write_text("def other():\n    pass\n", encoding="utf-8")
    ent4 = sync()
    assert ent4["text.tone.register"]["code"] == [] and ent4["text.tone.register"]["code_stale"][0]["state"] == "dead"


def test_fingerprint_ignores_comments_and_layout_but_not_code(proj):
    f = proj / "shortkit/x.py"
    f.parent.mkdir(parents=True)
    f.write_text("def g():\n    return 1\n", encoding="utf-8")
    a = config.code_fingerprint("shortkit/x.py:g")
    f.write_text("# header\n\n\ndef g():   # note\n    return 1\n", encoding="utf-8")
    assert config.code_fingerprint("shortkit/x.py:g", {}) == a
    f.write_text("def g():\n    return 2\n", encoding="utf-8")
    assert config.code_fingerprint("shortkit/x.py:g", {}) != a


def _reads_in_comprehension(pr):
    return {k: pr.get(k) for k in ("canvas.fps",)}


def test_anonymous_readers_are_named_by_their_enclosing_function(proj):
    pr = config.load_preset("joshuamagazine")
    _reads_in_comprehension(pr)
    (caller,) = pr.log.reads["canvas.fps"]
    assert caller.endswith(":_reads_in_comprehension"), caller


# ----------------------------------------------------------------------------- S2QA-07 measurement provenance
def test_measurement_file_of_another_preset_is_refused(proj):
    from shortkit import preset_cli

    meas(proj, "zz_other_channel", [item("text.roles.title.size_px", 99, unit="px", resolution=[1080, 1920])],
         preset_id="otherchannel-v1", source_snapshot="2025-01-01T00:00:00+00:00")
    with pytest.raises(config.PresetMixError):
        config.load_measurement_items(proj / P)
    with pytest.raises(config.PresetMixError):
        preset_cli.apply_measurements("joshuamagazine")
    assert not (proj / P / "measured.yaml").exists()
    assert config.load_preset("joshuamagazine").origin("text.roles.title.size_px") == "provisional"


@pytest.mark.parametrize("hdr,ok", [
    ({"source_snapshot": "2025-01-01T00:00:00+00:00"}, False),         # older / foreign snapshot
    ({"preset_id": None, "source_snapshot": None}, False),              # origin unknown
    ({"source_snapshot": None}, False),                                 # our id but no snapshot
    ({"preset_id": None}, True),                                        # this preset's snapshot, no id
    ({}, True)])
def test_measurement_file_of_another_snapshot_is_not_applied(proj, hdr, ok):
    for f in (proj / P / "measurements").glob("*.json"):     # the key's only source is the file under test
        f.unlink()
    meas(proj, "zz_synth", [item("text.roles.title.color", "#FF0000")], **hdr)
    it = config.load_measurement_items(proj / P)["text.roles.title.color"]
    assert (it["status"] == "measured") is ok
    apply()
    pr = config.load_preset("joshuamagazine")
    assert (pr.origin("text.roles.title.color") == "measured") is ok
    if not ok:
        assert it["refused"]["reason"] and it["refused"]["value"] == "#FF0000"
        assert sync(access_logs=[], discover=False)["text.roles.title.color"]["resolution_state"] == "remeasure"


# ----------------------------------------------------------------------------- S1-19 plan coordinates
def test_plan_canvas_resolution_check_and_apply_reports_affected_plans(proj):
    pr = config.load_preset("joshuamagazine")
    assert config.plan_canvas_check({}, pr)["status"] == "missing"
    assert config.plan_canvas_check({"canvas_resolution": [1080, 1920]}, pr)["status"] == "ok"
    mm = config.plan_canvas_check({"canvas_resolution": [720, 1280]}, pr)
    assert mm["status"] == "mismatch" and mm["same_aspect"] and mm["scale"] == [1.5, 1.5]
    assert config.rescale_px(540, "text.roles.title.anchor.x", [1080, 1920], [720, 1280]) == 360
    with pytest.raises(config.ResolutionMismatch):
        config.rescale_px(540, "text.roles.title.anchor.x", [1080, 1920], [1080, 1350])
    for ep, res in (("e_old", [1080, 1920]), ("e_none", None)):
        d = proj / "episodes" / ep
        d.mkdir()
        plan = {"episode_id": ep, "preset_id": "joshuamagazine-v1", "synthetic_fixture": True}
        if res:
            plan["canvas_resolution"] = res
        (d / "plan.yaml").write_text(yaml.safe_dump(plan), encoding="utf-8")
    meas(proj, "zz_synth_canvas", [item("canvas.width", 720, unit="px"), item("canvas.height", 1280, unit="px")])
    r = apply()
    got = {p["plan"]: p["status"] for p in r["plans_to_recheck"]}
    assert got == {"episodes/e_old/plan.yaml": "mismatch", "episodes/e_none/plan.yaml": "missing"}
