"""Stage table rows added in review round R2 (preset_cli._stage_blockers -> unresolved.md):
- the reference's information-disclosure order (formats.yaml ``disclosure_order`` + per-format ``disclosure``);
- the SFX catalog's ``partial`` state with its ``unmeasured_columns``;
- the reference channel's identity templates (``ref identity-templates`` manifest).

Every file written here is a CLEARLY LABELLED SYNTHETIC FIXTURE ("synthetic_fixture": true) in a temporary project
root -- no reference video was measured."""
from __future__ import annotations

import json
import shutil

import pytest
import yaml

from shortkit import paths, preset_cli

P = "presets/joshuamagazine"
TDIR = f"{P}/reference/identity_templates"


@pytest.fixture()
def proj(tmp_path, monkeypatch):
    repo = paths.project_root()
    root = tmp_path / "proj"
    root.mkdir()
    shutil.copy(repo / "shortkit.root", root / "shortkit.root")
    shutil.copytree(repo / P, root / P, ignore=shutil.ignore_patterns("analysis", "videos", "access_logs",
                                                                       "measured.yaml", "settings_registry.yaml",
                                                                       "identity_templates"))
    (root / "warehouse").mkdir()
    (root / "episodes").mkdir()
    monkeypatch.setenv("SHORTKIT_ROOT", str(root))
    monkeypatch.chdir(root)
    return root


def rows(root) -> dict:
    return {s["item"]: s for s in preset_cli._stage_blockers("joshuamagazine")}


def ok_snapshot(root, at="2026-01-01T00:00:00+00:00"):
    (root / P / "reference/latest100.json").write_text(json.dumps({
        "schema": "shortkit.ref_snapshot/1", "status": "ok", "captured_at": at, "method": "SYNTHETIC",
        "synthetic_fixture": True, "videos": [{"rank": 1, "video_id": "vidR000001", "kind": "short", "duration": 20.0}]}),
        encoding="utf-8")


def formats(root, **over):
    fy = yaml.safe_load((root / P / "formats.yaml").read_text("utf-8"))
    fy.update(over)
    fy["synthetic_fixture"] = True
    (root / P / "formats.yaml").write_text(yaml.safe_dump(fy, allow_unicode=True), encoding="utf-8")


def test_disclosure_order_row(proj):
    r = rows(proj)[preset_cli.DISCLOSURE_ITEM]
    assert r["status"] == "unmeasured" and "포맷 표 없음" in r["evidence"]         # the real tree: blocked, no table
    ok_snapshot(proj)
    formats(proj, table=[{"format_id": "F1", "disclosure": {"status": "measured"}},
                         {"format_id": "F2", "disclosure": {"status": "unmeasured"}}],
            disclosure_order={"status": "partial", "blocker": "F2: 라벨 없는 구성원 2편 (SYNTHETIC)"})
    r = rows(proj)[preset_cli.DISCLOSURE_ITEM]
    assert (r["status"], r["state"]) == ("partial", "needs_manual_observation")
    assert "F1=measured" in r["evidence"] and "F2=unmeasured" in r["evidence"] and "SYNTHETIC" in r["evidence"]
    assert "반전" in r["impact"]
    formats(proj, disclosure_order={"status": "measured", "blocker": None})
    r = rows(proj)[preset_cli.DISCLOSURE_ITEM]
    assert (r["status"], r["state"], r["impact"]) == ("measured", "resolved", "없음")
    formats(proj, preset_id="other-preset-v1")
    r = rows(proj)[preset_cli.DISCLOSURE_ITEM]
    assert (r["status"], r["state"]) == ("unmeasured", "foreign_file")


def test_sfx_catalog_partial_row_shows_unmeasured_columns(proj):
    cat = {"schema": "shortkit.sfx_catalog/1", "preset_id": "joshuamagazine-v1", "status": "partial",
           "blocker": "감정(영상을 본 사람의 라벨) 못 잼 — 종류 2/3개 (SYNTHETIC)", "synthetic_fixture": True,
           "column_status": {"per_video_count": "measured", "prev_caption_role": "measured", "screen_event": "partial",
                             "emotion": "partial"},
           "unmeasured_columns": {"screen_event": ["whoosh_a"], "emotion": ["whoosh_a", "pop_b"]}, "types": []}
    (proj / P / "sfx_catalog.json").write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8")
    r = rows(proj)[preset_cli.SFX_CATALOG_ITEM]
    assert (r["status"], r["state"]) == ("partial", "needs_manual_observation")
    assert "unmeasured_columns" in r["evidence"] and "whoosh_a" in r["evidence"] and "pop_b" in r["evidence"]
    assert "감정" in r["impact"] and "화면 사건" in r["impact"] and "column_status" in r["evidence"]
    cat["unmeasured_columns"] = {"screen_event": ["whoosh_a"]}
    (proj / P / "sfx_catalog.json").write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8")
    assert rows(proj)[preset_cli.SFX_CATALOG_ITEM]["state"] == "insufficient_data"
    md = preset_cli.write_unresolved("joshuamagazine").read_text("utf-8")
    line = next(ln for ln in md.splitlines() if ln.startswith(f"| {preset_cli.SFX_CATALOG_ITEM}"))
    assert "| 일부 측정 |" in line and "whoosh_a" in line


def _manifest(root, **kw):
    m = {"schema": "shortkit.identity_templates/1", "preset_id": "joshuamagazine-v1",
         "source_snapshot": "2026-01-01T00:00:00+00:00", "status": "measured", "blocker": None, "templates": [],
         "review": [], "manual_files": [], "synthetic_fixture": True}
    m.update(kw)
    (root / TDIR).mkdir(parents=True, exist_ok=True)
    (root / TDIR / "manifest.json").write_text(json.dumps(m, ensure_ascii=False), encoding="utf-8")


def test_identity_templates_row(proj):
    r = rows(proj)[preset_cli.IDENTITY_ITEM]
    assert r["status"] == "unmeasured" and "미실행" in r["evidence"] and r["state"] == "blocked_network"
    ok_snapshot(proj)
    _manifest(proj, status="partial", blocker="사람 확인이 필요한 후보 1개 (SYNTHETIC)",
              templates=[{"id": "idt01_recurrence"}], review=[{"id": "rev02_recurrence"}])
    r = rows(proj)[preset_cli.IDENTITY_ITEM]
    assert (r["status"], r["state"]) == ("partial", "needs_manual_observation")
    assert "templates=1" in r["evidence"] and "review=1" in r["evidence"] and "SYNTHETIC" in r["evidence"]
    _manifest(proj, templates=[{"id": "idt01_recurrence"}])
    r = rows(proj)[preset_cli.IDENTITY_ITEM]
    assert (r["status"], r["state"], r["impact"]) == ("measured", "resolved", "없음")
    # a manifest of another snapshot is not this preset's measurement any more
    ok_snapshot(proj, at="2026-02-01T00:00:00+00:00")
    r = rows(proj)[preset_cli.IDENTITY_ITEM]
    assert (r["status"], r["state"]) == ("unmeasured", "remeasure") and "다시 추출" in r["evidence"]


def test_real_command_writes_the_row_source(proj):
    """`ref identity-templates` on the (blocked) tree writes the unmeasured manifest the row then reads."""
    from shortkit.reference.identity_templates import extract

    extract("joshuamagazine", detector=lambda p: pytest.fail("no reference video may exist here"))
    r = rows(proj)[preset_cli.IDENTITY_ITEM]
    assert r["status"] == "unmeasured" and "status=unmeasured" in r["evidence"] and r["state"] == "blocked_network"


def test_registry_entry_of_the_templates_dir_shows_the_manifest(proj):
    """identity_exclusions.logo_templates_dir stays infra (a path), but its registry entry carries the manifest's state
    and the evidence (reference video, time) of the templates."""
    from shortkit import config

    ok_snapshot(proj)
    _manifest(proj, templates=[{"id": "idt01_recurrence", "file": f"{TDIR}/idt01_recurrence.png",
                                "evidence": [{"video_id": "vidR000001", "t": 1.5}]}])
    e = config.sync_registry("joshuamagazine", access_logs=[], qa_declarations={}, discover=False)["entries"][
        "identity_exclusions.logo_templates_dir"]
    assert e["category"] == "infra" and e["status"] == "not_applicable"
    assert e["artifact"]["status"] == "measured" and e["artifact"]["templates"] == 1
    assert e["evidence"] == [{"video_id": "vidR000001", "t": 1.5, "template": f"{TDIR}/idt01_recurrence.png"}]
    ok_snapshot(proj, at="2026-02-01T00:00:00+00:00")              # another snapshot -> the record is stale
    e = config.sync_registry("joshuamagazine", access_logs=[], qa_declarations={}, discover=False)["entries"][
        "identity_exclusions.logo_templates_dir"]
    assert e["artifact"]["status"] == "unmeasured" and e["artifact"]["stale"]
