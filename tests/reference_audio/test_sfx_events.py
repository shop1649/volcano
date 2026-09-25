"""SFX event extraction on SYNTHETIC mixes: timing, events under speech/BGM, mix contrast."""
from __future__ import annotations

import json

import numpy as np
import pytest

import synthref as S
from .conftest import PRESET, no_abs_paths
from shortkit import paths
from shortkit.reference import audio_bgm, separation, sfx_events as E

TOL = 0.05


def _truth_times(tr: dict) -> list[tuple[str, float]]:
    return [(x["name"], x["t"]) for x in tr["sfx"]] + [(f"knock{x['seed']}", x["t"]) for x in tr["onsite"]]


@pytest.mark.slow
@pytest.mark.parametrize("vid", ["synv1", "synv2", "synv3"])
def test_events_found_within_50ms_and_no_false_positives(project_env, vid):
    """Waveform-mode videos (the exact clean file was used): every truth SFX/on-site sound is found
    within 0.05 s, including those under speech and BGM; nothing else is accepted."""
    tr = project_env["truths"][vid]
    r = project_env["results"][vid]["sfx"]
    got = [e for e in r["events"] if e.get("class") != "intentional_silence"]
    truth = _truth_times(tr)
    for name, t in truth:
        assert any(abs(e["t"] - t) <= TOL for e in got), (name, t, [e["t"] for e in got])
    for e in got:
        assert any(abs(e["t"] - t) <= TOL for _, t in truth), ("unexpected event", e["t"])
    under = [x for x in tr["sfx"] if x["under_speech"]]
    assert under, "fixture must contain SFX under speech"
    for x in under:
        ev = min(got, key=lambda e: abs(e["t"] - x["t"]))
        assert ev["under_speech"] and ev["under_bgm"]


@pytest.mark.slow
def test_spectral_mode_recall(project_env):
    """synv4's BGM was re-timed (x1.05): residual by spectral subtraction. All truth events must be
    found within 0.05 s; extra low-level residue events are a documented limitation."""
    tr = project_env["truths"]["synv4"]
    r = project_env["results"]["synv4"]["sfx"]
    got = [e for e in r["events"] if e.get("class") != "intentional_silence"]
    for name, t in _truth_times(tr):
        assert any(abs(e["t"] - t) <= TOL for e in got), (name, t, [e["t"] for e in got])
    assert any("스펙트럼 차감" in x for x in r["limitations"])
    extra = [e for e in got if not any(abs(e["t"] - t) <= TOL for _, t in _truth_times(tr))]
    assert len(extra) <= 2


@pytest.mark.slow
def test_silence_event_and_fingerprint_files(project_env):
    r = project_env["results"]["synv1"]["sfx"]
    sil = [e for e in r["events"] if e.get("class") == "intentional_silence"]
    assert len(sil) == 1 and abs(sil[0]["t"] - 14.8) <= 0.05 and sil[0]["fp"] is None
    for e in r["events"]:
        if e.get("class") == "intentional_silence":
            continue
        assert e["fp"].startswith("presets/joshuamagazine/analysis/synv1/audio/sfx_fp/")
        p = np.load(paths.absp(e["fp"]))
        assert p.shape[0] == E.FP_MELS and p.max() == 0.0
        w = np.load(paths.absp(e["wave"]))
        assert 0 < len(w) <= int(E.WAVE_MAX_S * S.SR) + 1
    assert not no_abs_paths(r, project_env["root"])


class _BadSeparator:
    """TEST DOUBLE: an imperfect separator. Its vocals stem is only 70 % of the speech (the rest
    leaks into the residual) and it hallucinates a click that is NOT in the mix."""
    name = "bad-separator(test-double)"
    version = "synthetic"

    def __init__(self, vocals, other, fake_t):
        v = vocals * 0.7
        click = S.sfx_bank()["click"]
        i0 = int(fake_t * S.SR)
        v = v.copy()
        v[i0:i0 + len(click)] += click * 0.5
        self.v, self.o = v, other

    def separate(self, path, two_stems=False):
        return {"vocals": self.v, "other": self.o}, S.SR


@pytest.mark.slow
def test_separation_artifacts_rejected_by_mix_contrast(project_env, tmp_path):
    spec = S.DEFAULT_SPECS[0]                                          # synv1 content
    d = S.build(spec, project_env["lib"], project_env["bank"], tmp_path)
    vp = project_env["root"] / "presets" / PRESET / "reference" / "videos" / "synbad.wav"
    S._write(vp, d["mix"])
    fake_t = 9.0                                                        # nothing happens at 9.0 in the mix
    sep = _BadSeparator(d["vocals"], d["other"], fake_t)
    st = separation.separate_reference(PRESET, "synbad", separator=sep)
    audio_bgm.analyze_bgm(PRESET, "synbad", stems=st)
    from shortkit.reference.audio_original import analyze_original

    analyze_original(PRESET, "synbad", stems=st)
    r = E.analyze_sfx_events(PRESET, "synbad", stems=st)
    got = [e for e in r["events"] if e.get("class") != "intentional_silence"]
    truth = _truth_times(d["truth"])
    # the hallucinated click is not in the mix -> rejected
    assert not any(abs(e["t"] - fake_t) <= 0.1 for e in got)
    assert any(abs(e["t"] - fake_t) <= 0.1 for e in r["rejected"])
    # speech residue (30 % leak) is not accepted as SFX
    for e in got:
        assert any(abs(e["t"] - t) <= TOL for _, t in truth), ("artifact accepted", e["t"], e["mix_check"])
    assert any("copy_of_vocals" in x["reason"] or "mix_share" in x["reason"] for x in r["rejected"])
    # and the real SFX (incl. under speech) are still found
    for name, t in truth:
        assert any(abs(e["t"] - t) <= TOL for e in got), (name, t)


def test_similarity_invariance_unit():
    """Fingerprint similarity: same sound with gain/EQ/offset stays close; different sounds do not."""
    from scipy.signal import butter, sosfilt

    bank = S.sfx_bank()
    fp = lambda x, on=0.0: E.fingerprint_clip(x, S.SR, on)["patch"]  # noqa: E731
    lo = sosfilt(butter(2, 1500, "low", fs=S.SR, output="sos"), bank["ding"])
    ding_eq = (lo + 0.5 * (bank["ding"] - lo)).astype(np.float32)
    pad = np.concatenate([np.zeros(int(0.2 * S.SR), np.float32), bank["pop"] * 0.2])
    Sm = E.similarity_matrix([fp(bank["ding"]), fp(bank["pop"])],
                             [fp(ding_eq), fp(pad, 0.2), fp(bank["boom"]), fp(bank["whoosh"])])
    assert Sm[0, 0] > 0.9 and Sm[1, 1] > 0.9
    assert Sm[0, 2] < 0.8 and Sm[0, 3] < 0.8 and Sm[1, 2] < 0.8 and Sm[1, 3] < 0.8
    assert E.wave_xcorr(bank["pop"], bank["pop"] * 0.3) > 0.99
    assert E.wave_xcorr(S.knock(1), S.knock(2)) < 0.5


def test_missing_media_is_unmeasured(tmp_project):
    r = E.analyze_sfx_events(PRESET, "nothing_here")
    assert r["status"] == "unmeasured" and r["events"] == []
    saved = json.loads((tmp_project / "presets/joshuamagazine/analysis/nothing_here/audio/sfx_events.json").read_text())
    assert saved["status"] == "unmeasured"


@pytest.mark.slow
def test_realistic_path_aac_mp4_without_stems(project_env, tmp_path):
    """The path that actually runs on this machine: an MP4 with AAC audio, demucs unavailable (no
    stems). BGM still identified exactly; speech from the residual heuristic (low confidence);
    SFX under speech are NOT guessed (reported as unmeasured_under_speech); the others are found."""
    from shortkit.reference.audio_original import analyze_original
    from shortkit.util.media import ffmpeg

    spec = S.DEFAULT_SPECS[0]
    d = S.build(spec, project_env["lib"], project_env["bank"], tmp_path)
    wav = tmp_path / "mix.wav"
    S._write(wav, d["mix"])
    vp = project_env["root"] / "presets" / PRESET / "reference" / "videos" / "synaac.mp4"
    ffmpeg(["-f", "lavfi", "-i", "color=c=black:s=64x64:r=5", "-i", wav, "-shortest", "-c:v", "libx264",
            "-preset", "veryfast", "-c:a", "aac", "-b:a", "128k", "-ar", "44100", vp])
    b = audio_bgm.analyze_bgm(PRESET, "synaac")
    m = b["match"]
    assert (m["track_id"]["value"], m["version"]["value"]) == ("bed_a_sped_up", "sped_up")
    assert abs(m["section_start_s"]["value"] - 13.3) <= 0.02 and m["alignment"]["mode"] == "waveform"
    assert b["separator"]["status"] == "unmeasured"
    o = analyze_original(PRESET, "synaac")
    assert o["speech"]["confidence"] == "low"
    assert abs(o["ducking"]["depth_db"]["p50"] - spec.duck_db) <= 1.5
    r = E.analyze_sfx_events(PRESET, "synaac")
    # speech intervals were NOT measured (no vocals stem): the file is partial, never 'measured' (S4-05)
    assert r["status"] == "partial" and "Demucs" in r["blocker"] and r["unmeasured_coverage"]["intervals"]
    got = [e for e in r["events"] if e.get("class") != "intentional_silence"]
    truth = _truth_times(d["truth"])
    for x in d["truth"]["sfx"]:
        if x["under_speech"]:
            assert not any(abs(e["t"] - x["t"]) <= TOL for e in got)          # not guessed
            assert any(abs(e["t"] - x["t"]) <= TOL and "unmeasured_under_speech" in e["reason"] for e in r["rejected"])
        else:
            assert any(abs(e["t"] - x["t"]) <= TOL for e in got), x
    for e in got:
        assert any(abs(e["t"] - t) <= TOL for _, t in truth), ("unexpected", e["t"])
