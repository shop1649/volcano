"""Fixtures for edit-core tests: a temporary project root with a copy of the preset and tiny
synthetic media (ffmpeg lavfi testsrc2 + sine; clearly synthetic, generated on the fly)."""
from __future__ import annotations

import copy
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
PRESET_FILES = ["preset.yaml", "formats.yaml", "sfx_catalog.json", "sfx_map.yaml", "requested_changes.yaml",
                "settings_registry.yaml"]


def _ff(*args):
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", *map(str, args)], check=True)


@pytest.fixture(scope="session")
def media(tmp_path_factory):
    """Synthetic media shared by all tests (never stored in the repo)."""
    d = tmp_path_factory.mktemp("edit_media")
    _ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=4", "-f", "lavfi", "-i", "sine=f=440:d=4:sample_rate=48000",
        "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", d / "src_a.mp4")
    _ff("-f", "lavfi", "-i", "testsrc=s=240x240:r=12:d=3", "-c:v", "libx264", "-preset", "ultrafast",
        "-pix_fmt", "yuv420p", d / "src_b.mp4")
    _ff("-f", "lavfi", "-i", "sine=f=220:d=12:sample_rate=48000", "-af", "volume=0.3", "-ac", "2", d / "bgm.wav")
    _ff("-f", "lavfi", "-i", "sine=f=1000:d=0.2:sample_rate=48000", "-ac", "1", d / "pop.wav")
    _ff("-f", "lavfi", "-i", "sine=f=300:d=4:sample_rate=48000", "-ac", "1", d / "vocals.wav")
    return d


@pytest.fixture
def root(tmp_path, monkeypatch, media):
    """Temporary project root (SHORTKIT_ROOT) with the preset copied and media placed inside."""
    r = tmp_path / "proj"
    r.mkdir()
    shutil.copy(REPO / "shortkit.root", r / "shortkit.root")
    pd = r / "presets" / "joshuamagazine"
    pd.mkdir(parents=True)
    for f in PRESET_FILES:
        if (REPO / "presets/joshuamagazine" / f).exists():
            shutil.copy(REPO / "presets/joshuamagazine" / f, pd / f)
    md = r / "assets/test/generated/edit_fixture"
    md.mkdir(parents=True)
    for f in media.iterdir():
        shutil.copy(f, md / f.name)
    (r / "warehouse").mkdir()
    (r / "episodes").mkdir()
    monkeypatch.setenv("SHORTKIT_ROOT", str(r))
    monkeypatch.chdir(r)
    return r


def sha(p: Path) -> str:
    import hashlib

    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


M = "assets/test/generated/edit_fixture"


def base_plan(root: Path, mode: str = "test") -> dict:
    """A valid 5.75 s plan (test mode) over the synthetic sources."""
    return {
        "schema": "shortkit.plan/1", "episode_id": "t1", "preset_id": "joshuamagazine-v1",
        "format_id": "UNCLASSIFIED", "mode": mode, "episode_index": 2,
        "cover": {"text": "테스트 제목", "frame_t": 0.0}, "title_candidates": ["가", "나", "다"],
        "sources": [
            {"id": "a", "path": f"{M}/src_a.mp4", "sha256": sha(root / M / "src_a.mp4"), "warehouse_id": None,
             "has_embedded_music": False, "vocals_path": None,
             "clean": {"crop": None, "delogo": [], "inpaint": [], "blur": []},
             "protected": [{"label": "얼굴", "x": 140, "y": 20, "w": 40, "h": 40}]},
            {"id": "b", "path": f"{M}/src_b.mp4", "sha256": sha(root / M / "src_b.mp4"), "warehouse_id": None,
             "has_embedded_music": False, "clean": {}, "protected": []},
        ],
        "timeline": [
            {"id": "s1", "source": "a", "src_in": 0.5, "src_out": 2.5, "purpose": "hook"},
            {"id": "s2", "source": "a", "src_in": 2.5, "src_out": 3.5, "freeze": {"at": "end", "hold": 0.5},
             "transition_in": {"type": "flash"}},
            {"id": "s3", "source": "b", "src_in": 0.0, "src_out": 2.5, "transition_in": {"type": "crossfade", "dur": 0.25}},
        ],
        "captions": [
            {"id": "c_t", "role": "title", "text": "테스트 제목", "start": 0.0, "end": 5.75},
            {"id": "c_s", "role": "situation", "text": "화면이 움직인다", "start": 0.2, "end": 2.0,
             "grounding": {"kind": "seen", "source": "a", "src_t": 1.0}},
        ],
        "decorations": [],
        "sfx": [{"id": "fx1", "type": "pop", "t": 1.0, "event": {"t": 1.1, "desc": "무언가 나타남", "kind": "appear"},
                 "file": f"{M}/pop.wav"}],
        "bgm": {"enabled": True, "path": f"{M}/bgm.wav", "section_start_s": 1.0, "silences": []},
    }


def write_plan(root: Path, plan: dict) -> Path:
    p = root / "episodes" / plan["episode_id"] / "plan.yaml"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(yaml.safe_dump(plan, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return p


def set_preset(root: Path, dotted: str, value) -> None:
    """Edit the temp root's preset.yaml (never the repo's)."""
    p = root / "presets/joshuamagazine/preset.yaml"
    d = yaml.safe_load(p.read_text(encoding="utf-8"))
    cur = d
    parts = dotted.split(".")
    for k in parts[:-1]:
        cur = cur[k]
    cur[parts[-1]] = value
    p.write_text(yaml.safe_dump(d, allow_unicode=True, sort_keys=False), encoding="utf-8")


def load_preset():
    from shortkit import config

    return config.load_preset("joshuamagazine")


def codes(issues, severity=None):
    return {i["code"] for i in issues if severity is None or i["severity"] == severity}


@pytest.fixture
def plan(root):
    return copy.deepcopy(base_plan(root))
