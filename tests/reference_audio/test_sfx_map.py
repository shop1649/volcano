"""sfx_map: catalog types vs a SYNTHETIC SFX library made from the generated sfx with gain/EQ variants."""
from __future__ import annotations

import shutil

import numpy as np
import pytest
import yaml

import synthref as S
from .conftest import PRESET, no_abs_paths
from shortkit.reference import sfx_catalog as C, sfx_map as M

REPO = S.REPO


def _shelf(x, fc, g_hi):
    from scipy.signal import butter, sosfilt

    lo = sosfilt(butter(2, fc, "low", fs=S.SR, output="sos"), x)
    return (lo + g_hi * (x - lo)).astype(np.float32)


@pytest.mark.slow
def test_map_have_and_none(project_env):
    root = project_env["root"]
    bank = project_env["bank"]
    C.build_catalog(PRESET, video_ids=["synv1", "synv2", "synv3", "synv4"])
    lib = root / "assets" / "library" / "sfx"
    shutil.rmtree(lib, ignore_errors=True)
    (lib / "sub").mkdir(parents=True)
    sil = np.zeros(int(0.3 * S.SR), np.float32)
    S._write(lib / "whoosh_loud_late.wav", np.concatenate([sil, bank["whoosh"] * 1.8]))   # gain + leading silence
    S._write(lib / "ding_darker.wav", _shelf(bank["ding"], 1500, 0.5))                     # EQ (-6 dB highs)
    S._write(lib / "sub" / "pop_quiet_bright.wav", _shelf(bank["pop"], 800, 2.0) * 0.3)   # EQ + gain
    for other in ("riser", "click", "boing"):
        S._write(lib / f"{other}.wav", bank[other])
    (lib / "notes.txt").write_text("not audio")
    try:
        m = M.build_map(PRESET)
        assert m["library_status"] == "scanned" and m["library_files"] == 6
        cat = C.build_catalog(PRESET, video_ids=["synv1", "synv2", "synv3", "synv4"], write=False)
        from .test_catalog import _members

        name_of = {}
        for t in cat["types"]:
            if t["class"] == "edit_sfx":
                names = {n for _, _, n in _members(project_env, t["type_id"])}
                name_of[t["type_id"]] = names.pop()
        expect = {"whoosh": "assets/library/sfx/whoosh_loud_late.wav", "ding": "assets/library/sfx/ding_darker.wav",
                  "pop": "assets/library/sfx/sub/pop_quiet_bright.wav"}
        for tid, v in m["types"].items():
            nm = name_of[tid]
            if nm in expect:
                assert v["status"] == "have", (nm, v)
                assert v["file"] == expect[nm] and v["similarity"] >= M.MATCH_THRESHOLD
            else:                                                       # boom is not in the library
                assert nm == "boom"
                assert v["status"] == "none" and v["file"] is None and v["needed_asset"]
                assert "필요한 효과음" in v["needed_asset"]
        assert all(c.startswith(("onsite", "silence")) for c in m["not_mapped"])
        saved = yaml.safe_load((root / "presets" / PRESET / "sfx_map.yaml").read_text(encoding="utf-8"))
        assert saved["types"] == m["types"]
        assert not no_abs_paths(saved, root)
        assert abs(m["types"][[k for k, n in name_of.items() if n == "whoosh"][0]]["onset_s"] - 0.3) <= 0.03
    finally:
        shutil.rmtree(lib, ignore_errors=True)


@pytest.mark.slow
def test_library_missing_keeps_types_unmeasured(project_env):
    root = project_env["root"]
    C.build_catalog(PRESET, video_ids=["synv1", "synv2", "synv3", "synv4"])
    shutil.rmtree(root / "assets" / "library" / "sfx", ignore_errors=True)
    m = M.build_map(PRESET, write=False)
    assert m["library_status"] == "not_provided"
    assert m["types"] and all(v["status"] == "unmeasured" for v in m["types"].values())


def test_real_state_not_provided(tmp_project):
    """Current real state: catalog unmeasured (no reference analysed) and no SFX library ->
    library_status stays 'not_provided', no types invented."""
    shutil.copy(REPO / "presets/joshuamagazine/sfx_catalog.json", tmp_project / "presets/joshuamagazine/sfx_catalog.json")
    shutil.copy(REPO / "presets/joshuamagazine/sfx_map.yaml", tmp_project / "presets/joshuamagazine/sfx_map.yaml")
    m = M.build_map(PRESET)
    assert m["library_status"] == "not_provided" and m["types"] == {}
    assert m["catalog"]["status"] == "unmeasured"
    # the real repo has the folder with only a README: still not provided
    (tmp_project / "assets/library/sfx").mkdir(parents=True, exist_ok=True)
    shutil.copy(REPO / "assets/library/sfx/README.md", tmp_project / "assets/library/sfx/README.md")
    m = M.build_map(PRESET)
    assert m["library_status"] == "not_provided" and m["library_files"] == 0
    saved = yaml.safe_load((tmp_project / "presets/joshuamagazine/sfx_map.yaml").read_text(encoding="utf-8"))
    assert saved["library_root"] == "assets/library/sfx" and saved["library_status"] == "not_provided"


def test_external_library_root_token(tmp_project, tmp_path_factory):
    ext = tmp_path_factory.mktemp("user_sfx")
    S._write(ext / "pop_x.wav", S.sfx_bank()["pop"])
    (tmp_project / "local.yaml").write_text(f"sfx_library_root: {ext}\n", encoding="utf-8")
    files, errors = M.scan_library(ext, "$sfx_library_root")
    assert not errors and files[0]["stored"] == "$sfx_library_root/pop_x.wav"
    m = M.build_map(PRESET, write=False)
    assert m["library_root"] == "$sfx_library_root" and m["library_status"] == "scanned"
