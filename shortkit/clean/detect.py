"""Detect source overlays: original logos, watermarks, source overlays, burned-in subtitles.

Output (``warehouse/overlays/<source sha256>.json``, schema ``shortkit.overlays/1``)::

    {"schema", "algo", "source": {path|null, sha256, resolution, duration, fps},
     "overlays": [{id, kind: logo|watermark|source_overlay|burned_subtitle,
                   rect {x,y,w,h} (SOURCE px), resolution [W,H], start, end, text, confidence,
                   static, moving_group, band, corner, evidence {...}, template}],
     "review":  [...unconfirmed candidates a person must look at...],
     "checks":  {text_overlays, burned_subtitles, static_graphics: {status, reason}},
     "corners": {top_left|top_right|bottom_left|bottom_right: {text, graphic, overlays, crop}},
     "shots":   [{id, start, end, samples, camera, static_graphic}],
     "activity": {grid, resolution, values}   # motion energy (strategy: never crop away actions)
     "history": [...append-only provenance: detect / plan / apply / verify events...]}

Methods
- Frames are decoded once at ``decode_fps`` (analysis width); every ``1/sample_fps`` s a frame is
  analysed, and every shot (cut detection on thumbnails) gets at least two analysed frames, so
  overlays that exist only in inner cuts are sampled too.
- Text-like blobs: dense high-contrast strokes (morphological gradient density) -> tracked over
  samples by position + stroke appearance -> confirmed by Tesseract OCR on a source-resolution
  crop (eng+kor).  Tracks that never move and last the whole clip are static text overlays
  (watermark / source_overlay); the same text at different positions is a moving watermark;
  timed text lines in the upper/lower band are burned-in subtitles (start/end refined at the
  source frame rate).  Scripts Tesseract cannot read are still found by timing + stroke shape
  (lower confidence, marked ``ocr_unconfirmed``).
- Static graphics without text (logos): pixels whose appearance and edges persist while the
  content changes -- across shots (cross-shot persistence) or against a moving camera.  In a
  single static-camera shot a non-text logo cannot be told from the background: that check is
  reported ``unmeasured`` (못 잼) and the corner crops are saved for a person to look at.
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

import numpy as np

from .. import paths
from ..util.hashing import sha256_file
from ..util.jsonio import now_iso, read_json, write_json
from ..util.media import FFMPEG, MediaError, iter_frames, probe, read_frames

# Tesseract's OpenMP threads busy-wait; on a shared/oversubscribed CPU one OCR call goes from
# ~0.2 s to >15 s.  One thread per tesseract process is both faster and fairer.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

SCHEMA = "shortkit.overlays/1"
ALGO = "shortkit.clean.detect/2"   # /2: word fragments of one text line are joined (S6-9)
OVERLAYS_DIR = "warehouse/overlays"
KINDS = ("logo", "watermark", "source_overlay", "burned_subtitle")
KIND_KO = {"logo": "로고", "watermark": "워터마크", "source_overlay": "출처 오버레이", "burned_subtitle": "원어 자막(번인)"}
HANDLE_RE = re.compile(r"(@\w|www\.|\.com|\.net|\.tv|tiktok|douyin|kuaishou|instagram|youtube|reels|抖音|快手|틱톡)",
                       re.IGNORECASE)


@dataclass
class DetectParams:
    sample_fps: float = 2.0           # analysed frames per second
    decode_fps: float = 6.0           # decoded frames per second (cut detection, per-shot sampling)
    max_samples: int = 240
    analysis_width: int = 960
    static_width: int = 480
    grad_thr: int = 100               # stroke contrast threshold (0..255, 3x3 morphological gradient)
    density_thr: float = 0.45
    cut_thr: float = 32.0             # mean abs thumbnail difference that counts as a cut
    min_shot_s: float = 0.3
    ocr: bool = True
    ocr_lang: str = "eng+kor"
    ocr_word_conf: int = 70
    band_top: float = 0.30            # upper band = y_center < band_top * H
    band_bottom: float = 0.62         # lower band = y_center > band_bottom * H
    static_coverage: float = 0.9      # fraction of the clip a static overlay covers
    save: bool = True


# ----------------------------------------------------------------------------- geometry
def rect_iou(a: dict, b: dict) -> float:
    x0, y0 = max(a["x"], b["x"]), max(a["y"], b["y"])
    x1, y1 = min(a["x"] + a["w"], b["x"] + b["w"]), min(a["y"] + a["h"], b["y"] + b["h"])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    u = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return float(inter / u) if u > 0 else 0.0


def rect_union(rs: Iterable[dict]) -> dict:
    rs = list(rs)
    x0 = min(r["x"] for r in rs)
    y0 = min(r["y"] for r in rs)
    x1 = max(r["x"] + r["w"] for r in rs)
    y1 = max(r["y"] + r["h"] for r in rs)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def rect_clip(r: dict, W: int, H: int) -> dict:
    x0 = max(0, int(np.floor(r["x"])))
    y0 = max(0, int(np.floor(r["y"])))
    x1 = min(W, int(np.ceil(r["x"] + r["w"])))
    y1 = min(H, int(np.ceil(r["y"] + r["h"])))
    return {"x": x0, "y": y0, "w": max(0, x1 - x0), "h": max(0, y1 - y0)}


def rect_pad(r: dict, px: float, py: float | None = None) -> dict:
    py = px if py is None else py
    return {"x": r["x"] - px, "y": r["y"] - py, "w": r["w"] + 2 * px, "h": r["h"] + 2 * py}


def time_overlap(a0, a1, b0, b1) -> float:
    a0 = 0.0 if a0 is None else a0
    b0 = 0.0 if b0 is None else b0
    a1 = float("inf") if a1 is None else a1
    b1 = float("inf") if b1 is None else b1
    return max(0.0, min(a1, b1) - max(a0, b0))


# ----------------------------------------------------------------------------- text strokes
def stroke_mask(gray: np.ndarray, thr: int) -> np.ndarray:
    import cv2

    grad = cv2.morphologyEx(gray, cv2.MORPH_GRADIENT, cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3)))
    return grad > thr


def text_candidates(gray: np.ndarray, thr: int = 100, dens_thr: float = 0.45) -> tuple[list[dict], np.ndarray]:
    """Text-like blobs: dense clusters of high-contrast strokes, joined horizontally.

    Returns ``[{x,y,w,h,fill}]`` in ``gray`` px and the stroke mask.  Thin isolated lines
    (table edges, door frames) have low local density and are dropped.
    """
    import cv2

    m = stroke_mask(gray, thr)
    mf = m.astype(np.float32)
    dens = cv2.boxFilter(mf, -1, (7, 7))
    dense = ((dens > dens_thr) & m).astype(np.uint8)
    k = max(9, int(round(gray.shape[1] / 64)))
    cl = cv2.morphologyEx(dense, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, 5)))
    n, _lab, st, _c = cv2.connectedComponentsWithStats(cl, connectivity=8)
    H = gray.shape[0]
    out = []
    for i in range(1, n):
        x, y, w, h, _a = (int(v) for v in st[i])
        if h < 5 or h > 0.2 * H or w < 1.2 * h or w < 12:
            continue
        fill = float(mf[y:y + h, x:x + w].mean())
        if fill < 0.2:
            continue
        out.append({"x": x, "y": y, "w": w, "h": h, "fill": round(fill, 3)})
    return out, m


def _mask_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Symmetric stroke overlap with 1-px tolerance (0..1)."""
    import cv2

    if a.shape != b.shape:
        b = cv2.resize(b.astype(np.uint8), (a.shape[1], a.shape[0]), interpolation=cv2.INTER_NEAREST) > 0
    na, nb = int(a.sum()), int(b.sum())
    if na == 0 or nb == 0:
        return 0.0
    k = np.ones((3, 3), np.uint8)
    da = cv2.dilate(a.astype(np.uint8), k) > 0
    db = cv2.dilate(b.astype(np.uint8), k) > 0
    return float(min((a & db).sum() / na, (b & da).sum() / nb))


# ----------------------------------------------------------------------------- OCR
def _fill_mask(g: np.ndarray, polarity: str) -> np.ndarray:
    """Text fill pixels (extreme brightness or darkness) not touching the crop border."""
    import cv2

    if polarity == "bright":
        thr = max(160, int(np.percentile(g, 85)))
        m = (g >= thr).astype(np.uint8)
    else:
        thr = min(90, int(np.percentile(g, 15)))
        m = (g <= thr).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(m, connectivity=8)
    H, W = g.shape
    keep = np.zeros(n, bool)
    for i in range(1, n):
        x, y, w, h, _a = st[i]
        if x == 0 or y == 0 or x + w >= W or y + h >= H or h < 0.25 * H:
            continue
        keep[i] = True
    return keep[lab]


def ocr_text(crop_rgb: np.ndarray, lang: str = "eng+kor", psm: int | None = None, target_h: int = 44,
             timeout: float = 8.0) -> dict:
    """OCR one text crop with several binarisations; best variant wins.

    Returns ``{text, conf, max_word_conf, n_alnum, words, variant, available}``.  ``available``
    is False when Tesseract is missing (callers must then treat text as unmeasured).
    """
    import cv2

    try:
        import pytesseract
    except ImportError:
        return {"text": "", "conf": 0.0, "max_word_conf": 0, "n_alnum": 0, "words": [], "variant": None,
                "available": False}
    h, w = crop_rgb.shape[:2]
    if h < 4 or w < 4:
        return {"text": "", "conf": 0.0, "max_word_conf": 0, "n_alnum": 0, "words": [], "variant": None, "available": True}
    sc = min(4.0, max(1.0, target_h / h))
    img = cv2.resize(crop_rgb, None, fx=sc, fy=sc, interpolation=cv2.INTER_CUBIC) if sc != 1.0 else crop_rgb
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    psm = psm or (7 if w / max(h, 1) >= 2.5 else 6)
    variants = {
        "bright_fill": np.where(_fill_mask(g, "bright"), 0, 255).astype(np.uint8),
        "dark_fill": np.where(_fill_mask(g, "dark"), 0, 255).astype(np.uint8),
        "gray": g,
    }
    best = None
    timeouts = 0
    for name, v in variants.items():
        border = 255 if name != "gray" else int(np.median(g))
        v = cv2.copyMakeBorder(v, 12, 12, 12, 12, cv2.BORDER_CONSTANT, value=border)
        try:
            d = pytesseract.image_to_data(v, lang=lang, config=f"--psm {psm}", output_type=pytesseract.Output.DICT,
                                          timeout=timeout)
        except RuntimeError as e:   # pytesseract raises RuntimeError on timeout: skip this variant
            if "timeout" in str(e).lower():
                timeouts += 1
                continue
            raise
        except Exception:  # tesseract binary / language missing
            return {"text": "", "conf": 0.0, "max_word_conf": 0, "n_alnum": 0, "words": [], "variant": None,
                    "available": False}
        words = []
        for txt, cf in zip(d["text"], d["conf"]):
            txt = (txt or "").strip()
            try:
                cf = float(cf)
            except (TypeError, ValueError):
                cf = -1.0
            if txt and cf >= 0:
                words.append((txt, cf))
        alnum = [(t, c) for t, c in words if sum(ch.isalnum() for ch in t) >= 1]
        score = sum(c * sum(ch.isalnum() for ch in t) for t, c in alnum)
        n_alnum = sum(sum(ch.isalnum() for ch in t) for t, _ in alnum)
        res = {"text": " ".join(t for t, _ in words), "conf": round(float(np.mean([c for _, c in alnum])) if alnum else 0.0, 1),
               "max_word_conf": int(max((c for t, c in alnum if sum(ch.isalnum() for ch in t) >= 2), default=0)),
               "n_alnum": int(n_alnum), "words": [[t, int(c)] for t, c in words], "variant": name, "available": True,
               "_score": score}
        if best is None or res["_score"] > best["_score"]:
            best = res
    if best is None:   # every variant timed out: OCR result is unmeasured, not "no text"
        return {"text": "", "conf": 0.0, "max_word_conf": 0, "n_alnum": 0, "words": [], "variant": None,
                "available": False, "timeouts": timeouts}
    best.pop("_score", None)
    best["timeouts"] = timeouts
    return best


def ocr_confirmed(o: dict, word_conf: int = 70) -> bool:
    return bool(o.get("available")) and o.get("max_word_conf", 0) >= word_conf and o.get("n_alnum", 0) >= 3


def text_similarity(a: str, b: str) -> float:
    """Normalised similarity of two OCR strings (alnum only, case-insensitive)."""
    import difflib

    na = "".join(ch for ch in (a or "").lower() if ch.isalnum())
    nb = "".join(ch for ch in (b or "").lower() if ch.isalnum())
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


# ----------------------------------------------------------------------------- frame access
def read_crop_frames(src: str | Path, rect: dict, t0: float, t1: float, fps: float | None = None,
                     color: bool = False) -> list[tuple[float, np.ndarray]]:
    """Gray (or BGR when ``color``) crops of ``rect`` (SOURCE px) for every source frame with
    pts in [t0, t1).

    Frame times are the real presentation timestamps (``-copyts`` + ``showinfo``), not a
    frame-count estimate, so boundaries measured from them are exact to the frame.
    """
    t0 = max(0.0, t0)
    if t1 <= t0:
        return []
    x, y, w, h = (int(rect[k]) for k in ("x", "y", "w", "h"))
    w -= w % 2
    h -= h % 2
    if w < 2 or h < 2:
        return []
    # -ss is relative to the file start; with -copyts the filter sees absolute timestamps
    off = _start_offset(src)
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-v", "info", "-ss", f"{t0:.6f}", "-copyts", "-i", str(src),
           "-vf", f"trim=start={t0 + off:.6f}:end={t1 + off:.6f},crop={w}:{h}:{x}:{y},showinfo",
           "-f", "rawvideo", "-pix_fmt", "bgr24" if color else "gray", "-"]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if proc.returncode != 0:
        raise MediaError(proc.stderr.decode("utf-8", "replace")[-800:])
    times = [float(m) - off for m in re.findall(r"pts_time:\s*([-0-9.eE+]+)", proc.stderr.decode("utf-8", "replace"))]
    buf = proc.stdout
    ch = 3 if color else 1
    fb = w * h * ch
    shape = (h, w, 3) if color else (h, w)
    n = min(len(buf) // fb, len(times))
    return [(times[i], np.frombuffer(buf[i * fb:(i + 1) * fb], np.uint8).reshape(shape)) for i in range(n)]


_OFFSETS: dict[str, float] = {}


def _start_offset(src: str | Path) -> float:
    """Container start_time (media times in shortkit are relative to it)."""
    key = str(src)
    if key not in _OFFSETS:
        try:
            _OFFSETS[key] = float(probe(src).raw.get("format", {}).get("start_time") or 0.0)
        except Exception:
            _OFFSETS[key] = 0.0
    return _OFFSETS[key]


# ----------------------------------------------------------------------------- tracking
@dataclass
class _Track:
    id: int
    hits: list[tuple[int, float, dict]] = field(default_factory=list)   # (sample idx, t, rect analysis px)
    ref_mask: np.ndarray | None = None
    fills: list[float] = field(default_factory=list)
    shots: set = field(default_factory=set)

    @property
    def last(self) -> tuple[int, float, dict]:
        return self.hits[-1]


@dataclass
class _Shot:
    id: int
    start: float
    end: float = 0.0
    n: int = 0
    sum: np.ndarray | None = None
    sumsq: np.ndarray | None = None
    edges: np.ndarray | None = None
    prev_small: np.ndarray | None = None
    shifts: list = field(default_factory=list)


def _cut_score(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.mean(np.abs(a.astype(np.float32) - b.astype(np.float32))))


# ----------------------------------------------------------------------------- main
def overlays_path(sha: str) -> Path:
    return paths.absp(f"{OVERLAYS_DIR}/{sha}.json")


def load_overlays(sha: str) -> dict | None:
    return read_json(overlays_path(sha))


def _rel_or_none(p: Path) -> str | None:
    try:
        return paths.relp(p)
    except ValueError:
        return None


def append_history(sha: str, event: dict) -> None:
    """Append a provenance event (never removes earlier records)."""
    p = overlays_path(sha)
    doc = read_json(p)
    if doc is None:
        doc = {"schema": SCHEMA, "source": {"sha256": sha}, "overlays": [], "history": []}
    doc.setdefault("history", []).append({"at": now_iso(), **event})
    write_json(p, doc)


def detect_overlays(src: str | Path, params: DetectParams | None = None) -> dict:
    """Run detection on ``src`` and (by default) save ``warehouse/overlays/<sha256>.json``."""
    import cv2

    prm = params or DetectParams()
    src = Path(src)
    info = probe(src)
    W, H = info.width, info.height
    if not W or not H:
        raise MediaError(f"no video stream in {src}")
    sha = sha256_file(src)
    dur = float(info.duration)
    fps_src = float(info.fps or 30.0)
    aw = min(prm.analysis_width, W)
    ah = int(round(H * aw / W / 2) * 2)
    sx, sy = W / aw, H / ah
    sw_ = min(prm.static_width, aw)
    sh_ = int(round(H * sw_ / W / 2) * 2)
    sample_fps = min(prm.sample_fps, prm.max_samples / max(dur, 1e-3))
    decode_fps = max(sample_fps, min(prm.decode_fps, 3 * prm.max_samples / max(dur, 1e-3)))
    step = max(1, int(round(decode_fps / sample_fps)))

    samples: list[dict] = []          # analysed samples: {i, t, shot}
    tracks: list[_Track] = []
    shots: list[_Shot] = []
    activity = np.zeros((36, 64), np.float64)
    corner_frame_t = None
    cur: _Shot | None = None
    prev_thumb = None
    buffer: list[tuple[float, np.ndarray]] = []   # unanalysed frames of the current shot
    shot_samples = 0

    def analyse(t: float, gray: np.ndarray) -> None:
        nonlocal shot_samples
        si = len(samples)
        samples.append({"i": si, "t": round(t, 4), "shot": cur.id})
        shot_samples += 1
        cands, m = text_candidates(gray, prm.grad_thr, prm.density_thr)
        for c in cands:
            crop = m[c["y"]:c["y"] + c["h"], c["x"]:c["x"] + c["w"]]
            best, best_s = None, 0.0
            for tr in tracks:
                li, _lt, lr = tr.last
                if si - li > 2:
                    continue
                iou = rect_iou(c, lr)
                if iou < 0.5:
                    continue
                sim = _mask_similarity(crop, tr.ref_mask)
                if sim >= 0.5 and iou + sim > best_s:
                    best, best_s = tr, iou + sim
            if best is None:
                best = _Track(id=len(tracks), ref_mask=crop.copy())
                tracks.append(best)
            best.hits.append((si, t, {k: c[k] for k in ("x", "y", "w", "h")}))
            best.fills.append(c["fill"])
            best.shots.add(cur.id)
        small = cv2.resize(gray, (sw_, sh_), interpolation=cv2.INTER_AREA)
        sf = small.astype(np.float64)
        edges = cv2.Canny(small, 60, 160) > 0
        if cur.sum is None:
            cur.sum = np.zeros_like(sf)
            cur.sumsq = np.zeros_like(sf)
            cur.edges = np.zeros(sf.shape, np.float64)
        cur.sum += sf
        cur.sumsq += sf * sf
        cur.edges += edges
        cur.n += 1
        if cur.prev_small is not None:
            d = np.abs(sf - cur.prev_small.astype(np.float64))
            activity[:] += cv2.resize(d, (64, 36), interpolation=cv2.INTER_AREA)
            (dx, dy), resp = cv2.phaseCorrelate(cur.prev_small.astype(np.float32), small.astype(np.float32), hann)
            if resp >= 0.05:   # low response = no dominant global motion peak (ignore)
                cur.shifts.append(float(np.hypot(dx, dy)))
        cur.prev_small = small

    def close_shot(t_end: float) -> None:
        nonlocal buffer
        if cur is None:
            return
        # every shot gets >= 2 analysed samples when it has the frames for it
        need = max(0, 2 - shot_samples)
        if need and buffer:
            pick = sorted({int(round(q * (len(buffer) - 1))) for q in ((0.5,) if need == 1 else (0.25, 0.75))})
            for k in pick:
                analyse(*buffer[k])
        cur.end = t_end
        buffer = []

    hann = cv2.createHanningWindow((sw_, sh_), cv2.CV_32F)
    k = 0
    for t, rgb in iter_frames(src, fps=decode_fps, width=aw):
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        thumb = cv2.resize(gray, (64, 36), interpolation=cv2.INTER_AREA)
        is_cut = (prev_thumb is not None and _cut_score(prev_thumb, thumb) > prm.cut_thr
                  and cur is not None and t - cur.start >= prm.min_shot_s)
        if cur is None or is_cut:
            close_shot(t)
            cur = _Shot(id=len(shots), start=round(t if shots else 0.0, 4))
            shots.append(cur)
            shot_samples = 0
        prev_thumb = thumb
        if k % step == 0:
            analyse(t, gray)
            buffer = []
            if corner_frame_t is None and t >= dur / 2:
                corner_frame_t = t
        else:
            buffer.append((t, gray))
            if len(buffer) > 4 * step:
                buffer.pop(0)
        k += 1
    close_shot(dur)
    if not samples:
        raise MediaError(f"no frames decoded from {src}")
    shots[-1].end = round(dur, 4)
    s_times = [s["t"] for s in samples]
    interval = 1.0 / sample_fps

    # ---- confirm text tracks
    overlays: list[dict] = []
    review: list[dict] = []
    rejected: list[dict] = []
    frame_cache: dict[float, np.ndarray] = {}

    def full_frame(t: float) -> np.ndarray:
        t = round(t, 3)
        if t not in frame_cache:
            frame_cache[t] = read_frames(src, [t])[0]
        return frame_cache[t]

    ocr_available = True
    min_hits = 2 if len(samples) >= 3 else 1
    for tr in tracks:
        if len(tr.hits) < min_hits:
            continue
        rects_src = [{"x": r["x"] * sx, "y": r["y"] * sy, "w": r["w"] * sx, "h": r["h"] * sy} for _i, _t, r in tr.hits]
        u = rect_union(rects_src)
        med_h = float(np.median([r["h"] for r in rects_src]))
        i_first, t_first = tr.hits[0][0], tr.hits[0][1]
        i_last, t_last = tr.hits[-1][0], tr.hits[-1][1]
        t_mid = tr.hits[len(tr.hits) // 2][1]
        frame = full_frame(t_mid)
        pad = int(round(0.35 * med_h)) + 2
        cr = rect_clip(rect_pad(u, pad), W, H)
        o = ocr_text(frame[cr["y"]:cr["y"] + cr["h"], cr["x"]:cr["x"] + cr["w"]], prm.ocr_lang) if prm.ocr else \
            {"available": False, "text": "", "conf": 0.0, "max_word_conf": 0, "n_alnum": 0, "words": []}
        if not o.get("available"):
            ocr_available = False
        confirmed = ocr_confirmed(o, prm.ocr_word_conf)
        cy = u["y"] + u["h"] / 2
        band = "top" if cy < prm.band_top * H else ("bottom" if cy > prm.band_bottom * H else "middle")
        at_start = i_first == 0
        at_end = i_last == len(samples) - 1
        coverage = (len(tr.hits)) / len(samples)
        timed = not (at_start and at_end)
        aspect = u["w"] / max(u["h"], 1)
        rec = {"track": tr.id, "rect_text": {k: round(v, 1) for k, v in u.items()}, "resolution": [W, H],
               "line_h": round(med_h, 1),
               "t_first": t_first, "t_last": t_last, "i_first": i_first, "i_last": i_last, "hits": len(tr.hits),
               "coverage": round(coverage, 3), "band": band, "ocr": o, "shots": sorted(tr.shots),
               "fill": round(float(np.mean(tr.fills)), 3), "t_mid": t_mid}
        if confirmed:
            rec["confirmed_by"] = "ocr"
            rec["confidence"] = round(min(0.95, 0.5 + o["max_word_conf"] / 200 + 0.1 * min(1.0, len(tr.hits) / 6)), 2)
        elif timed and band != "middle" and len(tr.hits) >= 3 and aspect >= 3 and rec["fill"] >= 0.3:
            rec["confirmed_by"] = "textlike_timing"
            rec["confidence"] = 0.5
        elif not timed and (len(tr.shots) >= 2 or _ring_changes(src, u, s_times, W, H, full_frame)):
            rec["confirmed_by"] = "textlike_static_over_changing_content"
            rec["confidence"] = 0.5
        else:
            rec["reason"] = ("OCR 로 글자 확인 안 됨 + 시간/배경 변화 근거 없음" if not timed
                             else "OCR 로 글자 확인 안 됨 + 자막 모양/위치 조건 불충분")
            (review if (not timed and _corner_of(u, W, H)) else rejected).append(rec)
            continue
        overlays.append(rec)

    # ---- one text line tracked as several word fragments: join them (also the fragments that were not
    #      confirmed on their own), so the planned removal covers the whole line (S6-9: 'R IT' / 'st' left)
    overlays = _join_line_fragments(overlays, [review, rejected], interval, len(samples), s_times, W, H, full_frame,
                                    prm)

    # ---- merge co-timed adjacent lines (multi-line subtitles / two-line watermarks)
    overlays = _merge_lines(overlays, interval)

    # ---- moving watermarks: the same mark re-appearing at another position right after it vanished
    _group_moving(overlays, s_times, interval, full_frame, W, H)

    # ---- timing + extent refinement, classification
    final: list[dict] = []
    for rec in overlays:
        u = rec["rect_text"]
        start = 0.0 if rec["i_first"] == 0 else _refine_boundary(src, rec, s_times, fps_src, W, H, full_frame, "start",
                                                                 prm.grad_thr)
        end = dur if rec["i_last"] == len(samples) - 1 else _refine_boundary(src, rec, s_times, fps_src, W, H,
                                                                            full_frame, "end", prm.grad_thr)
        times_in = [t for t in s_times if start <= t <= end]
        shot_of = {sm["t"]: sm["shot"] for sm in samples}
        present_shots = set(rec["shots"])
        absent = [s_times[i] for i in (rec["i_first"] - 1, rec["i_last"] + 1)
                  if 0 <= i < len(s_times) and shot_of.get(s_times[i]) in present_shots
                  and not (start <= s_times[i] <= end)]
        ext = _refine_extent(src, u, rec["line_h"], times_in, W, H, full_frame, prm.grad_thr, absent)
        # the tracked text itself is always part of the overlay: low-contrast letters (white text over a
        # light wall) can be missing from the ink/difference masks
        ext["rect"] = rect_clip(rect_union([ext["rect"], rect_pad(u, 0.15 * rec["line_h"] + 2)]), W, H)
        if prm.ocr and ext["rect"]["w"] > u["w"] + rec["line_h"]:
            # the extent followed the line past the tracked words: read the whole line (residual checks
            # match OCR pieces against this text)
            cr = rect_clip(ext["rect"], W, H)
            fr = full_frame(rec["t_mid"])
            o2 = ocr_text(fr[cr["y"]:cr["y"] + cr["h"], cr["x"]:cr["x"] + cr["w"]], prm.ocr_lang)
            if ocr_confirmed(o2, prm.ocr_word_conf) and o2.get("n_alnum", 0) > rec["ocr"].get("n_alnum", 0):
                rec["ocr"] = o2
        coverage_t = (end - start) / max(dur, 1e-6)
        static = coverage_t >= prm.static_coverage and not rec.get("moving_group")
        text = rec["ocr"].get("text", "") if rec["ocr"].get("available") else ""
        corner = _corner_of(ext["rect"], W, H)
        if static and rec["confirmed_by"] == "ocr" and not HANDLE_RE.search(text or "") and ext["how"] != "ink+box" \
                and len(rec["shots"]) < 2 and not _ring_changes(src, u, s_times, W, H, full_frame):
            # fixed text in a fixed shot without a plate/handle may be part of the scene (a sign):
            # never auto-remove it, a person decides
            rec["reason"] = "정지 화면 속 고정 글자(간판 등 장면 일부일 수 있음) → 사람 확인"
            review.append(rec)
            continue
        if rec.get("moving_group"):
            kind = "watermark"
        elif static:
            kind = "watermark" if (HANDLE_RE.search(text or "") or corner) else "source_overlay"
        elif rec["band"] in ("top", "bottom"):
            kind = "burned_subtitle"
        else:
            kind = "source_overlay"
        final.append({
            "kind": kind, "rect": ext["rect"], "resolution": [W, H], "start": round(start, 3), "end": round(end, 3),
            "text": text or None, "confidence": rec["confidence"], "static": bool(static),
            "moving_group": rec.get("moving_group"), "band": rec["band"], "corner": corner,
            "evidence": {"method": rec["confirmed_by"], "sample_times": [rec["t_first"], rec["t_last"]],
                         "hits": rec["hits"], "shots": rec["shots"], "ocr": {k: rec["ocr"].get(k) for k in
                                                                              ("text", "conf", "max_word_conf", "variant")},
                         "rect_text": {k: int(round(v)) for k, v in u.items()}, "extent": ext["how"],
                         "timing": rec.get("timing") or "sample_grid",
                         **({"fragments": rec["fragments"]} if rec.get("fragments") else {})},
            "t_ref": rec["t_mid"],
        })

    # ---- static graphics (logos without text)
    shot_info, logos, graphic_status = _static_graphics(shots, samples, (sw_, sh_), W, H, final, prm)
    for lg in logos:
        cr = rect_clip(lg["rect"], W, H)
        fr = full_frame(lg["t_ref"])
        o = ocr_text(fr[cr["y"]:cr["y"] + cr["h"], cr["x"]:cr["x"] + cr["w"]], prm.ocr_lang) if prm.ocr else {}
        if ocr_confirmed(o, prm.ocr_word_conf):
            lg["kind"] = "watermark"
            lg["text"] = o["text"]
            lg["evidence"]["ocr"] = {k: o.get(k) for k in ("text", "conf", "max_word_conf", "variant")}
        final.append(lg)

    final.sort(key=lambda o: (o["start"], o["rect"]["y"], o["rect"]["x"]))
    for i, o in enumerate(final, 1):
        o["id"] = f"ov{i}"

    doc_dir = f"{OVERLAYS_DIR}/{sha}"
    # templates (original overlay crops) for residual checks after cleaning
    for o in final:
        cr = rect_clip(o["rect"], W, H)
        t_ref = o.pop("t_ref")
        fr = full_frame(t_ref)
        o["template"] = None
        o["template_t"] = round(float(t_ref), 3)
        if cr["w"] >= 4 and cr["h"] >= 4 and prm.save:
            p = paths.ensure_dir(doc_dir) / f"{o['id']}.png"
            cv2.imwrite(str(p), cv2.cvtColor(fr[cr["y"]:cr["y"] + cr["h"], cr["x"]:cr["x"] + cr["w"]], cv2.COLOR_RGB2BGR))
            o["template"] = paths.relp(p)
    for r in review:
        r.pop("t_mid", None)
    text_status = "measured" if (prm.ocr and ocr_available) else "unmeasured"
    corners = _corners(final, review, graphic_status, text_status, W, H)
    if prm.save and corner_frame_t is not None:
        fr = full_frame(corner_frame_t)
        for name, c in corners.items():
            cr = rect_clip(c["region"], W, H)
            p = paths.ensure_dir(doc_dir) / f"corner_{name}.png"
            cv2.imwrite(str(p), cv2.cvtColor(fr[cr["y"]:cr["y"] + cr["h"], cr["x"]:cr["x"] + cr["w"]], cv2.COLOR_RGB2BGR))
            c["crop"] = paths.relp(p)
            c["crop_t"] = round(corner_frame_t, 3)
    act = activity / max(1e-9, activity.sum()) if activity.sum() > 0 else activity
    doc = {
        "schema": SCHEMA, "algo": ALGO,
        "source": {"path": _rel_or_none(src), "sha256": sha, "resolution": [W, H], "duration": round(dur, 3),
                   "fps": round(fps_src, 3)},
        "detected_at": now_iso(),
        "params": {**asdict(prm), "sample_fps_used": round(sample_fps, 4), "decode_fps_used": round(decode_fps, 4),
                   "analysis_resolution": [aw, ah]},
        "shots": shot_info,
        "overlays": final,
        "review": [_review_row(r) for r in review],
        "rejected_candidates": [_review_row(r) for r in rejected[:50]],
        "checks": {
            "text_overlays": {"status": text_status, "method": "stroke-density blobs + tracking + Tesseract OCR",
                              "reason": None if text_status == "measured" else "OCR(Tesseract) 사용 불가",
                              "impact": None if text_status == "measured" else
                              "글자 워터마크·원어 자막이 최종 화면에 남을 수 있음 → 사람이 확인해야 함"},
            "burned_subtitles": {"status": "measured" if len(samples) >= 2 else "unmeasured",
                                 "method": "timed text lines in upper/lower band, boundaries refined at source fps"},
            "static_graphics": {**graphic_status, "impact": None if graphic_status["status"] == "measured" else
                                "원본 채널 로고(글자 없는 그림)가 최종 화면에 남을 수 있음 → 코너 캡처 확인 필요"},
        },
        "corners": corners,
        "activity": {"grid": [64, 36], "resolution": [W, H], "values": np.round(act, 6).tolist(),
                     "method": "sum of |frame difference| between analysed samples within shots"},
        "samples": {"n": len(samples), "times": s_times},
    }
    if prm.save:
        old = load_overlays(sha) or {}
        doc["history"] = list(old.get("history") or [])
        doc["history"].append({"at": doc["detected_at"], "action": "detect", "algo": ALGO,
                               "n_overlays": len(final),
                               "overlays": [{k: o[k] for k in ("id", "kind", "rect", "start", "end", "text")} for o in final]})
        if old.get("removals"):
            doc["removals"] = old["removals"]
        write_json(overlays_path(sha), doc)
        doc["_path"] = paths.relp(overlays_path(sha))
    return doc


def _review_row(r: dict) -> dict:
    return {"rect": {k: int(round(v)) for k, v in r["rect_text"].items()}, "resolution": r.get("resolution"),
            "t_first": r["t_first"], "t_last": r["t_last"],
            "hits": r["hits"], "band": r["band"], "ocr_text": r["ocr"].get("text"),
            "ocr_conf": r["ocr"].get("max_word_conf"), "reason": r.get("reason")}


def _corner_of(r: dict, W: int, H: int) -> str | None:
    cx, cy = r["x"] + r["w"] / 2, r["y"] + r["h"] / 2
    horiz = "left" if cx < 0.3 * W else ("right" if cx > 0.7 * W else None)
    vert = "top" if cy < 0.2 * H else ("bottom" if cy > 0.8 * H else None)
    return f"{vert}_{horiz}" if horiz and vert else None


def _ring_changes(src, u: dict, s_times: list[float], W: int, H: int, full_frame) -> bool:
    """Does the content around a static text blob change over time (i.e. it floats above the footage)?"""
    import cv2

    if len(s_times) < 3:
        return False
    ts = [s_times[int(round(q * (len(s_times) - 1)))] for q in (0.1, 0.5, 0.9)]
    ring = rect_clip(rect_pad(u, u["h"] * 1.5, u["h"] * 1.5), W, H)
    inner = rect_clip(rect_pad(u, 2), W, H)
    vals = []
    for t in ts:
        g = cv2.cvtColor(full_frame(t), cv2.COLOR_RGB2GRAY).astype(np.float32)
        m = np.ones((ring["h"], ring["w"]), bool)
        m[inner["y"] - ring["y"]:inner["y"] - ring["y"] + inner["h"], inner["x"] - ring["x"]:inner["x"] - ring["x"] + inner["w"]] = False
        vals.append(g[ring["y"]:ring["y"] + ring["h"], ring["x"]:ring["x"] + ring["w"]][m])
    d = max(float(np.mean(np.abs(vals[i] - vals[j]))) for i in range(3) for j in range(i + 1, 3))
    return d > 12.0


LINE_GAP_FACTOR = 2.5      # max horizontal gap between fragments of one text line, in line heights


def _same_line(a: dict, b: dict) -> bool:
    """Two text blobs on one text line: similar height, vertical overlap >= half the smaller one,
    horizontal gap <= LINE_GAP_FACTOR line heights (words of a subtitle / parts of a handle)."""
    ra, rb = a["rect_text"], b["rect_text"]
    ha, hb = max(a["line_h"], 1e-6), max(b["line_h"], 1e-6)
    if not 0.5 <= ha / hb <= 2.0:
        return False
    yov = min(ra["y"] + ra["h"], rb["y"] + rb["h"]) - max(ra["y"], rb["y"])
    if yov < 0.5 * min(ra["h"], rb["h"]):
        return False
    gap = max(ra["x"], rb["x"]) - min(ra["x"] + ra["w"], rb["x"] + rb["w"])
    return gap <= LINE_GAP_FACTOR * max(ha, hb)


def _co_timed(a: dict, b: dict, interval: float, n_samples: int) -> bool:
    """Same kind of timing (both whole-clip or both timed) and time overlap >= half the shorter span."""
    def whole(r):
        return r["i_first"] == 0 and r["i_last"] == n_samples - 1

    if whole(a) != whole(b):
        return False
    a0, a1 = a["t_first"], a["t_last"] + interval
    b0, b1 = b["t_first"], b["t_last"] + interval
    return min(a1, b1) - max(a0, b0) >= 0.5 * min(a1 - a0, b1 - b0)


def _join_line_fragments(overlays: list[dict], pools: list[list[dict]], interval: float, n_samples: int,
                         s_times: list[float], W: int, H: int, full_frame, prm: "DetectParams") -> list[dict]:
    """Join the word fragments of one text line into one overlay.

    The tracker follows stroke blobs, so one subtitle line ("WAIT FOR IT...") or one handle
    ("@fake_repost" over a changing background) can become several tracks, and a fragment that is
    too short for OCR on its own ("OR", "repost") is rejected or sent to review.  Removing only
    the confirmed fragments leaves the rest of the line on screen.  A confirmed overlay therefore
    absorbs every co-timed fragment on the same line (confirmed, review or rejected); the joined
    line is OCR'd again as a whole.  ``pools`` lists are edited in place."""
    recs = [dict(r) for r in overlays]
    changed = True
    while changed:
        changed = False
        for a in recs:
            for src in [recs, *pools]:
                for b in list(src):
                    if b is a or not _same_line(a, b) or not _co_timed(a, b, interval, n_samples):
                        continue
                    _absorb(a, b)
                    src.remove(b)
                    changed = True
                if changed:
                    break
            if changed:
                break
    for r in recs:
        if not r.get("fragments"):
            continue
        # a time where the whole joined line is on screen, OCR'd as one line
        mid = (r["t_first"] + r["t_last"]) / 2
        r["t_mid"] = min((t for t in s_times if r["t_first"] <= t <= r["t_last"]), key=lambda t: abs(t - mid),
                         default=r["t_mid"])
        if prm.ocr:
            u = r["rect_text"]
            cr = rect_clip(rect_pad(u, int(round(0.35 * r["line_h"])) + 2), W, H)
            fr = full_frame(r["t_mid"])
            o = ocr_text(fr[cr["y"]:cr["y"] + cr["h"], cr["x"]:cr["x"] + cr["w"]], prm.ocr_lang)
            if ocr_confirmed(o, prm.ocr_word_conf):
                r["ocr"] = o
                r["confirmed_by"] = "ocr"
                r["confidence"] = max(r["confidence"], round(min(0.95, 0.5 + o["max_word_conf"] / 200), 2))
    return recs


def _absorb(a: dict, b: dict) -> None:
    """Merge fragment ``b`` into line ``a`` (same line, co-timed)."""
    left, right = (a, b) if a["rect_text"]["x"] <= b["rect_text"]["x"] else (b, a)
    ta = (left["ocr"].get("text") or "").strip()
    tb = (right["ocr"].get("text") or "").strip()
    a_ocr = dict(a["ocr"])
    a_ocr["text"] = " ".join(t for t in (ta, tb) if t)
    if b["ocr"].get("max_word_conf", 0) > a_ocr.get("max_word_conf", 0):
        a_ocr["max_word_conf"] = b["ocr"]["max_word_conf"]
    a_ocr["n_alnum"] = int(a["ocr"].get("n_alnum", 0)) + int(b["ocr"].get("n_alnum", 0))
    a["ocr"] = a_ocr
    a["rect_text"] = rect_union([a["rect_text"], b["rect_text"]])
    a["line_h"] = max(a["line_h"], b["line_h"])
    for k, f in (("t_first", min), ("i_first", min), ("t_last", max), ("i_last", max), ("hits", max)):
        a[k] = f(a[k], b[k])
    a["shots"] = sorted(set(a.get("shots") or []) | set(b.get("shots") or []))
    if b.get("confirmed_by") == "ocr" and a.get("confirmed_by") != "ocr":
        a["confirmed_by"] = "ocr"
    a["confidence"] = max(a.get("confidence") or 0.0, b.get("confidence") or 0.0)
    a.setdefault("fragments", []).append({"track": b.get("track"), "text": b["ocr"].get("text"),
                                          "was": b.get("confirmed_by") or "unconfirmed",
                                          "rect_text": {k: round(v, 1) for k, v in b["rect_text"].items()}})


def _merge_lines(recs: list[dict], interval: float) -> list[dict]:
    recs = sorted(recs, key=lambda r: (r["rect_text"]["y"]))
    merged: list[dict] = []
    for r in recs:
        tgt = None
        for m in merged:
            if m.get("confirmed_by") is None:
                continue
            same_time = abs(m["t_first"] - r["t_first"]) <= 1.01 * interval and abs(m["t_last"] - r["t_last"]) <= 1.01 * interval
            a, b = m["rect_text"], r["rect_text"]
            gap = b["y"] - (a["y"] + a["h"])
            ov = min(a["x"] + a["w"], b["x"] + b["w"]) - max(a["x"], b["x"])
            if same_time and -0.5 * a["h"] <= gap <= 0.9 * max(m["line_h"], r["line_h"]) and ov >= 0.3 * min(a["w"], b["w"]) \
                    and m["band"] == r["band"]:
                tgt = m
                break
        if tgt is None:
            merged.append(dict(r))
            continue
        tgt["rect_text"] = rect_union([tgt["rect_text"], r["rect_text"]])
        tgt["hits"] = max(tgt["hits"], r["hits"])
        tgt["t_first"] = min(tgt["t_first"], r["t_first"])
        tgt["t_last"] = max(tgt["t_last"], r["t_last"])
        tgt["i_first"] = min(tgt["i_first"], r["i_first"])
        tgt["i_last"] = max(tgt["i_last"], r["i_last"])
        if r["ocr"].get("text"):
            tgt["ocr"] = dict(tgt["ocr"])
            tgt["ocr"]["text"] = (tgt["ocr"].get("text") or "") + "\n" + r["ocr"]["text"]
        tgt["confidence"] = max(tgt["confidence"], r["confidence"])
        tgt["lines"] = tgt.get("lines", 1) + 1
    return merged


def _refine_boundary(src, rec: dict, s_times: list[float], fps: float, W: int, H: int, full_frame, which: str,
                     thr: int) -> float:
    """Refine a start/end between the neighbouring samples at the source frame rate.

    Every source frame in the gap (plus 0.5 s on the absent side) is scored by how much of the
    overlay's stroke pattern (taken at the track's middle sample) it contains; the boundary is
    where the score crosses the midpoint between the present and absent levels.  Falls back to
    the sample midpoint (error <= half a sample interval) when the scores are not bimodal.
    """
    import cv2

    u = rect_clip(rect_pad(rec["rect_text"], 2), W, H)
    if which == "start":
        lo, hi = s_times[rec["i_first"] - 1], rec["t_first"]
        w0, w1 = lo - 0.5, hi + 1.5 / fps
    else:
        lo, hi = rec["t_last"], s_times[rec["i_last"] + 1]
        w0, w1 = lo - 0.5 / fps, hi + 0.5
    fallback = round((lo + hi) / 2, 3)
    ref = cv2.cvtColor(full_frame(rec["t_mid"]), cv2.COLOR_RGB2GRAY)[u["y"]:u["y"] + u["h"], u["x"]:u["x"] + u["w"]]
    T = stroke_mask(ref, thr)
    if T.sum() < 20:
        rec.setdefault("timing", {})[which] = "sample_midpoint"
        return fallback
    k = np.ones((3, 3), np.uint8)

    def score(g: np.ndarray) -> float:
        F = cv2.dilate(stroke_mask(g, thr).astype(np.uint8), k) > 0
        hh, ww = min(F.shape[0], T.shape[0]), min(F.shape[1], T.shape[1])
        TT = T[:hh, :ww]
        return float((TT & F[:hh, :ww]).sum() / max(1, TT.sum()))

    frames = read_crop_frames(src, u, w0, w1, fps)
    sc = [(t, score(g)) for t, g in frames]
    if len(sc) < 3 or max(v for _, v in sc) - min(v for _, v in sc) < 0.3:
        rec.setdefault("timing", {})[which] = "sample_midpoint"
        return fallback
    cut = (max(v for _, v in sc) + min(v for _, v in sc)) / 2
    pres = [(t, v >= cut) for t, v in sc]
    rec.setdefault("timing", {})[which] = "source_fps"
    # (sample labels are decode-grid times; the frame actually picked may be up to half a decode
    # interval away, so transitions are searched over the whole window)
    if which == "start":
        first = None     # last absent->present transition in the window
        for (_t, p), (t2, p2) in zip(pres[:-1], pres[1:]):
            if p2 and not p:
                first = t2
        return round(first, 4) if first is not None else fallback
    last = None          # first present->absent transition in the window
    for (_t, p), (t2, p2) in zip(pres[:-1], pres[1:]):
        if p and not p2:
            last = t2
            break
    return round(last, 4) if last is not None else fallback


LINE_GROW_GAP = 1.0        # a component joins the text line when its gap to the line is <= this many line heights
LINE_WIN = 8.0             # extent search window: this many line heights left/right of the tracked text


def _grow_line(stats: np.ndarray, keep: np.ndarray, band: tuple[float, float], line_h: float) -> np.ndarray:
    """Add connected components that continue the text line horizontally.

    The blob tracker misses letters that do not look like a word on their own (a single tall
    'I', 'T', 'IT', dots), so the tracked rect can stop in the middle of a subtitle.  Starting
    from the kept components, a component joins when it lies in the line's band (>= 70 % of its
    height), is text-sized (0.2..1.6 line heights tall) and its horizontal gap to the line is
    <= LINE_GROW_GAP line heights.  Long thin scene lines and tall scene edges fail the size test."""
    keep = keep.copy()
    if not keep.any():
        return keep
    b0, b1 = band

    def ext():
        idx = np.nonzero(keep)[0]
        x0 = min(int(stats[i, 0]) for i in idx)
        x1 = max(int(stats[i, 0] + stats[i, 2]) for i in idx)
        return x0, x1

    changed = True
    while changed:
        changed = False
        x0, x1 = ext()
        for i in range(1, len(keep)):
            if keep[i]:
                continue
            x, y, w, h = (int(v) for v in stats[i, :4])
            if not (0.2 * line_h <= h <= 1.6 * line_h):
                continue
            inside = max(0, min(y + h, b1) - max(y, b0))
            if inside < 0.7 * h:
                continue
            gap = max(x - x1, x0 - (x + w))
            if gap <= LINE_GROW_GAP * line_h:
                keep[i] = True
                changed = True
                x0, x1 = min(x0, x), max(x1, x + w)
    return keep


def _refine_extent(src, u: dict, line_h: float, times: list[float], W: int, H: int, full_frame, thr: int,
                   absent_times: list[float] | None = None) -> dict:
    """Overlay extent at source resolution.

    Timed overlays with a frame of the same shot where the overlay is absent: the persistent
    difference present-vs-absent around the text (exact in static shots).  Otherwise: the
    persistent text ink (+ outline) components belonging to the text rect and, when present,
    the plate/box drawn behind it (straight persistent edges, or a brightness step with a
    constant ratio all along its sides -- a semi-transparent plate).  In both cases the extent
    follows the text line beyond the tracked rect (:func:`_grow_line`).
    """
    import cv2

    if not times:
        return {"rect": rect_clip(rect_pad(u, 0.2 * line_h + 3), W, H), "how": "text_rect_padded"}
    ts = sorted({times[int(round(q * (len(times) - 1)))] for q in (0.2, 0.5, 0.8)})
    win = rect_clip({"x": u["x"] - LINE_WIN * line_h, "y": u["y"] - 1.5 * line_h, "w": u["w"] + 2 * LINE_WIN * line_h,
                     "h": u["h"] + 3 * line_h}, W, H)

    def crop(t):
        return cv2.cvtColor(full_frame(t), cv2.COLOR_RGB2GRAY)[win["y"]:win["y"] + win["h"], win["x"]:win["x"] + win["w"]]

    grays = [crop(t) for t in ts]
    core = rect_clip(rect_pad({"x": u["x"] - win["x"], "y": u["y"] - win["y"], "w": u["w"], "h": u["h"]},
                              0.25 * line_h), win["w"], win["h"])
    core_m = np.zeros(grays[0].shape, bool)
    core_m[core["y"]:core["y"] + core["h"], core["x"]:core["x"] + core["w"]] = True
    # scene-change guard region: the old +-3 line-height neighbourhood (independent of the wider search window)
    near = rect_clip({"x": u["x"] - 3 * line_h - win["x"], "y": 0, "w": u["w"] + 6 * line_h, "h": win["h"]},
                     win["w"], win["h"])
    near_m = np.zeros(grays[0].shape, bool)
    near_m[near["y"]:near["y"] + near["h"], near["x"]:near["x"] + near["w"]] = True
    band = (u["y"] - win["y"] - 0.25 * line_h, u["y"] - win["y"] + u["h"] + 0.25 * line_h)
    k3 = np.ones((3, 3), np.uint8)
    for ta in absent_times or []:
        ga = crop(ta).astype(np.int16)
        d = np.logical_and.reduce([np.abs(g.astype(np.int16) - ga) > 30 for g in grays])
        outside = d & ~core_m & near_m
        if outside.sum() > 0.15 * max(1, (near_m & ~core_m).sum()):
            continue          # the scene itself changed: difference is not the overlay
        dd = cv2.dilate(d.astype(np.uint8), k3)
        n, lab, st, _c = cv2.connectedComponentsWithStats(dd, connectivity=8)
        keep = np.zeros(n, bool)
        for i in range(1, n):
            comp = lab == i
            if (comp & core_m).sum() >= 0.5 * comp.sum():
                keep[i] = True
        keep = _grow_line(st, keep, band, line_h)
        sel = keep[lab] & d
        ys, xs = np.nonzero(sel)
        if xs.size >= 10:
            r = {"x": xs.min() - 2 + win["x"], "y": ys.min() - 2 + win["y"], "w": xs.max() - xs.min() + 5,
                 "h": ys.max() - ys.min() + 5}
            return {"rect": rect_clip(r, W, H), "how": "difference_vs_absent_frame"}
    ink = np.logical_and.reduce([stroke_mask(g, thr) for g in grays])
    di = cv2.dilate(ink.astype(np.uint8), k3)
    n, lab, st, _c = cv2.connectedComponentsWithStats(di, connectivity=8)
    keep = np.zeros(n, bool)
    for i in range(1, n):
        comp = lab == i
        if (comp & core_m).sum() >= 0.5 * comp.sum():
            keep[i] = True
    keep = _grow_line(st, keep, band, line_h)
    ys, xs = np.nonzero(keep[lab] & ink)
    if xs.size >= 10:
        ib = {"x": int(xs.min()), "y": int(ys.min()), "w": int(xs.max() - xs.min() + 1), "h": int(ys.max() - ys.min() + 1)}
    else:
        ib = {"x": u["x"] - win["x"], "y": u["y"] - win["y"], "w": u["w"], "h": u["h"]}
    # persistent edges, tolerant to the 1-px jitter of compressed video between frames
    edges = np.logical_and.reduce([cv2.dilate((cv2.Canny(g, 30, 90) > 0).astype(np.uint8), k3) > 0 for g in grays])
    box = _find_box(edges, ib, line_h)
    how = "ink"
    if box is None:
        box = _find_plate(grays, ib, line_h)
        how_box = "ink+plate"
    else:
        how_box = "ink+box"
    r = dict(ib)
    if box is not None:
        r = rect_union([r, box])
        how = how_box
    pad = 2 if box is not None else max(3.0, 0.12 * line_h)
    r = rect_pad(r, pad)
    r["x"] += win["x"]
    r["y"] += win["y"]
    return {"rect": rect_clip(r, W, H), "how": how}


PLATE_MIN_LIGHT = 40       # px level a side must have outside the plate to see its darkening (or 255-level: lightening)
PLATE_RATIO_TOL = 0.12     # per-column inside/outside ratio must stay within this of the side's median ratio
PLATE_SIDE_SCORE = 0.7     # share of measurable columns/rows that must agree for a plate side


def _find_plate(grays: list[np.ndarray], ib: dict, line_h: float) -> dict | None:
    """Semi-transparent plate behind text (e.g. ``drawbox color=black@0.55``): along each side the
    picture is darkened (or lightened) by the SAME ratio on the inside, whatever the background.

    For each side, candidate lines within reach of the ink box are scored by the share of
    measurable columns (rows) whose inside/outside ratio stays within PLATE_RATIO_TOL of the median
    ratio in every frame, with a median ratio <= 0.8 (darkening) or, on the inverted image,
    lightening.  Among the lines that pass, the strongest step wins and, on a tie, the outermost
    (the 2-px sample bands skip the boundary, so several neighbouring lines see the same step);
    the returned edge is the outer bound, so the plate is never under-covered.  A plate needs top
    and bottom plus a vertical side with one sign; the missing vertical side falls back to the ink
    edge.  Returns a rect in ``grays`` px or None."""
    Hh, Ww = grays[0].shape
    x0, x1 = int(ib["x"]), int(ib["x"] + ib["w"])
    y0, y1 = int(ib["y"]), int(ib["y"] + ib["h"])
    reach_v = int(max(4, 1.0 * line_h))
    reach_h = int(max(6, 2.5 * line_h))
    fs = [g.astype(np.float64) for g in grays]

    def side_score(fr: np.ndarray, pos: int, horizontal: bool, inside_after: bool, lo: int, hi: int,
                   invert: bool) -> tuple[float, float] | None:
        # mean of 2 px on each side of the boundary, skipping the 2 px around it (edge blur)
        a0, a1, b0, b1 = pos - 3, pos - 1, pos + 1, pos + 3
        if a0 < 0 or b1 > (Hh if horizontal else Ww) or hi <= lo:
            return None
        if horizontal:
            out_, in_ = fr[a0:a1, lo:hi].mean(axis=0), fr[b0:b1, lo:hi].mean(axis=0)
        else:
            out_, in_ = fr[lo:hi, a0:a1].mean(axis=1), fr[lo:hi, b0:b1].mean(axis=1)
        if not inside_after:
            out_, in_ = in_, out_
        if invert:
            out_, in_ = 255.0 - out_, 255.0 - in_
        ok = out_ >= PLATE_MIN_LIGHT
        if ok.sum() < max(4, 0.5 * ok.size):
            return None
        ratio = (in_[ok] + 1.0) / (out_[ok] + 1.0)
        med = float(np.median(ratio))
        if med > 0.8:
            return 0.0, med
        return float((np.abs(ratio - med) <= PLATE_RATIO_TOL).mean()), med

    best_plate = None
    for invert in (False, True):
        found: dict[str, int] = {}
        # the inside samples must stay off the ink (a plate within 2 px of the ink is covered by the ink pad)
        for name, cands, horizontal, inside_after, lo, hi in (
                ("top", range(y0 - 3, y0 - reach_v - 3, -1), True, True, max(0, x0), min(Ww, x1)),
                ("bottom", range(y1 + 3, y1 + reach_v + 3), True, False, max(0, x0), min(Ww, x1)),
                ("left", range(x0 - 3, x0 - reach_h - 3, -1), False, True, max(0, y0), min(Hh, y1)),
                ("right", range(x1 + 3, x1 + reach_h + 3), False, False, max(0, y0), min(Hh, y1))):
            chosen, min_med = None, None
            for pos in cands:                       # inner -> outer
                res = [side_score(fr, pos, horizontal, inside_after, lo, hi, invert) for fr in fs]
                if any(v is None for v in res):
                    continue
                sc = min(v[0] for v in res)
                med = float(np.mean([v[1] for v in res]))
                if sc < PLATE_SIDE_SCORE:
                    continue
                if min_med is None or med <= min_med + 0.03:
                    chosen = pos
                    min_med = med if min_med is None else min(min_med, med)
            if chosen is not None:
                # outer bound of the boundary: top/left plate starts at >= pos-1, bottom/right ends at <= pos
                found[name] = chosen - 1 if name in ("top", "left") else chosen
        if "top" in found and "bottom" in found and ({"left", "right"} & set(found)):
            bx0 = found.get("left", x0)
            bx1 = found.get("right", x1)
            plate = {"x": bx0, "y": found["top"], "w": bx1 - bx0 + 1, "h": found["bottom"] - found["top"] + 1}
            if best_plate is None or plate["w"] * plate["h"] > best_plate["w"] * best_plate["h"]:
                best_plate = plate
    return best_plate


def _group_moving(recs: list[dict], s_times: list[float], interval: float, full_frame, W: int, H: int) -> None:
    """Mark tracks that are one mark jumping between positions (e.g. a TikTok handle).

    Two tracks belong together when one starts within two sample intervals of the other's end,
    they sit at clearly different positions, have about the same size, and look the same
    (gradient-template match >= 0.5) or read the same (OCR similarity >= 0.7).  Language-agnostic.
    """
    import cv2

    def grad(img):
        g = img.astype(np.float32)
        return cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0), cv2.Sobel(g, cv2.CV_32F, 0, 1))

    def crop(rec):
        r = rect_clip(rec["rect_text"], W, H)
        g = cv2.cvtColor(full_frame(rec["t_mid"]), cv2.COLOR_RGB2GRAY)
        return g[r["y"]:r["y"] + r["h"], r["x"]:r["x"] + r["w"]]

    parent = list(range(len(recs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, a in enumerate(recs):
        for j, b in enumerate(recs):
            if j <= i:
                continue
            first, second = (a, b) if a["t_first"] <= b["t_first"] else (b, a)
            gap = second["t_first"] - first["t_last"]
            if not (0 < gap <= 2.01 * interval):
                continue
            ra, rb = a["rect_text"], b["rect_text"]
            ca = (ra["x"] + ra["w"] / 2, ra["y"] + ra["h"] / 2)
            cb = (rb["x"] + rb["w"] / 2, rb["y"] + rb["h"] / 2)
            if np.hypot(ca[0] - cb[0], ca[1] - cb[1]) < 2 * max(a["line_h"], b["line_h"]):
                continue
            if not (0.8 <= ra["w"] / max(rb["w"], 1) <= 1.25 and 0.75 <= ra["h"] / max(rb["h"], 1) <= 1.33):
                continue
            same_text = (a["ocr"].get("text") and b["ocr"].get("text") and len(a["ocr"]["text"]) >= 4
                         and text_similarity(a["ocr"]["text"], b["ocr"]["text"]) >= 0.7)
            ga, gb = crop(a), crop(b)
            look = 0.0
            if ga.size and gb.size:
                gb = cv2.resize(gb, (ga.shape[1], ga.shape[0]), interpolation=cv2.INTER_AREA)
                ta, tb = grad(ga), grad(gb)
                if float(ta.std()) > 1e-3 and float(tb.std()) > 1e-3:
                    look = float(cv2.matchTemplate(ta, tb, cv2.TM_CCOEFF_NORMED).max())
            if same_text or look >= 0.5:
                parent[find(j)] = find(i)
                a.setdefault("group_evidence", []).append({"with_track": b["track"], "look": round(look, 3),
                                                           "same_text": bool(same_text)})
    roots: dict[int, list[int]] = {}
    for i in range(len(recs)):
        roots.setdefault(find(i), []).append(i)
    g = 0
    for members in roots.values():
        if len(members) < 2:
            continue
        g += 1
        for i in members:
            recs[i]["moving_group"] = f"mw{g}"


def _find_box(edges: np.ndarray, ib: dict, line_h: float) -> dict | None:
    """Axis-aligned plate around the ink box: strong straight edges on >= 3 sides."""
    Hh, Ww = edges.shape
    e = edges.astype(np.uint8)
    # 3-px tolerance across the line direction
    ev = np.maximum(np.maximum(e, np.roll(e, 1, 0)), np.roll(e, -1, 0))
    eh = np.maximum(np.maximum(e, np.roll(e, 1, 1)), np.roll(e, -1, 1))
    x0, x1 = int(ib["x"]), int(ib["x"] + ib["w"])
    y0, y1 = int(ib["y"]), int(ib["y"] + ib["h"])
    reach_v = int(max(4, 1.0 * line_h))
    reach_h = int(max(6, 2.5 * line_h))
    sides: dict[str, tuple[int | None, float]] = {}

    def best_row(rows, xa, xb):
        best, bs = None, 0.0
        for r in rows:
            if 0 <= r < Hh and xb > xa:
                s = float(ev[r, xa:xb].mean())
                if s > bs:
                    best, bs = r, s
        return best, bs

    def best_col(cols, ya, yb):
        best, bs = None, 0.0
        for c in cols:
            if 0 <= c < Ww and yb > ya:
                s = float(eh[ya:yb, c].mean())
                if s > bs:
                    best, bs = c, s
        return best, bs

    xa, xb = max(0, x0), min(Ww, x1)
    ya, yb = max(0, y0), min(Hh, y1)
    sides["top"] = best_row(range(y0 - 1, y0 - reach_v - 1, -1), xa, xb)
    sides["bottom"] = best_row(range(y1, y1 + reach_v), xa, xb)
    sides["left"] = best_col(range(x0 - 1, x0 - reach_h - 1, -1), ya, yb)
    sides["right"] = best_col(range(x1, x1 + reach_h), ya, yb)
    strong = {k for k, (_v, sc) in sides.items() if sc >= 0.6}
    weak = {k for k, (_v, sc) in sides.items() if sc >= 0.4}
    # a plate needs a strong corner (one horizontal + one vertical side) and a third side
    corner = bool(strong & {"top", "bottom"}) and bool(strong & {"left", "right"})
    if not (corner and len(weak) >= 3):
        return None
    found = {k: v for k, (v, _sc) in sides.items() if k in weak}
    bx0 = found.get("left", x0)
    bx1 = found.get("right", x1)
    by0 = found.get("top", y0)
    by1 = found.get("bottom", y1)
    return {"x": bx0, "y": by0, "w": bx1 - bx0 + 1, "h": by1 - by0 + 1}


def _static_graphics(shots: list[_Shot], samples: list[dict], small_size, W: int, H: int, text_overlays: list[dict],
                     prm: DetectParams) -> tuple[list[dict], list[dict], dict]:
    """Logo-like graphics without text: edges that persist while the content under them changes.

    - cross-shot: edges present in >= 85 % of the samples of two shots with different content,
      grouped into blobs whose appearance also matches between those shots;
    - moving camera: edges that stay put (low temporal variance) while the shot pans/shakes.
    A logo that exists in only one static-camera shot cannot be separated from the background:
    such shots are reported, never silently assumed clean.
    """
    import cv2

    sw_, sh_ = small_size
    fx, fy = W / sw_, H / sh_
    info = []
    stats = {}
    for sh in shots:
        row = {"id": sh.id, "start": round(sh.start, 3), "end": round(sh.end, 3), "samples": sh.n}
        if sh.n >= 2:
            mean = sh.sum / sh.n
            std = np.sqrt(np.maximum(0.0, sh.sumsq / sh.n - mean * mean))
            persist = sh.edges / sh.n
            med = float(np.median(std))
            changing = float((std > 8.0).mean())
            shift = float(np.median(sh.shifts)) if sh.shifts else 0.0
            # content moves under a fixed overlay when the camera pans/shakes or most pixels change
            row["camera"] = "moving" if (shift >= 1.0 or changing >= 0.5) else "static"
            row["median_global_shift_px"] = round(shift * W / sw_, 1)
            row["changing_frac"] = round(changing, 3)
            row["median_temporal_std"] = round(med, 2)
            stats[sh.id] = {"mean": mean, "std": std, "persist": persist, "med": med, "shot": sh, "n": sh.n}
        else:
            row["camera"] = "unmeasured"
        info.append(row)
    excl = np.zeros((sh_, sw_), bool)
    for o in text_overlays:
        r = rect_clip({"x": o["rect"]["x"] / fx - 3, "y": o["rect"]["y"] / fy - 3, "w": o["rect"]["w"] / fx + 6,
                       "h": o["rect"]["h"] / fy + 6}, sw_, sh_)
        excl[r["y"]:r["y"] + r["h"], r["x"]:r["x"] + r["w"]] = True
    min_px = max(12, int(round(40 * sw_ / 480)))
    area_total = sw_ * sh_
    ids = sorted(stats, key=lambda k: -stats[k]["n"])[:20]
    pairs = [(a, b) for i, a in enumerate(ids) for b in ids[i + 1:]
             if float(np.mean(np.abs(stats[a]["mean"] - stats[b]["mean"]))) > 20.0]
    found: list[tuple[np.ndarray, str, list[int], float, np.ndarray | None]] = []
    if pairs:
        cross = np.zeros((sh_, sw_), bool)
        for a, b in pairs:
            cross |= np.minimum(stats[a]["persist"], stats[b]["persist"]) >= 0.85
        found.append((cross & ~excl, "cross_shot_persistence", ids, 0.8, None))
    for k in ids:
        st = stats[k]
        if next(r for r in info if r["id"] == k)["camera"] == "moving" and st["n"] >= 3:
            # pixels that stay put while the picture moves; only textured blobs (edges in the mean
            # image) count, so a uniform wall that looks the same while panning is not a logo
            still = (st["std"] < max(3.0, 0.15 * st["med"])).astype(np.uint8)
            still = cv2.morphologyEx(still, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8)) > 0
            mean_edges = cv2.Canny(np.clip(st["mean"], 0, 255).astype(np.uint8), 60, 160) > 0
            found.append((still & mean_edges & ~excl, "static_over_moving_camera", [k], 0.6, still & ~excl))
    logos: list[dict] = []
    for m, method, cand_shots, conf, body in found:
        # blobs: persistent edges closed into shapes (cross-shot) / still bodies (moving camera)
        base_mask = body if body is not None else m
        cl = cv2.morphologyEx(base_mask.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        n, lab, stt, _c = cv2.connectedComponentsWithStats(cl, connectivity=8)
        for i in range(1, n):
            x, y, w, h, a = (int(v) for v in stt[i])
            comp = lab == i
            epx = int((m & comp).sum())
            need = min_px if body is None else max(10, min_px // 3)
            if epx < need or w * h > 0.05 * area_total or w > 0.4 * sw_ or h > 0.4 * sh_ or min(w, h) < 6:
                continue
            if body is not None and epx < 0.05 * w * h:
                continue
            edge_pix = m & comp
            present = [k for k in cand_shots if float((stats[k]["persist"][edge_pix] >= 0.85).mean()) >= 0.6] \
                if body is None else list(cand_shots)
            if method == "cross_shot_persistence":
                if len(present) < 2:
                    continue
                box = (slice(y, y + h), slice(x, x + w))
                spread = np.max([stats[k]["mean"][box] for k in present], axis=0) - \
                    np.min([stats[k]["mean"][box] for k in present], axis=0)
                if float(np.median(spread)) > 25.0:
                    continue
            r = {"x": x * fx, "y": y * fy, "w": w * fx, "h": h * fy}
            if method == "static_over_moving_camera" and _corner_of(r, W, H) is None and \
                    not (r["y"] < 0.25 * H or r["y"] + r["h"] > 0.75 * H or r["x"] < 0.2 * W or r["x"] + r["w"] > 0.8 * W):
                continue
            if any(rect_iou(r, lg["rect"]) > 0.3 for lg in logos):
                continue
            # one entry per contiguous run of shots that show it
            order = sorted(present or cand_shots, key=lambda k: stats[k]["shot"].start)
            runs, cur = [], [order[0]]
            all_ids = [s.id for s in shots]
            for k in order[1:]:
                if all_ids.index(k) == all_ids.index(cur[-1]) + 1:
                    cur.append(k)
                else:
                    runs.append(cur)
                    cur = [k]
            runs.append(cur)
            for run in runs:
                t0 = stats[run[0]]["shot"].start
                t1 = stats[run[-1]]["shot"].end
                t_ref = next((s["t"] for s in samples if t0 <= s["t"] <= t1), samples[0]["t"])
                logos.append({"kind": "logo", "rect": rect_clip(rect_pad(r, 2 * fx), W, H), "resolution": [W, H],
                              "start": round(t0, 3), "end": round(t1, 3), "text": None, "confidence": conf,
                              "static": True, "moving_group": None, "band": None, "corner": _corner_of(r, W, H),
                              "evidence": {"method": method, "shots": run, "edge_px": epx}, "t_ref": t_ref})
    moving = [r["id"] for r in info if r.get("camera") == "moving"]
    static = [r["id"] for r in info if r.get("camera") != "moving"]
    for r in info:
        r["static_graphic"] = "measured" if r["id"] in moving else ("cross_shot_only" if pairs and r["id"] in ids
                                                                    else "unmeasured")
    if not static:
        status = {"status": "measured", "reason": None, "shots_unmeasured": []}
    elif pairs:
        status = {"status": "partial",
                  "reason": ("고정 카메라 샷: 여러 샷에 걸친 로고는 측정함, 한 샷에만 있는 글자 없는 고정 로고는 배경과 구분 못 함 → "
                             "코너 캡처를 사람이 확인해야 함"),
                  "shots_unmeasured": static}
    else:
        status = {"status": "unmeasured",
                  "reason": ("고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → "
                             "코너 캡처를 사람이 확인해야 함"),
                  "shots_unmeasured": static}
    status["method"] = "edges persisting across shots with different content / against a moving camera"
    return info, logos, status


def _corners(overlays: list[dict], review: list[dict], graphic_status: dict, text_status: str, W: int, H: int) -> dict:
    """Per-corner presence (present/absent/unmeasured) of text overlays and text-free graphics."""
    regions = {"top_left": {"x": 0, "y": 0, "w": int(0.3 * W), "h": int(0.2 * H)},
               "top_right": {"x": int(0.7 * W), "y": 0, "w": W - int(0.7 * W), "h": int(0.2 * H)},
               "bottom_left": {"x": 0, "y": int(0.8 * H), "w": int(0.3 * W), "h": H - int(0.8 * H)},
               "bottom_right": {"x": int(0.7 * W), "y": int(0.8 * H), "w": W - int(0.7 * W), "h": H - int(0.8 * H)}}
    scope = {"measured": "all_shots", "partial": "cross_shot_only"}.get(graphic_status["status"], "none")
    out = {}
    for name, reg in regions.items():
        hits = [o["id"] for o in overlays if _overlap_frac(o["rect"], reg) > 0.3]
        rev = [r for r in review if _overlap_frac(r["rect_text"], reg) > 0.3]
        if any(o["id"] in hits and o["kind"] != "logo" for o in overlays):
            text = "present"
        else:
            text = "absent" if text_status == "measured" and not rev else "unmeasured"
        if any(o["id"] in hits and o["kind"] == "logo" for o in overlays):
            graphic = "present"
        else:
            # "absent" only when every shot could be checked for text-free logos
            graphic = "absent" if graphic_status["status"] == "measured" else "unmeasured"
        out[name] = {"region": reg, "resolution": [W, H], "overlays": hits, "text": text, "graphic": graphic,
                     "graphic_scope": scope, "review": len(rev)}
    return out


def _overlap_frac(a: dict, b: dict) -> float:
    x0, y0 = max(a["x"], b["x"]), max(a["y"], b["y"])
    x1, y1 = min(a["x"] + a["w"], b["x"] + b["w"]), min(a["y"] + a["h"], b["y"] + b["h"])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    return inter / max(1e-9, a["w"] * a["h"])


def summary_ko(doc: dict) -> str:
    """Human-readable Korean summary of an overlays document."""
    src = doc.get("source", {})
    lines = [f"소스: {src.get('path') or '(프로젝트 밖 파일)'}  sha256={src.get('sha256', '')[:12]}  "
             f"해상도={src.get('resolution')}  길이={src.get('duration')}s",
             f"샷 {len(doc.get('shots', []))}개, 분석 프레임 {doc.get('samples', {}).get('n')}개"]
    ovs = doc.get("overlays", [])
    if not ovs:
        lines.append("검출된 오버레이: 없음")
    for o in ovs:
        r = o["rect"]
        lines.append(f"  - {o['id']} {KIND_KO.get(o['kind'], o['kind'])}: x={r['x']} y={r['y']} w={r['w']} h={r['h']} "
                     f"({o['resolution'][0]}x{o['resolution'][1]} 기준) {o['start']:.2f}~{o['end']:.2f}s "
                     f"신뢰도 {o['confidence']} 글자={o.get('text')!r} 근거={o['evidence']['method']}")
    tri = {"present": "있다", "absent": "없다", "unmeasured": "못 잼"}
    names = {"top_left": "좌상단", "top_right": "우상단", "bottom_left": "좌하단", "bottom_right": "우하단"}
    for name, c in (doc.get("corners") or {}).items():
        lines.append(f"  코너 {names.get(name, name)}: 글자 오버레이={tri.get(c['text'], c['text'])}  "
                     f"글자 없는 로고={tri.get(c['graphic'], c['graphic'])}"
                     + (f"  (사람 확인 후보 {c['review']}개)" if c.get("review") else "")
                     + (f"  캡처={c['crop']}" if c.get("crop") else ""))
    st = (doc.get("checks") or {}).get("static_graphics") or {}
    if st.get("status") == "partial":
        lines.append(f"  글자 없는 고정 로고 검사: 일부만 잼 — {st.get('reason')}")
    elif st.get("status") != "measured":
        lines.append(f"  글자 없는 고정 로고 검사: 못 잼 — {st.get('reason')}")
    if doc.get("review"):
        lines.append(f"  확인 필요 후보 {len(doc['review'])}개 (review 목록)")
    return "\n".join(lines)
