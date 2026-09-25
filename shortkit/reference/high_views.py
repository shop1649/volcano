"""Reference-only report over EVERY channel video with >= reference.high_view_threshold views.

    shortkit ref high-views-report   ->  presets/<name>/reference/high_views_report.{json,md}

The request says to analyse ALL videos with 800k+ views.  The latest-100 snapshot stays the production
basis (AGENTS.md rule 2): high-view videos OUTSIDE the snapshot get the full analysis chain (download ->
`ref audio-analyze --set high_views` -> `ref analyze --set high_views` -> `ref trace`) but their numbers
live only in this report -- they never enter measurements/*.json (``common.production_basis``).

Per video: view count (+ checked_at), in_latest100, format label (formats.yaml assignment for snapshot
members; a watched label kept under ``outside_snapshot_labels`` otherwise), structure statistics (duration,
cuts, captions by role, zoom / freeze / flash counts), audio (BGM presence + identified track / version,
original sound, ducking, SFX events by class and whether speech intervals were measurable), credits
traced (accounts, original URLs, fingerprint count) and COVERAGE of each analysis step.

``status`` = measured only when high_views.json is complete (``status: ok``, no ``unverified`` entry) AND
every listed video was downloaded AND analysed visually AND by audio AND traced (fingerprint).  Anything
less is ``unmeasured`` with the missing ids per step -- this is the row `shortkit preset unresolved` must
show for "조회수 80만 이상 영상 전체 분석" (``stage_status``).
"""
from __future__ import annotations

from collections import Counter

from .. import paths
from ..util.jsonio import now_iso, read_json, read_yaml, write_json
from ..util.stats import pstats
from .common import analysis_dir, load_reference_list, say, snapshot_blocker, snapshot_members, video_path, warn

SCHEMA = "shortkit.high_views_report/1"
STEPS = ("downloaded", "visual", "audio", "trace")
STEP_KO = {"downloaded": "영상 받기", "visual": "시각 분석(ref analyze)", "audio": "오디오 분석(ref audio-analyze)",
           "trace": "출처 추적·지문(ref trace)"}
STEP_CMD = {"downloaded": "shortkit ref download --set high_views",
            "visual": "shortkit ref analyze --set high_views",
            "audio": "shortkit ref audio-analyze --set high_views",
            "trace": "shortkit ref trace"}


def _fingerprints() -> dict[str, int]:
    from ..sourcing import exclusions as X

    out: dict[str, int] = {}
    for e in X.load():
        if e.get("kind") == "reference_footage" and e.get("phash"):
            out[str(e.get("ref_video_id"))] = out.get(str(e.get("ref_video_id")), 0) + len(e["phash"])
    return out


def coverage_of(preset: str, vid: str, fps: dict[str, int]) -> dict:
    d = analysis_dir(preset, vid)
    try:
        dl = video_path(preset, vid) is not None
    except ValueError:
        dl = False
    return {"downloaded": dl,
            "visual": all((d / f).is_file() for f in ("shots.json", "captions.json", "motion.json")),
            "audio": all((d / "audio" / f).is_file() for f in ("bgm.json", "original.json", "sfx_events.json")),
            "trace": (d / "trace.json").is_file() and fps.get(vid, 0) > 0}


def _structure(preset: str, vid: str) -> dict | None:
    d = analysis_dir(preset, vid)
    shots, caps, mot = (read_json(d / f"{n}.json") for n in ("shots", "captions", "motion"))
    if not (shots or caps or mot):
        return None
    dur = next((float(x["duration"]) for x in (shots, caps, mot) if x and x.get("duration")), None)
    cuts = (shots or {}).get("cuts") or []
    ev = (mot or {}).get("events") or []
    roles = Counter(c.get("role") for c in (caps or {}).get("items") or [] if c.get("role") != "identity_mark")
    per10 = (lambda n: round(10.0 * n / dur, 3)) if dur else (lambda n: None)  # noqa: E731
    return {"duration_s": dur, "cuts": len(cuts), "cuts_per_10s": per10(len(cuts)),
            "transitions": dict(Counter(c.get("type") for c in cuts)),
            "captions": sum(roles.values()), "captions_by_role": dict(roles),
            "zoom_events": sum(1 for e in ev if str(e.get("type", "")).startswith("zoom")),
            "freeze_events": sum(1 for e in ev if e.get("type") == "freeze"),
            "presence": {**((mot or {}).get("presence") or {}),
                         **{f"shots_{k}": v for k, v in ((shots or {}).get("presence") or {}).items()}}}


def _audio(preset: str, vid: str) -> dict | None:
    a = analysis_dir(preset, vid) / "audio"
    bgm, orig, sfx = (read_json(a / f) for f in ("bgm.json", "original.json", "sfx_events.json"))
    if not (bgm or orig or sfx):
        return None
    m = (bgm or {}).get("match") or {}
    ev = (sfx or {}).get("events") or []
    return {"bgm": {"presence": (bgm or {}).get("presence", "unmeasured"),
                    "track_id": (m.get("track_id") or {}).get("value"), "version": (m.get("version") or {}).get("value"),
                    "tempo_ratio": (m.get("tempo_ratio") or {}).get("value"),
                    "section_start_s": (m.get("section_start_s") or {}).get("value"),
                    "blocker": (bgm or {}).get("blocker")},
            "original_audio": ((orig or {}).get("original_audio") or {}).get("presence", "unmeasured"),
            "ducking": ((orig or {}).get("ducking") or {}).get("presence", "unmeasured"),
            "sfx": {"status": (sfx or {}).get("status", "unmeasured"), "blocker": (sfx or {}).get("blocker"),
                    "events_by_class": dict(Counter(e.get("class") or "미분류" for e in ev)),
                    "n_sfx": sum(1 for e in ev if e.get("class") != "intentional_silence"),
                    "counts_are_lower_bounds": bool((sfx or {}).get("unmeasured_coverage"))}}


def _credits(preset: str, vid: str) -> dict | None:
    tj = read_json(analysis_dir(preset, vid) / "trace.json")
    if not tj:
        return None
    return {"accounts": sorted({f"{a.get('platform')}:{a.get('account')}" for a in tj.get("accounts_found") or []}),
            "original_urls": tj.get("original_urls") or [], "sources_examined": tj.get("sources_examined") or [],
            "phash_count": tj.get("phash_count", 0)}


def _outside_labels(preset: str) -> dict[str, dict]:
    from ..config import load_preset

    try:
        fy = read_yaml(paths.absp(load_preset(preset).get("structure.formats_file")), {}) or {}
    except Exception:  # noqa: BLE001 - labels are optional context
        return {}
    return {str(r.get("video_id")): r for r in fy.get("outside_snapshot_labels") or [] if r.get("video_id")}


def build_report(preset: str, write: bool = True) -> dict:
    from .classify import load_membership

    hv = load_reference_list(preset, "high_views") or {}
    members, _snap = snapshot_members(preset)
    mset = set(members)
    fmt = load_membership(preset)
    olab = _outside_labels(preset)
    fps = _fingerprints()
    rows = []
    for v in hv.get("videos") or []:
        vid = v.get("video_id")
        if not vid:
            continue
        cov = coverage_of(preset, vid, fps)
        label = ({"format_id": fmt.get(vid), "source": "formats.yaml(스냅샷 구성원)"} if vid in mset and fmt.get(vid)
                 else {"structure_type": olab[vid].get("structure_type"), "intro_type": olab[vid].get("intro_type"),
                       "labeled_by": olab[vid].get("labeled_by"), "source": "format_labels.csv(스냅샷 밖, 참고)"}
                 if vid in olab else None)
        rows.append({"video_id": vid, "url": v.get("url"), "title": v.get("title"), "view_count": v.get("view_count"),
                     "view_count_checked_at": v.get("view_count_checked_at"), "published_at": v.get("published_at"),
                     "in_latest100": vid in mset, "kind": v.get("kind"), "format_label": label, "coverage": cov,
                     "structure": _structure(preset, vid), "audio": _audio(preset, vid),
                     "credits": _credits(preset, vid)})
    missing = {s: [r["video_id"] for r in rows if not r["coverage"][s]] for s in STEPS}
    unverified = hv.get("unverified") or []
    blockers = []
    if not hv:
        blockers.append("reference/high_views.json 없음(`shortkit ref collect` 미실행)")
    elif hv.get("status") not in ("ok",):
        blockers.append(f"high_views.json status={hv.get('status')}: {str(hv.get('blocker') or '')[:300]}")
    if unverified:
        blockers.append(f"조회수 확인 못 한 후보 {len(unverified)}편: " + ", ".join(u.get("video_id") for u in unverified[:10]))
    for s in STEPS:
        if missing[s]:
            blockers.append(f"{STEP_KO[s]} 안 된 영상 {len(missing[s])}편({', '.join(missing[s][:8])}"
                            + ("…" if len(missing[s]) > 8 else "") + f") → `{STEP_CMD[s]}`")
    if hv.get("status") == "blocked" or (not hv and not members):
        blockers.insert(0, snapshot_blocker(preset))
    status = "measured" if not blockers else "unmeasured"
    outside = [r for r in rows if not r["in_latest100"]]
    summary = {"n_high_views": len(rows), "n_in_latest100": len(rows) - len(outside), "n_outside_latest100": len(outside),
               "coverage": {s: len(rows) - len(missing[s]) for s in STEPS},
               "outside_latest100_reference_only": _summary(outside)}
    rep = {"schema": SCHEMA, "preset_id": _preset_id(preset), "generated_at": now_iso(), "status": status,
           "blocker": "; ".join(blockers) or None, "threshold": hv.get("threshold"),
           "high_views_checked_at": hv.get("checked_at"), "high_views_status": hv.get("status"),
           "reference_only": True,
           "rule": ("참고용 보고서: 조회수 기준 이상 영상 전부의 분석 결과. 제작 측정(measurements/*.json)은 최신 100편 스냅샷 "
                    "구성원만 쓰며 이 보고서의 값(특히 스냅샷 밖 영상)은 섞지 않는다"),
           "missing": missing, "unverified": unverified, "summary": summary, "videos": rows}
    if write:
        rdir = paths.preset_dir(preset) / "reference"
        write_json(rdir / "high_views_report.json", rep)
        (rdir / "high_views_report.md").write_text(_markdown(rep), encoding="utf-8")
        say(f"조회수 기준 이상 영상 보고서: {len(rows)}편(스냅샷 밖 {len(outside)}편), 상태 "
            f"{'측정' if status == 'measured' else '못 잼'} → {paths.relp(rdir / 'high_views_report.md')}")
        if blockers:
            warn("  " + blockers[0])
    return rep


def _preset_id(preset: str) -> str | None:
    try:
        from ..config import load_preset
        return load_preset(preset).preset_id
    except Exception:  # noqa: BLE001
        return None


def _summary(rows: list[dict]) -> dict:
    st = [r["structure"] for r in rows if r.get("structure")]
    au = [r["audio"] for r in rows if r.get("audio")]
    return {"n": len(rows), "n_with_visual": len(st), "n_with_audio": len(au),
            "duration_s": pstats([s["duration_s"] for s in st if s.get("duration_s") is not None]),
            "cuts_per_10s": pstats([s["cuts_per_10s"] for s in st if s.get("cuts_per_10s") is not None]),
            "captions": pstats([s["captions"] for s in st]),
            "bgm_presence": dict(Counter(a["bgm"]["presence"] for a in au)),
            "original_audio_presence": dict(Counter(a["original_audio"] for a in au)),
            "sfx_per_video": pstats([a["sfx"]["n_sfx"] for a in au if a["sfx"]["status"] in ("measured", "partial")]),
            "note": "참고용(스냅샷 밖 고조회 영상) — 제작 설정에 쓰지 않음"}


def _markdown(rep: dict) -> str:
    L = ["# 조회수 기준 이상 영상 분석 보고서(참고용)", "",
         f"자동 생성: `shortkit ref high-views-report` ({rep['generated_at']}). 기준 {rep.get('threshold')} 회, "
         f"목록 확인 {rep.get('high_views_checked_at')} (high_views.json 상태 {rep.get('high_views_status')}).", "",
         f"> {rep['rule']}", "",
         f"**상태: {'측정(전부 분석됨)' if rep['status'] == 'measured' else '못 잼'}**" +
         (f" — {rep['blocker']}" if rep.get("blocker") else ""), "",
         "## 분석 범위", "", "| 단계 | 완료 | 안 된 영상 | 명령 |", "|---|---:|---|---|"]
    n = rep["summary"]["n_high_views"]
    for s in STEPS:
        miss = rep["missing"][s]
        L.append(f"| {STEP_KO[s]} | {n - len(miss)}/{n} | {', '.join(miss[:10]) + ('…' if len(miss) > 10 else '') or '-'} "
                 f"| `{STEP_CMD[s]}` |")
    if rep.get("unverified"):
        L += ["", "조회수를 확인하지 못한 후보(못 잼): " + ", ".join(u.get("video_id") for u in rep["unverified"][:20])]
    L += ["", "## 영상별", "",
          "| 영상 | 조회수 | 최신100 | 포맷 라벨 | 길이 | 컷/10초 | 자막 | 확대/정지 | BGM | 원음 | 효과음 | 출처 |",
          "|---|---:|---|---|---:|---:|---:|---|---|---|---|---|"]
    for r in rep["videos"]:
        s, a, c, lab = r.get("structure") or {}, r.get("audio") or {}, r.get("credits") or {}, r.get("format_label") or {}
        lab_txt = lab.get("format_id") or lab.get("structure_type") or "-"
        bgm = (a.get("bgm") or {})
        bgm_txt = (f"{bgm.get('presence')}" + (f" {bgm.get('track_id')}/{bgm.get('version')}" if bgm.get("track_id") else "")
                   ) if a else "못 잼"
        sfx = a.get("sfx") or {}
        sfx_txt = (f"{sfx.get('n_sfx')}" + ("(하한)" if sfx.get("counts_are_lower_bounds") else "")) if a else "못 잼"
        cred = ", ".join(c.get("accounts") or [])[:80] if c else "못 잼"
        L.append(f"| {r['video_id']} | {r.get('view_count')} | {'예' if r['in_latest100'] else '아니오(참고)'} | {lab_txt} | "
                 f"{s.get('duration_s', '못 잼') if s else '못 잼'} | {s.get('cuts_per_10s', '') if s else ''} | "
                 f"{s.get('captions', '') if s else ''} | "
                 f"{(str(s.get('zoom_events')) + '/' + str(s.get('freeze_events'))) if s else ''} | {bgm_txt} | "
                 f"{a.get('original_audio', '못 잼') if a else '못 잼'} | {sfx_txt} | {cred or '-'} |")
    o = rep["summary"]["outside_latest100_reference_only"]
    L += ["", "## 스냅샷 밖 고조회 영상 요약(참고, 제작 측정 아님)", "",
          f"- 영상 {o['n']}편(시각 분석 {o['n_with_visual']}편, 오디오 분석 {o['n_with_audio']}편)",
          f"- 길이 p10/p50/p90: {o['duration_s'].get('p10')}/{o['duration_s'].get('p50')}/{o['duration_s'].get('p90')} 초 "
          f"(n={o['duration_s'].get('n')})",
          f"- 컷/10초 p50: {o['cuts_per_10s'].get('p50')} (n={o['cuts_per_10s'].get('n')})",
          f"- BGM 있다/없다/못 잼: {o['bgm_presence']}", f"- 원음: {o['original_audio_presence']}",
          f"- 편당 효과음 p10/p50/p90: {o['sfx_per_video'].get('p10')}/{o['sfx_per_video'].get('p50')}/"
          f"{o['sfx_per_video'].get('p90')} (n={o['sfx_per_video'].get('n')})", ""]
    return "\n".join(L) + "\n"


def stage_status(preset: str) -> dict:
    """Row for `shortkit preset unresolved`: '조회수 80만 이상 영상 전체 분석' is measured only when the high-view
    list is complete and every listed video was downloaded AND analysed (visual, audio, trace)."""
    rep = build_report(preset, write=False)
    n = rep["summary"]["n_high_views"]
    cov = rep["summary"]["coverage"]
    hv_state = rep.get("high_views_status")
    state = ("resolved" if rep["status"] == "measured" else
             "blocked_network" if hv_state in (None, "blocked") else "open")
    return {"item": "조회수 80만 이상 영상 전체 분석", "status": rep["status"],
            "impact": ("없음" if rep["status"] == "measured" else
                       "고조회 영상의 공통 구조·BGM·효과음·출처를 확인하지 못한 영상이 있음 → 고조회 소재 제외 목록·참고 보고서가 불완전"),
            "state": state,
            "evidence": (f"reference/high_views_report.json: 목록 {n}편(high_views.json status={hv_state}, 확인 못 함 "
                         f"{len(rep.get('unverified') or [])}편), " + ", ".join(f"{STEP_KO[s]} {cov[s]}/{n}" for s in STEPS))}
