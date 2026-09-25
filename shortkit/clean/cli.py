"""`shortkit clean ...` -- overlay detection, cleaning plan, apply, residual verification."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .. import paths
from ..util.hashing import sha256_file
from ..util.jsonio import now_iso, read_json, read_jsonl, read_yaml, write_json

CANDIDATES = "warehouse/candidates.jsonl"


def register(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("detect", help="원본 로고·출처 오버레이·원어 자막 검출 → warehouse/overlays/<sha256>.json")
    d.add_argument("--source", required=True, help="소스 영상 경로(프로젝트 루트 기준 또는 절대 경로)")
    d.add_argument("--sample-fps", type=float, default=2.0, help="분석 프레임 수/초 (기본 2)")
    d.add_argument("--max-samples", type=int, default=240,
                   help="분석 프레임 상한(긴 영상은 sample-fps 가 자동으로 낮아짐 → 짧은 자막을 놓칠 수 있음)")
    d.add_argument("--no-ocr", action="store_true", help="OCR 끄기(글자 검사는 '못 잼'으로 기록)")
    d.add_argument("--json", action="store_true", help="결과 JSON 을 그대로 출력")
    d.set_defaults(func=cmd_detect)

    f = sub.add_parser("faces", help="얼굴(보호 영역) 검출 → warehouse/overlays/<sha256>.faces.json")
    f.add_argument("--source", required=True)
    f.add_argument("--sample-fps", type=float, default=0.5)
    f.add_argument("--max-samples", type=int, default=24)
    f.set_defaults(func=cmd_faces)

    pl = sub.add_parser("plan", help="오버레이별 처리 결정(깨끗한 원본 → 잘라내기 → 국소 복원) + plan 용 clean 블록")
    pl.add_argument("--source", required=True)
    pl.add_argument("--region-aspect", default=None, help="영상 영역 비율(예: 1080:608, 16:9, 1.776). 생략 시 프리셋")
    pl.add_argument("--fit", choices=["cover", "contain"], default=None, help="생략 시 프리셋 canvas.video_region.fit")
    pl.add_argument("--preset", default="joshuamagazine")
    pl.add_argument("--protected", default=None,
                    help="보호 영역 파일(JSON/YAML 목록) 또는 episodes/<id>/plan.yaml (+ --source-id)")
    pl.add_argument("--source-id", default=None, help="--protected 가 plan.yaml 일 때 sources[].id")
    pl.add_argument("--no-faces", action="store_true", help="얼굴 검출 생략(→ 잘라내기 금지)")
    pl.add_argument("--face-sample-fps", type=float, default=0.5)
    pl.add_argument("--min-keep", type=float, default=None, help="잘라내기 후 남길 최소 면적 비율(기본 0.7)")
    pl.add_argument("--out", default=None, help="계획 JSON 저장 위치(기본 warehouse/overlays/<sha256>.plan.json)")
    pl.set_defaults(func=cmd_plan)

    cv = sub.add_parser("coverage", help="plan.yaml 의 clean 블록이 기록된 오버레이를 모두 덮는지 검사(빠진 오버레이 = 오류)")
    cv.add_argument("--plan", required=True, help="episodes/<id>/plan.yaml (또는 clean 블록 JSON/YAML)")
    cv.add_argument("--source-id", default=None, help="plan.yaml 의 sources[].id (생략 시 전부)")
    cv.add_argument("--all-time", action="store_true", help="타임라인이 쓰는 구간만이 아니라 소스 전체 시간 검사")
    cv.set_defaults(func=cmd_coverage)

    ap = sub.add_parser("apply", help="clean 블록 적용(inpaint→delogo→blur→crop) 후 잔여 검사")
    ap.add_argument("--source", required=True)
    ap.add_argument("--plan", default=None, help="계획 JSON(기본 warehouse/overlays/<sha256>.plan.json)")
    ap.add_argument("--inpaint-only", action="store_true", help="계획 없이 검출된 모든 오버레이를 inpaint")
    ap.add_argument("--out", required=True, help="출력 MP4 경로")
    ap.add_argument("--threads", type=int, default=None)
    ap.set_defaults(func=cmd_apply)

    v = sub.add_parser("verify", help="영상에 원래 오버레이가 남았는지 검사(템플릿 매칭 + OCR)")
    v.add_argument("--video", required=True, help="검사할 영상")
    v.add_argument("--source", default=None, help="오버레이 기록을 가진 원본 소스(좌표는 --plan 의 crop 로 변환)")
    v.add_argument("--plan", default=None, help="video 를 만든 계획 JSON(crop 좌표 변환용)")
    v.add_argument("--rect", default=None, help="직접 지정: x,y,w,h (video px)")
    v.add_argument("--template", default=None)
    v.add_argument("--text", default=None)
    v.add_argument("--times", default=None, help="검사 시각(초), 쉼표 구분")
    v.set_defaults(func=cmd_verify)

    s = sub.add_parser("show", help="소스의 오버레이 기록·처리 이력 보기")
    s.add_argument("--source", required=True)
    s.set_defaults(func=cmd_show)

    m = sub.add_parser("fetch-models", help="얼굴 검출용 Haar 캐스케이드 파일 받기(sha256 고정)")
    m.add_argument("--force", action="store_true")
    m.set_defaults(func=cmd_fetch_models)


# ----------------------------------------------------------------------------- helpers
def _src(path: str) -> Path:
    p = paths.absp(path) if not Path(path).is_absolute() else Path(path)
    if not p.is_file():
        raise SystemExit(f"소스 파일이 없습니다: {path}")
    return p


def _rel(p: Path) -> str | None:
    try:
        return paths.relp(p)
    except ValueError:
        return None


def _ensure_overlays(src: Path, sha: str) -> dict:
    from .detect import ALGO, detect_overlays, load_overlays

    doc = load_overlays(sha)
    if doc is None or not doc.get("algo"):
        print("오버레이 기록이 없어 검출을 먼저 실행합니다…")
        doc = detect_overlays(src)
    elif doc.get("algo") != ALGO:
        print(f"오버레이 기록이 이전 검출 알고리즘({doc.get('algo')})으로 만들어져 다시 검출합니다({ALGO})…")
        doc = detect_overlays(src)
    return doc


def faces_path(sha: str) -> Path:
    from .detect import OVERLAYS_DIR

    return paths.absp(f"{OVERLAYS_DIR}/{sha}.faces.json")


def plan_path(sha: str) -> Path:
    from .detect import OVERLAYS_DIR

    return paths.absp(f"{OVERLAYS_DIR}/{sha}.plan.json")


def _ensure_faces(src: Path, sha: str, sample_fps: float, max_samples: int = 24) -> dict:
    from .faces import detect_faces

    fp = faces_path(sha)
    doc = read_json(fp)
    req = {"sample_fps": sample_fps, "max_samples": max_samples}
    if doc and doc.get("status") == "measured" and doc.get("requested") == req:
        return doc
    doc = detect_faces(src, sample_fps=sample_fps, max_samples=max_samples)
    doc["source"] = {"path": _rel(src), "sha256": sha}
    doc["requested"] = req
    write_json(fp, doc)
    return doc


def _candidates() -> list[dict]:
    return read_jsonl(paths.absp(CANDIDATES))


def record_by_sha(sha: str, rows: list[dict] | None = None) -> dict | None:
    """Warehouse candidate record whose downloaded file has this sha256."""
    return next((r for r in (rows if rows is not None else _candidates()) if r.get("sha256") == sha), None)


def find_alternates(sha: str) -> list[dict]:
    """``alternates`` of the warehouse record whose sha256 is ``sha``: clean originals of the
    same content, linked with ``shortkit source link-original`` (entries: candidate id strings or
    ``{id, linked_by, ...}``; legacy ``{path, sha256}`` dicts are accepted).  Path/sha256 come from
    the linked record when the entry names a candidate."""
    rows = _candidates()
    by_id = {r.get("id"): r for r in rows}
    rec = record_by_sha(sha, rows)
    out = []
    for a in (rec or {}).get("alternates") or []:
        if isinstance(a, str):
            a = {"id": a}
        if not isinstance(a, dict):
            continue
        wid = a.get("id") or a.get("warehouse_id")
        r = by_id.get(wid) or {}
        out.append({"warehouse_id": wid, "path": a.get("path") or r.get("download_path"),
                    "sha256": a.get("sha256") or r.get("sha256"), "status": r.get("status"),
                    "linked_by": a.get("linked_by")})
    return out


def original_suggestions(sha: str, doc: dict) -> list[str]:
    """How to reach step 1 (a clean original) when the source has overlays and no linked original."""
    if not [o for o in doc.get("overlays", []) if not o.get("ignored")]:
        return []
    rows = _candidates()
    rec = record_by_sha(sha, rows)
    if rec is None:
        return ["이 파일은 창고 기록(candidates.jsonl)에 없음 → 출처·원본을 추적할 수 없음. "
                "`python -m shortkit source add-url <게시 URL> --file <이 파일>` 로 먼저 등록"]
    if find_alternates(sha):
        return []
    out = []
    ou = rec.get("original_url")
    if ou:
        try:
            from ..sourcing.platforms import url_key
        except Exception:  # noqa: BLE001
            url_key = None
        hit = [r for r in rows if url_key and url_key(r.get("url")) == url_key(ou) and r.get("id") != rec["id"]]
        if hit:
            out.append(f"원본 URL({ou}) 후보가 창고에 있음: {hit[0]['id']} → 같은 녹화인지 보고 "
                       f"`python -m shortkit source link-original {rec['id']} {hit[0]['id']} --by <이름> --note '...'`")
        else:
            out.append(f"원본 URL 이 기록됨({ou}) → `python -m shortkit source add-url {ou}` 후 받아서 "
                       f"`python -m shortkit source link-original {rec['id']} <원본 ID> --by <이름> --note '...'`")
    handles = sorted({h.get("handle") for h in (rec.get("repost_evidence") or []) if h.get("handle")})
    oa = rec.get("original_author")
    if not ou and (oa or handles) and (oa != rec.get("uploader") or handles):
        who = ", ".join([x for x in [oa, *handles] if x])
        out.append(f"원작자/워터마크 계정({who})의 원본 게시물을 찾으면 add-url 로 넣고 `source link-original` 로 연결")
    if not out:
        out.append("깨끗한 원본 후보 없음(원본 URL·원작자 기록 없음) → 원본을 찾으면 add-url 후 "
                   f"`python -m shortkit source link-original {rec['id']} <원본 ID> --by <이름> --note '...'`")
    return out


def _load_protected(arg: str | None, source_id: str | None) -> list[dict]:
    if not arg:
        return []
    p = paths.absp(arg)
    data = read_yaml(p) if p.suffix in (".yaml", ".yml") else read_json(p)
    if isinstance(data, dict) and "sources" in data:
        srcs = [s for s in data["sources"] if source_id is None or s.get("id") == source_id]
        return [dict(x) for s in srcs for x in (s.get("protected") or [])]
    if isinstance(data, dict) and "protected" in data:
        return list(data["protected"])
    return list(data or [])


def _yaml_block(obj) -> str:
    import yaml

    return yaml.safe_dump(json.loads(json.dumps(obj)), allow_unicode=True, sort_keys=False, width=120)


# ----------------------------------------------------------------------------- commands
def cmd_detect(args) -> int:
    from .detect import DetectParams, detect_overlays, summary_ko

    src = _src(args.source)
    doc = detect_overlays(src, DetectParams(sample_fps=args.sample_fps, max_samples=args.max_samples,
                                            ocr=not args.no_ocr))
    used = doc["params"]["sample_fps_used"]
    if used < args.sample_fps - 1e-6:
        print(f"주의: 영상이 길어 분석 간격이 {1 / used:.2f}s 로 늘어남 → 그보다 짧은 자막은 놓칠 수 있음 "
              f"(--max-samples 로 늘리기)")
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print(summary_ko(doc))
        print(f"기록: {doc.get('_path')}")
    _refresh_warehouse_record(doc["source"]["sha256"], quiet=args.json)
    return 0


def _refresh_warehouse_record(sha: str, quiet: bool = False) -> None:
    """A watermark handle of another account found here is repost evidence for the warehouse record of this
    file (original author / reposter / recency are recomputed and saved)."""
    try:
        from ..sourcing import warehouse
    except Exception:  # noqa: BLE001 - sourcing area unavailable
        return
    rows = warehouse.load()
    rec = next((r for r in rows if r.get("sha256") == sha), None)
    if rec is None:
        return
    before = (rec.get("original_author"), rec.get("reposter"))
    warehouse.refresh_scores(rec)
    warehouse.put(rec)
    if quiet:
        return
    other = [e for e in rec.get("repost_evidence") or [] if e.get("same_as_uploader") is False]
    if other:
        print(f"창고 후보 {rec['id']}: 워터마크 {', '.join(e['handle'] for e in other)} ≠ 업로더 {rec.get('uploader')} "
              f"→ 재업로드로 기록(원작자 {rec.get('original_author')}, 최근성은 원본 게시일로 판정)")
    elif (rec.get("original_author"), rec.get("reposter")) != before:
        print(f"창고 후보 {rec['id']}: 원작자/재업로더 갱신 → {rec.get('original_author')} / {rec.get('reposter')}")


def cmd_faces(args) -> int:
    src = _src(args.source)
    sha = sha256_file(src)
    doc = _ensure_faces(src, sha, args.sample_fps, args.max_samples)
    if doc["status"] != "measured":
        print(f"얼굴 검출: 못 잼 — {doc.get('blocker')}")
        return 1
    print(f"얼굴 검출({doc['method']}): 프레임 {len(doc['samples'])}개, 보호 영역 {len(doc['faces'])}개 "
          f"(해상도 {doc['resolution'][0]}x{doc['resolution'][1]})")
    for f in doc["faces"]:
        print(f"  - x={f['x']:.0f} y={f['y']:.0f} w={f['w']:.0f} h={f['h']:.0f} {f['start']:.1f}~{f['end']:.1f}s "
              f"(검출 {f['hits']}회, {','.join(f['kinds'])})")
    print(f"기록: {_rel(faces_path(sha))}")
    return 0


def cmd_plan(args) -> int:
    from . import strategy
    from .detect import append_history, load_overlays

    src = _src(args.source)
    sha = sha256_file(src)
    doc = _ensure_overlays(src, sha)
    if args.region_aspect:
        region = {"aspect": strategy.parse_aspect(args.region_aspect), "fit": args.fit or "cover", "size": None,
                  "source": "cli"}
        if args.fit is None:
            try:
                from ..config import load_preset

                region["fit"] = str(load_preset(args.preset).get("canvas.video_region.fit"))
                region["source"] = "cli aspect + preset fit"
            except Exception:
                pass
    else:
        from ..config import load_preset

        region = strategy.region_from_preset(load_preset(args.preset))
        if args.fit:
            region["fit"] = args.fit
    faces = None if args.no_faces else _ensure_faces(src, sha, args.face_sample_fps)
    alts = []
    for a in find_alternates(sha):
        adoc = None
        if a.get("sha256"):
            if a.get("path") and paths.absp(a["path"]).is_file():
                adoc = _ensure_overlays(paths.absp(a["path"]), a["sha256"])
            else:
                adoc = load_overlays(a["sha256"])
        afaces = None
        if adoc is not None and a.get("path") and paths.absp(a["path"]).is_file() and not args.no_faces:
            afaces = _ensure_faces(paths.absp(a["path"]), a["sha256"], args.face_sample_fps)
        alts.append({**a, "overlays": adoc, "faces": afaces})
    pol = strategy.CleanPolicy()
    if args.min_keep is not None:
        pol.min_keep_frac = args.min_keep
    plan = strategy.plan_clean(doc, region_aspect=region["aspect"], fit=region["fit"], faces=faces,
                               protected=_load_protected(args.protected, args.source_id), alternates=alts,
                               policy=pol, region_size=region.get("size"))
    plan["region"]["source"] = region.get("source")
    out = paths.absp(args.out) if args.out else plan_path(sha)
    write_json(out, plan)
    append_history(sha, {"action": "plan", "plan": _rel(out), "clean": plan["clean"],
                         "replace_source": plan.get("replace_source"),
                         "decisions": [{k: d.get(k) for k in ("overlay_id", "action", "reason")} for d in plan["decisions"]]})
    print(strategy.summary_ko(plan))
    rs = plan.get("replace_source")
    if rs:
        blk_path, blk_sha, wid = rs.get("path"), rs.get("sha256"), rs.get("warehouse_id")
        res_ = (plan.get("source") or {}).get("resolution") or doc["source"]["resolution"]
    else:
        rec = record_by_sha(sha)
        blk_path, blk_sha, wid = _rel(src), sha, (rec or {}).get("id")
        res_ = doc["source"]["resolution"]
    print("\n# plan.yaml sources[] 에 붙여 넣을 블록 (path·sha256·warehouse_id 를 함께 바꿀 것; 원본 px/시간, 해상도 "
          f"{res_[0]}x{res_[1]})")
    blk = {"path": blk_path, "sha256": blk_sha, "warehouse_id": wid, "clean": plan["clean"], "protected": plan["protected"]}
    print(_yaml_block(blk))
    if rs:
        alt = next((a for a in find_alternates(sha) if a.get("warehouse_id") == wid), {})
        if wid and alt.get("status") not in ("selected", "used"):
            print(f"! 교체 원본 {wid} 의 창고 상태가 {alt.get('status')!r} → production 에서는 선택된 후보만 쓸 수 있음: "
                  f"`python -m shortkit source review {wid} ...` 후 `python -m shortkit source select {wid} --by ...`")
        if not wid:
            print("! 교체 원본에 창고 ID 가 없음 → `source add-url <원본 URL> --file <원본 파일>` 로 등록 후 link-original")
    else:
        if wid is None:
            print("! 이 소스는 창고 기록이 없어 warehouse_id 를 비워 둠 → production validate 에서 오류(provenance_missing)")
        for tip in original_suggestions(sha, doc):
            print(f"  원본 찾기(1순위 깨끗한 원본): {tip}")
    # self-check: the printed block removes every recorded overlay of the file it names
    from .plan_coverage import coverage_report, summary_ko as cov_ko

    cov_src = paths.absp(blk_path) if blk_path else src
    rep = coverage_report(cov_src, plan["clean"], sha256=blk_sha)
    bad = [e for e in rep["uncovered"] if e.get("blocking")]
    print("덮개 검사(clean coverage): " + ("통과 — 기록된 오버레이를 모두 덮음" if not bad else "실패"))
    if rep["uncovered"]:
        print(cov_ko(rep["uncovered"]))
    print(f"계획 저장: {_rel(out) or out.name}")
    return 0 if not bad else 1


def _plan_sources(arg: str, source_id: str | None) -> list[dict]:
    p = paths.absp(arg)
    data = read_yaml(p) if p.suffix in (".yaml", ".yml") else read_json(p)
    if isinstance(data, dict) and "sources" in data:
        srcs = [s for s in data["sources"] if source_id is None or s.get("id") == source_id]
        tl = data.get("timeline") or []
        for s in srcs:
            s["_used"] = [[float(t["src_in"]), float(t["src_out"])] for t in tl if t.get("source") == s.get("id")
                          and t.get("src_in") is not None and t.get("src_out") is not None]
        return srcs
    return [{"id": source_id, "path": None, "clean": data, "_used": []}]


def cmd_coverage(args) -> int:
    from .plan_coverage import coverage_report, summary_ko as cov_ko

    srcs = _plan_sources(args.plan, args.source_id)
    if not srcs:
        print("검사할 소스가 없습니다(--source-id 확인)")
        return 2
    n_bad = 0
    for s in srcs:
        if not s.get("path"):
            print(f"[{s.get('id')}] path 없음 — plan.yaml 을 주세요")
            n_bad += 1
            continue
        used = None if args.all_time or not s.get("_used") else s["_used"]
        rep = coverage_report(s["path"], s.get("clean"), sha256=s.get("sha256"), used_ranges=used)
        bad = [e for e in rep["uncovered"] if e.get("blocking")]
        n_bad += len(bad)
        scope = "소스 전체 시간" if used is None else f"타임라인 구간 {used}"
        print(f"[{s.get('id')}] {s['path']} ({scope}) 기록={rep.get('record')} → "
              + ("통과" if not bad else f"덮지 못한 오버레이 {len(bad)}개"))
        if rep["uncovered"]:
            print(cov_ko(rep["uncovered"]))
    return 0 if n_bad == 0 else 1


def cmd_apply(args) -> int:
    from .apply import apply_clean, inpaint_video
    from .detect import append_history
    from .verify import verify_doc

    src = _src(args.source)
    sha = sha256_file(src)
    doc = _ensure_overlays(src, sha)
    out = paths.absp(args.out) if not Path(args.out).is_absolute() else Path(args.out)
    if args.inpaint_only:
        clean = {"crop": None, "delogo": [], "blur": [],
                 "inpaint": [{**{k: o["rect"][k] for k in ("x", "y", "w", "h")},
                              "start": o["start"], "end": o["end"]} for o in doc.get("overlays", [])]}
        r = inpaint_video(src, clean["inpaint"], out, threads=args.threads)
        res = {"out": r["out"], "sha256": r["sha256"], "steps": [{"op": "inpaint", "per_rect": r["per_rect"]}]}
    else:
        pp = paths.absp(args.plan) if args.plan else plan_path(sha)
        plan = read_json(pp)
        if not plan:
            print(f"계획 파일이 없습니다: {args.plan or _rel(pp)} — 먼저 `shortkit clean plan --source ...`")
            return 1
        if plan.get("replace_source"):
            print(f"이 계획은 원본 교체({plan['replace_source'].get('path')})를 권합니다. 교체한 원본으로 다시 실행하세요.")
            return 1
        if plan["source"].get("sha256") != sha:
            print("계획의 sha256 이 소스와 다릅니다 — 다른 파일의 계획입니다.")
            return 1
        clean = plan["clean"]
        res = apply_clean(src, clean, out, threads=args.threads)
        res["plan_status"] = plan.get("status")
        res["review_reasons"] = plan.get("review_reasons") or []
    ver = verify_doc(out, doc, clean=clean)
    append_history(sha, {"action": "apply", "out": _rel(out), "out_sha256": res["sha256"], "clean": clean,
                         "verify": ver["rows"]})
    removals = [{"overlay_id": r["overlay_id"], "residual": r["residual"], "how": r["how"],
                 "status": r["status"], "out_sha256": res["sha256"], "at": now_iso()} for r in ver["rows"]]
    _append_removals(sha, removals)
    print(f"출력: {_rel(out) or out.name}  sha256={res['sha256'][:12]}")
    _print_verify(ver["rows"])
    checks = doc.get("checks") or {}
    pending = res.get("review_reasons") or [f"{k}: {v.get('status')}" for k, v in checks.items()
                                            if isinstance(v, dict) and v.get("status") != "measured"]
    if pending:
        print("주의: 검출된 오버레이는 처리했지만 이 소스의 정리는 '완료'가 아님(사람 확인 필요):")
        for r in pending:
            print(f"  ! {r}")
    bad = [r for r in ver["rows"] if r["residual"] or r["status"] != "measured"]
    return 1 if bad else 0


def _append_removals(sha: str, removals: list[dict]) -> None:
    from .detect import overlays_path

    p = overlays_path(sha)
    doc = read_json(p) or {}
    doc.setdefault("removals", []).extend(removals)
    write_json(p, doc)


def _print_verify(rows: list[dict]) -> None:
    ko = {True: "남음", False: "없음", None: "못 잼"}
    for r in rows:
        extra = "잘라내기로 화면 밖" if r.get("how") == "removed_by_crop" else \
            f"템플릿 NCC={r.get('max_ncc')} OCR 일치={r.get('ocr_hits')}"
        print(f"  - {r['overlay_id']} {r['kind']}: 잔여 {ko[r['residual']]} ({extra})")


def cmd_verify(args) -> int:
    from .verify import residual_score, verify_doc

    video = _src(args.video)
    if args.rect:
        x, y, w, h = (float(v) for v in args.rect.split(","))
        times = [float(t) for t in (args.times or "").split(",") if t.strip()] or [0.0]
        rs = residual_score(video, {"x": x, "y": y, "w": w, "h": h}, args.template, times, args.text)
        print(json.dumps(rs, ensure_ascii=False, indent=2))
        return 0 if rs["residual"] is False else 1
    if not args.source:
        print("--source 또는 --rect 가 필요합니다")
        return 2
    from .detect import load_overlays

    sha = sha256_file(_src(args.source))
    doc = load_overlays(sha)
    if not doc:
        print("이 소스의 오버레이 기록이 없습니다 — `shortkit clean detect` 먼저")
        return 2
    clean = (read_json(paths.absp(args.plan)) or {}).get("clean") if args.plan else None
    ver = verify_doc(video, doc, clean=clean)
    _print_verify(ver["rows"])
    from .detect import append_history

    append_history(sha, {"action": "verify", "video": _rel(video), "video_sha256": sha256_file(video),
                         "rows": ver["rows"]})
    return 1 if (ver["residual_any"] or ver["unmeasured"]) else 0


def cmd_show(args) -> int:
    from .detect import load_overlays, summary_ko

    src = _src(args.source)
    sha = sha256_file(src)
    doc = load_overlays(sha)
    if not doc:
        print("기록 없음")
        return 1
    print(summary_ko(doc))
    print("이력:")
    for h in doc.get("history", []):
        print(f"  - {h.get('at')} {h.get('action')}" + (f" → {h.get('out') or h.get('plan') or ''}" if h.get("action") != "detect" else
                                                         f" (오버레이 {h.get('n_overlays')}개)"))
    for r in doc.get("removals", []):
        print(f"  제거 기록: {r['overlay_id']} residual={r['residual']} ({r['how']}) out={r['out_sha256'][:12]}")
    return 0


def cmd_fetch_models(args) -> int:
    from .faces import fetch_cascades

    res = fetch_cascades(force=args.force)
    for k, v in res["status"].items():
        print(f"{k}: {v}")
    print(f"위치: {res['dir']}  (출처 {res['source']['package']})")
    return 0 if all(not str(v).startswith("FAILED") for v in res["status"].values()) else 1
