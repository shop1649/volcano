"""Identity templates of the reference channel (S2QA-11): the channel's OWN persistent overlays (logo, watermark,
handle) cut from the fixed snapshot's reference videos, so QA (``identity.logo_templates``) can check that no final
frame reproduces them -- also a text-free logo the OCR check (``identity.forbidden_text``) cannot read.

Output: ``<identity_exclusions.logo_templates_dir>/``
    <id>.png          template crops (reference pixels, native resolution) -- QA reads every *.png / *.jpg here
    review/<id>.png   candidates a person must look at (never read by QA: a subfolder)
    manifest.json     measurement-like record (schema ``shortkit.identity_templates/1``): status measured | partial |
                      unmeasured, blocker, basis (snapshot, scanned / missing videos, per-video detector checks),
                      templates[] {id, file, sha256, kind, basis, text, matched_term, rect, resolution, rect_norm,
                      n_videos, share, times, evidence [{video_id, t, rect, resolution, start, end}]}, review[]

Method (per snapshot member with a downloaded file; Shorts only unless ``include_long``):
1. ``shortkit.clean.detect.detect_overlays`` (the source-overlay detector, ``save=False``: nothing is written to the
   warehouse) -> static text overlays / watermarks / text-free logos (cross-shot persistence) with OCR text.
2. Channel identity instances:
   - ``forbidden_text``: an overlay / review candidate whose OCR text matches ``identity_exclusions.forbidden_text``
     (normalised substring, or a >= 0.85 fuzzy window for OCR noise), plus the ``identity_mark`` lines that
     ``ref analyze`` already found (captions.json);
   - ``recurrence``: a static overlay at the same place (normalised rect IoU >= 0.5) with the same appearance
     (32x32 grey NCC >= 0.6) in >= max(2, 20 % of the scanned videos) DIFFERENT videos: a source's watermark belongs
     to one source, the channel's mark recurs over different footage.
   - ``cross_video_persistence``: edges that stay at the same place in every video while the footage changes from
     video to video (also finds a text-free logo inside single static-camera shots, which the per-video detector
     cannot) -- these instances join the recurrence groups.
   A recurring overlay becomes a template automatically only where channel logos sit (``AUTO_RULE``: a corner,
   <= 2 % of the frame) and when it does not overlap the channel's own captions (captions.json items -- e.g. a fixed
   title plate is a STYLE element to reproduce, not an identity mark); otherwise, without caption analysis, or for a
   flat crop (no texture: template matching would be meaningless) it goes to ``review``.  A person who looked at a
   candidate decides with ``--accept/--reject <id> --by <name>`` (``decisions.json``, re-applied on every re-run).
3. One template per group: the crop of the instance at the largest resolution.

Status: ``unmeasured`` when no snapshot video could be scanned (blocker = the collect / download blocker);
``partial`` when a target video was not scanned, OCR was unavailable, a video's text-free-logo check was
unmeasured, fewer than 2 videos were scanned (recurrence cannot be judged) or review candidates are pending;
``measured`` otherwise (``templates: []`` then means: no persistent identity mark found in the snapshot).
"""
from __future__ import annotations

import math
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .. import paths
from ..config import load_preset
from ..util.hashing import sha256_file
from ..util.jsonio import now_iso, read_json, write_json
from .common import (analysis_dir, basis_record, production_basis, resolve_ids, say, snapshot_blocker,
                     video_path, warn)

SCHEMA = "shortkit.identity_templates/1"
MANIFEST = "manifest.json"
REVIEW_DIR = "review"
STATIC_KINDS = ("logo", "watermark", "source_overlay")
RECUR_MIN_VIDEOS = 2
RECUR_MIN_SHARE = 0.2
RECT_IOU = 0.5
APPEAR_NCC = 0.6
FLAT_STD = 6.0                 # grey std of a crop below this: no texture, not a usable template
FUZZY_MIN = 0.85
# a recurring overlay becomes a template without a person only where channel logos / handles sit: a corner, small
AUTO_CORNER_X = 0.3           # centre within 30 % of the width from the left / right edge
AUTO_CORNER_Y = 0.2           # ... and within 20 % of the height from the top / bottom edge
AUTO_MAX_AREA = 0.02          # <= 2 % of the frame
AUTO_RULE = (f"반복 표식은 중심이 모서리(좌우 {int(AUTO_CORNER_X * 100)}%·상하 {int(AUTO_CORNER_Y * 100)}% 안)이고 "
             f"면적이 화면의 {int(AUTO_MAX_AREA * 100)}% 이하이며 채널 자막과 겹치지 않을 때만 자동 템플릿. 그 밖은 사람 확인"
             "(--accept/--reject). forbidden_text 글자 일치는 항상 템플릿")
METHOD = ("shortkit.clean.detect(레퍼런스 파일, 저장 안 함) → 채널 식별 표식 = (a) OCR 글자가 identity_exclusions.forbidden_text 와 "
          "일치(정규화 부분 문자열 또는 창 유사도 ≥ 0.85) + ref analyze 의 identity_mark 자막, (b) 서로 다른 영상 "
          f"≥ max({RECUR_MIN_VIDEOS}, 스캔 영상의 {int(RECUR_MIN_SHARE * 100)}%)에서 같은 자리(정규화 사각형 IoU ≥ {RECT_IOU})·"
          f"같은 모양(32x32 회색 NCC ≥ {APPEAR_NCC})으로 반복되는 고정 오버레이(채널 자막과 겹치거나 자막 분석이 없으면 사람 확인) "
          "→ 그룹마다 가장 큰 해상도 사례의 원본 픽셀 크롭")
RULE = ("QA identity.logo_templates 가 이 폴더의 *.png/*.jpg 를 출력 프레임과 정규화 상관으로 대조한다(review/ 하위 폴더는 "
        "읽지 않음). 템플릿은 원 채널 식별 요소를 '복제하지 않았는지' 검사하는 데만 쓰고 제작에 쓰지 않는다")


# ============================================================================= text matching
def norm_text(t: str | None) -> str:
    """Same normalisation as the analyzer's identity_mark rule (textboxes._norm_text)."""
    return re.sub(r"[^0-9a-z가-힣]", "", (t or "").lower())


def forbidden_match(text: str | None, terms: list[str]) -> str | None:
    """The forbidden term ``text`` shows (normalised substring, else a fuzzy window >= FUZZY_MIN), or None."""
    nt = norm_text(text)
    if not nt:
        return None
    for term in terms:
        m = norm_text(term)
        if len(m) >= 3 and m in nt:
            return term
    for term in terms:
        m = norm_text(term)
        if len(m) < 4 or len(nt) < len(m) - 1:
            continue
        best = 0.0
        for L in (len(m) - 1, len(m), len(m) + 1):
            for i in range(0, max(1, len(nt) - L + 1)):
                best = max(best, SequenceMatcher(None, m, nt[i:i + L]).ratio())
        if best >= FUZZY_MIN:
            return term
    return None


# ============================================================================= geometry / appearance
def norm_rect(r: dict, res: list[int] | tuple) -> dict:
    W, H = float(res[0]), float(res[1])
    return {"x": r["x"] / W, "y": r["y"] / H, "w": r["w"] / W, "h": r["h"] / H}


def rect_iou(a: dict, b: dict) -> float:
    x0, y0 = max(a["x"], b["x"]), max(a["y"], b["y"])
    x1, y1 = min(a["x"] + a["w"], b["x"] + b["w"]), min(a["y"] + a["h"], b["y"] + b["h"])
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    union = a["w"] * a["h"] + b["w"] * b["h"] - inter
    return inter / union if union > 0 else 0.0


def overlap_frac(a: dict, b: dict) -> float:
    """Share of ``a`` covered by ``b``."""
    x0, y0 = max(a["x"], b["x"]), max(a["y"], b["y"])
    x1, y1 = min(a["x"] + a["w"], b["x"] + b["w"]), min(a["y"] + a["h"], b["y"] + b["h"])
    return max(0.0, x1 - x0) * max(0.0, y1 - y0) / max(1e-9, a["w"] * a["h"])


def _aspect_key(res) -> float:
    return round(float(res[0]) / float(res[1]), 2)


def crop(frame: np.ndarray, r: dict) -> np.ndarray:
    H, W = frame.shape[:2]
    x0, y0 = max(0, int(math.floor(r["x"]))), max(0, int(math.floor(r["y"])))
    x1, y1 = min(W, int(math.ceil(r["x"] + r["w"]))), min(H, int(math.ceil(r["y"] + r["h"])))
    return frame[y0:y1, x0:x1]


def crop_instance(fr: np.ndarray, it: dict) -> np.ndarray:
    """Crop of an instance's rect (stored in ``it["resolution"]`` px) from a decoded frame of that video."""
    res = it["resolution"]
    if [fr.shape[1], fr.shape[0]] != [int(res[0]), int(res[1])]:
        sx, sy = fr.shape[1] / float(res[0]), fr.shape[0] / float(res[1])
        r = it["rect"]
        return crop(fr, {"x": r["x"] * sx, "y": r["y"] * sy, "w": r["w"] * sx, "h": r["h"] * sy})
    return crop(fr, it["rect"])


def appearance(c: np.ndarray) -> tuple[np.ndarray | None, float]:
    """(zero-mean unit 32x32 grey vector or None for an empty crop, grey std)."""
    import cv2

    if c.size == 0 or min(c.shape[:2]) < 4:
        return None, 0.0
    g = cv2.cvtColor(c, cv2.COLOR_RGB2GRAY) if c.ndim == 3 else c
    std = float(g.std())
    v = cv2.resize(g, (32, 32), interpolation=cv2.INTER_AREA).astype(np.float64).ravel()
    v -= v.mean()
    n = float(np.linalg.norm(v))
    return (v / n if n > 1e-6 else None), std


def ncc(a: np.ndarray | None, b: np.ndarray | None) -> float:
    if a is None or b is None:
        return 0.0
    return float(np.dot(a, b))


# ============================================================================= instances
def _caption_items(preset: str, vid: str) -> list[dict] | None:
    """The channel's own caption items (captions.json, any role but identity_mark) or None without analysis."""
    cap = read_json(analysis_dir(preset, vid) / "captions.json")
    if not isinstance(cap, dict):
        return None
    out = []
    res = cap.get("resolution")
    for c in cap.get("items") or []:
        bb = c.get("bbox")
        if c.get("role") == "identity_mark" or not bb or not res:
            continue
        out.append({"rect": norm_rect({"x": bb[0], "y": bb[1], "w": bb[2], "h": bb[3]}, res),
                    "start": c.get("start"), "end": c.get("end"), "role": c.get("role"), "text": c.get("text")})
    return out


def video_instances(preset: str, vid: str, doc: dict, terms: list[str]) -> list[dict]:
    """Candidate instances of one video: static overlays (recurrence candidates) + forbidden-text hits."""
    out = []
    res = (doc.get("source") or {}).get("resolution")
    for o in doc.get("overlays") or []:
        r, ores = o.get("rect"), o.get("resolution") or res
        if not r or not ores:
            continue
        term = forbidden_match(o.get("text"), terms)
        if not term and not (o.get("static") and o.get("kind") in STATIC_KINDS):
            continue
        out.append({"video_id": vid, "rect": {k: float(r[k]) for k in ("x", "y", "w", "h")}, "resolution": list(ores),
                    "start": o.get("start"), "end": o.get("end"),
                    "t": o.get("template_t") if o.get("template_t") is not None else o.get("start"),
                    "kind": o.get("kind"), "text": o.get("text"), "matched_term": term,
                    "method": f"clean.detect:{(o.get('evidence') or {}).get('method')}", "static": bool(o.get("static"))})
    for rv in doc.get("review") or []:
        term = forbidden_match(rv.get("ocr_text"), terms)
        if term and rv.get("rect") and (rv.get("resolution") or res):
            out.append({"video_id": vid, "rect": {k: float(rv["rect"][k]) for k in ("x", "y", "w", "h")},
                        "resolution": list(rv.get("resolution") or res), "start": rv.get("t_first"),
                        "end": rv.get("t_last"), "t": rv.get("t_first"), "kind": "watermark",
                        "text": rv.get("ocr_text"), "matched_term": term, "method": "clean.detect:review(OCR)",
                        "static": True})
    cap = read_json(analysis_dir(preset, vid) / "captions.json")
    if isinstance(cap, dict) and cap.get("resolution"):
        for c in cap.get("items") or []:
            bb = c.get("bbox")
            if c.get("role") != "identity_mark" or not bb:
                continue
            out.append({"video_id": vid, "rect": {"x": float(bb[0]), "y": float(bb[1]), "w": float(bb[2]),
                                                   "h": float(bb[3])},
                        "resolution": list(cap["resolution"]), "start": c.get("start"), "end": c.get("end"),
                        "t": c.get("t_rep") if c.get("t_rep") is not None else c.get("start"), "kind": "watermark",
                        "text": c.get("text"), "matched_term": forbidden_match(c.get("text"), terms) or "identity_mark",
                        "method": "ref analyze captions.json identity_mark", "static": True})
    return out


def group_instances(inst: list[dict], key: Callable[[dict], Any]) -> list[list[dict]]:
    """Greedy grouping: same ``key`` (term / None), same aspect, rect IoU >= RECT_IOU (normalised) and, for
    appearance-grouped instances, NCC >= APPEAR_NCC with the group's first member."""
    groups: list[list[dict]] = []
    for it in inst:
        placed = False
        for g in groups:
            g0 = g[0]
            if key(g0) != key(it) or _aspect_key(g0["resolution"]) != _aspect_key(it["resolution"]):
                continue
            if rect_iou(g0["nrect"], it["nrect"]) < RECT_IOU:
                continue
            if it.get("matched_term") is None and ncc(g0.get("vec"), it.get("vec")) < APPEAR_NCC:
                continue
            g.append(it)
            placed = True
            break
        if not placed:
            groups.append([it])
    return merge_same_place(groups)


def merge_same_place(groups: list[list[dict]]) -> list[list[dict]]:
    """Two groups at the same place (rect IoU >= RECT_IOU) that share a video are one overlay seen by two methods
    (e.g. the per-video detector's exact rect and the cross-video check's padded rect)."""
    out: list[list[dict]] = []
    for g in groups:
        for h in out:
            if (h[0].get("matched_term") == g[0].get("matched_term")
                    and _aspect_key(h[0]["resolution"]) == _aspect_key(g[0]["resolution"])
                    and rect_iou(h[0]["nrect"], g[0]["nrect"]) >= RECT_IOU
                    and {i["video_id"] for i in h} & {i["video_id"] for i in g}):
                h.extend(g)
                break
        else:
            out.append(list(g))
    return out


def representative(g: list[dict]) -> dict:
    """The instance whose crop becomes the template: an exact detector rect before the cross-video check's padded
    one, then the largest resolution, then the most texture."""
    return max(g, key=lambda i: (i.get("method") != "cross_video_persistence",
                                 i["resolution"][0] * i["resolution"][1], i.get("std") or 0.0))


# ============================================================================= cross-video persistence
XV_WIDTH = 240            # analysis width of the sampled frames
XV_FRAMES = 7             # frames per video
XV_PERSIST = 0.85         # an edge present in >= this share of a video's frames persists in that video
XV_EDGE_SHARE = 0.8       # ... in >= this share of the videos of one aspect ratio
XV_STD = 14.0             # grey std across the videos' median frames below this: the same pixels in every video
XV_CONTENT_DIFF = 10.0    # median frames of two videos differing by less (mean |diff|) show the same content


def cross_video_persistence(videos: dict[str, dict], need: int) -> tuple[dict[str, list[dict]], dict]:
    """The channel's own marks sit at the same place in EVERY video while the footage changes from video to video:
    edges that persist within each video (>= XV_PERSIST of its frames) and across the videos (>= XV_EDGE_SHARE of
    them, grey std across the videos' median frames < XV_STD).  Complements the per-video detector, which cannot
    tell a text-free logo from the background inside one static-camera shot.

    ``videos``: {vid: {"path", "duration", "resolution"}} -> ({vid: [instances]}, check record)."""
    import cv2

    from ..util.media import iter_frames

    per: dict[str, dict] = {}
    for vid, v in videos.items():
        dur, res = float(v.get("duration") or 0.0), v.get("resolution")
        if dur <= 0 or not res:
            continue
        try:        # one decoder pass at XV_FRAMES / duration fps (evenly spread samples, native aspect)
            got = [(round(t + 0.5 * dur / XV_FRAMES, 3), g) for t, g in
                   iter_frames(v["path"], fps=XV_FRAMES / dur, width=XV_WIDTH, gray=True,
                               start=0.5 * dur / XV_FRAMES)][:XV_FRAMES]
        except Exception:  # noqa: BLE001 - a video that cannot be sampled is simply not part of this check
            continue
        if len(got) < 3:
            continue
        per[vid] = {"times": [t for t, _ in got], "grays": [g.copy() for _, g in got], "res": list(res), "dur": dur}
    groups: dict[float, list[str]] = {}
    for vid, p in per.items():
        groups.setdefault(_aspect_key(p["res"]), []).append(vid)
    out: dict[str, list[dict]] = {}
    checked = []
    for asp, vids in sorted(groups.items()):
        rec = {"aspect": asp, "videos": len(vids)}
        checked.append(rec)
        if len(vids) < need:
            rec["status"] = "unmeasured"
            rec["reason"] = f"같은 화면 비율 영상 {len(vids)}편 < {need}편"
            continue
        h0, w0 = per[vids[0]]["grays"][0].shape
        med, pers = [], []
        for vid in vids:
            gs = [cv2.resize(g, (w0, h0), interpolation=cv2.INTER_AREA) for g in per[vid]["grays"]]
            med.append(np.median(np.stack(gs).astype(np.float32), axis=0))
            pers.append(np.mean([cv2.Canny(g, 60, 160) > 0 for g in gs], axis=0))
        diffs = [float(np.mean(np.abs(med[i] - med[j]))) for i in range(len(vids)) for j in range(i + 1, len(vids))]
        rec["median_content_diff"] = round(float(np.median(diffs)), 2)
        if float(np.median(diffs)) < XV_CONTENT_DIFF:
            rec["status"] = "unmeasured"
            rec["reason"] = "영상들의 화면 내용이 거의 같아(중앙 프레임 차이 작음) 채널 표식과 내용을 구분할 수 없음"
            continue
        rec["status"] = "measured"
        persist = np.stack(pers) >= XV_PERSIST
        share = persist.mean(axis=0)
        std = np.std(np.stack(med), axis=0)
        mask = (share >= XV_EDGE_SHARE) & (std < XV_STD)
        cl = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
        n, lab, stt, _c = cv2.connectedComponentsWithStats(cl, connectivity=8)
        found = []
        for i in range(1, n):
            x, y, w, h, _a = (int(q) for q in stt[i])
            comp = lab == i
            epx = int((mask & comp).sum())
            if epx < 12 or w * h > 0.05 * w0 * h0 or w > 0.4 * w0 or h > 0.4 * h0 or min(w, h) < 4:
                continue
            nr = {"x": max(0.0, (x - 2) / w0), "y": max(0.0, (y - 2) / h0), "w": min(1.0, (w + 4) / w0),
                  "h": min(1.0, (h + 4) / h0)}
            found.append(nr)
            for k, vid in enumerate(vids):
                if float(persist[k][comp & mask].mean()) < 0.6:
                    continue                                   # this video does not show it
                W, H = per[vid]["res"]
                r = {"x": nr["x"] * W, "y": nr["y"] * H, "w": min(nr["w"] * W, W - nr["x"] * W),
                     "h": min(nr["h"] * H, H - nr["y"] * H)}
                out.setdefault(vid, []).append({
                    "video_id": vid, "rect": r, "resolution": [W, H], "start": 0.0, "end": round(per[vid]["dur"], 3),
                    "t": per[vid]["times"][len(per[vid]["times"]) // 2], "kind": "logo", "text": None, "matched_term": None,
                    "method": "cross_video_persistence", "static": True})
        rec["candidates"] = len(found)
    measured = any(r.get("status") == "measured" for r in checked)
    return out, {"status": "measured" if measured else "unmeasured", "groups": checked,
                 "method": (f"영상마다 {XV_FRAMES}프레임(폭 {XV_WIDTH}px)의 가장자리가 {int(XV_PERSIST * 100)}% 이상 프레임에 남고, "
                            f"같은 비율 영상의 {int(XV_EDGE_SHARE * 100)}% 이상에서 같은 자리에 남으며 영상 간 중앙 프레임 회색 "
                            f"표준편차 < {XV_STD} 인 덩어리(내용은 영상마다 다름)"),
                 "reason": None if measured else "여러 영상 대조 불가(같은 비율 영상 부족 또는 내용이 같음)"}


# ============================================================================= main
def templates_dir(pr) -> Path:
    return paths.absp(str(pr.get("identity_exclusions.logo_templates_dir")))


def _old_generated(tdir: Path) -> list[Path]:
    old = read_json(tdir / MANIFEST) or {}
    files = [t.get("file") for t in (old.get("templates") or []) + (old.get("review") or []) + (old.get("rejected") or [])
             if t.get("file")]
    return [paths.absp(f) for f in files]


def extract(preset: str, ids: list[str] | None = None, include_long: bool = False, ocr: bool = True,
            detector: Callable | None = None, cross_video: bool = True) -> dict:
    """Scan the snapshot's reference videos and (re)write the identity templates + manifest.
    ``detector(path) -> overlays doc`` defaults to ``shortkit.clean.detect.detect_overlays(save=False)``."""
    import cv2

    pr = load_preset(preset)
    terms = [str(t) for t in (pr.get("identity_exclusions.forbidden_text") or [])]
    tdir = templates_dir(pr)
    pb = production_basis(preset, ids if ids is not None else resolve_ids(preset, set_name="latest100"),
                          include_long=include_long)
    targets = list(pb["ids"])
    if detector is None:
        from ..clean.detect import DetectParams, detect_overlays

        def detector(p: Path) -> dict:
            return detect_overlays(p, DetectParams(save=False, ocr=ocr))

    scanned: dict[str, dict] = {}
    missing, failed, checks = [], [], {}
    for vid in targets:
        vpath = video_path(preset, vid)
        if vpath is None:
            missing.append(vid)
            continue
        try:
            doc = detector(vpath)
        except Exception as e:  # keep going, but record it (never a silent 'clean')
            failed.append({"video_id": vid, "error": f"{type(e).__name__}: {e}"[:300]})
            warn(f"{vid}: 오버레이 검출 실패 {type(e).__name__}: {e}")
            continue
        scanned[vid] = {"doc": doc, "path": vpath}
        ch = doc.get("checks") or {}
        checks[vid] = {"text_overlays": (ch.get("text_overlays") or {}).get("status", "unmeasured"),
                       "static_graphics": (ch.get("static_graphics") or {}).get("status", "unmeasured"),
                       "n_overlays": len(doc.get("overlays") or [])}
    basis = {**basis_record(pb), "targets": targets, "scanned": sorted(scanned), "not_downloaded": missing,
             "failed": failed, "checks": checks, "forbidden_text": terms}
    head = {"schema": SCHEMA, "preset_id": pr.preset_id, "source_snapshot": pb.get("captured_at"),
            "source_snapshot_status": pb.get("snapshot_status"), "generated_at": now_iso(),
            "generated_by": "shortkit ref identity-templates", "method": METHOD, "rule": RULE,
            "templates_dir": paths.relp(tdir)}
    if not scanned:
        blocker = pb["blocker"] or (snapshot_blocker(preset) if not targets else
                                    f"스냅샷 영상 {len(targets)}편 중 받은(또는 검출에 성공한) 영상 없음"
                                    "(`shortkit ref download --set latest100` 필요)"
                                    + (f"; 검출 실패 {len(failed)}편" if failed else ""))
        old = read_json(tdir / MANIFEST) or {}
        if old.get("status") in ("measured", "partial") and old.get("source_snapshot") == head["source_snapshot"] \
                and head["source_snapshot"]:
            say(f"식별 템플릿: 지금 스캔할 영상 없음({blocker}) → 같은 스냅샷의 기존 결과 유지({paths.relp(tdir / MANIFEST)})")
            return {**old, "kept_previous": True, "scanned_now": 0}
        for f in _old_generated(tdir):            # stale templates of another snapshot must not stay in use
            if f.is_file():
                f.unlink()
        man = {**head, "status": "unmeasured", "blocker": blocker, "basis": basis, "templates": [], "review": [],
               "rejected": [], "partial_reasons": [], "manual_files": _manual_files(tdir, set())}
        write_json(tdir / MANIFEST, man)
        say(f"식별 템플릿: 못 잼 — {blocker} → {paths.relp(tdir / MANIFEST)}")
        return {**man, "scanned_now": 0}

    # ---- instances with appearance vectors (crops from the reference frames)
    frames: dict[tuple[str, float], np.ndarray] = {}

    def frame(vid: str, t: float) -> np.ndarray:
        from ..util.media import read_frames

        k = (vid, round(float(t or 0.0), 3))
        if k not in frames:
            frames[k] = read_frames(scanned[vid]["path"], [k[1]])[0]
        return frames[k]

    n_scan = len(scanned)
    need = max(RECUR_MIN_VIDEOS, int(math.ceil(RECUR_MIN_SHARE * n_scan)))
    xv_inst: dict[str, list[dict]] = {}
    xv_check = {"status": "unmeasured", "reason": "여러 영상 대조를 끔(cross_video=False)"}
    if cross_video:
        xv_inst, xv_check = cross_video_persistence(
            {vid: {"path": s["path"], "duration": (s["doc"].get("source") or {}).get("duration"),
                   "resolution": (s["doc"].get("source") or {}).get("resolution")} for vid, s in scanned.items()}, need)
    basis["cross_video"] = xv_check
    inst: list[dict] = []
    for vid, s in scanned.items():
        for it in video_instances(preset, vid, s["doc"], terms) + xv_inst.get(vid, []):
            it["nrect"] = norm_rect(it["rect"], it["resolution"])
            try:
                it["vec"], it["std"] = appearance(crop_instance(frame(vid, it["t"]), it))
            except Exception as e:  # noqa: BLE001 - a frame that cannot be read leaves the instance without appearance
                it["vec"], it["std"], it["frame_error"] = None, 0.0, f"{type(e).__name__}: {e}"[:200]
            inst.append(it)
    forb = group_instances([i for i in inst if i.get("matched_term")], key=lambda i: i["matched_term"])
    recur = [g for g in group_instances([i for i in inst if not i.get("matched_term") and i.get("static")],
                                        key=lambda i: None)
             if len({i["video_id"] for i in g}) >= need]
    caps = {vid: _caption_items(preset, vid) for vid in scanned}
    cands: list[tuple[str, list[dict], str | None]] = [("forbidden_text", g, None) for g in forb]
    for g in recur:
        cands.append(("recurrence", g, _recurrence_doubt(g, caps)))
    # ---- write crops + manifest
    old_files = _old_generated(tdir)
    tdir.mkdir(parents=True, exist_ok=True)
    decisions = read_json(tdir / DECISIONS) or {}
    written: set[Path] = set()
    templates, reviews, rejected = [], [], []
    for n, (basis_kind, g, why) in enumerate(cands, 1):
        rep = representative(g)
        rec = _group_record(g, basis_kind, n_scan)
        if why is None and (rep.get("std") or 0.0) < FLAT_STD:
            why = f"무늬 없는 크롭(회색 표준편차 {rep.get('std', 0.0):.1f} < {FLAT_STD}) — 템플릿 대조 불가"
        dec = find_decision(decisions, rec) if why is not None else None
        if dec is not None:
            rec["decision"] = dec
            if dec["decision"] == "reject":
                rec["reason"] = why
                rejected.append(rec)
                continue
            rec["confirmed_by"], rec["auto_doubt"] = dec.get("by"), why
            why = None
        is_review = why is not None
        tid = f"{'rev' if is_review else 'idt'}{n:02d}_{basis_kind}"
        out = (tdir / REVIEW_DIR / f"{tid}.png") if is_review else (tdir / f"{tid}.png")
        try:
            c = crop_instance(frame(rep["video_id"], rep["t"]), rep)
        except Exception as e:  # noqa: BLE001
            c = np.zeros((0, 0, 3), np.uint8)
            rec["crop_error"] = f"{type(e).__name__}: {e}"[:200]
        rec["id"] = tid
        if c.size:
            out.parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(str(out), cv2.cvtColor(c, cv2.COLOR_RGB2BGR))
            written.add(out.resolve())
            rec.update({"file": paths.relp(out), "sha256": sha256_file(out), "crop_from": {
                "video_id": rep["video_id"], "t": rep["t"], "rect": _round_rect(rep["rect"]),
                "resolution": rep["resolution"]}})
        elif not is_review:
            is_review, why = True, rec.get("crop_error") or "크롭 실패"
        if is_review:
            rec["reason"] = why
            reviews.append(rec)
        else:
            templates.append(rec)
    for f in old_files:                       # generated earlier, not produced now -> remove (manual files are kept)
        if f.is_file() and f.resolve() not in written:
            f.unlink()
    reasons = []
    if missing:
        reasons.append({"code": "not_downloaded", "text": f"받지 않은 스냅샷 영상 {len(missing)}편: {', '.join(missing[:10])}"
                        + ("…" if len(missing) > 10 else "")})
    if failed:
        reasons.append({"code": "detect_failed",
                        "text": f"검출 실패 {len(failed)}편: {', '.join(x['video_id'] for x in failed[:10])}"})
    no_ocr = [v for v, c in checks.items() if c["text_overlays"] != "measured"]
    if no_ocr:
        reasons.append({"code": "no_ocr", "text": f"OCR 못 함(글자 표식·forbidden_text 확인 못 함) {len(no_ocr)}편: "
                                                  f"{', '.join(no_ocr[:10])}"})
    # text-free logos: the cross-video check covers the channel's marks in every video it compared; otherwise each
    # video's own detector check must have been able to look for them
    no_gr = [] if xv_check.get("status") == "measured" else \
        [v for v, c in checks.items() if c["static_graphics"] not in ("measured", "partial")]
    if no_gr:
        reasons.append({"code": "no_graphic_check", "text": f"글자 없는 고정 로고 검사 못 잼(한 샷·고정 카메라, 여러 영상 대조 "
                                                            f"불가) {len(no_gr)}편: {', '.join(no_gr[:10])}"})
    if n_scan < RECUR_MIN_VIDEOS:
        reasons.append({"code": "few_videos", "text": f"스캔 영상 {n_scan}편 — 여러 영상에 반복되는 표식 판정에 "
                                                      f"{RECUR_MIN_VIDEOS}편 이상 필요"})
    man = {**head, "recurrence_rule": {"min_videos": need, "min_share": RECUR_MIN_SHARE, "rect_iou": RECT_IOU,
                                       "appearance_ncc": APPEAR_NCC, "flat_std": FLAT_STD,
                                       "auto_accept": AUTO_RULE},
           "basis": basis, "templates": templates, "review": reviews, "rejected": rejected,
           "partial_reasons": reasons, "manual_files": _manual_files(tdir, written)}
    _set_status(man, tdir)
    write_json(tdir / MANIFEST, man)
    say(f"식별 템플릿: 스캔 {n_scan}/{len(targets)}편, 템플릿 {len(templates)}개(글자 일치 "
        f"{sum(t['basis'] == 'forbidden_text' for t in templates)}, 반복 {sum(t['basis'] == 'recurrence' for t in templates)}), "
        f"사람 확인 {len(reviews)}개, 제외 판정 {len(rejected)}개, 상태 {man['status']} → {paths.relp(tdir / MANIFEST)}")
    return {**man, "scanned_now": n_scan}


def _recurrence_doubt(g: list[dict], caps: dict[str, list[dict] | None]) -> str | None:
    """Why a recurring overlay cannot be taken as the channel's identity mark automatically (None = accept)."""
    vids = sorted({i["video_id"] for i in g})
    for i in g:
        for c in caps.get(i["video_id"]) or []:
            if overlap_frac(i["nrect"], c["rect"]) > 0.3 and _time_overlap(i, c):
                return (f"채널 자막과 겹침({i['video_id']}: {c['role']} '{c['text']}') — 제목 판 등 편집 스타일 요소일 수 있어 "
                        "사람 확인")
    no_cap = [v for v in vids if caps.get(v) is None]
    if no_cap:
        return (f"자막 분석(captions.json) 없는 영상 {len(no_cap)}편 — 채널 자막(스타일 요소)과 구분 못 함 → "
                "`shortkit ref analyze` 후 다시 실행하거나 사람 확인")
    nr = g[0]["nrect"]
    cx, cy = nr["x"] + nr["w"] / 2, nr["y"] + nr["h"] / 2
    corner = (cx < AUTO_CORNER_X or cx > 1 - AUTO_CORNER_X) and (cy < AUTO_CORNER_Y or cy > 1 - AUTO_CORNER_Y)
    if not corner or nr["w"] * nr["h"] > AUTO_MAX_AREA:
        return (f"위치·크기가 로고 전형(모서리, 화면의 {AUTO_MAX_AREA * 100:.0f}% 이하)이 아님 — 장식·틀 등 편집 스타일 요소일 수 "
                "있어 사람 확인")
    return None


def _set_status(man: dict, tdir: Path) -> None:
    """status / blocker / note of a manifest from its partial reasons and pending review candidates."""
    reasons = [r for r in man.get("partial_reasons") or [] if r.get("code") != "review"]
    if man.get("review"):
        reasons.append({"code": "review", "text": f"사람 확인이 필요한 후보 {len(man['review'])}개({paths.relp(tdir / REVIEW_DIR)}/ "
                                                  "→ `shortkit ref identity-templates --accept|--reject <id> --by <이름>`)"})
    man["partial_reasons"] = reasons
    man["status"] = "partial" if reasons else "measured"
    man["blocker"] = "; ".join(r["text"] for r in reasons) or None
    man["note"] = ("templates 가 비어 있고 status=measured 이면 스냅샷에서 지속되는 채널 식별 표식을 찾지 못함(검출기 기준)"
                   if man["status"] == "measured" and not man.get("templates") else None)


# ============================================================================= person's decisions on review candidates
DECISIONS = "decisions.json"


def _signature(rec: dict) -> dict:
    res = rec.get("resolution") or [1, 1]
    return {"basis": rec.get("basis"), "aspect": _aspect_key(res), "rect_norm": rec.get("rect_norm")}


def find_decision(decisions: dict, rec: dict) -> dict | None:
    """The person's accept/reject decision for a candidate at the same place (same basis, aspect, rect IoU >= 0.5)."""
    sig = _signature(rec)
    for d in reversed(decisions.get("decisions") or []):
        s = d.get("signature") or {}
        if s.get("basis") == sig["basis"] and s.get("aspect") == sig["aspect"] and s.get("rect_norm") \
                and sig["rect_norm"] and rect_iou(s["rect_norm"], sig["rect_norm"]) >= RECT_IOU:
            return {k: d.get(k) for k in ("decision", "by", "at", "note", "candidate_id")}
    return None


def decide(preset: str, candidate_id: str, decision: str, by: str, note: str | None = None) -> dict:
    """A person who LOOKED at a review candidate accepts it as the channel's identity mark (it becomes a template) or
    rejects it (a style element / scene content).  Recorded in decisions.json (re-applied on every re-run) and applied
    to the current manifest without re-scanning."""
    import shutil

    if decision not in ("accept", "reject"):
        raise ValueError("decision must be accept or reject")
    if not (by or "").strip():
        raise ValueError("--by (확인한 사람) 필요")
    pr = load_preset(preset)
    tdir = templates_dir(pr)
    man = read_json(tdir / MANIFEST) or {}
    rec = next((r for r in man.get("review") or [] if r.get("id") == candidate_id), None)
    if rec is None:
        raise KeyError(f"review 후보 없음: {candidate_id} (manifest.json review[].id)")
    decs = read_json(tdir / DECISIONS) or {"schema": "shortkit.identity_template_decisions/1", "decisions": []}
    entry = {"candidate_id": candidate_id, "decision": decision, "by": by.strip(), "at": now_iso(), "note": note,
             "signature": _signature(rec), "reason_shown": rec.get("reason"), "file": rec.get("file")}
    decs["decisions"].append(entry)
    write_json(tdir / DECISIONS, decs)
    man["review"] = [r for r in man["review"] if r.get("id") != candidate_id]
    rec["decision"] = {k: entry[k] for k in ("decision", "by", "at", "note", "candidate_id")}
    if decision == "accept":
        src = paths.absp(rec["file"]) if rec.get("file") else None
        new_id = "idt" + candidate_id[3:] if candidate_id.startswith("rev") else candidate_id
        dst = tdir / f"{new_id}.png"
        if src is None or not src.is_file():
            raise FileNotFoundError(f"후보 크롭 없음: {rec.get('file')}")
        shutil.move(str(src), dst)
        rec.update({"id": new_id, "file": paths.relp(dst), "sha256": sha256_file(dst), "confirmed_by": entry["by"],
                    "auto_doubt": rec.pop("reason", None)})
        man.setdefault("templates", []).append(rec)
    else:
        man.setdefault("rejected", []).append(rec)
    _set_status(man, tdir)
    write_json(tdir / MANIFEST, man)
    say(f"식별 템플릿 후보 {candidate_id}: {decision} (확인: {entry['by']}) → 상태 {man['status']}")
    return man


def _time_overlap(i: dict, c: dict) -> bool:
    try:
        a0, a1 = float(i.get("start") or 0.0), float(i.get("end") if i.get("end") is not None else 1e9)
        b0, b1 = float(c.get("start") or 0.0), float(c.get("end") if c.get("end") is not None else 1e9)
    except (TypeError, ValueError):
        return True
    return min(a1, b1) > max(a0, b0)


def _round_rect(r: dict) -> dict:
    return {k: int(round(float(r[k]))) for k in ("x", "y", "w", "h")}


def _group_record(g: list[dict], basis_kind: str, n_scan: int) -> dict:
    vids = sorted({i["video_id"] for i in g})
    rep = representative(g)
    kinds = sorted({str(i.get("kind")) for i in g})
    texts = sorted({str(i["text"]) for i in g if i.get("text")})
    return {"kind": kinds[0] if len(kinds) == 1 else kinds, "basis": basis_kind,
            "text": texts[0] if texts else None, "texts": texts[:10],
            "matched_term": next((i["matched_term"] for i in g if i.get("matched_term")), None),
            "rect": _round_rect(rep["rect"]), "resolution": rep["resolution"],
            "rect_norm": {k: round(v, 4) for k, v in rep["nrect"].items()},
            "n_videos": len(vids), "share": round(len(vids) / max(1, n_scan), 3),
            "times": [[i.get("start"), i.get("end")] for i in g][:50],
            "evidence": [{"video_id": i["video_id"], "t": i.get("t"), "rect": _round_rect(i["rect"]),
                          "resolution": i["resolution"], "start": i.get("start"), "end": i.get("end"),
                          "method": i.get("method")} for i in g][:50]}


def _manual_files(tdir: Path, generated: set[Path]) -> list[str]:
    """Image files in the folder that this command did not write (e.g. placed by a person): QA reads them too."""
    if not tdir.is_dir():
        return []
    return sorted(paths.relp(p) for p in list(tdir.glob("*.png")) + list(tdir.glob("*.jpg"))
                  if p.resolve() not in generated)


def manifest_status(preset: str) -> dict:
    """{status, blocker, templates, review, file, source_snapshot} of the manifest (unmeasured when missing)."""
    pr = load_preset(preset)
    f = templates_dir(pr) / MANIFEST
    m = read_json(f) or {}
    return {"file": paths.relp(f), "exists": bool(m), "status": m.get("status", "unmeasured"),
            "blocker": m.get("blocker") if m else "식별 템플릿 manifest 없음(`shortkit ref identity-templates` 미실행)",
            "templates": len(m.get("templates") or []), "review": len(m.get("review") or []),
            "manual_files": len(m.get("manual_files") or []), "source_snapshot": m.get("source_snapshot"),
            "preset_id": m.get("preset_id")}
