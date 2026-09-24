"""Video probes on the final MP4: cuts/transitions, zoom, freeze, decorations, canvas layout,
source mapping, logo residual and faces.

Everything here is measured from decoded output frames.  The ResolvedEdit only tells us where
to look and what the plan expected; e.g. zoom is estimated with ORB + RANSAC similarity fits
between output frames, not read from the plan.
"""
from __future__ import annotations

import difflib
import math
import os
from pathlib import Path

import numpy as np

from . import (QAContext, clip_at, clip_transform, ease_value, hex_rgb, map_src_rect, rect_xywh, rgb_hex, rnd,
               src_time, zoom_scale)

THUMB_W = 96


def _cv2():
    import cv2  # noqa: WPS433 (heavy optional import)

    return cv2


# ----------------------------------------------------------------------------- frame helpers
def region_union(ctx: QAContext) -> list[float]:
    regs = [rect_xywh(c.region) for c in ctx.resolved.clips] or []
    vr = ctx.resolved.canvas.get("video_region") if isinstance(ctx.resolved.canvas, dict) else None
    if not regs and vr:
        regs = [rect_xywh(vr)]
    if not regs:
        return [0.0, 0.0, float(ctx.canvas_w), float(ctx.canvas_h)]
    x0 = min(r[0] for r in regs)
    y0 = min(r[1] for r in regs)
    x1 = max(r[0] + r[2] for r in regs)
    y1 = max(r[1] + r[3] for r in regs)
    return [x0, y0, x1 - x0, y1 - y0]


_PROBE_CACHE: dict = {}


def _info(path):
    from ..util.media import probe

    key = str(path)
    st = Path(path).stat()
    ck = (key, st.st_mtime, st.st_size)
    if ck not in _PROBE_CACHE:
        _PROBE_CACHE[ck] = probe(path)
    return _PROBE_CACHE[ck]


def grab(path, t: float, width: int | None = None) -> np.ndarray:
    """The frame displayed at time t (frame k with k/fps <= t < (k+1)/fps), RGB uint8.
    Same raw rgb24 conversion path as grab_window, so frames are directly comparable."""
    info = _info(path)
    rate = info.fps or 30.0
    k = int(math.floor(max(0.0, t) * rate + 1e-6))
    ts, frs = grab_window(path, k / rate, 0.5 / rate, width=width)
    if not frs:
        # past the end: last decodable frame
        ts, frs = grab_window(path, max(0.0, info.duration - 3.0 / rate), 3.0 / rate, width=width)
        if not frs:
            from ..util.media import MediaError

            raise MediaError(f"no frame at t={t} in {path}")
        return frs[-1]
    return frs[0]


def grab_window(path, start: float, dur: float, fps: float | None = None, width: int | None = None,
                crop: list[float] | None = None, src_res: tuple[int, int] | None = None, gray: bool = False):
    """Frames whose display interval starts in [start, start+dur), at native fps (or ``fps``),
    optionally cropped (crop in px of the file's native resolution, rounded to ints) then
    scaled.  Times are exact frame times k/fps (constant-frame-rate files starting at 0).
    Returns (times, frames)."""
    import subprocess

    from ..util.media import FFMPEG

    info = _info(path)
    W, H = src_res or (info.width, info.height)
    rate = float(fps or info.fps or 30.0)
    k0 = int(math.ceil(max(0.0, start) * rate - 1e-6))
    k1 = int(math.ceil((max(0.0, start) + max(0.0, dur)) * rate - 1e-6))
    n_want = max(1, k1 - k0)
    filters = []
    if fps:
        filters.append(f"fps={fps}")
    cw, ch = W, H
    if crop is not None:
        x, y, w, h = crop_ints(crop, W, H)
        filters.append(f"crop={w}:{h}:{x}:{y}")
        cw, ch = w, h
    ow, oh = cw, ch
    if width and width != cw:
        ow = int(width) // 2 * 2
        oh = max(2, int(round(ch * ow / cw)) // 2 * 2)
        filters.append(f"scale={ow}:{oh}:flags=area")
    args = [FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{max(0.0, (k0 - 0.5) / rate):.6f}", "-i",
            str(path), "-frames:v", str(n_want)]
    if filters:
        args += ["-vf", ",".join(filters)]
    args += ["-fps_mode", "passthrough", "-f", "rawvideo", "-pix_fmt", "gray" if gray else "rgb24", "-"]
    raw = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
    fb = ow * oh * (1 if gray else 3)
    n = len(raw) // fb
    frames = [np.frombuffer(raw[i * fb:(i + 1) * fb], np.uint8).reshape((oh, ow) if gray else (oh, ow, 3))
              for i in range(n)]
    return [(k0 + i) / rate for i in range(n)], frames


def crop_ints(crop, W: int, H: int) -> tuple[int, int, int, int]:
    """The integer crop grab_window actually applies (callers crop reference frames the same way).
    Everything is even: ffmpeg's crop on 4:2:0 video silently rounds odd sizes/offsets, which would
    shear the raw frames."""
    x, y, w, h = (int(round(v)) for v in crop)
    x = max(0, min(W - 2, x)) // 2 * 2
    y = max(0, min(H - 2, y)) // 2 * 2
    w = max(2, min(W - x, w)) // 2 * 2
    h = max(2, min(H - y, h)) // 2 * 2
    return x, y, w, h


def color_mask(img: np.ndarray, rgb, tol: float = 70.0) -> np.ndarray:
    d = img.astype(np.int32) - np.array(rgb, np.int32)[None, None, :]
    return (d * d).sum(axis=2) <= tol * tol


def ncc(a: np.ndarray, b: np.ndarray) -> float:
    a = a.astype(np.float64).ravel()
    b = b.astype(np.float64).ravel()
    a = a - a.mean()
    b = b - b.mean()
    den = math.sqrt(float((a * a).sum()) * float((b * b).sum()))
    return float((a * b).sum() / den) if den > 1e-9 else 0.0


def edge_map(gray: np.ndarray) -> np.ndarray:
    cv2 = _cv2()
    g = gray.astype(np.float32)
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    return np.sqrt(gx * gx + gy * gy)


# ----------------------------------------------------------------------------- the scan
def scan(ctx: QAContext, width: int = 540, zoom_every: int = 1) -> dict:
    """One streaming pass over the output at native fps (scaled to ``width``)."""
    cv2 = _cv2()
    from ..util.media import iter_frames

    W, H = ctx.info.width, ctx.info.height
    s = width / float(W)
    rx, ry, rw, rh = region_union(ctx)
    X0, Y0 = int(round(rx * s)), int(round(ry * s))
    X1, Y1 = int(round((rx + rw) * s)), int(round((ry + rh) * s))
    decos = list(ctx.resolved.decorations)
    deco_state = {d.id: {"bg": None, "rows": [], "rgb": hex_rgb((d.style or {}).get("color"), (255, 42, 42))}
                  for d in decos}
    fps = ctx.fps
    n_samples = 12
    sample_times = [ctx.info.duration * (i + 0.5) / n_samples for i in range(n_samples)]
    samples: list[tuple[float, np.ndarray]] = []
    times, thumbs, luma, luma_full, rgbm, hists = [], [], [], [], [], []
    orb = cv2.ORB_create(nfeatures=700, fastThreshold=12)
    zoom_rows: dict[str, list] = {c.id: [] for c in ctx.resolved.clips}
    anchors: dict[str, tuple] = {}
    trans_windows = _transition_windows(ctx)
    si = 0
    for i, (t, fr) in enumerate(iter_frames(ctx.mp4, width=width)):
        reg = fr[Y0:Y1, X0:X1]
        g = cv2.cvtColor(reg, cv2.COLOR_RGB2GRAY)
        th = cv2.resize(g, (THUMB_W, max(8, int(round(THUMB_W * g.shape[0] / max(1, g.shape[1]))))),
                        interpolation=cv2.INTER_AREA)
        times.append(t)
        thumbs.append(th)
        luma.append(float(g.mean()))
        luma_full.append(float(fr.mean()))
        rgbm.append(reg.reshape(-1, 3).mean(axis=0))
        small = cv2.resize(reg, (48, max(4, int(round(48 * reg.shape[0] / max(1, reg.shape[1]))))),
                           interpolation=cv2.INTER_AREA)
        hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV)
        h = cv2.calcHist([hsv], [0, 1, 2], None, [8, 4, 4], [0, 180, 0, 256, 0, 256]).ravel()
        hists.append(h / max(1.0, h.sum()))
        if si < n_samples and t >= sample_times[si]:
            samples.append((t, fr.copy()))
            si += 1
        # --- zoom (ORB similarity vs clip anchor)
        c = clip_at(ctx.resolved, t)
        if c is not None and not any(a <= t <= b for a, b in trans_windows) and (i % zoom_every == 0 or c.zoom):
            cx0, cy0, cw_, ch_ = rect_xywh(c.region)
            cg = cv2.cvtColor(fr[int(round(cy0 * s)):int(round((cy0 + ch_) * s)),
                                 int(round(cx0 * s)):int(round((cx0 + cw_) * s))], cv2.COLOR_RGB2GRAY)
            kp, des = orb.detectAndCompute(cg, None)
            if c.id not in anchors:
                if des is not None and len(kp) >= 20:
                    anchors[c.id] = (t, kp, des, 1.0)
                    zoom_rows[c.id].append([t, 1.0, None, None, len(kp)])
            else:
                est = _similarity(anchors[c.id][1], anchors[c.id][2], kp, des)
                if est is not None:
                    sc_, fx, fy, inl = est
                    base = anchors[c.id][3]
                    zoom_rows[c.id].append([t, base * sc_, fx / s + cx0 if fx is not None else None,
                                            fy / s + cy0 if fy is not None else None, inl])
                    if inl < 25 and des is not None and len(kp) >= 40:   # re-anchor (chain) when matches thin out
                        anchors[c.id] = (t, kp, des, base * sc_)
        # --- decorations (colour tracking)
        for d in decos:
            st = deco_state[d.id]
            if not (d.start - 0.6 <= t <= d.end + 0.4):
                continue
            m = color_mask(fr, st["rgb"], 70.0)
            if t < d.start - 0.05:
                st["bg"] = m if st["bg"] is None else (st["bg"] | m)
                continue
            if st["bg"] is not None:
                m = m & ~cv2.dilate(st["bg"].astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
            rot = _deco_expected_kf(d, t).get("rotation") or 0.0
            st["rows"].append(_deco_measure(t, fr, m, s, d.kind, rot))
    return {"scale": s, "region": [rx, ry, rw, rh], "times": np.array(times), "thumbs": thumbs,
            "luma": np.array(luma), "luma_full": np.array(luma_full), "rgb": np.array(rgbm),
            "hists": np.array(hists), "samples": samples, "zoom_rows": zoom_rows,
            "deco": {k: {"rows": v["rows"]} for k, v in deco_state.items()}, "fps": fps}


def _similarity(kp0, des0, kp1, des1, return_matrix: bool = False):
    cv2 = _cv2()
    if des0 is None or des1 is None or len(kp1) < 8:
        return None
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    ms = bf.match(des0, des1)
    if len(ms) < 8:
        return None
    p0 = np.float32([kp0[m.queryIdx].pt for m in ms])
    p1 = np.float32([kp1[m.trainIdx].pt for m in ms])
    M, inl = cv2.estimateAffinePartial2D(p0, p1, method=cv2.RANSAC, ransacReprojThreshold=2.0, maxIters=3000,
                                         confidence=0.995)
    if M is None or inl is None:
        return None
    n_in = int(inl.sum())
    if n_in < 8:
        return None
    a, b = float(M[0, 0]), float(M[1, 0])
    sc = math.hypot(a, b)
    fx = fy = None
    if abs(sc - 1.0) > 0.01:
        R = np.array([[M[0, 0], M[0, 1]], [M[1, 0], M[1, 1]]])
        try:
            fxy = np.linalg.solve(np.eye(2) - R, M[:, 2])
            fx, fy = float(fxy[0]), float(fxy[1])
        except np.linalg.LinAlgError:
            pass
    if return_matrix:
        return sc, fx, fy, n_in, M, n_in / max(1, len(ms))
    return sc, fx, fy, n_in


def _deco_measure(t: float, fr: np.ndarray, m: np.ndarray, s: float, kind: str = "circle",
                  rotation: float = 0.0) -> dict:
    """Colour-tracked decoration in one frame.  ``anchor`` follows the IR convention:
    circle/box -> bbox centre; arrow -> the tip (extreme point along the pointing direction,
    rotation clockwise from pointing DOWN)."""
    cv2 = _cv2()
    cnt = int(m.sum())
    row = {"t": round(t, 4), "visible": False, "count": cnt}
    if cnt < 12:
        return row
    n, lab, stats, cents = cv2.connectedComponentsWithStats(m.astype(np.uint8), connectivity=8)
    if n <= 1:
        return row
    areas = stats[1:, cv2.CC_STAT_AREA]
    big = areas.max()
    keep = [i + 1 for i, a in enumerate(areas) if a >= max(6, 0.1 * big)]
    km = np.isin(lab, keep)
    ys, xs = np.nonzero(km)
    x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
    vals = fr[km].astype(np.float32)
    dist = cv2.distanceTransform(km.astype(np.uint8), cv2.DIST_L2, 3)
    cx, cy = (x0 + x1 + 1) / 2, (y0 + y1 + 1) / 2
    if kind == "arrow":
        a = math.radians(rotation or 0.0)
        dvec = (-math.sin(a), math.cos(a))          # tail -> tip direction in screen coords
        proj = xs * dvec[0] + ys * dvec[1]
        sel = proj >= proj.max() - 1.5
        ax, ay = float(xs[sel].mean()) + 0.5, float(ys[sel].mean()) + 0.5
        ax, ay = ax + dvec[0] * 0.5, ay + dvec[1] * 0.5
    else:
        ax, ay = cx, cy
    row.update({"visible": True, "count": int(km.sum()),
                "bbox": [round(x0 / s, 1), round(y0 / s, 1), round((x1 - x0 + 1) / s, 1), round((y1 - y0 + 1) / s, 1)],
                "center": [round(ax / s, 1), round(ay / s, 1)],
                "bbox_center": [round(cx / s, 1), round(cy / s, 1)],
                "brightness": round(float(vals.max(axis=1).mean()), 2),
                "color": rgb_hex(np.median(vals, axis=0)),
                "stroke_px": round(float(2.0 * np.percentile(dist[km], 95)) / s, 1)})
    return row


def _transition_windows(ctx: QAContext) -> list[tuple[float, float]]:
    out = []
    fr = 1.0 / ctx.fps
    for c in ctx.resolved.clips[1:]:
        tr = c.transition_in
        d = float(tr.dur or 0.0)
        if tr.type == "crossfade":
            out.append((c.out_start - fr, c.out_start + d + fr))
        elif tr.type == "flash":
            out.append((c.out_start - d - fr, c.out_start + d + fr))
        else:
            out.append((c.out_start - fr, c.out_start + fr))
    return out


# ----------------------------------------------------------------------------- transitions
def frame_diffs(sc: dict) -> np.ndarray:
    th = sc["thumbs"]
    d = np.zeros(len(th))
    for i in range(1, len(th)):
        d[i] = float(np.abs(th[i].astype(np.int16) - th[i - 1].astype(np.int16)).mean())
    return d


def _local_ratio(d: np.ndarray, i: int, half: int = 6) -> float:
    """Spike strength of frame diff i vs its neighbourhood (80th percentile, so low-fps sources
    whose duplicated frames give zero diffs do not look like a cut every few frames)."""
    lo, hi = max(1, i - half), min(len(d), i + half + 1)
    neigh = [d[j] for j in range(lo, hi) if abs(j - i) > 1]
    base = float(np.percentile(neigh, 80)) if neigh else 0.0
    return float(d[i]) / (base + 0.5)


def _flash_runs(sc: dict, fps: float) -> list[dict]:
    lum = sc["luma"]
    n = len(lum)
    out = []
    if n < 5:
        return out
    base = np.array([np.median(np.r_[lum[max(0, i - 12):max(0, i - 4)], lum[min(n, i + 5):min(n, i + 13)]])
                     if (i - 4 > 0 or i + 5 < n) else lum[i] for i in range(n)])
    exc = lum - base
    on = exc >= 28.0
    i = 0
    while i < n:
        if on[i]:
            j = i
            while j + 1 < n and on[j + 1]:
                j += 1
            if (j - i + 1) / fps <= 0.8:
                k = int(i + np.argmax(exc[i:j + 1]))
                out.append({"start": float(sc["times"][i]), "end": float(sc["times"][j] + 1.0 / fps),
                            "peak_t": float(sc["times"][k]), "peak_excess": round(float(exc[k]), 1),
                            "color": rgb_hex(sc["rgb"][k]), "frames": j - i + 1})
            i = j + 1
        else:
            i += 1
    return out


def _blend_fit(sc: dict, a: int, b: int) -> dict | None:
    """Fit frames a..b as (1-alpha) A + alpha B, A = frame a-1, B = frame b+1."""
    th = sc["thumbs"]
    if a < 1 or b + 1 >= len(th) or b <= a:
        return None
    A = th[a - 1].astype(np.float32)
    B = th[b + 1].astype(np.float32)
    D = B - A
    den = float((D * D).sum())
    if den < 1e-6 or float(np.abs(D).mean()) < 4.0:
        return None
    alphas, res = [], []
    for j in range(a, b + 1):
        X = th[j].astype(np.float32) - A
        al = float((X * D).sum() / den)
        alphas.append(al)
        res.append(float(np.abs(X - al * D).mean()) / float(np.abs(D).mean()))
    return {"alphas": alphas, "resid": res}


def _classify_boundary(sc: dict, d: np.ndarray, flashes: list, t_b: float, dur: float, fps: float) -> dict:
    """What does the output actually show around an expected clip boundary?"""
    times = sc["times"]
    fr = 1.0 / fps
    # flash?
    for f in flashes:
        if f["end"] >= t_b - dur - 3 * fr and f["start"] <= t_b + dur + 3 * fr:
            return {"type": "flash", "t": round(f["start"], 4), "peak_t": round(f["peak_t"], 4),
                    "dur": round(f["end"] - f["start"], 4), "color": f["color"], "score": f["peak_excess"]}
    # gradual blend (crossfade)?  A hard cut has no intermediate frames, a blend has several.
    xf = _crossfade_fit(sc, t_b, dur, fps)
    if xf is not None:
        return xf
    # hard cut: strongest local-ratio spike within +-3 frames
    idx = [i for i in range(1, len(times)) if abs(times[i] - t_b) <= 3 * fr + 1e-6]
    best, best_r = None, 0.0
    for i in idx:
        r = _local_ratio(d, i)
        if r > best_r:
            best, best_r = i, r
    if best is not None and best_r >= 3.0 and d[best] >= 2.5:
        return {"type": "cut", "t": round(float(times[best]), 4), "dur": 0.0, "score": round(best_r, 2),
                "diff": round(float(d[best]), 2)}
    return {"type": "none", "t": None, "dur": None, "score": round(best_r, 2)}


def _crossfade_fit(sc: dict, t_b: float, dur: float, fps: float) -> dict | None:
    times = sc["times"]
    fr = 1.0 / fps
    span = max(3, int(round(max(dur, 0.2) * fps)))
    i0 = int(np.searchsorted(times, t_b - 2 * fr))
    best_fit = None
    for a in range(max(1, i0 - 2), min(len(times) - 2, i0 + 3)):
        for L in range(max(3, span - 2), span + 6):
            b = a + L - 1
            bf = _blend_fit(sc, a, b)
            if bf is None:
                continue
            al = np.array(bf["alphas"])
            mono = float(np.mean(np.diff(al) >= -0.03)) if len(al) > 1 else 0.0
            err = float(np.mean(bf["resid"]))
            mid = int(np.sum((al > 0.1) & (al < 0.9)))
            if mono >= 0.8 and mid >= 2 and al[0] < 0.45 and al[-1] > 0.55 and err < 0.45:
                cand = (err, a, b, al)
                if best_fit is None or cand[0] < best_fit[0]:
                    best_fit = cand
    if best_fit is None:
        return None
    err, a, b, al = best_fit
    tt = np.array(times[a:b + 1])
    sel = (al > 0.05) & (al < 0.95)
    if sel.sum() >= 2:
        k, c0 = np.polyfit(tt[sel], al[sel], 1)
        if k > 0:
            t0 = -c0 / k                     # alpha = 0
            return {"type": "crossfade", "t": round(float(t0), 4), "dur": round(float(1.0 / k), 4),
                    "score": round(1.0 - err, 3), "frames_in_blend": int(sel.sum())}
    return {"type": "crossfade", "t": round(float(times[a]), 4), "dur": round(float(times[b] - times[a] + fr), 4),
            "score": round(1.0 - err, 3)}


def motion_explains(ctx: QAContext, t_prev: float, t_cur: float, region) -> dict:
    """Is the change between two consecutive output frames a global move (zoom/pan) rather than
    a cut?  ORB + RANSAC similarity between the two frames of the video region."""
    cv2 = _cv2()
    try:
        a = grab(ctx.mp4, t_prev)
        b = grab(ctx.mp4, t_cur)
    except Exception:
        return {"motion": None}
    x, y, w, h = crop_ints(region, ctx.info.width, ctx.info.height)
    k = 540.0 / max(1, w)
    ga = cv2.resize(cv2.cvtColor(a[y:y + h, x:x + w], cv2.COLOR_RGB2GRAY), None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    gb = cv2.resize(cv2.cvtColor(b[y:y + h, x:x + w], cv2.COLOR_RGB2GRAY), None, fx=k, fy=k, interpolation=cv2.INTER_AREA)
    orb = cv2.ORB_create(nfeatures=800, fastThreshold=12)
    k1, d1 = orb.detectAndCompute(ga, None)
    k2, d2 = orb.detectAndCompute(gb, None)
    est = _similarity(k1, d1, k2, d2, return_matrix=True)
    if est is None:
        return {"motion": False, "inliers": 0}
    sc_, _, _, inl, M, ratio = est
    warped = cv2.warpAffine(ga, M, (gb.shape[1], gb.shape[0]), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    m = 12
    raw = float(np.abs(ga[m:-m, m:-m].astype(np.float32) - gb[m:-m, m:-m]).mean())
    res = float(np.abs(warped[m:-m, m:-m].astype(np.float32) - gb[m:-m, m:-m]).mean())
    explained = raw > 0 and res / raw < 0.5
    return {"motion": bool(inl >= 25 and explained), "inliers": inl, "inlier_ratio": round(ratio, 3),
            "scale": round(sc_, 4), "residual_ratio": round(res / raw, 3) if raw > 0 else None}


def analyze_transitions(ctx: QAContext, sc: dict) -> dict:
    fps = sc["fps"]
    fr = 1.0 / fps
    d = frame_diffs(sc)
    flashes = _flash_runs(sc, fps)
    bounds = []
    claimed: list[tuple[float, float]] = []
    for c in ctx.resolved.clips[1:]:
        tr = c.transition_in
        dur = float(tr.dur or 0.0)
        obs = _classify_boundary(sc, d, flashes, c.out_start, dur, fps)
        exp = {"type": tr.type, "t": round(c.out_start, 4), "dur": round(dur, 4),
               "color": tr.color if tr.type == "flash" else None}
        ok = obs["type"] == tr.type
        timing_ok = None
        if ok and tr.type == "cut":
            timing_ok = abs(obs["t"] - c.out_start) <= fr + 1e-3
        elif ok and tr.type == "crossfade":
            timing_ok = abs(obs["t"] - c.out_start) <= fr + 1e-3 and abs(obs["dur"] - dur) <= 2 * fr + 1e-3
        elif ok and tr.type == "flash":
            timing_ok = (obs["t"] - fr <= c.out_start + dur and obs["t"] + obs["dur"] + fr >= c.out_start - dur
                         and abs(obs["dur"] - dur) <= 2 * fr + 1e-3)
        bounds.append({"clip_id": c.id, "expected": exp, "observed": obs, "type_ok": ok, "timing_ok": timing_ok})
        claimed.append((c.out_start - max(dur, 0.2) - 2 * fr, c.out_start + max(dur, 0.2) + 2 * fr))
    # unexpected hard cuts / flashes
    extra = []
    times = sc["times"]
    for i in range(2, len(times) - 1):
        t = float(times[i])
        if any(a <= t <= b for a, b in claimed):
            continue
        r = _local_ratio(d, i)
        if r >= 5.0 and d[i] >= 6.0:
            extra.append({"t": round(t, 4), "type": "cut", "score": round(r, 2), "diff": round(float(d[i]), 2)})
    for f in flashes:
        if not any(a <= f["peak_t"] <= b for a, b in claimed):
            extra.append({"t": round(f["start"], 4), "type": "flash", "score": f["peak_excess"]})
    kept = []
    for e in extra:
        c = clip_at(ctx.resolved, e["t"])
        if e["type"] == "cut":
            mv = motion_explains(ctx, e["t"] - 1.0 / fps, e["t"], sc["region"])
            e["motion_check"] = mv
            if mv.get("motion"):
                continue                     # a zoom/pan step, not a cut
            if c is not None:
                e["clip_id"] = c.id
                e["source_has_cut"] = source_has_cut(c, src_time(c, e["t"]))
        kept.append(e)
    extra = kept
    return {"boundaries": bounds, "unexpected": extra, "flashes": flashes,
            "diff_stats": {"p50": rnd(np.median(d[1:]) if len(d) > 1 else None, 3),
                           "p90": rnd(np.percentile(d[1:], 90) if len(d) > 1 else None, 3)}}


def source_has_cut(clip, st: float) -> bool | None:
    from .. import paths

    p = paths.absp(clip.source_path)
    if not p.is_file():
        return None
    try:
        ts, fr = grab_window(p, max(0.0, st - 0.2), 0.4, width=THUMB_W, gray=True)
    except Exception:
        return None
    if len(fr) < 3:
        return None
    d = [float(np.abs(fr[i].astype(np.int16) - fr[i - 1].astype(np.int16)).mean()) for i in range(1, len(fr))]
    base = float(np.median(d)) + 0.5
    return bool(max(d) / base >= 4.0 and max(d) >= 5.0)


# ----------------------------------------------------------------------------- freeze
FREEZE_THR = 0.045       # mean abs diff (0..255) of 96-px thumbnails: repeated frames ~0.00-0.03,
                         # a still-looking real camera shot ~0.05-0.3 (measured on the test renders)


def analyze_freezes(ctx: QAContext, sc: dict, thr: float = FREEZE_THR) -> dict:
    fps = sc["fps"]
    fr = 1.0 / fps
    d = frame_diffs(sc)
    times = sc["times"]
    min_len = max(5, int(round(0.2 * fps)))
    runs = []
    i = 1
    n = len(d)
    while i < n:
        if d[i] < thr:
            j = i
            while j + 1 < n and (d[j + 1] < thr or (d[j + 1] < 2 * thr and j + 2 < n and d[j + 2] < thr)):
                j += 1
            L = j - i + 2          # frames i-1..j repeat
            if L >= min_len:
                runs.append({"start": round(float(times[i - 1]), 4), "end": round(float(times[j]) + fr, 4),
                             "frames": L, "mean_diff": round(float(d[i:j + 1].mean()), 4)})
            i = j + 1
        else:
            i += 1
    expected = []
    for c in ctx.resolved.clips:
        if c.freeze is not None:
            expected.append({"clip_id": c.id, "start": round(c.freeze.out_start, 4),
                             "end": round(c.freeze.out_start + c.freeze.hold, 4), "hold": round(c.freeze.hold, 4)})
    matched = set()
    for e in expected:
        c = next(x for x in ctx.resolved.clips if x.id == e["clip_id"])
        best = None
        for k, r in enumerate(runs):
            ov = min(r["end"], e["end"]) - max(r["start"], e["start"])
            if ov > 0 and (best is None or ov > best[0]):
                best = (ov, k)
        if best is None:
            e["observed"] = None
            e["start_ok"] = e["hold_ok"] = False
            mv = source_motion(c, src_time(c, e["start"] - 0.2), src_time(c, e["start"] - 1e-3))
            e["source_motion_before"] = mv
            continue
        r = runs[best[1]]
        matched.add(best[1])
        e["observed"] = r
        # a still source next to the freeze makes the run longer; that is not a timing error
        s_ok = abs(r["start"] - e["start"]) <= 2 * fr + 1e-3
        if not s_ok and r["start"] < e["start"]:
            mv = source_motion(c, src_time(c, r["start"]), src_time(c, e["start"] - 1e-3))
            e["source_motion_before"] = mv
            s_ok = mv is not None and mv < thr * 1.5
        e_ok = abs(r["end"] - e["end"]) <= 3 * fr + 1e-3
        if not e_ok and r["end"] > e["end"]:
            if c.out_end <= e["end"] + fr:
                e_ok = True                     # freeze at the end of the clip: the next clip ends it
            else:
                mv = source_motion(c, src_time(c, e["end"] + 1e-3), src_time(c, r["end"]))
                e["source_motion_after"] = mv
                e_ok = mv is not None and mv < thr * 1.5
        e["start_ok"], e["hold_ok"] = bool(s_ok), bool(e_ok)
        # can a freeze be told apart from the source here at all?
        mv_src = source_motion(c, src_time(c, e["start"] - 0.4), src_time(c, e["start"] - 1e-3))
        e["source_moving_before"] = mv_src
        e["distinguishable"] = None if mv_src is None else bool(mv_src >= thr * 1.5)
    unexpected = []
    for k, r in enumerate(runs):
        if k in matched:
            continue
        c = clip_at(ctx.resolved, (r["start"] + r["end"]) / 2)
        r = dict(r)
        if c is not None:
            r["clip_id"] = c.id
            mv = source_motion(c, src_time(c, r["start"]), src_time(c, r["end"] - 1e-3))
            r["source_mean_diff"] = rnd(mv, 4)
            r["source_static"] = None if mv is None else bool(mv < thr * 1.5)
        unexpected.append(r)
    return {"threshold": thr, "min_frames": min_len, "runs": runs, "expected": expected, "unexpected": unexpected}


def source_motion(clip, s0: float, s1: float) -> float | None:
    """Mean consecutive-frame difference of the SOURCE between source times s0..s1 (same
    96-px thumbnail measure as the output scan).  None if the source cannot be read."""
    from .. import paths

    p = paths.absp(clip.source_path)
    if not p.is_file():
        return None
    if s1 < s0:
        s0, s1 = s1, s0
    try:
        info = _info(p)
        rate = info.fps or 30.0
        ts, frs = grab_window(p, max(0.0, s0), max(2.0 / rate, s1 - s0 + 1.0 / rate), width=THUMB_W, gray=True)
    except Exception:
        return None
    if len(frs) < 2:
        return None
    return float(np.mean([np.abs(frs[i].astype(np.int16) - frs[i - 1].astype(np.int16)).mean() for i in range(1, len(frs))]))


def source_static(clip, s0: float, s1: float) -> bool | None:
    mv = source_motion(clip, s0, s1)
    return None if mv is None else bool(mv < FREEZE_THR * 1.5)


# ----------------------------------------------------------------------------- zoom
EASES = ("linear", "in", "out", "inout")


def analyze_zoom(ctx: QAContext, sc: dict) -> dict:
    out = []
    fr = 1.0 / sc["fps"]
    for c in ctx.resolved.clips:
        rows_all = [r for r in sc["zoom_rows"].get(c.id, []) if r[1] is not None]
        rows = [r for r in rows_all if r[4] is None or r[4] >= 15]
        item = {"clip_id": c.id, "n_samples": len(rows), "n_rejected_low_inliers": len(rows_all) - len(rows),
                "median_inliers": rnd(float(np.median([r[4] for r in rows])) if rows else None, 1)}
        z = c.zoom
        if z is not None:
            item["expected"] = {"scale_from": z.scale_from, "scale_to": z.scale_to, "start": round(c.out_start + z.start, 4),
                                "dur": z.dur, "ease": z.ease,
                                "center_canvas": _zoom_center_canvas(c)}
        if len(rows) < 4:
            item["status"] = "unmeasured"
            item["reason"] = "특징점 부족(ORB 매칭 실패) 또는 클립 길이가 너무 짧음"
            out.append(item)
            continue
        arr = np.array([[r[0], r[1]] for r in rows], float)
        t0 = arr[0, 0]
        # expected relative curve vs the anchor time
        exp_rel = np.array([zoom_scale(c, t) / max(1e-6, zoom_scale(c, t0)) for t in arr[:, 0]])
        meas = arr[:, 1]
        item["curve"] = [[rnd(t, 3), rnd(v, 4)] for t, v in arr[:: max(1, len(arr) // 40)]]
        item["measured_final_ratio"] = rnd(float(np.median(meas[-max(2, len(meas) // 6):])), 4)
        k5 = min(5, len(meas))
        smooth = np.array([np.median(meas[max(0, i - k5 // 2):i + k5 // 2 + 1]) for i in range(len(meas))])
        item["measured_max_dev"] = rnd(float(np.max(np.abs(smooth - 1.0))), 4)
        item["measured_spread"] = rnd(float(np.std(meas[-max(3, len(meas) // 3):])), 4)
        item["expected_final_ratio"] = rnd(float(exp_rel[-1]), 4)
        item["max_abs_err"] = rnd(float(np.max(np.abs(meas - exp_rel))), 4)
        if z is not None and abs(z.scale_to - z.scale_from) > 1e-3:
            lo, hi = float(meas[0]), item["measured_final_ratio"]
            half = lo + (hi - lo) / 2
            idx = np.nonzero((meas - half) * np.sign(hi - lo) >= 0)[0]
            item["measured_t50"] = rnd(float(arr[idx[0], 0]), 3) if len(idx) else None
            # expected t50 from the ease curve
            ts = np.linspace(c.out_start + z.start, c.out_start + z.start + max(z.dur, 1e-3), 200)
            ev = np.array([zoom_scale(c, t) for t in ts])
            eh = z.scale_from + (z.scale_to - z.scale_from) / 2
            k = np.nonzero((ev - eh) * np.sign(z.scale_to - z.scale_from) >= 0)[0]
            item["expected_t50"] = rnd(float(ts[k[0]]), 3) if len(k) else None
            # measured zoom duration (10%..90% of the change) and ease shape
            item.update(_zoom_shape(arr, lo, hi))
            fx = [r[2] for r in rows if r[2] is not None]
            fy = [r[3] for r in rows if r[3] is not None]
            if fx and fy:
                item["measured_center_canvas"] = [rnd(float(np.median(fx)), 1), rnd(float(np.median(fy)), 1)]
        item["status"] = "measured"
        item["tolerance"] = {"ratio": 0.04, "t50_s": max(0.1, 3 * fr)}
        out.append(item)
    # consecutive zoom count (same effect stacked on consecutive segments)
    zoomed = [(it.get("measured_max_dev") or 0) > 0.05 for it in out]
    run = best = 0
    for zf in zoomed:
        run = run + 1 if zf else 0
        best = max(best, run)
    return {"clips": out, "max_consecutive_measured": best}


def _zoom_center_canvas(c) -> list[float] | None:
    if c.zoom is None:
        return None
    tr = clip_transform(c, None)
    px, py = c.zoom.center_src
    return [rnd(px * tr["s"] + tr["tx"], 1), rnd(py * tr["s"] + tr["ty"], 1)]


def _zoom_shape(arr: np.ndarray, lo: float, hi: float) -> dict:
    t = arr[:, 0]
    v = arr[:, 1]
    if abs(hi - lo) < 0.03:
        return {"measured_dur": None, "measured_ease": None}
    u = (v - lo) / (hi - lo)
    i10 = np.nonzero(u >= 0.1)[0]
    i90 = np.nonzero(u >= 0.9)[0]
    if not len(i10) or not len(i90):
        return {"measured_dur": None, "measured_ease": None}
    # extrapolate 10-90% to a full-length estimate assuming the fitted ease
    ta, tb = float(t[i10[0]]), float(t[i90[0]])
    best = None
    for e in EASES:
        # find (start, dur) minimising error for this ease on a coarse grid
        for dur in np.linspace(max(0.05, (tb - ta) * 0.8), (tb - ta) * 2.5 + 0.1, 25):
            for st in np.linspace(ta - dur * 0.6, ta, 12):
                pred = np.array([ease_value((x - st) / dur, e) for x in t])
                err = float(np.mean((pred - u) ** 2))
                if best is None or err < best[0]:
                    best = (err, e, st, dur)
    return {"measured_dur": rnd(best[3], 3), "measured_zoom_start": rnd(best[2], 3), "measured_ease": best[1],
            "ease_fit_rmse": rnd(math.sqrt(best[0]), 4)}


# ----------------------------------------------------------------------------- decorations
def analyze_decorations(ctx: QAContext, sc: dict) -> dict:
    out = []
    fps = sc["fps"]
    for d in ctx.resolved.decorations:
        rows = sc["deco"].get(d.id, {}).get("rows", [])
        style = d.style or {}
        item = {"id": d.id, "kind": d.kind, "expected": {"start": d.start, "end": d.end, "blink_hz": d.blink_hz,
                                                          "color": style.get("color"),
                                                          "keyframes": d.keyframes}}
        inside = [r for r in rows if d.start + 0.5 / fps <= r["t"] <= d.end - 0.5 / fps]
        vis = [r for r in inside if r["visible"]]
        if not inside:
            item["status"] = "unmeasured"
            item["reason"] = "장식 구간 프레임 없음"
            out.append(item)
            continue
        item["visible_fraction"] = rnd(len(vis) / len(inside), 3)
        # --- position (only frames where it is visible)
        pos = []
        for r in vis:
            ex = _deco_expected_pos(d, r["t"])
            pos.append({"t": r["t"], "obs": r["center"], "exp": ex, "bbox": r["bbox"]})
        if pos:
            errs = [math.hypot(p["obs"][0] - p["exp"][0], p["obs"][1] - p["exp"][1]) for p in pos]
            o0, e0 = pos[0]["obs"], pos[0]["exp"]
            path = [math.hypot((p["obs"][0] - o0[0]) - (p["exp"][0] - e0[0]),
                               (p["obs"][1] - o0[1]) - (p["exp"][1] - e0[1])) for p in pos]
            item["position"] = {"n": len(pos), "abs_err_p50": rnd(float(np.median(errs)), 1),
                                "abs_err_p90": rnd(float(np.percentile(errs, 90)), 1),
                                "path_err_p90": rnd(float(np.percentile(path, 90)), 1),
                                "track": [[p["t"], p["obs"][0], p["obs"][1], p["exp"][0], p["exp"][1]]
                                          for p in pos[:: max(1, len(pos) // 30)]],
                                "size_obs": [rnd(float(np.median([p["bbox"][2] for p in pos])), 1),
                                             rnd(float(np.median([p["bbox"][3] for p in pos])), 1)],
                                "bbox_union": [rnd(min(p["bbox"][0] for p in pos), 1), rnd(min(p["bbox"][1] for p in pos), 1),
                                               rnd(max(p["bbox"][0] + p["bbox"][2] for p in pos) - min(p["bbox"][0] for p in pos), 1),
                                               rnd(max(p["bbox"][1] + p["bbox"][3] for p in pos) - min(p["bbox"][1] for p in pos), 1)]}
            item["color_obs"] = _mode([r.get("color") for r in vis])
            item["stroke_px_obs"] = rnd(float(np.median([r.get("stroke_px") or 0 for r in vis])), 1)
        # --- brightness / blink (separately from position)
        cnts = np.array([r["count"] if r["visible"] else 0 for r in inside], float)
        bri = np.array([r.get("brightness", 0.0) if r["visible"] else 0.0 for r in inside], float)
        peak = float(np.percentile(cnts * bri, 95)) if len(cnts) else 0.0
        level = (cnts * bri) / peak if peak > 0 else np.zeros_like(cnts)
        ts = np.array([r["t"] for r in inside])
        on = level >= 0.5
        n_on = int(np.sum(np.diff(on.astype(int)) == 1)) + (1 if len(on) and on[0] else 0)
        span = float(ts[-1] - ts[0] + 1.0 / fps) if len(ts) else 0.0
        item["brightness"] = {"n": int(len(inside)), "on_fraction": rnd(float(on.mean()) if len(on) else None, 3),
                              "on_events": n_on, "blink_hz_obs": rnd(_blink_freq(ts, level, fps), 3),
                              "cv": rnd(float(level.std() / max(1e-6, level.mean())) if len(level) else None, 3),
                              "curve": [[rnd(a, 3), rnd(b, 3)] for a, b in list(zip(ts, level))[:: max(1, len(ts) // 60)]],
                              "span_s": rnd(span, 3)}
        item["status"] = "measured"
        out.append(item)
    return {"items": out}


def _blink_freq(ts: np.ndarray, level: np.ndarray, fps: float) -> float | None:
    if len(ts) < 8:
        return None
    on = level >= 0.5
    rises = np.nonzero(np.diff(on.astype(int)) == 1)[0]
    if len(rises) >= 2:
        per = np.diff(ts[rises + 1])
        return float(1.0 / np.median(per)) if np.median(per) > 0 else None
    if on.mean() > 0.9 or on.mean() < 0.1:
        return 0.0
    return None


def _deco_expected_kf(d, t: float) -> dict:
    """Keyframe values interpolated at absolute output time t (x, y, w, h, rotation)."""
    kfs = sorted(d.keyframes, key=lambda k: k["t"])
    if not kfs:
        return {"x": 0.0, "y": 0.0}
    if t <= kfs[0]["t"]:
        return dict(kfs[0])
    for a, b in zip(kfs, kfs[1:]):
        if a["t"] <= t <= b["t"]:
            u = (t - a["t"]) / max(1e-6, b["t"] - a["t"])
            out = dict(a)
            for k in ("x", "y", "w", "h", "rotation"):
                if a.get(k) is not None and b.get(k) is not None:
                    out[k] = a[k] + (b[k] - a[k]) * u
            return out
    return dict(kfs[-1])


def _deco_expected_pos(d, t: float) -> list[float]:
    """Expected anchor at output time t: circle/box centre, arrow tip (IR convention,
    shortkit.edit.captions.deco_shape)."""
    k = _deco_expected_kf(d, t)
    return [float(k["x"]), float(k["y"])]


def _mode(vals):
    vals = [v for v in vals if v]
    if not vals:
        return None
    from collections import Counter

    return Counter(vals).most_common(1)[0][0]


# ----------------------------------------------------------------------------- canvas layout
def analyze_layout(ctx: QAContext, sc: dict, caption_boxes: list | None = None) -> dict:
    samples = sc.get("samples") or []
    s = sc["scale"]
    if len(samples) < 4:
        return {"status": "unmeasured", "reason": "샘플 프레임 부족"}
    stack = np.stack([f for _, f in samples]).astype(np.float32)
    gray = stack.mean(axis=3)
    std = gray.std(axis=0)
    bg_rgb = hex_rgb(((ctx.resolved.canvas.get("background") or {}).get("color")), (0, 0, 0))
    far = np.sqrt(((stack - np.array(bg_rgb, np.float32)) ** 2).sum(axis=3)).mean(axis=0)
    content = (std > 4.0) | (far > 30.0)
    H, W = content.shape
    rows = content.mean(axis=1) > 0.6
    runs, i = [], 0
    while i < H:
        if rows[i]:
            j = i
            while j + 1 < H and rows[j + 1]:
                j += 1
            runs.append((i, j))
            i = j + 1
        else:
            i += 1
    if not runs:
        return {"status": "unmeasured", "reason": "움직이는 영상 영역을 찾지 못함"}
    r0, r1 = max(runs, key=lambda r: r[1] - r[0])
    cols = content[r0:r1 + 1].mean(axis=0) > 0.5
    cx = np.nonzero(cols)[0]
    c0, c1 = (int(cx.min()), int(cx.max())) if len(cx) else (0, W - 1)
    region = [round(c0 / s, 1), round(r0 / s, 1), round((c1 - c0 + 1) / s, 1), round((r1 - r0 + 1) / s, 1)]
    outside = np.ones((H, W), bool)
    outside[r0:r1 + 1, c0:c1 + 1] = False
    for b in caption_boxes or []:
        x, y, w, h = b
        outside[max(0, int((y - 20) * s)):int((y + h + 20) * s), max(0, int((x - 20) * s)):int((x + w + 20) * s)] = False
    if outside.sum() < 50:
        return {"status": "measured", "video_region": region, "background": {"type": "unmeasured",
                                                                            "reason": "배경 영역 없음(영상이 화면을 채움)"}}
    px = stack[:, outside, :]
    med = np.median(px.reshape(-1, 3), axis=0)
    bstd = float(gray[:, outside].std(axis=0).mean())
    bg_type = "color" if bstd < 3.0 else "blur_source"
    return {"status": "measured", "video_region": region, "background": {"type": bg_type, "color": rgb_hex(med),
                                                                         "temporal_std": rnd(bstd, 2)},
            "resolution": [ctx.info.width, ctx.info.height], "fps": rnd(ctx.info.fps, 3)}


# ----------------------------------------------------------------------------- source mapping
def analyze_mapping(ctx: QAContext, work_w: int = 240) -> dict:
    """For each clip, which source time does the output actually show?  (NCC of the output
    video region against the geometrically fitted source frames around the planned time)."""
    from .. import paths

    cv2 = _cv2()
    out = []
    fr = 1.0 / ctx.fps
    for ci, c in enumerate(ctx.resolved.clips):
        item = {"clip_id": c.id, "source": c.source_path, "expected_src": [c.src_in, c.src_out], "speed": c.speed}
        p = paths.absp(c.source_path)
        if not p.is_file():
            item.update(status="unmeasured", reason=f"소스 파일 없음: {c.source_path}")
            out.append(item)
            continue
        t_lo = c.out_start + (float(c.transition_in.dur or 0) if ci else 0.0) + 2 * fr
        nxt = ctx.resolved.clips[ci + 1] if ci + 1 < len(ctx.resolved.clips) else None
        t_hi = (nxt.out_start if nxt else c.out_end) - 2 * fr
        if c.freeze is not None:
            ranges = [(t_lo, min(t_hi, c.freeze.out_start - fr)), (c.freeze.out_start + c.freeze.hold + fr, t_hi)]
        else:
            ranges = [(t_lo, t_hi)]
        cand_t = []
        for a, b in ranges:
            if b - a > 0.15:
                cand_t += [a + (b - a) * q for q in (0.2, 0.5, 0.8)]
        cand_t = cand_t[:3] if len(cand_t) <= 3 else [cand_t[0], cand_t[len(cand_t) // 2], cand_t[-1]]
        if not cand_t:
            item.update(status="unmeasured", reason="클립이 너무 짧아 비교할 프레임 없음")
            out.append(item)
            continue
        rx, ry, rw, rh = rect_xywh(c.region)
        k = work_w / rw
        wh = max(8, int(round(rh * k)))
        samples = []
        for t in cand_t:
            try:
                of = grab(ctx.mp4, t)
            except Exception:
                continue
            oreg = cv2.resize(of[int(ry):int(ry + rh), int(rx):int(rx + rw)], (work_w, wh), interpolation=cv2.INTER_AREA)
            og = cv2.cvtColor(oreg, cv2.COLOR_RGB2GRAY).astype(np.float32)
            exp_s = src_time(c, t)
            try:
                ts, frs = grab_window(p, max(0.0, exp_s - 0.8), 1.6)
            except Exception:
                continue
            tr = clip_transform(c, t)
            M = np.array([[tr["s"] * k, 0, (tr["tx"] - rx) * k], [0, tr["s"] * k, (tr["ty"] - ry) * k]], np.float32)
            best = (-2.0, None)
            vals = []
            for st, sf in zip(ts, frs):
                w_ = cv2.warpAffine(sf, M, (work_w, wh), flags=cv2.INTER_AREA)
                g = cv2.cvtColor(w_, cv2.COLOR_RGB2GRAY).astype(np.float32)
                v = ncc(g, og)
                vals.append(v)
                if v > best[0]:
                    best = (v, st)
            if best[1] is not None:
                # how sharply does the best source time stand out?  (a still scene matches every time)
                contrast = float(best[0] - np.percentile(vals, 20)) if len(vals) >= 5 else 0.0
                samples.append({"t": rnd(t, 3), "expected_src_t": rnd(exp_s, 3), "matched_src_t": rnd(best[1], 3),
                                "ncc": rnd(best[0], 3), "offset": rnd(best[1] - exp_s, 3), "contrast": rnd(contrast, 4),
                                "decisive": bool(contrast >= 0.02)})
        item["samples"] = samples
        item["src_fps"] = rnd(_info(p).fps, 3)
        good = [s for s in samples if s["ncc"] >= 0.6 and s["decisive"]]
        if not good:
            if any(s["ncc"] >= 0.6 for s in samples):
                item.update(status="unmeasured", reason="장면이 거의 정지해 있어 어느 소스 시각인지 구별되지 않음(NCC 곡선이 평평함)",
                            ncc_max=max(s["ncc"] for s in samples))
            else:
                item.update(status="unmeasured", reason="출력 화면과 소스 프레임이 충분히 일치하지 않음(NCC<0.6)")
        else:
            item["status"] = "measured"
            item["offset_p50"] = rnd(float(np.median([s["offset"] for s in good])), 3)
            if len(good) >= 2:
                tt = np.array([s["t"] for s in good])
                ss = np.array([s["matched_src_t"] for s in good])
                if tt.max() - tt.min() > 0.3:
                    item["speed_obs"] = rnd(float(np.polyfit(tt, ss, 1)[0]), 3)
        out.append(item)
    return {"clips": out}


# ----------------------------------------------------------------------------- logo residual
def analyze_residual(ctx: QAContext) -> dict:
    """For every clip with clean ops, check the mapped region of the output for what was
    supposed to be removed (edge-template NCC vs the original source crop + OCR)."""
    from .. import paths

    cv2 = _cv2()
    items = []
    verify = _clean_verify()
    fr = 1.0 / ctx.fps
    for ci, c in enumerate(ctx.resolved.clips):
        ops = [("delogo", r) for r in c.delogo] + [("inpaint", r) for r in c.inpaint] + [("blur", r) for r in c.blur]
        if not ops:
            continue
        p = paths.absp(c.source_path)
        for kind, r in ops:
            s0 = max(c.src_in, r.start if r.start is not None else c.src_in)
            s1 = min(c.src_out, r.end if r.end is not None else c.src_out)
            it = {"clip_id": c.id, "op": kind, "rect_src": [r.x, r.y, r.w, r.h], "src_range": [rnd(s0), rnd(s1)],
                  "reason": r.reason}
            if s1 <= s0:
                it.update(status="not_applicable", note="이 클립 구간과 겹치지 않음")
                items.append(it)
                continue
            # output times whose source time lies in [s0, s1]
            sp = float(c.speed or 1.0)
            t0 = c.out_start + (s0 - c.src_in) / sp
            t1 = c.out_start + (s1 - c.src_in) / sp
            lo = max(t0, c.out_start + (float(c.transition_in.dur or 0) if ci else 0.0) + fr)
            hi = min(t1, c.out_end - fr)
            if hi <= lo:
                it.update(status="not_applicable", note="출력에 보이는 구간 없음")
                items.append(it)
                continue
            times = [lo + (hi - lo) * q for q in (0.15, 0.5, 0.85)]
            obs = []
            for t in times:
                mr = map_src_rect(c, r, t)
                if mr is None:
                    obs.append({"t": rnd(t), "visible": False})
                    continue
                x, y, w, h = mr
                of = grab(ctx.mp4, t)
                oc = of[int(y):int(y + h), int(x):int(x + w)]
                row = {"t": rnd(t), "visible": True, "rect_out": [rnd(v, 1) for v in mr]}
                if p.is_file() and oc.size:
                    sf = grab(p, src_time(c, t))
                    sx, sy, sw, sh = r.x, r.y, r.w, r.h
                    # only the visible part of the source rect maps into mr
                    tr = clip_transform(c, t)
                    vx0, vy0 = (x - tr["tx"]) / tr["s"], (y - tr["ty"]) / tr["s"]
                    vx1, vy1 = (x + w - tr["tx"]) / tr["s"], (y + h - tr["ty"]) / tr["s"]
                    scrop = sf[max(0, int(vy0)):int(math.ceil(vy1)), max(0, int(vx0)):int(math.ceil(vx1))]
                    if scrop.size:
                        tmpl = cv2.resize(scrop, (oc.shape[1], oc.shape[0]), interpolation=cv2.INTER_AREA)
                        eg_t = edge_map(cv2.cvtColor(tmpl, cv2.COLOR_RGB2GRAY))
                        eg_o = edge_map(cv2.cvtColor(oc, cv2.COLOR_RGB2GRAY))
                        row["edge_ncc"] = rnd(ncc(eg_t, eg_o), 3)
                        row["pix_ncc"] = rnd(ncc(cv2.cvtColor(tmpl, cv2.COLOR_RGB2GRAY), cv2.cvtColor(oc, cv2.COLOR_RGB2GRAY)), 3)
                        try:
                            from .probes_text import ocr_text

                            ts_ = ocr_text(scrop, upscale=3)
                            to_ = ocr_text(oc, upscale=max(1, int(round(3 * scrop.shape[1] / max(1, oc.shape[1])))))
                            row["text_src"] = ts_
                            row["text_out"] = to_
                            row["text_sim"] = rnd(text_similarity(ts_, to_), 3) if ts_ else None
                        except Exception as e:  # OCR is extra evidence; edge NCC decides
                            row["ocr_error"] = str(e)[:200]
                        if verify is not None:
                            row["clean_verify"] = _call_verify(verify, ctx, mr, t, tmpl, row.get("text_src"))
                    row["residual"] = bool((row.get("edge_ncc") or 0) >= 0.55 or
                                           ((row.get("text_sim") or 0) >= 0.6 and len(row.get("text_src") or "") >= 3)
                                           or (row.get("clean_verify") or {}).get("present") is True)
                obs.append(row)
            it["samples"] = obs
            vis = [o for o in obs if o.get("visible")]
            if not vis:
                it.update(status="measured", residual=False, note="정리 영역이 출력 화면 밖(잘림)")
            elif any("residual" in o for o in vis):
                it.update(status="measured", residual=any(o.get("residual") for o in vis))
            else:
                it.update(status="unmeasured", reason="소스 파일이 없어 원래 오버레이와 비교 못 함")
            items.append(it)
    return {"items": items, "clean_verify_available": verify is not None}


def text_similarity(a: str | None, b: str | None) -> float:
    import re

    na = re.sub(r"[\W_]+", "", (a or "").lower())
    nb = re.sub(r"[\W_]+", "", (b or "").lower())
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


def _clean_verify():
    try:
        from ..clean.verify import residual_score  # type: ignore

        return residual_score
    except Exception:
        return None


def _call_verify(fn, ctx: QAContext, rect_out, t: float, tmpl: np.ndarray, text: str | None) -> dict:
    cv2 = _cv2()
    from .. import paths

    png = ctx.frames_dir / f"residual_tmpl_{int(t * 1000):07d}.png"
    cv2.imwrite(str(png), cv2.cvtColor(tmpl, cv2.COLOR_RGB2BGR))
    x, y, w, h = rect_out
    try:
        res = fn(ctx.mp4, {"x": x, "y": y, "w": w, "h": h, "start": t - 0.05, "end": t + 0.05}, png, [t], text or None)
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"[:300]}
    out = {"raw": _jsonable(res), "template": paths.relp(png)}
    if isinstance(res, dict):
        for k in ("residual", "present", "residual_present"):
            if isinstance(res.get(k), bool):
                out["present"] = res[k]
                break
        else:
            st = res.get("status")
            if st in ("present", "absent"):
                out["present"] = st == "present"
    return out


def _jsonable(v):
    import json

    try:
        return json.loads(json.dumps(v, default=lambda o: o.tolist() if hasattr(o, "tolist") else str(o)))
    except Exception:
        return str(v)[:500]


# ----------------------------------------------------------------------------- faces / protected
def face_detector():
    """Haar cascade from cv2.data when this OpenCV build ships it (4.x wheels), else a YuNet
    model file the user placed at $SHORTKIT_FACE_MODEL or assets/models/.  QA never downloads a
    model.  Returns (name, detect(img_rgb)->[[x,y,w,h]]) or (None, reason)."""
    cv2 = _cv2()
    casc_dir = getattr(getattr(cv2, "data", None), "haarcascades", None)
    if hasattr(cv2, "CascadeClassifier") and casc_dir:
        f = Path(casc_dir) / "haarcascade_frontalface_default.xml"
        if f.is_file():
            cc = cv2.CascadeClassifier(str(f))
            if not cc.empty():
                def det(img):
                    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
                    return [list(map(float, r)) for r in cc.detectMultiScale(g, 1.1, 5, minSize=(24, 24))]

                return "haar_frontalface_default", det
    cands = []
    if os.environ.get("SHORTKIT_FACE_MODEL"):
        cands.append(Path(os.environ["SHORTKIT_FACE_MODEL"]))
    try:
        from .. import paths

        cands += sorted(paths.absp("assets/models").glob("face_detection_yunet*.onnx"))
    except Exception:
        pass
    for m in cands:
        if m.is_file() and hasattr(cv2, "FaceDetectorYN"):
            try:
                yn = cv2.FaceDetectorYN.create(str(m), "", (320, 320), 0.7, 0.3, 5000)
            except Exception:
                continue

            def det(img, yn=yn):
                bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
                yn.setInputSize((bgr.shape[1], bgr.shape[0]))
                _, faces = yn.detect(bgr)
                return [] if faces is None else [list(map(float, f[:4])) for f in faces]

            return f"yunet:{m.name}", det
    return None, ("얼굴 검출기 없음: 이 OpenCV 빌드(cv2 %s)에는 Haar cascade(CascadeClassifier/cv2.data)가 없고, "
                  "얼굴 모델 파일(assets/models/face_detection_yunet*.onnx 또는 $SHORTKIT_FACE_MODEL)도 없음" % cv2.__version__)


def analyze_faces(ctx: QAContext, overlays: list[dict], sample_fps: float = 2.0) -> dict:
    """overlays: [{id, kind, start, end, bbox:[x,y,w,h] (MEASURED in the output)}]"""
    name, det = face_detector()
    res: dict = {"detector": name}
    if name is None:
        res["status"] = "unmeasured"
        res["reason"] = det
        return res
    hits = []
    n_frames = 0
    T = ctx.info.duration
    t = 0.25
    while t < T:
        active = [o for o in overlays if o["start"] <= t <= o["end"] and o.get("bbox")]
        if active:
            fr = grab(ctx.mp4, t)
            faces = det(fr)
            n_frames += 1
            for f in faces:
                for o in active:
                    from . import rect_intersection

                    inter = rect_intersection(f, o["bbox"])
                    if inter > 0.1 * f[2] * f[3]:
                        hits.append({"t": rnd(t, 2), "face": [rnd(v, 1) for v in f], "overlay": o["id"],
                                     "covered_frac": rnd(inter / (f[2] * f[3]), 3)})
        t += 1.0 / sample_fps
    res.update(status="measured", frames=n_frames, covered=hits)
    return res


def protected_rects_canvas(ctx: QAContext) -> list[dict]:
    """Planner-declared faces/hands/objects (plan sources[].protected, SOURCE px/time) mapped to
    canvas px for every clip that shows them.  These are declarations, not detections."""
    plan = ctx.plan or {}
    by_src = {s.get("id"): s.get("protected") or [] for s in plan.get("sources") or []}
    out = []
    for c in ctx.resolved.clips:
        for pr in by_src.get(c.source_id) or []:
            s0 = max(c.src_in, pr.get("start") if pr.get("start") is not None else c.src_in)
            s1 = min(c.src_out, pr.get("end") if pr.get("end") is not None else c.src_out)
            if s1 <= s0:
                continue
            sp = float(c.speed or 1.0)
            t0 = c.out_start + (s0 - c.src_in) / sp
            t1 = min(c.out_end, c.out_start + (s1 - c.src_in) / sp)
            mid = (t0 + t1) / 2
            mr = map_src_rect(c, pr, mid)
            if mr is not None:
                out.append({"label": pr.get("label"), "clip_id": c.id, "start": rnd(t0), "end": rnd(t1),
                            "rect": [rnd(v, 1) for v in mr]})
    return out


# ----------------------------------------------------------------------------- entry point
def probe_video(ctx: QAContext) -> dict:
    res: dict = {"resolution": [ctx.info.width, ctx.info.height], "fps": rnd(ctx.info.fps, 3),
                 "duration": rnd(ctx.info.duration, 4), "errors": {}}
    try:
        sc = scan(ctx, width=int(ctx.options.get("scan_width", 540)))
    except Exception as e:
        res["errors"]["scan"] = f"{type(e).__name__}: {e}"
        return res
    res["n_frames"] = int(len(sc["times"]))
    for name, fn in (("transitions", analyze_transitions), ("freezes", analyze_freezes), ("zoom", analyze_zoom),
                     ("decorations", analyze_decorations)):
        try:
            res[name] = fn(ctx, sc)
        except Exception as e:  # a failing analysis becomes 'unmeasured' rows, never a crash
            res["errors"][name] = f"{type(e).__name__}: {e}"
    res["_scan"] = sc                      # in-memory only (dropped before saving)
    for name, fn in (("mapping", analyze_mapping), ("residual", analyze_residual)):
        try:
            res[name] = fn(ctx)
        except Exception as e:
            res["errors"][name] = f"{type(e).__name__}: {e}"
    try:
        res["protected"] = protected_rects_canvas(ctx)
    except Exception as e:
        res["errors"]["protected"] = f"{type(e).__name__}: {e}"
    return res
