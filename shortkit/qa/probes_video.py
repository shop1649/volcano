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

from . import (QAContext, clip_at, clip_transform, ease_value, hex_rgb, map_src_rect, rect_iou, rect_xywh, rgb_hex, rnd,
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
    try:
        prot = protected_rects_canvas(ctx) if decos else []
    except Exception:
        prot = []
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
            row = _deco_measure(t, fr, m, s, d.kind, rot)
            # how much of each declared protected area do the decoration's own pixels cover?
            cov = {}
            for pi, pr in enumerate(prot):
                if pr.get("rect") is None or not (pr["start"] <= t <= pr["end"]):
                    continue
                px, py, pw, ph = pr["rect"]
                x0_, y0_ = int(px * s), int(py * s)
                x1_, y1_ = int(math.ceil((px + pw) * s)), int(math.ceil((py + ph) * s))
                area = max(1, (x1_ - x0_) * (y1_ - y0_))
                cov[pi] = round(float(m[max(0, y0_):y1_, max(0, x0_):x1_].sum()) / area, 4)
            if cov:
                row["prot_cover"] = cov
            st["rows"].append(row)
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


# ----------------------------------------------------------------------------- planned-geometry frame match
GEO_WORK_W = 240


def _region_gray(ctx: QAContext, c, frame: np.ndarray, work_w: int = GEO_WORK_W) -> np.ndarray:
    cv2 = _cv2()
    rx, ry, rw, rh = rect_xywh(c.region)
    wh = max(8, int(round(rh * work_w / rw)))
    reg = frame[int(ry):int(ry + rh), int(rx):int(rx + rw)]
    return cv2.cvtColor(cv2.resize(reg, (work_w, wh), interpolation=cv2.INTER_AREA), cv2.COLOR_RGB2GRAY).astype(np.float32)


def _warp_planned(c, src_frame: np.ndarray, t: float, zoom_extra: float = 1.0, work_w: int = GEO_WORK_W) -> np.ndarray:
    """The source frame placed in the clip region exactly as the plan says at output time t
    (``clip_transform``: fit + eased zoom), optionally scaled by ``zoom_extra`` about the region centre."""
    cv2 = _cv2()
    rx, ry, rw, rh = rect_xywh(c.region)
    k = work_w / rw
    wh = max(8, int(round(rh * k)))
    tr = clip_transform(c, t)
    s_, tx, ty = tr["s"] * zoom_extra, tr["tx"], tr["ty"]
    if zoom_extra != 1.0:
        cx, cy = rx + rw / 2.0, ry + rh / 2.0
        tx, ty = cx - (cx - tx) * zoom_extra, cy - (cy - ty) * zoom_extra
    M = np.array([[s_ * k, 0, (tx - rx) * k], [0, s_ * k, (ty - ry) * k]], np.float32)
    return cv2.cvtColor(cv2.warpAffine(src_frame, M, (work_w, wh), flags=cv2.INTER_AREA), cv2.COLOR_RGB2GRAY).astype(np.float32)


def planned_frame_match(ctx: QAContext, c, t: float, search_s: float | None = None, zoom_alt: float | None = None) -> dict:
    """Does the OUTPUT frame at t show the planned source frame under the planned geometry?
    Source frames within +-``search_s`` (default 1.5 source frames) of the planned source time are
    tried; -> {ncc, src_t, expected_src_t[, ncc_alt]} where ncc_alt is the same match with the picture
    scaled by ``zoom_alt`` (a zoom the plan does not have) -- the gap tells whether the geometry
    test can see a zoom of that size at all.  Empty dict when a file cannot be read."""
    from .. import paths

    p = paths.absp(c.source_path)
    if not p.is_file():
        return {}
    try:
        of = grab(ctx.mp4, t)
        rate = _info(p).fps or 30.0
        es = src_time(c, t)
        w = search_s if search_s is not None else 1.5 / rate
        ts, frs = grab_window(p, max(0.0, es - w), 2 * w + 1.0 / rate)
    except Exception:
        return {}
    if not frs:
        return {}
    og = _region_gray(ctx, c, of)
    vals = [ncc(_warp_planned(c, f, t), og) for f in frs]
    j = int(np.argmax(vals))
    out = {"t": rnd(t, 3), "expected_src_t": rnd(es, 3), "src_t": rnd(ts[j], 3), "ncc": rnd(vals[j], 4)}
    if zoom_alt is not None:
        out["ncc_alt"] = rnd(ncc(_warp_planned(c, frs[j], t, zoom_extra=zoom_alt), og), 4)
    return out


GEO_NCC_MIN = 0.95          # output frame == planned source frame under the planned geometry
GEO_ALT_MARGIN = 0.02       # ... and a 4 % zoom of it fits clearly worse (the test can see such a zoom)


def geometry_check(ctx: QAContext, c, n: int = 5, zoom_alt: float = 1.04) -> dict:
    """Planned geometry verified directly: at ``n`` times across the clip (outside transitions and
    freezes) the output region equals the planned source frame placed by ``clip_transform`` (NCC >=
    GEO_NCC_MIN) and the same frame zoomed by ``zoom_alt`` fits worse by >= GEO_ALT_MARGIN.  Feature-based
    scale curves are fooled by large moving subjects (people walking to the camera); this is not."""
    fr = 1.0 / ctx.fps
    clips = ctx.resolved.clips
    ci = next((i for i, x in enumerate(clips) if x.id == c.id), 0)
    t_lo = c.out_start + (float(c.transition_in.dur or 0) if ci else 0.0) + 2 * fr
    nxt = clips[ci + 1] if ci + 1 < len(clips) else None
    t_hi = (nxt.out_start if nxt else c.out_end) - 2 * fr
    ranges = [(t_lo, t_hi)]
    if c.freeze is not None:
        ranges = [(t_lo, min(t_hi, c.freeze.out_start - fr)), (c.freeze.out_start + c.freeze.hold + fr, t_hi)]
    span = sum(max(0.0, b - a) for a, b in ranges)
    if span <= 0.2:
        return {"status": "unmeasured", "reason": "비교할 구간이 너무 짧음"}
    times, acc = [], 0.0
    targets = [span * (k + 0.5) / n for k in range(n)]
    for a, b in ranges:
        L = max(0.0, b - a)
        times += [a + (q - acc) for q in targets if acc <= q < acc + L]
        acc += L
    rows = [r for r in (planned_frame_match(ctx, c, t, zoom_alt=zoom_alt) for t in times) if r]
    if len(rows) < 3:
        return {"status": "unmeasured", "reason": "프레임을 읽지 못함", "samples": rows}
    nccs = [r["ncc"] for r in rows]
    gaps = [r["ncc"] - r["ncc_alt"] for r in rows]
    confirmed = float(np.median(nccs)) >= GEO_NCC_MIN and min(nccs) >= GEO_NCC_MIN - 0.03 and \
        float(np.median(gaps)) >= GEO_ALT_MARGIN
    return {"status": "measured", "confirmed": bool(confirmed), "ncc_median": rnd(float(np.median(nccs)), 4),
            "ncc_min": rnd(min(nccs), 4), "zoom_alt": zoom_alt, "alt_gap_median": rnd(float(np.median(gaps)), 4),
            "samples": rows,
            "method": "출력 영상 영역 vs 계획 기하(clip_transform)로 놓은 소스 프레임 NCC, 4% 확대 대안과 비교"}


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
            # a blend must happen HERE: a fitted start/length outside the searched window is not a crossfade
            # (two nearly identical pictures around a jump cut gave t=-49 s, dur=81 s on test-coverage-001 s5)
            win = max(dur, 0.2) + 4 * fr
            if not (t_b - win <= t0 <= t_b + win and 2 * fr <= 1.0 / k <= 2 * win + 4 * fr):
                return None
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
    clips = ctx.resolved.clips
    for ci, c in enumerate(clips[1:], start=1):
        tr = c.transition_in
        dur = float(tr.dur or 0.0)
        obs = _classify_boundary(sc, d, flashes, c.out_start, dur, fps)
        exp = {"type": tr.type, "t": round(c.out_start, 4), "dur": round(dur, 4),
               "color": tr.color if tr.type == "flash" else None}
        prev = clips[ci - 1]
        cont = tr.type == "cut" and continuous_edit(prev, c)
        if cont:
            # the plan continues the same shot (same source, next source frame, same speed): there is no
            # picture change to see -- the output is right when it shows none
            exp["continuous"] = True
            exp["type_visible"] = "none"
        elif tr.type == "cut" and obs["type"] != "cut":
            # a jump between two nearly identical pictures shows no frame-difference spike: tell the two
            # sides apart by which planned source frame each output frame shows
            mb = boundary_by_mapping(ctx, prev, c)
            obs["mapping"] = mb
            if mb.get("verified"):
                obs = {"type": "cut", "t": round(c.out_start, 4), "dur": 0.0, "score": None, "method": "mapping",
                       "mapping": mb, "diff_obs": obs}
        ok = obs["type"] == (exp.get("type_visible") or tr.type)
        timing_ok = None
        if cont:
            timing_ok = ok
        elif ok and tr.type == "cut":
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
                # a low-fps / slowed source shows each source frame for several output frames: fast subject
                # motion then changes the picture in one step (test-coverage-001 s5: 12 fps at 0.5x -> a step
                # every 5 frames).  If both frames are exactly the planned source frames, it is the source's own
                # motion, not an edit.
                st = source_step(ctx, c, e["t"] - 1.0 / fps, e["t"])
                e["source_step"] = st
                if st.get("explained"):
                    continue
        kept.append(e)
    extra = kept
    return {"boundaries": bounds, "unexpected": extra, "flashes": flashes,
            "diff_stats": {"p50": rnd(np.median(d[1:]) if len(d) > 1 else None, 3),
                           "p90": rnd(np.percentile(d[1:], 90) if len(d) > 1 else None, 3)}}


def continuous_edit(prev, c) -> bool:
    """The boundary continues the same shot: same source file, the next clip starts where the previous one
    stops (within one source frame), same speed, no crop/geometry change."""
    if prev.source_path != c.source_path or abs(float(prev.speed or 1) - float(c.speed or 1)) > 1e-6:
        return False
    rate = _info_safe(c.source_path)
    if abs(float(c.src_in) - float(prev.src_out)) > 1.0 / rate + 1e-6:
        return False
    same_geo = rect_xywh(prev.region) == rect_xywh(c.region) and (prev.crop == c.crop) and prev.zoom is None \
        and c.zoom is None and tuple(prev.src_size) == tuple(c.src_size) and (prev.fit or "cover") == (c.fit or "cover")
    return bool(same_geo)


def _info_safe(stored) -> float:
    from .. import paths

    try:
        return float(_info(paths.absp(stored)).fps or 30.0)
    except Exception:
        return 30.0


def boundary_by_mapping(ctx: QAContext, prev, c, margin: float = 0.01) -> dict:
    """A hard cut between two similar pictures: the output frame one frame BEFORE the boundary must show
    the previous clip's planned source frame and the frame one frame AFTER it the next clip's -- each
    matched better than the other side's frame by ``margin`` NCC -- else the two sides are not told apart."""
    from .. import paths

    fr = 1.0 / ctx.fps
    t0, t1 = c.out_start - fr, c.out_start + fr
    pa, pb = planned_frame_match(ctx, prev, t0), planned_frame_match(ctx, c, t1)
    if not pa or not pb:
        return {"verified": False, "reason": "프레임을 읽지 못함"}
    try:
        fa = grab(paths.absp(prev.source_path), float(pa["src_t"]))
        fb = grab(paths.absp(c.source_path), float(pb["src_t"]))
        oa, ob = _region_gray(ctx, prev, grab(ctx.mp4, t0)), _region_gray(ctx, c, grab(ctx.mp4, t1))
    except Exception:
        return {"verified": False, "reason": "프레임을 읽지 못함"}
    cross_a = ncc(_warp_planned(c, fb, t1), oa)        # before-frame vs the NEXT clip's frame
    cross_b = ncc(_warp_planned(prev, fa, t0), ob)     # after-frame vs the PREVIOUS clip's frame
    ok = pa["ncc"] >= 0.9 and pb["ncc"] >= 0.9 and pa["ncc"] - cross_a >= margin and pb["ncc"] - cross_b >= margin
    return {"verified": bool(ok), "before": {"t": rnd(t0, 3), "own": pa["ncc"], "other": rnd(cross_a, 4), "src_t": pa["src_t"]},
            "after": {"t": rnd(t1, 3), "own": pb["ncc"], "other": rnd(cross_b, 4), "src_t": pb["src_t"]},
            "margin": margin}


def source_step(ctx: QAContext, c, t_prev: float, t_cur: float) -> dict:
    """Both output frames around a picture step show exactly the planned source frames (NCC >= 0.9,
    within one source frame of the plan) -> the step is the source's own frame change."""
    a, b = planned_frame_match(ctx, c, t_prev), planned_frame_match(ctx, c, t_cur)
    if not a or not b:
        return {"explained": False}
    rate = _info_safe(c.source_path)
    near = all(abs(float(r["src_t"]) - float(r["expected_src_t"])) <= 1.0 / rate + 1e-3 for r in (a, b))
    return {"explained": bool(a["ncc"] >= 0.9 and b["ncc"] >= 0.9 and near), "before": a, "after": b}


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
        # the picture can also change scale because the SOURCE moves (people walking to the camera,
        # camera zoom): measure the same thing on the source frames and divide it out
        try:
            sr_ = source_scale(ctx, c, float(arr[0, 0]), float(arr[-1, 0]))
        except Exception:
            sr_ = None
        item["source_ratio"] = rnd(sr_, 4) if sr_ else None
        if sr_:
            item["zoom_ratio_corrected"] = rnd(item["measured_final_ratio"] / sr_, 4)
        item["status"] = "measured"
        item["tolerance"] = {"ratio": 0.04, "t50_s": max(0.1, 3 * fr)}
        if z is None and (item.get("measured_max_dev") or 0) > 0.05:
            # the scale curve says "zoom" on a clip the plan does not zoom: check the geometry directly
            try:
                item["geometry"] = geometry_check(ctx, c)
            except Exception as e:
                item["geometry"] = {"status": "unmeasured", "reason": f"{type(e).__name__}: {e}"[:200]}
        out.append(item)
    # consecutive zoom count (same effect stacked on consecutive segments): a clip counts when it zooms by
    # plan, or when its scale curve moves and the planned (unzoomed) geometry does NOT reproduce the output
    zoomed = [((it.get("measured_max_dev") or 0) > 0.05) and
              not ((it.get("geometry") or {}).get("confirmed") is True) for it in out]
    run = best = 0
    for zf in zoomed:
        run = run + 1 if zf else 0
        best = max(best, run)
    return {"clips": out, "max_consecutive_measured": best}


def source_scale(ctx: QAContext, clip, t0: float, t1: float, work_w: int = 540) -> float | None:
    """Similarity-transform scale between the SOURCE frames shown at output times t0 and t1,
    both fitted into the clip region WITHOUT the plan's zoom."""
    from .. import paths

    cv2 = _cv2()
    p = paths.absp(clip.source_path)
    if not p.is_file():
        return None
    rx, ry, rw, rh = rect_xywh(clip.region)
    k = work_w / rw
    wh = max(8, int(round(rh * k)))
    tr = clip_transform(clip, None)
    M = np.array([[tr["s"] * k, 0, (tr["tx"] - rx) * k], [0, tr["s"] * k, (tr["ty"] - ry) * k]], np.float32)
    ims = []
    for t in (t0, t1):
        f = grab(p, src_time(clip, t))
        ims.append(cv2.cvtColor(cv2.warpAffine(f, M, (work_w, wh), flags=cv2.INTER_AREA), cv2.COLOR_RGB2GRAY))
    orb = cv2.ORB_create(nfeatures=700, fastThreshold=12)
    k0, d0 = orb.detectAndCompute(ims[0], None)
    k1, d1 = orb.detectAndCompute(ims[1], None)
    est = _similarity(k0, d0, k1, d1)
    if est is None or est[3] < 15:
        return None
    return float(est[0])


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
        pc: dict = {}
        for r in inside:
            for pi, v in (r.get("prot_cover") or {}).items():
                if v > pc.get(pi, {}).get("max_frac", -1):
                    pc[pi] = {"max_frac": v, "t": r["t"]}
        item["protected_cover"] = pc
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
STILL_NCC_MIN = GEO_NCC_MIN   # still scene: every sampled output frame == the planned source frame (same criterion as
#                              the zoom-geometry check: output region vs planned source frame under the planned geometry)
FLAT_STD = 2.0                # grey-level std below which a (masked) frame has no texture -> NCC undefined


def overlay_keep_mask(ctx: QAContext, c, t: float, rx: float, ry: float, k: float, shape: tuple[int, int]) -> np.ndarray:
    """True where the output region at output time ``t`` shows only the clip's footage: captions on screen (ink box
    incl. outline / label box, with room for entrance scaling), decorations and the clip's clean-op rects
    (delogo / blur / inpaint, mapped with the zoom) are masked out.  Work grid: canvas (x, y) -> ((x-rx)k, (y-ry)k)."""
    h, w = shape
    keep = np.ones((h, w), bool)

    def cut(x, y, ww, hh, pad):
        x0, y0 = int(math.floor((x - pad - rx) * k)), int(math.floor((y - pad - ry) * k))
        x1, y1 = int(math.ceil((x + ww + pad - rx) * k)), int(math.ceil((y + hh + pad - ry) * k))
        x0, y0, x1, y1 = max(0, x0), max(0, y0), min(w, x1), min(h, y1)
        if x1 > x0 and y1 > y0:
            keep[y0:y1, x0:x1] = False

    res = getattr(ctx, "resolved", None)
    for cap in getattr(res, "captions", None) or []:
        mo = getattr(cap, "motion_out", None) or {}
        t_end = float(cap.end) + float(mo.get("dur_s") or 0.0)
        if not (float(cap.start) - 0.05 <= t <= t_end + 0.05):
            continue
        box = getattr(cap, "box", None) or {}
        rect = box.get("rect") if box.get("enabled") else None
        bx, by, bw, bh = (float(v) for v in rect) if rect else rect_xywh(cap.bbox)
        mi = getattr(cap, "motion_in", None) or {}
        grow = max(1.0, float(mi.get("scale_from") or 1.0)) if mi.get("type") == "pop" else 1.0
        cut(bx - bw * (grow - 1) / 2, by - bh * (grow - 1) / 2, bw * grow, bh * grow, max(8.0, 0.25 * bh))
    for d in getattr(res, "decorations", None) or []:
        if not (float(d.start) - 0.05 <= t <= float(d.end) + 0.05):
            continue
        kf = _deco_expected_kf(d, t)
        dw, dh = float(kf.get("w") or 120.0), float(kf.get("h") or 120.0)
        stroke = float((d.style or {}).get("stroke_px") or 8.0)
        if d.kind == "arrow":        # tip at (x, y), any rotation
            r_ = max(dw, dh) + stroke
            cut(float(kf["x"]) - r_, float(kf["y"]) - r_, 2 * r_, 2 * r_, 6.0)
        else:                        # circle / box centred at (x, y)
            cut(float(kf["x"]) - dw / 2, float(kf["y"]) - dh / 2, dw, dh, stroke + 6.0)
    st = src_time(c, t)
    for r in list(getattr(c, "delogo", None) or []) + list(getattr(c, "inpaint", None) or []) + \
            list(getattr(c, "blur", None) or []):
        if getattr(r, "start", None) is not None and st < float(r.start) - 0.05:
            continue
        if getattr(r, "end", None) is not None and st > float(r.end) + 0.05:
            continue
        mr = map_src_rect(c, r, t)
        if mr is not None:
            cut(*mr, 6.0)
    return keep


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
        src_rate = float(_info(p).fps or 30.0)
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
        # stage 2 (only when no stage-1 sample is decisive): more positions across the clip, because the source
        # time can only be told where the picture moves -- a clip whose three fixed positions all fall in still
        # stretches (test-pipeline-001 s4 after trimming: people holding a pose) was left unmeasured although it
        # has moving moments elsewhere
        extra_t = []
        for a, b in ranges:
            if b - a > 0.15:
                extra_t += [a + (b - a) * q for q in (0.05, 0.1, 0.3, 0.4, 0.6, 0.7, 0.9, 0.95)]
        rx, ry, rw, rh = rect_xywh(c.region)
        k = work_w / rw
        wh = max(8, int(round(rh * k)))
        samples = []
        slowed = abs(float(c.speed or 1.0) - 1.0) > 1e-3
        for t, stage in [(t_, 1) for t_ in cand_t] + [(t_, 2) for t_ in extra_t]:
            # a speed change needs the slope over many samples (source-frame quantisation): keep going then
            if stage == 2 and not slowed and any(s_["decisive"] and s_["ncc"] >= 0.6 for s_ in samples):
                break
            try:
                of = grab(ctx.mp4, t)
            except Exception:
                continue
            oreg = cv2.resize(of[int(ry):int(ry + rh), int(rx):int(rx + rw)], (work_w, wh), interpolation=cv2.INTER_AREA)
            og = cv2.cvtColor(oreg, cv2.COLOR_RGB2GRAY).astype(np.float32)
            exp_s = src_time(c, t)
            try:
                ts, frs = grab_window(p, max(0.0, exp_s - 1.2), 2.4)
            except Exception:
                continue
            tr = clip_transform(c, t)
            M = np.array([[tr["s"] * k, 0, (tr["tx"] - rx) * k], [0, tr["s"] * k, (tr["ty"] - ry) * k]], np.float32)
            warped = []
            for st, sf in zip(ts, frs):
                w_ = cv2.warpAffine(sf, M, (work_w, wh), flags=cv2.INTER_AREA)
                warped.append(cv2.cvtColor(w_, cv2.COLOR_RGB2GRAY).astype(np.float32))
            if not warped:
                continue
            # compare only where the source actually changes over the search window (people moving);
            # a still background matches every source time equally
            stack = np.stack(warped)
            tstd = stack.std(axis=0)
            thr = max(3.0, float(np.percentile(tstd, 85)))
            mmask = tstd >= thr
            use_mask = mmask.mean() >= 0.01
            vals = []
            best = (-2.0, None)
            for st, g in zip(ts, warped):
                v = ncc(g[mmask], og[mmask]) if use_mask else ncc(g, og)
                vals.append(v)
                if v > best[0]:
                    best = (v, st)
            # the planned source frame itself (+-1.5 source frames of the planned time), overlays masked: for a
            # still scene, where no time stands out, this says whether the output shows the planned picture at all
            keep = overlay_keep_mask(ctx, c, t, rx, ry, k, og.shape)
            near = [g for st, g in zip(ts, warped) if abs(st - exp_s) <= 1.5 / src_rate]
            planned = None
            if near and keep.mean() >= 0.2:
                if float(og[keep].std()) < FLAT_STD or max(float(g[keep].std()) for g in near) < FLAT_STD:
                    planned = "flat"
                else:
                    planned = max(ncc(g[keep], og[keep]) for g in near)
            if best[1] is not None:
                # does the best source time stand out?  prominence = best minus the best match at least
                # 0.25 s away (a still scene matches every time); a best at the window edge may lie outside
                far = [v for st, v in zip(ts, vals) if abs(st - best[1]) >= 0.25]
                prominence = float(best[0] - max(far)) if far else 0.0
                at_edge = best[1] <= ts[0] + 1e-3 or best[1] >= ts[-1] - 1e-3
                full_ncc = ncc(warped[int(np.argmax(vals))], og)
                samples.append({"t": rnd(t, 3), "expected_src_t": rnd(exp_s, 3), "matched_src_t": rnd(best[1], 3),
                                "ncc": rnd(full_ncc, 3), "ncc_moving": rnd(best[0], 3), "offset": rnd(best[1] - exp_s, 3),
                                "prominence": rnd(prominence, 4), "moving_frac": rnd(float(mmask.mean()), 3),
                                "at_window_edge": bool(at_edge), "stage": stage,
                                "decisive": bool(use_mask and prominence >= 0.03 and not at_edge),
                                "ncc_planned": planned if planned in (None, "flat") else rnd(planned, 4),
                                "overlay_masked_frac": rnd(1.0 - float(keep.mean()), 3)})
        item["samples"] = samples
        item["src_fps"] = rnd(_info(p).fps, 3)
        good = [s for s in samples if s["ncc"] >= 0.6 and s["decisive"]]
        if not good:
            # no sample tells the source time -> still-scene rule on the planned frames themselves
            pl = [s["ncc_planned"] for s in samples if isinstance(s.get("ncc_planned"), (int, float))]
            n_flat = sum(1 for s in samples if s.get("ncc_planned") == "flat")
            item["still"] = {"threshold": STILL_NCC_MIN, "n_samples": len(samples), "n_compared": len(pl),
                             "n_flat": n_flat, "ncc_planned_min": rnd(min(pl), 4) if pl else None,
                             "ncc_planned": pl}
            if len(pl) >= 2 and len(pl) == len(samples) and min(pl) >= STILL_NCC_MIN:
                item.update(status="measured", mode="still_match", offset_p50=None,
                            reason="정지 장면: 계획 구간과 시각적으로 동일 (시점 특정 불가)")
            elif pl and min(pl) < STILL_NCC_MIN:
                bad = [s for s in samples if isinstance(s.get("ncc_planned"), (int, float)) and s["ncc_planned"] < STILL_NCC_MIN]
                item.update(status="measured", mode="still_mismatch", offset_p50=None,
                            reason=(f"출력 화면이 계획한 소스 프레임과 다름: {len(bad)}/{len(samples)} 시각에서 계획 프레임 NCC < "
                                    f"{STILL_NCC_MIN} (최저 {min(pl):.3f} @ {bad[0]['t'] if bad else '?'}s; 자막·장식·가림 영역 제외)"),
                            mismatch_times=[s["t"] for s in bad])
            elif any(s["ncc"] >= 0.6 for s in samples):
                item.update(status="unmeasured", reason="장면이 거의 정지해 있어 어느 소스 시각인지 구별되지 않음(NCC 곡선이 평평함)"
                            + (f"; 평평한(무늬 없는) 화면 {n_flat}개라 계획 프레임 대조도 못 함" if n_flat else ""),
                            ncc_max=max(s["ncc"] for s in samples))
            else:
                item.update(status="unmeasured", reason="출력 화면과 소스 프레임이 충분히 일치하지 않음(NCC<0.6)"
                            + (f"; 평평한(무늬 없는) 화면 {n_flat}개" if n_flat else ""))
        else:
            item["status"] = "measured"
            item["offset_p50"] = rnd(float(np.median([s["offset"] for s in good])), 3)
            if len(good) >= 2:
                tt = np.array([s["t"] for s in good])
                ss = np.array([s["matched_src_t"] for s in good])
                if tt.max() - tt.min() > 0.3:
                    item["speed_obs"] = rnd(float(np.polyfit(tt, ss, 1)[0]), 3)
                    # matched source times are whole source frames: the slope cannot be known better than one
                    # source frame over the sampled source span
                    span = float(ss.max() - ss.min())
                    fps_s = float(item.get("src_fps") or 30.0)
                    item["speed_quant_frac"] = rnd((1.0 / fps_s) / span, 4) if span > 0 else None
                    item["speed_samples"] = len(good)
        out.append(item)
    return {"clips": out}


# ----------------------------------------------------------------------------- logo residual
def original_source_path(ctx: QAContext, c) -> Path:
    """Absolute path of the ORIGINAL source of clip ``c`` (plan sources[].path), falling back to
    ``clip.source_path`` (which may be a cleaned intermediate)."""
    from .. import paths

    for s in (ctx.plan or {}).get("sources") or []:
        if s.get("id") == c.source_id and s.get("path"):
            return paths.absp(s["path"])
    return paths.absp(c.source_path)


def analyze_residual(ctx: QAContext) -> dict:
    """For every clip with clean ops, check the mapped region of the output for what was
    supposed to be removed (edge-template NCC vs the original source crop + OCR)."""
    cv2 = _cv2()
    items = []
    verify = _clean_verify()
    fr = 1.0 / ctx.fps
    for ci, c in enumerate(ctx.resolved.clips):
        ops = [("delogo", r) for r in c.delogo] + [("inpaint", r) for r in c.inpaint] + [("blur", r) for r in c.blur]
        if not ops:
            continue
        # compare with the ORIGINAL source: for inpaint ops clip.source_path is the cleaned intermediate
        # (warehouse/cache/clean/...), whose pixels are already inpainted and would match the output
        p = original_source_path(ctx, c)
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
            it["resolution"] = [ctx.info.width, ctx.info.height]
            if not vis:
                it.update(status="measured", residual=False, note="정리 영역이 출력 화면 밖(잘림)")
            elif any("residual" in o for o in vis):
                it.update(status="measured", residual=any(o.get("residual") for o in vis))
            else:
                it.update(status="unmeasured", reason="소스 파일이 없어 원래 오버레이와 비교 못 함")
            items.append(it)
    return {"items": items, "clean_verify_available": verify is not None}


# ----------------------------------------------------------------------------- overlay provenance
PROV_MARGIN_S = 0.1


def _transition_guard(ctx: QAContext, c, t: float) -> bool:
    """True when ``t`` is safely inside clip ``c`` alone (no crossfade/flash of it or the next clip)."""
    fr = 1.0 / ctx.fps
    if clip_at(ctx.resolved, t) is not c:
        return False
    clips = ctx.resolved.clips
    i = next((k for k, x in enumerate(clips) if x is c), None)
    for x in ([c] + ([clips[i + 1]] if i is not None and i + 1 < len(clips) else [])):
        tr = x.transition_in
        d = float(getattr(tr, "dur", 0) or 0)
        if getattr(tr, "type", "cut") in ("flash", "crossfade") and d > 0:
            if x.out_start - d / 2 - 2 * fr <= t <= x.out_start + d + 2 * fr:
                return False
    return c.out_start + fr <= t <= c.out_end - fr


def _prov_times(ctx: QAContext, c, s0: float, s1: float, n: int = 3) -> tuple[list[float], list[float]]:
    """Output times inside clip ``c`` whose SOURCE time lies in [s0, s1]: (no-zoom times, zoom times)."""
    fr = 1.0 / ctx.fps
    grid = np.arange(c.out_start + fr, c.out_end - fr, max(fr, 0.05))
    ok = [float(t) for t in grid if s0 + PROV_MARGIN_S <= src_time(c, float(t)) <= s1 - PROV_MARGIN_S
          and _transition_guard(ctx, c, float(t))]
    plain = [t for t in ok if c.zoom is None or abs(zoom_scale(c, t) - 1.0) < 1e-4]
    zoomed = [t for t in ok if t not in plain]

    def spread(v):
        if len(v) <= n:
            return [round(t, 3) for t in v]
        return [round(v[int(round(q * (len(v) - 1)))], 3) for q in np.linspace(0.15, 0.85, n)]
    return spread(plain), spread(zoomed)


def _source_sha(ctx: QAContext, sid: str, ps: dict) -> tuple[str | None, str]:
    from .. import paths
    from ..util.hashing import sha256_file

    if ps.get("sha256"):
        return str(ps["sha256"]), "plan sources[].sha256"
    p = paths.absp(ps["path"]) if ps.get("path") else None
    if p is not None and p.is_file():
        return sha256_file(p), "소스 파일 sha256 계산"
    return None, "소스 경로·sha256 없음"


def _visible_template(ctx: QAContext, c, o: dict, rect_out: dict, t_ref: float | None) -> tuple[str | None, bool]:
    """Template png for the part of the overlay that is visible on the canvas (the stored template
    is the whole SOURCE rect; a crop that cuts it would otherwise stretch the template)."""
    from .. import paths

    cv2 = _cv2()
    tpl = o.get("template")
    if not tpl or not paths.absp(tpl).is_file():
        return None, False
    tr = clip_transform(c, t_ref)
    s, tx, ty = tr["s"], tr["tx"], tr["ty"]
    r = o["rect"]
    vx0 = (rect_out["x"] - tx) / s
    vy0 = (rect_out["y"] - ty) / s
    vx1 = (rect_out["x"] + rect_out["w"] - tx) / s
    vy1 = (rect_out["y"] + rect_out["h"] - ty) / s
    rw, rh = float(r["w"]), float(r["h"])
    frac = max(0.0, min(vx1, r["x"] + rw) - max(vx0, r["x"])) * max(0.0, min(vy1, r["y"] + rh) - max(vy0, r["y"])) / max(1.0, rw * rh)
    if frac >= 0.97:
        return tpl, False
    img = cv2.imread(str(paths.absp(tpl)), cv2.IMREAD_COLOR)
    if img is None:
        return None, False
    ky, kx = img.shape[0] / max(1.0, rh), img.shape[1] / max(1.0, rw)
    x0 = int(max(0, math.floor((max(vx0, r["x"]) - r["x"]) * kx)))
    y0 = int(max(0, math.floor((max(vy0, r["y"]) - r["y"]) * ky)))
    x1 = int(min(img.shape[1], math.ceil((min(vx1, r["x"] + rw) - r["x"]) * kx)))
    y1 = int(min(img.shape[0], math.ceil((min(vy1, r["y"] + rh) - r["y"]) * ky)))
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None, True
    out = ctx.frames_dir / f"prov_tmpl_{c.id}_{o.get('id')}.png"
    cv2.imwrite(str(out), img[y0:y1, x0:x1])
    return paths.relp(out), True


def analyze_provenance(ctx: QAContext) -> dict:
    """Original overlays recorded by ``shortkit clean detect`` for each SOURCE
    (warehouse/overlays/<source sha256>.json: rect/template/text/start/end in SOURCE px/time) are
    looked for in the FINAL MP4 with ``shortkit.clean.verify.residual_score``.  Rects are mapped
    with ``clean.verify.source_rect_to_canvas`` at output times inside the clip's source range
    (outside transitions; while a zoom is active QA's own zoom-aware mapping is used instead).
    The document's own unmeasured checks (static text-free logos, corners) are carried along."""
    from .. import paths
    from . import tesseract_env

    try:
        from ..clean.detect import load_overlays, overlays_path
        from ..clean.verify import residual_score, source_rect_to_canvas
    except Exception as e:
        return {"status": "unavailable", "reason": f"shortkit.clean 사용 불가({type(e).__name__}: {e})"[:300], "sources": []}
    plan_srcs = {s.get("id"): s for s in (ctx.plan or {}).get("sources") or []}
    by_src: dict = {}
    for c in ctx.resolved.clips:
        by_src.setdefault(c.source_id, []).append(c)
    W, H = ctx.info.width, ctx.info.height
    out_sources = []
    for sid, clips in by_src.items():
        ps = plan_srcs.get(sid) or {"path": clips[0].source_path}
        sha, how = _source_sha(ctx, sid, ps)
        ent: dict = {"source_id": sid, "path": ps.get("path"), "sha256": sha, "sha256_from": how, "items": []}
        out_sources.append(ent)
        if sha is None:
            ent.update(status="unmeasured", reason=how)
            continue
        doc = load_overlays(sha)
        ent["record"] = paths.relp(overlays_path(sha)) if doc is not None else None
        if doc is None or "overlays" not in doc:
            ent.update(status="no_record", reason=(f"출처 기록 없음(warehouse/overlays/{sha[:12]}….json) — "
                                                   f"`python -m shortkit clean detect --source {ps.get('path')}`"))
            continue
        ent["status"] = "measured"
        res_src = (doc.get("source") or {}).get("resolution")
        used = [[float(c.src_in), float(c.src_out)] for c in clips]
        ent["used_src_ranges"] = used
        for o in doc.get("overlays") or []:
            rres = o.get("resolution") or res_src
            for c in clips:
                rect = dict(o["rect"])
                sw, sh = c.src_size
                if rres and sw and (int(rres[0]), int(rres[1])) != (int(sw), int(sh)):
                    kx, ky = sw / float(rres[0]), sh / float(rres[1])
                    rect = {"x": rect["x"] * kx, "y": rect["y"] * ky, "w": rect["w"] * kx, "h": rect["h"] * ky}
                o_end = float(o["end"]) if o.get("end") is not None else float(c.src_out)
                s0, s1 = max(float(c.src_in), float(o.get("start") or 0.0)), min(float(c.src_out), o_end)
                it = {"overlay_id": o.get("id"), "kind": o.get("kind"), "text": o.get("text"), "clip_id": c.id,
                      "rect_src": {k: rnd(rect[k], 1) for k in ("x", "y", "w", "h")},
                      "resolution_src": list(rres) if rres else [sw, sh], "overlay_src_range": [o.get("start"), o.get("end")],
                      "src_range_used": [rnd(s0), rnd(s1)], "template": o.get("template")}
                if s1 - s0 <= 2 * PROV_MARGIN_S:
                    continue                              # overlay not in the part of the source this clip uses
                ent["items"].append(it)
                plain, zoomed = _prov_times(ctx, c, s0, s1)
                if not plain and not zoomed:
                    it.update(status="unmeasured", residual=None, reason="출력에서 이 구간을 전환 없이 보여 주는 프레임이 없음")
                    continue
                if plain:
                    ro = source_rect_to_canvas(rect, c)
                    it["mapping"] = "clean.verify.source_rect_to_canvas"
                    if ro is None:
                        it.update(status="measured", residual=False, how="removed_by_crop", times=plain,
                                  note="잘라내기/영상 영역 밖이라 출력 화면에 없음(기하 계산)")
                        continue
                    groups = [(plain, ro)]
                else:
                    it["mapping"] = "qa.map_src_rect(줌 적용 좌표)"
                    groups = []
                    for t in zoomed:
                        mr = map_src_rect(c, rect, t)
                        if mr is not None:
                            groups.append(([t], {"x": mr[0], "y": mr[1], "w": mr[2], "h": mr[3]}))
                    if not groups:
                        it.update(status="measured", residual=False, how="removed_by_crop", times=zoomed,
                                  note="줌·잘라내기로 출력 화면 밖(기하 계산)")
                        continue
                per, stats = [], []
                for times, ro in groups:
                    tpl, cropped = _visible_template(ctx, c, {**o, "rect": rect}, ro, times[0] if c.zoom else None)
                    try:
                        with tesseract_env():
                            r = residual_score(ctx.mp4, ro, tpl, times, o.get("text"))
                    except Exception as e:
                        stats.append(None)
                        per.append({"times": times, "error": f"{type(e).__name__}: {e}"[:300]})
                        continue
                    stats.append(r)
                    per.append({"times": times, "rect_out": {k: rnd(ro[k], 1) for k in ("x", "y", "w", "h")},
                                "template": tpl, "template_cropped": cropped, "max_ncc": r.get("max_ncc"),
                                "max_tile_ncc": r.get("max_tile_ncc"), "ocr_hits": r.get("ocr_hits"),
                                "ocr_partial_hits": r.get("ocr_partial_hits"), "residual": r.get("residual"),
                                "status": r.get("status"), "per_time": r.get("per_time")})
                ok = [r for r in stats if r is not None and r.get("status") == "measured"]
                it.update(how="pixels", resolution_out=[W, H], checks=per,
                          times=[t for g in groups for t in g[0]],
                          rect_out={k: rnd(groups[0][1][k], 1) for k in ("x", "y", "w", "h")},
                          max_ncc=max((r["max_ncc"] for r in ok if r.get("max_ncc") is not None), default=None),
                          max_tile_ncc=max((r["max_tile_ncc"] for r in ok if r.get("max_tile_ncc") is not None),
                                           default=None),
                          ocr_hits=sum(int(r.get("ocr_hits") or 0) for r in ok),
                          ocr_partial_hits=sum(int(r.get("ocr_partial_hits") or 0) for r in ok),
                          thresholds=(ok[0].get("thresholds") if ok else None))
                if not ok:
                    it.update(status="unmeasured", residual=None,
                              reason="residual_score 가 측정하지 못함(템플릿·OCR 모두 없음/실패)")
                else:
                    it.update(status="measured", residual=any(bool(r.get("residual")) for r in ok))
        # the record's own unmeasured checks, restricted to the source ranges this episode uses
        checks = doc.get("checks") or {}
        shots = {sh.get("id"): sh for sh in doc.get("shots") or []}
        sg = checks.get("static_graphics") or {}
        carried = []
        if sg and sg.get("status") != "measured":
            um = [shots.get(i) or {"id": i} for i in sg.get("shots_unmeasured") or []]
            hit = [x for x in um if x.get("start") is None or any(min(b_, float(x.get("end") or 1e9)) - max(a_, float(x.get("start") or 0))
                                                                   > 0 for a_, b_ in used)]
            if hit or not um:
                carried.append({"check": "static_graphics", "status": "unmeasured", "doc_status": sg.get("status"),
                                "reason": sg.get("reason"), "impact": sg.get("impact"),
                                "shots": [{k: x.get(k) for k in ("id", "start", "end")} for x in hit]})
        to = checks.get("text_overlays") or {}
        if to and to.get("status") != "measured":
            carried.append({"check": "text_overlays", "status": "unmeasured", "doc_status": to.get("status"),
                            "reason": to.get("reason"), "impact": to.get("impact")})
        for name, cc in (doc.get("corners") or {}).items():
            um = [k for k in ("text", "graphic") if cc.get(k) == "unmeasured"]
            if not um:
                continue
            reg = cc.get("region") or {}
            vis = [c.id for c in clips if reg and source_rect_to_canvas(reg, c) is not None]
            if reg and not vis:
                continue                              # this corner is cropped away in every clip
            carried.append({"check": f"corner:{name}", "status": "unmeasured", "unmeasured": um, "region": reg,
                            "resolution": cc.get("resolution"), "crop": cc.get("crop"), "visible_in_clips": vis,
                            "reason": sg.get("reason") if "graphic" in um else to.get("reason")})
        ent["carried_unmeasured"] = carried
    return {"status": "measured", "sources": out_sources}


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
    from . import tesseract_env

    try:
        with tesseract_env():
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
FETCH_MODELS_HINT = "`python -m shortkit clean fetch-models` 로 고정된(sha256) Haar 캐스케이드를 받으면 측정됨"
FACE_ANALYSIS_W = 480          # detection width of the visible picture (canvas px -> analysis px)
FACE_MIN_PX = 20               # smallest face at analysis scale


def face_detector():
    """(name, detect(img_rgb) -> [[x, y, w, h], ...] in img px) or (None, reason).

    1. ``cv2.CascadeClassifier`` + ``cv2.data`` XML (OpenCV 4.x wheels);
    2. ``shortkit.clean.faces`` -- the numpy Haar evaluator on the pinned cascades that
       ``shortkit clean fetch-models`` put in warehouse/cache/models/haarcascades (frontal + profile
       + mirrored profile, NMS), the same detector the cleaning step uses (OpenCV 5 has no cascades);
    3. a YuNet ONNX model the user placed at $SHORTKIT_FACE_MODEL or assets/models/.
    QA never downloads a model."""
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

                return "haar_frontalface_default(cv2)", det
    missing_note = ""
    try:
        from ..clean import faces as cf

        dets, missing = cf.load_detectors()
        if dets and "frontal" not in missing:
            def det(img, dets=dets):
                return [[float(d["x"]), float(d["y"]), float(d["w"]), float(d["h"])]
                        for d in cf.detect_faces_in_frame(img, dets, min_face_px=FACE_MIN_PX, min_neighbors=4)]

            kinds = "+".join(d.kind for d in dets)
            return f"shortkit.clean.faces haar {kinds} ({dets[0].backend})", det
        missing_note = f"Haar 캐스케이드 없음({', '.join(missing) or '?'}; {cf.MODELS_DIR})"
    except Exception as e:  # clean module unavailable: fall through to YuNet / unmeasured
        missing_note = f"shortkit.clean.faces 사용 불가({type(e).__name__}: {e})"[:200]
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
    return None, (f"얼굴 검출기 없음: 이 OpenCV 빌드(cv2 {cv2.__version__})에는 Haar cascade(CascadeClassifier/cv2.data)가 없고, "
                  f"{missing_note}. {FETCH_MODELS_HINT}")


def _detect_in_rect(det, img: np.ndarray, rect, analysis_w: int = FACE_ANALYSIS_W) -> list[list[float]]:
    """Faces inside ``rect`` ([x, y, w, h] px of ``img``), returned in ``img`` px."""
    cv2 = _cv2()
    H, W = img.shape[:2]
    x0, y0 = max(0, int(math.floor(rect[0]))), max(0, int(math.floor(rect[1])))
    x1, y1 = min(W, int(math.ceil(rect[0] + rect[2]))), min(H, int(math.ceil(rect[1] + rect[3])))
    if x1 - x0 < 24 or y1 - y0 < 24:
        return []
    sub = img[y0:y1, x0:x1]
    k = min(1.0, analysis_w / float(x1 - x0))
    if k < 1.0:
        sub = cv2.resize(sub, (max(1, int(round((x1 - x0) * k))), max(1, int(round((y1 - y0) * k)))),
                         interpolation=cv2.INTER_AREA)
    return [[x0 + f[0] / k, y0 + f[1] / k, f[2] / k, f[3] / k] for f in det(np.ascontiguousarray(sub))]


def face_sample_plan(ctx: QAContext, overlays: list[dict], sample_fps: float = 1.0) -> tuple[list[float], list[dict]]:
    """(times, unsampled): output times to look for faces -- at most ``sample_fps`` (capped at 1)
    per second, samples at least 1/fps apart, and only while a caption is visible over the picture
    (a caption outside every clip's video region cannot cover a face in the footage).  A caption
    window that cannot get a sample of its own without breaking the rate (a < 1 s caption right after
    another sample) is returned in ``unsampled`` so the report can say it was not checked."""
    from . import rect_intersection

    fps = min(1.0, max(1e-3, float(sample_fps)))
    step = 1.0 / fps
    T = float(ctx.info.duration)
    wins = []
    for o in overlays:
        if not o.get("bbox") or o.get("end") is None or o.get("start") is None:
            continue
        a, e = max(0.0, float(o["start"])), min(T, float(o["end"]))
        if e <= a:
            continue
        if not any(rect_intersection(o["bbox"], c.region) > 0 and c.out_start < e and c.out_end > a
                   for c in ctx.resolved.clips):
            continue
        wins.append((a, e, o.get("id")))
    times: list[float] = []
    unsampled: list[dict] = []
    last = -1e9
    for a, e, oid in sorted(wins):
        t = max(a + min(step / 2.0, (e - a) / 2.0), last + step)
        while t <= e + 1e-9:
            times.append(round(t, 3))
            last = t
            t += step
        if not any(a - 1e-6 <= u <= e + 1e-6 for u in times):
            unsampled.append({"overlay": oid, "start": rnd(a), "end": rnd(e)})
    return times, unsampled


def face_sample_times(ctx: QAContext, overlays: list[dict], sample_fps: float = 1.0) -> list[float]:
    return face_sample_plan(ctx, overlays, sample_fps)[0]


def analyze_faces(ctx: QAContext, overlays: list[dict], sample_fps: float = 1.0) -> dict:
    """Do captions cover faces?  overlays: [{id, kind, start, end, bbox:[x,y,w,h] (MEASURED in the output)}]

    Faces are detected at <= 1 fps, only while captions are over the picture, two ways:
    (a) in the OUTPUT frame (visible picture area of the clip on top), and (b) in the SOURCE frame
    shown at that moment, mapped to canvas px with the clip geometry -- a caption that fully covers
    a face hides it from (a), so (b) is what finds it.  A hit = caption box covering > 10 % of a face.
    """
    from .. import paths
    from . import rect_intersection

    name, det = face_detector()
    res: dict = {"detector": name}
    if name is None:
        res["status"] = "unmeasured"
        res["reason"] = det
        return res
    fps = min(1.0, float(sample_fps))
    times, unsampled = face_sample_plan(ctx, overlays, fps)
    hits, faces_log = [], []
    for t in times:
        active = [o for o in overlays if o.get("bbox") and o["start"] <= t <= o["end"]]
        c = clip_at(ctx.resolved, t)
        if not active or c is None:
            continue
        vis = clip_transform(c, t)["visible"]
        found = []
        ok_paths = 0
        try:
            fr = grab(ctx.mp4, t)
            found += [{"rect": f, "from": "output"} for f in _detect_in_rect(det, fr, vis)]
            ok_paths += 1
        except Exception as e:
            res.setdefault("errors", []).append(f"t={t}: output {type(e).__name__}: {e}"[:200])
        sp = paths.absp(c.source_path)
        if sp.is_file():
            try:
                tr = clip_transform(c, t)
                s, tx, ty = tr["s"], tr["tx"], tr["ty"]
                sf = grab(sp, src_time(c, t))
                # the part of the source that is visible on the canvas
                src_vis = [(vis[0] - tx) / s, (vis[1] - ty) / s, vis[2] / s, vis[3] / s]
                for f in _detect_in_rect(det, sf, src_vis, analysis_w=int(round(FACE_ANALYSIS_W))):
                    mr = map_src_rect(c, {"x": f[0], "y": f[1], "w": f[2], "h": f[3]}, t)
                    # a face also found in the output frame is kept once (the output detection)
                    if mr is not None and not any(g["from"] == "output" and rect_iou(g["rect"], mr) > 0.4 for g in found):
                        found.append({"rect": mr, "from": "source", "rect_src": [rnd(v, 1) for v in f]})
                ok_paths += 1
            except Exception as e:
                res.setdefault("errors", []).append(f"t={t}: source {type(e).__name__}: {e}"[:200])
        if ok_paths < 2:
            # without the source frame a fully covered face is invisible: this moment is not checked
            unsampled.append({"overlay": ",".join(o["id"] for o in active), "start": rnd(t), "end": rnd(t),
                              "reason": "출력/소스 프레임을 읽지 못함"})
        faces_log.append({"t": t, "clip_id": c.id, "faces": [{"rect": [rnd(v, 1) for v in f["rect"]], "from": f["from"]}
                                                           for f in found]})
        for f in found:
            fx = f["rect"]
            area = fx[2] * fx[3]
            if area <= 0:
                continue
            for o in active:
                inter = rect_intersection(fx, o["bbox"])
                if inter > 0.1 * area:
                    hits.append({"t": rnd(t, 2), "face": [rnd(v, 1) for v in fx], "face_from": f["from"],
                                 "overlay": o["id"], "covered_frac": rnd(inter / area, 3)})
    res.update(status="measured", frames=len(times), sample_times=times, sample_fps_max=fps, covered=hits,
               unsampled_captions=unsampled,
               faces=faces_log, resolution=[ctx.info.width, ctx.info.height],
               min_face_px_canvas=rnd(FACE_MIN_PX * max((c.region.w for c in ctx.resolved.clips), default=ctx.canvas_w)
                                      / FACE_ANALYSIS_W, 1),
               method="얼굴: 출력 프레임 + 같은 순간의 소스 프레임(자막이 덮은 얼굴은 출력에서 안 보임)을 캔버스 좌표로 옮겨 검출; "
                      "자막 상자: 출력에서 측정")
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
            tr = clip_transform(c, mid)
            full_area = float(pr["w"]) * float(pr["h"]) * tr["s"] * tr["s"]
            vis = (mr[2] * mr[3] / full_area) if (mr is not None and full_area > 0) else 0.0
            out.append({"label": pr.get("label"), "clip_id": c.id, "start": rnd(t0), "end": rnd(t1),
                        "rect": [rnd(v, 1) for v in mr] if mr is not None else None, "visible_frac": rnd(min(1.0, vis), 3),
                        "resolution": [ctx.canvas_w, ctx.canvas_h]})
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
    for name, fn in (("mapping", analyze_mapping), ("residual", analyze_residual), ("provenance", analyze_provenance)):
        try:
            res[name] = fn(ctx)
        except Exception as e:
            res["errors"][name] = f"{type(e).__name__}: {e}"
    try:
        res["protected"] = protected_rects_canvas(ctx)
    except Exception as e:
        res["errors"]["protected"] = f"{type(e).__name__}: {e}"
    return res
