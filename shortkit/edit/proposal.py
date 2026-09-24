"""First-episode approval sheet: episodes/<id>/proposal.md (Korean).

Sections (headings fixed): 소재, 구간 시트, 표지 문구, 제목 후보 3종, 자막, 효과음 배치표, BGM, 미측정 영향.
The sheet embeds the plan sha256; ``shortkit episode approve`` refuses to approve a plan whose
proposal was generated for a different plan version.
"""
from __future__ import annotations

import re
from pathlib import Path

from .. import config, paths
from ..util.jsonio import now_iso
from ..util.stats import TRI_KO
from .plan import PlanError, approval_rule_key, approval_state, approval_state_for, plan_sha256
from .resolve import ResolveContext
from .sfxmap import MAP_STATUS_KO
from .validate import errors, warehouse_records

SHA_LINE = re.compile(r"plan_sha256:\s*`?([0-9a-f]{64})`?")
ROLE_KO = {"title": "제목", "description": "설명", "situation": "상황", "speaker": "인물", "dialogue": "대사",
           "reaction": "반응"}
GROUND_KO = {"seen": "화면에서 봄", "heard": "들림", "on_screen_text": "화면 글자", "source_metadata": "출처 정보",
             "framing": "편집 틀"}
MISSING = "못 잼"


def _peek(pr: config.Preset, key: str):
    """Display-only preset value for the report.  Deliberately NOT a traced read (``Preset.peek``):
    showing a value in a proposal is not production code using it, so it must not create a registry
    code link."""
    return pr.peek(key)


def overlap_accepted_unmeasured(rec: dict) -> dict | None:
    """The accepted-unmeasured entry for ``reference_overlap`` in a warehouse record's selection
    (the source was selected although the 'same recording as the reference' check was not done)."""
    for a in ((rec.get("selection") or {}).get("accepted_unmeasured") or []):
        key = a.get("key") if isinstance(a, dict) else a
        if key == "reference_overlap":
            return a if isinstance(a, dict) else {"key": key}
    return None


def tone_style_guide(pr: config.Preset) -> dict:
    """The script-writing style guide printed in the proposal (the sheet the first episode is approved
    on): the preset's register, emoji rule and measured sentence-ending examples.  Read through the
    preset (traced) -- the proposal is where the writer of the captions gets these values;
    ``validate.check_tone`` enforces register/emoji on the plan."""
    ex = pr.get("text.tone.sentence_end_examples")
    return {"register": pr.get("text.tone.register"), "emoji": pr.get("text.tone.emoji"),
            "sentence_end_examples": [str(x) for x in ex] if isinstance(ex, (list, tuple)) else ex,
            "origin": {k: pr.origin(f"text.tone.{k}") for k in ("register", "emoji", "sentence_end_examples")}}


def _v(x, unit: str = "") -> str:
    if x is None or x == "":
        return MISSING
    return f"{x}{unit}"


def _t(x: float) -> str:
    return f"{x:.2f}"


def _cell(s) -> str:
    return str(s).replace("|", "\\|").replace("\n", " / ")


def proposal_path(episode_id: str) -> Path:
    return paths.episode_dir(episode_id) / "proposal.md"


def proposal_sha(episode_id: str) -> str | None:
    p = proposal_path(episode_id)
    if not p.is_file():
        return None
    m = SHA_LINE.search(p.read_text(encoding="utf-8"))
    return m.group(1) if m else None


def build_proposal(plan: dict, ctx: ResolveContext, issues: list[dict]) -> str:
    pr: config.Preset = ctx.preset
    r = ctx.resolved
    sha = plan_sha256(plan)
    try:
        ap = approval_state_for(plan, pr)
    except PlanError as e:          # invalid approval rule: reported by validate (approval_rule); sheet still shown
        ap = {**approval_state(plan, True), "rule_key": approval_rule_key(plan), "rule_error": str(e)}
    L: list[str] = []
    L.append(f"# 제안서 — {plan['episode_id']}")
    L.append("")
    L.append(f"- 프리셋: `{plan['preset_id']}` / 포맷: `{plan['format_id']}` / 모드: `{plan['mode']}` / "
             f"회차: {plan.get('episode_index') or MISSING}")
    L.append(f"- plan_sha256: `{sha}`")
    L.append(f"- 작성 시각(UTC): {now_iso()}")
    rule = f"`{ap['rule_key']}`={_peek(pr, ap['rule_key'])}"
    need = (f"필요({rule})" if ap["required"] else
            ("불필요(test 모드)" if plan["mode"] != "production" else f"불필요({rule})"))
    if ap.get("rule_error"):
        need += f" — 승인 규칙 오류: {ap['rule_error']}"
    state = "승인됨" if ap["approved"] else "미승인"
    L.append(f"- 승인: {need} / 현재 {state}"
             + (f" ({ap['approved_by']}, {ap['approved_at']})" if ap["approved"] else ""))
    L.append(f"- 승인 방법: `python -m shortkit episode approve {plan['episode_id']} --by 이름` "
             "(승인 뒤 수정은 기록만 하고 다시 승인받지 않음)")
    ne = len(errors(issues))
    L.append(f"- 검증 결과: 오류 {ne}건, 경고 {len(issues) - ne}건"
             + (" — 오류가 있으면 승인해도 렌더되지 않음" if ne else ""))
    if plan.get("notes"):
        L.append(f"- 메모: {plan['notes']}")
    L.append("")

    # 소재
    L.append("## 소재")
    L.append("")
    recs = warehouse_records()
    L.append("| 소스 id | 파일 | sha256 | 플랫폼 | URL | 원작자 | 재게시자 | 조회수(확인 시각) | 게시일 | 선정 이유 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for s in plan["sources"]:
        rec = recs.get(s.get("warehouse_id") or "", {})
        views = rec.get("views")
        vtxt = (f"{views:,} ({_v(rec.get('views_checked_at'))})" if isinstance(views, int)
                else f"{MISSING} ({rec.get('views_source') or '창고 기록 없음'})")
        L.append("| " + " | ".join(_cell(x) for x in [
            s["id"], s["path"], (s.get("sha256") or MISSING)[:16] + ("…" if s.get("sha256") else ""),
            _v(rec.get("platform")), _v(rec.get("url")), _v(rec.get("original_author")), _v(rec.get("reposter")),
            vtxt, _v(rec.get("published_at")), _v(rec.get("selection_reason"))]) + " |")
    L.append("")
    for s in plan["sources"]:
        rec = recs.get(s.get("warehouse_id") or "")
        if not s.get("warehouse_id") or not rec:
            L.append(f"- {s['id']}: 창고 레코드 없음(warehouse_id={s.get('warehouse_id')!r}) → 출처 정보 {MISSING}")
            continue
        ov = overlap_accepted_unmeasured(rec)
        if ov is not None:
            L.append(f"- **주의 {s['id']}**: 레퍼런스와 같은 녹화인지 검사하지 못한 채(못 잼) 선택됨 — "
                     f"사유: {ov.get('reason') or MISSING}, 선택: {ov.get('by') or MISSING} {ov.get('at') or ''} "
                     f"/ 영향: {ov.get('impact') or '레퍼런스와 같은 녹화를 다시 쓸 위험(사용자 규칙 위반)'}")
        L.append(f"- {s['id']}: 창고 상태 {rec.get('status') or MISSING}, 음악 섞임 "
                 f"{ {True: '있다', False: '없다'}.get(s.get('has_embedded_music'), MISSING) }")
    L.append("")

    # 구간 시트
    L.append("## 구간 시트")
    L.append("")
    L.append("| 구간 | 소스 | 원본 시간(s) | 출력 시간(s) | 목적 | 확대 | 정지 | 들어오는 전환 | 원음 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    segs = {s["id"]: s for s in plan["timeline"]}
    for c in r.clips:
        seg = segs.get(c.id, {})
        z = (f"{c.zoom.scale_from}→{c.zoom.scale_to} @+{c.zoom.start}s {c.zoom.dur}s {c.zoom.ease}"
             if c.zoom else "없음")
        f = f"{c.freeze.hold}s (원본 {c.freeze.src_t:.2f}s)" if c.freeze else "없음"
        tr = c.transition_in.type + (f" {c.transition_in.dur}s" if c.transition_in.dur else "")
        oa = seg.get("original_audio") or {}
        o = (f"살림: {oa.get('reason', '')} ({oa.get('stem') or 'raw'}, 범위 {oa.get('ranges') or '전체'})"
             if oa.get("keep") else "끔")
        L.append("| " + " | ".join(_cell(x) for x in [
            c.id, c.source_id, f"{_t(c.src_in)}–{_t(c.src_out)}" + (f" ×{c.speed}" if c.speed != 1 else ""),
            f"{_t(c.out_start)}–{_t(c.out_end)}", c.purpose or "-", z, f, tr, o]) + " |")
    L.append(f"\n전체 길이: {r.duration:.2f}s\n")

    # 표지 문구
    L.append("## 표지 문구")
    L.append("")
    cov = plan.get("cover") or {}
    L.append(f"- 문구: {cov.get('text') or MISSING + ' (plan.cover.text 비어 있음)'}")
    L.append(f"- 표지 프레임: {_v(cov.get('frame_t'), 's')} / 프리셋 표지 방식: {_peek(pr, 'cover.source')}, "
             f"글자 역할: {_peek(pr, 'cover.text_role')}")
    L.append("")

    # 제목 후보
    L.append("## 제목 후보 3종")
    L.append("")
    tc = plan.get("title_candidates") or []
    for i in range(3):
        L.append(f"{i + 1}. {tc[i] if i < len(tc) else MISSING + ' (후보 부족)'}")
    L.append("")

    # 자막
    L.append("## 자막")
    L.append("")
    tg = tone_style_guide(pr)
    ko_origin = {"measured": "측정값", "provisional": "임시값·못 잼", "requested_change": "요청 변경"}
    ex = tg["sentence_end_examples"]
    L.append("### 말투 안내 (프리셋 text.tone)")
    L.append("")
    L.append(f"- 말투: {_v(tg['register'])} ({ko_origin.get(tg['origin']['register'], tg['origin']['register'])}) — "
             "제목·설명·상황·반응 자막에 검사(`episode validate`의 tone_register), 대사는 예외")
    L.append(f"- 이모지: {({True: '허용', False: '쓰지 않음'}).get(tg['emoji'], MISSING)} "
             f"({ko_origin.get(tg['origin']['emoji'], tg['origin']['emoji'])})")
    L.append("- 종결 어미 예시(레퍼런스 빈도 순): "
             + (", ".join(f"-{e}" for e in ex)
                + f" ({ko_origin.get(tg['origin']['sentence_end_examples'], tg['origin']['sentence_end_examples'])})"
                if ex else f"{MISSING}(측정 전 — 예시 없음, 말투는 위 기준만 검사)"))
    L.append("")
    pc = {c["id"]: c for c in plan.get("captions", [])}
    for role in ("title", "description", "situation", "speaker", "dialogue", "reaction"):
        caps = [c for c in r.captions if c.role == role]
        if not caps:
            continue
        L.append(f"### {ROLE_KO[role]} ({role})")
        L.append("")
        L.append("| id | 시간(s) | 문구 | 근거 |")
        L.append("|---|---|---|---|")
        for c in caps:
            g = pc.get(c.id, {}).get("grounding")
            gt = (f"{GROUND_KO.get(g['kind'], g['kind'])}"
                  + (f" · {g.get('source')}@{g.get('src_t')}s" if g.get("source") else "")
                  + (f" · {g.get('note')}" if g.get("note") else "")) if g else \
                ("근거 불필요(편집 틀 문구)" if role in ("title", "description") else "근거 없음")
            L.append(f"| {c.id} | {_t(c.start)}–{_t(c.end)} | {_cell(c.text)} | {_cell(gt)} |")
        L.append("")
    rv = plan.get("reveal") or {}
    if rv:
        L.append(f"반전 보호: {rv.get('t')}s 전 자막에 {rv.get('keywords')} 금지 — {rv.get('note', '')}")
        L.append("")

    # 효과음
    L.append("## 효과음 배치표")
    L.append("")
    L.append("| id | t(s) | 종류 | 사건 t(s) | 사건 | 차이(s) | 감정 | 파일 | 맵 상태 |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for s in r.audio.sfx:
        L.append("| " + " | ".join(_cell(x) for x in [
            s.id, _t(s.t), s.type, _t(s.event_t), s.event_desc, f"{s.t - s.event_t:+.2f}", _v(s.emotion),
            s.path or "미해결", MAP_STATUS_KO.get(s.map_status, s.map_status)]) + " |")
    L.append(f"\n효과음 {len(r.audio.sfx)}개. 컷 때문에 넣은 효과음은 없어야 하며, 모든 효과음은 사건과 "
             f"±{_peek(pr, 'audio.sfx.max_event_offset_s')}s 안.\n")

    # BGM
    L.append("## BGM")
    L.append("")
    b = r.audio.bgm
    if b is None:
        L.append("- BGM 사용 안 함(plan.bgm.enabled=false)")
    else:
        L.append(f"- 파일: {b.path or MISSING} / track_id: {b.track_id or '-'}")
        L.append(f"- 프리셋 곡 정보: 제목 {_v(_peek(pr, 'audio.bgm.title'))}, 버전 {_v(_peek(pr, 'audio.bgm.version'))}")
        L.append(f"- 사용 구간 시작: {b.section_start_s}s / 속도 비율: {b.tempo_ratio} / 레벨: {b.gain_db} dB / "
                 f"페이드 인 {b.fade_in_s}s · 아웃 {b.fade_out_s}s")
        L.append(f"- 덕킹(보존 대사 구간에서만): {[(round(a, 2), round(c, 2)) for a, c in b.duck_ranges] or '없음'}")
        L.append(f"- 의도적 정적: {[(round(a, 2), round(c, 2)) for a, c in b.silences] or '없음'}")
        L.append(f"- 원음 살린 구간: {[(o.clip_id, round(o.out_start, 2), round(o.out_end, 2), o.reason) for o in r.audio.originals] or '없음'}")
    L.append(f"- 목표 음량: {r.audio.target_lufs} LUFS, 최대 {r.audio.true_peak_db} dBTP")
    L.append("")

    # 미측정 영향
    L.append("## 미측정 영향")
    L.append("")
    prov = r.provisional_keys
    if not prov:
        L.append("이 에피소드가 읽은 프리셋 값은 모두 측정/규칙 값입니다.")
    else:
        L.append(f"이 에피소드가 읽은 프리셋 값 중 {len(prov)}개가 미측정(못 잼, 임시값)입니다. "
                 "아래 값은 레퍼런스와 같다고 말할 수 없습니다.")
        L.append("")
        L.append("| 키 | 현재(임시)값 | 영향 |")
        L.append("|---|---|---|")
        for k in prov:
            val = pr.peek(k)
            L.append(f"| `{k}` | {_cell(val)} | {_cell(config.impact_of(k))} |")
    unm = [i for i in issues if "unmeasured" in i["code"]]
    if unm:
        L.append("")
        L.append("검증에서 나온 미측정 항목:")
        for i in unm:
            L.append(f"- {i['code']}: {i['message_ko']}")
    L.append("")
    L.append(f"_범례: 있다/없다/못 잼 = {TRI_KO['present']}/{TRI_KO['absent']}/{TRI_KO['unmeasured']}_")
    return "\n".join(L) + "\n"


def write_proposal(plan: dict, ctx: ResolveContext, issues: list[dict]) -> Path:
    p = proposal_path(plan["episode_id"])
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(build_proposal(plan, ctx, issues), encoding="utf-8")
    return p
