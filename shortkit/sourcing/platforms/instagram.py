"""Instagram adapter (yt-dlp).

Query forms:
  - post / reel URL (``/p/<code>``, ``/reel/<code>``, ``/reels/<code>``, ``/tv/<code>``) -> yt-dlp ``Instagram``
  - ``#tag`` / keyword -> ``https://www.instagram.com/explore/tags/<tag>/`` (yt-dlp ``instagram:tag``)
  - ``@user`` -> ``https://www.instagram.com/<user>/`` (yt-dlp ``instagram:user``)

Hashtag / account listings need a logged-in session.  Without a cookies file configured in
``local.yaml`` (``sourcing.cookies.instagram``) the adapter returns ``login_required`` WITHOUT a
network request.  Views are taken only if the metadata provides them (``view_count`` /
``play_count``); likes stay likes.

Not live-tested on the build machine (instagram.com blocked by network policy).  yt-dlp 2026.08.19 marks
``instagram:user`` (account listing) as not working: an EMPTY listing from it is recorded as ``error``, not as
'ok, 0 results'.
"""
from __future__ import annotations

import re
import urllib.parse

from .. import platforms as base   # network calls go through base.* so tests can replace them
from . import LOGIN_REQUIRED, OK, SearchResult, access, classify_error, common_from_info

PLATFORM = "instagram"
VIEW_FIELDS = ("view_count", "play_count")
_POST_RE = re.compile(r"instagram\.com(?:/[^/?#]+)?/(?:p|tv|reels?)/[^/?#&]+")


def to_hashtag(keyword: str) -> str:
    k = keyword.strip().lstrip("#")
    k = re.sub(r"[\s\-]+", "", k)
    return re.sub(r"[^\w]", "", k, flags=re.UNICODE).lower()


def build_request(query: str) -> tuple[str, str]:
    q = query.strip()
    if q.startswith("http://") or q.startswith("https://"):
        if _POST_RE.search(q):
            return "url", q
        if "/explore/tags/" in q:
            return "hashtag", q
        return "user", q
    if q.startswith("@"):
        return "user", f"https://www.instagram.com/{q[1:]}/"
    return "hashtag", f"https://www.instagram.com/explore/tags/{urllib.parse.quote(to_hashtag(q))}/"


def normalize(info: dict) -> dict:
    c = common_from_info(info, PLATFORM, VIEW_FIELDS)
    if c["views"] is None:
        c["views_note"] = "Instagram 메타데이터가 조회수를 제공하지 않음(좋아요는 조회수로 쓰지 않음)"
    return c


def search(query: str, limit: int = 10, recent_only: bool = False) -> SearchResult:
    mode, url = build_request(query)
    res = SearchResult(platform=PLATFORM, query=query, mode=mode, request=url, access=access(OK))
    cookie = base.cookiefile(PLATFORM)
    if mode == "url":
        return _single(res, url, cookie)
    if not cookie:
        res.access = access(LOGIN_REQUIRED,
                            "Instagram 해시태그/계정 목록은 로그인 세션이 필요함. local.yaml 의 "
                            "sourcing.cookies.instagram 에 cookies.txt 경로를 설정해야 함 (네트워크 요청 안 함)")
        return res.done()
    broken = base.broken_extractor_note(url)
    if broken:
        res.notes.append(broken)
    try:
        listing = base.ytdlp_extract(url, flat=True, cookie=cookie, playlistend=int(limit))
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
        try:
            info = base.ytdlp_extract(item_url, cookie=cookie)
        except Exception as ex:  # noqa: BLE001
            res.item_errors.append({"id": e.get("id"), "url": item_url, **classify_error(ex)})
            continue
        c = normalize(info)
        c["_item_access"] = access(OK)
        res.candidates.append(c)
    if recent_only:
        base.drop_known_old(res)
    return res.done()


def _single(res: SearchResult, url: str, cookie: str | None) -> SearchResult:
    try:
        info = base.ytdlp_extract(url, cookie=cookie)
    except Exception as e:  # noqa: BLE001
        res.access = classify_error(e)
        return res.done()
    c = normalize(info)
    c["_item_access"] = access(OK)
    res.candidates.append(c)
    return res.done()


def fetch_url(url: str) -> SearchResult:
    res = SearchResult(platform=PLATFORM, query=url, mode="url", request=url, access=access(OK))
    return _single(res, url, base.cookiefile(PLATFORM))
