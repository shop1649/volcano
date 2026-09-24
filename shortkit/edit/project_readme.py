"""Korean README.md for the editable project folder, generated from the ACTUAL export decisions
(export_decisions.json written by the exporters) and the verification result (verify.json),
plus an orchestrator / CLI that runs the whole project export.

    write(resolved, out_dir, decisions) -> Path          (contract API)
    export_project(resolved, out_dir=None, master=None, verify=True, absolute=False) -> dict

    python -m shortkit.edit.project_readme export --episode <id> [--no-verify] [--absolute]
    python -m shortkit.edit.project_readme verify --episode <id>
    python -m shortkit.edit.project_readme readme --episode <id>

Nothing in the README is written from assumptions: every "verified" line quotes verify.json
numbers from a finished melt render; everything else is listed as 못 잼 (not verified).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .. import paths
from ..util.jsonio import now_iso, read_json
from .export_mlt import DECISIONS_FILE
from .ir import ResolvedEdit

ROLE_KO = {"title": "제목", "description": "설명", "situation": "상황", "speaker": "화자", "dialogue": "대사",
           "reaction": "반응"}
STATUS_KO = {"pass": "통과", "fail": "불일치", "unmeasured": "못 잼", None: "못 잼"}


def _fmt_s(t: float) -> str:
    return f"{t:.2f}s"


def _table(head: list[str], rows: list[list]) -> list[str]:
    out = ["| " + " | ".join(head) + " |", "|" + "|".join("---" for _ in head) + "|"]
    for r in rows:
        out.append("| " + " | ".join(str(x).replace("|", "/").replace("\n", " ") for x in r) + " |")
    return out


def _verify_summary(v: dict | None) -> tuple[str, list[str]]:
    if not v or not v.get("status"):
        return "못 잼", ["- MLT 렌더 비교: **못 잼** — verify.json 이 없음(검증을 실행하지 않음)"]
    st = v.get("status")
    lines = []
    if st in ("pass", "fail") and v.get("global"):
        g = v["global"]
        th = v.get("thresholds", {})
        diffs = [abs(r["level_diff_db"]) for r in v.get("rows", []) if r.get("audio") == "pass"
                 or r.get("audio") == "fail"]
        lines.append(f"- MLT 프로젝트를 melt 로 실제 렌더해 마스터 MP4 와 같은 시각 1초 격자로 비교: **{STATUS_KO[st]}**"
                     + (f" ({v.get('why')})" if v.get("why") else ""))
        lines.append(f"  - 화면 SSIM 전체 {g.get('ssim_overall')} (기준 ≥ {th.get('ssim_overall_min')}), "
                     f"가장 낮은 1초 {g.get('ssim_worst_second')} (기준 ≥ {th.get('ssim_sec_mean_min')}), "
                     f"평균 절대차 {g.get('mad_overall')} (1초 기준 ≤ {th.get('mad_sec_max')})")
        lines.append(f"  - 소리 RMS 포락선 상관 {g.get('audio_env_corr')} (기준 ≥ {th.get('audio_env_corr_min')}), "
                     f"초별 레벨 차 최대 {max(diffs):.2f} dB" if diffs else
                     f"  - 소리 RMS 포락선 상관 {g.get('audio_env_corr')}; 레벨 비교 가능한 초 없음")
        lines.append(f"  - 길이: 마스터 {g.get('duration_master_s')}s / 프로젝트 {g.get('duration_project_s')}s, "
                     f"비교 프레임 {g.get('frames_compared')}/{g.get('frames_expected')}")
        m = v.get("melt") or {}
        lines.append(f"  - 렌더 방식: `{' '.join(m.get('cmd', [])[:2])} …` ({m.get('mode')}), 결과 파일 {m.get('output')}")
    else:
        lines.append(f"- MLT 렌더 비교: **못 잼** — {v.get('why')}")
    return STATUS_KO.get(st, "못 잼"), lines


def write(resolved: ResolvedEdit, out_dir: Path, decisions: dict) -> Path:
    """Write <out_dir>/README.md (Korean) from export_decisions.json + verify.json + caller decisions."""
    r = resolved
    out_dir = Path(out_dir)
    ex = read_json(out_dir / DECISIONS_FILE, {}) or {}
    v = read_json(out_dir / "verify.json", None)
    mlt, fcp, oti = ex.get("mlt") or {}, ex.get("fcpxml") or {}, ex.get("otio") or {}
    decisions = decisions or {}
    W, H, fps = r.canvas["width"], r.canvas["height"], r.canvas["fps"]
    vstat, vlines = _verify_summary(v)
    other = (v or {}).get("other_formats") or {}
    L: list[str] = []
    L += [f"# {r.episode_id} 편집 프로젝트", "",
          f"- 생성 {now_iso()} · 프리셋 `{r.preset_id}` · 포맷 `{r.format_id}` · 모드 `{r.mode}`"
          + (" (테스트: 파이프라인 검증용, 게시용 아님)" if r.mode == "test" else ""),
          f"- 캔버스 {W}x{H} @ {fps:g}fps · 길이 {_fmt_s(r.duration)} · 마스터 `{r.output_path}`",
          "- 이 문서는 내보내기 코드가 실제로 내린 결정(`export_decisions.json`)과 검증 결과(`verify.json`)로 "
          "자동 생성됨. 적혀 있지 않은 것은 확인하지 않은 것임.", ""]
    # ---------------------------------------------------------------- files
    rows = []
    if mlt:
        rows.append([f"`{mlt.get('file')}`", "Shotcut (MLT XML) 편집 프로젝트", f"melt 렌더 비교: {vstat}"])
    if fcp:
        rows.append([f"`{fcp.get('file')}`", "DaVinci Resolve / Final Cut Pro 가져오기(FCPXML 1.9)",
                     "못 잼 (프로그램 없음; 형식·시간 일관성만 테스트)"])
    if oti:
        rows.append([f"`{oti.get('file')}`", "OpenTimelineIO 교환 파일", "못 잼 (렌더러 없음; 쓰기→읽기 왕복만 테스트)"])
    caps = mlt.get("captions") or fcp.get("captions") or oti.get("captions") or {}
    if caps.get("ass"):
        rows.append(["`captions.ass`", "자막 + 장식 전체(한 레이어). Aegisub/텍스트 편집기로 수정",
                     "마스터 렌더와 같은 파일(복사본)"])
    if caps.get("srt") or (out_dir / "captions.srt").is_file():
        rows.append(["`captions.srt`", f"모든 역할의 자막 텍스트·시간({caps.get('srt_count', len(r.captions))}개)",
                     "텍스트/시간만(스타일 없음)"])
    pre = []
    for key in ("mlt", "fcpxml", "otio"):
        for p in (ex.get(key) or {}).get("prerendered", []):
            if not any(p["file"] == q["file"] for q in pre):
                pre.append(p)
    if pre:
        rows.append(["`media/`", f"미리 렌더된 중간 파일 {len(pre)}개(아래 '굽혀 있는 것')", "-"])
    rows.append(["`verify.json`", "melt 렌더 비교 수치(초별 행 포함)", vstat])
    rows.append(["`export_decisions.json`", "내보내기 결정 기록(이 README 의 근거)", "-"])
    L += ["## 파일", ""] + _table(["파일", "용도", "검증"], rows) + [""]
    L += ["미디어 경로는 모두 **이 폴더 기준 상대 경로**다. 폴더 구조(프로젝트 루트 아래 `assets/`, `episodes/`, "
          "`warehouse/`)를 유지한 채로 열어야 한다.", ""]
    # ---------------------------------------------------------------- MLT
    if mlt:
        L += ["## Shotcut 에서 편집할 수 있는 것 (MLT)", ""]
        L += [f"- {x}" for x in mlt.get("editable", [])]
        tr_rows = [[t["track"], "영상" if t["kind"] == "video" else "소리", t["items"]] for t in mlt.get("tracks", [])]
        L += ["", "트랙 구성:", ""] + _table(["트랙", "종류", "클립 수"], tr_rows) + [""]
        loud = mlt.get("loudness") or {}
        if loud.get("gain_db") is not None:
            L.append(f"- 전체 음량: 타임라인 volume 필터 {loud['gain_db']:+.2f} dB (출처: {loud.get('source')})")
        else:
            L.append(f"- 전체 음량 이득: **못 잼** — {loud.get('why', '정보 없음')} (마스터와 음량이 다를 수 있음)")
        fgl = mlt.get("foreground_limiter")
        if fgl and fgl.get("status") == "있음":
            L.append(f"- 효과음/원본 소리 안전 리미터: 마스터가 최대 {fgl['master_max_reduction_db']} dB 줄인 것을 "
                     f"{fgl['source']} 에서 프레임별로 읽어 각 클립 volume 키프레임으로 재현 ({fgl['note']})")
        elif fgl:
            L.append(f"- 효과음/원본 소리 안전 리미터: **못 잼** — {fgl.get('why')}")
        lim = mlt.get("limiter")
        if lim:
            L.append(f"- 피크 리미터: {lim['service']} 한도 {lim['ceiling_dbfs']} dBFS — {lim['note']}")
        for d in mlt.get("delogo", [])[:1]:
            L.append(f"- delogo 주의: {d['note']}")
        if mlt.get("crossfades"):
            off = [c for c in mlt["crossfades"] if not c.get("on_frame_grid")]
            L.append(f"- crossfade {len(mlt['crossfades'])}개: Shotcut 전환(luma+mix)"
                     + (f"; 그중 {len(off)}개는 마스터의 시작점이 프레임 사이라 진행률이 최대 1프레임만큼 다름" if off else ""))
        for w in mlt.get("warnings", []):
            L.append(f"- 경고: {w}")
        L.append("")
        L += ["### Kdenlive", "",
              "- 이 `.mlt` 는 Shotcut 구조의 MLT XML 이다. Kdenlive 는 자체 형식(.kdenlive)을 편집 타임라인으로 열고, "
              "일반 MLT XML 은 보통 하나의 클립(재생목록)으로 불러온다(개별 클립 편집 불가) — Kdenlive 문서 기준이며 "
              "이 기계에서 확인하지 못함.",
              "- Kdenlive 에서 클립 단위로 편집하려면 `.otio` 가져오기(OpenTimelineIO 지원 버전)를 쓴다. "
              "이 기계에는 Kdenlive 가 없어 **확인하지 못함(못 잼)**.", ""]
    # ---------------------------------------------------------------- FCPXML
    if fcp:
        L += ["## DaVinci Resolve / Final Cut Pro 에서 편집할 수 있는 것 (FCPXML)", ""]
        L += [f"- {x}" for x in fcp.get("editable", [])]
        L += ["", "FCPXML 로 표현하지 못해 빠지거나 대체된 것:", ""] + [f"- {x}" for x in fcp.get("not_representable", [])]
        if fcp.get("loudness_gain_db") is not None:
            L.append(f"- 전체 음량 이득 {fcp['loudness_gain_db']:+.2f} dB 를 각 오디오 클립 음량에 더해 넣음(마스터 버스 없음)")
        L.append(f"- 미디어 경로: {'절대 file:// URL (이 기계 전용, 커밋 금지)' if fcp.get('absolute_urls') else '상대 URL'}"
                 " — 가져오기에서 미디어를 못 찾으면 `export --absolute` 로 이 컴퓨터 전용 파일을 만든다")
        L += [f"- 검증: {fcp.get('verification')}", ""]
    if oti:
        L += ["## OpenTimelineIO", "",
              f"- 트랙: " + ", ".join(f"{t['name']}({t['items']})" for t in oti.get("tracks", [])),
              f"- 마커: 자막 {oti.get('markers', {}).get('captions')}개(V2), 효과음 사건 "
              f"{oti.get('markers', {}).get('sfx_events')}개(A2)",
              "- 줌·정지·원본 정리(crop/delogo/inpaint/blur) 수치는 각 클립 metadata['shortkit'] 에 있음",
              f"- 검증: {oti.get('verification')}", ""]
    # ---------------------------------------------------------------- baked
    L += ["## 굽혀 있어(미리 합성되어) 개별 편집이 안 되는 것", ""]
    L.append("- **자막과 장식은 전부 `captions.ass` 한 파일, 한 레이어**로 그려진다(마스터 렌더와 같은 libass). "
             "NLE 의 개별 텍스트 클립이 아니므로 글자·위치·시간·스타일은 `captions.ass` 를 Aegisub 나 텍스트 편집기로 "
             "고친 뒤 다시 렌더/내보내기 해야 한다. `captions.srt` 는 텍스트·시간 참고용이다.")
    cap_rows = [[c.id, ROLE_KO.get(c.role, c.role), f"{c.start:.2f}–{c.end:.2f}", c.text.replace("\n", " / ")]
                for c in sorted(r.captions, key=lambda c: c.start)]
    if cap_rows:
        L += [""] + _table(["id", "역할", "시간(s)", "텍스트"], cap_rows)
    if r.decorations:
        L += ["", "장식(같은 ASS 레이어):", ""] + _table(
            ["id", "종류", "시간(s)"], [[d.id, d.kind, f"{d.start:.2f}–{d.end:.2f}"] for d in r.decorations])
    L.append("")
    if any(c.inpaint for c in r.clips):
        L.append("- inpaint 로 지운 소스는 미리 렌더된 중간 파일(resolve 가 만든 `warehouse/cache/clean/...`)을 소스로 "
                 "쓴다: " + ", ".join(sorted({c.source_path for c in r.clips if c.inpaint})))
    for p in pre:
        L.append(f"- `{p['file']}` — {p.get('why', p.get('kind'))}")
    L.append("")
    # ---------------------------------------------------------------- verification
    L += ["## 검증한 것", ""] + vlines
    if v and v.get("rows"):
        vr = [[r_["sec"], r_.get("ssim_mean", "-"), r_.get("mad", "-"), r_.get("level_diff_db", "-"),
               {"pass": "통과", "fail": "불일치", "unmeasured": "못 잼"}.get(r_["video"], r_["video"]),
               {"pass": "통과", "fail": "불일치", "quiet": "조용함(비교 안 함)", "unmeasured": "못 잼"}.get(
                   r_["audio"], r_["audio"])] for r_ in v["rows"]]
        L += ["", "초별 비교(같은 절대 시각):", ""] + _table(["초", "SSIM", "평균 절대차", "레벨 차(dB)", "화면", "소리"], vr)
    L.append("")
    L += ["## 검증하지 못한 것 (못 잼)", ""]
    nv = list((v or {}).get("not_verified") or ["Shotcut/Kdenlive GUI 에서 실제로 열어 보기",
                                               "사람이 직접 보고 들은 확인"])
    nv += ["DaVinci Resolve / Final Cut Pro 에서 FCPXML 가져오기·재생(프로그램 없음)",
           "OTIO 를 다른 편집기로 가져오기(Kdenlive/Resolve 어댑터 없음)"]
    for k, o in other.items():
        nv.append(f"{k}: {o.get('why')}")
    L += [f"- {x}" for x in nv] + [""]
    # ---------------------------------------------------------------- notes
    L += ["## 주의", ""]
    L.append("- 원본 소리는 기본 OFF: 영상 트랙의 소리는 모두 꺼져 있고, 살린 대사만 A3 트랙에 따로 있다.")
    L.append("- BGM 덕킹은 살린 대사 구간에서만 걸려 있다(효과음·컷 때문에 낮추지 않음). 정적 구간은 envelope 로 무음.")
    if r.fonts_dir:
        L.append(f"- 자막 글꼴: `{r.fonts_dir}` (git 에 없는 build 폴더). melt 는 이 폴더(프로젝트 폴더 기준 상대 경로 "
                 "av.fontsdir)를 쓰는데, 이 상대 경로는 실행 위치 기준으로 해석되므로 Shotcut 에서 글꼴이 다르게 보이면 "
                 "해당 글꼴을 시스템에 설치한다.")
    if r.warnings:
        L += ["- 계획 단계 경고:"] + [f"  - {w}" for w in r.warnings]
    if r.provisional_keys:
        L.append(f"- 프리셋 미측정(못 잼) 값 {len(r.provisional_keys)}개로 만든 편집이다(레퍼런스 일치 아님).")
    if decisions.get("plan_sha256"):
        L.append(f"- plan sha256 `{decisions['plan_sha256']}`")
    elif decisions.get("plan_file_sha256"):
        L.append(f"- plan.yaml 파일 sha256 `{decisions['plan_file_sha256']}`")
    ap = decisions.get("approval")
    if isinstance(ap, dict):
        if ap.get("required") is None and ap.get("approved") is None:
            L.append("- 승인 상태: plan.yaml 에 승인 기록 없음"
                     + (" (테스트 모드는 승인 불필요)" if r.mode == "test" else ""))
        else:
            L.append(f"- 승인 상태: 필요={ap.get('required')} 승인됨={ap.get('approved')}"
                     + (f" (승인자 {ap.get('approved_by')}, {ap.get('approved_at')})" if ap.get("approved") else ""))
    for s in decisions.get("sources", []) or []:
        L.append(f"- 소스 {s.get('id')}: `{s.get('path')}` sha256={str(s.get('sha256'))[:16]}… "
                 f"창고 id={s.get('warehouse_id')}")
    L += ["", "## 다시 만들기", "",
          f"```\npython -m shortkit episode export {r.episode_id}\n"
          f"# 또는 이 모듈만: python -m shortkit.edit.project_readme export --episode {r.episode_id}\n```", ""]
    out = out_dir / "README.md"
    out.write_text("\n".join(L), encoding="utf-8")
    return out


# ============================================================================ orchestration
def plan_decisions(episode_id: str) -> dict:
    """Provenance for the README when not called from `shortkit episode export` (which passes its
    own): plan file hash, approval block and sources as written in plan.yaml."""
    from ..util.hashing import sha256_file
    from ..util.jsonio import read_yaml

    f = paths.absp(f"episodes/{episode_id}/plan.yaml")
    plan = read_yaml(f, None)
    if not plan:
        return {}
    ap = plan.get("approval") or {}
    return {"plan_file_sha256": sha256_file(f), "notes": plan.get("notes", ""),
            "approval": {"required": ap.get("required"), "approved": ap.get("approved"),
                         "approved_by": ap.get("approved_by"), "approved_at": ap.get("approved_at")},
            "sources": [{"id": x.get("id"), "path": x.get("path"), "sha256": x.get("sha256"),
                         "warehouse_id": x.get("warehouse_id")} for x in plan.get("sources") or []]}


def load_resolved(episode_id: str) -> ResolvedEdit:
    d = read_json(paths.absp(f"episodes/{episode_id}/build/resolved.json"))
    if d is None:
        raise FileNotFoundError(f"episodes/{episode_id}/build/resolved.json 없음 (먼저 `shortkit episode resolve`)")
    return ResolvedEdit.from_dict(d)


def export_project(resolved: ResolvedEdit, out_dir: Path | None = None, master: Path | None = None,
                   verify: bool = True, absolute: bool = False, decisions: dict | None = None) -> dict:
    from . import export_fcpxml, export_mlt, export_otio, verify_project

    r = resolved
    out_dir = Path(out_dir) if out_dir else paths.absp(f"episodes/{r.episode_id}/project")
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict = {"episode_id": r.episode_id, "out_dir": paths.relp(out_dir), "files": {}, "errors": {}}
    mlt_file = None
    for name, fn in (("mlt", lambda: export_mlt.export(r, out_dir)),
                     ("fcpxml", lambda: export_fcpxml.export(r, out_dir)),
                     ("otio", lambda: export_otio.export(r, out_dir))):
        try:
            f = fn()
            summary["files"][name] = paths.relp(f)
            if name == "mlt":
                mlt_file = f
        except Exception as e:  # report, never hide
            summary["errors"][name] = f"{type(e).__name__}: {e}"
    if absolute:
        try:
            f = export_fcpxml.export(r, out_dir, absolute=True)
            summary["files"]["fcpxml_local"] = paths.relp(f)
        except Exception as e:
            summary["errors"]["fcpxml_local"] = f"{type(e).__name__}: {e}"
    master = Path(master) if master else paths.absp(r.output_path)
    if mlt_file is not None:
        if verify:
            res = verify_project.verify(r, master, mlt_file)
        else:
            res = {"status": "unmeasured", "why": "검증을 건너뜀(--no-verify)"}
            prev = read_json(out_dir / "verify.json", {}) or {}
            if not prev.get("global"):
                from ..util.jsonio import write_json

                write_json(out_dir / "verify.json", {"schema": "shortkit.project_verify/1", "episode_id": r.episode_id,
                                                     "checked_at": now_iso(), "status": "unmeasured",
                                                     "status_ko": "못 잼", "why": res["why"]})
        summary["verify"] = {k: res.get(k) for k in ("status", "why")}
        if res.get("global"):
            summary["verify"].update({k: res["global"].get(k) for k in ("ssim_overall", "ssim_worst_second",
                                                                        "mad_overall", "audio_env_corr")})
    for name in ("fcpxml", "otio"):
        if name in summary["files"]:
            verify_project.verify(r, master, paths.absp(summary["files"][name]))
    summary["readme"] = paths.relp(write(r, out_dir, decisions or {}))
    return summary


def _print_summary(s: dict) -> None:
    print(f"[프로젝트] {s['episode_id']} → {s['out_dir']}")
    for k, f in s["files"].items():
        print(f"  내보냄 {k}: {f}")
    for k, e in s["errors"].items():
        print(f"  [실패] {k}: {e}")
    v = s.get("verify") or {}
    st = {"pass": "통과", "fail": "불일치", "unmeasured": "못 잼"}.get(v.get("status"), "못 잼")
    line = f"  melt 렌더 비교: {st}"
    if v.get("ssim_overall") is not None:
        line += (f" (SSIM 전체 {v['ssim_overall']}, 최저 1초 {v['ssim_worst_second']}, 평균 절대차 {v['mad_overall']}, "
                 f"소리 포락선 상관 {v['audio_env_corr']})")
    if v.get("why"):
        line += f" — {v['why']}"
    print(line)
    print(f"  README: {s.get('readme')}")
    print("  확인 못 함(못 잼): Shotcut/Kdenlive GUI 열기, Resolve/FCP 가져오기, 사람의 시청·청취")


def cmd_export(args) -> int:
    r = load_resolved(args.episode)
    s = export_project(r, master=Path(args.master) if args.master else None, verify=not args.no_verify,
                       absolute=args.absolute, decisions=plan_decisions(r.episode_id))
    _print_summary(s)
    if s["errors"] or "mlt" not in s["files"]:
        return 1
    return 0 if (s.get("verify") or {}).get("status") in ("pass", None) or args.no_verify else 2


def cmd_verify(args) -> int:
    from . import verify_project

    r = load_resolved(args.episode)
    pf = paths.absp(f"episodes/{r.episode_id}/project/{r.episode_id}.mlt")
    master = Path(args.master) if args.master else paths.absp(r.output_path)
    res = verify_project.verify(r, master, pf)
    g = res.get("global") or {}
    print(f"melt 렌더 비교: {res['status_ko']}" + (f" — {res.get('why')}" if res.get("why") else ""))
    if g:
        print(f"  SSIM 전체 {g.get('ssim_overall')} / 최저 1초 {g.get('ssim_worst_second')} / 평균 절대차 "
              f"{g.get('mad_overall')} / 소리 포락선 상관 {g.get('audio_env_corr')}")
    write(r, pf.parent, plan_decisions(r.episode_id))
    return {"pass": 0, "fail": 2}.get(res["status"], 3)


def cmd_readme(args) -> int:
    r = load_resolved(args.episode)
    f = write(r, paths.absp(f"episodes/{r.episode_id}/project"), plan_decisions(r.episode_id))
    print(f"README: {paths.relp(f)}")
    return 0


def register(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="project_cmd", required=True)
    e = sub.add_parser("export", help="MLT/FCPXML/OTIO + captions + melt 검증 + README")
    e.add_argument("--episode", required=True)
    e.add_argument("--master", default=None, help="비교할 마스터 MP4 (기본: resolved.output_path)")
    e.add_argument("--no-verify", action="store_true", help="melt 렌더 비교 생략(결과는 못 잼으로 기록)")
    e.add_argument("--absolute", action="store_true", help="이 기계 전용 절대 경로 FCPXML(<id>.local.fcpxml)도 생성")
    e.set_defaults(func=cmd_export)
    v = sub.add_parser("verify", help="기존 .mlt 를 melt 로 렌더해 마스터와 비교")
    v.add_argument("--episode", required=True)
    v.add_argument("--master", default=None)
    v.set_defaults(func=cmd_verify)
    rd = sub.add_parser("readme", help="README.md 만 다시 생성")
    rd.add_argument("--episode", required=True)
    rd.set_defaults(func=cmd_readme)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m shortkit.edit.project_readme",
                                 description="편집 프로젝트 내보내기(MLT/FCPXML/OTIO)·melt 검증·README")
    register(ap)
    a = ap.parse_args(argv)
    return int(a.func(a) or 0)


if __name__ == "__main__":
    sys.exit(main())
