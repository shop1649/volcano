"""Master render: ResolvedEdit -> MP4 (H.264 yuv420p + AAC 48 kHz, +faststart).

Video: every output frame n (t = n / canvas.fps) is composed in numpy/OpenCV from the IR:
  decode (ffmpeg: accurate seek, delogo with enable=between(t,..) in SOURCE time, clean crop,
  area pre-scale, showinfo pts) -> source frame for the clip's source time (speed / freeze
  hold) -> sub-pixel affine fit into canvas.video_region (cover/contain) with the eased zoom
  about zoom.center -> background (color or blurred source) -> transitions (crossfade blend,
  flash colour overlay around the boundary) -> raw RGB piped into ffmpeg, where libass draws
  the ONE ASS file (captions + decorations, fontsdir = build/fonts) before x264 encoding.
Audio: mixed in numpy (sample exact, deterministic): BGM (tempo pre-step + section trim, gain,
  fades, per-sample envelope = ducking under kept dialogue + intentional silences only),
  kept originals, SFX at t (``pre_norm_stems``, side-effect free).

  Gain semantics: audio.bgm.gain_db, audio.sfx.gain_db_default / plan sfx gain_db and
  audio.original.keep_gain_db are levels AT THE FINAL PROGRAM LOUDNESS (``ref audio-measure`` writes
  audio.bgm.gain_db that way: clean-file LS gain + target_lufs - reference mix LUFS).  So the stems
  are summed at those levels and the loudness normalisation (one global gain g, integrated LUFS ->
  target) is expected to be a small trim.

  True-peak safety: the BGM is NEVER limited (no SFX- or cut-caused ducking).  Only the foreground
  (kept originals + SFX) gets a per-sample gain k <= 1 so that the 4x-oversampled peak of
  g * (bgm + k * fg) stays under the ceiling, and k never goes below -audio.loudness.max_limiter_db.
  If more reduction would be needed, g itself is lowered (closed form, ``limiter_gain_cap``) and the
  resulting LUFS shortfall is reported in render_report.json (warning in test mode, error -> no
  render in production).  build/mix.wav, build/stems/{bgm,originals,sfx}.wav (final levels) and
  build/fg_gain.json (per-frame foreground limiter gain, for the MLT exporter) are written.
"""
from __future__ import annotations

import math
import json
import os
import re
import subprocess
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .. import config, paths
from ..util.hashing import sha256_file
from ..util.jsonio import now_iso, write_json
from ..util.media import FFMPEG, ffmpeg, lufs, probe, read_audio, write_wav
from .audio import SILENCE_DB
from .ir import Clip, ResolvedEdit
from .resolve import base_fit, effective_src_rect, src_time_at, src_to_region

TP_MARGIN_DB = 0.5          # internal true-peak headroom below the preset ceiling (AAC overshoot)
LOUDNESS_ITER_TOL_LU = 0.3
NORM_TRIM_WARN_DB = 3.0     # diagnostic only: a larger normalisation gain means the plan/preset levels
                            # are not levels at program loudness (every stem ends up that far off plan)
# DEPRECATED legacy alias (exporters still import it): the blur strength is the preset key
# render.clean.blur_sigma_ratio carried in Clip.blur_sigma_ratio -- use ``blur_sigma_src``.
BLUR_SIGMA_FRAC = 1 / 6.0
EPS_T = 1e-3


class RenderError(RuntimeError):
    pass


def _threads() -> str:
    return os.environ.get("SHORTKIT_RENDER_THREADS", "2")


# ----------------------------------------------------------------------------- gates
def production_gate(r: ResolvedEdit, allow_unmeasured: bool = False) -> None:
    """Refuse production renders that break the user's gates, even when called directly
    (not only through the CLI): unresolved SFX, missing first-episode approval, preset keys
    that are unmeasured (unless allow_unmeasured) or linked to no code / no output check."""
    if r.mode != "production":
        return
    res = config.audit(r.preset_name, production=True)
    if res["unmeasured"] and not allow_unmeasured:
        raise RenderError(f"production 렌더 거부: 프리셋 미측정(못 잼) 키 {len(res['unmeasured'])}개 "
                          "(--allow-unmeasured 로만 진행 가능)")
    if res["no_code"] or res["no_qa"]:
        raise RenderError(f"production 렌더 거부: 코드/검사에 연결되지 않은 설정 {len(res['no_code'])}/{len(res['no_qa'])}개")
    bad = [s.id for s in r.audio.sfx if not s.path]
    if bad:
        raise RenderError(f"production 렌더 거부: 파일이 해결되지 않은 효과음 {bad} (sfx_map have 필요)")
    from .plan import approval_state, load_plan

    plan = load_plan(r.episode_id)
    pr = config.load_preset(r.preset_name, None if r.format_id == "UNCLASSIFIED" else r.format_id)
    st = approval_state(plan, bool(pr.get("approval.first_episode_requires_approval")))
    if st["required"] and not st["approved"]:
        raise RenderError("production 렌더 거부: 첫 에피소드 제안서가 승인되지 않았습니다")


# ----------------------------------------------------------------------------- audio
def db2lin(db: float) -> float:
    return float(10.0 ** (db / 20.0))


def _fit_len(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) >= n:
        return x[:n]
    return np.concatenate([x, np.zeros((n - len(x),) + x.shape[1:], np.float32)])


def _atempo_chain(r: float) -> str:
    parts = []
    while r > 2.0:
        parts.append("atempo=2.0")
        r /= 2.0
    while r < 0.5:
        parts.append("atempo=0.5")
        r /= 0.5
    parts.append(f"atempo={r:.6f}")
    return ",".join(parts)


def _has_filter(name: str) -> bool:
    try:
        out = subprocess.run([FFMPEG, "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    except OSError:
        return False
    return re.search(rf"\s{re.escape(name)}\s", out) is not None


def tempo_stretch(src: Path, ratio: float, dst: Path, sr: int) -> str:
    """Pitch-preserving tempo change (rubberband if available, else atempo). Returns method."""
    if _has_filter("rubberband"):
        af, method = f"rubberband=tempo={ratio:.6f}", "rubberband"
    else:
        af, method = _atempo_chain(ratio), "atempo"
    ffmpeg(["-i", src, "-af", af, "-ar", str(sr), "-ac", "2", "-c:a", "pcm_f32le", dst])
    return method


def envelope_gain(env: list, n: int, sr: int) -> np.ndarray:
    if not env:
        return np.ones(n, np.float32)
    t = np.arange(n) / sr
    et = np.array([p[0] for p in env], float)
    ed = np.array([p[1] for p in env], float)
    db = np.interp(t, et, ed)
    g = np.power(10.0, db / 20.0)
    g[db <= SILENCE_DB + 1e-6] = 0.0
    return g.astype(np.float32)


def _lin_fade(n: int, sr: int, fade_in: float, fade_out: float) -> np.ndarray:
    g = np.ones(n, np.float32)
    fi, fo = int(round(fade_in * sr)), int(round(fade_out * sr))
    if fi > 0:
        g[:fi] *= np.linspace(0.0, 1.0, fi, endpoint=False, dtype=np.float32)
    if fo > 0:
        g[max(0, n - fo):] *= np.linspace(1.0, 0.0, min(fo, n), dtype=np.float32)
    return g


def _tp_points(x: np.ndarray) -> np.ndarray:
    """(n, 5, ch) float32: every sample plus its 4 points of the 4x-oversampled signal (the true-peak
    grid used by the limiter and by ``_true_peak_db``)."""
    from scipy.signal import resample_poly

    n = len(x)
    if n == 0:
        return np.zeros((0, 5, x.shape[1] if x.ndim > 1 else 1), np.float32)
    up = resample_poly(x.astype(np.float32), 4, 1, axis=0)[: 4 * n]
    if len(up) < 4 * n:
        up = np.concatenate([up, np.zeros((4 * n - len(up), up.shape[1]), up.dtype)])
    return np.concatenate([x[:, None, :].astype(np.float32), up.reshape(n, 4, -1).astype(np.float32)], axis=1)


def _oversampled_peak(x: np.ndarray) -> np.ndarray:
    """Per-sample |x| envelope including inter-sample (4x oversampled) peaks, max over channels."""
    return np.abs(_tp_points(x)).max(axis=(1, 2))


def _smooth_min_gain(g: np.ndarray, blk: int = 240, W: int = 4) -> np.ndarray:
    """Look-ahead block minimum + widened min filter + moving average; never exceeds ``g`` and keeps
    its minimum (the averaging window is narrower than the min filter)."""
    from scipy.ndimage import minimum_filter1d, uniform_filter1d

    n = len(g)
    if n == 0 or g.min() >= 1.0:
        return np.ones(n, np.float32)
    nb = int(math.ceil(n / blk))
    gp = np.concatenate([g, np.ones(nb * blk - n)])
    gb = gp.reshape(nb, blk).min(axis=1)
    gm = minimum_filter1d(gb, size=2 * W + 3, mode="nearest")
    gs = uniform_filter1d(gm, size=2 * W + 1, mode="nearest")
    centers = (np.arange(nb) + 0.5) * blk
    return np.minimum(np.interp(np.arange(n), centers, gs), g).astype(np.float32)


def limiter_gain(x: np.ndarray, ceiling_db: float) -> np.ndarray:
    """Per-sample gain (<=1) keeping the 4x-oversampled (true) peak of ``x`` under the ceiling."""
    c = db2lin(ceiling_db)
    return _smooth_min_gain(np.minimum(1.0, c / np.maximum(_oversampled_peak(x), 1e-12)))


def _fg_need(bp: np.ndarray, fp: np.ndarray, c: float) -> np.ndarray:
    """Largest per-sample k in [0, 1] with |b + k f| <= c on every true-peak point (signed, exact:
    the feasible k form an interval [0, (c - sign(f) b) / |f|] when |b| <= c)."""
    af = np.abs(fp)
    with np.errstate(divide="ignore", invalid="ignore"):
        k = np.where(af > 1e-12, (c - np.sign(fp) * bp) / np.maximum(af, 1e-12), np.inf)
    return np.clip(k, 0.0, 1.0).min(axis=(1, 2)).astype(np.float32)


def foreground_limiter_gain(bg: np.ndarray, fg: np.ndarray, ceiling_db: float,
                            points: tuple[np.ndarray, np.ndarray] | None = None) -> np.ndarray:
    """Stem-aware safety limiter: gain (<=1) applied ONLY to the foreground stems (kept originals +
    SFX) so that the true peak of bg + fg * k stays under the ceiling.  The BGM is never modulated
    by it -- SFX (or cuts) must never duck the BGM (user rule).  (Where the BGM alone exceeds the
    ceiling no k helps: ``limiter_gain_cap`` lowers the global gain for that.)"""
    bp, fp = points if points is not None else (_tp_points(bg), _tp_points(fg))
    return _smooth_min_gain(_fg_need(bp, fp, db2lin(ceiling_db)))


def limiter_gain_cap(bp: np.ndarray, fp: np.ndarray, ceiling_db: float, max_reduction_db: float) -> float:
    """Largest global gain g for which g * bgm stays under the ceiling AND the foreground limiter
    needs at most ``max_reduction_db``:  g <= c / max_j max(|b_j|, m |f_j| + sign(f_j) b_j),
    m = 10^(-max_reduction_db / 20), over every true-peak point j (``_tp_points``)."""
    c, m = db2lin(ceiling_db), db2lin(-abs(max_reduction_db))
    d = np.maximum(np.abs(bp), m * np.abs(fp) + np.sign(fp) * bp)
    dm = float(d.max()) if d.size else 0.0
    return math.inf if dm <= 1e-12 else c / dm


def _true_peak_db(x: np.ndarray) -> float:
    from scipy.signal import resample_poly

    up = resample_poly(x, 4, 1, axis=0)
    p = float(np.abs(up).max()) if len(up) else 0.0
    return 20 * math.log10(p) if p > 0 else -math.inf


def _measure(x: np.ndarray, sr: int, tmpdir: Path) -> dict:
    f = tmpdir / "measure.wav"
    write_wav(f, x, sr)
    return lufs(f)


def _db(x: float) -> float:
    return round(20 * math.log10(max(1e-12, x)), 3)


@dataclass
class Stems:
    """Pre-normalisation stems: every source at its plan level (gain, fades, envelope, placement),
    i.e. the level it should have at the final program loudness, before the global gain g."""
    sample_rate: int
    bgm: np.ndarray                  # (n, 2) float32
    originals: np.ndarray
    sfx: np.ndarray
    info: dict = field(default_factory=dict)   # warnings, bgm_tempo_method, bgm, sfx_ranges, original_ranges

    @property
    def foreground(self) -> np.ndarray:
        return self.originals + self.sfx


def pre_norm_stems(r: ResolvedEdit) -> Stems:
    """Build the BGM / kept-originals / SFX stems from the IR exactly as the master mix uses them,
    BEFORE loudness normalisation and limiting.  Side-effect free: nothing is written to the project
    (tempo / speed intermediates live in a system temporary directory that is removed)."""
    a = r.audio
    sr = a.sample_rate
    n = int(round(r.duration * sr))
    info: dict = {"warnings": [], "sfx_ranges": {}, "original_ranges": []}
    bgm = np.zeros((n, 2), np.float32)
    orig = np.zeros((n, 2), np.float32)
    sfx = np.zeros((n, 2), np.float32)
    with tempfile.TemporaryDirectory(prefix="shortkit_stems_") as td:
        tmpdir = Path(td)
        if a.bgm and a.bgm.path:
            b = a.bgm
            src = paths.absp(b.path)
            offset = b.section_start_s
            if abs(b.tempo_ratio - 1.0) > 1e-9:
                tmp = tmpdir / "bgm_tempo.wav"
                info["bgm_tempo_method"] = tempo_stretch(src, b.tempo_ratio, tmp, sr)
                src, offset = tmp, b.section_start_s / b.tempo_ratio
            else:
                info["bgm_tempo_method"] = "none(ratio=1)"
            x = read_audio(src, sr=sr, mono=False, start=offset, duration=n / sr)
            if len(x) < n:
                info["warnings"].append(f"BGM 이 {(n - len(x)) / sr:.2f}s 부족 → 뒤는 무음")
            x = _fit_len(x, n)
            g = db2lin(b.gain_db) * _lin_fade(n, sr, b.fade_in_s, b.fade_out_s) * envelope_gain(b.envelope, n, sr)
            bgm = (x * g[:, None]).astype(np.float32)
            info["bgm"] = {"path": b.path, "section_start_s": b.section_start_s, "tempo_ratio": b.tempo_ratio,
                           "gain_db": b.gain_db, "envelope_points": len(b.envelope)}
        for o in a.originals:
            src = paths.absp(o.path)
            dur = o.src_end - o.src_start
            x = read_audio(src, sr=sr, mono=False, start=o.src_start, duration=dur)
            if abs(o.speed - 1.0) > 1e-9:
                t_in, t_out = tmpdir / "orig_in.wav", tmpdir / "orig_out.wav"
                write_wav(t_in, x, sr)
                ffmpeg(["-i", t_in, "-af", _atempo_chain(o.speed), "-ar", str(sr), "-ac", "2", t_out])
                x = read_audio(t_out, sr=sr, mono=False)
            m = int(round((o.out_end - o.out_start) * sr))
            x = _fit_len(x, m) * db2lin(o.gain_db) * _lin_fade(m, sr, o.fade_s, o.fade_s)[:, None]
            s0 = int(round(o.out_start * sr))
            e0 = min(n, s0 + m)
            orig[s0:e0] += x[: e0 - s0]
            info["original_ranges"].append({"clip_id": o.clip_id, "s0": s0, "e0": e0})
        for sp in a.sfx:
            if not sp.path:
                info["warnings"].append(f"효과음 {sp.id}({sp.type}) 파일 미해결 → 테스트 모드라서 넣지 않음")
                continue
            x = read_audio(paths.absp(sp.path), sr=sr, mono=False) * db2lin(sp.gain_db)
            s0 = int(round(sp.t * sr))
            e0 = min(n, s0 + len(x))
            if e0 > s0:
                sfx[s0:e0] += x[: e0 - s0]
            info["sfx_ranges"][sp.id] = [s0, e0]
    return Stems(sample_rate=sr, bgm=bgm, originals=orig, sfx=sfx, info=info)


def plan_loudness(st: Stems, target_lufs: float, ceiling_db: float, max_limiter_db: float,
                  tmpdir: Path) -> dict:
    """Global gain g and per-sample foreground gain k for the stems (see the module docstring).
    Returns {g, k, pre, wanted_gain_db, cap_gain_db, capped, iterations}."""
    sr = st.sample_rate
    bgm, fg = st.bgm, st.foreground
    pre = _measure(bgm + fg, sr, tmpdir)
    n = len(bgm)
    out = {"pre": pre, "g": 1.0, "k": np.ones(n, np.float32), "wanted_gain_db": None, "cap_gain_db": None,
           "capped": False, "iterations": 0}
    bp, fp = _tp_points(bgm), _tp_points(fg)
    c = db2lin(ceiling_db)
    cap = limiter_gain_cap(bp, fp, ceiling_db, max_limiter_db)
    out["cap_gain_db"] = None if math.isinf(cap) else _db(cap)
    if pre.get("integrated_lufs") is None or pre["integrated_lufs"] < -69.0:
        g = min(1.0, cap)          # (near) silence: no normalisation, but never over the ceiling
        out["silent"] = True
    else:
        want = db2lin(target_lufs - pre["integrated_lufs"])
        out["wanted_gain_db"] = _db(want)
        g = min(want, cap)
        for it in range(6):
            out["iterations"] = it + 1
            k = _smooth_min_gain(_fg_need(bp, fp, c / g))
            post = _measure(g * (bgm + fg * k[:, None]), sr, tmpdir)
            err = target_lufs - (post.get("integrated_lufs") if post.get("integrated_lufs") is not None else target_lufs)
            if abs(err) <= LOUDNESS_ITER_TOL_LU:
                break
            g_new = min(g * db2lin(err), cap)
            if abs(g_new - g) <= 1e-9 * g:
                break                      # at the limiter cap: cannot get louder without over-limiting
            g = g_new
        out["capped"] = g >= cap * (1 - 1e-9) and want > cap
    out["g"] = g
    out["k"] = _smooth_min_gain(_fg_need(bp, fp, c / g))
    return out


def fg_gain_frames(k: np.ndarray, sr: int, fps: float, duration: float) -> tuple[list[float], list[float]]:
    """Per output frame (frame f covers samples [round(f sr/fps), round((f+1) sr/fps))): (min k, mean k)."""
    nf = int(round(duration * fps))
    mins, means = [], []
    for f in range(nf):
        s0, s1 = int(round(f * sr / fps)), min(len(k), int(round((f + 1) * sr / fps)))
        seg = k[s0:s1] if s1 > s0 else k[max(0, s0 - 1):s0 + 1]
        mins.append(round(float(seg.min()), 6) if len(seg) else 1.0)
        means.append(round(float(seg.mean()), 6) if len(seg) else 1.0)
    return mins, means


def mix_audio(r: ResolvedEdit, build: Path) -> dict:
    a = r.audio
    if a.max_limiter_db is None or a.loudness_tolerance_lu is None:
        raise RenderError("resolved.json 에 audio.max_limiter_db / loudness_tolerance_lu 가 없습니다(이전 버전 IR): "
                          f"`shortkit episode resolve {r.episode_id}` 를 다시 실행하세요")
    sr = a.sample_rate
    prod = r.mode == "production"
    st = pre_norm_stems(r)
    n = len(st.bgm)
    rep: dict = {"sample_rate": sr, "samples": n, "warnings": list(st.info["warnings"]), "errors": [],
                 "level_semantics": "gain_db = 최종 프로그램 음량에서의 레벨(정규화는 작은 보정이어야 함)"}
    for k_ in ("bgm_tempo_method", "bgm"):
        if k_ in st.info:
            rep[k_] = st.info[k_]
    target, ceiling = a.target_lufs, a.true_peak_db - TP_MARGIN_DB
    max_lim, tol = float(a.max_limiter_db), float(a.loudness_tolerance_lu)
    rep["target_lufs"], rep["true_peak_ceiling_db"], rep["tp_margin_db"] = target, ceiling, TP_MARGIN_DB
    tmpdir = Path(tempfile.mkdtemp(prefix="mix_", dir=build))
    try:
        lp = plan_loudness(st, target, ceiling, max_lim, tmpdir)
        g, k = lp["g"], lp["k"]
        rep["pre_norm"] = lp["pre"]
        if lp.get("silent"):
            rep["warnings"].append("믹스가 무음에 가까워 음량 정규화를 하지 않음")
        rep["norm_gain_db"] = _db(g)
        red = float(-20 * np.log10(max(1e-9, float(k.min())))) if len(k) else 0.0
        rep["fg_limiter_max_reduction_db"] = round(red, 3)
        rep["limiter_max_reduction_db"] = 0.0      # no limiter ever touches the BGM / whole mix
        rep["bgm_limited"] = False
        rep["limiter"] = {"max_limiter_db": max_lim, "fg_max_reduction_db": round(red, 3),
                          "fg_samples_limited": int((k < 1.0 - 1e-6).sum()),
                          "gain_cap_db": lp["cap_gain_db"], "capped_by_limiter_rule": bool(lp["capped"]),
                          "applies_to": "kept originals + SFX only (BGM never limited)"}
        if red > max_lim + 0.01:
            raise RenderError(f"내부 오류: 전경 리미터 감쇠 {red:.2f} dB > 허용 {max_lim} dB")
        sfx_lim = []
        for s in a.sfx:
            rg = st.info["sfx_ranges"].get(s.id)
            if not rg or rg[1] <= rg[0]:
                continue
            rd = round(float(-20 * np.log10(max(1e-9, float(k[rg[0]:rg[1]].min())))), 2)
            sfx_lim.append({"id": s.id, "type": s.type, "t": s.t, "plan_gain_db": s.gain_db, "reduction_db": rd,
                            "final_gain_db": round(s.gain_db + 20 * math.log10(g) - rd, 2)})
        rep["sfx_limiting"] = sfx_lim
        kk = k[:, None]
        bgm, orig, sfx = st.bgm * g, st.originals * g * kk, st.sfx * g * kk
        mix = bgm + orig + sfx
        tp = _true_peak_db(mix)
        rep["final_trim_db"] = 0.0
        if tp > ceiling:            # residual from block smoothing: one global trim (never BGM-only)
            trim = db2lin(ceiling - tp)
            bgm, orig, sfx, mix = bgm * trim, orig * trim, sfx * trim, mix * trim
            rep["final_trim_db"] = round(ceiling - tp, 3)
        write_wav(build / "mix.wav", mix, sr)
        (build / "stems").mkdir(exist_ok=True)
        write_wav(build / "stems" / "bgm.wav", bgm, sr)
        write_wav(build / "stems" / "originals.wav", orig, sr)
        write_wav(build / "stems" / "sfx.wav", sfx, sr)
        fps = float(r.canvas["fps"])
        kmin, kmean = fg_gain_frames(k, sr, fps, r.duration)
        write_json(build / "fg_gain.json", {
            "schema": "shortkit.fg_gain/1", "episode_id": r.episode_id, "fps": fps, "frames": len(kmin),
            "sample_rate": sr, "applies_to": ["originals", "sfx"],
            "semantics": "foreground(원본 소리+효과음) 안전 리미터 이득 k(선형, <=1). 최종 = 정규화 전 스템 × "
                         "10^((norm_gain_db + final_trim_db)/20) × k. 프레임 f = 샘플 [round(f·sr/fps), "
                         "round((f+1)·sr/fps)); gain_min = 그 프레임의 최소 k(피크 순간), gain_mean = 평균 k. "
                         "BGM 에는 적용하지 않음.",
            "norm_gain_db": rep["norm_gain_db"], "final_trim_db": rep["final_trim_db"],
            "max_limiter_db": max_lim, "max_reduction_db": round(red, 3), "gain_min": kmin, "gain_mean": kmean})
        rep["fg_gain_file"] = f"episodes/{r.episode_id}/build/fg_gain.json"
        rep["mix_wav"] = lufs(build / "mix.wav")
        got = rep["mix_wav"].get("integrated_lufs")
        shortfall = None if got is None else round(target - got, 2)
        rep["loudness"] = {"target_lufs": target, "tolerance_lu": tol, "pre_norm_lufs": lp["pre"].get("integrated_lufs"),
                           "wanted_norm_gain_db": lp["wanted_gain_db"], "norm_gain_db": rep["norm_gain_db"],
                           "limiter_gain_cap_db": lp["cap_gain_db"], "capped_by_limiter_rule": bool(lp["capped"]),
                           "final_trim_db": rep["final_trim_db"], "mix_lufs": got, "shortfall_lu": shortfall,
                           "status": "ok"}
        if got is not None and (shortfall > tol or got - target > tol):
            why = (f"전경 리미터 최대 {max_lim} dB 규칙 때문에 전체 이득을 {lp['cap_gain_db']} dB 로 제한"
                   if lp["capped"] or rep["final_trim_db"] < 0 else "정규화 반복이 목표에 수렴하지 못함")
            msg = (f"목표 음량 {target} LUFS 에 못 맞춤(측정 {got} LUFS, 부족 {shortfall} LU > 허용 {tol} LU): {why}"
                   " → BGM/효과음/원음 레벨 균형 조정 필요")
            rep["loudness"]["status"] = "shortfall"
            (rep["errors"] if prod else rep["warnings"]).append(msg)
        if lp["wanted_gain_db"] is not None and abs(lp["wanted_gain_db"]) > NORM_TRIM_WARN_DB:
            rep["warnings"].append(f"정규화 이득 {lp['wanted_gain_db']} dB: 계획 레벨이 최종 프로그램 음량 기준이 아님"
                                   f"(모든 소리가 계획보다 {lp['wanted_gain_db']} dB 달라짐) → 프리셋/계획 gain_db 확인")
    finally:
        for f in tmpdir.glob("*"):
            f.unlink()
        tmpdir.rmdir()
    return rep


# ----------------------------------------------------------------------------- video
def _hex_rgb(h: str) -> np.ndarray:
    h = h.lstrip("#")
    return np.array([int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)], np.float32)


def _color_matrix(info) -> str:
    v = next((s for s in info.raw.get("streams", []) if s.get("codec_type") == "video"), {})
    cs = (v.get("color_space") or "").lower()
    if cs in ("bt709",):
        return "bt709"
    if cs in ("bt470bg", "smpte170m", "bt601"):
        return "bt601"
    return "bt709" if (info.height or 0) >= 720 else "bt601"   # untagged: HD convention


def blur_ratio(clip: Clip) -> float:
    """render.clean.blur_sigma_ratio as resolved into the IR (no code default)."""
    if clip.blur_sigma_ratio is None:
        raise RenderError(f"클립 {clip.id}: blur 연산이 있지만 IR 에 blur_sigma_ratio 가 없습니다(이전 버전 IR) → 다시 resolve")
    return float(clip.blur_sigma_ratio)


def blur_sigma_src(clip: Clip, rect) -> float:
    """Gaussian sigma in SOURCE px of one blur op: max(w, h) * render.clean.blur_sigma_ratio."""
    return max(1.0, max(float(rect.w), float(rect.h)) * blur_ratio(clip))


class ClipReader:
    """Forward-only frame source for one clip (source frames with their real pts)."""

    def __init__(self, clip: Clip):
        self.clip = clip
        src = paths.absp(clip.source_path)
        info = probe(src)
        self.src_fps = info.fps or 30.0
        ex, ey, ew, eh = effective_src_rect(clip)
        b, _, _ = base_fit(clip)
        zmax = 1.0
        if clip.zoom:
            zmax = max(1.0, clip.zoom.scale_from, clip.zoom.scale_to)
        k = min(1.0, b * zmax)
        self.W, self.H = max(2, int(round(ew * k))), max(2, int(round(eh * k)))
        self.kx, self.ky = self.W / ew, self.H / eh
        self.ex, self.ey = ex, ey
        start = max(0.0, clip.src_in - 2.0 / self.src_fps)
        dur = (clip.src_out - start) + 2.0 / self.src_fps
        vf = []
        iw, ih = info.width, info.height
        for d in clip.delogo:
            x = int(max(1, min(d.x, iw - 3)))
            y = int(max(1, min(d.y, ih - 3)))
            w = int(max(1, min(d.w, iw - 1 - x)))
            h = int(max(1, min(d.h, ih - 1 - y)))
            en = ""
            if d.start is not None or d.end is not None:
                en = f":enable='between(t,{d.start if d.start is not None else 0},{d.end if d.end is not None else 1e9})'"
            vf.append(f"delogo=x={x}:y={y}:w={w}:h={h}{en}")
        if clip.crop:
            vf.append(f"crop={int(round(ew))}:{int(round(eh))}:{int(round(ex))}:{int(round(ey))}")
        vf.append(f"scale={self.W}:{self.H}:flags=area:in_color_matrix={_color_matrix(info)}:in_range=auto:out_range=full")
        vf.append("format=rgb24")
        vf.append("showinfo")
        cmd = [FFMPEG, "-hide_banner", "-nostdin", "-v", "info", "-threads", _threads(), "-copyts",
               "-ss", f"{start:.6f}", "-t", f"{dur:.6f}", "-i", str(src), "-an", "-vf", ",".join(vf),
               "-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        self.pts: list[float] = []
        self._cv = threading.Condition()
        self._done = False
        self._err_tail: list[str] = []
        self._t = threading.Thread(target=self._read_stderr, daemon=True)
        self._t.start()
        self.frame_bytes = self.W * self.H * 3
        self.cur: np.ndarray | None = None
        self.cur_pts: float | None = None
        self.nxt: np.ndarray | None = None
        self.nxt_pts: float | None = None
        self.idx = 0
        self._advance()
        self._advance()

    def _read_stderr(self):
        pat = re.compile(r"\bn:\s*(\d+).*?\bpts_time:\s*(-?[\d.]+)")
        for raw in self.proc.stderr:
            line = raw.decode("utf-8", "replace")
            m = pat.search(line) if "showinfo" in line.lower() or "pts_time" in line else None
            if m:
                with self._cv:
                    self.pts.append(float(m.group(2)))
                    self._cv.notify_all()
            else:
                self._err_tail = (self._err_tail + [line])[-20:]
        with self._cv:
            self._done = True
            self._cv.notify_all()

    def _pts_of(self, i: int) -> float | None:
        with self._cv:
            while len(self.pts) <= i and not self._done:
                self._cv.wait(timeout=5)
            return self.pts[i] if i < len(self.pts) else None

    def _advance(self):
        self.cur, self.cur_pts = self.nxt, self.nxt_pts
        buf = self.proc.stdout.read(self.frame_bytes)
        if len(buf) < self.frame_bytes:
            self.nxt, self.nxt_pts = None, None
            return
        self.nxt = np.frombuffer(buf, np.uint8).reshape(self.H, self.W, 3)
        self.nxt_pts = self._pts_of(self.idx)
        self.idx += 1

    def frame_at(self, s: float) -> np.ndarray:
        while self.nxt is not None and self.nxt_pts is not None and self.nxt_pts <= s + EPS_T:
            self._advance()
        if self.cur is None:
            if self.nxt is None:
                raise RenderError(f"클립 {self.clip.id}: 소스 프레임을 읽지 못함 ({''.join(self._err_tail)[-400:]})")
            return self._apply_blur(self.nxt, self.nxt_pts or s)
        return self._apply_blur(self.cur, self.cur_pts if self.cur_pts is not None else s)

    def _apply_blur(self, fr: np.ndarray, pts: float) -> np.ndarray:
        if not self.clip.blur:
            return fr
        import cv2

        out = None
        for bl in self.clip.blur:
            if (bl.start is not None and pts < bl.start) or (bl.end is not None and pts > bl.end):
                continue
            if out is None:
                out = fr.copy()
            x0 = int(max(0, (bl.x - self.ex) * self.kx))
            y0 = int(max(0, (bl.y - self.ey) * self.ky))
            x1 = int(min(self.W, math.ceil((bl.x + bl.w - self.ex) * self.kx)))
            y1 = int(min(self.H, math.ceil((bl.y + bl.h - self.ey) * self.ky)))
            if x1 > x0 and y1 > y0:
                sig = max(1.0, max(bl.w * self.kx, bl.h * self.ky) * blur_ratio(self.clip))
                out[y0:y1, x0:x1] = cv2.GaussianBlur(out[y0:y1, x0:x1], (0, 0), sig)
        return fr if out is None else out

    def close(self):
        try:
            self.proc.stdout.close()
        except Exception:
            pass
        self.proc.kill()
        self.proc.wait()


class Compositor:
    def __init__(self, r: ResolvedEdit):
        import cv2

        self.cv2 = cv2
        self.r = r
        c = r.canvas
        self.W, self.H, self.fps = int(c["width"]), int(c["height"]), float(c["fps"])
        self.bg = c["background"]
        self.bg_rgb = _hex_rgb(self.bg["color"])
        self.readers: dict[str, ClipReader] = {}

    def _reader(self, clip: Clip) -> ClipReader:
        if clip.id not in self.readers:
            self.readers[clip.id] = ClipReader(clip)
        return self.readers[clip.id]

    def _background(self, frame: np.ndarray | None) -> np.ndarray:
        cv2 = self.cv2
        if self.bg["type"] == "blur_source" and frame is not None:
            small_w, small_h = max(2, self.W // 8), max(2, self.H // 8)
            fh, fw = frame.shape[:2]
            s = max(small_w / fw, small_h / fh)
            tmp = cv2.resize(frame, (max(1, int(round(fw * s))), max(1, int(round(fh * s)))), interpolation=cv2.INTER_AREA)
            y0 = (tmp.shape[0] - small_h) // 2
            x0 = (tmp.shape[1] - small_w) // 2
            tmp = tmp[y0:y0 + small_h, x0:x0 + small_w]
            tmp = cv2.GaussianBlur(tmp, (0, 0), max(0.5, float(self.bg["blur_sigma"]) / 8.0))
            return cv2.resize(tmp, (self.W, self.H), interpolation=cv2.INTER_LINEAR)
        out = np.empty((self.H, self.W, 3), np.uint8)
        out[:] = self.bg_rgb.astype(np.uint8)
        return out

    def clip_canvas(self, clip: Clip, t: float) -> np.ndarray:
        cv2 = self.cv2
        rd = self._reader(clip)
        u = t - clip.out_start
        s = src_time_at(clip, u)
        s = min(s, clip.src_out - 2 * EPS_T)
        fr = rd.frame_at(s)
        canvas = self._background(fr)
        R = clip.region
        rx, ry, rw, rh = int(round(R.x)), int(round(R.y)), int(round(R.w)), int(round(R.h))
        sc, tx, ty = src_to_region(clip, u)
        sx, sy = sc / rd.kx, sc / rd.ky
        M = np.array([[sx, 0.0, tx + 0.5 * sx - 0.5], [0.0, sy, ty + 0.5 * sy - 0.5]], np.float64)
        interp = cv2.INTER_CUBIC if max(sx, sy) > 1.05 else cv2.INTER_LINEAR
        reg = cv2.warpAffine(fr, M, (rw, rh), flags=interp, borderMode=cv2.BORDER_REPLICATE)
        # pixels whose centre falls outside the mapped source rectangle show the background
        x0 = tx
        x1 = tx + sx * rd.W
        y0 = ty
        y1 = ty + sy * rd.H
        cx0, cx1 = max(0, int(math.ceil(x0 - 0.5))), min(rw, int(math.floor(x1 - 0.5)) + 1)
        cy0, cy1 = max(0, int(math.ceil(y0 - 0.5))), min(rh, int(math.floor(y1 - 0.5)) + 1)
        dst = canvas[ry:ry + rh, rx:rx + rw]
        if cx1 > cx0 and cy1 > cy0:
            dst[cy0:cy1, cx0:cx1] = reg[cy0:cy1, cx0:cx1]
        return canvas

    def frame(self, n: int) -> np.ndarray:
        t = n / self.fps
        act = [c for c in self.r.clips if c.out_start - 1e-6 <= t < c.out_end - 1e-6]
        if not act:
            act = [self.r.clips[-1]] if t >= self.r.clips[-1].out_start else [self.r.clips[0]]
        if len(act) == 1:
            out = self.clip_canvas(act[0], t)
        else:
            a, b = act[-2], act[-1]
            d = max(1e-6, b.transition_in.dur)
            alpha = min(1.0, max(0.0, (t - b.out_start) / d))
            out = self.cv2.addWeighted(self.clip_canvas(a, t), 1.0 - alpha, self.clip_canvas(b, t), alpha, 0.0)
        for c in self.r.clips:
            tr = c.transition_in
            if tr.type == "flash" and tr.dur > 0 and abs(t - c.out_start) < tr.dur / 2.0:
                alpha = 1.0 - abs(t - c.out_start) / (tr.dur / 2.0)
                scope = getattr(tr, "scope", "region") or "region"
                if scope == "canvas":
                    rx, ry, rw, rh = 0, 0, self.W, self.H
                elif scope == "region":
                    R = c.region
                    rx, ry, rw, rh = int(round(R.x)), int(round(R.y)), int(round(R.w)), int(round(R.h))
                else:
                    raise RenderError(f"클립 {c.id}: flash scope {scope!r} 미지원(region|canvas)")
                reg = out[ry:ry + rh, rx:rx + rw].astype(np.float32)
                col = _hex_rgb(tr.color or "#FFFFFF")
                out[ry:ry + rh, rx:rx + rw] = np.clip(reg * (1 - alpha) + col * alpha + 0.5, 0, 255).astype(np.uint8)
        # release readers of finished clips
        for cid in list(self.readers):
            c = next(x for x in self.r.clips if x.id == cid)
            if t >= c.out_end + 1.0 / self.fps:
                self.readers.pop(cid).close()
        return out

    def close(self):
        for rd in self.readers.values():
            rd.close()
        self.readers.clear()


def render_video(r: ResolvedEdit, mix_wav: Path, out: Path) -> None:
    c = r.canvas
    W, H, fps = int(c["width"]), int(c["height"]), float(c["fps"])
    enc = c.get("encode") or {}
    n_frames = int(round(r.duration * fps))
    root = paths.project_root()
    ass_rel = r.ass_path
    fdir_rel = r.fonts_dir
    for rel in (ass_rel, fdir_rel):
        if not re.fullmatch(r"[A-Za-z0-9_./-]+", rel or ""):
            raise RenderError(f"필터 경로에 쓸 수 없는 문자: {rel}")
    vf = (f"[0:v]subtitles=filename={ass_rel}:fontsdir={fdir_rel},"
          "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p[v]")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp_out = out.with_name(out.stem + ".tmp.render.mp4")
    log = out.with_name(out.stem + ".ffmpeg.log")
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
           "-framerate", f"{fps:g}", "-i", "-", "-i", str(mix_wav), "-filter_complex", vf, "-map", "[v]", "-map", "1:a",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", str(enc.get("crf", 18)), "-pix_fmt", "yuv420p",
           "-r", f"{fps:g}", "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
           "-color_range", "tv", "-threads", _threads(),
           "-c:a", "aac", "-b:a", enc.get("audio_bitrate", "192k"), "-ar", "48000", "-ac", "2",
           "-movflags", "+faststart", "-t", f"{n_frames / fps:.6f}", str(tmp_out)]
    comp = Compositor(r)
    with open(log, "wb") as lf:
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=lf, cwd=str(root))
        try:
            for n in range(n_frames):
                fr = comp.frame(n)
                proc.stdin.write(np.ascontiguousarray(fr).tobytes())
            proc.stdin.close()
            rc = proc.wait()
        except BrokenPipeError:
            rc = proc.wait()
        finally:
            comp.close()
    if rc != 0:
        tail = log.read_text(errors="replace")[-2000:]
        raise RenderError(f"ffmpeg 인코딩 실패(rc={rc}):\n{tail}")
    os.replace(tmp_out, out)


def check_output_fonts(r: ResolvedEdit) -> dict:
    """Ask libass itself which face it selects for every caption style (no fallback allowed)."""
    from . import captions as cap_mod

    ass_txt = paths.absp(r.ass_path).read_text(encoding="utf-8")
    head = ass_txt.partition("[Events]")[0]
    expected = {}
    for ln in head.splitlines():
        if ln.startswith("Style:"):
            parts = ln.split(":", 1)[1].split(",")
            if parts[0].strip() != "deco":
                expected[parts[0].strip()] = parts[1].strip()
    return cap_mod.verify_libass_fonts(ass_txt, paths.absp(r.fonts_dir), expected)


def render(resolved: ResolvedEdit, *, allow_unmeasured: bool = False) -> Path:
    """Render the master MP4 (contract API). Writes build/{mix.wav, stems/*.wav, render_report.json}."""
    r = resolved
    production_gate(r, allow_unmeasured)
    build = paths.absp(f"episodes/{r.episode_id}/build")
    build.mkdir(parents=True, exist_ok=True)
    if not paths.absp(r.ass_path).is_file():
        raise RenderError(f"ASS 파일이 없습니다: {r.ass_path} (resolve 먼저)")
    t0 = now_iso()
    fontcheck = check_output_fonts(r)
    if not fontcheck["ok"]:
        bad = {k: v for k, v in fontcheck["styles"].items() if not v["ok"]}
        write_json(build / "fontcheck.json", fontcheck)
        raise RenderError("libass 가 요청한 글꼴을 쓰지 않음(대체 글꼴 사용 금지): " + json.dumps(bad, ensure_ascii=False)[:800])
    audio_rep = mix_audio(r, build)
    if audio_rep.get("errors") and r.mode == "production":
        write_json(build / "render_report.json", {
            "schema": "shortkit.render_report/1", "episode_id": r.episode_id, "started_at": t0, "finished_at": now_iso(),
            "status": "failed_audio", "output": None, "audio": audio_rep, "libass_fontcheck": fontcheck,
            "problems": list(audio_rep["errors"]), "mode": r.mode, "allow_unmeasured": allow_unmeasured})
        raise RenderError("production 렌더 거부(오디오): " + "; ".join(audio_rep["errors"]))
    out = paths.absp(r.output_path)
    render_video(r, build / "mix.wav", out)
    info = probe(out)
    W, H, fps = int(r.canvas["width"]), int(r.canvas["height"]), float(r.canvas["fps"])
    problems = []
    if (info.width, info.height) != (W, H):
        problems.append(f"해상도 {info.width}x{info.height} ≠ 프리셋 {W}x{H}")
    if info.fps is None or abs(info.fps - fps) > 0.01:
        problems.append(f"fps {info.fps} ≠ 프리셋 {fps}")
    if abs(info.duration - r.duration) > 1.5 / fps + 0.05:
        problems.append(f"길이 {info.duration:.3f}s ≠ 계획 {r.duration:.3f}s")
    mp4_loud = lufs(out)
    rep = {"schema": "shortkit.render_report/1", "episode_id": r.episode_id, "started_at": t0, "finished_at": now_iso(),
           "output": r.output_path, "sha256": sha256_file(out),
           "probe": {"width": info.width, "height": info.height, "fps": info.fps, "duration": info.duration,
                     "vcodec": info.vcodec, "acodec": info.acodec, "audio_rate": info.audio_rate,
                     "audio_channels": info.audio_channels},
           "expected": {"width": W, "height": H, "fps": fps, "duration": r.duration},
           "audio": audio_rep, "mp4_loudness": mp4_loud, "libass_fontcheck": fontcheck, "problems": problems, "mode": r.mode,
           "allow_unmeasured": allow_unmeasured, "provisional_keys_read": len(r.provisional_keys),
           "note": "이 수치는 기계 측정값이다. 사람이 직접 들어본 청취 확인은 포함되지 않는다."}
    write_json(build / "render_report.json", rep)
    if problems:
        raise RenderError("출력 검사 실패: " + "; ".join(problems))
    return out
