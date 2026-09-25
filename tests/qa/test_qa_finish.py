"""Regression tests for the QA-side remainders of the plan-validation review (D-finish):

1. gate A1 = ``shortkit.edit.plan.approval_state_for`` + ``series_first_episode`` (hand-written approvals and later
   episodes without an approved, rendered first episode fail);
2. style-vs-reference rows compare every key they list, and ``declarations()`` equals what is compared;
3. caption.reveal / replayed source frames / cover_up.protected 'none' / cover_up.faces are required;
4. embedded music measured in the OUTPUT (music_presence on the kept windows), speech presence in kept and ducked
   ranges, the vocals-stem QC row, BGM vs reference stems, SFX types from the catalog fingerprints.

Every fixture is SYNTHETIC (hand-written plans / probe dicts / catalogs, numpy-generated tones and noise written to a
temporary project root).  No external platform is contacted, nothing here is a listening check.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

import numpy as np
import pytest
import yaml

from shortkit import config
from shortkit.qa import checks, gate

from .test_qa_review_d import P, _builder, _row, temp_root  # noqa: F401  (fixture re-exported)


# ============================================================================ 1. gate A1
def _prod_plan(ep: str, idx: int | None, **over) -> dict:
    """A schema-valid plan (the test-pipeline-001 plan: CC-BY test footage) switched to production with the given index."""
    from .test_qa_review_d import REAL_ROOT

    p = yaml.safe_load((REAL_ROOT / "episodes/test-pipeline-001/plan.yaml").read_text(encoding="utf-8"))
    p.pop("approval", None)
    p.update({"episode_id": ep, "mode": "production", "episode_index": idx,
              "title_candidates": ["SYNTHETIC 가", "SYNTHETIC 나", "SYNTHETIC 다"]}, **over)
    return p


def _write_plan(root, p: dict) -> None:
    d = root / "episodes" / p["episode_id"]
    d.mkdir(parents=True, exist_ok=True)
    (d / "plan.yaml").write_text(yaml.safe_dump(p, allow_unicode=True, sort_keys=False), encoding="utf-8")


def _a1(rows_plan: dict, pr) -> list[dict]:
    g = gate.evaluate([_row("audio.sfx.no_event", "all", "same")], mode=rows_plan["mode"], mp4_sha_measured="a",
                      mp4_sha_now="a", unmeasured_preset_keys=[], plan=rows_plan,
                      approval=gate.approval_facts(rows_plan, pr))
    return [f for f in g["failures"] if f["rule"] == "A1"]


def test_a1_refuses_a_handwritten_approval(temp_root):
    pr = config.load_preset("joshuamagazine")
    p = _prod_plan("e1", 1, approval={"approved": True, "approved_by": "someone"})
    _write_plan(temp_root, p)
    a1 = _a1(p, pr)
    assert a1 and "증거 없음" in a1[0]["message"]
    # the same plan approved through the evidence path (snapshot + approval log) passes A1
    from shortkit.edit import plan as plan_mod

    p = _prod_plan("e1", 1)
    _write_plan(temp_root, p)
    plan_mod.record_approval("e1", p, by="SYNTHETIC-approver",
                             proposal_text=f"plan_sha256: `{plan_mod.plan_sha256(p)}`\n")
    approved = yaml.safe_load((temp_root / "episodes/e1/plan.yaml").read_text())
    assert _a1(approved, pr) == []


def test_a1_later_episode_needs_an_approved_rendered_first_episode(temp_root):
    from shortkit.edit import plan as plan_mod

    pr = config.load_preset("joshuamagazine")
    p2 = _prod_plan("e2", 2)
    _write_plan(temp_root, p2)
    # approval of later episodes is not required by the preset rule -- but the series rule is
    a1 = _a1(p2, pr)
    assert a1 and "첫 편" in a1[0]["message"]
    p1 = _prod_plan("e1", 1)
    _write_plan(temp_root, p1)
    plan_mod.record_approval("e1", p1, by="SYNTHETIC-approver", proposal_text=f"plan_sha256: `{plan_mod.plan_sha256(p1)}`\n")
    assert _a1(p2, pr), "approved but never rendered: still A1"
    plan_mod.append_log("e1", {"event": "render", "plan_sha256": plan_mod.plan_sha256(p1), "output": "x.mp4"})
    assert _a1(p2, pr) == []


def test_a1_without_approval_facts_fails_in_production_only():
    ok = [_row("audio.sfx.no_event", "all", "same")]
    kw = dict(mp4_sha_measured="a", mp4_sha_now="a", unmeasured_preset_keys=[])
    g = gate.evaluate(ok, mode="production", plan={"episode_index": 1, "approval": {"approved": True}}, **kw)
    assert any(f["rule"] == "A1" for f in g["failures"])
    g = gate.evaluate(ok, mode="test", plan={"episode_index": 1}, **kw)
    assert not any(f["rule"] == "A1" for f in g["failures"] + g["warnings"])


def test_gate_episode_uses_the_plan_approval_functions(temp_root, monkeypatch):
    from shortkit.edit import plan as plan_mod

    calls = []
    real_state, real_series = plan_mod.approval_state_for, plan_mod.series_first_episode
    monkeypatch.setattr(plan_mod, "approval_state_for", lambda p, pr: calls.append("state") or real_state(p, pr))
    monkeypatch.setattr(plan_mod, "series_first_episode", lambda p: calls.append("series") or real_series(p))
    pr = config.load_preset("joshuamagazine")
    f = gate.approval_facts(_prod_plan("e3", 3), pr)
    assert calls == ["state", "series"] and f["series"]["ok"] is False


# ============================================================================ 2. style rows compare every listed key
EPISODES_WITH_PROBES = ["test-pipeline-001", "test-coverage-001", "test-qa-good", "test-qa-bad"]
ROW_ONLY = ["canvas.", "caption.", "video.", "decor.", "audio.", "structure.", "cover.", "presence"]


def _rows_from_saved_probes(ep: str, monkeypatch) -> tuple[list[dict], list[tuple]]:
    """Rows rebuilt from the probes a real QA run saved (episodes/<ep>/qa/probes), with every preset key treated as
    measured (so every style row runs its compare); returns (rows, [(verdict, unread keys, observed)])."""
    from shortkit.qa import load_context
    from shortkit.util.jsonio import read_json

    from .test_qa_review_d import REAL_ROOT

    pdir = REAL_ROOT / "episodes" / ep / "qa" / "probes"
    if not (pdir / "text.json").is_file():
        pytest.skip(f"{ep}: saved probes missing (run `shortkit qa run --episode {ep}`)")
    orig = checks.RowBuilder.reference_of
    monkeypatch.setattr(checks.RowBuilder, "reference_of",
                        lambda self, keys: (({k: "SYNTHETIC-measured" for k in keys} if keys else None), [],
                                            orig(self, keys)[2]))
    calls = []

    def spy(self, compare, observed, keys):
        r = checks._KeyReads({k: self.pget(k) for k in keys})
        ok = compare(observed, r)
        calls.append((ok, [k for k in keys if k not in r.read], observed))
        return ok, [k for k in keys if k not in r.read] if ok is True else []
    monkeypatch.setattr(checks.RowBuilder, "_compare", spy)
    ctx = load_context(ep)
    probes = {k: read_json(pdir / f"{k}.json") for k in ("text", "video", "audio")}
    return checks.build_rows(ctx, probes, ROW_ONLY), calls


@pytest.mark.parametrize("ep", EPISODES_WITH_PROBES)
def test_every_style_compare_reads_every_key_it_lists(ep, monkeypatch):
    rows, calls = _rows_from_saved_probes(ep, monkeypatch)
    assert calls, "no style row ran its compare"
    unread = [(ok, u, str(o)[:120]) for ok, u, o in calls if u]
    assert not unread, unread                      # whatever the verdict (same / different / 못 잼)
    assert not [r["row_id"] for r in rows if r.get("keys_not_compared")]
    assert not [r["row_id"] for r in rows if r["check_id"].endswith("error") or r["category"] == "검사 오류"]
    # every key a row carries is declared for its check (the registry's qa_checks = what the rows compare)
    decl = checks.declarations()
    undeclared = sorted({(r["check_id"], k) for r in rows for k in r["keys"] if k not in decl.get(r["check_id"], [])})
    assert not undeclared, undeclared


def test_keys_a_compare_ignores_are_dropped_from_the_row(temp_root):
    b = _builder()
    keys = ["motion.zoom.scale_to", "motion.zoom.dur_s"]
    monkey = {k: "SYNTHETIC-measured" for k in keys}
    b.reference_of = lambda ks: ({k: monkey[k] for k in ks} if ks else None, [], [])
    row = b.style_row("video.zoom", "zoom_ref", "줌", checks.CAT["motion"], keys, {"final_ratio": 1.2},
                      lambda o, r: abs(o["final_ratio"] - float(r["motion.zoom.scale_to"])) <= 0.5)
    assert row["status"] == "same" and row["keys"] == ["motion.zoom.scale_to"]
    assert row["keys_not_compared"] == ["motion.zoom.dur_s"] and "읽지 않은 키" in row["note"]


def _all_measured(b):
    b.reference_of = lambda ks: ({k: "SYNTHETIC-measured" for k in ks} if ks else None, [], [])
    return b


def test_transition_reference_row_compares_durations_and_colour_even_when_the_type_differs(temp_root):
    b = _all_measured(_builder())
    seen = []
    real = b._compare

    def spy(compare, observed, keys):
        r = checks._KeyReads({k: b.pget(k) for k in keys})
        ok = compare(observed, r)
        seen.append((ok, set(r.read)))
        return real(compare, observed, keys)
    b._compare = spy
    fl = b.pget("motion.transitions.flash.dur_s")
    video = {"transitions": {"boundaries": [
        {"clip_id": "c2", "expected": {"type": "crossfade", "t": 2.0, "dur": 0.3}, "type_ok": True, "timing_ok": True,
         "observed": {"type": "crossfade", "t": 2.0, "dur": 0.3}},
        {"clip_id": "c3", "expected": {"type": "flash", "t": 4.0, "dur": fl, "color": "#FFFFFF"}, "type_ok": True,
         "timing_ok": True, "observed": {"type": "flash", "t": 4.0, "dur": fl, "color": "#FEFEFE"}}], "unexpected": []}}
    b.ctx.resolved.clips = []
    checks.rows_video(b, {"video": video})
    row = next(r for r in b.rows if r["row_id"] == "video.transitions:transitions_ref")
    assert set(row["keys"]) == {"motion.transitions.default", "motion.transitions.flash.dur_s",
                                "motion.transitions.flash.color", "motion.transitions.crossfade.dur_s"}
    ok, read = seen[-1]
    assert read == set(row["keys"])            # read although the modal type may already differ


def test_decoration_without_blinking_is_compared_by_its_lit_fraction(temp_root):
    from shortkit.util.jsonio import read_yaml, write_yaml

    y = read_yaml(temp_root / P / "preset.yaml")
    y["decorations"]["circle"]["blink_hz"] = 0
    write_yaml(temp_root / P / "preset.yaml", y)
    b = _all_measured(_builder())
    d = SimpleNamespace(id="d1", kind="circle", style={"color": b.pget("decorations.circle.color"), "stroke_px": 10},
                        blink_hz=0.0, keyframes=[{"t": 1.0, "x": 100, "y": 100, "w": 50}], start=1.0, end=3.0)
    b.ctx.resolved.decorations = [d]
    item = {"id": "d1", "status": "measured", "color_obs": b.pget("decorations.circle.color"), "stroke_px_obs": 10.0,
            "position": {"abs_err_p50": 1, "abs_err_p90": 2, "path_err_p90": 1, "track": [[1.0, 100, 100]]},
            "brightness": {"blink_hz_obs": None, "on_fraction": 0.98, "curve": []}}
    checks.rows_decorations(b, {"video": {"decorations": {"items": [item]}}})
    row = next(r for r in b.rows if r["row_id"] == "decor.style:d1_ref")
    assert row["status"] == "same" and "decorations.circle.blink_hz" in row["keys"]
    b = _all_measured(_builder())
    b.ctx.resolved.decorations = [d]
    item["brightness"] = {"blink_hz_obs": 2.0, "on_fraction": 0.5, "curve": []}
    checks.rows_decorations(b, {"video": {"decorations": {"items": [item]}}})
    assert next(r for r in b.rows if r["row_id"] == "decor.style:d1_ref")["status"] == "different"


def test_font_reference_row_compares_the_bold_key(temp_root, monkeypatch):
    from shortkit.reference import typography

    monkeypatch.setattr(typography, "face_weight", lambda name: (900 if "Black" in name else 400, None))
    obs = checks._font_obs("Noto Sans CJK KR Black")
    assert obs == {"best": "Noto Sans CJK KR Black", "weight_class": 900, "bold": True}
    assert checks._font_obs("Noto Sans CJK KR Regular")["bold"] is False


def test_timing_reference_row_reads_persist_with_the_analyzer_definition(temp_root):
    import json

    from shortkit.edit.ir import ResolvedEdit

    from .test_qa_review_d import REAL_ROOT

    res = ResolvedEdit.from_dict(json.loads((REAL_ROOT / "episodes/test-qa-good/build/resolved.json").read_text()))
    title = next(c for c in res.captions if c.role == "title")          # SYNTHETIC render: 0.0-7.8 s of 7.8 s

    def run(offset):
        b = _all_measured(_builder())
        b.ctx.resolved.captions = [title]
        b.ctx.info.duration = 7.8
        tp = {"status": "measured", "captions": [{"id": title.id, "found": True, "bbox_obs": [100, 100, 500, 60],
                                                  "onset": 0.0, "offset": offset, "similarity": 1.0}]}
        checks.rows_captions(b, {"text": tp})
        return next(r for r in b.rows if r["row_id"] == "caption.timing:title_ref")
    row = run(7.6)
    assert row["observed"]["persist"] == "whole_video"          # >= 90 % of the video, as reference.textboxes says
    assert "text.roles.title.persist" in row["keys"]
    want = _builder().pget("text.roles.title.persist")
    assert row["status"] == ("same" if want == "whole_video" else "different")
    row = run(3.0)                                              # shown 3 s of 7.8 s: timed
    assert row["observed"]["persist"] == "timed"
    assert row["status"] == ("different" if want == "whole_video" else row["status"])


def test_dialogue_lead_is_not_declared_or_carried():
    decl = checks.declarations()
    assert not [k for ks in decl.values() for k in ks if k.endswith("timing.lead_s")]


# ============================================================================ 3. reveal / replay / cover-up
def _watch(row_id, verdict="same"):
    return {"row_id": row_id, "kind": "watch", "verdict": verdict, "by": "SYNTHETIC-tester", "at": "2026-09-25",
            "note": "SYNTHETIC record", "mp4_sha256": "abc"}


def _reveal_row(plan, human=None):
    b = _builder(plan=plan)
    b.ctx.options.update(human_checks=human or [], mp4_sha256="abc")
    checks.rows_captions(b, {"text": {"status": "measured", "captions": []}})
    return next(r for r in b.rows if r["check_id"] == "caption.reveal")


def test_reveal_row_is_required_and_unmeasured_without_a_protected_reveal(temp_root):
    r = _reveal_row({})
    assert r["status"] == "unmeasured" and r["required"] is True and "reveal" in r["note"]
    r = _reveal_row({"reveal": {"none": True, "reason": "SYNTHETIC: 단순 동작 영상"}})
    assert r["status"] == "unmeasured" and r["required"] is True and "출력에서 잰 것이 아님" in r["note"]
    # a person who watched THIS mp4 decides; a record on another mp4 does not count
    assert _reveal_row({}, [_watch("caption.reveal:reveal")])["status"] == "same"
    assert _reveal_row({}, [dict(_watch("caption.reveal:reveal"), mp4_sha256="zzz")])["status"] == "unmeasured"
    # OCR failed: still a required reveal row
    b = _builder(plan={"reveal": {"t": 3.0, "keywords": ["x"]}})
    checks.rows_captions(b, {"text": {"status": "unmeasured", "reason": "SYNTHETIC: no tesseract"}})
    r = next(x for x in b.rows if x["check_id"] == "caption.reveal")
    assert r["status"] == "unmeasured" and r["required"] is True


def _replay_rows(mapping_clips, timeline):
    b = _builder(plan={"timeline": timeline})
    b.ctx.resolved.clips = [SimpleNamespace(id=t["id"], source_path="src.mp4", src_in=t["src_in"], src_out=t["src_out"],
                                            out_start=float(i) * 3.0) for i, t in enumerate(timeline)]
    checks._rows_replay(b, {"clips": mapping_clips}, {})
    return b.rows[0]


def test_replayed_source_frames_need_a_replay_mark():
    tl = [{"id": "a", "src_in": 1.0, "src_out": 4.0}, {"id": "b", "src_in": 3.0, "src_out": 5.0}]
    mp = [{"clip_id": "a", "status": "measured", "expected_src": [1.0, 4.0], "offset_p50": 0.01},
          {"clip_id": "b", "status": "measured", "expected_src": [3.0, 5.0], "offset_p50": -0.02}]
    r = _replay_rows(mp, tl)
    assert r["status"] == "different" and r["required"] is True and r["observed"]["repeats"][0]["again"] == "b"
    tl[1] = dict(tl[1], replay_of="a", replay_reason="SYNTHETIC: 결정적 순간 다시보기")
    r = _replay_rows(mp, tl)
    assert r["status"] == "same" and r["observed"]["repeats"][0]["marked_replay"] is True
    # planned apart but the output shows the same frames (measured offset): still a repeat
    tl = [{"id": "a", "src_in": 1.0, "src_out": 4.0}, {"id": "b", "src_in": 4.1, "src_out": 6.0}]
    mp = [dict(mp[0]), {"clip_id": "b", "status": "measured", "expected_src": [4.1, 6.0], "offset_p50": -0.6}]
    assert _replay_rows(mp, tl)["status"] == "different"
    # a clip whose source span was not measured: 못 잼
    mp = [dict(mp[0]), {"clip_id": "b", "status": "unmeasured", "expected_src": [4.1, 6.0]}]
    assert _replay_rows(mp, tl)["status"] == "unmeasured"
    # far apart and both measured: same
    tl = [{"id": "a", "src_in": 1.0, "src_out": 4.0}, {"id": "b", "src_in": 8.0, "src_out": 9.0}]
    mp = [dict(mp[0]), {"clip_id": "b", "status": "measured", "expected_src": [8.0, 9.0], "offset_p50": 0.0}]
    assert _replay_rows(mp, tl)["status"] == "same"


def _cover_rows(plan, protected=None, human=None):
    b = _builder(plan=plan)
    b.ctx.options.update(human_checks=human or [], mp4_sha256="abc", faces=False)
    checks.rows_cover_up(b, {"text": {"captions": []}, "video": {"protected": protected}})
    return {r["row_id"]: r for r in b.rows}


def test_no_protected_region_is_required_and_the_face_row_is_always_required(temp_root):
    tl = [{"id": "s1", "source": "v"}]
    rows = _cover_rows({"timeline": tl, "sources": [{"id": "v"}]})
    none = rows["cover_up.protected:none"]
    assert none["status"] == "unmeasured" and none["required"] is True
    faces = rows["cover_up.faces:detector"]
    assert faces["status"] == "unmeasured" and faces["required"] is True
    # a 'nothing to protect' review is a statement, not a measurement
    rev = {"by": "SYNTHETIC", "at": "2026-09-25", "note": "사람 없음"}
    rows = _cover_rows({"timeline": tl, "sources": [{"id": "v", "protected_reviewed": rev}]})
    assert rows["cover_up.protected:none"]["status"] == "unmeasured" and rows["cover_up.protected:none"]["required"]
    rows = _cover_rows({"timeline": tl, "sources": [{"id": "v", "protected_reviewed": rev}]},
                       human=[_watch("cover_up.protected:none")])
    assert rows["cover_up.protected:none"]["status"] == "same"
    # declared protected regions measured: the face row stays required (the detector is the output's own evidence)
    prot = [{"clip_id": "s1", "label": "face", "rect": [10, 10, 50, 50], "start": 0.0, "end": 2.0, "visible_frac": 1.0}]
    rows = _cover_rows({"timeline": tl, "sources": [{"id": "v"}]}, protected=prot)
    assert rows["cover_up.protected:s1#0"]["status"] == "same"
    assert rows["cover_up.faces:detector"]["required"] is True and rows["cover_up.faces:detector"]["status"] == "unmeasured"
    g = gate.evaluate(list(rows.values()), mode="test", mp4_sha_measured="a", mp4_sha_now="a", unmeasured_preset_keys=[])
    assert any(f["rule"] == "G2" and "cover_up.faces:detector" in f["rows"] for f in g["failures"])


# ============================================================================ 4. audio measured in the output
GEN = "assets/test/generated"          # espeak-ng TTS lines + synthetic chord beds + synthetic SFX (shortkit-generated)


def _mono(rel, sr=22050):
    from shortkit.util.media import read_audio

    from .test_qa_review_d import REAL_ROOT

    return read_audio(REAL_ROOT / rel, sr=sr, mono=True).astype(np.float32)


def _kept(o_start=1.0, o_end=None, n=None):
    return SimpleNamespace(clip_id="c1", out_start=o_start, out_end=o_end, fade_s=0.04, stem="raw", path="x.wav",
                           src_start=0.0, speed=1.0, speech=[], speech_status="unmeasured", gain_db=0.0)


def test_kept_voice_music_and_speech_are_measured_on_the_output_residual():
    """SYNTHETIC: TTS line alone -> speech, no music; TTS + chord bed left in -> music present."""
    from shortkit.qa.probes_audio import kept_audio_checks

    sr = 22050
    sp = _mono(f"{GEN}/speech_02.wav", sr)
    bed = _mono(f"{GEN}/music_bed_a.wav", sr)[: len(sp)]
    x = np.zeros(int(sr * 1.0) + len(sp) + sr, np.float32)
    x[sr: sr + len(sp)] = sp
    o = _kept(1.0, 1.0 + len(sp) / sr)
    ctx = SimpleNamespace(resolved=SimpleNamespace(audio=SimpleNamespace(bgm=None, originals=[o])))
    res = kept_audio_checks(ctx, x, sr, bgm_found=True)
    assert res["music"][0]["status"] == "absent"
    assert res["speech"]["status"] == "measured" and res["speech"]["spans"]
    y = x.copy()
    y[sr: sr + len(bed)] += 0.5 * bed * (np.abs(sp).max() / max(1e-9, np.abs(bed).max()))
    assert kept_audio_checks(ctx, y, sr, bgm_found=True)["music"][0]["status"] == "present"
    # the planned BGM not found in the mix: it cannot be removed -> 못 잼, never judged on the mix
    ctx.resolved.audio.bgm = SimpleNamespace(path="bgm.wav")
    r = kept_audio_checks(ctx, y, sr, bgm_found=False)
    assert r["music"][0]["status"] == "unmeasured" and r["speech"]["status"] == "unmeasured"


def _voice_rows(music_status, speech_spans, hem=None, stem="raw", human=None, mode="test", src_extra=None):
    o = _kept(2.0, 4.0)
    o.stem = stem
    if stem == "vocals":
        o.path = (src_extra or {}).get("vocals_path") or o.path
    o.speech = [[0.2, 1.8]]
    o.speech_status = "measured"
    b = _builder(mode=mode, plan={"sources": [{"id": "s1", "has_embedded_music": hem, **(src_extra or {})}]})
    b.ctx.resolved.clips = [SimpleNamespace(id="c1", source_id="s1")]
    b.ctx.resolved.audio.originals = [o]
    b.ctx.options.update(human_checks=human or [], mp4_sha256="abc")
    ap = {"originals": {"voice_out": {
        "music": [{"index": 0, "status": music_status, "polyphonic_share": 0.5 if music_status == "present" else 0.0,
                   "range_out": [2.04, 3.96], "reason": "SYNTHETIC 애매함" if music_status == "unmeasured" else None}],
        "speech": {"status": "measured" if speech_spans is not None else "unmeasured", "spans": speech_spans or [],
                   "reason": None if speech_spans is not None else "SYNTHETIC"}}}}
    checks._rows_kept_voice(b, ap)
    return {r["row_id"]: r for r in b.rows}


def test_embedded_music_row_is_the_output_measurement_not_the_plan_flag(temp_root):
    rows = _voice_rows("absent", [[2.1, 3.9]], hem=False)
    m = rows["audio.original:music0"]
    assert m["status"] == "same" and m["required"] is True and m["observed"]["basis"] == "출력 측정"
    assert "사람 청취 확인 아님" in m["note"]
    # has_embedded_music: false does not make it 'same' when the output has music
    assert _voice_rows("present", [[2.1, 3.9]], hem=False)["audio.original:music0"]["status"] == "different"
    # the plan says music is embedded and the raw sound was kept: different even if the detector heard none
    assert _voice_rows("absent", [[2.1, 3.9]], hem=True)["audio.original:music0"]["status"] == "different"
    # ambiguous detector: 못 잼 unless a person listened to THIS mp4
    assert _voice_rows("unmeasured", [[2.1, 3.9]], hem=False)["audio.original:music0"]["status"] == "unmeasured"
    rec = {"row_id": "audio.original:music0", "kind": "listen", "verdict": "same", "by": "SYNTHETIC-tester",
           "at": "2026-09-25", "note": "SYNTHETIC", "mp4_sha256": "abc"}
    r = _voice_rows("unmeasured", [[2.1, 3.9]], hem=False, human=[rec])["audio.original:music0"]
    assert r["status"] == "same" and r["observed"]["basis"] == "사람 청취 기록"


def test_kept_range_must_be_speech_in_the_output(temp_root):
    r = _voice_rows("absent", [[2.1, 3.9]])["audio.original:speech0"]
    assert r["status"] == "same" and r["observed"]["planned_speech_covered"] == pytest.approx(1.0)
    r = _voice_rows("absent", [[2.0, 2.5]])["audio.original:speech0"]
    assert r["status"] == "different"                                     # 25 % of the kept range
    assert _voice_rows("absent", None)["audio.original:speech0"]["status"] == "unmeasured"


def test_vocals_stem_quality_record_row(temp_root):
    import json as _json

    d = temp_root / "warehouse" / "stems" / "s1"
    d.mkdir(parents=True)
    (d / "vocals.wav").write_bytes(b"RIFF")
    vp = "warehouse/stems/s1/vocals.wav"
    src = {"vocals_path": vp, "sha256": "a" * 64}
    rows = _voice_rows("absent", [[2.1, 3.9]], hem=True, stem="vocals", src_extra=src)
    q = rows["audio.original:vocals_qc0"]
    assert q["status"] == "unmeasured" and q["required"] is True and "품질 기록 없음" in q["note"]
    rec = {"status": "measured", "source_sha256": "a" * 64, "vocals": vp, "usable": True,
           "quality": {"passed": True, "fail_reasons": []}}
    (d / "quality.json").write_text(_json.dumps(rec))
    rows = _voice_rows("absent", [[2.1, 3.9]], hem=True, stem="vocals", src_extra=src)
    o = rows["audio.original:vocals_qc0"]
    assert o["status"] == "same" and o["observed"]["quality"]["passed"] is True and "사람 청취가 아님" in o["note"]
    (d / "quality.json").write_text(_json.dumps(dict(rec, usable=False, quality={"passed": False, "fail_reasons": ["음악 잔류"]})))
    assert _voice_rows("absent", [[2.1, 3.9]], hem=True, stem="vocals", src_extra=src)["audio.original:vocals_qc0"][
        "status"] == "different"


def test_ducking_only_under_speech_measured_in_the_output(temp_root):
    b = _builder()
    b.ctx.resolved.audio.bgm = SimpleNamespace(duck_ranges=[[2.0, 4.0]], silences=[], fade_in_s=0.0, fade_out_s=0.0)
    b.ctx.resolved.clips = []
    ap = {"originals": {"voice_out": {"speech": {"status": "measured", "spans": [[2.1, 3.9]]}}}}
    checks._duck_speech_row(b, ap, [(2.0, 4.1)], [], [(0.0, 0.2), (9.8, 11.0)], 0.08, 0.3)
    assert b.rows[-1]["status"] == "same"
    checks._duck_speech_row(b, ap, [(2.0, 4.1), (6.0, 7.5)], [], [(0.0, 0.2), (9.8, 11.0)], 0.08, 0.3)
    r = b.rows[-1]
    assert r["status"] == "different" and r["required"] is True and "6.0" in r["note"]
    checks._duck_speech_row(b, {"originals": {}}, [(2.0, 4.1)], [], [], 0.08, 0.3)
    assert b.rows[-1]["status"] == "unmeasured"


def _write_wav(path, x, sr=22050):
    from scipy.io import wavfile

    path.parent.mkdir(parents=True, exist_ok=True)
    wavfile.write(str(path), sr, np.asarray(x, np.float32))


def test_bgm_clean_file_row_fingerprints_reference_stems(temp_root):
    sr = 8000
    rng = np.random.default_rng(7)
    music = (0.3 * np.sin(2 * np.pi * 220 * np.arange(sr * 4) / sr) + 0.05 * rng.standard_normal(sr * 4)).astype(np.float32)
    _write_wav(temp_root / "assets/library/music/SYNTH_bed.wav", music, sr)
    bgm = SimpleNamespace(path="assets/library/music/SYNTH_bed.wav")
    b = _builder(mode="production")
    checks._bgm_clean_file_row(b, bgm, True)
    r = b.rows[-1]
    assert r["status"] == "unmeasured" and r["required"] is True               # no reference stem to compare with
    other = (0.3 * np.sin(2 * np.pi * 330 * np.arange(sr * 4) / sr) + 0.05 * rng.standard_normal(sr * 4)).astype(np.float32)
    _write_wav(temp_root / P / "analysis/SYNTHvid0001/stems/other.wav", other, sr)
    b = _builder(mode="production")
    checks._bgm_clean_file_row(b, bgm, True)
    assert b.rows[-1]["status"] == "same" and b.rows[-1]["observed"]["reference_stems_compared"] == 1
    _write_wav(temp_root / P / "analysis/SYNTHvid0001/stems/other.wav", 0.5 * music, sr)     # a gain-changed copy
    b = _builder(mode="production")
    checks._bgm_clean_file_row(b, bgm, True)
    assert b.rows[-1]["status"] == "different" and b.rows[-1]["observed"]["stem_match"]


def _catalog_with_centroids(root, types: dict[str, str]):
    """SYNTHETIC measured catalog whose centroids are the fingerprints of the given generated SFX files."""
    from shortkit.edit.validate import sfx_file_similarity  # noqa: F401  (same fingerprint path as classification)
    from shortkit.reference.separation import load_mono
    from shortkit.reference.sfx_events import SR as FP_SR, fingerprint_clip
    from shortkit.reference.sfx_map import onset_of
    from shortkit.util.jsonio import write_json

    from .test_qa_review_d import REAL_ROOT

    fp_dir = root / P / "sfx_fp"
    fp_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for tid, rel in types.items():
        x = load_mono(REAL_ROOT / rel, FP_SR)
        np.save(fp_dir / f"{tid}.npy", fingerprint_clip(x, FP_SR, onset_of(x))["patch"])
        out.append({"type_id": tid, "class": "edit_sfx", "fingerprint": {"centroid": f"{P}/sfx_fp/{tid}.npy"},
                    "per_video_count": {"overall": {"n": 5, "p10": 0.0, "p50": 1.0, "p90": 2.0},
                                        "videos": {"v1": 0, "v2": 1, "v3": 1, "v4": 2, "v5": 2}}})
    write_json(root / P / "sfx_catalog.json", {"schema": "shortkit.sfx_catalog/1", "preset_id": "joshuamagazine-v1",
                                               "status": "measured", "basis": {"videos": ["v1", "v2", "v3", "v4", "v5"]},
                                               "types": out})


def test_detected_sfx_are_typed_by_the_catalog_fingerprint_not_the_plan_label(temp_root):
    import shutil as _sh

    from shortkit.qa.probes_audio import classify_sfx_detections

    from .test_qa_review_d import REAL_ROOT

    for f in ("whoosh", "ding", "boom"):
        (temp_root / GEN / "sfx").mkdir(parents=True, exist_ok=True)
        _sh.copy(REAL_ROOT / GEN / "sfx" / f"{f}.wav", temp_root / GEN / "sfx" / f"{f}.wav")
    _catalog_with_centroids(temp_root, {"cat_whoosh": f"{GEN}/sfx/whoosh.wav", "cat_ding": f"{GEN}/sfx/ding.wav"})
    ctx = SimpleNamespace(preset=config.load_preset("joshuamagazine"))
    # the plan labelled the whoosh file 'ding' (and a boom that is in no catalog type)
    dets = [{"t": 1.0, "type": "ding", "file": f"{GEN}/sfx/whoosh.wav"},
            {"t": 3.0, "type": "ding", "file": f"{GEN}/sfx/ding.wav"},
            {"t": 5.0, "type": "boom", "file": f"{GEN}/sfx/boom.wav"}]
    summ = classify_sfx_detections(ctx, dets)
    assert summ["status"] == "measured"
    assert dets[0]["catalog_type"]["type_id"] == "cat_whoosh" and dets[1]["catalog_type"]["type_id"] == "cat_ding"
    assert dets[2]["catalog_type"]["status"] == "measured" and dets[2]["catalog_type"]["type_id"] is None
    # per-SFX type rows: the plan label vs the sound
    b = _builder()
    placed = [(SimpleNamespace(id="fx1", type="cat_ding"), dets[0]), (SimpleNamespace(id="fx2", type="cat_ding"), dets[1])]
    checks._sfx_type_rows(b, placed)
    rows = {r["row_id"]: r for r in b.rows}
    assert rows["audio.sfx.type:fx1"]["status"] == "different" and rows["audio.sfx.type:fx2"]["status"] == "same"
    # catalog counts: by the fingerprint type; the boom is a sound outside the catalog
    cnt = checks.catalog_counts(dets)
    assert cnt == {"cat_whoosh": 1, "cat_ding": 1, checks.UNCLASSIFIED: 1}
    b = _builder()
    checks._rows_sfx_catalog(b, {"bgm": {}}, cnt)
    rows = {r["row_id"]: r for r in b.rows}
    assert rows["audio.sfx.count:catalog:unknown"]["status"] == "different"
    assert rows["audio.sfx.count:catalog:cat_whoosh"]["status"] == "same"
    # the same-time grid compares catalog types; an unclassified detection makes its cell 못 잼
    from shortkit.qa import grid

    ours = grid.our_sfx({"status": "measured", "sfx": {"detections": [dict(dets[0]), {"t": 2.2, "type": "x",
                                                                                     "catalog_type": {"status": "unmeasured"}}]},
                         "bgm": {}})
    assert ours[0]["type"] == "cat_whoosh" and ours[1]["type"] is None
    cells = grid.sfx_cells([{"t": 1.1, "type": "cat_whoosh"}], [], ours, 3.0, 3.0)["cells"]
    assert cells[2]["status"] == "same" and cells[4]["status"] == "unmeasured"


def test_new_audio_rows_are_declared():
    decl = checks.declarations()
    assert decl["audio.sfx.type"] == ["audio.sfx.catalog"] and "video.replay" in decl
    assert "audio.ducking.only_under_kept_dialogue" in decl["audio.ducking"]


def test_fitted_part_rebuilds_the_chosen_columns():
    from shortkit.qa.probes_audio import fitted_part, window_ls

    rng = np.random.default_rng(3)
    sr, n = 8000, 8000 * 2
    a, b = rng.standard_normal(n).astype(np.float32), rng.standard_normal(n).astype(np.float32)
    y = (0.5 * a + 0.2 * b).astype(np.float32)
    _, G, _ = window_ls(y, [a, b], sr, 0.05)
    assert np.allclose(fitted_part([a, b], G, [0], n, sr, 0.05), 0.5 * a, atol=1e-4)
    assert np.allclose(y - fitted_part([a, b], G, [1], n, sr, 0.05), 0.5 * a, atol=1e-4)
