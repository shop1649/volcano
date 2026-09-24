"""SFX event extraction from a reference video's audio.

    residual = mix - vocals stem - g(t) * aligned clean BGM          (waveform mode)
    residual = spectral subtraction of g(t)*|aligned clean| from (mix - vocals)   (spectral mode)

``g(t)`` is the per-window least-squares BGM gain; it is estimated twice: the second pass
interpolates the gain across the first pass's event intervals so that the SFX themselves do not
bias the BGM gain.  Events are segmented on the residual (log-mel spectral flux + energy with
onset back-tracking on a 5 ms envelope) and must also be present in the ORIGINAL MIX: a
separation/subtraction artifact is rejected when (a) the event's share of the mix energy in its
own bands is too small, (b) the mix shows no energy rise at the onset, or (c) the residual
waveform is mostly a copy of the BGM or of the vocals stem.  Rejected candidates are kept in
``rejected`` with the reason.  Events under speech/BGM are kept (the residual has them removed).

Fingerprints: 64-band log-mel patch (onset-20 ms .. +0.5 s, hop 256) saved as ``sfx_fp/eNNN.npy``,
a <= 1 s residual waveform snippet ``sfx_fp/eNNN_wave.npy`` (for the edit-vs-onsite waveform
test) and summary statistics in the JSON.

Output: ``analysis/<id>/audio/sfx_events.json`` (``type_id``/``class`` are filled by the catalog).
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from .. import paths
from ..util.jsonio import now_iso, read_json, write_json
from .audio_bgm import BgmModel, _runs, gain_curve_waveform
from .separation import (SR, Stems, audio_dir, frame_rms_db, istft, logmel, rel_or_none, stft)

SCHEMA = "shortkit.audio_sfx_events/1"
EV_NFFT, EV_HOP, EV_MELS = 1024, 128, 64
FP_NFFT, FP_HOP, FP_MELS = 1024, 256, 64
FP_PRE_S, FP_LEN_S, WAVE_MAX_S = 0.02, 0.5, 0.4   # wave snippet = what the edit-vs-onsite xcorr uses
DETECT_ABOVE_FLOOR_DB = 15.0
SPLIT_ONSET_DB = 9.0
MIN_EVENT_S = 0.02
MAX_EVENT_S = 3.0
MIX_SHARE_MIN = 0.2          # event energy / mix energy in the event's bands
MIX_RISE_MIN_DB = 1.0        # mix band energy rise at the onset (required unless the event dominates its bands)
MIX_SHARE_DOMINANT = 0.5     # share at/above which the event is plainly in the mix (e.g. SFX under speech)
ARTIFACT_CORR_MAX = 0.5      # |corr(residual, bgm or vocals)| above this = copy of a known stem
SUB_NFFT, SUB_HOP, SUB_OVER, SUB_FLOOR = 512, 128, 1.5, 0.03   # spectral-mode subtraction


# ============================================================================ residual
def _gain_excluding(bgm_sig: np.ndarray, model: BgmModel, sr: int, events: list[dict]) -> np.ndarray:
    """Per-sample BGM gain; inside event intervals it is interpolated from the neighbours."""
    t, g, on = gain_curve_waveform(bgm_sig, model.aligned, sr)
    bad = np.zeros(len(t), bool)
    for e in events:
        bad |= (t >= e["t"] - 0.06) & (t <= e["t"] + e["dur"] + 0.06)
    good = ~bad & on
    if good.sum() >= 2 and bad.any():
        g = g.copy()
        g[bad] = np.interp(t[bad], t[good], g[good])
    return np.interp(np.arange(len(bgm_sig)) / sr, t, g).astype(np.float32)


def residual_signal(ctx: dict, events_hint: list[dict] | None = None) -> tuple[np.ndarray, str, list[str]]:
    vocals, model, bgm_sig = ctx["vocals"], ctx["model"], ctx["bgm_sig"]
    sr = SR
    lim: list[str] = []
    if vocals is None:
        lim.append("보컬 stem 없음: 대사와 겹친 효과음은 분리 불가 → 대사 구간 이벤트는 'unmeasured_under_speech'")
    if model is None:                      # only reached when bgm.json says BGM is absent
        return bgm_sig.copy(), "mix - vocals (BGM 없음)" if vocals is not None else "mix (BGM 없음)", lim
    if model.mode == "waveform" and model.aligned is not None:
        g = _gain_excluding(bgm_sig, model, sr, events_hint or [])
        res = bgm_sig - g * model.aligned[:len(bgm_sig)]
        return res.astype(np.float32), ("mix - vocals - g(t)*aligned clean BGM (파형 LS)" if vocals is not None
                                        else "mix - g(t)*aligned clean BGM (파형 LS)"), lim
    # spectral mode: magnitude subtraction with the mix phase (short STFT: onsets stay sharp)
    n_fft, hop = SUB_NFFT, SUB_HOP
    S = stft(bgm_sig, n_fft, hop)
    Cm = model.aligned_mag(n_fft, hop, S.shape[0])
    # tolerate small timing jitter of stretched transients (+-3 frames)
    from scipy.ndimage import maximum_filter1d

    Cm = maximum_filter1d(Cm, size=7, axis=0)
    gt = model.gain_at(np.arange(S.shape[0]) * hop / sr)
    M = np.abs(S)
    R = np.maximum(M - SUB_OVER * gt[:, None] * Cm, SUB_FLOOR * M)
    S2 = R * np.exp(1j * np.angle(S))
    lim.append("레퍼런스가 BGM 속도를 바꿈 → 스펙트럼 차감(근사, n_fft %d): BGM 파형 복사 검사 불가, "
               "짧은 저역 BGM 잔재가 이벤트로 남을 수 있음(믹스 몫·상승 검사만 적용)" % n_fft)
    return istft(S2, n_fft, hop, len(bgm_sig)), f"spectral subtraction (n_fft {n_fft}, mix phase)", lim


# ============================================================================ detection
def _short_env_db(x: np.ndarray, sr: int, win_s: float = 0.005, hop_s: float = 0.0025) -> tuple[np.ndarray, np.ndarray]:
    return frame_rms_db(x, sr, win_s, hop_s)


def detect_events(res: np.ndarray, sr: int = SR) -> tuple[list[dict], dict]:
    """Onset/event segmentation on the residual. Returns (events, detector info)."""
    L = logmel(res, sr, EV_NFFT, EV_HOP, EV_MELS).astype(np.float64)
    E = 10 * np.log10(np.sum(10 ** (L / 10), axis=1) + 1e-12)
    hop_s = EV_HOP / sr
    t = np.arange(len(E)) * hop_s
    floor = max(float(np.percentile(E, 20)), -100.0)
    thr = floor + DETECT_ABOVE_FLOOR_DB
    active = E > thr
    # fill tiny gaps (30 ms)
    runs = _runs(active)
    merged: list[list[int]] = []
    for a, b in runs:
        if merged and (a - merged[-1][1]) * hop_s <= 0.03:
            merged[-1][1] = b
        else:
            merged.append([a, b])
    # onset strength: mean of the top-25% band rises (dB) over 3 frames, on a floored spectrogram
    Lf = np.maximum(L, thr - 10 - 10 * np.log10(EV_MELS))
    rise = np.zeros_like(Lf)
    rise[4:] = np.maximum(0.0, Lf[4:] - np.maximum(Lf[1:-3], Lf[:-4]))
    k = max(1, EV_MELS // 4)
    strength = np.sort(rise, axis=1)[:, -k:].mean(axis=1)
    et, env = _short_env_db(res, sr)
    ev_floor = max(float(np.percentile(env, 20)), -100.0)
    events = []
    for a, b in merged:
        if (b - a) * hop_s < MIN_EVENT_S:
            continue
        starts = [a]
        # split at strong onsets inside the run
        i = a + 3
        while i < b - 2:
            if strength[i] >= SPLIT_ONSET_DB and strength[i] == strength[max(a, i - 6):i + 7].max() \
                    and (i - starts[-1]) * hop_s >= 0.08 and E[min(b - 1, i + 3)] >= E[max(a, i - 3)] - 1.0:
                starts.append(i)
                i += int(0.08 / hop_s)
            else:
                i += 1
        for j, s in enumerate(starts):
            e_end = starts[j + 1] if j + 1 < len(starts) else b
            t_coarse = float(t[s])
            # back-track the onset on the 5 ms envelope: walk back from the detection point to the
            # last sample under the onset level (the rise that belongs to THIS event only)
            hi = t_coarse + 0.04 if j == 0 else float(t[min(e_end - 1, s + int(0.04 / hop_s))])
            win = np.nonzero((et >= t_coarse - 0.15) & (et <= hi))[0]
            if not len(win):
                continue
            if j == 0:
                pre = (et >= t_coarse - 0.2) & (et < t_coarse - 0.09)
                base = float(np.median(env[pre])) if pre.any() else ev_floor
                near = win[et[win] >= t_coarse - 0.01]
                seg_peak = float(env[near].max()) if len(near) else float(env[win].max())
                level = max(ev_floor + 6.0, base + 6.0, seg_peak - 40.0)
                ic = int(near[np.argmax(env[near])]) if len(near) else int(win[-1])
                i = ic
                imin = ic
                while i > win[0] and env[i - 1] > level:
                    i -= 1
                    if env[i] < env[imin]:
                        imin = i
                    elif env[i] > env[imin] + 6.0:     # climbing into an earlier sound: stop at the valley
                        i = imin
                        break
                onset = float(et[i]) - 0.0025
            else:
                # a new sound over a tail: first point of the steepest envelope rise
                idx = win[et[win] >= t_coarse - 0.03]
                d = np.diff(env[idx], prepend=env[idx][0])
                onset = float(et[idx[int(np.argmax(d))]]) - 0.0025
            # end: energy falls 35 dB under the event peak (or floor+6), or next event start
            t_stop = float(t[e_end - 1] + hop_s) if e_end > s else onset + MIN_EVENT_S
            mm = (et >= onset) & (et <= t_stop)
            ii = np.nonzero(mm)[0]
            if not len(ii):
                continue
            pk = float(env[ii].max())
            lvl_end = max(ev_floor + 6.0, pk - 35.0)
            last = ii[env[ii] > lvl_end]
            end = float(et[last[-1]] + 0.0025) if len(last) else t_stop
            end = min(end, t_stop, onset + MAX_EVENT_S)
            if end - onset < MIN_EVENT_S:
                continue
            events.append({"t": round(max(0.0, onset), 4), "dur": round(end - onset, 4),
                           "peak_dbfs": round(pk, 2), "onset_strength_db": round(float(strength[s]), 2)})
    # de-duplicate onsets closer than 60 ms
    events.sort(key=lambda e: e["t"])
    out: list[dict] = []
    for e in events:
        if out and e["t"] - out[-1]["t"] < 0.06:
            if e["peak_dbfs"] > out[-1]["peak_dbfs"]:
                out[-1]["peak_dbfs"] = e["peak_dbfs"]
            out[-1]["dur"] = round(max(out[-1]["dur"], e["t"] + e["dur"] - out[-1]["t"]), 4)
            continue
        out.append(e)
    info = {"floor_db": round(floor, 1), "threshold_db": round(thr, 1), "env_floor_db": round(ev_floor, 1),
            "method": f"log-mel {EV_MELS} (n_fft {EV_NFFT}, hop {EV_HOP}) 에너지 > 바닥+{DETECT_ABOVE_FLOOR_DB} dB 구간, "
                      f"상위 25 % 대역 상승 >= {SPLIT_ONSET_DB} dB 에서 분할, 5 ms 포락선으로 시작점 역추적"}
    return out, info


# ============================================================================ mix contrast
def _corr(a: np.ndarray, b: np.ndarray) -> float:
    na, nb = float(np.linalg.norm(a)), float(np.linalg.norm(b))
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def _local_abs_corr(a: np.ndarray, b: np.ndarray, sr: int, win_s: float = 0.02) -> float:
    """Energy-weighted mean over short sub-windows of |corr(a, b)|.

    Catches residue that is a (time-varying) scaled copy of a known stem, e.g. a BGM gain step
    that the smoothed gain curve did not follow, whose sign flips inside the event window."""
    w = max(16, int(win_s * sr))
    n = min(len(a), len(b)) // w
    if n == 0:
        return abs(_corr(a, b))
    A = a[:n * w].reshape(n, w).astype(np.float64)
    B = b[:n * w].reshape(n, w).astype(np.float64)
    na, nb = np.linalg.norm(A, axis=1), np.linalg.norm(B, axis=1)
    ok = (na > 1e-9) & (nb > 1e-9)
    if not ok.any():
        return 0.0
    c = np.abs((A[ok] * B[ok]).sum(1)) / (na[ok] * nb[ok])
    wts = na[ok] ** 2
    return float((c * wts).sum() / wts.sum())


def mix_check(ev: dict, res: np.ndarray, mix: np.ndarray, sr: int, bgm_est: np.ndarray | None,
              vocals: np.ndarray | None) -> dict:
    t0 = ev["t"]
    t1 = t0 + max(ev["dur"], 0.03)
    a, b = int(t0 * sr), min(len(mix), int(min(t1, t0 + 0.5) * sr))
    pa, pb = max(0, int((t0 - 0.25) * sr)), max(0, int((t0 - 0.03) * sr))
    seg_r, seg_m = res[a:b], mix[a:b]
    if len(seg_r) < 64:
        return {"passed": False, "reason": "too_short"}
    nfft = 1 << int(np.ceil(np.log2(max(len(seg_r), 256))))
    Rr = np.abs(np.fft.rfft(seg_r * np.hanning(len(seg_r)), nfft)) ** 2
    Rm = np.abs(np.fft.rfft(seg_m * np.hanning(len(seg_m)), nfft)) ** 2
    freqs = np.fft.rfftfreq(nfft, 1 / sr)
    # the event's own bands: 1/3-octave-ish bins where the residual is within 10 dB of its max
    edges = np.geomspace(50, sr / 2, 25)
    band_r = np.array([Rr[(freqs >= lo) & (freqs < hi)].sum() for lo, hi in zip(edges[:-1], edges[1:])])
    band_m = np.array([Rm[(freqs >= lo) & (freqs < hi)].sum() for lo, hi in zip(edges[:-1], edges[1:])])
    sel = band_r >= band_r.max() * 0.1
    share = float(band_r[sel].sum() / max(band_m[sel].sum(), 1e-20))
    # mix energy rise at the onset in those bands
    rise_db = None
    if pb - pa >= 64:
        pre = mix[pa:pb]
        Rp = np.abs(np.fft.rfft(pre * np.hanning(len(pre)), nfft)) ** 2 * (len(seg_m) / len(pre))
        band_p = np.array([Rp[(freqs >= lo) & (freqs < hi)].sum() for lo, hi in zip(edges[:-1], edges[1:])])
        rise_db = float(10 * np.log10(max(band_m[sel].sum(), 1e-20) / max(band_p[sel].sum(), 1e-20)))
    lo_hz = float(edges[:-1][sel].min()) if sel.any() else None
    hi_hz = float(edges[1:][sel].max()) if sel.any() else None
    # waveform-copy test needs the aligned BGM waveform (waveform mode); in spectral mode (re-timed
    # BGM) no reliable copy test exists -> only the mix share / mix rise checks apply (limitation).
    c_bgm = _local_abs_corr(seg_r, bgm_est[a:b], sr) if bgm_est is not None else None
    c_voc = _local_abs_corr(seg_r, vocals[a:b], sr) if vocals is not None else None
    reasons = []
    if share < MIX_SHARE_MIN:
        reasons.append(f"mix_share {share:.2f} < {MIX_SHARE_MIN}")
    if rise_db is not None and rise_db < MIX_RISE_MIN_DB and share < MIX_SHARE_DOMINANT:
        reasons.append(f"mix_rise {rise_db:.1f} dB < {MIX_RISE_MIN_DB}")
    if c_bgm is not None and abs(c_bgm) > ARTIFACT_CORR_MAX:
        reasons.append(f"copy_of_bgm |corr| {abs(c_bgm):.2f}")
    if c_voc is not None and abs(c_voc) > ARTIFACT_CORR_MAX:
        reasons.append(f"copy_of_vocals |corr| {abs(c_voc):.2f}")
    return {"passed": not reasons, "reasons": reasons, "mix_share": round(share, 3),
            "mix_rise_db": None if rise_db is None else round(rise_db, 2),
            "corr_bgm": None if c_bgm is None else round(c_bgm, 3),
            "corr_vocals": None if c_voc is None else round(c_voc, 3),
            "band_hz": [None if lo_hz is None else round(lo_hz), None if hi_hz is None else round(hi_hz)]}


# ============================================================================ fingerprints
def fingerprint_clip(x: np.ndarray, sr: int = SR, onset_s: float = 0.0, dur_s: float | None = None) -> dict:
    """Log-mel patch [FP_MELS, frames] (dB, relative to its max, floored at -80), waveform snippet, stats."""
    a = int(round((onset_s - FP_PRE_S) * sr))
    n = int(round((FP_PRE_S + FP_LEN_S) * sr))
    seg = np.zeros(n, np.float32)
    s0, s1 = max(0, a), min(len(x), a + n)
    if s1 > s0:
        seg[s0 - a:s1 - a] = x[s0:s1]
    L = logmel(seg, sr, FP_NFFT, FP_HOP, FP_MELS).T.astype(np.float32)     # [mels, frames]
    L = np.maximum(L - L.max(), -80.0)
    dur = dur_s if dur_s is not None else _auto_duration(x, sr, onset_s)
    w0 = max(0, int(round(onset_s * sr)))
    wave = np.asarray(x[w0:w0 + int(min(max(dur, 0.02), WAVE_MAX_S) * sr)], np.float32)
    return {"patch": L, "wave": wave, "stats": clip_stats(wave, sr, dur)}


def _auto_duration(x: np.ndarray, sr: int, onset_s: float) -> float:
    seg = x[int(onset_s * sr):int((onset_s + MAX_EVENT_S) * sr)]
    if len(seg) < 64:
        return len(seg) / sr
    t, env = _short_env_db(seg, sr)
    pk = float(env.max())
    above = np.nonzero(env > pk - 35.0)[0]
    return float(t[above[-1]] + 0.0025) if len(above) else len(seg) / sr


def clip_stats(wave: np.ndarray, sr: int, dur: float) -> dict:
    if len(wave) < 32:
        return {"dur_s": round(dur, 4)}
    P = np.abs(np.fft.rfft(wave * np.hanning(len(wave)))) ** 2
    f = np.fft.rfftfreq(len(wave), 1 / sr)
    tot = P.sum() + 1e-20
    cen = float((f * P).sum() / tot)
    bw = float(np.sqrt(((f - cen) ** 2 * P).sum() / tot))
    flat = float(np.exp(np.mean(np.log(P + 1e-20))) / (np.mean(P) + 1e-20))
    t, env = _short_env_db(wave, sr)
    ipk = int(np.argmax(env))
    after = np.nonzero(env[ipk:] < env[ipk] - 20)[0]
    return {"dur_s": round(dur, 4), "peak_dbfs": round(float(env.max()), 2),
            "rms_dbfs": round(float(20 * np.log10(np.sqrt(np.mean(wave ** 2)) + 1e-9)), 2),
            "centroid_hz": round(cen, 1), "bandwidth_hz": round(bw, 1), "flatness": round(flat, 4),
            "attack_s": round(float(t[ipk]), 4),
            "decay20_s": round(float(t[after[0]]) if len(after) else float(t[-1] - t[ipk]), 4)}


def patch_matrix(patches: list[np.ndarray], shift: int = 0, mode: str = "shape") -> np.ndarray:
    """Normalised feature rows for cosine similarity; ``shift`` moves the patch in time (frames)."""
    rows = []
    for p in patches:
        q = p + 80.0                                      # 0 .. 80 dB above the floor
        if shift:
            q = np.roll(q, shift, axis=1)
            if shift > 0:
                q[:, :shift] = 0.0
            else:
                q[:, shift:] = 0.0
        if mode == "dyn":                                 # per-band mean removed: EQ-invariant
            q = q - q.mean(axis=1, keepdims=True)
        else:                                             # per-patch mean removed: gain-invariant
            q = q - q.mean()
        v = q.ravel().astype(np.float64)
        rows.append(v / (np.linalg.norm(v) + 1e-12))
    return np.array(rows) if rows else np.zeros((0, 1))


def similarity_matrix(pa: list[np.ndarray], pb: list[np.ndarray] | None = None, max_shift: int = 3) -> np.ndarray:
    """Fingerprint similarity (0..1-ish): max over +-max_shift frame shifts of the mean of the
    gain-invariant and EQ-invariant patch cosines."""
    pb = pa if pb is None else pb
    if not pa or not pb:
        return np.zeros((len(pa), len(pb)))
    A_s, A_d = patch_matrix(pa, 0, "shape"), patch_matrix(pa, 0, "dyn")
    best = np.full((len(pa), len(pb)), -1.0)
    for s in range(-max_shift, max_shift + 1):
        B_s, B_d = patch_matrix(pb, s, "shape"), patch_matrix(pb, s, "dyn")
        best = np.maximum(best, 0.5 * (A_s @ B_s.T + A_d @ B_d.T))
    return best


def wave_xcorr(a: np.ndarray, b: np.ndarray, max_lag_s: float = 0.05, sr: int = SR) -> float:
    """Max normalised cross-correlation of two snippets (both start at their onset)."""
    n = min(len(a), len(b))
    if n < 64:
        return 0.0
    a, b = a[:n].astype(np.float64), b[:n].astype(np.float64)
    L = int(max_lag_s * sr)
    nfft = 1 << int(np.ceil(np.log2(2 * n)))
    c = np.fft.irfft(np.fft.rfft(a, nfft) * np.conj(np.fft.rfft(b, nfft)), nfft)
    lags = np.concatenate([c[:L + 1], c[-L:]]) if L > 0 else c[:1]
    den = np.linalg.norm(a) * np.linalg.norm(b) + 1e-12
    return float(np.max(np.abs(lags)) / den)


# ============================================================================ per video
def sfx_events_path(preset_name: str, video_id: str) -> Path:
    return audio_dir(preset_name, video_id) / "sfx_events.json"


def fp_dir(preset_name: str, video_id: str) -> Path:
    return audio_dir(preset_name, video_id) / "sfx_fp"


def analyze_sfx_events(preset_name: str, video_id: str, audio_path: str | os.PathLike | None = None,
                       stems: Stems | None = None, write: bool = True, ctx: dict | None = None) -> dict:
    from .audio_original import load_context, original_path

    ctx = ctx or load_context(preset_name, video_id, audio_path, stems)
    out: dict = {"schema": SCHEMA, "video_id": video_id, "analyzed_at": now_iso()}
    if ctx.get("src") is None:
        out.update({"status": "unmeasured", "blocker": f"레퍼런스 원본 파일 없음(video_id={video_id})", "events": [],
                    "rejected": []})
        if write:
            write_json(sfx_events_path(preset_name, video_id), out)
        return out
    sr = SR
    mix, vocals, model = ctx["mix"], ctx["vocals"], ctx["model"]
    st = ctx.get("stems")
    out["audio_file"] = rel_or_none(ctx["src"])
    out["separator"] = ({"status": "measured", "model": st.model, "model_version": st.model_version}
                        if st is not None else {"status": "unmeasured",
                                                "blocker": (read_json(audio_dir(preset_name, video_id) /
                                                                      "separation.json") or {}).get("blocker")
                                                or "분리 실행 기록 없음"})
    bgm_rec = ctx.get("bgm_rec") or {}
    out["bgm"] = {"mode": model.mode if model is not None else None, "status": bgm_rec.get("status", "unmeasured"),
                  "presence": bgm_rec.get("presence", "unmeasured")}
    if model is None and bgm_rec.get("presence") != "absent":
        # music may be in the mix but it is not identified/aligned: music onsets cannot be told apart
        # from SFX -> do not report events (no guessing)
        out.update({"status": "unmeasured", "events": [], "rejected": [],
                    "blocker": ("BGM 미식별(또는 bgm.json 없음) — 음악 속 효과음을 음악과 구분할 수 없음: "
                                + str(bgm_rec.get("blocker") or "`shortkit ref bgm-identify` 먼저"))})
        if write:
            write_json(sfx_events_path(preset_name, video_id), out)
        return out
    orig0 = read_json(original_path(preset_name, video_id)) or {}
    if vocals is None and (orig0.get("speech") or {}).get("presence") not in ("present", "absent"):
        # without a vocals stem the speech segments are the only way to keep syllables out of the events
        out.update({"status": "unmeasured", "events": [], "rejected": [],
                    "blocker": "보컬 stem 없음 + 대사 구간 못 잼(original.json) — 대사와 효과음을 구분할 수 없음"})
        if write:
            write_json(sfx_events_path(preset_name, video_id), out)
        return out
    # pass 1 / pass 2 (gain re-estimated without the events)
    res, method, lim = residual_signal(ctx)
    ev1, _ = detect_events(res, sr)
    if model is not None and model.mode == "waveform":
        res, method, lim = residual_signal(ctx, ev1)
    cands, info = detect_events(res, sr)
    bgm_est = None
    if model is not None and model.aligned is not None:
        bgm_est = model.gain_samples(len(mix)) * model.aligned[:len(mix)]
    orig = orig0
    speech = ((orig.get("speech") or {}).get("segments")) or []
    speech_status = (orig.get("speech") or {}).get("presence", "unmeasured")
    # heuristic (no-stem) speech segments have loose edges: widen them for the under-speech test
    sp_pad = 0.3 if (orig.get("speech") or {}).get("confidence") == "low" else 0.0
    mix_rms = float(np.sqrt(np.mean(mix ** 2)) + 1e-12)
    fdir = fp_dir(preset_name, video_id)
    if write and fdir.is_dir():
        for old in fdir.glob("e*.npy"):
            old.unlink()
    events, rejected = [], []
    for e in cands:
        chk = mix_check(e, res, mix, sr, bgm_est, vocals)
        e_end = e["t"] + e["dur"]
        under_speech = any(s["start"] - sp_pad < e_end and s["end"] + sp_pad > e["t"] for s in speech)
        under_bgm = bool(model is not None and float(model.gain_at(e["t"] + 0.01)) > 1e-3)
        rec = dict(e)
        rec.update({"under_speech": under_speech, "under_bgm": under_bgm, "mix_check": chk})
        if not chk["passed"]:
            rejected.append(rec | {"reason": "; ".join(chk.get("reasons") or [chk.get("reason", "")])})
            continue
        if vocals is None and under_speech:
            rejected.append(rec | {"reason": "unmeasured_under_speech (보컬 stem 없음)"})
            continue
        events.append(rec)
    for i, e in enumerate(events):
        eid = f"e{i:03d}"
        fp = fingerprint_clip(res, sr, e["t"], e["dur"])
        seg = res[int(e["t"] * sr):int((e["t"] + min(e["dur"], 0.5)) * sr)]
        e_rms = float(np.sqrt(np.mean(seg ** 2))) if len(seg) else 0.0
        e.update({"id": eid, "type_id": None, "class": None,
                  "gain_db": round(20 * np.log10(max(e_rms, 1e-9) / mix_rms), 2),
                  "stats": fp["stats"]})
        if write:
            fdir.mkdir(parents=True, exist_ok=True)
            np.save(fdir / f"{eid}.npy", fp["patch"].astype(np.float16))
            np.save(fdir / f"{eid}_wave.npy", fp["wave"].astype(np.float16))
        e["fp"] = paths.relp(fdir / f"{eid}.npy") if write else None
        e["wave"] = paths.relp(fdir / f"{eid}_wave.npy") if write else None
        e["band_hz"] = e["mix_check"].get("band_hz")
    # intentional silences from original.json: mix below the floor AND BGM cut -> an event of class
    # intentional_silence (fp null); silences without a confirmed BGM cut are listed separately.
    sil_other = []
    for s in ((orig.get("silences") or {}).get("items") or []):
        rec = {"t": s["start"], "dur": s["dur"], "type_id": None, "gain_db": s.get("mix_db"), "fp": None,
               "bgm_cut": s.get("bgm_cut")}
        if s.get("bgm_cut") is True:
            events.append(rec | {"id": f"s{sum(1 for e in events if e.get('class') == 'intentional_silence'):03d}",
                                 "class": "intentional_silence"})
        else:
            sil_other.append(rec | {"class": None, "note": "BGM 끊김 확인 안 됨(bgm_cut=%s)" % s.get("bgm_cut")})
    events.sort(key=lambda e: e["t"])
    n_unm = sum(1 for r in rejected if str(r.get("reason", "")).startswith("unmeasured_under_speech"))
    out["unmeasured_coverage"] = ({"intervals": [[max(0.0, x["start"] - sp_pad), x["end"] + sp_pad] for x in speech],
                                   "n_candidates": n_unm,
                                   "note": "보컬 stem 없음 → 이 구간의 효과음은 못 잼(개수는 하한값)"}
                                  if vocals is None and speech else None)
    out.update({"status": "measured", "blocker": None, "residual_method": method, "limitations": lim,
                "detector": info, "speech_status": speech_status,
                "mix_check_rule": {"mix_share_min": MIX_SHARE_MIN, "mix_rise_min_db": MIX_RISE_MIN_DB,
                                   "mix_share_dominant": MIX_SHARE_DOMINANT, "artifact_corr_max": ARTIFACT_CORR_MAX,
                                   "rule": "믹스 안 같은 대역에서 이벤트 몫 >= min AND (몫 >= dominant OR 시작점에서 믹스 "
                                           "상승 >= rise) AND 잔여가 BGM/보컬 stem 의 복사본이 아님(20 ms 구간 |상관|)"},
                "fingerprint": {"method": f"log-mel {FP_MELS} bands, n_fft {FP_NFFT}, hop {FP_HOP}, "
                                          f"onset-{FP_PRE_S}s..+{FP_LEN_S}s, dB re max floored -80 (float16); "
                                          f"residual waveform <= {WAVE_MAX_S}s (float16)"},
                "gain_db_ref": "이벤트 RMS(최대 0.5 s) / 믹스 전체 RMS (dB)",
                "events": events, "silences_unclassified": sil_other, "rejected": rejected})
    if write:
        write_json(sfx_events_path(preset_name, video_id), out)
    return out
