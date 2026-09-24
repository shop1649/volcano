"""Synthetic / openly-licensed test assets for pipeline validation.

These assets exist ONLY to prove the pipeline works end-to-end on a machine (render, project
export, QA, analysis accuracy on known ground truth).  They are never production material and
never stand in for the reference channel's measurements.

    shortkit testassets synth              music bed, SFX set, Korean TTS lines (espeak-ng if present)
    shortkit testassets fetch-video        CC-BY 4.0 Intel sample clips (sha256-pinned)
    shortkit testassets dirty-source       a source clip with a fake watermark, burned-in English
                                           subtitles, embedded music + speech (for clean/audio tests)

Everything lands in assets/test/generated/ (git-ignored) and a manifest.json with sha256.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import urllib.request
from pathlib import Path

import numpy as np

from . import paths
from .util.hashing import sha256_file
from .util.jsonio import now_iso, read_json, write_json
from .util.media import ffmpeg, write_wav

OUT = "assets/test/generated"
SR = 48000

# CC-BY 4.0, https://github.com/intel-iot-devkit/sample-videos (commit 57978890822836f2b4743852f04f62fc511757e4)
INTEL_BASE = "https://github.com/intel-iot-devkit/sample-videos/raw/master/"
TEST_VIDEOS = {
    "classroom.mp4": "a69bd5e39ff0e74286d13bcbfdadddd307b85decd2d9853db7518e0028785e31",
    "head-pose-face-detection-female-and-male.mp4": "650166430c4bf9ddc470ac17a86d1fcbd6d76c64e60ed73675fdc6b3e3d3af38",
    "face-demographics-walking-and-pause.mp4": "d88ab9aa03634f66f8815db3dc940e1cdd80b098440effb20882e814fd206bf5",
    "people-detection.mp4": "18ffe8672d741e3e29c9d891d22c59d453720b086c25b35c88b393d55f92f693",
}
TEST_VIDEO_LICENSE = "CC BY 4.0 — Intel Corporation, intel-iot-devkit/sample-videos"

TTS_LINES = {
    "speech_01": "잠깐만요, 이거 진짜예요?",
    "speech_02": "저기 봐, 들어온다!",
    "speech_03": "아니 이게 무슨 일이야",
}


# ----------------------------------------------------------------------------- synthesis
def _env(n: int, a: float, d: float, sr: int = SR) -> np.ndarray:
    t = np.arange(n) / sr
    return np.minimum(1.0, t / max(a, 1e-4)) * np.exp(-t / max(d, 1e-4))


def synth_music(seconds: float = 60.0, bpm: float = 120.0, seed: int = 7, key_shift: int = 0) -> np.ndarray:
    """Deterministic music-like bed: chords + bass + kick/hat. Stereo float32."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    out = np.zeros(n, np.float32)
    beat = 60.0 / bpm
    prog = [[0, 4, 7], [-3, 0, 4], [-7, -3, 0], [-5, -1, 2]]  # I vi IV V (semitones from A4-ish)
    base = 220.0 * 2 ** (key_shift / 12)
    bar = 4 * beat
    t_all = np.arange(n) / SR
    for bi in range(int(seconds / bar) + 1):
        ch = prog[bi % 4]
        s0 = int(bi * bar * SR)
        s1 = min(n, int((bi + 1) * bar * SR))
        if s0 >= n:
            break
        tt = t_all[s0:s1] - bi * bar
        seg = np.zeros(s1 - s0, np.float32)
        for semi in ch:
            f = base * 2 ** (semi / 12)
            seg += 0.06 * (np.sin(2 * np.pi * f * tt) + 0.3 * np.sin(2 * np.pi * 2 * f * tt))
        fb = base / 2 * 2 ** (ch[0] / 12)
        seg += 0.12 * np.sin(2 * np.pi * fb * tt) * (0.6 + 0.4 * np.cos(2 * np.pi * tt / beat))
        out[s0:s1] += seg
    for k in range(int(seconds / beat)):
        s = int(k * beat * SR)
        if s >= n:
            break
        L = min(int(0.25 * SR), n - s)
        tt = np.arange(L) / SR
        kick = np.sin(2 * np.pi * (50 + 80 * np.exp(-tt * 30)) * tt) * np.exp(-tt * 12)
        out[s:s + L] += 0.35 * kick.astype(np.float32)
        h = s + int(beat * SR / 2)
        if h < n:
            L2 = min(int(0.05 * SR), n - h)
            out[h:h + L2] += 0.05 * rng.standard_normal(L2).astype(np.float32) * _env(L2, 0.001, 0.015)
    out /= max(1e-6, float(np.max(np.abs(out)))) / 0.8
    return np.stack([out, np.roll(out, 240)], axis=1).astype(np.float32)


def synth_sfx() -> dict[str, np.ndarray]:
    rng = np.random.default_rng(11)
    s: dict[str, np.ndarray] = {}

    def T(sec):
        return np.arange(int(sec * SR)) / SR

    t = T(0.45)
    noise = rng.standard_normal(t.size)
    sweep = np.cumsum(np.interp(t, [0, 0.45], [300, 5000])) / SR
    s["whoosh"] = (noise * np.sin(2 * np.pi * sweep) ** 2 * np.hanning(t.size)) * 0.6
    t = T(0.12)
    s["pop"] = np.sin(2 * np.pi * (900 - 3000 * t) * t) * _env(t.size, 0.002, 0.03) * 0.9
    t = T(1.2)
    s["ding"] = (np.sin(2 * np.pi * 1318.5 * t) + 0.4 * np.sin(2 * np.pi * 2637 * t)) * _env(t.size, 0.003, 0.35) * 0.5
    t = T(1.0)
    s["boom"] = (np.sin(2 * np.pi * (40 + 60 * np.exp(-t * 6)) * t) * _env(t.size, 0.005, 0.3)
                 + 0.2 * rng.standard_normal(t.size) * _env(t.size, 0.001, 0.08)) * 0.9
    t = T(1.5)
    s["riser"] = np.sin(2 * np.pi * np.cumsum(np.interp(t, [0, 1.5], [200, 1600])) / SR) * (t / 1.5) ** 2 * 0.5
    t = T(0.08)
    s["click"] = rng.standard_normal(t.size) * _env(t.size, 0.0005, 0.01) * 0.8
    t = T(0.6)
    s["boing"] = np.sin(2 * np.pi * (220 + 80 * np.sin(2 * np.pi * 12 * t)) * t) * _env(t.size, 0.002, 0.25) * 0.6
    t = T(0.5)
    s["scratch"] = np.sin(2 * np.pi * np.cumsum(np.interp(t, [0, .15, .3, .5], [900, 200, 1200, 150])) / SR) \
        * rng.uniform(0.5, 1, t.size) * np.hanning(t.size) * 0.6
    return {k: v.astype(np.float32) for k, v in s.items()}


def tts(text: str, out_wav: Path) -> bool:
    exe = shutil.which("espeak-ng") or shutil.which("espeak")
    if not exe:
        return False
    tmp = out_wav.with_suffix(".raw.wav")
    subprocess.run([exe, "-v", "ko", "-s", "165", "-w", str(tmp), text], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ffmpeg(["-i", tmp, "-ar", str(SR), "-ac", "1", out_wav])
    tmp.unlink(missing_ok=True)
    return True


def fake_speech(seconds: float, seed: int) -> np.ndarray:
    """Formant-ish voiced bursts used when no TTS engine exists (clearly not real speech)."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    t = np.arange(n) / SR
    f0 = 140 + 30 * np.sin(2 * np.pi * 3 * t)
    ph = np.cumsum(2 * np.pi * f0 / SR)
    x = sum(np.sin(k * ph) / k for k in range(1, 12))
    sy = (np.sin(2 * np.pi * 4.5 * t + rng.uniform(0, 6)) > -0.2).astype(float)
    return (0.3 * x * sy * np.hanning(n)).astype(np.float32)


# ----------------------------------------------------------------------------- commands
def cmd_synth(args) -> int:
    out = paths.ensure_dir(OUT)
    man = read_json(out / "manifest.json", {}) or {}
    write_wav(out / "music_bed_a.wav", synth_music(60, 120, 7, 0), SR)
    write_wav(out / "music_bed_b.wav", synth_music(60, 96, 3, 5), SR)
    # "sped-up version" of bed A, to test version/tempo discrimination
    ffmpeg(["-i", out / "music_bed_a.wav", "-af", "atempo=1.1", out / "music_bed_a_x1.1.wav"])
    sdir = paths.ensure_dir(f"{OUT}/sfx")
    for k, v in synth_sfx().items():
        write_wav(sdir / f"{k}.wav", v, SR)
    used_tts = False
    for k, line in TTS_LINES.items():
        wav = out / f"{k}.wav"
        if tts(line, wav):
            used_tts = True
        else:
            write_wav(wav, fake_speech(2.0, hash(k) % 1000), SR)
    files = {}
    for p in sorted(out.rglob("*.wav")):
        files[paths.relp(p)] = sha256_file(p)
    man.update({"generated_at": now_iso(), "synth_files": files, "tts_engine": "espeak-ng" if used_tts else "none(fake)",
                "tts_lines": TTS_LINES, "license": "generated by shortkit (no third-party content)"})
    write_json(out / "manifest.json", man)
    print(f"synth: {len(files)} files -> {OUT}")
    return 0


def cmd_fetch_video(args) -> int:
    out = paths.ensure_dir(f"{OUT}/video")
    man = read_json(paths.absp(OUT) / "manifest.json", {}) or {}
    local = os.environ.get("SHORTKIT_TESTVIDEO_DIR") or args.local_dir
    got = {}
    for name, sha in TEST_VIDEOS.items():
        dst = out / name
        if dst.exists() and sha256_file(dst) == sha:
            got[name] = "cached"
            continue
        src = Path(local) / name if local else None
        try:
            if src and src.is_file():
                shutil.copyfile(src, dst)
                how = f"copied from local dir"
            else:
                urllib.request.urlretrieve(INTEL_BASE + name, dst)
                how = "downloaded"
        except Exception as e:  # network may be blocked: say so, don't pretend
            got[name] = f"FAILED: {e}"
            continue
        if sha256_file(dst) != sha:
            got[name] = "FAILED: sha256 mismatch (GitHub LFS pointer or blocked proxy page?)"
            dst.unlink(missing_ok=True)
            continue
        got[name] = how
    man.update({"test_videos": {n: {"sha256": TEST_VIDEOS[n], "status": s, "license": TEST_VIDEO_LICENSE,
                                    "url": INTEL_BASE + n} for n, s in got.items()}})
    write_json(paths.absp(OUT) / "manifest.json", man)
    for n, s in got.items():
        print(f"{n}: {s}")
    return 0 if all(not s.startswith("FAILED") for s in got.values()) else 1


def make_dirty_source(src_video: Path, dst: Path, seconds: float = 20.0) -> dict:
    """Source clip with: fake corner watermark (top-left), burned-in English subtitles (bottom),
    embedded music bed + a speech line.  Returns ground truth for clean/audio tests."""
    gen = paths.absp(OUT)
    music = gen / "music_bed_b.wav"
    speech = gen / "speech_01.wav"
    if not music.exists() or not speech.exists():
        raise FileNotFoundError("run `shortkit testassets synth` first")
    font = _any_font()
    wm = {"x": 16, "y": 14, "w": 190, "h": 44, "text": "@fake_repost"}
    sub = {"y_from_bottom": 40, "text": "WAIT FOR IT...", "start": 2.0, "end": 6.0}
    draw = (f"drawbox=x={wm['x']}:y={wm['y']}:w={wm['w']}:h={wm['h']}:color=black@0.55:t=fill,"
            f"drawtext=fontfile='{font}':text='{wm['text']}':x={wm['x'] + 10}:y={wm['y'] + 8}:fontsize=26:fontcolor=white,"
            f"drawtext=fontfile='{font}':text='{sub['text']}':x=(w-text_w)/2:y=h-{sub['y_from_bottom']}-text_h:"
            f"fontsize=34:fontcolor=white:borderw=3:bordercolor=black:enable='between(t,{sub['start']},{sub['end']})'")
    speech_at = 8.0
    ffmpeg(["-t", f"{seconds}", "-i", src_video, "-i", music, "-i", speech,
            "-filter_complex",
            f"[0:v]{draw},format=yuv420p[v];[1:a]volume=0.5[m];[2:a]adelay={int(speech_at * 1000)}|{int(speech_at * 1000)},volume=1.0[s];"
            f"[m][s]amix=inputs=2:normalize=0:duration=first[a]",
            "-map", "[v]", "-map", "[a]", "-t", f"{seconds}", "-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
            "-c:a", "aac", "-b:a", "160k", "-ar", str(SR), dst])
    return {"watermark": wm, "subtitle": sub, "speech": {"file": paths.relp(speech), "start": speech_at},
            "music": {"file": paths.relp(music), "gain": 0.5}, "base_video": src_video.name}


def cmd_dirty(args) -> int:
    vid = paths.absp(f"{OUT}/video/{args.video}")
    if not vid.exists():
        print(f"missing {vid}; run `shortkit testassets fetch-video` first")
        return 1
    dst = paths.absp(f"{OUT}/dirty_source.mp4")
    gt = make_dirty_source(vid, dst, args.seconds)
    gt["sha256"] = sha256_file(dst)
    write_json(paths.absp(f"{OUT}/dirty_source.truth.json"), gt)
    print(f"dirty source -> {paths.relp(dst)}")
    return 0


def _any_font() -> str:
    for c in ["/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/Library/Fonts/Arial Bold.ttf",
              "C:/Windows/Fonts/arialbd.ttf"]:
        if Path(c).exists():
            return c
    try:
        out = subprocess.run(["fc-match", "-f", "%{file}", "sans:bold"], capture_output=True, text=True).stdout
        if out:
            return out
    except FileNotFoundError:
        pass
    raise FileNotFoundError("no usable font for drawtext")


def register(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("synth")
    s.set_defaults(func=cmd_synth)
    f = sub.add_parser("fetch-video")
    f.add_argument("--local-dir", default=None, help="이미 받아 둔 Intel sample-videos 폴더")
    f.set_defaults(func=cmd_fetch_video)
    d = sub.add_parser("dirty-source")
    d.add_argument("--video", default="classroom.mp4")
    d.add_argument("--seconds", type=float, default=20.0)
    d.set_defaults(func=cmd_dirty)
