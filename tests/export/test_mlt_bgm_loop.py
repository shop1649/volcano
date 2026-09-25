"""Slow: the MLT project reproduces the master's BGM LOOP and START RAMP sample-wise (melt render vs the
master's own stem builder, SYNTHETIC IR over the repository's test music).

* bgm.loop with music shorter than the episode: the master (render.pre_norm_stems) repeats the music from
  section_start with render.loop_fill (equal-power cos/sin crossfade at every loop point); the exporter
  pre-renders exactly that (loop points are not on the frame grid) and must say so in its decisions.
* the master's 1024-sample linear start ramp (build/fg_gain.json start_ramp_samples, AAC abrupt-start
  guard) becomes a tractor avfilter.afade.

Negative controls: without the loop the melt render falls silent after the music ends, and without the
ramp the first 1024 samples are not faded -- both are caught by the same comparison."""
from __future__ import annotations

import json
import math
import shutil

import numpy as np
import pytest

import export_fixtures as ef
from shortkit.edit import verify_project

pytestmark = [pytest.mark.slow,
              pytest.mark.skipif(verify_project.find_melt() is None, reason="melt not installed")]

EID = "test-export-loop"
XF = 0.05                     # audio.bgm.loop_xfade_s of this synthetic test (the rule key the master reads)
RAMP = 1024
SR = 48000


class _Preset:
    """Stand-in exposing only the rule key render.bgm_loop_xfade reads (Preset.get semantics: KeyError)."""

    def get(self, key):
        if key == "audio.bgm.loop_xfade_s":
            return XF
        raise KeyError(key)


def _ir():
    r = ef.build_resolved(EID)
    b = r.audio.bgm
    b.section_start_s = 57.5                  # music_bed_a.wav is 60 s -> 2.5 s of music for a 5.7 s episode
    b.loop = True
    b.gain_db = -12.0
    b.envelope, b.duck_ranges, b.fade_in_s, b.fade_out_s = [], [], 0.0, 0.0
    r.audio.originals, r.audio.sfx = [], []    # BGM only: the comparison isolates the loop and the ramp
    return r


def _write_master_records(root, r, ramp: int):
    """build/render_report.json + fg_gain.json as render.mix_audio writes them (normalisation 0 dB here)."""
    from shortkit.edit.render import pre_norm_stems

    st = pre_norm_stems(r, _Preset())
    loop = st.info["bgm_loop"]
    fps = float(r.canvas["fps"])
    N = int(round(r.duration * fps))
    b = root / "episodes" / EID / "build"
    b.mkdir(parents=True, exist_ok=True)
    (b / "render_report.json").write_text(json.dumps({
        "schema": "shortkit.render_report/1", "episode_id": EID, "note": "synthetic test (tests/export)",
        "audio": {"norm_gain_db": 0.0, "final_trim_db": 0.0, "limiter_max_reduction_db": 0.0,
                  "fg_limiter_max_reduction_db": 0.0, "bgm": {**st.info["bgm"], "loop_applied": loop},
                  **({"start_ramp_samples": ramp} if ramp else {}),
                  "encoded_true_peak": {"final_db": -2.0, "ok": True}}}), encoding="utf-8")
    (b / "fg_gain.json").write_text(json.dumps({
        "schema": "shortkit.fg_gain/1", "episode_id": EID, "fps": fps, "frames": N, "sample_rate": SR,
        "applies_to": ["originals", "sfx"], "semantics": "synthetic test", "norm_gain_db": 0.0, "final_trim_db": 0.0,
        "max_limiter_db": 3.0, "max_reduction_db": 0.0, "gain_min": [1.0] * N, "gain_mean": [1.0] * N,
        "start_ramp_samples": ramp}), encoding="utf-8")
    master = st.bgm.astype(np.float64)
    if ramp:
        master[:ramp] *= np.linspace(0.0, 1.0, ramp, endpoint=False)[:, None]
    return master, loop


def _melt_audio(root, r, proj):
    from shortkit.util.media import read_audio

    wav = proj / "melt_audio.wav"
    verify_project.run_melt(proj / f"{EID}.mlt", ["-consumer", f"avformat:{wav.name}", "video_off=1", "vn=1",
                                                  "ar=48000", "ac=2", "acodec=pcm_f32le", "real_time=-1"], timeout=900)
    return read_audio(wav, sr=SR, mono=False).astype(np.float64)


def _export(root, r, ramp: int, *, no_loop: bool = False, monkeypatch=None):
    from shortkit.edit import export_mlt

    ef.write_ass(root, r)
    master, loop = _write_master_records(root, r, ramp)
    proj = root / "episodes" / EID / "project"
    shutil.rmtree(proj, ignore_errors=True)
    if no_loop:       # scoped: the root fixture's SHORTKIT_ROOT lives on the same monkeypatch
        with monkeypatch.context() as m:
            m.setattr(export_mlt.MltBuilder, "_bgm_loop", lambda self, src, offset: None)
            out, dec = export_mlt.export_with_decisions(r, proj)
    else:
        out, dec = export_mlt.export_with_decisions(r, proj)
    return master, loop, _melt_audio(root, r, proj), dec


def _err(a, b, s0=0, s1=None):
    n = min(len(a), len(b))
    s1 = n if s1 is None else min(s1, n)
    return float(np.abs(a[s0:s1] - b[s0:s1]).max())


def test_mlt_bgm_loop_and_start_ramp_match_the_master(root):
    r = _ir()
    master, loop, melt, dec = _export(root, r, RAMP)
    lp = dec["audio"]["bgm_loop"]
    assert lp["status"] == "있음" and lp["source"].endswith("render_report.json"), lp
    assert lp["repeats"] == loop["repeats"] == 2 and lp["matches_master_loop_starts"] is True
    assert lp["loop_starts_out_s"] == loop["loop_starts_out_s"]          # 2.45 s and 4.90 s
    assert dec["start_ramp"]["status"] == "있음" and dec["start_ramp"]["samples"] == RAMP
    assert any(p["kind"] == "bgm_loop" for p in dec["prerendered"])
    xml = (root / "episodes" / EID / "project" / f"{EID}.mlt").read_text(encoding="utf-8")
    assert "avfilter.afade" in xml and f'"av.nb_samples">{RAMP}<' in xml
    n = min(len(master), len(melt))
    assert n >= int(5.6 * SR)
    pk = float(np.abs(master).max())
    assert pk > 0.05
    # whole file, sample-wise: only 16-bit intermediates differ (loop wav, melt's s16 audio path);
    # measured on the build machine: max |diff| 5.6e-5 whole file, 3.8e-5 in each crossfade region
    assert _err(master, melt) < 3e-4, _err(master, melt)
    for t in loop["loop_starts_out_s"]:                                   # each equal-power crossfade region
        s = int(round(t * SR))
        assert _err(master, melt, s - 2400, s + int(XF * SR) + 2400) < 3e-4
    # the ramp: sample 0 silent, then a linear 0 -> 1 gain over RAMP samples (i / RAMP)
    assert abs(melt[0]).max() < 1e-4 and _err(master, melt, 0, RAMP) < 3e-4
    from shortkit.edit.render import pre_norm_stems

    raw = pre_norm_stems(r, _Preset()).bgm.astype(np.float64)
    for k in (256, 512, 768):
        ch = int(np.argmax(np.abs(raw[k])))
        assert abs(melt[k, ch] / raw[k, ch] - k / RAMP) < 0.01, (k, melt[k, ch] / raw[k, ch])


def test_negative_controls_without_loop_or_ramp(root, monkeypatch):
    r = _ir()
    master, loop, melt, _ = _export(root, r, RAMP, no_loop=True, monkeypatch=monkeypatch)
    after = int(round(2.6 * SR))                          # past the end of the 2.5 s of music
    assert float(np.sqrt((master[after:after + SR] ** 2).mean())) > 0.01
    assert _err(master, melt, after, after + SR) > 0.02  # melt: silence where the master loops
    master0, _, melt0, dec0 = _export(root, _ir(), 0)      # the master did NOT ramp -> no afade in the project
    assert dec0["start_ramp"]["status"] == "없음"
    ramped = master0.copy()
    ramped[:RAMP] *= np.linspace(0.0, 1.0, RAMP, endpoint=False)[:, None]
    assert _err(master0, melt0, 0, RAMP) < 1e-3          # unramped master == unramped project
    assert _err(ramped, melt0, 0, RAMP) > 10 * _err(master0, melt0, 0, RAMP) + 1e-4
    assert math.isclose(dec0["audio"]["bgm_loop"]["xfade_s"], XF)
