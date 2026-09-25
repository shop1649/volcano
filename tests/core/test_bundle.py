"""Single-MD bundle: selection policy and the embedded restore snippet (run exactly as printed)."""
import re
import shutil
import subprocess
import sys

import pytest

from shortkit import bundle, paths


@pytest.fixture()
def proj(tmp_path):
    root = tmp_path / "proj"
    (root / "presets/p/sfx_fp").mkdir(parents=True)
    shutil.copy(paths.project_root() / "shortkit.root", root / "shortkit.root")
    (root / ".gitignore").write_text("local.yaml\nepisodes/*/build/\n*.tmp\n", encoding="utf-8")
    (root / "presets/p/preset.yaml").write_text("preset_id: p-v1\n", encoding="utf-8")
    (root / "presets/p/sfx_fp/edit_01.npy").write_bytes(b"\x93NUMPY" + b"\x00" * 20000)
    (root / "presets/p/measurements").mkdir()
    (root / "presets/p/measurements/visual_text.json").write_text('{"items": []}' + " " * 500_000, encoding="utf-8")
    (root / "cookies").mkdir()
    (root / "cookies/youtube.txt").write_text(".youtube.com\tTRUE\t/\tTRUE\t0\tSID\tSECRET\n", encoding="utf-8")
    (root / "local.yaml").write_text("sourcing: {cookies: {instagram: my_ig_cookie.dat}}\n", encoding="utf-8")
    (root / "my_ig_cookie.dat").write_text("secret", encoding="utf-8")
    (root / "episodes/e1/build").mkdir(parents=True)
    (root / "episodes/e1/build/resolved.json").write_text("{}", encoding="utf-8")
    (root / "episodes/e1/plan.yaml").write_text("episode_id: e1\n", encoding="utf-8")
    (root / "run.log").write_text("/abs/path", encoding="utf-8")
    (root / "docs/validation/mockloop").mkdir(parents=True)
    (root / "docs/validation/mockloop/build_scratch.py").write_text("print('scratch')\n", encoding="utf-8")
    (root / "docs/validation/mockloop.md").write_text("python docs/validation/mockloop/build_scratch.py\n", encoding="utf-8")
    (root / "docs/validation/sheet.png").write_bytes(b"\x89PNG" + b"\x00" * 100)
    return root


def test_selection_keeps_preset_assets_and_never_packs_secrets(proj):
    files, skipped = bundle.select_files(proj)       # no git here -> .gitignore fallback
    assert "presets/p/sfx_fp/edit_01.npy" in files
    assert "presets/p/measurements/visual_text.json" in files          # > 400 kB text is kept
    assert "episodes/e1/plan.yaml" in files
    # the validation scripts a bundled doc tells the reader to run are packed (the restore found them missing)
    assert "docs/validation/mockloop/build_scratch.py" in files and "docs/validation/mockloop.md" in files
    assert "docs/validation/sheet.png" not in files
    for secret in ("cookies/youtube.txt", "local.yaml", "my_ig_cookie.dat", "run.log", "episodes/e1/build/resolved.json"):
        assert secret not in files


def test_embedded_restore_snippet_runs_as_printed(proj, tmp_path):
    payload, files = bundle.build_payload(proj)
    md = bundle.render_md(payload, files, "# header\n")
    work = tmp_path / "work"
    work.mkdir()
    (work / "PRESET_BUNDLE.md").write_text(md, encoding="utf-8")
    snippet = re.search(r"```bash\n(.*?)\n```", md, re.S).group(1)
    r = subprocess.run(["bash", "-c", snippet.replace("python3 -", f"{sys.executable} -", 1)], cwd=work,
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (work / "shortkit-preset/presets/p/sfx_fp/edit_01.npy").is_file()
    assert "sha256 ok" in r.stdout
    n = int(re.search(r"1–(\d+) 줄만 읽는다", md).group(1))
    assert md.splitlines()[n].startswith("<!-- SHORTKIT-PAYLOAD-BEGIN")   # line n+1 is the marker


def test_binary_under_presets_too_big_fails_the_build(proj):
    (proj / "presets/p/big.bin").write_bytes(b"\x00" * (bundle.BINARY_MAX_BYTES + 1))
    with pytest.raises(ValueError):
        bundle.build_payload(proj)
