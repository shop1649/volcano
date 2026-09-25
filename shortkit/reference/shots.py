"""Shot boundaries of a reference video: hard cuts, white/colored flashes and crossfades.

Measured inside the footage region (``layout``/region detection) so that caption changes are not
mistaken for cuts.  All frames are decoded (CFR assumption, index-derived times) at a small
width.  Output ``analysis/<id>/shots.json`` (docs/CONTRACT.md section 11)::

    {"video_id", "resolution": [w, h], "fps", "duration",
     "cuts": [{"t", "type": "cut|flash|crossfade", "score", ...}], "shots": [{"start", "end"}],
     "presence": {"cut"|"flash"|"crossfade": present|absent|unmeasured}}

``t`` is the first frame of the new shot for a cut, the first brightened frame for a flash and
the first blended frame for a crossfade (``dur`` = blend length).  Flashes also carry ``scope``
``{value: canvas|region|None, outside_share, ...}``: whether the flash brightened the whole canvas
or only the video region (``motion.transitions.flash.scope``).
"""
from __future__ import annotations

from pathlib import Path

import numpy as np

from ..util.jsonio import now_iso, write_json
from ..util.media import probe
from ..util.stats import tri_state
from .common import analysis_dir, hexrgb, iter_native, region_or_full

SCHEMA = "shortkit.ref_shots/1"
METHOD = {
    "cut": "HSV histogram Bhattacharyya distance between consecutive frames >= 0.35 and >= 3x the local median",
    "flash": "mean luma of the footage region >= 40 above the local median and >= 150, lasting <= 0.5 s",
    "crossfade": "4-24 frame window whose frames are least-squares blends of the frames just outside it "
                 "(blend weight monotonic 0->1, residual < 35% of the endpoint difference) AND the blend is spatially "
                 "uniform: in the interior frames with 0.25 <= weight <= 0.75, >= 60% of the pixels that change by "
                 ">= 20 levels have their own weight within +-0.2 of the frame's weight (median over those frames); "
                 "a zoom or a person moving in a static shot changes pixels all-or-nothing and fails this",
    "frame_times": "frame index / fps (constant frame rate assumed)",
}


def _hist(frame_rgb: np.ndarray) -> np.ndarray:
    import cv2
    hsv = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2HSV)
    h = cv2.calcHist([hsv], [0, 1, 2], None, [16, 8, 8], [0, 180, 0, 256, 0, 256])
    return cv2.normalize(h, h).flatten()


def analyze(video: str | Path, video_id: str, preset: str | None = None, region: dict | None = None,
            out_dir: Path | None = None, width: int = 160, max_seconds: float | None = None) -> dict:
    import cv2

    video = Path(video)
    info = probe(video)
    W, H = int(info.width), int(info.height)
    fps = float(info.fps or 30.0)
    reg = region_or_full(region, W, H)
    hists, grays, luma, cols = [], [], [], []
    for t, fr in iter_native(video, fps, crop=reg, width=width, max_seconds=max_seconds):
        hists.append(_hist(fr))
        g = cv2.cvtColor(fr, cv2.COLOR_RGB2GRAY)
        grays.append(cv2.GaussianBlur(g, (3, 3), 0).astype(np.float32))
        luma.append(float(g.mean()))
        cols.append(fr.reshape(-1, 3).mean(axis=0))
    n = len(hists)
    duration = n / fps if n else float(info.duration)
    res = {"schema": SCHEMA, "video_id": video_id, "resolution": [W, H], "fps": fps, "duration": round(duration, 3),
           "region_used": reg, "method": METHOD, "analyzed_at": now_iso(), "cuts": [], "shots": []}
    if n < 3:
        res["presence"] = {k: "unmeasured" for k in ("cut", "flash", "crossfade")}
        res["note"] = "프레임 부족"
        _write(res, preset, video_id, out_dir)
        return res
    dh = np.zeros(n)
    for i in range(1, n):
        dh[i] = cv2.compareHist(hists[i - 1], hists[i], cv2.HISTCMP_BHATTACHARYYA)
    luma_a = np.array(luma)
    events: list[dict] = []
    # ---- flashes
    flash_frames = np.zeros(n, bool)
    k = int(round(0.5 * fps))
    for i in range(n):
        lo, hi = max(0, i - k), min(n, i + k + 1)
        base = np.median(np.concatenate([luma_a[lo:max(lo, i - 3)], luma_a[min(hi, i + 4):hi]])) \
            if (i - 3 > lo or i + 4 < hi) else np.median(luma_a[lo:hi])
        if luma_a[i] - base >= 40 and luma_a[i] >= 150:
            flash_frames[i] = True
    i = 0
    while i < n:
        if flash_frames[i]:
            j = i
            while j + 1 < n and flash_frames[j + 1]:
                j += 1
            if (j - i + 1) / fps <= 0.5:
                # include the ramp frames around the run (luma still clearly above the neighbours)
                s, e = i, j
                pre = luma_a[max(0, i - k):i]
                post = luma_a[j + 1:min(n, j + 1 + k)]
                b0 = float(np.median(pre)) if len(pre) else luma_a[i]
                b1 = float(np.median(post)) if len(post) else luma_a[j]
                while s - 1 >= 0 and luma_a[s - 1] - b0 >= 15 and s - 1 > i - k:
                    s -= 1
                while e + 1 < n and luma_a[e + 1] - b1 >= 15 and e + 1 < j + k:
                    e += 1
                peak = int(i + np.argmax(luma_a[i:j + 1]))
                joins = None
                if s - 1 >= 0 and e + 1 < n:
                    joins = bool(cv2.compareHist(hists[s - 1], hists[e + 1], cv2.HISTCMP_BHATTACHARYYA) >= 0.3)
                events.append({"t": round(s / fps, 3), "type": "flash", "score": round(float(luma_a[peak] - b0) / 255, 3),
                               "dur": round((e - s + 1) / fps, 3), "peak_t": round(peak / fps, 3),
                               "color": hexrgb(cols[peak]), "joins_shots": joins, "_span": (s, e)})
            i = j + 1
        else:
            i += 1
    blocked = np.zeros(n, bool)
    for ev in events:
        s, e = ev["_span"]
        blocked[max(0, s - 2):min(n, e + 3)] = True
    # ---- hard cuts
    for i in range(1, n):
        if blocked[i]:
            continue
        loc = np.concatenate([dh[max(1, i - 7):i], dh[i + 1:min(n, i + 8)]])
        med = float(np.median(loc)) if len(loc) else 0.0
        if dh[i] >= 0.35 and dh[i] >= 3 * max(med, 0.02) and dh[i] == dh[max(1, i - 2):min(n, i + 3)].max():
            events.append({"t": round(i / fps, 3), "type": "cut", "score": round(float(dh[i]), 3), "_span": (i, i)})
            blocked[max(0, i - 2):min(n, i + 3)] = True
    # ---- crossfades
    events += _crossfades(grays, hists, dh, fps, blocked)
    events.sort(key=lambda e: e["t"])
    bounds = []
    for ev in events:
        s, e = ev.pop("_span")
        bounds.append((s, e, ev["type"]))
    shots, cur = [], 0
    for s, e, typ in bounds:
        if s > cur:
            shots.append({"start": round(cur / fps, 3), "end": round(s / fps, 3)})
        cur = s if typ == "cut" else e + 1     # a cut frame is the first frame of the new shot
    if cur < n:
        shots.append({"start": round(cur / fps, 3), "end": round(n / fps, 3)})
    full_frame = not (region or {}).get("video_region")
    for ev in events:
        if ev["type"] == "flash":
            ev["scope"] = flash_scope(video, ev, reg, W, H, fps, full_frame=full_frame)
    res["cuts"] = events
    res["shots"] = shots
    res["n_shots"] = len(shots)
    res["presence"] = {k: tri_state([any(e["type"] == k for e in events)]) for k in ("cut", "flash", "crossfade")}
    res["presence_note"] = "없다 = 이 영상 전체를 검사해서 찾지 못함(검출기 기준)"
    _write(res, preset, video_id, out_dir)
    return res


FLASH_SCOPE_CANVAS = 0.6      # share of brightened pixels outside the video region -> whole canvas
FLASH_SCOPE_REGION = 0.15     # at most this share -> the flash covers only the video region
FLASH_SCOPE_METHOD = ("peak flash frame vs per-pixel median of the frames 0.1-0.25 s before / after the flash, full "
                      "canvas at 180 px width: share of pixels OUTSIDE the video region (2 % border trimmed, pixels "
                      "without brightening headroom excluded) that brighten by >= max(15, 0.4 x the region's mean "
                      f"rise); >= {FLASH_SCOPE_CANVAS} -> canvas, <= {FLASH_SCOPE_REGION} -> region, else unmeasured; "
                      "full-frame footage -> unmeasured (no outside area)")
METHOD["flash_scope"] = FLASH_SCOPE_METHOD


def flash_scope(video: Path, ev: dict, reg: dict, W: int, H: int, fps: float, full_frame: bool = False,
                width: int = 180) -> dict:
    """Did a flash brighten the whole canvas or only the video region?  (``motion.transitions.flash.scope``)"""
    import cv2

    from .common import read_segment

    out: dict = {"value": None}
    if full_frame or (reg["w"] >= 0.97 * W and reg["h"] >= 0.97 * H):
        out["note"] = "영상이 화면 전체를 덮음 → 영역 밖이 없어 범위 판정 불가"
        return out
    t0, dur = float(ev["t"]), float(ev.get("dur") or 1.0 / fps)
    peak_t = float(ev.get("peak_t", t0))
    pre = read_segment(video, max(0.0, t0 - 0.25), max(0.0, t0 - 0.1 + 1e-6), fps, width=width, gray=True)
    post = read_segment(video, t0 + dur + 0.1, t0 + dur + 0.25 + 1e-6, fps, width=width, gray=True)
    peak = read_segment(video, peak_t, peak_t + 0.5 / fps, fps, width=width, gray=True)
    base_frames = [f for _, f in pre + post]
    if not peak or len(base_frames) < 2:
        out["note"] = "플래시 앞뒤 프레임 부족"
        return out
    P = peak[0][1].astype(np.float32)
    B = np.median(np.stack(base_frames).astype(np.float32), axis=0)
    h, w = P.shape
    kx, ky = w / W, h / H
    inside = np.zeros((h, w), bool)
    x0, y0 = int(round(reg["x"] * kx)), int(round(reg["y"] * ky))
    x1, y1 = int(round((reg["x"] + reg["w"]) * kx)), int(round((reg["y"] + reg["h"]) * ky))
    inside[y0:y1, x0:x1] = True
    m = max(1, int(round(0.02 * min(h, w))))
    grown = cv2.dilate(inside.astype(np.uint8), np.ones((2 * m + 1, 2 * m + 1), np.uint8)).astype(bool)
    shrunk = cv2.erode(inside.astype(np.uint8), np.ones((2 * m + 1, 2 * m + 1), np.uint8)).astype(bool)
    outside = ~grown
    outside[:m, :] = outside[-m:, :] = False
    outside[:, :m] = outside[:, -m:] = False
    D = P - B
    rise_in = float(np.mean(D[shrunk])) if shrunk.any() else 0.0
    out["region_rise"] = round(rise_in, 1)
    if rise_in < 20:
        out["note"] = "영상 영역 안의 밝기 상승이 작음 → 판정 불가"
        return out
    thr = max(15.0, 0.4 * rise_in)
    usable = outside & (B <= 255.0 - thr)
    if usable.sum() < 0.03 * h * w:
        out["note"] = "영역 밖에 밝아질 여유가 있는 픽셀이 너무 적음(이미 밝은 배경 등)"
        return out
    share = float((D[usable] >= thr).mean())
    out.update({"outside_share": round(share, 3), "outside_pixels": int(usable.sum()),
                "outside_rise_p50": round(float(np.median(D[usable])), 1)})
    if share >= FLASH_SCOPE_CANVAS:
        out["value"] = "canvas"
    elif share <= FLASH_SCOPE_REGION:
        out["value"] = "region"
    else:
        out["note"] = "영역 밖 일부만 밝아짐 → 판정 불가"
    return out


XF_UNIFORM_MIN = 0.6     # share of changed pixels following the frame's blend weight (renderer crossfades: ~0.97;
XF_PIXEL_DIFF = 20.0     # zoom ramps / walking people in static shots mis-taken for blends: 0.12-0.39, mockloop)
XF_ALPHA_TOL = 0.2


def _blend_uniformity(grays, a: int, b: int, alphas: np.ndarray, diff: np.ndarray) -> float | None:
    """Median over interior frames (0.25 <= weight <= 0.75) of the share of changing pixels whose own blend
    weight (g_k - g_a) / (g_b - g_a) lies within XF_ALPHA_TOL of the frame's least-squares weight.
    A crossfade mixes every pixel by the same weight; geometric change (zoom, pan) or an object moving
    over a still background switches pixels between the two end states instead.  None = not testable."""
    sel = np.abs(diff) >= XF_PIXEL_DIFF
    if sel.sum() < 20:
        return None
    ga = grays[a]
    shares = []
    for k, al in zip(range(a + 1, b), alphas):
        if not 0.25 <= al <= 0.75:
            continue
        ai = (grays[k] - ga)[sel] / diff[sel]
        shares.append(float(np.mean(np.abs(ai - al) <= XF_ALPHA_TOL)))
    return float(np.median(shares)) if shares else None


def _crossfades(grays, hists, dh, fps, blocked) -> list[dict]:
    import cv2
    n = len(grays)
    found: list[dict] = []
    taken = blocked.copy()
    cands = []
    for L in range(4, 25):
        for a in range(0, n - L - 1):
            b = a + L + 1
            if taken[a + 1:b].any():
                continue
            span = cv2.compareHist(hists[a], hists[b], cv2.HISTCMP_BHATTACHARYYA)
            if span < 0.25:
                continue
            if dh[a + 1:b + 1].max() >= 0.5 * span:
                continue
            ga, gb = grays[a], grays[b]
            diff = gb - ga
            den = float((diff * diff).sum())
            if den < 1e-3:
                continue
            alphas, resid = [], []
            for k in range(a + 1, b):
                r = grays[k] - ga
                al = float((r * diff).sum() / den)
                alphas.append(al)
                resid.append(float(np.abs(r - al * diff).mean()))
            alphas = np.array(alphas)
            base = float(np.abs(diff).mean())
            rr = float(np.mean(resid)) / max(base, 1e-6)
            mono = np.all(np.diff(alphas) > -0.08)
            if not mono or alphas[0] > 0.35 or alphas[-1] < 0.65 or rr > 0.35:
                continue
            if np.corrcoef(np.arange(len(alphas)), alphas)[0, 1] < 0.95:
                continue
            uni = _blend_uniformity(grays, a, b, alphas, diff)
            if uni is not None and uni < XF_UNIFORM_MIN:
                continue
            cands.append((span * (1 - rr), a, b, alphas, rr, span))
    cands.sort(key=lambda c: -c[0])
    for score, a, b, alphas, rr, span in cands:
        if taken[a:b + 1].any():
            continue
        idx = np.arange(a + 1, b)
        inside = idx[(alphas > 0.03) & (alphas < 0.97)]
        s = int(inside[0]) if len(inside) else a + 1
        e = int(inside[-1]) if len(inside) else b - 1
        ev = {"t": round(s / fps, 3), "type": "crossfade", "score": round(float(span), 3),
              "dur": round((e - s + 2) / fps, 3), "blend_residual": round(rr, 3), "_span": (s, e)}
        uni = [float(np.std(grays[a])), float(np.std(grays[b]))]
        if min(uni) < 6:
            ev["note"] = "한쪽 끝이 단색 화면 → 색으로 페이드(fade to/from color)"
        found.append(ev)
        taken[a:b + 1] = True
    return found


def _write(res: dict, preset: str | None, video_id: str, out_dir: Path | None) -> None:
    d = out_dir if out_dir is not None else analysis_dir(preset, video_id)
    write_json(Path(d) / "shots.json", res)
