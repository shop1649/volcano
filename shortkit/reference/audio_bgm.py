"""BGM identification and alignment against a library of CLEAN music files.

User rule: BGM is identified by title AND version AND speed AND used section; a different part
of the same song is NOT a match; production uses the clean library file, never a stem
separated from the reference.

Library: ``assets/library/music`` (+ ``local.yaml: music_library_root``).  Each root may have an
``index.yaml`` (format of assets/library/music/README.md; one entry per FILE)::

    tracks:
      - {track_id: bed_a_original, song_id: bed_a, title: "...", artist: "...", version: original,
         file: bed_a.wav, tempo_ratio_to_original: 1.0}
      - {track_id: bed_a_sped_up, song_id: bed_a, title: "...", version: sped_up, file: bed_a_x1.1.wav,
         tempo_ratio_to_original: 1.1}

``track_id`` identifies the file entry (what preset ``audio.bgm.track_id`` points to); the SONG is
``song_id`` (else ``title``+``artist``, else ``track_id``).  ``id`` is accepted as an alias of
``track_id`` and ``tracks`` may also be a mapping ``{track_id: {...}}``.  Without an index, files are
scanned and ``title``/``version`` stay unmeasured.

Method (numpy/scipy only):
 1. coarse: log-mel spectral-shape features (frame-mean removed -> invariant to BGM gain and
    ducking), clean features resampled for every tempo ratio r in [0.85, 1.15] (step 0.005),
    normalised cross-correlation over all offsets (FFT); then fine r (step 0.0005).
 2. waveform refinement when |r-1| <= 0.003 (the reference used this exact file): probe windows
    are located in the clean file by GCC-PHAT, a line clean_t = offset + r*ref_t is fitted, and
    pre-emphasised waveform correlation ("coherence", p75 over probes) verifies the fit.  Repeated sections of a
    song that look identical in the spectrogram are separated here; if they are still
    indistinguishable the section is reported ``ambiguous`` with all candidates.
 3. gain: per-window least squares of the (vocals-removed) mix on the aligned clean waveform
    (waveform mode) or robust magnitude ratio (spectral mode, when the reference re-timed the
    file); presence/used range/cuts/fades from that curve.

Optional online recognizer (shazamio) is only a hint and is NOT tested here (not installed;
recognition hosts are not reachable from the build machine).
"""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np

from .. import paths
from ..util.hashing import sha256_file
from ..util.jsonio import now_iso, read_json, read_yaml, write_json
from .separation import (AUDIO_EXT, SR, Stems, audio_dir, find_reference_media, fractional_delay, load_mono,
                         local_settings, logmel, rel_or_none, resolve_stored, stft, store_path)

SCHEMA = "shortkit.audio_bgm/1"

TEMPO_RANGE = (0.85, 1.15)
TEMPO_STEP_COARSE = 0.005
TEMPO_STEP_FINE = 0.0005
TEMPO_TOL = 0.01              # match tolerance on tempo ratio
OFFSET_TOL_S = 0.25           # match tolerance on section start (clean-file seconds)
ID_MIN_SCORE = 0.30           # minimum feature NCC to call a track identified
ID_MIN_MARGIN = 0.08          # best track must beat the best *other* track by this much
VERSION_TIE = 0.05            # same-track candidates within this NCC are "equally explaining"
WAVEFORM_MAX_DEV = 0.003      # |r-1| up to which the exact-file waveform path is tried
MIN_COHERENCE = 0.2           # waveform path: probe coherence p75 >= this ...
MIN_COHERENCE_MAX = 0.5       # ... and the best probe >= this (plus >= 3 probes on one line within 4 ms)
AMBIG_COHERENCE = 0.05        # repeat candidates within this coherence -> ambiguous section
AMBIG_LOCAL_COHERENCE = 0.03  # spectral-mode equivalent of AMBIG_COHERENCE (short-window waveform match)
REPEAT_NCC_BAND = 0.08        # other offsets within this feature NCC of the best are verified too
FEAT_NFFT, FEAT_HOP, FEAT_MELS, FEAT_FMAX = 2048, 512, 40, 8000.0
GAIN_WIN_S, GAIN_HOP_S = 0.05, 0.01
PRESENT_BELOW_BASE_DB = 25.0  # BGM counted present while gain > base - 25 dB
CUT_MIN_S = 0.3
# restart / loop detection (piecewise alignment against the SAME clean file at the found tempo)
LOOP_WIN_S, LOOP_HOP_S = 3.0, 1.0   # analysis windows (shorter repeats cannot be detected)
LOOP_MIN_NCC = 0.5            # a window "is this clean file at another offset" only above this feature NCC ...
LOOP_MARGIN = 0.1             # ... and when it beats the main line by this much (spectral mode)
LOOP_TIE = 0.02               # main line within this of the best feature NCC -> stays on the main line
LOOP_SPECTRAL_NCC = 0.6       # spectral mode (no waveform check possible): stricter NCC and >= 2 windows
LOOP_LINE_TOL_S = 0.3         # windows whose clean offsets differ by less than this belong to one line
LOOP_JUMP_S = 1.0             # line change that counts as a jump: backward = restart/loop, forward = skip
CRITERIA = {"tempo_tol": TEMPO_TOL, "offset_tol_s": OFFSET_TOL_S, "id_min_score": ID_MIN_SCORE,
            "id_min_margin": ID_MIN_MARGIN, "tempo_range": list(TEMPO_RANGE),
            "rule": "같은 곡 AND 같은 버전 AND 속도 허용오차 이내 AND 사용 구간 시작 허용오차 이내 — 같은 곡의 다른 구간은 불일치"}


# ============================================================================ library
@dataclass
class LibraryTrack:
    track_id: str
    title: str | None
    version: str | None
    file: Path
    stored: str
    tempo_ratio_to_original: float | None = None
    meta: dict = field(default_factory=dict)
    song_id: str | None = None
    artist: str | None = None

    @property
    def song(self) -> str:
        """Song identity used for 'same song, other version' decisions."""
        if self.song_id:
            return str(self.song_id)
        if self.title:
            return f"{self.title}\u241f{self.artist or ''}"
        return self.track_id


def library_roots() -> list[tuple[str | None, Path]]:
    roots: list[tuple[str | None, Path]] = [(None, paths.absp("assets/library/music"))]
    extra = local_settings().get("music_library_root")
    if extra:
        roots.append(("$music_library_root", Path(os.path.expanduser(str(extra)))))
    return roots


def load_library(roots: list[tuple[str | None, Path]] | None = None, *, rejected: list[dict] | None = None,
                 check_reference_audio: bool = True) -> list[LibraryTrack]:
    """Clean-music library files.  A file that is audio taken from a reference video -- a separated stem
    (same bytes, or the same waveform: ``reference_audio_copy``) or the reference's own media -- is NOT a clean
    music file (user rule) and is left out; each such file is appended to ``rejected`` with the reason."""
    out: list[LibraryTrack] = []
    seen: set[Path] = set()
    for token, root in roots or library_roots():
        if not root.is_dir():
            continue
        idx = read_yaml(root / "index.yaml") or {}
        entries = idx.get("tracks") or []
        if isinstance(entries, dict):
            entries = [{"track_id": k, **(v or {})} for k, v in entries.items()]
        for t in entries:
            fn = t.get("file") or t.get("path")
            if not fn:
                continue
            f = (root / str(fn)).resolve()
            if not f.is_file() or f in seen:
                continue
            seen.add(f)
            out.append(LibraryTrack(track_id=str(t.get("track_id") or t.get("id") or f.stem), title=t.get("title"),
                                    version=t.get("version"), file=f, stored=store_path(f, token, root),
                                    tempo_ratio_to_original=t.get("tempo_ratio_to_original"),
                                    song_id=t.get("song_id"), artist=t.get("artist"),
                                    meta={k: v for k, v in t.items() if k not in ("track_id", "id", "title", "version",
                                                                                  "file", "path", "song_id",
                                                                                  "artist")}))
        for f in sorted(root.rglob("*")):
            if f.is_file() and f.suffix.lower() in AUDIO_EXT and f.resolve() not in seen:
                seen.add(f.resolve())
                out.append(LibraryTrack(track_id=f.stem, title=None, version=None, file=f.resolve(),
                                        stored=store_path(f, token, root), meta={"indexed": False}))
    if not check_reference_audio or not out:
        return out
    ref = ReferenceAudio.scan()
    kept = []
    for tr in out:
        hit = ref.copy_of(tr.file)
        if hit is None:
            kept.append(tr)
        elif rejected is not None:
            rejected.append({"file": tr.stored, "track_id": tr.track_id, **hit})
    return kept


# ============================================================================ reference-audio guard
# A clean music file must never be audio taken from a reference video (a separated stem, or the reference's
# own audio).  Same bytes -> refused.  Same waveform -> refused when the library file lies INSIDE one stem at
# one lag (a trimmed / re-encoded / resampled / gain-changed copy) AND follows that stem's own level changes.
# The clean source a stem was separated from is not refused: a whole song is longer than the stem (it cannot
# lie inside it), and a clean excerpt does not follow the stem's ducking, fades, cuts and leaked SFX.  Limit:
# when the stem has no level change and no leak at all over the excerpt, a clean excerpt and a stem copy are
# the same signal and the excerpt is refused (the safe side).  Time-stretched or re-edited stems (pieces
# re-ordered / looped past the stem length) are not detected by the waveform rule.  Engineering thresholds,
# validated on SYNTHETIC stems only (tests/reference_audio/test_library_stem_guard.py).
STEM_COPY_SR = 8000
STEM_COPY_NCC = 0.98          # whole library file vs the stem segment at the best lag (gain-invariant)
STEM_COPY_WIN_S = 0.25        # level-following test windows
STEM_COPY_DEV_DB = 3.0        # a window "does not follow" the stem when levels differ by more than this ...
STEM_COPY_MAX_DEV_WIN = 1     # ... and a copy has at most this many such windows
STEM_COPY_ACTIVE_DB = -40.0   # windows quieter than this (re the loudest window of either) are ignored
STEM_COPY_LEN_TOL_S = 0.5     # a file longer than the stem + this cannot lie inside it
STEM_COPY_MIN_S = 1.0         # shorter files are not comparable by waveform (bytes only)
STEM_EXT = (".wav", ".flac", ".mp3", ".m4a", ".ogg", ".aac", ".opus", ".aif", ".aiff")
_DECODED: dict[tuple, np.ndarray] = {}
_SHA: dict[tuple, str] = {}
_COPY_CACHE: dict[tuple, dict | None] = {}


def _stat_key(p: Path) -> tuple:
    st = p.stat()
    return (str(p.resolve()), st.st_size, st.st_mtime_ns)


def _sha_cached(p: Path) -> str:
    k = _stat_key(p)
    if k not in _SHA:
        _SHA[k] = sha256_file(p)
    return _SHA[k]


def _decoded(p: Path) -> np.ndarray:
    k = _stat_key(p)
    if k not in _DECODED:
        if len(_DECODED) > 64:
            _DECODED.clear()
        x = load_mono(p, STEM_COPY_SR).astype(np.float64)
        nz = np.nonzero(np.abs(x) > 1e-4)[0]                 # digital silence at the ends is not content
        _DECODED[k] = x[nz[0]:nz[-1] + 1] if nz.size else x[:0]
    return _DECODED[k]


def reference_stem_files() -> list[Path]:
    """Audio separated from reference videos: presets/*/analysis/*/stems/** (every preset of this project)."""
    base = paths.absp("presets")
    out: list[Path] = []
    for d in sorted(base.glob("*/analysis/*/stems")) if base.is_dir() else []:
        out += [f for f in sorted(d.rglob("*")) if f.is_file() and f.suffix.lower() in STEM_EXT]
    return out


def reference_media_files() -> list[Path]:
    base = paths.absp("presets")
    out: list[Path] = []
    for d in sorted(base.glob("*/reference/videos")) if base.is_dir() else []:
        out += [f for f in sorted(d.iterdir()) if f.is_file() and f.suffix.lower() in AUDIO_EXT]
    return out


def _ncc_inside(a: np.ndarray, b: np.ndarray) -> tuple[float, int]:
    """(max gain-invariant NCC, lag) of ``b`` slid fully inside ``a`` (len(a) >= len(b))."""
    n = len(b)
    b = b - b.mean()
    nb = float(np.linalg.norm(b))
    if nb <= 1e-9 or len(a) < n:
        return 0.0, 0
    m = 1 << int(np.ceil(np.log2(len(a) + n)))
    corr = np.fft.irfft(np.fft.rfft(a, m) * np.conj(np.fft.rfft(b, m)), m)[: len(a) - n + 1]
    c1 = np.concatenate([[0.0], np.cumsum(a)])
    c2 = np.concatenate([[0.0], np.cumsum(a * a)])
    s1 = c1[n:] - c1[:-n]
    s2 = c2[n:] - c2[:-n]
    na = np.sqrt(np.maximum(s2 - s1 * s1 / n, 1e-12))
    v = corr / (na * nb)
    k = int(np.argmax(v))
    return float(v[k]), k


def _level_deviations(seg: np.ndarray, x: np.ndarray) -> tuple[int, int]:
    """Windows where the gain-matched file does NOT follow the stem segment's level (> STEM_COPY_DEV_DB),
    over the windows where either is active.  -> (deviating, active)."""
    g = float(np.dot(seg, x) / max(float(np.dot(x, x)), 1e-12))
    y = g * x
    w = int(STEM_COPY_WIN_S * STEM_COPY_SR)
    k = len(x) // w
    if k < 1:
        return 0, 0
    es = 10 * np.log10(np.mean(seg[: k * w].reshape(k, w) ** 2, axis=1) + 1e-12)
    ey = 10 * np.log10(np.mean(y[: k * w].reshape(k, w) ** 2, axis=1) + 1e-12)
    top = max(float(es.max()), float(ey.max()))
    act = np.maximum(es, ey) > top + STEM_COPY_ACTIVE_DB
    dev = np.abs(ey - es)[act]
    return int(np.sum(dev > STEM_COPY_DEV_DB)), int(act.sum())


@dataclass
class ReferenceAudio:
    """What counts as reference audio here: stem files, stem sha256s kept in separation records (the stem cache
    is git-ignored and may be gone), and the downloaded reference media."""
    stems: list[Path]
    hashes: dict[str, tuple[str, str]]          # sha256 -> (kind, what)

    @classmethod
    def scan(cls) -> "ReferenceAudio":
        stems = reference_stem_files()
        hashes: dict[str, tuple[str, str]] = {}
        base = paths.absp("presets")
        for rec in sorted(base.glob("*/analysis/*/audio/separation.json")) if base.is_dir() else []:
            for name, sha in ((read_json(rec) or {}).get("stems_sha256") or {}).items():
                if isinstance(sha, str) and len(sha) == 64:
                    hashes.setdefault(sha, ("separation_record", f"{paths.relp(rec)}#{name}"))
        for f in reference_media_files():
            hashes[_sha_cached(f)] = ("reference_media", paths.relp(f))
        for f in stems:
            hashes[_sha_cached(f)] = ("stem", paths.relp(f))
        return cls(stems=stems, hashes=hashes)

    def copy_of(self, f: Path) -> dict | None:
        """{kind, matched, method, reason, ...} when ``f`` is reference audio, else None."""
        sha = _sha_cached(f)
        if sha in self.hashes:
            kind, what = self.hashes[sha]
            return {"kind": kind, "matched": what, "method": "sha256", "sha256": sha,
                    "reason": f"레퍼런스에서 나온 음원과 같은 파일(sha256 동일: {what}) — 깨끗한 음악 파일이 아님"}
        if not self.stems:
            return None
        key = (_stat_key(f), tuple(_stat_key(s) for s in self.stems))
        if key in _COPY_CACHE:
            return _COPY_CACHE[key]
        res = None
        try:
            x = _decoded(f)
        except Exception:                        # undecodable: identify() reports it; bytes were compared
            x = np.zeros(0)
        if len(x) >= STEM_COPY_MIN_S * STEM_COPY_SR:
            tol = int(STEM_COPY_LEN_TOL_S * STEM_COPY_SR)
            for s in self.stems:
                try:
                    y = _decoded(s)
                except Exception:
                    continue
                if len(x) > len(y) + tol:        # longer than the stem: cannot be a (trimmed) copy of it
                    continue
                a = np.concatenate([np.zeros(tol), y, np.zeros(tol)])
                ncc, lag = _ncc_inside(a, x)
                if ncc < STEM_COPY_NCC:
                    continue
                dev, act = _level_deviations(a[lag:lag + len(x)], x)
                if act and dev <= STEM_COPY_MAX_DEV_WIN:
                    res = {"kind": "stem", "matched": paths.relp(s), "method": "waveform", "ncc": round(ncc, 4),
                           "lag_s": round((lag - tol) / STEM_COPY_SR, 3), "deviating_windows": dev,
                           "active_windows": act,
                           "reason": (f"레퍼런스 분리 음원 {paths.relp(s)} 의 일부와 같은 파형(상관 {ncc:.3f} >= "
                                      f"{STEM_COPY_NCC}, 음량 변화까지 따라감: 어긋난 창 {dev}/{act}) — 깨끗한 음악 "
                                      "파일이 아님")}
                    break
        _COPY_CACHE[key] = res
        return res


def reference_audio_copy(path: str | os.PathLike) -> dict | None:
    """Public check: is ``path`` audio taken from a reference video (stem copy or reference media)?"""
    return ReferenceAudio.scan().copy_of(Path(path))


# ============================================================================ features
_FEAT_CACHE: dict[tuple, tuple[np.ndarray, np.ndarray]] = {}


def align_features(x: np.ndarray, sr: int = SR) -> np.ndarray:
    """Gain-invariant spectral-shape features [T, D] (hop FEAT_HOP, frames centred on i*hop)."""
    L = logmel(x, sr, FEAT_NFFT, FEAT_HOP, FEAT_MELS, fmax=FEAT_FMAX).astype(np.float64)
    level = L.max(axis=1)
    silent = level < max(-90.0, float(np.percentile(level, 99)) - 60.0) if len(level) else level < 0
    S = L - L.mean(axis=1, keepdims=True)
    mu = S[~silent].mean(0) if (~silent).any() else 0.0
    sd = S[~silent].std(0) + 1e-6 if (~silent).any() else 1.0
    S = (S - mu) / sd
    S[silent] = 0.0
    return S.astype(np.float32)


def _track_audio_and_features(track: LibraryTrack, sr: int = SR) -> tuple[np.ndarray, np.ndarray]:
    st = track.file.stat()
    key = (str(track.file), st.st_mtime_ns, st.st_size, sr)
    if key not in _FEAT_CACHE:
        a = load_mono(track.file, sr)
        _FEAT_CACHE.clear() if len(_FEAT_CACHE) > 16 else None
        _FEAT_CACHE[key] = (a, align_features(a, sr))
    return _FEAT_CACHE[key]


def _resample_frames(C: np.ndarray, r: float) -> np.ndarray:
    """C_r[j] = C[j*r] (linear interpolation along time)."""
    N = C.shape[0]
    n_out = int(np.floor((N - 1) / r)) + 1
    pos = np.arange(n_out) * r
    i0 = np.minimum(np.floor(pos).astype(int), N - 1)
    i1 = np.minimum(i0 + 1, N - 1)
    w = (pos - i0)[:, None]
    return (C[i0] * (1 - w) + C[i1] * w).astype(np.float32)


def _ncc_lags(R: np.ndarray, C: np.ndarray, min_overlap: int) -> tuple[np.ndarray, np.ndarray]:
    """Normalised cross-correlation for all lags L (ref frame i <-> clean frame i+L).

    Returns (lags, ncc) restricted to lags whose overlap is >= min_overlap frames."""
    M, N = R.shape[0], C.shape[0]
    nfft = 1 << int(np.ceil(np.log2(M + N + 1)))
    FR = np.fft.rfft(R, nfft, axis=0)
    FC = np.fft.rfft(C, nfft, axis=0)
    corr = np.fft.irfft((np.conj(FR) * FC).sum(axis=1), nfft)
    lags = np.arange(-(M - 1), N)
    num = corr[lags % nfft]
    er = np.concatenate([[0.0], np.cumsum((R.astype(np.float64) ** 2).sum(1))])
    ec = np.concatenate([[0.0], np.cumsum((C.astype(np.float64) ** 2).sum(1))])
    lo = np.maximum(0, -lags)
    hi = np.minimum(M, N - lags)
    ok = (hi - lo) >= min_overlap
    # the WHOLE reference energy is used (not only the overlap): dropping reference frames that the
    # clean file does not explain must never raise the score.
    ER = np.full(lags.shape, er[-1])
    EC = ec[np.clip(hi + lags, 0, N)] - ec[np.clip(lo + lags, 0, N)]
    den = np.sqrt(np.maximum(ER * EC, 1e-12))
    ncc = np.where(ok & (ER > 1e-9) & (EC > 1e-9), num / den, -1.0)
    return lags, ncc


def _peaks(ncc: np.ndarray, min_sep: int, k: int = 8) -> list[int]:
    order = np.argsort(ncc)[::-1]
    out: list[int] = []
    for i in order:
        if ncc[i] <= -1:
            break
        if all(abs(int(i) - j) >= min_sep for j in out):
            out.append(int(i))
            if len(out) >= k:
                break
    return out


def _parabolic(y: np.ndarray, i: int) -> float:
    if 0 < i < len(y) - 1:
        a, b, c = y[i - 1], y[i], y[i + 1]
        den = a - 2 * b + c
        if abs(den) > 1e-12:
            return float(i + 0.5 * (a - c) / den)
    return float(i)


def coarse_align(R: np.ndarray, C: np.ndarray, sr: int = SR, tempo_range=TEMPO_RANGE,
                 step: float = TEMPO_STEP_COARSE, fine_step: float = TEMPO_STEP_FINE) -> dict:
    """Search tempo ratio r and offset on feature sequences.

    Returns {"best": {r, lag, offset_s, ncc}, "by_r": [(r, ncc)], "repeats": [{offset_s, ncc}]}."""
    hop_s = FEAT_HOP / sr
    M = R.shape[0]

    def search(rs):
        res = []
        for r in rs:
            Cr = _resample_frames(C, r)
            min_ov = max(8, int(0.5 * min(M, Cr.shape[0])))
            lags, ncc = _ncc_lags(R, Cr, min_ov)
            i = int(np.argmax(ncc))
            res.append((float(ncc[i]), float(r), lags, ncc, i))
        return res

    lo, hi = tempo_range
    rs = np.round(np.arange(lo, hi + 1e-9, step), 6)
    coarse = search(rs)
    best = max(coarse, key=lambda z: z[0])
    rf = np.round(np.arange(best[1] - 1.2 * step, best[1] + 1.2 * step + 1e-9, fine_step), 6)
    rf = rf[(rf >= lo - 1e-9) & (rf <= hi + 1e-9)]
    fine = search(rf)
    bf = max(fine, key=lambda z: z[0])
    ncc_b, r_b, lags, ncc, i = bf
    lag = lags[0] + _parabolic(ncc, i)
    min_sep = max(1, int(round(1.0 / hop_s)))
    reps = []
    for j in _peaks(ncc, min_sep, k=10):
        lj = lags[0] + _parabolic(ncc, j)
        reps.append({"offset_s": round(float(lj * r_b * hop_s), 4), "ncc": round(float(ncc[j]), 4)})
    return {"best": {"r": r_b, "lag": float(lag), "offset_s": float(lag * r_b * hop_s), "ncc": float(ncc_b)},
            "by_r": [(z[1], round(z[0], 4)) for z in coarse], "repeats": reps}


# ============================================================================ waveform refinement
def _gcc_phat_locate(x: np.ndarray, y: np.ndarray, beta: float = 0.8) -> float | None:
    """Sample position of x inside y (x fully contained), GCC-PHAT(beta) with parabolic refinement."""
    if len(y) < len(x) or len(x) < 64:
        return None
    nfft = 1 << int(np.ceil(np.log2(len(x) + len(y))))
    X = np.fft.rfft(x, nfft)
    Y = np.fft.rfft(y, nfft)
    G = Y * np.conj(X)
    G = G / (np.abs(G) ** beta + 1e-12 * (np.abs(G).max() + 1e-30))
    g = np.fft.irfft(G, nfft)[:len(y) - len(x) + 1]
    k = int(np.argmax(g))
    return _parabolic(g, k)


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    a = a - a.mean()
    b = b - b.mean()
    d = float(np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / d) if d > 1e-12 else 0.0


def _preemph(x: np.ndarray) -> np.ndarray:
    return np.diff(x, prepend=x[:1]).astype(np.float32)


def aligned_waveform(clean: np.ndarray, sr: int, r: float, offset_s: float, n: int) -> tuple[np.ndarray, np.ndarray]:
    """Clean waveform at clean time offset + r*t for ref samples t = 0..n-1 (zeros outside the file).

    Returns (y, valid_mask)."""
    from scipy.signal import resample

    q0 = offset_s * sr
    a = int(np.floor(q0))
    frac = q0 - a
    need = int(np.ceil(n * r)) + 8
    seg = np.zeros(need, np.float32)
    s0, s1 = max(0, a), min(len(clean), a + need)
    if s1 > s0:
        seg[s0 - a:s1 - a] = clean[s0:s1]
    valid_src = np.zeros(need, bool)
    if s1 > s0:
        valid_src[s0 - a:s1 - a] = True
    if abs(r - 1.0) > 1e-7:
        m = int(round(need / r))
        seg = resample(seg, m).astype(np.float32)
        idx = np.minimum((np.arange(m) * r).astype(int), need - 1)
        valid_src = valid_src[idx]
        frac = frac / r
    y = fractional_delay(seg, -frac)
    out = np.zeros(n, np.float32)
    k = min(n, len(y))
    out[:k] = y[:k]
    valid = np.zeros(n, bool)
    valid[:min(n, len(valid_src))] = valid_src[:n]
    out[~valid] = 0.0
    return out, valid


def waveform_refine(ref: np.ndarray, clean: np.ndarray, sr: int, r0: float, off0: float,
                    n_probes: int = 8, win_s: float = 1.5, search_s: float = 0.06) -> dict | None:
    """Refine (r, offset) with GCC-PHAT probes and a weighted line fit; return coherence stats."""
    dur = len(ref) / sr
    if dur < win_s + 0.1:
        win_s = max(0.3, dur - 0.1)
    W = int(win_s * sr)
    starts = np.linspace(0.0, max(0.0, dur - win_s), n_probes)
    probes = []
    floor = max(1e-5, float(np.sqrt(np.mean(ref ** 2))) * 0.05)
    for t in starts:
        i0 = int(round(t * sr))
        x = ref[i0:i0 + W]
        if len(x) < W * 0.9 or float(np.sqrt(np.mean(x ** 2))) < floor:
            continue
        c = off0 + r0 * t
        j0 = int(np.floor((c - search_s) * sr))
        L = int(np.ceil((win_s * r0 + 2 * search_s) * sr))
        if j0 < 0 or j0 + L > len(clean):
            continue
        y = clean[j0:j0 + L]
        if float(np.sqrt(np.mean(y ** 2))) < 1e-5:
            continue
        pos = _gcc_phat_locate(_preemph(x), _preemph(y))
        if pos is None:
            continue
        cpos = (j0 + pos) / sr
        probes.append({"t": float(t), "clean_t": float(cpos)})
    if len(probes) < 2:
        return None
    t = np.array([p["t"] for p in probes])
    c = np.array([p["clean_t"] for p in probes])
    # start from the largest consensus set (probes on one line within 10 ms), not from all probes: when
    # the reference cut/restarted the music, probes of the other part would pull a least-squares line
    d = c - r0 * t
    votes = np.array([(np.abs(d - di) < 0.010).sum() for di in d])
    keep = np.abs(d - d[int(np.argmax(votes))]) < 0.010
    if keep.sum() < 2:
        keep = np.ones(len(t), bool)
    r, off = r0, off0
    for _ in range(3):
        if keep.sum() >= 2 and np.ptp(t[keep]) > 0.5:
            A = np.stack([np.ones(keep.sum()), t[keep]], 1)
            off, r = np.linalg.lstsq(A, c[keep], rcond=None)[0]
        else:
            off = float(np.median(c[keep] - r0 * t[keep]))
            r = r0
        res = np.abs(c - (off + r * t))
        new = res < 0.004
        if new.sum() < 2 or (new == keep).all():
            keep = new if new.sum() >= 2 else keep
            break
        keep = new
    if abs(r - 1.0) < 2e-5:
        r = 1.0
        off = float(np.median(c[keep] - t[keep])) if keep.any() else off
    # coherence: pre-emphasised waveform NCC on each probe window at the fitted line
    cohs = []
    for p in probes:
        i0 = int(round(p["t"] * sr))
        x = ref[i0:i0 + W]
        y, valid = aligned_waveform(clean, sr, r, off + r * p["t"], len(x))
        if valid.mean() < 0.9:
            continue
        coh = _ncc(_preemph(x), _preemph(y))
        p["coherence"] = round(coh, 4)
        p["residual_ms"] = round(1000 * float(abs(p["clean_t"] - (off + r * p["t"]))), 2)
        cohs.append(coh)
    if not cohs:
        return None
    # probes dominated by overlays (speech/SFX) have low coherence; the BGM-dominated ones decide
    return {"r": float(r), "offset_s": float(off), "coherence": float(np.percentile(cohs, 75)),
            "coherence_max": float(np.max(cohs)), "n_probes": len(probes), "n_inliers": int(keep.sum()),
            "probes": probes}


# ============================================================================ alignment
@dataclass
class Alignment:
    tempo_ratio: float
    offset_s: float                 # clean-file time at reference t = 0
    feature_ncc: float
    mode: str                       # waveform | spectral
    coherence: float | None
    ambiguous: bool
    section_candidates: list[dict]
    probes: list[dict]
    by_r: list = field(default_factory=list)

    def clean_t(self, t: float) -> float:
        return self.offset_s + self.tempo_ratio * t

    def to_dict(self) -> dict:
        d = asdict(self)
        d.pop("by_r", None)
        return d


def align(ref: np.ndarray, clean: np.ndarray, sr: int = SR, ref_feat: np.ndarray | None = None,
          clean_feat: np.ndarray | None = None, tempo_range=TEMPO_RANGE, coarse: dict | None = None) -> Alignment:
    """Align a reference mix (or its vocals-removed version) to one clean music file."""
    if coarse is None:
        R = align_features(ref, sr) if ref_feat is None else ref_feat
        C = align_features(clean, sr) if clean_feat is None else clean_feat
        coarse = coarse_align(R, C, sr, tempo_range)
    co = coarse
    b = co["best"]
    r0, off0 = b["r"], b["offset_s"]
    cands = [{"offset_s": off0, "ncc": b["ncc"]}]
    for rep in co["repeats"]:
        if abs(rep["offset_s"] - off0) > 1.0 and rep["ncc"] >= b["ncc"] - REPEAT_NCC_BAND:
            cands.append(rep)
    if abs(r0 - 1.0) <= WAVEFORM_MAX_DEV:
        refined = []
        for cnd in cands:
            wr = waveform_refine(ref, clean, sr, r0, cnd["offset_s"])
            if wr is not None:
                refined.append((wr, cnd))
        # accepted when several probes sit on one line (sub-ms) and some probe matches the waveform well
        good = [z for z in refined if z[0]["n_inliers"] >= min(3, z[0]["n_probes"])
                and z[0]["coherence_max"] >= MIN_COHERENCE_MAX and z[0]["coherence"] >= MIN_COHERENCE]
        if good:
            good.sort(key=lambda z: -z[0]["coherence"])
            wr, cnd = good[0]
            others = [{"offset_s": round(z[0]["offset_s"], 4), "coherence": round(z[0]["coherence"], 4),
                       "feature_ncc": round(z[1]["ncc"], 4)} for z in refined]
            amb = [o for o in others if abs(o["offset_s"] - wr["offset_s"]) > 1.0
                   and o["coherence"] >= wr["coherence"] - AMBIG_COHERENCE]
            return Alignment(tempo_ratio=wr["r"], offset_s=wr["offset_s"], feature_ncc=b["ncc"], mode="waveform",
                             coherence=wr["coherence"], ambiguous=bool(amb), section_candidates=others,
                             probes=wr["probes"], by_r=co["by_r"])
    # spectral mode (the reference re-timed the file): verify each candidate offset with short-window
    # waveform matching (time-stretch keeps short grains intact; repeated sections do not share them).
    scored = []
    scores = local_waveform_coherence(ref, clean, sr, r0, [c["offset_s"] for c in cands])
    for cnd, sc in zip(cands, scores):
        scored.append({"offset_s": round(cnd["offset_s"], 4), "feature_ncc": round(cnd["ncc"], 4),
                       "local_coherence": None if sc is None else round(sc, 4)})
    scored.sort(key=lambda o: -(o["local_coherence"] if o["local_coherence"] is not None else -1))
    top = scored[0]
    amb = [o for o in scored[1:] if o["local_coherence"] is not None and top["local_coherence"] is not None
           and abs(o["offset_s"] - top["offset_s"]) > 1.0
           and o["local_coherence"] >= top["local_coherence"] - AMBIG_LOCAL_COHERENCE]
    return Alignment(tempo_ratio=r0, offset_s=float(top["offset_s"]), feature_ncc=b["ncc"], mode="spectral",
                     coherence=top["local_coherence"], ambiguous=bool(amb), section_candidates=scored, probes=[],
                     by_r=co["by_r"])


def local_waveform_coherence(ref: np.ndarray, clean: np.ndarray, sr: int, r: float, offsets: list[float],
                             n_win: int = 300, win_s: float = 0.03, search_s: float = 0.015) -> list[float | None]:
    """Short-window waveform match along the lines clean_t = offset + r*t (one score per offset).

    Time-stretching (WSOLA/atempo) copies short grains of the original waveform, so ~30 ms windows of
    the reference are found almost exactly in the clean file near the predicted position; a repeated
    section that only *sounds* the same fails on the windows whose content differs (fills, noise,
    transients).  Score = mean of the lowest quartile of per-window best pre-emphasised NCC (within
    +-search_s), computed on the reference windows that every candidate covers, so overlays
    (speech/SFX) and coverage affect all candidates equally."""
    W = int(win_s * sr)
    S = int(search_s * sr)
    dur = len(ref) / sr
    xs = _preemph(ref)
    cs = _preemph(clean)
    lvl = float(np.sqrt(np.mean(xs ** 2))) + 1e-12
    ts = np.linspace(0.05, max(0.05, dur - win_s - 0.05), n_win)
    table = np.full((len(offsets), len(ts)), np.nan)
    for k, t in enumerate(ts):
        i0 = int(t * sr)
        x = xs[i0:i0 + W]
        if len(x) < W or float(np.sqrt(np.mean(x ** 2))) < 0.1 * lvl:
            continue
        xc = x - x.mean()
        nx = np.linalg.norm(xc)
        for j, off in enumerate(offsets):
            c = int(round((off + r * t) * sr))
            if c - S < 0 or c + W + S > len(cs):
                continue
            y = cs[c - S:c + W + S]
            yy = np.lib.stride_tricks.sliding_window_view(y, W)
            yc = yy - yy.mean(1, keepdims=True)
            den = np.linalg.norm(yc, axis=1) * nx + 1e-12
            table[j, k] = float(np.max((yc @ xc) / den))
    common = ~np.isnan(table).any(axis=0)
    out: list[float | None] = []
    for j in range(len(offsets)):
        row = table[j, common] if common.sum() >= 8 else np.nan_to_num(table[j], nan=0.0)[~np.isnan(table).all(0)]
        if len(row) < 8:
            out.append(None)
            continue
        v = np.sort(row)
        out.append(float(v[: max(2, len(v) // 4)].mean()))
    return out


_MAG_CACHE: dict[tuple, np.ndarray] = {}


def _clean_mag_cached(clean: np.ndarray, sr: int) -> np.ndarray:
    key = (id(clean), len(clean), sr, float(clean[: min(len(clean), 4096)].sum()))
    if key not in _MAG_CACHE:
        if len(_MAG_CACHE) > 8:
            _MAG_CACHE.clear()
        _MAG_CACHE[key] = np.abs(stft(clean, SPEC_NFFT, SPEC_HOP)).astype(np.float32)
    return _MAG_CACHE[key]


# ============================================================================ gain curve
@dataclass
class BgmModel:
    """Aligned clean BGM for one reference, plus its gain curve (used by original/sfx modules)."""
    mode: str
    sr: int
    aligned: np.ndarray | None          # waveform mode: clean waveform aligned to ref samples (unit gain)
    valid: np.ndarray | None            # waveform mode: sample mask inside the clean file
    t: np.ndarray                       # gain curve times (s)
    gain: np.ndarray                    # linear gain of the clean file in the mix
    gain_db: np.ndarray
    clean_on: np.ndarray                # clean file has signal at that time (bool per curve point)
    hop_s: float
    mag_aligned: np.ndarray | None = None   # spectral mode: |STFT| of clean aligned to ref frames (n_fft 2048/hop 256)
    clean: np.ndarray | None = None         # the clean file (mono, sr) for other resolutions
    tempo_ratio: float = 1.0
    offset_s: float = 0.0

    def aligned_mag(self, n_fft: int, hop: int, n_frames: int) -> np.ndarray | None:
        """|STFT| of the clean file at another resolution, aligned to reference frames (unit gain)."""
        if self.clean is None:
            return None
        Cm = np.abs(stft(self.clean, n_fft, hop))
        hop_s = hop / self.sr
        pos = (self.offset_s + self.tempo_ratio * np.arange(n_frames) * hop_s) / hop_s
        out = np.zeros((n_frames, Cm.shape[1]), np.float32)
        ok = (pos >= 0) & (pos <= Cm.shape[0] - 1)
        p = pos[ok]
        i0 = np.floor(p).astype(int)
        i1 = np.minimum(i0 + 1, Cm.shape[0] - 1)
        w = (p - i0)[:, None]
        out[ok] = Cm[i0] * (1 - w) + Cm[i1] * w
        return out

    def gain_at(self, t: np.ndarray | float) -> np.ndarray:
        return np.interp(t, self.t, self.gain, left=0.0, right=0.0)

    def gain_samples(self, n: int) -> np.ndarray:
        return self.gain_at(np.arange(n) / self.sr).astype(np.float32)

    def estimate(self, n: int) -> np.ndarray | None:
        """g(t) * aligned clean (waveform mode only)."""
        if self.aligned is None:
            return None
        return (self.gain_samples(n) * self.aligned[:n]).astype(np.float32)


SPEC_NFFT, SPEC_HOP = 2048, 256


def _medfilt(x: np.ndarray, k: int) -> np.ndarray:
    from scipy.signal import medfilt

    return medfilt(x, k) if len(x) >= k else x


def gain_curve_waveform(b: np.ndarray, c: np.ndarray, sr: int, win_s: float = GAIN_WIN_S,
                        hop_s: float = GAIN_HOP_S) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    from .separation import frame_signal

    win = int(round(win_s * sr))
    hop = int(round(hop_s * sr))
    w = np.hanning(win).astype(np.float64)
    B = frame_signal(b, win, hop).astype(np.float64)
    Cf = frame_signal(c, win, hop).astype(np.float64)
    num = (B * Cf * w).sum(1)
    den = (Cf * Cf * w).sum(1)
    ref_den = np.percentile(den[den > 0], 90) if (den > 0).any() else 1.0
    on = den > ref_den * 1e-4
    g = np.where(on, num / np.maximum(den, 1e-12), 0.0)
    g = np.maximum(g, 0.0)
    g = _medfilt(g, 5)
    return np.arange(len(g)) * hop / sr, g, on


def gain_curve_spectral(B: np.ndarray, Cm: np.ndarray, sr: int, hop: int = SPEC_HOP) -> tuple[np.ndarray, ...]:
    """Per-frame BGM gain from mel-band energy ratios (reference vs aligned clean magnitude).

    Band energies are stable under time-stretching (individual bins are not); the median over the
    bands where the clean music has energy is robust to other sources that dominate a few bands."""
    from .separation import mel_filterbank

    T = min(B.shape[0], Cm.shape[0])
    fb = mel_filterbank(sr, SPEC_NFFT, 40, fmax=min(sr / 2, 10000.0))
    Pb = (np.abs(B[:T]) ** 2) @ fb.T
    Pc = (Cm[:T].astype(np.float64) ** 2) @ fb.T
    e = Pc.sum(1)
    ref_e = np.percentile(e[e > 0], 90) if (e > 0).any() else 1.0
    on = e > ref_e * 1e-3
    g_db = np.full(T, -100.0)
    for i in np.nonzero(on)[0]:
        pc = Pc[i]
        sel = pc > pc.max() * 1e-3
        if sel.sum() < 3:
            continue
        g_db[i] = float(np.median(10 * np.log10(np.maximum(Pb[i, sel], 1e-20) / pc[sel])))
    g_db = _medfilt(g_db, 9)
    g = np.where(on, 10 ** (g_db / 20), 0.0)
    return np.arange(T) * hop / sr, g, on


def aligned_magnitude(clean: np.ndarray, sr: int, r: float, offset_s: float, n_frames: int) -> np.ndarray:
    Cm = _clean_mag_cached(clean, sr)
    hop_s = SPEC_HOP / sr
    pos = (offset_s + r * np.arange(n_frames) * hop_s) / hop_s
    out = np.zeros((n_frames, Cm.shape[1]), np.float32)
    ok = (pos >= 0) & (pos <= Cm.shape[0] - 1)
    p = pos[ok]
    i0 = np.floor(p).astype(int)
    i1 = np.minimum(i0 + 1, Cm.shape[0] - 1)
    w = (p - i0)[:, None]
    out[ok] = Cm[i0] * (1 - w) + Cm[i1] * w
    return out


def build_bgm_model(bgm_sig: np.ndarray, clean: np.ndarray, sr: int, al: Alignment) -> BgmModel:
    n = len(bgm_sig)
    if al.mode == "waveform":
        y, valid = aligned_waveform(clean, sr, al.tempo_ratio, al.offset_s, n)
        t, g, on = gain_curve_waveform(bgm_sig, y, sr)
        return BgmModel(mode="waveform", sr=sr, aligned=y, valid=valid, t=t, gain=g,
                        gain_db=20 * np.log10(np.maximum(g, 1e-5)), clean_on=on, hop_s=GAIN_HOP_S, clean=clean,
                        tempo_ratio=al.tempo_ratio, offset_s=al.offset_s)
    B = stft(bgm_sig, SPEC_NFFT, SPEC_HOP)
    Cm = aligned_magnitude(clean, sr, al.tempo_ratio, al.offset_s, B.shape[0])
    t, g, on = gain_curve_spectral(B, Cm, sr)
    return BgmModel(mode="spectral", sr=sr, aligned=None, valid=None, t=t, gain=g,
                    gain_db=20 * np.log10(np.maximum(g, 1e-5)), clean_on=on, hop_s=SPEC_HOP / sr, mag_aligned=Cm,
                    clean=clean, tempo_ratio=al.tempo_ratio, offset_s=al.offset_s)


def _runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) index runs of True."""
    m = np.concatenate([[False], mask.astype(bool), [False]])
    d = np.diff(m.astype(int))
    return list(zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]))


def describe_gain(model: BgmModel, speech_mask_fn=None) -> dict:
    """Base level, presence, used range, cuts and fades from the gain curve."""
    t, gdb, on = model.t, model.gain_db, model.clean_on
    hop = float(np.median(np.diff(t))) if len(t) > 1 else model.hop_s
    audible = on & (gdb > -60)
    if audible.sum() < max(3, int(0.3 / hop)):
        return {"present": False}
    base_all = float(np.percentile(gdb[audible], 75))
    present = on & (gdb > base_all - PRESENT_BELOW_BASE_DB)
    idx = np.nonzero(present)[0]
    t_start, t_end = float(t[idx[0]]), float(t[idx[-1]])
    speech = speech_mask_fn(t) if speech_mask_fn is not None else np.zeros(len(t), bool)
    free = present & ~speech
    if free.sum() >= 3:
        base = float(np.median(gdb[free]))
        base_method = "BGM 있음·대사 없음 구간 LS 이득 중앙값"
    else:
        base = base_all
        base_method = "BGM 있음 구간 LS 이득 p75 (대사 구간 정보 없음)"
    cuts = []
    inner = np.zeros(len(t), bool)
    inner[idx[0]:idx[-1] + 1] = True
    for a, b in _runs(inner & ~present):
        if (b - a) * hop >= CUT_MIN_S:
            cuts.append({"start": round(float(t[a]), 3), "end": round(float(t[b - 1] + hop), 3)})

    def ramp(seq_t, seq_db, reverse=False):
        # linear-amplitude fade model (ffmpeg afade 'tri'): -25 dB -> -1.5 dB spans 0.785 of the fade
        if reverse:
            seq_t, seq_db = seq_t[::-1], seq_db[::-1]
        lo = np.nonzero(seq_db >= base - 25)[0]
        hi = np.nonzero(seq_db >= base - 1.5)[0]
        if not len(lo) or not len(hi):
            return None
        span = abs(float(seq_t[hi[0]] - seq_t[lo[0]]))
        return round(span / 0.785, 3) if span > 1.5 * hop else 0.0

    a0 = idx[0]
    win_in = slice(a0, min(len(t), a0 + int(4.0 / hop)))
    b1 = idx[-1] + 1
    win_out = slice(max(0, b1 - int(4.0 / hop)), b1)
    fade_in = ramp(t[win_in], gdb[win_in])
    fade_out = ramp(t[win_out], gdb[win_out], reverse=True)
    return {"present": True, "base_db": round(base, 2), "base_method": base_method, "used_start": round(t_start, 3),
            "used_end": round(t_end + hop, 3), "cuts": cuts, "fade_in_s": fade_in, "fade_out_s": fade_out,
            "present_mask": present}


# ============================================================================ restart / loop
def detect_restarts(bgm_sig: np.ndarray, clean: np.ndarray, sr: int, al: Alignment,
                    clean_feat: np.ndarray | None = None) -> dict:
    """Does the BGM restart (jump back to an earlier point of the same clean file) inside the video?

    The reference BGM signal is cut into LOOP_WIN_S windows (hop LOOP_HOP_S); each window is aligned
    against the SAME clean file at the identified tempo (gain-invariant feature NCC over all offsets,
    window fully inside the file).  A window stays on the main line when the main line is (nearly,
    LOOP_TIE) the best feature match.  Otherwise the candidate offsets (main line + feature peaks within
    REPEAT_NCC_BAND of the best, NCC >= LOOP_MIN_NCC) are verified:
      waveform mode: GCC-PHAT probe line fit + pre-emphasised waveform coherence (the same test as the
        main alignment); the highest coherence wins, the main line wins ties (AMBIG_COHERENCE);
      spectral mode (re-timed file, no waveform test): best feature offset, NCC >= LOOP_SPECTRAL_NCC,
        better than the main line by LOOP_MARGIN, on >= 2 consecutive windows.
    Consecutive lines in time order give jumps: clean offset change < -LOOP_JUMP_S = restart (loop),
    > +LOOP_JUMP_S = forward skip.

    presence: present = at least one restart; absent = no restart and the main line explains >= 1
    window; unmeasured otherwise.  Repeats shorter than one window cannot be detected (``limits``); a
    restart into a part that sounds identical to the main line is not distinguishable (and not audible)."""
    hop_s = FEAT_HOP / sr
    r = float(al.tempo_ratio)
    waveform = al.mode == "waveform"
    method = (f"{LOOP_WIN_S:g} s 창(간격 {LOOP_HOP_S:g} s)마다 같은 깨끗한 음원과 특징 NCC 정렬(속도 {r:.4f} 고정); "
              f"주 정렬선이 최고 점수(차 {LOOP_TIE} 이내)면 유지, 아니면 후보 시작점(주 정렬선 + 특징 봉우리) 검증 — "
              + ("파형 모드: GCC-PHAT 탐침 직선 + 파형 일치도 최고(동률이면 주 정렬선)" if waveform else
                 f"스펙트럼 모드: 특징 NCC >= {LOOP_SPECTRAL_NCC}, 주 정렬선보다 +{LOOP_MARGIN}, 연속 2창 이상")
              + f" → 시간순 정렬선 사이 시작점 변화 < -{LOOP_JUMP_S:g} s = 되감김(반복), > +{LOOP_JUMP_S:g} s = 건너뜀")
    limits = [f"{LOOP_WIN_S:g} s 보다 짧은 반복 구간은 검출 불가",
              "주 정렬선과 소리가 같은 구간으로의 되감김은 구분 불가(들리는 차이도 없음)"]
    R = align_features(bgm_sig, sr)
    C = align_features(clean, sr) if clean_feat is None else clean_feat
    Cr = _resample_frames(C, r)
    M = max(8, int(round(LOOP_WIN_S / hop_s)))
    H = max(1, int(round(LOOP_HOP_S / hop_s)))
    if R.shape[0] < M or Cr.shape[0] < M:
        return {"presence": "unmeasured", "status": "unmeasured", "method": method, "limits": limits,
                "blocker": f"영상 또는 음원이 분석 창({LOOP_WIN_S:g} s)보다 짧음", "windows": [], "jumps": [],
                "segments": []}
    main_lag = al.offset_s / (r * hop_s)            # Cr frame = ref frame + main_lag
    wlen = int(round(LOOP_WIN_S * sr))

    def verify(seg: np.ndarray, t0: float, off: float) -> tuple[float | None, float]:
        """(waveform coherence if the probes fit one line, refined offset at reference t = 0)."""
        wr = waveform_refine(seg, clean, sr, r, off + r * t0, n_probes=4, win_s=0.75)
        if not wr or wr["n_inliers"] < min(3, wr["n_probes"]) or wr["coherence_max"] < MIN_COHERENCE_MAX \
                or wr["coherence"] < MIN_COHERENCE:
            return None, off
        return float(wr["coherence"]), float(wr["offset_s"] - r * t0)

    wins = []
    for i0 in range(0, R.shape[0] - M + 1, H):
        Rw = R[i0:i0 + M]
        t0 = round(i0 * hop_s, 3)
        if float(np.mean(np.abs(Rw).sum(1) == 0)) > 0.5:
            wins.append({"t": t0, "label": "quiet"})
            continue
        lags, ncc = _ncc_lags(Rw, Cr, M)
        k = int(np.argmax(ncc))
        best = float(ncc[k])
        j = i0 + main_lag + (M - 1)                   # index of the main-line lag in `lags`
        on = [ncc[q] for q in (int(np.floor(j)), int(np.ceil(j))) if 0 <= q < len(ncc)]
        n_main = float(max(on)) if on else -1.0
        rec = {"t": t0, "ncc_main": round(n_main, 4), "ncc_best": round(best, 4)}
        main_ok = n_main > -1 and n_main >= LOOP_MIN_NCC - 0.2
        if main_ok and n_main >= best - LOOP_TIE:
            rec.update({"label": "main", "offset_s": round(al.offset_s, 3)})
            wins.append(rec)
            continue
        if best < LOOP_MIN_NCC:
            rec.update({"label": "main", "offset_s": round(al.offset_s, 3)} if main_ok and n_main >= best - LOOP_MARGIN
                       else {"label": "unexplained"})
            wins.append(rec)
            continue
        offs = []
        for q in _peaks(ncc, max(1, int(round(1.0 / hop_s))), k=6):
            if ncc[q] < max(LOOP_MIN_NCC, best - REPEAT_NCC_BAND):
                continue
            off = (float(lags[0] + _parabolic(ncc, q)) - i0) * r * hop_s   # clean time at reference t = 0
            if abs(off - al.offset_s) > LOOP_LINE_TOL_S:
                offs.append((off, float(ncc[q])))
        if waveform:
            seg = bgm_sig[int(round(t0 * sr)):int(round(t0 * sr)) + wlen]
            coh_main = verify(seg, t0, al.offset_s)[0] if main_ok else None
            scored = []
            for off, nc in offs:
                coh, off_r = verify(seg, t0, off)
                if coh is not None:
                    scored.append((coh, off_r, nc))
            rec["coherence_main"] = None if coh_main is None else round(coh_main, 4)
            top = max(scored) if scored else None
            if top and (coh_main is None or top[0] > coh_main + AMBIG_COHERENCE):
                rec.update({"label": "other", "offset_s": round(top[1], 3), "coherence": round(top[0], 4),
                            "verified": "waveform"})
            elif coh_main is not None or (main_ok and n_main >= best - LOOP_MARGIN):
                rec.update({"label": "main", "offset_s": round(al.offset_s, 3)})
            else:
                rec["label"] = "unexplained"
        else:
            if offs and best >= LOOP_SPECTRAL_NCC and (not main_ok or best >= n_main + LOOP_MARGIN):
                off, nc = max(offs, key=lambda z: z[1])
                rec.update({"label": "other", "offset_s": round(off, 3), "verified": "feature"})
            elif main_ok:
                rec.update({"label": "main", "offset_s": round(al.offset_s, 3)})
            else:
                rec["label"] = "unexplained"
        wins.append(rec)
    # group consecutive line windows into segments (a line may be interrupted by quiet/unexplained windows)
    segs: list[dict] = []
    for w in wins:
        if w["label"] not in ("main", "other") or (w["label"] == "other" and not w.get("verified")):
            continue
        if segs and segs[-1]["label"] == w["label"] and abs(segs[-1]["offset_s"] - w["offset_s"]) <= LOOP_LINE_TOL_S:
            segs[-1]["end"] = round(w["t"] + LOOP_WIN_S, 3)
            segs[-1]["last_start"] = w["t"]
            segs[-1]["n_windows"] += 1
            continue
        segs.append({"label": w["label"], "start": w["t"], "end": round(w["t"] + LOOP_WIN_S, 3), "last_start": w["t"],
                     "offset_s": w["offset_s"], "n_windows": 1, "verified": w.get("verified") or "main_line"})
    if not waveform:                                   # spectral mode: a lone window is not enough evidence
        segs = [s for s in segs if s["label"] == "main" or s["n_windows"] >= 2]
    jumps = []
    for a, b in zip(segs, segs[1:]):
        d = b["offset_s"] - a["offset_s"]
        if abs(d) <= LOOP_JUMP_S:
            continue
        # change point: between the last window of line a and the first window of line b, the frame where
        # line b starts to explain the features better than line a (least-squares split of the difference)
        lo, hi = a["last_start"], b["start"] + LOOP_WIN_S
        tj = _change_point(R, Cr, lo, hi, a["offset_s"], b["offset_s"], r, hop_s)
        jumps.append({"t": tj, "t_range": [round(a["last_start"] + LOOP_WIN_S / 2, 3),
                                           round(b["start"] + LOOP_WIN_S / 2, 3)],
                      "from_offset_s": a["offset_s"],
                      "to_offset_s": b["offset_s"], "jump_s": round(d, 3), "kind": "restart" if d < 0 else "skip",
                      "clean_t_before": round(a["offset_s"] + r * tj, 3),
                      "clean_t_after": round(b["offset_s"] + r * tj, 3)})
    n_main = sum(1 for w in wins if w["label"] == "main")
    if any(j["kind"] == "restart" for j in jumps):
        presence = "present"
    elif n_main:
        presence = "absent"
    else:
        presence = "unmeasured"
    unexplained = [w["t"] for w in wins if w["label"] == "unexplained"]
    out = {"presence": presence, "status": "measured" if presence != "unmeasured" else "unmeasured",
           "method": method, "limits": limits, "segments": segs, "jumps": jumps,
           "unexplained_window_starts": unexplained, "windows": wins}
    if presence == "unmeasured":
        out["blocker"] = "주 정렬선이 설명하는 창이 없음"
    return out


def _change_point(R: np.ndarray, Cr: np.ndarray, t_lo: float, t_hi: float, off_a: float, off_b: float, r: float,
                  hop_s: float) -> float:
    """Time in [t_lo, t_hi] where line b (clean = off_b + r*t) takes over from line a, from per-frame
    feature cosine similarity (split point maximising sum(a before) + sum(b after))."""
    i_lo, i_hi = max(0, int(t_lo / hop_s)), min(R.shape[0], int(np.ceil(t_hi / hop_s)))

    def sim(off: float) -> np.ndarray:
        idx = np.arange(i_lo, i_hi) + int(round(off / (r * hop_s)))
        ok = (idx >= 0) & (idx < Cr.shape[0])
        out = np.zeros(i_hi - i_lo)
        x = R[i_lo:i_hi][ok]
        y = Cr[idx[ok]]
        den = np.linalg.norm(x, axis=1) * np.linalg.norm(y, axis=1)
        out[ok] = np.where(den > 1e-9, (x * y).sum(1) / np.maximum(den, 1e-9), 0.0)
        return out

    if i_hi - i_lo < 2:
        return round(t_lo, 3)
    d = sim(off_b) - sim(off_a)                  # > 0 where line b explains better
    # score(k) = -sum(d[:k]) + sum(d[k:]) -> maximise
    cs = np.concatenate([[0.0], np.cumsum(d)])
    score = (cs[-1] - cs) - cs
    k = int(np.argmax(score))
    return round((i_lo + k) * hop_s, 3)


# ============================================================================ identification
def identify(ref: np.ndarray, sr: int = SR, library: list[LibraryTrack] | None = None,
             tempo_range=TEMPO_RANGE) -> dict:
    """Rank library files against the reference; choose track + version per the documented rules."""
    lib = load_library() if library is None else library
    if not lib:
        return {"status": "unmeasured", "blocker": "음악 라이브러리가 비어 있음(assets/library/music, local.yaml "
                                                   "music_library_root)", "candidates": []}
    R = align_features(ref, sr)
    coarse = []
    for tr in lib:
        clean, C = _track_audio_and_features(tr, sr)
        coarse.append((tr, coarse_align(R, C, sr, tempo_range)))
    top = max(c[1]["best"]["ncc"] for c in coarse)
    cands = []
    for tr, co in coarse:
        if co["best"]["ncc"] >= max(ID_MIN_SCORE, top - 0.15):
            clean, _ = _track_audio_and_features(tr, sr)
            al = align(ref, clean, sr, coarse=co)      # verification only for plausible files
        else:
            al = Alignment(tempo_ratio=co["best"]["r"], offset_s=co["best"]["offset_s"], feature_ncc=co["best"]["ncc"],
                           mode="coarse_only", coherence=None, ambiguous=False, section_candidates=[], probes=[])
        cands.append({"track": tr, "alignment": al, "ncc": al.feature_ncc})
    cands.sort(key=lambda z: -z["ncc"])
    best = cands[0]
    other_songs = [c for c in cands if c["track"].song != best["track"].song]
    margin = best["ncc"] - (other_songs[0]["ncc"] if other_songs else 0.0)
    same = [c for c in cands if c["track"].song == best["track"].song and c["ncc"] >= best["ncc"] - VERSION_TIE]
    why = "최고 점수"
    exact = [c for c in same if abs(c["alignment"].tempo_ratio - 1.0) <= TEMPO_TOL]
    if exact:
        exact.sort(key=lambda c: (-(c["alignment"].coherence or 0.0), -c["ncc"]))
        chosen = exact[0]
        why = "같은 곡 후보 중 속도 1.0 에 맞는 버전(그 파일 그대로 사용된 것으로 설명됨)"
    else:
        orig = [c for c in same if (c["track"].version or "").lower() == "original"]
        chosen = orig[0] if orig else best
        why = "같은 곡 후보 모두 재생속도 변경 필요 → 원곡(original) 버전 기준으로 속도 보고" if orig else why
    identified = best["ncc"] >= ID_MIN_SCORE and margin >= ID_MIN_MARGIN
    return {"status": "measured" if identified else "unmeasured",
            "blocker": None if identified else (
                f"라이브러리에서 확실한 일치 곡 없음 (최고 {best['ncc']:.2f}, 차이 {margin:.2f}; 기준 "
                f"{ID_MIN_SCORE}/{ID_MIN_MARGIN})"),
            "chosen": chosen if identified else None, "why": why if identified else None, "margin": margin,
            "candidates": cands}


def is_match(expected: dict, observed: dict, tempo_tol: float = TEMPO_TOL, offset_tol_s: float = OFFSET_TOL_S) -> dict:
    """User rule: same song (title) AND same version AND tempo within tol AND section start within tol.

    ``expected``/``observed``: {track_id?, song?|title?, version, tempo_ratio, section_start_s}.
    ``track_id`` (library file entry) is compared when both sides give it; the song is compared as
    ``song`` if given, else ``title``.  A different part of the same song (offset outside the
    tolerance) is NOT a match; anything missing makes the result ``unmeasured``, never ``same``."""
    checks = {}
    if expected.get("track_id") is not None and observed.get("track_id") is not None:
        checks["track_id"] = str(expected["track_id"]) == str(observed["track_id"])
    sk = "song" if (expected.get("song") is not None or observed.get("song") is not None) else "title"
    if expected.get(sk) is None and observed.get(sk) is None and "track_id" in checks:
        pass                                               # track_id already identifies the song
    else:
        a, b = expected.get(sk), observed.get(sk)
        checks[sk] = None if a is None or b is None else (str(a) == str(b))
    a, b = expected.get("version"), observed.get("version")
    checks["version"] = None if a is None or b is None else (str(a) == str(b))
    for k, tol in (("tempo_ratio", tempo_tol), ("section_start_s", offset_tol_s)):
        a, b = expected.get(k), observed.get(k)
        checks[k] = None if a is None or b is None else bool(abs(float(a) - float(b)) <= tol)
    if any(v is False for v in checks.values()):
        status = "different"
    elif any(v is None for v in checks.values()):
        status = "unmeasured"
    else:
        status = "same"
    return {"match": status == "same", "status": status, "checks": checks,
            "tolerance": {"tempo_ratio": tempo_tol, "section_start_s": offset_tol_s}}


# ============================================================================ online recognizer (hint only)
def online_recognize(path: Path) -> dict:
    """shazamio hint (title/artist only; never a substitute for the clean-library match).

    NOT tested on the build machine (shazamio not installed; network policy)."""
    try:
        import asyncio

        from shazamio import Shazam  # type: ignore
    except Exception as e:
        return {"status": "not_installed", "note": f"shazamio 없음: {type(e).__name__}"}
    try:
        sh = Shazam()
        fn = getattr(sh, "recognize", None) or getattr(sh, "recognize_song")
        out = asyncio.run(fn(str(path)))
        tr = (out or {}).get("track") or {}
        return {"status": "hint", "title": tr.get("title"), "artist": tr.get("subtitle"), "key": tr.get("key"),
                "note": "온라인 인식 결과는 힌트일 뿐 — 버전/속도/구간은 깨끗한 음원 대조로만 확정"}
    except Exception as e:
        return {"status": "error", "note": f"{type(e).__name__}: {str(e)[:200]}"}


# ============================================================================ per-video analysis
def bgm_path(preset_name: str, video_id: str) -> Path:
    return audio_dir(preset_name, video_id) / "bgm.json"


def _field(value, status="measured", **kw) -> dict:
    return {"value": value, "status": status if value is not None or status != "measured" else "unmeasured", **kw}


def speech_mask_from_vocals(vocals: np.ndarray | None, sr: int):
    """Callable t -> bool mask of speech presence from a vocals stem (None if no stem)."""
    if vocals is None:
        return None
    from .audio_original import speech_segments_from_stem

    segs = speech_segments_from_stem(vocals, sr)

    def f(t):
        m = np.zeros(len(t), bool)
        for s in segs:
            m |= (t >= s["start"]) & (t <= s["end"])
        return m

    return f


def analyze_bgm(preset_name: str, video_id: str, audio_path: str | os.PathLike | None = None,
                stems: Stems | None = None, separator_status: dict | None = None,
                library: list[LibraryTrack] | None = None, online: bool = False, write: bool = True) -> dict:
    src = Path(audio_path) if audio_path else find_reference_media(preset_name, video_id)
    out: dict = {"schema": SCHEMA, "video_id": video_id, "analyzed_at": now_iso(), "criteria": CRITERIA}
    if src is None or not src.is_file():
        out.update({"status": "unmeasured", "presence": "unmeasured",
                    "blocker": f"레퍼런스 원본 파일 없음(video_id={video_id}) — 다운로드 전/차단"})
        if write:
            write_json(bgm_path(preset_name, video_id), out)
        return out
    if stems is None:
        from .separation import load_cached_stems

        stems = load_cached_stems(preset_name, video_id, audio_path=src)
    mix = load_mono(src, SR)
    vocals = stems.vocals if stems is not None else None
    bgm_sig = mix.copy()
    if vocals is not None:
        n = min(len(mix), len(vocals))
        bgm_sig[:n] = mix[:n] - vocals[:n]
    sep = separator_status or ({"status": "measured", "model": stems.model, "model_version": stems.model_version}
                               if stems is not None else _separation_status(preset_name, video_id))
    out.update({"audio_file": rel_or_none(src), "audio_sha256": sha256_file(src), "duration_s": round(len(mix) / SR, 3),
                "separator": sep,
                "signal": "mix - vocals stem" if vocals is not None else "mix (vocals stem 없음)"})
    refused: list[dict] = []
    lib = load_library(rejected=refused) if library is None else library
    out["library"] = {"n_files": len(lib), "roots": [tok or rel_or_none(p) for tok, p in library_roots()],
                      "refused_reference_audio": refused}
    ident = identify(bgm_sig, SR, lib)
    cands_json = []
    for c in ident.get("candidates", [])[:8]:
        al: Alignment = c["alignment"]
        cands_json.append({"track_id": c["track"].track_id, "song": c["track"].song_id or c["track"].title,
                           "version": c["track"].version, "file": c["track"].stored,
                           "feature_ncc": round(c["ncc"], 4), "tempo_ratio": round(al.tempo_ratio, 5),
                           "section_start_s": round(al.offset_s, 3), "mode": al.mode,
                           "coherence": None if al.coherence is None else round(al.coherence, 4),
                           "selected": bool(ident.get("chosen") is c)})
    out["candidates"] = cands_json
    if online:
        out["online_recognition"] = online_recognize(src)
    else:
        out["online_recognition"] = {"status": "not_run"}
    speech_fn = speech_mask_from_vocals(vocals, SR)
    if ident["status"] != "measured":
        out.update({"status": "unmeasured", "blocker": ident["blocker"],
                    "presence": _presence_without_match(stems)})
        if write:
            write_json(bgm_path(preset_name, video_id), out)
        return out
    ch = ident["chosen"]
    tr: LibraryTrack = ch["track"]
    al: Alignment = ch["alignment"]
    clean, clean_feat = _track_audio_and_features(tr, SR)
    model = build_bgm_model(bgm_sig, clean, SR, al)
    g = describe_gain(model, speech_fn)
    if not g.get("present"):
        out.update({"status": "unmeasured", "presence": "unmeasured",
                    "blocker": "정렬은 되었으나 BGM 레벨 곡선에서 BGM 이 들리는 구간을 찾지 못함"})
        if write:
            write_json(bgm_path(preset_name, video_id), out)
        return out
    r = al.tempo_ratio
    used_ref = [g["used_start"], g["used_end"]]
    used_clean = [round(al.clean_t(used_ref[0]), 3), round(al.clean_t(used_ref[1]), 3)]
    tvo = (r * float(tr.tempo_ratio_to_original)) if tr.tempo_ratio_to_original else None
    mix_rms = float(np.sqrt(np.mean(mix ** 2)) + 1e-12)
    try:
        from ..util.media import lufs

        mix_lufs = lufs(src).get("integrated_lufs")
    except Exception:  # loudness is auxiliary; never invent it
        mix_lufs = None
    est = model.estimate(len(mix))
    if est is not None:
        seg = slice(int(used_ref[0] * SR), int(used_ref[1] * SR))
        bgm_to_mix = 20 * np.log10(float(np.sqrt(np.mean(est[seg] ** 2)) + 1e-12) /
                                   float(np.sqrt(np.mean(mix[seg] ** 2)) + 1e-12))
    else:
        bgm_to_mix = None
    sec_status = "ambiguous" if al.ambiguous else "measured"
    out.update({
        "status": "measured", "blocker": None, "presence": "present",
        "match": {
            "track_id": _field(tr.track_id, note="라이브러리 파일 항목 id (프리셋 audio.bgm.track_id 값)"),
            "song_id": _field(tr.song_id or tr.title, "measured" if (tr.song_id or tr.title) else "unmeasured"),
            "artist": _field(tr.artist, "measured" if tr.artist else "unmeasured"),
            "title": _field(tr.title, "measured" if tr.title else "unmeasured",
                            **({} if tr.title else {"blocker": "라이브러리 index.yaml 에 제목 없음"})),
            "version": _field(tr.version, "measured" if tr.version else "unmeasured",
                              **({} if tr.version else {"blocker": "라이브러리 index.yaml 에 버전 없음"})),
            "file": tr.stored,
            "file_sha256": sha256_file(tr.file),
            "why_this_version": ident["why"],
            "tempo_ratio": _field(round(r, 5), tolerance=TEMPO_TOL,
                                  method=f"{al.mode}: feature NCC tempo grid {TEMPO_RANGE} step {TEMPO_STEP_FINE}"
                                  + (" + GCC-PHAT probe line fit" if al.mode == "waveform" else "")),
            "tempo_vs_original": _field(None if tvo is None else round(tvo, 5),
                                        "measured" if tvo is not None else "unmeasured"),
            "section_start_s": _field(round(al.offset_s, 3), sec_status, tolerance=OFFSET_TOL_S,
                                      candidates=al.section_candidates,
                                      note=("반복 구간이 파형 수준에서도 구분되지 않음 — 후보 전부 기록" if al.ambiguous
                                            else None)),
            "used_range_ref_s": _field(used_ref),
            "used_range_clean_s": _field(used_clean),
            "gain_db": _field(round(g["base_db"], 2), method=g["base_method"] + (
                " (파형 LS)" if al.mode == "waveform" else " (mel 대역 에너지비 중앙값: 레퍼런스가 속도 변경)")),
            "bgm_to_mix_db": _field(None if bgm_to_mix is None else round(float(bgm_to_mix), 2),
                                    "measured" if bgm_to_mix is not None else "unmeasured"),
            "fade_in_s": _field(g["fade_in_s"], method="선형 진폭 페이드 모델: -25→-1.5 dB 구간/0.785"),
            "fade_out_s": _field(g["fade_out_s"], method="선형 진폭 페이드 모델: -25→-1.5 dB 구간/0.785"),
            "cuts": _field(g["cuts"]),
            "loop": detect_restarts(bgm_sig, clean, SR, al, clean_feat=clean_feat),
            "alignment": {"mode": al.mode, "feature_ncc": round(al.feature_ncc, 4),
                          "coherence": None if al.coherence is None else round(al.coherence, 4),
                          "probes": al.probes, "margin_vs_other_tracks": round(ident["margin"], 4),
                          "mix_rms_dbfs": round(20 * np.log10(mix_rms), 2)},
            "mix_integrated_lufs": _field(mix_lufs, "measured" if mix_lufs is not None else "unmeasured",
                                          method="ffmpeg ebur128 (레퍼런스 믹스 전체)"),
        },
        "gain_curve": _decimate_curve(model, 0.1),
    })
    if write:
        write_json(bgm_path(preset_name, video_id), out)
    return out


def _decimate_curve(model: BgmModel, step: float) -> dict:
    ts = np.arange(0.0, float(model.t[-1]) if len(model.t) else 0.0, step)
    vals = np.interp(ts, model.t, model.gain_db)
    on = np.interp(ts, model.t, model.clean_on.astype(float)) > 0.5
    return {"hop_s": step, "t0": 0.0, "unit": "dB re clean file", "db": [round(float(v), 1) if o else None
                                                                          for v, o in zip(vals, on)]}


def _presence_without_match(stems: Stems | None) -> str:
    """BGM presence when no library file matched: only from the non-vocal stems, and only when the
    answer is clear (sustained tonal signal -> present; near silence -> absent); else unmeasured."""
    if stems is None:
        return "unmeasured"
    acc = stems.accompaniment()
    if acc is None:
        return "unmeasured"
    from .separation import frame_rms_db

    _, lv = frame_rms_db(acc, SR, 0.2, 0.1)
    loud = lv > -45.0
    if float(np.mean(lv > -50.0)) < 0.05:
        return "absent"
    if float(np.mean(loud)) >= 0.5:
        P = np.abs(stft(acc, 2048, 1024)) ** 2
        n = min(len(P), len(loud))
        idx = np.nonzero(np.interp(np.arange(n) * 1024 / SR, np.arange(len(lv)) * 0.1, loud.astype(float)) > 0.5)[0]
        if len(idx):
            Pl = np.maximum(P[idx], 1e-12)
            flat = np.exp(np.mean(np.log(Pl), axis=1)) / np.mean(Pl, axis=1)
            if float(np.median(flat)) < 0.2:
                return "present"
    return "unmeasured"


def _separation_status(preset_name: str, video_id: str) -> dict:
    rec = read_json(audio_dir(preset_name, video_id) / "separation.json")
    if rec:
        return {"status": rec.get("status"), "model": rec.get("model") or rec.get("separator"),
                "model_version": rec.get("model_version"), "blocker": rec.get("blocker")}
    return {"status": "unmeasured", "model": None, "model_version": None,
            "blocker": "분리 실행 기록 없음 (`shortkit ref separate` 전)"}


def load_bgm_model(preset_name: str, video_id: str, bgm_sig: np.ndarray, sr: int = SR) -> tuple[BgmModel | None, dict | None]:
    """Rebuild the aligned clean BGM + gain curve for a video from its bgm.json (no search)."""
    rec = read_json(bgm_path(preset_name, video_id))
    if not rec or rec.get("status") != "measured":
        return None, rec
    m = rec["match"]
    f = resolve_stored(m["file"])
    if not f.is_file():
        return None, rec
    clean = load_mono(f, sr)
    al = Alignment(tempo_ratio=float(m["tempo_ratio"]["value"]), offset_s=float(m["section_start_s"]["value"]),
                   feature_ncc=float(m["alignment"]["feature_ncc"]), mode=m["alignment"]["mode"],
                   coherence=m["alignment"].get("coherence"), ambiguous=False, section_candidates=[], probes=[])
    return build_bgm_model(bgm_sig, clean, sr, al), rec


def align_files(ref_path: str | os.PathLike, clean_path: str | os.PathLike, sr: int = SR) -> dict:
    """Ad-hoc: align a reference audio/video file to one clean music file (CLI bgm-align)."""
    ref = load_mono(ref_path, sr)
    clean = load_mono(clean_path, sr)
    al = align(ref, clean, sr)
    model = build_bgm_model(ref, clean, sr, al)
    g = describe_gain(model)
    d = al.to_dict()
    d.update({k: v for k, v in g.items() if k != "present_mask"})
    return d
