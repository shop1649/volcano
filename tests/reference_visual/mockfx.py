"""SYNTHETIC mocks for the effect emitters (zoom ease / recenter, flash scope, decorations).

Every mock is drawn with the PRODUCTION RENDERER's own conventions so the analyzers are checked
against exactly what our renderer would output:
  * zoom: ``shortkit.edit.resolve.src_to_region`` (eased scale, fixed point / recenter) + the same
    warpAffine mapping as ``shortkit.edit.render`` on a synthetic texture;
  * flash: the renderer's flash overlay (alpha = 1 - |t - boundary| / (dur / 2)) on the video region
    only (``scope: region``) or on the whole canvas (``scope: canvas``);
  * decorations: ASS drawings from ``shortkit.edit.captions.decoration_events`` (arrow / circle / box
    with ``blink_hz``) burned with libass over moving synthetic footage.
None of this is reference-channel data.
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

import numpy as np

W, H, FPS = 540, 960, 30
BG = (30, 42, 90)


def texture(w: int, h: int, seed: int = 7) -> np.ndarray:
    """Deterministic high-texture RGB image (random rectangles / circles / lines on smooth noise)."""
    import cv2

    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, (h // 16 + 1, w // 16 + 1, 3)).astype(np.uint8)
    img = cv2.resize(base, (w, h), interpolation=cv2.INTER_CUBIC)
    for _ in range(int(w * h / 900)):
        c = tuple(int(v) for v in rng.integers(0, 255, 3))
        x, y = int(rng.integers(0, w)), int(rng.integers(0, h))
        r = int(rng.integers(3, 18))
        k = rng.integers(0, 3)
        if k == 0:
            cv2.rectangle(img, (x, y), (x + r, y + int(rng.integers(3, 18))), c, -1)
        elif k == 1:
            cv2.circle(img, (x, y), r, c, -1)
        else:
            cv2.line(img, (x, y), (x + int(rng.integers(-30, 30)), y + int(rng.integers(-30, 30))), c, 2)
    # keep the texture desaturated so it never looks like a saturated decoration
    hsv = cv2.cvtColor(img, cv2.COLOR_RGB2HSV)
    hsv[..., 1] = (hsv[..., 1] * 0.35).astype(np.uint8)
    return cv2.cvtColor(hsv, cv2.COLOR_HSV2RGB)


def write_video(path: Path, frames, w: int = W, h: int = H, fps: int = FPS, crf: int = 16) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt",
                          "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset",
                          "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE)
    for fr in frames:
        p.stdin.write(np.ascontiguousarray(fr, np.uint8).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    return path


# ----------------------------------------------------------------------------- zoom
ZOOM_REGION = (0.0, 210.0, 540.0, 540.0)
ZOOM_SRC = (960, 540)


def zoom_clip(ease: str, recenter: bool, center_src=(336.0, 270.0), scale_to: float = 1.3, start: float = 0.6,
              dur: float = 0.5, total: float = 1.8, fit: str = "cover"):
    from shortkit.edit.ir import Clip, Rect, Zoom

    rx, ry, rw, rh = ZOOM_REGION
    return Clip(id="z", source_id="tex", source_path="tex.png", src_in=0.0, src_out=total, speed=1.0,
                out_start=0.0, out_end=total, region=Rect(rx, ry, rw, rh), fit=fit, src_size=ZOOM_SRC,
                zoom=Zoom(scale_from=1.0, scale_to=scale_to, center_src=tuple(center_src), start=start, dur=dur,
                          ease=ease, recenter=recenter))


def zoom_frames(clip, total: float, seed: int = 3):
    """Frames exactly as shortkit.edit.render.clip_canvas maps a still source (src_to_region + the
    renderer's warpAffine convention), plus +-2 levels of per-frame noise."""
    import cv2

    from shortkit.edit.resolve import src_to_region

    src = texture(*ZOOM_SRC, seed=seed)
    rng = np.random.default_rng(seed + 1)
    rx, ry, rw, rh = (int(v) for v in ZOOM_REGION)
    n = int(round(total * FPS))
    for k in range(n):
        u = k / FPS
        sc, tx, ty = src_to_region(clip, u)
        M = np.array([[sc, 0.0, tx + 0.5 * sc - 0.5], [0.0, sc, ty + 0.5 * sc - 0.5]], np.float64)
        reg = cv2.warpAffine(src, M, (rw, rh), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_CONSTANT,
                             borderValue=BG)
        canvas = np.empty((H, W, 3), np.uint8)
        canvas[:] = BG
        canvas[ry:ry + rh, rx:rx + rw] = reg
        noise = rng.integers(-2, 3, canvas.shape)
        yield np.clip(canvas.astype(int) + noise, 0, 255).astype(np.uint8)


def build_zoom_mock(out: Path, ease: str, recenter: bool, **kw) -> tuple[Path, dict]:
    total = kw.pop("total", 1.8)
    clip = zoom_clip(ease, recenter, total=total, **kw)
    write_video(out, zoom_frames(clip, total))
    rx, ry, rw, rh = ZOOM_REGION
    return out, {"region": {"x": int(rx), "y": int(ry), "w": int(rw), "h": int(rh)}, "ease": ease,
                 "recenter": recenter, "start": clip.zoom.start, "dur": clip.zoom.dur, "scale_to": clip.zoom.scale_to}


# ----------------------------------------------------------------------------- flash
FLASH_REGION = (0, 300, 540, 304)


def flash_frames(scope: str, color=(255, 255, 255), boundary: float = 1.0, dur: float = 0.2, total: float = 2.0,
                 seed: int = 11):
    """Two 'shots' of scrolling texture with a renderer flash at the boundary."""
    rx, ry, rw, rh = FLASH_REGION
    a, b = texture(rw + 200, rh, seed), texture(rw + 200, rh, seed + 5)
    n = int(round(total * FPS))
    col = np.array(color, np.float32)
    for k in range(n):
        t = k / FPS
        src = a if t < boundary else b
        off = int(3 * k) % 200
        canvas = np.empty((H, W, 3), np.uint8)
        canvas[:] = BG
        canvas[ry:ry + rh, rx:rx + rw] = src[:, off:off + rw]
        if abs(t - boundary) < dur / 2.0:
            alpha = 1.0 - abs(t - boundary) / (dur / 2.0)
            if scope == "canvas":
                x0, y0, x1, y1 = 0, 0, W, H
            else:
                x0, y0, x1, y1 = rx, ry, rx + rw, ry + rh
            reg = canvas[y0:y1, x0:x1].astype(np.float32)
            canvas[y0:y1, x0:x1] = np.clip(reg * (1 - alpha) + col * alpha + 0.5, 0, 255).astype(np.uint8)
        yield canvas


def build_flash_mock(out: Path, scope: str, **kw) -> tuple[Path, dict]:
    write_video(out, flash_frames(scope, **kw))
    rx, ry, rw, rh = FLASH_REGION
    return out, {"region": {"x": rx, "y": ry, "w": rw, "h": rh}, "scope": scope}


# ----------------------------------------------------------------------------- decorations
def footage_frames(total: float, seed: int = 21):
    """Moving desaturated footage in a band + solid background (the base under decorations)."""
    rx, ry, rw, rh = FLASH_REGION
    a = texture(rw + 400, rh, seed)
    n = int(round(total * FPS))
    for k in range(n):
        off = int(4 * k) % 400
        canvas = np.empty((H, W, 3), np.uint8)
        canvas[:] = BG
        canvas[ry:ry + rh, rx:rx + rw] = a[:, off:off + rw]
        yield canvas


def build_decoration_mock(out: Path, decorations: list[dict], total: float = 4.0, tmp: Path | None = None) -> Path:
    """Render decorations with the production ASS writer (shortkit.edit.captions) over footage.

    ``decorations``: [{kind, start, end, keyframes[{t,x,y,w,h,rotation}], blink_hz, style{...}}]."""
    from shortkit.edit.captions import AssDoc, decoration_events, style_line
    from shortkit.edit.ir import Decoration

    tmp = tmp or out.parent
    base = write_video(tmp / (out.stem + "_base.mp4"), footage_frames(total))
    doc = AssDoc(W, H)
    doc.styles.append(style_line("deco", "NotoSansCJKkr-Bold", 20, "#FFFFFF", "#000000", "#000000", 400, 0, 0))
    for i, d in enumerate(decorations):
        doc.events += decoration_events(Decoration(id=f"d{i}", kind=d["kind"], start=d["start"], end=d["end"],
                                                   keyframes=d["keyframes"], blink_hz=d.get("blink_hz", 0.0),
                                                   style=d["style"]), float(FPS))
    ass = tmp / (out.stem + ".ass")
    ass.write_text(doc.render(), encoding="utf-8")
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", str(base), "-vf",
                    f"ass={ass}", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p",
                    str(out)], check=True)
    return out


def ease_ref(u: float, kind: str) -> float:
    from shortkit.edit.resolve import ease
    return ease(u, kind)


_ = math
