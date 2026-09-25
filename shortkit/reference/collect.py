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
  latest100.json   the fixed baseline.  An existing ``status: ok`` OR ``status: partial`` snapshot is
                   NEVER replaced unless ``--refresh-snapshot`` is given (a replaced one is archived as
                   ``latest100.replaced_<time>.json``); a failed attempt never replaces it.  A partial
                   snapshot stores ``failures`` / ``missing_members`` (metadata failures among the newest
                   N of a tab, with the reason); the next ``ref collect`` re-queries only those ids and
                   COMPLETES the same snapshot (membership as of its ``captured_at``; each step is logged
                   under ``completions`` and the previous version archived as
                   ``latest100.completed_<time>.json``).
  all_videos.json  whole-channel listing, reference only.  Stable fields (url, title, published_at,
                   duration, kind) of snapshot members come from latest100; TIME-VARYING fields
                   (view_count, view_count_checked_at) are this run's freshest values, the snapshot's
                   count is kept apart as ``view_count_at_snapshot``.
  high_views.json  EVERY channel video with an exact view_count >= reference.high_view_threshold
                   (+checked_at).  With yt-dlp, per-video metadata is fetched for the newest N of each
                   tab AND for every other listing entry whose approximate (flat) count is >= 90 % of
                   the threshold or unknown, so the set is exact over the whole channel; candidates whose
                   metadata could not be read are listed under ``unverified`` with the reason and the
                   file is ``status: partial``.
  meta/<id>.json   per-video metadata (title, description, tags) used by `ref trace` (latest N of each
                   tab + every high-view candidate).
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
from .common import BASIS_STATUSES, SNAPSHOT_SCHEMA, reference_dir, safe_id, say, scrub, warn

LISTING_SCHEMA = "shortkit.ref_channel_listing/1"
HIGH_SCHEMA = "shortkit.ref_high_views/1"
API_BASE = "https://www.googleapis.com/youtube/v3/"
TABS = ("shorts", "videos")
HV_MARGIN = 0.9          # flat-listing counts are rounded ("79만", "1.2M"): candidates from 90 % of the threshold

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
               extract: Callable[..., dict] | None = None, threshold: int | None = None,
               extra_ids: list[str] | tuple = ()) -> dict:
    """Listing + per-video metadata with yt-dlp.  Raises Blocked when the channel is unreachable.

    Metadata is fetched for (1) the newest ``latest_n`` of each tab, (2) ``extra_ids`` (members a
    partial snapshot is missing) and (3) when ``threshold`` is given, every other listing entry whose
    flat (approximate) view count is >= HV_MARGIN x threshold or unknown -- so the high-view set is exact
    over the whole channel.  Failures of (1)/(2) go to ``failures``, of (3) to ``hv_failures``."""
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
            tabs[tab] = {"status": kind, "error": scrub(msg)}
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
    for vid in extra_ids:
        if vid not in want:
            want.append(vid)
    # high-view candidates outside the newest N: approximate count near/above the threshold, or unknown
    hv_want: list[str] = []
    if threshold:
        cands = [(v, r.get("view_count_flat")) for v, r in listing.items() if v not in want]
        cands = [(v, c) for v, c in cands if c is None or c >= HV_MARGIN * threshold]
        hv_want = [v for v, _ in sorted(cands, key=lambda x: (x[1] is None, -(x[1] or 0), x[0]))]
    hv_not_fetched: list[str] = []
    if max_meta is not None:
        want = want[:max_meta]
        room = max(0, max_meta - len(want))
        hv_want, hv_not_fetched = hv_want[:room], hv_want[room:]
    meta: dict[str, dict] = {}
    failures: list[dict] = []
    hv_failures: list[dict] = []
    blocked_n = 0
    rank_of = {v: (tab, i + 1) for tab in TABS for i, v in enumerate(order.get(tab, []))}
    for group, ids in (("latest", want), ("high_views", hv_want)):
        for vid in ids:
            url = (listing.get(vid) or {}).get("url") or f"https://www.youtube.com/watch?v={vid}"
            try:
                info = extract(f"https://www.youtube.com/watch?v={vid}", False, cookies)
            except Exception as e:
                msg = f"{type(e).__name__}: {e}"
                k = classify_error(msg)
                blocked_n += k == "blocked"
                tab, rk = rank_of.get(vid, (None, None))
                (failures if group == "latest" else hv_failures).append(
                    {"video_id": vid, "kind": k, "error": scrub(msg)[:500], "tab": tab, "tab_rank": rk,
                     "at": now_iso(), "view_count_flat": (listing.get(vid) or {}).get("view_count_flat")})
                continue
            meta[vid] = {"checked_at": now_iso(), "info": info, "url": url}
    if want and not meta and blocked_n:
        raise Blocked(f"영상 메타데이터 {len(want)}건 모두 실패: {failures[0]['error']}")
    return {"tabs": tabs, "listing": listing, "meta": meta, "failures": failures, "order": order,
            "hv_candidates": hv_want + hv_not_fetched, "hv_failures": hv_failures, "hv_not_fetched": hv_not_fetched,
            "method": f"yt-dlp {_ydl_version()} (extract_flat /shorts,/videos + per-video metadata: newest "
                      f"{latest_n}/tab + every high-view candidate)"}


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
# fields of a snapshot member that do not change over time: latest100 wins on these in all_videos
STABLE_KEYS = ("url", "title", "published_at", "upload_date", "duration", "kind")


def _member_sort(v: dict) -> float:
    ts = _ts_from_iso(v.get("published_at")) if v.get("published_at") else None
    if ts is None:
        ts = _date_sort(v.get("upload_date"))
    return float(ts) if ts is not None else float("-inf")


def missing_members_of(res: dict, latest_ids: set[str]) -> list[dict]:
    """Metadata failures among the newest N of a tab (possible snapshot members), with the reason."""
    return [{"video_id": f["video_id"], "tab": f.get("tab"), "tab_rank": f.get("tab_rank"), "kind": f.get("kind"),
             "error": f.get("error"), "at": f.get("at"),
             "url": (res["listing"].get(f["video_id"]) or {}).get("url")}
            for f in res.get("failures") or [] if f["video_id"] not in latest_ids]


def complete_snapshot(old: dict, res: dict, latest_n: int) -> tuple[dict, dict | None]:
    """Complete a PARTIAL snapshot in place: members whose metadata failed at capture time are
    re-queried (``res`` holds this run's metadata for them); a recovered video published no later than
    ``captured_at`` enters the list when it ranks within the newest ``latest_n`` as of that time (the
    last-ranked member then drops out).  Membership stays defined by the original capture time.
    -> (snapshot, completion record or None when nothing changed)."""
    missing = [m for m in old.get("missing_members") or [] if isinstance(m, dict) and m.get("video_id")]
    if not missing:
        return old, None
    cap_ts = _ts_from_iso(old.get("captured_at"))
    recovered, still, non_members = [], [], []
    fails = {f["video_id"]: f for f in res.get("failures") or []}
    for m in missing:
        vid = m["video_id"]
        if vid in res.get("meta", {}):
            base = res["listing"].get(vid) or {"url": m.get("url") or f"https://www.youtube.com/watch?v={vid}",
                                               "kind": {"shorts": "short", "videos": "video"}.get(m.get("tab"))}
            r = _record_from_meta(vid, base, res["meta"][vid])
            if r["_sort"] is None:
                still.append({**m, "error": "게시 시각을 받지 못함", "at": now_iso()})
            elif cap_ts is not None and r["_sort"] > cap_ts:
                non_members.append({"video_id": vid, "reason": "고정 시각 이후 게시(구성원 아님)"})
            else:
                recovered.append(_clean(r, LATEST_KEYS))
        else:
            f = fails.get(vid)
            still.append({**m, "error": (f or {}).get("error") or "이번 시도에서 조회되지 않음",
                          "kind": (f or {}).get("kind", m.get("kind")), "at": now_iso()})
    if not recovered and not non_members:
        new = dict(old)
        new["missing_members"] = still
        return new, {"at": now_iso(), "recovered": [], "dropped": [], "resolved_non_members": [],
                     "still_missing": [m["video_id"] for m in still], "changed": False}
    videos = [dict(v) for v in old.get("videos") or []] + recovered
    videos.sort(key=lambda v: (-_member_sort(v), v["video_id"]))
    keep, dropped = videos[:latest_n], videos[latest_n:]
    for i, v in enumerate(keep, 1):
        v["rank"] = i
    rec_ids = {v["video_id"] for v in recovered}
    non_members += [{"video_id": v["video_id"], "reason": f"다시 조회 결과 최신 {latest_n}편 밖"} for v in dropped
                    if v["video_id"] in rec_ids]
    comp = {"at": now_iso(), "recovered": [v["video_id"] for v in keep if v["video_id"] in rec_ids],
            "dropped": [v["video_id"] for v in dropped if v["video_id"] not in rec_ids],
            "resolved_non_members": non_members, "still_missing": [m["video_id"] for m in still], "changed": True}
    new = dict(old)
    new.update({"videos": keep, "n": len(keep), "missing_members": still,
                "completions": list(old.get("completions") or []) + [comp]})
    if not still and (len(keep) >= latest_n or not old.get("partial_reason_listing_short")):
        new["status"] = "ok"
        new["blocker"] = None
    else:
        new["blocker"] = (f"구성원 후보 {len(still)}편의 메타데이터를 아직 받지 못함: "
                          + ", ".join(f"{m['video_id']}({str(m.get('error'))[:80]})" for m in still[:5]))
    return new, comp


def collect(preset: str = "joshuamagazine", method: str = "auto", refresh_snapshot: bool = False,
            cookies: str | None = None, max_meta: int | None = None,
            extract: Callable[..., dict] | None = None, api_getter: Callable[[str], dict] | None = None) -> dict:
    """Run a collection attempt and write the reference files.  Returns a summary dict with
    ``status`` (ok|partial|blocked|kept), ``snapshot_status`` and ``exit_code`` (0 only when the
    snapshot is ok AND the high-view set is exact)."""
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
    snap_path = rdir / "latest100.json"
    old = read_json(snap_path)
    kept = bool(old and old.get("status") in BASIS_STATUSES and not refresh_snapshot)
    extra_ids = [m["video_id"] for m in (old or {}).get("missing_members") or []
                 if isinstance(m, dict) and m.get("video_id")] if kept else []
    try:
        if method == "api":
            if not key:
                raise Blocked("YOUTUBE_API_KEY 환경 변수가 없음")
            res = list_api(handle, channel_id, latest_n, key, getter=api_getter)
        else:
            res = list_ytdlp(channel_url, latest_n, cookies=cookies, max_meta=max_meta, extract=extract,
                             threshold=threshold, extra_ids=extra_ids)
    except Blocked as e:
        label = f"yt-dlp {_ydl_version()}" if method == "ytdlp" else "youtube-data-api-v3"
        return _write_blocked(preset, rdir, channel_url, label, attempted_at, scrub(str(e)))
    latest, all_recs, notes = build_records(res, latest_n)
    latest_ids = {r["video_id"] for r in latest}
    status = "ok"
    blocker = None
    listing_short = False
    missing = missing_members_of(res, latest_ids)
    if missing:
        status = "partial"
        blocker = (f"메타데이터 실패 {len(missing)}건(최신 {latest_n}편 후보): "
                   + "; ".join(f"{m['video_id']}: {str(m['error'])[:160]}" for m in missing[:3]))
    if len(latest) < latest_n:
        n_total = len(res["listing"])
        if n_total >= latest_n or missing:
            status = "partial"
            listing_short = True
            blocker = blocker or f"게시 시각이 확인된 영상이 {len(latest)}편뿐(목록 {n_total}편)"
        else:
            notes.append(f"채널 전체 영상이 {n_total}편뿐이라 최신 {latest_n}편을 채우지 못함")
    # per-video metadata (descriptions for `ref trace`)
    for r in all_recs:
        if r.get("_meta"):
            write_json(rdir / "meta" / f"{r['video_id']}.json", {"video_id": r["video_id"], **r["_meta"],
                                                                  "source": res["method"]})
    snapshot = {"schema": SNAPSHOT_SCHEMA, "preset_id": pr.preset_id, "channel_url": channel_url,
                "captured_at": attempted_at, "method": res["method"], "status": status, "blocker": blocker,
                "latest_n": latest_n, "n": len(latest), "sort": "published_at desc (timestamp; upload_date if no time)",
                "tabs": res.get("tabs"), "notes": notes, "failures": res.get("failures") or [],
                "missing_members": missing, "partial_reason_listing_short": listing_short,
                "videos": [_clean(r, LATEST_KEYS) for r in latest]}
    completion = None
    if kept:
        snapshot, completion = complete_snapshot(old, res, latest_n)
        if completion and completion.get("changed"):
            write_json(rdir / f"latest100.completed_{_stamp(attempted_at)}.json", old)
            write_json(snap_path, snapshot)
            say(f"부분(partial) 스냅샷을 같은 고정 시각({old.get('captured_at')}) 기준으로 보완했습니다: 복구 "
                f"{len(completion['recovered'])}편, 빠짐 {len(completion['dropped'])}편, 아직 못 받음 "
                f"{len(completion['still_missing'])}편 → 상태 {snapshot.get('status')}")
        elif completion:
            write_json(snap_path, snapshot)          # refreshed failure reasons only
        say(f"기존 최신 {latest_n}편 스냅샷(고정 시각 {old.get('captured_at')}, 상태 {snapshot.get('status')})을 "
            "유지합니다. 새로 고정하려면 --refresh-snapshot 을 주세요.")
    else:
        if old and old.get("status") in BASIS_STATUSES:
            write_json(rdir / f"latest100.replaced_{_stamp(old.get('captured_at'))}.json", old)
        write_json(snap_path, snapshot)
    # all_videos: latest100 wins on STABLE fields; view counts are this run's freshest values
    snap_by_id = {v["video_id"]: v for v in snapshot.get("videos") or []}
    all_out = []
    for r in all_recs:
        rr = _clean(r, ALL_KEYS)
        if r["video_id"] in snap_by_id:
            s = snap_by_id[r["video_id"]]
            for k in STABLE_KEYS:
                rr[k] = s.get(k)
            rr["view_count_at_snapshot"] = s.get("view_count")
            rr["view_count_at_snapshot_checked_at"] = s.get("view_count_checked_at")
            if rr.get("view_count") is None and s.get("view_count") is not None:
                rr.update(view_count=s.get("view_count"), view_count_checked_at=s.get("view_count_checked_at"),
                          view_count_source="latest100_snapshot")
            rr["in_latest100"] = True
        else:
            rr["in_latest100"] = False
        all_out.append(rr)
    write_json(rdir / "all_videos.json", {
        "schema": LISTING_SCHEMA, "preset_id": pr.preset_id, "channel_url": channel_url, "captured_at": attempted_at,
        "method": res["method"], "status": status, "blocker": blocker, "n": len(all_out),
        "note": "채널 전체 목록(참고용). 분석 기준은 latest100.json 이며 같은 영상의 고정 필드(주소·제목·게시일·길이·종류)가 다르면 "
                "latest100 을 따른다. 조회수는 시간에 따라 변하므로 이번 수집의 최신값(view_count, 확인일)이고 스냅샷 당시 값은 "
                "view_count_at_snapshot.",
        "videos": all_out})
    hv = high_view_sets(all_out, res, threshold)
    hv_status = "ok" if status in ("ok", "partial") and not hv["unverified"] else "partial"
    hv_blocker = None
    if hv["unverified"]:
        hv_blocker = (f"조회수 {threshold:,} 이상일 수 있는 영상 {len(hv['unverified'])}편의 정확한 조회수를 확인하지 못함: "
                      + ", ".join(f"{u['video_id']}({u['reason'][:60]})" for u in hv["unverified"][:5]))
    write_json(rdir / "high_views.json", {
        "schema": HIGH_SCHEMA, "preset_id": pr.preset_id, "threshold": threshold, "checked_at": attempted_at,
        "status": hv_status, "blocker": hv_blocker, "n": len(hv["exact"]),
        "method": ("yt-dlp: 각 탭 최신 N편 + 목록 근사 조회수가 기준의 90% 이상이거나 없는 모든 영상의 영상별 메타데이터"
                   if method != "api" else "YouTube Data API v3 videos.list statistics.viewCount (채널 전체)"),
        "candidates_checked": len(res.get("hv_candidates") or []),
        "videos": [{"video_id": r["video_id"], "url": r["url"], "title": r["title"], "view_count": r["view_count"],
                    "view_count_checked_at": r["view_count_checked_at"], "view_count_source": r.get("view_count_source"),
                    "view_count_at_snapshot": r.get("view_count_at_snapshot"), "published_at": r["published_at"],
                    "kind": r["kind"], "in_latest100": r["in_latest100"]}
                   for r in sorted(hv["exact"], key=lambda r: -r["view_count"])],
        "unverified": hv["unverified"]})
    append_jsonl(rdir / "collect_log.jsonl", {"at": attempted_at, "method": res["method"], "status": status,
                                              "blocker": blocker, "n_listing": len(res["listing"]),
                                              "n_latest": len(latest), "snapshot_kept": kept,
                                              "snapshot_status": snapshot.get("status"),
                                              "completion": completion, "n_high": len(hv["exact"]),
                                              "n_high_unverified": len(hv["unverified"])})
    say(f"수집 {status}: 채널 목록 {len(res['listing'])}편, 최신 {len(latest)}편, "
        f"조회수 {threshold:,} 이상(정확) {len(hv['exact'])}편, 확인 못 함 {len(hv['unverified'])}편")
    ok = snapshot.get("status") == "ok" and hv_status == "ok"
    return {"status": "kept" if kept else status, "snapshot_status": snapshot.get("status"),
            "exit_code": 0 if ok else 4, "n_latest": len(latest), "n_all": len(all_out), "n_high": len(hv["exact"]),
            "n_high_unverified": len(hv["unverified"])}


def high_view_sets(all_out: list[dict], res: dict, threshold: int) -> dict:
    """{"exact": records with a metadata (or earlier exact snapshot) count >= threshold,
        "unverified": entries that may be >= threshold but whose exact count was not read (with the reason)}."""
    exact, unverified = [], []
    hv_fail = {f["video_id"]: f for f in res.get("hv_failures") or []}
    fail = {f["video_id"]: f for f in res.get("failures") or []}
    not_fetched = set(res.get("hv_not_fetched") or [])
    flat = {v: (b or {}).get("view_count_flat") for v, b in res.get("listing", {}).items()}
    for r in all_out:
        vc, src = r.get("view_count"), r.get("view_count_source")
        if src in ("video_metadata", "latest100_snapshot") and vc is not None and vc >= threshold:
            exact.append(r)            # (view counts do not go down: an earlier exact count >= threshold stays high)
            continue
        if src == "video_metadata":
            continue                   # exact and below the threshold
        fl = flat.get(r["video_id"])
        if fl is not None and fl < HV_MARGIN * threshold:
            continue                   # far below the threshold even allowing for rounding
        vid = r["video_id"]
        f = hv_fail.get(vid) or fail.get(vid)
        reason = (f"영상 메타데이터 조회 실패: {str(f.get('error'))[:200]}" if f else
                  "메타데이터 조회 상한(--max-meta)으로 조회하지 않음" if vid in not_fetched else
                  "목록 화면의 근사 조회수만 있음(영상 메타데이터 미확인)" if fl is not None else
                  "조회수 정보 없음(영상 메타데이터 미확인)")
        unverified.append({"video_id": vid, "view_count_approx": fl, "reason": reason,
                           "url": r.get("url"), "kind": r.get("kind")})
    return {"exact": exact, "unverified": unverified}


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
