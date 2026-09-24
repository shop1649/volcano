"""Editorial motion inside the footage region: zoom in/out, freeze frames, speed ramps (+ flashes
copied from shots.json).

Per consecutive frame pair (native rate, footage region at 320 px width, caption boxes masked):
  * similarity transform by ORB matches + RANSAC -> scale; zoom events are runs of same-sign
    per-frame scale change (>= 0.3 %/frame) totalling >= 5 %, or single-frame jumps >= 5 %
    ("punch-in").  Camera zooms inside the source cannot be told apart from editor zooms.
  * mean absolute gray difference -> freeze = run of (near) identical frames >= 0.25 s.
  * unique-frame rate (share of pairs that change) -> a speed ramp is a sustained change of that
    rate inside one shot (frame-duplication slow motion).  Optical-flow/blended slow motion is
    NOT detectable this way, so "no ramp found" is reported as unmeasured, never as absent.

Output ``analysis/<id>/motion.json`` (docs/CONTRACT.md section 11)::

    {"video_id", "resolution", "events": [{"t", "end", "type": "zoom_in|zoom_out|freeze|speed|flash",
     "value", ...}], "presence": {zoom|freeze|speed|flash: present|absent|unmeasured}}

``value``: zoom -> scale_to (relative to the zoom start), freeze -> hold_s, speed -> factor
(new/old playback speed), flash -> dur_s.
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from ..util.jsonio import now_iso, read_json, write_json
from ..util.media import probe
from ..util.stats import tri_state
from .common import analysis_dir, iter_native, region_or_full

SCHEMA = "shortkit.ref_motion/1"
WIDTH = 320
METHOD = {
    "zoom": "ORB (600) + RANSAC similarity per frame pair in the footage region (captions masked); runs of "
            "same-sign scale change >= 0.3%/frame totalling >= 5%, or one-frame jumps >= 5%",
    "freeze": ">= 0.25 s of frames with <= 0.03% pixels changing by > 6 levels, with motion (>= 0.3% pixels) "
              "right before and after inside the same shot",
    "speed": "unique-frame rate change (>= 1.4x or <= 0.7x, sustained >= 0.4 s) inside one shot "
             "(frame-duplication slow/fast motion only)",
    "flash": "copied from shots.json",
    "frame_times": "frame index / fps (constant frame rate assumed)",
}


def _similarity(prev, cur, mask, orb, bf):
    import cv2
    k1, d1 = orb.detectAndCompute(prev, mask)
    k2, d2 = orb.detectAndCompute(cur, mask)
    if d1 is None or d2 is None or len(k1) < 12 or len(k2) < 12:
        return None
    m = bf.match(d1, d2)
    if len(m) < 12:
        return None
    p1 = np.float32([k1[x.queryIdx].pt for x in m])
    p2 = np.float32([k2[x.trainIdx].pt for x in m])
    M, inl = cv2.estimateAffinePartial2D(p1, p2, method=cv2.RANSAC, ransacReprojThreshold=2.0,
                                         maxIters=500, confidence=0.99)
    if M is None or inl is None:
        return None
    ni = int(inl.sum())
    if ni < 12 or ni < 0.3 * len(m):
        return None
    s = math.hypot(M[0, 0], M[1, 0])
    # fixed point of the transform = zoom center
    A = M[:, :2]
    tvec = M[:, 2]
    try:
        c = np.linalg.solve(np.eye(2) - A, tvec) if abs(s - 1) > 1e-3 else None
    except np.linalg.LinAlgError:
        c = None
    return {"s": s, "inliers": ni, "tx": float(M[0, 2]), "ty": float(M[1, 2]),
            "center": (float(c[0]), float(c[1])) if c is not None else None}


def analyze(video: str | Path, video_id: str, preset: str | None = None, region: dict | None = None,
            out_dir: Path | None = None, shots: dict | None = None, captions: dict | None = None,
            max_seconds: float | None = None) -> dict:
    import cv2

    video = Path(video)
    info = probe(video)
    W, H = int(info.width), int(info.height)
    fps = float(info.fps or 30.0)
    d = Path(out_dir) if out_dir is not None else analysis_dir(preset, video_id)
    shots = shots if shots is not None else (read_json(d / "shots.json") or {})
    captions = captions if captions is not None else (read_json(d / "captions.json") or {})
    reg = region_or_full(region, W, H)
    sc = WIDTH / reg["w"]
    # boundaries: pairs across cuts / inside flashes and crossfades are not analysed
    excl: list[tuple[float, float]] = []
    for c in shots.get("cuts") or []:
        t = float(c["t"])
        dur = float(c.get("dur") or 0.0)
        excl.append((t - 1.5 / fps, t + dur + 1.5 / fps))
    mask = None
    grays, stats = [], []
    orb = cv2.ORB_create(nfeatures=600, fastThreshold=12)
    bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=True)
    prev = None
    for t, fr in iter_native(video, fps, crop=reg, width=WIDTH, gray=True, max_seconds=max_seconds):
        if mask is None:
            mask = np.full(fr.shape, 255, np.uint8)
            for it in captions.get("items") or []:
                x, y, w, h = it["bbox"]
                mx, my = 0.25 * w + 4 / sc, 0.25 * h + 4 / sc     # pop / slide animations overshoot the rest box
                x0, y0 = int((x - mx - reg["x"]) * sc), int((y - my - reg["y"]) * sc)
                x1, y1 = int((x + w + mx - reg["x"]) * sc), int((y + h + my - reg["y"]) * sc)
                if x1 > 0 and y1 > 0 and x0 < fr.shape[1] and y0 < fr.shape[0]:
                    mask[max(0, y0):y1, max(0, x0):x1] = 0
        g = fr
        if prev is not None:
            skip = any(a <= t <= b for a, b in excl)
            dd = np.abs(g.astype(np.int16) - prev.astype(np.int16))
            dd[mask == 0] = 0          # caption animations are not footage motion
            diff = float(dd.mean())
            changed = int((dd > 6).sum())
            sim = None if skip else _similarity(prev, g, mask, orb, bf)
            stats.append({"t": t, "diff": diff, "changed": changed, "npix": int(dd.size), "skip": skip, "sim": sim})
        prev = g
    n = len(stats)
    duration = (n + 1) / fps
    events: list[dict] = []
    # ------------------------------------------------------------------ zoom
    logs = [math.log(s["sim"]["s"]) if s["sim"] else None for s in stats]
    analysable = sum(1 for s in stats if s["sim"] is not None)
    i = 0
    while i < n:
        lg = logs[i]
        if lg is None or abs(lg) < 0.003:
            i += 1
            continue
        sign = 1 if lg > 0 else -1
        j = i
        total = lg
        gaps = 0
        while j + 1 < n:
            nx = logs[j + 1]
            if nx is not None and nx * sign >= 0.003:
                j += 1
                total += nx
                gaps = 0
            elif gaps == 0 and j + 2 < n and logs[j + 2] is not None and logs[j + 2] * sign >= 0.003:
                j += 1
                gaps = 1
            else:
                break
        if abs(total) >= math.log(1.05):
            t0 = stats[i]["t"] - 1.0 / fps          # the frame before the first scaled frame
            t1 = stats[j]["t"]
            centers = [stats[k]["sim"]["center"] for k in range(i, j + 1)
                       if stats[k]["sim"] and stats[k]["sim"]["center"]]
            ctr = None
            if centers:
                cx = float(np.median([c[0] for c in centers])) / sc + reg["x"]
                cy = float(np.median([c[1] for c in centers])) / sc + reg["y"]
                ctr = [round(cx, 1), round(cy, 1)]
            st = math.exp(total)
            events.append({"t": round(t0, 3), "end": round(t1, 3), "type": "zoom_in" if sign > 0 else "zoom_out",
                           "value": round(st, 4), "scale_from": 1.0, "scale_to": round(st, 4),
                           "dur_s": round(t1 - t0, 3), "center": ctr, "frames": j - i + 1,
                           "kind": "punch" if j == i else "ramp"})
        i = j + 1
    # ------------------------------------------------------------------ freeze
    # frozen pair = (almost) no pixel changes by more than 6 levels; an editorial freeze must be
    # bounded by visible motion inside the same shot (a still scene is not a freeze)
    shot_ranges = [(float(s_["start"]), float(s_["end"])) for s_ in shots.get("shots") or []] or [(0.0, duration)]
    npix = stats[0]["npix"] if stats else 1
    still_thr = max(3, int(0.0003 * npix))
    move_thr = max(30, int(0.003 * npix))
    frozen = np.array([(not s_["skip"]) and s_["changed"] <= still_thr for s_ in stats], bool)

    def shot_of(t):
        for a_, b_ in shot_ranges:
            if a_ - 1e-6 <= t < b_ + 1e-6:
                return (a_, b_)
        return None

    k = 0
    freeze_runs = []
    rejected_still = 0
    while k < n:
        if frozen[k]:
            j = k
            while j + 1 < n and frozen[j + 1]:
                j += 1
            hold = (j - k + 1) / fps
            if hold >= 0.25:
                sh = shot_of(stats[k]["t"])
                before = [stats[q]["changed"] for q in range(max(0, k - 3), k) if not stats[q]["skip"]
                          and sh and sh[0] <= stats[q]["t"]]
                after = [stats[q]["changed"] for q in range(j + 1, min(n, j + 4)) if not stats[q]["skip"]
                         and sh and stats[q]["t"] < sh[1]]
                if before and after and max(before) >= move_thr and max(after) >= move_thr:
                    t0 = stats[k]["t"] - 1.0 / fps
                    events.append({"t": round(stats[k]["t"], 3), "end": round(stats[j]["t"] + 1.0 / fps, 3),
                                   "type": "freeze", "value": round(hold, 3), "hold_s": round(hold, 3),
                                   "held_frame_t": round(t0, 3)})
                    freeze_runs.append((k, j))
                else:
                    rejected_still += 1
            k = j + 1
        else:
            k += 1
    # ------------------------------------------------------------------ speed ramps
    in_freeze = np.zeros(n, bool)
    for a, b in freeze_runs:
        in_freeze[a:b + 1] = True
    win = max(4, int(round(0.5 * fps)))
    speed_checked = False
    for a, b in shot_ranges:
        idx = [k for k in range(n) if a <= stats[k]["t"] < b and not stats[k]["skip"] and not in_freeze[k]]
        if len(idx) < 2 * win + 2:
            continue
        speed_checked = True
        # 1 = clearly new frame (visible motion), 0 = duplicate, NaN = too little motion to tell
        # (a still scene is not frame duplication)
        u = np.array([1.0 if stats[k]["changed"] >= move_thr else (0.0 if stats[k]["changed"] <= still_thr else np.nan)
                      for k in idx])
        ts = np.array([stats[k]["t"] for k in idx])
        best = None

        def wmean(x):
            ok = ~np.isnan(x)
            return float(x[ok].mean()) if ok.sum() >= 0.6 * len(x) else None

        for p in range(win, len(u) - win + 1):
            left, right = wmean(u[p - win:p]), wmean(u[p:p + win])
            if not left or not right:
                continue
            ratio = right / left
            if (ratio <= 0.7 or ratio >= 1.43) and abs(right - left) >= 0.25:
                # sustained: the new rate holds until the shot end / at least 0.4 s
                hold = wmean(u[p:]) if len(u) - p < 2 * win else wmean(u[p:p + 2 * win])
                if hold is None or abs(hold / left - ratio) > 0.25:
                    continue
                score = abs(math.log(ratio))
                if best is None or score > best[0] + 1e-9:
                    best = (score, p, ratio)
        if best:
            _, p, ratio = best
            # align to the first changed-rate frame
            t0 = float(ts[p]) - 1.0 / fps
            events.append({"t": round(t0, 3), "end": round(b, 3), "type": "speed", "value": round(float(ratio), 3),
                           "factor": round(float(ratio), 3), "method": "unique-frame rate (frame duplication)"})
    # ------------------------------------------------------------------ flashes
    for c in shots.get("cuts") or []:
        if c.get("type") == "flash":
            events.append({"t": c["t"], "end": round(float(c["t"]) + float(c.get("dur") or 0), 3), "type": "flash",
                           "value": c.get("dur"), "dur_s": c.get("dur"), "color": c.get("color")})
    events.sort(key=lambda e: e["t"])
    cover = analysable / max(1, sum(1 for s in stats if not s["skip"]))
    presence = {
        "zoom": tri_state([any(e["type"].startswith("zoom") for e in events)]) if cover >= 0.5 or
        any(e["type"].startswith("zoom") for e in events) else "unmeasured",
        "freeze": tri_state([any(e["type"] == "freeze" for e in events)]) if n else "unmeasured",
        "speed": "present" if any(e["type"] == "speed" for e in events) else "unmeasured",
        "flash": (shots.get("presence") or {}).get("flash", "unmeasured"),
    }
    res = {"schema": SCHEMA, "video_id": video_id, "resolution": [W, H], "fps": fps, "duration": round(duration, 3),
           "region_used": reg, "analysis_width": WIDTH, "method": METHOD, "analyzed_at": now_iso(),
           "zoom_analysable_share": round(cover, 3), "still_runs_not_freeze": rejected_still,
           "events": events, "presence": presence,
           "presence_note": "speed 는 프레임 복제 방식만 검출 가능 → 못 찾으면 '없다'가 아니라 '못 잼'"}
    write_json(d / "motion.json", res)
    return res
