"""Episode plan I/O: load + JSON-schema validation, canonical sha256, approval block updates.

``episodes/<episode_id>/plan.yaml`` is validated against ``shortkit/schema/plan.schema.json``
(authoritative).  The plan sha256 is computed over canonical JSON of the plan WITHOUT the
``approval`` block, so recording an approval does not change the hash that was approved.
"""
from __future__ import annotations

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from .. import paths
from ..util.jsonio import read_json, read_yaml

SCHEMA_FILE = Path(__file__).resolve().parent.parent / "schema" / "plan.schema.json"
TEST_FORMAT_ID = "UNCLASSIFIED"


class PlanError(ValueError):
    """Plan could not be loaded or does not satisfy the JSON schema."""

    def __init__(self, message: str, errors: list[str] | None = None):
        super().__init__(message)
        self.errors = errors or []


@lru_cache(maxsize=1)
def schema() -> dict:
    return read_json(SCHEMA_FILE)


def plan_path(episode_id: str) -> Path:
    return paths.episode_dir(episode_id) / "plan.yaml"


def build_dir(episode_id: str) -> Path:
    return paths.episode_dir(episode_id) / "build"


def schema_errors(plan: Any) -> list[str]:
    """Human-readable JSON-schema violations (Korean prefix, JSON-pointer location)."""
    import jsonschema

    v = jsonschema.Draft202012Validator(schema())
    out = []
    for e in sorted(v.iter_errors(plan), key=lambda e: [str(p) for p in e.absolute_path]):
        where = "/".join(str(p) for p in e.absolute_path) or "(최상위)"
        out.append(f"{where}: {e.message}")
    return out


def validate_schema(plan: Any) -> None:
    errs = schema_errors(plan)
    if errs:
        raise PlanError("plan.yaml 이 스키마(shortkit/schema/plan.schema.json)와 맞지 않습니다:\n  - "
                        + "\n  - ".join(errs), errs)


def load_plan(episode_id_or_path: str | Path, *, check_schema: bool = True) -> dict:
    """Load a plan by episode id (``episodes/<id>/plan.yaml``) or by path; schema-validate it."""
    p = Path(episode_id_or_path)
    if p.suffix in (".yaml", ".yml") or p.is_file():
        path = paths.absp(p)
    else:
        path = plan_path(str(episode_id_or_path))
    if not path.is_file():
        raise PlanError(f"plan.yaml 이 없습니다: {_rel_or_name(path)}")
    try:
        plan = read_yaml(path)
    except yaml.YAMLError as e:
        raise PlanError(f"plan.yaml YAML 문법 오류: {e}") from None
    if not isinstance(plan, dict):
        raise PlanError("plan.yaml 최상위가 매핑이 아닙니다")
    if check_schema:
        validate_schema(plan)
    if path.parent.name != plan.get("episode_id"):
        raise PlanError(f"폴더 이름({path.parent.name})과 plan.episode_id({plan.get('episode_id')})가 다릅니다")
    return plan


def _rel_or_name(p: Path) -> str:
    try:
        return paths.relp(p)
    except Exception:
        return p.name


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def plan_sha256(plan: dict) -> str:
    """sha256 of canonical JSON of the plan without its ``approval`` block."""
    body = {k: v for k, v in plan.items() if k != "approval"}
    return hashlib.sha256(canonical_json(body).encode("utf-8")).hexdigest()


APPROVAL_FIRST_KEY = "approval.first_episode_requires_approval"
APPROVAL_LATER_KEY = "approval.later_episodes_require_approval"


def is_first_episode(plan: dict) -> bool:
    """episode_index 1 = first episode.  A plan WITHOUT an index is treated as a first episode
    (the approval gate must not be skipped just because the index was left out)."""
    idx = plan.get("episode_index")
    return idx is None or int(idx) <= 1


def approval_rule_key(plan: dict) -> str:
    """The preset key that decides whether THIS episode needs approval (first vs later episodes)."""
    return APPROVAL_FIRST_KEY if is_first_episode(plan) else APPROVAL_LATER_KEY


def approval_state_for(plan: dict, preset) -> dict:
    """The approval gate: reads the preset rule for this episode's index (traced ``Preset.get``:
    ``approval.first_episode_requires_approval`` for episode 1, ``approval.later_episodes_require_approval``
    for episode_index > 1) and returns ``approval_state``."""
    key = approval_rule_key(plan)
    rule = preset.get(key)
    if not isinstance(rule, bool):
        raise PlanError(f"프리셋 {key}={rule!r}: true/false 만 허용")
    st = approval_state(plan, rule)
    st["rule_key"] = key
    return st


def approval_state(plan: dict, preset_requires: bool) -> dict:
    """Approval facts for gates/reports.

    ``preset_requires`` is the preset rule for THIS episode's index (``approval_state_for`` reads it:
    first_episode_requires_approval for episode 1 / no index, later_episodes_require_approval for
    episode_index > 1).  required: production & that rule (a plan may also set approval.required: true
    explicitly; it can never switch the rule off).  Test mode never needs approval.

    ``approved`` is true only when the approval block is backed by evidence (``approval_evidence``: the
    approved plan sha256, an ``approve`` event with that sha in approval_log.jsonl and the stored snapshot of
    the approved proposal + plan written by ``shortkit episode approve``).  A hand-written
    ``approval: {approved: true}`` is ``approval_claimed`` but not approved (S3-01).
    """
    ap = plan.get("approval") or {}
    prod = plan.get("mode") == "production"
    required = (prod and bool(preset_requires)) or (prod and ap.get("required") is True)
    claimed = bool(ap.get("approved"))
    ev = approval_evidence(plan) if claimed else {"ok": False, "problems": [], "snapshot": None}
    approved = claimed and ev["ok"]
    cur = plan_sha256(plan)
    return {"required": required, "approved": approved, "approval_claimed": claimed,
            "evidence_problems": ev["problems"], "snapshot": ev.get("snapshot"),
            "approved_by": ap.get("approved_by"),
            "approved_at": ap.get("approved_at"), "approved_plan_sha256": ap.get("approved_plan_sha256"),
            "plan_sha256": cur, "first_episode": is_first_episode(plan),
            "changed_since_approval": bool(approved and ap.get("approved_plan_sha256")
                                           and ap.get("approved_plan_sha256") != cur)}


# ----------------------------------------------------------------------------- approval evidence (S3-01 / S3-02)
APPROVALS_DIR = "approvals"
SNAPSHOT_SHA_LINE = re.compile(r"plan_sha256:\s*`?([0-9a-f]{64})`?")


def approval_log_path(episode_id: str) -> Path:
    return paths.episode_dir(episode_id) / "approval_log.jsonl"


def approval_log(episode_id: str) -> list[dict]:
    from ..util.jsonio import read_jsonl

    return [r for r in read_jsonl(approval_log_path(episode_id)) if isinstance(r, dict)]


def append_log(episode_id: str, row: dict) -> dict:
    from ..util.jsonio import append_jsonl, now_iso

    r = {"at": now_iso(), **row}
    append_jsonl(approval_log_path(episode_id), r)
    return r


def snapshot_dir(episode_id: str, sha: str) -> Path:
    """episodes/<id>/approvals/<approved plan sha256>/ : proposal.md + plan.json exactly as approved."""
    return paths.episode_dir(episode_id) / APPROVALS_DIR / sha


def _file_sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def approval_evidence(plan: dict) -> dict:
    """Is the plan's approval block backed by what ``shortkit episode approve`` records?

    Required: ``approved_plan_sha256`` and ``approved_by`` set; an ``approve`` event with that sha in
    approval_log.jsonl; the snapshot ``approvals/<sha>/proposal.md`` (embedding that sha, same file sha256 as
    the log row) and ``approvals/<sha>/plan.json`` (whose plan sha256 is that sha).
    -> ``{ok, problems[], snapshot}``."""
    ap = plan.get("approval") or {}
    eid = plan.get("episode_id") or ""
    problems: list[str] = []
    sha = ap.get("approved_plan_sha256")
    if not sha:
        problems.append("approved_plan_sha256 없음(승인한 plan 판을 알 수 없음)")
    if not str(ap.get("approved_by") or "").strip():
        problems.append("approved_by 없음(승인한 사람 기록 없음)")
    snap = None
    if sha:
        rows = [r for r in approval_log(eid) if r.get("event") == "approve" and r.get("plan_sha256") == sha]
        if not rows:
            problems.append(f"approval_log.jsonl 에 plan_sha256 {sha[:12]}… 의 approve 기록 없음")
        d = snapshot_dir(eid, sha)
        prop, pj = d / "proposal.md", d / "plan.json"
        snap = {"dir": paths.relp(d) if d.is_dir() else None, "proposal": None, "plan": None}
        if not prop.is_file():
            problems.append(f"승인한 제안서 사본 없음({APPROVALS_DIR}/{sha[:12]}…/proposal.md)")
        else:
            m = SNAPSHOT_SHA_LINE.search(prop.read_text(encoding="utf-8"))
            if not m or m.group(1) != sha:
                problems.append("승인한 제안서 사본의 plan_sha256 이 승인 기록과 다름")
            fsha = _file_sha(prop)
            snap["proposal"] = paths.relp(prop)
            if rows and rows[-1].get("proposal_sha256") and rows[-1]["proposal_sha256"] != fsha:
                problems.append("승인한 제안서 사본이 승인 뒤 바뀜(파일 sha256 불일치)")
        if not pj.is_file():
            problems.append(f"승인한 plan 사본 없음({APPROVALS_DIR}/{sha[:12]}…/plan.json)")
        else:
            try:
                snap_plan = json.loads(pj.read_text(encoding="utf-8"))
                if plan_sha256(snap_plan) != sha:
                    problems.append("승인한 plan 사본의 sha256 이 승인 기록과 다름")
                snap["plan"] = paths.relp(pj)
            except (OSError, ValueError) as e:
                problems.append(f"승인한 plan 사본을 읽지 못함: {e}")
    return {"ok": not problems, "problems": problems, "snapshot": snap}


def approved_snapshot_plan(plan: dict) -> dict | None:
    """The plan exactly as approved (approvals/<sha>/plan.json), or None."""
    sha = (plan.get("approval") or {}).get("approved_plan_sha256")
    if not sha:
        return None
    p = snapshot_dir(plan.get("episode_id") or "", sha) / "plan.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# sections of a plan an approver sees in the proposal (proposal.py headings)
SECTION_KO = {"sources": "소재", "timeline": "구간 시트", "cover": "표지 문구", "title_candidates": "제목 후보",
              "captions": "자막", "sfx": "효과음 배치표", "bgm": "BGM", "decorations": "장식", "reveal": "반전 보호",
              "format_id": "포맷", "episode_index": "회차", "mode": "모드", "preset_id": "프리셋", "notes": "메모",
              "output": "출력", "actions": "중요 동작"}


def plan_diff_sections(old: dict, new: dict) -> list[dict]:
    """Top-level sections that differ between the approved plan and the current one (approval excluded):
    ``[{key, ko, detail}]`` with item ids added/removed/changed for list sections."""
    out = []
    keys = sorted((set(old) | set(new)) - {"approval"})
    for k in keys:
        a, b = old.get(k), new.get(k)
        if canonical_json(a) == canonical_json(b):
            continue
        detail = ""
        if isinstance(a, list) and isinstance(b, list) and all(isinstance(x, dict) and "id" in x for x in a + b):
            ia, ib = {x["id"]: x for x in a}, {x["id"]: x for x in b}
            add = sorted(set(ib) - set(ia))
            rem = sorted(set(ia) - set(ib))
            chg = sorted(i for i in set(ia) & set(ib) if canonical_json(ia[i]) != canonical_json(ib[i]))
            parts = ([f"추가 {add}"] if add else []) + ([f"삭제 {rem}"] if rem else []) + ([f"변경 {chg}"] if chg else [])
            detail = ", ".join(parts)
        elif isinstance(a, list) and isinstance(b, list):
            detail = f"{a} → {b}"
        out.append({"key": k, "ko": SECTION_KO.get(k, k), "detail": detail})
    return out


def record_approval(episode_id: str, plan: dict, *, by: str, proposal_text: str, note: str | None = None,
                    required: bool | None = None, validation: dict | None = None) -> dict:
    """Store the evidence of an approval (``shortkit episode approve``): snapshot of the approved proposal and
    plan under approvals/<sha>/, an ``approve`` event in approval_log.jsonl (with the snapshot sha256s), and the
    approval block in plan.yaml.  Returns the approval block."""
    from ..util.jsonio import now_iso

    sha = plan_sha256(plan)
    m = SNAPSHOT_SHA_LINE.search(proposal_text)
    if not m or m.group(1) != sha:
        raise PlanError("제안서의 plan_sha256 이 현재 plan 과 다릅니다: 제안서를 다시 만든 뒤 승인하세요")
    d = snapshot_dir(episode_id, sha)
    d.mkdir(parents=True, exist_ok=True)
    (d / "proposal.md").write_text(proposal_text, encoding="utf-8")
    body = {k: v for k, v in plan.items() if k != "approval"}
    (d / "plan.json").write_text(json.dumps(body, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    approval = {"required": bool(required) if required is not None else bool((plan.get("approval") or {}).get("required")),
                "approved": True, "approved_by": by, "approved_at": now_iso(), "approved_plan_sha256": sha,
                "note": note}
    append_log(episode_id, {"event": "approve", "by": by, "plan_sha256": sha, "required": approval["required"],
                            "snapshot": paths.relp(d), "proposal_sha256": _file_sha(d / "proposal.md"),
                            "plan_snapshot_sha256": _file_sha(d / "plan.json"), "validation": validation})
    write_approval(episode_id, approval)
    return approval


# ----------------------------------------------------------------------------- series (S3-01)
def _rendered_after_approval(episode_id: str, sha: str) -> dict | None:
    rows = approval_log(episode_id)
    seen_approve = False
    for r in rows:
        if r.get("event") == "approve" and r.get("plan_sha256") == sha:
            seen_approve = True
        elif seen_approve and r.get("event") == "render" and r.get("output"):
            return r
    return None


def series_first_episode(plan: dict) -> dict:
    """For a PRODUCTION plan with episode_index > 1: the first production episode of the same preset
    (episode_index 1 or no index) must exist in episodes/, be approved with evidence (``approval_evidence``)
    and have been rendered after its approval.  -> ``{ok, first: [episode ids], problems[]}``."""
    out = {"ok": True, "first": [], "problems": []}
    if plan.get("mode") != "production" or is_first_episode(plan):
        return out
    base = paths.absp("episodes")
    cands = []
    for pp in sorted(base.glob("*/plan.yaml")) if base.is_dir() else []:
        if pp.parent.name == plan.get("episode_id"):
            continue
        try:
            other = read_yaml(pp)
        except Exception:        # an unreadable plan is not a first episode
            continue
        if not isinstance(other, dict) or other.get("mode") != "production" \
                or other.get("preset_id") != plan.get("preset_id") or other.get("episode_id") != pp.parent.name:
            continue
        try:
            if not is_first_episode(other):
                continue
        except (TypeError, ValueError):     # malformed episode_index: not a valid first episode
            continue
        cands.append(other)
    if not cands:
        out.update(ok=False, problems=[f"같은 프리셋({plan.get('preset_id')})의 production 첫 편(episode_index 1)이 "
                                       "episodes/ 에 없음"])
        return out
    probs = []
    for o in cands:
        ev = approval_evidence(o) if (o.get("approval") or {}).get("approved") else \
            {"ok": False, "problems": ["승인 기록 없음"]}
        if not ev["ok"]:
            probs.append(f"{o['episode_id']}: 승인 증거 없음({'; '.join(ev['problems'])})")
            continue
        r = _rendered_after_approval(o["episode_id"], o["approval"]["approved_plan_sha256"])
        if r is None:
            probs.append(f"{o['episode_id']}: 승인 뒤 렌더 기록 없음(approval_log.jsonl render)")
            continue
        out["first"].append(o["episode_id"])
    if not out["first"]:
        out.update(ok=False, problems=probs)
    return out


# ----------------------------------------------------------------------------- writing
_TOP_KEY = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:")


def replace_top_level_block(text: str, key: str, block_yaml: str) -> str:
    """Replace (or append) the top-level ``key:`` block in YAML text, keeping every other line
    (comments included) untouched."""
    lines = text.splitlines(keepends=True)
    start = end = None
    for i, ln in enumerate(lines):
        m = _TOP_KEY.match(ln)
        if start is None:
            if m and m.group(1) == key:
                start = i
        else:
            if m or (ln.strip() and not ln[:1].isspace() and not ln.lstrip().startswith("#")):
                end = i
                break
    if not block_yaml.endswith("\n"):
        block_yaml += "\n"
    if start is None:
        sep = "" if (not text or text.endswith("\n")) else "\n"
        return text + sep + block_yaml
    if end is None:
        end = len(lines)
    # keep trailing comment lines that belong to the next block
    while end > start + 1 and lines[end - 1].lstrip().startswith("#"):
        end -= 1
    return "".join(lines[:start]) + block_yaml + "".join(lines[end:])


def write_approval(episode_id: str, approval: dict) -> dict:
    """Write the approval block into plan.yaml (other text preserved) and re-validate."""
    path = plan_path(episode_id)
    text = path.read_text(encoding="utf-8")
    block = yaml.safe_dump({"approval": approval}, allow_unicode=True, sort_keys=False, width=110)
    new_text = replace_top_level_block(text, "approval", block)
    plan = yaml.safe_load(new_text)
    validate_schema(plan)
    if (plan.get("approval") or {}) != approval:
        raise PlanError("approval 블록을 plan.yaml 에 정확히 쓰지 못했습니다")
    tmp = path.with_suffix(".yaml.tmp.write")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(path)
    return plan
