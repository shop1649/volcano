"""Exporters in sync with the master renderer (fast, no melt render):

  * flash Transition.scope: 'canvas' = whole frame, 'region' = video region (MLT, FCPXML, OTIO)
  * Zoom.recenter: every exported placement equals resolve.src_to_region on every frame
  * foreground limiter: read from build/fg_gain.json (per-frame gain), fallback build/stems vs
    render.pre_norm_stems (speed-changed originals), '못 잼' when the file does not fit the IR
  * blur sigma = render.blur_sigma_src (render.clean.blur_sigma_ratio), no hidden default
  * read_audio channel convention: mono files get +3.01 dB in MLT (melt upmixes mono at -3.01 dB),
    speed-changed originals are pre-rendered with the master's exact steps

Fixture media: assets/test/generated (CC-BY Intel sample clips + synthetic audio), test mode only.
"""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from fractions import Fraction

import numpy as np
import pytest

import export_fixtures as ef


def _props(el):
    return {p.get("name"): p.text for p in el.findall("property")}


def _cubic(p, kind):
    p = min(1.0, max(0.0, p))
    return {"in": p ** 3, "out": 1 - (1 - p) ** 3,
            "inout": 4 * p ** 3 if p < 0.5 else 1 - (-2 * p + 2) ** 3 / 2}.get(kind, p)


_OPS = {"g": "in", "h": "out", "i": "inout"}


def _eval_mlt_rect(anim: str, k: int) -> list[float]:
    """Evaluate an MLT rect animation ('0=x y w h o;15h=...;30=...') at relative frame k: the easing
    operator on a keyframe applies to the segment that starts there (melt 7.22)."""
    if "=" not in anim:
        return [float(v) for v in anim.split()[:4]]
    kfs = []
    for part in anim.split(";"):
        key, val = part.split("=")
        op = key[-1] if key[-1] in _OPS else ""
        kfs.append((int(key.rstrip("ghi")), op, [float(v) for v in val.split()[:4]]))
    if k <= kfs[0][0]:
        return kfs[0][2]
    for (k0, op, v0), (k1, _, v1) in zip(kfs, kfs[1:]):
        if k0 <= k <= k1:
            e = _cubic((k - k0) / (k1 - k0), _OPS.get(op, "linear"))
            return [a + (b - a) * e for a, b in zip(v0, v1)]
    return kfs[-1][2]


def _expected_rect(c, n, fps=30.0):
    """Canvas rect of the cropped source at output frame n straight from resolve.src_to_region."""
    from shortkit.edit.export_mlt import crop_int, region_int
    from shortkit.edit.resolve import src_to_region

    s, tx, ty = src_to_region(c, n / fps - c.out_start)
    _, _, cw, ch = crop_int(c)
    rx, ry, _, _ = region_int(c)
    return [rx + tx, ry + ty, s * cw, s * ch]


def _mlt(r, out_dir, monkeypatch, report=False):
    from shortkit.edit import export_mlt

    if not report:
        monkeypatch.setattr(export_mlt, "load_render_report", lambda r_: None)
    out, dec = export_mlt.export_with_decisions(r, out_dir, compute_loudness=False)
    return out, dec, ET.parse(out).getroot()


def _project(root, r):
    d = root / "episodes" / r.episode_id / "project"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ----------------------------------------------------------------------------- flash scope
@pytest.mark.parametrize("scope", ["region", "canvas"])
def test_flash_scope_canvas_vs_region(root, scope, monkeypatch):
    from shortkit.edit import export_fcpxml, export_otio
    from shortkit.edit.export_mlt import flash_runs

    otio = pytest.importorskip("opentimelineio")
    r = ef.build_resolved(f"test-export-flash-{scope}")
    r.clips[1].transition_in.scope = scope
    ef.write_ass(root, r)
    out_dir = _project(root, r)
    want = [0, 0, 360, 640] if scope == "canvas" else [0, 219, 360, 203]      # region = (0, 219, 360, 203)
    (fr,) = flash_runs(r)
    assert fr["scope"] == scope and fr["rect"] == want
    # MLT: the flash colour clip is placed over exactly that rect (profile px)
    out, dec, x = _mlt(r, out_dir, monkeypatch)
    (fl,) = [p for p in x.iter("producer") if p.get("id").startswith("flash")]
    aff = [_props(f) for f in fl.findall("filter") if _props(f)["mlt_service"] == "affine"][0]
    assert aff["transition.rect"] == " ".join(str(v) for v in want) + " 1"
    assert _props(fl)["shortkit:flash_scope"] == scope
    assert dec["flashes"][0]["scope"] == scope and dec["flashes"][0]["rect"] == want
    # FCPXML: a still of the rect's size, centred on the rect
    fx = ET.parse(export_fcpxml.export(r, out_dir)).getroot()
    (v,) = [e for e in fx.iter("video") if e.get("name", "").startswith("플래시")]
    asset = fx.find(f"resources/asset[@id='{v.get('ref')}']")
    fmt_ = fx.find(f"resources/format[@id='{asset.get('format')}']")
    assert (int(fmt_.get("width")), int(fmt_.get("height"))) == (want[2], want[3])
    px, py = (float(a) for a in v.find("adjust-transform").get("position").split())
    assert px == pytest.approx((want[0] + want[2] / 2 - 180) / 640 * 100, abs=1e-3)
    assert py == pytest.approx(-(want[1] + want[3] / 2 - 320) / 640 * 100, abs=1e-3)
    # OTIO metadata
    tl = otio.adapters.read_from_file(str(export_otio.export(r, out_dir)))
    v3 = [t for t in tl.tracks if t.name == "V3 플래시"][0]
    meta = [c for c in v3 if isinstance(c, otio.schema.Clip)][0].metadata["shortkit"]
    assert meta["scope"] == scope and [meta["rect"][k] for k in "xywh"] == want


def test_flash_unknown_scope_is_refused(root):
    from shortkit.edit.export_mlt import flash_runs

    r = ef.build_resolved("test-export-flash-bad")
    r.clips[1].transition_in.scope = "screen"
    with pytest.raises(ValueError, match="scope"):
        flash_runs(r)


# ----------------------------------------------------------------------------- zoom recenter
def _recenter_ir(eid, center):
    r = ef.build_resolved(eid)
    for c in r.clips:
        if c.zoom:
            c.zoom.recenter = True
    r.clips[0].zoom.center_src = center
    return r


@pytest.mark.parametrize("center,mode", [((1100.0, 450.0), "native_cubic_easing"),   # no cover clamp mid-zoom
                                         ((1500.0, 300.0), "per_frame")])            # cover clamp engages
def test_recenter_zoom_mlt_matches_src_to_region_every_frame(root, monkeypatch, center, mode):
    from shortkit.edit.export_mlt import zoom_animates

    r = _recenter_ir(f"test-export-rc-{mode}", center)
    ef.write_ass(root, r)
    out, dec, x = _mlt(r, _project(root, r), monkeypatch)
    zk = {z["clip"]: z for z in dec["zoom_keyframes"]}
    assert zk["c1"]["mode"] == mode and zk["c1"]["recenter"] is True
    assert zk["c3"]["mode"] == "per_frame"                   # off-grid zoom
    clips = {c.id: c for c in r.clips}
    moved = checked = 0
    for p in x.iter("producer"):
        pr = _props(p)
        if not p.get("id").split("_")[1:2] == ["video"] or "shortkit:piece" not in pr:
            continue
        c = clips[pr["shortkit:clip_id"]]
        assert zoom_animates(c) == (c.zoom is not None)
        n0, n1 = (int(v) for v in pr["shortkit:piece"].split(":")[1].split("-"))
        aff = [_props(f) for f in p.findall("filter") if _props(f)["mlt_service"] == "affine"][0]
        for n in range(n0, n1):          # every output frame of every piece (incl. crossfade halves)
            got = _eval_mlt_rect(aff["transition.rect"], n - n0)
            want = _expected_rect(c, n)
            assert got == pytest.approx(want, abs=0.01), (c.id, n, got, want)
            checked += 1
            moved += c.zoom is not None
    assert checked >= 171 and moved > 0
    # recenter really changes the placement (not the fixed-point zoom)
    import copy

    fixed = copy.deepcopy(r.clips[0])
    fixed.zoom.recenter = False
    assert _expected_rect(fixed, 45) != pytest.approx(_expected_rect(r.clips[0], 45), abs=1.0)


def test_recenter_with_constant_scale_still_animates():
    from shortkit.edit.export_mlt import zoom_animates

    r = ef.build_resolved("test-export-rc-const")
    z = r.clips[0].zoom
    z.scale_from = z.scale_to = 1.3
    assert not zoom_animates(r.clips[0])            # fixed point: constant placement
    z.recenter = True
    assert zoom_animates(r.clips[0])                # the anchor travels to the region centre
    z.scale_from = z.scale_to = 1.0
    assert not zoom_animates(r.clips[0])


def _t(s):
    s = s.rstrip("s")
    if "/" in s:
        a, b = s.split("/")
        return Fraction(int(a), int(b))
    return Fraction(s)


def test_recenter_zoom_fcpxml_and_otio_use_src_to_region(root):
    from shortkit.edit import export_fcpxml, export_otio
    from shortkit.edit.resolve import effective_src_rect, src_to_region

    otio = pytest.importorskip("opentimelineio")
    r = _recenter_ir("test-export-rc-nle", (1500.0, 300.0))
    ef.write_ass(root, r)
    out_dir = _project(root, r)
    fx = ET.parse(export_fcpxml.export(r, out_dir)).getroot()
    c = r.clips[0]
    el = [e for e in fx.iter("asset-clip") if e.get("name") == "c1"][0]
    start = _t(el.get("start"))
    pos = el.find("adjust-transform/param[@name='position']/keyframeAnimation")
    sca = el.find("adjust-transform/param[@name='scale']/keyframeAnimation")
    assert pos is not None and len(pos) >= 15                    # one keyframe per frame while zooming
    sw, sh = c.src_size
    ex, ey, ew, eh = effective_src_rect(c)
    for kp, ks in zip(pos, sca):
        n = int((_t(kp.get("time")) - start) * 30)               # clip c1 starts at output frame 0
        s, tx, ty = src_to_region(c, n / 30 - c.out_start)
        fxc = c.region.x + tx + s * (sw / 2 - ex)
        fyc = c.region.y + ty + s * (sh / 2 - ey)
        px, py = (float(v) for v in kp.get("value").split())
        assert px == pytest.approx((fxc - 180) / 640 * 100, abs=1e-3), n
        assert py == pytest.approx(-(fyc - 320) / 640 * 100, abs=1e-3), n
        assert float(ks.get("value").split()[0]) == pytest.approx(s, abs=1e-5)
        assert kp.get("interp") == "linear"
    # trim follows the visible window (FCP has no region mask)
    lefts = el.find("adjust-crop/trim-rect/param[@name='left']/keyframeAnimation")
    assert lefts is not None and len({k.get("value") for k in lefts}) > 1
    dec = json.loads((out_dir / "export_decisions.json").read_text(encoding="utf-8"))["fcpxml"]
    z1 = [z for z in dec["zoom"] if z["clip"] == "c1"][0]
    assert z1["recenter"] is True and z1["trim_animated"] is True
    # OTIO carries recenter + the per-frame rects of src_to_region
    tl = otio.adapters.read_from_file(str(export_otio.export(r, out_dir)))
    v2 = tl.tracks[1]
    m = [cl for cl in v2 if isinstance(cl, otio.schema.Clip)][0].metadata["shortkit"]
    assert m["zoom"]["recenter"] is True
    for k, rect in m["piece"]["canvas_rect_by_frame"].items():
        assert rect == pytest.approx(_expected_rect(c, m["piece"]["out_frames"][0] + int(k)), abs=1e-3)


# ----------------------------------------------------------------------------- foreground limiter
def _fg_profile(N):
    k = [1.0] * N
    for f in range(62, 72):          # SFX x1 at 2.05 s (frame 62..) is limited by up to -6 dB
        k[f] = 0.5
    for f in range(100, 104):        # inside the kept original line (2.2-4.2 s)
        k[f] = 0.8
    return k


def test_fg_gain_read_path_mlt_fcpxml_otio(root, monkeypatch):
    from shortkit.edit import export_fcpxml, export_otio
    from shortkit.edit.export_mlt import db

    otio = pytest.importorskip("opentimelineio")
    r = ef.build_resolved("test-export-fg")
    ef.write_ass(root, r)
    N = 171
    k = _fg_profile(N)
    ef.write_render_report(root, r, {"norm_gain_db": -2.0}, k=k)
    out_dir = _project(root, r)
    out, dec, x = _mlt(r, out_dir, monkeypatch, report=True)
    fl = dec["foreground_limiter"]
    assert fl["status"] == "있음" and fl["source"] == "episodes/test-export-fg/build/fg_gain.json"
    assert fl["master_max_reduction_db"] == pytest.approx(6.021, abs=1e-3)

    def limiter_levels(prod):
        f = [_props(q) for q in prod.findall("filter")
             if _props(q).get("shortkit:role") == "master foreground safety limiter"]
        return dict((int(a), float(b)) for a, b in (p.split("=") for p in f[0]["level"].split(";"))) if f else None

    sfx = [p for p in x.iter("producer") if _props(p).get("shotcut:caption", "").startswith("효과음")][0]
    orig = [p for p in x.iter("producer") if _props(p).get("shotcut:caption", "").startswith("원본 소리")][0]
    for prod, n0, e_in in ((sfx, round(2.05 * 30), 0), (orig, round(2.2 * 30), 0)):
        lv = limiter_levels(prod)
        # keyframe i = the gain at the END of clip frame i = boundary of output frames n0+i, n0+i+1
        for i, v in lv.items():
            a, b = k[min(N - 1, n0 + i - e_in)], k[min(N - 1, n0 + i - e_in + 1)]
            assert v == pytest.approx(db((a + b) / 2), abs=1e-3), (i, n0)
        assert min(lv.values()) == pytest.approx(-6.021, abs=0.01)       # both overlap frames 66..71
    lo = limiter_levels(orig)
    assert lo[102 - 66] == pytest.approx(db(0.8), abs=1e-3)              # the dip inside the kept line only
    bgm = [p for p in x.iter("producer") if _props(p).get("shotcut:caption", "").startswith("BGM")][0]
    assert limiter_levels(bgm) is None                              # the BGM is never limited
    # loudness gain from the same master report
    main = x.find("tractor[@id='tractor0']")
    vol = [_props(f) for f in main.findall("filter") if _props(f)["mlt_service"] == "volume"][0]
    assert float(vol["level"]) == pytest.approx(-2.0)
    # FCPXML: SFX volume keyframes include the dip; OTIO: metadata per frame
    fx = ET.parse(export_fcpxml.export(r, out_dir)).getroot()
    (sx,) = [e for e in fx.iter("asset-clip") if e.get("name", "").startswith("SFX")]
    vals = [float(q.get("value").rstrip("dB")) for q in sx.iter("keyframe")]
    assert vals and min(vals) == pytest.approx(-6.0 - 2.0 + db(0.5), abs=0.05)
    tl = otio.adapters.read_from_file(str(export_otio.export(r, out_dir)))
    a2 = [t for t in tl.tracks if t.name.startswith("A2")][0]
    meta = [c for c in a2 if isinstance(c, otio.schema.Clip)][0].metadata["shortkit"]
    assert meta["fg_limiter"]["source"].endswith("fg_gain.json") and min(meta["fg_limiter"]["gain_db_by_frame"]) < -5.9


def test_fg_gain_not_used_when_it_does_not_fit_the_ir(root, monkeypatch):
    r = ef.build_resolved("test-export-fg-bad")
    ef.write_ass(root, r)
    ef.write_render_report(root, r, {"norm_gain_db": -2.0}, k=_fg_profile(171)[:150])     # wrong frame count
    out, dec, x = _mlt(r, _project(root, r), monkeypatch, report=True)
    assert dec["foreground_limiter"]["status"] == "못 잼" and "프레임 수" in dec["foreground_limiter"]["why"]
    assert not [q for q in x.iter("property") if q.text == "master foreground safety limiter"]
    # a render_report from another render than fg_gain.json -> refused too
    ef.write_render_report(root, r, {"norm_gain_db": -2.0}, k=_fg_profile(171))
    rep = root / "episodes" / r.episode_id / "build" / "render_report.json"
    d = json.loads(rep.read_text(encoding="utf-8"))
    d["audio"]["norm_gain_db"] = -5.0
    rep.write_text(json.dumps(d), encoding="utf-8")
    out, dec, x = _mlt(r, _project(root, r), monkeypatch, report=True)
    assert dec["foreground_limiter"]["status"] == "못 잼" and "다른 렌더" in dec["foreground_limiter"]["why"]


def test_fg_gain_none_when_master_did_not_limit(root, monkeypatch):
    r = ef.build_resolved("test-export-fg-none")
    ef.write_ass(root, r)
    ef.write_render_report(root, r, {"norm_gain_db": -1.0})
    out, dec, x = _mlt(r, _project(root, r), monkeypatch, report=True)
    assert dec["foreground_limiter"]["status"] == "없음"
    assert not [q for q in x.iter("property") if q.text == "master foreground safety limiter"]


def test_fg_gain_fallback_from_stems_with_speed_changed_original(root):
    """No fg_gain.json (older render): k per frame from build/stems vs render.pre_norm_stems, which
    also covers a kept original played at 1.5x."""
    from shortkit.edit.export_mlt import master_foreground_gain
    from shortkit.edit.render import pre_norm_stems
    from shortkit.util.media import write_wav

    r = ef.build_resolved("test-export-fg-stems")
    o = r.audio.originals[0]
    o.speed, o.src_end = 1.5, 3.0                      # 3 s of source in 2 s of output
    st = pre_norm_stems(r)
    sr, n = st.sample_rate, len(st.bgm)
    fps, N = 30.0, 171
    kf = np.ones(N)
    kf[62:72], kf[80:95] = 0.5, 0.7                    # SFX and the (speed-changed) original line
    ks = np.repeat(kf, int(sr / fps))[:n]
    g = 10 ** (-3.0 / 20)
    stems = root / "episodes" / r.episode_id / "build" / "stems"
    write_wav(stems / "originals.wav", st.originals * g * ks[:, None], sr)
    write_wav(stems / "sfx.wav", st.sfx * g * ks[:, None], sr)
    rep = root / "episodes" / r.episode_id / "build" / "render_report.json"
    rep.write_text(json.dumps({"audio": {"norm_gain_db": -3.0, "final_trim_db": 0.0,
                                         "fg_limiter_max_reduction_db": 6.02}}), encoding="utf-8")
    dec: dict = {}
    k = master_foreground_gain(r, dec)
    assert dec["foreground_limiter"]["status"] == "있음" and "pre_norm_stems" in dec["foreground_limiter"]["source"]
    fg_frames = [f for f in range(N) if float(np.abs(st.foreground[int(f * sr / fps):int((f + 1) * sr / fps)]).max()) > 1e-3]
    assert any(80 <= f < 95 for f in fg_frames)       # the 1.5x original has content where it was limited
    for f in fg_frames:
        assert k[f] == pytest.approx(kf[f], abs=0.01), f


# ----------------------------------------------------------------------------- audio conventions
def test_speed_changed_original_prerender_equals_master_stem(root):
    """Media.tempo_original = the master's steps (read_audio stereo, unity mono upmix -> atempo)."""
    from shortkit.edit.export_mlt import Media
    from shortkit.edit.render import pre_norm_stems
    from shortkit.util.media import probe, read_audio

    r = ef.build_resolved("test-export-orig-speed")
    o = r.audio.originals[0]
    o.speed, o.src_end, o.fade_s = 1.5, 3.0, 0.0
    assert probe(root / o.path).audio_channels == 1          # mono speech: the channel convention matters
    out_dir = _project(root, r)
    dec = {"prerendered": [], "warnings": []}
    rel = Media(r, out_dir, dec).tempo_original(o, r.audio.sample_rate)
    got = read_audio(root / rel, sr=48000, mono=False)
    st = pre_norm_stems(r)
    s0 = int(round(o.out_start * 48000))
    m = int(round((o.out_end - o.out_start) * 48000))
    want = st.originals[s0:s0 + m]
    got = np.pad(got, ((0, max(0, m - len(got))), (0, 0)))[:m]
    assert float(np.abs(got - want).max()) < 2e-4
    assert float(np.sqrt((want ** 2).mean())) > 0.01
    assert dec["prerendered"][0]["kind"] == "original_tempo"


def test_mono_files_get_upmix_compensation_in_mlt(root, resolved, fresh_project, monkeypatch):
    from shortkit.edit.export_mlt import MONO_UPMIX_COMP_DB

    out, dec, x = _mlt(resolved, fresh_project, monkeypatch)
    assert MONO_UPMIX_COMP_DB == pytest.approx(3.0103, abs=1e-4)

    def comp(prod):
        return [_props(f)["level"] for f in prod.findall("filter")
                if (_props(f).get("shortkit:role") or "").startswith("mono->stereo")]
    by_cap = {_props(p).get("shotcut:caption", ""): p for p in x.iter("producer")}
    sfx = [p for c, p in by_cap.items() if c.startswith("효과음")][0]
    orig = [p for c, p in by_cap.items() if c.startswith("원본 소리")][0]
    bgm = [p for c, p in by_cap.items() if c.startswith("BGM")][0]
    assert comp(sfx) == ["3.0103"] and comp(orig) == ["3.0103"]         # whoosh.wav, speech_02.wav: mono
    assert comp(bgm) == []                                             # music_bed_a.wav: stereo
    files = dec["audio"]["mono_upmix_compensation"]["files"]
    assert sorted(files) == ["assets/test/generated/sfx/whoosh.wav", "assets/test/generated/speech_02.wav"]


# ----------------------------------------------------------------------------- blur
def test_blur_sigma_comes_from_render_blur_sigma_src(root, monkeypatch):
    from shortkit.edit import export_fcpxml, export_mlt
    from shortkit.edit.ir import TimedRect
    from shortkit.edit.render import RenderError, blur_sigma_src

    calls = []

    def fake_ffmpeg(args, **kw):
        calls.append([str(a) for a in args])
        open(args[-1], "wb").close()

    monkeypatch.setattr(export_mlt, "ffmpeg", fake_ffmpeg)
    monkeypatch.setattr(export_fcpxml, "ffmpeg", fake_ffmpeg)
    r = ef.build_resolved("test-export-blur", blur_sigma_ratio=0.25)
    c = r.clips[2]
    c.blur = [TimedRect(1300, 300, 240, 120, 10.5, 11.5, "synthetic blur test")]
    out_dir = _project(root, r)
    dec = {"prerendered": [], "warnings": []}
    export_mlt.Media(r, out_dir, dec).source_for(c)
    assert blur_sigma_src(c, c.blur[0]) == pytest.approx(60.0)
    assert "gblur=sigma=60.000" in calls[-1][calls[-1].index("-filter_complex") + 1]
    assert dec["prerendered"][0]["sigmas_src_px"] == [60.0]
    fdec = {"prerendered": [], "warnings": []}
    export_fcpxml.FcpBuilder(r, out_dir, False, fdec).nle_source(c)
    assert "gblur=sigma=60.000" in calls[-1][calls[-1].index("-filter_complex") + 1]
    assert fdec["prerendered"][0]["blur_sigmas_src_px"] == [60.0]
    # an IR without the preset value is refused (no hidden default)
    c.blur_sigma_ratio = None
    with pytest.raises(RenderError):
        export_mlt.Media(r, out_dir, {"prerendered": [], "warnings": []}).source_for(c)
