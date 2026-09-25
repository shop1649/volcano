"""Format table from snapshot members only; representative required for 'measured' (review finding S1-04).
All labels / analysis files are SYNTHETIC."""
from __future__ import annotations

import yaml

from shortkit.reference import classify as K

from test_rv_classify_aggregate import lab, make_video, write_labels, write_snapshot

P = "presets/joshuamagazine"


def _snap100(proj):
    ids = [f"s{i:04d}xxxxxx" for i in range(100)]
    write_snapshot(proj, [(v, 1000 + i) for i, v in enumerate(ids)])
    return ids


def test_labels_outside_snapshot_never_make_a_format(proj):
    ids = _snap100(proj)
    for v in ids[:3]:
        make_video(proj, v, 30, 2.0)
    write_labels(proj, [lab(v, "사건-반전") for v in ids] + [lab("s0120xxxxxx", "비교-나열")])
    out = K.build("joshuamagazine")
    fy = yaml.safe_load((proj / P / "formats.yaml").read_text("utf-8"))
    assert [t["structure_type"] for t in fy["table"]] == ["사건-반전"]
    assert fy["table"][0]["share"] == 1.0 and fy["table"][0]["n"] == 100
    assert "s0120xxxxxx" not in fy["assignments"]
    assert [r["video_id"] for r in fy["outside_snapshot_labels"]] == ["s0120xxxxxx"]
    assert fy["basis"]["outside_snapshot_labels"] == 1
    assert out["status"] == "measured" and fy["table"][0]["representative"]["video_id"] in ids[:3]


def test_format_without_representative_is_not_measured(proj):
    """Every member labelled but no analysis files -> representative unmeasured -> status partial."""
    ids = _snap100(proj)
    write_labels(proj, [lab(v, "사건-반전") for v in ids])
    out = K.build("joshuamagazine")
    assert out["status"] == "partial" and out["formats_without_representative"] == ["F1"]
    assert "대표 영상" in out["blocker"]


def test_no_snapshot_means_no_format_table(proj):
    make_video(proj, "x0000000001", 30, 2.0)
    write_labels(proj, [lab("x0000000001", "사건-반전")])
    out = K.build("joshuamagazine")
    assert out["status"] == "unmeasured" and out["table"] == [] and "스냅샷" in out["blocker"]


def test_classify_prepare_defaults_to_the_snapshot(proj):
    import argparse

    from shortkit.reference.cli import register
    ap = argparse.ArgumentParser()
    register(ap)
    ns = ap.parse_args(["classify", "prepare"])
    assert ns.set == "latest100"
    ns = ap.parse_args(["trace"])
    assert ns.set == "reference"
