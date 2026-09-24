"""Audio probes on the decoded output mix.

Every known signal is located in the mix by matching against the true file:

* BGM: onset-envelope cross-correlation over tempo candidates finds (tempo, offset) of the
  planned music file in the output; a waveform cross-correlation refines the offset (the used
  section).  A different part of the same song gives a different offset -> reported as such.
* Per-window least squares (0.25 s and 0.05 s windows) of the mix onto
  [aligned BGM, per-clip original audio, detected SFX] gives the BGM gain curve (ducking,
  silences, fades) and the original-audio presence per window.
* SFX: normalised matched filter of every known SFX file over the residual (mix minus fitted
  BGM/original) -> detected times, type, gain.  Energy onsets left in the final residual that
  no known signal explains are reported as unexplained sounds.
* Loudness: EBU R128 integrated + true peak of the MP4 (ffmpeg ebur128).

``build/stems/*.wav`` are NOT used for the primary measurements (they are the renderer's own
intermediate files); they may be listed as extra evidence only.
"""
from __future__ import annotations

import math
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from . import QAContext, in_ranges, merge_ranges, rnd

SR = 22050
WIN = 0.25
FINE = 0.05


# ----------------------------------------------------------------------------- decoding
def load_mono(path, sr: int = SR, start: float | None = None, duration: float | None = None,
              tempo: float = 1.0) -> np.ndarray:
    """Decode to mono float32; optional pitch-preserving tempo change (ffmpeg atempo chain)."""
    from ..util.media import FFMPEG, probe, read_audio

    if abs(tempo - 1.0) < 1e-6:
        return read_audio(path, sr=sr, mono=True, start=start, duration=duration)
    info = probe(path)
    if not info.has_audio:
        return np.zeros(0, np.float32)
    chain, r = [], float(tempo)
    while r > 2.0:
        chain.append("atempo=2.0")
        r /= 2.0
    while r < 0.5:
        chain.append("atempo=0.5")
        r /= 0.5
    chain.append(f"atempo={r:.6f}")
    args = [FFMPEG, "-hide_banner", "-nostdin", "-v", "error"]
    if start is not None:
        args += ["-ss", f"{start:.6f}"]
    args += ["-i", str(path)]
    if duration is not None:
        args += ["-t", f"{duration:.6f}"]
    args += ["-vn", "-af", ",".join(chain), "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    raw = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
    return np.frombuffer(raw, np.float32).copy()


# ----------------------------------------------------------------------------- envelopes / xcorr
def onset_env(x: np.ndarray, sr: int = SR, hop: int = 256) -> np.ndarray:
    from scipy.signal import stft

    if len(x) < 2048:
        return np.zeros(1)
    _, _, Z = stft(x, fs=sr, nperseg=1024, noverlap=1024 - hop, boundary=None, padded=False)
    mag = np.abs(Z)
    nb = 24
    edges = np.unique(np.geomspace(2, mag.shape[0] - 1, nb + 1).astype(int))
    bands = np.stack([mag[a:b].sum(axis=0) for a, b in zip(edges[:-1], edges[1:])])
    lb = np.log1p(100.0 * bands)
    flux = np.maximum(0.0, np.diff(lb, axis=1)).sum(axis=0)
    flux = np.r_[0.0, flux]
    # remove slow trend
    k = 32
    if len(flux) > k:
        trend = np.convolve(flux, np.ones(k) / k, mode="same")
        flux = flux - trend
    s = flux.std()
    return (flux - flux.mean()) / s if s > 0 else flux * 0


def xcorr_full(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """c[k] = sum_n a[n] * b[n + k - (len(a)-1)]   (numpy 'full' correlate of b against a)."""
    from scipy.signal import fftconvolve

    return fftconvolve(b, a[::-1], mode="full")


def find_bgm(y: np.ndarray, music: np.ndarray, sr: int = SR, tempo_center: float = 1.0, span: float = 0.2,
             step: float = 0.005, hop: int = 256) -> dict:
    """Search tempo r and offset: y(t) ~ g * music(off + r*t).  Returns best + runner-up."""
    ey = onset_env(y, sr, hop)
    em = onset_env(music, sr, hop)
    fr = hop / sr
    cands = np.arange(max(0.5, tempo_center - span), tempo_center + span + 1e-9, step)
    if not np.any(np.isclose(cands, 1.0)):
        cands = np.r_[cands, 1.0]
    best, results = None, []
    for r in cands:
        # music envelope resampled to output time: em'(u) = em(r*u)
        n_out = int(len(em) / r)
        if n_out < 8:
            continue
        idx = np.arange(n_out) * r
        emr = np.interp(idx, np.arange(len(em)), em)
        c = xcorr_full(ey, emr)          # lag k: ey[n] ~ emr[n + k - (len(ey)-1)]
        norm = math.sqrt(float((ey ** 2).sum()) * float((emr ** 2).sum()) / max(1, len(emr)) * len(ey))
        k = int(np.argmax(c))
        lag = k - (len(ey) - 1)          # in output frames
        score = float(c[k] / (norm + 1e-9))
        results.append((score, float(r), lag, c))
        if best is None or score > best[0]:
            best = (score, float(r), lag, c)
    if best is None:
        return {"found": False}
    score, r, lag, c = best
    offset = lag * fr * r                # music time at output t=0
    # runner-up: best peak of the same tempo at an offset >= 1 s away
    guard = int(1.0 / fr)
    k0 = lag + (len(ey) - 1)
    c2 = c.copy()
    c2[max(0, k0 - guard):k0 + guard] = -np.inf
    k2 = int(np.argmax(c2))
    norm = score and c[k0] / score
    ru = {"offset": rnd((k2 - (len(ey) - 1)) * fr * r, 3), "score": rnd(float(c2[k2] / (norm + 1e-9)), 4)} \
        if np.isfinite(c2[k2]) else None
    by_tempo = sorted(results, key=lambda x: -x[0])[:5]
    return {"found": True, "tempo": round(r, 4), "offset": round(offset, 4), "env_score": round(score, 4),
            "runner_up_same_tempo": ru, "top_tempi": [[round(x[1], 4), round(x[0], 4)] for x in by_tempo]}


def global_align(y: np.ndarray, ref: np.ndarray, min_overlap: float = 0.5, sr: int = SR) -> dict:
    """Waveform alignment over ALL lags: y[n] ~ g * ref[n + L].  Returns best L, its NCC and the
    best NCC at least 0.5 s away (a different part of the same song)."""
    from scipy.signal import fftconvolve

    ny, nr = len(y), len(ref)
    if ny == 0 or nr == 0:
        return {"lag": 0, "ncc": 0.0, "runner_up": None}
    c = fftconvolve(ref.astype(np.float64), y[::-1].astype(np.float64), mode="full")   # index j -> L = j-(ny-1)
    L = np.arange(len(c)) - (ny - 1)
    cs = np.r_[0.0, np.cumsum(ref.astype(np.float64) ** 2)]
    a = np.clip(L, 0, nr)
    b = np.clip(L + ny, 0, nr)
    e = cs[b] - cs[a]
    ey = float((y.astype(np.float64) ** 2).sum())
    ncc_all = c / np.sqrt(np.maximum(e, 1e-12) * ey + 1e-12)
    ok = (b - a) >= min_overlap * min(ny, nr)
    ncc_all = np.where(ok, ncc_all, -np.inf)
    k = int(np.argmax(ncc_all))
    best = float(ncc_all[k])
    sr_guard = int(0.5 * sr)
    far = ncc_all.copy()
    far[max(0, k - sr_guard):k + sr_guard] = -np.inf
    k2 = int(np.argmax(far))
    ru = {"lag": int(L[k2]), "ncc": round(float(far[k2]), 4)} if np.isfinite(far[k2]) else None
    return {"lag": int(L[k]), "ncc": best, "runner_up": ru}


def refine_offset(y: np.ndarray, ref: np.ndarray, approx_lag: int, search: int) -> tuple[int, float]:
    """Waveform alignment near a known lag: y[n] ~ g * ref[n + L], L in approx +- search."""
    from scipy.signal import fftconvolve

    lo = max(-len(y) + 1, approx_lag - search)
    hi = min(len(ref) - 1, approx_lag + search)
    if hi < lo:
        return approx_lag, 0.0
    a0 = max(0, lo)
    a1 = min(len(ref), hi + len(y))
    seg = ref[a0:a1].astype(np.float64)
    c = fftconvolve(seg, y[::-1].astype(np.float64), mode="full")   # c[j] = sum y[n] seg[n + j - (len(y)-1)]
    cs = np.r_[0.0, np.cumsum(seg ** 2)]
    ey = float((y.astype(np.float64) ** 2).sum())
    Ls = np.arange(lo, hi + 1)
    j = Ls - a0 + len(y) - 1
    valid = (j >= 0) & (j < len(c))
    s0 = np.clip(Ls - a0, 0, len(seg))
    s1 = np.clip(Ls - a0 + len(y), 0, len(seg))
    e = cs[s1] - cs[s0]
    v = np.full(len(Ls), -np.inf)
    v[valid] = c[j[valid]] / np.sqrt(e[valid] * ey + 1e-12)
    k = int(np.argmax(v))
    return int(Ls[k]), float(v[k])


def align_signal(ref: np.ndarray, L: int, n: int) -> np.ndarray:
    """out[t] = ref[t + L] for t in [0, n)."""
    out = np.zeros(n, np.float32)
    a = max(0, -L)
    b = min(n, len(ref) - L)
    if b > a:
        out[a:b] = ref[a + L:b + L]
    return out


# ----------------------------------------------------------------------------- windowed LS
def window_ls(y: np.ndarray, cols: list[np.ndarray], sr: int, win: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Per-window least squares y ~ sum g_k cols_k.  Returns (t_centres, gains[w,k], resid)."""
    n = len(y)
    L = max(1, int(round(win * sr)))
    nw = int(math.ceil(n / L))
    G = np.full((nw, len(cols)), np.nan)
    resid = y.astype(np.float64).copy()
    tc = np.zeros(nw)
    for w in range(nw):
        a, b = w * L, min(n, (w + 1) * L)
        tc[w] = (a + b) / 2 / sr
        yw = y[a:b].astype(np.float64)
        act = [k for k, c in enumerate(cols) if float(np.abs(c[a:b]).max(initial=0.0)) > 1e-6
               and float((c[a:b].astype(np.float64) ** 2).sum()) > 1e-9 * (b - a)]
        if not act:
            continue
        X = np.stack([cols[k][a:b].astype(np.float64) for k in act], axis=1)
        g, *_ = np.linalg.lstsq(X, yw, rcond=None)
        G[w, act] = g
        resid[a:b] = yw - X @ g
    return tc, G, resid.astype(np.float32)


def db(v, floor: float = -120.0):
    v = np.asarray(v, float)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = 20 * np.log10(np.abs(v))
    return np.where(np.isnan(out), np.nan, np.maximum(np.nan_to_num(out, nan=floor, neginf=floor), floor))


# ----------------------------------------------------------------------------- matched filter
def matched_ncc(x: np.ndarray, s: np.ndarray) -> np.ndarray:
    from scipy.signal import fftconvolve

    if len(x) < len(s) or len(s) == 0:
        return np.zeros(0)
    num = fftconvolve(x.astype(np.float64), s[::-1].astype(np.float64), mode="valid")
    cs = np.cumsum(np.r_[0.0, x.astype(np.float64) ** 2])
    e = cs[len(s):] - cs[:-len(s)]
    ns = math.sqrt(float((s.astype(np.float64) ** 2).sum()))
    return num / (ns * np.sqrt(np.maximum(e, 1e-12)))


def detect_sfx(res: np.ndarray, templates: dict, sr: int = SR, thr: float = 0.45) -> list[dict]:
    from scipy.signal import find_peaks

    cand = []
    for key, tp in templates.items():
        s = tp["audio"]
        if len(s) < 16:
            continue
        # trim leading silence of the file so t = audible start
        c = matched_ncc(res, s)
        if not len(c):
            continue
        # one detection per sound: tonal SFX correlate with themselves at small lags
        pk, props = find_peaks(c, height=thr, distance=max(1, int(max(0.12, 0.8 * len(s) / sr) * sr)))
        for p, h in zip(pk, props["peak_heights"]):
            seg = res[p:p + len(s)].astype(np.float64)
            g = float((seg * s).sum() / max(1e-12, float((s.astype(np.float64) ** 2).sum())))
            cand.append({"t": p / sr, "key": key, "type": tp["type"], "file": tp.get("file"), "ncc": float(h),
                         "gain": g, "len": len(s) / sr})
    cand.sort(key=lambda d: -d["ncc"])
    acc: list[dict] = []
    for d in cand:
        clash = [a for a in acc if abs(a["t"] - d["t"]) < 0.04]
        if clash and not (all(a["type"] != d["type"] for a in clash) and d["ncc"] >= 0.7 and
                          all(a["ncc"] >= 0.7 for a in clash)):
            continue
        acc.append(d)
    acc.sort(key=lambda d: d["t"])
    return acc


def place(template: np.ndarray, t: float, g: float, n: int, sr: int = SR) -> np.ndarray:
    out = np.zeros(n, np.float32)
    a = int(round(t * sr))
    b = min(n, a + len(template))
    if b > a >= 0:
        out[a:b] = g * template[:b - a]
    return out


def _energy_db(x: np.ndarray, hop: int, L: int) -> np.ndarray:
    n = (len(x) - L) // hop
    if n <= 0:
        return np.zeros(0)
    cs = np.r_[0.0, np.cumsum(x.astype(np.float64) ** 2)]
    idx = np.arange(n) * hop
    e = (cs[idx + L] - cs[idx]) / L
    return 10 * np.log10(e + 1e-12)


def onset_times(x: np.ndarray, sr: int, hop_s: float = 0.005, rise_db: float = 10.0) -> list[float]:
    hop = int(hop_s * sr)
    L = int(0.02 * sr)
    e = _energy_db(x, hop, L)
    out = []
    for i in range(6, len(e)):
        if e[i] - e[i - 6] >= rise_db:
            t = i * hop / sr
            if not out or t - out[-1] > 0.05:
                out.append(t)
    return out


def unexplained_onsets(res: np.ndarray, mix: np.ndarray, sr: int, exclude: list, hop_s: float = 0.005,
                       rise_db: float = 14.0, model: np.ndarray | None = None) -> list[dict]:
    """Sharp energy rises left in the residual that coincide with no onset of the fitted known
    signals (``model`` = mix - residual)."""
    hop = int(hop_s * sr)
    L = int(0.02 * sr)
    er_db = _energy_db(res, hop, L)
    em_db = _energy_db(mix, hop, L)
    n = len(er_db)
    if n <= 10:
        return []
    mix_med = float(np.median(em_db))
    known = onset_times(model, sr, hop_s) if model is not None else []
    out = []
    k = int(0.4 / hop_s)
    last_t = -1.0
    for i in range(k, n):
        t = i * hop / sr
        if t < 0.1 or t > len(res) / sr - 0.1:
            continue
        floor = float(np.median(er_db[i - k:i - 2]))
        jump = er_db[i] - floor
        if jump >= rise_db and er_db[i] >= mix_med - 24 and (er_db[i] - er_db[max(0, i - 6)]) >= rise_db * 0.7 \
                and er_db[i] - em_db[i] >= -12.0:
            if in_ranges(t, exclude) or any(abs(t - kt) <= 0.04 for kt in known):
                continue
            if t - last_t < 0.25:
                continue
            out.append({"t": round(t, 3), "level_db_rel_mix": round(float(er_db[i] - mix_med), 1),
                        "rise_db": round(float(jump), 1), "resid_to_mix_db": round(float(er_db[i] - em_db[i]), 1)})
            last_t = t
    return out


# ----------------------------------------------------------------------------- helpers on the IR
def _full_original_tracks(ctx: QAContext, n: int, sr: int) -> list[dict]:
    """For every clip: its source audio (the stem the plan keeps for it, else raw) laid out on
    the output timeline as if the original sound were ON for the whole clip."""
    from .. import paths
    from ..util.media import probe

    res = ctx.resolved
    kept_path = {}
    for o in res.audio.originals:
        kept_path.setdefault(o.clip_id, o.path)
    out = []
    for c in res.clips:
        p = kept_path.get(c.id) or c.source_path
        ap = paths.absp(p)
        item = {"clip_id": c.id, "path": p, "track": None, "has_audio": False}
        if ap.is_file():
            try:
                has = probe(ap).has_audio
            except Exception:
                has = False
            item["has_audio"] = has
            if has:
                seg_end = c.src_out
                seg = load_mono(ap, sr, start=c.src_in, duration=max(0.0, seg_end - c.src_in), tempo=float(c.speed or 1.0))
                tr = np.zeros(n, np.float32)
                a = int(round(c.out_start * sr))
                if c.freeze is not None:
                    k = int(round((c.freeze.out_start - c.out_start) * sr))
                    k = max(0, min(len(seg), k))
                    b = min(n, a + k)
                    tr[a:b] = seg[:b - a]
                    a2 = int(round((c.freeze.out_start + c.freeze.hold) * sr))
                    b2 = min(n, a2 + len(seg) - k)
                    if b2 > a2:
                        tr[a2:b2] = seg[k:k + b2 - a2]
                else:
                    b = min(n, a + len(seg))
                    if b > a:
                        tr[a:b] = seg[:b - a]
                # the clip only owns [out_start, out_end]
                e = int(round(c.out_end * sr))
                tr[e:] = 0
                item["track"] = tr
        out.append(item)
    return out


def _sfx_templates(ctx: QAContext, sr: int) -> tuple[dict, list[str]]:
    """Known SFX files: every placement's file + sfx_map 'have' files (+ plan explicit files)."""
    from .. import paths
    from ..util.jsonio import read_yaml

    tps: dict = {}
    notes = []

    def add(type_id, rel):
        if not rel:
            return
        key = f"{type_id}|{rel}"
        if key in tps:
            return
        ap = paths.absp(rel)
        if not ap.is_file():
            notes.append(f"효과음 파일 없음: {rel}")
            return
        a = load_mono(ap, sr)
        nz = np.nonzero(np.abs(a) > 1e-4 * max(1e-9, float(np.abs(a).max(initial=0))))[0]
        if len(nz):
            a = a[nz[0]:nz[-1] + 1]
        tps[key] = {"type": type_id, "file": rel, "audio": a.astype(np.float32)}

    for s in ctx.resolved.audio.sfx:
        add(s.type, s.path)
    try:
        map_rel = ctx.preset.get("audio.sfx.map")
        m = read_yaml(paths.absp(map_rel), {}) or {}
        for tid, ent in (m.get("types") or {}).items():
            if isinstance(ent, dict) and ent.get("status") == "have" and ent.get("file"):
                add(tid, ent["file"])
    except Exception as e:
        notes.append(f"sfx_map 읽기 실패: {type(e).__name__}")
    return tps, notes


def _planned_bgm_env(ctx: QAContext):
    """Planned extra BGM gain (dB) at output time t: the IR envelope when present, else ducking
    and silences rebuilt from duck_ranges/silences."""
    bgm = ctx.resolved.audio.bgm
    if bgm is None:
        return None
    pts = [(float(a), float(b)) for a, b in (bgm.envelope or [])]
    if len(pts) >= 2:
        ts = np.array([p[0] for p in pts])
        vs = np.array([p[1] for p in pts])
        return lambda t: float(np.interp(t, ts, vs))
    depth = 10.0
    try:
        depth = float(ctx.preset.get("audio.ducking.depth_db"))
    except Exception:
        pass
    ducks = [tuple(x) for x in bgm.duck_ranges or []]
    sils = [tuple(x) for x in bgm.silences or []]

    def f(t):
        if any(a <= t <= b for a, b in sils):
            return -120.0
        if any(a <= t <= b for a, b in ducks):
            return -depth
        return 0.0
    return f


# ----------------------------------------------------------------------------- main probe
def probe_audio(ctx: QAContext, sr: int = SR) -> dict:
    from .. import paths
    from ..util.media import lufs

    res = ctx.resolved
    out: dict = {"sr": sr, "window_s": WIN, "fine_window_s": FINE, "errors": {}}
    if not ctx.info.has_audio:
        out["status"] = "no_audio"
        return out
    y = load_mono(ctx.mp4, sr)
    n = len(y)
    T = n / sr
    out["duration"] = rnd(T, 4)
    out["mix_rms_db"] = rnd(float(10 * np.log10(float((y.astype(np.float64) ** 2).mean()) + 1e-12)), 2)
    try:
        out["loudness"] = lufs(ctx.mp4)
    except Exception as e:
        out["errors"]["loudness"] = f"{type(e).__name__}: {e}"
    if ctx.stems:
        out["stems_listed_as_extra_evidence"] = sorted(paths.relp(p) for p in ctx.stems.values())

    # ---------------- BGM search
    bgm = res.audio.bgm
    bgm_al = None
    b_info: dict = {"planned": bool(bgm and bgm.path)}
    if bgm is not None and bgm.path:
        bp = paths.absp(bgm.path)
        b_info["expected"] = {"path": bgm.path, "track_id": bgm.track_id, "section_start_s": bgm.section_start_s,
                              "tempo_ratio": bgm.tempo_ratio, "gain_db": bgm.gain_db, "fade_in_s": bgm.fade_in_s,
                              "fade_out_s": bgm.fade_out_s, "silences": bgm.silences, "duck_ranges": bgm.duck_ranges}
        if not bp.is_file():
            b_info["status"] = "unmeasured"
            b_info["reason"] = f"BGM 원본 파일 없음: {bgm.path}"
        else:
            try:
                music = load_mono(bp, sr)
                rp = float(bgm.tempo_ratio or 1.0)
                fb = find_bgm(y, music, sr, tempo_center=rp)
                b_info["search"] = fb
                # waveform alignment for the planned tempo and the best envelope tempi
                cands = [rp] + [t for t, _ in (fb.get("top_tempi") or [])[:4]]
                tried: dict = {}
                refs: dict = {}
                for r in cands:
                    r_used = 1.0 if abs(r - 1.0) < 0.0025 else round(float(r), 4)
                    if any(abs(r_used - k) < 0.002 for k in tried):
                        continue
                    ref = music if r_used == 1.0 else load_mono(bp, sr, tempo=r_used)
                    ga = global_align(y, ref, sr=sr)
                    tried[r_used] = ga
                    refs[r_used] = ref
                b_info["tempo_candidates"] = {str(k): rnd(v["ncc"], 4) for k, v in tried.items()}
                r_best = max(tried, key=lambda k: tried[k]["ncc"])
                ga = tried[r_best]
                pl = next((v for k, v in tried.items() if abs(k - (1.0 if abs(rp - 1) < 0.0025 else rp)) < 0.002), None)
                b_info["planned_tempo_waveform_ncc"] = rnd(pl["ncc"], 4) if pl else None
                b_info["waveform_ncc"] = rnd(ga["ncc"], 4)
                if ga["ncc"] >= 0.3:
                    L = ga["lag"]
                    b_info["found"] = True
                    b_info["offset_method"] = "waveform cross-correlation"
                    b_info["tempo_obs"] = round(r_best, 4)
                    b_info["section_start_obs"] = rnd(L / sr * r_best, 4)
                    if ga.get("runner_up"):
                        b_info["runner_up_section"] = {"section_start_s": rnd(ga["runner_up"]["lag"] / sr * r_best, 3),
                                                       "ncc": ga["runner_up"]["ncc"]}
                    bgm_al = align_signal(refs[r_best], L, n)
                else:
                    b_info["found"] = False
                    b_info["reason"] = "계획한 음악 파일의 파형을 출력에서 찾지 못함(파형 상관 < 0.3)"
                b_info["status"] = "measured"
            except Exception as e:
                b_info["status"] = "unmeasured"
                b_info["reason"] = f"{type(e).__name__}: {e}"[:300]
    else:
        b_info["status"] = "not_planned"
    out["bgm"] = b_info

    # ---------------- originals (full-track regressors per clip)
    try:
        tracks = _full_original_tracks(ctx, n, sr)
    except Exception as e:
        tracks = []
        out["errors"]["originals"] = f"{type(e).__name__}: {e}"
    # refine each track's alignment a little (renderer latency / rounding)
    for tr in tracks:
        if tr["track"] is None:
            continue
        nz = np.nonzero(tr["track"])[0]
        if len(nz) < sr // 4:
            continue
        a, b = nz[0], nz[-1] + 1
        seg_ref = tr["track"][a:b]
        L, v = refine_offset(y[a:b], np.r_[np.zeros(int(0.1 * sr), np.float32), seg_ref, np.zeros(int(0.1 * sr), np.float32)],
                             int(0.1 * sr), int(0.1 * sr))
        tr["align_ncc"] = rnd(v, 3)
        shift = L - int(0.1 * sr)
        if v >= 0.3 and shift != 0:
            tr["track"] = align_signal(tr["track"], shift, n)
            tr["shift_s"] = rnd(shift / sr, 4)
    cols, names = [], []
    if bgm_al is not None:
        cols.append(bgm_al)
        names.append("bgm")
    for tr in tracks:
        if tr["track"] is not None:
            cols.append(tr["track"])
            names.append(f"orig:{tr['clip_id']}")

    # ---------------- pass 1 LS (no SFX) -> residual for the matched filter
    templates, tnotes = _sfx_templates(ctx, sr)
    out["sfx_templates"] = sorted({f"{v['type']}:{v['file']}" for v in templates.values()})
    if tnotes:
        out["sfx_template_notes"] = tnotes
    if cols:
        _, _, r1 = window_ls(y, cols, sr, FINE)
    else:
        r1 = y.copy()
    dets = detect_sfx(r1, templates, sr) if templates else []
    for d in dets:
        d["t"] = round(d["t"], 4)
        d["gain_db_file"] = rnd(20 * math.log10(max(1e-9, abs(d["gain"]))), 2)
    # ---------------- pass 2 LS with the detected SFX placed
    sfx_cols = [place(templates[d["key"]]["audio"], d["t"], 1.0, n, sr) for d in dets]
    all_cols = cols + sfx_cols
    if all_cols:
        tc, G, _ = window_ls(y, all_cols, sr, WIN)
        tcf, Gf, r2 = window_ls(y, all_cols, sr, FINE)
    else:
        tc = tcf = np.zeros(0)
        G = Gf = np.zeros((0, 0))
        r2 = y.copy()
    # ---------------- BGM gain curve
    if bgm_al is not None:
        g = G[:, 0]
        gf = Gf[:, 0]
        ref_g = float(np.nanpercentile(np.abs(g), 90)) if np.any(np.isfinite(g)) else float("nan")
        rel = db(np.abs(g) / ref_g) if ref_g > 0 else np.full_like(g, np.nan)
        relf = db(np.abs(gf) / ref_g) if ref_g > 0 else np.full_like(gf, np.nan)
        present_music = np.array([float(np.abs(bgm_al[int(max(0, (t - WIN / 2)) * sr):int((t + WIN / 2) * sr)]).max(initial=0)) > 1e-4
                                  for t in tc])
        b_info["plateau_gain"] = rnd(ref_g, 6)
        b_info["plateau_gain_db"] = rnd(20 * math.log10(ref_g), 2) if ref_g > 0 else None
        b_info["gain_curve"] = [[rnd(t, 3), rnd(v, 2)] for t, v in zip(tc, rel)]
        b_info["gain_curve_fine"] = [[rnd(t, 3), rnd(v, 2)] for t, v in zip(tcf, relf)]
        b_info["music_file_covers"] = [[rnd(t, 3), bool(p)] for t, p in zip(tc, present_music)]
        # measured ducks / silences on the fine curve
        depth = float((res.audio.bgm and 10.0) or 10.0)
        try:
            depth = float(ctx.preset.get("audio.ducking.depth_db"))
        except Exception:
            pass
        duck_thr = -max(3.0, min(6.0, depth / 2.0))
        sil = [(t - FINE / 2, t + FINE / 2) for t, v in zip(tcf, relf) if np.isfinite(v) and v <= -30.0]
        dk = [(t - FINE / 2, t + FINE / 2) for t, v in zip(tcf, relf) if np.isfinite(v) and -30.0 < v <= duck_thr]
        b_info["ducked_ranges_obs"] = [[rnd(a, 3), rnd(b, 3)] for a, b in merge_ranges(dk, gap=FINE * 1.5) if b - a >= 0.1]
        b_info["silent_ranges_obs"] = [[rnd(a, 3), rnd(b, 3)] for a, b in merge_ranges(sil, gap=FINE * 1.5) if b - a >= 0.1]
        b_info["duck_threshold_db"] = duck_thr
        # where the BGM ends (last window with the music present and audible)
        aud = [t for t, v in zip(tcf, relf) if np.isfinite(v) and v > -30]
        b_info["audible_span_obs"] = [rnd(min(aud), 3), rnd(max(aud), 3)] if aud else None
        if b_info.get("section_start_obs") is not None and aud:
            r_used = b_info.get("tempo_obs") or 1.0
            b_info["used_section_obs"] = [rnd(b_info["section_start_obs"] + r_used * min(aud), 3),
                                          rnd(b_info["section_start_obs"] + r_used * max(aud), 3)]
        # continuity (loop / jump): alignment quality in thirds of the audible span
        thirds = []
        for q in range(3):
            a_ = int(n * q / 3)
            b_ = int(n * (q + 1) / 3)
            yy, bb = y[a_:b_].astype(np.float64), bgm_al[a_:b_].astype(np.float64)
            den = math.sqrt(float((yy ** 2).sum()) * float((bb ** 2).sum()))
            thirds.append(rnd(float((yy * bb).sum() / den) if den > 0 else None, 3))
        b_info["ncc_by_third"] = thirds

    # ---------------- originals presence per window
    orig_rows = []
    kept = [(o.out_start, o.out_end) for o in res.audio.originals]
    exp_gain = {}
    for o in res.audio.originals:
        exp_gain.setdefault(o.clip_id, o.gain_db)
    ref_g = b_info.get("plateau_gain")
    bgm_gain_db = float(bgm.gain_db) if bgm is not None else None
    for k, nm in enumerate(names):
        if not nm.startswith("orig:"):
            continue
        cid = nm.split(":", 1)[1]
        col = cols[k]
        for w, t in enumerate(tc):
            a, b = int(max(0, t - WIN / 2) * sr), int(min(n, (t + WIN / 2) * sr))
            if float(np.abs(col[a:b]).max(initial=0)) < 1e-4:
                continue
            gk = G[w, k] if w < len(G) else np.nan
            if not np.isfinite(gk):
                continue
            xs = col[a:b].astype(np.float64) * gk
            contrib = 10 * math.log10(float((xs ** 2).mean()) + 1e-12) - 10 * math.log10(float((y[a:b].astype(np.float64) ** 2).mean()) + 1e-12)
            row = {"t": rnd(t, 3), "clip_id": cid, "gain": rnd(gk, 5), "gain_db": rnd(20 * math.log10(max(1e-9, abs(gk))), 2),
                   "contrib_db": rnd(contrib, 2), "kept_expected": in_ranges(t, kept)}
            if ref_g and bgm_gain_db is not None:
                row["gain_db_mix_scale"] = rnd(20 * math.log10(max(1e-9, abs(gk)) / ref_g) + bgm_gain_db, 2)
            row["present"] = bool(contrib > -15.0 and abs(gk) > 0.05 * (ref_g / (10 ** (bgm_gain_db / 20)) if ref_g and bgm_gain_db is not None else 0.0))
            orig_rows.append(row)
    out["originals"] = {"tracks": [{k: v for k, v in tr.items() if k != "track"} for tr in tracks],
                        "expected_kept": [[rnd(a, 3), rnd(b, 3)] for a, b in kept],
                        "expected_gain_db": exp_gain, "windows": orig_rows,
                        "present_ranges_obs": [[rnd(a, 3), rnd(b, 3)] for a, b in merge_ranges(
                            [(r["t"] - WIN / 2, r["t"] + WIN / 2) for r in orig_rows if r["present"]], gap=0.01)]}
    # ---------------- SFX gains relative to the BGM heard at the same moment
    env = _planned_bgm_env(ctx)
    for i, d in enumerate(dets):
        if bgm_al is not None and ref_g:
            d["gain_db_rel_bgm_plateau"] = rnd(20 * math.log10(max(1e-9, abs(d["gain"])) / ref_g), 2)
            a_, b_ = d["t"], d["t"] + max(0.05, min(d["len"], 0.5))
            loc = [abs(Gf[w, 0]) for w, tt in enumerate(tcf) if a_ - FINE / 2 <= tt <= b_ + FINE / 2 and np.isfinite(Gf[w, 0])]
            planned_extra = env(d["t"]) if env else 0.0
            if loc and np.median(loc) > 0 and planned_extra > -40 and bgm_gain_db is not None:
                g_loc = float(np.median(loc))
                d["bgm_local_gain_db_rel_plateau"] = rnd(20 * math.log10(g_loc / ref_g), 2)
                # SFX level in the plan's dB scale = SFX/BGM(now) ratio + planned BGM level now
                d["gain_db_mix_scale"] = rnd(20 * math.log10(max(1e-9, abs(d["gain"])) / g_loc) + bgm_gain_db + planned_extra, 2)
                d["gain_reference"] = "local_bgm"
            elif bgm_gain_db is not None:
                d["gain_db_mix_scale"] = rnd(d["gain_db_rel_bgm_plateau"] + bgm_gain_db, 2)
                d["gain_reference"] = "bgm_plateau (BGM 없음/정적 구간)"
        d.pop("key", None)
    out["sfx"] = {"detections": dets, "threshold_ncc": 0.45}
    # ---------------- unexplained onsets in the final residual
    exclude = [(d["t"] - 0.05, d["t"] + d["len"] + 0.05) for d in dets] + [(a - 0.1, b + 0.1) for a, b in kept]
    try:
        out["unexplained_onsets"] = unexplained_onsets(r2, y, sr, exclude, model=(y - r2).astype(np.float32))
    except Exception as e:
        out["errors"]["onsets"] = f"{type(e).__name__}: {e}"
    out["residual_rms_db_rel_mix"] = rnd(10 * math.log10(float((r2.astype(np.float64) ** 2).mean()) + 1e-12)
                                         - 10 * math.log10(float((y.astype(np.float64) ** 2).mean()) + 1e-12), 2)
    out["status"] = "measured"
    return out
