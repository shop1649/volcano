"""Mask extraction, rendering, alignment and verdict rules (synthetic captions only)."""
from __future__ import annotations

import numpy as np
import pytest

from shortkit.reference import typography as T
from typography_helpers import clean_crop


def _iou(a, b):
    return (a & b).sum() / max(1, (a | b).sum())


def test_parse_rgb():
    assert T.parse_rgb("#FFE400") == (255, 228, 0)
    assert T.parse_rgb("&H0000E4FF") == (255, 228, 0)       # ASS &HAABBGGRR
    assert T.parse_rgb((1.2, 2, 3)) == (1, 2, 3)
    assert T.parse_rgb(None) is None
    with pytest.raises(ValueError):
        T.parse_rgb("#12")


@pytest.mark.parametrize("fill,outline", [((255, 255, 255), (0, 0, 0)), ((255, 228, 0), (0, 0, 0)),
                                          ((255, 255, 255), None)])
def test_extract_masks_matches_truth(fonts_ready, fill, outline):
    crop, _, truth = clean_crop("Pretendard Black", "아니 이게 무슨 일이야", 60, fill=fill, outline=outline)
    given = T.extract_masks(crop, fill, outline if outline is not None else (60, 90, 120))
    assert _iou(given["fill"], truth) > 0.97
    est = T.extract_masks(crop)
    assert est["estimated"] is True
    assert np.linalg.norm(np.array(est["fill_rgb"]) - np.array(fill)) < 40
    assert _iou(est["fill"], truth) > 0.95


def test_extract_masks_drops_background_blobs_of_fill_colour(fonts_ready):
    crop, _, truth = clean_crop("Pretendard Black", "저기 봐", 64)
    crop = crop.copy()
    crop[:6, :] = 255          # white background strip touching the border (same colour as the fill)
    crop[-9:-3, 2:12] = 255    # white blob near the border, not wrapped by outline
    m = T.extract_masks(crop, (255, 255, 255), (0, 0, 0))
    assert _iou(m["fill"], truth) > 0.97


def test_font_iou_clean_self_beats_others(fonts_ready):
    crop, xy, _ = clean_crop("Gothic A1 Black", "결국 참지 못한 남자", 56)
    r_self = T.font_iou(crop, "결국 참지 못한 남자", "Gothic A1 Black", 56, (255, 255, 255), (0, 0, 0), glyphs=True)
    assert r_self["iou"] > 0.95
    assert abs(r_self["scale"] - 1.0) < 0.02
    assert abs(r_self["dx"] - xy[0]) < 0.6 and abs(r_self["dy"] - xy[1]) < 0.6
    assert len(r_self["glyphs"]) == len("결국참지못한남자")
    for other in ("Black Han Sans", "Jua", "Pretendard Black"):
        r = T.font_iou(crop, "결국 참지 못한 남자", other, 56, (255, 255, 255), (0, 0, 0))
        assert r["iou"] < r_self["iou"] - 0.03, (other, r["iou"], r_self["iou"])


def test_font_iou_accepts_path_and_ttc_index(fonts_ready):
    from shortkit import fonts

    face = fonts.resolve_font("Noto Sans CJK KR Black")
    if face is None:
        pytest.skip("Noto Sans CJK KR Black not installed")
    crop, _, _ = clean_crop("Noto Sans CJK KR Black", "역대급 반전", 50)
    by_path = T.font_iou(crop, "역대급 반전", str(face.path), 50, (255, 255, 255), (0, 0, 0), face_index=face.index)
    assert by_path["iou"] > 0.95
    assert by_path["font"] == "Noto Sans CJK KR Black"


def test_multiline_text(fonts_ready):
    a, _, ta = clean_crop("Pretendard Black", "아니 이게", 50, margin_frac=0.2)
    b, _, tb = clean_crop("Pretendard Black", "무슨 일이야", 50, margin_frac=0.2)
    w = max(a.shape[1], b.shape[1])
    crop = np.zeros((a.shape[0] + b.shape[0], w, 3), np.uint8)
    crop[:] = (60, 90, 120)
    crop[:a.shape[0], :a.shape[1]] = a
    crop[a.shape[0]:, :b.shape[1]] = b
    r = T.font_iou(crop, "아니 이게\n무슨 일이야", "Pretendard Black", 50, (255, 255, 255), (0, 0, 0))
    assert r["iou"] > 0.93 and len(r["lines"]) == 2


def test_verdict_rules():
    ceil = {"n": 24, "p10": 0.93, "p50": 0.95, "p90": 0.97, "noise": {"p90": 0.03}}
    assert T._verdict(0.96, True, 0.05, True, ceil)[0] == "identical"
    # margin within measured noise -> never identical
    v, reasons = T._verdict(0.96, True, 0.02, True, ceil)
    assert v == "similar" and any("잡음" in r for r in reasons)
    # below ceiling p10 -> not identical even with a big margin
    assert T._verdict(0.92, True, 0.2, True, ceil)[0] == "similar"
    # glyph check failed
    assert T._verdict(0.96, True, 0.05, False, ceil)[0] == "similar"
    # far below the ceiling -> different
    assert T._verdict(0.85, False, -0.1, None, ceil)[0] == "different"
    # no ceiling -> unmeasured (never a guess)
    assert T._verdict(0.99, True, 0.5, True, {"n": 0, "p10": None})[0] == "unmeasured"
    assert T._verdict(0.99, True, 0.5, True, None)[0] == "unmeasured"


def test_identify_requires_ceiling_or_conditions(fonts_ready):
    crop, _, _ = clean_crop("Jua", "저기 봐", 40)
    with pytest.raises(ValueError):
        T.identify(crop, "저기 봐", ["Jua", "Gugi"], None)


def test_degrade_scales_to_reference_resolution():
    cond = T.Conditions(canvas=(1080, 1920), ref_resolution=(720, 1280), crf=30, x264_preset="veryfast")
    frames = [np.full((96, 1080, 3), v, np.uint8) for v in (0, 128, 255)]
    out = T.degrade(frames, cond)
    assert len(out) == 3 and out[0].shape == (64, 720, 3)
    assert abs(int(out[1].mean()) - 128) < 6


def test_style_colors_textboxes_vocabulary():
    st = T._style_colors({"color": "#FFE400", "outline_color": "#000000", "outline_visibility": "visible",
                          "outline_px": 5.0, "bg_color": "#203040", "ink_h": 50})
    assert st["fill"] == (255, 228, 0) and st["edge"] == (0, 0, 0) and st["outline_px"] == 5.0
    st = T._style_colors({"color": "#FFFFFF", "outline_color": "#101010", "outline_visibility": "none",
                          "bg_color": "#203040"})
    assert st["outline"] is None and st["edge"] == (0x20, 0x30, 0x40)     # no outline: edge = background
    st = T._style_colors({"outline_visibility": "unmeasured"})
    assert st["fill"] is None and st["edge"] is None                       # -> estimated from the crop


def test_measure_caption_qp_on_known_constant_qp_clip(tmp_path):
    from shortkit.util.media import FFMPEG, run

    clip = tmp_path / "qp27.mp4"     # SYNTHETIC lavfi test pattern encoded at a known constant QP
    run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=10:d=2", "-c:v", "libx264",
         "-preset", "veryfast", "-qp", "27", "-x264-params", "ipratio=1.0:pbratio=1.0:aq-mode=0",
         "-pix_fmt", "yuv420p", str(clip)])
    q = T.measure_caption_qp(clip, [(0.5, 1.0, [32, 32, 120, 48])])
    assert q["qp"]["p50"] == 27 and q["spans"][0]["n_mb"] >= 8
    # and the emulation encodes caption macroblocks at exactly that QP
    cond = T.Conditions(canvas=(320, 240), ref_resolution=(320, 240), qp=27, x264_preset="veryfast")
    assert cond.label() == "h264_qp27_320x240"
    out = T.degrade([np.full((240, 320, 3), 90, np.uint8)] * 3, cond)
    assert len(out) == 3


def test_unscorable_crop_is_reported_not_guessed(fonts_ready):
    good, _, _ = clean_crop("Jua", "저기 봐", 48)
    blank = np.full((60, 200, 3), 128, np.uint8)       # no caption at all
    items = [{"crop": good, "text": "저기 봐", "size_hint_px": 48, "id": "good"},
             {"crop": blank, "text": "저기 봐", "size_hint_px": 48, "id": "blank"}]
    ceil = {"*": {"n": 10, "p10": 0.9, "p50": 0.95, "p90": 0.97, "noise": {"p90": 0.02},
                  "glyph": {"p10": 0.85, "p50": 0.95}}}
    r = T.identify_many(items, ["Jua", "Gugi"], ceil, color_mode="estimated")
    assert [f["id"] for f in r["failed_crops"]] == ["blank"]
    assert r["ranked"][0]["font"] == "Jua" and len(r["ranked"][0]["per_crop"]) == 1


def test_extract_masks_adds_the_highlight_colour(fonts_ready):
    """mockloop defect: a title with one highlighted word (second fill colour) lost that word from the fill
    mask -> glyph IoU 0.00 for its syllables and the right font (ranked first) was judged 'different'.
    ``alt_fill_rgb`` (the caption's measured highlight colour) adds those glyphs."""
    crop, xy, truth = clean_crop("Pretendard Black", "빈 방에 온 사람들", 60, fill=(255, 243, 176))
    # recolour the last word as the highlight: same glyph pixels, yellow instead of cream
    f = T.load_font(T.font_ref("Pretendard Black").abspath, 60, T.font_ref("Pretendard Black").index)
    x_hl = xy[0] + f.getlength("빈 방에 온 ")
    hl = truth.copy()
    hl[:, :int(x_hl)] = False
    img = crop.copy()
    img[hl] = (255, 212, 0)
    only_main = T.extract_masks(img, (255, 243, 176), (0, 0, 0))
    both = T.extract_masks(img, (255, 243, 176), (0, 0, 0), alt_fill_rgb=(255, 212, 0))
    assert _iou(only_main["fill"], truth) < 0.8                 # the highlighted word is missing
    assert _iou(both["fill"], truth) > 0.95
    assert not (both["fill"] & both["outline"]).any()
