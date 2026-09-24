"""CLI registration and real runs of the audio sub-commands (temp project, SYNTHETIC media)."""
from __future__ import annotations

import argparse
import shutil

import pytest

import synthref as S
from shortkit.reference import audio_cli

REPO = S.REPO
CMDS = {"separate", "bgm-identify", "bgm-align", "original", "sfx-events", "sfx-catalog", "sfx-map", "audio-analyze",
        "audio-measure"}


def test_register_adds_all_commands():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    audio_cli.register(sub)
    assert CMDS <= set(sub.choices)


def test_real_state_commands(tmp_project, capsys):
    """Real preset files (copied into a temp root): no reference media, no libraries."""
    for f in ("sfx_catalog.json", "sfx_map.yaml"):
        shutil.copy(REPO / "presets/joshuamagazine" / f, tmp_project / "presets/joshuamagazine" / f)
    assert audio_cli.main(["sfx-catalog"]) == 0
    assert audio_cli.main(["sfx-map"]) == 0
    assert audio_cli.main(["bgm-identify", "--video", "notdownloaded"]) == 0
    assert audio_cli.main(["separate", "--video", "notdownloaded"]) == 3
    out = capsys.readouterr().out
    assert "못 잼" in out and "미제공" in out
    assert audio_cli.main(["audio-measure"]) == 0                # no reference video: every item 못 잼 + blocker
    out = capsys.readouterr().out
    for key in ("audio.loudness.integrated_lufs", "audio.bgm.loop", "audio.original.keep_gain_db",
                "audio.original.fade_s", "audio.silence.fade_s", "audio.sfx.gain_db_default"):
        assert key in out
    assert "측정됨" not in out


@pytest.mark.slow
def test_audio_analyze_chain(project_env, capsys):
    assert audio_cli.main(["audio-analyze", "--video", "synv3"]) == 0          # demucs fails -> cached oracle stems
    out = capsys.readouterr().out
    assert "bed_b" in out and "덕킹 있다" in out
    ref = project_env["root"] / "presets/joshuamagazine/reference/videos/synv2.wav"
    assert audio_cli.main(["bgm-align", "--ref", str(ref), "--clean", str(project_env["lib"]["bed_a.wav"]),
                           "--out", str(project_env["root"] / "align.json")]) == 0
    assert "시작 20.000" in capsys.readouterr().out
