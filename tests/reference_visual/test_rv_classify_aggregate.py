"""Format classification (labels -> formats.yaml) and measurement aggregation by format.

All analysis files here are SYNTHETIC, hand-written in the documented analysis formats
(docs/CONTRACT.md section 11) with known values, so the expected statistics are exact.
"""
from __future__ import annotations

import csv
import json
import subprocess

import pytest
import yaml

from shortkit.reference import aggregate as A
from shortkit.reference import classify as K
from shortkit.util.jsonio import write_json

P = "presets/joshuamagazine"


def _layout_role(size, y, color="#FFFFFF", box=False, motion="pop", dur=0.12, scale=0.85, lines=1):
    return {"n_items": 3, "size_px": size, "ink_h_px": size * 0.645, "anchor": {"x": 270.0, "y": y},
            "align": "center", "color": color, "highlight_color": None, "highlight_presence": "absent",
            "outline_px": 3.0, "outline_color": "#000000", "outline_visibility": "visible", "shadow_px": 0.0,
            "shadow_color": None,
            "box": {"present": "present" if box else "absent", "share": 1.0 if box else 0.0,
                    "color": "#000000" if box else None, "alpha": 0.6 if box else None,
                    "pad_x": 8 if box else None, "pad_y": 10 if box else None},
            "line_spacing": 1.02 if lines > 1 else None, "max_chars_per_line": 12, "max_lines": lines,
            "max_width_px": 400, "motion_in": {"type": motion, "n": 3, "dur_s": dur, "scale_from": scale},
            "motion_out": {"type": "none", "n": 3, "dur_s": 0.0},
            "timing": {"min_dur_s": 1.2, "dur_p50_s": 2.0, "lead_s": None}, "persist": "timed",
            "evidence": [{"t": 1.0, "frame": None, "item": "c01"}]}


def make_video(root, vid, sit_size, cuts_per_10s, dur=30.0, zoom=1.2, texts=("모여 있다", "들어온다")):
    """SYNTHETIC per-video analysis files."""
    d = root / P / "analysis" / vid
    n_cuts = int(round(cuts_per_10s * dur / 10))
    write_json(d / "shots.json", {"video_id": vid, "resolution": [540, 960], "fps": 30, "duration": dur,
                                  "cuts": [{"t": 1.0 + i, "type": "cut", "score": 0.9} for i in range(n_cuts)]
                                  + [{"t": 20.0, "type": "flash", "score": 0.5, "dur": 0.2, "color": "#FFFFFF"}],
                                  "shots": [], "presence": {"cut": "present", "flash": "present",
                                                            "crossfade": "absent"}})
    items = [{"id": f"c{i}", "start": 1.0 + 3 * i, "end": 3.0 + 3 * i, "role": "situation", "text": t,
              "bbox": [100, 680, 300, 30], "motion_in": "pop", "style": {}, "frame": None}
             for i, t in enumerate(texts)]
    items.append({"id": "t", "start": 0.0, "end": dur, "role": "title", "text": "오늘의 사건", "bbox": [100, 130, 300, 40],
                  "motion_in": "unmeasured", "style": {}, "frame": None})
    write_json(d / "captions.json", {"video_id": vid, "resolution": [540, 960], "duration": dur, "items": items})
    write_json(d / "motion.json", {"video_id": vid, "resolution": [540, 960], "duration": dur,
                                   "events": [{"t": 2.0, "end": 2.5, "type": "zoom_in", "value": zoom, "scale_to": zoom,
                                               "dur_s": 0.5}],
                                   "presence": {"zoom": "present", "freeze": "absent", "speed": "unmeasured",
                                                "flash": "present"}})
    write_json(d / "layout.json", {"video_id": vid, "resolution": [540, 960],
                                   "video_region": {"x": 0, "y": 300, "w": 540, "h": 304}, "background": "color",
                                   "background_color": "#101010",
                                   "roles": {"situation": _layout_role(sit_size, 700.0),
                                             "title": {**_layout_role(40, 150.0, motion=None), "persist": "whole_video"}}})


def write_snapshot(root, vids_views):
    write_json(root / P / "reference/latest100.json", {
        "schema": "shortkit.ref_snapshot/1", "status": "ok", "captured_at": "2026-01-01T00:00:00+00:00",
        "method": "SYNTHETIC", "videos": [{"rank": i + 1, "video_id": v, "url": f"https://www.youtube.com/watch?v={v}",
                                           "title": f"SYNTHETIC {v}", "duration": 30.0 + i, "view_count": views,
                                           "published_at": None, "kind": "short"}
                                          for i, (v, views) in enumerate(vids_views)]})


def write_labels(root, rows):
    with (root / P / "format_labels.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=K.LABEL_HEADER)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def lab(vid, st, intro="", by="tester(watched)", watched="yes"):
    return {"video_id": vid, "intro_type": intro, "structure_type": st, "notes": "", "labeled_by": by,
            "watched": watched}


@pytest.fixture()
def fivevids(proj):
    # structure A: v1..v3 (v2 is the medoid: its cut rate sits between v1 and v3)
    make_video(proj, "vid0000001", 30, 2.0)
    make_video(proj, "vid0000002", 34, 3.0)
    make_video(proj, "vid0000003", 38, 4.0)
    # structure B: v4, v5 -> tie on distance, v5 has more views
    make_video(proj, "vid0000004", 40, 8.0, texts=("진짜 왔어요", "왜 그래요"))
    make_video(proj, "vid0000005", 44, 8.0, texts=("진짜 왔어요", "왜 그래요"))
    make_video(proj, "vid0000006", 50, 5.0)
    write_snapshot(proj, [("vid0000001", 10), ("vid0000002", 20), ("vid0000003", 30), ("vid0000004", 100),
                          ("vid0000005", 900), ("vid0000006", 5)])
    return proj


def test_build_formats_from_watched_labels(fivevids):
    root = fivevids
    write_labels(root, [lab("vid0000001", "setup-reveal", "question"), lab("vid0000002", "setup-reveal", "question"),
                        lab("vid0000003", "setup-reveal", "shock"), lab("vid0000004", "list"),
                        lab("vid0000005", "list"),
                        lab("vid0000006", "list", watched="no"),          # not watched -> ignored
                        lab("vid0000007", "list", by="")])                # nobody signed -> rejected
    out = K.build("joshuamagazine")
    fy = yaml.safe_load((root / P / "formats.yaml").read_text("utf-8"))
    assert out["status"] == "partial" and fy["status"] == "partial"      # vid0000006 unlabeled
    assert [t["format_id"] for t in fy["table"]] == ["F1", "F2"]
    f1, f2 = fy["table"]
    assert f1["structure_type"] == "setup-reveal" and f1["n"] == 3 and f1["share"] == 0.6
    assert f1["members"] == ["vid0000001", "vid0000002", "vid0000003"] and f1["videos"] == f1["members"]
    assert {v["intro_type"]: v["n"] for v in f1["intro_variants"]} == {"question": 2, "shock": 1}
    assert f1["representative"]["video_id"] == "vid0000002"
    assert f2["representative"]["video_id"] == "vid0000005" and "동률" in f2["representative"]["reason"]
    assert fy["assignments"]["vid0000004"] == "F2"
    assert "vid0000006" in fy["unlabeled"]
    assert {r["video_id"] for r in fy["rejected_labels"]} == {"vid0000006", "vid0000007"}
    # format ids are stable across rebuilds even when the order by size changes
    write_labels(root, [lab("vid0000001", "setup-reveal"), lab("vid0000004", "list"), lab("vid0000005", "list")])
    K.build("joshuamagazine")
    fy2 = yaml.safe_load((root / P / "formats.yaml").read_text("utf-8"))
    ids = {t["structure_type"]: t["format_id"] for t in fy2["table"]}
    assert ids == {"setup-reveal": "F1", "list": "F2"}


def test_no_labels_keeps_unmeasured(proj):
    out = K.build("joshuamagazine")
    assert out["status"] == "unmeasured" and out["table"] == [] and out["blocker"]
    fy = yaml.safe_load((proj / P / "formats.yaml").read_text("utf-8"))
    assert fy["status"] == "unmeasured"


def test_aggregate_overall_and_by_format(fivevids):
    root = fivevids
    write_labels(root, [lab("vid0000001", "setup-reveal"), lab("vid0000002", "setup-reveal"),
                        lab("vid0000003", "setup-reveal"), lab("vid0000004", "list"), lab("vid0000005", "list")])
    K.build("joshuamagazine")
    A.aggregate("joshuamagazine")
    items = {}
    for f in (root / P / "measurements").glob("visual_*.json"):
        d = json.loads(f.read_text("utf-8"))
        assert d["source_snapshot"] == "2026-01-01T00:00:00+00:00"
        for it in d["items"]:
            items[it["key"]] = it
    sz = items["text.roles.situation.size_px"]
    # 540x960 -> 1080x1920: x2
    assert sz["overall"]["n"] == 6 and sz["resolution"] == [1080, 1920]
    assert sz["by_format"]["F1"]["n"] == 3 and sz["by_format"]["F1"]["p50"] == 68.0
    assert sz["by_format"]["F1"]["value"] == 68.0
    assert sz["by_format"]["F2"]["p50"] == 84.0 and sz["by_format"]["F2"]["p10"] == pytest.approx(80.8)
    assert sz["value"] == sz["overall"]["p50"]
    assert {e["video_id"] for e in sz["evidence"]} <= {f"vid000000{i}" for i in range(1, 7)}
    assert items["text.roles.situation.anchor.y"]["value"] == 1400.0
    assert items["text.roles.situation.motion_in.type"]["value"] == "pop"
    assert items["text.roles.situation.motion_in.type"]["by_format"]["F2"]["value"] == "pop"
    assert items["canvas.video_region.h"]["value"] == 608
    assert items["canvas.background.color"]["value"] == "#101010"
    assert items["motion.zoom.scale_to"]["value"] == 1.2
    assert items["motion.transitions.default"]["value"] == "cut"
    dur = items["structure.duration_s.p50"]
    assert dur["value"] == dur["overall"]["p50"] == 32.5 and dur["overall"]["n"] == 6
    assert items["structure.duration_s.n"]["value"] == 6
    assert items["structure.duration_s.n"]["by_format"]["F2"]["value"] == 2
    assert items["structure.duration_s.p10"]["value"] == dur["overall"]["p10"]
    # nothing observed -> unmeasured with a reason, never a default
    hl = items["text.roles.situation.highlight_color"]
    assert hl["status"] == "unmeasured" and hl["value"] is None and hl["blocker"]
    sp = items["text.roles.speaker.size_px"]
    assert sp["status"] == "unmeasured" and "speaker" in sp["blocker"]
    # tone: F1 texts end in 반말 (-다), F2 in 해요체
    reg = items["text.tone.register"]
    assert reg["by_format"]["F1"]["value"] == "반말_구어체" and reg["by_format"]["F2"]["value"] == "해요체"


def test_aggregate_without_data_is_unmeasured(proj):
    write_json(proj / P / "reference/latest100.json", {"status": "blocked", "blocker": "SYNTHETIC 403",
                                                       "captured_at": "x", "method": "yt-dlp", "videos": []})
    r = A.aggregate("joshuamagazine")
    assert r["videos"] == 0
    for f in (proj / P / "measurements").glob("visual_*.json"):
        for it in json.loads(f.read_text("utf-8"))["items"]:
            assert it["status"] == "unmeasured" and it["value"] is None, it["key"]
            assert "차단" in it["blocker"] or "SYNTHETIC 403" in it["blocker"], it


def test_registry_reads_aggregate_blockers(proj):
    """The provenance registry (shortkit.config) must pick the items up (shared format)."""
    from shortkit import config
    make_video(proj, "vid0000001", 30, 2.0)
    A.aggregate("joshuamagazine")
    reg = config.sync_registry("joshuamagazine", access_logs=[], qa_declarations={})
    e = reg["entries"]["text.roles.situation.size_px"]
    assert e["status"] == "measured" and e["measurement"]["resolution"] == [1080, 1920]
    e2 = reg["entries"]["text.roles.speaker.size_px"]
    assert e2["status"] == "unmeasured" and e2.get("blocker")


def test_ending_classes():
    assert A.ending_class("학생들이 모여 있다")[0] == "반말"
    assert A.ending_class("진짜 왔어요?")[0] == "해요체"
    assert A.ending_class("결국 들킴")[0] == "음슴체"
    assert A.ending_class("감사합니다")[0] == "합쇼체"
    assert A.ending_class("오늘의 사건")[0] == "명사형/기타"


def test_prepare_packets_and_label_template(proj):
    vdir = proj / P / "reference/videos"
    vdir.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x568:d=3:r=10", "-c:v",
                    "libx264", "-preset", "veryfast", str(vdir / "vid0000001.mp4")], check=True)
    make_video(proj, "vid0000001", 30, 2.0)
    r = K.prepare("joshuamagazine", ["vid0000001"])
    assert r["prepared"] == ["vid0000001"]
    rv = proj / P / "analysis/vid0000001/review"
    assert (rv / "contact_sheet.jpg").is_file() and (rv / "timeline.md").is_file()
    md = (rv / "timeline.md").read_text("utf-8")
    assert "실제로 보고" in md and "자막 타임라인" in md and "컷 목록" in md
    rows = list(csv.DictReader((proj / P / "format_labels.csv").open(encoding="utf-8")))
    assert rows == [{"video_id": "vid0000001", "intro_type": "", "structure_type": "", "notes": "", "labeled_by": "",
                     "watched": "no"}]
    # a human label is never touched by a later prepare
    write_labels(proj, [lab("vid0000001", "setup-reveal")])
    K.prepare("joshuamagazine", ["vid0000001"])
    rows = list(csv.DictReader((proj / P / "format_labels.csv").open(encoding="utf-8")))
    assert rows[0]["structure_type"] == "setup-reveal" and len(rows) == 1


def test_identity_mark_is_not_a_title():
    """The reference channel's own name burned into the frame must not become a style sample."""
    from shortkit.reference.textboxes import assign_roles

    def item(text, bbox, start, end, ink_h, color="#FFFFFF", box="absent"):
        return {"text": text, "bbox": bbox, "start": start, "end": end,
                "style": {"ink_h": ink_h, "color": color, "box": {"present": box}}}

    items = [item("조슈아매거진", [800, 40, 200, 60], 0, 30, 50),          # SYNTHETIC channel mark, biggest
             item("오늘의 사건", [300, 200, 480, 50], 0, 30, 40),
             item("학생들이 모여 있다", [300, 1400, 480, 40], 2, 5, 30)]
    assign_roles(items, 30.0, 1920, None, identity_texts=["조슈아매거진", "joshuamagazine"])
    assert [i["role"] for i in items] == ["identity_mark", "title", "situation"]


def test_long_form_uploads_excluded_by_default(fivevids):
    root = fivevids
    snap = json.loads((root / P / "reference/latest100.json").read_text("utf-8"))
    snap["videos"][5]["kind"] = "video"                 # vid0000006 is a long-form upload
    write_json(root / P / "reference/latest100.json", snap)
    r = A.aggregate("joshuamagazine")
    assert r["videos"] == 5
    d = json.loads((root / P / "measurements/visual_text.json").read_text("utf-8"))
    assert d["basis"]["excluded_long_form"] == ["vid0000006"]
    assert A.aggregate("joshuamagazine", include_long=True)["videos"] == 6


def test_track_crop_memory_is_bounded():
    import numpy as np

    from shortkit.reference.textboxes import MAX_CROPS, Sample, Track, _thin_crops
    tr = Track(id=1)
    for i in range(300):
        tr.samples.append(Sample(t=i * 0.2, idx=i, bbox=(0, 0, 10, 10), crop=np.zeros((4, 4, 3), np.uint8),
                                 origin=(0, 0)))
        _thin_crops(tr)
    kept = [s for s in tr.samples if s.crop is not None]
    assert len(kept) <= MAX_CROPS and tr.samples[0].crop is not None and tr.samples[-1].crop is not None


def test_dialogue_by_speech_overlap():
    """Band captions without quote marks become dialogue when they overlap kept speech (audio analysis)."""
    from shortkit.reference.textboxes import assign_roles

    def item(text, start, end):
        return {"text": text, "bbox": [300, 1400, 480, 40], "start": start, "end": end,
                "style": {"ink_h": 30, "color": "#FFFFFF", "box": {"present": "absent"}}}

    items = [item("학생들이 모여 있다", 1.0, 3.0), item("이거 진짜야", 5.0, 6.5), item("그리고 끝났다", 8.0, 9.0)]
    assign_roles(items, 30.0, 1920, speech=[(4.8, 6.6)])
    assert [i["role"] for i in items] == ["situation", "dialogue", "situation"]
    assert "말소리" in items[1]["role_reason"]
