"""Reference analyzer vocabulary and sign shared with the renderer and QA (SYNTHETIC libass video, not channel data).

* A caption entering upward is measured as the renderer's ``slide_up`` (+ offset_px); a caption entering downward
  is recorded as ``slide_down`` with its direction and ``renderer_supported: false`` (resolve refuses it).
* lead_s = speech onset - caption start: the quoted line is heard at 3.0 s (audio/original.json speech segment), its
  caption shows at 2.8 s -> +0.2 (same case as tests/edit/test_motion_lead_semantics.py and
  tests/qa/test_qa_outputs.py::test_dialogue_lead_same_case_as_reference_and_resolve).
"""
from __future__ import annotations

import json
import subprocess

import numpy as np
import pytest

W, H, FPS = 540, 960, 30
SPEECH = [(3.0, 4.0)]
EVENTS = [
    # (start, end, override, text), one caption band (y = 700): an upward and a downward slide entrance (0.2 s, 40 px),
    # then the quoted dialogue line at 2.8 s
    (0.3, 1.2, r"{\move(270,740,270,700,0,200)}", "위로 올라온다"),
    (1.5, 2.4, r"{\move(270,660,270,700,0,200)}", "아래로 내려온다"),
    (2.8, 4.4, r"{\pos(270,700)}", "“진짜 왔어?”"),
]


def _t(s: float) -> str:
    cs = int(round(s * 100))
    return f"{cs // 360000}:{(cs // 6000) % 60:02d}:{(cs // 100) % 60:02d}.{cs % 100:02d}"


@pytest.fixture(scope="module")
def analyzed(tmp_path_factory):
    import cv2

    from shortkit.reference import textboxes

    d = tmp_path_factory.mktemp("rv_slide_lead")
    ass = d / "c.ass"
    lines = ["[Script Info]", "ScriptType: v4.00+", f"PlayResX: {W}", f"PlayResY: {H}", "ScaledBorderAndShadow: yes", "",
             "[V4+ Styles]",
             "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
             "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
             "MarginR, MarginV, Encoding",
             "Style: S,Noto Sans CJK KR Black,34,&H00FFFFFF,&H00FFFFFF,&H00000000,&H00000000,0,0,0,0,100,100,0,0,1,3,0,5,"
             "10,10,10,1", "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for a, b, ov, txt in EVENTS:
        lines.append(f"Dialogue: 0,{_t(a)},{_t(b)},S,,0,0,0,,{ov}{txt}")
    ass.write_text("\n".join(lines) + "\n", encoding="utf-8")
    rng = np.random.default_rng(3)
    g = cv2.resize(rng.normal(0, 1, (H // 40 + 2, W // 40 + 2)).astype(np.float32), (W, H), interpolation=cv2.INTER_CUBIC)
    g = np.clip(120 + 30 * g / float(np.abs(g).max()), 0, 255).astype(np.uint8)
    cv2.imwrite(str(d / "bg.png"), np.stack([g, g, g], axis=2))
    mp4 = d / "slides.mp4"
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-loop", "1", "-framerate", str(FPS), "-i",
                    "bg.png", "-t", "5.0", "-vf", "ass=c.ass,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "16", mp4.name], check=True, cwd=d)
    out = d / "analysis"
    (out / "audio").mkdir(parents=True)
    (out / "audio" / "original.json").write_text(json.dumps(
        {"speech": {"presence": "present", "segments": [{"start": a, "end": b} for a, b in SPEECH]}}), encoding="utf-8")
    cap, lay = textboxes.analyze(mp4, "slides", region={"video_region": None}, out_dir=out, save_frames=False)
    return cap, lay


def _item(cap, fragment):
    its = [it for it in cap["items"] if fragment in it["text"].replace(" ", "")]
    assert len(its) == 1, [it["text"] for it in cap["items"]]
    return its[0]


def test_upward_entrance_is_the_renderers_slide_up(analyzed):
    cap, lay = analyzed
    it = _item(cap, "올라온다")
    mi = it["style"]["motion_in"]
    assert it["motion_in"] == "slide_up" and mi["renderer_supported"] is True
    assert mi["direction_deg"] == pytest.approx(90, abs=15) and mi["offset_px"] == pytest.approx(40, abs=6)


def test_downward_entrance_is_recorded_with_its_direction_and_flagged(analyzed):
    cap, lay = analyzed
    it = _item(cap, "내려온다")
    mi = it["style"]["motion_in"]
    assert it["motion_in"] == "slide_down" and mi["renderer_supported"] is False
    assert mi["direction_deg"] == pytest.approx(-90, abs=15) and "not drawn by the renderer" in mi["note"]
    assert all(it["motion_in"] != "slide" for it in cap["items"])       # the old direction-less name is gone


def test_dialogue_lead_is_speech_onset_minus_caption_start(analyzed):
    cap, lay = analyzed
    it = _item(cap, "진짜왔어")
    assert it["role"] == "dialogue", it.get("role_reason")
    assert it["start"] == pytest.approx(2.8, abs=1.5 / FPS)
    assert it["style"]["lead_s"] == pytest.approx(0.2, abs=1.5 / FPS)      # caption BEFORE the line: positive
    assert lay["roles"]["dialogue"]["timing"]["lead_s"] == pytest.approx(0.2, abs=1.5 / FPS)


def test_aggregate_keeps_unsupported_motion_and_only_slide_up_offsets():
    from shortkit.reference.aggregate import motion_vocab_extra

    rows = [{"value": "slide_down"}, {"value": "slide_down"}, {"value": "pop"}]
    ex = motion_vocab_extra(rows, "in")
    assert ex["renderer_supported"] is False and ex["unsupported_values"] == {"slide_down": 2}
    assert motion_vocab_extra([{"value": "slide_up"}], "in")["renderer_supported"] is True
    assert motion_vocab_extra([{"value": "slide_up"}], "out")["renderer_supported"] is False     # no exit slides
    assert "ref analyze" in motion_vocab_extra([{"value": "slide"}], "in")["unsupported_note"]
