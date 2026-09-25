"""Burned-in text analysis of a reference video: line detection, tracking over time, OCR,
role clustering and per-role style measurement.

Pipeline (all coordinates are px in the video's own resolution, stored with ``resolution``):

1. Sample frames at ``fps`` (default 5; 4-10 recommended).  Per frame, candidate text lines are
   found with a morphological gradient restricted to pixels that did not change since the previous
   sample (overlays are static while footage moves), closed horizontally into line blobs and
   split at empty rows.
2. Line blobs are tracked across samples (IoU + gradient-signature correlation).  A track is a
   line of text with constant content and position.
3. Each track is OCR-confirmed (tesseract ``kor+eng``, ``--psm 7``) on a binarized crop (fill
   pixels black on white).  Tracks without letters / with low confidence are dropped.
4. Style per line on up to 3 samples (median): fill color (+ a second "highlight" color when a
   distinct color cluster covers >= 12 % of the fill), outline thickness and color (distance
   transform rings around the fill), drop shadow (asymmetric dark offset), background box
   (4-sided contrast step around the ink), font size (ink height of Hangul rows converted to a
   libass ``Fontsize`` by rendering a calibration line with the role's preset font).
5. Lines that appear and disappear together and are stacked are grouped into caption items.
6. Native-frame refinement per item: exact appear/disappear frame, motion_in / motion_out type
   (pop = scale change, slide = offset, fade = alpha ramp, none) and duration from bbox scale /
   position / alpha trajectories, box alpha by regression against the frame before appearance.
7. Roles: title (persistent, top), description (persistent/long, directly under the title and
   smaller), speaker (small boxed short label), reaction (short, big, saturated color), and within
   the main caption band dialogue (quote marks, or overlapping speech from audio analysis) vs
   situation.  Every assignment stores ``role_reason``.

Anything that cannot be determined is ``None`` / ``"unmeasured"`` with a note, never a default.
"""
from __future__ import annotations

import math
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .. import paths
from ..util.jsonio import now_iso, read_json, write_json
from ..util.media import probe, read_frames
from ..util.stats import tri_state
from .common import (ROLES, analysis_dir, color_dist, color_mode, detect_video_region, even_crop, hexrgb,
                     read_segment, saturation)

SCHEMA_CAPTIONS = "shortkit.ref_captions/1"
SCHEMA_LAYOUT = "shortkit.ref_layout/1"
DEFAULT_FPS = 5.0
DEFAULT_CALIB_FONT = "Noto Sans CJK KR Black"
CALIB_TEXT = "가나다라마바사아자차카타파하한글높이"
QUOTE_CHARS = set('"“”„‟\'‘’「」『』《》')
QUOTE_OPEN = set('"“„‟\'‘「『《')
QUOTE_CLOSE = set('"”‟\'’」』》')
HANGUL_RE = re.compile(r"[가-힣]")


def quote_pair(text: str) -> dict:
    """Leading / trailing quote marks of an OCR'd caption (first char of the first line, last char
    of the last line, ignoring spaces and trailing punctuation-free whitespace).

    ``kind``: ``pair`` (both ends quoted), ``none`` (neither), ``partial`` (one end only -- usually an
    OCR drop, not a style).  ``open`` / ``close`` are the exact OCR'd characters."""
    t = (text or "").strip()
    if not t:
        return {"kind": "none", "open": "", "close": ""}
    o = t[0] if t[0] in QUOTE_OPEN else ""
    c = t[-1] if t[-1] in QUOTE_CLOSE and len(t) > 1 else ""
    kind = "pair" if (o and c) else ("none" if not (o or c) else "partial")
    return {"kind": kind, "open": o, "close": c}
LETTER_RE = re.compile(r"[가-힣A-Za-z0-9]")

METHOD = {
    "detection": "morphological gradient (>=60) on pixels unchanged since previous sample (<14), glyph-like "
                 "components (frame-like ones peeled: straight runs >= 4 x min line height cut out, a peeled "
                 "word kept where it continues a kept text row), horizontal close, row-valley split; tracked "
                 "by IoU>=0.5 and gradient-signature correlation>=0.55",
    "ocr": "tesseract kor+eng --psm 7 on fill mask (black on white, ink height scaled to ~44px)",
    "size_px": "Hangul ink height (row-profile >= 12% of max) / (ink height per em px of the calibration font "
               "rendered by libass) -> font EM size in px at the video resolution (renderer convention; "
               "libass Fontsize = size_px * (winAscent+winDescent)/unitsPerEm)",
    "outline_px": "sum over distance-transform rings around the fill of the share of outline-colored pixels "
                  "(closer to the outline colour than to the fill and to the LOCAL background = median of the 3 "
                  "rings past the first ring-median step > max(12, 4 x robust noise)); no step within 0.5 x "
                  "text height -> 'unbounded' (not measured)",
    "box": "4-sided luminance step around the glyph fill bbox (>=15 levels, same sign, pad>=2px); pad = step "
           "distance minus a visible outline (renderer: box = ink incl. outline + pad; an outline invisible "
           "against the box stays in the pad, noted); alpha by linear regression box = a*C + (1-a)*background "
           "using the frame before the text appears",
    "motion": "native frames around appear/disappear; changed-pixel bbox scale/offset vs rest; alpha by "
              "projection on the rest footprint; pop if |scale-1|>=0.06, slide if offset>=max(3px,0.1h), "
              "fade if alpha<=0.75 on the first visible frame",
    "bbox": "visible ink (fill + outline, excluding box and shadow) at rest, [x, y, w, h] px",
}


# ============================================================================= font calibration
_CALIB: dict[str, dict | None] = {}


def ink_height(mask: np.ndarray) -> int | None:
    prof = mask.sum(axis=1).astype(float)
    if prof.size == 0 or prof.max() <= 0:
        return None
    rows = np.nonzero(prof >= 0.12 * prof.max())[0]
    return int(rows[-1] - rows[0] + 1)


_FONTSELECT_RE = re.compile(r"fontselect: \((?P<req>.*?), \d+, \d+\) -> (?P<file>.*?), (?P<idx>\d+), (?P<ps>\S+)")


def calibrate_font(font_name: str) -> dict | None:
    """Ink height of a Hangul line per libass ``Fontsize`` unit for ``font_name``.

    The font must resolve exactly (``shortkit.fonts.resolve_font``) AND libass must actually
    select that face: libass silently substitutes unknown names (e.g. "Noto Sans CJK KR Bold" is
    not a family/fullname libass knows and falls back to another font), so the ``fontselect``
    line of the libass log is checked and the PostScript name is tried first.  Returns None when
    the exact face cannot be rendered -- the size is then reported unmeasured, never guessed.
    """
    if font_name in _CALIB:
        return _CALIB[font_name]
    _CALIB[font_name] = None
    try:
        from .. import fonts
        face = fonts.resolve_font(font_name)
    except Exception:
        face = None
    if face is None:
        return None
    use_dir = getattr(face, "source", "") != "system"
    for ass_name in [n for n in (face.postscript, font_name) if n]:
        r = _render_calibration(ass_name, Path(face.path), int(face.index), face.postscript, use_dir)
        if r is not None:
            # Preset convention (shared with the renderer, shortkit/edit/captions.py): size_px is the EM size in
            # canvas px; libass Fontsize = size_px * (winAscent+winDescent)/unitsPerEm.  Convert the per-Fontsize
            # ink ratio into a per-em-px ratio so measured size_px means the same thing the renderer consumes.
            from ..edit.captions import read_faces
            fm = read_faces(str(face.path))[int(face.index)]
            fs_per_em = fm.win_sum / fm.units_per_em
            r["fontsize_per_em"] = round(fs_per_em, 5)
            r["ratio_em"] = round(r["ratio"] * fs_per_em, 5)
            r.update({"font": font_name, "libass_name": ass_name, "font_file": _display(face.path),
                      "face_index": int(face.index)})
            _CALIB[font_name] = r
            return r
    return None


def _render_calibration(ass_name: str, font_path: Path, face_index: int, postscript: str | None,
                        use_fontsdir: bool) -> dict | None:
    import cv2

    fs = 200
    with tempfile.TemporaryDirectory() as td:
        ass = Path(td) / "c.ass"
        ass.write_text(
            "[Script Info]\nScriptType: v4.00+\nPlayResX: 1920\nPlayResY: 1080\nWrapStyle: 2\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
            "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding\n"
            f"Style: C,{ass_name},{fs},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,5,"
            "0,0,0,1\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
            f"Dialogue: 0,0:00:00.00,0:00:01.00,C,,0,0,0,,{{\\pos(960,540)}}{CALIB_TEXT}\n", encoding="utf-8")
        png = Path(td) / "c.png"
        vf = f"ass={ass}"
        if use_fontsdir:
            vf += ":fontsdir=" + str(font_path.parent).replace("\\", "/").replace(":", r"\:")
        p = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "verbose", "-y", "-f", "lavfi", "-i",
                            "color=c=black:s=1920x1080:d=1:r=25", "-vf", vf,
                            "-frames:v", "1", str(png)], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        log = p.stderr.decode("utf-8", "replace")
        sel = [m for m in _FONTSELECT_RE.finditer(log) if m.group("req") == ass_name]
        if p.returncode != 0 or not sel:
            return None
        # every face libass used for this style must be the requested one (no glyph fallback)
        for m in sel:
            f = m.group("file")
            try:
                same = Path(f).resolve() == font_path.resolve()
            except OSError:
                same = False
            # memory fonts loaded from fontsdir are logged by PostScript name instead of path
            same = same or (bool(postscript) and f == postscript and m.group("ps") == postscript)
            if not same or int(m.group("idx")) != face_index:
                return None
        img = cv2.imread(str(png), cv2.IMREAD_GRAYSCALE)
    if img is None:
        return None
    ih = ink_height(img > 128)
    if not ih:
        return None
    return {"ratio": round(ih / fs, 5), "fontsize": fs, "ink_h": ih, "text": CALIB_TEXT,
            "renderer": "libass (ffmpeg ass filter)", "verified_face": True}


def _display(p) -> str:
    try:
        return paths.relp(p)
    except Exception:
        return f"<system>/{Path(p).name}"


# ============================================================================= detection
def _grad(gray: np.ndarray) -> np.ndarray:
    import cv2
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    return cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, k)


PEEL_RUN_MIN_H = 4.0   # straight runs >= this x min line height are cut out of frame-like components


def detect_lines(rgb: np.ndarray, prev_gray: np.ndarray | None) -> tuple[list[tuple[int, int, int, int]], np.ndarray]:
    """Candidate text-line boxes (x, y, w, h) and the stable-gradient mask used for tracking."""
    import cv2

    H, W = rgb.shape[:2]
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    grad = _grad(gray)
    m = grad >= 60
    if prev_gray is not None:
        m &= cv2.absdiff(gray, prev_gray) < 14
    # edge components -> keep only glyph-like ones (strong contrast, not long thin frames/lines)
    n0, lab0, st0, _ = cv2.connectedComponentsWithStats(m.astype(np.uint8), 8)
    min_h = max(8, int(round(0.008 * H)))
    strong = (grad >= 120).ravel().astype(np.float64)
    area = st0[:, 4].astype(float)
    share = np.bincount(lab0.ravel(), weights=strong, minlength=n0) / np.maximum(area, 1)
    cw, ch = st0[:, 2], st0[:, 3]
    dens0 = area / np.maximum(cw * ch, 1)
    frame_like = (((dens0 < 0.1) & (np.maximum(cw, ch) > 2.5 * min_h))     # rectangle outlines, table edges
                  | ((cw > 4 * ch) & (dens0 < 0.2)))                          # long straight edges
    glyphish = (share >= 0.3) & (area >= 6) & (ch >= 0.35 * min_h)
    keep = glyphish & (ch <= 0.2 * H) & ~frame_like
    keep[0] = False
    mu = keep[lab0].astype(np.uint8)
    # A glyph that touches a frame-like structure is dropped with it (mockloop: the first word of a speaker
    # label touched its own box's top edge (pad 3 px at the working scale), which met scene edges running
    # up to the video border).  Peel such components: cut their straight runs out and re-test the rest.
    fl = np.nonzero(frame_like & glyphish)[0]
    fl = fl[fl != 0]
    if fl.size:
        run = max(5, int(round(PEEL_RUN_MIN_H * min_h)))
        fm = np.isin(lab0, fl).astype(np.uint8)
        runs = (cv2.morphologyEx(fm, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (run, 1)))
                | cv2.morphologyEx(fm, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_RECT, (1, run))))
        # the runs' 1-px neighbourhood goes too (antialiased edge rows beside the straight run)
        runs = cv2.dilate(runs, np.ones((3, 3), np.uint8))
        rest = fm & (1 - runs)
        n1, lab1, st1, _ = cv2.connectedComponentsWithStats(rest, 8)
        if n1 > 1:
            a1 = st1[:, 4].astype(float)
            sh1 = np.bincount(lab1.ravel(), weights=strong, minlength=n1) / np.maximum(a1, 1)
            w1, h1 = st1[:, 2], st1[:, 3]
            d1 = a1 / np.maximum(w1 * h1, 1)
            k1 = ((sh1 >= 0.3) & (a1 >= 6) & (h1 >= 0.35 * min_h) & (h1 <= 0.2 * H)
                  & ~((d1 < 0.1) & (np.maximum(w1, h1) > 2.5 * min_h)) & ~((w1 > 4 * h1) & (d1 < 0.2)))
            k1[0] = False
            # accept a peeled word only where it continues a kept text row (same band, similar height,
            # within one line height) -- the first word of a label beside its other words; loose scene
            # bits left over from the peel never
            pk = k1[lab1].astype(np.uint8)
            kxw = max(5, int(round(0.02 * W)))
            ker = cv2.getStructuringElement(cv2.MORPH_RECT, (kxw, 3))
            ng, labg, stg, _ = cv2.connectedComponentsWithStats(cv2.morphologyEx(pk, cv2.MORPH_CLOSE, ker), 8)
            nr, _labr, str_, _ = cv2.connectedComponentsWithStats(cv2.morphologyEx(mu, cv2.MORPH_CLOSE, ker), 8)
            rows = [str_[j] for j in range(1, nr) if str_[j][3] >= min_h]
            for j in range(1, ng):
                x_, y_, w_, h_ = stg[j][:4]
                for (rx, ry, rw, rh, _a) in rows:
                    vov = min(y_ + h_, ry + rh) - max(y_, ry)
                    gap = max(x_ - (rx + rw), rx - (x_ + w_))
                    if vov >= 0.6 * max(h_, rh) and gap <= max(h_, rh) and 0.6 <= h_ / max(rh, 1) <= 1.6:
                        mu |= (pk & (labg == j)).astype(np.uint8)
                        break
    kx = max(5, int(round(0.02 * W)))
    closed = cv2.morphologyEx(mu, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (kx, 3)))
    n, lab, st, _ = cv2.connectedComponentsWithStats(closed, 8)
    boxes = []
    for i in range(1, n):
        x, y, w, h, area_i = st[i]
        if h < min_h or h > 0.2 * H or w < 0.5 * h or w < min_h:
            continue
        dens = mu[y:y + h, x:x + w].mean()
        if dens < 0.15:
            continue
        for (sy, sh) in _split_rows(mu[y:y + h, x:x + w], min_h):
            sub = mu[y + sy:y + sy + sh, x:x + w]
            cols = np.nonzero(sub.any(axis=0))[0]
            if cols.size == 0:
                continue
            bx0, bx1 = x + int(cols[0]), x + int(cols[-1]) + 1
            if (bx1 - bx0) < 0.5 * sh:
                continue
            boxes.append((int(bx0), int(y + sy), int(bx1 - bx0), int(sh)))
    boxes = _merge_lines(boxes)
    return boxes, mu


def _split_rows(mask: np.ndarray, min_h: int) -> list[tuple[int, int]]:
    prof = mask.sum(axis=1).astype(float)
    h = len(prof)
    # only boxes tall enough to hold two lines are split; each part must itself be line-sized
    # (small unoutlined Hangul has empty rows between stacked jamo inside ONE line)
    if h < 2.2 * min_h or prof.max() <= 0:
        return [(0, h)]
    empty = prof <= 0.04 * prof.max()
    parts, start = [], None
    for i in range(h + 1):
        full = i < h and not empty[i]
        if full and start is None:
            start = i
        elif not full and start is not None:
            parts.append((start, i - start))
            start = None
    parts = [p for p in parts if p[1] >= max(3, 0.3 * min_h)]
    if len(parts) <= 1:
        return [(0, h)] if not parts else [parts[0]]
    if any(p[1] < max(min_h, 0.35 * h / len(parts)) for p in parts):
        return [(0, h)]
    # real text lines have similar heights and a real gap; the jamo of one big syllable ("헉") do not
    hs = [p[1] for p in parts]
    gaps = [parts[i + 1][0] - (parts[i][0] + parts[i][1]) for i in range(len(parts) - 1)]
    if max(hs) > 1.35 * min(hs) or min(gaps) < 0.1 * min(hs):
        return [(0, h)]
    return parts


def _merge_lines(boxes: list[tuple[int, int, int, int]]) -> list[tuple[int, int, int, int]]:
    boxes = sorted(boxes, key=lambda b: b[0])
    changed = True
    while changed:
        changed = False
        out: list[list[int]] = []
        for b in boxes:
            x, y, w, h = b
            for o in out:
                ox, oy, ow, oh = o
                vov = min(y + h, oy + oh) - max(y, oy)
                gap = max(x - (ox + ow), ox - (x + w))
                if vov >= 0.5 * min(h, oh) and gap <= 1.0 * max(h, oh) and max(h, oh) <= 1.8 * min(h, oh):
                    nx0, ny0 = min(x, ox), min(y, oy)
                    nx1, ny1 = max(x + w, ox + ow), max(y + h, oy + oh)
                    o[:] = [nx0, ny0, nx1 - nx0, ny1 - ny0]
                    changed = True
                    break
            else:
                out.append(list(b))
        boxes = [tuple(o) for o in out]
    return boxes


def _sig(mask: np.ndarray, b) -> np.ndarray:
    import cv2
    x, y, w, h = b
    c = mask[y:y + h, x:x + w].astype(np.float32)
    s = cv2.resize(c, (48, 12), interpolation=cv2.INTER_AREA).ravel()
    s = s - s.mean()
    n = np.linalg.norm(s)
    return s / n if n > 1e-6 else s


def _iou(a, b) -> float:
    ax0, ay0, aw, ah = a
    bx0, by0, bw, bh = b
    ix = max(0, min(ax0 + aw, bx0 + bw) - max(ax0, bx0))
    iy = max(0, min(ay0 + ah, by0 + bh) - max(ay0, by0))
    inter = ix * iy
    u = aw * ah + bw * bh - inter
    return inter / u if u > 0 else 0.0


@dataclass
class Sample:
    t: float
    idx: int
    bbox: tuple[int, int, int, int]
    crop: np.ndarray | None
    origin: tuple[int, int]


@dataclass
class Track:
    id: int
    samples: list[Sample] = field(default_factory=list)
    sig: np.ndarray | None = None

    @property
    def last(self) -> Sample:
        return self.samples[-1]

    @property
    def start(self) -> float:
        return self.samples[0].t

    @property
    def end(self) -> float:
        return self.samples[-1].t


def _crop_with_pad(rgb: np.ndarray, b, pad: int) -> tuple[np.ndarray, tuple[int, int]]:
    H, W = rgb.shape[:2]
    x, y, w, h = b
    x0, y0 = max(0, x - pad), max(0, y - pad)
    x1, y1 = min(W, x + w + pad), min(H, y + h + pad)
    return rgb[y0:y1, x0:x1].copy(), (x0, y0)


def track_lines(video: Path, fps: float, max_seconds: float | None = None) -> tuple[list[Track], dict]:
    """Stage 1+2: sample, detect and track candidate lines."""
    import cv2

    from ..util.media import iter_frames

    tracks: list[Track] = []
    active: list[Track] = []
    prev_gray = None
    idx = -1
    info = {"n_samples": 0}
    for t, fr in iter_frames(video, fps=fps, duration=max_seconds):
        idx += 1
        # detection runs at a fixed working scale (<= DETECT_H rows) so that thresholds behave the
        # same for 720p and 1080p uploads; crops and all measurements stay at full resolution
        H0, W0 = fr.shape[:2]
        f = min(1.0, DETECT_H / H0)
        det = fr if f >= 1.0 else cv2.resize(fr, (int(round(W0 * f)), int(round(H0 * f))), interpolation=cv2.INTER_AREA)
        gray = cv2.cvtColor(det, cv2.COLOR_RGB2GRAY)
        boxes, mask = detect_lines(det, prev_gray)
        prev_gray = gray
        if f < 1.0:
            mask_full = mask
            boxes = [_upscale_box(b, f, W0, H0) for b in boxes]
        else:
            mask_full = mask
        cands = sorted(boxes, key=lambda b: -b[2] * b[3])
        used: set[int] = set()
        still: list[Track] = []
        for b in cands:
            s = _sig(mask_full, _downscale_box(b, f) if f < 1.0 else b)
            best, best_score = None, 0.0
            for tr in active:
                if tr.id in used:
                    continue
                iou = _iou(b, tr.last.bbox)
                if iou < 0.5:
                    continue
                corr = float(np.dot(s, tr.sig)) if tr.sig is not None and s.size == tr.sig.size else 0.0
                if corr < 0.55:
                    continue
                score = iou + corr
                if score > best_score:
                    best, best_score = tr, score
            pad = max(10, int(b[3]))
            crop, org = _crop_with_pad(fr, b, pad)
            smp = Sample(t=float(t), idx=idx, bbox=tuple(int(v) for v in b), crop=crop, origin=org)
            if best is None:
                best = Track(id=len(tracks) + 1)
                tracks.append(best)
            best.samples.append(smp)
            _thin_crops(best)
            best.sig = s if best.sig is None else _norm(0.7 * best.sig + 0.3 * s)
            used.add(best.id)
            still.append(best)
        # keep tracks alive for one missed sample
        active = still + [tr for tr in active if tr.id not in used and idx - tr.last.idx <= 1]
    info["n_samples"] = idx + 1
    return [tr for tr in tracks if len(tr.samples) >= 2], info


MAX_CROPS = 24


def _thin_crops(tr: Track) -> None:
    """Bound memory for long-lived lines (a title on screen for 60 s at 1080p): keep at most
    MAX_CROPS stored crops, evenly thinned; the geometry of every sample is kept."""
    kept = [i for i, sm in enumerate(tr.samples) if sm.crop is not None]
    if len(kept) <= MAX_CROPS:
        return
    for j, i in enumerate(kept[1:-1], 1):
        if j % 2 == 1:
            tr.samples[i].crop = None


DETECT_H = 960


def _upscale_box(b, f: float, W: int, H: int) -> tuple[int, int, int, int]:
    x, y, w, h = b
    x0, y0 = max(0, int(np.floor(x / f)) - 1), max(0, int(np.floor(y / f)) - 1)
    x1, y1 = min(W, int(np.ceil((x + w) / f)) + 1), min(H, int(np.ceil((y + h) / f)) + 1)
    return (x0, y0, x1 - x0, y1 - y0)


def _downscale_box(b, f: float) -> tuple[int, int, int, int]:
    x, y, w, h = b
    return (int(round(x * f)), int(round(y * f)), max(1, int(round(w * f))), max(1, int(round(h * f))))


def _norm(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n > 1e-6 else v


# ============================================================================= segmentation & style
def _otsu(vals: np.ndarray) -> float:
    import cv2
    v = np.clip(vals, 0, 255).astype(np.uint8).reshape(-1, 1)
    thr, _ = cv2.threshold(v, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return float(thr)


def segment_line(crop: np.ndarray, core: tuple[int, int, int, int]) -> dict | None:
    """Fill mask of a text line inside ``crop``; ``core`` = detected line box in crop coords."""
    import cv2

    Hc, Wc = crop.shape[:2]
    x, y, w, h = core
    L = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY).astype(np.float32)
    core_px = L[y:y + h, x:x + w]
    if core_px.size < 16:
        return None
    thr = _otsu(core_px)
    hi = L > thr
    border = np.zeros((Hc, Wc), bool)
    border[y:y + h, x] = border[y:y + h, x + w - 1] = True
    border[y, x:x + w] = border[y + h - 1, x:x + w] = True
    hi_b = hi[border].mean()
    inside = np.zeros((Hc, Wc), bool)
    inside[y:y + h, x:x + w] = True
    hi_c = hi[inside].mean()
    fill = hi if hi_b <= (1 - hi_b) else ~hi
    if (hi_b <= (1 - hi_b)) != (hi_c <= 0.5):
        pass  # polarity from the border rule wins; the core share is only informative
    fill &= inside
    n, lab, st, _ = cv2.connectedComponentsWithStats(fill.astype(np.uint8), 8)
    keep = np.zeros(n, bool)
    for i in range(1, n):
        cx, cy, cw, ch, area = st[i]
        if area < 3:
            continue
        touches = cx <= x or cy <= y or cx + cw >= x + w or cy + ch >= y + h
        if touches and (ch >= 0.9 * h or cw >= 0.9 * w):
            continue  # a frame/box edge, not a glyph
        keep[i] = True
    _drop_corner_background(crop, lab, st, keep, (x, y, w, h))
    fill = keep[lab]
    if fill.sum() < 10:
        return None
    ys, xs = np.nonzero(fill)
    return {"fill": fill, "fill_bbox": (int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1),
                                       int(ys.max() - ys.min() + 1)), "L": L}


CORNER_BG_CONTINUE_DIST = 40.0   # RGB distance: a piece whose colour continues past the line box is background
CORNER_BG_TEXT_DIST = 60.0       # ... unless its colour is within this of the interior glyphs' colour


def _drop_corner_background(crop, lab, st, keep, core) -> None:
    """Background pieces on the fill side of the threshold that are clipped by the line box: the detector's
    box encloses the whole ink, so a real glyph ends inside it, while a background piece continues past the
    box edge with the same colour.  mockloop: a red reaction word with a black outline over a wood floor --
    floor pieces in the box corners became a 14-17 % 'highlight' colour (#5A453A) of the fill."""
    x, y, w, h = core
    Hc, Wc = lab.shape
    idx = [i for i in range(1, len(keep)) if keep[i]]
    touch = {i: (st[i][0] <= x or st[i][1] <= y or st[i][0] + st[i][2] >= x + w or st[i][1] + st[i][3] >= y + h)
             for i in idx}
    interior = [i for i in idx if not touch[i]]
    if not interior:
        return
    # ... and only pieces that do not have the text colour (interior glyphs) -- a faint watermark's edge
    # glyphs continue into similar-looking footage too
    txt = np.median(crop[np.isin(lab, interior)].astype(float), axis=0)
    for i in idx:
        if not touch[i]:
            continue
        cx, cy, cw, ch, _a = st[i]
        m = lab == i
        if float(np.linalg.norm(np.median(crop[m].astype(float), axis=0) - txt)) <= CORNER_BG_TEXT_DIST:
            continue
        edge_in, edge_out = [], []
        if cx <= x and x - 2 >= 0:
            r = np.nonzero(m[:, x])[0]
            edge_in.append(crop[r, x]); edge_out.append(crop[r, x - 2])
        if cx + cw >= x + w and x + w + 1 < Wc:
            r = np.nonzero(m[:, x + w - 1])[0]
            edge_in.append(crop[r, x + w - 1]); edge_out.append(crop[r, x + w + 1])
        if cy <= y and y - 2 >= 0:
            c = np.nonzero(m[y, :])[0]
            edge_in.append(crop[y, c]); edge_out.append(crop[y - 2, c])
        if cy + ch >= y + h and y + h + 1 < Hc:
            c = np.nonzero(m[y + h - 1, :])[0]
            edge_in.append(crop[y + h - 1, c]); edge_out.append(crop[y + h + 1, c])
        if not edge_in:
            continue
        a = np.concatenate(edge_in).astype(float)
        b = np.concatenate(edge_out).astype(float)
        if len(a) < 3:
            continue
        # per pixel: does the piece's colour carry on 2 px outside the box?
        cont = np.linalg.norm(a - b, axis=1) < CORNER_BG_CONTINUE_DIST
        if cont.mean() >= 0.6:
            keep[i] = False


def measure_line(crop: np.ndarray, core: tuple[int, int, int, int]) -> dict | None:
    """Style of one text line (crop coords).  Returns None if no text-like fill was found."""
    import cv2

    seg = segment_line(crop, core)
    if seg is None:
        return None
    fill = seg["fill"]
    L = seg["L"]
    Hc, Wc = fill.shape
    fx, fy, fw, fh = seg["fill_bbox"]
    dist = cv2.distanceTransform((~fill).astype(np.uint8), cv2.DIST_L2, 3)
    ring12 = (dist > 0.5) & (dist <= 2.0)
    out_col = np.median(crop[ring12].astype(float), axis=0) if ring12.sum() >= 10 else None
    color, highlight, hl_share = _fill_colors(crop, fill, out_col)
    # ---- background box (checked first: a box must not be mistaken for a thick outline)
    box = _find_box(L, seg["fill_bbox"])
    if box.get("present") == "present":
        bx, by, bw, bh = box["bbox"]
        inbox = np.zeros_like(fill)
        inbox[by + 2:by + bh - 2, bx + 2:bx + bw - 2] = True
        far = inbox & (dist > 2.5)
    else:
        far = dist > max(6.0, 0.45 * fh)
    bg_col = np.median(crop[far].astype(float), axis=0) if far.sum() >= 20 else None
    dmax = int(max(3, min(0.5 * fh, 20)))
    # What the outline is judged against is the colour just OUTSIDE it (first plateau past the ring
    # profile's first step), not a far-field median: a dark semi-transparent box around the line (found or
    # not -- per-line box search misses the box of a multi-line block) otherwise reads as outline, and a
    # black outline on a near-black box (mockloop: #000 on #070C19) as "indistinguishable".
    step_thr, local_bg, edge_d = _outline_edge(crop, dist, out_col, dmax)
    bg_far = bg_col
    if local_bg is not None:
        bg_col = local_bg
    outline_px, outline_color, vis = None, None, "unmeasured"
    if out_col is not None and bg_col is not None:
        d_ob = float(np.linalg.norm(out_col - bg_col))
        if bg_far is not None:
            # the ring must differ from the far field too: a light label box (white text on pink) has a
            # "step" where the ring leaves the box, but its ring colour is the box colour
            d_ob = min(d_ob, float(np.linalg.norm(out_col - bg_far)))
        d_of = float(np.linalg.norm(out_col - np.asarray(color_rgb(color))))
        if d_ob < max(OUTLINE_MIN_STEP, step_thr):
            vis = "indistinguishable"   # ring looks like the local background: no visible outline to measure
        elif d_of < 30:
            vis = "none"
            outline_px = 0.0
        else:
            vis = "visible"
            total = 0.0
            ended = False
            for d in range(1, dmax + 1):
                ring = (dist > d - 1) & (dist <= d)
                if ring.sum() < 5:
                    break
                c = crop[ring].astype(float)
                to_o = np.linalg.norm(c - out_col, axis=1)
                to_b = np.linalg.norm(c - bg_col, axis=1)
                if bg_far is not None:
                    # a pixel must also be closer to the outline than to the far-field background: the
                    # local plateau is one colour, the background around a word often two (wall / floor)
                    to_b = np.minimum(to_b, np.linalg.norm(c - bg_far, axis=1))
                to_f = np.linalg.norm(c - np.asarray(color_rgb(color)), axis=1)
                frac = float(((to_o < to_b) & (to_o < to_f)).mean())
                if d > 1 and frac < 0.15:
                    ended = True
                    break
                total += frac
            if not ended and edge_d is None:
                # outline-coloured rings up to 0.5 x text height and no colour step: a dark region around the
                # text (an undetected box), not a measurable outline
                vis, outline_px = "unbounded", None
            else:
                outline_px = round(total, 2)
                outline_color = hexrgb(out_col)
    if box.get("present") == "present":
        # renderer contract (shortkit/edit/resolve.py): box = ink bbox INCLUDING the outline + pad per side.
        # _find_box measured from the glyph fill, so a visible outline is subtracted; an outline that is not
        # visible against the box cannot be separated from the pad and stays inside it (noted).
        box["pad_fill_x"], box["pad_fill_y"] = box["pad_x"], box["pad_y"]
        if vis == "visible" and outline_px:
            box["pad_x"] = int(max(0, round(box["pad_x"] - outline_px)))
            box["pad_y"] = int(max(0, round(box["pad_y"] - outline_px)))
        elif vis != "none":
            box["pad_note"] = "outline not separable from the box: pad measured from the glyph fill"
    # ink = fill + outline
    ink = fill.copy()
    if outline_px:
        ink |= dist <= outline_px + 0.5
    ys, xs = np.nonzero(ink)
    ink_bbox = (int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1))
    # ---- shadow
    shadow_px, shadow_color = _shadow(crop, ink, bg_col) if box.get("present") != "present" else (None, None)
    hang = ink_height(fill)
    return {"fill": fill, "ink": ink, "fill_bbox": seg["fill_bbox"], "ink_bbox": ink_bbox, "ink_h": hang,
            "color": color, "highlight_color": highlight, "highlight_share": hl_share,
            "outline_px": outline_px, "outline_color": outline_color, "outline_visibility": vis,
            # the colour right next to the glyphs: inside a box that is the box (its interior median), not the
            # plateau past the first ring step (which leaves a tight box -- the typography masks use this)
            "bg_color": (hexrgb(bg_far) if (box.get("present") == "present" and bg_far is not None)
                         else hexrgb(bg_col) if bg_col is not None else None),
            "shadow_px": shadow_px, "shadow_color": shadow_color, "box": box}


OUTLINE_MIN_STEP = 12.0     # RGB distance: smallest ring-colour step read as the outline's outer edge
OUTLINE_STEP_SIGMA = 4.0    # ... or this many robust noise sigmas of the outline ring, if larger


def _outline_edge(crop: np.ndarray, dist: np.ndarray, out_col, dmax: int):
    """Outer edge of the outline ring from the ring-median colour profile.

    Returns ``(step_threshold, local_background, edge_d)``: the first ring (d >= 2) whose median colour
    differs from the outline colour by more than ``max(OUTLINE_MIN_STEP, OUTLINE_STEP_SIGMA * noise)`` is
    the edge; the median of the next three rings is the local background.  ``edge_d`` None = no step.
    """
    if out_col is None:
        return OUTLINE_MIN_STEP, None, None
    core = (dist > 1.0) & (dist <= 2.0)
    if core.sum() < 10:
        return OUTLINE_MIN_STEP, None, None
    c = crop[core].astype(float)
    ref = np.median(c, axis=0)          # the ring right outside the glyph edge's antialiasing
    mad = np.median(np.abs(c - ref), axis=0) * 1.4826
    thr = max(OUTLINE_MIN_STEP, OUTLINE_STEP_SIGMA * float(np.linalg.norm(mad)))
    meds = []
    for d in range(1, dmax + 4):
        ring = (dist > d - 1) & (dist <= d)
        if ring.sum() < 5:
            break
        meds.append(np.median(crop[ring].astype(float), axis=0))
    # from d = 3 on, against the d = 2 ring (the 0.5-2 px ring colour can be a fill/outline blend, which
    # made the outline itself the "step" -- mockloop SYNTHmock05 reaction: 0.77 px for a 6 px outline)
    for i in range(2, len(meds)):
        if float(np.linalg.norm(meds[i] - ref)) > thr:
            nxt = meds[i + 1:i + 4]
            if not nxt:
                return thr, None, None
            return thr, np.median(np.array(nxt), axis=0), i + 1
    return thr, None, None


def color_rgb(hexstr: str) -> list[float]:
    h = hexstr.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def _fill_colors(crop: np.ndarray, fill: np.ndarray, edge_col) -> tuple[str, str | None, float]:
    """Main fill color and an optional second ("highlight") color.

    Only stroke-center pixels are used (inner distance >= 60 % of the thickest stroke), so
    anti-aliased edges do not pull the color toward the outline.  A second k-means cluster counts
    as a highlight only if it covers >= 12 % of those pixels, is > 60 away from the main color and
    is not a blend between the main color and the edge/outline color.
    """
    import cv2
    inner = cv2.distanceTransform(fill.astype(np.uint8), cv2.DIST_L2, 3)
    mx = float(inner.max())
    core = fill & (inner >= max(1.0, 0.6 * mx))
    if core.sum() < 12:
        core = fill
    px = crop[core].astype(float)
    if len(px) < 30:
        return hexrgb(np.median(px, axis=0)), None, 0.0
    data = px.astype(np.float32)
    crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 20, 1.0)
    _, lab, cent = cv2.kmeans(data, 2, None, crit, 3, cv2.KMEANS_PP_CENTERS)
    lab = lab.ravel()
    shares = np.bincount(lab, minlength=2) / len(lab)
    major = int(np.argmax(shares))
    minor = 1 - major
    main = np.median(px[lab == major], axis=0)
    if shares[minor] >= 0.12 and np.linalg.norm(cent[0] - cent[1]) > 60:
        hl = np.median(px[lab == minor], axis=0)
        if edge_col is None:
            return hexrgb(main), hexrgb(hl), round(float(shares[minor]), 3)
        e = np.asarray(edge_col, float)
        if _seg_dist(hl, main, e) <= 35:          # minority = anti-aliased blend of fill and edge
            return hexrgb(main), None, 0.0
        if _seg_dist(main, hl, e) <= 35:          # majority is the blend: the pure fill is the minority
            return hexrgb(hl), None, 0.0
        return hexrgb(main), hexrgb(hl), round(float(shares[minor]), 3)
    return hexrgb(np.median(px, axis=0)), None, 0.0


def _seg_dist(p, a, b) -> float:
    """Distance of color p from the segment a-b (a blend of a and b lies on it)."""
    p, a, b = (np.asarray(v, float) for v in (p, a, b))
    ab = b - a
    den = float(ab @ ab)
    t = 0.0 if den < 1e-9 else float(np.clip((p - a) @ ab / den, 0, 1))
    return float(np.linalg.norm(p - (a + t * ab)))


def _shadow(crop: np.ndarray, ink: np.ndarray, bg_col) -> tuple[float | None, str | None]:
    """Drop shadow = dark copy offset down-right (ASS convention). None when undeterminable."""
    import cv2
    if bg_col is None:
        return None, None
    if float(np.dot(np.asarray(bg_col, float), [0.2126, 0.7152, 0.0722])) < 50:
        return None, None       # a (dark) shadow on a dark background is invisible: cannot tell
    Hc, Wc = ink.shape
    near = cv2.dilate(ink.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    best = 0
    cols = []
    busy = 0
    for k in range(1, 11):
        pos = np.zeros_like(ink)
        pos[k:, k:] = ink[:Hc - k, :Wc - k]
        neg = np.zeros_like(ink)
        neg[:Hc - k, :Wc - k] = ink[k:, k:]
        sp, sn = pos & ~near, neg & ~near
        if sp.sum() < 10 or sn.sum() < 10:
            break
        cp = crop[sp].astype(float)
        cn = crop[sn].astype(float)
        fp = float((np.linalg.norm(cp - bg_col, axis=1) > 40).mean())
        fn = float((np.linalg.norm(cn - bg_col, axis=1) > 40).mean())
        if fn > 0.5:
            busy += 1
        if fp - fn > 0.35:
            best = k
            cols.append(np.median(cp, axis=0))
        elif k > best + 1:
            break
    if busy >= 2 and best == 0:
        return None, None      # background too busy to tell
    if best == 0:
        return 0.0, None
    return float(best), hexrgb(np.median(np.stack(cols), axis=0))


def _find_box(L: np.ndarray, ink_bbox, line_h: float | None = None) -> dict:
    """Rectangle behind the text: consistent luminance step on all four sides.  ``line_h`` = one text
    line's height when ``ink_bbox`` holds a multi-line block (default: the bbox height)."""
    Hc, Wc = L.shape
    x, y, w, h = ink_bbox
    x1, y1 = x + w - 1, y + h - 1
    lh = float(line_h or h)
    maxd = int(max(4, 1.3 * lh))
    mind = int(max(3, round(0.2 * lh)))   # glyph outlines are thinner than 0.2 h; box pads are wider
    steps: dict[str, list[tuple[int, float]]] = {"l": [], "r": [], "t": [], "b": []}
    med = np.median
    # per-row / per-column step, then the median: a real box edge crosses the whole side,
    # a glyph outline only a few rows of it
    for d in range(mind, maxd + 1):
        if x - d - 2 >= 0:
            steps["l"].append((d, float(med(L[y:y1 + 1, x - d:x - d + 2].mean(1) - L[y:y1 + 1, x - d - 2:x - d].mean(1)))))
        if x1 + d + 2 < Wc:
            steps["r"].append((d, float(med(L[y:y1 + 1, x1 + d - 1:x1 + d + 1].mean(1)
                                            - L[y:y1 + 1, x1 + d + 1:x1 + d + 3].mean(1)))))
        if y - d - 2 >= 0:
            steps["t"].append((d, float(med(L[y - d:y - d + 2, x:x1 + 1].mean(0) - L[y - d - 2:y - d, x:x1 + 1].mean(0)))))
        if y1 + d + 2 < Hc:
            steps["b"].append((d, float(med(L[y1 + d - 1:y1 + d + 1, x:x1 + 1].mean(0)
                                            - L[y1 + d + 1:y1 + d + 3, x:x1 + 1].mean(0)))))
    if any(not v for v in steps.values()):
        return {"present": "unmeasured", "note": "crop too small around the text"}
    res = {}
    for sign in (-1, 1):
        picks = {}
        for side, vals in steps.items():
            d, s = max(vals, key=lambda ds: sign * ds[1])
            picks[side] = (d, sign * s)
        res[sign] = picks
    sign = max((-1, 1), key=lambda sg: min(v[1] for v in res[sg].values()))
    picks = res[sign]
    if min(v[1] for v in picks.values()) < 15:
        return {"present": "absent"}
    dl, dr, dt, db = picks["l"][0], picks["r"][0], picks["t"][0], picks["b"][0]
    bx0, bx1, by0, by1 = x - dl, x1 + dr, y - dt, y1 + db
    inner = np.ones((by1 - by0 + 1, bx1 - bx0 + 1), bool)
    inner[max(0, y - by0 - 1):y1 - by0 + 2, max(0, x - bx0 - 1):x1 - bx0 + 2] = False
    return {"present": "present", "polarity": "dark" if sign < 0 else "light",
            "bbox": [int(bx0), int(by0), int(bx1 - bx0 + 1), int(by1 - by0 + 1)],
            "pad_x": int(round((dl + dr) / 2)), "pad_y": int(round((dt + db) / 2)),
            "contrast": round(min(v[1] for v in picks.values()), 1)}


# ============================================================================= OCR
def ocr_line(fill: np.ndarray, bbox) -> tuple[str, float]:
    """OCR one line from its fill mask; returns (text, mean word confidence).

    Tesseract is unstable on short lines (one or two syllables), so when the first attempt is
    weak the line is re-read at other scales and the most confident reading with letters wins.
    """
    best = ("", -1.0)
    best_hangul = ("", -1.0)
    for lang in ("kor+eng", "kor"):
        for target in (44.0, 32.0, 60.0):
            txt, conf = _ocr_once(fill, bbox, target, lang)
            if not LETTER_RE.search(txt):
                continue
            if conf > best[1]:
                best = (txt, conf)
            if HANGUL_RE.search(txt) and _hangul_share(txt) >= 0.5 and conf > best_hangul[1]:
                best_hangul = (txt, conf)
            if best_hangul[1] >= 75:
                return best_hangul
    # Korean captions: a Hangul reading of usable confidence beats a more 'confident' Latin misreading of
    # heavy glyphs (mockloop: '빤히' -> 'mts]' 50 vs '반히' 46.5)
    if best_hangul[1] >= 40:
        return best_hangul
    return best


def _ocr_once(fill: np.ndarray, bbox, target_h: float, lang: str = "kor+eng") -> tuple[str, float]:
    import os

    import cv2
    try:
        import pytesseract
    except ImportError:
        return "", -1.0
    # tesseract's OpenMP threads crawl on a shared, loaded CPU; one thread per call is faster
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    x, y, w, h = bbox
    if h < 5 or w > 60 * h:
        return "", -1.0          # not a text line (thin rule / specks)
    m = fill[max(0, y - 2):y + h + 2, max(0, x - 2):x + w + 2].astype(np.uint8)
    if m.size == 0:
        return "", -1.0
    # normalise the ink height to ~target_h in BOTH directions: tesseract misreads very large glyphs
    # (a 110 px heavy two-syllable reaction word read as 'HTS' at native size -- mockloop validation)
    scale = max(0.2, target_h / max(1, h))
    scale = min(scale, 3000.0 / max(1, m.shape[1]), 8.0)
    img = np.where(m > 0, 0, 255).astype(np.uint8)
    if scale != 1.0:
        img = cv2.resize(img, None, fx=scale, fy=scale,
                         interpolation=cv2.INTER_CUBIC if scale > 1.0 else cv2.INTER_AREA)
        if scale < 1.0:
            img = np.where(img >= 128, 255, 0).astype(np.uint8)
    img = cv2.copyMakeBorder(img, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    try:
        d = pytesseract.image_to_data(img, lang=lang, config="--psm 7",
                                      output_type=pytesseract.Output.DICT, timeout=30)
    except Exception:
        return "", -1.0
    words = []
    for i, txt in enumerate(d.get("text", [])):
        txt = (txt or "").strip()
        try:
            c = float(d["conf"][i])
        except (TypeError, ValueError, KeyError):
            c = -1.0
        if txt and c >= 0:
            words.append((txt, c, int(d["left"][i]), int(d["width"][i]), int(d["height"][i])))
    if not words:
        return "", -1.0
    words.sort(key=lambda w_: w_[2])
    # tesseract kor often splits one Korean word into syllables; a real space is a wide gap
    hmed = float(np.median([w_[4] for w_ in words])) or 1.0
    out = words[0][0]
    for prev, cur in zip(words, words[1:]):
        gap = cur[2] - (prev[2] + prev[3])
        out += (" " if gap >= 0.28 * hmed else "") + cur[0]
    return out, float(np.mean([w_[1] for w_ in words]))


# ============================================================================= per-track measurement
def _measure_track(tr: Track) -> dict | None:
    n = len(tr.samples)
    with_crop = [i for i, sm in enumerate(tr.samples) if sm.crop is not None]
    picks = sorted({min(with_crop, key=lambda i: abs(i - k)) for k in (n // 2, n // 4, (3 * n) // 4)})
    meas = []
    for i in picks:
        s = tr.samples[i]
        ox, oy = s.origin
        core = (s.bbox[0] - ox, s.bbox[1] - oy, s.bbox[2], s.bbox[3])
        m = measure_line(s.crop, core)
        if m is not None:
            m["sample"] = s
            meas.append(m)
    if not meas:
        return None
    mid = min(meas, key=lambda m: abs(m["sample"].idx - tr.samples[n // 2].idx))
    text, conf = ocr_line(mid["fill"], mid["fill_bbox"])
    if not LETTER_RE.search(text or "") or conf < 75:
        # weak reading: read the other samples too and keep the most confident reading
        for m in meas:
            if m is mid:
                continue
            t2, c2 = ocr_line(m["fill"], m["fill_bbox"])
            if LETTER_RE.search(t2 or "") and c2 > conf:
                text, conf, mid = t2, c2, m
    if not LETTER_RE.search(text or "") or conf < 40 or not plausible_text(text):
        return None
    s = mid["sample"]
    ox, oy = s.origin
    ib = mid["ink_bbox"]
    num = lambda k: _median([m[k] for m in meas])  # noqa: E731
    out = {
        "track": tr.id, "start_sample": tr.start, "end_sample": tr.end, "n_samples": n,
        "text": _clean_text(text), "ocr_conf": round(conf, 1),
        "bbox": [ib[0] + ox, ib[1] + oy, ib[2], ib[3]],
        "fill_bbox": [mid["fill_bbox"][0] + ox, mid["fill_bbox"][1] + oy, mid["fill_bbox"][2], mid["fill_bbox"][3]],
        "ink_h": num("ink_h"), "color": color_mode([m["color"] for m in meas])["mode"],
        "highlight_color": color_mode([m["highlight_color"] for m in meas])["mode"],
        "outline_px": num("outline_px"),
        "outline_color": color_mode([m["outline_color"] for m in meas])["mode"],
        "outline_visibility": _mode([m["outline_visibility"] for m in meas]),
        "bg_color": mid["bg_color"],
        "shadow_px": num("shadow_px"), "shadow_color": color_mode([m["shadow_color"] for m in meas])["mode"],
        "box": _merge_box([m["box"] for m in meas], (ox, oy), mid),
        "t_rep": s.t, "_rep": mid, "_track": tr,
    }
    out["hangul_share"] = _hangul_share(out["text"])
    return out


def _merge_box(boxes: list[dict], origin, mid) -> dict:
    pres = [b.get("present") for b in boxes]
    state = tri_state([p == "present" for p in pres if p in ("present", "absent")])
    if state != "present" or sum(p == "present" for p in pres) * 2 < len(pres):
        return {"present": "absent" if state in ("absent", "present") else "unmeasured"}
    pb = [b for b in boxes if b.get("present") == "present"]
    ref = mid["box"] if mid["box"].get("present") == "present" else pb[0]
    bx = list(ref["bbox"])
    return {"present": "present", "polarity": ref.get("polarity"),
            "bbox": [bx[0] + origin[0], bx[1] + origin[1], bx[2], bx[3]],
            "pad_x": _median([b["pad_x"] for b in pb]), "pad_y": _median([b["pad_y"] for b in pb]),
            "pad_fill_x": _median([b.get("pad_fill_x") for b in pb]),
            "pad_fill_y": _median([b.get("pad_fill_y") for b in pb]),
            **({"pad_note": ref["pad_note"]} if ref.get("pad_note") else {}),
            "color": None, "alpha": None}


def plausible_text(t: str) -> bool:
    """A caption line has Hangul (syllables or jamo), or >= 3 Latin letters/digits, and letters
    make up at least half of its visible characters (rejects OCR of textures such as '|1')."""
    vis = [c for c in (t or "") if not c.isspace()]
    if not vis:
        return False
    hangul = sum(bool(re.match(r"[\uac00-\ud7a3\u3131-\u318e]", c)) for c in vis)
    alnum = sum(c.isascii() and c.isalnum() for c in vis)
    if hangul == 0 and alnum < 3:
        return False
    return (hangul + alnum) >= 0.5 * len(vis)


def _clean_text(t: str) -> str:
    t = re.sub(r"\s+", " ", t or "").strip()
    return t


def _hangul_share(t: str) -> float:
    letters = [c for c in t if not c.isspace()]
    if not letters:
        return 0.0
    return sum(bool(HANGUL_RE.match(c)) for c in letters) / len(letters)


def _median(vals):
    v = [float(x) for x in vals if x is not None]
    return round(float(np.median(v)), 3) if v else None


def _mode(vals):
    v = [x for x in vals if x is not None]
    if not v:
        return None
    return max(set(v), key=v.count)


# ============================================================================= grouping into items
def _letters(t: str) -> str:
    return re.sub(r"[^0-9A-Za-z\uac00-\ud7a3]", "", t or "")


def merge_split_lines(lines: list[dict], sample_dt: float) -> list[dict]:
    """Re-join ONE on-screen line whose track broke in two back-to-back tracks (part of the line lost its
    'stable gradient' for a while, e.g. a semi-transparent label box over moving footage: mockloop saw
    '파란 셔츠 남성' 6.4-8.4 s + '셔츠 남성' 8.4-9.6 s).  Joined only when the tracks touch in time (<= 1.5
    samples apart), sit on the same row (vertical overlap >= 70 % of the lower one), overlap horizontally
    (>= 50 % of the narrower), have the same ink height (+-20 %) and fill colour (RGB <= 40), and the
    letters of one reading are contained in the other.  The merged line keeps the longer reading and its
    measurement, the union box and the full time span."""
    from .common import color_dist

    out: list[dict] = []
    for ln in sorted(lines, key=lambda l: l["start_sample"]):
        for pv in out:
            if not (0 <= ln["start_sample"] - pv["end_sample"] <= 1.5 * sample_dt + 1e-6):
                continue
            (ax, ay, aw, ah), (bx, by, bw, bh) = pv["bbox"], ln["bbox"]
            vov = min(ay + ah, by + bh) - max(ay, by)
            hov = min(ax + aw, bx + bw) - max(ax, bx)
            if vov < 0.7 * min(ah, bh) or hov < 0.5 * min(aw, bw):
                continue
            ha, hb = pv.get("ink_h") or 0, ln.get("ink_h") or 0
            if not ha or not hb or max(ha, hb) > 1.2 * min(ha, hb):
                continue
            if not (pv.get("color") and ln.get("color")) or color_dist(pv["color"], ln["color"]) > 40:
                continue
            ta, tb_ = _letters(pv["text"]), _letters(ln["text"])
            if not ta or not tb_ or (ta not in tb_ and tb_ not in ta):
                continue
            keep, other = (pv, ln) if len(ta) >= len(tb_) else (ln, pv)
            merged = dict(keep)
            x0, y0 = min(ax, bx), min(ay, by)
            x1, y1 = max(ax + aw, bx + bw), max(ay + ah, by + bh)
            merged.update({"bbox": [x0, y0, x1 - x0, y1 - y0], "start_sample": min(pv["start_sample"], ln["start_sample"]),
                           "end_sample": max(pv["end_sample"], ln["end_sample"]),
                           "n_samples": pv.get("n_samples", 0) + ln.get("n_samples", 0),
                           "merged_tracks": [pv.get("track"), ln.get("track")],
                           "merged_texts": [pv["text"], ln["text"]]})
            out[out.index(pv)] = merged
            break
        else:
            out.append(ln)
    return out


def group_items(lines: list[dict], sample_dt: float) -> list[list[dict]]:
    lines = sorted(lines, key=lambda l: (l["start_sample"], l["bbox"][1]))
    items: list[list[dict]] = []
    for ln in lines:
        x, y, w, h = ln["bbox"]
        placed = False
        for it in items:
            ref = it[0]
            if abs(ref["start_sample"] - ln["start_sample"]) > 1.5 * sample_dt + 1e-6 or \
                    abs(ref["end_sample"] - ln["end_sample"]) > 1.5 * sample_dt + 1e-6:
                continue
            ux0 = min(l["bbox"][0] for l in it)
            ux1 = max(l["bbox"][0] + l["bbox"][2] for l in it)
            uy0 = min(l["bbox"][1] for l in it)
            uy1 = max(l["bbox"][1] + l["bbox"][3] for l in it)
            gap = max(y - uy1, uy0 - (y + h))
            hov = min(ux1, x + w) - max(ux0, x)
            mh = float(np.median([l["bbox"][3] for l in it]))
            if gap <= 0.8 * max(h, mh) and hov > 0 and max(h, mh) <= 1.6 * min(h, mh):
                it.append(ln)
                placed = True
                break
        if not placed:
            items.append([ln])
    for it in items:
        it.sort(key=lambda l: l["bbox"][1])
    return items


# ============================================================================= native refinement
FILL_HINT_DIST = 60.0   # RGB distance to the measured fill colour for a pixel to stay in the rest fill mask


def _text_masks(rest: np.ndarray, lines_rel: list[tuple[int, int, int, int]], fill_hint=None) -> dict | None:
    """Fill / edge-ring masks and colors of an item at rest inside a native crop.

    ``fill_hint`` = the fill colour measured on the sampled lines: the luminance split of
    ``segment_line`` also takes background brighter than the text (a red word over a beige wall --
    mockloop), and background pixels in the mask 'match the rest appearance' before the text exists,
    so no text-free frame was found and the timing/motion stayed unmeasured.
    """
    import cv2
    H, W = rest.shape[:2]
    fill = np.zeros((H, W), bool)
    for (x, y, w, h) in lines_rel:
        x0, y0 = max(0, x - 2), max(0, y - 2)
        seg = segment_line(rest, (x0, y0, min(w + 4, W - x0), min(h + 4, H - y0)))
        if seg is not None:
            fill |= seg["fill"]
    if fill_hint is not None and fill.sum() >= 10:
        near = np.linalg.norm(rest.astype(float) - np.asarray(fill_hint, float), axis=2) < FILL_HINT_DIST
        if (fill & near).sum() >= 0.3 * fill.sum():
            fill &= near
    if fill.sum() < 10:
        return None
    dist = cv2.distanceTransform((~fill).astype(np.uint8), cv2.DIST_L2, 3)
    ring = (dist > 0.5) & (dist <= 2.0)
    inner = cv2.distanceTransform(fill.astype(np.uint8), cv2.DIST_L2, 3)
    fcore = fill & (inner >= 1.0)
    if fcore.sum() < 10:
        fcore = fill
    return {"fill": fcore, "ring": ring, "K": fcore | ring,
            "fill_col": np.median(rest[fcore].astype(float), axis=0),
            "edge_col": np.median(rest[ring].astype(float), axis=0) if ring.any() else None}


def _match_rest(F: np.ndarray, Rf: np.ndarray, tm: dict) -> float:
    """Share of the rest appearance reproduced at the rest position (min of fill and edge ring)."""
    d = np.abs(F.astype(np.int16) - Rf.astype(np.int16)).max(axis=2) < 40
    return float(min(d[tm["fill"]].mean(), d[tm["ring"]].mean() if tm["ring"].any() else 1.0))


def _text_like(F: np.ndarray, tm: dict) -> np.ndarray:
    """Pixels of the fill color that sit next to edge(outline/box)-colored pixels."""
    import cv2
    fc = np.linalg.norm(F.astype(float) - tm["fill_col"], axis=2) < 50
    if tm["edge_col"] is None:
        return fc
    ec = np.linalg.norm(F.astype(float) - tm["edge_col"], axis=2) < 50
    ec = cv2.dilate(ec.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    return fc & ec


def _bbox_of(mask: np.ndarray):
    ys, xs = np.nonzero(mask)
    if len(xs) < 8:
        return None
    x0, x1 = np.percentile(xs, [1, 99])
    y0, y1 = np.percentile(ys, [1, 99])
    return (float(x0), float(y0), float(x1 - x0 + 1), float(y1 - y0 + 1))


def _alpha_proj(F, B, Rf, K) -> float:
    a = (F.astype(float) - B.astype(float))[K]
    r = (Rf.astype(float) - B.astype(float))[K]
    den = float((r * r).sum())
    return float((a * r).sum() / den) if den > 1e-6 else 0.0


def analyze_transition(frames: list[tuple[float, np.ndarray]], tm: dict, direction: str, fps: float) -> dict:
    """Motion of an item entering (``in``: frames end at the rest frame) or leaving (``out``: frames
    start at the rest frame).

    background frame B = latest frame (walking away from rest) where the text is absent: it matches
    < 10 % of the rest appearance, holds < 10 % of the rest's text-like pixels, and differs from
    rest over the text footprint almost as much as the most different such frame.
    """
    if not frames:
        return {"type": "unmeasured", "note": "no frames"}
    seq = frames if direction == "in" else list(reversed(frames))
    ridx = len(seq) - 1
    Rt, Rf = seq[ridx]
    E_rest = int(_text_like(Rf, tm).sum())
    K = tm["K"]
    stats = []
    for t, F in seq:
        stats.append({"t": t, "p": _match_rest(F, Rf, tm), "E": int(_text_like(F, tm).sum()),
                      "D": float(np.abs(F.astype(np.int16) - Rf.astype(np.int16)).max(axis=2)[K].mean())})
    # footage behind the text can contain text-like color pairs: measure E above its window minimum
    E_base = min(st_["E"] for st_ in stats[:ridx]) if ridx else 0
    cand = [i for i in range(ridx) if stats[i]["p"] <= 0.1
            and stats[i]["E"] <= E_base + 0.1 * max(E_rest - E_base, 1)]
    if not cand:
        return {"type": "unmeasured", "note": "no frame without the text inside the analysed window"}
    # nearest absent frame to rest, then outward while it keeps getting more different from rest
    # (a fade's faint frames look absent too); never walk into unrelated changes (flash, far frames)
    cset = set(cand)
    b_i = max(cand)
    limit = b_i - int(round(0.5 * fps))
    while (b_i - 1) in cset and b_i - 1 >= limit and stats[b_i - 1]["D"] > 1.05 * stats[b_i]["D"]:
        b_i -= 1
    Bt, B = seq[b_i]
    traj = []
    for i in range(b_i + 1, ridx + 1):
        t, F = seq[i]
        tl = _text_like(F, tm)
        traj.append({"t": t, "p": stats[i]["p"], "E": stats[i]["E"], "alpha": _alpha_proj(F, B, Rf, K),
                     "bbox": _bbox_of(tl) if tl.sum() >= 0.1 * max(E_rest, 1) else None})
    vis = [i for i, q in enumerate(traj) if q["alpha"] >= 0.08 or q["E"] - E_base >= 0.1 * max(E_rest - E_base, 1)]
    if not vis:
        return {"type": "unmeasured", "note": "no visible transition frame"}
    first = vis[0]
    rest_from = len(traj) - 1
    for i in range(len(traj) - 1, first - 1, -1):
        if traj[i]["p"] >= 0.85:
            rest_from = i
        else:
            break
    rbox = _bbox_of(_text_like(Rf, tm))
    q0 = traj[first]
    s0, off = None, 0.0
    if rbox is not None and q0["bbox"] is not None:
        rw, rh = rbox[2], rbox[3]
        s0 = math.sqrt(max(q0["bbox"][2], 1) * max(q0["bbox"][3], 1) / (rw * rh))
        off = math.hypot(q0["bbox"][0] + q0["bbox"][2] / 2 - (rbox[0] + rw / 2),
                         q0["bbox"][1] + q0["bbox"][3] / 2 - (rbox[1] + rh / 2))
    rh = rbox[3] if rbox else 10.0
    t_first = q0["t"]
    t_rest = traj[rest_from]["t"]
    dur = abs(t_rest - t_first)
    out: dict[str, Any] = {"t_edge": t_first, "t_rest": t_rest, "frames": len(traj),
                           "alpha_first": round(q0["alpha"], 3),
                           "scale_first": round(s0, 3) if s0 is not None else None,
                           "offset_first_px": round(off, 1), "background_frame_t": Bt}
    key_scale = "scale_from" if direction == "in" else "scale_to"
    if rest_from <= first:
        out.update({"type": "none", "dur_s": 0.0})
    elif s0 is not None and abs(s0 - 1) >= 0.06:
        out.update({"type": "pop", "dur_s": round(dur, 3), key_scale: round(s0, 3)})
    elif off >= max(3.0, 0.1 * rh):
        out.update({"type": "slide", "dur_s": round(dur, 3), "offset_px": round(off, 1)})
    elif q0["alpha"] <= 0.75:
        ramp = [(q["t"], q["alpha"]) for q in traj[first:rest_from + 1]]
        t_zero = t_first - (1.0 / fps if direction == "in" else -1.0 / fps)
        if len(ramp) >= 2:
            ts = np.array([r[0] for r in ramp])
            als = np.array([r[1] for r in ramp])
            slope, icpt = np.polyfit(ts, als, 1)
            if abs(slope) > 1e-6:
                tz = float(-icpt / slope)
                if abs(tz - t_first) <= 1.5 / fps:
                    t_zero = tz
        out.update({"type": "fade", "dur_s": round(abs(t_rest - t_zero), 3), "t_zero": round(t_zero, 4)})
    else:
        out.update({"type": "none", "dur_s": 0.0, "note": "short partial transition not classified"})
    return out


def refine_item(video: Path, item: dict, fps_native: float, sample_dt: float, W: int, H: int,
                cuts: list[float] | None = None) -> dict:
    """Exact timing, motion in/out and box alpha from native frames around the item edges."""
    x, y, w, h = item["bbox"]
    ex, ey = int(0.35 * w + 0.6 * h), int(0.9 * h)
    R = {"x": max(0, x - ex), "y": max(0, y - ey)}
    R["w"] = min(W, x + w + ex) - R["x"]
    R["h"] = min(H, y + h + ey) - R["y"]
    R = even_crop(R, W, H)
    back = max(0.8, 2.5 * sample_dt)
    duration = item.get("_duration") or 0.0
    t_a0 = max(0.0, item["start_sample"] - back)
    t_b1 = item["end_sample"] + back
    # never look across a shot boundary: the background changes there
    for c in cuts or []:
        if t_a0 < c <= item["start_sample"] - 1.0 / fps_native:
            t_a0 = c
        if item["end_sample"] + 1.0 / fps_native <= c < t_b1:
            t_b1 = c
    seg_in = read_segment(video, t_a0, item["start_sample"] + 0.5 / fps_native, fps_native, crop=R)
    seg_out = read_segment(video, item["end_sample"], t_b1, fps_native, crop=R)
    lines_rel = [(l["bbox"][0] - R["x"], l["bbox"][1] - R["y"], l["bbox"][2], l["bbox"][3]) for l in item["lines"]]
    res: dict[str, Any] = {"region": R}
    cols = [l.get("color") for l in item["lines"] if l.get("color")]
    hint = color_rgb(color_mode(cols)["mode"]) if cols and color_mode(cols)["mode"] else None
    tm_in = _text_masks(seg_in[-1][1], lines_rel, hint) if seg_in else None
    tm_out = _text_masks(seg_out[0][1], lines_rel, hint) if seg_out else None
    # near the ends of the video, check the actual first / last frame instead of assuming
    at_video_start = bool(item["start_sample"] <= sample_dt + 1e-6 and seg_in and tm_in
                          and seg_in[0][0] <= 0.5 / fps_native
                          and _match_rest(seg_in[0][1], seg_in[-1][1], tm_in) >= 0.85)
    at_video_end = bool(item["end_sample"] >= duration - sample_dt - 1.0 / fps_native - 1e-6 and seg_out and tm_out
                        and seg_out[-1][0] >= duration - 1.5 / fps_native
                        and _match_rest(seg_out[-1][1], seg_out[0][1], tm_out) >= 0.85)
    if at_video_start:
        mi = {"type": "unmeasured", "note": "text already on screen at the first frame (motion_in not observable)"}
        res["start"] = 0.0
    else:
        mi = analyze_transition(seg_in, tm_in, "in", fps_native) if (seg_in and tm_in) else \
            {"type": "unmeasured", "note": "text mask not found at rest"}
        if mi.get("type") == "unmeasured" and seg_in and tm_in and t_a0 in (cuts or []) \
                and _match_rest(seg_in[0][1], seg_in[-1][1], tm_in) >= 0.85:
            # fully there on the first frame of the shot: it comes in with the cut
            mi = {"type": "none", "dur_s": 0.0, "t_edge": seg_in[0][0], "note": "컷과 함께 완전한 상태로 등장"}
        res["start"] = round(float(mi.get("t_zero", mi.get("t_edge", item["start_sample"]))), 3)
    if at_video_end:
        mo = {"type": "unmeasured", "note": "text still on screen at the last frame (motion_out not observable)"}
        res["end"] = round(duration, 3)
    else:
        mo = analyze_transition(seg_out, tm_out, "out", fps_native) if (seg_out and tm_out) else \
            {"type": "unmeasured", "note": "text mask not found at rest"}
        if mo.get("type") == "unmeasured" and seg_out and tm_out and t_b1 in (cuts or []) \
                and _match_rest(seg_out[-1][1], seg_out[0][1], tm_out) >= 0.85:
            mo = {"type": "none", "dur_s": 0.0, "t_edge": seg_out[-1][0], "note": "컷과 함께 사라짐"}
        if "t_zero" in mo:
            res["end"] = round(float(mo["t_zero"]), 3)
        elif mo.get("t_edge") is not None:
            res["end"] = round(float(mo["t_edge"]) + 1.0 / fps_native, 3)   # exclusive end
        else:
            res["end"] = round(item["end_sample"] + sample_dt, 3)
            mo.setdefault("note", "end time only at sampling precision")
    res["motion_in"], res["motion_out"] = mi, mo
    res["_seg_in"], res["_seg_out"] = seg_in, seg_out
    return res


def _block_box(ref: dict, grp: list[dict], style: dict) -> dict | None:
    """One box around a multi-line block.  The per-line search misses it (its edges lie beyond the other
    line, out of the 1.3 x line-height range -- mockloop: 2-line situation captions reported no box and
    the safe-margin bottom lost the box pad), so the box is searched around the union of the lines'
    glyph fills in the rest frame, with the one-line step range."""
    import cv2

    seg = ref.get("_seg_in") or []
    fbs = [l.get("fill_bbox") for l in grp]
    if not seg or any(f is None for f in fbs):
        return None
    R = ref["region"]
    rest = seg[-1][1]
    x0 = min(f[0] for f in fbs) - R["x"]
    y0 = min(f[1] for f in fbs) - R["y"]
    x1 = max(f[0] + f[2] for f in fbs) - R["x"]
    y1 = max(f[1] + f[3] for f in fbs) - R["y"]
    if x0 < 0 or y0 < 0 or x1 > rest.shape[1] or y1 > rest.shape[0]:
        return None
    L = cv2.cvtColor(rest, cv2.COLOR_RGB2GRAY).astype(np.float32)
    box = _find_box(L, (x0, y0, x1 - x0, y1 - y0), line_h=float(np.median([f[3] for f in fbs])))
    if box.get("present") != "present":
        return None
    box["pad_fill_x"], box["pad_fill_y"] = box["pad_x"], box["pad_y"]
    op = style.get("outline_px")
    if style.get("outline_visibility") == "visible" and op:
        box["pad_x"] = int(max(0, round(box["pad_x"] - op)))
        box["pad_y"] = int(max(0, round(box["pad_y"] - op)))
    elif style.get("outline_visibility") != "none":
        box["pad_note"] = "outline not separable from the box: pad measured from the glyph fill"
    bx, by, bw, bh = box["bbox"]
    box["bbox"] = [bx + R["x"], by + R["y"], bw, bh]
    box.update({"color": None, "alpha": None, "source": "block (multi-line)"})
    return box


def box_alpha(item: dict, ref: dict) -> dict:
    """alpha / color of a background box by regression I = a*C + (1-a)*B on static pixels."""
    box = item["style"]["box"]
    if box.get("present") != "present":
        return box
    seg_in, seg_out = ref.get("_seg_in") or [], ref.get("_seg_out") or []
    mi, mo = ref.get("motion_in") or {}, ref.get("motion_out") or {}
    R = ref["region"]
    bx, by, bw, bh = box["bbox"]
    x0, y0 = bx - R["x"], by - R["y"]
    if x0 < 0 or y0 < 0 or not seg_in:
        box["alpha_note"] = "box outside the analysed window"
        return box
    Bt = mi.get("background_frame_t")
    B = next((f for t, f in seg_in if Bt is not None and abs(t - Bt) < 1e-6), None)
    A = None
    if seg_out and mo.get("background_frame_t") is not None:
        A = next((f for t, f in seg_out if abs(t - mo["background_frame_t"]) < 1e-6), None)
    rest = seg_in[-1][1]
    if B is None:
        box["alpha_note"] = "no frame before the box appears"
        return box
    sl = (slice(y0, y0 + bh), slice(x0, x0 + bw))
    Bb = B[sl].astype(float)
    Ib = rest[sl].astype(float)
    if Bb.shape != Ib.shape or Bb.size == 0:
        box["alpha_note"] = "box crop mismatch"
        return box
    mask = np.ones(Bb.shape[:2], bool)
    tx, ty, tw, th = item["bbox"]
    mask[max(0, ty - by - 2):ty - by + th + 2, max(0, tx - bx - 2):tx - bx + tw + 2] = False
    mask[:2, :] = mask[-2:, :] = False
    mask[:, :2] = mask[:, -2:] = False
    if A is not None and A.shape == B.shape:
        static = np.abs(A[sl].astype(float) - Bb).max(axis=2) < 10
        mask &= static
    if mask.sum() < 60:
        box["alpha_note"] = "too few static background pixels under the box"
        return box
    b = Bb[mask]
    i = Ib[mask]
    if float(b.std(axis=0).mean()) < 6:
        box["alpha_note"] = "background under the box is flat: alpha and color not separable"
        box["color_observed"] = hexrgb(np.median(i, axis=0))
        return box
    slopes, icpts = [], []
    for c in range(3):
        if b[:, c].std() < 3:
            continue
        s, k = np.polyfit(b[:, c], i[:, c], 1)
        slopes.append(s)
        icpts.append((c, k))
    if not slopes:
        box["alpha_note"] = "background channels flat"
        return box
    a = float(np.clip(1.0 - np.median(slopes), 0.0, 1.0))
    box["alpha"] = round(a, 3)
    if a > 0.05:
        col = [0.0, 0.0, 0.0]
        for c, k in icpts:
            col[c] = k / a
        box["color"] = hexrgb(col)
    box["color_observed"] = hexrgb(np.median(i, axis=0))
    box["alpha_method"] = "regression on static background pixels (frame before appearance vs rest)"
    return box


# ============================================================================= roles
def _norm_text(t: str) -> str:
    return re.sub(r"[^0-9a-z\uac00-\ud7a3]", "", (t or "").lower())


def assign_roles(items: list[dict], duration: float, H: int, speech: list[tuple[float, float]] | None,
                 identity_texts: list[str] | None = None) -> None:
    for it in items:
        it["role"], it["role_reason"] = "unknown", ""
    # the reference channel's own name/logo text is an identity mark, never a caption style sample
    marks = [m for m in (_norm_text(x) for x in identity_texts or []) if len(m) >= 3]
    for it in items:
        nt = _norm_text(it["text"])
        if marks and any(m in nt for m in marks):
            it["role"] = "identity_mark"
            it["role_reason"] = "채널 고유 식별 문구(identity_exclusions.forbidden_text)와 일치 → 자막 스타일 측정에서 제외"
    items = [it for it in items if it["role"] == "unknown"]
    if not items:
        return

    def dur(it):
        return it["end"] - it["start"]

    persistent = [it for it in items if dur(it) >= 0.6 * duration]
    title = None
    tops = [it for it in persistent if (it["bbox"][1] + it["bbox"][3] / 2) < 0.4 * H]
    if tops:
        title = max(tops, key=lambda it: (it["style"].get("ink_h") or 0, -it["bbox"][1]))
        title["role"] = "title"
        title["role_reason"] = f"화면의 {100 * dur(title) / duration:.0f}% 동안 고정, 상단(중심 y<0.4H), 가장 큰 글자"
        tb = title["bbox"]
        for it in items:
            if it is title or it["role"] != "unknown":
                continue
            below = it["bbox"][1] - (tb[1] + tb[3])
            hov = min(tb[0] + tb[2], it["bbox"][0] + it["bbox"][2]) - max(tb[0], it["bbox"][0])
            smaller = (it["style"].get("ink_h") or 1e9) < (title["style"].get("ink_h") or 0)
            if -0.2 * tb[3] <= below <= 2.5 * tb[3] and hov > 0 and smaller and \
                    (dur(it) >= 0.6 * duration or it["start"] <= title["start"] + 2.0):
                it["role"] = "description"
                it["role_reason"] = "제목 바로 아래(제목 높이 2.5배 이내), 제목보다 작은 글자"
    timed = [it for it in items if it["role"] == "unknown"]
    sizes = [it["style"].get("ink_h") for it in timed if it["style"].get("ink_h")]
    med = float(np.median(sizes)) if sizes else None
    for it in timed:
        st = it["style"]
        chars = len(re.sub(r"[\s\W_]", "", it["text"]))
        big = med is not None and st.get("ink_h") and st["ink_h"] >= 1.15 * med
        small = med is not None and st.get("ink_h") and st["ink_h"] <= 0.85 * med
        if st["box"].get("present") == "present" and (small or med is None) and 0 < chars <= 10:
            it["role"] = "speaker"
            it["role_reason"] = "배경 박스가 있는 작은 짧은 라벨(인물 근접 여부는 얼굴 검출기 없음 → 못 잼)"
        elif big and 0 < chars <= 6 and st.get("color") and saturation(st["color"]) >= 0.35:
            it["role"] = "reaction"
            it["role_reason"] = f"짧은({chars}자) 큰 글자(중앙값의 {st['ink_h'] / med:.2f}배), 채도 높은 색"
    rest = [it for it in items if it["role"] == "unknown"]
    if not rest:
        return
    # main caption band = the vertical cluster holding most timed items
    ys = sorted((it["bbox"][1] + it["bbox"][3] / 2, i) for i, it in enumerate(rest))
    tol = 0.06 * H
    best: list[int] = []
    for cy, i in ys:
        cl = [j for (cy2, j) in ys if abs(cy2 - cy) <= tol]
        if len(cl) > len(best):
            best = cl
    band = [rest[j] for j in best]
    band_y = float(np.median([it["bbox"][1] + it["bbox"][3] / 2 for it in band]))
    for it in band:
        quoted = any(c in QUOTE_CHARS for c in it["text"])
        spk = False
        if speech:
            ov = sum(max(0.0, min(it["end"], b) - max(it["start"], a)) for a, b in speech)
            spk = ov >= 0.5 * max(1e-6, dur(it))
        if quoted or spk:
            it["role"] = "dialogue"
            it["role_reason"] = "자막 띠 안, " + ("따옴표" if quoted else "") + \
                (" + " if quoted and spk else "") + ("원음 말소리 구간과 겹침" if spk else "")
        else:
            it["role"] = "situation"
            it["role_reason"] = f"주 자막 띠(y≈{band_y:.0f}) 안의 시간제 자막, 따옴표·말소리 겹침 없음"
    # a band item colored like the quoted items (and unlike the other band items) is dialogue too
    dcols = [it["style"]["color"] for it in band if it["role"] == "dialogue" and it["style"].get("color")]
    scols = [it["style"]["color"] for it in band if it["role"] == "situation" and it["style"].get("color")]
    if dcols and scols:
        dmode = color_mode(dcols)["mode"]
        for it in band:
            if it["role"] == "situation" and it["style"].get("color") and \
                    color_dist(it["style"]["color"], dmode) < 30 and \
                    color_mode(scols)["mode"] and color_dist(color_mode(scols)["mode"], dmode) > 60:
                if sum(color_dist(c, dmode) < 30 for c in scols) * 2 < len(scols):
                    it["role"] = "dialogue"
                    it["role_reason"] = "자막 띠 안, 따옴표 대사와 같은 글자색(상황 자막 색과 다름)"


# ============================================================================= main entry
def analyze(video: str | Path, video_id: str, preset: str | None = None, fps: float = DEFAULT_FPS,
            region: dict | None = None, out_dir: Path | None = None, save_frames: bool = True,
            role_fonts: dict[str, str] | None = None, max_seconds: float | None = None,
            identity_texts: list[str] | None = None) -> tuple[dict, dict]:
    """Analyze one video; writes captions.json + layout.json (+ evidence frames) into out_dir.

    ``identity_texts``: the reference channel's own name variants (preset
    ``identity_exclusions.forbidden_text``); matching lines get role ``identity_mark`` and are
    excluded from the role style summaries."""
    video = Path(video)
    info = probe(video)
    W, H = int(info.width), int(info.height)
    fps_native = float(info.fps or 30.0)
    duration = float(info.duration) if max_seconds is None else min(float(info.duration), max_seconds)
    if out_dir is None:
        out_dir = analysis_dir(preset, video_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    if region is None:
        region = detect_video_region(video, max_seconds=max_seconds)
    sample_dt = 1.0 / fps
    tracks, tinfo = track_lines(video, fps, max_seconds=max_seconds)
    lines = []
    dropped = 0
    for tr in tracks:
        m = _measure_track(tr)
        if m is None:
            dropped += 1
            continue
        lines.append(m)
    lines = merge_split_lines(lines, sample_dt)
    groups = group_items(lines, sample_dt)
    speech = _speech_ranges(out_dir)
    shots = read_json(out_dir / "shots.json") or {}
    cut_times = [float(c["t"]) for c in shots.get("cuts") or [] if c.get("t") is not None]
    items: list[dict] = []
    for gi, grp in enumerate(groups):
        x0 = min(l["bbox"][0] for l in grp)
        y0 = min(l["bbox"][1] for l in grp)
        x1 = max(l["bbox"][0] + l["bbox"][2] for l in grp)
        y1 = max(l["bbox"][1] + l["bbox"][3] for l in grp)
        it = {"id": f"c{gi + 1:02d}", "lines": grp, "bbox": [x0, y0, x1 - x0, y1 - y0],
              "start_sample": min(l["start_sample"] for l in grp), "end_sample": max(l["end_sample"] for l in grp),
              "_duration": duration}
        ref = refine_item(video, it, fps_native, sample_dt, W, H, cuts=cut_times)
        it["start"], it["end"] = ref["start"], ref["end"]
        it["text"] = "\n".join(l["text"] for l in grp)
        it["style"] = _item_style(grp)
        if len(grp) >= 2 and it["style"]["box"].get("present") != "present":
            blk = _block_box(ref, grp, it["style"])
            if blk is not None:
                it["style"]["box"] = blk
        it["_ref"] = ref
        items.append(it)
    assign_roles(items, duration, H, speech, identity_texts)
    for it in items:
        # dialogue timing relative to the real line it quotes (needs the audio analysis)
        it["style"]["lead_s"] = None
        if it["role"] == "dialogue" and speech:
            ov = [(a, b) for a, b in speech if min(it["end"], b) - max(it["start"], a) > 0]
            if ov:
                it["style"]["lead_s"] = round(it["start"] - min(a for a, _ in ov), 3)
    fonts_used: dict[str, dict | None] = {}
    for it in items:
        fname = (role_fonts or {}).get(it["role"]) or DEFAULT_CALIB_FONT
        if fname not in fonts_used:
            fonts_used[fname] = calibrate_font(fname)
        cal = fonts_used[fname]
        st = it["style"]
        hs = [l["ink_h"] for l in it["lines"] if l.get("ink_h") and l["hangul_share"] >= 0.5]
        if cal and hs:
            st["size_px"] = round(float(np.median(hs)) / cal["ratio_em"], 1)   # em px (renderer convention)
            st["ass_fontsize"] = round(float(np.median(hs)) / cal["ratio"], 1)  # the equivalent libass Fontsize
            st["size_calibration"] = {"font": cal["font"], "ratio_per_fontsize": cal["ratio"],
                                      "ratio_per_em_px": cal["ratio_em"], "fontsize_per_em": cal["fontsize_per_em"],
                                      "convention": "size_px = em px; ASS Fontsize = size_px*fontsize_per_em"}
        else:
            st["size_px"] = None
            st["size_note"] = "보정 글꼴 없음" if not cal else "한글 비율이 낮은 줄뿐이라 크기 환산 못 함"
        if len(it["lines"]) >= 2 and st.get("size_px"):
            cys = [l["bbox"][1] + l["bbox"][3] / 2 for l in it["lines"]]
            pitch = float(np.median(np.diff(cys)))
            st["line_pitch_px"] = round(pitch, 1)
            st["line_spacing"] = round(pitch / st["size_px"], 3)
        else:
            st["line_pitch_px"] = None
            st["line_spacing"] = None
        st["box"] = box_alpha(it, it["_ref"])
    captions_items = []
    frames_rel = []
    for it in items:
        ref = it["_ref"]
        mi, mo = ref["motion_in"], ref["motion_out"]
        t_rep = float(np.median([l["t_rep"] for l in it["lines"]]))
        frame_rel = None
        if save_frames:
            try:
                fr = read_frames(video, [t_rep])[0]
                fpath = out_dir / "frames" / f"{it['id']}_{int(round(t_rep * 1000)):06d}.jpg"
                _save_jpg(fpath, fr)
                frame_rel = _rel(fpath)
                frames_rel.append(frame_rel)
            except Exception:
                frame_rel = None
        st = it["style"]
        st["motion_in"] = _clean_motion(mi)
        st["motion_out"] = _clean_motion(mo)
        captions_items.append({
            "id": it["id"], "start": it["start"], "end": it["end"], "role": it["role"],
            "role_reason": it["role_reason"], "text": it["text"], "bbox": it["bbox"],
            "motion_in": mi.get("type", "unmeasured"), "motion_out": mo.get("type", "unmeasured"),
            "style": st, "t_rep": round(t_rep, 3), "frame": frame_rel,
            "ocr_conf": _median([l["ocr_conf"] for l in it["lines"]]),
            "lines": [{"text": l["text"], "bbox": l["bbox"], "chars": len(l["text"].strip()),
                       "ink_h": l["ink_h"], "ocr_conf": l["ocr_conf"]} for l in it["lines"]],
        })
    captions = {"schema": SCHEMA_CAPTIONS, "video_id": video_id, "resolution": [W, H], "fps_sampled": fps,
                "fps_native": fps_native, "duration": round(duration, 3), "analyzed_at": now_iso(),
                "method": METHOD, "calibration": {k: v for k, v in fonts_used.items()},
                "tracks": {"candidates": len(tracks), "rejected_by_ocr": dropped, "lines": len(lines)},
                "speech_source": "audio/original.json" if speech else None,
                "items": captions_items,
                "presence": {r: tri_state([any(c["role"] == r for c in captions_items)]) for r in ROLES},
                "identity_marks": [{"text": c["text"], "bbox": c["bbox"], "start": c["start"], "end": c["end"],
                                    "frame": c.get("frame")} for c in captions_items if c["role"] == "identity_mark"],
                "presence_note": "없다 = 이 영상의 자동 검출에서 해당 역할 자막을 찾지 못함"}
    layout = {"schema": SCHEMA_LAYOUT, "video_id": video_id, "resolution": [W, H],
              "video_region": region.get("video_region"), "background": region.get("background", "unmeasured"),
              "background_color": region.get("background_color"), "region_detection": region,
              "roles": summarize_roles(captions_items, duration, W), "analyzed_at": now_iso()}
    write_json(out_dir / "captions.json", captions)
    write_json(out_dir / "layout.json", layout)
    return captions, layout


def _clean_motion(m: dict) -> dict:
    keep = ("type", "dur_s", "scale_from", "scale_to", "offset_px", "direction_deg", "alpha_first", "note")
    return {k: m[k] for k in keep if k in m}


def _item_style(grp: list[dict]) -> dict:
    cm = color_mode([l["color"] for l in grp])
    hl = color_mode([l["highlight_color"] for l in grp])
    if hl["mode"] and cm["mode"] and color_dist(hl["mode"], cm["mode"]) <= 60:
        hl = {"mode": None}
    x0 = min(l["bbox"][0] for l in grp)
    x1 = max(l["bbox"][0] + l["bbox"][2] for l in grp)
    y0 = min(l["bbox"][1] for l in grp)
    y1 = max(l["bbox"][1] + l["bbox"][3] for l in grp)
    align = "unmeasured"
    if len(grp) >= 2:
        L = np.std([l["bbox"][0] for l in grp])
        C = np.std([l["bbox"][0] + l["bbox"][2] / 2 for l in grp])
        R = np.std([l["bbox"][0] + l["bbox"][2] for l in grp])
        vals = {"left": L, "center": C, "right": R}
        best = min(vals, key=vals.get)
        others = sorted(v for k, v in vals.items() if k != best)
        if vals[best] <= 3 and others[0] >= 2 * max(vals[best], 1.0):
            align = best
    boxes = [l["box"] for l in grp]
    box = boxes[0] if len(boxes) == 1 else _combine_boxes(boxes)
    vis = _mode([l["outline_visibility"] for l in grp])
    return {"ink_h": _median([l["ink_h"] for l in grp]), "color": cm["mode"], "highlight_color": hl["mode"],
            "outline_px": _median([l["outline_px"] for l in grp]),
            "outline_color": color_mode([l["outline_color"] for l in grp])["mode"],
            "outline_visibility": vis,
            "shadow_px": _median([l["shadow_px"] for l in grp]),
            "shadow_color": color_mode([l["shadow_color"] for l in grp])["mode"],
            "box": box, "n_lines": len(grp), "align": align,
            "anchor": {"x": round((x0 + x1) / 2, 1), "y": round((y0 + y1) / 2, 1)},
            "left": x0, "right": x1, "bg_color": grp[0].get("bg_color"),
            "chars_per_line": [len(l["text"].strip()) for l in grp]}


def _combine_boxes(boxes: list[dict]) -> dict:
    pres = [b for b in boxes if b.get("present") == "present"]
    if not pres:
        st = tri_state([False for b in boxes if b.get("present") == "absent"])
        return {"present": st}
    x0 = min(b["bbox"][0] for b in pres)
    y0 = min(b["bbox"][1] for b in pres)
    x1 = max(b["bbox"][0] + b["bbox"][2] for b in pres)
    y1 = max(b["bbox"][1] + b["bbox"][3] for b in pres)
    out = dict(pres[0])
    out["bbox"] = [x0, y0, x1 - x0, y1 - y0]
    return out


def summarize_roles(items: list[dict], duration: float, W: int) -> dict:
    """Per-video, per-role style summary (medians / modes).  Consumed by `ref aggregate`."""
    out: dict[str, dict] = {}
    for role in ROLES:
        its = [c for c in items if c["role"] == role]
        if not its:
            continue
        st = [c["style"] for c in its]
        durs = [c["end"] - c["start"] for c in its]
        mi_types = [s["motion_in"].get("type") for s in st if s["motion_in"].get("type") not in (None, "unmeasured")]
        mo_types = [s["motion_out"].get("type") for s in st if s["motion_out"].get("type") not in (None, "unmeasured")]
        mi_mode = _mode(mi_types)
        mo_mode = _mode(mo_types)
        align = _role_alignment(its)
        valign = _role_valign(its)
        box_states = [s["box"].get("present") for s in st]
        pboxes = [s["box"] for s in st if s["box"].get("present") == "present"]
        hl = [s["highlight_color"] for s in st if s.get("highlight_color")]
        out[role] = {
            "n_items": len(its),
            "size_px": _median([s.get("size_px") for s in st]),
            "ink_h_px": _median([s.get("ink_h") for s in st]),
            "anchor": {"x": _median([_anchor_x(s, align) for s in st]),
                       "y": _median([_anchor_y(c, valign) for c in its])},
            "align": align,
            "valign": valign,
            "color": color_mode([s.get("color") for s in st])["mode"],
            "highlight_color": color_mode(hl)["mode"],
            "highlight_presence": tri_state([bool(s.get("highlight_color")) for s in st]),
            "outline_px": _median([s.get("outline_px") for s in st if s.get("outline_visibility") in ("visible", "none")]),
            "outline_color": color_mode([s.get("outline_color") for s in st])["mode"],
            "outline_visibility": _mode([s.get("outline_visibility") for s in st]),
            "shadow_px": _median([s.get("shadow_px") for s in st]),
            "shadow_color": color_mode([s.get("shadow_color") for s in st])["mode"],
            "box": {"present": tri_state([b == "present" for b in box_states if b in ("present", "absent")]),
                    "share": round(sum(b == "present" for b in box_states) / len(box_states), 3),
                    "color": color_mode([b.get("color") for b in pboxes])["mode"],
                    "alpha": _median([b.get("alpha") for b in pboxes]),
                    "pad_x": _median([b.get("pad_x") for b in pboxes]),
                    "pad_y": _median([b.get("pad_y") for b in pboxes])},
            "line_spacing": _median([s.get("line_spacing") for s in st]),
            "max_chars_per_line": max((max(s["chars_per_line"]) for s in st if s.get("chars_per_line")), default=None),
            "max_lines": max(s["n_lines"] for s in st),
            "max_width_px": max(c["bbox"][2] for c in its),
            "motion_in": {"type": mi_mode, "n": len(mi_types),
                          "dur_s": _median([s["motion_in"].get("dur_s") for s in st
                                            if s["motion_in"].get("type") == mi_mode]) if mi_mode else None,
                          "scale_from": _median([s["motion_in"].get("scale_from") for s in st
                                                 if s["motion_in"].get("type") == "pop"]) if mi_mode == "pop" else None,
                          "offset_px": _median([s["motion_in"].get("offset_px") for s in st
                                                if s["motion_in"].get("type") == "slide"]) if mi_mode == "slide" else None},
            "motion_out": {"type": mo_mode, "n": len(mo_types),
                           "dur_s": _median([s["motion_out"].get("dur_s") for s in st
                                             if s["motion_out"].get("type") == mo_mode]) if mo_mode else None},
            "timing": {"min_dur_s": round(min(durs), 3), "dur_p50_s": _median(durs),
                       "lead_s": _median([s.get("lead_s") for s in st])},
            "persist": "whole_video" if any(d >= 0.9 * duration for d in durs) else "timed",
            "texts": [c["text"] for c in its],
            "evidence": [{"t": c["t_rep"], "frame": c.get("frame"), "item": c["id"]} for c in its[:5]],
        }
    return out


def _anchor_x(s: dict, align: str) -> float | None:
    if align == "left":
        return s.get("left")
    if align == "right":
        return s.get("right")
    return s["anchor"]["x"]


def _anchor_y(c: dict, valign: str) -> float:
    x, y, w, h = c["bbox"]
    if valign == "top":
        return float(y)
    if valign == "bottom":
        return float(y + h)
    return float(y + h / 2)


def _role_valign(its: list[dict]) -> str:
    """Which edge stays put when the line count changes: compare 1-line and multi-line items of the
    role (top / middle / bottom).  Needs both kinds, else unmeasured."""
    groups: dict[int, list[dict]] = {}
    for c in its:
        groups.setdefault(int(c["style"].get("n_lines") or 1), []).append(c)
    if len(groups) < 2:
        return "unmeasured"
    ks = sorted(groups)
    a, b = groups[ks[0]], groups[ks[-1]]

    def med(cs, f):
        return float(np.median([f(c["bbox"]) for c in cs]))

    d = {"top": abs(med(a, lambda q: q[1]) - med(b, lambda q: q[1])),
         "middle": abs(med(a, lambda q: q[1] + q[3] / 2) - med(b, lambda q: q[1] + q[3] / 2)),
         "bottom": abs(med(a, lambda q: q[1] + q[3]) - med(b, lambda q: q[1] + q[3]))}
    best = min(d, key=d.get)
    hmin = min(float(np.median([c["bbox"][3] for c in a])), float(np.median([c["bbox"][3] for c in b])))
    others = sorted(v for k, v in d.items() if k != best)
    return best if d[best] <= max(3.0, 0.1 * hmin) and others[0] >= 2 * max(d[best], 1.0) else "unmeasured"


def _role_alignment(its: list[dict]) -> str:
    aligns = [c["style"].get("align") for c in its if c["style"].get("align") not in (None, "unmeasured")]
    if aligns:
        return _mode(aligns)
    if len(its) < 2:
        return "unmeasured"
    widths = [c["bbox"][2] for c in its]
    if max(widths) - min(widths) < 8:
        return "unmeasured"   # same widths: cannot tell left/center/right apart
    L = np.std([c["bbox"][0] for c in its])
    C = np.std([c["bbox"][0] + c["bbox"][2] / 2 for c in its])
    R = np.std([c["bbox"][0] + c["bbox"][2] for c in its])
    vals = {"left": L, "center": C, "right": R}
    best = min(vals, key=vals.get)
    others = sorted(v for k, v in vals.items() if k != best)
    return best if vals[best] <= 4 and others[0] >= 2 * max(vals[best], 1.0) else "unmeasured"


def _speech_ranges(out_dir: Path) -> list[tuple[float, float]] | None:
    """Speech intervals of the reference from ``audio/original.json`` (shortkit.reference.audio_original):
    ``speech.segments`` [{start, end}] when ``speech.presence == present`` (mockloop: only the older
    ``events`` list was read, so dialogue lead_s was never measured and speech never helped role
    assignment).  Without a vocals stem these edges come from a heuristic (``confidence: low``)."""
    d = read_json(out_dir / "audio" / "original.json")
    if not d:
        return None
    rng = []
    sp = d.get("speech") or {}
    if sp.get("presence") == "present":
        for sgm in sp.get("segments") or []:
            if sgm.get("start") is not None and sgm.get("end") is not None:
                rng.append((float(sgm["start"]), float(sgm["end"])))
    for e in d.get("events") or []:
        cls = str(e.get("class") or e.get("type_id") or "").lower()
        if cls in ("speech", "dialogue", "voice", "vocals", "speech_kept") or "speech" in cls:
            t = float(e.get("t", 0))
            rng.append((t, t + float(e.get("dur", 0))))
    return rng or None


def _save_jpg(path: Path, rgb: np.ndarray) -> None:
    import cv2
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 85])


def _rel(p: Path) -> str | None:
    try:
        return paths.relp(p)
    except Exception:
        return None
