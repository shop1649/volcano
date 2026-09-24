"""FCPXML 1.9 export (DaVinci Resolve / Final Cut Pro import) from a ResolvedEdit.

UNVERIFIED HERE: this machine has neither Resolve nor Final Cut Pro, so the file is only checked
for well-formedness and internal time consistency (tests/export).  Everything below follows the
FCPXML 1.9 element model (resources/format/asset/media-rep, library/event/project/sequence/spine,
asset-clip + connected clips on lanes, timeMap retiming, transitions, adjust-* parameters with
keyframeAnimation, caption elements).

Mapping decisions (also written to export_decisions.json -> "fcpxml"):
  * times are rational seconds on the sequence frame grid (frameDuration = 1/fps).
  * one spine asset-clip per IR clip; speed and freeze are ONE timeMap per clip (hold = flat
    segment); a crossfade becomes a spine <transition> centred on the middle of the IR overlap
    (both clips have the needed media handles because the IR plays them through the overlap).
  * clips with delogo / blur reference a pre-cleaned intermediate (media/*_nleclean_*.mp4) so the
    source overlay can never come back in Resolve/FCP (they have no delogo); blur sigma =
    render.blur_sigma_src (render.clean.blur_sigma_ratio); inpaint is already baked into the IR
    source path.
  * geometry (resolve.src_to_region: fit, eased zoom, Zoom.recenter, cover clamp): adjust-conform
    none + adjust-crop trim (the source window visible inside the video region, % of the source
    dimension; FCP has no region mask) + adjust-transform position/scale (position in % of the
    sequence height, y up - the usual FCPXML convention; not confirmable here).  While the zoom
    moves, position / scale / trim get one linear keyframe per output frame (exact on the grid).
  * flash = connected still (solid colour PNG of the Transition.scope rect: video region or the
    whole canvas) with adjust-blend keyframes.
  * audio = connected clips below the spine (BGM lane -1, SFX lane -2.., originals lane -3..)
    with adjust-volume keyframes (gain + ducking/silence envelope + fades + master loudness gain +
    the master's per-frame foreground limiter from build/fg_gain.json on SFX / kept originals).
  * captions = FCPXML caption elements (iTT, ko) for every role, text only; the styled captions
    and decorations are the ASS file (captions.ass) - see README.
  * media src are relative URLs by default; absolute=True writes file:// URLs for local import
    (never commit such a file).
"""
from __future__ import annotations

import math
import os
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

from .. import paths
from ..util.hashing import sha256_text
from ..util.jsonio import now_iso
from ..util.media import ffmpeg, probe
from .export_mlt import (EPS_PICK, clip_frame_range, fg_gain_db_at_frame_start, fps_fraction, fps_of, hex_rgb,
                         load_render_report, master_foreground_gain, merge_decisions, n_frames, source_time,
                         write_caption_files, zoom_animates, zoom_motion_frames)
from .ir import Clip, ResolvedEdit
from .resolve import effective_src_rect, src_to_region

FCPXML_VERSION = "1.9"
CROSS_DISSOLVE_UID = "FxPlug:4731E73A-8DAC-4113-9A30-AE85B1761265"
ROLE_KO = {"title": "제목", "description": "설명", "situation": "상황", "speaker": "화자", "dialogue": "대사",
           "reaction": "반응"}


class Clock:
    def __init__(self, fps: float):
        self.fr = fps_fraction(fps)
        self.fd = Fraction(1, 1) / self.fr          # frame duration

    def frames(self, n: int) -> str:
        return self.fmt(n * self.fd)

    def seconds_on_grid(self, t: float) -> str:
        return self.frames(int(round(t * float(self.fr))))

    @staticmethod
    def fmt(v: Fraction) -> str:
        v = Fraction(v)
        if v.denominator == 1:
            return f"{v.numerator}s"
        return f"{v.numerator}/{v.denominator}s"


def parse_time(s: str) -> Fraction:
    s = s.rstrip("s")
    if "/" in s:
        a, b = s.split("/")
        return Fraction(int(a), int(b))
    return Fraction(s)


class FcpBuilder:
    def __init__(self, r: ResolvedEdit, out_dir: Path, absolute: bool, dec: dict):
        self.r = r
        self.out_dir = out_dir
        self.absolute = absolute
        self.dec = dec
        self.fps = fps_of(r)
        self.clk = Clock(self.fps)
        self.W, self.H = int(r.canvas["width"]), int(r.canvas["height"])
        self.N = n_frames(r)
        self.root = ET.Element("fcpxml", {"version": FCPXML_VERSION})
        self.res = ET.SubElement(self.root, "resources")
        self._rid = 0
        self._assets: dict[str, str] = {}
        self._formats: dict[tuple, str] = {}
        self._ts = 0
        self.fg_gain: list[float] | None = None      # master foreground limiter per output frame (fg_gain.json)
        self.seq_format = self.format_for(self.W, self.H, self.fps, "FFVideoFormatRateUndefined")
        self.dissolve = self.new_id()
        ET.SubElement(self.res, "effect", {"id": self.dissolve, "name": "Cross Dissolve", "uid": CROSS_DISSOLVE_UID})

    # ---------------------------------------------------------------- resources
    def new_id(self) -> str:
        self._rid += 1
        return f"r{self._rid}"

    def format_for(self, w: int, h: int, fps: float | None, name: str | None = None) -> str:
        key = (w, h, round(fps or 0, 3))
        if key in self._formats:
            return self._formats[key]
        fid = self.new_id()
        attrs = {"id": fid, "name": name or "FFVideoFormatRateUndefined", "width": str(w), "height": str(h),
                 "colorSpace": "1-1-1 (Rec. 709)"}
        if fps:
            attrs["frameDuration"] = Clock.fmt(Fraction(1, 1) / fps_fraction(fps))
        ET.SubElement(self.res, "format", attrs)
        self._formats[key] = fid
        return fid

    def url(self, root_rel: str) -> str:
        if self.absolute:
            return paths.absp(root_rel).resolve().as_uri()
        return Path(os.path.relpath(paths.absp(root_rel), self.out_dir)).as_posix()

    def asset(self, root_rel: str, name: str | None = None, still: bool = False) -> str:
        if root_rel in self._assets:
            return self._assets[root_rel]
        info = probe(paths.absp(root_rel))
        aid = self.new_id()
        attrs = {"id": aid, "name": name or Path(root_rel).name,
                 "uid": sha256_text(root_rel).upper()[:32], "start": "0s",
                 "hasVideo": "1" if info.width else "0", "hasAudio": "1" if info.has_audio else "0"}
        if still:
            attrs["duration"] = "0s"
        else:
            attrs["duration"] = self.clk.frames(int(math.floor(info.duration * self.fps + 1e-6)))
        if info.width:
            attrs["format"] = self.format_for(info.width, info.height, None if still else info.fps)
        if info.has_audio:
            attrs.update({"audioSources": "1", "audioChannels": str(info.audio_channels or 2),
                          "audioRate": str(info.audio_rate or 48000)})
        a = ET.SubElement(self.res, "asset", attrs)
        ET.SubElement(a, "media-rep", {"kind": "original-media", "src": self.url(root_rel)})
        self._assets[root_rel] = aid
        return aid

    # ---------------------------------------------------------------- media for NLEs
    def nle_source(self, c: Clip) -> tuple[str, float]:
        """(root-relative file, time offset) for clips that need cleaning the NLE cannot do."""
        if not c.delogo and not c.blur:
            return c.source_path, 0.0
        from .render import blur_sigma_src

        # master's blur strength (render.clean.blur_sigma_ratio via the IR); RenderError on an old IR
        sigmas = [blur_sigma_src(c, bl) for bl in c.blur]
        info = probe(paths.absp(c.source_path))
        sfps = info.fps or 30.0
        a = max(0.0, math.floor((c.src_in - 1.0) * sfps) / sfps)
        b = c.src_out + 1.0
        key = sha256_text(repr((c.source_path, a, b, [(d.x, d.y, d.w, d.h, d.start, d.end) for d in c.delogo],
                                [(d.x, d.y, d.w, d.h, d.start, d.end) for d in c.blur],
                                [round(x, 6) for x in sigmas])))[:12]
        media = self.out_dir / "media"
        media.mkdir(parents=True, exist_ok=True)
        out = media / f"{c.id}_nleclean_{key}.mp4"
        iw, ih = info.width, info.height
        chain, last = [], "[0:v]"
        j = 0
        for d in c.delogo:
            x = int(max(1, min(d.x, iw - 3)))
            y = int(max(1, min(d.y, ih - 3)))
            w = int(max(1, min(d.w, iw - 1 - x)))
            h = int(max(1, min(d.h, ih - 1 - y)))
            s0 = (d.start if d.start is not None else 0.0) - a
            s1 = (d.end if d.end is not None else 1e9) - a
            chain.append(f"{last}delogo=x={x}:y={y}:w={w}:h={h}:enable='between(t,{s0:.4f},{s1:.4f})'[d{j}]")
            last = f"[d{j}]"
            j += 1
        for bi, bl in enumerate(c.blur):
            x, y = int(round(bl.x)), int(round(bl.y))
            w, h = max(2, int(round(bl.w))), max(2, int(round(bl.h)))
            sig = sigmas[bi]
            s0 = (bl.start if bl.start is not None else 0.0) - a
            s1 = (bl.end if bl.end is not None else 1e9) - a
            chain.append(f"{last}split[m{j}][c{j}];[c{j}]crop={w}:{h}:{x}:{y},gblur=sigma={sig:.3f}[b{j}];"
                         f"[m{j}][b{j}]overlay={x}:{y}:enable='between(t,{s0:.4f},{s1:.4f})'[d{j}]")
            last = f"[d{j}]"
            j += 1
        if not out.is_file():
            ffmpeg(["-ss", f"{a:.6f}", "-i", paths.absp(c.source_path), "-t", f"{b - a:.6f}", "-an",
                    "-filter_complex", ";".join(chain), "-map", last, "-fps_mode", "passthrough",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-pix_fmt", "yuv420p", out])
        rec = {"kind": "nle_clean_intermediate", "clip": c.id,
               "file": Path(os.path.relpath(out, self.out_dir)).as_posix(), "source_range_s": [round(a, 4), round(b, 4)],
               "blur_sigmas_src_px": [round(x, 3) for x in sigmas],
               "sigma_rule": "gaussian sigma = max(w, h) × render.clean.blur_sigma_ratio (render.blur_sigma_src)",
               "why": "Resolve/FCP 에는 delogo 가 없어 원본 오버레이가 다시 보이지 않도록 delogo·blur 를 미리 적용한 "
                      "중간 파일을 FCPXML/OTIO 소스로 사용"}
        if not any(x.get("file") == rec["file"] for x in self.dec["prerendered"]):
            self.dec["prerendered"].append(rec)
        return paths.relp(out), a

    def flash_still(self, color: str, w: int, h: int) -> str:
        from PIL import Image

        media = self.out_dir / "media"
        media.mkdir(parents=True, exist_ok=True)
        out = media / f"flash_{color.lstrip('#').upper()}_{w}x{h}.png"
        if not out.is_file():
            Image.new("RGB", (w, h), hex_rgb(color)).save(out)
        return paths.relp(out)

    # ---------------------------------------------------------------- timing helpers
    def media_time_str(self, t: float) -> str:
        """Media (source) time on the sequence frame grid, floored like render's frame pick."""
        return self.clk.frames(int(math.floor((t + EPS_PICK) * self.fps + 1e-9)))

    def keyframe(self, parent: ET.Element, time: str, value: str, interp: str | None = None) -> None:
        a = {"time": time, "value": value}
        if interp:
            a["interp"] = interp
        ET.SubElement(parent, "keyframe", a)

    # ---------------------------------------------------------------- spine
    def spine_items(self) -> list[dict]:
        """Clip spans on the spine: crossfades cut at the middle of the IR overlap."""
        spans = []
        for i, c in enumerate(self.r.clips):
            n0, n1 = clip_frame_range(c, self.fps)
            spans.append({"i": i, "clip": c, "n0": n0, "n1": n1, "s": n0, "e": n1, "tr": None})
        for k in range(1, len(spans)):
            a, b = spans[k - 1], spans[k]
            if b["clip"].transition_in.type == "crossfade" and b["n0"] < a["n1"]:
                o0, o1 = b["n0"], a["n1"]
                cut = (o0 + o1) // 2
                a["e"], b["s"] = cut, cut
                b["tr"] = (o0, o1 - o0)
            elif b["s"] < a["e"]:
                b["s"] = a["e"]
                self.dec["warnings"].append(f"클립 {b['clip'].id}: 앞 클립과 겹쳐 시작을 뒤로 미룸")
        return [s for s in spans if s["e"] > s["s"]]

    def clip_element(self, parent: ET.Element, sp: dict) -> ET.Element:
        c: Clip = sp["clip"]
        src_rel, off = self.nle_source(c)
        aid = self.asset(src_rel)
        n0, s, e = sp["n0"], sp["s"], sp["e"]
        retime = abs(c.speed - 1.0) > 1e-9 or c.freeze is not None
        # clip-local time T(n) = L0 + (n - n0)/fps, L0 = media time at the clip's first frame
        L0_frames = int(math.floor((source_time(c, n0, self.fps) - off + EPS_PICK) * self.fps + 1e-9))
        start_frames = (L0_frames + (s - n0)) if retime else \
            int(math.floor((source_time(c, s, self.fps) - off + EPS_PICK) * self.fps + 1e-9))
        el = ET.SubElement(parent, "asset-clip", {
            "ref": aid, "offset": self.clk.frames(s), "name": c.id, "start": self.clk.frames(start_frames),
            "duration": self.clk.frames(e - s), "tcFormat": "NDF", "srcEnable": "video"})
        if retime:
            tm = ET.SubElement(el, "timeMap")
            n1 = sp["n1"]
            pts = {n0, n1}
            if c.freeze is not None:
                f = c.freeze
                fl = f.out_start
                pts.add(int(math.ceil(fl * self.fps - 1e-7)))
                pts.add(int(math.ceil((fl + f.hold) * self.fps - 1e-7)))
            for n in sorted(p for p in pts if n0 <= p <= n1):
                u_src = source_time(c, min(n, n1 - 1), self.fps) if n < n1 else \
                    min(c.src_out, source_time(c, n1 - 1, self.fps) + c.speed / self.fps)
                ET.SubElement(tm, "timept", {"time": self.clk.frames(L0_frames + (n - n0)),
                                             "value": self.clk.fmt(Fraction(u_src - off).limit_denominator(100000)),
                                             "interp": "linear"})
        self.transform(el, c, sp, L0_frames if retime else start_frames - (s - n0), off)
        return el

    def transform(self, el: ET.Element, c: Clip, sp: dict, L0_frames: int, off: float) -> None:
        """adjust-crop trim (the source window visible inside the video region: clean crop ∩ region,
        the only region mask FCPXML has) + adjust-transform position/scale, all from
        resolve.src_to_region (cover/contain fit, eased zoom, Zoom.recenter, cover clamp).  While the
        zoom moves, every output frame gets a linear keyframe, so the values equal the master's on
        the frame grid (FCP's own ease curves are not the master's cubic ones)."""
        sw, sh = c.src_size
        ex, ey, ew, eh = effective_src_rect(c)
        R = c.region

        def placement(n: int) -> tuple[float, float, float]:
            return src_to_region(c, n / self.fps - c.out_start)

        def trim(n: int) -> tuple[float, float, float, float]:
            s, tx, ty = placement(n)
            vx0, vx1 = max(ex, ex - tx / s), min(ex + ew, ex + (R.w - tx) / s)
            vy0, vy1 = max(ey, ey - ty / s), min(ey + eh, ey + (R.h - ty) / s)
            return (round(100 * vx0 / sw, 4), round(100 * vy0 / sh, 4), round(100 * (sw - vx1) / sw, 4),
                    round(100 * (sh - vy1) / sh, 4))

        def pos_scale(n: int) -> tuple[str, str]:
            s, tx, ty = placement(n)
            # canvas position of the ORIGINAL frame centre (FCP transforms about the frame centre)
            fx = R.x + tx + s * (sw / 2 - ex)
            fy = R.y + ty + s * (sh / 2 - ey)
            px = (fx - self.W / 2) / self.H * 100
            py = -(fy - self.H / 2) / self.H * 100
            return f"{px:.4f} {py:.4f}", f"{s:.6f} {s:.6f}"

        first, last, n0 = sp["s"], sp["e"] - 1, sp["n0"]
        ks = [first]
        if zoom_animates(c):
            zf0, zf1 = zoom_motion_frames(c, self.fps)
            lo, hi = max(first, int(math.floor(zf0))), min(last, int(math.ceil(zf1)))
            ks = sorted({first, last, *range(lo, hi + 1)})
        trims = [trim(k) for k in ks]
        ps = [pos_scale(k) for k in ks]
        ET.SubElement(el, "adjust-conform", {"type": "none"})
        crop = ET.SubElement(el, "adjust-crop", {"mode": "trim"})
        t0 = trims[0]
        tr_el = ET.SubElement(crop, "trim-rect", {"left": f"{t0[0]:.4f}", "top": f"{t0[1]:.4f}",
                                                  "right": f"{t0[2]:.4f}", "bottom": f"{t0[3]:.4f}"})
        trim_anim = len(set(trims)) > 1
        if trim_anim:
            for j, name in enumerate(("left", "top", "right", "bottom")):
                ka = ET.SubElement(ET.SubElement(tr_el, "param", {"name": name}), "keyframeAnimation")
                for k, v in zip(ks, trims):
                    self.keyframe(ka, self.clk.frames(L0_frames + (k - n0)), f"{v[j]:.4f}", "linear")
        tr = ET.SubElement(el, "adjust-transform", {"position": ps[0][0], "scale": ps[0][1], "anchor": "0 0"})
        if len(set(ps)) > 1:
            pa = ET.SubElement(ET.SubElement(tr, "param", {"name": "position"}), "keyframeAnimation")
            sa = ET.SubElement(ET.SubElement(tr, "param", {"name": "scale"}), "keyframeAnimation")
            for k, (p, s) in zip(ks, ps):
                t = self.clk.frames(L0_frames + (k - n0))
                self.keyframe(pa, t, p, "linear")
                self.keyframe(sa, t, s, "linear")
        if c.zoom is not None:
            z = c.zoom
            self.dec.setdefault("zoom", []).append({
                "clip": c.id, "keyframes": len(ks) if len(set(ps)) > 1 else 0, "mode": "per_frame_linear",
                "ease": z.ease, "recenter": bool(getattr(z, "recenter", False)), "trim_animated": trim_anim,
                "note": "줌이 움직이는 동안 프레임마다 linear 키프레임(resolve.src_to_region 값, recenter·cover 고정 포함) "
                        "→ 프레임 격자에서 마스터와 같은 위치·크기; 영상 영역 밖으로 넘치지 않도록 trim-rect 를 영역 안에 "
                        "보이는 소스 창으로 함께 애니메이션(trim-rect param 애니메이션은 확인 못 함)"})

    # ---------------------------------------------------------------- connected clips
    def anchor_for(self, spans: list[dict], spine_els: list[tuple[int, int, ET.Element, Fraction]], n: int):
        """Spine element whose range contains output frame n -> (element, local time of n)."""
        for s, e, el, local0 in spine_els:
            if s <= n < e:
                return el, local0 + Fraction(n - s) * self.clk.fd
        s, e, el, local0 = spine_els[-1] if n >= spine_els[-1][1] else spine_els[0]
        return el, local0 + Fraction(n - s) * self.clk.fd

    def volume(self, el: ET.Element, gain_db: float, local0: Fraction, nframes: int, env_fn=None,
               fade_in: float = 0.0, fade_out: float = 0.0, fg_db: list[float] | None = None) -> None:
        """adjust-volume: constant gain + envelope (dB) + linear fades + the master's foreground limiter
        (``fg_db``: dB per clip frame k, value at the start of the frame; build/fg_gain.json)."""
        from .export_mlt import SILENCE_DB_FLOOR

        if fg_db is not None and min(fg_db, default=0.0) >= -0.05:
            fg_db = None

        def val(k: int) -> float:
            t = k / self.fps
            v = gain_db
            if env_fn is not None:
                v += env_fn(t)
            if fg_db is not None:
                v += fg_db[min(k, len(fg_db) - 1)]
            g = 1.0
            if fade_in > 0:
                g *= min(1.0, t / fade_in)
            if fade_out > 0:
                g *= max(0.0, min(1.0, (nframes / self.fps - t) / fade_out))
            v += 20 * math.log10(g) if g > 1e-6 else SILENCE_DB_FLOOR
            return max(SILENCE_DB_FLOOR, v)

        av = ET.SubElement(el, "adjust-volume", {"amount": f"{gain_db:.2f}dB"})
        if env_fn is None and fade_in <= 0 and fade_out <= 0 and fg_db is None:
            return
        ks = {0, nframes - 1}
        if fade_in > 0:
            ks.update(range(0, min(nframes, int(math.ceil(fade_in * self.fps)) + 1)))
        if fade_out > 0:
            ks.update(range(max(0, nframes - int(math.ceil(fade_out * self.fps)) - 1), nframes))
        if env_fn is not None or fg_db is not None:
            ks.update(range(nframes))
        ks = sorted(ks)
        vals = [(k, val(k)) for k in ks]
        keep = [vals[0]]
        for i in range(1, len(vals) - 1):
            (k0, v0), (k1, v1), (k2, v2) = keep[-1], vals[i], vals[i + 1]
            if abs(v0 + (v2 - v0) * (k1 - k0) / (k2 - k0) - v1) > 0.05:
                keep.append(vals[i])
        if len(vals) > 1:
            keep.append(vals[-1])
        p = ET.SubElement(av, "param", {"name": "amount"})
        ka = ET.SubElement(p, "keyframeAnimation")
        for k, v in keep:
            self.keyframe(ka, self.clk.fmt(local0 + Fraction(k) * self.clk.fd), f"{v:.2f}dB", "linear")

    def connected_audio(self, spans, spine_els, gain_extra: float) -> None:
        r = self.r
        b = r.audio.bgm
        if b is not None and b.path:
            src, offset = b.path, b.section_start_s
            if abs(b.tempo_ratio - 1.0) > 1e-9:
                from .export_mlt import Media

                src = Media(r, self.out_dir, self.dec).tempo_bgm(b.path, b.tempo_ratio, r.audio.sample_rate)
                offset = b.section_start_s / b.tempo_ratio
            parent, local = self.anchor_for(spans, spine_els, 0)
            n = self.N
            el = ET.SubElement(parent, "asset-clip", {
                "ref": self.asset(src), "lane": "-1", "offset": self.clk.fmt(local), "name": "BGM",
                "start": self.clk.seconds_on_grid(offset), "duration": self.clk.frames(n), "audioRole": "music"})
            from .audio import envelope_db_at

            env = (lambda t, _e=b.envelope: envelope_db_at(_e, t)) if b.envelope else None
            self.volume(el, b.gain_db + gain_extra, self.start_of(el), n, env, b.fade_in_s, b.fade_out_s)
        for k, s in enumerate(r.audio.sfx):
            if not s.path:
                continue
            n0 = int(round(s.t * self.fps))
            if n0 >= self.N:
                continue
            info = probe(paths.absp(s.path))
            n = max(1, min(int(math.ceil(info.duration * self.fps)), self.N - n0))
            parent, local = self.anchor_for(spans, spine_els, n0)
            el = ET.SubElement(parent, "asset-clip", {
                "ref": self.asset(s.path), "lane": str(-2 - (k % 2)), "offset": self.clk.fmt(local),
                "name": f"SFX {s.type}", "start": "0s", "duration": self.clk.frames(n), "audioRole": "effects"})
            self.volume(el, s.gain_db + gain_extra, Fraction(0), n, fg_db=self.fg_db(n0, n))
            ET.SubElement(el, "note").text = f"event {s.event_t:.2f}s: {s.event_desc}"
        for o in r.audio.originals:
            n0 = int(round(o.out_start * self.fps))
            n = max(1, int(round((o.out_end - o.out_start) * self.fps)))
            src, start = o.path, o.src_start
            if abs(o.speed - 1.0) > 1e-9:
                from .export_mlt import Media

                src = Media(r, self.out_dir, self.dec).tempo_original(o, r.audio.sample_rate)
                start = 0.0
            parent, local = self.anchor_for(spans, spine_els, n0)
            info = probe(paths.absp(src))
            el = ET.SubElement(parent, "asset-clip", {
                "ref": self.asset(src), "lane": "-4", "offset": self.clk.fmt(local), "name": f"원본 {o.clip_id}",
                "start": self.clk.seconds_on_grid(start), "duration": self.clk.frames(n), "audioRole": "dialogue"})
            if info.width:
                el.set("srcEnable", "audio")
            self.volume(el, o.gain_db + gain_extra, self.start_of(el), n, None, o.fade_s, o.fade_s,
                        fg_db=self.fg_db(n0, n))

    def fg_db(self, n0: int, n: int) -> list[float] | None:
        """The master's foreground limiter (build/fg_gain.json) in dB for output frames n0 .. n0+n-1."""
        if not self.fg_gain:
            return None
        return [fg_gain_db_at_frame_start(self.fg_gain, n0 + k) for k in range(n)]

    def start_of(self, el: ET.Element) -> Fraction:
        return parse_time(el.get("start", "0s"))

    def flashes(self, spans, spine_els) -> None:
        from .export_mlt import flash_runs

        for fr in flash_runs(self.r):
            c = self.r.clips[fr["clip_index"]]
            rx, ry, rw, rh = fr["rect"]           # Transition.scope: region or whole canvas
            still = self.flash_still(fr["color"], rw, rh)
            aid = self.asset(still, still=True)
            parent, local = self.anchor_for(spans, spine_els, fr["n0"])
            n = fr["n1"] - fr["n0"]
            v = ET.SubElement(parent, "video", {"ref": aid, "lane": "2", "offset": self.clk.fmt(local),
                                                "name": f"플래시 {c.id}", "start": "0s", "duration": self.clk.frames(n)})
            cxp = (rx + rw / 2 - self.W / 2) / self.H * 100
            cyp = -(ry + rh / 2 - self.H / 2) / self.H * 100
            ET.SubElement(v, "adjust-conform", {"type": "none"})
            ET.SubElement(v, "adjust-transform", {"position": f"{cxp:.4f} {cyp:.4f}", "scale": "1 1", "anchor": "0 0"})
            bl = ET.SubElement(v, "adjust-blend", {"amount": "1"})
            p = ET.SubElement(bl, "param", {"name": "amount"})
            ka = ET.SubElement(p, "keyframeAnimation")
            for k, a in enumerate(fr["alphas"]):
                self.keyframe(ka, self.clk.frames(k), f"{a:.4f}", "linear")
            self.dec.setdefault("flashes", []).append({"clip": c.id, "frames": [fr["n0"], fr["n1"]], "scope": fr["scope"],
                                                       "rect": fr["rect"], "resolution": [self.W, self.H]})

    def captions(self, spans, spine_els) -> None:
        for i, cap in enumerate(sorted(self.r.captions, key=lambda c: c.start)):
            n0 = int(round(cap.start * self.fps))
            n1 = max(n0 + 1, int(round(cap.end * self.fps)))
            n1 = min(n1, self.N)
            if n0 >= self.N:
                continue
            parent, local = self.anchor_for(spans, spine_els, n0)
            self._ts += 1
            ts = f"ts{self._ts}"
            el = ET.SubElement(parent, "caption", {
                "lane": str(10 + i % 5), "offset": self.clk.fmt(local), "name": f"{ROLE_KO.get(cap.role, cap.role)}",
                "start": "3600s", "duration": self.clk.frames(n1 - n0), "role": "iTT?captionFormat=ITT.ko"})
            tx = ET.SubElement(el, "text", {"placement": "bottom" if cap.anchor[1] > self.H / 2 else "top"})
            ET.SubElement(tx, "text-style", {"ref": ts}).text = "\n".join(cap.lines) if cap.lines else cap.text
            d = ET.SubElement(el, "text-style-def", {"id": ts})
            r_, g_, b_ = hex_rgb(cap.color)
            ET.SubElement(d, "text-style", {"font": cap.font_name, "fontSize": f"{cap.size_px:g}",
                                            "fontColor": f"{r_ / 255:.3f} {g_ / 255:.3f} {b_ / 255:.3f} 1",
                                            "backgroundColor": "0 0 0 0"})

    # ---------------------------------------------------------------- document
    def build(self, gain_extra: float) -> None:
        r = self.r
        lib = ET.SubElement(self.root, "library")
        ev = ET.SubElement(lib, "event", {"name": f"shortkit {r.episode_id}"})
        pj = ET.SubElement(ev, "project", {"name": r.episode_id})
        seq = ET.SubElement(pj, "sequence", {"format": self.seq_format, "duration": self.clk.frames(self.N),
                                              "tcStart": "0s", "tcFormat": "NDF", "audioLayout": "stereo",
                                              "audioRate": "48k"})
        spine = ET.SubElement(seq, "spine")
        spans = self.spine_items()
        spine_els: list[tuple[int, int, ET.Element, Fraction]] = []
        cur = 0
        for sp in spans:
            if sp["s"] > cur:
                g = ET.SubElement(spine, "gap", {"name": "Gap", "offset": self.clk.frames(cur), "start": "3600s",
                                                 "duration": self.clk.frames(sp["s"] - cur)})
                spine_els.append((cur, sp["s"], g, Fraction(3600)))
            if sp["tr"] is not None:
                o0, d = sp["tr"]
                t = ET.SubElement(spine, "transition", {"name": "Cross Dissolve", "offset": self.clk.frames(o0),
                                                        "duration": self.clk.frames(d)})
                ET.SubElement(t, "filter-video", {"ref": self.dissolve, "name": "Cross Dissolve"})
                self.dec["crossfades"].append({"clip": sp["clip"].id, "offset_frames": o0, "duration_frames": d,
                                               "cut_frame": sp["s"]})
            el = self.clip_element(spine, sp)
            spine_els.append((sp["s"], sp["e"], el, parse_time(el.get("start"))))
            cur = sp["e"]
        if cur < self.N:
            g = ET.SubElement(spine, "gap", {"name": "Gap", "offset": self.clk.frames(cur), "start": "3600s",
                                             "duration": self.clk.frames(self.N - cur)})
            spine_els.append((cur, self.N, g, Fraction(3600)))
        self.connected_audio(spans, spine_els, gain_extra)
        self.flashes(spans, spine_els)
        self.captions(spans, spine_els)

    def tostring(self) -> str:
        ET.indent(self.root, space="  ")
        return ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n'
                + ET.tostring(self.root, encoding="unicode") + "\n")


def export_with_decisions(resolved: ResolvedEdit, out_dir: Path, absolute: bool = False) -> tuple[Path, dict]:
    r = resolved
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dec: dict = {"format": "fcpxml", "version": FCPXML_VERSION, "file": f"{r.episode_id}.fcpxml",
                 "created_at": now_iso(), "absolute_urls": absolute, "warnings": [], "prerendered": [],
                 "crossfades": [], "verified": False,
                 "verification": "이 기계에 DaVinci Resolve / Final Cut Pro 가 없어 가져오기·렌더 확인 못 함(못 잼). "
                                 "XML 형식과 시간 일관성만 테스트함"}
    if not (out_dir / "captions.srt").is_file():
        dec["captions"] = write_caption_files(r, out_dir)
    rep = load_render_report(r)
    a = (rep or {}).get("audio") or {}
    gain = float(a.get("norm_gain_db") or 0.0) + float(a.get("final_trim_db") or 0.0)
    dec["loudness_gain_db"] = round(gain, 3) if a.get("norm_gain_db") is not None else None
    if a.get("norm_gain_db") is None:
        dec["warnings"].append("render_report.json 이 없어 음량 정규화 이득을 넣지 않음(못 잼)")
    b = FcpBuilder(r, out_dir, absolute, dec)
    b.fg_gain = master_foreground_gain(r, dec)
    b.build(gain)
    name = f"{r.episode_id}.local.fcpxml" if absolute else f"{r.episode_id}.fcpxml"
    out = out_dir / name
    out.write_text(b.tostring(), encoding="utf-8")
    dec["file"] = name
    dec["editable"] = ["클립 순서·트림·속도/정지(timeMap)", "crossfade(Cross Dissolve)", "위치·크기·줌 키프레임",
                       "clean crop(adjust-crop trim)", "오디오 클립별 음량 키프레임(BGM 덕킹·페이드, 효과음, 원본 소리)",
                       "자막 텍스트(caption 요소, 스타일 없음)"]
    dec["assumptions"] = [
        "adjust-transform position 단위 = 시퀀스 프레임 높이의 %, y 는 위쪽이 + (FCPXML 관례로 알려진 값; 이 기계에서 확인 못 함)",
        "adjust-crop trim-rect 단위 = 소스 가로/세로 각각의 %, trim-rect 의 left/top/right/bottom param 키프레임 "
        "애니메이션(줌 중 영상 영역 마스크 대용) (확인 못 함)",
        "줌: 움직이는 동안 프레임마다 linear 키프레임(마스터의 3차 easing·recenter 를 프레임 격자에서 그대로 재현; "
        "FCP 쪽 해석은 확인 못 함)",
        "timeMap 의 time 은 클립 로컬 시간(start 기준), value 는 소스 시간",
        "모노 오디오 파일: 마스터는 양쪽 채널에 같은 크기(0 dB)로 넣음(shortkit.util.media.read_audio) — "
        "Resolve/FCP 가 모노를 어떻게 스테레오에 놓는지(팬/레벨) 확인 못 함",
        "효과음/원본 소리 음량 키프레임에 마스터 전경 안전 리미터(build/fg_gain.json)를 프레임 단위로 더함"]
    dec["not_representable"] = [
        "영상 영역 마스크(trim-rect 로 영역 밖 소스를 잘라 대신함; 화면 가장자리 처리 차이 가능)",
        "delogo/blur (미리 정리한 중간 파일로 대체)",
        "자막·장식의 스타일/위치/모션(captions.ass 에만 있음)",
        "마스터의 샘플 단위 전경 리미터(프레임 단위 음량 키프레임으로 근사)"]
    if not absolute:
        merge_decisions(out_dir, "fcpxml", dec)
    return out, dec


def export(resolved: ResolvedEdit, out_dir: Path, absolute: bool = False) -> Path:
    """Contract API: write <out_dir>/<id>.fcpxml (relative media URLs; absolute=True -> <id>.local.fcpxml)."""
    return export_with_decisions(resolved, out_dir, absolute)[0]
