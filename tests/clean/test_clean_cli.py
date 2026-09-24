"""End-to-end CLI run in a temporary project root: detect -> faces -> plan -> apply -> verify -> show."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REAL_ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.slow


def run(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = dict(os.environ, SHORTKIT_ROOT=str(root), PYTHONPATH=str(REAL_ROOT))
    return subprocess.run([sys.executable, "-m", "shortkit", "clean", *args], cwd=root, env=env,
                          capture_output=True, text=True, timeout=900)


def test_cli_end_to_end(clean_root, dirty_short, cascades_ok):
    src = str(dirty_short.relative_to(clean_root))
    r = run(clean_root, "detect", "--source", src)
    assert r.returncode == 0, r.stderr
    assert "워터마크" in r.stdout and "원어 자막" in r.stdout
    if cascades_ok:
        r = run(clean_root, "faces", "--source", src, "--sample-fps", "0.25", "--max-samples", "2")
        assert r.returncode == 0, r.stderr
        assert "보호 영역" in r.stdout
    r = run(clean_root, "plan", "--source", src, "--region-aspect", "1080:608", "--fit", "cover",
            "--face-sample-fps", "0.25", "--out", "warehouse/overlays/cli_plan.json")
    assert r.returncode == 0, r.stderr
    assert "판단 근거" in r.stdout and "clean:" in r.stdout
    plan = json.loads((clean_root / "warehouse/overlays/cli_plan.json").read_text())
    r = run(clean_root, "apply", "--source", src, "--plan", "warehouse/overlays/cli_plan.json",
            "--out", "warehouse/cache/clean/cli_out.mp4", "--threads", "2")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "잔여 남음" not in r.stdout and "잔여 없음" in r.stdout
    r = run(clean_root, "verify", "--video", "warehouse/cache/clean/cli_out.mp4", "--source", src,
            "--plan", "warehouse/overlays/cli_plan.json")
    assert r.returncode == 0, r.stdout + r.stderr
    r = run(clean_root, "show", "--source", src)
    assert r.returncode == 0
    for act in ("detect", "plan", "apply", "verify"):
        assert act in r.stdout
    # provenance: the overlay records stay after removal, with removal entries added
    sha = plan["source"]["sha256"]
    doc = json.loads((clean_root / f"warehouse/overlays/{sha}.json").read_text())
    assert len(doc["overlays"]) == 2 and len(doc["removals"]) == 2
    assert all(rm["residual"] is False for rm in doc["removals"])
    # verify on the untouched source must report the overlays as still there (exit 1)
    r = run(clean_root, "verify", "--video", src, "--source", src)
    assert r.returncode == 1 and "잔여 남음" in r.stdout
