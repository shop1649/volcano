"""Editable MLT XML project (Shotcut-openable, rendered by melt 7.22) from a ResolvedEdit.

Consumes ONLY the ResolvedEdit IR (+ files it references) and mirrors the master renderer's
semantics (``shortkit.edit.render`` / ``shortkit.edit.resolve`` helpers are imported so the two
cannot drift):

  frame n shows time t = n / fps; a clip is active for out_start - 1e-6 <= t < out_end - 1e-6
  source time at local time u = t - out_start: resolve.src_time_at (speed, freeze hold)
  placement: resolve.src_to_region (cover/contain fit + eased zoom about zoom.center, clipped to
             the video region)
  crossfade: linear blend over [b.out_start, a.out_end); flash: colour over the video region with
             alpha = 1 - |t - cut| / (dur / 2)
  captions + decorations: the ONE ASS file drawn over everything by libass

Track layout (tractor, bottom -> top)::

    0  background      Shotcut's hidden black producer
    V1 배경            canvas background (colour, or blurred source for blur_source)
    V2 영상            one producer per clip piece (crop -> delogo -> affine -> qtcrop); crossfades
                       are Shotcut transition tractors (luma + mix)
    V3 플래시          colour producers with keyframed opacity (only if a flash exists)
    A1 BGM             clean music file (tempo pre-render if tempo_ratio != 1), volume keyframes
    A2.. 효과음        one clip per SFX at t (extra tracks only when SFX overlap)
    A3.. 원본 소리      kept original audio / vocals stem with gain + fades
    tractor filters    avfilter.subtitles (captions.ass next to the project), volume (loudness gain)

MLT facts this module relies on (checked with melt 7.22 on the build machine, see
tests/export): filter keyframes are relative to the filter's ``in`` which must equal the playlist
entry ``in`` while the producer spans its whole length (Shotcut style); the ``freeze`` filter
dead-locks melt 7.22 -> held frames are still-image producers extracted with ffmpeg; affine
placement is exact only when rendering at the profile resolution; qtcrop/qtblend need an X
display (melt is run through ``xvfb-run`` when DISPLAY is unset).
"""
from __future__ import annotations

import math
import os
import shutil
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

from .. import paths
from ..util.hashing import sha256_text
from ..util.jsonio import now_iso, read_json, write_json
from ..util.media import MediaError, ffmpeg, probe
from .ir import Clip, ResolvedEdit
from .resolve import base_fit, effective_src_rect, ease as r_ease, src_time_at, src_to_region

MLT_VERSION = "7.22.0"
EPS_ACTIVE = 1e-6          # render.Compositor.frame activity margin
EPS_PICK = 1e-3            # render.EPS_T: a source frame is shown when pts <= s + 1 ms
SILENCE_DB_FLOOR = -120.0  # audio.SILENCE_DB; MLT volume level at this value is inaudible
DECISIONS_FILE = "export_decisions.json"

# render.py easing is cubic; these are melt 7.22's cubic easing keyframe operators
_MLT_EASE = {"linear": "", "in": "g", "out": "h", "inout": "i"}


# ============================================================================ shared helpers
def _cubic(p: float, kind: str) -> float:
    p = min(1.0, max(0.0, p))
    if kind == "in":
        return p ** 3
    if kind == "out":
        return 1.0 - (1.0 - p) ** 3
    if kind == "inout":
        return 4 * p ** 3 if p < 0.5 else 1.0 - (-2.0 * p + 2.0) ** 3 / 2.0
    return p


def native_ease_ok(kind: str) -> bool:
    """True when resolve.ease(kind) is the cubic curve melt implements natively."""
    if kind not in _MLT_EASE:
        return False
    return all(abs(r_ease(p, kind) - _cubic(p, kind)) < 1e-9 for p in (0.1, 0.25, 0.4, 0.5, 0.6, 0.9))


def fps_of(r: ResolvedEdit) -> float:
    return float(r.canvas["fps"])


def fps_fraction(fps: float) -> Fraction:
    return Fraction(fps).limit_denominator(1001)


def first_frame(t: float, fps: float) -> int:
    """First frame n with n/fps >= t - 1e-6 (render activity rule)."""
    return int(math.ceil((t - EPS_ACTIVE) * fps - 1e-9))


def n_frames(r: ResolvedEdit) -> int:
    return int(round(r.duration * fps_of(r)))


def rel_to(path_root_rel: str, out_dir: Path) -> str:
    """Root-relative stored path -> path relative to the project folder (POSIX)."""
    return Path(os.path.relpath(paths.absp(path_root_rel), out_dir)).as_posix()


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = (h or "#000000").lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def mlt_color(h: str, alpha: int = 255) -> str:
    r, g, b = hex_rgb(h)
    return f"#{alpha:02X}{r:02X}{g:02X}{b:02X}"


def fmt(v: float, nd: int = 4) -> str:
    s = f"{v:.{nd}f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def db(x: float) -> float:
    return 20.0 * math.log10(x) if x > 1e-6 else SILENCE_DB_FLOOR


@dataclass
class Piece:
    """A run of output frames [n0, n1) of one clip shown by one producer."""
    clip_index: int
    kind: str                  # play | hold
    n0: int
    n1: int
    s0: float                  # source time shown at n0 (hold: the held source time)

    @property
    def length(self) -> int:
        return self.n1 - self.n0


@dataclass
class Segment:
    """One element of the V2 playlist: a plain piece, or a crossfade overlap (pieces of A and B)."""
    n0: int
    n1: int
    pieces: list[Piece] = field(default_factory=list)          # plain
    a_pieces: list[Piece] = field(default_factory=list)        # crossfade outgoing
    b_pieces: list[Piece] = field(default_factory=list)        # crossfade incoming
    kind: str = "piece"                                         # piece | crossfade | blank


def clip_frame_range(c: Clip, fps: float) -> tuple[int, int]:
    return first_frame(c.out_start, fps), first_frame(c.out_end, fps)


def clip_pieces(r: ResolvedEdit, i: int) -> list[Piece]:
    """Split clip i into play/hold runs exactly where render.src_time_at switches."""
    c = r.clips[i]
    fps = fps_of(r)
    n0, n1 = clip_frame_range(c, fps)
    if n1 <= n0:
        return []
    kinds: list[tuple[int, str]] = []
    f = c.freeze
    for n in range(n0, n1):
        u = n / fps - c.out_start
        k = "play"
        if f is not None:
            fl = f.out_start - c.out_start
            if fl <= u < fl + f.hold:
                k = "hold"
        if not kinds or kinds[-1][1] != k:
            kinds.append((n, k))
    out = []
    for j, (a, k) in enumerate(kinds):
        b = kinds[j + 1][0] if j + 1 < len(kinds) else n1
        s0 = source_time(c, a, fps)
        out.append(Piece(i, k, a, b, s0))
    return out


def source_time(c: Clip, n: int, fps: float) -> float:
    s = src_time_at(c, n / fps - c.out_start)
    return min(s, c.src_out - 2 * EPS_PICK)


def split_piece(p: Piece, n: int, c: Clip, fps: float) -> tuple[Piece, Piece]:
    assert p.n0 < n < p.n1
    a = Piece(p.clip_index, p.kind, p.n0, n, p.s0)
    b = Piece(p.clip_index, p.kind, n, p.n1, p.s0 if p.kind == "hold" else source_time(c, n, fps))
    return a, b


def build_segments(r: ResolvedEdit, warnings: list[str]) -> list[Segment]:
    """Lay clip pieces on one track; crossfade overlaps become transition segments."""
    fps = fps_of(r)
    per_clip = [clip_pieces(r, i) for i in range(len(r.clips))]
    segs: list[Segment] = []
    cursor = 0
    for i, c in enumerate(r.clips):
        pcs = per_clip[i]
        if not pcs:
            warnings.append(f"클립 {c.id}: 출력 프레임이 0개라 건너뜀")
            continue
        start = pcs[0].n0
        if c.transition_in.type == "crossfade" and segs and start < cursor:
            # overlap [start, cursor): pull A's pieces that fall inside out of the previous segments
            o0, o1 = start, cursor
            a_in: list[Piece] = []
            while segs and segs[-1].n1 > o0:
                s = segs.pop()
                if s.kind != "piece":
                    warnings.append(f"클립 {c.id}: 겹치는 전환이 연속되어 이전 전환 일부가 잘림")
                    src = s.b_pieces
                else:
                    src = s.pieces
                keep: list[Piece] = []
                for p in src:
                    if p.n1 <= o0:
                        keep.append(p)
                    elif p.n0 >= o0:
                        a_in.append(p)
                    else:
                        x, y = split_piece(p, o0, r.clips[p.clip_index], fps)
                        keep.append(x)
                        a_in.append(y)
                if keep:
                    segs.append(Segment(keep[0].n0, keep[-1].n1, pieces=keep))
                    break
            a_in.sort(key=lambda p: p.n0)
            b_in: list[Piece] = []
            rest: list[Piece] = []
            for p in pcs:
                if p.n1 <= o1:
                    b_in.append(p)
                elif p.n0 >= o1:
                    rest.append(p)
                else:
                    x, y = split_piece(p, o1, c, fps)
                    b_in.append(x)
                    rest.append(y)
            if a_in and b_in and a_in[0].n0 == o0 and b_in[-1].n1 == o1:
                segs.append(Segment(o0, o1, a_pieces=a_in, b_pieces=b_in, kind="crossfade"))
            else:
                warnings.append(f"클립 {c.id}: crossfade 구간 구성 실패 → 컷으로 처리")
                segs.append(Segment(o0, o1, pieces=b_in))
            pcs = rest
            cursor = o1
            if not pcs:
                continue
            start = pcs[0].n0
        if start < cursor:
            # overlapping cut (should not happen for a valid IR): trim the incoming clip
            warnings.append(f"클립 {c.id}: 앞 클립과 {cursor - start}프레임 겹침(crossfade 아님) → 앞부분을 잘라 맞춤")
            trimmed = []
            for p in pcs:
                if p.n1 <= cursor:
                    continue
                if p.n0 < cursor:
                    p = split_piece(p, cursor, c, fps)[1]
                trimmed.append(p)
            pcs = trimmed
            if not pcs:
                continue
            start = pcs[0].n0
        if start > cursor:
            segs.append(Segment(cursor, start, kind="blank"))
        segs.append(Segment(pcs[0].n0, pcs[-1].n1, pieces=pcs))
        cursor = pcs[-1].n1
    return segs


def flash_runs(r: ResolvedEdit) -> list[dict]:
    """Frames where render draws a flash: [{clip_index, n0, n1, alphas[], color}]."""
    fps = fps_of(r)
    N = n_frames(r)
    runs = []
    for i, c in enumerate(r.clips):
        tr = c.transition_in
        if tr.type != "flash" or tr.dur <= 0:
            continue
        half = tr.dur / 2.0
        lo = max(0, int(math.floor((c.out_start - half) * fps)) - 1)
        hi = min(N, int(math.ceil((c.out_start + half) * fps)) + 2)
        frames = []
        for n in range(lo, hi):
            d = abs(n / fps - c.out_start)
            if d < half:
                frames.append((n, 1.0 - d / half))
        if not frames:
            continue
        runs.append({"clip_index": i, "n0": frames[0][0], "n1": frames[-1][0] + 1,
                     "alphas": [a for _, a in frames], "color": tr.color or "#FFFFFF"})
    return runs


def region_int(c: Clip) -> tuple[int, int, int, int]:
    R = c.region
    return int(round(R.x)), int(round(R.y)), int(round(R.w)), int(round(R.h))


def crop_int(c: Clip) -> tuple[int, int, int, int]:
    ex, ey, ew, eh = effective_src_rect(c)
    return int(round(ex)), int(round(ey)), int(round(ew)), int(round(eh))


def canvas_rect(c: Clip, n: int, fps: float) -> tuple[float, float, float, float]:
    """Canvas rect of the (cropped) source image at output frame n (render.src_to_region)."""
    s, tx, ty = src_to_region(c, n / fps - c.out_start)
    _, _, cw, ch = crop_int(c)
    R = c.region
    rx, ry, _, _ = region_int(c)
    return rx + tx, ry + ty, s * cw, s * ch


def load_render_report(r: ResolvedEdit) -> dict | None:
    return read_json(paths.absp(f"episodes/{r.episode_id}/build/render_report.json"))


def write_caption_files(r: ResolvedEdit, out_dir: Path) -> dict:
    """Copy the ONE ASS file next to the project and write captions.srt (all roles)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    res: dict = {"ass": None, "srt": None, "notes": []}
    src = paths.absp(r.ass_path)
    if src.is_file():
        shutil.copyfile(src, out_dir / "captions.ass")
        res["ass"] = "captions.ass"
    else:
        res["notes"].append(f"ASS 파일 없음: {r.ass_path} → 자막/장식 레이어를 넣지 못함")
    order = {"title": 0, "description": 1, "situation": 2, "speaker": 3, "dialogue": 4, "reaction": 5}
    caps = sorted(r.captions, key=lambda c: (c.start, order.get(c.role, 9), c.id))
    lines = []
    for k, c in enumerate(caps, 1):
        text = "\n".join(c.lines) if c.lines else c.text
        lines += [str(k), f"{_srt_time(c.start)} --> {_srt_time(c.end)}", text.strip() or " ", ""]
    (out_dir / "captions.srt").write_text("\n".join(lines), encoding="utf-8")
    res["srt"] = "captions.srt"
    res["srt_count"] = len(caps)
    res["roles"] = sorted({c.role for c in caps})
    return res


def _srt_time(t: float) -> str:
    ms = int(round(max(0.0, t) * 1000))
    h, ms = divmod(ms, 3600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def merge_decisions(out_dir: Path, key: str, value: dict) -> dict:
    f = out_dir / DECISIONS_FILE
    d = read_json(f, {}) or {}
    d[key] = value
    d["updated_at"] = now_iso()
    write_json(f, d)
    return d


# ============================================================================ media preparation
class Media:
    """Per-export media cache: probes, blur intermediates, held-frame stills, tempo BGM."""

    def _record(self, rec: dict) -> None:
        if not any(x.get("file") == rec.get("file") for x in self.dec["prerendered"]):
            self.dec["prerendered"].append(rec)

    def __init__(self, r: ResolvedEdit, out_dir: Path, decisions: dict):
        self.r = r
        self.out_dir = out_dir
        self.media_dir = out_dir / "media"
        self.dec = decisions
        self._probe: dict[str, object] = {}
        self._blur: dict[str, tuple[str, float]] = {}

    def info(self, rel: str):
        if rel not in self._probe:
            try:
                self._probe[rel] = probe(paths.absp(rel))
            except (MediaError, OSError) as e:
                self._probe[rel] = None
                self.dec["warnings"].append(f"미디어를 읽지 못함: {rel}: {str(e)[:120]}")
        return self._probe[rel]

    def source_for(self, c: Clip) -> tuple[str, float]:
        """(root-relative file, time offset) the pieces of clip c read from.

        Blur ops have no region-limited MLT equivalent without masks, so a blurred intermediate
        covering the clip's source range is pre-rendered (render.BLUR_SIGMA_FRAC).  Inpaint is
        already baked into c.source_path by resolve (warehouse/cache/clean/...)."""
        if not c.blur:
            return c.source_path, 0.0
        if c.id in self._blur:
            return self._blur[c.id]
        from .render import BLUR_SIGMA_FRAC

        info = self.info(c.source_path)
        sfps = (info.fps if info else None) or 30.0
        a = max(0.0, math.floor((c.src_in - 1.0) * sfps) / sfps)
        b = c.src_out + 1.0
        key = sha256_text(repr((c.source_path, a, b, [(x.x, x.y, x.w, x.h, x.start, x.end) for x in c.blur])))[:12]
        self.media_dir.mkdir(parents=True, exist_ok=True)
        out = self.media_dir / f"{c.id}_blur_{key}.mp4"
        chain, last = [], "[0:v]"
        for j, bl in enumerate(c.blur):
            x, y = int(round(bl.x)), int(round(bl.y))
            w, h = max(2, int(round(bl.w))), max(2, int(round(bl.h)))
            sig = max(1.0, max(bl.w, bl.h) * BLUR_SIGMA_FRAC)
            s0 = (bl.start if bl.start is not None else 0.0) - a
            s1 = (bl.end if bl.end is not None else 1e9) - a
            chain.append(f"{last}split[m{j}][c{j}];[c{j}]crop={w}:{h}:{x}:{y},gblur=sigma={sig:.3f}[b{j}];"
                         f"[m{j}][b{j}]overlay={x}:{y}:enable='between(t,{s0:.4f},{s1:.4f})'[o{j}]")
            last = f"[o{j}]"
        if not out.is_file():
            ffmpeg(["-ss", f"{a:.6f}", "-i", paths.absp(c.source_path), "-t", f"{b - a:.6f}", "-an",
                    "-filter_complex", ";".join(chain), "-map", last, "-fps_mode", "passthrough",
                    "-c:v", "libx264", "-preset", "veryfast", "-crf", "12", "-pix_fmt", "yuv420p", out])
        rel = paths.relp(out)
        self._blur[c.id] = (rel, a)
        self._record({
            "kind": "blur_intermediate", "clip": c.id, "file": Path(os.path.relpath(out, self.out_dir)).as_posix(),
            "why": "영역 흐림(blur)은 MLT 필터만으로 같은 영역·시간에 적용할 수 없어 미리 렌더한 중간 파일을 사용",
            "source_range_s": [round(a, 4), round(b, 4)],
            "sigma_rule": "gaussian sigma = max(w, h) / 6 (SOURCE px, render.BLUR_SIGMA_FRAC)"})
        return self._blur[c.id]

    def hold_still(self, c: Clip, src_rel: str, offset: float, s: float) -> str:
        """PNG of the source frame render shows at source time s (last frame with pts <= s + 1 ms)."""
        info = self.info(src_rel)
        sfps = (info.fps if info else None) or 30.0
        st = 0.0
        if info is not None:
            v = next((x for x in info.raw.get("streams", []) if x.get("codec_type") == "video"), {})
            try:
                st = float(v.get("start_time") or 0.0)
            except (TypeError, ValueError):
                st = 0.0
        local = s - offset
        k = max(0, int(math.floor((local + EPS_PICK - st) * sfps + 1e-9)))
        t_seek = max(0.0, st + (k - 0.25) / sfps)
        key = sha256_text(repr((src_rel, round(local, 6), k)))[:12]
        self.media_dir.mkdir(parents=True, exist_ok=True)
        out = self.media_dir / f"{c.id}_hold_{key}.png"
        if not out.is_file():
            ffmpeg(["-ss", f"{t_seek:.6f}", "-i", paths.absp(src_rel), "-frames:v", "1", "-an", out])
        self._record({
            "kind": "freeze_still", "clip": c.id, "file": Path(os.path.relpath(out, self.out_dir)).as_posix(),
            "source_time_s": round(s, 4), "source_frame_index": k,
            "why": "정지(freeze)는 원본의 한 프레임을 이미지로 뽑아 이미지 클립으로 넣음 "
                   "(melt 7.22 의 freeze 필터는 렌더가 멈추는 문제가 있어 사용하지 않음)"})
        return paths.relp(out)

    def tempo_bgm(self, src_rel: str, ratio: float, sr: int) -> str:
        from .render import tempo_stretch

        key = sha256_text(repr((src_rel, ratio, sr)))[:12]
        self.media_dir.mkdir(parents=True, exist_ok=True)
        out = self.media_dir / f"bgm_tempo_{key}.wav"
        method = "cached"
        if not out.is_file():
            method = tempo_stretch(paths.absp(src_rel), ratio, out, sr)
        self._record({
            "kind": "bgm_tempo", "file": Path(os.path.relpath(out, self.out_dir)).as_posix(), "tempo_ratio": ratio,
            "method": method, "source": src_rel,
            "why": f"BGM 속도 {ratio:g}배: 원곡 대비 속도 변경을 마스터와 같은 방법(render.tempo_stretch)으로 미리 렌더"})
        return paths.relp(out)

    def tempo_original(self, o, sr: int) -> str:
        from .render import _atempo_chain

        key = sha256_text(repr((o.path, o.src_start, o.src_end, o.speed)))[:12]
        self.media_dir.mkdir(parents=True, exist_ok=True)
        out = self.media_dir / f"orig_{o.clip_id}_{key}.wav"
        if not out.is_file():
            ffmpeg(["-ss", f"{o.src_start:.6f}", "-i", paths.absp(o.path), "-t", f"{o.src_end - o.src_start:.6f}",
                    "-vn", "-af", _atempo_chain(o.speed), "-ar", str(sr), "-ac", "2", "-c:a", "pcm_s16le", out])
        self._record({
            "kind": "original_tempo", "clip": o.clip_id, "file": Path(os.path.relpath(out, self.out_dir)).as_posix(),
            "why": f"원본 소리 {o.speed:g}배속: 마스터와 같은 atempo(음높이 유지)로 미리 렌더"})
        return paths.relp(out)


# ============================================================================ XML builder
class MltBuilder:
    def __init__(self, r: ResolvedEdit, out_dir: Path, decisions: dict):
        self.r = r
        self.out_dir = out_dir
        self.fps = fps_of(r)
        self.N = n_frames(r)
        self.W, self.H = int(r.canvas["width"]), int(r.canvas["height"])
        self.dec = decisions
        self.media = Media(r, out_dir, decisions)
        self.root = ET.Element("mlt", {"LC_NUMERIC": "C", "version": MLT_VERSION, "title": f"shortkit {r.episode_id}",
                                       "producer": "main_bin"})
        self._ids: dict[str, int] = {}
        self.tracks: list[tuple[str, str, str]] = []   # (playlist id, kind video|audio, hide)
        self.track_names: list[dict] = []
        self.fg_gain: list[float] | None = None

    # ---------------------------------------------------------------- small utils
    def uid(self, prefix: str) -> str:
        k = self._ids.get(prefix, 0)
        self._ids[prefix] = k + 1
        return f"{prefix}{k}"

    @staticmethod
    def prop(el: ET.Element, name: str, value) -> None:
        p = ET.SubElement(el, "property", {"name": name})
        p.text = str(value)

    def rel(self, root_rel: str) -> str:
        return rel_to(root_rel, self.out_dir)

    def src_length(self, rel: str) -> int:
        info = self.media.info(rel)
        if info is None or not info.duration:
            return 0
        return int(math.floor(info.duration * self.fps + 1e-6))

    # ---------------------------------------------------------------- profile / bin
    def profile(self) -> None:
        fr = fps_fraction(self.fps)
        g = math.gcd(self.W, self.H)
        ET.SubElement(self.root, "profile", {
            "description": f"shortkit {self.W}x{self.H} {float(fr):g}fps", "width": str(self.W), "height": str(self.H),
            "progressive": "1", "sample_aspect_num": "1", "sample_aspect_den": "1",
            "display_aspect_num": str(self.W // g), "display_aspect_den": str(self.H // g),
            "frame_rate_num": str(fr.numerator), "frame_rate_den": str(fr.denominator), "colorspace": "709"})
        pl = ET.SubElement(self.root, "playlist", {"id": "main_bin"})
        self.prop(pl, "xml_retain", 1)
        self.prop(pl, "shotcut:projectAudioChannels", 2)
        self.prop(pl, "shotcut:projectFolder", 1)

    def background_black(self) -> None:
        p = ET.SubElement(self.root, "producer", {"id": "black", "in": "0", "out": str(self.N - 1)})
        for k, v in (("length", self.N), ("eof", "pause"), ("resource", "0"), ("aspect_ratio", 1),
                     ("mlt_service", "color"), ("mlt_image_format", "rgba"), ("set.test_audio", 0)):
            self.prop(p, k, v)
        pl = ET.SubElement(self.root, "playlist", {"id": "background"})
        ET.SubElement(pl, "entry", {"producer": "black", "in": "0", "out": str(self.N - 1)})

    def playlist(self, name: str, kind: str) -> ET.Element:
        pid = self.uid("playlist")
        pl = ET.SubElement(self.root, "playlist", {"id": pid})
        self.prop(pl, f"shotcut:{kind}", 1)
        self.prop(pl, "shotcut:name", name)
        self.tracks.append((pid, kind, "audio" if kind == "video" else "video"))
        return pl

    @staticmethod
    def blank(pl: ET.Element, n: int) -> None:
        if n > 0:
            ET.SubElement(pl, "blank", {"length": str(n)})

    # ---------------------------------------------------------------- video pieces
    def _producer_for_piece(self, p: Piece, role: str) -> tuple[str, int, int]:
        """Create one producer element for a piece; returns (id, entry_in, entry_out)."""
        c = self.r.clips[p.clip_index]
        src_rel, off = self.media.source_for(c)
        pid = self.uid(f"{c.id}_{role}_")
        if p.kind == "hold":
            still = self.media.hold_still(c, src_rel, off, p.s0)
            el = ET.SubElement(self.root, "producer", {"id": pid, "in": "0", "out": str(p.length - 1)})
            for k, v in (("length", p.length), ("eof", "pause"), ("resource", self.rel(still)), ("ttl", 1),
                         ("aspect_ratio", 1), ("mlt_service", "qimage"), ("shotcut:caption", f"{c.id} 정지")):
                self.prop(el, k, v)
            e_in, e_out = 0, p.length - 1
            src_is_still = True
        else:
            local = p.s0 - off
            length = self.src_length(src_rel)
            if abs(c.speed - 1.0) < 1e-9:
                e_in = max(0, int(math.floor((local + EPS_PICK) * self.fps + 1e-9)))
                total = max(length, e_in + p.length)
                el = ET.SubElement(self.root, "producer", {"id": pid, "in": "0", "out": str(total - 1)})
                for k, v in (("length", total), ("eof", "pause"), ("resource", self.rel(src_rel)),
                             ("audio_index", -1), ("mlt_service", "avformat"), ("seekable", 1)):
                    self.prop(el, k, v)
            else:
                sp = c.speed
                e_in = max(0, int(math.floor((local + EPS_PICK) * self.fps / sp + 1e-9)))
                total = max(int(math.floor(length / sp)), e_in + p.length)
                res = self.rel(src_rel)
                el = ET.SubElement(self.root, "producer", {"id": pid, "in": "0", "out": str(total - 1)})
                for k, v in (("length", total), ("eof", "pause"), ("resource", f"{fmt(sp, 6)}:{res}"),
                             ("audio_index", -1), ("mlt_service", "timewarp"), ("shotcut:producer", "avformat"),
                             ("warp_speed", fmt(sp, 6)), ("warp_resource", res), ("warp_pitch", 0), ("seekable", 1)):
                    self.prop(el, k, v)
            if length and e_in + p.length > length + 1:
                self.dec["warnings"].append(f"클립 {c.id}: 소스 길이를 넘는 구간({e_in + p.length}>{length} 프레임)")
            e_out = e_in + p.length - 1
            self.prop(el, "shotcut:caption", c.id)
            src_is_still = False
        self.prop(el, "shortkit:clip_id", c.id)
        self.prop(el, "shortkit:piece", f"{p.kind}:{p.n0}-{p.n1}")
        self._clip_filters(el, c, p, role, e_in, e_out, off, src_is_still)
        return pid, e_in, e_out

    def _filter(self, parent: ET.Element, service: str, e_in: int, e_out: int, props: list[tuple[str, object]],
                shotcut: str | None = None) -> ET.Element:
        f = ET.SubElement(parent, "filter", {"id": self.uid("filter"), "in": str(e_in), "out": str(e_out)})
        self.prop(f, "mlt_service", service)
        if shotcut:
            self.prop(f, "shotcut:filter", shotcut)
        for k, v in props:
            self.prop(f, k, v)
        return f

    def _clip_filters(self, el: ET.Element, c: Clip, p: Piece, role: str, e_in: int, e_out: int, off: float,
                      still: bool) -> None:
        sw, sh = c.src_size
        cx, cy, cw, ch = crop_int(c)
        # 1. clean crop (SOURCE px). MLT applies it at the producer before every other filter.
        if (cx, cy, cw, ch) != (0, 0, sw, sh):
            self._filter(el, "crop", e_in, e_out, [("left", cx), ("top", cy), ("right", max(0, sw - cx - cw)),
                                                   ("bottom", max(0, sh - cy - ch)), ("center", 0),
                                                   ("use_profile", 0)], "cropSource")
        # 2. delogo, SOURCE px/time.  Under an affine filter melt hands producer filters the CROPPED
        #    source scaled to the profile height (measured with avfilter.showinfo on melt 7.22:
        #    1920x1000 crop in a 360x640 profile -> 1228x640), so the rect is cropped-source px * k.
        if role == "video":
            k = self.H / ch
            fw = int(math.floor(self.H * cw / ch))
            for d in c.delogo:
                win = self._delogo_window(c, p, d, e_in, e_out, off, still)
                if win is None:
                    continue
                x0 = max(1.0, min(d.x - cx, cw - 3.0))
                y0 = max(1.0, min(d.y - cy, ch - 3.0))
                x = int(max(1, min(round(x0 * k), fw - 3)))
                y = int(max(1, min(round(y0 * k), self.H - 3)))
                w = int(max(1, min(round(d.w * k), fw - 1 - x)))
                h = int(max(1, min(round(d.h * k), self.H - 1 - y)))
                self._filter(el, "avfilter.delogo", win[0], win[1],
                             [("av.x", x), ("av.y", y), ("av.w", w), ("av.h", h), ("av.show", 0),
                              ("shortkit:source_rect", f"{fmt(d.x)} {fmt(d.y)} {fmt(d.w)} {fmt(d.h)}"),
                              ("shortkit:frame_scale", fmt(k, 6)),
                              ("shortkit:reason", d.reason or "delogo")])
                self.dec.setdefault("delogo", []).append({
                    "clip": c.id, "source_rect": [d.x, d.y, d.w, d.h], "source_resolution": [sw, sh],
                    "mlt_rect": [x, y, w, h], "mlt_frame_resolution": [fw, self.H], "scale": round(k, 6),
                    "note": "melt 는 affine 아래 필터에 '자른 소스를 프로필 높이로 맞춘' 프레임을 줌 → 좌표에 배율 적용. "
                            "Shotcut 미리보기(축소 해상도)에서는 위치가 어긋나 보일 수 있고, 내보내기(전체 해상도)는 맞음"})
        # 3. placement / zoom (affine rect keyframes, canvas px) and 4. region mask
        if role == "video":
            rect_kf = self._rect_keyframes(c, p)
            self._filter(el, "affine", e_in, e_out,
                         [("background", "color:#00000000"), ("transition.fill", 1), ("transition.distort", 1),
                          ("transition.rect", rect_kf), ("transition.valign", "top"), ("transition.halign", "left"),
                          ("transition.threads", 0)], "affineSizePosition")
            rx, ry, rw, rh = region_int(c)
            self._filter(el, "qtcrop", e_in, e_out, [("rect", f"{rx} {ry} {rw} {rh} 1"), ("circle", 0),
                                                     ("color", "#00000000"), ("radius", 0)], "cropRectangle")
        else:  # blurred background: cover the whole canvas, gaussian blur
            s = max(self.W / cw, self.H / ch)
            w, h = cw * s, ch * s
            self._filter(el, "affine", e_in, e_out,
                         [("background", "color:#00000000"), ("transition.fill", 1), ("transition.distort", 1),
                          ("transition.rect", f"{fmt((self.W - w) / 2)} {fmt((self.H - h) / 2)} {fmt(w)} {fmt(h)} 1")],
                         "affineSizePosition")
            sigma = float(self.r.canvas["background"].get("blur_sigma") or 30)
            self._filter(el, "avfilter.gblur", e_in, e_out, [("av.sigma", fmt(sigma, 3))])

    def _delogo_window(self, c: Clip, p: Piece, d, e_in: int, e_out: int, off: float, still: bool):
        fps = self.fps
        if p.kind == "hold":
            s = p.s0
            if (d.start is None or s >= d.start) and (d.end is None or s <= d.end):
                return e_in, e_out
            return None
        # frames of the piece whose source time is inside [start, end]
        inside = []
        for k in range(p.length):
            s = source_time(c, p.n0 + k, fps)
            if (d.start is None or s >= d.start - EPS_PICK) and (d.end is None or s <= d.end + EPS_PICK):
                inside.append(k)
        if not inside:
            return None
        if inside[-1] - inside[0] + 1 != len(inside):
            self.dec["warnings"].append(f"클립 {c.id}: delogo 시간창이 끊어져 있어 하나의 구간으로 합침")
        return e_in + inside[0], e_in + inside[-1]

    def _rect_keyframes(self, c: Clip, p: Piece) -> str:
        """transition.rect animation: exact per-frame values while the zoom moves, native cubic
        easing (2 keyframes) when the zoom lies on the frame grid inside this piece."""
        fps = self.fps

        def val(n: int) -> str:
            x, y, w, h = canvas_rect(c, n, fps)
            return f"{fmt(x)} {fmt(y)} {fmt(w)} {fmt(h)} 1"

        z = c.zoom
        if z is None or abs(z.scale_to - z.scale_from) < 1e-9:
            return val(p.n0)
        zf0 = (c.out_start + z.start) * fps
        zf1 = (c.out_start + z.start + z.dur) * fps
        a0, a1 = p.n0, p.n1 - 1
        if zf1 <= a0 or zf0 >= a1 + 1:     # zoom does not move inside this piece
            return f"0={val(a0)};{a1 - a0}={val(a1)}" if a1 > a0 else val(a0)
        on_grid = abs(zf0 - round(zf0)) < 1e-6 and abs(zf1 - round(zf1)) < 1e-6
        if on_grid and a0 <= round(zf0) and round(zf1) <= a1 and native_ease_ok(z.ease) and z.dur > 0:
            k0, k1 = int(round(zf0)), int(round(zf1))
            parts = []
            if a0 < k0:
                parts.append(f"0={val(a0)}")
            parts.append(f"{k0 - a0}{_MLT_EASE[z.ease]}={val(k0)}")
            parts.append(f"{k1 - a0}={val(k1)}")
            if k1 < a1:
                parts.append(f"{a1 - a0}={val(a1)}")
            self.dec.setdefault("zoom_keyframes", []).append({"clip": c.id, "mode": "native_cubic_easing",
                                                              "ease": z.ease})
            return ";".join(parts)
        lo = max(a0, int(math.floor(zf0)))
        hi = min(a1, int(math.ceil(zf1)))
        ks = sorted({a0, a1, *range(lo, hi + 1)})
        self.dec.setdefault("zoom_keyframes", []).append({"clip": c.id, "mode": "per_frame", "ease": z.ease,
                                                          "why": "줌 시작/끝이 프레임 경계에 있지 않거나 조각이 줌 중간에서 나뉨"})
        return ";".join(f"{k - a0}={val(k)}" for k in ks)

    def _entry(self, pl: ET.Element, pid: str, e_in: int, e_out: int) -> None:
        ET.SubElement(pl, "entry", {"producer": pid, "in": str(e_in), "out": str(e_out)})

    def _pieces_track(self, pieces: list[Piece], role: str) -> tuple[str, int, int]:
        """A single piece -> its producer; several -> a sub-playlist (for transition tractors)."""
        if len(pieces) == 1:
            return self._producer_for_piece(pieces[0], role)
        sub = ET.Element("playlist", {"id": self.uid("xfade_pl")})
        for p in pieces:
            pid, a, b = self._producer_for_piece(p, role)
            self._entry(sub, pid, a, b)
        self.root.append(sub)
        n = sum(p.length for p in pieces)
        self.dec["warnings"].append("crossfade 구간 안에 정지/분할 경계가 있어 전환 트랙에 하위 재생목록을 사용 "
                                    "(melt 렌더는 정상, Shotcut 에서는 일반 전환으로 보이지 않을 수 있음)")
        return sub.get("id"), 0, n - 1

    def video_track(self, segs: list[Segment], role: str, name: str) -> None:
        # producers must be defined before the playlist that references them
        entries: list[tuple] = []
        for s in segs:
            if s.kind == "blank":
                entries.append(("blank", s.n1 - s.n0))
            elif s.kind == "piece":
                for p in s.pieces:
                    entries.append(("entry",) + self._producer_for_piece(p, role))
            else:
                n = s.n1 - s.n0
                a_id, a_in, a_out = self._pieces_track(s.a_pieces, role)
                b_id, b_in, b_out = self._pieces_track(s.b_pieces, role)
                tid = self.uid("transition_tractor")
                tr = ET.SubElement(self.root, "tractor", {"id": tid, "in": "0", "out": str(n - 1)})
                self.prop(tr, "shotcut:transition", "lumaMix")
                ET.SubElement(tr, "track", {"producer": a_id, "in": str(a_in), "out": str(a_out)})
                ET.SubElement(tr, "track", {"producer": b_id, "in": str(b_in), "out": str(b_out)})
                t1 = ET.SubElement(tr, "transition", {"id": self.uid("transition"), "out": str(n - 1)})
                for k, v in (("a_track", 0), ("b_track", 1), ("factory", "loader"), ("mlt_service", "luma"),
                             ("alpha_over", 1), ("fix_background_alpha", 1)):
                    self.prop(t1, k, v)
                t2 = ET.SubElement(tr, "transition", {"id": self.uid("transition"), "out": str(n - 1)})
                for k, v in (("a_track", 0), ("b_track", 1), ("start", -1), ("accepts_blanks", 1),
                             ("mlt_service", "mix")):
                    self.prop(t2, k, v)
                entries.append(("entry", tid, 0, n - 1))
                if role == "video":
                    c = self.r.clips[s.b_pieces[0].clip_index]
                    self.dec["crossfades"].append({"clip": c.id, "frames": [s.n0, s.n1],
                                                   "dur_s": c.transition_in.dur,
                                                   "on_frame_grid": abs(c.out_start * self.fps
                                                                        - round(c.out_start * self.fps)) < 1e-6})
        pl = self.playlist(name, "video")
        for e in entries:
            if e[0] == "blank":
                self.blank(pl, e[1])
            else:
                self._entry(pl, e[1], e[2], e[3])
        self.track_names.append({"track": name, "kind": "video", "items": sum(1 for e in entries if e[0] == "entry")})

    def background_track(self, segs: list[Segment]) -> None:
        bg = self.r.canvas.get("background") or {"type": "color", "color": "#000000"}
        if bg.get("type") == "blur_source":
            self.video_track(segs, "blurbg", "V1 배경(흐린 소스)")
            self.dec["notes"].append("배경 blur_source: 소스를 화면 가득 채워 avfilter.gblur 로 흐림(마스터는 1/8 축소 후 "
                                     "흐림·확대라 흐림 질감이 약간 다를 수 있음)")
            return
        pid = self.uid("bgcolor")
        p = ET.SubElement(self.root, "producer", {"id": pid, "in": "0", "out": str(self.N - 1)})
        for k, v in (("length", self.N), ("eof", "pause"), ("resource", mlt_color(bg.get("color") or "#000000")),
                     ("aspect_ratio", 1), ("mlt_service", "color"), ("mlt_image_format", "rgba"),
                     ("shotcut:caption", "배경색")):
            self.prop(p, k, v)
        pl = self.playlist("V1 배경", "video")
        self._entry(pl, pid, 0, self.N - 1)
        self.track_names.append({"track": "V1 배경", "kind": "video", "items": 1})

    def flash_track(self) -> None:
        runs = flash_runs(self.r)
        if not runs:
            return
        entries = []
        for fr in runs:
            c = self.r.clips[fr["clip_index"]]
            n = fr["n1"] - fr["n0"]
            pid = self.uid("flash")
            p = ET.SubElement(self.root, "producer", {"id": pid, "in": "0", "out": str(n - 1)})
            for k, v in (("length", n), ("eof", "pause"), ("resource", mlt_color(fr["color"])), ("aspect_ratio", 1),
                         ("mlt_service", "color"), ("mlt_image_format", "rgba"), ("shotcut:caption", f"플래시 {c.id}")):
                self.prop(p, k, v)
            kf = ";".join(f"{k}={fmt(a, 5)}" for k, a in enumerate(fr["alphas"]))
            self._filter(p, "brightness", 0, n - 1, [("level", 1), ("alpha", kf)], "brightnessOpacity")
            rx, ry, rw, rh = region_int(c)
            self._filter(p, "affine", 0, n - 1, [("background", "color:#00000000"), ("transition.fill", 1),
                                                 ("transition.distort", 1),
                                                 ("transition.rect", f"{rx} {ry} {rw} {rh} 1")], "affineSizePosition")
            entries.append((fr["n0"], fr["n1"], pid))
            self.dec["flashes"].append({"clip": c.id, "frames": [fr["n0"], fr["n1"]], "color": fr["color"],
                                        "shape": "alpha = 1 - |t - cut| / (dur/2), 영상 영역에만"})
        pl = self.playlist("V3 플래시", "video")
        cur = 0
        for n0, n1, pid in entries:
            if n0 < cur:
                self.dec["warnings"].append("플래시 구간이 겹쳐 뒤 플래시를 잘라냄")
                continue
            self.blank(pl, n0 - cur)
            self._entry(pl, pid, 0, n1 - n0 - 1)
            cur = n1
        self.track_names.append({"track": "V3 플래시", "kind": "video", "items": len(entries)})

    # ---------------------------------------------------------------- audio
    def _audio_producer(self, rel: str, caption: str, length: int, video_file: bool) -> str:
        pid = self.uid("audio")
        p = ET.SubElement(self.root, "producer", {"id": pid, "in": "0", "out": str(max(0, length - 1))})
        for k, v in (("length", max(1, length)), ("eof", "pause"), ("resource", self.rel(rel)),
                     ("mlt_service", "avformat"), ("seekable", 1), ("shotcut:caption", caption)):
            self.prop(p, k, v)
        if video_file:
            self.prop(p, "video_index", -1)
        return pid

    def _gain_filters(self, el: ET.Element, e_in: int, e_out: int, gain_db: float, fade_in: float, fade_out: float,
                      env_fn=None, fg_gain: list[float] | None = None, out_n0: int = 0) -> None:
        """volume filters: constant gain, optional envelope (dB of relative time), linear-amplitude fades.

        melt's volume filter ramps linearly from the previous frame's gain to this frame's gain over
        the frame's samples, so every animated value is the render's gain at the END of the frame."""
        n = e_out - e_in + 1
        T = n / self.fps
        end = [(k + 1) / self.fps for k in range(n)]
        self._filter(el, "volume", e_in, e_out, [("level", fmt(gain_db, 3))], "audioGain")
        if env_fn is not None:
            vals = [max(SILENCE_DB_FLOOR, float(env_fn(t))) for t in end]
            self._filter(el, "volume", e_in, e_out, [("level", self._compact(vals)),
                                                     ("shortkit:role", "envelope(ducking/silence)")], "audioGain")
        if fg_gain is not None:
            K = len(fg_gain)

            def kv(i):
                a = fg_gain[min(K - 1, max(0, out_n0 + i))]
                b = fg_gain[min(K - 1, max(0, out_n0 + i + 1))]
                return db((a + b) / 2)
            vals = [kv(i) for i in range(n)]
            if min(vals) < -0.05:
                self._filter(el, "volume", e_in, e_out, [("level", self._compact(vals)),
                                                         ("shortkit:role", "master foreground safety limiter")],
                             "audioGain")
        if fade_in > 0:
            kmax = min(n - 1, int(math.ceil(fade_in * self.fps)))
            vals = [(k, db(min(1.0, end[k] / fade_in))) for k in range(0, kmax + 1)]
            self._filter(el, "volume", e_in, e_out, [("level", self._kf(vals)),
                                                     ("shotcut:animIn", int(round(fade_in * self.fps)))], "fadeInVolume")
        if fade_out > 0:
            k0 = max(0, int(math.floor((T - fade_out) * self.fps)) - 1)
            vals = [(k, db(max(0.0, min(1.0, (T - end[k]) / fade_out)))) for k in range(k0, n)]
            if k0 > 0:
                vals.insert(0, (0, 0.0))
            self._filter(el, "volume", e_in, e_out, [("level", self._kf(vals)),
                                                     ("shotcut:animOut", int(round(fade_out * self.fps)))],
                         "fadeOutVolume")

    @staticmethod
    def _kf(vals: list[tuple[int, float]]) -> str:
        return ";".join(f"{k}={fmt(v, 3)}" for k, v in vals)

    def _compact(self, per_frame: list[float]) -> str:
        """Per-frame dB list -> keyframes, dropping points that linear interpolation reproduces."""
        pts = list(enumerate(per_frame))
        if len(pts) == 1:
            return self._kf(pts)
        keep = [pts[0]]
        for i in range(1, len(pts) - 1):
            (k0, v0), (k1, v1), (k2, v2) = keep[-1], pts[i], pts[i + 1]
            if abs(v0 + (v2 - v0) * (k1 - k0) / (k2 - k0) - v1) > 0.01:
                keep.append(pts[i])
        if len(pts) > 1:
            keep.append(pts[-1])
        return self._kf(keep)

    def bgm_track(self) -> None:
        b = self.r.audio.bgm
        if b is None:
            self.dec["audio"]["bgm"] = {"status": "없음(계획에 BGM 없음)"}
            return
        if not b.path:
            self.dec["audio"]["bgm"] = {"status": "못 잼", "why": "BGM 파일 미식별(IR bgm.path=None) → 트랙에 넣지 않음"}
            return
        src, offset = b.path, b.section_start_s
        if abs(b.tempo_ratio - 1.0) > 1e-9:
            src = self.media.tempo_bgm(b.path, b.tempo_ratio, self.r.audio.sample_rate)
            offset = b.section_start_s / b.tempo_ratio
        length = self.src_length(src)
        e_in = int(round(offset * self.fps))
        n = self.N
        if length and e_in + n > length:
            n = max(1, length - e_in)
            self.dec["warnings"].append(f"BGM 파일이 짧아 {n}프레임만 배치(마스터는 남은 부분 무음)")
        e_out = e_in + n - 1
        pid = self._audio_producer(src, f"BGM {Path(b.path).name}", max(length, e_out + 1), False)
        p = self.root.find(f"producer[@id='{pid}']")
        from .audio import envelope_db_at

        env_fn = (lambda t, _e=b.envelope: envelope_db_at(_e, t)) if b.envelope else None
        self._gain_filters(p, e_in, e_out, b.gain_db, b.fade_in_s, min(b.fade_out_s, self.r.duration), env_fn)
        pl = self.playlist("A1 BGM", "audio")
        self._entry(pl, pid, e_in, e_out)
        self.track_names.append({"track": "A1 BGM", "kind": "audio", "items": 1})
        self.dec["audio"]["bgm"] = {
            "status": "있음", "file": self.rel(src), "section_start_s": b.section_start_s, "tempo_ratio": b.tempo_ratio,
            "entry_in_frame": e_in, "quantization_s": round(abs(e_in / self.fps - offset), 4),
            "gain_db": b.gain_db, "fade_in_s": b.fade_in_s, "fade_out_s": b.fade_out_s,
            "envelope_points": len(b.envelope), "duck_ranges": b.duck_ranges, "silences": b.silences,
            "note": "시작점은 프레임(1/fps) 단위로 맞춰짐; 덕킹/정적 envelope 는 volume level 키프레임"}

    def _lanes(self, items: list[tuple[int, int, object]]) -> list[list[tuple[int, int, object]]]:
        lanes: list[list] = []
        for it in sorted(items, key=lambda x: x[0]):
            for ln in lanes:
                if ln[-1][1] <= it[0]:
                    ln.append(it)
                    break
            else:
                lanes.append([it])
        return lanes

    def sfx_tracks(self) -> None:
        items = []
        skipped = []
        for s in self.r.audio.sfx:
            if not s.path:
                skipped.append({"id": s.id, "type": s.type, "map_status": s.map_status})
                continue
            length = self.src_length(s.path)
            n0 = int(round(s.t * self.fps))
            n = max(1, min(length or 1, self.N - n0))
            if n0 >= self.N:
                skipped.append({"id": s.id, "type": s.type, "why": "영상 끝 이후"})
                continue
            items.append((n0, n0 + n, s, length))
        lanes = self._lanes([(a, b, (s, ln)) for a, b, s, ln in items])
        for li, lane in enumerate(lanes or []):
            prods = []
            for n0, n1, (s, length) in lane:
                pid = self._audio_producer(s.path, f"효과음 {s.type} ({s.id})", max(length, n1 - n0), False)
                p = self.root.find(f"producer[@id='{pid}']")
                self._gain_filters(p, 0, n1 - n0 - 1, s.gain_db, 0.0, 0.0, fg_gain=self.fg_gain, out_n0=n0)
                self.prop(p, "shortkit:event", f"{s.event_t:.3f}s {s.event_desc}")
                prods.append((n0, n1, pid))
            name = "A2 효과음" if li == 0 else f"A2 효과음 {li + 1}"
            pl = self.playlist(name, "audio")
            cur = 0
            for n0, n1, pid in prods:
                self.blank(pl, n0 - cur)
                self._entry(pl, pid, 0, n1 - n0 - 1)
                cur = n1
            self.track_names.append({"track": name, "kind": "audio", "items": len(prods)})
        self.dec["audio"]["sfx"] = {"placed": len(items), "tracks": len(lanes), "skipped_unresolved": skipped,
                                    "note": "효과음 위치는 프레임 단위(1/fps)로 맞춰짐"}

    def original_tracks(self) -> None:
        items = []
        for o in self.r.audio.originals:
            n0 = int(round(o.out_start * self.fps))
            n = max(1, int(round((o.out_end - o.out_start) * self.fps)))
            items.append((n0, min(self.N, n0 + n), o))
        lanes = self._lanes(items)
        for li, lane in enumerate(lanes):
            prods = []
            for n0, n1, o in lane:
                if abs(o.speed - 1.0) > 1e-9:
                    src = self.media.tempo_original(o, self.r.audio.sample_rate)
                    e_in = 0
                    video_file = False
                else:
                    src = o.path
                    e_in = int(round(o.src_start * self.fps))
                    info = self.media.info(o.path)
                    video_file = bool(info and info.width)
                length = self.src_length(src)
                e_out = e_in + (n1 - n0) - 1
                pid = self._audio_producer(src, f"원본 소리 {o.clip_id} ({o.stem})", max(length, e_out + 1), video_file)
                p = self.root.find(f"producer[@id='{pid}']")
                self._gain_filters(p, e_in, e_out, o.gain_db, o.fade_s, o.fade_s, fg_gain=self.fg_gain, out_n0=n0)
                self.prop(p, "shortkit:reason", o.reason or "kept original")
                prods.append((n0, n1, pid, e_in, e_out))
            name = "A3 원본 소리" if li == 0 else f"A3 원본 소리 {li + 1}"
            pl = self.playlist(name, "audio")
            cur = 0
            for n0, n1, pid, e_in, e_out in prods:
                self.blank(pl, n0 - cur)
                self._entry(pl, pid, e_in, e_out)
                cur = n1
            self.track_names.append({"track": name, "kind": "audio", "items": len(prods)})
        self.dec["audio"]["originals"] = {"clips": len(items), "tracks": len(lanes),
                                          "stems": sorted({o.stem for _, _, o in items})}

    # ---------------------------------------------------------------- tractor
    def tractor(self, caption_file: str | None, gain_db: float | None, limiter_db: float | None = None) -> None:
        tr = ET.SubElement(self.root, "tractor", {"id": "tractor0", "title": f"shortkit {self.r.episode_id}",
                                                   "in": "0", "out": str(self.N - 1)})
        self.prop(tr, "shotcut", 1)
        self.prop(tr, "shotcut:projectAudioChannels", 2)
        self.prop(tr, "shotcut:projectFolder", 1)
        self.prop(tr, "shortkit:episode_id", self.r.episode_id)
        self.prop(tr, "shortkit:preset_id", self.r.preset_id)
        ET.SubElement(tr, "track", {"producer": "background"})
        for pid, kind, hide in self.tracks:
            ET.SubElement(tr, "track", {"producer": pid, "hide": hide})
        for i, (pid, kind, _) in enumerate(self.tracks, start=1):
            t = ET.SubElement(tr, "transition", {"id": self.uid("transition")})
            for k, v in (("a_track", 0), ("b_track", i), ("mlt_service", "mix"), ("always_active", 1), ("sum", 1)):
                self.prop(t, k, v)
        for i, (pid, kind, _) in enumerate(self.tracks, start=1):
            if kind != "video":
                continue
            t = ET.SubElement(tr, "transition", {"id": self.uid("transition")})
            for k, v in (("a_track", 0), ("b_track", i), ("version", "0.1"), ("mlt_service", "qtblend"),
                         ("threads", 0), ("always_active", 1)):
                self.prop(t, k, v)
        if caption_file:
            props = [("av.filename", caption_file)]
            if self.r.fonts_dir and paths.absp(self.r.fonts_dir).is_dir():
                props.append(("av.fontsdir", self.rel(self.r.fonts_dir)))
            f = ET.SubElement(tr, "filter", {"id": self.uid("filter")})
            self.prop(f, "mlt_service", "avfilter.subtitles")
            for k, v in props:
                self.prop(f, k, v)
            self.prop(f, "shortkit:role", "captions+decorations (one ASS layer, same file as the master)")
        if gain_db is not None:
            f = ET.SubElement(tr, "filter", {"id": self.uid("filter")})
            self.prop(f, "mlt_service", "volume")
            self.prop(f, "level", fmt(gain_db, 3))
            self.prop(f, "shotcut:filter", "audioGain")
            self.prop(f, "shortkit:role", "loudness normalization gain (master render)")
        if limiter_db is not None:
            f = ET.SubElement(tr, "filter", {"id": self.uid("filter")})
            for k, v in (("mlt_service", "avfilter.alimiter"), ("av.limit", fmt(10 ** (limiter_db / 20.0), 5)),
                         ("av.attack", 5), ("av.release", 50), ("av.level", 0), ("av.level_in", 1),
                         ("av.level_out", 1),
                         ("shortkit:role", "peak limiter standing in for the master's true-peak limiter")):
                self.prop(f, k, v)

    def tostring(self) -> str:
        # tractor must come last (melt plays the last service); main_bin first (Shotcut)
        ET.indent(self.root, space="  ")
        return '<?xml version="1.0" encoding="utf-8"?>\n' + ET.tostring(self.root, encoding="unicode") + "\n"


# ============================================================================ loudness
def master_foreground_gain(r: ResolvedEdit, decisions: dict) -> list[float] | None:
    """Per-output-frame gain the master's stem-aware safety limiter applied to the foreground
    (kept originals + SFX), READ from the master's own build stems:

        k[f] = <fg_out, fg_pre> / <fg_pre, fg_pre> / (norm_gain * final_trim)   over frame f

    fg_out = build/stems/{originals,sfx}.wav written by render.py (after gain + limiter + trim),
    fg_pre = the same stems rebuilt from the IR before normalization (gain_db, fades, placement).
    Returns None when the master used no foreground limiting or its stems are missing."""
    import numpy as np

    from ..util.media import read_audio

    a = ((load_render_report(r) or {}).get("audio") or {})
    red = a.get("fg_limiter_max_reduction_db")
    if red is None or float(red) <= 0.05:
        return None
    build = paths.absp(f"episodes/{r.episode_id}/build/stems")
    files = [build / "originals.wav", build / "sfx.wav"]
    if not all(f.is_file() for f in files):
        decisions["foreground_limiter"] = {"status": "못 잼", "master_max_reduction_db": red,
                                           "why": "마스터가 효과음/원본 소리에 안전 리미터를 걸었지만 build/stems 가 없어 "
                                                  "프레임별 감쇠를 읽지 못함 → MLT 에서는 그 구간이 더 크게 들림"}
        return None
    sr = r.audio.sample_rate
    n = int(round(r.duration * sr))
    fps = fps_of(r)
    N = n_frames(r)

    def fit(x):
        x = x[:n]
        return np.pad(x, ((0, n - len(x)), (0, 0))) if len(x) < n else x

    fo = fit(read_audio(files[0], sr=sr, mono=False)) + fit(read_audio(files[1], sr=sr, mono=False))
    fp = np.zeros((n, 2), np.float32)
    for o in r.audio.originals:
        if abs(o.speed - 1.0) > 1e-9:
            decisions["foreground_limiter"] = {"status": "못 잼", "why": "배속 원본 소리의 사전 스템 재구성 미구현"}
            return None
        x = read_audio(paths.absp(o.path), sr=sr, mono=False, start=o.src_start, duration=o.src_end - o.src_start)
        m = int(round((o.out_end - o.out_start) * sr))
        x = np.pad(x, ((0, max(0, m - len(x))), (0, 0)))[:m]
        g = np.ones(m, np.float32) * 10 ** (o.gain_db / 20)
        fl = int(round(o.fade_s * sr))
        if fl > 0:
            g[:fl] *= np.linspace(0.0, 1.0, fl, endpoint=False, dtype=np.float32)
            g[max(0, m - fl):] *= np.linspace(1.0, 0.0, min(fl, m), dtype=np.float32)
        s0 = int(round(o.out_start * sr))
        e0 = min(n, s0 + m)
        fp[s0:e0] += (x * g[:, None])[: e0 - s0]
    for sp in r.audio.sfx:
        if not sp.path:
            continue
        x = read_audio(paths.absp(sp.path), sr=sr, mono=False) * 10 ** (sp.gain_db / 20)
        s0 = int(round(sp.t * sr))
        e0 = min(n, s0 + len(x))
        if e0 > s0:
            fp[s0:e0] += x[: e0 - s0]
    g0 = 10 ** ((float(a.get("norm_gain_db") or 0.0) + float(a.get("final_trim_db") or 0.0)) / 20)
    k = []
    for f in range(N):
        s0, s1 = int(round(f * sr / fps)), min(n, int(round((f + 1) * sr / fps)))
        pp = float((fp[s0:s1] ** 2).sum())
        if s1 <= s0 or pp < 1e-10:
            k.append(None)
            continue
        k.append(float(min(1.0, max(1e-6, float((fo[s0:s1] * fp[s0:s1]).sum()) / pp / g0))))
    last = 1.0
    for i, v in enumerate(k):      # frames without foreground content keep the previous value
        if v is None:
            k[i] = last
        else:
            last = v
    decisions["foreground_limiter"] = {
        "status": "있음", "master_max_reduction_db": red,
        "measured_max_reduction_db": round(-20 * math.log10(min(k)), 2),
        "source": f"episodes/{r.episode_id}/build/stems/{{originals,sfx}}.wav",
        "how": "마스터 스템과 IR 로 다시 만든 정규화 전 스템의 프레임별 비율 → 효과음/원본 소리 클립의 volume 키프레임",
        "note": "마스터 리미터는 5 ms 블록 단위, MLT 키프레임은 프레임(1/fps) 단위라 피크 순간은 약간 다를 수 있음"}
    return k


def loudness_gain(r: ResolvedEdit, project_file: Path, decisions: dict, compute: bool = True) -> float | None:
    """Master normalization gain: render_report.json if present, else melt pre-pass (no gain)."""
    rep = load_render_report(r)
    a = (rep or {}).get("audio") or {}
    if a.get("norm_gain_db") is not None:
        g = float(a["norm_gain_db"]) + float(a.get("final_trim_db") or 0.0)
        red = float(a.get("limiter_max_reduction_db") or 0.0)
        ceiling = a.get("true_peak_ceiling_db")
        if ceiling is None:
            ceiling = r.audio.true_peak_db - 0.5
        decisions["limiter"] = ({"ceiling_dbfs": round(float(ceiling), 3), "master_max_reduction_db": red,
                                 "service": "avfilter.alimiter (attack 5 ms, release 50 ms, auto level off)",
                                 "note": "마스터는 4배 오버샘플 true-peak 리미터, MLT 는 ffmpeg alimiter(샘플 피크) → "
                                         "피크 부근 레벨이 조금 다를 수 있음"}
                                if red > 0.05 else None)
        decisions["loudness"] = {
            "gain_db": round(g, 3), "source": f"episodes/{r.episode_id}/build/render_report.json",
            "norm_gain_db": a["norm_gain_db"], "final_trim_db": a.get("final_trim_db"),
            "master_limiter_max_reduction_db": a.get("limiter_max_reduction_db"),
            "note": "마스터의 정규화 이득 + 최종 트림을 타임라인 volume 필터로 적용"}
        return g
    if not compute:
        decisions["loudness"] = {"gain_db": None, "source": "unmeasured", "status": "못 잼",
                                 "why": "render_report.json 없음, 사전 측정 생략"}
        return None
    from .verify_project import melt_audio_lufs

    mp4 = paths.absp(r.output_path)
    try:
        meas = melt_audio_lufs(project_file, mp4 if mp4.is_file() else None)
    except Exception as e:  # melt missing / failed: never invent a gain
        from .verify_project import scrub

        decisions["loudness"] = {"gain_db": None, "source": "unmeasured", "status": "못 잼",
                                 "why": f"melt 사전 측정 실패: {type(e).__name__}: {scrub(str(e))[:200]}"}
        return None
    li = meas.get("integrated_lufs")
    if li is None or li < -69:
        decisions["loudness"] = {"gain_db": None, "source": "unmeasured", "status": "못 잼",
                                 "why": "melt 사전 측정 결과가 무음"}
        return None
    if meas.get("rms_ratio_db") is not None:
        g, how = float(meas["rms_ratio_db"]), "master_mp4_rms_ratio"
    else:
        g, how = r.audio.target_lufs - li, "target_lufs"
    tp = meas.get("true_peak_db")
    ceiling = r.audio.true_peak_db - 0.5
    master_tp = None
    if mp4.is_file():
        from ..util.media import lufs

        master_tp = lufs(mp4).get("true_peak_db")
    # a limiter only when the master itself stayed under the ceiling (it was limited) or there is no master
    need = tp is not None and tp + g > ceiling and (master_tp is None or master_tp <= ceiling + 1.0)
    decisions["limiter"] = ({"ceiling_dbfs": round(ceiling, 3), "prepass_true_peak_after_gain_db": round(tp + g, 2),
                             "master_true_peak_db": master_tp,
                             "service": "avfilter.alimiter (attack 5 ms, release 50 ms, auto level off)",
                             "note": "이득 적용 후 피크가 한도를 넘어 리미터를 넣음(마스터 리미터와 알고리즘 다름)"}
                            if need else None)
    decisions["loudness"] = {"gain_db": round(g, 3), "source": "computed_melt_prepass", "pre_gain_lufs": li,
                             "target_from": how, "target_lufs": r.audio.target_lufs,
                             "note": "render_report.json 이 없어 MLT 소리를 melt 로 한 번 렌더해 계산: 마스터 MP4 가 있으면 "
                                     "파일 전체 RMS 비(같은 믹스의 두 렌더 사이 이득), 없으면 목표 LUFS - 측정 LUFS"}
    return g


# ============================================================================ entry points
def export_with_decisions(resolved: ResolvedEdit, out_dir: Path, *, compute_loudness: bool = True) -> tuple[Path, dict]:
    r = resolved
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    dec: dict = {"format": "mlt", "file": f"{r.episode_id}.mlt", "created_at": now_iso(), "warnings": [], "notes": [],
                 "prerendered": [], "crossfades": [], "flashes": [], "audio": {}, "semantics": {
                     "source": "shortkit.edit.render / shortkit.edit.resolve (src_time_at, src_to_region, ease)",
                     "frame_rule": "n 번째 프레임 = n/fps 초, 클립은 out_start-1e-6 <= t < out_end-1e-6 에서 보임"}}
    caps = write_caption_files(r, out_dir)
    dec["captions"] = caps
    b = MltBuilder(r, out_dir, dec)
    b.profile()
    b.background_black()
    segs = build_segments(r, dec["warnings"])
    b.background_track(segs)
    b.video_track(segs, "video", "V2 영상")
    b.flash_track()
    b.fg_gain = master_foreground_gain(r, dec)
    b.bgm_track()
    b.sfx_tracks()
    b.original_tracks()
    dec["tracks"] = b.track_names
    dec["coordinates"] = ("affine/qtcrop/flash rect 은 캔버스 px (profile 해상도 기준), crop 은 SOURCE px, "
                          "delogo 는 mlt_frame_resolution 기준 px")
    dec["profile"] = {"width": b.W, "height": b.H, "fps": b.fps, "frames": b.N, "display_aspect": "9:16"
                      if b.W * 16 == b.H * 9 else f"{b.W}:{b.H}"}
    out = out_dir / f"{r.episode_id}.mlt"
    # write once without the loudness gain (needed for a melt pre-pass), then with it
    b.tractor(caps["ass"], None)
    out.write_text(b.tostring(), encoding="utf-8")
    gain = loudness_gain(r, out, dec, compute=compute_loudness)
    b.root.remove(b.root.find("tractor[@id='tractor0']"))
    lim = dec.get("limiter")
    b.tractor(caps["ass"], gain, lim["ceiling_dbfs"] if lim else None)
    out.write_text(b.tostring(), encoding="utf-8")
    dec["editable"] = [
        "클립 순서·길이·트림(V2 영상 트랙의 각 조각)", "클립별 위치/크기/줌(Size, Position & Rotate = affine 키프레임)",
        "원본 정리 crop(Crop: Source)·delogo(avfilter.delogo) 수치", "영상 영역 마스크(Crop: Rectangle = qtcrop)",
        "crossfade 전환(luma+mix 전환 트랙)", "플래시(V3 트랙의 색 클립, Opacity 키프레임)",
        "BGM 시작점·이득·덕킹 envelope·페이드(volume 필터)", "효과음 위치·이득(A2)", "원본 소리 구간·이득·페이드(A3)",
        "전체 음량 이득(타임라인 volume 필터)"]
    dec["baked"] = [
        "자막·장식 전체가 ASS 한 파일(captions.ass)로 한 레이어에 그려짐 → 텍스트는 captions.ass 를 Aegisub/텍스트 "
        "편집기로 고쳐야 하며 NLE 의 개별 텍스트 클립이 아님",
        "inpaint 로 지운 소스는 미리 렌더된 중간 파일(warehouse/cache/clean)을 소스로 사용",
        "정지(freeze) 프레임은 이미지 파일(media/*_hold_*.png)",
        *(["BGM 속도 변경은 미리 렌더된 wav(media/bgm_tempo_*.wav)"] if r.audio.bgm and r.audio.bgm.path
          and abs(r.audio.bgm.tempo_ratio - 1) > 1e-9 else []),
        *(["영역 흐림(blur)은 미리 렌더된 중간 영상(media/*_blur_*.mp4)"] if any(c.blur for c in r.clips) else [])]
    merge_decisions(out_dir, "mlt", dec)
    return out, dec


def export(resolved: ResolvedEdit, out_dir: Path) -> Path:
    """Contract API: write episodes/<id>/project/<id>.mlt (+ captions.ass/.srt, media/, decisions)."""
    return export_with_decisions(resolved, out_dir)[0]
