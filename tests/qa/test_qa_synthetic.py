"""End-to-end QA on SYNTHETIC renders with known ground truth (tests/qa/qa_synth.py).

episodes/test-qa-good : rendered exactly as its plan (resolved.json) says
episodes/test-qa-bad  : same plan, deliberately wrong render (moved caption over a declared face,
                        wrong BGM section, extra ducking, SFX without event, unknown extra sound,
                        watermark left in, decoration shifted)

The probes must recover the truth within stated tolerances and the checks must flag every
deliberate mistake -- and nothing else that is actually right.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

pytestmark = pytest.mark.slow

ROOT = Path(__file__).resolve().parents[2]


def _synth_hash() -> str:
    return hashlib.sha256((HERE / "qa_synth.py").read_bytes()).hexdigest()[:16]


def _ensure(ep: str, bad: bool) -> None:
    import qa_synth

    marker = ROOT / "episodes" / ep / "build" / "synth_hash.txt"
    mp4 = ROOT / "episodes" / ep / "output" / f"{ep}.mp4"
    if marker.is_file() and mp4.is_file() and marker.read_text().strip() == _synth_hash():
        return
    qa_synth.render_episode(ep, bad=bad)
    marker.write_text(_synth_hash())


@pytest.fixture(scope="session")
def reports():
    from shortkit.qa.report import run_and_write

    out = {}
    for ep, bad in (("test-qa-good", False), ("test-qa-bad", True)):
        _ensure(ep, bad)
        # a fresh measurement every session (the QA code is what is under test)
        dfile = ROOT / "episodes" / ep / "qa" / "defects.jsonl"
        if dfile.exists():
            dfile.unlink()
        out[ep] = run_and_write(ep, recheck_others=False, quiet=True)
    return out


def rows(rep, check_id=None, row_id=None):
    rs = rep["rows"]
    if row_id:
        rs = [r for r in rs if r["row_id"] == row_id]
        assert rs, f"row {row_id} missing"
        return rs[0]
    return [r for r in rs if r["check_id"] == check_id]


def status(rep, row_id):
    return rows(rep, row_id=row_id)["status"]


# ----------------------------------------------------------------------------- GOOD render
def test_good_captions_found_at_the_right_place_and_time(reports):
    rep = reports["test-qa-good"]
    for cid in ("t1", "s1", "k1", "d1", "r1"):
        assert status(rep, f"caption.position:{cid}") == "same", cid
        assert status(rep, f"caption.timing:{cid}") == "same", cid
        assert status(rep, f"caption.size:{cid}") == "same", cid
    text = json.loads((ROOT / "episodes/test-qa-good/qa/probes/text.json").read_text())
    caps = {c["id"]: c for c in text["captions"]}
    # onset/offset within one frame of the truth (native 30 fps)
    assert abs(caps["s1"]["onset"] - 0.8) <= 1 / 30 + 0.005
    assert abs(caps["s1"]["offset"] - 2.3) <= 1 / 30 + 0.005
    assert abs(caps["r1"]["onset"] - 5.4) <= 1 / 30 + 0.005


def test_good_caption_motion_pop_fade_none(reports):
    rep = reports["test-qa-good"]
    text = json.loads((ROOT / "episodes/test-qa-good/qa/probes/text.json").read_text())
    caps = {c["id"]: c for c in text["captions"]}
    assert caps["s1"]["motion_in_obs"]["type"] == "pop"
    assert caps["s1"]["motion_in_obs"]["scale_first"] == pytest.approx(0.85, abs=0.06)
    assert caps["r1"]["motion_in_obs"]["type"] == "pop"
    assert caps["r1"]["motion_in_obs"]["scale_first"] > 1.15
    assert caps["k1"]["motion_in_obs"]["type"] == "fade"
    assert caps["d1"]["motion_in_obs"]["type"] == "none"
    for cid in ("t1", "s1", "k1", "d1", "r1"):
        assert status(rep, f"caption.motion:{cid}") == "same", cid


def test_good_cuts_transitions_zoom_freeze(reports):
    rep = reports["test-qa-good"]
    for cid in ("c2", "c3"):
        assert status(rep, f"video.cuts:{cid}") == "same", cid
        assert status(rep, f"video.transitions:{cid}") == "same", cid
    assert status(rep, "video.cuts:unexpected") == "same"
    assert status(rep, "video.zoom:c3") == "same"
    z = rows(rep, row_id="video.zoom:c3")["observed"]
    assert z["measured_final_ratio"] == pytest.approx(1.3, abs=0.04)
    assert status(rep, "video.freeze:c3") == "same"
    assert status(rep, "video.freeze:unexpected") == "same"
    video = json.loads((ROOT / "episodes/test-qa-good/qa/probes/video.json").read_text())
    b = {x["clip_id"]: x for x in video["transitions"]["boundaries"]}
    assert b["c2"]["observed"]["type"] == "crossfade"
    assert b["c2"]["observed"]["t"] == pytest.approx(2.2, abs=1 / 30)
    assert b["c2"]["observed"]["dur"] == pytest.approx(0.3, abs=2 / 30)
    assert b["c3"]["observed"]["type"] == "flash"


def test_good_decoration_position_and_blink_measured_separately(reports):
    rep = reports["test-qa-good"]
    assert status(rep, "decor.position:dc1") == "same"
    assert status(rep, "decor.brightness:dc1") == "same"
    br = rows(rep, row_id="decor.brightness:dc1")["observed"]
    assert br["blink_hz"] == pytest.approx(2.0, rel=0.15)


def test_good_audio(reports):
    rep = reports["test-qa-good"]
    for rid in ("audio.bgm:file", "audio.bgm:tempo", "audio.bgm:section", "audio.ducking:planned",
                "audio.ducking:outside", "audio.ducking:orig_present", "audio.ducking:depth", "audio.silence:s0",
                "audio.silence:unexpected", "audio.original:kept0", "audio.original:level0", "audio.original:off",
                "audio.sfx.no_event:all",
                "audio.sfx.unexplained:all", "audio.loudness:mix"):
        assert status(rep, rid) == "same", rid
    for fx in ("fx1", "fx2", "fx3", "fx4"):
        assert status(rep, f"audio.sfx.placement:{fx}") == "same", fx
        assert status(rep, f"audio.sfx.offset:{fx}") == "same", fx
        assert status(rep, f"audio.sfx.placement:{fx}:gain") == "same", fx
    sec = rows(rep, row_id="audio.bgm:section")["observed"]["section_start_s"]
    assert sec == pytest.approx(12.0, abs=0.01)
    # user rule through audio_bgm.is_match: track AND version AND tempo AND section
    m = rows(rep, row_id="audio.bgm:match")
    assert m["status"] == "same"
    assert m["observed"]["checks"] == {"track_id": True, "version": True, "tempo_ratio": True, "section_start_s": True}
    assert "곡=같다, 버전=같다, 속도=같다, 구간=같다" in m["note"]
    assert "is_match 4요소: 곡=같다, 버전=같다, 속도=같다, 구간=같다" in rows(rep, row_id="audio.bgm:file")["note"]


def _op_rows(rep):
    """per-op residual rows (the plan's own clean ops), not the provenance rows"""
    return [r for r in rows(rep, "clean.residual") if not r["row_id"].startswith("clean.residual:prov:")]


def test_good_residual_identity_cover_up(reports):
    rep = reports["test-qa-good"]
    assert [r["status"] for r in _op_rows(rep)] == ["same"]
    # sources never scanned by `shortkit clean detect` (no warehouse/overlays record): honest 못 잼
    for r in rows(rep, "clean.residual"):
        if r["row_id"].startswith("clean.residual:prov:") and r["observed"] is None:
            assert r["status"] == "unmeasured" and "clean detect" in r["note"]
    assert status(rep, "identity.forbidden_text:all") == "same"
    assert status(rep, "cover_up.protected:c1#0") == "same"


def test_good_gate_blockers_are_only_honest_unmeasured_items(reports):
    """With a provisional preset nothing may be called complete; in test mode the gate may only
    fail on items that genuinely cannot be measured here -- never on a false 'different'."""
    rep = reports["test-qa-good"]
    diff = [r["row_id"] for r in rep["rows"] if r["status"] == "different"]
    # the noun title "실험 영상 모음" ('collection') is register-neutral (aggregate.ending_class, fix-qa2): it used to be
    # classified 음슴체 and made caption.tone:register a false 'different'
    tone = rows(rep, row_id="caption.tone:register")
    assert tone["status"] == "same", tone["observed"]
    assert any(it["ending"] == "모음" and it["class"] == "명사형/기타" for it in tone["observed"]["items"]), tone["observed"]
    assert diff == []
    g = rep["gate"]
    assert not g["complete"]
    for f in g["failures"]:
        assert f["rule"] == "G2", f


# ----------------------------------------------------------------------------- BAD render
def test_bad_moved_caption_is_flagged_and_covers_the_face(reports):
    rep = reports["test-qa-bad"]
    r = rows(rep, row_id="caption.position:s1")
    assert r["status"] == "different"
    assert r["observed"]["dy"] == pytest.approx(-353, abs=6)
    assert status(rep, "cover_up.protected:c1#0") == "different"
    # the other captions are still right
    for cid in ("t1", "d1"):
        assert status(rep, f"caption.position:{cid}") == "same", cid


def test_bad_wrong_bgm_section(reports):
    rep = reports["test-qa-bad"]
    r = rows(rep, row_id="audio.bgm:section")
    assert r["status"] == "different"
    # same file (track + version) at the same tempo but another part of the song is NOT a match
    m = rows(rep, row_id="audio.bgm:match")
    assert m["status"] == "different"
    assert m["observed"]["checks"] == {"track_id": True, "version": True, "tempo_ratio": True, "section_start_s": False}
    assert "곡=같다, 버전=같다, 속도=같다, 구간=다르다" in m["note"]
    # the synthetic bed repeats exactly every 8 s (4 bars) apart from faint random hats, so 17 s and
    # 25 s are the same sound; either is a correct measurement, 12 s (the plan) is not
    obs = r["observed"]["section_start_s"]
    assert min(abs(obs - 17.0 - 8 * k) for k in range(-2, 6)) <= 0.01, obs
    assert min(abs(obs - 12.0 - 8 * k) for k in range(-2, 6)) > 1.0, obs


def test_bad_ducking_outside_kept_dialogue(reports):
    rep = reports["test-qa-bad"]
    r = rows(rep, row_id="audio.ducking:outside")
    assert r["status"] == "different"
    rngs = [x["range"] for x in r["observed"]["ducking_outside"]]
    assert any(a <= 1.3 and b >= 1.8 for a, b in rngs), rngs
    assert status(rep, "audio.ducking:planned") == "same"


def test_bad_sfx_without_event_and_unknown_sound(reports):
    rep = reports["test-qa-bad"]
    ne = rows(rep, row_id="audio.sfx.no_event:all")
    assert ne["status"] == "different"
    assert any(abs(i["t"] - 6.9) < 0.03 and i["type"] == "pop" for i in ne["observed"]["items"])
    un = rows(rep, row_id="audio.sfx.unexplained:all")
    assert un["status"] == "different"
    assert any(abs(o["t"] - 1.6) < 0.05 for o in un["observed"]["onsets"])
    assert rows(rep, row_id="audio.sfx.count:pop")["observed"] == 2
    for fx in ("fx1", "fx2", "fx3", "fx4"):              # the planned ones are still there
        assert status(rep, f"audio.sfx.placement:{fx}") == "same", fx


def test_bad_leftover_watermark(reports):
    rep = reports["test-qa-bad"]
    r = _op_rows(rep)
    assert [x["status"] for x in r] == ["different"]
    assert r[0]["observed"]["edge_ncc"] >= 0.55
    # the corner OCR net catches the same account handle independently of the plan's clean ops
    assert status(rep, "clean.corners:all") == "different"
    assert status(reports["test-qa-good"], "clean.corners:all") == "same"


def test_bad_decoration_position_wrong_but_blink_right(reports):
    rep = reports["test-qa-bad"]
    assert status(rep, "decor.position:dc1") == "different"
    assert status(rep, "decor.brightness:dc1") == "same"


def test_bad_gate_fails_and_defects_recorded(reports):
    rep = reports["test-qa-bad"]
    assert rep["gate"]["pass"] is False
    rules = {f["rule"] for f in rep["gate"]["failures"]}
    assert {"G1", "G3"} <= rules
    items = [json.loads(l) for l in (ROOT / "episodes/test-qa-bad/qa/defects.jsonl").read_text().splitlines() if l.strip()]
    ids = {d["row_id"] for d in items}
    for rid in ("caption.position:s1", "audio.bgm:section", "audio.ducking:outside", "audio.sfx.no_event:all",
                "decor.position:dc1"):
        assert rid in ids, rid
    assert all(d["status"] == "open" and d["final_gate"]["pass"] is False for d in items)


def test_font_rows_same_only_for_identical_verdict(reports):
    """caption.font: typography.identify_many against a ceiling measured for THIS output's encode
    settings (x264 SEI: crf 18, veryfast); 'same' only for the verdict identical.  The REQUIRED rows are per role
    (pooled over every rest-frame crop of the role); per-caption rows are informational (not gate-required)."""
    for ep, rep in reports.items():
        fr = [r for r in rows(rep, "caption.font") if not r["row_id"].endswith("_ref")
              and not r["row_id"].startswith("caption.font:role_")]
        assert len(fr) == 5, ep
        assert all(r["required"] is False for r in fr), ep
        roles = {r["row_id"]: r for r in rows(rep, "caption.font") if r["row_id"].startswith("caption.font:role_")}
        assert set(roles) == {f"caption.font:role_{x}" for x in ("title", "situation", "speaker", "dialogue", "reaction")}
        for r in roles.values():
            assert r["required"] is True
            v = (r["observed"] or {}).get("verdict")
            assert (r["status"] == "same") == (v == "identical"), (ep, r["row_id"], r["status"], v, r["note"])
        for r in fr:
            v = (r["observed"] or {}).get("verdict")
            assert (r["status"] == "same") == (v == "identical"), (ep, r["row_id"], r["status"], v)
            if v is not None:
                cond = r["observed"]["conditions"]
                assert cond["crf"] == 18 and cond["x264_preset"] == "veryfast", cond
                assert cond["assumed"] is False
    # the synthetic renders use exactly the planned faces (production libass path) -> identical, per role
    good = reports["test-qa-good"]
    for role in ("title", "situation", "speaker", "dialogue", "reaction"):
        r = rows(good, row_id=f"caption.font:role_{role}")
        assert r["status"] == "same", (role, r["observed"], r["note"])
    for cid in ("t1", "s1", "k1", "d1", "r1"):
        r = rows(good, row_id=f"caption.font:{cid}")
        assert r["status"] == "same" and r["observed"]["verdict"] == "identical", (cid, r["observed"], r["note"])
        assert r["observed"]["top"] == r["expected"] or r["observed"]["top"].replace(" ", "") == r["expected"].replace(" ", "")


def test_faces_detected_with_clean_faces_at_most_1fps_while_captions_over_picture(reports):
    from shortkit.clean.faces import find_cascade

    if find_cascade("frontal") is None:
        pytest.skip("Haar cascades not fetched here (python -m shortkit clean fetch-models)")
    good = rows(reports["test-qa-good"], row_id="cover_up.faces:detector")
    bad = rows(reports["test-qa-bad"], row_id="cover_up.faces:detector")
    for r in (good, bad):
        assert "shortkit.clean.faces" in r["observed"]["detector"]
        ts = r["observed"]["sample_times"]
        assert all(b - a >= 1.0 - 1e-6 for a, b in zip(ts, ts[1:])), ts            # <= 1 fps
        assert len(ts) <= 8                                                          # 7.8 s video
    # GOOD: captions over the picture only 2.8-4.6 (speaker label) and 5.4-6.6 (reaction); no face covered
    assert all(2.8 <= t <= 4.6 or 5.4 <= t <= 6.6 for t in good["observed"]["sample_times"]), good["observed"]
    assert good["status"] == "same" and good["observed"]["faces_detected"] > 0
    # BAD: the situation caption moved over the two faces (0.8-2.3 s) -> found through the source frame
    assert bad["status"] == "different"
    hits = bad["observed"]["hits"]
    assert any(h["overlay"] == "s1" and 0.8 <= h["t"] <= 2.3 for h in hits), hits


# ----------------------------------------------------------------------------- report files / CLI
def test_report_files_and_sheet(reports):
    qa = ROOT / "episodes/test-qa-good/qa"
    md = (qa / "report.md").read_text(encoding="utf-8")
    assert "| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |" in md
    assert "못 잼 항목과 이유" in md
    from PIL import Image

    im = Image.open(qa / "compare_sheet.png")
    assert im.size[0] > 800 and im.size[1] > 500
    rep = json.loads((qa / "report.json").read_text())
    for r in rep["rows"]:
        for k in ("check_id", "item", "category", "reference", "expected", "observed", "tolerance", "status",
                  "intended_change", "change_ref", "evidence", "note"):
            assert k in r
        assert r["status"] in ("same", "different", "unmeasured")
    # stored paths are root-relative
    assert not rep["output"]["path"].startswith("/")
    assert all(not s.startswith("/") for s in rep["sheets"])
    # the preset keys QA read are saved for the registry (config.ACCESS_LOG_GLOBS collects qa/preset_access.json)
    acc = json.loads((qa / "preset_access.json").read_text())
    assert acc["preset_id"] == rep["preset_id"]
    assert any(c.startswith("shortkit/qa/") for callers in acc["reads"].values() for c in callers)
    assert "text.tone.register" in acc["reads"] and "audio.loudness.tolerance_lu" in acc["reads"]
    from shortkit.config import all_access_logs

    assert "episodes/test-qa-good/qa/preset_access.json" in all_access_logs()


def test_cli_gate_and_defects_list(reports):
    env = {"PYTHONPATH": str(ROOT), "PATH": "/usr/local/bin:/usr/bin:/bin"}
    g = subprocess.run([sys.executable, "-m", "shortkit", "qa", "gate", "--episode", "test-qa-bad"], cwd=ROOT,
                       capture_output=True, text=True, env=env)
    assert g.returncode == 1 and "불합격" in g.stdout
    d = subprocess.run([sys.executable, "-m", "shortkit", "qa", "defects", "list", "--episode", "test-qa-bad"], cwd=ROOT,
                       capture_output=True, text=True, env=env)
    assert d.returncode == 0 and "D001" in d.stdout


# ----------------------------------------------------------------------------- temp project root
@pytest.fixture()
def temp_root_with_episodes(reports, tmp_path, monkeypatch):
    """A throw-away project root: preset copy, the two synthetic episodes, test media symlinked."""
    import shutil

    root = tmp_path / "proj"
    root.mkdir()
    shutil.copy(ROOT / "shortkit.root", root / "shortkit.root")
    shutil.copytree(ROOT / "presets" / "joshuamagazine", root / "presets" / "joshuamagazine",
                    ignore=shutil.ignore_patterns("videos", "frames", "stems", "*.wav", "*.mp4"))
    (root / "assets" / "test").mkdir(parents=True)
    (root / "assets" / "test" / "generated").symlink_to(ROOT / "assets" / "test" / "generated")
    for ep in ("test-qa-good", "test-qa-bad"):
        src = ROOT / "episodes" / ep
        dst = root / "episodes" / ep
        (dst / "build").mkdir(parents=True)
        (dst / "output").mkdir()
        shutil.copy(src / "build" / "resolved.json", dst / "build" / "resolved.json")
        shutil.copy(src / "plan.yaml", dst / "plan.yaml")
        shutil.copy(src / "output" / f"{ep}.mp4", dst / "output" / f"{ep}.mp4")
        shutil.copytree(src / "qa" / "probes", dst / "qa" / "probes")
    monkeypatch.setenv("SHORTKIT_ROOT", str(root))
    return root


def test_sheet_with_reference_and_its_analysis(temp_root_with_episodes):
    """SYNTHETIC reference: the bad render plays the 'reference', with hand-written analysis files."""
    import shutil

    from PIL import Image

    from shortkit.qa import load_context
    from shortkit.qa.sheet import make_sheets
    from shortkit.util.jsonio import read_json, write_json

    root = temp_root_with_episodes
    (root / "ref").mkdir()
    shutil.copy(root / "episodes/test-qa-bad/output/test-qa-bad.mp4", root / "ref" / "refvid.mp4")
    an = root / "presets/joshuamagazine/analysis/refvid"
    write_json(an / "captions.json", {"video_id": "refvid", "resolution": [720, 1280], "items": [
        {"start": 0.5, "end": 2.0, "role": "situation", "text": "합성 레퍼런스 자막", "bbox": [100, 900, 500, 50],
         "motion_in": "pop"}]})
    write_json(an / "audio" / "sfx_events.json", {"video_id": "refvid", "events": [
        {"t": 0.8, "dur": 0.1, "type_id": "pop", "class": "edit_sfx", "gain_db": -6}]})
    ctx = load_context("test-qa-good", reference="ref/refvid.mp4")
    assert set(ctx.reference_analysis) == {"captions", "audio_sfx_events"}
    text = read_json(root / "episodes/test-qa-good/qa/probes/text.json")
    audio = read_json(root / "episodes/test-qa-good/qa/probes/audio.json")
    files = make_sheets(ctx, text, audio, seconds=4)
    assert files[0] == "episodes/test-qa-good/qa/compare_sheet.png" and len(files) == 2   # 8 s / 4 s pages
    im = Image.open(root / files[0])
    assert im.size[1] > 400


def test_defect_recheck_runs_same_check_on_other_episodes(temp_root_with_episodes):
    from shortkit.qa import defects, load_context

    ctx = load_context("test-qa-bad")
    fake = {"rows": [{"check_id": "audio.sfx.no_event", "row_id": "audio.sfx.no_event:all", "status": "different",
                      "required": True, "intended_change": False, "item": "사건 없는 효과음 0", "category": "사건 없는 효과음 0",
                      "expected": 0, "observed": {"count": 1}, "note": ""}],
            "gate": {"pass": False, "complete": False}, "output": {"sha256": "x"}}
    st = defects.sync(ctx, fake, recheck_others=True, quiet=True)
    assert st["new"] == 1
    d = defects.load("test-qa-bad")[0]
    rc = [c for c in d["recheck_same_cases"] if c["episode_id"] == "test-qa-good"]
    assert rc and rc[0]["verdict"] == "ok" and rc[0]["rows"] == {"audio.sfx.no_event:all": "same"}
