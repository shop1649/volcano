"""Shared helpers for sourcing tests (unique module name: imported by test files).

Network access is never used: every test that exercises a platform adapter installs a fake
``ytdlp_extract`` / ``http_get_json`` / ``ytdlp_download`` backed by SYNTHETIC fixtures
(tests/sourcing/fixtures/*.json, each labelled ``_fixture: SYNTHETIC ...``).
"""
from __future__ import annotations

import copy
import json
import shutil
import subprocess
from pathlib import Path


REPO = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures"
GEN = REPO / "assets" / "test" / "generated"
VIDEO = GEN / "video"

# Real error text produced on the build machine by the proxy block (2026-09-24 live run).
BLOCKED_TEXT = ("ERROR: query \"x\" page 1: Unable to download API page: ('Unable to connect to proxy', "
                "OSError('Tunnel connection failed: 403 Forbidden')) (caused by ProxyError(...))")


class FakeDownloadError(Exception):
    """Stands in for yt_dlp.utils.DownloadError (same message text)."""


def load_fixture(name: str) -> dict:
    d = json.loads((FIX / name).read_text(encoding="utf-8"))
    assert str(d.get("_fixture", "")).startswith("SYNTHETIC"), name
    return d



class FakeNet:
    """URL -> info dict / JSON / exception. Unknown URLs fail the test (no silent network)."""

    def __init__(self) -> None:
        self.extract: dict[str, object] = {}
        self.json: dict[str, object] = {}
        self.downloads: dict[str, object] = {}
        self.calls: list[tuple] = []

    def _resolve(self, table: dict, key: str):
        for k, v in table.items():
            if key == k or (k.endswith("*") and key.startswith(k[:-1])):
                if isinstance(v, BaseException):
                    raise v
                return copy.deepcopy(v)
        raise AssertionError(f"unexpected network call in test: {key}")

    def ytdlp_extract(self, url, *, flat=False, cookie=None, playlistend=None):
        self.calls.append(("extract", url, flat, cookie))
        return self._resolve(self.extract, url)

    def http_get_json(self, url, *, headers=None, timeout=20.0):
        self.calls.append(("json", url, dict(headers or {})))
        return self._resolve(self.json, url)

    def ytdlp_download(self, url, out_template, *, cookie=None):
        self.calls.append(("download", url, out_template))
        v = self._resolve(self.downloads, url)
        src = Path(v["file"])
        dst = Path(out_template.replace("%(ext)s", "mp4"))
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(src, dst)
        info = dict(v.get("info") or {})
        info["_shortkit_filepath"] = str(dst)
        return info


def _cut(src: Path, dst: Path, ss: float, t: float, vf: str) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", str(ss), "-t", str(t), "-i", str(src),
                    "-filter_complex" if ";" in vf else "-vf", vf, "-an", "-c:v", "libx264", "-preset", "veryfast",
                    "-crf", "30", str(dst)], check=True)
    return dst
