"""Cross-module remainders of the review (E2-edit-qa), `episode validate` side.  Everything here is SYNTHETIC
(generated signals / hand-written catalogs and format tables in a temp project root) -- no reference measurement.

1. BGM guard: a CLEAN library song of which a reference stem is an excerpt (constant gain, fades, a leaked SFX) is
   not a stem copy -- validate uses the library's rule (``reference.audio_bgm.reference_audio_copy``).
2. SFX catalog status 'partial' (every video counted, a per-type column unmeasured): the count rule runs; a
   'partial' column is not a rule; production stays blocked.
3. First caption: the reference analyzer's definition (title / description left out).
4. plan.intro_type vs formats.yaml intro_variants of the plan's format.
5. Cut density / median shot length vs structure.cuts_per_10s / structure.shot_len_s.
"""
from __future__ import annotations

import copy
import json

import numpy as np
import pytest
import yaml

from e2_synth import SR, stem_of, synth_song  # noqa: F401  (bare helper module of this test dir)

from .conftest import codes, load_preset, set_preset
from .test_validate import run

P = "presets/joshuamagazine"


def _prod(plan):
    p = copy.deepcopy(plan)
    p["mode"] = "production"
    return p


# ============================================================================ 1. BGM vs reference stems
def _old_whole_file_ncc(a: np.ndarray, b: np.ndarray) -> float:
    """The REMOVED validate rule (max gain-invariant NCC of the stem slid over the file, >= 0.95 = copy)."""
    n = len(b)
    b = b - b.mean()
    m = 1 << int(np.ceil(np.log2(len(a) + n)))
    corr = np.fft.irfft(np.fft.rfft(a, m) * np.conj(np.fft.rfft(b, m)), m)[: len(a) - n + 1]
    c1 = np.concatenate([[0.0], np.cumsum(a)])
    c2 = np.concatenate([[0.0], np.cumsum(a * a)])
    s1, s2 = c1[n:] - c1[:-n], c2[n:] - c2[:-n]
    return float(np.max(corr / (np.sqrt(np.maximum(s2 - s1 * s1 / n, 1e-12)) * np.linalg.norm(b))))


@pytest.fixture
def stem_setup(root):
    from shortkit.util.media import write_wav

    song = synth_song(40.0)
    stem = stem_of(song)
    lib = root / "assets/library/music"
    lib.mkdir(parents=True, exist_ok=True)
    write_wav(lib / "song.wav", song, SR)
    write_wav(lib / "stem_copy.wav", (0.5 * stem[int(3 * SR):int(15 * SR)]).astype(np.float32), SR)  # trimmed, -6 dB
    sdir = root / P / "analysis" / "SYNTHstemv1" / "stems"
    sdir.mkdir(parents=True, exist_ok=True)
    write_wav(sdir / "other.wav", stem, SR)
    return song, stem


def test_clean_song_whose_excerpt_is_a_stem_is_not_refused(root, plan, stem_setup):
    from shortkit.edit.audio_checks import reference_stem_match
    from shortkit.reference.audio_bgm import reference_audio_copy
    from shortkit.reference.separation import load_mono

    # the case the old rule refused: whole-file correlation of the stem inside the clean song >= 0.95
    a = load_mono(root / "assets/library/music/song.wav", 8000).astype(np.float64)
    b = load_mono(root / P / "analysis/SYNTHstemv1/stems/other.wav", 8000).astype(np.float64)
    assert _old_whole_file_ncc(a, b) >= 0.95
    # one rule: validate == the library guard
    assert reference_stem_match("assets/library/music/song.wav") is None
    assert reference_audio_copy(root / "assets/library/music/song.wav") is None
    plan["bgm"] = {"enabled": True, "path": "assets/library/music/song.wav", "silences": []}
    assert "bgm_from_reference" not in codes(run(root, plan))
    # a real stem copy (trimmed, gain-changed, re-written) is still refused, by validate and by the library
    m = reference_stem_match("assets/library/music/stem_copy.wav")
    assert m and m["stem"] == f"{P}/analysis/SYNTHstemv1/stems/other.wav" and m["method"] == "waveform"
    assert reference_audio_copy(root / "assets/library/music/stem_copy.wav")["matched"] == m["stem"]
    plan["bgm"]["path"] = "assets/library/music/stem_copy.wav"
    iss = run(root, plan)
    assert "bgm_from_reference" in codes(iss, "error")
    # a byte copy of a stem whose FILE is gone is still caught through the separation record's sha256
    from shortkit.util.hashing import sha256_file

    stem_file = root / P / "analysis/SYNTHstemv1/stems/other.wav"
    (root / "assets/library/music/stem_bytes.wav").write_bytes(stem_file.read_bytes())
    rec = root / P / "analysis/SYNTHstemv1/audio/separation.json"
    rec.parent.mkdir(parents=True, exist_ok=True)
    rec.write_text(json.dumps({"stems_sha256": {"other": sha256_file(stem_file)}}))
    stem_file.unlink()
    assert reference_stem_match("assets/library/music/stem_bytes.wav")["method"] == "sha256"


# ============================================================================ 2. partial SFX catalog
def _partial_catalog(root, per_type: dict, classes: dict, columns: dict, col_values: dict | None = None,
                     per_video_count: str = "measured"):
    """SYNTHETIC catalog written the way ``ref sfx-catalog`` writes a partial one: every video counted
    (per_video_count measured), some per-type column not measured for every event."""
    from .test_sfx_count_rule import _write

    _write(root, per_type, classes, embed=True)
    p = root / P / "sfx_catalog.json"
    cat = json.loads(p.read_text())
    for t in cat["types"]:
        t["columns"] = {"per_video_count": "measured", **columns}
        t.update(copy.deepcopy(col_values or {}))
    cat["status"] = "partial"
    cat["column_status"] = {"per_video_count": per_video_count, **columns}
    cat["unmeasured_columns"] = {c: [t["type_id"] for t in cat["types"]] for c, v in columns.items() if v != "measured"}
    cat["blocker"] = "감정(영상을 본 사람의 라벨) 못 잼 — SYNTHETIC"
    p.write_text(json.dumps(cat, ensure_ascii=False))


MEASURED_COLS = {"emotion": {"n": 3, "mode": "surprise", "share": {"surprise": 1.0}},
                 "screen_event": {"n": 3, "mode": "appear", "share": {"none": 1.0}},
                 "prev_caption_role": {"n": 3, "mode": "situation", "share": {"situation": 1.0}}}


def test_partial_catalog_runs_the_count_rule_and_blocks_production(root, plan):
    cols = {"prev_caption_role": "measured", "screen_event": "measured", "emotion": "unmeasured"}
    _partial_catalog(root, {"pop": [2, 3, 3, 3, 5]}, {"pop": "edit_sfx"}, cols)   # allowed [2, 5]; the plan has 1 pop
    iss = run(root, plan)
    assert "sfx_count_range" in codes(iss, "error")                 # the count rule ran on the partial catalog
    assert "sfx_catalog_partial" in codes(iss, "warn") and "sfx_range_unmeasured" not in codes(iss)
    p = _prod(plan)
    assert "sfx_catalog_partial" in codes(run(root, p), "error")    # production blocked until fully measured
    assert "sfx_catalog_partial" in codes(run(root, p, allow_unmeasured=True), "warn")
    _partial_catalog(root, {"pop": [1, 1, 1, 1, 1]}, {"pop": "edit_sfx"}, cols)
    assert not {"sfx_count_range", "sfx_total_range"} & codes(run(root, plan))
    # counts that are lower bounds (SFX under speech not measurable) are not a measured basis
    _partial_catalog(root, {"pop": [2, 3, 3, 3, 5]}, {"pop": "edit_sfx"}, cols, per_video_count="lower_bound")
    iss = run(root, plan)
    assert "sfx_range_unmeasured" in codes(iss) and "sfx_count_range" not in codes(iss)


def test_partial_column_is_not_a_catalog_rule(root, plan):
    p = _prod(plan)
    p["sfx"][0]["emotion"] = "funny"                                  # not in the (partial) emotion share
    partial_emo = {**MEASURED_COLS, "emotion": {**MEASURED_COLS["emotion"], "n_missing": 2, "n_events": 5}}
    cols = {"prev_caption_role": "measured", "screen_event": "measured", "emotion": "partial"}
    _partial_catalog(root, {"pop": [1, 1, 1, 1, 1]}, {"pop": "edit_sfx"}, cols, partial_emo)
    iss = run(root, p, allow_unmeasured=True)
    assert "sfx_emotion_mismatch" not in codes(iss)                  # a partial column is never used as a rule ...
    assert "sfx_emotion_unmeasured" in codes(iss, "warn")             # ... it is 못 잼
    assert "sfx_emotion_unmeasured" in codes(run(root, p), "error")
    # the measured columns of the same partial catalog ARE rules
    assert "sfx_screen_event_mismatch" not in codes(iss) and "sfx_prev_caption_mismatch" not in codes(iss)
    bad = {**partial_emo, "prev_caption_role": {"n": 3, "mode": "reaction", "share": {"reaction": 1.0}}}
    _partial_catalog(root, {"pop": [1, 1, 1, 1, 1]}, {"pop": "edit_sfx"}, cols, bad)
    assert "sfx_prev_caption_mismatch" in codes(run(root, p, allow_unmeasured=True), "error")
    # once the column is measured it is a rule again
    cols_m = {**cols, "emotion": "measured"}
    _partial_catalog(root, {"pop": [1, 1, 1, 1, 1]}, {"pop": "edit_sfx"}, cols_m, MEASURED_COLS)
    assert "sfx_emotion_mismatch" in codes(run(root, p, allow_unmeasured=True), "error")


def test_catalog_column_state_reads_columns_then_derives():
    from shortkit.edit.validate import catalog_column_state, catalog_counts_measured

    assert catalog_column_state({"columns": {"emotion": "partial"}, "emotion": {"n": 3}}, "emotion") == "partial"
    assert catalog_column_state({"emotion": {"n": 3, "n_missing": 1}}, "emotion") == "partial"
    assert catalog_column_state({"emotion": {"n": 0}}, "emotion") == "unmeasured"
    assert catalog_column_state({"emotion": {"n": 3}}, "emotion") == "measured"
    assert catalog_counts_measured({"status": "measured"})
    assert catalog_counts_measured({"status": "partial", "column_status": {"per_video_count": "measured"}})
    assert not catalog_counts_measured({"status": "partial", "column_status": {"per_video_count": "lower_bound"}})
    assert not catalog_counts_measured({"status": "partial"})
    assert not catalog_counts_measured({"status": "unmeasured", "column_status": {"per_video_count": "measured"}})


# ============================================================================ 3. first caption definition
def test_first_caption_uses_the_reference_analyzer_definition(root, plan):
    from shortkit.edit.validate import first_caption_excluded_roles
    from shortkit.qa.checks import FIRST_CAPTION_EXCLUDED_ROLES as QA_ROLES
    from shortkit.reference.aggregate import FIRST_CAPTION_EXCLUDED_ROLES as REF_ROLES

    assert {"title", "description"} <= set(first_caption_excluded_roles())
    assert first_caption_excluded_roles() == tuple(REF_ROLES)          # the analyzer's own constant
    assert set(QA_ROLES) == set(REF_ROLES)                              # QA's row uses the same definition
    plan["captions"][1]["start"] = 1.0                   # first TIMED caption at 1.0 s (title at 0.0 s)
    iss = run(root, plan)
    assert "first_caption_unmeasured" in codes(iss, "warn")          # preset value provisional: not compared
    assert "first_caption_timing" not in codes(iss)
    from shortkit.util.jsonio import write_yaml

    write_yaml(root / P / "measured.yaml", {"preset_id": "joshuamagazine-v1",
                                            "common": {"structure": {"first_caption_at_s": 1.0}}})
    iss = run(root, plan)
    # the old rule took the title at 0.0 s and warned |0.0 - 1.0| > 0.25; the analyzer leaves the title out
    assert not {"first_caption_timing", "first_caption_unmeasured"} & codes(iss), iss
    write_yaml(root / P / "measured.yaml", {"preset_id": "joshuamagazine-v1",
                                            "common": {"structure": {"first_caption_at_s": 0.0}}})
    msgs = [i["message_ko"] for i in run(root, plan) if i["code"] == "first_caption_timing"]
    assert msgs and "c_s" in msgs[0]


# ============================================================================ 4. intro_type vs intro variants
def _formats(root, variants):
    p = root / P / "formats.yaml"
    fy = yaml.safe_load(p.read_text(encoding="utf-8"))
    fy.update({"status": "measured", "blocker": None,
               "table": [{"format_id": "F1", "structure_type": "SYNTH", "n": 3, "members": ["v1", "v2", "v3"],
                          "intro_variants": [{"intro_type": k, "n": n, "members": []} for k, n in variants]}]})
    p.write_text(yaml.safe_dump(fy, allow_unicode=True), encoding="utf-8")


def test_intro_type_is_checked_against_the_formats_intro_variants(root, plan):
    _formats(root, [("질문형", 2), ("결과 먼저", 1)])
    p = _prod(plan)
    p["format_id"] = "F1"
    assert "intro_type_missing" in codes(run(root, p), "error")
    p["intro_type"] = "질문형"
    iss = run(root, p)
    assert not {"intro_type_missing", "intro_type_unknown", "intro_variants_unmeasured"} & codes(iss)
    p["intro_type"] = "카운트다운"
    assert "intro_type_unknown" in codes(run(root, p), "error")
    t = copy.deepcopy(p)
    t["mode"] = "test"
    assert "intro_type_unknown" in codes(run(root, t), "warn")
    # a member without a recorded intro -> the list of variants is incomplete -> 못 잼
    _formats(root, [("질문형", 2), ("미기재", 1)])
    p["intro_type"] = "질문형"
    assert "intro_variants_unmeasured" in codes(run(root, p), "error")
    assert "intro_variants_unmeasured" in codes(run(root, p, allow_unmeasured=True), "warn")
    assert "intro_variants_unmeasured" in codes(run(root, t), "warn")


def test_intro_type_in_schema_and_unmeasured_formats(root, plan):
    plan["intro_type"] = ""
    assert "schema" in codes(run(root, plan), "error")            # present means a real label
    plan["intro_type"] = "질문형"
    iss = run(root, plan)                                          # repo formats.yaml: unmeasured, test mode
    assert "schema" not in codes(iss) and "intro_variants_unmeasured" in codes(iss, "warn")


# ============================================================================ 5. cut density / shot length
def test_cut_structure_of_the_plan_vs_the_reference_range(root, plan):
    from shortkit.edit.resolve import resolve_context
    from shortkit.edit.validate import cut_structure, planned_transitions

    ctx = resolve_context(plan, load_preset())
    tr = planned_transitions(ctx.resolved)
    assert [x["type"] for x in tr] == ["flash", "crossfade"]
    cs = cut_structure([x["t"] for x in tr], ctx.resolved.duration)
    iss = run(root, plan)
    assert {"cuts_per_10s_unmeasured", "shot_len_s_unmeasured"} <= codes(iss, "warn")      # preset: n 0, null
    lo, hi = cs["cuts_per_10s"] - 0.5, cs["cuts_per_10s"] + 0.5
    set_preset(root, "structure.cuts_per_10s", {"p10": lo, "p50": cs["cuts_per_10s"], "p90": hi, "n": 20})
    set_preset(root, "structure.shot_len_s", {"p10": cs["shot_len_median_s"] - 0.3, "p50": cs["shot_len_median_s"],
                                              "p90": cs["shot_len_median_s"] + 0.3, "n": 20})
    iss = run(root, plan)
    assert not {"cuts_per_10s_range", "shot_len_s_range", "cuts_per_10s_unmeasured", "shot_len_s_unmeasured"} & codes(iss)
    set_preset(root, "structure.cuts_per_10s", {"p10": hi + 1, "p50": hi + 2, "p90": hi + 3, "n": 20})
    assert "cuts_per_10s_range" in codes(run(root, plan), "warn")
    assert "cuts_per_10s_range" in codes(run(root, _prod(plan)), "error")
    set_preset(root, "structure.shot_len_s", {"p10": 0.2, "p50": 0.3, "p90": 0.4, "n": 20})
    assert "shot_len_s_range" in codes(run(root, _prod(plan)), "error")


def test_a_cut_that_continues_the_same_shot_is_not_a_boundary(root, plan):
    from shortkit.edit.resolve import resolve_context
    from shortkit.edit.validate import planned_transitions

    plan["timeline"] = [{"id": "s1", "source": "a", "src_in": 0.5, "src_out": 1.5, "purpose": "hook"},
                        {"id": "s2", "source": "a", "src_in": 1.5, "src_out": 2.5},       # next source frame: no cut seen
                        {"id": "s3", "source": "b", "src_in": 0.0, "src_out": 2.0}]
    tr = planned_transitions(resolve_context(plan, load_preset()).resolved)
    assert [(x["clip_id"], x["type"]) for x in tr] == [("s3", "cut")]


def test_cut_structure_is_the_reference_analyzers_definition():
    """validate/QA ``cut_structure`` == ``reference.aggregate.cut_structure_rows`` on the same SYNTHETIC shots."""
    from shortkit.edit.validate import cut_structure
    from shortkit.reference.aggregate import cut_structure_rows

    vids = {"v1": ([1.0, 2.5, 2.9, 7.0], 10.0), "v2": ([], 6.0), "v3": ([0.0, 3.3, 5.0], 5.0)}
    videos = {v: {"format_id": "F1", "shots": {"duration": d, "cuts": [{"t": t, "type": "cut"} for t in ts],
                                                 "presence": {"cut": "present"}}} for v, (ts, d) in vids.items()}
    ref = cut_structure_rows(videos, {v: d for v, (_, d) in vids.items()})["per_video"]
    for v, (ts, d) in vids.items():
        mine = cut_structure(ts, d)
        assert mine["cuts_per_10s"] == ref[v]["cuts_per_10s"] and mine["shot_len_median_s"] == ref[v]["shot_len_median_s"]
