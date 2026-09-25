"""Caption font identification on the FINAL MP4 with a ceiling measured for THIS output.

Method (shortkit.reference.typography, applied to the output instead of the reference):

1. The caption crop cut from the output frame is scored against the expected font and its
   nearest look-alikes (``typography.nearest_candidates``, clean-render IoU) with
   ``typography.identify_many`` (fill-mask IoU + per-glyph IoU, colours given).
2. A raw IoU means nothing on its own, so the expected font's IoU *ceiling* is measured under
   the output's own pipeline: known strings are rendered by libass through ffmpeg's
   ``subtitles`` filter exactly like ``shortkit.edit.render`` (same PostScript face name and
   ``Fontsize = size_px * (winAscent+winDescent)/unitsPerEm`` convention, fontsdir holding only
   that face, bt709 conversion) over the episode's own source footage (or the measured label-box
   colour), encoded with the x264 CRF/preset read from the output MP4's x264 SEI, decoded, and
   cropped like the QA crop.  ``typography.ceiling`` turns those samples into p10/noise/glyph
   statistics.
3. Verdicts are typography's: ``identical`` / ``similar`` / ``different`` / ``unmeasured``.  The QA
   row says ``same`` ONLY for ``identical``.

Ceilings are cached in ``warehouse/cache/qa/font_ceilings/`` per (font, EXACT size_px, crf) --
the key also carries the x264 preset, canvas width, fps, caption style class (outline / label box /
plain, colours) and the background behind the caption (the episode's footage, or the flat colour
measured around the caption), because each of those changes what the true font can reach.
Size is NOT bucketed: measured on test-pipeline-001 (Noto Sans CJK KR Black, outline 6/66, crf 18
veryfast, 24 libass samples per size on black) the same-font IoU p10 was 0.9607 / 0.9621 / 0.9739 /
0.9595 / 0.9663 / 0.9722 at 60 / 63 / 64.5 / 66 / 68 / 71 px -- it moves by ~0.01 between neighbouring
sizes (pixel-grid / hinting), so a 66 px caption compared with a 63 px ceiling was judged against the
wrong threshold (c_sit3: 0.963 vs p10 0.966 -> 'similar').
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np

SAMPLER = "shortkit.qa.font_id/libass-subtitles/7"   # /2: exact size_px, flat bg; /3: sampled at the QA rest delay;
#                                                      /4: every string cropped at each POOL_DELAYS_S delay, events
#                                                          start half a frame before their first frame (cs rounding);
#                                                      /5: rows carry their placement (``row_spec``);
#                                                      /6: x264 threads from the output SEI, TAIL_FRAMES after the last crop;
#                                                      /7: the caption's entrance motion (pop / fade) before the rest frames
CACHE_DIR = "warehouse/cache/qa/font_ceilings"
# Delays after the caption comes to rest (entrance motion over) at which the per-ROLE pooled font check takes output
# crops, and at which the ceiling samples its libass emulation.  The first one is the per-caption rest delay.  A static
# caption is re-encoded by x264 frame after frame (test-pipeline-001 c_sit3: IoU 0.9634 at t_rest, 0.9608 half a second
# later), so every output crop is compared with ceiling samples taken at the SAME delay.
POOL_DELAYS_S = (None, 0.40, 0.70, 1.00)      # None = CAPTION_REST_SETTLE_S
BOOTSTRAP_N = 4000
SIZE_BUCKETS = (14, 16, 18, 20, 22, 24, 27, 30, 33, 36, 40, 45, 50, 56, 63, 71, 80, 90, 100, 112, 125, 140, 160,
                180, 200, 225, 250)
CEIL_REPEATS = 4          # per string slot: 3 slots x 4 = 12 samples (6 left p10 / noise too uncertain, see ceiling_strings)
FRAMES_PER_SAMPLE = 3     # minimum frames a sample string is shown (see sample_frames)
# frames a ceiling string stays on screen after its last crop: the output caption keeps going, and x264 (b-frames 3,
# rc_lookahead 10 at veryfast) codes a frame looking that far ahead -- the next string must not appear inside that window
TAIL_FRAMES = 12


def delay_frames(fps: float) -> list[int]:
    """POOL_DELAYS_S in frames after the text comes to rest (ascending, distinct); [0] = the per-caption rest delay
    (CAPTION_REST_SETTLE_S, the delay at which QA measures each caption)."""
    from . import CAPTION_REST_SETTLE_S

    out: list[int] = []
    for d in POOL_DELAYS_S:
        k = max(1, int(round(float(CAPTION_REST_SETTLE_S if d is None else d) * float(fps))))
        if k not in out:
            out.append(k)
    return sorted(out)


def sample_frames(fps: float) -> tuple[int, int]:
    """(frames each ceiling string is shown, index of the per-caption rest frame): every string stays on screen
    until the last pooled delay (``delay_frames``) + TAIL_FRAMES; the per-caption crop is taken CAPTION_REST_SETTLE_S
    after the text appears -- the delay at which QA measures the output caption."""
    ds = delay_frames(fps)
    return max(FRAMES_PER_SAMPLE, ds[-1] + TAIL_FRAMES), ds[0]
N_NEAREST = 3
# x264 presets are identified by their subme value (unique per preset unless a tune overrides it)
SUBME_PRESET = {0: "ultrafast", 1: "superfast", 2: "veryfast", 4: "faster", 6: "fast", 7: "medium", 8: "slow",
                9: "slower", 10: "veryslow", 11: "placebo"}


def _canon(v) -> str:
    return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def size_bucket(size_px: float) -> int:
    """Nearest size of a ~11 % geometric ladder.  Display / grouping only: ceilings are measured at the
    caption's exact size (module doc: the ceiling does NOT change slowly with size)."""
    s = max(1.0, float(size_px))
    return min(SIZE_BUCKETS, key=lambda b: abs(math.log(b / s)))


# ----------------------------------------------------------------------------- encode settings
def x264_settings(mp4: str | os.PathLike, max_bytes: int = 8 << 20) -> dict | None:
    """Parse the x264 SEI ("x264 - core ... options: ...") of an MP4 -> {crf, preset, options}.
    None when the stream carries no x264 SEI (other encoder / stripped)."""
    with open(mp4, "rb") as fh:
        data = fh.read(max_bytes)
    i = data.find(b"x264 - core")
    if i < 0:
        return None
    j = data.find(b"\x00", i)
    txt = data[i:(j if j > 0 else i + 4096)].decode("latin-1", "replace")
    m = re.search(r"options:\s*(.*)$", txt, re.S)
    opts = {}
    for tok in (m.group(1) if m else "").split():
        if "=" in tok:
            k, v = tok.split("=", 1)
            opts[k] = v
    out = {"encoder_sei": txt.split(" - ")[0:2], "rc": opts.get("rc"), "crf": None, "preset": None,
           "options": {k: opts.get(k) for k in ("rc", "crf", "subme", "ref", "me", "trellis", "bframes", "keyint",
                                                "rc_lookahead", "threads") if k in opts}}
    try:
        out["crf"] = float(opts["crf"]) if opts.get("rc") == "crf" and "crf" in opts else None
    except ValueError:
        out["crf"] = None
    try:
        out["preset"] = SUBME_PRESET.get(int(opts["subme"])) if "subme" in opts else None
    except ValueError:
        out["preset"] = None
    return out


def encode_settings(ctx) -> dict:
    """Output encode settings for the ceiling (measured from the MP4's x264 SEI; cached on ctx)."""
    cache = ctx.options.setdefault("_font_id", {})
    if "encode" in cache:
        return cache["encode"]
    res: dict = {"codec": "h264", "crf": None, "preset": None, "source": None, "notes": []}
    vc = (getattr(ctx.info, "vcodec", None) or "").lower()
    if vc and vc != "h264":
        res.update(codec=vc, source=None)
        res["notes"].append(f"출력 코덱 {vc}: x264 설정을 읽을 수 없음")
    else:
        try:
            sei = x264_settings(ctx.mp4)
        except OSError as e:
            sei = None
            res["notes"].append(f"MP4 읽기 실패: {e}")
        if sei and sei.get("crf") is not None:
            res.update(crf=sei["crf"], preset=sei["preset"], source="output MP4 x264 SEI", x264=sei["options"])
            try:        # frame threads change x264's rate control / lookahead decisions: emulate the same count
                res["threads"] = int(sei["options"]["threads"]) if sei["options"].get("threads") else None
            except ValueError:
                res["threads"] = None
            if sei["preset"] is None:
                res["notes"].append(f"x264 subme={sei['options'].get('subme')} 로 프리셋을 특정하지 못함")
        elif sei:
            res["notes"].append(f"x264 rc={sei.get('rc')} (CRF 인코딩이 아님)")
        else:
            res["notes"].append("출력 MP4 에 x264 설정 기록(SEI)이 없음")
    cache["encode"] = res
    return res


# ----------------------------------------------------------------------------- libass samples
def _bg_strips(ctx, n: int, W: int, Hs: int, seed: int, color: tuple | None) -> tuple[list[np.ndarray], str]:
    if color is not None:
        a = np.empty((Hs, W, 3), np.uint8)
        a[:] = color
        return [a] * n, "color:#%02X%02X%02X" % tuple(color)
    from .. import paths
    from .probes_video import grab_window

    rng = np.random.default_rng(seed)
    clips = [c for c in ctx.resolved.clips if paths.absp(c.source_path).is_file()]
    out: list[np.ndarray] = []
    used = []
    tries = 0
    while clips and len(out) < n and tries < 8:
        tries += 1
        c = clips[int(rng.integers(len(clips)))]
        t = float(rng.uniform(c.src_in, max(c.src_in, c.src_out - 0.5)))
        try:
            _, frs = grab_window(paths.absp(c.source_path), t, (n - len(out)) / 30.0 + 0.2, width=W)
        except Exception:
            continue
        for f in frs:
            if f.shape[0] < Hs:
                continue
            y0 = (f.shape[0] - Hs) // 2
            out.append(np.ascontiguousarray(f[y0:y0 + Hs, :W]))
            if len(out) >= n:
                break
        used.append(f"{c.source_path}@{t:.2f}")
    if len(out) < n:
        g = np.full((Hs, W, 3), 96, np.uint8)
        out += [g] * (n - len(out))
        used.append("color:#606060(부족분)")
    return out, "video:" + ";".join(used[:4])


def _ass_doc(W: int, Hs: int, style: str, events: list[str]) -> str:
    # same Script Info flags as shortkit.edit.captions.AssDoc (PlayRes == LayoutRes == frame size)
    return ("[Script Info]\nScriptType: v4.00+\nPlayResX: %d\nPlayResY: %d\nLayoutResX: %d\nLayoutResY: %d\n"
            "WrapStyle: 2\nScaledBorderAndShadow: yes\nYCbCr Matrix: None\nKerning: yes\n\n[V4+ Styles]\n"
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, "
            "Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, "
            "MarginL, MarginR, MarginV, Encoding\n%s\n\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, "
            "MarginR, MarginV, Effect, Text\n%s\n") % (W, Hs, W, Hs, style, "\n".join(events))


def _stream(cmd: list[str], cwd: str, frames=None, frame_bytes: int = 0, keep: set[int] | None = None) -> dict:
    """Run ffmpeg feeding raw ``frames`` (iterable of arrays) on stdin and reading raw frames of ``frame_bytes``
    from stdout, keeping only the frame indices in ``keep`` -- so a long sample stream never sits in memory."""
    import threading

    proc = subprocess.Popen(cmd, cwd=cwd, stdin=subprocess.PIPE if frames is not None else subprocess.DEVNULL,
                            stdout=subprocess.PIPE if frame_bytes else subprocess.DEVNULL, stderr=subprocess.PIPE)
    err: list[bytes] = []
    werr: list[BaseException] = []

    def feed():
        try:
            for f in frames:
                proc.stdin.write(np.ascontiguousarray(f).tobytes())
        except (BrokenPipeError, OSError) as e:        # ffmpeg died: its stderr says why
            werr.append(e)
        finally:
            try:
                proc.stdin.close()
            except OSError:
                pass

    th_err = threading.Thread(target=lambda: err.append(proc.stderr.read()), daemon=True)
    th_err.start()
    th_in = threading.Thread(target=feed, daemon=True) if frames is not None else None
    if th_in is not None:
        th_in.start()
    got: dict[int, bytes] = {}
    if frame_bytes:
        i = 0
        while True:
            buf = proc.stdout.read(frame_bytes)
            if not buf or len(buf) < frame_bytes:
                break
            if keep is None or i in keep:
                got[i] = buf
            i += 1
    if th_in is not None:
        th_in.join()
    rc = proc.wait()
    th_err.join()
    if rc != 0:
        raise subprocess.CalledProcessError(rc, cmd, stderr=b"".join(err))
    return got


def ass_style(font: str, font_file: str | None, size: float, fill: tuple, outline: tuple | None,
              outline_px: float) -> tuple:
    """(face, ASS font name, ASS style line) exactly as the production renderer writes a caption style
    (``shortkit.edit.captions.resolve_font`` / ``style_line``: libass-matched face name, win-metric size, Bold flag)."""
    from ..edit import captions as capmod

    rf = capmod.resolve_font(font, font_file)
    face = rf.face
    name = getattr(rf, "ass_name", None) or face.ass_name
    hexc = lambda c: "#%02X%02X%02X" % tuple(int(v) for v in c)   # noqa: E731
    line = capmod.style_line("s", name, face.ass_fontsize(size), hexc(fill), hexc(outline or (0, 0, 0)),
                             "#000000", face.weight, outline_px if outline is not None else 0.0, 0.0)
    return face, name, line


def libass_samples(ctx, font: str, size: float, fill: tuple, outline: tuple | None, outline_px: float,
                   box: tuple | None, strings, crf: float, preset: str, fps: float, seed: int = 7,
                   font_file: str | None = None, bg: tuple | None = None, delays: list[int] | None = None,
                   threads: int | None = None, motion_in: dict | None = None):
    """typography.Sample list rendered like the production renderer (see module doc).
    Background: the label-box colour when ``box``, else the flat colour ``bg`` when given (caption over
    a flat canvas area), else strips of the episode's own source footage.
    Every string is shown for ``sample_frames(fps)[0]`` frames and cropped at each delay in ``delays`` (frames after
    it appears; default: the per-caption rest delay only); a sample's ``group`` ends in ``|d<delay>`` so repeats of the
    same string AT THE SAME DELAY share a group (the noise estimate)."""
    from ..edit import captions as capmod
    from ..reference import typography as ty
    from ..util.media import FFMPEG

    face, ass_name, style = ass_style(font, font_file, size, fill, outline, outline_px)
    W = int(ctx.canvas_w)
    k, k_at = sample_frames(fps)
    dls = sorted({int(d) for d in (delays or [k_at])})
    if dls[-1] > k - TAIL_FRAMES:
        raise ValueError(f"지연 {dls[-1]}프레임 + 꼬리 {TAIL_FRAMES}프레임이 표본 표시 길이 {k}프레임을 넘음")
    m_in, entry = entrance(motion_in, fps)
    k += m_in                  # the string enters like the caption, then rests; delays count from the rest frame
    Hs = int(math.ceil(size * 2.6 / 16.0)) * 16
    rng = np.random.default_rng(seed)
    specs = [(si, s, rep) for si, s in enumerate(strings) for rep in range(CEIL_REPEATS)]
    n = len(specs) * k
    evs = []
    for j, (_si, s, _rep) in enumerate(specs):
        x = W / 2 + rng.uniform(-40, 40) + rng.uniform(0, 1)
        y = Hs / 2 + rng.uniform(-6, 6) + rng.uniform(0, 1)
        # ASS times are centiseconds: start/end half a frame BEFORE the first/after-last frame so the rounding can
        # never push the text one frame late (frame j*k is the first frame showing string j)
        t0 = max(0.0, (j * k - 0.5) / fps)
        t1 = ((j + 1) * k - 0.5) / fps
        evs.append(f"Dialogue: 2,{capmod.ass_time(t0)},{capmod.ass_time(t1)},s,,0,0,0,,"
                   f"{{\\an5\\pos({x:.2f},{y:.2f}){entry}}}{s}")
    bgs, bg_desc = _bg_strips(ctx, n, W, Hs, seed, box if box is not None else bg)
    # plain canvas for locating the fill ink: far from the fill colour (dark fills on white)
    luma = 0.2126 * fill[0] + 0.7152 * fill[1] + 0.0722 * fill[2]
    black = np.full((Hs, W, 3), 0 if luma > 110 else 255, np.uint8)
    fb = W * Hs * 3
    loc_idx = {j * k + m_in + dls[0] for j in range(len(specs))}
    want = {j * k + m_in + d for j in range(len(specs)) for d in dls}
    with tempfile.TemporaryDirectory(prefix="sk_qa_font_") as td:
        tdp = Path(td)
        (tdp / "fonts").mkdir()
        os.symlink(face.path, tdp / "fonts" / Path(face.path).name)
        ass_txt = _ass_doc(W, Hs, style, evs)
        (tdp / "c.ass").write_text(ass_txt, encoding="utf-8")
        # the emulation is only valid if libass really draws the expected face (no substitution)
        chk = capmod.verify_libass_fonts(ass_txt, tdp / "fonts", {"s": face.postscript or ass_name})
        if not chk.get("ok"):
            raise RuntimeError(f"libass 가 기대 글꼴({ass_name})을 쓰지 않음: {chk.get('styles')}")
        base = [FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s", f"{W}x{Hs}", "-framerate", f"{fps:g}", "-i", "-"]
        # 1) lossless render on black: where the fill ink is (crop box, like the QA crop)
        ref = _stream(base + ["-vf", "subtitles=filename=c.ass:fontsdir=fonts", "-f", "rawvideo", "-pix_fmt", "rgb24",
                              "-"], td, frames=(black for _ in range(n)), frame_bytes=fb, keep=loc_idx)
        # 2) the output pipeline: subtitles -> bt709 yuv420p -> x264 at the output's CRF/preset -> decode
        _stream(base + ["-vf", "subtitles=filename=c.ass:fontsdir=fonts,"
                        "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
                        "-c:v", "libx264", "-preset", preset, "-crf", f"{crf:g}", "-pix_fmt", "yuv420p",
                        "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                        "-color_range", "tv", "-threads", str(int(threads or 2)), "enc.mp4"], td, frames=iter(bgs))
        del bgs
        dec = _stream([FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-i", "enc.mp4", "-f", "rawvideo",
                       "-pix_fmt", "rgb24", "-"], td, frame_bytes=fb, keep=want)
    img = lambda buf: np.frombuffer(buf, np.uint8).reshape(Hs, W, 3)   # noqa: E731
    fv = np.array(fill, np.int32)
    samples = []
    for j, (si, s, _rep) in enumerate(specs):
        at = j * k + m_in + dls[0]
        if at not in ref:
            continue
        m = np.sqrt(((img(ref[at]).astype(np.int32) - fv) ** 2).sum(axis=2)) < 80
        ys, xs = np.nonzero(m)
        if not len(xs):
            continue
        pad = 3 if box is not None else int(float(outline_px if outline is not None else 0) + 6)
        x0, y0 = max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad)
        x1, y1 = min(W, int(xs.max()) + 1 + pad), min(Hs, int(ys.max()) + 1 + pad)
        around = box if box is not None else outline
        for d in dls:
            mid = j * k + m_in + d
            if mid not in dec:
                continue
            sm = ty.Sample(crop=img(dec[mid])[y0:y1, x0:x1].copy(), text=s, size_px=float(size),
                           fill_rgb=tuple(fill), outline_rgb=None if around is None else tuple(around),
                           font=font, group=f"{si}:{s}|{size:g}|d{d}", style="box" if box is not None else
                           ("outline" if outline is not None else "plain"), canvas_size_px=float(size))
            sm.spec = j            # the placement (string, position, background) this crop was cut from
            samples.append(sm)
    return samples, bg_desc


def entrance(motion_in: dict | None, fps: float) -> tuple[int, str]:
    """(frames before the text is at rest, ASS override tags) of a caption's entrance motion, written the way the
    production renderer writes it (``shortkit.edit.captions.caption_events``: pop = \\fscx/\\fscy from scale_from to 100
    over dur_s, fade = \\fad(dur_s, 0)).  x264 codes the rest frame from the frame before it, so how the text got
    there (a 98 %-scaled glyph, a half-faded glyph, nothing) decides the quality of every later rest frame, which
    are skip copies of it.  A ceiling event starts half a frame before its first frame, so the text is at rest from
    frame ceil(dur_s * fps - 0.5) on -- the same count as the output caption (first frame -> start + dur_s)."""
    mi = motion_in or {}
    typ = mi.get("type") or "none"
    ms = int(round(float(mi.get("dur_s") or 0.0) * 1000))
    if typ not in ("pop", "fade") or ms <= 0:
        return 0, ""
    m_in = max(0, int(math.ceil(ms / 1000.0 * fps - 0.5)))
    if typ == "pop":
        pct = f"{float(mi.get('scale_from') or 1.0) * 100:g}"
        return m_in, f"\\fscx{pct}\\fscy{pct}\\t(0,{ms},\\fscx100\\fscy100)"
    return m_in, f"\\fad({ms},0)"


def sample_delay(sm) -> int | None:
    """The delay (frames after the text appeared) a ceiling sample was cropped at (from its group)."""
    m = re.search(r"\|d(\d+)$", str(getattr(sm, "group", "") or ""))
    return int(m.group(1)) if m else None


# ----------------------------------------------------------------------------- cache
def _cache_path(key: dict) -> Path:
    from .. import paths

    h = hashlib.sha256(_canon(key).encode()).hexdigest()[:24]
    return paths.absp(CACHE_DIR) / f"{h}.json"


def _read_cache(key: dict) -> dict | None:
    from ..util.jsonio import read_json

    p = _cache_path(key)
    d = read_json(p) if p.is_file() else None
    if isinstance(d, dict) and d.get("key") == json.loads(_canon(key)):
        return d
    return None


def _write_cache(key: dict, payload: dict) -> None:
    from ..util.jsonio import now_iso, write_json

    write_json(_cache_path(key), {"key": json.loads(_canon(key)), "measured_at": now_iso(), **payload})


def nearest_fonts(expected: str, k: int = N_NEAREST) -> list[str]:
    """The ``k`` candidate fonts that look most like ``expected`` (clean-render IoU; cached)."""
    from ..fonts import candidate_names
    from ..reference import typography as ty

    cands = sorted(set(candidate_names()))
    key = {"kind": "nearest", "font": expected, "candidates": cands, "k": k, "method": "typography.nearest_candidates"}
    hit = _read_cache(key)
    if hit is not None:
        return list(hit["nearest"])
    refs, _missing = ty.resolve_candidates(cands)
    near = ty.nearest_candidates(expected, refs, k=k)
    names = [n for n, _ in near]
    _write_cache(key, {"nearest": names, "scores": [[n, round(v, 4)] for n, v in near]})
    return names


def expected_ref(font: str, font_file: str | None = None):
    """typography.FontRef of the face the renderer uses (font_file wins over the name lookup)."""
    from .. import paths
    from ..reference import typography as ty

    if font_file:
        from ..edit.captions import resolve_font

        f = resolve_font(font, font_file).face
        return ty.FontRef(name=ty.font_ref(paths.absp(font_file), f.index).name, path=str(f.path), index=f.index)
    return ty.font_ref(font)


def _quant(c) -> tuple:
    """Measured colour quantised so near-identical backgrounds share a ceiling."""
    return tuple(int(min(255, max(0, round(float(v) / 8.0) * 8))) for v in c)


def ceiling_strings(text: str, slots: int = 3) -> list[str]:
    """The caption's own lines as the ceiling's sample strings (>= ``slots`` slots, each rendered
    CEIL_REPEATS times at jittered positions).  The IoU the true font reaches depends on the TEXT (small
    glyphs such as quote marks or dense syllables have relatively more edge): measured on test-pipeline-001
    c_dlg ("저기 봐, 들어온다!" in quotes, 62 px on black) the generic strings gave p10 0.977 while the
    caption's quote glyphs alone scored 0.89/0.91 -- a content effect, not a font difference."""
    lines = [ln for ln in (text or "").split("\n") if ln.strip()]
    if not lines:
        return []
    k = -(-slots // len(lines))
    return (lines * k)[:max(slots, len(lines))]


def ceiling_for(ctx, font: str, size_px: float, fill: tuple, outline: tuple | None, outline_px: float,
                box: tuple | None, font_file: str | None = None, bg: tuple | None = None,
                strings: list[str] | None = None, delays: list[int] | None = None,
                motion_in: dict | None = None) -> tuple[dict, dict, bool]:
    """(ceiling, conditions, from_cache) for ``font`` at the caption's exact ``size_px`` under the output's
    encode settings.  ``bg``: flat colour measured around a non-boxed caption (None = footage behind it);
    ``strings``: the sample strings (default: typography.DEFAULT_STRINGS[:3]; QA passes the caption's own
    lines, ``ceiling_strings``); ``delays``: crop delays in frames after the text appears (default
    ``delay_frames(fps)``).  The returned ceiling is the one at the FIRST delay (the per-caption rest delay);
    ``ceiling["by_delay"][str(d)]`` holds a full typography ceiling (rows, glyph, noise) for every delay d.
    ``motion_in``: the caption's entrance motion, reproduced before the rest frames (``entrance``; measured on
    test-coverage-001 c_sit1 / c_sit3 / c_rx it moves the ceiling p10 by -0.0025 / -0.0008 / -0.0004)."""
    from ..reference import typography as ty

    enc = encode_settings(ctx)
    if enc.get("crf") is None:
        raise LookupError("출력 인코딩 CRF 를 측정하지 못함: " + "; ".join(enc.get("notes") or []))
    preset = enc.get("preset")
    assumed = preset is None
    preset = preset or "medium"
    size = round(float(size_px), 1)
    strs = list(strings) if strings else list(ty.DEFAULT_STRINGS[:3])
    fr = expected_ref(font, font_file)
    if box is not None:     # measured label-box colour: quantised so near-identical boxes share a ceiling
        box = _quant(box)
        bg = None
    elif bg is not None:
        bg = _quant(bg)
    frac = round(float(outline_px) / float(size_px), 3) if (outline is not None and size_px) else 0.0
    style = {"kind": "box" if box is not None else ("outline" if outline is not None else "plain"),
             "fill": list(fill), "outline": list(outline) if outline is not None else None, "outline_frac": frac,
             "box": list(box) if box is not None else None, "bg": list(bg) if bg is not None else "footage"}
    fps = round(float(ctx.fps), 3)
    dls = sorted({int(d) for d in (delays or delay_frames(fps))})
    _face, _name, ass_line = ass_style(font, font_file, size, tuple(fill), outline, frac * size)
    mi = motion_in or {}
    motion = ({"type": mi.get("type"), "dur_s": round(float(mi.get("dur_s") or 0.0), 3),
               "scale_from": round(float(mi.get("scale_from") or 1.0), 3) if mi.get("type") == "pop" else None}
              if entrance(mi, fps)[0] > 0 else None)
    key = {"kind": "ceiling", "sampler": SAMPLER, "font": fr.name, "face": [Path(fr.path).name, fr.index],
           "ass_style": ass_line, "size_px": size, "crf": enc["crf"], "preset": preset, "codec": "h264",
           "width": int(ctx.canvas_w), "fps": fps, "style": style, "strings": strs, "repeats": CEIL_REPEATS,
           "frames_per_sample": sample_frames(fps)[0], "delays": dls, "threads": enc.get("threads") or 2,
           "motion_in": motion}
    cond = ty.Conditions(canvas=(int(ctx.canvas_w), int(ctx.canvas_h)), ref_resolution=(int(ctx.canvas_w), int(ctx.canvas_h)),
                         codec="h264", crf=float(enc["crf"]), x264_preset=preset, frames_per_sample=sample_frames(fps)[0],
                         fps=fps, background=("color:#%02X%02X%02X" % tuple(box if box is not None else bg)
                                              if (box is not None or bg is not None) else "video"),
                         renderer="libass(ffmpeg subtitles filter, shortkit.edit.render 규약)", assumed=assumed,
                         source=f"{enc.get('source')}" + (" / x264 프리셋 특정 못 함 → medium 가정" if assumed else ""))
    hit = _read_cache(key)
    if hit is not None:
        return hit["ceiling"], cond.to_dict(), True
    samples, bg_desc = libass_samples(ctx, font, size, fill, outline, frac * size, box, strs,
                                      float(enc["crf"]), preset, fps, font_file=font_file, bg=bg, delays=dls,
                                      threads=enc.get("threads"), motion_in=motion)
    by: dict[str, dict] = {}
    for d in dls:
        sub = [sm for sm in samples if sample_delay(sm) == d]
        if len(sub) < 4:
            continue
        c = ty.ceiling(fr, cond, samples=sub, color_mode="given", keep_rows=True)
        c["background"] = bg_desc
        c["delay_frames"] = d
        c["row_spec"] = [getattr(sm, "spec", None) for sm in sub]     # rows[i] was cut from placement row_spec[i]
        by[str(d)] = c
    if str(dls[0]) not in by:
        raise RuntimeError(f"천장 실험 샘플 부족({len(samples)}개)")
    top = {**by[str(dls[0])], "by_delay": by}
    _write_cache(key, {"ceiling": top, "conditions": cond.to_dict()})
    return top, cond.to_dict(), False


# ----------------------------------------------------------------------------- identification
def _same(a: str | None, b: str | None) -> bool:
    return str(a or "").replace(" ", "").lower() == str(b or "").replace(" ", "").lower()


def identify_caption_font(ctx, cap, crop: np.ndarray, text: str, fill: tuple, around: tuple | None,
                          boxed: bool, bg: tuple | None = None) -> dict:
    """typography.identify_many on one output crop; verdict of the EXPECTED font.  ``bg``: flat colour
    measured behind a non-boxed caption (the ceiling is then rendered over that colour)."""
    from ..reference import typography as ty

    font_file = getattr(cap, "font_file", None)
    exp_ref = expected_ref(cap.font_name, font_file)
    outline = None if boxed else (around if (cap.outline_px and around is not None) else None)
    box = around if boxed else None
    ceil, cond, cached = ceiling_for(ctx, cap.font_name, float(cap.size_px), tuple(fill), outline,
                                     float(cap.outline_px or 0.0), box, font_file=font_file, bg=bg,
                                     strings=ceiling_strings(text) or None, motion_in=getattr(cap, "motion_in", None))
    try:
        others = nearest_fonts(cap.font_name)
    except Exception as e:  # the look-alike list is a strengthening, never a reason to skip
        others = []
        near_err = f"{type(e).__name__}: {e}"[:200]
    else:
        near_err = None
    cands = [exp_ref] + [n for n in others if not _same(n, exp_ref.name)]
    items = [{"crop": crop, "text": text, "size_hint_px": float(cap.size_px), "fill_rgb": tuple(fill),
              "outline_rgb": None if around is None else tuple(around), "id": cap.id}]
    res = ty.identify_many(items, cands, {exp_ref.name: ceil}, color_mode="given")
    ranked = res.get("ranked") or []
    er = next((r for r in ranked if _same(r["font"], exp_ref.name)), None)
    out = {"method": "typography.identify_many + 출력 인코딩 조건의 천장(ceiling)", "expected": cap.font_name,
           "expected_canonical": exp_ref.name, "candidates": [c.name if hasattr(c, "name") else c for c in cands],
           "conditions": cond, "ceiling_cached": cached,
           "ceiling": {k: ceil.get(k) for k in ("n", "p10", "p50", "p90", "n_failed")} |
           {"noise_p90": (ceil.get("noise") or {}).get("p90"), "glyph_p10": (ceil.get("glyph") or {}).get("p10"),
            "size_px": round(float(cap.size_px), 1), "background": ceil.get("background")},
           "ranked": [{k: r.get(k) for k in ("rank", "font", "iou", "margin", "verdict", "glyph_pass")} for r in ranked],
           "top": res.get("top"), "top_verdict": res.get("top_verdict"), "summary": res.get("summary"),
           "failed_crops": res.get("failed_crops"), "missing_candidates": res.get("missing_candidates")}
    if near_err:
        out["nearest_error"] = near_err
    if er is None:
        out.update(status="unmeasured", verdict="unmeasured",
                   reason="기대 글꼴 점수를 계산하지 못함: " + "; ".join(f.get("reason", "") for f in res.get("failed_crops") or []))
        return out
    out.update(status="measured", verdict=er["verdict"], verdict_ko=ty.VERDICT_KO.get(er["verdict"]),
               iou_expected=er["iou"], margin=er["margin"], reasons=er.get("reasons"),
               glyph_below_floor=er.get("glyph_below_floor"))
    return out


# ----------------------------------------------------------------------------- per-role pooled identification
def _noise_spreads(ceil: dict) -> list[float]:
    """Spread (max - min) of the self IoU across repeats of one string at one delay (typography.ceiling's noise)."""
    groups: dict[str, list[float]] = {}
    for r in ceil.get("rows") or []:
        if r.get("iou") is not None:
            groups.setdefault(str(r.get("group")), []).append(float(r["iou"]))
    return [max(v) - min(v) for v in groups.values() if len(v) > 1]


def placement_matrix(ceil: dict, delays: list[int]) -> np.ndarray | None:
    """Ceiling IoU per placement (rows) at each of ``delays`` (columns): the crops the ceiling cut from ONE rendered
    string at those delays.  Placements missing any of the delays are dropped; None when nothing is left."""
    by = ceil.get("by_delay") or {}
    cols = []
    for d in delays:
        c = by.get(str(d)) or {}
        spec, rows = c.get("row_spec") or [], c.get("rows") or []
        if len(spec) != len(rows):
            return None
        cols.append({sp: r.get("iou") for sp, r in zip(spec, rows) if sp is not None})
    common = sorted(set.intersection(*(set(k for k, v in col.items() if v is not None) for col in cols))) if cols else []
    if not common:
        return None
    return np.array([[float(col[sp]) for col in cols] for sp in common], float)


def bootstrap_median(groups: list[np.ndarray], n_boot: int = BOOTSTRAP_N, seed: int = 7) -> np.ndarray:
    """Distribution of the MEDIAN over the pooled crops if every caption had been drawn in the true font.

    ``groups``: one placement matrix per caption (``placement_matrix``: ceiling placements x that caption's crop
    delays).  The rest frames of one caption are the SAME placement of the text re-encoded frame after frame -- on
    test-coverage-001 their IoUs agree to 3 decimals across 0.12-1.0 s -- so they are not independent draws: each
    replicate draws ONE placement per caption, reads it at that caption's delays, and takes the median of all."""
    rng = np.random.default_rng(seed)
    parts = [g[rng.integers(0, g.shape[0], size=n_boot)] for g in groups]
    return np.median(np.concatenate(parts, axis=1), axis=1)


def identify_role_font(ctx, role: str, entries: list[dict]) -> dict:
    """Font of one caption ROLE pooled over every crop of every caption of that role (several rest frames each).

    Font identity is a property of the role style (every caption of a role uses one face), so the per-caption
    single-crop verdict is noisy evidence of one question.  ``entries``: one per caption ``{cap, text, fill, around,
    boxed, bg, crops: [{crop, delay, t}]}`` (``delay`` = frames after the caption came to rest; only delays of
    ``delay_frames(fps)`` are used).  Rules (typography's, applied to the pool):

    * score  = median over all pooled crops of the expected font's IoU (``typography.score_crops``: fill-mask IoU +
      per-glyph IoU, colours given); the same crops are scored against the nearest look-alike fonts
    * ceiling = the distribution of the median of the SAME crops had they been drawn in the true font, bootstrapped
      from the ceiling samples of each caption (``ceiling_for``: exact size, the caption's own text, the background
      really behind it, the output's CRF/preset): per caption one ceiling placement, read at that caption's crop
      delays (a caption's rest frames are one placement re-encoded, not independent crops -- ``bootstrap_median``);
      its p10 replaces the single-crop p10
    * noise (margin rule) = p90 of the self-IoU spread across repeats, pooled over those ceilings (unchanged rule)
    * per-glyph rule unchanged: >= GLYPH_PASS_SHARE of the pooled glyphs reach their own ceiling's glyph p10 and
      none falls below its own ceiling's outlier fence
    * verdict = ``typography._verdict``: identical / similar / different / unmeasured (row: same only for identical)
    * another face ranked first by more than the noise gets the SAME rules with its own ceilings; if that face is
      'identical', the output is positively another font and the planned font's verdict is 'different' (measured on
      a synthetic render drawn in Pretendard Black where the plan says Noto Sans CJK KR Black: planned 0.911 < p10 0.936
      but >= p10 - noise, so the IoU rule alone said 'similar'; Pretendard Black led by 0.061 > noise 0.032)
    """
    from ..reference import typography as ty
    from ..util.stats import pstats

    fps = float(ctx.fps)
    dls = delay_frames(fps)
    first = entries[0]["cap"]
    font_file = getattr(first, "font_file", None)
    exp_ref = expected_ref(first.font_name, font_file)
    out: dict = {"method": "역할 단위 합동 판정: 모든 자막의 여러 정지 프레임 crop 의 기대 글꼴 IoU 중앙값 vs 같은 개수 crop 중앙값의 "
                           "천장(부트스트랩, 자막별 문구·정확한 크기·실제 배경·같은 지연)", "role": role,
           "expected": first.font_name, "expected_canonical": exp_ref.name, "delays_frames": dls,
           "captions": [e["cap"].id for e in entries]}
    items, crop_ceil, crop_meta, notes = [], {}, [], []
    cap_ceil: dict[str, dict] = {}
    crop_cap: dict[str, str] = {}
    crop_delay: dict[str, int] = {}
    cond0 = None
    for e in entries:
        cap = e["cap"]
        outline = None if e["boxed"] else (e["around"] if (cap.outline_px and e["around"] is not None) else None)
        box = e["around"] if e["boxed"] else None
        try:
            ceil, cond, cached = ceiling_for(ctx, cap.font_name, float(cap.size_px), tuple(e["fill"]), outline,
                                             float(cap.outline_px or 0.0), box, font_file=getattr(cap, "font_file", None),
                                             bg=e.get("bg"), strings=ceiling_strings(e["text"]) or None, delays=dls,
                                             motion_in=getattr(cap, "motion_in", None))
        except Exception as ex:
            notes.append(f"{cap.id}: 천장 실험 실패 {type(ex).__name__}: {ex}"[:200])
            continue
        cond0 = cond0 or cond
        cap_ceil[cap.id] = ceil
        by = ceil.get("by_delay") or {}
        for c in e["crops"]:
            cd = by.get(str(c["delay"]))
            if not cd or not cd.get("n"):
                notes.append(f"{cap.id}@{c['delay']}: 이 지연의 천장 없음")
                continue
            iid = f"{cap.id}@{c['delay']}"
            items.append({"crop": c["crop"], "text": e["text"], "size_hint_px": float(cap.size_px),
                          "fill_rgb": tuple(e["fill"]), "outline_rgb": None if e["around"] is None else tuple(e["around"]),
                          "id": iid})
            crop_ceil[iid] = cd
            crop_cap[iid], crop_delay[iid] = cap.id, int(c["delay"])
            crop_meta.append({"id": iid, "caption": cap.id, "delay_frames": c["delay"], "t": c.get("t"),
                              "ceiling_cached": cached})
    out["conditions"] = cond0
    if notes:
        out["notes"] = notes
    if not items:
        out.update(status="unmeasured", verdict="unmeasured", reason="합동 판정에 쓸 crop 이 없음 "
                   "(정지 프레임을 얻지 못했거나 천장 실험 실패)")
        return out
    try:
        others = nearest_fonts(first.font_name)
    except Exception as ex:  # the look-alike list is a strengthening, never a reason to skip
        others = []
        out["nearest_error"] = f"{type(ex).__name__}: {ex}"[:200]
    cands = [exp_ref] + [n for n in others if not _same(n, exp_ref.name)]
    out["candidates"] = [c.name if hasattr(c, "name") else c for c in cands]
    per, missing, failed = ty.score_crops(items, cands, "given")
    out["missing_candidates"], out["failed_crops"] = missing, failed
    exp_rows = next((rows for n, rows in per.items() if _same(n, exp_ref.name)), None) or []
    if not exp_rows:
        out.update(status="unmeasured", verdict="unmeasured",
                   reason="기대 글꼴 점수를 계산하지 못함: " + "; ".join(f.get("reason", "") for f in failed or []))
        return out
    agg = {n: float(np.median([r["iou"] for r in rows])) for n, rows in per.items() if rows}
    exp_name = next(n for n in agg if _same(n, exp_ref.name))
    others_agg = {n: v for n, v in agg.items() if n != exp_name}
    runner = max(others_agg, key=others_agg.get) if others_agg else None
    margin = agg[exp_name] - (others_agg[runner] if runner else 0.0)
    is_top = all(agg[exp_name] >= v for v in others_agg.values())
    pv = _pooled_verdict(exp_rows, cap_ceil, crop_cap, crop_delay, is_top, margin)
    if pv.get("error"):
        out.update(status="unmeasured", verdict="unmeasured", reason=pv["error"])
        return out
    verdict, reasons, bst, noise, gshare, gpass, weak, gsz = (pv[k] for k in ("verdict", "reasons", "bst", "noise",
                                                                          "gshare", "gpass", "weak", "gsz"))
    # another face ranked first beyond the noise: apply the SAME rules to it with its own ceilings (same captions,
    # size, background, entrance, encode).  If it is 'identical', the output is positively that other face -> the
    # planned font is 'different' (typography: only an identical verdict names a font).
    top = max(agg, key=agg.get)
    alt = None
    if not _same(top, exp_name) and (agg[top] - agg[exp_name]) > (noise.get("p90") or 0.0):
        alt = {"font": top, "iou": round(agg[top], 4), "lead_over_expected": round(agg[top] - agg[exp_name], 4)}
        try:
            alt_ceil = {}
            for e in entries:
                cap = e["cap"]
                if cap.id not in cap_ceil:
                    continue
                outline = None if e["boxed"] else (e["around"] if (cap.outline_px and e["around"] is not None) else None)
                alt_ceil[cap.id] = ceiling_for(ctx, top, float(cap.size_px), tuple(e["fill"]), outline,
                                               float(cap.outline_px or 0.0), e["around"] if e["boxed"] else None,
                                               bg=e.get("bg"), strings=ceiling_strings(e["text"]) or None, delays=dls,
                                               motion_in=getattr(cap, "motion_in", None))[0]
            second = max(v for n, v in agg.items() if n != top)
            apv = _pooled_verdict(per[top], alt_ceil, crop_cap, crop_delay, True, agg[top] - second)
            alt.update(verdict=apv.get("verdict", "unmeasured"), reasons=apv.get("reasons") or [apv.get("error")],
                       ceiling_p10=(apv.get("bst") or {}).get("p10"))
        except Exception as ex:
            alt.update(verdict="unmeasured", reasons=[f"다른 글꼴 천장 실험 실패: {type(ex).__name__}: {ex}"[:200]])
        if alt.get("verdict") == "identical":
            verdict = "different"
            reasons = [f"출력 글꼴이 다른 글꼴 {top} 로 '동일' 판정됨(그 글꼴의 천장·차순위 대비 차이·글자별 검사 통과): "
                       + "; ".join(alt["reasons"])] + reasons
    per_crop_iou = {x["id"]: round(float(x["iou"]), 4) for x in exp_rows}
    for m in crop_meta:
        m["iou_expected"] = per_crop_iou.get(m["id"])
    out.update(status="measured", verdict=verdict, verdict_ko=ty.VERDICT_KO.get(verdict), reasons=reasons,
               n_crops=len(exp_rows), n_captions=len({m["caption"] for m in crop_meta if m.get("iou_expected") is not None}),
               iou_expected=round(agg[exp_name], 4), iou_stats=pstats([x["iou"] for x in exp_rows], 4),
               margin=round(margin, 4), runner_up=runner, top=max(agg, key=agg.get),
               ranked=[{"font": n, "iou": round(v, 4), "n": len(per[n])} for n, v in sorted(agg.items(), key=lambda kv: -kv[1])],
               ceiling={"method": f"중앙값 부트스트랩 {BOOTSTRAP_N}회(자막마다 같은 문구·크기·배경의 천장 배치 1개를 뽑아 "
                                  "그 자막 crop 과 같은 지연에서 읽음)",
                        "n_crops": len(exp_rows), "p10": bst["p10"], "p50": bst["p50"], "p90": bst["p90"],
                        "noise_p90": noise.get("p90"), "noise_n": noise.get("n"),
                        "placements_per_caption": gsz, "unit": "자막 1개 = 배치 1개(여러 지연 프레임은 같은 배치)"},
               glyph={"share_ge_own_p10": None if gshare is None else round(gshare, 3), "n": pv["n_glyphs"],
                      "pass": gpass, "below_fence": weak[:20]},
               crops=crop_meta, other_font=alt)
    return out


def _pooled_verdict(rows: list[dict], cap_ceil: dict, crop_cap: dict, crop_delay: dict, is_top: bool,
                    margin: float) -> dict:
    """typography's verdict for ONE candidate font over pooled crops (``rows`` = its score_crops rows): the pooled
    median IoU against the p10 of the bootstrapped median (``bootstrap_median``: one ceiling placement per caption at
    that caption's crop delays), margin over the runner-up vs the pooled noise p90, per-glyph rule against each
    crop's own ceiling.  ``cap_ceil``: caption id -> ``ceiling_for`` result of THIS font."""
    from ..reference import typography as ty
    from ..util.stats import pstats

    groups, gsz, by_crop = [], [], {}
    for cid in dict.fromkeys(crop_cap[x["id"]] for x in rows):
        dl = [crop_delay[x["id"]] for x in rows if crop_cap[x["id"]] == cid]
        mtx = placement_matrix(cap_ceil.get(cid) or {}, dl)
        if mtx is None:
            return {"error": f"{cid}: 천장 표본을 배치(placement)별로 읽을 수 없음 — 합동 천장 계산 불가"}
        groups.append(mtx)
        gsz.append(int(mtx.shape[0]))
        for x in rows:
            if crop_cap[x["id"]] == cid:
                by_crop[x["id"]] = (cap_ceil[cid].get("by_delay") or {}).get(str(crop_delay[x["id"]])) or {}
    boot = bootstrap_median(groups)
    bst = pstats(boot.tolist(), 4)
    noise = pstats([v for iid in by_crop for v in _noise_spreads(by_crop[iid])], 4)
    gvals, weak = [], []
    for x in rows:
        gst = by_crop[x["id"]].get("glyph") or {}
        gp10, fence = gst.get("p10"), ty.glyph_floor(gst)
        for g in x.get("glyphs") or []:
            if gp10 is not None:
                gvals.append(g["iou"] >= gp10)
            if fence is not None and g["iou"] < fence:
                weak.append({"crop": x["id"], "ch": g["ch"], "iou": round(float(g["iou"]), 3), "fence": fence})
    gshare = float(np.mean(gvals)) if gvals else None
    gpass = None if gshare is None else (gshare >= ty.GLYPH_PASS_SHARE and not weak)
    iou = float(np.median([x["iou"] for x in rows]))
    verdict, reasons = ty._verdict(iou, is_top, margin, gpass, {"n": bst["n"], "p10": bst["p10"],
                                                                "noise": {"p90": noise.get("p90")}})
    if weak:
        reasons.append("글자별 하한보다 나쁜 글자: " + ", ".join(f"{w['ch']}({w['iou']:.2f}<{w['fence']:.2f})"
                                                        for w in weak[:6]) + " — 다른 글꼴이거나 문구 오류일 수 있음")
    return {"verdict": verdict, "reasons": reasons, "bst": bst, "noise": noise, "gshare": gshare, "gpass": gpass,
            "weak": weak, "gsz": gsz, "n_glyphs": len(gvals)}


# ----------------------------------------------------------------------------- exact-position re-render check
# The strongest font evidence the output allows: re-render the caption EXACTLY as production did -- the episode's own
# ASS events (position, \\move / \\fad / \\t motion, highlight markup) with the caption's style naming the PLANNED face
# (the plan's font_name, never simply the face the ASS on disk names), libass through ffmpeg's subtitles filter over the
# episode's own composited frames (shortkit.edit.render.Compositor), bt709 conversion, x264 at the CRF / preset /
# threads read from the output's SEI, starting at frame 0 like the production encode -- and compare the MP4 crop with
# that re-render and with re-renders in the top alternative faces at the same position.
# Measured: re-renders started at frame 0 reproduced the MP4 crops bit for bit (MAE 0.000; test-pipeline-001 c_desc,
# test-coverage-001 c_rx), while a re-render started at the key frame before the caption did NOT (test-coverage-001
# c_rx: MAE 1.13 from frame 250 -- x264 carries state across key frames); the alternatives were 7-66 MAE away.
# The re-encode noise is measured by the same planned render started at other frames (EXACT_MISALIGNED_STARTS: a
# different GOP phase): how far a re-encode of the SAME picture can land.
#
# Verdict per caption:  identical  = the planned face reproduces the MP4 within the re-encode noise (MAE <= noise)
#                                    AND every alternative is worse by more than the noise
#                       best_not_reproduced = the planned face is closer than every alternative by more than the noise
#                                    but its re-render does not reproduce the MP4 (MAE > noise: the picture behind the
#                                    caption was not made by this pipeline, e.g. a synthetic test render) -> counts as
#                                    'identical' for the role only when the pooled statistics also say identical
#                       different  = an alternative face reproduces the MP4 better than the planned face by more than
#                                    the noise
#                       not_reproduced = none of the above (no font verdict from this check)
EXACT_MAX_CAPTIONS_PER_ROLE = 4
EXACT_MAX_CROPS = 4
EXACT_TAIL_FRAMES = 24            # frames after the last crop: > x264 rc_lookahead (10 at veryfast) + b-frames
EXACT_MISALIGNED_STARTS = (1, 3)  # planned re-renders started off frame 0 (another GOP phase): the re-encode noise
EXACT_PARALLEL = 8                # x264 re-encodes fed by one Compositor pass (else: frames on disk, batches)


def mp4_keyframes(ctx) -> list[int]:
    """Frame indices of the key frames of the output MP4 (ffprobe), cached on ctx."""
    cache = ctx.options.setdefault("_font_id", {})
    if "keyframes" in cache:
        return cache["keyframes"]
    from ..util.media import FFPROBE

    out = subprocess.run([FFPROBE, "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey", "-show_entries",
                          "frame=pts_time", "-of", "csv=p=0", str(ctx.mp4)], capture_output=True, text=True, timeout=120)
    fps = float(ctx.fps)
    ks = sorted({int(round(float(x.strip().rstrip(",")) * fps)) for x in out.stdout.splitlines()
                 if x.strip().rstrip(",") not in ("", "N/A")})
    cache["keyframes"] = ks
    return ks


def _event_matches(line: str, cap) -> str | None:
    """The style name of this ``Dialogue:`` line if it is a TEXT event of ``cap`` (same start, end and line text; the
    style is whatever the renderer named -- the role in production), else None.  Box drawings (\\p1..) are not text."""
    from ..edit import captions as capmod

    f = line.split(",", 9)
    if len(f) < 10:
        return None
    if f[1] != capmod.ass_time(cap.start) or f[2] != capmod.ass_time(cap.end):
        return None
    if re.search(r"\\p[1-9]", f[9]):
        return None
    body = re.sub(r"\{[^}]*\}", "", f[9])
    lines = [str(ln) for ln in (cap.lines or str(cap.text).split("\n")) if str(ln).strip()]
    return f[3] if any(body == ln for ln in lines) else None


def alt_face_ass(ass_txt: str, caps: list, size_px: float, alt, prefix: str = "qaalt_") -> tuple[str, dict]:
    """The production ASS with the text events of ``caps`` switched to copies of their styles that name ``alt`` (a
    captions.ResolvedFont) -- libass-matched name, win-metric font size for the same size_px, Bold flag from the face
    weight; everything else (colours, outline, alignment, the events' position / motion tags) unchanged.
    -> (text, {cloned style name: number of events switched})."""
    from ..edit import captions as capmod

    head, sep, events = ass_txt.partition("[Events]")
    rows = capmod._style_rows(head)
    clones: dict[str, str] = {}
    out, counts = [], {}
    for ln in events.split("\n"):
        if ln.startswith("Dialogue:"):
            st = next((x for x in (_event_matches(ln, c) for c in caps) if x), None)
            if st and st in rows:
                name = f"{prefix}{st}"
                if name not in clones:
                    parts = list(rows[st])
                    parts[0], parts[1] = name, alt.ass_name
                    parts[2] = capmod._f(alt.face.ass_fontsize(float(size_px)))
                    parts[7] = str(capmod.ass_bold_flag(alt.face.weight))
                    clones[name] = "Style: " + ",".join(parts)
                f = ln.split(",", 9)
                f[3] = name
                ln = ",".join(f)
                counts[name] = counts.get(name, 0) + 1
        out.append(ln)
    head2 = head.rstrip("\n") + "\n" + "\n".join(clones.values()) + "\n\n"
    return head2 + sep + "\n".join(out), counts


def _decode_indices(path, idxs: set[int], first_index: int, fps: float, W: int, H: int) -> dict[int, np.ndarray]:
    """Frames ``idxs`` (absolute indices) of a re-render whose first frame is absolute frame ``first_index``."""
    from ..util.media import FFMPEG

    want = {i - first_index for i in idxs if i >= first_index}
    if not want:
        return {}
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-i", str(path), "-frames:v", str(max(want) + 1),
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    got = _stream(cmd, "/", frame_bytes=W * H * 3, keep=want)
    return {i + first_index: np.frombuffer(buf, np.uint8).reshape(H, W, 3) for i, buf in got.items()}


def _decode_mp4_frames(ctx, idxs: set[int], start: int) -> dict[int, np.ndarray]:
    """Frames of the OUTPUT MP4 at ``idxs`` decoded from key frame ``start`` (accurate seek)."""
    from ..util.media import FFMPEG

    W, H, fps = int(ctx.info.width), int(ctx.info.height), float(ctx.fps)
    cmd = [FFMPEG, "-hide_banner", "-nostdin", "-v", "error"]
    if start > 0:
        cmd += ["-ss", f"{(start - 0.5) / fps:.6f}"]
    cmd += ["-i", str(ctx.mp4), "-frames:v", str(max(idxs) - start + 1), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    got = _stream(cmd, "/", frame_bytes=W * H * 3, keep={i - start for i in idxs})
    return {i + start: np.frombuffer(buf, np.uint8).reshape(H, W, 3) for i, buf in got.items()}


def _crop_box(cap, W: int, H: int) -> tuple[int, int, int, int]:
    pad = max(8.0, 0.25 * float(cap.bbox.h))
    x0, y0 = max(0, int(cap.bbox.x - pad)), max(0, int(cap.bbox.y - pad))
    x1, y1 = min(W, int(math.ceil(cap.bbox.x + cap.bbox.w + pad))), min(H, int(math.ceil(cap.bbox.y + cap.bbox.h + pad)))
    return x0, y0, x1, y1


def _mae(a: np.ndarray, b: np.ndarray, box) -> float:
    x0, y0, x1, y1 = box
    return float(np.abs(a[y0:y1, x0:x1].astype(np.int16) - b[y0:y1, x0:x1].astype(np.int16)).mean())


def caption_crop_frames(ctx, cap) -> list[int]:
    """Frame indices where a caption is at rest (after its entrance motion), at the pooled delays."""
    fps = float(ctx.fps)
    mi = cap.motion_in or {}
    dur_in = float(mi.get("dur_s") or 0.0) if (mi.get("type") or "none") != "none" else 0.0
    n_rest = int(math.ceil((float(cap.start) + dur_in) * fps - 1e-6))
    n_last = int(math.ceil(float(cap.end) * fps - 1e-6)) - 1
    n_total = int(round(float(ctx.info.duration) * fps))
    out = [n_rest + d for d in delay_frames(fps) if n_rest + d < min(n_last, n_total - 1)]
    return out[:EXACT_MAX_CROPS]


def exact_render_checks(ctx, role_caps: dict[str, list], role_alts: dict[str, list[str]]) -> dict:
    """Exact-position re-render check for the captions in ``role_caps`` ({role: [caption, ...]}) against the top
    alternative faces ``role_alts`` ({role: [font name, ...]}).  -> {"captions": {caption id: result}, "notes": [...]}.
    One Compositor pass from frame 0 (where the production encode started) feeds every re-encode: the planned face from
    frame 0, the planned face from EXACT_MISALIGNED_STARTS (the re-encode noise), and one layer per alternative rank
    (``_alt_layers``)."""
    from .. import paths
    from ..edit import captions as capmod

    res: dict = {"captions": {}, "notes": [], "method": "production ASS 이벤트 그대로(위치·모션)에 계획 글꼴, libass→bt709→x264"
                                                        "(출력 SEI 의 CRF·프리셋·스레드), 제작처럼 0 프레임부터 다시 그린 것 vs 출력 crop"}
    r = ctx.resolved
    enc = encode_settings(ctx)
    if enc.get("crf") is None or enc.get("preset") is None:
        res["error"] = "출력 인코딩 설정(CRF·프리셋)을 SEI 에서 읽지 못함: " + "; ".join(enc.get("notes") or [])
        return res
    ass_p = paths.absp(r.ass_path) if r.ass_path else None
    fonts_dir = paths.absp(r.fonts_dir) if r.fonts_dir else paths.episode_dir(ctx.episode_id) / "build" / "fonts"
    if ass_p is None or not ass_p.is_file() or not fonts_dir.is_dir():
        res["error"] = f"렌더에 쓴 ASS/글꼴 폴더 없음: {r.ass_path}, {r.fonts_dir or paths.relp(fonts_dir)}"
        return res
    ass_txt = ass_p.read_text(encoding="utf-8")
    W, H, fps = int(ctx.canvas_w), int(ctx.canvas_h), float(ctx.fps)
    n_total = int(round(float(ctx.info.duration) * fps))
    # alternative faces (resolved once)
    alts: dict[str, list] = {}
    planned_rf: dict[str, object] = {}
    for role, caps in role_caps.items():
        try:
            planned_rf[role] = capmod.resolve_font(caps[0].font_name, getattr(caps[0], "font_file", None))
        except Exception as e:
            res["notes"].append(f"{role}: 계획 글꼴 {caps[0].font_name} 을 찾지 못함: {type(e).__name__}: {e}"[:200])
    for role, names in role_alts.items():
        got = []
        planned = set()
        for c in role_caps.get(role) or []:
            try:
                f = capmod.resolve_font(c.font_name, getattr(c, "font_file", None)).face
                planned.add((str(Path(f.path).resolve()), int(f.index)))
            except Exception:
                pass
        for nm in names:
            try:
                rf = capmod.resolve_font(nm)
            except Exception as e:  # a missing alternative is recorded, never replaced by another face
                res["notes"].append(f"대안 글꼴 {nm} 을 찾지 못함: {type(e).__name__}: {e}"[:200])
                continue
            if (str(Path(rf.face.path).resolve()), int(rf.face.index)) in planned:
                continue                     # the planned face itself is not an alternative
            got.append((nm, rf))
        alts[role] = got
    jobs = []
    for role, caps in role_caps.items():
        if role not in planned_rf:
            for cap in caps:
                res["captions"][cap.id] = {"status": "unmeasured", "verdict": "unmeasured",
                                           "reason": f"계획 글꼴 {cap.font_name} 을 찾지 못해 다시 그릴 수 없음"}
            continue
        for cap in caps[:EXACT_MAX_CAPTIONS_PER_ROLE]:
            crops = caption_crop_frames(ctx, cap)
            if not crops:
                res["captions"][cap.id] = {"status": "unmeasured", "verdict": "unmeasured", "reason": "정지 프레임이 없음(표시 시간이 짧음)"}
                continue
            if not any(_event_matches(ln, cap) for ln in ass_txt.split("\n") if ln.startswith("Dialogue:")):
                res["captions"][cap.id] = {"status": "unmeasured", "verdict": "unmeasured",
                                           "reason": "렌더에 쓴 ASS 에서 이 자막의 이벤트를 찾지 못함(resolve 후 다시 렌더?)"}
                continue
            jobs.append({"cap": cap, "role": role, "crops": crops, "box": _crop_box(cap, W, H)})
    if jobs:
        try:
            _exact_all(ctx, jobs, ass_txt, fonts_dir, alts, planned_rf, enc, W, H, fps, n_total, res)
        except Exception as e:
            for j in jobs:
                res["captions"][j["cap"].id] = {"status": "unmeasured", "verdict": "unmeasured",
                                                "reason": f"재렌더 실패: {type(e).__name__}: {e}"[:300]}
    return res


def _face_dir(tdp: Path, tag: str, fonts_dir: Path, faces: list) -> Path:
    """fontsdir for a re-render: the render's own faces + the given faces (symlinks)."""
    fd = tdp / f"fonts_{tag}"
    fd.mkdir()
    for p in fonts_dir.iterdir():
        if not (fd / p.name).exists():
            os.symlink(p.resolve(), fd / p.name)
    for f in faces:
        if not (fd / Path(f.path).name).exists():
            os.symlink(Path(f.path).resolve(), fd / Path(f.path).name)
    return fd


def _alt_layers(jobs: list, alts: dict) -> list[dict]:
    """Alternative re-renders to make: layer i switches every role to its i-th alternative at once, except roles whose
    crop boxes overlap another role's in space AND time (their alternative glyphs would reach the other's crop) --
    those get layers of their own.  -> [{role: (name, ResolvedFont)}]."""
    def span(role):
        js = [j for j in jobs if j["role"] == role]
        return [(j["box"], min(j["crops"]), max(j["crops"])) for j in js]

    def clash(r1, r2):
        for (b1, a1, e1) in span(r1):
            for (b2, a2, e2) in span(r2):
                if a1 <= e2 and a2 <= e1 and b1[0] < b2[2] and b2[0] < b1[2] and b1[1] < b2[3] and b2[1] < b1[3]:
                    return True
        return False
    roles = sorted({j["role"] for j in jobs})
    groups: list[list[str]] = []
    for r in roles:
        for g in groups:
            if not any(clash(r, o) for o in g):
                g.append(r)
                break
        else:
            groups.append([r])
    layers = []
    for g in groups:
        depth = max((len(alts.get(r) or []) for r in g), default=0)
        for i in range(depth):
            lay = {r: alts[r][i] for r in g if len(alts.get(r) or []) > i}
            if lay:
                layers.append(lay)
    return layers


def _exact_all(ctx, jobs: list, ass_txt: str, fonts_dir: Path, alts: dict, planned_rf: dict, enc: dict,
               W: int, H: int, fps: float, n_total: int, res: dict) -> None:
    from ..edit import captions as capmod
    from ..edit.render import Compositor
    from ..util.media import FFMPEG

    last = max(max(j["crops"]) for j in jobs)
    n_end = min(n_total, last + EXACT_TAIL_FRAMES + 1)
    first_crop = min(min(j["crops"]) for j in jobs)
    mis = [m for m in EXACT_MISALIGNED_STARTS if 0 < m < first_crop]
    idxs = sorted({i for j in jobs for i in j["crops"]})
    roles = sorted({j["role"] for j in jobs})
    with tempfile.TemporaryDirectory(prefix="sk_qa_exact_") as td:
        tdp = Path(td)
        # the PLANNED face (the plan's font_name, resolved like the renderer does), not whatever face the ASS on disk
        # names: a render whose ASS carried a wrong face must not be 'reproduced' by re-rendering that same ASS
        plan_txt, plan_faces, n_plan = ass_txt, {}, 0
        for role in roles:
            caps = [j["cap"] for j in jobs if j["role"] == role]
            plan_txt, n_by = alt_face_ass(plan_txt, caps, float(caps[0].size_px), planned_rf[role], prefix="qaplan_")
            n_plan += sum(n_by.values())
            plan_faces.update({name: planned_rf[role].face for name in n_by})
        pd = _face_dir(tdp, "plan", fonts_dir, [rf.face for rf in planned_rf.values()])
        chk = capmod.verify_libass_fonts(plan_txt, pd, plan_faces) if plan_faces else {"ok": False}
        if not chk.get("ok") or not n_plan:
            bad = {k_: {kk: v.get(kk) for kk in ("selected", "fallback_glyphs", "synthetic_bold")}
                   for k_, v in (chk.get("styles") or {}).items() if not v.get("ok")}
            raise RuntimeError(f"계획 글꼴로 다시 그릴 수 없음(libass 선택/대체 글자 {bad}, 바꾼 이벤트 {n_plan}개)")
        (tdp / "plan.ass").write_text(plan_txt, encoding="utf-8")
        variants = [{"tag": "plan", "start": 0, "ass": "plan.ass", "fonts": pd.name}]
        variants += [{"tag": f"mis{m}", "start": m, "ass": "plan.ass", "fonts": pd.name} for m in mis]
        alt_meta: dict[str, dict] = {}
        for li, lay in enumerate(_alt_layers(jobs, alts)):
            txt, faces, role_names = plan_txt, {}, {}
            for role, (nm, rf) in lay.items():
                caps = [j["cap"] for j in jobs if j["role"] == role]
                txt, n_by = alt_face_ass(txt, caps, float(caps[0].size_px), rf)
                role_names[role] = list(n_by)
                faces.update({name: rf.face for name in n_by})
            tag = f"alt{li}"
            fd = _face_dir(tdp, tag, fonts_dir, [rf.face for _, rf in lay.values()] + [x.face for x in planned_rf.values()])
            chk = capmod.verify_libass_fonts(txt, fd, faces) if faces else {"ok": False, "styles": {}}
            styles = chk.get("styles") or {}
            ok_roles = {}
            for role, (nm, rf) in lay.items():
                names = role_names.get(role) or []
                st_ok = bool(names) and all((styles.get(n) or {}).get("ok") for n in names)
                if st_ok:
                    ok_roles[role] = nm
                else:
                    bad = {n: {kk: (styles.get(n) or {}).get(kk) for kk in ("selected", "fallback_glyphs")} for n in names}
                    res["notes"].append(f"{role}: 대안 {nm} 재렌더 불가(libass 선택/대체 글자 {bad})")
            if not ok_roles:
                continue
            (tdp / f"{tag}.ass").write_text(txt, encoding="utf-8")
            variants.append({"tag": tag, "start": 0, "ass": f"{tag}.ass", "fonts": fd.name})
            alt_meta[tag] = ok_roles
        _encode_variants(ctx, variants, tdp, enc, W, H, fps, 0, n_end, FFMPEG, Compositor)
        frames = {v["tag"]: _decode_indices(tdp / f"{v['tag']}.mp4", set(idxs), v["start"], fps, W, H) for v in variants}
    mp4f = _decode_mp4_frames(ctx, set(idxs), 0)
    for j in jobs:
        cap, box = j["cap"], j["box"]
        crops = [i for i in j["crops"] if i in mp4f and i in frames["plan"]]
        if not crops:
            res["captions"][cap.id] = {"status": "unmeasured", "verdict": "unmeasured", "reason": "crop 프레임을 디코드하지 못함"}
            continue
        d_plan = [_mae(frames["plan"][i], mp4f[i], box) for i in crops]
        noise_by = {}
        for v in variants:
            if v["tag"].startswith("mis"):
                ds = [_mae(frames[v["tag"]][i], frames["plan"][i], box) for i in crops if i in frames[v["tag"]]]
                if ds:
                    noise_by[v["tag"]] = max(ds)
        alt_d = {}
        for tag, ok_roles in alt_meta.items():
            if j["role"] in ok_roles:
                alt_d[ok_roles[j["role"]]] = round(float(np.mean([_mae(frames[tag][i], mp4f[i], box) for i in crops])), 4)
        dp = float(np.mean(d_plan))
        noise = max(noise_by.values()) if noise_by else None
        out = {"status": "measured", "start_frame": 0, "crop_frames": crops, "crop_box": list(box),
               "conditions": {"crf": enc.get("crf"), "x264_preset": enc.get("preset"), "threads": enc.get("threads"),
                              "assumed": False, "source": enc.get("source"),
                              "renderer": "libass(ffmpeg subtitles) + shortkit.edit.render.Compositor, 0 프레임부터(제작과 같게)"},
               "mae_planned": round(dp, 4), "mae_planned_per_crop": [round(x, 4) for x in d_plan],
               "mae_alternatives": alt_d, "noise_mae": None if noise is None else round(noise, 4),
               "noise_by_start": {t: round(v, 4) for t, v in noise_by.items()},
               "misaligned_starts": [v["start"] for v in variants if v["tag"].startswith("mis")],
               "expected": cap.font_name}
        if noise is None:
            out.update(status="unmeasured", verdict="unmeasured", reason="다른 시작 프레임 재렌더가 없어 재인코딩 잡음을 못 잼")
        elif not alt_d:
            out.update(status="unmeasured", verdict="unmeasured",
                       reason="대안 글꼴을 같은 위치에 재렌더하지 못해 차이(margin)를 못 잼")
        else:
            best_alt = min(alt_d, key=alt_d.get)
            margin = alt_d[best_alt] - dp
            out.update(best_alternative=best_alt, margin=round(margin, 4), reproduced=dp <= noise)
            if dp <= noise and margin > noise:
                out.update(verdict="identical", reason=(f"계획 글꼴 재렌더가 출력과 MAE {dp:.3f} ≤ 재인코딩 잡음 {noise:.3f}, "
                                                        f"가장 가까운 대안 {best_alt} 보다 {margin:.3f} 더 가까움(> 잡음)"))
            elif margin > noise:
                out.update(verdict="best_not_reproduced",
                           reason=(f"계획 글꼴이 가장 가까운 대안 {best_alt} 보다 {margin:.3f} 더 가깝지만(> 잡음 {noise:.3f}) 재렌더가 "
                                   f"출력을 그대로 재현하지는 못함(MAE {dp:.3f} > 잡음) — 자막 뒤 화면·인코딩이 이 파이프라인과 "
                                   "다름(합성 테스트 렌더 등): 역할 판정은 합동 통계도 동일일 때만 동일"))
            elif alt_d[best_alt] < dp - noise:
                out.update(verdict="different", reason=(f"대안 {best_alt} 재렌더가 출력과 더 가까움(MAE {alt_d[best_alt]:.3f} < "
                                                        f"계획 {dp:.3f} − 잡음 {noise:.3f})"))
            else:
                out.update(verdict="not_reproduced", reason=(f"계획 글꼴 재렌더가 출력을 재현하지 못함(MAE {dp:.3f} > 잡음 "
                                                             f"{noise:.3f})이고 대안도 더 가깝지 않음 — 글꼴 외 차이(위치·색·배경)나 "
                                                             "후보 밖 글꼴일 수 있어 이 검사로는 판정 못 함"))
        res["captions"][cap.id] = out


def _encode_variants(ctx, variants: list, tdp: Path, enc: dict, W: int, H: int, fps: float, n0: int, n_end: int,
                     FFMPEG: str, Compositor) -> None:
    """Composite frames n0..n_end once and feed every variant's x264 encode (production's filter chain and settings);
    with more than EXACT_PARALLEL variants the frames go to disk first and the encodes run in batches."""
    def start(v):
        vf = (f"setpts=PTS+{v['start'] / fps:.6f}/TB,subtitles=filename={v['ass']}:fontsdir={v['fonts']},"
              "setpts=PTS-STARTPTS,scale=out_color_matrix=bt709:out_range=tv,format=yuv420p")
        cmd = [FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
               "-s", f"{W}x{H}", "-framerate", f"{fps:g}", "-i", "-", "-vf", vf, "-c:v", "libx264",
               "-preset", str(enc["preset"]), "-crf", f"{float(enc['crf']):g}", "-pix_fmt", "yuv420p",
               "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
               "-threads", str(int(enc.get("threads") or 2)), f"{v['tag']}.mp4"]
        return subprocess.Popen(cmd, cwd=str(tdp), stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE)

    def finish(procs):
        errs = {}
        for tag, pr in procs.items():
            try:
                pr.stdin.close()
            except OSError:
                pass
            rc = pr.wait()
            if rc != 0:
                errs[tag] = pr.stderr.read().decode("utf-8", "replace")[-300:]
        if errs:
            raise RuntimeError(f"재렌더 인코딩 실패: {errs}")

    comp = Compositor(ctx.resolved)
    if len(variants) <= EXACT_PARALLEL:
        procs = {v["tag"]: start(v) for v in variants}
        try:
            for n in range(n0, n_end):
                buf = np.ascontiguousarray(comp.frame(n)).tobytes()
                for v in variants:
                    if n >= v["start"]:
                        procs[v["tag"]].stdin.write(buf)
        finally:
            comp.close()
            finish(procs)
        return
    raw = tdp / "frames.rgb"
    fb = W * H * 3
    try:
        with open(raw, "wb") as fh:
            for n in range(n0, n_end):
                fh.write(np.ascontiguousarray(comp.frame(n)).tobytes())
    finally:
        comp.close()
    for bi in range(0, len(variants), EXACT_PARALLEL):
        batch = variants[bi:bi + EXACT_PARALLEL]
        procs = {v["tag"]: start(v) for v in batch}
        try:
            with open(raw, "rb") as fh:
                for n in range(n0, n_end):
                    buf = fh.read(fb)
                    for v in batch:
                        if n >= v["start"]:
                            procs[v["tag"]].stdin.write(buf)
        finally:
            finish(procs)
    raw.unlink()


def combine_role_verdict(pooled: dict, exact: dict[str, dict]) -> dict:
    """The role's font verdict: the exact-position re-render decides 'identical' (every checked caption identical and
    the pooled statistics not 'different'); 'different' from either line of evidence; otherwise the pooled 'identical'
    / 'similar' is at most 'similar' (못 잼)."""
    vs = [e.get("verdict") for e in exact.values() if e.get("status") == "measured"]
    ex = ("unmeasured" if not vs else "different" if "different" in vs else
          "identical" if all(v == "identical" for v in vs) else
          "best_not_reproduced" if all(v in ("identical", "best_not_reproduced") for v in vs) else "not_reproduced")
    pv = pooled.get("verdict") or "unmeasured"
    if ex == "identical":
        final = "identical" if pv != "different" else "unmeasured"
    elif ex == "best_not_reproduced":
        final = "identical" if pv == "identical" else ("different" if pv == "different" else "similar")
    elif ex == "different":
        final = "different"
    elif pv == "different":
        final = "different"
    elif pv in ("identical", "similar"):
        final = "similar"
    else:
        final = pv
    return {"exact_role_verdict": ex, "pooled_verdict": pv, "verdict": final,
            "conflict": ex == "identical" and pv == "different"}
