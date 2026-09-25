"""Source separation (Demucs) for reference analysis and for cleaning original source audio.

Two uses:

1. Reference analysis (`separate_reference`): split a reference video's mix into stems
   (htdemucs: vocals/drums/bass/other, or two-stems vocals/no_vocals).  Stems are cached in
   ``presets/<name>/analysis/<video_id>/stems/`` (git-ignored) together with ``stems.json``
   (model name + version + input sha256).  The *tracked* status record is
   ``analysis/<video_id>/audio/separation.json`` so that callers can mark stem-dependent
   measurements ``unmeasured`` when separation was impossible.

2. Source cleaning (`separate_vocals_for_source`): remove music that is already embedded in a
   new source clip.  The user rule is "separate, then check quality": the vocals stem is only
   usable when `quality_check` passes (residual-music correlation, spectral flatness, levels).
   Listening checks are never claimed by this code (``listening_check: not_done``).

If demucs/torch are not installed, or the pretrained weights cannot be obtained (the weights
host ``dl.fbaipublicfiles.com`` is blocked on the build machine), ``SeparationUnavailable`` is
raised with the reason.  Nothing here installs packages or downloads weights from other hosts.

This module also holds the small shared helpers of the reference-audio package (analysis
paths, audio loading, STFT / log-mel features) so the other audio modules use one definition.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

import numpy as np

from .. import paths
from ..util.hashing import sha256_file
from ..util.jsonio import now_iso, read_json, read_jsonl, read_yaml, write_json
from ..util.media import MediaError, probe, read_audio, write_wav

SR = 22050                     # analysis sample rate (mono)
STEMS_4 = ("vocals", "drums", "bass", "other")
AUDIO_EXT = (".wav", ".mp3", ".flac", ".ogg", ".m4a", ".aac", ".opus", ".aif", ".aiff", ".webm", ".mp4", ".mkv",
             ".mov")
DEFAULT_PRESET = "joshuamagazine"


class SeparationUnavailable(RuntimeError):
    """Separation could not run here.  ``reason`` is shown to the user (Korean/English)."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


# ============================================================================ paths / io helpers
def analysis_dir(preset_name: str, video_id: str) -> Path:
    return paths.absp(f"presets/{preset_name}/analysis/{video_id}")


def audio_dir(preset_name: str, video_id: str) -> Path:
    return analysis_dir(preset_name, video_id) / "audio"


def stems_dir(preset_name: str, video_id: str) -> Path:
    return analysis_dir(preset_name, video_id) / "stems"


def rel_or_none(p: str | os.PathLike | None) -> str | None:
    if p is None:
        return None
    try:
        return paths.relp(p)
    except ValueError:
        return None


def find_reference_media(preset_name: str, video_id: str) -> Path | None:
    """Locate the downloaded reference file for ``video_id``.

    Looks at ``reference/downloads.jsonl`` first (field ``path``/``file``/``download_path``),
    then ``reference/videos/<video_id>.*``."""
    ref = paths.absp(f"presets/{preset_name}/reference")
    for row in reversed(read_jsonl(ref / "downloads.jsonl")):
        if str(row.get("video_id")) != str(video_id):
            continue
        for k in ("path", "file", "download_path"):
            v = row.get(k)
            if v and paths.absp(v).is_file():
                return paths.absp(v)
    vdir = ref / "videos"
    if vdir.is_dir():
        for p in sorted(vdir.glob(f"{video_id}.*")):
            if p.suffix.lower() in AUDIO_EXT and not p.name.endswith((".part", ".tmp")):
                return p
    return None


def load_mono(path: str | os.PathLike, sr: int = SR) -> np.ndarray:
    return read_audio(path, sr=sr, mono=True).astype(np.float32)


def local_settings() -> dict:
    """User-local settings (``local.yaml`` at the project root, git-ignored)."""
    try:
        return read_yaml(paths.project_root() / "local.yaml", {}) or {}
    except Exception:
        return {}


LIBRARY_TOKENS = {"$music_library_root": "music_library_root", "$sfx_library_root": "sfx_library_root"}


def store_path(p: str | os.PathLike, token: str | None = None, token_root: Path | None = None) -> str:
    """Root-relative path for storage; files in a user library outside the project are stored as
    ``$<token>/<path relative to that library root>`` (never as an absolute path)."""
    try:
        return paths.relp(p)
    except ValueError:
        if token and token_root is not None:
            rel = Path(p).resolve().relative_to(Path(token_root).resolve()).as_posix()
            return f"{token}/{rel}"
        raise


def resolve_stored(s: str) -> Path:
    """Inverse of `store_path` (expands ``$music_library_root`` / ``$sfx_library_root`` from local.yaml)."""
    for tok, key in LIBRARY_TOKENS.items():
        if s == tok or s.startswith(tok + "/"):
            root = local_settings().get(key)
            if not root:
                raise FileNotFoundError(f"{s}: local.yaml 에 {key} 가 없음")
            return Path(os.path.expanduser(str(root))) / s[len(tok) + 1:]
    return paths.absp(s)


# ============================================================================ DSP helpers (shared)
def db(x: np.ndarray | float, floor: float = 1e-10) -> np.ndarray:
    return 10.0 * np.log10(np.maximum(np.asarray(x, dtype=np.float64), floor))


def frame_signal(x: np.ndarray, n_fft: int, hop: int, center: bool = True) -> np.ndarray:
    """[T, n_fft] frames; with ``center`` frame i is centred on sample i*hop."""
    x = np.asarray(x, dtype=np.float32)
    if center:
        x = np.pad(x, (n_fft // 2, n_fft // 2))
    if len(x) < n_fft:
        x = np.pad(x, (0, n_fft - len(x)))
    n = 1 + (len(x) - n_fft) // hop
    return np.lib.stride_tricks.sliding_window_view(x, n_fft)[::hop][:n]


def stft(x: np.ndarray, n_fft: int = 1024, hop: int = 256) -> np.ndarray:
    """Complex STFT [T, n_fft//2+1] (hann, centred frames)."""
    w = np.hanning(n_fft).astype(np.float32)
    return np.fft.rfft(frame_signal(x, n_fft, hop) * w, axis=1)


def istft(S: np.ndarray, n_fft: int, hop: int, length: int) -> np.ndarray:
    """Inverse of `stft` (weighted overlap-add, hann analysis+synthesis)."""
    w = np.hanning(n_fft).astype(np.float64)
    frames = np.fft.irfft(S, n=n_fft, axis=1) * w
    T = frames.shape[0]
    out = np.zeros(T * hop + n_fft, np.float64)
    norm = np.zeros_like(out)
    for i in range(T):
        s = i * hop
        out[s:s + n_fft] += frames[i]
        norm[s:s + n_fft] += w * w
    out = out[n_fft // 2:n_fft // 2 + length]
    norm = norm[n_fft // 2:n_fft // 2 + length]
    return (out / np.maximum(norm, 1e-8)).astype(np.float32)


_MEL_CACHE: dict[tuple, np.ndarray] = {}


def mel_filterbank(sr: int, n_fft: int, n_mels: int, fmin: float = 30.0, fmax: float | None = None) -> np.ndarray:
    key = (sr, n_fft, n_mels, fmin, fmax)
    if key in _MEL_CACHE:
        return _MEL_CACHE[key]
    fmax = fmax or sr / 2

    def hz2mel(f):
        return 2595.0 * np.log10(1.0 + np.asarray(f) / 700.0)

    def mel2hz(m):
        return 700.0 * (10 ** (np.asarray(m) / 2595.0) - 1.0)

    freqs = np.linspace(0, sr / 2, n_fft // 2 + 1)
    pts = mel2hz(np.linspace(hz2mel(fmin), hz2mel(fmax), n_mels + 2))
    fb = np.zeros((n_mels, freqs.size), np.float32)
    for i in range(n_mels):
        lo, c, hi = pts[i], pts[i + 1], pts[i + 2]
        up = (freqs - lo) / max(c - lo, 1e-9)
        dn = (hi - freqs) / max(hi - c, 1e-9)
        fb[i] = np.maximum(0.0, np.minimum(up, dn))
    # guarantee every band has at least one bin (low bands at small n_fft)
    for i in range(n_mels):
        if fb[i].sum() == 0:
            fb[i, int(np.argmin(np.abs(freqs - pts[i + 1])))] = 1.0
    _MEL_CACHE[key] = fb
    return fb


def logmel(x: np.ndarray, sr: int = SR, n_fft: int = 1024, hop: int = 256, n_mels: int = 64,
           fmax: float | None = None) -> np.ndarray:
    """Log-mel power [T, n_mels] in dB (floor -100 dB)."""
    P = np.abs(stft(x, n_fft, hop)) ** 2
    M = P @ mel_filterbank(sr, n_fft, n_mels, fmax=fmax).T
    return db(M, 1e-10).astype(np.float32)


def frame_rms_db(x: np.ndarray, sr: int, win_s: float, hop_s: float) -> tuple[np.ndarray, np.ndarray]:
    """(times, rms dBFS) with centred windows."""
    win = max(2, int(round(win_s * sr)))
    hop = max(1, int(round(hop_s * sr)))
    fr = frame_signal(x, win, hop)
    r = np.sqrt(np.mean(fr.astype(np.float64) ** 2, axis=1))
    return np.arange(len(r)) * hop / sr, (20 * np.log10(np.maximum(r, 1e-6))).astype(np.float32)


def fractional_delay(x: np.ndarray, d: float) -> np.ndarray:
    """x(t - d) for fractional sample delay d (FFT phase shift, same length)."""
    n = len(x)
    if abs(d) < 1e-9:
        return x.astype(np.float32)
    nf = 1 << int(np.ceil(np.log2(n + 2 * abs(int(d)) + 64)))
    X = np.fft.rfft(x, nf)
    k = np.arange(X.size)
    y = np.fft.irfft(X * np.exp(-2j * np.pi * k * d / nf), nf)[:n]
    return y.astype(np.float32)


# ============================================================================ separator API
class Separator(Protocol):
    name: str
    version: str | None

    def separate(self, path: Path, two_stems: bool = False) -> tuple[dict[str, np.ndarray], int]:
        """Return ({stem_name: float32 array [n] or [n, ch]}, sample_rate)."""
        ...


class DemucsSeparator:
    """Wrapper around the documented Demucs v4 python API (demucs.pretrained / demucs.apply).

    NOT live-tested on the build machine: torch/demucs are not installed and the weights host is
    blocked.  Any failure to import or to obtain weights raises SeparationUnavailable.
    """

    def __init__(self, model: str = "htdemucs", device: str = "cpu", shifts: int = 1, overlap: float = 0.25,
                 segment: float | None = None):
        self.name = f"demucs {model}"
        self.model_name = model
        self.device = device
        self.shifts = shifts
        self.overlap = overlap
        self.segment = segment
        self.version: str | None = None
        self._model = None

    def _load(self):
        if self._model is not None:
            return self._model
        try:
            import torch  # noqa: F401
        except Exception as e:  # ImportError or broken install
            raise SeparationUnavailable(f"torch 미설치/불러오기 실패 ({type(e).__name__}: {e}) — demucs 분리 불가") from None
        try:
            import demucs  # noqa: F401
            from demucs.pretrained import get_model
        except Exception as e:
            raise SeparationUnavailable(f"demucs 미설치/불러오기 실패 ({type(e).__name__}: {e})") from None
        self.version = getattr(demucs, "__version__", None)
        try:
            model = get_model(self.model_name)   # downloads weights on first use (dl.fbaipublicfiles.com)
        except Exception as e:
            raise SeparationUnavailable(
                f"demucs 가중치({self.model_name})를 얻지 못함: {type(e).__name__}: {str(e)[:300]} "
                "(가중치 호스트 dl.fbaipublicfiles.com 차단 가능성)") from None
        model.eval()
        self._model = model
        return model

    def separate(self, path: Path, two_stems: bool = False) -> tuple[dict[str, np.ndarray], int]:
        model = self._load()
        import torch
        from demucs.apply import apply_model

        sr = int(model.samplerate)
        ch = int(getattr(model, "audio_channels", 2))
        wav = read_audio(path, sr=sr, mono=False)                     # [n, 2]
        if ch == 1:
            wav = wav.mean(axis=1, keepdims=True)
        t = torch.from_numpy(np.ascontiguousarray(wav.T)).float()   # [ch, n]
        ref = t.mean(0)
        mu, sd = ref.mean(), ref.std() + 1e-8
        t = (t - mu) / sd
        kw = dict(device=self.device, shifts=self.shifts, split=True, overlap=self.overlap, progress=False)
        if self.segment:
            kw["segment"] = self.segment
        with torch.no_grad():
            out = apply_model(model, t[None], **kw)[0]
        out = out * sd + mu
        stems = {name: out[i].cpu().numpy().T.astype(np.float32) for i, name in enumerate(model.sources)}
        if two_stems:
            voc = stems.get("vocals")
            if voc is None:
                raise SeparationUnavailable(f"model {self.model_name} has no vocals source")
            rest = sum(v for k, v in stems.items() if k != "vocals")
            stems = {"vocals": voc, "no_vocals": rest}
        return stems, sr


SEPARATORS: dict[str, Callable[[], Separator]] = {
    "demucs": lambda: DemucsSeparator("htdemucs"),
    "htdemucs": lambda: DemucsSeparator("htdemucs"),
    "htdemucs_ft": lambda: DemucsSeparator("htdemucs_ft"),
}


def get_separator(name: str = "demucs") -> Separator:
    if name not in SEPARATORS:
        raise KeyError(f"unknown separator '{name}' (known: {', '.join(sorted(SEPARATORS))})")
    return SEPARATORS[name]()


# ============================================================================ reference stems
@dataclass
class Stems:
    sr: int
    stems: dict[str, np.ndarray]           # mono float32 at `sr`
    model: str
    model_version: str | None
    mode: str                              # "4stems" | "two_stems_vocals"
    files: dict[str, str] = field(default_factory=dict)   # root-relative wav paths (cache)

    @property
    def vocals(self) -> np.ndarray | None:
        return self.stems.get("vocals")

    def accompaniment(self) -> np.ndarray | None:
        rest = [v for k, v in self.stems.items() if k != "vocals"]
        if not rest:
            return None
        n = min(len(v) for v in rest)
        return np.sum([v[:n] for v in rest], axis=0).astype(np.float32)


def separation_record_path(preset_name: str, video_id: str) -> Path:
    return audio_dir(preset_name, video_id) / "separation.json"


def load_cached_stems(preset_name: str, video_id: str, sr: int = SR, audio_path: str | os.PathLike | None = None
                      ) -> Stems | None:
    """Cached stems of a reference video; None if missing or made from a different input file."""
    meta = read_json(stems_dir(preset_name, video_id) / "stems.json")
    if not meta or meta.get("status") != "measured":
        return None
    src = Path(audio_path) if audio_path else find_reference_media(preset_name, video_id)
    if src is not None and src.is_file() and meta.get("input_sha256") and meta["input_sha256"] != sha256_file(src):
        return None
    arrs = {}
    for name, rel in (meta.get("files") or {}).items():
        p = paths.absp(rel)
        if not p.is_file():
            return None
        arrs[name] = load_mono(p, sr)
    if not arrs:
        return None
    return Stems(sr=sr, stems=arrs, model=meta.get("model"), model_version=meta.get("model_version"),
                 mode=meta.get("mode"), files=meta.get("files") or {})


def separate_reference(preset_name: str, video_id: str, audio_path: str | os.PathLike | None = None,
                       separator: Separator | None = None, two_stems: bool = False, force: bool = False,
                       sr: int = SR) -> Stems:
    """Separate one reference video's audio into cached stems.

    Always writes ``analysis/<id>/audio/separation.json`` (tracked) with the outcome.
    Raises SeparationUnavailable (after recording it) when separation cannot run here."""
    src = Path(audio_path) if audio_path else find_reference_media(preset_name, video_id)
    rec_path = separation_record_path(preset_name, video_id)
    if src is None or not Path(src).is_file():
        reason = f"레퍼런스 원본 파일 없음(video_id={video_id})"
        write_json(rec_path, {"video_id": video_id, "status": "unmeasured", "blocker": reason, "checked_at": now_iso()})
        raise SeparationUnavailable(reason)
    src = Path(src)
    sha = sha256_file(src)
    mode = "two_stems_vocals" if two_stems else "4stems"
    sdir = stems_dir(preset_name, video_id)
    meta = read_json(sdir / "stems.json") or {}
    sep = separator or get_separator("demucs")
    if not force and meta.get("status") == "measured" and meta.get("input_sha256") == sha \
            and meta.get("mode") == mode and (separator is None or meta.get("model") == sep.name):
        cached = load_cached_stems(preset_name, video_id, sr, audio_path=src)
        if cached is not None:
            rec = read_json(rec_path) or {}
            if rec.get("status") == "measured" and not rec.get("stems_sha256"):    # records made before stem hashing
                hashes = {n: sha256_file(paths.absp(f)) for n, f in (meta.get("files") or {}).items()
                          if paths.absp(f).is_file()}
                if hashes:
                    write_json(rec_path, rec | {"stems_sha256": hashes})
            return cached
    try:
        stems_raw, ssr = sep.separate(src, two_stems=two_stems)
    except SeparationUnavailable as e:
        attempt = {"separator": sep.name, "blocker": e.reason, "checked_at": now_iso()}
        old = read_json(rec_path) or {}
        if old.get("status") == "measured" and old.get("input_sha256") == sha \
                and load_cached_stems(preset_name, video_id, sr, audio_path=src) is not None:
            # keep the valid stems made earlier (other model); only log the failed attempt
            old["last_failed_attempt"] = attempt
            write_json(rec_path, old)
        else:
            write_json(rec_path, {"video_id": video_id, "status": "unmeasured", "blocker": e.reason,
                                  "separator": sep.name, "input": rel_or_none(src), "input_sha256": sha,
                                  "checked_at": now_iso()})
        raise
    files, hashes = {}, {}
    for name, arr in stems_raw.items():
        out = sdir / f"{name}.wav"
        write_wav(out, np.asarray(arr, np.float32), ssr)
        files[name] = paths.relp(out)
        hashes[name] = sha256_file(out)
    # stems_sha256 is kept in the (tracked) separation record too: the stem cache is git-ignored, and a stem
    # copied into the music library must stay recognisable after the cache is gone (audio_bgm.load_library)
    meta = {"video_id": video_id, "status": "measured", "model": sep.name, "model_version": sep.version,
            "mode": mode, "sample_rate": ssr, "input": rel_or_none(src), "input_sha256": sha, "files": files,
            "stems_sha256": hashes, "created_at": now_iso()}
    write_json(sdir / "stems.json", meta)
    write_json(rec_path, {k: meta[k] for k in ("video_id", "status", "model", "model_version", "mode", "input",
                                                "input_sha256", "stems_sha256", "created_at")}
               | {"blocker": None, "stems_dir": paths.relp(sdir), "note": "stems 는 git 에 올리지 않는 캐시"})
    st = load_cached_stems(preset_name, video_id, sr, audio_path=src)
    assert st is not None
    return st


def stems_or_none(preset_name: str, video_id: str, separator: Separator | None = None,
                  audio_path: str | os.PathLike | None = None, sr: int = SR) -> tuple[Stems | None, dict]:
    """Cached stems, or run the separator; never raises for unavailability.

    Returns (stems|None, status-dict) where status-dict is what callers store under
    ``separator`` in their json (status, model, blocker)."""
    src = Path(audio_path) if audio_path else find_reference_media(preset_name, video_id)
    cached = load_cached_stems(preset_name, video_id, sr, audio_path=src)
    meta = read_json(stems_dir(preset_name, video_id) / "stems.json") or {}
    fresh = src is not None and src.is_file() and meta.get("input_sha256") == sha256_file(src)
    if cached is not None and fresh:  # a valid cache is used whatever separator is offered (its model is recorded)
        return cached, {"status": "measured", "model": cached.model, "model_version": cached.model_version,
                        "mode": cached.mode, "blocker": None}
    try:
        st = separate_reference(preset_name, video_id, audio_path=audio_path, separator=separator, sr=sr)
        return st, {"status": "measured", "model": st.model, "model_version": st.model_version, "mode": st.mode,
                    "blocker": None}
    except SeparationUnavailable as e:
        return None, {"status": "unmeasured", "model": (separator.name if separator else "demucs htdemucs"),
                      "model_version": None, "mode": None, "blocker": e.reason}


# ============================================================================ quality check
# thresholds for "vocals stem is clean enough to use as original audio" (documented in report)
QC_MAX_LEAK_DB = -20.0        # vocals energy in music-only frames relative to vocals energy in speech frames
QC_MAX_MUSIC_CORR = 0.30      # correlation of vocals-stem spectra with the music spectra (music-only frames)
QC_MIN_FLATNESS = 0.05        # tonal residue (flatness below this) in music-only frames counts as leak


def _spectral_flatness(P: np.ndarray) -> np.ndarray:
    P = np.maximum(P, 1e-12)
    return np.exp(np.mean(np.log(P), axis=1)) / np.mean(P, axis=1)


def quality_check(mix: np.ndarray, vocals: np.ndarray, accompaniment: np.ndarray | None, sr: int = SR,
                  music_ref: np.ndarray | None = None) -> dict:
    """Objective quality report of a vocals stem (no listening claimed).

    - ``levels``: RMS dBFS of input, vocals, accompaniment; vocals share of input energy.
    - ``music_leak_db``: vocals-stem energy in frames where the music is present but speech is
      not (music-only frames), relative to vocals energy in speech frames.  Speech frames = loud
      vocals-stem frames whose spectrum does NOT correlate with the music spectrum (>= 0.5 means
      the frame is music leakage).
    - ``residual_music_corr``: correlation of the vocals stem's magnitude spectra with the music
      spectra over music-only frames (music = ``music_ref`` if given, else the accompaniment).
    - ``flatness_music_only``: spectral flatness of the vocals stem in music-only frames (tonal
      music residue -> low flatness).
    - ``passed``: leak and correlation under thresholds.
    """
    n = min(len(mix), len(vocals), *( [len(accompaniment)] if accompaniment is not None else []))
    mix, vocals = mix[:n], vocals[:n]
    music = music_ref[:n] if music_ref is not None and len(music_ref) >= n else \
        (accompaniment[:n] if accompaniment is not None else None)
    n_fft, hop = 1024, 256

    def rms_db(x):
        return float(20 * np.log10(max(1e-9, float(np.sqrt(np.mean(np.asarray(x, np.float64) ** 2))))))

    rep: dict = {"method": "stft 1024/256 @%d Hz; speech frames from vocals-stem energy, music frames from music "
                           "reference/accompaniment energy" % sr,
                 "thresholds": {"music_leak_db_max": QC_MAX_LEAK_DB, "residual_music_corr_max": QC_MAX_MUSIC_CORR,
                                "flatness_min": QC_MIN_FLATNESS},
                 "listening_check": "not_done"}
    rep["levels"] = {"input_rms_dbfs": round(rms_db(mix), 2), "vocals_rms_dbfs": round(rms_db(vocals), 2),
                     "accompaniment_rms_dbfs": round(rms_db(accompaniment[:n]), 2) if accompaniment is not None else None,
                     "vocals_share_db": round(rms_db(vocals) - rms_db(mix), 2)}
    V = np.abs(stft(vocals, n_fft, hop)) ** 2
    ev = db(V.sum(1))
    if music is None:
        rep.update({"status": "unmeasured", "blocker": "음악 기준 신호(반주 stem/깨끗한 음원) 없음", "passed": None})
        return rep
    M = np.abs(stft(music, n_fft, hop)) ** 2
    T = min(V.shape[0], M.shape[0])
    V, M, ev = V[:T], M[:T], ev[:T]
    em = db(M.sum(1))
    # per-frame spectral correlation of the vocals stem with the music: a frame whose vocals-stem
    # spectrum looks like the music is leakage, not speech
    va = np.sqrt(V) - np.sqrt(V).mean(1, keepdims=True)
    ma = np.sqrt(M) - np.sqrt(M).mean(1, keepdims=True)
    fcorr = (va * ma).sum(1) / (np.linalg.norm(va, axis=1) * np.linalg.norm(ma, axis=1) + 1e-12)
    speech = (ev > (np.percentile(ev, 99) - 30.0)) & (fcorr < 0.5)
    music_on = em > (np.percentile(em, 99) - 30.0)
    music_only = music_on & ~_dilate(speech, 8)
    rep["frames"] = {"speech": int(speech.sum()), "music_only": int(music_only.sum()), "total": int(len(ev))}
    if music_only.sum() < 10:
        rep.update({"status": "unmeasured", "blocker": "음악만 있는 구간이 거의 없어 누설 측정 불가", "passed": None})
        return rep
    e_speech = float(np.mean(V[speech].sum(1))) if speech.sum() else 1e-12
    e_leak = float(np.mean(V[music_only].sum(1)))
    leak_db = float(10 * np.log10(max(e_leak, 1e-14) / max(e_speech, 1e-14)))
    a = np.sqrt(V[music_only]).ravel()
    b = np.sqrt(M[music_only]).ravel()
    a = a - a.mean()
    b = b - b.mean()
    corr = float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
    flat = float(np.median(_spectral_flatness(V[music_only])))
    rep.update({"status": "measured", "music_leak_db": round(leak_db, 2), "residual_music_corr": round(corr, 3),
                "flatness_music_only": round(flat, 4)})
    leak_tonal = leak_db > QC_MAX_LEAK_DB and flat < QC_MIN_FLATNESS
    rep["passed"] = bool(leak_db <= QC_MAX_LEAK_DB and corr <= QC_MAX_MUSIC_CORR) and not leak_tonal
    reasons = []
    if leak_db > QC_MAX_LEAK_DB:
        reasons.append(f"음악 구간 누설 {leak_db:.1f} dB > {QC_MAX_LEAK_DB} dB")
    if corr > QC_MAX_MUSIC_CORR:
        reasons.append(f"음악 스펙트럼 상관 {corr:.2f} > {QC_MAX_MUSIC_CORR}")
    rep["fail_reasons"] = reasons
    return rep


def _dilate(mask: np.ndarray, k: int) -> np.ndarray:
    if k <= 0:
        return mask
    c = np.convolve(mask.astype(float), np.ones(2 * k + 1), mode="same")
    return c > 0


def separate_vocals_for_source(source: str | os.PathLike, separator: Separator | None = None,
                               out_dir: str | os.PathLike | None = None,
                               music_ref: str | os.PathLike | None = None) -> dict:
    """Remove music embedded in a source clip: separate vocals, then quality-check them.

    Writes (git-ignored) ``warehouse/cache/separation/<sha12>/{vocals,accompaniment}.wav`` and
    ``quality.json``; returns the record (root-relative paths).  ``status`` is
    ``unmeasured`` (with ``blocker``) if separation is unavailable, else ``measured`` with
    ``quality.passed`` telling whether the vocals stem may be used as original audio.
    """
    src = Path(source)
    sha = sha256_file(src)
    od = Path(out_dir) if out_dir else paths.absp(f"warehouse/cache/separation/{sha[:12]}")
    rec: dict = {"schema": "shortkit.source_separation/1", "source": rel_or_none(src), "source_sha256": sha,
                 "created_at": now_iso(), "listening_check": "not_done"}
    sep = separator or get_separator("demucs")
    rec["separator"] = {"name": sep.name, "version": getattr(sep, "version", None)}
    try:
        stems_raw, ssr = sep.separate(src, two_stems=True)
    except SeparationUnavailable as e:
        rec.update({"status": "unmeasured", "blocker": e.reason, "vocals": None, "quality": None,
                    "usable": False})
        write_json(od / "quality.json", rec)
        return rec
    rec["separator"]["version"] = getattr(sep, "version", None)
    voc = np.asarray(stems_raw["vocals"], np.float32)
    acc = stems_raw.get("no_vocals")
    if acc is None:
        rest = [np.asarray(v, np.float32) for k, v in stems_raw.items() if k != "vocals"]
        acc = np.sum(rest, axis=0) if rest else None
    write_wav(od / "vocals.wav", voc, ssr)
    rec["vocals"] = rel_or_none(od / "vocals.wav")
    if acc is not None:
        write_wav(od / "accompaniment.wav", np.asarray(acc, np.float32), ssr)
        rec["accompaniment"] = rel_or_none(od / "accompaniment.wav")
    mix = load_mono(src, SR)
    v = load_mono(od / "vocals.wav", SR)
    a = load_mono(od / "accompaniment.wav", SR) if acc is not None else None
    mref = None
    if music_ref:
        mref = load_mono(music_ref, SR)
        rec["music_ref"] = rel_or_none(music_ref)
    q = quality_check(mix, v, a, SR, music_ref=mref)
    rec.update({"status": "measured", "blocker": None, "quality": q, "usable": bool(q.get("passed"))})
    write_json(od / "quality.json", rec)
    return rec


def media_duration(path: str | os.PathLike) -> float | None:
    try:
        return float(probe(path).duration)
    except MediaError:
        return None
