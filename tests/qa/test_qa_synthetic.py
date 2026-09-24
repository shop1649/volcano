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
                "audio.silence:unexpected", "audio.original:kept0", "audio.original:off", "audio.sfx.no_event:all",
                "audio.sfx.unexplained:all", "audio.loudness:mix"):
        assert status(rep, rid) == "same", rid
    for fx in ("fx1", "fx2", "fx3", "fx4"):
        assert status(rep, f"audio.sfx.placement:{fx}") == "same", fx
        assert status(rep, f"audio.sfx.offset:{fx}") == "same", fx
        assert status(rep, f"audio.sfx.placement:{fx}:gain") == "same", fx
    sec = rows(rep, row_id="audio.bgm:section")["observed"]["section_start_s"]
    assert sec == pytest.approx(12.0, abs=0.01)


def test_good_residual_identity_cover_up(reports):
    rep = reports["test-qa-good"]
    assert [r["status"] for r in rows(rep, "clean.residual")] == ["same"]
    assert status(rep, "identity.forbidden_text:all") == "same"
    assert status(rep, "cover_up.protected:c1#0") == "same"


def test_good_gate_blockers_are_only_honest_unmeasured_items(reports):
    """With a provisional preset nothing may be called complete; in test mode the gate may only
    fail on items that genuinely cannot be measured here -- never on a false 'different'."""
    rep = reports["test-qa-good"]
    diff = [r["row_id"] for r in rep["rows"] if r["status"] == "different"]
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
    assert r["observed"]["section_start_s"] == pytest.approx(17.0, abs=0.01)


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
    assert [r["status"] for r in rows(rep, "clean.residual")] == ["different"]


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


def test_cli_gate_and_defects_list(reports):
    env = {"PYTHONPATH": str(ROOT), "PATH": "/usr/local/bin:/usr/bin:/bin"}
    g = subprocess.run([sys.executable, "-m", "shortkit", "qa", "gate", "--episode", "test-qa-bad"], cwd=ROOT,
                       capture_output=True, text=True, env=env)
    assert g.returncode == 1 and "불합격" in g.stdout
    d = subprocess.run([sys.executable, "-m", "shortkit", "qa", "defects", "list", "--episode", "test-qa-bad"], cwd=ROOT,
                       capture_output=True, text=True, env=env)
    assert d.returncode == 0 and "D001" in d.stdout
