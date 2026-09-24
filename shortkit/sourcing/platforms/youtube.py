"""YouTube adapter (yt-dlp).

search: ``ytsearchN:<q>`` (relevance) or ``ytsearchdateN:<q>`` (newest first, ``recent_only``) as a
FLAT listing, then per-item full metadata (documented yt-dlp info-dict fields: ``view_count``,
``timestamp``/``upload_date``, ``uploader``, ``channel``, ``duration``, ``width``/``height``;
``like_count`` is kept separately and never used as views).

Views come only from the per-item ``view_count``; a listing entry whose full metadata could
not be fetched keeps ``views=None`` / ``views_source='unavailable'`` (the approximate count
text in search listings is not used).

Not live-tested on the build machine (youtube.com / googlevideo.com blocked by network policy).
"""
from __future__ import annotations

from .. import platforms as base   # network calls go through base.* so tests can replace them
from . import OK, SearchResult, access, classify_error, common_from_info, float_or_none

PLATFORM = "youtube"
VIEW_FIELDS = ("view_count",)


def normalize(info: dict) -> dict:
    c = common_from_info(info, PLATFORM, VIEW_FIELDS)
    if not c["url"] and c["platform_id"]:
        c["url"] = f"https://www.youtube.com/watch?v={c['platform_id']}"
    c["extra"]["live_status"] = info.get("live_status")
    c["extra"]["is_short_url"] = "/shorts/" in str(info.get("original_url") or info.get("webpage_url") or "")
    return c


def normalize_flat(entry: dict, acc: dict) -> dict:
    """Listing entry only (full metadata failed): identity + title, no views/date."""
    vid = str(entry.get("id") or "")
    url = entry.get("url") or (f"https://www.youtube.com/watch?v={vid}" if vid else None)
    if url and not str(url).startswith("http") and vid:
        url = f"https://www.youtube.com/watch?v={vid}"
    return {
        "platform": PLATFORM, "platform_id": vid, "url": url, "title": entry.get("title"),
        "description": None, "uploader": entry.get("uploader") or entry.get("channel"),
        "uploader_id": entry.get("uploader_id") or entry.get("channel_id"),
        "uploader_url": entry.get("uploader_url") or entry.get("channel_url"),
        "channel": entry.get("channel"), "channel_id": entry.get("channel_id"),
        "views": None, "views_source": "unavailable", "views_field": None,
        "views_note": "개별 메타데이터를 받지 못해 조회수 미확인: " + acc.get("platform_status", "?"),
        "likes": None, "comments": None, "published_at": None, "published_at_source": None,
        "duration": float_or_none(entry.get("duration")), "width": None, "height": None, "fps": None,
        "tags": [], "original_url": None, "original_author_hint": None,
        "extra": {"listing_only": True}, "_item_access": acc,
    }


def search(query: str, limit: int = 10, recent_only: bool = False) -> SearchResult:
    if query.strip().startswith(("http://", "https://")):
        return fetch_url(query.strip())
    prefix = "ytsearchdate" if recent_only else "ytsearch"
    req = f"{prefix}{int(limit)}:{query}"
    res = SearchResult(platform=PLATFORM, query=query, mode="keyword", request=req, access=access(OK))
    try:
        listing = base.ytdlp_extract(req, flat=True)
    except Exception as e:  # noqa: BLE001 - every failure is recorded with its exact text
        res.access = classify_error(e)
        return res.done()
    entries = [e for e in (listing or {}).get("entries") or [] if isinstance(e, dict)][: int(limit)]
    for e in entries:
        url = e.get("url") or e.get("webpage_url") or f"https://www.youtube.com/watch?v={e.get('id')}"
        if not str(url).startswith("http"):
            url = f"https://www.youtube.com/watch?v={e.get('id')}"
        try:
            info = base.ytdlp_extract(url)
            c = normalize(info)
            c["_item_access"] = access(OK)
        except Exception as ex:  # noqa: BLE001
            acc = classify_error(ex)
            res.item_errors.append({"id": e.get("id"), "url": url, **acc})
            c = normalize_flat(e, acc)
        res.candidates.append(c)
    if res.item_errors:
        res.notes.append(f"목록은 받았으나 {len(res.item_errors)}/{len(entries)} 항목의 개별 메타데이터 실패")
    return res.done()


def fetch_url(url: str) -> SearchResult:
    res = SearchResult(platform=PLATFORM, query=url, mode="url", request=url, access=access(OK))
    try:
        info = base.ytdlp_extract(url)
    except Exception as e:  # noqa: BLE001
        res.access = classify_error(e)
        return res.done()
    c = normalize(info)
    c["_item_access"] = access(OK)
    res.candidates.append(c)
    return res.done()
