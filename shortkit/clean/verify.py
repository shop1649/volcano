"""Residual checks: is an original overlay still visible in a (cleaned / final) video?

``residual_score(video, rect, template_png, times, text)`` looks at ``rect`` (px of *that*
video) at the given times and combines

- template matching of the original overlay crop (``template_png``, saved by detect.py) on
  gradient-magnitude images (``TM_CCOEFF_NORMED``; the template is resized to the rect, the
  search window is the rect grown by ``search_pad`` so small misalignment is tolerated);
- OCR of the region: a hit is OCR text similar to the overlay's known ``text`` (or, when no
  text is known, any confidently read word).

Calibrated on the synthetic dirty source (assets/test/generated): overlay present -> gradient
NCC ~1.0, removed or never present -> <= 0.15; threshold 0.5.  Also used by QA on the final
MP4 (map SOURCE rects to canvas px with :func:`source_rect_to_canvas`).

PART of an overlay left on screen (S6-9: the plate edge + 'st' of a handle, 'R IT' of a subtitle) lowers
the whole-template NCC below the threshold and OCR reads only a fragment, so two partial checks are added:
- per-tile NCC: the template is cut into about w/h tiles along the text line and each tile is searched
  near its own position; any tile >= TILE_NCC_THR is a residue.  Measured (people-detection dirty source,
  2026-09-25): overlay present 0.92-1.00, partial residue 0.70-0.83, cleaned <= 0.34 -> threshold 0.6.
  Tiles with little texture in the template (< 35 % of its mean gradient) are skipped;
- partial OCR: a word read with conf >= 60 that is a >= 3-character piece of the overlay's known text
  (letters/digits only), or a 2-character piece read with conf >= 85 ('st', 'IT').
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

import numpy as np

from .. import paths
from ..util.media import probe, read_frames
from .detect import ocr_confirmed, ocr_text, rect_clip, text_similarity

NCC_THR = 0.5
TEXT_SIM_THR = 0.6
TILE_NCC_THR = 0.6
TILE_MIN_ENERGY = 0.35
PARTIAL_CONF = 60
PARTIAL_CONF_2CH = 85


def _grad(g: np.ndarray) -> np.ndarray:
    import cv2

    g = g.astype(np.float32)
    return cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))


def _norm(s: str | None) -> str:
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def partial_text_hits(words: list, text: str | None) -> list[str]:
    """OCR words that are pieces of the overlay's known ``text`` (see module docstring)."""
    known = _norm(text)
    if len(known) < 4:
        return []
    out = []
    for w, cf in words or []:
        n = _norm(w)
        try:
            cf = float(cf)
        except (TypeError, ValueError):
            continue
        if (len(n) >= 3 and cf >= PARTIAL_CONF and n in known) or (len(n) == 2 and cf >= PARTIAL_CONF_2CH and n in known):
            out.append(str(w))
    return out


def _tile_nccs(g: np.ndarray, tg: np.ndarray, r: dict, W: int, H: int, search_pad: float) -> list[float | None]:
    """Per-tile gradient NCC of the template ``tg`` (resized to ``r``) around each tile's own position."""
    import cv2

    n = int(np.clip(round(r["w"] / max(r["h"], 1)), 1, 8))
    if n < 2:
        return []
    emean = float(tg.mean())
    out: list[float | None] = []
    for i in range(n):
        x0, x1 = i * r["w"] // n, (i + 1) * r["w"] // n
        tt = tg[:, x0:x1]
        if tt.shape[1] < 4 or float(tt.mean()) < TILE_MIN_ENERGY * emean or float(tt.std()) < 1e-3:
            out.append(None)
            continue
        px, py = int(search_pad * (x1 - x0)) + 4, int(search_pad * r["h"]) + 4
        s = rect_clip({"x": r["x"] + x0 - px, "y": r["y"] - py, "w": (x1 - x0) + 2 * px, "h": r["h"] + 2 * py}, W, H)
        reg = _grad(g[s["y"]:s["y"] + s["h"], s["x"]:s["x"] + s["w"]])
        if reg.shape[0] < tt.shape[0] or reg.shape[1] < tt.shape[1]:
            out.append(None)
            continue
        out.append(round(float(cv2.matchTemplate(reg, tt, cv2.TM_CCOEFF_NORMED).max()), 4))
    return out


def residual_score(video: str | Path, rect: dict, template_png: str | Path | None, times: list[float],
                   text: str | None, *, ncc_thr: float = NCC_THR, ocr: bool = True, lang: str = "eng+kor",
                   search_pad: float = 0.25, tile_thr: float = TILE_NCC_THR) -> dict:
    """``{max_ncc, max_tile_ncc, ocr_hits, ocr_partial_hits, residual, status, per_time[...]}`` for one
    overlay rect.  Residual = whole-template NCC >= ``ncc_thr``, or any tile NCC >= ``tile_thr``, or an OCR
    hit (similar to the known text, or a piece of it).

    ``status`` is ``unmeasured`` when neither a template nor a working OCR was available (then
    ``residual`` is None -- never reported as clean).
    """
    import cv2

    video = Path(video)
    info = probe(video)
    W, H = info.width, info.height
    r = rect_clip(rect, W, H)
    tmpl = None
    if template_png:
        tp = paths.absp(template_png) if not Path(template_png).is_absolute() else Path(template_png)
        img = cv2.imread(str(tp), cv2.IMREAD_GRAYSCALE)
        if img is not None and r["w"] >= 4 and r["h"] >= 4:
            tmpl = cv2.resize(img, (r["w"], r["h"]), interpolation=cv2.INTER_AREA) \
                if img.shape[:2] != (r["h"], r["w"]) else img
    times = [t for t in times if 0 <= t < info.duration] or [min(max(0.0, info.duration / 2), info.duration)]
    per = []
    max_ncc = None
    max_tile = None
    hits = 0
    partial = 0
    ocr_ok = False
    if r["w"] < 4 or r["h"] < 4:
        return {"max_ncc": None, "ocr_hits": 0, "residual": False, "status": "measured",
                "note": "영역이 화면 밖(잘라내기로 제거됨)", "rect": r, "per_time": []}
    frames = read_frames(video, times)
    pad_x, pad_y = int(round(search_pad * r["w"])) + 4, int(round(search_pad * r["h"])) + 4
    tg = _grad(tmpl) if tmpl is not None else None
    for t, fr in zip(times, frames):
        g = cv2.cvtColor(fr, cv2.COLOR_RGB2GRAY)
        row: dict = {"t": round(float(t), 3)}
        if tg is not None:
            s = rect_clip({"x": r["x"] - pad_x, "y": r["y"] - pad_y, "w": r["w"] + 2 * pad_x, "h": r["h"] + 2 * pad_y}, W, H)
            reg = _grad(g[s["y"]:s["y"] + s["h"], s["x"]:s["x"] + s["w"]])
            if reg.shape[0] >= tg.shape[0] and reg.shape[1] >= tg.shape[1] and float(tg.std()) > 1e-3:
                v = float(cv2.matchTemplate(reg, tg, cv2.TM_CCOEFF_NORMED).max())
                row["ncc"] = round(v, 4)
                max_ncc = v if max_ncc is None else max(max_ncc, v)
                tiles = _tile_nccs(g, tg, r, W, H, search_pad)
                if tiles:
                    row["tile_ncc"] = tiles
                    vals = [x for x in tiles if x is not None]
                    if vals:
                        max_tile = max(vals) if max_tile is None else max(max_tile, max(vals))
        if ocr:
            o = ocr_text(fr[r["y"]:r["y"] + r["h"], r["x"]:r["x"] + r["w"]], lang)
            if o.get("available"):
                ocr_ok = True
                pieces: list[str] = []
                if text:
                    sim = max([text_similarity(o["text"], text)] +
                              [text_similarity(o["text"], ln) for ln in str(text).splitlines() if ln.strip()])
                    hit = sim >= TEXT_SIM_THR and o.get("n_alnum", 0) >= 2
                    row["ocr_similarity"] = round(sim, 3)
                    if not hit:
                        pieces = partial_text_hits(o.get("words"), text)
                else:
                    hit = ocr_confirmed(o, 80)
                row["ocr_text"] = o["text"]
                row["ocr_conf"] = o.get("max_word_conf")
                row["ocr_hit"] = bool(hit)
                if pieces:
                    row["ocr_partial"] = pieces
                hits += int(hit)
                partial += int(bool(pieces))
            else:
                row["ocr"] = "unavailable"
        per.append(row)
    measured = max_ncc is not None or ocr_ok
    residual = None if not measured else bool((max_ncc is not None and max_ncc >= ncc_thr)
                                              or (max_tile is not None and max_tile >= tile_thr)
                                              or hits > 0 or partial > 0)
    return {"max_ncc": None if max_ncc is None else round(max_ncc, 4),
            "max_tile_ncc": None if max_tile is None else round(max_tile, 4),
            "ocr_hits": hits + partial, "ocr_partial_hits": partial, "residual": residual,
            "status": "measured" if measured else "unmeasured",
            "thresholds": {"ncc": ncc_thr, "tile_ncc": tile_thr, "text_sim": TEXT_SIM_THR,
                           "partial_ocr_conf": [PARTIAL_CONF, PARTIAL_CONF_2CH]},
            "method": "gradient-NCC template match (whole + per tile) + Tesseract OCR (similar text or a piece of it)",
            "rect": r, "per_time": per}


def overlay_times(o: dict, n: int = 3, duration: float | None = None) -> list[float]:
    s = float(o.get("start") or 0.0)
    e = float(o.get("end") if o.get("end") is not None else (duration or s + 1.0))
    if e <= s:
        return [s]
    return [round(s + (e - s) * q, 3) for q in np.linspace(0.2, 0.8, n)]


def map_through_clean(rect: dict, clean: dict | None) -> dict | None:
    """SOURCE rect -> rect in a video produced by ``apply_clean`` (crop shifts coordinates).
    None when the crop removed the rect entirely."""
    if not clean or not clean.get("crop"):
        return dict(rect)
    c = clean["crop"]
    x0 = max(rect["x"], c["x"])
    y0 = max(rect["y"], c["y"])
    x1 = min(rect["x"] + rect["w"], c["x"] + c["w"])
    y1 = min(rect["y"] + rect["h"], c["y"] + c["h"])
    if x1 <= x0 or y1 <= y0:
        return None
    return {"x": x0 - c["x"], "y": y0 - c["y"], "w": x1 - x0, "h": y1 - y0}


def source_rect_to_canvas(rect: dict, clip) -> dict | None:
    """SOURCE px rect -> canvas px for an IR clip (``shortkit.edit.ir.Clip`` or its dict):
    cleaning crop, then fit (cover/contain) into ``clip.region``.  Zoom is NOT applied (the rect
    is valid while no zoom is active).  None when the rect is outside the visible area."""
    g = (lambda k: clip[k]) if isinstance(clip, dict) else (lambda k: getattr(clip, k))
    sw, sh = g("src_size")
    crop = g("crop")
    crop = (crop if isinstance(crop, dict) else vars(crop)) if crop is not None else {"x": 0, "y": 0, "w": sw, "h": sh}
    reg = g("region")
    reg = reg if isinstance(reg, dict) else vars(reg)
    fit = g("fit")
    sx = reg["w"] / crop["w"]
    sy = reg["h"] / crop["h"]
    s = max(sx, sy) if fit == "cover" else min(sx, sy)
    vw, vh = crop["w"] * s, crop["h"] * s
    ox = reg["x"] + (reg["w"] - vw) / 2
    oy = reg["y"] + (reg["h"] - vh) / 2
    x0 = ox + (rect["x"] - crop["x"]) * s
    y0 = oy + (rect["y"] - crop["y"]) * s
    x1, y1 = x0 + rect["w"] * s, y0 + rect["h"] * s
    x0, y0 = max(x0, reg["x"]), max(y0, reg["y"])
    x1, y1 = min(x1, reg["x"] + reg["w"]), min(y1, reg["y"] + reg["h"])
    if x1 <= x0 or y1 <= y0:
        return None
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def verify_doc(video: str | Path, doc: dict, *, mapper: Callable[[dict], dict | None] | None = None,
               clean: dict | None = None, n_times: int = 3, ocr: bool = True) -> dict:
    """Residual check of every overlay of an overlays document in ``video``.

    ``mapper`` maps a SOURCE rect into ``video`` px (default: through ``clean``'s crop).
    Returns ``{rows: [...], residual_any, unmeasured}``; rows whose rect was cropped out are
    ``removed_by_crop`` (geometric fact, no pixels to check).
    """
    rows = []
    dur = float(doc["source"].get("duration") or 0.0)
    for o in doc.get("overlays", []):
        rr = mapper(o["rect"]) if mapper else map_through_clean(o["rect"], clean)
        row = {"overlay_id": o["id"], "kind": o["kind"], "text": o.get("text")}
        if rr is None:
            row.update({"status": "measured", "residual": False, "how": "removed_by_crop"})
        else:
            rs = residual_score(video, rr, o.get("template"), overlay_times(o, n_times, dur), o.get("text"), ocr=ocr)
            row.update({"status": rs["status"], "residual": rs["residual"], "max_ncc": rs["max_ncc"],
                        "ocr_hits": rs["ocr_hits"], "rect": rs["rect"], "how": "pixels"})
        rows.append(row)
    return {"rows": rows, "residual_any": any(r["residual"] for r in rows),
            "unmeasured": [r["overlay_id"] for r in rows if r["status"] != "measured"]}
