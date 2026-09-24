"""OpenTimelineIO (.otio) export from a ResolvedEdit (neutral interchange; Kdenlive/Resolve/others
import OTIO through their own adapters - none of which exist on this machine, so only a
write -> read round trip is tested).

Tracks: V1 배경 (solid colour generator), V2 영상 (one clip per play/hold piece, crossfades as
SMPTE_Dissolve transitions centred on the middle of the IR overlap), V3 플래시 (solid colour
generator clips), A1 BGM, A2 효과음 (+ extra lanes when SFX overlap), A3 원본 소리.
Media references are ExternalReference with target_url RELATIVE to the .otio file.
Metadata ``shortkit`` on every clip carries what OTIO has no schema for: zoom (from/to/centre/
start/dur/ease + per-frame canvas rects of the zoom), freeze, cleaning (crop, delogo, inpaint,
blur), region/fit, volume envelope.  Markers: one per SFX event (A2) and per caption (V2).
"""
from __future__ import annotations

import math
import os
from pathlib import Path

from .. import paths
from ..util.jsonio import now_iso
from ..util.media import probe
from .export_mlt import (EPS_PICK, Piece, build_segments, canvas_rect, crop_int, flash_runs, fps_of,
                         load_render_report, merge_decisions, n_frames, write_caption_files)
from .ir import Clip, ResolvedEdit

ROLE_COLOR = {"title": "RED", "description": "ORANGE", "situation": "YELLOW", "speaker": "CYAN", "dialogue": "GREEN",
              "reaction": "MAGENTA"}


def _otio():
    import opentimelineio as otio  # optional dependency (pyproject extra "otio")

    return otio


class OtioBuilder:
    def __init__(self, r: ResolvedEdit, out_dir: Path, dec: dict):
        self.otio = _otio()
        self.r = r
        self.out_dir = out_dir
        self.dec = dec
        self.fps = fps_of(r)
        self.N = n_frames(r)
        self._refs: dict[str, object] = {}

    def rt(self, frames: float):
        return self.otio.opentime.RationalTime(frames, self.fps)

    def tr(self, start: float, dur: float):
        return self.otio.opentime.TimeRange(self.rt(start), self.rt(dur))

    def url(self, root_rel: str) -> str:
        return Path(os.path.relpath(paths.absp(root_rel), self.out_dir)).as_posix()

    def ref(self, root_rel: str):
        info = probe(paths.absp(root_rel))
        n = int(math.floor(info.duration * self.fps + 1e-6))
        return self.otio.schema.ExternalReference(target_url=self.url(root_rel), available_range=self.tr(0, n),
                                                  metadata={"shortkit": {"root_relative": root_rel,
                                                                         "size": [info.width, info.height]
                                                                         if info.width else None,
                                                                         "has_audio": info.has_audio}})

    def solid(self, name: str, color: str, n: int, meta: dict):
        gref = self.otio.schema.GeneratorReference(name=name, generator_kind="SolidColor",
                                                   parameters={"color": color}, available_range=self.tr(0, n))
        return self.otio.schema.Clip(name=name, media_reference=gref, source_range=self.tr(0, n),
                                     metadata={"shortkit": meta})

    # ---------------------------------------------------------------- video
    def clip_meta(self, c: Clip, p: Piece | None) -> dict:
        def rect(x):
            return None if x is None else {"x": x.x, "y": x.y, "w": x.w, "h": x.h}

        m = {"clip_id": c.id, "source_id": c.source_id, "purpose": c.purpose, "speed": c.speed,
             "src_in": c.src_in, "src_out": c.src_out, "out_start": c.out_start, "out_end": c.out_end,
             "region": rect(c.region), "canvas_resolution": [self.r.canvas["width"], self.r.canvas["height"]],
             "fit": c.fit, "src_size": list(c.src_size),
             "coordinates": "region/canvas_rect: canvas px (canvas_resolution); crop/delogo/inpaint/blur/zoom.center: "
                            "SOURCE px (src_size)",
             "cleaning": {"crop": rect(c.crop),
                          "delogo": [dict(rect(d), start=d.start, end=d.end, reason=d.reason) for d in c.delogo],
                          "inpaint": [dict(rect(d), start=d.start, end=d.end, reason=d.reason) for d in c.inpaint],
                          "blur": [dict(rect(d), start=d.start, end=d.end, reason=d.reason) for d in c.blur],
                          "inpaint_baked_into_source": bool(c.inpaint)},
             "zoom": None, "freeze": None, "transition_in": {"type": c.transition_in.type, "dur": c.transition_in.dur,
                                                             "color": c.transition_in.color}}
        if c.zoom:
            z = c.zoom
            m["zoom"] = {"scale_from": z.scale_from, "scale_to": z.scale_to, "center_src": list(z.center_src),
                         "start": z.start, "dur": z.dur, "ease": z.ease, "ease_curve": "cubic (render.py)"}
        if c.freeze:
            f = c.freeze
            m["freeze"] = {"src_t": f.src_t, "out_start": f.out_start, "hold": f.hold}
        if p is not None:
            m["piece"] = {"kind": p.kind, "out_frames": [p.n0, p.n1], "source_time_at_start": round(p.s0, 6)}
            rects = {}
            if c.zoom and abs(c.zoom.scale_to - c.zoom.scale_from) > 1e-9:
                for n in range(p.n0, p.n1):
                    rects[str(n - p.n0)] = [round(v, 3) for v in canvas_rect(c, n, self.fps)]
            else:
                rects["0"] = [round(v, 3) for v in canvas_rect(c, p.n0, self.fps)]
            m["piece"]["canvas_rect_by_frame"] = rects
        return m

    def piece_clip(self, p: Piece, n: int | None = None, n0: int | None = None):
        """OTIO clip for a piece (optionally only frames [n0, n0+n) of it)."""
        c = self.r.clips[p.clip_index]
        src_rel = c.source_path
        if c.delogo or c.blur:
            from .export_fcpxml import FcpBuilder

            src_rel, off = FcpBuilder(self.r, self.out_dir, False, self.dec).nle_source(c)
        else:
            off = 0.0
        first = p.n0 if n0 is None else n0
        cnt = (p.n1 - first) if n is None else n
        from .export_mlt import source_time

        s = (p.s0 if p.kind == "hold" else source_time(c, first, self.fps)) - off
        start = int(math.floor((s + EPS_PICK) * self.fps + 1e-9))
        effects = []
        if p.kind == "hold":
            effects.append(self.otio.schema.FreezeFrame(name="freeze"))
            dur_media = cnt
        elif abs(c.speed - 1.0) > 1e-9:
            effects.append(self.otio.schema.LinearTimeWarp(name="speed", time_scalar=c.speed))
            dur_media = cnt
        else:
            dur_media = cnt
        name = f"{c.id}" + (" 정지" if p.kind == "hold" else "")
        cl = self.otio.schema.Clip(name=name, media_reference=self.ref(src_rel), source_range=self.tr(start, dur_media),
                                   metadata={"shortkit": self.clip_meta(c, p)})
        cl.effects[:] = effects
        return cl

    def video_track(self):
        otio = self.otio
        tr = otio.schema.Track(name="V2 영상", kind=otio.schema.TrackKind.Video)
        segs = build_segments(self.r, self.dec["warnings"])
        cur = 0
        pending_tr = None
        for s in segs:
            if s.kind == "blank":
                tr.append(otio.schema.Gap(source_range=self.tr(0, s.n1 - s.n0)))
                cur = s.n1
                continue
            if s.kind == "piece":
                for p in s.pieces:
                    tr.append(self.piece_clip(p))
                    if pending_tr is not None:
                        pending_tr = None
                cur = s.n1
                continue
            # crossfade [n0, n1): outgoing plays until the cut, incoming from the cut; transition around it
            cut = (s.n0 + s.n1) // 2
            for p in s.a_pieces:
                if p.n0 < cut:
                    tr.append(self.piece_clip(p, n=min(p.n1, cut) - p.n0))
            t = otio.schema.Transition(name="crossfade", transition_type=otio.schema.TransitionTypes.SMPTE_Dissolve,
                                       in_offset=self.rt(cut - s.n0), out_offset=self.rt(s.n1 - cut),
                                       metadata={"shortkit": {"ir_overlap_frames": [s.n0, s.n1], "cut_frame": cut}})
            tr.append(t)
            for p in s.b_pieces:
                if p.n1 > cut:
                    a = max(p.n0, cut)
                    tr.append(self.piece_clip(p, n=p.n1 - a, n0=a))
            cur = s.n1
        if cur < self.N:
            tr.append(otio.schema.Gap(source_range=self.tr(0, self.N - cur)))
        for cap in sorted(self.r.captions, key=lambda c: c.start):
            n0 = int(round(cap.start * self.fps))
            n1 = max(n0 + 1, int(round(cap.end * self.fps)))
            tr.markers.append(otio.schema.Marker(
                name=cap.text.replace("\n", " "), marked_range=self.tr(n0, n1 - n0),
                color=getattr(otio.schema.MarkerColor, ROLE_COLOR.get(cap.role, "WHITE")),
                metadata={"shortkit": {"kind": "caption", "id": cap.id, "role": cap.role, "lines": cap.lines,
                                       "anchor": list(cap.anchor), "resolution": [self.r.canvas["width"],
                                                                                  self.r.canvas["height"]],
                                       "font_name": cap.font_name, "size_px": cap.size_px,
                                       "grounding": cap.grounding, "drawn_by": "captions.ass (libass)"}}))
        return tr

    def background_track(self):
        otio = self.otio
        tr = otio.schema.Track(name="V1 배경", kind=otio.schema.TrackKind.Video)
        bg = self.r.canvas.get("background") or {}
        tr.append(self.solid("배경", bg.get("color") or "#000000", self.N,
                             {"background": bg, "note": "blur_source 면 흐린 소스를 배경으로(마스터 기준)"}))
        return tr

    def flash_track(self):
        otio = self.otio
        runs = flash_runs(self.r)
        if not runs:
            return None
        tr = otio.schema.Track(name="V3 플래시", kind=otio.schema.TrackKind.Video)
        cur = 0
        for fr in runs:
            if fr["n0"] < cur:
                continue
            if fr["n0"] > cur:
                tr.append(otio.schema.Gap(source_range=self.tr(0, fr["n0"] - cur)))
            c = self.r.clips[fr["clip_index"]]
            n = fr["n1"] - fr["n0"]
            tr.append(self.solid(f"플래시 {c.id}", fr["color"], n,
                                 {"opacity_by_frame": [round(a, 4) for a in fr["alphas"]],
                                  "region": {"x": c.region.x, "y": c.region.y, "w": c.region.w, "h": c.region.h}}))
            cur = fr["n1"]
        return tr

    # ---------------------------------------------------------------- audio
    def lanes(self, items):
        lanes: list[list] = []
        for it in sorted(items, key=lambda x: x[0]):
            for ln in lanes:
                if ln[-1][1] <= it[0]:
                    ln.append(it)
                    break
            else:
                lanes.append([it])
        return lanes

    def audio_track(self, name: str, items: list[tuple[int, int, object]]):
        otio = self.otio
        tr = otio.schema.Track(name=name, kind=otio.schema.TrackKind.Audio)
        cur = 0
        for n0, n1, clip in items:
            if n0 > cur:
                tr.append(otio.schema.Gap(source_range=self.tr(0, n0 - cur)))
            tr.append(clip)
            cur = n1
        return tr

    def audio_tracks(self, gain_extra: float) -> list:
        otio = self.otio
        r = self.r
        out = []
        b = r.audio.bgm
        if b is not None and b.path:
            src, offset = b.path, b.section_start_s
            if abs(b.tempo_ratio - 1.0) > 1e-9:
                from .export_mlt import Media

                src = Media(r, self.out_dir, self.dec).tempo_bgm(b.path, b.tempo_ratio, r.audio.sample_rate)
                offset = b.section_start_s / b.tempo_ratio
            cl = otio.schema.Clip(name="BGM", media_reference=self.ref(src),
                                  source_range=self.tr(int(round(offset * self.fps)), self.N),
                                  metadata={"shortkit": {"track_id": b.track_id, "section_start_s": b.section_start_s,
                                                         "tempo_ratio": b.tempo_ratio, "gain_db": b.gain_db,
                                                         "loudness_gain_db": gain_extra, "fade_in_s": b.fade_in_s,
                                                         "fade_out_s": b.fade_out_s,
                                                         "envelope_db": [list(p) for p in b.envelope],
                                                         "duck_ranges": [list(x) for x in b.duck_ranges],
                                                         "silences": [list(x) for x in b.silences]}})
            out.append(self.audio_track("A1 BGM", [(0, self.N, cl)]))
        sfx_items = []
        for s in r.audio.sfx:
            if not s.path:
                continue
            n0 = int(round(s.t * self.fps))
            if n0 >= self.N:
                continue
            info = probe(paths.absp(s.path))
            n = max(1, min(int(math.ceil(info.duration * self.fps)), self.N - n0))
            cl = otio.schema.Clip(name=f"효과음 {s.type}", media_reference=self.ref(s.path), source_range=self.tr(0, n),
                                  metadata={"shortkit": {"id": s.id, "type": s.type, "gain_db": s.gain_db,
                                                         "loudness_gain_db": gain_extra, "event_t": s.event_t,
                                                         "event_desc": s.event_desc, "map_status": s.map_status}})
            sfx_items.append((n0, n0 + n, cl, s))
        for li, lane in enumerate(self.lanes([(a, b_, (c, s)) for a, b_, c, s in sfx_items])):
            tr = self.audio_track("A2 효과음" if li == 0 else f"A2 효과음 {li + 1}", [(a, b_, cs[0]) for a, b_, cs in lane])
            for a, b_, (c, s) in lane:
                tr.markers.append(otio.schema.Marker(
                    name=f"{s.type}: {s.event_desc}", marked_range=self.tr(int(round(s.event_t * self.fps)), 1),
                    color=otio.schema.MarkerColor.PINK,
                    metadata={"shortkit": {"kind": "sfx_event", "sfx_id": s.id, "sfx_t": s.t, "event_t": s.event_t,
                                           "offset_s": round(s.t - s.event_t, 4)}}))
            out.append(tr)
        orig_items = []
        for o in r.audio.originals:
            n0 = int(round(o.out_start * self.fps))
            n = max(1, int(round((o.out_end - o.out_start) * self.fps)))
            src, start = o.path, o.src_start
            if abs(o.speed - 1.0) > 1e-9:
                from .export_mlt import Media

                src = Media(r, self.out_dir, self.dec).tempo_original(o, r.audio.sample_rate)
                start = 0.0
            cl = otio.schema.Clip(name=f"원본 소리 {o.clip_id}", media_reference=self.ref(src),
                                  source_range=self.tr(int(round(start * self.fps)), n),
                                  metadata={"shortkit": {"clip_id": o.clip_id, "stem": o.stem, "gain_db": o.gain_db,
                                                         "loudness_gain_db": gain_extra, "fade_s": o.fade_s,
                                                         "speed": o.speed, "reason": o.reason}})
            orig_items.append((n0, n0 + n, cl))
        for li, lane in enumerate(self.lanes(orig_items)):
            out.append(self.audio_track("A3 원본 소리" if li == 0 else f"A3 원본 소리 {li + 1}", lane))
        return out

    def build(self, gain_extra: float):
        otio = self.otio
        r = self.r
        tl = otio.schema.Timeline(name=r.episode_id, global_start_time=self.rt(0))
        tl.metadata["shortkit"] = {
            "schema": "shortkit.otio/1", "episode_id": r.episode_id, "preset_id": r.preset_id, "mode": r.mode,
            "canvas": {k: v for k, v in r.canvas.items() if k != "encode"}, "duration_s": r.duration,
            "frames": self.N, "captions_file": "captions.ass", "captions_srt": "captions.srt",
            "note": "자막·장식은 captions.ass 한 파일(libass)로 그려짐; OTIO 마커는 위치 표시용"}
        tl.tracks.append(self.background_track())
        tl.tracks.append(self.video_track())
        ft = self.flash_track()
        if ft is not None:
            tl.tracks.append(ft)
        for t in self.audio_tracks(gain_extra):
            tl.tracks.append(t)
        return tl


def export_with_decisions(resolved: ResolvedEdit, out_dir: Path) -> tuple[Path, dict]:
    otio = _otio()
    r = resolved
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dec: dict = {"format": "otio", "file": f"{r.episode_id}.otio", "created_at": now_iso(), "warnings": [],
                 "prerendered": [], "otio_version": otio.__version__, "verified": False,
                 "verification": "OTIO 는 자체 렌더러가 없어 렌더 동등성 못 잼; 쓰기→읽기 왕복과 구조만 테스트함"}
    if not (out_dir / "captions.srt").is_file():
        dec["captions"] = write_caption_files(r, out_dir)
    rep = load_render_report(r)
    a = (rep or {}).get("audio") or {}
    gain = float(a.get("norm_gain_db") or 0.0) + float(a.get("final_trim_db") or 0.0)
    b = OtioBuilder(r, out_dir, dec)
    tl = b.build(gain)
    out = out_dir / f"{r.episode_id}.otio"
    otio.adapters.write_to_file(tl, str(out))
    dec["tracks"] = [{"name": t.name, "kind": str(t.kind), "items": len(t)} for t in tl.tracks]
    dec["markers"] = {"captions": len(r.captions), "sfx_events": sum(1 for s in r.audio.sfx if s.path)}
    merge_decisions(out_dir, "otio", dec)
    return out, dec


def export(resolved: ResolvedEdit, out_dir: Path) -> Path:
    """Contract API: write <out_dir>/<id>.otio."""
    return export_with_decisions(resolved, out_dir)[0]
