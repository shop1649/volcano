"""TikTok adapter (yt-dlp).

Query forms:
  - ``https://www.tiktok.com/@user/video/<id>``   direct video URL (also vm.tiktok.com short links)
  - ``@user`` or ``https://www.tiktok.com/@user``  a user's feed (yt-dlp ``tiktok:user``)
  - anything else = keyword -> hashtag ``https://www.tiktok.com/tag/<tag>`` (yt-dlp ``tiktok:tag``)

Views come ONLY from play/view count fields (yt-dlp maps TikTok ``playCount``/``play_count`` to
``view_count``; ``play_count`` is also accepted).  ``like_count`` (TikTok "digg") is kept as likes
and never used as views.  TikTok has no server-side date filter: ``recent_only`` drops items whose
published date is known to be older than the recency window (unknown dates are kept, labelled).

Not live-tested on the build machine (tiktok.com blocked by network policy).  Note: yt-dlp
2026.08.19 marks ``tiktok:tag`` as not working (``_WORKING=False``), and TikTok has no keyword search in
yt-dlp at all (keywords go through the hashtag page).  When a broken extractor returns an EMPTY listing the
platform status is ``error`` (not 'ok, 0 results'), with the working routes in the note: ``@account``
(``tiktok:user``) and direct video URLs (``source add-url``).
"""
from __future__ import annotations

import re
import urllib.parse

from .. import platforms as base   # network calls go through base.* so tests can replace them
from . import OK, SearchResult, access, classify_error, common_from_info

PLATFORM = "tiktok"
VIEW_FIELDS = ("view_count", "play_count")


def to_hashtag(keyword: str) -> str:
    """'#Funny Cats' -> 'funnycats' (TikTok tags have no spaces/punctuation)."""
    k = keyword.strip().lstrip("#")
    k = re.sub(r"[\s\-]+", "", k)
    k = re.sub(r"[^\w]", "", k, flags=re.UNICODE)
    return k.lower()


def build_request(query: str) -> tuple[str, str]:
    q = query.strip()
    if q.startswith("http://") or q.startswith("https://"):
        if re.search(r"/video/\d+", q) or re.search(r"(?:vm|vt)\.tiktok\.com/|tiktok\.com/t/", q):
            return "url", q
        if "/tag/" in q:
            return "hashtag", q
        if re.search(r"tiktok\.com/@[\w.-]+/?(?:$|[?#])", q):
            return "user", q
        return "url", q
    if q.startswith("@"):
        return "user", f"https://www.tiktok.com/@{q[1:]}"
    tag = to_hashtag(q)
    return "hashtag", f"https://www.tiktok.com/tag/{urllib.parse.quote(tag)}"


def normalize(info: dict) -> dict:
    c = common_from_info(info, PLATFORM, VIEW_FIELDS)
    if not c["url"] and c["platform_id"]:
        up = info.get("uploader") or info.get("uploader_id") or "_"
        c["url"] = f"https://www.tiktok.com/@{up}/video/{c['platform_id']}"
    c["extra"]["repost_count"] = info.get("repost_count")
    c["extra"]["track"] = info.get("track")
    c["extra"]["artists"] = info.get("artists") or info.get("artist")
    return c


def search(query: str, limit: int = 10, recent_only: bool = False) -> SearchResult:
    mode, url = build_request(query)
    res = SearchResult(platform=PLATFORM, query=query, mode=mode, request=url, access=access(OK))
    broken = base.broken_extractor_note(url)
    if broken:
        res.notes.append(broken)
    if mode == "url":
        return _single(res, url)
    try:
        listing = base.ytdlp_extract(url, flat=True, cookie=base.cookiefile(PLATFORM), playlistend=int(limit))
    except Exception as e:  # noqa: BLE001
        res.access = classify_error(e)
        if broken:
            res.access["note"] = (res.access["note"] + " | " + broken)[:base.NOTE_MAX]
        return res.done()
    entries = [e for e in (listing or {}).get("entries") or [] if isinstance(e, dict)][: int(limit)]
    if not entries and broken:
        res.access = base.broken_listing_access(PLATFORM, broken, mode)
        return res.done()
    for e in entries:
        item_url = e.get("webpage_url") or e.get("url")
        if e.get("view_count") is not None and e.get("timestamp") and not e.get("_type") == "url":
            info = e                      # the listing already carried full metadata
        else:
            try:
                info = base.ytdlp_extract(item_url, cookie=base.cookiefile(PLATFORM))
            except Exception as ex:  # noqa: BLE001
                acc = classify_error(ex)
                res.item_errors.append({"id": e.get("id"), "url": item_url, **acc})
                continue
        c = normalize(info)
        c["_item_access"] = access(OK)
        res.candidates.append(c)
    if res.item_errors:
        res.notes.append(f"목록은 받았으나 {len(res.item_errors)}/{len(entries)} 항목의 개별 메타데이터 실패")
    if recent_only:
        base.drop_known_old(res)
    return res.done()


def _single(res: SearchResult, url: str) -> SearchResult:
    try:
        info = base.ytdlp_extract(url, cookie=base.cookiefile(PLATFORM))
    except Exception as e:  # noqa: BLE001
        res.access = classify_error(e)
        return res.done()
    c = normalize(info)
    c["_item_access"] = access(OK)
    res.candidates.append(c)
    return res.done()


def fetch_url(url: str) -> SearchResult:
    res = SearchResult(platform=PLATFORM, query=url, mode="url", request=url, access=access(OK))
    return _single(res, url)
