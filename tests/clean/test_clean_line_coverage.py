"""S6-9 regression: a dirty source built from people-detection.mp4 (the clean-folder test of a different
source) rendered with part of the watermark ('st' + the plate edges) and a subtitle fragment ('R IT') still
visible.  Causes: the detector kept only the OCR-confirmed word fragments of a text line and missed the
semi-transparent plate; nothing checked that the plan's clean block covers the overlay record.

Media: CC-BY Intel sample clip + SYNTHETIC overlays drawn with ffmpeg (same parameters as
``shortkit testassets dirty-source``); the exact overlay pixels come from drawing the same chain on a flat
grey frame."""
from __future__ import annotations

import json

import numpy as np
import pytest

from shortkit.clean import coverage, coverage_report
from shortkit.clean.detect import (ALGO, DetectParams, _find_plate, _grow_line, _join_line_fragments,
                                   detect_overlays)
from shortkit.util.media import ffmpeg, probe

WM = {"x": 16, "y": 14, "w": 190, "h": 44, "text": "@fake_repost"}      # testassets.make_dirty_source
SUB = {"y_from_bottom": 40, "text": "WAIT FOR IT...", "start": 2.0, "end": 6.0}


def _draw_chain() -> str:
    from shortkit.testassets import _any_font

    font = _any_font()
    return (f"drawbox=x={WM['x']}:y={WM['y']}:w={WM['w']}:h={WM['h']}:color=black@0.55:t=fill,"
            f"drawtext=fontfile='{font}':text='{WM['text']}':x={WM['x'] + 10}:y={WM['y'] + 8}:fontsize=26:fontcolor=white,"
            f"drawtext=fontfile='{font}':text='{SUB['text']}':x=(w-text_w)/2:y=h-{SUB['y_from_bottom']}-text_h:"
            f"fontsize=34:fontcolor=white:borderw=3:bordercolor=black:enable='between(t,{SUB['start']},{SUB['end']})'")


@pytest.fixture(scope="module")
def people_dirty(clean_root, env_root):
    base = clean_root / "assets/test/generated/video/people-detection.mp4"
    if not base.is_file():
        pytest.skip("people-detection.mp4 missing (python -m shortkit testassets fetch-video)")
    out = clean_root / "assets/test/generated/dirty_people8.mp4"
    if not out.exists():
        ffmpeg(["-t", "8", "-i", base, "-vf", f"{_draw_chain()},format=yuv420p", "-an", "-c:v", "libx264", "-crf", "20",
                "-preset", "veryfast", out])
    info = probe(out)
    truth_png = clean_root / "assets/test/generated/dirty_people8_truth.png"
    ffmpeg(["-f", "lavfi", "-i", f"color=c=0x808080:s={info.width}x{info.height}:d=4:r=10", "-vf", _draw_chain(),
            "-ss", "3", "-frames:v", "1", truth_png])
    import cv2

    g = cv2.imread(str(truth_png), cv2.IMREAD_GRAYSCALE).astype(int)
    truth = np.abs(g - 128) > 3                      # plate + text + outline at t=3 (both overlays on screen)
    mp = env_root()
    try:
        doc = detect_overlays(out)
    finally:
        mp.__exit__(None, None, None)
    return {"path": out, "doc": doc, "truth": truth, "W": info.width, "H": info.height}


def _covered_by(rects, W, H) -> np.ndarray:
    m = np.zeros((H, W), bool)
    for r in rects:
        x0, y0 = max(0, int(np.floor(r["x"]))), max(0, int(np.floor(r["y"])))
        x1, y1 = min(W, int(np.ceil(r["x"] + r["w"]))), min(H, int(np.ceil(r["y"] + r["h"])))
        m[y0:y1, x0:x1] = True
    return m


@pytest.mark.slow
def test_detected_overlays_cover_every_drawn_pixel(people_dirty):
    """Before the fix: watermark x=24 w=169 (plate 16..206 and 'st' up to x=222 left out) and the subtitle split
    into word fragments with 'R IT' uncovered."""
    doc, truth, W, H = people_dirty["doc"], people_dirty["truth"], people_dirty["W"], people_dirty["H"]
    active = [o["rect"] for o in doc["overlays"] if o["start"] <= 3.0 < o["end"]]
    left = truth & ~_covered_by(active, W, H)
    ys, xs = np.nonzero(left)
    assert left.sum() == 0, f"{left.sum()} drawn px not in any overlay rect, bbox x={xs.min()}..{xs.max()} " \
                            f"y={ys.min()}..{ys.max()}; overlays={[(o['id'], o['rect']) for o in doc['overlays']]}"
    wm = [o for o in doc["overlays"] if o["kind"] == "watermark"]
    assert len(wm) == 1 and "@" in (wm[0]["text"] or "")      # one watermark for the whole handle
    # the whole handle line is one overlay (the 'repost' half is no longer a separate review item)
    assert not [r for r in doc["review"] if "repost" in str(r.get("ocr_text"))]
    assert doc["algo"] == ALGO


@pytest.mark.slow
def test_old_block_is_flagged_and_new_plan_block_covers(people_dirty, clean_root, env_root):
    from shortkit.clean import strategy

    doc = people_dirty["doc"]
    src = people_dirty["path"]
    # the block pasted in the S6-9 episode (from the old detector): too small for the plate/handle, subtitle gap
    old_block = {"crop": None, "delogo": [], "blur": [], "inpaint": [
        {"x": 22, "y": 16, "w": 173, "h": 38, "start": None, "end": None},
        {"x": 209, "y": 360, "w": 156, "h": 38, "start": 2.0, "end": 5.25},
        {"x": 355, "y": 361, "w": 63, "h": 37, "start": 2.0, "end": 6.083},
        {"x": 464, "y": 379, "w": 58, "h": 19, "start": 2.0, "end": 6.083},
        {"x": 243, "y": 360, "w": 111, "h": 39, "start": 5.25, "end": 6.083}]}
    bad = coverage(src, old_block)
    kinds = {e["kind"] for e in bad if e["code"] == "uncovered"}
    assert {"watermark", "burned_subtitle"} <= kinds, bad
    assert all(e["blocking"] for e in bad if e["code"] == "uncovered")
    plan = strategy.plan_clean(doc, region_aspect=1080 / 608, fit="cover", faces={"status": "unmeasured"})
    rep = coverage_report(src, plan["clean"])
    assert [e for e in rep["uncovered"] if e["blocking"]] == [] and rep["status"] == "measured"
    assert len(rep["covered"]) == len(doc["overlays"])
    # pixels: the planned inpaint leaves no drawn pixel of either overlay at t=3
    truth, W, H = people_dirty["truth"], people_dirty["W"], people_dirty["H"]
    rects = [r for r in plan["clean"]["inpaint"] if r["start"] is None or r["start"] <= 3.0 < r["end"]]
    assert (truth & ~_covered_by(rects, W, H)).sum() == 0


# ----------------------------------------------------------------------------- unit tests (no video)
def test_find_plate_semi_transparent_box_with_overflowing_text():
    rng = np.random.default_rng(3)
    Hh, Ww = 90, 300
    yy, xx = np.mgrid[0:Hh, 0:Ww].astype(np.float64)
    bg = np.clip(140 + 70 * np.sin(xx / 9.0) + 10 * np.sin(yy / 15.0), 50, 250)   # scene texture varies along x
    bg[:, :100] *= 0.7                                                    # darker scene part (like the door)
    frames = []
    for k in range(3):
        g = bg + rng.normal(0, 2, bg.shape)
        g[20:64, 30:220] *= 0.45                                          # plate: black@0.55 over the scene
        g[30:52, 45:250] = 255                                            # text ink overflowing to the right
        frames.append(np.clip(g, 0, 255).astype(np.uint8))
    ib = {"x": 45, "y": 30, "w": 205, "h": 22}
    plate = _find_plate(frames, ib, 22.0)
    assert plate is not None
    # never inside the true plate (rows 20..63, cols 30..), at most 2 px outside it
    assert 28 <= plate["x"] <= 30 and 18 <= plate["y"] <= 20 and 64 <= plate["y"] + plate["h"] <= 66
    # no plate: the same text over the plain scene
    plain = [np.clip(bg + 0, 0, 255).astype(np.uint8) for _ in range(3)]
    for g in plain:
        g[30:52, 45:250] = 255
    assert _find_plate(plain, ib, 22.0) is None


def test_grow_line_takes_missed_letters_but_not_scene_lines():
    # stats rows: [x, y, w, h, area]; 0 = background
    stats = np.array([[0, 0, 0, 0, 0],
                      [100, 50, 60, 25, 900],     # tracked word (kept)
                      [170, 50, 20, 25, 300],     # 'IT' missed by the tracker: same line, gap 10
                      [200, 68, 30, 7, 100],      # dots '...' (short, bottom of the line)
                      [240, 55, 300, 2, 600],     # thin scene line in the band -> too thin
                      [120, 0, 12, 140, 800],     # tall door frame crossing the band -> too tall
                      [600, 50, 30, 25, 300]])    # far away word -> gap too large
    keep = np.zeros(len(stats), bool)
    keep[1] = True
    out = _grow_line(stats, keep, (44.0, 81.0), 25.0)
    assert out.tolist() == [False, True, True, True, False, False, False]


def _rec(track, x, w, t0, t1, i0, i1, text="", conf=None, y=100.0, h=25.0):
    return {"track": track, "rect_text": {"x": x, "y": y, "w": w, "h": h}, "line_h": h, "t_first": t0, "t_last": t1,
            "i_first": i0, "i_last": i1, "hits": i1 - i0 + 1, "ocr": {"text": text, "max_word_conf": 90, "n_alnum": len(text)},
            "shots": [0], "fill": 0.4, "t_mid": (t0 + t1) / 2, "band": "bottom",
            **({"confirmed_by": conf, "confidence": 0.9} if conf else {"reason": "unconfirmed"})}


def test_join_line_fragments_absorbs_unconfirmed_words_on_the_same_line():
    prm = DetectParams(ocr=False)
    s_times = [i * 0.5 for i in range(40)]
    wai = _rec(3, 251, 65, 2.0, 5.0, 4, 10, "WAI", conf="ocr")
    fo = _rec(5, 369, 40, 2.0, 6.0, 4, 12, "FO", conf="textlike_timing")
    orr = _rec(4, 386, 52, 2.0, 6.0, 4, 12, "OR")                 # rejected on its own (2 letters)
    later = _rec(9, 400, 60, 10.0, 12.0, 20, 24, "NEXT", conf="ocr")   # another subtitle later: not co-timed
    other_line = _rec(7, 260, 60, 2.0, 6.0, 4, 12, "LINE2", conf="ocr", y=160.0)
    wm = _rec(1, 28, 87, 0.0, 19.5, 0, 39, "@fake", conf="ocr", y=22.0)
    repost = _rec(2, 133, 89, 0.0, 19.5, 0, 39, "repost", conf="ocr", y=27.0, h=20.0)
    review, rejected = [], [orr]
    out = _join_line_fragments([wai, fo, later, other_line, wm, repost], [review, rejected], 0.5, 40, s_times,
                               768, 432, None, prm)
    by_track = {r["track"]: r for r in out}
    line = by_track[3]
    assert line["rect_text"]["x"] == 251 and line["rect_text"]["x"] + line["rect_text"]["w"] == 438
    assert line["t_first"] == 2.0 and line["t_last"] == 6.0
    assert {f["track"] for f in line["fragments"]} == {4, 5} and rejected == []
    assert 9 in by_track and 7 in by_track and 5 not in by_track
    handle = by_track[1]
    assert handle["ocr"]["text"] == "@fake repost" and 2 not in by_track


def _write_record(root, sha, overlays, *, algo=ALGO, review=None, text_status="measured", W=768, H=432, dur=20.0):
    d = root / "warehouse/overlays"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sha}.json").write_text(json.dumps({
        "schema": "shortkit.overlays/1", "algo": algo,
        "source": {"path": None, "sha256": sha, "resolution": [W, H], "duration": dur, "fps": 25.0},
        "overlays": overlays, "review": review or [],
        "checks": {"text_overlays": {"status": text_status}}}))


def _ov(i, kind, x, y, w, h, start=0.0, end=20.0, text=None):
    return {"id": f"ov{i}", "kind": kind, "rect": {"x": x, "y": y, "w": w, "h": h}, "resolution": [768, 432],
            "start": start, "end": end, "text": text}


def test_coverage_geometry_time_crop_and_problems(clean_root):
    sha = "e" * 64
    _write_record(clean_root, sha, [_ov(1, "watermark", 15, 13, 213, 46, text="@fake_repost"),
                                    _ov(2, "burned_subtitle", 245, 361, 275, 37, start=2.0, end=6.083, text="WAIT")])
    wm_ok = {"x": 13, "y": 11, "w": 217, "h": 50, "start": None, "end": None}
    sub_ok = {"x": 243, "y": 359, "w": 279, "h": 41, "start": 2.0, "end": 6.083}
    assert coverage("x.mp4", {"inpaint": [wm_ok, sub_ok]}, sha256=sha) == []
    # a subtitle op that ends one frame (40 ms) early leaves a flash -> uncovered; 1 ms rounding does not
    short = coverage("x.mp4", {"inpaint": [wm_ok, {**sub_ok, "end": 6.043}]}, sha256=sha)
    assert [e["overlay_id"] for e in short] == ["ov2"] and short[0]["uncovered_times"] == [[6.043, 6.083]]
    assert coverage("x.mp4", {"inpaint": [wm_ok, {**sub_ok, "end": 6.082}]}, sha256=sha) == []
    # the plate's left edge (x 15..21) not in the block -> reported with where it is
    left = coverage("x.mp4", {"inpaint": [{**wm_ok, "x": 22, "w": 208}, sub_ok]}, sha256=sha)
    assert left[0]["overlay_id"] == "ov1" and left[0]["uncovered_rect"]["x"] == 16 and left[0]["blocking"]
    # a crop that leaves the watermark outside the picture covers it
    assert coverage("x.mp4", {"crop": {"x": 0, "y": 80, "w": 768, "h": 352}, "inpaint": [sub_ok]}, sha256=sha) == []
    # only the source time the episode uses counts; the visible (fit) area too
    assert coverage("x.mp4", {"inpaint": [wm_ok]}, sha256=sha, used_ranges=[[8.0, 12.0]]) == []
    assert [e["overlay_id"] for e in coverage("x.mp4", {"inpaint": [wm_ok]}, sha256=sha,
                                              used_ranges=[[1.0, 12.0]])] == ["ov2"]
    assert coverage("x.mp4", {"inpaint": [sub_ok]}, sha256=sha, visible={"x": 0, "y": 70, "w": 768, "h": 362}) == []
    # an empty/missing block leaves everything
    assert {e["overlay_id"] for e in coverage("x.mp4", None, sha256=sha)} == {"ov1", "ov2"}


def test_coverage_problems_are_reported_not_passed(clean_root, tmp_path):
    missing = coverage(tmp_path / "nope.mp4", {"inpaint": []})
    assert missing[0]["code"] == "source_missing" and missing[0]["blocking"]
    none = coverage("x.mp4", {"inpaint": []}, sha256="f" * 64)
    assert none[0]["code"] == "no_record" and none[0]["blocking"] and "clean detect" in none[0]["reason"]
    sha = "a1" * 32
    _write_record(clean_root, sha, [], algo="shortkit.clean.detect/1", text_status="unmeasured",
                  review=[{"rect": {"x": 600, "y": 20, "w": 90, "h": 20}, "t_first": 0.0, "t_last": 19.5,
                           "ocr_text": "repost"}])
    codes = {e["code"]: e for e in coverage("x.mp4", {"inpaint": []}, sha256=sha)}
    assert codes["record_stale"]["blocking"]                       # old detector: re-run clean detect
    assert codes["text_unmeasured"]["blocking"] is False           # 못 잼 carried, never "clean"
    assert codes["review_uncovered"]["blocking"] is False
    ok = coverage("x.mp4", {"inpaint": [{"x": 598, "y": 18, "w": 94, "h": 24, "start": None, "end": None}]}, sha256=sha)
    assert "review_uncovered" not in {e["code"] for e in ok}


@pytest.mark.slow
def test_plan_uses_linked_clean_original_and_prints_its_provenance(people_dirty, clean_root):
    """S5-08: `source link-original` -> `clean plan` plans a source replacement and the printed block carries
    path + sha256 + warehouse_id of the replacement (before: path + sha256 only -> provenance_sha_mismatch)."""
    import os
    import subprocess
    import sys
    from pathlib import Path

    from shortkit.sourcing import warehouse
    from shortkit.util.hashing import sha256_file

    base = clean_root / "assets/test/generated/video/people-detection.mp4"
    alt = clean_root / "warehouse/sources/youtube_SYNTHorig02.mp4"
    alt.parent.mkdir(parents=True, exist_ok=True)
    ffmpeg(["-t", "8", "-i", base, "-an", "-c:v", "libx264", "-crf", "20", "-preset", "veryfast", alt])
    dirty_rel = str(people_dirty["path"].relative_to(clean_root))
    cand = clean_root / "warehouse/candidates.jsonl"
    try:
        d = warehouse.build_record({"platform": "tiktok", "platform_id": "7422222222222222222", "uploader": "reup_hub",
                                    "url": "https://www.tiktok.com/@reup_hub/video/7422222222222222222",
                                    "_item_access": {"platform_status": "ok", "note": ""}})
        d.update(download_path=dirty_rel, sha256=sha256_file(people_dirty["path"]))
        c = warehouse.build_record({"platform": "youtube", "platform_id": "SYNTHorig02", "uploader": "cam",
                                    "url": "https://www.youtube.com/shorts/SYNTHorig02",
                                    "_item_access": {"platform_status": "ok", "note": ""}})
        c.update(download_path="warehouse/sources/youtube_SYNTHorig02.mp4", sha256=sha256_file(alt))
        warehouse.save([d, c])
        warehouse.link_original(d["id"], c["id"], by="tester", note="두 파일 모두 봄: 같은 복도 장면")
        root_pkg = Path(__file__).resolve().parents[2]
        env = dict(os.environ, SHORTKIT_ROOT=str(clean_root), PYTHONPATH=str(root_pkg), OMP_THREAD_LIMIT="1")
        r = subprocess.run([sys.executable, "-m", "shortkit", "clean", "plan", "--source", dirty_rel, "--no-faces",
                            "--region-aspect", "1080:608", "--fit", "cover", "--out", "warehouse/overlays/alt_plan.json"],
                           cwd=clean_root, env=env, capture_output=True, text=True, timeout=900)
        assert r.returncode == 0, r.stdout + r.stderr
        out = r.stdout
        assert "원본 교체" in out
        assert "path: warehouse/sources/youtube_SYNTHorig02.mp4" in out
        assert f"sha256: {c['sha256']}" in out and f"warehouse_id: {c['id']}" in out
        assert f"source select {c['id']}" in out                   # replacement must be a selected candidate
        assert "덮개 검사(clean coverage): 통과" in out
        plan = json.loads((clean_root / "warehouse/overlays/alt_plan.json").read_text())
        assert plan["replace_source"]["warehouse_id"] == c["id"]
        # the printed provenance is exactly the warehouse record episode validate compares with
        assert warehouse.get(c["id"])["sha256"] == plan["replace_source"]["sha256"]
    finally:
        cand.unlink(missing_ok=True)


OLD_S69_INPAINT = [{"x": 22, "y": 16, "w": 173, "h": 38, "start": None, "end": None},
                   {"x": 209, "y": 360, "w": 156, "h": 38, "start": 2.0, "end": 5.25},
                   {"x": 355, "y": 361, "w": 63, "h": 37, "start": 2.0, "end": 6.083},
                   {"x": 464, "y": 379, "w": 58, "h": 19, "start": 2.0, "end": 6.083},
                   {"x": 243, "y": 360, "w": 111, "h": 39, "start": 5.25, "end": 6.083}]


@pytest.mark.slow
def test_residual_score_catches_a_partly_removed_overlay(people_dirty, clean_root):
    """Before: the S6-9 output ('st' + plate edge, 'R IT' visible) scored whole-template NCC 0.29/0.38 and OCR
    similarity < 0.6 -> 'no residual'.  Per-tile NCC and OCR pieces of the known text catch it; a complete
    removal still scores clean."""
    from shortkit.clean import strategy
    from shortkit.clean.apply import inpaint_video
    from shortkit.clean.verify import overlay_times, residual_score

    doc, src = people_dirty["doc"], people_dirty["path"]
    part = clean_root / "warehouse/cache/clean/people8_old_block.mp4"
    full = clean_root / "warehouse/cache/clean/people8_new_block.mp4"
    part.parent.mkdir(parents=True, exist_ok=True)
    inpaint_video(src, OLD_S69_INPAINT, part)
    plan = strategy.plan_clean(doc, region_aspect=1080 / 608, fit="cover", faces={"status": "unmeasured"})
    inpaint_video(src, plan["clean"]["inpaint"], full)
    for o in doc["overlays"]:
        if o["kind"] == "watermark" or (o.get("text") and "WAIT" in o["text"]):
            ts = [t for t in overlay_times(o, 3, 8.0) if t < 8.0]
            left = residual_score(part, o["rect"], o["template"], ts, o["text"])
            assert left["residual"] is True, (o["id"], left["max_ncc"], left["max_tile_ncc"], left["per_time"])
            assert left["max_tile_ncc"] >= 0.6
            gone = residual_score(full, o["rect"], o["template"], ts, o["text"])
            assert gone["residual"] is False, (o["id"], gone["max_ncc"], gone["max_tile_ncc"], gone["per_time"])


def test_partial_text_hits_rules():
    from shortkit.clean.verify import partial_text_hits

    assert partial_text_hits([["RIT", 86]], "WAIT FOR IT...") == ["RIT"]
    assert partial_text_hits([["st", 96]], "@fake_repost") == ["st"]
    assert partial_text_hits([["st", 70]], "@fake_repost") == []           # 2 letters need conf >= 85
    assert partial_text_hits([["xyz", 95], ["ab", 99]], "@fake_repost") == []
    assert partial_text_hits([["IT", 99]], "IT") == []                        # known text too short to split


def test_cli_coverage_reads_plan_and_uses_timeline_ranges(clean_root, capsys):
    import yaml

    from shortkit.cli import main

    sha = "c7" * 32
    _write_record(clean_root, sha, [_ov(1, "watermark", 15, 13, 213, 46, text="@fake_repost"),
                                    _ov(2, "burned_subtitle", 245, 361, 275, 37, start=2.0, end=6.083, text="WAIT")])
    ep = clean_root / "episodes/_pytest_cov"
    ep.mkdir(parents=True, exist_ok=True)
    wm = {"x": 13, "y": 11, "w": 217, "h": 50, "start": None, "end": None}
    plan = {"sources": [{"id": "v", "path": "assets/test/generated/none.mp4", "sha256": sha,
                         "clean": {"crop": None, "delogo": [], "blur": [], "inpaint": [wm]}}],
            "timeline": [{"id": "s1", "source": "v", "src_in": 8.0, "src_out": 12.0}]}
    (ep / "plan.yaml").write_text(yaml.safe_dump(plan))
    assert main(["clean", "coverage", "--plan", "episodes/_pytest_cov/plan.yaml"]) == 0      # subtitle not used
    assert "통과" in capsys.readouterr().out
    assert main(["clean", "coverage", "--plan", "episodes/_pytest_cov/plan.yaml", "--all-time"]) == 1
    out = capsys.readouterr().out
    assert "ov2" in out and "덮지 못한 오버레이 1개" in out
    plan["timeline"][0]["src_in"] = 1.0
    (ep / "plan.yaml").write_text(yaml.safe_dump(plan))
    assert main(["clean", "coverage", "--plan", "episodes/_pytest_cov/plan.yaml"]) == 1


@pytest.mark.slow
def test_clean_detect_marks_the_warehouse_record_as_repost(people_dirty, clean_root, capsys):
    """S5-04 via clean detect: the '@fake_repost' watermark read by detection != the record's uploader."""
    from shortkit.clean.cli import _refresh_warehouse_record
    from shortkit.sourcing import warehouse
    from shortkit.util.hashing import sha256_file

    cand = clean_root / "warehouse/candidates.jsonl"
    try:
        rec = warehouse.build_record({"platform": "tiktok", "platform_id": "7433333333333333333",
                                      "uploader": "viralclips_daily", "published_at": "2026-09-22T00:00:00+00:00",
                                      "url": "https://www.tiktok.com/@viralclips_daily/video/7433333333333333333",
                                      "_item_access": {"platform_status": "ok", "note": ""}})
        rec["sha256"] = sha256_file(people_dirty["path"])
        warehouse.save([rec])
        _refresh_warehouse_record(rec["sha256"])
        assert "재업로드로 기록" in capsys.readouterr().out
        got = warehouse.get(rec["id"])
        assert got["reposter"] == "viralclips_daily" and got["original_author"].lower().startswith("@fake")
        assert got["scores"]["recency_label"] == "unknown"
    finally:
        cand.unlink(missing_ok=True)
