"""Fixtures for edit-core tests: a temporary project root with a copy of the preset and tiny
synthetic media (ffmpeg lavfi testsrc2 + sine; clearly synthetic, generated on the fly)."""
from __future__ import annotations
import sys as _sys_for_helpers
from pathlib import Path as _Path_for_helpers
_HERE_FOR_HELPERS = str(_Path_for_helpers(__file__).resolve().parent)  # bare-name helper modules of this test dir
if _HERE_FOR_HELPERS not in _sys_for_helpers.path:
    _sys_for_helpers.path.insert(0, _HERE_FOR_HELPERS)

import copy
import shutil
import subprocess
from pathlib import Path

import numpy as np
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
    # SYNTHETIC speech-like line (glottal pulses + vowel formants, syllables) at 1.0-2.6 s, and a SYNTHETIC chord bed
    from shortkit.util.media import write_wav

    sr = 48000
    sp = np.concatenate([np.zeros(sr), speech_like(1.6, sr), np.zeros(int(1.4 * sr))]).astype(np.float32)
    write_wav(d / "speech.wav", sp, sr)
    write_wav(d / "music.wav", chord_bed(4.0, sr), sr)
    for name, wav in (("src_speech.mp4", "speech.wav"), ("src_music.mp4", "music.wav")):
        _ff("-f", "lavfi", "-i", "testsrc2=s=320x180:r=30:d=4", "-i", d / wav, "-map", "0:v", "-map", "1:a",
            "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2", "-t", "4",
            d / name)
    return d


def speech_like(dur: float = 1.6, sr: int = 48000, seed: int = 3) -> "np.ndarray":
    """SYNTHETIC speech-like signal: glottal pulse train (f0 110-170 Hz contour) through vowel formants, syllables
    of 0.12-0.22 s with short gaps (syllabic modulation).  Not a recording of anybody."""
    from scipy.signal import lfilter

    rng = np.random.default_rng(seed)
    n = int(dur * sr)
    t = np.arange(n) / sr
    f0 = 140 + 30 * np.sin(2 * np.pi * 0.7 * t) + 8 * np.sin(2 * np.pi * 5.1 * t)
    ph = np.cumsum(f0 / sr)
    src = lfilter([1.0], [1.0, -0.97], (np.diff(np.floor(ph), prepend=0) > 0).astype(float))
    y, env = np.zeros(n), np.zeros(n)
    vowels = [(730, 1090, 2440), (270, 2290, 3010), (300, 870, 2240), (530, 1840, 2480)]
    pos, k = 0.0, 0
    while pos < dur:
        L, G = rng.uniform(0.12, 0.22), rng.uniform(0.05, 0.10)
        a, b = int(pos * sr), min(n, int((pos + L) * sr))
        if a >= n:
            break
        env[a:b] = np.hanning(b - a)
        out = np.zeros(b - a)
        for F, bw in zip(vowels[k % 4], (80, 100, 120)):
            r, th = np.exp(-np.pi * bw / sr), 2 * np.pi * F / sr
            out += lfilter([1 - r], [1, -2 * r * np.cos(th), r * r], src[a:b])
        y[a:b] = out
        pos, k = pos + L + G, k + 1
    y = y * env
    return (0.5 * y / (np.max(np.abs(y)) + 1e-9)).astype(np.float32)


def chord_bed(dur: float = 4.0, sr: int = 48000) -> "np.ndarray":
    """SYNTHETIC music bed: sustained triads (I-vi) + bass, like shortkit.testassets.synth_music."""
    t = np.arange(int(dur * sr)) / sr
    y = np.zeros_like(t)
    for i, chord in enumerate(([0, 4, 7], [-3, 0, 4])):
        m = (t >= i * dur / 2) & (t < (i + 1) * dur / 2)
        for semi in chord:
            f = 220.0 * 2 ** (semi / 12)
            y[m] += 0.1 * (np.sin(2 * np.pi * f * t[m]) + 0.3 * np.sin(4 * np.pi * f * t[m]))
        y[m] += 0.15 * np.sin(2 * np.pi * 110.0 * 2 ** (chord[0] / 12) * t[m])
    return (0.6 * y / np.max(np.abs(y))).astype(np.float32)


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
