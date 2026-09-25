"""`shortkit ref <audio command>`: reference audio analysis sub-commands.

    ref separate       Demucs 분리(레퍼런스 영상 stem 캐시) / --source: 소재 원본의 음악 제거 + 품질 검사
    ref bgm-identify   깨끗한 음원 라이브러리에서 BGM 곡·버전·속도·사용 구간·레벨 식별 -> audio/bgm.json
    ref bgm-align      임의의 레퍼런스 오디오와 깨끗한 음원 파일 하나를 정렬(속도·시작 지점·게인)
    ref original       원음(대사) 유무·BGM 덕킹·의도적 정적 -> audio/original.json
    ref sfx-events     효과음 이벤트 추출(BGM·보컬 제거 잔여 + 믹스 대조) -> audio/sfx_events.json
    ref sfx-catalog    최신 N편 효과음 카탈로그 -> sfx_catalog.json
    ref sfx-map        카탈로그 종류 ↔ 사용자 효과음 창고 매칭 -> sfx_map.yaml
    ref audio-analyze  위 영상별 단계를 순서대로(separate → bgm → original → sfx-events → loudness);
                       --set latest100 (제작 측정 기준) | high_views (참고 보고서) | ..., --all = 카탈로그용 최신 N편
    ref audio-measure  영상별 결과를 measurements/audio.json 으로 집계(audio.loudness.*, audio.bgm.* 반복 포함,
                       audio.ducking.*, audio.original.keep_gain_db/fade_s, audio.silence.fade_s,
                       audio.sfx.gain_db_default)

`register(subparsers)` is called by ``shortkit/reference/cli.py``; this module can also run on its
own: ``python -m shortkit.reference.audio_cli <command> ...``.
"""
from __future__ import annotations

import argparse
import sys

from ..util.jsonio import write_json
from ..util.stats import TRI_KO
from .separation import DEFAULT_PRESET

STATUS_KO = {"measured": "측정됨", "unmeasured": "못 잼", "ambiguous": "구간 모호(후보 여럿)",
             "have": "있음", "none": "없음"}


def _ko(s) -> str:
    return TRI_KO.get(s) or STATUS_KO.get(s) or str(s)


def register(sub) -> None:
    """Add the audio commands to the `ref` sub-parsers object."""
    p = sub.add_parser("separate", help="Demucs 음원 분리(레퍼런스 stem 캐시) / --source 소재 원본 음악 제거+품질 검사")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--video", help="레퍼런스 video_id")
    g.add_argument("--source", help="새 소재 파일(원본에 섞인 음악 제거)")
    p.add_argument("--audio", help="레퍼런스 원본 파일 경로(생략 시 reference/videos 에서 찾음)")
    p.add_argument("--model", default="htdemucs")
    p.add_argument("--two-stems", action="store_true", help="vocals / no_vocals 두 갈래로만 분리")
    p.add_argument("--force", action="store_true")
    p.add_argument("--music-ref", help="--source: 품질 검사용 깨끗한 음악 파일(있으면)")
    p.add_argument("--preset", default=DEFAULT_PRESET)
    p.set_defaults(func=cmd_separate)

    p = sub.add_parser("bgm-identify", help="BGM 곡·버전·속도·사용 구간 식별 -> analysis/<id>/audio/bgm.json")
    _video_args(p)
    p.add_argument("--online", action="store_true", help="shazamio 가 설치돼 있으면 힌트용 온라인 인식(미검증)")
    p.set_defaults(func=cmd_bgm_identify)

    p = sub.add_parser("bgm-align", help="레퍼런스 오디오와 깨끗한 음원 1개 정렬(속도 0.85~1.15, 시작 지점, 게인)")
    p.add_argument("--ref", required=True, help="레퍼런스 오디오/영상 파일")
    p.add_argument("--clean", required=True, help="깨끗한 음원 파일")
    p.add_argument("--out", help="결과 JSON 저장 경로")
    p.set_defaults(func=cmd_bgm_align)

    p = sub.add_parser("original", help="원음/대사 유무·덕킹·의도적 정적 -> analysis/<id>/audio/original.json")
    _video_args(p)
    p.set_defaults(func=cmd_original)

    p = sub.add_parser("sfx-events", help="효과음 이벤트 추출 -> analysis/<id>/audio/sfx_events.json")
    _video_args(p)
    p.set_defaults(func=cmd_sfx_events)

    p = sub.add_parser("sfx-catalog", help="최신 N편 효과음 카탈로그 -> sfx_catalog.json")
    p.add_argument("--preset", default=DEFAULT_PRESET)
    p.add_argument("--videos", help="쉼표로 구분한 video_id 목록(생략 시 스냅샷 최신 N편)")
    p.add_argument("--latest-n", type=int, default=None, help="기본: preset reference.sfx_catalog_latest_n")
    p.add_argument("--emotion-template", action="store_true",
                   help="영상을 본 사람이 채울 감정 라벨 템플릿 CSV 도 씀(sfx_emotion_labels.template.csv)")
    p.set_defaults(func=cmd_sfx_catalog)

    p = sub.add_parser("sfx-map", help="카탈로그 종류 ↔ 효과음 창고 매칭 -> sfx_map.yaml")
    p.add_argument("--preset", default=DEFAULT_PRESET)
    p.add_argument("--threshold", type=float, default=None, help="유사도 기준(기본 0.80)")
    p.set_defaults(func=cmd_sfx_map)

    p = sub.add_parser("audio-measure", help="영상별 음량/bgm/original/효과음 결과 -> measurements/audio.json (프리셋 audio.* "
                                             "측정값 + presence.bgm/original_audio/ducking/intentional_silence). 최신 100편 "
                                             "스냅샷 구성원만(그 밖은 basis.excluded_non_snapshot)")
    p.add_argument("--preset", default=DEFAULT_PRESET)
    p.add_argument("--videos", help="쉼표로 구분한 video_id 목록(생략 시 분석·다운로드된 스냅샷 영상 전부; 스냅샷 밖 id 는 제외)")
    p.set_defaults(func=cmd_audio_measure)

    p = sub.add_parser("audio-analyze", help="영상별 오디오 분석 일괄: separate → bgm-identify → original → sfx-events → 음량")
    _video_args(p, allow_all=True)
    p.add_argument("--no-separate", action="store_true", help="분리 시도 생략(캐시만 사용)")
    p.set_defaults(func=cmd_audio_analyze)


def _video_args(p: argparse.ArgumentParser, allow_all: bool = False) -> None:
    if allow_all:
        from .common import SET_NAMES

        g = p.add_mutually_exclusive_group(required=True)
        g.add_argument("--video")
        g.add_argument("--set", choices=list(SET_NAMES),
                       help="영상 묶음: latest100(제작 측정 기준 = BGM·원음·덕킹·음량) / high_views(조회수 기준 이상 전부, "
                            "참고 보고서) / reference / downloaded ...")
        g.add_argument("--all", action="store_true",
                       help="효과음 카탈로그 기준 = 스냅샷 최신 N편(sfx_catalog_latest_n)만. BGM·원음 측정은 --set latest100")
    else:
        p.add_argument("--video", required=True)
    p.add_argument("--audio", help="레퍼런스 원본 파일 경로(생략 시 reference/videos 에서 찾음)")
    p.add_argument("--preset", default=DEFAULT_PRESET)


# ============================================================================ commands
def cmd_separate(a) -> int:
    from .separation import DemucsSeparator, SeparationUnavailable, separate_reference, separate_vocals_for_source

    sep = DemucsSeparator(a.model)
    if a.source:
        rec = separate_vocals_for_source(a.source, separator=sep, music_ref=a.music_ref)
        if rec["status"] != "measured":
            print(f"[분리] 못 잼: {rec['blocker']}")
            return 3
        q = rec["quality"] or {}
        print(f"[분리] vocals -> {rec['vocals']}  품질 검사: {'통과' if q.get('passed') else '불통과'} "
              f"(누설 {q.get('music_leak_db')} dB, 음악 상관 {q.get('residual_music_corr')}) — 청취 확인은 하지 않음")
        return 0 if q.get("passed") else 4
    try:
        st = separate_reference(a.preset, a.video, audio_path=a.audio, separator=sep, two_stems=a.two_stems,
                                force=a.force)
    except SeparationUnavailable as e:
        print(f"[분리] {a.video}: 못 잼 — {e.reason}")
        print("  → stem 이 필요한 측정(대사 겹친 효과음, 보컬 기반 대사 구간)은 '못 잼' 또는 대체 방법으로 표시됩니다.")
        return 3
    print(f"[분리] {a.video}: {st.model} ({st.model_version}) {st.mode} -> {', '.join(st.files.values())}")
    return 0


def cmd_bgm_identify(a) -> int:
    from .audio_bgm import analyze_bgm

    r = analyze_bgm(a.preset, a.video, audio_path=a.audio, online=a.online)
    _print_bgm(r)
    return 0


def _print_bgm(r: dict) -> None:
    print(f"[BGM] {r['video_id']}: 상태 {_ko(r['status'])}, BGM {_ko(r.get('presence'))}")
    if r.get("blocker"):
        print(f"  사유: {r['blocker']}")
    m = r.get("match")
    if m:
        f = lambda k: m[k]["value"]  # noqa: E731
        print(f"  곡 {f('track_id')} / 제목 {f('title')} / 버전 {f('version')} ({_ko(m['version']['status'])})")
        print(f"  속도 x{f('tempo_ratio')}  사용 구간 시작 {f('section_start_s')} s ({_ko(m['section_start_s']['status'])})"
              f"  사용 범위(레퍼런스) {f('used_range_ref_s')}  게인 {f('gain_db')} dB")
        print(f"  페이드 in {f('fade_in_s')} s / out {f('fade_out_s')} s, 끊김 {len(f('cuts'))}회, "
              f"정렬 {m['alignment']['mode']} (일치도 {m['alignment']['coherence']})")
        lp = m.get("loop") or {}
        jumps = ", ".join(f"{j['t']:.2f}s {'되감김' if j['kind'] == 'restart' else '건너뜀'} {j['jump_s']:+.1f}s"
                          for j in lp.get("jumps") or [])
        print(f"  BGM 되감김(반복) {_ko(lp.get('presence', 'unmeasured'))}" + (f": {jumps}" if jumps else ""))


def cmd_bgm_align(a) -> int:
    from .audio_bgm import align_files

    d = align_files(a.ref, a.clean)
    if a.out:
        write_json(a.out, d)
    print(f"[정렬] 속도 x{d['tempo_ratio']:.4f}  시작 {d['offset_s']:.3f} s  모드 {d['mode']}  "
          f"특징 NCC {d['feature_ncc']:.3f}  일치도 {d['coherence']}  구간 모호 {d['ambiguous']}")
    if d.get("present"):
        print(f"  게인 {d.get('base_db')} dB, 사용 범위 {d.get('used_start')}~{d.get('used_end')} s, "
              f"페이드 in {d.get('fade_in_s')} / out {d.get('fade_out_s')} s, 끊김 {d.get('cuts')}")
    return 0


def cmd_original(a) -> int:
    from .audio_original import analyze_original

    r = analyze_original(a.preset, a.video, audio_path=a.audio)
    _print_original(r)
    return 0


def _print_original(r: dict) -> None:
    sp, dk = r.get("speech") or {}, r.get("ducking") or {}
    print(f"[원음] {r['video_id']}: 대사 {_ko(sp.get('presence'))} (방법: {sp.get('method') or '-'}), "
          f"원음 {_ko((r.get('original_audio') or {}).get('presence'))}")
    if r.get("blocker"):
        print(f"  사유: {r['blocker']}")
    d = dk.get("depth_db") or {}
    print(f"  덕킹 {_ko(dk.get('presence'))}" + (f": 깊이 p50 {d.get('p50')} dB (n={d.get('n')}), "
                                                f"attack p50 {(dk.get('attack_s') or {}).get('p50')} s, "
                                                f"release p50 {(dk.get('release_s') or {}).get('p50')} s"
                                                if d.get("n") else f" — {dk.get('blocker') or r.get('blocker')}"))
    sil = (r.get("silences") or {}).get("items") or []
    ramps = [f"{side} {x['fade_s']:.3f}s" for s in sil for side, x in (s.get("ramps") or {}).items()
             if isinstance(x, dict) and x.get("status") == "measured"]
    print(f"  정적 {len(sil)}개 (BGM 끊김 확인 {sum(1 for s in sil if s.get('bgm_cut'))}개)"
          + (f", 경사(렌더러 fade_s) {', '.join(ramps)}" if ramps else ""))
    oe = r.get("original_edges") or {}
    fades = [f"{e['edge']} {e['t']:.2f}s {e['fade_s']:.3f}s" for e in oe.get("edges") or [] if e.get("status") == "measured"]
    print("  원음 켜짐/꺼짐 경사: " + (", ".join(fades) if fades else f"못 잼 — {oe.get('blocker')}"))
    kl = r.get("kept_speech_level") or {}
    print("  살린 대사 음량(프로그램 대비): " + (f"{kl['rel_program_lu']:+.1f} LU" if kl.get("status") == "measured"
                                              else f"못 잼 — {kl.get('blocker')}"))


def cmd_sfx_events(a) -> int:
    from .sfx_events import analyze_sfx_events

    r = analyze_sfx_events(a.preset, a.video, audio_path=a.audio)
    _print_sfx(r)
    return 0


def _print_sfx(r: dict) -> None:
    if r["status"] not in ("measured", "partial"):
        print(f"[효과음] {r['video_id']}: 못 잼 — {r.get('blocker')}")
        return
    if r["status"] == "partial":
        print(f"[효과음] {r['video_id']}: 일부만 측정(대사 구간 못 잼) — {r.get('blocker')}")
    ev = r["events"]
    n_sfx = sum(1 for e in ev if e.get("class") != "intentional_silence")
    print(f"[효과음] {r['video_id']}: 이벤트 {n_sfx}개, 의도적 정적 {len(ev) - n_sfx}개, 믹스 대조 탈락 {len(r['rejected'])}개")
    print(f"  잔여 신호: {r['residual_method']}")
    for lim in r.get("limitations") or []:
        print(f"  한계: {lim}")


def cmd_sfx_catalog(a) -> int:
    from .sfx_catalog import build_catalog, write_emotion_template

    vids = [v.strip() for v in a.videos.split(",") if v.strip()] if a.videos else None
    c = build_catalog(a.preset, video_ids=vids, latest_n=a.latest_n)
    b = c["basis"]
    print(f"[카탈로그] 상태 {_ko(c['status'])}  분석 영상 {b['n_videos']}/{b['target_n']}  종류 {len(c['types'])}개")
    if c.get("blocker"):
        print(f"  사유: {c['blocker']}")
    for t in c["types"]:
        print(f"  {t['type_id']:<12} {t['class']:<20} {t['n_events']}회/{t['n_videos']}편  {t['label']}")
    if a.emotion_template and c["types"]:
        p = write_emotion_template(a.preset)
        print(f"  감정 라벨 템플릿 -> {p.name} (영상을 직접 본 사람이 채워 sfx_emotion_labels.csv 로 저장)")
    return 0


def cmd_sfx_map(a) -> int:
    from .sfx_map import MATCH_THRESHOLD, build_map

    m = build_map(a.preset, threshold=a.threshold or MATCH_THRESHOLD)
    status_ko = {"not_provided": "미제공", "scanned": "스캔함"}
    print(f"[효과음 창고] {m['library_root']} ({m['library_root_source']}): {status_ko.get(m['library_status'])}, "
          f"파일 {m.get('library_files', 0)}개; 카탈로그 {_ko(m['catalog']['status'])}")
    for tid, v in (m.get("types") or {}).items():
        print(f"  {tid:<12} {_ko(v['status'])}  {v.get('file') or ''}  유사도 {v.get('similarity')}")
        if v.get("needed_asset") and v["status"] != "have":
            print(f"     필요: {v['needed_asset']}")
    if not m.get("types"):
        print("  매핑할 효과음 종류 없음" + (f" — {m.get('note')}" if m.get("note") else ""))
    return 0


def cmd_audio_measure(a) -> int:
    from .audio_original import aggregate_measurements

    vids = [v.strip() for v in a.videos.split(",") if v.strip()] if a.videos else None
    r = aggregate_measurements(a.preset, vids)
    ex = (r.get("basis") or {}).get("excluded_non_snapshot") or []
    print(f"[측정 집계] 스냅샷 영상 {len(r['videos'])}편(스냅샷 밖 제외 {len(ex)}편) -> measurements/audio.json")
    for it in r["items"]:
        n = (it.get("overall") or {}).get("n", 0)
        blk = str(it.get("blocker") or "")
        print(f"  {it['key']:<32} {_ko(it['status']):<4} 값 {it['value']}  n={n}"
              + (f"  ({blk[:160]}{'…' if len(blk) > 160 else ''})" if blk else ""))
    print("  → `shortkit preset apply-measurements` 로 프리셋에 반영")
    return 0


def cmd_audio_analyze(a) -> int:
    from .audio_bgm import analyze_bgm
    from .audio_original import analyze_original, load_context, measure_loudness
    from .separation import DemucsSeparator, stems_or_none
    from .sfx_catalog import newest_video_ids
    from .sfx_events import analyze_sfx_events

    if a.all:
        vids, n, blocker = newest_video_ids(a.preset)
        if not vids:
            print(f"[오디오 분석] 대상 영상 없음 — {blocker}")
            return 0
    elif getattr(a, "set", None):
        from .common import resolve_ids

        vids = resolve_ids(a.preset, set_name=a.set)
        if not vids:
            print(f"[오디오 분석] '{a.set}' 묶음에 영상 없음 — `shortkit ref collect`/`ref download` 결과 확인")
            return 3
        print(f"[오디오 분석] '{a.set}' {len(vids)}편")
    else:
        vids = [a.video]
    for vid in vids:
        audio = a.audio if a.video else None
        if a.no_separate:
            from .separation import load_cached_stems

            st, sst = load_cached_stems(a.preset, vid, audio_path=audio), None
        else:
            st, sst = stems_or_none(a.preset, vid, separator=DemucsSeparator("htdemucs"), audio_path=audio)
            if st is None:
                print(f"[분리] {vid}: 못 잼 — {sst['blocker']}")
        b = analyze_bgm(a.preset, vid, audio_path=audio, stems=st, separator_status=sst)
        _print_bgm(b)
        ctx = load_context(a.preset, vid, audio, st)
        _print_original(analyze_original(a.preset, vid, ctx=ctx))
        _print_sfx(analyze_sfx_events(a.preset, vid, ctx=ctx))
        ld = measure_loudness(a.preset, vid, audio_path=audio)
        print(f"[음량] {vid}: " + (f"{ld['integrated_lufs']} LUFS, 최대 {ld['true_peak_db']} dBTP (ebur128)"
                                   if ld.get("status") == "measured" else f"못 잼 — {ld.get('blocker')}"))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="shortkit.reference.audio_cli", description="레퍼런스 오디오 분석")
    register(ap.add_subparsers(dest="cmd", required=True))
    args = ap.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    sys.exit(main())
