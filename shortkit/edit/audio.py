"""Audio plan (resolve side): BGM, ducking envelope, intentional silences, kept originals, SFX.

Rules enforced here (user's audio rules):
- Original sound is OFF unless a segment keeps it (``original_audio.keep`` with a reason).
- BGM is ducked ONLY under kept original-audio ranges (kept dialogue).  SFX and cuts are never
  a reason to duck: the envelope is built from kept ranges and plan.bgm.silences only.
- Intentional silences mute the BGM with ``audio.silence.fade_s`` ramps.
- BGM must be a clean music file: plan.bgm.path or preset ``audio.bgm.track_id`` looked up in
  ``assets/library/music/index.yaml`` (or ``music_library_root`` from local.yaml).
- BGM identity is title AND version: the library entry's title/version must equal the preset's
  audio.bgm.title / audio.bgm.version (``check_bgm_identity``; a different version is a different track).
  The used section starts at plan.bgm.section_start_s or else the preset's audio.bgm.section_start_s.

Gain semantics (shared with the renderer): audio.bgm.gain_db, audio.sfx.gain_db_default / plan
sfx gain_db are levels AT THE FINAL PROGRAM LOUDNESS (gain applied to the clean file / SFX file).
``ref audio-measure`` measures audio.bgm.gain_db that way (clean-file LS gain + target_lufs -
reference mix LUFS), so the master's loudness normalisation is a small trim; the foreground safety
limiter may reduce SFX / kept originals by at most audio.loudness.max_limiter_db (``shortkit.edit.render``).

Kept original sound is different: audio.original.keep_gain_db (and a plan's
``timeline[].original_audio.gain_db``, same unit) is the kept speech LOUDNESS relative to the programme
loudness in LU -- what ``ref audio-measure`` emits (value_semantics "LU re programme loudness": kept
speech integrated loudness - mix integrated loudness).  The applied gain is therefore
``T + keep_gain_db - L_src`` with T = audio.loudness.integrated_lufs and L_src the measured integrated
loudness (EBU R128, ``kept_audio_loudness``) of the kept source audio of that clip -- or, when the clip
keeps less than KEPT_LEVEL_MIN_S of audio, of everything kept from that source.  QA measures the same
quantity on the output (``shortkit.qa.checks._rows_original``).
"""
from __future__ import annotations

from pathlib import Path

from .. import config, paths
from ..util.jsonio import read_yaml
from ..util.media import MediaError, probe
from . import sfxmap
from .ir import AudioPlan, Bgm, Clip, OriginalAudio, SfxPlacement

SILENCE_DB = -120.0      # envelope floor meaning "muted" (render maps <= -120 dB to exact 0)
# kept audio needed for an EBU R128 integrated loudness: one 400 ms gating block (ffmpeg ebur128 reports
# -70 LUFS = "none" below it; measured: 0.3 s -> -70, 0.4 s -> defined).  The reference analyzer asks
# 1.0 s of speech (KEEP_LEVEL_MIN_S) for a stable per-video statistic; here one clip's level is needed.
KEPT_LEVEL_MIN_S = 0.4
LEVEL_SR = 48000


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


def library_path(stored: str) -> Path:
    """Root-relative path or ``$music_library_root/...`` / ``$sfx_library_root/...`` token path
    (``shortkit.reference.separation.resolve_stored``) -> absolute path."""
    if stored.startswith("$"):
        from ..reference.separation import resolve_stored

        return Path(resolve_stored(stored))
    return paths.absp(stored)


def _index_entry(tracks, track_id: str) -> dict | None:
    """index.yaml ``tracks`` as a mapping {track_id: entry} or a list of entries keyed ``track_id``
    (assets/library/music/README.md) or ``id``."""
    if isinstance(tracks, dict):
        ent = tracks.get(track_id)
        return ent if isinstance(ent, dict) else None
    if isinstance(tracks, list):
        return next((t for t in tracks if isinstance(t, dict)
                     and (t.get("track_id") == track_id or t.get("id") == track_id)), None)
    return None


def lookup_track(track_id: str) -> tuple[str | None, dict]:
    """track id -> (root-relative path | None, index entry).

    Library roots and entry files may be ``$music_library_root/...`` tokens.  A file outside the
    project cannot be stored in the IR (``_outside_root``: copy it into assets/library/music)."""
    for root in music_library_roots():
        try:
            idx = read_yaml(library_path(root) / "index.yaml", None)
        except FileNotFoundError:
            continue
        if not idx:
            continue
        ent = _index_entry(idx.get("tracks", idx) if isinstance(idx, dict) else idx, track_id)
        if not ent:
            continue
        f = ent.get("path") or ent.get("file")
        if not f:
            return None, ent
        cands = [f] if str(f).startswith("$") else [f, f"{root.rstrip('/')}/{f}"]
        for cand in cands:
            try:
                p = library_path(cand)
            except FileNotFoundError:
                continue
            if p.is_file():
                try:
                    return paths.relp(p), ent
                except ValueError:
                    return None, {**ent, "_outside_root": True}
        return None, ent
    return None, {}


def library_entry_for_path(stored: str) -> dict | None:
    """The music-library index entry whose file is ``stored`` (a plan.bgm.path), or None when the
    file is not a library track (then its title/version are unknown)."""
    try:
        want = paths.absp(stored).resolve()
    except Exception:
        return None
    for root in music_library_roots():
        try:
            idx = read_yaml(library_path(root) / "index.yaml", None)
        except FileNotFoundError:
            continue
        if not idx:
            continue
        tracks = idx.get("tracks", idx) if isinstance(idx, dict) else idx
        ents = list(tracks.values()) if isinstance(tracks, dict) else list(tracks or [])
        for ent in ents:
            if not isinstance(ent, dict):
                continue
            f = ent.get("path") or ent.get("file")
            if not f:
                continue
            cands = [f] if str(f).startswith("$") else [f, f"{root.rstrip('/')}/{f}"]
            for cand in cands:
                try:
                    if library_path(cand).resolve() == want:
                        return ent
                except (FileNotFoundError, OSError, ValueError):
                    continue
    return None


def _norm_ident(v) -> str:
    return " ".join(str(v).split()).casefold()


def check_bgm_identity(plan: dict, bcfg, ent: dict | None, source: str, issues: list[dict]) -> dict:
    """BGM identity = title AND version (a different version of the same song is a different track).

    ``source``: "track_id" (preset audio.bgm.track_id looked up in the music library) or "plan_path"
    (plan.bgm.path).  The library entry's title/version must equal the preset's audio.bgm.title /
    audio.bgm.version: a track_id entry that differs is always an error; a plan file that differs or
    cannot be identified is an error in production and a warning in test.  When the preset itself has
    no title/version (못 잼) nothing can be compared -- ``validate.check_audio`` reports that."""
    want_t, want_v = bcfg["title"], bcfg["version"]
    res = {"preset_title": want_t, "preset_version": want_v, "entry_title": (ent or {}).get("title"),
           "entry_version": (ent or {}).get("version"), "source": source, "match": None}
    if not want_t or not want_v:
        return res
    prod = plan["mode"] == "production"
    soft = "error" if (prod or source == "track_id") else "warn"
    where = "audio.bgm.track_id" if source == "track_id" else "bgm.path"
    if not ent:
        if source == "plan_path":
            issues.append(_issue("error" if prod else "warn", "bgm_identity_unknown",
                                 f"plan.bgm.path 파일이 음악 라이브러리(index.yaml)에 없어 프리셋 곡('{want_t}', 버전 {want_v})과 "
                                 "같은 곡·버전인지 확인할 수 없습니다", where))
        return res                      # track_id not found: bgm_track_missing is reported by the caller
    got_t, got_v = ent.get("title"), ent.get("version")
    if not got_t or not got_v:
        issues.append(_issue(soft, "bgm_entry_unidentified",
                             f"음악 라이브러리 항목에 제목·버전이 없습니다(title={got_t!r}, version={got_v!r}): "
                             f"프리셋 곡('{want_t}', 버전 {want_v})인지 확인 불가", where))
        return res
    bad = []
    if _norm_ident(got_t) != _norm_ident(want_t):
        bad.append(f"제목 '{got_t}' ≠ 프리셋 '{want_t}'")
    if _norm_ident(got_v) != _norm_ident(want_v):
        bad.append(f"버전 '{got_v}' ≠ 프리셋 '{want_v}'(다른 버전은 다른 트랙)")
    res["match"] = not bad
    if bad:
        issues.append(_issue(soft, "bgm_track_mismatch", "BGM 이 프리셋 곡과 다릅니다: " + ", ".join(bad), where))
    return res


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


def kept_audio_loudness(pieces: list[tuple[str, float, float]], sr: int = LEVEL_SR) -> dict:
    """Integrated loudness (EBU R128 via ``util.media.lufs``, the same measurement as the programme
    loudness) of kept source audio: ``pieces`` = [(stored path, src_start, src_end)], each read with
    ``util.media.read_audio``'s stereo convention (mono duplicated at unity -- exactly as the renderer
    places it on the stereo timeline) and concatenated.  -> {lufs | None, seconds, reason}."""
    import tempfile

    import numpy as np

    from ..util.media import lufs, read_audio, write_wav

    parts = []
    for path, a, b in pieces:
        if b > a:
            parts.append(read_audio(paths.absp(path), sr=sr, mono=False, start=float(a), duration=float(b - a)))
    x = np.concatenate(parts) if parts else np.zeros((0, 2), np.float32)
    secs = len(x) / sr
    if secs < KEPT_LEVEL_MIN_S:
        return {"lufs": None, "seconds": round(secs, 3),
                "reason": f"보존 원음 {secs:.2f}s < {KEPT_LEVEL_MIN_S:g}s (게이트 통합 음량을 잴 수 없음)"}
    with tempfile.TemporaryDirectory(prefix="shortkit_keptlvl_") as td:
        f = Path(td) / "kept.wav"
        write_wav(f, x, sr)
        v = lufs(f).get("integrated_lufs")
    if v is None or v <= -69.0:
        return {"lufs": None, "seconds": round(secs, 3), "reason": "보존 원음이 무음에 가까움(통합 음량 측정 불가)"}
    return {"lufs": float(v), "seconds": round(secs, 3), "reason": None}


def kept_levels(kept: list[dict]) -> dict[int, dict]:
    """Loudness of the kept source audio for every kept range (index into ``kept``): measured per clip
    (all its kept pieces), else -- when a clip keeps less than KEPT_LEVEL_MIN_S -- per source file
    (all kept pieces of that file).  -> {i: {lufs, seconds, scope, reason}}."""
    by_clip: dict[str, list[int]] = {}
    by_path: dict[str, list[int]] = {}
    for i, k in enumerate(kept):
        by_clip.setdefault(k["clip_id"], []).append(i)
        by_path.setdefault(k["path"], []).append(i)
    cache: dict[tuple, dict] = {}

    def measure(idx: list[int]) -> dict:
        key = tuple(idx)
        if key not in cache:
            cache[key] = kept_audio_loudness([(kept[j]["path"], kept[j]["src_start"], kept[j]["src_end"]) for j in idx])
        return cache[key]

    out: dict[int, dict] = {}
    for cid, idx in by_clip.items():
        m = measure(idx)
        scope = "clip"
        if m["lufs"] is None and m["seconds"] < KEPT_LEVEL_MIN_S:
            ms = measure(by_path[kept[idx[0]]["path"]])
            if ms["lufs"] is not None or ms["seconds"] >= KEPT_LEVEL_MIN_S:
                m, scope = ms, "source"
        for j in idx:
            out[j] = {**m, "scope": scope}
    return out


def kept_speech(path: str, src_start: float, src_end: float) -> dict:
    """Speech spans (SOURCE s) of a kept audio file inside [src_start, src_end] (``audio_checks.speech_spans``)."""
    from .audio_checks import speech_spans

    sp = speech_spans(path)
    if sp["status"] != "measured":
        return {"status": "unmeasured", "spans": [], "reason": sp.get("reason")}
    spans = [[round(max(a, src_start), 4), round(min(b, src_end), 4)] for a, b in sp["spans"]
             if min(b, src_end) > max(a, src_start)]
    return {"status": "measured", "spans": spans, "reason": None}


def duck_pieces(originals: list[OriginalAudio]) -> list[tuple[float, float]]:
    out = []
    for o in originals:
        if o.speech_status != "measured":
            out.append((o.out_start, o.out_end))
            continue
        for a, b in o.speech:
            out.append((round(o.out_start + (a - o.src_start) / o.speed, 6), round(o.out_start + (b - o.src_start) / o.speed, 6)))
    return out


def bgm_loop_xfade_s(preset: config.Preset) -> float | None:
    """audio.bgm.loop_xfade_s (rule key: equal-power crossfade at the BGM loop point), None when the
    preset does not define it -- callers turn that into an error, never into a default."""
    try:
        v = preset.get("audio.bgm.loop_xfade_s")
    except KeyError:
        return None
    return None if v is None else float(v)


# ----------------------------------------------------------------------------- main
def build_audio_plan(plan: dict, preset: config.Preset, clips: list[Clip], duration: float, sources: dict,
                     issues: list[dict]) -> AudioPlan:
    a = preset.section("audio")
    sr = int(a["sample_rate"])
    loud = a["loudness"]
    target_lufs, tp = float(loud["integrated_lufs"]), float(loud["true_peak_db"])
    max_lim, tol_lu = float(loud["max_limiter_db"]), float(loud["tolerance_lu"])
    if max_lim < 0:
        issues.append(_issue("error", "rule_max_limiter", f"audio.loudness.max_limiter_db={max_lim}: 0 이상이어야 합니다",
                             "audio.loudness.max_limiter_db"))
        max_lim = 0.0
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
    kept: list[dict] = []
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
            if not path or not (src and src.exists):
                continue                # missing source: reported by the source checks
        rel = float(oa["gain_db"]) if oa.get("gain_db") is not None else keep_gain
        kept.append({**k, "clip_id": clip.id, "path": path, "stem": stem, "rel_lu": rel, "where": where,
                     "reason": oa.get("reason", "")})
    levels = kept_levels(kept) if kept else {}
    for i, k in enumerate(kept):
        lv = levels[i]
        if lv["lufs"] is None:
            # no guess: without the source loudness the level rule (T + keep_gain_db - L_src) has no value
            issues.append(_issue("error", "original_level_unmeasured",
                                 f"보존 원음 음량(L_src)을 잴 수 없어 이득을 정할 수 없습니다: {lv['reason']} "
                                 "(audio.original.keep_gain_db = 프로그램 음량 대비 LU)", k["where"]))
            continue
        sp = kept_speech(k["path"], k["src_start"], k["src_end"])
        originals.append(OriginalAudio(
            clip_id=k["clip_id"], path=k["path"], stem=k["stem"], src_start=k["src_start"], src_end=k["src_end"],
            out_start=k["out_start"], out_end=k["out_end"], speed=k["clip"].speed,
            gain_db=round(target_lufs + k["rel_lu"] - lv["lufs"], 3), fade_s=fade_s, reason=k["reason"],
            speech=sp["spans"], speech_status=sp["status"]))
    # ducking only under kept SPEECH (user rule): the detected speech inside each kept range, mapped to output time;
    # a kept range whose speech could not be measured ducks whole (validate reports it), one without speech not at all
    duck_ranges = merge_ranges(duck_pieces(originals))

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
            else:
                check_bgm_identity(plan, bcfg, library_entry_for_path(path), "plan_path", issues)
        elif track_id:
            path, ent = lookup_track(track_id)
            if path is None:
                msg = ("음악 라이브러리 파일이 프로젝트 밖에 있습니다(assets/library/music 으로 복사)"
                       if ent.get("_outside_root") else f"BGM track_id '{track_id}' 를 음악 라이브러리에서 찾지 못함")
                issues.append(_issue("error", "bgm_track_missing", msg, "audio.bgm.track_id"))
            check_bgm_identity(plan, bcfg, ent or None, "track_id", issues)
        else:
            sev = "error" if plan["mode"] == "production" else "warn"
            issues.append(_issue(sev, "bgm_unidentified",
                                 "BGM 미식별(못 잼): plan.bgm.path 도 preset audio.bgm.track_id 도 없습니다", "bgm"))
        # used section and speed: the preset's (reference) values unless the plan overrides them; an override
        # is reported -- a different part / speed of the same song is NOT the reference's music (user rule)
        section_p, tempo_p = float(bcfg["section_start_s"]), float(bcfg["tempo_ratio"])
        section = float(pb["section_start_s"]) if pb.get("section_start_s") is not None else section_p
        tempo = float(pb["tempo_ratio"]) if pb.get("tempo_ratio") is not None else tempo_p
        gain_p = float(bcfg["gain_db"])
        gain = float(pb["gain_db"]) if pb.get("gain_db") is not None else gain_p
        # a plan override of the reference's music section / speed / level is a style deviation: error in production
        ov_sev = "error" if plan["mode"] == "production" else "warn"
        for key, got, want, unit in (("section_start_s", section, section_p, "s"), ("tempo_ratio", tempo, tempo_p, ""),
                                     ("gain_db", gain, gain_p, " dB")):
            if pb.get(key) is not None and abs(got - want) > 1e-3:
                org = preset.origin(f"audio.bgm.{key}")
                issues.append(_issue(ov_sev, f"bgm_{key}_override",
                                     f"plan.bgm.{key}={got}{unit} 가 프리셋 audio.bgm.{key}={want}{unit}"
                                     f"({'임시값·못 잼' if org == 'provisional' else org}) 와 다릅니다: 같은 곡의 "
                                     "다른 구간/속도/크기는 레퍼런스 음악과 일치가 아님(의도한 변경이면 requested_changes 로)",
                                     f"bgm.{key}"))
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
                        # the renderer loops back to section_start with an equal-power crossfade of this length
                        xf = bgm_loop_xfade_s(preset)
                        seg = (bdur - section) / tempo
                        if xf is None:
                            issues.append(_issue("error", "bgm_loop_xfade_missing",
                                                 "audio.bgm.loop=true 로 BGM 을 반복해야 하지만 프리셋에 audio.bgm.loop_xfade_s(규칙 키) "
                                                 "가 없습니다 — 프리셋/설정 담당이 추가해야 함(추측값으로 반복하지 않음)",
                                                 "audio.bgm.loop_xfade_s"))
                        elif xf <= 0 or 2 * xf >= seg:
                            issues.append(_issue("error", "bgm_loop_xfade", f"audio.bgm.loop_xfade_s={xf}: 0 보다 크고 반복 구간"
                                                 f"({seg:.2f}s)의 절반보다 짧아야 합니다", "audio.bgm.loop_xfade_s"))
                        else:
                            issues.append(_issue("warn", "bgm_loop",
                                                 f"BGM 반복: 원곡 {section:.2f}s~끝({bdur:.2f}s, 속도 {tempo:g}배 → {seg:.2f}s)이 "
                                                 f"영상 {duration:.2f}s 보다 짧아 section_start 로 되감아 이어 붙임"
                                                 f"(등전력 크로스페이드 {xf:g}s, audio.bgm.loop=true)", "bgm"))
                    else:
                        sev = "error" if plan["mode"] == "production" else "warn"
                        issues.append(_issue(sev, "bgm_too_short",
                                             f"BGM 이 부족합니다: 필요 {need:.2f}s(원곡 기준) > 파일 {bdur:.2f}s", "bgm"))
            except MediaError as e:
                issues.append(_issue("error", "bgm_probe_failed", f"BGM 을 읽지 못함: {e}", "bgm.path"))
        env = build_envelope(duration, duck_ranges, depth, attack, release, silences, sil_fade)
        bgm = Bgm(path=path, track_id=track_id if not pb.get("path") else None, section_start_s=section,
                  tempo_ratio=tempo, gain_db=gain, fade_in_s=fi, fade_out_s=fo, envelope=env, silences=silences,
                  duck_ranges=duck_ranges, loop=loop)

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
                     sfx=placements, max_limiter_db=max_lim, loudness_tolerance_lu=tol_lu)
