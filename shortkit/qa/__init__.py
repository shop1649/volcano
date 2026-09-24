"""Output QA on the FINAL MP4 (docs/CONTRACT.md section 10).

Principle: every observation comes from measuring the rendered MP4 itself (frames, OCR, the
decoded audio mix).  ``build/resolved.json`` supplies only the *expected* values that the
measurements are compared with; it is never taken as evidence that the output is right.

Modules
    probes_text   caption OCR / ink bbox / onset-offset / motion_in / font / identity text
    probes_video  cuts & transitions / zoom / freeze / decorations / faces / logo residual /
                  source mapping / canvas layout
    probes_audio  BGM search (file, tempo, section) + per-window least-squares gains, original
                  audio presence, SFX matched filter, unexplained onsets, loudness
    checks        rows {check_id, item, category, reference, expected, observed, tolerance,
                  status, intended_change, change_ref, evidence, note} + declarations()
    sheet         compare sheet PNGs (1-second grid, caption strip, 0.5-second SFX strip)
    report        report.json / report.md
    gate          pass/fail rules
    defects       defects.jsonl lifecycle (found -> fix note -> automatic re-check)
    cli           `shortkit qa ...`

This package ``__init__`` stays import-light: ``shortkit.config`` imports
``shortkit.qa.checks.declarations`` while building the registry.
"""
from __future__ import annotations

import contextlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

QA_SCHEMA = "shortkit.qa_report/1"

# Tesseract's OpenMP threads busy-wait; on the shared 4-core build machine one OCR call went from
# ~0.2 s to minutes.  Every tesseract process QA starts (pytesseract here, shortkit.clean's OCR
# through clean.verify.residual_score) inherits os.environ, so the limit is set at import AND
# forced to 1 around every call (``tesseract_env``) even when the caller's shell set another value.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")


@contextlib.contextmanager
def tesseract_env():
    """Run the enclosed tesseract call(s) with ``OMP_THREAD_LIMIT=1`` (restored afterwards)."""
    old = os.environ.get("OMP_THREAD_LIMIT")
    os.environ["OMP_THREAD_LIMIT"] = "1"
    try:
        yield
    finally:
        if old is None:
            os.environ.pop("OMP_THREAD_LIMIT", None)
        else:
            os.environ["OMP_THREAD_LIMIT"] = old


class QAError(RuntimeError):
    """A QA run cannot start (missing inputs).  Measurement failures never raise this: they
    become ``unmeasured`` rows with a reason."""


# ----------------------------------------------------------------------------- small helpers
def hex_rgb(color: str | None, default: tuple[int, int, int] | None = None) -> tuple[int, int, int] | None:
    """'#RRGGBB' / 'RRGGBB' / '&HAABBGGRR' (ASS) -> (r, g, b)."""
    if not color:
        return default
    c = str(color).strip()
    try:
        if c.upper().startswith("&H"):
            h = c[2:].rstrip("&")
            h = h[-6:].rjust(6, "0")
            b, g, r = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return (r, g, b)
        c = c.lstrip("#")
        if len(c) == 3:
            c = "".join(ch * 2 for ch in c)
        return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))
    except (ValueError, IndexError):
        return default


def rgb_hex(rgb) -> str | None:
    if rgb is None:
        return None
    r, g, b = (int(round(float(v))) for v in rgb[:3])
    return "#{:02X}{:02X}{:02X}".format(max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


def rect_xywh(r: Any) -> tuple[float, float, float, float]:
    if r is None:
        raise ValueError("rect is None")
    if isinstance(r, dict):
        return float(r["x"]), float(r["y"]), float(r["w"]), float(r["h"])
    if hasattr(r, "x"):
        return float(r.x), float(r.y), float(r.w), float(r.h)
    x, y, w, h = r
    return float(x), float(y), float(w), float(h)


def rect_intersection(a, b) -> float:
    ax, ay, aw, ah = rect_xywh(a)
    bx, by, bw, bh = rect_xywh(b)
    iw = min(ax + aw, bx + bw) - max(ax, bx)
    ih = min(ay + ah, by + bh) - max(ay, by)
    return max(0.0, iw) * max(0.0, ih)


def rect_iou(a, b) -> float:
    inter = rect_intersection(a, b)
    _, _, aw, ah = rect_xywh(a)
    _, _, bw, bh = rect_xywh(b)
    union = aw * ah + bw * bh - inter
    return inter / union if union > 0 else 0.0


def rect_center(r) -> tuple[float, float]:
    x, y, w, h = rect_xywh(r)
    return x + w / 2.0, y + h / 2.0


def overlaps(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def in_ranges(t: float, ranges, pad: float = 0.0) -> bool:
    return any(float(a) - pad <= t <= float(b) + pad for a, b in ranges or [])


def merge_ranges(ranges, gap: float = 0.0) -> list[list[float]]:
    out: list[list[float]] = []
    for a, b in sorted((float(a), float(b)) for a, b in ranges):
        if out and a <= out[-1][1] + gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def rnd(v, d: int = 3):
    if v is None:
        return None
    try:
        return round(float(v), d)
    except (TypeError, ValueError):
        return v


# ----------------------------------------------------------------------------- geometry of a clip
def clip_transform(clip, t: float | None = None) -> dict:
    """Affine mapping SOURCE px -> CANVAS px for ``clip`` at output time ``t``.

    Convention (documented; the renderer must match it and QA measures whether it does):
    the source (after ``crop``) is scaled uniformly to cover/contain ``region`` and centred in
    it; a zoom scales the fitted picture by z(t) about the canvas position of
    ``zoom.center_src`` clamped into the region (that point stays put).  Returns
    {s, tx, ty, visible:[x,y,w,h]} with canvas = s * src + (tx, ty).
    """
    rx, ry, rw, rh = rect_xywh(clip.region)
    sw, sh = clip.src_size
    if clip.crop is not None:
        cx, cy, cw, ch = rect_xywh(clip.crop)
    else:
        cx, cy, cw, ch = 0.0, 0.0, float(sw), float(sh)
    if cw <= 0 or ch <= 0:
        cw, ch = float(sw), float(sh)
    s = max(rw / cw, rh / ch) if (clip.fit or "cover") == "cover" else min(rw / cw, rh / ch)
    tx = rx + rw / 2.0 - (cx + cw / 2.0) * s
    ty = ry + rh / 2.0 - (cy + ch / 2.0) * s
    z = zoom_scale(clip, t) if t is not None else 1.0
    if clip.zoom is not None and abs(z - 1.0) > 1e-6:
        px, py = clip.zoom.center_src
        ox = min(max(px * s + tx, rx), rx + rw)     # canvas position of the zoom centre (fixed)
        oy = min(max(py * s + ty, ry), ry + rh)
        tx = ox - (ox - tx) * z
        ty = oy - (oy - ty) * z
        s = s * z
    vis_x0 = max(rx, cx * s + tx)
    vis_y0 = max(ry, cy * s + ty)
    vis_x1 = min(rx + rw, (cx + cw) * s + tx)
    vis_y1 = min(ry + rh, (cy + ch) * s + ty)
    return {"s": s, "tx": tx, "ty": ty,
            "visible": [vis_x0, vis_y0, max(0.0, vis_x1 - vis_x0), max(0.0, vis_y1 - vis_y0)]}


def ease_value(u: float, ease: str | None) -> float:
    """Ease curves (cubic), identical definitions to the renderer's contract:
    in = u^3, out = 1-(1-u)^3, inout = cubic in-out, linear = u."""
    u = min(1.0, max(0.0, u))
    e = (ease or "linear").lower()
    if e == "in":
        return u ** 3
    if e == "out":
        return 1.0 - (1.0 - u) ** 3
    if e == "inout":
        return 4 * u ** 3 if u < 0.5 else 1.0 - (-2.0 * u + 2.0) ** 3 / 2.0
    return u


def zoom_scale(clip, t: float | None) -> float:
    z = clip.zoom
    if z is None or t is None:
        return 1.0
    t0 = clip.out_start + float(z.start)
    if t <= t0:
        return float(z.scale_from)
    if z.dur <= 0 or t >= t0 + z.dur:
        return float(z.scale_to)
    return float(z.scale_from) + (float(z.scale_to) - float(z.scale_from)) * ease_value((t - t0) / z.dur, z.ease)


def map_src_rect(clip, rect, t: float | None = None) -> list[float] | None:
    """SOURCE rect -> CANVAS rect (clipped to the visible picture). None if not visible."""
    x, y, w, h = rect_xywh(rect)
    tr = clip_transform(clip, t)
    s, tx, ty = tr["s"], tr["tx"], tr["ty"]
    ox, oy, ow, oh = x * s + tx, y * s + ty, w * s, h * s
    vx, vy, vw, vh = tr["visible"]
    x0, y0 = max(ox, vx), max(oy, vy)
    x1, y1 = min(ox + ow, vx + vw), min(oy + oh, vy + vh)
    if x1 - x0 < 1 or y1 - y0 < 1:
        return None
    return [x0, y0, x1 - x0, y1 - y0]


def src_time(clip, t: float) -> float:
    """Output time -> source time shown inside ``clip``: speed scales; a freeze holds
    ``freeze.src_t`` for ``hold`` seconds and playback then continues from the held frame."""
    sp = float(clip.speed or 1.0)
    u = t - clip.out_start
    move = (clip.src_out - clip.src_in) / sp
    f = clip.freeze
    if f is None:
        return float(clip.src_in) + min(max(u, 0.0), move) * sp
    f_local = f.out_start - clip.out_start
    if u < f_local:
        return float(clip.src_in) + max(u, 0.0) * sp
    if u < f_local + f.hold:
        return float(f.src_t)
    return min(float(clip.src_out), float(f.src_t) + (u - f_local - f.hold) * sp)


def clip_at(resolved, t: float):
    """The clip on top at output time t (a later clip wins during its transition)."""
    best = None
    for c in resolved.clips:
        if c.out_start - 1e-6 <= t < c.out_end + 1e-6:
            best = c
    return best


# ----------------------------------------------------------------------------- context
@dataclass
class QAContext:
    episode_id: str
    resolved: Any                    # shortkit.edit.ir.ResolvedEdit
    preset: Any                      # shortkit.config.Preset
    plan: dict | None
    mp4: Path
    info: Any                        # shortkit.util.media.ProbeInfo
    qa_dir: Path
    reference_mp4: Path | None = None
    reference_id: str | None = None
    reference_analysis: dict = field(default_factory=dict)
    stems: dict = field(default_factory=dict)
    options: dict = field(default_factory=dict)

    @property
    def canvas_w(self) -> int:
        return int(self.resolved.canvas.get("width") or self.info.width)

    @property
    def canvas_h(self) -> int:
        return int(self.resolved.canvas.get("height") or self.info.height)

    @property
    def fps(self) -> float:
        return float(self.info.fps or self.resolved.canvas.get("fps") or 30.0)

    @property
    def frames_dir(self) -> Path:
        d = self.qa_dir / "frames"
        d.mkdir(parents=True, exist_ok=True)
        return d


def load_context(episode_id: str, reference: str | None = None, mp4: str | None = None,
                 reference_id: str | None = None, options: dict | None = None) -> QAContext:
    from .. import paths
    from ..config import load_preset
    from ..edit.ir import ResolvedEdit
    from ..util.jsonio import read_json, read_yaml
    from ..util.media import probe

    ep = paths.episode_dir(episode_id)
    rj = ep / "build" / "resolved.json"
    d = read_json(rj)
    if d is None:
        raise QAError(f"{paths.relp(rj) if rj.is_absolute() else rj} 없음 — 먼저 `shortkit episode render` 로 "
                      "resolved.json 과 출력 MP4 를 만드세요")
    resolved = ResolvedEdit.from_dict(d)
    fmt = resolved.format_id if resolved.format_id and resolved.format_id != "UNCLASSIFIED" else None
    preset = load_preset(resolved.preset_name, fmt)
    preset.assert_same_preset(resolved.preset_id, "build/resolved.json")
    out = paths.absp(mp4) if mp4 else paths.absp(resolved.output_path or f"episodes/{episode_id}/output/{episode_id}.mp4")
    if not out.is_file():
        raise QAError(f"출력 MP4 없음: {resolved.output_path} — 렌더가 끝난 최종 MP4 만 검수합니다")
    info = probe(out)
    plan = read_yaml(ep / "plan.yaml")
    qa_dir = ep / "qa"
    qa_dir.mkdir(parents=True, exist_ok=True)
    stems = {p.stem: p for p in sorted((ep / "build" / "stems").glob("*.wav"))} if (ep / "build" / "stems").is_dir() else {}
    ref_path = paths.absp(reference) if reference else None
    if ref_path is not None and not ref_path.is_file():
        raise QAError(f"레퍼런스 MP4 없음: {reference}")
    rid = reference_id or (ref_path.stem if ref_path else None)
    analysis = load_reference_analysis(resolved.preset_name, rid) if rid else {}
    return QAContext(episode_id=episode_id, resolved=resolved, preset=preset, plan=plan, mp4=out, info=info,
                     qa_dir=qa_dir, reference_mp4=ref_path, reference_id=rid, reference_analysis=analysis,
                     stems=stems, options=dict(options or {}))


def load_reference_analysis(preset_name: str, video_id: str) -> dict:
    """Read presets/<name>/analysis/<video_id>/{shots,captions,motion,layout}.json and
    audio/{bgm,original,sfx_events}.json when they exist (written by the reference modules)."""
    from .. import paths
    from ..util.jsonio import read_json

    base = paths.preset_dir(preset_name) / "analysis" / video_id
    out: dict = {}
    if not base.is_dir():
        return out
    for name in ("shots", "captions", "motion", "layout"):
        v = read_json(base / f"{name}.json")
        if v is not None:
            out[name] = v
    for name in ("bgm", "original", "sfx_events"):
        v = read_json(base / "audio" / f"{name}.json")
        if v is not None:
            out[f"audio_{name}"] = v
    return out


def run_episode(episode_id: str, reference: str | None = None, sheet_seconds: float = 15.0,
                mp4: str | None = None, reference_id: str | None = None, only: list[str] | None = None,
                recheck_others: bool = True, quiet: bool = False) -> dict:
    """Full QA run: probes -> rows -> sheet -> report -> gate -> defects.  Returns report dict."""
    from .report import run_and_write

    return run_and_write(episode_id, reference=reference, sheet_seconds=sheet_seconds, mp4=mp4,
                         reference_id=reference_id, only=only, recheck_others=recheck_others, quiet=quiet)
