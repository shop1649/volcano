"""Regression tests for the two QA false positives the clean-folder restore episode (test-restore-001) found.
Every picture here is SYNTHETIC (numpy noise textures through x264).

* speed: the slope of matched source time over OUTPUT time across a freeze reads as slow motion (s3: 0.883 for a
  1.0x clip with a 0.7 s hold) -- the slope is now taken over the footage's playback clock (hold removed);
* zoom: a subject walking to the camera fools the feature scale curve (s1: 1.89x over 6.8 s measured, plan 1.25x
  over 0.35 s) -- the planned eased zoom is now verified directly on the output (planned geometry incl. instants
  inside the zoom ramp, captions masked, +-4 % scale alternatives), and a wrong zoom is still caught.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

FFMPEG = "ffmpeg"
REPO = Path(__file__).resolve().parents[2]
W, H = 320, 180


def _write(path: Path, frames, fps: float) -> None:
    p = subprocess.Popen([FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset", "ultrafast",
                          "-crf", "12", "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(np.ascontiguousarray(f, dtype=np.uint8).tobytes())
    p.stdin.close()
    assert p.wait() == 0


def _scene(n: int, fps: float, grow: bool, seed: int = 3) -> list[np.ndarray]:
    """Static textured background + a textured square: moving sideways (grow=False) or growing like a person
    walking to the camera (grow=True)."""
    import cv2

    rng = np.random.default_rng(seed)
    bg = cv2.GaussianBlur(rng.integers(0, 255, (H, W, 3)).astype(np.uint8), (0, 0), 1.5)
    tex = cv2.GaussianBlur(rng.integers(0, 255, (64, 64, 3)).astype(np.uint8), (0, 0), 1.0)
    out = []
    for i in range(n):
        t = i / fps
        f = bg.copy()
        sz = int(round(40 + 35 * t)) if grow else 48
        sub = cv2.resize(tex, (sz, sz), interpolation=cv2.INTER_LINEAR)
        x0 = (W // 2 + 40 - sz // 2) if grow else int(20 + 60 * t)
        y0 = H // 2 - sz // 2
        x1, y1 = min(W, x0 + sz), min(H, y0 + sz)
        f[y0:y1, x0:x1] = sub[: y1 - y0, : x1 - x0]
        out.append(f)
    return out


def _ctx(mp4: Path, clip):
    from shortkit.util.media import probe

    return SimpleNamespace(fps=30.0, mp4=mp4, info=probe(mp4),
                           resolved=SimpleNamespace(clips=[clip], captions=[], decorations=[]))


@pytest.fixture()
def gen_dir(tmp_path, monkeypatch):
    r = tmp_path / "proj"
    r.mkdir()
    shutil.copy(REPO / "shortkit.root", r / "shortkit.root")
    monkeypatch.setenv("SHORTKIT_ROOT", str(r))
    d = r / "assets/test/generated"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ----------------------------------------------------------------------------- speed across a freeze
def test_speed_slope_is_taken_over_the_playback_clock_not_across_the_freeze_hold(gen_dir):
    """1.0x clip with a 0.7 s hold at source 1.5 s: speed_obs ~ 1.0 (was ~0.85 over raw output times)."""
    from shortkit.edit.ir import Clip, Freeze, Rect
    from shortkit.qa.probes_video import analyze_mapping, play_time

    src_fps, dur = 12.0, 4.0
    src = _scene(int(src_fps * dur), src_fps, grow=False)
    _write(gen_dir / "move12.mp4", src, src_fps)
    hold, f_src = 0.7, 1.5
    frames = []
    for i in range(int(round((dur - 0.1 + hold) * 30))):
        t = i / 30.0
        st = t if t < f_src else (f_src if t < f_src + hold else t - hold)
        frames.append(src[min(len(src) - 1, int(st * src_fps + 1e-6))])
    _write(gen_dir / "move12_freeze.mp4", frames, 30.0)
    c = Clip(id="s3", source_id="v", source_path="assets/test/generated/move12.mp4", src_in=0.0, src_out=dur - 0.1,
             speed=1.0, out_start=0.0, out_end=dur - 0.1 + hold, region=Rect(0.0, 0.0, float(W), float(H)), fit="cover",
             src_size=(W, H), freeze=Freeze(src_t=f_src, out_start=f_src, hold=hold))
    assert play_time(c, 1.0) == 1.0 and play_time(c, 1.8) == pytest.approx(1.5) and play_time(c, 3.0) == pytest.approx(2.3)
    it = analyze_mapping(_ctx(gen_dir / "move12_freeze.mp4", c))["clips"][0]
    assert it["status"] == "measured", it
    good = [s for s in it["samples"] if s["ncc"] >= 0.6 and s["decisive"]]
    assert any(s["t"] < f_src for s in good) and any(s["t"] > f_src + hold for s in good), it["samples"]
    tol = max(0.05, float(it.get("speed_quant_frac") or 0))
    assert it["speed_obs"] == pytest.approx(1.0, abs=tol), it
    # the old estimate (slope over raw output times) is visibly biased by the hold
    raw = float(np.polyfit([s["t"] for s in good], [s["matched_src_t"] for s in good], 1)[0])
    assert raw < 1.0 - tol, raw


# ----------------------------------------------------------------------------- zoom with a growing subject
def _render_zoomed(gen_dir: Path, name: str, zoom) -> Path:
    """Output = source frames placed with the RENDERER's geometry (edit.resolve.src_to_region) and ``zoom``."""
    import cv2

    from shortkit.edit.ir import Clip, Rect
    from shortkit.edit.resolve import src_to_region

    src = _scene(90, 30.0, grow=True)
    if not (gen_dir / "walk30.mp4").is_file():
        _write(gen_dir / "walk30.mp4", src, 30.0)
    rc = Clip(id="r", source_id="v", source_path="x", src_in=0.0, src_out=3.0, speed=1.0, out_start=0.0, out_end=3.0,
              region=Rect(0.0, 0.0, float(W), float(H)), fit="cover", src_size=(W, H), zoom=zoom)
    out = []
    for i, f in enumerate(src):
        s, tx, ty = src_to_region(rc, i / 30.0)
        M = np.array([[s, 0, tx], [0, s, ty]], np.float32)
        out.append(cv2.warpAffine(f, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE))
    p = gen_dir / f"{name}.mp4"
    _write(p, out, 30.0)
    return p


@pytest.mark.parametrize("rendered, confirmed", [
    ((1.0, 1.25, 1.0, 0.35, "out"), True),            # as planned
    ((1.0, 1.25, 1.3, 0.35, "out"), False),           # starts 0.3 s late
    ((1.0, 1.40, 1.0, 0.35, "out"), False),           # wrong final scale
    ((1.0, 1.25, 1.0, 1.20, "out"), False),           # much slower ramp
])
def test_planned_zoom_is_verified_on_the_output_geometry_and_a_wrong_zoom_is_not(gen_dir, rendered, confirmed):
    from shortkit.edit.ir import Clip, Rect, Zoom
    from shortkit.qa.probes_video import geometry_check

    a, b, st, du, ea = rendered
    mp4 = _render_zoomed(gen_dir, f"walk_zoom_{st}_{b}_{du}", Zoom(a, b, (160.0, 90.0), st, du, ea))
    zp = Zoom(1.0, 1.25, (160.0, 90.0), 1.0, 0.35, "out")
    c = Clip(id="s1", source_id="v", source_path="assets/test/generated/walk30.mp4", src_in=0.0, src_out=3.0, speed=1.0,
             out_start=0.0, out_end=3.0, region=Rect(0.0, 0.0, float(W), float(H)), fit="cover", src_size=(W, H), zoom=zp)
    ramp = [zp.start + zp.dur * q for q in (0.25, 0.5, 0.75)]
    g = geometry_check(_ctx(mp4, c), c, zoom_alt=(1.04, 1 / 1.04), extra_times=ramp)
    assert g["status"] == "measured" and g["n_extra"] == 3, g
    assert g["confirmed"] is confirmed, g


def test_zoom_row_trusts_the_geometry_only_with_in_ramp_evidence():
    from shortkit.qa.checks import _zoom_effective, _zoom_geometry_confirmed

    fooled = {"status": "measured", "expected": {"dur": 0.35, "ease": "out"}, "expected_final_ratio": 1.25,
              "measured_final_ratio": 1.89, "zoom_ratio_corrected": 1.89, "measured_dur": 6.77, "measured_ease": "inout"}
    geo = {"status": "measured", "confirmed": True, "n_extra": 3, "ncc_median": 0.99, "ncc_min": 0.97, "alt_gap_median": 0.05}
    assert _zoom_geometry_confirmed(dict(fooled, geometry=geo))
    assert not _zoom_geometry_confirmed(dict(fooled, geometry=dict(geo, n_extra=0)))      # no ramp instant checked
    assert not _zoom_geometry_confirmed(dict(fooled, geometry=dict(geo, confirmed=False)))
    eff = _zoom_effective(dict(fooled, geometry=geo))
    assert (eff["measured_final_ratio"], eff["measured_dur"], eff["measured_ease"], eff["observed_by"]) == \
        (1.25, 0.35, "out", "geometry")
    assert _zoom_effective(dict(fooled, geometry=dict(geo, confirmed=False)))["measured_final_ratio"] == 1.89
