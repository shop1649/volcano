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
    """Decode to mono float32 with an explicit (L+R)/2 downmix for stereo (ffmpeg's default -ac 1
    uses 0.707*(L+R), which would make a mono signal placed on both channels look +3 dB louder
    than a stereo one).  Optional pitch-preserving tempo change (ffmpeg atempo chain)."""
    from ..util.media import FFMPEG, probe

    info = probe(path)
    if not info.has_audio:
        dur = duration if duration is not None else max(0.0, info.duration - (start or 0.0))
        return np.zeros(int(round(dur * sr)), np.float32)
    chain = []
    ch = int(info.audio_channels or 1)
    if ch == 2:
        chain.append("pan=mono|c0=0.5*c0+0.5*c1")
    if abs(tempo - 1.0) >= 1e-6:
        r = float(tempo)
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
    args += ["-vn"]
    if chain:
        args += ["-af", ",".join(chain)]
    args += ["-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
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
    valid = ncc_all[ok]
    ncc_all = np.where(ok, ncc_all, -np.inf)
    k = int(np.argmax(ncc_all))
    best = float(ncc_all[k])
    # detection significance: how far the peak stands above the correlation at all other lags
    z = float((best - valid.mean()) / (valid.std() + 1e-12)) if valid.size > 10 else 0.0
    sr_guard = int(0.5 * sr)
    far = ncc_all.copy()
    far[max(0, k - sr_guard):k + sr_guard] = -np.inf
    k2 = int(np.argmax(far))
    ru = {"lag": int(L[k2]), "ncc": round(float(far[k2]), 4)} if np.isfinite(far[k2]) else None
    return {"lag": int(L[k]), "ncc": best, "runner_up": ru, "z": z}


def local_match(y: np.ndarray, ref_al: np.ndarray, sr: int = SR, win: float = 0.25) -> dict:
    """How well an aligned reference explains the mix, window by window.
    q95/q70 of per-window NCC (the music matches almost perfectly wherever it dominates) and the
    energy fraction a per-window gain fit explains, versus the same fit with the reference
    shifted to unrelated offsets (null)."""
    L = int(win * sr)
    vals = []
    for a in range(0, len(y) - L + 1, L):
        yw = y[a:a + L].astype(np.float64)
        rw = ref_al[a:a + L].astype(np.float64)
        er = float((rw ** 2).sum())
        ey = float((yw ** 2).sum())
        if er < 1e-9 or ey < 1e-12:
            continue
        vals.append(float((yw * rw).sum() / np.sqrt(er * ey)))

    def explained(r):
        _, _, res = window_ls(y, [r], sr, win)
        return 1.0 - float((res.astype(np.float64) ** 2).sum()) / max(1e-12, float((y.astype(np.float64) ** 2).sum()))

    ex = explained(ref_al)
    nulls = []
    for sh in (0.31, 0.73, 1.37):
        k = int(sh * sr)
        nulls.append(explained(np.r_[ref_al[k:], np.zeros(k, np.float32)]))
    null = float(np.median(nulls))
    if not vals:
        return {"n": 0, "q95": 0.0, "q70": 0.0, "explained": round(ex, 4), "explained_null": round(null, 4)}
    return {"n": len(vals), "q95": round(float(np.percentile(vals, 95)), 4), "q70": round(float(np.percentile(vals, 70)), 4),
            "explained": round(ex, 4), "explained_null": round(null, 4)}


def match_found(lm: dict) -> bool:
    """The file is in the mix at this alignment when, in the windows where it dominates, the mix
    matches it almost exactly (q95 of 0.25 s window NCC >= 0.7; unrelated music stays < 0.5).
    The explained-energy numbers are reported but not used: per-window gain fits also explain some
    energy with a wrong tempo."""
    return bool(lm.get("q95", 0) >= 0.7)


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


def fitted_part(cols: list[np.ndarray], G: np.ndarray, idx: list[int], n: int, sr: int, win: float) -> np.ndarray:
    """Sum over the columns ``idx`` of (per-window gain x column), as ``window_ls`` fitted them."""
    L = max(1, int(round(win * sr)))
    out = np.zeros(n, np.float64)
    for w in range(G.shape[0]):
        a, b = w * L, min(n, (w + 1) * L)
        for k in idx:
            g = G[w, k]
            if np.isfinite(g):
                out[a:b] += g * cols[k][a:b].astype(np.float64)
    return out.astype(np.float32)


def kept_audio_checks(ctx: QAContext, voice_out: np.ndarray, sr: int, bgm_found: bool) -> dict:
    """What the kept original sound IS in the output: ``voice_out`` = output mix minus the fitted BGM and SFX (the
    kept originals + whatever else is not ours).  On it, with the SAME detectors ``episode validate`` uses on the
    source (``shortkit.edit.audio_checks``):
      * music_presence per kept range (music left in the kept voice: embedded music not removed);
      * speech_spans over the whole programme (output seconds) -- speech inside kept ranges and under ducked BGM.
    Without the BGM located in the mix the BGM cannot be removed: both are unmeasured (never judged on the mix)."""
    from ..edit.audio_checks import music_presence, speech_spans

    res = ctx.resolved
    out: dict = {"method": "출력 믹스 − (찾은 BGM·효과음의 창별 최소제곱 맞춤) = 보존 원음 + 설명되지 않은 소리; "
                           "edit.audio_checks 의 음악·음성 검출기로 측정(합성 음원으로만 검증된 공학 규칙)"}
    planned_bgm = res.audio.bgm is not None and bool(getattr(res.audio.bgm, "path", None))
    if planned_bgm and not bgm_found:
        why = "계획한 BGM 을 출력에서 찾지 못해 믹스에서 뺄 수 없음(음악 판정을 BGM 과 구별 못 함)"
        out["music"] = [{"index": i, "clip_id": o.clip_id, "range_out": [rnd(o.out_start), rnd(o.out_end)],
                         "status": "unmeasured", "reason": why} for i, o in enumerate(res.audio.originals)]
        out["speech"] = {"status": "unmeasured", "spans": [], "reason": why}
        return out
    import os
    import tempfile

    from scipy.io import wavfile

    fd, tmp = tempfile.mkstemp(suffix=".wav", prefix="qa_voice_out_")
    os.close(fd)
    try:
        wavfile.write(tmp, sr, np.clip(voice_out, -1.0, 1.0).astype(np.float32))
        items = []
        for i, o in enumerate(res.audio.originals):
            fade = float(getattr(o, "fade_s", 0.0) or 0.0)
            rng = (float(o.out_start) + fade, float(o.out_end) - fade)
            m = music_presence(tmp, [rng]) if rng[1] > rng[0] else {"status": "unmeasured", "reason": "구간 없음"}
            items.append({"index": i, "clip_id": o.clip_id, "range_out": [rnd(rng[0]), rnd(rng[1])],
                          **{k: m.get(k) for k in ("status", "polyphonic_share", "sustained_share", "active_s", "reason")},
                          "method": m.get("method")})
        out["music"] = items
        sp = speech_spans(tmp)
        out["speech"] = {"status": sp["status"], "spans": [[rnd(a), rnd(b)] for a, b in sp.get("spans") or []],
                         "reason": sp.get("reason"), "method": sp.get("method")}
    finally:
        try:
            os.unlink(tmp)
        except OSError:
            pass
    return out


def classify_sfx_detections(ctx: QAContext, dets: list[dict]) -> dict:
    """The catalog TYPE of every detected SFX, from its sound: the detected file's log-mel fingerprint against every
    catalog type's centroid (``presets/<p>/sfx_fp/<type>.npy``; the method and threshold of ``reference.sfx_map`` and
    ``edit.validate.sfx_file_similarity``) -- never the plan's label.  Adds ``catalog_type`` {status, type_id,
    similarity, runner_up} to each detection; returns the summary."""
    from .. import paths
    from ..util.jsonio import read_json

    try:
        rel = ctx.preset.get("audio.sfx.catalog")
    except KeyError:
        rel = None
    cat = read_json(paths.absp(rel)) if rel else None
    from ..edit.validate import catalog_counts_measured

    # a 'partial' catalog (every target video analysed and counted; only a per-type column such as emotion missing)
    # has its type fingerprints: the rule of episode validate (edit.validate.catalog_counts_measured) decides
    if not cat or not catalog_counts_measured(cat):
        why = ("효과음 카탈로그 미측정(상태 " + str((cat or {}).get("status") or "없음") + ": "
               + str((cat or {}).get("blocker") or "없음")[:160] + ") — 종류 지문 없음")
        for d in dets:
            d["catalog_type"] = {"status": "unmeasured", "type_id": None, "reason": why}
        return {"status": "unmeasured", "reason": why, "catalog_status": (cat or {}).get("status")}
    cents = []
    for t in cat.get("types") or []:
        c = (t.get("fingerprint") or {}).get("centroid")
        if t.get("type_id") and c and paths.absp(c).is_file():
            cents.append((t["type_id"], t.get("class"), c))
    if not cents:
        why = "카탈로그에 지문(centroid) 파일이 있는 종류가 없음"
        for d in dets:
            d["catalog_type"] = {"status": "unmeasured", "type_id": None, "reason": why}
        return {"status": "unmeasured", "reason": why}
    from ..edit.validate import sfx_file_similarity
    from ..reference.sfx_map import MATCH_THRESHOLD

    by_file: dict = {}
    for d in dets:
        f = d.get("file")
        if f in by_file:
            d["catalog_type"] = dict(by_file[f])
            continue
        try:
            sims = sorted(((sfx_file_similarity(f, c), tid, cls) for tid, cls, c in cents), reverse=True)
        except Exception as e:  # never a silent pass
            ent = {"status": "unmeasured", "type_id": None, "reason": f"지문 계산 실패: {type(e).__name__}: {e}"[:200]}
        else:
            best = sims[0]
            ent = {"status": "measured", "type_id": best[1] if best[0] >= MATCH_THRESHOLD else None,
                   "class": best[2] if best[0] >= MATCH_THRESHOLD else None, "similarity": round(float(best[0]), 3),
                   "best_candidate": best[1], "threshold": MATCH_THRESHOLD,
                   "runner_up": ({"type_id": sims[1][1], "similarity": round(float(sims[1][0]), 3)} if len(sims) > 1 else None)}
        by_file[f] = ent
        d["catalog_type"] = dict(ent)
    return {"status": "measured", "types_with_centroid": len(cents), "files": len(by_file),
            "catalog_status": cat.get("status")}


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


def detect_sfx(res: np.ndarray, templates: dict, sr: int = SR, thr: float = 0.45, max_iter: int = 60) -> list[dict]:
    """Matching pursuit with normalised matched filters: repeatedly take the best-matching
    (template, time) over all known SFX files, record it, subtract its fitted copy, and search
    again.  Subtracting stops a tonal SFX's own tail from being detected as a second sound."""
    from scipy.signal import find_peaks

    r = res.astype(np.float64).copy()
    tps = {k: v for k, v in templates.items() if len(v["audio"]) >= 16}
    out: list[dict] = []
    for _ in range(max_iter):
        best = None
        for key, tp in tps.items():
            s = tp["audio"]
            c = matched_ncc(r, s)
            if not len(c):
                continue
            pk, props = find_peaks(c, height=thr, distance=max(1, int(0.05 * sr)))
            if not len(pk):
                continue
            j = int(np.argmax(props["peak_heights"]))
            if best is None or props["peak_heights"][j] > best[0]:
                best = (float(props["peak_heights"][j]), key, int(pk[j]))
        if best is None:
            break
        h, key, p = best
        s = tps[key]["audio"].astype(np.float64)
        seg = r[p:p + len(s)]
        g = float((seg * s[:len(seg)]).sum() / max(1e-12, float((s[:len(seg)] ** 2).sum())))
        r[p:p + len(s)] -= g * s[:len(seg)]
        if any(o["key"] == key and abs(o["t"] - p / sr) < 0.02 for o in out):
            continue                       # numerical re-hit of the same event
        if g <= 0:
            continue                       # anti-correlated leftover, not a sound
        # a same-type hit inside an earlier detection's span that is much weaker is that sound's
        # own tail left over after subtraction (e.g. a limiter changed its envelope), not a new one
        if any(o["key"] == key and o["t"] <= p / sr < o["t"] + o["len"] and g < 0.5 * o["gain"] for o in out):
            continue
        out.append({"t": p / sr, "sample": int(p), "key": key, "type": tps[key]["type"], "file": tps[key].get("file"),
                    "ncc": h, "gain": g, "len": len(s) / sr})
    out.sort(key=lambda d: d["t"])
    return out


# a matched component this far below the programme over its own span is masked -- not a placed sound but fit
# leakage in the residual (the same -24 dB floor the unexplained-onset detector uses).  Measured on the test
# renders: every placed SFX contributes -11.5..+0.1 dB (test-pipeline-001, test-coverage-001, test-qa-good/bad);
# a "pop" matched at NCC 0.51 inside loud kept speech (test-pipeline-001 10.74 s) contributed -34.3 dB.
SFX_MIN_CONTRIB_DB = -24.0


def sfx_contrib_db(y: np.ndarray, sample: int, tmpl: np.ndarray, gain: float) -> float | None:
    """Energy of the fitted SFX over its span relative to the output mix over the same span (dB)."""
    a = int(sample)
    b = min(len(y), a + len(tmpl))
    if b - a < 16:
        return None
    es = (float(gain) ** 2) * float((tmpl[:b - a].astype(np.float64) ** 2).sum())
    ey = float((y[a:b].astype(np.float64) ** 2).sum())
    return 10 * math.log10(es / ey + 1e-12) if ey > 0 else None


def place(template: np.ndarray, t: float, g: float, n: int, sr: int = SR) -> np.ndarray:
    out = np.zeros(n, np.float32)
    a = int(round(t * sr))
    b = min(n, a + len(template))
    if b > a >= 0:
        out[a:b] = g * template[:b - a]
    return out


def lowpass(x: np.ndarray, sr: int = SR, fc: float = 5000.0) -> np.ndarray:
    """Zero-phase low-pass.  AAC keeps the waveform of the low band; above ~5 kHz it may replace
    noise-like content (perceptual noise substitution), which breaks waveform matching of noisy
    SFX (whoosh, scratch) and biases their gains low."""
    from scipy.signal import butter, sosfiltfilt

    if len(x) < 64:
        return x.astype(np.float32)
    sos = butter(6, fc, btype="low", fs=sr, output="sos")
    return sosfiltfilt(sos, x.astype(np.float64)).astype(np.float32)


def sfx_joint_gain(y: np.ndarray, t: float, tmpl: np.ndarray, cols: list[np.ndarray], sr: int = SR,
                   win: float = FINE) -> float | None:
    """Gain of one SFX occurrence from a joint least-squares fit over its span: one coefficient
    for the SFX, one per short window for every other known signal (their gains may vary)."""
    a = int(round(t * sr))
    b = min(len(y), a + len(tmpl))
    if b - a < 16:
        return None
    L = max(1, int(win * sr))
    X = [np.r_[tmpl[:b - a]].astype(np.float64)]
    for c in cols:
        seg = c[a:b].astype(np.float64)
        if float(np.abs(seg).max(initial=0)) < 1e-6:
            continue
        for w0 in range(0, b - a, L):
            piece = np.zeros(b - a)
            piece[w0:w0 + L] = seg[w0:w0 + L]
            if float((piece ** 2).sum()) > 1e-9:
                X.append(piece)
    A = np.stack(X, axis=1)
    g, *_ = np.linalg.lstsq(A, y[a:b].astype(np.float64), rcond=None)
    return float(g[0])


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


def _planned_loop(ctx: QAContext, bgm, file_dur_s: float, out_dur_s: float) -> dict | None:
    """The plan's BGM loop geometry (None when no loop is planned or needed): with audio.bgm.loop the music
    from section_start (at the tempo) repeats from section_start every (segment - crossfade) seconds, the
    crossfade being audio.bgm.loop_xfade_s (``shortkit.edit.render.loop_fill`` is the renderer's side)."""
    if not getattr(bgm, "loop", False):
        return None
    r = float(bgm.tempo_ratio or 1.0)
    seg = (file_dur_s - float(bgm.section_start_s)) / r
    if seg >= out_dur_s - 1e-3:
        return None
    try:
        xf = float(ctx.preset.get("audio.bgm.loop_xfade_s"))
    except (KeyError, TypeError, ValueError):
        return {"error": "audio.bgm.loop_xfade_s 없음 — 반복 지점 크로스페이드 길이를 모름", "segment_s": round(seg, 4),
                "starts_out_s": [], "xfade_s": None, "section_start_s": float(bgm.section_start_s)}
    P = seg - xf
    starts = []
    t = P
    while P > 0 and t < out_dur_s:
        starts.append(round(t, 4))
        t += P
    return {"segment_s": round(seg, 4), "period_s": round(P, 4), "xfade_s": xf, "starts_out_s": starts,
            "section_start_s": float(bgm.section_start_s)}


def bgm_loop_pieces(y: np.ndarray, ref: np.ndarray, sr: int, r: float, starts_out_s: list[float],
                    xfade_s: float | None, margin_s: float = 0.1) -> dict:
    """Measure a looped BGM piece by piece: the output between consecutive planned loop starts (minus the
    crossfade and a margin) is aligned on its own with the music at tempo ``r`` (``global_align``) ->
    per piece the music time at the piece's start (original-file seconds) and the window match (q95).
    Also returns the aligned regressor (each piece at its measured lag, equal-power crossfades at the
    planned loop starts)."""
    n = len(y)
    xf = float(xfade_s or 0.0)
    bounds = [0.0] + [float(t) for t in starts_out_s] + [n / sr]
    pieces, lags = [], []
    for k in range(len(bounds) - 1):
        a, b = bounds[k], bounds[k + 1]
        a_m = a + (xf + margin_s if k > 0 else 0.0)
        b_m = b - margin_s
        item = {"piece": k, "out": [rnd(a, 3), rnd(b, 3)], "measured_span": [rnd(a_m, 3), rnd(b_m, 3)],
                "section_start_obs": None, "q95": None}
        if b_m - a_m < 0.5:
            item["reason"] = "조각이 너무 짧음(< 0.5 s)"
            pieces.append(item)
            lags.append(None)
            continue
        A, B = int(round(a_m * sr)), int(round(b_m * sr))
        seg = y[A:B]
        ga = global_align(seg, ref, sr=sr)
        lm = local_match(seg, align_signal(ref, ga["lag"], len(seg)), sr)
        lag_full = ga["lag"] - A                       # y[t] ~ ref[t + lag_full] on the whole timeline
        item["section_start_obs"] = rnd((ga["lag"] / sr - (a_m - a)) * r, 4)   # music time at the piece start
        item["q95"] = lm.get("q95")
        item["found"] = match_found(lm)
        item["waveform_ncc"] = rnd(ga["ncc"], 4)
        pieces.append(item)
        lags.append(lag_full if item["found"] else None)
    aligned = None
    if all(v is not None for v in lags):
        aligned = np.zeros(n, np.float32)
        nx = int(round(xf * sr))
        th = (np.arange(max(nx, 1)) + 0.5) / max(nx, 1) * (math.pi / 2)
        for k, L in enumerate(lags):
            w = np.zeros(n, np.float32)
            s0 = int(round(bounds[k] * sr))
            s1 = int(round(bounds[k + 1] * sr))
            w[s0:s1] = 1.0
            if k > 0 and nx > 0:                    # fade in over [s0, s0 + nx)
                e = min(n, s0 + nx)
                w[s0:e] = np.sin(th[:e - s0])
            if k < len(lags) - 1 and nx > 0:        # fade out over [s1, s1 + nx) (overlaps the next piece)
                e = min(n, s1 + nx)
                w[s1:e] = np.cos(th[:e - s1])
            aligned += w * align_signal(ref, L, n)
    return {"pieces": pieces, "aligned": aligned,
            "method": "반복 조각별 파형 상호상관(global_align) — 조각 시작의 원곡 시각 = section_start 여야 함"}


def kept_levels_obs(ctx: QAContext, orig_rows: list[dict], mix_lufs: float | None) -> list[dict]:
    """Kept original sound level relative to the programme, measured on the output -- the definition of
    audio.original.keep_gain_db (``ref audio-measure``: kept speech integrated loudness - mix integrated
    loudness, LU) and of the renderer's gain rule T + keep_gain_db - L_src (``shortkit.edit.audio``):

        rel = L_src + 20 log10(g) - L_mix

    L_src = integrated loudness of the kept source audio (``edit.audio.kept_levels``: per clip, per source
    when a clip keeps < KEPT_LEVEL_MIN_S; the SOURCE file is an input, not the renderer's output), g = median
    least-squares gain of that clip's source track in the output mix over its kept windows (0.25 s, edges
    +-0.15 s excluded, windows where the original is present), L_mix = the MP4's integrated loudness.  The
    renderer's own stems are never used."""
    from ..edit.audio import kept_levels

    res = ctx.resolved
    kept = [{"clip_id": o.clip_id, "path": o.path, "src_start": o.src_start, "src_end": o.src_end}
            for o in res.audio.originals]
    levels = kept_levels(kept) if kept else {}
    out = []
    for i, o in enumerate(res.audio.originals):
        lv = levels.get(i) or {}
        ws = [w for w in orig_rows if w["clip_id"] == o.clip_id and w.get("present")
              and o.out_start + 0.15 <= w["t"] <= o.out_end - 0.15 and w.get("gain") is not None]
        g = float(np.median([abs(float(w["gain"])) for w in ws])) if ws else None
        item = {"index": i, "clip_id": o.clip_id, "out": [rnd(o.out_start, 3), rnd(o.out_end, 3)],
                "src_lufs": lv.get("lufs"), "src_scope": lv.get("scope"), "src_seconds": lv.get("seconds"),
                "fit_gain_db": rnd(20 * math.log10(g), 2) if g and g > 0 else None, "n_windows": len(ws),
                "mix_lufs": mix_lufs, "rel_lu_obs": None}
        if lv.get("lufs") is None:
            item["reason"] = lv.get("reason") or "소스 음량 측정 실패"
        elif not g or g <= 0:
            item["reason"] = "출력에서 원음 창을 찾지 못함(존재 창 없음)"
        elif mix_lufs is None:
            item["reason"] = "출력 통합 음량 측정 실패"
        else:
            item["rel_lu_obs"] = rnd(float(lv["lufs"]) + 20 * math.log10(g) - float(mix_lufs), 2)
        out.append(item)
    return out


# ----------------------------------------------------------------------------- main probe
# ----------------------------------------------------------------------------- BGM level and edge ramps
# The reference analyzers measure these on the reference mix (shortkit.reference.audio_original / audio_bgm); QA runs
# the SAME functions on the output so both sides are read with one definition:
#   level      audio.bgm.gain_db = LS gain of the clean file + (target LUFS - mix LUFS)   (ref audio-measure)
#   silences   measure_silence_ramps  (renderer shape: dB-linear 0 -> -120 dB)            -> audio.silence.fade_s
#   ducking    measure_ducking on the BGM gain curve under the speech measured in the output -> attack_s / release_s
#   originals  measure_original_ramps (renderer shape: linear amplitude)                  -> audio.original.fade_s
def bgm_level_obs(plateau_gain_db: float | None, target_lufs: float | None, mix_lufs: float | None) -> dict:
    """BGM level at the final programme loudness as `ref audio-measure` defines audio.bgm.gain_db: the LS gain of the
    clean file in the mix (dB, the BGM plateau = 90th percentile of the 0.25 s window gains) + target LUFS - the mix's
    measured integrated LUFS."""
    method = ("깨끗한 음원 LS 이득(0.25 s 창 이득의 p90 = BGM 기준 레벨, dB) + 목표 LUFS − 출력 통합 LUFS "
              "(ref audio-measure 의 audio.bgm.gain_db 와 같은 정의)")
    if plateau_gain_db is None or target_lufs is None or mix_lufs is None:
        return {"status": "unmeasured", "method": method,
                "reason": "BGM 이득 또는 출력 음량을 재지 못함" if plateau_gain_db is None or mix_lufs is None else "목표 음량 없음"}
    return {"status": "measured", "level_db": rnd(plateau_gain_db + float(target_lufs) - float(mix_lufs), 2),
            "ls_gain_db": rnd(plateau_gain_db, 2), "mix_lufs": mix_lufs, "target_lufs": target_lufs, "method": method}


def _bgm_model(bgm_sig: np.ndarray, aligned: np.ndarray, sr: int):
    """A reference BgmModel (waveform mode) of the output: the clean file aligned to the output (unit gain) and the
    BGM gain curve of ``bgm_sig`` against it (reference.audio_bgm.gain_curve_waveform)."""
    from ..reference.audio_bgm import GAIN_HOP_S, BgmModel, gain_curve_waveform

    t, g, on = gain_curve_waveform(bgm_sig, aligned, sr)
    return BgmModel(mode="waveform", sr=sr, aligned=aligned, valid=None, t=t, gain=g,
                    gain_db=20 * np.log10(np.maximum(g, 1e-5)), clean_on=on, hop_s=GAIN_HOP_S)


def planned_bgm_signal(ctx: QAContext, aligned: np.ndarray, sr: int) -> np.ndarray:
    """The planned BGM of the IR (fades x envelope, the renderer's own functions) on the aligned clean file: what the
    output's BGM would be if the renderer drew exactly the plan."""
    from ..edit.render import _lin_fade, envelope_gain

    b = ctx.resolved.audio.bgm
    n = len(aligned)
    g = _lin_fade(n, sr, float(b.fade_in_s or 0.0), float(b.fade_out_s or 0.0)) * envelope_gain(b.envelope or [], n, sr)
    return (aligned.astype(np.float64) * g).astype(np.float32)


def bgm_ramps(ctx: QAContext, bgm_sig: np.ndarray, aligned: np.ndarray, sr: int, speech: list | None) -> dict:
    """Intentional-silence ramps and ducking attack / release of the output's BGM, each measured twice with the same
    reference function: on the output (``bgm_sig`` = mix minus the fitted original sound and SFX) and on the planned
    BGM signal (IR envelope on the same aligned clean file) -- the planned reading is what the measurement gives for
    the renderer's planned ramp (window blur included), so observed vs planned compares like with like."""
    from ..reference.audio_original import measure_ducking, measure_silence_ramps

    out: dict = {}
    b = ctx.resolved.audio.bgm
    obs_m = _bgm_model(bgm_sig, aligned, sr)
    plan_sig = planned_bgm_signal(ctx, aligned, sr)
    plan_m = _bgm_model(plan_sig, aligned, sr)
    items_o = [{"start": float(a), "end": float(c), "bgm_cut": True} for a, c in (b.silences or [])]
    items_p = [dict(x) for x in items_o]
    try:
        meth = measure_silence_ramps(bgm_sig, obs_m, items_o, sr)
        measure_silence_ramps(plan_sig, plan_m, items_p, sr)
        out["silences"] = {"method": meth.get("method"), "blocker": meth.get("blocker"),
                           "items": [{"range": [rnd(o["start"], 3), rnd(o["end"], 3)], "observed": o.get("ramps"),
                                      "planned_reading": p.get("ramps")} for o, p in zip(items_o, items_p)]}
    except Exception as e:  # never a silent pass
        out["silences"] = {"status": "unmeasured", "reason": f"{type(e).__name__}: {e}"[:300]}
    sp = [{"start": float(a), "end": float(c)} for a, c in (speech or [])]
    try:
        do = measure_ducking(obs_m, sp)
        dp = measure_ducking(plan_m, sp)
        keep = ("presence", "blocker", "depth_db", "attack_s", "release_s", "method")
        out["ducking"] = {"observed": {k: do.get(k) for k in keep if k in do},
                          "planned_reading": {k: dp.get(k) for k in keep if k in dp},
                          "per_segment": [{"start": rnd(x["start"], 3), "end": rnd(x["end"], 3),
                                           **{k: x.get(k) for k in ("status", "depth_db", "attack_s", "release_s",
                                                                    "blocker")},
                                           "planned_reading": {k: y.get(k) for k in ("status", "depth_db", "attack_s",
                                                                                      "release_s")}}
                                          for x, y in zip(do.get("per_segment") or [], dp.get("per_segment") or [])],
                          "speech_used": [[rnd(x["start"], 3), rnd(x["end"], 3)] for x in sp]}
    except Exception as e:
        out["ducking"] = {"status": "unmeasured", "reason": f"{type(e).__name__}: {e}"[:300]}
    return out


def original_ramps(ctx: QAContext, orig_sig: np.ndarray, sr: int) -> dict:
    """On/off edge ramps of the kept original sound in the output (reference.audio_original.measure_original_ramps on
    ``orig_sig`` = mix minus the fitted BGM and SFX), per kept range of the IR; in the renderer's audio.original.fade_s
    units.  Only edges followed by stationary sound are measurable (speech starting at the edge shows its own attack)."""
    from ..reference.audio_original import measure_original_ramps

    segs = [{"start": float(o.out_start), "end": float(o.out_end)} for o in ctx.resolved.audio.originals]
    if not segs:
        return {"items": []}
    edges = measure_original_ramps(orig_sig, segs, sr)
    items = []
    for i, o in enumerate(ctx.resolved.audio.originals):
        # measure_original_ramps returns (on, off) per segment in order ('t' of a measured edge is its crossing time)
        es = [dict(e, edge_t=round(float(o.out_start if e["edge"] == "on" else o.out_end), 3))
              for e in edges[2 * i:2 * i + 2]]
        items.append({"index": i, "clip_id": o.clip_id, "planned_fade_s": o.fade_s, "edges": es})
    return {"items": items, "method": "reference.audio_original.measure_original_ramps(출력 − 찾은 BGM·효과음)"}


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
                    ga["local"] = local_match(y, align_signal(ref, ga["lag"], n), sr)
                    tried[r_used] = ga
                    refs[r_used] = ref
                b_info["tempo_candidates"] = {str(k): {"ncc": rnd(v["ncc"], 4), **v["local"]} for k, v in tried.items()}
                r_best = max(tried, key=lambda k: (tried[k]["local"]["q95"], tried[k]["ncc"]))
                ga = tried[r_best]
                pl = next((v for k, v in tried.items() if abs(k - (1.0 if abs(rp - 1) < 0.0025 else rp)) < 0.002), None)
                b_info["planned_tempo_waveform_ncc"] = rnd(pl["ncc"], 4) if pl else None
                b_info["waveform_ncc"] = rnd(ga["ncc"], 4)
                b_info["local_match"] = ga["local"]
                # the planned file is "found" when, at its best lag, the mix matches it almost exactly
                # wherever it dominates
                if match_found(ga["local"]):
                    L = ga["lag"]
                    b_info["found"] = True
                    b_info["offset_method"] = "waveform cross-correlation"
                    b_info["tempo_obs"] = round(r_best, 4)
                    b_info["section_start_obs"] = rnd(L / sr * r_best, 4)
                    if ga.get("runner_up"):
                        ru_l = ga["runner_up"]["lag"]
                        lm_ru = local_match(y, align_signal(refs[r_best], ru_l, n), sr)
                        b_info["runner_up_section"] = {"section_start_s": rnd(ru_l / sr * r_best, 3),
                                                       "ncc": ga["runner_up"]["ncc"], "explained": lm_ru["explained"],
                                                       "q95": lm_ru["q95"]}
                    bgm_al = align_signal(refs[r_best], L, n)
                    lp = _planned_loop(ctx, bgm, len(music) / sr, T)
                    if lp is not None:
                        # the music loops back to section_start: one alignment per repeat (a single lag fits one
                        # piece only); the regressor for the gain curves follows the measured pieces
                        lpm = bgm_loop_pieces(y, refs[r_best], sr, r_best, lp["starts_out_s"], lp["xfade_s"])
                        b_info["loop"] = {"planned": lp, **{k: v for k, v in lpm.items() if k != "aligned"}}
                        if lpm.get("aligned") is not None:
                            bgm_al = lpm["aligned"]
                            if lpm["pieces"] and lpm["pieces"][0].get("section_start_obs") is not None:
                                b_info["section_start_obs"] = lpm["pieces"][0]["section_start_obs"]
                                b_info["offset_method"] = "waveform cross-correlation per loop piece"
                                b_info.pop("runner_up_section", None)
                else:
                    b_info["found"] = False
                    b_info["reason"] = "계획한 음악 파일의 파형을 출력에서 찾지 못함(0.25초 창별 상관 q95 < 0.7)"
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
    # SFX matching in the low band (see lowpass())
    tpl_lp = {k: dict(v, audio=lowpass(v["audio"], sr)) for k, v in templates.items()}
    dets = detect_sfx(lowpass(r1, sr), tpl_lp, sr) if templates else []
    out["sfx_band"] = "0-5 kHz (AAC 고역 잡음 대체 영향 제외)"
    for d in dets:
        # the exact matched sample is kept for placement and gain: re-deriving it from a time rounded to 0.1 ms
        # moved a noise-like whoosh by one sample (22.05 kHz) and its fitted gain fell 3.3 dB (test-pipeline-001 fx1)
        d["t"] = round(d["t"], 4)
        d["gain_db_file"] = rnd(20 * math.log10(max(1e-9, abs(d["gain"]))), 2)
    # ---------------- pass 2 LS with the detected SFX placed
    templates_by_det = [templates[d["key"]]["audio"] for d in dets]
    sfx_cols = [place(templates[d["key"]]["audio"], d["sample"] / sr, 1.0, n, sr) for d in dets]
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
        if b_info.get("section_start_obs") is not None and aud and not b_info.get("loop"):
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
    try:
        out["originals"]["levels"] = kept_levels_obs(ctx, orig_rows, (out.get("loudness") or {}).get("integrated_lufs"))
    except Exception as e:
        out["errors"]["original_levels"] = f"{type(e).__name__}: {e}"
    # ---------------- the kept voice as it is in the output (mix minus fitted BGM and SFX): music left in it, speech
    try:
        ours = [k for k, nm in enumerate(names) if not nm.startswith("orig:")] + list(range(len(cols), len(all_cols)))
        voice_out = (y.astype(np.float64) - fitted_part(all_cols, Gf, ours, n, sr, FINE)).astype(np.float32) \
            if all_cols else y.copy()
        out["originals"]["voice_out"] = kept_audio_checks(ctx, voice_out, sr, bgm_al is not None)
    except Exception as e:
        voice_out = None
        out["errors"]["voice_out"] = f"{type(e).__name__}: {e}"
    # ---------------- BGM level at programme loudness, silence / ducking ramps, kept-original edge ramps
    if bgm_al is not None:
        b_info["level"] = bgm_level_obs(b_info.get("plateau_gain_db"), res.audio.target_lufs,
                                        (out.get("loudness") or {}).get("integrated_lufs"))
        try:
            others = [k for k, nm in enumerate(names) if nm.startswith("orig:")] + list(range(len(cols), len(all_cols)))
            bgm_sig = (y.astype(np.float64) - fitted_part(all_cols, Gf, others, n, sr, FINE)).astype(np.float32)
            sp_out = ((out["originals"].get("voice_out") or {}).get("speech") or {})
            b_info["ramps"] = bgm_ramps(ctx, bgm_sig, bgm_al, sr,
                                        sp_out.get("spans") if sp_out.get("status") == "measured" else None)
            if sp_out.get("status") != "measured":
                b_info["ramps"]["ducking_speech_note"] = "출력 말소리를 재지 못함: " + str(sp_out.get("reason") or "")
        except Exception as e:
            out["errors"]["bgm_ramps"] = f"{type(e).__name__}: {e}"
    if voice_out is not None and res.audio.originals:
        try:
            out["originals"]["ramps"] = original_ramps(ctx, voice_out, sr)
        except Exception as e:
            out["errors"]["original_ramps"] = f"{type(e).__name__}: {e}"
    # ---------------- SFX gains relative to the BGM heard at the same moment
    env = _planned_bgm_env(ctx)
    y_lp = lowpass(y, sr) if dets else y
    cols_lp = [lowpass(c, sr) for c in cols] if dets else cols
    for i, d in enumerate(dets):
        jg = sfx_joint_gain(y_lp, d["sample"] / sr, lowpass(templates_by_det[i], sr), cols_lp, sr)
        if jg is not None:
            d["gain"] = jg
            d["gain_db_file"] = rnd(20 * math.log10(max(1e-9, abs(jg))), 2)
            d["gain_method"] = "joint LS over the SFX span"
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
        cdb = sfx_contrib_db(y, d["sample"], templates_by_det[i], d["gain"])
        d["contrib_db_rel_mix"] = rnd(cdb, 1)
        d.pop("key", None)
    subaudible = [d for d in dets if d.get("contrib_db_rel_mix") is not None and d["contrib_db_rel_mix"] < SFX_MIN_CONTRIB_DB]
    for d in subaudible:
        d["why_dropped"] = f"믹스 대비 {d['contrib_db_rel_mix']} dB < {SFX_MIN_CONTRIB_DB:g} dB: 가려져 들리지 않는 잔차 일치(배치된 소리 아님)"
    dets = [d for d in dets if d not in subaudible]
    try:
        cls_sum = classify_sfx_detections(ctx, dets)
    except Exception as e:  # a failed classification leaves the types unmeasured, never the plan's labels
        cls_sum = {"status": "unmeasured", "reason": f"{type(e).__name__}: {e}"[:200]}
        for d in dets:
            d["catalog_type"] = {"status": "unmeasured", "type_id": None, "reason": cls_sum["reason"]}
    out["sfx"] = {"detections": dets, "threshold_ncc": 0.45, "min_contrib_db_rel_mix": SFX_MIN_CONTRIB_DB,
                  "subaudible_matches": subaudible, "catalog_classification": cls_sum}
    # ---------------- unexplained onsets in the final residual
    exclude = [(d["t"] - 0.05, d["t"] + d["len"] + 0.05) for d in dets] + [(a - 0.1, b + 0.1) for a, b in kept]
    # fast gain changes of the BGM itself (edges of measured ducks/silences, planned envelope steps,
    # fades) leave fit error there, not a new sound.  (Not "wherever the fitted gain jumps": an
    # unknown sound itself perturbs the fitted gain and would hide itself.)
    if bgm_al is not None:
        edges = []
        for a, b in (b_info.get("ducked_ranges_obs") or []) + (b_info.get("silent_ranges_obs") or []):
            edges += [a, b]
        if bgm is not None:
            for a, b in list(bgm.duck_ranges or []) + list(bgm.silences or []):
                edges += [float(a), float(b)]
            pts = [(float(t), float(v)) for t, v in (bgm.envelope or [])]
            for (t0, v0), (t1, v1) in zip(pts, pts[1:]):
                if abs(v1 - v0) >= 3.0:
                    edges += [t0, t1]
            edges += [float(bgm.fade_in_s or 0), T - float(bgm.fade_out_s or 0)]
        exclude += [(e - 0.12, e + 0.12) for e in edges]
    try:
        out["unexplained_onsets"] = unexplained_onsets(r2, y, sr, exclude, model=(y - r2).astype(np.float32))
    except Exception as e:
        out["errors"]["onsets"] = f"{type(e).__name__}: {e}"
    out["residual_rms_db_rel_mix"] = rnd(10 * math.log10(float((r2.astype(np.float64) ** 2).mean()) + 1e-12)
                                         - 10 * math.log10(float((y.astype(np.float64) ** 2).mean()) + 1e-12), 2)
    out["status"] = "measured"
    return out
