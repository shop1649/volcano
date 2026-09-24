"""Ceiling / discriminability / identify() on SYNTHETIC degraded captions (slow: ffmpeg + many IoU searches)."""
from __future__ import annotations

import numpy as np
import pytest

from shortkit.reference import typography as T
from typography_helpers import degrade_and_crop, frankenstein_frame

pytestmark = pytest.mark.slow

CANDIDATES = ["Gothic A1 Black", "Pretendard Black", "Noto Sans CJK KR Black", "NanumGothic ExtraBold",
              "Black Han Sans", "Do Hyeon", "Gothic A1 ExtraBold", "NanumSquare ExtraBold"]
COND23 = T.Conditions(crf=23, x264_preset="veryfast", background="black")
CEIL_KW = dict(strings=T.DEFAULT_STRINGS[3:6], sizes=[48, 72], repeats=2,
               styles=("white_black_outline", "yellow_black_outline"))


def _ceilings(names, cond, **kw):
    out = {}
    for n in names:
        fr = T.font_ref(n)
        sams = T.make_samples(fr, kw["strings"], kw["sizes"], cond, kw["styles"], kw["repeats"], seed=11,
                              style_cycle=True)
        out[fr.name] = T.ceiling(fr, cond, samples=sams)
    return out


@pytest.fixture(scope="module")
def ceilings23(fonts_ready):
    resolved = [n for n in CANDIDATES if _has(n)]
    if len(resolved) < 6:
        pytest.skip(f"need >= 6 candidate fonts, have {resolved}")
    return _ceilings(resolved, COND23, **CEIL_KW)


def _has(name):
    from shortkit import fonts

    return fonts.resolve_font(name) is not None


def test_ceiling_stats_computed(ceilings23):
    for name, c in ceilings23.items():
        assert c["n"] == 3 * 2 * 2
        assert c["p10"] <= c["p50"] <= c["p90"] <= 1.0
        assert c["p50"] > 0.85, (name, c)
        assert c["noise"]["n"] == 6 and c["noise"]["p90"] is not None
        assert c["glyph"]["n"] > 0 and c["glyph"]["min"] <= c["glyph"]["p10"]
        assert set(c["by_size"]) == {"48", "72"}
        assert c["conditions"]["label"] == "h264_crf23_1080x1920"


@pytest.mark.parametrize("font_a", ["Gothic A1 Black", "Pretendard Black"])
@pytest.mark.parametrize("style", ["white_black_outline", "yellow_black_outline"])
def test_identify_ranks_true_font_first_as_identical(ceilings23, font_a, style):
    sm = T.make_samples(T.font_ref(font_a), ["아니 이게 무슨 일이야"], [64], COND23, styles=(style,), repeats=1,
                        seed=3)[0]
    r = T.identify(sm.crop, sm.text, list(ceilings23), COND23, size_hint_px=sm.size_px, ceilings=ceilings23)
    assert len(r["ranked"]) >= 6
    top = r["ranked"][0]
    assert top["font"] == font_a
    assert top["verdict"] == "identical", top["reasons"]
    assert top["margin"] > top["ceiling_used"]["noise_p90"]
    assert top["iou"] >= top["ceiling_used"]["p10"]
    assert "동일 판정" in r["summary"] and font_a in r["summary"]
    assert all(row["verdict"] != "identical" for row in r["ranked"][1:])


def test_swapped_glyph_is_not_identical(ceilings23):
    """One syllable drawn in another font (same layout): per-glyph check must stop 'identical'."""
    text = "아니 이게 무슨 일이야"
    frame, box = frankenstein_frame("Pretendard Black", "Black Han Sans", text, text.index("무"), 64, 1080, 160)
    crop = degrade_and_crop(frame, box, COND23)
    r = T.identify(crop, text, list(ceilings23), COND23, size_hint_px=64, ceilings=ceilings23)
    row = next(x for x in r["ranked"] if x["font"] == "Pretendard Black")
    assert row["verdict"] != "identical", row["reasons"]
    assert row["glyph_pass"] is False or row["iou"] < row["ceiling_used"]["p10"]
    if row["glyph_below_floor"]:
        assert any(w["ch"] == "무" for w in row["glyph_below_floor"])


def test_near_duplicate_weight_not_identical_within_noise(fonts_ready):
    """Pretendard Bold vs ExtraBold (and Noto Sans CJK KR Bold, whose Hangul Pretendard derives from).

    The near duplicate must never be called identical; the winner is 'identical' only when its
    margin exceeds the measured noise, and otherwise the report says it cannot be confirmed."""
    names = [n for n in ["Pretendard Bold", "Pretendard ExtraBold", "Pretendard Black", "Noto Sans CJK KR Bold",
                         "Gothic A1 ExtraBold", "NanumGothic ExtraBold"] if _has(n)]
    if len(names) < 6:
        pytest.skip("near-duplicate candidates missing")
    cond = T.Conditions(crf=32, x264_preset="veryfast", background="black")
    ceil = _ceilings(names, cond, strings=T.DEFAULT_STRINGS[:3], sizes=[40, 56], repeats=2,
                     styles=("white_black_outline",))
    disc = T.discriminability("Pretendard Bold", ["Pretendard ExtraBold"], cond,
                              samples=T.make_samples(T.font_ref("Pretendard Bold"), T.DEFAULT_STRINGS[:3], [40, 56],
                                                     cond, ("white_black_outline",), 2, seed=11),
                              self_ceiling=None)
    pair = disc["pairs"][0]
    assert pair["other"] == "Pretendard ExtraBold" and pair["cross_iou"]["n"] == 12
    assert pair["separable"] == (pair["margin"]["p10"] > pair["noise_p90"])
    checked = 0
    for s, size in (("결국 참지 못한 남자", 40), ("사장님의 한마디", 40), ("잠깐만 이거 진짜야?", 56)):
        sm = T.make_samples(T.font_ref("Pretendard Bold"), [s], [size], cond, repeats=1, seed=5)[0]
        r = T.identify(sm.crop, s, names, cond, size_hint_px=sm.size_px, ceilings=ceil)
        rows = {x["font"]: x for x in r["ranked"]}
        assert rows["Pretendard ExtraBold"]["verdict"] != "identical"
        assert rows["Noto Sans CJK KR Bold"]["verdict"] != "identical"
        top = r["ranked"][0]
        noise = top["ceiling_used"]["noise_p90"]
        if top["verdict"] == "identical":
            assert top["font"] == "Pretendard Bold"
            assert top["margin"] > noise and top["iou"] >= top["ceiling_used"]["p10"] and top["glyph_pass"]
        else:
            assert "동일 확정 불가" in r["summary"] or "다름" in r["summary"] or "different" in str(r["top_verdict"])
            if top["margin"] <= noise:
                assert any("잡음" in x for x in top["reasons"])
        checked += 1
    assert checked == 3


def test_identify_many_aggregates_crops(ceilings23):
    fr = T.font_ref("Gothic A1 Black")
    sams = T.make_samples(fr, T.DEFAULT_STRINGS[:2], [56], COND23, styles=("white_black_outline",), repeats=1, seed=9)
    items = [{"crop": s.crop, "text": s.text, "size_hint_px": s.size_px, "fill_rgb": s.fill_rgb,
              "outline_rgb": s.outline_rgb, "id": f"s{i}"} for i, s in enumerate(sams)]
    r = T.identify_many(items, list(ceilings23), ceilings23, color_mode="given")
    assert r["n_crops"] == 2
    top = r["ranked"][0]
    assert top["font"] == "Gothic A1 Black" and len(top["per_crop"]) == 2
    assert abs(top["iou"] - float(np.median([c["iou"] for c in top["per_crop"]]))) < 1e-3
