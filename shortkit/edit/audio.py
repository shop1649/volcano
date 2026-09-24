"""Audio plan (resolve side): BGM, ducking envelope, intentional silences, kept originals, SFX.

Rules enforced here (user's audio rules):
- Original sound is OFF unless a segment keeps it (``original_audio.keep`` with a reason).
- BGM is ducked ONLY under kept original-audio ranges (kept dialogue).  SFX and cuts are never
  a reason to duck: the envelope is built from kept ranges and plan.bgm.silences only.
- Intentional silences mute the BGM with ``audio.silence.fade_s`` ramps.
- BGM must be a clean music file: plan.bgm.path or preset ``audio.bgm.track_id`` looked up in
  ``assets/library/music/index.yaml`` (or ``music_library_root`` from local.yaml).
"""
from __future__ import annotations

from pathlib import Path

from .. import config, paths
from ..util.jsonio import read_yaml
from ..util.media import MediaError, probe
from . import sfxmap
from .ir import AudioPlan, Bgm, Clip, OriginalAudio, SfxPlacement

SILENCE_DB = -120.0      # envelope floor meaning "muted" (render maps <= -120 dB to exact 0)


def _issue(sev, code, msg, where=""):
    from .resolve import issue

    return issue(sev, code, msg, where)


# ----------------------------------------------------------------------------- music library
def music_library_roots() -> list[str]:
    roots = ["assets/library/music"]
    loc = sfxmap.local_settings().get("music_library_root")
    if loc:
        roots.append(loc)
    return roots


def lookup_track(track_id: str) -> tuple[str | None, dict]:
    """track id -> (root-relative path | None, index entry)."""
    for root in music_library_roots():
        idx = read_yaml(paths.absp(root) / "index.yaml", None)
        if not idx:
            continue
        tracks = idx.get("tracks", idx)
        ent = None
        if isinstance(tracks, dict):
            ent = tracks.get(track_id)
        elif isinstance(tracks, list):
            ent = next((t for t in tracks if isinstance(t, dict) and t.get("id") == track_id), None)
        if not ent:
            continue
        f = ent.get("path") or ent.get("file")
        if not f:
            return None, ent
        for cand in (f, str(Path(root) / f)):
            p = paths.absp(cand)
            if p.is_file():
                try:
                    return paths.relp(p), ent
                except ValueError:
                    return None, {**ent, "_outside_root": True}
        return None, ent
    return None, {}


# ----------------------------------------------------------------------------- envelopes
def merge_ranges(ranges: list[tuple[float, float]], join_gap: float = 0.0) -> list[tuple[float, float]]:
    out: list[list[float]] = []
    for a, b in sorted(ranges):
        if out and a <= out[-1][1] + join_gap:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(round(a, 6), round(b, 6)) for a, b in out]


def _ramp_shape(r: tuple[float, float], pre: float, post: float):
    """Trapezoid 0 -> 1 over [a-pre, a], 1 on [a, b], 1 -> 0 over [b, b+post]."""
    a, b = r

    def f(t: float) -> float:
        if t <= a - pre or t >= b + post:
            return 0.0
        if t < a:
            return (t - (a - pre)) / pre if pre > 0 else 1.0
        if t <= b:
            return 1.0
        return 1.0 - (t - b) / post if post > 0 else 0.0
    return f, [a - pre, a, b, b + post]


def build_envelope(duration: float, duck_ranges: list[tuple[float, float]], depth_db: float, attack_s: float,
                   release_s: float, silences: list[tuple[float, float]], fade_s: float) -> list[tuple[float, float]]:
    """Piecewise-linear BGM gain envelope in dB over output time.

    Only two things shape it: ducking under kept original audio, and intentional silences.
    Ranges closer than their ramps are merged first, so the sum of trapezoids is exact."""
    shapes = []
    for r in merge_ranges(duck_ranges, attack_s + release_s):
        f, bps = _ramp_shape(r, attack_s, release_s)
        shapes.append((f, -abs(depth_db), bps))
    for r in merge_ranges(silences, 2 * fade_s):
        f, bps = _ramp_shape(r, fade_s, fade_s)
        shapes.append((f, SILENCE_DB, bps))
    pts = {0.0, round(duration, 6)}
    for _, _, bps in shapes:
        pts.update(round(min(max(x, 0.0), duration), 6) for x in bps)
    env = []
    for t in sorted(pts):
        db = sum(g * f(t) for f, g, _ in shapes)
        env.append((t, round(max(db, SILENCE_DB * 1.0), 4) + 0.0))
    # drop redundant collinear interior points (keeps the envelope small and exact)
    out = [env[0]]
    for i in range(1, len(env) - 1):
        (t0, v0), (t1, v1), (t2, v2) = out[-1], env[i], env[i + 1]
        if t2 > t0 and abs(v0 + (v2 - v0) * (t1 - t0) / (t2 - t0) - v1) < 1e-6:
            continue
        out.append(env[i])
    if len(env) > 1:
        out.append(env[-1])
    return out


def envelope_db_at(env: list[tuple[float, float]], t: float) -> float:
    if not env:
        return 0.0
    if t <= env[0][0]:
        return env[0][1]
    for (t0, v0), (t1, v1) in zip(env, env[1:]):
        if t <= t1:
            return v0 if t1 <= t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return env[-1][1]


# ----------------------------------------------------------------------------- originals
def kept_original_ranges(plan: dict, clips: list[Clip], issues: list[dict], sources: dict) -> list[dict]:
    """Per kept range: {clip, seg, src_start, src_end, out_start, out_end} (freeze splits ranges)."""
    by_id = {c.id: c for c in clips}
    out = []
    for seg in plan["timeline"]:
        oa = seg.get("original_audio") or {}
        if not oa.get("keep"):
            continue
        where = f"timeline[{seg['id']}].original_audio"
        clip = by_id.get(seg["id"])
        if clip is None:
            continue
        ranges = oa.get("ranges") or [[clip.src_in, clip.src_out]]
        for a, b in ranges:
            a, b = float(a), float(b)
            if b <= a or a < clip.src_in - 1e-6 or b > clip.src_out + 1e-6:
                issues.append(_issue("error", "original_range", f"보존 구간 [{a}, {b}] 이 세그먼트 "
                                     f"[{clip.src_in}, {clip.src_out}] 안에 있어야 합니다", where))
                continue
            pieces = [(a, b)]
            f = clip.freeze
            if f is not None and a < f.src_t < b:
                pieces = [(a, f.src_t), (f.src_t, b)]
            for pa, pb in pieces:
                # audio after a mid-segment freeze resumes when the hold ends (silent during the hold)
                after_hold = f is not None and f.src_t < clip.src_out - 1e-9 and pa >= f.src_t - 1e-9
                os_ = clip.out_start + (pa - clip.src_in) / clip.speed + (f.hold if after_hold else 0.0)
                out.append({"clip": clip, "seg": seg, "src_start": pa, "src_end": pb, "out_start": round(os_, 6),
                            "out_end": round(os_ + (pb - pa) / clip.speed, 6)})
    return out


# ----------------------------------------------------------------------------- main
def build_audio_plan(plan: dict, preset: config.Preset, clips: list[Clip], duration: float, sources: dict,
                     issues: list[dict]) -> AudioPlan:
    a = preset.section("audio")
    sr = int(a["sample_rate"])
    loud = a["loudness"]
    target_lufs, tp = float(loud["integrated_lufs"]), float(loud["true_peak_db"])
    orig_cfg = a["original"]
    if orig_cfg["default"] not in ("off", False):
        issues.append(_issue("error", "rule_original_default",
                             f"audio.original.default={orig_cfg['default']!r}: 원본 소리는 기본 OFF 여야 합니다(사용자 규칙)",
                             "audio.original.default"))
    keep_gain, fade_s = float(orig_cfg["keep_gain_db"]), float(orig_cfg["fade_s"])
    duck = a["ducking"]
    if duck["only_under_kept_dialogue"] is not True:
        issues.append(_issue("error", "rule_ducking_scope",
                             "audio.ducking.only_under_kept_dialogue 는 true 여야 합니다(사용자 규칙)",
                             "audio.ducking.only_under_kept_dialogue"))
    depth, attack, release = float(duck["depth_db"]), float(duck["attack_s"]), float(duck["release_s"])
    sil_fade = float(a["silence"]["fade_s"])

    # --- originals (kept ranges only)
    originals: list[OriginalAudio] = []
    for k in kept_original_ranges(plan, clips, issues, sources):
        seg, clip = k["seg"], k["clip"]
        oa = seg["original_audio"]
        where = f"timeline[{seg['id']}].original_audio"
        src = sources.get(seg["source"])
        stem = oa.get("stem") or "raw"
        if stem == "vocals":
            vp = (src.plan.get("vocals_path") if src else None)
            if not vp or not paths.absp(vp).is_file():
                issues.append(_issue("error", "vocals_missing", "stem=vocals 인데 sources[].vocals_path 파일이 없습니다", where))
                continue
            path = vp
        else:
            path = src.path if src else None
            if src and src.exists and not src.has_audio:
                issues.append(_issue("error", "original_no_audio", f"소스 {src.id} 에 오디오 스트림이 없습니다", where))
                continue
        originals.append(OriginalAudio(
            clip_id=clip.id, path=path, stem=stem, src_start=k["src_start"], src_end=k["src_end"],
            out_start=k["out_start"], out_end=k["out_end"], speed=clip.speed,
            gain_db=float(oa["gain_db"]) if oa.get("gain_db") is not None else keep_gain, fade_s=fade_s,
            reason=oa.get("reason", "")))
    duck_ranges = merge_ranges([(o.out_start, o.out_end) for o in originals])

    # --- BGM
    bcfg = a["bgm"]
    pb = plan.get("bgm") or {}
    bgm = None
    track_id = bcfg["track_id"]
    loop = bool(bcfg["loop"])
    if pb.get("enabled", True):
        path = pb.get("path")
        if path:
            if not paths.absp(path).is_file():
                issues.append(_issue("error", "bgm_missing", f"BGM 파일이 없습니다: {path}", "bgm.path"))
                path = None
        elif track_id:
            path, ent = lookup_track(track_id)
            if path is None:
                msg = ("음악 라이브러리 파일이 프로젝트 밖에 있습니다(assets/library/music 으로 복사)"
                       if ent.get("_outside_root") else f"BGM track_id '{track_id}' 를 음악 라이브러리에서 찾지 못함")
                issues.append(_issue("error", "bgm_track_missing", msg, "audio.bgm.track_id"))
        else:
            sev = "error" if plan["mode"] == "production" else "warn"
            issues.append(_issue(sev, "bgm_unidentified",
                                 "BGM 미식별(못 잼): plan.bgm.path 도 preset audio.bgm.track_id 도 없습니다", "bgm"))
        section = float(pb["section_start_s"]) if pb.get("section_start_s") is not None else float(bcfg["section_start_s"])
        tempo = float(pb["tempo_ratio"]) if pb.get("tempo_ratio") is not None else float(bcfg["tempo_ratio"])
        gain = float(pb["gain_db"]) if pb.get("gain_db") is not None else float(bcfg["gain_db"])
        fi, fo = float(bcfg["fade_in_s"]), float(bcfg["fade_out_s"])
        if tempo <= 0:
            issues.append(_issue("error", "bgm_tempo", "tempo_ratio 는 0보다 커야 합니다", "bgm.tempo_ratio"))
            tempo = 1.0
        silences = []
        for s in pb.get("silences") or []:
            s0, s1 = float(s["start"]), float(s["end"])
            if s1 <= s0 or s0 < 0 or s1 > duration + 1e-6:
                issues.append(_issue("error", "silence_range", f"정적 구간 [{s0}, {s1}] 이 영상 길이 0..{duration:.2f} 안에 있어야 합니다",
                                     "bgm.silences"))
                continue
            silences.append((s0, s1))
        if path:
            try:
                bdur = probe(paths.absp(path)).duration
                need = section + duration * tempo
                if bdur + 1e-3 < need:
                    if loop:
                        issues.append(_issue("error", "bgm_loop_unsupported",
                                             "BGM 이 짧고 audio.bgm.loop=true 이지만 반복 이어붙이기는 렌더러에 구현되지 않음", "bgm"))
                    else:
                        sev = "error" if plan["mode"] == "production" else "warn"
                        issues.append(_issue(sev, "bgm_too_short",
                                             f"BGM 이 부족합니다: 필요 {need:.2f}s(원곡 기준) > 파일 {bdur:.2f}s", "bgm"))
            except MediaError as e:
                issues.append(_issue("error", "bgm_probe_failed", f"BGM 을 읽지 못함: {e}", "bgm.path"))
        env = build_envelope(duration, duck_ranges, depth, attack, release, silences, sil_fade)
        bgm = Bgm(path=path, track_id=track_id if not pb.get("path") else None, section_start_s=section,
                  tempo_ratio=tempo, gain_db=gain, fade_in_s=fi, fade_out_s=fo, envelope=env, silences=silences,
                  duck_ranges=duck_ranges)

    # --- SFX
    sfx_cfg = a["sfx"]
    gain_default = float(sfx_cfg["gain_db_default"])
    smap = sfxmap.load_map(preset)
    placements: list[SfxPlacement] = []
    for s in plan.get("sfx") or []:
        where = f"sfx[{s['id']}]"
        look = sfxmap.lookup(preset, s["type"], smap)
        path = None
        if s.get("file"):
            if paths.absp(s["file"]).is_file():
                path = s["file"]
            else:
                issues.append(_issue("error", "sfx_file_missing", f"효과음 파일이 없습니다: {s['file']}", where))
        elif look["file"]:
            path = look["file"]
        else:
            sev = "error" if plan["mode"] == "production" else "warn"
            issues.append(_issue(sev, "sfx_unresolved",
                                 f"효과음 '{s['type']}' 파일 미해결(맵 상태 {sfxmap.MAP_STATUS_KO[look['status']]}): "
                                 "production 렌더는 거부됩니다", where))
        ev = s["event"]
        placements.append(SfxPlacement(
            id=s["id"], type=s["type"], path=path, t=float(s["t"]),
            gain_db=float(s["gain_db"]) if s.get("gain_db") is not None else gain_default,
            event_t=float(ev["t"]), event_desc=ev["desc"], emotion=s.get("emotion"), map_status=look["status"]))
    return AudioPlan(sample_rate=sr, target_lufs=target_lufs, true_peak_db=tp, bgm=bgm, originals=originals,
                     sfx=placements)
