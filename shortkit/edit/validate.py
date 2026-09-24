"""Plan rule checks -> issues ``[{severity: error|warn, code, message_ko, where}]``.

Every rule below is enforced in code (not only documented).  ``error`` blocks resolve/render;
``warn`` is reported.  Unmeasured things are never passed silently: they produce at least a
warning (and an error in production unless ``allow_unmeasured``).
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from .. import config, paths
from ..util.hashing import sha256_file
from ..util.jsonio import read_jsonl, read_yaml
from . import sfxmap
from .plan import TEST_FORMAT_ID, approval_state, schema_errors
from .resolve import (EPS, ResolveContext, clips_at, issue, map_src_rect, rects_intersect, resolve_context,
                      src_time_at)

GROUNDING_FREE_ROLES = ("title", "description")
SFX_STACK_WINDOW_S = 0.5          # user rule: never stack the same effect repeatedly
CUT_WORDS = {"컷", "cut", "장면전환", "장면 전환", "scene change", "scenechange", "transition", "전환"}
NON_CUT_EVENT_KINDS = {"freeze", "zoom_in", "zoom_out", "text_pop", "flash", "action", "reaction", "speech",
                       "impact", "appear", "reveal", "emotion", "gesture"}


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


# ----------------------------------------------------------------------------- sources / provenance
def _norm_url(u: str | None) -> str | None:
    return u.strip().rstrip("/") if isinstance(u, str) and u.strip() else None


def warehouse_records() -> dict[str, dict]:
    recs: dict[str, dict] = {}
    for r in read_jsonl(paths.absp("warehouse/candidates.jsonl")):
        if r.get("id"):
            recs[r["id"]] = {**recs.get(r["id"], {}), **r}
    return recs


def excluded_urls() -> dict[str, str]:
    urls: dict[str, str] = {}
    for e in read_jsonl(paths.absp("warehouse/exclusions.jsonl")):
        if e.get("kind") == "url" and _norm_url(e.get("url")):
            urls[_norm_url(e["url"])] = e.get("reason") or "exclusions.jsonl(url)"
        elif e.get("kind") == "reference_footage":
            for u in [e.get("ref_url")] + list(e.get("original_urls") or []):
                if _norm_url(u):
                    urls[_norm_url(u)] = f"레퍼런스 영상 {e.get('ref_video_id')} 의 원본/주소"
    return urls


def check_sources(plan: dict, ctx: ResolveContext, out: list[dict]) -> None:
    prod = plan["mode"] == "production"
    recs = warehouse_records()
    excl = excluded_urls()
    for s in plan["sources"]:
        where = f"sources[{s['id']}]"
        si = ctx.sources.get(s["id"])
        if si and si.exists:
            if not s.get("sha256"):
                out.append(issue("error" if prod else "warn", "source_sha_missing", "sources[].sha256 이 비어 있습니다", where))
            elif sha256_file(si.abs) != s["sha256"]:
                out.append(issue("error", "source_sha_mismatch", f"sha256 불일치: {s['path']} 파일이 기록과 다릅니다", where))
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
        if (rec.get("reference_overlap") or {}).get("excluded") is True:
            ro = rec["reference_overlap"]
            out.append(issue("error", "source_excluded_reference",
                             f"레퍼런스와 같은 원본으로 판정된 소재입니다(matched={ro.get('matched_video_id')}, "
                             f"method={ro.get('method')})", where))
        if rec.get("status") in ("excluded", "rejected"):
            out.append(issue("error", "source_excluded_status", f"창고 레코드 상태가 {rec.get('status')} 입니다", where))
        for u in (rec.get("url"), rec.get("original_url")):
            if _norm_url(u) in excl:
                out.append(issue("error", "source_excluded_url", f"제외 목록 URL 과 일치: {u} ({excl[_norm_url(u)]})", where))
        if rec.get("sha256") and s.get("sha256") and rec["sha256"] != s["sha256"]:
            out.append(issue("error", "provenance_sha_mismatch", "창고 레코드 sha256 과 plan sha256 이 다릅니다", where))


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
    prev_flash = False
    for seg in plan["timeline"]:
        fl = (seg.get("transition_in") or {}).get("type") == "flash"
        if fl and prev_flash:
            out.append(issue("warn", "transition_stacked", "플래시 전환이 연속 세그먼트에 반복됩니다(같은 효과 연속 쌓기)",
                             f"timeline[{seg['id']}]"))
        prev_flash = fl
    segs = plan["timeline"]
    for i, a in enumerate(segs):
        for b in segs[i + 1:]:
            if a["source"] == b["source"]:
                ov = min(a["src_out"], b["src_out"]) - max(a["src_in"], b["src_in"])
                if ov > 0.05:
                    out.append(issue("warn", "segment_repeat",
                                     f"같은 원본 구간이 두 번 쓰입니다({a['id']}·{b['id']}, {ov:.2f}s): 길이를 채우려는 반복은 금지 "
                                     "(의도한 다시보기라면 purpose 에 적기)", f"timeline[{b['id']}]"))
    slow = float(preset.get("motion.speed.slowmo_factor"))
    for seg in plan["timeline"]:
        sp = float(seg.get("speed") or 1.0)
        if sp < 1.0 and abs(sp - slow) > 1e-6:
            out.append(issue("warn", "speed_not_preset", f"느린 재생 {sp} 가 프리셋 slowmo_factor {slow} 와 다릅니다",
                             f"timeline[{seg['id']}]"))


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


def check_structure(plan: dict, ctx: ResolveContext, out: list[dict]) -> None:
    pr, r = ctx.preset, ctx.resolved
    ds = pr.get("structure.duration_s")
    n = int(ds.get("n") or 0)
    if r.duration <= 0:
        out.append(issue("error", "duration_zero", "타임라인 길이가 0 입니다", "timeline"))
    elif n == 0 or ds.get("p10") is None:
        out.append(issue("warn", "duration_unmeasured", f"영상 길이 분포 미측정(못 잼): {r.duration:.2f}s 의 적합성 판정 불가",
                         "structure.duration_s"))
    elif not (float(ds["p10"]) <= r.duration <= float(ds["p90"])):
        out.append(issue("warn", "duration_range", f"길이 {r.duration:.2f}s 가 관측 범위 p10..p90 "
                         f"({ds['p10']}..{ds['p90']}) 밖", "timeline"))
    fc = float(pr.get("structure.first_caption_at_s"))
    if r.captions:
        first = min(c.start for c in r.captions)
        if abs(first - fc) > 0.25:
            out.append(issue("warn", "first_caption_timing", f"첫 자막 {first:.2f}s ≠ 프리셋 {fc:.2f}s", "captions"))


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
    # grounding
    for c in plan.get("captions", []):
        where = f"captions[{c['id']}]"
        g = c.get("grounding")
        if c["role"] not in GROUNDING_FREE_ROLES and not g:
            out.append(issue("error" if prod else "warn", "caption_grounding",
                             f"{c['role']} 자막에 근거(grounding)가 없습니다: 본 것/들은 것만 쓴다", where))
        if c["role"] == "dialogue" and (not g or g.get("kind") != "heard"):
            out.append(issue("error" if prod else "warn", "dialogue_not_heard",
                             "dialogue 는 실제로 들린 대사여야 합니다(grounding.kind=heard)", where))
        if g and g.get("source") and g["source"] not in src_ids:
            out.append(issue("error", "grounding_source", f"grounding.source '{g['source']}' 가 sources 에 없습니다", where))
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
    # decorations vs protected (warn: pointing AT something is allowed, covering it is not)
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
                    if m and rects_intersect(drect, m) and (clip.source_id, k) not in reported:
                        reported.add((clip.source_id, k))
                        out.append(issue("warn", "decoration_covers_protected",
                                         f"장식 {d.id} 이 보호 영역 '{p['label']}' 과 겹칩니다(출력 {t:.2f}s)",
                                         f"decorations[{d.id}]"))
    # reveal guard
    rv = plan.get("reveal") or {}
    if rv.get("keywords"):
        rt = float(rv.get("t") or 0.0)
        for c in r.captions:
            if c.start < rt - EPS:
                for kw in rv["keywords"]:
                    if kw and kw in c.text.replace("\n", " "):
                        out.append(issue("error", "reveal_leak",
                                         f"반전({rt:.2f}s) 전에 시작하는 자막 {c.id} 에 '{kw}' 가 있습니다(반전 미리 설명 금지)",
                                         f"captions[{c.id}]"))
        for kw in rv["keywords"]:
            if kw and kw in ((plan.get("cover") or {}).get("text") or ""):
                out.append(issue("warn", "reveal_in_cover", f"표지 문구에 반전 키워드 '{kw}' 가 있습니다", "cover.text"))
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


def _kf_at(d, t: float) -> dict:
    from .captions import _interp_kf

    kfs = d.keyframes
    if t <= kfs[0]["t"]:
        return kfs[0]
    for a, b in zip(kfs, kfs[1:]):
        if t <= b["t"]:
            return _interp_kf(a, b, t)
    return kfs[-1]


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
        if kind not in NON_CUT_EVENT_KINDS and any(abs(float(ev["t"]) - b) < 0.05 for b in boundaries):
            out.append(issue("warn", "sfx_event_at_cut",
                             f"사건 시각 {ev['t']}s 가 컷 경계와 같습니다: 컷이 아니라 화면 속 사건인지 확인(kind 로 명시)", where))
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
    for typ, lst in by_type.items():
        ts = sorted(float(s["t"]) for s in lst)
        for a, b in zip(ts, ts[1:]):
            if b - a < SFX_STACK_WINDOW_S - 1e-9:
                out.append(issue("error", "sfx_stacking", f"같은 효과음 '{typ}' 이 {b - a:.2f}s 간격으로 겹쳐 쌓였습니다"
                                 f"(<{SFX_STACK_WINDOW_S}s)", f"sfx[{typ}@{b:.2f}]"))
    # observed ranges from the catalog
    cat = sfxmap.load_catalog(pr)
    fid = None if plan["format_id"] == TEST_FORMAT_ID else plan["format_id"]
    if cat.get("status") != "measured":
        sev = "error" if (prod and not allow_unmeasured) else "warn"
        out.append(issue(sev, "sfx_range_unmeasured",
                         f"효과음 카탈로그 미측정(못 잼): 종류별 개수·분포가 포맷 관측 범위 안인지 판정 불가 "
                         f"({cat.get('blocker') or cat.get('_path')})", "sfx"))
    else:
        types = {t.get("type_id"): t for t in cat.get("types") or []}
        for typ in by_type:
            if typ not in types:
                out.append(issue("error", "sfx_type_unknown", f"카탈로그에 없는 효과음 종류 '{typ}'", "sfx"))
        for typ, ent in types.items():
            if ent.get("class") == "intentional_silence":
                continue
            st, basis = sfxmap.count_range(ent.get("per_video_count"), fid)
            cnt = len(by_type.get(typ, []))
            if st is None:
                out.append(issue("warn", "sfx_count_unmeasured", f"'{typ}' 영상당 개수 분포 미측정(못 잼)", "sfx"))
            elif not (float(st["p10"]) <= cnt <= float(st["p90"])):
                out.append(issue("error", "sfx_count_range", f"'{typ}' {cnt}개가 관측 범위 {st['p10']}..{st['p90']} "
                                 f"({basis}) 밖", "sfx"))
        tot = cat.get("per_video_total")
        st, basis = sfxmap.count_range(tot, fid)
        n_all = len(plan.get("sfx") or [])
        if st is None:
            out.append(issue("error" if (prod and not allow_unmeasured) else "warn", "sfx_total_unmeasured",
                             "영상당 효과음 총개수 분포 미측정(못 잼)", "sfx"))
        elif not (float(st["p10"]) <= n_all <= float(st["p90"])):
            out.append(issue("error", "sfx_total_range", f"효과음 총 {n_all}개가 관측 범위 {st['p10']}..{st['p90']} ({basis}) 밖",
                             "sfx"))
    for sp in r.audio.sfx:
        if prod and sp.path and sp.map_status != "have":
            out.append(issue("warn", "sfx_explicit_unmapped",
                             f"'{sp.type}' 는 명시 파일을 쓰지만 레퍼런스 종류와의 유사도는 미측정(맵 상태 {sp.map_status})",
                             f"sfx[{sp.id}]"))


# ----------------------------------------------------------------------------- audio
def check_audio(plan: dict, ctx: ResolveContext, out: list[dict], allow_unmeasured: bool) -> None:
    prod = plan["mode"] == "production"
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
        hem = srcs.get(seg["source"], {}).get("has_embedded_music")
        if remove_music and stem == "raw":
            if hem is True:
                out.append(issue("error", "embedded_music_raw",
                                 "소스에 음악이 섞여 있는데 원음(raw)을 그대로 씁니다: 분리한 vocals stem 을 쓰세요", where))
            elif hem is None:
                out.append(issue("error" if prod else "warn", "embedded_music_unknown",
                                 "소스에 음악이 섞였는지 확인하지 않았습니다(has_embedded_music 못 잼)", where))
        if stem == "vocals":
            out.append(issue("warn", "vocals_quality_unchecked",
                             "분리한 목소리(vocals) 품질은 사람이 들어서 확인해야 합니다(자동 확인 안 함, 못 잼)", where))
    b = ctx.resolved.audio.bgm
    if b is not None and b.path:
        bp = b.path.replace("\\", "/")
        if bp.startswith("presets/") and ("/analysis/" in bp or "/reference/" in bp) or "/stems/" in bp:
            out.append(issue("error", "bgm_from_reference",
                             f"BGM 은 깨끗한 음악 파일이어야 합니다(레퍼런스에서 분리한 stem 금지): {b.path}", "bgm.path"))
    if prod and b is not None and not (plan.get("bgm") or {}).get("path"):
        title, version = pr.get("audio.bgm.title"), pr.get("audio.bgm.version")
        if not title or not version:
            out.append(issue("warn" if allow_unmeasured else "error", "bgm_identity_unmeasured",
                             "BGM 제목·버전 미식별(못 잼): 곡 일치 판정 불가", "audio.bgm"))


# ----------------------------------------------------------------------------- approval / audit
def check_approval(plan: dict, preset: config.Preset, out: list[dict], for_render: bool) -> None:
    st = approval_state(plan, bool(preset.get("approval.first_episode_requires_approval")))
    if st["required"] and not st["approved"]:
        out.append(issue("error" if for_render else "warn", "approval_required",
                         "첫 에피소드: 제안서(proposal.md) 승인 전에는 렌더할 수 없습니다 "
                         f"(`shortkit episode proposal {plan['episode_id']}` → `... approve --by 이름`)", "approval"))
    if st["required"]:
        cov = ((plan.get("cover") or {}).get("text") or "").strip()
        tcs = [t for t in plan.get("title_candidates") or [] if str(t).strip()]
        if not cov or len(tcs) < 3:
            out.append(issue("error", "proposal_incomplete",
                             f"첫 에피소드 제안서에는 표지 문구와 제목 후보 3종이 필요합니다(표지 {'있음' if cov else '없음'}, "
                             f"제목 후보 {len(tcs)}개)", "cover/title_candidates"))
    if st["changed_since_approval"]:
        out.append(issue("warn", "approval_plan_changed",
                         "승인 뒤 plan 이 수정됨(재승인은 요구하지 않음, 변경 사실만 기록)", "approval"))


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
    check_sources(plan, ctx, out)
    check_motion(plan, preset, out)
    check_structure(plan, ctx, out)
    check_protected_framing(plan, ctx, out)
    check_captions(plan, ctx, out)
    check_sfx(plan, ctx, out, allow_unmeasured)
    check_audio(plan, ctx, out, allow_unmeasured)
    check_approval(plan, preset, out, for_render)
    check_audit(plan, preset, out, allow_unmeasured)
    seen, uniq = set(), []
    for i in out:
        k = (i["severity"], i["code"], i["where"], i["message_ko"])
        if k not in seen:
            seen.add(k)
            uniq.append(i)
    return (uniq, ctx) if return_context else uniq
