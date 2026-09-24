"""ResolvedEdit: the single intermediate representation of an edit.

``resolve(plan, preset) -> ResolvedEdit`` turns a plan + preset into absolute output times,
resolved files and resolved style values.  Everything downstream consumes ONLY this IR:

  - shortkit.edit.render          ffmpeg master render (MP4)
  - shortkit.edit.export_mlt      editable MLT/Shotcut project (verified by a melt render)
  - shortkit.edit.export_fcpxml   FCPXML 1.9 (DaVinci Resolve / Final Cut import; unverified here)
  - shortkit.edit.export_otio     OpenTimelineIO json (neutral interchange)
  - shortkit.qa.*                 expected values for output checks

Paths inside the IR are root-relative strings (``shortkit.paths.absp`` at use time).
Times are seconds (float). Canvas coordinates are px in the canvas resolution.
Serialized to ``episodes/<id>/build/resolved.json``.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

SCHEMA = "shortkit.resolved/1"


@dataclass
class Rect:
    x: float
    y: float
    w: float
    h: float


@dataclass
class TimedRect:
    x: float
    y: float
    w: float
    h: float
    start: float | None = None      # SOURCE time (for clean ops) or OUTPUT time (for overlays), per field doc
    end: float | None = None
    reason: str = ""


@dataclass
class Zoom:
    scale_from: float
    scale_to: float
    center_src: tuple[float, float]  # zoom center in SOURCE px
    start: float                     # seconds from clip out_start (output time)
    dur: float
    ease: str                        # linear | in | out | inout


@dataclass
class Freeze:
    src_t: float                     # source time of the held frame
    out_start: float                 # output time the hold starts
    hold: float


@dataclass
class Transition:
    type: str                        # cut | flash | crossfade
    dur: float
    color: str | None = None         # flash color


@dataclass
class Clip:
    id: str
    source_id: str
    source_path: str
    src_in: float
    src_out: float
    speed: float
    out_start: float                 # output time where the clip's first frame shows
    out_end: float                   # output time where it ends (incl. freeze hold)
    region: Rect                     # canvas rect the (cleaned) source is fitted into
    fit: str                         # cover | contain
    src_size: tuple[int, int]        # source width, height
    crop: Rect | None = None         # cleaning crop in SOURCE px (applied before fit)
    delogo: list[TimedRect] = field(default_factory=list)   # SOURCE px, SOURCE time
    inpaint: list[TimedRect] = field(default_factory=list)  # SOURCE px, SOURCE time
    blur: list[TimedRect] = field(default_factory=list)     # SOURCE px, SOURCE time
    zoom: Zoom | None = None
    freeze: Freeze | None = None
    transition_in: Transition = field(default_factory=lambda: Transition("cut", 0.0))
    purpose: str = ""


@dataclass
class CaptionBox:
    id: str
    role: str
    text: str                        # final text incl. line breaks (\n) after layout
    lines: list[str]
    start: float
    end: float
    anchor: tuple[float, float]      # canvas px
    align: str
    valign: str
    bbox: Rect                       # expected ink bbox on canvas at rest (after motion_in), px
    font_name: str
    font_file: str | None
    size_px: float
    color: str
    highlight: list[str]
    highlight_color: str
    outline_px: float
    outline_color: str
    shadow_px: float
    box: dict
    motion_in: dict
    motion_out: dict
    grounding: dict | None = None


@dataclass
class Decoration:
    id: str
    kind: str
    start: float
    end: float
    keyframes: list[dict]            # absolute OUTPUT times: {t, x, y, w, h, rotation}
    blink_hz: float
    style: dict


@dataclass
class OriginalAudio:
    clip_id: str
    path: str                        # source file or its vocals stem
    stem: str                        # raw | vocals
    src_start: float
    src_end: float
    out_start: float
    out_end: float
    speed: float
    gain_db: float
    fade_s: float
    reason: str = ""


@dataclass
class SfxPlacement:
    id: str
    type: str
    path: str | None                 # None = unresolved (sfx_map says none/unmeasured) -> render refuses in production
    t: float
    gain_db: float
    event_t: float
    event_desc: str
    emotion: str | None
    map_status: str                  # have | none | unmeasured (있음/없음/못 잼)


@dataclass
class Bgm:
    path: str | None
    track_id: str | None
    section_start_s: float           # offset into the clean music file
    tempo_ratio: float
    gain_db: float
    fade_in_s: float
    fade_out_s: float
    envelope: list[tuple[float, float]]   # (output t, extra gain dB) piecewise-linear; ducking/silence only
    silences: list[tuple[float, float]]
    duck_ranges: list[tuple[float, float]]  # kept-dialogue ranges that caused ducking


@dataclass
class AudioPlan:
    sample_rate: int
    target_lufs: float
    true_peak_db: float
    bgm: Bgm | None
    originals: list[OriginalAudio]
    sfx: list[SfxPlacement]


@dataclass
class ResolvedEdit:
    schema: str
    episode_id: str
    preset_id: str
    preset_name: str
    format_id: str
    mode: str
    canvas: dict                     # {width, height, fps, background:{type,color,blur_sigma}}
    duration: float
    clips: list[Clip]
    captions: list[CaptionBox]
    decorations: list[Decoration]
    ass_path: str                    # captions + decorations rendered by libass (shared by ffmpeg and MLT)
    fonts_dir: str | None            # directory passed to libass
    audio: AudioPlan
    output_path: str
    warnings: list[str] = field(default_factory=list)
    provisional_keys: list[str] = field(default_factory=list)   # preset keys still unmeasured
    requested_change_keys: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict[str, Any]) -> "ResolvedEdit":
        def rect(v):
            return Rect(**v) if v else None

        def trs(vs):
            return [TimedRect(**v) for v in vs or []]

        clips = []
        for c in d["clips"]:
            c = dict(c)
            c["region"] = Rect(**c["region"])
            c["crop"] = rect(c.get("crop"))
            c["delogo"] = trs(c.get("delogo"))
            c["inpaint"] = trs(c.get("inpaint"))
            c["blur"] = trs(c.get("blur"))
            c["src_size"] = tuple(c["src_size"])
            if c.get("zoom"):
                z = dict(c["zoom"])
                z["center_src"] = tuple(z["center_src"])
                c["zoom"] = Zoom(**z)
            c["freeze"] = Freeze(**c["freeze"]) if c.get("freeze") else None
            c["transition_in"] = Transition(**c["transition_in"])
            clips.append(Clip(**c))
        caps = []
        for c in d["captions"]:
            c = dict(c)
            c["bbox"] = Rect(**c["bbox"])
            c["anchor"] = tuple(c["anchor"])
            caps.append(CaptionBox(**c))
        decos = [Decoration(**x) for x in d.get("decorations", [])]
        a = d["audio"]
        bgm = None
        if a.get("bgm"):
            b = dict(a["bgm"])
            b["envelope"] = [tuple(x) for x in b.get("envelope", [])]
            b["silences"] = [tuple(x) for x in b.get("silences", [])]
            b["duck_ranges"] = [tuple(x) for x in b.get("duck_ranges", [])]
            bgm = Bgm(**b)
        audio = AudioPlan(sample_rate=a["sample_rate"], target_lufs=a["target_lufs"], true_peak_db=a["true_peak_db"],
                          bgm=bgm, originals=[OriginalAudio(**o) for o in a.get("originals", [])],
                          sfx=[SfxPlacement(**s) for s in a.get("sfx", [])])
        rest = {k: v for k, v in d.items() if k not in ("clips", "captions", "decorations", "audio")}
        return ResolvedEdit(clips=clips, captions=caps, decorations=decos, audio=audio, **rest)
