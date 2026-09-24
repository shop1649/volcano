"""Every validation rule has a failing and a passing case (synthetic media, temp project root)."""
from __future__ import annotations

import json

import pytest
import yaml

from .conftest import M, codes, load_preset, set_preset, write_plan


def run(root, plan, **kw):
    from shortkit.edit.validate import validate

    write_plan(root, plan)
    return validate(plan, load_preset(), **kw)


def test_base_plan_passes(root, plan):
    iss = run(root, plan)
    assert not codes(iss, "error"), iss
    # unmeasured things are never silent: they show up as warnings
    assert {"preset_unmeasured", "sfx_range_unmeasured", "format_unclassified"} <= codes(iss, "warn")


def test_schema_error(root, plan):
    plan["timeline"][0]["bogus"] = 1
    assert "schema" in codes(run(root, plan), "error")


# ----------------------------------------------------------------------------- preset / format
def test_preset_mixing_guard(root, plan):
    plan["preset_id"] = "other-channel-v1"
    assert "preset_mix" in codes(run(root, plan), "error")


def test_preset_mixing_side_file(root, plan):
    p = root / "presets/joshuamagazine/sfx_map.yaml"
    d = yaml.safe_load(p.read_text())
    d["preset_id"] = "other-channel-v1"
    p.write_text(yaml.safe_dump(d))
    assert "preset_mix" in codes(run(root, plan), "error")


def test_format_unclassified_only_in_test(root, plan):
    assert "format_unclassified" not in codes(run(root, plan), "error")
    plan["mode"] = "production"
    assert "format_unclassified" in codes(run(root, plan), "error")


def test_format_production_requires_measured_table(root, plan):
    plan["mode"] = "production"
    plan["format_id"] = "F1"
    assert "formats_unmeasured" in codes(run(root, plan), "error")
    p = root / "presets/joshuamagazine/formats.yaml"
    d = yaml.safe_load(p.read_text())
    d["status"] = "measured"
    d["table"] = [{"format_id": "F1", "name": "x"}]
    p.write_text(yaml.safe_dump(d))
    c = codes(run(root, plan), "error")
    assert not ({"formats_unmeasured", "format_unknown", "format_unclassified"} & c)
    plan["format_id"] = "F9"
    assert "format_unknown" in codes(run(root, plan), "error")


# ----------------------------------------------------------------------------- sources
def test_source_missing_and_sha(root, plan):
    plan["sources"][0]["sha256"] = "0" * 64
    assert "source_sha_mismatch" in codes(run(root, plan), "error")
    plan["sources"][0]["path"] = f"{M}/nope.mp4"
    assert "source_missing" in codes(run(root, plan), "error")


def test_source_excluded_by_reference_overlap(root, plan):
    rec = {"id": "w1", "platform": "tiktok", "url": "https://example.invalid/v/1", "original_url": None,
           "reference_overlap": {"excluded": True, "matched_video_id": "ref123", "method": "phash"}}
    (root / "warehouse/candidates.jsonl").write_text(json.dumps(rec) + "\n")
    plan["sources"][0]["warehouse_id"] = "w1"
    assert "source_excluded_reference" in codes(run(root, plan), "error")
    rec["reference_overlap"]["excluded"] = False
    (root / "warehouse/candidates.jsonl").write_text(json.dumps(rec) + "\n")
    assert not {"source_excluded_reference", "source_excluded_url"} & codes(run(root, plan), "error")


def test_source_excluded_by_url(root, plan):
    rec = {"id": "w2", "url": "https://example.invalid/v/2", "original_url": "https://example.invalid/orig/9",
           "reference_overlap": {"excluded": False}}
    (root / "warehouse/candidates.jsonl").write_text(json.dumps(rec) + "\n")
    (root / "warehouse/exclusions.jsonl").write_text(
        json.dumps({"kind": "url", "url": "https://example.invalid/orig/9/", "reason": "레퍼런스 원본"}) + "\n")
    plan["sources"][0]["warehouse_id"] = "w2"
    assert "source_excluded_url" in codes(run(root, plan), "error")
    (root / "warehouse/exclusions.jsonl").write_text("")
    assert "source_excluded_url" not in codes(run(root, plan), "error")


def test_provenance_required_in_production(root, plan):
    plan["mode"] = "production"
    assert "provenance_missing" in codes(run(root, plan), "error")
    plan["mode"] = "test"
    assert "provenance_missing" in codes(run(root, plan), "warn")


# ----------------------------------------------------------------------------- timeline
def test_segment_ranges(root, plan):
    plan["timeline"][0]["src_out"] = 9.0          # source is 4 s long
    assert "segment_beyond_source" in codes(run(root, plan), "error")
    plan["timeline"][0]["src_out"] = 0.4           # <= src_in
    assert "segment_range" in codes(run(root, plan), "error")


def test_zoom_consecutive(root, plan):
    plan["timeline"][0]["zoom"] = {"center": [160, 90]}
    assert "zoom_stacked" not in codes(run(root, plan), "error")
    plan["timeline"][1]["zoom"] = {"center": [160, 90]}
    assert "zoom_stacked" in codes(run(root, plan), "error")


def test_freeze_count(root, plan):
    plan["timeline"][0]["freeze"] = {"at": "end"}
    assert "freeze_count" not in codes(run(root, plan), "error")   # 2 <= max 2
    plan["timeline"][2]["freeze"] = {"at": "end"}
    assert "freeze_count" in codes(run(root, plan), "error")


def test_first_segment_transition(root, plan):
    plan["timeline"][0]["transition_in"] = {"type": "flash"}
    assert "transition_first" in codes(run(root, plan), "error")


# ----------------------------------------------------------------------------- captions
def test_grounding_rules(root, plan):
    del plan["captions"][1]["grounding"]
    assert "caption_grounding" in codes(run(root, plan), "warn")
    plan["mode"] = "production"
    assert "caption_grounding" in codes(run(root, plan), "error")
    plan["captions"][1]["grounding"] = {"kind": "seen"}
    assert "caption_grounding" not in codes(run(root, plan))


def test_dialogue_must_be_heard(root, plan):
    plan["mode"] = "production"
    plan["captions"].append({"id": "c_d", "role": "dialogue", "text": "안녕", "start": 2.2, "end": 3.0,
                             "grounding": {"kind": "seen"}})
    assert "dialogue_not_heard" in codes(run(root, plan), "error")
    plan["captions"][-1]["grounding"] = {"kind": "heard", "source": "a", "src_t": 2.7}
    assert "dialogue_not_heard" not in codes(run(root, plan))


def test_same_role_overlap(root, plan):
    plan["captions"].append({"id": "c_s2", "role": "situation", "text": "또 움직인다", "start": 1.5, "end": 2.5,
                             "grounding": {"kind": "seen"}})
    assert "caption_same_role_overlap" in codes(run(root, plan), "error")
    plan["captions"][-1]["start"] = 2.0
    assert "caption_same_role_overlap" not in codes(run(root, plan))


def test_cross_role_collision(root, plan):
    # dialogue shares the situation anchor (y=1430) -> collides while both are visible
    plan["captions"].append({"id": "c_d", "role": "dialogue", "text": "안녕", "start": 1.0, "end": 1.8,
                             "grounding": {"kind": "heard"}})
    assert "caption_collision" in codes(run(root, plan), "error")
    plan["captions"][-1]["start"], plan["captions"][-1]["end"] = 2.1, 2.9
    assert "caption_collision" not in codes(run(root, plan))


def test_caption_fit_uses_font_metrics(root, plan):
    plan["captions"][1]["text"] = "아주 길고 긴 상황 설명 자막이 세 줄을 넘어서 계속 이어진다 정말로 길다"
    c = codes(run(root, plan), "error")
    assert "caption_overflow_lines" in c
    plan["captions"][1]["text"] = "짧은 자막"
    assert "caption_overflow_lines" not in codes(run(root, plan))


def test_caption_covers_protected(root, plan):
    # protected face of source a maps to canvas ~ (472..607, 723..859); put a situation caption on it
    plan["captions"][1]["pos"] = [540, 790]
    c = codes(run(root, plan), "error")
    assert "caption_covers_protected" in c
    # same place but the protected rect is only active later (source time 3.0+) -> no overlap
    plan["sources"][0]["protected"][0]["start"] = 3.0
    assert "caption_covers_protected" not in codes(run(root, plan))


def test_caption_safe_margin(root, plan):
    plan["captions"][1]["pos"] = [540, 1850]
    assert "caption_outside_safe" in codes(run(root, plan), "error")


def test_reveal_guard(root, plan):
    plan["reveal"] = {"t": 3.0, "keywords": ["움직"]}
    assert "reveal_leak" in codes(run(root, plan), "error")
    plan["reveal"]["t"] = 0.1
    assert "reveal_leak" not in codes(run(root, plan))


def test_identity_text_forbidden(root, plan):
    plan["title_candidates"][0] = "조슈아 매거진 스타일"
    assert "identity_text" in codes(run(root, plan), "error")


def test_font_never_substituted(root, plan):
    set_preset(root, "text.roles.situation.font_name", "No Such Font Family XYZ")
    assert "font_missing" in codes(run(root, plan), "error")


# ----------------------------------------------------------------------------- SFX
def test_sfx_event_kind_cut(root, plan):
    plan["sfx"][0]["event"]["kind"] = "cut"
    assert "sfx_cut_event" in codes(run(root, plan), "error")


def test_sfx_event_offset(root, plan):
    plan["sfx"][0]["event"]["t"] = 1.35
    assert "sfx_event_offset" in codes(run(root, plan), "error")
    plan["sfx"][0]["event"]["t"] = 1.3
    assert "sfx_event_offset" not in codes(run(root, plan))


def test_sfx_stacking(root, plan):
    plan["sfx"].append({"id": "fx2", "type": "pop", "t": 1.3, "event": {"t": 1.3, "desc": "또 나타남", "kind": "appear"},
                        "file": f"{M}/pop.wav"})
    assert "sfx_stacking" in codes(run(root, plan), "error")
    plan["sfx"][-1]["type"] = "ding"
    assert "sfx_stacking" not in codes(run(root, plan))


def _measured_catalog(root, p10, p90, tot=None):
    cat = {"schema": "shortkit.sfx_catalog/1", "preset_id": "joshuamagazine-v1", "status": "measured",
           "types": [{"type_id": "pop", "class": "edit_sfx",
                      "per_video_count": {"overall": {"n": 50, "p10": p10, "p50": p10, "p90": p90}}}]}
    if tot:
        cat["per_video_total"] = {"overall": {"n": 50, "p10": tot[0], "p50": tot[0], "p90": tot[1]}}
    (root / "presets/joshuamagazine/sfx_catalog.json").write_text(json.dumps(cat))


def test_sfx_count_range_from_measured_catalog(root, plan):
    _measured_catalog(root, 2, 4, (1, 6))
    assert "sfx_count_range" in codes(run(root, plan), "error")       # 1 pop < p10 2
    _measured_catalog(root, 1, 3, (1, 6))
    c = codes(run(root, plan))
    assert "sfx_count_range" not in c and "sfx_range_unmeasured" not in c
    _measured_catalog(root, 1, 3, (3, 6))
    assert "sfx_total_range" in codes(run(root, plan), "error")
    plan["sfx"][0]["type"] = "whoosh_unknown"
    assert "sfx_type_unknown" in codes(run(root, plan), "error")


def test_sfx_catalog_unmeasured_never_silent(root, plan):
    assert "sfx_range_unmeasured" in codes(run(root, plan), "warn")
    plan["mode"] = "production"
    assert "sfx_range_unmeasured" in codes(run(root, plan), "error")
    assert "sfx_range_unmeasured" in codes(run(root, plan, allow_unmeasured=True), "warn")


def test_sfx_unresolved_refused_in_production(root, plan):
    plan["sfx"][0]["file"] = None
    assert "sfx_unresolved" in codes(run(root, plan), "warn")
    plan["mode"] = "production"
    assert "sfx_unresolved" in codes(run(root, plan), "error")


# ----------------------------------------------------------------------------- audio
def test_original_keep_requires_reason_and_range(root, plan):
    plan["timeline"][0]["original_audio"] = {"keep": True, "ranges": [[1.0, 2.0]]}
    assert "original_keep_reason" in codes(run(root, plan), "error")
    plan["timeline"][0]["original_audio"]["reason"] = "말하는 사람"
    assert "original_keep_reason" not in codes(run(root, plan))
    plan["timeline"][0]["original_audio"]["ranges"] = [[0.2, 2.0]]    # starts before src_in 0.5
    assert "original_range" in codes(run(root, plan), "error")


def test_embedded_music_raw(root, plan):
    plan["sources"][0]["has_embedded_music"] = True
    plan["timeline"][0]["original_audio"] = {"keep": True, "reason": "대사", "stem": "raw"}
    assert "embedded_music_raw" in codes(run(root, plan), "error")
    plan["sources"][0]["vocals_path"] = f"{M}/vocals.wav"
    plan["timeline"][0]["original_audio"]["stem"] = "vocals"
    c = codes(run(root, plan), "error")
    assert "embedded_music_raw" not in c and "vocals_missing" not in c


def test_embedded_music_unknown(root, plan):
    plan["sources"][0]["has_embedded_music"] = None
    plan["timeline"][0]["original_audio"] = {"keep": True, "reason": "대사"}
    assert "embedded_music_unknown" in codes(run(root, plan), "warn")
    plan["mode"] = "production"
    assert "embedded_music_unknown" in codes(run(root, plan), "error")


def test_bgm_silence_inside_duration(root, plan):
    plan["bgm"]["silences"] = [{"start": 5.0, "end": 9.0}]
    assert "silence_range" in codes(run(root, plan), "error")
    plan["bgm"]["silences"] = [{"start": 2.0, "end": 2.5}]
    assert "silence_range" not in codes(run(root, plan))


def test_rule_keys_cannot_be_turned_off(root, plan):
    set_preset(root, "audio.ducking.only_under_kept_dialogue", False)
    set_preset(root, "audio.original.default", "on")
    c = codes(run(root, plan), "error")
    assert {"rule_ducking_scope", "rule_original_default"} <= c


# ----------------------------------------------------------------------------- approval / audit
def test_approval_gate(root, plan):
    plan["mode"] = "production"
    plan["episode_index"] = 1
    assert "approval_required" in codes(run(root, plan, for_render=True), "error")
    assert "approval_required" in codes(run(root, plan), "warn")        # not rendering: just a warning
    from shortkit.edit.plan import plan_sha256

    plan["approval"] = {"approved": True, "approved_by": "tester", "approved_at": "2026-09-24T00:00:00+00:00",
                        "approved_plan_sha256": plan_sha256(plan)}
    assert "approval_required" not in codes(run(root, plan, for_render=True))
    plan["captions"][1]["text"] = "수정된 자막"          # later edit: recorded, never re-asked
    c = codes(run(root, plan, for_render=True))
    assert "approval_required" not in c and "approval_plan_changed" in c


def test_test_mode_never_needs_approval(root, plan):
    plan["episode_index"] = 1
    assert "approval_required" not in codes(run(root, plan, for_render=True))


def test_production_audit_unmeasured(root, plan):
    plan["mode"] = "production"
    assert "preset_unmeasured" in codes(run(root, plan), "error")
    assert "preset_unmeasured" in codes(run(root, plan, allow_unmeasured=True), "warn")


# ----------------------------------------------------------------------------- framing / repetition
def test_crop_must_keep_protected(root, plan):
    plan["sources"][0]["clean"]["crop"] = {"x": 0, "y": 60, "w": 320, "h": 120}   # face at y 20..60 cut away
    assert "crop_cuts_protected" in codes(run(root, plan), "error")
    plan["sources"][0]["clean"]["crop"] = {"x": 0, "y": 10, "w": 320, "h": 160}
    assert "crop_cuts_protected" not in codes(run(root, plan))


def test_region_fit_must_keep_protected(root, plan):
    # 240x240 source b cover-fitted into 1080x608 shows only source y 52..188: a hand at the top is cut
    plan["sources"][1]["protected"] = [{"label": "손", "x": 100, "y": 10, "w": 30, "h": 30}]
    assert "protected_cropped" in codes(run(root, plan), "error")
    plan["sources"][1]["protected"] = [{"label": "손", "x": 100, "y": 100, "w": 30, "h": 30}]
    assert "protected_cropped" not in codes(run(root, plan))


def test_repeat_and_stacked_transitions(root, plan):
    plan["timeline"].append({"id": "s4", "source": "a", "src_in": 1.0, "src_out": 2.0, "transition_in": {"type": "flash"}})
    plan["timeline"][2]["transition_in"] = {"type": "flash"}
    c = codes(run(root, plan), "warn")
    assert "segment_repeat" in c and "transition_stacked" in c


def test_bgm_must_not_be_reference_stem(root, plan):
    d = root / "presets/joshuamagazine/analysis/vid1/stems"
    d.mkdir(parents=True)
    (d / "other.wav").write_bytes((root / M / "bgm.wav").read_bytes())
    plan["bgm"]["path"] = "presets/joshuamagazine/analysis/vid1/stems/other.wav"
    assert "bgm_from_reference" in codes(run(root, plan), "error")


def test_first_episode_proposal_needs_cover_and_three_titles(root, plan):
    plan["mode"] = "production"
    plan["episode_index"] = 1
    plan["title_candidates"] = ["하나", "둘"]
    assert "proposal_incomplete" in codes(run(root, plan), "error")
    plan["title_candidates"].append("셋")
    assert "proposal_incomplete" not in codes(run(root, plan))


def test_vocals_stem_quality_is_a_listening_item(root, plan):
    plan["sources"][0]["vocals_path"] = f"{M}/vocals.wav"
    plan["timeline"][0]["original_audio"] = {"keep": True, "reason": "대사", "stem": "vocals"}
    assert "vocals_quality_unchecked" in codes(run(root, plan), "warn")


def test_sfx_event_must_match_real_source_moment(root, plan):
    # s1 shows source a 0.5..2.5 at output 0..2 -> src_t 1.6 appears at output 1.1
    plan["sfx"][0]["event"].update({"source": "a", "src_t": 1.6})
    assert not {"sfx_event_mismatch", "sfx_event_not_shown"} & codes(run(root, plan))
    plan["sfx"][0]["event"]["src_t"] = 2.2          # really shown at 1.7 -> sfx at 1.0 is 0.7 s off
    assert "sfx_event_mismatch" in codes(run(root, plan), "error")
    plan["sfx"][0]["event"]["src_t"] = 3.9          # cut out of the edit
    assert "sfx_event_not_shown" in codes(run(root, plan), "error")


def test_paths_must_be_root_relative(root, plan):
    plan["output"] = {"path": "../outside.mp4"}
    assert "path_not_root_relative" in codes(run(root, plan), "error")
    plan["output"] = {"path": "episodes/t1/output/t1.mp4"}
    assert "path_not_root_relative" not in codes(run(root, plan))
