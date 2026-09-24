"""shortkit.fonts: manifest, exact lookup (no fallback), .ttc face index, fetch/verify."""
from __future__ import annotations

import re
import shutil
import urllib.error

import pytest

from shortkit import fonts


def test_manifest_entries_well_formed():
    m = fonts.load_manifest()
    acq = [e for e in m["fonts"] if e.get("status") == "acquirable"]
    assert len(acq) >= 11
    for e in acq:
        assert e["url"].startswith("https://raw.githubusercontent.com/"), e
        assert re.fullmatch(r"[0-9a-f]{64}", e["sha256"]), e
        assert e["license"] == "OFL-1.1"
        assert e["file"].startswith("assets/fonts/") and not e["file"].startswith("/")
    nacq = [e for e in m["fonts"] if e.get("status") == "not_acquired"]
    assert {"Gmarket Sans Bold", "여기어때 잘난체", "Cafe24 Ssurround"} <= {e["name"] for e in nacq}
    for e in nacq:  # never invented
        assert e.get("url") is None and e.get("sha256") is None and e.get("file") is None
    assert all("name" in e for e in m["system"])


def test_find_font_exact_manifest(fonts_ready):
    for e in fonts.manifest_entries("acquirable"):
        face = fonts.resolve_font(e["name"])
        assert face is not None, e["name"]
        assert face.source == "manifest"
        assert face.matches(e["name"])
        assert fonts.find_font(e["name"]) == face.path
        assert face.sha256 == e["sha256"]


def test_find_font_rejects_fallbacks(fonts_ready):
    # 'Pretendard' alone: only Black/ExtraBold/Bold faces exist -> no Regular face -> None
    for name in ["Arial", "Pretendard", "Pretendard Medium", "Noto Sans CJK KR Heavy", "Gmarket Sans Bold",
                 "Gothic A1", "", "   "]:
        assert fonts.find_font(name) is None, name
    info = fonts.explain_font("Arial")
    assert info["found"] is False
    if "fc_match_would_substitute" in info:
        assert info["substitute_accepted"] is False


def test_case_and_blank_insensitive_like_fontconfig(fonts_ready):
    a = fonts.resolve_font("Pretendard Black")
    b = fonts.resolve_font("pretendardblack")
    assert a is not None and b is not None and a.path == b.path


def test_ttc_face_index():
    face = fonts.resolve_font("Noto Sans CJK KR Black")
    if face is None:
        pytest.skip("system font Noto Sans CJK KR Black not installed")
    idx = fonts.font_face_index(face.path, "Noto Sans CJK KR Black")
    assert idx == face.index
    from PIL import ImageFont

    fam, sty = ImageFont.truetype(str(face.path), 20, index=idx).getname()
    assert (fam, sty) == ("Noto Sans CJK KR", "Black")
    if face.path.suffix.lower() == ".ttc":
        # another face of the same collection must NOT answer to the KR name
        assert fonts.font_face_index(face.path, "Noto Sans CJK KR Bold") is None
        assert face.to_dict()["path"].startswith("<system>/")   # machine path never stored


def test_sha256_mismatch_is_never_used(tmp_root):
    dst = tmp_root / "assets" / "fonts" / "Pretendard-Black.otf"
    dst.unlink()
    # a *different* valid font file under the pinned name
    shutil.copy(tmp_root / "assets" / "fonts" / "Pretendard-Bold.otf", dst)
    fonts.clear_caches()
    assert fonts.find_font("Pretendard Black") is None
    ok = fonts.resolve_font("Pretendard Bold")
    assert ok is not None and ok.path.name == "Pretendard-Bold.otf"
    rows = {r["name"]: r for r in fonts.verify_all()["fonts"]}
    assert rows["Pretendard Black"]["state"] == "sha256_mismatch"


def test_ambiguous_name_is_refused(monkeypatch, tmp_path):
    a = fonts.FontFace(path=tmp_path / "a.ttf", index=0, family="X", style="Bold", names=["X Bold"], postscript="X-Bold")
    b = fonts.FontFace(path=tmp_path / "b.ttf", index=0, family="X", style="Bold", names=["X Bold"],
                       postscript="Xalt-Bold")
    monkeypatch.setattr(fonts, "_tiers", lambda extra: iter([("manifest", []), ("dir", [a, b]), ("system", [])]))
    assert fonts.resolve_font("X Bold") is None
    monkeypatch.setattr(fonts, "_tiers", lambda extra: iter([("manifest", [a]), ("dir", [b]), ("system", [])]))
    assert fonts.resolve_font("X Bold").path == a.path   # earlier tier wins, not ambiguous


def test_fetch_all_local_copy_and_reported_network_failure(tmp_root, tmp_path, monkeypatch):
    local = tmp_path / "cache"
    local.mkdir()
    shutil.copy(tmp_root / "assets" / "fonts" / "Jua-Regular.ttf", local / "Jua-Regular.ttf")
    for n in ("Jua-Regular.ttf", "Gugi-Regular.ttf"):
        (tmp_root / "assets" / "fonts" / n).unlink()
    (local / "Gugi-Regular.ttf").write_bytes(b"not a font")     # wrong content under the right name

    def blocked(*a, **k):  # SYNTHETIC: simulates a blocked network
        raise urllib.error.URLError("blocked (synthetic test)")

    monkeypatch.setattr(fonts.urllib.request, "urlopen", blocked)
    r = fonts.fetch_all(local_dir=local, names=["Jua", "Gugi"])
    assert r["results"]["Jua"]["status"] == "ok_copied"
    assert r["results"]["Gugi"]["status"] == "failed"
    assert "blocked" in r["results"]["Gugi"]["detail"]
    assert r["ok"] is False
    assert not (tmp_root / "assets" / "fonts" / "Gugi-Regular.ttf").exists()
    assert fonts.find_font("Gugi") is None
    assert fonts.find_font("Jua") is not None
