"""Font verdict coverage rules (review findings S1-11, S1-17, S1-03 for fonts).

Videos and captions here are SYNTHETIC (tiny ffmpeg test patterns + hand-written captions.json); only the
sampling / verdict logic is exercised, no font is rendered."""
from __future__ import annotations

import json
from collections import Counter

from shortkit.reference import typography as T
from shortkit.util.jsonio import write_json
from shortkit.util.media import FFMPEG, run

P = "presets/joshuamagazine"


def _ceil(p10=0.80, noise=0.03):
    return {"n": 20, "p10": p10, "p50": 0.85, "p90": 0.9, "noise": {"p90": noise},
            "glyph": {"p10": 0.70, "p50": 0.80, "min": 0.6}}


def _rows(iou, n=3, vid="v1"):
    return [{"id": f"{vid}#{i}.0", "iou": iou, "glyphs": [{"ch": "가", "iou": 0.85}, {"ch": "나", "iou": 0.86}]}
            for i in range(n)]


def test_single_scored_candidate_is_never_identical():
    """S1-17: with no scored alternative the margin is vacuous -> 'similar', not 'identical'."""
    r = T.rank_candidates({"SomeFont": _rows(0.81)}, {"SomeFont": _ceil()})
    assert r["top_verdict"] == "similar" and "다른 후보가 없음" in " ".join(r["ranked"][0]["reasons"])
    # the same score with a scored, clearly worse alternative can be identical
    r2 = T.rank_candidates({"SomeFont": _rows(0.81), "Other": _rows(0.60)},
                           {"SomeFont": _ceil(), "Other": _ceil()})
    assert r2["top_verdict"] == "identical" and r2["top"] == "SomeFont"


def test_identical_requires_crops_from_several_videos():
    """S1-11: an 'identical' resting on one video while 3 videos have the role is downgraded."""
    per = {"SomeFont": _rows(0.81, 3, "aaa"), "Other": _rows(0.60, 3, "aaa")}
    vid_of = {r["id"]: "aaa" for r in per["SomeFont"]}
    idr = T.rank_candidates(per, {"SomeFont": _ceil(), "Other": _ceil()})
    assert idr["top_verdict"] == "identical"
    out = T.require_video_coverage(idr, per, vid_of, videos_available=3)
    assert out["top_verdict"] == "similar" and out["videos_scored"] == 1 and out["videos_required"] == 3
    assert "근거 영상 1편" in out["summary"]
    # when the snapshot has only this one video with the role, one video is all there is
    assert T.require_video_coverage(idr, per, vid_of, videos_available=1)["top_verdict"] == "identical"


def _tiny_video(path, dur=2.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    run([FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
         f"testsrc=size=90x160:rate=10:duration={dur}", "-c:v", "libx264", "-pix_fmt", "yuv420p", str(path)])


def _setup_videos(root, ids, n_lines=15, members=None, fmts=None):
    rows = []
    for v in ids:
        f = root / P / "reference/videos" / f"{v}.mp4"
        _tiny_video(f)
        rows.append(json.dumps({"video_id": v, "path": f"{P}/reference/videos/{v}.mp4", "format": "synthetic"}))
        items = [{"id": f"c{i}", "start": 0.1 * i, "end": 0.1 * i + 0.1, "t_rep": 0.1 * i + 0.05, "role": "title",
                  "text": f"자막{i}", "bbox": [10, 10, 60, 20], "ocr_conf": 90.0, "style": {}} for i in range(n_lines)]
        write_json(root / P / "analysis" / v / "captions.json", {"video_id": v, "resolution": [90, 160],
                                                                  "items": items, "note": "SYNTHETIC"})
    (root / P / "reference/downloads.jsonl").write_text("\n".join(rows) + "\n", encoding="utf-8")
    write_json(root / P / "reference/latest100.json", {
        "schema": "shortkit.ref_snapshot/1", "status": "ok", "captured_at": "2026-01-01T00:00:00+00:00",
        "method": "SYNTHETIC", "videos": [{"rank": i + 1, "video_id": v, "kind": "short"}
                                          for i, v in enumerate(members if members is not None else ids)]})


def test_crops_are_sampled_round_robin_across_videos(tmp_root):
    """S1-11: 3 analysed videos x 15 title lines, 12 crops -> 4 per video, coverage recorded."""
    ids = ["aaa0000000A", "bbb0000000B", "ccc0000000C"]
    _setup_videos(tmp_root, ids)
    out = T.collect_reference_crops("joshuamagazine", ["title"], 12)
    by = Counter(i["video_id"] for i in out["items"]["title"])
    assert by == {v: 4 for v in ids}
    cov = out["coverage"]["title"]
    assert cov["videos_available"] == 3 and cov["videos_sampled"] == 3 and cov["crops_per_video"] == dict(by)


def test_crops_alternate_formats(tmp_root):
    ids = ["aaa0000000A", "bbb0000000B", "ccc0000000C"]
    _setup_videos(tmp_root, ids)
    fmt = {"aaa0000000A": "F1", "bbb0000000B": "F1", "ccc0000000C": "F2"}
    out = T.collect_reference_crops("joshuamagazine", ["title"], 3, fmt_of=fmt)
    assert {i["format_id"] for i in out["items"]["title"]} == {"F1", "F2"}
    assert out["coverage"]["title"]["formats_available"] == {"F1": 2, "F2": 1}


def test_crops_only_from_snapshot_members(tmp_root):
    """S1-03 (fonts): an analysed video outside the snapshot never contributes crops."""
    ids = ["aaa0000000A", "hvold000001"]
    _setup_videos(tmp_root, ids, n_lines=3, members=["aaa0000000A"])
    out = T.collect_reference_crops("joshuamagazine", ["title"], 12)
    assert {i["video_id"] for i in out["items"]["title"]} == {"aaa0000000A"}
    assert out["basis"]["excluded_non_snapshot"] == ["hvold000001"]


def test_every_snapshot_format_gets_its_own_verdict():
    """S1-11: a format with no crops is 'unmeasured' per format, never covered by the channel-wide verdict; a
    format whose crops come from one video (of 3 available) is not 'identical'."""
    its = [{"id": f"{v}#{i}.0", "video_id": v} for v in ("aaa", "bbb", "ccc") for i in range(2)]
    per = {"SomeFont": [{"id": i["id"], "iou": 0.81, "glyphs": [{"ch": "가", "iou": 0.85}]} for i in its],
           "Other": [{"id": i["id"], "iou": 0.60, "glyphs": [{"ch": "가", "iou": 0.6}]} for i in its]}
    fmt_of = {"aaa": "F1", "bbb": "F1", "ccc": "F1", "ddd": "F2", "eee": "F3"}
    cov = {"formats_available": {"F1": 3, "F3": 3}}
    out = T.per_format_verdicts(its, per, {"SomeFont": _ceil(), "Other": _ceil()}, fmt_of, ["F1", "F2", "F3"], cov)
    assert out["F1"]["verdict"] == "identical" and out["F1"]["value"] == "SomeFont" and out["F1"]["videos_scored"] == 3
    assert out["F2"] == {"n": 0, "top": None, "verdict": "unmeasured", "value": None, "summary": out["F2"]["summary"]}
    assert "옮겨 쓰지 않음" in out["F2"]["summary"] and out["F3"]["value"] is None
    its1 = [i for i in its if i["video_id"] == "aaa"]
    one = T.per_format_verdicts(its1, {n: [r for r in rows if r["id"].startswith("aaa")] for n, rows in per.items()},
                                {"SomeFont": _ceil(), "Other": _ceil()}, fmt_of, ["F1"], {"formats_available": {"F1": 3}})
    assert one["F1"]["verdict"] == "similar" and one["F1"]["value"] is None
