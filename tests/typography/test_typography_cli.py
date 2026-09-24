"""`ref font-ceiling` / `ref fonts` / `ref font-candidates` end to end in a temporary project root.

The "reference video" used here is SYNTHETIC (captions rendered by this test with an OFL font,
scaled and H.264-encoded); it only exercises the pipeline, it is not reference data.
"""
from __future__ import annotations

import argparse
import json
import math

import numpy as np
import pytest

from shortkit.reference import typography as T
from shortkit.util.jsonio import read_json, write_json
from shortkit.util.media import run, FFMPEG


def _parser():
    ap = argparse.ArgumentParser()
    T.register(ap.add_subparsers(dest="cmd", required=True))
    return ap


def _no_abs_paths(obj, root):
    txt = json.dumps(obj, ensure_ascii=False)
    assert str(root) not in txt
    assert "/home/" not in txt and "/usr/share" not in txt and "/tmp/" not in txt


def test_fonts_cli_without_crops_is_unmeasured(tmp_root, capsys):
    a = _parser().parse_args(["fonts", "--preset", "joshuamagazine"])
    assert a.func(a) == 0
    out = capsys.readouterr().out
    assert "못 잼" in out
    rep = read_json(tmp_root / "presets" / "joshuamagazine" / "fonts_report.json")
    ident = rep["identification"]
    assert ident["status"] == "unmeasured" and ident["label_ko"] == "못 잼" and ident["blocker"]
    assert ident["roles"]["title"]["current_preset_font"] == "Noto Sans CJK KR Black"
    assert ident["roles"]["title"]["status"] == "unmeasured"
    assert rep["status"].startswith("unmeasured")
    assert not (tmp_root / "presets" / "joshuamagazine" / "measurements" / "font_identity.json").exists()
    _no_abs_paths(rep, tmp_root)


def test_font_candidates_cli_lists(tmp_root, capsys):
    a = _parser().parse_args(["font-candidates"])
    assert a.func(a) == 0
    out = capsys.readouterr().out
    assert "Pretendard Black" in out and "확보 못 함" in out


@pytest.mark.slow
def test_font_ceiling_cli_writes_assumed_report(tmp_root, capsys):
    a = _parser().parse_args(["font-ceiling", "--preset", "joshuamagazine", "--fonts",
                              "Pretendard Bold,Pretendard ExtraBold", "--crf", "30", "--sizes", "40,72",
                              "--n-strings", "1", "--repeats", "2", "--nearest", "1", "--background", "black"])
    assert a.func(a) == 0
    rep = read_json(tmp_root / "presets" / "joshuamagazine" / "fonts_report.json")
    assert rep["status"] == T.STATUS_CEILING_ONLY
    assert rep["conditions_assumed"] is True
    lab = "h264_crf30_1080x1920"
    assert set(rep["ceilings"][lab]) == {"Pretendard Bold", "Pretendard ExtraBold"}
    for c in rep["ceilings"][lab].values():
        assert c["n"] == 4 and c["p10"] is not None and c["noise"]["n"] == 2
    pairs = rep["discriminability"][lab]
    assert {(p["font"], p["other"]) for p in pairs} == {("Pretendard Bold", "Pretendard ExtraBold"),
                                                        ("Pretendard ExtraBold", "Pretendard Bold")}
    asm = {x["input"]: x for x in rep["assumptions"]}
    assert asm["ref_resolution"]["status"] == "assumed" and asm["rate_control"]["status"] == "assumed"
    assert asm["caption_sizes_px"]["resolution"] == [1080, 1920]
    assert rep["identification"]["status"] == "unmeasured"
    assert "--crf 30" in rep["command"]
    _no_abs_paths(rep, tmp_root)


def _synthetic_reference(root, font="Gothic A1 Black", video_id="synthvid01"):
    """SYNTHETIC reference: two title captions rendered at 1080x1920, scaled to 720x1280, H.264 1500 kbps."""
    fr = T.font_ref(font)
    W, H, fps = 1080, 1920, 10
    texts = [("결국 참지 못한 남자", 0.0, 0.6), ("역대급 반전 등장", 0.6, 1.2)]
    frames, items = [], []
    size, opx = 72.0, 5.4
    for text, t0, t1 in texts:
        f = T.load_font(fr.abspath, size, fr.index)
        x0, y0, x1, y1 = f.getbbox(text, anchor="ls", stroke_width=opx)
        xy = ((W - (x1 - x0)) / 2 - x0 + 0.3, 330 - (y0 + y1) / 2 + 0.6)
        base = np.zeros((H, W, 3), np.uint8)
        base[:, :] = (35, 45, 60)
        base[656:1264] = (120, 110, 90)
        img, box = T.draw_caption(base, text, fr.abspath, size, xy, (255, 255, 255), (0, 0, 0), opx, fr.index)
        n = int(round((t1 - t0) * fps))
        frames += [img] * n
        sc = 720 / 1080
        bb = [round(box[0] * sc, 1), round(box[1] * sc, 1), round((box[2] - box[0]) * sc, 1),
              round((box[3] - box[1]) * sc, 1)]
        # field names follow shortkit.reference.textboxes (captions.json); values are synthetic truth
        items.append({"id": f"c{len(items)}", "start": t0, "end": t1, "t_rep": round((t0 + t1) / 2, 3),
                      "role": "title", "text": text, "bbox": bb, "motion_in": "none", "ocr_conf": 91.0,
                      "lines": [{"text": text, "bbox": bb, "chars": len(text.replace(" ", "")), "ocr_conf": 91.0}],
                      "style": {"color": "#FFFFFF", "outline_color": "#000000", "outline_visibility": "visible",
                                "outline_px": round(opx * sc, 2), "bg_color": "#232D3C",
                                "ink_h": round((y1 - y0 - 2 * opx) * sc, 1)}})
    vdir = root / "presets" / "joshuamagazine" / "reference" / "videos"
    vdir.mkdir(parents=True)
    out = vdir / f"{video_id}.mp4"
    raw = b"".join(f.tobytes() for f in frames)
    run([FFMPEG, "-hide_banner", "-nostdin", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(fps), "-i", "-", "-vf", "scale=720:1280:flags=bicubic",
         "-c:v", "libx264", "-preset", "veryfast", "-b:v", "1500k", "-pix_fmt", "yuv420p", str(out)], input_bytes=raw)
    adir = root / "presets" / "joshuamagazine" / "analysis" / video_id
    write_json(adir / "captions.json", {"video_id": video_id, "resolution": [720, 1280], "items": items,
                                        "note": "SYNTHETIC test fixture"})
    (root / "presets" / "joshuamagazine" / "formats.yaml").write_text(
        "schema: shortkit.formats/1\npreset_id: joshuamagazine-v1\nassignments: {%s: F1}\ntable: []\n" % video_id,
        encoding="utf-8")
    (root / "presets" / "joshuamagazine" / "reference" / "downloads.jsonl").write_text(
        json.dumps({"video_id": video_id, "path": f"presets/joshuamagazine/reference/videos/{video_id}.mp4",
                    "format": "synthetic"}) + "\n", encoding="utf-8")
    return out


@pytest.mark.slow
def test_ref_fonts_end_to_end_on_synthetic_reference(tmp_root, capsys):
    _synthetic_reference(tmp_root)
    a = _parser().parse_args(["fonts", "--preset", "joshuamagazine", "--roles", "title,situation", "--candidates",
                              "Gothic A1 Black,Noto Sans CJK KR Black,Pretendard Black,Black Han Sans"])
    assert a.func(a) == 0
    rep = read_json(tmp_root / "presets" / "joshuamagazine" / "fonts_report.json")
    ident = rep["identification"]
    assert ident["conditions"]["assumed"] is False
    assert ident["conditions"]["ref_resolution"] == [720, 1280] and ident["conditions"]["bitrate_kbps"] > 0
    title = ident["roles"]["title"]
    assert title["n_crops"] == 2 and title["color_mode"] == "given"
    # quantisation measured from the reference itself (not the average bitrate) drives the ceiling
    assert title["caption_qp"]["median"] > 0 and title["ceiling_conditions"]["qp"] is not None
    assert title["ceiling_conditions"]["label"].startswith("h264_qp") and title["ceiling_conditions"]["assumed"] is False
    assert title["ceiling_conditions"]["background"] == "color:#232D3C"
    assert title["by_format"]["F1"]["value"] == "Gothic A1 Black" and title["by_format"]["F1"]["n"] == 2
    assert title["candidate_ranking"][0]["font"] == "Gothic A1 Black"
    assert title["verdict"] == "identical", title["candidate_ranking"][0]["reasons"]
    assert title["status"] == "measured"
    assert ident["roles"]["situation"]["status"] == "unmeasured"      # no crops for that role
    assert ident["status"] == "partial" and rep["status"].startswith("partial")
    meas = read_json(tmp_root / "presets" / "joshuamagazine" / "measurements" / "font_identity.json")
    items = {i["key"]: i for i in meas["items"]}
    assert items["text.roles.title.font_name"]["status"] == "measured"
    assert items["text.roles.title.font_name"]["value"] == "Gothic A1 Black"
    assert items["text.roles.title.font_name"]["resolution"] == [720, 1280]
    assert items["text.roles.title.font_name"]["by_format"]["F1"]["value"] == "Gothic A1 Black"
    assert items["text.roles.title.font_name"]["overall"]["n"] == 2
    assert "text.roles.situation.font_name" not in items   # nothing measured -> nothing written for it
    for c in title["crops"]:
        assert c["resolution"] == [720, 1280] and len(c["bbox"]) == 4
    _no_abs_paths(rep, tmp_root)
    _no_abs_paths(meas, tmp_root)
