"""BGM identification / alignment on SYNTHETIC reference-like mixes with known ground truth."""
from __future__ import annotations

import json

import pytest

import synthref as S
from .conftest import PRESET, no_abs_paths
from shortkit.reference import audio_bgm as B

VERSION_OF = {"bed_a.wav": ("bed_a_original", "bed_a", "original"),
              "bed_a_x1.1.wav": ("bed_a_sped_up", "bed_a", "sped_up"),
              "bed_b.wav": ("bed_b_original", "bed_b", "original")}


def _obs(r: dict) -> dict:
    m = r["match"]
    d = {k: m[k]["value"] for k in ("track_id", "version", "tempo_ratio", "section_start_s")}
    d["song"] = m["song_id"]["value"]
    return d


@pytest.mark.slow
@pytest.mark.parametrize("vid", ["synv1", "synv2", "synv3", "synv4"])
def test_bgm_identified_track_version_tempo_section(project_env, vid):
    tr = project_env["truths"][vid]["bgm"]
    r = project_env["results"][vid]["bgm"]
    assert r["status"] == "measured" and r["presence"] == "present"
    track, song, version = VERSION_OF[tr["file"]]
    exp = {"track_id": track, "song": song, "version": version, "tempo_ratio": tr["tempo_ratio"],
           "section_start_s": tr["section_start_s"]}
    res = B.is_match(exp, _obs(r))
    assert res["match"], (res, _obs(r))
    m = r["match"]
    assert m["section_start_s"]["status"] == "measured"            # not ambiguous
    assert abs(m["gain_db"]["value"] - tr["gain_db"]) <= 0.5
    assert abs(m["tempo_ratio"]["value"] - tr["tempo_ratio"]) <= 0.005
    assert abs(m["section_start_s"]["value"] - tr["section_start_s"]) <= 0.05
    if tr["tempo_ratio"] == 1.0:
        assert m["alignment"]["mode"] == "waveform"
    else:
        assert m["alignment"]["mode"] == "spectral"                   # the reference re-timed the file
    assert not no_abs_paths(r, project_env["root"])


@pytest.mark.slow
def test_sped_up_version_is_not_reported_as_original(project_env):
    """synv1 uses the sped-up VERSION file: the match must name that version at tempo 1.0,
    not 'original x1.1' (and the original is recorded only as an alternative candidate)."""
    r = project_env["results"]["synv1"]["bgm"]
    m = r["match"]
    assert m["version"]["value"] == "sped_up" and abs(m["tempo_ratio"]["value"] - 1.0) < 1e-3
    assert abs(m["tempo_vs_original"]["value"] - 1.1) < 1e-3
    orig = [c for c in r["candidates"] if c["version"] == "original" and c["song"] == "bed_a"]
    assert orig and not orig[0]["selected"] and abs(orig[0]["tempo_ratio"] - 1.1) < 0.005
    exp_orig = {"song": "bed_a", "version": "original", "tempo_ratio": 1.1, "section_start_s": 13.3 * 1.1}
    assert B.is_match(exp_orig, _obs(r))["match"] is False       # different version => not a match


@pytest.mark.slow
def test_fades_and_cut(project_env):
    m = project_env["results"]["synv1"]["bgm"]["match"]
    tr = project_env["truths"]["synv1"]
    assert abs(m["fade_in_s"]["value"] - tr["bgm"]["fade_in_s"]) <= 0.1
    assert abs(m["fade_out_s"]["value"] - tr["bgm"]["fade_out_s"]) <= 0.1
    cuts = m["cuts"]["value"]
    assert len(cuts) == 1
    assert abs(cuts[0]["start"] - tr["silence"]["start"]) <= 0.05 and abs(cuts[0]["end"] - tr["silence"]["end"]) <= 0.05


def test_different_part_of_same_song_is_not_a_match():
    exp = {"song": "bed_a", "version": "original", "tempo_ratio": 1.0, "section_start_s": 10.0}
    same = B.is_match(exp, dict(exp, section_start_s=10.1))
    assert same["match"] and same["status"] == "same"
    other_part = B.is_match(exp, dict(exp, section_start_s=18.0))   # 8 s later: same chords, other part
    assert other_part["match"] is False and other_part["status"] == "different"
    assert other_part["checks"]["section_start_s"] is False
    assert B.is_match(exp, dict(exp, tempo_ratio=1.05))["match"] is False
    assert B.is_match(exp, dict(exp, version="sped_up"))["match"] is False
    assert B.is_match(exp, dict(exp, song="bed_b"))["match"] is False
    assert B.is_match(dict(exp, track_id="bed_a_original"), dict(exp, track_id="bed_a_sped_up"))["match"] is False
    assert B.is_match({"title": "A", "version": "original", "tempo_ratio": 1.0, "section_start_s": 3.0},
                      {"title": "A", "version": "original", "tempo_ratio": 1.004, "section_start_s": 3.2})["match"]
    un = B.is_match(exp, dict(exp, version=None))
    assert un["match"] is False and un["status"] == "unmeasured"


@pytest.mark.slow
def test_alignment_separates_repeated_sections(project_env):
    """bed_a repeats its chord loop every 8 s; the alignment must still pick the actually used
    part (waveform coherence), and a reference made from another part must not match."""
    clean = S._read(project_env["lib"]["bed_a.wav"])
    sp = S._read(S.GEN / "speech_03.wav")
    for off in (10.0, 31.7):
        ref = clean[int(off * S.SR):int((off + 15) * S.SR)] * 0.25
        ref[3 * S.SR:3 * S.SR + len(sp)] += sp * 0.5
        al = B.align(ref, clean, S.SR)
        assert al.mode == "waveform" and not al.ambiguous
        assert abs(al.offset_s - off) < 0.02 and abs(al.tempo_ratio - 1.0) < 1e-3
        repeats = [c for c in al.section_candidates if abs(c["offset_s"] - al.offset_s) > 1.0]
        assert repeats and max(c["coherence"] for c in repeats) < al.coherence - 0.2
    exp = {"song": "bed_a", "version": "original", "tempo_ratio": 1.0, "section_start_s": 10.0}
    obs = {"song": "bed_a", "version": "original", "tempo_ratio": round(al.tempo_ratio, 4),
           "section_start_s": al.offset_s}                             # observed = 31.7 (other part)
    assert B.is_match(exp, obs)["match"] is False


def test_library_index_and_external_root(tmp_project, tmp_path_factory):
    """index.yaml gives title/version; a library outside the project root is stored as a token path."""
    lib = S.make_library(tmp_project)
    tracks = B.load_library()
    by_file = {t.file.name: t for t in tracks}
    assert by_file["bed_a_x1.1.wav"].version == "sped_up" and by_file["bed_a.wav"].title == "Test Bed A"
    assert by_file["bed_b.wav"].stored == "assets/library/music/bed_b.wav"
    ext = tmp_path_factory.mktemp("user_music")
    S._write(ext / "extra_song.wav", S._read(lib["bed_b.wav"])[: 5 * S.SR])
    (tmp_project / "local.yaml").write_text(f"music_library_root: {ext}\n", encoding="utf-8")
    tracks = B.load_library()
    extra = [t for t in tracks if t.file.name == "extra_song.wav"]
    assert extra and extra[0].stored == "$music_library_root/extra_song.wav"
    assert extra[0].title is None and extra[0].version is None          # no index -> unmeasured fields
    from shortkit.reference.separation import resolve_stored

    assert resolve_stored(extra[0].stored) == ext / "extra_song.wav"


def test_empty_library_is_unmeasured(tmp_project):
    vp = tmp_project / "presets/joshuamagazine/reference/videos/vz.wav"
    S._write(vp, S._read(S.GEN / "speech_01.wav"))
    r = B.analyze_bgm(PRESET, "vz")
    assert r["status"] == "unmeasured" and "라이브러리" in r["blocker"]
    assert r["presence"] == "unmeasured"
    saved = json.loads((tmp_project / "presets/joshuamagazine/analysis/vz/audio/bgm.json").read_text())
    assert saved["status"] == "unmeasured"
    # no reference media at all
    r2 = B.analyze_bgm(PRESET, "missing_video")
    assert r2["status"] == "unmeasured" and r2["presence"] == "unmeasured"


@pytest.mark.slow
def test_unknown_music_is_not_forced_into_a_match(tmp_project):
    """Music that is not in the library must stay unidentified (no nearest-track guess)."""
    lib = S.make_library(tmp_project)
    (lib["bed_b.wav"]).unlink()
    idx = tmp_project / "assets/library/music/index.yaml"
    idx.write_text("\n".join(ln for ln in idx.read_text().splitlines() if "bed_b" not in ln) + "\n")
    vp = tmp_project / "presets/joshuamagazine/reference/videos/vb.wav"
    S._write(vp, S._read(S.GEN / "music_bed_b.wav")[5 * S.SR:20 * S.SR] * 0.3)
    r = B.analyze_bgm(PRESET, "vb")
    assert r["status"] == "unmeasured" and r.get("match") is None
    assert r["candidates"] and all(not c["selected"] for c in r["candidates"])


def test_online_recognizer_absent_is_reported():
    out = B.online_recognize(S.GEN / "music_bed_a.wav")
    assert out["status"] in ("not_installed", "error", "hint")
    if out["status"] == "not_installed":
        assert "shazamio" in out["note"]


def test_index_aliases(tmp_project):
    """index.yaml variants: list with `id`, and mapping form {track_id: {...}}."""
    lib = tmp_project / "assets/library/music"
    lib.mkdir(parents=True, exist_ok=True)
    x = S._read(S.GEN / "music_bed_b.wav")[: 3 * S.SR]
    S._write(lib / "a.wav", x)
    S._write(lib / "b.wav", x * 0.5)
    (lib / "index.yaml").write_text("tracks:\n  - {id: song_a_orig, title: A, version: original, file: a.wav}\n",
                                    encoding="utf-8")
    t = {x.file.name: x for x in B.load_library()}
    assert t["a.wav"].track_id == "song_a_orig" and t["a.wav"].song.startswith("A")
    assert t["b.wav"].track_id == "b" and t["b.wav"].version is None           # unindexed file
    (lib / "index.yaml").write_text("tracks:\n  song_b_half: {title: B, version: remix, path: b.wav}\n",
                                    encoding="utf-8")
    t = {x.file.name: x for x in B.load_library()}
    assert t["b.wav"].track_id == "song_b_half" and t["b.wav"].version == "remix"
