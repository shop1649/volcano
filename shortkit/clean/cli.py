"""`shortkit clean ...` -- overlay detection, cleaning plan, apply, residual verification."""
from __future__ import annotations

import argparse
import json
import sys
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
    from .detect import detect_overlays, load_overlays

    doc = load_overlays(sha)
    if doc is None or not doc.get("algo"):
        print("오버레이 기록이 없어 검출을 먼저 실행합니다…")
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


def find_alternates(sha: str) -> list[dict]:
    """``alternates`` of the warehouse record whose sha256 is ``sha``: clean originals of the
    same content (list of {path, sha256} or candidate ids)."""
    rows = read_jsonl(paths.absp(CANDIDATES))
    by_id = {r.get("id"): r for r in rows}
    rec = next((r for r in rows if r.get("sha256") == sha), None)
    out = []
    for a in (rec or {}).get("alternates") or []:
        if isinstance(a, str):
            r = by_id.get(a) or {}
            out.append({"warehouse_id": a, "path": r.get("download_path"), "sha256": r.get("sha256")})
        elif isinstance(a, dict):
            out.append({"warehouse_id": a.get("id") or a.get("warehouse_id"),
                        "path": a.get("path") or a.get("download_path"), "sha256": a.get("sha256")})
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
    doc = detect_overlays(src, DetectParams(sample_fps=args.sample_fps, ocr=not args.no_ocr))
    if args.json:
        print(json.dumps(doc, ensure_ascii=False, indent=2))
    else:
        print(summary_ko(doc))
        print(f"기록: {doc.get('_path')}")
    return 0


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
            adoc = load_overlays(a["sha256"])
            if adoc is None and a.get("path") and paths.absp(a["path"]).is_file():
                from .detect import detect_overlays

                adoc = detect_overlays(paths.absp(a["path"]))
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
    print("\n# plan.yaml sources[] 에 붙여 넣을 블록 (원본 px/시간, 해상도 "
          f"{doc['source']['resolution'][0]}x{doc['source']['resolution'][1]})")
    blk = {"clean": plan["clean"], "protected": plan["protected"]}
    if plan.get("replace_source"):
        blk = {"path": plan["replace_source"]["path"], "sha256": plan["replace_source"]["sha256"], **blk}
    print(_yaml_block(blk))
    print(f"계획 저장: {_rel(out) or out.name}")
    return 0


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
    ver = verify_doc(out, doc, clean=clean)
    append_history(sha, {"action": "apply", "out": _rel(out), "out_sha256": res["sha256"], "clean": clean,
                         "verify": ver["rows"]})
    removals = [{"overlay_id": r["overlay_id"], "residual": r["residual"], "how": r["how"],
                 "status": r["status"], "out_sha256": res["sha256"], "at": now_iso()} for r in ver["rows"]]
    _append_removals(sha, removals)
    print(f"출력: {_rel(out) or out.name}  sha256={res['sha256'][:12]}")
    _print_verify(ver["rows"])
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
