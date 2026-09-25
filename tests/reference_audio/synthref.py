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


def random_bed(seed: int, dur: float = 60.0) -> np.ndarray:
    """NON-PERIODIC synthetic music (random notes + bass + noise hits): every section differs, so a
    restart/jump inside the file has a unique ground truth (the generated beds repeat every 8-10 s)."""
    rng = np.random.default_rng(seed)
    n = int(dur * SR)
    y = np.zeros(n, np.float64)
    t = 0.0
    while t < dur:                                         # lead notes
        d = float(rng.uniform(0.12, 0.5))
        f0 = 440.0 * 2 ** ((int(rng.integers(48, 85)) - 69) / 12)
        a, b = int(t * SR), min(n, int((t + d) * SR))
        tt = np.arange(b - a) / SR
        env = np.minimum(1.0, tt / 0.01) * np.exp(-tt / (0.6 * d))
        tone = sum(np.sin(2 * np.pi * f0 * h * tt + rng.uniform(0, 6.3)) / h for h in (1, 2, 3, 4))
        y[a:b] += float(rng.uniform(0.2, 0.5)) * env * tone
        t += d
    t = 0.0
    while t < dur:                                         # bass
        d = float(rng.uniform(1.0, 2.0))
        f0 = 440.0 * 2 ** ((int(rng.integers(28, 45)) - 69) / 12)
        a, b = int(t * SR), min(n, int((t + d) * SR))
        tt = np.arange(b - a) / SR
        y[a:b] += 0.35 * np.minimum(1.0, tt / 0.02) * np.sin(2 * np.pi * f0 * tt)
        t += d
    for th in np.cumsum(rng.exponential(0.25, int(dur * 6))):   # noise hits
        if th >= dur - 0.1:
            break
        a = int(th * SR)
        m = int(0.06 * SR)
        y[a:a + m] += 0.3 * rng.standard_normal(m) * np.exp(-np.arange(m) / (0.012 * SR))
    return (0.5 * y / np.max(np.abs(y))).astype(np.float32)


def add_random_bed(root: Path, name: str = "bed_r", seed: int = 7, dur: float = 60.0) -> Path:
    """Write a NON-PERIODIC bed into the temp library and add it to index.yaml (SYNTHETIC)."""
    import yaml

    lib = root / "assets" / "library" / "music"
    lib.mkdir(parents=True, exist_ok=True)
    dst = lib / f"{name}.wav"
    _write(dst, random_bed(seed, dur))
    idx_p = lib / "index.yaml"
    idx = yaml.safe_load(idx_p.read_text(encoding="utf-8")) if idx_p.exists() else {}
    idx = idx or {}
    tracks = [t for t in (idx.get("tracks") or []) if t.get("track_id") != f"{name}_original"]
    tracks.append({"track_id": f"{name}_original", "song_id": name, "title": f"Test Random {name}",
                   "version": "original", "file": dst.name, "tempo_ratio_to_original": 1.0})
    idx["tracks"] = tracks
    idx_p.write_text(yaml.safe_dump(idx, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return dst


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
    silence_fade: float = 0.0                    # renderer shape: dB-linear 0 -> -120 dB over this, before/after
    bgm_segments: list | None = None             # [(ref_t, clean_offset)] BGM restarts/jumps (tempo 1.0 only)
    ambience: list = field(default_factory=list)  # [(start, end, gain_db, fade_s, seed)] room tone, linear fades
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
        if spec.bgm_segments:
            # piecewise: from ref time t_k the BGM plays the clean file from offset o_k (restart / jump)
            assert spec.bgm_tempo == 1.0, "bgm_segments only with tempo 1.0"
            segs = sorted(spec.bgm_segments) + [(spec.dur, None)]
            for (t_k, o_k), (t_n, _) in zip(segs, segs[1:]):
                a, b = int(round(t_k * SR)), min(n, int(round(t_n * SR)))
                s0 = int(round(o_k * SR))
                piece = clean[s0:s0 + (b - a)]
                bgm[a:a + len(piece)] = piece
        elif spec.bgm_tempo != 1.0:
            # take the section first, then time-stretch it (reference re-timed the file)
            s0 = int(spec.bgm_offset * SR)
            sec = clean[s0:s0 + int((spec.dur * spec.bgm_tempo + 1.0) * SR)]
            src = atempo(sec, spec.bgm_tempo, tmpdir)
            m = min(n, len(src))
            bgm[:m] = src[:m]
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
                        "release_s": spec.release, "fade_in_s": spec.fade_in, "fade_out_s": spec.fade_out,
                        "segments": [list(x) for x in spec.bgm_segments] if spec.bgm_segments else None,
                        "loop": _has_restart(spec)}
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
    truth["ambience"] = []
    for a, b, g, fade, seed in spec.ambience:
        # kept "original sound" room tone: stationary noise with LINEAR-AMPLITUDE edge fades (the
        # renderer's shape for kept originals, shortkit.edit.render._lin_fade)
        i0, i1 = int(round(a * SR)), min(n, int(round(b * SR)))
        x = room_tone(seed, i1 - i0) * _db2a(g)
        env = np.ones(i1 - i0, np.float32)
        k = int(round(fade * SR))
        if k > 0:
            env[:k] = np.linspace(0.0, 1.0, k, endpoint=False)
            env[-k:] = np.minimum(env[-k:], np.linspace(1.0, 0.0, k))
        other[i0:i1] += x * env
        truth["ambience"].append({"start": a, "end": b, "gain_db": g, "fade_s": fade})
    mix = bgm + speech + other
    if spec.silence:
        a, b = spec.silence
        mute = silence_gain(t, a, b, spec.silence_fade)
        mix *= mute
        bgm *= mute
        speech *= mute
        other *= mute
        truth["silence"] = {"start": a, "end": b, "fade_s": spec.silence_fade}
    return {"mix": mix.astype(np.float32), "vocals": speech, "other": (bgm + other).astype(np.float32),
            "truth": truth}


def silence_gain(t: np.ndarray, a: float, b: float, fade: float) -> np.ndarray:
    """Intentional-silence gain with the RENDERER's shape (shortkit.edit.audio.build_envelope):
    dB-linear 0 -> -120 dB over [a - fade, a], exact 0 on [a, b), -120 -> 0 dB over [b, b + fade]."""
    db = np.zeros(len(t))
    if fade > 0:
        down = (t >= a - fade) & (t < a)
        db[down] = -120.0 * (t[down] - (a - fade)) / fade
        up = (t >= b) & (t < b + fade)
        db[up] = -120.0 * (1.0 - (t[up] - b) / fade)
    g = 10 ** (db / 20)
    g[(t >= a) & (t < b)] = 0.0
    g[db <= -120.0 + 1e-9] = 0.0
    return g.astype(np.float32)


def room_tone(seed: int, n: int) -> np.ndarray:
    """Stationary low-passed noise at ~0 dBFS RMS (different waveform for every seed)."""
    from scipy.signal import butter, sosfilt

    rng = np.random.default_rng(seed)
    y = sosfilt(butter(2, 3000.0, "low", fs=SR, output="sos"), rng.standard_normal(n + 2048))[2048:]
    return (y / (np.sqrt(np.mean(y ** 2)) + 1e-12)).astype(np.float32)


def _has_restart(spec: VideoSpec) -> bool:
    """Ground truth: does the clean position jump back by more than 1 s anywhere?"""
    if not spec.bgm_segments:
        return False
    segs = sorted(spec.bgm_segments)
    return any(o_n - (o_k + (t_n - t_k)) < -1.0 for (t_k, o_k), (t_n, o_n) in zip(segs, segs[1:]))


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
              # seed 707 (not 404): knock(404) has waveform xcorr 0.72 with knock(202) -- by the catalog's own rule
              # (EDIT_XCORR 0.70) the SAME waveform, so it was never a 'unique' on-site sound; this only surfaced
              # once fingerprints stopped carrying mix residual (mockloop validation)
              onsite=[(707, 11.0, -10.0)], format_id="F2"),
]
