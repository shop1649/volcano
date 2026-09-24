"""Reference font identification with an explicit IoU ceiling.

Why a ceiling
-------------
Comparing a caption crop cut from a compressed YouTube video with a clean render of a
candidate font can never reach IoU 1.0: scaling, chroma subsampling, quantisation and the
mask extraction itself eat pixels at every edge.  A raw IoU (say 0.86) therefore means nothing
on its own.  This module measures, for the *same* pipeline, how high the IoU of the TRUE font
gets (``ceiling``: render known strings with a font -> degrade exactly like the reference
(scale to the reference resolution, H.264/VP9/AV1 encode at the reference CRF/bitrate,
decode) -> same mask extraction -> IoU against the clean render of that same font), and how
high the IoU of the NEAREST OTHER fonts gets under the same degradation (``discriminability``).

Verdicts (``identify``)
-----------------------
``identical``  IoU >= ceiling p10 of that font under these conditions AND the margin over the
               best other candidate > measured noise AND the per-glyph check passes.
``similar``    not excluded, but not proven (e.g. a near-duplicate weight within noise).
``different``  IoU < ceiling p10 - noise: below what the same font reaches 90 % of the time.
Only ``identical`` may be written to a preset as a measured ``font_name``; ``similar`` stays
``unmeasured`` (못 잼) with the nearest candidate listed as information, never as the value.

Mask convention: the *fill* mask (glyph interior, outline excluded) is what is compared,
because outline width is a separate style parameter.  Pixels are classified on luma between
the outline and fill colours (t >= 0.5 -> fill; chroma only gates out background colours,
since yuv420 chroma bleeds across edges), which reproduces the 50 % coverage threshold used
for the rendered candidate.

Everything measured here is tied to its conditions (canvas + reference resolution, codec,
CRF/bitrate, renderer, background); a ceiling measured under ASSUMED conditions is labelled
as such and never stands in for the real reference download's conditions.
"""
from __future__ import annotations

import argparse
import io
import math
import os
import sys
import tempfile
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from .. import paths
from ..util.jsonio import now_iso, read_json, read_jsonl, write_json
from ..util.media import FFMPEG, MediaError, probe, run
from ..util.stats import pstats

UPSAMPLE = 4               # candidate rendered at 4x -> translation search step 0.25 px
SCALE_RANGE = 0.15         # +-15 % around the ink-height matched size
GLYPH_PASS_SHARE = 0.5     # share of glyphs that must reach the per-glyph ceiling p10 (and none below the fence)

# Korean caption-like strings used for ceiling experiments (no reference content).
DEFAULT_STRINGS = [
    "아니 이게 무슨 일이야",
    "저기 봐 들어온다",
    "결국 참지 못한 남자",
    "역대급 반전 등장",
    "잠깐만 이거 진짜야?",
    "끝까지 보면 소름",
    "갑자기 벌어진 일",
    "사장님의 한마디",
]
DEFAULT_SIZES = [40, 56, 72, 90]
STYLE_VARIANTS = {
    # name: (fill, outline, outline width as a fraction of the font size)
    "white_black_outline": ((255, 255, 255), (0, 0, 0), 0.075),
    "yellow_black_outline": ((255, 228, 0), (0, 0, 0), 0.075),
    "white_no_outline": ((255, 255, 255), None, 0.0),
}

VERDICT_KO = {"identical": "동일", "similar": "유사(동일 확정 불가)", "different": "다름", "unmeasured": "못 잼"}


# ============================================================================= colours & masks
def parse_rgb(c: Any) -> tuple[int, int, int] | None:
    if c is None:
        return None
    if isinstance(c, str):
        s = c.strip()
        if s.upper().startswith("&H"):           # ASS colour: &H[AA]BBGGRR[&]
            h = s[2:].rstrip("&")
            if len(h) not in (6, 8):
                raise ValueError(f"bad colour {c!r}")
            h = h[-6:]
            return int(h[4:6], 16), int(h[2:4], 16), int(h[0:2], 16)
        s = s.lstrip("#")
        if len(s) == 8:                          # #RRGGBBAA -> RRGGBB
            s = s[:6]
        if len(s) != 6:
            raise ValueError(f"bad colour {c!r}")
        return int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
    t = tuple(int(round(float(v))) for v in c)
    if len(t) < 3:
        raise ValueError(f"bad colour {c!r}")
    return t[0], t[1], t[2]


def _disk(r: int) -> np.ndarray:
    import cv2

    r = max(1, int(r))
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))


def estimate_colors(crop_rgb: np.ndarray) -> dict:
    """Estimate fill / outline / background colours of a caption crop (cut with a margin).

    k-means (k=4) on pixel colours.  For each cluster only its connected components that do
    NOT touch the crop border count (glyph fills never touch it; background does).  The fill
    cluster maximises  area x contrast-to-its-ring x ring-purity^3: glyph fills are wrapped by
    one colour (the outline, or the local background), outlines by two (fill + background).
    outline = median colour of the ring 2-3 px around those components (equals the
    background when there is no outline).
    """
    import cv2

    img = np.ascontiguousarray(crop_rgb[..., :3])
    h, w = img.shape[:2]
    px = img.reshape(-1, 3).astype(np.float32)
    k = 4 if len(px) >= 64 else 2
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    cv2.setRNGSeed(12345)
    _, labels, centers = cv2.kmeans(px, k, None, crit, 2, cv2.KMEANS_PP_CENTERS)
    lab = labels.reshape(h, w)
    imgf = img.astype(np.float32)
    best = None
    for c in range(k):
        m = (lab == c).astype(np.uint8)
        n, cc, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
        if n <= 1:
            continue
        xs, ys, ws, hs, area = st[:, 0], st[:, 1], st[:, 2], st[:, 3], st[:, 4]
        touch = (xs == 0) | (ys == 0) | (xs + ws >= w) | (ys + hs >= h)
        ok = ~touch & (area >= 3)
        ok[0] = False
        if not ok.any():
            continue
        interior = ok[cc]
        ring = (cv2.dilate(interior.astype(np.uint8), _disk(3)) > 0) & \
            ~(cv2.dilate(interior.astype(np.uint8), _disk(1)) > 0) & (m == 0)
        if not ring.any():
            continue
        core = cv2.erode(interior.astype(np.uint8), _disk(1)) > 0
        inner = imgf[core] if core.any() else imgf[interior]
        f = np.median(inner, axis=0)
        rpx = imgf[ring]
        o = np.median(rpx, axis=0)
        contrast = float(np.linalg.norm(f - o))
        # ring purity: a glyph fill is wrapped by ONE colour (outline); an outline is wrapped
        # by the fill on one side and the background on the other
        purity = float(np.bincount(lab[ring], minlength=k).max()) / float(ring.sum())
        score = float(interior.sum()) * contrast * purity ** 3
        if best is None or score > best[0]:
            best = (score, f, o, c)
    if best is None:
        raise ValueError("no text-like colour cluster in crop (crop must include a margin around the caption)")
    bpx = np.concatenate([img[0, :], img[-1, :], img[:, 0], img[:, -1]])
    bg_rgb = np.median(bpx, axis=0)
    return {"fill": tuple(int(round(v)) for v in best[1]), "outline": tuple(int(round(v)) for v in best[2]),
            "background": tuple(int(v) for v in bg_rgb), "method": "kmeans4+interior-components+ring"}


def extract_masks(crop_rgb: np.ndarray, fill_rgb: Any = None, outline_rgb: Any = None,
                  drop_border: bool = True) -> dict:
    """Fill / outline masks of a caption crop by colour classification.

    ``fill_rgb``/``outline_rgb`` given -> used as is; missing ones are estimated
    (:func:`estimate_colors`).  When fill and outline differ in luma (the normal case) the
    decision is made on luma -- t = (Y - Y_outline) / (Y_fill - Y_outline), t >= 0.5 -> fill --
    because yuv420 video keeps luma at full resolution while chroma bleeds across edges; the
    chroma of a pixel must lie near the fill<->outline chroma segment (else background).  With
    no usable luma contrast the RGB projection onto the outline->fill segment is used.
    Fill components not enclosed by outline-coloured pixels (background objects that happen
    to share the fill colour) are dropped when the crop shows a consistent ring, and with
    ``drop_border`` (crops are cut with a margin around the caption) components touching the
    crop border are background by construction.
    """
    import cv2

    img = np.asarray(crop_rgb)[..., :3].astype(np.float32)
    f = parse_rgb(fill_rgb)
    o = parse_rgb(outline_rgb)
    est = None
    if f is None or o is None:
        est = estimate_colors(np.asarray(crop_rgb)[..., :3].astype(np.uint8))
        f = f or est["fill"]
        o = o or est["outline"]
    fv = np.array(f, np.float32)
    ov = np.array(o, np.float32)
    d = fv - ov
    L2 = float(d @ d)
    if L2 < 30.0 ** 2:
        raise ValueError(f"fill {f} and outline/background {o} colours are too close to separate")
    Yp, Cp = _ycc(img)
    Yf, Cf = _ycc(fv)
    Yo, Co = _ycc(ov)
    if abs(float(Yf - Yo)) >= 50.0:
        # yuv420 video: luma is full resolution, chroma is half resolution and bleeds across
        # edges -> fill/outline decided on luma (linear in coverage), chroma only rejects
        # colours that cannot be a fill/outline mixture.
        method = "luma+chroma-gate"
        t = (Yp - float(Yo)) / float(Yf - Yo)
        dc = Cf - Co
        Lc = float(dc @ dc)
        if Lc < 1.0:
            rc = np.linalg.norm(Cp - Co, axis=-1)
        else:
            u = np.clip(((Cp - Co) @ dc) / Lc, 0.0, 1.0)
            rc = np.linalg.norm(Cp - (Co + u[..., None] * dc), axis=-1)
        on_line = rc < max(24.0, 0.35 * math.sqrt(Lc))
    else:
        method = "rgb-projection"
        t = ((img - ov) @ d) / L2
        proj = ov + t[..., None] * d
        r = np.linalg.norm(img - proj, axis=-1)
        on_line = r < max(30.0, 0.3 * math.sqrt(L2))
    fill = on_line & (t >= 0.5) & (t <= 1.6)
    outline = on_line & (t < 0.5) & (t >= -0.6)
    # drop specks
    n, cc, st, _ = cv2.connectedComponentsWithStats(fill.astype(np.uint8), connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= 3
    if drop_border and n > 1:
        H_, W_ = fill.shape
        xs, ys, ws, hs = st[:, 0], st[:, 1], st[:, 2], st[:, 3]
        touch = (xs == 0) | (ys == 0) | (xs + ws >= W_) | (ys + hs >= H_)
        keep[1:] &= ~touch[1:]
    # enclosure filter
    ring_ok_total, ring_total = 0, 0
    comp_ring: list[tuple[int, int, int]] = []
    for i in range(1, n):
        if not keep[i]:
            continue
        x, y, ww, hh = st[i, :4]
        x0, y0, x1, y1 = max(0, x - 3), max(0, y - 3), min(fill.shape[1], x + ww + 3), min(fill.shape[0], y + hh + 3)
        comp = (cc[y0:y1, x0:x1] == i).astype(np.uint8)
        ring = (cv2.dilate(comp, _disk(2)) > 0) & (comp == 0) & ~fill[y0:y1, x0:x1]
        nr = int(ring.sum())
        ok = int((ring & outline[y0:y1, x0:x1]).sum())
        comp_ring.append((i, ok, nr))
        ring_ok_total += ok
        ring_total += nr
    global_agree = ring_ok_total / ring_total if ring_total else 0.0
    enclosure = global_agree >= 0.6
    if enclosure:
        for i, ok, nr in comp_ring:
            if nr and ok / nr < 0.7:
                keep[i] = False
    fill = keep[cc]
    if outline.any() and fill.any():
        near = cv2.dilate(fill.astype(np.uint8), _disk(max(2, int(0.12 * max(1, _ink_height(fill)))))) > 0
        outline = outline & near
    return {"fill": fill, "outline": outline, "fill_rgb": tuple(int(v) for v in fv), "outline_rgb": tuple(int(v) for v in ov),
            "estimated": est is not None, "estimate": est, "enclosure_filter": enclosure, "method": method,
            "ring_agreement": round(global_agree, 3)}


def _ycc(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """BT.601 full-range luma and (Cb, Cr) of RGB values (any leading shape)."""
    a = np.asarray(rgb, np.float32)
    R, G, B = a[..., 0], a[..., 1], a[..., 2]
    Y = 0.299 * R + 0.587 * G + 0.114 * B
    Cb = -0.168736 * R - 0.331264 * G + 0.5 * B
    Cr = 0.5 * R - 0.418688 * G - 0.081312 * B
    return Y, np.stack([Cb, Cr], axis=-1)


def _ink_height(mask: np.ndarray, frac: float = 0.0) -> int:
    rows = mask.sum(axis=1)
    if rows.max(initial=0) == 0:
        return 0
    thr = max(0.0, frac * rows.max())
    ys = np.nonzero(rows > thr)[0]
    return int(ys[-1] - ys[0] + 1)


# ============================================================================= rendering
@lru_cache(maxsize=32)
def _font_bytes(path: str, mtime_ns: int, size: int) -> bytes:
    return Path(path).read_bytes()


def load_font(font_path: str | os.PathLike, size: float, index: int = 0):
    from PIL import ImageFont

    p = Path(font_path)
    st = p.stat()
    return ImageFont.truetype(io.BytesIO(_font_bytes(str(p), st.st_mtime_ns, st.st_size)), size=float(size),
                              index=int(index))


@dataclass
class FontRef:
    name: str
    path: str                 # runtime path (absolute or root-relative)
    index: int = 0

    @property
    def abspath(self) -> Path:
        return paths.absp(self.path)


def font_ref(name_or_path: str | os.PathLike | FontRef, index: int | None = None) -> FontRef:
    """FontRef from an exact font name (shortkit.fonts.resolve_font) or a file path."""
    if isinstance(name_or_path, FontRef):
        return name_or_path
    s = str(name_or_path)
    p = Path(s)
    if p.suffix.lower() in (".ttf", ".otf", ".ttc", ".otc") and paths.absp(s).is_file():
        idx = 0 if index is None else index
        from ..fonts import face_infos

        faces = [f for f in face_infos(paths.absp(s)) if f.index == idx]
        nm = faces[0].canonical if faces else p.stem
        return FontRef(name=nm, path=s, index=idx)
    from ..fonts import resolve_font

    face = resolve_font(s)
    if face is None:
        raise FileNotFoundError(f"font '{s}' not found (exact name match required, no fallback)")
    return FontRef(name=face.canonical, path=str(face.path), index=face.index)


def render_coverage(text: str, font_path: str | os.PathLike, size_px: float, face_index: int = 0,
                    stroke_px: float = 0.0, margin: int = 2) -> tuple[np.ndarray, dict]:
    """Anti-aliased coverage (float32 0..1) of ``text`` tightly cropped (+margin px).

    meta: origin (x, y) of the baseline-left anchor inside the array, per-glyph boxes
    [x0, y0, x1, y1] in array coordinates (spaces skipped).
    """
    from PIL import Image, ImageDraw

    font = load_font(font_path, size_px, face_index)
    sw = float(stroke_px)
    x0, y0, x1, y1 = font.getbbox(text, anchor="ls", stroke_width=sw)
    W, H = int(x1 - x0) + 2 * margin, int(y1 - y0) + 2 * margin
    ox, oy = margin - x0, margin - y0
    im = Image.new("L", (max(1, W), max(1, H)), 0)
    ImageDraw.Draw(im).text((ox, oy), text, font=font, fill=255, anchor="ls", stroke_width=sw, stroke_fill=255)
    raw = np.asarray(im, dtype=np.uint8)
    cov = raw.astype(np.float32) / 255.0
    boxes = []
    for i, ch in enumerate(text):
        if ch.isspace():
            continue
        adv = font.getlength(text[:i])
        bx0, by0, bx1, by1 = font.getbbox(ch, anchor="ls")
        if bx1 <= bx0 or by1 <= by0:
            continue
        boxes.append({"i": i, "ch": ch, "box": [ox + adv + bx0, oy + by0, ox + adv + bx1, oy + by1]})
    return cov, {"origin": (ox, oy), "glyphs": boxes, "size_px": float(size_px), "raw_u8": raw}


def draw_caption(canvas_rgb: np.ndarray, text: str, font_path: str | os.PathLike, size_px: float,
                 xy: tuple[float, float], fill_rgb: Any, outline_rgb: Any = None, outline_px: float = 0.0,
                 face_index: int = 0, supersample: int = 4) -> tuple[np.ndarray, list[float]]:
    """Draw a caption (fill over outline stroke) at baseline-left ``xy`` (sub-pixel) on an RGB array.

    ``supersample`` > 1 renders the text layer at that factor and box-downsamples it
    (unhinted, fractional positioning -- how video editors / libass render text);
    ``supersample`` = 1 uses FreeType's hinted 1x raster.  Returns (image, ink bbox
    [x0, y0, x1, y1] incl. outline, float px)."""
    from PIL import Image, ImageDraw

    img = np.ascontiguousarray(canvas_rgb[..., :3]).astype(np.float32)
    k = max(1, int(supersample))
    sw = float(outline_px) if outline_rgb is not None else 0.0
    font1 = load_font(font_path, size_px, face_index)
    bx0, by0, bx1, by1 = font1.getbbox(text, anchor="ls", stroke_width=sw)
    box = [xy[0] + bx0, xy[1] + by0, xy[0] + bx1, xy[1] + by1]
    H, W = img.shape[:2]
    m = int(math.ceil(sw)) + 4
    X0, Y0 = max(0, int(math.floor(box[0])) - m), max(0, int(math.floor(box[1])) - m)
    X1, Y1 = min(W, int(math.ceil(box[2])) + m), min(H, int(math.ceil(box[3])) + m)
    if X1 <= X0 or Y1 <= Y0:
        return img.astype(np.uint8), box
    fontk = load_font(font_path, size_px * k, face_index)
    org = ((xy[0] - X0) * k, (xy[1] - Y0) * k)

    def layer(stroke: float) -> np.ndarray:
        im = Image.new("L", ((X1 - X0) * k, (Y1 - Y0) * k), 0)
        kw = {"stroke_width": stroke * k, "stroke_fill": 255} if stroke > 0 else {}
        ImageDraw.Draw(im).text(org, text, font=fontk, fill=255, anchor="ls", **kw)
        a = np.asarray(im, np.float32) / 255.0
        return a.reshape(Y1 - Y0, k, X1 - X0, k).mean(axis=(1, 3)) if k > 1 else a

    a_f = layer(0.0)[..., None]
    region = img[Y0:Y1, X0:X1]
    fill = np.array(parse_rgb(fill_rgb), np.float32)
    if sw > 0:
        a_u = np.maximum(layer(sw)[..., None], a_f)
        out = np.array(parse_rgb(outline_rgb), np.float32)
        region = region * (1 - a_u) + out * (a_u - a_f) + fill * a_f
    else:
        region = region * (1 - a_f) + fill * a_f
    img[Y0:Y1, X0:X1] = region
    return np.clip(np.round(img), 0, 255).astype(np.uint8), box


# ============================================================================= alignment / IoU
def _phase_template(S: np.ndarray, th: int, tw: int, U: int, py: int, px: int) -> np.ndarray:
    """Low-res template of hi-res coverage placed at hi-res offset (py, px) inside the first
    low-res pixel, from the integral image ``S`` of the uint8 coverage (shape th+1 x tw+1):
    exact box downsampling."""
    Hq = -(-(th + py) // U)
    Wq = -(-(tw + px) // U)
    r = np.arange(Hq + 1) * U - py
    c = np.arange(Wq + 1) * U - px
    r = np.clip(r, 0, th)
    c = np.clip(c, 0, tw)
    A = S[np.ix_(r, c)]
    return ((A[1:, 1:] - A[:-1, 1:] - A[1:, :-1] + A[:-1, :-1]) / float(255 * U * U)).astype(np.float32)


def _iou_at(Mpad: np.ndarray, msum: int, D: np.ndarray, r0: int, c0: int) -> tuple[float, int, int]:
    h, w = D.shape
    Hs, Ws = Mpad.shape
    rr0, cc0 = max(0, r0), max(0, c0)
    rr1, cc1 = min(Hs, r0 + h), min(Ws, c0 + w)
    inter = 0
    if rr1 > rr0 and cc1 > cc0:
        inter = int((D[rr0 - r0:rr1 - r0, cc0 - c0:cc1 - c0] & Mpad[rr0:rr1, cc0:cc1]).sum())
    union = int(D.sum()) + msum - inter
    return (inter / union if union else 0.0), inter, union


def _eval_scale(M: np.ndarray, text: str, font: FontRef, size: float, U: int, pad: int,
                glyphs: bool = False, phase_step: int = 1) -> dict:
    """Best hard IoU of ``text`` at ``size`` over all translations (1/U px grid).

    For every sub-pixel phase the hi-res coverage is box-downsampled exactly (integral image)
    and cross-correlated with the mask at crop resolution (soft intersection); the best
    integer shift of each phase and its 3x3 neighbourhood are scored by hard IoU."""
    import cv2

    cov, meta = render_coverage(text, font.abspath, size * U, font.index, margin=U)
    th, tw = cov.shape
    S = np.zeros((th + 1, tw + 1), np.int64 if th * tw > 8_000_000 else np.int32)
    S[1:, 1:] = meta["raw_u8"].cumsum(0, dtype=S.dtype).cumsum(1, dtype=S.dtype)
    h, w = M.shape
    Hq, Wq = -(-(th + U) // U), -(-(tw + U) // U)
    P = pad + int(max(0, Hq - h, Wq - w))
    Mpad = np.pad(M, P)
    Mf = Mpad.astype(np.float32)
    msum = int(M.sum())
    best = (-1.0, 0, 0, 0, 0, None, 0, 0)
    for py in range(0, U, phase_step):
        for px in range(0, U, phase_step):
            T = _phase_template(S, th, tw, U, py, px)
            R = cv2.matchTemplate(Mf, T, cv2.TM_CCORR)
            iy, ix = np.unravel_index(int(np.argmax(R)), R.shape)
            D = T >= 0.5
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    y, x = int(iy) + dy, int(ix) + dx
                    iou, inter, union = _iou_at(Mpad, msum, D, y, x)
                    if iou > best[0]:
                        best = (iou, y, x, py, px, D, inter, union)
    iou, y, x, py, px, D, inter, union = best
    # hi-res position of the coverage array's top-left in padded crop coords
    hx, hy = x * U + px, y * U + py
    ax = (hx + meta["origin"][0]) / U - P
    ay = (hy + meta["origin"][1]) / U - P
    out = {"iou": float(iou), "size_px": float(size), "anchor_xy": (round(ax, 3), round(ay, 3)),
           "inter": inter, "union": union}
    if glyphs and D is not None:
        gl = []
        for g in meta["glyphs"]:
            gx0, gy0, gx1, gy1 = g["box"]
            wx0 = max(int(math.floor((hx + gx0) / U)) - 1, 0)
            wy0 = max(int(math.floor((hy + gy0) / U)) - 1, 0)
            wx1 = min(int(math.ceil((hx + gx1) / U)) + 1, Mpad.shape[1])
            wy1 = min(int(math.ceil((hy + gy1) / U)) + 1, Mpad.shape[0])
            if wx1 <= wx0 or wy1 <= wy0:
                continue
            Mw = Mpad[wy0:wy1, wx0:wx1]
            Dw = np.zeros_like(Mw)
            ry0, rx0 = max(wy0, y), max(wx0, x)
            ry1, rx1 = min(wy1, y + D.shape[0]), min(wx1, x + D.shape[1])
            if ry1 > ry0 and rx1 > rx0:
                Dw[ry0 - wy0:ry1 - wy0, rx0 - wx0:rx1 - wx0] = D[ry0 - y:ry1 - y, rx0 - x:rx1 - x]
            gi = int((Mw & Dw).sum())
            gu = int((Mw | Dw).sum())
            gl.append({"i": g["i"], "ch": g["ch"], "iou": round(gi / gu, 4) if gu else 0.0})
        out["glyphs"] = gl
    return out


def _split_lines(M: np.ndarray, n: int) -> list[tuple[int, int]] | None:
    """Split a multi-line mask into n horizontal bands at the emptiest row gaps."""
    rows = M.sum(axis=1)
    ys = np.nonzero(rows)[0]
    if len(ys) == 0:
        return None
    if n == 1:
        return [(0, M.shape[0])]
    lo, hi = ys[0], ys[-1] + 1
    band = (hi - lo) / n
    cuts = []
    for k in range(1, n):
        c = lo + band * k
        a, b = int(c - band * 0.35), int(c + band * 0.35)
        seg = rows[a:b]
        if len(seg) == 0:
            return None
        cuts.append(a + int(np.argmin(seg)))
    edges = [0] + cuts + [M.shape[0]]
    return [(edges[i], edges[i + 1]) for i in range(n)]


def mask_iou(mask: np.ndarray, text: str, font: FontRef | str, size_hint_px: float | None = None,
             upsample: int = UPSAMPLE, scale_range: float = SCALE_RANGE, glyphs: bool = True) -> dict:
    """Best IoU between a binary fill mask and the rendered ``text`` in ``font``.

    Search: scale within +-``scale_range`` around the ink-height-matched size (plus around
    ``size_hint_px`` when that lies outside), coarse 5 % steps refined by halving down to
    0.3 %; translation by cross-correlation on a ``upsample``x grid (1/``upsample`` px) with a
    3x3 hard-IoU refinement.  Multi-line text (``\\n``) is split into line bands.
    """
    fr = font_ref(font)
    M = np.asarray(mask, bool)
    lines = [ln for ln in text.split("\n") if ln.strip()]
    if not lines or not M.any():
        return {"iou": 0.0, "scale": None, "dx": None, "dy": None, "error": "empty mask or text"}
    bands = _split_lines(M, len(lines))
    if bands is None:
        return {"iou": 0.0, "scale": None, "dx": None, "dy": None, "error": "cannot split lines"}
    res_lines, inter_sum, union_sum = [], 0.0, 0.0
    for ln, (a, b) in zip(lines, bands):
        r = _line_iou(M[a:b], ln, fr, size_hint_px, upsample, scale_range, glyphs)
        r["band"] = [a, b]
        res_lines.append(r)
        # recombine as pooled IoU
        inter_sum += r.pop("_inter", 0)
        union_sum += r.pop("_union", 0)
    iou = inter_sum / union_sum if union_sum else 0.0
    first = res_lines[0]
    out = {"iou": round(float(iou), 4), "scale": first.get("scale"), "dx": first.get("dx"), "dy": first.get("dy"),
           "size_px": first.get("size_px"), "font": fr.name}
    if len(res_lines) > 1:
        out["lines"] = res_lines
    if glyphs:
        out["glyphs"] = [g for r in res_lines for g in r.get("glyphs", [])]
    return out


def _line_iou(M: np.ndarray, text: str, fr: FontRef, size_hint: float | None, U: int, rng: float,
              glyphs: bool) -> dict:
    mh = _ink_height(M, 0.02)
    ref_size = float(size_hint) if size_hint else max(8.0, mh * 1.2)
    cov, _ = render_coverage(text, fr.abspath, ref_size * U, fr.index, margin=0)
    ch = _ink_height(cov >= 0.5, 0.02) / U
    center = ref_size * (mh / ch) if ch > 0 and mh > 0 else ref_size
    pad = 4
    cache: dict[float, dict] = {}

    def ev(size: float, phase_step: int) -> dict:
        key = round(size, 4)
        if key not in cache or cache[key]["_ps"] > phase_step:
            cache[key] = _eval_scale(M, text, fr, size, U, pad, phase_step=phase_step)
            cache[key]["_ps"] = phase_step
        return cache[key]

    windows = [center]
    if size_hint and abs(size_hint / center - 1) > rng:
        windows.append(float(size_hint))
    best_size, best_iou = center, -1.0
    for c in windows:
        for f in np.linspace(-rng, rng, 7):
            s = float(c * (1 + f))
            r = ev(s, U)            # coarse: integer-pixel translation only
            if r["iou"] > best_iou:
                best_iou, best_size = r["iou"], s
    best_iou = ev(best_size, max(1, U // 2))["iou"]
    step = best_size * 0.025
    lo_lim, hi_lim = min(windows) * (1 - rng), max(windows) * (1 + rng)
    while step >= best_size * 0.003:
        for s in (best_size - step, best_size + step):
            if lo_lim <= s <= hi_lim:
                r = ev(s, max(1, U // 2))
                if r["iou"] > best_iou:
                    best_iou, best_size = r["iou"], s
        step /= 2
    final = _eval_scale(M, text, fr, best_size, U, pad, glyphs=glyphs)
    base = float(size_hint) if size_hint else center
    ax, ay = final["anchor_xy"]
    out = {"iou": round(float(final["iou"]), 4), "scale": round(float(best_size / base), 4),
           "size_px": round(float(best_size), 3),
           "dx": ax, "dy": ay, "n_evals": len(cache) + 1}
    if glyphs:
        out["glyphs"] = final.get("glyphs", [])
    out["_inter"], out["_union"] = final["inter"], final["union"]
    return out


def font_iou(crop_rgb: np.ndarray, text: str, font_path: str | os.PathLike | FontRef, size_hint_px: float | None,
             fill_rgb: Any = None, outline_rgb: Any = None, *, face_index: int | None = None,
             masks: dict | None = None, glyphs: bool = False) -> dict:
    """IoU of the caption crop's fill mask vs ``text`` rendered in ``font_path`` (CONTRACT section 11).

    -> ``{iou, scale, dx, dy, size_px, ...}``; ``dx, dy`` = baseline-left anchor of the best
    placement in crop px; ``scale`` = best size / ``size_hint_px``.
    ``font_path`` may also be an exact font name or a :class:`FontRef`; ``.ttc`` faces are
    selected with ``face_index`` (or by name through :func:`font_ref`).
    """
    fr = font_ref(font_path, face_index) if not isinstance(font_path, FontRef) else font_path
    m = masks or extract_masks(crop_rgb, fill_rgb, outline_rgb)
    r = mask_iou(m["fill"], text, fr, size_hint_px, glyphs=glyphs)
    r["colors"] = {"fill": m["fill_rgb"], "outline": m["outline_rgb"], "estimated": m["estimated"]}
    return r


# ============================================================================= degradation
@dataclass
class Conditions:
    """How the reference pixels were produced (emulated for the ceiling)."""
    canvas: tuple[int, int] = (1080, 1920)          # editor canvas the captions were rendered at
    ref_resolution: tuple[int, int] = (1080, 1920)  # resolution of the downloaded reference video
    codec: str = "h264"                              # h264 | vp9 | av1
    crf: float | None = 23.0
    bitrate_kbps: float | None = None                # full-frame video bitrate (overrides crf)
    qp: float | None = None                          # constant QP (h264; measured caption-macroblock QP; overrides both)
    x264_preset: str = "medium"
    gop: int = 60
    frames_per_sample: int = 3                       # sample frame taken from the middle (P/B frame)
    fps: float = 30.0
    background: str = "video"                        # video (test clips, moving) | black | color:#RRGGBB
    scale_flags: str = "bicubic"
    renderer: str = "supersample4"                   # supersample4 (unhinted, fractional) | hinted1x
    assumed: bool = True                             # True = not from a real reference download
    source: str = "assumed"                          # where the numbers came from

    def label(self) -> str:
        if self.qp is not None:
            q = f"qp{self.qp:g}"
        else:
            q = f"crf{self.crf:g}" if self.bitrate_kbps is None else f"{self.bitrate_kbps:g}kbps"
        return f"{self.codec}_{q}_{self.ref_resolution[0]}x{self.ref_resolution[1]}"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["canvas"] = list(self.canvas)
        d["ref_resolution"] = list(self.ref_resolution)
        d["label"] = self.label()
        return d

    @staticmethod
    def from_dict(d: dict) -> "Conditions":
        d = {k: v for k, v in d.items() if k in Conditions.__dataclass_fields__}
        for k in ("canvas", "ref_resolution"):
            if k in d:
                d[k] = tuple(int(v) for v in d[k])
        return Conditions(**d)


_ENCODERS = {"h264": "libx264", "vp9": "libvpx-vp9", "av1": "libsvtav1"}


def _encoder_args(cond: Conditions, area_frac: float) -> list[str]:
    enc = _ENCODERS.get(cond.codec)
    if enc is None:
        raise ValueError(f"unsupported codec {cond.codec}")
    a = ["-c:v", enc, "-pix_fmt", "yuv420p", "-g", str(cond.gop)]
    if cond.codec == "h264":
        a += ["-preset", cond.x264_preset, "-bf", "2", "-threads", "2"]
    elif cond.codec == "vp9":
        a += ["-deadline", "good", "-cpu-used", "4", "-row-mt", "1", "-threads", "2"]
    else:
        a += ["-preset", "8"]
    if cond.qp is not None:
        if cond.codec != "h264":
            raise ValueError("constant-QP emulation is implemented for h264 only")
        # same QP for I/P/B and no adaptive quantisation: every caption macroblock gets exactly qp
        a += ["-qp", f"{int(round(cond.qp))}", "-x264-params", "ipratio=1.0:pbratio=1.0:aq-mode=0"]
    elif cond.bitrate_kbps:
        br = max(20.0, cond.bitrate_kbps * area_frac)
        a += ["-b:v", f"{br:.0f}k", "-maxrate", f"{br * 1.5:.0f}k", "-bufsize", f"{br * 2:.0f}k"]
    else:
        a += ["-crf", f"{cond.crf:g}"]
        if cond.codec == "vp9":
            a += ["-b:v", "0"]
    return a


def degrade(frames: Sequence[np.ndarray], cond: Conditions, keep_every: int = 1, keep_offset: int = 0) -> list[np.ndarray]:
    """Emulate the reference pipeline on canvas-resolution RGB frames.

    scale (canvas -> reference resolution, ``cond.scale_flags``) -> yuv420p encode with
    ``cond.codec`` at ``cond.crf`` or ``cond.bitrate_kbps`` (scaled to the frame area) -> decode
    -> RGB frames at reference scale.  Returns frames ``keep_offset::keep_every``.
    """
    if not frames:
        return []
    H, W = frames[0].shape[:2]
    sc = cond.ref_resolution[0] / cond.canvas[0]
    rw = max(2, int(round(W * sc / 2)) * 2)
    rh = max(2, int(round(H * sc / 2)) * 2)
    area_frac = (rw * rh) / float(cond.ref_resolution[0] * cond.ref_resolution[1])
    raw = b"".join(np.ascontiguousarray(f[..., :3], dtype=np.uint8).tobytes() for f in frames)
    with tempfile.TemporaryDirectory(prefix="sk_typo_") as td:
        enc = Path(td) / ("enc.mkv" if cond.codec != "h264" else "enc.mp4")
        vf = f"scale={rw}:{rh}:flags={cond.scale_flags}" if (rw, rh) != (W, H) else "null"
        run([FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
             "-s", f"{W}x{H}", "-r", f"{cond.fps:g}", "-i", "-", "-vf", vf, *_encoder_args(cond, area_frac), str(enc)],
            input_bytes=raw)
        out = run([FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-i", str(enc), "-f", "rawvideo",
                   "-pix_fmt", "rgb24", "-"]).stdout
    fb = rw * rh * 3
    n = len(out) // fb
    dec = [np.frombuffer(out[i * fb:(i + 1) * fb], np.uint8).reshape(rh, rw, 3) for i in range(n)]
    if n != len(frames):
        raise MediaError(f"decoded {n} frames, expected {len(frames)}")
    return dec[keep_offset::keep_every]


def _background_frames(cond: Conditions, n: int, width: int, height: int, seed: int) -> list[np.ndarray]:
    """Background strips: consecutive frames of the CC-BY test clips (``video``, moving), a solid
    colour (``color:#RRGGBB``), or black."""
    if cond.background == "video":
        vids = sorted(paths.absp("assets/test/generated/video").glob("*.mp4")) if \
            paths.absp("assets/test/generated/video").is_dir() else []
        if vids:
            rng = np.random.default_rng(seed)
            v = vids[int(rng.integers(len(vids)))]
            try:
                info = probe(v)
                start = float(rng.uniform(0, max(0.0, info.duration - n / cond.fps - 0.5)))
                raw = run([FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{start:.3f}", "-i", str(v),
                           "-frames:v", str(n), "-vf", f"scale={width}:-2,crop={width}:{height}:0:(ih-{height})/2",
                           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]).stdout
                fb = width * height * 3
                fr = [np.frombuffer(raw[i * fb:(i + 1) * fb], np.uint8).reshape(height, width, 3)
                      for i in range(len(raw) // fb)]
                if len(fr) == n:
                    return fr
            except MediaError:
                pass
    col = (0, 0, 0)
    if cond.background.startswith("color:"):
        col = parse_rgb(cond.background.split(":", 1)[1])
    out = []
    for _ in range(n):
        a = np.empty((height, width, 3), np.uint8)
        a[:] = col
        out.append(a)
    return out


# ============================================================================= synthetic reference samples
@dataclass
class Sample:
    crop: np.ndarray
    text: str
    size_px: float            # at reference resolution
    fill_rgb: tuple
    outline_rgb: tuple | None
    font: str                 # truth (synthetic)
    group: str                # string/size/style group id (repeats share it)
    style: str
    canvas_size_px: float


def style_spec(style: Any) -> tuple[str, tuple, tuple | None, float, float | None]:
    """(name, fill, outline|None, outline width / font size, outline width / ink height|None)
    from a STYLE_VARIANTS name or a dict ``{name?, fill, outline, outline_frac | outline_frac_ink}``
    (e.g. measured from captions.json, where the ink height is what is measurable)."""
    if isinstance(style, str):
        f, o, fr = STYLE_VARIANTS[style]
        return style, f, o, fr, None
    f = parse_rgb(style["fill"])
    o = parse_rgb(style.get("outline"))
    fr = float(style.get("outline_frac") or 0.0) if o is not None else 0.0
    fi = float(style["outline_frac_ink"]) if (o is not None and style.get("outline_frac_ink")) else None
    name = style.get("name") or f"fill{f}_outline{o}_{fr:g}"
    return name, f, o, fr, fi


@lru_cache(maxsize=256)
def ink_ratio(font_path: str, index: int = 0, text: str = "결국 참지 못한 남자") -> float:
    """Ink height (fill coverage >= 0.5) of a Korean line per 1 px of font size."""
    cov, _ = render_coverage(text, font_path, 400.0, index, margin=0)
    return _ink_height(cov >= 0.5, 0.02) / 400.0


def make_samples(font: FontRef, strings: Sequence[str], sizes: Sequence[float], cond: Conditions,
                 styles: Sequence[Any] = ("white_black_outline",), repeats: int = 2, seed: int = 7,
                 style_cycle: bool = False, size_mode: str = "em") -> list[Sample]:
    """Render captions in ``font`` on background strips at canvas resolution, degrade them like
    the reference, and cut crops at reference resolution (synthetic; truth = ``font``).

    ``style_cycle``: string i uses style i % len(styles) (instead of every style x string).
    ``size_mode="ink"``: ``sizes`` are target INK heights (canvas px) -- each font is rendered
    at the em size that gives that ink height, so fonts are compared at the text height that
    was actually measured on the reference."""
    r_ink = ink_ratio(str(font.abspath), font.index)
    if size_mode == "ink":
        sizes = [round(h / r_ink, 2) for h in sizes] if r_ink > 0 else list(sizes)
    rng = np.random.default_rng(seed)
    W = cond.canvas[0]
    specs = []
    sty = [style_spec(x) for x in styles]
    for si, s in enumerate(strings):
        for st in ([sty[si % len(sty)]] if style_cycle else sty):
            for size in sizes:
                for rep in range(repeats):
                    specs.append((st, s, float(size), rep))
    if not specs:
        return []
    maxsize = max(sizes)
    Hs = int(math.ceil(maxsize * 2.4 / 16.0)) * 16
    k = max(1, int(cond.frames_per_sample))
    frames, metas = [], []
    bgs = _background_frames(cond, len(specs) * k, W, Hs, seed)
    ss = 1 if cond.renderer == "hinted1x" else 4
    for j, (st, s, size, rep) in enumerate(specs):
        st, fill, outline, ofrac, ofrac_ink = st
        if outline is None:
            opx = 0.0
        elif ofrac_ink is not None:
            opx = round(size * r_ink * ofrac_ink, 2)
        else:
            opx = round(size * ofrac, 2)
        fnt = load_font(font.abspath, size, font.index)
        bx0, by0, bx1, by1 = fnt.getbbox(s, anchor="ls", stroke_width=opx)
        tw = bx1 - bx0
        if tw > W - 20:
            continue
        x = (W - tw) / 2 - bx0 + rng.uniform(-40, 40) + rng.uniform(0, 1)
        x = min(max(x, 10 - bx0), W - 10 - bx1)
        y = Hs / 2 - (by0 + by1) / 2 + rng.uniform(-6, 6) + rng.uniform(0, 1)
        box = None
        for f in range(k):
            img, box = draw_caption(bgs[j * k + f], s, font.abspath, size, (x, y), fill, outline, opx, font.index,
                                    supersample=ss)
            frames.append(img)
        metas.append((st, s, size, rep, box, fill, outline))
    mid = k // 2
    dec = degrade(frames, cond, keep_every=k, keep_offset=mid)
    sc = cond.ref_resolution[0] / cond.canvas[0]
    samples = []
    for (st, s, size, rep, box, fill, outline), img in zip(metas, dec):
        m = max(3.0, 0.15 * size * sc)
        x0 = max(0, int(math.floor(box[0] * sc - m)))
        y0 = max(0, int(math.floor(box[1] * sc - m)))
        x1 = min(img.shape[1], int(math.ceil(box[2] * sc + m)))
        y1 = min(img.shape[0], int(math.ceil(box[3] * sc + m)))
        samples.append(Sample(crop=img[y0:y1, x0:x1].copy(), text=s, size_px=size * sc, fill_rgb=fill,
                              outline_rgb=outline, font=font.name, group=f"{st}|{s}|{size:g}", style=st,
                              canvas_size_px=size))
    return samples


def _sample_iou(sm: Sample, cand: FontRef, color_mode: str, glyphs: bool = True, masks: dict | None = None) -> dict:
    if masks is None:
        masks = _sample_masks(sm, color_mode)
    r = mask_iou(masks["fill"], sm.text, cand, sm.size_px, glyphs=glyphs)
    return r


def _sample_masks(sm: Sample, color_mode: str) -> dict:
    if color_mode == "given":
        # without an outline the "outline" side of the colour segment is the local background
        o = sm.outline_rgb if sm.outline_rgb is not None else None
        return extract_masks(sm.crop, sm.fill_rgb, o)
    return extract_masks(sm.crop)


# ============================================================================= ceiling / discriminability
def _glyph_values(rows: Iterable[dict]) -> list[float]:
    return [g["iou"] for r in rows for g in (r.get("glyphs") or [])]


def ceiling(font: FontRef | str, cond: Conditions, strings: Sequence[str] = DEFAULT_STRINGS[:4],
            sizes: Sequence[float] = DEFAULT_SIZES, styles: Sequence[str] = ("white_black_outline",),
            repeats: int = 2, color_mode: str = "estimated", seed: int = 7,
            samples: list[Sample] | None = None, keep_rows: bool = True) -> dict:
    """IoU upper bound of this method for ``font`` under ``cond``.

    -> ``{n, p10, p50, p90, glyph: {n,p10,p50,p90}, noise: {...}, by_size: {...}, rows: [...]}``
    ``noise`` = spread (max - min) of the self IoU across repeats of the same string/size/style
    (different sub-pixel position, background and encode context) -- the repeatability of one
    IoU measurement; its p90 is the margin a winner must exceed.
    """
    fr = font_ref(font)
    sams = samples if samples is not None else make_samples(fr, strings, sizes, cond, styles, repeats, seed)
    rows = []
    for sm in sams:
        try:
            r = _sample_iou(sm, fr, color_mode)
            err = r.get("error")
        except ValueError as e:      # mask extraction impossible on this crop
            r, err = {}, str(e)
        rows.append({"group": sm.group, "text": sm.text, "size_px": round(sm.size_px, 2), "style": sm.style,
                     "iou": None if err else r["iou"], "scale": r.get("scale"), "glyphs": r.get("glyphs", []),
                     **({"error": err} if err else {})})
    groups: dict[str, list[float]] = {}
    for r in rows:
        if r["iou"] is not None:
            groups.setdefault(r["group"], []).append(r["iou"])
    spreads = [max(v) - min(v) for v in groups.values() if len(v) > 1]
    by_size: dict[str, list[float]] = {}
    for r in rows:
        by_size.setdefault(f"{r['size_px']:g}", []).append(r["iou"])
    n_failed = sum(1 for r in rows if r["iou"] is None)
    out = {"font": fr.name, "conditions": cond.to_dict(), "color_mode": color_mode,
           **pstats([r["iou"] for r in rows], 4),
           "n_failed": n_failed,   # crops where the method could not extract a mask (excluded, reported)
           "glyph": {**pstats(_glyph_values(rows), 4),
                     "min": round(min(_glyph_values(rows)), 4) if _glyph_values(rows) else None},
           "noise": pstats(spreads, 4),
           "by_size": {k: pstats(v, 4) for k, v in sorted(by_size.items(), key=lambda kv: float(kv[0]))}}
    if keep_rows:
        out["rows"] = [{k: v for k, v in r.items() if k != "glyphs"} for r in rows]
    return out


def discriminability(font: FontRef | str, others: Sequence[FontRef | str], cond: Conditions,
                     samples: list[Sample] | None = None, self_ceiling: dict | None = None,
                     color_mode: str = "estimated", **kw) -> dict:
    """Cross-font IoU: crops rendered in ``font`` scored against each of ``others`` (same
    degradation).  margin = self IoU - cross IoU per sample; ``separable`` when margin p10 >
    noise p90 (the near font would not be mistaken)."""
    fr = font_ref(font)
    sams = samples if samples is not None else make_samples(fr, kw.get("strings", DEFAULT_STRINGS[:4]),
                                                            kw.get("sizes", DEFAULT_SIZES), cond,
                                                            kw.get("styles", ("white_black_outline",)),
                                                            kw.get("repeats", 2), kw.get("seed", 7))
    masks = []
    for sm in sams:
        try:
            masks.append(_sample_masks(sm, color_mode))
        except ValueError:
            masks.append(None)
    if self_ceiling is None or not self_ceiling.get("rows"):
        self_ceiling = ceiling(fr, cond, samples=sams, color_mode=color_mode)
    self_iou = [r["iou"] for r in self_ceiling["rows"]]
    noise = (self_ceiling.get("noise") or {}).get("p90") or 0.0
    out = []
    for o in others:
        orf = font_ref(o)
        cross = [mask_iou(m["fill"], sm.text, orf, sm.size_px, glyphs=False)["iou"] if (m is not None and si is not None)
                 else None for sm, m, si in zip(sams, masks, self_iou)]
        margins = [a - b for a, b in zip(self_iou, cross) if a is not None and b is not None]
        mst = pstats(margins, 4)
        out.append({"font": fr.name, "other": orf.name, "cross_iou": pstats(cross, 4), "margin": mst,
                    "other_wins_share": round(float(np.mean([m <= 0 for m in margins])), 4) if margins else None,
                    "noise_p90": noise,
                    "separable": bool(mst["n"] and mst["p10"] is not None and mst["p10"] > noise)})
    return {"font": fr.name, "conditions": cond.to_dict(), "pairs": out}


def nearest_candidates(font: FontRef | str, candidates: Sequence[FontRef | str], k: int = 3,
                       probe_strings: Sequence[str] = ("아니 이게 무슨 일이야", "결국 참지 못한 남자"),
                       size_px: float = 72.0) -> list[tuple[str, float]]:
    """Rank other candidates by clean-render IoU against ``font`` (no degradation)."""
    fr = font_ref(font)
    scores = []
    masks = []
    for s in probe_strings:
        cov, _ = render_coverage(s, fr.abspath, size_px, fr.index, margin=int(size_px * 0.2))
        masks.append((s, cov >= 0.5))
    for c in candidates:
        cr = font_ref(c)
        if cr.name == fr.name:
            continue
        v = [mask_iou(m, s, cr, size_px, glyphs=False)["iou"] for s, m in masks]
        scores.append((cr.name, float(np.mean(v))))
    scores.sort(key=lambda t: -t[1])
    return scores[:k]


# ============================================================================= identification
def _verdict(iou: float, is_top: bool, margin: float, glyph_pass: bool | None, ceil: dict | None) -> tuple[str, list[str]]:
    reasons: list[str] = []
    if not ceil or not ceil.get("n") or ceil.get("p10") is None:
        return "unmeasured", ["이 조건의 IoU 천장(ceiling)이 측정되지 않음 → 판정 불가"]
    p10 = ceil["p10"]
    noise = (ceil.get("noise") or {}).get("p90") or 0.0
    if iou < p10 - noise:
        reasons.append(f"IoU {iou:.3f} < 천장 p10 {p10:.3f} - 잡음 {noise:.3f}")
        return "different", reasons
    ok_ceiling = iou >= p10
    ok_margin = is_top and margin > noise
    reasons.append(f"IoU {iou:.3f} {'>=' if ok_ceiling else '<'} 천장 p10 {p10:.3f}")
    reasons.append(f"차순위 대비 차이 {margin:+.3f} {'>' if ok_margin else '<='} 잡음 {noise:.3f}")
    if glyph_pass is not None:
        reasons.append(f"글자별 검사 {'통과' if glyph_pass else '실패'}")
    if ok_ceiling and ok_margin and glyph_pass:
        return "identical", reasons
    return "similar", reasons


def score_crops(items: Sequence[dict], candidates: Sequence[FontRef | str],
                color_mode: str = "given") -> tuple[dict[str, list[dict]], list[str], list[dict]]:
    """IoU (+ per-glyph IoU) of every crop against every candidate
    -> ({font: [row per crop]}, missing candidate names, crops that could not be scored)."""
    refs, missing = [], []
    for c in candidates:
        try:
            fr = font_ref(c)
        except FileNotFoundError:
            missing.append(str(c))
            continue
        if fr.name not in {r.name for r in refs}:
            refs.append(fr)
    masks, failed = [], []
    for it in items:
        try:
            masks.append(extract_masks(it["crop"], it.get("fill_rgb") if color_mode == "given" else None,
                                       it.get("outline_rgb") if color_mode == "given" else None))
        except ValueError as e:     # no separable text colours: this crop cannot be scored
            masks.append(None)
            failed.append({"id": it.get("id"), "reason": str(e)})
    per: dict[str, list[dict]] = {}
    for fr in refs:
        rows = []
        for it, m in zip(items, masks):
            if m is None:
                continue
            r = mask_iou(m["fill"], it["text"], fr, it.get("size_hint_px"), glyphs=True)
            if r.get("error"):
                continue
            rows.append({"id": it.get("id"), "iou": r["iou"], "scale": r.get("scale"), "glyphs": r.get("glyphs", [])})
        per[fr.name] = rows
    return per, missing, failed


def glyph_floor(gstat: dict) -> float | None:
    """Outlier fence for one glyph: p10 - 2 x (p50 - p10) of the same-font per-glyph IoU.

    A glyph of the true font falls below it only as an outlier; a glyph drawn from another
    design (or a mis-OCR'd character) typically falls far below.  (The raw minimum of a small
    ceiling sample is too noisy to use as a hard limit.)"""
    p10, p50 = gstat.get("p10"), gstat.get("p50")
    if p10 is None or p50 is None:
        return None
    return round(p10 - 2.0 * max(0.0, p50 - p10), 4)


def rank_candidates(per: dict[str, list[dict]], ceilings: dict[str, dict]) -> dict:
    """Verdict per candidate from per-crop scores (see module doc).  Aggregate IoU = median over
    crops; margin = aggregate - best other aggregate; ceilings: {font: ceiling} (``"*"`` fallback)."""
    per = {n: rows for n, rows in per.items() if rows}
    agg = {n: float(np.median([r["iou"] for r in rows])) for n, rows in per.items()}
    ranked = sorted(agg, key=lambda n: -agg[n])
    out_rows = []
    for rank, n in enumerate(ranked, 1):
        others = [agg[o] for o in ranked if o != n]
        margin = agg[n] - (max(others) if others else 0.0)
        ceil = ceilings.get(n) or ceilings.get("*")
        gvals = _glyph_values(per[n])
        gstat = (ceil or {}).get("glyph") or {}
        gp10, gp50, gmin = gstat.get("p10"), gstat.get("p50"), gstat.get("min")
        gfloor = glyph_floor(gstat)
        gshare = float(np.mean([g >= gp10 for g in gvals])) if (gvals and gp10 is not None) else None
        gpass = None
        weak: list[dict] = []
        if gshare is not None:
            weak = [{"crop": r.get("id"), "ch": g["ch"], "iou": g["iou"]} for r in per[n] for g in r.get("glyphs") or []
                    if gfloor is not None and g["iou"] < gfloor]
            gpass = gshare >= GLYPH_PASS_SHARE and not weak
        verdict, reasons = _verdict(agg[n], rank == 1, margin, gpass, ceil)
        if weak:
            reasons.append(f"글자별 하한({gfloor:.2f})보다 나쁜 글자: "
                           + ", ".join(f"{w['ch']}({w['iou']:.2f})" for w in weak[:6])
                           + " — 다른 글꼴이거나 OCR 문구 오류일 수 있음")
        out_rows.append({"rank": rank, "font": n, "iou": round(agg[n], 4), "margin": round(margin, 4),
                         "iou_stats": pstats([r["iou"] for r in per[n]], 4),
                         "per_crop": [{k: v for k, v in r.items() if k != "glyphs"} for r in per[n]],
                         "glyph_share_ge_p10": None if gshare is None else round(gshare, 3),
                         "glyph_below_floor": weak, "glyph_pass": gpass, "verdict": verdict, "verdict_ko": VERDICT_KO[verdict],
                         "reasons": reasons,
                         "ceiling_used": None if not ceil else {k: ceil.get(k) for k in ("n", "p10", "p50", "p90")} |
                         {"noise_p90": (ceil.get("noise") or {}).get("p90"), "glyph_p10": gp10, "glyph_p50": gp50,
                          "glyph_min": gmin, "glyph_floor": gfloor,
                          "font": ceil.get("font"), "conditions": (ceil.get("conditions") or {}).get("label")}})
    top = out_rows[0] if out_rows else None
    if top and top["verdict"] == "identical":
        summary = f"동일 판정: {top['font']} (IoU {top['iou']:.3f}, 천장 p10 {top['ceiling_used']['p10']:.3f}, " \
                  f"차순위 대비 +{top['margin']:.3f} > 잡음 {top['ceiling_used']['noise_p90']:.3f})"
    elif top and top["verdict"] == "similar":
        summary = f"동일 확정 불가: 가장 가까운 후보 {top['font']} 는 '유사' (동일 폰트라고 쓰지 않음)"
    elif top and top["verdict"] == "unmeasured":
        summary = "천장 미측정 → 판정 못 잼"
    elif top:
        summary = "모든 후보가 '다름' — 레퍼런스 글꼴이 후보 목록에 없을 가능성(확보 못 한 글꼴 목록 확인)"
    else:
        summary = "평가할 후보/crop 없음 → 판정 못 잼"
    n_crops = max((len(r) for r in per.values()), default=0)
    return {"n_crops": n_crops, "ranked": out_rows, "summary": summary,
            "top": top["font"] if top else None, "top_verdict": top["verdict"] if top else None}


def identify_many(items: Sequence[dict], candidates: Sequence[FontRef | str], ceilings: dict[str, dict],
                  color_mode: str = "given") -> dict:
    """Rank candidates over one or more crops.

    items: ``[{crop, text, size_hint_px, fill_rgb?, outline_rgb?, id?}]``.
    ceilings: ``{font name: ceiling dict}`` measured under the reference's conditions
    (``"*"`` = used for fonts without their own entry).
    """
    per, missing, failed = score_crops(items, candidates, color_mode)
    res = rank_candidates(per, ceilings)
    res.update({"n_crops": len(items), "color_mode": color_mode, "missing_candidates": missing,
                "failed_crops": failed})
    return res


def identify(crop: np.ndarray | Sequence[dict], text: str | None, candidates: Sequence[FontRef | str],
             conditions: Conditions | dict | None = None, *, size_hint_px: float | None = None,
             fill_rgb: Any = None, outline_rgb: Any = None, ceilings: dict[str, dict] | None = None,
             ceiling_kw: dict | None = None) -> dict:
    """Rank ``candidates`` for one crop (or a list of item dicts, see :func:`identify_many`).

    ``ceilings`` measured beforehand are reused; otherwise each candidate's ceiling is measured
    now under ``conditions`` (expensive: one synthetic experiment per candidate).
    """
    items = list(crop) if (isinstance(crop, (list, tuple)) and crop and isinstance(crop[0], dict)) else \
        [{"crop": crop, "text": text, "size_hint_px": size_hint_px, "fill_rgb": fill_rgb, "outline_rgb": outline_rgb}]
    color_mode = "given" if all(it.get("fill_rgb") is not None for it in items) else "estimated"
    if ceilings is None:
        if conditions is None:
            raise ValueError("either ceilings or conditions are required (no ceiling -> no verdict)")
        cond = conditions if isinstance(conditions, Conditions) else Conditions.from_dict(conditions)
        ceilings = {}
        for c in candidates:
            try:
                fr = font_ref(c)
            except FileNotFoundError:
                continue
            ceilings[fr.name] = ceiling(fr, cond, color_mode=color_mode, **(ceiling_kw or {}))
    res = identify_many(items, candidates, ceilings, color_mode=color_mode)
    if conditions is not None:
        res["conditions"] = (conditions if isinstance(conditions, Conditions) else Conditions.from_dict(conditions)).to_dict()
    return res


# ============================================================================= experiments (ceiling report)
def resolve_candidates(names: Iterable[str]) -> tuple[list[FontRef], list[str]]:
    refs, missing, seen = [], [], set()
    for n in names:
        try:
            fr = font_ref(n)
        except FileNotFoundError:
            missing.append(str(n))
            continue
        if fr.name in seen:
            continue
        seen.add(fr.name)
        refs.append(fr)
    return refs, missing


def _font_job(font_name: str, cond_dict: dict, strings: list[str], sizes: list[float], styles: list,
              repeats: int, others: list[str], color_mode: str, seed: int, size_mode: str = "em") -> dict:
    """One font under one condition: its ceiling + cross IoU vs its nearest candidates."""
    fr = font_ref(font_name)
    cond = Conditions.from_dict(cond_dict)
    sams = make_samples(fr, strings, sizes, cond, styles, repeats, seed, style_cycle=True, size_mode=size_mode)
    ceil = ceiling(fr, cond, samples=sams, color_mode=color_mode)
    pairs = []
    if others:
        pairs = discriminability(fr, others, cond, samples=sams, self_ceiling=ceil, color_mode=color_mode)["pairs"]
    return {"font": fr.name, "ceiling": ceil, "pairs": pairs}


def _nearest_job(font_name: str, others: list[str], k: int) -> tuple[str, list]:
    return font_name, nearest_candidates(font_name, others, k=k)


def _worker_init() -> None:
    try:
        import cv2

        cv2.setNumThreads(1)     # one core per worker process (the machine is shared)
    except Exception:  # noqa: BLE001
        pass


def _pmap(fn, arglist: list[tuple], jobs: int, progress=None) -> list:
    out = []
    if jobs <= 1:
        for i, a in enumerate(arglist):
            out.append(fn(*a))
            if progress:
                progress(i + 1, len(arglist))
        return out
    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(max_workers=jobs, initializer=_worker_init) as ex:
        futs = [ex.submit(fn, *a) for a in arglist]
        for i, f in enumerate(futs):
            out.append(f.result())
            if progress:
                progress(i + 1, len(arglist))
    return out


def run_ceiling_experiment(fonts: Sequence[str], conditions: Sequence[Conditions],
                           strings: Sequence[str] = DEFAULT_STRINGS[:3], sizes: Sequence[float] = DEFAULT_SIZES,
                           styles: Sequence[Any] = ("white_black_outline", "yellow_black_outline"),
                           repeats: int = 2, k_nearest: int = 3, jobs: int = 1, color_mode: str = "estimated",
                           seed: int = 7, progress=None) -> dict:
    """Ceiling of every font and its discriminability vs its ``k_nearest`` candidates, for each condition."""
    refs, missing = resolve_candidates(fonts)
    names = [r.name for r in refs]
    nearest = {}
    if k_nearest > 0 and len(names) > 1:
        res = _pmap(_nearest_job, [(n, names, k_nearest) for n in names], jobs)
        nearest = {n: v for n, v in res}
    out = {"fonts": [{"name": r.name, "file": _store_font_path(r)} for r in refs], "missing": missing,
           "nearest_clean": {n: [{"font": o, "iou_clean": round(v, 4)} for o, v in lst] for n, lst in nearest.items()},
           "ceilings": {}, "discriminability": {}, "conditions": {},
           "sample_design": {"strings": list(strings), "sizes_px_canvas": list(sizes),
                             "styles": [style_spec(s)[0] for s in styles], "style_cycle": True,
                             "repeats": repeats, "color_mode": color_mode, "seed": seed,
                             "n_per_font": len(strings) * len(sizes) * repeats}}
    for cond in conditions:
        lab = cond.label()
        args = [(n, cond.to_dict(), list(strings), list(sizes), list(styles), repeats,
                 [o for o, _ in nearest.get(n, [])], color_mode, seed) for n in names]
        res = _pmap(_font_job, args, jobs, progress)
        out["conditions"][lab] = cond.to_dict()
        out["ceilings"][lab] = {r["font"]: {k: v for k, v in r["ceiling"].items() if k not in ("rows", "conditions")}
                                for r in res}
        out["discriminability"][lab] = [p for r in res for p in r["pairs"]]
    return out


def _store_font_path(fr: FontRef) -> str:
    try:
        return paths.relp(fr.abspath)
    except (ValueError, RuntimeError):
        return f"<system>/{fr.abspath.name}"


def summarize_experiment(exp: dict) -> list[str]:
    lines = []
    for lab, ceils in exp["ceilings"].items():
        p10s = [c["p10"] for c in ceils.values() if c.get("p10") is not None]
        p50s = [c["p50"] for c in ceils.values() if c.get("p50") is not None]
        noise = [c["noise"]["p90"] for c in ceils.values() if (c.get("noise") or {}).get("p90") is not None]
        pairs = exp["discriminability"].get(lab, [])
        sep = sum(1 for p in pairs if p["separable"])
        lines.append(f"[{lab}] 같은 글꼴 IoU 천장: 글꼴별 p10 {min(p10s):.3f}~{max(p10s):.3f}, p50 {min(p50s):.3f}~"
                     f"{max(p50s):.3f} (글꼴 {len(ceils)}종)" if p10s else f"[{lab}] 천장 계산 실패")
        if noise:
            lines.append(f"[{lab}] 측정 잡음(같은 문구·크기 반복의 IoU 차이) p90: {min(noise):.3f}~{max(noise):.3f}")
        if pairs:
            lines.append(f"[{lab}] 가까운 글꼴 쌍 {len(pairs)}개 중 구분 가능(차이 p10 > 잡음 p90) {sep}개")
            hard = sorted(pairs, key=lambda p: (p["margin"]["p10"] if p["margin"]["p10"] is not None else 9))[:5]
            for p in hard:
                lines.append(f"    {p['font']} vs {p['other']}: 교차 IoU p50 {p['cross_iou']['p50']}, 차이 p10 "
                             f"{p['margin']['p10']}, 잡음 p90 {p['noise_p90']}, "
                             f"{'구분 가능' if p['separable'] else '구분 불가 → 동일 판정 금지(유사로만 보고)'}")
    return lines


# ============================================================================= preset report
REPORT_SCHEMA = "shortkit.fonts_report/1"
STATUS_CEILING_ONLY = "ceiling_only: reference crops unmeasured (못 잼)"


def _report_path(preset_name: str) -> Path:
    return paths.preset_dir(preset_name) / "fonts_report.json"


def assumptions_for(conds: Sequence[Conditions], exp: dict) -> list[dict]:
    """Which inputs of the ceiling experiment are assumptions to be replaced by measured values."""
    c0 = conds[0]
    rc = sorted({f"crf {c.crf:g}" if c.bitrate_kbps is None else f"{c.bitrate_kbps:g} kbps" for c in conds})
    return [
        {"input": "ref_resolution", "value": list(c0.ref_resolution), "status": "assumed" if c0.assumed else "measured",
         "replace_with": "reference/downloads.jsonl 의 실제 다운로드 해상도(ffprobe)"},
        {"input": "codec", "value": c0.codec, "status": "assumed" if c0.assumed else "measured",
         "replace_with": "실제 다운로드의 비디오 코덱(avc1/vp9/av01, ffprobe)"},
        {"input": "rate_control", "value": rc, "status": "assumed" if c0.assumed else "measured",
         "replace_with": "실제 다운로드의 비디오 비트레이트 → bitrate 모드로 재계산"},
        {"input": "canvas", "value": list(c0.canvas), "status": "preset(provisional)",
         "replace_with": "측정된 canvas 해상도(레퍼런스 편집 해상도는 직접 알 수 없음: 다운로드 해상도와 같다고 가정)"},
        {"input": "caption_sizes_px", "value": exp["sample_design"]["sizes_px_canvas"], "resolution": list(c0.canvas),
         "status": "assumed", "replace_with": "analysis/<id>/captions.json 역할별 글자 크기 분포"},
        {"input": "caption_style", "value": exp["sample_design"]["styles"], "status": "assumed",
         "replace_with": "captions.json style 의 채움색·외곽선색·외곽선 두께"},
        {"input": "renderer", "value": c0.renderer, "status": "assumed",
         "replace_with": "알 수 없음(레퍼런스 편집 프로그램) — hinted1x 로도 계산해 민감도 확인 가능"},
        {"input": "background", "value": c0.background, "status": "assumed",
         "replace_with": "레퍼런스 자막 뒤 배경(영상/단색) 측정값"},
        {"input": "strings", "value": exp["sample_design"]["strings"], "status": "synthetic",
         "replace_with": "그대로 사용 가능(레퍼런스 문구가 아닌 합성 문구)"},
    ]


def write_ceiling_report(preset, exp: dict, conds: Sequence[Conditions], command: str) -> Path:
    """Write/merge presets/<name>/fonts_report.json (keeps an existing identification section)."""
    from ..config import impact_of

    path = _report_path(preset.name)
    old = read_json(path, {}) or {}
    ident = old.get("identification") or _unmeasured_identification(preset, _no_crops_blocker(preset.name))
    assumed = any(c.assumed for c in conds)
    rep = {
        "schema": REPORT_SCHEMA, "preset_id": preset.preset_id, "status": None,
        "generated_at": now_iso(), "command": command,
        "conditions_assumed": assumed,
        "summary_ko": ([("가정 조건(실제 레퍼런스 다운로드 아님)으로 계산한 IoU 천장입니다. 레퍼런스 자막 crop 은 못 잼 → "
                         "글꼴 판정은 못 잼.") if assumed else "실제 레퍼런스 조건으로 계산한 IoU 천장입니다."]
                       + summarize_experiment(exp)),
        "method": {
            "mask": "fill-only (외곽선 제외), 색 투영(외곽선→채움 선분, t>=0.5) + 테두리 접촉 성분 제거 + 외곽선 둘러싸임 검사",
            "render": f"후보 글꼴을 {UPSAMPLE}배 해상도로 렌더 후 상자 축소(비힌팅·분수 위치), 50% 커버리지 임계",
            "alignment": f"크기 ±{SCALE_RANGE:.0%} (잉크 높이 맞춤 중심, 5% 격자 → 절반씩 0.3%까지), 이동 1/{UPSAMPLE}px 격자 상호상관",
            "ceiling": "같은 글꼴로 합성 자막 렌더 → 레퍼런스처럼 축소·인코딩·디코딩 → 같은 마스크 추출 → 같은 글꼴 깨끗한 렌더와 IoU",
            "noise": "같은 문구·크기·스타일 반복(부분 픽셀 위치·배경·인코딩 문맥만 다름) IoU 차이(max-min)의 분포",
            "verdict": {"identical": "IoU >= 그 글꼴 천장 p10 AND 차순위 대비 차이 > 잡음 p90 AND 글자별 검사 통과"
                                     f"(글자 {GLYPH_PASS_SHARE:.0%} 이상이 글자별 천장 p10 이상, 그리고 글자별 하한 "
                                     "p10-2x(p50-p10) 미만인 글자 없음)",
                        "similar": "제외는 안 되지만 동일 확정 불가 — 프리셋 값으로 쓰지 않음(못 잼 유지)",
                        "different": "IoU < 천장 p10 - 잡음 p90"},
        },
        "assumptions": assumptions_for(conds, exp),
        "candidates": {"evaluated": exp["fonts"], "missing": exp["missing"],
                       "not_acquired": _not_acquired()},
        "sample_design": exp["sample_design"],
        "conditions": exp["conditions"],
        "ceilings": exp["ceilings"],
        "nearest_clean": exp["nearest_clean"],
        "discriminability": exp["discriminability"],
        "identification": ident,
        "impact_if_unmeasured": impact_of("text.roles.title.font_name"),
    }
    rep["status"] = _report_status(rep)
    write_json(path, rep)
    return path


def _not_acquired() -> list[str]:
    from ..fonts import not_acquired_names

    return not_acquired_names()


def _no_crops_blocker(preset_name: str) -> str:
    base = "레퍼런스 자막 crop 없음 (analysis/<id>/captions.json + 레퍼런스 영상 파일 필요)"
    try:
        from .common import snapshot_blocker

        return f"{base} — {snapshot_blocker(preset_name)}"
    except Exception:  # noqa: BLE001 - the explanation is optional, the status is not
        return base


def _unmeasured_identification(preset, blocker: str) -> dict:
    from ..config import impact_of

    roles = {}
    for role in preset.section("text.roles"):
        name = preset.get(f"text.roles.{role}.font_name")
        roles[role] = {"status": "unmeasured", "label_ko": "못 잼", "current_preset_font": name,
                       "current_value_origin": preset.origin(f"text.roles.{role}.font_name"),
                       "candidate_ranking": None, "verdict": None}
    return {"status": "unmeasured", "label_ko": "못 잼", "blocker": blocker,
            "impact": impact_of("text.roles.title.font_name"),
            "resolution": "레퍼런스 영상 다운로드 → captions.json 생성 → `shortkit ref fonts` (실제 해상도·비트레이트로 천장 재계산 포함)",
            "roles": roles}


# ============================================================================= reference crops (ref fonts)
def _reference_video(preset_dir: Path, video_id: str) -> Path | None:
    for row in read_jsonl(preset_dir / "reference" / "downloads.jsonl"):
        if row.get("video_id") == video_id and row.get("path"):
            p = paths.absp(row["path"])
            if p.is_file():
                return p
    vdir = preset_dir / "reference" / "videos"
    if vdir.is_dir():
        for p in sorted(vdir.glob(f"{video_id}.*")):
            if p.suffix.lower() in (".mp4", ".webm", ".mkv", ".mov"):
                return p
    return None


def _style_colors(style: dict) -> dict:
    """Mask colours from a captions.json style (shortkit.reference.textboxes vocabulary).

    fill = ``color``; the colour on the other side of the fill edge = ``outline_color`` when
    ``outline_visibility == visible``, else the measured local ``bg_color`` (no visible outline);
    missing values stay None and are estimated from the crop."""
    def rgb(v):
        try:
            return parse_rgb(v) if v is not None else None
        except ValueError:
            return None

    vis = style.get("outline_visibility")
    fill = rgb(style.get("fill_rgb") or style.get("color") or style.get("fill"))
    outline_col = rgb(style.get("outline_rgb") or style.get("outline_color"))
    opx = style.get("outline_px")
    visible = (vis == "visible") or (vis is None and outline_col is not None and (opx is None or float(opx) > 0))
    edge = outline_col if visible else rgb(style.get("bg_color"))
    size = style.get("size_px")
    return {"fill": fill, "edge": edge, "outline": outline_col if visible else None,
            "outline_px": float(opx) if (visible and opx is not None) else None,
            "size_px": float(size) if size is not None else None,
            "ink_h": float(style["ink_h"]) if style.get("ink_h") else None,
            "bg": rgb(style.get("bg_color"))}


def _video_formats(preset) -> dict[str, str]:
    """video_id -> format_id from formats.yaml (``assignments`` or ``table[].videos``)."""
    from ..util.jsonio import read_yaml

    out: dict[str, str] = {}
    try:
        fy = read_yaml(paths.absp(preset.get("structure.formats_file")), {}) or {}
    except Exception:  # noqa: BLE001 - no formats file = no per-format split
        return out
    for vid, fmt in (fy.get("assignments") or {}).items():
        out[str(vid)] = str(fmt)
    for row in fy.get("table") or []:
        fid = row.get("format_id") or row.get("id")
        for vid in row.get("videos") or []:
            out.setdefault(str(vid), str(fid))
    return out


def collect_reference_crops(preset_name: str, roles: Sequence[str] | None = None, max_per_role: int = 12,
                            min_ocr_conf: float = 60.0) -> dict:
    """Single-line caption crops from analysis/<id>/captions.json + the downloaded reference videos.

    Uses each item's ``lines[]`` (text + bbox per line) when present, else the item box; the frame
    is read at ``t_rep`` (else the middle of start..end).  Lines whose OCR confidence is below
    ``min_ocr_conf`` are skipped (a wrong text would fail the per-glyph check for every font).
    -> {"items": {role: [item...]}, "videos": {video_id: probe summary}, "skipped": [...]}"""
    from ..util.media import read_frames

    pdir = paths.preset_dir(preset_name)
    items: dict[str, list[dict]] = {}
    videos: dict[str, dict] = {}
    video_paths: dict[str, Path] = {}       # runtime only (never stored)
    skipped: list[dict] = []
    for cj in sorted((pdir / "analysis").glob("*/captions.json")):
        cap = read_json(cj, {}) or {}
        vid = str(cap.get("video_id") or cj.parent.name)
        res = cap.get("resolution")
        video = _reference_video(pdir, vid)
        if video is None:
            skipped.append({"video_id": vid, "reason": "레퍼런스 영상 파일 없음"})
            continue
        info = probe(video)
        vstream = next((s for s in info.raw.get("streams", []) if s.get("codec_type") == "video"), {})
        vbr = vstream.get("bit_rate") or info.bit_rate
        videos[vid] = {"resolution": [info.width, info.height], "codec": vstream.get("codec_name"),
                       "bitrate_kbps": round(int(vbr) / 1000.0, 1) if vbr else None, "fps": info.fps,
                       "file": _safe_rel(video)}
        video_paths[vid] = video
        sx = sy = 1.0
        if res and info.width and info.height:
            sx, sy = info.width / float(res[0]), info.height / float(res[1])
        for k, it in enumerate(cap.get("items") or []):
            role = it.get("role")
            if not role or (roles and role not in roles):
                continue
            st = _style_colors(it.get("style") or {})
            t = it.get("t_rep")
            if t is None:
                t = (float(it.get("start", 0)) + float(it.get("end", it.get("start", 0)))) / 2.0
            lines = it.get("lines") or [{"text": it.get("text"), "bbox": it.get("bbox"), "ocr_conf": it.get("ocr_conf")}]
            frame = None
            for li, ln in enumerate(lines):
                if len(items.get(role, [])) >= max_per_role:
                    break
                text = (ln.get("text") or "").strip()
                bbox = ln.get("bbox")
                if not text or not bbox:
                    skipped.append({"video_id": vid, "item": k, "line": li, "reason": "text/bbox 없음"})
                    continue
                conf = ln.get("ocr_conf")
                if conf is not None and float(conf) < min_ocr_conf:
                    skipped.append({"video_id": vid, "item": k, "line": li, "reason": f"OCR 신뢰도 낮음({conf})"})
                    continue
                if frame is None:
                    try:
                        frame = read_frames(video, [float(t)])[0]
                    except Exception as e:  # noqa: BLE001 - report every failure
                        skipped.append({"video_id": vid, "item": k, "reason": f"프레임 읽기 실패: {e}"})
                        break
                x, y, w, h = [float(v) for v in bbox]
                x, y, w, h = x * sx, y * sy, w * sx, h * sy
                m = max(4.0, 0.15 * h)
                x0, y0 = max(0, int(x - m)), max(0, int(y - m))
                x1 = min(frame.shape[1], int(math.ceil(x + w + m)))
                y1 = min(frame.shape[0], int(math.ceil(y + h + m)))
                size = st["size_px"] * sy if st["size_px"] else None
                items.setdefault(role, []).append({
                    "id": f"{vid}#{k}.{li}", "video_id": vid, "t": round(float(t), 3), "crop": frame[y0:y1, x0:x1].copy(),
                    "start": float(it.get("start", t)), "end": float(it.get("end", t)),
                    "text": text, "size_hint_px": size, "fill_rgb": st["fill"], "outline_rgb": st["edge"],
                    "outline_color": st["outline"], "outline_px": st["outline_px"] * sy if st["outline_px"] else None,
                    "ink_h": (ln.get("ink_h") or st["ink_h"] or 0) * sy or None, "bg_rgb": st["bg"],
                    "bbox": [x0, y0, x1 - x0, y1 - y0], "resolution": [info.width, info.height]})
    return {"items": items, "videos": videos, "video_paths": video_paths, "skipped": skipped}


def _safe_rel(p: Path) -> str:
    try:
        return paths.relp(p)
    except (ValueError, RuntimeError):
        return Path(p).name


def _parse_qp_tables(stderr: str) -> list[dict]:
    """Per-frame macroblock tables from ``ffmpeg -debug qp+mb_type`` (H.264 decoder) stderr.

    Each macroblock prints as ``%2d`` QP + a type char (+ partition/interlace chars); type
    ``S``/``d``/``g`` = skipped (no residual coded in this frame)."""
    import re

    frames: list[dict] = []
    cur = None
    row_re = re.compile(r"^\[h264 @ [^\]]+\] (.*)$")
    cell_re = re.compile(r"(\d{1,2})([^\d\s])")
    for line in stderr.splitlines():
        if "New frame, type:" in line:
            cur = {"type": line.rsplit(":", 1)[1].strip(), "rows": []}
            frames.append(cur)
            continue
        if cur is None:
            continue
        m = row_re.match(line)
        if not m:
            continue
        body = m.group(1)
        if not body.strip() or not body.lstrip()[:1].isdigit():
            continue
        cells = cell_re.findall(body)
        if not cells or len(cells) * 3 < len(body.strip()) / 3:
            continue
        cur["rows"].append([(int(q), t) for q, t in cells])
    return [f for f in frames if f["rows"]]


def measure_caption_qp(video: str | os.PathLike, spans: Sequence[tuple[float, float, Sequence[float]]],
                       fps: float | None = None) -> dict | None:
    """Effective H.264 quantiser of the caption pixels, from the decoder's macroblock tables.

    spans: (t0, t1, bbox [x, y, w, h] in video px) of each caption (its own start..end).
    The video is decoded from the start (``ffmpeg -debug qp+mb_type``, no seeking, so table i
    ~ frame i).  For every macroblock we keep the QP it was LAST CODED with in a reference
    (I/P) frame -- a skipped macroblock is a copy of that earlier coding, so its nominal QP is
    meaningless.  A span's effective QP = median over its caption macroblocks of that state at
    the end of the span.  (A B-frame sampled mid-span may be coded at a different QP; ignored.)
    Returns None for non-H.264 video (the QP table is an H.264 decoder feature) or when no
    caption macroblock was ever coded."""
    info = probe(video)
    if info.vcodec != "h264":
        return None
    fps = fps or info.fps or 30.0
    t_end = max(float(t1) for _, t1, _ in spans) + 0.5
    proc = run([FFMPEG, "-hide_banner", "-nostdin", "-threads", "1", "-debug", "qp+mb_type", "-i", str(video),
                "-t", f"{t_end:.3f}", "-an", "-f", "null", "-"], check=False)
    frames = _parse_qp_tables((proc.stderr or b"").decode("utf-8", "replace"))
    if not frames:
        return None
    ends = {}
    for k, (t0, t1, bbox) in enumerate(spans):
        ends.setdefault(min(len(frames) - 1, max(0, int(math.ceil(float(t1) * fps)) - 1)), []).append(k)
    state: dict[tuple[int, int], int] = {}
    per_span: list[dict | None] = [None] * len(spans)
    for idx, f in enumerate(frames):
        if f["type"] in ("I", "P", "SP", "SI"):
            for r, row in enumerate(f["rows"]):
                for c, (qp, t) in enumerate(row):
                    if t not in ("S", "d", "g"):
                        state[(r, c)] = qp
        for k in ends.get(idx, []):
            x, y, w, h = [float(v) for v in spans[k][2]]
            c0, c1 = int(x // 16), int(math.ceil((x + w) / 16))
            r0, r1 = int(y // 16), int(math.ceil((y + h) / 16))
            q = [state[(r, c)] for r in range(r0, r1) for c in range(c0, c1) if (r, c) in state]
            if q:
                per_span[k] = {"t0": float(spans[k][0]), "t1": float(spans[k][1]), "n_mb": len(q),
                               "qp_median": float(np.median(q))}
    vals = [p["qp_median"] for p in per_span if p]
    if not vals:
        return None
    return {"method": "ffmpeg -debug qp+mb_type; last coded QP of caption macroblocks in reference (I/P) frames",
            "qp": pstats(vals, 2), "spans": per_span}


def conditions_from_videos(videos: dict, canvas: tuple[int, int]) -> Conditions | None:
    """Median real conditions of the downloaded reference videos (resolution/codec/bitrate)."""
    if not videos:
        return None
    from collections import Counter

    res = Counter(tuple(v["resolution"]) for v in videos.values() if v.get("resolution")).most_common(1)
    codecs = Counter(v.get("codec") for v in videos.values() if v.get("codec")).most_common(1)
    brs = [v["bitrate_kbps"] for v in videos.values() if v.get("bitrate_kbps")]
    codec = {"h264": "h264", "vp9": "vp9", "av1": "av1"}.get(codecs[0][0] if codecs else "", "h264")
    return Conditions(canvas=canvas, ref_resolution=res[0][0] if res else canvas, codec=codec,
                      crf=None if brs else 23.0, bitrate_kbps=float(np.median(brs)) if brs else None,
                      assumed=not brs, source=f"ffprobe of {len(videos)} reference downloads" +
                      ("" if brs else " (bitrate unknown -> CRF 23 ASSUMED)"))


def _role_style(its: list[dict]) -> tuple[Any, str, str]:
    """(style for the ceiling samples, color_mode, background) from measured caption styles."""
    fills = [i["fill_rgb"] for i in its if i["fill_rgb"] is not None]
    bgs = [i["bg_rgb"] for i in its if i.get("bg_rgb") is not None]
    background = "video"
    if bgs and len(bgs) == len(its) and max(np.linalg.norm(np.array(b, float) - np.array(bgs[0], float)) for b in bgs) < 30:
        background = "color:#%02X%02X%02X" % tuple(bgs[0])
    if len(fills) != len(its):
        return "white_black_outline", "estimated", background
    outl = its[0].get("outline_color")
    inks = [i["ink_h"] for i in its if i.get("ink_h")]
    opx = [i["outline_px"] for i in its if i["outline_px"]]
    if outl is not None and opx and inks:
        return ({"name": "measured", "fill": fills[0], "outline": outl,
                 "outline_frac_ink": float(np.median(opx) / np.median(inks))}, "given", background)
    if outl is not None and opx:
        sizes_ = [i["size_hint_px"] for i in its if i["size_hint_px"]]
        frac = float(np.median(opx) / np.median(sizes_)) if sizes_ else 0.075
        return {"name": "measured", "fill": fills[0], "outline": outl, "outline_frac": frac}, "given", background
    return {"name": "measured", "fill": fills[0], "outline": outl, "outline_frac": 0.075 if outl is not None else 0.0}, \
        "given", background


def identify_reference(preset_name: str, roles: Sequence[str] | None = None, max_per_role: int = 12,
                       candidates: Sequence[str] | None = None, jobs: int = 1, repeats: int = 2,
                       progress=None) -> dict:
    """`ref fonts`: identify the font of each caption role from real reference crops."""
    from ..config import load_preset
    from ..fonts import candidate_names

    pr = load_preset(preset_name)
    canvas = (int(pr.get("canvas.width")), int(pr.get("canvas.height")))
    role_names = list(roles or pr.section("text.roles").keys())
    cands = list(candidates or candidate_names())
    if not candidates:
        for r in role_names:
            n = pr.get(f"text.roles.{r}.font_name")
            if n and n not in cands:
                cands.append(n)
    crops = collect_reference_crops(preset_name, role_names, max_per_role)
    ident = _unmeasured_identification(pr, _no_crops_blocker(preset_name))
    ident["roles"] = {r: v for r, v in ident["roles"].items() if r in role_names}
    ident["skipped"] = crops["skipped"]
    ident["videos"] = crops["videos"]
    measurement_items = []
    if not any(crops["items"].values()):
        _merge_identification(pr, ident)
        return ident
    cond = conditions_from_videos(crops["videos"], canvas)
    refs, missing = resolve_candidates(cands)
    fmt_of = _video_formats(pr)
    ident.update({"status": "partial", "label_ko": "일부 측정", "blocker": None, "conditions": cond.to_dict(),
                  "candidates_missing": missing, "candidates_not_acquired": _not_acquired()})
    for role in role_names:
        its = crops["items"].get(role) or []
        if not its:
            ident["roles"][role].update({"blocker": "이 역할의 자막 crop 없음"})
            continue
        style, color_mode, background = _role_style(its)
        rcond = Conditions.from_dict({**cond.to_dict(), "background": background})
        qp = None
        if rcond.codec == "h264":
            spans_by_video: dict[str, list] = {}
            for i in its:
                spans_by_video.setdefault(i["video_id"], []).append((i["start"], i["end"], i["bbox"]))
            meds, qps = [], {}
            for vid, spans in spans_by_video.items():
                q = measure_caption_qp(crops["video_paths"][vid], spans)
                if q:
                    qps[vid] = q
                    meds.append(q["qp"]["p50"])
            if meds:
                qp = {"per_video": qps, "median": float(np.median(meds))}
                rcond = Conditions.from_dict({**rcond.to_dict(), "qp": round(qp["median"]), "crf": None,
                                              "bitrate_kbps": None, "assumed": False,
                                              "source": "caption-macroblock QP measured with ffmpeg -debug qp"})
        sc = rcond.ref_resolution[0] / rcond.canvas[0]
        # ceiling at the INK height measured on the reference crops (font independent)
        inks = []
        for i in its:
            m = extract_masks(i["crop"], i["fill_rgb"] if color_mode == "given" else None,
                              i["outline_rgb"] if color_mode == "given" else None)
            inks.append(_ink_height(m["fill"], 0.02))
        inks = [v for v in inks if v > 0] or [i["bbox"][3] / 1.3 for i in its]
        ink_canvas = sorted({int(round(v / sc)) for v in np.percentile(inks, [10, 50, 90])})
        args = [(fr.name, rcond.to_dict(), DEFAULT_STRINGS[:4], ink_canvas, [style], repeats, [], color_mode, 7, "ink")
                for fr in refs]
        res = _pmap(_font_job, args, jobs, progress)
        ceilings = {r["font"]: r["ceiling"] for r in res}
        per, _, failed_crops = score_crops(its, refs, color_mode)
        idr = rank_candidates(per, ceilings)
        top = idr["ranked"][0] if idr["ranked"] else None
        identical = bool(top and top["verdict"] == "identical")
        by_format = {}
        for fmt in sorted({fmt_of.get(i["video_id"]) for i in its} - {None}):
            ids = {i["id"] for i in its if fmt_of.get(i["video_id"]) == fmt}
            sub = rank_candidates({n: [r for r in rows if r["id"] in ids] for n, rows in per.items()}, ceilings)
            by_format[fmt] = {"n": len(ids), "top": sub["top"], "verdict": sub["top_verdict"], "summary": sub["summary"],
                              "value": sub["top"] if sub["top_verdict"] == "identical" else None}
        ident["roles"][role].update({
            "status": "measured" if identical else "unmeasured",
            "label_ko": "측정" if identical else "못 잼",
            "n_crops": len(its), "crops": [{"id": i["id"], "video_id": i["video_id"], "t": i["t"], "bbox": i["bbox"],
                                            "resolution": i["resolution"], "text": i["text"]} for i in its],
            "candidate_ranking": [{k: v for k, v in r.items() if k != "per_crop"} for r in idr["ranked"]],
            "verdict": top["verdict"] if top else None, "summary": idr["summary"], "failed_crops": failed_crops,
            "by_format": by_format or None,
            "by_format_note": None if by_format else "포맷 분류 없음(formats.yaml 미측정) → 포맷별 판정 못 잼",
            "ceiling_conditions": rcond.to_dict(), "caption_qp": qp, "ceiling_ink_heights_px_canvas": ink_canvas,
            "sizes_resolution": list(rcond.canvas), "color_mode": color_mode,
            "ceilings": {n: {k: v for k, v in c.items() if k not in ("rows", "conditions")} for n, c in ceilings.items()}})
        mi = {"key": f"text.roles.{role}.font_name", "unit": None, "resolution": list(rcond.ref_resolution),
              "method": "font IoU vs candidates with measured IoU ceiling (shortkit.reference.typography)",
              "measured_at": now_iso(),
              "evidence": [{"video_id": i["video_id"], "t": i["t"], "value": None, "bbox": i["bbox"]} for i in its[:10]],
              "overall": {**(top["iou_stats"] if top else {"n": 0, "p10": None, "p50": None, "p90": None}),
                          "top": top["font"] if top else None, "margin": top["margin"] if top else None},
              "by_format": {f: {"n": v["n"], "value": v["value"], "verdict": v["verdict"]} for f, v in by_format.items()}}
        if identical:
            mi.update({"status": "measured", "value": top["font"], "blocker": None})
        else:
            mi.update({"status": "unmeasured", "value": None, "blocker": f"동일 판정 없음: {idr['summary']}"})
        measurement_items.append(mi)
    if all(ident["roles"][r].get("status") == "measured" for r in role_names):
        ident["status"] = "measured"
        ident["label_ko"] = "측정"
    _merge_identification(pr, ident)
    if measurement_items:
        write_json(pr.dir / "measurements" / "font_identity.json",
                   {"schema": "shortkit.measurement/1", "group": "font_identity", "source_snapshot": None,
                    "items": measurement_items})
    return ident


def _merge_identification(preset, ident: dict) -> None:
    path = _report_path(preset.name)
    rep = read_json(path, {}) or {"schema": REPORT_SCHEMA, "preset_id": preset.preset_id}
    rep["identification"] = ident
    rep["identification_updated_at"] = now_iso()
    rep["status"] = _report_status(rep)
    write_json(path, rep)


def _report_status(rep: dict) -> str:
    st = (rep.get("identification") or {}).get("status")
    if st == "measured":
        return "measured"
    if st == "partial":
        return "partial: 일부 역할만 동일 판정/측정, 나머지 못 잼"
    if rep.get("ceilings"):
        return STATUS_CEILING_ONLY
    return "unmeasured (못 잼): 천장·판정 모두 미측정"


# ============================================================================= CLI
def _parse_res(s: str) -> tuple[int, int]:
    a, b = s.lower().split("x")
    return int(a), int(b)


def _progress(prefix: str):
    def f(i, n):
        print(f"  {prefix} {i}/{n}", file=sys.stderr, flush=True)
    return f


def cmd_font_ceiling(args) -> int:
    from ..config import load_preset
    from ..fonts import candidate_names

    pr = load_preset(args.preset)
    canvas = (int(pr.get("canvas.width")), int(pr.get("canvas.height")))
    ref_res = _parse_res(args.ref_resolution) if args.ref_resolution else canvas
    conds = []
    for crf in (args.crf or ([] if args.bitrate_kbps else [23.0, 30.0])):
        conds.append(Conditions(canvas=canvas, ref_resolution=ref_res, codec=args.codec, crf=float(crf),
                                background=args.background, renderer=args.renderer, assumed=True,
                                source="assumed (CLI)"))
    for br in args.bitrate_kbps or []:
        conds.append(Conditions(canvas=canvas, ref_resolution=ref_res, codec=args.codec, crf=None,
                                bitrate_kbps=float(br), background=args.background, renderer=args.renderer,
                                assumed=True, source="assumed (CLI)"))
    if args.fonts:
        fonts_ = [f.strip() for f in args.fonts.split(",") if f.strip()]
    else:
        fonts_ = candidate_names()
        for r in pr.section("text.roles"):
            n = pr.get(f"text.roles.{r}.font_name")
            if n and n not in fonts_:
                fonts_.append(n)
    sizes = [float(v) for v in args.sizes.split(",")] if args.sizes else list(DEFAULT_SIZES)
    strings = DEFAULT_STRINGS[:args.n_strings]
    styles = args.style or ["white_black_outline", "yellow_black_outline"]
    print(f"글꼴 {len(fonts_)}종 × 조건 {len(conds)}개 × 표본 {len(strings) * len(sizes) * args.repeats}개 "
          f"(가까운 후보 {args.nearest}개와 교차) — 계산 중…", flush=True)
    exp = run_ceiling_experiment(fonts_, conds, strings, sizes, styles, args.repeats, args.nearest, args.jobs,
                                 args.color_mode, progress=_progress("font"))
    for line in summarize_experiment(exp):
        print(line)
    if exp["missing"]:
        print("찾지 못한 후보(대체 글꼴 사용 안 함): " + ", ".join(exp["missing"]))
    if args.no_write:
        return 0
    cmd = _command_line(args)
    p = write_ceiling_report(pr, exp, conds, cmd)
    print(f"보고서: {_safe_rel(p)}  (상태: {read_json(p)['status']})")
    return 0


def _command_line(args) -> str:
    parts = ["python -m shortkit ref font-ceiling", f"--preset {args.preset}"]
    parts += [f"--crf {c:g}" for c in args.crf or []]
    parts += [f"--bitrate-kbps {b:g}" for b in args.bitrate_kbps or []]
    if args.ref_resolution:
        parts.append(f"--ref-resolution {args.ref_resolution}")
    if args.sizes:
        parts.append(f"--sizes {args.sizes}")
    if args.fonts:
        parts.append(f'--fonts "{args.fonts}"')
    parts += [f"--codec {args.codec}", f"--n-strings {args.n_strings}", f"--repeats {args.repeats}",
              f"--nearest {args.nearest}", f"--background {args.background}", f"--renderer {args.renderer}",
              f"--color-mode {args.color_mode}"]
    parts += [f"--style {st}" for st in args.style or []]
    return " ".join(parts)


def cmd_fonts(args) -> int:
    roles = [r.strip() for r in args.roles.split(",")] if args.roles else None
    cands = [c.strip() for c in args.candidates.split(",")] if args.candidates else None
    ident = identify_reference(args.preset, roles, args.max_crops, cands, args.jobs, progress=_progress("font"))
    print(f"글꼴 판정 상태: {ident['status']} ({ident.get('label_ko')})")
    if ident.get("blocker"):
        print(f"  막힌 이유: {ident['blocker']}")
        print(f"  제작 영향: {ident.get('impact')}")
    for role, r in ident["roles"].items():
        verdict = r.get("verdict")
        print(f"  {role:<12} {r.get('label_ko', '못 잼'):<6} 현재 프리셋 글꼴={r.get('current_preset_font')}"
              + (f"  판정={VERDICT_KO.get(verdict, verdict)}: {r.get('summary')}" if verdict else ""))
    print(f"보고서: {_safe_rel(_report_path(args.preset))}")
    return 0


def cmd_font_candidates(args) -> int:
    from .. import fonts as F

    if args.fetch:
        r = F.fetch_all(local_dir=args.local_dir)
        for name, row in r["results"].items():
            print(f"{name:<28} {row['status']:<16} {row['detail']}")
    return F._cmd_list(args)


def register(subparsers) -> None:
    """Add `ref fonts`, `ref font-ceiling`, `ref font-candidates` to the `ref` sub-command group."""
    if isinstance(subparsers, argparse.ArgumentParser):
        subparsers = subparsers.add_subparsers(dest="cmd", required=True)
    p = subparsers.add_parser("font-ceiling", help="글꼴 판정 IoU 천장(같은 글꼴 상한)·가까운 글꼴 구분력 계산 → fonts_report.json")
    p.add_argument("--preset", default="joshuamagazine")
    p.add_argument("--crf", action="append", type=float, help="가정 CRF (여러 번; 기본 23, 30)")
    p.add_argument("--bitrate-kbps", action="append", type=float, help="전체 화면 기준 비디오 비트레이트(kbps)")
    p.add_argument("--codec", default="h264", choices=sorted(_ENCODERS))
    p.add_argument("--ref-resolution", default=None, help="레퍼런스 다운로드 해상도 WxH (기본: 프리셋 canvas)")
    p.add_argument("--sizes", default=None, help="canvas 기준 글자 크기 px, 쉼표 구분 (기본 40,56,72,90)")
    p.add_argument("--n-strings", type=int, default=3)
    p.add_argument("--repeats", type=int, default=2)
    p.add_argument("--style", action="append", choices=sorted(STYLE_VARIANTS))
    p.add_argument("--background", default="video", choices=["video", "black"])
    p.add_argument("--renderer", default="supersample4", choices=["supersample4", "hinted1x"])
    p.add_argument("--color-mode", default="estimated", choices=["estimated", "given"])
    p.add_argument("--fonts", default=None, help="글꼴 이름 목록(쉼표). 기본: manifest+시스템 후보+프리셋 역할 글꼴")
    p.add_argument("--nearest", type=int, default=3, help="글꼴마다 교차 비교할 가까운 후보 수")
    p.add_argument("--jobs", type=int, default=1)
    p.add_argument("--no-write", action="store_true", help="보고서 파일을 쓰지 않음")
    p.set_defaults(func=cmd_font_ceiling)

    q = subparsers.add_parser("fonts", help="레퍼런스 자막 crop 으로 역할별 글꼴 판정(동일/유사/다름) → fonts_report.json")
    q.add_argument("--preset", default="joshuamagazine")
    q.add_argument("--roles", default=None)
    q.add_argument("--candidates", default=None)
    q.add_argument("--max-crops", type=int, default=12)
    q.add_argument("--jobs", type=int, default=1)
    q.set_defaults(func=cmd_fonts)

    c = subparsers.add_parser("font-candidates", help="후보 글꼴 상태 확인(--fetch: manifest 글꼴 받기)")
    c.add_argument("--fetch", action="store_true")
    c.add_argument("--local-dir", default=None)
    c.set_defaults(func=cmd_font_candidates)


if __name__ == "__main__":
    _ap = argparse.ArgumentParser(prog="python -m shortkit.reference.typography")
    register(_ap)
    _a = _ap.parse_args()
    sys.exit(_a.func(_a))
