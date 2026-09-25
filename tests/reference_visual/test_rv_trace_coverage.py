"""Reverse trace coverage (review findings S5-01, S5-02, S5-05, S5-06, S5-07).

Descriptions, snapshot / listing entries and captions are SYNTHETIC; the on-screen credit video is built
here with ffmpeg (moving test pattern in a band + static text in the black band) -- never channel data."""
from __future__ import annotations

import json
import os
import subprocess

import pytest

from shortkit.reference import trace_sources as T
from shortkit.sourcing import exclusions as X
from shortkit.util.jsonio import write_json

P = "presets/joshuamagazine"


def _snap(proj, ids, hv=()):
    write_json(proj / P / "reference/latest100.json", {
        "status": "ok", "captured_at": "SYNTHETIC", "videos": [
            {"rank": i + 1, "video_id": v, "title": "SYNTHETIC", "url": f"https://www.youtube.com/watch?v={v}"}
            for i, v in enumerate(ids)]})
    write_json(proj / P / "reference/high_views.json", {"status": "ok", "unverified": [], "videos": [
        {"video_id": v, "url": f"https://www.youtube.com/watch?v={v}", "view_count": 1_500_000, "in_latest100": False}
        for v in hv]})
    write_json(proj / P / "reference/all_videos.json", {"status": "ok", "videos": [
        {"video_id": v, "url": f"https://www.youtube.com/watch?v={v}"} for v in list(ids) + list(hv) + ["OLDNOHV0001"]]})


def _rows(proj):
    return [json.loads(x) for x in (proj / "warehouse/exclusions.jsonl").read_text("utf-8").splitlines() if x.strip()]


def test_description_urls_all_fenced_off_except_own(proj):
    """S5-01: a credited YouTube original and a bare (no credit keyword) TikTok post URL are both excluded;
    the reference channel's own profile link is not a source."""
    _snap(proj, ["REFLATEST01"])
    write_json(proj / P / "reference/meta/REFLATEST01.json", {"video_id": "REFLATEST01", "description": (
        "SYNTHETIC\n영상 출처: https://youtu.be/AAAAAAAAAAA\n"
        "https://www.tiktok.com/@bareurl_creator/video/7311111111111111111\n"
        "구독: https://www.youtube.com/@joshuamagazine")})
    T.trace("joshuamagazine", ["REFLATEST01"], do_ocr=False, lens=False)
    assert X.check_urls(["https://www.youtube.com/watch?v=AAAAAAAAAAA"])["excluded"] is True
    assert X.check_urls(["https://www.tiktok.com/@bareurl_creator/video/7311111111111111111"])["excluded"] is True
    rows = {r.get("url"): r for r in _rows(proj) if r["kind"] == "url"}
    assert rows["https://youtu.be/AAAAAAAAAAA"]["credit_line"] is True
    assert rows["https://www.tiktok.com/@bareurl_creator/video/7311111111111111111"]["credit_line"] is False
    assert "https://www.youtube.com/@joshuamagazine" not in rows


def test_high_view_and_whole_channel_videos_are_fenced_off(proj):
    """S5-02: the documented `ref trace` (default set latest100 ∪ high_views ∪ downloaded) traces the old
    high-view video; every channel upload in all_videos is a URL exclusion; the channel itself is an account row."""
    import argparse

    from shortkit.reference.cli import _ids, register
    _snap(proj, ["REFLATEST01"], hv=["REFOLDHV002"])
    write_json(proj / P / "reference/meta/REFOLDHV002.json", {"video_id": "REFOLDHV002", "description":
                                                               "출처: https://www.tiktok.com/@hvcreator/video/7300000000000000001"})
    ap = argparse.ArgumentParser()
    register(ap)
    ns = ap.parse_args(["trace", "--no-ocr", "--no-lens"])
    assert _ids(ns) == ["REFLATEST01", "REFOLDHV002"]
    T.trace("joshuamagazine", _ids(ns), do_ocr=False, lens=False)
    for u in ("https://www.youtube.com/watch?v=REFOLDHV002", "https://www.tiktok.com/@hvcreator/video/7300000000000000001",
              "https://www.youtube.com/shorts/OLDNOHV0001"):
        assert X.check_urls([u])["excluded"] is True, u
    acc = [r for r in _rows(proj) if r["kind"] == "account"]
    assert len(acc) == 1 and acc[0]["handle"] == "@joshuamagazine" and acc[0]["platform"] == "youtube"
    assert (proj / P / "analysis/REFOLDHV002/trace.json").is_file()


def test_script_channel_uses_reference_captions(proj):
    """S5-05: the reference's caption text (captions.json) is its script: keywords with times, and the script
    channel counts as covered; no transcript.json needed."""
    _snap(proj, ["REFLATEST01"])
    write_json(proj / P / "analysis/REFLATEST01/captions.json", {"video_id": "REFLATEST01", "resolution": [1080, 1920],
                                                                  "items": [
        {"start": 1.0, "end": 2.0, "role": "situation", "text": "고양이가 냉장고 문을 연다"},
        {"start": 3.0, "end": 4.0, "role": "reaction", "text": "고양이 천재"},
        {"start": 0.0, "end": 9.0, "role": "identity_mark", "text": "조슈아매거진"},
        {"start": 5.0, "end": 6.0, "role": "description", "text": "출처: 틱톡 @kr_cat_src"}]})
    T.trace("joshuamagazine", ["REFLATEST01"], do_ocr=False, lens=False)
    tj = json.loads((proj / P / "analysis/REFLATEST01/trace.json").read_text("utf-8"))
    assert tj["script_captions"]["status"] == "measured" and "냉장고" in tj["script_captions"]["keywords"]
    kw = {k["keyword"]: k for k in tj["keywords_found"] if k["kind"] == "caption_script"}
    assert "냉장고" in kw and kw["냉장고"]["t"] == 1.0 and "조슈아매거진" not in kw
    acc = {a["account"]: a for a in tj["accounts_found"]}
    assert acc["@kr_cat_src"]["kind"] == "on_screen_caption" and acc["@kr_cat_src"]["t"] == 5.0
    assert "script" in tj["sources_examined"]
    sa = json.loads((proj / "warehouse/source_accounts.json").read_text("utf-8"))
    assert sa["stage"]["channels"]["script"] == {"covered": 1, "target": 1, "missing": []}


def _credit_band_video(path):
    """SYNTHETIC 720x1280: moving test pattern in y 320..960, static credit text in the lower black band."""
    font = None
    for cand in ("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        if os.path.isfile(cand):
            font = cand
    if font is None:
        pytest.skip("no DejaVu font for the synthetic credit text")
    fc = (f"color=c=black:s=720x1280:r=10:d=6[bg];testsrc2=s=720x640:r=10:d=6[fg];[bg][fg]overlay=0:320[v];"
          f"[v]drawtext=fontfile={font}:text='@outside_credit':fontsize=44:fontcolor=white:x=160:y=1060")
    subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", "-filter_complex", fc,
                    "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(path)], check=True)


@pytest.mark.slow
def test_on_screen_credit_outside_footage_band_is_read(proj):
    """S5-06: handle OCR runs over the whole frame, so a credit printed in the black band is found."""
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")
    vid = "REFBAND0001"
    _snap(proj, [vid])
    vdir = proj / P / "reference/videos"
    vdir.mkdir(parents=True)
    _credit_band_video(vdir / f"{vid}.mp4")
    write_json(proj / P / f"analysis/{vid}/layout.json", {"video_id": vid, "resolution": [720, 1280],
                                                           "video_region": {"x": 0, "y": 320, "w": 720, "h": 640}})
    T.trace("joshuamagazine", [vid], do_ocr=True, lens=False, ocr_fps=1.0)
    tj = json.loads((proj / P / f"analysis/{vid}/trace.json").read_text("utf-8"))
    assert tj["watermark_ocr_area"] == "full_frame"
    # (tesseract may drop the underscore -- a known OCR limit recorded in the item note; compare normalised)
    assert any("outsidecredit" in T._norm(w["account"]) for w in tj["watermarks"]), tj["watermarks"]
    fp = [r for r in _rows(proj) if r["kind"] == "reference_footage"][0]
    assert fp["region"]["y"] == 320 and fp["region"]["h"] == 640          # fingerprint stays on the footage band


def test_stage_is_per_channel_and_not_measured_from_one_description(proj):
    """S5-07: one account in one description is NOT a measured reverse-trace stage."""
    _snap(proj, ["REFLATEST01"])
    write_json(proj / P / "reference/meta/REFLATEST01.json", {"video_id": "REFLATEST01",
                                                               "description": "출처: 틱톡 @someone_src"})
    T.trace("joshuamagazine", ["REFLATEST01"], do_ocr=False, lens=False)
    sa = json.loads((proj / "warehouse/source_accounts.json").read_text("utf-8"))
    assert sa["status"] == "measured"                       # the listed account IS a measured result ...
    st = sa["stage"]
    assert st["status"] == "unmeasured" and st["state"] == "open"   # ... but the stage is not done
    assert st["channels"]["description"] == {"covered": 1, "target": 1, "missing": []}
    for c in ("script", "on_screen", "lens", "fingerprint"):
        assert st["channels"][c]["covered"] == 0 and st["channels"][c]["missing"] == ["REFLATEST01"], c
    assert st["exclusion_fingerprints"] == 0 and "지문" in st["impact"]
    row = T.stage_status("joshuamagazine")
    assert row["status"] == "unmeasured" and row["state"] == "open" and "설명란 1/1" in row["evidence"]
    assert "지문 0/1" in row["evidence"]


def test_stage_blocked_snapshot_state(proj):
    write_json(proj / P / "reference/latest100.json", {"status": "blocked", "blocker": "SYNTHETIC 403",
                                                       "captured_at": "2026-09-24T00:00:00+00:00", "videos": []})
    T.trace("joshuamagazine", [], do_ocr=False, lens=False)
    row = T.stage_status("joshuamagazine")
    assert row["status"] == "unmeasured" and row["state"] == "blocked_network"


def test_transcribe_writes_transcript_only_with_an_engine(proj, monkeypatch):
    """S5-05: `ref transcribe` writes analysis/<id>/audio/transcript.json through an ASR engine (a SYNTHETIC
    test double here -- faster-whisper is optional); without one nothing is written (못 잼), and trace reads the
    transcript as part of the script channel."""
    import builtins

    from shortkit.reference import transcribe as TR
    vid = "REFLATEST01"
    _snap(proj, [vid])
    vdir = proj / P / "reference/videos"
    vdir.mkdir(parents=True)
    (vdir / f"{vid}.mp4").write_bytes(b"SYNTHETIC placeholder")
    real_import = builtins.__import__

    def no_fw(name, *a, **k):
        if name == "faster_whisper":
            raise ImportError("SYNTHETIC: not installed")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_fw)
    r = TR.transcribe_video("joshuamagazine", vid)
    assert r["status"] == "unmeasured" and "faster-whisper" in r["blocker"]
    assert not TR.transcript_path("joshuamagazine", vid).exists()
    monkeypatch.setattr(builtins, "__import__", real_import)

    def fake_engine(audio, model, language):          # SYNTHETIC ASR double
        assert audio.endswith(f"{vid}.mp4") and language == "ko"
        return [{"start": 1.25, "end": 2.0, "text": "강아지 탈출 성공"}, {"start": 3.0, "end": 3.5, "text": " "}]

    r = TR.transcribe_video("joshuamagazine", vid, engine=fake_engine, engine_label="SYNTHETIC")
    assert r["status"] == "measured" and r["segments"] == 1
    tj = json.loads(TR.transcript_path("joshuamagazine", vid).read_text("utf-8"))
    assert tj["status"] == "measured" and tj["segments"] == [{"start": 1.25, "end": 2.0, "text": "강아지 탈출 성공"}]
    assert "사람이 들어 확인한 것이 아님" in tj["note"]
    kw = T.transcript_keywords("joshuamagazine", vid)
    assert kw["status"] == "measured" and "강아지" in kw["keywords"] and kw["times"]["강아지"] == 1.25


def test_account_row_gains_channel_ids_learned_later(proj):
    """S5-02 (finish): a first trace without channel metadata (e.g. collect blocked) writes the account row with
    no channel id; once collect has written meta/<id>.json with the channel id, the next trace must add a row that
    carries it -- sourcing matches candidates by channel id too (a re-upload under another handle)."""
    _snap(proj, ["REFLATEST01"])
    T.trace("joshuamagazine", ["REFLATEST01"], do_ocr=False, lens=False)
    acc = [r for r in _rows(proj) if r["kind"] == "account"]
    assert len(acc) == 1 and "UCSYNTHETIC0000000000001" not in acc[0]["channel_ids"]     # only the preset hint
    write_json(proj / P / "reference/meta/REFLATEST01.json", {"video_id": "REFLATEST01", "channel_id": "UCSYNTHETIC0000000000001",
                                                               "description": "SYNTHETIC"})
    cand = {"platform": "youtube", "uploader": "someone else", "channel_id": "UCSYNTHETIC0000000000001"}
    assert X.check_account(cand) is None
    T.trace("joshuamagazine", ["REFLATEST01"], do_ocr=False, lens=False)
    acc = [r for r in _rows(proj) if r["kind"] == "account"]
    assert any("UCSYNTHETIC0000000000001" in (r.get("channel_ids") or []) for r in acc), acc
    assert X.check_account(cand)["excluded"] is True
    T.trace("joshuamagazine", ["REFLATEST01"], do_ocr=False, lens=False)     # nothing new -> no duplicate row
    assert len([r for r in _rows(proj) if r["kind"] == "account"]) == len(acc)
