"""Renderer audio conventions fixed in the qa-loop round (synthetic signals, generated here):

* ``render.tempo_stretch`` keeps read_audio's channel convention for MONO input (unity on both channels,
  not ffmpeg's -3 dB upmix);
* the unused ``render.BLUR_SIGMA_FRAC`` alias is gone (the blur strength is render.clean.blur_sigma_ratio);
* ``audio.original.keep_gain_db`` = kept speech loudness relative to the programme (LU): applied gain
  = T + keep_gain_db - L_src (per clip, per source when a clip keeps < KEPT_LEVEL_MIN_S, never a guess);
* ``audio.bgm.loop``: music shorter than the episode loops back to section_start with an equal-power
  crossfade of ``audio.bgm.loop_xfade_s`` (read through the preset, clear error when missing); without
  loop the short music is still refused/warned as before.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
import yaml

from .conftest import M, codes, load_preset, set_preset, write_plan

SR = 48000


def _ff(*args):
    import subprocess

    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", *map(str, args)], check=True)


def _rms_db(x):
    return 10 * math.log10(float((np.asarray(x, np.float64) ** 2).mean()) + 1e-20)


# ----------------------------------------------------------------------------- (a) tempo_stretch, (b) alias
def test_tempo_stretch_mono_input_keeps_unity_on_both_channels(tmp_path):
    from shortkit.edit.render import tempo_stretch
    from shortkit.util.media import read_audio

    src = tmp_path / "mono.wav"
    _ff("-f", "lavfi", "-i", f"sine=f=330:d=3:sample_rate={SR}", "-af", "volume=0.5", "-ac", "1", src)
    dst = tmp_path / "out.wav"
    tempo_stretch(src, 1.1, dst, SR)
    x = read_audio(src, sr=SR, mono=True)
    y = read_audio(dst, sr=SR, mono=False)
    assert y.shape[1] == 2
    core = slice(int(0.3 * SR), int(2.4 * SR))          # skip the filter's edges
    for ch in (0, 1):
        assert _rms_db(y[core, ch]) == pytest.approx(_rms_db(x[int(0.3 * SR):int(2.6 * SR)]), abs=0.3)   # not -3 dB


def test_blur_sigma_frac_alias_removed():
    from shortkit.edit import render

    assert not hasattr(render, "BLUR_SIGMA_FRAC")


# ----------------------------------------------------------------------------- (c) keep_gain_db semantics
def _speech_source(root, name="talk.mp4", dur=6.0):
    """Video with a 1.5 s tone burst at 1.0 s (the 'line') over a quiet bed (synthetic)."""
    p = root / M / name
    _ff("-f", "lavfi", "-i", f"testsrc2=s=320x180:r=30:d={dur}", "-f", "lavfi",
        "-i", f"sine=f=500:d={dur}:sample_rate={SR}", "-filter_complex",
        "[1:a]volume='if(between(t,1,2.5),0.4,0.02)':eval=frame[a]", "-map", "0:v", "-map", "[a]",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "1", p)
    return f"{M}/{name}"


def _src_lufs(root, rel, a, b):
    from shortkit.util.media import lufs, read_audio, write_wav

    x = read_audio(root / rel, sr=SR, mono=False, start=a, duration=b - a)
    f = root / "seg.wav"
    write_wav(f, x, SR)
    return lufs(f)["integrated_lufs"]


def test_keep_gain_db_is_level_relative_to_programme(root, plan):
    from shortkit.edit.resolve import resolve_context
    from tests.edit.conftest import sha

    rel = _speech_source(root)

    plan["sources"][0].update(path=rel, sha256=sha(root / rel))
    plan["timeline"][0]["original_audio"] = {"keep": True, "reason": "대사", "ranges": [[1.0, 2.5]]}
    write_plan(root, plan)
    pr = load_preset()
    T = float(pr.peek("audio.loudness.integrated_lufs"))
    keep = float(pr.peek("audio.original.keep_gain_db"))
    ctx = resolve_context(plan, pr)
    (o,) = ctx.resolved.audio.originals
    L_src = _src_lufs(root, rel, 1.0, 2.5)
    assert o.gain_db == pytest.approx(T + keep - L_src, abs=0.05)
    # a plan override is in the same unit (LU re programme)
    plan["timeline"][0]["original_audio"]["gain_db"] = -6.0
    write_plan(root, plan)
    (o2,) = resolve_context(plan, load_preset()).resolved.audio.originals
    assert o2.gain_db == pytest.approx(T - 6.0 - L_src, abs=0.05)
    # the preset key changes it by exactly its difference
    set_preset(root, "audio.original.keep_gain_db", keep - 4.0)
    plan["timeline"][0]["original_audio"].pop("gain_db")
    (o3,) = resolve_context(plan, load_preset()).resolved.audio.originals
    assert o3.gain_db == pytest.approx(o.gain_db - 4.0, abs=0.01)


def test_keep_gain_short_clip_uses_source_level_else_error(root, plan):
    """A clip keeping < KEPT_LEVEL_MIN_S is levelled from everything kept from its source; with nothing
    measurable the gain is NOT guessed: resolve reports original_level_unmeasured."""
    from shortkit.edit.audio import KEPT_LEVEL_MIN_S
    from shortkit.edit.resolve import resolve_context
    from tests.edit.conftest import sha

    rel = _speech_source(root)
    plan["sources"][0].update(path=rel, sha256=sha(root / rel))
    plan["timeline"][0]["original_audio"] = {"keep": True, "reason": "대사", "ranges": [[1.0, 1.0 + KEPT_LEVEL_MIN_S / 2]]}
    write_plan(root, plan)
    c = resolve_context(plan, load_preset())                 # never raises: plan problems become issues
    assert "original_level_unmeasured" in codes(c.issues, "error") and not c.resolved.audio.originals
    # the second segment of the same source keeps enough: the short clip is levelled per source
    # (everything kept from that file), the long one per clip
    plan["timeline"][1]["original_audio"] = {"keep": True, "reason": "대사", "ranges": [[2.5, 3.5]]}
    write_plan(root, plan)
    pr = load_preset()
    r = resolve_context(plan, pr).resolved
    o1, o2 = sorted(r.audio.originals, key=lambda o: o.out_start)
    T, keep = float(pr.peek("audio.loudness.integrated_lufs")), float(pr.peek("audio.original.keep_gain_db"))
    from shortkit.util.media import lufs, read_audio, write_wav

    pieces = [read_audio(root / rel, sr=SR, mono=False, start=a, duration=b - a)
              for a, b in ((1.0, 1.0 + KEPT_LEVEL_MIN_S / 2), (2.5, 3.5))]
    write_wav(root / "both.wav", np.concatenate(pieces), SR)
    assert o1.gain_db == pytest.approx(T + keep - lufs(root / "both.wav")["integrated_lufs"], abs=0.05)
    assert o2.gain_db == pytest.approx(T + keep - _src_lufs(root, rel, 2.5, 3.5), abs=0.05)


# ----------------------------------------------------------------------------- (d) BGM loop
def test_loop_fill_equal_power_and_returns_to_section_start():
    from shortkit.edit.render import loop_fill

    rng = np.random.default_rng(3)
    seg = rng.standard_normal((1000, 2)).astype(np.float32)
    nx = 100
    out, starts = loop_fill(seg, 2600, nx)
    P = len(seg) - nx
    assert starts == [P, 2 * P, 3 * P][:len(starts)] and starts[0] == P
    assert np.allclose(out[:P], seg[:P])                                   # copy 0 untouched before the loop
    assert np.allclose(out[P + nx:2 * P], seg[nx:P])                        # repeat = section start again
    th = (np.arange(nx) + 0.5) / nx * (math.pi / 2)
    assert np.allclose(np.cos(th) ** 2 + np.sin(th) ** 2, 1.0)             # equal-power law
    assert np.allclose(out[P:P + nx], seg[P:] * np.cos(th)[:, None] + seg[:nx] * np.sin(th)[:, None], atol=1e-6)
    with pytest.raises(Exception):
        loop_fill(seg, 3000, 600)                                           # crossfade longer than half the piece


def _short_bgm(root, dur=3.0):
    p = root / M / "bgm_short.wav"
    _ff("-f", "lavfi", "-i", f"sine=f=220:d={dur}:sample_rate={SR}", "-af", "volume=0.3", "-ac", "2", p)
    return f"{M}/bgm_short.wav"


def test_bgm_loop_true_loops_in_stems_and_false_keeps_refusing(root, plan):
    from shortkit.edit.render import pre_norm_stems
    from shortkit.edit.resolve import resolve_context

    plan["bgm"]["path"] = _short_bgm(root)
    plan["bgm"]["section_start_s"] = 1.0                       # 2.0 s of music for a 5.75 s episode
    write_plan(root, plan)
    # loop false: as before -- warning in test mode, error in production
    r = resolve_context(plan, load_preset())
    assert "bgm_too_short" in codes(r.issues, "warn") and r.resolved.audio.bgm.loop is False
    st = pre_norm_stems(r.resolved)
    assert any("부족" in w for w in st.info["warnings"]) and "bgm_loop" not in st.info
    prod = dict(plan, mode="production")
    assert "bgm_too_short" in codes(resolve_context(prod, load_preset()).issues, "error")
    # loop true: resolve accepts (warning names the loop), the stem repeats the music from section_start
    set_preset(root, "audio.bgm.loop", True)
    pr = load_preset()
    r2 = resolve_context(plan, pr)
    assert "bgm_loop" in codes(r2.issues, "warn") and not codes(r2.issues, "error")
    st2 = pre_norm_stems(r2.resolved, pr)
    lp = st2.info["bgm_loop"]
    xf = float(pr.peek("audio.bgm.loop_xfade_s"))
    assert lp["xfade_s"] == xf and lp["segment_s"] == pytest.approx(2.0, abs=0.01)
    assert lp["loop_starts_out_s"][0] == pytest.approx(2.0 - xf, abs=1e-3)
    assert "audio.bgm.loop_xfade_s" in pr.log.to_dict()                    # read through the preset (traced)
    # the music never stops: no silent gap at the loop points
    b = np.abs(st2.bgm[:, 0])
    win = int(0.02 * SR)
    env = np.array([b[i:i + win].max() for i in range(0, len(b) - win, win)])
    assert env[int(0.2 * SR / win):int(5.0 * SR / win)].min() > 0.1 * env.max()


def test_bgm_loop_without_xfade_key_is_a_clear_error(root, plan):
    from shortkit.edit.render import RenderError, bgm_loop_xfade
    from shortkit.edit.resolve import resolve_context

    p = root / "presets/joshuamagazine/preset.yaml"
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    d["audio"]["bgm"].pop("loop_xfade_s", None)
    d["audio"]["bgm"]["loop"] = True
    p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")
    plan["bgm"]["path"] = _short_bgm(root)
    plan["bgm"]["section_start_s"] = 1.0
    write_plan(root, plan)
    assert "bgm_loop_xfade_missing" in codes(resolve_context(plan, load_preset()).issues, "error")
    with pytest.raises(RenderError, match="loop_xfade_s"):
        bgm_loop_xfade(None, load_preset())


# ----------------------------------------------------------------------------- delivered true peak
def test_delivered_true_peak_is_verified_on_a_trial_aac_encode(root, plan):
    """The PCM mix is kept under ceiling - TP_MARGIN_DB, but AAC can overshoot more (content-dependent; an
    abrupt start inside the first AAC frame measured +2 dB).  The renderer encodes a trial AAC, decodes it and
    corrects until the delivered true peak meets audio.loudness.true_peak_db."""
    from shortkit.edit import render
    from shortkit.edit.resolve import resolve_context
    from shortkit.util.media import write_wav

    n = int(8.0 * SR)
    t = np.arange(n) / SR
    rng = np.random.default_rng(0)
    # a bed that starts at full level with a strong offset (like test music_bed_a's right channel) + bright noise
    x = 0.45 * np.cos(2 * np.pi * 55 * t) + 0.25 * rng.standard_normal(n) * (1 + 0.5 * np.sin(2 * np.pi * 3 * t))
    bed = np.stack([x, 0.6 * x + 0.3], axis=1).astype(np.float32)
    write_wav(root / M / "bed_hot.wav", np.clip(bed, -1, 1), SR)
    plan["bgm"]["path"] = f"{M}/bed_hot.wav"
    plan["bgm"]["section_start_s"] = 0.0
    write_plan(root, plan)
    pr = load_preset()
    r = resolve_context(plan, pr).resolved
    build = root / "episodes/t1/build"
    build.mkdir(parents=True, exist_ok=True)
    rep = render.mix_audio(r, build, pr)
    et = rep["encoded_true_peak"]
    assert et["steps"][0]["step"] == "pcm"
    assert et["final_db"] <= float(pr.peek("audio.loudness.true_peak_db")) + 1e-6, et
    import tempfile
    from pathlib import Path

    from shortkit.util.media import read_audio

    mix = read_audio(build / "mix.wav", sr=SR, mono=False)
    with tempfile.TemporaryDirectory() as td:
        tp2, _ = render.encoded_true_peak(mix, SR, str(r.canvas["encode"]["audio_bitrate"]), Path(td))
    assert tp2 <= float(pr.peek("audio.loudness.true_peak_db")) + 0.1      # the written mix really encodes under it
