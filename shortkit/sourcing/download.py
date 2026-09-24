"""Download a warehouse candidate with provenance: ``warehouse/sources/<platform>_<id>.mp4``.

After a successful download the record gets ``download_path`` (root-relative), ``sha256``,
``download {status, at, format{...}, probe{...}, tool}``, a file-based ``quality`` measurement and a
fingerprint ``reference_overlap`` check (reference footage -> status 'excluded').

On failure (blocked platform, login required, ...) the record keeps its status, gets
``download {status: 'failed', platform_status, error, at}`` and ``access`` is updated; callers continue
with the next candidate (``download_many``).  A failure is never reported as success.

``attach_local_file`` is the manual-intake path for a file the user obtained themselves (copied into
warehouse/sources so the stored path stays inside the project).
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .. import paths
from ..util.hashing import sha256_file
from ..util.jsonio import now_iso
from . import exclusions, warehouse
from . import platforms as base
from .platforms import classify_error


def target_path(rec: dict, ext: str = "mp4") -> Path:
    return paths.absp(f"{warehouse.SOURCES_DIR}/{rec['id']}.{ext}")


def _probe_dict(p: Path) -> dict:
    from ..util.media import probe

    i = probe(p)
    return {"width": i.width, "height": i.height, "fps": round(i.fps, 3) if i.fps else None,
            "duration": round(i.duration, 3), "vcodec": i.vcodec, "acodec": i.acodec, "has_audio": i.has_audio,
            "bit_rate": i.bit_rate}


def _format_info(info: dict) -> dict:
    keys = ("format_id", "format", "ext", "vcodec", "acodec", "width", "height", "fps", "tbr", "vbr", "abr",
            "filesize", "filesize_approx", "protocol")
    out = {k: info.get(k) for k in keys if info.get(k) is not None}
    rf = info.get("requested_formats")
    if rf:
        out["requested_formats"] = [{k: f.get(k) for k in keys if f.get(k) is not None} for f in rf]
    return out


def finalize_file(rec: dict, file: Path, *, how: str, fmt: dict | None = None, measure: bool = True) -> dict:
    """Common post-download bookkeeping: hash, probe, quality (``measure``), fingerprint overlap check (always)."""
    rec["download_path"] = paths.relp(file)
    rec["sha256"] = sha256_file(file)
    pr = _probe_dict(file)
    rec["download"] = {"status": "ok", "at": now_iso(), "how": how, "format": fmt or {}, "probe": pr}
    for k in ("width", "height", "duration"):
        if pr.get(k) and not rec.get(k):
            rec[k] = pr[k]
    rec["orientation"] = warehouse.orientation(rec.get("width"), rec.get("height"))
    if measure:
        from .score import measure_quality

        try:
            rec["quality"] = measure_quality(file)
        except Exception as e:  # noqa: BLE001
            rec["quality"] = {"measured_at": None, "error": f"{type(e).__name__}: {e}"}
    # the reference-overlap check always runs on a new file (hard rule: never reuse the reference's recording)
    try:
        res = exclusions.check(rec, video_path=file)
    except Exception as e:  # noqa: BLE001
        res = {"excluded": None, "method": "error", "note": f"지문 검사 실패: {type(e).__name__}: {e}"}
    warehouse.apply_overlap(rec, res, by="download:exclusions")
    return warehouse.refresh_scores(rec)


def download(cid: str, *, force: bool = False, measure: bool = True) -> dict:
    """Download one candidate. Returns {ok, id, status, path?, sha256?, error?}."""
    rec = warehouse.get(cid)
    if rec.get("status") == "excluded" and not force:
        return {"ok": False, "id": cid, "status": "refused",
                "error": "레퍼런스와 같은 녹화로 제외된 후보라 받지 않음(--force 로 검증용 다운로드 가능)"}
    if rec.get("download_path") and not force and paths.absp(rec["download_path"]).is_file():
        return {"ok": True, "id": cid, "status": "already", "path": rec["download_path"], "sha256": rec.get("sha256")}
    url = rec.get("url")
    if not url:
        return {"ok": False, "id": cid, "status": "failed", "error": "URL 없음"}
    out = target_path(rec)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmpl = str(out.with_suffix("")) + ".%(ext)s"
    now = now_iso()
    try:
        info = base.ytdlp_download(url, tmpl, cookie=base.cookiefile(rec["platform"]))
    except Exception as e:  # noqa: BLE001 - recorded, never hidden
        acc = classify_error(e)
        rec["download"] = {"status": "failed", "at": now, "platform_status": acc["platform_status"],
                           "error": acc["note"]}
        rec["access"] = {**acc, "checked_at": now}
        warehouse.put(rec)
        return {"ok": False, "id": cid, "status": acc["platform_status"], "error": acc["note"]}
    fp = Path(info.get("_shortkit_filepath") or out)
    if not fp.is_file() and out.is_file():
        fp = out
    if not fp.is_file():
        rec["download"] = {"status": "failed", "at": now, "platform_status": "error",
                           "error": "yt-dlp 가 성공을 반환했지만 파일이 없음"}
        warehouse.put(rec)
        return {"ok": False, "id": cid, "status": "error", "error": rec["download"]["error"]}
    if fp.suffix != ".mp4" or fp != out:
        from ..util.media import ffmpeg

        try:
            ffmpeg(["-i", fp, "-c", "copy", "-movflags", "+faststart", out])
        except Exception as e:  # noqa: BLE001 - recorded, never hidden
            rec["download"] = {"status": "failed", "at": now, "platform_status": "error",
                               "error": base.scrub(f"mp4 로 옮기기(remux) 실패: {type(e).__name__}: {e}")[:800]}
            warehouse.put(rec)
            return {"ok": False, "id": cid, "status": "error", "error": rec["download"]["error"]}
        if fp != out:
            fp.unlink(missing_ok=True)
        fp = out
    # refresh metadata carried by the download (views etc.), through the platform normaliser
    try:
        adapter = base.get_adapter(rec["platform"])
        norm = getattr(adapter, "normalize", None)
        if norm and rec["platform"] != "reddit":
            item = norm(info)
            item["_item_access"] = base.access(base.OK)
            if str(item.get("platform_id")) == str(rec["platform_id"]):
                rec = warehouse.merge_record(rec, item)
    except KeyError:
        pass
    rec["access"] = {**base.access(base.OK), "checked_at": now}
    rec = finalize_file(rec, fp, how="yt-dlp", fmt={**_format_info(info), "tool": warehouse._tool_version("yt")},
                        measure=measure)
    warehouse.put(rec)
    return {"ok": True, "id": cid, "status": "ok", "path": rec["download_path"], "sha256": rec["sha256"],
            "excluded": (rec.get("reference_overlap") or {}).get("excluded")}


def download_many(ids: list[str], **kw) -> list[dict]:
    """Try every candidate; a blocked platform never stops the others."""
    out = []
    for cid in ids:
        try:
            out.append(download(cid, **kw))
        except KeyError as e:
            out.append({"ok": False, "id": cid, "status": "missing", "error": str(e)})
    return out


def attach_local_file(cid: str, file: str | Path, *, measure: bool = True, note: str | None = None) -> dict:
    """Manual intake: copy a user-provided file into warehouse/sources and record provenance."""
    rec = warehouse.get(cid)
    src = Path(file).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"파일 없음: {file}")
    out = target_path(rec, ext=src.suffix.lstrip(".").lower() or "mp4")
    out.parent.mkdir(parents=True, exist_ok=True)
    if src != out.resolve():
        shutil.copy2(src, out)
    rec = finalize_file(rec, out, how="manual_file" + (f" ({note})" if note else ""),
                        fmt={"source_file_name": src.name}, measure=measure)
    warehouse.put(rec)
    return rec
