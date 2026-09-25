"""Regression tests for SFX-analysis defects found by the SYNTHETIC mockloop validation
(docs/validation/mockloop.md).  Signals are built here from the generated SFX set + synthetic noise."""
from __future__ import annotations

import numpy as np
import pytest

import synthref as S
from shortkit.reference import sfx_events as E


def _residual_bed(seed: int, n: int, level_db: float, beat: float = 3.0) -> np.ndarray:
    """A stand-in for mix residual after BGM subtraction: noise with drum-like transients every 230 ms."""
    rng = np.random.default_rng(seed)
    x = rng.standard_normal(n) * 0.2
    for k in range(0, n, int(0.23 * S.SR)):
        m = min(n - k, int(0.03 * S.SR))
        x[k:k + m] += beat * rng.standard_normal(m) * np.exp(-np.arange(m) / (0.006 * S.SR))
    x = x / (np.sqrt(np.mean(x ** 2)) + 1e-12) * 10 ** (level_db / 20)
    return x.astype(np.float32)


def _event_patch(sfx: np.ndarray, bed: np.ndarray, at: float) -> np.ndarray:
    x = bed.copy()
    i = int(at * S.SR)
    x[i:i + len(sfx)] += sfx
    evs, _ = E.detect_events(x, S.SR)
    ev = min(evs, key=lambda e: abs(e["t"] - at))
    assert abs(ev["t"] - at) <= 0.06, evs          # a slow-attack whoosh is picked up ~45 ms after its file start
    return E.fingerprint_clip(x, S.SR, ev["t"], ev["dur"])["patch"], ev


def _music_residual(offset_s: float, level_db: float, dur_s: float = 3.0) -> np.ndarray:
    """Imperfect BGM subtraction: a passage of the synthetic music bed left in the residual at level_db RMS."""
    from pathlib import Path

    from shortkit.reference.separation import load_mono

    f = Path(__file__).resolve().parents[2] / "assets/test/generated/music_bed_b.wav"
    if not f.is_file():
        pytest.skip("assets/test/generated missing: python -m shortkit testassets synth")
    x = load_mono(f, S.SR)[int(offset_s * S.SR):int((offset_s + dur_s) * S.SR)].astype(np.float64)
    return (x / (np.sqrt(np.mean(x ** 2)) + 1e-12) * 10 ** (level_db / 20)).astype(np.float32)


@pytest.mark.parametrize("name", ["pop", "ding"])
def test_same_sfx_over_different_residual_is_similar(name):
    """mockloop defect: the SAME pop.wav / ding.wav over different BGM passages scored 0.31-0.60 (catalog
    threshold 0.80) because the patch compared 80 dB of dynamic range and 0.4 s after a 0.12 s pop, i.e. mostly
    mix residual; they never formed a catalog type.  With music-bed residual at -35 dB the former fingerprint
    scored 0.77 / 0.77 here."""
    sfx = S.sfx_bank()[name] * 0.5
    pa, _ = _event_patch(sfx, _music_residual(5.0, -35.0), 1.0)
    pb, _ = _event_patch(sfx, _music_residual(23.0, -35.0), 1.0)
    sim = float(E.similarity_matrix([pa], [pb])[0, 0])
    assert sim >= 0.85, sim


def test_different_sfx_stay_apart():
    bank = S.sfx_bank()
    n = int(3.0 * S.SR)
    pa, _ = _event_patch(bank["pop"] * 0.5, _residual_bed(1, n, -38.0), 1.0)
    pb, _ = _event_patch(bank["ding"] * 0.5, _residual_bed(2, n, -38.0), 1.0)
    pc, _ = _event_patch(bank["whoosh"] * 0.5, _residual_bed(3, n, -38.0), 1.0)
    M = E.similarity_matrix([pa, pb, pc])
    assert max(M[0, 1], M[0, 2], M[1, 2]) < 0.8, M


def test_long_ding_over_residual_transients_is_one_event():
    """mockloop defect: residual transients in a 1.2 s ding's decaying tail passed the band-onset split
    (total energy -0.9 dB) and cut the ding into 2-3 events that then fell into different catalog types."""
    sfx = S.sfx_bank()["ding"] * 0.5
    x = _residual_bed(4, int(3.0 * S.SR), -45.0)      # the former split rule cut this ding into 5 events
    i = int(1.0 * S.SR)
    x[i:i + len(sfx)] += sfx
    evs, _ = E.detect_events(x, S.SR)
    inside = [e for e in evs if 0.95 <= e["t"] <= 2.1]
    assert len(inside) == 1, [(e["t"], e["dur"]) for e in inside]
    assert inside[0]["dur"] >= 0.6, inside[0]


def test_pop_right_after_a_ding_still_splits():
    bank = S.sfx_bank()
    x = _residual_bed(5, int(3.0 * S.SR), -45.0)
    for name, at in (("ding", 1.0), ("pop", 1.7)):
        s = bank[name] * 0.5
        i = int(at * S.SR)
        x[i:i + len(s)] += s
    evs, _ = E.detect_events(x, S.SR)
    assert any(abs(e["t"] - 1.0) <= 0.03 for e in evs) and any(abs(e["t"] - 1.7) <= 0.03 for e in evs), \
        [(e["t"], e["dur"]) for e in evs]


def test_faint_lead_in_does_not_move_the_onset():
    """mockloop defect: a -51 dB residual blip 60 ms before a -17 dB pop became the event onset (the pop
    then fingerprinted 12 frames late and formed its own catalog type; offset_to_event was 60 ms off)."""
    pop = S.sfx_bank()["pop"] * 0.5
    x = np.zeros(int(2.0 * S.SR), np.float32)
    rng = np.random.default_rng(9)
    i0 = int(0.94 * S.SR)
    x[i0:i0 + int(0.06 * S.SR)] += (rng.standard_normal(int(0.06 * S.SR)) * 10 ** (-48 / 20)).astype(np.float32)
    i = int(1.0 * S.SR)
    x[i:i + len(pop)] += pop
    evs, _ = E.detect_events(x, S.SR)
    ev = min(evs, key=lambda e: abs(e["t"] - 1.0))
    assert abs(ev["t"] - 1.0) <= 0.01, evs


def test_slow_attack_whoosh_onset_is_not_moved_to_its_peak():
    wh = S.sfx_bank()["whoosh"] * 0.5
    x = np.zeros(int(2.0 * S.SR), np.float32)
    i = int(1.0 * S.SR)
    x[i:i + len(wh)] += wh
    evs, _ = E.detect_events(x, S.SR)
    ev = min(evs, key=lambda e: abs(e["t"] - 1.0))
    assert ev["t"] <= 1.06, evs          # the whoosh peaks ~0.2 s after its file start


# ----------------------------------------------------------------- BGM transient residue (lossy codec)
def _hat_bed(n: int, sr: int, period: float = 0.625, level_db: float = -22.0, seed: int = 11):
    """BGM stand-in: a soft low pad + hi-hat bursts (4-11 kHz noise, 30 ms decay) every ``period`` s."""
    import scipy.signal as ss

    rng = np.random.default_rng(seed)
    t = np.arange(n) / sr
    x = 0.02 * np.sin(2 * np.pi * 110 * t)
    b, a = ss.butter(4, [4500 / (sr / 2), 0.95], "band")
    hats = []
    for k in np.arange(0.1, n / sr - 0.1, period):
        i = int(k * sr)
        m = int(0.03 * sr)
        burst = ss.lfilter(b, a, rng.standard_normal(m)) * np.exp(-np.arange(m) / (0.008 * sr))
        burst *= 10 ** (level_db / 20) / (np.abs(burst).max() + 1e-12)
        x[i:i + m] += burst
        hats.append(k)
    return x.astype(np.float32), hats


def test_codec_error_on_a_bgm_hihat_is_not_an_onsite_sound():
    """mockloop defect: in AAC the bed's hi-hats come back slightly different from the clean library file, so
    after subtraction 4.5-11 kHz bursts ~10 dB under each hi-hat remained; five of them passed the mix checks
    (mix share 0.2-0.5, not a scaled copy: |corr| ~0.1) and became 'onsite' sound types in 4 of 5 videos.
    A residual event that starts with a BGM transient in its own bands and is not louder than it there is now
    rejected ('bgm_transient_residue'); a real knock between hi-hats, or louder than the hi-hat, is kept."""
    import scipy.signal as ss

    sr = E.SR
    n = int(3.0 * sr)
    bgm, hats = _hat_bed(n, sr)
    rng = np.random.default_rng(5)
    # codec error on the hi-hat at hats[2]: decorrelated HF noise with the hi-hat's envelope, -8 dB under it
    h = hats[2]
    i, m = int(h * sr), int(0.03 * sr)
    b, a = ss.butter(4, [4500 / (sr / 2), 0.95], "band")
    err = ss.lfilter(b, a, rng.standard_normal(m)) * np.exp(-np.arange(m) / (0.008 * sr))
    err *= 10 ** (-30.0 / 20) / (np.abs(err).max() + 1e-12)
    res = np.zeros(n, np.float32)
    res[i:i + m] += err
    # a real knock (2.4 kHz damped sine) between two hi-hats, weaker than a hi-hat
    k0 = int((hats[3] + 0.3) * sr)
    kn = int(0.06 * sr)
    knock = (10 ** (-28 / 20) * np.sin(2 * np.pi * 2400 * np.arange(kn) / sr) * np.exp(-np.arange(kn) / (0.012 * sr)))
    res[k0:k0 + kn] += knock
    # a loud pop exactly on a hi-hat (louder than the hi-hat in its bands)
    p0 = int(hats[4] * sr)
    pop = (10 ** (-10 / 20) * np.sin(2 * np.pi * 900 * np.arange(kn) / sr) * np.exp(-np.arange(kn) / (0.02 * sr)))
    res[p0:p0 + kn] += pop
    mix = bgm + res
    ev_codec = E.mix_check({"t": h, "dur": 0.03}, res, mix, sr, bgm, None)
    ev_knock = E.mix_check({"t": hats[3] + 0.3, "dur": 0.06}, res, mix, sr, bgm, None)
    ev_pop = E.mix_check({"t": hats[4], "dur": 0.06}, res, mix, sr, bgm, None)
    assert not ev_codec["passed"] and any("bgm_transient_residue" in r for r in ev_codec["reasons"]), ev_codec
    assert ev_knock["passed"], ev_knock
    assert ev_pop["passed"], ev_pop
