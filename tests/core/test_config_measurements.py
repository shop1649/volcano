"""Measurement-item loader rules shared by registry sync, apply-measurements and QA."""
import json
import shutil

import pytest

from shortkit import config, paths


@pytest.fixture()
def root(tmp_path, monkeypatch):
    shutil.copy(paths.project_root() / "shortkit.root", tmp_path / "shortkit.root")
    d = tmp_path / "presets" / "p" / "measurements"
    d.mkdir(parents=True)
    monkeypatch.setenv("SHORTKIT_ROOT", str(tmp_path))
    return d


def _write(d, name, items):
    (d / name).write_text(json.dumps({"schema": "shortkit.measurement/1", "items": items}), encoding="utf-8")


def test_measured_beats_unmeasured_regardless_of_file_order(root):
    _write(root, "a_manual.json", [{"key": "k.x", "status": "measured", "value": 3}])
    _write(root, "z_visual.json", [{"key": "k.x", "status": "unmeasured", "blocker": "b"}])
    it = config.load_measurement_items(root.parent)["k.x"]
    assert it["status"] == "measured" and it["value"] == 3 and it["file"].endswith("a_manual.json")
    assert any(f.endswith("z_visual.json") for f in it["also_in"])


def test_two_measured_values_for_one_key_is_a_conflict(root):
    _write(root, "a.json", [{"key": "k.y", "status": "measured", "value": 1}])
    _write(root, "b.json", [{"key": "k.y", "status": "measured", "value": 2}])
    with pytest.raises(config.MeasurementConflict):
        config.load_measurement_items(root.parent)
    it = config.load_measurement_items(root.parent, strict=False)["k.y"]
    assert it["value"] == 1 and it["conflicts"]
