"""SYNTHETIC mock-reference videos with known ground truth (test fixture generator).

These videos imitate the *editing structure* of a Korean shorts channel (static title +
description on a colored background, footage in a band, timed captions with pop-in, a boxed
speaker label, a yellow quoted dialogue line, a big colored reaction pop, a digital zoom, a
freeze frame, a white flash, a crossfade and a 0.5x slow-motion ramp).  They are made from the
CC-BY Intel sample clips + libass captions and are NEVER reference-channel data.

The ground truth for text geometry is produced by rendering each caption event alone on a flat
gray still (same libass, same fonts) and measuring it with plain color thresholds, so the truth
does not depend on the analyzers under test.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np

GEN_VERSION = 7
W, H, FPS = 540, 960, 30
REGION = {"x": 0, "y": 300, "w": 540, "h": 304}
BG_HEX = "#1E2A5A"
DURATION = 9.0
FONT_BLACK = "Noto Sans CJK KR Black"
FONT_BOLD = "NotoSansCJKkr-Bold"   # PostScript name: libass cannot select "Noto Sans CJK KR Bold" by name


def _ass_color(hexstr: str, alpha: int = 0) -> str:
    h = hexstr.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _t(s: float) -> str:
    cs = int(round(s * 100))
    return f"{cs // 360000}:{(cs // 6000) % 60:02d}:{(cs // 100) % 60:02d}.{cs % 100:02d}"


# role, style, start, end, pos, text(with overrides), plain text, truth extras
EVENTS = [
    dict(id="title", role="title", style="Title", start=0.0, end=9.0, pos=(270, 150),
         text=r"오늘의 {\c&H00E4FF&}황당{\c&HFFFFFF&} 사건", plain="오늘의 황당 사건",
         size=40, color="#FFFFFF", highlight="#FFE400", outline=3, box=False, motion_in="none"),
    dict(id="desc", role="description", style="Desc", start=0.0, end=9.0, pos=(270, 215),
         text="교실에서 벌어진 일", plain="교실에서 벌어진 일",
         size=24, color="#DDDDDD", highlight=None, outline=2, box=False, motion_in="none"),
    dict(id="s1", role="situation", style="Sit", start=0.5, end=2.8, pos=(270, 700),
         text=r"{\fscx85\fscy85\t(0,150,\fscx100\fscy100)}학생들이 모여 있다", plain="학생들이 모여 있다",
         size=34, color="#FFFFFF", highlight=None, outline=3, box=False, motion_in="pop", motion_dur=0.15,
         scale_from=0.85),
    dict(id="s2", role="situation", style="Sit", start=3.1, end=5.4, pos=(270, 700),
         text=r"{\fscx85\fscy85\t(0,150,\fscx100\fscy100)}갑자기 누가\N들어온다", plain="갑자기 누가\n들어온다",
         size=34, color="#FFFFFF", highlight=None, outline=3, box=False, motion_in="pop", motion_dur=0.15,
         scale_from=0.85, lines=2),
    dict(id="spk", role="speaker", style="Spk", start=3.2, end=5.0, pos=(420, 360),
         text=r"{\fad(150,150)}선생님", plain="선생님",
         size=22, color="#FFFFFF", highlight=None, outline=None, box=True, box_color="#000000", box_alpha=0.6,
         motion_in="fade", motion_dur=0.15),
    dict(id="dlg", role="dialogue", style="Dlg", start=6.0, end=7.6, pos=(270, 700),
         text="“진짜 왔어?”", plain="“진짜 왔어?”",
         size=32, color="#FFE400", highlight=None, outline=3, box=False, motion_in="none"),
    dict(id="rx", role="reaction", style="Rx", start=8.1, end=8.9, pos=(270, 520),
         text=r"{\fscx135\fscy135\t(0,100,\fscx100\fscy100)}헉!", plain="헉!",
         size=56, color="#3CE6FF", highlight=None, outline=4, box=False, motion_in="pop", motion_dur=0.10,
         scale_from=1.35),
]

STYLES = {
    # name: (font, size, fill, outline_color, back, border_style, outline, shadow)
    "Title": (FONT_BLACK, 40, "#FFFFFF", _ass_color("#000000"), _ass_color("#000000"), 1, 3, 0),
    "Desc": (FONT_BOLD, 24, "#DDDDDD", _ass_color("#000000"), _ass_color("#000000"), 1, 2, 0),
    "Sit": (FONT_BLACK, 34, "#FFFFFF", _ass_color("#000000"), _ass_color("#000000"), 1, 3, 0),
    "Spk": (FONT_BOLD, 22, "#FFFFFF", _ass_color("#000000", alpha=0x66), _ass_color("#000000", 0x66), 3, 6, 0),
    "Dlg": (FONT_BLACK, 32, "#FFE400", _ass_color("#000000"), _ass_color("#000000"), 1, 3, 0),
    "Rx": (FONT_BLACK, 56, "#3CE6FF", _ass_color("#000000"), _ass_color("#000000"), 1, 4, 0),
}

CUTS = [
    {"t": 3.0, "type": "cut"},
    {"t": 5.6, "type": "flash", "window": [5.45, 5.8]},
    {"t": 6.8, "type": "crossfade", "dur": 0.4},
]
MOTION = [
    {"type": "zoom_in", "t": 1.0, "end": 1.5, "scale_to": 1.3},
    {"type": "freeze", "t": 4.0, "hold": 0.6},
    {"type": "speed", "t": 8.0, "factor": 0.5},
]


def ass_text(events=None) -> str:
    out = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "WrapStyle: 2",
           "ScaledBorderAndShadow: yes", "", "[V4+ Styles]",
           "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
           "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
           "MarginL, MarginR, MarginV, Encoding"]
    for name, (font, size, fill, oc, back, bs, ol, sh) in STYLES.items():
        out.append(f"Style: {name},{font},{size},{_ass_color(fill)},&H000000FF,{oc},{back},0,0,0,0,100,100,0,0,"
                   f"{bs},{ol},{sh},5,10,10,10,1")
    out += ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for e in events if events is not None else EVENTS:
        out.append(f"Dialogue: 0,{_t(e['start'])},{_t(e['end'])},{e['style']},,0,0,0,,"
                   f"{{\\pos({e['pos'][0]},{e['pos'][1]})}}{e['text']}")
    return "\n".join(out) + "\n"


def _run(cmd: list[str]) -> None:
    p = subprocess.run([str(c) for c in cmd], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        raise RuntimeError(p.stderr.decode("utf-8", "replace")[-3000:])


def _still_truth(tmp: Path, ev: dict) -> dict:
    """Render one event alone on flat gray at its rest time and measure it with color thresholds."""
    import cv2

    rest = dict(ev)
    # drop the animation so the still shows the rest state
    rest["text"] = ev["text"].replace(r"{\fscx85\fscy85\t(0,150,\fscx100\fscy100)}", "") \
        .replace(r"{\fscx135\fscy135\t(0,100,\fscx100\fscy100)}", "").replace(r"{\fad(150,150)}", "")
    rest["start"], rest["end"] = 0.0, 1.0
    a = tmp / f"still_{ev['id']}.ass"
    a.write_text(ass_text([rest]), encoding="utf-8")
    png = tmp / f"still_{ev['id']}.png"
    _run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "lavfi", "-i",
          f"color=c=0x808080:s={W}x{H}:d=1:r={FPS}", "-vf", f"ass={a}", "-frames:v", "1", png])
    img = cv2.cvtColor(cv2.imread(str(png)), cv2.COLOR_BGR2RGB).astype(int)
    diff = np.abs(img - 128).max(axis=2)
    truth: dict = {}
    if ev.get("box"):
        boxm = diff > 12
        ys, xs = np.nonzero(boxm)
        truth["box_bbox"] = [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)]
        ink = img.min(axis=2) > 170
    else:
        ink = diff > 40
    ys, xs = np.nonzero(ink)
    truth["bbox"] = [int(xs.min()), int(ys.min()), int(xs.max() - xs.min() + 1), int(ys.max() - ys.min() + 1)]
    if ev.get("lines", 1) >= 2:
        rows = ink.any(axis=1)
        runs, start = [], None
        for yy in range(len(rows) + 1):
            on = yy < len(rows) and rows[yy]
            if on and start is None:
                start = yy
            elif not on and start is not None:
                runs.append((start, yy - 1))
                start = None
        runs = [r for r in runs if r[1] - r[0] >= 4]
        centers = [(a + b) / 2 for a, b in runs]
        truth["line_pitch"] = float(np.median(np.diff(centers))) if len(centers) >= 2 else None
    if ev.get("box"):
        bx, by, bw, bh = truth["box_bbox"]
        x, y, w, h = truth["bbox"]
        truth["pad_x"] = x - bx
        truth["pad_y"] = y - by
    return truth


def build_mock(out_dir: Path, video_dir: Path, force: bool = False) -> dict:
    """Create out_dir/mockref_a.mp4 + mockref_a.truth.json (cached by GEN_VERSION)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    mp4 = out_dir / "mockref_a.mp4"
    tj = out_dir / "mockref_a.truth.json"
    if not force and mp4.is_file() and tj.is_file():
        t = json.loads(tj.read_text(encoding="utf-8"))
        if t.get("gen_version") == GEN_VERSION:
            return t
    tmp = out_dir / "_mock_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    ass = tmp / "mock.ass"
    ass.write_text(ass_text(), encoding="utf-8")
    cls = video_dir / "classroom.mp4"
    ppl = video_dir / "people-detection.mp4"
    fac = video_dir / "face-demographics-walking-and-pause.mp4"
    for p in (cls, ppl, fac):
        if not p.is_file():
            raise FileNotFoundError(f"{p} missing: run `python -m shortkit testassets fetch-video`")
    sc = f"scale={REGION['w']}:{REGION['h']},setsar=1"
    fc = (
        f"[0:v]scale=1080:608,setsar=1,fps=30,zoompan=z='if(lt(it,1),1,if(lt(it,1.5),1+0.3*(it-1)/0.5,1.3))'"
        f":x='iw/2-iw/zoom/2':y='ih/2-ih/zoom/2':d=1:s={REGION['w']}x{REGION['h']}:fps=30,"
        f"trim=duration=3,setpts=PTS-STARTPTS,format=yuv420p[a];"
        f"[1:v]{sc},fps=30,trim=duration=1,setpts=PTS-STARTPTS,tpad=stop_mode=clone:stop_duration=0.6,format=yuv420p[b1];"
        f"[2:v]{sc},fps=30,trim=duration=1,setpts=PTS-STARTPTS,fade=t=out:st=0.9:d=0.1:color=white,format=yuv420p[b2];"
        f"[3:v]{sc},fps=30,trim=duration=1.6,setpts=PTS-STARTPTS,fade=t=in:st=0:d=0.2:color=white,format=yuv420p,settb=AVTB[c];"
        f"[4:v]{sc},fps=30,trim=duration=1.2,setpts=PTS-STARTPTS,format=yuv420p[d1];"
        f"[5:v]{sc},setpts=2*(PTS-STARTPTS),fps=30,trim=duration=1.0,setpts=PTS-STARTPTS,format=yuv420p[d2];"
        f"[d1][d2]concat=n=2:v=1:a=0,settb=AVTB[d];"
        f"[c][d]xfade=transition=fade:duration=0.4:offset=1.2[cd];"
        f"[a][b1][b2][cd]concat=n=4:v=1:a=0[fg];"
        f"[6:v][fg]overlay=x={REGION['x']}:y={REGION['y']}:eof_action=pass,format=yuv420p,ass={ass}[out]"
    )
    bg = BG_HEX.lstrip("#")
    _run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y",
          "-ss", "1.2", "-t", "3.2", "-i", cls,
          "-ss", "5", "-t", "1.2", "-i", ppl,
          "-ss", "6", "-t", "1.2", "-i", ppl,
          "-ss", "10", "-t", "1.8", "-i", fac,
          "-ss", "20", "-t", "1.3", "-i", cls,
          "-ss", "21.2", "-t", "0.6", "-i", cls,
          "-f", "lavfi", "-i", f"color=c=0x{bg}:s={W}x{H}:r={FPS}:d={DURATION}",
          "-filter_complex", fc, "-map", "[out]", "-t", f"{DURATION}", "-r", str(FPS),
          "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", "-pix_fmt", "yuv420p", mp4])
    events = []
    for ev in EVENTS:
        tr = _still_truth(tmp, ev)
        e = {k: v for k, v in ev.items() if k not in ("text", "style")}
        e.update(tr)
        events.append(e)
    truth = {"gen_version": GEN_VERSION, "synthetic": True,
             "note": "SYNTHETIC mock reference (Intel CC-BY clips + libass). Not reference-channel data.",
             "resolution": [W, H], "fps": FPS, "duration": DURATION, "video_region": REGION,
             "background": {"type": "color", "color": BG_HEX}, "events": events, "cuts": CUTS, "motion": MOTION}
    tj.write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    shutil.rmtree(tmp, ignore_errors=True)
    return truth


def build_blur_mock(out_dir: Path, video_dir: Path) -> dict:
    """3-second mock (three 1-s shots) with a blurred-source background (canvas.background.type =
    blur_source)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    mp4 = out_dir / "mockref_blur.mp4"
    tj = out_dir / "mockref_blur.truth.json"
    if mp4.is_file() and tj.is_file():
        t = json.loads(tj.read_text(encoding="utf-8"))
        if t.get("gen_version") == GEN_VERSION:
            return t
    srcs = [(video_dir / "classroom.mp4", 4), (video_dir / "people-detection.mp4", 8),
            (video_dir / "face-demographics-walking-and-pause.mp4", 20)]
    parts = []
    for i, _ in enumerate(srcs):
        parts.append(f"[{i}:v]fps=30,scale=640:360,setsar=1,trim=duration=1,setpts=PTS-STARTPTS[s{i}]")
    fc = ";".join(parts) + (f";[s0][s1][s2]concat=n=3:v=1:a=0,split[x][y];[x]scale={W}:{H},boxblur=20:2[bg];"
                            f"[y]scale={REGION['w']}:{REGION['h']}[fg];[bg][fg]overlay=x={REGION['x']}:y={REGION['y']},"
                            f"format=yuv420p[out]")
    cmd = ["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y"]
    for src, ss in srcs:
        cmd += ["-ss", str(ss), "-t", "1.2", "-i", src]
    _run(cmd + ["-filter_complex", fc, "-map", "[out]", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", mp4])
    truth = {"gen_version": GEN_VERSION, "synthetic": True, "resolution": [W, H], "video_region": REGION,
             "background": {"type": "blur_source"}}
    tj.write_text(json.dumps(truth, ensure_ascii=False, indent=1), encoding="utf-8")
    return truth


def build_hd_mock(out_dir: Path, video_dir: Path) -> tuple[dict, Path]:
    """The 540x960 mock upscaled to 1080x1920 (lanczos): checks that detection / measurement do not
    depend on the upload resolution.  Truth = the base truth with px values x2."""
    truth = build_mock(out_dir, video_dir)
    mp4 = out_dir / "mockref_hd.mp4"
    stamp = out_dir / "mockref_hd.version"
    if not (mp4.is_file() and stamp.is_file() and stamp.read_text().strip() == str(GEN_VERSION)):
        _run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", out_dir / "mockref_a.mp4", "-vf",
              "scale=1080:1920:flags=lanczos", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", mp4])
        stamp.write_text(str(GEN_VERSION))
    return truth, mp4
