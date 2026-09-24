"""SYNTHETIC reference-like fixtures for the reference-audio tests.

!!! Everything built here is SYNTHETIC test data with known ground truth. It is NOT reference-
channel data and never stands in for a measurement of the reference channel. !!!

A "reference-like" video audio is assembled from the generated test assets
(assets/test/generated: music beds, espeak-ng Korean TTS lines, synthetic SFX):
  - BGM from a library file at a known section/tempo/version, with fades,
  - speech lines with BGM ducking under them (known depth / attack / release, linear-dB ramps),
  - SFX at known times (also under speech and under BGM),
  - unique "on-site" sounds (random resonant knocks, one waveform per video),
  - an intentional silence gap (everything muted, BGM cut).
The ORACLE separator test double returns the known vocals stem exactly (demucs is unavailable).
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

SYNTHETIC_LABEL = "SYNTHETIC TEST FIXTURE (known ground truth) — not reference-channel data"
REPO = Path(__file__).resolve().parents[2]
GEN = REPO / "assets" / "test" / "generated"
SR = 22050


def _read(path: Path) -> np.ndarray:
    from shortkit.util.media import read_audio

    return read_audio(path, sr=SR, mono=True).astype(np.float32)


def _write(path: Path, x: np.ndarray, sr: int = SR) -> None:
    from shortkit.util.media import write_wav

    write_wav(path, np.asarray(x, np.float32), sr)


def require_assets() -> list[str]:
    need = [GEN / "music_bed_a.wav", GEN / "music_bed_a_x1.1.wav", GEN / "music_bed_b.wav",
            GEN / "speech_01.wav", GEN / "speech_02.wav", GEN / "speech_03.wav", GEN / "sfx" / "pop.wav"]
    return [str(p) for p in need if not p.exists()]


def make_project(root: Path) -> None:
    """Minimal temp project root: marker + a copy of the joshuamagazine preset folder files."""
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "shortkit.root", root / "shortkit.root")
    pd = root / "presets" / "joshuamagazine"
    pd.mkdir(parents=True, exist_ok=True)
    for f in ("preset.yaml", "sfx_map.yaml", "sfx_catalog.json", "formats.yaml"):
        src = REPO / "presets" / "joshuamagazine" / f
        if src.exists():
            shutil.copy(src, pd / f)


def make_library(root: Path, with_index: bool = True) -> dict[str, Path]:
    """Clean-music library (22.05 kHz mono copies of the generated beds) + index.yaml."""
    lib = root / "assets" / "library" / "music"
    lib.mkdir(parents=True, exist_ok=True)
    files = {"bed_a.wav": GEN / "music_bed_a.wav", "bed_a_x1.1.wav": GEN / "music_bed_a_x1.1.wav",
             "bed_b.wav": GEN / "music_bed_b.wav"}
    out = {}
    for name, src in files.items():
        dst = lib / name
        if not dst.exists():
            _write(dst, _read(src))
        out[name] = dst
    if with_index:
        (lib / "index.yaml").write_text(
            "schema: shortkit.music_library/1\n"
            "# SYNTHETIC test library (generated beds)\n"
            "tracks:\n"
            "  - {track_id: bed_a_original, song_id: bed_a, title: 'Test Bed A', version: original, file: bed_a.wav,"
            " tempo_ratio_to_original: 1.0}\n"
            "  - {track_id: bed_a_sped_up, song_id: bed_a, title: 'Test Bed A', version: sped_up, file: bed_a_x1.1.wav,"
            " tempo_ratio_to_original: 1.1}\n"
            "  - {track_id: bed_b_original, song_id: bed_b, title: 'Test Bed B', version: original, file: bed_b.wav,"
            " tempo_ratio_to_original: 1.0}\n",
            encoding="utf-8")
    return out


def atempo(x: np.ndarray, ratio: float, tmpdir: Path) -> np.ndarray:
    """Pitch-preserving tempo change with ffmpeg atempo (WSOLA)."""
    from shortkit.util.media import ffmpeg

    a, b = tmpdir / "atempo_in.wav", tmpdir / "atempo_out.wav"
    _write(a, x)
    ffmpeg(["-i", a, "-af", f"atempo={ratio}", "-ar", str(SR), "-ac", "1", b])
    return _read(b)


def sfx_bank() -> dict[str, np.ndarray]:
    return {p.stem: _read(p) for p in sorted((GEN / "sfx").glob("*.wav"))}


def knock(seed: int) -> np.ndarray:
    """Unique 'on-site' sound: resonant noise knock (different waveform for every seed)."""
    from scipy.signal import lfilter

    rng = np.random.default_rng(seed)
    n = int(0.25 * SR)
    t = np.arange(n) / SR
    f0 = rng.uniform(350, 700)
    r = 0.995
    th = 2 * np.pi * f0 / SR
    y = lfilter([1 - r], [1, -2 * r * np.cos(th), r * r], rng.standard_normal(n) * np.exp(-t / 0.02))
    y = y / (np.max(np.abs(y)) + 1e-9) * 0.5 * np.exp(-t / 0.08)
    return y.astype(np.float32)


def _db2a(d: float) -> float:
    return float(10 ** (d / 20))


def _active_range(x: np.ndarray, rel_db: float = 40.0) -> tuple[int, int]:
    a = np.abs(x)
    thr = a.max() * 10 ** (-rel_db / 20)
    idx = np.nonzero(a > thr)[0]
    return int(idx[0]), int(idx[-1])


@dataclass
class VideoSpec:
    video_id: str
    dur: float = 20.0
    bgm_file: str | None = "bed_a_x1.1.wav"      # library file name
    bgm_offset: float = 13.3                     # section start in that file (s)
    bgm_tempo: float = 1.0                       # extra atempo applied (1.0 = file as is)
    bgm_gain_db: float = -12.0
    fade_in: float = 0.0
    fade_out: float = 0.0
    speech: list = field(default_factory=list)   # [(name, t, gain_db)]
    duck_db: float = 9.0
    attack: float = 0.1
    release: float = 0.3
    sfx: list = field(default_factory=list)      # [(name, t, gain_db)]
    onsite: list = field(default_factory=list)   # [(seed, t, gain_db)]
    silence: tuple | None = None                 # (start, end)
    format_id: str = "F1"


def build(spec: VideoSpec, lib: dict[str, Path], bank: dict[str, np.ndarray], tmpdir: Path) -> dict:
    """Return {"mix", "vocals", "other", "truth"} (all SR mono float32)."""
    n = int(spec.dur * SR)
    t = np.arange(n) / SR
    speech = np.zeros(n, np.float32)
    truth: dict = {"label": SYNTHETIC_LABEL, "video_id": spec.video_id, "speech": [], "sfx": [], "onsite": [],
                   "silence": None, "bgm": None}
    for name, ts, g in spec.speech:
        s = _read(GEN / f"{name}.wav")
        a, b = _active_range(s)
        s = s[a:b + 1]
        i0 = int(ts * SR)
        m = min(len(s), n - i0)
        speech[i0:i0 + m] += s[:m] * _db2a(g)
        truth["speech"].append({"name": name, "start": ts, "end": round(ts + m / SR, 4)})
    bgm = np.zeros(n, np.float32)
    if spec.bgm_file:
        clean = _read(lib[spec.bgm_file])
        if spec.bgm_tempo != 1.0:
            # take the section first, then time-stretch it (reference re-timed the file)
            s0 = int(spec.bgm_offset * SR)
            sec = clean[s0:s0 + int((spec.dur * spec.bgm_tempo + 1.0) * SR)]
            src = atempo(sec, spec.bgm_tempo, tmpdir)
        else:
            s0 = int(round(spec.bgm_offset * SR))
            src = clean[s0:s0 + n]
        m = min(n, len(src))
        bgm[:m] = src[:m]
        env_db = np.zeros(n)
        for sp in truth["speech"]:
            s, e = sp["start"], sp["end"]
            down = np.clip((t - s) / spec.attack, 0, 1)
            up = np.clip((t - e) / spec.release, 0, 1)
            env_db = np.minimum(env_db, -spec.duck_db * (down - up * (t >= e)))
        amp = _db2a(spec.bgm_gain_db) * 10 ** (env_db / 20)
        if spec.fade_in > 0:
            amp *= np.clip(t / spec.fade_in, 0, 1)
        if spec.fade_out > 0:
            amp *= np.clip((spec.dur - t) / spec.fade_out, 0, 1)
        bgm = (bgm * amp).astype(np.float32)
        truth["bgm"] = {"file": spec.bgm_file, "section_start_s": spec.bgm_offset, "tempo_ratio": spec.bgm_tempo,
                        "gain_db": spec.bgm_gain_db, "duck_db": spec.duck_db, "attack_s": spec.attack,
                        "release_s": spec.release, "fade_in_s": spec.fade_in, "fade_out_s": spec.fade_out}
    other = np.zeros(n, np.float32)
    for name, ts, g in spec.sfx:
        x = bank[name]
        i0 = int(round(ts * SR))
        m = min(len(x), n - i0)
        other[i0:i0 + m] += x[:m] * _db2a(g)
        truth["sfx"].append({"name": name, "t": ts, "gain_db": g,
                             "under_speech": any(s["start"] < ts + len(x) / SR and s["end"] > ts
                                                 for s in truth["speech"])})
    for seed, ts, g in spec.onsite:
        x = knock(seed)
        i0 = int(round(ts * SR))
        m = min(len(x), n - i0)
        other[i0:i0 + m] += x[:m] * _db2a(g)
        truth["onsite"].append({"seed": seed, "t": ts})
    mix = bgm + speech + other
    if spec.silence:
        a, b = spec.silence
        mute = ((t < a) | (t >= b)).astype(np.float32)
        mix *= mute
        bgm *= mute
        speech *= mute
        other *= mute
        truth["silence"] = {"start": a, "end": b}
    return {"mix": mix.astype(np.float32), "vocals": speech, "other": (bgm + other).astype(np.float32),
            "truth": truth}


class OracleSeparator:
    """TEST DOUBLE separator: returns the known stems of synthetic mixes (demucs is unavailable)."""

    name = "oracle(test-double)"
    version = "synthetic"

    def __init__(self):
        self.by_path: dict[str, dict[str, np.ndarray]] = {}

    def add(self, path: Path, stems: dict[str, np.ndarray]) -> None:
        self.by_path[str(Path(path).resolve())] = stems

    def separate(self, path: Path, two_stems: bool = False):
        st = self.by_path[str(Path(path).resolve())]
        if two_stems:
            return {"vocals": st["vocals"], "no_vocals": st["other"]}, SR
        return {"vocals": st["vocals"], "other": st["other"]}, SR


DEFAULT_SPECS = [
    VideoSpec("synv1", bgm_file="bed_a_x1.1.wav", bgm_offset=13.3, bgm_gain_db=-12.0, fade_in=0.5, fade_out=0.8,
              speech=[("speech_01", 4.0, -3.0), ("speech_02", 11.0, -3.0)], duck_db=9.0, attack=0.1, release=0.3,
              sfx=[("pop", 2.0, -8.0), ("whoosh", 5.0, -10.0), ("ding", 8.0, -12.0), ("click", 11.8, -10.0),
                   ("boom", 17.0, -8.0)],
              onsite=[(101, 9.6, -10.0)], silence=(14.8, 15.5), format_id="F1"),
    VideoSpec("synv2", bgm_file="bed_a.wav", bgm_offset=20.0, bgm_gain_db=-14.0,
              speech=[("speech_03", 6.0, -3.0)], duck_db=8.0, attack=0.1, release=0.3,
              sfx=[("pop", 3.0, -6.0), ("whoosh", 6.6, -9.0), ("ding", 12.5, -10.0), ("boom", 16.0, -9.0),
                   ("boing", 10.0, -10.0)],
              onsite=[(202, 14.0, -10.0)], format_id="F1"),
    VideoSpec("synv3", bgm_file="bed_b.wav", bgm_offset=5.0, bgm_gain_db=-13.0,
              speech=[("speech_01", 9.0, -3.0)], duck_db=10.0, attack=0.1, release=0.3,
              sfx=[("pop", 1.5, -9.0), ("ding", 4.0, -11.0), ("whoosh", 9.6, -9.0), ("scratch", 15.0, -9.0)],
              onsite=[(303, 6.5, -10.0)], silence=(12.0, 12.6), format_id="F2"),
    VideoSpec("synv4", bgm_file="bed_b.wav", bgm_offset=30.0, bgm_tempo=1.05, bgm_gain_db=-12.0,
              speech=[("speech_02", 8.0, -3.0)], duck_db=9.0, attack=0.1, release=0.3,
              sfx=[("pop", 2.5, -7.0), ("ding", 5.5, -10.0), ("boom", 13.0, -8.0), ("whoosh", 8.3, -9.0)],
              onsite=[(404, 11.0, -10.0)], format_id="F2"),
]
