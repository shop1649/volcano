"""Does a plan's ``sources[].clean`` block remove every recorded overlay of its source?

The documented flow is ``clean detect`` -> ``clean plan`` -> paste the printed block into
``plan.yaml``.  Nothing downstream used to check that the pasted block still matches the overlay
record (warehouse/overlays/<source sha256>.json): a hand-written or stale block, a skipped
``clean detect`` or a record made by an older detector left original logos/subtitles on screen
(S6-9).  :func:`coverage` compares the block with the record geometrically:

- an overlay is covered at time t when every pixel of its rect (SOURCE px, eroded by ``tol_px``)
  lies outside ``clean.crop`` or inside a ``delogo``/``inpaint``/``blur`` rect active at t
  (op times are ``start <= t < end``; ``None`` = whole clip), for all t in the overlay's
  ``[start, end)`` -- restricted to ``used_ranges`` (the source times the episode shows) and to
  ``visible`` (the source area the renderer shows) when given;
- time slivers shorter than half a source frame are ignored (rounding of stored times).

Returned entries (list, empty = everything covered)::

    {code, blocking, overlay_id, kind, text, rect, resolution, start, end,
     uncovered_frac, uncovered_px, uncovered_rect, uncovered_times, reason}

``code``: ``uncovered`` (blocking), ``no_record`` / ``source_missing`` / ``record_stale``
(blocking: the check itself cannot be trusted -> run ``clean detect`` again),
``text_unmeasured`` (not blocking: OCR was unavailable, so text overlays may be missing from the
record -- 못 잼), ``review_uncovered`` (not blocking: an unconfirmed text candidate a person must
look at is not removed by the block).
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np

OPS = ("delogo", "inpaint", "blur")


def _abs(source_path: str | Path) -> Path:
    from .. import paths

    p = Path(source_path)
    return p if p.is_absolute() else paths.absp(str(source_path))


def _ranges_overlap(a0: float, a1: float, ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    out = []
    for r0, r1 in ranges:
        lo, hi = max(a0, r0), min(a1, r1)
        if hi > lo:
            out.append((lo, hi))
    return out


def _px_box(r: dict, W: int, H: int, erode: float = 0.0) -> tuple[int, int, int, int]:
    """Pixel index box [x0, x1) x [y0, y1) of the pixels a (float) rect covers, eroded by ``erode`` px."""
    x0 = max(0, int(np.ceil(r["x"] + erode - 1e-6)))
    y0 = max(0, int(np.ceil(r["y"] + erode - 1e-6)))
    x1 = min(W, int(np.floor(r["x"] + r["w"] - erode + 1e-6)))
    y1 = min(H, int(np.floor(r["y"] + r["h"] - erode + 1e-6)))
    return x0, y0, max(x0, x1), max(y0, y1)


def _op_active(op: dict, a: float, b: float, eps: float) -> bool:
    s, e = op.get("start"), op.get("end")
    return (s is None or float(s) <= a + eps) and (e is None or float(e) >= b - eps)


def _uncovered_mask(box: tuple[int, int, int, int], clean: dict, ops: list[dict], visible: dict | None) -> np.ndarray:
    x0, y0, x1, y1 = box
    m = np.ones((y1 - y0, x1 - x0), bool)
    if m.size == 0:
        return m

    def cut(r: dict, inside: bool) -> None:
        rx0, ry0 = int(np.floor(r["x"])), int(np.floor(r["y"]))
        rx1, ry1 = int(np.ceil(r["x"] + r["w"])), int(np.ceil(r["y"] + r["h"]))
        ix0, iy0 = max(x0, rx0) - x0, max(y0, ry0) - y0
        ix1, iy1 = min(x1, rx1) - x0, min(y1, ry1) - y0
        if inside:                        # pixels inside r are removed from the "still visible" mask
            if ix1 > ix0 and iy1 > iy0:
                m[iy0:iy1, ix0:ix1] = False
        else:                             # pixels OUTSIDE r are removed (crop / not shown)
            keep = np.zeros_like(m)
            if ix1 > ix0 and iy1 > iy0:
                keep[iy0:iy1, ix0:ix1] = True
            np.logical_and(m, keep, out=m)

    crop = (clean or {}).get("crop")
    if crop:
        cut(crop, inside=False)
    if visible:
        cut(visible, inside=False)
    for op in ops:
        cut(op, inside=True)
    return m


def _segments(t0: float, t1: float, ops: list[dict]) -> list[tuple[float, float]]:
    pts = {t0, t1}
    for op in ops:
        for k in ("start", "end"):
            v = op.get(k)
            if v is not None and t0 < float(v) < t1:
                pts.add(float(v))
    pts = sorted(pts)
    return list(zip(pts[:-1], pts[1:]))


def _check_rect(o: dict, clean: dict, ranges: list[tuple[float, float]], W: int, H: int, eps: float,
                tol_px: float, visible: dict | None) -> dict | None:
    ops = [dict(op) for k in OPS for op in ((clean or {}).get(k) or [])]
    box = _px_box(o["rect"], W, H, tol_px)
    area = max(1, (box[2] - box[0]) * (box[3] - box[1]))
    worst, worst_mask, bad_times = 0, None, []
    for a0, a1 in ranges:
        for a, b in _segments(a0, a1, ops):
            if b - a <= eps:
                continue
            active = [op for op in ops if _op_active(op, a, b, eps)]
            m = _uncovered_mask(box, clean, active, visible)
            n = int(m.sum())
            if n:
                bad_times.append([round(a, 3), round(b, 3)])
                if n > worst:
                    worst, worst_mask = n, m
    if not worst:
        return None
    ys, xs = np.nonzero(worst_mask)
    ur = {"x": int(box[0] + xs.min()), "y": int(box[1] + ys.min()), "w": int(xs.max() - xs.min() + 1),
          "h": int(ys.max() - ys.min() + 1)}
    return {"uncovered_frac": round(worst / area, 4), "uncovered_px": worst, "uncovered_rect": ur,
            "uncovered_times": bad_times}


def coverage_report(source_path: str | Path, clean_block: dict | None, *, sha256: str | None = None,
                    used_ranges: Iterable[Iterable[float]] | None = None, visible: dict | None = None,
                    tol_px: float = 1.0) -> dict:
    """Full result: ``{status, source, sha256, record, algo, uncovered[], covered[], checked_at}``
    (``uncovered`` is what :func:`coverage` returns)."""
    from .. import paths
    from ..util.hashing import sha256_file
    from ..util.jsonio import now_iso
    from .detect import ALGO, KIND_KO, load_overlays, overlays_path

    src = _abs(source_path)
    out: dict = {"source": str(source_path), "sha256": sha256, "record": None, "algo": None, "uncovered": [],
                 "covered": [], "checked_at": now_iso()}

    def problem(code: str, reason: str, blocking: bool = True, **kw) -> dict:
        e = {"code": code, "blocking": blocking, "overlay_id": None, "kind": None, "text": None, "reason": reason, **kw}
        out["uncovered"].append(e)
        return e

    if sha256 is None:
        if not src.is_file():
            problem("source_missing", f"소스 파일이 없어 오버레이 기록을 찾을 수 없음: {source_path}")
            out["status"] = "unmeasured"
            return out
        sha256 = sha256_file(src)
    out["sha256"] = sha256
    doc = load_overlays(sha256)
    if not doc or "overlays" not in doc or not doc.get("algo"):
        problem("no_record", f"오버레이 기록 없음(warehouse/overlays/{sha256[:12]}….json) → "
                             f"`python -m shortkit clean detect --source {source_path}` 후 `clean plan` 결과를 붙여야 함")
        out["status"] = "unmeasured"
        return out
    try:
        out["record"] = paths.relp(overlays_path(sha256))
    except ValueError:
        out["record"] = None
    out["algo"] = doc.get("algo")
    if doc.get("algo") != ALGO:
        problem("record_stale", f"이전 검출 알고리즘({doc.get('algo')}) 기록 — 현재 {ALGO} 는 글자 줄 조각·반투명 판까지 "
                                f"잡음 → `clean detect` 다시 실행 후 `clean plan` 결과로 clean 블록을 바꿔야 함")
    src_info = doc.get("source") or {}
    W, H = (src_info.get("resolution") or [0, 0])[:2]
    dur = float(src_info.get("duration") or 0.0)
    fps = float(src_info.get("fps") or 30.0)
    eps = 0.5 / max(fps, 1.0)
    ranges_all = [(float(a), float(b)) for a, b in (used_ranges or [(0.0, dur or 1e9)])]
    clean = dict(clean_block or {})
    for o in doc.get("overlays") or []:
        if o.get("ignored"):
            continue
        rres = o.get("resolution") or [W, H]
        oo = dict(o)
        if [int(rres[0]), int(rres[1])] != [int(W), int(H)] and rres[0] and rres[1]:
            kx, ky = W / float(rres[0]), H / float(rres[1])
            oo["rect"] = {"x": o["rect"]["x"] * kx, "y": o["rect"]["y"] * ky, "w": o["rect"]["w"] * kx,
                          "h": o["rect"]["h"] * ky}
        s = float(o.get("start") or 0.0)
        e = float(o["end"]) if o.get("end") is not None else (dur or 1e9)
        ranges = _ranges_overlap(s, e, ranges_all)
        if not ranges:
            out["covered"].append({"overlay_id": o.get("id"), "how": "not_in_used_source_time"})
            continue
        res = _check_rect(oo, clean, ranges, int(W), int(H), eps, tol_px, visible)
        if res is None:
            out["covered"].append({"overlay_id": o.get("id"), "how": "clean_block"})
            continue
        out["uncovered"].append({
            "code": "uncovered", "blocking": True, "overlay_id": o.get("id"), "kind": o.get("kind"),
            "text": o.get("text"), "rect": o.get("rect"), "resolution": rres, "start": o.get("start"),
            "end": o.get("end"), **res,
            "reason": (f"{o.get('id')} {KIND_KO.get(o.get('kind'), o.get('kind'))}"
                       + (f" '{o.get('text')}'" if o.get("text") else "")
                       + f": clean 블록이 {res['uncovered_frac']:.0%} ({res['uncovered_px']}px, "
                         f"x={res['uncovered_rect']['x']} y={res['uncovered_rect']['y']} "
                         f"w={res['uncovered_rect']['w']} h={res['uncovered_rect']['h']}, {W}x{H} 기준)를 "
                         f"{res['uncovered_times'][0][0]}~{res['uncovered_times'][-1][1]}s 에 남김 → "
                         f"`clean plan` 결과를 다시 붙이기")})
    for i, rv in enumerate(doc.get("review") or []):
        r = rv.get("rect")
        if not r:
            continue
        ranges = _ranges_overlap(float(rv.get("t_first") or 0.0), float(rv.get("t_last") or dur) + eps * 2, ranges_all)
        if not ranges:
            continue
        res = _check_rect({"rect": r}, clean, ranges, int(W), int(H), eps, tol_px, visible)
        if res is not None:
            problem("review_uncovered", f"확인 필요 글자 후보 review[{i}] '{rv.get('ocr_text')}' "
                                        f"(x={r['x']} y={r['y']} w={r['w']} h={r['h']}) 가 제거되지 않음 → 사람이 보고 "
                                        "원본 오버레이면 clean 블록에 추가", blocking=False, rect=r, **res)
    to = (doc.get("checks") or {}).get("text_overlays") or {}
    if to.get("status") != "measured":
        problem("text_unmeasured", "이 기록은 글자 오버레이 검사를 못 잼(OCR 없음) → 글자 워터마크·원어 자막이 기록에 빠졌을 수 "
                                   "있음(사람 확인 필요)", blocking=False)
    out["status"] = "measured"
    return out


def coverage(source_path: str | Path, clean_block: dict | None, **kw) -> list[dict]:
    """Recorded overlays of ``source_path`` that ``clean_block`` does not remove (plus entries for
    problems that make the check impossible).  Empty list = every recorded overlay is covered.
    Keyword options: ``sha256``, ``used_ranges`` [[src_in, src_out], ...], ``visible`` (SOURCE rect
    the renderer shows), ``tol_px``.  ``episode validate`` must error on entries with ``blocking``."""
    return coverage_report(source_path, clean_block, **kw)["uncovered"]


def summary_ko(entries: list[dict]) -> str:
    if not entries:
        return "clean 블록이 기록된 오버레이를 모두 덮음"
    return "\n".join(("  ✗ " if e.get("blocking") else "  ! ") + e["reason"] for e in entries)
