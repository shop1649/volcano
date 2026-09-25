"""Plan rule checks -> issues ``[{severity: error|warn, code, message_ko, where}]``.

Every rule below is enforced in code (not only documented).  ``error`` blocks resolve/render;
``warn`` is reported.  Unmeasured things are never passed silently: they produce at least a
warning (and an error in production unless ``allow_unmeasured``).
"""
from __future__ import annotations

import math
import re
from collections import defaultdict
from pathlib import Path

from .. import config, paths
from ..util.hashing import sha256_file
from ..util.jsonio import read_json, read_jsonl, read_yaml
from . import sfxmap
from .plan import (TEST_FORMAT_ID, PlanError, approval_state_for, approved_snapshot_plan, plan_diff_sections,
                   schema_errors, series_first_episode)
from .resolve import (EPS, ResolveContext, clips_at, issue, map_src_rect, rects_intersect, resolve_context,
                      src_time_at)

GROUNDING_FREE_ROLES = ("title", "description")
SFX_STACK_WINDOW_S = 0.5          # user rule: never stack the same effect repeatedly
CUT_WORDS = {"컷", "cut", "장면전환", "장면 전환", "scene change", "scenechange", "transition", "전환"}
NON_CUT_EVENT_KINDS = {"freeze", "zoom_in", "zoom_out", "text_pop", "flash", "action", "reaction", "speech",
                       "impact", "appear", "reveal", "emotion", "gesture"}
# narration = our own words (tone / branding rules apply); dialogue (real lines) and speaker labels do not
NARRATION_ROLES = ("title", "description", "situation", "reaction")
# text.tone.register values (the reference analyzer's REGISTER_MAP values + 혼합 = no single register)
TONE_REGISTERS = ("반말_구어체", "해요체", "음슴체", "합쇼체", "혼합")
# emoji = pictographs, or a symbol in emoji presentation (VS16) / keycap; plain text symbols (♪ ♥ ★ →) are not emoji
EMOJI_RE = re.compile("[\U0001F000-\U0001FAFF]|[\u2190-\u2BFF\u3030\u303D\u3297\u3299][\uFE0F\u20E3]|[0-9#*]\uFE0F?\u20E3")
SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+|\n+")
# own-branding patterns: an @handle (not an e-mail) or URL-like text
HANDLE_RE = re.compile(r"(?<![\w.])@[\w][\w.\-]*", re.UNICODE)
URL_RE = re.compile(r"(?:https?://|www\.)\S+|\b[\w\-]+(?:\.[\w\-]+)*\.(?:com|net|org|kr|co|tv|io|me|ly|gg|be|app|link|xyz|shop)"
                    r"\b(?:/\S*)?", re.IGNORECASE | re.ASCII)
# segments whose purpose makes a held tail the point (reaction shots, the ending)
TAIL_EXEMPT_PURPOSES = {"reaction", "outro", "반응", "마무리"}


def errors(issues: list[dict]) -> list[dict]:
    return [i for i in issues if i["severity"] == "error"]


def format_issues(issues: list[dict]) -> str:
    lab = {"error": "오류", "warn": "경고"}
    lines = [f"[{lab[i['severity']]}] {i['code']} @ {i['where'] or '-'}: {i['message_ko']}" for i in
             sorted(issues, key=lambda i: (i["severity"] != "error", i["where"]))]
    ne, nw = len(errors(issues)), len(issues) - len(errors(issues))
    lines.append(f"결과: 오류 {ne}건, 경고 {nw}건 → {'통과' if ne == 0 else '막힘'}")
    return "\n".join(lines)


# ----------------------------------------------------------------------------- preset / format
def check_preset_mixing(plan: dict, preset: config.Preset, out: list[dict]) -> bool:
    try:
        preset.assert_same_preset(plan["preset_id"], "plan.yaml")
    except config.PresetMixError as e:
        out.append(issue("error", "preset_mix", f"프리셋 섞임: {e}", "preset_id"))
        return False
    ok = True
    for key in ("structure.formats_file", "audio.sfx.catalog", "audio.sfx.map"):
        rel = preset.get(key)
        p = paths.absp(rel)
        d = (read_yaml(p, {}) if p.suffix in (".yaml", ".yml") else _read_json(p)) if p.is_file() else {}
        pid = (d or {}).get("preset_id")
        if pid:
            try:
                preset.assert_same_preset(pid, rel)
            except config.PresetMixError as e:
                out.append(issue("error", "preset_mix", f"프리셋 섞임: {e}", key))
                ok = False
    return ok


def _read_json(p: Path):
    from ..util.jsonio import read_json

    return read_json(p, {})


def check_paths(plan: dict, out: list[dict]) -> None:
    """Stored paths are root-relative POSIX and never escape the project root."""
    cands = [(f"sources[{s['id']}].path", s.get("path")) for s in plan["sources"]]
    cands += [(f"sources[{s['id']}].vocals_path", s.get("vocals_path")) for s in plan["sources"]]
    cands += [("bgm.path", (plan.get("bgm") or {}).get("path")), ("output.path", (plan.get("output") or {}).get("path"))]
    cands += [(f"sfx[{x['id']}].file", x.get("file")) for x in plan.get("sfx") or []]
    for where, v in cands:
        if not v:
            continue
        pp = Path(str(v).replace("\\", "/"))
        if pp.is_absolute() or ".." in pp.parts or str(v).startswith("~") or "\\" in str(v):
            out.append(issue("error", "path_not_root_relative",
                             f"루트 기준 상대 POSIX 경로만 저장할 수 있습니다(절대 경로·'..' 금지): {v}", where))


def check_format(plan: dict, preset: config.Preset, out: list[dict]) -> None:
    rel = preset.get("structure.formats_file")
    fm = read_yaml(paths.absp(rel), None) or {}
    ids = [e.get("format_id") or e.get("id") for e in fm.get("table") or [] if isinstance(e, dict)]
    fid, mode = plan["format_id"], plan["mode"]
    if mode == "production":
        if fid == TEST_FORMAT_ID:
            out.append(issue("error", "format_unclassified", "production 모드에서는 format_id=UNCLASSIFIED 를 쓸 수 없습니다",
                             "format_id"))
        elif fm.get("status") != "measured":
            out.append(issue("error", "formats_unmeasured",
                             f"{rel} 상태가 measured 가 아님({fm.get('status')}, 못 잼): 포맷 분류 전에는 production 불가",
                             "format_id"))
        elif fid not in ids:
            out.append(issue("error", "format_unknown", f"format_id '{fid}' 가 {rel} 표에 없습니다", "format_id"))
    else:
        if fid == TEST_FORMAT_ID:
            out.append(issue("warn", "format_unclassified", "테스트 모드: 포맷 미분류(UNCLASSIFIED) — 포맷별 범위 검사는 못 함",
                             "format_id"))
        elif fid not in ids:
            out.append(issue("warn", "format_unknown", f"format_id '{fid}' 가 {rel} 표에 없습니다", "format_id"))


INTRO_UNRECORDED = ("미기재", "", "unmeasured", "못 잼")    # classify writes 미기재 for a blank intro label


def format_intro_variants(preset: config.Preset, format_id: str) -> tuple[list[str] | None, str]:
    """The measured intro variants (도입 방식) of ``format_id``: formats.yaml ``table[].intro_variants[].intro_type``
    (``reference.classify``: videos whose structure is the same and only the intro differs).  -> (variants, why):
    variants None = unmeasured (format table not measured, format missing, no variants, or a member whose intro was
    not recorded -- the set of variants is then incomplete)."""
    rel = preset.get("structure.formats_file")
    fm = read_yaml(paths.absp(rel), None) or {}
    if fm.get("status") != "measured":
        return None, f"{rel} 상태 {fm.get('status')}(못 잼): {str(fm.get('blocker') or '')[:160]}"
    row = next((e for e in fm.get("table") or [] if isinstance(e, dict)
                and (e.get("format_id") or e.get("id")) == format_id), None)
    if row is None:
        return None, f"포맷 {format_id} 가 {rel} 표에 없음"
    iv = row.get("intro_variants") or []
    names = [str(v.get("intro_type") if isinstance(v, dict) else v).strip() for v in iv]
    if not names:
        return None, f"포맷 {format_id} 의 intro_variants 가 비어 있음"
    blank = [n for n in names if n.casefold() in INTRO_UNRECORDED]
    if blank:
        return None, f"포맷 {format_id} 구성원 중 도입 방식이 기록되지 않은 영상이 있음(intro_type {blank[0]!r}) — 도입 변형 목록 불완전"
    return names, ""


def check_intro_type(plan: dict, preset: config.Preset, out: list[dict], allow_unmeasured: bool) -> None:
    """plan.intro_type must be one of the intro variants the reference shows for the plan's format (user: 도입 방식만
    다른 것과 전개 구조가 실제로 다른 것을 구분).  Production: missing / not a variant -> error; variants unmeasured
    -> error unless --allow-unmeasured.  Test mode: warnings."""
    prod = plan["mode"] == "production"
    sev = "error" if prod else "warn"
    un_sev = "error" if (prod and not allow_unmeasured) else "warn"
    it = str(plan.get("intro_type") or "").strip()
    if not it:
        out.append(issue(sev, "intro_type_missing",
                         "도입 방식(intro_type)이 없습니다: formats.yaml 의 이 포맷 intro_variants 중 하나를 적는다", "intro_type"))
    if plan["format_id"] == TEST_FORMAT_ID:
        out.append(issue("warn", "intro_variants_unmeasured",
                         "테스트 모드(포맷 미분류): 도입 방식을 레퍼런스 포맷의 도입 변형과 비교 못 함", "intro_type"))
        return
    variants, why = format_intro_variants(preset, plan["format_id"])
    if variants is None:
        out.append(issue(un_sev, "intro_variants_unmeasured",
                         f"포맷 {plan['format_id']} 의 도입 변형(intro_variants) 미측정(못 잼): {why} — "
                         f"intro_type {it or '(없음)'!r} 이 레퍼런스에 있는 도입인지 판정 불가", "intro_type"))
    elif it and it not in variants:
        out.append(issue(sev, "intro_type_unknown",
                         f"도입 방식 {it!r} 은 포맷 {plan['format_id']} 의 레퍼런스 도입 변형 {variants} 에 없습니다", "intro_type"))


# ----------------------------------------------------------------------------- sources / provenance
def _norm_url(u: str | None) -> str | None:
    return u.strip().rstrip("/") if isinstance(u, str) and u.strip() else None


def warehouse_records() -> dict[str, dict]:
    """Source warehouse records by id (``shortkit.sourcing.warehouse.load``)."""
    try:
        from ..sourcing import warehouse as wh

        rows = wh.load()
    except ImportError:          # sourcing area unavailable: read the agreed file format directly
        rows = read_jsonl(paths.absp("warehouse/candidates.jsonl"))
    recs: dict[str, dict] = {}
    for r in rows:
        if r.get("id"):
            recs[r["id"]] = {**recs.get(r["id"], {}), **r}
    return recs


WAREHOUSE_USABLE = ("selected", "used")


def exclusion_entries() -> list[dict]:
    try:
        from ..sourcing import exclusions as X

        return X.load()
    except ImportError:
        return [e for e in read_jsonl(paths.absp("warehouse/exclusions.jsonl")) if isinstance(e, dict)]


def excluded_url_hit(urls, entries: list[dict] | None = None) -> dict | None:
    """The sourcing URL rule (canonical ``url_key`` equality: watch?v= / shorts / youtu.be / query variants are
    the same video) -- ``shortkit.sourcing.exclusions.check_urls`` -- re-run on every validate (S5-03)."""
    from ..sourcing import exclusions as X

    return X.check_urls(list(urls), exclusion_entries() if entries is None else entries)


def reference_account_hit(rec: dict, entries: list[dict] | None = None) -> dict | None:
    """The record's uploader/channel is the reference channel itself (``exclusions.check_account``)."""
    from ..sourcing import exclusions as X

    return X.check_account(rec, exclusion_entries() if entries is None else entries)


def excluded_urls() -> dict[str, str]:
    """Raw exclusion URLs (kept for display); the rule itself is ``excluded_url_hit``."""
    urls: dict[str, str] = {}
    for e in exclusion_entries():
        if e.get("kind") == "url" and _norm_url(e.get("url")):
            urls[_norm_url(e["url"])] = e.get("reason") or "exclusions.jsonl(url)"
        elif e.get("kind") == "reference_footage":
            for u in [e.get("ref_url")] + list(e.get("original_urls") or []):
                if _norm_url(u):
                    urls[_norm_url(u)] = f"레퍼런스 영상 {e.get('ref_video_id')} 의 원본/주소"
    return urls


# generated test sources (``shortkit episode test-source`` etc.): bytes depend on the ffmpeg / TTS build, so a test
# plan may pin their CONTENT instead (sources[].test_fingerprint) -- test mode only, production keeps the sha rule
FINGERPRINT_SPEECH_TOL_S = 0.1


def video_content_md5(stored: str) -> str | None:
    """md5 of the decoded video frames (gray, 1/8 scale is not used: full frames, ffmpeg -f md5).  The H.264 decoder
    is bit-exact, so a stream-copied video gives the same value whatever ffmpeg muxed the container."""
    import subprocess

    from ..util.media import FFMPEG

    try:
        r = subprocess.run([FFMPEG, "-v", "error", "-nostdin", "-i", str(paths.absp(stored)), "-map", "0:v:0",
                            "-f", "md5", "-"], capture_output=True, text=True, timeout=600)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (r.stdout or "").strip()
    return out.split("=", 1)[1] if r.returncode == 0 and out.startswith("MD5=") else None


def source_content_fingerprint(stored: str) -> dict:
    """Content fingerprint of a generated test source: decoded-video md5 + speech spans of its audio."""
    from .audio_checks import speech_spans

    sp = speech_spans(stored)
    return {"video_md5": video_content_md5(stored),
            "speech": [[round(a, 3), round(b, 3)] for a, b in sp["spans"]] if sp["status"] == "measured" else None}


def fingerprint_matches(want: dict, got: dict) -> list[str]:
    bad = []
    if not want.get("video_md5") or got.get("video_md5") != want["video_md5"]:
        bad.append(f"영상 프레임 md5 {str(got.get('video_md5'))[:12]}… ≠ 기록 {str(want.get('video_md5'))[:12]}…")
    ws, gs = want.get("speech") or [], got.get("speech")
    if gs is None:
        bad.append("말소리 구간을 못 잼")
    elif len(ws) != len(gs) or any(abs(a - c) > FINGERPRINT_SPEECH_TOL_S or abs(b - d) > FINGERPRINT_SPEECH_TOL_S
                                   for (a, b), (c, d) in zip(ws, gs)):
        bad.append(f"말소리 구간 {gs} ≠ 기록 {ws} (±{FINGERPRINT_SPEECH_TOL_S}s)")
    return bad


def check_sources(plan: dict, ctx: ResolveContext, out: list[dict]) -> None:
    prod = plan["mode"] == "production"
    recs = warehouse_records()
    entries = exclusion_entries()
    newest_excl = max((str(e.get("added_at")) for e in entries if e.get("added_at")), default=None)
    for s in plan["sources"]:
        where = f"sources[{s['id']}]"
        si = ctx.sources.get(s["id"])
        if si and si.exists:
            if not s.get("sha256"):
                out.append(issue("error" if prod else "warn", "source_sha_missing", "sources[].sha256 이 비어 있습니다", where))
            elif sha256_file(si.abs) != s["sha256"]:
                fp = s.get("test_fingerprint")
                if not prod and fp:
                    bad = fingerprint_matches(fp, source_content_fingerprint(s["path"]))
                    if not bad:
                        out.append(issue("warn", "source_sha_regenerated",
                                         f"{s['path']} 의 바이트(sha256)는 기록과 다르지만 내용 지문(영상 프레임 md5·말소리 구간)이 같습니다: "
                                         "다른 ffmpeg/TTS 빌드로 다시 만든 생성 테스트 소스(테스트 모드에서만 허용)", where))
                    else:
                        out.append(issue("error", "source_sha_mismatch",
                                         f"sha256 불일치이고 내용 지문도 다릅니다: {'; '.join(bad)}", where))
                else:
                    out.append(issue("error", "source_sha_mismatch", f"sha256 불일치: {s['path']} 파일이 기록과 다릅니다", where))
        if prod and s.get("test_fingerprint"):
            out.append(issue("warn", "test_fingerprint_ignored",
                             "test_fingerprint 는 테스트 모드용: production 은 sha256 만 인정", f"{where}.test_fingerprint"))
        wid = s.get("warehouse_id")
        if not wid:
            out.append(issue("error" if prod else "warn", "provenance_missing",
                             "warehouse_id 없음: 출처 기록(창고 레코드)이 연결되지 않았습니다", where))
            continue
        rec = recs.get(wid)
        if rec is None:
            out.append(issue("error" if prod else "warn", "provenance_record_missing",
                             f"warehouse/candidates.jsonl 에 '{wid}' 레코드가 없습니다", where))
            continue
        ro = rec.get("reference_overlap") or {}
        if ro.get("excluded") is True:
            out.append(issue("error", "source_excluded_reference",
                             f"레퍼런스와 같은 원본으로 판정된 소재입니다(matched={ro.get('matched_video_id')}, "
                             f"method={ro.get('method')})", where))
        st = rec.get("status")
        if st in ("excluded", "rejected"):
            out.append(issue("error", "source_excluded_status", f"창고 레코드 상태가 {st} 입니다", where))
        elif st not in WAREHOUSE_USABLE:
            out.append(issue("error" if prod else "warn", "source_not_selected",
                             f"창고 레코드 상태가 {st!r} 입니다: 선택(selected) 또는 사용(used)된 소재만 쓸 수 있습니다 "
                             f"(`shortkit source select {wid}`)", where))
        # the exclusion rules are re-run on every validate: rows added after intake count (S5-03)
        acc = reference_account_hit(rec, entries)
        if acc:
            out.append(issue("error", "source_reference_account", f"레퍼런스 채널 자체의 업로드입니다: {acc['note']}", where))
        hit = excluded_url_hit([rec.get("url"), rec.get("original_url")], entries)
        if hit:
            out.append(issue("error", "source_excluded_url",
                             f"제외 목록 URL 과 같은 영상입니다(정규화 url_key): {hit.get('matched_url')} ({hit.get('note')})", where))
        if ro.get("excluded") is not True and newest_excl and \
                any(e.get("kind") == "reference_footage" and str(e.get("added_at") or "") > str(ro.get("checked_at") or "")
                    for e in entries):
            # fingerprints registered after the stored check: check the plan's file against them now
            try:
                from ..sourcing import exclusions as X

                res = X.check(rec, video_path=s["path"], entries=entries) if si and si.exists else {"excluded": None}
            except Exception as e:           # never a silent pass
                res = {"excluded": None, "note": f"{type(e).__name__}: {e}"}
            if res.get("excluded") is True:
                out.append(issue("error", "source_excluded_reference",
                                 f"레퍼런스와 같은 녹화입니다(나중에 등록된 레퍼런스 지문과 다시 비교: {res.get('note')})", where))
            elif res.get("excluded") is None:
                out.append(issue("error" if prod else "warn", "reference_overlap_stale",
                                 f"창고의 레퍼런스 중복 검사({ro.get('checked_at')})가 그 뒤 추가된 레퍼런스 지문보다 오래됐고 다시 "
                                 f"검사하지 못함(못 잼): {res.get('note')} → `shortkit source exclude-check {wid}`", where))
        if not rec.get("sha256"):
            out.append(issue("error" if prod else "warn", "provenance_sha_missing",
                             f"창고 레코드 '{wid}' 에 sha256 이 없어 같은 파일인지 확인할 수 없습니다(못 잼)", where))
        elif not s.get("sha256") or rec["sha256"] != s["sha256"]:
            out.append(issue("error", "provenance_sha_mismatch",
                             f"창고 레코드 sha256({str(rec['sha256'])[:12]}…) 과 plan sha256"
                             f"({str(s.get('sha256'))[:12]}…) 이 다릅니다", where))


def visible_source_rect(ctx: ResolveContext, source_id: str) -> dict | None:
    """SOURCE rect the renderer shows of this source (base fit of the video region, clean crop applied), or None
    when the whole frame can be visible (background = blurred source, or a zoom that shrinks the picture)."""
    from .resolve import base_fit, effective_src_rect

    if ctx.resolved is None or ctx.resolved.canvas["background"]["type"] == "blur_source":
        return None
    clips = [c for c in ctx.resolved.clips if c.source_id == source_id and all(c.src_size)]
    if not clips:
        return None
    if any(c.zoom and min(c.zoom.scale_from, c.zoom.scale_to) < 1.0 for c in clips):
        return None
    c = clips[0]
    ex, ey, ew, eh = effective_src_rect(c)
    sc, ox, oy = base_fit(c)
    R = c.region
    x0, x1 = max(ex, ex + (0.0 - ox) / sc), min(ex + ew, ex + (R.w - ox) / sc)
    y0, y1 = max(ey, ey + (0.0 - oy) / sc), min(ey + eh, ey + (R.h - oy) / sc)
    return {"x": x0, "y": y0, "w": max(0.0, x1 - x0), "h": max(0.0, y1 - y0)}


def check_clean_coverage(plan: dict, ctx: ResolveContext, out: list[dict]) -> None:
    """Every recorded original logo / source overlay / burned-in subtitle of every source is removed by its
    ``clean`` block over the source times the edit shows and the area the renderer shows
    (``shortkit.clean.coverage``).  Blocking entries (uncovered / no_record / source_missing / record_stale):
    error in production, warning in test; non-blocking entries (text_unmeasured / review_uncovered): warning."""
    prod = plan["mode"] == "production"
    try:
        from ..clean import coverage
    except ImportError as e:
        out.append(issue("error" if prod else "warn", "clean_unavailable",
                         f"shortkit.clean 을 불러오지 못해 원본 로고·자막 제거 여부를 검사하지 못함(못 잼): {e}", "sources"))
        return
    for s in plan["sources"]:
        segs = [seg for seg in plan["timeline"] if seg["source"] == s["id"]]
        if not segs:
            continue
        where = f"sources[{s['id']}].clean"
        try:
            ents = coverage(s["path"], s.get("clean"), sha256=s.get("sha256"),
                            used_ranges=[[float(seg["src_in"]), float(seg["src_out"])] for seg in segs],
                            visible=visible_source_rect(ctx, s["id"]))
        except Exception as e:              # never a silent pass
            out.append(issue("error" if prod else "warn", "clean_check_failed",
                             f"오버레이 제거 검사 실패(못 잼): {type(e).__name__}: {e}", where))
            continue
        for e in ents:
            blocking = bool(e.get("blocking"))
            out.append(issue(("error" if prod else "warn") if blocking else "warn", f"clean_{e.get('code')}",
                             str(e.get("reason") or e.get("code")), where))


def check_crop_faces(plan: dict, ctx: ResolveContext, out: list[dict]) -> None:
    """A ``clean.crop`` must not cut away a person or the action (S5-09): checked against the face track of the
    source (warehouse/overlays/<sha>.faces.json, ``shortkit clean faces``), the plan's protected rects and the
    motion activity of the overlay record, with the cleaner's own rule (``clean.strategy.validate_crop``).
    No measured face track = crop not verifiable (못 잼).  Production = error, test = warning."""
    prod = plan["mode"] == "production"
    sev = "error" if prod else "warn"
    for s in plan["sources"]:
        crop = (s.get("clean") or {}).get("crop")
        segs = [seg for seg in plan["timeline"] if seg["source"] == s["id"]]
        si = ctx.sources.get(s["id"])
        if not crop or not segs or si is None or not si.width:
            continue
        where = f"sources[{s['id']}].clean.crop"
        sha = s.get("sha256") or (sha256_file(si.abs) if si.exists else None)
        try:
            from ..clean.detect import load_overlays
            from ..clean.strategy import validate_crop

            faces = read_json(paths.absp(f"warehouse/overlays/{sha}.faces.json")) if sha else None
            doc = load_overlays(sha) if sha else None
        except ImportError as e:
            out.append(issue(sev, "crop_faces_unmeasured", f"shortkit.clean 없음 → 잘라내기 검사 못 함: {e}", where))
            continue
        if not faces or faces.get("status") != "measured":
            out.append(issue(sev, "crop_faces_unmeasured",
                             f"clean.crop 이 있는데 이 소스의 얼굴 검출 기록이 없거나 못 잼(warehouse/overlays/{str(sha)[:12]}….faces.json)"
                             " → 사람이 잘리는지 확인할 수 없음: `shortkit clean faces` / `clean plan` 결과의 crop 을 쓰기", where))
            continue
        W, H = int(si.width), int(si.height)
        fr = faces.get("resolution") or [W, H]
        kx, ky = W / float(fr[0]), H / float(fr[1])
        used = [(float(seg["src_in"]), float(seg["src_out"])) for seg in segs]

        def active(p):
            a = p.get("start")
            b = p.get("end")
            return any((a is None or float(a) < y) and (b is None or float(b) > x) for x, y in used)

        prot = [{"label": p.get("label", "face"), "x": p["x"] * kx, "y": p["y"] * ky, "w": p["w"] * kx, "h": p["h"] * ky}
                for p in faces.get("protected") or [] if active(p)]
        prot += [dict(p) for p in s.get("protected") or [] if active(p)]
        vr = ctx.resolved.canvas["video_region"]
        res = validate_crop({k: float(crop[k]) for k in ("x", "y", "w", "h")}, W, H, protected=prot,
                            region_aspect=float(vr["w"]) / float(vr["h"]), fit=vr["fit"],
                            activity=(doc or {}).get("activity"), region_size=[float(vr["w"]), float(vr["h"])])
        if not res["ok"]:
            out.append(issue(sev, "crop_invalid", "clean.crop 이 잘라내기 규칙을 어깁니다: " + "; ".join(res["reasons"]), where))


# ----------------------------------------------------------------------------- timeline / motion
def check_motion(plan: dict, preset: config.Preset, out: list[dict]) -> None:
    max_consec = int(preset.get("motion.zoom.max_consecutive"))
    run, worst, where = 0, 0, ""
    for seg in plan["timeline"]:
        run = run + 1 if seg.get("zoom") else 0
        if run > worst:
            worst, where = run, f"timeline[{seg['id']}]"
    if worst > max_consec:
        out.append(issue("error", "zoom_stacked", f"연속 세그먼트 줌 {worst}회 > 허용 {max_consec}회(같은 효과 연속 쌓기 금지)",
                         where))
    max_fr = int(preset.get("motion.freeze.max_per_video"))
    n_fr = sum(1 for s in plan["timeline"] if s.get("freeze"))
    if n_fr > max_fr:
        out.append(issue("error", "freeze_count", f"정지 화면 {n_fr}회 > 영상당 최대 {max_fr}회", "timeline"))
    prod = plan["mode"] == "production"
    sev = "error" if prod else "warn"
    prev = None
    for seg in plan["timeline"]:
        tt = (seg.get("transition_in") or {}).get("type") or "cut"
        if tt in ("flash", "crossfade") and prev == tt:
            out.append(issue(sev, "transition_stacked", f"{tt} 전환이 연속 세그먼트에 반복됩니다(같은 효과 연속 쌓기 금지)",
                             f"timeline[{seg['id']}]"))
        prev = tt
    segs = plan["timeline"]
    for i, a in enumerate(segs):
        for b in segs[i + 1:]:
            if a["source"] == b["source"]:
                ov = min(a["src_out"], b["src_out"]) - max(a["src_in"], b["src_in"])
                if ov > 0.05:
                    replay = b.get("replay_of") == a["id"] and str(b.get("replay_reason") or "").strip()
                    if replay:
                        out.append(issue("warn", "segment_replay",
                                         f"{b['id']} 는 {a['id']} 의 의도한 다시보기({b['replay_reason']}, {ov:.2f}s): 레퍼런스의 다시보기 "
                                         "빈도는 못 잼 — 분량 채우기가 아닌지 검수에서 확인", f"timeline[{b['id']}]"))
                    else:
                        out.append(issue(sev, "segment_repeat",
                                         f"같은 원본 구간이 두 번 쓰입니다({a['id']}·{b['id']}, {ov:.2f}s): 길이를 채우려는 반복은 금지 "
                                         "(의도한 다시보기면 뒤 구간에 replay_of: <앞 구간 id> + replay_reason)", f"timeline[{b['id']}]"))


# fixed style values a plan field can set: (plan location, preset key, label)
def _num_differs(a, b, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) > tol
    except (TypeError, ValueError):
        return a != b


def check_style_overrides(plan: dict, preset: config.Preset, out: list[dict]) -> None:
    """Fixed style lives in the preset (measured from the reference, or a requested change in
    requested_changes.yaml, which changes the PRESET value); a plan may only choose per-episode things
    (times, coordinates, which transition, zoom centre ...).  A plan value that differs from the preset's
    fixed-style value -- zoom scale/dur/ease, freeze hold, flash/crossfade duration, slow-motion factor,
    decoration blink rate, caption position of a non-speaker role, kept-original / SFX level -- is a
    deviation from the reference that nothing else would report: error in production, warning in test
    (S1-08 / S2QA-09).  Equal values are not overrides."""
    prod = plan["mode"] == "production"
    sev = "error" if prod else "warn"

    def flag(where: str, got, key: str, want, unit: str = "") -> None:
        org = preset.origin(key)
        out.append(issue(sev, "style_override",
                         f"plan 이 고정 스타일 {key}={want}{unit}({'임시값·못 잼' if org == 'provisional' else org}) 을 "
                         f"{got}{unit} 로 덮어씁니다: 레퍼런스와 다른 스타일 — 의도한 변경이면 requested_changes.yaml 에 "
                         "적어 프리셋 값을 바꾸고 plan 에서는 지우기", where))

    z = {k: preset.get(f"motion.zoom.{k}") for k in ("scale_to", "dur_s", "ease")}
    hold = preset.get("motion.freeze.hold_s")
    tdur = {"flash": preset.get("motion.transitions.flash.dur_s"),
            "crossfade": preset.get("motion.transitions.crossfade.dur_s")}
    slow = preset.get("motion.speed.slowmo_factor")
    for seg in plan["timeline"]:
        w = f"timeline[{seg['id']}]"
        zm = seg.get("zoom") or {}
        if zm:
            if zm.get("scale_to") is not None and _num_differs(zm["scale_to"], z["scale_to"]):
                flag(f"{w}.zoom.scale_to", zm["scale_to"], "motion.zoom.scale_to", z["scale_to"])
            if zm.get("dur") is not None and _num_differs(zm["dur"], z["dur_s"]):
                flag(f"{w}.zoom.dur", zm["dur"], "motion.zoom.dur_s", z["dur_s"], "s")
            if zm.get("ease") is not None and zm["ease"] != z["ease"]:
                flag(f"{w}.zoom.ease", zm["ease"], "motion.zoom.ease", z["ease"])
            if zm.get("scale_from") is not None and _num_differs(zm["scale_from"], 1.0):
                out.append(issue(sev, "style_override",
                                 f"zoom.scale_from={zm['scale_from']}: 레퍼런스 확대는 원래 크기(1.0)에서 시작하는 것으로 잰다 "
                                 "(motion.zoom.scale_to = 시작 대비 최종 배율) — 다른 시작 배율은 레퍼런스와 다른 스타일",
                                 f"{w}.zoom.scale_from"))
        fr = seg.get("freeze") or {}
        if fr and fr.get("hold") is not None and _num_differs(fr["hold"], hold):
            flag(f"{w}.freeze.hold", fr["hold"], "motion.freeze.hold_s", hold, "s")
        tr = seg.get("transition_in") or {}
        if tr.get("dur") is not None and tr.get("type") in tdur and _num_differs(tr["dur"], tdur[tr["type"]]):
            flag(f"{w}.transition_in.dur", tr["dur"], f"motion.transitions.{tr['type']}.dur_s", tdur[tr["type"]], "s")
        sp = float(seg.get("speed") or 1.0)
        if sp < 1.0 and _num_differs(sp, slow):
            out.append(issue(sev, "speed_not_preset", f"느린 재생 {sp} 가 프리셋 slowmo_factor {slow} 와 다릅니다", w))
        elif sp > 1.0 + 1e-9:
            out.append(issue(sev, "style_override", f"빨리 재생 ×{sp}: 프리셋에 빨리 재생 배율이 없습니다(레퍼런스 스타일 아님)",
                             f"{w}.speed"))
        oa = seg.get("original_audio") or {}
        if oa.get("keep") and oa.get("gain_db") is not None:
            kg = preset.get("audio.original.keep_gain_db")
            if _num_differs(oa["gain_db"], kg):
                flag(f"{w}.original_audio.gain_db", oa["gain_db"], "audio.original.keep_gain_db", kg, " LU")
    for d in plan.get("decorations") or []:
        if d.get("blink_hz") is not None:
            want = preset.get(f"decorations.{d['kind']}.blink_hz")
            if _num_differs(d["blink_hz"], want):
                flag(f"decorations[{d['id']}].blink_hz", d["blink_hz"], f"decorations.{d['kind']}.blink_hz", want, " Hz")
    for c in plan.get("captions") or []:
        if c.get("pos") and c["role"] != "speaker":
            out.append(issue(sev, "style_override",
                             f"{c['role']} 자막 위치를 plan 에서 정합니다(pos={c['pos']}): 제목·설명·본문 위치는 고정 스타일"
                             f"(text.roles.{c['role']}.anchor) — plan 의 위치 지정은 인물 표시(speaker)만", f"captions[{c['id']}].pos"))
    gd = preset.get("audio.sfx.gain_db_default")
    for x in plan.get("sfx") or []:
        if x.get("gain_db") is not None and _num_differs(x["gain_db"], gd):
            flag(f"sfx[{x['id']}].gain_db", x["gain_db"], "audio.sfx.gain_db_default", gd, " dB")


def check_protected_framing(plan: dict, ctx: ResolveContext, out: list[dict]) -> None:
    """Never crop away the important person/action: protected rects (faces/hands/key objects)
    must survive the clean crop and the region fit; a zoom that cuts one is reported."""
    from .resolve import base_fit, effective_src_rect, src_to_region

    prot = {s["id"]: s.get("protected") or [] for s in plan["sources"]}
    for clip in ctx.resolved.clips:
        if not all(clip.src_size):
            continue
        for p in prot.get(clip.source_id, []):
            if (p.get("start") is not None and p["start"] > clip.src_out) or \
                    (p.get("end") is not None and p["end"] < clip.src_in):
                continue
            where = f"timeline[{clip.id}]"
            ex, ey, ew, eh = effective_src_rect(clip)
            if clip.crop and (p["x"] < ex - 0.5 or p["y"] < ey - 0.5 or p["x"] + p["w"] > ex + ew + 0.5
                              or p["y"] + p["h"] > ey + eh + 0.5):
                out.append(issue("error", "crop_cuts_protected", f"clean.crop 이 보호 영역 '{p['label']}' 을 잘라냅니다", where))
                continue
            R = clip.region
            for u, sev, code, why in ((None, "error", "protected_cropped", "영상 영역 맞춤(fit)"),
                                      ("zoom", "warn", "zoom_cuts_protected", "확대(zoom)")):
                if u is None:
                    s_, tx, ty = base_fit(clip)
                else:
                    if not clip.zoom:
                        continue
                    s_, tx, ty = src_to_region(clip, clip.zoom.start + clip.zoom.dur)
                x0 = tx + s_ * (p["x"] - ex)
                y0 = ty + s_ * (p["y"] - ey)
                x1, y1 = x0 + s_ * p["w"], y0 + s_ * p["h"]
                if x0 < -0.5 or y0 < -0.5 or x1 > R.w + 0.5 or y1 > R.h + 0.5:
                    out.append(issue(sev, code, f"{why} 때문에 보호 영역 '{p['label']}' 이 화면 밖으로 잘립니다", where))


FIRST_CAPTION_TOL_S = 0.25


def first_caption_excluded_roles() -> tuple[str, ...]:
    """Caption roles the reference analyzer leaves out of structure.first_caption_at_s (title, description,
    identity marks, unknown): ``reference.aggregate.FIRST_CAPTION_EXCLUDED_ROLES`` itself (never a copy)."""
    from ..reference.aggregate import FIRST_CAPTION_EXCLUDED_ROLES

    return tuple(FIRST_CAPTION_EXCLUDED_ROLES)


def check_structure(plan: dict, ctx: ResolveContext, out: list[dict]) -> None:
    """Planned duration vs the measured range structure.duration_s p10..p90 (of this plan's format when
    the preset was loaded for a format): outside -> error in production / warning in test.  All four
    keys are read through the preset every time (unmeasured -> the unmeasured warning).  Cut density and median
    shot length: ``check_cut_structure``.  First caption: the reference analyzer's definition (first TIMED caption,
    roles in ``reference.aggregate.FIRST_CAPTION_EXCLUDED_ROLES`` left out)."""
    pr, r = ctx.preset, ctx.resolved
    prod = plan["mode"] == "production"
    ds = pr.section("structure.duration_s")
    n, p10, p50, p90 = ds.get("n"), ds.get("p10"), ds.get("p50"), ds.get("p90")
    n = int(n or 0)
    if r.duration <= 0:
        out.append(issue("error", "duration_zero", "타임라인 길이가 0 입니다", "timeline"))
    elif n == 0 or p10 is None or p90 is None:
        out.append(issue("warn", "duration_unmeasured", f"영상 길이 분포 미측정(못 잼, n={n}, p10={p10}, p50={p50}, "
                         f"p90={p90}): {r.duration:.2f}s 의 적합성 판정 불가", "structure.duration_s"))
    elif not (float(p10) - 1e-6 <= r.duration <= float(p90) + 1e-6):
        out.append(issue("error" if prod else "warn", "duration_range",
                         f"길이 {r.duration:.2f}s 가 관측 범위 p10..p90 ({p10}..{p90}, 중앙값 {p50}, n={n}"
                         f"{', 포맷 ' + str(pr.format_id) if pr.format_id else ''}) 밖", "timeline"))
    check_cut_structure(plan, ctx, out)
    # first caption: the reference analyzer's definition (structure.first_caption_at_s = start of each video's first
    # TIMED caption; title / description / identity marks frame the whole video and are left out)
    excluded = first_caption_excluded_roles()
    fc = pr.get("structure.first_caption_at_s")
    timed = [c for c in r.captions if c.role not in excluded]
    if pr.origin("structure.first_caption_at_s") not in ("measured", "requested_change") or fc is None:
        out.append(issue("warn", "first_caption_unmeasured",
                         f"첫 시간제 자막 시각(structure.first_caption_at_s = {fc!r}) 미측정(못 잼, 임시값): 이 plan 의 "
                         + (f"첫 시간제 자막 {min(c.start for c in timed):.2f}s" if timed else "시간제 자막 없음")
                         + " 을 레퍼런스와 비교 못 함", "captions"))
    elif timed:
        first = min(timed, key=lambda c: c.start)
        if abs(first.start - float(fc)) > FIRST_CAPTION_TOL_S:
            out.append(issue("warn", "first_caption_timing",
                             f"첫 시간제 자막({first.id}, {first.role}) {first.start:.2f}s ≠ 프리셋 {float(fc):.2f}s "
                             f"(±{FIRST_CAPTION_TOL_S}s; 제목·설명 제외 — 레퍼런스 분석기와 같은 정의)", "captions"))
    else:
        out.append(issue("warn", "first_caption_timing",
                         f"시간제 자막(제목·설명 외)이 없음: 레퍼런스 첫 자막 {float(fc):.2f}s 와 비교할 자막 없음", "captions"))


def planned_transitions(r) -> list[dict]:
    """Shot boundaries of the planned edit in the reference analyzer's vocabulary (``reference.aggregate``
    TRANSITION_TYPES cut / flash / crossfade at each clip start).  A hard cut that continues the same shot (same
    source, next source frame, same speed and geometry: ``qa.probes_video.continuous_edit``, the rule QA uses on the
    output) shows no picture change and is not a boundary.  -> [{t, type, clip_id}]."""
    from ..qa.probes_video import continuous_edit

    out = []
    for prev, c in zip(r.clips, r.clips[1:]):
        typ = c.transition_in.type
        if typ == "cut" and continuous_edit(prev, c):
            continue
        out.append({"t": float(c.out_start), "type": typ, "clip_id": c.id})
    return out


def cut_structure(times: list[float], duration: float) -> dict:
    """Cut density and median shot length of ONE video from its transition times -- the definition of
    ``reference.aggregate.cut_structure_rows`` (transitions with 0 < t < duration; shots = gaps between 0, the
    transitions and the end; median over the video's shots).  Used for the plan (validate) and the output (QA)."""
    ts = sorted(float(t) for t in times if 0.0 < float(t) < duration)
    edges = [0.0] + ts + [float(duration)]
    shots = [round(b - a, 3) for a, b in zip(edges, edges[1:]) if b - a > 1e-3]
    shots_sorted = sorted(shots)
    k = len(shots_sorted)
    med = (shots_sorted[k // 2] if k % 2 else 0.5 * (shots_sorted[k // 2 - 1] + shots_sorted[k // 2])) if k else None
    return {"cuts_per_10s": round(len(ts) / duration * 10.0, 3) if duration > 0 else None, "n_cuts": len(ts),
            "shot_len_median_s": None if med is None else round(med, 3), "shots_s": shots, "duration": round(duration, 3)}


def check_cut_structure(plan: dict, ctx: ResolveContext, out: list[dict]) -> None:
    """The plan's cut density (transitions per 10 s) and median shot length vs the reference distributions
    ``structure.cuts_per_10s`` / ``structure.shot_len_s`` p10..p90 (per-video values of the format's snapshot videos
    when the preset was loaded for a format): outside -> error in production / warning in test; unmeasured ->
    warning (못 잼).  Keys read through the preset every time."""
    pr, r = ctx.preset, ctx.resolved
    prod = plan["mode"] == "production"
    if r.duration <= 0:
        return
    tr = planned_transitions(r)
    cs = cut_structure([x["t"] for x in tr], r.duration)
    fmt = f", 포맷 {pr.format_id}" if pr.format_id else ""
    for key, val, what, unit in (("structure.cuts_per_10s", cs["cuts_per_10s"], "컷 밀도(10초당 전환 수)", "개"),
                                 ("structure.shot_len_s", cs["shot_len_median_s"], "샷 길이 중앙값", "s")):
        try:
            st = pr.section(key)
            n, p10, p50, p90 = st.get("n"), st.get("p10"), st.get("p50"), st.get("p90")
        except (KeyError, TypeError):     # a preset from before the key existed: 못 잼, never a pass
            n = p10 = p50 = p90 = None
        n = int(n or 0)
        code = key.split(".")[1]
        desc = (f"{what} {val}{unit} (전환 {cs['n_cuts']}개: " + ", ".join(f"{x['type']}@{x['t']:.2f}s" for x in tr[:8])
                + ("…" if len(tr) > 8 else "") + f" / {r.duration:.2f}s)")
        if n == 0 or p10 is None or p90 is None:
            out.append(issue("warn", f"{code}_unmeasured", f"{key} 분포 미측정(못 잼, n={n}, p10={p10}, p50={p50}, "
                             f"p90={p90}): 계획의 {desc} 적합성 판정 불가", key))
        elif val is None or not (float(p10) - 1e-6 <= float(val) <= float(p90) + 1e-6):
            out.append(issue("error" if prod else "warn", f"{code}_range",
                             f"계획의 {desc} 가 레퍼런스 관측 범위 p10..p90 ({p10}..{p90}, 중앙값 {p50}, n={n}{fmt}) 밖",
                             "timeline"))


# ----------------------------------------------------------------------------- captions
def _cap_rects(c) -> list[tuple[float, float, float, float]]:
    rs = [(c.bbox.x, c.bbox.y, c.bbox.w, c.bbox.h)]
    if (c.box or {}).get("enabled") and c.box.get("rect"):
        rs.append(tuple(c.box["rect"]))
    return rs


def _union(rs):
    x0 = min(r[0] for r in rs)
    y0 = min(r[1] for r in rs)
    x1 = max(r[0] + r[2] for r in rs)
    y1 = max(r[1] + r[3] for r in rs)
    return x0, y0, x1 - x0, y1 - y0


def _frame_times(a: float, b: float, fps: float) -> list[float]:
    import math

    n0, n1 = int(math.ceil(a * fps - 1e-6)), int(math.ceil(b * fps - 1e-6))
    return [n / fps for n in range(n0, n1)]


def check_captions(plan: dict, ctx: ResolveContext, out: list[dict]) -> None:
    prod = plan["mode"] == "production"
    r = ctx.resolved
    plan_caps = {c["id"]: c for c in plan.get("captions", [])}
    src_ids = {s["id"] for s in plan["sources"]}
    # layout fit + safe area
    W, H = r.canvas["width"], r.canvas["height"]
    sm = r.canvas["safe_margin"]
    for c in r.captions:
        where = f"captions[{c.id}]"
        lay = ctx.layouts.get(c.id)
        st = ctx.role_styles.get(c.role, {})
        if lay is None:
            continue
        if lay.overflow_lines:
            out.append(issue("error", "caption_overflow_lines",
                             f"{len(lay.lines)}줄 > 최대 {st.get('max_lines')}줄 (글꼴 실측 줄바꿈: {' / '.join(l.text for l in lay.lines)})",
                             where))
        if lay.overflow_width:
            out.append(issue("error", "caption_overflow_width",
                             f"줄 폭 {lay.max_line_width:.0f}px > 최대 {st.get('max_width_px')}px", where))
        x, y, w, h = _union(_cap_rects(c))
        if x < sm["left"] - 0.5 or y < sm["top"] - 0.5 or x + w > W - sm["right"] + 0.5 or y + h > H - sm["bottom"] + 0.5:
            out.append(issue("error", "caption_outside_safe",
                             f"자막 영역 ({x:.0f},{y:.0f},{w:.0f}x{h:.0f}) 이 안전 여백 밖으로 나갑니다", where))
        if c.end > r.duration + 1e-3:
            out.append(issue("warn", "caption_past_end", f"자막 끝 {c.end:.2f}s > 영상 길이 {r.duration:.2f}s", where))
    # same-role overlap and cross-role collisions
    caps = sorted(r.captions, key=lambda c: c.start)
    for i, a in enumerate(caps):
        for b in caps[i + 1:]:
            if b.start >= a.end - EPS:
                break
            ra, rb = _union(_cap_rects(a)), _union(_cap_rects(b))
            hit = rects_intersect(ra, rb)
            if a.role == b.role and (a.role != "speaker" or hit):
                out.append(issue("error", "caption_same_role_overlap",
                                 f"같은 역할({a.role}) 자막 {a.id} 와 {b.id} 가 시간상 겹칩니다", f"captions[{b.id}]"))
            elif hit:
                out.append(issue("error", "caption_collision", f"자막 {a.id}({a.role}) 와 {b.id}({b.role}) 가 같은 시간에 "
                                 "화면에서 겹칩니다", f"captions[{b.id}]"))
    # protected rects (faces/hands/key objects) -- caption rest bbox must not cover them
    fps = float(r.canvas["fps"])
    prot = {s["id"]: s.get("protected") or [] for s in plan["sources"]}
    for c in r.captions:
        crect = _union(_cap_rects(c))
        reported = set()
        for t in _frame_times(c.start, c.end, fps):
            for clip in clips_at(r, t):
                if not all(clip.src_size):
                    continue        # source unreadable: already an error, geometry unknown
                u = t - clip.out_start
                st = src_time_at(clip, u)
                for k, p in enumerate(prot.get(clip.source_id, [])):
                    if (p.get("start") is not None and st < p["start"] - EPS) or \
                            (p.get("end") is not None and st > p["end"] + EPS):
                        continue
                    m = map_src_rect(clip, u, p)
                    key = (clip.source_id, k)
                    if m and rects_intersect(crect, m) and key not in reported:
                        reported.add(key)
                        out.append(issue("error", "caption_covers_protected",
                                         f"자막이 보호 영역 '{p['label']}'(소스 {clip.source_id})을 가립니다: 출력 {t:.2f}s, "
                                         f"자막 ({crect[0]:.0f},{crect[1]:.0f},{crect[2]:.0f}x{crect[3]:.0f}) vs "
                                         f"보호 ({m[0]:.0f},{m[1]:.0f},{m[2]:.0f}x{m[3]:.0f})", f"captions[{c.id}]"))
    # decorations vs protected (warn: pointing AT / encircling something is allowed, covering it is not)
    for d in r.decorations:
        from .captions import deco_shape

        reported = set()
        for t in _frame_times(d.start, d.end, fps):
            kf = _kf_at(d, t)
            polys, _ = deco_shape(d.kind, kf, d.style)
            xs = [x for p in polys for x, _ in p]
            ys = [y for p in polys for _, y in p]
            drect = (min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))
            for clip in clips_at(r, t):
                if not all(clip.src_size):
                    continue
                u = t - clip.out_start
                st = src_time_at(clip, u)
                for k, p in enumerate(prot.get(clip.source_id, [])):
                    if (p.get("start") is not None and st < p["start"] - EPS) or \
                            (p.get("end") is not None and st > p["end"] + EPS):
                        continue
                    m = map_src_rect(clip, u, p)
                    if m and deco_covers(d.kind, kf, d.style, drect, m) and (clip.source_id, k) not in reported:
                        reported.add((clip.source_id, k))
                        out.append(issue("warn", "decoration_covers_protected",
                                         f"장식 {d.id} 이 보호 영역 '{p['label']}' 과 겹칩니다(출력 {t:.2f}s)",
                                         f"decorations[{d.id}]"))
    # identity exclusions
    forb = [f for f in (ctx.preset.get("identity_exclusions.forbidden_text") or []) if f]
    texts = [(f"captions[{c['id']}]", c["text"]) for c in plan.get("captions", [])]
    texts += [("cover.text", (plan.get("cover") or {}).get("text") or "")]
    texts += [(f"title_candidates[{i}]", t) for i, t in enumerate(plan.get("title_candidates") or [])]
    for where, t in texts:
        low = "".join(t.split()).casefold()
        for f in forb:
            if "".join(f.split()).casefold() in low:
                out.append(issue("error", "identity_text", f"레퍼런스 채널 식별 문구 '{f}' 는 쓸 수 없습니다", where))
    _ = plan_caps


# ----------------------------------------------------------------------------- grounding (S3-04)
GROUNDING_WINDOW_S = 1.0         # rule: the grounded moment is on screen within this distance of the caption interval
GROUNDING_ON_SCREEN_ROLES = ("situation", "reaction", "dialogue", "speaker")
HEARD_TOL_S = 0.3                # heard src_t must lie in (or this close to) a detected speech span
# relation / kinship / social-role words: a caption that states one needs a note saying where the footage shows it
RELATION_WORDS = ("엄마", "아빠", "어머니", "아버지", "부모", "남편", "아내", "부인", "와이프", "남친", "여친", "남자친구",
                  "여자친구", "애인", "연인", "전남친", "전여친", "친구", "오빠", "누나", "언니", "동생", "남매", "자매", "형제",
                  "아들", "딸", "할머니", "할아버지", "손자", "손녀", "삼촌", "이모", "고모", "사촌", "조카", "선생님", "제자",
                  "사장", "직원", "동료", "상사", "부하", "주인", "이웃", "가족", "부부", "커플", "신랑", "신부", "시어머니",
                  "장모", "며느리", "사위", "룸메이트", "짝꿍")


def speech_source(s: dict) -> tuple[str | None, str]:
    """The audio of a plan source where speech can be measured: its vocals stem if given, else the raw audio when
    the source has no embedded music.  (None, why) when music is mixed in and there is no vocals stem."""
    vp = s.get("vocals_path")
    if vp and paths.absp(vp).is_file():
        return vp, "vocals"
    if s.get("has_embedded_music") is True:
        return None, "원본에 음악이 섞였는데 분리한 목소리(vocals_path)가 없어 말소리를 잴 수 없음"
    return s["path"], "raw"


def _source_speech(s: dict) -> dict:
    from .audio_checks import speech_spans

    path, how = speech_source(s)
    if path is None:
        return {"status": "unmeasured", "spans": [], "reason": how, "stem": None}
    return {**speech_spans(path), "stem": how, "path": path}


def check_grounding(plan: dict, ctx: ResolveContext, out: list[dict]) -> None:
    """Captions say only what the footage shows (S3-04).  Production = error, test = warning:
    every caption has a grounding (title/description may use kind=framing, nothing else may); seen/heard name
    the source and source time; that moment is in the edit, and for situation/reaction/dialogue/speaker it is on
    screen within GROUNDING_WINDOW_S of the caption; a heard line is speech at src_t (automatic speech check of
    the source audio or its vocals stem); a caption stating a relation needs a note."""
    from .resolve import src_to_out_time

    prod = plan["mode"] == "production"
    sev = "error" if prod else "warn"
    r = ctx.resolved
    srcs = {s["id"]: s for s in plan["sources"]}
    speech_cache: dict[str, dict] = {}
    for c in plan.get("captions", []):
        where = f"captions[{c['id']}]"
        g = c.get("grounding")
        role = c["role"]
        if not g:
            if role not in GROUNDING_FREE_ROLES or prod:
                out.append(issue(sev, "caption_grounding",
                                 f"{role} 자막에 근거(grounding)가 없습니다: 본 것/들은 것만 쓴다"
                                 + (" (제목·설명은 kind=framing + note 로 편집 틀임을 적기)" if role in GROUNDING_FREE_ROLES else ""),
                                 where))
            if role == "dialogue":
                out.append(issue(sev, "dialogue_not_heard", "dialogue 는 실제로 들린 대사여야 합니다(grounding.kind=heard)", where))
            continue
        kind = g.get("kind")
        if role == "dialogue" and kind != "heard":
            out.append(issue(sev, "dialogue_not_heard", "dialogue 는 실제로 들린 대사여야 합니다(grounding.kind=heard)", where))
        if kind == "framing" and role not in GROUNDING_FREE_ROLES:
            out.append(issue(sev, "grounding_framing_role",
                             f"{role} 자막은 편집 틀(framing)을 근거로 쓸 수 없습니다: 화면에서 본 것(seen)·들린 것(heard)·화면 글자로 "
                             "근거를 적기(관계·동기·대사를 지어내지 않음)", where))
        src_id, st = g.get("source"), g.get("src_t")
        if src_id and src_id not in srcs:
            out.append(issue("error", "grounding_source", f"grounding.source '{src_id}' 가 sources 에 없습니다", where))
            continue
        if kind in ("seen", "heard") and (not src_id or st is None):
            out.append(issue(sev, "grounding_incomplete",
                             f"grounding.kind={kind} 에는 source 와 src_t(원본 시각)가 필요합니다: 어느 장면을 보고/듣고 쓴 것인지", where))
        text = c["text"].replace("\n", " ")
        rel = [w for w in RELATION_WORDS if w in text]
        if rel and role in ("speaker", "situation", "reaction", "title", "description") and \
                not str(g.get("note") or "").strip():
            out.append(issue(sev, "grounding_relation_note",
                             f"관계를 말하는 자막({', '.join(rel)})에는 영상 어디에서 그 관계가 확인되는지 grounding.note 가 필요합니다"
                             "(없는 관계를 지어내지 않음)", where))
        if not src_id or st is None:
            continue
        st = float(st)
        clips = [cl for cl in r.clips if cl.source_id == src_id and cl.src_in - EPS <= st <= cl.src_out + EPS]
        if not clips:
            out.append(issue(sev, "grounding_not_shown",
                             f"근거 장면 {src_id}@{st}s 가 편집본에 나오지 않습니다(타임라인 구간 밖)", where))
        elif role in GROUNDING_ON_SCREEN_ROLES:
            a, b = float(c["start"]), float(c["end"])
            ts = [src_to_out_time(cl, st) for cl in clips]
            dist = min(0.0 if a - EPS <= t <= b + EPS else min(abs(t - a), abs(t - b)) for t in ts)
            if dist > GROUNDING_WINDOW_S + 1e-9:
                tt = min(ts, key=lambda t: abs(t - a))
                out.append(issue(sev, "grounding_not_on_screen",
                                 f"근거 장면 {src_id}@{st}s 는 출력 {tt:.2f}s 에 보이는데 자막은 {a:.2f}~{b:.2f}s 입니다"
                                 f"(> {GROUNDING_WINDOW_S}s 떨어짐): 자막이 말하는 장면이 그때 화면에 없음", where))
        if kind == "heard":
            if src_id not in speech_cache:
                speech_cache[src_id] = _source_speech(srcs[src_id])
            sp = speech_cache[src_id]
            if sp["status"] != "measured":
                out.append(issue(sev, "grounding_speech_unmeasured",
                                 f"들린 대사 근거 {src_id}@{st}s 의 말소리를 자동 확인하지 못함(못 잼): {sp['reason']}", where))
            else:
                from .audio_checks import span_at

                if span_at(sp["spans"], st, HEARD_TOL_S) is None:
                    out.append(issue(sev, "grounding_no_speech",
                                     f"들린 대사 근거 {src_id}@{st}s 에 말소리가 없습니다(자동 음성 검사, {sp['stem']}; 검출된 말 구간 "
                                     f"{[(round(x, 2), round(y, 2)) for x, y in sp['spans']] or '없음'})", where))


def check_watch_records(plan: dict, out: list[dict]) -> None:
    """Who watched each source before writing captions (S3-04): ``sources[].watched {by, at, sha256}`` for the
    exact file (sha256 = the source's), consistent with the warehouse review's ``watched_file_sha256``.
    Production = error, test = warning."""
    prod = plan["mode"] == "production"
    sev = "error" if prod else "warn"
    used = {seg["source"] for seg in plan["timeline"]}
    recs = None
    for s in plan["sources"]:
        if s["id"] not in used:
            continue
        where = f"sources[{s['id']}].watched"
        w = s.get("watched") or {}
        if not str(w.get("by") or "").strip() or not w.get("at"):
            out.append(issue(sev, "watch_record_missing",
                             "이 소스를 처음부터 끝까지 보고 들은 기록(sources[].watched: by, at, sha256)이 없습니다: 자막은 본 뒤에만 쓴다",
                             where))
            continue
        if not w.get("sha256") or (s.get("sha256") and w["sha256"] != s["sha256"]):
            out.append(issue(sev, "watch_record_sha",
                             f"본 파일의 sha256({str(w.get('sha256'))[:12]}…) 이 소스 sha256({str(s.get('sha256'))[:12]}…) 과 다릅니다", where))
        if s.get("warehouse_id"):
            if recs is None:
                recs = warehouse_records()
            revs = [rv for rv in (recs.get(s["warehouse_id"]) or {}).get("reviews") or [] if rv.get("watched_file_sha256")]
            if revs and not any(rv["watched_file_sha256"] == s.get("sha256") for rv in revs):
                out.append(issue(sev, "watch_record_review_mismatch",
                                 "창고 검토 기록(reviews[].watched_file_sha256)이 이 파일이 아닌 다른 파일을 본 것입니다", where))


# ----------------------------------------------------------------------------- information order (S3-05)
def check_reveal(plan: dict, ctx: ResolveContext, out: list[dict], allow_unmeasured: bool) -> None:
    """Do not pre-announce the twist.  ``reveal: {t, keywords}`` protects it: captions starting before t, the cover
    and the title candidates must not contain the keywords.  Production: a reveal block is required (or
    ``reveal: {none: true, reason}`` when the story has no twist -- not allowed when a segment's purpose is
    reveal); reveal.t lies inside the first reveal-purpose segment; the disclosure order is compared with the
    format's measured order (formats.yaml ``beats`` / ``reveal_frac``) -- 못 잼 when not measured."""
    prod = plan["mode"] == "production"
    sev = "error" if prod else "warn"
    r = ctx.resolved
    rv = plan.get("reveal")
    rsegs = [seg for seg in plan["timeline"] if (seg.get("purpose") or "").strip().casefold().startswith(("reveal", "반전"))]
    if not rv:
        if prod or rsegs:
            out.append(issue(sev, "reveal_missing",
                             "반전 보호(reveal: t, keywords)가 없습니다" + (f" — 구간 {[x['id'] for x in rsegs]} 의 목적이 reveal"
                                                                          if rsegs else "")
                             + ": 반전이 없는 이야기면 reveal: {none: true, reason: ...}", "reveal"))
        rv = {}
    if rv.get("none"):
        if rsegs:
            out.append(issue(sev, "reveal_missing", f"reveal.none 인데 목적이 reveal 인 구간 {[x['id'] for x in rsegs]} 이 있습니다",
                             "reveal"))
        if not str(rv.get("reason") or "").strip():
            out.append(issue(sev, "reveal_missing", "reveal.none 에는 이유(reason)가 필요합니다", "reveal"))
    kws = [k for k in rv.get("keywords") or [] if k]
    if not rv.get("none") and rv and (not kws or rv.get("t") is None):
        out.append(issue(sev, "reveal_incomplete", "reveal 에는 t(반전 시각)와 keywords(미리 말하면 안 되는 말)가 필요합니다",
                         "reveal"))
    if kws:
        rt = float(rv.get("t") or 0.0)
        for c in r.captions:
            if c.start < rt - EPS:
                for kw in kws:
                    if kw in c.text.replace("\n", " "):
                        out.append(issue("error", "reveal_leak",
                                         f"반전({rt:.2f}s) 전에 시작하는 자막 {c.id} 에 '{kw}' 가 있습니다(반전 미리 설명 금지)",
                                         f"captions[{c.id}]"))
        for kw in kws:
            if kw in ((plan.get("cover") or {}).get("text") or ""):
                out.append(issue(sev, "reveal_in_cover", f"표지 문구에 반전 키워드 '{kw}' 가 있습니다(표지는 반전 전에 보임)",
                                 "cover.text"))
            for i, t in enumerate(plan.get("title_candidates") or []):
                if kw in str(t):
                    out.append(issue(sev, "reveal_in_title", f"제목 후보 '{t}' 에 반전 키워드 '{kw}' 가 있습니다(제목은 반전 전에 보임)",
                                     f"title_candidates[{i}]"))
        if rsegs and rv.get("t") is not None:
            first = next((cl for cl in r.clips if cl.id == rsegs[0]["id"]), None)
            if first is not None and not (first.out_start - 0.5 <= rt <= first.out_end + EPS):
                out.append(issue(sev, "reveal_time_segment",
                                 f"reveal.t {rt:.2f}s 가 반전 구간 {first.id}({first.out_start:.2f}~{first.out_end:.2f}s) 밖입니다",
                                 "reveal.t"))
    # disclosure order vs the reference format (measured per format)
    if plan["format_id"] == TEST_FORMAT_ID:
        out.append(issue("warn", "reveal_order_unmeasured", "테스트 모드(포맷 미분류): 정보 공개 순서를 레퍼런스 포맷과 비교 못 함",
                         "reveal"))
        return
    fm = read_yaml(paths.absp(ctx.preset.get("structure.formats_file")), None) or {}
    row = next((e for e in fm.get("table") or [] if isinstance(e, dict)
                and (e.get("format_id") or e.get("id")) == plan["format_id"]), None) or {}
    beats, frac = row.get("beats"), row.get("reveal_frac") or {}
    if not beats and not frac.get("n"):
        out.append(issue("error" if (prod and not allow_unmeasured) else "warn", "reveal_order_unmeasured",
                         f"포맷 {plan['format_id']} 의 정보 공개 순서(formats.yaml beats / reveal_frac)가 측정되지 않아 이 plan 의 "
                         "순서(구간 목적 순서·반전 시각)를 레퍼런스와 비교 못 함(못 잼)", "reveal"))
        return
    seq = []
    for seg in plan["timeline"]:
        pu = (seg.get("purpose") or "").strip().casefold().split(" ")[0]
        if pu and (not seq or seq[-1] != pu):
            seq.append(pu)
    if beats:
        order = [str(b).casefold() for b in beats]
        idx = [order.index(pu) if pu in order else None for pu in seq]
        bad = [pu for pu, i in zip(seq, idx) if i is None]
        known = [i for i in idx if i is not None]
        if bad or any(b < a for a, b in zip(known, known[1:])):
            out.append(issue(sev, "reveal_order",
                             f"구간 목적 순서 {seq} 가 포맷 {plan['format_id']} 의 전개 {beats} 와 다릅니다"
                             + (f"(포맷에 없는 목적 {bad})" if bad else ""), "timeline"))
    if frac.get("n") and rv.get("t") is not None and r.duration > 0:
        f = float(rv["t"]) / r.duration
        if not (float(frac["p10"]) - 1e-6 <= f <= float(frac["p90"]) + 1e-6):
            out.append(issue(sev, "reveal_time_range",
                             f"반전 시각 비율 {f:.2f} 가 포맷 관측 범위 p10..p90 ({frac['p10']}..{frac['p90']}, n={frac['n']}) 밖",
                             "reveal.t"))


def deco_covers(kind: str, kf: dict, style: dict, drect, m) -> bool:
    """Does a decoration's ink cover canvas rect ``m``?  A circle/box is a RING: a protected rect
    lying entirely inside the ring's inner edge is pointed at (enclosed), not covered.  Arrows and
    rotated rings use the bounding box (conservative)."""
    if not rects_intersect(drect, m):
        return False
    if kind not in ("circle", "box") or kf.get("rotation") or not kf.get("w") or not kf.get("h"):
        return True
    cx, cy = float(kf["x"]), float(kf["y"])
    st = float(style.get("stroke_px") or 0.0)
    ia, ib = float(kf["w"]) / 2.0 - st, float(kf["h"]) / 2.0 - st
    if ia <= 0 or ib <= 0:
        return True
    corners = [(m[0], m[1]), (m[0] + m[2], m[1]), (m[0], m[1] + m[3]), (m[0] + m[2], m[1] + m[3])]
    if kind == "box":
        inside = all(abs(x - cx) <= ia and abs(y - cy) <= ib for x, y in corners)
    else:                       # ellipse is convex: all four corners inside -> the whole rect inside
        inside = all(((x - cx) / ia) ** 2 + ((y - cy) / ib) ** 2 <= 1.0 for x, y in corners)
    return not inside


def _kf_at(d, t: float) -> dict:
    from .captions import _interp_kf

    kfs = d.keyframes
    if t <= kfs[0]["t"]:
        return kfs[0]
    for a, b in zip(kfs, kfs[1:]):
        if t <= b["t"]:
            return _interp_kf(a, b, t)
    return kfs[-1]


# ----------------------------------------------------------------------------- tone / own branding
def _sentences(text: str) -> list[str]:
    return [p.strip() for p in SENTENCE_SPLIT_RE.split(text or "") if p and p.strip()]


def _ending_classifier():
    """The reference analyzer's ending classifier (``shortkit.reference.aggregate.ending_class``), so
    the register measured from the reference and the register enforced here are the same thing."""
    from ..reference.aggregate import REGISTER_MAP, ending_class

    return ending_class, REGISTER_MAP


def check_tone(plan: dict, preset: config.Preset, out: list[dict]) -> None:
    """text.tone.register / text.tone.emoji on narration captions (title, description, situation,
    reaction).  Dialogue (real lines), speaker labels and on-screen-text transcriptions are exempt.
    Every sentence is classified by its ending (합쇼체 -습니다/-입니다, 해요체 -요/-죠, 음슴체 -음/-함,
    반말 -다/-어/-야 ...; noun phrases are neutral); a sentence in another register than the preset's
    is an error in production / a warning in test.  혼합 = no single register (nothing to enforce)."""
    prod = plan["mode"] == "production"
    sev = "error" if prod else "warn"
    reg = preset.get("text.tone.register")
    emoji_ok = preset.get("text.tone.emoji")
    check_reg = False
    if reg is None:
        out.append(issue("warn", "tone_register_unmeasured", "자막 말투(text.tone.register) 미측정(못 잼): 종결 어미 검사 안 함",
                         "text.tone.register"))
    elif reg not in TONE_REGISTERS:
        out.append(issue("error", "tone_register_value", f"text.tone.register={reg!r} 미지원 {TONE_REGISTERS}",
                         "text.tone.register"))
    else:
        check_reg = reg != "혼합"
    if emoji_ok is None:
        out.append(issue("warn", "tone_emoji_unmeasured", "자막 이모지 허용 여부(text.tone.emoji) 미측정(못 잼): 검사 안 함",
                         "text.tone.emoji"))
    elif not isinstance(emoji_ok, bool):
        out.append(issue("error", "tone_emoji_value", f"text.tone.emoji={emoji_ok!r}: true/false 만 허용", "text.tone.emoji"))
        emoji_ok = None
    classify = register_map = None
    if check_reg:
        try:
            classify, register_map = _ending_classifier()
        except Exception as e:          # never skip silently
            out.append(issue(sev, "tone_check_unavailable",
                             f"종결 어미 분류기(shortkit.reference.aggregate)를 불러오지 못해 말투 검사를 못 함: "
                             f"{type(e).__name__}: {e}", "text.tone.register"))
            check_reg = False
    for c in plan.get("captions", []):
        if c["role"] not in NARRATION_ROLES or (c.get("grounding") or {}).get("kind") == "on_screen_text":
            continue
        where = f"captions[{c['id']}]"
        if emoji_ok is False and EMOJI_RE.search(c["text"]):
            out.append(issue(sev, "tone_emoji", f"프리셋 text.tone.emoji=false 인데 {c['role']} 자막에 이모지가 있습니다", where))
        if not check_reg:
            continue
        for sent in _sentences(c["text"]):
            got = classify(sent)
            if got is None or got[0] not in register_map:
                continue                # noun phrase / other: register-neutral
            if register_map[got[0]] != reg:
                out.append(issue(sev, "tone_register",
                                 f"'{sent}' 의 끝 '{got[1]}' 은 {register_map[got[0]]} 입니다 — 프리셋 말투는 {reg} "
                                 "(대사 dialogue 는 예외)", where))


def check_own_branding(plan: dict, preset: config.Preset, out: list[dict]) -> None:
    """identity_exclusions.own_branding: 'none' = this preset adds no channel branding, so narration
    captions (title/description/situation/reaction) must not carry an @handle or URL-like text unless
    the caption transcribes text really visible in the footage (grounding.kind = on_screen_text).
    A string / list value = those exact handles/URLs are the allowed own branding (requested change)."""
    own = preset.get("identity_exclusions.own_branding")
    if own in (None, False) or (isinstance(own, str) and own.strip().casefold() == "none"):
        allowed: list[str] = []
    elif isinstance(own, str):
        allowed = [own.strip()]
    elif isinstance(own, (list, tuple)) and all(isinstance(x, str) for x in own):
        allowed = [x.strip() for x in own]
    else:
        out.append(issue("error", "own_branding_value", f"identity_exclusions.own_branding={own!r}: 'none' 또는 허용할 "
                         "핸들/주소 문자열(목록)만 가능", "identity_exclusions.own_branding"))
        return
    allow = {a.casefold() for a in allowed}
    for c in plan.get("captions", []):
        if c["role"] not in NARRATION_ROLES or (c.get("grounding") or {}).get("kind") == "on_screen_text":
            continue
        hits = [m.group(0) for rx in (HANDLE_RE, URL_RE) for m in rx.finditer(c["text"])]
        hits = [h for h in dict.fromkeys(hits) if h.casefold().rstrip(".,!?") not in allow]
        if hits:
            out.append(issue("error", "own_branding_text",
                             f"자막에 채널 핸들/주소 형태 문구 {hits} 가 있습니다: 프리셋 own_branding={own!r} "
                             "(화면 속 글자를 옮긴 것이면 grounding.kind=on_screen_text)", f"captions[{c['id']}]"))


# ----------------------------------------------------------------------------- meaningless tails
def segment_meaning_marks(plan: dict, r, clip, vis_end: float) -> list[tuple[float, str]]:
    """Output times that carry meaning inside one clip: ends of grounded captions shown over it, SFX
    events, kept original sound, freeze end, zoom end, decorations pointing at something, the reveal."""
    grounded = {c["id"] for c in plan.get("captions", []) if c.get("grounding")}
    a, b = clip.out_start, vis_end
    marks: list[tuple[float, str]] = []
    for c in r.captions:
        if c.id in grounded and c.start < b - EPS and c.end > a + EPS:
            marks.append((min(c.end, b), f"자막 {c.id}"))
    for s in r.audio.sfx:
        if a - EPS <= s.event_t <= b + EPS:
            marks.append((s.event_t, f"효과음 사건 {s.id}"))
    for o in r.audio.originals:
        if o.clip_id == clip.id:
            marks.append((min(o.out_end, b), "살린 원음"))
    if clip.freeze:
        marks.append((min(clip.freeze.out_start + clip.freeze.hold, b), "정지"))
    if clip.zoom:
        marks.append((min(clip.out_start + clip.zoom.start + clip.zoom.dur, b), "확대"))
    for d in r.decorations:
        if d.start < b - EPS and d.end > a + EPS:
            marks.append((min(d.end, b), f"장식 {d.id}"))
    rv = plan.get("reveal") or {}
    if rv.get("t") is not None and a - EPS <= float(rv["t"]) <= b + EPS:
        marks.append((float(rv["t"]), "반전"))
    return marks


def check_trim_tail(plan: dict, ctx: ResolveContext, out: list[dict]) -> None:
    """User rule 'trim meaningless tails': a segment must not keep running longer than
    motion.trim.tail_after_meaning_s after its last meaning mark (``segment_meaning_marks``).
    Segments whose purpose is reaction/outro are exempt (the held tail is their point).  The tail
    ends where the next shot starts to appear (crossfade start) or at the clip end."""
    r = ctx.resolved
    tail_max = float(ctx.preset.get("motion.trim.tail_after_meaning_s"))
    segs = {s["id"]: s for s in plan["timeline"]}
    prod = plan["mode"] == "production"
    for i, clip in enumerate(r.clips):
        seg = segs.get(clip.id, {})
        purpose = (seg.get("purpose") or "").strip().casefold()
        reason = str(seg.get("tail_reason") or "").strip()
        exempt = bool(purpose) and purpose.split()[0] in TAIL_EXEMPT_PURPOSES
        # production: a held tail needs its stated reason (tail_reason) -- a reaction/outro purpose alone is not one
        if exempt and not prod:
            continue
        sev = "warn" if (reason or not prod) else "error"
        nxt = r.clips[i + 1] if i + 1 < len(r.clips) else None
        vis_end = nxt.out_start if (nxt is not None and nxt.transition_in.type == "crossfade") else clip.out_end
        where = f"timeline[{clip.id}]"
        marks = segment_meaning_marks(plan, r, clip, vis_end)
        if not marks:
            if vis_end - clip.out_start > tail_max + 1e-6:
                out.append(issue(sev, "trim_no_meaning",
                                 f"세그먼트 {clip.id}({vis_end - clip.out_start:.2f}s)에 의미 표지(근거 있는 자막·효과음 사건·"
                                 "살린 원음·정지·확대·장식)가 없습니다: 필요 없는 구간이면 자르고, 남겨야 하면 tail_reason 에 이유"
                                 + (f" — 남긴 이유: {reason}" if reason else ""), where))
            continue
        t_last, what = max(marks)
        tail = vis_end - t_last
        if tail > tail_max + 1e-6:
            out.append(issue(sev, "trim_tail",
                             f"세그먼트 {clip.id} 가 마지막 의미({what}, {t_last:.2f}s) 뒤로 {tail:.2f}s 더 이어집니다 "
                             f"(> motion.trim.tail_after_meaning_s {tail_max}s): 의미가 끝난 꼬리는 자르기"
                             "(중요한 동작이면 자막/사건으로 표시, 남겨야 하는 꼬리면 tail_reason 에 이유)"
                             + (f" — 남긴 이유: {reason}" if reason else ""), where))


# ----------------------------------------------------------------------------- cuts inside actions / lines (S3-06)
CUT_MARGIN_S = 0.05              # a boundary this close to an action edge is at the edge, not inside
SPEECH_CUT_TOL_S = 0.15          # speech continuing longer than this past a kept range's edge = the line is cut


def check_cuts(plan: dict, ctx: ResolveContext, out: list[dict]) -> None:
    """Never cut an important action or a kept line (S3-06).  Production = error, test = warning:
    * ``actions[] {id, source, src_start, src_end, desc}``: a segment boundary (src_in/src_out) strictly inside an
      action of the same source cuts it;
    * a kept original range must not start/end in the middle of speech (automatic speech check of the audio it
      keeps: raw or vocals stem);
    * a heard dialogue line (grounding kind heard) must not be cut by the segment that shows it."""
    from .audio_checks import span_at

    prod = plan["mode"] == "production"
    sev = "error" if prod else "warn"
    srcs = {s["id"]: s for s in plan["sources"]}
    for act in plan.get("actions") or []:
        a0, a1 = float(act["src_start"]), float(act["src_end"])
        for seg in plan["timeline"]:
            if seg["source"] != act["source"]:
                continue
            for edge, v in (("src_in", float(seg["src_in"])), ("src_out", float(seg["src_out"]))):
                if a0 + CUT_MARGIN_S < v < a1 - CUT_MARGIN_S:
                    out.append(issue(sev, "cut_inside_action",
                                     f"구간 {seg['id']} 의 {edge}={v}s 가 중요한 동작 '{act.get('desc') or act.get('id')}'"
                                     f"({a0}~{a1}s) 한가운데를 자릅니다", f"timeline[{seg['id']}]"))
    cache: dict[str, dict] = {}

    def speech_of(stored: str) -> dict:
        from .audio_checks import speech_spans

        if stored not in cache:
            cache[stored] = speech_spans(stored)
        return cache[stored]

    for seg in plan["timeline"]:
        oa = seg.get("original_audio") or {}
        if not oa.get("keep"):
            continue
        s = srcs.get(seg["source"])
        if not s:
            continue
        stored = s.get("vocals_path") if (oa.get("stem") or "raw") == "vocals" else s["path"]
        if not stored or not paths.absp(stored).is_file():
            continue
        sp = speech_of(stored)
        if sp["status"] != "measured":
            continue                    # reported by the kept-speech check (check_audio)
        for a, b in oa.get("ranges") or [[seg["src_in"], seg["src_out"]]]:
            a, b = float(a), float(b)
            for x, y in sp["spans"]:
                if x < b - CUT_MARGIN_S and y > b + SPEECH_CUT_TOL_S:
                    out.append(issue(sev, "kept_speech_cut",
                                     f"살린 원음 [{a}, {b}] 이 말하는 중간({x:.2f}~{y:.2f}s 말소리)의 {b}s 에서 끊깁니다", 
                                     f"timeline[{seg['id']}].original_audio"))
                if x < a - SPEECH_CUT_TOL_S and y > a + CUT_MARGIN_S:
                    out.append(issue(sev, "kept_speech_cut",
                                     f"살린 원음 [{a}, {b}] 이 말하는 중간({x:.2f}~{y:.2f}s 말소리)의 {a}s 에서 시작합니다",
                                     f"timeline[{seg['id']}].original_audio"))
    for c in plan.get("captions") or []:
        g = c.get("grounding") or {}
        if c["role"] != "dialogue" or g.get("kind") != "heard" or not g.get("source") or g.get("src_t") is None:
            continue
        s = srcs.get(g["source"])
        if not s:
            continue
        stored, _ = speech_source(s)
        if not stored or not paths.absp(stored).is_file():
            continue
        sp = speech_of(stored)
        span = span_at(sp["spans"], float(g["src_t"]), HEARD_TOL_S) if sp["status"] == "measured" else None
        if span is None:
            continue                    # grounding_no_speech / grounding_speech_unmeasured report it
        segs = [seg for seg in plan["timeline"] if seg["source"] == g["source"]
                and float(seg["src_in"]) - EPS <= float(g["src_t"]) <= float(seg["src_out"]) + EPS]
        for seg in segs:
            if float(seg["src_out"]) < span[1] - SPEECH_CUT_TOL_S or float(seg["src_in"]) > span[0] + SPEECH_CUT_TOL_S:
                out.append(issue(sev, "dialogue_line_cut",
                                 f"대사 자막 {c['id']} 의 말({span[0]:.2f}~{span[1]:.2f}s)을 구간 {seg['id']}"
                                 f"({seg['src_in']}~{seg['src_out']}s)이 중간에서 자릅니다", f"captions[{c['id']}]"))


# ----------------------------------------------------------------------------- repetition (S3-07)
def check_repetition(plan: dict, ctx: ResolveContext, out: list[dict]) -> None:
    """Do not stack the same effect or repeat to pad (S3-07): consecutive captions of one role with the same
    text; two decorations of the same kind drawn over the same place at the same time.
    Production = error, test = warning (segment repeats / stacked transitions: ``check_motion``)."""
    from .captions import deco_shape

    prod = plan["mode"] == "production"
    sev = "error" if prod else "warn"
    by_role: dict[str, list[dict]] = defaultdict(list)
    for c in sorted(plan.get("captions") or [], key=lambda c: float(c["start"])):
        by_role[c["role"]].append(c)
    for role, cs in by_role.items():
        for a, b in zip(cs, cs[1:]):
            if " ".join(a["text"].split()).casefold() == " ".join(b["text"].split()).casefold():
                out.append(issue(sev, "caption_repeat",
                                 f"같은 {role} 자막 '{b['text']}' 이 연달아 반복됩니다({a['id']} → {b['id']}): 같은 효과 쌓기·분량 채우기 금지",
                                 f"captions[{b['id']}]"))
    decos = ctx.resolved.decorations
    for i, a in enumerate(decos):
        for b in decos[i + 1:]:
            if a.kind != b.kind:
                continue
            t0, t1 = max(a.start, b.start), min(a.end, b.end)
            if t1 <= t0 + EPS:
                continue
            tm = (t0 + t1) / 2

            def rect(d):
                kf = _kf_at(d, tm)
                polys, _ = deco_shape(d.kind, kf, d.style)
                xs = [x for pp in polys for x, _ in pp]
                ys = [y for pp in polys for _, y in pp]
                return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)

            ra, rb = rect(a), rect(b)
            ix = max(0.0, min(ra[0] + ra[2], rb[0] + rb[2]) - max(ra[0], rb[0]))
            iy = max(0.0, min(ra[1] + ra[3], rb[1] + rb[3]) - max(ra[1], rb[1]))
            inter = ix * iy
            union = ra[2] * ra[3] + rb[2] * rb[3] - inter
            if union > 0 and inter / union >= 0.5:
                out.append(issue(sev, "decoration_duplicate",
                                 f"장식 {a.id}·{b.id}({a.kind}) 이 같은 때({t0:.2f}~{t1:.2f}s) 같은 자리에 겹쳐 그려집니다(같은 효과 쌓기)",
                                 f"decorations[{b.id}]"))


# ----------------------------------------------------------------------------- protected declared (S3-08)
def check_protected_declared(plan: dict, out: list[dict]) -> None:
    """Faces / hands / key objects must be declared for every source shown (captions and decorations are checked
    against them).  An empty list is allowed only with ``protected_reviewed {by, at, note}`` (someone looked and
    found nothing to protect).  Production = error, test = warning."""
    prod = plan["mode"] == "production"
    used = {seg["source"] for seg in plan["timeline"]}
    for s in plan["sources"]:
        if s["id"] not in used or s.get("protected"):
            continue
        rv = s.get("protected_reviewed") or {}
        if str(rv.get("by") or "").strip() and rv.get("at") and str(rv.get("note") or "").strip():
            continue
        out.append(issue("error" if prod else "warn", "protected_missing",
                         f"소스 {s['id']} 에 보호 영역(얼굴·손·핵심 물체)이 없습니다: 자막·장식이 가리는지 검사할 수 없음 — 적거나, "
                         "보호할 것이 없음을 확인했으면 protected_reviewed: {by, at, note}", f"sources[{s['id']}].protected"))


# ----------------------------------------------------------------------------- Korean narration (S3-10)
HANGUL_MIN_SHARE = 0.5
KOREAN_ROLES = ("title", "description", "situation", "reaction", "speaker")


def hangul_share(text: str, allow: list[str] | None = None) -> float | None:
    t = text
    for a in allow or []:
        if a:
            t = t.replace(a, " ")
    letters = [ch for ch in t if ch.isalpha()]
    if not letters:
        return None
    hang = sum(1 for ch in letters if "\uac00" <= ch <= "\ud7a3" or "\u1100" <= ch <= "\u11ff" or "\u3130" <= ch <= "\u318f")
    return hang / len(letters)


def check_korean(plan: dict, out: list[dict]) -> None:
    """Our own caption text is short natural KOREAN: title/description/situation/reaction/speaker captions whose
    letters are less than HANGUL_MIN_SHARE Hangul are an error in production / warning in test -- unless the
    caption transcribes on-screen text (grounding.kind on_screen_text) or the foreign words are listed in
    ``captions[].foreign_terms`` (names, handles, brand names).  Dialogue is what was said (exempt)."""
    prod = plan["mode"] == "production"
    for c in plan.get("captions") or []:
        if c["role"] not in KOREAN_ROLES or (c.get("grounding") or {}).get("kind") == "on_screen_text":
            continue
        sh = hangul_share(c["text"], c.get("foreign_terms"))
        if sh is not None and sh < HANGUL_MIN_SHARE:
            out.append(issue("error" if prod else "warn", "caption_not_korean",
                             f"{c['role']} 자막 '{c['text']}' 의 글자 중 한글이 {sh:.0%} 뿐입니다(< {HANGUL_MIN_SHARE:.0%}): 한국어로 쓰기"
                             "(고유 이름·핸들이면 foreign_terms 에 적기)", f"captions[{c['id']}]"))


# ----------------------------------------------------------------------------- SFX
def check_sfx(plan: dict, ctx: ResolveContext, out: list[dict], allow_unmeasured: bool) -> None:
    pr, r = ctx.preset, ctx.resolved
    prod = plan["mode"] == "production"
    if pr.get("audio.sfx.require_event") is not True:
        out.append(issue("error", "rule_sfx_event", "audio.sfx.require_event 는 true 여야 합니다(사용자 규칙)",
                         "audio.sfx.require_event"))
    max_off = float(pr.get("audio.sfx.max_event_offset_s"))
    boundaries = [c.out_start for c in r.clips[1:]]
    by_type: dict[str, list[dict]] = defaultdict(list)
    for s in plan.get("sfx") or []:
        where = f"sfx[{s['id']}]"
        ev = s.get("event") or {}
        by_type[s["type"]].append(s)
        if not ev or not ev.get("desc"):
            out.append(issue("error", "sfx_no_event", "효과음에 화면 사건(event)이 없습니다", where))
            continue
        kind = (ev.get("kind") or "").strip().casefold()
        desc_n = "".join(ev["desc"].split()).casefold()
        if kind == "cut" or desc_n in {"".join(w.split()) for w in CUT_WORDS}:
            out.append(issue("error", "sfx_cut_event", "효과음은 컷 때문이 아니라 화면 속 사건 때문에 넣는다(event.kind=cut 금지)", where))
        if abs(float(s["t"]) - float(ev["t"])) > max_off + 1e-9:
            out.append(issue("error", "sfx_event_offset",
                             f"|sfx.t − event.t| = {abs(float(s['t']) - float(ev['t'])):.3f}s > {max_off}s", where))
        if not (0 <= float(s["t"]) < r.duration):
            out.append(issue("error", "sfx_time", f"효과음 시각 {s['t']}s 가 영상 길이 밖", where))
        if not (0 <= float(ev["t"]) <= r.duration):
            out.append(issue("error", "sfx_event_time", f"사건 시각 {ev['t']}s 가 영상 길이 밖", where))
        if not ev.get("source") or ev.get("src_t") is None:
            out.append(issue("error" if prod else "warn", "sfx_event_source_missing",
                             "효과음 사건에는 원본 위치(event.source, event.src_t)가 필요합니다: 화면 속 어느 순간인지 적어야 "
                             "사건과 효과음의 시차·컷과의 구분을 검사할 수 있음", where))
    # the stated event time must be where that source moment really appears in the output
    from .resolve import src_to_out_time

    for s in plan.get("sfx") or []:
        ev = s.get("event") or {}
        if ev.get("source") and ev.get("src_t") is not None:
            cands = [src_to_out_time(c, float(ev["src_t"])) for c in r.clips
                     if c.source_id == ev["source"] and c.src_in - EPS <= float(ev["src_t"]) <= c.src_out + EPS]
            where = f"sfx[{s['id']}]"
            if not cands:
                out.append(issue("error", "sfx_event_not_shown",
                                 f"사건 원본 시각 {ev['source']}@{ev['src_t']}s 가 편집본에 나오지 않습니다", where))
                continue
            real = min(cands, key=lambda x: abs(x - float(ev["t"])))
            d = abs(real - float(ev["t"]))
            if abs(float(s["t"]) - real) > max_off + 1e-9:
                out.append(issue("error", "sfx_event_mismatch",
                                 f"사건이 실제로 보이는 시각 {real:.2f}s 와 효과음 {float(s['t']):.2f}s 차이가 {max_off}s 를 넘습니다", where))
            elif d > 0.05:
                out.append(issue("warn", "sfx_event_time_drift",
                                 f"event.t {ev['t']}s 와 원본 시각이 가리키는 출력 시각 {real:.2f}s 가 {d:.2f}s 다릅니다", where))
    check_sfx_at_cut(plan, ctx, out)
    for typ, lst in by_type.items():
        ts = sorted(float(s["t"]) for s in lst)
        for a, b in zip(ts, ts[1:]):
            if b - a < SFX_STACK_WINDOW_S - 1e-9:
                out.append(issue("error", "sfx_stacking", f"같은 효과음 '{typ}' 이 {b - a:.2f}s 간격으로 겹쳐 쌓였습니다"
                                 f"(<{SFX_STACK_WINDOW_S}s)", f"sfx[{typ}@{b:.2f}]"))
    # observed ranges from the catalog
    cat = sfxmap.load_catalog(pr)
    fid = None if plan["format_id"] == TEST_FORMAT_ID else plan["format_id"]
    counts_ok = catalog_counts_measured(cat)
    if cat.get("status") != "measured":
        # production stays blocked while the catalog is not fully measured (unless --allow-unmeasured)
        sev = "error" if (prod and not allow_unmeasured) else "warn"
        if counts_ok:
            gaps = catalog_unmeasured_columns(cat)
            out.append(issue(sev, "sfx_catalog_partial",
                             "효과음 카탈로그 일부 못 잼(status partial): 편당 개수는 모든 대상 영상에서 셌으므로 개수 규칙은 "
                             "검사하지만, 종류별 열 " + (", ".join(f"{c}({len(v)}종류)" for c, v in gaps.items()) or "?")
                             + f" 이 측정되지 않아 카탈로그가 완성되지 않음 ({cat.get('blocker') or '-'})", "sfx"))
        else:
            out.append(issue(sev, "sfx_range_unmeasured",
                             f"효과음 카탈로그 미측정(못 잼): 종류별 개수·분포가 포맷 관측 범위 안인지 판정 불가 "
                             f"({cat.get('blocker') or cat.get('_path')})", "sfx"))
    if counts_ok:
        check_sfx_counts(plan, ctx, cat, fid, by_type, out, prod and not allow_unmeasured)
    check_sfx_catalog_rules(plan, ctx, cat, out, allow_unmeasured)
    check_sfx_files(plan, ctx, cat, out, allow_unmeasured)


SFX_CUT_WINDOW_S = 0.1           # an event this close to a cut is "at the cut" unless a planned screen event is there too
SCREEN_EVENT_WINDOW_S = 0.1


def planned_screen_events(r) -> list[tuple[float, str]]:
    """Screen events of OUR edit in the reference analyzer's vocabulary (``reference.sfx_catalog.screen_events``):
    cut / flash / crossfade at clip boundaries, zoom_in / zoom_out at zoom start, freeze at the hold start, speed at a
    speed-changed clip, text_<motion_in> / text_on at caption starts, decoration starts ("decoration")."""
    ev: list[tuple[float, str]] = []
    for i, c in enumerate(r.clips):
        if i:
            ev.append((c.out_start, c.transition_in.type if c.transition_in.type in ("flash", "crossfade") else "cut"))
        if c.zoom:
            ev.append((c.out_start + c.zoom.start, "zoom_in" if c.zoom.scale_to >= c.zoom.scale_from else "zoom_out"))
        if c.freeze:
            ev.append((c.freeze.out_start, "freeze"))
        if abs(c.speed - 1.0) > 1e-9:
            ev.append((c.out_start, "speed"))
    for cap in r.captions:
        mi = (cap.motion_in or {}).get("type")
        ev.append((cap.start, "text_pop" if mi == "pop" else (f"text_{mi}" if mi and mi != "none" else "text_on")))
    for d in r.decorations:
        ev.append((d.start, "decoration"))
    return sorted(ev)


CUT_KINDS_EDIT = ("cut", "crossfade", "flash")


def _event_out_time(ev: dict, r) -> float:
    from .resolve import src_to_out_time

    if ev.get("source") and ev.get("src_t") is not None:
        cands = [src_to_out_time(c, float(ev["src_t"])) for c in r.clips
                 if c.source_id == ev["source"] and c.src_in - EPS <= float(ev["src_t"]) <= c.src_out + EPS]
        if cands:
            return min(cands, key=lambda x: abs(x - float(ev["t"])))
    return float(ev["t"])


def check_sfx_at_cut(plan: dict, ctx: ResolveContext, out: list[dict]) -> None:
    """SFX are placed because of an on-screen event, never because of a cut (S4-08): an event that falls on a cut
    (within SFX_CUT_WINDOW_S of a clip boundary, e.g. the first frame of the new clip) is an error in production /
    warning in test -- whatever its kind label says -- unless a planned non-cut screen event (zoom start, freeze,
    caption appearance, decoration) is at the same moment."""
    prod = plan["mode"] == "production"
    r = ctx.resolved
    evs = planned_screen_events(r)
    cuts = [t for t, k in evs if k in CUT_KINDS_EDIT]
    for s in plan.get("sfx") or []:
        ev = s.get("event") or {}
        if not ev.get("desc"):
            continue
        t = _event_out_time(ev, r)
        near_cut = [c for c in cuts if abs(c - t) < SFX_CUT_WINDOW_S]
        if not near_cut:
            continue
        other = [(x, k) for x, k in evs if k not in CUT_KINDS_EDIT and abs(x - t) <= SCREEN_EVENT_WINDOW_S]
        if other:
            continue
        out.append(issue("error" if prod else "warn", "sfx_event_at_cut",
                         f"사건 '{ev['desc']}'({t:.2f}s) 이 컷 경계({near_cut[0]:.2f}s)에 있고 같은 순간에 컷 말고 다른 화면 사건"
                         "(확대·정지·자막 등장·장식)이 없습니다: 컷 때문에 넣은 효과음으로 봄(kind 이름으로는 면제되지 않음)",
                         f"sfx[{s['id']}]"))


def _plan_screen_event_at(evs: list[tuple[float, str]], t: float, window: float) -> str:
    """Nearest planned screen event within +-window (the analyzer's rule: a non-cut event almost as close wins)."""
    near = sorted((abs(x - t), k) for x, k in evs if abs(x - t) <= window)
    if not near:
        return "none"
    non_cut = [z for z in near if z[1] not in ("cut", "crossfade")]
    return (non_cut[0] if non_cut and non_cut[0][0] <= near[0][0] + 0.1 else near[0])[1]


def _prev_caption_role(r, t: float) -> str:
    prev = [c for c in r.captions if c.start <= t + 0.05]
    return max(prev, key=lambda c: c.start).role if prev else "none"


def catalog_counts_measured(cat: dict) -> bool:
    """The catalog's per-video counts cover every target video: status 'measured', or 'partial' (every target video
    analysed and counted; only a per-type column such as emotion is not measured for every event) with
    ``column_status.per_video_count == 'measured'`` (never 'lower_bound').  'unmeasured' (a target video missing, or
    SFX under speech not measurable) -> False."""
    cs = cat.get("column_status") or {}
    if cat.get("status") == "measured":
        return cs.get("per_video_count", "measured") == "measured"
    return cat.get("status") == "partial" and cs.get("per_video_count") == "measured"


def catalog_column_state(t: dict, col: str) -> str:
    """measured | partial | unmeasured of one per-type catalog column: ``types[].columns[col]`` (written by
    ``ref sfx-catalog``), else derived the same way (``sfx_catalog._column_status``: no value -> unmeasured, some
    events without a value -> partial)."""
    cols = t.get("columns") or {}
    if col in cols:
        return str(cols[col])
    c = t.get(col) or {}
    if not c.get("n"):
        return "unmeasured"
    return "partial" if c.get("n_missing") or c.get("status") == "partial" else "measured"


def catalog_unmeasured_columns(cat: dict) -> dict[str, list[str]]:
    """{column: [type ids whose column is not measured]} over the catalog's required per-type columns
    (``reference.sfx_catalog.REQUIRED_COLUMNS``)."""
    from ..reference.sfx_catalog import REQUIRED_COLUMNS

    out: dict[str, list[str]] = {}
    for t in cat.get("types") or []:
        for c in REQUIRED_COLUMNS:
            if catalog_column_state(t, c) != "measured":
                out.setdefault(c, []).append(str(t.get("type_id")))
    return out


def check_sfx_catalog_rules(plan: dict, ctx: ResolveContext, cat: dict, out: list[dict], allow_unmeasured: bool) -> None:
    """The catalog's per-type placement rules are production rules (S4-06): the sound's emotion (tagged after the
    event was checked) must be one the reference shows for that type; the screen event at the sound and the role of
    the caption before it must be among those observed for the type.  sfx[].emotion is required in production.
    The catalog is used when its counts are measured (status measured, or partial: ``catalog_counts_measured``) and
    each column only when ``types[].columns`` marks it 'measured' -- a 'partial' column (some events without a value)
    is NOT a rule: 못 잼 (error in production unless --allow-unmeasured)."""
    prod = plan["mode"] == "production"
    sev = "error" if prod else "warn"
    un_sev = "error" if (prod and not allow_unmeasured) else "warn"
    r = ctx.resolved
    for s in plan.get("sfx") or []:
        if not str(s.get("emotion") or "").strip():
            out.append(issue(sev, "sfx_emotion_missing",
                             "효과음 감정(emotion)이 없습니다: 사건을 확인한 뒤 감정을 붙이고 카탈로그 규칙에 맞는 소리를 고른다",
                             f"sfx[{s['id']}]"))
    if not catalog_counts_measured(cat):
        return
    types = {t.get("type_id"): t for t in cat.get("types") or []}
    evs = planned_screen_events(r)
    ko = {"emotion": "감정", "screen_event": "화면 사건 분포", "prev_caption_role": "직전 자막 역할 분포"}

    def unmeasured(s: dict, col: str, where: str) -> None:
        c = types[s["type"]].get(col) or {}
        state = catalog_column_state(types[s["type"]], col)
        why = (f"일부 이벤트만 값이 있음(partial: {c.get('n_missing')}/{c.get('n_events')} 누락)" if state == "partial"
               else str(c.get("blocker") or "값 없음"))
        out.append(issue(un_sev, f"sfx_{col}_unmeasured",
                         f"카탈로그 '{s['type']}' 의 {ko[col]} 못 잼({why}): 이 자리의 효과음이 레퍼런스 규칙에 맞는지 판정 불가",
                         where))

    for s in plan.get("sfx") or []:
        t = types.get(s["type"])
        if not t:
            continue
        where = f"sfx[{s['id']}]"
        emo = t.get("emotion") or {}
        if catalog_column_state(t, "emotion") != "measured":
            unmeasured(s, "emotion", where)
        elif str(s.get("emotion") or "").strip() and s["emotion"] not in (emo.get("share") or {}):
            out.append(issue(sev, "sfx_emotion_mismatch",
                             f"감정 '{s['emotion']}' 은 레퍼런스의 '{s['type']}' 감정 {sorted(emo.get('share') or {})} 에 없습니다",
                             where))
        se = t.get("screen_event") or {}
        if catalog_column_state(t, "screen_event") != "measured":
            unmeasured(s, "screen_event", where)
        else:
            got = _plan_screen_event_at(evs, float(s["t"]), float(t.get("event_window_s") or SCREEN_EVENT_WINDOW_S))
            if got not in (se.get("share") or {}):
                out.append(issue(sev, "sfx_screen_event_mismatch",
                                 f"'{s['type']}' 는 레퍼런스에서 화면 사건 {se.get('share')} 에 맞춰 나오는데 이 자리"
                                 f"({float(s['t']):.2f}s)의 화면 사건은 '{got}' 입니다", where))
        pc = t.get("prev_caption_role") or {}
        if catalog_column_state(t, "prev_caption_role") != "measured":
            unmeasured(s, "prev_caption_role", where)
        else:
            got = _prev_caption_role(r, float(s["t"]))
            if got not in (pc.get("share") or {}):
                out.append(issue(sev, "sfx_prev_caption_mismatch",
                                 f"'{s['type']}' 앞 자막 역할이 레퍼런스에서는 {pc.get('share')} 인데 여기서는 '{got}' 입니다", where))


def check_sfx_files(plan: dict, ctx: ResolveContext, cat: dict, out: list[dict], allow_unmeasured: bool) -> None:
    """An explicit sfx[].file must sound like its catalog type (S4-07): log-mel fingerprint similarity to the type's
    centroid (``reference.sfx_map``'s method and MATCH_THRESHOLD).  Below the threshold: error in production /
    warning in test; no centroid (catalog unmeasured): 못 잼."""
    prod = plan["mode"] == "production"
    sev = "error" if prod else "warn"
    un_sev = "error" if (prod and not allow_unmeasured) else "warn"
    # the fingerprint centroids come from clustering every target video: usable when the counts are (partial too)
    types = {t.get("type_id"): t for t in cat.get("types") or []} if catalog_counts_measured(cat) else {}
    for sp in ctx.resolved.audio.sfx:
        x = next((s for s in plan.get("sfx") or [] if s["id"] == sp.id), {})
        if not x.get("file") or not sp.path:
            continue
        where = f"sfx[{sp.id}].file"
        t = types.get(sp.type)
        cen = ((t or {}).get("fingerprint") or {}).get("centroid")
        if not cen or not paths.absp(cen).is_file():
            out.append(issue(un_sev if prod else "warn", "sfx_file_type_unmeasured",
                             f"명시 파일 {sp.path} 이 종류 '{sp.type}' 소리인지 비교할 카탈로그 지문이 없음(못 잼)", where))
            continue
        try:
            sim = sfx_file_similarity(sp.path, cen)
        except Exception as e:           # never a silent pass
            out.append(issue(un_sev, "sfx_file_type_unmeasured", f"지문 비교 실패(못 잼): {type(e).__name__}: {e}", where))
            continue
        from ..reference.sfx_map import MATCH_THRESHOLD

        if sim < MATCH_THRESHOLD:
            out.append(issue(sev, "sfx_file_type_mismatch",
                             f"명시 파일 {sp.path} 의 소리가 종류 '{sp.type}' 와 다릅니다(지문 유사도 {sim:.3f} < {MATCH_THRESHOLD})", where))


def sfx_file_similarity(stored: str, centroid: str) -> float:
    import numpy as np

    from ..reference.separation import load_mono
    from ..reference.sfx_events import SR as FP_SR, fingerprint_clip, similarity_matrix
    from ..reference.sfx_map import MAX_FILE_S, onset_of

    x = load_mono(paths.absp(stored), FP_SR)[: int(MAX_FILE_S * FP_SR)]
    on = onset_of(x)
    fp = fingerprint_clip(x, FP_SR, on)
    c = np.load(paths.absp(centroid)).astype(np.float32)
    return float(similarity_matrix([c], [fp["patch"]])[0][0])


# SFX count rule (user: "편당 개수와 종류 분포는 해당 포맷의 관측 범위에 맞춘다"):
# * Only ADDED effects are counted: catalog types of class ``edit_sfx``, plus ``intentional_silence``
#   when the plan has silences (plan.bgm.silences).  ``onsite_sound`` types are sounds of the reference's
#   own footage (source audio), not effects an editor adds, so they are neither counted nor placeable.
# * Allowed per-episode count for a type (and for the total) = [floor(p10), ceil(p90)] of the observed
#   per-video counts of the plan's format (``per_video_count.by_format[F]``, else ``overall``): counts are
#   integers, and the linearly interpolated p10/p90 of a small sample can fall between integers.
# * ALSO allowed: any count observed at least once in that format's reference videos (with n = 5 the
#   interpolated p10 = 0.4 would otherwise exclude a count of 0 that a reference video really has).
#   The per-video counts come from the catalog entry's ``per_video_count.videos`` when present, otherwise
#   from the per-video ``sfx_events.json`` files into which ``ref sfx-catalog`` writes the type ids (only
#   when they reproduce the catalog's own n/p10/p50/p90; otherwise only the range rule is applied).
#   Counts of ``lower_bound_videos`` (SFX under speech not measurable) are lower bounds: a count accepted
#   only because such a video showed it gets a warning.
COUNTED_SFX_CLASS = "edit_sfx"
SILENCE_CLASS = "intentional_silence"
ONSITE_CLASS = "onsite_sound"


def allowed_count_range(st: dict) -> tuple[int, int]:
    """[floor(p10), ceil(p90)] of an observed per-video count distribution."""
    return int(math.floor(float(st["p10"]) + 1e-9)), int(math.ceil(float(st["p90"]) - 1e-9))


def observed_sfx_counts(cat: dict, preset, format_id: str | None) -> dict:
    """Per-video counts behind the catalog statistics, restricted to the videos of ``format_id`` (all
    videos when None).  Returns {"types": {type_id: {video_id: count}}, "videos", "lower_bound", "source",
    "problem"}; ``problem`` set = no usable per-video counts (then only the range rule applies)."""
    basis = cat.get("basis") or {}
    vids = [str(v) for v in basis.get("videos") or []]
    types = [t for t in cat.get("types") or [] if t.get("type_id")]
    res: dict = {"types": {}, "videos": [], "all_types": {}, "all_videos": vids, "formats": {},
                 "lower_bound": set(), "source": None, "problem": None}
    if not vids or not types:
        res["problem"] = "카탈로그 basis.videos 가 비어 있음"
        return res
    for t in types:
        res["lower_bound"] |= set((t.get("per_video_count") or {}).get("lower_bound_videos") or [])
    counts: dict[str, dict[str, int]] = {t["type_id"]: {v: 0 for v in vids} for t in types}
    if all(isinstance((t.get("per_video_count") or {}).get("videos"), dict) for t in types):
        for t in types:
            for v, c in t["per_video_count"]["videos"].items():
                if str(v) in counts[t["type_id"]]:
                    counts[t["type_id"]][str(v)] = int(c)
        res["source"] = "sfx_catalog per_video_count.videos"
    else:
        from ..reference.sfx_events import sfx_events_path

        for v in vids:
            d = read_json(sfx_events_path(preset.name, v))
            if not d or not d.get("catalog"):
                res["problem"] = f"{v} 의 sfx_events.json 에 카탈로그 종류 배정이 없음"
                return res
            for e in d.get("events") or []:
                if e.get("type_id") in counts:
                    counts[e["type_id"]][v] += 1
        res["source"] = "analysis/<video>/audio/sfx_events.json (ref sfx-catalog 가 배정한 type_id)"
    from ..reference.sfx_catalog import video_formats
    from ..util.stats import pstats_by_group

    fmts = video_formats(preset.name)
    for t in types:       # the per-video counts must reproduce the catalog's own statistics
        rows = [{"format_id": fmts.get(v), "count": counts[t["type_id"]][v]} for v in vids]
        mine = pstats_by_group(rows, "count")["overall"]
        theirs = (t.get("per_video_count") or {}).get("overall") or {}
        if theirs.get("n") and any(theirs.get(k) is None or abs(float(mine[k]) - float(theirs[k])) > 1e-3
                                   for k in ("n", "p10", "p50", "p90")):
            res["problem"] = (f"영상별 개수가 카탈로그 통계와 다름('{t['type_id']}': {mine} ≠ {theirs}) — "
                              "카탈로그를 다시 만들어야 함")
            return res
    sel = [v for v in vids if format_id is None or fmts.get(v) == format_id]
    res.update({"videos": sel, "types": {tid: {v: c[v] for v in sel} for tid, c in counts.items()},
                "all_types": counts, "formats": fmts})
    return res


def _count_verdict(out: list[dict], what: str, cnt: int, st: dict | None, basis: str, per_video: dict | None,
                   lower_bound: set, obs_basis_ok: bool, code: str, unmeasured_sev: str, where: str = "sfx") -> None:
    if st is None or st.get("p10") is None or st.get("p90") is None:
        out.append(issue(unmeasured_sev, code.replace("_range", "_unmeasured"),
                         f"{what} 영상당 개수 분포 미측정(못 잼)", where))
        return
    lo, hi = allowed_count_range(st)
    if lo <= cnt <= hi:
        return
    seen = {v: c for v, c in (per_video or {}).items() if c == cnt} if obs_basis_ok else {}
    exact = sorted(v for v in seen if v not in lower_bound)
    if exact:
        return
    rng = f"[floor(p10), ceil(p90)] = [{lo}, {hi}] (p10 {st['p10']}, p90 {st['p90']}, n={st.get('n')}, {basis})"
    if seen:
        out.append(issue("warn", code.replace("_range", "_lower_bound"),
                         f"{what} {cnt}개는 {rng} 밖이고, 대사 구간 효과음을 못 잰(하한값) 영상 "
                         f"{', '.join(sorted(seen))} 에서만 관측된 개수입니다", where))
        return
    obs = sorted(set((per_video or {}).values())) if obs_basis_ok else None
    out.append(issue("error", code, f"{what} {cnt}개가 관측 범위 {rng} 밖"
                     + (f"이고 레퍼런스 영상에서 관측된 개수({obs})도 아닙니다" if obs is not None else
                        "(영상별 관측 개수 없음)"), where))


def check_sfx_counts(plan: dict, ctx: ResolveContext, cat: dict, fid: str | None, by_type: dict,
                     out: list[dict], strict: bool) -> None:
    """Per-type counts and the total against the format's observed range (rule above)."""
    types = {t.get("type_id"): t for t in cat.get("types") or []}
    silences = list((plan.get("bgm") or {}).get("silences") or [])
    counted = {COUNTED_SFX_CLASS} | ({SILENCE_CLASS} if silences else set())
    for typ in by_type:
        if typ not in types:
            out.append(issue("error", "sfx_type_unknown", f"카탈로그에 없는 효과음 종류 '{typ}'", "sfx"))
        elif types[typ].get("class") == ONSITE_CLASS:
            out.append(issue("error", "sfx_type_onsite",
                             f"'{typ}' 는 현장음(레퍼런스 원본 소리) 종류라 편집 효과음으로 넣을 수 없습니다", "sfx"))
    obs = observed_sfx_counts(cat, ctx.preset, fid)
    obs_ok = obs["problem"] is None
    if not obs_ok:
        out.append(issue("warn", "sfx_observed_counts_unavailable",
                         f"영상별 관측 개수를 쓸 수 없어 [floor(p10), ceil(p90)] 범위만 검사: {obs['problem']}", "sfx"))
    unmeasured_sev = "warn"
    counted_types = [t for t, e in types.items() if e.get("class") in counted]
    has_silence_type = any(types[t].get("class") == SILENCE_CLASS for t in counted_types)
    if silences and not has_silence_type:
        # a measured catalog without an intentional_silence type = no reference video showed one (count 0)
        out.append(issue("error", "sfx_silence_unobserved",
                         f"계획의 의도적 정적 {len(silences)}개: 측정된 카탈로그에 의도적 정적 종류가 없음"
                         "(레퍼런스 영상 모두 0개) → 관측 범위 밖", "bgm.silences"))
    for typ in counted_types:
        ent = types[typ]
        cnt = len(silences) if ent.get("class") == SILENCE_CLASS else len(by_type.get(typ, []))
        st, basis = sfxmap.count_range(ent.get("per_video_count"), fid)
        # observed counts of the same video set as the range (format videos only for a by_format range)
        pv = (obs["types"] if basis.startswith("by_format") else obs["all_types"]).get(typ)
        _count_verdict(out, f"'{typ}'", cnt, st, basis, pv, obs["lower_bound"], obs_ok,
                       "sfx_count_range", unmeasured_sev)
    # total of the counted classes: per-video totals from the same per-video counts (same classes)
    n_all = sum(len(by_type.get(t, [])) for t in counted_types if types[t].get("class") == COUNTED_SFX_CLASS)
    n_all += len(silences) if has_silence_type else 0
    tot_st, tot_basis, per_video_tot = None, "none", None
    if obs_ok:
        from ..util.stats import pstats_by_group

        allc = obs["all_types"]
        rows = [{"format_id": obs["formats"].get(v), "count": sum(allc.get(t, {}).get(v, 0) for t in counted_types)}
                for v in obs["all_videos"]]
        tot_st, tot_basis = sfxmap.count_range(pstats_by_group(rows, "count"), fid)
        vset = obs["videos"] if tot_basis.startswith("by_format") else obs["all_videos"]
        per_video_tot = {v: sum(allc.get(t, {}).get(v, 0) for t in counted_types) for v in vset}
        tot_basis = f"{tot_basis}, 영상별 개수에서 계산({'+'.join(sorted(counted))})"
    elif cat.get("per_video_total"):
        tot_st, tot_basis = sfxmap.count_range(cat.get("per_video_total"), fid)
    _count_verdict(out, "효과음 총", n_all, tot_st, tot_basis, per_video_tot, obs["lower_bound"], obs_ok,
                   "sfx_total_range", "error" if strict else "warn")


# ----------------------------------------------------------------------------- audio
KEPT_SPEECH_MIN_SHARE = 0.5      # rule: kept original sound is mostly speech (the user keeps important lines only)


def vocals_quality(s: dict, vocals_path: str) -> dict:
    """The automatic quality record of a separated vocals stem (``reference.separation.separate_vocals_for_source``
    writes quality.json next to vocals.wav): {ok, problems[], record}.  It must belong to THIS source (sha256) and
    this stem file, and ``quality.passed`` / ``usable`` must be true.  No listening is implied."""
    q = paths.absp(vocals_path).parent / "quality.json"
    rec = read_json(q)
    probs = []
    if not rec:
        return {"ok": False, "missing": True, "problems": [f"품질 기록 없음({paths.relp(q) if q.parent.is_dir() else q.name})"],
                "record": None}
    if rec.get("source_sha256") and s.get("sha256") and rec["source_sha256"] != s["sha256"]:
        probs.append(f"다른 소스(sha256 {str(rec['source_sha256'])[:12]}…)에서 분리한 기록")
    if rec.get("vocals") and rec["vocals"] != vocals_path:
        probs.append(f"기록의 목소리 파일 {rec['vocals']} ≠ plan vocals_path {vocals_path}")
    if rec.get("status") != "measured":
        probs.append(f"분리/검사 못 함({rec.get('blocker')})")
    q_ = rec.get("quality") or {}
    if q_.get("passed") is not True or rec.get("usable") is not True:
        probs.append("자동 품질 검사 불합격: " + ("; ".join(q_.get("fail_reasons") or []) or f"passed={q_.get('passed')}"))
    return {"ok": not probs, "missing": False, "problems": probs, "record": paths.relp(q)}


def check_audio(plan: dict, ctx: ResolveContext, out: list[dict], allow_unmeasured: bool) -> None:
    """Original sound, embedded music, vocals quality, BGM source (S4-01..S4-04).  Measurements are automatic
    (``audio_checks``); nothing here is a listening check."""
    from .audio_checks import music_presence, overlap, reference_stem_match, speech_spans

    prod = plan["mode"] == "production"
    sev = "error" if prod else "warn"
    pr = ctx.preset
    remove_music = pr.get("audio.original.remove_embedded_music") is True
    srcs = {s["id"]: s for s in plan["sources"]}
    for seg in plan["timeline"]:
        oa = seg.get("original_audio") or {}
        where = f"timeline[{seg['id']}].original_audio"
        if not oa.get("keep"):
            if oa.get("ranges"):
                out.append(issue("warn", "original_ranges_ignored", "keep=false 인데 ranges 가 있습니다(원음은 꺼짐)", where))
            continue
        if not (oa.get("reason") or "").strip():
            out.append(issue("error", "original_keep_reason", "원음을 살리려면 이유(중요 대사/말하는 사람)가 필요합니다", where))
        stem = oa.get("stem") or "raw"
        s = srcs.get(seg["source"], {})
        hem = s.get("has_embedded_music")
        ranges = [(float(a), float(b)) for a, b in (oa.get("ranges") or [[seg["src_in"], seg["src_out"]]])]
        music = None
        if s.get("path") and paths.absp(s["path"]).is_file():
            music = music_presence(s["path"], ranges)          # measured on the RAW source audio
        mtxt = (f"자동 음악 검사: {music['status']}, 동시 지속 부분음 비율 {music.get('polyphonic_share')}"
                + (f" ({music['reason']})" if music and music.get("reason") else "")) if music else "자동 음악 검사 못 함"
        if hem is None:
            # whoever keeps original sound must have checked the source for embedded music (true/false)
            out.append(issue("error" if prod else "warn", "embedded_music_unknown",
                             f"원음을 살리는 소스 {seg['source']} 에 음악이 섞였는지 기록되지 않았습니다"
                             f"(sources[].has_embedded_music = true/false 필요, 지금은 못 잼; {mtxt})", where))
        elif hem is False and music and music["status"] == "present":
            out.append(issue(sev, "embedded_music_detected",
                             f"has_embedded_music=false 인데 살린 원본 구간 {ranges} 에서 음악으로 보이는 지속 화음이 잡힙니다({mtxt}): "
                             "음악을 분리하고(vocals stem) 품질을 검사하거나 기록을 고치기", where))
        elif hem is False and stem == "raw" and (music is None or music["status"] == "unmeasured"):
            out.append(issue(sev, "embedded_music_unverified",
                             f"has_embedded_music=false 를 자동 검사로 확인하지 못함({mtxt}): 음악이 섞였는지 못 잼 — 분리(vocals stem + "
                             "품질 기록)로 확인", where))
        if remove_music and stem == "raw" and (hem is True or (music and music["status"] == "present")):
            out.append(issue("error", "embedded_music_raw",
                             "소스에 음악이 섞여 있는데 원음(raw)을 그대로 씁니다: 분리한 vocals stem 을 쓰세요", where))
        # the kept audio must be speech (S4-02)
        kept_path = s.get("vocals_path") if stem == "vocals" else s.get("path")
        if kept_path and paths.absp(kept_path).is_file():
            if stem == "raw" and music and music["status"] == "present":
                out.append(issue(sev, "kept_speech_unmeasured",
                                 "음악이 섞인 원음에서는 말소리를 자동으로 잴 수 없습니다(분리한 vocals stem 필요)", where))
            else:
                sp = speech_spans(kept_path)
                total = sum(b - a for a, b in ranges)
                if sp["status"] != "measured":
                    out.append(issue(sev, "kept_speech_unmeasured", f"살린 원음의 말소리를 자동으로 재지 못함(못 잼): {sp['reason']}",
                                     where))
                elif total > 0:
                    share = sum(overlap(a, b, sp["spans"]) for a, b in ranges) / total
                    if share < KEPT_SPEECH_MIN_SHARE:
                        out.append(issue(sev, "kept_no_speech",
                                         f"살린 원음 {ranges} 중 말소리는 {share:.0%} 뿐입니다(< {KEPT_SPEECH_MIN_SHARE:.0%}, 자동 음성 검사): "
                                         "중요한 대사·말하는 구간만 살린다(BGM 덕킹도 말소리 구간에만 걸림)", where))
        if stem == "vocals":
            vp = s.get("vocals_path")
            if vp and paths.absp(vp).is_file():
                vq = vocals_quality(s, vp)
                if not vq["ok"]:
                    out.append(issue(sev, "vocals_quality_missing" if vq["missing"] else "vocals_quality_failed",
                                     "분리한 목소리(vocals stem)의 자동 품질 검사: " + "; ".join(vq["problems"])
                                     + " → `shortkit` 분리 단계(separate_vocals_for_source)의 quality.json 이 합격이어야 씀", where))
            out.append(issue("warn", "vocals_listening_needed",
                             "분리한 목소리의 음질은 사람이 들어서 확인해야 합니다(에이전트는 듣지 못함 — 청취 검수 완료 아님)", where))
    b = ctx.resolved.audio.bgm
    if b is not None and b.path:
        bp = b.path.replace("\\", "/")
        if bp.startswith("presets/") and ("/analysis/" in bp or "/reference/" in bp) or "/stems/" in bp:
            out.append(issue("error", "bgm_from_reference",
                             f"BGM 은 깨끗한 음악 파일이어야 합니다(레퍼런스에서 분리한 stem 금지): {b.path}", "bgm.path"))
        else:
            # one rule with the music library and QA (reference.audio_bgm.reference_audio_copy)
            m = reference_stem_match(b.path)
            if m:
                out.append(issue("error", "bgm_from_reference",
                                 f"BGM 파일 {b.path}: {m.get('reason') or m['stem']} (방법 {m.get('method')}, "
                                 f"대상 {m['stem']}): 깨끗한 음악 파일만 쓴다", "bgm.path"))
    if b is not None:
        # the preset's BGM identity (title AND version); the library entry / plan file is compared
        # against it in ``audio.check_bgm_identity`` (resolve)
        title, version = pr.get("audio.bgm.title"), pr.get("audio.bgm.version")
        if not title or not version:
            sev2 = ("warn" if allow_unmeasured else "error") if prod else "warn"
            out.append(issue(sev2, "bgm_identity_unmeasured",
                             f"프리셋 BGM 제목·버전 미식별(못 잼: title={title!r}, version={version!r}): 쓰는 음악 파일이 "
                             "레퍼런스 곡·버전과 같은지 판정 불가", "audio.bgm"))


# ----------------------------------------------------------------------------- channel presence (있다/없다/못 잼)
PRESENCE_KEYS = ("zoom", "freeze", "speed_change", "flash", "crossfade", "decorations", "bgm", "original_audio",
                 "ducking", "intentional_silence")
PRESENCE_KO = {"zoom": "확대", "freeze": "정지", "speed_change": "속도 변화", "flash": "플래시 전환", "crossfade": "디졸브 전환",
               "decorations": "장식", "bgm": "BGM", "original_audio": "원음 살림", "ducking": "덕킹", "intentional_silence": "의도적 정적"}


def _presence_value(v) -> str:
    if v is True or str(v).strip().casefold() in ("present", "있다"):
        return "present"
    if v is False or str(v).strip().casefold() in ("absent", "없다"):
        return "absent"
    return "unmeasured"


def plan_effect_use(plan: dict, r) -> dict[str, bool]:
    tl = plan["timeline"]
    bgm = r.audio.bgm
    return {"zoom": any(seg.get("zoom") for seg in tl),
            "freeze": any(seg.get("freeze") for seg in tl),
            "speed_change": any(abs(float(seg.get("speed") or 1.0) - 1.0) > 1e-9 for seg in tl),
            "flash": any(c.transition_in.type == "flash" for c in r.clips),
            "crossfade": any(c.transition_in.type == "crossfade" for c in r.clips),
            "decorations": bool(plan.get("decorations")),
            "bgm": bgm is not None,
            "original_audio": any((seg.get("original_audio") or {}).get("keep") for seg in tl),
            "ducking": bool(bgm is not None and bgm.duck_ranges),
            "intentional_silence": bool(bgm is not None and bgm.silences)}


def check_presence(plan: dict, ctx: ResolveContext, out: list[dict]) -> None:
    """Channel-level presence of each effect (preset ``presence.*``: present / absent / unmeasured, measured from
    the reference).  An effect the reference never uses (absent) that the plan uses: error in production,
    warning in test.  An effect the reference uses (present) that the plan never uses: warning.  Unmeasured:
    warning (the plan's choice cannot be compared)."""
    prod = plan["mode"] == "production"
    uses = plan_effect_use(plan, ctx.resolved)
    unmeasured = []
    for k in PRESENCE_KEYS:
        try:
            v = _presence_value(ctx.preset.get(f"presence.{k}"))
        except KeyError:
            v = "unmeasured"
        if v == "absent" and uses[k]:
            out.append(issue("error" if prod else "warn", "presence_absent_used",
                             f"레퍼런스는 {PRESENCE_KO[k]}을(를) 쓰지 않는데(presence.{k}=absent) 이 plan 은 씁니다", f"presence.{k}"))
        elif v == "present" and not uses[k]:
            out.append(issue("warn", "presence_present_unused",
                             f"레퍼런스는 {PRESENCE_KO[k]}을(를) 쓰는데(presence.{k}=present) 이 plan 은 쓰지 않습니다", f"presence.{k}"))
        elif v == "unmeasured":
            unmeasured.append(f"{k}({'씀' if uses[k] else '안 씀'})")
    if unmeasured:
        out.append(issue("warn", "presence_unmeasured",
                         f"레퍼런스의 효과 사용 여부 못 잼: {', '.join(unmeasured)} — 이 plan 의 선택을 레퍼런스와 비교할 수 없음",
                         "presence"))


# ----------------------------------------------------------------------------- cover
def _ws(s: str) -> str:
    return " ".join(str(s).split())


def caption_at_rest(c, t: float) -> bool:
    """Caption fully shown at output time t: after its motion_in, before its motion_out."""
    mi, mo = c.motion_in or {}, c.motion_out or {}
    d_in = float(mi.get("dur_s") or 0.0) if mi.get("type") not in (None, "none") else 0.0
    d_out = float(mo.get("dur_s") or 0.0) if mo.get("type") not in (None, "none") else 0.0
    return c.start + d_in - EPS <= t < c.end - d_out - 1e-9


def check_cover(plan: dict, ctx: ResolveContext, out: list[dict]) -> None:
    """plan.cover.text is the 표지 문구 and must be the text actually visible on the cover frame
    (cover.frame_t, default 0.0): some caption at rest at frame_t shows exactly that text (line
    breaks / repeated spaces aside).  Error in production, warning in test mode."""
    prod = plan["mode"] == "production"
    sev = "error" if prod else "warn"
    cov = plan.get("cover") or {}
    text = _ws(cov.get("text") or "")
    r = ctx.resolved
    t = float(cov["frame_t"]) if cov.get("frame_t") is not None else 0.0
    src_mode = ctx.preset.get("cover.source")
    role = ctx.preset.get("cover.text_role")
    if src_mode == "first_frame" and abs(t) > EPS:
        out.append(issue(sev, "cover_frame_not_first", f"프리셋 cover.source=first_frame 인데 cover.frame_t={t}s 입니다",
                         "cover.frame_t"))
    if not text:
        return                       # empty cover text: proposal_incomplete (first episode) reports it
    if not (0.0 <= t < r.duration):
        out.append(issue(sev, "cover_frame_t", f"cover.frame_t={t}s 가 영상 길이 0..{r.duration:.2f}s 밖입니다",
                         "cover.frame_t"))
        return
    plan_text = {c["id"]: c["text"] for c in plan.get("captions", [])}
    shown = [c for c in r.captions if caption_at_rest(c, t)]
    match = [c for c in shown if text in (_ws(c.text.replace("\n", " ")), _ws(plan_text.get(c.id, "")))]
    if not match:
        vis = " / ".join(f"{c.id}({c.role}): {_ws(c.text.replace(chr(10), ' '))}" for c in shown) or "없음"
        out.append(issue(sev, "cover_text_not_visible",
                         f"표지 문구 '{text}' 가 표지 프레임 {t:.2f}s 에 보이는 자막에 없습니다(보이는 자막: {vis}). "
                         "표지 문구는 표지 프레임에 실제로 보이는 글자여야 합니다", "cover.text"))
    elif role and all(c.role != role for c in match):
        out.append(issue("warn", "cover_text_role",
                         f"표지 문구가 {match[0].role} 자막으로 보입니다(프리셋 cover.text_role={role})", "cover.text"))


# ----------------------------------------------------------------------------- approval / audit
def distinct_titles(cands) -> list[str]:
    """Title candidates that really differ: whitespace collapsed, case folded, empty dropped (S3-11)."""
    seen, out = set(), []
    for t in cands or []:
        k = " ".join(str(t).split()).casefold()
        if k and k not in seen:
            seen.add(k)
            out.append(str(t))
    return out


def check_approval(plan: dict, preset: config.Preset, out: list[dict], for_render: bool) -> None:
    """The approval gate (``plan.approval_state_for``): episode 1 (or no episode_index) follows
    approval.first_episode_requires_approval, episode_index > 1 follows
    approval.later_episodes_require_approval.  Test mode never needs approval.

    An approval counts only with its evidence (approved plan sha256 + approve event in approval_log.jsonl +
    stored snapshot of the approved proposal/plan, ``plan.approval_evidence``); a later production episode
    needs the approved and rendered first production episode of the same preset (``plan.series_first_episode``)."""
    try:
        st = approval_state_for(plan, preset)
    except PlanError as e:
        out.append(issue("error", "approval_rule", str(e), "approval"))
        return
    prod = plan["mode"] == "production"
    if prod and plan.get("episode_index") is None:
        out.append(issue("warn", "episode_index_missing",
                         "episode_index 가 없어 첫 에피소드로 취급합니다(승인 필요 여부를 정하려면 회차를 적으세요)",
                         "episode_index"))
    who = "첫 에피소드" if st["first_episode"] else f"{plan.get('episode_index')}번째 에피소드({st['rule_key']}=true)"
    if st["approval_claimed"] and not st["approved"]:
        out.append(issue("error" if (prod and st["required"]) else "warn", "approval_evidence_missing",
                         "approval 블록에 승인이 적혀 있지만 증거가 없습니다: " + "; ".join(st["evidence_problems"])
                         + f" → `shortkit episode proposal {plan['episode_id']}` 후 `... approve --by 이름` 으로만 승인",
                         "approval"))
    if st["required"] and not st["approved"]:
        out.append(issue("error" if for_render else "warn", "approval_required",
                         f"{who}: 제안서(proposal.md) 승인 전에는 렌더할 수 없습니다 "
                         f"(`shortkit episode proposal {plan['episode_id']}` → `... approve --by 이름`)", "approval"))
    if st["required"]:
        cov = ((plan.get("cover") or {}).get("text") or "").strip()
        raw = [t for t in plan.get("title_candidates") or [] if str(t).strip()]
        tcs = distinct_titles(raw)
        if not cov or len(tcs) < 3:
            out.append(issue("error", "proposal_incomplete",
                             f"{who} 제안서에는 표지 문구와 서로 다른 제목 후보 3종이 필요합니다(표지 {'있음' if cov else '없음'}, "
                             f"제목 후보 {len(raw)}개 중 서로 다른 것 {len(tcs)}개 — 공백·대소문자만 다른 것은 같은 후보)",
                             "cover/title_candidates"))
    if prod and not st["first_episode"]:
        ser = series_first_episode(plan)
        if not ser["ok"]:
            out.append(issue("error" if for_render else "warn", "series_first_episode",
                             f"{plan.get('episode_index')}번째 에피소드: 승인되고 렌더된 첫 편이 없습니다 — "
                             + "; ".join(ser["problems"]) + " (첫 편 승인 관문을 건너뛸 수 없음)", "episode_index"))
    if st["changed_since_approval"]:
        snap = approved_snapshot_plan(plan)
        diff = plan_diff_sections(snap, plan) if snap is not None else []
        txt = ", ".join(f"{d['ko']}" + (f"({d['detail']})" if d["detail"] else "") for d in diff) or "알 수 없음(사본 없음)"
        out.append(issue("warn", "approval_plan_changed",
                         f"승인({str(st['approved_plan_sha256'])[:12]}…) 뒤 plan 이 수정됨 — 바뀐 부분: {txt}. 재승인은 요구하지 "
                         "않지만 승인자가 보지 못한 내용이므로 렌더 기록에 남김", "approval"))


def check_audit(plan: dict, preset: config.Preset, out: list[dict], allow_unmeasured: bool) -> None:
    prod = plan["mode"] == "production"
    res = config.audit(preset.name, production=prod)
    n_un = len(res["unmeasured"])
    if prod:
        if n_un:
            out.append(issue("warn" if allow_unmeasured else "error", "preset_unmeasured",
                             f"프리셋 미측정(못 잼) 스타일 키 {n_un}개: production 렌더 불가"
                             + (" (--allow-unmeasured 로 경고 처리됨)" if allow_unmeasured else ""), "preset"))
        if res["no_code"] or res["no_qa"]:
            out.append(issue("error", "registry_unlinked",
                             f"코드에 연결 안 된 설정 {len(res['no_code'])}개, 출력 검사 없는 설정 {len(res['no_qa'])}개 "
                             "(`shortkit preset audit`)", "preset"))
    elif n_un:
        out.append(issue("warn", "preset_unmeasured", f"테스트 모드: 프리셋 미측정(못 잼) 키 {n_un}개로 렌더합니다(레퍼런스 일치 아님)",
                         "preset"))


# ----------------------------------------------------------------------------- entry
def validate(plan: dict, preset: config.Preset | None = None, *, preset_name: str | None = None,
             for_render: bool = False, allow_unmeasured: bool = False,
             return_context: bool = False, execute_clean: bool = False):
    """Run every rule.  Returns issues (and the ResolveContext when ``return_context``)."""
    out: list[dict] = []
    errs = schema_errors(plan)
    if errs:
        out += [issue("error", "schema", e, "plan.yaml") for e in errs]
        return (out, None) if return_context else out
    if preset is None:
        from .resolve import preset_for_plan

        try:
            preset = preset_for_plan(plan, preset_name)
        except (KeyError, FileNotFoundError, config.PresetMixError) as e:
            out.append(issue("error", "preset_unknown", f"프리셋을 불러오지 못함: {e}", "preset_id"))
            return (out, None) if return_context else out
    if not check_preset_mixing(plan, preset, out):
        return (out, None) if return_context else out
    ctx = resolve_context(plan, preset, execute_clean=execute_clean)
    out += ctx.issues
    check_paths(plan, out)
    check_format(plan, preset, out)
    check_intro_type(plan, preset, out, allow_unmeasured)
    check_sources(plan, ctx, out)
    check_clean_coverage(plan, ctx, out)
    check_crop_faces(plan, ctx, out)
    check_motion(plan, preset, out)
    check_style_overrides(plan, preset, out)
    check_structure(plan, ctx, out)
    check_protected_framing(plan, ctx, out)
    check_captions(plan, ctx, out)
    check_grounding(plan, ctx, out)
    check_watch_records(plan, out)
    check_reveal(plan, ctx, out, allow_unmeasured)
    check_tone(plan, preset, out)
    check_own_branding(plan, preset, out)
    check_trim_tail(plan, ctx, out)
    check_cuts(plan, ctx, out)
    check_repetition(plan, ctx, out)
    check_protected_declared(plan, out)
    check_korean(plan, out)
    check_cover(plan, ctx, out)
    check_sfx(plan, ctx, out, allow_unmeasured)
    check_audio(plan, ctx, out, allow_unmeasured)
    check_presence(plan, ctx, out)
    check_approval(plan, preset, out, for_render)
    check_audit(plan, preset, out, allow_unmeasured)
    seen, uniq = set(), []
    for i in out:
        k = (i["severity"], i["code"], i["where"], i["message_ko"])
        if k not in seen:
            seen.add(k)
            uniq.append(i)
    return (uniq, ctx) if return_context else uniq
