"""Automatic audio measurements used by ``episode validate`` and the resolver (no listening claimed).

- ``speech_spans``      where a source (or its vocals stem) carries speech: voiced frames with syllable-rate level
                        modulation (``reference.audio_original.speech_segments_from_residual``) confirm speech; the
                        energy segments (``speech_segments_from_stem``) that overlap them give its extent.  Designed for
                        audio WITHOUT music (a raw source whose music was checked, or a vocals stem); with music under
                        the speech the voicing test fails and the result is "no speech" -> callers need a vocals stem.
- ``music_presence``    music embedded in a kept source range: sustained spectral partials (>= MUSIC_HOLD_S at the same
                        frequency) that are NOT harmonics of one voice (two simultaneous sustained partials with no
                        common f0 in 70-500 Hz) -- chords / bass + melody.  A single voice (speech, TTS) has only
                        harmonics of its own f0.  present / absent / unmeasured (ambiguous) -- never a guess.
- ``reference_stem_match`` a BGM file that is audio taken from a reference video.  ONE rule shared with the music
                        library (``reference.audio_bgm.load_library``) and QA (row audio.bgm:clean_file):
                        ``reference.audio_bgm.reference_audio_copy`` -- same sha256 as a stem file, a stem sha256 kept in
                        a separation record (the stem cache may be gone) or the downloaded reference media; or the file lies
                        INSIDE one stem at one lag (gain-invariant NCC >= audio_bgm.STEM_COPY_NCC) AND follows that stem's
                        own level changes (ducking, fades, leaked SFX).  The clean song a stem was separated from is not a
                        copy (a stem is an excerpt of it at some gain, with leaks: the old whole-file NCC >= 0.95 rule
                        refused it -- false positive fixed 2026-09-25).

Validation of the detectors (2026-09-25, this machine): espeak-ng Korean TTS lines (speech_01..03) and the
generated classroom test source -> speech found / music "absent" (polyphonic share 0.0-0.015); the synthetic chord
beds music_bed_a/b -> music "present" (0.49-0.98), no speech; TTS + bed at -10 / -20 dB -> "present" (0.41 / 0.16).
Only synthetic music and TTS were available (no real recordings): thresholds are engineering rules, not
measurements of the reference.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import numpy as np

from .. import paths

SR = 22050
MUSIC_SR = 16000
MUSIC_NFFT, MUSIC_HOP = 2048, 512
MUSIC_HOLD_S = 0.4              # a partial held this long at one frequency (+-1 bin) is "sustained"
MUSIC_PROM_DB = 10.0            # spectral peak prominence over the local (41-bin median) floor
MUSIC_PRESENT_SHARE = 0.10      # share of active frames with inharmonic sustained partials -> music present
MUSIC_ABSENT_SHARE = 0.03       # below this -> absent; in between -> unmeasured (ambiguous)
MUSIC_MIN_ACTIVE_S = 0.5        # less audible audio than this -> nothing to judge (absent if silent)


def _stat_key(p: Path) -> tuple:
    st = p.stat()
    return str(p.resolve()), st.st_mtime_ns, st.st_size


@lru_cache(maxsize=32)
def _load(key: tuple, sr: int) -> np.ndarray:
    from ..util.media import read_audio

    return np.asarray(read_audio(key[0], sr=sr, mono=True), np.float32)


def load_mono(stored: str, sr: int = SR) -> np.ndarray | None:
    p = paths.absp(stored)
    if not p.is_file():
        return None
    try:
        return _load(_stat_key(p), sr)
    except Exception:          # unreadable: callers report "unmeasured"
        return None


def has_audio_stream(stored: str) -> bool | None:
    from ..util.media import MediaError, probe

    try:
        return bool(probe(paths.absp(stored)).has_audio)
    except (MediaError, OSError):
        return None


# ----------------------------------------------------------------------------- speech
@lru_cache(maxsize=32)
def _speech_cached(key: tuple) -> tuple:
    from ..reference.audio_original import speech_segments_from_residual, speech_segments_from_stem

    x = _load(key, SR)
    if not len(x) or float(np.max(np.abs(x))) < 1e-5:
        return tuple()
    voiced = speech_segments_from_residual(x, SR)
    extent = speech_segments_from_stem(x, SR)
    out = []
    for e in extent:
        if any(v["start"] < e["end"] and v["end"] > e["start"] for v in voiced):
            out.append((float(e["start"]), float(e["end"])))
    for v in voiced:                     # voiced speech outside every energy segment (very quiet line)
        if not any(a < v["end"] and b > v["start"] for a, b in out):
            out.append((float(v["start"]), float(v["end"])))
    return tuple(sorted(out))


def speech_spans(stored: str) -> dict:
    """{status: measured|unmeasured, spans: [(start, end)] in the file's seconds, method, reason}."""
    method = ("음성 판정: 유성음(75-400 Hz 자기상관 >= 0.5) + 음절 속도 레벨 변화(초당 6 dB 골 2회 이상), "
              "범위: 에너지 구간(최대 대비 30 dB 안) — reference.audio_original")
    p = paths.absp(stored)
    if not p.is_file():
        return {"status": "unmeasured", "spans": [], "method": method, "reason": f"파일 없음: {stored}"}
    if has_audio_stream(stored) is False:
        return {"status": "measured", "spans": [], "method": method, "reason": "오디오 스트림 없음"}
    try:
        spans = list(_speech_cached(_stat_key(p)))
    except Exception as e:        # never a silent pass
        return {"status": "unmeasured", "spans": [], "method": method, "reason": f"{type(e).__name__}: {e}"}
    return {"status": "measured", "spans": spans, "method": method, "reason": None}


def overlap(a0: float, a1: float, spans) -> float:
    return float(sum(max(0.0, min(a1, b) - max(a0, a)) for a, b in spans))


def span_at(spans, t: float, tol: float = 0.3):
    """The speech span containing t (within tol), or None."""
    best = None
    for a, b in spans:
        d = 0.0 if a <= t <= b else min(abs(t - a), abs(t - b))
        if d <= tol and (best is None or d < best[0]):
            best = (d, (a, b))
    return best[1] if best else None


# ----------------------------------------------------------------------------- music
def _harmonic_pair(f1: float, f2: float, f0min: float = 70.0, f0max: float = 500.0, nmax: int = 16,
                   tol: float = 0.02) -> bool:
    lo, hi = min(f1, f2), max(f1, f2)
    for m in range(1, nmax + 1):
        f0 = lo / m
        if f0 < f0min:
            break
        if f0 > f0max:
            continue
        n = round(hi / f0)
        if 1 <= n <= 2 * nmax and abs(hi - n * f0) <= tol * hi:
            return True
    return False


def music_features(x: np.ndarray, sr: int = MUSIC_SR) -> dict | None:
    from scipy.ndimage import median_filter

    n_fft, hop = MUSIC_NFFT, MUSIC_HOP
    if len(x) < n_fft:
        return None
    win = np.hanning(n_fft)
    nfr = 1 + (len(x) - n_fft) // hop
    F = np.lib.stride_tricks.sliding_window_view(x, n_fft)[::hop][:nfr] * win
    P = np.abs(np.fft.rfft(F, axis=1)) ** 2
    L = 10 * np.log10(P + 1e-12)
    fr = np.fft.rfftfreq(n_fft, 1 / sr)
    band = (fr >= 80.0) & (fr <= 4000.0)
    floor = median_filter(L, size=(1, 41), mode="nearest")
    lvl = 10 * np.log10(P[:, band].sum(1) + 1e-12)
    active = lvl > max(float(lvl.max()) - 40.0, -80.0)
    top = float(L[:, band].max())
    minlen = int(np.ceil(MUSIC_HOLD_S * sr / hop))
    ispk = np.zeros_like(L, bool)
    ispk[:, 1:-1] = ((L[:, 1:-1] > L[:, :-2]) & (L[:, 1:-1] >= L[:, 2:]) & ((L - floor)[:, 1:-1] > MUSIC_PROM_DB)
                     & (L[:, 1:-1] > top - 60.0))
    ispk[:, ~band] = False
    ispk[~active] = False
    tracks: list[dict] = []
    open_: list[int] = []
    for i in range(nfr):
        ks = np.nonzero(ispk[i])[0]
        new_open, used = [], set()
        for k in ks:
            a, b, c = L[i, k - 1], L[i, k], L[i, k + 1]
            den = a - 2 * b + c
            f = (k + (0.5 * (a - c) / den if den else 0.0)) * sr / n_fft
            hit = next((ti for ti in open_ if ti not in used and abs(tracks[ti]["k"] - k) <= 1), None)
            if hit is None:
                tracks.append({"start": i, "k": int(k), "f": [f]})
                new_open.append(len(tracks) - 1)
            else:
                tracks[hit]["k"] = int(k)
                tracks[hit]["f"].append(f)
                used.add(hit)
                new_open.append(hit)
        open_ = new_open
    frame_f: list[list[float]] = [[] for _ in range(nfr)]
    for t in tracks:
        if len(t["f"]) >= minlen:
            for j, f in enumerate(t["f"]):
                frame_f[t["start"] + j].append(f)
    sustained = np.array([bool(ff) for ff in frame_f])
    poly = np.zeros(nfr, bool)
    for i, ff in enumerate(frame_f):
        ff = sorted(ff)
        poly[i] = any(not _harmonic_pair(ff[a], ff[b]) for a in range(len(ff)) for b in range(a + 1, len(ff)))
    na = int(active.sum())
    return {"active_s": round(na * hop / sr, 3), "sustained_share": round(float((sustained & active).sum() / max(na, 1)), 3),
            "polyphonic_share": round(float((poly & active).sum() / max(na, 1)), 3)}


def music_presence(stored: str, ranges: list[tuple[float, float]]) -> dict:
    """Music inside the given SOURCE-time ranges of a file: {status: present|absent|unmeasured, polyphonic_share,
    sustained_share, active_s, method, reason}."""
    method = (f"지속 부분음 검사: {MUSIC_HOLD_S}s 이상 같은 주파수로 이어지는 스펙트럼 봉우리 중 한 목소리의 배음으로 설명되지 "
              f"않는 동시 부분음(화음·베이스+선율) 비율 >= {MUSIC_PRESENT_SHARE} → 음악 있음, < {MUSIC_ABSENT_SHARE} → 없음, "
              "사이 → 못 잼 (합성 음악·TTS 로만 검증됨)")
    p = paths.absp(stored)
    if not p.is_file():
        return {"status": "unmeasured", "method": method, "reason": f"파일 없음: {stored}"}
    if has_audio_stream(stored) is False:
        return {"status": "absent", "method": method, "reason": "오디오 스트림 없음", "polyphonic_share": 0.0,
                "sustained_share": 0.0, "active_s": 0.0}
    try:
        x = _load(_stat_key(p), MUSIC_SR)
    except Exception as e:
        return {"status": "unmeasured", "method": method, "reason": f"{type(e).__name__}: {e}"}
    parts = [x[int(max(0.0, a) * MUSIC_SR):int(max(0.0, b) * MUSIC_SR)] for a, b in ranges if b > a]
    parts = [q for q in parts if len(q)]
    if not parts or float(max(np.max(np.abs(q)) for q in parts)) < 1e-4:
        return {"status": "absent", "method": method, "reason": "무음", "polyphonic_share": 0.0, "sustained_share": 0.0,
                "active_s": 0.0}
    feats = [music_features(q) for q in parts]
    feats = [f for f in feats if f]
    if not feats:
        return {"status": "unmeasured", "method": method, "reason": "구간이 너무 짧음(< 0.13 s)"}
    act = sum(f["active_s"] for f in feats)
    poly = sum(f["polyphonic_share"] * f["active_s"] for f in feats) / max(act, 1e-9)
    sus = sum(f["sustained_share"] * f["active_s"] for f in feats) / max(act, 1e-9)
    res = {"method": method, "polyphonic_share": round(poly, 3), "sustained_share": round(sus, 3),
           "active_s": round(act, 3), "reason": None}
    if act < MUSIC_MIN_ACTIVE_S:
        return {**res, "status": "unmeasured", "reason": f"들리는 소리 {act:.2f}s < {MUSIC_MIN_ACTIVE_S}s"}
    if poly >= MUSIC_PRESENT_SHARE:
        return {**res, "status": "present"}
    if poly < MUSIC_ABSENT_SHARE:
        return {**res, "status": "absent"}
    return {**res, "status": "unmeasured", "reason": f"애매함(동시 부분음 비율 {poly:.3f})"}


# ----------------------------------------------------------------------------- reference stems
def reference_stem_files() -> list[Path]:
    """Audio separated from reference videos: presets/*/analysis/*/stems/** (``reference.audio_bgm``'s list)."""
    from ..reference.audio_bgm import reference_stem_files as _files

    return _files()


def reference_stem_match(stored: str) -> dict | None:
    """The reference audio that ``stored`` copies, or None.  Delegates to
    ``reference.audio_bgm.reference_audio_copy`` (the library's rule, see the module docstring) so validate, QA and
    the library refuse exactly the same files.  -> {stem (what was matched), kind, method, reason, ...}."""
    p = paths.absp(stored)
    if not p.is_file():
        return None
    from ..reference.audio_bgm import reference_audio_copy

    m = reference_audio_copy(p)
    if not m:
        return None
    return {**m, "stem": m.get("matched")}
