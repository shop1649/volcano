"""`shortkit episode ...` : plan scaffold, validation, first-episode approval, resolve, render, export."""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from .. import paths
from ..util.hashing import sha256_file
from ..util.jsonio import append_jsonl, now_iso, write_json
from ..util.media import ffmpeg, probe
from .plan import (PlanError, append_log, approval_state_for, approved_snapshot_plan, load_plan, plan_diff_sections,
                   plan_path, plan_sha256, record_approval)
from .validate import errors, format_issues, validate

# issues that an approval itself resolves: everything else must be fixed BEFORE approving (S3-02)
APPROVAL_CODES = ("approval_required", "approval_evidence_missing")

EXPORTERS = ("export_mlt", "export_fcpxml", "export_otio")


def register(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("new", help="episodes/<id>/plan.yaml 틀 만들기")
    s.add_argument("episode_id")
    s.add_argument("--preset", default="joshuamagazine")
    s.add_argument("--mode", choices=["test", "production"], default="production")
    s.add_argument("--format", default=None, help="formats.yaml 의 format_id (test 모드 기본 UNCLASSIFIED)")
    s.add_argument("--index", type=int, default=None, help="이 프리셋의 몇 번째 에피소드인지(1 = 첫 편, 승인 필요)")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_new)

    for name, fn, hlp in (("validate", cmd_validate, "plan 규칙 검사"),
                          ("proposal", cmd_proposal, "첫 편 승인용 제안서(proposal.md) 작성"),
                          ("resolve", cmd_resolve, "ResolvedEdit/ASS 생성(build/)"),
                          ("render", cmd_render, "마스터 MP4 렌더(검증·승인 관문 포함)"),
                          ("export", cmd_export, "편집 프로젝트 내보내기(MLT/FCPXML/OTIO)"),
                          ("all", cmd_all, "validate → resolve → render → export")):
        s = sub.add_parser(name, help=hlp)
        s.add_argument("episode_id")
        s.add_argument("--preset", default=None, help="프리셋 폴더 이름(생략 시 plan.preset_id 로 찾음)")
        if name in ("validate", "render", "all", "proposal", "resolve"):
            s.add_argument("--allow-unmeasured", action="store_true",
                           help="production 에서 미측정(못 잼) 스타일 키를 오류 대신 경고로 취급")
        if name == "validate":
            s.add_argument("--for-render", action="store_true", help="렌더 관문 기준(승인 필요 여부 포함)으로 검사")
            s.add_argument("--json", action="store_true")
        s.set_defaults(func=fn)

    s = sub.add_parser("approve", help="제안서 승인 기록(approved, approved_at, approved_plan_sha256) + 승인한 제안서·plan 사본 보관")
    s.add_argument("episode_id")
    s.add_argument("--by", required=True, help="승인한 사람 이름")
    s.add_argument("--note", default=None)
    s.add_argument("--preset", default=None)
    s.add_argument("--allow-unmeasured", action="store_true",
                   help="렌더와 같은 기준: production 에서 미측정(못 잼) 스타일 키를 오류 대신 경고로 취급")
    s.set_defaults(func=cmd_approve)

    s = sub.add_parser("test-source", help="테스트 소스: classroom.mp4 영상 + speech_02.wav 음성(원음 보존/덕킹 검증용)")
    s.add_argument("--at", type=float, default=19.6, help="음성을 넣을 소스 시각(s)")
    s.set_defaults(func=cmd_test_source)


# ----------------------------------------------------------------------------- helpers
def _load(args):
    from .resolve import preset_for_plan

    plan = load_plan(args.episode_id)
    preset = preset_for_plan(plan, getattr(args, "preset", None))
    return plan, preset


def _print_issues(issues):
    print(format_issues(issues))


def _log(episode_id: str, row: dict) -> None:
    append_log(episode_id, row)


def access_log_path(episode_id: str, command: str) -> Path:
    return paths.episode_dir(episode_id) / "build" / f"preset_access_{command}.json"


def save_access(episode_id: str, preset, command: str) -> Path | None:
    """Every command that consumes the preset saves its traced reads (``Preset.save_access_log``) to
    episodes/<id>/build/preset_access_<command>.json; ``shortkit preset sync`` collects them
    (``config.all_access_logs``) into the registry's code links."""
    if preset is None or not paths.episode_dir(episode_id).is_dir():
        return None
    p = access_log_path(episode_id, command)
    p.parent.mkdir(parents=True, exist_ok=True)
    preset.save_access_log(p)
    return p


# ----------------------------------------------------------------------------- new
PLAN_TEMPLATE = """# 에피소드 계획 (스키마: shortkit/schema/plan.schema.json)
# - 시간: sources/timeline 의 src_* 는 원본(소스) 시각, captions/sfx/decorations 는 출력 시각(초).
# - 좌표: sources[].clean / protected 는 원본 px, captions[].pos / decorations 는 캔버스 px({W}x{H}).
# - 고정 스타일(글꼴·색·위치 기본값 등)은 프리셋에 있다. 여기에는 이번 소재에서 새로 판단한 값만 쓴다.
# - 자막은 실제로 보고 들은 것만. 관계·동기·대사를 지어내지 않는다(grounding 필수).
# - 효과음은 화면 속 사건 때문에만(event 필수, kind: cut 금지, |t - event.t| <= {OFF}s).
schema: shortkit.plan/1
episode_id: {EID}
preset_id: {PID}
format_id: {FMT}
mode: {MODE}
episode_index: {IDX}
notes: ''
cover:
  text: ''                               # 표지 문구 = 표지 프레임(frame_t)에 실제로 보이는 자막 글자와 같아야 함
  frame_t: 0.0
title_candidates: []
sources:
- id: src1
  path: warehouse/sources/TODO.mp4      # 창고에 받은 소재(루트 기준 상대 경로)
  sha256: null
  warehouse_id: null                     # warehouse/candidates.jsonl 의 id
  has_embedded_music: null               # 원본에 음악이 섞였는지 true/false (원음을 살리면 필수; null = 못 잼)
  clean: {{crop: null, delogo: [], inpaint: [], blur: []}}
  protected: []                          # 얼굴/손/핵심 물체 {{label, x, y, w, h, start, end}} (원본 px/시각)
timeline:
- id: s1
  source: src1
  src_in: 0.0
  src_out: 3.0
  purpose: hook
captions: []
decorations: []
sfx: []
bgm:
  enabled: true
  path: null                             # null = 프리셋 audio.bgm.track_id
  silences: []
"""


def cmd_new(args) -> int:
    from .. import config

    path = plan_path(args.episode_id)
    if path.exists() and not args.force:
        print(f"이미 있습니다: {paths.relp(path)} (--force 로 덮어쓰기)")
        return 1
    pr = config.load_preset(args.preset)
    fmt = args.format or ("UNCLASSIFIED" if args.mode == "test" else "TODO_FORMAT_ID")
    idx = args.index if args.index is not None else 1
    txt = PLAN_TEMPLATE.format(W=pr.get("canvas.width"), H=pr.get("canvas.height"),
                               OFF=pr.get("audio.sfx.max_event_offset_s"), EID=args.episode_id, PID=pr.preset_id,
                               FMT=fmt, MODE=args.mode, IDX=idx)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(txt, encoding="utf-8")
    save_access(args.episode_id, pr, "new")
    print(f"만듦: {paths.relp(path)}  (소스·구간·자막·효과음을 채운 뒤 `shortkit episode validate {args.episode_id}`)")
    return 0


# ----------------------------------------------------------------------------- validate / proposal / approve
def cmd_validate(args) -> int:
    try:
        plan, preset = _load(args)
    except PlanError as e:
        print(f"[오류] {e}")
        return 1
    try:
        issues = validate(plan, preset, for_render=args.for_render, allow_unmeasured=args.allow_unmeasured)
    finally:
        save_access(args.episode_id, preset, "validate")
    if args.json:
        print(json.dumps(issues, ensure_ascii=False, indent=2))
    else:
        _print_issues(issues)
    return 1 if errors(issues) else 0


def cmd_proposal(args) -> int:
    from .proposal import write_proposal

    try:
        plan, preset = _load(args)
    except PlanError as e:
        print(f"[오류] {e}")
        return 1
    try:
        issues, ctx = validate(plan, preset, allow_unmeasured=getattr(args, "allow_unmeasured", False),
                               return_context=True)
        if ctx is None or ctx.resolved is None:
            _print_issues(issues)
            print("제안서를 만들 수 없습니다(스키마/프리셋 오류).")
            return 1
        p = write_proposal(plan, ctx, issues)
    finally:
        save_access(args.episode_id, preset, "proposal")
    print(f"제안서: {paths.relp(p)}  (plan_sha256 {plan_sha256(plan)[:12]}…)")
    ne = len(errors(issues))
    print(f"검증: 오류 {ne}건, 경고 {len(issues) - ne}건" + (" — 오류를 먼저 고치세요" if ne else ""))
    return 0


def cmd_approve(args) -> int:
    """Record an approval of the CURRENT proposal.md.  Refused when the proposal was made from another plan
    version, or when the plan has validation errors other than the missing approval itself (a proposal with
    missing title candidates / unresolved SFX / ... is not approvable: the approver must see the final items).
    The approved proposal and plan are kept under approvals/<sha>/ (``plan.record_approval``)."""
    from .proposal import proposal_path, proposal_sha

    try:
        plan, preset = _load(args)
    except PlanError as e:
        print(f"[오류] {e}")
        return 1
    sha = plan_sha256(plan)
    psha = proposal_sha(args.episode_id)
    if psha is None:
        print(f"[오류] proposal.md 가 없습니다: 먼저 `shortkit episode proposal {args.episode_id}`")
        return 1
    if psha != sha:
        print("[오류] proposal.md 가 현재 plan 과 다른 버전에서 만들어졌습니다. 제안서를 다시 만든 뒤 승인하세요.")
        return 1
    allow = bool(getattr(args, "allow_unmeasured", False))
    try:
        st = approval_state_for(plan, preset)
        issues = validate(plan, preset, for_render=True, allow_unmeasured=allow)
    except PlanError as e:
        print(f"[오류] {e}")
        return 1
    finally:
        save_access(args.episode_id, preset, "approve")
    blocking = [i for i in errors(issues) if i["code"] not in APPROVAL_CODES]
    if blocking:
        _print_issues(blocking)
        print("[오류] 승인 거부: 위 오류가 남은 제안서는 승인할 수 없습니다(승인자가 본 것이 렌더되는 것과 같아야 함). "
              "고친 뒤 제안서를 다시 만들고 승인하세요.")
        return 1
    try:
        record_approval(args.episode_id, plan, by=args.by, note=args.note, required=bool(st["required"]),
                        proposal_text=proposal_path(args.episode_id).read_text(encoding="utf-8"),
                        validation={"errors": 0, "warnings": len(issues), "allow_unmeasured": allow,
                                    "warning_codes": sorted({i["code"] for i in issues})})
    except PlanError as e:
        print(f"[오류] {e}")
        return 1
    print(f"승인 기록: {args.by} / plan_sha256 {sha[:12]}… — 승인한 제안서·plan 사본: "
          f"episodes/{args.episode_id}/approvals/{sha}/ (이후 수정은 재승인 없이 바뀐 부분만 기록됨)")
    return 0


# ----------------------------------------------------------------------------- resolve / render
def cmd_resolve(args) -> int:
    from .resolve import ResolveError, resolve_episode

    try:
        plan, preset = _load(args)
    except PlanError as e:
        print(f"[오류] {e}")
        return 1
    try:
        r = resolve_episode(args.episode_id, args.preset, allow_unmeasured=args.allow_unmeasured, preset=preset)
    except PlanError as e:
        print(f"[오류] {e}")
        return 1
    except ResolveError as e:
        _print_issues(e.issues)
        return 1
    finally:
        save_access(args.episode_id, preset, "resolve")
    print(f"resolved: {len(r.clips)}클립 {r.duration:.2f}s, 자막 {len(r.captions)}, 장식 {len(r.decorations)}, "
          f"효과음 {len(r.audio.sfx)} → episodes/{r.episode_id}/build/resolved.json, captions.ass")
    for w in r.warnings:
        print(f"  [경고] {w}")
    return 0


def _render(args) -> int:
    from .render import RenderError, render
    from .resolve import ResolveError, resolve_episode

    try:
        plan, preset = _load(args)
    except PlanError as e:
        print(f"[오류] {e}")
        return 1
    try:
        return _render_steps(args, plan, preset, render, RenderError, resolve_episode, ResolveError)
    finally:
        save_access(args.episode_id, preset, "render")


def _render_steps(args, plan, preset, render, RenderError, resolve_episode, ResolveError) -> int:
    issues = validate(plan, preset, for_render=True, allow_unmeasured=args.allow_unmeasured)
    _print_issues(issues)
    if errors(issues):
        print("렌더 중단: 위 오류를 먼저 고치세요.")
        return 1
    try:
        r = resolve_episode(args.episode_id, args.preset, allow_unmeasured=args.allow_unmeasured, preset=preset)
        out = render(r, allow_unmeasured=args.allow_unmeasured, preset=preset)
    except ResolveError as e:
        _print_issues(e.issues)
        return 1
    except RenderError as e:
        print(f"[렌더 실패] {e}")
        return 1
    st = approval_state_for(plan, preset)
    snap = approved_snapshot_plan(plan) if st["approved"] else None
    _log(args.episode_id, {"event": "render", "plan_sha256": st["plan_sha256"],
                           "approved_plan_sha256": st["approved_plan_sha256"],
                           "changed_since_approval": st["changed_since_approval"],
                           "changed_sections": plan_diff_sections(snap, plan) if snap is not None else None,
                           "output": paths.relp(out),
                           "output_sha256": sha256_file(out), "allow_unmeasured": args.allow_unmeasured})
    rep = json.loads((paths.episode_dir(args.episode_id) / "build" / "render_report.json").read_text())
    for w in (rep.get("audio") or {}).get("warnings") or []:
        print(f"  [렌더 경고] {w}")
    if plan["mode"] == "production":
        for row in mark_sources_used(plan):
            _log(args.episode_id, {"event": "warehouse_used", **row})
            print(f"  [창고] {row['warehouse_id']}: " + ("사용함(used) 기록" if row["ok"] else f"기록 실패 — {row['error']}"))
    au = rep.get("audio") or {}
    lo = au.get("loudness") or {}
    if lo:
        print(f"  [음량] 정규화 이득 {au.get('norm_gain_db')} dB (원했던 값 {lo.get('wanted_norm_gain_db')} dB), "
              f"전경 리미터 최대 {au.get('fg_limiter_max_reduction_db')} dB / 한도 {(au.get('limiter') or {}).get('max_limiter_db')} dB, "
              f"BGM 리미터 없음, mix {lo.get('mix_lufs')} LUFS (부족 {lo.get('shortfall_lu')} LU, {lo.get('status')})")
    ml = rep.get("mp4_loudness") or {}
    print(f"렌더 완료: {paths.relp(out)}  {rep['probe']['width']}x{rep['probe']['height']} "
          f"{rep['probe']['fps']}fps {rep['probe']['duration']:.2f}s, 음량 {ml.get('integrated_lufs')} LUFS "
          f"/ 최대 {ml.get('true_peak_db')} dBTP (기계 측정; 사람 청취 확인 아님)")
    return 0


def mark_sources_used(plan: dict) -> list[dict]:
    """After a successful PRODUCTION render: record usage of every linked warehouse source
    (``shortkit.sourcing.warehouse.mark_used``).  Returns one row per source with a warehouse_id."""
    rows = []
    wids = list(dict.fromkeys(s["warehouse_id"] for s in plan.get("sources", []) if s.get("warehouse_id")))
    if not wids:
        return rows
    try:
        from ..sourcing import warehouse as wh
    except ImportError as e:
        return [{"warehouse_id": w, "ok": False, "error": f"shortkit.sourcing.warehouse 없음: {e}"} for w in wids]
    for w in wids:
        try:
            wh.mark_used(w, plan["episode_id"], by="shortkit episode render")
            rows.append({"warehouse_id": w, "ok": True, "error": None})
        except Exception as e:  # never hide a failed provenance update
            rows.append({"warehouse_id": w, "ok": False, "error": f"{type(e).__name__}: {e}"})
    return rows


def cmd_render(args) -> int:
    return _render(args)


def cmd_export(args) -> int:
    try:
        plan, preset = _load(args)
    except PlanError as e:
        print(f"[오류] {e}")
        return 1
    try:
        return _export_steps(args, plan, preset)
    except PlanError as e:
        print(f"[오류] {e}")
        return 1
    finally:
        save_access(args.episode_id, preset, "export")


def _export_steps(args, plan, preset) -> int:
    from .resolve import load_resolved, resolve_episode

    try:
        r = load_resolved(args.episode_id)
    except FileNotFoundError:
        r = resolve_episode(args.episode_id, args.preset, preset=preset)
    out_dir = paths.episode_dir(args.episode_id) / "project"
    out_dir.mkdir(parents=True, exist_ok=True)
    master = paths.absp(r.output_path)
    produced, unavailable = {}, []
    for name in EXPORTERS:
        try:
            mod = importlib.import_module(f"shortkit.edit.{name}")
        except ImportError as e:
            unavailable.append(f"{name} ({e})")
            continue
        try:
            f = mod.export(r, out_dir)
            produced[name] = Path(f)
            print(f"내보냄: {name} → {paths.relp(f)}")
        except Exception as e:
            print(f"[실패] {name}: {type(e).__name__}: {e}")
    try:
        vp = importlib.import_module("shortkit.edit.verify_project")
        if master.is_file():
            for name, f in produced.items():
                try:
                    res = vp.verify(r, master, f)
                    print(f"검증 {name}: {json.dumps(res, ensure_ascii=False)[:300]}")
                except Exception as e:
                    print(f"[검증 실패] {name}: {type(e).__name__}: {e}")
        else:
            print("마스터 MP4 가 없어 프로젝트 검증을 건너뜀(먼저 render)")
    except ImportError as e:
        unavailable.append(f"verify_project ({e})")
    try:
        pr_mod = importlib.import_module("shortkit.edit.project_readme")
        st = approval_state_for(plan, preset)
        decisions = {"plan_sha256": st["plan_sha256"], "approval": st, "notes": plan.get("notes", ""),
                     "warnings": r.warnings, "provisional_keys": r.provisional_keys,
                     "sources": [{"id": s["id"], "path": s["path"], "sha256": s.get("sha256"),
                                  "warehouse_id": s.get("warehouse_id")} for s in plan["sources"]]}
        f = pr_mod.write(r, out_dir, decisions)
        print(f"README: {paths.relp(f)}")
    except ImportError as e:
        unavailable.append(f"project_readme ({e})")
    if unavailable:
        print("사용할 수 없는 내보내기 모듈: " + ", ".join(unavailable))
    return 0 if produced else 1


def cmd_all(args) -> int:
    try:
        plan, preset = _load(args)
    except PlanError as e:
        print(f"[오류] {e}")
        return 1
    try:
        st = approval_state_for(plan, preset)
    except PlanError as e:
        print(f"[오류] {e}")
        return 1
    finally:
        save_access(args.episode_id, preset, "all")
    if st["required"] and not st["approved"]:
        cmd_proposal(args)
        who = "첫 에피소드" if st["first_episode"] else f"{plan.get('episode_index')}번째 에피소드({st['rule_key']}=true)"
        print(f"{who}: 제안서를 확인한 뒤 `shortkit episode approve {args.episode_id} --by 이름` 후 다시 실행하세요.")
        return 3
    rc = _render(args)
    if rc:
        return rc
    return cmd_export(args)


# ----------------------------------------------------------------------------- test source
TEST_SOURCE = "assets/test/generated/classroom_voice.mp4"


def make_voice_test_source(at: float = 19.6, video: str = "assets/test/generated/video/classroom.mp4",
                           speech: str = "assets/test/generated/speech_02.wav", out: str = TEST_SOURCE) -> dict:
    """classroom.mp4 (no audio) + speech_02.wav placed at ``at`` seconds -> a test source with a real
    audible line, so kept-original-audio and ducking are exercised.  Synthetic (espeak-ng TTS)."""
    v, s, o = paths.absp(video), paths.absp(speech), paths.absp(out)
    for f in (v, s):
        if not f.is_file():
            raise FileNotFoundError(f"{paths.relp(f)} 없음: `python -m shortkit testassets synth|fetch-video` 먼저")
    dur = probe(v).duration
    ms = int(round(at * 1000))
    ffmpeg(["-i", v, "-i", s, "-filter_complex",
            f"[1:a]aresample=48000,adelay={ms}|{ms},apad,atrim=0:{dur:.6f},aformat=channel_layouts=stereo[a]",
            "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-fflags", "+bitexact", "-flags:a", "+bitexact", "-map_metadata", "-1", "-t", f"{dur:.6f}", o])
    truth = {"schema": "shortkit.testsource/1", "output": out, "sha256": sha256_file(o), "created_at": now_iso(),
             "video": video, "video_sha256": sha256_file(v), "speech": speech, "speech_sha256": sha256_file(s),
             "speech_at_s": at, "speech_dur_s": round(probe(s).duration, 6),
             "note": "합성 테스트 소스: 영상(Intel sample, CC BY 4.0, 무음)에 espeak-ng 한국어 TTS 한 줄을 얹음. "
                     "화면 속 인물의 실제 말이 아니다."}
    write_json(o.with_suffix(".truth.json"), truth)
    return truth


def cmd_test_source(args) -> int:
    t = make_voice_test_source(args.at)
    print(f"테스트 소스: {t['output']} sha256={t['sha256']} (음성 {t['speech_at_s']}s~{t['speech_at_s'] + t['speech_dur_s']:.2f}s)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="shortkit episode")
    register(ap)
    a = ap.parse_args()
    sys.exit(a.func(a))
