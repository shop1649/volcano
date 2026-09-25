"""`shortkit ref ...` : reference channel collection, visual measurement, format classification,
source tracing (+ the typography / audio sub-commands registered by their own modules)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import paths
from .common import DEFAULT_PRESET, SET_NAMES, analysis_dir, resolve_ids, say, video_path, warn


def _ids(args) -> list[str]:
    ids = resolve_ids(args.preset, ids=getattr(args, "ids", None), set_name=getattr(args, "set", None),
                      limit=getattr(args, "limit", None))
    return ids


def cmd_collect(args) -> int:
    from .collect import collect
    r = collect(args.preset, method=args.method, refresh_snapshot=args.refresh_snapshot, cookies=args.cookies,
                max_meta=args.max_meta)
    return int(r["exit_code"])


def cmd_download(args) -> int:
    from .download import download
    ids = _ids(args)
    if not ids:
        warn("받을 영상이 없습니다(스냅샷이 비었거나 차단 상태). `shortkit ref collect` 결과를 확인하세요.")
        return 3
    r = download(args.preset, ids, max_height=args.max_height, cookies=args.cookies)
    return 3 if r["blocked"] else (1 if r["failed"] else 0)


def analyze_video(preset: str, vid: str, video: Path, fps: float = 5.0, only: set[str] | None = None,
                  max_seconds: float | None = None) -> dict:
    from ..config import load_preset
    from . import motion, shots, textboxes
    from .common import detect_video_region, region_evidence

    pr = load_preset(preset)
    role_fonts = {r: pr.get(f"text.roles.{r}.font_name") for r in pr.section("text.roles").keys()}
    identity = list(pr.get("identity_exclusions.forbidden_text", []) or [])
    out_dir = analysis_dir(preset, vid)
    out_dir.mkdir(parents=True, exist_ok=True)
    region = detect_video_region(video, max_seconds=max_seconds)
    region["evidence"] = region_evidence(preset, vid, video, region)     # stored in layout.json region_detection
    res = {"region": region}
    only = only or {"shots", "text", "motion"}
    if "shots" in only:
        res["shots"] = shots.analyze(video, vid, preset, region=region, out_dir=out_dir, max_seconds=max_seconds)
    if "text" in only:
        res["captions"], res["layout"] = textboxes.analyze(video, vid, preset, fps=fps, region=region,
                                                            out_dir=out_dir, role_fonts=role_fonts,
                                                            max_seconds=max_seconds, identity_texts=identity)
    if "motion" in only:
        res["motion"] = motion.analyze(video, vid, preset, region=region, out_dir=out_dir, max_seconds=max_seconds)
    return res


def cmd_analyze(args) -> int:
    only = set(args.only.split(",")) if args.only else None
    jobs: list[tuple[str, Path]] = []
    if args.video:
        if not args.id:
            warn("--video 에는 --id 가 필요합니다.")
            return 2
        jobs.append((args.id, Path(args.video)))
    else:
        for vid in _ids(args):
            v = video_path(args.preset, vid)
            if v is None:
                warn(f"{vid}: 영상 파일 없음(`shortkit ref download` 필요) → 건너뜀")
                continue
            jobs.append((vid, v))
    if not jobs:
        warn("분석할 영상이 없습니다.")
        return 3
    failed = 0
    for vid, v in jobs:
        d = analysis_dir(args.preset, vid)
        if args.skip_existing and all((d / f).is_file() for f in ("shots.json", "captions.json", "motion.json")):
            say(f"{vid}: 기존 분석 사용")
            continue
        try:
            r = analyze_video(args.preset, vid, v, fps=args.fps, only=only)
        except Exception as e:  # keep going with the other videos, but say so
            failed += 1
            warn(f"{vid}: 분석 실패 {type(e).__name__}: {e}")
            continue
        caps = (r.get("captions") or {}).get("items") or []
        cuts = (r.get("shots") or {}).get("cuts") or []
        ev = (r.get("motion") or {}).get("events") or []
        roles = {}
        for c in caps:
            roles[c["role"]] = roles.get(c["role"], 0) + 1
        say(f"{vid}: 영상 영역 {r['region'].get('video_region')}, 배경 {r['region'].get('background')}, "
            f"컷 {len(cuts)}, 자막 {len(caps)} {roles}, 모션 사건 {len(ev)} → {paths.relp(analysis_dir(args.preset, vid))}")
    return 1 if failed else 0


def cmd_classify_prepare(args) -> int:
    from .classify import prepare
    ids = _ids(args)
    if not ids:
        warn("검토 자료를 만들 영상이 없습니다(포맷 분류는 최신 100편 스냅샷 구성원 기준 — `shortkit ref collect` 결과 확인).")
        return 3
    prepare(args.preset, ids)
    return 0


def cmd_classify_build(args) -> int:
    from .classify import build
    r = build(args.preset)
    return 0 if r["status"] in ("measured", "partial") else 3


def cmd_aggregate(args) -> int:
    from .aggregate import aggregate
    ids = _ids(args) if (args.ids or args.set) else None
    r = aggregate(args.preset, ids, include_long=args.include_long)
    return 0 if r["videos"] else 3


def cmd_manual_aggregate(args) -> int:
    from .manual import aggregate_manual
    r = aggregate_manual(args.preset, include_long=args.include_long)
    return 0 if r["measured"] else 3


def cmd_trace(args) -> int:
    from .trace_sources import trace
    ids = _ids(args)
    r = trace(args.preset, ids, ocr_fps=args.ocr_fps, do_ocr=not args.no_ocr, lens=not args.no_lens)
    return 0 if r["traced_now"] else 3


def cmd_identity_templates(args) -> int:
    from .identity_templates import decide, extract
    if args.accept or args.reject:
        if not args.by:
            warn("--accept/--reject 에는 --by <후보 크롭을 실제로 본 사람> 이 필요합니다.")
            return 2
        m = decide(args.preset, args.accept or args.reject, "accept" if args.accept else "reject", args.by, args.note)
        return {"measured": 0, "partial": 4}.get(m["status"], 3)
    ids = _ids(args) if (args.ids or args.set) else None
    r = extract(args.preset, ids, include_long=args.include_long, ocr=not args.no_ocr)
    if r.get("kept_previous"):
        return 3
    return {"measured": 0, "partial": 4}.get(r["status"], 3)


def cmd_high_views_report(args) -> int:
    from .high_views import build_report
    r = build_report(args.preset)
    return 0 if r["status"] == "measured" else (3 if not r["videos"] else 4)


def cmd_transcribe(args) -> int:
    from .transcribe import transcribe_many
    r = transcribe_many(args.preset, _ids(args), model=args.model, language=args.language, force=args.force)
    return 0 if any(x["status"] in ("measured", "cached") for x in r["results"]) else 3


def _sel(p: argparse.ArgumentParser, default_set: str | None = "latest100") -> None:
    p.add_argument("--preset", default=DEFAULT_PRESET)
    p.add_argument("--ids", default=None, help="영상 id 쉼표 구분")
    p.add_argument("--set", default=default_set, choices=list(SET_NAMES),
                   help="대상 묶음(--ids 가 없을 때): latest100=고정 스냅샷(제작 측정 기준), high_views=조회수 기준 이상 전부, "
                        "high_views_outside=그중 스냅샷 밖(참고용), reference=latest100∪high_views∪downloaded")
    p.add_argument("--limit", type=int, default=None)


def register(p) -> None:
    sub = p.add_subparsers(dest="cmd", required=True) if isinstance(p, argparse.ArgumentParser) else p

    c = sub.add_parser("collect", help="채널 목록·최신 100편 스냅샷·고조회수 목록 수집(yt-dlp 또는 YouTube Data API)")
    c.add_argument("--preset", default=DEFAULT_PRESET)
    c.add_argument("--method", default="auto", choices=["auto", "ytdlp", "api"],
                   help="auto: YOUTUBE_API_KEY 가 있으면 api, 없으면 yt-dlp")
    c.add_argument("--refresh-snapshot", action="store_true", help="이미 고정된 ok 스냅샷을 새로 고정(기본: 유지)")
    c.add_argument("--cookies", default=None, help="yt-dlp 쿠키 파일(프로젝트 루트 기준, git 제외 파일)")
    c.add_argument("--max-meta", type=int, default=None, help="영상별 메타데이터 조회 최대 편수(시험용)")
    c.set_defaults(func=cmd_collect)

    d = sub.add_parser("download", help="레퍼런스 영상 받기(mp4 1080p 이하, 소리 포함) → reference/videos + downloads.jsonl")
    _sel(d)
    d.add_argument("--max-height", type=int, default=1080, help="짧은 변 기준 최대 해상도(세로 쇼츠 1080x1920 이면 1080)")
    d.add_argument("--cookies", default=None)
    d.set_defaults(func=cmd_download)

    a = sub.add_parser("analyze", help="컷·자막(위치/크기/색/외곽선/박스/모션/역할)·화면 모션 측정 → analysis/<id>/")
    _sel(a, default_set="downloaded")
    a.add_argument("--video", default=None, help="임의 파일 분석(예: 시험용 모의 레퍼런스). --id 필요")
    a.add_argument("--id", default=None)
    a.add_argument("--fps", type=float, default=5.0, help="자막 검출 표본 프레임률(4~10 권장)")
    a.add_argument("--only", default=None, help="shots,text,motion 중 일부")
    a.add_argument("--skip-existing", action="store_true")
    a.set_defaults(func=cmd_analyze)

    k = sub.add_parser("classify", help="포맷 분류: prepare(검토 자료·라벨 파일) / build(formats.yaml)")
    ks = k.add_subparsers(dest="classify_cmd", required=True)
    kp = ks.add_parser("prepare", help="영상별 검토 자료(1초 밀착 인화·자막 타임라인·컷·모션·오디오) + 라벨 파일 행 "
                                       "(기본: 최신 100편 스냅샷 — 포맷 표는 스냅샷 구성원만으로 만든다)")
    _sel(kp, default_set="latest100")
    kp.set_defaults(func=cmd_classify_prepare)
    kb = ks.add_parser("build", help="본 사람이 채운 라벨(format_labels.csv: intro_type, structure_type, beats=구간 목적 순서, "
                                     "reveal_t=반전 시각 초 또는 none, labeled_by, watched=yes)로 formats.yaml 생성 — 포맷별 "
                                     "대표 영상 + 정보 공개 순서(beats, reveal_frac p10/p50/p90). 라벨 없으면 못 잼 유지")
    kb.add_argument("--preset", default=DEFAULT_PRESET)
    kb.set_defaults(func=cmd_classify_build)

    g = sub.add_parser("aggregate", help="영상별 측정 → measurements/visual_*.json (전체·포맷별 n/p10/p50/p90). "
                                        "최신 100편 스냅샷 구성원만 사용(그 밖의 영상은 basis.excluded_non_snapshot 에 기록)")
    _sel(g, default_set=None)
    g.add_argument("--include-long", action="store_true", help="긴 영상(kind=video)도 포함(기본: 쇼츠만)")
    g.set_defaults(func=cmd_aggregate)

    mg = sub.add_parser("manual-aggregate",
                        help="영상을 본 사람의 관찰(manual_observations.csv: video_id,t,key,value,observed_by,watched,note; "
                             "watched=yes + observed_by 인 행만) + 자동 장식 검출 → measurements/manual.json "
                             "(장식·이모지·표지 키; px 는 레퍼런스 영상 자체 픽셀)")
    mg.add_argument("--preset", default=DEFAULT_PRESET)
    mg.add_argument("--include-long", action="store_true", help="긴 영상(kind=video) 관찰도 포함")
    mg.set_defaults(func=cmd_manual_aggregate)

    t = sub.add_parser("trace", help="레퍼런스 소재 출처 추적(설명란·자막 대본·화면 출처 OCR·렌즈용 키프레임·지문) → warehouse/. "
                                    "기본 대상 = latest100 ∪ high_views ∪ downloaded; 채널 전체 영상 주소는 항상 제외 목록에")
    _sel(t, default_set="reference")
    t.add_argument("--ocr-fps", type=float, default=0.5)
    t.add_argument("--no-ocr", action="store_true")
    t.add_argument("--no-lens", action="store_true")
    t.set_defaults(func=cmd_trace)

    it = sub.add_parser("identity-templates",
                        help="레퍼런스 채널 자체의 지속 표식(로고·워터마크·핸들)을 스냅샷 영상에서 추출 → "
                             "identity_exclusions.logo_templates_dir 의 템플릿 PNG + manifest.json (QA identity.logo_templates 가 "
                             "읽음). shortkit.clean.detect(저장 안 함) + forbidden_text OCR 일치 + 여러 영상 반복. 영상이 없으면 "
                             "못 잼 manifest(수집 차단 사유). 종료 코드 0=측정, 4=일부(사람 확인·누락), 3=레퍼런스 없음")
    _sel(it, default_set=None)
    it.add_argument("--include-long", action="store_true", help="긴 영상(kind=video)도 포함(기본: 쇼츠만)")
    it.add_argument("--no-ocr", action="store_true", help="OCR 없이(글자 표식·forbidden_text 확인은 못 잼으로 기록)")
    it.add_argument("--accept", default=None, metavar="ID",
                    help="사람 확인 후보(manifest review[].id)를 채널 식별 표식으로 확정(템플릿이 됨; 다시 스캔하지 않음)")
    it.add_argument("--reject", default=None, metavar="ID", help="사람 확인 후보를 식별 표식 아님(편집 스타일·장면 일부)으로 판정")
    it.add_argument("--by", default=None, help="후보 크롭을 실제로 본 사람(--accept/--reject 필수)")
    it.add_argument("--note", default=None)
    it.set_defaults(func=cmd_identity_templates)

    hv = sub.add_parser("high-views-report",
                        help="조회수 기준 이상 영상 전부의 분석 범위(받기·시각·오디오·추적)와 참고용 요약 → "
                             "reference/high_views_report.{json,md} (제작 측정과 섞지 않음)")
    hv.add_argument("--preset", default=DEFAULT_PRESET)
    hv.set_defaults(func=cmd_high_views_report)

    tr = sub.add_parser("transcribe", help="(선택) 음성 인식(faster-whisper 가 설치돼 있을 때만) → analysis/<id>/audio/"
                                           "transcript.json. 없으면 아무 파일도 쓰지 않고 못 잼으로 보고; 대본 추적은 자막(captions.json)을 씀")
    _sel(tr, default_set="reference")
    tr.add_argument("--model", default="small", help="faster-whisper 모델 이름(가중치는 미리 받아 둬야 함)")
    tr.add_argument("--language", default="ko")
    tr.add_argument("--force", action="store_true")
    tr.set_defaults(func=cmd_transcribe)

    for modname in ("typography", "audio_cli"):
        try:
            mod = __import__(f"shortkit.reference.{modname}", fromlist=["register"])
        except ImportError as e:
            print(f"[shortkit ref] {modname} 명령을 불러오지 못함: {e}", file=sys.stderr)
            continue
        mod.register(sub)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="shortkit ref")
    register(ap)
    ns = ap.parse_args()
    sys.exit(ns.func(ns))
