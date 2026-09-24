"""ASS content, layout conventions and font resolution (no fallback)."""
from __future__ import annotations

import re

import pytest

from conftest import load_preset, set_preset, write_plan


def build_ass(root, plan):
    from shortkit.edit.resolve import resolve_episode

    write_plan(root, plan)
    r = resolve_episode("t1")
    return r, (root / r.ass_path).read_text(encoding="utf-8")


def test_script_header_uses_canvas(root, plan):
    r, ass = build_ass(root, plan)
    pr = load_preset()
    assert f"PlayResX: {pr.get('canvas.width')}" in ass and f"PlayResY: {pr.get('canvas.height')}" in ass
    assert "ScaledBorderAndShadow: yes" in ass and "WrapStyle: 2" in ass


def test_one_event_per_line_with_exact_pitch(root, plan):
    plan["captions"][1]["text"] = "첫째 줄\n둘째 줄"
    r, ass = build_ass(root, plan)
    pos = [tuple(map(float, m)) for m in re.findall(r"\\an5(?:\\move\([^)]*,([\d.]+),([\d.]+),0,\d+\)|\\pos\(([\d.]+),([\d.]+)\))", ass)
           for m in [tuple(x for x in m if x)]]
    lines = [ln for ln in ass.splitlines() if ln.startswith("Dialogue:") and ",situation," in ln and "\\p3" not in ln]
    assert len(lines) == 2
    ys = []
    for ln in lines:
        m = re.search(r"\\move\(([\d.]+),([\d.]+),([\d.]+),([\d.]+),0,\d+\)", ln) or re.search(r"\\pos\(([\d.]+),([\d.]+)\)", ln)
        g = [float(x) for x in m.groups()]
        ys.append(g[3] if len(g) == 4 else g[1])
    pr = load_preset()
    pitch = pr.get("text.roles.situation.size_px") * pr.get("text.roles.situation.line_spacing")
    assert ys[1] - ys[0] == pytest.approx(pitch, abs=0.011)
    assert pos  # regex sanity


def test_style_fontsize_from_win_metrics(root, plan):
    from shortkit.edit.captions import resolve_font

    r, ass = build_ass(root, plan)
    pr = load_preset()
    f = resolve_font(pr.get("text.roles.situation.font_name"))
    exp = pr.get("text.roles.situation.size_px") * (f.face.win_ascent + f.face.win_descent) / f.face.units_per_em
    m = re.search(r"^Style: situation,([^,]+),([\d.]+),", ass, re.M)
    assert m.group(1) == pr.get("text.roles.situation.font_name")
    assert float(m.group(2)) == pytest.approx(exp, abs=0.01)


def test_motion_tags(root, plan):
    set_preset(root, "text.roles.situation.motion_in", {"type": "pop", "dur_s": 0.2, "scale_from": 0.5, "offset_px": 0})
    set_preset(root, "text.roles.situation.motion_out", {"type": "fade", "dur_s": 0.3})
    r, ass = build_ass(root, plan)
    ln = next(l for l in ass.splitlines() if ",situation," in l and "\\p3" not in l)
    assert "\\fscx50\\fscy50\\t(0,200,\\fscx100\\fscy100)" in ln and "\\fad(0,300)" in ln
    set_preset(root, "text.roles.situation.motion_in", {"type": "slide_up", "dur_s": 0.25, "scale_from": 1.0, "offset_px": 40})
    r, ass = build_ass(root, plan)
    ln = next(l for l in ass.splitlines() if ",situation," in l and "\\p3" not in l)
    m = re.search(r"\\move\(([\d.]+),([\d.]+),([\d.]+),([\d.]+),0,250\)", ln)
    assert m and float(m.group(2)) - float(m.group(4)) == pytest.approx(40)


def test_box_drawing_padding_and_alpha(root, plan):
    set_preset(root, "text.roles.situation.box", {"enabled": True, "color": "#102030", "alpha": 0.5, "pad_x": 20, "pad_y": 10})
    r, ass = build_ass(root, plan)
    cap = next(c for c in r.captions if c.id == "c_s")
    x, y, w, h = cap.box["rect"]
    assert x == pytest.approx(cap.bbox.x - 20) and h == pytest.approx(cap.bbox.h + 20)
    ln = next(l for l in ass.splitlines() if ",situation," in l and "\\p3" in l)
    assert ln.startswith("Dialogue: 1,") and "\\1c&H302010&" in ln and "\\1a&H80&" in ln
    m = re.search(r"m 0 0 l (\d+) 0 \d+ (\d+) 0 \d+", ln)
    assert int(m.group(1)) / 4 == pytest.approx(w, abs=0.25) and int(m.group(2)) / 4 == pytest.approx(h, abs=0.25)


def test_highlight_spans(root, plan):
    plan["captions"][1]["highlight"] = ["움직"]
    r, ass = build_ass(root, plan)
    hl = load_preset().get("text.roles.situation.highlight_color").lstrip("#")
    bgr = (hl[4:6] + hl[2:4] + hl[0:2]).upper()
    assert f"{{\\1c&H{bgr}&}}움직{{\\1c&H" in ass


def test_decoration_move_and_blink(root, plan):
    plan["decorations"] = [{"id": "d1", "kind": "arrow", "start": 1.0, "end": 3.0, "blink_hz": 2.0,
                            "keyframes": [{"t": 0.0, "x": 300, "y": 900}, {"t": 1.0, "x": 400, "y": 950}]}]
    r, ass = build_ass(root, plan)
    evs = [l for l in ass.splitlines() if ",deco," in l]
    assert len(evs) == 2                                   # one event per keyframe interval (+ hold)
    assert "\\move(" in evs[0] and "\\p3" in evs[0]
    m = re.search(r"\\move\(([\d.]+),([\d.]+),([\d.]+),([\d.]+),0,1000\)", evs[0])
    assert float(m.group(3)) - float(m.group(1)) == pytest.approx(100) and float(m.group(4)) - float(m.group(2)) == pytest.approx(50)
    toggles = re.findall(r"\\t\((\d+),(\d+),\\alpha&H(..)&\)", evs[0])
    assert [(int(b), a) for _, b, a in toggles] == [(250, "FF"), (500, "00"), (750, "FF")]
    pr = load_preset()
    col = pr.get("decorations.arrow.color").lstrip("#")
    assert f"\\1c&H{(col[4:6] + col[2:4] + col[0:2]).upper()}&" in evs[0]


def test_circle_box_rings_have_holes(root):
    from shortkit.edit.captions import deco_shape

    polys, _ = deco_shape("circle", {"x": 100, "y": 100, "w": 80, "h": 60}, {"stroke_px": 8})
    assert len(polys) == 2

    def area(p):
        return sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1) in zip(p, p[1:] + p[:1])) / 2

    assert area(polys[0]) * area(polys[1]) < 0              # opposite winding -> hole


def test_font_resolution_refuses_fallback(root):
    from shortkit.edit.captions import FontError, resolve_font

    with pytest.raises(FontError):
        resolve_font("Definitely Not Installed Font 123")
    f = resolve_font(load_preset().get("text.roles.description.font_name"))
    names = [n.casefold().replace(" ", "") for n in f.face.names]
    assert load_preset().get("text.roles.description.font_name").casefold().replace(" ", "") in names


def test_break_lines_by_metrics():
    from shortkit.edit.captions import break_lines, resolve_font, _pil_font

    f = resolve_font("Noto Sans CJK KR Black")
    font = _pil_font(f.face.path, f.face.index, 66.0)
    lines = break_lines("창가 남성이 일어선다 그리고 다시 앉는다", font, 14, 960)
    assert len(lines) == 2 and all(len(l.replace(" ", "")) <= 14 for l in lines)
    lines = break_lines("가나다라마바사아자차카타파하", font, 5, 5000)     # no spaces: char split
    assert [len(l) for l in lines] == [5, 5, 4]
    assert break_lines("가\n나", font, 14, 960) == ["가", "나"]


def test_font_fallback_without_fonts_module_verifies_names(root, monkeypatch):
    """When shortkit.fonts is unavailable, fc-match is accepted only if the face carries the exact
    name (fc-match substitutes silently), otherwise an exact fc-list search is used."""
    import builtins

    from shortkit.edit import captions as c

    real = builtins.__import__

    def fake(name, globals=None, locals=None, fromlist=(), level=0):
        if (level and fromlist and "fonts" in fromlist) or name == "shortkit.fonts":
            raise ImportError("hidden for test")
        return real(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake)
    c.clear_font_cache()
    f = c.resolve_font("Noto Sans CJK KR Bold")
    assert f.how in ("fc-match(verified)", "fc-list(exact)") and f.face.weight == 700
    with pytest.raises(c.FontError):
        c.resolve_font("Nope Font Family 42")
    c.clear_font_cache()
