"""SYNTHETIC mockloop: ground truth of the mock references vs what the reference analyzers measured.

    SHORTKIT_ROOT=<scratch> PYTHONPATH=<repo> python docs/validation/mockloop/accuracy.py truth
    SHORTKIT_ROOT=<scratch> PYTHONPATH=<repo> python docs/validation/mockloop/accuracy.py compare [--out docs/validation/mockloop/accuracy.json]

``truth`` derives, per mock video, the value each measured preset key SHOULD come out as, from what the
renderer was told and did (presets/mocktruth, episodes/mockref-00N/plan.yaml, build/resolved.json,
build/render_report.json, build/stems) -- never from the analyzers under test.  Where the preset key is a
style value and the measurement is an observed statistic of the videos (max chars per line, safe margins,
shortest display time ...), the truth is that statistic computed from the resolved plans.

``compare`` reads presets/joshuamagazine/measurements/*.json + sfx_catalog.json + sfx_map.yaml +
formats.yaml of the scratch project and writes a table: truth (value, n, p10/p50/p90) vs measured, error,
tolerance (TOL, stated before any comparison was run) and a verdict:
    pass | fail (measured but outside tolerance / wrong n) | unmeasured (truth exhibited, analyzer said 못 잼)
    | not_exhibited (truth absent in the mocks and analyzer said 못 잼 -> correct) | false_positive.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

import numpy as np
import yaml

VIDS = {n: f"SYNTHmock{n:02d}" for n in range(1, 6)}

# ---------------------------------------------------------------------------- tolerances (stated up front)
TOL = {
    "exact": 0.0,               # categorical / booleans / ints that must match
    "canvas_px": 4.0,           # video region edges (canvas px)
    "anchor_px": 6.0,           # caption anchor x/y: renderer anchors the LINE BOX, analyzer the ink box
    "margin_px": 6.0,           # safe margins (ink/box extents)
    "size_rel": 0.05,           # font EM size, max width (relative)
    "outline_px": 1.0,
    "pad_px": 2.0,
    "alpha": 0.05,
    "color_rgb": 30.0,          # euclidean RGB (H.264 4:2:0 on saturated colours)
    "line_spacing": 0.05,
    "chars": 1.0,
    "frames_s": 0.05,           # ~1.5 frames at 30 fps: motion / transition / freeze durations
    "timing_s": 0.07,           # ~2 frames: display times, first caption time
    "lead_s": 0.10,
    "zoom_scale": 0.03,
    "speed": 0.05,
    "lufs": 0.5,
    "tp_db": 0.5,
    "bgm_gain_db": 1.0,
    "tempo": 0.01,
    "section_s": 0.10,
    "duck_depth_db": 1.5,
    "duck_attack_s": 0.05,
    "duck_release_s": 0.10,
    "bgm_fade_s": 0.20,
    "orig_fade_s": 0.02,
    "sil_fade_s": 0.03,
    "sfx_gain_db": 2.0,
    "duration_s": 0.10,
    "deco_rel": 0.05,
    "deco_outline_px": 1.5,
    "deco_ratio": 0.05,
    "blink_hz": 0.1,
}


def root() -> Path:
    return Path(os.environ["SHORTKIT_ROOT"]).resolve()


def rj(p: Path, default=None):
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else default


def ry(p: Path, default=None):
    return yaml.safe_load(p.read_text(encoding="utf-8")) if p.is_file() else default


def pst(vals) -> dict:
    v = [float(x) for x in vals if x is not None]
    if not v:
        return {"n": 0, "p10": None, "p50": None, "p90": None}
    q = np.percentile(v, [10, 50, 90])
    return {"n": len(v), "p10": round(float(q[0]), 3), "p50": round(float(q[1]), 3), "p90": round(float(q[2]), 3)}


def get(d: dict, key: str, default=None):
    cur = d
    for part in key.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return default
        cur = cur[part]
    return cur


def lufs_of(path: Path, extra_af: str = "") -> float | None:
    af = (extra_af + "," if extra_af else "") + "ebur128"
    p = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-i", str(path), "-vn", "-af", af, "-f", "null", "-"],
                       capture_output=True, text=True)
    s = p.stderr[p.stderr.rfind("Summary:"):]
    for line in s.splitlines():
        line = line.strip()
        if line.startswith("I:"):
            try:
                return float(line.split()[1])
            except (IndexError, ValueError):
                return None
    return None


def wav_onset_s(path: Path, rel_db: float = 30.0) -> float:
    import wave

    with wave.open(str(path)) as w:
        sr, n, ch = w.getframerate(), w.getnframes(), w.getnchannels()
        x = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float64)
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    hop = int(0.005 * sr)
    fr = np.array([np.sqrt(np.mean(x[i:i + hop] ** 2)) for i in range(0, len(x) - hop, hop)]) + 1e-9
    db = 20 * np.log10(fr)
    idx = np.nonzero(db >= db.max() - rel_db)[0]
    return float(idx[0] * hop / sr) if len(idx) else 0.0


# ============================================================================ truth
def episode_truth(r: Path, n: int, pr: dict) -> dict:
    ed = r / "episodes" / f"mockref-{n:03d}"
    plan = ry(ed / "plan.yaml")
    R = rj(ed / "build" / "resolved.json")
    RR = rj(ed / "build" / "render_report.json")
    caps = R["captions"]
    by_role: dict[str, list[dict]] = {}
    for c in caps:
        by_role.setdefault(c["role"], []).append(c)
    out: dict[str, object] = {}
    W, H = R["canvas"]["width"], R["canvas"]["height"]
    # ---------------------------------------------------------------- canvas
    out["canvas.width"], out["canvas.height"] = RR["probe"]["width"], RR["probe"]["height"]
    out["canvas.fps"] = RR["probe"]["fps"]
    for k in ("x", "y", "w", "h"):
        out[f"canvas.video_region.{k}"] = pr["canvas"]["video_region"][k]
    out["canvas.background.type"] = pr["canvas"]["background"]["type"]
    out["canvas.background.color"] = pr["canvas"]["background"]["color"]
    ext = []
    for c in caps:
        b = c["bbox"]
        x0, y0, x1, y1 = b["x"], b["y"], b["x"] + b["w"], b["y"] + b["h"]
        bx = c.get("box") or {}
        if bx.get("enabled") and bx.get("rect"):
            X, Y, BW, BH = bx["rect"]
            x0, y0, x1, y1 = min(x0, X), min(y0, Y), max(x1, X + BW), max(y1, Y + BH)
        ext.append((x0, y0, x1, y1))
    out["canvas.safe_margin.left"] = round(min(e[0] for e in ext), 1)
    out["canvas.safe_margin.top"] = round(min(e[1] for e in ext), 1)
    out["canvas.safe_margin.right"] = round(W - max(e[2] for e in ext), 1)
    out["canvas.safe_margin.bottom"] = round(H - max(e[3] for e in ext), 1)
    # ---------------------------------------------------------------- text roles
    for role, cs in by_role.items():
        st = pr["text"]["roles"][role]
        pre = f"text.roles.{role}."
        out[pre + "font_name"] = st["font_name"]
        out[pre + "bold"] = st["bold"]
        out[pre + "size_px"] = st["size_px"]
        out[pre + "anchor.x"] = float(np.median([c["anchor"][0] for c in cs]))
        out[pre + "anchor.y"] = float(np.median([c["anchor"][1] for c in cs]))
        out[pre + "anchor.align"] = st["anchor"]["align"]
        out[pre + "anchor.valign"] = st["anchor"]["valign"]
        out[pre + "color"] = st["color"]
        hl = any(w and w in c["text"] for c in cs for w in (c.get("highlight") or []))
        out[pre + "highlight_color"] = st["highlight_color"] if hl else None
        out[pre + "outline_px"] = st["outline_px"]
        out[pre + "outline_color"] = st["outline_color"] if st["outline_px"] > 0 else None
        out[pre + "shadow_px"] = st["shadow_px"]
        out[pre + "shadow_color"] = st["shadow_color"] if st["shadow_px"] > 0 else None
        out[pre + "box.enabled"] = bool(st["box"]["enabled"])
        if st["box"]["enabled"]:
            for k in ("color", "alpha", "pad_x", "pad_y"):
                out[pre + "box." + k] = st["box"][k]
        multi = [c for c in cs if len(c["lines"]) >= 2]
        out[pre + "line_spacing"] = st["line_spacing"] if multi else None
        out[pre + "max_chars_per_line"] = max(len(l) for c in cs for l in c["lines"])
        out[pre + "max_lines"] = max(len(c["lines"]) for c in cs)
        out[pre + "max_width_px"] = round(max(c["bbox"]["w"] for c in cs), 1)
        mi, mo = st["motion_in"], st["motion_out"]
        out[pre + "motion_in.type"] = mi["type"]
        # a plain cut ("none") is a 0 s transition, observable only when the caption actually appears /
        # disappears inside the video (a title shown from frame 0 to the last frame never exhibits either);
        # a fade/pop starting at frame 0 is visible (the first frames show it partly)
        dur_v = RR["probe"]["duration"]
        shows_in = mi["type"] != "none" or any(c["start"] > 0.05 for c in cs)
        shows_out = mo["type"] != "none" or any(c["end"] < dur_v - 0.05 for c in cs)
        out[pre + "motion_in.dur_s"] = (mi["dur_s"] if mi["type"] != "none" else 0.0) if shows_in else None
        out[pre + "motion_in.scale_from"] = mi["scale_from"] if mi["type"] == "pop" else None
        out[pre + "motion_in.offset_px"] = mi["offset_px"] if mi["type"].startswith("slide") else None
        out[pre + "motion_out.type"] = mo["type"]
        out[pre + "motion_out.dur_s"] = (mo["dur_s"] if mo["type"] != "none" else 0.0) if shows_out else None
        out[pre + "persist"] = st["persist"]
        if st["persist"] != "whole_video":
            out[pre + "timing.min_dur_s"] = round(min(c["end"] - c["start"] for c in cs), 3)
        if role == "dialogue":
            out[pre + "quote_marks"] = st.get("quote_marks")
    # dialogue lead: caption start - onset of the TTS line in the output
    lines = {"assets/test/sources/face_voice.mp4": [("speech_01.wav", 10.0), ("speech_03.wav", 62.0)],
             "assets/test/sources/people_voice.mp4": [("speech_02.wav", 15.0)]}
    leads = []
    for c in by_role.get("dialogue", []):
        best = None
        for clip in R["clips"]:
            for wav, at in lines.get(clip["source_path"], []):
                if clip["src_in"] <= at < clip["src_out"]:
                    on = clip["out_start"] + (at - clip["src_in"]) / clip["speed"] + \
                        wav_onset_s(r / "assets/test/generated" / wav)
                    if best is None or abs(c["start"] - on) < abs(best):
                        best = c["start"] - on
        if best is not None:
            leads.append(best)
    if leads:
        out["text.roles.dialogue.timing.lead_s"] = round(float(np.median(leads)), 3)
    # ---------------------------------------------------------------- tone (same classifier, on the TRUE text)
    from shortkit.reference.aggregate import REGISTER_MAP, ending_class

    cls, ends = Counter(), Counter()
    for c in caps:
        if c["role"] not in ("title", "description", "situation", "reaction"):
            continue
        e = ending_class(c["text"].split("\n")[-1])
        if e:
            cls[e[0]] += 1
            if e[0] != "명사형/기타":
                ends[e[1][-2:] if len(e[1]) >= 2 else e[1]] += 1
    sent = {k: v for k, v in cls.items() if k != "명사형/기타"}
    if sent:
        top, k = max(sent.items(), key=lambda kv: kv[1])
        out["text.tone.register"] = REGISTER_MAP[top] if k / sum(sent.values()) >= 0.6 else "혼합"
    out["_tone_endings"] = dict(ends)
    # ---------------------------------------------------------------- motion
    clips = R["clips"]
    zs = [c["zoom"] for c in clips if c.get("zoom")]
    if zs:
        out["motion.zoom.scale_to"] = float(np.median([z["scale_to"] for z in zs]))
        out["motion.zoom.dur_s"] = float(np.median([z["dur"] for z in zs]))
        out["motion.zoom.ease"] = Counter(z["ease"] for z in zs).most_common(1)[0][0]
        out["motion.zoom.recenter"] = bool(Counter(z["recenter"] for z in zs).most_common(1)[0][0])
    fz = [c["freeze"]["hold"] for c in clips if c.get("freeze")]
    if fz:
        out["motion.freeze.hold_s"] = float(np.median(fz))
    sp = [c["speed"] for c in clips if c["speed"] < 1]
    out["motion.speed.slowmo_factor"] = float(np.median(sp)) if sp else None
    # boundaries between contiguous source time of the same source are invisible joins (used for the
    # slow-motion ramps) -- not transitions a viewer (or an analyzer) can see
    vis = [c for p_, c in zip(clips, clips[1:])
           if not (c["source_id"] == p_["source_id"] and abs(c["src_in"] - p_["src_out"]) < 1e-6)]
    tr = [c["transition_in"]["type"] for c in vis]
    out["motion.transitions.default"] = Counter(tr).most_common(1)[0][0]
    out["_visible_boundaries"] = [(c["out_start"], c["transition_in"]["type"]) for c in vis]
    fl = [c["transition_in"] for c in clips[1:] if c["transition_in"]["type"] == "flash"]
    if fl:
        out["motion.transitions.flash.dur_s"] = float(np.median([t["dur"] for t in fl]))
        out["motion.transitions.flash.color"] = fl[0]["color"]
        out["motion.transitions.flash.scope"] = fl[0]["scope"]
    xf = [c["transition_in"]["dur"] for c in clips[1:] if c["transition_in"]["type"] == "crossfade"]
    out["motion.transitions.crossfade.dur_s"] = float(np.median(xf)) if xf else None
    # ---------------------------------------------------------------- decorations
    for d in R["decorations"]:
        stl = d["style"]
        for k in ("color", "size_px", "outline_px", "outline_color", "blink_hz", "head_len_ratio", "head_width_ratio",
                  "shaft_width_ratio"):
            out[f"decorations.{d['kind']}.{k}"] = stl[k]
    # ---------------------------------------------------------------- structure
    out["_duration"] = RR["probe"]["duration"]
    timed = [c["start"] for c in caps if c["role"] not in ("title", "description")]
    out["structure.first_caption_at_s"] = min(timed)
    # ---------------------------------------------------------------- audio
    A = RR["audio"]
    L = RR["mp4_loudness"]["integrated_lufs"]
    out["audio.loudness.integrated_lufs"] = L
    out["audio.loudness.true_peak_db"] = RR["mp4_loudness"]["true_peak_db"]
    lib = {x["track_id"]: x for x in (ry(r / "assets/library/music/index.yaml") or {}).get("tracks", [])}
    t = lib[pr["audio"]["bgm"]["track_id"]]
    out["audio.bgm.track_id"] = t["track_id"]
    out["audio.bgm.title"] = t["title"]
    out["audio.bgm.version"] = t["version"]
    out["audio.bgm.tempo_ratio"] = R["audio"]["bgm"]["tempo_ratio"]
    out["audio.bgm.section_start_s"] = R["audio"]["bgm"]["section_start_s"]
    norm = float(A["norm_gain_db"]) + float(A.get("final_trim_db") or 0.0)
    out["_bgm_ls_gain"] = float(R["audio"]["bgm"]["gain_db"]) + norm       # gain actually applied to the clean file
    out["_mix_lufs"] = L
    out["audio.bgm.fade_in_s"] = R["audio"]["bgm"]["fade_in_s"]
    out["audio.bgm.fade_out_s"] = R["audio"]["bgm"]["fade_out_s"]
    out["audio.bgm.loop"] = bool(R["audio"]["bgm"]["loop"])
    if R["audio"]["bgm"]["duck_ranges"]:
        out["audio.ducking.depth_db"] = pr["audio"]["ducking"]["depth_db"]
        out["audio.ducking.attack_s"] = pr["audio"]["ducking"]["attack_s"]
        out["audio.ducking.release_s"] = pr["audio"]["ducking"]["release_s"]
    if R["audio"]["originals"]:
        out["audio.original.fade_s"] = pr["audio"]["original"]["fade_s"]
        # kept speech loudness re programme: originals stem x normalisation gain, over the kept ranges
        seg = [(o["out_start"], o["out_end"]) for o in R["audio"]["originals"]]
        with tempfile.TemporaryDirectory() as td:
            fil = "+".join(f"between(t,{a:.3f},{b:.3f})" for a, b in seg)
            tmp = Path(td) / "o.wav"
            subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-i",
                            str(ed / "build/stems/originals.wav"), "-af",
                            f"aselect='{fil}',asetpts=N/SR/TB,volume={norm}dB", str(tmp)], check=True)
            lo = lufs_of(tmp)
        out["_kept_speech_lufs"] = lo
    if R["audio"]["bgm"].get("silences"):
        out["audio.silence.fade_s"] = pr["audio"]["silence"]["fade_s"]
    # SFX: per event final gain on the GENERATED file (render report: plan gain + norm - limiter)
    ev = []
    for s, lim in zip(R["audio"]["sfx"], A.get("sfx_limiting") or []):
        assert s["id"] == lim["id"]
        ev.append({"type": s["type"], "t": s["t"], "event_t": s["event_t"], "final_gain_db": lim["final_gain_db"],
                   "path": s["path"]})
    out["_sfx_events"] = ev
    out["_silences"] = R["audio"]["bgm"].get("silences") or []
    return out


def build_truth(r: Path) -> dict:
    pr = ry(r / "presets/mocktruth/preset.yaml")
    per = {VIDS[n]: episode_truth(r, n, pr) for n in VIDS}
    keys = sorted({k for d in per.values() for k in d if not k.startswith("_")})
    T: dict[str, dict] = {}
    for k in keys:
        vals = {v: d.get(k) for v, d in per.items() if d.get(k) is not None}
        T[k] = {"per_video": vals, "preset": get(pr, k)}
    # derived: BGM gain at the programme loudness, with T = p50 of the mocks' loudness (the analyzer's rule)
    Tp = float(np.median([d["_mix_lufs"] for d in per.values()]))
    T["audio.bgm.gain_db"] = {"per_video": {v: round(d["_bgm_ls_gain"] + Tp - d["_mix_lufs"], 2) for v, d in per.items()},
                              "preset": pr["audio"]["bgm"]["gain_db"], "note": f"applied gain + (T {Tp} - mix LUFS)"}
    kg = {v: round(d["_kept_speech_lufs"] - d["_mix_lufs"], 2) for v, d in per.items() if d.get("_kept_speech_lufs")}
    sil = {f"{v}@{side}": d["audio.silence.fade_s"] for v, d in per.items() if d.get("audio.silence.fade_s") is not None
           for side in ("into", "out_of")}
    if sil:
        T["audio.silence.fade_s"] = {"per_video": sil, "preset": pr["audio"]["silence"]["fade_s"],
                                     "note": "one row per ramp (into / out of each silence), like the method"}
    T["audio.original.keep_gain_db"] = {"per_video": kg, "preset": pr["audio"]["original"]["keep_gain_db"],
                                        "note": "originals stem x norm gain over kept ranges (LUFS) - mix LUFS"}
    # SFX gain in the renderer's semantics on the MAPPED LIBRARY file (the file production will use)
    from shortkit.reference.audio_original import _sfx_file_level

    libmap = {"pop": "assets/library/sfx/lib_pop_bright.wav", "whoosh": "assets/library/sfx/lib_whoosh_soft.wav",
              "ding": "assets/library/sfx/lib_ding_clean.wav"}
    lvl = {}
    for typ, lf in libmap.items():
        lvl[typ] = (_sfx_file_level(f"assets/test/generated/sfx/{typ}.wav")[0], _sfx_file_level(lf)[0])
    sg = {}
    for v, d in per.items():
        for k, e in enumerate(d["_sfx_events"]):
            sg[f"{v}@{e['t']}"] = round(e["final_gain_db"] + (Tp - d["_mix_lufs"]) + (lvl[e["type"]][0] - lvl[e["type"]][1]), 2)
    T["audio.sfx.gain_db_default"] = {"per_video": sg, "preset": pr["audio"]["sfx"]["gain_db_default"],
                                      "note": "per event: final gain on generated file + (T - mix LUFS) + (generated file "
                                              "RMS - mapped library file RMS), same window as the method (one row per event)",
                                      "file_levels_dbfs": lvl}
    # structure
    durs = {v: d["_duration"] for v, d in per.items()}
    st = pst(durs.values())
    for leaf in ("p10", "p50", "p90"):
        T[f"structure.duration_s.{leaf}"] = {"per_video": durs, "preset": None, "rule": leaf, "fixed": st[leaf]}
    T["structure.duration_s.n"] = {"per_video": {}, "preset": None, "fixed": 5}
    # tone examples
    ends = Counter()
    for d in per.values():
        ends.update(d["_tone_endings"])
    T["text.tone.sentence_end_examples"] = {"per_video": {}, "preset": None, "fixed": [e for e, _ in ends.most_common(8)]}
    # SFX catalog truth
    counts = {typ: {v: sum(1 for e in d["_sfx_events"] if e["type"] == typ) for v, d in per.items()}
              for typ in ("pop", "whoosh", "ding")}
    offs = {typ: [round(e["t"] - e["event_t"], 3) for d in per.values() for e in d["_sfx_events"] if e["type"] == typ]
            for typ in counts}
    sil = {v: len(d["_silences"]) for v, d in per.items()}
    catalog = {"types": {typ: {"per_video_count": c, "stats": pst(c.values()), "offset_to_event_s": pst(offs[typ]),
                               "class": "edit_sfx", "library_file": libmap[typ]} for typ, c in counts.items()},
               "per_video_total": pst([sum(c[v] for c in counts.values()) for v in per]),
               "intentional_silence_per_video": sil}
    return {"schema": "mockloop.truth/1", "synthetic": True, "videos": VIDS, "programme_T_p50": Tp, "keys": T,
            "sfx_catalog": catalog, "formats": {v: "F1" for v in per}}


# ============================================================================ compare
FAMILY_TOL = [  # (predicate on key, tolerance name, kind)
    (lambda k: k in ("canvas.width", "canvas.height", "canvas.fps"), "exact", "num"),
    (lambda k: k.startswith("canvas.video_region."), "canvas_px", "num"),
    (lambda k: k.startswith("canvas.safe_margin."), "margin_px", "num"),
    (lambda k: k.endswith(".anchor.x") or k.endswith(".anchor.y"), "anchor_px", "num"),
    (lambda k: k.endswith(".size_px") and k.startswith("text."), "size_rel", "rel"),
    (lambda k: k.endswith(".max_width_px"), "size_rel", "rel"),
    (lambda k: k.endswith(".outline_px") and k.startswith("text."), "outline_px", "num"),
    (lambda k: k.endswith(".shadow_px"), "outline_px", "num"),
    (lambda k: k.endswith(".box.pad_x") or k.endswith(".box.pad_y"), "pad_px", "num"),
    (lambda k: k.endswith(".box.alpha"), "alpha", "num"),
    (lambda k: k.endswith("color"), "color_rgb", "color"),
    (lambda k: k.endswith(".line_spacing"), "line_spacing", "num"),
    (lambda k: k.endswith(".max_chars_per_line"), "chars", "num"),
    (lambda k: k.endswith(".max_lines"), "exact", "num"),
    (lambda k: k.endswith(".dur_s") and k.startswith("text."), "frames_s", "num"),
    (lambda k: k.endswith(".scale_from"), "zoom_scale", "num"),
    (lambda k: k.endswith(".offset_px"), "anchor_px", "num"),
    (lambda k: k.endswith("timing.min_dur_s"), "timing_s", "num"),
    (lambda k: k.endswith("timing.lead_s"), "lead_s", "num"),
    (lambda k: k == "motion.zoom.scale_to", "zoom_scale", "num"),
    (lambda k: k in ("motion.zoom.dur_s", "motion.freeze.hold_s", "motion.transitions.flash.dur_s",
                     "motion.transitions.crossfade.dur_s"), "frames_s", "num"),
    (lambda k: k == "motion.speed.slowmo_factor", "speed", "num"),
    (lambda k: k == "audio.loudness.integrated_lufs", "lufs", "num"),
    (lambda k: k == "audio.loudness.true_peak_db", "tp_db", "num"),
    (lambda k: k == "audio.bgm.gain_db", "bgm_gain_db", "num"),
    (lambda k: k == "audio.bgm.tempo_ratio", "tempo", "num"),
    (lambda k: k == "audio.bgm.section_start_s", "section_s", "num"),
    (lambda k: k in ("audio.bgm.fade_in_s", "audio.bgm.fade_out_s"), "bgm_fade_s", "num"),
    (lambda k: k == "audio.ducking.depth_db", "duck_depth_db", "num"),
    (lambda k: k == "audio.ducking.attack_s", "duck_attack_s", "num"),
    (lambda k: k == "audio.ducking.release_s", "duck_release_s", "num"),
    (lambda k: k == "audio.original.fade_s", "orig_fade_s", "num"),
    (lambda k: k == "audio.original.keep_gain_db", "lufs", "num"),
    (lambda k: k == "audio.silence.fade_s", "sil_fade_s", "num"),
    (lambda k: k == "audio.sfx.gain_db_default", "sfx_gain_db", "num"),
    (lambda k: k.startswith("structure.duration_s."), "duration_s", "num"),
    (lambda k: k == "structure.first_caption_at_s", "timing_s", "num"),
    (lambda k: k == "decorations.arrow.size_px", "deco_rel", "rel"),
    (lambda k: k == "decorations.arrow.outline_px", "deco_outline_px", "num"),
    (lambda k: k.endswith("_ratio") and k.startswith("decorations."), "deco_ratio", "num"),
    (lambda k: k.endswith("blink_hz"), "blink_hz", "num"),
]


PER_EVENT_KEYS = {"audio.silence.fade_s", "audio.sfx.gain_db_default"}


def tol_for(key: str) -> tuple[str, float, str]:
    for pred, name, kind in FAMILY_TOL:
        if pred(key):
            return name, TOL[name], kind
    return "exact", 0.0, "cat"


def rgb(h: str):
    h = h.lstrip("#")
    return np.array([int(h[i:i + 2], 16) for i in (0, 2, 4)], float)


def err_of(kind: str, truth, meas):
    if truth is None or meas is None:
        return None
    if kind == "color":
        return round(float(np.linalg.norm(rgb(str(truth)) - rgb(str(meas)))), 1)
    if kind in ("num", "rel"):
        try:
            e = float(meas) - float(truth)
        except (TypeError, ValueError):
            return None
        if kind == "rel":
            return round(e / float(truth), 4) if float(truth) else None
        return round(e, 4)
    return 0.0 if truth == meas else 1.0


def load_measurements(r: Path) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
    from shortkit.config import load_measurement_items

    return load_measurement_items(r / "presets/joshuamagazine", strict=False)


def compare(r: Path, truth: dict) -> list[dict]:
    meas = load_measurements(r)
    rows = []
    for key, t in sorted(truth["keys"].items()):
        tname, tol, kind = tol_for(key)
        per = t.get("per_video") or {}
        m = meas.get(key)
        rule = (m or {}).get("value_rule") or ("p90" if key.endswith(("max_chars_per_line", "max_lines", "max_width_px"))
                                               else "p10" if key.startswith("canvas.safe_margin") else "p50")
        numeric = kind in ("num", "rel") or kind == "color"
        if "fixed" in t:
            tval = t["fixed"]
            tstats = pst(per.values()) if per and kind != "cat" else {"n": len(per) or None}
        elif kind in ("num", "rel") and per:
            tstats = pst(per.values())
            if rule == "mode":
                tval = Counter(per.values()).most_common(1)[0][0]
            else:
                tval = tstats.get(rule if rule in ("p10", "p50", "p90") else "p50")
            if key.endswith((".max_lines", ".max_chars_per_line")) and tval is not None:
                tval = int(round(tval))                   # the aggregator stores these as integers (as_int)
        elif per:
            tstats = {"n": len(per)}
            tval = Counter(json.dumps(v, ensure_ascii=False) for v in per.values()).most_common(1)[0][0]
            tval = json.loads(tval)
        else:
            tstats, tval = {"n": 0}, None
        row = {"key": key, "family": tname, "tolerance": tol, "truth_value": tval, "truth_preset": t.get("preset"),
               "truth_n": tstats.get("n"), "truth_p10": tstats.get("p10"), "truth_p50": tstats.get("p50"),
               "truth_p90": tstats.get("p90"), "measured_status": (m or {}).get("status", "absent"),
               "measured_value": (m or {}).get("value"), "measured_n": get(m or {}, "overall.n"),
               "measured_p10": get(m or {}, "overall.p10"), "measured_p50": get(m or {}, "overall.p50"),
               "measured_p90": get(m or {}, "overall.p90"), "file": (m or {}).get("file"),
               "blocker": (m or {}).get("blocker")}
        exhibited = tval is not None and (tstats.get("n") or 0) != 0 if "fixed" not in t else tval is not None
        if not m or m.get("status") != "measured":
            row["verdict"] = "unmeasured" if exhibited else "not_exhibited"
        elif not exhibited:
            row["verdict"] = "false_positive"
        else:
            e = err_of(kind, tval, m.get("value"))
            row["error"] = e
            ok = e is not None and abs(e) <= tol + 1e-9
            if kind in ("num", "rel") and "fixed" not in t:
                pe = {q: err_of(kind, tstats.get(q), get(m, f"overall.{q}")) for q in ("p10", "p50", "p90")}
                row["pct_errors"] = pe
                ok = ok and all(v is not None and abs(v) <= tol + 1e-9 for v in pe.values())
            # coverage: per-video keys may be measured in fewer videos than exhibit the style (reported, not a
            # value error); MORE videos than exhibit it means the analyzer saw it where it is absent -> fail.
            # Keys observed per EVENT (silence ramps, SFX events) have their own n.
            if kind in ("num", "rel", "color") and "fixed" not in t and key not in PER_EVENT_KEYS and \
                    row["measured_n"] is not None and row["truth_n"] is not None:
                row["coverage"] = f"{row['measured_n']}/{row['truth_n']}"
                if row["measured_n"] > row["truth_n"]:
                    row["n_excess"] = True
                    ok = False
            row["verdict"] = "pass" if ok else "fail"
        rows.append(row)
    return rows


def font_equivalence(r: Path, rows: list[dict]) -> None:
    """Diagnostic for size_px / line_spacing (the verdict against the truth is NOT changed).

    size_px is an EM size, so the analyzer converts the measured Hangul ink height with the ink/em ratio of
    a calibration font (the role's font in the preset at analysis time).  When that font is not the
    reference's font the number differs from the truth even with an exact ink height.  The font-equivalent
    truth = truth x ratio(truth font) / ratio(calibration font) is what an exact analyzer must report;
    rendering the calibration font at that size reproduces the reference ink height."""
    from shortkit.reference.textboxes import calibrate_font

    tp = ry(r / "presets/mocktruth/preset.yaml")
    cal_fonts: dict[str, Counter] = {}
    for n in range(1, 6):
        cap = rj(r / f"presets/joshuamagazine/analysis/SYNTHmock{n:02d}/captions.json", {}) or {}
        for it in cap.get("items") or []:
            f = get(it, "style.size_calibration.font")
            if f:
                cal_fonts.setdefault(it["role"], Counter())[f] += 1
    for row in rows:
        k = row["key"]
        if not (k.startswith("text.roles.") and k.endswith((".size_px", ".line_spacing"))):
            continue
        role = k.split(".")[2]
        if role not in cal_fonts or row.get("truth_value") is None or row.get("measured_value") is None:
            continue
        cf = cal_fonts[role].most_common(1)[0][0]
        tf = tp["text"]["roles"][role]["font_name"]
        a_, b_ = calibrate_font(tf), calibrate_font(cf)
        if not a_ or not b_:
            continue
        f = a_["ratio_em"] / b_["ratio_em"]
        eq = row["truth_value"] * f if k.endswith(".size_px") else row["truth_value"] / f
        err = (row["measured_value"] - eq) / eq
        row["font_equivalence"] = {"truth_font": tf, "calibration_font": cf, "ratio_truth_over_calib": round(f, 4),
                                   "font_equivalent_truth": round(eq, 3), "rel_error": round(err, 4),
                                   "within_tolerance": abs(err) <= row["tolerance"]}


def compare_catalog(r: Path, truth: dict) -> dict:
    cat = rj(r / "presets/joshuamagazine/sfx_catalog.json", {}) or {}
    smap = ry(r / "presets/joshuamagazine/sfx_map.yaml", {}) or {}
    fm = ry(r / "presets/joshuamagazine/formats.yaml", {}) or {}
    out = {"catalog_status": cat.get("status"), "types": []}
    for t in cat.get("types") or []:
        ex = t.get("examples") or []
        m = (smap.get("types") or {}).get(t["type_id"]) or {}
        out["types"].append({"type_id": t["type_id"], "class": t.get("class"), "n_events": t.get("n_events"),
                             "n_videos": t.get("n_videos"), "per_video_count": get(t, "per_video_count.overall"),
                             "offset_to_event_s": t.get("offset_to_event_s"), "gain_db_rel_mix": t.get("gain_db_rel_mix"),
                             "screen_event_mode": get(t, "screen_event.mode"),
                             "prev_caption_role_mode": get(t, "prev_caption_role.mode"),
                             "examples": [(e.get("video_id"), e.get("t")) for e in ex],
                             "map_status": m.get("status"), "map_file": m.get("file"), "similarity": m.get("similarity")})
    out["per_video_total"] = cat.get("per_video_total")
    out["formats"] = {"status": fm.get("status"), "assignments": fm.get("assignments"),
                      "table": [{k: e.get(k) for k in ("format_id", "structure_type", "n", "representative")}
                                for e in fm.get("table") or []]}
    return out


def _fmt(v) -> str:
    if v is None:
        return "–"
    if isinstance(v, float):
        return f"{v:.4g}"
    if isinstance(v, (list, dict)):
        return json.dumps(v, ensure_ascii=False).replace("|", "\\|")
    return str(v).replace("|", "\\|")


def md_table(res: dict) -> str:
    """Markdown accuracy table (every key): truth n/p10/p50/p90 vs measured n/p10/p50/p90, verdict."""
    head = ("| key | 계열(허용) | 참값 | 참값 n / p10 / p50 / p90 | 측정값 | 측정 n / p10 / p50 / p90 | 판정 |\n"
            "|---|---|---|---|---|---|---|")
    out = [head]
    for x in res["rows"]:
        tv = " / ".join(_fmt(x.get(k)) for k in ("truth_n", "truth_p10", "truth_p50", "truth_p90"))
        mv = " / ".join(_fmt(x.get(k)) for k in ("measured_n", "measured_p10", "measured_p50", "measured_p90"))
        verdict = x["verdict"]
        fe = x.get("font_equivalence")
        if fe:
            verdict += f" (글꼴 환산 {fe['font_equivalent_truth']:.4g}, 오차 {fe['rel_error'] * 100:+.1f}%)"
        out.append(f"| `{x['key']}` | {x['family']} ({_fmt(x['tolerance'])}) | {_fmt(x['truth_value'])} | {tv} | "
                   f"{_fmt(x['measured_value'])} | {mv} | {verdict} |")
    return "\n".join(out)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["truth", "compare", "table"])
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)
    r = root()
    tp = r / "mockloop_truth.json"
    if a.cmd == "table":
        print(md_table(rj(Path(a.out) if a.out else r / "mockloop_accuracy.json")))
        return 0
    if a.cmd == "truth":
        t = build_truth(r)
        tp.write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"truth: {len(t['keys'])} keys -> {tp}")
        return 0
    truth = rj(tp)
    rows = compare(r, truth)
    font_equivalence(r, rows)
    cat = compare_catalog(r, truth)
    res = {"schema": "mockloop.accuracy/1", "synthetic": True, "tolerances": TOL, "rows": rows, "catalog": cat,
           "catalog_truth": truth["sfx_catalog"],
           "summary": dict(Counter(x["verdict"] for x in rows))}
    outp = Path(a.out) if a.out else r / "mockloop_accuracy.json"
    outp.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res["summary"], ensure_ascii=False))
    for x in rows:
        if x["verdict"] in ("fail", "false_positive", "unmeasured"):
            print(f"{x['verdict']:<14} {x['key']:<48} truth={x['truth_value']!s:<22} meas={x['measured_value']!s:<22} "
                  f"err={x.get('error')} n={x['truth_n']}/{x['measured_n']} {str(x.get('blocker') or '')[:90]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
