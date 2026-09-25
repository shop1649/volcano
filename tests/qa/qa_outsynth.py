"""SYNTHETIC renders with known values for the output checks added in wave 5 (tests/qa/test_qa_outputs.py).

Everything here is drawn with the PRODUCTION renderer's own functions so the QA measurements are checked against
exactly what our renderer would output:
  * captions: shortkit.edit.captions (resolve_font + probe_ass_names, layout_text, role_style_line, caption_events,
    box_events via caption_events, libass_ink_bboxes + box_rect_from_ink for the box rect) burned with ffmpeg's
    ``subtitles`` filter (fontsdir) over a static, smooth grey texture -- a caption with a drop shadow, a boxed
    label, a slide_up dialogue line with quote marks, and a reaction caption with a colour "glyph" (an ASS drawing
    in a colour none of the caption's) next to it;
  * frames of clips: shortkit.edit.render.Compositor (background, fit, zoom geometry of edit.resolve.src_to_region,
    flash overlay with its scope) over the CC-BY sample clips of assets/test/generated.
None of this is reference-channel data.
"""
from __future__ import annotations

import dataclasses
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from shortkit import paths
from shortkit.edit.ir import CaptionBox, Rect

W, H, FPS = 720, 1280, 30
DUR = 3.6
FONT = "Noto Sans CJK KR Black"


def smooth_texture(w: int, h: int, seed: int = 5, amp: float = 26.0, base: float = 132.0) -> np.ndarray:
    """Static low-contrast grey texture: visible enough for the box regression (std >= 6), smooth enough that a
    drop shadow stands out (reference.textboxes._shadow 'busy' rule)."""
    import cv2

    rng = np.random.default_rng(seed)
    g = rng.normal(0.0, 1.0, (h // 40 + 2, w // 40 + 2)).astype(np.float32)
    g = cv2.resize(g, (w, h), interpolation=cv2.INTER_CUBIC)
    g = base + amp * g / max(1e-6, float(np.abs(g).max()))
    # a band of stronger texture behind the boxed label: the box regression needs a non-flat background (std >= 6)
    y0, y1 = 440, 620
    f = rng.normal(0.0, 1.0, ((y1 - y0) // 10 + 2, w // 10 + 2)).astype(np.float32)
    f = cv2.resize(f, (w, y1 - y0), interpolation=cv2.INTER_CUBIC)
    g[y0:y1] += 34.0 * f / max(1e-6, float(np.abs(f).max()))
    tint = np.stack([g, g * 0.98 + 2, g * 0.96 + 4], axis=2)
    return np.clip(tint, 0, 255).astype(np.uint8)


def write_frames(path: Path, frames, w: int, h: int, fps: float = FPS, crf: int = 16) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt",
                          "rgb24", "-s", f"{w}x{h}", "-r", str(fps), "-i", "-", "-c:v", "libx264", "-preset",
                          "veryfast", "-crf", str(crf), "-pix_fmt", "yuv420p", str(path)], stdin=subprocess.PIPE)
    for fr in frames:
        p.stdin.write(np.ascontiguousarray(fr, np.uint8).tobytes())
    p.stdin.close()
    if p.wait() != 0:
        raise RuntimeError("ffmpeg failed")
    return path


def _font():
    from shortkit.edit import captions as cm

    rf = cm.resolve_font(FONT)
    pr = cm.probe_ass_names([rf.face])
    name = (pr.get((str(rf.face.path), int(rf.face.index))) or {}).get("name")
    return dataclasses.replace(rf, libass_name=name) if name else rf


def _style(**kw) -> dict:
    st = {"size_px": 52.0, "color": "#FFFFFF", "outline_px": 4.0, "outline_color": "#000000", "shadow_px": 0.0,
          "shadow_color": "#000000", "max_chars_per_line": 20, "max_width_px": 680.0, "line_spacing": 1.15,
          "align": "center", "valign": "middle", "max_lines": 2}
    st.update(kw)
    return st


# id, role, text, anchor, style overrides, box, motion_in, start, end
CAPS = [
    dict(id="sh", role="situation", text="그림자 테스트", anchor=(360, 260),
         style=dict(shadow_px=5.0, shadow_color="#2040C0"), box=None, mi={"type": "none", "dur_s": 0.0},
         start=0.5, end=2.6),
    dict(id="ns", role="description", text="그림자 없는 줄", anchor=(360, 380), style=dict(size_px=44.0),
         box=None, mi={"type": "none", "dur_s": 0.0}, start=0.5, end=2.6),
    dict(id="bx", role="speaker", text="박스 라벨", anchor=(360, 520),
         style=dict(size_px=40.0, outline_px=0.0), box=dict(enabled=True, color="#183050", alpha=0.7, pad_x=14, pad_y=8),
         mi={"type": "fade", "dur_s": 0.15}, start=0.6, end=2.4),
    dict(id="dl", role="dialogue", text='"잠깐만요 진짜요?"', anchor=(360, 800),
         style=dict(color="#FFE400", outline_px=5.0), box=None, mi={"type": "slide_up", "dur_s": 0.2, "offset_px": 40},
         start=1.0, end=3.0),
    dict(id="rx", role="reaction", text="헉", anchor=(300, 1060), style=dict(size_px=64.0, color="#FFE400", outline_px=6.0),
         box=None, mi={"type": "none", "dur_s": 0.0}, start=0.8, end=2.8),
]
EMOJI_DISK = dict(caption="rx", x=336, y=1048, r=12, color="#22CC44")    # a colour 'glyph' (top-left, radius) next to 'rx'


def caption_irs(fonts_dir: Path) -> tuple[list[CaptionBox], dict, dict]:
    """IR captions + layouts + ASS style lines, built with the production layout / ink functions."""
    from shortkit.edit import captions as cm

    rf = _font()
    fonts_dir.mkdir(parents=True, exist_ok=True)
    dst = fonts_dir / Path(rf.face.path).name
    if not dst.exists():
        os.symlink(rf.face.path, dst)
    caps, lays, styles = [], {}, {}
    for c in CAPS:
        st = _style(**c["style"])
        lay = cm.layout_text(c["text"], rf.face, st, c["anchor"])
        styles[c["role"]] = cm.role_style_line(c["role"], st, rf)
        box = {"enabled": False, "color": "#000000", "alpha": 0.0, "pad_x": 16, "pad_y": 8, "rect": None}
        if c["box"]:
            box = dict(c["box"], rect=None)
        ix, iy, iw, ih = lay.ink
        mi = {"type": "none", "dur_s": 0.0, "scale_from": 1.0, "offset_px": 0, **c["mi"]}
        caps.append(CaptionBox(id=c["id"], role=c["role"], text="\n".join(lb.text for lb in lay.lines),
                               lines=[lb.text for lb in lay.lines], start=c["start"], end=c["end"], anchor=c["anchor"],
                               align="center", valign="middle", bbox=Rect(ix, iy, iw, ih), font_name=FONT,
                               font_file=str(dst), size_px=st["size_px"], color=st["color"], highlight=[],
                               highlight_color="#FFFFFF", outline_px=st["outline_px"], outline_color=st["outline_color"],
                               shadow_px=st["shadow_px"], box=box, motion_in=mi, motion_out={"type": "none", "dur_s": 0.0},
                               grounding=None, line_spacing=st["line_spacing"], shadow_color=st["shadow_color"],
                               weight=int(rf.face.weight),
                               lines_pos=[(round(lb.center[0], 3), round(lb.center[1], 3)) for lb in lay.lines]))
        lays[c["id"]] = lay
    boxed = [c for c in caps if c.box.get("enabled")]
    jobs = [{"style": c.role, "outline": c.outline_px, "lines": [(lb.text, lb.center[0], lb.center[1])
                                                                  for lb in lays[c.id].lines]} for c in boxed]
    inks = cm.libass_ink_bboxes(W, H, {c.role: styles[c.role] for c in boxed}, jobs, [str(rf.face.path)])
    for c, ink in zip(boxed, inks):
        x0, y0, x1, y1 = ink
        c.bbox = Rect(float(x0), float(y0), float(x1 - x0), float(y1 - y0))
        c.box["rect"] = cm.box_rect_from_ink(ink, float(c.box["pad_x"]), float(c.box["pad_y"]))
    return caps, lays, styles


def render_captions(out: Path, emoji: bool = True) -> tuple[Path, list[CaptionBox]]:
    """The caption test MP4 (W x H, DUR s, static texture) and its IR captions."""
    from shortkit.edit import captions as cm

    tmp = out.parent
    fonts_dir = tmp / "fonts"
    caps, lays, styles = caption_irs(fonts_dir)
    doc = cm.AssDoc(W, H)
    doc.styles += list(styles.values())
    doc.styles.append(cm.style_line("deco", _font().ass_name, 20, "#FFFFFF", "#000000", "#000000", 400, 0, 0))
    for c in caps:
        doc.events += cm.caption_events(c, lays[c.id], c.role)
    if emoji:
        d = EMOJI_DISK
        cap = next(c for c in caps if c.id == d["caption"])
        pts = [(d["r"] * np.cos(a), d["r"] * np.sin(a)) for a in np.linspace(0, 2 * np.pi, 40, endpoint=False)]
        cmds, *_ = cm._drawing([pts])
        doc.events.append(cm.AssEvent(3, cap.start, cap.end, "deco",
                                      f"{{\\an7\\pos({d['x']},{d['y']})\\bord0\\shad0\\1c{cm.ass_bgr(d['color'])}\\p3}}"
                                      + cmds + "{\\p0}"))
    ass = tmp / (out.stem + ".ass")
    ass.write_text(doc.render(), encoding="utf-8")
    base = write_frames(tmp / (out.stem + "_base.mp4"), (smooth_texture(W, H) for _ in range(int(DUR * FPS))), W, H)
    rel_ass, rel_fonts = os.path.relpath(ass, tmp), os.path.relpath(fonts_dir, tmp)
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-i", base.name, "-vf",
                    f"subtitles=filename={rel_ass}:fontsdir={rel_fonts},scale=out_color_matrix=bt709:out_range=tv,"
                    "format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "16", out.name],
                   check=True, cwd=tmp)
    return out, caps


def media_ctx(mp4: Path, captions=(), clips=(), decorations=(), canvas: dict | None = None, audio=None, preset=None,
              mode: str = "test", plan: dict | None = None):
    """A QAContext-like object for probe functions (no episode folder)."""
    from shortkit.util.media import probe

    info = probe(mp4)
    info_ns = SimpleNamespace(width=int(info.width), height=int(info.height), duration=float(info.duration),
                              fps=float(info.fps or FPS), has_audio=bool(getattr(info, "has_audio", False)),
                              audio_rate=getattr(info, "audio_rate", None))
    res = SimpleNamespace(mode=mode, format_id="UNCLASSIFIED", clips=list(clips), captions=list(captions),
                          decorations=list(decorations), canvas=canvas or {"width": info_ns.width,
                                                                              "height": info_ns.height, "fps": FPS,
                                                                              "background": {"type": "color",
                                                                                             "color": "#000000"}},
                          audio=audio or SimpleNamespace(sfx=[], originals=[], bgm=None), duration=info_ns.duration)
    if preset is None:
        from shortkit import config

        preset = config.load_preset("joshuamagazine")
    return SimpleNamespace(mp4=Path(mp4), fps=info_ns.fps, info=info_ns, resolved=res, canvas_w=info_ns.width,
                           canvas_h=info_ns.height, options={}, preset=preset, plan=plan or {}, episode_id="synth",
                           frames_dir=Path(mp4).parent, stems={}, reference_analysis={}, reference_id=None,
                           reference_mp4=None, reference_info={})


# ----------------------------------------------------------------------------- clips through the production compositor
GEN = "assets/test/generated"


def clip(cid: str, source: str, src_in: float, out_start: float, out_end: float, region, **kw):
    from shortkit.edit.ir import Clip
    from shortkit.util.media import probe

    info = probe(paths.absp(source))
    base = dict(id=cid, source_id=cid, source_path=source, src_in=src_in, src_out=src_in + (out_end - out_start),
                speed=1.0, out_start=out_start, out_end=out_end, region=Rect(*region), fit="cover",
                src_size=(int(info.width), int(info.height)))
    base.update(kw)
    return Clip(**base)


def render_clips(out: Path, clips: list, canvas: dict, duration: float) -> Path:
    """Frames of ``clips`` exactly as shortkit.edit.render.Compositor draws them (no captions / audio)."""
    from shortkit.edit.render import Compositor

    r = SimpleNamespace(canvas=canvas, clips=clips, captions=[], decorations=[])
    comp = Compositor(r)
    n = int(round(duration * float(canvas["fps"])))
    try:
        write_frames(out, (comp.frame(k) for k in range(n)), int(canvas["width"]), int(canvas["height"]),
                     float(canvas["fps"]))
    finally:
        comp.close()
    return out


def probe_caption_items(ctx) -> dict:
    """The per-caption output measurements of probes_text.probe_captions without its evidence files / font pools:
    locate at rest, onset / offset / entrance (measure_timing), and the style extras (caption_style_extras)."""
    from shortkit.qa import CAPTION_REST_SETTLE_S
    from shortkit.qa import probes_text as pt
    from shortkit.qa.probes_video import grab

    fr_ = 1.0 / ctx.fps
    out = {}
    for cap in ctx.resolved.captions:
        dur_in = float((cap.motion_in or {}).get("dur_s") or 0.0)
        t_rest = min(cap.start + dur_in + CAPTION_REST_SETTLE_S, (cap.start + cap.end) / 2)
        t_rest = max(cap.start + fr_, min(t_rest, cap.end - 2 * fr_))
        frame = grab(ctx.mp4, t_rest)
        loc = pt.locate_caption(frame, cap)
        item = {"id": cap.id, "role": cap.role, "t_rest": round(t_rest, 3), **{k: v for k, v in loc.items() if k != "bbox"}}
        if loc.get("found"):
            item["bbox_obs"] = loc["bbox"]
            item.update(pt.measure_timing(ctx, cap, loc, frame))
            item.update(pt.caption_style_extras(ctx, cap, loc, frame, t_rest, item))
        out[cap.id] = item
    return out
