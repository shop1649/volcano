"""Caption box pad semantics, measured from rendered pixels (libass through ffmpeg).

The reference analyzer measures ``box.pad_x`` / ``box.pad_y`` as (box edge - ink edge) of the
visible ink INCLUDING the outline stroke.  The renderer must draw the box as ink bbox (incl.
outline) + pad on each side, so the same measurement on our output gives the preset pad back."""
from __future__ import annotations

import subprocess

import numpy as np
import pytest

from conftest import load_preset, set_preset, write_plan

BG = (0, 255, 0)
BOX = (0, 0, 255)


def _render_ass_frame(root, ass_rel: str, fonts_rel: str, t: float, W: int, H: int) -> np.ndarray:
    """One RGB frame of the ASS file over a flat green canvas (blended in RGB, no chroma subsampling)."""
    vf = f"format=rgb24,subtitles=filename={ass_rel}:fontsdir={fonts_rel}"
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
           f"color=c=0x00FF00:s={W}x{H}:r=30:d={t + 1.0:.3f}", "-vf", vf, "-ss", f"{t:.3f}", "-frames:v", "1",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    out = subprocess.run(cmd, cwd=str(root), capture_output=True, check=True).stdout
    return np.frombuffer(out, np.uint8).reshape(H, W, 3).astype(np.int32)


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


@pytest.mark.parametrize("outline_px", [0, 5])
def test_box_pad_measured_from_pixels(root, plan, outline_px):
    from shortkit.edit.resolve import resolve_episode

    set_preset(root, "text.roles.speaker.box", {"enabled": True, "color": "#0000FF", "alpha": 1.0, "pad_x": 14, "pad_y": 6})
    set_preset(root, "text.roles.speaker.outline_px", outline_px)
    set_preset(root, "text.roles.speaker.color", "#FFFFFF")
    set_preset(root, "text.roles.speaker.outline_color", "#000000")
    set_preset(root, "text.roles.speaker.motion_in", {"type": "none", "dur_s": 0.0, "scale_from": 1.0, "offset_px": 0})
    set_preset(root, "text.roles.speaker.motion_out", {"type": "none", "dur_s": 0.0})
    plan["captions"] = [{"id": "c_spk", "role": "speaker", "text": "창가 남성 Ag", "start": 0.0, "end": 2.0,
                         "pos": [540, 400], "grounding": {"kind": "seen", "source": "a", "src_t": 1.0}}]
    plan["cover"]["text"] = "창가 남성 Ag"
    write_plan(root, plan)
    r = resolve_episode("t1")
    cap = r.captions[0]
    pr = load_preset()
    W, H = int(pr.get("canvas.width")), int(pr.get("canvas.height"))
    img = _render_ass_frame(root, r.ass_path, r.fonts_dir, 1.0, W, H)

    # box: >= 50 % box coverage over the green background (|BOX - BG| = 510 in summed RGB)
    not_bg = np.abs(img - np.array(BG)).sum(axis=2) > 255
    bx0, by0, bx1, by1 = _bbox(not_bg)
    inside = np.zeros_like(not_bg)
    inside[by0:by1, bx0:bx1] = True
    # ink = pixels that are NOT a blend of box blue and background green (those lie on R = 0, G + B = 255):
    # white fill (R = 255) and black outline (G + B = 0) are both >= 255 away; threshold ~50 % coverage
    resid = np.abs(img[..., 0]) + np.abs(img[..., 1] + img[..., 2] - 255)
    ink = inside & (resid > 128)
    ix0, iy0, ix1, iy1 = _bbox(ink)
    pads = {"left": ix0 - bx0, "right": bx1 - ix1, "top": iy0 - by0, "bottom": by1 - iy1}
    exp_x, exp_y = cap.box["pad_x"], cap.box["pad_y"]
    tol = 1.5
    print("DEBUG", outline_px, "box", (bx0, by0, bx1, by1), "ink", (ix0, iy0, ix1, iy1), "ir_bbox",
          (cap.bbox.x, cap.bbox.y, cap.bbox.x + cap.bbox.w, cap.bbox.y + cap.bbox.h), "rect", cap.box["rect"])
    assert abs(pads["left"] - exp_x) <= tol and abs(pads["right"] - exp_x) <= tol, (pads, exp_x)
    assert abs(pads["top"] - exp_y) <= tol and abs(pads["bottom"] - exp_y) <= tol, (pads, exp_y)
    # the IR ink bbox (incl. outline) is where libass really drew the ink
    b = cap.bbox
    assert abs(ix0 - b.x) <= tol and abs(ix1 - (b.x + b.w)) <= tol, ((ix0, ix1), (b.x, b.x + b.w))
    assert abs(iy0 - b.y) <= tol and abs(iy1 - (b.y + b.h)) <= tol, ((iy0, iy1), (b.y, b.y + b.h))
