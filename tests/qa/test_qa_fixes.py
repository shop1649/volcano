"""Unit tests for the QA integration fixes (tesseract threads, faces, provenance rows, font verdicts,
BGM is_match).  Media used here is SYNTHETIC or the CC-BY Intel sample clip in assets/test/generated;
anything written goes to a temporary project root."""
from __future__ import annotations

import os
import shutil
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest

from shortkit import config, paths
from shortkit.edit.ir import Bgm, Clip, Rect
from shortkit.qa import checks

REAL_ROOT = paths.project_root()
GEN = REAL_ROOT / "assets/test/generated"


@pytest.fixture()
def temp_root(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    shutil.copy(REAL_ROOT / "shortkit.root", root / "shortkit.root")
    shutil.copytree(REAL_ROOT / "presets" / "joshuamagazine", root / "presets" / "joshuamagazine",
                    ignore=shutil.ignore_patterns("videos", "frames", "stems", "*.wav", "*.mp4", "analysis"))
    monkeypatch.setenv("SHORTKIT_ROOT", str(root))
    return root


def _builder(mode="test", **ctx_kw):
    pr = config.load_preset("joshuamagazine")
    ctx = SimpleNamespace(preset=pr, resolved=SimpleNamespace(mode=mode, format_id="UNCLASSIFIED", clips=[]),
                          episode_id="e", plan={}, options={}, **ctx_kw)
    return checks.RowBuilder(ctx)


# ============================================================================ 3. OMP_THREAD_LIMIT=1 for tesseract
def test_every_tesseract_call_runs_with_one_openmp_thread(monkeypatch):
    """The shell may export another value: QA forces 1 around every tesseract call (and restores)."""
    import pytesseract

    from shortkit.qa import probes_text

    monkeypatch.setenv("OMP_THREAD_LIMIT", "8")
    seen = []
    real_popen = pytesseract.pytesseract.subprocess.Popen

    def spy(*a, **kw):                       # tesseract inherits os.environ (pytesseract passes no env)
        seen.append((kw.get("env") or os.environ).get("OMP_THREAD_LIMIT"))
        return real_popen(*a, **kw)

    monkeypatch.setattr(pytesseract.pytesseract.subprocess, "Popen", spy)
    ok, ver = probes_text.tesseract_ok()
    if not ok:
        pytest.skip(f"tesseract unavailable: {ver}")
    img = np.full((60, 240, 3), 255, np.uint8)
    import cv2

    cv2.putText(img, "TEST 42", (10, 42), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 3)
    words = probes_text.ocr_words(img, psm=7)
    assert seen and set(seen) == {"1"}, seen          # real tesseract processes, all with 1 thread
    assert any("42" in w["text"] for w in words), words
    assert os.environ["OMP_THREAD_LIMIT"] == "8"      # restored for the rest of the process


def test_clean_verify_calls_from_qa_run_with_one_thread(temp_root, monkeypatch):
    from shortkit.qa import probes_video

    monkeypatch.setenv("OMP_THREAD_LIMIT", "4")
    seen = []

    def fake_verify(video, rect, template_png, times, text):
        seen.append(os.environ.get("OMP_THREAD_LIMIT"))
        return {"residual": False, "status": "measured"}

    (temp_root / "f").mkdir()
    ctx = SimpleNamespace(mp4="x.mp4", frames_dir=temp_root / "f")
    out = probes_video._call_verify(fake_verify, ctx, [0, 0, 10, 10], 1.0, np.zeros((10, 10, 3), np.uint8), None)
    assert seen == ["1"] and out["present"] is False
    assert os.environ["OMP_THREAD_LIMIT"] == "4"


# ============================================================================ 1. faces via shortkit.clean.faces
def test_face_detector_uses_clean_faces_numpy_haar_when_models_present():
    from shortkit.clean.faces import find_cascade
    from shortkit.qa.probes_video import _detect_in_rect, face_detector, grab

    if find_cascade("frontal") is None:
        pytest.skip("Haar cascades not fetched here (python -m shortkit clean fetch-models)")
    name, det = face_detector()
    assert name and "shortkit.clean.faces" in name, (name, det)
    vid = GEN / "video/head-pose-face-detection-female-and-male.mp4"
    if not vid.is_file():
        pytest.skip("CC-BY sample clip missing (python -m shortkit testassets fetch-video)")
    fr = grab(vid, 12.0)                                        # two people facing the camera (768x432)
    faces = _detect_in_rect(det, fr, [0, 0, fr.shape[1], fr.shape[0]])
    assert len(faces) >= 1, faces
    # the declared male face region of tests/qa/qa_synth.py (x 456-592, y 80-250) is found
    assert any(f[0] < 592 and f[0] + f[2] > 456 and f[1] < 250 and f[1] + f[3] > 80 for f in faces), faces


def test_face_detector_unmeasured_with_fetch_models_hint_without_models(temp_root, monkeypatch):
    import cv2

    from shortkit.qa.probes_video import FETCH_MODELS_HINT, face_detector

    monkeypatch.delenv("SHORTKIT_FACE_MODEL", raising=False)
    if hasattr(cv2, "data") and hasattr(cv2, "CascadeClassifier"):
        monkeypatch.delattr(cv2, "CascadeClassifier")        # an OpenCV 4 build would ship cascades
    name, reason = face_detector()                           # temp root: no warehouse/cache/models
    assert name is None
    assert "fetch-models" in reason and FETCH_MODELS_HINT in reason


def _clip(cid, out_start, out_end, region=(0, 437, 720, 405)):
    return Clip(id=cid, source_id="s", source_path="x.mp4", src_in=0.0, src_out=out_end - out_start, speed=1.0,
                out_start=out_start, out_end=out_end, region=Rect(*region), fit="cover", src_size=(1920, 1080))


def test_face_samples_at_most_1fps_and_only_while_captions_cover_the_picture():
    from shortkit.qa.probes_video import face_sample_times

    ctx = SimpleNamespace(info=SimpleNamespace(duration=12.0),
                          resolved=SimpleNamespace(clips=[_clip("a", 0, 6), _clip("b", 6, 12)]))
    ov = [{"id": "title", "start": 0.0, "end": 12.0, "bbox": [100, 150, 500, 60]},     # above the picture: never
          {"id": "sit", "start": 1.0, "end": 4.2, "bbox": [100, 600, 500, 60]},       # over the picture
          {"id": "rx", "start": 3.5, "end": 5.0, "bbox": [300, 700, 100, 50]},        # overlaps 'sit'
          {"id": "short", "start": 9.0, "end": 9.3, "bbox": [100, 500, 200, 40]}]     # shorter than 1 s
    for fps in (1.0, 5.0):                                   # asking for more than 1 fps is capped
        ts = face_sample_times(ctx, ov, fps)
        assert all(b - a >= 1.0 - 1e-6 for a, b in zip(ts, ts[1:])), ts
        assert all(1.0 <= t <= 5.0 or 9.0 <= t <= 9.3 for t in ts), ts
        assert any(9.0 <= t <= 9.3 for t in ts)             # every caption interval gets a sample
        assert len(ts) <= 5
    assert face_sample_times(ctx, [ov[0]], 1.0) == []
    # a < 1 s caption squeezed between two samples cannot get its own sample at <= 1 fps:
    # it is reported as not checked (the row then cannot say 'same')
    from shortkit.qa.probes_video import face_sample_plan

    ts, unsampled = face_sample_plan(ctx, ov + [{"id": "blip", "start": 3.6, "end": 4.4, "bbox": [100, 600, 100, 40]}])
    assert all(b - a >= 1.0 - 1e-6 for a, b in zip(ts, ts[1:])), ts
    assert [u["overlay"] for u in unsampled] == ["blip"]


def test_faces_row_unmeasured_when_a_caption_was_not_sampled(temp_root, monkeypatch):
    import shortkit.qa.probes_video as pv

    b = _builder(canvas_w=720, canvas_h=1280)
    fres = {"status": "measured", "detector": "x", "frames": 2, "sample_times": [1.5, 2.5], "covered": [],
            "faces": [{"t": 1.5, "faces": [{"rect": [0, 0, 50, 50]}]}],
            "unsampled_captions": [{"overlay": "blip", "start": 3.6, "end": 4.4}]}
    monkeypatch.setattr(pv, "analyze_faces", lambda ctx, overlays: fres)
    checks.rows_cover_up(b, {"text": {"captions": []}, "video": {"protected": []}})
    r = next(r for r in b.rows if r["row_id"] == "cover_up.faces:detector")
    assert r["status"] == "unmeasured" and "blip" in r["note"]


# ============================================================================ 2. provenance rows
def test_provenance_rows_residual_carried_unmeasured_and_missing_record(temp_root):
    b = _builder(mode="production")
    pv = {"status": "measured", "sources": [
        {"source_id": "v1", "status": "measured", "record": "warehouse/overlays/abc.json", "sha256": "abc",
         "items": [
             {"overlay_id": "ov1", "kind": "watermark", "text": "@x", "clip_id": "s1", "status": "measured",
              "residual": True, "how": "pixels", "max_ncc": 0.9, "ocr_hits": 2, "rect_out": {"x": 1, "y": 2, "w": 3, "h": 4},
              "resolution_out": [1080, 1920], "times": [1.0], "mapping": "clean.verify.source_rect_to_canvas",
              "rect_src": {"x": 1, "y": 2, "w": 3, "h": 4}, "resolution_src": [1920, 1080], "src_range_used": [0, 2],
              "thresholds": {"ncc": 0.5}},
             {"overlay_id": "ov2", "kind": "burned_subtitle", "text": "WAIT", "clip_id": "s1", "status": "measured",
              "residual": False, "how": "removed_by_crop", "times": [2.0], "mapping": "clean.verify.source_rect_to_canvas"},
             {"overlay_id": "ov3", "kind": "logo", "clip_id": "s1", "status": "unmeasured", "residual": None,
              "reason": "없음"}],
         "carried_unmeasured": [
             {"check": "static_graphics", "status": "unmeasured", "reason": "고정 카메라 단일 샷", "impact": "로고가 남을 수 있음"},
             {"check": "corner:top_right", "status": "unmeasured", "unmeasured": ["graphic"], "crop": "c.png"}]},
        {"source_id": "v2", "status": "no_record", "sha256": "def", "reason": "출처 기록 없음 — `python -m shortkit clean detect`"}]}
    checks._rows_provenance(b, {"provenance": pv})
    st = {r["row_id"]: r for r in b.rows}
    assert st["clean.residual:prov:v1:ov1@s1"]["status"] == "different"
    assert st["clean.residual:prov:v1:ov2@s1"]["status"] == "same"
    assert st["clean.residual:prov:v1:ov3@s1"]["status"] == "unmeasured"
    sg = st["clean.residual:prov:v1:static_graphics"]
    assert sg["status"] == "unmeasured" and sg["required"] and "제작 영향" in sg["note"]
    co = st["clean.residual:prov:v1:corner:top_right"]
    assert co["status"] == "unmeasured" and "우상단" in co["item"] and "c.png" in co["note"]
    nr = st["clean.residual:prov:v2"]
    assert nr["status"] == "unmeasured" and nr["required"] and "clean detect" in nr["note"]
    assert all(r["category"] == checks.CAT["logo"] for r in b.rows)


# ============================================================================ 4. font verdict -> row status
def _font_m(verdict, top="Noto Sans CJK KR Black"):
    return {"found": True, "bbox_obs": [0, 0, 300, 50], "lines_found": 1,
            "font": {"status": "measured", "method": "identify", "best": top, "iou_expected": 0.95,
                     "scores": [{"font": top, "iou": 0.95}],
                     "identify": {"status": "measured", "verdict": verdict, "verdict_ko": verdict, "top": top,
                                  "expected_canonical": "Noto Sans CJK KR Black", "top_verdict": verdict,
                                  "iou_expected": 0.95, "margin": 0.05, "reasons": ["r"], "ranked": [],
                                  "ceiling": {"p10": 0.93}, "conditions": {"crf": 18.0}}}}


@pytest.mark.parametrize("verdict,status", [("identical", "same"), ("similar", "unmeasured"),
                                            ("different", "different"), ("unmeasured", "unmeasured")])
def test_font_row_is_same_only_for_identical(temp_root, verdict, status):
    b = _builder()
    cap = SimpleNamespace(id="t1", font_name="Noto Sans CJK KR Black")
    r = checks._font_row(b, cap, _font_m(verdict), "[t1]", "title", {})
    assert r["status"] == status and r["observed"]["verdict"] == verdict


def test_font_row_fallback_never_says_same(temp_root):
    b = _builder()
    cap = SimpleNamespace(id="t1", font_name="Noto Sans CJK KR Black")
    m = {"found": True, "bbox_obs": [0, 0, 300, 50], "lines_found": 1,
         "font": {"status": "measured", "method": "font_iou", "best": "Noto Sans CJK KR Black", "iou_expected": 0.97,
                  "scores": [{"font": "Noto Sans CJK KR Black", "iou": 0.97}, {"font": "NanumGothic", "iou": 0.5}],
                  "identify": {"status": "unmeasured", "reason": "x264 SEI 없음"}}}
    r = checks._font_row(b, cap, m, "[t1]", "title", {})
    assert r["status"] == "unmeasured" and "x264 SEI 없음" in r["note"]
    m["font"]["scores"] = [{"font": "Noto Sans CJK KR Black", "iou": 0.6}, {"font": "NanumGothic", "iou": 0.9}]
    m["font"]["iou_expected"] = 0.6
    assert checks._font_row(b, cap, m, "[t1]", "title", {})["status"] == "different"


def test_size_bucket_and_x264_sei(tmp_path):
    from shortkit.qa.font_id import size_bucket, x264_settings
    from shortkit.util.media import FFMPEG

    assert size_bucket(56) == 56 and size_bucket(27) == 27 and size_bucket(44) == 45 and size_bucket(41) == 40
    out = tmp_path / "t.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "testsrc=s=64x64:d=0.2", "-c:v", "libx264",
                    "-preset", "fast", "-crf", "23", str(out)], check=True)
    s = x264_settings(out)
    assert s["crf"] == 23.0 and s["preset"] == "fast", s


def test_identify_on_output_pipeline_crops_tells_the_weight_apart(temp_root, tmp_path, monkeypatch):
    """Crops rendered by the production libass path at CRF 18: the right font is 'identical', a
    different weight of the same family is NOT (never 'same'); ceilings are cached per key."""
    from shortkit.qa import font_id
    from shortkit.util.media import FFMPEG

    mp4 = tmp_path / "o.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "color=c=gray:s=720x1280:d=0.2", "-c:v", "libx264",
                    "-preset", "veryfast", "-crf", "18", str(mp4)], check=True)
    ctx = SimpleNamespace(mp4=mp4, info=SimpleNamespace(vcodec="h264"), canvas_w=720, canvas_h=1280, fps=30.0,
                          resolved=SimpleNamespace(clips=[]), options={})
    monkeypatch.setattr(font_id, "nearest_fonts", lambda name, k=3: ["Noto Sans CJK KR Bold", "Noto Sans CJK KR Black"])
    white, black = (255, 255, 255), (0, 0, 0)
    cap = SimpleNamespace(id="t", font_name="Noto Sans CJK KR Black", size_px=56.0, outline_px=4.0)
    res = {}
    for truth in ("Noto Sans CJK KR Black", "Noto Sans CJK KR Bold"):
        sams, _ = font_id.libass_samples(ctx, truth, 56.0, white, black, 4.0, None, ["사장님의 한마디"], 18.0,
                                         "veryfast", 30.0, seed=11)
        res[truth] = font_id.identify_caption_font(ctx, cap, sams[0].crop, "사장님의 한마디", white, black, False)
    assert res["Noto Sans CJK KR Black"]["verdict"] == "identical", res["Noto Sans CJK KR Black"]
    assert res["Noto Sans CJK KR Bold"]["verdict"] != "identical", res["Noto Sans CJK KR Bold"]
    assert res["Noto Sans CJK KR Bold"]["top"] == "Noto Sans CJK KR Bold"
    assert res["Noto Sans CJK KR Black"]["conditions"]["crf"] == 18.0
    assert res["Noto Sans CJK KR Black"]["ceiling_cached"] is False and res["Noto Sans CJK KR Bold"]["ceiling_cached"] is True
    files = list((temp_root / font_id.CACHE_DIR).glob("*.json"))
    assert len(files) == 1                                   # one ceiling: (Black, bucket 56, crf 18, style)


# ============================================================================ 5. BGM: is_match semantics
def _bgm():
    return Bgm(path="assets/test/generated/music_bed_a.wav", track_id=None, section_start_s=12.0, tempo_ratio=1.0,
               gain_db=-16, fade_in_s=0, fade_out_s=0.5, envelope=[], silences=[], duck_ranges=[])


def test_bgm_match_names_which_of_the_four_matched(temp_root):
    b = _builder()
    ok = {"status": "measured", "found": True, "tempo_obs": 1.0, "section_start_obs": 12.0,
          "local_match": {"q95": 0.99}, "waveform_ncc": 0.3}
    m = checks._bgm_match(b, _bgm(), ok)
    assert m["status"] == "same" and m["parts_ko"] == "곡=같다, 버전=같다, 속도=같다, 구간=같다"
    wrong_part = dict(ok, section_start_obs=17.0)
    m = checks._bgm_match(b, _bgm(), wrong_part)
    assert m["status"] == "different" and m["parts_ko"] == "곡=같다, 버전=같다, 속도=같다, 구간=다르다"
    sped = dict(ok, tempo_obs=1.1)
    m = checks._bgm_match(b, _bgm(), sped)
    assert m["status"] == "different" and "속도=다르다" in m["parts_ko"] and "구간=같다" in m["parts_ko"]
    # a repeating bed: the runner-up position equals the plan and sounds identical -> same section
    rep = dict(ok, section_start_obs=20.0, runner_up_section={"section_start_s": 12.0, "q95": 0.99, "ncc": 0.3})
    assert checks._bgm_match(b, _bgm(), rep)["status"] == "same"
    absent = {"status": "measured", "found": False}
    m = checks._bgm_match(b, _bgm(), absent)
    assert m["status"] == "different" and m["parts_ko"] == "곡=다르다, 버전=못 잼, 속도=못 잼, 구간=못 잼"
    m = checks._bgm_match(b, _bgm(), {"status": "unmeasured", "reason": "x"})
    assert m["status"] == "unmeasured"
    checks._bgm_match_row(b, _bgm(), wrong_part)
    row = b.rows[-1]
    assert row["row_id"] == "audio.bgm:match" and row["status"] == "different" and "구간=다르다" in row["note"]


def test_provenance_times_avoid_transitions_and_zoom(temp_root):
    from shortkit.edit.ir import Transition, Zoom
    from shortkit.qa import src_time
    from shortkit.qa.probes_video import _prov_times

    a = _clip("a", 0.0, 3.0)
    b = Clip(id="b", source_id="s", source_path="x.mp4", src_in=10.0, src_out=14.0, speed=1.0, out_start=2.7,
             out_end=6.7, region=Rect(0, 437, 720, 405), fit="cover", src_size=(1920, 1080),
             transition_in=Transition("crossfade", 0.3), zoom=Zoom(1.0, 1.3, (960, 540), 2.0, 0.5, "out"))
    c = Clip(id="c", source_id="s", source_path="x.mp4", src_in=20.0, src_out=22.0, speed=1.0, out_start=6.7,
             out_end=8.7, region=Rect(0, 437, 720, 405), fit="cover", src_size=(1920, 1080),
             transition_in=Transition("flash", 0.2, "#FFFFFF"))
    ctx = SimpleNamespace(fps=30.0, resolved=SimpleNamespace(clips=[a, b, c]))
    plain, zoomed = _prov_times(ctx, b, 10.0, 14.0)
    assert plain and zoomed
    for t in plain + zoomed:
        assert 2.7 + 0.3 < t < 6.7 - 0.1, t                        # after the crossfade, before the flash
        assert 10.0 <= src_time(b, t) <= 14.0
    assert all(t < 2.7 + 2.0 for t in plain) and all(t >= 2.7 + 2.0 for t in zoomed)
    # a source range the clip does not use gives nothing
    assert _prov_times(ctx, b, 30.0, 31.0) == ([], [])


def test_visible_template_is_cropped_like_the_canvas_rect(temp_root):
    import cv2

    from shortkit.clean.verify import source_rect_to_canvas
    from shortkit.qa.probes_video import _visible_template

    tpl = temp_root / "warehouse/overlays/x/ov1.png"
    tpl.parent.mkdir(parents=True)
    img = np.zeros((20, 100, 3), np.uint8)
    img[:, 50:] = 255                                     # right half white
    cv2.imwrite(str(tpl), img)
    (temp_root / "f").mkdir()
    ctx = SimpleNamespace(frames_dir=temp_root / "f")
    cl = Clip(id="c", source_id="s", source_path="x.mp4", src_in=0, src_out=5, speed=1.0, out_start=0, out_end=5,
              region=Rect(0, 0, 1080, 608), fit="cover", src_size=(1920, 1080), crop=Rect(50, 0, 1870, 1052))
    o = {"id": "ov1", "rect": {"x": 0, "y": 10, "w": 100, "h": 20}, "template": "warehouse/overlays/x/ov1.png"}
    ro = source_rect_to_canvas(o["rect"], cl)
    rel, cropped = _visible_template(ctx, cl, o, ro, None)
    assert cropped is True
    out = cv2.imread(str(temp_root / rel))
    assert abs(out.shape[1] - 50) <= 1 and out.shape[0] == 20
    assert out.mean() > 250                               # only the visible (white) half is kept
    # fully visible rect: the stored template is used as is
    o2 = dict(o, rect={"x": 200, "y": 100, "w": 100, "h": 20})
    assert _visible_template(ctx, cl, o2, source_rect_to_canvas(o2["rect"], cl), None) == (o["template"], False)


def test_qa_zoom_geometry_matches_renderer_contract_including_recenter():
    """QA's clip_transform must be the renderer's src_to_region (edit.resolve) in canvas px,
    for the fixed-point zoom and for Zoom.recenter (centre moves to the region centre)."""
    import itertools

    from shortkit.edit.ir import Zoom
    from shortkit.edit.resolve import src_to_region
    from shortkit.qa import clip_transform

    for recenter, crop, fit, center in itertools.product((False, True), (None, Rect(120, 66, 1800, 1014)),
                                                         ("cover", "contain"),
                                                         ((1500.0, 300.0), (960.0, 540.0), (100.0, 1000.0))):
        c = Clip(id="z", source_id="s", source_path="x.mp4", src_in=0.0, src_out=4.0, speed=1.0, out_start=2.0,
                 out_end=6.0, region=Rect(0, 437, 1080, 608), fit=fit, src_size=(1920, 1080), crop=crop,
                 zoom=Zoom(1.0, 1.4, center, 0.5, 1.0, "inout", recenter=recenter))
        ex, ey = (crop.x, crop.y) if crop else (0.0, 0.0)
        for t in (2.2, 2.7, 3.0, 3.4, 5.0):
            s, tx, ty = src_to_region(c, t - c.out_start)
            tr = clip_transform(c, t)
            for p in ((0.0, 0.0), (960.0, 540.0), (1700.0, 900.0)):
                want = (c.region.x + s * (p[0] - ex) + tx, c.region.y + s * (p[1] - ey) + ty)
                got = (tr["s"] * p[0] + tr["tx"], tr["s"] * p[1] + tr["ty"])
                assert abs(want[0] - got[0]) < 1e-6 and abs(want[1] - got[1]) < 1e-6, (recenter, crop, fit, center, t, p)
