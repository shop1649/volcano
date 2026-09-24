"""Overlay detection on the dirty test source, clean clips (false positives) and a SYNTHETIC clip."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from shortkit.clean.detect import DetectParams, detect_overlays, load_overlays, rect_iou, summary_ko
from shortkit.util.media import ffmpeg, read_frames

pytestmark = pytest.mark.slow


def subtitle_truth_rect(dirty: Path, base_video: Path, t: float = 4.0) -> dict:
    """Ground truth of the burned-in subtitle: pixels that differ from the clean base video."""
    a = read_frames(dirty, [t])[0].astype(int)
    b = read_frames(base_video, [t])[0].astype(int)
    H = a.shape[0]
    d = np.abs(a - b).max(axis=2) > 40
    d[: int(0.75 * H)] = False
    ys, xs = np.nonzero(d)
    return {"x": int(xs.min()), "y": int(ys.min()), "w": int(xs.max() - xs.min() + 1), "h": int(ys.max() - ys.min() + 1)}


def _no_abs_paths(obj) -> bool:
    s = json.dumps(obj)
    return "/home/" not in s and "/tmp/" not in s and "\\\\" not in s


def test_dirty_source_watermark_and_subtitle(dirty_doc, truth, clean_root, dirty):
    ovs = dirty_doc["overlays"]
    wm_truth = {k: truth["watermark"][k] for k in ("x", "y", "w", "h")}
    base = clean_root / "assets/test/generated/video" / truth["base_video"]
    if not base.is_file():
        pytest.skip("base video missing")
    sub_truth = subtitle_truth_rect(dirty, base)
    wm = max(ovs, key=lambda o: rect_iou(o["rect"], wm_truth))
    sub = max(ovs, key=lambda o: rect_iou(o["rect"], sub_truth))
    assert rect_iou(wm["rect"], wm_truth) >= 0.5, (wm, wm_truth)
    assert rect_iou(sub["rect"], sub_truth) >= 0.5, (sub, sub_truth)
    assert wm["kind"] == "watermark" and wm["corner"] == "top_left" and wm["static"]
    assert sub["kind"] == "burned_subtitle"
    assert abs(sub["start"] - truth["subtitle"]["start"]) <= 0.5
    assert abs(sub["end"] - truth["subtitle"]["end"]) <= 0.5
    for o in (wm, sub):
        assert o["resolution"] == [1920, 1080]           # coordinates always carry their resolution
    assert len(ovs) == 2, summary_ko(dirty_doc)          # nothing else is flagged
    # honesty: a static single shot cannot rule out a text-free logo -> unmeasured, not "clear"
    assert dirty_doc["checks"]["static_graphics"]["status"] == "unmeasured"
    assert dirty_doc["corners"]["top_right"]["graphic"] == "unmeasured"
    assert dirty_doc["corners"]["top_left"]["text"] == "present"
    assert dirty_doc["corners"]["top_right"]["text"] == "absent"
    assert dirty_doc["checks"]["static_graphics"]["impact"]


def test_provenance_file_written(dirty_doc, clean_root):
    sha = dirty_doc["source"]["sha256"]
    p = clean_root / "warehouse/overlays" / f"{sha}.json"
    assert p.is_file()
    doc = json.loads(p.read_text())
    assert doc["history"] and doc["history"][-1]["action"] == "detect"
    assert doc["source"]["path"] == "assets/test/generated/dirty_source.mp4"
    for o in doc["overlays"]:
        assert o["template"] and (clean_root / o["template"]).is_file()
    for c in doc["corners"].values():
        assert (clean_root / c["crop"]).is_file()
    assert _no_abs_paths(doc)


def test_redetect_keeps_history(dirty_doc, dirty):
    from shortkit.clean.detect import append_history

    sha = dirty_doc["source"]["sha256"]
    append_history(sha, {"action": "apply", "note": "test removal record"})
    n = len(load_overlays(sha)["history"])
    # a new detection must not drop earlier provenance
    doc2 = detect_overlays(dirty, DetectParams(sample_fps=1.0))
    assert len(doc2["history"]) == n + 1
    assert any(h["action"] == "apply" for h in doc2["history"])


@pytest.mark.parametrize("name", ["classroom.mp4", "people-detection.mp4"])
def test_clean_clip_has_no_detections(clean_root, name):
    src = clean_root / "assets/test/generated/video" / name
    if not src.is_file():
        pytest.skip(f"{name} missing")
    short = clean_root / f"assets/test/generated/clean12_{name}"
    if not short.exists():
        ffmpeg(["-i", src, "-t", "12", "-an", "-c", "copy", short])
    doc = detect_overlays(short)
    assert doc["overlays"] == [], summary_ko(doc)


def test_synthetic_logo_moving_watermark_foreign_subtitle(clean_root):
    """SYNTHETIC clip (see clean_synth.py): text-free logo over two shots, a watermark that jumps
    position, Chinese subtitles Tesseract cannot read."""
    import clean_synth

    cls = clean_root / "assets/test/generated/video/classroom.mp4"
    ppl = clean_root / "assets/test/generated/video/people-detection.mp4"
    if not (cls.is_file() and ppl.is_file()):
        pytest.skip("Intel sample clips missing")
    b = clean_synth.build(clean_root / "assets/test/generated/synth", cls, ppl)
    tr = b["truth"]
    doc = detect_overlays(b["dirty"])
    ovs = doc["overlays"]

    def best(key):
        return max(ovs, key=lambda o: rect_iou(o["rect"], tr[key]))

    logo, ma, mb, zh = best("logo"), best("mover_a"), best("mover_b"), best("zh_sub")
    for o, key in ((logo, "logo"), (ma, "mover_a"), (mb, "mover_b"), (zh, "zh_sub")):
        assert rect_iou(o["rect"], tr[key]) >= 0.5, (key, o, tr[key])
        assert abs(o["start"] - tr[key]["start"]) <= 0.5 and abs(o["end"] - tr[key]["end"]) <= 0.5, (key, o)
    assert logo["kind"] == "logo" and logo["evidence"]["method"] == "cross_shot_persistence"
    assert ma["kind"] == mb["kind"] == "watermark" and ma["moving_group"] and ma["moving_group"] == mb["moving_group"]
    assert zh["kind"] == "burned_subtitle"
    assert len(ovs) == 4, summary_ko(doc)
    # two static-camera shots: cross-shot logos measured, shot-unique ones not -> "partial", never "measured"
    assert doc["checks"]["static_graphics"]["status"] == "partial"


def test_without_ocr_text_check_is_unmeasured(clean_root):
    p = clean_root / "assets/test/generated/synth/synth_overlays.mp4"
    if not p.is_file():
        pytest.skip("synthetic clip not built")
    doc = detect_overlays(p, DetectParams(ocr=False, save=False))
    assert doc["checks"]["text_overlays"]["status"] == "unmeasured"


def test_synthetic_moving_camera_logo(clean_root):
    """SYNTHETIC pan over a still frame with a fixed text-free logo: the moving-camera path."""
    import clean_synth

    cls = clean_root / "assets/test/generated/video/classroom.mp4"
    if not cls.is_file():
        pytest.skip("classroom.mp4 missing")
    b = clean_synth.build_pan(clean_root / "assets/test/generated/synth", cls)
    doc = detect_overlays(b["dirty"])
    assert len(doc["overlays"]) == 1, summary_ko(doc)
    o = doc["overlays"][0]
    assert o["kind"] == "logo" and o["evidence"]["method"] == "static_over_moving_camera"
    assert rect_iou(o["rect"], b["truth"]["logo"]) >= 0.5
    assert doc["shots"][0]["camera"] == "moving" and doc["checks"]["static_graphics"]["status"] == "measured"
    assert doc["corners"]["top_left"]["graphic"] == "present" and doc["corners"]["top_right"]["graphic"] == "absent"
