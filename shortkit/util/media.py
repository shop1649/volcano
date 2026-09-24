"""Thin, dependency-free wrappers around ffmpeg / ffprobe.

All heavy media I/O goes through these helpers so that tool discovery (``FFMPEG`` /
``FFPROBE`` env overrides) and error reporting are consistent across modules.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np

FFMPEG = os.environ.get("FFMPEG", "ffmpeg")
FFPROBE = os.environ.get("FFPROBE", "ffprobe")


class MediaError(RuntimeError):
    pass


def which(tool: str) -> str | None:
    return shutil.which(tool)


def run(cmd: Sequence[str], *, check: bool = True, capture: bool = True, timeout: float | None = None,
        input_bytes: bytes | None = None) -> subprocess.CompletedProcess:
    """Run a command; on failure raise MediaError with the tail of stderr."""
    proc = subprocess.run(list(map(str, cmd)), input=input_bytes,
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.PIPE if capture else None, timeout=timeout)
    if check and proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", "replace")[-4000:]
        raise MediaError(f"command failed ({proc.returncode}): {' '.join(map(str, cmd))[:600]}\n{err}")
    return proc


def ffmpeg(args: Sequence[str], **kw) -> subprocess.CompletedProcess:
    return run([FFMPEG, "-hide_banner", "-nostdin", "-y", *map(str, args)], **kw)


@dataclass
class ProbeInfo:
    path: str
    duration: float
    width: int | None
    height: int | None
    fps: float | None
    nb_frames: int | None
    has_audio: bool
    audio_rate: int | None
    audio_channels: int | None
    vcodec: str | None
    acodec: str | None
    bit_rate: int | None
    raw: dict

    @property
    def resolution(self) -> tuple[int, int] | None:
        return (self.width, self.height) if self.width and self.height else None


def _ratio(s: str | None) -> float | None:
    if not s or s in ("0/0", "N/A"):
        return None
    if "/" in s:
        a, b = s.split("/")
        return float(a) / float(b) if float(b) else None
    return float(s)


def probe(path: str | os.PathLike) -> ProbeInfo:
    out = run([FFPROBE, "-v", "error", "-print_format", "json", "-show_format", "-show_streams", str(path)]).stdout
    d = json.loads(out)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), None)
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"
              and int(s.get("channels") or 0) > 0), None)
    fmt = d.get("format", {})
    dur = float(fmt.get("duration") or (v or {}).get("duration") or (a or {}).get("duration") or 0.0)
    nb = (v or {}).get("nb_frames")
    return ProbeInfo(
        path=str(path), duration=dur,
        width=int(v["width"]) if v else None, height=int(v["height"]) if v else None,
        fps=_ratio((v or {}).get("avg_frame_rate")) or _ratio((v or {}).get("r_frame_rate")),
        nb_frames=int(nb) if nb and str(nb).isdigit() else None,
        has_audio=a is not None,
        audio_rate=int(a["sample_rate"]) if a else None, audio_channels=int(a["channels"]) if a else None,
        vcodec=(v or {}).get("codec_name"), acodec=(a or {}).get("codec_name"),
        bit_rate=int(fmt["bit_rate"]) if fmt.get("bit_rate") else None, raw=d)


def read_audio(path: str | os.PathLike, sr: int = 22050, mono: bool = True, start: float | None = None,
               duration: float | None = None) -> np.ndarray:
    """Decode audio to float32 numpy (mono: shape [n]; stereo: [n, 2]). Silent array if no audio.

    Channel convention: mono -> stereo duplicates at unity gain; stereo -> mono is (L+R)/2."""
    info = probe(path)
    ch = 1 if mono else 2
    if not info.has_audio:
        dur = duration if duration is not None else max(0.0, info.duration - (start or 0.0))
        return np.zeros(int(round(dur * sr)) if mono else (int(round(dur * sr)), 2), dtype=np.float32)
    args = []
    if start is not None:
        args += ["-ss", f"{start:.6f}"]
    args += ["-i", str(path)]
    if duration is not None:
        args += ["-t", f"{duration:.6f}"]
    # Explicit channel convention (ffmpeg's defaults are -3 dB for mono->stereo and 0.707*(L+R) for
    # stereo->mono, which silently shifts levels):  a mono file on a stereo timeline plays at unity on
    # both channels, and a stereo file is downmixed as (L+R)/2.  QA measures with the same convention.
    src_ch = int(info.audio_channels or 1)
    if mono and src_ch == 2:
        args += ["-vn", "-af", "pan=mono|c0=0.5*c0+0.5*c1"]
    elif not mono and src_ch == 1:
        args += ["-vn", "-af", "pan=stereo|c0=c0|c1=c0"]
    else:
        args += ["-vn"]
    args += ["-ac", str(ch), "-ar", str(sr), "-f", "f32le", "-"]
    raw = run([FFMPEG, "-hide_banner", "-nostdin", "-v", "error", *args]).stdout
    a = np.frombuffer(raw, dtype=np.float32).copy()
    return a if mono else a.reshape(-1, 2)


def write_wav(path: str | os.PathLike, audio: np.ndarray, sr: int) -> None:
    """Write float32 [-1,1] audio (mono [n] or [n,ch]) as 16-bit PCM WAV via ffmpeg."""
    a = np.asarray(audio, dtype=np.float32)
    ch = 1 if a.ndim == 1 else a.shape[1]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    run([FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", str(ch),
         "-i", "-", "-c:a", "pcm_s16le", str(path)], input_bytes=np.clip(a, -1, 1).tobytes())


def read_frames(path: str | os.PathLike, times: Sequence[float], width: int | None = None) -> list[np.ndarray]:
    """Grab RGB frames (uint8 HxWx3) at the given timestamps (accurate seek)."""
    import cv2  # local import: optional heavy dep

    frames = []
    for t in times:
        vf = [] if width is None else ["-vf", f"scale={width}:-2"]
        raw = run([FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-ss", f"{max(0.0, t):.4f}", "-i", str(path),
                   "-frames:v", "1", *vf, "-f", "image2pipe", "-vcodec", "png", "-"]).stdout
        img = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise MediaError(f"no frame at t={t} in {path}")
        frames.append(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    return frames


def iter_frames(path: str | os.PathLike, fps: float | None = None, width: int | None = None,
                gray: bool = False, start: float | None = None, duration: float | None = None):
    """Stream decoded frames as numpy arrays: yields (t_seconds, frame).

    Frames are sampled at ``fps`` (or native rate).  Uses a raw pipe, so memory stays flat.
    """
    info = probe(path)
    w, h = info.width, info.height
    if not w or not h:
        raise MediaError(f"no video stream in {path}")
    filters = []
    if fps:
        filters.append(f"fps={fps}")
    if width:
        h = int(round(h * width / w / 2) * 2)
        w = width
        filters.append(f"scale={w}:{h}")
    pix = "gray" if gray else "rgb24"
    args = [FFMPEG, "-hide_banner", "-nostdin", "-v", "error"]
    if start is not None:
        args += ["-ss", f"{start:.6f}"]
    args += ["-i", str(path)]
    if duration is not None:
        args += ["-t", f"{duration:.6f}"]
    if filters:
        args += ["-vf", ",".join(filters)]
    args += ["-f", "rawvideo", "-pix_fmt", pix, "-"]
    proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    frame_bytes = w * h * (1 if gray else 3)
    rate = fps or info.fps or 30.0
    i = 0
    t0 = start or 0.0
    try:
        while True:
            buf = proc.stdout.read(frame_bytes)
            if len(buf) < frame_bytes:
                break
            arr = np.frombuffer(buf, np.uint8).reshape((h, w) if gray else (h, w, 3))
            yield t0 + i / rate, arr
            i += 1
    finally:
        proc.stdout.close()
        proc.wait()


def lufs(path: str | os.PathLike) -> dict:
    """EBU R128 integrated loudness / true peak / LRA of a file's audio via ffmpeg ebur128."""
    proc = run([FFMPEG, "-hide_banner", "-nostdin", "-i", str(path), "-vn", "-af", "ebur128=peak=true", "-f", "null", "-"],
               check=True)
    txt = (proc.stderr or b"").decode("utf-8", "replace")
    summary = txt[txt.rfind("Summary:"):]
    out = {"integrated_lufs": None, "lra": None, "true_peak_db": None}
    for line in summary.splitlines():
        line = line.strip()
        if line.startswith("I:"):
            out["integrated_lufs"] = _num(line)
        elif line.startswith("LRA:"):
            out["lra"] = _num(line)
        elif line.startswith("Peak:"):
            out["true_peak_db"] = _num(line)
    return out


def _num(line: str) -> float | None:
    for tok in line.replace(":", " ").split():
        try:
            return float(tok)
        except ValueError:
            continue
    return None
