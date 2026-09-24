"""Decide how each detected overlay is removed, in the user's order:

1. a clean original exists (warehouse record ``alternates``: same content without the overlay,
   verified by its own overlay detection) -> use that file instead;
2. crop -- only when the overlay sits in a frame margin, the crop keeps every protected region
   (faces, plan-protected people/objects) whole, keeps the important motion, and the remaining
   frame still fills the target video region (crop aspect = region aspect, so ``cover`` and
   ``contain`` both fill it);
3. local restoration -- ``delogo`` for small static graphic logos, ``inpaint`` (OpenCV Telea,
   temporal clean-plate assisted) for text / subtitles / other overlays;
   ``blur`` only as the last resort (region too large to restore).

The result contains the plan-ready ``clean`` block (SOURCE px / SOURCE time, matching
``sources[].clean`` in plan.schema.json), plan-ready ``protected`` rects and a rationale list.
Crop is refused outright when faces could not be measured (never guess that nobody is there).
"""
from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass
from typing import Any, Iterable

import numpy as np

from ..util.jsonio import now_iso
from .detect import KIND_KO, rect_iou, rect_pad, time_overlap

SCHEMA = "shortkit.clean_plan/1"
ACTION_KO = {"alternate": "깨끗한 원본 사용", "crop": "잘라내기", "delogo": "로고 지움(delogo)",
             "inpaint": "국소 복원(inpaint)", "blur": "흐림(최후 수단)", "unresolved": "처리 못 함"}


@dataclass
class CleanPolicy:
    margin_frac: float = 0.2            # overlay must lie within this fraction of the frame from the cut side
    crop_pad_px: float = 6.0            # extra px cut beyond the overlay edge
    protected_margin_frac: float = 0.1  # margin kept around protected rects (fraction of their size)
    min_keep_frac: float = 0.7          # crop area / area the fit would show without cleaning
    min_activity_keep: float = 0.9      # share of motion energy (inside the default view) the crop keeps
    max_upscale: float = 1.5            # region px / crop px (checked only when the region size is known)
    delogo_max_area_frac: float = 0.02  # delogo only for small static graphic logos
    inpaint_max_area_frac: float = 0.12 # larger areas cannot be restored credibly -> blur (last resort)
    alt_match_iou: float = 0.3


# ----------------------------------------------------------------------------- helpers
def region_from_preset(preset) -> dict:
    """Target video region from the preset (``canvas.video_region``), read through Preset.get."""
    w = float(preset.get("canvas.video_region.w"))
    h = float(preset.get("canvas.video_region.h"))
    fit = str(preset.get("canvas.video_region.fit"))
    return {"aspect": w / h, "fit": fit, "size": [w, h], "source": "preset:canvas.video_region"}


def parse_aspect(s: str | float) -> float:
    if isinstance(s, (int, float)):
        return float(s)
    s = str(s).strip()
    for sep in (":", "/", "x"):
        if sep in s:
            a, b = s.split(sep, 1)
            return float(a) / float(b)
    return float(s)


def default_view(W: int, H: int, aspect: float, fit: str) -> dict:
    """Source area the renderer shows without a cleaning crop."""
    if fit == "contain":
        return {"x": 0.0, "y": 0.0, "w": float(W), "h": float(H)}
    w = min(float(W), H * aspect)
    h = w / aspect
    return {"x": (W - w) / 2, "y": (H - h) / 2, "w": w, "h": h}


def _contains(outer: dict, inner: dict, tol: float = 0.5) -> bool:
    return (inner["x"] >= outer["x"] - tol and inner["y"] >= outer["y"] - tol
            and inner["x"] + inner["w"] <= outer["x"] + outer["w"] + tol
            and inner["y"] + inner["h"] <= outer["y"] + outer["h"] + tol)


def _disjoint(a: dict, b: dict) -> bool:
    return (a["x"] + a["w"] <= b["x"] or b["x"] + b["w"] <= a["x"] or
            a["y"] + a["h"] <= b["y"] or b["y"] + b["h"] <= a["y"])


def _activity_in(act: dict | None, r: dict, W: int, H: int) -> float:
    if not act or not act.get("values"):
        return 0.0
    v = np.asarray(act["values"], dtype=np.float64)
    gh, gw = v.shape
    x0, x1 = r["x"] / W * gw, (r["x"] + r["w"]) / W * gw
    y0, y1 = r["y"] / H * gh, (r["y"] + r["h"]) / H * gh
    # fractional cell coverage
    cx = np.clip(np.minimum(np.arange(gw) + 1, x1) - np.maximum(np.arange(gw), x0), 0, 1)
    cy = np.clip(np.minimum(np.arange(gh) + 1, y1) - np.maximum(np.arange(gh), y0), 0, 1)
    return float((v * cy[:, None] * cx[None, :]).sum())


def protected_with_margin(prot: Iterable[dict], W: int, H: int, frac: float) -> list[dict]:
    out = []
    for p in prot:
        m = max(p["w"], p["h"]) * frac
        r = rect_pad(p, m)
        x0, y0 = max(0.0, r["x"]), max(0.0, r["y"])
        x1, y1 = min(float(W), r["x"] + r["w"]), min(float(H), r["y"] + r["h"])
        out.append({**p, "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0})
    return out


def validate_crop(crop: dict, W: int, H: int, *, protected: list[dict], region_aspect: float, fit: str,
                  activity: dict | None = None, policy: CleanPolicy | None = None,
                  region_size: list[float] | None = None) -> dict:
    """Check a cleaning crop against the hard rules. ``{ok, reasons[], keep_frac, activity_keep}``.

    - every protected rect (+margin) must be entirely inside the crop (never cut people/objects);
    - the crop must fill the target region (aspect == region aspect);
    - it must keep ``min_keep_frac`` of the default view and ``min_activity_keep`` of its motion;
    - it must not force more than ``max_upscale`` when the region size is known.
    """
    pol = policy or CleanPolicy()
    reasons = []
    if crop["x"] < -0.5 or crop["y"] < -0.5 or crop["x"] + crop["w"] > W + 0.5 or crop["y"] + crop["h"] > H + 0.5:
        reasons.append("잘라낼 영역이 원본 화면 밖으로 나감")
    for p in protected_with_margin(protected, W, H, pol.protected_margin_frac):
        if not _contains(crop, p):
            reasons.append(f"보호 영역({p.get('label', 'face')}) 이 잘림: x={p['x']:.0f} y={p['y']:.0f} "
                           f"w={p['w']:.0f} h={p['h']:.0f}")
    asp = crop["w"] / max(crop["h"], 1e-9)
    if abs(asp / region_aspect - 1) > 0.01:
        reasons.append(f"비율 {asp:.4f} ≠ 영상 영역 비율 {region_aspect:.4f} → 영역을 꽉 채우지 못함")
    view = default_view(W, H, region_aspect, fit)
    keep = (crop["w"] * crop["h"]) / max(view["w"] * view["h"], 1e-9)
    if keep < pol.min_keep_frac:
        reasons.append(f"남는 면적 {keep:.0%} < 최소 {pol.min_keep_frac:.0%} (확대가 너무 큼)")
    a_view = _activity_in(activity, view, W, H)
    a_crop = _activity_in(activity, crop, W, H)
    act_keep = 1.0 if a_view <= 1e-9 else min(1.0, a_crop / a_view)
    if act_keep < pol.min_activity_keep:
        reasons.append(f"움직임(중요 동작) {act_keep:.0%} 만 남음 < {pol.min_activity_keep:.0%}")
    if region_size:
        up = region_size[0] / max(crop["w"], 1e-9)
        base_up = region_size[0] / max(view["w"], 1e-9)
        if up > pol.max_upscale and up > base_up * 1.0001:
            reasons.append(f"확대 배율 {up:.2f} > {pol.max_upscale}")
    return {"ok": not reasons, "reasons": reasons, "keep_frac": round(keep, 4), "activity_keep": round(act_keep, 4)}


def _even_floor(v: float) -> int:
    i = int(np.floor(v))
    return i - (i % 2)


def _best_crop_in_box(box: dict, aspect: float, prot: list[dict], W: int, H: int, act: dict | None) -> dict | None:
    """Largest region-aspect rect inside ``box`` containing all protected rects, positioned at
    the motion centroid (or the box centre) as far as the protected rects allow."""
    bw, bh = box["w"], box["h"]
    if bw <= 2 or bh <= 2:
        return None
    w = min(bw, bh * aspect)
    h = w / aspect
    wi, hi = _even_floor(w), _even_floor(h)
    # keep the exact aspect after integer rounding (shrink to the nearest consistent pair)
    for _ in range(64):
        if abs((wi / max(hi, 1)) / aspect - 1) <= 0.004:
            break
        if wi / max(hi, 1) > aspect:
            wi -= 2
        else:
            hi -= 2
    if wi <= 2 or hi <= 2:
        return None
    if prot:
        px0 = min(p["x"] for p in prot)
        py0 = min(p["y"] for p in prot)
        px1 = max(p["x"] + p["w"] for p in prot)
        py1 = max(p["y"] + p["h"] for p in prot)
        lo_x, hi_x = max(box["x"], px1 - wi), min(box["x"] + bw - wi, px0)
        lo_y, hi_y = max(box["y"], py1 - hi), min(box["y"] + bh - hi, py0)
    else:
        lo_x, hi_x = box["x"], box["x"] + bw - wi
        lo_y, hi_y = box["y"], box["y"] + bh - hi
    if lo_x > hi_x + 1e-6 or lo_y > hi_y + 1e-6:
        return None
    cx, cy = box["x"] + bw / 2, box["y"] + bh / 2
    if act and act.get("values"):
        v = np.asarray(act["values"], dtype=np.float64)
        if v.sum() > 0:
            gh, gw = v.shape
            cx = float((v.sum(axis=0) * (np.arange(gw) + 0.5)).sum() / v.sum()) * W / gw
            cy = float((v.sum(axis=1) * (np.arange(gh) + 0.5)).sum() / v.sum()) * H / gh
    x = float(np.clip(cx - wi / 2, lo_x, hi_x))
    y = float(np.clip(cy - hi / 2, lo_y, hi_y))
    xi = int(np.ceil(x)) if int(np.ceil(x)) <= hi_x else int(np.floor(x))
    yi = int(np.ceil(y)) if int(np.ceil(y)) <= hi_y else int(np.floor(y))
    return {"x": xi, "y": yi, "w": wi, "h": hi}


def _margin_sides(r: dict, W: int, H: int, frac: float) -> list[str]:
    sides = []
    if r["y"] + r["h"] <= frac * H:
        sides.append("top")
    if r["y"] >= (1 - frac) * H:
        sides.append("bottom")
    if r["x"] + r["w"] <= frac * W:
        sides.append("left")
    if r["x"] >= (1 - frac) * W:
        sides.append("right")
    return sides


def _cut_box(assign: list[tuple[dict, str]], W: int, H: int, pad: float) -> dict:
    x0, y0, x1, y1 = 0.0, 0.0, float(W), float(H)
    for ov, side in assign:
        r = ov["rect"]
        if side == "top":
            y0 = max(y0, r["y"] + r["h"] + pad)
        elif side == "bottom":
            y1 = min(y1, r["y"] - pad)
        elif side == "left":
            x0 = max(x0, r["x"] + r["w"] + pad)
        else:
            x1 = min(x1, r["x"] - pad)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def _alt_is_clean_for(ov: dict, alt_doc: dict, W: int, H: int, pol: CleanPolicy) -> bool:
    aw, ah = alt_doc["source"]["resolution"]
    nr = {"x": ov["rect"]["x"] / W, "y": ov["rect"]["y"] / H, "w": ov["rect"]["w"] / W, "h": ov["rect"]["h"] / H}
    for o in alt_doc.get("overlays", []):
        r = o["rect"]
        na = {"x": r["x"] / aw, "y": r["y"] / ah, "w": r["w"] / aw, "h": r["h"] / ah}
        if rect_iou(nr, na) >= pol.alt_match_iou and time_overlap(ov["start"], ov["end"], o["start"], o["end"]) > 0:
            return False
    return True


def _alt_measured(alt_doc: dict) -> bool:
    ch = alt_doc.get("checks") or {}
    return (ch.get("text_overlays") or {}).get("status") == "measured"


# ----------------------------------------------------------------------------- main
def plan_clean(doc: dict, *, region_aspect: float, fit: str = "cover", faces: dict | None = None,
               protected: list[dict] | None = None, alternates: list[dict] | None = None,
               policy: CleanPolicy | None = None, region_size: list[float] | None = None) -> dict:
    """Plan the cleaning of one source.

    ``doc``: overlays document (detect.py).  ``faces``: faces.detect_faces() result.
    ``protected``: extra plan-protected rects (SOURCE px/time).  ``alternates``:
    ``[{path, sha256, warehouse_id?, overlays: <overlays doc of that file or None>}]``.
    """
    pol = policy or CleanPolicy()
    W, H = doc["source"]["resolution"]
    dur = float(doc["source"].get("duration") or 0.0)
    ovs = [o for o in doc.get("overlays", []) if not o.get("ignored")]
    rationale: list[str] = []
    warnings: list[str] = []
    decisions: list[dict] = []
    ch = doc.get("checks") or {}
    if (ch.get("text_overlays") or {}).get("status") != "measured":
        warnings.append("글자 오버레이 검출을 못 잼(OCR 없음) → 남은 오버레이가 있을 수 있음")
    if (ch.get("static_graphics") or {}).get("status") != "measured":
        warnings.append("글자 없는 고정 로고 검사 못 잼(" + str((ch.get("static_graphics") or {}).get("reason")) +
                        ") → corners 캡처를 사람이 확인해야 함")
    if doc.get("review"):
        warnings.append(f"확인되지 않은 글자 후보 {len(doc['review'])}개(review) → 사람이 확인해야 함")

    # ---- protected regions
    prot: list[dict] = []
    faces_status = (faces or {}).get("status", "unmeasured")
    if faces and faces_status == "measured":
        fr = faces.get("resolution") or [W, H]
        sx, sy = W / fr[0], H / fr[1]
        for p in faces.get("protected", []):
            prot.append({"label": p.get("label", "face"), "x": p["x"] * sx, "y": p["y"] * sy, "w": p["w"] * sx,
                         "h": p["h"] * sy, "start": p.get("start"), "end": p.get("end")})
    for p in protected or []:
        prot.append({"label": p.get("label", "protected"), "x": float(p["x"]), "y": float(p["y"]), "w": float(p["w"]),
                     "h": float(p["h"]), "start": p.get("start"), "end": p.get("end")})
    crop_allowed = faces_status == "measured"
    if not crop_allowed:
        rationale.append("얼굴 검출 못 잼 → 사람이 잘릴 수 있으므로 잘라내기 금지(국소 복원만 사용)")

    base = {"schema": SCHEMA, "created_at": now_iso(),
            "source": {k: doc["source"].get(k) for k in ("path", "sha256", "resolution", "duration")},
            "region": {"aspect": round(region_aspect, 6), "fit": fit, "size": region_size},
            "policy": asdict(pol), "faces_status": faces_status,
            "protected": [{k: (round(v, 1) if isinstance(v, float) and k in ("x", "y", "w", "h") else v)
                           for k, v in p.items() if k in ("label", "x", "y", "w", "h", "start", "end")} for p in prot]}

    # ---- (1) clean original
    for alt in alternates or []:
        adoc = alt.get("overlays")
        if not adoc:
            rationale.append(f"대체 원본 {alt.get('path') or alt.get('sha256')}: 오버레이 검출 기록 없음 → 깨끗한지 못 잼, 사용 안 함")
            continue
        if not _alt_measured(adoc):
            rationale.append(f"대체 원본 {alt.get('path')}: 글자 검사 못 잼 → 사용 안 함")
            continue
        if ovs and all(_alt_is_clean_for(o, adoc, W, H, pol) for o in ovs):
            sub = plan_clean(adoc, region_aspect=region_aspect, fit=fit, faces=alt.get("faces"),
                             protected=None, alternates=None, policy=pol, region_size=region_size)
            sub["replace_source"] = {"path": alt.get("path"), "sha256": alt.get("sha256"),
                                     "warehouse_id": alt.get("warehouse_id"),
                                     "reason": "같은 내용의 오버레이 없는 원본(창고 기록 alternates, 자체 검출로 확인)"}
            sub["replaced"] = base["source"]
            if protected:
                sub["warnings"].append("plan 의 보호 영역은 교체 전 원본 좌표 → 대체 원본 기준으로 다시 지정해야 함")
                sub["status"] = "needs_review"
                sub["review_reasons"] = list(sub.get("review_reasons") or []) + [sub["warnings"][-1]]
            sub["decisions"] = [{"overlay_id": o["id"], "kind": o["kind"], "action": "alternate",
                                 "reason": "대체 원본에는 이 오버레이가 없음"} for o in ovs] + sub["decisions"]
            sub["rationale"] = [f"{o['id']} {KIND_KO.get(o['kind'])}: 깨끗한 원본 있음 → 원본 교체" for o in ovs] + \
                rationale + sub["rationale"]
            return sub
        rationale.append(f"대체 원본 {alt.get('path')}: 같은 위치에 오버레이가 있음 → 사용 안 함")

    # ---- (2) crop
    crop = None
    removed_by_crop: set[str] = set()
    crop_check = None
    if crop_allowed and ovs:
        prot_m = protected_with_margin(prot, W, H, pol.protected_margin_frac)
        cands = [(o, _margin_sides(o["rect"], W, H, pol.margin_frac)) for o in ovs]
        cands = [(o, s) for o, s in cands if s]
        for o in ovs:
            if not _margin_sides(o["rect"], W, H, pol.margin_frac):
                decisions.append({"overlay_id": o["id"], "kind": o["kind"], "action": "crop_rejected",
                                  "reason": "화면 가장자리 여백에 있지 않음"})
        best = None
        n = min(len(cands), 8)
        tried = 0
        for k in range(n, 0, -1):
            for subset in itertools.combinations(cands[:8], k):
                for sides in itertools.product(*[s for _o, s in subset]):
                    tried += 1
                    box = _cut_box([(o, sd) for (o, _s), sd in zip(subset, sides)], W, H, pol.crop_pad_px)
                    c = _best_crop_in_box(box, region_aspect, prot_m, W, H, doc.get("activity"))
                    if c is None:
                        continue
                    v = validate_crop(c, W, H, protected=prot, region_aspect=region_aspect, fit=fit,
                                      activity=doc.get("activity"), policy=pol, region_size=region_size)
                    if not v["ok"]:
                        continue
                    removed = {o["id"] for o in ovs if _disjoint(o["rect"], c)}
                    score = (len(removed), c["w"] * c["h"])
                    if best is None or score > best[0]:
                        best = (score, c, removed, v, [(o["id"], sd) for (o, _s), sd in zip(subset, sides)])
        if best is not None:
            _, crop, removed_by_crop, crop_check, cuts = best
            crop_check["cuts"] = [{"overlay_id": i, "side": s} for i, s in cuts]
            # explain why the remaining croppable overlays could not be cut away as well
            for o, sides in cands:
                if o["id"] in removed_by_crop:
                    continue
                for sd in sides:
                    box = _cut_box([(next(x for x, _ in cands if x["id"] == i), s) for i, s in cuts] + [(o, sd)],
                                   W, H, pol.crop_pad_px)
                    c = _best_crop_in_box(box, region_aspect, prot_m, W, H, doc.get("activity"))
                    why = ["보호 영역을 모두 담는 비율 맞는 잘라내기 불가"] if c is None else \
                        validate_crop(c, W, H, protected=prot, region_aspect=region_aspect, fit=fit,
                                      activity=doc.get("activity"), policy=pol, region_size=region_size)["reasons"]
                    decisions.append({"overlay_id": o["id"], "kind": o["kind"], "action": "crop_rejected",
                                      "side": sd, "reason": "; ".join(why) or "더 작은 잘라내기가 더 많은 오버레이를 제거"})
            rationale.append(f"잘라내기 {crop['w']}x{crop['h']}+{crop['x']}+{crop['y']} (원본 {W}x{H} 기준): "
                             f"보호 영역 {len(prot)}개 모두 포함, 남는 면적 {crop_check['keep_frac']:.0%}, "
                             f"움직임 {crop_check['activity_keep']:.0%} 유지, 영상 영역({fit}) 꽉 채움")
        elif cands:
            rationale.append("잘라내기 후보 모두 규칙 위반(보호 영역 잘림/남는 면적 부족/움직임 손실/비율) → 국소 복원")
            # record why the single-overlay crops failed (for the report)
            for o, sides in cands:
                for sd in sides:
                    box = _cut_box([(o, sd)], W, H, pol.crop_pad_px)
                    c = _best_crop_in_box(box, region_aspect, prot_m, W, H, doc.get("activity"))
                    why = ["보호 영역을 모두 담는 비율 맞는 잘라내기 불가"] if c is None else \
                        validate_crop(c, W, H, protected=prot, region_aspect=region_aspect, fit=fit,
                                      activity=doc.get("activity"), policy=pol, region_size=region_size)["reasons"]
                    decisions.append({"overlay_id": o["id"], "kind": o["kind"], "action": "crop_rejected",
                                      "side": sd, "reason": "; ".join(why)})

    # ---- (3) local restoration for the rest
    clean: dict[str, Any] = {"crop": crop, "delogo": [], "inpaint": [], "blur": []}
    frame_area = float(W * H)
    for o in ovs:
        if o["id"] in removed_by_crop:
            decisions.append({"overlay_id": o["id"], "kind": o["kind"], "action": "crop",
                              "reason": "잘라내기 영역 밖으로 빠짐", "rect": o["rect"]})
            rationale.append(f"{o['id']} {KIND_KO.get(o['kind'])} ({_where(o, W, H)}, {o['start']:.2f}~{o['end']:.2f}s): "
                             "깨끗한 원본 없음 → 잘라내기로 제거")
            continue
        r = o["rect"]
        area = r["w"] * r["h"] / frame_area
        whole = o["start"] <= 0.05 and o["end"] >= dur - 0.05
        t0 = None if whole else round(float(o["start"]), 3)
        t1 = None if whole else round(float(o["end"]), 3)
        overlaps_face = [p for p in prot if not _disjoint(p, r) and time_overlap(p.get("start"), p.get("end"), o["start"],
                                                                                  o["end"]) > 0]
        if o["kind"] == "logo" and o.get("static", True) and area <= pol.delogo_max_area_frac:
            action = "delogo"
            rr = _delogo_rect(r, W, H)
            why = f"작은 고정 로고(면적 {area:.2%}) → ffmpeg delogo"
        elif area <= pol.inpaint_max_area_frac:
            action = "inpaint"
            rr = _int_rect(rect_pad(r, 2), W, H)
            why = (f"글자/오버레이(면적 {area:.2%}) → 국소 복원 inpaint"
                   + ("(시간 한정)" if not whole else "") + ", 정지 배경이면 앞뒤 프레임의 깨끗한 판으로 채움")
        else:
            action = "blur"
            rr = _int_rect(r, W, H)
            why = f"면적 {area:.2%} > 복원 한도 {pol.inpaint_max_area_frac:.0%} → 최후 수단 흐림"
        if overlaps_face:
            why += f"; 보호 영역 {len(overlaps_face)}개와 겹침 → 복원 결과를 사람이 확인해야 함"
            warnings.append(f"{o['id']}: 얼굴/보호 영역과 겹치는 오버레이 복원 — 결과 확인 필요")
        entry = {**rr, "start": t0, "end": t1, "reason": f"{o['id']} {o['kind']}" + (f" '{o['text']}'" if o.get("text") else "")}
        clean[action].append(entry)
        decisions.append({"overlay_id": o["id"], "kind": o["kind"], "action": action, "reason": why, "rect": rr,
                          "start": t0, "end": t1})
        rej = [d for d in decisions if d["overlay_id"] == o["id"] and d["action"] == "crop_rejected"]
        prefix = ("잘라내기 불가(" + " / ".join(f"{d.get('side', '')}: {d['reason']}" for d in rej) + ") → ") if rej else \
            ("잘라내기 조건 불충족 → " if crop_allowed else "")
        rationale.append(f"{o['id']} {KIND_KO.get(o['kind'])} ({_where(o, W, H)}, {o['start']:.2f}~{o['end']:.2f}s): "
                         f"깨끗한 원본 없음 → {prefix}{why}")
    if not ovs:
        rationale.append("검출된 오버레이 없음 → 정리 작업 없음")
    notes = "; ".join(f"{d['overlay_id']}:{ACTION_KO.get(d['action'], d['action'])}" for d in decisions
                      if d["action"] in ACTION_KO)
    # a plan is only "complete" when every check was measured and nothing waits for a person
    review_reasons = list(warnings)
    clean["notes"] = (f"shortkit clean plan ({doc['source'].get('sha256', '')[:12]}): " + (notes or "오버레이 없음"))
    return {**base, "replace_source": None, "clean": clean, "decisions": decisions, "rationale": rationale,
            "warnings": warnings, "crop_check": crop_check,
            "status": "needs_review" if review_reasons else "complete", "review_reasons": review_reasons}


def _where(o: dict, W: int, H: int) -> str:
    names = {"top_left": "좌상단", "top_right": "우상단", "bottom_left": "좌하단", "bottom_right": "우하단"}
    if o.get("corner"):
        return names.get(o["corner"], o["corner"])
    return {"top": "상단", "bottom": "하단", "middle": "중앙"}.get(o.get("band") or "", "화면 안")


def _int_rect(r: dict, W: int, H: int) -> dict:
    x0 = max(0, int(np.floor(r["x"])))
    y0 = max(0, int(np.floor(r["y"])))
    x1 = min(W, int(np.ceil(r["x"] + r["w"])))
    y1 = min(H, int(np.ceil(r["y"] + r["h"])))
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def _delogo_rect(r: dict, W: int, H: int) -> dict:
    """ffmpeg delogo interpolates from a 1-px border around the rect: keep it inside the frame."""
    x0 = max(1, int(np.floor(r["x"])))
    y0 = max(1, int(np.floor(r["y"])))
    x1 = min(W - 1, int(np.ceil(r["x"] + r["w"])))
    y1 = min(H - 1, int(np.ceil(r["y"] + r["h"])))
    return {"x": x0, "y": y0, "w": max(1, x1 - x0), "h": max(1, y1 - y0)}


def summary_ko(plan: dict) -> str:
    lines = [f"상태: {'완료' if plan.get('status') == 'complete' else '사람 확인 필요(완료 아님)'}"]
    if plan.get("replace_source"):
        rs = plan["replace_source"]
        lines.append(f"원본 교체: {rs.get('path')} (sha256 {str(rs.get('sha256'))[:12]}) — {rs.get('reason')}")
    c = plan["clean"]
    lines.append(f"얼굴 검출: {'측정함' if plan.get('faces_status') == 'measured' else '못 잼'}, "
                 f"보호 영역 {len(plan.get('protected', []))}개")
    lines.append("잘라내기: " + (f"{c['crop']}" if c.get("crop") else "없음"))
    for k in ("delogo", "inpaint", "blur"):
        for e in c.get(k, []):
            span = "전체 구간" if e.get("start") is None else "%.2f~%.2fs" % (e["start"], e["end"])
            lines.append(f"{ACTION_KO[k]}: x={e['x']} y={e['y']} w={e['w']} h={e['h']} {span} ({e.get('reason', '')})")
    lines.append("판단 근거:")
    lines += [f"  - {r}" for r in plan.get("rationale", [])]
    for w in plan.get("warnings", []):
        lines.append(f"  ! {w}")
    return "\n".join(lines)
