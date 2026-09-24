"""SYNTHETIC test clip for shortkit.clean (clearly not real platform footage).

Two shots (CC-BY Intel sample clips, scaled to 960x540, 15 fps) with overlays burned in by
ffmpeg, rendered twice -- with and without overlays -- so the ground-truth rects are measured
from the pixel difference instead of guessed from font metrics:

- a text-free graphic logo (ring + triangle PNG) at the top-right for the whole clip (both shots)
- a moving watermark "@mover_clip": top-left for t < 5 s, bottom-right for t >= 5 s
- a Chinese burned-in subtitle (Tesseract here has no Chinese model) at the bottom, 1.5-3.5 s
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import numpy as np

from shortkit.util.media import ffmpeg, read_frames

LOGO_XY = (850, 24)
MOVER = {"text": "@mover_clip", "a": (24, 22), "b": (740, 492), "switch": 5.0}
ZH = {"text": "等一下 看这里", "start": 1.5, "end": 3.5}


def _font(pattern: str) -> str:
    return subprocess.run(["fc-match", "-f", "%{file}", pattern], capture_output=True, text=True).stdout.strip()


def make_logo_png(path: Path) -> None:
    import cv2

    img = np.zeros((72, 72, 4), np.uint8)
    cv2.circle(img, (36, 36), 30, (0, 140, 255, 255), 7, cv2.LINE_AA)
    pts = np.array([[36, 14], [58, 54], [14, 54]], np.int32)
    cv2.fillPoly(img, [pts], (255, 90, 20, 255), cv2.LINE_AA)
    cv2.imwrite(str(path), img)


def build(out_dir: Path, classroom: Path, people: Path) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    logo = out_dir / "synth_logo.png"
    make_logo_png(logo)
    base = out_dir / "synth_base.mp4"
    dirty = out_dir / "synth_overlays.mp4"
    latin = _font("DejaVu Sans:bold")
    cjk = _font("Noto Sans CJK SC:bold") or _font("Noto Sans CJK KR:bold")
    shots = ("[0:v]trim=0:4,setpts=PTS-STARTPTS,scale=960:540,fps=15,format=yuv420p[a];"
             "[1:v]trim=0:4,setpts=PTS-STARTPTS,scale=960:540,fps=15,format=yuv420p[b];"
             "[a][b]concat=n=2:v=1:a=0[base]")
    ffmpeg(["-i", classroom, "-i", people, "-filter_complex", shots, "-map", "[base]", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "16", "-threads", "2", base])
    mv, sw = MOVER, MOVER["switch"]
    draw = (f"[0:v][1:v]overlay={LOGO_XY[0]}:{LOGO_XY[1]}[l];"
            f"[l]drawtext=fontfile='{latin}':text='{mv['text']}':fontsize=22:fontcolor=white:borderw=2:bordercolor=black:"
            f"x={mv['a'][0]}:y={mv['a'][1]}:enable='lt(t,{sw})',"
            f"drawtext=fontfile='{latin}':text='{mv['text']}':fontsize=22:fontcolor=white:borderw=2:bordercolor=black:"
            f"x={mv['b'][0]}:y={mv['b'][1]}:enable='gte(t,{sw})',"
            f"drawtext=fontfile='{cjk}':text='{ZH['text']}':fontsize=34:fontcolor=white:borderw=3:bordercolor=black:"
            f"x=(w-text_w)/2:y=h-40-text_h:enable='between(t,{ZH['start']},{ZH['end']})'[v]")
    ffmpeg(["-i", base, "-loop", "1", "-i", logo, "-filter_complex", draw, "-map", "[v]", "-t", "8", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "16", "-threads", "2", dirty])
    truth = measure_truth(base, dirty)
    (out_dir / "synth_overlays.truth.json").write_text(json.dumps(truth, indent=1))
    return {"base": base, "dirty": dirty, "truth": truth}


def _bbox(mask: np.ndarray, region: tuple[int, int, int, int]) -> dict:
    x0, y0, x1, y1 = region
    ys, xs = np.nonzero(mask[y0:y1, x0:x1])
    return {"x": int(x0 + xs.min()), "y": int(y0 + ys.min()), "w": int(xs.max() - xs.min() + 1),
            "h": int(ys.max() - ys.min() + 1)}


def measure_truth(base: Path, dirty: Path) -> dict:
    """Ground truth rects from |dirty - base| at known times inside known areas."""
    def diff(t):
        a, b = read_frames(base, [t])[0], read_frames(dirty, [t])[0]
        return np.abs(a.astype(int) - b.astype(int)).max(axis=2) > 40
    d2, d6 = diff(2.5), diff(6.0)
    return {
        "resolution": [960, 540],
        "logo": {**_bbox(d6, (800, 0, 960, 130)), "start": 0.0, "end": 8.0},
        "mover_a": {**_bbox(d2, (0, 0, 400, 100)), "start": 0.0, "end": MOVER["switch"]},
        "mover_b": {**_bbox(d6, (600, 430, 960, 540)), "start": MOVER["switch"], "end": 8.0},
        "zh_sub": {**_bbox(d2, (200, 440, 700, 540)), "start": ZH["start"], "end": ZH["end"]},
        "note": "SYNTHETIC: overlays drawn by ffmpeg on CC-BY Intel sample clips",
    }


def build_pan(out_dir: Path, still_video: Path) -> dict:
    """SYNTHETIC moving-camera clip: a slow pan across a still frame of a CC-BY Intel sample clip
    with a text-free logo fixed at the top-left (a static overlay over moving content)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    logo = out_dir / "synth_logo.png"
    if not logo.exists():
        make_logo_png(logo)
    pan = out_dir / "synth_pan.mp4"
    base = out_dir / "synth_pan_base.mp4"
    common = ("[0:v]trim=start_frame=0:end_frame=1,loop=loop=149:size=1:start=0,setpts=N/15/TB,"
              "scale=1280:720,crop=640:360:'40+t*60':'100+t*25',format=yuv420p")
    ffmpeg(["-i", still_video, "-filter_complex", common + "[v]", "-map", "[v]", "-t", "5", "-r", "15",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-threads", "2", base])
    ffmpeg(["-i", still_video, "-i", logo, "-filter_complex", common + "[b];[1:v]scale=48:48[l];[b][l]overlay=20:16[v]",
            "-map", "[v]", "-t", "5", "-r", "15", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
            "-threads", "2", pan])
    a, b = read_frames(base, [2.0])[0], read_frames(pan, [2.0])[0]
    d = np.abs(a.astype(int) - b.astype(int)).max(axis=2) > 40
    return {"dirty": pan, "base": base, "truth": {"logo": {**_bbox(d, (0, 0, 200, 150)), "start": 0.0, "end": 5.0}}}
