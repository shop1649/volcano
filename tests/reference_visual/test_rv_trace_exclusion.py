"""Reference trace -> sourcing exclusion check, end to end on a SYNTHETIC mock reference.

The "reference Short" is mockref_a.mp4 (Intel CC-BY clips placed in a band on a colored
background with libass captions -- see mockref.py; NOT reference-channel data).  `ref trace`
fingerprints it through ``shortkit.sourcing.exclusions.add_reference_footage``; the sourcing check
must then flag the same recording even when it is re-encoded, rescaled and placed differently, and
must not flag a different recording.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from shortkit.reference import trace_sources as T
from shortkit.sourcing import exclusions as X
from shortkit.util.jsonio import write_json

P = "presets/joshuamagazine"
VID = "mockref0001"
VIDEO_DIR = Path(__file__).resolve().parents[2] / "assets" / "test" / "generated" / "video"


def _ff(args: list) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", *[str(a) for a in args]], check=True)


@pytest.fixture()
def traced_mock(proj, mock_truth):
    truth, mp4 = mock_truth
    vdir = proj / P / "reference/videos"
    vdir.mkdir(parents=True)
    shutil.copy(mp4, vdir / f"{VID}.mp4")
    write_json(proj / P / "reference/latest100.json", {
        "status": "ok", "captured_at": "SYNTHETIC", "videos": [{"rank": 1, "video_id": VID, "title": "SYNTHETIC mock",
                                                                 "url": f"https://www.youtube.com/shorts/{VID}"}]})
    # no layout.json: trace detects the footage region itself (same detector as `ref analyze`)
    out = T.trace("joshuamagazine", [VID], do_ocr=False, lens=False)
    return proj, truth, out


def _candidates(tmp: Path, video_dir: Path) -> dict[str, Path]:
    cls = video_dir / "classroom.mp4"
    other = video_dir / "head-pose-face-detection-female-and-male.mp4"     # never used in the mock
    c = {}
    # (a1) the mock's classroom footage (source 20..21.7 s), re-encoded smaller and heavier-compressed,
    #      placed off-centre on a black 9:16 canvas (a repost layout that differs from the reference's)
    c["same_vertical"] = tmp / "same_vertical.mp4"
    _ff(["-ss", "19.6", "-t", "3", "-i", cls, "-filter_complex",
         "color=c=black:s=720x1280:r=25:d=3[bg];[0:v]scale=720:-2,setsar=1[fg];[bg][fg]overlay=0:180:shortest=1,"
         "format=yuv420p", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "32", c["same_vertical"]])
    # (a2) the same footage as a small landscape upload (source 1.0..4.0 s)
    c["same_small"] = tmp / "same_small.mp4"
    _ff(["-ss", "1.0", "-t", "3", "-i", cls, "-vf", "scale=426:240,setsar=1,fps=24", "-an", "-c:v", "libx264",
         "-preset", "veryfast", "-crf", "34", c["same_small"]])
    # (b) a different recording in the same repost layout
    c["different"] = tmp / "different.mp4"
    _ff(["-ss", "5", "-t", "3", "-i", other, "-filter_complex",
         "color=c=black:s=720x1280:r=25:d=3[bg];[0:v]scale=720:-2,setsar=1[fg];[bg][fg]overlay=0:180:shortest=1,"
         "format=yuv420p", "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "32", c["different"]])
    return c


def test_trace_fingerprint_matches_sourcing_check(traced_mock, tmp_path):
    proj, truth, out = traced_mock
    rows = [json.loads(x) for x in (proj / "warehouse/exclusions.jsonl").read_text("utf-8").splitlines() if x.strip()]
    fp = [r for r in rows if r["kind"] == "reference_footage"]
    assert len(fp) == 1
    e = fp[0]
    # region = the footage band, stored with the resolution it refers to
    reg, tr = e["region"], truth["video_region"]
    assert e["region"]["resolution"] == truth["resolution"]
    for k in ("x", "y", "w", "h"):
        assert abs(reg[k] - tr[k]) <= 8, (reg, tr)
    assert "footage region cropped" in e["method"] and e["ref_url"].endswith(VID)
    # identical hashing: the sourcing keyframe hasher reproduces the stored fingerprint exactly
    kf = X.keyframe_hashes(proj / P / f"reference/videos/{VID}.mp4", n=T.N_KEYFRAMES, variants=False,
                           region={k: reg[k] for k in ("x", "y", "w", "h")})
    assert [k["phash"] for k in kf] == e["phash"]
    assert len(e["phash"]) >= 20


@pytest.fixture()
def cands(tmp_path_factory, mock_truth):
    return _candidates(tmp_path_factory.mktemp("cands"), VIDEO_DIR)


def test_same_recording_excluded_different_not(traced_mock, cands):
    proj, _, _ = traced_mock
    entries = X.load()
    assert any(r["kind"] == "reference_footage" for r in entries)
    for name in ("same_vertical", "same_small"):
        r = X.check(video_path=cands[name], entries=entries)
        assert r["excluded"] is True, (name, r)
        assert r["matched_ref_video_id"] == VID and r["matched_keyframes"] >= X.MIN_MATCH_KEYFRAMES
    r = X.check(video_path=cands["different"], entries=entries)
    assert r["excluded"] is False, r
    # URL rule: the reference URL itself is excluded too
    u = X.check(urls=[f"https://youtube.com/shorts/{VID}"], entries=entries)
    assert u["excluded"] is True and u["method"] == "url"
    # a second trace adds no duplicate fingerprint
    T.trace("joshuamagazine", [VID], do_ocr=False, lens=False)
    assert sum(r["kind"] == "reference_footage" for r in X.load()) == 1
