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

Also here: intentional silences (mix below a floor for >= 0.3 s mid-video, with BGM cut), and BGM
dips not explained by speech (evidence for "SFX/cuts are never a reason to duck").
"""
from __future__ import annotations

import os
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
                    "silences": {"status": "unmeasured", "items": [], "blocker": why}})
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
    out["silences"] = {"status": "measured", "items": sil,
                       "rule": f"믹스가 바닥(max({SILENCE_ABS_FLOOR_DB} dBFS, 활성 중앙값-{SILENCE_REL_DB} dB)) 아래로 "
                               f"{SILENCE_MIN_S} s 이상, 앞뒤 {SILENCE_EDGE_S} s 제외; bgm_cut=BGM 이 앞뒤엔 있고 그 안에선 없음"}
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


# ============================================================================ preset measurements
def _video_ids_with_audio(preset_name: str) -> list[str]:
    from .. import paths

    base = paths.absp(f"presets/{preset_name}/analysis")
    if not base.is_dir():
        return []
    return sorted(p.parent.parent.name for p in base.glob("*/audio/bgm.json"))


def aggregate_measurements(preset_name: str, video_ids: list[str] | None = None, write: bool = True) -> dict:
    """Per-video bgm.json / original.json -> ``presets/<name>/measurements/audio.json`` items for the
    preset keys audio.bgm.* and audio.ducking.* (overall + by_format, evidence per video/time).

    Keys with no measured video stay ``unmeasured`` with the blocker; nothing is filled in."""
    from .. import paths
    from ..config import load_preset
    from ..util.stats import categorical, pstats_by_group
    from .audio_bgm import bgm_path
    from .sfx_catalog import video_formats

    pr = load_preset(preset_name)
    target = float(pr.get("audio.loudness.integrated_lufs"))
    vids = video_ids if video_ids is not None else _video_ids_with_audio(preset_name)
    fmts = video_formats(preset_name)
    bgm = {v: read_json(bgm_path(preset_name, v)) for v in vids}
    orig = {v: read_json(original_path(preset_name, v)) for v in vids}
    measured_bgm = {v: b for v, b in bgm.items() if b and b.get("status") == "measured" and b.get("match")}
    items = []

    def numeric(key, rows, unit, method, blocker):
        if not rows:
            return {"key": key, "status": "unmeasured", "value": None, "unit": unit, "overall": {"n": 0},
                    "by_format": {}, "evidence": [], "method": method, "measured_at": now_iso(),
                    "blocker": blocker}
        g = pstats_by_group(rows, "value")
        byf = {f: dict(st, value=st["p50"]) for f, st in g["by_format"].items()}
        return {"key": key, "status": "measured", "value": g["overall"]["p50"], "unit": unit,
                "overall": g["overall"], "by_format": byf,
                "evidence": [{"video_id": r["video_id"], "t": r["t"], "value": r["value"]} for r in rows],
                "method": method, "measured_at": now_iso(), "blocker": None}

    def cat(key, rows, method, blocker):
        vals = [r["value"] for r in rows]
        if not vals:
            return {"key": key, "status": "unmeasured", "value": None, "overall": {"n": 0}, "by_format": {},
                    "evidence": [], "method": method, "measured_at": now_iso(), "blocker": blocker}
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

    no_bgm = "BGM 이 식별된 레퍼런스 영상 없음(다운로드 차단/라이브러리 미일치)"

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
    from collections import Counter

    pairs = Counter((b["match"]["track_id"]["value"], b["match"]["version"]["value"]) for b in measured_bgm.values())
    modal = pairs.most_common(1)[0][0] if pairs else None
    note = f" (가장 많이 쓰인 곡·버전 {modal[0]}/{modal[1]} 인 영상만)" if modal else ""
    items.append(numeric("audio.bgm.tempo_ratio", rows_of("tempo_ratio", modal), "ratio",
                         "특징 NCC 속도 격자 + 파형 정렬" + note, no_bgm))
    items.append(numeric("audio.bgm.section_start_s", rows_of("section_start_s", modal), "s",
                         "깨끗한 음원 안 사용 시작 지점" + note, no_bgm))
    gain_rows = []
    for v, b in measured_bgm.items():
        m = b["match"]
        lu = (m.get("mix_integrated_lufs") or {}).get("value")
        if m["gain_db"]["status"] == "measured" and lu is not None:
            gain_rows.append({"video_id": v, "format_id": fmts.get(v), "t": m["used_range_ref_s"]["value"][0],
                              "value": round(m["gain_db"]["value"] + (target - lu), 2)})
    items.append(numeric("audio.bgm.gain_db", gain_rows, "dB",
                         f"깨끗한 음원 대비 LS 이득(대사 없는 구간 중앙값)을 믹스 통합 음량이 목표 {target} LUFS 일 때로 "
                         "환산: gain + (목표 LUFS - 레퍼런스 믹스 LUFS)", no_bgm))
    items.append(numeric("audio.bgm.fade_in_s", rows_of("fade_in_s"), "s", "선형 진폭 페이드 모델", no_bgm))
    items.append(numeric("audio.bgm.fade_out_s", rows_of("fade_out_s"), "s", "선형 진폭 페이드 모델", no_bgm))
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
    no_dk = "덕킹을 잴 수 있는 영상 없음(BGM 미식별 또는 대사 구간 없음)"
    items.append(numeric("audio.ducking.depth_db", dk_rows["depth_db"], "dB", "대사 전/중 BGM 이득 중앙값 차", no_dk))
    items.append(numeric("audio.ducking.attack_s", dk_rows["attack_s"], "s", "10→90 % 하강 시간/0.8 (선형 dB 경사)", no_dk))
    items.append(numeric("audio.ducking.release_s", dk_rows["release_s"], "s", "10→90 % 복귀 시간/0.8 (선형 dB 경사)", no_dk))
    snap = read_json(paths.absp(pr.get("reference.snapshot_file"))) or {}
    out = {"schema": "shortkit.measurement/1", "group": "audio",
           "source_snapshot": snap.get("captured_at") if isinstance(snap, dict) else None,
           "videos": vids, "generated_at": now_iso(), "items": items}
    if write:
        write_json(paths.absp(f"presets/{preset_name}/measurements/audio.json"), out)
    return out
