"""Caption-line measurements shared by the reference analyzer and output QA.

A value measured in a reference video and the same value measured in our rendered MP4 must mean the same thing, so
both sides call ONE implementation (docs/CONTRACT.md §12):

* ``drop_shadow`` -- the drop shadow of one caption line.  ``shortkit.reference.textboxes.measure_line`` calls it
  for every reference line; QA measures the output through the same ``measure_line`` (``qa.probes_text``), so the
  preset key ``text.roles.<role>.shadow_px`` / ``shadow_color`` and its output check read the same estimator.

Definition (the renderer's ASS convention, shortkit/edit/captions.py ``style_line``): the shadow is a copy of the
ink (fill + outline) moved ``shadow_px`` px right AND ``shadow_px`` px down, drawn in ``shadow_color`` under the
text.  Px are the frame's own pixels.
"""
from __future__ import annotations

import math

import numpy as np

SHADOW_ALGO = "shortkit.util.textmeasure.drop_shadow/1"
SHADOW_MAX_PX = 12            # largest offset searched
SHADOW_DIFF_RGB = 40.0        # a pixel 'differs from the background' above this RGB distance
SHADOW_SIDE_COS = 0.5         # side of a pixel: cos(angle between (pixel - nearest fill pixel) and (1, 1)) >= this
#                               = lower-right side (where a shadow lies), <= -this = upper-left side (never shadow)
SHADOW_RING_STOP = 0.15       # a side's extent ends at the first ring (d > 1) whose 'different' share is below this
#                               (the same stop rule as the outline ring loop of reference.textboxes.measure_line)
SHADOW_EDGE_SHARE = 0.5       # the symmetric part (fill anti-aliasing + outline) ends at the first ring below this;
#                               rings at or above it form the ink model the shadow is predicted from
SHADOW_ASYM_PX = 0.75         # lower-right extent minus upper-left extent needed for a shadow (a 1 px shadow gives
#                               ~1.1; a 6 px outline without a shadow up to 0.5 -- SYNTHETIC libass renders)
SHADOW_MIN_IOU = 0.35         # best IoU between the offset-ink prediction and the measured halo below this: 못 잼
DARK_BG_LUMA = 50.0           # a (dark) shadow on a background darker than this cannot be seen


def luma(rgb) -> float:
    return float(np.dot(np.asarray(rgb, float)[:3], [0.2126, 0.7152, 0.0722]))


def glyph_sides(fill: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """``(dist, cos)`` for every pixel: Euclidean distance to the nearest fill pixel, and the cosine of the angle
    between (pixel - that fill pixel) and the drop-shadow direction (1, 1): +1 = straight down-right of the glyph
    edge, -1 = straight up-left (0 on the fill itself)."""
    import cv2

    fill = np.asarray(fill, bool)
    dist, lab = cv2.distanceTransformWithLabels((~fill).astype(np.uint8), cv2.DIST_L2, 5,
                                                labelType=cv2.DIST_LABEL_PIXEL)
    zy, zx = np.nonzero(fill)
    if zy.size == 0:
        return dist, np.zeros(fill.shape, np.float32)
    # label of each fill pixel -> its coordinates (no assumption about OpenCV's label order)
    ids = lab[zy, zx].astype(np.int64)
    lut_x = np.zeros(int(ids.max()) + 1, np.int64)
    lut_y = np.zeros_like(lut_x)
    lut_x[ids], lut_y[ids] = zx, zy
    H, W = fill.shape
    yy, xx = np.mgrid[0:H, 0:W]
    li = np.clip(lab.astype(np.int64), 0, lut_x.size - 1)
    vx = (xx - lut_x[li]).astype(np.float32)
    vy = (yy - lut_y[li]).astype(np.float32)
    n = np.hypot(vx, vy)
    cos = np.where(n > 0, (vx + vy) / (np.maximum(n, 1e-6) * math.sqrt(2.0)), 0.0).astype(np.float32)
    return dist, cos


def _ring_shares(diff: np.ndarray, dist: np.ndarray, side: np.ndarray, dmax: int) -> list[float | None]:
    """Share of 'different from the background' pixels in each 1-px distance ring (d-1, d] of one side."""
    ring = np.ceil(dist).astype(np.int64)
    sel = side & (ring >= 1) & (ring <= dmax)
    n = np.bincount(ring[sel], minlength=dmax + 1)
    k = np.bincount(ring[sel], weights=diff[sel].astype(np.float64), minlength=dmax + 1)
    return [float(k[d] / n[d]) if n[d] >= 5 else None for d in range(1, dmax + 1)]


def _extent_tail(shares: list[float | None]) -> float | None:
    """Sum of ring shares until a ring (d > 1) falls below SHADOW_RING_STOP; None = never ends (busy / unbounded)."""
    tot = 0.0
    for i, f in enumerate(shares):
        if f is None:
            return tot if i > 0 else None
        if i > 0 and f < SHADOW_RING_STOP:
            return tot
        tot += f
    return None


def _extent_edge(shares: list[float | None]) -> float | None:
    """The symmetric part only: ring shares up to the first ring below SHADOW_EDGE_SHARE (its share counted when it
    is >= SHADOW_RING_STOP).  A shadow's bleed onto the upper-left side (from a stroke further up-left) is a slowly
    falling tail below 0.5 and is not counted."""
    tot = 0.0
    for f in shares:
        if f is None:
            return tot
        if f >= SHADOW_RING_STOP:
            tot += f
        if f < SHADOW_EDGE_SHARE:
            return tot
    return None


def _shift(m: np.ndarray, k: int) -> np.ndarray:
    out = np.zeros_like(m)
    H, W = m.shape
    if k < H and k < W:
        out[k:, k:] = m[:H - k, :W - k]
    return out


def _hex(rgb) -> str:
    r, g, b = (int(round(min(255.0, max(0.0, float(c))))) for c in list(rgb)[:3])
    return f"#{r:02X}{g:02X}{b:02X}"


def _r(v, d: int = 3):
    return None if v is None else round(float(v), d)


def drop_shadow(crop: np.ndarray, fill: np.ndarray, bg_col, *, max_px: int = SHADOW_MAX_PX) -> dict:
    """Drop shadow of one caption line from its glyph FILL mask (``crop`` RGB, ``fill`` bool of the same size,
    ``bg_col`` = local background RGB).

    1. Halo = pixels outside the fill that differ from the background by > SHADOW_DIFF_RGB.
    2. Every pixel is on the upper-left or the lower-right side of the glyph edge nearest to it (``glyph_sides``).
       An outline and the fill's anti-aliasing are the same on both sides; a shadow adds halo on the lower-right
       side only.  Extent of each side = summed halo share of the 1-px distance rings (outline ring-loop stop rule).
    3. Lower-right extent - upper-left extent < SHADOW_ASYM_PX -> no shadow (``shadow_px`` 0, measured).
    4. Otherwise the ink model I = fill + the upper-left rings that are >= 50 % different; offset = the k whose prediction
       shift(I, (k, k)) - I best matches the halo outside I (IoU, k = 1..max_px, sub-pixel parabola); colour = median
       of the 30 % of the halo inside that prediction that differ most from the background (1 px away from the ink
       when there are enough such pixels).

    Returns ``{status: measured|unmeasured, shadow_px, shadow_color, reason?, ...evidence}``; unmeasured (못 잼) when
    the background is unknown or too dark (luma < 50: a dark shadow is invisible), the upper-left side never
    returns to the background (busy footage / an undetected box), or the offset prediction does not fit.
    Measuring against the fill (not an outline measured all around the glyphs) keeps a shadow in the outline's
    colour (black on black) from being read as a thicker outline."""
    out: dict = {"algo": SHADOW_ALGO,
                 "method": "글자 채움 기준 왼쪽 위(그림자 없는 쪽)와 오른쪽 아래의 '배경과 다른 화소' 폭 차이 ≥ "
                           f"{SHADOW_ASYM_PX}px 이면 그림자 있음 → (채움 + 왼쪽 위 폭)을 오른쪽 아래로 k px 옮긴 모양과 "
                           "배경과 다른 화소의 IoU 최대 k(포물선 보정), 색 = 그 안에서 배경과 가장 다른 30% 화소의 중앙값",
                 "shadow_px": None, "shadow_color": None}
    if bg_col is None:
        return {**out, "status": "unmeasured", "reason": "배경색을 모름"}
    bg = np.asarray(bg_col, np.float32)[:3]
    if luma(bg) < DARK_BG_LUMA:
        return {**out, "status": "unmeasured", "reason": f"배경이 어두워(휘도 < {DARK_BG_LUMA:g}) 그림자가 보이지 않음"}
    fill = np.asarray(fill, bool)
    if int(fill.sum()) < 10:
        return {**out, "status": "unmeasured", "reason": "글자 채움이 너무 작음"}
    import cv2

    ys, _xs = np.nonzero(fill)
    fh = int(ys.max() - ys.min() + 1)
    dist, cos = glyph_sides(fill)
    diff = (np.sqrt(((crop[..., :3].astype(np.float32) - bg) ** 2).sum(axis=2)) > SHADOW_DIFF_RGB) & ~fill
    d_outline = int(max(3, min(0.5 * fh, 20)))          # the outline search range of textboxes.measure_line
    dmax = d_outline + int(max_px) + 2
    ul, dr = cos <= -SHADOW_SIDE_COS, cos >= SHADOW_SIDE_COS
    su, sd = _ring_shares(diff, dist, ul, dmax), _ring_shares(diff, dist, dr, dmax)
    e_ul, t_ul, t_dr = _extent_edge(su), _extent_tail(su), _extent_tail(sd)
    out.update({"rings_upper_left": [_r(v, 2) for v in su[:16]], "rings_lower_right": [_r(v, 2) for v in sd[:16]],
                "extent_upper_left_px": _r(t_ul, 2), "extent_lower_right_px": _r(t_dr, 2),
                "symmetric_px": _r(e_ul, 2)})
    if e_ul is None or t_ul is None:
        return {**out, "status": "unmeasured", "reason": "왼쪽 위(그림자가 없는 쪽)도 배경으로 돌아오지 않음(복잡한 배경/박스)"}
    if t_dr is None:
        return {**out, "status": "unmeasured", "reason": "오른쪽 아래가 배경으로 돌아오지 않음(그림자 폭을 정할 수 없음)"}
    asym = t_dr - t_ul
    out["asymmetry_px"] = _r(asym, 2)
    if asym < SHADOW_ASYM_PX:
        return {**out, "status": "measured", "shadow_px": 0.0, "shadow_color": None}
    # ink model = fill + the upper-left rings that are mostly (>= 50 %) different from the background.  Its extent
    # sets where the predicted shadow ends, so a model narrower or wider than the visible ink moves the best offset
    # by the same amount (SYNTHETIC libass renders: 'dist <= summed extent' left out the 58 %-covered 4th ring of a
    # 3 px outline and read a 3 px shadow as 3.9 px; with whole rings >= 50 %: 3.0 px)
    n_ink = 0
    for f in su:
        if f is None or f < SHADOW_EDGE_SHARE:
            break
        n_ink += 1
    ink = fill | (dist <= n_ink)
    halo = diff & ~ink & (dist <= e_ul + 1.5 * max_px + 2)
    scores: list[tuple[float, int]] = []
    for k in range(1, int(max_px) + 1):
        P = _shift(ink, k) & ~ink
        u = float((P | halo).sum())
        scores.append((float((P & halo).sum()) / u if u else 0.0, k))
    out["scores"] = [[k, _r(v, 3)] for v, k in scores]
    best, k = max(scores)
    out["iou"] = _r(best, 3)
    if best < SHADOW_MIN_IOU:
        return {**out, "status": "unmeasured",
                "reason": "오른쪽 아래가 배경과 더 다르지만 옮긴 글자 모양과 맞지 않음(그림자 폭을 정할 수 없음)"}
    kv = {kk: v for v, kk in scores}
    kf = float(k)
    if k - 1 in kv and k + 1 in kv:
        den = kv[k - 1] - 2 * kv[k] + kv[k + 1]
        if den < 0:
            kf = k + 0.5 * (kv[k - 1] - kv[k + 1]) / den
    near = cv2.dilate(ink.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    sel = _shift(ink, k) & ~near & diff
    if sel.sum() < 10:
        sel = _shift(ink, k) & ~ink & diff
    color = None
    if sel.sum() >= 10:
        px = crop[sel][:, :3].astype(float)
        # a thin (1-2 px) shadow is mostly anti-aliased blend with the background: the colour is read from the
        # pixels furthest from the background (the fully covered ones; SYNTHETIC 2 px black shadow read #505050
        # from the median of all its pixels)
        far_ = np.linalg.norm(px - bg, axis=1)
        px = px[far_ >= np.percentile(far_, 70)]
        color = _hex(np.median(px, axis=0))
    return {**out, "status": "measured", "shadow_px": round(kf, 2), "shadow_px_int": int(k), "shadow_color": color}
