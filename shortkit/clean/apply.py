"""Apply cleaning operations to a source video.

- :func:`inpaint_video` -- per-frame local restoration of rects within their time ranges
  (OpenCV Telea inpainting; when the background around a timed overlay is static, the rect is
  filled from a temporal-median "clean plate" of the frames just before/after the overlay).
  Keeps the audio (stream copy when the codec fits MP4), H.264 video.  Used by the resolver;
  :func:`cache_path` gives the cache location ``warehouse/cache/clean/<sha>_<opshash>.mp4``.
- :func:`apply_clean` -- materialise a whole plan ``clean`` block (inpaint -> delogo -> blur ->
  crop) into one file, e.g. for review or for QA of the cleaning itself.
- :func:`ffmpeg_clean_filters` -- the delogo/blur/crop part as an ffmpeg filter chain.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

import numpy as np

from .. import paths
from ..util.hashing import sha256_file, sha256_text
from ..util.jsonio import now_iso, read_json, write_json
from ..util.media import FFMPEG, MediaError, ffmpeg, probe

ALGO = "shortkit.clean.apply/1"
CACHE_DIR = "warehouse/cache/clean"
MP4_AUDIO_COPY = {"aac", "mp3", "ac3", "eac3", "alac", "opus"}


# ----------------------------------------------------------------------------- op identity
def normalize_rects(rects: list[dict], W: int, H: int) -> list[dict]:
    """Integer rects clamped to the frame; start/end floats or None (= whole clip)."""
    out = []
    for r in rects or []:
        x0 = max(0, int(np.floor(float(r["x"]))))
        y0 = max(0, int(np.floor(float(r["y"]))))
        x1 = min(W, int(np.ceil(float(r["x"]) + float(r["w"]))))
        y1 = min(H, int(np.ceil(float(r["y"]) + float(r["h"]))))
        if x1 - x0 < 1 or y1 - y0 < 1:
            continue
        s = r.get("start")
        e = r.get("end")
        out.append({"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0,
                    "start": None if s is None else round(float(s), 4), "end": None if e is None else round(float(e), 4)})
    return out


def ops_hash(ops: Any, params: dict | None = None) -> str:
    return sha256_text(json.dumps({"algo": ALGO, "ops": ops, "params": params or {}}, sort_keys=True))[:16]


def _params(radius: int = 5, temporal: bool = True, crf: int = 18, ring: int = 8, plate_tol: float = 10.0,
            **_ignored) -> dict:
    return {"radius": radius, "temporal": temporal, "crf": crf, "ring": ring, "plate_tol": plate_tol}


def cache_path(src: str | Path, rects: list[dict], src_sha: str | None = None, **kw) -> Path:
    """Cache location of ``inpaint_video(src, rects, ...)``: warehouse/cache/clean/<sha>_<opshash>.mp4
    (``kw``: the same radius/temporal/crf/ring/plate_tol options passed to inpaint_video)."""
    info = probe(src)
    sha = src_sha or sha256_file(src)
    oh = ops_hash(normalize_rects(rects, info.width, info.height), _params(**kw))
    return paths.absp(f"{CACHE_DIR}/{sha}_{oh}.mp4")


def _rel(p: Path) -> str | None:
    try:
        return paths.relp(p)
    except ValueError:
        return None       # outside the project root: never store an absolute path


# ----------------------------------------------------------------------------- clean plates
def _build_plate(src: Path, r: dict, dur: float, fps: float, ring: int, W: int, H: int,
                 span: float = 1.5) -> dict | None:
    """Median background of the rect (+ring) from frames just outside the overlay's time range.

    Returns None when there are no such frames or the background there is not static.
    """
    from .detect import read_crop_frames

    if r["start"] is None and r["end"] is None:
        return None
    # rect + ring, clamped to the frame, even-sized (the crop reader works on even dimensions)
    x0, y0 = max(0, r["x"] - ring), max(0, r["y"] - ring)
    x1, y1 = min(W, r["x"] + r["w"] + ring), min(H, r["y"] + r["h"] + ring)
    if (x1 - x0) % 2:
        x0, x1 = (x0 - 1, x1) if x0 > 0 else ((x0, x1 + 1) if x1 < W else (x0, x1 - 1))
    if (y1 - y0) % 2:
        y0, y1 = (y0 - 1, y1) if y0 > 0 else ((y0, y1 + 1) if y1 < H else (y0, y1 - 1))
    win = {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}
    if win["w"] < 4 or win["h"] < 4 or x0 > r["x"] or y0 > r["y"] or x1 < r["x"] + r["w"] or y1 < r["y"] + r["h"]:
        return None      # the plate must cover the whole rect
    crops = []
    t_s = 0.0 if r["start"] is None else r["start"]
    t_e = dur if r["end"] is None else r["end"]
    if t_s > 0.1:
        crops += read_crop_frames(src, win, max(0.0, t_s - span), max(0.0, t_s - 0.5 / fps), color=True)
    if t_e < dur - 0.1:
        crops += read_crop_frames(src, win, t_e + 0.5 / fps, min(dur, t_e + span), color=True)
    if len(crops) < 3:
        return None
    stack = np.stack([c for _t, c in crops]).astype(np.float32)
    plate = np.median(stack, axis=0)
    std = float(np.median(stack.std(axis=0)))
    if std > 6.0 or plate.shape[:2] != (win["h"], win["w"]):
        return None
    return {"plate": plate, "win": win, "std": round(std, 2), "n": len(crops)}


# ----------------------------------------------------------------------------- main
def inpaint_video(src: str | Path, rects: list[dict], out: str | Path, *, radius: int = 5, temporal: bool = True,
                  crf: int = 18, preset: str = "veryfast", threads: int | None = None, ring: int = 8,
                  plate_tol: float = 10.0) -> dict:
    """Inpaint ``rects`` ({x,y,w,h,start,end} SOURCE px/time) in every frame of their time range.

    Frames are decoded at the source's average frame rate (constant), so the output keeps the
    source duration and audio sync.  Result dict: out, sha256, source_sha256, ops_hash, frames,
    frames_inpainted, per_rect methods (plate/telea), audio handling, cached flag.
    """
    src, out = Path(src), Path(out)
    info = probe(src)
    W, H = info.width, info.height
    if not W or not H:
        raise MediaError(f"no video stream in {src}")
    fps = float(info.fps or 30.0)
    dur = float(info.duration)
    v_off = _video_offset(info)
    sha = sha256_file(src)
    norm = normalize_rects(rects, W, H)
    params = _params(radius=radius, temporal=temporal, crf=crf, ring=ring, plate_tol=plate_tol)
    oh = ops_hash(norm, params)
    meta_p = out.with_name(out.name + ".json")
    meta = read_json(meta_p)
    if out.is_file() and meta and meta.get("source_sha256") == sha and meta.get("ops_hash") == oh \
            and meta.get("sha256") == sha256_file(out):
        return {**meta, "cached": True}
    t_start = time.time()
    out.parent.mkdir(parents=True, exist_ok=True)
    plates = {}
    if temporal:
        for i, r in enumerate(norm):
            p = _build_plate(src, r, dur, fps, ring, W, H)
            if p is not None:
                plates[i] = p
    frame_bytes = W * H * 3
    dec = subprocess.Popen([FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-i", str(src), "-map", "0:v:0",
                            "-vf", f"fps={fps:.6f}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
                           stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    acodec = info.acodec if info.has_audio else None
    audio_mode = "none" if not acodec else ("copy" if acodec in MP4_AUDIO_COPY else "aac")
    tmp = out.with_name(out.stem + ".part" + out.suffix)
    enc_cmd = [FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "bgr24",
               "-s", f"{W}x{H}", "-framerate", f"{fps:.6f}", "-i", "-", "-i", str(src), "-map", "0:v:0"]
    if acodec:
        enc_cmd += ["-map", "1:a:0", "-c:a", "copy" if audio_mode == "copy" else "aac"]
        if audio_mode == "aac":
            enc_cmd += ["-b:a", "192k"]
    enc_cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
    if threads:
        enc_cmd += ["-threads", str(threads)]
    enc_cmd += [str(tmp)]
    enc = subprocess.Popen(enc_cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    stats = [{"rect": {k: r[k] for k in ("x", "y", "w", "h", "start", "end")}, "frames": 0, "plate": 0, "telea": 0,
              "plate_info": ({k: v for k, v in plates[i].items() if k in ("std", "n")} if i in plates else None)}
             for i, r in enumerate(norm)]
    n = 0
    n_done = 0
    try:
        while True:
            buf = dec.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            t = v_off + n / fps      # SOURCE time (relative to the file start, like ffmpeg -ss)
            frame = None
            for i, r in enumerate(norm):
                if (r["start"] is not None and t < r["start"] - 1e-6) or (r["end"] is not None and t >= r["end"] - 1e-6):
                    continue
                if frame is None:
                    frame = np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
                how = _restore_rect(frame, r, plates.get(i), radius, ring, plate_tol)
                stats[i]["frames"] += 1
                stats[i][how] += 1
            if frame is not None:
                n_done += 1
                enc.stdin.write(frame.tobytes())
            else:
                enc.stdin.write(buf)
            n += 1
    finally:
        dec.stdout.close()
        dec.wait()
        try:
            enc.stdin.close()
        except BrokenPipeError:
            pass
        rc = enc.wait()
    if rc != 0:
        err = (enc.stderr.read() or b"").decode("utf-8", "replace")[-1500:]
        tmp.unlink(missing_ok=True)
        raise MediaError(f"encode failed: {err}")
    if n == 0:
        tmp.unlink(missing_ok=True)
        raise MediaError(f"no frames decoded from {src}")
    tmp.replace(out)
    res = {"schema": "shortkit.clean_apply/1", "algo": ALGO, "out": _rel(out), "sha256": sha256_file(out),
           "source": _rel(src), "source_sha256": sha, "ops": norm, "ops_hash": oh, "params": params,
           "frames": n, "frames_inpainted": n_done, "fps": round(fps, 4), "resolution": [W, H],
           "audio": audio_mode, "per_rect": stats, "created_at": now_iso(),
           "elapsed_s": round(time.time() - t_start, 2), "cached": False}
    write_json(meta_p, res)
    return res


def _video_offset(info) -> float:
    """Start of the video stream relative to the file start (ffmpeg -ss / plan times are file-relative)."""
    try:
        fmt0 = float(info.raw.get("format", {}).get("start_time") or 0.0)
        v = next(s for s in info.raw.get("streams", []) if s.get("codec_type") == "video")
        return max(0.0, float(v.get("start_time") or 0.0) - fmt0)
    except (StopIteration, TypeError, ValueError):
        return 0.0


def _restore_rect(frame: np.ndarray, r: dict, plate: dict | None, radius: int, ring: int, tol: float) -> str:
    """Restore one rect in place. Returns 'plate' or 'telea'."""
    import cv2

    H, W = frame.shape[:2]
    if plate is not None:
        win = plate["win"]
        x0, y0 = max(0, win["x"]), max(0, win["y"])
        x1, y1 = min(W, win["x"] + win["w"]), min(H, win["y"] + win["h"])
        pl = plate["plate"][y0 - win["y"]:y1 - win["y"], x0 - win["x"]:x1 - win["x"]]
        cur = frame[y0:y1, x0:x1].astype(np.float32)
        if pl.shape == cur.shape and pl.size:
            inner = np.zeros(cur.shape[:2], bool)
            iy0, ix0 = r["y"] - y0, r["x"] - x0
            inner[max(0, iy0):iy0 + r["h"], max(0, ix0):ix0 + r["w"]] = True
            ringm = ~inner
            if ringm.sum() >= 20:
                off = (cur[ringm] - pl[ringm]).mean(axis=0)
                mad = float(np.abs(cur[ringm] - (pl[ringm] + off)).mean())
                if mad <= tol:
                    filled = np.clip(pl + off, 0, 255)
                    # feather the seam over a few px inside the rect
                    m = inner.astype(np.float32)
                    m = cv2.GaussianBlur(m, (0, 0), 1.5) * inner
                    m = np.maximum(m, cv2.erode(inner.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(np.float32))
                    blend = cur * (1 - m[..., None]) + filled * m[..., None]
                    frame[y0:y1, x0:x1] = np.clip(blend + 0.5, 0, 255).astype(np.uint8)
                    return "plate"
    m = 2 * radius + 8
    wx0, wy0 = max(0, r["x"] - m), max(0, r["y"] - m)
    wx1, wy1 = min(W, r["x"] + r["w"] + m), min(H, r["y"] + r["h"] + m)
    sub = np.ascontiguousarray(frame[wy0:wy1, wx0:wx1])
    mask = np.zeros(sub.shape[:2], np.uint8)
    mask[r["y"] - wy0:r["y"] - wy0 + r["h"], r["x"] - wx0:r["x"] - wx0 + r["w"]] = 255
    frame[wy0:wy1, wx0:wx1] = cv2.inpaint(sub, mask, radius, cv2.INPAINT_TELEA)
    return "telea"


def inpaint_cached(src: str | Path, rects: list[dict], **kw) -> dict:
    """``inpaint_video`` into the project cache (``warehouse/cache/clean/<sha>_<opshash>.mp4``)."""
    return inpaint_video(src, rects, cache_path(src, rects, **kw), **kw)


# ----------------------------------------------------------------------------- ffmpeg ops
def _enable(e: dict) -> str:
    if e.get("start") is None and e.get("end") is None:
        return ""
    s = 0.0 if e.get("start") is None else float(e["start"])
    t = 1e9 if e.get("end") is None else float(e["end"])
    return f":enable='between(t,{s:.4f},{t:.4f})'"


def ffmpeg_clean_filters(clean: dict, W: int, H: int, label_in: str = "0:v", label_out: str = "vclean") -> str:
    """filter_complex chain for the delogo / blur / crop part of a ``clean`` block (SOURCE px/time;
    inpaint is done by :func:`inpaint_video` beforehand)."""
    parts = []
    cur = label_in
    k = 0
    for e in clean.get("delogo") or []:
        x = max(1, int(e["x"]))
        y = max(1, int(e["y"]))
        w = max(1, min(int(e["w"]), W - 1 - x))
        h = max(1, min(int(e["h"]), H - 1 - y))
        nxt = f"cl{k}"
        parts.append(f"[{cur}]delogo=x={x}:y={y}:w={w}:h={h}{_enable(e)}[{nxt}]")
        cur, k = nxt, k + 1
    for e in clean.get("blur") or []:
        x, y = max(0, int(e["x"])), max(0, int(e["y"]))
        w = min(int(e["w"]), W - x)
        h = min(int(e["h"]), H - y)
        w -= w % 2
        h -= h % 2
        if w < 4 or h < 4:
            continue
        rad = max(2, min(w, h) // 8)
        crad = max(1, min(rad // 2, min(w, h) // 4 - 1))
        a, b, bb, nxt = f"cl{k}a", f"cl{k}b", f"cl{k}bb", f"cl{k}"
        parts.append(f"[{cur}]split[{a}][{b}]")
        parts.append(f"[{b}]crop={w}:{h}:{x}:{y},boxblur={rad}:2:{crad}:2[{bb}]")
        parts.append(f"[{a}][{bb}]overlay={x}:{y}{_enable(e)}[{nxt}]")
        cur, k = nxt, k + 1
    c = clean.get("crop")
    if c:
        nxt = f"cl{k}"
        parts.append(f"[{cur}]crop={int(c['w'])}:{int(c['h'])}:{int(c['x'])}:{int(c['y'])}[{nxt}]")
        cur, k = nxt, k + 1
    parts.append(f"[{cur}]null[{label_out}]")
    return ";".join(parts)


def apply_clean(src: str | Path, clean: dict, out: str | Path, *, threads: int | None = None, crf: int = 18,
                preset: str = "veryfast") -> dict:
    """Materialise a plan ``clean`` block: inpaint (cached) -> delogo -> blur -> crop."""
    src, out = Path(src), Path(out)
    info = probe(src)
    W, H = info.width, info.height
    steps = []
    stage_in = src
    if clean.get("inpaint"):
        r = inpaint_cached(src, clean["inpaint"], threads=threads, crf=crf, preset=preset)
        steps.append({"op": "inpaint", "result": {k: r[k] for k in ("out", "sha256", "ops_hash", "frames_inpainted",
                                                                    "per_rect", "cached")}})
        stage_in = paths.absp(r["out"])
    has_ff = bool(clean.get("delogo") or clean.get("blur") or clean.get("crop"))
    out.parent.mkdir(parents=True, exist_ok=True)
    if has_ff:
        fc = ffmpeg_clean_filters(clean, W, H)
        a_info = probe(stage_in)
        cmd = ["-i", stage_in, "-filter_complex", fc, "-map", "[vclean]"]
        if a_info.has_audio:
            cmd += ["-map", "0:a:0", "-c:a", "copy" if (a_info.acodec in MP4_AUDIO_COPY) else "aac"]
        cmd += ["-c:v", "libx264", "-preset", preset, "-crf", str(crf), "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        if threads:
            cmd += ["-threads", str(threads)]
        ffmpeg([*cmd, out])
        steps.append({"op": "ffmpeg", "filter_complex": fc})
    elif stage_in != src:
        shutil.copyfile(stage_in, out)
    else:
        shutil.copyfile(src, out)
        steps.append({"op": "copy", "note": "정리할 작업 없음"})
    res = {"schema": "shortkit.clean_apply/1", "algo": ALGO, "out": _rel(out), "sha256": sha256_file(out),
           "source": _rel(src), "source_sha256": sha256_file(src), "clean": clean,
           "ops_hash": ops_hash(clean), "steps": steps, "created_at": now_iso()}
    write_json(out.with_name(out.name + ".json"), res)
    return res
