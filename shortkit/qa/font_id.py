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

Ceilings are cached in ``warehouse/cache/qa/font_ceilings/`` per (font, size bucket, crf) --
the key also carries the x264 preset, canvas width, fps and caption style class (outline /
label box / plain, colours), because each of those changes what the true font can reach.
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

SAMPLER = "shortkit.qa.font_id/libass-subtitles/1"
CACHE_DIR = "warehouse/cache/qa/font_ceilings"
SIZE_BUCKETS = (14, 16, 18, 20, 22, 24, 27, 30, 33, 36, 40, 45, 50, 56, 63, 71, 80, 90, 100, 112, 125, 140, 160,
                180, 200, 225, 250)
CEIL_REPEATS = 2
FRAMES_PER_SAMPLE = 3
N_NEAREST = 3
# x264 presets are identified by their subme value (unique per preset unless a tune overrides it)
SUBME_PRESET = {0: "ultrafast", 1: "superfast", 2: "veryfast", 4: "faster", 6: "fast", 7: "medium", 8: "slow",
                9: "slower", 10: "veryslow", 11: "placebo"}


def _canon(v) -> str:
    return json.dumps(v, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def size_bucket(size_px: float) -> int:
    """Nearest size of a ~11 % geometric ladder (the ceiling changes slowly with size)."""
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


def libass_samples(ctx, font: str, size: float, fill: tuple, outline: tuple | None, outline_px: float,
                   box: tuple | None, strings, crf: float, preset: str, fps: float, seed: int = 7):
    """typography.Sample list rendered like the production renderer (see module doc)."""
    from ..edit import captions as capmod
    from ..reference import typography as ty
    from ..util.media import FFMPEG

    face = capmod.resolve_font(font).face
    W = int(ctx.canvas_w)
    k = FRAMES_PER_SAMPLE
    Hs = int(math.ceil(size * 2.6 / 16.0)) * 16
    rng = np.random.default_rng(seed)
    specs = [(s, rep) for s in strings for rep in range(CEIL_REPEATS)]
    n = len(specs) * k
    hexc = lambda c: "#%02X%02X%02X" % tuple(int(v) for v in c)   # noqa: E731
    style = capmod.style_line("s", face.ass_name, face.ass_fontsize(size), hexc(fill), hexc(outline or (0, 0, 0)),
                              "#000000", face.weight, outline_px if outline is not None else 0.0, 0.0)
    evs = []
    for j, (s, _rep) in enumerate(specs):
        x = W / 2 + rng.uniform(-40, 40) + rng.uniform(0, 1)
        y = Hs / 2 + rng.uniform(-6, 6) + rng.uniform(0, 1)
        evs.append(f"Dialogue: 2,{capmod.ass_time(j * k / fps)},{capmod.ass_time((j + 1) * k / fps)},s,,0,0,0,,"
                   f"{{\\an5\\pos({x:.2f},{y:.2f})}}{s}")
    bgs, bg_desc = _bg_strips(ctx, n, W, Hs, seed, box)
    black = np.zeros((Hs, W, 3), np.uint8)
    with tempfile.TemporaryDirectory(prefix="sk_qa_font_") as td:
        tdp = Path(td)
        (tdp / "fonts").mkdir()
        os.symlink(face.path, tdp / "fonts" / Path(face.path).name)
        (tdp / "c.ass").write_text(_ass_doc(W, Hs, style, evs), encoding="utf-8")
        base = [FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                "-s", f"{W}x{Hs}", "-framerate", f"{fps:g}", "-i", "-"]
        # 1) lossless render on black: where the fill ink is (crop box, like the QA crop)
        raw_ref = subprocess.run(base + ["-vf", "subtitles=filename=c.ass:fontsdir=fonts", "-f", "rawvideo",
                                         "-pix_fmt", "rgb24", "-"], input=black.tobytes() * n,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=td, check=True).stdout
        # 2) the output pipeline: subtitles -> bt709 yuv420p -> x264 at the output's CRF/preset -> decode
        subprocess.run(base + ["-vf", "subtitles=filename=c.ass:fontsdir=fonts,"
                               "scale=out_color_matrix=bt709:out_range=tv,format=yuv420p",
                               "-c:v", "libx264", "-preset", preset, "-crf", f"{crf:g}", "-pix_fmt", "yuv420p",
                               "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709",
                               "-color_range", "tv", "-threads", "2", "enc.mp4"],
                       input=b"".join(np.ascontiguousarray(b).tobytes() for b in bgs),
                       stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, cwd=td, check=True)
        raw_dec = subprocess.run([FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-i", "enc.mp4", "-f", "rawvideo",
                                  "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=td,
                                 check=True).stdout
    fb = W * Hs * 3
    ref = [np.frombuffer(raw_ref[i * fb:(i + 1) * fb], np.uint8).reshape(Hs, W, 3) for i in range(len(raw_ref) // fb)]
    dec = [np.frombuffer(raw_dec[i * fb:(i + 1) * fb], np.uint8).reshape(Hs, W, 3) for i in range(len(raw_dec) // fb)]
    fv = np.array(fill, np.int32)
    samples = []
    for j, (s, _rep) in enumerate(specs):
        mid = j * k + k // 2
        if mid >= len(ref) or mid >= len(dec):
            continue
        m = np.sqrt(((ref[mid].astype(np.int32) - fv) ** 2).sum(axis=2)) < 80
        ys, xs = np.nonzero(m)
        if not len(xs):
            continue
        pad = 3 if box is not None else int(float(outline_px if outline is not None else 0) + 6)
        x0, y0 = max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad)
        x1, y1 = min(W, int(xs.max()) + 1 + pad), min(Hs, int(ys.max()) + 1 + pad)
        around = box if box is not None else outline
        samples.append(ty.Sample(crop=dec[mid][y0:y1, x0:x1].copy(), text=s, size_px=float(size),
                                 fill_rgb=tuple(fill), outline_rgb=None if around is None else tuple(around),
                                 font=font, group=f"{s}|{size:g}", style="box" if box is not None else
                                 ("outline" if outline is not None else "plain"), canvas_size_px=float(size)))
    return samples, bg_desc


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


def ceiling_for(ctx, font: str, size_px: float, fill: tuple, outline: tuple | None, outline_px: float,
                box: tuple | None) -> tuple[dict, dict, bool]:
    """(ceiling, conditions, from_cache) for ``font`` under the output's encode settings."""
    from ..reference import typography as ty

    enc = encode_settings(ctx)
    if enc.get("crf") is None:
        raise LookupError("출력 인코딩 CRF 를 측정하지 못함: " + "; ".join(enc.get("notes") or []))
    preset = enc.get("preset")
    assumed = preset is None
    preset = preset or "medium"
    b = size_bucket(size_px)
    fr = ty.font_ref(font)
    frac = round(float(outline_px) / float(size_px), 3) if (outline is not None and size_px) else 0.0
    style = {"kind": "box" if box is not None else ("outline" if outline is not None else "plain"),
             "fill": list(fill), "outline": list(outline) if outline is not None else None, "outline_frac": frac,
             "box": list(box) if box is not None else None}
    fps = round(float(ctx.fps), 3)
    key = {"kind": "ceiling", "sampler": SAMPLER, "font": fr.name, "face": [Path(fr.path).name, fr.index],
           "size_bucket": b, "crf": enc["crf"], "preset": preset, "codec": "h264", "width": int(ctx.canvas_w),
           "fps": fps, "style": style, "strings": list(ty.DEFAULT_STRINGS[:3]), "repeats": CEIL_REPEATS,
           "frames_per_sample": FRAMES_PER_SAMPLE}
    cond = ty.Conditions(canvas=(int(ctx.canvas_w), int(ctx.canvas_h)), ref_resolution=(int(ctx.canvas_w), int(ctx.canvas_h)),
                         codec="h264", crf=float(enc["crf"]), x264_preset=preset, frames_per_sample=FRAMES_PER_SAMPLE,
                         fps=fps, background="color:#%02X%02X%02X" % tuple(box) if box is not None else "video",
                         renderer="libass(ffmpeg subtitles filter, shortkit.edit.render 규약)", assumed=assumed,
                         source=f"{enc.get('source')}" + (" / x264 프리셋 특정 못 함 → medium 가정" if assumed else ""))
    hit = _read_cache(key)
    if hit is not None:
        return hit["ceiling"], cond.to_dict(), True
    samples, bg = libass_samples(ctx, font, float(b), fill, outline, frac * b, box, ty.DEFAULT_STRINGS[:3],
                                 float(enc["crf"]), preset, fps)
    if len(samples) < 4:
        raise RuntimeError(f"천장 실험 샘플 부족({len(samples)}개)")
    c = ty.ceiling(fr, cond, samples=samples, color_mode="given", keep_rows=True)
    c["background"] = bg
    _write_cache(key, {"ceiling": c, "conditions": cond.to_dict()})
    return c, cond.to_dict(), False


# ----------------------------------------------------------------------------- identification
def _same(a: str | None, b: str | None) -> bool:
    return str(a or "").replace(" ", "").lower() == str(b or "").replace(" ", "").lower()


def identify_caption_font(ctx, cap, crop: np.ndarray, text: str, fill: tuple, around: tuple | None,
                          boxed: bool) -> dict:
    """typography.identify_many on one output crop; verdict of the EXPECTED font."""
    from ..reference import typography as ty

    exp_ref = ty.font_ref(cap.font_name)
    outline = None if boxed else (around if (cap.outline_px and around is not None) else None)
    box = around if boxed else None
    ceil, cond, cached = ceiling_for(ctx, cap.font_name, float(cap.size_px), tuple(fill), outline,
                                     float(cap.outline_px or 0.0), box)
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
            "size_bucket": size_bucket(cap.size_px), "background": ceil.get("background")},
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
