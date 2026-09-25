"""S2QA-11: `ref identity-templates` cuts the reference channel's OWN persistent overlays (logo / handle) out of the
snapshot's reference videos into ``identity_exclusions.logo_templates_dir`` (templates + manifest.json), and QA
``identity.logo_templates`` reads that folder.

Everything here is SYNTHETIC: tiny lavfi test-pattern clips with a drawn ring+triangle logo, a drawn plate and a drawn
channel-name text (labelled synthetic reference videos -- the real reference channel is not reachable here).  The fast
tests replace the detector with synthetic overlay records (the detector itself is tested in tests/clean); the slow
test runs the real ``shortkit.clean.detect`` on the synthetic clips.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from shortkit.reference import identity_templates as IT
from shortkit.util.jsonio import write_json
from shortkit.util.media import ffmpeg

P = "presets/joshuamagazine"
TDIR = f"{P}/reference/identity_templates"
W, H = 360, 640
LOGO = {"x": 300, "y": 12, "w": 48, "h": 48}
PLATE = {"x": 60, "y": 80, "w": 240, "h": 40}
NAME = {"x": 12, "y": 596, "w": 190, "h": 26}          # generous box around the drawn channel name
SRCWM = {"x": 12, "y": 12, "w": 120, "h": 22}


def _font() -> str:
    return subprocess.run(["fc-match", "-f", "%{file}", "DejaVu Sans:bold"], capture_output=True, text=True).stdout.strip()


def make_logo_png(path: Path) -> None:
    import cv2

    img = np.zeros((48, 48, 4), np.uint8)
    cv2.circle(img, (24, 24), 20, (0, 140, 255, 255), 5, cv2.LINE_AA)
    cv2.fillPoly(img, [np.array([[24, 9], [39, 36], [9, 36]], np.int32)], (255, 90, 20, 255), cv2.LINE_AA)
    cv2.imwrite(str(path), img)


PALETTE = ["0x3050a0", "0xa05030", "0x40a040", "0x806090", "0x909030"]


def make_ref_video(path: Path, k: int, logo: Path | None, plate: bool, name: bool, srcwm: str | None) -> None:
    """SYNTHETIC reference clip: a different flat colour per video with temporal noise (footage stand-in: nothing in
    it persists) + optional channel overlays."""
    font = _font()
    f = ["[0:v]noise=alls=25:allf=t+u,format=yuv420p[b]"]
    cur = "b"
    if logo is not None:
        f.append(f"[{cur}][1:v]overlay={LOGO['x']}:{LOGO['y']}[l]")
        cur = "l"
    draw = []
    if plate:
        draw.append(f"drawbox=x={PLATE['x']}:y={PLATE['y']}:w={PLATE['w']}:h={PLATE['h']}:color=white:t=fill")
        draw.append(f"drawtext=fontfile='{font}':text='DAILY CASE':x={PLATE['x'] + 40}:y={PLATE['y'] + 8}:fontsize=22:"
                    "fontcolor=black")
    if name:
        draw.append(f"drawtext=fontfile='{font}':text='JOSHUA MAGAZINE':x={NAME['x'] + 4}:y={NAME['y'] + 4}:fontsize=16:"
                    "fontcolor=white:borderw=2:bordercolor=black")
    if srcwm:
        draw.append(f"drawtext=fontfile='{font}':text='{srcwm}':x={SRCWM['x'] + 2}:y={SRCWM['y'] + 2}:fontsize=14:"
                    "fontcolor=white:borderw=2:bordercolor=black")
    if draw:
        f.append(f"[{cur}]" + ",".join(draw) + "[v]")
        cur = "v"
    inputs = ["-f", "lavfi", "-i", f"color=c={PALETTE[k % len(PALETTE)]}:s={W}x{H}:d=2:r=10"]
    if logo is not None:
        inputs += ["-loop", "1", "-i", str(logo)]
    ffmpeg([*inputs, "-filter_complex", ";".join(f), "-map", f"[{cur}]", "-t", "2", "-c:v", "libx264",
            "-preset", "veryfast", "-crf", "18", "-threads", "1", str(path)])


def snapshot(root, vids):
    write_json(root / P / "reference/latest100.json", {
        "schema": "shortkit.ref_snapshot/1", "status": "ok", "captured_at": "2026-01-01T00:00:00+00:00",
        "method": "SYNTHETIC", "videos": [{"rank": i + 1, "video_id": v, "url": f"https://www.youtube.com/watch?v={v}",
                                           "title": f"SYNTHETIC {v}", "duration": 2.0, "view_count": 1,
                                           "published_at": None, "kind": "short"} for i, v in enumerate(vids)]})


def captions(root, vid, items):
    write_json(root / P / "analysis" / vid / "captions.json",
               {"video_id": vid, "resolution": [W, H], "duration": 2.0, "items": items})


def ov(kind, rect, text=None, static=True, method="cross_shot_persistence"):
    return {"kind": kind, "rect": dict(rect), "resolution": [W, H], "start": 0.0, "end": 2.0, "text": text,
            "static": static, "template_t": 1.0, "evidence": {"method": method}}


def doc(overlays, review=(), text="measured", graphic="partial"):
    """SYNTHETIC detector output in the shortkit.overlays/1 shape (fields used by identity_templates)."""
    return {"source": {"resolution": [W, H], "duration": 2.0}, "overlays": list(overlays), "review": list(review),
            "checks": {"text_overlays": {"status": text}, "static_graphics": {"status": graphic}}}


@pytest.fixture()
def refset(proj, tmp_path):
    logo = tmp_path / "logo.png"
    make_logo_png(logo)
    vdir = proj / P / "reference/videos"
    vdir.mkdir(parents=True)
    make_ref_video(vdir / "vidR000001.mp4", 0, logo, plate=False, name=True, srcwm="@someone_one")
    make_ref_video(vdir / "vidR000002.mp4", 1, logo, plate=True, name=False, srcwm=None)
    make_ref_video(vdir / "vidR000003.mp4", 2, logo, plate=True, name=False, srcwm=None)
    snapshot(proj, ["vidR000001", "vidR000002", "vidR000003", "vidR000004"])     # vidR000004: not downloaded
    for v in ("vidR000001", "vidR000002", "vidR000003"):
        items = [{"start": 0.5, "end": 1.5, "role": "situation", "text": "모여 있다", "bbox": [80, 500, 200, 30]}]
        if v != "vidR000001":
            items.append({"start": 0.0, "end": 2.0, "role": "title", "text": "DAILY CASE", "bbox": [100, 86, 150, 26]})
        captions(proj, v, items)
    docs = {
        "vidR000001": doc([ov("logo", LOGO), ov("watermark", NAME, "JOSHUA MAGAZlNE", method="ocr"),   # OCR noise
                           ov("watermark", SRCWM, "@someone_one", method="ocr")]),
        "vidR000002": doc([ov("logo", LOGO), ov("source_overlay", PLATE, "DAILY CASE", method="ocr")]),
        "vidR000003": doc([ov("logo", LOGO), ov("source_overlay", PLATE, "DAILY CASE", method="ocr")]),
    }
    return proj, (lambda p: docs[Path(p).stem]), logo


def manifest(root) -> dict:
    return json.loads((root / TDIR / "manifest.json").read_text("utf-8"))


def test_templates_from_forbidden_text_and_recurrence(refset):
    root, det, _ = refset
    r = IT.extract("joshuamagazine", detector=det)
    m = manifest(root)
    assert r["status"] == m["status"] == "partial"                   # vidR000004 not downloaded + a review candidate
    assert "vidR000004" in m["blocker"] and "사람 확인" in m["blocker"]
    assert m["basis"]["scanned"] == ["vidR000001", "vidR000002", "vidR000003"]
    assert m["basis"]["not_downloaded"] == ["vidR000004"] and m["source_snapshot"] == "2026-01-01T00:00:00+00:00"
    by = {t["basis"]: t for t in m["templates"]}
    assert set(by) == {"forbidden_text", "recurrence"} and len(m["templates"]) == 2
    name = by["forbidden_text"]
    assert name["matched_term"] in ("joshuamagazine", "joshua magazine", "JOSHUA MAGAZINE")
    assert name["rect"] == NAME and name["resolution"] == [W, H] and name["evidence"][0]["video_id"] == "vidR000001"
    logo = by["recurrence"]
    assert logo["n_videos"] == 3 and logo["share"] == 1.0 and logo["rect"] == LOGO
    assert {e["video_id"] for e in logo["evidence"]} == {"vidR000001", "vidR000002", "vidR000003"}
    assert all(e["resolution"] == [W, H] and 0.0 <= e["t"] <= 2.0 for e in logo["evidence"])
    # seen by the per-video detector (exact rect, its template_t) AND by the cross-video check: one group
    assert all(e["t"] == 1.0 for e in logo["evidence"] if e["method"].startswith("clean.detect"))
    assert {e["method"] for e in logo["evidence"]} == {"clean.detect:cross_shot_persistence", "cross_video_persistence"}
    assert logo["crop_from"]["rect"] == LOGO
    for t in m["templates"]:
        f = root / t["file"]
        assert f.parent == root / TDIR and f.is_file() and len(t["sha256"]) == 64
    # the recurring plate overlaps the channel's own title caption: a STYLE element -> review, never a template
    assert len(m["review"]) == 1 and "자막과 겹침" in m["review"][0]["reason"]
    assert (root / m["review"][0]["file"]).parent == root / TDIR / "review"
    # a source's watermark in one video is neither the channel name nor recurring -> not an identity mark
    assert all("someone" not in str(t.get("text")) for t in m["templates"] + m["review"])
    # the logo crop really is the logo (reference pixels)
    import cv2
    crop = cv2.imread(str(root / logo["file"]))
    assert crop.shape[:2] == (LOGO["h"], LOGO["w"]) and crop.std() > 20


def test_qa_identity_check_reads_the_folder(refset, tmp_path):
    """QA identity.logo_templates matches the folder's templates: an output that copies the channel logo is
    'different', one without it is 'same' (the review/ subfolder is not read)."""
    from shortkit.qa.checks import _logo_template_check

    root, det, logo = refset
    IT.extract("joshuamagazine", detector=det)
    copied, clean = tmp_path / "copied.mp4", tmp_path / "clean.mp4"
    make_ref_video(copied, 3, logo, plate=False, name=False, srcwm=None)
    make_ref_video(clean, 3, None, plate=True, name=False, srcwm=None)     # plate (style) kept, no identity mark

    def ctx(mp4):
        return SimpleNamespace(resolved=SimpleNamespace(mode="production"), info=SimpleNamespace(duration=2.0), mp4=mp4)

    hit = _logo_template_check(ctx(copied), TDIR)
    assert hit["status"] == "different" and hit["observed"]["hits"]
    assert {h["template"] for h in hit["observed"]["hits"]} == {Path(t["file"]).name for t in manifest(root)["templates"]
                                                                if t["basis"] == "recurrence"}
    ok = _logo_template_check(ctx(clean), TDIR)
    assert ok["status"] == "same" and not ok["observed"]["hits"]
    assert all(not n.startswith("rev") for n in ok["expected"]["templates"])


def test_no_reference_videos_writes_unmeasured_manifest(proj):
    write_json(proj / P / "reference/latest100.json", {"status": "blocked", "blocker": "SYNTHETIC 403 youtube 차단",
                                                       "captured_at": "2026-01-02T00:00:00+00:00", "method": "yt-dlp",
                                                       "videos": []})
    r = IT.extract("joshuamagazine", detector=lambda p: pytest.fail("no video may be scanned"))
    m = manifest(proj)
    assert r["status"] == m["status"] == "unmeasured" and m["templates"] == [] and m["review"] == []
    assert "SYNTHETIC 403" in m["blocker"]
    assert not list((proj / TDIR).glob("*.png"))
    st = IT.manifest_status("joshuamagazine")
    assert st["status"] == "unmeasured" and st["exists"] and "SYNTHETIC 403" in st["blocker"]


def test_snapshot_members_not_downloaded(proj):
    snapshot(proj, ["vidR000001"])
    r = IT.extract("joshuamagazine", detector=lambda p: pytest.fail("nothing downloaded"))
    assert r["status"] == "unmeasured" and "ref download" in r["blocker"]


def test_rerun_removes_stale_generated_templates_keeps_manual_files(refset):
    root, det, _ = refset
    IT.extract("joshuamagazine", detector=det)
    manual = root / TDIR / "manual_logo.png"            # placed by a person: never deleted, listed, read by QA
    import cv2
    cv2.imwrite(str(manual), np.full((20, 20, 3), 128, np.uint8))
    first = {t["file"] for t in manifest(root)["templates"]}
    # the channel name is gone from the (synthetic) detector output now -> its template must not stay in use
    det2 = {k: {**det(Path(k + ".mp4"))} for k in ("vidR000001", "vidR000002", "vidR000003")}
    det2["vidR000001"] = doc([ov("logo", LOGO)])
    IT.extract("joshuamagazine", detector=lambda p: det2[Path(p).stem])
    m = manifest(root)
    assert [t["basis"] for t in m["templates"]] == ["recurrence"]
    for f in first - {t["file"] for t in m["templates"]}:
        assert not (root / f).exists()
    assert manual.is_file() and m["manual_files"] == [f"{TDIR}/manual_logo.png"]
    # later blocked run of the SAME snapshot keeps the result (the files stay valid evidence)
    (root / P / "reference/videos").rename(root / "videos_away")
    r = IT.extract("joshuamagazine", detector=lambda p: pytest.fail("nothing to scan"))
    assert r.get("kept_previous") and manifest(root)["templates"] == m["templates"]


def test_measured_with_no_identity_mark(proj, tmp_path):
    """Every member scanned, checks measured, nothing recurring: measured with templates [] (never a guessed logo)."""
    vdir = proj / P / "reference/videos"
    vdir.mkdir(parents=True)
    for i, v in enumerate(("vidR000001", "vidR000002")):
        make_ref_video(vdir / f"{v}.mp4", i, None, plate=False, name=False, srcwm=None)
        captions(proj, v, [])
    snapshot(proj, ["vidR000001", "vidR000002"])
    r = IT.extract("joshuamagazine", detector=lambda p: doc([], graphic="measured"))
    assert r["status"] == "measured" and r["templates"] == [] and r["blocker"] is None and r["note"]
    # the cross-video comparison covers text-free logos even where each video's own check could not (one static shot)
    r = IT.extract("joshuamagazine", detector=lambda p: doc([], graphic="unmeasured"))
    assert r["status"] == "measured" and r["basis"]["cross_video"]["status"] == "measured"
    # ... without it, a video whose text-free-logo check was unmeasured keeps the whole manifest partial
    r = IT.extract("joshuamagazine", detector=lambda p: doc([], graphic="unmeasured"), cross_video=False)
    assert r["status"] == "partial" and "고정 로고 검사 못 잼" in r["blocker"]


def test_cross_video_finds_logo_the_detector_missed(proj, tmp_path):
    """Text-free logo, each video one static shot (the per-video detector reports nothing, graphic check unmeasured):
    the cross-video persistence check finds it; a mark in the middle of the frame goes to review (not a logo place)."""
    logo = tmp_path / "logo.png"
    make_logo_png(logo)
    vdir = proj / P / "reference/videos"
    vdir.mkdir(parents=True)
    ids = ["vidR000001", "vidR000002", "vidR000003"]
    for i, v in enumerate(ids):
        make_ref_video(vdir / f"{v}.mp4", i, logo, plate=False, name=False, srcwm=None)
        captions(proj, v, [])
    snapshot(proj, ids)
    r = IT.extract("joshuamagazine", detector=lambda p: doc([], graphic="unmeasured"))
    assert r["status"] == "measured", r["blocker"]
    [t] = r["templates"]
    assert t["basis"] == "recurrence" and t["n_videos"] == 3
    assert {e["method"] for e in t["evidence"]} == {"cross_video_persistence"}
    x = t["rect"]
    assert x["x"] <= LOGO["x"] and x["y"] <= LOGO["y"] and x["x"] + x["w"] >= LOGO["x"] + LOGO["w"] - 2 \
        and x["y"] + x["h"] >= LOGO["y"] + LOGO["h"] - 2 and x["w"] <= LOGO["w"] + 16


def test_non_corner_recurrence_needs_a_person_then_decisions_stick(refset):
    """A recurring overlay outside the logo places is never auto-accepted; a person's --accept makes it a template
    and the decision is re-applied on the next scan; --reject keeps it out."""
    root, det, _ = refset
    mid = {"x": 150, "y": 300, "w": 60, "h": 40}
    det3 = {k: {**det(Path(k + ".mp4"))} for k in ("vidR000001", "vidR000002", "vidR000003")}
    for k in det3:
        det3[k] = {**det3[k], "overlays": det3[k]["overlays"] + [ov("logo", mid)]}
    r = IT.extract("joshuamagazine", detector=lambda p: det3[Path(p).stem])
    rev = [x for x in r["review"] if x["rect"] == mid]
    assert len(rev) == 1 and "로고 전형" in rev[0]["reason"]
    with pytest.raises(ValueError):
        IT.decide("joshuamagazine", rev[0]["id"], "accept", by="")
    m = IT.decide("joshuamagazine", rev[0]["id"], "accept", by="tester(looked at the crop)")
    acc = [t for t in m["templates"] if t["rect"] == mid]
    assert len(acc) == 1 and acc[0]["confirmed_by"] == "tester(looked at the crop)" and (root / acc[0]["file"]).is_file()
    assert (root / acc[0]["file"]).parent == root / TDIR
    # the plate is still pending
    assert m["status"] == "partial" and any("자막과 겹침" in x["reason"] for x in m["review"])
    plate = next(x for x in m["review"] if "자막과 겹침" in x["reason"])
    m = IT.decide("joshuamagazine", plate["id"], "reject", by="tester(looked at the crop)", note="제목 판(스타일)")
    assert not m["review"] and [x["rect"] for x in m["rejected"]] == [PLATE]
    # re-scan: both decisions are re-applied, nothing pending (vidR000004 still missing -> partial for that only)
    r = IT.extract("joshuamagazine", detector=lambda p: det3[Path(p).stem])
    assert not r["review"] and any(t["rect"] == mid and t.get("confirmed_by") for t in r["templates"])
    assert [x["rect"] for x in r["rejected"]] == [PLATE]
    assert not list((root / TDIR / "review").glob("*.png"))            # the rejected crop does not linger
    assert (root / TDIR / "decisions.json").is_file()
    assert [x["code"] for x in r["partial_reasons"]] == ["not_downloaded"]


def test_forbidden_match():
    terms = ["조슈아매거진", "joshuamagazine", "JOSHUA MAGAZINE"]
    assert IT.forbidden_match("@joshuamagazine", terms) == "joshuamagazine"
    assert IT.forbidden_match("조슈아 매거진 제공", terms) == "조슈아매거진"
    assert IT.forbidden_match("JOSHUA MAGAZlNE", terms)                   # one OCR error
    assert IT.forbidden_match("@someone_one", terms) is None
    assert IT.forbidden_match("", terms) is None


@pytest.mark.slow
def test_real_detector_on_synthetic_references(proj, tmp_path):
    """The real shortkit.clean.detect over SYNTHETIC reference clips cut from the CC-BY Intel sample videos (two shots
    each, different offsets per video) with the same drawn logo: the recurring logo becomes a template, and the
    source footage itself (different in every video) yields no template."""
    vid_dir = Path(__file__).resolve().parents[2] / "assets/test/generated/video"
    a_src, b_src = vid_dir / "classroom.mp4", vid_dir / "people-detection.mp4"
    if not (a_src.is_file() and b_src.is_file()):
        pytest.skip("Intel sample clips missing: python -m shortkit testassets fetch-video --local-dir ...")
    logo = tmp_path / "logo.png"
    make_logo_png(logo)
    vdir = proj / P / "reference/videos"
    vdir.mkdir(parents=True)
    ids = ["vidS000001", "vidS000002", "vidS000003"]
    for i, v in enumerate(ids):
        o = 3 * i
        shots = (f"[0:v]trim={o}:{o + 3},setpts=PTS-STARTPTS,scale=-2:{H},crop={W}:{H},fps=10,format=yuv420p[a];"
                 f"[1:v]trim={o}:{o + 3},setpts=PTS-STARTPTS,scale=-2:{H},crop={W}:{H},fps=10,format=yuv420p[b];"
                 f"[a][b]concat=n=2:v=1:a=0[c];[c][2:v]overlay={LOGO['x']}:{LOGO['y']}[v]")
        ffmpeg(["-i", str(a_src), "-i", str(b_src), "-loop", "1", "-i", str(logo), "-filter_complex", shots,
                "-map", "[v]", "-t", "6", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-threads", "1",
                str(vdir / f"{v}.mp4")])
        captions(proj, v, [])
    snapshot(proj, ids)
    r = IT.extract("joshuamagazine")
    rec = [t for t in r["templates"] if t["basis"] == "recurrence"]
    assert len(rec) == 1, (r["templates"], r["review"])
    x = rec[0]["rect"]
    assert abs(x["x"] - LOGO["x"]) <= 8 and abs(x["y"] - LOGO["y"]) <= 8 and rec[0]["n_videos"] == 3
    assert any(e["method"].startswith("clean.detect") for e in rec[0]["evidence"])
    # these three clips share their footage (same two sources, 3 s apart): the cross-video check says it cannot tell
    # marks from content instead of guessing
    xv = r["basis"]["cross_video"]
    assert xv["status"] == "measured" or "내용" in xv["groups"][0]["reason"]
