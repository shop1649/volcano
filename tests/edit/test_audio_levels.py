"""Gain semantics + safety limiter: levels are AT FINAL PROGRAM LOUDNESS, the BGM is never limited,
the foreground (SFX + kept originals) is limited by at most audio.loudness.max_limiter_db, and when
more would be needed the global gain drops and the LUFS shortfall is reported (synthetic signals)."""
from __future__ import annotations

import json
import math

import numpy as np
import pytest

from .conftest import load_preset, set_preset, write_plan

SR = 48000


def _sine(f, amp, n, sr=SR):
    t = np.arange(n) / sr
    x = amp * np.sin(2 * np.pi * f * t)
    return np.stack([x, x], axis=1).astype(np.float32)


def test_limiter_gain_cap_is_exact_bound():
    """g <= c / max(|b|, m|f| + sign(f) b): at that g the foreground needs exactly the allowed maximum."""
    from shortkit.edit.render import (_true_peak_db, _tp_points, db2lin, foreground_limiter_gain,
                                      limiter_gain_cap)

    n = SR
    bgm = _sine(220, 0.7, n)
    fg = np.zeros_like(bgm)
    fg[int(0.4 * SR):int(0.6 * SR)] = _sine(1000, 0.6, int(0.2 * SR))
    ceiling, max_lim = -2.0, 3.0
    bp, fp = _tp_points(bgm), _tp_points(fg)
    cap = limiter_gain_cap(bp, fp, ceiling, max_lim)
    assert cap < 1.0                                           # 0.7 + 0.6 does not fit under -2 dBFS
    k = foreground_limiter_gain(bgm * cap, fg * cap, ceiling)
    red = -20 * math.log10(float(k.min()))
    assert red == pytest.approx(max_lim, abs=0.02)             # binding, never more than the rule
    out = cap * bgm + cap * fg * k[:, None]
    assert _true_peak_db(out) <= ceiling + 0.05
    assert k[: int(0.3 * SR)].min() == 1.0 and k[int(0.75 * SR):].min() == 1.0
    # a slightly larger global gain would need more than max_lim
    k2 = foreground_limiter_gain(bgm * cap * db2lin(0.5), fg * cap * db2lin(0.5), ceiling)
    assert -20 * math.log10(float(k2.min())) > max_lim + 0.1


def test_plan_loudness_lowers_global_gain_instead_of_over_limiting(tmp_path):
    from shortkit.edit.render import Stems, _tp_points, limiter_gain_cap, plan_loudness

    n = 3 * SR
    bgm = _sine(220, 0.1, n)                                   # quiet bed -> normalisation wants a big boost
    sfx = np.zeros_like(bgm)
    sfx[SR:SR + SR // 50] = _sine(900, 0.8, SR // 50)           # short, hot SFX (20 ms): peaky, little loudness
    st = Stems(SR, bgm, np.zeros_like(bgm), sfx)
    lp = plan_loudness(st, -14.0, -2.0, 3.0, tmp_path)
    cap = limiter_gain_cap(_tp_points(bgm), _tp_points(sfx), -2.0, 3.0)
    assert lp["capped"] is True and lp["g"] == pytest.approx(cap) and lp["cap_reason"] == "foreground_limit"
    assert lp["wanted_gain_db"] > 20 * math.log10(lp["g"]) + 1.0
    assert -20 * math.log10(float(lp["k"].min())) <= 3.0 + 1e-3
    # without any foreground the bed alone is normalised (the cap only follows its own peak)
    lp2 = plan_loudness(Stems(SR, bgm, np.zeros_like(bgm), np.zeros_like(bgm)), -14.0, -2.0, 3.0, tmp_path)
    assert lp2["capped"] is False and float(lp2["k"].min()) == 1.0
    # a bed whose own peak is at the ceiling caps the gain by itself: reported as such, never limited
    z = np.zeros_like(bgm)
    lp3 = plan_loudness(Stems(SR, _sine(220, 0.3, n), z, z), 0.0, -2.0, 3.0, tmp_path)     # wants ~+14 dB
    assert lp3["capped"] is True and lp3["cap_reason"] == "bgm_peak"
    assert lp3["g"] * 0.3 == pytest.approx(10 ** (-2.0 / 20), rel=0.01)


CLICK = "assets/test/generated/edit_fixture/click_hot.wav"


def _loud_plan(root, plan):
    """BGM below the target at its plan level + a short hot click (synthetic, written here): the mix
    cannot reach -14 LUFS without limiting the click by more than 3 dB."""
    from shortkit.util.media import write_wav

    n = SR // 100                                              # 10 ms, 1 kHz, 0.9 peak
    write_wav(root / CLICK, (0.9 * np.sin(2 * np.pi * 1000 * np.arange(n) / SR)).astype(np.float32), SR)
    set_preset(root, "audio.bgm.gain_db", 10.0)
    plan["timeline"][2]["original_audio"] = {"keep": False}
    plan["sfx"][0]["file"] = CLICK
    plan["sfx"][0]["gain_db"] = 0.0
    write_plan(root, plan)


def test_pre_norm_stems_levels_and_no_side_effects(root, plan):
    from shortkit.edit.render import db2lin, pre_norm_stems
    from shortkit.edit.resolve import resolve_episode
    from shortkit.util.media import read_audio

    _loud_plan(root, plan)
    r = resolve_episode("t1")
    build = root / "episodes/t1/build"
    before = sorted(p.relative_to(root) for p in root.rglob("*"))
    st = pre_norm_stems(r)
    assert sorted(p.relative_to(root) for p in root.rglob("*")) == before          # nothing written
    s = r.audio.sfx[0]
    a, e = st.info["sfx_ranges"][s.id]
    ref = read_audio(root / s.path, sr=SR, mono=False)
    assert s.gain_db == 0.0 and np.abs(st.sfx[a:e]).max() == pytest.approx(np.abs(ref).max(), rel=1e-3)
    # BGM at gain_db (fades/envelope aside): the plan level, not a pre-normalisation guess
    b = read_audio(root / r.audio.bgm.path, sr=SR, mono=False, start=r.audio.bgm.section_start_s, duration=0.5)
    assert np.abs(st.bgm[SR // 10:SR // 2]).max() == pytest.approx(np.abs(b[SR // 10:]).max() * db2lin(10.0), rel=2e-2)
    assert not (build / "mix.wav").exists()


def test_mix_audio_reports_shortfall_and_writes_fg_gain(root, plan):
    from shortkit.edit import render
    from shortkit.edit.resolve import resolve_episode
    from shortkit.util.media import read_audio

    _loud_plan(root, plan)
    r = resolve_episode("t1")
    assert r.audio.max_limiter_db == load_preset().get("audio.loudness.max_limiter_db")
    build = root / "episodes/t1/build"
    rep = render.mix_audio(r, build)
    max_lim = r.audio.max_limiter_db
    assert rep["limiter"]["capped_by_limiter_rule"] is True
    assert rep["fg_limiter_max_reduction_db"] <= max_lim + 0.01
    assert rep["fg_limiter_max_reduction_db"] == pytest.approx(max_lim, abs=0.05)
    assert rep["bgm_limited"] is False and rep["limiter_max_reduction_db"] == 0.0
    lo = rep["loudness"]
    assert lo["status"] == "shortfall" and lo["shortfall_lu"] > r.audio.loudness_tolerance_lu
    assert rep["errors"] == [] and any("목표 음량" in w for w in rep["warnings"])      # test mode: warning
    # BGM stem = plan-level stem x one global gain (never modulated by any limiter)
    pre = render.pre_norm_stems(r)
    g = 10 ** ((rep["norm_gain_db"] + rep["final_trim_db"]) / 20)
    out_b = read_audio(build / "stems/bgm.wav", sr=SR, mono=False)
    n = min(len(out_b), len(pre.bgm))
    np.testing.assert_allclose(out_b[:n], np.clip(pre.bgm[:n] * g, -1, 1), atol=2e-4)
    # per-frame foreground gain for the MLT exporter
    fgj = json.loads((build / "fg_gain.json").read_text())
    assert fgj["frames"] == round(r.duration * r.canvas["fps"]) == len(fgj["gain_min"]) == len(fgj["gain_mean"])
    assert fgj["applies_to"] == ["originals", "sfx"] and fgj["norm_gain_db"] == rep["norm_gain_db"]
    assert min(fgj["gain_min"]) == pytest.approx(10 ** (-max_lim / 20), abs=2e-3)
    f_sfx = int(r.audio.sfx[0].t * r.canvas["fps"])
    assert min(fgj["gain_min"][f_sfx:f_sfx + 8]) < 1.0 and fgj["gain_min"][0] == 1.0
    # production: the same shortfall is an error
    r.mode = "production"
    rep2 = render.mix_audio(r, build)
    assert rep2["errors"] and not any("목표 음량" in w for w in rep2["warnings"])


def test_render_refuses_production_shortfall_before_video(root, plan, monkeypatch):
    from shortkit.edit import render
    from shortkit.edit.resolve import resolve_episode

    _loud_plan(root, plan)
    r = resolve_episode("t1")
    r.mode = "production"
    monkeypatch.setattr(render, "production_gate", lambda *a, **k: None)   # isolate the audio rule
    called = []
    monkeypatch.setattr(render, "render_video", lambda *a, **k: called.append(1))
    with pytest.raises(render.RenderError, match="오디오"):
        render.render(r)
    assert not called
    rep = json.loads((root / "episodes/t1/build/render_report.json").read_text())
    assert rep["status"] == "failed_audio" and rep["problems"]


def test_consistent_levels_need_only_a_small_trim(root, plan):
    """With levels that ARE at program loudness (bed ~ target, SFX peaks under the ceiling) the
    normalisation is a small trim and nothing is limited."""
    from shortkit.edit import render
    from shortkit.edit.resolve import resolve_episode
    from shortkit.util.media import lufs

    bed = lufs(root / "assets/test/generated/edit_fixture/bgm.wav")["integrated_lufs"]
    set_preset(root, "audio.bgm.gain_db", round(-14.0 - bed, 2))     # bed at the target when it is the program
    plan["timeline"][2]["original_audio"] = {"keep": False}
    plan["sfx"][0]["gain_db"] = 0.0
    write_plan(root, plan)
    r = resolve_episode("t1")
    rep = render.mix_audio(r, root / "episodes/t1/build")
    assert abs(rep["loudness"]["wanted_norm_gain_db"]) < 1.0
    assert rep["fg_limiter_max_reduction_db"] == 0.0 and rep["loudness"]["status"] == "ok"
    assert all(x["reduction_db"] == 0.0 for x in rep["sfx_limiting"])
    assert abs(rep["mix_wav"]["integrated_lufs"] + 14.0) <= r.audio.loudness_tolerance_lu


def test_old_ir_without_limiter_rule_is_refused(root, plan):
    from shortkit.edit import render
    from shortkit.edit.resolve import resolve_episode

    write_plan(root, plan)
    r = resolve_episode("t1")
    r.audio.max_limiter_db = None
    with pytest.raises(render.RenderError, match="resolve"):
        render.mix_audio(r, root / "episodes/t1/build")
