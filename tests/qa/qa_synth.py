"""SYNTHETIC test episodes for the QA module (clearly labelled: generated here, never production).

A tiny independent renderer (numpy + OpenCV + ffmpeg/libass) that produces an output MP4 whose
ground truth we control exactly, plus the matching ``build/resolved.json`` and ``plan.yaml``:

  video   3 clips from the CC-BY Intel sample clips / the synthetic dirty source:
          c1 head-pose (12 fps) -> crossfade 0.3 s -> c2 dirty_source (fake watermark, delogo'd in
          the GOOD variant) -> flash 0.12 s -> c3 classroom with zoom 1.0->1.3 (ease out) and a
          0.6 s freeze at the end
  text    title (whole video), situation (pop 0.85), speaker label (box, fade), dialogue,
          reaction (pop 1.35) rendered by libass from our own ASS file
  deco    red circle ring moving (200,600)->(400,650) over 3.0-4.5 s, blinking 2 Hz
  audio   music_bed_a from 12.0 s at -16 dB, ducked -10 dB under the kept original line
          (dirty_source 8.0-10.3 s at out 2.7-5.0), intentional silence 6.3-6.8, 0.5 s fade out,
          SFX pop/whoosh/ding/boom at known times, then one linear loudness gain

The BAD variant contains deliberate mistakes (the IR stays the GOOD plan):
  situation caption drawn 353 px higher (over the declared male face), BGM from 17.0 s
  (wrong section), extra ducking 1.2-1.9 s (outside kept dialogue), an extra planned-type SFX
  (pop at 6.9 s, no event), an unknown SFX (click at 1.6 s), watermark left in (no delogo),
  decoration drawn 40 px to the right (blink kept).
"""
from __future__ import annotations

import math
import subprocess
from pathlib import Path

import numpy as np

from shortkit import paths
from shortkit.edit.ir import (SCHEMA, AudioPlan, Bgm, CaptionBox, Clip, Decoration, Freeze, OriginalAudio, Rect,
                              ResolvedEdit, SfxPlacement, TimedRect, Transition, Zoom)
from shortkit.util.jsonio import write_json, write_yaml
from shortkit.util.media import FFMPEG, lufs, probe, read_audio

GEN = "assets/test/generated"
W, H, FPS = 720, 1280, 30
REGION = (0.0, 437.0, 720.0, 405.0)
DUR = 7.8
SR = 48000
FONT_BLACK = "Noto Sans CJK KR Black"
FONT_BOLD = "Noto Sans CJK KR Bold"
# Fonts are written the way the production renderer (shortkit.edit.captions / edit.render) writes them:
# PostScript face name, Fontsize = size_px * (winAscent+winDescent)/unitsPerEm, Bold = face weight,
# a fontsdir holding exactly those faces, ffmpeg's `subtitles` filter, bt709 conversion.  (ffmpeg's
# `ass` filter lays glyphs out ~2 % wider than `subtitles`, so the synthetic truth must use the same
# path as production for the font check -- whose ceiling emulates production -- to be meaningful.)

CLIPS = [
    dict(id="c1", source=f"{GEN}/video/head-pose-face-detection-female-and-male.mp4", src_in=10.0, src_out=12.5,
         out_start=0.0, out_end=2.5, src_size=(768, 432), tr=("cut", 0.0, None)),
    dict(id="c2", source=f"{GEN}/dirty_source.mp4", src_in=7.5, src_out=10.5, out_start=2.2, out_end=5.2,
         src_size=(1920, 1080), tr=("crossfade", 0.3, None), delogo=dict(x=16, y=14, w=190, h=44)),
    dict(id="c3", source=f"{GEN}/video/classroom.mp4", src_in=24.0, src_out=26.0, out_start=5.2, out_end=7.8,
         src_size=(1920, 1080), tr=("flash", 0.12, "#FFFFFF"),
         zoom=dict(scale_from=1.0, scale_to=1.3, center=(960.0, 540.0), start=0.4, dur=0.5, ease="out"),
         freeze=dict(src_t=26.0, out_start=7.2, hold=0.6)),
]

CAPTIONS = [
    dict(id="t1", role="title", text="실험 영상 모음", start=0.0, end=DUR, anchor=(360, 220), size=56, color="#FFFFFF",
         outline=4, font=FONT_BLACK, motion=("none", 0.0, 1.0)),
    dict(id="s1", role="situation", text="두 사람이 고개를 돌린다", start=0.8, end=2.3, anchor=(360, 953), size=44,
         color="#FFFFFF", outline=4, font=FONT_BLACK, motion=("pop", 0.12, 0.85)),
    dict(id="k1", role="speaker", text="선생님", start=2.8, end=4.6, anchor=(560, 480), size=27, color="#FFFFFF",
         outline=0, font=FONT_BOLD, motion=("fade", 0.15, 1.0), box=True),
    dict(id="d1", role="dialogue", text="\"잠깐만요 진짜예요?\"", start=2.8, end=5.0, anchor=(360, 953), size=41,
         color="#FFE400", outline=4, font=FONT_BLACK, motion=("none", 0.0, 1.0)),
    dict(id="r1", role="reaction", text="헉!", start=5.4, end=6.6, anchor=(360, 760), size=51, color="#FFE400",
         outline=5, font=FONT_BLACK, motion=("pop", 0.1, 1.35)),
]

DECO = dict(id="dc1", kind="circle", start=3.0, end=4.5, kf=[(3.0, 200.0, 600.0), (4.5, 400.0, 650.0)], size=90.0,
            stroke=7.0, blink_hz=2.0, color="#FF2A2A")

SFX = [
    dict(id="fx1", type="pop", t=0.8, gain=-6.0, event_t=0.8, desc="상황 자막이 튀어나옴", kind="text_pop"),
    dict(id="fx2", type="whoosh", t=2.25, gain=-8.0, event_t=2.3, desc="교사가 화면 안으로 걸어 들어옴", kind="action"),
    dict(id="fx3", type="ding", t=5.4, gain=-8.0, event_t=5.4, desc="반응 자막 '헉!' 등장", kind="text_pop"),
    dict(id="fx4", type="boom", t=5.95, gain=-10.0, event_t=6.0, desc="교실 확대가 끝나며 강조", kind="zoom_in"),
]
BGM = dict(path=f"{GEN}/music_bed_a.wav", section=12.0, tempo=1.0, gain=-16.0, fade_out=0.5, duck=[(2.7, 5.0)],
           silences=[(6.3, 6.8)], depth=10.0, attack=0.08, release=0.3, sil_fade=0.05)
ORIG = dict(clip_id="c2", path=f"{GEN}/dirty_source.mp4", src=(8.0, 10.3), out=(2.7, 5.0), gain=0.0, fade=0.04)
TARGET_LUFS = -18.0
PROTECTED = dict(label="남성 얼굴", x=456, y=80, w=136, h=170, start=10.0, end=12.5)

BAD = dict(caption_dy={"s1": -353}, bgm_section=17.0, extra_duck=[(1.2, 1.9)],
           extra_sfx=[dict(type="pop", t=6.9, gain=-6.0), dict(type="click", t=1.6, gain=-3.0)],
           no_delogo=True, deco_dx=40.0)


# ----------------------------------------------------------------------------- helpers
def _ass_color(hex_rgb: str, alpha: int = 0) -> str:
    h = hex_rgb.lstrip("#")
    return f"&H{alpha:02X}{h[4:6]}{h[2:4]}{h[0:2]}".upper()


def _ass_time(t: float) -> str:
    cs = int(round(t * 100))
    return f"{cs // 360000}:{(cs // 6000) % 60:02d}:{(cs // 100) % 60:02d}.{cs % 100:02d}"


def _ring(r_out: float, r_in: float, n: int = 48) -> str:
    def poly(r, rev):
        pts = [(r_out + r * math.cos(2 * math.pi * i / n), r_out + r * math.sin(2 * math.pi * i / n)) for i in range(n)]
        if rev:
            pts = pts[::-1]
        return "m {:.1f} {:.1f} l ".format(*pts[0]) + " ".join(f"{x:.1f} {y:.1f}" for x, y in pts[1:])
    return poly(r_out, False) + " " + poly(r_in, True)


def _face(name: str):
    from shortkit.edit.captions import resolve_font

    return resolve_font(name).face


def link_fonts(fonts_dir: Path) -> None:
    """fontsdir with exactly the caption faces (like shortkit.edit.resolve.link_fonts)."""
    import os

    fonts_dir.mkdir(parents=True, exist_ok=True)
    for name in sorted({c["font"] for c in CAPTIONS}):
        f = Path(_face(name).path)
        dst = fonts_dir / f.name
        if not dst.exists():
            os.symlink(f, dst)


def build_ass(bad: bool, rest_only: bool = False) -> str:
    """Our own ASS (captions + decoration).  rest_only: every caption without motion, one per
    second, used to derive the ground-truth ink bboxes on a black canvas."""
    styles = []
    for c in CAPTIONS:
        face = _face(c["font"])
        fs = face.ass_fontsize(c["size"])
        if c.get("box"):
            styles.append(f"Style: {c['id']},{face.ass_name},{fs:.3f},{_ass_color(c['color'])},{_ass_color(c['color'])},"
                          f"{_ass_color('#000000', 0x59)},&H00000000,{face.weight},0,0,0,100,100,0,0,3,6,0,5,0,0,0,1")
        else:
            styles.append(f"Style: {c['id']},{face.ass_name},{fs:.3f},{_ass_color(c['color'])},{_ass_color(c['color'])},"
                          f"&H00000000,&H00000000,{face.weight},0,0,0,100,100,0,0,1,{c['outline']},0,5,0,0,0,1")
    styles.append(f"Style: deco,{_face(FONT_BLACK).ass_name},20,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1")
    ev = []
    for i, c in enumerate(CAPTIONS):
        x, y = c["anchor"]
        if rest_only:
            ev.append(f"Dialogue: 1,{_ass_time(i + 0.0)},{_ass_time(i + 0.9)},{c['id']},,0,0,0,,{{\\an5\\pos({x},{y})}}{c['text']}")
            continue
        if bad:
            y += BAD["caption_dy"].get(c["id"], 0)
        typ, dur, sf = c["motion"]
        tag = f"\\an5\\pos({x},{y})"
        if typ == "pop":
            p = int(round(sf * 100))
            tag += f"\\fscx{p}\\fscy{p}\\t(0,{int(dur * 1000)},\\fscx100\\fscy100)"
        elif typ == "fade":
            tag += f"\\fad({int(dur * 1000)},{int(dur * 1000)})"
        ev.append(f"Dialogue: 1,{_ass_time(c['start'])},{_ass_time(c['end'])},{c['id']},,0,0,0,,{{{tag}}}{c['text']}")
    if not rest_only:
        d = DECO
        r = d["size"] / 2
        (t0, x0, y0), (t1, x1, y1) = d["kf"]
        dx = BAD["deco_dx"] if bad else 0.0
        period = 1.0 / d["blink_hz"]
        k = 0
        while d["start"] + k * period < d["end"] - 1e-9:
            a = d["start"] + k * period
            b = min(d["end"], a + period / 2)
            pa = (x0 + (x1 - x0) * (a - t0) / (t1 - t0), y0 + (y1 - y0) * (a - t0) / (t1 - t0))
            pb = (x0 + (x1 - x0) * (b - t0) / (t1 - t0), y0 + (y1 - y0) * (b - t0) / (t1 - t0))
            mv = (f"\\move({pa[0] - r + dx:.1f},{pa[1] - r:.1f},{pb[0] - r + dx:.1f},{pb[1] - r:.1f},0,"
                  f"{int(round((b - a) * 1000))})")
            ev.append(f"Dialogue: 0,{_ass_time(a)},{_ass_time(b)},deco,,0,0,0,,{{\\an7{mv}\\bord0\\shad0\\1c{_ass_color(d['color'])}\\p1}}"
                      f"{_ring(r, r - d['stroke'])}{{\\p0}}")
            k += 1
    return ("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nLayoutResX: %d\nLayoutResY: %d\n"
            "WrapStyle: 2\nScaledBorderAndShadow: yes\nYCbCr Matrix: None\nKerning: yes\n\n"
            "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
            "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding\n%s\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, "
            "MarginV, Effect, Text\n%s\n") % (W, H, W, H, "\n".join(styles), "\n".join(ev))


def _decode(src: Path, until: float, size: tuple[int, int], delogo: dict | None) -> tuple[list[np.ndarray], float]:
    info = probe(src)
    vf = []
    if delogo:
        vf.append(f"delogo=x={delogo['x']}:y={delogo['y']}:w={delogo['w']}:h={delogo['h']}")
    vf.append(f"scale={size[0]}:{size[1]}:flags=area")
    raw = subprocess.run([FFMPEG, "-v", "error", "-i", str(src), "-t", f"{until:.3f}", "-an", "-vf", ",".join(vf),
                          "-f", "rawvideo", "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, check=True).stdout
    fb = size[0] * size[1] * 3
    frames = [np.frombuffer(raw[i * fb:(i + 1) * fb], np.uint8).reshape(size[1], size[0], 3) for i in range(len(raw) // fb)]
    return frames, float(info.fps or 30.0)


def _ease_out(u: float) -> float:
    u = min(1.0, max(0.0, u))
    return 1.0 - (1.0 - u) ** 3


def _src_t(c: dict, t: float) -> float:
    u = t - c["out_start"]
    f = c.get("freeze")
    move = c["src_out"] - c["src_in"]
    if not f:
        return c["src_in"] + min(max(u, 0.0), move)
    fl = f["out_start"] - c["out_start"]
    if u < fl:
        return c["src_in"] + max(u, 0.0)
    if u < fl + f["hold"]:
        return f["src_t"]
    return min(c["src_out"], f["src_t"] + (u - fl - f["hold"]))


def _region_frame(c: dict, t: float, frames: list[np.ndarray], fps: float) -> np.ndarray:
    import cv2

    idx = min(len(frames) - 1, int(math.floor(_src_t(c, t) * fps + 1e-6)))
    img = frames[idx]
    z = c.get("zoom")
    if z:
        u = (t - c["out_start"] - z["start"]) / z["dur"]
        s = z["scale_from"] + (z["scale_to"] - z["scale_from"]) * _ease_out(u)
        if abs(s - 1.0) > 1e-6:
            k = REGION[2] / c["src_size"][0]
            cx, cy = z["center"][0] * k, z["center"][1] * k
            M = np.array([[s, 0, (1 - s) * cx], [0, s, (1 - s) * cy]], np.float64)
            img = cv2.warpAffine(img, M, (img.shape[1], img.shape[0]), flags=cv2.INTER_LINEAR,
                                 borderMode=cv2.BORDER_REPLICATE)
    return img


# ----------------------------------------------------------------------------- audio
def _db(x):
    return 10 ** (x / 20.0)


def _bgm_env(n: int, bad: bool) -> np.ndarray:
    t = np.arange(n) / SR
    g = np.zeros(n)                         # dB
    ducks = list(BGM["duck"]) + (BAD["extra_duck"] if bad else [])
    for a, b in ducks:
        down = np.clip((t - (a - BGM["attack"])) / BGM["attack"], 0, 1)
        up = np.clip(1 - (t - b) / BGM["release"], 0, 1)
        m = np.where(t < a, down, np.where(t <= b, 1.0, up))
        g = np.minimum(g, -BGM["depth"] * m)
    lin = _db(g)
    for a, b in BGM["silences"]:
        f = BGM["sil_fade"]
        m = np.clip(np.minimum((a - t) / f, (t - b) / f), 0, 1)
        lin *= np.where((t >= a - f) & (t <= b + f), m, 1.0)
    fo = BGM["fade_out"]
    lin *= np.clip((DUR - t) / fo, 0, 1)
    return lin


def build_audio(bad: bool, out_wav: Path) -> dict:
    n = int(round(DUR * SR))
    root = paths.project_root()
    music = read_audio(root / BGM["path"], sr=SR, mono=False)
    sec = BAD["bgm_section"] if bad else BGM["section"]
    a = int(round(sec * SR))
    bgm = music[a:a + n]
    mix = np.zeros((n, 2), np.float64)
    mix[:len(bgm)] += bgm * _db(BGM["gain"]) * _bgm_env(n, bad)[:len(bgm), None]
    o = read_audio(root / ORIG["path"], sr=SR, mono=False, start=ORIG["src"][0],
                   duration=ORIG["src"][1] - ORIG["src"][0]).mean(axis=1)          # (L+R)/2
    k = len(o)
    fl = int(ORIG["fade"] * SR)
    env = np.ones(k)
    env[:fl] = np.linspace(0, 1, fl)
    env[-fl:] = np.linspace(1, 0, fl)
    s = int(round(ORIG["out"][0] * SR))
    mix[s:s + k] += (o * env * _db(ORIG["gain"]))[:, None][: n - s]
    placements = [dict(type=x["type"], t=x["t"], gain=x["gain"]) for x in SFX] + (BAD["extra_sfx"] if bad else [])
    for p in placements:
        sfx = read_audio(root / f"{GEN}/sfx/{p['type']}.wav", sr=SR, mono=True)
        s = int(round(p["t"] * SR))
        e = min(n, s + len(sfx))
        mix[s:e] += (sfx[:e - s] * _db(p["gain"]))[:, None]
    tmp = out_wav.with_suffix(".pre.wav")
    from shortkit.util.media import write_wav

    write_wav(tmp, mix.astype(np.float32), SR)
    L = lufs(tmp)["integrated_lufs"]
    g = _db(TARGET_LUFS - L)
    mix *= g
    write_wav(out_wav, mix.astype(np.float32), SR)
    tmp.unlink()
    return {"pre_lufs": L, "gain": g, "peak": float(np.abs(mix).max())}


# ----------------------------------------------------------------------------- truth bboxes
def caption_truth_bboxes(work: Path) -> dict[str, list[float]]:
    """Render every caption at rest on black and take its FILL-colour bbox (+ outline -> IR bbox)."""
    from shortkit.util.media import read_frames

    ass = work / "rest.ass"
    ass.write_text(build_ass(False, rest_only=True), encoding="utf-8")
    link_fonts(work / "fonts")
    mp4 = work / "rest.mp4"
    subprocess.run([FFMPEG, "-v", "error", "-y", "-f", "lavfi", "-i", f"color=c=black:s={W}x{H}:r={FPS}:d={len(CAPTIONS)}",
                    "-vf", f"subtitles=filename={ass.name}:fontsdir=fonts", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "12", "-pix_fmt", "yuv444p",
                    mp4.name], check=True, cwd=str(work))
    out = {}
    frames = read_frames(mp4, [i + 0.45 for i in range(len(CAPTIONS))])
    for c, f in zip(CAPTIONS, frames):
        rgb = np.array([int(c["color"][i:i + 2], 16) for i in (1, 3, 5)])
        m = np.sqrt(((f.astype(np.int32) - rgb) ** 2).sum(axis=2)) < 60
        ys, xs = np.nonzero(m)
        o = c["outline"]
        out[c["id"]] = [float(xs.min() - o), float(ys.min() - o), float(xs.max() - xs.min() + 1 + 2 * o),
                        float(ys.max() - ys.min() + 1 + 2 * o)]
    return out


# ----------------------------------------------------------------------------- IR / plan
def build_resolved(episode_id: str, bboxes: dict) -> ResolvedEdit:
    clips = []
    for c in CLIPS:
        z = c.get("zoom")
        f = c.get("freeze")
        clips.append(Clip(
            id=c["id"], source_id=c["id"] + "_src", source_path=c["source"], src_in=c["src_in"], src_out=c["src_out"], speed=1.0,
            out_start=c["out_start"], out_end=c["out_end"], region=Rect(*REGION), fit="cover", src_size=tuple(c["src_size"]),
            crop=None, delogo=[TimedRect(**c["delogo"], reason="가짜 워터마크")] if c.get("delogo") else [],
            zoom=Zoom(z["scale_from"], z["scale_to"], tuple(z["center"]), z["start"], z["dur"], z["ease"]) if z else None,
            freeze=Freeze(f["src_t"], f["out_start"], f["hold"]) if f else None,
            transition_in=Transition(c["tr"][0], c["tr"][1], c["tr"][2])))
    caps = []
    for c in CAPTIONS:
        typ, dur, sf = c["motion"]
        b = bboxes[c["id"]]
        caps.append(CaptionBox(
            id=c["id"], role=c["role"], text=c["text"], lines=[c["text"]], start=c["start"], end=c["end"],
            anchor=tuple(c["anchor"]), align="center", valign="middle", bbox=Rect(*b), font_name=c["font"], font_file=None,
            size_px=float(c["size"]), color=c["color"], highlight=[], highlight_color="#FFFFFF", outline_px=float(c["outline"]),
            outline_color="#000000", shadow_px=0.0,
            box={"enabled": bool(c.get("box")), "color": "#000000", "alpha": 0.65, "pad_x": 9, "pad_y": 4},
            motion_in={"type": typ, "dur_s": dur, "scale_from": sf, "offset_px": 0},
            motion_out={"type": "fade" if typ == "fade" else "none", "dur_s": dur if typ == "fade" else 0.0},
            grounding={"kind": "seen"}))
    d = DECO
    deco = Decoration(id=d["id"], kind=d["kind"], start=d["start"], end=d["end"],
                      keyframes=[{"t": t, "x": x, "y": y, "w": d["size"], "h": d["size"], "rotation": None} for t, x, y in d["kf"]],
                      blink_hz=d["blink_hz"], style={"color": d["color"], "stroke_px": d["stroke"], "blink_hz": 0.0})
    bgm = Bgm(path=BGM["path"], track_id="synthetic_bed_a", section_start_s=BGM["section"], tempo_ratio=BGM["tempo"],
              gain_db=BGM["gain"], fade_in_s=0.0, fade_out_s=BGM["fade_out"], envelope=[], silences=list(BGM["silences"]),
              duck_ranges=list(BGM["duck"]))
    orig = OriginalAudio(clip_id=ORIG["clip_id"], path=ORIG["path"], stem="raw", src_start=ORIG["src"][0], src_end=ORIG["src"][1],
                         out_start=ORIG["out"][0], out_end=ORIG["out"][1], speed=1.0, gain_db=ORIG["gain"], fade_s=ORIG["fade"],
                         reason="말하는 사람의 실제 대사")
    sfx = [SfxPlacement(id=s["id"], type=s["type"], path=f"{GEN}/sfx/{s['type']}.wav", t=s["t"], gain_db=s["gain"],
                        event_t=s["event_t"], event_desc=s["desc"], emotion=None, map_status="have") for s in SFX]
    audio = AudioPlan(sample_rate=SR, target_lufs=TARGET_LUFS, true_peak_db=-1.0, bgm=bgm, originals=[orig], sfx=sfx)
    return ResolvedEdit(schema=SCHEMA, episode_id=episode_id, preset_id="joshuamagazine-v1", preset_name="joshuamagazine",
                        format_id="UNCLASSIFIED", mode="test",
                        canvas={"width": W, "height": H, "fps": float(FPS), "background": {"type": "color", "color": "#000000",
                                                                                          "blur_sigma": 30.0},
                                "video_region": {"x": REGION[0], "y": REGION[1], "w": REGION[2], "h": REGION[3], "fit": "cover"}},
                        duration=DUR, clips=clips, captions=caps, decorations=[deco],
                        ass_path=f"episodes/{episode_id}/build/captions.ass", fonts_dir=None, audio=audio,
                        output_path=f"episodes/{episode_id}/output/{episode_id}.mp4")


def build_plan(episode_id: str) -> dict:
    return {"schema": "shortkit.plan/1", "episode_id": episode_id, "preset_id": "joshuamagazine-v1",
            "format_id": "UNCLASSIFIED", "mode": "test", "notes": "SYNTHETIC QA test episode (tests/qa/qa_synth.py)",
            "cover": {"text": "실험 영상 모음", "frame_t": 0.0},
            "sources": [{"id": c["id"] + "_src", "path": c["source"],
                         **({"protected": [PROTECTED]} if c["id"] == "c1" else {})} for c in CLIPS],
            "timeline": [], "captions": [],
            "sfx": [{"id": s["id"], "type": s["type"], "t": s["t"],
                     "event": {"t": s["event_t"], "desc": s["desc"], "kind": s["kind"]}} for s in SFX]}


# ----------------------------------------------------------------------------- main
def render_episode(episode_id: str, bad: bool = False) -> dict:
    """Render the synthetic episode into episodes/<episode_id>/ of the CURRENT project root."""
    root = paths.project_root()
    ep = root / "episodes" / episode_id
    (ep / "build").mkdir(parents=True, exist_ok=True)
    (ep / "output").mkdir(parents=True, exist_ok=True)
    bboxes = caption_truth_bboxes(ep / "build")
    res = build_resolved(episode_id, bboxes)
    write_json(ep / "build" / "resolved.json", res.to_dict())
    write_yaml(ep / "plan.yaml", build_plan(episode_id))
    ass = ep / "build" / "captions.ass"
    ass.write_text(build_ass(bad), encoding="utf-8")
    wav = ep / "build" / "synthetic_mix.wav"
    ainfo = build_audio(bad, wav)
    # sources, decoded once at region size
    srcs = {}
    for c in CLIPS:
        k = REGION[2] / c["src_size"][0]
        size = (int(round(c["src_size"][0] * k)), int(round(c["src_size"][1] * k)))
        dl = c.get("delogo") if (c.get("delogo") and not (bad and BAD["no_delogo"])) else None
        srcs[c["id"]] = _decode(root / c["source"], c["src_out"] + 0.3, size, dl)
    out = ep / "output" / f"{episode_id}.mp4"
    n_frames = int(round(DUR * FPS))
    link_fonts(ep / "build" / "fonts")
    vf = (f"subtitles=filename={ass.relative_to(root).as_posix()}:fontsdir={(ep / 'build' / 'fonts').relative_to(root).as_posix()},"
          "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p")
    cmd = [FFMPEG, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-framerate", str(FPS),
           "-i", "-", "-i", str(wav), "-vf", vf, "-map", "0:v", "-map", "1:a",
           "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
           "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
           "-c:a", "aac", "-b:a", "192k",
           "-ar", str(SR), "-ac", "2", "-t", f"{DUR:.3f}", str(out)]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, cwd=str(root))
    rx, ry, rw, rh = (int(v) for v in REGION)
    try:
        for n in range(n_frames):
            t = n / FPS
            canvas = np.zeros((H, W, 3), np.uint8)
            act = [c for c in CLIPS if c["out_start"] - 1e-6 <= t < c["out_end"] - 1e-6] or [CLIPS[-1]]
            if len(act) == 1:
                reg = _region_frame(act[0], t, *srcs[act[0]["id"]])
            else:
                a, b = act[-2], act[-1]
                al = min(1.0, max(0.0, (t - b["out_start"]) / b["tr"][1]))
                ra = _region_frame(a, t, *srcs[a["id"]]).astype(np.float32)
                rb = _region_frame(b, t, *srcs[b["id"]]).astype(np.float32)
                reg = np.clip(ra * (1 - al) + rb * al + 0.5, 0, 255).astype(np.uint8)
            reg = reg[:rh, :rw]
            for c in CLIPS:
                typ, dur, col = c["tr"]
                if typ == "flash" and abs(t - c["out_start"]) < dur / 2:
                    al = 1.0 - abs(t - c["out_start"]) / (dur / 2)
                    reg = np.clip(reg.astype(np.float32) * (1 - al) + 255 * al + 0.5, 0, 255).astype(np.uint8)
            canvas[ry:ry + reg.shape[0], rx:rx + reg.shape[1]] = reg
            proc.stdin.write(canvas.tobytes())
    finally:
        proc.stdin.close()
        proc.wait()
    if proc.returncode != 0:
        raise RuntimeError("synthetic render failed")
    return {"episode_id": episode_id, "mp4": out.relative_to(root).as_posix(), "bad": bad, "audio": ainfo,
            "bboxes": bboxes}
