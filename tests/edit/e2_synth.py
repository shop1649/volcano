"""SYNTHETIC audio for the E2 BGM-guard tests (tests/edit/test_e2_remainders.py, tests/qa/test_qa_e2.py).
Generated signals only -- not a recording, not reference-channel data."""
from __future__ import annotations

import numpy as np

SR = 22050


def synth_song(dur: float, sr: int = SR, seed: int = 11) -> np.ndarray:
    """SYNTHETIC 'song': a random triad every 0.5 s (decaying), bass, a noise tick every second."""
    rng = np.random.default_rng(seed)
    n = int(dur * sr)
    t = np.arange(n) / sr
    y = np.zeros(n)
    for k in range(int(np.ceil(dur / 0.5))):
        a, b = int(k * 0.5 * sr), min(n, int((k + 1) * 0.5 * sr))
        root_semi = int(rng.integers(-5, 7))
        chord = [0, 4, 7] if rng.random() < 0.5 else [0, 3, 7]
        tt = t[a:b]
        env = np.exp(-(tt - tt[0]) * 3.0)
        for s in chord:
            f = 220 * 2 ** ((root_semi + s) / 12)
            y[a:b] += 0.12 * env * (np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(4 * np.pi * f * tt))
        y[a:b] += 0.18 * env * np.sin(2 * np.pi * 110 * 2 ** (root_semi / 12) * tt)
        if k % 2 == 0:
            m = min(b - a, int(0.03 * sr))
            y[a:a + m] += 0.2 * rng.standard_normal(m) * np.linspace(1, 0, m)
    return (0.7 * y / np.abs(y).max()).astype(np.float32)


def stem_of(song: np.ndarray, sr: int = SR) -> np.ndarray:
    """SYNTHETIC separated music stem of a reference: song[10 s:30 s] at a constant -12 dB (original sound off -> no
    ducking), 0.5 s / 0.8 s fades and one faint leaked 'pop' -- the normal shape of a real stem."""
    n = int(20 * sr)
    t = np.arange(n) / sr
    x = song[int(10 * sr):int(10 * sr) + n] * 10 ** (-12 / 20) * np.clip(t / 0.5, 0, 1) * np.clip((20 - t) / 0.8, 0, 1)
    k = np.arange(int(0.2 * sr))
    pop = 0.6 * np.sin(2 * np.pi * 1000 * k / sr) * np.exp(-k / sr * 20)
    x[int(2 * sr):int(2 * sr) + len(pop)] += pop * 10 ** (-22 / 20)
    return x.astype(np.float32)
