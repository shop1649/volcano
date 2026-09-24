"""Separation wrapper: demucs unavailable here -> SeparationUnavailable; quality check of vocals stems.

SYNTHETIC data only (generated assets / dirty_source test clip with known truth)."""
from __future__ import annotations

import json

import numpy as np
import pytest

import synthref as S
from shortkit.reference import separation as sep

GEN = S.GEN


def test_demucs_path_raises_cleanly_here(tmp_path):
    """torch/demucs are not installed on the build machine (weights host blocked too)."""
    d = sep.get_separator("demucs")
    with pytest.raises(sep.SeparationUnavailable) as ei:
        d.separate(GEN / "speech_01.wav")
    assert ei.value.reason
    assert "torch" in ei.value.reason or "demucs" in ei.value.reason


def test_separate_reference_records_unmeasured(tmp_project):
    vp = tmp_project / "presets/joshuamagazine/reference/videos/vx.wav"
    S._write(vp, S._read(GEN / "speech_01.wav"))
    with pytest.raises(sep.SeparationUnavailable):
        sep.separate_reference("joshuamagazine", "vx")
    rec = json.loads((tmp_project / "presets/joshuamagazine/analysis/vx/audio/separation.json").read_text())
    assert rec["status"] == "unmeasured" and rec["blocker"]
    assert rec["input"] == "presets/joshuamagazine/reference/videos/vx.wav"      # root-relative
    st, status = sep.stems_or_none("joshuamagazine", "vx", separator=sep.get_separator("demucs"))
    assert st is None and status["status"] == "unmeasured"
    # missing reference file -> also unmeasured, never a crash
    with pytest.raises(sep.SeparationUnavailable):
        sep.separate_reference("joshuamagazine", "no_such_video")


def test_stem_cache_kept_when_demucs_fails(tmp_project):
    vp = tmp_project / "presets/joshuamagazine/reference/videos/vy.wav"
    x = S._read(GEN / "speech_02.wav")
    S._write(vp, x)
    orc = S.OracleSeparator()
    orc.add(vp, {"vocals": x, "other": np.zeros_like(x)})
    st = sep.separate_reference("joshuamagazine", "vy", separator=orc)
    assert st.model == "oracle(test-double)" and set(st.files) == {"vocals", "other"}
    with pytest.raises(sep.SeparationUnavailable):
        sep.separate_reference("joshuamagazine", "vy", separator=sep.get_separator("demucs"), force=True)
    rec = json.loads((tmp_project / "presets/joshuamagazine/analysis/vy/audio/separation.json").read_text())
    assert rec["status"] == "measured" and rec["last_failed_attempt"]["blocker"]
    st2, status = sep.stems_or_none("joshuamagazine", "vy", separator=sep.get_separator("demucs"))
    assert st2 is not None and status["model"] == "oracle(test-double)"
    # a changed input file invalidates the cache
    S._write(vp, x * 0.5)
    assert sep.load_cached_stems("joshuamagazine", "vy") is None


def _dirty_truth():
    truth = json.loads((GEN / "dirty_source.truth.json").read_text())
    mix = S._read(GEN / "dirty_source.mp4")
    n = len(mix)
    speech = np.zeros(n, np.float32)
    s = S._read(GEN / "speech_01.wav")
    i0 = int(truth["speech"]["start"] * S.SR)
    m = min(len(s), n - i0)
    speech[i0:i0 + m] = s[:m]
    music = S._read(GEN / "music_bed_b.wav")[:n] * float(truth["music"]["gain"])
    return mix, speech, music


class _ArraySep:
    name = "test-double"
    version = "synthetic"

    def __init__(self, vocals, acc):
        self.v, self.a = vocals, acc

    def separate(self, path, two_stems=False):
        return {"vocals": self.v, "no_vocals": self.a}, S.SR


@pytest.mark.slow
def test_source_separation_quality_check_pass_and_fail(tmp_project):
    """'separate, then quality-check': a clean vocals stem passes, a stem with music leak fails."""
    if not (GEN / "dirty_source.mp4").exists():
        pytest.skip("dirty_source.mp4 missing (python -m shortkit testassets dirty-source)")
    mix, speech, music = _dirty_truth()
    good = sep.separate_vocals_for_source(GEN / "dirty_source.mp4", separator=_ArraySep(speech, music),
                                          out_dir=tmp_project / "warehouse/cache/separation/good")
    assert good["status"] == "measured"
    assert good["quality"]["passed"] is True and good["usable"] is True
    assert good["listening_check"] == "not_done"
    assert good["vocals"].startswith("warehouse/cache/separation/good/")
    leaky = sep.separate_vocals_for_source(GEN / "dirty_source.mp4",
                                           separator=_ArraySep(speech + 0.3 * music, 0.7 * music),
                                           out_dir=tmp_project / "warehouse/cache/separation/leaky")
    q = leaky["quality"]
    assert q["passed"] is False and leaky["usable"] is False
    assert q["music_leak_db"] > sep.QC_MAX_LEAK_DB
    assert q["fail_reasons"]
    # demucs path here -> unmeasured, not usable, never a crash
    un = sep.separate_vocals_for_source(GEN / "dirty_source.mp4",
                                        out_dir=tmp_project / "warehouse/cache/separation/demucs")
    assert un["status"] == "unmeasured" and un["usable"] is False and un["blocker"]


def test_quality_check_unit():
    """Pure-array quality check on SYNTHETIC signals."""
    sr = S.SR
    t = np.arange(4 * sr) / sr
    music = (0.2 * np.sin(2 * np.pi * 330 * t) + 0.1 * np.sin(2 * np.pi * 495 * t)).astype(np.float32)
    speech = np.zeros_like(music)
    speech[sr:2 * sr] = 0.3 * np.sin(2 * np.pi * 150 * t[:sr]) * np.hanning(sr)
    q_ok = sep.quality_check(music + speech, speech, music, sr)
    assert q_ok["status"] == "measured" and q_ok["passed"]
    q_bad = sep.quality_check(music + speech, speech + 0.5 * music, 0.5 * music, sr)
    assert q_bad["passed"] is False
    assert q_bad["residual_music_corr"] > sep.QC_MAX_MUSIC_CORR
