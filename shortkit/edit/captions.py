"""Caption typography: exact font resolution, font metrics, line layout and the ONE ASS file.

Coordinates are canvas px (the ASS script has PlayResX/Y = canvas size, so script px == video
px).  Sizes follow one convention everywhere in shortkit:

    size_px      = font em size in canvas px (what PIL ``ImageFont.truetype(size=...)`` uses)
    line pitch   = size_px * line_spacing          (baseline-to-baseline distance)
    line box     = [top, top + asc + desc] with asc/desc from OS/2 usWinAscent/usWinDescent

libass sizes a font so that (usWinAscent + usWinDescent) == ASS ``Fontsize`` (FreeType
REAL_DIM request after libass' GDI-compatible metric override), hence
``ass_fontsize = size_px * (winAscent + winDescent) / unitsPerEm``.  Every line is its own
event with an exact ``\\pos`` (``\\an5`` = centre of the line box), so line spacing is exact
and independent of libass' own line layout.

Font rule (user: never guess): the requested family/full name must match the resolved face
exactly.  ``fc-match`` substitutes silently (e.g. "Noto Sans CJK KR Bold" -> DejaVu Sans), so
it is never trusted; a non-matching name is an error.

Name written into the ASS style (``FaceMetrics.ass_name``) -- libass 0.17.1 ``ass_fontselect.c``,
confirmed per face with the ``fontselect`` log (tests/edit/test_font_libass_names.py):

* libass indexes a face by its Windows-platform (3) family names (name id 1) and full names
  (id 4) plus its PostScript name (id 6), and ``matches_full_or_postscript_name`` uses the
  PostScript name ONLY for PostScript/CFF outlines and the full name ONLY for TrueType outlines
  (the GDI rule).  So "BlackHanSans-Regular" (TrueType) falls back to DejaVu/WenQuanYi while
  "Black Han Sans Regular" matches; "Noto Sans CJK KR Bold" (CFF) falls back while
  "NotoSansCJKkr-Bold" matches.
* A family-name match picks the member closest in weight, so a shared family such as
  "NanumGothic" or "Noto Sans CJK KR" selects another weight -> family names are only a last
  resort, accepted when the libass probe proves they select this very face.
* => ``ass_name`` = PostScript name for CFF faces, Windows full name for TrueType faces.
  :func:`probe_ass_names` asks libass itself (the resolver uses it) and falls back to other
  names of the SAME face only when libass selects exactly that face with them.

Weight: libass reads the style ``Bold`` field as a boolean (``style->Bold = !!style->Bold``:
400 and 900 both request weight 700) and emboldens synthetically when the requested weight
exceeds the face's ``usWeightClass`` + 150.  ``style_line`` therefore writes ``-1`` (700) only
for faces of weight >= 550 and ``0`` (400) otherwise; :func:`verify_libass_fonts` rejects any
synthetic emboldening it can see in the log.
"""
from __future__ import annotations

import math
import os
import re
import shutil
import struct
import subprocess
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from .. import paths

ASS_FORBIDDEN = re.compile(r"[{}\\]")


class FontError(RuntimeError):
    pass


# ----------------------------------------------------------------------------- sfnt parsing
@dataclass
class FaceMetrics:
    path: str                  # runtime absolute path (never stored)
    index: int
    names: list[str]           # family (1,16), full (4), postscript (6), "family style"
    family: str
    style: str
    units_per_em: int
    win_ascent: int
    win_descent: int
    hhea_ascent: int
    hhea_descent: int
    weight: int
    postscript: str | None = None   # name id 6
    cff: bool = False               # PostScript/CFF outlines ('CFF ' / 'CFF2' table) vs TrueType ('glyf')
    win_fullnames: list[str] = field(default_factory=list)   # platform 3 name id 4 (en-US first)
    win_families: list[str] = field(default_factory=list)    # platform 3 name id 1 (en-US first)

    @property
    def ass_name(self) -> str:
        """Name written into ASS styles (see module doc): libass matches the PostScript name of CFF
        faces and the Windows full name of TrueType faces; everything else may fall back silently."""
        cands = self.libass_name_candidates
        return cands[0] if cands else (self.postscript or (self.names[0] if self.names else self.family))

    @property
    def libass_name_candidates(self) -> list[str]:
        """Names libass can resolve to this face, best first: the GDI-rule name (PostScript for CFF,
        Windows full name for TrueType), then the other name kind, then Windows family names (these
        are shared by every weight of a family, so :func:`probe_ass_names` must prove them)."""
        ps = [self.postscript] if self.postscript else []
        first = ps + self.win_fullnames if self.cff else self.win_fullnames + ps
        out: list[str] = []
        for n in first + self.win_families:
            if n and not re.search(r"[,{}\\\r\n]", n) and all(_norm(n) != _norm(o) for o in out):
                out.append(n)
        return out

    @property
    def win_sum(self) -> int:
        s = self.win_ascent + self.win_descent
        return s if s > 0 else (self.hhea_ascent - self.hhea_descent)

    def ass_fontsize(self, size_px: float) -> float:
        return size_px * self.win_sum / self.units_per_em

    def asc_px(self, size_px: float) -> float:
        a = self.win_ascent if self.win_ascent + self.win_descent > 0 else self.hhea_ascent
        return size_px * a / self.units_per_em

    def desc_px(self, size_px: float) -> float:
        d = self.win_descent if self.win_ascent + self.win_descent > 0 else -self.hhea_descent
        return size_px * d / self.units_per_em


def _u16(b, o):
    return struct.unpack_from(">H", b, o)[0]


def _i16(b, o):
    return struct.unpack_from(">h", b, o)[0]


def _u32(b, o):
    return struct.unpack_from(">I", b, o)[0]


def _face_offsets(data: bytes) -> list[int]:
    if data[:4] == b"ttcf":
        n = _u32(data, 8)
        return [_u32(data, 12 + 4 * i) for i in range(n)]
    return [0]


def _tables(data: bytes, off: int) -> dict[str, tuple[int, int]]:
    num = _u16(data, off + 4)
    out = {}
    for i in range(num):
        rec = off + 12 + 16 * i
        tag = data[rec:rec + 4].decode("latin-1")
        out[tag] = (_u32(data, rec + 8), _u32(data, rec + 12))
    return out


def _names(data: bytes, off: int, length: int) -> dict[int, list[str]]:
    count = _u16(data, off + 2)
    str_off = off + _u16(data, off + 4)
    res: dict[int, list[str]] = {}
    for i in range(count):
        r = off + 6 + 12 * i
        pid, eid, lid, nid, ln, so = (_u16(data, r), _u16(data, r + 2), _u16(data, r + 4), _u16(data, r + 6),
                                     _u16(data, r + 8), _u16(data, r + 10))
        if nid not in (1, 2, 4, 6, 16, 17):
            continue
        raw = data[str_off + so:str_off + so + ln]
        try:
            if pid in (0, 3):
                s = raw.decode("utf-16-be")
            elif pid == 1 and eid == 0:
                s = raw.decode("mac_roman")
            else:
                continue
        except UnicodeDecodeError:
            continue
        s = s.strip("\x00").strip()
        if s and s not in res.setdefault(nid, []):
            res[nid].append(s)
    return res


def _win_names(data: bytes, off: int, length: int) -> dict[int, list[str]]:
    """Windows-platform (3) names -- the only ones libass indexes (``get_font_info``) --
    en-US (0x409) first, then the other languages in table order."""
    count = _u16(data, off + 2)
    str_off = off + _u16(data, off + 4)
    rows: list[tuple[int, int, int, str]] = []
    for i in range(count):
        r = off + 6 + 12 * i
        pid, lid, nid, ln, so = (_u16(data, r), _u16(data, r + 4), _u16(data, r + 6), _u16(data, r + 8),
                                 _u16(data, r + 10))
        if pid != 3 or nid not in (1, 4):
            continue
        try:
            s = data[str_off + so:str_off + so + ln].decode("utf-16-be").strip("\x00").strip()
        except UnicodeDecodeError:
            continue
        if s:
            rows.append((0 if lid == 0x409 else 1, i, nid, s))
    res: dict[int, list[str]] = {}
    for _, _, nid, s in sorted(rows):
        if s not in res.setdefault(nid, []):
            res[nid].append(s)
    return res


@lru_cache(maxsize=64)
def read_faces(path: str) -> tuple[FaceMetrics, ...]:
    """All faces of a TTF/OTF/TTC with names and the metrics libass uses."""
    data = Path(path).read_bytes()
    faces = []
    for idx, off in enumerate(_face_offsets(data)):
        t = _tables(data, off)
        if "head" not in t or "name" not in t:
            continue
        upem = _u16(data, t["head"][0] + 18)
        nm = _names(data, *t["name"])
        wa = wd = 0
        weight = 400
        if "OS/2" in t:
            o = t["OS/2"][0]
            weight = _u16(data, o + 4)
            if t["OS/2"][1] >= 78:
                wa = _i16(data, o + 74)
                wd = _i16(data, o + 76)
        ha = hd = 0
        if "hhea" in t:
            h = t["hhea"][0]
            ha, hd = _i16(data, h + 4), _i16(data, h + 6)
        fams = nm.get(16, []) + nm.get(1, [])
        styles = nm.get(17, []) + nm.get(2, [])
        names = list(dict.fromkeys(nm.get(1, []) + nm.get(16, []) + nm.get(4, []) + nm.get(6, [])))
        for f in nm.get(16, []) or nm.get(1, []):
            for s in nm.get(17, []) or nm.get(2, []):
                names.append(f"{f} {s}")
        wn = _win_names(data, *t["name"])
        faces.append(FaceMetrics(path=str(path), index=idx, names=list(dict.fromkeys(names)),
                                 family=(fams or [Path(path).stem])[0], style=(styles or ["Regular"])[0],
                                 units_per_em=upem or 1000, win_ascent=wa, win_descent=wd, hhea_ascent=ha,
                                 hhea_descent=hd, weight=weight,
                                 postscript=(nm.get(6) or [None])[0],
                                 cff=("CFF " in t or "CFF2" in t),
                                 win_fullnames=wn.get(4, []), win_families=wn.get(1, [])))
    return tuple(faces)


def _norm(s: str) -> str:
    return "".join(str(s).split()).casefold()


def face_by_name(path: str | Path, name: str) -> FaceMetrics | None:
    for f in read_faces(str(path)):
        if any(_norm(n) == _norm(name) for n in f.names):
            return f
    return None


# ----------------------------------------------------------------------------- font resolution
@dataclass
class ResolvedFont:
    name: str
    face: FaceMetrics
    how: str                     # font_file | shortkit.fonts | font_dirs | fontconfig
    libass_name: str | None = None   # name proven by probe_ass_names (None: not probed -> face.ass_name)

    @property
    def path(self) -> Path:
        return Path(self.face.path)

    @property
    def ass_name(self) -> str:
        return self.libass_name or self.face.ass_name


_FONT_CACHE: dict[tuple, ResolvedFont] = {}


def clear_font_cache() -> None:
    _FONT_CACHE.clear()


def resolve_font(name: str, font_file: str | None = None, font_dirs: Iterable[str] = ()) -> ResolvedFont:
    """Resolve ``name`` to an exact face.  Raises FontError instead of ever substituting.
    Successful lookups are cached per process (key includes the project root)."""
    key = (name, font_file, tuple(font_dirs), str(paths.project_root()))
    hit = _FONT_CACHE.get(key)
    if hit is not None and Path(hit.face.path).is_file():
        return hit
    f = _resolve_font_uncached(name, font_file, font_dirs)
    _FONT_CACHE[key] = f
    return f


def _resolve_font_uncached(name: str, font_file: str | None, font_dirs: Iterable[str]) -> ResolvedFont:
    if font_file:
        p = paths.absp(font_file)
        if not p.is_file():
            raise FontError(f"font_file 이 없습니다: {font_file}")
        f = face_by_name(p, name)
        if f is None:
            raise FontError(f"font_file {font_file} 안에 '{name}' 이름의 글꼴이 없습니다(대체 사용 안 함)")
        return ResolvedFont(name, f, "font_file")
    try:  # agreed API (another module); import lazily
        from .. import fonts as _fonts  # type: ignore
        find_font = _fonts.find_font
    except ImportError:
        find_font = None
    if find_font is not None:
        import inspect

        try:
            kw = {"extra_dirs": list(font_dirs)} if "extra_dirs" in inspect.signature(find_font).parameters else {}
            p = find_font(name, **kw)
        except Exception as e:  # never silently fall back when the lookup itself failed
            raise FontError(f"shortkit.fonts.find_font('{name}') 실패: {type(e).__name__}: {e}") from None
        if p is None:
            raise FontError(f"글꼴 '{name}' 을 찾지 못했습니다(대체 글꼴은 쓰지 않음). "
                            "`python -m shortkit.fonts find` / `shortkit doctor --fetch-fonts` 로 확인하세요")
        f = face_by_name(p, name)
        if f is None:
            raise FontError(f"shortkit.fonts 가 돌려준 {Path(p).name} 에 '{name}' 이름이 없습니다(검증 실패)")
        return ResolvedFont(name, f, "shortkit.fonts")
    for d in font_dirs:
        root = paths.absp(d)
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*")):
            if p.suffix.lower() in (".ttf", ".otf", ".ttc", ".otc") and p.is_file():
                f = face_by_name(p, name)
                if f is not None:
                    return ResolvedFont(name, f, "font_dirs")
    # fc-match answers with a substitute when the name is unknown: accept it ONLY if the returned
    # face really carries the requested name; otherwise search fc-list for an exact name.
    if shutil.which("fc-match"):
        out = subprocess.run(["fc-match", "-f", "%{file}", name], capture_output=True, text=True).stdout.strip()
        if out and Path(out).is_file():
            f = face_by_name(out, name)
            if f is not None:
                return ResolvedFont(name, f, "fc-match(verified)")
    for file, idx in _fc_list_candidates(name):
        f = face_by_name(file, name)
        if f is not None:
            return ResolvedFont(name, f, "fc-list(exact)")
    raise FontError(f"글꼴 '{name}' 을 찾지 못했습니다(fc-match 대체 글꼴은 쓰지 않음)")


def _fc_list_candidates(name: str) -> list[tuple[str, int]]:
    if not shutil.which("fc-list"):
        return []
    out = subprocess.run(["fc-list", "-f", "%{file}\t%{index}\t%{family}\t%{fullname}\t%{postscriptname}\n"],
                         capture_output=True, text=True).stdout
    hits = []
    for ln in out.splitlines():
        parts = ln.split("\t")
        if len(parts) < 5:
            continue
        names = [s.strip() for s in ",".join(parts[2:5]).split(",")]
        if any(_norm(n) == _norm(name) for n in names):
            hits.append((parts[0], int(parts[1] or 0)))
    return sorted(set(hits))


# ----------------------------------------------------------------------------- layout
@dataclass
class LineBox:
    text: str
    left: float          # x of the advance box
    top: float           # top of the line box (asc+desc)
    width: float         # advance width
    height: float        # asc + desc
    baseline: float
    ink: tuple[float, float, float, float]    # x0, y0, x1, y1 (incl. outline stroke, excl. shadow)

    @property
    def center(self) -> tuple[float, float]:
        return (self.left + self.width / 2.0, self.top + self.height / 2.0)


@dataclass
class Layout:
    lines: list[LineBox]
    block: tuple[float, float, float, float]  # x, y, w, h of the layout box
    ink: tuple[float, float, float, float]    # x, y, w, h of the ink bbox (text+outline+shadow)
    overflow_lines: bool
    overflow_width: bool
    max_line_width: float
    ass_fontsize: float
    asc_px: float
    desc_px: float
    pitch: float


@lru_cache(maxsize=64)
def _pil_font(path: str, index: int, size: float):
    from PIL import ImageFont

    return ImageFont.truetype(path, size=size, index=index)


def break_lines(text: str, font, max_chars: int, max_width: float) -> list[str]:
    """Greedy word wrap on spaces; words longer than the limits are split by character.

    Forced breaks: ``\\n`` in the plan text.  Character counts exclude spaces."""
    out: list[str] = []

    def fits(s: str) -> bool:
        return len(s.replace(" ", "")) <= max_chars and font.getlength(s) <= max_width + 1e-6

    for para in text.split("\n"):
        words = para.split(" ") if para.strip() else [""]
        cur = ""
        for w in words:
            cand = w if not cur else f"{cur} {w}"
            if fits(cand):
                cur = cand
                continue
            if cur:
                out.append(cur)
                cur = ""
            if fits(w):
                cur = w
                continue
            piece = ""
            for ch in w:
                if fits(piece + ch) or not piece:
                    piece += ch
                else:
                    out.append(piece)
                    piece = ch
            cur = piece
        out.append(cur)
    return [ln for ln in out] or [""]


def layout_text(text: str, face: FaceMetrics, style: dict, anchor: tuple[float, float]) -> Layout:
    """Lay out ``text`` for a role style at ``anchor`` (canvas px)."""
    size = float(style["size_px"])
    font = _pil_font(face.path, face.index, size)
    lines = break_lines(text, font, int(style["max_chars_per_line"]), float(style["max_width_px"]))
    asc, desc = face.asc_px(size), face.desc_px(size)
    lh = asc + desc
    pitch = size * float(style["line_spacing"])
    n = len(lines)
    block_h = (n - 1) * pitch + lh
    ax, ay = anchor
    valign = style["valign"]
    top0 = ay if valign == "top" else (ay - block_h / 2.0 if valign == "middle" else ay - block_h)
    stroke = int(round(float(style.get("outline_px") or 0)))
    shadow = float(style.get("shadow_px") or 0)
    boxes: list[LineBox] = []
    for i, ln in enumerate(lines):
        w = float(font.getlength(ln))
        align = style["align"]
        left = ax - w / 2.0 if align == "center" else (ax if align == "left" else ax - w)
        top = top0 + i * pitch
        base = top + asc
        if ln:
            x0, y0, x1, y1 = font.getbbox(ln, anchor="ls", stroke_width=stroke)
            ink = (left + x0, base + y0, left + x1, base + y1)
        else:
            ink = (left, base, left, base)
        boxes.append(LineBox(ln, left, top, w, lh, base, ink))
    bx0 = min(b.left for b in boxes)
    bx1 = max(b.left + b.width for b in boxes)
    ix0 = min(b.ink[0] for b in boxes)
    iy0 = min(b.ink[1] for b in boxes)
    ix1 = max(b.ink[2] for b in boxes) + max(0.0, shadow)
    iy1 = max(b.ink[3] for b in boxes) + max(0.0, shadow)
    mw = max(b.width for b in boxes)
    return Layout(lines=boxes, block=(bx0, top0, bx1 - bx0, block_h), ink=(ix0, iy0, ix1 - ix0, iy1 - iy0),
                  overflow_lines=n > int(style["max_lines"]), overflow_width=mw > float(style["max_width_px"]) + 0.5,
                  max_line_width=mw, ass_fontsize=face.ass_fontsize(size), asc_px=asc, desc_px=desc, pitch=pitch)


# ----------------------------------------------------------------------------- ASS writing
def ass_color(hex_rgb: str, alpha: float = 1.0) -> str:
    """'#RRGGBB' + opacity (1 = opaque) -> '&HAABBGGRR'."""
    h = hex_rgb.lstrip("#")
    if len(h) != 6 or not re.fullmatch(r"[0-9A-Fa-f]{6}", h):
        raise ValueError(f"bad color {hex_rgb!r} (expected #RRGGBB)")
    r, g, b = h[0:2], h[2:4], h[4:6]
    a = int(round((1.0 - max(0.0, min(1.0, alpha))) * 255))
    return f"&H{a:02X}{b}{g}{r}".upper()


def ass_bgr(hex_rgb: str) -> str:
    h = hex_rgb.lstrip("#")
    return f"&H{h[4:6]}{h[2:4]}{h[0:2]}&".upper()


def ass_time(t: float) -> str:
    cs = int(round(max(0.0, t) * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, c = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{c:02d}"


def _f(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def _drawing(points_list: list[list[tuple[float, float]]], scale_pow: int = 3) -> tuple[str, float, float, float, float]:
    """Polygons -> ASS drawing (\\p3: coordinates x4 as integers, quarter-px precision).
    Returns (commands, min_x, min_y, w, h) with the drawing normalized so its bbox starts at 0,0."""
    k = 2 ** (scale_pow - 1)
    xs = [x for pts in points_list for x, _ in pts]
    ys = [y for pts in points_list for _, y in pts]
    mx, my = min(xs), min(ys)
    cmds = []
    for pts in points_list:
        p0 = pts[0]
        cmds.append(f"m {int(round((p0[0] - mx) * k))} {int(round((p0[1] - my) * k))}")
        cmds.append("l " + " ".join(f"{int(round((x - mx) * k))} {int(round((y - my) * k))}" for x, y in pts[1:]))
    return " ".join(cmds), mx, my, max(xs) - mx, max(ys) - my


@dataclass
class AssEvent:
    layer: int
    start: float
    end: float
    style: str
    text: str


@dataclass
class AssDoc:
    width: int
    height: int
    styles: list[str] = field(default_factory=list)
    events: list[AssEvent] = field(default_factory=list)

    def render(self) -> str:
        head = ["[Script Info]", "; generated by shortkit.edit.captions (do not edit by hand)",
                "ScriptType: v4.00+", f"PlayResX: {self.width}", f"PlayResY: {self.height}",
                "LayoutResX: %d" % self.width, "LayoutResY: %d" % self.height,
                "WrapStyle: 2", "ScaledBorderAndShadow: yes", "YCbCr Matrix: None", "Kerning: yes", "",
                "[V4+ Styles]",
                "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
                "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
                "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding"]
        head += self.styles
        head += ["", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
        evs = sorted(self.events, key=lambda e: (e.start, e.layer))
        body = [f"Dialogue: {e.layer},{ass_time(e.start)},{ass_time(e.end)},{e.style},,0,0,0,,{e.text}" for e in evs]
        return "\n".join(head + body) + "\n"


LIBASS_EMBOLDEN_MARGIN = 150   # libass ass_font.c: embolden when requested weight > face weight + 150


def ass_bold_flag(face_weight: int) -> int:
    """ASS style ``Bold`` value for a face of ``face_weight`` (usWeightClass).  libass reads the style
    field as a boolean (non-zero -> weight 700, zero -> 400) and emboldens synthetically when the
    request exceeds the face weight + 150, so -1 (700) is written only when that cannot happen."""
    return -1 if int(face_weight or 400) + LIBASS_EMBOLDEN_MARGIN >= 700 else 0


def style_line(name: str, fontname: str, fontsize: float, color: str, outline_color: str, shadow_color: str,
               weight: int, outline: float, shadow: float) -> str:
    """``weight`` = the selected face's usWeightClass (mapped to the libass-safe Bold flag)."""
    return (f"Style: {name},{fontname},{_f(fontsize)},{ass_color(color)},{ass_color(color)},"
            f"{ass_color(outline_color)},{ass_color(shadow_color)},{ass_bold_flag(weight)},0,0,0,100,100,0,0,1,"
            f"{_f(outline)},{_f(shadow)},5,0,0,0,1")


def role_style_line(role: str, st: dict, font: "ResolvedFont") -> str:
    """The ASS style line of a caption role (libass-matched face name, win-metric font size)."""
    f = font
    return style_line(role, f.ass_name, f.face.ass_fontsize(float(st["size_px"])), st["color"],
                      st["outline_color"], st["shadow_color"], f.face.weight,
                      float(st["outline_px"]), float(st["shadow_px"]))


def highlight_markup(line: str, words: list[str], base_color: str, hl_color: str) -> str:
    """Wrap every occurrence of the highlight words in colour overrides (same font -> metrics unchanged)."""
    if not words:
        return line
    spans: list[tuple[int, int]] = []
    for w in sorted({w for w in words if w}, key=len, reverse=True):
        for m in re.finditer(re.escape(w), line):
            if not any(a < m.end() and m.start() < b for a, b in spans):
                spans.append((m.start(), m.end()))
    if not spans:
        return line
    out, pos = [], 0
    for a, b in sorted(spans):
        out.append(line[pos:a])
        out.append("{\\1c%s}%s{\\1c%s}" % (ass_bgr(hl_color), line[a:b], ass_bgr(base_color)))
        pos = b
    out.append(line[pos:])
    return "".join(out)


def caption_events(cap, layout: Layout, style_name: str) -> list[AssEvent]:
    """ASS events for one resolved caption (IR CaptionBox + its Layout)."""
    mi, mo = cap.motion_in or {}, cap.motion_out or {}
    in_type, in_ms = mi.get("type", "none"), int(round(float(mi.get("dur_s") or 0) * 1000))
    out_type, out_ms = mo.get("type", "none"), int(round(float(mo.get("dur_s") or 0) * 1000))
    fad_in = in_ms if in_type == "fade" else 0
    fad_out = out_ms if out_type == "fade" else 0
    fad = f"\\fad({fad_in},{fad_out})" if (fad_in or fad_out) else ""
    bx, by, bw, bh = layout.block
    cx, cy = bx + bw / 2.0, by + bh / 2.0

    def motion(px: float, py: float) -> str:
        if in_type == "pop" and in_ms > 0:
            s = float(mi.get("scale_from") or 1.0)
            sx, sy = cx + s * (px - cx), cy + s * (py - cy)
            pct = _f(s * 100)
            return (f"\\move({_f(sx)},{_f(sy)},{_f(px)},{_f(py)},0,{in_ms})"
                    f"\\fscx{pct}\\fscy{pct}\\t(0,{in_ms},\\fscx100\\fscy100)")
        if in_type == "slide_up" and in_ms > 0:
            off = float(mi.get("offset_px") or 0)
            return f"\\move({_f(px)},{_f(py + off)},{_f(px)},{_f(py)},0,{in_ms})"
        return f"\\pos({_f(px)},{_f(py)})"

    evs: list[AssEvent] = []
    box = cap.box or {}
    if box.get("enabled") and box.get("rect"):
        evs += box_events(cap, style_name, fad_out, in_type, in_ms, mi)
    for lb in layout.lines:
        if not lb.text:
            continue
        px, py = lb.center
        body = highlight_markup(lb.text, list(cap.highlight or []), cap.color, cap.highlight_color)
        evs.append(AssEvent(2, cap.start, cap.end, style_name, f"{{\\an5{motion(px, py)}{fad}}}{body}"))
    return evs


def box_events(cap, style_name: str, fad_out_ms: int, in_type: str, in_ms: int, mi: dict) -> list[AssEvent]:
    """Caption box = ``box.rect`` (ink bbox incl. outline + pad per side, integer canvas px).

    libass snaps the edges of a drawing placed at a fractional / centred (\\an5) position outward
    to whole pixels (a 243 px box came out 244 px), so AT REST the box is drawn with \\an7 at its
    integer top-left corner -- its pixel edges are then exactly the rect.  A pop (scale) motion
    needs the centre as the scaling origin, so it gets its own \\an5 event for the motion only."""
    x, y, w, h = (float(v) for v in cap.box["rect"])
    cmds, _, _, _, _ = _drawing([[(0, 0), (w, 0), (w, h), (0, h)]])
    look = (f"\\bord0\\shad0\\blur0\\1c{ass_bgr(cap.box['color'])}"
            f"\\1a&H{int(round((1 - float(cap.box['alpha'])) * 255)):02X}&\\p3")
    body = cmds + "{\\p0}"
    fin = in_ms if in_type == "fade" else 0
    evs: list[AssEvent] = []
    rest_start = cap.start
    if in_type == "pop" and in_ms > 0:
        cx, cy = x + w / 2.0, y + h / 2.0
        sc = float(mi.get("scale_from") or 1.0)
        pct = _f(sc * 100)
        t_end = min(cap.end, cap.start + in_ms / 1000.0)
        evs.append(AssEvent(1, cap.start, t_end, style_name,
                            f"{{\\an5\\pos({_f(cx)},{_f(cy)})\\fscx{pct}\\fscy{pct}\\t(0,{in_ms},\\fscx100\\fscy100)"
                            f"{look}}}" + body))
        rest_start = t_end
    if in_type == "slide_up" and in_ms > 0:
        off = float(mi.get("offset_px") or 0)
        pos = f"\\move({_f(x)},{_f(y + off)},{_f(x)},{_f(y)},0,{in_ms})"
    else:
        pos = f"\\pos({_f(x)},{_f(y)})"
    fad = f"\\fad({fin},{fad_out_ms})" if (fin or fad_out_ms) else ""
    if cap.end > rest_start:
        evs.append(AssEvent(1, rest_start, cap.end, style_name, f"{{\\an7{pos}{fad}{look}}}" + body))
    return evs


def box_rect_from_ink(ink: tuple[float, float, float, float], pad_x: float, pad_y: float) -> list[int]:
    """Box rect [x, y, w, h] (integer px) = ink bbox (x0, y0, x1, y1; incl. outline) + pad per side."""
    x0, y0, x1, y1 = ink
    bx0, by0 = int(round(x0 - pad_x)), int(round(y0 - pad_y))
    bx1, by1 = int(round(x1 + pad_x)), int(round(y1 + pad_y))
    return [bx0, by0, bx1 - bx0, by1 - by0]


def libass_ink_bboxes(width: int, height: int, styles: dict[str, str], jobs: list[dict],
                      font_files: Iterable[str | os.PathLike], threshold: int = 128) -> list[tuple[int, int, int, int] | None]:
    """Ink bbox (x0, y0, x1, y1; x1/y1 exclusive, canvas px) of captions AS LIBASS DRAWS THEM:
    each job ``{style, outline, lines: [(text, px, py)]}`` is rendered alone (white fill AND white
    outline on black, no shadow, at rest) through ffmpeg/libass, and the pixels with >= 50 %
    coverage give the bbox.  This is the "visible ink incl. outline" the reference analyzer
    measures, so box pads computed from it match a pixel measurement of our own output."""
    import tempfile

    from ..util.media import FFMPEG

    if not jobs:
        return []
    doc = AssDoc(int(width), int(height))
    doc.styles = list(styles.values())
    for i, j in enumerate(jobs):
        for text, px, py in j["lines"]:
            if not text:
                continue
            doc.events.append(AssEvent(0, i * 0.1, (i + 1) * 0.1, j["style"],
                                       f"{{\\an5\\pos({_f(px)},{_f(py)})\\bord{_f(float(j.get('outline') or 0))}"
                                       f"\\shad0\\blur0\\1c&HFFFFFF&\\3c&HFFFFFF&\\1a&H00&\\3a&H00&}}{text}"))
    n = len(jobs)
    with tempfile.TemporaryDirectory(prefix="shortkit_ink_") as td:
        tdp = Path(td)
        fd = tdp / "fonts"
        fd.mkdir()
        for f in font_files:
            src = Path(f)
            dst = fd / src.name
            if not dst.exists():
                try:
                    dst.symlink_to(src.resolve())
                except OSError:
                    shutil.copyfile(src, dst)
        (tdp / "ink.ass").write_text(doc.render(), encoding="utf-8")
        proc = subprocess.run([FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                               f"color=c=black:s={int(width)}x{int(height)}:r=10:d={n * 0.1 + 0.05:.2f}",
                               "-vf", "format=rgb24,subtitles=filename=ink.ass:fontsdir=fonts", "-frames:v", str(n),
                               "-f", "rawvideo", "-pix_fmt", "gray", "-"], cwd=td, capture_output=True)
    if proc.returncode != 0:
        raise FontError("libass 잉크 측정 렌더 실패: " + proc.stderr.decode("utf-8", "replace")[-600:])
    import numpy as np

    fs = int(width) * int(height)
    buf = proc.stdout
    if len(buf) < n * fs:
        raise FontError(f"libass 잉크 측정: 프레임 {len(buf) // fs}/{n} 개만 나옴")
    out: list[tuple[int, int, int, int] | None] = []
    for i in range(n):
        fr = np.frombuffer(buf[i * fs:(i + 1) * fs], np.uint8).reshape(int(height), int(width))
        ys, xs = np.nonzero(fr >= threshold)
        out.append(None if len(xs) == 0 else (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1))
    return out


# ----------------------------------------------------------------------------- decorations
# Arrow geometry comes from the preset (decorations.arrow.head_len_ratio / head_width_ratio /
# shaft_width_ratio, copied into Decoration.style by the resolver); there is no code default.
ARROW_RATIO_KEYS = ("head_len_ratio", "head_width_ratio", "shaft_width_ratio")
RING_SEGMENTS = 72


def _rot(pts, deg):
    a = math.radians(deg or 0.0)
    c, s = math.cos(a), math.sin(a)
    return [(x * c - y * s, x * s + y * c) for x, y in pts]


def deco_shape(kind: str, kf: dict, style: dict) -> tuple[list[list[tuple[float, float]]], tuple[float, float]]:
    """Polygons in canvas px for one keyframe; returns (polygons, reference point).

    arrow : tip at (x, y); length = h or style size_px; head width = w or length * head_width_ratio;
            head length = length * head_len_ratio; shaft width = length * shaft_width_ratio (scaled
            with w); rotation degrees clockwise, 0 = pointing DOWN (arrow above its target).
    circle: ellipse ring centred at (x, y) with size w x h, stroke = style stroke_px.
    box   : rectangle ring centred at (x, y) with size w x h, stroke = style stroke_px.
    """
    x, y = float(kf["x"]), float(kf["y"])
    if kind == "arrow":
        missing = [k for k in ARROW_RATIO_KEYS if style.get(k) is None]
        if missing:
            raise ValueError(f"decorations.arrow.{missing[0]} 가 장식 스타일에 없습니다(현재 프리셋으로 다시 resolve)")
        r_len, r_w, r_sh = (float(style[k]) for k in ARROW_RATIO_KEYS)
        L = float(kf.get("h") or style["size_px"])
        W = float(kf.get("w") or L * r_w)
        hl, sw = L * r_len, max(2.0, L * r_sh * (W / (L * r_w)))
        pts = [(0, 0), (-W / 2, -hl), (-sw / 2, -hl), (-sw / 2, -L), (sw / 2, -L), (sw / 2, -hl), (W / 2, -hl)]
        pts = [(px + x, py + y) for px, py in _rot(pts, kf.get("rotation") or 0.0)]
        return [pts], (x, y)
    w, h = float(kf["w"]), float(kf["h"])
    st = float(style["stroke_px"])
    if kind == "circle":
        outer = [(x + w / 2 * math.cos(2 * math.pi * i / RING_SEGMENTS), y + h / 2 * math.sin(2 * math.pi * i / RING_SEGMENTS))
                 for i in range(RING_SEGMENTS)]
        inner = [(x + max(0.5, w / 2 - st) * math.cos(2 * math.pi * i / RING_SEGMENTS),
                  y + max(0.5, h / 2 - st) * math.sin(2 * math.pi * i / RING_SEGMENTS)) for i in range(RING_SEGMENTS)]
    elif kind == "box":
        outer = [(x - w / 2, y - h / 2), (x + w / 2, y - h / 2), (x + w / 2, y + h / 2), (x - w / 2, y + h / 2)]
        iw, ih = max(0.5, w / 2 - st), max(0.5, h / 2 - st)
        inner = [(x - iw, y - ih), (x + iw, y - ih), (x + iw, y + ih), (x - iw, y + ih)]
    else:
        raise ValueError(f"unknown decoration kind {kind}")
    if kf.get("rotation"):
        outer = [(px + x, py + y) for px, py in _rot([(a - x, b - y) for a, b in outer], kf["rotation"])]
        inner = [(px + x, py + y) for px, py in _rot([(a - x, b - y) for a, b in inner], kf["rotation"])]
    return [outer, list(reversed(inner))], (x, y)


def _blink_tags(ev_start: float, ev_end: float, deco_start: float, hz: float) -> str:
    if not hz or hz <= 0:
        return ""
    period = 1.0 / hz
    tags = []
    # visible during the first half of each period, counted from the decoration start
    k0 = math.floor((ev_start - deco_start) / period)
    k = k0
    while True:
        on = deco_start + k * period
        off = on + period / 2.0
        if on >= ev_end:
            break
        for tt, a in ((on, "00"), (off, "FF")):
            if ev_start < tt < ev_end:
                ms = int(round((tt - ev_start) * 1000))
                # complete AT the toggle instant (frame times on the toggle show the new state)
                tags.append(f"\\t({max(0, ms - 1)},{ms},\\alpha&H{a}&)")
        k += 1
    phase = (ev_start - deco_start) % period
    init = "\\alpha&H00&" if phase < period / 2.0 - 1e-9 else "\\alpha&HFF&"
    return init + "".join(tags)


def _interp_kf(a: dict, b: dict, t: float) -> dict:
    if b["t"] <= a["t"]:
        return dict(a)
    u = (t - a["t"]) / (b["t"] - a["t"])
    out = dict(a)
    for k in ("x", "y", "w", "h", "rotation"):
        va, vb = a.get(k), b.get(k)
        if va is not None and vb is not None:
            out[k] = va + (vb - va) * u
    out["t"] = t
    return out


def decoration_events(deco, fps: float, style_name: str = "deco") -> list[AssEvent]:
    """IR Decoration -> ASS events: one event per keyframe interval with \\move when only the
    position changes; per-frame events when size/rotation change (exact, no approximation)."""
    st = deco.style
    color = st["color"]
    outline = float(st.get("outline_px") or 0)
    ocol = st.get("outline_color") or "#000000"
    base = f"\\bord{_f(outline)}\\shad0\\blur0\\1c{ass_bgr(color)}\\3c{ass_bgr(ocol)}"
    kfs = sorted(deco.keyframes, key=lambda k: k["t"])
    segs: list[tuple[float, float, dict, dict]] = []
    if kfs[0]["t"] > deco.start:
        segs.append((deco.start, kfs[0]["t"], kfs[0], kfs[0]))
    for a, b in zip(kfs, kfs[1:]):
        segs.append((a["t"], b["t"], a, b))
    if kfs[-1]["t"] < deco.end:
        segs.append((kfs[-1]["t"], deco.end, kfs[-1], kfs[-1]))
    evs: list[AssEvent] = []
    for s0, s1, a, b in segs:
        s0c, s1c = max(s0, deco.start), min(s1, deco.end)
        if s1c <= s0c:
            continue
        same_shape = all((a.get(k) or 0) == (b.get(k) or 0) for k in ("w", "h", "rotation"))
        if same_shape:
            ka, kb = _interp_kf(a, b, s0c), _interp_kf(a, b, s1c)
            polys, _ = deco_shape(deco.kind, ka, st)
            cmds, mx, my, _, _ = _drawing(polys)
            polys_b, _ = deco_shape(deco.kind, kb, st)
            _, mxb, myb, _, _ = _drawing(polys_b)
            pos = (f"\\pos({_f(mx)},{_f(my)})" if (mx, my) == (mxb, myb) else
                   f"\\move({_f(mx)},{_f(my)},{_f(mxb)},{_f(myb)},0,{int(round((s1c - s0c) * 1000))})")
            tag = f"{{\\an7{pos}{base}{_blink_tags(s0c, s1c, deco.start, deco.blink_hz)}\\p3}}"
            evs.append(AssEvent(0, s0c, s1c, style_name, tag + cmds + "{\\p0}"))
        else:
            n0 = int(math.floor(s0c * fps + 1e-6))
            n1 = int(math.ceil(s1c * fps - 1e-6))
            for n in range(n0, n1):
                f0, f1 = max(s0c, n / fps), min(s1c, (n + 1) / fps)
                if f1 <= f0:
                    continue
                k = _interp_kf(a, b, f0)
                polys, _ = deco_shape(deco.kind, k, st)
                cmds, mx, my, _, _ = _drawing(polys)
                tag = f"{{\\an7\\pos({_f(mx)},{_f(my)}){base}{_blink_tags(f0, f1, deco.start, deco.blink_hz)}\\p3}}"
                evs.append(AssEvent(0, f0, f1, style_name, tag + cmds + "{\\p0}"))
    return evs


def write_ass(path: str | os.PathLike, canvas: dict, captions: list, layouts: dict, role_styles: dict,
              decorations: list, fonts: dict) -> str:
    """Write the single ASS file used by ffmpeg (and MLT). Returns the text."""
    doc = AssDoc(int(canvas["width"]), int(canvas["height"]))
    for role, st in role_styles.items():
        doc.styles.append(role_style_line(role, st, fonts[role]))
    # decorations are vector drawings; the style font only has to exist (no fallback lookups)
    deco_font = fonts[next(iter(role_styles))].ass_name if role_styles else "sans-serif"
    doc.styles.append(style_line("deco", deco_font, 20, "#FFFFFF", "#000000", "#000000", 400, 0, 0))
    for cap in captions:
        doc.events += caption_events(cap, layouts[cap.id], cap.role)
    for d in decorations:
        doc.events += decoration_events(d, float(canvas["fps"]))
    txt = doc.render()
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(txt, encoding="utf-8")
    return txt


# ----------------------------------------------------------------------------- libass font-selection guard
_FONTSELECT_RE = re.compile(r"fontselect: \((?P<req>.+?), (?P<w>\d+), (?P<i>\d+)\) -> (?P<path>.*?), (?P<idx>\d+), (?P<ps>\S+)")
_FALLBACK_RE = re.compile(r"Glyph 0x(?P<cp>[0-9A-Fa-f]+) not found, selecting one more font for \((?P<req>.+?), (?P<w>\d+), ")
DEFAULT_SAMPLE = "가나다 ABC 123 !?"
_FONT_EXTS = (".ttf", ".otf", ".ttc", ".otc")
_EVENT_FORMAT = "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"


def _style_rows(head: str) -> dict[str, list[str]]:
    """style name -> the fields of its ``Style:`` line (V4+ order)."""
    out: dict[str, list[str]] = {}
    for ln in head.splitlines():
        if ln.startswith("Style:"):
            parts = [x.strip() for x in ln.split(":", 1)[1].split(",")]
            out[parts[0]] = parts
    return out


def _libass_request_weight(bold_field: str) -> int:
    """libass ass.c: ``style->Bold = !!style->Bold`` then 1 -> 700, 0 -> 400."""
    try:
        return 700 if int(float(bold_field)) != 0 else 400
    except ValueError:
        return 400


def event_chars(ass_text: str) -> dict[str, str]:
    """style -> the distinct visible characters of its Dialogue events (override tags and vector
    drawings removed).  This is what the font check must cover: a glyph missing from the face
    makes libass pick another font for that character."""
    chars: dict[str, set[str]] = {}
    for ln in ass_text.splitlines():
        if not ln.startswith("Dialogue:"):
            continue
        parts = ln.split(":", 1)[1].split(",", 9)
        if len(parts) < 10:
            continue
        st, text = parts[3].strip(), parts[9]
        vis, pos, drawing = [], 0, False
        for m in re.finditer(r"\{([^}]*)\}", text):
            if not drawing:
                vis.append(text[pos:m.start()])
            pm = re.findall(r"\\p(\d+)", m.group(1))
            if pm:
                drawing = int(pm[-1]) > 0
            pos = m.end()
        if not drawing:
            vis.append(text[pos:])
        s = "".join(vis).replace("\\N", "").replace("\\n", "").replace("\\h", "")
        chars.setdefault(st, set()).update(ch for ch in s if not ch.isspace())
    return {k: "".join(sorted(v)) for k, v in chars.items() if v}


def _dir_faces(fonts_dir: str | os.PathLike) -> list[FaceMetrics]:
    """Faces libass loads from ``fontsdir`` (it reads the directory itself, not recursively)."""
    d = Path(fonts_dir)
    if not d.is_dir():
        return []
    out: list[FaceMetrics] = []
    for p in sorted(d.iterdir()):
        if p.suffix.lower() in _FONT_EXTS and p.is_file():
            try:
                out.extend(read_faces(str(p)))
            except (OSError, struct.error, IndexError):
                continue
    return out


def _same_file(a: str | os.PathLike, b: str | os.PathLike) -> bool:
    try:
        pa, pb = Path(a).resolve(), Path(b).resolve()
        if pa == pb:
            return True
        if pa.stat().st_size != pb.stat().st_size:
            return False
        from ..util.hashing import sha256_file

        return sha256_file(pa) == sha256_file(pb)
    except OSError:
        return False


def _expected_faces(spec, dir_faces: list[FaceMetrics]) -> tuple[str, list[FaceMetrics], str]:
    """(expected PostScript name, candidate faces, how).  ``spec`` is a FaceMetrics / ResolvedFont
    (exact face), a PostScript name, or a face name that identifies exactly ONE face (one PostScript
    name) among the fonts_dir files; anything else is compared verbatim with the selected PS name."""
    if isinstance(spec, ResolvedFont):
        spec = spec.face
    if isinstance(spec, FaceMetrics):
        return spec.postscript or "", [spec], "face"
    s = str(spec)
    by_ps = [f for f in dir_faces if f.postscript and _norm(f.postscript) == _norm(s)]
    if by_ps:
        return by_ps[0].postscript or s, by_ps, "postscript"
    by_name = [f for f in dir_faces
               if any(_norm(n) == _norm(s) for n in f.names + f.win_fullnames + f.win_families)]
    pss = {_norm(f.postscript or "") for f in by_name}
    if by_name and len(pss) == 1 and by_name[0].postscript:
        return by_name[0].postscript, by_name, "name_in_fonts_dir"
    return s, [], "as_given"


def _selected_face_weight(m, faces: list[FaceMetrics], dir_faces: list[FaceMetrics]) -> int | None:
    """usWeightClass of the face a fontselect line names: the expected face, else the fonts-dir face with
    that PostScript name, else the logged system file itself; None only if none of them can be read."""
    ps, path, idx = m.group("ps"), m.group("path"), int(m.group("idx"))
    for pool in (faces, dir_faces):
        cand = [f for f in pool if f.postscript and _norm(f.postscript) == _norm(ps)]
        if cand:
            return int(cand[0].weight or 400)
    if os.path.isabs(path) and Path(path).is_file():
        try:
            got = [f for f in read_faces(path) if f.index == idx]
        except (OSError, struct.error, IndexError):
            got = []
        if got:
            return int(got[0].weight or 400)
    return None


def _judge_selection(matches: list, ps: str, faces: list[FaceMetrics], dir_faces: list[FaceMetrics] = ()) -> dict:
    """Compare libass' fontselect lines for one request with the expected face."""
    selected = [m.group("ps") for m in matches]
    files, wrong_file, synth = [], False, False
    face_w = None
    for m in matches:
        path, idx, w = m.group("path"), int(m.group("idx")), int(m.group("w"))
        face_w = _selected_face_weight(m, faces, list(dir_faces))
        if face_w is None:
            synth = None if synth is False else synth       # weight unreadable: cannot rule it out
        elif w > face_w + LIBASS_EMBOLDEN_MARGIN:
            synth = True
        if os.path.isabs(path):                      # fontconfig (system) face: check the very file
            files.append(f"<system>/{Path(path).name}")
            if faces and not any(_same_file(path, f.path) and idx == f.index for f in faces):
                wrong_file = True
        else:                                        # memory font loaded from fontsdir (logged by PS name)
            files.append(f"<fontsdir>/{path}#{idx}")
            if faces and not any(idx == f.index for f in faces):
                wrong_file = True
    ok = bool(selected) and all(_norm(g) == _norm(ps) for g in selected) and not wrong_file and synth is False
    return {"selected": selected, "selected_files": files, "face_weight": face_w, "synthetic_bold": synth,
            "wrong_file": wrong_file, "ok": ok}


def _run_libass(ass_text: str, fonts_dir: str | os.PathLike | None, font_files: Iterable = ()) -> tuple[int, str]:
    """Render one 640x360 frame through ffmpeg/libass at verbose level; returns (rc, log).  The fonts
    directory is linked as ./fonts so no path escaping is needed in the filter string."""
    import tempfile

    from ..util.media import FFMPEG

    with tempfile.TemporaryDirectory(prefix="shortkit_fontsel_") as td:
        tdp = Path(td)
        fd = tdp / "fonts"
        if fonts_dir is not None:
            fd.symlink_to(Path(fonts_dir).resolve(), target_is_directory=True)
        else:
            fd.mkdir()
            for f in font_files:
                src = Path(f).resolve()
                dst = fd / src.name
                if not dst.exists():
                    dst.symlink_to(src)
        (tdp / "fontcheck.ass").write_text(ass_text, encoding="utf-8")
        proc = subprocess.run([FFMPEG, "-hide_banner", "-nostdin", "-v", "verbose", "-f", "lavfi", "-i",
                               "color=black:s=640x360:d=0.2", "-vf", "subtitles=filename=fontcheck.ass:fontsdir=fonts",
                               "-frames:v", "1", "-f", "null", "-"], cwd=td, capture_output=True, text=True)
    return proc.returncode, proc.stderr or ""


def _sample_events(style: str, sample: str, chunk: int = 12) -> list[str]:
    s = "".join(ch for ch in sample if not ch.isspace() and ch not in "{}\\") or DEFAULT_SAMPLE
    return [f"Dialogue: 0,0:00:00.00,0:00:01.00,{style},,0,0,0,,{{\\an7\\pos(4,{4 + 30 * (k % 10)})}}{s[i:i + chunk]}"
            for k, i in enumerate(range(0, len(s), chunk))]


def verify_libass_fonts(ass_text: str, fonts_dir: str | os.PathLike, expected: dict,
                        sample: str | None = None) -> dict:
    """Render every expected style through ffmpeg/libass with verbose logging and confirm from the
    ``fontselect`` log that libass selected exactly the expected face, with no glyph fallback and no
    synthetic emboldening.  ``expected`` maps style name -> the face: a FaceMetrics/ResolvedFont, a
    PostScript name, or a name identifying exactly one face among the ``fonts_dir`` files.

    Each style is rendered with the characters its own events use (``event_chars``); styles without
    events (and every style when ``sample`` is given) use ``sample`` / ``DEFAULT_SAMPLE``.
    Returns {ok, styles: {style: {requested, expected, expected_postscript, selected, selected_files,
    requested_weight, face_weight, synthetic_bold, fallback_glyphs, sample, ok}}}.

    This checks the OUTPUT renderer's real behaviour instead of trusting our own font resolution."""
    head, _, _ = ass_text.partition("[Events]")
    rows = _style_rows(head)
    used = event_chars(ass_text) if sample is None else {}
    dir_faces = _dir_faces(fonts_dir)
    events, samples = [], {}
    for st in rows:
        if st in expected:
            samples[st] = sample if sample is not None else used.get(st, DEFAULT_SAMPLE)
            events += _sample_events(st, samples[st])
    test_ass = head + "[Events]\n" + _EVENT_FORMAT + "\n" + "\n".join(events) + "\n"
    rc, log = _run_libass(test_ass, fonts_dir)
    sel_all = list(_FONTSELECT_RE.finditer(log))
    fb_all = list(_FALLBACK_RE.finditer(log))
    res: dict = {"ok": True, "styles": {}}
    for st, parts in rows.items():
        if st not in expected:
            continue
        req = parts[1] if len(parts) > 1 else None
        w = _libass_request_weight(parts[7]) if len(parts) > 7 else 400
        ps, faces, how = _expected_faces(expected[st], dir_faces)
        matches = [m for m in sel_all if m.group("req") == req and int(m.group("w")) == w]
        fb = ["U+" + m.group("cp").upper() for m in fb_all if m.group("req") == req and int(m.group("w")) == w]
        j = _judge_selection(matches, ps, faces, dir_faces)
        ok = j["ok"] and not fb
        exp = expected[st]
        res["styles"][st] = {"requested": req, "expected": exp if isinstance(exp, str) else ps,
                             "expected_postscript": ps, "expected_by": how, "requested_weight": w,
                             "selected": j["selected"], "selected_files": j["selected_files"],
                             "face_weight": j["face_weight"], "synthetic_bold": j["synthetic_bold"],
                             "wrong_file": j["wrong_file"], "fallback_glyphs": fb, "sample": samples[st], "ok": ok}
        res["ok"] = res["ok"] and ok
    if rc != 0:
        res["ok"] = False
        res["error"] = log[-1500:]
    return res


_PROBE_CACHE: dict[tuple, dict] = {}


def probe_ass_names(faces: Iterable[FaceMetrics], extra_font_files: Iterable[str | os.PathLike] = ()) -> dict:
    """Ask libass which name selects each face.  The fonts directory holds every given face's file
    (plus ``extra_font_files``) -- the same set ``build/fonts`` gets -- and fontconfig adds the system
    fonts, exactly as in the render.  Every candidate name of every face
    (``FaceMetrics.libass_name_candidates``) is rendered once; the chosen name is the first whose
    PRIMARY selection (the first fontselect line; glyph coverage is checked later by
    ``verify_libass_fonts`` with the real caption text) is this very face (PostScript name, face
    index, file) without synthetic emboldening.

    Returns ``{(path, index): {"name": str | None, "tried": [{name, selected, selected_files, ok}]}}``;
    ``name`` None = libass reaches this face under none of its names (the caller must refuse it)."""
    uniq: dict[tuple[str, int], FaceMetrics] = {}
    for f in faces:
        uniq.setdefault((str(f.path), int(f.index)), f)
    files = sorted({str(Path(f.path).resolve()) for f in uniq.values()} |
                   {str(Path(p).resolve()) for p in extra_font_files})
    key = tuple((p, Path(p).stat().st_mtime) for p in files) + tuple(sorted(uniq))
    hit = _PROBE_CACHE.get(key)
    if hit is not None:
        return hit
    doc = AssDoc(640, 360)
    plan: list[tuple[tuple[str, int], str, str]] = []
    for fi, (k, f) in enumerate(uniq.items()):
        for ci, name in enumerate(f.libass_name_candidates):
            sn = f"p{fi}_{ci}"
            doc.styles.append(style_line(sn, name, 40, "#FFFFFF", "#000000", "#000000", f.weight, 0, 0))
            doc.events.append(AssEvent(0, 0.0, 1.0, sn, "가A"))
            plan.append((k, sn, name))
    rc, log = _run_libass(doc.render(), None, files)
    if rc != 0:
        raise FontError("libass 글꼴 이름 확인 렌더 실패: " + log[-600:])
    sel_all = list(_FONTSELECT_RE.finditer(log))
    out: dict = {k: {"name": None, "tried": []} for k in uniq}
    for k, sn, name in plan:
        f = uniq[k]
        w = 700 if ass_bold_flag(f.weight) else 400
        first = [m for m in sel_all if m.group("req") == name and int(m.group("w")) == w][:1]
        j = _judge_selection(first, f.postscript or "", [f]) if f.postscript else \
            {"selected": [m.group("ps") for m in first], "selected_files": [], "ok": False}
        out[k]["tried"].append({"name": name, "selected": j["selected"], "selected_files": j["selected_files"],
                                "ok": j["ok"]})
        if j["ok"] and out[k]["name"] is None:
            out[k]["name"] = name
    _PROBE_CACHE[key] = out
    return out
