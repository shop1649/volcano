"""Reference channel listing and the fixed "latest 100" snapshot.

Two methods (``--method auto`` picks the API when ``YOUTUBE_API_KEY`` is set):

* ``ytdlp``  -- yt-dlp ``extract_flat`` over the channel's ``/shorts`` and ``/videos`` tabs (tab
  order = newest first), then full per-video metadata (``timestamp``/``upload_date``,
  ``duration``, ``view_count``, ``description``) for the newest ``latest_n`` of each tab, merged
  and sorted by publish time.
* ``api``    -- YouTube Data API v3: ``channels.list`` (uploads playlist) -> ``playlistItems.list``
  (``contentDetails.videoPublishedAt``) -> ``videos.list`` (``statistics.viewCount``,
  ``contentDetails.duration``, ``snippet``).  The API has no "is a Short" flag: ``kind`` is
  derived from duration (<= 180 s -> short) and marked as such.

Files (presets/<name>/reference/):
  latest100.json   the fixed baseline.  An existing ``status: ok`` snapshot is NEVER overwritten
                   unless ``--refresh-snapshot`` is given; a failed attempt never replaces it.
  all_videos.json  whole-channel listing, reference only (latest100 wins on conflicting fields).
  high_views.json  videos with an exact view_count >= reference.high_view_threshold (+checked_at);
                   flat-listing approximations above the threshold are kept apart as ``unverified``.
  meta/<id>.json   per-video metadata (title, description, tags) used by `ref trace`.
  collect_log.jsonl every attempt (method, status, exact blocker).

A network block (HTTP 403 from the egress proxy, DNS failure, timeouts ...) is written as
``status: blocked`` with the exact error text and zero videos, and the command exits non-zero.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

from .. import paths
from ..config import load_preset
from ..util.jsonio import append_jsonl, now_iso, read_json, write_json
from .common import SNAPSHOT_SCHEMA, reference_dir, safe_id, say, warn

LISTING_SCHEMA = "shortkit.ref_channel_listing/1"
HIGH_SCHEMA = "shortkit.ref_high_views/1"
API_BASE = "https://www.googleapis.com/youtube/v3/"
TABS = ("shorts", "videos")

_BLOCK_PATTERNS = ("403", "forbidden", "tunnel connection failed", "urlopen error", "connection refused",
                   "timed out", "timeout", "name or service not known", "temporary failure in name resolution",
                   "network is unreachable", "connection reset", "remote end closed", "certificate verify failed",
                   "unable to download webpage", "http error 429", "sign in to confirm", "proxy", "egress",
                   "unable to download api page", "ssl")
_TAB_ABSENT = ("does not have a", "this channel has no", "tab does not exist")


class Blocked(RuntimeError):
    """The platform could not be reached (network policy, login wall, rate limit ...)."""


def classify_error(msg: str) -> str:
    m = (msg or "").lower()
    if any(p in m for p in _TAB_ABSENT):
        return "tab_absent"
    if any(p in m for p in _BLOCK_PATTERNS):
        return "blocked"
    return "error"


# ============================================================================= yt-dlp
def _ydl_version() -> str:
    try:
        import yt_dlp
        return yt_dlp.version.__version__
    except Exception:  # pragma: no cover
        return "unknown"


def ydl_extract(url: str, flat: bool, cookies: str | None = None) -> dict:
    """One yt-dlp ``extract_info`` call (no download).  Tests monkeypatch
    ``yt_dlp.YoutubeDL.extract_info`` with SYNTHETIC info dicts."""
    import yt_dlp

    opts: dict[str, Any] = {"quiet": True, "no_warnings": True, "skip_download": True, "noprogress": True,
                            "socket_timeout": 20, "retries": 1, "extractor_retries": 1}
    if flat:
        opts["extract_flat"] = "in_playlist"
    if cookies:
        opts["cookiefile"] = str(paths.absp(cookies))
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    return ydl.sanitize_info(info) if hasattr(ydl, "sanitize_info") and info is not None else (info or {})


def _iso_from_ts(ts) -> str | None:
    try:
        return dt.datetime.fromtimestamp(float(ts), dt.timezone.utc).replace(microsecond=0).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def _date_from_upload(ud: str | None) -> str | None:
    if ud and re.fullmatch(r"\d{8}", str(ud)):
        return f"{ud[:4]}-{ud[4:6]}-{ud[6:]}"
    return None


def _flat_entries(info: dict) -> list[dict]:
    """Entries of a tab listing (nested playlists are flattened)."""
    out = []
    for e in info.get("entries") or []:
        if not e:
            continue
        if e.get("_type") == "playlist" and e.get("entries"):
            out.extend(_flat_entries(e))
        else:
            out.append(e)
    return out


def list_ytdlp(channel_url: str, latest_n: int, cookies: str | None = None, max_meta: int | None = None,
               extract: Callable[..., dict] | None = None) -> dict:
    """Listing + per-video metadata with yt-dlp.  Raises Blocked when the channel is unreachable."""
    extract = extract or ydl_extract
    tabs: dict[str, dict] = {}
    listing: dict[str, dict] = {}
    order: dict[str, list[str]] = {}
    for tab in TABS:
        url = channel_url.rstrip("/") + "/" + tab
        try:
            info = extract(url, True, cookies)
        except Exception as e:  # yt_dlp.utils.DownloadError and friends
            msg = f"{type(e).__name__}: {e}"
            kind = classify_error(msg)
            tabs[tab] = {"status": kind, "error": msg}
            if kind == "blocked":
                raise Blocked(f"{url}: {msg}") from None
            continue
        ents = _flat_entries(info)
        tabs[tab] = {"status": "ok", "n": len(ents), "url": url}
        order[tab] = []
        for e in ents:
            vid = e.get("id")
            if not vid:
                continue
            try:
                safe_id(vid)
            except ValueError:
                continue
            order[tab].append(vid)
            rec = listing.setdefault(vid, {"video_id": vid})
            rec.setdefault("kind", "short" if tab == "shorts" else "video")
            rec.setdefault("title", e.get("title"))
            rec.setdefault("url", f"https://www.youtube.com/shorts/{vid}" if tab == "shorts"
                           else f"https://www.youtube.com/watch?v={vid}")
            if e.get("duration") is not None:
                rec.setdefault("duration", e.get("duration"))
            if e.get("view_count") is not None:
                rec["view_count_flat"] = int(e["view_count"])
            rec["tab_rank"] = {**rec.get("tab_rank", {}), tab: len(order[tab])}
    if not listing:
        errs = "; ".join(f"{k}: {v.get('error')}" for k, v in tabs.items() if v.get("error"))
        raise Blocked(f"채널 목록이 비어 있음 ({errs or 'no entries'})")
    # per-video metadata: newest latest_n of each tab (tab order = newest first)
    want: list[str] = []
    for tab in TABS:
        for vid in order.get(tab, [])[:latest_n]:
            if vid not in want:
                want.append(vid)
    if max_meta is not None:
        want = want[:max_meta]
    meta: dict[str, dict] = {}
    failures: list[dict] = []
    blocked_n = 0
    for vid in want:
        url = listing[vid]["url"]
        try:
            info = extract(f"https://www.youtube.com/watch?v={vid}", False, cookies)
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            k = classify_error(msg)
            blocked_n += k == "blocked"
            failures.append({"video_id": vid, "kind": k, "error": msg[:500]})
            continue
        meta[vid] = {"checked_at": now_iso(), "info": info, "url": url}
    if want and not meta and blocked_n:
        raise Blocked(f"영상 메타데이터 {len(want)}건 모두 실패: {failures[0]['error']}")
    return {"tabs": tabs, "listing": listing, "meta": meta, "failures": failures, "order": order,
            "method": f"yt-dlp {_ydl_version()} (extract_flat /shorts,/videos + per-video metadata)"}


def _record_from_meta(vid: str, base: dict, m: dict) -> dict:
    info = m["info"]
    ts = info.get("timestamp") or info.get("release_timestamp")
    pub = _iso_from_ts(ts) if ts else None
    ud = _date_from_upload(info.get("upload_date"))
    return {"video_id": vid, "url": base.get("url"), "title": info.get("title") or base.get("title"),
            "published_at": pub, "upload_date": ud or (pub[:10] if pub else None),
            "published_at_precision": "second" if pub else ("day" if ud else None),
            "duration": info.get("duration") if info.get("duration") is not None else base.get("duration"),
            "view_count": int(info["view_count"]) if info.get("view_count") is not None else None,
            "view_count_checked_at": m["checked_at"], "view_count_source": "video_metadata",
            "kind": base.get("kind"), "_sort": float(ts) if ts else _date_sort(ud),
            "_meta": {"title": info.get("title"), "description": info.get("description"), "tags": info.get("tags"),
                      "channel": info.get("channel"), "channel_id": info.get("channel_id"),
                      "uploader_id": info.get("uploader_id"), "width": info.get("width"),
                      "height": info.get("height"), "fetched_at": m["checked_at"]}}


def _date_sort(ud: str | None) -> float | None:
    if not ud:
        return None
    try:
        return dt.datetime.strptime(ud, "%Y-%m-%d").replace(tzinfo=dt.timezone.utc).timestamp()
    except ValueError:
        return None


# ============================================================================= YouTube Data API v3
def _api_get(endpoint: str, params: dict, key: str, getter: Callable[[str], dict] | None = None) -> dict:
    q = dict(params)
    q["key"] = key
    url = API_BASE + endpoint + "?" + urllib.parse.urlencode(q)
    if getter is not None:
        return getter(url)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        # never echo the key
        raise Blocked(f"{endpoint}: {type(e).__name__}: {str(e).replace(key, '***')}") from None


_ISO_DUR = re.compile(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?")


def iso8601_duration(s: str | None) -> float | None:
    if not s:
        return None
    m = _ISO_DUR.fullmatch(s)
    if not m:
        return None
    d, h, mi, se = m.groups()
    return float(d or 0) * 86400 + float(h or 0) * 3600 + float(mi or 0) * 60 + float(se or 0)


def list_api(handle: str | None, channel_id: str | None, latest_n: int, key: str,
             getter: Callable[[str], dict] | None = None, max_items: int | None = None) -> dict:
    ch = None
    if handle:
        r = _api_get("channels", {"part": "contentDetails,snippet", "forHandle": handle}, key, getter)
        ch = (r.get("items") or [None])[0]
    if ch is None and channel_id:
        r = _api_get("channels", {"part": "contentDetails,snippet", "id": channel_id}, key, getter)
        ch = (r.get("items") or [None])[0]
    if ch is None:
        raise Blocked("channels.list: 채널을 찾지 못함 (forHandle / id)")
    uploads = ch["contentDetails"]["relatedPlaylists"]["uploads"]
    items: list[dict] = []
    token = None
    while True:
        p = {"part": "contentDetails,snippet", "playlistId": uploads, "maxResults": 50}
        if token:
            p["pageToken"] = token
        r = _api_get("playlistItems", p, key, getter)
        items.extend(r.get("items") or [])
        token = r.get("nextPageToken")
        if not token or (max_items and len(items) >= max_items):
            break
    ids = [it["contentDetails"]["videoId"] for it in items if it.get("contentDetails", {}).get("videoId")]
    vids: dict[str, dict] = {}
    checked = now_iso()
    for i in range(0, len(ids), 50):
        r = _api_get("videos", {"part": "snippet,contentDetails,statistics", "id": ",".join(ids[i:i + 50])},
                     key, getter)
        for v in r.get("items") or []:
            vids[v["id"]] = v
    listing, meta = {}, {}
    for it in items:
        vid = it.get("contentDetails", {}).get("videoId")
        if not vid or vid not in vids:
            continue
        try:
            safe_id(vid)
        except ValueError:
            continue
        v = vids[vid]
        dur = iso8601_duration(v.get("contentDetails", {}).get("duration"))
        pub = it["contentDetails"].get("videoPublishedAt") or v.get("snippet", {}).get("publishedAt")
        vc = v.get("statistics", {}).get("viewCount")
        kind = "short" if dur is not None and dur <= 180 else "video"
        listing[vid] = {"video_id": vid, "kind": kind, "kind_method": "duration<=180s (API has no Shorts flag)",
                        "url": f"https://www.youtube.com/watch?v={vid}", "title": v.get("snippet", {}).get("title")}
        meta[vid] = {"checked_at": checked, "url": listing[vid]["url"], "info": {
            "title": v.get("snippet", {}).get("title"), "description": v.get("snippet", {}).get("description"),
            "tags": v.get("snippet", {}).get("tags"), "channel": v.get("snippet", {}).get("channelTitle"),
            "channel_id": v.get("snippet", {}).get("channelId"), "duration": dur,
            "view_count": int(vc) if vc is not None else None, "timestamp": _ts_from_iso(pub),
            "upload_date": pub[:10].replace("-", "") if pub else None}}
    return {"tabs": {"uploads": {"status": "ok", "n": len(items), "playlist": uploads}}, "listing": listing,
            "meta": meta, "failures": [], "method": "youtube-data-api-v3 (channels/playlistItems/videos)"}


def _ts_from_iso(s: str | None) -> float | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


# ============================================================================= snapshot files
def build_records(res: dict, latest_n: int) -> tuple[list[dict], list[dict], list[str]]:
    """(latest list, all list, notes) from a listing result."""
    notes: list[str] = []
    recs = []
    for vid, base in res["listing"].items():
        if vid in res["meta"]:
            recs.append(_record_from_meta(vid, base, res["meta"][vid]))
        else:
            recs.append({"video_id": vid, "url": base.get("url"), "title": base.get("title"), "published_at": None,
                         "upload_date": None, "duration": base.get("duration"),
                         "view_count": base.get("view_count_flat"),
                         "view_count_checked_at": now_iso() if base.get("view_count_flat") is not None else None,
                         "view_count_source": "flat_listing_approx" if base.get("view_count_flat") is not None
                         else "unavailable", "kind": base.get("kind"), "_sort": None})
    dated = [r for r in recs if r["_sort"] is not None]
    undated = [r for r in recs if r["_sort"] is None]
    dated.sort(key=lambda r: (-r["_sort"], r["video_id"]))
    latest = dated[:latest_n]
    if len(latest) < latest_n and undated:
        notes.append(f"게시 시각을 모르는 영상 {len(undated)}편은 최신순 정렬에서 제외됨(메타데이터 미수집)")
    for i, r in enumerate(latest, 1):
        r["rank"] = i
    all_recs = dated + sorted(undated, key=lambda r: r["video_id"])
    return latest, all_recs, notes


def _clean(r: dict, keys: tuple) -> dict:
    return {k: r.get(k) for k in keys}


LATEST_KEYS = ("rank", "video_id", "url", "title", "published_at", "upload_date", "duration", "view_count",
               "view_count_checked_at", "kind")
ALL_KEYS = ("video_id", "url", "title", "published_at", "upload_date", "duration", "view_count",
            "view_count_source", "view_count_checked_at", "kind", "in_latest100")


def collect(preset: str = "joshuamagazine", method: str = "auto", refresh_snapshot: bool = False,
            cookies: str | None = None, max_meta: int | None = None,
            extract: Callable[..., dict] | None = None, api_getter: Callable[[str], dict] | None = None) -> dict:
    """Run a collection attempt and write the reference files.  Returns a summary dict with
    ``status`` (ok|partial|blocked|kept) and ``exit_code``."""
    pr = load_preset(preset)
    channel_url = pr.get("reference.channel_url")
    latest_n = int(pr.get("reference.latest_n"))
    threshold = int(pr.get("reference.high_view_threshold"))
    handle = pr.get("reference.channel_handle", None)
    channel_id = pr.get("reference.channel_id_hint", None)
    rdir = reference_dir(preset)
    rdir.mkdir(parents=True, exist_ok=True)
    key = os.environ.get("YOUTUBE_API_KEY")
    if method == "auto":
        method = "api" if key else "ytdlp"
    attempted_at = now_iso()
    try:
        if method == "api":
            if not key:
                raise Blocked("YOUTUBE_API_KEY 환경 변수가 없음")
            res = list_api(handle, channel_id, latest_n, key, getter=api_getter)
        else:
            res = list_ytdlp(channel_url, latest_n, cookies=cookies, max_meta=max_meta, extract=extract)
    except Blocked as e:
        label = f"yt-dlp {_ydl_version()}" if method == "ytdlp" else "youtube-data-api-v3"
        return _write_blocked(preset, rdir, channel_url, label, attempted_at, str(e))
    latest, all_recs, notes = build_records(res, latest_n)
    status = "ok"
    blocker = None
    if res.get("failures"):
        status = "partial"
        blocker = f"메타데이터 실패 {len(res['failures'])}건: {res['failures'][0]['error'][:300]}"
    if len(latest) < latest_n:
        n_total = len(res["listing"])
        if n_total >= latest_n or res.get("failures"):
            status = "partial"
            blocker = blocker or f"게시 시각이 확인된 영상이 {len(latest)}편뿐(목록 {n_total}편)"
        else:
            notes.append(f"채널 전체 영상이 {n_total}편뿐이라 최신 {latest_n}편을 채우지 못함")
    # per-video metadata (descriptions for `ref trace`)
    for r in all_recs:
        if r.get("_meta"):
            write_json(rdir / "meta" / f"{r['video_id']}.json", {"video_id": r["video_id"], **r["_meta"],
                                                                  "source": res["method"]})
    snap_path = rdir / "latest100.json"
    old = read_json(snap_path)
    kept = bool(old and old.get("status") == "ok" and not refresh_snapshot)
    snapshot = {"schema": SNAPSHOT_SCHEMA, "preset_id": pr.preset_id, "channel_url": channel_url,
                "captured_at": attempted_at, "method": res["method"], "status": status, "blocker": blocker,
                "latest_n": latest_n, "n": len(latest), "sort": "published_at desc (timestamp; upload_date if no time)",
                "tabs": res.get("tabs"), "notes": notes, "videos": [_clean(r, LATEST_KEYS) for r in latest]}
    if kept:
        say(f"기존 최신 {latest_n}편 스냅샷(고정 시각 {old.get('captured_at')})을 유지합니다. "
            "새로 고정하려면 --refresh-snapshot 을 주세요.")
        snapshot = old
    else:
        if old and old.get("status") == "ok":
            write_json(rdir / f"latest100.replaced_{_stamp(old.get('captured_at'))}.json", old)
        write_json(snap_path, snapshot)
    # all_videos: latest100 (the kept or new snapshot) wins on conflicts
    snap_by_id = {v["video_id"]: v for v in snapshot.get("videos") or []}
    all_out = []
    for r in all_recs:
        rr = _clean(r, ALL_KEYS)
        if r["video_id"] in snap_by_id:
            s = snap_by_id[r["video_id"]]
            for k in ("url", "title", "published_at", "upload_date", "duration", "view_count", "view_count_checked_at",
                      "kind"):
                rr[k] = s.get(k)
            rr["view_count_source"] = "latest100_snapshot"
            rr["in_latest100"] = True
        else:
            rr["in_latest100"] = False
        all_out.append(rr)
    write_json(rdir / "all_videos.json", {
        "schema": LISTING_SCHEMA, "preset_id": pr.preset_id, "channel_url": channel_url, "captured_at": attempted_at,
        "method": res["method"], "status": status, "blocker": blocker, "n": len(all_out),
        "note": "채널 전체 목록(참고용). 분석 기준은 latest100.json 이며 같은 영상의 값이 다르면 latest100 을 따른다.",
        "videos": all_out})
    exact = [r for r in all_out if r.get("view_count") is not None and r["view_count"] >= threshold
             and r.get("view_count_source") in ("video_metadata", "latest100_snapshot")]
    approx = [r for r in all_out if r.get("view_count") is not None and r["view_count"] >= threshold
              and r.get("view_count_source") == "flat_listing_approx"]
    write_json(rdir / "high_views.json", {
        "schema": HIGH_SCHEMA, "preset_id": pr.preset_id, "threshold": threshold, "checked_at": attempted_at,
        "status": status, "blocker": blocker, "n": len(exact),
        "videos": [{"video_id": r["video_id"], "url": r["url"], "title": r["title"], "view_count": r["view_count"],
                    "view_count_checked_at": r["view_count_checked_at"], "published_at": r["published_at"],
                    "kind": r["kind"], "in_latest100": r["in_latest100"]}
                   for r in sorted(exact, key=lambda r: -r["view_count"])],
        "unverified": [{"video_id": r["video_id"], "view_count_approx": r["view_count"],
                        "reason": "목록 화면의 근사 조회수만 있음(영상 메타데이터 미확인)"} for r in approx]})
    append_jsonl(rdir / "collect_log.jsonl", {"at": attempted_at, "method": res["method"], "status": status,
                                              "blocker": blocker, "n_listing": len(res["listing"]),
                                              "n_latest": len(latest), "snapshot_kept": kept})
    say(f"수집 {status}: 채널 목록 {len(res['listing'])}편, 최신 {len(latest)}편, "
        f"조회수 {threshold:,} 이상(정확) {len(exact)}편, 근사치만 {len(approx)}편")
    return {"status": "kept" if kept else status, "exit_code": 0 if status == "ok" else 4,
            "n_latest": len(latest), "n_all": len(all_out), "n_high": len(exact)}


def _stamp(iso: str | None) -> str:
    return re.sub(r"[^0-9]", "", iso or now_iso())[:14]


def _write_blocked(preset: str, rdir: Path, channel_url: str, method: str, at: str, err: str) -> dict:
    pr = load_preset(preset)
    blocked = {"status": "blocked", "blocker": err, "captured_at": at, "method": method,
               "channel_url": channel_url, "videos": [], "n": 0}
    snap_path = rdir / "latest100.json"
    old = read_json(snap_path)
    if old and old.get("status") in ("ok", "partial"):
        warn("이전 스냅샷을 그대로 둡니다(이번 시도는 차단됨).")
    else:
        write_json(snap_path, {"schema": SNAPSHOT_SCHEMA, "preset_id": pr.preset_id,
                               "latest_n": int(pr.get("reference.latest_n")), **blocked,
                               "notes": ["차단으로 목록을 한 건도 받지 못함 — 이 파일은 차단 사실의 기록이며 기준 목록이 아님"]})
    for name, schema in (("all_videos", LISTING_SCHEMA), ("high_views", HIGH_SCHEMA)):
        p = rdir / f"{name}.json"
        o = read_json(p)
        if not (o and o.get("status") in ("ok", "partial")):
            extra = {"threshold": int(pr.get("reference.high_view_threshold")), "checked_at": at,
                     "unverified": []} if name == "high_views" else {}
            write_json(p, {"schema": schema, "preset_id": pr.preset_id, **blocked, **extra})
    append_jsonl(rdir / "collect_log.jsonl", {"at": at, "method": method, "status": "blocked", "blocker": err[:2000]})
    warn(f"레퍼런스 채널 목록을 가져오지 못했습니다(차단): {err[:600]}")
    warn("→ 목록·게시일·조회수를 한 건도 확보하지 못해 latest100.json 에 'blocked' 로 기록했습니다. "
         "네트워크가 열린 환경에서 `python -m shortkit ref collect` 를 다시 실행하세요.")
    return {"status": "blocked", "exit_code": 3, "blocker": err}
