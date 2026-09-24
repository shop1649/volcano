"""plan.yaml + preset -> ResolvedEdit (shortkit/edit/ir.py).

Everything downstream (ffmpeg render, MLT/FCPXML/OTIO export, QA) consumes only the IR, the
ONE ASS file and ``build/caption_layout.json``.  Preset style values are read only through
``Preset.get`` / ``Preset.section`` so the registry can link each key to this code.

Time model (output seconds):
    clip.out_start = previous out_end            (cut / flash)
                   = previous out_end - dur      (crossfade: overlaps the previous clip by dur)
    clip.out_end   = out_start + (src_out - src_in) / speed + freeze.hold
Geometry (canvas px): the (cleaned, cropped) source is fitted into canvas.video_region
(cover/contain, centred), then zoomed about zoom.center (SOURCE px) which stays fixed on
screen; see ``src_to_region``.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import config, paths
from ..util.hashing import sha256_file
from ..util.jsonio import now_iso, write_json
from ..util.media import MediaError, probe
from . import captions as cap_mod
from .ir import (SCHEMA, CaptionBox, Clip, Decoration, Freeze, Rect, ResolvedEdit, TimedRect, Transition,
                 Zoom)
from .plan import TEST_FORMAT_ID, build_dir, load_plan

MOTION_IN_TYPES = ("none", "fade", "pop", "slide_up")
MOTION_OUT_TYPES = ("none", "fade")
EASES = ("linear", "in", "out", "inout")
FLASH_SCOPES = ("region", "canvas")
ROLES = ("title", "description", "situation", "speaker", "dialogue", "reaction")
EPS = 1e-6


# ----------------------------------------------------------------------------- issues
def issue(severity: str, code: str, message_ko: str, where: str = "") -> dict:
    assert severity in ("error", "warn")
    return {"severity": severity, "code": code, "message_ko": message_ko, "where": where}


class ResolveError(RuntimeError):
    def __init__(self, issues: list[dict]):
        self.issues = issues
        errs = [i for i in issues if i["severity"] == "error"]
        super().__init__("resolve 실패: " + "; ".join(f"[{i['code']}] {i['message_ko']}" for i in errs[:8]))


@dataclass
class SourceInfo:
    id: str
    path: str                  # root-relative (plan)
    abs: Path
    exists: bool
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    has_audio: bool = False
    plan: dict = field(default_factory=dict)


@dataclass
class ResolveContext:
    plan: dict
    preset: config.Preset
    resolved: ResolvedEdit | None
    issues: list[dict]
    sources: dict[str, SourceInfo]
    layouts: dict[str, cap_mod.Layout] = field(default_factory=dict)
    fonts: dict[str, cap_mod.ResolvedFont] = field(default_factory=dict)
    role_styles: dict[str, dict] = field(default_factory=dict)

    @property
    def errors(self) -> list[dict]:
        return [i for i in self.issues if i["severity"] == "error"]


# ----------------------------------------------------------------------------- preset helpers
def preset_for_plan(plan: dict, preset_name: str | None = None) -> config.Preset:
    """Load the preset the plan belongs to (by preset_id), or the explicitly named one.
    The mixing guard runs in validate (explicit preset whose id differs -> error)."""
    name = preset_name or config.preset_name_for_id(plan["preset_id"])
    fmt = plan.get("format_id")
    return config.load_preset(name, None if (not fmt or fmt == TEST_FORMAT_ID) else fmt)


ROLE_SCHEMA: dict[str, Any] = {
    "font_name": None, "font_file": None, "bold": None, "size_px": None, "color": None,
    "highlight_color": None, "outline_px": None, "outline_color": None, "shadow_px": None,
    "shadow_color": None, "line_spacing": None, "max_width_px": None, "max_lines": None,
    "max_chars_per_line": None, "persist": None, "quote_marks": "optional",
    "box": {"enabled": None, "color": None, "alpha": None, "pad_x": None, "pad_y": None},
    "anchor": {"x": None, "y": None, "align": None, "valign": None},
    "motion_in": {"type": None, "dur_s": None, "scale_from": None, "offset_px": None},
    "motion_out": {"type": None, "dur_s": None},
    "timing": {"lead_s": None, "min_dur_s": None},
}


def read_role_style(preset: config.Preset, role: str, issues: list[dict]) -> dict | None:
    """Read every supported key of text.roles.<role> through the preset (traced).
    Keys the renderer does not implement are reported, never silently read."""
    try:
        sec = preset.section(f"text.roles.{role}")
    except (KeyError, TypeError):
        issues.append(issue("error", "role_style_missing", f"프리셋에 text.roles.{role} 이 없습니다", f"text.roles.{role}"))
        return None

    def read_role_style_tree(m, schema, prefix):
        present = set(iter(m))          # key listing only (TrackedMapping records reads on __contains__)
        out = {}
        for k in present:
            if k not in schema:
                issues.append(issue("warn", "preset_key_unsupported",
                                    f"렌더러가 구현하지 않은 프리셋 키: {prefix}.{k} (읽지 않음)", f"{prefix}.{k}"))
        for k, sub in schema.items():
            if k not in present:
                if sub == "optional":
                    continue
                issues.append(issue("error", "role_key_missing", f"프리셋 키 없음: {prefix}.{k}", f"{prefix}.{k}"))
                continue
            if isinstance(sub, dict):
                out[k] = read_role_style_tree(m[k], sub, f"{prefix}.{k}")
            else:
                v = m[k]
                out[k] = list(v) if isinstance(v, (list, tuple)) else v
        return out

    st = read_role_style_tree(sec, ROLE_SCHEMA, f"text.roles.{role}")
    flat = dict(st)
    for grp in ("anchor",):
        if grp in st:
            flat["align"] = st[grp].get("align")
            flat["valign"] = st[grp].get("valign")
    return flat


def read_canvas(preset: config.Preset) -> dict:
    c = preset.section("canvas")
    bg = c["background"]
    vr = c["video_region"]
    sm = c["safe_margin"]
    return {"width": int(c["width"]), "height": int(c["height"]), "fps": float(c["fps"]),
            "background": {"type": bg["type"], "color": bg["color"], "blur_sigma": float(bg["blur_sigma"])},
            "video_region": {"x": float(vr["x"]), "y": float(vr["y"]), "w": float(vr["w"]), "h": float(vr["h"]),
                             "fit": vr["fit"]},
            "safe_margin": {k: float(sm[k]) for k in ("left", "right", "top", "bottom")}}


# ----------------------------------------------------------------------------- geometry
def effective_src_rect(clip: Clip) -> tuple[float, float, float, float]:
    if clip.crop:
        return clip.crop.x, clip.crop.y, clip.crop.w, clip.crop.h
    return 0.0, 0.0, float(clip.src_size[0]), float(clip.src_size[1])


def base_fit(clip: Clip) -> tuple[float, float, float]:
    """(scale, off_x, off_y): region-local q = off + scale * (p_src - crop_xy)."""
    ex, ey, ew, eh = effective_src_rect(clip)
    R = clip.region
    s = max(R.w / ew, R.h / eh) if clip.fit == "cover" else min(R.w / ew, R.h / eh)
    return s, (R.w - ew * s) / 2.0, (R.h - eh * s) / 2.0


def ease(p: float, kind: str) -> float:
    p = min(1.0, max(0.0, p))
    if kind == "in":
        return p ** 3
    if kind == "out":
        return 1.0 - (1.0 - p) ** 3
    if kind == "inout":
        return 4 * p ** 3 if p < 0.5 else 1.0 - (-2.0 * p + 2.0) ** 3 / 2.0
    return p


def zoom_scale(clip: Clip, u: float) -> float:
    z = clip.zoom
    if not z:
        return 1.0
    if z.dur <= 0:
        return z.scale_to if u >= z.start else z.scale_from
    return z.scale_from + (z.scale_to - z.scale_from) * ease((u - z.start) / z.dur, z.ease)


def zoom_progress(clip: Clip, u: float) -> float:
    """Eased zoom progress in [0, 1] at local output time u (0 before start, 1 after start + dur)."""
    z = clip.zoom
    if not z:
        return 0.0
    if z.dur <= 0:
        return 1.0 if u >= z.start else 0.0
    return ease((u - z.start) / z.dur, z.ease)


def src_to_region(clip: Clip, u: float) -> tuple[float, float, float]:
    """Affine (s, tx, ty) with region-local q = s * (p_src - crop_xy) + t at local output time u.

    Fixed point (``Zoom.recenter`` false): the un-zoomed region position of ``zoom.center_src``,
    clamped into the region, stays where it is while the scale changes.  With recenter true that
    point moves (same eased progress) to the region centre; for ``fit = cover`` the translation is
    clamped so the scaled picture keeps covering the region."""
    b, ox, oy = base_fit(clip)
    z = zoom_scale(clip, u)
    if clip.zoom and z != 1.0:
        ex, ey, ew, eh = effective_src_rect(clip)
        cx, cy = clip.zoom.center_src
        R = clip.region
        px = min(max(ox + b * (cx - ex), 0.0), R.w)
        py = min(max(oy + b * (cy - ey), 0.0), R.h)
        if not getattr(clip.zoom, "recenter", False):
            return z * b, px * (1 - z) + z * ox, py * (1 - z) + z * oy
        w = zoom_progress(clip, u)
        qx, qy = px + (R.w / 2.0 - px) * w, py + (R.h / 2.0 - py) * w
        s = z * b
        tx, ty = qx - s * (cx - ex), qy - s * (cy - ey)
        if clip.fit == "cover":
            tx = min(0.0, max(R.w - s * ew, tx)) if s * ew >= R.w else tx
            ty = min(0.0, max(R.h - s * eh, ty)) if s * eh >= R.h else ty
        return s, tx, ty
    return b, ox, oy


def src_time_at(clip: Clip, u: float) -> float:
    """Source time displayed at local output time u (freeze holds; speed scales)."""
    move = (clip.src_out - clip.src_in) / clip.speed
    f = clip.freeze
    if f is None:
        return clip.src_in + min(max(u, 0.0), move) * clip.speed
    f_local = f.out_start - clip.out_start
    if u < f_local:
        return clip.src_in + max(u, 0.0) * clip.speed
    if u < f_local + f.hold:
        return f.src_t
    return min(clip.src_out, f.src_t + (u - f_local - f.hold) * clip.speed)


def map_src_rect(clip: Clip, u: float, rect: dict) -> tuple[float, float, float, float] | None:
    """SOURCE-px rect -> canvas-px rect (clipped to the video region) at local output time u."""
    s, tx, ty = src_to_region(clip, u)
    ex, ey, _, _ = effective_src_rect(clip)
    x0 = clip.region.x + tx + s * (rect["x"] - ex)
    y0 = clip.region.y + ty + s * (rect["y"] - ey)
    x1, y1 = x0 + s * rect["w"], y0 + s * rect["h"]
    R = clip.region
    x0, y0 = max(x0, R.x), max(y0, R.y)
    x1, y1 = min(x1, R.x + R.w), min(y1, R.y + R.h)
    if x1 <= x0 or y1 <= y0:
        return None
    return x0, y0, x1 - x0, y1 - y0


def clips_at(resolved: ResolvedEdit, t: float) -> list[Clip]:
    return [c for c in resolved.clips if c.out_start - EPS <= t < c.out_end - EPS]


def rects_intersect(a, b) -> bool:
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    return ax < bx + bw and bx < ax + aw and ay < by + bh and by < ay + ah


def src_to_out_time(clip: Clip, src_t: float) -> float:
    """Output time where source time src_t is shown (first occurrence)."""
    f = clip.freeze
    base = clip.out_start + (src_t - clip.src_in) / clip.speed
    if f is not None and src_t > f.src_t + EPS and f.src_t < clip.src_out - EPS:
        base += f.hold
    return base


# ----------------------------------------------------------------------------- sources
def probe_sources(plan: dict, issues: list[dict]) -> dict[str, SourceInfo]:
    out: dict[str, SourceInfo] = {}
    for s in plan.get("sources", []):
        where = f"sources[{s['id']}]"
        if s["id"] in out:
            issues.append(issue("error", "source_dup_id", f"소스 id 중복: {s['id']}", where))
        rel = s["path"]
        if os.path.isabs(rel) or rel.startswith("~"):
            issues.append(issue("error", "abs_path", f"절대 경로는 저장할 수 없습니다(루트 기준 상대 경로 사용): {rel}", where))
        ap = paths.absp(rel)
        si = SourceInfo(id=s["id"], path=rel, abs=ap, exists=ap.is_file(), plan=s)
        if si.exists:
            try:
                pi = probe(ap)
                si.duration, si.width, si.height, si.fps, si.has_audio = (pi.duration, pi.width, pi.height,
                                                                          pi.fps, pi.has_audio)
                if not pi.width:
                    issues.append(issue("error", "source_no_video", f"영상 스트림이 없습니다: {rel}", where))
            except MediaError as e:
                issues.append(issue("error", "source_probe_failed", f"소스를 읽지 못함: {rel}: {str(e)[:200]}", where))
                si.exists = False
        else:
            issues.append(issue("error", "source_missing", f"소스 파일이 없습니다: {rel}", where))
        out[s["id"]] = si
    return out


def _timed_rects(lst) -> list[TimedRect]:
    return [TimedRect(x=float(r["x"]), y=float(r["y"]), w=float(r["w"]), h=float(r["h"]), start=r.get("start"),
                      end=r.get("end"), reason=r.get("reason", "")) for r in (lst or [])]


def run_inpaint(src: SourceInfo, rects: list[dict], issues: list[dict], execute: bool) -> str | None:
    """Clean intermediate via ``shortkit.clean.apply`` (lazy import): the cache location is
    ``clean.apply.cache_path`` (warehouse/cache/clean/<source sha256>_<ops hash>.mp4, shared with
    every other user of the cleaner) and ``inpaint_cached`` builds / re-validates it."""
    where = f"sources[{src.id}].clean.inpaint"
    try:
        from ..clean.apply import cache_path, inpaint_cached  # type: ignore
    except Exception as e:  # module owned by another area; report instead of skipping silently
        issues.append(issue("error", "inpaint_unavailable",
                            f"소스 {src.id} 에 clean.inpaint 가 있지만 shortkit.clean.apply 를 불러오지 못함: "
                            f"{type(e).__name__}", where))
        return None
    if not src.exists:
        return None
    rs = [dict(r) for r in rects]
    try:
        out = Path(cache_path(src.abs, rs, src_sha=src.plan.get("sha256") or None))
        rel = paths.relp(out)
    except Exception as e:
        issues.append(issue("error", "inpaint_failed", f"inpaint 캐시 경로 계산 실패({src.id}): {type(e).__name__}: {e}",
                            where))
        return None
    if execute:
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            res = inpaint_cached(src.abs, rs)
        except Exception as e:
            issues.append(issue("error", "inpaint_failed", f"inpaint 실패({src.id}): {type(e).__name__}: {e}", where))
            return None
        got = res.get("out") if isinstance(res, dict) else None
        if got and Path(paths.absp(got)).resolve() != out.resolve():
            issues.append(issue("error", "inpaint_cache_mismatch",
                                f"inpaint 결과 경로 {got} 가 캐시 경로 {rel} 와 다릅니다", where))
            return None
    return rel


# ----------------------------------------------------------------------------- timeline
def resolve_clips(plan: dict, preset: config.Preset, canvas: dict, sources: dict[str, SourceInfo],
                  issues: list[dict], execute_clean: bool) -> list[Clip]:
    # read the fixed motion style once (every key used below, traced to this function)
    z_sec, f_sec, t_sec = preset.section("motion.zoom"), preset.section("motion.freeze"), \
        preset.section("motion.transitions")
    mz = {"scale_to": z_sec["scale_to"], "dur_s": z_sec["dur_s"], "ease": z_sec["ease"],
          "recenter": z_sec["recenter"]}
    mf = {"hold_s": f_sec["hold_s"]}
    mt = {"default": t_sec["default"], "flash": {"dur_s": t_sec["flash"]["dur_s"], "color": t_sec["flash"]["color"],
                                                 "scope": t_sec["flash"]["scope"]},
          "crossfade": {"dur_s": t_sec["crossfade"]["dur_s"]}}
    if not isinstance(mz["recenter"], bool):
        issues.append(issue("error", "zoom_recenter", f"motion.zoom.recenter={mz['recenter']!r}: true/false 만 허용",
                            "motion.zoom.recenter"))
        mz["recenter"] = False
    if mt["flash"]["scope"] not in FLASH_SCOPES:
        issues.append(issue("error", "flash_scope", f"motion.transitions.flash.scope={mt['flash']['scope']!r} 미지원 "
                            f"{FLASH_SCOPES}", "motion.transitions.flash.scope"))
        mt["flash"]["scope"] = "region"
    blur_ratio = float(preset.get("render.clean.blur_sigma_ratio"))
    if not blur_ratio > 0:
        issues.append(issue("error", "blur_sigma_ratio", f"render.clean.blur_sigma_ratio={blur_ratio}: 0보다 커야 합니다",
                            "render.clean.blur_sigma_ratio"))
    vr = canvas["video_region"]
    region = Rect(vr["x"], vr["y"], vr["w"], vr["h"])
    clips: list[Clip] = []
    t = 0.0
    cleaned: dict[str, str | None] = {}
    for i, seg in enumerate(plan["timeline"]):
        where = f"timeline[{seg['id']}]"
        src = sources.get(seg["source"])
        if src is None:
            issues.append(issue("error", "segment_unknown_source", f"세그먼트 소스 id 없음: {seg['source']}", where))
            continue
        speed = float(seg.get("speed") or 1.0)
        a, b = float(seg["src_in"]), float(seg["src_out"])
        if b <= a:
            issues.append(issue("error", "segment_range", f"src_out({b}) 이 src_in({a}) 보다 커야 합니다", where))
            continue
        if src.duration is not None and b > src.duration + 1e-3:
            issues.append(issue("error", "segment_beyond_source",
                                f"src_out {b:.3f}s 가 소스 길이 {src.duration:.3f}s 를 넘습니다", where))
        move = (b - a) / speed
        # transition
        tr = seg.get("transition_in") or {}
        ttype = tr.get("type") or mt["default"]
        if ttype not in ("cut", "flash", "crossfade"):
            issues.append(issue("error", "transition_type", f"지원하지 않는 전환 종류: {ttype}", where))
            ttype = "cut"
        if i == 0 and ttype != "cut":
            issues.append(issue("error", "transition_first", "첫 세그먼트에는 전환(flash/crossfade)을 둘 수 없습니다", where))
            ttype = "cut"
        tdur, tcolor = 0.0, None
        if ttype == "flash":
            tdur = float(tr.get("dur") if tr.get("dur") is not None else mt["flash"]["dur_s"])
            tcolor = mt["flash"]["color"]
        elif ttype == "crossfade":
            tdur = float(tr.get("dur") if tr.get("dur") is not None else mt["crossfade"]["dur_s"])
        out_start = t - tdur if ttype == "crossfade" else t
        # freeze
        fr = None
        hold = 0.0
        if seg.get("freeze"):
            f = seg["freeze"]
            hold = float(f.get("hold") if f.get("hold") is not None else mf["hold_s"])
            at = f.get("at") or "end"
            if at == "src_t":
                fs = f.get("src_t")
                if fs is None or not (a <= float(fs) <= b):
                    issues.append(issue("error", "freeze_src_t", "freeze.at=src_t 인데 src_t 가 없거나 세그먼트 밖입니다", where))
                    fs = b
                fs = float(fs)
                fr = Freeze(src_t=fs, out_start=round(out_start + (fs - a) / speed, 6), hold=hold)
            else:
                fr = Freeze(src_t=b, out_start=round(out_start + move, 6), hold=hold)
            if hold <= 0:
                issues.append(issue("error", "freeze_hold", "정지 길이(hold)는 0보다 커야 합니다", where))
        out_end = out_start + move + hold
        # zoom
        zm = None
        if seg.get("zoom"):
            z = seg["zoom"]
            zm = Zoom(scale_from=float(z.get("scale_from") if z.get("scale_from") is not None else 1.0),
                      scale_to=float(z["scale_to"] if z.get("scale_to") is not None else mz["scale_to"]),
                      center_src=(float(z["center"][0]), float(z["center"][1])),
                      start=float(z.get("start") or 0.0),
                      dur=float(z["dur"] if z.get("dur") is not None else mz["dur_s"]),
                      ease=z.get("ease") or mz["ease"], recenter=bool(mz["recenter"]))
            if zm.ease not in EASES:
                issues.append(issue("error", "zoom_ease", f"지원하지 않는 zoom ease: {zm.ease}", where))
            if src.width and not (0 <= zm.center_src[0] <= src.width and 0 <= zm.center_src[1] <= src.height):
                issues.append(issue("error", "zoom_center", f"zoom.center {zm.center_src} 가 소스 화면 밖입니다", where))
            if zm.start + zm.dur > (out_end - out_start) + 1e-6:
                issues.append(issue("warn", "zoom_past_clip", "zoom 이 세그먼트가 끝난 뒤에 완료됩니다", where))
        # cleaning
        cl = src.plan.get("clean") or {}
        crop = cl.get("crop")
        crop_r = Rect(float(crop["x"]), float(crop["y"]), float(crop["w"]), float(crop["h"])) if crop else None
        if crop_r and src.width and (crop_r.x < 0 or crop_r.y < 0 or crop_r.x + crop_r.w > src.width + 0.5
                                     or crop_r.y + crop_r.h > src.height + 0.5 or crop_r.w <= 0 or crop_r.h <= 0):
            issues.append(issue("error", "crop_outside", "clean.crop 이 소스 화면 밖입니다", f"sources[{src.id}].clean.crop"))
        source_path = src.path
        if cl.get("inpaint"):
            if src.id not in cleaned:
                cleaned[src.id] = run_inpaint(src, cl["inpaint"], issues, execute_clean)
            if cleaned[src.id]:
                source_path = cleaned[src.id]
        clip = Clip(id=seg["id"], source_id=src.id, source_path=source_path, src_in=a, src_out=b, speed=speed,
                    out_start=round(out_start, 6), out_end=round(out_end, 6), region=region,
                    fit=canvas["video_region"]["fit"], src_size=(int(src.width or 0), int(src.height or 0)),
                    crop=crop_r, delogo=_timed_rects(cl.get("delogo")), inpaint=_timed_rects(cl.get("inpaint")),
                    blur=_timed_rects(cl.get("blur")), zoom=zm, freeze=fr,
                    transition_in=Transition(ttype, tdur, tcolor, mt["flash"]["scope"] if ttype == "flash" else "region"),
                    purpose=seg.get("purpose", ""), blur_sigma_ratio=blur_ratio)
        if ttype == "crossfade" and clips:
            prev = clips[-1]
            if tdur <= 0 or tdur >= (prev.out_end - prev.out_start) - EPS or tdur >= (out_end - out_start) - EPS:
                issues.append(issue("error", "crossfade_dur", f"crossfade 길이 {tdur}s 가 앞/뒤 클립보다 깁니다", where))
        clips.append(clip)
        t = out_end
    if canvas["video_region"]["fit"] not in ("cover", "contain"):
        issues.append(issue("error", "fit_mode", f"canvas.video_region.fit={canvas['video_region']['fit']} 미지원",
                            "canvas.video_region.fit"))
    if canvas["background"]["type"] not in ("color", "blur_source"):
        issues.append(issue("error", "background_type", f"canvas.background.type={canvas['background']['type']} 미지원",
                            "canvas.background.type"))
    return clips


# ----------------------------------------------------------------------------- captions
def resolve_captions(ctx: ResolveContext, canvas: dict, duration: float, build_rel: str) -> list[CaptionBox]:
    preset, issues = ctx.preset, ctx.issues
    font_dirs = list(preset.get("text.font_dirs") or [])
    caps: list[CaptionBox] = []
    for c in ctx.plan.get("captions", []):
        role = c["role"]
        where = f"captions[{c['id']}]"
        if role not in ctx.role_styles:
            st = read_role_style(preset, role, issues)
            if st is None:
                continue
            ctx.role_styles[role] = st
            try:
                f = cap_mod.resolve_font(st["font_name"], st.get("font_file"), font_dirs)
                ctx.fonts[role] = f
                if st.get("bold") and f.face.weight < 600:
                    issues.append(issue("error", "font_not_bold",
                                        f"{role}: bold=true 인데 글꼴 '{st['font_name']}' 굵기가 {f.face.weight} 입니다"
                                        "(렌더러별 가짜 볼드 차이 방지를 위해 굵은 글꼴을 지정)", f"text.roles.{role}"))
            except cap_mod.FontError as e:
                issues.append(issue("error", "font_missing", f"{role}: {e}", f"text.roles.{role}.font_name"))
            for key, allowed in (("motion_in", MOTION_IN_TYPES), ("motion_out", MOTION_OUT_TYPES)):
                if st[key]["type"] not in allowed:
                    issues.append(issue("error", "motion_type", f"{role}.{key}.type={st[key]['type']} 미지원({allowed})",
                                        f"text.roles.{role}.{key}.type"))
            if st["anchor"]["align"] not in ("left", "center", "right") or \
                    st["anchor"]["valign"] not in ("top", "middle", "bottom"):
                issues.append(issue("error", "anchor_align", f"{role}.anchor align/valign 값이 잘못됨",
                                    f"text.roles.{role}.anchor"))
        st = ctx.role_styles[role]
        font = ctx.fonts.get(role)
        text = c["text"]
        if cap_mod.ASS_FORBIDDEN.search(text):
            issues.append(issue("error", "caption_bad_char", "자막에 { } \\ 문자는 쓸 수 없습니다(ASS 제어 문자)", where))
            continue
        if role == "dialogue" and st.get("quote_marks"):
            q0, q1 = st["quote_marks"][0], st["quote_marks"][-1]
            if not text.startswith(q0):
                text = q0 + text
            if not text.endswith(q1) or len(text) == 1:
                text = text + q1
        start = max(0.0, float(c["start"]) - float(st["timing"]["lead_s"]))
        end = float(c["end"])
        if st["persist"] == "whole_video":
            end = duration
        elif st["persist"] != "timed":
            issues.append(issue("error", "persist_value", f"{role}.persist={st['persist']} 미지원",
                                f"text.roles.{role}.persist"))
        if end <= start:
            issues.append(issue("error", "caption_time", f"자막 끝({end})이 시작({start})보다 커야 합니다", where))
        if end - start < float(st["timing"]["min_dur_s"]) - 1e-6:
            issues.append(issue("warn", "caption_short",
                                f"자막 표시 시간 {end - start:.2f}s < 최소 {st['timing']['min_dur_s']}s", where))
        anchor = (float(c["pos"][0]), float(c["pos"][1])) if c.get("pos") else \
            (float(st["anchor"]["x"]), float(st["anchor"]["y"]))
        if font is None:
            continue
        lay = cap_mod.layout_text(text, font.face, st, anchor)
        ctx.layouts[c["id"]] = lay
        ix, iy, iw, ih = (round(v, 2) for v in lay.ink)
        box = {k: st["box"][k] for k in ("enabled", "color", "alpha", "pad_x", "pad_y")}
        box["rect"] = ([round(ix - float(box["pad_x"]), 2), round(iy - float(box["pad_y"]), 2),
                        round(iw + 2 * float(box["pad_x"]), 2), round(ih + 2 * float(box["pad_y"]), 2)]
                       if box["enabled"] else None)
        caps.append(CaptionBox(
            id=c["id"], role=role, text="\n".join(lb.text for lb in lay.lines), lines=[lb.text for lb in lay.lines],
            start=round(start, 6), end=round(end, 6), anchor=anchor, align=st["align"], valign=st["valign"],
            bbox=Rect(ix, iy, iw, ih), font_name=st["font_name"],
            font_file=f"{build_rel}/fonts/{Path(font.face.path).name}", size_px=float(st["size_px"]),
            color=st["color"], highlight=list(c.get("highlight") or []), highlight_color=st["highlight_color"],
            outline_px=float(st["outline_px"]), outline_color=st["outline_color"], shadow_px=float(st["shadow_px"]),
            box=box, motion_in=dict(st["motion_in"]), motion_out=dict(st["motion_out"]),
            grounding=c.get("grounding"), line_spacing=float(st["line_spacing"]), shadow_color=st["shadow_color"],
            weight=int(font.face.weight), lines_pos=[(round(lb.center[0], 3), round(lb.center[1], 3))
                                                     for lb in lay.lines]))
    return caps


DECO_KEYS = {"arrow": ("color", "size_px", "outline_px", "outline_color", "blink_hz",
                       "head_len_ratio", "head_width_ratio", "shaft_width_ratio"),
             "circle": ("color", "stroke_px", "blink_hz"),
             "box": ("color", "stroke_px", "blink_hz")}


def resolve_decorations(plan: dict, preset: config.Preset, issues: list[dict]) -> list[Decoration]:
    out = []
    for d in plan.get("decorations", []) or []:
        where = f"decorations[{d['id']}]"
        kind = d["kind"]
        sec = preset.section(f"decorations.{kind}")
        present = set(iter(sec))
        optional = DECO_KEYS.get(f"{kind}_optional", ())
        st = {k: sec[k] for k in DECO_KEYS[kind] + optional if k in present}
        for k in DECO_KEYS[kind]:
            if k not in st:
                issues.append(issue("error", "deco_key_missing", f"프리셋 키 없음: decorations.{kind}.{k}", where))
        for k in present:
            if k not in DECO_KEYS[kind] + optional:
                issues.append(issue("warn", "preset_key_unsupported", f"렌더러가 구현하지 않은 프리셋 키: decorations.{kind}.{k}",
                                    f"decorations.{kind}.{k}"))
        start, end = float(d["start"]), float(d["end"])
        if end <= start:
            issues.append(issue("error", "deco_time", "장식 end 가 start 보다 커야 합니다", where))
        kfs = []
        for k in sorted(d["keyframes"], key=lambda k: k["t"]):
            if not (-EPS <= k["t"] <= end - start + EPS):
                issues.append(issue("error", "deco_keyframe_time", f"키프레임 t={k['t']} 가 장식 구간(0..{end - start:.2f}) 밖", where))
            if kind in ("circle", "box") and (not k.get("w") or not k.get("h")):
                issues.append(issue("error", "deco_size", f"{kind} 키프레임에는 w/h 가 필요합니다", where))
            kfs.append({"t": round(start + float(k["t"]), 6), "x": float(k["x"]), "y": float(k["y"]),
                        "w": k.get("w"), "h": k.get("h"), "rotation": k.get("rotation")})
        blink = d.get("blink_hz")
        blink = float(st.get("blink_hz") or 0.0) if blink is None else float(blink)
        out.append(Decoration(id=d["id"], kind=kind, start=start, end=end, keyframes=kfs, blink_hz=blink, style=st))
    return out


# ----------------------------------------------------------------------------- main
def resolve_context(plan: dict, preset: config.Preset, *, execute_clean: bool = False) -> ResolveContext:
    """Resolve without writing files; never raises for plan problems (they become issues)."""
    issues: list[dict] = []
    sources = probe_sources(plan, issues)
    ctx = ResolveContext(plan=plan, preset=preset, resolved=None, issues=issues, sources=sources)
    canvas = read_canvas(preset)
    out = plan.get("output") or {}
    crf = int(out.get("crf") or 18)
    if not 18 <= crf <= 20:
        issues.append(issue("error", "crf_range", f"output.crf={crf}: 18~20 만 허용", "output.crf"))
        crf = min(20, max(18, crf))
    canvas["encode"] = {"crf": crf, "audio_bitrate": out.get("audio_bitrate") or "192k", "pix_fmt": "yuv420p",
                        "vcodec": "libx264", "acodec": "aac"}
    clips = resolve_clips(plan, preset, canvas, sources, issues, execute_clean)
    duration = max((c.out_end for c in clips), default=0.0)
    eid = plan["episode_id"]
    build_rel = f"episodes/{eid}/build"
    captions = resolve_captions(ctx, canvas, duration, build_rel)
    decorations = resolve_decorations(plan, preset, issues)
    from .audio import build_audio_plan  # local import (audio imports resolve helpers)

    audio = build_audio_plan(plan, preset, clips, duration, sources, issues)
    out_path = out.get("path") or f"episodes/{eid}/output/{eid}.mp4"
    if os.path.isabs(out_path):
        issues.append(issue("error", "abs_path", "output.path 는 루트 기준 상대 경로여야 합니다", "output.path"))
    reads = set(preset.log.reads)
    fmt = plan.get("format_id")
    resolved = ResolvedEdit(
        schema=SCHEMA, episode_id=eid, preset_id=preset.preset_id, preset_name=preset.name,
        format_id=fmt, mode=plan["mode"], canvas=canvas, duration=round(duration, 6), clips=clips,
        captions=captions, decorations=decorations, ass_path=f"{build_rel}/captions.ass",
        fonts_dir=f"{build_rel}/fonts", audio=audio, output_path=out_path,
        warnings=[f"[{i['code']}] {i['message_ko']}" for i in issues if i["severity"] == "warn"],
        provisional_keys=sorted(k for k in reads if preset.origin(k) == "provisional"),
        requested_change_keys=sorted(set(preset.requested_keys()) & reads))
    ctx.resolved = resolved
    return ctx


def resolve(plan: dict, preset: config.Preset) -> ResolvedEdit:
    """Pure resolve (contract API).  Raises ResolveError when the plan has errors."""
    ctx = resolve_context(plan, preset)
    if ctx.errors:
        raise ResolveError(ctx.issues)
    return ctx.resolved


def link_fonts(ctx: ResolveContext, build: Path) -> None:
    fdir = build / "fonts"
    fdir.mkdir(parents=True, exist_ok=True)
    for f in ctx.fonts.values():
        src = Path(f.face.path)
        dst = fdir / src.name
        if dst.is_symlink() or dst.exists():
            try:
                if dst.resolve() == src.resolve() or (dst.is_file() and sha256_file(dst) == sha256_file(src)):
                    continue
            except OSError:
                pass
            dst.unlink()
        try:
            dst.symlink_to(src)
        except OSError:
            import shutil

            shutil.copyfile(src, dst)


def layout_record(ctx: ResolveContext) -> dict:
    caps = {}
    for c in ctx.resolved.captions:
        lay = ctx.layouts[c.id]
        st = ctx.role_styles[c.role]
        f = ctx.fonts[c.role]
        caps[c.id] = {
            "role": c.role, "font": {"name": st["font_name"], "file_name": Path(f.face.path).name, "face_index": f.face.index,
                                     "weight": f.face.weight, "resolved_by": f.how, "units_per_em": f.face.units_per_em,
                                     "win_ascent": f.face.win_ascent, "win_descent": f.face.win_descent},
            "ass_fontsize": round(lay.ass_fontsize, 3), "line_spacing": st["line_spacing"],
            "line_pitch_px": round(lay.pitch, 3), "asc_px": round(lay.asc_px, 3), "desc_px": round(lay.desc_px, 3),
            "shadow_color": st["shadow_color"], "bold": st["bold"],
            "block": [round(v, 2) for v in lay.block], "ink": [round(v, 2) for v in lay.ink],
            "lines": [{"text": lb.text, "left": round(lb.left, 2), "top": round(lb.top, 2), "width": round(lb.width, 2),
                       "height": round(lb.height, 2), "baseline": round(lb.baseline, 2),
                       "center": [round(lb.center[0], 2), round(lb.center[1], 2)],
                       "ink": [round(v, 2) for v in lb.ink]} for lb in lay.lines]}
    return {"schema": "shortkit.caption_layout/1", "episode_id": ctx.resolved.episode_id,
            "resolution": [ctx.resolved.canvas["width"], ctx.resolved.canvas["height"]],
            "convention": "size_px = em px; pitch = size_px*line_spacing; line box = winAscent+winDescent; "
                          "ASS Fontsize = size_px*(winAscent+winDescent)/unitsPerEm; one \\an5\\pos event per line",
            "captions": caps}


def write_build(ctx: ResolveContext) -> ResolvedEdit:
    r = ctx.resolved
    build = build_dir(r.episode_id)
    build.mkdir(parents=True, exist_ok=True)
    link_fonts(ctx, build)
    cap_mod.write_ass(paths.absp(r.ass_path), r.canvas, r.captions, ctx.layouts, ctx.role_styles, r.decorations,
                      ctx.fonts)
    write_json(build / "caption_layout.json", layout_record(ctx))
    write_json(build / "resolved.json", r.to_dict())
    ctx.preset.save_access_log(build / "preset_access.json")
    write_json(build / "resolve_issues.json", {"resolved_at": now_iso(), "issues": ctx.issues})
    return r


def resolve_episode(episode_id: str, preset_name: str | None = None, *,
                    allow_unmeasured: bool = False) -> ResolvedEdit:
    """Validate (all rules) + resolve an episode and write build/{resolved.json, captions.ass,
    preset_access.json, caption_layout.json}.  Raises ResolveError on errors (nothing written).
    Warnings of every rule are stored in ``resolved.warnings``."""
    from .validate import validate

    plan = load_plan(episode_id)
    preset = preset_for_plan(plan, preset_name)
    issues, ctx = validate(plan, preset, allow_unmeasured=allow_unmeasured, return_context=True,
                           execute_clean=True)
    if ctx is None or any(i["severity"] == "error" for i in issues):
        raise ResolveError(issues)
    ctx.issues = issues
    ctx.resolved.warnings = [f"[{i['code']}] {i['message_ko']}" for i in issues if i["severity"] == "warn"]
    return write_build(ctx)


def load_resolved(episode_id: str) -> ResolvedEdit:
    from ..util.jsonio import read_json

    d = read_json(build_dir(episode_id) / "resolved.json")
    if d is None:
        raise FileNotFoundError(f"build/resolved.json 없음: 먼저 `shortkit episode resolve {episode_id}`")
    return ResolvedEdit.from_dict(d)
