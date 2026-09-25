"""QA row fixes, round 2 (fix-qa2): first-caption definition shared with the reference analyzer, style keys that do
not apply to a role, the still-scene source-mapping rule, and the pooled per-role font verdict.

Everything here is SYNTHETIC (hand-written analysis files / probe dicts) or rendered from the CC-BY Intel sample
clips in assets/test/generated; anything written goes to a temporary project root.
"""
from __future__ import annotations

import shutil
from types import SimpleNamespace

import numpy as np
import pytest

from shortkit import config, paths
from shortkit.qa import checks

REAL_ROOT = paths.project_root()


@pytest.fixture()
def temp_root(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    shutil.copy(REAL_ROOT / "shortkit.root", root / "shortkit.root")
    shutil.copytree(REAL_ROOT / "presets" / "joshuamagazine", root / "presets" / "joshuamagazine",
                    ignore=shutil.ignore_patterns("videos", "frames", "stems", "*.wav", "*.mp4", "analysis"))
    (root / "warehouse").mkdir()
    monkeypatch.setenv("SHORTKIT_ROOT", str(root))
    return root


def _cap(cid, role, start, end=None, **kw):
    return SimpleNamespace(id=cid, role=role, start=start, end=end if end is not None else start + 2.0, **kw)


# ============================================================================ 2. first caption = analyzer's definition
def test_first_caption_uses_the_reference_analyzer_definition(temp_root):
    """The same caption set measured by the reference analyzer (``ref aggregate`` over captions.json) and by QA
    (output onsets) gives the same first-caption time: title and description are not 'the first caption'."""
    from shortkit.reference import aggregate as A
    from shortkit.util.jsonio import read_json, write_json

    items = [("t", "title", 0.0, 20.0), ("d", "description", 0.0, 4.0), ("k", "speaker", 0.3, 3.0),
             ("s", "situation", 0.5, 4.0), ("r", "reaction", 6.0, 7.0)]
    # production aggregation uses ONLY members of the fixed latest-N snapshot: a SYNTHETIC snapshot holding the test
    # video (the real snapshot of this repo is 'blocked' and empty)
    write_json(paths.preset_dir("joshuamagazine") / "reference" / "latest100.json", {
        "schema": "shortkit.ref_snapshot/1", "status": "ok", "captured_at": "2026-01-01T00:00:00+00:00",
        "method": "SYNTHETIC (test fixture)", "latest_n": 1, "n": 1,
        "videos": [{"rank": 1, "video_id": "vid0000001", "url": "https://www.youtube.com/watch?v=vid0000001",
                    "title": "SYNTHETIC vid0000001", "duration": 20.0, "view_count": None, "published_at": None,
                    "kind": "short"}]})
    d = paths.preset_dir("joshuamagazine") / "analysis" / "vid0000001"
    write_json(d / "captions.json", {"video_id": "vid0000001", "resolution": [1080, 1920], "duration": 20.0,
                                     "items": [{"id": i, "role": r, "start": a, "end": b, "text": "가나다",
                                                "bbox": [100, 100, 300, 50], "style": {}, "frame": None}
                                               for i, r, a, b in items]})
    A.aggregate("joshuamagazine", ids=["vid0000001"])
    meas = read_json(paths.preset_dir("joshuamagazine") / "measurements" / "visual_structure.json")
    ref = next(it for it in meas["items"] if it["key"] == "structure.first_caption_at_s")
    assert ref["status"] == "measured" and ref["value"] == pytest.approx(0.3)

    caps = [_cap(i, r, a, b) for i, r, a, b in items]
    onsets = [{"id": i, "onset": a} for i, _r, a, _b in items]
    fc = checks.first_timed_caption(caps, onsets)
    assert fc["t"] == pytest.approx(ref["value"]) and fc["caption"] == "k"
    # the roles QA leaves out are exactly the analyzer's: a title-only change moves neither
    from shortkit.reference import aggregate

    assert checks.FIRST_CAPTION_EXCLUDED_ROLES is aggregate.FIRST_CAPTION_EXCLUDED_ROLES


def test_first_caption_unmeasured_when_an_earlier_caption_was_not_measured():
    caps = [_cap("t", "title", 0.0, 20.0), _cap("k", "speaker", 0.3), _cap("s", "situation", 0.45)]
    fc = checks.first_timed_caption(caps, [{"id": "t", "onset": 0.0}, {"id": "k", "onset": None},
                                           {"id": "s", "onset": 0.45}])
    assert fc["t"] is None and "k" in fc["note"]
    # a caption planned well after the measured first one cannot have been first
    caps.append(_cap("late", "reaction", 5.0))
    fc = checks.first_timed_caption(caps, [{"id": "k", "onset": 0.3}, {"id": "s", "onset": 0.45}])
    assert fc["t"] == pytest.approx(0.3) and fc["caption"] == "k"


# ============================================================================ 1. pooled per-role font verdict
def test_structured_bootstrap_treats_a_captions_rest_frames_as_one_placement():
    """Rest frames of one caption are one placement re-encoded (test-coverage-001 c_sit1: 0.9661/0.966/0.966/0.966),
    so the ceiling of the pooled median draws one ceiling placement per caption, not one per crop: with a single
    caption the pooled ceiling is that caption's own distribution, however many rest frames were taken."""
    from shortkit.qa.font_id import bootstrap_median, placement_matrix

    rows = [{"iou": v, "group": "0:x|66|d4"} for v in (0.95, 0.96, 0.97, 0.98)]
    ceil = {"by_delay": {"4": {"rows": rows, "row_spec": [0, 1, 2, 3]},
                         "12": {"rows": [dict(r) for r in rows], "row_spec": [0, 1, 2, 3]}}}
    m = placement_matrix(ceil, [4, 12, 12, 4])
    assert m.shape == (4, 4) and np.allclose(m[:, 0], m[:, 1])
    one = bootstrap_median([m])
    assert set(np.round(np.unique(one), 4)) <= {0.95, 0.96, 0.97, 0.98}      # never tighter than one placement
    assert np.percentile(one, 10) == pytest.approx(0.95)
    # four captions: the median of four independent placements is tighter than one placement
    four = bootstrap_median([m, m, m, m])
    assert np.percentile(four, 10) > np.percentile(one, 10)
    # placements missing a delay are dropped, a ceiling without placement ids cannot be pooled
    ceil["by_delay"]["12"]["rows"][2]["iou"] = None
    assert placement_matrix(ceil, [4, 12]).shape == (3, 2)
    assert placement_matrix({"by_delay": {"4": {"rows": rows}}}, [4]) is None


def _wrong_font_root(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    root.mkdir()
    shutil.copy(REAL_ROOT / "shortkit.root", root / "shortkit.root")
    shutil.copytree(REAL_ROOT / "presets" / "joshuamagazine", root / "presets" / "joshuamagazine",
                    ignore=shutil.ignore_patterns("videos", "frames", "stems", "*.wav", "*.mp4", "analysis"))
    (root / "assets" / "test").mkdir(parents=True)
    (root / "assets" / "test" / "generated").symlink_to(REAL_ROOT / "assets" / "test" / "generated")
    if (REAL_ROOT / "assets" / "fonts").is_dir():
        (root / "assets" / "fonts").symlink_to(REAL_ROOT / "assets" / "fonts")
    monkeypatch.setenv("SHORTKIT_ROOT", str(root))
    return root


@pytest.mark.slow
def test_wrong_face_drawn_for_a_role_is_different(tmp_path, monkeypatch):
    """SYNTHETIC: the situation caption is drawn in another face than the plan (IR) says, through the production
    libass path at CRF 18.  The per-role pooled font row must say 'different' (required row, gate G1)."""
    import sys

    sys.path.insert(0, str(REAL_ROOT / "tests" / "qa"))
    import qa_synth
    from shortkit.edit.captions import resolve_font

    wrong = None
    for name in ("Pretendard Black", "Noto Sans CJK KR Bold"):
        try:
            resolve_font(name)
            wrong = name
            break
        except Exception:
            continue
    if wrong is None or not (REAL_ROOT / qa_synth.GEN / "video" / "head-pose-face-detection-female-and-male.mp4").is_file():
        pytest.skip("test media / a second face not available here")
    _wrong_font_root(tmp_path, monkeypatch)
    swap = {"s1": wrong}

    def swapped(fn):
        def w(*a, **kw):
            if kw.get("rest_only") or (len(a) > 1 and a[1]):
                return fn(*a, **kw)             # truth bboxes: the planned face (as the plan says)
            saved = [c["font"] for c in qa_synth.CAPTIONS]
            for c in qa_synth.CAPTIONS:
                c["font"] = swap.get(c["id"], c["font"])
            try:
                return fn(*a, **kw)
            finally:
                for c, f in zip(qa_synth.CAPTIONS, saved):
                    c["font"] = f
        return w

    monkeypatch.setattr(qa_synth, "build_ass", swapped(qa_synth.build_ass))
    monkeypatch.setattr(qa_synth, "link_fonts", swapped(qa_synth.link_fonts))
    qa_synth.render_episode("test-qa-wrongfont", bad=False)

    from shortkit.qa import load_context
    from shortkit.qa.probes_text import probe_captions, probe_font_roles

    ctx = load_context("test-qa-wrongfont")
    ctx.resolved.captions = [c for c in ctx.resolved.captions if c.id == "s1"]
    assert ctx.resolved.captions[0].font_name == "Noto Sans CJK KR Black"        # the plan's face
    caps = probe_captions(ctx)
    assert caps[0]["found"], caps
    roles = probe_font_roles(ctx, caps)
    r = roles["situation"]
    assert r["status"] == "measured" and r["n_crops"] >= 3, r
    assert r["verdict"] == "different", (r["verdict"], r.get("reasons"), r.get("ranked"))
    from shortkit.reference.typography import font_ref

    # positively identified: the face really drawn ranks first and passes the unchanged rules with its own ceilings
    assert r["top"] == font_ref(wrong).name and r["other_font"]["verdict"] == "identical", r.get("other_font")
    rows = checks.build_rows(ctx, {"text": {"status": "measured", "captions": caps, "font_roles": roles}},
                             only=["caption.font"])
    row = next(x for x in rows if x["row_id"] == "caption.font:role_situation")
    assert row["status"] == "different" and row["required"] is True
    per_cap = next(x for x in rows if x["row_id"] == "caption.font:s1")
    assert per_cap["required"] is False and per_cap["covered_by"] == "caption.font:role_situation"
    # first line of evidence: the exact-position re-render in the face really drawn reproduces the output better
    assert r["exact"]["exact_role_verdict"] == "different", r["exact"]


# ============================================================================ 3. style keys that do not apply
class _Preset:
    """Minimal preset: values + origins (measured unless listed as provisional)."""

    def __init__(self, data: dict, provisional: set[str]):
        self.data, self.prov = data, provisional
        self.format_id, self.name, self.dir = None, "fake", REAL_ROOT / "presets" / "joshuamagazine"

    def get(self, key):
        from shortkit.config import get_path

        return get_path(self.data, key)

    def origin(self, key):
        return "provisional" if key in self.prov else "measured"

    def requested_keys(self):
        return []


def _role_style(**kw):
    st = {"color": "#FFFFFF", "highlight_color": "#FFE400", "outline_px": 6, "outline_color": "#000000",
          "shadow_px": 0, "shadow_color": "#000000", "size_px": 66, "line_spacing": 1.15, "max_lines": 1,
          "max_chars_per_line": 14, "box": {"enabled": False, "color": "#000000", "alpha": 0.5, "pad_x": 16, "pad_y": 8},
          "motion_in": {"type": "fade", "dur_s": 0.2, "scale_from": 1.0, "offset_px": 0},
          "motion_out": {"type": "none", "dur_s": 0.0}, "timing": {"lead_s": 0.0, "min_dur_s": 1.0}, "persist": "timed"}
    st.update(kw)
    return st


def _style_builder(role_style: dict, prov: set[str], role="reaction", bg=None):
    data = {"text": {"roles": {role: role_style}},
            "canvas": {"background": bg or {"type": "color", "color": "#000000", "blur_sigma": 30}}}
    ctx = SimpleNamespace(preset=_Preset(data, prov), resolved=SimpleNamespace(mode="test", format_id=None, clips=[]),
                          episode_id="e", plan={}, options={})
    b = checks.RowBuilder(ctx)
    b.measurements = lambda: {}
    return b


def test_keys_that_do_not_apply_leave_the_row_and_are_named_in_the_note():
    role = "reaction"
    prov = {f"text.roles.{role}.{k}" for k in ("box.color", "box.alpha", "box.pad_x", "box.pad_y", "shadow_color",
                                               "highlight_color", "line_spacing", "timing.lead_s",
                                               "motion_in.scale_from", "motion_in.offset_px", "motion_out.dur_s")}
    b = _style_builder(_role_style(), prov)
    caps = [SimpleNamespace(role=role, highlight=[], lines=["빤히"], text="빤히")]
    na = checks.role_not_applicable(b, role, caps)
    k = lambda n: f"text.roles.{role}.{n}"   # noqa: E731
    assert set(na) == {k("box.color"), k("box.alpha"), k("box.pad_x"), k("box.pad_y"), k("shadow_color"),
                       k("highlight_color"), k("line_spacing"), k("timing.lead_s"), k("motion_in.scale_from"),
                       k("motion_in.offset_px"), k("motion_out.dur_s")}
    keys = checks._role_keys(role, ["color", "highlight_color", "outline_px", "outline_color", "shadow_px",
                                    "shadow_color", "box.enabled", "box.color", "box.alpha", "box.pad_x", "box.pad_y"])
    ok = lambda o, r: True                    # noqa: E731
    r_old = b.style_row("caption.style", "x_ref", "x", "c", keys, {"fill_color": "#FFFFFF"}, ok)
    assert r_old["status"] == "unmeasured"                      # before: box.* / shadow_color / highlight made it 못 잼
    r = b.style_row("caption.style", "y_ref", "y", "c", keys, {"fill_color": "#FFFFFF"}, ok, na=na)
    assert r["status"] == "same", r["note"]
    assert "box.alpha — box.enabled=false" in r["note"] and k("box.alpha") not in r["keys"]
    assert r["not_applicable"][k("shadow_color")].startswith("shadow_px=0")
    # a PROVISIONAL governing key still makes the row 못 잼 (the decision itself is not measured)
    b2 = _style_builder(_role_style(), prov | {k("box.enabled")})
    r2 = b2.style_row("caption.style", "z_ref", "z", "c", keys, {"fill_color": "#FFFFFF"}, ok,
                      na=checks.role_not_applicable(b2, role, caps))
    assert r2["status"] == "unmeasured" and k("box.enabled") in r2["note"]


def test_applicability_follows_the_role_style_and_the_plan():
    role = "situation"
    b = _style_builder(_role_style(box={"enabled": True, "color": "#000000", "alpha": 0.5, "pad_x": 16, "pad_y": 8},
                                   shadow_px=3, max_lines=2,
                                   motion_in={"type": "pop", "dur_s": 0.12, "scale_from": 0.85, "offset_px": 0},
                                   motion_out={"type": "fade", "dur_s": 0.15}), set(), role=role)
    caps = [SimpleNamespace(role=role, highlight=["사람"], lines=["한 줄", "두 줄"], text="한 줄\n두 줄")]
    na = checks.role_not_applicable(b, role, caps)
    k = lambda n: f"text.roles.{role}.{n}"   # noqa: E731
    assert set(na) == {k("timing.lead_s"), k("motion_in.offset_px")}
    # one line, max_lines 1 -> line_spacing does not apply; two lines under max_lines 1 -> it still applies
    b1 = _style_builder(_role_style(max_lines=1), set(), role="dialogue")
    assert "text.roles.dialogue.line_spacing" in checks.role_not_applicable(
        b1, "dialogue", [SimpleNamespace(role="dialogue", highlight=[], lines=["한 줄"], text="한 줄")])
    na2 = checks.role_not_applicable(b1, "dialogue", [SimpleNamespace(role="dialogue", highlight=[], lines=["a", "b"],
                                                                      text="a\nb")])
    assert "text.roles.dialogue.line_spacing" not in na2 and "text.roles.dialogue.timing.lead_s" not in na2
    # whole-video title: min_dur_s does not apply
    bt = _style_builder(_role_style(persist="whole_video"), set(), role="title")
    assert "text.roles.title.timing.min_dur_s" in checks.role_not_applicable(bt, "title", [])


# ============================================================================ 4. still scene source mapping
def _still(path, src_filter: str, dur: float = 4.0):
    import subprocess

    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "testsrc2=s=320x180:r=30:d=0.04", "-filter_complex",
                    f"[0:v]hue=s=0,{src_filter}loop=loop={int(dur * 30)}:size=1:start=0,setpts=N/30/TB",
                    "-frames:v", str(int(dur * 30)), "-r", "30", "-c:v", "libx264", "-preset", "ultrafast", "-crf", "16",
                    "-pix_fmt", "yuv420p", str(path)], check=True)


def _mapping(temp_root, out_filter: str | None, src_filter: str = ""):
    from shortkit.edit.ir import Clip, Rect
    from shortkit.qa.probes_video import analyze_mapping

    d = temp_root / "assets/test/generated"
    d.mkdir(parents=True, exist_ok=True)
    _still(d / "src_still.mp4", src_filter)
    out = d / "src_still.mp4"
    if out_filter is not None:
        out = d / "out_still.mp4"
        _still(out, out_filter)
    c = Clip(id="s1", source_id="v", source_path="assets/test/generated/src_still.mp4", src_in=0.0, src_out=4.0,
             speed=1.0, out_start=0.0, out_end=4.0, region=Rect(0.0, 0.0, 320.0, 180.0), fit="cover", src_size=(320, 180))
    ctx = SimpleNamespace(fps=30.0, mp4=out, resolved=SimpleNamespace(clips=[c], captions=[], decorations=[]))
    (it,) = analyze_mapping(ctx)["clips"]
    b = _style_builder(_role_style(), set())
    b.ctx.resolved = ctx.resolved
    b.ctx.fps = 30.0
    checks.rows_video(b, {"video": {"mapping": {"clips": [it]}}})
    return it, next(r for r in b.rows if r["check_id"] == "video.mapping")


def test_still_scene_that_shows_the_planned_frames_is_same(temp_root):
    it, row = _mapping(temp_root, None)
    assert not any(s["decisive"] for s in it["samples"])              # no source time stands out
    assert it["mode"] == "still_match" and min(it["still"]["ncc_planned"]) >= 0.95, it["still"]
    assert row["status"] == "same" and row["note"] == "정지 장면: 계획 구간과 시각적으로 동일 (시점 특정 불가)"


def test_still_scene_showing_other_frames_is_different(temp_root):
    it, row = _mapping(temp_root, "hflip,")                           # a different (mirrored) still picture
    assert it["mode"] == "still_mismatch", it.get("still")
    assert row["status"] == "different" and row["observed"]["mismatch_times"]
    it2, row2 = _mapping(temp_root, "crop=300:170:20:10,scale=320:180,")   # the same scene, shifted 20 px
    assert row2["status"] == "different", it2.get("still")


def test_still_scene_without_texture_stays_unmeasured(temp_root):
    it, row = _mapping(temp_root, None, src_filter="drawbox=x=0:y=0:w=320:h=180:color=gray:t=fill,")
    assert row["status"] == "unmeasured", it
    assert it["still"]["n_flat"] == len(it["samples"])


def test_defect_of_a_row_that_became_informational_is_superseded_not_fixed(temp_root):
    """A per-caption font row that was a required 못 잼 defect and is now informational (the per-role pooled row
    decides) is closed as 'superseded' -- never reported as fixed."""
    from shortkit.qa import defects

    ctx = SimpleNamespace(episode_id="e1")
    row = {"check_id": "caption.font", "row_id": "caption.font:c_desc", "status": "unmeasured", "required": True,
           "intended_change": False, "item": "자막 글꼴", "category": "폰트", "expected": "X", "observed": None,
           "note": "유사"}
    role_row = {"check_id": "caption.font", "row_id": "caption.font:role_description", "status": "same",
                "required": True, "intended_change": False, "item": "역할 글꼴", "category": "폰트"}
    rep = {"rows": [row], "gate": {"pass": False, "complete": False}, "output": {"sha256": "a"}}
    defects.sync(ctx, rep, recheck_others=False, quiet=True)
    assert defects.load("e1")[0]["status"] == "open"
    # the per-caption row is now informational AND names the (measured) per-role row that judges it
    rep["rows"] = [{**row, "required": False, "note": "참고 행", "covered_by": "caption.font:role_description"}, role_row]
    st = defects.sync(ctx, rep, recheck_others=False, quiet=True)
    d = defects.load("e1")[0]
    assert d["status"] == "superseded" and st.get("superseded") == 1 and st["verified_now"] == 0
    assert d["history"][-1]["event"] == "superseded" and "고쳐진 것이 아님" in d["history"][-1]["note"]
    # required and failing again -> reopened
    rep["rows"] = [row]
    defects.sync(ctx, rep, recheck_others=False, quiet=True)
    assert defects.load("e1")[0]["status"] == "reopened"


# ============================================================================ 1b. real test episodes (right font)
@pytest.mark.slow
@pytest.mark.parametrize("episode", ["test-pipeline-001", "test-coverage-001"])
def test_planned_font_per_role_on_the_test_episodes(episode):
    """The test episodes are rendered with exactly the planned faces (production libass path; the render refuses any
    substitution).  Per role the planned font must be 'identical': the exact-position re-render (same ASS event,
    libass, bt709, x264 at the output's CRF/preset, from frame 0 like production) reproduces the output crops within
    the re-encode noise and beats the top alternative faces by more than it.  Single-caption roles used to stay
    'similar' on the pooled statistics alone (test-pipeline-001 description: median IoU 0.9511 < pooled p10 0.9548)
    although the right face was rendered -- the exact re-render settles them."""
    from shortkit.qa import load_context
    from shortkit.qa.probes_text import probe_captions, probe_font_roles

    mp4 = REAL_ROOT / "episodes" / episode / "output" / f"{episode}.mp4"
    if not mp4.is_file():
        pytest.skip(f"{episode} not rendered here")
    ctx = load_context(episode)
    caps = probe_captions(ctx)
    roles = probe_font_roles(ctx, caps)
    assert set(roles) == {c.role for c in ctx.resolved.captions}
    for role, r in roles.items():
        assert r["status"] == "measured", (role, r.get("reason"))
        assert r["verdict"] == "identical", (role, r["verdict"], r.get("reasons"))
        assert r["exact"]["exact_role_verdict"] == "identical", (role, r["exact"])
        for cid, e in r["exact"]["captions"].items():
            assert e["mae_planned"] <= e["noise_mae"] and e["margin"] > e["noise_mae"], (role, cid, e)
        # the pooled statistics (second line of evidence) never contradict it
        assert r["exact"]["pooled_verdict"] in ("identical", "similar"), (role, r["exact"]["pooled_verdict"])


def test_ceiling_entrance_matches_the_renderer_tags():
    """The ceiling strings enter like the caption (production caption_events tags) and rest from the same frame count
    as the output caption: pop 0.12 s at 30 fps -> 4 frames (start + 0.12 s falls between frames 3 and 4)."""
    from shortkit.qa.font_id import entrance

    n, tag = entrance({"type": "pop", "dur_s": 0.12, "scale_from": 0.85}, 30.0)
    assert n == 4 and tag == "\\fscx85\\fscy85\\t(0,120,\\fscx100\\fscy100)"
    assert entrance({"type": "pop", "dur_s": 0.1, "scale_from": 1.35}, 30.0) == (3, "\\fscx135\\fscy135\\t(0,100,\\fscx100\\fscy100)")
    assert entrance({"type": "fade", "dur_s": 0.2}, 30.0) == (6, "\\fad(200,0)")
    assert entrance({"type": "none", "dur_s": 0.0}, 30.0) == (0, "") and entrance(None, 30.0) == (0, "")
    # the production renderer writes the same scale transform for this pop (test-coverage-001 c_rx)
    ass = (REAL_ROOT / "episodes/test-coverage-001/project/captions.ass")
    if ass.is_file():
        assert "\\fscx135\\fscy135\\t(0,100,\\fscx100\\fscy100)" in ass.read_text(encoding="utf-8")
