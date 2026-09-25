"""`shortkit qa ...` — output QA on the final MP4."""
from __future__ import annotations

import argparse
import sys


def register(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="최종 MP4 측정 → report.json/report.md/비교 시트/관문/결함 재확인")
    r.add_argument("--episode", required=True)
    r.add_argument("--reference", default=None,
                   help="같은 시각 비교용 레퍼런스 MP4 (프로젝트 안의 경로). 기본 = formats.yaml 에서 이 포맷의 대표 영상")
    r.add_argument("--reference-id", default=None, help="레퍼런스 영상 id (analysis/<id>/ 사용; 기본=파일 이름)")
    r.add_argument("--reference-override-reason", default=None,
                   help="포맷 대표 영상이 아닌 레퍼런스를 쓰는 이유(production 관문 R1 이 요구; 보고서에 기록)")
    r.add_argument("--sheet-seconds", type=float, default=15.0, help="비교 시트 한 장당 초(기본 15)")
    r.add_argument("--mp4", default=None,
                   help="다른 MP4 를 검사(기본: resolved.json 의 output_path = 납품 파일). 납품 파일이 아니면 결과는 "
                        "qa/other_mp4/<이름>/ 에 쓰이고 에피소드 보고서·결함·최종 관문에는 쓰이지 않음")
    r.add_argument("--no-recheck-others", action="store_true", help="다른 에피소드의 같은 검사 재확인을 건너뜀")
    r.set_defaults(func=cmd_run)

    g = sub.add_parser("gate", help="저장된 보고서 + 현재 MP4 + 현재 프리셋으로 최종 관문 판정")
    g.add_argument("--episode", required=True)
    g.add_argument("--production", action="store_true", help="production 규칙 강제(미측정 키 = 완료 아님)")
    g.set_defaults(func=cmd_gate)

    s = sub.add_parser("sheet", help="비교 시트만 다시 그림(저장된 probes 사용)")
    s.add_argument("--episode", required=True)
    s.add_argument("--reference", default=None)
    s.add_argument("--reference-id", default=None)
    s.add_argument("--sheet-seconds", type=float, default=15.0)
    s.set_defaults(func=cmd_sheet)

    d = sub.add_parser("defects", help="결함 기록 보기·수정 메모·재확인")
    dsub = d.add_subparsers(dest="dcmd", required=True)
    dl = dsub.add_parser("list")
    dl.add_argument("--episode", required=True)
    dl.add_argument("--all", action="store_true", help="해결된 결함도 표시")
    dl.set_defaults(func=cmd_defects_list)
    df = dsub.add_parser("fix", help="수정 내용 기록(다음 qa run 에서 자동 재측정)")
    df.add_argument("--episode", required=True)
    df.add_argument("--id", required=True)
    df.add_argument("--note", required=True)
    df.add_argument("--by", default=None)
    df.set_defaults(func=cmd_defects_fix)
    dr = dsub.add_parser("recheck", help="qa run 을 다시 실행해 열린 결함과 다른 에피소드의 같은 검사를 재확인")
    dr.add_argument("--episode", required=True)
    dr.add_argument("--reference", default=None)
    dr.add_argument("--sheet-seconds", type=float, default=15.0)
    dr.set_defaults(func=cmd_defects_recheck)

    c = sub.add_parser("checks", help="검사 id → 검증하는 프리셋 키 목록")
    c.set_defaults(func=cmd_checks)

    h = sub.add_parser("human-check", help="사람이 최종 MP4 를 직접 듣거나 보고 내린 판정 기록(에이전트는 사용 금지)")
    h.add_argument("--episode", required=True)
    h.add_argument("--row", required=True, help="검사 행 id (예: audio.original:music0, audio.sfx.on_cut:fx1)")
    h.add_argument("--kind", required=True, choices=["listen", "watch"])
    h.add_argument("--verdict", required=True, choices=["same", "different"])
    h.add_argument("--by", required=True, help="직접 듣거나 본 사람")
    h.add_argument("--note", required=True, help="무엇을 듣고/보고 그렇게 판단했는지")
    h.set_defaults(func=cmd_human_check)


def _print_summary(rep: dict) -> None:
    s = rep["summary"]
    g = rep["gate"]
    print(f"[qa] {rep['episode_id']}: 같다 {s['same']} / 다르다 {s['different']} (의도한 변경 {s['intended_change']}) / "
          f"못 잼 {s['unmeasured']}  (총 {s['total']}행)")
    for cat, d in s["by_category"].items():
        print(f"     {cat}: 같다 {d['same']} 다르다 {d['different']} 못 잼 {d['unmeasured']}")
    print(f"[qa] 최종 관문: {g['verdict_ko']}")
    for f in g["failures"]:
        rows = f.get("rows") or []
        print(f"     ✗ {f['rule']} {f['message']}" + (f": {', '.join(map(str, rows[:6]))}{' …' if len(rows) > 6 else ''}" if rows else ""))
    for w in g["warnings"]:
        print(f"     △ {w['rule']} {w['message']}")
    d = rep.get("defects") or {}
    if d and "error" not in d:
        print(f"[qa] 결함: 열림 {d.get('open')} / 새로 {d.get('new')} / 고침 확인 {d.get('verified_now')} / 재발 {d.get('reopened')} / "
              f"고침 기록 필요 {d.get('needs_record')}")
    elif d:
        print(f"[qa] 결함 기록 실패: {d['error']}")
    print(f"[qa] 보고서: episodes/{rep['episode_id']}/qa/report.md, 시트: {', '.join(rep.get('sheets') or []) or '없음'}")


def cmd_run(args) -> int:
    from . import QAError
    from .report import run_and_write

    try:
        rep = run_and_write(args.episode, reference=args.reference, sheet_seconds=args.sheet_seconds, mp4=args.mp4,
                            reference_id=args.reference_id, recheck_others=not args.no_recheck_others,
                            reference_override_reason=getattr(args, "reference_override_reason", None))
    except QAError as e:
        print(f"[qa] 시작할 수 없음: {e}", file=sys.stderr)
        return 2
    _print_summary(rep)
    return 0 if rep["gate"]["pass"] else 1


def cmd_gate(args) -> int:
    from .gate import gate_episode

    g = gate_episode(args.episode, production=True if args.production else None)
    print(f"[qa] 최종 관문({args.episode}): {g['verdict_ko']}")
    for f in g["failures"]:
        rows = f.get("rows") or []
        print(f"   ✗ {f['rule']} {f['message']}" + (f": {', '.join(map(str, rows[:8]))}" if rows else ""))
    for w in g.get("warnings", []):
        print(f"   △ {w['rule']} {w['message']}")
    return 0 if g["pass"] else 1


def cmd_sheet(args) -> int:
    from .. import paths
    from ..util.jsonio import read_json
    from . import load_context
    from .sheet import make_sheets

    ctx = load_context(args.episode, reference=args.reference, reference_id=args.reference_id)
    pdir = paths.episode_dir(args.episode) / "qa" / "probes"
    text = read_json(pdir / "text.json")
    audio = read_json(pdir / "audio.json")
    if text is None or audio is None:
        print("[qa] 저장된 측정(probes)이 없어 자막/효과음 줄은 계획 시각('?') 또는 '못 잼'으로 표시됩니다. "
              "먼저 `shortkit qa run` 을 권장합니다.")
    files = make_sheets(ctx, text, audio, args.sheet_seconds)
    print("\n".join(files))
    return 0


def cmd_defects_list(args) -> int:
    from .defects import ACTIVE, NEEDS_RECORD, load

    items = load(args.episode)
    shown = [d for d in items if args.all or d["status"] in ACTIVE + NEEDS_RECORD]
    if not shown:
        print(f"[qa] {args.episode}: 열린 결함 없음 (전체 {len(items)}건)")
        return 0
    for d in shown:
        print(f"{d['id']} [{d['status']}] {d['check_id']} — {d['description'][:160]}")
        if d.get("fix"):
            print(f"     수정 메모: {d['fix']}")
        for rc in d.get("recheck_same_cases", [])[-3:]:
            print(f"     다른 에피소드 재확인: {rc.get('episode_id')} → {rc.get('verdict')}")
        fg = d.get("final_gate") or {}
        print(f"     최종 관문: {'통과' if fg.get('pass') else '불합격'} ({fg.get('checked_at')})")
    return 0


def cmd_defects_fix(args) -> int:
    from .defects import add_fix

    d = add_fix(args.episode, args.id, args.note, args.by)
    print(f"[qa] {d['id']} → {d['status']} (다음 `shortkit qa run --episode {args.episode}` 에서 자동 재측정)")
    return 0


def cmd_defects_recheck(args) -> int:
    ns = argparse.Namespace(episode=args.episode, reference=args.reference, sheet_seconds=args.sheet_seconds, mp4=None,
                            reference_id=None, no_recheck_others=False, reference_override_reason=None)
    return cmd_run(ns)


def cmd_human_check(args) -> int:
    """Record a person's listening / watching verdict for one row, bound to the deliverable's sha256."""
    from .. import paths
    from ..util.hashing import sha256_file
    from ..util.jsonio import read_json
    from .human import record

    rj = read_json(paths.episode_dir(args.episode) / "build" / "resolved.json") or {}
    mp4 = paths.absp(rj.get("output_path") or f"episodes/{args.episode}/output/{args.episode}.mp4")
    if not mp4.is_file():
        print(f"[qa] 출력 MP4 없음: {paths.relp(mp4)}", file=sys.stderr)
        return 2
    try:
        rec = record(args.episode, args.row, args.kind, args.verdict, args.by, args.note, sha256_file(mp4))
    except ValueError as e:
        print(f"[qa] 기록 못 함: {e}", file=sys.stderr)
        return 2
    print(f"[qa] 사람 {'청취' if args.kind == 'listen' else '시청'} 기록: {rec['row_id']} → {rec['verdict']} ({rec['by']}, "
          f"MP4 sha256 {rec['mp4_sha256'][:12]}…) — 다음 `shortkit qa run` 에서 반영")
    return 0


def cmd_checks(args) -> int:
    from .checks import declarations

    for cid, pats in declarations().items():
        print(f"{cid}: {', '.join(pats) if pats else '(프리셋 키 없음 — 계획 대비 검사)'}")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    register(ap)
    a = ap.parse_args()
    sys.exit(a.func(a))
