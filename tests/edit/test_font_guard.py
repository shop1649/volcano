"""libass font guard: styles must name faces by PostScript name.  libass (fontconfig provider) does not
resolve a full name such as 'Noto Sans CJK KR Bold' -- it silently falls back to another face -- so the
guard (captions.verify_libass_fonts / render.check_output_fonts) must reject it and accept the
PostScript name of the same face."""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest

FULLNAME = "Noto Sans CJK KR Bold"


def _face():
    from shortkit.edit.captions import FontError, resolve_font

    try:
        return resolve_font(FULLNAME).face
    except FontError:
        pytest.skip(f"{FULLNAME} not installed")


def _ass(fontname: str) -> str:
    from shortkit.edit.captions import AssDoc, style_line

    doc = AssDoc(640, 360)
    doc.styles.append(style_line("speaker", fontname, 40, "#FFFFFF", "#000000", "#000000", 700, 2, 0))
    return doc.render()


def _fonts_dir(tmp_path, face) -> str:
    d = tmp_path / "fonts"
    d.mkdir(exist_ok=True)
    link = d / os.path.basename(face.path)
    if not link.exists():
        link.symlink_to(face.path)
    return str(d)


def test_fullname_rejected_postscript_accepted(tmp_path):
    from shortkit.edit.captions import verify_libass_fonts

    face = _face()
    assert face.postscript and face.postscript != FULLNAME and face.ass_name == face.postscript
    fd = _fonts_dir(tmp_path, face)
    bad = verify_libass_fonts(_ass(FULLNAME), fd, {"speaker": face.postscript})
    assert bad["ok"] is False
    st = bad["styles"]["speaker"]
    assert st["requested"] == FULLNAME and face.postscript not in st["selected"], st
    good = verify_libass_fonts(_ass(face.postscript), fd, {"speaker": face.postscript})
    assert good["ok"] is True, good
    assert good["styles"]["speaker"]["selected"] and set(good["styles"]["speaker"]["selected"]) == {face.postscript}
    assert good["styles"]["speaker"]["fallback_glyphs"] == []


def test_render_check_output_fonts_uses_the_ass_style_names(tmp_path, monkeypatch):
    """render.check_output_fonts expects libass to select exactly the name written in each style."""
    from shortkit.edit import render

    face = _face()
    root = tmp_path / "proj"
    (root / "b").mkdir(parents=True)
    (root / "shortkit.root").write_text("")
    monkeypatch.setenv("SHORTKIT_ROOT", str(root))
    fd = _fonts_dir(root / "b", face)
    assert fd.endswith("b/fonts")
    for name, ok in ((FULLNAME, False), (face.postscript, True)):
        (root / "b/captions.ass").write_text(_ass(name), encoding="utf-8")
        r = SimpleNamespace(ass_path="b/captions.ass", fonts_dir="b/fonts")
        res = render.check_output_fonts(r)
        assert res["ok"] is ok, (name, res)
