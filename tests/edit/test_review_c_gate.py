"""Review wave 2 (group C) regression tests: fixed-style overrides and the first-episode approval gate.

S1-08 / S2QA-09  plan overrides of fixed style values (zoom/freeze/transition/blink ...) are reported
S3-01            approval must be backed by evidence (sha + approval_log + stored snapshot); a later
                 production episode needs an approved + rendered first episode of the same preset
S3-02            ``episode approve`` refuses a plan with validation errors; the approved sheet is kept
S3-11            three DISTINCT title candidates
Temp project root + synthetic media (tests/edit/conftest.py)."""
from __future__ import annotations

import copy
import json
from types import SimpleNamespace

import yaml

from .conftest import codes, load_preset, write_plan
from .test_validate import run


def _where(iss, code):
    return {i["where"] for i in iss if i["code"] == code}


def _sev(iss, code):
    return {i["severity"] for i in iss if i["code"] == code}


# ----------------------------------------------------------------------------- S1-08 / S2QA-09
def test_fixed_style_overrides_are_reported(root, plan):
    pr = load_preset()
    plan["timeline"][0]["zoom"] = {"center": [160, 90], "dur": 0.9, "ease": "linear", "scale_to": 1.6}
    plan["timeline"][1]["transition_in"] = {"type": "flash", "dur": 0.5}
    plan["decorations"] = [{"id": "d1", "kind": "arrow", "start": 0.5, "end": 1.5, "blink_hz": 4.0,
                            "keyframes": [{"t": 0.0, "x": 900, "y": 300}]}]
    iss = run(root, plan)
    w = _where(iss, "style_override")
    assert {"timeline[s1].zoom.dur", "timeline[s1].zoom.ease", "timeline[s1].zoom.scale_to",
            "timeline[s2].transition_in.dur", "timeline[s2].freeze.hold", "decorations[d1].blink_hz"} <= w, iss
    # crossfade dur 0.25 == preset motion.transitions.crossfade.dur_s: not an override
    assert pr.peek("motion.transitions.crossfade.dur_s") == 0.25
    assert "timeline[s3].transition_in.dur" not in w
    assert _sev(iss, "style_override") == {"warn"}           # test mode: reported, not blocking
    plan["mode"] = "production"
    assert "error" in _sev(run(root, plan), "style_override")


def test_caption_position_override_only_for_speaker(root, plan):
    plan["captions"][1]["pos"] = [540, 900]                 # situation caption moved by the plan
    assert "captions[c_s].pos" in _where(run(root, plan), "style_override")
    plan["captions"][1]["pos"] = None
    plan["captions"].append({"id": "c_p", "role": "speaker", "text": "남성", "start": 0.5, "end": 1.5,
                             "pos": [500, 700], "grounding": {"kind": "seen", "source": "a", "src_t": 1.0}})
    assert not {w for w in _where(run(root, plan), "style_override") if w.startswith("captions")}


# ----------------------------------------------------------------------------- S3-01
def _prod(plan, idx):
    p = copy.deepcopy(plan)
    p["mode"] = "production"
    p["episode_index"] = idx
    return p


def test_handwritten_approval_is_not_an_approval(root, plan):
    from shortkit.edit.plan import approval_state_for

    p = _prod(plan, 1)
    p["approval"] = {"approved": True}
    iss = run(root, p, for_render=True, allow_unmeasured=True)
    assert "approval_required" in codes(iss, "error")
    assert "approval_evidence_missing" in codes(iss, "error")
    assert approval_state_for(p, load_preset())["approved"] is False


def test_later_episode_needs_approved_and_rendered_first_episode(root, plan):
    from shortkit.edit import plan as plan_mod

    p2 = _prod(plan, 2)
    iss = run(root, p2, for_render=True, allow_unmeasured=True)
    assert "series_first_episode" in codes(iss, "error"), iss
    # an approved (with evidence) and rendered production episode 1 of the same preset
    p1 = _prod(plan, 1)
    p1["episode_id"] = "e1"
    write_plan(root, p1)
    plan_mod.record_approval("e1", p1, by="tester", proposal_text=f"plan_sha256: `{plan_mod.plan_sha256(p1)}`\n")
    assert "series_first_episode" in codes(run(root, p2, for_render=True, allow_unmeasured=True), "error")
    plan_mod.append_log("e1", {"event": "render", "plan_sha256": plan_mod.plan_sha256(p1), "output": "x.mp4"})
    assert "series_first_episode" not in codes(run(root, p2, for_render=True, allow_unmeasured=True))
    # another preset's first episode does not count
    other = yaml.safe_load((root / "episodes/e1/plan.yaml").read_text())
    other["preset_id"] = "other-v1"
    (root / "episodes/e1/plan.yaml").write_text(yaml.safe_dump(other, allow_unicode=True))
    assert "series_first_episode" in codes(run(root, p2, for_render=True, allow_unmeasured=True), "error")


# ----------------------------------------------------------------------------- S3-02
def test_approve_refuses_plan_with_errors_and_keeps_snapshot(root, plan, monkeypatch):
    from shortkit.edit import cli, plan as plan_mod

    p = _prod(plan, 1)
    p["title_candidates"] = []
    write_plan(root, p)
    args = SimpleNamespace(episode_id="t1", preset=None, allow_unmeasured=True, by="reviewer", note=None)
    assert cli.cmd_proposal(args) == 0
    assert cli.cmd_approve(args) == 1                       # proposal_incomplete etc.: refused
    assert not (yaml.safe_load((root / "episodes/t1/plan.yaml").read_text()).get("approval") or {}).get("approved")
    # a plan whose only remaining issue is the approval itself is approved, and the approved sheet is kept
    p["title_candidates"] = ["가나", "다라", "마바"]
    write_plan(root, p)
    real = cli.validate

    def only_approval(*a, **k):          # simulate an otherwise clean plan (the temp root has no measured preset)
        res = real(*a, **k)
        keep = lambda iss: [i for i in iss if i["code"] in ("approval_required",) or i["severity"] == "warn"]
        return (keep(res[0]), res[1]) if isinstance(res, tuple) else keep(res)

    monkeypatch.setattr(cli, "validate", only_approval)
    assert cli.cmd_proposal(args) == 0
    assert cli.cmd_approve(args) == 0
    sha = plan_mod.plan_sha256(p)
    snap = root / "episodes/t1/approvals" / sha
    assert (snap / "proposal.md").is_file() and (snap / "plan.json").is_file()
    assert sha in (snap / "proposal.md").read_text()
    approved = plan_mod.load_plan("t1")
    assert plan_mod.approval_evidence(approved)["ok"], plan_mod.approval_evidence(approved)
    # a change after approval: recorded (no re-approval), shown in the regenerated sheet, the snapshot survives
    txt = (root / "episodes/t1/plan.yaml").read_text()
    (root / "episodes/t1/plan.yaml").write_text(txt.replace("마바", "사아"))
    monkeypatch.setattr(cli, "validate", real)
    assert cli.cmd_proposal(args) == 0
    sheet = (root / "episodes/t1/proposal.md").read_text()
    assert "승인 뒤 바뀜" in sheet and "제목 후보" in sheet and sha[:12] in sheet
    assert "마바" in (snap / "proposal.md").read_text()
    iss = run(root, plan_mod.load_plan("t1"), for_render=True, allow_unmeasured=True)
    msg = " ".join(i["message_ko"] for i in iss if i["code"] == "approval_plan_changed")
    assert "제목 후보" in msg
    assert "approval_required" not in codes(iss)


# ----------------------------------------------------------------------------- S3-11
def test_three_distinct_title_candidates(root, plan):
    p = _prod(plan, 1)
    p["title_candidates"] = ["교실의 순간들", "교실의 순간들", "교실의  순간들 "]
    assert "proposal_incomplete" in codes(run(root, p), "error")
    p["title_candidates"] = ["교실의 순간들", "창가의 남성", "고개를 든 사람"]
    assert "proposal_incomplete" not in codes(run(root, p))
