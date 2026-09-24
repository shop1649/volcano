"""`shortkit source ...` : new-source warehouse commands (Korean output)."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ..util.jsonio import now_iso
from . import download as dl
from . import exclusions, keywords, score, warehouse
from .platforms import ACCESS_KO, PLATFORMS

SORTS = ("views", "recent", "score", "seen")


def register(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search", help="플랫폼 검색 → 후보 창고에 기록(모든 검색은 search_log 에 남음)")
    s.add_argument("--query", "-q", action="append", default=[], help="검색어(여러 번 가능). TikTok 은 해시태그로 변환")
    s.add_argument("--from-queries", action="store_true", help="warehouse/queries.yaml 의 검색어 전부 실행")
    s.add_argument("--platform", nargs="+", default=["all"], choices=[*PLATFORMS, "all"])
    s.add_argument("--limit", type=int, default=10)
    s.add_argument("--recent", action="store_true", help="최근 게시물 위주(YouTube 날짜순, Reddit 새 글, 그 외 게시일로 거름)")
    s.add_argument("--note", default=None, help="검색 기록에 남길 메모(예: 접속 확인용)")
    s.set_defaults(func=cmd_search)

    ls = sub.add_parser("list", help="후보 목록(플랫폼별 확인된 조회수 순위, 조회수 모름은 뒤에 표시)")
    ls.add_argument("--platform", choices=[*PLATFORMS, "other"], default=None)
    ls.add_argument("--sort", choices=SORTS, default="views")
    ls.add_argument("--status", choices=warehouse.STATUSES, default=None)
    ls.add_argument("--limit", type=int, default=50)
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(func=cmd_list)

    sh = sub.add_parser("show", help="후보 한 건의 전체 기록")
    sh.add_argument("id")
    sh.set_defaults(func=cmd_show)

    rv = sub.add_parser("review", help="영상을 직접 본 사람의 검토 기록(강도·반전·형식 적합)")
    rv.add_argument("id")
    rv.add_argument("--watched-by", required=True, help="영상을 실제로 본 사람/에이전트 이름")
    rv.add_argument("--intensity", type=int, required=True, choices=range(1, 6), metavar="1-5")
    rv.add_argument("--reversal", type=int, required=True, choices=range(1, 6), metavar="1-5")
    rv.add_argument("--format-fit", type=int, required=True, choices=range(1, 6), metavar="1-5")
    rv.add_argument("--notes", required=True, help="본 내용(무슨 일이 몇 초에 일어나는지 등)")
    rv.add_argument("--watermark", choices=["present", "absent"], default=None, help="워터마크/출처 표기 확인 결과")
    rv.add_argument("--format-id", default=None, help="맞는 포맷(프리셋 formats.yaml 의 id)")
    rv.add_argument("--original-published-at", default=None,
                    help="재업로드일 때 확인한 원본 게시일(YYYY-MM-DD 또는 ISO) — 최근성은 이 날짜로 판정")
    rv.add_argument("--preset", default="joshuamagazine", help="포맷 표를 읽을 프리셋")
    rv.set_defaults(func=cmd_review)

    se = sub.add_parser("select", help="최종 선택(검토 기록 필수, 못 잼 항목은 --accept-unmeasured 로 명시해야 함)")
    se.add_argument("id")
    se.add_argument("--by", default="user")
    se.add_argument("--accept-unmeasured", default="",
                    help="알고도 선택할 못 잼 항목(쉼표): reference_overlap,recency,quality")
    se.add_argument("--reason", default=None, help="--accept-unmeasured 사유(필수)")
    se.set_defaults(func=cmd_select)

    us = sub.add_parser("use", help="선택된 후보를 에피소드에 사용함으로 기록(status used)")
    us.add_argument("id")
    us.add_argument("--episode", required=True)
    us.add_argument("--by", default="user")
    us.set_defaults(func=cmd_use)

    rj = sub.add_parser("reject", help="후보 탈락 처리")
    rj.add_argument("id")
    rj.add_argument("--reason", required=True)
    rj.add_argument("--by", default="user")
    rj.set_defaults(func=cmd_reject)

    d = sub.add_parser("download", help="yt-dlp 로 warehouse/sources/<platform>_<id>.mp4 다운로드 + sha256 + 중복 검사")
    d.add_argument("ids", nargs="*")
    d.add_argument("--selected", action="store_true", help="선택된 후보 전부")
    d.add_argument("--force", action="store_true")
    d.set_defaults(func=cmd_download)

    ec = sub.add_parser("exclude-check", help="레퍼런스 영상과 같은 녹화인지 검사(파일 경로 또는 후보 ID)")
    ec.add_argument("target", help="영상 파일 경로 또는 후보 ID")
    ec.add_argument("--url", action="append", default=[], help="URL 규칙도 함께 검사")
    ec.set_defaults(func=cmd_exclude_check)

    ea = sub.add_parser("exclude-add", help="제외 목록 추가(레퍼런스 영상 지문 또는 URL)")
    ea.add_argument("--ref-video", default=None, help="레퍼런스 영상 파일(지문 등록)")
    ea.add_argument("--ref-id", default=None)
    ea.add_argument("--ref-url", default=None)
    ea.add_argument("--original-url", action="append", default=[])
    ea.add_argument("--region", default=None, help="레퍼런스 화면 안의 소스 영상 영역 x,y,w,h (그 영상 해상도 기준 px)")
    ea.add_argument("--url", default=None, help="URL 규칙")
    ea.add_argument("--reason", default=None)
    ea.add_argument("--by", default="user")
    ea.set_defaults(func=cmd_exclude_add)

    au = sub.add_parser("add-url", help="URL 직접 입력(수동 수집). --file 로 직접 받은 파일도 연결")
    au.add_argument("url")
    au.add_argument("--file", default=None, help="사용자가 직접 확보한 영상 파일(창고로 복사됨)")
    au.add_argument("--keyword", action="append", default=[])
    au.add_argument("--note", default=None)
    au.set_defaults(func=cmd_add_url)

    lg = sub.add_parser("log", help="검색 기록(검색어·플랫폼·시각·결과 수·접속 상태)")
    lg.add_argument("--platform", default=None)
    lg.add_argument("--limit", type=int, default=30)
    lg.add_argument("--json", action="store_true")
    lg.set_defaults(func=cmd_log)

    q = sub.add_parser("queries", help="검색어 목록(레퍼런스 추적분/사용자 추가분) 보기·추가")
    q.add_argument("--add", default=None)
    q.add_argument("--platform", nargs="+", default=None, choices=PLATFORMS)
    q.add_argument("--by", default="user")
    q.add_argument("--note", default=None)
    q.set_defaults(func=cmd_queries)


# ----------------------------------------------------------------------------- helpers
def _views_txt(c: dict) -> str:
    if score.views_confirmed(c):
        return f"{c['views']:,} ({str(c.get('views_checked_at'))[:10]})"
    if c.get("reddit_score") is not None:
        return f"모름(Reddit 비공개; 점수 {c['reddit_score']}는 조회수 아님)"
    return "모름"


def _pub_txt(c: dict) -> str:
    r = score.recency_for(c)
    if r["age_days"] is None:
        return "게시일 모름"
    what = "원본 " if r.get("basis") == "original_published_at" else ""
    return f"{what}{str(r['published_at'])[:10]} ({r['age_days']:.0f}일, {r['label_ko']})"


def _overlap_txt(c: dict) -> str:
    ov = c.get("reference_overlap") or {}
    if ov.get("excluded") is True:
        return f"제외({ov.get('matched_video_id')})"
    if ov.get("excluded") is False:
        return "다른 녹화"
    return "못 잼"


def _review_txt(c: dict) -> str:
    r = score.review_of(c)
    if not r:
        return "없음"
    return f"{r['watched_by']}: 강{r['intensity']}/반{r['reversal']}/형{r['format_fit']}"


def _dur_txt(c: dict) -> str:
    d = c.get("duration")
    o = {"vertical": "세로", "horizontal": "가로", "square": "정사각"}.get(c.get("orientation") or "", "?")
    return f"{d:.0f}s·{o}" if isinstance(d, (int, float)) else f"?·{o}"


def _row(rank, c: dict, flags=()) -> str:
    acc = (c.get("access") or {}).get("platform_status")
    fl = (" [" + ",".join(flags) + "]") if flags else ""
    return (f"{rank if rank is not None else '-':>3}  {c['id']:<28} 조회 {_views_txt(c):<26} "
            f"좋아요 {c.get('likes') if c.get('likes') is not None else '-':<8} 게시 {_pub_txt(c):<24} "
            f"{_dur_txt(c):<9} 상태 {warehouse.STATUS_KO.get(c.get('status'), c.get('status'))}  "
            f"중복 {_overlap_txt(c)}  검토 {_review_txt(c)}  접속 {ACCESS_KO.get(acc, acc)}{fl}")


def _platforms(arg: list[str]) -> list[str]:
    return list(PLATFORMS) if "all" in arg else list(dict.fromkeys(arg))


# ----------------------------------------------------------------------------- commands
def cmd_search(args) -> int:
    plan: list[tuple[str, list[str]]] = [(q, _platforms(args.platform)) for q in args.query]
    if args.from_queries:
        ref = keywords.reference_derived()
        if ref["status"] != "measured":
            print(f"[레퍼런스 추적 검색어] {ref['label']}: {ref['note']}")
        for q in keywords.all_queries():
            pfs = [p for p in q["platforms"] if p in _platforms(args.platform)]
            if pfs:
                plan.append((q["query"], pfs))
    if not plan:
        print("검색어가 없습니다. --query 를 주거나 `shortkit source queries --add` 로 검색어를 추가하세요.")
        return 2
    any_ok = False
    for query, pfs in plan:
        rows = warehouse.run_search(query, pfs, limit=args.limit, recent_only=args.recent, note=args.note)
        for r in rows:
            st = r["access"]["platform_status"]
            any_ok |= st == "ok"
            print(f"[{r['platform']}] '{query}' → 접속: {ACCESS_KO.get(st, st)}, 결과 {r['result_count']}건 "
                  f"(신규 {r['new_count']}, 갱신 {r['updated_count']}, 항목 오류 {r['item_errors']})")
            if st != "ok":
                print(f"    오류 원문: {r['access']['note'][:300]}")
            for n in r.get("notes") or []:
                print(f"    참고: {n}")
    print(f"검색 기록: {warehouse.SEARCH_LOG}")
    return 0 if any_ok else 1


def cmd_list(args) -> int:
    cands = warehouse.load()
    if args.status:
        cands = [c for c in cands if c.get("status") == args.status]
    if args.platform:
        cands = [c for c in cands if c.get("platform") == args.platform]
    if not cands:
        print("후보 없음")
        return 0
    if args.sort == "views":
        rows = score.rank_by_views(cands)
        items = [(r["rank"], r["candidate"], r["flags"]) for r in rows]
    elif args.sort == "recent":
        def _age(c):
            r = score.recency_for(c)
            a = r["age_days"] if r["label"] != "unknown" else None
            return (a is None, a if a is not None else 0.0)
        items = [(None, c, []) for c in sorted(cands, key=_age)]
    elif args.sort == "score":
        ranked = score.rank_for_selection(cands)
        rest = [c for c in cands if c not in [x[0] for x in ranked]]
        items = [(i, c, [f"종합 {s['total']}" if s["total"] is not None else "종합 못 잼"])
                 for i, (c, s) in enumerate(ranked, 1)] + [(None, c, ["검토 없음/제외"]) for c in rest]
    else:
        items = [(None, c, []) for c in sorted(cands, key=lambda c: c.get("first_seen_at") or "")]
    items = items[: args.limit]
    if args.json:
        print(json.dumps([{"rank": r, "id": c["id"], "flags": f, "views": c.get("views"),
                           "views_checked_at": c.get("views_checked_at"), "status": c.get("status")}
                          for r, c, f in items], ensure_ascii=False, indent=1))
        return 0
    pf = None
    for rank, c, flags in items:
        if args.sort == "views" and c.get("platform") != pf:
            pf = c.get("platform")
            print(f"\n== {pf} (확인된 조회수 순위; 조회수 모름은 순위 없이 뒤에) ==")
        print(_row(rank, c, flags))
    return 0


def cmd_show(args) -> int:
    try:
        c = warehouse.get(args.id)
    except KeyError as e:
        print(e.args[0])
        return 1
    print(json.dumps(c, ensure_ascii=False, indent=1))
    return 0


def cmd_review(args) -> int:
    try:
        c = warehouse.get(args.id)
    except KeyError as e:
        print(e.args[0])
        return 1
    r = {"watched_by": args.watched_by.strip(), "watched_at": now_iso(), "intensity": args.intensity,
         "reversal": args.reversal, "format_fit": args.format_fit, "notes": args.notes.strip(),
         "watermark": args.watermark, "format_id": args.format_id,
         "watched_file_sha256": c.get("sha256")}
    probs = score.validate_review(r)
    if args.original_published_at and score.parse_time(args.original_published_at) is None:
        probs.append("--original-published-at 날짜 형식 오류")
    if args.format_id:
        ids, note = score.known_format_ids(args.preset)
        r["format_id_check"] = note
        if ids is not None and args.format_id not in ids:
            probs.append(f"포맷 id '{args.format_id}' 가 포맷 표에 없음({', '.join(sorted(ids))})")
    if probs:
        print("검토 기록 거부: " + ", ".join(probs))
        return 1
    if args.original_published_at:
        r["original_published_at"] = args.original_published_at
        c["original_published_at"] = args.original_published_at
        c["original_published_at_source"] = f"review:{r['watched_by']}"
    c.setdefault("reviews", []).append(r)
    warehouse.refresh_scores(c)
    warehouse.put(c)
    print(f"{c['id']}: 검토 기록 저장 (본 사람 {r['watched_by']}, 강도 {r['intensity']}, 반전 {r['reversal']}, "
          f"형식 적합 {r['format_fit']})")
    if r.get("format_id_check"):
        print(f"  포맷 id: {r['format_id_check']}")
    if not c.get("sha256"):
        print("  참고: 창고에 파일이 없음(다운로드 전) — 어디서 봤는지 notes 에 적어 두세요.")
    return 0


def select_candidate(cid: str, *, by: str = "user", accept: list[str] | None = None,
                     reason: str | None = None) -> tuple[bool, dict, list[str]]:
    """Backward-compatible alias of :func:`warehouse.select`."""
    return warehouse.select(cid, by=by, accept=accept, reason=reason)


def cmd_select(args) -> int:
    try:
        ok, c, msgs = select_candidate(args.id, by=args.by, accept=args.accept_unmeasured.split(","),
                                       reason=args.reason)
    except KeyError as e:
        print(e.args[0])
        return 1
    for m in msgs:
        print(m)
    return 0 if ok else 1


def cmd_use(args) -> int:
    try:
        c = warehouse.mark_used(args.id, args.episode, by=args.by)
    except KeyError as e:
        print(e.args[0])
        return 1
    except warehouse.SelectionError as e:
        print(f"거부: {e}")
        return 1
    print(f"{c['id']}: 사용함 → {', '.join(c['used_in'])} (plan.yaml sources[]: path={c.get('download_path')}, "
          f"sha256={c.get('sha256')}, warehouse_id={c['id']})")
    return 0


def cmd_reject(args) -> int:
    try:
        c = warehouse.get(args.id)
    except KeyError as e:
        print(e.args[0])
        return 1
    warehouse.set_status(c, "rejected", args.by, args.reason)
    warehouse.put(c)
    print(f"{c['id']} 탈락 처리: {args.reason}")
    return 0


def cmd_download(args) -> int:
    ids = list(args.ids)
    if args.selected:
        ids += [c["id"] for c in warehouse.load() if c.get("status") == "selected" and c["id"] not in ids]
    if not ids:
        print("받을 후보가 없습니다(ID 또는 --selected).")
        return 2
    res = dl.download_many(ids, force=args.force)
    n_ok = 0
    for r in res:
        if r["ok"]:
            n_ok += 1
            ex = {True: " — 레퍼런스와 같은 녹화로 판정되어 제외됨", False: "", None: " — 레퍼런스 중복 못 잼"}.get(
                r.get("excluded"), "")
            print(f"[성공] {r['id']}: {r.get('path')} sha256={str(r.get('sha256'))[:16]}…{ex}")
        else:
            st = r.get("status")
            print(f"[실패] {r['id']}: {ACCESS_KO.get(st, st)} — {str(r.get('error'))[:300]}")
    print(f"다운로드 {n_ok}/{len(res)} 성공")
    return 0 if n_ok == len(res) else 1


def _print_check(res: dict) -> None:
    ex = res.get("excluded")
    head = {True: "제외 대상(레퍼런스와 같은 녹화/URL)", False: "레퍼런스와 다른 녹화", None: "못 잼"}[ex]
    print(f"판정: {head}")
    print(f"  방법: {res.get('method')}  일치 레퍼런스: {res.get('matched_ref_video_id')}  거리: {res.get('distance')}  "
          f"일치 키프레임: {res.get('matched_keyframes')}/{res.get('n_keyframes')}")
    if res.get("note"):
        print(f"  메모: {res['note']}")


def cmd_exclude_check(args) -> int:
    target = args.target
    rec = None
    try:
        rec = warehouse.get(target)
    except KeyError:
        pass
    if rec is not None:
        res = exclusions.check(rec, urls=args.url)
        warehouse.apply_overlap(rec, res, by="cli:exclude-check")
        warehouse.refresh_scores(rec)
        warehouse.put(rec)
        print(f"후보 {rec['id']} (파일 {rec.get('download_path') or '없음'})")
    else:
        p = Path(target)
        if not p.is_file():
            print(f"파일도 후보 ID 도 아님: {target}")
            return 2
        res = exclusions.check(None, video_path=p.resolve(), urls=args.url)
    _print_check(res)
    return 0 if res.get("excluded") is False else (3 if res.get("excluded") else 4)


def cmd_exclude_add(args) -> int:
    if args.ref_video:
        if not args.ref_id:
            print("--ref-id 가 필요합니다")
            return 2
        region = None
        if args.region:
            try:
                x, y, w, h = (float(v) for v in args.region.split(","))
            except ValueError:
                print("--region 은 x,y,w,h 형식")
                return 2
            region = {"x": x, "y": y, "w": w, "h": h}
        e = exclusions.add_reference_footage(Path(args.ref_video).resolve(), args.ref_id, ref_url=args.ref_url,
                                             original_urls=args.original_url, added_by=args.by, region=region)
        print(f"레퍼런스 지문 등록: {args.ref_id} 키프레임 {len(e['phash'])}장 → {exclusions.EXCLUSIONS}")
        return 0
    if args.url:
        exclusions.add_url(args.url, args.reason or "사용자 지정", args.by)
        print(f"URL 규칙 등록: {args.url}")
        return 0
    print("--ref-video 또는 --url 중 하나가 필요합니다")
    return 2


def cmd_add_url(args) -> int:
    rec, row = warehouse.intake_url(args.url, keywords=args.keyword, note=args.note)
    st = row["access"]["platform_status"]
    print(f"{rec['id']}: 메타데이터 접속 {ACCESS_KO.get(st, st)} (조회수 {_views_txt(rec)})")
    if st != "ok":
        print(f"    오류 원문: {row['access']['note'][:300]}")
    if args.file:
        rec = dl.attach_local_file(rec["id"], args.file, note=args.note)
        print(f"  파일 연결: {rec['download_path']} sha256={rec['sha256'][:16]}…")
        _print_check({**rec["reference_overlap"], "matched_ref_video_id": rec["reference_overlap"].get("matched_video_id")})
    return 0


def cmd_log(args) -> int:
    rows = warehouse.read_log(args.platform)[-args.limit:]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=1))
        return 0
    if not rows:
        print("검색 기록 없음")
        return 0
    for r in rows:
        st = (r.get("access") or {}).get("platform_status")
        print(f"{r.get('at')}  {r.get('platform'):<9} {r.get('kind', 'search'):<13} '{r.get('query')}'  "
              f"결과 {r.get('result_count')}건  접속 {ACCESS_KO.get(st, st)}"
              + (f"  메모: {r['note']}" if r.get("note") else ""))
        if st != "ok":
            print(f"      {str((r.get('access') or {}).get('note'))[:200]}")
    return 0


def cmd_queries(args) -> int:
    if args.add:
        e = keywords.add_user_query(args.add, args.platform, added_by=args.by, note=args.note)
        print(f"사용자 검색어 추가: {e['query']} ({', '.join(e['platforms'])})")
    ref = keywords.reference_derived()
    print(f"[레퍼런스 추적 검색어/계정] {ref['label']} — {ref['note']}")
    for q in ref["queries"] + ref["accounts"]:
        print(f"   - {q['query']}  ({', '.join(q['platforms'])}, 근거 {len(q.get('evidence') or [])}건)")
    uq = keywords.user_queries()
    print(f"[사용자 검색어] {len(uq)}개")
    for q in uq:
        print(f"   - {q['query']}  ({', '.join(q['platforms'])})")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    register(ap)
    a = ap.parse_args()
    sys.exit(a.func(a))
