"""Every preset key has a real code consumer: access logs per command, registry collection, and the
rules that enforce text.tone / own_branding / trim tail / duration range / BGM identity / approval
for later episodes (synthetic media, temp project root)."""
from __future__ import annotations

import json
import shutil

import pytest
import yaml

from .conftest import M, codes, load_preset, set_preset, write_plan


def run(root, plan, **kw):
    from shortkit.edit.validate import validate

    write_plan(root, plan)
    return validate(plan, load_preset(), **kw)


def by(callers, fn: str) -> bool:
    """Caller ids are root-relative paths in the project and bare file names in a temp root."""
    return any(c == fn or c.endswith("/" + fn) for c in callers)


def msgs(issues, code):
    return [i["message_ko"] for i in issues if i["code"] == code]


# ----------------------------------------------------------------------------- config classification
def test_classification_blur_ratio_rule_and_tone_notes_meta():
    from shortkit import config

    assert config.classify_key("render.clean.blur_sigma_ratio") == "rule"
    assert config.classify_key("text.tone.notes") == "meta"
    assert config.classify_key("text.tone.register") is None           # still a reference style
    assert "BGM 버전" in config.impact_of("audio.bgm.version")
    assert "p10..p90" in config.impact_of("structure.duration_s.p10")


# ----------------------------------------------------------------------------- access logs
def test_every_command_saves_its_access_log_and_sync_collects_them(root, plan):
    from shortkit import config
    from shortkit.cli import main

    write_plan(root, plan)
    assert main(["episode", "validate", "t1"]) == 0
    assert main(["episode", "proposal", "t1"]) == 0
    assert main(["episode", "resolve", "t1"]) == 0
    b = root / "episodes/t1/build"
    for cmd in ("validate", "proposal", "resolve"):
        acc = json.loads((b / f"preset_access_{cmd}.json").read_text())
        assert acc["preset_id"] == "joshuamagazine-v1" and acc["reads"], cmd
    prop = json.loads((b / "preset_access_proposal.json").read_text())["reads"]
    assert len(prop["text.tone.sentence_end_examples"]) == 1
    assert by(prop["text.tone.sentence_end_examples"], "proposal.py:tone_style_guide")
    val = json.loads((b / "preset_access_validate.json").read_text())["reads"]
    assert by(val["text.tone.register"], "validate.py:check_tone")
    assert by(val["identity_exclusions.own_branding"], "validate.py:check_own_branding")
    assert by(val["motion.trim.tail_after_meaning_s"], "validate.py:check_trim_tail")
    # resolve: contract file + the command's own log hold the same (whole-command) reads
    assert (b / "preset_access.json").is_file()
    # a QA access log (written by `shortkit qa run`) is collected too
    qa = root / "episodes/t1/qa"
    qa.mkdir(parents=True, exist_ok=True)
    (qa / "preset_access.json").write_text(json.dumps(
        {"preset_id": "joshuamagazine-v1", "reads": {"text.tone.notes": ["shortkit/qa/checks.py:fake_reader"]}}))
    logs = config.all_access_logs()
    assert {"episodes/t1/build/preset_access_validate.json", "episodes/t1/build/preset_access_proposal.json",
            "episodes/t1/build/preset_access_resolve.json", "episodes/t1/build/preset_access.json",
            "episodes/t1/qa/preset_access.json"} <= set(logs)
    reg = config.sync_registry("joshuamagazine", access_logs=[], qa_declarations={})     # discovery is automatic
    ent = reg["entries"]
    assert by(ent["text.tone.sentence_end_examples"]["code"], "proposal.py:tone_style_guide")
    assert "shortkit/qa/checks.py:fake_reader" in ent["text.tone.notes"]["code"]
    assert "episodes/t1/qa/preset_access.json" in reg["access_logs"]
    # a log of another preset is ignored
    (qa / "preset_access.json").write_text(json.dumps(
        {"preset_id": "other-v1", "reads": {"text.tone.emoji": ["x.py:other"]}}))
    reg = config.sync_registry("joshuamagazine", qa_declarations={}, discover=True)
    assert "x.py:other" not in reg["entries"]["text.tone.emoji"]["code"]


# ----------------------------------------------------------------------------- text.tone
@pytest.mark.parametrize("text,bad", [("학생이 자리에 앉습니다", True), ("학생이 자리에 앉아요", True),
                                      ("학생이 자리에 앉는다", False), ("오늘의 사건", False),
                                      ("진짜? 대박이다", False), ("앉았다. 그리고 웃어요", True)])
def test_tone_register_banmal(root, plan, text, bad):
    plan["captions"][1]["text"] = text
    iss = run(root, plan)
    assert ("tone_register" in codes(iss, "warn")) is bad, iss
    assert "tone_register" not in codes(iss, "error")          # test mode: warning


def test_tone_register_production_error_and_dialogue_exempt(root, plan):
    plan["captions"][1]["text"] = "화면이 움직입니다"
    plan["mode"] = "production"
    assert "tone_register" in codes(run(root, plan, allow_unmeasured=True), "error")
    plan["mode"] = "test"
    plan["captions"][1]["role"] = "dialogue"                   # a real line keeps its own register
    plan["captions"][1]["grounding"] = {"kind": "heard", "source": "a", "src_t": 1.0}
    assert "tone_register" not in codes(run(root, plan))


def test_tone_register_haeyo_flags_plain_declaratives(root, plan):
    set_preset(root, "text.tone.register", "해요체")
    plan["captions"][1]["text"] = "화면이 움직인다"
    assert "tone_register" in codes(run(root, plan))
    plan["captions"][1]["text"] = "화면이 움직여요"
    assert "tone_register" not in codes(run(root, plan))
    set_preset(root, "text.tone.register", "혼합")                  # mixed: nothing to enforce
    plan["captions"][1]["text"] = "화면이 움직입니다"
    assert "tone_register" not in codes(run(root, plan))
    set_preset(root, "text.tone.register", "존댓말")
    assert "tone_register_value" in codes(run(root, plan), "error")


def test_tone_on_screen_text_exempt(root, plan):
    plan["captions"][1]["text"] = "출입을 금합니다"
    plan["captions"][1]["grounding"] = {"kind": "on_screen_text", "source": "a", "src_t": 1.0}
    assert "tone_register" not in codes(run(root, plan))


def test_tone_emoji(root, plan):
    plan["captions"][1]["text"] = "화면이 움직인다 ♪"             # a plain text symbol is not an emoji
    assert "tone_emoji" not in codes(run(root, plan))
    plan["captions"][1]["text"] = "화면이 움직인다 🔥"
    assert "tone_emoji" in codes(run(root, plan), "warn")
    set_preset(root, "text.tone.emoji", True)
    assert "tone_emoji" not in codes(run(root, plan))
    set_preset(root, "text.tone.emoji", None)
    assert "tone_emoji_unmeasured" in codes(run(root, plan), "warn")


# ----------------------------------------------------------------------------- own branding
@pytest.mark.parametrize("text", ["@my_channel 구독", "자세한 건 www.example.com", "shorts.example.kr/abc 참고"])
def test_own_branding_none_forbids_handles_and_urls(root, plan, text):
    plan["captions"][1]["text"] = text
    assert "own_branding_text" in codes(run(root, plan), "error")


def test_own_branding_exemptions(root, plan):
    plan["captions"][1]["text"] = "@store_sign 간판"
    plan["captions"][1]["grounding"] = {"kind": "on_screen_text", "source": "a", "src_t": 1.0}
    assert "own_branding_text" not in codes(run(root, plan))
    plan["captions"][1]["grounding"] = {"kind": "seen", "source": "a", "src_t": 1.0}
    plan["captions"][1]["role"] = "speaker"                     # person identification label
    assert "own_branding_text" not in codes(run(root, plan))
    plan["captions"][1]["role"] = "situation"
    plan["captions"][1]["text"] = "메일은 a@b 로"                  # not a handle, not a URL
    assert "own_branding_text" not in codes(run(root, plan))
    plan["captions"][1]["text"] = "@ours 에서 봐"
    set_preset(root, "identity_exclusions.own_branding", "@ours")  # a requested own branding
    assert "own_branding_text" not in codes(run(root, plan))
    set_preset(root, "identity_exclusions.own_branding", {"bad": 1})
    assert "own_branding_value" in codes(run(root, plan), "error")


# ----------------------------------------------------------------------------- meaningless tail
def test_trim_tail(root, plan):
    iss = run(root, plan)
    # s3 (b, 2.5 s) carries no grounded caption / SFX event / decoration: no meaning mark
    assert any("s3" in w for w in msgs(iss, "trim_no_meaning"))
    assert not msgs(iss, "trim_tail")
    plan["timeline"][2]["purpose"] = "outro"                    # ending segment: exempt
    assert "trim_no_meaning" not in codes(run(root, plan))
    # s1 = out 0.0-2.0; its caption ends at 1.2 -> 0.8 s tail > 0.25 s
    plan["captions"][1]["end"] = 1.2
    plan["sfx"][0]["t"], plan["sfx"][0]["event"]["t"] = 0.9, 1.0
    t = msgs(run(root, plan), "trim_tail")
    assert t and "s1" in t[0] and "0.80s" in t[0]
    set_preset(root, "motion.trim.tail_after_meaning_s", 1.0)
    assert "trim_tail" not in codes(run(root, plan))
    set_preset(root, "motion.trim.tail_after_meaning_s", 0.25)
    plan["timeline"][0]["purpose"] = "reaction"
    assert "trim_tail" not in codes(run(root, plan))


def test_trim_tail_counts_decorations_and_kept_audio(root, plan):
    plan["timeline"][2]["purpose"] = "outro"
    plan["captions"][1]["end"] = 1.2
    plan["sfx"][0]["t"], plan["sfx"][0]["event"]["t"] = 0.9, 1.0
    plan["decorations"] = [{"id": "d1", "kind": "box", "start": 0.5, "end": 1.9,
                            "keyframes": [{"t": 0.0, "x": 540, "y": 1100, "w": 100, "h": 80}]}]
    assert "trim_tail" not in codes(run(root, plan))            # 2.0 - 1.9 = 0.1 s


# ----------------------------------------------------------------------------- duration range
def test_duration_range_through_preset(root, plan):
    iss = run(root, plan)
    assert "duration_unmeasured" in codes(iss, "warn")
    set_preset(root, "structure.duration_s", {"p10": 10.0, "p50": 20.0, "p90": 30.0, "n": 12})
    iss = run(root, plan)
    m = msgs(iss, "duration_range")
    assert m and "10.0..30.0" in m[0] and "중앙값 20.0" in m[0]
    assert "duration_range" in codes(iss, "warn")
    plan["mode"] = "production"
    assert "duration_range" in codes(run(root, plan, allow_unmeasured=True), "error")
    set_preset(root, "structure.duration_s", {"p10": 3.0, "p50": 5.0, "p90": 8.0, "n": 12})
    assert "duration_range" not in codes(run(root, plan, allow_unmeasured=True))
    pr = load_preset()
    from shortkit.edit.validate import validate

    validate(plan, pr, allow_unmeasured=True)
    for k in ("p10", "p50", "p90", "n"):
        assert by(pr.log.reads[f"structure.duration_s.{k}"], "validate.py:check_structure")


# ----------------------------------------------------------------------------- approval for later episodes
def test_later_episode_approval_rule(root, plan):
    from shortkit.edit.plan import approval_state_for

    plan["mode"] = "production"
    plan["episode_index"] = 2
    iss = run(root, plan, for_render=True, allow_unmeasured=True)
    assert "approval_required" not in codes(iss)                # later_episodes_require_approval: false
    # ... but a later episode is never a way around the first-episode gate: no approved + rendered episode 1 (S3-01)
    assert "series_first_episode" in codes(iss, "error")
    pr = load_preset()
    st = approval_state_for(plan, pr)
    assert st["rule_key"] == "approval.later_episodes_require_approval" and not st["required"]
    assert by(pr.log.reads["approval.later_episodes_require_approval"], "plan.py:approval_state_for")
    assert "approval.first_episode_requires_approval" not in pr.log.reads
    set_preset(root, "approval.later_episodes_require_approval", True)
    iss = run(root, plan, for_render=True, allow_unmeasured=True)
    assert any("2번째 에피소드" in m for m in msgs(iss, "approval_required"))
    set_preset(root, "approval.later_episodes_require_approval", "no")
    assert "approval_rule" in codes(run(root, plan), "error")


def test_missing_episode_index_is_treated_as_first(root, plan):
    plan["mode"] = "production"
    plan.pop("episode_index")
    iss = run(root, plan, for_render=True, allow_unmeasured=True)
    assert "approval_required" in codes(iss, "error") and "episode_index_missing" in codes(iss, "warn")


def test_production_gate_reads_later_rule(root, plan):
    from shortkit.edit.render import RenderError, production_gate
    from shortkit.edit.resolve import resolve_context

    plan["mode"] = "production"
    plan["episode_index"] = 3
    write_plan(root, plan)
    set_preset(root, "approval.later_episodes_require_approval", True)
    pr = load_preset()
    r = resolve_context(plan, pr).resolved
    import shortkit.config as config

    orig = config.audit
    config.audit = lambda *a, **k: {"unmeasured": [], "no_code": [], "no_qa": []}   # isolate the approval gate
    try:
        for s in r.audio.sfx:
            s.path = s.path or "x.wav"
        with pytest.raises(RenderError, match="3번째 에피소드"):
            production_gate(r, True, pr)
    finally:
        config.audit = orig
    assert by(pr.log.reads["approval.later_episodes_require_approval"], "plan.py:approval_state_for")


# ----------------------------------------------------------------------------- BGM identity
def _library(root, title="Song A", version="original"):
    d = root / "assets/library/music"
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy(root / M / "bgm.wav", d / "song_a.wav")
    (d / "index.yaml").write_text(yaml.safe_dump(
        {"tracks": [{"track_id": "song_a", "path": "song_a.wav", "title": title, "version": version}]},
        allow_unicode=True), encoding="utf-8")
    return "assets/library/music/song_a.wav"


def test_bgm_track_id_title_version_must_match(root, plan):
    _library(root)
    plan["bgm"] = {"enabled": True, "path": None, "silences": []}
    set_preset(root, "audio.bgm.track_id", "song_a")
    set_preset(root, "audio.bgm.title", "Song A")
    set_preset(root, "audio.bgm.version", "original")
    iss = run(root, plan)
    assert not {"bgm_track_mismatch", "bgm_identity_unmeasured", "bgm_track_missing"} & codes(iss), iss
    set_preset(root, "audio.bgm.version", "sped_up")             # a different version is a different track
    iss = run(root, plan)
    assert "bgm_track_mismatch" in codes(iss, "error") and any("버전" in m for m in msgs(iss, "bgm_track_mismatch"))
    set_preset(root, "audio.bgm.version", "original")
    set_preset(root, "audio.bgm.title", "Song B")
    assert "bgm_track_mismatch" in codes(run(root, plan), "error")


def test_bgm_track_entry_without_identity(root, plan):
    _library(root, title=None, version=None)
    plan["bgm"] = {"enabled": True, "path": None, "silences": []}
    set_preset(root, "audio.bgm.track_id", "song_a")
    set_preset(root, "audio.bgm.title", "Song A")
    set_preset(root, "audio.bgm.version", "original")
    assert "bgm_entry_unidentified" in codes(run(root, plan), "error")


def test_bgm_plan_path_identity(root, plan):
    lib = _library(root)
    set_preset(root, "audio.bgm.title", "Song A")
    set_preset(root, "audio.bgm.version", "original")
    iss = run(root, plan)                                        # plan file is not a library track
    assert "bgm_identity_unknown" in codes(iss, "warn")
    plan["mode"] = "production"
    assert "bgm_identity_unknown" in codes(run(root, plan, allow_unmeasured=True), "error")
    plan["mode"] = "test"
    plan["bgm"]["path"] = lib
    assert not {"bgm_identity_unknown", "bgm_track_mismatch"} & codes(run(root, plan))
    set_preset(root, "audio.bgm.version", "slowed")
    assert "bgm_track_mismatch" in codes(run(root, plan), "warn")   # plan override: warning in test


def test_bgm_identity_unmeasured_and_reads(root, plan):
    pr = load_preset()
    from shortkit.edit.validate import validate

    write_plan(root, plan)
    iss = validate(plan, pr)
    assert "bgm_identity_unmeasured" in codes(iss, "warn")
    assert by(pr.log.reads["audio.bgm.title"], "audio.py:check_bgm_identity")
    assert by(pr.log.reads["audio.bgm.version"], "audio.py:check_bgm_identity")
    plan["mode"] = "production"
    assert "bgm_identity_unmeasured" in codes(run(root, plan), "error")
    assert "bgm_identity_unmeasured" in codes(run(root, plan, allow_unmeasured=True), "warn")


def test_bgm_section_from_preset_unless_overridden(root, plan):
    iss = run(root, plan)                                        # base plan overrides section_start_s 1.0
    assert "bgm_section_start_s_override" in codes(iss, "warn")
    plan["bgm"].pop("section_start_s")
    pr = load_preset()
    from shortkit.edit.resolve import resolve_context

    write_plan(root, plan)
    ctx = resolve_context(plan, pr)
    assert ctx.resolved.audio.bgm.section_start_s == float(pr.peek("audio.bgm.section_start_s"))
    assert by(pr.log.reads["audio.bgm.section_start_s"], "audio.py:build_audio_plan")
    assert "bgm_section_start_s_override" not in codes(ctx.issues)


# ----------------------------------------------------------------------------- decoration rings
def test_ring_decoration_encloses_protected_without_covering():
    from shortkit.edit.validate import deco_covers

    kf = {"x": 500, "y": 900, "w": 300, "h": 340}
    face = (450, 840, 100, 120)
    assert not deco_covers("circle", kf, {"stroke_px": 10}, (350, 730, 300, 340), face)
    assert deco_covers("circle", dict(kf, w=140, h=140), {"stroke_px": 10}, (430, 830, 140, 140), face)
    assert not deco_covers("box", kf, {"stroke_px": 8}, (350, 730, 300, 340), face)
    assert deco_covers("box", dict(kf, rotation=10), {"stroke_px": 8}, (350, 730, 300, 340), face)
    assert deco_covers("arrow", kf, {}, (350, 730, 300, 340), face)


def test_proposal_shows_tone_style_guide(root, plan):
    from shortkit.edit.proposal import build_proposal
    from shortkit.edit.validate import validate

    set_preset(root, "text.tone.sentence_end_examples", ["는다", "했다"])
    write_plan(root, plan)
    pr = load_preset()
    issues, ctx = validate(plan, pr, return_context=True)
    md = build_proposal(plan, ctx, issues)
    assert "### 말투 안내" in md and "-는다, -했다" in md and "반말_구어체" in md
    rd = pr.log.reads["text.tone.sentence_end_examples"]
    assert len(rd) == 1 and by(rd, "proposal.py:tone_style_guide")


# ----------------------------------------------------------------------------- registry link hygiene
def test_registry_drops_dead_and_superseded_code_links(root, plan):
    from shortkit import config
    from shortkit.util.jsonio import read_yaml, write_yaml

    (root / "shortkit/edit").mkdir(parents=True)
    (root / "shortkit/edit/resolve.py").write_text("def resolve_decorations():\n    pass\n", encoding="utf-8")
    assert config.code_link_alive("shortkit/edit/resolve.py:resolve_decorations")
    assert config.code_link_alive("shortkit/edit/resolve.py:<dictcomp>")
    assert not config.code_link_alive("shortkit/edit/resolve.py:gone_function")
    assert not config.code_link_alive("shortkit/edit/missing.py:f") and not config.code_link_alive("resolve.py:f")
    reg_file = config.registry_path("joshuamagazine")
    reg = read_yaml(reg_file)
    reg["entries"]["decorations.box.color"]["code"] = ["shortkit/edit/resolve.py:<dictcomp>",
                                                        "shortkit/edit/resolve.py:gone_function"]
    reg["entries"]["decorations.circle.color"]["code"] = ["shortkit/edit/resolve.py:<dictcomp>"]
    write_yaml(reg_file, reg)
    log = root / "episodes/t1/build/preset_access_render.json"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text(json.dumps({"preset_id": "joshuamagazine-v1",
                               "reads": {"decorations.box.color": ["shortkit/edit/resolve.py:resolve_decorations"]}}))
    ent = config.sync_registry("joshuamagazine", qa_declarations={})["entries"]
    assert ent["decorations.box.color"]["code"] == ["shortkit/edit/resolve.py:resolve_decorations"]
    # code links come only from the tracked access-log archive (config.sync_registry, wave-2 registry fix): a link
    # that exists only in the previous registry file is not carried over
    assert ent["decorations.circle.color"]["code"] == []


def test_circle_and_box_styles_are_read_when_used(root, plan):
    from shortkit.edit.resolve import resolve_context

    write_plan(root, plan)
    pr = load_preset()
    resolve_context(plan, pr)
    assert "decorations.circle.color" not in pr.log.reads                  # read only when a plan uses them
    plan["decorations"] = [
        {"id": "d1", "kind": "circle", "start": 0.5, "end": 1.5, "keyframes": [{"t": 0.0, "x": 540, "y": 900, "w": 200, "h": 200}]},
        {"id": "d2", "kind": "box", "start": 2.0, "end": 3.0, "keyframes": [{"t": 0.0, "x": 540, "y": 900, "w": 200, "h": 120}]}]
    pr = load_preset()
    r = resolve_context(plan, pr).resolved
    for kind in ("circle", "box"):
        for k in ("color", "stroke_px", "blink_hz"):
            assert by(pr.log.reads[f"decorations.{kind}.{k}"], "resolve.py:resolve_decorations"), (kind, k)
    assert r.decorations[0].style["stroke_px"] == pr.peek("decorations.circle.stroke_px")
    assert r.decorations[1].blink_hz == float(pr.peek("decorations.box.blink_hz"))
