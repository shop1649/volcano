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
    """
    ap = plan.get("approval") or {}
    prod = plan.get("mode") == "production"
    required = (prod and bool(preset_requires)) or (prod and ap.get("required") is True)
    approved = bool(ap.get("approved"))
    cur = plan_sha256(plan)
    return {"required": required, "approved": approved, "approved_by": ap.get("approved_by"),
            "approved_at": ap.get("approved_at"), "approved_plan_sha256": ap.get("approved_plan_sha256"),
            "plan_sha256": cur, "first_episode": is_first_episode(plan),
            "changed_since_approval": bool(approved and ap.get("approved_plan_sha256")
                                           and ap.get("approved_plan_sha256") != cur)}


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
