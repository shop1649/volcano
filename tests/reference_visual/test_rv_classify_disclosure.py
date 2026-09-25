"""Per-format information-disclosure order (user: "반전을 미리 설명하지 말고 레퍼런스의 정보 공개 순서를 따른다").

``ref classify build`` measures, per format, the ordered segment purposes (``beats``) and the reveal time as a
share of the video (``reveal_frac`` {n, p10, p50, p90}) from the label columns ``beats`` / ``reveal_t`` that the
person who WATCHED the video fills in.  ``episode validate`` reads exactly these two fields
(shortkit/edit/validate.py check_reveal).  Nothing is inferred: missing, conflicting or incomparable orders stay
못 잼 with the reason.  All labels / analysis files are SYNTHETIC.
"""
from __future__ import annotations

import csv

import pytest
import yaml

from shortkit.reference import classify as K

from test_rv_classify_aggregate import make_video, write_labels, write_snapshot

P = "presets/joshuamagazine"
BY = "tester(watched, SYNTHETIC)"


def lab(vid, st, beats="", reveal_t="", watched="yes", by=BY):
    return {"video_id": vid, "intro_type": "", "structure_type": st, "beats": beats, "reveal_t": reveal_t, "notes": "",
            "labeled_by": by, "watched": watched}


@pytest.fixture()
def five(proj):
    for i in range(1, 6):
        make_video(proj, f"vid000000{i}", 30 + i, 2.0 + i, dur=30.0)          # analysed duration 30 s
    write_snapshot(proj, [(f"vid000000{i}", 10 * i) for i in range(1, 6)])
    return proj


def _fy(proj):
    return yaml.safe_load((proj / P / "formats.yaml").read_text("utf-8"))


def _row(fy, st):
    return next(r for r in fy["table"] if r["structure_type"] == st)


def test_beats_and_reveal_fraction_per_format(five):
    write_labels(five, [
        lab("vid0000001", "setup-reveal", "hook > context > build > reveal > reaction", "20"),
        lab("vid0000002", "setup-reveal", "hook>build>reveal>reaction", "18"),
        lab("vid0000003", "setup-reveal", "도입 > 상황 > 전개 > 반전 > 반응 > 마무리", "24"),      # Korean aliases
        lab("vid0000004", "list", "hook>build>outro", "none"),
        lab("vid0000005", "list", "hook > build > build > outro", "none")])                # repeats collapse
    out = K.build("joshuamagazine")
    fy = _fy(five)
    assert out["status"] == "measured"
    f1, f2 = _row(fy, "setup-reveal"), _row(fy, "list")
    # the exact fields episode validate reads
    assert f1["beats"] == ["hook", "context", "build", "reveal", "reaction", "outro"]
    fr = f1["reveal_frac"]
    assert fr["n"] == 3 and fr["p50"] == pytest.approx(20 / 30, abs=1e-6)
    assert fr["p10"] == pytest.approx(0.6 + 0.2 * (2 / 3 - 0.6), abs=1e-6)             # numpy linear p10 of .6,.667,.8
    assert f1["reveal_presence"] == {"n": 3, "n_reveal": 3, "n_none": 0, "share": 1.0}
    assert f1["reveal_t_s"]["n"] == 3 and f1["disclosure"]["status"] == "measured"
    ev = {e["video_id"]: e for e in f1["disclosure"]["evidence"]}
    assert ev["vid0000001"]["reveal_t"] == 20.0 and ev["vid0000001"]["duration_source"] == "analysis"
    assert ev["vid0000001"]["labeled_by"] == BY
    assert f2["beats"] == ["hook", "build", "outro"] and f2["reveal_frac"]["n"] == 0
    assert f2["reveal_presence"]["n_none"] == 2
    assert fy["disclosure_order"]["status"] == "measured" and fy["disclosure_order"]["missing"] == []
    assert fy["disclosure_order"]["reveal_frac_overall"]["n"] == 3
    assert "reveal_t" in fy["label_columns"] and "beats" in fy["label_columns"]


def test_missing_member_labels_withhold_the_format_values(five):
    write_labels(five, [
        lab("vid0000001", "setup-reveal", "hook>build>reveal", "20"),
        lab("vid0000002", "setup-reveal", "hook>build>reveal", ""),               # reveal time not filled in
        lab("vid0000003", "setup-reveal"),                                         # disclosure not labelled
        lab("vid0000004", "list", "hook>build>outro", "none"),
        lab("vid0000005", "list", "hook>build>outro", "none")])
    K.build("joshuamagazine")
    fy = _fy(five)
    f1 = _row(fy, "setup-reveal")
    assert f1["beats"] is None and f1["reveal_frac"]["n"] == 0                     # validate -> reveal_order_unmeasured
    d = f1["disclosure"]
    assert d["status"] == "partial" and sorted(d["missing"]) == ["vid0000002", "vid0000003"]
    assert "vid0000002" in d["blocker"] and d["partial_stats"]["reveal_frac"]["n"] == 1
    assert _row(fy, "list")["beats"] == ["hook", "build", "outro"]
    assert fy["disclosure_order"]["status"] == "partial"
    assert fy["status"] == "measured"                    # the format table itself (structure labels) is complete


def test_conflicting_or_incomparable_orders_are_not_guessed(five):
    write_labels(five, [
        lab("vid0000001", "setup-reveal", "hook>build>reveal>reaction", "20"),
        lab("vid0000002", "setup-reveal", "hook>reveal>build>reaction", "10"),      # build/reveal the other way
        lab("vid0000003", "setup-reveal", "hook>build>reveal>reaction", "21"),
        lab("vid0000004", "list", "hook>build>outro", "none"),
        lab("vid0000005", "list", "context>build>outro", "none")])                  # hook vs context never co-occur
    K.build("joshuamagazine")
    fy = _fy(five)
    f1, f2 = _row(fy, "setup-reveal"), _row(fy, "list")
    assert f1["beats"] is None and f1["disclosure"]["order"]["status"] == "conflict"
    assert ["build", "reveal"] in [c["pair"] for c in f1["disclosure"]["order"]["conflicts"]]
    assert f1["reveal_frac"]["n"] == 3                                           # the reveal time is still measured
    assert f2["beats"] is None and f2["disclosure"]["order"]["status"] == "partial_order"
    assert f2["disclosure"]["order"]["unknown_pairs"] == [["hook", "context"]]
    assert fy["disclosure_order"]["status"] == "partial"


def test_invalid_or_unwatched_disclosure_labels_are_rejected(five):
    write_labels(five, [
        lab("vid0000001", "setup-reveal", "hook>climax>reveal", "20"),                 # unknown purpose
        lab("vid0000002", "setup-reveal", "hook>build>reaction", "12"),                # a time but no reveal beat
        lab("vid0000003", "setup-reveal", "hook>build>reveal", "none"),                # reveal beat but 'none'
        lab("vid0000004", "list", "hook>build>outro", "45"),                           # past the 30 s video (and no reveal)
        lab("vid0000005", "list", "hook>build>outro", "none", watched="no")])          # not watched -> not a label
    out = K.build("joshuamagazine")
    fy = _fy(five)
    rej = {r["video_id"]: r["reason"] for r in fy["disclosure_order"]["rejected"]}
    assert set(rej) == {"vid0000001", "vid0000002", "vid0000003", "vid0000004"}
    assert "climax" in rej["vid0000001"] and "reveal" in rej["vid0000002"] and "none" in rej["vid0000003"]
    for r in fy["table"]:
        assert r["beats"] is None and r["reveal_frac"]["n"] == 0
    assert fy["disclosure_order"]["status"] == "unmeasured"
    assert out["status"] == "partial"                        # vid0000005 not watched -> structure unlabeled too


def test_parse_helpers():
    assert K.parse_beats("Hook → build ->reveal / reaction") == (["hook", "build", "reveal", "reaction"], None)
    assert K.parse_beats("")[0] is None
    assert K.parse_reveal_t("none") == ("none", None) and K.parse_reveal_t("없음") == ("none", None)
    assert K.parse_reveal_t("12.5") == (12.5, None) and K.parse_reveal_t("-1")[0] is None
    assert K.parse_reveal_t("") == (None, None)


def test_prepare_upgrades_an_old_label_file(proj):
    """An existing label file written with the old header gains the new empty columns; human labels are kept."""
    make_video(proj, "vid0000001", 30, 2.0)
    old = ["video_id", "intro_type", "structure_type", "notes", "labeled_by", "watched", "extra_col"]
    with (proj / P / "format_labels.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=old)
        w.writeheader()
        w.writerow({"video_id": "vid0000001", "intro_type": "q", "structure_type": "setup-reveal", "notes": "n",
                    "labeled_by": BY, "watched": "yes", "extra_col": "kept"})
    K.prepare("joshuamagazine", ["vid0000001"])
    with (proj / P / "format_labels.csv").open(encoding="utf-8") as f:
        rd = csv.DictReader(f)
        rows = list(rd)
        header = rd.fieldnames
    assert header[: len(K.LABEL_HEADER)] == K.LABEL_HEADER and header[-1] == "extra_col"
    assert rows == [{"video_id": "vid0000001", "intro_type": "q", "structure_type": "setup-reveal", "beats": "",
                     "reveal_t": "", "notes": "n", "labeled_by": BY, "watched": "yes", "extra_col": "kept"}]
    md = (proj / P / "analysis/vid0000001/review/timeline.md").read_text("utf-8")
    assert "beats" in md and "reveal_t" in md and "hook" in md


def test_episode_validate_reads_the_measured_order(five):
    """End to end on the field contract: the formats.yaml written here drives episode validate's reveal-order checks
    (shortkit.edit.validate.check_reveal, read only)."""
    from types import SimpleNamespace as NS

    from shortkit import config
    from shortkit.edit import validate as V

    write_labels(five, [lab(f"vid000000{i}", "setup-reveal", "hook>build>reveal>reaction", str(t))
                        for i, t in ((1, 18), (2, 20), (3, 21), (4, 24), (5, 19))])
    K.build("joshuamagazine")
    fid = _row(_fy(five), "setup-reveal")["format_id"]
    pr = config.load_preset("joshuamagazine")

    def run(purposes, reveal_t, dur=30.0):
        segs, t0, clips = [], 0.0, []
        for i, pu in enumerate(purposes):
            segs.append({"id": f"s{i}", "purpose": pu})
            clips.append(NS(id=f"s{i}", out_start=t0, out_end=t0 + dur / len(purposes)))
            t0 += dur / len(purposes)
        plan = {"mode": "production", "format_id": fid, "timeline": segs, "cover": {}, "title_candidates": [],
                "reveal": {"t": reveal_t, "keywords": ["SYNTHETIC-KW"]}}
        ctx = NS(preset=pr, resolved=NS(captions=[], clips=clips, duration=dur))
        out: list[dict] = []
        V.check_reveal(plan, ctx, out, allow_unmeasured=False)
        return {i["code"] for i in out}

    assert not {"reveal_order", "reveal_time_range", "reveal_order_unmeasured"} & run(
        ["hook", "build", "reveal", "reaction"], 18.5)
    assert "reveal_order" in run(["hook", "reveal", "build", "reaction"], 10.0)
    assert "reveal_time_range" in run(["hook", "build", "reveal", "reaction"], 25.0)   # 0.83 > p90 of the format
