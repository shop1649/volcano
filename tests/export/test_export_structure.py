"""Fast structure tests for the project exporters (no melt render).

Fixture: 3 clips from assets/test/generated (dirty_source crop+delogo+zoom / people-detection
flash+freeze / classroom crossfade+1.5x+off-grid zoom), 2 captions + 1 decoration in one ASS,
BGM with ducking envelope, 1 SFX, 1 kept original line (espeak-ng TTS wav as 'vocals' stem).
"""
from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path

import pytest

import export_fixtures as ef


# ----------------------------------------------------------------------------- timeline math
def test_pieces_split_freeze_exactly_where_render_holds(resolved):
    from shortkit.edit.export_mlt import clip_pieces
    from shortkit.edit.resolve import src_time_at

    ps = clip_pieces(resolved, 1)              # c2: flash in, freeze 3.5s held 0.6s from out 2.5s
    assert [p.kind for p in ps] == ["play", "hold", "play"]
    assert (ps[0].n0, ps[0].n1, ps[1].n1, ps[2].n1) == (60, 75, 93, 123)
    assert ps[1].length == 18 and ps[1].s0 == pytest.approx(3.5)
    c = resolved.clips[1]
    for p in ps:                                # every frame's kind agrees with render.src_time_at
        for n in range(p.n0, p.n1):
            s = src_time_at(c, n / 30 - c.out_start)
            assert (s == pytest.approx(3.5)) == (p.kind == "hold") or p.kind == "play"


def test_segments_crossfade_and_contiguity(resolved):
    from shortkit.edit.export_mlt import build_segments

    warn: list[str] = []
    segs = build_segments(resolved, warn)
    assert not warn
    assert segs[0].n0 == 0 and segs[-1].n1 == 171
    for a, b in zip(segs, segs[1:]):
        assert a.n1 == b.n0                     # contiguous, no overlap on the track
    xf = [s for s in segs if s.kind == "crossfade"]
    assert len(xf) == 1 and (xf[0].n0, xf[0].n1) == (111, 123)      # 3.7s .. 4.1s
    assert xf[0].a_pieces[0].n0 == 111 and xf[0].a_pieces[-1].n1 == 123
    assert xf[0].b_pieces[0].n0 == 111 and xf[0].b_pieces[-1].n1 == 123
    assert resolved.clips[xf[0].a_pieces[0].clip_index].id == "c2"
    assert resolved.clips[xf[0].b_pieces[0].clip_index].id == "c3"


def test_flash_alpha_matches_render_formula(resolved):
    from shortkit.edit.export_mlt import flash_runs

    (fr,) = flash_runs(resolved)
    assert (fr["n0"], fr["n1"]) == (58, 63)                          # |t-2.0| < 0.1
    assert fr["alphas"][2] == pytest.approx(1.0)
    for k, a in enumerate(fr["alphas"]):
        assert a == pytest.approx(1 - abs((58 + k) / 30 - 2.0) / 0.1)


def test_caption_files(root, resolved, fresh_project):
    from shortkit.edit.export_mlt import write_caption_files

    res = write_caption_files(resolved, fresh_project)
    assert res["ass"] == "captions.ass" and res["srt_count"] == 2
    assert (fresh_project / "captions.ass").read_bytes() == (root / resolved.ass_path).read_bytes()
    srt = (fresh_project / "captions.srt").read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:05,700\n테스트 제목" in srt
    assert "00:00:00,500 --> 00:00:03,000\n문이 열린다" in srt


# ----------------------------------------------------------------------------- MLT
@pytest.fixture
def mlt(root, resolved, fresh_project, monkeypatch):
    from shortkit.edit import export_mlt

    monkeypatch.setattr(export_mlt, "load_render_report", lambda r: None)   # independent of test order
    out, dec = export_mlt.export_with_decisions(resolved, fresh_project, compute_loudness=False)
    return out, dec, ET.parse(out).getroot()


def _props(el):
    return {p.get("name"): p.text for p in el.findall("property")}


def test_mlt_profile_tracks_and_relative_paths(root, mlt):
    out, dec, x = mlt
    prof = x.find("profile").attrib
    assert (prof["width"], prof["height"], prof["frame_rate_num"], prof["frame_rate_den"]) == ("360", "640", "30", "1")
    assert (prof["display_aspect_num"], prof["display_aspect_den"]) == ("9", "16")
    assert x[-1].tag == "tractor" and x[-1].get("id") == "tractor0"          # melt plays the last service
    names = [_props(pl).get("shotcut:name") for pl in x.findall("playlist") if _props(pl).get("shotcut:name")]
    assert names == ["V1 배경", "V2 영상", "V3 플래시", "A1 BGM", "A2 효과음", "A3 원본 소리"]
    text = out.read_text(encoding="utf-8")
    assert str(root) not in text and "/home/" not in text and "/tmp/" not in text
    for p in x.iter("producer"):
        res = _props(p).get("resource", "")
        if _props(p).get("mlt_service") in ("avformat", "qimage", "timewarp"):
            rel = res.split(":", 1)[1] if _props(p)["mlt_service"] == "timewarp" else res
            assert not Path(rel).is_absolute() and (out.parent / rel).is_file(), rel


def test_mlt_clip_filters(mlt, resolved):
    out, dec, x = mlt
    prods = {p.get("id"): p for p in x.iter("producer")}
    c1 = prods["c1_video_0"]
    f = {_props(fl)["mlt_service"]: _props(fl) for fl in c1.findall("filter")}
    assert f["crop"]["bottom"] == "80" and f["crop"]["top"] == "0"
    # delogo: SOURCE (16,14,190,44) -> cropped frame scaled to profile height (640/1000)
    k = 640 / 1000
    assert (int(f["avfilter.delogo"]["av.x"]), int(f["avfilter.delogo"]["av.w"])) == (round(16 * k), round(190 * k))
    assert f["qtcrop"]["rect"] == "0 219 360 203 1"
    rect = f["affine"]["transition.rect"]
    assert "15h=" in rect                       # zoom starts at 0.5 s on the frame grid: native cubic ease-out
    c3 = [p for pid, p in prods.items() if pid.startswith("c3_video")]
    assert all(_props(p)["mlt_service"] == "timewarp" and _props(p)["warp_speed"] == "1.5" for p in c3)
    c3_rects = [_props(fl)["transition.rect"] for p in c3 for fl in p.findall("filter")
                if _props(fl)["mlt_service"] == "affine"]
    assert any(r.count(";") > 5 for r in c3_rects)   # off-grid zoom (118.5 frames) -> per-frame keyframes
    hold = [p for pid, p in prods.items() if pid.startswith("c2_video") and _props(p)["mlt_service"] == "qimage"]
    assert len(hold) == 1 and hold[0].get("out") == "17"


def test_mlt_transitions_flash_audio(mlt):
    out, dec, x = mlt
    xt = [t for t in x.findall("tractor") if _props(t).get("shotcut:transition") == "lumaMix"]
    assert len(xt) == 1
    svcs = sorted(_props(t)["mlt_service"] for t in xt[0].findall("transition"))
    assert svcs == ["luma", "mix"] and xt[0].get("out") == "11"
    flash = [p for p in x.iter("producer") if p.get("id").startswith("flash")]
    assert len(flash) == 1
    alpha = [_props(fl) for fl in flash[0].findall("filter") if _props(fl)["mlt_service"] == "brightness"][0]["alpha"]
    assert alpha.split(";")[2] == "2=1"
    main = x.find("tractor[@id='tractor0']")
    tfs = {_props(fl)["mlt_service"]: _props(fl) for fl in main.findall("filter")}
    assert tfs["avfilter.subtitles"]["av.filename"] == "captions.ass"
    assert "volume" not in tfs                   # compute_loudness=False and no render report -> no invented gain
    assert dec["loudness"]["gain_db"] is None and dec["loudness"]["status"] == "못 잼"
    pls = {_props(pl).get("shotcut:name"): pl for pl in x.findall("playlist")}
    sfx = pls["A2 효과음"]
    assert sfx[2].tag == "blank" and sfx[2].get("length") == str(round(2.05 * 30))
    orig = pls["A3 원본 소리"]
    assert orig[2].tag == "blank" and orig[2].get("length") == "66"
    bgm_prod = [p for p in x.iter("producer") if _props(p).get("shotcut:caption", "").startswith("BGM")][0]
    levels = [_props(fl) for fl in bgm_prod.findall("filter")]
    env = [l for l in levels if l.get("shortkit:role", "").startswith("envelope")][0]["level"]
    # ducked -10 dB inside the kept-dialogue range (frame 90 ~ 3.0 s), 0 dB outside (frame 30)
    kf = dict((int(a), float(b)) for a, b in (p.split("=") for p in env.split(";")))
    ks = sorted(kf)

    def at(n):
        for a, b in zip(ks, ks[1:]):
            if a <= n <= b:
                return kf[a] + (kf[b] - kf[a]) * (n - a) / (b - a)
        return kf[ks[-1]]
    assert at(30) == pytest.approx(0.0, abs=0.01) and at(90) == pytest.approx(-10.0, abs=0.01)
    tracks = main.findall("track")
    assert [t.get("hide") for t in tracks[1:4]] == ["audio"] * 3        # original sound OFF on video tracks
    assert [t.get("hide") for t in tracks[4:]] == ["video"] * 3


# ----------------------------------------------------------------------------- FCPXML
def _t(s: str) -> Fraction:
    s = s.rstrip("s")
    if "/" in s:
        a, b = s.split("/")
        return Fraction(int(a), int(b))
    return Fraction(s)


@pytest.fixture
def fcpxml(root, resolved, fresh_project):
    from shortkit.edit import export_fcpxml

    out = export_fcpxml.export(resolved, fresh_project)
    return out, ET.parse(out).getroot()


def test_fcpxml_wellformed_and_consistent(fcpxml, resolved):
    out, x = fcpxml
    assert x.tag == "fcpxml" and x.get("version") == "1.9"
    assert out.read_text(encoding="utf-8").startswith('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>')
    ids = {e.get("id") for e in x.find("resources")} | {e.get("id") for e in x.iter("text-style-def")}
    assert len([e for e in x.iter("text-style-def")]) == len({e.get("id") for e in x.iter("text-style-def")})
    for e in x.iter():
        if e.get("ref"):
            assert e.get("ref") in ids, e.get("ref")
        if e.get("format"):
            assert e.get("format") in ids
    seq = x.find("library/event/project/sequence")
    fd = _t(x.find(f"resources/format[@id='{seq.get('format')}']").get("frameDuration"))
    assert fd == Fraction(1, 30)
    total = _t(seq.get("duration"))
    assert total == Fraction(171, 30)
    spine = seq.find("spine")
    cur = Fraction(0)
    items = [e for e in spine if e.tag in ("asset-clip", "gap")]
    for e in spine:
        off, dur = _t(e.get("offset")), _t(e.get("duration"))
        assert (off / fd).denominator == 1 and (dur / fd).denominator == 1      # on the frame grid
        if e.tag == "transition":
            assert off < cur < off + dur                                         # straddles the cut
            continue
        assert off == cur, (e.tag, e.get("name"))                              # contiguous, monotonic
        cur = off + dur
    assert cur == total == sum(_t(e.get("duration")) for e in items)
    assert [e.get("name") for e in items if e.tag == "asset-clip"] == ["c1", "c2", "c3"]
    tr = spine.find("transition")
    assert _t(tr.get("offset")) == Fraction(111, 30) and _t(tr.get("duration")) == Fraction(12, 30)
    # connected clips: lane set, local offset inside the parent's local range
    n_conn = 0
    for parent in items:
        p0 = _t(parent.get("start", "0s"))
        for ch in parent:
            if ch.get("lane") is None:
                continue
            n_conn += 1
            assert p0 <= _t(ch.get("offset")) < p0 + _t(parent.get("duration")), ch.get("name")
    captions = list(x.iter("caption"))
    assert len(captions) == 2 and {c.find("text/text-style").text for c in captions} == {"테스트 제목", "문이 열린다"}
    assert n_conn == 1 + 1 + 1 + 1 + 2                   # BGM, SFX, original, flash, 2 captions
    c2 = items[1] if items[1].get("name") == "c2" else [e for e in items if e.get("name") == "c2"][0]
    tps = [(_t(t.get("time")), _t(t.get("value"))) for t in c2.find("timeMap")]
    flat = [a for a, b in zip(tps, tps[1:]) if a[1] == b[1]]
    assert len(flat) == 1 and flat[0][1] == Fraction(7, 2)                    # the freeze hold at 3.5 s
    c3 = [e for e in items if e.get("name") == "c3"][0]
    tps = [(_t(t.get("time")), _t(t.get("value"))) for t in c3.find("timeMap")]
    (a, b), (c, d) = tps[0], tps[-1]
    assert float((d - b) / (c - a)) == pytest.approx(1.5, rel=0.03)            # 1.5x speed
    for e in x.iter("media-rep"):
        src = e.get("src")
        assert not src.startswith("file:") and (out.parent / src).is_file(), src


def test_fcpxml_absolute_variant_is_local_only(root, resolved, fresh_project):
    from shortkit.edit import export_fcpxml

    out = export_fcpxml.export(resolved, fresh_project, absolute=True)
    assert out.name.endswith(".local.fcpxml")
    x = ET.parse(out).getroot()
    srcs = [e.get("src") for e in x.iter("media-rep")]
    assert srcs and all(s.startswith("file:///") for s in srcs)


# ----------------------------------------------------------------------------- OTIO
def test_otio_round_trip(root, resolved, fresh_project):
    otio = pytest.importorskip("opentimelineio")
    from shortkit.edit import export_otio

    out = export_otio.export(resolved, fresh_project)
    tl = otio.adapters.read_from_file(str(out))
    assert tl.name == resolved.episode_id
    names = [t.name for t in tl.tracks]
    assert names[:3] == ["V1 배경", "V2 영상", "V3 플래시"] and "A1 BGM" in names and "A3 원본 소리" in names
    v2 = tl.tracks[1]
    assert v2.duration().to_frames() == 171
    clips = [c for c in v2 if isinstance(c, otio.schema.Clip)]
    assert any(isinstance(e, otio.schema.FreezeFrame) for c in clips for e in c.effects)
    assert any(isinstance(e, otio.schema.LinearTimeWarp) and e.time_scalar == 1.5 for c in clips for e in c.effects)
    trs = [t for t in v2 if isinstance(t, otio.schema.Transition)]
    assert len(trs) == 1 and (trs[0].in_offset + trs[0].out_offset).to_frames() == 12
    for c in clips:
        url = c.media_reference.target_url
        assert not Path(url).is_absolute() and (out.parent / url).is_file()
        assert c.metadata["shortkit"]["clip_id"] in ("c1", "c2", "c3")
    assert clips[0].metadata["shortkit"]["zoom"]["scale_to"] == 1.3
    assert clips[0].metadata["shortkit"]["cleaning"]["delogo"][0]["x"] == 16
    assert len(v2.markers) == 2 and {m.metadata["shortkit"]["role"] for m in v2.markers} == {"title", "situation"}
    sfx = [t for t in tl.tracks if t.name.startswith("A2")][0]
    (m,) = sfx.markers
    assert m.metadata["shortkit"]["kind"] == "sfx_event" and m.metadata["shortkit"]["event_t"] == 2.1
    # a second write of what was read is identical (lossless round trip)
    again = fresh_project / "again.otio"
    otio.adapters.write_to_file(tl, str(again))
    assert otio.adapters.read_from_file(str(again)).to_json_string() == tl.to_json_string()


# ----------------------------------------------------------------------------- verify honesty
def test_verify_without_melt_is_unmeasured(root, resolved, fresh_project, monkeypatch):
    from shortkit.edit import export_mlt, verify_project
    from shortkit.util.jsonio import read_json

    out, _ = export_mlt.export_with_decisions(resolved, fresh_project, compute_loudness=False)
    monkeypatch.setattr(verify_project, "find_melt", lambda: None)
    stand_in = root / "assets/test/generated/dirty_source.mp4"      # any existing file: melt check comes first
    res = verify_project.verify(resolved, stand_in, out)
    assert res["status"] == "unmeasured" and "melt" in res["why"] and "rows" not in res
    assert read_json(fresh_project / "verify.json")["status"] == "unmeasured"


def test_verify_without_master_is_unmeasured(root, resolved, fresh_project):
    from shortkit.edit import export_mlt, verify_project

    out, _ = export_mlt.export_with_decisions(resolved, fresh_project, compute_loudness=False)
    res = verify_project.verify(resolved, root / "episodes" / "nope.mp4", out)
    assert res["status"] == "unmeasured" and "마스터" in res["why"]


def test_verify_non_mlt_never_passes_and_keeps_mlt_result(root, resolved, fresh_project):
    from shortkit.edit import verify_project
    from shortkit.util.jsonio import read_json, write_json

    write_json(fresh_project / "verify.json", {"status": "pass", "status_ko": "통과", "global": {"x": 1}})
    f = fresh_project / f"{resolved.episode_id}.fcpxml"
    f.write_text("<fcpxml/>", encoding="utf-8")
    res = verify_project.verify(resolved, root / "assets/test/generated/dirty_source.mp4", f)
    assert res["status"] == "unmeasured"
    d = read_json(fresh_project / "verify.json")
    assert d["status"] == "pass" and "why" not in d and d["other_formats"]["fcpxml"]["status"] == "unmeasured"


def test_readme_says_unmeasured_without_verification(root, resolved, fresh_project, monkeypatch):
    from shortkit.edit import export_mlt, project_readme

    monkeypatch.setattr(export_mlt, "load_render_report", lambda r: None)
    export_mlt.export_with_decisions(resolved, fresh_project, compute_loudness=False)
    f = project_readme.write(resolved, fresh_project, {"plan_sha256": "abc"})
    t = f.read_text(encoding="utf-8")
    assert "## 검증한 것" in t and "**못 잼**" in t and "통과" not in t.split("## 검증한 것")[1].split("##")[0]
    assert "captions.ass" in t and "한 레이어" in t and "Kdenlive" in t
    assert "전체 음량 이득: **못 잼**" in t
