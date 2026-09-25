"""Review wave 2 (group C) regression tests: caption / structure / audio / SFX / source rules of ``episode validate``.

Every test builds a plan over SYNTHETIC media (tests/edit/conftest.py: testsrc2 video, sine tones, a synthetic
speech-like line at 1.0-2.6 s, a synthetic chord bed) in a temporary project root.  Finding ids in the names."""
from __future__ import annotations

import copy
import json
import shutil
import subprocess

import numpy as np
import pytest

from .conftest import M, codes, load_preset, set_preset, sha, write_plan
from .test_validate import run


def _msgs(iss, code):
    return [i["message_ko"] for i in iss if i["code"] == code]


def _sev(iss, code):
    return {i["severity"] for i in iss if i["code"] == code}


def _prod(plan):
    p = copy.deepcopy(plan)
    p["mode"] = "production"
    return p


def _speech_source(root, plan, sid="sp", seg=("s3", 0.5, 3.5)):
    """Put the synthetic speech source (speech 1.0-2.6 s) into the plan as segment ``seg``."""
    plan["sources"].append({"id": sid, "path": f"{M}/src_speech.mp4", "sha256": sha(root / M / "src_speech.mp4"),
                            "warehouse_id": None, "has_embedded_music": False, "clean": {},
                            "protected": [{"label": "얼굴", "x": 10, "y": 10, "w": 30, "h": 30}]})
    sid_seg, a, b = seg
    for i, s in enumerate(plan["timeline"]):
        if s["id"] == sid_seg:
            plan["timeline"][i] = {"id": sid_seg, "source": sid, "src_in": a, "src_out": b,
                                   "transition_in": {"type": "crossfade", "dur": 0.25}}
    return plan


# ----------------------------------------------------------------------------- S3-04 grounding
def test_s3_04_grounding_must_point_at_shown_footage(root, plan):
    p = _prod(plan)
    base = codes(run(root, p))
    assert not {"grounding_framing_role", "grounding_incomplete", "grounding_not_shown", "grounding_not_on_screen"} & base
    p["captions"][1]["grounding"] = {"kind": "framing"}
    assert "grounding_framing_role" in codes(run(root, p), "error")
    p["captions"][1]["grounding"] = {"kind": "seen"}
    assert "grounding_incomplete" in codes(run(root, p), "error")
    p["captions"][1]["grounding"] = {"kind": "seen", "source": "a", "src_t": 0.1}      # before s1 (src 0.5..)
    assert "grounding_not_shown" in codes(run(root, p), "error")
    p["captions"][1]["grounding"] = {"kind": "seen", "source": "b", "src_t": 2.0}      # on screen at 5.25 s
    assert "grounding_not_on_screen" in codes(run(root, p), "error")
    # production also needs a grounding for title/description (kind framing allowed there)
    assert "caption_grounding" in codes(run(root, p), "error")
    p["captions"][0]["grounding"] = {"kind": "framing", "note": "편집 틀 제목"}
    assert not [i for i in run(root, p) if i["code"] == "caption_grounding" and i["where"] == "captions[c_t]"]


def test_s3_04_heard_line_needs_speech_and_relation_needs_note(root, plan):
    p = _speech_source(root, _prod(plan))
    p["captions"].append({"id": "c_d", "role": "dialogue", "text": "저기 봐", "start": 3.8, "end": 5.3,
                          "grounding": {"kind": "heard", "source": "sp", "src_t": 1.2}})
    iss = run(root, p)
    assert not {"grounding_no_speech", "grounding_speech_unmeasured"} & codes(iss), _msgs(iss, "grounding_no_speech")
    p["captions"][-1]["grounding"]["src_t"] = 3.2                  # silent part of the source
    p["captions"][-1].update(start=5.5, end=6.2)
    assert "grounding_no_speech" in codes(run(root, p), "error")
    p["captions"].append({"id": "c_k", "role": "speaker", "text": "엄마", "start": 0.3, "end": 1.5, "pos": [500, 700],
                          "grounding": {"kind": "seen", "source": "a", "src_t": 1.0}})
    assert "grounding_relation_note" in codes(run(root, p), "error")
    p["captions"][-1]["grounding"]["note"] = "영상 설명란에 '엄마와 딸' 로 소개됨"
    assert "grounding_relation_note" not in codes(run(root, p))


def test_s3_04_watch_record(root, plan):
    p = _prod(plan)
    iss = run(root, p)
    assert {"sources[a].watched", "sources[b].watched"} <= {i["where"] for i in iss if i["code"] == "watch_record_missing"}
    for s in p["sources"]:
        s["watched"] = {"by": "tester", "at": "2026-09-25T00:00:00+00:00", "sha256": s["sha256"]}
    assert not {"watch_record_missing", "watch_record_sha"} & codes(run(root, p))
    p["sources"][0]["watched"]["sha256"] = "0" * 64
    assert "watch_record_sha" in codes(run(root, p), "error")


# ----------------------------------------------------------------------------- S3-05 reveal
def test_s3_05_reveal_required_and_titles_checked(root, plan):
    p = _prod(plan)
    assert "reveal_missing" in codes(run(root, p), "error")
    p["reveal"] = {"none": True, "reason": "반전이 없는 이야기"}
    assert "reveal_missing" not in codes(run(root, p))
    p["timeline"][2]["purpose"] = "reveal"
    assert "reveal_missing" in codes(run(root, p), "error")
    p["reveal"] = {"t": 3.3, "keywords": ["사라짐"]}
    p["title_candidates"] = ["가나", "결국 사라짐", "다라"]
    p["cover"]["text"] = "사라짐 주의"
    iss = run(root, p)
    assert "reveal_in_title" in codes(iss, "error") and "reveal_in_cover" in codes(iss, "error")
    # the order of disclosure vs the reference format: not measured -> 못 잼, never silently passed
    assert "reveal_order_unmeasured" in codes(iss)
    # test mode without a reveal segment: no reveal block needed
    assert "reveal_missing" not in codes(run(root, plan))


# ----------------------------------------------------------------------------- S3-06 cuts
def test_s3_06_cut_inside_declared_action(root, plan):
    plan["actions"] = [{"id": "act1", "source": "a", "src_start": 2.0, "src_end": 3.0, "desc": "일어서는 동작"}]
    assert "cut_inside_action" in codes(run(root, plan), "warn")     # s1 ends / s2 starts at 2.5
    p = _prod(plan)
    assert "cut_inside_action" in codes(run(root, p), "error")
    p["actions"][0]["src_end"] = 2.5
    assert "cut_inside_action" not in codes(run(root, p))


def test_s3_06_kept_line_and_dialogue_not_cut(root, plan):
    p = _speech_source(root, _prod(plan))
    p["timeline"][2]["original_audio"] = {"keep": True, "reason": "대사", "ranges": [[0.8, 2.0]]}
    assert "kept_speech_cut" in codes(run(root, p), "error")        # speech runs 1.0-2.6
    p["timeline"][2]["original_audio"]["ranges"] = [[0.8, 2.8]]
    assert "kept_speech_cut" not in codes(run(root, p))
    p["timeline"][2]["src_out"] = 2.0
    p["timeline"][2].pop("original_audio")
    p["captions"].append({"id": "c_d", "role": "dialogue", "text": "저기 봐", "start": 3.8, "end": 4.9,
                          "grounding": {"kind": "heard", "source": "sp", "src_t": 1.2}})
    assert "dialogue_line_cut" in codes(run(root, p), "error")


def test_s3_06_trim_tail_is_an_error_in_production(root, plan):
    assert "trim_no_meaning" in codes(run(root, plan), "warn")       # s3 has no meaning mark
    p = _prod(plan)
    assert "trim_no_meaning" in codes(run(root, p), "error")
    p["timeline"][2]["tail_reason"] = "마지막 장면을 여운으로 남김(레퍼런스 마무리처럼)"
    iss = run(root, p)
    assert "trim_no_meaning" in codes(iss, "warn") and "trim_no_meaning" not in codes(iss, "error")


# ----------------------------------------------------------------------------- S3-07 repetition
def test_s3_07_repetition_is_blocked_in_production(root, plan):
    p = _prod(plan)
    p["timeline"].append({"id": "s4", "source": "a", "src_in": 0.5, "src_out": 2.0, "purpose": "reaction"})
    assert "segment_repeat" in codes(run(root, p), "error")
    p["timeline"][3].update(replay_of="s1", replay_reason="결정적 순간 다시보기")
    iss = run(root, p)
    assert "segment_repeat" not in codes(iss) and "segment_replay" in codes(iss, "warn")
    p["timeline"][2]["transition_in"] = {"type": "flash"}            # s2 flash, s3 flash
    assert "transition_stacked" in codes(run(root, p), "error")
    p["captions"] += [{"id": f"c_r{i}", "role": "reaction", "text": "헉", "start": 1.0 + i, "end": 1.8 + i,
                       "grounding": {"kind": "seen", "source": "a", "src_t": 1.5 + i * 0.5}} for i in range(2)]
    assert "caption_repeat" in codes(run(root, p), "error")
    arrow = {"kind": "arrow", "start": 0.5, "end": 1.5, "keyframes": [{"t": 0.0, "x": 900, "y": 300}]}
    p["decorations"] = [{"id": "d1", **arrow}, {"id": "d2", **arrow}]
    assert "decoration_duplicate" in codes(run(root, p), "error")


# ----------------------------------------------------------------------------- S3-08 protected
def test_s3_08_protected_must_be_declared(root, plan):
    p = _prod(plan)
    iss = run(root, p)
    assert "sources[b].protected" in {i["where"] for i in iss if i["code"] == "protected_missing"}
    assert _sev(iss, "protected_missing") == {"error"}
    p["sources"][1]["protected_reviewed"] = {"by": "tester", "at": "2026-09-25", "note": "사람·손·물체 없는 시험 패턴"}
    assert "protected_missing" not in codes(run(root, p))
    assert _sev(run(root, plan), "protected_missing") == {"warn"}


# ----------------------------------------------------------------------------- S3-10 Korean
def test_s3_10_narration_must_be_korean(root, plan):
    p = _prod(plan)
    p["captions"][1]["text"] = "He sits back down"
    assert "caption_not_korean" in codes(run(root, p), "error")
    p["captions"][1]["text"] = "iPhone 떨어뜨림"
    assert "caption_not_korean" in codes(run(root, p), "error")
    p["captions"][1]["foreign_terms"] = ["iPhone"]
    assert "caption_not_korean" not in codes(run(root, p))


# ----------------------------------------------------------------------------- S4-01 / S4-02 original sound
def test_s4_01_embedded_music_is_measured_not_trusted(root, plan):
    plan["sources"].append({"id": "mu", "path": f"{M}/src_music.mp4", "sha256": sha(root / M / "src_music.mp4"),
                            "warehouse_id": None, "has_embedded_music": False, "clean": {}, "protected": []})
    plan["timeline"][2] = {"id": "s3", "source": "mu", "src_in": 0.5, "src_out": 3.5,
                           "transition_in": {"type": "crossfade", "dur": 0.25},
                           "original_audio": {"keep": True, "reason": "인물이 말하는 중요한 대사", "stem": "raw"}}
    iss = run(root, plan)
    assert "embedded_music_detected" in codes(iss, "warn") and "embedded_music_raw" in codes(iss, "error")
    assert "embedded_music_detected" in codes(run(root, _prod(plan)), "error")
    # a speech-only source kept raw: no music found
    p = _speech_source(root, copy.deepcopy(plan), sid="sp2")
    p["timeline"][2]["original_audio"] = {"keep": True, "reason": "대사", "ranges": [[0.8, 2.8]]}
    assert not {"embedded_music_detected", "embedded_music_raw", "embedded_music_unverified"} & codes(run(root, p))


def test_s4_02_kept_range_must_be_speech_and_ducks_only_speech(root, plan):
    from shortkit.edit.resolve import resolve_context

    plan["timeline"][2]["original_audio"] = {"keep": False}
    plan["timeline"][0]["original_audio"] = {"keep": True, "reason": "말하는 사람", "ranges": [[1.0, 2.0]]}  # a 440 Hz tone
    iss = run(root, plan)
    assert "kept_no_speech" in codes(iss, "warn")
    assert "kept_no_speech" in codes(run(root, _prod(plan)), "error")
    ctx = resolve_context(plan, load_preset())
    assert ctx.resolved.audio.bgm.duck_ranges == []                    # nobody speaks -> no ducking
    p = _speech_source(root, copy.deepcopy(plan))
    p["timeline"][0].pop("original_audio")
    p["timeline"][2]["original_audio"] = {"keep": True, "reason": "대사", "ranges": [[0.8, 2.8]]}
    write_plan(root, p)
    assert "kept_no_speech" not in codes(run(root, p))
    ctx = resolve_context(p, load_preset())
    (a, b), = ctx.resolved.audio.bgm.duck_ranges
    s3 = next(c for c in ctx.resolved.clips if c.id == "s3")
    # ducked only under the detected speech (1.0-2.6 s of the source), not the whole kept range 0.8-2.8
    assert a == pytest.approx(s3.out_start + (1.0 - 0.5), abs=0.1) and b == pytest.approx(s3.out_start + (2.6 - 0.5), abs=0.15)


def test_s4_03_vocals_stem_needs_passing_quality_record(root, plan):
    d = root / M / "sep"
    d.mkdir()
    shutil.copy(root / M / "vocals.wav", d / "vocals.wav")
    vp = f"{M}/sep/vocals.wav"
    p = _prod(plan)
    p["sources"][0].update(vocals_path=vp, has_embedded_music=True)
    p["timeline"][0]["original_audio"] = {"keep": True, "reason": "대사", "stem": "vocals", "ranges": [[1.0, 2.0]]}
    iss = run(root, p)
    assert "vocals_quality_missing" in codes(iss, "error") and "vocals_listening_needed" in codes(iss, "warn")
    rec = {"schema": "shortkit.source_separation/1", "source_sha256": p["sources"][0]["sha256"], "vocals": vp,
           "status": "measured", "usable": False, "listening_check": "not_done",
           "quality": {"passed": False, "fail_reasons": ["음악 구간 누설 12.0 dB > -20.0 dB"]}}
    (d / "quality.json").write_text(json.dumps(rec, ensure_ascii=False))
    assert "vocals_quality_failed" in codes(run(root, p), "error")
    rec.update(usable=True, quality={"passed": True, "fail_reasons": []})
    (d / "quality.json").write_text(json.dumps(rec, ensure_ascii=False))
    assert not {"vocals_quality_failed", "vocals_quality_missing"} & codes(run(root, p))


# ----------------------------------------------------------------------------- S4-04 BGM
def test_s4_04_bgm_copied_from_a_reference_stem(root, plan):
    stems = root / "presets/joshuamagazine/analysis/SYNTHREF01/stems"
    stems.mkdir(parents=True)
    shutil.copy(root / M / "music.wav", stems / "other.wav")
    lib = root / "assets/library/music"
    lib.mkdir(parents=True)
    shutil.copy(root / M / "music.wav", lib / "bed_copy.wav")                        # same bytes
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(root / M / "music.wav"), "-af", "volume=0.5",
                    "-c:a", "pcm_s24le", str(lib / "bed_quieter.wav")], check=True)   # same waveform, other bytes
    plan["bgm"] = {"enabled": True, "path": "assets/library/music/bed_copy.wav", "silences": []}
    assert "bgm_from_reference" in codes(run(root, plan), "error")
    plan["bgm"]["path"] = "assets/library/music/bed_quieter.wav"
    assert "bgm_from_reference" in codes(run(root, plan), "error")
    plan["bgm"]["path"] = f"{M}/bgm.wav"
    assert "bgm_from_reference" not in codes(run(root, plan))


# ----------------------------------------------------------------------------- S4-06 / S4-07 / S4-08 SFX
def _catalog(root, **type_fields):
    from .test_sfx_count_rule import _write

    _write(root, {"pop": [1, 1, 1, 1, 1]}, {"pop": "edit_sfx"})
    p = root / "presets/joshuamagazine/sfx_catalog.json"
    cat = json.loads(p.read_text())
    cat["types"][0].update(type_fields)
    p.write_text(json.dumps(cat, ensure_ascii=False))


def test_s4_06_catalog_rules_are_production_rules(root, plan):
    share = {"emotion": {"n": 3, "mode": "surprise", "share": {"surprise": 1.0}},
             "screen_event": {"n": 3, "mode": "zoom_in", "share": {"zoom_in": 1.0}},
             "prev_caption_role": {"n": 3, "mode": "situation", "share": {"situation": 1.0}}, "event_window_s": 0.3}
    _catalog(root, **share)
    p = _prod(plan)
    iss = run(root, p, allow_unmeasured=True)
    assert "sfx_emotion_missing" in codes(iss, "error")
    p["sfx"][0]["emotion"] = "funny"
    assert "sfx_emotion_mismatch" in codes(run(root, p, allow_unmeasured=True), "error")
    p["sfx"][0]["emotion"] = "surprise"
    assert "sfx_screen_event_mismatch" in codes(run(root, p, allow_unmeasured=True), "error")   # no zoom at 1.0 s
    p["timeline"][0]["zoom"] = {"center": [160, 90], "start": 1.0}
    iss = run(root, p, allow_unmeasured=True)
    assert not {"sfx_emotion_mismatch", "sfx_screen_event_mismatch", "sfx_prev_caption_mismatch"} & codes(iss)
    _catalog(root, **{**share, "prev_caption_role": {"n": 3, "mode": "reaction", "share": {"reaction": 1.0}}})
    assert "sfx_prev_caption_mismatch" in codes(run(root, p, allow_unmeasured=True), "error")
    _catalog(root, **{**share, "emotion": {"n": 0, "share": {}, "blocker": "라벨 없음"}})
    assert "sfx_emotion_unmeasured" in codes(run(root, p), "error")


def test_s4_07_explicit_file_must_sound_like_its_type(root, plan):
    from shortkit.reference.separation import load_mono
    from shortkit.reference.sfx_events import SR, fingerprint_clip
    from shortkit.reference.sfx_map import onset_of

    x = load_mono(root / M / "pop.wav", SR)
    cen = root / "presets/joshuamagazine/sfx_fp/pop.npy"
    cen.parent.mkdir(parents=True, exist_ok=True)
    np.save(cen, fingerprint_clip(x, SR, onset_of(x))["patch"])
    _catalog(root, fingerprint={"centroid": "presets/joshuamagazine/sfx_fp/pop.npy"})
    p = _prod(plan)
    assert "sfx_file_type_mismatch" not in codes(run(root, p, allow_unmeasured=True))
    p["sfx"][0]["file"] = f"{M}/vocals.wav"                                          # a 4 s 300 Hz tone as "pop"
    assert "sfx_file_type_mismatch" in codes(run(root, p, allow_unmeasured=True), "error")


def test_s4_08_sfx_on_a_cut_is_refused_whatever_its_label(root, plan):
    p = _prod(plan)
    assert "sfx_event_source_missing" in codes(run(root, p), "error")                # event without source/src_t
    # s2 starts at 2.0 s (source a 2.5 s): an "appear" event on its first frame is the cut itself
    p["sfx"][0].update(t=2.0, event={"t": 2.0, "desc": "새 장면이 나타남", "kind": "appear", "source": "a", "src_t": 2.5})
    iss = run(root, p)
    assert "sfx_event_at_cut" in codes(iss, "error") and "sfx_event_source_missing" not in codes(iss)
    p["timeline"][1]["zoom"] = {"center": [160, 90], "start": 0.0}                   # a planned zoom starts there too
    assert "sfx_event_at_cut" not in codes(run(root, p))


# ----------------------------------------------------------------------------- S5-03 exclusions
def test_s5_03_exclusions_rechecked_on_every_validate(root, plan):
    from shortkit.sourcing import exclusions as X

    rec = {"id": "w1", "platform": "youtube", "url": "https://www.youtube.com/watch?v=REFLATEST01", "status": "selected",
           "sha256": plan["sources"][0]["sha256"],
           "reference_overlap": {"excluded": False, "checked_at": "2026-09-01T00:00:00+00:00"}}
    (root / "warehouse/candidates.jsonl").write_text(json.dumps(rec) + "\n")
    plan["sources"][0]["warehouse_id"] = "w1"
    assert not {"source_excluded_url", "source_excluded_reference"} & codes(run(root, plan))
    X.add_url("https://www.youtube.com/shorts/REFLATEST01", "레퍼런스 자체 업로드(합성 픽스처)", "test")
    assert "source_excluded_url" in codes(run(root, plan), "error")                  # url_key: same video
    (root / "warehouse/exclusions.jsonl").write_text("")
    X.add_reference_footage(root / M / "src_a.mp4", "SYNTHREF01")                     # fingerprints added later
    assert "source_excluded_reference" in codes(run(root, plan), "error")


# ----------------------------------------------------------------------------- S5-09 crop vs faces
def test_s5_09_crop_checked_against_face_track(root, plan):
    p = _prod(plan)
    p["sources"][0]["clean"] = {"crop": {"x": 0, "y": 0, "w": 256, "h": 144}}
    p["sources"][0]["protected"] = []
    p["sources"][0]["protected_reviewed"] = {"by": "t", "at": "2026-09-25", "note": "없음"}
    assert "crop_faces_unmeasured" in codes(run(root, p), "error")
    s = p["sources"][0]["sha256"]
    faces = {"status": "measured", "resolution": [320, 180],
             "protected": [{"label": "face", "x": 270, "y": 20, "w": 40, "h": 40, "start": 0.0, "end": 4.0}]}
    (root / "warehouse/overlays").mkdir(parents=True, exist_ok=True)
    (root / f"warehouse/overlays/{s}.faces.json").write_text(json.dumps(faces))
    iss = run(root, p)
    assert "crop_invalid" in codes(iss, "error") and any("보호 영역" in m for m in _msgs(iss, "crop_invalid"))


# ----------------------------------------------------------------------------- S6-6 generated test sources
def test_s6_6_regenerated_test_source_accepted_by_content_in_test_mode(root, plan):
    from shortkit.edit.validate import source_content_fingerprint

    fp = source_content_fingerprint(f"{M}/src_speech.mp4")
    assert fp["video_md5"] and fp["speech"]
    # the "same" source made by another build: video stream copied, audio re-encoded (other bytes)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(root / M / "src_speech.mp4"), "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "96k", str(root / M / "src_speech_rebuilt.mp4")], check=True)
    p = _speech_source(root, copy.deepcopy(plan))
    p["sources"][-1].update(path=f"{M}/src_speech_rebuilt.mp4", test_fingerprint=fp)   # sha256 = original bytes
    iss = run(root, p)
    assert "source_sha_regenerated" in codes(iss, "warn") and "source_sha_mismatch" not in codes(iss)
    assert "source_sha_mismatch" in codes(run(root, _prod(p)), "error")               # production: bytes only
    p["sources"][-1]["test_fingerprint"] = {**fp, "video_md5": "0" * 32}
    assert "source_sha_mismatch" in codes(run(root, p), "error")


# ----------------------------------------------------------------------------- clean.coverage in validate
def test_clean_coverage_is_enforced(root, plan):
    from shortkit.clean.detect import ALGO

    iss = run(root, plan)
    assert "sources[a].clean" in {i["where"] for i in iss if i["code"] == "clean_no_record"}
    assert _sev(iss, "clean_no_record") == {"warn"}
    assert "error" in _sev(run(root, _prod(plan)), "clean_no_record")
    doc = {"algo": ALGO, "source": {"resolution": [320, 180], "duration": 4.0, "fps": 30.0},
           "overlays": [{"id": "o1", "kind": "logo", "rect": {"x": 150, "y": 80, "w": 30, "h": 16},
                         "resolution": [320, 180], "start": 0.0, "end": None}],
           "checks": {"text_overlays": {"status": "measured"}, "static_graphics": {"status": "measured"}}}
    (root / "warehouse/overlays").mkdir(parents=True, exist_ok=True)
    (root / f"warehouse/overlays/{plan['sources'][0]['sha256']}.json").write_text(json.dumps(doc))
    p = _prod(plan)
    assert "clean_uncovered" in codes(run(root, p), "error")
    p["sources"][0]["clean"] = {"crop": None, "delogo": [{"x": 148, "y": 78, "w": 34, "h": 20}], "inpaint": [], "blur": []}
    assert "clean_uncovered" not in codes(run(root, p))


# ----------------------------------------------------------------------------- presence.*
def test_presence_keys_compare_plan_with_reference(root, plan):
    plan["timeline"][0]["zoom"] = {"center": [160, 90]}
    iss = run(root, plan)
    assert "presence_unmeasured" in codes(iss, "warn")
    set_preset(root, "presence.zoom", "absent")
    set_preset(root, "presence.intentional_silence", "present")
    iss = run(root, plan)
    assert "presence_absent_used" in codes(iss, "warn")
    assert "presence.intentional_silence" in {i["where"] for i in iss if i["code"] == "presence_present_unused"}
    assert "presence_absent_used" in codes(run(root, _prod(plan)), "error")
