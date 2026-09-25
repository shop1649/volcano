"""Final gate (docs/CONTRACT.md section 10).

The gate passes only when
  G1  no row is ``different`` without ``intended_change``
  G2  no required row is ``unmeasured``
  G3  SFX without an event = 0 (the ``audio.sfx.no_event`` row is ``same``)
  G4  every SFX lies within +-max_event_offset_s of its event (all ``audio.sfx.offset`` rows ``same``)
  G5  the report measured THE DELIVERABLE (``resolved.output_path``) and that file on disk is the one that was
      measured (sha256 unchanged since the QA run)
  G6  the inputs the rows were judged against (preset layers, formats / SFX catalog, plan, resolved edit, ASS,
      human check records) are unchanged since the QA run -- otherwise the saved rows are stale
  R1  (production) the output was compared with a reference video at the same absolute times: the format's
      representative video from formats.yaml (or another video with a recorded override reason), its analysis
      files, and the compare sheet (test mode: warning)
  A1  (production) a first episode (episode_index 1) was rendered without an approved proposal
Production additionally requires (``complete``):
  P1  no preset key is still unmeasured (provisional) -- unmeasured never becomes complete
  P2  no style-vs-reference row is ``unmeasured``
  P3  the plan is a production plan (test-mode outputs are never publishable)
  P4  no other row is ``unmeasured`` either (a not-required 못 잼 row is still not a measured item) unless the row
      names the required row that makes the same judgement (``covered_by``) and that row was measured
"""
from __future__ import annotations

from .checks import CAT


def covered(row: dict, by_id: dict[str, dict]) -> bool:
    """A not-required 못 잼 row whose judgement is made by another (measured) row, e.g. a per-caption font row
    covered by the per-role pooled font row."""
    cb = row.get("covered_by")
    if not cb:
        return False
    other = by_id.get(cb)
    return other is not None and other.get("status") != "unmeasured"


def reference_problems(reference: dict | None) -> list[str]:
    """Why the same-time reference comparison does not count (empty = it does)."""
    ref = reference or {}
    out = []
    rep = ref.get("representative") or {}
    if not ref.get("video_id"):
        out.append("레퍼런스 영상 없음" + (f" — {rep.get('reason')}" if rep.get("reason") else ""))
        return out
    if rep.get("video_id") and ref.get("video_id") != rep.get("video_id") and not ref.get("override_reason"):
        out.append(f"레퍼런스 {ref.get('video_id')} 는 포맷 {rep.get('format_id')} 의 대표 영상 {rep.get('video_id')} 가 아님"
                   "(--reference-override-reason 기록 없음)")
    if not rep.get("video_id") and not ref.get("override_reason"):
        out.append("포맷의 대표 영상을 formats.yaml 에서 확인하지 못함" + (f": {rep.get('reason')}" if rep.get("reason") else "")
                   + " — 다른 영상을 쓰려면 --reference-override-reason 필요")
    if not ref.get("path"):
        out.append("레퍼런스 MP4 없음(프레임 비교 못 함)")
    need = {"captions", "shots", "audio_sfx_events"}
    miss = sorted(need - set(ref.get("analysis_files") or []))
    if miss:
        out.append("레퍼런스 분석 파일 없음: " + ", ".join(miss))
    if not ref.get("sheets"):
        out.append("비교 시트 없음")
    return out


def evaluate(rows: list[dict], *, mode: str, mp4_sha_measured: str | None, mp4_sha_now: str | None,
             unmeasured_preset_keys: list[str], production: bool | None = None, checked_at: str | None = None,
             plan: dict | None = None, reference: dict | None = None, measured_path: str | None = None,
             deliverable_path: str | None = None, inputs_measured: dict | None = None,
             inputs_now: dict | None = None) -> dict:
    from ..util.jsonio import now_iso

    production = (mode == "production") if production is None else production
    fails: list[dict] = []
    warns: list[dict] = []
    by_id = {r["row_id"]: r for r in rows}

    diff = [r for r in rows if r["status"] == "different" and not r.get("intended_change")]
    if diff:
        fails.append({"rule": "G1", "message": f"의도하지 않은 차이(다르다) {len(diff)}건",
                      "rows": [r["row_id"] for r in diff]})
    req_un = [r for r in rows if r["status"] == "unmeasured" and r.get("required")]
    if req_un:
        fails.append({"rule": "G2", "message": f"필수 항목 못 잼 {len(req_un)}건 — 못 잼은 완료가 아님",
                      "rows": [r["row_id"] for r in req_un]})
    ne = [r for r in rows if r["check_id"] == "audio.sfx.no_event"]
    if not ne:
        if any(r["check_id"].startswith("audio.") for r in rows):
            fails.append({"rule": "G3", "message": "사건 없는 효과음 검사 행이 없음", "rows": []})
    elif any(r["status"] != "same" for r in ne):
        fails.append({"rule": "G3", "message": "사건 없는 효과음이 0 이 아님(또는 못 잼)", "rows": [r["row_id"] for r in ne]})
    off = [r for r in rows if r["check_id"] == "audio.sfx.offset" and r["status"] != "same"]
    if off:
        fails.append({"rule": "G4", "message": f"사건과의 시차 초과/못 잼 효과음 {len(off)}건", "rows": [r["row_id"] for r in off]})
    if measured_path and deliverable_path and str(measured_path) != str(deliverable_path):
        fails.append({"rule": "G5", "message": f"보고서가 납품 MP4({deliverable_path})가 아닌 파일({measured_path})을 측정함 — "
                                               "`shortkit qa run --episode` 로 납품 파일을 다시 검수", "rows": []})
    if mp4_sha_now is None:
        fails.append({"rule": "G5", "message": "출력 MP4 가 없음", "rows": []})
    elif mp4_sha_measured and mp4_sha_now != mp4_sha_measured:
        fails.append({"rule": "G5", "message": "QA 이후 출력 MP4 가 바뀜 — 다시 `shortkit qa run` 필요", "rows": []})
    if inputs_measured is not None and inputs_now is not None:
        changed = sorted(k for k in set(inputs_measured) | set(inputs_now) if inputs_measured.get(k) != inputs_now.get(k))
        if changed:
            fails.append({"rule": "G6", "message": "QA 이후 판정 기준 파일이 바뀜(저장된 행이 낡음) — 다시 `shortkit qa run` 필요",
                          "rows": changed})
    elif inputs_now is not None and inputs_measured is None:
        fails.append({"rule": "G6", "message": "보고서에 판정 기준 파일 지문이 없음(이전 형식) — 다시 `shortkit qa run` 필요",
                      "rows": []})

    # same-absolute-time comparison with the format's representative video
    if reference is not None:
        rp = reference_problems(reference)
        if rp:
            (fails if production else warns).append(
                {"rule": "R1", "message": "레퍼런스 같은 시각 비교 없음/불충분: " + "; ".join(rp), "rows": []})

    # first episode of a preset: the proposal must have been approved before rendering
    ap = (plan or {}).get("approval") or {}
    if mode == "production" and (plan or {}).get("episode_index") == 1 and ap.get("required", True) and not ap.get("approved"):
        fails.append({"rule": "A1", "message": "첫 에피소드 제안서가 승인되지 않은 채 렌더됨", "rows": []})
    style_un = [r for r in rows if r.get("kind") == "style_vs_reference" and r["status"] == "unmeasured"]
    other_un = [r for r in rows if r["status"] == "unmeasured" and not r.get("required")
                and r.get("kind") != "style_vs_reference" and not covered(r, by_id)]
    prod_fail: list[dict] = []
    if unmeasured_preset_keys:
        prod_fail.append({"rule": "P1", "message": f"프리셋 미측정(임시값) 키 {len(unmeasured_preset_keys)}개",
                          "rows": unmeasured_preset_keys[:50]})
    if style_un:
        prod_fail.append({"rule": "P2", "message": f"레퍼런스 대비 못 잼 {len(style_un)}건",
                          "rows": [r["row_id"] for r in style_un]})
    if mode != "production":
        prod_fail.append({"rule": "P3", "message": "테스트 모드 출력(파이프라인 검증용) — 게시 불가", "rows": []})
    if other_un:
        prod_fail.append({"rule": "P4", "message": f"필수 표시가 없는 못 잼 {len(other_un)}건 — 못 잰 항목은 완료로 치지 않음",
                          "rows": [r["row_id"] for r in other_un]})
    if production:
        fails.extend(prod_fail)
    else:
        warns.extend(prod_fail)
    missing_cats = sorted(set(CAT[k] for k in ("text_pos", "cut", "music", "original", "sfx_no_event", "identity",
                                                "loudness")) - {r["category"] for r in rows})
    if missing_cats and len(rows) > 5:
        warns.append({"rule": "W1", "message": "행이 없는 필수 분류: " + ", ".join(missing_cats), "rows": []})
    passed = not fails
    n_un = sum(1 for r in rows if r["status"] == "unmeasured")
    n_un_nonreq = sum(1 for r in rows if r["status"] == "unmeasured" and not r.get("required"))
    complete = passed and not prod_fail
    verdict = ("통과" if passed else "불합격")
    if passed and not complete:
        verdict += " (완료 아님: " + ", ".join(p["rule"] for p in prod_fail) + ")"
    verdict += f" — 못 잼 {n_un}건(필수 {n_un - n_un_nonreq}, 참고 {n_un_nonreq})"
    return {"pass": passed, "complete": complete, "mode": mode, "production_rules": production,
            "checked_at": checked_at or now_iso(), "failures": fails, "warnings": warns,
            "unmeasured": {"total": n_un, "required": n_un - n_un_nonreq, "not_required": n_un_nonreq,
                           "not_required_uncovered": len(other_un) + len(style_un)},
            "verdict_ko": verdict}


def gate_episode(episode_id: str, production: bool | None = None) -> dict:
    """Re-evaluate the gate from the saved report + THE DELIVERABLE currently on disk (resolved.output_path) + the
    judging inputs now (their fingerprints must equal the ones the rows were measured against)."""
    from .. import paths
    from ..config import load_preset
    from ..util.hashing import sha256_file
    from ..util.jsonio import read_json, read_yaml
    from .report import input_fingerprints

    ep = paths.episode_dir(episode_id)
    rep = read_json(ep / "qa" / "report.json")
    if rep is None:
        return {"pass": False, "complete": False, "failures": [{"rule": "G0", "message": "QA 보고서 없음 — 먼저 `shortkit qa run`",
                                                                "rows": []}], "warnings": [], "verdict_ko": "불합격"}
    rj = read_json(ep / "build" / "resolved.json") or {}
    deliverable = rj.get("output_path") or f"episodes/{episode_id}/output/{episode_id}.mp4"
    mp4 = paths.absp(deliverable)
    sha_now = sha256_file(mp4) if mp4.is_file() else None
    fmt = rep.get("format_id") if rep.get("format_id") not in (None, "UNCLASSIFIED") else None
    pr = load_preset(rep["preset_name"], fmt)
    try:
        inputs_now = input_fingerprints(episode_id, pr)
    except Exception as e:  # a fingerprint that cannot be taken is a reason to re-run, never to pass silently
        inputs_now = {"error": f"{type(e).__name__}: {e}"}
    return evaluate(rep["rows"], mode=rep.get("mode", "test"), mp4_sha_measured=rep["output"].get("sha256"),
                    mp4_sha_now=sha_now, unmeasured_preset_keys=pr.unmeasured_keys(), production=production,
                    plan=read_yaml(ep / "plan.yaml"), reference=rep.get("reference") or {},
                    measured_path=rep["output"].get("path"), deliverable_path=paths.relp(mp4),
                    inputs_measured=rep.get("inputs"), inputs_now=inputs_now)
