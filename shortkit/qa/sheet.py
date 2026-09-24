"""Compare sheet PNGs: reference vs ours at the SAME absolute times.

Layout per page (``seconds`` columns, one per second t = page*seconds + k):

    [label] | t=0 | t=1 | ...
    레퍼런스 프레임       frame at t (reference MP4)            or '레퍼런스 없음(못 잼)'
    레퍼런스 자막         caption text active at t (captions.json) or '못 잼'
    레퍼런스 효과음       two 0.5 s cells per second, SFX type ids (audio/sfx_events.json) or '못 잼'
    우리 프레임           frame at t (output MP4)
    우리 자막             caption text active at t (measured onset/offset; '?' = timing not measured)
    우리 효과음           two 0.5 s cells per second, SFX type ids detected in the output mix
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from . import QAContext

CELL_W = 132
LABEL_W = 150
HEAD_H = 46
CAP_H = 64
SFX_H = 34
BG = (250, 250, 250)
GRID = (190, 190, 190)
INK = (20, 20, 20)
MUTED = (140, 140, 140)
REF_TINT = (236, 242, 250)
OURS_TINT = (246, 246, 236)


def label_font(size: int = 16):
    """A Korean-capable font for labels (exact family lookup; falls back to fontconfig ko)."""
    from PIL import ImageFont

    cands = []
    try:
        from ..fonts import find_font, font_face_index

        for name in ("Noto Sans CJK KR Bold", "Noto Sans CJK KR Regular", "NanumGothic Bold", "NanumGothic"):
            p = find_font(name)
            if p is not None:
                cands.append((p, font_face_index(p, name) or 0))
                break
    except Exception:
        pass
    if not cands:
        import subprocess

        try:
            out = subprocess.run(["fc-match", "-f", "%{file}|%{index}", ":lang=ko"], capture_output=True, text=True,
                                 timeout=10).stdout
            if out and "|" in out:
                f, i = out.split("|", 1)
                cands.append((Path(f), int(i or 0)))
        except Exception:
            pass
    for p, idx in cands:
        try:
            return ImageFont.truetype(str(p), size, index=idx), True
        except Exception:
            continue
    return ImageFont.load_default(), False


def _frames_at(path, times: list[float], width: int) -> dict[float, np.ndarray]:
    from ..util.media import iter_frames, probe

    out = {}
    if path is None:
        return out
    info = probe(path)
    want = sorted(t for t in times if t < info.duration)
    if not want:
        return out
    j = 0
    for t, fr in iter_frames(path, fps=1, width=width):
        while j < len(want) and want[j] <= t + 0.5:
            if abs(want[j] - t) <= 0.51:
                out[want[j]] = fr.copy()
            j += 1
        if j >= len(want):
            break
    return out


def _wrap(draw, text: str, font, width: int, max_lines: int = 3) -> list[str]:
    lines: list[str] = []
    for para in (text or "").split("\n"):
        cur = ""
        for ch in para:
            if draw.textlength(cur + ch, font=font) <= width:
                cur += ch
            else:
                lines.append(cur)
                cur = ch
        lines.append(cur)
    lines = [l for l in lines if l is not None]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        lines[-1] = lines[-1][:-1] + "…" if lines[-1] else "…"
    return lines


def ours_caption_track(ctx: QAContext, text_probe: dict | None) -> list[dict]:
    meas = {c["id"]: c for c in (text_probe or {}).get("captions") or []}
    out = []
    for cap in ctx.resolved.captions:
        m = meas.get(cap.id) or {}
        on, off = m.get("onset"), m.get("offset")
        measured = on is not None and off is not None and m.get("found")
        out.append({"start": on if on is not None else cap.start, "end": off if off is not None else cap.end,
                    "text": cap.text.replace("\n", " "), "role": cap.role, "measured": bool(measured),
                    "found": bool(m.get("found"))})
    return out


def reference_caption_track(ctx: QAContext) -> list[dict] | None:
    c = ctx.reference_analysis.get("captions")
    if not c:
        return None
    return [{"start": float(i.get("start", 0)), "end": float(i.get("end", 0)), "text": str(i.get("text") or ""),
             "role": i.get("role"), "measured": True, "found": True} for i in c.get("items") or []]


def reference_sfx_track(ctx: QAContext) -> list[dict] | None:
    s = ctx.reference_analysis.get("audio_sfx_events")
    if not s:
        return None
    return [{"t": float(e.get("t", 0)), "type": e.get("type_id") or "?"} for e in s.get("events") or []]


def make_sheets(ctx: QAContext, text_probe: dict | None, audio_probe: dict | None, seconds: float = 15.0) -> list[str]:
    from PIL import Image, ImageDraw

    from .. import paths

    seconds = max(1, int(round(seconds or 15)))
    font, korean_ok = label_font(15)
    small, _ = label_font(12)
    head, _ = label_font(18)
    W, H = ctx.info.width, ctx.info.height
    th = int(round(CELL_W * H / W))
    ref_info = None
    if ctx.reference_mp4 is not None:
        from ..util.media import probe

        ref_info = probe(ctx.reference_mp4)
    dur = max(ctx.info.duration, ref_info.duration if ref_info else 0.0)
    n_sec = int(math.ceil(dur))
    times = [float(t) for t in range(n_sec)]
    ours_fr = _frames_at(ctx.mp4, times, CELL_W)
    ref_fr = {}
    ref_th = th
    if ref_info is not None:
        ref_th = int(round(CELL_W * ref_info.height / ref_info.width))
        ref_fr = _frames_at(ctx.reference_mp4, times, CELL_W)
    ours_caps = ours_caption_track(ctx, text_probe)
    ref_caps = reference_caption_track(ctx) if ref_info is not None else None
    ours_sfx = [{"t": d["t"], "type": d["type"]} for d in ((audio_probe or {}).get("sfx") or {}).get("detections") or []]
    ours_sfx_measured = (audio_probe or {}).get("status") == "measured"
    ref_sfx = reference_sfx_track(ctx) if ref_info is not None else None
    pages = max(1, int(math.ceil(n_sec / seconds)))
    out_files = []
    rows_spec = [("레퍼런스 프레임", "ref_frame", ref_th), ("레퍼런스 자막", "ref_cap", CAP_H), ("레퍼런스 효과음(0.5초)", "ref_sfx", SFX_H),
                 ("우리 프레임", "our_frame", th), ("우리 자막", "our_cap", CAP_H), ("우리 효과음(0.5초)", "our_sfx", SFX_H)]
    for pg in range(pages):
        cols = list(range(pg * seconds, min(n_sec, (pg + 1) * seconds)))
        width = LABEL_W + CELL_W * max(1, len(cols))
        height = HEAD_H + 24 + sum(h for _, _, h in rows_spec) + 8 * len(rows_spec) + 30
        img = Image.new("RGB", (width, height), BG)
        dr = ImageDraw.Draw(img)
        title = (f"{ctx.episode_id} 비교 시트 {pg + 1}/{pages}  (같은 절대 시각, 1초 격자, 효과음 0.5초 칸)  "
                 f"레퍼런스: {ctx.reference_id or '없음'}")
        dr.text((8, 12), title, fill=INK, font=head)
        y = HEAD_H
        for k, t in enumerate(cols):
            dr.text((LABEL_W + k * CELL_W + 4, y + 2), f"t={t}s", fill=INK, font=font)
        y += 24
        for label, kind, h in rows_spec:
            tint = REF_TINT if kind.startswith("ref") else OURS_TINT
            dr.rectangle([0, y, width - 1, y + h], fill=tint)
            dr.text((6, y + max(2, h // 2 - 9)), label, fill=INK, font=font)
            is_ref = kind.startswith("ref")
            if is_ref and ref_info is None:
                dr.rectangle([LABEL_W, y, width - 1, y + h], fill=(230, 230, 230))
                dr.text((LABEL_W + 10, y + max(2, h // 2 - 9)), "레퍼런스 없음(못 잼)", fill=MUTED, font=font)
                y += h + 8
                continue
            for k, t in enumerate(cols):
                x0 = LABEL_W + k * CELL_W
                dr.rectangle([x0, y, x0 + CELL_W - 1, y + h], outline=GRID)
                if kind.endswith("frame"):
                    fr = (ref_fr if is_ref else ours_fr).get(float(t))
                    if fr is not None:
                        im = Image.fromarray(fr)
                        if im.size[1] > h:
                            im = im.crop((0, 0, im.size[0], h))
                        img.paste(im, (x0, y))
                    else:
                        dr.text((x0 + 6, y + h // 2 - 8), "프레임 없음", fill=MUTED, font=small)
                elif kind.endswith("cap"):
                    track = ref_caps if is_ref else ours_caps
                    if track is None:
                        dr.text((x0 + 4, y + 4), "자막 분석 없음\n(못 잼)", fill=MUTED, font=small)
                        continue
                    act = [c for c in track if c["start"] <= t + 0.5 < c["end"]]
                    txt = " / ".join(("" if c["measured"] else "?") + c["text"] for c in act)
                    for li, line in enumerate(_wrap(dr, txt, small, CELL_W - 8, 4)):
                        dr.text((x0 + 4, y + 3 + li * 15), line, fill=INK, font=small)
                else:
                    track = ref_sfx if is_ref else (ours_sfx if ours_sfx_measured else None)
                    for half in (0, 1):
                        hx = x0 + half * CELL_W // 2
                        dr.rectangle([hx, y, hx + CELL_W // 2 - 1, y + h], outline=GRID)
                        if track is None:
                            dr.text((hx + 3, y + 8), "못 잼", fill=MUTED, font=small)
                            continue
                        a, b_ = t + 0.5 * half, t + 0.5 * half + 0.5
                        ids = [s["type"] for s in track if a <= s["t"] < b_]
                        if ids:
                            dr.rectangle([hx + 1, y + 1, hx + CELL_W // 2 - 2, y + h - 1], fill=(255, 226, 180))
                            dr.text((hx + 3, y + 8), ",".join(ids)[:12], fill=INK, font=small)
            y += h + 8
        foot = ("? = 등장/퇴장 시각을 측정하지 못해 계획 시각으로 표시. 우리 효과음 = 출력 믹스 정합 필터 검출."
                + ("" if korean_ok else " (한글 글꼴 없음)"))
        dr.text((8, y + 4), foot, fill=MUTED, font=small)
        name = "compare_sheet.png" if pg == 0 else f"compare_sheet_p{pg + 1:02d}.png"
        p = ctx.qa_dir / name
        img.save(p)
        out_files.append(paths.relp(p))
    # remove stale extra pages from an earlier, longer run
    for old in ctx.qa_dir.glob("compare_sheet_p*.png"):
        if paths.relp(old) not in out_files:
            old.unlink()
    return out_files
