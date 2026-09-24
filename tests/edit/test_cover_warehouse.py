"""Cover text = text visible on the cover frame; embedded-music record for kept originals; warehouse
link (record exists, selected|used, same sha256, not reference footage), usage recorded after a
production render, and the proposal flag for a source selected with the reference-overlap check
unmeasured.  (Synthetic warehouse records written into the temp project root.)"""
from __future__ import annotations

import json

import pytest

from .conftest import codes, load_preset, write_plan


def run(root, plan, **kw):
    from shortkit.edit.validate import validate

    write_plan(root, plan)
    return validate(plan, load_preset(), **kw)


# ----------------------------------------------------------------------------- cover
def test_cover_text_must_be_visible_on_cover_frame(root, plan):
    assert not {"cover_text_not_visible", "cover_frame_t"} & codes(run(root, plan))     # title shown at 0.0
    plan["cover"]["text"] = "표지에 없는 문구"
    iss = run(root, plan)
    assert "cover_text_not_visible" in codes(iss, "warn")                                 # test mode: warning
    msg = next(i["message_ko"] for i in iss if i["code"] == "cover_text_not_visible")
    assert "테스트 제목" in msg                                                           # tells what IS visible
    plan["mode"] = "production"
    assert "cover_text_not_visible" in codes(run(root, plan), "error")


def test_cover_frame_t_selects_the_visible_caption(root, plan):
    # situation caption c_s is shown 0.2..2.0 with a pop motion_in; at rest from 0.2 + dur
    plan["cover"] = {"text": "화면이 움직인다", "frame_t": 0.0}
    assert "cover_text_not_visible" in codes(run(root, plan), "warn")                    # not shown yet at 0.0
    din = float(load_preset().get("text.roles.situation.motion_in.dur_s"))
    plan["cover"]["frame_t"] = round(0.2 + din + 0.1, 3)
    iss = run(root, plan)
    assert "cover_text_not_visible" not in codes(iss)
    assert "cover_text_role" in codes(iss, "warn")                     # preset cover.text_role = title
    assert "cover_frame_not_first" in codes(iss, "warn")               # preset cover.source = first_frame
    plan["cover"]["frame_t"] = 99.0
    assert "cover_frame_t" in codes(run(root, plan), "warn")


def test_cover_text_ignores_line_breaks_only(root, plan):
    plan["captions"][0]["text"] = "아주 긴 테스트 제목 문장 하나"
    plan["cover"]["text"] = "아주 긴 테스트 제목 문장 하나"
    assert "cover_text_not_visible" not in codes(run(root, plan))
    plan["cover"]["text"] = "아주 긴 테스트 제목"
    assert "cover_text_not_visible" in codes(run(root, plan))


# ----------------------------------------------------------------------------- embedded music
@pytest.mark.parametrize("stem", ["raw", "vocals"])
def test_kept_original_needs_embedded_music_record(root, plan, stem):
    from .conftest import M

    plan["sources"][0]["has_embedded_music"] = None
    plan["sources"][0]["vocals_path"] = f"{M}/vocals.wav"
    plan["timeline"][0]["original_audio"] = {"keep": True, "reason": "대사", "stem": stem, "ranges": [[1.0, 2.0]]}
    assert "embedded_music_unknown" in codes(run(root, plan), "warn")
    plan["mode"] = "production"
    assert "embedded_music_unknown" in codes(run(root, plan), "error")
    plan["sources"][0]["has_embedded_music"] = False
    assert "embedded_music_unknown" not in codes(run(root, plan))
    # a source whose original audio is NOT kept does not need the record
    plan["sources"][0]["has_embedded_music"] = None
    plan["timeline"][0]["original_audio"] = {"keep": False}
    assert "embedded_music_unknown" not in codes(run(root, plan))


def test_test_episode_plan_records_embedded_music():
    """episodes/test-pipeline-001: the kept-audio source has has_embedded_music recorded (no music by
    construction: assets/test/generated/classroom_voice.truth.json)."""
    from shortkit import paths
    from shortkit.edit.plan import load_plan
    from shortkit.util.jsonio import read_json

    plan = load_plan("test-pipeline-001")
    kept = {s["source"] for s in plan["timeline"] if (s.get("original_audio") or {}).get("keep")}
    assert kept
    for s in plan["sources"]:
        if s["id"] in kept:
            assert s["has_embedded_music"] is False
            truth = read_json(paths.absp(s["path"].replace(".mp4", ".truth.json")))
            assert truth["sha256"] == s["sha256"] and "speech" in truth and "music" not in json.dumps(truth)
    title = next(c for c in plan["captions"] if c["role"] == "title")
    assert plan["cover"]["text"] == title["text"] and title["start"] <= (plan["cover"]["frame_t"] or 0.0)


# ----------------------------------------------------------------------------- warehouse
def _rec(root, plan, **over):
    rec = {"id": "wh1", "platform": "local", "url": "https://example.invalid/v/wh1", "original_url": None,
           "status": "selected", "sha256": plan["sources"][0]["sha256"],
           "reference_overlap": {"excluded": False, "method": "phash"}, "first_seen_at": "2026-09-24T00:00:00+00:00"}
    rec.update(over)
    (root / "warehouse/candidates.jsonl").write_text(json.dumps(rec, ensure_ascii=False) + "\n")
    plan["sources"][0]["warehouse_id"] = "wh1"
    return rec


WH_CODES = {"provenance_record_missing", "source_not_selected", "provenance_sha_missing", "provenance_sha_mismatch",
            "source_excluded_reference", "source_excluded_status"}


def test_warehouse_link_ok(root, plan):
    _rec(root, plan)
    assert not WH_CODES & codes(run(root, plan))
    _rec(root, plan, status="used")
    assert not WH_CODES & codes(run(root, plan))


def test_warehouse_link_problems(root, plan):
    plan["mode"] = "production"
    _rec(root, plan, status="candidate")
    assert "source_not_selected" in codes(run(root, plan), "error")
    _rec(root, plan, sha256="f" * 64)
    assert "provenance_sha_mismatch" in codes(run(root, plan), "error")
    _rec(root, plan, sha256=None)
    assert "provenance_sha_missing" in codes(run(root, plan), "error")
    _rec(root, plan, reference_overlap={"excluded": True, "matched_video_id": "ref1", "method": "phash"})
    assert "source_excluded_reference" in codes(run(root, plan), "error")
    plan["sources"][0]["warehouse_id"] = "nope"
    assert "provenance_record_missing" in codes(run(root, plan), "error")
    plan["mode"] = "test"                                               # test mode: missing record / status warn
    assert "provenance_record_missing" in codes(run(root, plan), "warn")
    _rec(root, plan, status="candidate")
    assert "source_not_selected" in codes(run(root, plan), "warn")


def test_mark_used_after_production_render(root, plan):
    from shortkit.edit.cli import mark_sources_used
    from shortkit.sourcing import warehouse as wh

    _rec(root, plan)
    rows = mark_sources_used(plan)
    assert rows == [{"warehouse_id": "wh1", "ok": True, "error": None}]
    rec = wh.get("wh1")
    assert rec["status"] == "used" and rec["used_in"] == ["t1"]
    assert mark_sources_used(plan)[0]["ok"] and wh.get("wh1")["used_in"] == ["t1"]     # idempotent
    _rec(root, plan, status="candidate")
    bad = mark_sources_used(plan)[0]
    assert bad["ok"] is False and "SelectionError" in bad["error"]                       # never hidden


def test_cli_render_marks_used_only_in_production(root, plan, monkeypatch):
    """_render calls mark_used after a successful render in production only (render itself stubbed)."""
    from shortkit.edit import cli as ecli
    from shortkit.edit import render as rmod
    from shortkit.sourcing import warehouse as wh

    _rec(root, plan)
    write_plan(root, plan)
    out = root / "episodes/t1/output/t1.mp4"

    def fake_render(r, allow_unmeasured=False, preset=None):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"x")
        (root / "episodes/t1/build").mkdir(parents=True, exist_ok=True)
        (root / "episodes/t1/build/render_report.json").write_text(json.dumps(
            {"probe": {"width": 1, "height": 1, "fps": 30, "duration": 1.0}, "audio": {}, "mp4_loudness": {}}))
        return out

    from shortkit.edit import resolve as res_mod

    monkeypatch.setattr(rmod, "render", fake_render)
    monkeypatch.setattr(ecli, "validate", lambda *a, **k: [])
    monkeypatch.setattr(res_mod, "resolve_episode", lambda *a, **k: None)
    from shortkit.cli import main

    assert main(["episode", "render", "t1"]) == 0
    assert wh.get("wh1")["status"] == "selected"                      # test mode: provenance untouched
    plan["mode"] = "production"
    write_plan(root, plan)
    assert main(["episode", "render", "t1"]) == 0
    assert wh.get("wh1")["status"] == "used" and wh.get("wh1")["used_in"] == ["t1"]
    log = [json.loads(x) for x in (root / "episodes/t1/approval_log.jsonl").read_text().splitlines()]
    assert any(e["event"] == "warehouse_used" and e["ok"] for e in log)


def test_proposal_flags_reference_overlap_accepted_unmeasured(root, plan):
    from shortkit.edit.proposal import build_proposal
    from shortkit.edit.validate import validate

    acc = [{"key": "reference_overlap", "text": "레퍼런스 중복 여부 못 잼", "impact": "같은 녹화 재사용 위험",
            "reason": "검사 도구 차단", "by": "tester", "at": "2026-09-24T00:00:00+00:00"}]
    _rec(root, plan, selection={"accepted_unmeasured": acc})
    write_plan(root, plan)
    issues, ctx = validate(plan, load_preset(), return_context=True)
    md = build_proposal(plan, ctx, issues)
    line = next(ln for ln in md.splitlines() if "레퍼런스와 같은 녹화인지 검사하지 못한 채" in ln)
    assert "검사 도구 차단" in line and plan["sources"][0]["id"] in line
    _rec(root, plan, selection={"accepted_unmeasured": [{"key": "recency", "reason": "x"}]})
    md = build_proposal(plan, *reversed(validate(plan, load_preset(), return_context=True)))
    assert "레퍼런스와 같은 녹화인지 검사하지 못한 채" not in md
