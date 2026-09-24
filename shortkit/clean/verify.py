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


def _grad(g: np.ndarray) -> np.ndarray:
    import cv2

    g = g.astype(np.float32)
    return cv2.magnitude(cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3))


def residual_score(video: str | Path, rect: dict, template_png: str | Path | None, times: list[float],
                   text: str | None, *, ncc_thr: float = NCC_THR, ocr: bool = True, lang: str = "eng+kor",
                   search_pad: float = 0.25) -> dict:
    """``{max_ncc, ocr_hits, residual, status, per_time[...]}`` for one overlay rect.

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
    hits = 0
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
        if ocr:
            o = ocr_text(fr[r["y"]:r["y"] + r["h"], r["x"]:r["x"] + r["w"]], lang)
            if o.get("available"):
                ocr_ok = True
                if text:
                    sim = max([text_similarity(o["text"], text)] +
                              [text_similarity(o["text"], ln) for ln in str(text).splitlines() if ln.strip()])
                    hit = sim >= TEXT_SIM_THR and o.get("n_alnum", 0) >= 2
                    row["ocr_similarity"] = round(sim, 3)
                else:
                    hit = ocr_confirmed(o, 80)
                row["ocr_text"] = o["text"]
                row["ocr_conf"] = o.get("max_word_conf")
                row["ocr_hit"] = bool(hit)
                hits += int(hit)
            else:
                row["ocr"] = "unavailable"
        per.append(row)
    measured = max_ncc is not None or ocr_ok
    residual = None if not measured else bool((max_ncc is not None and max_ncc >= ncc_thr) or hits > 0)
    return {"max_ncc": None if max_ncc is None else round(max_ncc, 4), "ocr_hits": hits, "residual": residual,
            "status": "measured" if measured else "unmeasured", "thresholds": {"ncc": ncc_thr, "text_sim": TEXT_SIM_THR},
            "method": "gradient-NCC template match + Tesseract OCR", "rect": r, "per_time": per}


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
