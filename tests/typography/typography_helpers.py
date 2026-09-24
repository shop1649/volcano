"""SYNTHETIC caption images for typography tests (rendered here; no reference pixels)."""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageDraw

from shortkit.reference import typography as T


def clean_crop(font: str, text: str, size: float, fill=(255, 255, 255), outline=(0, 0, 0), outline_frac=0.075,
               bg=(60, 90, 120), margin_frac=0.3, subpx=(0.37, 0.61)):
    """Caption drawn (supersampled) on a flat background; returns (crop, anchor_xy, truth_fill_mask)."""
    fr = T.font_ref(font)
    f = T.load_font(fr.abspath, size, fr.index)
    opx = size * outline_frac if outline is not None else 0.0
    x0, y0, x1, y1 = f.getbbox(text, anchor="ls", stroke_width=opx)
    m = int(size * margin_frac)
    W, H = int(x1 - x0) + 2 * m, int(y1 - y0) + 2 * m
    xy = (m - x0 + subpx[0], m - y0 + subpx[1])
    canvas = np.zeros((H, W, 3), np.uint8)
    canvas[:] = bg
    img, _ = T.draw_caption(canvas, text, fr.abspath, size, xy, fill, outline, opx, fr.index)
    # truth fill mask: fill coverage >= 0.5 at the same position (same supersampling)
    black = np.zeros_like(canvas)
    tru, _ = T.draw_caption(black, text, fr.abspath, size, xy, (255, 255, 255), None, 0.0, fr.index)
    return img, xy, tru[..., 0] >= 128


def frankenstein_frame(font_a: str, font_b: str, text: str, swap_index: int, size: float, width: int, height: int,
                       fill=(255, 255, 255), outline=(0, 0, 0), outline_frac=0.075, ss: int = 4, bg=None):
    """Caption in font A where ONE glyph (text[swap_index]) is drawn with font B at A's advance
    (same layout, different glyph shape).  Returns (frame, ink bbox)."""
    fa, fb = T.font_ref(font_a), T.font_ref(font_b)
    A = T.load_font(fa.abspath, size * ss, fa.index)
    B = T.load_font(fb.abspath, size * ss, fb.index)
    A1 = T.load_font(fa.abspath, size, fa.index)
    opx = size * outline_frac
    x0, y0, x1, y1 = A1.getbbox(text, anchor="ls", stroke_width=opx)
    ox = (width - (x1 - x0)) / 2 - x0
    oy = height / 2 - (y0 + y1) / 2
    fill_l = Image.new("L", (width * ss, height * ss), 0)
    union_l = Image.new("L", (width * ss, height * ss), 0)
    df, du = ImageDraw.Draw(fill_l), ImageDraw.Draw(union_l)
    for i, ch in enumerate(text):
        if ch.isspace():
            continue
        x = (ox + A1.getlength(text[:i])) * ss
        font = B if i == swap_index else A
        df.text((x, oy * ss), ch, font=font, fill=255, anchor="ls")
        du.text((x, oy * ss), ch, font=font, fill=255, anchor="ls", stroke_width=opx * ss, stroke_fill=255)

    def down(im):
        a = np.asarray(im, np.float32) / 255.0
        return a.reshape(height, ss, width, ss).mean(axis=(1, 3))[..., None]

    af = down(fill_l)
    au = np.maximum(down(union_l), af)
    base = np.zeros((height, width, 3), np.float32) if bg is None else bg.astype(np.float32)
    img = base * (1 - au) + np.array(outline, np.float32) * (au - af) + np.array(fill, np.float32) * af
    box = [ox + x0, oy + y0, ox + x1, oy + y1]
    return np.clip(np.round(img), 0, 255).astype(np.uint8), box


def degrade_and_crop(frame: np.ndarray, box, cond: T.Conditions, frames: int = 3):
    """Encode a static caption frame like the reference pipeline; crop (with margin) the middle frame."""
    dec = T.degrade([frame] * frames, cond, keep_every=frames, keep_offset=frames // 2)[0]
    sc = cond.ref_resolution[0] / cond.canvas[0]
    h = (box[3] - box[1]) * sc
    m = max(3.0, 0.15 * h)
    x0, y0 = max(0, int(math.floor(box[0] * sc - m))), max(0, int(math.floor(box[1] * sc - m)))
    x1 = min(dec.shape[1], int(math.ceil(box[2] * sc + m)))
    y1 = min(dec.shape[0], int(math.ceil(box[3] * sc + m)))
    return dec[y0:y1, x0:x1].copy()
