"""Regression tests for the QA fixes of the qa-loop round.  Every signal here is SYNTHETIC (generated in the
test: PIL / libass text through x264, numpy noise, the generated music bed and TTS lines).

* tone: QA classifies the output's narration with the reference analyzer's classifier and aggregation
  (``shortkit.reference.aggregate.ending_class`` / ``tone_items``) -- the same thing validate enforces;
* highlight recolouring: yuv420 chroma bleed at the edges of a coloured (highlighted) word left pixels off the
  RGB colour line, the typography mask dropped whole glyph components (test-pipeline-001 c_sit4: 울 0.26);
* font ceiling: measured at the caption's EXACT size, over the flat colour really behind it, with the
  caption's own text, 12 samples (the size bucket / generic strings / 6 samples judged captions against the
  wrong threshold: c_sit3 'similar', c_dlg 'different' for the right font);
* kept original level: rel LU = L_src + fitted gain - programme loudness (definition of keep_gain_db);
* BGM loop: every repeat must start again at section_start (a jump elsewhere is a different section).
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import tempfile
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

REPO = Path(__file__).resolve().parents[2]
GEN = REPO / "assets/test/generated"


# ----------------------------------------------------------------------------- tone
@pytest.mark.parametrize("texts", [
    ["창가 남성이 일어선다", "다시 자리에 앉는다", "뒷줄 남성이 손을 든다", "움직임 테스트 영상"],
    ["이게 뭐예요", "진짜 놀랐어요", "그리고 떠난다"],
    ["결국 참지 못함", "다시 앉았음", "손을 든다"],
    ["고개를 기울입니다", "두 사람이 섰습니다"],
    ["빤히", "갸우뚱?", "두 사람"],                                  # noun phrases only -> no register
    ["한 사람이 나간다", "와 이게 뭐지", "정말 멋져요", "너무 좋아요", "대박이죠"],
])
def test_tone_register_same_classifier_and_rule_as_the_analyzer(texts):
    from shortkit.qa.probes_text import classify_register
    from shortkit.reference.aggregate import tone_items

    items = [{"role": "situation", "text": t} for t in texts]
    ref = tone_items({"v1": {"captions": {"items": items}, "format_id": None}}, "blocked")[0]
    got = classify_register(texts)
    assert got["mode"] == ref["value"]
    assert got["n"] == sum(v for k, v in (ref.get("ending_counts") or {}).items() if k != "명사형/기타")


def test_tone_uses_the_validate_classifier_not_a_last_letter_heuristic():
    """'-다' after a noun-like word and '-요' are classified by ending_class (the old last-letter heuristic
    called any final '다' 반말 and 요 해요체 regardless of the word)."""
    from shortkit.qa.probes_text import classify_register
    from shortkit.reference.aggregate import REGISTER_MAP, ending_class

    for t in ("두 사람이 고개를 기울입니다", "아이템", "요즘"):
        r = ending_class(t)
        got = classify_register([t])
        assert got["mode"] == (REGISTER_MAP.get(r[0]) if r and r[0] in REGISTER_MAP else None)


# ----------------------------------------------------------------------------- highlight recolouring
def _font():
    from shortkit.fonts import find_font, font_face_index

    p = find_font("Noto Sans CJK KR Black")
    if p is None:
        pytest.skip("Noto Sans CJK KR Black not installed")
    return p, font_face_index(p, "Noto Sans CJK KR Black") or 0


def _x264_roundtrip(img: np.ndarray) -> np.ndarray:
    """The renderer's output path for one frame: rgb -> bt709 yuv420p -> x264 crf 18 veryfast -> rgb."""
    from shortkit.util.media import FFMPEG

    H, W = img.shape[:2]
    with tempfile.TemporaryDirectory() as td:
        subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", "30",
                        "-i", "-", "-vf", "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p", "-c:v", "libx264",
                        "-preset", "veryfast", "-crf", "18", "-colorspace", "bt709", "-color_primaries", "bt709",
                        "-color_trc", "bt709", "-color_range", "tv", f"{td}/a.mp4"], input=img.tobytes() * 3, check=True)
        raw = subprocess.run([FFMPEG, "-v", "error", "-i", f"{td}/a.mp4", "-frames:v", "1", "-f", "rawvideo",
                              "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, check=True).stdout
    return np.frombuffer(raw, np.uint8).reshape(H, W, 3)


def test_highlight_recolour_keeps_glyphs_whose_edges_carry_chroma_bleed():
    from PIL import Image, ImageDraw, ImageFont

    from shortkit.qa.probes_text import recolor_blend, recolor_highlight
    from shortkit.reference.typography import extract_masks

    path, idx = _font()
    f = ImageFont.truetype(str(path), 60, index=idx)
    W, H = 704, 112

    def render(colors):
        im = Image.new("RGB", (W, H), (0, 0, 0))
        d = ImageDraw.Draw(im)
        x = 20
        for word, col in colors:
            d.text((x, 15), word, font=f, fill=col, stroke_width=6, stroke_fill=(0, 0, 0))
            x += d.textlength(word + " ", font=f)
        return np.array(im)

    white, yellow = (255, 255, 255), (255, 228, 0)
    hl = _x264_roundtrip(render([("고개를", white), ("기울인다", yellow)]))
    ref = extract_masks(_x264_roundtrip(render([("고개를", white), ("기울인다", white)])), white, (0, 0, 0))["fill"]

    def iou(m):
        return float((m & ref).sum()) / max(1, float((m | ref).sum()))

    old = extract_masks(recolor_blend(hl, yellow, white, (0, 0, 0)), white, (0, 0, 0))["fill"]
    new = extract_masks(recolor_highlight(hl, yellow, white, (0, 0, 0)), white, (0, 0, 0))["fill"]
    assert iou(old) < 0.9            # the bug: whole highlighted glyph components dropped (measured 0.78)
    assert iou(new) >= 0.99          # luma coverage keeps them (measured 0.998)


def test_recolour_without_luma_contrast_falls_back_to_rgb_line():
    from shortkit.qa.probes_text import recolor_blend, recolor_highlight

    img = np.zeros((10, 10, 3), np.uint8)
    img[3:7, 3:7] = (0, 0, 200)                     # dark blue highlight on black: luma contrast < 50
    a = recolor_highlight(img, (0, 0, 200), (255, 255, 255), (0, 0, 0))
    assert np.array_equal(a, recolor_blend(img, (0, 0, 200), (255, 255, 255), (0, 0, 0)))


# ----------------------------------------------------------------------------- font ceiling conditions
@pytest.fixture()
def temp_root(tmp_path, monkeypatch):
    r = tmp_path / "proj"
    r.mkdir()
    shutil.copy(REPO / "shortkit.root", r / "shortkit.root")
    monkeypatch.setenv("SHORTKIT_ROOT", str(r))
    return r


def test_ceiling_uses_exact_size_own_text_flat_background_and_12_samples(temp_root, monkeypatch):
    from shortkit.qa import font_id

    _font()
    seen = {}

    def fake_samples(ctx, font, size, fill, outline, outline_px, box, strings, crf, preset, fps, seed=7,
                     font_file=None, bg=None):
        seen.update(size=size, strings=list(strings), bg=bg, box=box, outline_px=outline_px)
        return [object()] * (len(strings) * font_id.CEIL_REPEATS), "color:#000000"

    def fake_ceiling(fr, cond, samples, color_mode, keep_rows):
        seen["n_samples"] = len(samples)
        seen["background"] = cond.background
        return {"n": len(samples), "p10": 0.96, "p50": 0.97, "p90": 0.98, "noise": {"p90": 0.01}, "glyph": {}}

    import shortkit.reference.typography as ty

    monkeypatch.setattr(font_id, "libass_samples", fake_samples)
    monkeypatch.setattr(ty, "ceiling", fake_ceiling)
    ctx = SimpleNamespace(options={"_font_id": {"encode": {"crf": 18.0, "preset": "veryfast", "source": "test"}}},
                          canvas_w=1080, canvas_h=1920, fps=30.0)
    text = "뒷줄 남성이 손을 든다"
    font_id.ceiling_for(ctx, "Noto Sans CJK KR Black", 66.0, (255, 255, 255), (0, 0, 0), 6.0, None,
                        bg=(1, 0, 2), strings=font_id.ceiling_strings(text))
    assert seen["size"] == 66.0 and font_id.size_bucket(66.0) != 66          # not the 63 px bucket
    assert seen["strings"] == [text] * 3
    assert seen["bg"] == (0, 0, 0) and seen["box"] is None                    # measured flat colour (quantised)
    assert seen["outline_px"] == pytest.approx(6.0, abs=0.01)          # outline/size ratio kept (3 decimals)
    assert seen["n_samples"] == 12 and seen["background"] == "color:#000000"
    # over footage: no flat colour; multi-line captions give every line a slot
    assert font_id.ceiling_strings("첫 줄\n둘째 줄") == ["첫 줄", "둘째 줄", "첫 줄"]
    from shortkit.qa.probes_text import _flat_bg

    assert _flat_bg({"box_region_color": "#000000", "box_region_std": 0.1}, False) == (0, 0, 0)
    assert _flat_bg({"box_region_color": "#58504B", "box_region_std": 25.4}, False) is None
    assert _flat_bg({"box_region_color": "#000000", "box_region_std": 0.1}, True) is None


# ----------------------------------------------------------------------------- kept original level
def _mix_ctx(orig_path: str, out_start: float, out_end: float, src_start: float, src_end: float):
    o = SimpleNamespace(clip_id="s1", path=orig_path, src_start=src_start, src_end=src_end, out_start=out_start,
                        out_end=out_end, gain_db=0.0, stem="raw", reason="대사")
    return SimpleNamespace(resolved=SimpleNamespace(audio=SimpleNamespace(originals=[o])))


def test_kept_level_is_source_loudness_plus_fitted_gain_minus_programme(temp_root):
    """rel = L_src + 20 log10(g) - L_mix with g the median window gain of the kept track."""
    from shortkit.edit.audio import kept_audio_loudness
    from shortkit.qa.probes_audio import kept_levels_obs

    rel = "assets/test/generated/speech_01.wav"
    d = temp_root / "assets/test/generated"
    d.mkdir(parents=True)
    shutil.copy(GEN / "speech_01.wav", d / "speech_01.wav")
    L = kept_audio_loudness([(rel, 0.0, 2.5)])["lufs"]
    ctx = _mix_ctx(rel, 1.0, 3.5, 0.0, 2.5)
    g_db = -3.0
    rows = [{"clip_id": "s1", "t": 1.0 + 0.125 + 0.25 * k, "present": True, "gain": 10 ** (g_db / 20)} for k in range(10)]
    rows.append({"clip_id": "s1", "t": 1.05, "present": True, "gain": 10.0})          # edge window: excluded
    (lv,) = kept_levels_obs(ctx, rows, -14.0)
    assert lv["rel_lu_obs"] == pytest.approx(L + g_db + 14.0, abs=0.01)
    assert lv["n_windows"] == 8                                           # +-0.15 s edges excluded
    (lv2,) = kept_levels_obs(ctx, [], -14.0)
    assert lv2["rel_lu_obs"] is None and lv2["reason"]


def test_kept_level_row_same_within_tolerance_different_beyond(temp_root):
    from shortkit.qa.checks import TOL, RowBuilder, _rows_original

    shutil.copytree(REPO / "presets/joshuamagazine", temp_root / "presets/joshuamagazine",
                    ignore=shutil.ignore_patterns("analysis", "reference", "frames", "*.npy"))
    from shortkit.config import load_preset

    pr = load_preset("joshuamagazine")
    keep = float(pr.peek("audio.original.keep_gain_db"))
    tol = float(pr.peek("audio.loudness.tolerance_lu")) + TOL["orig_level_noise_lu"]
    o = SimpleNamespace(clip_id="s1", path="x.wav", src_start=0.0, src_end=2.0, out_start=1.0, out_end=3.0,
                        gain_db=5.0, stem="raw", reason="대사")
    for obs, want in ((keep + tol - 0.05, "same"), (keep - tol - 0.2, "different"), (None, "unmeasured")):
        ctx = SimpleNamespace(preset=pr, plan={"timeline": [{"id": "s1"}], "sources": []},
                              resolved=SimpleNamespace(audio=SimpleNamespace(originals=[o]), clips=[], mode="test"))
        b = RowBuilder(ctx)
        ap = {"originals": {"windows": [], "expected_kept": [[1.0, 3.0]], "tracks": [],
                            "levels": [{"index": 0, "rel_lu_obs": obs, "src_lufs": -20.0, "fit_gain_db": 0.0,
                                        "n_windows": 5, "mix_lufs": -14.0}]}}
        _rows_original(b, ap)
        row = next(r for r in b.rows if r["row_id"] == "audio.original:level0")
        assert row["status"] == want and row["required"] is True


# ----------------------------------------------------------------------------- BGM loop
def test_bgm_loop_pieces_find_section_start_in_every_repeat_and_catch_a_wrong_jump():
    from shortkit.edit.render import loop_fill
    from shortkit.qa.probes_audio import SR, bgm_loop_pieces, load_mono

    music = load_mono(GEN / "music_bed_a.wav", SR)                 # 60 s synthetic bed
    section, n = 50.0, int(16.0 * SR)                               # 10 s of music for a 16 s episode
    xf = 0.05
    seg = music[int(section * SR):]
    good, starts = loop_fill(seg, n, int(round(xf * SR)))
    loop_t = [s_ / SR for s_ in starts]
    res = bgm_loop_pieces(good, music, SR, 1.0, loop_t, xf)
    assert len(res["pieces"]) == 2 and res["aligned"] is not None
    for pc in res["pieces"]:
        assert pc["found"] and pc["section_start_obs"] == pytest.approx(section, abs=0.02)
    # the aligned regressor explains the output (the gain curves after the loop point stay valid)
    c = float(np.dot(res["aligned"], good) / (np.linalg.norm(res["aligned"]) * np.linalg.norm(good)))
    assert c > 0.99
    # a "loop" that jumps to another part of the song (section + 3 s) is caught on the repeat
    bad = good.copy()
    P = starts[0]
    wrong = music[int((section + 3.0) * SR):]
    bad[P:] = wrong[:n - P]
    r2 = bgm_loop_pieces(bad, music, SR, 1.0, loop_t, xf)
    assert r2["pieces"][0]["section_start_obs"] == pytest.approx(section, abs=0.02)
    assert abs(r2["pieces"][1]["section_start_obs"] - section) > 1.0


def test_bgm_loop_row_statuses(temp_root):
    from shortkit.qa.checks import RowBuilder, _bgm_loop_row

    bgm = SimpleNamespace(section_start_s=50.0)
    ctx = SimpleNamespace(preset=None, resolved=SimpleNamespace(mode="test"))
    planned = {"starts_out_s": [9.95], "xfade_s": 0.05, "segment_s": 10.0}
    for pieces, want in (([{"piece": 0, "section_start_obs": 50.0, "found": True},
                           {"piece": 1, "section_start_obs": 50.01, "found": True}], "same"),
                         ([{"piece": 0, "section_start_obs": 50.0, "found": True},
                           {"piece": 1, "section_start_obs": 53.0, "found": True}], "different"),
                         ([{"piece": 0, "section_start_obs": 50.0, "found": True},
                           {"piece": 1, "section_start_obs": None, "reason": "짧음"}], "unmeasured")):
        b = RowBuilder(ctx)
        b.reference_of = lambda keys: ("못 잼", [], [])
        _bgm_loop_row(b, bgm, {"loop": {"planned": planned, "pieces": pieces}})
        assert b.rows[-1]["status"] == want


# ----------------------------------------------------------------------------- source mapping sampling
def test_mapping_finds_the_moving_moment_when_fixed_positions_are_still(temp_root):
    """A clip whose picture only moves in a short stretch (people holding a pose, test-pipeline-001 s4 after
    trimming): the three fixed sample positions all see still frames -> the source time cannot be told there;
    the second sampling stage looks at more positions and measures it where the picture moves."""
    from shortkit.edit.ir import Clip, Rect
    from shortkit.qa.probes_video import analyze_mapping

    d = temp_root / "assets/test/generated"
    d.mkdir(parents=True)
    still = d / "still.mp4"
    # a frozen test pattern (grey) with a white box moving across it only in 3.4-4.6 s
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "testsrc2=s=320x180:r=30:d=0.04", "-f", "lavfi", "-i", "color=white:s=48x48:r=30:d=6",
                    "-filter_complex", "[0:v]hue=s=0,eq=contrast=0.3,loop=loop=180:size=1:start=0,setpts=N/30/TB[bg];"
                    "[bg][1:v]overlay=x='40+120*(t-3.4)':y=60:enable='between(t,3.4,4.6)'",
                    "-frames:v", "180", "-r", "30", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
                    str(still)], check=True)
    rel = "assets/test/generated/still.mp4"
    c = Clip(id="s1", source_id="v", source_path=rel, src_in=0.0, src_out=6.0, speed=1.0, out_start=0.0, out_end=6.0,
             region=Rect(0.0, 0.0, 320.0, 180.0), fit="cover", src_size=(320, 180))
    ctx = SimpleNamespace(fps=30.0, mp4=still, resolved=SimpleNamespace(clips=[c]))
    (it,) = analyze_mapping(ctx)["clips"]
    st1 = [s_ for s_ in it["samples"] if s_["stage"] == 1]
    assert st1 and not any(s_["decisive"] for s_ in st1)             # the old sampling: unmeasured
    assert it["status"] == "measured", json.dumps(it["samples"])
    good = [s_ for s_ in it["samples"] if s_["decisive"]]
    assert good and all(3.4 <= s_["t"] <= 4.6 for s_ in good) and abs(it["offset_p50"]) <= 1.0 / 30 + 1e-6


# ----------------------------------------------------------------------------- outline over a dark background
def test_outline_thickness_is_not_inflated_by_a_dark_background():
    """7 px black outline over a navy background (#2D2B3B lies inside the 90 colour tolerance of black):
    each pixel goes to the nearer of outline colour and local background (was measured 11 px)."""
    from PIL import Image, ImageDraw, ImageFont

    from shortkit.qa.probes_text import _style_at_rest, color_mask

    path, idx = _font()
    f = ImageFont.truetype(str(path), 76, index=idx)
    im = Image.new("RGB", (300, 160), (45, 43, 59))
    ImageDraw.Draw(im).text((40, 25), "빤히", font=f, fill=(255, 228, 0), stroke_width=7, stroke_fill=(0, 0, 0))
    frame = np.array(im)
    m = color_mask(frame, (255, 228, 0), 80.0)
    ys, xs = np.nonzero(m)
    bbox = [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)]
    cap = SimpleNamespace(color="#FFE400", highlight=[], highlight_color=None, outline_px=7.0, outline_color="#000000",
                          box={}, size_px=76.0)
    out = _style_at_rest(frame, m, bbox, cap)
    assert abs(out["outline_px_obs"] - 7) <= 2, out            # the check allows +-max(2, 35 %)
    assert out["outline_bg_color"] == "#2D2B3B"


# ----------------------------------------------------------------------------- caption text by glyph shape
def test_short_caption_text_by_glyph_shape_tells_one_syllable_apart():
    """When tesseract cannot read a short bold caption, the expected text rendered in the expected face is
    compared glyph by glyph: the right text scores high on every glyph, a one-syllable change does not."""
    from PIL import Image, ImageDraw, ImageFont

    from shortkit.reference import typography as ty

    path, idx = _font()
    f = ImageFont.truetype(str(path), 76, index=idx)
    im = Image.new("RGB", (260, 150), (60, 60, 70))
    ImageDraw.Draw(im).text((30, 20), "빤히", font=f, fill=(255, 228, 0), stroke_width=7, stroke_fill=(0, 0, 0))
    crop = _x264_roundtrip(np.array(im))
    ref = ty.font_ref("Noto Sans CJK KR Black")
    got = {}
    for text in ("빤히", "반히", "빤하"):
        per, _, failed = ty.score_crops([{"crop": crop, "text": text, "size_hint_px": 76.0, "fill_rgb": (255, 228, 0),
                                          "outline_rgb": (0, 0, 0), "id": "c"}], [ref], "given")
        (row,) = per[ref.name]
        got[text] = {g["ch"]: g["iou"] for g in row["glyphs"]}
    assert min(got["빤히"].values()) >= 0.93
    assert got["반히"]["반"] < got["빤히"]["빤"] - 0.1 and got["빤하"]["하"] < got["빤히"]["히"] - 0.05


def test_caption_text_row_uses_shape_evidence_only_when_it_passes():
    from shortkit.qa.checks import _shape_text_evidence

    m = {"font": {"identify": {"status": "measured", "expected_canonical": "Noto Sans CJK KR Black",
                               "ranked": [{"font": "Noto Sans CJK KR Black", "iou": 0.9757, "glyph_pass": True,
                                           "verdict": "similar"}]}}}
    ev = _shape_text_evidence(m)
    assert ev["glyph_pass"] is True and ev["verdict"] == "similar"
    m["font"]["identify"]["ranked"][0]["glyph_pass"] = False
    assert _shape_text_evidence(m)["glyph_pass"] is False
    assert _shape_text_evidence({"font": {"identify": {"status": "unmeasured"}}}) is None


# ----------------------------------------------------------------------------- transitions
def test_continuous_edit_point_is_recognised():
    from shortkit.edit.ir import Clip, Rect
    from shortkit.qa.probes_video import continuous_edit

    R = Rect(0.0, 656.0, 1080.0, 608.0)
    src = "assets/test/generated/video/face-demographics-walking-and-pause.mp4"      # 12 fps
    a = Clip(id="s2", source_id="v", source_path=src, src_in=5.0, src_out=10.0, speed=1.0, out_start=4.8, out_end=9.8,
             region=R, fit="cover", src_size=(768, 432))
    b = Clip(id="s3", source_id="v", source_path=src, src_in=10.0, src_out=13.0, speed=1.0, out_start=9.8, out_end=13.5,
             region=R, fit="cover", src_size=(768, 432))
    assert continuous_edit(a, b) is True                       # test-coverage-001 s2 -> s3
    b.src_in = 10.5
    assert continuous_edit(a, b) is False                      # a jump
    b.src_in, b.speed = 10.0, 0.5
    assert continuous_edit(a, b) is False                      # speed change


def test_crossfade_fit_outside_the_boundary_window_is_rejected():
    """Two nearly identical pictures with a slow drift once fitted a 'crossfade' at t=-49 s lasting 81 s
    (test-coverage-001 s5).  A blend must start and end around the boundary."""
    from shortkit.qa.probes_video import _crossfade_fit

    rng = np.random.default_rng(1)
    A = rng.integers(0, 255, (54, 96)).astype(np.float32)
    D = rng.normal(0, 30, (54, 96)).astype(np.float32)
    n = 40
    thumbs = [np.clip(A + (i / 800.0) * D * 20, 0, 255).astype(np.uint8) for i in range(n)]   # slow global drift
    sc = {"times": np.arange(n) / 30.0, "thumbs": thumbs}
    r = _crossfade_fit(sc, 20 / 30.0, 0.0, 30.0)
    assert r is None or (abs(r["t"] - 20 / 30.0) <= 0.4 and r["dur"] <= 1.0)
    # a real 0.25 s crossfade is still found
    B = rng.integers(0, 255, (54, 96)).astype(np.float32)
    thumbs2 = [A.astype(np.uint8)] * 20 + [np.clip(A + (B - A) * (k + 1) / 8, 0, 255).astype(np.uint8) for k in range(7)] \
        + [B.astype(np.uint8)] * 13
    r2 = _crossfade_fit({"times": np.arange(40) / 30.0, "thumbs": thumbs2}, 20 / 30.0, 0.25, 30.0)
    assert r2 is not None and abs(r2["t"] - 20 / 30.0) <= 0.07 and abs(r2["dur"] - 0.25) <= 0.1


def _slowmo_pair(d: Path):
    """12 fps source with a box sweeping across (synthetic) and a 30 fps 'output' = the source at 0.5x
    (every source frame shown for 5 output frames), plus a 10 % zoomed version of that output."""
    src = d / "src12.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "testsrc2=s=320x180:r=12:d=4", "-f", "lavfi", "-i", "color=white:s=60x60:r=12:d=4",
                    "-filter_complex", "[0:v]hue=s=0[bg];[bg][1:v]overlay=x='20+60*t':y=50",
                    "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", str(src)], check=True)
    out = d / "out30.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", str(src), "-vf",
                    "setpts=2*PTS,fps=30", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12", "-pix_fmt", "yuv420p",
                    str(out)], check=True)
    zoomed = d / "out30_zoom.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", str(out), "-vf",
                    "scale=352:198,crop=320:180:16:9", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "12",
                    "-pix_fmt", "yuv420p", str(zoomed)], check=True)
    return src, out, zoomed


def test_slowed_source_steps_and_geometry_are_checked_against_the_planned_frames(temp_root):
    from shortkit.edit.ir import Clip, Rect
    from shortkit.qa.probes_video import geometry_check, source_step
    from shortkit.util.media import probe

    d = temp_root / "assets/test/generated"
    d.mkdir(parents=True)
    src, out, zoomed = _slowmo_pair(d)
    c = Clip(id="s5", source_id="v", source_path="assets/test/generated/src12.mp4", src_in=0.0, src_out=3.9,
             speed=0.5, out_start=0.0, out_end=7.8, region=Rect(0.0, 0.0, 320.0, 180.0), fit="cover", src_size=(320, 180))
    ctx = SimpleNamespace(fps=30.0, mp4=out, info=probe(out), resolved=SimpleNamespace(clips=[c]))
    # a source-frame step: output frame 25 shows source frame 5 (t=0.4167), frame 24 still source frame 4
    st = source_step(ctx, c, 24 / 30.0, 25 / 30.0)
    assert st["explained"] is True, st
    g = geometry_check(ctx, c)
    assert g["status"] == "measured" and g["confirmed"] is True, g
    ctx_z = SimpleNamespace(fps=30.0, mp4=zoomed, info=probe(zoomed), resolved=SimpleNamespace(clips=[c]))
    gz = geometry_check(ctx_z, c)
    assert gz["confirmed"] is False, gz                         # a real 10 % zoom is not explained away


# ----------------------------------------------------------------------------- SFX level / presence
def test_noise_like_sfx_gain_needs_the_exact_matched_sample():
    """A whoosh-like (noise) SFX: its fitted gain collapses when it is placed one sample off -- which is what
    re-deriving the position from a time rounded to 0.1 ms did (test-pipeline-001 fx1: -15.5 dB measured,
    -12.24 dB in the render stem).  The probe keeps the matched sample."""
    from shortkit.qa.probes_audio import SR, detect_sfx, lowpass, sfx_joint_gain

    rng = np.random.default_rng(5)
    n_t = int(0.45 * SR)
    tmpl = (rng.standard_normal(n_t) * np.hanning(n_t)).astype(np.float32)
    y = np.zeros(int(3.0 * SR), np.float32)
    p = 24303                                   # 1.10218 s -> rounds to 1.1022 s -> sample 24304
    g_true = 10 ** (-12 / 20)
    y[p:p + n_t] += g_true * tmpl
    y += (0.01 * rng.standard_normal(len(y))).astype(np.float32)
    d = detect_sfx(lowpass(y), {"w": {"type": "whoosh", "file": "x", "audio": lowpass(tmpl)}})[0]
    assert d["sample"] == p
    exact = sfx_joint_gain(lowpass(y), d["sample"] / SR, lowpass(tmpl), [])
    rounded = sfx_joint_gain(lowpass(y), round(d["t"], 4), lowpass(tmpl), [])
    assert abs(20 * math.log10(exact) + 12) <= 0.3
    assert 20 * math.log10(abs(rounded)) < -13.0                          # the old path: > 1 dB low


def test_subaudible_residual_match_is_not_counted_as_a_placed_sfx():
    from shortkit.qa.probes_audio import SFX_MIN_CONTRIB_DB, sfx_contrib_db

    rng = np.random.default_rng(2)
    y = rng.standard_normal(20000).astype(np.float32)                    # loud programme (speech stand-in)
    tmpl = np.sin(2 * np.pi * 800 * np.arange(2646) / 22050).astype(np.float32)
    assert sfx_contrib_db(y, 1000, tmpl, 0.02) < SFX_MIN_CONTRIB_DB        # a -35 dB match under it
    assert sfx_contrib_db(y, 1000, tmpl, 0.5) > SFX_MIN_CONTRIB_DB         # a real effect on top of it
