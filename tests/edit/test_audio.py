"""Audio plan: ducking ONLY under kept original audio, intentional silences, limiter never ducks BGM."""
from __future__ import annotations

import numpy as np
import pytest

from conftest import load_preset, write_plan


def test_envelope_ducks_only_kept_ranges():
    from shortkit.edit.audio import build_envelope, envelope_db_at

    env = build_envelope(10.0, [(3.0, 4.0)], 10.0, 0.1, 0.3, [], 0.05)
    assert envelope_db_at(env, 1.0) == 0.0
    assert envelope_db_at(env, 2.95) == pytest.approx(-5.0)            # half-way through the attack
    assert envelope_db_at(env, 3.5) == pytest.approx(-10.0)
    assert envelope_db_at(env, 4.15) == pytest.approx(-5.0)            # release
    assert envelope_db_at(env, 4.3) == 0.0 and envelope_db_at(env, 9.0) == 0.0


def test_no_kept_audio_means_flat_envelope():
    from shortkit.edit.audio import build_envelope

    env = build_envelope(10.0, [], 10.0, 0.1, 0.3, [], 0.05)
    assert all(v == 0.0 for _, v in env)


def test_silence_mutes_with_fade():
    from shortkit.edit.audio import SILENCE_DB, build_envelope, envelope_db_at
    from shortkit.edit.render import envelope_gain

    env = build_envelope(5.0, [], 10.0, 0.1, 0.3, [(2.0, 2.5)], 0.05)
    assert envelope_db_at(env, 2.2) == SILENCE_DB and envelope_db_at(env, 1.9) == 0.0
    g = envelope_gain(env, 5 * 1000, 1000)
    assert g[2100] == 0.0 and g[2400] == 0.0 and g[1900] == 1.0 and 0 < g[1975] < 1


def test_close_ranges_merge_instead_of_pumping():
    from shortkit.edit.audio import build_envelope, envelope_db_at

    env = build_envelope(10.0, [(3.0, 4.0), (4.2, 5.0)], 10.0, 0.1, 0.3, [], 0.05)
    assert envelope_db_at(env, 4.1) == pytest.approx(-10.0)


def test_audio_plan_from_plan(root, plan):
    """Kept original range -> duck range in OUTPUT time; SFX and cuts never create ducking."""
    from shortkit.edit.resolve import resolve_context

    plan["timeline"][2]["original_audio"] = {"keep": False}
    plan["timeline"][1]["original_audio"] = {"keep": True, "reason": "말하는 사람", "ranges": [[2.8, 3.3]]}
    plan["bgm"]["silences"] = [{"start": 0.5, "end": 0.8, "reason": "강조"}]
    write_plan(root, plan)
    ctx = resolve_context(plan, load_preset())
    a = ctx.resolved.audio
    assert [(o.out_start, o.out_end) for o in a.originals] == [(pytest.approx(2.3), pytest.approx(2.8))]
    assert a.bgm.duck_ranges == [(pytest.approx(2.3), pytest.approx(2.8))]
    from shortkit.edit.audio import envelope_db_at

    # around the SFX (t=1.0) and every cut boundary the BGM is not ducked
    for t in (1.0, 1.05, 2.0, 3.25, 3.5):
        assert envelope_db_at(a.bgm.envelope, t) == 0.0, t
    assert envelope_db_at(a.bgm.envelope, 2.5) == pytest.approx(-load_preset().get("audio.ducking.depth_db"))
    assert envelope_db_at(a.bgm.envelope, 0.6) <= -119
    pr = load_preset()
    assert a.target_lufs == pr.get("audio.loudness.integrated_lufs")
    assert a.sfx[0].gain_db == pr.get("audio.sfx.gain_db_default")


def test_original_range_split_by_mid_freeze(root, plan):
    from shortkit.edit.resolve import resolve_context

    plan["timeline"][1]["freeze"] = {"at": "src_t", "src_t": 3.0, "hold": 0.5}
    plan["timeline"][1]["original_audio"] = {"keep": True, "reason": "대사", "ranges": [[2.6, 3.4]]}
    write_plan(root, plan)
    o = resolve_context(plan, load_preset()).resolved.audio.originals
    assert [(round(x.out_start, 3), round(x.out_end, 3)) for x in o] == [(2.1, 2.5), (3.0, 3.4)]


def test_foreground_limiter_never_touches_bgm():
    from shortkit.edit.render import _true_peak_db, foreground_limiter_gain

    sr = 48000
    t = np.arange(sr) / sr
    bgm = np.stack([0.2 * np.sin(2 * np.pi * 220 * t)] * 2, axis=1)
    fg = np.zeros_like(bgm)
    fg[20000:22000] = 0.95                      # hot SFX transient
    k = foreground_limiter_gain(bgm, fg, -1.0)
    out = bgm + fg * k[:, None]
    assert _true_peak_db(out) <= -1.0 + 0.05
    assert k[:15000].min() == 1.0 and k[27000:].min() == 1.0
    np.testing.assert_array_equal(out[:15000], bgm[:15000])     # BGM untouched outside the SFX


def test_sfxmap_lookup_statuses(root):
    from shortkit.edit import sfxmap

    pr = load_preset()
    assert sfxmap.lookup(pr, "whoosh")["status"] == "unmeasured"        # not in the map -> never "have"
    p = root / "presets/joshuamagazine/sfx_map.yaml"
    (root / "assets/library/sfx").mkdir(parents=True)
    (root / "assets/library/sfx/w.wav").write_bytes(b"RIFF")
    p.write_text("preset_id: joshuamagazine-v1\nlibrary_root: assets/library/sfx\ntypes:\n"
                 "  whoosh: {status: have, file: w.wav}\n  boom: {status: none}\n")
    assert sfxmap.lookup(pr, "whoosh") ["file"] == "assets/library/sfx/w.wav"
    assert sfxmap.lookup(pr, "boom")["status"] == "none" and sfxmap.lookup(pr, "boom")["file"] is None


def test_bgm_track_id_lookup_in_music_library(root, plan):
    """preset audio.bgm.track_id -> assets/library/music/index.yaml (synthetic index for the test)."""
    import shutil

    from conftest import set_preset
    from shortkit.edit.resolve import resolve_context

    lib = root / "assets/library/music"
    lib.mkdir(parents=True)
    shutil.copy(root / "assets/test/generated/edit_fixture/bgm.wav", lib / "clean_track.wav")
    (lib / "index.yaml").write_text("tracks:\n  - {id: trk1, path: clean_track.wav, title: 합성, version: original}\n")
    set_preset(root, "audio.bgm.track_id", "trk1")
    plan["bgm"] = {"enabled": True, "path": None, "silences": []}
    write_plan(root, plan)
    b = resolve_context(plan, load_preset()).resolved.audio.bgm
    assert b.path == "assets/library/music/clean_track.wav" and b.track_id == "trk1"
    set_preset(root, "audio.bgm.track_id", "missing")
    ctx = resolve_context(plan, load_preset())
    assert "bgm_track_missing" in {i["code"] for i in ctx.errors}
