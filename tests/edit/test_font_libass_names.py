"""Every candidate font (assets/fonts/manifest.yaml: fetched files + system faces) must render in libass
EXACTLY -- the face libass selects is read back from its own ``fontselect`` log.

libass 0.17.1 (ass_fontselect.c) matches a PostScript name only for CFF outlines and a Windows full name
only for TrueType outlines, so TrueType faces such as Black Han Sans fell back to DejaVu/WenQuanYi when the
style carried their PostScript name ("BlackHanSans-Regular").  It also reads the style Bold field as a
boolean and emboldens synthetically when 700 > face weight + 150.  Faces that are not on this machine are
skipped (never replaced by another face)."""
from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
_MAN = yaml.safe_load((REPO / "assets/fonts/manifest.yaml").read_text(encoding="utf-8"))
CANDIDATES = [e["name"] for e in _MAN.get("fonts", []) if e.get("status") == "acquirable"] + \
             [e["name"] for e in _MAN.get("system", [])]


@pytest.fixture(autouse=True)
def _repo_root(monkeypatch):
    monkeypatch.setenv("SHORTKIT_ROOT", str(REPO))


def _face(name: str):
    from shortkit.edit.captions import FontError, resolve_font

    try:
        return resolve_font(name).face
    except FontError:
        pytest.skip(f"'{name}' is not on this machine (no substitute is used)")


def _one_style_ass(fontname: str, weight: int, text: str = "가나다 ABC 123 !?") -> str:
    from shortkit.edit.captions import AssDoc, AssEvent, style_line

    doc = AssDoc(640, 360)
    doc.styles.append(style_line("s", fontname, 40, "#FFFFFF", "#000000", "#000000", weight, 2, 0))
    doc.events.append(AssEvent(0, 0.0, 1.0, "s", "{\\an5\\pos(320,180)}" + text))
    return doc.render()


def _fonts_dir(tmp_path, *faces) -> Path:
    d = tmp_path / "fonts"
    d.mkdir(exist_ok=True)
    for f in faces:
        link = d / os.path.basename(f.path)
        if not link.exists():
            link.symlink_to(Path(f.path).resolve())
    return d


@pytest.mark.parametrize("name", CANDIDATES)
def test_manifest_face_renders_exactly_in_libass(name, tmp_path):
    from shortkit.edit.captions import verify_libass_fonts

    face = _face(name)
    # GDI rule: PostScript name for CFF outlines, Windows full name for TrueType outlines
    if face.cff:
        assert face.ass_name == face.postscript
    else:
        assert face.win_fullnames and face.ass_name == face.win_fullnames[0]
    fd = _fonts_dir(tmp_path, face)
    res = verify_libass_fonts(_one_style_ass(face.ass_name, face.weight), fd, {"s": face})
    st = res["styles"]["s"]
    assert res["ok"], st
    assert st["selected"] and set(st["selected"]) == {face.postscript}, st
    assert st["fallback_glyphs"] == [] and st["synthetic_bold"] is False and st["wrong_file"] is False
    # the style's own name, resolved inside the fonts dir, identifies the same face (render.check_output_fonts
    # without caption_layout.json and qa/font_id.py pass the name)
    by_name = verify_libass_fonts(_one_style_ass(face.ass_name, face.weight), fd, {"s": face.ass_name})
    assert by_name["ok"] and by_name["styles"]["s"]["expected_postscript"] == face.postscript


def test_probe_over_all_present_candidates_chooses_the_rule_name():
    """All present candidate faces in ONE fonts directory (as build/fonts would hold them) + the system
    fonts: libass must reach each face under its rule name, and the probe must pick exactly that name."""
    from shortkit.edit.captions import FontError, probe_ass_names, resolve_font

    faces = []
    for n in CANDIDATES:
        try:
            faces.append(resolve_font(n).face)
        except FontError:
            continue
    if len(faces) < 2:
        pytest.skip("fewer than two candidate fonts on this machine")
    res = probe_ass_names(faces)
    for f in faces:
        r = res[(str(f.path), f.index)]
        assert r["name"] == f.ass_name, (f.family, f.style, r["tried"])


def test_postscript_name_of_a_truetype_face_is_refused(tmp_path):
    """The failure the mockloop run hit: a TrueType face named by its PostScript name falls back."""
    from shortkit.edit.captions import verify_libass_fonts

    face = _face("Black Han Sans")
    assert not face.cff and face.postscript == "BlackHanSans-Regular"
    fd = _fonts_dir(tmp_path, face)
    res = verify_libass_fonts(_one_style_ass(face.postscript, face.weight), fd, {"s": face})
    st = res["styles"]["s"]
    assert res["ok"] is False and face.postscript not in st["selected"] and st["fallback_glyphs"], st


def test_shared_family_name_selecting_another_weight_is_rejected_by_the_probe():
    """'Gothic A1' is the Windows family of both the Black and the ExtraBold face; libass then picks by
    weight (ExtraBold for a Bold=-1 request), so the probe must not accept it for the Black face."""
    from shortkit.edit.captions import probe_ass_names

    black, xb = _face("Gothic A1 Black"), _face("Gothic A1 ExtraBold")
    res = probe_ass_names([black, xb])
    tried = {t["name"]: t for t in res[(str(black.path), black.index)]["tried"]}
    assert "Gothic A1" in tried and tried["Gothic A1"]["ok"] is False
    assert tried["Gothic A1"]["selected"] == [xb.postscript]
    assert res[(str(black.path), black.index)]["name"] == "Gothic A1 Black"


def test_bold_flag_never_asks_libass_for_synthetic_bold(tmp_path):
    from shortkit.edit.captions import ass_bold_flag, style_line, verify_libass_fonts

    assert [ass_bold_flag(w) for w in (100, 400, 500, 549, 550, 600, 700, 900)] == [0, 0, 0, 0, -1, -1, -1, -1]
    assert ",0,0,0,0,100,100," in style_line("s", "X", 40, "#FFFFFF", "#000000", "#000000", 400, 0, 0)
    assert ",-1,0,0,0,100,100," in style_line("s", "X", 40, "#FFFFFF", "#000000", "#000000", 900, 0, 0)
    face = _face("Black Han Sans")                         # usWeightClass 400
    fd = _fonts_dir(tmp_path, face)
    good = verify_libass_fonts(_one_style_ass(face.ass_name, face.weight), fd, {"s": face})
    assert good["ok"] and good["styles"]["s"]["requested_weight"] == 400
    # the old style line wrote the numeric weight; any non-zero Bold means 700 to libass -> faux bold
    forced = _one_style_ass(face.ass_name, 900)
    bad = verify_libass_fonts(forced, fd, {"s": face})
    st = bad["styles"]["s"]
    assert bad["ok"] is False and st["requested_weight"] == 700 and st["synthetic_bold"] is True, st


def test_font_check_covers_the_characters_the_captions_use(tmp_path):
    """A glyph the face lacks (here U+1F600) makes libass select another font for it: the check renders
    each style with its own events' characters, so this is caught even though the default sample passes."""
    from shortkit.edit.captions import event_chars, verify_libass_fonts

    face = _face("Pretendard Black")
    fd = _fonts_dir(tmp_path, face)
    ass = _one_style_ass(face.ass_name, face.weight, text="웃음 \U0001F600")
    assert set(event_chars(ass)["s"]) == set("웃음\U0001F600")
    res = verify_libass_fonts(ass, fd, {"s": face})
    assert res["ok"] is False and "U+1F600" in res["styles"]["s"]["fallback_glyphs"], res["styles"]["s"]
    ok = verify_libass_fonts(_one_style_ass(face.ass_name, face.weight, text="{\\1c&HFFFFFF&}웃음{\\p1}m 0 0 l 9 9{\\p0}"),
                             fd, {"s": face})
    assert ok["ok"] and ok["styles"]["s"]["sample"] == "".join(sorted("웃음")), ok["styles"]["s"]
