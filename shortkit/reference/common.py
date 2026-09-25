"""Shared helpers for the reference-channel modules (collect / download / analyze / classify /
aggregate / trace).

Every stored path is root-relative (``shortkit.paths.relp``).  Human-facing messages are Korean.
"""
from __future__ import annotations

import csv
import re
import sys
from pathlib import Path
from typing import Any, Iterable, Sequence

import numpy as np

from .. import paths
from ..util.jsonio import read_json, read_jsonl

DEFAULT_PRESET = "joshuamagazine"
ROLES = ("title", "description", "situation", "speaker", "dialogue", "reaction")
ROLE_KO = {"title": "제목", "description": "설명", "situation": "상황 자막", "speaker": "인물 라벨",
           "dialogue": "대사", "reaction": "반응 자막", "unknown": "분류 못 함"}
SNAPSHOT_SCHEMA = "shortkit.ref_snapshot/1"
VIDEO_EXTS = (".mp4", ".mkv", ".webm", ".mov")


# ----------------------------------------------------------------------------- messages
def say(msg: str) -> None:
    print(msg, flush=True)


def warn(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


# ----------------------------------------------------------------------------- locations
def preset_dir(preset: str) -> Path:
    return paths.preset_dir(preset)


def reference_dir(preset: str) -> Path:
    return paths.preset_dir(preset) / "reference"


def videos_dir(preset: str) -> Path:
    return reference_dir(preset) / "videos"


def analysis_dir(preset: str, video_id: str) -> Path:
    return paths.preset_dir(preset) / "analysis" / safe_id(video_id)


def snapshot_path(preset: str) -> Path:
    return reference_dir(preset) / "latest100.json"


def safe_id(video_id: str) -> str:
    """Video ids are used as folder names; refuse anything that could escape the folder."""
    s = str(video_id)
    if not re.fullmatch(r"[A-Za-z0-9_.\-]{1,128}", s) or s in (".", ".."):
        raise ValueError(f"unsafe video id: {video_id!r}")
    return s


def load_snapshot(preset: str) -> dict | None:
    return read_json(snapshot_path(preset))


def load_reference_list(preset: str, name: str) -> dict | None:
    return read_json(reference_dir(preset) / f"{name}.json")


def video_path(preset: str, video_id: str) -> Path | None:
    """Downloaded reference video for an id (downloads.jsonl first, then the videos folder)."""
    vid = safe_id(video_id)
    for row in reversed(read_jsonl(reference_dir(preset) / "downloads.jsonl")):
        if row.get("video_id") == vid and row.get("path"):
            p = paths.absp(row["path"])
            if p.is_file():
                return p
    for ext in VIDEO_EXTS:
        p = videos_dir(preset) / f"{vid}{ext}"
        if p.is_file():
            return p
    return None


def resolve_ids(preset: str, ids: str | Sequence[str] | None = None, set_name: str | None = None,
                limit: int | None = None) -> list[str]:
    """Explicit ids (comma separated) or a named set: latest100 | high_views | downloaded | analyzed."""
    out: list[str] = []
    if ids:
        items = ids.split(",") if isinstance(ids, str) else list(ids)
        out = [safe_id(i.strip()) for i in items if i and i.strip()]
    elif set_name in ("latest100", "high_views", "all_videos"):
        d = load_reference_list(preset, set_name) or {}
        out = [v["video_id"] for v in d.get("videos") or [] if v.get("video_id")]
    elif set_name == "downloaded":
        seen = []
        for row in read_jsonl(reference_dir(preset) / "downloads.jsonl"):
            if row.get("video_id") and row["video_id"] not in seen:
                seen.append(row["video_id"])
        out = seen
    elif set_name == "analyzed":
        adir = paths.preset_dir(preset) / "analysis"
        out = sorted(p.name for p in adir.iterdir() if p.is_dir()) if adir.is_dir() else []
    if limit:
        out = out[:limit]
    return out


def views_of(preset: str) -> dict[str, int]:
    """video_id -> view_count from the fixed snapshot (latest100 wins over all_videos)."""
    out: dict[str, int] = {}
    for name in ("all_videos", "latest100"):
        d = load_reference_list(preset, name) or {}
        for v in d.get("videos") or []:
            if v.get("video_id") and isinstance(v.get("view_count"), (int, float)):
                out[v["video_id"]] = int(v["view_count"])
    return out


def snapshot_blocker(preset: str) -> str:
    """Korean explanation of why there is no reference data (used in 'unmeasured' blockers)."""
    snap = load_snapshot(preset)
    if not snap:
        return "레퍼런스 최신 100편 스냅샷 없음(`shortkit ref collect` 미실행)"
    if snap.get("status") == "blocked":
        return (f"레퍼런스 목록 수집 차단({snap.get('captured_at')}, {snap.get('method')}): "
                f"{str(snap.get('blocker') or '')[:300]}")
    return "레퍼런스 영상 분석 결과 없음(`shortkit ref download` → `shortkit ref analyze` 필요)"


def scrub(text: str) -> str:
    """Remove machine-specific locations (project root, home directory) from text that is stored
    (error messages from yt-dlp/ffmpeg can contain absolute paths)."""
    import os

    out = str(text or "")
    try:
        root = str(paths.project_root())
        out = out.replace(root + os.sep, "").replace(root, ".")
    except RuntimeError:
        pass
    home = os.path.expanduser("~")
    if home and home not in ("/", "~"):
        out = out.replace(home, "~")
    return out


# ----------------------------------------------------------------------------- colors
def hexrgb(rgb: Iterable[float]) -> str:
    r, g, b = [int(round(min(255.0, max(0.0, float(c))))) for c in list(rgb)[:3]]
    return f"#{r:02X}{g:02X}{b:02X}"


def rgb_of(hexstr: str) -> np.ndarray:
    h = hexstr.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], dtype=float)


def color_dist(a, b) -> float:
    a = rgb_of(a) if isinstance(a, str) else np.asarray(a, float)
    b = rgb_of(b) if isinstance(b, str) else np.asarray(b, float)
    return float(np.linalg.norm(a - b))


def saturation(rgb) -> float:
    c = np.asarray(rgb_of(rgb) if isinstance(rgb, str) else rgb, float) / 255.0
    mx, mn = float(c.max()), float(c.min())
    return 0.0 if mx <= 1e-6 else (mx - mn) / mx


def color_mode(colors: Iterable[str | None], tol: float = 28.0) -> dict:
    """Categorical summary for measured colors: greedy clustering (RGB distance <= tol) so that
    compression noise (#FEFEFE vs #FFFFFF) does not split one color into many.  The cluster value
    is the per-channel median of its members."""
    vals = [c for c in colors if c]
    clusters: list[list[str]] = []
    for c in vals:
        for cl in clusters:
            if color_dist(c, _median_hex(cl)) <= tol:
                cl.append(c)
                break
        else:
            clusters.append([c])
    clusters.sort(key=len, reverse=True)
    n = len(vals)
    summ = [{"color": _median_hex(cl), "count": len(cl), "share": round(len(cl) / n, 4)} for cl in clusters]
    return {"n": n, "clusters": summ, "mode": summ[0]["color"] if summ else None}


def _median_hex(cl: list[str]) -> str:
    return hexrgb(np.median(np.stack([rgb_of(c) for c in cl]), axis=0))


# ----------------------------------------------------------------------------- video region / background
def detect_video_region(video: str | Path, fps: float = 4.0, width: int = 216,
                        max_seconds: float | None = 120.0) -> dict:
    """Find the rectangle where the source footage plays (the rest is a static or blurred
    background with overlays).

    Method: per-pixel activity = share of consecutive sampled frames whose gray value changes by
    more than 8 levels; rows/columns where >50 % of pixels are active form the region.  When the
    whole frame is active, a low-sharpness band at the top/bottom is treated as a blurred copy of
    the source (``blur_source``).  Returns coordinates in the video's own resolution.

    Static-camera footage (CCTV-like: an empty room where only a person moves) is mostly NOT active,
    so activity alone can lose it and return a caption box instead.  When the canvas has a FLAT
    background (>= 60 % of the border pixels of the per-pixel temporal median frame within RGB 30 of
    their median colour), pixels whose temporal median differs from that colour by > 30 also count
    (union with activity: rows found by activity are never dropped).  Brief global events such as a
    full-canvas flash do not move a temporal median.
    """
    import cv2

    from ..util.media import iter_frames, probe

    info = probe(video)
    W, H = int(info.width or 0), int(info.height or 0)
    if not W or not H:
        return {"resolution": None, "video_region": None, "background": "unmeasured",
                "background_color": None, "note": "영상 스트림 없음"}
    prev = None
    act = None
    sharp = None
    mean_rgb = None
    vgrad = None
    n = 0
    kept: list[np.ndarray] = []          # frames for the temporal median (decimated to <= MEDIAN_MAX_FRAMES)
    stride, k = 1, 0
    for t, fr in iter_frames(video, fps=fps, width=width, duration=max_seconds):
        if k % stride == 0:
            kept.append(fr)
            if len(kept) > MEDIAN_MAX_FRAMES:
                kept = kept[::2]
                stride *= 2
        k += 1
        g = cv2.cvtColor(fr, cv2.COLOR_RGB2GRAY).astype(np.int16)
        lap = np.abs(cv2.Laplacian(g.astype(np.float32), cv2.CV_32F, ksize=3))
        if act is None:
            act = np.zeros(g.shape, np.float64)
            sharp = np.zeros(g.shape, np.float64)
            mean_rgb = np.zeros(fr.shape, np.float64)
            vgrad = np.zeros(g.shape[0] - 1, np.float64)
        sharp += lap
        mean_rgb += fr
        vgrad += np.abs(np.diff(g.astype(np.float64), axis=0)).mean(axis=1)
        if prev is not None:
            act += (np.abs(g - prev) > 8)
            n += 1
        prev = g
    if act is None or n < 2:
        return {"resolution": [W, H], "video_region": None, "background": "unmeasured", "background_color": None,
                "note": "프레임 부족"}
    act /= n
    sharp /= (n + 1)
    mean_rgb /= (n + 1)
    h, w = act.shape
    sx, sy = W / w, H / h
    active = act > 0.12
    med = np.median(np.stack(kept), axis=0)
    flat_bg = flat_border_color(med)
    if flat_bg is not None:
        active = active | (np.linalg.norm(med - np.asarray(flat_bg, float), axis=2) > FLAT_BG_TOL)
    row = active.mean(axis=1)
    rows = _longest_run(row > 0.5)
    note = ""
    bg_type = "unmeasured"
    bg_color = None
    if rows is None:
        return {"resolution": [W, H], "video_region": None, "background": "unmeasured", "background_color": None,
                "note": "움직이는 영역을 찾지 못함(정지 화면 위주 영상)", "method": _REGION_METHOD}
    y0, y1 = rows
    col = active[y0:y1 + 1].mean(axis=0)
    cols = _longest_run(col > 0.5) or (0, w - 1)
    x0, x1 = cols
    full = (y1 - y0 + 1) >= 0.97 * h and (x1 - x0 + 1) >= 0.97 * w
    if full:
        # all rows change: maybe a blurred copy of the source fills the background
        rs = np.percentile(sharp, 30, axis=1)
        k = max(1, h // 60)
        rs = np.convolve(rs, np.ones(k) / k, mode="same")
        ref = np.percentile(rs, 90)
        sharp_rows = _longest_run(rs > 0.35 * ref)
        if sharp_rows and (sharp_rows[1] - sharp_rows[0] + 1) < 0.9 * h:
            y0, y1 = sharp_rows
            # the sharpness band is soft at low-texture edges: snap each edge to the strongest
            # time-averaged horizontal discontinuity (footage edge vs. blurred copy) nearby
            band = y1 - y0 + 1
            win = max(2, int(0.3 * band))
            lo, hi = max(1, y0 - win), min(h - 2, y0 + win)
            if hi > lo:
                y0 = int(lo + np.argmax(vgrad[lo - 1:hi]))    # boundary k|k+1 -> first row k+1
            lo, hi = max(0, y1 - win), min(h - 2, y1 + win)
            if hi > lo:
                y1 = int(lo + np.argmax(vgrad[lo:hi + 1]))
            bg_type = "blur_source"
            note = "배경 영역도 변하지만 선명도가 낮음 → 원본을 흐리게 깐 배경"
            full = False
        else:
            note = "영상이 화면 전체를 덮어 배경이 보이지 않음"
    region = {"x": int(round(x0 * sx)), "y": int(round(y0 * sy)),
              "w": int(round((x1 - x0 + 1) * sx)), "h": int(round((y1 - y0 + 1) * sy))}
    region = _snap_region(region, W, H)
    if not full and bg_type == "unmeasured":
        outside = np.ones((h, w), bool)
        outside[y0:y1 + 1, x0:x1 + 1] = False
        if outside.sum() > 0.02 * h * w:
            oact = float(np.median(act[outside]))
            px = mean_rgb[outside]
            med = np.median(px, axis=0)
            share = float((np.linalg.norm(px - med, axis=1) < 30).mean())
            if oact < 0.05 and share >= 0.6:
                bg_type, bg_color = "color", hexrgb(med)
            elif oact >= 0.2:
                bg_type = "blur_source"
                note = "영상 밖 영역이 계속 변함 → 원본 흐림 배경으로 추정"
            else:
                note = f"영상 밖 영역이 정지해 있으나 단색이 아님(단색 비율 {share:.2f}) → 이미지 배경?"
    return {"resolution": [W, H], "video_region": None if full else region,
            "video_region_full_frame": bool(full), "background": bg_type, "background_color": bg_color,
            "note": note, "method": _REGION_METHOD, "sampled_fps": fps, "analysis_width": width}


MEDIAN_MAX_FRAMES = 160
FLAT_BG_TOL = 30.0          # RGB distance to the flat background colour
FLAT_BG_SHARE = 0.6         # share of border pixels that must be that colour


def flat_border_color(med_rgb: np.ndarray) -> tuple[float, float, float] | None:
    """Colour of a flat canvas background from a temporal-median frame (None when the border is not flat):
    border = top/bottom 3 % rows + left/right 2 % columns; flat when >= FLAT_BG_SHARE of those pixels lie
    within FLAT_BG_TOL of their per-channel median."""
    h, w = med_rgb.shape[:2]
    ty, tx = max(1, int(round(0.03 * h))), max(1, int(round(0.02 * w)))
    border = np.concatenate([med_rgb[:ty].reshape(-1, 3), med_rgb[-ty:].reshape(-1, 3),
                             med_rgb[:, :tx].reshape(-1, 3), med_rgb[:, -tx:].reshape(-1, 3)]).astype(float)
    c = np.median(border, axis=0)
    share = float((np.linalg.norm(border - c, axis=1) <= FLAT_BG_TOL).mean())
    return (float(c[0]), float(c[1]), float(c[2])) if share >= FLAT_BG_SHARE else None


_REGION_METHOD = ("per-pixel activity (gray change > 8 between frames sampled at fps) OR, on a flat canvas background, "
                  "temporal-median colour != background colour (RGB > 30) → rows/cols with >50% such pixels "
                  "pixels; blurred background via 30th-percentile Laplacian profile")


def _snap_region(r: dict, W: int, H: int) -> dict:
    """Snap edges that are within 1% of the frame border to the border."""
    x0, y0, x1, y1 = r["x"], r["y"], r["x"] + r["w"], r["y"] + r["h"]
    if x0 <= 0.01 * W:
        x0 = 0
    if y0 <= 0.01 * H:
        y0 = 0
    if x1 >= 0.99 * W:
        x1 = W
    if y1 >= 0.99 * H:
        y1 = H
    return {"x": int(x0), "y": int(y0), "w": int(x1 - x0), "h": int(y1 - y0)}


def _longest_run(mask: np.ndarray) -> tuple[int, int] | None:
    best = None
    start = None
    for i, v in enumerate(list(mask) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if best is None or (i - 1 - start) > (best[1] - best[0]):
                best = (start, i - 1)
            start = None
    return best


def get_region(preset: str, video_id: str, video: Path) -> dict:
    """Region info from analysis/<id>/layout.json if present, else detect now."""
    lay = read_json(analysis_dir(preset, video_id) / "layout.json")
    if lay and "video_region" in lay and lay.get("region_detection"):
        return lay["region_detection"]
    return detect_video_region(video)


def region_or_full(reg: dict | None, W: int, H: int) -> dict:
    r = (reg or {}).get("video_region")
    return r if r else {"x": 0, "y": 0, "w": W, "h": H}


# ----------------------------------------------------------------------------- csv
def read_csv_rows(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [dict(r) for r in csv.DictReader(f)]


def write_csv_rows(path: Path, header: Sequence[str], rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp.write")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(header), extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in header})
    tmp.replace(path)


def first(xs: Iterable[Any], default: Any = None) -> Any:
    for x in xs:
        return x
    return default


# ----------------------------------------------------------------------------- frame access
def read_segment(video: str | Path, t0: float, t1: float, fps: float, crop: dict | None = None,
                 width: int | None = None, gray: bool = False) -> list[tuple[float, np.ndarray]]:
    """Decode every native frame with t0 <= t < t1 (constant-frame-rate assumption).

    Frame times are derived from the frame index on the ``fps`` grid, so they are exact for CFR
    video (YouTube downloads are CFR).  ``crop`` is {x,y,w,h} in source px (applied before
    ``width`` scaling).
    """
    import subprocess

    from ..util.media import FFMPEG, probe

    info = probe(video)
    W, H = int(info.width), int(info.height)
    f0 = max(0, int(np.ceil(t0 * fps - 1e-6)))
    f1 = int(np.ceil(t1 * fps - 1e-6))
    if f1 <= f0:
        return []
    filters = []
    cw, ch = W, H
    if crop:
        c = even_crop(crop, W, H)
        x, y, cw, ch = c["x"], c["y"], c["w"], c["h"]
        filters.append(f"crop={cw}:{ch}:{x}:{y}:exact=1")
    if width:
        ch = int(round(ch * width / cw / 2) * 2)
        cw = width
        filters.append(f"scale={cw}:{ch}")
    pix = "gray" if gray else "rgb24"
    args = [FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{max(0.0, (f0 - 0.5) / fps):.6f}",
            "-i", str(video), "-frames:v", str(f1 - f0)]
    if filters:
        args += ["-vf", ",".join(filters)]
    args += ["-f", "rawvideo", "-pix_fmt", pix, "-"]
    raw = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL).stdout
    fb = cw * ch * (1 if gray else 3)
    out = []
    for i in range(len(raw) // fb):
        arr = np.frombuffer(raw[i * fb:(i + 1) * fb], np.uint8).reshape((ch, cw) if gray else (ch, cw, 3))
        out.append(((f0 + i) / fps, arr))
    return out


def iter_native(video: str | Path, fps: float, crop: dict | None = None, width: int | None = None,
                gray: bool = False, max_seconds: float | None = None):
    """Stream every native frame (index-derived times, CFR assumption) of the whole video,
    optionally cropped (even-aligned) and scaled.  Yields (t, frame)."""
    import subprocess

    from ..util.media import FFMPEG, probe

    info = probe(video)
    W, H = int(info.width), int(info.height)
    filters = []
    cw, ch = W, H
    if crop:
        c = even_crop(crop, W, H)
        cw, ch = c["w"], c["h"]
        filters.append(f"crop={cw}:{ch}:{c['x']}:{c['y']}:exact=1")
    if width:
        ch = int(round(ch * width / cw / 2) * 2)
        cw = width
        filters.append(f"scale={cw}:{ch}")
    args = [FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-i", str(video)]
    if max_seconds:
        args += ["-t", f"{max_seconds:.3f}"]
    if filters:
        args += ["-vf", ",".join(filters)]
    args += ["-vsync", "passthrough", "-f", "rawvideo", "-pix_fmt", "gray" if gray else "rgb24", "-"]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    fb = cw * ch * (1 if gray else 3)
    i = 0
    try:
        while True:
            buf = proc.stdout.read(fb)
            if len(buf) < fb:
                break
            yield i / fps, np.frombuffer(buf, np.uint8).reshape((ch, cw) if gray else (ch, cw, 3))
            i += 1
    finally:
        proc.stdout.close()
        proc.wait()


def even_crop(crop: dict, W: int, H: int) -> dict:
    """Clip a crop rect to the frame and make it even-aligned (chroma-subsampled video can only be
    cropped on even coordinates; callers must use the returned rect for their offsets)."""
    x = max(0, int(crop["x"]))
    y = max(0, int(crop["y"]))
    x -= x % 2
    y -= y % 2
    w = min(W - x, int(crop["w"]) + (int(crop["x"]) - x))
    h = min(H - y, int(crop["h"]) + (int(crop["y"]) - y))
    w -= w % 2
    h -= h % 2
    return {"x": x, "y": y, "w": max(2, w), "h": max(2, h)}
