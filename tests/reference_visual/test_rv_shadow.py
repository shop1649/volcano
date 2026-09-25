"""The reference analyzer measures a caption's drop shadow (textboxes.measure_line -> shortkit.util.textmeasure.drop_shadow,
the estimator QA uses on our output).

SYNTHETIC: captions drawn with the production renderer's own ASS functions (shortkit.edit.captions: layout_text,
role_style_line -> libass) over a static smooth grey texture, then read by the analyzer's own pipeline (track_lines ->
_measure_track).  Known values: shadow offset / colour, outline, fill.  Not reference-channel data.

The old reference function ended its search at k = 1 (that ring lies inside the dilated ink) and returned 0 for every
shadow; with a black outline + black shadow the fill segmentation also took the outline as the fill (colour #000000,
OCR '브림자테스트'), so the whole line style was wrong.
"""
from __future__ import annotations

import dataclasses
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

from shortkit.reference.common import color_dist

W, H, FPS = 720, 1280, 30
TEXT = "그림자 테스트 줄"
# id, size, fill, outline_px, shadow_px, shadow_color, y
CASES = [
    ("none", 52.0, "#FFFFFF", 4.0, 0.0, "#000000", 150),
    ("black4", 52.0, "#FFFFFF", 4.0, 4.0, "#000000", 300),
    ("blue5", 52.0, "#FFFFFF", 3.0, 5.0, "#2040C0", 450),
    ("thin2", 48.0, "#FFFFFF", 2.0, 2.0, "#000000", 600),
    ("yellow_no_outline3", 56.0, "#FFE400", 0.0, 3.0, "#000000", 750),
    ("yellow_thick6", 60.0, "#FFE400", 6.0, 0.0, "#000000", 900),
]
SHADOW_TOL = 1.0      # = shortkit.qa.checks.SHADOW_TOL_PX (the QA output check uses the same estimator)
OUTLINE_TOL = 0.8


def _texture(seed: int = 5) -> np.ndarray:
    import cv2

    rng = np.random.default_rng(seed)
    g = rng.normal(0.0, 1.0, (H // 40 + 2, W // 40 + 2)).astype(np.float32)
    g = cv2.resize(g, (W, H), interpolation=cv2.INTER_CUBIC)
    g = 132.0 + 26.0 * g / max(1e-6, float(np.abs(g).max()))
    return np.clip(np.stack([g, g * 0.98 + 2, g * 0.96 + 4], axis=2), 0, 255).astype(np.uint8)


def _render(d: Path) -> Path:
    from shortkit.edit import captions as cm

    rf = cm.resolve_font("Noto Sans CJK KR Black")
    pr = cm.probe_ass_names([rf.face])
    name = (pr.get((str(rf.face.path), int(rf.face.index))) or {}).get("name")
    if name:
        rf = dataclasses.replace(rf, libass_name=name)
    fonts = d / "fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    dst = fonts / Path(rf.face.path).name
    if not dst.exists():
        os.symlink(rf.face.path, dst)
    doc = cm.AssDoc(W, H)
    for cid, size, fill, ol, sh, sc, y in CASES:
        st = {"size_px": size, "color": fill, "outline_px": ol, "outline_color": "#000000", "shadow_px": sh,
              "shadow_color": sc, "max_chars_per_line": 20, "max_width_px": 680.0, "line_spacing": 1.15,
              "align": "center", "valign": "middle", "max_lines": 1}
        doc.styles.append(cm.role_style_line(cid, st, rf))
        lay = cm.layout_text(TEXT, rf.face, st, (360, y))
        ln = lay.lines[0]
        doc.events.append(cm.AssEvent(0, 0.0, 2.0, cid,
                                      f"{{\\an5\\pos({ln.center[0]:.2f},{ln.center[1]:.2f})}}" + ln.text))
    (d / "t.ass").write_text(doc.render(), encoding="utf-8")
    import cv2

    cv2.imwrite(str(d / "bg.png"), cv2.cvtColor(_texture(), cv2.COLOR_RGB2BGR))
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-loop", "1", "-framerate", str(FPS),
                    "-i", "bg.png", "-t", "1.2", "-vf", "subtitles=filename=t.ass:fontsdir=fonts,format=yuv420p",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "caps.mp4"], check=True, cwd=d)
    return d / "caps.mp4"


@pytest.fixture(scope="module")
def measured(tmp_path_factory):
    from shortkit.reference import textboxes as tb

    mp4 = _render(tmp_path_factory.mktemp("rv_shadow"))
    tracks, _ = tb.track_lines(mp4, 5.0)
    out = {}
    for tr in tracks:
        m = tb._measure_track(tr)
        if m is None:
            continue
        cy = m["bbox"][1] + m["bbox"][3] / 2
        case = min(CASES, key=lambda c: abs(c[6] - cy))
        if abs(case[6] - cy) < 40:
            out[case[0]] = m
    return out


def test_every_line_is_read_with_its_real_fill(measured):
    assert set(measured) == {c[0] for c in CASES}
    for cid, size, fill, ol, sh, sc, y in CASES:
        m = measured[cid]
        assert m["text"].replace(" ", "") == TEXT.replace(" ", ""), (cid, m["text"])
        assert color_dist(m["color"], fill) <= 40, (cid, m["color"])


@pytest.mark.parametrize("cid", [c[0] for c in CASES])
def test_reference_measures_the_drop_shadow(measured, cid):
    case = next(c for c in CASES if c[0] == cid)
    _, size, fill, ol, sh, sc, y = case
    m = measured[cid]
    rep = m["_rep"]["shadow"]
    assert rep["algo"] == "shortkit.util.textmeasure.drop_shadow/1" and rep["status"] == "measured", rep
    if sh == 0:
        assert m["shadow_px"] == 0.0 and m["shadow_color"] is None, rep
    else:
        assert m["shadow_px"] == pytest.approx(sh, abs=SHADOW_TOL), rep
        assert color_dist(m["shadow_color"], sc) <= 60, (m["shadow_color"], sc)
    if ol > 0:
        # a shadow in the outline colour no longer widens the outline (measured on the upper-left side)
        assert m["outline_px"] == pytest.approx(ol, abs=OUTLINE_TOL), (cid, m["outline_px"])


def test_shadow_estimator_units():
    """drop_shadow on hand-made masks: a (k, k) copy under a ring outline is found; no copy -> 0; dark background
    and a busy upper-left side -> 못 잼."""
    import cv2

    from shortkit.util.textmeasure import drop_shadow

    img = np.full((120, 300, 3), 140, np.uint8)
    fill = np.zeros((120, 300), bool)
    cv2.putText(fill.view(np.uint8), "SHADOW", (20, 80), cv2.FONT_HERSHEY_SIMPLEX, 2.0, 1, 9)
    fill = fill.astype(bool)
    dist = cv2.distanceTransform((~fill).astype(np.uint8), cv2.DIST_L2, 5)
    ink = fill | (dist <= 3)
    sh = np.zeros_like(ink)
    sh[5:, 5:] = ink[:-5, :-5]
    img[sh & ~ink] = (30, 60, 200)
    img[ink & ~fill] = (0, 0, 0)
    img[fill] = (255, 255, 255)
    r = drop_shadow(img, fill, (140, 140, 140))
    assert r["status"] == "measured" and r["shadow_px"] == pytest.approx(5, abs=1.0), r
    assert color_dist(r["shadow_color"], "#1E3CC8") <= 20
    flat = np.full_like(img, 140)
    flat[ink & ~fill] = (0, 0, 0)
    flat[fill] = (255, 255, 255)
    r0 = drop_shadow(flat, fill, (140, 140, 140))
    assert r0["status"] == "measured" and r0["shadow_px"] == 0.0
    assert drop_shadow(flat, fill, (20, 20, 20))["status"] == "unmeasured"
    busy = flat.copy()
    busy[~ink] = np.random.default_rng(1).integers(0, 255, (int((~ink).sum()), 3))
    assert drop_shadow(busy, fill, (140, 140, 140))["status"] == "unmeasured"
