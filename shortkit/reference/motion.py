"""Editorial motion inside the footage region: zoom in/out, freeze frames, speed ramps (+ flashes
copied from shots.json).

Per consecutive frame pair (native rate, footage region at 320 px width, caption boxes masked):
  * similarity transform by ORB matches + RANSAC -> scale; zoom events are runs of same-sign
    per-frame scale change (>= 0.3 %/frame) totalling >= 5 %, or single-frame jumps >= 5 %
    ("punch-in").  Camera zooms inside the source cannot be told apart from editor zooms.
  * mean absolute gray difference -> freeze = run of (near) identical frames >= 0.25 s.
  * unique-frame rate (share of pairs that change) -> a speed ramp is a sustained change of that
    rate inside one shot (frame-duplication slow motion).  Optical-flow/blended slow motion is
    NOT detectable this way, so "no ramp found" is reported as unmeasured, never as absent.

Output ``analysis/<id>/motion.json`` (docs/CONTRACT.md section 11)::

    {"video_id", "resolution", "events": [{"t", "end", "type": "zoom_in|zoom_out|freeze|speed|flash",
     "value", ...}], "presence": {zoom|freeze|speed|flash: present|absent|unmeasured}}

``value``: zoom -> scale_to (relative to the zoom start), freeze -> hold_s, speed -> factor
(new/old playback speed), flash -> dur_s.

Zoom ramps also carry ``ease_fit`` (``fit_ease``: which renderer ease curve -- linear / in / out /
inout -- reproduces the measured scale curve, with the fitted start / duration) and
``recenter_fit`` (``classify_recenter``: does the zoom keep a fixed point inside the video region,
or does it travel toward the centre) for ``motion.zoom.ease`` / ``motion.zoom.recenter``.

``decorations`` (``detect_decorations``, EXPERIMENTAL): arrow / circle / box overlays with colour,
stroke / size / arrow ratios / outline and blink rate, in the video's own px -- read by
``shortkit.reference.manual`` (``decorations.*`` keys, a watched manual observation wins).
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import numpy as np

from ..util.jsonio import now_iso, read_json, write_json
from ..util.media import probe
from ..util.stats import tri_state
from .common import analysis_dir, hexrgb, iter_native, region_or_full

SCHEMA = "shortkit.ref_motion/1"
WIDTH = 320
METHOD = {
    "zoom": "ORB (600) + RANSAC similarity per frame pair in the footage region (captions masked); runs of "
            "same-sign scale change >= 0.3%/frame totalling >= 5%, or one-frame jumps >= 5%",
    "freeze": ">= 0.25 s of frames with <= 0.03% pixels changing by > 6 levels, with motion (>= 0.3% pixels) "
              "right before and after inside the same shot",
    "speed": "unique-frame rate change (>= 1.4x or <= 0.7x, sustained >= 0.4 s) inside one shot "
             "(frame-duplication slow/fast motion only)",
    "flash": "copied from shots.json (incl. scope: canvas | region)",
    "zoom_ease": "cumulative scale over the zoom run + up to 0.5 s of the same shot on each side, fitted with "
                 "c0 + A*ease((t-t0)/dur) for the renderer eases linear/in(u^3)/out(1-(1-u)^3)/inout (t0, dur on a "
                 "quarter-frame grid, c0/A least squares); named only if 2nd-best SSE >= 1.5x best and RMS <= 8% "
                 "of the amplitude",
    "zoom_recenter": "cumulative similarity transforms T_k vs (1 - z_k): pure zoom about an apparent fixed point "
                     "(drift <= 5% of the region's shorter side) inside the region -> stays (recenter false); fixed "
                     "point outside the region or drifting toward the centre -> moves (recenter true); zoom about "
                     "the centre (both modes identical) or other drift -> no observation",
    "frame_times": "frame index / fps (constant frame rate assumed)",
}


def _similarity(prev, cur, mask, orb, bf):
    import cv2
    k1, d1 = orb.detectAndCompute(prev, mask)
    k2, d2 = orb.detectAndCompute(cur, mask)
    if d1 is None or d2 is None or len(k1) < 12 or len(k2) < 12:
        return None
    m = bf.match(d1, d2)
    if len(m) < 12:
        return None
    p1 = np.float32([k1[x.queryIdx].pt for x in m])
    p2 = np.float32([k2[x.trainIdx].pt for x in m])
    M, inl = cv2.estimateAffinePartial2D(p1, p2, method=cv2.RANSAC, ransacReprojThreshold=2.0,
                                         maxIters=500, confidence=0.99)
    if M is None or inl is None:
        return None
    ni = int(inl.sum())
    if ni < 12 or ni < 0.3 * len(m):
        return None
    s = math.hypot(M[0, 0], M[1, 0])
    # fixed point of the transform = zoom center
    A = M[:, :2]
    tvec = M[:, 2]
    try:
        c = np.linalg.solve(np.eye(2) - A, tvec) if abs(s - 1) > 1e-3 else None
    except np.linalg.LinAlgError:
        c = None
    return {"s": s, "inliers": ni, "tx": float(M[0, 2]), "ty": float(M[1, 2]),
            "a": float(M[0, 0]), "b": float(M[1, 0]),
            "center": (float(c[0]), float(c[1])) if c is not None else None}


# ============================================================================= zoom ease / recenter
EASES = ("linear", "in", "out", "inout")
EASE_DECISIVE_RATIO = 1.5      # second-best SSE / best SSE needed to name an ease
EASE_MAX_REL_RMS = 0.08        # best-fit RMS residual / zoom amplitude
RECENTER_PURE_DRIFT = 0.05     # pure zoom: fixed-point drift <= 5 % of the region's shorter side
RECENTER_CENTRE_ZONE = 0.1     # |fixed point - region centre| <= 10 % of the shorter side: both modes identical
RECENTER_OUTSIDE_TOL = 0.03    # fixed point this far (share of the side) outside the region = outside
EASE_EXT_S = 0.5               # frames of the same shot added before / after a zoom run for the fits


def ease_curve(u, kind: str) -> np.ndarray:
    """Vectorised renderer ease (shortkit.edit.resolve.ease): linear = u, in = u^3,
    out = 1 - (1 - u)^3, inout = 4u^3 (u < 0.5) else 1 - (-2u + 2)^3 / 2; u clipped to [0, 1]."""
    u = np.clip(np.asarray(u, float), 0.0, 1.0)
    if kind == "in":
        return u ** 3
    if kind == "out":
        return 1.0 - (1.0 - u) ** 3
    if kind == "inout":
        return np.where(u < 0.5, 4.0 * u ** 3, 1.0 - (-2.0 * u + 2.0) ** 3 / 2.0)
    return u


def fit_ease(ts, zs, fps: float, sign: int = 0) -> dict | None:
    """Fit the cumulative zoom scale curve z(t) = c0 + A * ease((t - t0) / dur) for every renderer
    ease (grid over t0 / dur on a quarter-frame grid, c0 / A by least squares; the zoom must
    start and finish inside the window).  The ease is named only when the best curve beats the
    second best by ``EASE_DECISIVE_RATIO`` in SSE and fits within ``EASE_MAX_REL_RMS`` of the
    amplitude; otherwise ``ease`` is None (unmeasured for this event)."""
    ts = np.asarray(ts, float)
    zs = np.asarray(zs, float)
    n = len(ts)
    if n < 6:
        return None
    step = 1.0 / (4.0 * fps)
    lo, hi = ts[0] - 1.0 / fps, ts[-1] + 1.0 / fps
    a_grid = np.arange(lo, ts[-1], step)
    d_grid = np.arange(2.0 / fps, (hi - lo) + step, step)
    zc = zs - zs.mean()
    sst = float((zc ** 2).sum())
    if sst <= 0:
        return None
    per: dict[str, tuple] = {}
    for kind in EASES:
        best = None
        for a in a_grid:
            ok_d = d_grid[a + d_grid <= hi + 1e-9]
            if not len(ok_d):
                continue
            E = ease_curve((ts[None, :] - a) / ok_d[:, None], kind)
            Em = E.mean(axis=1, keepdims=True)
            Ec = E - Em
            var = (Ec ** 2).sum(axis=1)
            cov = (Ec * zc[None, :]).sum(axis=1)
            sse = np.full(len(ok_d), np.inf)
            good = var > 1e-12
            if sign:
                good &= np.sign(cov) == sign
            sse[good] = sst - cov[good] ** 2 / var[good]
            k = int(np.argmin(sse))
            if np.isfinite(sse[k]) and (best is None or sse[k] < best[0]):
                A = float(cov[k] / var[k])
                c0 = float(zs.mean() - A * Em[k, 0])
                best = (max(0.0, float(sse[k])), float(a), float(ok_d[k]), A, c0)
        if best is not None:
            per[kind] = best
    if not per:
        return None
    order = sorted(per, key=lambda k: per[k][0])
    b = per[order[0]]
    sse_b = b[0]
    sse_2 = per[order[1]][0] if len(order) > 1 else float("inf")
    ratio = (sse_2 / sse_b) if sse_b > 1e-12 else float("inf")
    amp = abs(b[3])
    rms = math.sqrt(sse_b / n)
    decided = ratio >= EASE_DECISIVE_RATIO and amp > 0 and rms <= EASE_MAX_REL_RMS * amp
    return {"ease": order[0] if decided else None, "best": order[0], "t0": round(b[1], 4), "dur_s": round(b[2], 4),
            "scale_from": round(b[4], 4), "scale_to": round((b[4] + b[3]) / b[4], 4) if b[4] else None,
            "rms": round(rms, 5), "rel_rms": round(rms / amp, 4) if amp else None,
            "sse_ratio_2nd_best": round(ratio, 3) if math.isfinite(ratio) else None,
            "sse": {k: round(v[0], 7) for k, v in per.items()}, "n_points": n,
            "note": None if decided else "ease 곡선끼리 구분이 뚜렷하지 않음(잡음·짧은 구간) → 이 사건은 못 잼"}


def _window_transforms(stats: list[dict], i0: int, i1: int) -> tuple[list[float], list[np.ndarray]]:
    """Cumulative similarity transforms (3x3, analysis px) from the frame before stats[i0] to each
    frame of stats[i0..i1].  A frame pair without a transform takes the mean of its nearest
    available neighbours inside the window (identity when there are none)."""
    params = []
    for k in range(i0, i1 + 1):
        s_ = stats[k]["sim"]
        params.append(None if not s_ or s_.get("a") is None else
                      np.array([math.log(max(1e-6, s_["s"])), math.atan2(s_["b"], s_["a"]), s_["tx"], s_["ty"]]))
    filled = []
    for q, p in enumerate(params):
        if p is not None:
            filled.append(p)
            continue
        prv = next((params[r] for r in range(q - 1, -1, -1) if params[r] is not None), None)
        nxt = next((params[r] for r in range(q + 1, len(params)) if params[r] is not None), None)
        nb = [x for x in (prv, nxt) if x is not None]
        filled.append(np.mean(nb, axis=0) if nb else np.zeros(4))
    C = np.eye(3)
    times = [stats[i0]["t"] - (stats[i0 + 1]["t"] - stats[i0]["t"] if i1 > i0 else 0.0)]
    mats = [C.copy()]
    for q, p in enumerate(filled):
        s_, th, tx, ty = math.exp(p[0]), p[1], p[2], p[3]
        M = np.array([[s_ * math.cos(th), -s_ * math.sin(th), tx], [s_ * math.sin(th), s_ * math.cos(th), ty],
                      [0.0, 0.0, 1.0]])
        C = M @ C
        times.append(stats[i0 + q]["t"])
        mats.append(C.copy())
    return times, mats


def classify_recenter(mats: list[np.ndarray], sc: float, reg: dict) -> dict:
    """Does the zoom keep a fixed point on screen, or does the zoom target travel to the centre?

    The renderer's recenter=false zoom is a pure zoom about a fixed point clamped INSIDE the video
    region.  Its recenter=true zoom moves the target to the region centre with the same eased
    progress as the scale, which is again a pure zoom -- but about the apparent point
    C + (p - C) * S / (S - 1), i.e. OUTSIDE the region unless the target p is near the centre
    (and cover-fit clamping can pin it to an edge).  Per event (cumulative transforms T_k vs
    (1 - z_k)): a pure zoom with its fixed point inside the region and away from the centre ->
    ``stays`` (recenter false reproduces it exactly); a fixed point outside the region, or one that
    drifts toward the centre -> ``moves`` (recenter true); a zoom about the centre (both modes
    identical) or any other drift -> ``centre`` / ``ambiguous`` (no observation)."""
    zs = np.array([math.hypot(M[0, 0], M[1, 0]) for M in mats])
    T = np.array([[M[0, 2], M[1, 2]] for M in mats])
    w = 1.0 - zs
    den = float((w ** 2).sum())
    side = min(reg["w"], reg["h"])
    cx, cy = reg["x"] + reg["w"] / 2.0, reg["y"] + reg["h"] / 2.0
    if den < 1e-8 or abs(w).max() < 0.02:
        return {"recenter": None, "class": "ambiguous", "note": "배율 변화가 너무 작음"}
    p = (w[:, None] * T).sum(axis=0) / den                     # apparent fixed point, analysis px
    res = T - w[:, None] * p[None, :]
    drift = float(np.sqrt((res ** 2).sum(axis=1).mean()) / abs(w).max()) / sc   # canvas px
    pc = [float(p[0] / sc + reg["x"]), float(p[1] / sc + reg["y"])]
    out = {"fixed_point": [round(pc[0], 1), round(pc[1], 1)], "drift_px": round(drift, 2),
           "region_centre": [round(cx, 1), round(cy, 1)]}
    tol = RECENTER_OUTSIDE_TOL * side
    inside = (reg["x"] - tol <= pc[0] <= reg["x"] + reg["w"] + tol) and \
        (reg["y"] - tol <= pc[1] <= reg["y"] + reg["h"] + tol)
    dist_c = math.hypot(pc[0] - cx, pc[1] - cy)
    if drift <= RECENTER_PURE_DRIFT * side:
        if not inside:
            out.update(recenter=True, **{"class": "moves"},
                       note="순수 확대지만 고정점이 영상 영역 밖 → recenter=false(고정점을 영역 안으로 제한)로는 재현 불가")
        elif dist_c <= RECENTER_CENTRE_ZONE * side:
            out.update(recenter=None, **{"class": "centre"}, note="화면 중앙 근처를 확대 → 두 방식 결과가 같아 판정 불가")
        else:
            out.update(recenter=False, **{"class": "stays"}, note="고정점이 영역 안에서 제자리 → recenter=false 로 그대로 재현")
        return out
    # the fixed point moves: estimate it per frame where the scale change is large enough
    big = abs(w) >= 0.3 * abs(w).max()
    fk = [(T[k] / w[k]) / sc + np.array([reg["x"], reg["y"]]) for k in range(len(w)) if big[k]]
    if len(fk) >= 3:
        d0 = math.hypot(fk[0][0] - cx, fk[0][1] - cy)
        d1 = math.hypot(fk[-1][0] - cx, fk[-1][1] - cy)
        out["fixed_point_path"] = [[round(float(f[0]), 1), round(float(f[1]), 1)] for f in (fk[0], fk[-1])]
        if d0 - d1 >= RECENTER_CENTRE_ZONE * side:
            out.update(recenter=True, **{"class": "moves"}, note="확대 중 고정점이 화면 중심 쪽으로 이동")
            return out
    out.update(recenter=None, **{"class": "ambiguous"}, note="고정점이 움직이지만 중심 쪽 이동이 아님(이동+확대) → 판정 불가")
    return out


def analyze(video: str | Path, video_id: str, preset: str | None = None, region: dict | None = None,
            out_dir: Path | None = None, shots: dict | None = None, captions: dict | None = None,
            max_seconds: float | None = None, decorations: bool = True) -> dict:
    import cv2

    video = Path(video)
    info = probe(video)
    W, H = int(info.width), int(info.height)
    fps = float(info.fps or 30.0)
    d = Path(out_dir) if out_dir is not None else analysis_dir(preset, video_id)
    shots = shots if shots is not None else (read_json(d / "shots.json") or {})
    captions = captions if captions is not None else (read_json(d / "captions.json") or {})
    reg = region_or_full(region, W, H)
    sc = WIDTH / reg["w"]
    # boundaries: pairs across cuts / inside flashes and crossfades are not analysed
    excl: list[tuple[float, float]] = []
    for c in shots.get("cuts") or []:
        t = float(c["t"])
        dur = float(c.get("dur") or 0.0)
        excl.append((t - 1.5 / fps, t + dur + 1.5 / fps))
    mask = None
    stats = []
    orb = cv2.ORB_create(nfeatures=600, fastThreshold=12)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    prev = None
    for t, fr in iter_native(video, fps, crop=reg, width=WIDTH, gray=True, max_seconds=max_seconds):
        if mask is None:
            mask = np.full(fr.shape, 255, np.uint8)
            for it in captions.get("items") or []:
                x, y, w, h = it["bbox"]
                mx, my = 0.25 * w + 4 / sc, 0.25 * h + 4 / sc     # pop / slide animations overshoot the rest box
                x0, y0 = int((x - mx - reg["x"]) * sc), int((y - my - reg["y"]) * sc)
                x1, y1 = int((x + w + mx - reg["x"]) * sc), int((y + h + my - reg["y"]) * sc)
                if x1 > 0 and y1 > 0 and x0 < fr.shape[1] and y0 < fr.shape[0]:
                    mask[max(0, y0):y1, max(0, x0):x1] = 0
        g = fr
        if prev is not None:
            skip = any(a <= t <= b for a, b in excl)
            dd = np.abs(g.astype(np.int16) - prev.astype(np.int16))
            dd[mask == 0] = 0          # caption animations are not footage motion
            diff = float(dd.mean())
            changed = int((dd > 6).sum())
            sim = None if skip else _similarity(prev, g, mask, orb, bf)
            stats.append({"t": t, "diff": diff, "changed": changed, "npix": int(dd.size), "skip": skip, "sim": sim})
        prev = g
    n = len(stats)
    duration = (n + 1) / fps
    events: list[dict] = []
    # ------------------------------------------------------------------ zoom
    logs = [math.log(s["sim"]["s"]) if s["sim"] else None for s in stats]
    analysable = sum(1 for s in stats if s["sim"] is not None)
    i = 0
    while i < n:
        lg = logs[i]
        if lg is None or abs(lg) < 0.003:
            i += 1
            continue
        sign = 1 if lg > 0 else -1
        j = i
        total = lg
        gaps = 0
        while j + 1 < n:
            nx = logs[j + 1]
            if nx is not None and nx * sign >= 0.003:
                j += 1
                total += nx
                gaps = 0
            elif gaps == 0 and j + 2 < n and logs[j + 2] is not None and logs[j + 2] * sign >= 0.003:
                j += 1
                gaps = 1
            else:
                break
        if abs(total) >= math.log(1.05):
            t0 = stats[i]["t"] - 1.0 / fps          # the frame before the first scaled frame
            t1 = stats[j]["t"]
            centers = [stats[k]["sim"]["center"] for k in range(i, j + 1)
                       if stats[k]["sim"] and stats[k]["sim"]["center"]]
            ctr = None
            if centers:
                cx = float(np.median([c[0] for c in centers])) / sc + reg["x"]
                cy = float(np.median([c[1] for c in centers])) / sc + reg["y"]
                ctr = [round(cx, 1), round(cy, 1)]
            st = math.exp(total)
            ev_z = {"t": round(t0, 3), "end": round(t1, 3), "type": "zoom_in" if sign > 0 else "zoom_out",
                    "value": round(st, 4), "scale_from": 1.0, "scale_to": round(st, 4),
                    "dur_s": round(t1 - t0, 3), "center": ctr, "frames": j - i + 1,
                    "kind": "punch" if j == i else "ramp"}
            if j > i:
                # fitting window: the run plus up to EASE_EXT_S of the same shot on each side, so
                # the slow start / end of an eased zoom (below the run threshold) is included
                ext = max(2, int(round(EASE_EXT_S * fps)))
                i0, i1 = i, j
                while i0 - 1 >= 0 and i - i0 < ext and not stats[i0 - 1]["skip"]:
                    i0 -= 1
                while i1 + 1 < n and i1 - j < ext and not stats[i1 + 1]["skip"]:
                    i1 += 1
                times, mats = _window_transforms(stats, i0, i1)
                zs = [math.hypot(M[0, 0], M[1, 0]) for M in mats]
                fit = fit_ease(times, zs, fps, sign=sign)
                ev_z["ease_fit"] = fit
                ev_z["scale_curve"] = [[round(tt, 4), round(zz, 5)] for tt, zz in zip(times, zs)]
                ev_z["recenter_fit"] = classify_recenter(mats, sc, reg)
            events.append(ev_z)
        i = j + 1
    # ------------------------------------------------------------------ freeze
    # frozen pair = (almost) no pixel changes by more than 6 levels; an editorial freeze must be
    # bounded by visible motion inside the same shot (a still scene is not a freeze)
    shot_ranges = [(float(s_["start"]), float(s_["end"])) for s_ in shots.get("shots") or []] or [(0.0, duration)]
    npix = stats[0]["npix"] if stats else 1
    still_thr = max(3, int(0.0003 * npix))
    move_thr = max(30, int(0.003 * npix))
    frozen = np.array([(not s_["skip"]) and s_["changed"] <= still_thr for s_ in stats], bool)

    def shot_of(t):
        for a_, b_ in shot_ranges:
            if a_ - 1e-6 <= t < b_ + 1e-6:
                return (a_, b_)
        return None

    k = 0
    freeze_runs = []
    rejected_still = 0
    while k < n:
        if frozen[k]:
            j = k
            while j + 1 < n and frozen[j + 1]:
                j += 1
            hold = (j - k + 1) / fps
            if hold >= 0.25:
                sh = shot_of(stats[k]["t"])
                before = [stats[q]["changed"] for q in range(max(0, k - 3), k) if not stats[q]["skip"]
                          and sh and sh[0] <= stats[q]["t"]]
                after = [stats[q]["changed"] for q in range(j + 1, min(n, j + 4)) if not stats[q]["skip"]
                         and sh and stats[q]["t"] < sh[1]]
                if before and after and max(before) >= move_thr and max(after) >= move_thr:
                    t0 = stats[k]["t"] - 1.0 / fps
                    events.append({"t": round(stats[k]["t"], 3), "end": round(stats[j]["t"] + 1.0 / fps, 3),
                                   "type": "freeze", "value": round(hold, 3), "hold_s": round(hold, 3),
                                   "held_frame_t": round(t0, 3)})
                    freeze_runs.append((k, j))
                else:
                    rejected_still += 1
            k = j + 1
        else:
            k += 1
    # ------------------------------------------------------------------ speed ramps
    in_freeze = np.zeros(n, bool)
    for a, b in freeze_runs:
        in_freeze[a:b + 1] = True
    win = max(4, int(round(0.5 * fps)))
    speed_checked = 0
    for a, b in shot_ranges:
        idx = [k for k in range(n) if a <= stats[k]["t"] < b and not stats[k]["skip"] and not in_freeze[k]]
        if len(idx) < 2 * win + 2:
            continue
        speed_checked += 1
        # 1 = clearly new frame (visible motion), 0 = duplicate, NaN = too little motion to tell
        # (a still scene is not frame duplication)
        u = np.array([1.0 if stats[k]["changed"] >= move_thr else (0.0 if stats[k]["changed"] <= still_thr else np.nan)
                      for k in idx])
        ts = np.array([stats[k]["t"] for k in idx])
        best = None

        def wmean(x):
            ok = ~np.isnan(x)
            return float(x[ok].mean()) if ok.sum() >= 0.6 * len(x) else None

        for p in range(win, len(u) - win + 1):
            left, right = wmean(u[p - win:p]), wmean(u[p:p + win])
            if not left or not right:
                continue
            ratio = right / left
            if (ratio <= 0.7 or ratio >= 1.43) and abs(right - left) >= 0.25:
                # sustained: the new rate holds until the shot end / at least 0.4 s
                hold = wmean(u[p:]) if len(u) - p < 2 * win else wmean(u[p:p + 2 * win])
                if hold is None or abs(hold / left - ratio) > 0.25:
                    continue
                score = abs(math.log(ratio))
                if best is None or score > best[0] + 1e-9:
                    best = (score, p, ratio)
        if best:
            _, p, ratio = best
            # align to the first changed-rate frame
            t0 = float(ts[p]) - 1.0 / fps
            events.append({"t": round(t0, 3), "end": round(b, 3), "type": "speed", "value": round(float(ratio), 3),
                           "factor": round(float(ratio), 3), "method": "unique-frame rate (frame duplication)"})
    # ------------------------------------------------------------------ flashes
    for c in shots.get("cuts") or []:
        if c.get("type") == "flash":
            events.append({"t": c["t"], "end": round(float(c["t"]) + float(c.get("dur") or 0), 3), "type": "flash",
                           "value": c.get("dur"), "dur_s": c.get("dur"), "color": c.get("color"),
                           "scope": (c.get("scope") or {}).get("value")})
    events.sort(key=lambda e: e["t"])
    cover = analysable / max(1, sum(1 for s in stats if not s["skip"]))
    presence = {
        "zoom": tri_state([any(e["type"].startswith("zoom") for e in events)]) if cover >= 0.5 or
        any(e["type"].startswith("zoom") for e in events) else "unmeasured",
        "freeze": tri_state([any(e["type"] == "freeze" for e in events)]) if n else "unmeasured",
        "speed": "present" if any(e["type"] == "speed" for e in events) else "unmeasured",
        "flash": (shots.get("presence") or {}).get("flash", "unmeasured"),
    }
    res = {"schema": SCHEMA, "video_id": video_id, "resolution": [W, H], "fps": fps, "duration": round(duration, 3),
           "region_used": reg, "analysis_width": WIDTH, "method": METHOD, "analyzed_at": now_iso(),
           "zoom_analysable_share": round(cover, 3), "still_runs_not_freeze": rejected_still,
           "events": events, "presence": presence,
           "speed_shots_checked": speed_checked,
           "presence_note": "speed 는 프레임 복제 방식만 검출 가능 → 못 찾으면 '없다'가 아니라 '못 잼'"}
    if decorations:
        res["decorations"] = detect_decorations(video, captions=captions, max_seconds=max_seconds)
    write_json(d / "motion.json", res)
    return res


# ============================================================================= decorations (automatic)
# Arrow / circle / box overlays (preset ``decorations.*``).  EXPERIMENTAL: validated only on
# decorations drawn by our own renderer (tests/reference_visual/mockfx.py); on reference videos
# every detection must be confirmed by someone who watched it (manual_observations.csv).
DECO_WIDTH = 270                 # detection width of the per-frame pass (px)
DECO_SAT = 0.6 * 255             # vivid fill: HSV S >= 0.6 ...
DECO_VAL = 0.6 * 255             # ... and V >= 0.6 (dark / muted saturated footage is not a decoration)
DECO_MIN_AREA_SHARE = 0.0002     # component area / frame area (detection width)
DECO_MIN_SIZE_SHARE = 0.07       # shape's larger bbox side / frame width
DECO_MIN_VISIBLE_S = 0.4         # visible at least this long in total
ARROW_RATIO_RANGE = {"head_len_ratio": (0.15, 0.7), "head_width_ratio": (0.25, 1.2), "shaft_width_ratio": (0.05, 0.6)}
DECO_MAX_GAP_S = 1.0             # off-runs up to this long inside one decoration = blinking
DECO_FLAT_STD = 14.0             # drawn fill: interior colour std (mean over channels, full res)
DECO_METHOD = {
    "detection": f"per native frame at {DECO_WIDTH} px width: HSV S>=0.6, V>=0.6 pixels outside the caption boxes "
                 "(captions.json, padded) -> connected components per 30-degree hue bin, tracked by bbox IoU "
                 f"(>=0.5 frame to frame, >=0.7 across gaps <= {DECO_MAX_GAP_S} s) and colour (RGB distance <= 45); kept when visible >= "
                 f"{DECO_MIN_VISIBLE_S} s, >= {int(DECO_MIN_SIZE_SHARE * 100)}% of the frame width, popping in at "
                 ">= 60% of its size, not part of a text-like row of same-colour components",
    "measurement": "one native full-resolution frame in the middle of the longest visible run: fill mask (saturated, "
                   f"colour within 60 of the track colour); interior colour std <= {DECO_FLAT_STD} (flat drawn fill) "
                   "else rejected; ring (hole >= 20% of the outer area) -> box (4-vertex polygon, rectangularity "
                   ">= 0.9) or circle (ellipse fit area ratio 0.92-1.08); solid with 2 convexity defects deeper "
                   "than 6% of the length and plausible ratios (head length 0.15-0.7, head width 0.25-1.2, shaft "
                   "0.05-0.6 of the length) -> arrow: principal axis width profile -> length (size_px), head length / "
                   "head width / shaft width ratios, outline = sum over distance rings outside the fill of the share "
                   "of outline-coloured pixels",
    "coverage": "sizes / strokes / widths use sub-pixel fill coverage (pixel colour projected between the inpainted "
                "local background and the fill colour), ring stroke from the soft area and the outer size "
                "(renderer geometry: inner = outer - 2 x stroke)",
    "blink": "visibility per native frame between first and last appearance (1-frame gaps filled): >= 2 visible runs "
             "-> blink_hz = 1 / mean spacing of the visible-run starts, duty = on share; one run -> blink_hz 0",
    "coordinates": "video px of the analysed file (resolution stored with the result)",
    "validation": "synthetic renderer-drawn mocks only (tests/reference_visual/mockfx.py) — not validated on "
                  "reference videos",
}


def _iou_xywh(a, b) -> float:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    ix = max(0.0, min(ax + aw, bx + bw) - max(ax, bx))
    iy = max(0.0, min(ay + ah, by + bh) - max(ay, by))
    inter = ix * iy
    u = aw * ah + bw * bh - inter
    return inter / u if u > 0 else 0.0


def _caption_rects(captions: dict | None) -> list[tuple[float, float, float, float, float, float]]:
    """(start, end, x0, y0, x1, y1) video px of every caption (ink U box), padded for pop overshoot."""
    out = []
    for it in (captions or {}).get("items") or []:
        if not it.get("bbox"):
            continue
        x, y, w, h = it["bbox"]
        x0, y0, x1, y1 = x, y, x + w, y + h
        bx = ((it.get("style") or {}).get("box") or {})
        if bx.get("present") == "present" and bx.get("bbox"):
            X, Y, BW, BH = bx["bbox"]
            x0, y0, x1, y1 = min(x0, X), min(y0, Y), max(x1, X + BW), max(y1, Y + BH)
        m = 0.25 * (y1 - y0) + 4
        out.append((float(it.get("start", 0.0)) - 0.1, float(it.get("end", 1e9)) + 0.1, x0 - m, y0 - m, x1 + m, y1 + m))
    return out


def _deco_components(fr: np.ndarray, rects: list, k: float, min_area: int) -> list[dict]:
    """Saturated components per hue bin (12 bins of 30 degrees centred on red/yellow/green/cyan/blue/
    magenta and their midpoints), so a decoration never merges with a saturated background of
    another hue.  Colour = mean RGB of the component."""
    import cv2
    hsv = cv2.cvtColor(fr, cv2.COLOR_RGB2HSV)
    sat = (hsv[..., 1] >= DECO_SAT) & (hsv[..., 2] >= DECO_VAL)
    for x0, y0, x1, y1 in rects:
        ya, yb = max(0, int(y0 * k)), max(0, int(math.ceil(y1 * k)))
        xa, xb = max(0, int(x0 * k)), max(0, int(math.ceil(x1 * k)))
        sat[ya:yb, xa:xb] = False
    if int(sat.sum()) < min_area:
        return []
    hb = ((hsv[..., 0].astype(np.int16) + 7) // 15) % 12
    counts = np.bincount(hb[sat].ravel(), minlength=12)
    out = []
    for b in np.nonzero(counts >= min_area)[0]:
        m = (sat & (hb == b)).astype(np.uint8)
        n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        keep = [q for q in range(1, n) if st[q, cv2.CC_STAT_AREA] >= min_area]
        if not keep:
            continue
        flat = lab.ravel()
        cnt = np.maximum(np.bincount(flat, minlength=n), 1)
        means = np.stack([np.bincount(flat, weights=fr[..., c].ravel().astype(np.float64), minlength=n) / cnt
                          for c in range(3)], axis=1)
        for q in keep:
            x, y, w, h, a = (int(v) for v in st[q])
            out.append({"bbox": (x, y, w, h), "area": a, "color": means[q], "hue_bin": int(b)})
    return out


def _text_like(c: dict, comps: list[dict]) -> bool:
    """A component in a row of >= 2 same-colour components of similar height = a line of text."""
    x, y, w, h = c["bbox"]
    nb = 0
    for o in comps:
        if o is c:
            continue
        ox, oy, ow, oh = o["bbox"]
        if np.linalg.norm(o["color"] - c["color"]) > 45 or not (0.5 * h <= oh <= 2.0 * h):
            continue
        vov = min(y + h, oy + oh) - max(y, oy)
        gap = max(ox - (x + w), x - (ox + ow))
        if vov >= 0.5 * min(h, oh) and gap < 1.5 * h:
            nb += 1
    return nb >= 2


def _runs(on: list[bool]) -> list[tuple[bool, int]]:
    out: list[tuple[bool, int]] = []
    for v in on:
        if out and out[-1][0] == v:
            out[-1] = (v, out[-1][1] + 1)
        else:
            out.append((v, 1))
    return out


def blink_from_presence(on: list[bool], fps: float) -> dict:
    """blink_hz / duty from a per-frame visibility series (first and last entries visible).
    Period = spacing of the visible-run starts over the whole series (robust to the +-1 frame
    rounding of individual runs); duty = median visible share of each on+off cycle."""
    on = list(on)
    for q in range(1, len(on) - 1):          # 1-frame dropouts are detection noise, not blinking
        if not on[q] and on[q - 1] and on[q + 1]:
            on[q] = True
    runs = _runs(on)
    starts, pos = [], 0
    for v, n_ in runs:
        if v:
            starts.append(pos)
        pos += n_
    if len(starts) < 2:
        return {"blink_hz": 0.0, "duty": 1.0, "visible_runs": len(starts)}
    per = (starts[-1] - starts[0]) / (len(starts) - 1) / fps
    duty = float(np.median([runs[q][1] / (runs[q][1] + runs[q + 1][1]) for q in range(0, len(runs) - 1)
                            if runs[q][0] and not runs[q + 1][0]]))
    return {"blink_hz": round(1.0 / per, 3) if per > 0 else None, "duty": round(duty, 3), "visible_runs": len(starts),
            "period_s": round(per, 4)}


def _fill_mask(crop: np.ndarray, color: np.ndarray) -> np.ndarray:
    """Strict fill mask: saturated pixels within RGB distance 60 of the track colour (largest component)."""
    import cv2
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV)
    m = (hsv[..., 1] >= DECO_SAT) & (hsv[..., 2] >= DECO_VAL) & \
        (np.linalg.norm(crop.astype(np.float32) - color[None, None, :], axis=2) <= 60)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    if n <= 1:
        return np.zeros(m.shape, np.uint8)
    q = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
    return (lab == q).astype(np.uint8)


def _coverage(crop: np.ndarray, strict: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Sub-pixel fill coverage alpha in [0, 1]: each pixel within 2 px of the strict mask is projected
    on the line from the local background (inpainted from the pixels just outside that band) to
    the fill colour -- anti-aliasing and chroma blur then count as partial coverage instead of
    being cut by a threshold.  Returns (alpha, mask50, fill_rgb)."""
    import cv2
    k3 = np.ones((3, 3), np.uint8)
    core = cv2.erode(strict, k3)
    F = np.median(crop[core.astype(bool)] if core.sum() >= 20 else crop[strict.astype(bool)], axis=0).astype(np.float64)
    band = cv2.dilate(strict, k3, iterations=2)
    bg = cv2.inpaint(crop, band, 3, cv2.INPAINT_TELEA).astype(np.float64)
    d = F[None, None, :] - bg
    den = (d * d).sum(axis=2)
    num = ((crop.astype(np.float64) - bg) * d).sum(axis=2)
    alpha = np.where(den >= 30.0 ** 2, np.clip(num / np.maximum(den, 1.0), 0.0, 1.0), strict.astype(np.float64))
    alpha[band == 0] = 0.0
    m50 = (alpha >= 0.5).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m50, connectivity=8)
    if n > 1:
        q = 1 + int(np.argmax(st[1:, cv2.CC_STAT_AREA]))
        m50 = (lab == q).astype(np.uint8)
        alpha[cv2.dilate(m50, k3, iterations=2) == 0] = 0.0
    return alpha, m50, F


def _outline(crop: np.ndarray, mask: np.ndarray, length: float) -> tuple[float | None, str | None]:
    """Outline around a filled shape: sum over 1-px distance rings (exact Euclidean distance from
    the fill) of the share of pixels close to the outline colour (the ring 2-3 px out)."""
    import cv2
    dist = cv2.distanceTransform((1 - mask).astype(np.uint8), cv2.DIST_L2, cv2.DIST_MASK_PRECISE)
    ring2 = (dist >= 2) & (dist < 3)
    if ring2.sum() < 20:
        return None, None
    oc = np.median(crop[ring2].astype(np.float32), axis=0)
    maxd = int(max(4, 0.3 * length))
    shares = []
    for dd in range(1, maxd + 1):
        ring = (dist > dd - 0.5) & (dist <= dd + 0.5)
        if ring.sum() < 10:
            break
        shares.append(float((np.linalg.norm(crop[ring].astype(np.float32) - oc, axis=1) <= 60).mean()))
        if dd >= 2 and shares[-1] < 0.3:
            break                                 # the outline ended (the partial ring is counted)
    if len(shares) < 3 or shares[1] < 0.8:
        return 0.0, None                          # no consistent colour right outside the fill
    if shares[-1] >= 0.3:
        return None, None                         # never ends: outline indistinguishable from background
    return round(float(sum(shares)), 2), hexrgb(oc)


def _ring_stroke(area: float, a: float, b: float, kind: str) -> float | None:
    """Stroke width from the soft ring area and the outer size (a, b): box A = 2s(a+b) - 4s^2,
    ellipse A = pi/4 (2s(a+b) - 4s^2) (renderer: inner size = outer - 2 stroke)."""
    k = area if kind == "box" else 4.0 * area / math.pi
    disc = (a + b) ** 2 - 4.0 * k
    if disc < 0:
        return None
    return ((a + b) - math.sqrt(disc)) / 4.0


def _shape_measure(crop: np.ndarray, alpha: np.ndarray, mask: np.ndarray) -> dict:
    import cv2
    cs, hier = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_NONE)
    if not cs:
        return {"kind": None, "reason": "윤곽 없음"}
    hier = hier[0]
    outer_i = max((q for q in range(len(cs)) if hier[q][3] == -1), key=lambda q: cv2.contourArea(cs[q]))
    outer = cs[outer_i]
    a_out = float(cv2.contourArea(outer))
    holes = [q for q in range(len(cs)) if hier[q][3] == outer_i]
    hole = max(holes, key=lambda q: cv2.contourArea(cs[q])) if holes else None
    per_o = float(cv2.arcLength(outer, True))
    (_, _), (rw, rh), _ = cv2.minAreaRect(outer)
    rect_area = max(1.0, rw * rh)
    soft_area = float(alpha.sum())
    out: dict[str, Any] = {}
    if hole is not None and cv2.contourArea(cs[hole]) >= 0.2 * a_out:
        approx = cv2.approxPolyDP(outer, 0.02 * per_o, True)
        rectangularity = a_out / rect_area
        out["rectangularity"] = round(rectangularity, 3)
        # contours run through the outermost mask pixel centres: +1 px restores the outer edges
        if len(approx) == 4 and rectangularity >= 0.9:
            a_, b_ = max(rw, rh) + 1.0, min(rw, rh) + 1.0
            st = _ring_stroke(soft_area, a_, b_, "box")
            out.update(kind="box", stroke_px=round(st, 2) if st else None, outer_size=[round(a_, 1), round(b_, 1)])
            return out
        if len(outer) >= 5:
            (_, _), (ea, eb), _ = cv2.fitEllipse(outer)
            ratio = a_out / max(1.0, math.pi / 4.0 * ea * eb)
            out["ellipse_area_ratio"] = round(ratio, 3)
            if 0.92 <= ratio <= 1.08:
                a_, b_ = max(ea, eb) + 1.0, min(ea, eb) + 1.0
                st = _ring_stroke(soft_area, a_, b_, "circle")
                out.update(kind="circle", stroke_px=round(st, 2) if st else None,
                           outer_size=[round(a_, 1), round(b_, 1)])
                return out
        out.update(kind=None, reason="고리 모양이지만 원·상자 어느 쪽도 아님")
        return out
    # solid: arrow?
    L = max(rw, rh)
    hull = cv2.convexHull(outer, returnPoints=False)
    try:
        defects = cv2.convexityDefects(outer, hull)
    except cv2.error:
        defects = None
    dfs = np.zeros((0, 4)) if defects is None else np.asarray(defects).reshape(-1, 4)
    deep = [float(dd[3]) / 256.0 for dd in dfs if dd[3] / 256.0 >= 0.06 * L]
    out["deep_defects"] = len(deep)
    if len(deep) != 2:
        out.update(kind=None, reason=f"속이 찬 도형, 깊은 오목점 {len(deep)}개(화살표는 2개)")
        return out
    ys, xs = np.nonzero(mask)
    P = np.stack([xs, ys], axis=1).astype(np.float64) + 0.5
    mu = P.mean(axis=0)
    _, _, vt = np.linalg.svd(P - mu, full_matrices=False)
    v = vt[0]
    ya, xa = np.nonzero(alpha > 0)
    A = alpha[ya, xa]
    Q = np.stack([xa, ya], axis=1).astype(np.float64) + 0.5
    s_ = (Q - mu) @ v
    s50 = (P - mu) @ v
    lo, hi = float(s50.min()) - 0.5, float(s50.max()) + 0.5     # pixel-centre extent -> edges
    # tip at the end whose last 8 % is narrower (the head); orient s from the tip (0) to the tail
    e8 = 0.08 * (hi - lo)
    w_lo = float(A[(s_ >= lo) & (s_ < lo + e8)].sum())
    w_hi = float(A[(s_ > hi - e8) & (s_ <= hi)].sum())
    if w_lo > w_hi:
        s_, lo, hi, v = -s_, -hi, -lo, -v
    s_ = s_ - lo
    length = hi - lo
    nb = max(8, int(round(length)))
    step = length / nb
    idx = np.clip((s_ / step).astype(int), 0, nb - 1)
    width = np.bincount(idx, weights=A, minlength=nb) / step          # soft width per 1-px slice
    # 1-px slices of a diagonal shape alias (pixel centres fall unevenly into slices): means over
    # zones and a 5-slice moving average are unbiased, single slices are not
    width_s = np.convolve(width, np.ones(5) / 5.0, mode="same")
    Wmax = float(width_s[2:-2].max()) if nb > 6 else float(width.max())
    shaft_zone = width[int(0.75 * nb):int(0.95 * nb)]
    sw = float(np.mean(shaft_zone)) if len(shaft_zone) else None
    if not sw or sw >= 0.8 * Wmax:
        out.update(kind=None, reason="머리·몸통 폭 차이가 없음")
        return out
    half = (Wmax + sw) / 2.0
    shoulder = max(b_ for b_ in range(nb) if width_s[b_] >= half)
    # head profile is linear from the tip: fit it, extrapolate the tip (width 0) and the shoulder width
    hb_ = np.arange(nb)[(np.arange(nb) >= 0.15 * shoulder) & (np.arange(nb) <= 0.85 * shoulder)]
    tip_s, shoulder_s = 0.0, (shoulder + 1) * step
    Wfit = Wmax
    if len(hb_) >= 3:
        sl, ic = np.polyfit((hb_ + 0.5) * step, width[hb_], 1)
        if sl > 0:
            tip_s = float(np.clip(-ic / sl, -0.1 * length, 0.1 * length))
            Wfit = float(sl * shoulder_s + ic)
    length_fit = length - tip_s
    hl = shoulder_s - tip_s
    tip_dir = -v                                   # from the tail towards the tip
    # rotation, renderer convention: 0 = pointing DOWN, degrees clockwise (image y down)
    rot = round(math.degrees(math.atan2(-tip_dir[0], tip_dir[1])), 1) % 360.0
    ratios = {"head_len_ratio": hl / length_fit, "head_width_ratio": Wfit / length_fit,
              "shaft_width_ratio": sw / length_fit}
    bad = [k for k, (a, b) in ARROW_RATIO_RANGE.items() if not a <= ratios[k] <= b]
    if bad:
        out.update(kind=None, reason=f"화살표 비율이 그럴듯한 범위 밖: {bad}")
        return out
    ol_px, ol_col = _outline(crop, mask, length_fit)
    out.update(kind="arrow", size_px=round(length_fit, 1), head_len_ratio=round(hl / length_fit, 3),
               head_width_ratio=round(Wfit / length_fit, 3), shaft_width_ratio=round(sw / length_fit, 3),
               outline_px=ol_px, outline_color=ol_col, rotation_deg=round(rot, 1))
    return out


def detect_decorations(video: str | Path, captions: dict | None = None, max_seconds: float | None = None,
                       width: int = DECO_WIDTH) -> dict:
    """Automatic arrow / circle / box detector (see DECO_METHOD).  Returns
    ``{"resolution", "items": [{kind, t, end, color, stroke_px | size_px + ratios + outline, blink_hz,
    duty, bbox, frame_t, ...}], "rejected": {...}, "method", "status"}`` in the video's own px.
    Limitation: two same-hue decorations that touch merge into one component (then usually rejected)."""
    import cv2

    from .common import read_segment

    video = Path(video)
    info = probe(video)
    W, H = int(info.width), int(info.height)
    fps = float(info.fps or 30.0)
    k = min(1.0, width / W)
    dw = int(round(W * k))
    rects = _caption_rects(captions)
    min_area = max(12, int(DECO_MIN_AREA_SHARE * dw * (H * k)))
    max_gap = int(round(DECO_MAX_GAP_S * fps))
    per_frame: list[list[dict]] = []
    live: list[dict] = []
    done: list[dict] = []
    nf = 0
    for t, fr in iter_native(video, fps, width=dw if k < 1.0 else None, max_seconds=max_seconds):
        fi = nf
        nf += 1
        vis = [(r[2], r[3], r[4], r[5]) for r in rects if r[0] <= t <= r[1]]
        comps = _deco_components(fr, vis, k, min_area)
        per_frame.append(comps)
        for c in comps:
            best = None
            for tr in live:
                gap = fi - tr["last"]
                if gap <= 0 or gap > max_gap + 1:
                    continue
                iou = _iou_xywh(tr["bboxes"][-1], c["bbox"])
                if iou < (0.5 if gap == 1 else 0.7) or np.linalg.norm(tr["colors"][-1] - c["color"]) > 45:
                    continue
                if best is None or iou > best[0]:
                    best = (iou, tr)
            if best:
                tr = best[1]
            else:
                tr = {"frames": [], "bboxes": [], "areas": [], "colors": [], "comps": []}
                live.append(tr)
            tr["frames"].append(fi)
            tr["bboxes"].append(c["bbox"])
            tr["areas"].append(c["area"])
            tr["colors"].append(c["color"])
            tr["comps"].append(c)
            tr["last"] = fi
        still = []
        for tr in live:
            (still if fi - tr["last"] <= max_gap + 1 else done).append(tr)
        live = still
    done += live
    rejected = {"short": 0, "small": 0, "not_sudden": 0, "text_like": 0, "not_flat": 0, "shape": 0}
    items = []
    for tr in done:
        fr_idx = tr["frames"]
        if len(fr_idx) < DECO_MIN_VISIBLE_S * fps:
            rejected["short"] += 1
            continue
        med_area = float(np.median(tr["areas"]))
        side = max(max(b[2], b[3]) for b in tr["bboxes"])
        if side < DECO_MIN_SIZE_SHARE * dw:
            rejected["small"] += 1
            continue
        on = [False] * (fr_idx[-1] - fr_idx[0] + 1)
        for f in fr_idx:
            on[f - fr_idx[0]] = True
        # every visible run must pop in at (nearly) full size: drawn overlays do, footage rarely
        starts = [q for q, f in enumerate(fr_idx) if q == 0 or f - fr_idx[q - 1] > 2]
        if any(tr["areas"][q] < 0.6 * med_area for q in starts):
            rejected["not_sudden"] += 1
            continue
        runs = _runs(on)
        # representative frame: middle of the longest visible run
        pos, best_run = 0, (0, 0)
        for v, n_ in runs:
            if v and n_ > best_run[1]:
                best_run = (pos, n_)
            pos += n_
        rep_f = fr_idx[0] + best_run[0] + best_run[1] // 2
        rep_q = min(range(len(fr_idx)), key=lambda q: abs(fr_idx[q] - rep_f))
        rep_c = tr["comps"][rep_q]
        if _text_like(rep_c, per_frame[fr_idx[rep_q]]):
            rejected["text_like"] += 1
            continue
        t_rep = fr_idx[rep_q] / fps
        seg = read_segment(video, t_rep, t_rep + 0.5 / fps, fps)
        if not seg:
            rejected["shape"] += 1
            continue
        full = seg[0][1]
        x, y, w, h = (v_ / k for v_ in rep_c["bbox"])
        pad = 0.3 * max(w, h) + 6
        X0, Y0 = int(max(0, x - pad)), int(max(0, y - pad))
        X1, Y1 = int(min(W, x + w + pad)), int(min(H, y + h + pad))
        crop = full[Y0:Y1, X0:X1]
        strict = _fill_mask(crop, np.median(np.stack(tr["colors"]), axis=0))
        if strict.sum() < 20:
            rejected["shape"] += 1
            continue
        core = cv2.distanceTransform(strict, cv2.DIST_L2, 3) >= 1.5
        pix = crop[core] if core.sum() >= 30 else crop[strict.astype(bool)]
        flat = float(pix.astype(np.float32).std(axis=0).mean())
        if flat > DECO_FLAT_STD:
            rejected["not_flat"] += 1
            continue
        alpha, mask, _ = _coverage(crop, strict)
        shp = _shape_measure(crop, alpha, mask)
        if not shp.get("kind"):
            rejected["shape"] += 1
            continue
        ys, xs = np.nonzero(mask)
        bl = blink_from_presence(on, fps)
        it = {"kind": shp.pop("kind"), "t": round(fr_idx[0] / fps, 3), "end": round((fr_idx[-1] + 1) / fps, 3),
              "frame_t": round(t_rep, 3), "color": hexrgb(np.median(pix, axis=0)),
              "bbox": [int(X0 + xs.min()), int(Y0 + ys.min()), int(xs.max() - xs.min() + 1),
                       int(ys.max() - ys.min() + 1)],
              "fill_std": round(flat, 2), **bl, **shp}
        items.append(it)
    items.sort(key=lambda it: it["t"])
    return {"resolution": [W, H], "fps": fps, "detection_width": dw, "method": DECO_METHOD,
            "status": "experimental", "items": items, "tracks_considered": len(done), "rejected": rejected,
            "note": "자동 검출은 우리 렌더러가 그린 합성 모의 영상으로만 검증됨 — 레퍼런스에서는 본 사람이 "
                    "manual_observations.csv 로 확인해야 함"}
