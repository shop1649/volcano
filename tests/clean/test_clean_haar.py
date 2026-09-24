"""The numpy Haar evaluator must reproduce OpenCV's CascadeClassifier (installed OpenCV 5 has none)."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pytest

from shortkit.clean.faces import HaarCascade, _nms, find_cascade, group_rectangles, merge_tracks

FIX = Path(__file__).parent / "fixtures" / "haar_native_opencv410.json"
REAL_ROOT = Path(__file__).resolve().parents[2]


def test_group_rectangles_merges_neighbours_and_drops_weak():
    rects = [(100, 100, 50, 50), (102, 101, 50, 50), (99, 98, 52, 52), (101, 100, 49, 49),   # 4 neighbours
             (300, 300, 40, 40)]                                                              # lonely
    out = group_rectangles(rects, 3, 0.2)
    assert len(out) == 1
    x, y, w, h, n = out[0]
    assert n == 4 and abs(x - 100) <= 2 and abs(w - 50) <= 2


def test_opencv_skip_rule_after_stage0_rejection():
    # rows of stage-0 rejections: OpenCV evaluates every other one and skips the window after an odd run
    rej = np.array([[True, True, True, False, False, True, False]])
    ev = HaarCascade._evaluated_after_skips(rej)
    assert ev.tolist() == [[True, False, True, False, True, True, False]]


def test_merge_tracks_and_nms():
    d = [{"x": 10, "y": 10, "w": 20, "h": 20, "neighbors": 5}, {"x": 11, "y": 11, "w": 20, "h": 20, "neighbors": 3}]
    assert len(_nms(d, 0.3)) == 1
    samples = [(0.0, [d[0]]), (1.0, [d[1]]), (2.0, []), (3.0, [{"x": 200, "y": 10, "w": 20, "h": 20, "neighbors": 4}])]
    tr = merge_tracks(samples, 1.0, 4.0)
    assert len(tr) == 2
    a = next(t for t in tr if t["x"] < 100)
    assert a["start"] == 0.0 and a["end"] == 1.5 and a["hits"] == 2
    assert a["x"] < 10 and a["x"] + a["w"] > 31      # padded union


def _frame_gray(video: Path, t: float) -> np.ndarray:
    import cv2

    from shortkit.util.media import run

    raw = run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-ss", str(t), "-i", str(video), "-frames:v", "1",
               "-f", "image2pipe", "-vcodec", "png", "-"]).stdout
    img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    if g.shape[1] > 960:
        g = cv2.resize(g, (960, int(round(g.shape[0] * 960 / g.shape[1]))), interpolation=cv2.INTER_AREA)
    return cv2.equalizeHist(g)


@pytest.mark.slow
def test_numpy_haar_matches_native_opencv_410(cascades_ok):
    if not cascades_ok:
        pytest.skip("cascade XMLs unavailable")
    fx = json.loads(FIX.read_text())
    cas = {"frontal": HaarCascade(find_cascade("frontal")), "profile": HaarCascade(find_cascade("profile"))}
    checked = 0
    for case in fx["cases"]:
        video = REAL_ROOT / case["video"]
        if not video.is_file():
            continue
        g = _frame_gray(video, case["t"])
        if hashlib.sha256(g.tobytes()).hexdigest() != case["gray_sha256"]:
            pytest.skip("decoded frame differs from the one the native results were computed on (ffmpeg build?)")
        for kind, det in cas.items():
            mine = sorted([list(r) for r in det.detect(g, 1.1, 3, (24, 24))])
            assert mine == sorted(case["native"][kind]), (case["video"], kind)
        checked += 1
    if not checked:
        pytest.skip("test videos missing")
