"""Regression tests for the D-qa review findings (S1-06, S1-13, S2QA-01..16, S4-09, font exact-position check).

Every fixture here is SYNTHETIC: hand-written rows / probe dicts / catalogs / formats tables, tiny lavfi-generated
MP4s, and the synthetic QA episode renderer (tests/qa/qa_synth.py).  Anything written goes to a temporary project
root; no external platform is contacted.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest

from shortkit import config, paths
from shortkit.qa import checks, gate

REAL_ROOT = paths.project_root()
P = "presets/joshuamagazine"


@pytest.fixture()
def temp_root(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    shutil.copy(REAL_ROOT / "shortkit.root", root / "shortkit.root")
    shutil.copytree(REAL_ROOT / P, root / P,
                    ignore=shutil.ignore_patterns("videos", "frames", "stems", "*.wav", "*.mp4", "analysis"))
    (root / "warehouse").mkdir()
    (root / "episodes").mkdir()
    monkeypatch.setenv("SHORTKIT_ROOT", str(root))
    return root


def _snap_at(root) -> str | None:
    from shortkit.util.jsonio import read_json

    return (read_json(root / P / "reference" / "latest100.json") or {}).get("captured_at")


def _measure(root, name: str, items: list[dict]) -> None:
    """SYNTHETIC measurement file of THIS preset and its fixed snapshot (the loader refuses files of unknown origin)."""
    from shortkit.util.jsonio import write_json

    write_json(root / P / "measurements" / f"{name}.json", {"schema": "shortkit.measurement/1", "group": name,
                                                             "preset_id": "joshuamagazine-v1",
                                                             "source_snapshot": _snap_at(root), "items": items})


def _measured_layer(root, common: dict) -> None:
    from shortkit.util.jsonio import write_yaml

    write_yaml(root / P / "measured.yaml", {"preset_id": "joshuamagazine-v1", "common": common})


def _row(cid, subj, status, required=True, category="컷", kind="output_vs_plan", **kw):
    return {"check_id": cid, "row_id": f"{cid}:{subj}", "status": status, "required": required, "kind": kind,
            "category": category, "intended_change": False, **kw}


def _builder(mode="test", plan=None, **kw):
    pr = config.load_preset("joshuamagazine")
    res = SimpleNamespace(mode=mode, format_id="UNCLASSIFIED", clips=[], captions=[], decorations=[],
                          audio=SimpleNamespace(sfx=[], originals=[], bgm=None), canvas={}, duration=10.0)
    ctx = SimpleNamespace(preset=pr, resolved=res, episode_id="e", plan=plan or {}, options={}, fps=30.0,
                          info=SimpleNamespace(duration=10.0, width=720, height=1280, fps=30.0, audio_rate=48000),
                          canvas_w=720, canvas_h=1280, reference_analysis={}, reference_id=None, reference_mp4=None,
                          reference_info={}, **kw)
    return checks.RowBuilder(ctx)


def _tiny_mp4(path, seconds=1.0, color="blue"):
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c={color}:s=64x96:r=30:d={seconds}",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)], check=True)


# ============================================================================ S2QA-01: 못 잼 never becomes complete
ROWS_01 = [_row("identity.logo_templates", "all", "unmeasured", required=False, category=checks.CAT["identity"]),
           _row("audio.original", "music0", "unmeasured", required=False, category=checks.CAT["original"]),
           _row("caption.tone", "emoji", "unmeasured", required=False, category=checks.CAT["cap_text"]),
           _row("audio.sfx.no_event", "all", "same", category=checks.CAT["sfx_no_event"])]


def test_production_gate_is_not_complete_with_unrequired_unmeasured_rows():
    g = gate.evaluate(ROWS_01, mode="production", mp4_sha_measured="a", mp4_sha_now="a", unmeasured_preset_keys=[],
                      production=True, plan={"episode_index": 2, "approval": {"approved": True}})
    assert g["complete"] is False and g["pass"] is False
    p4 = next(f for f in g["failures"] if f["rule"] == "P4")
    assert set(p4["rows"]) == {"identity.logo_templates:all", "audio.original:music0", "caption.tone:emoji"}
    assert "못 잼 3건" in g["verdict_ko"]
    # test mode: the same rows are a warning (never complete anyway: P3)
    g = gate.evaluate(ROWS_01, mode="test", mp4_sha_measured="a", mp4_sha_now="a", unmeasured_preset_keys=[])
    assert g["pass"] and not g["complete"] and any(w["rule"] == "P4" for w in g["warnings"])


def test_a_covered_informational_row_does_not_block_but_an_uncovered_one_does():
    role = _row("caption.font", "role_title", "same", category=checks.CAT["font"])
    per = _row("caption.font", "t1", "unmeasured", required=False, category=checks.CAT["font"],
               covered_by="caption.font:role_title")
    ne = _row("audio.sfx.no_event", "all", "same")
    kw = dict(mode="production", mp4_sha_measured="a", mp4_sha_now="a", unmeasured_preset_keys=[], production=True)
    assert gate.evaluate([role, per, ne], **kw)["complete"] is True
    # the covering row itself unmeasured (and required) -> the per-caption row counts again (and G2 fails)
    g = gate.evaluate([dict(role, status="unmeasured"), per, ne], **kw)
    assert not g["complete"] and "caption.font:t1" in next(f for f in g["failures"] if f["rule"] == "P4")["rows"]


# ============================================================================ S2QA-11: reference logo templates
def test_missing_logo_templates_are_required_in_production(temp_root):
    b = _builder(mode="production")
    r = checks._logo_template_check(b.ctx, b.pget("identity_exclusions.logo_templates_dir"))
    assert r["status"] == "unmeasured" and r["required"] is True
    b = _builder(mode="test")
    assert checks._logo_template_check(b.ctx, b.pget("identity_exclusions.logo_templates_dir"))["required"] is False


# ============================================================================ S2QA-14: plan declarations are not measurements
def _orig_builder(mode, hem, stem, human=None, sha="abc"):
    clip = SimpleNamespace(id="c1", source_id="s1")
    orig = SimpleNamespace(clip_id="c1", out_start=0.0, out_end=2.0, gain_db=0.0, stem=stem, reason="대사", path="x.wav")
    b = _builder(mode=mode, plan={"sources": [{"id": "s1", "has_embedded_music": hem}]})
    b.ctx.resolved.clips = [clip]
    b.ctx.resolved.audio.originals = [orig]
    b.ctx.options.update(human_checks=human or [], mp4_sha256=sha)
    checks._rows_original(b, {"originals": {"windows": [], "expected_kept": [[0.0, 2.0]]}})
    return next(r for r in b.rows if r["row_id"] == "audio.original:music0")


def test_embedded_music_verdict_is_never_the_plan_declaration(temp_root):
    r = _orig_builder("production", False, "raw")
    assert r["status"] == "unmeasured" and r["required"] is True and "선언" in r["note"]
    r = _orig_builder("production", True, "vocals")
    assert r["status"] == "unmeasured" and r["required"] is True
    assert _orig_builder("production", True, "raw")["status"] == "different"
    # a person's listening record on THIS mp4 decides; one made on another mp4 does not count
    rec = {"row_id": "audio.original:music0", "kind": "listen", "verdict": "same", "by": "SYNTHETIC-tester",
           "at": "2026-09-25", "note": "보존 구간 3회 청취, 음악 없음", "mp4_sha256": "abc"}
    r = _orig_builder("production", True, "vocals", human=[rec])
    assert r["status"] == "same" and r["observed"]["basis"] == "사람 청취 기록"
    r = _orig_builder("production", True, "vocals", human=[dict(rec, mp4_sha256="other")])
    assert r["status"] == "unmeasured"


def test_human_check_record_validation(temp_root):
    from shortkit.qa import human

    (temp_root / "episodes" / "e1" / "qa").mkdir(parents=True)
    with pytest.raises(ValueError):
        human.record("e1", "audio.original:music0", "listen", "same", "", "note", "abc")
    with pytest.raises(ValueError):
        human.record("e1", "audio.original:music0", "listen", "maybe", "me", "note", "abc")
    rec = human.record("e1", "audio.original:music0", "listen", "same", "SYNTHETIC-tester", "들어 봄", "abc")
    assert human.latest(human.load("e1"), "audio.original:music0", "abc") == rec
    assert human.latest(human.load("e1"), "audio.original:music0", "zzz") is None


def _sfx_on_cut(probes, mode="production", human=None):
    b = _builder(mode=mode)
    b.ctx.options.update(human_checks=human or [], mp4_sha256="abc")
    s = SimpleNamespace(id="fx1", type="whoosh", event_t=2.0, event_desc="문이 열림")
    d = {"t": 2.03, "type": "whoosh"}
    checks._sfx_on_cut_rows(b, [(s, d)], probes)
    return {r["row_id"]: r for r in b.rows}


def test_sfx_on_a_measured_cut_needs_an_independent_event():
    video = {"transitions": {"boundaries": [{"observed": {"type": "cut", "t": 2.0}}], "unexpected": []}}
    rows = _sfx_on_cut({"video": video})
    r = rows["audio.sfx.on_cut:fx1"]
    assert r["status"] == "unmeasured" and r["required"] is True
    # a caption appearing at the event (measured in the output) is independent evidence
    rows = _sfx_on_cut({"video": video, "text": {"captions": [{"id": "c", "found": True, "onset": 2.05}]}})
    assert rows["audio.sfx.on_cut:fx1"]["status"] == "same"
    # a person who watched it decides
    rec = {"row_id": "audio.sfx.on_cut:fx1", "kind": "watch", "verdict": "different", "by": "SYNTHETIC-tester",
           "at": "2026-09-25", "note": "컷 때문", "mp4_sha256": "abc"}
    assert _sfx_on_cut({"video": video}, human=[rec])["audio.sfx.on_cut:fx1"]["status"] == "different"
    # no cut near the SFX: no per-SFX row
    far = {"transitions": {"boundaries": [{"observed": {"type": "cut", "t": 5.0}}], "unexpected": []}}
    assert "audio.sfx.on_cut:fx1" not in _sfx_on_cut({"video": far})


# ============================================================================ S2QA-06: one requested key of a row
def test_single_key_requested_change_is_an_intended_change(temp_root):
    from shortkit.util.jsonio import write_yaml

    write_yaml(temp_root / P / "requested_changes.yaml", {
        "preset_id": "joshuamagazine-v1", "changes": {"text": {"roles": {"situation": {"anchor": {"y": 1500}}}}},
        "log": [{"at": "2026-09-25", "by": "SYNTHETIC", "keys": ["text.roles.situation.anchor.y"]}]})
    b = _builder()
    keys = checks._role_keys("situation", ["anchor.x", "anchor.y"])
    cmp = lambda o, r: abs(o["x"] - float(r["text.roles.situation.anchor.x"])) <= 20 and \
        abs(o["y"] - float(r["text.roles.situation.anchor.y"])) <= 20     # noqa: E731
    b.style_row("caption.position", "situation_ref", "위치", checks.CAT["text_pos"], keys, {"x": 540, "y": 1500}, cmp)
    rows = {r["row_id"]: r for r in b.rows}
    r = rows["caption.position:situation_ref"]
    assert r["status"] == "different" and r["intended_change"] is True and r["keys"] == ["text.roles.situation.anchor.y"]
    o = rows["caption.position:situation_ref:others"]            # anchor.x: provisional -> 못 잼, not same
    assert o["status"] == "unmeasured" and o["keys"] == ["text.roles.situation.anchor.x"]
    # the output NOT showing the requested value is an unintended difference
    b2 = _builder()
    b2.style_row("caption.position", "situation_ref", "위치", checks.CAT["text_pos"], keys, {"x": 540, "y": 1430}, cmp)
    assert b2.rows[0]["status"] == "different" and not b2.rows[0]["intended_change"]


# ============================================================================ S2QA-08: exact colour match
def test_exact_colour_match_is_same(temp_root):
    assert checks._cwithin("#FFFFFF", "#FFFFFF", 45) is True
    assert checks._cwithin(None, "#FFFFFF", 45) is None
    _measured_layer(temp_root, {"canvas": {"background": {"type": "color", "color": "#000000"}}})
    _measure(temp_root, "canvas", [
        {"key": "canvas.background.type", "status": "measured", "value": "color", "overall": {"n": 5}},
        {"key": "canvas.background.color", "status": "measured", "value": "#000000", "overall": {"n": 5}}])
    b = _builder()
    b.ctx.resolved.canvas = {"width": 720, "height": 1280, "fps": 30, "background": {"type": "color", "color": "#000000"}}
    b.ctx.resolved.clips = [SimpleNamespace(region=SimpleNamespace(x=0, y=437, w=720, h=405))]
    probes = {"video": {"layout": {"status": "measured", "video_region": [0, 437, 720, 405],
                                   "background": {"type": "color", "color": "#000000"}}}, "text": {}}
    checks.rows_canvas(b, probes)
    r = next(x for x in b.rows if x["row_id"] == "canvas.background:background_ref")
    assert r["status"] == "same", r
    assert "canvas.background.blur_sigma" not in r["keys"]


# ============================================================================ S2QA-10: exit motion
def _cap(**kw):
    base = dict(id="c1", role="speaker", start=1.0, end=3.0, motion_in={"type": "fade", "dur_s": 0.15},
                motion_out={"type": "fade", "dur_s": 0.15})
    base.update(kw)
    return SimpleNamespace(**base)


def test_exit_motion_is_compared_and_unmeasurable_types_are_not_same():
    fr = 1 / 30
    b = _builder()
    m = {"motion_in_obs": {"type": "fade", "fade_dur_s": 0.167}, "motion_out_obs": {"type": "fade", "fade_dur_s": 0.167},
         "onset": 1.0, "offset": 3.0}
    checks._motion_rows(b, _cap(), m, "speaker", "[c1]", {}, fr)
    rows = {r["row_id"]: r for r in b.rows}
    assert rows["caption.motion:c1"]["status"] == "same"
    out = rows["caption.motion:c1:out"]
    assert out["status"] == "same" and "text.roles.speaker.motion_out.dur_s" in out["keys"]
    # the fade out lasts twice as long as planned -> different
    b = _builder()
    checks._motion_rows(b, _cap(), dict(m, motion_out_obs={"type": "fade", "fade_dur_s": 0.3}), "speaker", "[c1]", {}, fr)
    assert {r["row_id"]: r for r in b.rows}["caption.motion:c1:out"]["status"] == "different"
    # a slide entrance is not measured by the probe: 못 잼, never 'same'
    b = _builder()
    checks._motion_rows(b, _cap(motion_in={"type": "slide_up", "dur_s": 0.2, "offset_px": 40}),
                        dict(m, motion_in_obs={"type": "none"}), "speaker", "[c1]", {}, fr)
    assert {r["row_id"]: r for r in b.rows}["caption.motion:c1"]["status"] == "unmeasured"


def test_fade_length_from_presence_curves():
    from shortkit.qa.probes_text import fade_length

    ts = [i / 30 for i in range(12)]
    rise = [0, 0, 0.17, 0.33, 0.5, 0.66, 0.92, 1, 1, 1, 1, 1]           # libass \fad(200) at 30 fps
    assert fade_length(ts, rise, rising=True) == pytest.approx(0.2, abs=1e-3)
    fall = [1, 1, 1, 1, 0.97, 0.5, 0.29, 0.11, 0.0, 0, 0, 0]
    assert fade_length(ts, fall, rising=False) == pytest.approx(ts[8] - ts[4], abs=1e-3)
    assert fade_length(ts, [1] * 12, rising=False) is None


# ============================================================================ S2QA-13 / S4-09: SFX count rule = validate's
def _catalog(root):
    from shortkit.util.jsonio import write_json
    from shortkit.util.stats import pstats

    vids = ["v1", "v2", "v3", "v4", "v5"]
    counts = {"whoosh_a": [0, 1, 1, 2, 3], "crowd_cheer": [1, 1, 1, 2, 2], "silence_cut": [1, 1, 1, 1, 1]}
    cls = {"whoosh_a": "edit_sfx", "crowd_cheer": "onsite_sound", "silence_cut": "intentional_silence"}
    types = []
    for t, c in counts.items():
        st = pstats(c, 4)
        types.append({"type_id": t, "class": cls[t], "per_video_count": {"overall": {k: st[k] for k in ("n", "p10", "p50", "p90")},
                                                                         "videos": dict(zip(vids, c))}})
    write_json(root / P / "sfx_catalog.json", {"schema": "shortkit.sfx_catalog/1", "preset_id": "joshuamagazine-v1",
                                               "status": "measured", "basis": {"videos": vids}, "types": types})


def _count_rows(obs_c, silences):
    b = _builder()
    ap = {"bgm": {"status": "measured", "found": True, "silent_ranges_obs": silences, "audible_span_obs": [0.0, 12.0]}}
    checks._rows_sfx_catalog(b, ap, obs_c)
    return {r["row_id"]: r for r in b.rows}


def test_catalog_counts_follow_the_validate_rule(temp_root):
    from collections import Counter

    _catalog(temp_root)
    rows = _count_rows(Counter({"whoosh_a": 3}), [[6.8, 7.45]])
    assert rows["audio.sfx.count:catalog:whoosh_a"]["status"] == "same"      # 3 was observed in a reference video
    assert "audio.sfx.count:catalog:crowd_cheer" not in rows                  # onsite sound: never counted
    sil = rows["audio.sfx.count:catalog:silence_cut"]
    assert sil["status"] == "same" and sil["observed"] == 1                   # counted from the OUTPUT's silences
    assert "audio.sfx.count:catalog:total" in rows
    # 0 whooshes: inside [floor(p10), ceil(p90)] = [0, 3] -> same (the old raw p10 0.4 said different)
    rows = _count_rows(Counter(), [])
    assert rows["audio.sfx.count:catalog:whoosh_a"]["status"] == "same"
    assert "audio.sfx.count:catalog:silence_cut" not in rows                  # no silences -> silence type not counted
    # 5 whooshes: outside the range and never observed -> different
    assert _count_rows(Counter({"whoosh_a": 5}), [])["audio.sfx.count:catalog:whoosh_a"]["status"] == "different"
    # an onsite type placed as an edit SFX -> different
    assert _count_rows(Counter({"crowd_cheer": 1}), [])["audio.sfx.count:catalog:crowd_cheer"]["status"] == "different"


# ============================================================================ S2QA-15: cut structure vs the format
def test_cut_structure_rows_measure_the_output_and_need_the_preset_keys(temp_root):
    from shortkit.util.jsonio import read_yaml, write_yaml

    video = {"transitions": {"boundaries": [{"observed": {"type": "cut", "t": 2.0}}, {"observed": {"type": "cut", "t": 5.0}}],
                             "unexpected": []}}
    b = _builder()
    checks._rows_cut_structure(b, {"video": video})
    rows = {r["row_id"]: r for r in b.rows}
    r = rows["structure.cuts:rate_ref"]
    assert r["status"] == "unmeasured" and "structure.cuts_per_10s.p10" in r["note"]
    assert r["observed"]["cuts_per_10s"] == pytest.approx(2.0) and rows["structure.cuts:shot_len_ref"]["observed"][
        "shot_len_median_s"] == pytest.approx(3.0)
    # once `ref aggregate` provides the keys (SYNTHETIC measured values), the output is judged against them
    y = read_yaml(temp_root / P / "preset.yaml")
    y["structure"]["cuts_per_10s"] = {"p10": 3.0, "p90": 6.0}
    y["structure"]["shot_len_s"] = {"p10": 1.0, "p90": 4.0}
    write_yaml(temp_root / P / "preset.yaml", y)
    _measured_layer(temp_root, {"structure": {"cuts_per_10s": {"p10": 3.0, "p90": 6.0}, "shot_len_s": {"p10": 1.0, "p90": 4.0}}})
    _measure(temp_root, "visual_structure", [{"key": k, "status": "measured", "value": v, "overall": {"n": 10}}
                                             for k, v in (("structure.cuts_per_10s.p10", 3.0), ("structure.cuts_per_10s.p90", 6.0),
                                                          ("structure.shot_len_s.p10", 1.0), ("structure.shot_len_s.p90", 4.0))])
    b = _builder()
    checks._rows_cut_structure(b, {"video": video})
    rows = {r["row_id"]: r for r in b.rows}
    assert rows["structure.cuts:rate_ref"]["status"] == "different"            # 2 cuts / 10 s < p10 3
    assert rows["structure.cuts:shot_len_ref"]["status"] == "same"


# ============================================================================ S1-06 / S2QA-04: reference comparison
def _formats(root, rep="refvid00001"):
    from shortkit.util.jsonio import write_yaml

    write_yaml(root / P / "formats.yaml", {"schema": "shortkit.formats/1", "preset_id": "joshuamagazine-v1", "status": "measured",
                                          "table": [{"format_id": "F1", "structure_type": "SYNTHETIC",
                                                     "members": [rep, "refvid00002"],
                                                     "intro_variants": [{"intro_type": "cold_open", "n": 2}],
                                                     "representative": {"video_id": rep}}],
                                          "assignments": {rep: "F1", "refvid00002": "F1"}})


def test_representative_video_comes_from_formats_yaml(temp_root):
    from shortkit.qa import representative_for

    pr = config.load_preset("joshuamagazine", "F1")
    r = representative_for(pr, "UNCLASSIFIED")
    assert r["video_id"] is None and "포맷" in r["reason"]
    _formats(temp_root)
    r = representative_for(pr, "F1")
    assert r["video_id"] == "refvid00001" and r["path"] is None and "ref download" in r["reason"]
    _tiny_mp4(temp_root / P / "reference" / "videos" / "refvid00001.mp4")
    r = representative_for(pr, "F1")
    assert r["path"] == f"{P}/reference/videos/refvid00001.mp4" and r["intro_variants"][0]["intro_type"] == "cold_open"


def _episode(root, ep="e1", fmt="F1", mode="production"):
    """SYNTHETIC episode: resolved.json + a tiny output MP4 (enough for load_context / gate_episode)."""
    from shortkit.util.jsonio import write_json, write_yaml

    res = json.loads((REAL_ROOT / "episodes/test-qa-good/build/resolved.json").read_text())
    res.update(episode_id=ep, format_id=fmt, mode=mode, output_path=f"episodes/{ep}/output/{ep}.mp4",
               ass_path=f"episodes/{ep}/build/captions.ass")
    write_json(root / "episodes" / ep / "build" / "resolved.json", res)
    (root / "episodes" / ep / "build" / "captions.ass").write_text("[Script Info]\n", encoding="utf-8")
    write_yaml(root / "episodes" / ep / "plan.yaml", {"episode_id": ep, "mode": mode, "episode_index": 2})
    _tiny_mp4(root / "episodes" / ep / "output" / f"{ep}.mp4")
    return res


def test_qa_context_defaults_to_the_format_representative_and_keeps_other_mp4s_apart(temp_root):
    from shortkit.qa import load_context

    _formats(temp_root)
    _tiny_mp4(temp_root / P / "reference" / "videos" / "refvid00001.mp4")
    _episode(temp_root)
    ctx = load_context("e1")
    assert ctx.reference_id == "refvid00001" and ctx.reference_mp4 is not None
    assert ctx.reference_info["chosen_by"] == "formats.yaml 대표 영상" and ctx.deliverable is True
    _tiny_mp4(temp_root / "episodes/e1/output/alt.mp4", color="red")
    ctx = load_context("e1", mp4="episodes/e1/output/alt.mp4")
    assert ctx.deliverable is False and ctx.qa_dir == temp_root / "episodes/e1/qa/other_mp4/alt"


def test_production_gate_requires_the_representative_reference():
    ok = [_row("audio.sfx.no_event", "all", "same")]
    kw = dict(mode="production", mp4_sha_measured="a", mp4_sha_now="a", unmeasured_preset_keys=[], production=True,
              plan={"episode_index": 2})
    rep = {"format_id": "F1", "video_id": "refvid00001"}
    full = {"video_id": "refvid00001", "path": "r.mp4", "representative": rep,
            "analysis_files": ["audio_sfx_events", "captions", "shots"], "sheets": ["s.png"]}
    assert gate.evaluate(ok, reference={"representative": {"reason": "no formats"}}, **kw)["failures"][0]["rule"] == "R1"
    assert not [f for f in gate.evaluate(ok, reference=full, **kw)["failures"] if f["rule"] == "R1"]
    other = dict(full, video_id="refvid00002")
    assert any(f["rule"] == "R1" for f in gate.evaluate(ok, reference=other, **kw)["failures"])
    assert not [f for f in gate.evaluate(ok, reference=dict(other, override_reason="대표 영상 파일 손상, 같은 포맷 2위 사용"),
                                         **kw)["failures"] if f["rule"] == "R1"]
    assert any(f["rule"] == "R1" for f in gate.evaluate(ok, reference=dict(full, analysis_files=["captions"]),
                                                        **kw)["failures"])
    # test mode: a warning only
    g = gate.evaluate(ok, reference={}, **dict(kw, mode="test", production=None))
    assert any(w["rule"] == "R1" for w in g["warnings"]) and not any(f["rule"] == "R1" for f in g["failures"])


def test_same_time_grid_cells():
    from shortkit.qa import grid

    ref = [{"start": 0.0, "end": 10.0, "role": "title"}, {"start": 0.3, "end": 2.5, "role": "situation"}]
    ours = [{"id": "t", "role": "title", "start": 0.0, "end": 10.0, "measured": True, "plan_start": 0, "plan_end": 10},
            {"id": "s", "role": "situation", "start": 0.3, "end": 2.5, "measured": True, "plan_start": 0.3, "plan_end": 2.5}]
    res = grid.caption_cells(ref, ours, 5.0, 5.0)
    assert [c["status"] for c in res["cells"]] == ["same"] * 5
    ours[1] = dict(ours[1], start=3.2, end=4.5, plan_start=3.2, plan_end=4.5)
    res = grid.caption_cells(ref, ours, 5.0, 5.0)
    assert grid._status(res["cells"]) == "different"
    ours[1] = dict(ours[1], measured=False)
    assert "unmeasured" in [c["status"] for c in grid.caption_cells(ref, ours, 5.0, 5.0)["cells"]]
    cuts = grid.cut_cells([{"t": 2.1, "type": "cut"}], [{"t": 2.4, "type": "cut"}], 4.0, 6.0)
    assert grid._status(cuts["cells"]) == "same" and cuts["past_shorter_video"] == 2
    assert grid._status(grid.cut_cells([{"t": 2.1, "type": "cut"}], [{"t": 3.4, "type": "cut"}], 4.0, 4.0)["cells"]) == "different"
    sfx = grid.sfx_cells([{"t": 1.2, "type": "whoosh"}], [[3.0, 4.0]], [{"t": 1.3, "type": "whoosh"}], 4.0, 4.0)
    assert [c["status"] for c in sfx["cells"]][2] == "same" and grid._status(sfx["cells"]) == "unmeasured"


def test_grid_rows_without_a_reference_are_required_unmeasured():
    from shortkit.qa import grid

    b = _builder(mode="production")
    b.ctx.reference_info = {"representative": {"reason": "formats.yaml 없음"}}
    grid.rows_reference_grid(b, {"text": {"status": "measured"}, "video": {}, "audio": {"status": "measured"}})
    rows = {r["row_id"]: r for r in b.rows}
    for rid in ("ref_grid.captions:grid", "ref_grid.cuts:grid", "ref_grid.sfx:grid"):
        assert rows[rid]["status"] == "unmeasured" and rows[rid]["required"] is True, rid


# ============================================================================ S2QA-03 / S2QA-16: stale or foreign report
def _report_for(root, ep, **over):
    from shortkit.qa.report import input_fingerprints
    from shortkit.util.hashing import sha256_file
    from shortkit.util.jsonio import write_json

    pr = config.load_preset("joshuamagazine")
    out = f"episodes/{ep}/output/{ep}.mp4"
    rep = {"episode_id": ep, "preset_name": "joshuamagazine", "format_id": "UNCLASSIFIED", "mode": "test",
           "rows": [_row("audio.sfx.no_event", "all", "same")],
           "output": {"path": out, "sha256": sha256_file(root / out)}, "reference": {},
           "inputs": input_fingerprints(ep, pr)}
    rep.update(over)
    write_json(root / "episodes" / ep / "qa" / "report.json", rep)
    return rep


def test_gate_checks_the_deliverable_not_the_file_the_report_names(temp_root):
    from shortkit.util.hashing import sha256_file

    _episode(temp_root, fmt="UNCLASSIFIED", mode="test")
    alt = temp_root / "episodes/e1/output/alt.mp4"
    _tiny_mp4(alt, color="red")
    _report_for(temp_root, "e1", output={"path": "episodes/e1/output/alt.mp4", "sha256": sha256_file(alt)})
    g = gate.gate_episode("e1")
    assert any(f["rule"] == "G5" and "납품" in f["message"] for f in g["failures"])
    # the report measured the deliverable, which was then replaced by another render
    _report_for(temp_root, "e1")
    assert not [f for f in gate.gate_episode("e1")["failures"] if f["rule"] in ("G5", "G6")]
    _tiny_mp4(temp_root / "episodes/e1/output/e1.mp4", color="green")
    assert any(f["rule"] == "G5" for f in gate.gate_episode("e1")["failures"])


def test_gate_refuses_rows_judged_against_changed_inputs(temp_root):
    from shortkit.util.jsonio import write_yaml

    _episode(temp_root, fmt="UNCLASSIFIED", mode="test")
    _report_for(temp_root, "e1")
    assert not [f for f in gate.gate_episode("e1")["failures"] if f["rule"] == "G6"]
    write_yaml(temp_root / P / "requested_changes.yaml", {"preset_id": "joshuamagazine-v1",
                                                          "changes": {"audio": {"loudness": {"integrated_lufs": -16.0}}}})
    g6 = [f for f in gate.gate_episode("e1")["failures"] if f["rule"] == "G6"]
    assert g6 and f"{P}/requested_changes.yaml" in g6[0]["rows"]
    # a report written before fingerprints existed is not trusted either
    _report_for(temp_root, "e1", inputs=None)
    assert any(f["rule"] == "G6" for f in gate.gate_episode("e1")["failures"])


# ============================================================================ S2QA-02: 'fixed' needs a fix and a re-check
def _drow(status, required=True, **kw):
    return dict(_row("caption.position", "s1", status, required=required), item="자막 위치", expected=1, observed=2,
                note="", **kw)


def _drep(*rows):
    return {"rows": list(rows), "gate": {"pass": False, "complete": False}, "output": {"sha256": "a"}}


def test_defect_is_not_fixed_without_a_recorded_fix(temp_root):
    from shortkit.qa import defects

    (temp_root / "episodes" / "e1" / "qa").mkdir(parents=True)
    ctx = SimpleNamespace(episode_id="e1")
    defects.sync(ctx, _drep(_drow("different")), recheck_others=False)
    st = defects.sync(ctx, _drep(_drow("same")), recheck_others=True)
    d = defects.load("e1")[0]
    assert d["status"] == "resolved_without_fix" and st["verified_now"] == 0 and st["needs_record"] == 1
    defects.add_fix("e1", d["id"], "SYNTHETIC: 자막 y 좌표를 계획대로 고침")
    defects.sync(ctx, _drep(_drow("same")), recheck_others=True)
    d = defects.load("e1")[0]
    assert d["status"] == "fixed" and d["recheck_same_cases"][-1]["verdict"] == "no_other_episodes"


def test_defect_of_a_row_now_unmeasured_stays_open(temp_root):
    from shortkit.qa import defects

    (temp_root / "episodes" / "e1" / "qa").mkdir(parents=True)
    ctx = SimpleNamespace(episode_id="e1")
    defects.sync(ctx, _drep(_drow("different")), recheck_others=False)
    st = defects.sync(ctx, _drep(_drow("unmeasured", required=False)), recheck_others=False)
    d = defects.load("e1")[0]
    assert d["status"] == "open" and st["unmeasured_now"] == 1 and d["history"][-1]["event"] == "unmeasured_now"


def test_legacy_fixed_records_without_a_fix_are_reclassified(temp_root):
    from shortkit.qa import defects
    from shortkit.util.jsonio import write_jsonl

    (temp_root / "episodes" / "e1" / "qa").mkdir(parents=True)
    write_jsonl(defects.path_for("e1"), [{"id": "D001", "check_id": "caption.position", "row_id": "caption.position:s1",
                                          "status": "fixed", "fix": None, "fix_notes": [], "recheck_same_cases": [],
                                          "history": [{"event": "found"}, {"event": "verified_fixed"}]}])
    st = defects.sync(SimpleNamespace(episode_id="e1"), _drep(_drow("same")), recheck_others=False)
    d = defects.load("e1")[0]
    assert st["reclassified"] == 1 and d["status"] == "resolved_without_fix"
    assert d["history"][-1]["event"] == "reclassified" and d["fix"] is None       # the real fix is not invented


# ============================================================================ font: exact-position re-render
def test_role_verdict_needs_the_exact_render_for_identical():
    from shortkit.qa.font_id import combine_role_verdict

    ident = {"c1": {"status": "measured", "verdict": "identical"}}
    assert combine_role_verdict({"verdict": "similar"}, ident)["verdict"] == "identical"      # single-caption role
    assert combine_role_verdict({"verdict": "identical"}, {})["verdict"] == "similar"          # pooled alone: 못 잼
    assert combine_role_verdict({"verdict": "different"}, ident)["verdict"] == "unmeasured"    # conflict
    diff = {"c1": {"status": "measured", "verdict": "different"}}
    assert combine_role_verdict({"verdict": "identical"}, diff)["verdict"] == "different"
    best = {"c1": {"status": "measured", "verdict": "best_not_reproduced"}}
    assert combine_role_verdict({"verdict": "identical"}, best)["verdict"] == "identical"
    assert combine_role_verdict({"verdict": "similar"}, best)["verdict"] == "similar"


def test_alternative_face_ass_switches_only_the_captions_text_events():
    from shortkit.edit import captions as capmod
    from shortkit.qa.font_id import alt_face_ass

    try:
        alt = capmod.resolve_font("Pretendard Black")
    except Exception:
        pytest.skip("Pretendard Black not installed here")
    ass = ("[Script Info]\nScriptType: v4.00+\n\n[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, "
           "SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, "
           "Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
           "Style: speaker,NotoSansCJKkr-Bold,57.92,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,-1,0,0,0,100,100,0,0,1,0,0,5,0,0,0,1\n\n"
           "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
           "Dialogue: 1,0:00:00.30,0:00:03.90,speaker,,0,0,0,,{\\an7\\pos(650,748)\\p3}m 0 0 l 712 0 712 196 0 196{\\p0}\n"
           "Dialogue: 2,0:00:00.30,0:00:03.90,speaker,,0,0,0,,{\\an5\\pos(740,770)\\fad(150,150)}창가 남성\n"
           "Dialogue: 2,0:00:05.00,0:00:06.00,speaker,,0,0,0,,{\\an5\\pos(740,770)}다른 자막\n")
    cap = SimpleNamespace(id="c_spk", start=0.3, end=3.9, lines=["창가 남성"], text="창가 남성", size_px=48.0)
    txt, counts = alt_face_ass(ass, [cap], 48.0, alt)
    assert counts == {"qaalt_speaker": 1}
    lines = txt.splitlines()
    assert any(ln.startswith("Style: qaalt_speaker," + alt.ass_name + ",") for ln in lines)
    ev = [ln for ln in lines if ln.startswith("Dialogue:")]
    assert ev[0].split(",")[3] == "speaker"                     # the box drawing keeps its style
    assert ev[1].split(",")[3] == "qaalt_speaker" and "\\pos(740,770)\\fad(150,150)" in ev[1]
    assert ev[2].split(",")[3] == "speaker"                     # another caption is untouched


@pytest.mark.slow
def test_exact_render_reproduces_the_title_and_tells_a_wrong_face(tmp_path, monkeypatch):
    """SYNTHETIC episode (tests/qa/qa_synth.py) rendered through libass/x264: the exact-position re-render of the
    title (over the flat canvas) in the planned face reproduces the MP4 within the re-encode noise and beats the
    alternatives by more than the noise; drawn in another face, the alternative wins ('different')."""
    import sys

    sys.path.insert(0, str(REAL_ROOT / "tests" / "qa"))
    import qa_synth
    from shortkit.edit.captions import resolve_font
    from shortkit.qa import load_context
    from shortkit.qa.font_id import exact_render_checks

    wrong = None
    for name in ("Pretendard Black", "Noto Sans CJK KR Bold"):
        try:
            resolve_font(name)
            wrong = name
            break
        except Exception:
            continue
    if wrong is None or not (REAL_ROOT / qa_synth.GEN / "video" / "head-pose-face-detection-female-and-male.mp4").is_file():
        pytest.skip("test media / a second face not available here")
    root = tmp_path / "proj"
    root.mkdir()
    shutil.copy(REAL_ROOT / "shortkit.root", root / "shortkit.root")
    shutil.copytree(REAL_ROOT / P, root / P,
                    ignore=shutil.ignore_patterns("videos", "frames", "stems", "*.wav", "*.mp4", "analysis"))
    (root / "assets" / "test").mkdir(parents=True)
    (root / "assets" / "test" / "generated").symlink_to(REAL_ROOT / "assets" / "test" / "generated")
    if (REAL_ROOT / "assets" / "fonts").is_dir():
        (root / "assets" / "fonts").symlink_to(REAL_ROOT / "assets" / "fonts")
    monkeypatch.setenv("SHORTKIT_ROOT", str(root))
    alts = [n for n in ("Pretendard Black", "Noto Sans CJK KR Bold", "Pretendard Bold")]

    qa_synth.render_episode("test-qa-exact", bad=False)
    ctx = load_context("test-qa-exact")
    t1 = [c for c in ctx.resolved.captions if c.id == "t1"]
    res = exact_render_checks(ctx, {"title": t1}, {"title": alts})
    e = res["captions"]["t1"]
    assert e["verdict"] == "identical", e
    assert e["mae_planned"] <= e["noise_mae"] < min(e["mae_alternatives"].values()) - e["mae_planned"]

    swap = {"t1": wrong}
    saved = [c["font"] for c in qa_synth.CAPTIONS]
    orig_build, orig_link = qa_synth.build_ass, qa_synth.link_fonts

    def swapped(fn):
        def w(*a, **kw):
            if kw.get("rest_only") or (len(a) > 1 and a[1]):
                return fn(*a, **kw)
            for c in qa_synth.CAPTIONS:
                c["font"] = swap.get(c["id"], c["font"])
            try:
                return fn(*a, **kw)
            finally:
                for c, f in zip(qa_synth.CAPTIONS, saved):
                    c["font"] = f
        return w
    monkeypatch.setattr(qa_synth, "build_ass", swapped(orig_build))
    monkeypatch.setattr(qa_synth, "link_fonts", swapped(orig_link))
    qa_synth.render_episode("test-qa-exact-wrong", bad=False)
    ctx = load_context("test-qa-exact-wrong")
    t1 = [c for c in ctx.resolved.captions if c.id == "t1"]
    assert t1[0].font_name != wrong
    # the ASS of this render names the wrong face; the check re-renders in the PLANNED face (never the face the ASS on
    # disk names), so the face really drawn -- an alternative -- reproduces the output better
    res = exact_render_checks(ctx, {"title": t1}, {"title": alts})
    e = res["captions"]["t1"]
    assert e["verdict"] == "different" and e["best_alternative"] == wrong, e
