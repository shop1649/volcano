"""Reddit adapter (public JSON listing, no login).

search: ``GET https://www.reddit.com/search.json?q=<q>&sort=top&t=month&type=link&limit=N&raw_json=1``
with a descriptive custom User-Agent (Reddit API rules), keeping only video posts:
``is_video`` / ``media.reddit_video`` (Reddit-hosted, v.redd.it) or ``post_hint`` ``rich:video`` /
known video hosts (external link -> ``original_url``).  ``recent_only`` uses ``sort=new&t=week``.

Reddit exposes NO public view counts: ``views`` is always ``None`` with ``views_source='unavailable'``
(the listing's ``view_count`` field is null for everyone and is ignored).  The vote ``score`` is
stored separately as ``reddit_score`` and is NEVER converted to or used as views.

Documented listing fields used: kind ``t3``; data.id, title, selftext, author, subreddit, permalink,
url / url_overridden_by_dest, domain, created_utc, score, upvote_ratio, num_comments, is_video,
media/secure_media.reddit_video{width,height,duration,fallback_url}, post_hint, crosspost_parent_list.

Not live-tested on the build machine (reddit.com blocked by network policy).
"""
from __future__ import annotations

import urllib.parse

from .. import platforms as base   # network calls go through base.* so tests can replace them
from . import OK, SearchResult, access, classify_error, epoch_to_iso, float_or_none, int_or_none

PLATFORM = "reddit"
SEARCH_URL = "https://www.reddit.com/search.json"
VIDEO_HOSTS = ("v.redd.it", "youtube.com", "youtu.be", "streamable.com", "tiktok.com", "instagram.com",
               "gfycat.com", "clips.twitch.tv", "twitter.com", "x.com", "vimeo.com")
VIEWS_NOTE = "Reddit 은 공개 조회수를 제공하지 않음(점수 reddit_score 는 조회수가 아님)"


def build_url(query: str, limit: int = 10, recent_only: bool = False) -> str:
    params = {
        "q": query,
        "sort": "new" if recent_only else "top",
        "t": "week" if recent_only else "month",
        "type": "link",
        "limit": str(min(100, max(25, int(limit) * 4))),   # over-fetch: only video posts are kept
        "raw_json": "1",
    }
    return f"{SEARCH_URL}?{urllib.parse.urlencode(params)}"


def _reddit_video(p: dict) -> dict:
    for k in ("secure_media", "media"):
        rv = (p.get(k) or {}).get("reddit_video") if isinstance(p.get(k), dict) else None
        if rv:
            return rv
    return {}


def is_video_post(p: dict) -> bool:
    if p.get("is_video") or _reddit_video(p):
        return True
    if p.get("post_hint") in ("hosted:video", "rich:video"):
        return True
    dom = str(p.get("domain") or "").lower()
    return any(dom == h or dom.endswith("." + h) for h in VIDEO_HOSTS)


def normalize_post(p: dict) -> dict:
    rv = _reddit_video(p)
    hosted = bool(p.get("is_video") or rv)
    permalink = p.get("permalink") or ""
    url = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else (permalink or None)
    external = None if hosted else (p.get("url_overridden_by_dest") or p.get("url"))
    xpost = (p.get("crosspost_parent_list") or [None])[0] or {}
    hint = None
    if xpost:
        hint = {"name": xpost.get("author"), "basis": "crosspost_parent",
                "url": f"https://www.reddit.com{xpost.get('permalink')}" if xpost.get("permalink") else None}
    return {
        "platform": PLATFORM,
        "platform_id": str(p.get("id") or ""),
        "url": url,
        "title": p.get("title"),
        "description": (p.get("selftext") or "")[:4000] or None,
        "uploader": p.get("author"),
        "uploader_id": p.get("author_fullname"),
        "uploader_url": f"https://www.reddit.com/user/{p['author']}" if p.get("author") else None,
        "channel": f"r/{p['subreddit']}" if p.get("subreddit") else None,
        "channel_id": p.get("subreddit_id"),
        "views": None,                      # Reddit has no public view counts -- never derived from score
        "views_source": "unavailable",
        "views_field": None,
        "views_note": VIEWS_NOTE,
        "likes": None,
        "reddit_score": int_or_none(p.get("score")),
        "reddit_upvote_ratio": float_or_none(p.get("upvote_ratio")),
        "comments": int_or_none(p.get("num_comments")),
        "published_at": epoch_to_iso(p.get("created_utc")),
        "published_at_source": "created_utc" if p.get("created_utc") else None,
        "duration": float_or_none(rv.get("duration")),
        "width": int_or_none(rv.get("width")),
        "height": int_or_none(rv.get("height")),
        "fps": None,
        "tags": [p["link_flair_text"]] if p.get("link_flair_text") else [],
        "original_url": external,
        "original_author_hint": hint,
        "extra": {"subreddit": p.get("subreddit"), "domain": p.get("domain"), "hosted_video": hosted,
                  "over_18": bool(p.get("over_18")), "post_hint": p.get("post_hint"),
                  "is_crosspost": bool(xpost)},
    }


def _posts(listing) -> list[dict]:
    """Search -> Listing; a post permalink .json -> [Listing(post), Listing(comments)]."""
    if isinstance(listing, list):
        listing = listing[0] if listing else {}
    children = ((listing or {}).get("data") or {}).get("children") or []
    return [c.get("data") or {} for c in children if isinstance(c, dict) and c.get("kind") == "t3"]


def search(query: str, limit: int = 10, recent_only: bool = False) -> SearchResult:
    if query.strip().startswith(("http://", "https://")) and "/comments/" in query:
        return fetch_url(query.strip())
    url = build_url(query, limit, recent_only)
    res = SearchResult(platform=PLATFORM, query=query, mode="search", request=url, access=access(OK))
    try:
        data = base.http_get_json(url, headers={"User-Agent": base.user_agent()})
    except Exception as e:  # noqa: BLE001
        res.access = classify_error(e)
        return res.done()
    posts = _posts(data)
    vids = [p for p in posts if is_video_post(p)][: int(limit)]
    for p in vids:
        c = normalize_post(p)
        c["_item_access"] = access(OK)
        res.candidates.append(c)
    res.notes.append(f"게시물 {len(posts)}건 중 영상 게시물 {len(vids)}건")
    return res.done()


def fetch_url(url: str) -> SearchResult:
    res = SearchResult(platform=PLATFORM, query=url, mode="url", request=url, access=access(OK))
    sp = urllib.parse.urlsplit(url)
    path = sp.path.rstrip("/")
    json_url = urllib.parse.urlunsplit(("https", "www.reddit.com", path + ".json", "raw_json=1", ""))
    res.request = json_url
    try:
        data = base.http_get_json(json_url, headers={"User-Agent": base.user_agent()})
    except Exception as e:  # noqa: BLE001
        res.access = classify_error(e)
        return res.done()
    for p in _posts(data)[:1]:
        c = normalize_post(p)
        c["_item_access"] = access(OK)
        res.candidates.append(c)
    return res.done()
