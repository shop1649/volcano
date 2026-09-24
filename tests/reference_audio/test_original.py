"""Speech presence, BGM ducking and intentional silences on SYNTHETIC mixes with known truth."""
from __future__ import annotations

import shutil

import pytest

import synthref as S
from .conftest import PRESET, no_abs_paths
from shortkit.reference import audio_bgm, audio_original as O, separation


@pytest.mark.slow
@pytest.mark.parametrize("vid", ["synv1", "synv2", "synv3", "synv4"])
def test_ducking_depth_attack_release(project_env, vid):
    tr = project_env["truths"][vid]["bgm"]
    dk = project_env["results"][vid]["original"]["ducking"]
    assert dk["presence"] == "present"
    assert abs(dk["depth_db"]["p50"] - tr["duck_db"]) <= 1.5          # acceptance: within 1.5 dB
    assert abs(dk["attack_s"]["p50"] - tr["attack_s"]) <= 0.06
    assert abs(dk["release_s"]["p50"] - tr["release_s"]) <= 0.06
    assert abs(dk["lead_s"]["p50"]) <= 0.05


@pytest.mark.slow
@pytest.mark.parametrize("vid", ["synv1", "synv2", "synv3", "synv4"])
def test_speech_segments(project_env, vid):
    truth = project_env["truths"][vid]["speech"]
    o = project_env["results"][vid]["original"]
    assert o["speech"]["presence"] == "present" and o["original_audio"]["presence"] == "present"
    segs = o["speech"]["segments"]
    assert len(segs) == len(truth)
    for s, t in zip(segs, truth):
        assert abs(s["start"] - t["start"]) <= 0.1 and abs(s["end"] - t["end"]) <= 0.1
    assert not no_abs_paths(o, project_env["root"])


@pytest.mark.slow
def test_intentional_silence_found(project_env):
    for vid in ("synv1", "synv3"):
        tr = project_env["truths"][vid]["silence"]
        items = project_env["results"][vid]["original"]["silences"]["items"]
        assert len(items) == 1
        s = items[0]
        assert s["bgm_cut"] is True
        assert abs(s["start"] - tr["start"]) <= 0.05 and abs(s["end"] - tr["end"]) <= 0.05
    for vid in ("synv2", "synv4"):
        assert project_env["results"][vid]["original"]["silences"]["items"] == []


@pytest.mark.slow
def test_no_ducking_is_reported_absent(project_env, tmp_path):
    """Speech over BGM without any dip -> ducking 'absent' (measured), not 'unmeasured'."""
    spec = S.VideoSpec("synnd", bgm_file="bed_b.wav", bgm_offset=12.0, bgm_gain_db=-13.0,
                       speech=[("speech_01", 5.0, -3.0)], duck_db=0.0, sfx=[("pop", 2.0, -8.0)], dur=14.0)
    d = S.build(spec, project_env["lib"], project_env["bank"], tmp_path)
    vp = project_env["root"] / "presets" / PRESET / "reference" / "videos" / "synnd.wav"
    S._write(vp, d["mix"])
    project_env["oracle"].add(vp, d)
    st = separation.separate_reference(PRESET, "synnd", separator=project_env["oracle"])
    audio_bgm.analyze_bgm(PRESET, "synnd", stems=st)
    o = O.analyze_original(PRESET, "synnd", stems=st)
    assert o["ducking"]["presence"] == "absent"
    assert abs(o["ducking"]["depth_db"]["p50"]) <= 1.0


@pytest.mark.slow
def test_no_vocals_stem_uses_residual_heuristic(project_env, tmp_path):
    """Without a vocals stem (demucs unavailable) speech is found on mix - aligned clean BGM,
    labelled low confidence; ducking is still measured from the BGM gain curve."""
    spec = S.DEFAULT_SPECS[1]                                           # synv2
    d = S.build(spec, project_env["lib"], project_env["bank"], tmp_path)
    vp = project_env["root"] / "presets" / PRESET / "reference" / "videos" / "synv2ns.wav"
    S._write(vp, d["mix"])
    shutil.rmtree(separation.stems_dir(PRESET, "synv2ns"), ignore_errors=True)
    b = audio_bgm.analyze_bgm(PRESET, "synv2ns")
    assert b["status"] == "measured" and b["signal"].startswith("mix (")
    o = O.analyze_original(PRESET, "synv2ns")
    assert o["speech"]["confidence"] == "low"
    segs = o["speech"]["segments"]
    t = d["truth"]["speech"][0]
    assert any(abs(s["start"] - t["start"]) <= 0.25 and abs(s["end"] - t["end"]) <= 0.35 for s in segs), segs
    assert o["ducking"]["presence"] == "present"
    assert abs(o["ducking"]["depth_db"]["p50"] - spec.duck_db) <= 1.5


def test_missing_media_is_unmeasured(tmp_project):
    o = O.analyze_original(PRESET, "nothing_here")
    assert o["status"] == "unmeasured"
    assert o["ducking"]["presence"] == "unmeasured" and o["speech"]["presence"] == "unmeasured"


@pytest.mark.slow
def test_aggregate_measurements(project_env):
    """measurements/audio.json from the SYNTHETIC videos: evidence -> value, overall + by_format."""
    import json

    r = O.aggregate_measurements(PRESET, ["synv1", "synv2", "synv3", "synv4"])
    items = {i["key"]: i for i in r["items"]}
    d = items["audio.ducking.depth_db"]
    assert d["status"] == "measured" and d["overall"]["n"] == 5 and set(d["by_format"]) == {"F1", "F2"}
    assert 8.0 - 1.5 <= d["value"] <= 10.0 + 1.5
    assert all({"video_id", "t", "value"} <= set(e) for e in d["evidence"])
    tid = items["audio.bgm.track_id"]
    assert tid["status"] == "measured" and tid["overall"]["n"] == 4
    assert items["audio.bgm.tempo_ratio"]["status"] == "measured"
    assert items["audio.bgm.gain_db"]["status"] == "measured"
    saved = json.loads((project_env["root"] / "presets" / PRESET / "measurements" / "audio.json").read_text())
    assert saved["schema"] == "shortkit.measurement/1" and saved["group"] == "audio"
    assert not no_abs_paths(saved, project_env["root"])


def test_aggregate_measurements_empty_is_unmeasured(tmp_project):
    r = O.aggregate_measurements(PRESET)
    assert r["items"] and all(i["status"] == "unmeasured" and i["blocker"] for i in r["items"])
