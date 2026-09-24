"""Reference download bookkeeping with a SYNTHETIC fetcher (no network).

The fetcher stands in for yt-dlp: it copies a locally generated clip to the output template path
and returns a SYNTHETIC info dict shaped like yt-dlp's (``format_id``, ``requested_downloads``).
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from shortkit.reference import download as D


@pytest.fixture()
def tiny_clip(tmp_path):
    p = tmp_path / "tiny.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=320x180:d=1:r=30", "-f", "lavfi",
                    "-i", "sine=f=440:d=1", "-shortest", "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
                    str(p)], check=True)
    return p


def test_download_records_and_cache(proj, tiny_clip):
    calls = []

    def fetch(url, out_dir, max_height, cookies):
        vid = url.split("v=")[1]
        calls.append(vid)
        dst = out_dir / f"{vid}.mp4"
        shutil.copy(tiny_clip, dst)
        return {"id": vid, "format_id": "137+140", "webpage_url": url,
                "requested_downloads": [{"filepath": str(dst)}]}   # SYNTHETIC info dict

    r = D.download("joshuamagazine", ["abcDEF12345", "zzzYYY00000"], fetch=fetch)
    assert r["ok"] == ["abcDEF12345", "zzzYYY00000"]
    rows = [json.loads(x) for x in (proj / "presets/joshuamagazine/reference/downloads.jsonl").read_text().splitlines()]
    assert len(rows) == 2
    for k in ("video_id", "path", "sha256", "format_id", "width", "height", "fps", "vcodec", "acodec", "bitrate",
              "downloaded_at"):
        assert k in rows[0]
    assert rows[0]["path"] == "presets/joshuamagazine/reference/videos/abcDEF12345.mp4"   # root-relative
    assert rows[0]["width"] == 320 and rows[0]["acodec"] == "aac" and rows[0]["format_id"] == "137+140"
    # second run: cached, fetcher not called again
    r2 = D.download("joshuamagazine", ["abcDEF12345"], fetch=fetch)
    assert r2["cached"] == ["abcDEF12345"] and calls == ["abcDEF12345", "zzzYYY00000"]


def test_preexisting_file_registered_and_block_stops(proj, tiny_clip):
    vdir = proj / "presets/joshuamagazine/reference/videos"
    vdir.mkdir(parents=True)
    shutil.copy(tiny_clip, vdir / "handCopied1.mp4")

    def fetch(url, out_dir, max_height, cookies):
        raise RuntimeError("ERROR: Unable to download webpage: Tunnel connection failed: 403 Forbidden")

    r = D.download("joshuamagazine", ["handCopied1", "netVideo001", "netVideo002"], fetch=fetch)
    assert r["registered"] == ["handCopied1"]
    assert r["blocked"] is True and len(r["failed"]) == 2
    rows = [json.loads(x) for x in (proj / "presets/joshuamagazine/reference/downloads.jsonl").read_text().splitlines()]
    assert rows[0]["format_id"] is None and "pre-existing" in rows[0]["source"]
    log = (proj / "presets/joshuamagazine/reference/download_log.jsonl").read_text()
    assert "403" in log


def test_unsafe_ids_rejected(proj):
    with pytest.raises(ValueError):
        D.download("joshuamagazine", ["../../etc"], fetch=lambda *a: {})
