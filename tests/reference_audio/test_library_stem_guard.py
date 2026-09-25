"""The clean-music library must never contain audio separated from a reference video (user rule:
"깨끗한 음악 파일을 사용한다. 레퍼런스에서 분리한 음원을 그대로 제작용 BGM으로 쓰지 마라").

``audio_bgm.load_library`` drops library files that are a copy of a reference stem -- same bytes
(sha256), or the same waveform: the file lies inside one stem at one lag (gain-invariant correlation) AND
follows that stem's own level changes (ducking, fades, SFX leaks) -- and reports them.  The CLEAN source a
stem was separated from is never dropped: it does not follow the stem's ducking and leaks, and a full song
is longer than the stem.  Everything here is SYNTHETIC (generated beds / SFX; the "stem" is built by hand
the way a separator output looks: clean section x gain curve + leaked SFX).
"""
from __future__ import annotations

import json
import shutil

import numpy as np

import synthref as S
from shortkit.reference import audio_bgm as B

from .conftest import PRESET

SEC = 10.0          # the reference used bed_a from 10 s (SYNTHETIC)
DUR = 20.0


def _stem(lib) -> np.ndarray:
    """SYNTHETIC separated music stem of a reference: bed_a[10 s:30 s] at -12 dB, ducked 9 dB over 5..8 s,
    fades, plus two leaked SFX (what a real music stem of a mix looks like)."""
    clean = S._read(lib["bed_a.wav"])
    n = int(DUR * S.SR)
    seg = clean[int(SEC * S.SR):int(SEC * S.SR) + n].copy()
    t = np.arange(n) / S.SR
    env_db = np.where((t >= 5.0) & (t < 8.0), -9.0, 0.0) - 12.0
    env = 10 ** (env_db / 20) * np.clip(t / 0.5, 0, 1) * np.clip((DUR - t) / 0.8, 0, 1)
    x = (seg * env).astype(np.float32)
    bank = S.sfx_bank()
    for name, ts, g in (("pop", 2.0, -8.0), ("whoosh", 12.0, -9.0), ("ding", 16.5, -10.0)):
        s = bank[name]
        i0 = int(ts * S.SR)
        m = min(len(s), n - i0)
        x[i0:i0 + m] += s[:m] * 10 ** (g / 20)
    return x


def _setup(root):
    lib = S.make_library(root)
    stem = _stem(lib)
    sdir = root / "presets" / PRESET / "analysis" / "SYNTHstem01" / "stems"
    S._write(sdir / "other.wav", stem)
    speech = S._read(S.GEN / "speech_01.wav")
    mix = stem.copy()
    mix[int(4 * S.SR):int(4 * S.SR) + len(speech)] += speech[: len(mix) - int(4 * S.SR)]
    S._write(root / "presets" / PRESET / "reference" / "videos" / "SYNTHstem01.wav", mix)
    return lib, stem, sdir / "other.wav"


def _names(tracks):
    return sorted(t.file.name for t in tracks)


def test_clean_sources_are_kept_and_stem_copies_are_dropped(tmp_project):
    lib, stem, stem_file = _setup(tmp_project)
    music = tmp_project / "assets/library/music"
    rejected: list[dict] = []
    assert _names(B.load_library(rejected=rejected)) == ["bed_a.wav", "bed_a_x1.1.wav", "bed_b.wav"]
    assert rejected == []                                     # the clean source of the stem is NOT a stem copy
    # 1) byte copy of the stem
    shutil.copy(stem_file, music / "found_bgm.wav")
    # 2) trimmed (3..15 s), gain -6 dB, resampled to 44.1 kHz 16-bit: same waveform, different bytes
    from scipy.signal import resample_poly

    import soundfile as sf

    part = stem[int(3 * S.SR):int(15 * S.SR)] * 0.5
    sf.write(music / "bgm_edit.wav", resample_poly(part, 2, 1).astype(np.float32), 2 * S.SR, subtype="PCM_16")
    # 3) a short excerpt of the CLEAN file covering the same span (legit short clean file) -> kept
    clean = S._read(lib["bed_a.wav"])
    S._write(music / "bed_a_excerpt.wav", clean[int((SEC + 3) * S.SR):int((SEC + 15) * S.SR)] * 0.7)
    # 4) the reference video's own audio (byte copy)
    shutil.copy(tmp_project / "presets" / PRESET / "reference" / "videos" / "SYNTHstem01.wav", music / "ref_mix.wav")
    rejected = []
    kept = _names(B.load_library(rejected=rejected))
    assert kept == ["bed_a.wav", "bed_a_excerpt.wav", "bed_a_x1.1.wav", "bed_b.wav"], (kept, rejected)
    by = {r["file"].rsplit("/", 1)[-1]: r for r in rejected}
    assert set(by) == {"found_bgm.wav", "bgm_edit.wav", "ref_mix.wav"}
    assert by["found_bgm.wav"]["method"] == "sha256"
    assert by["found_bgm.wav"]["matched"] == f"presets/{PRESET}/analysis/SYNTHstem01/stems/other.wav"
    assert by["ref_mix.wav"]["method"] == "sha256" and by["ref_mix.wav"]["kind"] == "reference_media"
    w = by["bgm_edit.wav"]
    assert w["method"] == "waveform" and w["ncc"] >= B.STEM_COPY_NCC and w["deviating_windows"] <= B.STEM_COPY_MAX_DEV_WIN
    assert abs(w["lag_s"] - 3.0) < 0.01
    assert all(r["reason"] for r in rejected)


def test_stem_hashes_survive_deleting_the_stem_cache(tmp_project):
    """Stems are a git-ignored cache; the separation record keeps their sha256, so a byte copy is still refused."""
    from shortkit.reference import separation as SEP

    lib, stem, stem_file = _setup(tmp_project)
    rec = SEP.separation_record_path(PRESET, "SYNTHstem01")
    rec.parent.mkdir(parents=True, exist_ok=True)
    from shortkit.util.hashing import sha256_file

    rec.write_text(json.dumps({"video_id": "SYNTHstem01", "status": "measured",
                               "stems_sha256": {"other": sha256_file(stem_file)}}), encoding="utf-8")
    shutil.copy(stem_file, tmp_project / "assets/library/music/kept_copy.wav")
    shutil.rmtree(stem_file.parent)
    rejected: list[dict] = []
    assert "kept_copy.wav" not in _names(B.load_library(rejected=rejected))
    assert rejected and rejected[0]["method"] == "sha256" and rejected[0]["kind"] == "separation_record"


def test_separate_reference_records_stem_hashes(tmp_project):
    from shortkit.reference import separation as SEP

    lib, stem, _ = _setup(tmp_project)
    vp = tmp_project / "presets" / PRESET / "reference" / "videos" / "SYNTHstem01.wav"
    oracle = S.OracleSeparator()
    oracle.add(vp, {"vocals": np.zeros_like(stem), "other": stem, "mix": stem})
    SEP.separate_reference(PRESET, "SYNTHstem01", separator=oracle, force=True)
    rec = json.loads(SEP.separation_record_path(PRESET, "SYNTHstem01").read_text("utf-8"))
    assert set(rec["stems_sha256"]) == {"vocals", "other"} and all(len(v) == 64 for v in rec["stems_sha256"].values())


def test_analyze_bgm_reports_refused_library_files(tmp_project):
    lib, stem, stem_file = _setup(tmp_project)
    shutil.copy(stem_file, tmp_project / "assets/library/music/found_bgm.wav")
    r = B.analyze_bgm(PRESET, "SYNTHstem01", write=False)
    refused = r["library"]["refused_reference_audio"]
    assert [x["file"] for x in refused] == ["assets/library/music/found_bgm.wav"]
    assert all(c["file"] != "assets/library/music/found_bgm.wav" for c in r.get("candidates") or [])
    assert r["library"]["n_files"] == 3
