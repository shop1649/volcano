"""Audio measurement basis (snapshot members only, per-key basis), audio-analyze --set, channel-level audio
presence items, and SFX catalog status without Demucs (review findings S1-03, S4-10, S1-07, S4-05).

All media and per-video analysis files here are SYNTHETIC (sines / hand-written JSON)."""
from __future__ import annotations

import argparse

import numpy as np

import synthref as S
from shortkit.reference import audio_original as O
from shortkit.reference import sfx_catalog as C
from shortkit.util.jsonio import write_json

PRESET = "joshuamagazine"
A = "presets/joshuamagazine/analysis"


def _sine(root, vid, amp):
    sr = 48000
    t = np.arange(int(4 * sr)) / sr
    x = (amp * np.sin(2 * np.pi * 997.0 * t)).astype(np.float32)
    S._write(root / "presets" / PRESET / "reference" / "videos" / f"{vid}.wav", np.stack([x, x], 1), sr)


def test_audio_measure_uses_snapshot_members_only(tmp_project):
    """S1-03: a downloaded high-view video outside the snapshot (-6 dBFS sine) must not enter audio.json."""
    _sine(tmp_project, "member01", 0.1)          # -20 LUFS
    _sine(tmp_project, "hvold0001", 0.5)         # -6 LUFS, not a snapshot member
    S.write_snapshot(tmp_project, ["member01"])
    r = O.aggregate_measurements(PRESET)
    assert r["videos"] == ["member01"]
    assert r["basis"]["excluded_non_snapshot"] == ["hvold0001"]
    lu = {i["key"]: i for i in r["items"]}["audio.loudness.integrated_lufs"]
    assert lu["overall"]["n"] == 1 and abs(lu["value"] + 20.0) <= 0.3
    # an explicit --videos list cannot smuggle it in either
    r2 = O.aggregate_measurements(PRESET, ["hvold0001"])
    assert r2["videos"] == [] and all(i["status"] == "unmeasured" for i in r2["items"])


def test_every_audio_item_records_its_basis(tmp_project):
    """S4-10: measurements/audio.json says which set and which per-video file each key rests on."""
    _sine(tmp_project, "member01", 0.1)
    S.write_snapshot(tmp_project, ["member01"])
    r = O.aggregate_measurements(PRESET)
    for it in r["items"]:
        b = it["basis"]
        assert b["set"].startswith("latest100") and b["source_files"] and b["videos_considered"] == 1, it["key"]
    lu = {i["key"]: i for i in r["items"]}["audio.loudness.integrated_lufs"]
    assert lu["basis"]["source_files"].endswith("loudness.json") and lu["basis"]["videos_with_data"] == 1
    assert "sfx_catalog_latest_n" in r["basis"]["sfx_catalog_basis"]


def _write_audio(root, vid, bgm, orig_audio, ducking, silences, sil_status="measured", sfx_sil=False):
    d = root / A / vid / "audio"
    # music detected but not identified against the clean library: presence only, no match
    write_json(d / "bgm.json", {"video_id": vid, "status": "unmeasured", "presence": bgm, "label": S.SYNTHETIC_LABEL,
                                "blocker": "SYNTHETIC: 라이브러리 미일치"})
    write_json(d / "original.json", {
        "video_id": vid, "status": "measured", "label": S.SYNTHETIC_LABEL,
        "original_audio": {"presence": orig_audio, "segments": [{"start": 4.0, "end": 5.0}] if orig_audio == "present" else []},
        "ducking": {"presence": ducking, "per_segment": [{"start": 4.1, "end": 5.0}] if ducking == "present" else []},
        "silences": {"status": sil_status, "items": silences}})
    write_json(d / "sfx_events.json", {"video_id": vid, "status": "measured", "label": S.SYNTHETIC_LABEL,
                                       "events": [{"t": 9.0, "dur": 0.5, "class": "intentional_silence", "fp": None}]
                                       if sfx_sil else []})


def test_audio_presence_items(tmp_project):
    """S1-07: presence.{bgm, original_audio, ducking, intentional_silence}: tri-state with counts per format."""
    ids = ["a1", "a2", "a3"]
    S.write_snapshot(tmp_project, ids)
    write_json(tmp_project / "presets" / PRESET / "formats.yaml", {"status": "measured",
                                                                   "assignments": {"a1": "F1", "a2": "F1", "a3": "F2"}})
    _write_audio(tmp_project, "a1", "present", "present", "present", [], sfx_sil=True)
    _write_audio(tmp_project, "a2", "present", "absent", "absent", [{"start": 3.0, "dur": 0.5, "bgm_cut": False}])
    _write_audio(tmp_project, "a3", "unmeasured", "unmeasured", "unmeasured",
                 [{"start": 3.0, "dur": 0.5, "bgm_cut": None}])
    r = O.aggregate_measurements(PRESET, ids)
    it = {i["key"]: i for i in r["items"]}
    b = it["presence.bgm"]
    assert b["status"] == "measured" and b["value"] == "present"
    assert b["overall"] == {"n": 2, "n_present": 2, "n_absent": 0, "n_unmeasured": 1, "share": 1.0, "value": "present"}
    assert b["by_format"]["F2"]["n"] == 0 and b["by_format"]["F2"]["value"] is None
    assert b["evidence"][0]["video_id"] == "a1" and b["evidence"][0]["value"] == "present"
    oa = it["presence.original_audio"]
    assert oa["value"] == "present" and oa["overall"]["n_present"] == 1 and oa["overall"]["share"] == 0.5
    dk = it["presence.ducking"]
    assert dk["value"] == "present" and dk["evidence"][0]["t"] == 4.1
    si = it["presence.intentional_silence"]
    assert si["value"] == "present" and si["overall"]["n"] == 2 and si["overall"]["n_unmeasured"] == 1
    assert si["evidence"][0]["t"] == 9.0
    for k in O.PRESENCE_AUDIO_KEYS:
        assert it[k]["unit"] == "tri_state" and it[k]["basis"]["videos_with_data"] == it[k]["overall"]["n"]


def test_audio_presence_unmeasured_without_data(tmp_project):
    S.write_snapshot(tmp_project, ["a1"])
    r = O.aggregate_measurements(PRESET, ["a1"])
    for k in O.PRESENCE_AUDIO_KEYS:
        it = {i["key"]: i for i in r["items"]}[k]
        assert it["status"] == "unmeasured" and it["value"] is None and it["blocker"], k


def test_audio_analyze_set_covers_the_whole_snapshot(tmp_project, monkeypatch):
    """S4-10: `ref audio-analyze --set latest100` analyses every snapshot member (the catalog's --all only the
    newest sfx_catalog_latest_n = 50)."""
    from shortkit.reference import audio_bgm, audio_cli, audio_original, separation, sfx_events

    ids = [f"m{i:03d}" for i in range(60)]
    S.write_snapshot(tmp_project, ids)
    seen: list[str] = []
    monkeypatch.setattr(separation, "load_cached_stems", lambda *a, **k: None)
    monkeypatch.setattr(audio_bgm, "analyze_bgm", lambda p, v, **k: seen.append(v) or
                        {"video_id": v, "status": "unmeasured", "presence": "unmeasured", "blocker": "SYNTHETIC"})
    monkeypatch.setattr(audio_original, "load_context", lambda *a, **k: {})
    monkeypatch.setattr(audio_original, "analyze_original", lambda p, v, **k: {"video_id": v})
    monkeypatch.setattr(audio_original, "measure_loudness", lambda p, v, **k: {"status": "unmeasured", "blocker": "x"})
    monkeypatch.setattr(sfx_events, "analyze_sfx_events", lambda p, v, **k: {"video_id": v, "status": "unmeasured",
                                                                               "blocker": "x"})
    monkeypatch.setattr(audio_cli, "_print_original", lambda r: None)
    ap = argparse.ArgumentParser()
    audio_cli.register(ap.add_subparsers(dest="cmd"))
    a = ap.parse_args(["audio-analyze", "--set", "latest100", "--no-separate"])
    assert audio_cli.cmd_audio_analyze(a) == 0
    assert seen == ids
    seen.clear()
    a = ap.parse_args(["audio-analyze", "--all", "--no-separate"])
    audio_cli.cmd_audio_analyze(a)
    assert len(seen) == 50


def test_catalog_without_demucs_is_unmeasured(tmp_project):
    """S4-05: per-video files whose speech intervals could not be measured (no vocals stem) make the catalog
    unmeasured with the Demucs blocker, even when every target video was analysed."""
    S.write_snapshot(tmp_project, ["x1", "x2"])
    for v in ("x1", "x2"):
        write_json(tmp_project / A / v / "audio" / "sfx_events.json", {
            "video_id": v, "status": "partial", "blocker": "Demucs 분리 없음", "label": S.SYNTHETIC_LABEL,
            "separator": {"status": "unmeasured", "blocker": "torch 미설치"},
            "unmeasured_coverage": {"intervals": [[2.0, 4.0]], "n_candidates": 3}, "events": []})
    cat = C.build_catalog(PRESET, video_ids=["x1", "x2"])
    assert cat["basis"]["n_videos"] == 2 and cat["basis"]["missing"] == []
    assert cat["status"] == "unmeasured" and "Demucs" in cat["blocker"] and cat["counts_are_lower_bounds"] is True
    assert cat["basis"]["videos_with_unmeasured_intervals"] == ["x1", "x2"]
