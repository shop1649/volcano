"""QA side of the E2 remainders (SYNTHETIC signals and catalogs in a temp project root).

1. audio.bgm:clean_file uses the ONE reference-audio rule of validate and the library: a clean song of which a
   reference stem is an excerpt is 'same'; a stem copy is 'different'.
2. audio.sfx.count:catalog* with a 'partial' catalog: the count rows are real verdicts, a required 못 잼 row keeps
   production blocked; detections whose type is unknown widen each count into a range (never a false 'same').
5. structure.cuts rows use the reference analyzer's definition (edit.validate.cut_structure).
"""
from __future__ import annotations

from collections import Counter
from types import SimpleNamespace

import numpy as np

from shortkit.qa import checks

from .test_qa_review_d import P, _builder, temp_root  # noqa: F401  (fixture re-exported)

SR = 22050


def _song_and_stem():
    import sys
    from pathlib import Path

    d = str(Path(__file__).resolve().parents[1] / "edit")
    if d not in sys.path:
        sys.path.insert(0, d)
    from e2_synth import stem_of, synth_song  # SYNTHETIC generators shared with the validate test

    song = synth_song(40.0)
    return song, stem_of(song)


def test_bgm_clean_file_row_shares_the_library_rule(temp_root):
    from shortkit.util.media import write_wav

    song, stem = _song_and_stem()
    lib = temp_root / "assets/library/music"
    lib.mkdir(parents=True, exist_ok=True)
    write_wav(lib / "song.wav", song, SR)
    write_wav(lib / "stem_copy.wav", (0.5 * stem[int(3 * SR):int(15 * SR)]).astype(np.float32), SR)
    sdir = temp_root / P / "analysis" / "SYNTHstemq1" / "stems"
    sdir.mkdir(parents=True, exist_ok=True)
    write_wav(sdir / "other.wav", stem, SR)
    b = _builder(mode="production")
    checks._bgm_clean_file_row(b, SimpleNamespace(path="assets/library/music/song.wav"), True)
    r = b.rows[-1]
    assert r["status"] == "same" and r["observed"]["stem_match"] is None, r            # the old rule: NCC 0.987 -> different
    assert r["observed"]["reference_stems_compared"] == 1
    b = _builder(mode="production")
    checks._bgm_clean_file_row(b, SimpleNamespace(path="assets/library/music/stem_copy.wav"), True)
    r = b.rows[-1]
    assert r["status"] == "different" and r["observed"]["stem_match"]["method"] == "waveform"


def _catalog(root, counts: list[int], status="partial", per_video_count="measured", emotion="unmeasured"):
    from shortkit.util.jsonio import write_json
    from shortkit.util.stats import pstats

    vids = [f"v{i + 1}" for i in range(len(counts))]
    cols = {"prev_caption_role": "measured", "screen_event": "measured", "emotion": emotion}
    write_json(root / P / "sfx_catalog.json", {
        "schema": "shortkit.sfx_catalog/1", "preset_id": "joshuamagazine-v1", "status": status,
        "blocker": "감정 라벨 없음 — SYNTHETIC", "basis": {"videos": vids},
        "column_status": {"per_video_count": per_video_count, **cols},
        "types": [{"type_id": "pop", "class": "edit_sfx", "columns": {"per_video_count": "measured", **cols},
                   "per_video_count": {"overall": pstats(counts), "videos": dict(zip(vids, counts))}}]})


def _rows(b):
    return {r["row_id"]: r for r in b.rows}


def test_partial_catalog_counts_are_judged_and_production_stays_blocked(temp_root):
    _catalog(temp_root, [2, 3, 3, 3, 5])                                   # allowed [2, 5]; observed {2, 3, 5}
    b = _builder(mode="production")
    checks._rows_sfx_catalog(b, {"bgm": {}}, Counter({"pop": 1}))
    rows = _rows(b)
    assert rows["audio.sfx.count:catalog:pop"]["status"] == "different"     # the count rule ran
    cat_row = rows["audio.sfx.count:catalog"]
    assert cat_row["status"] == "unmeasured" and cat_row["required"] is True
    assert "emotion" in cat_row["observed"]["unmeasured_columns"]
    b = _builder(mode="production")
    checks._rows_sfx_catalog(b, {"bgm": {}}, Counter({"pop": 3}))
    assert _rows(b)["audio.sfx.count:catalog:pop"]["status"] == "same"
    # lower-bound counts are not a measured basis: no count verdicts at all
    _catalog(temp_root, [2, 3, 3, 3, 5], per_video_count="lower_bound")
    b = _builder(mode="production")
    checks._rows_sfx_catalog(b, {"bgm": {}}, Counter({"pop": 1}))
    rows = _rows(b)
    assert list(rows) == ["audio.sfx.count:catalog"] and rows["audio.sfx.count:catalog"]["status"] == "unmeasured"
    # a fully measured catalog has no completeness row
    _catalog(temp_root, [2, 3, 3, 3, 5], status="measured", emotion="measured")
    b = _builder(mode="production")
    checks._rows_sfx_catalog(b, {"bgm": {}}, Counter({"pop": 3}))
    assert "audio.sfx.count:catalog" not in _rows(b)


def test_unclassified_detections_turn_counts_into_ranges(temp_root):
    _catalog(temp_root, [1, 1, 1, 1, 1], status="measured", emotion="measured")   # allowed exactly 1
    b = _builder(mode="test")
    checks._rows_sfx_catalog(b, {"bgm": {}}, Counter({"pop": 1, None: 1}))        # true count 1 or 2
    rows = _rows(b)
    assert rows["audio.sfx.count:catalog:pop"]["status"] == "unmeasured"        # not a false 'same'
    assert "1~2" in rows["audio.sfx.count:catalog:pop"]["note"]
    _catalog(temp_root, [2, 3, 3, 3, 5], status="measured", emotion="measured")
    b = _builder(mode="test")
    checks._rows_sfx_catalog(b, {"bgm": {}}, Counter({"pop": 2, None: 1}))        # 2 or 3: both allowed
    assert _rows(b)["audio.sfx.count:catalog:pop"]["status"] == "same"


def test_cut_rows_use_the_reference_definition(temp_root):
    from shortkit.edit.validate import cut_structure

    b = _builder()
    probes = {"video": {"transitions": {"boundaries": [{"observed": {"type": "cut", "t": 2.0}},
                                                       {"observed": {"type": "none", "t": None}},
                                                       {"observed": {"type": "crossfade", "t": 6.5}}],
                                        "unexpected": [{"t": 8.0, "type": "cut"}]}}}
    checks._rows_cut_structure(b, probes)
    rows = _rows(b)
    want = cut_structure([2.0, 6.5, 8.0], 10.0)
    assert rows["structure.cuts:rate_ref"]["observed"]["cuts_per_10s"] == want["cuts_per_10s"] == 3.0
    assert rows["structure.cuts:shot_len_ref"]["observed"]["shot_len_median_s"] == want["shot_len_median_s"] == 2.0
    # wave 5: the rows also read p50 (the output's position against the reference median is reported)
    assert checks.declarations()["structure.cuts"] == ["structure.cuts_per_10s.p10", "structure.cuts_per_10s.p50",
                                                       "structure.cuts_per_10s.p90", "structure.shot_len_s.p10",
                                                       "structure.shot_len_s.p50", "structure.shot_len_s.p90"]
