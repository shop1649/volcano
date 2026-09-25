"""One vocabulary / one sign between the reference analyzer, the renderer (resolve) and QA.

* slide: the analyzer names a measured slide by its direction (reference.textboxes.slide_kind); 'slide_up' is the
  renderer's upward entrance, any other measured slide is refused by resolve with a clear error (never mapped).
* lead_s = speech onset - caption start (positive = the caption appears before the line is heard).  The same
  synthetic case is used in tests/reference_visual/test_rv_slide_lead.py (analyzer) and
  tests/qa/test_qa_outputs.py::test_dialogue_lead_same_case_as_reference_and_resolve (QA): the line is heard at
  3.0 s, the caption shows at 2.8 s -> lead_s = +0.2.
"""
from __future__ import annotations

import pytest

from .conftest import load_preset, set_preset, write_plan

LEAD_CASE = {"speech": [(3.0, 4.0)], "caption_start": 2.8, "caption_end": 4.4, "lead_s": 0.2}


def ctx_for(root, plan):
    from shortkit.edit.resolve import resolve_context

    write_plan(root, plan)
    return resolve_context(plan, load_preset())


def test_resolve_draws_the_dialogue_lead_s_before_the_line(root, plan):
    from shortkit.reference.textboxes import dialogue_lead

    set_preset(root, "text.roles.dialogue.timing.lead_s", LEAD_CASE["lead_s"])
    heard = LEAD_CASE["speech"][0][0]
    plan["captions"].append({"id": "c_d", "role": "dialogue", "text": "진짜 왔어?", "start": heard,
                             "end": LEAD_CASE["caption_end"], "grounding": {"kind": "heard"}})
    c = ctx_for(root, plan)
    cap = next(x for x in c.resolved.captions if x.id == "c_d")
    # plan start = the moment the line is heard; the caption is drawn lead_s earlier
    assert cap.start == pytest.approx(LEAD_CASE["caption_start"])
    # ... which is exactly what the analyzer's / QA's definition reads back
    lead, onset = dialogue_lead(cap.start, cap.end, LEAD_CASE["speech"])
    assert onset == pytest.approx(heard) and lead == pytest.approx(LEAD_CASE["lead_s"])
    # a negative lead_s = the caption appears after the line starts
    set_preset(root, "text.roles.dialogue.timing.lead_s", -0.1)
    cap = next(x for x in ctx_for(root, plan).resolved.captions if x.id == "c_d")
    assert cap.start == pytest.approx(heard + 0.1)
    assert dialogue_lead(cap.start, cap.end, LEAD_CASE["speech"])[0] == pytest.approx(-0.1)


@pytest.mark.parametrize("mtype", ["slide_down", "slide_left", "slide_right", "slide_diagonal", "slide"])
def test_resolve_refuses_a_measured_slide_the_renderer_cannot_draw(root, plan, mtype):
    set_preset(root, "text.roles.situation.motion_in", {"type": mtype, "dur_s": 0.2, "scale_from": 1.0,
                                                        "offset_px": 40})
    c = ctx_for(root, plan)
    errs = [i for i in c.errors if i["code"] == "motion_unsupported_slide"]
    assert errs, c.errors
    assert errs[0]["where"] == "text.roles.situation.motion_in.type" and mtype in errs[0]["message_ko"]
    assert "slide_up" in errs[0]["message_ko"]
    # never silently mapped: whatever was resolved still carries the measured type
    for cap in (c.resolved.captions if c.resolved else []):
        if cap.role == "situation":
            assert cap.motion_in["type"] == mtype


def test_resolve_episode_raises_on_an_unsupported_slide(root, plan):
    from shortkit.edit.resolve import ResolveError, resolve_episode

    set_preset(root, "text.roles.situation.motion_in", {"type": "slide_down", "dur_s": 0.2, "scale_from": 1.0,
                                                        "offset_px": 40})
    write_plan(root, plan)
    with pytest.raises(ResolveError) as e:
        resolve_episode("t1")
    assert "motion_unsupported_slide" in {i["code"] for i in e.value.issues}
    assert "slide_down" in str(e.value)


def test_slide_up_and_exit_slides(root, plan):
    set_preset(root, "text.roles.situation.motion_in", {"type": "slide_up", "dur_s": 0.2, "scale_from": 1.0,
                                                        "offset_px": 40})
    c = ctx_for(root, plan)
    assert not [i for i in c.errors if i["code"].startswith("motion_")], c.errors
    # the renderer draws no exit slide at all: a measured exit slide (even upward) is refused too
    set_preset(root, "text.roles.situation.motion_out", {"type": "slide_up", "dur_s": 0.2})
    c = ctx_for(root, plan)
    errs = [i for i in c.errors if i["code"] == "motion_unsupported_slide"]
    assert errs and errs[0]["where"] == "text.roles.situation.motion_out.type"


def test_analyzer_vocabulary_is_the_renderers():
    from shortkit.edit.resolve import MOTION_IN_TYPES, MOTION_OUT_TYPES
    from shortkit.reference.textboxes import renderer_motion_vocab, slide_kind

    assert renderer_motion_vocab() == (tuple(MOTION_IN_TYPES), tuple(MOTION_OUT_TYPES))
    up = slide_kind(0.0, 40.0, "in")            # first frame 40 px BELOW rest, moving up
    assert up["type"] == "slide_up" and up["type"] in MOTION_IN_TYPES and up["renderer_supported"] is True
    down = slide_kind(0.0, -40.0, "in")
    assert down["type"] == "slide_down" and down["renderer_supported"] is False and down["direction_deg"] == -90.0
