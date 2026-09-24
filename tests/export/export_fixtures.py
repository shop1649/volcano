"""Helpers for the export tests: a temporary project root, a hand-built ResolvedEdit and an
INDEPENDENT reference master renderer (numpy compositor + ffmpeg/libass), written from the IR
semantics documented in shortkit/edit/ir.py and shortkit/edit/render.py, without importing the
exporter or the production renderer.

All media are the repository's test assets (assets/test/generated): CC-BY Intel sample clips,
the generated "dirty" source (fake watermark + burned subtitle) and synthetic music / SFX /
espeak-ng Korean TTS.  Nothing here is production material.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
GEN = REPO / "assets" / "test" / "generated"
MEDIA = ["dirty_source.mp4", "video/people-detection.mp4", "video/classroom.mp4", "music_bed_a.wav",
         "sfx/whoosh.wav", "speech_02.wav"]


def have_media() -> bool:
    return all((GEN / m).is_file() for m in MEDIA)


def make_root(base: Path) -> Path:
    root = base / "proj"
    root.mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "shortkit.root", root / "shortkit.root")
    for m in MEDIA:
        dst = root / "assets" / "test" / "generated" / m
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists():
            shutil.copy(GEN / m, dst)
    return root


# ----------------------------------------------------------------------------- IR
def build_resolved(episode_id: str = "test-export-001", *, W: int = 360, H: int = 640, fps: float = 30.0,
                   bgm_tempo: float = 1.0):
    """3 clips (crop+delogo+zoom / flash+freeze / crossfade+speed+off-grid zoom), captions,
    one decoration, BGM with ducking under one kept original line, one SFX."""
    from shortkit.edit.ir import (AudioPlan, Bgm, CaptionBox, Clip, Decoration, Freeze, OriginalAudio, Rect,
                                  ResolvedEdit, SfxPlacement, TimedRect, Transition, Zoom)

    region = Rect(0.0, round(656 * H / 1920), float(W), round(608 * H / 1920))
    g = "assets/test/generated"
    clips = [
        Clip(id="c1", source_id="dirty", source_path=f"{g}/dirty_source.mp4", src_in=0.5, src_out=2.5, speed=1.0,
             out_start=0.0, out_end=2.0, region=region, fit="cover", src_size=(1920, 1080),
             crop=Rect(0.0, 0.0, 1920.0, 1000.0),
             delogo=[TimedRect(16, 14, 190, 44, None, None, "fake watermark @fake_repost")],
             zoom=Zoom(1.0, 1.3, (960.0, 500.0), 0.5, 0.5, "out"), purpose="hook"),
        Clip(id="c2", source_id="people", source_path=f"{g}/video/people-detection.mp4", src_in=3.0, src_out=4.5,
             speed=1.0, out_start=2.0, out_end=4.1, region=region, fit="cover", src_size=(768, 432),
             freeze=Freeze(src_t=3.5, out_start=2.5, hold=0.6),
             transition_in=Transition("flash", 0.2, "#FFFFFF"), purpose="build"),
        Clip(id="c3", source_id="classroom", source_path=f"{g}/video/classroom.mp4", src_in=10.0, src_out=13.0,
             speed=1.5, out_start=3.7, out_end=5.7, region=region, fit="cover", src_size=(1920, 1080),
             zoom=Zoom(1.0, 1.2, (1400.0, 400.0), 0.25, 0.6, "inout"),
             transition_in=Transition("crossfade", 0.4, None), purpose="reveal"),
    ]
    duration = 5.7

    def cap(cid, role, text, start, end, y, size):
        return CaptionBox(id=cid, role=role, text=text, lines=[text], start=start, end=end, anchor=(W / 2, y),
                          align="center", valign="middle", bbox=Rect(W * 0.1, y - size, W * 0.8, size * 2),
                          font_name="Noto Sans CJK KR Black", font_file=None, size_px=size, color="#FFFFFF",
                          highlight=[], highlight_color="#FFE400", outline_px=2, outline_color="#000000",
                          shadow_px=0, box={"enabled": False}, motion_in={"type": "none", "dur_s": 0.0},
                          motion_out={"type": "none", "dur_s": 0.0},
                          grounding={"note": "synthetic test caption"})

    captions = [cap("t1", "title", "테스트 제목", 0.0, duration, 110, 28),
                cap("s1", "situation", "문이 열린다", 0.5, 3.0, 477, 22)]
    decorations = [Decoration(id="d1", kind="circle", start=1.0, end=2.0,
                              keyframes=[{"t": 1.0, "x": 150, "y": 280, "w": 60, "h": 60, "rotation": 0}],
                              blink_hz=0.0, style={"color": "#FF2A2A", "stroke_px": 4})]
    env = [(0.0, 0.0), (2.12, 0.0), (2.2, -10.0), (4.2, -10.0), (4.5, 0.0), (duration, 0.0)]
    bgm = Bgm(path=f"{g}/music_bed_a.wav", track_id=None, section_start_s=5.0, tempo_ratio=bgm_tempo, gain_db=-18.0,
              fade_in_s=0.0, fade_out_s=0.8, envelope=env, silences=[], duck_ranges=[(2.2, 4.2)])
    audio = AudioPlan(sample_rate=48000, target_lufs=-14.0, true_peak_db=-1.5, bgm=bgm,
                      originals=[OriginalAudio(clip_id="c2", path=f"{g}/speech_02.wav", stem="vocals", src_start=0.0,
                                               src_end=2.0, out_start=2.2, out_end=4.2, speed=1.0, gain_db=0.0,
                                               fade_s=0.04, reason="synthetic kept line")],
                      sfx=[SfxPlacement(id="x1", type="whoosh_a", path=f"{g}/sfx/whoosh.wav", t=2.05, gain_db=-6.0,
                                        event_t=2.1, event_desc="사람이 화면에 들어옴", emotion="surprise",
                                        map_status="have")])
    build = f"episodes/{episode_id}/build"
    return ResolvedEdit(schema="shortkit.resolved/1", episode_id=episode_id, preset_id="joshuamagazine-v1",
                        preset_name="joshuamagazine", format_id="UNCLASSIFIED", mode="test",
                        canvas={"width": W, "height": H, "fps": fps,
                                "background": {"type": "color", "color": "#000000", "blur_sigma": 30},
                                "video_region": {"x": region.x, "y": region.y, "w": region.w, "h": region.h,
                                                 "fit": "cover"}},
                        duration=duration, clips=clips, captions=captions, decorations=decorations,
                        ass_path=f"{build}/captions.ass", fonts_dir=None, audio=audio,
                        output_path=f"episodes/{episode_id}/output/{episode_id}.mp4")


def write_ass(root: Path, r) -> Path:
    """Minimal ASS (same conventions as shortkit.edit.captions: PlayRes = canvas, \\an5\\pos)."""
    W, H = int(r.canvas["width"]), int(r.canvas["height"])

    def ts(t):
        cs = int(round(t * 100))
        return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"

    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2",
             "ScaledBorderAndShadow: yes", "YCbCr Matrix: None", "", "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
             "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
             "MarginL, MarginR, MarginV, Encoding"]
    for c in r.captions:
        lines.append(f"Style: {c.role},{c.font_name},{c.size_px:g},&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,"
                     f"900,0,0,0,100,100,0,0,1,{c.outline_px:g},0,5,0,0,0,1")
    lines.append("Style: deco,Noto Sans CJK KR Black,20,&H002A2AFF,&H002A2AFF,&H00FFFFFF,&H00000000,0,0,0,0,100,100,"
                 "0,0,1,0,0,7,0,0,0,1")
    lines += ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for c in r.captions:
        lines.append(f"Dialogue: 1,{ts(c.start)},{ts(c.end)},{c.role},,0,0,0,,"
                     f"{{\\an5\\pos({c.anchor[0]:g},{c.anchor[1]:g})}}{c.text}")
    for d in r.decorations:
        k = d.keyframes[0]
        x, y, w, h = k["x"], k["y"], k["w"], k["h"]
        ring = (f"m {w / 2:g} 0 b {w:g} 0 {w:g} {h:g} {w / 2:g} {h:g} b 0 {h:g} 0 0 {w / 2:g} 0 "
                f"m {w / 2:g} 4 b 4 4 4 {h - 4:g} {w / 2:g} {h - 4:g} b {w - 4:g} {h - 4:g} {w - 4:g} 4 {w / 2:g} 4")
        lines.append(f"Dialogue: 2,{ts(d.start)},{ts(d.end)},deco,,0,0,0,,{{\\an7\\pos({x - w / 2:g},{y - h / 2:g})"
                     f"\\bord0\\shad0\\1c&H2A2AFF&\\p1}}{ring}{{\\p0}}")
    out = root / r.ass_path
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


# ----------------------------------------------------------------------------- reference master
def _ease(p, kind):
    p = min(1.0, max(0.0, p))
    if kind == "in":
        return p ** 3
    if kind == "out":
        return 1 - (1 - p) ** 3
    if kind == "inout":
        return 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2
    return p


def _src_time(c, u):
    move = (c.src_out - c.src_in) / c.speed
    f = c.freeze
    if f is None:
        s = c.src_in + min(max(u, 0.0), move) * c.speed
    else:
        fl = f.out_start - c.out_start
        if u < fl:
            s = c.src_in + max(u, 0.0) * c.speed
        elif u < fl + f.hold:
            s = f.src_t
        else:
            s = min(c.src_out, f.src_t + (u - fl - f.hold) * c.speed)
    return min(s, c.src_out - 0.002)


def _placement(c, u):
    """(scale, tx, ty) region-local mapping of cropped-source px, zoom about the clamped anchor."""
    ex, ey, ew, eh = (c.crop.x, c.crop.y, c.crop.w, c.crop.h) if c.crop else (0, 0, c.src_size[0], c.src_size[1])
    R = c.region
    b = max(R.w / ew, R.h / eh) if c.fit == "cover" else min(R.w / ew, R.h / eh)
    ox, oy = (R.w - ew * b) / 2, (R.h - eh * b) / 2
    z = 1.0
    if c.zoom:
        zz = c.zoom
        z = zz.scale_from + (zz.scale_to - zz.scale_from) * _ease((u - zz.start) / zz.dur, zz.ease) if zz.dur > 0 \
            else (zz.scale_to if u >= zz.start else zz.scale_from)
    if z == 1.0:
        return b, ox, oy
    px = min(max(ox + b * (c.zoom.center_src[0] - ex), 0), R.w)
    py = min(max(oy + b * (c.zoom.center_src[1] - ey), 0), R.h)
    return z * b, px * (1 - z) + z * ox, py * (1 - z) + z * oy


class _Source:
    def __init__(self, root: Path, c):
        import cv2  # noqa: F401

        src = root / c.source_path
        info = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                          "stream=r_frame_rate", "-of", "json", str(src)],
                                         capture_output=True, check=True).stdout)
        a, b_ = info["streams"][0]["r_frame_rate"].split("/")
        info2 = json.loads(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                                           "stream=color_space", "-of", "json", str(src)],
                                          capture_output=True, check=True).stdout)["streams"][0]
        self.fps = float(a) / float(b_)
        ex, ey, ew, eh = (c.crop.x, c.crop.y, c.crop.w, c.crop.h) if c.crop else (0, 0, c.src_size[0], c.src_size[1])
        R = c.region
        b = max(R.w / ew, R.h / eh) if c.fit == "cover" else min(R.w / ew, R.h / eh)
        zmax = max(1.0, c.zoom.scale_to, c.zoom.scale_from) if c.zoom else 1.0
        k = min(1.0, 2 * b * zmax)
        self.w, self.h = max(2, int(round(round(ew) * k))), max(2, int(round(round(eh) * k)))
        self.kx, self.ky = self.w / ew, self.h / eh
        vf = []
        for d in c.delogo:
            en = ""
            if d.start is not None or d.end is not None:
                en = f":enable='between(t,{d.start or 0},{d.end if d.end is not None else 1e9})'"
            vf.append(f"delogo=x={int(d.x)}:y={int(d.y)}:w={int(d.w)}:h={int(d.h)}{en}")
        if c.crop:
            vf.append(f"crop={int(round(ew))}:{int(round(eh))}:{int(round(ex))}:{int(round(ey))}")
        # colour conventions of shortkit.edit.render: BT.709 for tagged-709 or untagged HD, else BT.601
        cs = info2.get("color_space") or ""
        mat = "bt709" if cs == "bt709" or (cs in ("", "unknown") and c.src_size[1] >= 720) else "bt601"
        vf.append(f"scale={self.w}:{self.h}:flags=area:in_color_matrix={mat}:in_range=auto:out_range=full")
        t_end = c.src_out + 0.2
        raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(src), "-t", f"{t_end:.3f}", "-an", "-vf", ",".join(vf),
                              "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], capture_output=True, check=True).stdout
        fb = self.w * self.h * 3
        n = len(raw) // fb
        first = max(0, int(math.floor((c.src_in - 0.2) * self.fps)))
        self.first = first
        self.frames = [np.frombuffer(raw[i * fb:(i + 1) * fb], np.uint8).reshape(self.h, self.w, 3)
                       for i in range(first, n)]

    def at(self, s):
        i = int(math.floor((s + 1e-3) * self.fps + 1e-9)) - self.first
        return self.frames[min(max(i, 0), len(self.frames) - 1)]


def _hex(h):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], np.float32)


def render_master(root: Path, r, out: Path) -> dict:
    """Master MP4 from the IR (independent of shortkit.edit.render / export_*). Returns loudness info."""
    import cv2

    from shortkit.util.media import lufs, read_audio, write_wav

    W, H, fps = int(r.canvas["width"]), int(r.canvas["height"]), float(r.canvas["fps"])
    N = int(round(r.duration * fps))
    bg = _hex(r.canvas["background"]["color"])
    srcs = {c.id: _Source(root, c) for c in r.clips}

    def clip_canvas(c, t):
        S = srcs[c.id]
        u = t - c.out_start
        fr = S.at(_src_time(c, u))
        canvas = np.empty((H, W, 3), np.float32)
        canvas[:] = bg
        R = c.region
        rx, ry, rw, rh = int(round(R.x)), int(round(R.y)), int(round(R.w)), int(round(R.h))
        sc, tx, ty = _placement(c, u)
        sx, sy = sc / S.kx, sc / S.ky
        M = np.array([[sx, 0, tx + 0.5 * sx - 0.5], [0, sy, ty + 0.5 * sy - 0.5]], np.float64)
        reg = cv2.warpAffine(fr, M, (rw, rh), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
        x0, x1, y0, y1 = tx, tx + sx * S.w, ty, ty + sy * S.h
        cx0, cx1 = max(0, math.ceil(x0 - 0.5)), min(rw, math.floor(x1 - 0.5) + 1)
        cy0, cy1 = max(0, math.ceil(y0 - 0.5)), min(rh, math.floor(y1 - 0.5) + 1)
        if cx1 > cx0 and cy1 > cy0:
            canvas[ry + cy0:ry + cy1, rx + cx0:rx + cx1] = reg[cy0:cy1, cx0:cx1]
        return canvas

    wd = out.parent
    wd.mkdir(parents=True, exist_ok=True)
    # ---- audio (numpy mix, linear fades, dB-linear envelope, loudness gain to target)
    sr = r.audio.sample_rate
    n = int(round(r.duration * sr))
    mix = np.zeros((n, 2), np.float32)
    b = r.audio.bgm
    x = read_audio(root / b.path, sr=sr, mono=False, start=b.section_start_s, duration=n / sr)[:n]
    t = np.arange(len(x)) / sr
    env_db = np.interp(t, [p[0] for p in b.envelope], [p[1] for p in b.envelope])
    g = 10 ** ((b.gain_db + env_db) / 20)
    fo = int(round(b.fade_out_s * sr))
    fade = np.ones(len(x))
    if fo:
        fade[len(x) - fo:] = np.linspace(1, 0, fo)
    mix[:len(x)] += x * (g * fade)[:, None]
    for o in r.audio.originals:
        y = read_audio(root / o.path, sr=sr, mono=False, start=o.src_start, duration=o.src_end - o.src_start)
        m = int(round((o.out_end - o.out_start) * sr))
        y = np.pad(y, ((0, max(0, m - len(y))), (0, 0)))[:m]
        fl = int(round(o.fade_s * sr))
        gg = np.ones(m) * 10 ** (o.gain_db / 20)
        if fl:
            gg[:fl] *= np.linspace(0, 1, fl, endpoint=False)
            gg[m - fl:] *= np.linspace(1, 0, fl)
        s0 = int(round(o.out_start * sr))
        mix[s0:s0 + m] += (y * gg[:, None])[:n - s0]
    for s in r.audio.sfx:
        y = read_audio(root / s.path, sr=sr, mono=False) * 10 ** (s.gain_db / 20)
        s0 = int(round(s.t * sr))
        e0 = min(n, s0 + len(y))
        mix[s0:e0] += y[:e0 - s0]
    pre_wav = wd / "master_pre.wav"
    write_wav(pre_wav, mix, sr)
    pre = lufs(pre_wav)["integrated_lufs"]
    gain_db = r.audio.target_lufs - pre
    mix *= 10 ** (gain_db / 20)
    mix_wav = wd / "master_mix.wav"
    write_wav(mix_wav, mix, sr)
    pre_wav.unlink()
    # ---- video
    ass = root / r.ass_path
    cmd = ["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-framerate",
           f"{fps:g}", "-i", "-", "-i", str(mix_wav), "-vf",
           f"subtitles=filename={ass.name},scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-t", f"{N / fps:.6f}", str(out.resolve())]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, cwd=str(ass.parent))
    for i in range(N):
        tt = i / fps
        act = [c for c in r.clips if c.out_start - 1e-6 <= tt < c.out_end - 1e-6] or [r.clips[-1]]
        if len(act) == 1:
            fr = clip_canvas(act[0], tt)
        else:
            a_, b_ = act[-2], act[-1]
            al = min(1.0, max(0.0, (tt - b_.out_start) / b_.transition_in.dur))
            fr = clip_canvas(a_, tt) * (1 - al) + clip_canvas(b_, tt) * al
        for c in r.clips:
            tr = c.transition_in
            if tr.type == "flash" and abs(tt - c.out_start) < tr.dur / 2:
                al = 1 - abs(tt - c.out_start) / (tr.dur / 2)
                R = c.region
                ry, rh = int(round(R.y)), int(round(R.h))
                rx, rw = int(round(R.x)), int(round(R.w))
                fr[ry:ry + rh, rx:rx + rw] = fr[ry:ry + rh, rx:rx + rw] * (1 - al) + _hex(tr.color or "#FFFFFF") * al
        proc.stdin.write(np.clip(fr + 0.5, 0, 255).astype(np.uint8).tobytes())
    proc.stdin.close()
    assert proc.wait() == 0
    mix_wav.unlink()
    return {"pre_lufs": pre, "norm_gain_db": round(gain_db, 3)}


def write_render_report(root: Path, r, loud: dict) -> Path:
    """build/render_report.json in the shape shortkit.edit.render writes (audio.norm_gain_db)."""
    p = root / "episodes" / r.episode_id / "build" / "render_report.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"schema": "shortkit.render_report/1", "episode_id": r.episode_id,
                             "note": "written by tests/export reference master (synthetic test)",
                             "audio": {"norm_gain_db": loud["norm_gain_db"], "limiter_max_reduction_db": 0.0}}),
                 encoding="utf-8")
    return p
