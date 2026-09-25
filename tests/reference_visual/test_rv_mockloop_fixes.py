"""Regression tests for analyzer defects found by the SYNTHETIC mockloop validation
(docs/validation/mockloop.md).  Every clip here is generated on the fly (numpy -> ffmpeg) and is
clearly synthetic.

Stated tolerances: video region edges +-2 analysis steps (the detector samples at 216 px width, i.e.
~1.25 px at 270 px width -> +-3 px here).
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from shortkit.reference.common import detect_video_region, flat_border_color

W, H, FPS = 270, 480, 30
BG = (20, 33, 61)
BAND = (155, 307)          # footage rows [y0, y1)


def _write(path: Path, frames: list[np.ndarray]) -> None:
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "ultrafast",
                          "-crf", "16", "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(np.ascontiguousarray(f, dtype=np.uint8).tobytes())
    p.stdin.close()
    assert p.wait() == 0


def _static_camera_clip(path: Path, flash: bool = True) -> None:
    """Flat canvas + a STATIC textured footage band (CCTV-like: only a small square walks across it) +
    a caption box below it that pops on/off with changing 'text' + one full-canvas white flash."""
    rng = np.random.default_rng(7)
    tex = rng.integers(60, 200, size=(BAND[1] - BAND[0], W, 3)).astype(np.uint8)
    frames = []
    for i in range(6 * FPS):
        f = np.empty((H, W, 3), np.uint8)
        f[:] = BG
        f[BAND[0]:BAND[1]] = tex
        x = 10 + (i * 2) % (W - 40)                       # the only thing moving inside the footage
        f[BAND[0] + 60:BAND[0] + 80, x:x + 20] = (230, 230, 230)
        if (i // 15) % 2 == 0:                             # caption box on/off every 0.5 s, text changes
            f[360:384, 50:220] = (9, 15, 27)
            f[366:378, 60:210] = rng.integers(0, 2, size=(12, 150, 1)) * 255
        if flash and i in (60, 61):                         # full-canvas flash (scope canvas)
            f[:] = 255
        frames.append(f)
    _write(path, frames)


def test_region_of_static_camera_footage_on_flat_background(tmp_path):
    """mockloop defect: activity-only detection returned the caption box (x 270, y 1455, 560x35 on the
    1080x1920 mocks) because static-camera footage barely changes; the temporal-median colour against the
    flat background finds the footage band."""
    v = tmp_path / "static.mp4"
    _static_camera_clip(v)
    r = detect_video_region(v)
    vr = r["video_region"]
    assert vr is not None, r
    assert abs(vr["y"] - BAND[0]) <= 3 and abs(vr["y"] + vr["h"] - BAND[1]) <= 3, vr
    assert vr["x"] == 0 and vr["w"] == W, vr
    assert r["background"] == "color"
    bg = r["background_color"].lstrip("#")
    assert np.linalg.norm(np.array([int(bg[i:i + 2], 16) for i in (0, 2, 4)]) - BG) <= 12


def test_flat_border_color_refuses_non_flat_borders():
    rng = np.random.default_rng(1)
    noisy = rng.integers(0, 255, size=(96, 54, 3)).astype(float)
    assert flat_border_color(noisy) is None
    flat = np.empty((96, 54, 3))
    flat[:] = BG
    flat[30:60] = 128.0
    c = flat_border_color(flat)
    assert c is not None and np.allclose(c, BG)


# ----------------------------------------------------------------------------- crossfade vs zoom / motion
def _texture(seed: int, h: int, w: int) -> np.ndarray:
    import cv2

    rng = np.random.default_rng(seed)
    t = rng.integers(0, 255, size=(h // 8, w // 8, 3)).astype(np.uint8)
    return cv2.resize(t, (w, h), interpolation=cv2.INTER_CUBIC)


def _zoom_then_crossfade_clip(path: Path, still: np.ndarray, other: np.ndarray, center=(380, 250)) -> dict:
    """Static-camera still (empty room): 1 s still, a 0.4 s ease-out digital zoom 1.0 -> 1.35 about
    ``center``, 1 s still (zoomed), 0.3 s crossfade to a different scene, 1 s still.
    Truth: ONE crossfade at 2.4 s, NO crossfade at the zoom (1.0-1.4 s)."""
    import cv2

    h, w = still.shape[:2]
    B = other

    def zoomed(z: float) -> np.ndarray:
        cx, cy = center
        M = np.array([[z, 0, (1 - z) * cx], [0, z, (1 - z) * cy]], np.float32)
        return cv2.warpAffine(still, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

    frames = []
    for i in range(int(3.7 * FPS)):
        t = i / FPS
        if t < 1.0:
            f = still
        elif t < 1.4:
            u = (t - 1.0) / 0.4
            f = zoomed(1.0 + 0.35 * (1 - (1 - u) ** 3))
        elif t < 2.4:
            f = zoomed(1.35)
        elif t < 2.7:
            a = (t - 2.4) / 0.3
            f = (zoomed(1.35) * (1 - a) + B * a).astype(np.uint8)
        else:
            f = B
        frames.append(np.ascontiguousarray(f))
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{w}x{h}", "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16",
                          "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE)
    for f in frames:
        p.stdin.write(f.tobytes())
    p.stdin.close()
    assert p.wait() == 0
    return {"crossfade_t": 2.4, "zoom_t": 1.0}


def _still(name: str, t: float) -> np.ndarray:
    """One frame of a CC-BY Intel sample clip (768x432): people-detection 10 s = empty room,
    face-demographics 12 s = a man standing in a hallway."""
    from shortkit.util.media import read_frames

    src = Path(__file__).resolve().parents[2] / "assets/test/generated/video" / name
    if not src.is_file():
        pytest.skip("Intel sample clips missing: python -m shortkit testassets fetch-video --local-dir ...")
    return read_frames(src, [t])[0]


def test_zoom_ramp_is_not_a_crossfade(tmp_path):
    """mockloop defect: digital zoom ramps on low-texture static footage passed the blend test (mean
    residual 0.13-0.35 < 0.35) and became 0.3-0.7 s 'crossfades' that also hid the zoom from the motion
    analysis.  A crossfade mixes every changing pixel by the same weight; a zoom does not."""
    from shortkit.reference import shots

    v = tmp_path / "zx.mp4"
    truth = _zoom_then_crossfade_clip(v, _still("people-detection.mp4", 10.0),
                                      _still("face-demographics-walking-and-pause.mp4", 12.0))
    r = shots.analyze(v, "zx", region=None, out_dir=tmp_path)
    xf = [c for c in r["cuts"] if c["type"] == "crossfade"]
    assert not [c for c in xf if abs(c["t"] - truth["zoom_t"]) < 0.6], r["cuts"]
    assert len([c for c in xf if abs(c["t"] - truth["crossfade_t"]) <= 0.1]) == 1, r["cuts"]


# ----------------------------------------------------------------------------- zoom on low-frame-rate sources
def test_people_walking_in_a_12fps_source_is_not_a_zoom(tmp_path):
    """mockloop defect: a 12 fps CCTV-like clip played at 30 fps (every source frame duplicated 2-3x) with
    two people walking toward the camera produced 14 'zoom_in' events of 1.05-1.10 (ORB fits on the
    walking people; runs bridged duplicated frames).  No editorial zoom exists in this clip."""
    from shortkit.reference import motion, shots

    src = Path(__file__).resolve().parents[2] / "assets/test/generated/video/face-demographics-walking-and-pause.mp4"
    if not src.is_file():
        pytest.skip("Intel sample clips missing: python -m shortkit testassets fetch-video --local-dir ...")
    v = tmp_path / "walk30.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-ss", "28.5", "-t", "5", "-i", str(src),
                    "-vf", "fps=30", "-an", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(v)], check=True)
    sh = shots.analyze(v, "w", region=None, out_dir=tmp_path)
    m = motion.analyze(v, "w", region=None, out_dir=tmp_path, shots=sh, captions={}, decorations=False)
    assert not [e for e in m["events"] if e["type"].startswith("zoom")], m["events"]


def test_digital_zoom_scale_from_end_to_end_ecc(tmp_path):
    """The renderer-style digital zoom (ease-out 1.0 -> 1.35 over 0.4 s) on the static room is measured
    end to end (ECC) within +-0.03 and is not split into a crossfade."""
    from shortkit.reference import motion, shots

    v = tmp_path / "zx.mp4"
    _zoom_then_crossfade_clip(v, _still("people-detection.mp4", 10.0),
                              _still("face-demographics-walking-and-pause.mp4", 12.0))
    sh = shots.analyze(v, "zx", region=None, out_dir=tmp_path)
    m = motion.analyze(v, "zx", region=None, out_dir=tmp_path, shots=sh, captions={}, decorations=False)
    zi = [e for e in m["events"] if e["type"] == "zoom_in"]
    assert len(zi) == 1, m["events"]
    assert zi[0]["scale_to"] == pytest.approx(1.35, abs=0.03), zi[0]
    assert abs(zi[0]["t"] - 1.0) <= 0.1, zi[0]


# ----------------------------------------------------------------------------- caption OCR / tracking
@pytest.mark.parametrize("word", ["빤히", "멈칫", "헉!"])
def test_big_heavy_reaction_word_is_read_as_hangul(word):
    """mockloop defect: 110 px Pretendard Black reaction words were OCR'd at native size (the scale never
    went below 1.0) -> 'HTS'/'HiT|' at confidence 0-33 -> the whole reaction caption was dropped as
    'not text' in all 5 mocks.  The ink height is now normalised in both directions and a Hangul reading of
    usable confidence (>= 40) wins over a Latin misreading."""
    from PIL import Image, ImageDraw, ImageFont

    from shortkit.reference import textboxes as tb

    font = Path(__file__).resolve().parents[2] / "assets/fonts/Pretendard-Black.otf"
    if not font.is_file():
        pytest.skip("assets/fonts/Pretendard-Black.otf missing (shortkit doctor --fetch-fonts)")
    im = Image.new("L", (420, 200), 0)
    ImageDraw.Draw(im).text((40, 30), word, font=ImageFont.truetype(str(font), 110), fill=255)
    m = np.array(im) >= 128
    ys, xs = np.nonzero(m)
    txt, conf = tb.ocr_line(m, (int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)))
    assert tb.HANGUL_RE.search(txt) and conf >= 40, (txt, conf)
    assert tb.plausible_text(txt)


def _line(track, text, bbox, s, e, ink_h=34, color="#FFFFFF"):
    return {"track": track, "text": text, "bbox": list(bbox), "start_sample": s, "end_sample": e, "n_samples": 5,
            "ink_h": ink_h, "color": color}


def test_split_label_track_is_merged_but_consecutive_captions_are_not():
    from shortkit.reference.textboxes import merge_split_lines

    dt = 0.2
    split = [_line(1, "파란 셔츠 남성", (723, 783, 211, 34), 6.4, 8.4), _line(2, "셔츠 남성", (798, 783, 136, 34), 8.6, 9.6)]
    out = merge_split_lines(split, dt)
    assert len(out) == 1 and out[0]["text"] == "파란 셔츠 남성"
    assert out[0]["bbox"] == [723, 783, 211, 34] and out[0]["start_sample"] == 6.4 and out[0]["end_sample"] == 9.6
    # two different situation captions back to back in the same band stay two items
    cons = [_line(3, "한 여성이 방으로 들어와요", (236, 1453, 608, 54), 0.4, 2.8, 54),
            _line(4, "창가 쪽으로 걸어가요", (295, 1453, 491, 54), 3.0, 5.6, 54)]
    assert len(merge_split_lines(cons, dt)) == 2
    # a gap longer than 1.5 samples is a new appearance, not a broken track
    late = [split[0], _line(5, "셔츠 남성", (798, 783, 136, 34), 9.0, 9.6)]
    assert len(merge_split_lines(late, dt)) == 2


# ----------------------------------------------------------------------------- slow motion of a low-fps source
def test_half_speed_ramp_of_a_12fps_source(tmp_path):
    """mockloop defect: a 0.5x frame-duplication ramp of a 12 fps source rendered at 30 fps changes the
    unique-frame rate 0.4 -> 0.2; the absolute 0.25 floor hid all four such ramps.  Small changes are now
    accepted only with a regular duplication cadence of the same ratio on both sides."""
    from shortkit.reference import motion, shots

    src = Path(__file__).resolve().parents[2] / "assets/test/generated/video/face-demographics-walking-and-pause.mp4"
    if not src.is_file():
        pytest.skip("Intel sample clips missing: python -m shortkit testassets fetch-video --local-dir ...")
    v = tmp_path / "ramp.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", str(src), "-filter_complex",
                    "[0:v]trim=28.5:31.5,setpts=PTS-STARTPTS[a];[0:v]trim=31.5:33.0,setpts=2*(PTS-STARTPTS)[b];"
                    "[a][b]concat=n=2:v=1:a=0,fps=30[v]", "-map", "[v]", "-c:v", "libx264", "-crf", "16",
                    "-pix_fmt", "yuv420p", str(v)], check=True)
    sh = shots.analyze(v, "r", region=None, out_dir=tmp_path)
    assert not sh["cuts"], sh["cuts"]
    m = motion.analyze(v, "r", region=None, out_dir=tmp_path, shots=sh, captions={}, decorations=False)
    sp = [e for e in m["events"] if e["type"] == "speed"]
    assert len(sp) == 1, m["events"]
    assert sp[0]["factor"] == pytest.approx(0.5, abs=0.1) and sp[0]["t"] == pytest.approx(3.0, abs=0.2), sp[0]


# ----------------------------------------------------------------- outline on a dark semi-transparent box
CANVAS_NAVY = (16, 27, 56)      # 0.45 x this = #070C19, the box colour measured in the mockloop references


def _outlined_line_on_box(pad: tuple[int, int, int, int], outline: int = 5, margin: int = 40):
    """White text with a black ``outline`` px stroke on a black 0.55-alpha box = ink (fill + outline) +
    ``pad`` (left, top, right, bottom) -- the renderer's convention -- over a flat navy canvas; returned as
    the analyzer's line crop (ink bbox + ``margin``) and the detector bbox (= ink bbox).
    mockloop: #000 outline on the #070C19 box read 'indistinguishable' (single-line captions) or ~18 px
    (a multi-line block, whose one box reaches past the neighbour line and out of the crop)."""
    import cv2

    Hc, Wc = 700, 900
    fill = np.zeros((Hc, Wc), np.uint8)
    cv2.putText(fill, "SITUATION 42", (150, 300), cv2.FONT_HERSHEY_SIMPLEX, 2.0, 255, 9, cv2.LINE_AA)
    fill_b = fill >= 128
    dist = cv2.distanceTransform((~fill_b).astype(np.uint8), cv2.DIST_L2, 5)
    ink = dist <= outline
    ys, xs = np.nonzero(ink)
    ix0, iy0, ix1, iy1 = xs.min(), ys.min(), xs.max(), ys.max()
    img = np.empty((Hc, Wc, 3), float)
    img[:] = CANVAS_NAVY
    img[iy0 - pad[1]:iy1 + pad[3] + 1, ix0 - pad[0]:ix1 + pad[2] + 1] = 0.45 * np.asarray(CANVAS_NAVY, float)
    img[ink & ~fill_b] = 0.0
    a = (fill.astype(float) / 255.0)[..., None]
    img = np.clip(img * (1 - a) + 255.0 * a, 0, 255).astype(np.uint8)
    crop = img[iy0 - margin:iy1 + margin + 1, ix0 - margin:ix1 + margin + 1].copy()
    return crop, (margin, margin, int(ix1 - ix0 + 1), int(iy1 - iy0 + 1))


def test_black_outline_on_near_black_box_is_measured_and_pad_excludes_it():
    from shortkit.reference.textboxes import measure_line

    crop, core = _outlined_line_on_box(pad=(18, 8, 18, 8))
    m = measure_line(crop, core)
    assert m["outline_visibility"] == "visible"
    assert m["outline_px"] == pytest.approx(5.0, abs=1.0)
    assert m["box"]["present"] == "present"
    # pad is measured from the outline's outer edge (renderer contract), not from the glyph fill
    assert m["box"]["pad_x"] == pytest.approx(18, abs=2)
    assert m["box"]["pad_y"] == pytest.approx(8, abs=2)
    assert m["box"]["pad_fill_x"] - m["box"]["pad_x"] == pytest.approx(5, abs=1)


def test_outline_inside_a_block_box_that_leaves_the_crop_is_bounded_by_the_local_background():
    """First line of a two-line block: its box continues below the crop and the far field is the canvas,
    so the dark box must not be counted as outline up to the 0.5 x height cap."""
    from shortkit.reference.textboxes import measure_line

    crop, core = _outlined_line_on_box(pad=(26, 8, 26, 160))
    m = measure_line(crop, core)
    assert m["box"]["present"] != "present"
    assert m["outline_visibility"] == "visible"
    assert m["outline_px"] == pytest.approx(5.0, abs=1.0)


# ----------------------------------------------------------------- caption timing: rest fill mask vs background
def test_rest_fill_mask_keeps_only_the_measured_text_colour(monkeypatch):
    """mockloop defect (SYNTHmock03/04 reaction words, red fill + black outline, fade in/out over a beige
    wall): the luminance split of segment_line also put wall pixels that are brighter than the red text into
    the rest 'fill' mask; those pixels 'match the rest appearance' before the word exists (p ~ 0.25 > 0.1),
    so no text-free frame was found, motion_in/out stayed unmeasured and start/end fell back to the 5 fps
    samples (0.4 s late).  The rest fill mask is now limited to the fill colour measured on the lines.
    The contaminated segmentation is injected here (it depends on the exact footage behind the word)."""
    from shortkit.reference import textboxes as tb

    H, W = 120, 240
    wall, red = np.array([226, 214, 196.0]), np.array([255, 77, 77.0])
    bg = np.empty((H, W, 3)); bg[:] = wall
    bg += np.random.default_rng(1).normal(0, 3, size=bg.shape)
    glyph = np.zeros((H, W), bool); glyph[35:85, 50:90] = True; glyph[35:85, 120:190] = True
    outline = np.zeros((H, W), bool); outline[29:91, 44:96] = True; outline[29:91, 114:196] = True
    text = bg.copy(); text[outline] = 0.0; text[glyph] = red
    alphas = [0.0] * 12 + [min(1.0, k / 6.0) for k in range(1, 13)]
    frames = [(round(i / 30.0, 4), np.clip(bg * (1 - a) + text * a, 0, 255).astype(np.uint8)) for i, a in enumerate(alphas)]
    wall_strip = np.zeros((H, W), bool); wall_strip[29:91, 196:214] = True; wall_strip[29:91, 26:44] = True

    def seg(_img, core):
        return {"fill": glyph | wall_strip}

    monkeypatch.setattr(tb, "segment_line", seg)
    lines = [(26, 29, 188, 62)]
    tm0 = tb._text_masks(frames[-1][1], lines)
    assert tb.analyze_transition(frames, tm0, "in", 30.0)["type"] == "unmeasured"      # the old failure
    tm = tb._text_masks(frames[-1][1], lines, fill_hint=red)
    assert not (tm["fill"] & wall_strip).any()
    mi = tb.analyze_transition(frames, tm, "in", 30.0)
    assert mi["type"] == "fade"
    assert mi["t_zero"] == pytest.approx(11 / 30.0, abs=1.0 / 30)
    assert mi["dur_s"] == pytest.approx(6 / 30.0, abs=1.5 / 30)


# ----------------------------------------------------------------- detection: word glued to a scene frame
def test_label_word_touching_a_scene_frame_is_still_detected(monkeypatch):
    """mockloop defect (SYNTHmock01/02/05 speaker label '파란 셔츠 남성' read as '셔츠 남성'): at the 960-row
    working scale the first word's glyph tops touched a dark edge that ran along the top of the label and
    up (door-frame edges) to the video-region border, so the word joined one sparse frame-like component
    (540 x 102 px, density 0.05) that the 'rectangle outline' filter dropped whole.  Frame-like components
    are now peeled (straight runs cut out) and a peeled word is kept where it continues a kept text row."""
    from shortkit.reference import textboxes as tb
    from shortkit.reference.typography import draw_caption, load_font

    font = Path(__file__).resolve().parents[2] / "assets/fonts/Pretendard-Bold.otf"
    if not font.is_file():
        pytest.skip("assets/fonts/Pretendard-Bold.otf missing")
    img = np.empty((960, 540, 3), np.float32); img[:] = BG
    img[310:615] = (175, 172, 168)                                    # footage band (flat wall)
    txt = "파란 셔츠 남성"
    f = load_font(str(font), 19)
    x0, y0, x1, y1 = f.getbbox(txt, anchor="ls")
    bx, by = 356, 386
    img[by:by + (y1 - y0) + 6, bx:bx + (x1 - x0) + 16] = (230, 0, 126)   # pink label box, pad 3 px
    base = (bx + 8 - x0, by + 3 - y0)
    img, bb = draw_caption(img, txt, str(font), 19, base, (255, 255, 255))
    wx1 = int(base[0] + f.getbbox("파란", anchor="ls")[2])
    top = int(np.floor(bb[1]))
    img[top - 3:top - 1, bx:wx1 + 2] = 0.0                            # rail 1 px above the first word
    img[310:top - 1, bx:bx + 2] = 0.0                                 # posts up to the video border
    img[310:top - 1, wx1:wx1 + 2] = 0.0
    img = np.clip(img, 0, 255).astype(np.uint8)
    import cv2
    g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
    monkeypatch.setattr(tb, "PEEL_RUN_MIN_H", 1000.0)                 # no peel = the old behaviour
    old = [b for b in tb.detect_lines(img, g)[0] if 370 < b[1] < 420]
    assert old and min(b[0] for b in old) > bb[0] + 30                # first word lost
    monkeypatch.setattr(tb, "PEEL_RUN_MIN_H", 4.0)
    new = [b for b in tb.detect_lines(img, g)[0] if 370 < b[1] < 420]
    assert len(new) == 1
    x, y, w, h = new[0]
    assert x == pytest.approx(bb[0], abs=3) and x + w == pytest.approx(bb[2], abs=3)


def test_white_text_on_a_light_label_box_has_no_visible_outline():
    """Speaker label (white text on a 0.85 pink box, pad 6 px vertically): the ring profile steps where
    it leaves the box, but the ring colour IS the box colour -- no outline (was 1.2-4.4 px after the
    local-background change; the far-field box colour now also has to differ)."""
    import cv2

    from shortkit.reference.textboxes import measure_line

    Hc, Wc = 180, 520
    fill = np.zeros((Hc, Wc), np.uint8)
    cv2.putText(fill, "SPEAKER A", (60, 110), cv2.FONT_HERSHEY_SIMPLEX, 1.3, 255, 4, cv2.LINE_AA)
    fb = fill >= 128
    ys, xs = np.nonzero(fb)
    rng = np.random.default_rng(2)
    img = cv2.GaussianBlur(rng.integers(40, 220, size=(Hc, Wc, 3)).astype(np.float32), (0, 0), 3).astype(float)
    img[ys.min() - 6:ys.max() + 7, xs.min() - 16:xs.max() + 17] = (
        0.15 * img[ys.min() - 6:ys.max() + 7, xs.min() - 16:xs.max() + 17] + 0.85 * np.array([230, 0, 126.0]))
    a = (fill / 255.0)[..., None]
    img = np.clip(img * (1 - a) + 255.0 * a, 0, 255).astype(np.uint8)
    # the detector's box follows the gradient: 2 px around the glyphs
    core = (int(xs.min()) - 2, int(ys.min()) - 2, int(xs.max() - xs.min() + 5), int(ys.max() - ys.min() + 5))
    m = measure_line(img, core)
    assert m["outline_visibility"] in ("indistinguishable", "none")
    assert not m["outline_px"]
    assert m["box"]["present"] == "present"
    assert m["box"]["pad_x"] == pytest.approx(16, abs=2) and m["box"]["pad_y"] == pytest.approx(6, abs=2)


def test_block_box_around_a_two_line_caption():
    """One 0.55 black box around a two-line block (renderer: block ink incl. outline + pad): the per-line
    search cannot see it; the block search around the union of the glyph fills finds it and reports the
    pad from the outline edge."""
    import cv2

    from shortkit.reference.textboxes import _block_box

    H, W = 420, 760
    fills = []
    fill = np.zeros((H, W), np.uint8)
    cv2.putText(fill, "LINE ONE", (230, 170), cv2.FONT_HERSHEY_SIMPLEX, 2.0, 255, 9, cv2.LINE_AA)
    cv2.putText(fill, "SECOND LINE", (140, 250), cv2.FONT_HERSHEY_SIMPLEX, 2.0, 255, 9, cv2.LINE_AA)
    fb = fill >= 128
    dist = cv2.distanceTransform((~fb).astype(np.uint8), cv2.DIST_L2, 5)
    ink = dist <= 5
    ys, xs = np.nonzero(ink)
    img = np.empty((H, W, 3), float); img[:] = CANVAS_NAVY
    img[ys.min() - 8:ys.max() + 9, xs.min() - 18:xs.max() + 19] *= 0.45
    img[ink & ~fb] = 0.0
    img[fb] = 255.0
    img = img.astype(np.uint8)
    for (y0, y1) in ((100, 200), (200, 280)):
        band = np.zeros_like(fb); band[y0:y1] = True
        yy, xx = np.nonzero(fb & band)
        fills.append({"fill_bbox": [int(xx.min()), int(yy.min()), int(xx.max() - xx.min() + 1), int(yy.max() - yy.min() + 1)]})
    ref = {"_seg_in": [(0.0, img)], "region": {"x": 0, "y": 0, "w": W, "h": H}}
    box = _block_box(ref, fills, {"outline_px": 5.0, "outline_visibility": "visible"})
    assert box is not None and box["present"] == "present"
    assert box["pad_x"] == pytest.approx(18, abs=2) and box["pad_y"] == pytest.approx(8, abs=2)
    bx, by, bw, bh = box["bbox"]
    assert by == pytest.approx(ys.min() - 8, abs=2) and by + bh == pytest.approx(ys.max() + 9, abs=2)


def test_background_clipped_by_the_line_box_is_not_part_of_the_fill(monkeypatch):
    """mockloop defect (SYNTHmock04 reaction '두근', red fill + 6 px black outline over a wood floor): the
    floor is on the text's side of the luminance threshold, so the floor inside the corners of the line box
    joined the fill mask and came out as a 14-17 % second fill colour -> highlight_color #5A453A (the truth
    has no highlight) and a too-thin outline.  Pieces whose colour continues past the box edge are dropped."""
    from shortkit.reference import textboxes as tb
    from shortkit.reference.typography import draw_caption

    font = Path(__file__).resolve().parents[2] / "assets/fonts/Pretendard-Black.otf"
    if not font.is_file():
        pytest.skip("assets/fonts/Pretendard-Black.otf missing")
    bg = np.empty((300, 520, 3), np.float32); bg[:] = (40, 38, 52)        # dark trousers / shadow
    _, bb = draw_caption(bg.copy(), "두근", str(font), 110, (150, 200), (254, 76, 76), (0, 0, 0), 6)
    x0, y0, x1, y1 = (int(round(v)) for v in bb)
    bg[:y0 + 30, x1 - 40:] = (90, 69, 58)                                 # wood floor in the top-right corner,
    bg[y1 - 25:, :x0 + 30] = (90, 69, 58)                                 # ... and bottom-left, past the box
    img, bb = draw_caption(bg, "두근", str(font), 110, (150, 200), (254, 76, 76), (0, 0, 0), 6)
    img = np.clip(img, 0, 255).astype(np.uint8)
    core = (x0, y0, x1 - x0, y1 - y0)                                     # detector box = ink incl. outline
    m = tb.measure_line(img, core)
    assert m["highlight_color"] is None
    assert m["outline_px"] == pytest.approx(6.0, abs=1.0)
    monkeypatch.setattr(tb, "_drop_corner_background", lambda *a, **k: None)   # the old behaviour
    old = tb.measure_line(img, core)
    assert old["highlight_color"] is not None


def test_speech_ranges_read_the_original_json_speech_segments(tmp_path):
    """mockloop defect: textboxes read speech from original.json 'events', but audio_original writes
    'speech': {'presence', 'segments'} -> dialogue lead_s was never measured (4/4 dialogue captions had
    lead_s None) and speech never took part in role assignment."""
    import json

    from shortkit.reference.textboxes import _speech_ranges

    (tmp_path / "audio").mkdir()
    (tmp_path / "audio" / "original.json").write_text(json.dumps(
        {"speech": {"presence": "present", "confidence": "low",
                    "segments": [{"start": 9.08, "end": 11.21}, {"start": 12.0, "end": 12.5}]}}), encoding="utf-8")
    assert _speech_ranges(tmp_path) == [(9.08, 11.21), (12.0, 12.5)]
    (tmp_path / "audio" / "original.json").write_text(json.dumps({"speech": {"presence": "absent", "segments": []}}),
                                                     encoding="utf-8")
    assert _speech_ranges(tmp_path) is None
