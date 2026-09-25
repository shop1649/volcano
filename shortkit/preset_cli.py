"""`shortkit preset ...` : registry sync, audit, applying measurements."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config, paths
from .util.jsonio import now_iso, read_json, read_yaml, write_yaml


def register(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("sync", help="settings_registry.yaml 재생성(측정 파일·접근 기록 보관함·QA 선언 반영)")
    s.add_argument("--preset", default="joshuamagazine")
    s.add_argument("--access-log", action="append", default=[],
                   help="episodes/<id>/build/preset_access.json (여러 번 지정 가능). 생략 시 모든 에피소드에서 수집. "
                        "모든 기록은 presets/<p>/access_logs/ (추적)로 복사되고 code 링크는 그 보관함에서만 만든다")
    s.set_defaults(func=cmd_sync)

    a = sub.add_parser("audit", help="보고서에만 있고 코드/검사에 연결되지 않은 설정, 미측정 설정 점검")
    a.add_argument("--preset", default="joshuamagazine")
    a.add_argument("--test", action="store_true", help="테스트 모드: 미측정 값은 경고로만 취급")
    a.set_defaults(func=cmd_audit)

    m = sub.add_parser("apply-measurements", help="measurements/*.json 의 측정값을 measured.yaml 로 반영(px 값은 유효 캔버스로 환산)")
    m.add_argument("--preset", default="joshuamagazine")
    m.set_defaults(func=cmd_apply)

    u = sub.add_parser("unresolved", help="미확정(못 잼) 항목·제작 영향·해결 상태 문서(unresolved.md) 생성")
    u.add_argument("--preset", default="joshuamagazine")
    u.set_defaults(func=cmd_unresolved)

    sh = sub.add_parser("show", help="유효 프리셋 값과 출처(measured/provisional/requested_change) 출력")
    sh.add_argument("--preset", default="joshuamagazine")
    sh.add_argument("--format", default=None)
    sh.add_argument("key", nargs="?", default=None)
    sh.set_defaults(func=cmd_show)


def _all_access_logs() -> list[str]:
    return [str(p) for p in config.all_access_logs()]


def cmd_sync(args) -> int:
    logs = args.access_log or _all_access_logs()
    reg = config.sync_registry(args.preset, access_logs=logs)
    ents = reg["entries"]
    by = {}
    for e in ents.values():
        by[e["status"]] = by.get(e["status"], 0) + 1
    print(f"registry: {len(ents)} keys  " + "  ".join(f"{k}={v}" for k, v in sorted(by.items())))
    print(f"access logs found now: {len(logs)}; archived logs used for code links: {len(reg['access_logs'])} "
          f"({reg['access_log_archive']})")
    stale = sorted(k for k, e in ents.items() if e.get("code_stale"))
    if stale:
        print(f"stale code links (function changed/removed since the log): {len(stale)} keys — 에피소드 명령을 다시 실행해 갱신")
    return 0


def cmd_audit(args) -> int:
    res = config.audit(args.preset, production=not args.test)
    for k in ("unmeasured", "no_code", "no_qa"):
        print(f"{k}: {len(res[k])}")
        for key in res[k][:200]:
            print(f"   - {key}")
    if res.get("stale_code"):
        print(f"no_code 중 오래된 링크만 있는 키(코드가 기록 뒤 바뀜/없어짐): {len(res['stale_code'])}")
    print(f"not_applicable_given: {len(res.get('not_applicable_given') or [])}")
    print("RESULT:", "OK" if res["ok"] else "BLOCKED")
    return 0 if res["ok"] else 1


# ----------------------------------------------------------------------------- apply-measurements
def _effective(preset: str, base: dict, common: dict, by_format: dict, requested: dict, fmt: str | None,
               by_fmt_un: dict | None = None) -> config.Preset:
    """The preset production would load from these layers (read through Preset.get)."""
    measured = {"common": common, "by_format": by_format, "by_format_unmeasured": by_fmt_un or {}}
    eff = config.merge_layers(base, measured, requested, fmt)
    return config.Preset(name=preset, data=eff, base=base, measured=measured, requested=requested, format_id=fmt)


def _px_source_resolution(it: dict) -> list[int] | None:
    """Resolution the stored px value refers to: ``scaled_to.resolution`` (emitters scale to it), else
    ``resolution``."""
    src = (it.get("scaled_to") or {}).get("resolution") or it.get("resolution")
    return [int(src[0]), int(src[1])] if src else None


def _plans_to_recheck(pr: config.Preset) -> list[dict]:
    """Episode plans of this preset whose coordinates are not declared in the effective canvas (S1-19)."""
    out = []
    for f in sorted(paths.project_root().glob("episodes/*/plan.yaml")):
        plan = read_yaml(f, {}) or {}
        if not isinstance(plan, dict) or plan.get("preset_id") != pr.preset_id:
            continue
        chk = config.plan_canvas_check(plan, pr)
        if chk["status"] != "ok":
            out.append({"plan": paths.relp(f), "status": chk["status"], "plan_resolution": chk["plan"],
                        "canvas": chk["preset"], "message_ko": chk["message_ko"]})
    return out


def apply_measurements(preset: str) -> dict:
    """measurements/*.json -> measured.yaml.

    - only items of THIS preset's fixed snapshot are used (``config.load_measurement_items`` guard: another
      preset's file raises, another snapshot's file is refused);
    - px items are rescaled from the resolution they are stored in (``scaled_to`` / ``resolution``) to the
      EFFECTIVE canvas (measured canvas.width/height when measured) -- a different aspect ratio is not applied;
    - a format whose by_format entry is explicitly unmeasured (value None) does NOT inherit the channel value
      (``by_format_unmeasured``)."""
    d = paths.preset_dir(preset)
    base = read_yaml(d / "preset.yaml")
    requested = read_yaml(d / "requested_changes.yaml", {}) or {}
    prev = read_yaml(d / "measured.yaml", {}) or {}
    old_canvas = _effective(preset, base, prev.get("common") or {}, prev.get("by_format") or {}, requested,
                            None).canvas_resolution()
    items = config.load_measurement_items(d)          # measured beats unmeasured; conflicts / other preset raise
    common: dict = {}
    by_format: dict = {}
    by_fmt_un: dict[str, list[str]] = {}
    applied, skipped, refused = [], [], []
    for key, it in sorted(items.items()):
        if it.get("refused"):
            refused.append({"key": key, "file": it.get("file"), "reason": it["refused"]["reason"]})
        if it.get("status") != "measured" or it.get("value") is None:
            skipped.append(key)
            continue
        _set(common, key, it["value"])
        applied.append(key)
        for fmt, st in (it.get("by_format") or {}).items():
            if not isinstance(st, dict):
                continue
            if st.get("value") is not None and st.get("status") != "unmeasured":
                _set(by_format.setdefault(fmt, {}), key, st["value"])
            elif "value" in st or st.get("status") == "unmeasured":
                by_fmt_un.setdefault(fmt, []).append(key)        # explicitly unmeasured here: no inheritance
    # ---- px coordinates: stored resolution -> effective canvas (per format when a format's canvas differs)
    canvas = _effective(preset, base, common, by_format, requested, None).canvas_resolution()
    fmts = sorted(set(by_format) | set(by_fmt_un))
    fcanvas = {f: _effective(preset, base, common, by_format, requested, f, by_fmt_un).canvas_resolution() for f in fmts}
    rescaled, not_applied = [], []
    for key in list(applied):
        it = items[key]
        if it.get("unit") != "px" or config.px_axis(key) is None:
            continue
        src = _px_source_resolution(it)
        raw = config.get_path(common, key)
        if not src:
            not_applied.append({"key": key, "reason": "px 값에 해상도(resolution/scaled_to) 없음 → 캔버스에 놓을 수 없음"})
        else:
            try:
                v = config.rescale_px(raw, key, src, canvas)
            except config.ResolutionMismatch as e:
                not_applied.append({"key": key, "reason": f"{e} → ref aggregate 를 다시 실행(측정 캔버스로 환산)"})
            else:
                _set(common, key, v)
                if src != canvas:
                    rescaled.append({"key": key, "from": src, "to": canvas, "value_stored": raw, "value": v})
                for f in fmts:
                    fv = config.get_path(by_format.get(f) or {}, key, None)
                    if key in by_fmt_un.get(f, []):
                        continue
                    if fv is None and fcanvas[f] == canvas:
                        continue                                  # inherits the (already rescaled) common value
                    try:
                        _set(by_format.setdefault(f, {}), key,
                             config.rescale_px(raw if fv is None else fv, key, src, fcanvas[f]))
                    except config.ResolutionMismatch as e:
                        by_fmt_un.setdefault(f, []).append(key)
                        not_applied.append({"key": key, "format": f, "reason": str(e)})
                continue
        _unset(common, key)
        for f in fmts:
            _unset(by_format.get(f) or {}, key)
        applied.remove(key)
        skipped.append(key)
    out = {"preset_id": base["preset_id"], "generated_at": now_iso(),
           "note": "generated by `shortkit preset apply-measurements`; do not edit by hand",
           "canvas_resolution": canvas,
           "coordinates": {"note": "모든 px 값은 canvas_resolution(포맷별은 canvas_by_format) 기준. 측정 파일의 해상도에서 환산함",
                           "canvas_by_format": {f: c for f, c in fcanvas.items() if c != canvas},
                           "rescaled": rescaled, "not_applied": not_applied},
           "refused_measurements": refused,
           "common": common, "by_format": by_format,
           "by_format_unmeasured": {f: sorted(set(v)) for f, v in sorted(by_fmt_un.items())}}
    write_yaml(d / "measured.yaml", out)
    new_pr = config.load_preset(preset)
    return {"applied": applied, "skipped_unmeasured": skipped, "refused": refused, "rescaled": rescaled,
            "not_applied": not_applied, "canvas": canvas, "canvas_before": old_canvas,
            "plans_to_recheck": _plans_to_recheck(new_pr)}


def _set(d: dict, dotted: str, value) -> None:
    parts = dotted.split(".")
    cur = d
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value


def _unset(d: dict, dotted: str) -> None:
    parts = dotted.split(".")
    chain = [d]
    for p in parts[:-1]:
        nxt = chain[-1].get(p) if isinstance(chain[-1], dict) else None
        if not isinstance(nxt, dict):
            return
        chain.append(nxt)
    chain[-1].pop(parts[-1], None)
    for p, parent in zip(reversed(parts[:-1]), reversed(chain[:-1])):   # drop emptied parents
        if isinstance(parent.get(p), dict) and not parent[p]:
            parent.pop(p)


def cmd_apply(args) -> int:
    r = apply_measurements(args.preset)
    print(f"applied {len(r['applied'])} measured keys; {len(r['skipped_unmeasured'])} still unmeasured")
    print(f"canvas {r['canvas'][0]}x{r['canvas'][1]} (before {r['canvas_before'][0]}x{r['canvas_before'][1]}); "
          f"px rescaled {len(r['rescaled'])}, not applied {len(r['not_applied'])}")
    for x in r["not_applied"]:
        print(f"   ! not applied: {x['key']}{' [' + x['format'] + ']' if x.get('format') else ''}: {x['reason']}")
    if r["refused"]:
        files = sorted({x["file"] for x in r["refused"]})
        print(f"refused measurement files (not this preset's fixed snapshot): {files}")
    if r["plans_to_recheck"]:
        print(f"plans whose coordinates are not in the canvas {r['canvas'][0]}x{r['canvas'][1]}: "
              + ", ".join(f"{p['plan']}({p['status']})" for p in r["plans_to_recheck"]))
    config.sync_registry(args.preset, access_logs=_all_access_logs())
    return 0


def cmd_show(args) -> int:
    pr = config.load_preset(args.preset, args.format)
    flat = config.flatten(pr.data)
    for k, v in flat.items():
        if args.key and not k.startswith(args.key):
            continue
        na = pr.not_applicable(k) if pr.origin(k) == "provisional" else None
        print(f"{k} = {v!r}   [{pr.origin(k)}{'; 해당 없음: ' + na['given'] if na else ''}]")
    return 0


# ----------------------------------------------------------------------------- unresolved.md
def _foreign(doc: dict, pr: config.Preset) -> str | None:
    pid = doc.get("preset_id") if isinstance(doc, dict) else None
    return pid if pid and pid != pr.preset_id else None


def _row(item, status, impact, state, evidence) -> dict:
    return {"item": item, "status": status, "impact": impact, "state": state, "evidence": evidence}


def _safe_stage(fn, preset: str, item: str) -> dict:
    try:
        return fn(preset)
    except Exception as e:     # a stage evaluator failure is reported, never hidden as 'measured'
        return _row(item, "unmeasured", "판정 실패 → 이 단계의 상태를 알 수 없음", "error", f"평가 실패: {type(e).__name__}: {e}")


def _stage_blockers(preset: str) -> list[dict]:
    """Stage-level blockers, each evaluated from the EFFECTIVE preset (all layers) and the stage's own files."""
    from .reference import high_views, trace_sources

    d = paths.preset_dir(preset)
    pr = config.load_preset(preset)
    ident = config.preset_identity(d)
    net = ident["snapshot_status"] not in ("ok", "partial")
    out: list[dict] = []
    # ---- fixed latest-N snapshot
    snap = read_json(paths.absp(pr.get("reference.snapshot_file")), {}) or {}
    n, want = len(snap.get("videos") or []), int(pr.get("reference.latest_n"))
    st = snap.get("status")
    out.append(_row(f"최신 {want}편 목록·게시일 고정", "measured" if st == "ok" and n >= want else "unmeasured",
                    "포맷 분류·모든 측정의 기준 표본이 없음 → 모든 스타일 값이 임시값",
                    "resolved" if st == "ok" and n >= want else ("blocked_network" if st in (None, "blocked") else "open"),
                    f"{pr.get('reference.snapshot_file')} status={st or '없음'} videos={n} blocker={snap.get('blocker')}"))
    # ---- high-view videos (reference-only report)
    out.append(_safe_stage(high_views.stage_status, preset, "조회수 80만 이상 영상 전체 분석"))
    # ---- formats
    fm = read_yaml(d / "formats.yaml", {}) or {}
    fo = _foreign(fm, pr)
    fst = "unmeasured" if fo else fm.get("status", "unmeasured")
    out.append(_row("포맷 분류표·포맷별 대표 영상", fst,
                    "포맷별 p10/p50/p90, 효과음 개수 범위, 대표 영상 비교(QA)를 쓸 수 없음 → 에피소드는 test 모드(UNCLASSIFIED)만 가능",
                    "resolved" if fst == "measured" else ("foreign_file" if fo else "blocked_network" if net else
                                                         "needs_manual_observation"),
                    f"formats.yaml status={fm.get('status')}" + (f" preset_id={fo}(다른 프리셋)" if fo else "")
                    + (f" blocker={fm.get('blocker')}" if fst != "measured" and fm.get("blocker") else "")))
    # ---- information-disclosure order (per format: beats / reveal_frac), labelled by people who watched
    out.append(_disclosure_stage(fm, fo, net))
    # ---- SFX catalog / map
    out.append(_sfx_catalog_stage(d, pr, net))
    sm = read_yaml(d / "sfx_map.yaml", {}) or {}
    types = sm.get("types") or {}
    have = sum(1 for t in types.values() if isinstance(t, dict) and t.get("status") == "have")
    sm_ok = sm.get("library_status") == "provided" and types and have == len(types)
    out.append(_row("효과음 창고 연결(sfx_map)", "measured" if sm_ok else "unmeasured",
                    "제작에 쓸 효과음 파일이 정해지지 않음 → production 렌더 불가",
                    "resolved" if sm_ok else "open_user_asset",
                    f"sfx_map.yaml library_status={sm.get('library_status')} have={have}/{len(types)}"))
    # ---- BGM (effective preset: measured layer included)
    out.append(_bgm_stage(pr, net))
    # ---- fonts
    out.append(_font_stage(pr, d, net))
    # ---- reverse trace
    out.append(_safe_stage(trace_sources.stage_status, preset, "레퍼런스 소재 출처·반복 계정·키워드 역추적"))
    # ---- the reference channel's own identity marks (templates the QA identity check matches)
    out.append(_safe_stage(lambda p: _identity_stage(p, pr, net), preset, IDENTITY_ITEM))
    return out


DISCLOSURE_ITEM = "레퍼런스 정보 공개 순서(포맷별 beats·reveal_frac)"


def _disclosure_stage(fm: dict, foreign: str | None, net: bool) -> dict:
    """formats.yaml ``disclosure_order`` {status, blocker} + each format's ``disclosure`` status."""
    do = (fm.get("disclosure_order") or {}) if not foreign else {}
    st = "unmeasured" if foreign else (do.get("status") or "unmeasured")
    per = [f"{r.get('format_id')}={(r.get('disclosure') or {}).get('status', 'unmeasured')}"
           for r in fm.get("table") or [] if isinstance(r, dict)]
    if st == "measured":
        state = "resolved"
    elif foreign:
        state = "foreign_file"
    elif net and not fm.get("table"):
        state = "blocked_network"
    else:
        state = "needs_manual_observation"         # beats / reveal_t come only from people who watched (format_labels.csv)
    impact = ("없음" if st == "measured" else
              "포맷별 정보 공개 순서(구간 목적 순서·반전 시각 비율)를 몰라 반전을 앞당겨 말하는지 레퍼런스 기준으로 판정 불가 "
              "(에피소드 reveal 가드는 계획의 reveal 로만 작동)")
    return _row(DISCLOSURE_ITEM, st, impact, state,
                f"formats.yaml disclosure_order status={do.get('status') if not foreign else '-'}"
                + (f" preset_id={foreign}(다른 프리셋)" if foreign else "")
                + (f"; 포맷별: {', '.join(per)}" if per else "; 포맷 없음")
                + (f"; blocker={do.get('blocker')}" if st != "measured" and do.get("blocker") else ""))


SFX_CATALOG_ITEM = "효과음 카탈로그(최신 50편 Demucs)"


def _sfx_catalog_stage(d: Path, pr: config.Preset, net: bool) -> dict:
    """sfx_catalog.json status incl. ``partial`` (every video analysed, but a required per-type column is not measured
    for every type: ``unmeasured_columns`` {column: [type_id]})."""
    from .reference.sfx_catalog import COLUMN_KO

    cat = read_json(d / "sfx_catalog.json", {}) or {}
    co = _foreign(cat, pr)
    cst = "unmeasured" if co else cat.get("status", "unmeasured")
    gaps = (cat.get("unmeasured_columns") or {}) if not co else {}
    gap_txt = "; ".join(f"{COLUMN_KO.get(c, c)}: 종류 {len(v)}개({', '.join(map(str, v[:6]))}{'…' if len(v) > 6 else ''})"
                        for c, v in gaps.items() if v)
    if cst == "measured":
        state, impact = "resolved", "없음"
    elif co:
        state, impact = "foreign_file", "효과음 종류·편당 개수·자리 규칙이 없음 → 효과음 개수/분포 검사는 못 잼"
    elif cst == "partial":
        state = "needs_manual_observation" if "emotion" in gaps else "insufficient_data"
        impact = (f"종류별 필수 열 일부 못 잼({', '.join(COLUMN_KO.get(c, c) for c in gaps)}) → 그 열로 정하는 자리 규칙·감정 "
                  "검사는 못 잼, 카탈로그는 production 기준으로 쓰이지 않음")
    else:
        state = "blocked_network" if net else "open"
        impact = "효과음 종류·편당 개수·자리 규칙이 없음 → 효과음 개수/분포 검사는 못 잼"
    ev = f"sfx_catalog.json status={cat.get('status')}"
    if cat.get("column_status"):
        ev += " column_status=" + ", ".join(f"{k}={v}" for k, v in cat["column_status"].items())
    if gap_txt:
        ev += f"; unmeasured_columns: {gap_txt}"
    if cat.get("counts_are_lower_bounds"):
        ev += "; 편당 개수는 하한값(대사 밑 효과음 못 잼)"
    if cst != "measured" and cat.get("blocker"):
        ev += f"; blocker={cat.get('blocker')}"
    if co:
        ev += f" preset_id={co}(다른 프리셋)"
    return _row(SFX_CATALOG_ITEM, cst, impact, state, ev)


IDENTITY_ITEM = "원 채널 식별 템플릿(로고·워터마크·핸들, QA identity.logo_templates)"


def _identity_stage(preset: str, pr: config.Preset, net: bool) -> dict:
    """``<identity_exclusions.logo_templates_dir>/manifest.json`` (``shortkit ref identity-templates``)."""
    from .reference.identity_templates import manifest_status

    m = manifest_status(preset)
    foreign = m.get("preset_id") if m.get("preset_id") not in (None, pr.preset_id) else None
    snap = config.preset_identity(pr.dir).get("snapshot_captured_at")
    stale = bool(m.get("exists") and snap and m.get("source_snapshot") and m["source_snapshot"] != snap)
    st = "unmeasured" if (foreign or stale) else m["status"]
    if st == "measured":
        state = "resolved"
    elif foreign:
        state = "foreign_file"
    elif stale:
        state = "remeasure"
    elif net or config._NETWORK_RE.search(str(m.get("blocker") or "")):
        state = "blocked_network"
    elif m.get("review"):
        state = "needs_manual_observation"
    else:
        state = "open"
    impact = ("없음" if st == "measured" else
              "원 채널의 글자 없는 로고·워터마크를 QA 가 대조할 템플릿이 없음(또는 일부) → identity.logo_templates 못 잼, "
              "production 관문 통과 불가(글자 표식은 OCR 검사만)")
    return _row(IDENTITY_ITEM, st, impact, state,
                f"{m['file']} status={m['status'] if m.get('exists') else '없음'} templates={m['templates']} "
                f"review={m['review']} manual_files={m['manual_files']}"
                + (f" source_snapshot={m.get('source_snapshot')}≠{snap}(다시 추출)" if stale else "")
                + (f" preset_id={foreign}(다른 프리셋)" if foreign else "")
                + (f"; blocker={m.get('blocker')}" if st != "measured" and m.get("blocker") else ""))


BGM_ID_KEYS = ("track_id", "title", "version", "tempo_ratio", "section_start_s")


def _bgm_stage(pr: config.Preset, net: bool) -> dict:
    item = "BGM 곡·버전·속도·사용 구간 식별"
    vals = {k: pr.get(f"audio.bgm.{k}") for k in BGM_ID_KEYS}
    orgs = {k: pr.origin(f"audio.bgm.{k}") for k in BGM_ID_KEYS}
    pres, pres_o = pr.get("presence.bgm"), pr.origin("presence.bgm")
    ev = ", ".join(f"{k}={vals[k]!r}({orgs[k]})" for k in BGM_ID_KEYS) + f"; presence.bgm={pres}({pres_o})"
    has_lib = config._music_library_has_tracks()
    if pres_o in ("measured", "requested_change") and pres == "absent":
        return _row(item, "absent", "없음 — 레퍼런스에 BGM 이 없어 넣지 않음", "resolved", ev)
    if all(o in ("measured", "requested_change") for o in orgs.values()) and vals["track_id"]:
        from .edit.audio import lookup_track

        path, _ = lookup_track(str(vals["track_id"]))
        return _row(item, "measured", "없음" if path else "곡은 식별됐으나 깨끗한 음악 파일이 라이브러리에 없음 → production 렌더 불가",
                    "resolved" if path else "open_user_asset",
                    ev + f"; 라이브러리 파일={path or '없음'}")
    missing = [k for k in BGM_ID_KEYS if orgs[k] not in ("measured", "requested_change")]
    return _row(item, "unmeasured", "음악 구간 일치 판정 불가, 깨끗한 음악 파일 확보 불가",
                "blocked_network" if net else ("open_user_asset" if not has_lib else "open"),
                ev + f"; 못 잰 항목={missing}; 음악 라이브러리 트랙 {'있음' if has_lib else '없음'}")


def _font_stage(pr: config.Preset, d: Path, net: bool) -> dict:
    item = "글꼴 식별(IoU 상한 + 후보 검증)"
    fr = read_json(d / "fonts_report.json", {}) or {}
    fo = _foreign(fr, pr)
    idn = (fr.get("identification") or {}) if not fo else {}
    roles = list(pr.section("text.roles").keys())
    per = []
    ok = []
    for r in roles:
        o = pr.origin(f"text.roles.{r}.font_name")
        rv = ((idn.get("roles") or {}).get(r) or {})
        per.append(f"{r}={rv.get('verdict') or rv.get('label_ko') or '-'}/{o}")
        if o in ("measured", "requested_change"):
            ok.append(r)
    status = "measured" if len(ok) == len(roles) else ("partial" if ok else "unmeasured")
    if status == "measured":
        state = "resolved"
    elif fo:
        state = "foreign_file"
    elif net or config._NETWORK_RE.search(str(idn.get("blocker") or "")):
        state = "blocked_network"
    else:
        state = "open"          # crops exist but no identical verdict: more candidate fonts / better crops needed
    return _row(item, status, "없음" if status == "measured" else "글꼴이 레퍼런스와 같은지 판정 불가(동일 판정 없는 역할은 임시 글꼴)",
                state, f"fonts_report.json status={fr.get('status', '없음')}" + (f" preset_id={fo}(다른 프리셋)" if fo else "")
                + "; 역할별 판정/값 출처: " + ", ".join(per))


PRESENCE_KO = {"present": "있다", "absent": "없다", "unmeasured": "못 잼"}


def _presence_rows(pr: config.Preset) -> list[str]:
    """Channel-level 있다/없다/못 잼 for motion, transitions, BGM, original audio (overall + per format)."""
    meas = config.load_measurement_items(pr.dir, strict=False)
    keys = [k for k in config.flatten(pr.data) if k.startswith("presence.")]
    fmts = sorted({f for k in keys for f in ((meas.get(k) or {}).get("by_format") or {})})
    lines = ["| 항목 | 전체 | " + " | ".join(fmts) + (" | " if fmts else "") + "n(있다/측정) | 근거 |",
             "|---|---|" + "---|" * len(fmts) + "---|---|"]
    for k in sorted(keys):
        m = meas.get(k) or {}
        v = pr.get(k) if pr.origin(k) in ("measured", "requested_change") else "unmeasured"
        cells = []
        for f in fmts:
            st = (m.get("by_format") or {}).get(f) or {}
            cells.append(PRESENCE_KO.get(st.get("value") or "unmeasured", str(st.get("value"))))
        ov = m.get("overall") or {}
        ev = ", ".join(f"{e.get('video_id')}@{e.get('t')}" for e in (m.get("evidence") or [])[:3]) or (m.get("blocker") or "-")[:80]
        lines.append(f"| `{k}` | {PRESENCE_KO.get(v, v)} | " + " | ".join(cells) + (" | " if fmts else "")
                     + f"{ov.get('n_present', '-')}/{ov.get('n', 0)} | {ev} |")
    return lines


def write_unresolved(preset: str) -> Path:
    reg = read_yaml(config.registry_path(preset), {}) or {}
    ents = reg.get("entries") or {}
    stage = _stage_blockers(preset)
    pr = config.load_preset(preset)
    groups: dict[str, list[str]] = {}
    for k, e in ents.items():
        if e.get("status") == "unmeasured":
            groups.setdefault(e.get("impact_if_unmeasured") or "-", []).append(k)
    lines = ["# 미확정 항목·제작 영향·해결 상태", "",
             f"자동 생성: `shortkit preset unresolved` ({now_iso()}). 손으로 고치지 말 것 — 원본은 settings_registry.yaml 과 각 산출물"
             "(단계 표는 유효 프리셋 = preset.yaml + measured.yaml + requested_changes.yaml 과 각 단계 파일에서 다시 평가).",
             "", "못 잼 = 측정하지 못함. 못 잼 항목은 임시값으로만 테스트 렌더가 가능하고, QA 에서 완료로 승격되지 않는다.", "",
             "## 1. 단계 단위 미확정", "", "| 항목 | 상태 | 제작 영향 | 해결 상태 | 근거 |", "|---|---|---|---|---|"]
    ko = {"measured": "측정됨", "unmeasured": "못 잼", "partial": "일부 측정", "absent": "없다(측정)"}
    for s in stage:
        lines.append(f"| {s['item']} | {ko.get(s['status'], s['status'])} | {s['impact']} | {s['state']} | {s['evidence']} |")
    lines += ["", "## 2. 모션·전환·BGM·원음 있다/없다/못 잼 (채널 단위, 전체·포맷별)", ""] + _presence_rows(pr)
    counts: dict[str, int] = {}
    states: dict[str, int] = {}
    for e in ents.values():
        counts[e.get("status")] = counts.get(e.get("status"), 0) + 1
        if e.get("status") == "unmeasured":
            states[e.get("resolution_state")] = states.get(e.get("resolution_state"), 0) + 1
    lines += ["", "## 3. 프리셋 설정 키 단위", "",
              "상태별 개수: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())), "",
              "못 잼 키의 해결 상태: " + ", ".join(f"{k}={v}" for k, v in sorted(states.items())), "",
              "| 제작 영향 | 못 잼 키 수 | 해결 상태 | 키 |", "|---|---|---|---|"]
    for impact, keys in sorted(groups.items(), key=lambda x: -len(x[1])):
        shown = ", ".join(f"`{k}`" for k in sorted(keys)[:12]) + (" …" if len(keys) > 12 else "")
        st = sorted({ents[k].get("resolution_state") for k in keys})
        lines.append(f"| {impact} | {len(keys)} | {', '.join(st)} | {shown} |")
    routes = {k: e for k, e in ents.items() if e.get("status") == "unmeasured"
              and (e.get("measurement_route") or {}).get("route") == "manual_observation"}
    if routes:
        lines += ["", "### 자동 측정 방법이 없는 키(관찰 경로)", "", "| 키 | 해결 상태 | 측정 경로 |", "|---|---|---|"]
        for k, e in sorted(routes.items()):
            r = e["measurement_route"]
            lines.append(f"| `{k}` | {e.get('resolution_state')} | {r.get('how')}"
                         + (f" — {r['missing']}" if r.get("missing") else "") + " |")
    na = {k: e for k, e in ents.items() if e.get("status") == "not_applicable_given"}
    lines += ["", "### 다른 측정값 때문에 해당 없는 키", ""]
    if na:
        lines += ["| 키 | 근거 키 = 값 | 이유 | 제작에서 |", "|---|---|---|---|"]
        for k, e in sorted(na.items()):
            n = e.get("not_applicable") or {}
            lines.append(f"| `{k}` | `{n.get('given')}` = {n.get('given_value')!r} | {n.get('reason')} | {n.get('production_use')} |")
    else:
        lines.append("없음(근거가 되는 값이 아직 측정되지 않음)")
    lines += ["", "## 4. 해결 방법", "",
              "1. 네트워크가 열린 컴퓨터(또는 환경 설정에서 youtube.com, *.googlevideo.com, i.ytimg.com, tiktok.com, instagram.com, "
              "reddit.com, v.redd.it, dl.fbaipublicfiles.com 허용)에서 AGENTS.md 의 '레퍼런스 분석 실행 순서'를 실행.",
              "2. 효과음 창고·깨끗한 음악 파일을 assets/library/ 또는 local.yaml 경로에 제공.",
              "3. 관찰 경로 키(위 표)는 영상을 본 사람이 manual_observations.csv 에 기록 → `shortkit ref manual-aggregate`.",
              "4. 측정 후 `shortkit preset apply-measurements` → `shortkit preset sync` → `shortkit preset unresolved` 로 이 문서 갱신.", ""]
    out = paths.preset_dir(preset) / "unresolved.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def cmd_unresolved(args) -> int:
    p = write_unresolved(args.preset)
    print(f"wrote {paths.relp(p)}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    register(ap)
    a = ap.parse_args()
    sys.exit(a.func(a))
