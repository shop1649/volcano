"""Download reference videos (mp4, <= 1080p, with audio) for analysis.

    shortkit ref download --set latest100|high_views   or   --ids a,b,c

Files land in ``presets/<name>/reference/videos/<id>.mp4`` (git-ignored); provenance goes to
``reference/downloads.jsonl``::

    {video_id, path, sha256, format_id, width, height, fps, vcodec, acodec, bitrate, downloaded_at, ...}

A file that already exists is reused (sha256 checked against its record); an existing file
without a record (e.g. copied in by hand on another machine) is registered with
``format_id: null`` and ``source: pre-existing file``.  Failures go to ``download_log.jsonl``.
"""
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .. import paths
from ..util.hashing import sha256_file
from ..util.jsonio import append_jsonl, now_iso, read_jsonl
from ..util.media import probe
from .collect import Blocked, classify_error
from .common import reference_dir, safe_id, say, scrub, videos_dir, warn

# Cap the SHORT side, not the height: a vertical Short is 1080x1920, and a height cap of 1080 would
# fetch a 608x1080 rendition.  yt-dlp's sort field "res" is the smaller dimension of the video.
FORMAT = "bv*+ba/b"


def _format_for(max_short_side: int) -> str:
    return FORMAT


def _format_sort(max_short_side: int) -> list[str]:
    return [f"res:{int(max_short_side)}", "ext:mp4:m4a", "fps"]


def ydl_download(url: str, out_dir: Path, max_height: int = 1080, cookies: str | None = None) -> dict:
    """One yt-dlp download.  Returns the info dict (with ``requested_downloads``)."""
    import yt_dlp

    opts = {"quiet": True, "no_warnings": True, "noprogress": True, "format": _format_for(max_height),
            "format_sort": _format_sort(max_height),
            "merge_output_format": "mp4", "outtmpl": str(out_dir / "%(id)s.%(ext)s"), "retries": 2,
            "socket_timeout": 30, "overwrites": False}
    if cookies:
        opts["cookiefile"] = str(paths.absp(cookies))
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.sanitize_info(info) if hasattr(ydl, "sanitize_info") else info


def _record(vid: str, f: Path, info: dict | None, source: str) -> dict:
    pi = probe(f)
    info = info or {}
    fmt = info.get("format_id")
    return {"video_id": vid, "path": paths.relp(f), "sha256": sha256_file(f), "format_id": fmt,
            "width": pi.width, "height": pi.height, "fps": round(pi.fps, 3) if pi.fps else None,
            "vcodec": pi.vcodec, "acodec": pi.acodec, "bitrate": pi.bit_rate, "duration": round(pi.duration, 3),
            "has_audio": pi.has_audio, "downloaded_at": now_iso(), "source": source,
            "source_url": info.get("webpage_url") or info.get("original_url"),
            "requested_format": (f"{_format_for(1080)} sort={','.join(_format_sort(1080))}") if fmt else None}


def download(preset: str, ids: list[str], max_height: int = 1080, cookies: str | None = None,
             fetch: Callable[..., dict] | None = None) -> dict:
    fetch = fetch or ydl_download
    rdir = reference_dir(preset)
    vdir = videos_dir(preset)
    vdir.mkdir(parents=True, exist_ok=True)
    log_path = rdir / "downloads.jsonl"
    recs = {}
    for r in read_jsonl(log_path):
        recs[r["video_id"]] = r
    out = {"ok": [], "cached": [], "registered": [], "failed": [], "blocked": False}
    for raw in ids:
        vid = safe_id(raw)
        existing = next((p for p in sorted(vdir.glob(f"{vid}.*"))
                         if p.suffix.lower() in (".mp4", ".mkv", ".webm", ".mov")), None)
        if existing is not None:
            rec = recs.get(vid)
            if rec and rec.get("path") == paths.relp(existing) and rec.get("sha256") == sha256_file(existing):
                out["cached"].append(vid)
                continue
            r = _record(vid, existing, None, "pre-existing file (provenance unknown: not downloaded by this command)")
            append_jsonl(log_path, r)
            out["registered"].append(vid)
            continue
        if out["blocked"]:
            out["failed"].append({"video_id": vid, "error": "skipped after block"})
            continue
        url = f"https://www.youtube.com/watch?v={vid}"
        try:
            info = fetch(url, vdir, max_height, cookies)
        except Exception as e:
            msg = scrub(f"{type(e).__name__}: {e}")
            kind = classify_error(msg)
            append_jsonl(rdir / "download_log.jsonl", {"video_id": vid, "status": kind, "error": msg[:2000],
                                                       "at": now_iso()})
            out["failed"].append({"video_id": vid, "error": msg[:300], "kind": kind})
            if kind == "blocked" or isinstance(e, Blocked):
                out["blocked"] = True
            continue
        f = None
        for d in (info or {}).get("requested_downloads") or []:
            if d.get("filepath") and Path(d["filepath"]).is_file():
                f = Path(d["filepath"])
        if f is None:
            f = next((p for p in sorted(vdir.glob(f"{vid}.*")) if p.suffix.lower() in (".mp4", ".mkv", ".webm")), None)
        if f is None:
            append_jsonl(rdir / "download_log.jsonl", {"video_id": vid, "status": "error",
                                                       "error": "yt-dlp returned without a file", "at": now_iso()})
            out["failed"].append({"video_id": vid, "error": "no file"})
            continue
        r = _record(vid, f, info, "yt-dlp")
        append_jsonl(log_path, r)
        out["ok"].append(vid)
    say(f"다운로드: 새로 받음 {len(out['ok'])}, 캐시 사용 {len(out['cached'])}, 기존 파일 등록 {len(out['registered'])}, "
        f"실패 {len(out['failed'])}")
    if out["failed"]:
        warn("실패: " + "; ".join(f"{x['video_id']}: {x['error'][:160]}" for x in out["failed"][:5]))
    if out["blocked"]:
        warn("플랫폼 접속이 차단되어 나머지 다운로드를 건너뛰었습니다(download_log.jsonl 참조).")
    return out
