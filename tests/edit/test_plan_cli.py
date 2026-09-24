"""plan.py (sha, approval block writing) and the CLI flow: new -> validate -> proposal -> approve."""
from __future__ import annotations

import yaml

from .conftest import base_plan, write_plan


def test_sha_excludes_approval(root):
    from shortkit.edit.plan import plan_sha256

    p = base_plan(root)
    a = plan_sha256(p)
    p["approval"] = {"approved": True}
    assert plan_sha256(p) == a
    p["captions"][1]["text"] = "다른 자막"
    assert plan_sha256(p) != a


def test_replace_top_level_block_keeps_comments():
    from shortkit.edit.plan import replace_top_level_block

    txt = "# head\nschema: x\napproval:\n  approved: false\n# keep me\nsources: []\n"
    out = replace_top_level_block(txt, "approval", "approval:\n  approved: true\n")
    assert out == "# head\nschema: x\napproval:\n  approved: true\n# keep me\nsources: []\n"
    out2 = replace_top_level_block("schema: x\n", "approval", "approval: {a: 1}\n")
    assert out2 == "schema: x\napproval: {a: 1}\n"


def test_cli_new_validate(root, capsys):
    from shortkit.cli import main

    assert main(["episode", "new", "ep-a", "--mode", "test"]) == 0
    txt = (root / "episodes/ep-a/plan.yaml").read_text()
    assert "format_id: UNCLASSIFIED" in txt and "mode: test" in txt
    rc = main(["episode", "validate", "ep-a"])
    out = capsys.readouterr().out
    assert rc == 1 and "source_missing" in out          # template points at a TODO source


def test_cli_proposal_approve_flow(root, capsys):
    from shortkit.cli import main
    from shortkit.edit.plan import load_plan, plan_sha256

    p = base_plan(root, mode="production")
    p["episode_id"] = "ep-b"
    p["episode_index"] = 1
    write_plan(root, p)
    assert main(["episode", "approve", "ep-b", "--by", "홍길동"]) == 1          # no proposal yet
    assert main(["episode", "proposal", "ep-b"]) == 0
    md = (root / "episodes/ep-b/proposal.md").read_text()
    for h in ("## 소재", "## 구간 시트", "## 표지 문구", "## 제목 후보 3종", "## 자막", "## 효과음 배치표", "## BGM", "## 미측정 영향"):
        assert h in md, h
    assert plan_sha256(load_plan("ep-b")) in md
    # render gate: first production episode not approved -> validate --for-render fails on approval
    capsys.readouterr()
    main(["episode", "validate", "ep-b", "--for-render"])
    assert "approval_required" in capsys.readouterr().out
    assert main(["episode", "approve", "ep-b", "--by", "홍길동"]) == 0
    plan = load_plan("ep-b")
    ap = plan["approval"]
    assert ap["approved"] is True and ap["approved_by"] == "홍길동" and ap["approved_plan_sha256"] == plan_sha256(plan)
    txt = (root / "episodes/ep-b/plan.yaml").read_text()
    assert yaml.safe_load(txt)["captions"] == p["captions"]
    capsys.readouterr()
    main(["episode", "validate", "ep-b", "--for-render"])
    assert "approval_required" not in capsys.readouterr().out
    # a later edit of the approved plan is recorded, never re-asked; proposal sha now differs
    plan["captions"][1]["text"] = "고친 자막"
    write_plan(root, plan)
    capsys.readouterr()
    main(["episode", "validate", "ep-b", "--for-render"])
    out = capsys.readouterr().out
    assert "approval_required" not in out and "approval_plan_changed" in out
    assert main(["episode", "approve", "ep-b", "--by", "홍길동"]) == 1          # stale proposal is refused
