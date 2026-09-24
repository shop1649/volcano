"""Slow: render the exported MLT with melt and compare it with an independently rendered master.

Thresholds asserted here (documented in shortkit/edit/verify_project.py; defaults are looser):
  * verify() status == pass with the default thresholds (per-second SSIM >= 0.90, overall >= 0.95,
    per-second mean |diff| <= 10, audio envelope corr >= 0.90, per-second level diff <= 2 dB)
  * AND every second of THIS fixture: SSIM >= 0.95, mean |diff| <= 4, |level diff| <= 1 dB
    (measured on the build machine: SSIM 0.984-0.993, |diff| 0.5-2.4, level diff <= 0.26 dB).
The negative test proves the comparison catches a real edit error (zoom keyframes removed).
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from shortkit.edit import verify_project

pytestmark = [pytest.mark.slow,
              pytest.mark.skipif(verify_project.find_melt() is None, reason="melt not installed")]


def test_mlt_project_matches_master(root, resolved, fresh_project, master):
    from shortkit.edit import project_readme
    from shortkit.util.jsonio import read_json

    s = project_readme.export_project(resolved, verify=True)
    assert not s["errors"], s["errors"]
    v = read_json(fresh_project / "verify.json")
    assert v["status"] == "pass", v.get("why")
    assert v["melt"]["cmd"][:3] in (["xvfb-run", "-a", "melt"],) or v["melt"]["cmd"][0] == "melt"
    g = v["global"]
    assert g["frames_compared"] == g["frames_expected"] == 171
    assert g["ssim_overall"] >= 0.97 and g["audio_env_corr"] >= 0.98
    for row in v["rows"]:
        assert row["ssim_mean"] >= 0.95, row
        assert row["mad"] <= 4.0, row
        assert row["audio"] == "pass" and abs(row["level_diff_db"]) <= 1.0, row
    # loudness gain came from the master's build file, not a guess
    dec = read_json(fresh_project / "export_decisions.json")["mlt"]
    assert dec["loudness"]["gain_db"] == pytest.approx(master["loudness"]["norm_gain_db"], abs=1e-3)
    # nothing machine-specific stored
    for f in ("verify.json", "export_decisions.json", f"{resolved.episode_id}.mlt", "README.md"):
        t = (fresh_project / f).read_text(encoding="utf-8")
        assert str(root) not in t and "/usr/bin" not in t, f
    readme = (fresh_project / "README.md").read_text(encoding="utf-8")
    assert "**통과**" in readme and str(g["ssim_overall"]) in readme


def test_verify_detects_broken_zoom(root, resolved, fresh_project, master):
    from shortkit.edit import export_mlt

    out, _ = export_mlt.export_with_decisions(resolved, fresh_project)
    tree = ET.parse(out)
    for p in tree.getroot().iter("producer"):
        if p.get("id") == "c1_video_0":
            for f in p.findall("filter"):
                props = {q.get("name"): q for q in f.findall("property")}
                if props["mlt_service"].text == "affine":
                    props["transition.rect"].text = props["transition.rect"].text.split(";")[0].split("=")[1]
    broken = out.with_name("broken.mlt")
    tree.write(broken, encoding="utf-8", xml_declaration=True)          # same folder: captions.ass resolves
    v = verify_project.verify(resolved, master["path"], broken)
    assert v["status"] == "fail"
    rows = {r["sec"]: r for r in v["rows"]}
    assert rows[1]["video"] == "fail"                 # 1.0-2.0 s is held at 1.3x in the master
    assert all(rows[k]["video"] == "pass" for k in (3, 4, 5))


def test_loudness_gain_computed_by_melt_prepass_without_render_report(root, resolved, fresh_project, master,
                                                                      monkeypatch):
    from shortkit.edit import export_mlt

    monkeypatch.setattr(export_mlt, "load_render_report", lambda r: None)
    out, dec = export_mlt.export_with_decisions(resolved, fresh_project)
    lo = dec["loudness"]
    assert lo["source"] == "computed_melt_prepass" and lo["target_from"] == "master_mp4_rms_ratio"
    assert lo["gain_db"] == pytest.approx(master["loudness"]["norm_gain_db"], abs=1.0)


def test_tempo_bgm_and_blur_are_prerendered_and_declared(root, fresh_project, monkeypatch):
    """BGM tempo_ratio != 1 -> media/bgm_tempo_*.wav via render.tempo_stretch; a blur op ->
    media/<clip>_blur_*.mp4 used by the MLT pieces; both listed as baked in decisions/README."""
    import xml.etree.ElementTree as ET

    import export_fixtures as ef
    from shortkit.edit import export_mlt, project_readme
    from shortkit.edit.ir import TimedRect

    monkeypatch.setattr(export_mlt, "load_render_report", lambda r: None)
    r = ef.build_resolved(bgm_tempo=1.1)
    r.clips[2].blur = [TimedRect(1300, 300, 200, 200, 10.5, 11.5, "synthetic blur test")]
    ef.write_ass(root, r)
    out, dec = export_mlt.export_with_decisions(r, fresh_project, compute_loudness=False)
    kinds = {p["kind"]: p for p in dec["prerendered"]}
    assert "bgm_tempo" in kinds and kinds["bgm_tempo"]["tempo_ratio"] == 1.1
    assert kinds["bgm_tempo"]["method"] in ("rubberband", "atempo", "cached")
    assert "blur_intermediate" in kinds and (fresh_project / kinds["blur_intermediate"]["file"]).is_file()
    x = ET.parse(out).getroot()
    res = [q.text for q in x.iter("property") if q.get("name") == "resource"]
    assert any("media/bgm_tempo_" in t for t in res)
    assert any("media/c3_blur_" in t for t in res)
    bgm_entry = [e for pl in x.findall("playlist") for e in pl.findall("entry")
                 if any(q.text == "A1 BGM" for q in pl.findall("property"))][0]
    assert bgm_entry.get("in") == str(round(5.0 / 1.1 * 30))
    t = project_readme.write(r, fresh_project, {}).read_text(encoding="utf-8")
    assert "bgm_tempo_" in t and "_blur_" in t
