"""Measurement emitters of `ref audio-measure` on SYNTHETIC reference-like mixes with known ground truth:
audio.loudness.*, audio.bgm.loop, audio.silence.fade_s, audio.original.fade_s / keep_gain_db,
audio.sfx.gain_db_default, and the real (no reference) state.

All media is SYNTHETIC (synthref.py); the fades/restarts are built with the RENDERER's own shapes, so
the ground truth is in the units production uses."""
from __future__ import annotations

import json
import shutil

import numpy as np
import pytest

import synthref as S
from .conftest import PRESET, no_abs_paths
from shortkit.reference import audio_bgm, audio_original as O, separation

REPO = S.REPO
NEW_KEYS = ("audio.loudness.integrated_lufs", "audio.loudness.true_peak_db", "audio.bgm.loop",
            "audio.original.keep_gain_db", "audio.original.fade_s", "audio.silence.fade_s",
            "audio.sfx.gain_db_default")


def _spec(vid, **kw):
    base = {"bgm_file": "bed_r.wav", "bgm_offset": 12.0, "bgm_gain_db": -12.0}
    return S.VideoSpec(vid, **(base | kw))


SPECS = [
    # restarts / jumps of the BGM inside the video (non-periodic bed: unique ground truth)
    _spec("lpr", bgm_offset=10.0, bgm_segments=[(0.0, 10.0), (9.0, 10.0)], speech=[("speech_03", 3.0, -3.0)],
          format_id="F1"),
    _spec("lps", bgm_offset=10.0, bgm_segments=[(0.0, 10.0), (8.0, 40.0)], speech=[("speech_01", 12.0, -3.0)],
          format_id="F2"),
    _spec("lpe", bgm_offset=48.0, bgm_segments=[(0.0, 48.0), (11.5, 0.0)], dur=22.0,
          speech=[("speech_02", 5.0, -3.0)], format_id="F1"),
    # intentional silences with the renderer's dB-linear ramp
    _spec("sf0", silence=(8.0, 8.8), silence_fade=0.0, speech=[("speech_01", 3.0, -3.0)], format_id="F1"),
    _spec("sf1", silence=(8.0, 8.8), silence_fade=0.08, speech=[("speech_01", 3.0, -3.0)], format_id="F2"),
    _spec("sf2", silence=(8.0, 8.8), silence_fade=0.2, speech=[("speech_01", 3.0, -3.0)], format_id="F2"),
    # kept original sound: room tone with the renderer's linear-amplitude edge fades, speech inside
    _spec("of0", ambience=[(5.0, 11.0, -20.0, 0.0, 11)], speech=[("speech_02", 6.5, -3.0)], duck_db=8.0),
    _spec("of1", ambience=[(5.0, 11.0, -20.0, 0.05, 12)], speech=[("speech_02", 6.5, -3.0)], duck_db=8.0),
    _spec("of2", ambience=[(4.0, 12.0, -22.0, 0.15, 13)], speech=[("speech_02", 6.5, -3.0)], duck_db=8.0,
          format_id="F2"),
    # speech only (no BGM): kept speech level == programme level
    S.VideoSpec("spo", bgm_file=None, speech=[("speech_01", 2.0, -3.0), ("speech_03", 8.0, -3.0)], dur=14.0),
]
VIDS = [s.video_id for s in SPECS]


@pytest.fixture(scope="module")
def emit_project(tmp_path_factory):
    miss = S.require_assets()
    if miss:
        pytest.skip("test assets missing (run `python -m shortkit testassets synth`): " + ", ".join(miss))
    root = tmp_path_factory.mktemp("skemit")
    S.make_project(root)
    mp = pytest.MonkeyPatch()
    mp.setenv("SHORTKIT_ROOT", str(root))
    from shortkit.util.jsonio import read_yaml, write_yaml

    lib = S.make_library(root)
    lib["bed_r.wav"] = S.add_random_bed(root)
    bank = S.sfx_bank()
    oracle = S.OracleSeparator()
    res = {}
    for spec in SPECS:
        d = S.build(spec, lib, bank, root)
        vp = root / "presets" / PRESET / "reference" / "videos" / f"{spec.video_id}.wav"
        S._write(vp, d["mix"])
        oracle.add(vp, d)
        st = separation.separate_reference(PRESET, spec.video_id, separator=oracle)
        b = audio_bgm.analyze_bgm(PRESET, spec.video_id, stems=st)
        ctx = O.load_context(PRESET, spec.video_id, stems=st)
        o = O.analyze_original(PRESET, spec.video_id, ctx=ctx)
        res[spec.video_id] = {"truth": d["truth"], "bgm": b, "original": o, "mix": d["mix"], "vocals": d["vocals"]}
    fy = root / "presets" / PRESET / "formats.yaml"
    fd = read_yaml(fy, {}) or {}
    fd["assignments"] = {s.video_id: s.format_id for s in SPECS}
    write_yaml(fy, fd)
    S.write_snapshot(root, VIDS)
    yield {"root": root, "res": res}
    mp.undo()


@pytest.fixture
def emit_env(emit_project, monkeypatch):
    monkeypatch.setenv("SHORTKIT_ROOT", str(emit_project["root"]))
    return emit_project


# ----------------------------------------------------------------------------- audio.bgm.loop
@pytest.mark.slow
@pytest.mark.parametrize("vid,presence,kind,t_jump", [("lpr", "present", "restart", 9.0),
                                                      ("lps", "absent", "skip", 8.0),
                                                      ("lpe", "present", "restart", 11.5)])
def test_bgm_restart_detected(emit_env, vid, presence, kind, t_jump):
    r = emit_env["res"][vid]
    assert r["truth"]["bgm"]["loop"] is (presence == "present")
    b = r["bgm"]
    assert b["status"] == "measured"
    lp = b["match"]["loop"]
    assert lp["presence"] == presence, lp["jumps"]
    assert len(lp["jumps"]) == 1, lp["jumps"]
    j = lp["jumps"][0]
    assert j["kind"] == kind and abs(j["t"] - t_jump) <= 0.3
    assert j["t_range"][0] - 0.3 <= t_jump <= j["t_range"][1] + 0.3


@pytest.mark.slow
def test_continuous_bgm_has_no_restart(emit_env):
    for vid in ("sf0", "of1"):
        lp = emit_env["res"][vid]["bgm"]["match"]["loop"]
        assert lp["presence"] == "absent" and lp["jumps"] == []


# ----------------------------------------------------------------------------- audio.silence.fade_s
@pytest.mark.slow
@pytest.mark.parametrize("vid", ["sf0", "sf1", "sf2"])
def test_silence_ramps_in_renderer_units(emit_env, vid):
    r = emit_env["res"][vid]
    truth = r["truth"]["silence"]["fade_s"]
    items = [i for i in r["original"]["silences"]["items"] if i.get("bgm_cut")]
    assert len(items) == 1
    ramps = items[0]["ramps"]
    for side in ("into", "out_of"):
        assert ramps[side]["status"] == "measured", ramps
        assert abs(ramps[side]["fade_s"] - truth) <= max(0.01, 0.1 * truth), (side, ramps[side], truth)


# ----------------------------------------------------------------------------- audio.original.fade_s
@pytest.mark.slow
@pytest.mark.parametrize("vid", ["of0", "of1", "of2"])
def test_original_edge_ramps_in_renderer_units(emit_env, vid):
    r = emit_env["res"][vid]
    amb = r["truth"]["ambience"][0]
    edges = [e for e in r["original"]["original_edges"]["edges"] if e["status"] == "measured"]
    assert {e["edge"] for e in edges} == {"on", "off"}, r["original"]["original_edges"]
    for e in edges:
        assert abs(e["fade_s"] - amb["fade_s"]) <= 0.025, (e, amb)
        edge_t = amb["start"] if e["edge"] == "on" else amb["end"]
        assert abs(e["t"] - edge_t) <= amb["fade_s"] + 0.05


@pytest.mark.slow
def test_speech_edges_are_not_read_as_fades(emit_env):
    """Speech starting/ending at an edge shows its own envelope, not an edit ramp -> skipped."""
    for vid in ("sf0", "lpr", "spo"):
        oe = emit_env["res"][vid]["original"]["original_edges"]
        assert all(e["status"] != "measured" for e in oe.get("edges") or []), oe


# ----------------------------------------------------------------------------- audio.original.keep_gain_db
def _lufs(x):
    return O._lufs_of(np.asarray(x, np.float32), S.SR)


@pytest.mark.slow
@pytest.mark.parametrize("vid", ["of1", "sf1", "spo"])
def test_kept_speech_level_matches_truth(emit_env, vid):
    r = emit_env["res"][vid]
    kl = r["original"]["kept_speech_level"]
    assert kl["status"] == "measured", kl
    true_speech = np.concatenate([r["vocals"][int(s["start"] * S.SR):int(s["end"] * S.SR)]
                                  for s in r["truth"]["speech"]])
    truth = _lufs(true_speech) - _lufs(r["mix"])
    assert abs(kl["rel_program_lu"] - truth) <= 0.5, (kl, truth)
    if vid == "spo":                                   # the programme IS the speech
        assert abs(kl["rel_program_lu"]) <= 0.7


# ----------------------------------------------------------------------------- aggregation
@pytest.mark.slow
def test_aggregate_emits_all_new_keys(emit_env):
    r = O.aggregate_measurements(PRESET, VIDS)
    items = {i["key"]: i for i in r["items"]}
    assert set(NEW_KEYS) <= set(items)
    lu = items["audio.loudness.integrated_lufs"]
    assert lu["status"] == "measured" and lu["overall"]["n"] == len(VIDS) and set(lu["by_format"]) == {"F1", "F2"}
    assert all("range_s" in e and e["t"] == 0.0 for e in lu["evidence"])
    tp = items["audio.loudness.true_peak_db"]
    assert tp["status"] == "measured" and tp["unit"] == "dBTP" and tp["value"] < 0
    lp = items["audio.bgm.loop"]
    assert lp["status"] == "measured" and lp["overall"]["counts"]["present"] == 2
    assert lp["value"] is False and lp["presence"] == "present"      # 2 of 9 videos restart: majority does not
    assert {e["video_id"] for e in lp["evidence"] if e["value"] == "present"} == {"lpr", "lpe"}
    sf = items["audio.silence.fade_s"]
    assert sf["status"] == "measured" and sf["overall"]["n"] == 6
    assert abs(sf["overall"]["p50"] - 0.08) <= 0.01 and sf["by_format"]["F2"]["n"] == 4
    of = items["audio.original.fade_s"]
    assert of["status"] == "measured" and of["overall"]["n"] == 6
    assert abs(of["value"] - 0.05) <= 0.025
    kg = items["audio.original.keep_gain_db"]
    assert kg["status"] == "measured" and kg["value_semantics"].startswith("LU re programme")
    assert kg["overall"]["n"] == len(VIDS)
    bg = items["audio.bgm.gain_db"]
    assert bg["target_lufs"]["overall"] == lu["value"] and "이번 측정" in bg["target_lufs"]["source"]
    assert bg["target_lufs"]["by_format"] == {f: v["value"] for f, v in lu["by_format"].items()}
    sx = items["audio.sfx.gain_db_default"]
    assert sx["status"] == "unmeasured" and sx["blocker"]                 # no SFX catalog in this project
    saved = json.loads((emit_env["root"] / "presets" / PRESET / "measurements" / "audio.json").read_text())
    assert not no_abs_paths(saved, emit_env["root"])
    ld = json.loads(O.loudness_path(PRESET, "sf1").read_text())
    assert ld["schema"] == O.LOUDNESS_SCHEMA and ld["audio_file"].startswith("presets/")


def test_loudness_of_known_sine(tmp_project):
    """997 Hz sine, amplitude A on both channels -> 20*log10(A) LUFS (BS.1770) and dBTP."""
    from shortkit.util.jsonio import read_yaml, write_yaml

    sr = 48000
    t = np.arange(int(6 * sr)) / sr
    vdir = tmp_project / "presets" / PRESET / "reference" / "videos"
    for vid, amp in (("sine20", 0.1), ("sine26", 0.05)):
        x = (amp * np.sin(2 * np.pi * 997.0 * t)).astype(np.float32)
        S._write(vdir / f"{vid}.wav", np.stack([x, x], 1), sr)
    fy = tmp_project / "presets" / PRESET / "formats.yaml"
    fd = read_yaml(fy, {}) or {}
    fd["assignments"] = {"sine20": "F1", "sine26": "F2"}
    write_yaml(fy, fd)
    S.write_snapshot(tmp_project, ["sine20", "sine26"])
    r = O.aggregate_measurements(PRESET)                   # default set: the downloaded reference files
    assert r["videos"] == ["sine20", "sine26"]
    items = {i["key"]: i for i in r["items"]}
    lu, tp = items["audio.loudness.integrated_lufs"], items["audio.loudness.true_peak_db"]
    assert abs(lu["by_format"]["F1"]["value"] + 20.0) <= 0.3 and abs(lu["by_format"]["F2"]["value"] + 26.02) <= 0.3
    assert abs(tp["by_format"]["F1"]["value"] + 20.0) <= 0.3 and abs(tp["by_format"]["F2"]["value"] + 26.02) <= 0.3
    assert lu["overall"]["n"] == 2 and abs(lu["value"] + 23.0) <= 0.3
    first = json.loads(O.loudness_path(PRESET, "sine20").read_text())
    O.aggregate_measurements(PRESET)
    again = json.loads(O.loudness_path(PRESET, "sine20").read_text())
    assert again["measured_at"] == first["measured_at"]    # cached by sha256


def test_real_state_items_carry_collect_blocker(tmp_project):
    """No reference video (collection blocked): every audio item is unmeasured with the blocker text of
    reference/latest100.json, like the visual items."""
    snap = REPO / "presets" / PRESET / "reference" / "latest100.json"
    (tmp_project / "presets" / PRESET / "reference").mkdir(parents=True, exist_ok=True)
    shutil.copy(snap, tmp_project / "presets" / PRESET / "reference" / "latest100.json")
    real = json.loads(snap.read_text())
    r = O.aggregate_measurements(PRESET)
    items = {i["key"]: i for i in r["items"]}
    assert set(NEW_KEYS) <= set(items)
    for it in r["items"]:
        assert it["status"] == "unmeasured" and it["value"] is None
        if real.get("status") == "blocked":
            assert "레퍼런스 목록 수집 차단" in it["blocker"], it
            assert str(real["blocker"])[:60] in it["blocker"]


# ----------------------------------------------------------------------------- audio.sfx.gain_db_default
@pytest.mark.slow
def test_sfx_gain_default_in_renderer_semantics(project_env):
    """Catalogued SFX events -> gain applied to the mapped library FILE at programme loudness T:
    truth = placed gain (dB re bank file) - library file gain (dB re bank file) + T - mix LUFS."""
    from shortkit.reference import sfx_catalog as C, sfx_map as M

    root = project_env["root"]
    vids = ["synv1", "synv2", "synv3", "synv4"]
    C.build_catalog(PRESET, video_ids=vids)
    lib = root / "assets" / "library" / "sfx"
    map_file = root / "presets" / PRESET / "sfx_map.yaml"
    saved_map = map_file.read_text(encoding="utf-8") if map_file.exists() else None
    shutil.rmtree(lib, ignore_errors=True)
    lib.mkdir(parents=True)
    bank = project_env["bank"]
    file_gain = {"pop": 0.0, "whoosh": -6.0, "ding": 3.0, "boom": -2.0}
    for name, g in file_gain.items():
        S._write(lib / f"{name}.wav", bank[name] * 10 ** (g / 20))
    try:
        m = M.build_map(PRESET)
        assert sum(1 for v in m["types"].values() if v["status"] == "have") == 4
        r = O.aggregate_measurements(PRESET, vids, write=False)
        it = {i["key"]: i for i in r["items"]}["audio.sfx.gain_db_default"]
        assert it["status"] == "measured", it
        T = it["target_lufs"]["overall"]
        mix_lufs = {v: O.measure_loudness(PRESET, v, write=False)["integrated_lufs"] for v in vids}
        errs = []
        for e in it["evidence"]:
            tr = [x for x in project_env["truths"][e["video_id"]]["sfx"] if abs(x["t"] - e["t"]) <= 0.05]
            assert tr, e
            truth = tr[0]["gain_db"] - file_gain[tr[0]["name"]] + T - mix_lufs[e["video_id"]]
            errs.append(e["value"] - truth)
        assert len(errs) >= 10
        assert float(np.median(np.abs(errs))) <= 0.75 and float(np.max(np.abs(errs))) <= 2.0, errs
        assert it["catalog_gain_db_rel_mix_overall"]["n"] >= len(errs)
        assert "gain_db_rel_mix" in it["method"]
    finally:
        shutil.rmtree(lib, ignore_errors=True)
        if saved_map is not None:
            map_file.write_text(saved_map, encoding="utf-8")
