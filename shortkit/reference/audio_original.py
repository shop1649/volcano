"""Original sound (speech / on-site audio) presence and BGM ducking in a reference video.

Inputs per video: the mix, the vocals stem when separation ran (else the mix with the known,
aligned clean BGM removed), and the BGM model from ``bgm.json`` (aligned clean file + gain
curve).  Output: ``analysis/<id>/audio/original.json``.

Ducking is measured only from the BGM gain curve around speech segments:
    depth_db   = median gain before speech  - median gain inside speech
    attack_s   = (t90 - t10) / 0.8 of the downward ramp  (linear-in-dB ramp model, the same shape as
                 ``ResolvedEdit.audio.bgm.envelope``); release_s likewise for the upward ramp.
    lead_s     = ramp start - speech onset (negative: BGM dips before the voice starts)
Presence: present if median depth >= 2 dB, absent if speech segments with BGM around them exist
but depth < 2 dB, unmeasured otherwise (no BGM identified, or no speech segment measurable).

Also here: intentional silences (mix below a floor for >= 0.3 s mid-video, with BGM cut) and the BGM
ramps into/out of them, the on/off edge ramps of the original (non-BGM) sound, the loudness of the
kept speech relative to the programme, BGM dips not explained by speech (evidence for "SFX/cuts are
never a reason to duck"), per-video EBU R128 loudness (``audio/loudness.json``) and the preset
aggregation ``measurements/audio.json`` (``aggregate_measurements``).

Ramp durations are reported in the RENDERER's units (``shortkit.edit``): a ramp is read as the time
between two level crossings (hi_db/lo_db under the plateau) and converted with a table computed by
running the same measurement (same window) on the renderer's own ramp shape -- dB-linear 0 -> -120 dB
for intentional silences (``edit.audio.build_envelope``), linear amplitude for kept original sound
(``edit.render._lin_fade``).  Measurement blur of the window is therefore part of the model, not a bias.
"""
from __future__ import annotations

import os
import tempfile
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..util.jsonio import now_iso, read_json, write_json
from ..util.stats import pstats
from .audio_bgm import BgmModel, _runs, describe_gain, load_bgm_model
from .separation import (SR, Stems, audio_dir, find_reference_media, frame_rms_db, frame_signal, load_cached_stems,
                         load_mono, rel_or_none)

SCHEMA = "shortkit.audio_original/1"
DUCK_PRESENT_DB = 2.0
SPEECH_GAP_FILL_S = 0.35
SPEECH_MIN_S = 0.15
SILENCE_MIN_S = 0.3
SILENCE_EDGE_S = 0.3
SILENCE_ABS_FLOOR_DB = -60.0
SILENCE_REL_DB = 40.0
# ramp measurements (see module docstring)
SIL_RAMP_WIN_S, SIL_RAMP_HOP_S = 0.003, 0.0005       # fine LS BGM gain around silence edges (waveform mode)
SIL_RAMP_LO_DB, SIL_RAMP_HI_DB = -30.0, -2.0
SIL_RAMP_BASE_S = (1.2, 0.6)                          # base level window: [edge-1.2, edge-0.6] outside the silence
ORIG_RAMP_WIN_S, ORIG_RAMP_HOP_S = 0.010, 0.001      # RMS envelope of the original (non-BGM) sound
ORIG_RAMP_LO_DB, ORIG_RAMP_HI_DB = -25.0, -2.0
ORIG_RAMP_CONTRAST_DB = 30.0                          # plateau - floor needed to read the -25 dB point
ORIG_RAMP_STEADY_DB = 4.0                             # plateau p90-p10 over ORIG_RAMP_STEADY_S after the ramp
ORIG_RAMP_STEADY_S = 0.3                              # (stationary content such as room tone; speech modulates more)
EDGE_MARGIN_S = 0.5                                   # edges this close to the video start/end are not fades
KEEP_LEVEL_MIN_S = 1.0                                # speech needed for a gated loudness of the kept speech
LOUDNESS_SCHEMA = "shortkit.audio_loudness/1"


# ============================================================================ speech presence
def _mask_to_segments(t: np.ndarray, mask: np.ndarray, hop: float, gap_fill: float, min_len: float) -> list[dict]:
    segs = [[float(t[a]), float(t[b - 1] + hop)] for a, b in _runs(mask)]
    merged: list[list[float]] = []
    for s in segs:
        if merged and s[0] - merged[-1][1] <= gap_fill:
            merged[-1][1] = s[1]
        else:
            merged.append(s)
    return [{"start": round(a, 3), "end": round(b, 3)} for a, b in merged if b - a >= min_len]


def speech_segments_from_stem(vocals: np.ndarray, sr: int = SR, rel_db: float = 30.0,
                              abs_floor_db: float = -55.0) -> list[dict]:
    """Speech segments from a vocals stem: energy within `rel_db` of the stem's loud level."""
    t, lv = frame_rms_db(vocals, sr, 0.03, 0.01)
    if not len(lv) or float(np.max(lv)) < abs_floor_db:
        return []
    thr = max(abs_floor_db, float(np.percentile(lv, 99)) - rel_db)
    return _mask_to_segments(t, lv > thr, 0.01, SPEECH_GAP_FILL_S, SPEECH_MIN_S)


def voicing(x: np.ndarray, sr: int = SR, win_s: float = 0.04, hop_s: float = 0.01,
            fmin: float = 75.0, fmax: float = 400.0) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(times, pitch strength 0..1, level dBFS) by normalised autocorrelation in the pitch range."""
    from scipy.signal import butter, sosfiltfilt

    sos = butter(4, [80.0, 3500.0], btype="band", fs=sr, output="sos")
    xf = sosfiltfilt(sos, x).astype(np.float32)
    win, hop = int(win_s * sr), int(hop_s * sr)
    F = frame_signal(xf, win, hop).astype(np.float64)
    F = F - F.mean(1, keepdims=True)
    nfft = 1 << int(np.ceil(np.log2(2 * win)))
    ac = np.fft.irfft(np.abs(np.fft.rfft(F * np.hanning(win), nfft, axis=1)) ** 2, nfft, axis=1)[:, :win]
    e0 = ac[:, 0] + 1e-12
    lo, hi = int(sr / fmax), min(win - 1, int(sr / fmin))
    strength = np.clip(ac[:, lo:hi].max(axis=1) / e0, 0, 1)
    lv = 10 * np.log10(np.mean(F ** 2, axis=1) + 1e-12)
    return np.arange(len(strength)) * hop / sr, strength, lv


def speech_segments_from_residual(residual: np.ndarray, sr: int = SR) -> list[dict]:
    """Heuristic speech detector for the no-vocals-stem case (mix minus aligned BGM).

    Voiced frames (pitch strength >= 0.5 in 75-400 Hz, level within 35 dB of the loud level) grouped
    into segments; a segment counts as speech if >= 30 % of it is voiced and it shows syllable-rate
    level modulation (>= 2 dips of 6 dB per second).  Low confidence: SFX with a pitch (e.g. a
    boing) can pass.  Callers label the method."""
    t, st, lv = voicing(residual, sr)
    if not len(lv):
        return []
    thr = max(-55.0, float(np.percentile(lv, 99)) - 35.0)
    voiced = (st >= 0.5) & (lv > thr)
    cand = _mask_to_segments(t, voiced, 0.01, SPEECH_GAP_FILL_S, 0.3)
    out = []
    for s in cand:
        m = (t >= s["start"]) & (t < s["end"])
        vf = float(voiced[m].mean()) if m.any() else 0.0
        seg_lv = lv[m]
        # syllabic modulation: count local minima 6 dB under the running max
        dips = 0
        run_max = -1e9
        low = False
        for v in seg_lv:
            run_max = max(run_max * 0.98 + v * 0.02, v) if run_max > -1e8 else v
            if not low and v < run_max - 6:
                dips += 1
                low = True
            elif low and v > run_max - 3:
                low = False
        dur = s["end"] - s["start"]
        if vf >= 0.3 and dips / max(dur, 1e-6) >= 2.0:
            out.append(s | {"voiced_fraction": round(vf, 3)})
    return out


# ============================================================================ ducking
def _crossing(t: np.ndarray, y: np.ndarray, start: float, level: float, below: bool) -> float | None:
    idx = np.nonzero(t >= start)[0]
    for i in idx:
        if (y[i] <= level) if below else (y[i] >= level):
            if i > 0:
                y0, y1 = y[i - 1], y[i]
                if y1 != y0:
                    return float(t[i - 1] + (level - y0) / (y1 - y0) * (t[i] - t[i - 1]))
            return float(t[i])
    return None


def measure_ducking(model: BgmModel | None, speech: list[dict]) -> dict:
    method = ("BGM 이득 곡선(깨끗한 음원 정렬 LS, 10 ms) 에서 대사 전(-1.2~-0.25 s)·대사 중(+0.3 s~끝-0.1 s) "
              "중앙값 차 = 깊이; 10→90 % 경사 시간/0.8 = attack/release (선형 dB 경사 모델)")
    if model is None:
        return {"presence": "unmeasured", "blocker": "BGM 미식별(정렬된 깨끗한 음원 없음) → BGM 레벨 곡선 없음",
                "method": method}
    if not speech:
        return {"presence": "unmeasured", "blocker": "대사(원음) 구간 없음 — 덕킹 여부를 판정할 근거 없음",
                "method": method}
    t, g = model.t, model.gain_db
    on = model.clean_on
    all_speech = np.zeros(len(t), bool)
    for s in speech:
        all_speech |= (t >= s["start"] - 0.1) & (t <= s["end"] + 0.1)
    per = []
    for s in speech:
        s0, s1 = s["start"], s["end"]
        if s1 - s0 < 0.5:
            continue
        pre = (t >= s0 - 1.2) & (t < s0 - 0.25) & on & ~all_speech & (g > -60)
        inn = (t >= s0 + 0.3) & (t <= s1 - 0.1) & on
        post = (t >= s1 + 0.8) & (t <= s1 + 2.0) & on & ~all_speech & (g > -60)
        if pre.sum() < 5 or inn.sum() < 5:
            per.append({"start": s0, "end": s1, "status": "unmeasured",
                        "blocker": "대사 전후에 BGM 이 없어 비교 불가"})
            continue
        base = float(np.median(g[pre]))
        duck = float(np.median(g[inn]))
        depth = base - duck
        rec = {"start": s0, "end": s1, "status": "measured", "base_db": round(base, 2), "ducked_db": round(duck, 2),
               "depth_db": round(depth, 2)}
        if depth >= 3.0:
            l10, l90 = base - 0.1 * depth, base - 0.9 * depth
            t10 = _crossing(t, g, s0 - 0.6, l10, below=True)
            t90 = _crossing(t, g, t10, l90, below=True) if t10 is not None else None
            if t10 is not None and t90 is not None and t90 - t10 < 2.0:
                a = (t90 - t10) / 0.8
                rec["attack_s"] = round(a, 3)
                rec["lead_s"] = round(t10 - 0.1 * a - s0, 3)
            if post.sum() >= 5:
                base_post = float(np.median(g[post]))
                d2 = base_post - duck
                if d2 >= 3.0:
                    r10, r90 = duck + 0.1 * d2, duck + 0.9 * d2
                    u10 = _crossing(t, g, s1 - 0.3, r10, below=False)
                    u90 = _crossing(t, g, u10, r90, below=False) if u10 is not None else None
                    if u10 is not None and u90 is not None and u90 - u10 < 3.0:
                        rl = (u90 - u10) / 0.8
                        rec["release_s"] = round(rl, 3)
                        rec["release_delay_s"] = round(u10 - 0.1 * rl - s1, 3)
        per.append(rec)
    meas = [p for p in per if p["status"] == "measured"]
    if not meas:
        return {"presence": "unmeasured", "blocker": "측정 가능한 대사 구간(앞뒤에 BGM 있음, 0.5 s 이상) 없음",
                "per_segment": per, "method": method}
    depth = pstats([p["depth_db"] for p in meas])
    presence = "present" if depth["p50"] >= DUCK_PRESENT_DB else "absent"
    out = {"presence": presence, "threshold_db": DUCK_PRESENT_DB, "depth_db": depth,
           "attack_s": pstats([p.get("attack_s") for p in meas]),
           "release_s": pstats([p.get("release_s") for p in meas]),
           "lead_s": pstats([p.get("lead_s") for p in meas]),
           "release_delay_s": pstats([p.get("release_delay_s") for p in meas]),
           "per_segment": per, "method": method}
    return out


def unexplained_dips(model: BgmModel | None, speech: list[dict], cuts: list[dict], base_db: float | None) -> list[dict]:
    """BGM dips >= 3 dB for >= 0.2 s that are not under speech (+-0.5 s) and not cuts."""
    if model is None or base_db is None:
        return []
    t, g = model.t, model.gain_db
    hop = model.hop_s
    excl = np.zeros(len(t), bool)
    for s in speech:
        excl |= (t >= s["start"] - 0.5) & (t <= s["end"] + 0.5)
    for c in cuts:
        excl |= (t >= c["start"] - 0.3) & (t <= c["end"] + 0.3)
    dip = model.clean_on & (g < base_db - 3.0) & (g > base_db - 25.0) & ~excl
    return [{"start": round(float(t[a]), 3), "end": round(float(t[b - 1] + hop), 3),
             "min_db_rel_base": round(float(g[a:b].min() - base_db), 2)}
            for a, b in _runs(dip) if (b - a) * hop >= 0.2]


# ============================================================================ silences
def detect_silences(mix: np.ndarray, sr: int, model: BgmModel | None, bgm_desc: dict | None) -> list[dict]:
    """Mix below a floor for >= 0.3 s away from the edges; ``bgm_cut`` True/False/None (unknown)."""
    t, lv = frame_rms_db(mix, sr, 0.02, 0.01)
    dur = len(mix) / sr
    active = lv[lv > -80]
    if not len(active):
        return []
    floor = max(SILENCE_ABS_FLOOR_DB, float(np.median(active)) - SILENCE_REL_DB)
    out = []
    for a, b in _runs(lv < floor):
        s, e = float(t[a]), float(t[b - 1] + 0.01)
        if e - s < SILENCE_MIN_S or s < SILENCE_EDGE_S or e > dur - SILENCE_EDGE_S:
            continue
        rec = {"start": round(s, 3), "end": round(e, 3), "dur": round(e - s, 3),
               "mix_db": round(float(np.max(lv[a:b])), 1), "floor_db": round(floor, 1)}
        if model is None or not bgm_desc or not bgm_desc.get("present"):
            rec["bgm_cut"] = None
        else:
            pm = bgm_desc["present_mask"]
            tt = model.t
            inside = (tt >= s + 0.05) & (tt <= e - 0.05)
            before = (tt >= s - 2.0) & (tt < s - 0.05)
            after = (tt > e + 0.05) & (tt <= e + 2.0)
            gone = inside.any() and not pm[inside].any()
            around = bool(pm[before].any() or pm[after].any())
            rec["bgm_cut"] = bool(gone and around)
        out.append(rec)
    return out


# ============================================================================ ramps (renderer units)
def _moving_mean(x: np.ndarray, k: int) -> np.ndarray:
    """Mean over the k samples ending at each index >= k-1 (length len(x) - k + 1)."""
    c = np.concatenate([[0.0], np.cumsum(np.asarray(x, np.float64))])
    return (c[k:] - c[:-k]) / k


def _first_cross(t: np.ndarray, y: np.ndarray, level: float, start: int = 0) -> tuple[float | None, int | None]:
    """First time at index >= start where y >= level (linear interpolation; NaN samples skipped)."""
    idx = np.nonzero(np.nan_to_num(y[start:], nan=-np.inf) >= level)[0]
    if not len(idx):
        return None, None
    i = start + int(idx[0])
    j = i - 1
    while j >= 0 and np.isnan(y[j]):
        j -= 1
    if j < 0 or j < start - 1 or y[i] == y[j]:
        return float(t[i]), i
    return float(t[j] + (level - y[j]) / (y[i] - y[j]) * (t[i] - t[j])), i


def rising_span(t: np.ndarray, env_db: np.ndarray, base_db: float, lo_db: float, hi_db: float) -> dict | None:
    """Rising edge: the first crossing of base+hi_db, and before it the last crossing of base+lo_db
    (searching back from the top keeps isolated floor spikes out).  Falling edges are measured on
    time-reversed arrays.  NaN samples are unknown and skipped."""
    t_hi, i_hi = _first_cross(t, env_db, base_db + hi_db)
    if t_hi is None or not i_hi:
        return None
    lo = base_db + lo_db
    below = np.nonzero(np.nan_to_num(env_db[:i_hi], nan=np.inf) < lo)[0]
    if not len(below):
        return None
    j = int(below[-1])
    k = j + 1
    while k < i_hi and np.isnan(env_db[k]):
        k += 1
    y0, y1 = env_db[j], env_db[k]
    t_lo = float(t[k]) if y1 == y0 else float(t[j] + (lo - y0) / (y1 - y0) * (t[k] - t[j]))
    return {"t_lo": t_lo, "t_hi": t_hi, "span_s": abs(t_hi - t_lo), "i_hi": i_hi}


@lru_cache(maxsize=16)
def ramp_table(shape: str, meas: str, win_s: float, lo_db: float, hi_db: float, f_max: float = 1.0,
               f_step: float = 0.002) -> tuple[tuple[float, ...], tuple[float, ...]]:
    """(fade durations, spans) : the span the measurement reads on the renderer's ramp of each duration.

    shape 'db120'  : dB-linear -120 -> 0 dB over F, exact 0 before (edit.audio.build_envelope silences)
    shape 'lin_amp': amplitude 0 -> 1 linearly over F (edit.render._lin_fade, kept originals)
    meas  'ls'     : window mean of the amplitude (LS gain against the known clean signal)
    meas  'rms'    : window RMS (envelope of stationary content)"""
    dt = 1e-4
    k = max(1, int(round(win_s / dt)))
    Fs, spans = [], []
    for F in np.arange(0.0, f_max + 1e-9, f_step):
        pad = win_s + 0.02
        t = np.arange(-pad, F + pad, dt)
        if F <= 0:
            a = (t >= 0).astype(np.float64)
        elif shape == "db120":
            db = -120.0 * (1.0 - np.clip(t / F, 0.0, 1.0))
            a = np.where(t <= 0, 0.0, 10 ** (db / 20))
        else:
            a = np.clip(t / F, 0.0, 1.0)
        m = _moving_mean(a, k) if meas == "ls" else np.sqrt(_moving_mean(a * a, k))
        tm = t[k - 1:] - (k - 1) * dt / 2                 # window centre
        mdb = 20 * np.log10(np.maximum(m, 1e-12))
        sp = rising_span(tm, mdb, 0.0, lo_db, hi_db)
        if sp is None:
            continue
        Fs.append(round(float(F), 6))
        spans.append(float(sp["span_s"]))
    return tuple(Fs), tuple(spans)


def span_to_fade(span_s: float, table: tuple[tuple[float, ...], tuple[float, ...]]) -> float:
    """Invert a ramp table (spans are non-decreasing in F); spans at/below the F=0 reading -> 0."""
    Fs, spans = np.array(table[0]), np.maximum.accumulate(np.array(table[1]))
    if span_s <= spans[0]:
        return 0.0
    if span_s >= spans[-1]:
        return float(Fs[-1])
    return float(np.interp(span_s, spans, Fs))


def _fine_ls_gain_db(b: np.ndarray, y: np.ndarray, sr: int, t0: float, t1: float,
                     win_s: float = SIL_RAMP_WIN_S, hop_s: float = SIL_RAMP_HOP_S) -> tuple[np.ndarray, np.ndarray]:
    """Short-window least-squares gain of the known clean BGM ``y`` in ``b`` (dB, NaN where the clean
    file itself is near silent in that window)."""
    a0, a1 = max(0, int(t0 * sr)), min(len(b), len(y), int(t1 * sr))
    w = max(2, int(round(win_s * sr)))
    h = max(1, int(round(hop_s * sr)))
    if a1 - a0 <= w:
        return np.zeros(0), np.zeros(0)
    bb, yy = b[a0:a1].astype(np.float64), y[a0:a1].astype(np.float64)
    num = _moving_mean(bb * yy, w)[::h]
    den = _moving_mean(yy * yy, w)[::h]
    ok = den > max(1e-12, float(np.median(den[den > 0])) * 1e-3) if (den > 0).any() else den > 1e-12
    g = np.where(ok, np.abs(num) / np.maximum(den, 1e-20), np.nan)
    tt = (a0 + np.arange(len(num)) * h + (w - 1) / 2) / sr
    return tt, np.where(np.isnan(g), np.nan, 20 * np.log10(np.maximum(g, 1e-6)))


def measure_silence_ramps(bgm_sig: np.ndarray, model: BgmModel | None, items: list[dict], sr: int = SR) -> dict:
    """BGM ramp into / out of each intentional silence (bgm_cut True), in the renderer's
    ``audio.silence.fade_s`` units (dB-linear 0 -> -120 dB).  Waveform-aligned BGM only."""
    table = ramp_table("db120", "ls", SIL_RAMP_WIN_S, SIL_RAMP_LO_DB, SIL_RAMP_HI_DB)
    method = (f"BGM 파형 LS 이득({SIL_RAMP_WIN_S * 1000:g} ms 창) 이 정적 앞 기준 레벨(가장자리 -{SIL_RAMP_BASE_S[0]}"
              f"~-{SIL_RAMP_BASE_S[1]} s 중앙값) 대비 {SIL_RAMP_HI_DB:g} → {SIL_RAMP_LO_DB:g} dB 를 지나는 시간 → "
              "렌더러 모양(dB 선형 0→-120 dB) 에 같은 측정을 한 표로 fade_s 환산")
    if model is None or model.aligned is None:
        why = ("BGM 미식별" if model is None else "BGM 이 속도 변경(스펙트럼 정렬) — 짧은 경사를 잴 파형 정렬 없음")
        for it in items:
            if it.get("bgm_cut"):
                it["ramps"] = {"status": "unmeasured", "blocker": why}
        return {"method": method, "blocker": why}
    y = model.aligned
    dur = len(bgm_sig) / sr
    for it in items:
        if not it.get("bgm_cut"):
            continue
        rec: dict = {}
        for side, edge in (("into", float(it["start"])), ("out_of", float(it["end"]))):
            outside = -1.0 if side == "into" else 1.0
            b_lo, b_hi = sorted((edge + outside * SIL_RAMP_BASE_S[0], edge + outside * SIL_RAMP_BASE_S[1]))
            r_lo, r_hi = sorted((edge + outside * SIL_RAMP_BASE_S[1], edge - outside * 0.2))
            if b_lo < 0 or b_hi > dur:
                rec[side] = {"status": "unmeasured", "blocker": "정적 앞/뒤 기준 구간이 영상 밖"}
                continue
            tb, gb = _fine_ls_gain_db(bgm_sig, y, sr, b_lo, b_hi)
            fin = gb[np.isfinite(gb)]
            if len(fin) < 20 or float(np.median(fin)) < -60:
                rec[side] = {"status": "unmeasured", "blocker": "정적 앞/뒤에 BGM 이 없음(기준 레벨 없음)"}
                continue
            base = float(np.median(fin))
            tr, gr = _fine_ls_gain_db(bgm_sig, y, sr, r_lo, r_hi)
            if side == "into":                         # falling edge -> reversed time (rising from the silence)
                tr, gr = -tr[::-1], gr[::-1]
            sp = rising_span(tr, gr, base, SIL_RAMP_LO_DB, SIL_RAMP_HI_DB)
            if sp is None:
                rec[side] = {"status": "unmeasured", "blocker": "경사 교차점을 찾지 못함"}
                continue
            f = span_to_fade(sp["span_s"], table)
            rec[side] = {"status": "measured", "fade_s": round(f, 4), "span_s": round(sp["span_s"], 4),
                         "t": round(abs(sp["t_hi"]), 3), "base_db": round(base, 2)}
        it["ramps"] = rec
    return {"method": method, "table_resolution_s": 0.002}


def original_signal(ctx: dict) -> tuple[np.ndarray | None, str | None, str | None]:
    """(original = everything but the BGM, description, blocker): mix - aligned clean BGM estimate."""
    model, mix = ctx.get("model"), ctx["mix"]
    if model is not None and model.aligned is not None:
        return (mix - model.estimate(len(mix))).astype(np.float32), "믹스 - 정렬된 깨끗한 BGM(파형 LS)", None
    if model is None and (ctx.get("bgm_rec") or {}).get("presence") == "absent":
        return mix, "믹스(BGM 없음)", None
    return None, None, ("BGM 파형 정렬 없음(미식별 또는 속도 변경) — BGM 을 뺀 원음 신호를 만들 수 없음")


def bgm_unexplained_spans(bgm_rec: dict | None) -> list[tuple[float, float]]:
    """Time spans where the music follows another line of the clean file than the main alignment (after a
    restart/skip, and +-0.5 s around the jump): there, mix - aligned BGM still holds music.  (Windows that
    no line explains are NOT excluded: that is usually loud non-music sound -- e.g. room tone -- over
    the BGM, which the main line still removes.)"""
    lp = ((bgm_rec or {}).get("match") or {}).get("loop") or {}
    out = [(float(x["start"]), float(x["end"])) for x in lp.get("segments") or [] if x.get("label") == "other"]
    out += [(float(j["t"]) - 0.5, float(j["t"]) + 0.5) for j in lp.get("jumps") or []]
    return out


def measure_original_ramps(orig: np.ndarray, segments: list[dict], sr: int = SR,
                           exclude: list[tuple[float, float]] | None = None) -> list[dict]:
    """On/off edge ramp of the original (non-BGM) sound at each original-audio segment edge, in the
    renderer's ``audio.original.fade_s`` units (linear amplitude).  Only edges where the content right
    after the ramp is stationary (room tone, steady noise: p90-p10 <= ORIG_RAMP_STEADY_DB over
    ORIG_RAMP_STEADY_S) are
    measured; speech that starts at the edge shows its own attack, not the edit ramp."""
    table = ramp_table("lin_amp", "rms", ORIG_RAMP_WIN_S, ORIG_RAMP_LO_DB, ORIG_RAMP_HI_DB)
    w = max(2, int(round(ORIG_RAMP_WIN_S * sr)))
    h = max(1, int(round(ORIG_RAMP_HOP_S * sr)))
    x2 = orig.astype(np.float64) ** 2
    ms = _moving_mean(x2, w)[::h]
    env = 10 * np.log10(np.maximum(ms, 1e-14))
    tt = (np.arange(len(ms)) * h + (w - 1) / 2) / sr
    dur = len(orig) / sr
    out = []
    for sgm in segments:
        for kind, edge in (("on", float(sgm["start"])), ("off", float(sgm["end"]))):
            rec = {"edge": kind, "t": round(edge, 3)}
            if edge < EDGE_MARGIN_S or edge > dur - EDGE_MARGIN_S:
                out.append(rec | {"status": "skipped", "reason": "영상 시작/끝 경계(편집 페이드 아님)"})
                continue
            if any(a <= edge <= b for a, b in exclude or []):
                out.append(rec | {"status": "skipped", "reason": "BGM 이 주 정렬선으로 설명되지 않는 구간(되감김/건너뜀 등) — "
                                                                 "원음 신호에 BGM 이 남음"})
                continue
            if kind == "on":
                t, e, x0 = tt, env, edge
            else:                                          # falling edge -> time reversed
                t, e, x0 = -tt[::-1], env[::-1], -edge
            fl = (t >= x0 - 0.8) & (t < x0 - 0.4)
            reg = (t >= x0 - 0.4) & (t <= x0 + 0.6)
            if fl.sum() < 10 or reg.sum() < 10:
                out.append(rec | {"status": "skipped", "reason": "경계 주변 신호 부족"})
                continue
            floor = float(np.median(e[fl]))
            ri = np.nonzero(reg)[0]
            on = ri[e[ri] > floor + 15.0]
            if not len(on):
                out.append(rec | {"status": "skipped", "reason": "경계에서 원음 레벨 상승 없음"})
                continue
            t_on = float(t[on[0]])
            pw = (t >= t_on) & (t <= t_on + 0.6)
            plateau = float(np.percentile(e[pw], 75))
            if plateau - floor < ORIG_RAMP_CONTRAST_DB:
                out.append(rec | {"status": "skipped", "reason": f"켜짐/꺼짐 대비 {plateau - floor:.1f} dB < "
                                                                    f"{ORIG_RAMP_CONTRAST_DB:g} dB"})
                continue
            a = max(0, int(on[0]) - int(0.4 / ORIG_RAMP_HOP_S))
            sp = rising_span(t[a:], e[a:], plateau, ORIG_RAMP_LO_DB, ORIG_RAMP_HI_DB)
            if sp is None:
                out.append(rec | {"status": "skipped", "reason": "경사 교차점을 찾지 못함"})
                continue
            st = (t >= sp["t_hi"]) & (t <= sp["t_hi"] + ORIG_RAMP_STEADY_S)
            steady = float(np.percentile(e[st], 90) - np.percentile(e[st], 10)) if st.sum() >= 10 else 99.0
            if steady > ORIG_RAMP_STEADY_DB:
                out.append(rec | {"status": "skipped", "reason": f"경사 뒤 소리가 일정하지 않음(p90-p10 {steady:.1f} dB) — "
                                                                    "소리 내용(말소리·효과음) 자체의 시작/끝이라 편집 경사를 못 잼"})
                continue
            f = span_to_fade(sp["span_s"], table)
            out.append(rec | {"status": "measured", "t": round(abs(sp["t_hi"]) if kind == "off" else sp["t_lo"], 3),
                              "fade_s": round(f, 4), "span_s": round(sp["span_s"], 4),
                              "plateau_db": round(plateau, 1), "floor_db": round(floor, 1),
                              "steady_p90_p10_db": round(steady, 1)})
    return out


def _lufs_of(x: np.ndarray, sr: int) -> float | None:
    """EBU R128 integrated loudness (ffmpeg ebur128) of a mono signal via a temporary wav."""
    from ..util.media import lufs, write_wav

    with tempfile.TemporaryDirectory(prefix="shortkit_lufs_") as td:
        p = Path(td) / "x.wav"
        write_wav(p, np.asarray(x, np.float32), sr)
        v = lufs(p).get("integrated_lufs")
    return None if v is None or v < -69.0 else float(v)


def kept_speech_level(mix: np.ndarray, vocals: np.ndarray | None, speech: list[dict] | None, sr: int = SR) -> dict:
    """Loudness of the kept speech relative to the programme: integrated loudness (EBU R128, same mono
    downmix for both) of the vocals stem over the speech segments minus that of the whole mix."""
    method = ("보컬 stem 의 대사 구간만 이어 붙인 EBU R128 통합 음량 - 믹스 전체 통합 음량(둘 다 같은 모노 "
              "다운믹스, ffmpeg ebur128) = 최종 음량 T 에서 살린 대사가 T+값 LUFS 에 놓임")
    if vocals is None:
        return {"status": "unmeasured", "method": method,
                "blocker": "보컬 stem 없음(분리 불가) — 믹스에서 대사 음량만 잴 수 없음"}
    if not speech:
        return {"status": "unmeasured", "method": method, "blocker": "대사 구간 없음"}
    parts = [vocals[int(s["start"] * sr):int(s["end"] * sr)] for s in speech]
    total = sum(len(p_) for p_ in parts) / sr
    if total < KEEP_LEVEL_MIN_S:
        return {"status": "unmeasured", "method": method,
                "blocker": f"대사 길이 {total:.2f} s < {KEEP_LEVEL_MIN_S:g} s (게이트 통합 음량 불가)"}
    ls = _lufs_of(np.concatenate(parts), sr)
    lm = _lufs_of(mix, sr)
    if ls is None or lm is None:
        return {"status": "unmeasured", "method": method, "blocker": "음량 측정 실패(무음에 가까움)"}
    return {"status": "measured", "rel_program_lu": round(ls - lm, 2), "speech_lufs_mono": round(ls, 2),
            "mix_lufs_mono": round(lm, 2), "speech_s": round(total, 2), "t": speech[0]["start"], "method": method}


# ============================================================================ per video
def original_path(preset_name: str, video_id: str) -> Path:
    return audio_dir(preset_name, video_id) / "original.json"


def load_context(preset_name: str, video_id: str, audio_path: str | os.PathLike | None = None,
                 stems: Stems | None = None) -> dict:
    """Mix, stems, BGM model and derived signals shared by the original/sfx analyses."""
    src = Path(audio_path) if audio_path else find_reference_media(preset_name, video_id)
    if src is None or not Path(src).is_file():
        return {"src": None}
    mix = load_mono(src, SR)
    if stems is None:
        stems = load_cached_stems(preset_name, video_id, audio_path=src)
    vocals = None
    if stems is not None and stems.vocals is not None:
        vocals = np.zeros_like(mix)
        n = min(len(mix), len(stems.vocals))
        vocals[:n] = stems.vocals[:n]
    bgm_sig = mix - vocals if vocals is not None else mix
    model, bgm_rec = load_bgm_model(preset_name, video_id, bgm_sig, SR)
    return {"src": Path(src), "mix": mix, "stems": stems, "vocals": vocals, "bgm_sig": bgm_sig, "model": model,
            "bgm_rec": bgm_rec}


def analyze_original(preset_name: str, video_id: str, audio_path: str | os.PathLike | None = None,
                     stems: Stems | None = None, write: bool = True, ctx: dict | None = None) -> dict:
    ctx = ctx or load_context(preset_name, video_id, audio_path, stems)
    out: dict = {"schema": SCHEMA, "video_id": video_id, "analyzed_at": now_iso()}
    if ctx.get("src") is None:
        why = f"레퍼런스 원본 파일 없음(video_id={video_id}) — 다운로드 전/차단"
        out.update({"status": "unmeasured", "blocker": why,
                    "speech": {"presence": "unmeasured", "blocker": why},
                    "original_audio": {"presence": "unmeasured", "blocker": why},
                    "ducking": {"presence": "unmeasured", "blocker": why},
                    "silences": {"status": "unmeasured", "items": [], "blocker": why},
                    "original_edges": {"status": "unmeasured", "edges": [], "blocker": why},
                    "kept_speech_level": {"status": "unmeasured", "blocker": why}})
        if write:
            write_json(original_path(preset_name, video_id), out)
        return out
    mix, vocals, model = ctx["mix"], ctx["vocals"], ctx["model"]
    sr = SR
    out["audio_file"] = rel_or_none(ctx["src"])
    st = ctx.get("stems")
    out["separator"] = ({"status": "measured", "model": st.model, "model_version": st.model_version}
                        if st is not None else _sep_status(preset_name, video_id))
    bgm_desc = None
    if model is not None:
        from .audio_bgm import speech_mask_from_vocals

        bgm_desc = describe_gain(model, speech_mask_from_vocals(vocals, sr))
    # --- speech / original sound
    if vocals is not None:
        speech = speech_segments_from_stem(vocals, sr)
        sp = {"method": "보컬 stem 에너지(상위 레벨 -30 dB 이내, 0.35 s 간격 병합)", "confidence": "normal"}
        if model is None:
            # BGM not aligned: the non-vocal residual is usable only when BGM is known to be absent
            bgm_absent = (ctx.get("bgm_rec") or {}).get("presence") == "absent"
            residual = ctx["bgm_sig"] if bgm_absent else None
        elif model.aligned is not None:
            residual = ctx["bgm_sig"] - model.estimate(len(mix))
        else:
            from .sfx_events import residual_signal

            residual, _, _ = residual_signal(ctx)
    elif model is not None and model.aligned is not None:
        residual = mix - model.estimate(len(mix))
        speech = speech_segments_from_residual(residual, sr)
        sp = {"method": "보컬 stem 없음 → (믹스 - 정렬된 깨끗한 BGM) 잔여 신호의 유성음·음절 변조 휴리스틱",
              "confidence": "low"}
    elif model is not None:
        from .sfx_events import residual_signal

        residual, _, _ = residual_signal(ctx)
        speech = speech_segments_from_residual(residual, sr)
        sp = {"method": "보컬 stem 없음 + BGM 속도 변경 → 스펙트럼 차감 잔여 신호의 유성음·음절 변조 휴리스틱",
              "confidence": "low"}
    else:
        speech, residual = None, None
        sp = {"method": None, "confidence": None,
              "blocker": "보컬 stem 없음(분리 불가) 이고 BGM 도 파형 정렬되지 않음 → 대사만 떼어낼 방법 없음"}
    dur = len(mix) / sr
    if speech is None:
        out["speech"] = {"presence": "unmeasured", **sp}
        out["original_audio"] = {"presence": "unmeasured", "blocker": sp["blocker"]}
    else:
        frac = sum(s["end"] - s["start"] for s in speech) / max(dur, 1e-6)
        out["speech"] = {"presence": "present" if speech else "absent", "segments": speech,
                         "fraction": round(frac, 4), **sp}
        out["original_audio"] = _original_presence(residual, sr, speech, dur)
    # --- ducking
    out["ducking"] = measure_ducking(model, speech or []) if speech is not None else \
        {"presence": "unmeasured", "blocker": "대사 구간 측정 불가 → 덕킹 판정 불가"}
    if model is not None and bgm_desc and bgm_desc.get("present"):
        out["bgm_level"] = {"base_db": bgm_desc["base_db"], "base_method": bgm_desc["base_method"],
                            "unexplained_dips": unexplained_dips(model, speech or [], bgm_desc["cuts"],
                                                                 bgm_desc["base_db"]),
                            "note": "대사 밖 BGM 하강(효과음·컷 때문에 덕킹했는지 확인용)"}
    else:
        out["bgm_level"] = {"status": "unmeasured", "blocker": (ctx.get("bgm_rec") or {}).get("blocker")
                            or "bgm.json 없음(`shortkit ref bgm-identify` 전)"}
    sil = detect_silences(mix, sr, model, bgm_desc)
    ramp_info = measure_silence_ramps(ctx["bgm_sig"], model, sil, sr)
    out["silences"] = {"status": "measured", "items": sil,
                       "rule": f"믹스가 바닥(max({SILENCE_ABS_FLOOR_DB} dBFS, 활성 중앙값-{SILENCE_REL_DB} dB)) 아래로 "
                               f"{SILENCE_MIN_S} s 이상, 앞뒤 {SILENCE_EDGE_S} s 제외; bgm_cut=BGM 이 앞뒤엔 있고 그 안에선 없음",
                       "ramp_method": ramp_info["method"]}
    # --- on/off edge ramps of the original sound + loudness of the kept speech
    o_sig, o_desc, o_blk = original_signal(ctx)
    oa_segs = (out.get("original_audio") or {}).get("segments") or []
    if o_sig is None or speech is None:
        out["original_edges"] = {"status": "unmeasured", "edges": [],
                                 "blocker": o_blk or "원음 구간 측정 불가"}
    else:
        edges = measure_original_ramps(o_sig, oa_segs, sr, exclude=bgm_unexplained_spans(ctx.get("bgm_rec")))
        ok = [e for e in edges if e["status"] == "measured"]
        out["original_edges"] = {
            "status": "measured" if ok else "unmeasured", "signal": o_desc, "edges": edges,
            "method": (f"원음 신호({o_desc}) RMS {ORIG_RAMP_WIN_S * 1000:g} ms 포락선이 경계 뒤 일정 레벨(p75) 대비 "
                       f"{ORIG_RAMP_LO_DB:g} → {ORIG_RAMP_HI_DB:g} dB 를 지나는 시간 → 렌더러 모양(선형 진폭) 에 같은 측정을 한 "
                       f"표로 fade_s 환산; 경사 뒤 {ORIG_RAMP_STEADY_S:g} s 가 일정(p90-p10 <= {ORIG_RAMP_STEADY_DB:g} dB)한 "
                       "경계만"),
            "blocker": None if ok else ("측정 가능한 원음 경계 없음(말소리로 바로 시작/끝나거나 대비 부족)" if oa_segs
                                        else "원음 구간 없음")}
    out["kept_speech_level"] = kept_speech_level(mix, vocals, speech, sr)
    out["status"] = "measured" if speech is not None else "unmeasured"
    out["blocker"] = None if speech is not None else sp.get("blocker")
    if write:
        write_json(original_path(preset_name, video_id), out)
    return out


def _original_presence(residual: np.ndarray | None, sr: int, speech: list[dict], dur: float) -> dict:
    """Original (on-site) sound = speech segments + sustained non-BGM residual (>= 0.5 s)."""
    if residual is None:
        if not speech:
            return {"presence": "unmeasured", "segments": [],
                    "blocker": "BGM 이 제거되지 않아 대사 외 현장음 유무를 잴 수 없음(대사도 없음)"}
        return {"presence": "present", "segments": speech,
                "method": "대사 구간만(BGM 미제거라 대사 외 현장음은 못 잼)"}
    t, lv = frame_rms_db(residual, sr, 0.05, 0.02)
    active = lv > max(-55.0, float(np.percentile(lv, 99)) - 35.0) if len(lv) else np.zeros(0, bool)
    segs = _mask_to_segments(t, active, 0.02, 0.2, 0.5)
    allseg = sorted(speech + segs, key=lambda s: s["start"])
    merged: list[dict] = []
    for s in allseg:
        if merged and s["start"] <= merged[-1]["end"]:
            merged[-1]["end"] = max(merged[-1]["end"], s["end"])
        else:
            merged.append({"start": s["start"], "end": s["end"]})
    frac = sum(s["end"] - s["start"] for s in merged) / max(dur, 1e-6)
    return {"presence": "present" if merged else "absent", "segments": merged, "fraction": round(frac, 4),
            "method": "대사 구간 ∪ BGM 제거 잔여 신호가 0.5 s 이상 지속되는 구간(짧은 효과음 제외)"}


def _sep_status(preset_name: str, video_id: str) -> dict:
    rec = read_json(audio_dir(preset_name, video_id) / "separation.json")
    if rec:
        return {"status": rec.get("status"), "model": rec.get("model"), "blocker": rec.get("blocker")}
    return {"status": "unmeasured", "blocker": "분리 실행 기록 없음"}


# ============================================================================ per-video loudness
def loudness_path(preset_name: str, video_id: str) -> Path:
    return audio_dir(preset_name, video_id) / "loudness.json"


def measure_loudness(preset_name: str, video_id: str, audio_path: str | os.PathLike | None = None,
                     write: bool = True) -> dict:
    """EBU R128 of one reference file (ffmpeg ebur128 on the file as downloaded) -> audio/loudness.json.

    Also stores the RMS of the analysis mono downmix (the reference of sfx_events ``gain_db``) and the
    time of the sample peak (evidence for the true peak).  Cached by the file's sha256."""
    from ..util.hashing import sha256_file
    from ..util.media import lufs, read_audio

    src = Path(audio_path) if audio_path else find_reference_media(preset_name, video_id)
    if src is None or not Path(src).is_file():
        return {"schema": LOUDNESS_SCHEMA, "video_id": video_id, "status": "unmeasured",
                "blocker": f"레퍼런스 원본 파일 없음(video_id={video_id}) — 다운로드 전/차단"}
    sha = sha256_file(src)
    old = read_json(loudness_path(preset_name, video_id))
    if old and old.get("schema") == LOUDNESS_SCHEMA and old.get("audio_sha256") == sha and old.get("status"):
        return old
    out = {"schema": LOUDNESS_SCHEMA, "video_id": video_id, "measured_at": now_iso(), "audio_file": rel_or_none(src),
           "audio_sha256": sha, "method": "ffmpeg ebur128=peak=true (파일 그대로: 통합 음량 I, 참 최대 레벨 Peak, LRA)"}
    try:
        ld = lufs(src)
    except Exception as e:  # noqa: BLE001 - a failed measurement is unmeasured, never a guess
        out.update({"status": "unmeasured", "blocker": f"ebur128 실패: {type(e).__name__}"})
        return out
    x = read_audio(src, sr=48000, mono=False)
    pk = int(np.argmax(np.max(np.abs(x), axis=1))) if len(x) else 0
    mono = load_mono(src, SR)
    il, tp = ld.get("integrated_lufs"), ld.get("true_peak_db")
    out.update({"status": "measured" if il is not None and il > -69.0 else "unmeasured",
                "integrated_lufs": il if il is not None and il > -69.0 else None, "true_peak_db": tp,
                "lra": ld.get("lra"), "duration_s": round(len(mono) / SR, 3),
                "sample_peak_t": round(pk / 48000, 3),
                "mix_rms_dbfs": round(float(20 * np.log10(np.sqrt(np.mean(mono.astype(np.float64) ** 2)) + 1e-12)), 3),
                "mix_rms_basis": f"모노 다운믹스 (L+R)/2, {SR} Hz — sfx_events gain_db 의 기준(믹스 전체 RMS)"})
    if out["status"] != "measured":
        out["blocker"] = "무음에 가까움(통합 음량 없음)"
    if write:
        write_json(loudness_path(preset_name, video_id), out)
    return out


# ============================================================================ preset measurements
def _video_ids_with_audio(preset_name: str) -> list[str]:
    from .. import paths

    base = paths.absp(f"presets/{preset_name}/analysis")
    if not base.is_dir():
        return []
    return sorted({p.parent.parent.name for pat in ("*/audio/bgm.json", "*/audio/loudness.json")
                   for p in base.glob(pat)})


def _video_ids_for_measure(preset_name: str) -> list[str]:
    """Analysed videos + downloaded reference files (long-form uploads of the snapshot excluded)."""
    from .. import paths
    from ..util.jsonio import read_jsonl
    from .separation import AUDIO_EXT

    ids = set(_video_ids_with_audio(preset_name))
    ref = paths.absp(f"presets/{preset_name}/reference")
    ids |= {str(r["video_id"]) for r in read_jsonl(ref / "downloads.jsonl") if r.get("video_id")}
    if (ref / "videos").is_dir():
        ids |= {p.stem for p in (ref / "videos").iterdir()
                if p.is_file() and p.suffix.lower() in AUDIO_EXT and not p.name.endswith((".part", ".tmp"))}
    snap = read_json(ref / "latest100.json") or {}
    long_form = {str(v.get("video_id")) for v in (snap.get("videos") or []) if isinstance(v, dict)
                 and v.get("kind") == "video"} if isinstance(snap, dict) else set()
    return sorted(i for i in ids if i not in long_form)


def _sfx_file_level(stored: str) -> tuple[float | None, str | None]:
    """RMS (dBFS, analysis mono downmix) of a library SFX file over the same window the events use:
    from its onset (40 dB under the peak) for min(duration to 35 dB under the peak, 0.5 s)."""
    from .sfx_events import _auto_duration
    from .sfx_map import onset_of
    from .separation import resolve_stored

    try:
        f = resolve_stored(stored)
        x = load_mono(f, SR)
    except Exception as e:  # noqa: BLE001
        return None, f"효과음 파일을 읽지 못함({type(e).__name__})"
    if not len(x) or float(np.max(np.abs(x))) < 1e-6:
        return None, "효과음 파일이 무음"
    on = onset_of(x, SR)
    dur = _auto_duration(x, SR, on)
    seg = x[int(on * SR):int((on + min(max(dur, 0.02), 0.5)) * SR)]
    return float(20 * np.log10(np.sqrt(np.mean(seg.astype(np.float64) ** 2)) + 1e-12)), None


def aggregate_measurements(preset_name: str, video_ids: list[str] | None = None, write: bool = True) -> dict:
    """Per-video loudness.json / bgm.json / original.json / sfx_events.json (+ sfx_catalog.json, sfx_map.yaml)
    -> ``presets/<name>/measurements/audio.json`` items for the preset keys audio.loudness.*, audio.bgm.*,
    audio.ducking.*, audio.original.keep_gain_db / fade_s, audio.silence.fade_s and audio.sfx.gain_db_default
    (overall + by_format, evidence per video/time).

    Levels that the renderer applies "at the final programme loudness" (CONTRACT section 12) are
    converted with the programme target T that production will use: a requested change of
    audio.loudness.integrated_lufs if there is one, else the value measured in this run (per format for
    the per-format statistics), else the preset's current value -- the method text names which.
    Keys with no measured video stay ``unmeasured`` with the blocker (the reference-collection blocker
    when no reference video exists at all); nothing is filled in."""
    from collections import Counter

    from .. import paths
    from ..config import load_preset
    from ..util.stats import categorical, pstats, pstats_by_group
    from .audio_bgm import bgm_path
    from .common import snapshot_blocker
    from .sfx_catalog import video_formats
    from .sfx_events import sfx_events_path

    pr = load_preset(preset_name)
    vids = video_ids if video_ids is not None else _video_ids_for_measure(preset_name)
    fmts = video_formats(preset_name)
    no_ref = snapshot_blocker(preset_name) if not vids else None

    def blk(specific: str) -> str:
        return no_ref or specific

    bgm = {v: read_json(bgm_path(preset_name, v)) for v in vids}
    orig = {v: read_json(original_path(preset_name, v)) for v in vids}
    loud = {v: measure_loudness(preset_name, v, write=write) for v in vids}
    measured_bgm = {v: b for v, b in bgm.items() if b and b.get("status") == "measured" and b.get("match")}
    items = []

    def unmeasured(key, unit, method, blocker, **extra):
        it = {"key": key, "status": "unmeasured", "value": None, "overall": {"n": 0}, "by_format": {},
              "evidence": [], "method": method, "measured_at": now_iso(), "blocker": blocker}
        if unit is not None:
            it["unit"] = unit
        return it | extra

    def numeric(key, rows, unit, method, blocker, **extra):
        if not rows:
            return unmeasured(key, unit, method, blocker, **extra)
        g = pstats_by_group(rows, "value")
        byf = {f: dict(st, value=st["p50"]) for f, st in g["by_format"].items()}
        return {"key": key, "status": "measured", "value": g["overall"]["p50"], "unit": unit,
                "overall": g["overall"], "by_format": byf,
                "evidence": [{"video_id": r["video_id"], "t": r["t"], "value": r["value"]} for r in rows],
                "method": method, "measured_at": now_iso(), "blocker": None} | extra

    def cat(key, rows, method, blocker):
        vals = [r["value"] for r in rows]
        if not vals:
            return unmeasured(key, None, method, blocker)
        c = categorical(vals)
        byf = {}
        for f in sorted({r["format_id"] for r in rows if r.get("format_id")}):
            cf = categorical([r["value"] for r in rows if r.get("format_id") == f])
            byf[f] = {"n": cf["n"], "counts": cf["counts"], "mode": cf["mode"], "value": cf["mode"]}
        return {"key": key, "status": "measured", "value": c["mode"],
                "overall": {"n": c["n"], "counts": c["counts"], "share": c["share"], "mode": c["mode"]},
                "by_format": byf,
                "evidence": [{"video_id": r["video_id"], "t": r["t"], "value": r["value"]} for r in rows],
                "method": method, "measured_at": now_iso(), "blocker": None}

    # ------------------------------------------------------------ loudness (EBU R128 per reference file)
    no_file = "레퍼런스 원본 파일이 있는 영상 없음(다운로드 전/차단)"
    lrows = [{"video_id": v, "format_id": fmts.get(v), "t": 0.0, "value": d["integrated_lufs"],
              "range_s": [0.0, d.get("duration_s")]} for v, d in loud.items() if d.get("status") == "measured"]
    it_lufs = numeric("audio.loudness.integrated_lufs", lrows, "LUFS",
                      "ffmpeg ebur128 통합 음량(EBU R128, 레퍼런스 파일 전체) — 근거 t=0 은 파일 전체 구간", blk(no_file))
    for e, r in zip(it_lufs["evidence"], lrows):
        e["range_s"] = r["range_s"]
    tprows = [{"video_id": v, "format_id": fmts.get(v), "t": d.get("sample_peak_t"), "value": d["true_peak_db"]}
              for v, d in loud.items() if d.get("status") == "measured" and d.get("true_peak_db") is not None]
    items.append(it_lufs)
    items.append(numeric("audio.loudness.true_peak_db", tprows, "dBTP",
                         "ffmpeg ebur128 참 최대 레벨(4배 오버샘플, 레퍼런스 파일 전체); 값 = p50(영상별 최대치의 중앙값); "
                         "근거 t = 샘플 최대값 위치(참고)", blk(no_file)))

    LKEY = "audio.loudness.integrated_lufs"

    def target_for(fmt: str | None = None) -> tuple[float, str]:
        """Programme loudness T production will use (see the docstring)."""
        if pr.origin(LKEY) == "requested_change":
            return float(pr.get(LKEY)), "requested_change"
        if it_lufs["status"] == "measured":
            bf = it_lufs["by_format"].get(fmt) if fmt else None
            if bf and bf.get("value") is not None:
                return float(bf["value"]), f"이번 측정 {fmt} p50"
            return float(it_lufs["value"]), "이번 측정 p50"
        return float(pr.get(LKEY)), f"프리셋 현재값({pr.origin(LKEY)})"

    def numeric_conv(key, raw, conv, unit, method, blocker):
        """Numeric item whose value depends on T: overall stats with T(overall), per-format stats with
        T(format); evidence values use T(overall)."""
        T0, src0 = target_for(None)
        rows = [dict(r, value=conv(r, T0)) for r in raw]
        rows = [r for r in rows if r["value"] is not None]
        tnote = f" [T: 전체 {T0:g} LUFS ({src0})"
        if not rows:
            return unmeasured(key, unit, method + tnote + "]", blocker)
        ov = pstats([r["value"] for r in rows])
        byf, tf = {}, {}
        for f in sorted({r["format_id"] for r in rows if r.get("format_id")}):
            Tf, srcf = target_for(f)
            st = pstats([conv(r, Tf) for r in raw if r.get("format_id") == f])
            if st["n"]:
                byf[f] = dict(st, value=st["p50"])
                tf[f] = Tf
        if tf:
            tnote += "; 포맷별 " + ", ".join(f"{f} {v:g}" for f, v in tf.items())
        return {"key": key, "status": "measured", "value": ov["p50"], "unit": unit, "overall": ov, "by_format": byf,
                "evidence": [{"video_id": r["video_id"], "t": r["t"], "value": r["value"]} for r in rows],
                "method": method + tnote + "]", "measured_at": now_iso(), "blocker": None,
                "target_lufs": {"overall": T0, "source": src0, "by_format": tf}}

    # ------------------------------------------------------------ BGM
    no_bgm = blk("BGM 이 식별된 레퍼런스 영상 없음(다운로드 차단/라이브러리 미일치)")

    def rows_of(field, only=None):
        out = []
        for v, b in measured_bgm.items():
            m = b["match"]
            f = m.get(field) or {}
            if f.get("status") != "measured" or f.get("value") is None:
                continue
            if only and (m["track_id"]["value"], m["version"]["value"]) != only:
                continue
            out.append({"video_id": v, "format_id": fmts.get(v), "t": m["used_range_ref_s"]["value"][0],
                        "value": f["value"]})
        return out

    tid_rows = rows_of("track_id")
    items.append(cat("audio.bgm.track_id", tid_rows, "깨끗한 음원 라이브러리 대조(bgm.json)", no_bgm))
    items.append(cat("audio.bgm.title", rows_of("title"), "라이브러리 index.yaml 제목", no_bgm))
    items.append(cat("audio.bgm.version", rows_of("version"), "라이브러리 index.yaml 버전 + 속도 1.0 일치 규칙", no_bgm))
    pairs = Counter((b["match"]["track_id"]["value"], b["match"]["version"]["value"]) for b in measured_bgm.values())
    modal = pairs.most_common(1)[0][0] if pairs else None
    note = f" (가장 많이 쓰인 곡·버전 {modal[0]}/{modal[1]} 인 영상만)" if modal else ""
    items.append(numeric("audio.bgm.tempo_ratio", rows_of("tempo_ratio", modal), "ratio",
                         "특징 NCC 속도 격자 + 파형 정렬" + note, no_bgm))
    items.append(numeric("audio.bgm.section_start_s", rows_of("section_start_s", modal), "s",
                         "깨끗한 음원 안 사용 시작 지점" + note, no_bgm))
    gain_raw = []
    for v, b in measured_bgm.items():
        m = b["match"]
        lu = (m.get("mix_integrated_lufs") or {}).get("value")
        if m["gain_db"]["status"] == "measured" and lu is not None:
            gain_raw.append({"video_id": v, "format_id": fmts.get(v), "t": m["used_range_ref_s"]["value"][0],
                             "gain": float(m["gain_db"]["value"]), "lufs": float(lu)})
    items.append(numeric_conv("audio.bgm.gain_db", gain_raw, lambda r, T: round(r["gain"] + (T - r["lufs"]), 2), "dB",
                              "깨끗한 음원 대비 LS 이득(대사 없는 구간 중앙값)을 최종 음량 T 일 때로 환산: "
                              "gain + (T - 레퍼런스 믹스 LUFS)", no_bgm))
    items.append(numeric("audio.bgm.fade_in_s", rows_of("fade_in_s"), "s", "선형 진폭 페이드 모델", no_bgm))
    items.append(numeric("audio.bgm.fade_out_s", rows_of("fade_out_s"), "s", "선형 진폭 페이드 모델", no_bgm))
    loop_rows = []
    for v, b in measured_bgm.items():
        lp = b["match"].get("loop") or {}
        if lp.get("presence") not in ("present", "absent"):
            continue
        rs = [j for j in lp.get("jumps") or [] if j.get("kind") == "restart"]
        loop_rows.append({"video_id": v, "format_id": fmts.get(v), "value": lp["presence"],
                          "t": rs[0]["t"] if rs else b["match"]["used_range_ref_s"]["value"][0]})
    lp_item = cat("audio.bgm.loop", loop_rows,
                  "영상별 BGM 되감김(같은 음원의 앞 지점으로 되돌아감) 있다/없다: bgm.json match.loop (창별 같은 음원 정렬 → "
                  "정렬선 사이 시작점 변화 < -1 s). 값 = 측정 영상의 과반(>50 %)이 '있다'일 때만 true(동률은 false)",
                  no_bgm if not measured_bgm else blk("되감김을 판정할 수 있는 BGM 영상 없음"))
    if lp_item["status"] == "measured":
        cnt = lp_item["overall"]["counts"]
        lp_item["value"] = bool(cnt.get("present", 0) > cnt.get("absent", 0))
        lp_item["presence"] = "present" if cnt.get("present") else "absent"
        for f, st in lp_item["by_format"].items():
            st["value"] = bool(st["counts"].get("present", 0) > st["counts"].get("absent", 0))
        lp_item["unit"] = "bool"
    items.append(lp_item)
    # ------------------------------------------------------------ ducking
    dk_rows = {"depth_db": [], "attack_s": [], "release_s": []}
    for v, o in orig.items():
        dk = (o or {}).get("ducking") or {}
        if dk.get("presence") not in ("present", "absent"):
            continue
        for seg in dk.get("per_segment") or []:
            if seg.get("status") != "measured":
                continue
            for k in dk_rows:
                if seg.get(k) is not None:
                    dk_rows[k].append({"video_id": v, "format_id": fmts.get(v), "t": seg["start"], "value": seg[k]})
    no_dk = blk("덕킹을 잴 수 있는 영상 없음(BGM 미식별 또는 대사 구간 없음)")
    items.append(numeric("audio.ducking.depth_db", dk_rows["depth_db"], "dB", "대사 전/중 BGM 이득 중앙값 차", no_dk))
    items.append(numeric("audio.ducking.attack_s", dk_rows["attack_s"], "s", "10→90 % 하강 시간/0.8 (선형 dB 경사)", no_dk))
    items.append(numeric("audio.ducking.release_s", dk_rows["release_s"], "s", "10→90 % 복귀 시간/0.8 (선형 dB 경사)", no_dk))
    # ------------------------------------------------------------ kept original sound
    kl_rows = []
    for v, o in orig.items():
        kl = (o or {}).get("kept_speech_level") or {}
        if kl.get("status") == "measured":
            kl_rows.append({"video_id": v, "format_id": fmts.get(v), "t": kl.get("t"), "value": kl["rel_program_lu"]})
    items.append(numeric(
        "audio.original.keep_gain_db", kl_rows, "dB",
        "살린 대사의 음량 - 프로그램 음량 (LU): 보컬 stem 의 대사 구간 EBU R128 통합 음량 - 믹스 통합 음량(같은 모노 다운믹스). "
        "최종 음량 T 에서 살린 대사는 T + 값 LUFS 에 놓인다. 렌더러는 이 dB 를 '녹음된 그대로의 원본 소리'에 곱하므로 "
        "소스 대사 음량이 L_src 이면 필요한 이득은 T + 값 - L_src (소스별 음량 맞춤은 렌더러 쪽 과제)",
        blk("살린 대사 음량을 잴 영상 없음(보컬 stem 없음 = 분리 불가, 또는 대사 없음)"),
        value_semantics="LU re programme loudness (kept speech integrated loudness - mix integrated loudness)"))
    sfx_near: dict[str, list[tuple[float, float]]] = {}
    for v in vids:
        d = read_json(sfx_events_path(preset_name, v)) or {}
        sfx_near[v] = [(float(e["t"]), float(e["t"]) + float(e.get("dur") or 0.0)) for e in d.get("events") or []
                       if e.get("class") != "intentional_silence"]
    fe_rows, fe_skipped = [], Counter()
    for v, o in orig.items():
        oe = (o or {}).get("original_edges") or {}
        for e in oe.get("edges") or []:
            if e.get("status") != "measured":
                fe_skipped[str(e.get("reason", e.get("status")))[:40]] += 1
                continue
            if any(a - 0.3 <= e["t"] <= b + 0.3 for a, b in sfx_near.get(v, [])):
                fe_skipped["효과음 구간 ±0.3 s 안 경계 제외"] += 1
                continue
            fe_rows.append({"video_id": v, "format_id": fmts.get(v), "t": e["t"], "value": e["fade_s"],
                            "edge": e["edge"]})
    fe_item = numeric("audio.original.fade_s", fe_rows, "s",
                      "원음(믹스 - 정렬된 BGM) RMS 10 ms 포락선의 켜짐/꺼짐 경사: 경계 뒤 일정 레벨 대비 -25 → -2 dB 시간을 "
                      f"렌더러의 선형 진폭 페이드에 같은 측정을 한 표로 환산; 경사 뒤 {ORIG_RAMP_STEADY_S:g} s 가 일정한"
                      f"(p90-p10 <= {ORIG_RAMP_STEADY_DB:g} dB) 경계만, 효과음 구간(시작~끝) ±0.3 s 경계 제외",
                      blk("편집 경사를 잴 수 있는 원음 경계 없음(BGM 파형 정렬 없음, 원음이 말소리로 바로 시작/끝남, 또는 대비 부족)"))
    if fe_skipped:
        fe_item["edges_skipped"] = dict(fe_skipped)
    items.append(fe_item)
    # ------------------------------------------------------------ intentional silence ramps
    sr_rows = []
    for v, o in orig.items():
        for it in ((o or {}).get("silences") or {}).get("items") or []:
            for side, r in ((it.get("ramps") or {}).items() if isinstance(it.get("ramps"), dict) else []):
                if isinstance(r, dict) and r.get("status") == "measured":
                    sr_rows.append({"video_id": v, "format_id": fmts.get(v), "t": r["t"], "value": r["fade_s"],
                                    "side": side})
    items.append(numeric("audio.silence.fade_s", sr_rows, "s",
                         "의도적 정적(BGM 끊김) 앞뒤 BGM 파형 LS 이득(3 ms 창)이 기준 레벨 대비 -2 → -30 dB 를 지나는 시간을 "
                         "렌더러 모양(dB 선형 0→-120 dB, edit.audio.build_envelope)에 같은 측정을 한 표로 fade_s 환산 "
                         "(들어갈 때·나올 때 모두 표본)",
                         blk("BGM 이 파형 정렬된 영상에서 의도적 정적(BGM 끊김)을 찾지 못함")))
    # ------------------------------------------------------------ SFX level at the programme loudness
    items.append(_sfx_gain_item(preset_name, pr, vids, fmts, loud, numeric_conv, unmeasured, blk))
    snap = read_json(paths.absp(pr.get("reference.snapshot_file"))) or {}
    out = {"schema": "shortkit.measurement/1", "group": "audio",
           "source_snapshot": snap.get("captured_at") if isinstance(snap, dict) else None,
           "videos": vids, "generated_at": now_iso(), "items": items}
    if write:
        write_json(paths.absp(f"presets/{preset_name}/measurements/audio.json"), out)
    return out


def _sfx_gain_item(preset_name, pr, vids, fmts, loud, numeric_conv, unmeasured, blk) -> dict:
    """audio.sfx.gain_db_default: level of the catalogued edit SFX in the reference programme converted
    to the renderer's gain semantics (dB applied to the library FILE, at the final programme loudness T):

        gain = gain_db_rel_mix + mix_rms_dbfs - mix_LUFS + T - file_rms_dbfs

    per catalogued event (sfx_events.json: event RMS over min(dur, 0.5 s) re whole-mix RMS; loudness.json:
    whole-mix RMS of the same mono downmix and EBU R128 LUFS of the file; sfx_map.yaml: the library file
    mapped to the event's type (status have); file RMS over the same window from its onset)."""
    from collections import Counter

    from .. import paths
    from ..util.jsonio import read_yaml
    from .sfx_catalog import catalog_path
    from .sfx_events import sfx_events_path

    key = "audio.sfx.gain_db_default"
    method = ("카탈로그 효과음(edit_sfx) 이벤트마다 gain = gain_db_rel_mix(이벤트 RMS[최대 0.5 s] - 믹스 전체 RMS) + "
              "믹스 RMS dBFS - 믹스 LUFS + T - 매핑된 창고 파일 RMS dBFS(시작점부터 같은 길이) → 렌더러 의미(최종 음량 T 에서 "
              "효과음 파일에 곱하는 dB); 값 = 이벤트 p50")
    cat = read_json(catalog_path(preset_name)) or {}
    types = {t["type_id"]: t for t in cat.get("types") or [] if t.get("class") == "edit_sfx"}
    cat_note = {"catalog_status": cat.get("status", "unmeasured"),
                "catalog_gain_db_rel_mix_p50_by_type": {tid: (t.get("gain_db_rel_mix") or {}).get("p50")
                                                        for tid, t in types.items()}}
    if not types:
        return unmeasured(key, "dB", method, blk("효과음 카탈로그에 edit_sfx 종류 없음(카탈로그 못 잼)"), **cat_note)
    smap = read_yaml(paths.absp(pr.get("audio.sfx.map")), {}) or {}
    mapped = {tid: v for tid, v in (smap.get("types") or {}).items() if isinstance(v, dict) and v.get("status") == "have"
              and v.get("file")}
    levels: dict[str, tuple[float | None, str | None]] = {tid: _sfx_file_level(v["file"]) for tid, v in mapped.items()}
    raw, prog, rel_all, why = [], [], [], Counter()
    for v in vids:
        ld = loud.get(v) or {}
        d = read_json(sfx_events_path(preset_name, v)) or {}
        for e in d.get("events") or []:
            tid = e.get("type_id")
            if tid not in types or e.get("gain_db") is None:
                continue
            if ld.get("status") != "measured" or ld.get("mix_rms_dbfs") is None:
                why["믹스 음량(loudness.json) 없음"] += 1
                continue
            rel_all.append(float(e["gain_db"]))
            lvl = float(e["gain_db"]) + float(ld["mix_rms_dbfs"]) - float(ld["integrated_lufs"])
            prog.append(lvl)
            fl = levels.get(tid)
            if fl is None:
                why[f"{tid}: 창고 매핑 없음(sfx_map {((smap.get('types') or {}).get(tid) or {}).get('status', '없음')})"] += 1
                continue
            if fl[0] is None:
                why[f"{tid}: {fl[1]}"] += 1
                continue
            raw.append({"video_id": v, "format_id": fmts.get(v), "t": e["t"], "type_id": tid, "lvl": lvl,
                        "file_rms": fl[0]})
    extra = cat_note | {"catalog_gain_db_rel_mix_overall": pstats(rel_all),
                        "level_re_programme_db": pstats(prog),
                        "level_re_programme_note": "이벤트 RMS dBFS - 믹스 LUFS (파일과 무관한 부분; 참고)",
                        "events_not_converted": dict(why), "mapped_types": sorted(mapped)}
    if not raw:
        b = ("효과음 창고 매핑(sfx_map status have) 없음 → 파일 대비 이득으로 환산 불가" if prog
             else "효과음 이벤트가 측정된 영상 없음")
        return unmeasured(key, "dB", method, blk(b), **extra)
    it = numeric_conv(key, raw, lambda r, T: round(r["lvl"] + T - r["file_rms"], 2), "dB", method, None)
    it.update(extra)
    return it
