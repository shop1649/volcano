"""Fast unit tests for shortkit.qa (no video decoding except tiny synthetic arrays).

All signals here are SYNTHETIC (numpy noise / tones / the generated music bed), built in the test.
"""
from __future__ import annotations

import shutil
from types import SimpleNamespace

import numpy as np
import pytest

from shortkit import config, paths
from shortkit.edit.ir import Clip, Freeze, Rect, Transition, Zoom
from shortkit.qa import clip_transform, ease_value, hex_rgb, map_src_rect, merge_ranges, src_time, zoom_scale
from shortkit.qa import checks, gate
from shortkit.qa import probes_audio as pa


def _clip(**kw):
    base = dict(id="c", source_id="s", source_path="x.mp4", src_in=10.0, src_out=12.0, speed=1.0, out_start=5.0,
                out_end=7.0, region=Rect(0, 437, 720, 405), fit="cover", src_size=(1920, 1080))
    base.update(kw)
    return Clip(**base)


# ----------------------------------------------------------------------------- declarations
def test_declarations_cover_every_style_key():
    pr = config.load_preset("joshuamagazine")
    decl = checks.declarations()
    missing = []
    for k in config.flatten(pr.data):
        cat = config.classify_key(k)
        if cat in ("meta", "infra", "rule"):
            continue
        if not any(config._match(k, p) for pats in decl.values() for p in pats):
            missing.append(k)
    assert missing == []
    fams = {"canvas.", "text.roles.", "text.tone.", "motion.", "decorations.", "audio.", "structure.", "cover."}
    for f in fams:
        assert any(p.startswith(f) or p.startswith(f.rstrip(".")) for pats in decl.values() for p in pats), f


def test_categories_required_by_user_exist():
    for c in ("글자 위치", "폰트", "자막 타이밍", "컷", "모션(확대·정지·전환)", "음악 구간", "원음", "로고 잔류",
              "효과음 종류별 개수", "사건과의 시차", "사건 없는 효과음 0", "움직이는 장식(위치/밝기 각각)", "식별 요소",
              "얼굴·손·물체 가림", "음량"):
        assert c in checks.REQUIRED_CATEGORIES


# ----------------------------------------------------------------------------- geometry
def test_hex_rgb_variants():
    assert hex_rgb("#FFE400") == (255, 228, 0)
    assert hex_rgb("&H0000E4FF") == (255, 228, 0)
    assert hex_rgb(None, (1, 2, 3)) == (1, 2, 3)


def test_cover_fit_and_rect_mapping():
    c = _clip()
    tr = clip_transform(c, 5.5)
    assert tr["s"] == pytest.approx(0.375)
    assert map_src_rect(c, {"x": 16, "y": 14, "w": 190, "h": 44}, 5.5) == pytest.approx([6.0, 437 + 5.25, 71.25, 16.5])


def test_zoom_fixed_point_and_ease():
    c = _clip(zoom=Zoom(1.0, 1.3, (960.0, 540.0), 0.4, 0.5, "out"))
    assert zoom_scale(c, 5.2) == 1.0
    assert zoom_scale(c, 6.0) == pytest.approx(1.3)
    assert zoom_scale(c, 5.65) == pytest.approx(1.0 + 0.3 * ease_value(0.5, "out"))
    assert ease_value(0.5, "out") == pytest.approx(0.875)        # cubic out
    # the zoom centre does not move
    t = 6.0
    tr = clip_transform(c, t)
    assert 960 * tr["s"] + tr["tx"] == pytest.approx(360.0)
    assert 540 * tr["s"] + tr["ty"] == pytest.approx(437 + 202.5)


def test_src_time_freeze_continues_from_held_frame():
    c = _clip(src_in=24.0, src_out=26.0, out_start=5.2, out_end=7.8, freeze=Freeze(26.0, 7.2, 0.6))
    assert src_time(c, 6.2) == pytest.approx(25.0)
    assert src_time(c, 7.5) == pytest.approx(26.0)
    c2 = _clip(src_in=0.0, src_out=4.0, out_start=0.0, out_end=4.5, freeze=Freeze(1.0, 1.0, 0.5))
    assert src_time(c2, 1.2) == 1.0
    assert src_time(c2, 2.0) == pytest.approx(1.5)


def test_merge_ranges():
    assert merge_ranges([(0, 1), (1.05, 2), (3, 4)], gap=0.1) == [[0, 2], [3, 4]]


# ----------------------------------------------------------------------------- audio DSP (synthetic)
SR = 16000


def _music(seconds=20.0, seed=3):
    rng = np.random.default_rng(seed)
    t = np.arange(int(seconds * SR)) / SR
    x = 0.2 * np.sin(2 * np.pi * 220 * t) * (0.5 + 0.5 * np.sin(2 * np.pi * 2 * t))
    for k in range(int(seconds * 4)):                # random "hat" bursts every 0.25 s
        s = int(k * 0.25 * SR)
        n = int(0.03 * SR)
        x[s:s + n] += 0.3 * rng.standard_normal(n) * np.exp(-np.arange(n) / 80)
    return x.astype(np.float32)


def test_find_bgm_tempo_and_exact_section():
    music = _music(20.0)
    sec = 6.3
    y = 0.4 * music[int(sec * SR):int(sec * SR) + 5 * SR]
    y = y + 0.01 * np.random.default_rng(1).standard_normal(len(y)).astype(np.float32)
    fb = pa.find_bgm(y, music, SR, tempo_center=1.0, span=0.05, step=0.01, hop=128)
    assert fb["found"] and fb["tempo"] == pytest.approx(1.0, abs=0.011)
    # this music is periodic (hat every 0.25 s): the onset envelope alone is ambiguous in offset,
    # the waveform alignment over all lags is not
    ga = pa.global_align(y, music, sr=SR)
    assert ga["lag"] / SR == pytest.approx(sec, abs=1e-3) and ga["ncc"] > 0.95
    assert ga["runner_up"]["ncc"] < ga["ncc"] - 0.05   # a different part of the same "song" is worse
    L, v = pa.refine_offset(y, music, int(round((sec + 0.02) * SR)), int(0.05 * SR))
    assert L / SR == pytest.approx(sec, abs=1e-3) and v > 0.95


def test_window_ls_recovers_ducking_and_sfx_matched_filter():
    music = _music(8.0)
    n = len(music)
    t = np.arange(n) / SR
    gain = np.where((t > 3.0) & (t < 5.0), 10 ** (-10 / 20), 1.0)
    click = (np.random.default_rng(5).standard_normal(int(0.05 * SR)) * np.exp(-np.arange(int(0.05 * SR)) / 150)).astype(np.float32)
    y = (0.3 * music * gain).astype(np.float32)
    y[int(6.0 * SR):int(6.0 * SR) + len(click)] += 0.3 * click
    tc, G, r = pa.window_ls(y, [music], SR, 0.25)
    rel = pa.db(G[:, 0] / np.nanpercentile(G[:, 0], 90))
    inside = rel[(tc > 3.3) & (tc < 4.7)]
    outside = rel[(tc < 2.7) | ((tc > 5.3) & (tc < 5.8))]
    assert np.all(np.abs(inside + 10) < 0.5) and np.all(np.abs(outside) < 0.5)
    dets = pa.detect_sfx(r, {"click": {"type": "click", "file": "synthetic", "audio": click}}, SR)
    assert len(dets) == 1 and dets[0]["t"] == pytest.approx(6.0, abs=0.002)
    assert 20 * np.log10(dets[0]["gain"]) == pytest.approx(20 * np.log10(0.3), abs=0.5)


def test_unexplained_onset_found_in_residual():
    rng = np.random.default_rng(2)
    n = 4 * SR
    y = 0.001 * rng.standard_normal(n).astype(np.float32)
    y[2 * SR:2 * SR + 800] += 0.3 * rng.standard_normal(800).astype(np.float32)
    ons = pa.unexplained_onsets(y, y, SR, exclude=[])
    assert len(ons) == 1 and ons[0]["t"] == pytest.approx(2.0, abs=0.02)
    assert pa.unexplained_onsets(y, y, SR, exclude=[(1.9, 2.2)]) == []


# ----------------------------------------------------------------------------- gate
def _row(cid, status, required=True, intended=False, kind="output_vs_plan"):
    return {"check_id": cid, "row_id": f"{cid}:x", "status": status, "required": required, "intended_change": intended,
            "kind": kind, "category": "컷"}


def test_gate_rules():
    ok_rows = [_row("video.cuts", "same"), _row("audio.sfx.no_event", "same"), _row("audio.sfx.offset", "same")]
    g = gate.evaluate(ok_rows, mode="test", mp4_sha_measured="a", mp4_sha_now="a", unmeasured_preset_keys=["k"])
    assert g["pass"] and not g["complete"]            # test mode: never complete for publishing
    assert any(w["rule"] == "P1" for w in g["warnings"])
    g = gate.evaluate(ok_rows + [_row("caption.position", "different")], mode="test", mp4_sha_measured="a",
                      mp4_sha_now="a", unmeasured_preset_keys=[])
    assert not g["pass"] and g["failures"][0]["rule"] == "G1"
    g = gate.evaluate(ok_rows + [_row("x.y", "different", intended=True)], mode="test", mp4_sha_measured="a",
                      mp4_sha_now="a", unmeasured_preset_keys=[])
    assert g["pass"]
    g = gate.evaluate(ok_rows + [_row("x.y", "unmeasured", required=True)], mode="test", mp4_sha_measured="a",
                      mp4_sha_now="a", unmeasured_preset_keys=[])
    assert not g["pass"] and any(f["rule"] == "G2" for f in g["failures"])
    g = gate.evaluate([_row("video.cuts", "same"), _row("audio.sfx.no_event", "different"), _row("audio.sfx.offset", "same")],
                      mode="test", mp4_sha_measured="a", mp4_sha_now="a", unmeasured_preset_keys=[])
    assert any(f["rule"] == "G3" for f in g["failures"])
    g = gate.evaluate(ok_rows, mode="test", mp4_sha_measured="a", mp4_sha_now="b", unmeasured_preset_keys=[])
    assert any(f["rule"] == "G5" for f in g["failures"])
    # production: unmeasured preset keys and style rows 'unmeasured' block completion
    g = gate.evaluate(ok_rows + [_row("caption.font", "unmeasured", required=False, kind="style_vs_reference")],
                      mode="production", mp4_sha_measured="a", mp4_sha_now="a", unmeasured_preset_keys=["text.roles.title.size_px"])
    assert not g["pass"] and {f["rule"] for f in g["failures"]} >= {"P1", "P2"}


# ----------------------------------------------------------------------------- style-vs-reference rows
@pytest.fixture()
def temp_root(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    shutil.copy(paths.project_root() / "shortkit.root", root / "shortkit.root")
    shutil.copytree(paths.project_root() / "presets" / "joshuamagazine", root / "presets" / "joshuamagazine",
                    ignore=shutil.ignore_patterns("videos", "frames", "stems", "*.wav", "*.mp4"))
    monkeypatch.setenv("SHORTKIT_ROOT", str(root))
    return root


def _ctx_with(preset, mode="test"):
    return SimpleNamespace(preset=preset, resolved=SimpleNamespace(mode=mode, format_id="F1"), episode_id="e")


def test_style_rows_provisional_measured_and_requested(temp_root):
    from shortkit.util.jsonio import write_json, write_yaml

    d = temp_root / "presets" / "joshuamagazine"
    write_yaml(d / "measured.yaml", {"preset_id": "joshuamagazine-v1", "common": {"canvas": {"width": 1080, "height": 1920,
                                                                                               "fps": 30}}})
    write_json(d / "measurements" / "canvas.json", {"schema": "shortkit.measurement/1", "group": "canvas", "items": [
        {"key": "canvas.width", "status": "measured", "value": 1080, "overall": {"n": 40, "p10": 1080, "p50": 1080, "p90": 1080}},
        {"key": "canvas.height", "status": "measured", "value": 1920, "overall": {"n": 40, "p10": 1920, "p50": 1920, "p90": 1920}},
        {"key": "canvas.fps", "status": "measured", "value": 30, "overall": {"n": 40, "p10": 30, "p50": 30, "p90": 30}}]})
    write_yaml(d / "requested_changes.yaml", {"preset_id": "joshuamagazine-v1", "changes": {"audio": {"loudness": {
        "integrated_lufs": -16.0}}}})
    pr = config.load_preset("joshuamagazine", "F1")
    b = checks.RowBuilder(_ctx_with(pr))
    cmp = lambda o, r: o["width"] == r["canvas.width"] and o["height"] == r["canvas.height"]  # noqa: E731
    r1 = b.style_row("canvas.format", "a", "x", "화면 구성", ["canvas.width", "canvas.height", "canvas.fps"],
                     {"width": 1080, "height": 1920, "fps": 30}, cmp)
    assert r1["status"] == "same" and r1["reference"]["canvas.width"]["p50"] == 1080
    r2 = b.style_row("canvas.format", "b", "x", "화면 구성", ["canvas.width"], {"width": 720, "height": 1920}, cmp)
    assert r2["status"] == "different" and not r2["intended_change"]
    # provisional key: 못 잼 even if the output equals the preset value
    r3 = b.style_row("caption.size", "c", "x", "글자 위치", ["text.roles.title.size_px"], {"size_px_est": 84.0},
                     lambda o, r: True)
    assert r3["status"] == "unmeasured" and r3["reference"] == "못 잼"
    # requested change: reported as an intended difference, linked to requested_changes.yaml
    r4 = b.style_row("audio.loudness", "d", "x", "음량", ["audio.loudness.integrated_lufs"], {"integrated_lufs": -16.1},
                     lambda o, r: abs(o["integrated_lufs"] - r["audio.loudness.integrated_lufs"]) <= 1.0)
    assert r4["status"] == "different" and r4["intended_change"] and "requested_changes.yaml" in r4["change_ref"]
    r5 = b.style_row("audio.loudness", "e", "x", "음량", ["audio.loudness.integrated_lufs"], {"integrated_lufs": -10.0},
                     lambda o, r: abs(o["integrated_lufs"] - r["audio.loudness.integrated_lufs"]) <= 1.0)
    assert r5["status"] == "different" and not r5["intended_change"]
    # QA reads are traced as code links for the registry
    assert any("checks.py" in c for c in pr.log.to_dict().get("audio.loudness.integrated_lufs", []))


# ----------------------------------------------------------------------------- defects lifecycle
def test_defects_lifecycle(temp_root):
    from shortkit.qa import defects

    (temp_root / "episodes" / "e1" / "qa").mkdir(parents=True)
    ctx = SimpleNamespace(episode_id="e1")

    def rep(status):
        return {"rows": [dict(_row("caption.position", status), item="자막 위치", expected=1, observed=2, note="")],
                "gate": {"pass": status == "same", "complete": False}, "output": {"sha256": "abc"}}

    s = defects.sync(ctx, rep("different"), recheck_others=False)
    assert s["new"] == 1 and s["open"] == 1
    items = defects.load("e1")
    assert items[0]["status"] == "open" and items[0]["final_gate"]["pass"] is False
    for k in ("id", "check_id", "found_at", "description", "fix", "recheck_same_cases", "final_gate"):
        assert k in items[0]
    defects.add_fix("e1", items[0]["id"], "자막 y 좌표 수정")
    s = defects.sync(ctx, rep("different"), recheck_others=False)
    assert s["reopened"] == 1 and defects.load("e1")[0]["status"] == "reopened"
    defects.add_fix("e1", items[0]["id"], "다시 수정")
    s = defects.sync(ctx, rep("same"), recheck_others=False)
    d = defects.load("e1")[0]
    assert s["verified_now"] == 1 and d["status"] == "fixed" and d["final_gate"]["pass"] is True
    assert [h["event"] for h in d["history"]] == ["found", "fix_submitted", "reopened", "fix_submitted", "verified_fixed"]
