"""Defect records: ``episodes/<id>/qa/defects.jsonl``.

One record per failing row (``different`` without intended change, or a required row that is
``unmeasured``)::

    {id, check_id, row_id, episode_id, found_at, found, description, fix, fix_notes[], status,
     recheck_same_cases[], final_gate, last_seen_at, history[]}

Lifecycle (every ``shortkit qa run`` does this automatically):
    open ─(qa defects fix --note)→ fix_submitted ─(re-run: row passes)→ fixed   (fix note + same-case re-check)
                                            └──(re-run: row still fails)→ reopened
    open/reopened ─(re-run: row passes, NO fix note)→ resolved_without_fix  (not 'fixed': the audit trail needs
            the fix; ``qa defects fix --note`` then makes it 'fixed' on the next run)
    fixed / resolved_without_fix ─(later run fails again)→ reopened
    active ─(re-run: row is 못 잼 and not required)→ stays active with an ``unmeasured_now`` event (a row that can no
            longer be measured is not a fixed row) -- EXCEPT when the row names the required row that now makes the
            same judgement (``covered_by``, e.g. per-caption font rows -> the per-role pooled font row) and that row
            was measured: then ``superseded`` (NOT fixed)
'fixed' also requires the same-case re-check: after each run every defect that is open/reopened or was fixed in
this run is re-checked on the OTHER episodes that have a render (same check_id, measured on their MP4) and the
result is appended to ``recheck_same_cases``; with no other rendered episode an explicit ``no_other_episodes``
entry is recorded, and a run with ``--no-recheck-others`` leaves a fixed defect ``fixed_unrechecked`` until a run
re-checks it.  ``final_gate`` always holds the latest gate result.
Records closed as 'fixed' by an older version without a fix note are reclassified ``resolved_without_fix`` on the
next run (history event ``reclassified``); their real fix is not invented.
"""
from __future__ import annotations

from pathlib import Path

ACTIVE = ("open", "fix_submitted", "reopened")
# passing now but the audit trail is incomplete (no fix note / no same-case re-check): listed by default
NEEDS_RECORD = ("resolved_without_fix", "fixed_unrechecked")
CLOSED = ("fixed", "superseded")


def path_for(episode_id: str) -> Path:
    from .. import paths

    return paths.episode_dir(episode_id) / "qa" / "defects.jsonl"


def load(episode_id: str) -> list[dict]:
    from ..util.jsonio import read_jsonl

    return read_jsonl(path_for(episode_id))


def save(episode_id: str, items: list[dict]) -> None:
    from ..util.jsonio import write_jsonl

    write_jsonl(path_for(episode_id), items)


def failing(rows: list[dict]) -> list[dict]:
    return [r for r in rows if (r["status"] == "different" and not r.get("intended_change"))
            or (r["status"] == "unmeasured" and r.get("required"))]


def _desc(r: dict) -> str:
    from .report import _fmt

    kind = "못 잼(필수)" if r["status"] == "unmeasured" else "다르다"
    return (f"{r['item']}: {kind} — 기대 {_fmt(r.get('expected'), 80)} / 측정 {_fmt(r.get('observed'), 80)}"
            + (f" ({r['note']})" if r.get("note") else ""))


def _next_id(items: list[dict]) -> str:
    n = 0
    for d in items:
        try:
            n = max(n, int(str(d["id"]).lstrip("D")))
        except ValueError:
            continue
    return f"D{n + 1:03d}"


def _has_fix(d: dict) -> bool:
    return bool(d.get("fix") or d.get("fix_notes"))


def _reclassify_legacy(items: list[dict], now: str) -> int:
    """'fixed' records without a fix note (closed by an older rule) -> resolved_without_fix (history kept)."""
    n = 0
    for d in items:
        if d.get("status") == "fixed" and not _has_fix(d):
            d["status"] = "resolved_without_fix"
            d.setdefault("history", []).append({"at": now, "event": "reclassified", "from": "fixed",
                                                "note": "고침 기록(fix) 없이 'fixed' 로 닫혔던 결함 — 'fixed' 는 고침 메모와 같은 사례 "
                                                        "재검사가 있어야 함. 실제 고침 내용은 추측해 채우지 않음: "
                                                        "`shortkit qa defects fix --note` 로 기록하면 다음 실행에서 fixed"})
            n += 1
    return n


def sync(ctx, report: dict, recheck_others: bool = True, quiet: bool = False) -> dict:
    from ..util.jsonio import now_iso

    ep = ctx.episode_id
    items = load(ep)
    now = now_iso()
    rows = {r["row_id"]: r for r in report["rows"]}
    fail = {r["row_id"]: r for r in failing(report["rows"])}
    gate = {"pass": report["gate"]["pass"], "complete": report["gate"]["complete"], "checked_at": now,
            "mp4_sha256": report["output"]["sha256"]}
    stats = {"new": 0, "verified_now": 0, "reopened": 0, "still_open": 0, "not_rechecked": 0,
             "resolved_without_fix": 0, "unmeasured_now": 0, "superseded": 0,
             "reclassified": _reclassify_legacy(items, now)}
    by_row = {d["row_id"]: d for d in items}
    touched: list[dict] = []
    fixed_now: list[dict] = []
    for d in items:
        r = rows.get(d["row_id"])
        if r is None:
            if d["status"] in ACTIVE:
                d.setdefault("history", []).append({"at": now, "event": "not_rechecked",
                                                    "note": "이번 실행에 해당 검사 행이 없음"})
                stats["not_rechecked"] += 1
            continue
        failed = d["row_id"] in fail
        if d["status"] in ACTIVE or d["status"] in NEEDS_RECORD:
            if failed:
                if d["status"] in ("fix_submitted",) + NEEDS_RECORD:
                    was = d["status"]
                    d["status"] = "reopened"
                    d["history"].append({"at": now, "event": "reopened", "observed": r.get("observed"),
                                         "note": "수정 후 다시 측정했지만 여전히 실패" if was == "fix_submitted"
                                         else "다시 실패함"})
                    stats["reopened"] += 1
                else:
                    stats["still_open"] += 1
                d["last_seen_at"] = now
                d["last_observed"] = r.get("observed")
            elif r["status"] == "unmeasured":
                cb = r.get("covered_by")
                cov = rows.get(cb) if cb else None
                if not r.get("required") and cov is not None and cov.get("status") != "unmeasured":
                    d["status"] = "superseded"
                    d["history"].append({"at": now, "event": "superseded", "status_now": r["status"], "covered_by": cb,
                                         "note": f"필수 판정이 {cb} 로 옮겨짐(그 행 {cov.get('status')}) — 고쳐진 것이 아님: "
                                                 + (r.get("note") or "")[:200]})
                    stats["superseded"] += 1
                else:
                    # a row that can no longer be measured is not a fixed row: keep the defect open
                    d["history"].append({"at": now, "event": "unmeasured_now", "status_now": r["status"],
                                         "required_now": bool(r.get("required")),
                                         "note": "이번 실행에서 못 잼(필수 아님) — 고쳐졌는지 확인되지 않아 열린 채로 둠: "
                                                 + (r.get("note") or "")[:200]})
                    d["last_seen_at"] = now
                    stats["unmeasured_now"] += 1
            elif _has_fix(d):
                if d["status"] != "fixed_unrechecked" or recheck_others:
                    d["history"].append({"at": now, "event": "verified_fixed", "status_now": r["status"],
                                         "observed": r.get("observed")})
                d["status"] = "fixed"          # confirmed after the same-case re-check below
                d["verified_at"] = now
                fixed_now.append(d)
                stats["verified_now"] += 1
            elif d["status"] != "resolved_without_fix":
                d["status"] = "resolved_without_fix"
                d["history"].append({"at": now, "event": "resolved_without_fix", "status_now": r["status"],
                                     "observed": r.get("observed"),
                                     "note": "행이 더 이상 실패하지 않지만 고침 기록이 없음 — 'fixed' 아님. "
                                             "`shortkit qa defects fix --note` 로 무엇을 고쳤는지 기록해야 함"})
                stats["resolved_without_fix"] += 1
            touched.append(d)
        elif d["status"] in CLOSED and failed:
            d["status"] = "reopened"
            d["history"].append({"at": now, "event": "regressed", "observed": r.get("observed")})
            stats["reopened"] += 1
            touched.append(d)
    for rid, r in fail.items():
        if rid in by_row:
            continue
        d = {"id": _next_id(items), "check_id": r["check_id"], "row_id": rid, "episode_id": ep, "found_at": now,
             "found": _desc(r), "description": _desc(r), "category": r["category"], "fix": None, "fix_notes": [],
             "status": "open", "recheck_same_cases": [], "final_gate": None, "last_seen_at": now,
             "last_observed": r.get("observed"), "evidence": r.get("evidence"),
             "history": [{"at": now, "event": "found", "status": r["status"]}]}
        items.append(d)
        by_row[rid] = d
        touched.append(d)
        stats["new"] += 1
    for d in items:
        d["final_gate"] = gate
    rechecked = []
    others = other_episodes(ep) if recheck_others else []
    if recheck_others and touched and others:
        rechecked = recheck_other_episodes(ep, sorted({d["check_id"] for d in touched}), quiet=quiet)
        for d in touched:
            for rc in rechecked:
                res = rc["results"].get(d["check_id"])
                if res is None:
                    continue
                d["recheck_same_cases"].append({"episode_id": rc["episode_id"], "checked_at": rc["checked_at"],
                                                "check_id": d["check_id"], **res})
    elif recheck_others and touched:
        for d in touched:
            d["recheck_same_cases"].append({"episode_id": None, "checked_at": now, "check_id": d["check_id"],
                                            "verdict": "no_other_episodes",
                                            "note": "렌더된 다른 에피소드가 없어 같은 사례 재검사 대상 없음"})
    # 'fixed' needs the same-case re-check on record
    for d in fixed_now:
        if not any(str(rc.get("checked_at") or "") >= now for rc in d.get("recheck_same_cases") or []):
            d["status"] = "fixed_unrechecked"
            d["history"].append({"at": now, "event": "fixed_unrechecked",
                                 "note": "고침은 확인됐지만 같은 사례 재검사 기록이 없음(--no-recheck-others) — 다음 qa run 에서 재검사"})
    save(ep, items)
    stats["open"] = sum(1 for d in items if d["status"] in ACTIVE)
    stats["needs_record"] = sum(1 for d in items if d["status"] in NEEDS_RECORD)
    stats["total"] = len(items)
    stats["rechecked_other_episodes"] = [f"{rc['episode_id']}: " + ", ".join(
        f"{k}={v['verdict']}" for k, v in rc["results"].items()) for rc in rechecked]
    return stats


def other_episodes(exclude: str) -> list[str]:
    from .. import paths
    from ..util.jsonio import read_json

    root = paths.project_root() / "episodes"
    out = []
    if not root.is_dir():
        return out
    for d in sorted(root.iterdir()):
        if d.name == exclude or not (d / "build" / "resolved.json").is_file():
            continue
        rj = read_json(d / "build" / "resolved.json") or {}
        mp4 = paths.absp(rj.get("output_path") or f"episodes/{d.name}/output/{d.name}.mp4")
        if mp4.is_file():
            out.append(d.name)
    return out


def recheck_other_episodes(exclude: str, check_ids: list[str], limit: int = 10, quiet: bool = False) -> list[dict]:
    """Run the same checks (measured on each other episode's own MP4) and summarise."""
    from ..util.jsonio import now_iso
    from .report import run_and_write

    out = []
    for ep in other_episodes(exclude)[:limit]:
        try:
            part = run_and_write(ep, only=check_ids, quiet=True, write=False)
        except Exception as e:
            out.append({"episode_id": ep, "checked_at": now_iso(),
                        "results": {cid: {"verdict": "error", "error": f"{type(e).__name__}: {e}"[:200]} for cid in check_ids}})
            continue
        res = {}
        for cid in check_ids:
            rs = [r for r in part["rows"] if r["check_id"] == cid]
            if not rs:
                res[cid] = {"verdict": "not_applicable", "rows": {}}
                continue
            bad = failing(rs)
            un = [r for r in rs if r["status"] == "unmeasured"]
            res[cid] = {"verdict": "problem" if bad else ("unmeasured" if un and len(un) == len(rs) else "ok"),
                        "rows": {r["row_id"]: r["status"] for r in rs},
                        "mp4_sha256": part["output"]["sha256"]}
        out.append({"episode_id": ep, "checked_at": now_iso(), "results": res})
        if not quiet:
            print(f"[qa] 다른 에피소드 재확인 {ep}: " + ", ".join(f"{k}={v['verdict']}" for k, v in res.items()))
    return out


def add_fix(episode_id: str, defect_id: str, note: str, by: str | None = None) -> dict:
    from ..util.jsonio import now_iso

    items = load(episode_id)
    for d in items:
        if d["id"] == defect_id:
            now = now_iso()
            d["fix"] = note
            d.setdefault("fix_notes", []).append({"at": now, "note": note, "by": by})
            if d["status"] in ("open", "reopened", "fixed", "fixed_unrechecked", "resolved_without_fix"):
                d["status"] = "fix_submitted"
            d.setdefault("history", []).append({"at": now, "event": "fix_submitted", "note": note})
            save(episode_id, items)
            return d
    raise KeyError(f"{episode_id}: 결함 {defect_id} 없음")
