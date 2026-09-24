"""Render smoke tests (short synthetic clips).  Canvas size / fps always come from the preset."""
from __future__ import annotations

import json

import numpy as np
import pytest
import yaml

from conftest import M, load_preset, write_plan


def _frame(path, t):
    from shortkit.util.media import read_frames

    return read_frames(path, [t])[0]


@pytest.mark.slow
def test_render_end_to_end(root, plan, capsys):
    from shortkit.cli import main
    from shortkit.util.media import probe, read_audio

    plan["timeline"][0]["zoom"] = {"center": [160, 90], "start": 0.3}
    plan["timeline"][0]["original_audio"] = {"keep": True, "reason": "테스트 음(사인파)", "ranges": [[1.0, 2.0]]}
    plan["decorations"] = [{"id": "d1", "kind": "circle", "start": 0.5, "end": 1.5,
                            "keyframes": [{"t": 0, "x": 300, "y": 900, "w": 120, "h": 120}]}]
    plan["bgm"]["silences"] = [{"start": 3.0, "end": 3.4, "reason": "정지 강조"}]
    write_plan(root, plan)
    assert main(["episode", "render", "t1"]) == 0, capsys.readouterr().out
    out = root / "episodes/t1/output/t1.mp4"
    pr = load_preset()
    info = probe(out)
    assert (info.width, info.height) == (pr.get("canvas.width"), pr.get("canvas.height"))
    assert info.fps == pytest.approx(pr.get("canvas.fps"))
    assert info.duration == pytest.approx(5.75, abs=0.1)
    rep = json.loads((root / "episodes/t1/build/render_report.json").read_text())
    assert rep["problems"] == []
    for f in ("mix.wav", "stems/bgm.wav", "stems/originals.wav", "stems/sfx.wav"):
        assert (root / "episodes/t1/build" / f).is_file()
    assert abs(rep["mp4_loudness"]["integrated_lufs"] - pr.get("audio.loudness.integrated_lufs")) <= 1.5
    assert rep["mp4_loudness"]["true_peak_db"] <= pr.get("audio.loudness.true_peak_db") + 0.5
    # geometry: background above the video region, video inside it, white flash at the s2 boundary (t=2.0)
    vr = pr.get("canvas.video_region")
    f1 = _frame(out, 1.0)
    assert f1[vr["y"] - 40, 20].max() < 30                      # black background
    assert f1[vr["y"] + vr["h"] // 2, vr["w"] // 2].max() > 40   # source picture inside the region
    ff = _frame(out, 2.0)
    assert ff[vr["y"] + 50: vr["y"] + vr["h"] - 50: 50, 50: vr["w"] - 50: 50].min() > 235
    # the circle decoration (red) is drawn at its keyframe position
    f07 = _frame(out, 0.7)
    ring = f07[900 - 60 + 4, 300]
    assert ring[0] > 180 and ring[1] < 90
    # audio: BGM silent inside the intentional silence, ducked only under the kept range
    b = read_audio(root / "episodes/t1/build/stems/bgm.wav", sr=48000, mono=True)
    o = read_audio(root / "episodes/t1/build/stems/originals.wav", sr=48000, mono=True)

    def rms(x, a, c):
        s = x[int(a * 48000):int(c * 48000)]
        return 20 * np.log10(np.sqrt(np.mean(s ** 2)) + 1e-12)

    assert rms(b, 3.1, 3.3) < -100
    # original sound only inside the kept range (source 1.0..2.0 -> output 0.5..1.5)
    assert rms(o, 0.1, 0.4) < -100 and rms(o, 0.7, 1.4) > -40 and rms(o, 1.7, 3.0) < -100
    duck = rms(b, 0.8, 1.3) - rms(b, 2.3, 2.8)
    assert duck == pytest.approx(-pr.get("audio.ducking.depth_db"), abs=1.5)
    assert abs(rms(b, 2.3, 2.8) - rms(b, 4.0, 5.0)) < 1.5              # no ducking around SFX / cuts


@pytest.mark.slow
def test_canvas_is_preset_driven(root, plan):
    """Changing the preset canvas (via requested_changes) changes the rendered MP4 accordingly."""
    from shortkit.edit.render import render
    from shortkit.edit.resolve import resolve_context, write_build
    from shortkit.util.media import probe

    rc = root / "presets/joshuamagazine/requested_changes.yaml"
    d = yaml.safe_load(rc.read_text()) or {}
    d["changes"] = {"canvas": {"width": 360, "height": 640, "fps": 15,
                               "video_region": {"x": 0, "y": 218, "w": 360, "h": 204, "fit": "contain"},
                               "background": {"type": "blur_source"}}}
    rc.write_text(yaml.safe_dump(d, allow_unicode=True))
    plan["captions"] = []
    plan["timeline"] = plan["timeline"][:1]
    plan["sfx"] = []
    # also exercise: slow motion + kept original via the vocals stem, BGM tempo pre-step, delogo, blur
    plan["timeline"][0]["speed"] = 0.5
    plan["sources"][0]["vocals_path"] = f"{M}/vocals.wav"
    plan["timeline"][0]["original_audio"] = {"keep": True, "reason": "대사", "stem": "vocals", "ranges": [[1.0, 1.5]]}
    plan["bgm"]["tempo_ratio"] = 1.1
    plan["sources"][0]["clean"]["delogo"] = [{"x": 10, "y": 10, "w": 60, "h": 30, "start": 0.0, "end": 2.0}]
    plan["sources"][0]["clean"]["blur"] = [{"x": 200, "y": 100, "w": 80, "h": 60}]
    write_plan(root, plan)
    pr = load_preset()
    ctx = resolve_context(plan, pr)
    assert not ctx.errors, ctx.errors
    r = write_build(ctx)
    assert "canvas.width" in r.requested_change_keys
    assert r.duration == pytest.approx(4.0)
    o = r.audio.originals[0]
    assert (o.out_start, o.out_end, o.path) == (pytest.approx(1.0), pytest.approx(2.0), f"{M}/vocals.wav")
    out = render(r)
    info = probe(out)
    assert (info.width, info.height, info.fps) == (360, 640, 15)
    fr = _frame(out, 1.0)
    # blurred source background (not flat black) above the contain-fitted region
    assert fr[100, 180].max() > 20
    rep = json.loads((root / "episodes/t1/build/render_report.json").read_text())
    assert rep["audio"]["bgm_tempo_method"] in ("rubberband", "atempo") and rep["problems"] == []
    from shortkit.util.media import read_audio

    orig = read_audio(root / "episodes/t1/build/stems/originals.wav", sr=48000, mono=True)
    seg = orig[int(1.1 * 48000):int(1.9 * 48000)]
    assert np.sqrt(np.mean(seg ** 2)) > 1e-3                         # slowed vocals present (atempo 0.5)
    assert np.sqrt(np.mean(orig[: int(0.9 * 48000)] ** 2)) < 1e-5   # nothing outside the kept range
    # blur op: the blurred source rect is smoother than the same spot unblurred in the source
    region_y = 218 + (204 - 202.5) / 2
    sx = 360 / 320
    y0, x0 = int(region_y + 105 * sx), int(205 * sx)
    patch = fr[y0:y0 + 40, x0:x0 + 60].astype(float)
    assert np.abs(np.diff(patch, axis=1)).mean() < 12


def test_production_gate_inside_render(root, plan):
    """render() itself refuses production edits with unmeasured preset keys / no approval."""
    from shortkit.edit.render import RenderError, render
    from shortkit.edit.resolve import resolve_context, write_build

    plan["mode"] = "production"
    plan["episode_index"] = 1
    write_plan(root, plan)
    r = write_build(resolve_context(plan, load_preset()))
    with pytest.raises(RenderError, match="미측정"):
        render(r)
    with pytest.raises(RenderError):
        render(r, allow_unmeasured=True)       # still refused: registry links missing / not approved
    assert not (root / "episodes/t1/output/t1.mp4").exists()
