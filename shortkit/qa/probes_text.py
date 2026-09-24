"""Text probes on the final MP4: caption ink bbox / OCR text / onset-offset / motion_in /
font / tone, identity text (forbidden channel marks) and leftover source text in corners.

Measurement method (per caption)
  1. Grab the frame at rest (after the entrance animation).  Build an ink mask from the
     caption's fill colours, keeping only pixels next to the outline colour when the caption
     has an outline (this rejects white video content).
  2. Group the mask into text-line candidates (horizontal closing + connected components) and
     OCR every candidate (tesseract kor+eng, psm 7) on the binarised mask; the candidates whose
     OCR text matches an expected line best are the caption.  So a caption drawn in the wrong
     place is still found (and reported where it really is).
  3. Onset/offset: decode the caption region at native fps around the planned start/end and
     compare each frame with the rest frame over the ink pixels (presence 0..1).
  4. motion_in: the first frames after onset -> ink bbox width vs rest (pop = scale change),
     presence ramp (fade), or neither (none).
"""
from __future__ import annotations

import math
import os
import re
from collections import Counter

import numpy as np

from . import QAContext, hex_rgb, rect_intersection, rgb_hex, rnd
from .probes_video import color_mask, grab, grab_window, text_similarity

OCR_LANG = "kor+eng"
OCR_TIMEOUT_S = 20
# tesseract's OpenMP threads thrash badly on a loaded machine (one call took minutes with the
# default thread count); one thread per call is 100x faster here.  Only affects the tesseract
# subprocess environment.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")
_OCR_STATS = {"calls": 0, "timeouts": 0}


def _cv2():
    import cv2

    return cv2


# ----------------------------------------------------------------------------- OCR helpers
def tesseract_ok() -> tuple[bool, str]:
    try:
        import pytesseract

        langs = set(pytesseract.get_languages(config=""))
        miss = [l for l in ("kor", "eng") if l not in langs]
        if miss:
            return False, f"tesseract 언어 데이터 없음: {miss}"
        return True, str(pytesseract.get_tesseract_version())
    except Exception as e:
        return False, f"tesseract 사용 불가: {type(e).__name__}: {e}"


def ocr_words(img: np.ndarray, psm: int = 6, lang: str = OCR_LANG, upscale: int = 1, min_conf: float = 0.0) -> list[dict]:
    import pytesseract
    from PIL import Image

    cv2 = _cv2()
    im = img
    if upscale and upscale > 1:
        im = cv2.resize(im, (im.shape[1] * upscale, im.shape[0] * upscale), interpolation=cv2.INTER_CUBIC)
    _OCR_STATS["calls"] += 1
    try:
        d = pytesseract.image_to_data(Image.fromarray(im), lang=lang, config=f"--psm {psm}",
                                      output_type=pytesseract.Output.DICT, timeout=OCR_TIMEOUT_S)
    except RuntimeError:           # pytesseract raises RuntimeError on timeout
        _OCR_STATS["timeouts"] += 1
        return []
    out = []
    for i, txt in enumerate(d["text"]):
        txt = (txt or "").strip()
        if not txt:
            continue
        conf = float(d["conf"][i])
        if conf < min_conf:
            continue
        u = float(upscale or 1)
        out.append({"text": txt, "conf": conf, "box": [d["left"][i] / u, d["top"][i] / u, d["width"][i] / u,
                                                       d["height"][i] / u],
                    "line": (d["block_num"][i], d["par_num"][i], d["line_num"][i])})
    return out


def ocr_text(img: np.ndarray, psm: int = 6, upscale: int = 1, lang: str = OCR_LANG) -> str:
    ws = ocr_words(img, psm=psm, upscale=upscale, lang=lang)
    return " ".join(w["text"] for w in ws if w["conf"] >= 30)


def norm_text(s: str | None) -> str:
    return re.sub(r"[\W_]+", "", (s or "").lower())


# ----------------------------------------------------------------------------- masks
def ink_mask(img: np.ndarray, cap, tol: float = 80.0) -> np.ndarray:
    """Pixels of the caption fill colour(s); with an outline, only those next to it."""
    cv2 = _cv2()
    fills = [hex_rgb(cap.color, (255, 255, 255))]
    if cap.highlight:
        hc = hex_rgb(cap.highlight_color)
        if hc:
            fills.append(hc)
    m = np.zeros(img.shape[:2], bool)
    for f in fills:
        m |= color_mask(img, f, tol)
    op = float(cap.outline_px or 0)
    if op >= 2:
        om = color_mask(img, hex_rgb(cap.outline_color, (0, 0, 0)), 95.0)
        k = int(op * 1.5) + 3
        near = cv2.dilate(om.astype(np.uint8), np.ones((k, k), np.uint8)).astype(bool)
        m &= near
    return m


def _line_candidates(m: np.ndarray, line_h: float) -> list[list[int]]:
    cv2 = _cv2()
    kw = max(5, int(line_h * 0.9))
    kh = max(1, int(line_h * 0.12))
    closed = cv2.morphologyEx(m.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((kh, kw), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(closed, connectivity=8)
    out = []
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if h < 0.35 * line_h or h > 2.6 * line_h or w < 0.4 * line_h:
            continue
        # tight bbox from the raw mask inside the component
        sub = m[y:y + h, x:x + w] & (lab[y:y + h, x:x + w] == i)
        ys, xs = np.nonzero(sub)
        if len(xs) < 20:
            continue
        out.append([int(x + xs.min()), int(y + ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)])
    return out


def _ocr_mask_crop(m: np.ndarray, box: list[int], pad: int = 12) -> str:
    x, y, w, h = box
    H, W = m.shape
    x0, y0, x1, y1 = max(0, x - pad), max(0, y - pad), min(W, x + w + pad), min(H, y + h + pad)
    crop = np.where(m[y0:y1, x0:x1], 0, 255).astype(np.uint8)
    up = 2 if h < 28 else 1
    return ocr_text(crop, psm=7, upscale=up, lang=OCR_LANG)


def expected_lines(cap) -> list[str]:
    lines = [l for l in (cap.lines or []) if l and l.strip()]
    if not lines:
        lines = [l for l in (cap.text or "").split("\n") if l.strip()]
    return lines


def locate_caption(frame: np.ndarray, cap, max_ocr: int = 10) -> dict:
    """Find the caption in a full canvas frame.  Returns measured bbox (fill ink), lines, OCR text."""
    lines = expected_lines(cap)
    n_lines = max(1, len(lines))
    ex, ey, ew, eh = cap.bbox.x, cap.bbox.y, cap.bbox.w, cap.bbox.h
    line_h = max(8.0, (eh / n_lines) * 0.8 if eh > 0 else cap.size_px * 0.62)
    m = ink_mask(frame, cap)
    cands = _line_candidates(m, line_h)
    ecx, ecy = ex + ew / 2, ey + eh / 2
    cands.sort(key=lambda b: math.hypot(b[0] + b[2] / 2 - ecx, b[1] + b[3] / 2 - ecy))
    scored = []
    for b in cands[:max_ocr]:
        txt = _ocr_mask_crop(m, b)
        sims = [text_similarity(txt, l) for l in lines] or [0.0]
        scored.append({"box": b, "ocr": txt, "sims": sims})
    # assign each expected line its best candidate (greedy, distinct)
    used, chosen = set(), []
    for li in range(len(lines)):
        best = None
        for k, s in enumerate(scored):
            if k in used:
                continue
            v = s["sims"][li] if li < len(s["sims"]) else 0.0
            if best is None or v > best[0]:
                best = (v, k)
        if best is not None and best[0] >= 0.34:
            used.add(best[1])
            chosen.append((li, scored[best[1]], best[0]))
    res = {"n_candidates": len(cands), "mask_px": int(m.sum())}
    if not chosen:
        res.update(found=False, candidates=[{"box": s["box"], "ocr": s["ocr"]} for s in scored[:5]])
        return res
    boxes = [c[1]["box"] for c in chosen]
    x0 = min(b[0] for b in boxes)
    y0 = min(b[1] for b in boxes)
    x1 = max(b[0] + b[2] for b in boxes)
    y1 = max(b[1] + b[3] for b in boxes)
    chosen.sort(key=lambda c: c[1]["box"][1])
    ocr_join = "\n".join(c[1]["ocr"] for c in chosen)
    res.update(found=True, bbox=[x0, y0, x1 - x0, y1 - y0],
               line_boxes=[c[1]["box"] for c in chosen], ocr=ocr_join,
               similarity=round(text_similarity(ocr_join, "".join(lines)), 3),
               lines_found=len(chosen), lines_expected=len(lines))
    # style measurements at rest
    res.update(_style_at_rest(frame, m, res["bbox"], cap))
    return res


def _style_at_rest(frame: np.ndarray, m: np.ndarray, bbox, cap) -> dict:
    cv2 = _cv2()
    x, y, w, h = bbox
    H, W = m.shape
    sub = m[y:y + h, x:x + w]
    px = frame[y:y + h, x:x + w][sub]
    out: dict = {}
    if len(px):
        main = hex_rgb(cap.color, (255, 255, 255))
        d = np.sqrt(((px.astype(np.float32) - np.array(main, np.float32)) ** 2).sum(axis=1))
        core = px[d <= np.percentile(d, 60)] if len(px) > 20 else px
        out["fill_color"] = rgb_hex(np.median(core, axis=0))
        hc = hex_rgb(cap.highlight_color) if cap.highlight else None
        if hc:
            out["highlight_px"] = int(color_mask(frame[y:y + h, x:x + w], hc, 60.0).sum())
    # ---- outline: rings grown outward from the fill ink; the first ring is anti-aliasing
    op = float(cap.outline_px or 0)
    pad = int(max(6, op * 3 + 6))
    y0, y1, x0, x1 = max(0, y - pad), min(H, y + h + pad), max(0, x - pad), min(W, x + w + pad)
    fm = m[y0:y1, x0:x1].astype(np.uint8)
    region = frame[y0:y1, x0:x1]
    oc = hex_rgb(cap.outline_color, (0, 0, 0))
    near = color_mask(region, oc, 90.0)
    prev = fm.astype(bool)
    fracs = []
    for k in range(1, int(max(4, op * 2.5)) + 2):
        grown = cv2.dilate(fm, np.ones((2 * k + 1, 2 * k + 1), np.uint8)).astype(bool)
        ring = grown & ~prev
        prev = grown
        if ring.sum() == 0:
            break
        fracs.append(float(near[ring].mean()))
    th = 0
    started = False
    for k, f in enumerate(fracs, start=1):
        if f >= 0.5:
            started = True
            th = k
        elif started or k > 2:
            break
    out["outline_px_obs"] = th
    out["outline_ring_fracs"] = [round(f, 2) for f in fracs[:10]]
    ring3 = cv2.dilate(fm, np.ones((7, 7), np.uint8)).astype(bool) & ~cv2.dilate(fm, np.ones((3, 3), np.uint8)).astype(bool)
    if ring3.sum() > 10:
        out["outline_color"] = rgb_hex(np.median(region[ring3], axis=0))
    # is the outline distinguishable from the background at all?
    k_in = int(2 * max(op, 2) + 5)
    k_out = int(4 * max(op, 2) + 9)
    outer = cv2.dilate(fm, np.ones((k_out, k_out), np.uint8)).astype(bool) & ~cv2.dilate(fm, np.ones((k_in, k_in), np.uint8)).astype(bool)
    if outer.sum() > 10:
        out["outline_bg_same_color_frac"] = round(float(color_mask(region, oc, 60.0)[outer].mean()), 3)
    # ---- box behind the text: darkening ratio inside the box vs a ring just outside it
    box = cap.box or {}
    rect = box.get("rect")
    if rect:
        bx0, by0, bw_, bh_ = (float(v) for v in rect)
    else:
        bp_x, bp_y = float(box.get("pad_x") or 12), float(box.get("pad_y") or 6)
        bx0, by0, bw_, bh_ = x - bp_x, y - bp_y, w + 2 * bp_x, h + 2 * bp_y
    bx0i, by0i = int(max(0, bx0 + 2)), int(max(0, by0 + 2))
    bx1i, by1i = int(min(W, bx0 + bw_ - 2)), int(min(H, by0 + bh_ - 2))
    g = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY).astype(np.float32)
    if bx1i - bx0i > 4 and by1i - by0i > 4:
        kk = int(2 * op + 7)
        text_near = cv2.dilate(m.astype(np.uint8), np.ones((kk, kk), np.uint8)).astype(bool)
        inside = np.zeros_like(m)
        inside[by0i:by1i, bx0i:bx1i] = True
        inside &= ~text_near
        ring = np.zeros_like(m)
        R = 8
        ring[max(0, by0i - R - 4):min(H, by1i + R + 4), max(0, bx0i - R - 4):min(W, bx1i + R + 4)] = True
        ring[max(0, by0i - 4):min(H, by1i + 4), max(0, bx0i - 4):min(W, bx1i + 4)] = False
        ring &= ~text_near
        if inside.sum() > 20 and ring.sum() > 20:
            li, lo = float(g[inside].mean()), float(g[ring].mean())
            out["box_inside_luma"] = round(li, 1)
            out["box_outside_luma"] = round(lo, 1)
            out["box_region_color"] = rgb_hex(np.median(frame[inside], axis=0))
            out["box_region_std"] = round(float(g[inside].std()), 2)
            if lo >= 35:
                out["box_alpha_obs"] = round(max(0.0, min(1.0, 1.0 - li / lo)), 3)
            else:
                out["box_alpha_obs"] = None          # background too dark to see a dark box
    out["ink_h"] = int(h)
    out["ink_w"] = int(w)
    return out


# ----------------------------------------------------------------------------- timing / motion
def _ink_diff(frames: list[np.ndarray], rest: np.ndarray, mask: np.ndarray) -> np.ndarray:
    if mask.sum() < 10:
        return np.full(len(frames), np.nan)
    r = rest.astype(np.float32)[mask]
    return np.array([float(np.abs(f.astype(np.float32)[mask] - r).mean()) for f in frames])


def _ramp_start(ts, p, i) -> float:
    """Onset: frame i is the first clearly visible frame; if it is only partly visible (fade),
    extrapolate the presence ramp back to 0."""
    if p[i] >= 0.9 or i + 1 >= len(p):
        return ts[i]
    slope = (p[i + 1] - p[i]) / max(1e-6, ts[i + 1] - ts[i])
    if slope <= 0.5:
        return ts[i]
    t0 = ts[i] - p[i] / slope
    return max(ts[i - 1] if i > 0 else ts[i], min(ts[i], t0))


def measure_timing(ctx: QAContext, cap, loc: dict, rest_png: np.ndarray) -> dict:
    """Onset/offset (native fps), entrance motion and fade-out, from region crops decoded with the
    same rgb path; the rest frame is taken from the same decode."""
    cv2 = _cv2()
    from .probes_video import crop_ints

    fps = ctx.fps
    fr = 1.0 / fps
    W, H = ctx.info.width, ctx.info.height
    x, y, w, h = loc["bbox"]
    mi = cap.motion_in or {}
    mo = cap.motion_out or {}
    sc_from = float(mi.get("scale_from") or 1.0)
    grow = max(1.0, sc_from) * 1.15
    cx, cy = x + w / 2, y + h / 2
    margin = float(cap.outline_px or 0) + 12
    rw, rh = w * grow + 2 * margin, h * grow + 2 * margin
    X, Y, RW, RH = crop_ints([cx - rw / 2, cy - rh / 2, rw, rh], W, H)
    m_full = ink_mask(rest_png, cap)
    mask = np.zeros((RH, RW), bool)
    sx0, sy0 = max(x, X), max(y, Y)
    sx1, sy1 = min(x + w, X + RW), min(y + h, Y + RH)
    mask[sy0 - Y:sy1 - Y, sx0 - X:sx1 - X] = m_full[sy0:sy1, sx0:sx1]
    mask = cv2.erode(mask.astype(np.uint8), np.ones((2, 2), np.uint8)).astype(bool)
    out: dict = {"region": [X, Y, RW, RH]}
    dur_in = float(mi.get("dur_s") or 0.0)
    dur_out = float(mo.get("dur_s") or 0.0) if (mo.get("type") or "none") != "none" else 0.0
    # ---------------- onset
    t_rest = min(cap.start + dur_in + 0.12, (cap.start + cap.end) / 2)
    t_a = max(0.0, cap.start - 0.35)
    t_b = max(t_rest + 2 * fr, cap.start + dur_in + 0.45)
    ts, frs = grab_window(ctx.mp4, t_a, t_b - t_a, crop=[X, Y, RW, RH])
    if frs:
        ir = int(np.argmin([abs(t - t_rest) for t in ts]))
        rest = frs[ir]
        D = _ink_diff(frs, rest, mask)
        norm = float(np.nanmax(D)) if np.any(np.isfinite(D)) else float("nan")
        out["onset_contrast"] = rnd(norm, 1)
        if not np.isfinite(norm):
            out["onset"] = None
            out["onset_note"] = "자막 잉크 화소가 너무 적음"
        elif norm < 12.0:
            if cap.start < 2 * fr:
                out["onset"] = round(ts[0], 4)
                out["onset_note"] = "첫 프레임부터 표시"
            else:
                out["onset"] = None
                out["onset_note"] = "자막 전후 화면 차이가 작아 등장 시점 측정 불가"
        else:
            p = 1.0 - np.clip(D / norm, 0.0, 1.0)
            idx = None
            for i in range(len(p)):
                if p[i] >= 0.15 and all(p[j] >= 0.15 for j in range(i, min(len(p), i + 3))):
                    idx = i
                    break
            if idx is None:
                out["onset"] = None
                out["onset_note"] = "자막이 기대 구간에 나타나지 않음"
            else:
                out["onset_frame_t"] = round(ts[idx], 4)
                out["onset"] = round(_ramp_start(ts, p, idx), 4)
                out.update(_motion_in(ts, frs, p, idx, rest, mask, cap, fps))
            out["presence_in"] = [[rnd(a, 3), rnd(b, 3)] for a, b in zip(ts, p)]
    # ---------------- offset
    if cap.end >= ctx.info.duration - 1.5 * fr:
        ts2, frs2 = grab_window(ctx.mp4, max(0.0, ctx.info.duration - 1.0), 1.0, crop=[X, Y, RW, RH])
        if frs2:
            ir = 0
            D2 = _ink_diff([frs2[-1]], frs2[ir], mask) if len(frs2) > 1 else np.array([np.nan])
            # compare the last frame with the rest look measured at onset (same decode path)
            if frs:
                D2 = _ink_diff([frs2[-1]], rest, mask)
            vis = bool(np.isfinite(D2[0]) and D2[0] < max(12.0, 0.3 * (out.get("onset_contrast") or 0)))
            out["offset"] = round(ctx.info.duration, 4) if vis else None
            out["offset_note"] = "영상 끝까지 표시" if vis else "마지막 프레임에 없음"
    else:
        t_c = max(0.0, cap.end - max(0.45, dur_out + 0.3))
        ts2, frs2 = grab_window(ctx.mp4, t_c, (cap.end - t_c) + 0.35, crop=[X, Y, RW, RH])
        if frs2:
            t_r2 = max(t_c, cap.end - dur_out - 0.12)
            ir = int(np.argmin([abs(t - t_r2) for t in ts2]))
            D2 = _ink_diff(frs2, frs2[ir], mask)
            norm2 = float(np.nanmax(D2)) if np.any(np.isfinite(D2)) else float("nan")
            if not np.isfinite(norm2) or norm2 < 12.0:
                out["offset"] = None
                out["offset_note"] = "자막 전후 화면 차이가 작아 퇴장 시점 측정 불가"
            else:
                p2 = 1.0 - np.clip(D2 / norm2, 0.0, 1.0)
                vis = [i for i in range(len(p2)) if p2[i] >= 0.15]
                last = vis[-1] if vis else None
                if last is None or last >= len(p2) - 1:
                    out["offset"] = None
                    out["offset_note"] = "퇴장 시점이 측정 창 밖"
                else:
                    # fade-out: extrapolate the falling ramp to zero; hard cut: next frame time
                    k0 = last
                    while k0 > 0 and 0.12 < p2[k0 - 1] < 0.92:
                        k0 -= 1
                    ramp_frames = last - k0 + 1 if p2[last] < 0.92 else 0
                    if ramp_frames >= 2:
                        slope = (p2[last] - p2[k0]) / max(1e-6, ts2[last] - ts2[k0])
                        t_end = ts2[last] - p2[last] / slope if slope < -0.5 else ts2[last] + fr
                        out["offset"] = round(min(ts2[last] + fr, max(ts2[last], t_end)), 4)
                    else:
                        out["offset"] = round(ts2[last] + fr, 4)
                    out["motion_out_obs"] = {"type": "fade" if ramp_frames >= 2 else "none",
                                             "dur_s": round(ramp_frames * fr, 3), "expected": mo.get("type")}
                out["presence_out"] = [[rnd(a, 3), rnd(b, 3)] for a, b in zip(ts2, p2)]
    return out


def _motion_in(ts, frs, p, i0, rest, mask, cap, fps) -> dict:
    cols = np.nonzero(mask.any(axis=0))[0]
    if not len(cols):
        return {}
    w_rest = cols.max() - cols.min() + 1
    c_rest = int(mask.sum())
    scales, counts = [], []
    for f in frs[i0:i0 + int(math.ceil(0.5 * fps)) + 1]:
        m = ink_mask(f, cap)
        cnt = int(m.sum())
        counts.append(cnt)
        if cnt >= 0.25 * c_rest:
            cc = np.nonzero(m.any(axis=0))[0]
            scales.append(float((cc.max() - cc.min() + 1) / w_rest))
        else:
            scales.append(None)
    s0 = next((s for s in scales[:2] if s is not None), None)
    pp = [float(v) for v in p[i0:i0 + len(scales)]]
    typ = "none"
    if s0 is not None and abs(s0 - 1.0) >= 0.06:
        typ = "pop"
    elif pp and pp[0] <= 0.8 and any(v >= 0.9 for v in pp[1:]):
        typ = "fade"
    settle = None
    for k, (s, v) in enumerate(zip(scales, pp)):
        if s is not None and abs(s - 1.0) <= 0.025 and v >= 0.88:
            settle = k
            break
    return {"motion_in_obs": {"type": typ, "scale_first": rnd(s0, 3), "presence_first": rnd(pp[0] if pp else None, 3),
                              "dur_s": rnd(settle / fps, 3) if settle is not None else None,
                              "scales": [rnd(s, 3) for s in scales[:8]], "presence": [rnd(v, 3) for v in pp[:8]]}}


# ----------------------------------------------------------------------------- font
def measure_font(frame: np.ndarray, cap, bbox) -> dict:
    try:
        from ..reference.typography import font_iou  # type: ignore
    except Exception as e:
        return {"status": "unmeasured", "reason": f"shortkit.reference.typography.font_iou 사용 불가 ({type(e).__name__})"}
    from .. import paths

    try:
        from ..fonts import find_font
    except Exception:
        find_font = None
    exp_path = paths.absp(cap.font_file) if cap.font_file else (find_font(cap.font_name) if find_font else None)
    if exp_path is None or not exp_path.exists():
        return {"status": "unmeasured", "reason": f"기대 글꼴 파일을 찾지 못함: {cap.font_name}"}
    x, y, w, h = bbox
    pad = int(float(cap.outline_px or 0) + 6)
    crop = frame[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad]
    text = "\n".join(expected_lines(cap))
    cands = [(cap.font_name, exp_path)]
    if find_font is not None:
        for alt in ("NanumGothic", "Noto Sans CJK KR Regular", "NanumMyeongjo"):
            if alt.replace(" ", "").lower() == str(cap.font_name).replace(" ", "").lower():
                continue
            ap = find_font(alt)
            if ap is not None and ap != exp_path:
                cands.append((alt, ap))
            if len(cands) >= 3:
                break
    scores = []
    for name, fp in cands:
        try:
            r = font_iou(crop, text, fp, cap.size_px, fill_rgb=hex_rgb(cap.color),
                         outline_rgb=hex_rgb(cap.outline_color) if cap.outline_px else None)
            scores.append({"font": name, "iou": rnd((r or {}).get("iou"), 4), "scale": rnd((r or {}).get("scale"), 3)})
        except Exception as e:
            scores.append({"font": name, "error": f"{type(e).__name__}: {e}"[:200]})
    ok = [s for s in scores if s.get("iou") is not None]
    if not ok or scores[0].get("iou") is None:
        return {"status": "unmeasured", "reason": "font_iou 계산 실패", "scores": scores}
    best = max(ok, key=lambda s: s["iou"])
    return {"status": "measured", "expected": cap.font_name, "best": best["font"], "iou_expected": scores[0]["iou"],
            "scores": scores}


# ----------------------------------------------------------------------------- tone
def classify_register(texts: list[str]) -> dict:
    cnt: Counter = Counter()
    for t in texts:
        s = re.sub(r"[^\w가-힣]+$", "", (t or "").strip())
        if not s:
            continue
        last = s[-1]
        if last == "요":
            cnt["해요체"] += 1
        elif last in "음함임슴됨":
            cnt["음슴체"] += 1
        elif last in "다야어아지네냐까군라자해봐와줘가":
            cnt["반말_구어체"] += 1
        else:
            cnt["기타"] += 1
    n = sum(cnt.values())
    mode = cnt.most_common(1)[0][0] if n else None
    if n and cnt.most_common(1)[0][1] / n < 0.7 and len([k for k in cnt if k != "기타"]) > 1:
        mode = "혼합"
    return {"n": n, "counts": dict(cnt), "mode": mode}


# ----------------------------------------------------------------------------- identity / corners
def _fuzzy_contains(hay: str, needle: str, thr: float = 0.85) -> float:
    import difflib

    h, n = norm_text(hay), norm_text(needle)
    if not h or not n:
        return 0.0
    if n in h:
        return 1.0
    best = 0.0
    L = len(n)
    for i in range(0, max(1, len(h) - L + 1)):
        seg = h[i:i + L]
        best = max(best, difflib.SequenceMatcher(None, seg, n).ratio())
    return best


def probe_identity(ctx: QAContext, captions: list[dict], step: float = 1.0) -> dict:
    """Forbidden identity text (full-frame OCR, 1 fps + every clip's middle) and leftover
    source text in the corners / bottom band of the video region (upscaled crops)."""
    cv2 = _cv2()
    from . import clip_at

    try:
        forbidden = list(ctx.preset.get("identity_exclusions.forbidden_text") or [])
    except KeyError:
        forbidden = []
    T = ctx.info.duration
    times = [min(T - 0.05, 0.5 + k * step) for k in range(int(max(1, math.floor(T / step))))]
    for c in ctx.resolved.clips:                       # inner cuts: every clip's middle too
        times.append((c.out_start + c.out_end) / 2)
    times = sorted({round(t, 2) for t in times if 0 <= t < T})
    hits, leftovers, samples = [], [], []
    W, H = ctx.info.width, ctx.info.height
    # captions' own OCR text is checked for forbidden terms too
    for cp in captions:
        for f in forbidden:
            sc = _fuzzy_contains(cp.get("ocr") or "", f)
            if sc >= 0.85:
                hits.append({"t": cp.get("t_rest"), "text": f, "score": round(sc, 3), "ocr": cp.get("ocr"),
                             "where": f"caption {cp['id']}"})
    prev_g = None
    prev_words: list[dict] = []
    for t in times:
        fr = grab(ctx.mp4, t)
        g = cv2.cvtColor(fr, cv2.COLOR_RGB2GRAY)
        small = cv2.resize(g, (g.shape[1] // 4, g.shape[0] // 4), interpolation=cv2.INTER_AREA)
        if prev_g is not None and float(np.abs(small.astype(np.int16) - prev_g.astype(np.int16)).mean()) < 1.5:
            words = prev_words                          # practically the same picture: reuse the OCR
        else:
            words = ocr_words(g, psm=11)
        prev_g, prev_words = small, words
        full_text = " ".join(w["text"] for w in words if w["conf"] >= 30)
        for f in forbidden:
            sc = _fuzzy_contains(full_text, f)
            if sc >= 0.85:
                hits.append({"t": t, "text": f, "score": round(sc, 3), "ocr": full_text[:200], "where": "frame"})
        c = clip_at(ctx.resolved, t)
        zones = {"canvas_top_left": [0, 0, W * 0.4, H * 0.12], "canvas_top_right": [W * 0.6, 0, W * 0.4, H * 0.12]}
        if c is not None:
            rx, ry, rw, rh = c.region.x, c.region.y, c.region.w, c.region.h
            zones.update({"video_top_left": [rx, ry, rw * 0.38, rh * 0.3],
                          "video_top_right": [rx + rw * 0.62, ry, rw * 0.38, rh * 0.3],
                          "video_bottom": [rx, ry + rh * 0.72, rw, rh * 0.28]})
        active = [cp for cp in captions if cp.get("found") and cp["start"] - 0.05 <= t <= cp["end"] + 0.05]
        act_text = [cp.get("text", "") for cp in active]
        cand: list[tuple[str, dict]] = []
        for w_ in words:
            cx_, cy_ = w_["box"][0] + w_["box"][2] / 2, w_["box"][1] + w_["box"][3] / 2
            for zname, (zx, zy, zw, zh) in zones.items():
                if zx <= cx_ <= zx + zw and zy <= cy_ <= zy + zh:
                    cand.append((zname, w_))
                    break
        for zname in [z for z in zones if z.startswith("video_")]:
            zx, zy, zw, zh = (int(round(v)) for v in zones[zname])
            zx, zy = max(0, zx), max(0, zy)
            zw, zh = min(W - zx, zw), min(H - zy, zh)
            if zw < 8 or zh < 8:
                continue
            for w_ in ocr_words(g[zy:zy + zh, zx:zx + zw], psm=11, upscale=2):
                w_ = dict(w_)
                w_["box"] = [zx + w_["box"][0], zy + w_["box"][1], w_["box"][2], w_["box"][3]]
                cand.append((zname, w_))
        for zname, w_ in cand:
            txt = w_["text"]
            handle_like = bool(re.search(r"@|www|\.com|\.net|tiktok|youtube|instagram", txt, re.I))
            if len(norm_text(txt)) < 2 or (w_["conf"] < 45 and not handle_like):
                continue
            box = w_["box"]
            if any(rect_intersection(box, cp["bbox_obs"]) > 0.2 * max(1.0, box[2] * box[3]) for cp in active
                   if cp.get("bbox_obs")):
                continue
            if any(text_similarity(txt, at) >= 0.5 or (len(norm_text(txt)) >= 2 and norm_text(txt) in norm_text(at))
                   for at in act_text):
                continue
            leftovers.append({"t": t, "zone": zname, "text": txt, "conf": round(w_["conf"], 1), "handle_like": handle_like,
                              "box": [round(v, 1) for v in box], "clip_id": c.id if c is not None else None})
        samples.append(t)
    groups: list[dict] = []
    for lo in leftovers:
        for gp in groups:
            if gp["zone"] == lo["zone"] and gp["clip_id"] == lo["clip_id"] and text_similarity(gp["text"], lo["text"]) >= 0.6:
                if lo["t"] not in gp["times"]:
                    gp["times"].append(lo["t"])
                gp["confs"].append(lo["conf"])
                gp["handle_like"] = gp["handle_like"] or lo["handle_like"]
                break
        else:
            groups.append({"zone": lo["zone"], "clip_id": lo["clip_id"], "text": lo["text"], "times": [lo["t"]],
                           "confs": [lo["conf"]], "box": lo["box"], "handle_like": lo["handle_like"]})
    for gp in groups:
        gp["persistent"] = (len(gp["times"]) >= 2 and len(norm_text(gp["text"])) >= 3
                            and (max(gp["confs"]) >= 60 or gp["handle_like"]))
    return {"forbidden_terms": forbidden, "sample_times": samples, "forbidden_hits": hits, "leftovers": leftovers[:200],
            "leftover_groups": groups, "ocr_calls": _OCR_STATS["calls"], "ocr_timeouts": _OCR_STATS["timeouts"]}


# ----------------------------------------------------------------------------- entry points
def probe_captions(ctx: QAContext) -> list[dict]:
    cv2 = _cv2()
    from .. import paths

    fr_ = 1.0 / ctx.fps
    out = []
    frame_cache: dict[float, np.ndarray] = {}
    for cap in ctx.resolved.captions:
        mi = cap.motion_in or {}
        dur_in = float(mi.get("dur_s") or 0.0)
        t_rest = min(cap.start + dur_in + 0.12, (cap.start + cap.end) / 2)
        t_rest = max(cap.start + fr_, min(t_rest, cap.end - 2 * fr_))
        t_key = round(t_rest, 3)
        item = {"id": cap.id, "role": cap.role, "text": cap.text, "start": cap.start, "end": cap.end,
                "t_rest": t_key, "expected_bbox": [cap.bbox.x, cap.bbox.y, cap.bbox.w, cap.bbox.h],
                "resolution": [ctx.info.width, ctx.info.height]}
        try:
            frame = frame_cache.get(t_key)
            if frame is None:
                frame = grab(ctx.mp4, t_rest)
                frame_cache[t_key] = frame
            loc = locate_caption(frame, cap)
            item.update({k: v for k, v in loc.items() if k not in ("bbox",)})
            if loc.get("found"):
                item["bbox_obs"] = loc["bbox"]
                x, y, w, h = loc["bbox"]
                pad = 30
                crop = frame[max(0, y - pad):y + h + pad, max(0, x - pad):x + w + pad]
                fp = ctx.frames_dir / f"cap_{_safe(cap.id)}_{int(t_rest * 1000):07d}.png"
                cv2.imwrite(str(fp), cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
                item["evidence_frame"] = paths.relp(fp)
                try:
                    item.update(measure_timing(ctx, cap, loc, frame))
                except Exception as e:
                    item["timing_error"] = f"{type(e).__name__}: {e}"[:300]
                item["font"] = measure_font(frame, cap, loc["bbox"])
        except Exception as e:
            item["found"] = False
            item["error"] = f"{type(e).__name__}: {e}"[:300]
        out.append(item)
    return out


def probe_cover(ctx: QAContext, captions: list[dict]) -> dict:
    plan = ctx.plan or {}
    cov = plan.get("cover") or {}
    t = cov.get("frame_t")
    t = 0.0 if t is None else float(t)
    try:
        src = ctx.preset.get("cover.source")
        role = ctx.preset.get("cover.text_role")
    except KeyError:
        src, role = None, None
    exp_text = cov.get("text") or next((c.text for c in ctx.resolved.captions if c.role == role), None)
    fr = grab(ctx.mp4, t)
    caps_at = [c for c in ctx.resolved.captions if c.start <= t + 1e-3 < c.end and c.role == role]
    ocr = ""
    for c in caps_at:
        loc = locate_caption(fr, c)
        if loc.get("found"):
            ocr += loc.get("ocr", "")
    if not ocr:
        ocr = ocr_text(fr, psm=11)
    return {"t": t, "source": src, "text_role": role, "expected_text": exp_text, "ocr": ocr[:300],
            "similarity": rnd(text_similarity(ocr, exp_text), 3) if exp_text else None,
            "role_caption_visible": bool(caps_at)}


def _safe(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", str(s))[:40]


def probe_text(ctx: QAContext) -> dict:
    ok, ver = tesseract_ok()
    res: dict = {"ocr_engine": ver if ok else None, "errors": {}}
    if not ok:
        res["status"] = "unmeasured"
        res["reason"] = ver
        return res
    try:
        res["captions"] = probe_captions(ctx)
    except Exception as e:
        res["errors"]["captions"] = f"{type(e).__name__}: {e}"
        res["captions"] = []
    try:
        res["identity"] = probe_identity(ctx, res["captions"])
    except Exception as e:
        res["errors"]["identity"] = f"{type(e).__name__}: {e}"
    try:
        good = [c.get("ocr", "") for c in res["captions"] if c.get("found") and (c.get("similarity") or 0) >= 0.6]
        res["tone"] = classify_register(good)
    except Exception as e:
        res["errors"]["tone"] = f"{type(e).__name__}: {e}"
    try:
        res["cover"] = probe_cover(ctx, res["captions"])
    except Exception as e:
        res["errors"]["cover"] = f"{type(e).__name__}: {e}"
    res["status"] = "measured"
    return res
