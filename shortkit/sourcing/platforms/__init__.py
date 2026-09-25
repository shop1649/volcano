"""Platform adapters for new-source discovery (YouTube / TikTok / Instagram / Reddit).

Every adapter exposes::

    search(query, limit=10, recent_only=False) -> SearchResult
    fetch_url(url) -> SearchResult            # one item, direct URL intake

A ``SearchResult`` always carries an *access status* for the platform call:

    ok              the platform answered
    blocked         network policy / platform refused the connection (HTTP 403 at the proxy, ...)
    login_required  the platform needs a logged-in session (cookies) for this request
    error           anything else; ``note`` keeps the exact error text

Network I/O goes through the two module-level functions :func:`ytdlp_extract` /
:func:`ytdlp_download` (yt-dlp) and :func:`http_get_json` (plain HTTPS JSON).  Tests replace
them with synthetic fixtures (monkeypatch); adapters must always call them through this
module (``base.ytdlp_extract``) so the replacement takes effect.

Normalized candidate dict produced by the adapters (consumed by ``warehouse.build_record``)::

    platform, platform_id, url, title, description, uploader, uploader_id, uploader_url,
    channel, channel_id, views (int|None), views_source ('platform_metadata'|'unavailable'),
    views_field (which metadata field the number came from), views_note,
    likes (int|None, NEVER used as views), comments, reddit_score (reddit only, NEVER views),
    published_at (UTC ISO or YYYY-MM-DD), published_at_source, duration, width, height, fps,
    tags, original_url, original_author_hint, extra{}
"""
from __future__ import annotations

import datetime as _dt
import json
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from typing import Any

from ... import paths
from ...util.jsonio import now_iso, read_yaml

PLATFORMS = ("youtube", "tiktok", "instagram", "reddit")

OK = "ok"
BLOCKED = "blocked"
LOGIN_REQUIRED = "login_required"
ERROR = "error"
ACCESS_STATUSES = (OK, BLOCKED, LOGIN_REQUIRED, ERROR)
ACCESS_KO = {OK: "접속됨", BLOCKED: "차단됨", LOGIN_REQUIRED: "로그인 필요", ERROR: "오류"}

DEFAULT_USER_AGENT = "python:shortkit-sourcing:0.1 (source discovery; set sourcing.user_agent in local.yaml)"
NOTE_MAX = 800


# ----------------------------------------------------------------------------- result types
@dataclass
class SearchResult:
    platform: str
    query: str
    mode: str                         # keyword | hashtag | user | url | search
    request: str                      # what was actually requested (yt-dlp query / URL)
    access: dict                      # {platform_status, note}
    candidates: list[dict] = field(default_factory=list)
    item_errors: list[dict] = field(default_factory=list)   # per-item metadata failures
    started_at: str = field(default_factory=now_iso)
    finished_at: str | None = None
    notes: list[str] = field(default_factory=list)          # extra facts (e.g. extractor marked broken)

    def done(self) -> "SearchResult":
        self.finished_at = now_iso()
        return self

    def to_dict(self) -> dict:
        return asdict(self)


def scrub(text: str) -> str:
    """Remove machine-specific absolute paths (project root, home directories) from stored text."""
    t = str(text or "")
    try:
        t = t.replace(str(paths.project_root()) + "/", "")
    except Exception:  # noqa: BLE001
        pass
    t = re.sub(r"(?<![\w:/.])(/home/[^/\s'\"]+|/Users/[^/\s'\"]+|/root(?=/))|"
               r"\b[A-Za-z]:\\+Users\\+[^\\\s'\"]+", "~", t)
    return re.sub(r"(?<![\w:/.])(?:/private)?(?:/tmp|/var/folders|/var/tmp)/[^\s'\")]*", "<tmp>", t)


def access(status: str, note: str = "") -> dict:
    assert status in ACCESS_STATUSES, status
    return {"platform_status": status, "note": scrub(note or "")[:NOTE_MAX]}


# ----------------------------------------------------------------------------- error classification
_BLOCK_PATTERNS = [
    r"Tunnel connection failed:\s*40[37]",
    r"ProxyError",
    r"blocked by (?:the )?(?:network|egress) policy",
    r"HTTP Error 403",
    r"\b403\b.*Forbidden",
    r"Forbidden.*\b403\b",
    r"HTTP Error 451",
]
_LOGIN_PATTERNS = [
    r"[Ss]ign in to confirm",
    r"login required",
    r"[Ll]ogin is required",
    r"requires? (?:a )?log(?:ged)?[ -]?in",
    r"use --cookies",
    r"--cookies-from-browser",
    r"This content isn't available.*log",
    r"rate-limit reached or login required",
    r"age[- ]restricted|confirm your age",
]


def classify_error(exc: BaseException | str) -> dict:
    """Map an exception / error text to an access dict, keeping the exact error text."""
    if isinstance(exc, BaseException):
        text = f"{type(exc).__name__}: {exc}"
        cause = exc.__cause__ or exc.__context__
        if cause is not None and str(cause) not in text:
            text += f" (cause: {type(cause).__name__}: {cause})"
    else:
        text = str(exc)
    text = re.sub(r"\x1b\[[0-9;]*m", "", text).strip()
    for pat in _LOGIN_PATTERNS:
        if re.search(pat, text):
            return access(LOGIN_REQUIRED, text)
    for pat in _BLOCK_PATTERNS:
        if re.search(pat, text):
            return access(BLOCKED, text)
    return access(ERROR, text)


# ----------------------------------------------------------------------------- local (user) settings
def local_settings() -> dict:
    """``local.yaml`` (git-ignored, per machine). Only the ``sourcing`` section is used here::

        sourcing:
          cookies: {instagram: cookies_instagram.txt, tiktok: null, youtube: null}   # root-relative or absolute
          user_agent: "python:myapp:0.1 (by /u/me)"
    """
    try:
        d = read_yaml(paths.absp("local.yaml"), {}) or {}
    except Exception:
        return {}
    return d.get("sourcing") or {}


def cookiefile(platform: str) -> str | None:
    c = (local_settings().get("cookies") or {}).get(platform)
    if not c:
        return None
    p = paths.absp(c)
    return str(p) if p.is_file() else None


def user_agent() -> str:
    return local_settings().get("user_agent") or DEFAULT_USER_AGENT


# ----------------------------------------------------------------------------- network primitives
class _YdlLog:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def debug(self, msg: str) -> None:
        pass

    def info(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        self.warnings.append(str(msg))

    def error(self, msg: str) -> None:
        self.warnings.append(str(msg))


def _ydl_opts(flat: bool, cookie: str | None, playlistend: int | None, log: _YdlLog) -> dict:
    o: dict[str, Any] = {
        "quiet": True, "no_warnings": False, "skip_download": True, "logger": log,
        "socket_timeout": 20, "retries": 1, "extractor_retries": 1, "noprogress": True,
    }
    if flat:
        o["extract_flat"] = "in_playlist"
    if cookie:
        o["cookiefile"] = cookie
    if playlistend:
        o["playlistend"] = int(playlistend)
    return o


def ytdlp_extract(url: str, *, flat: bool = False, cookie: str | None = None,
                  playlistend: int | None = None) -> dict:
    """yt-dlp metadata extraction (no download). Raises on failure (see classify_error)."""
    import yt_dlp

    log = _YdlLog()
    with yt_dlp.YoutubeDL(_ydl_opts(flat, cookie, playlistend, log)) as ydl:
        info = ydl.extract_info(url, download=False)
        info = ydl.sanitize_info(info)
    if isinstance(info, dict) and log.warnings:
        info["_shortkit_warnings"] = log.warnings[:10]
    return info


YTDLP_FORMAT = "bv*[ext=mp4][vcodec^=avc1]+ba[ext=m4a]/b[ext=mp4]/bv*+ba/b"


def ytdlp_download(url: str, out_template: str, *, cookie: str | None = None) -> dict:
    """Download with yt-dlp to ``out_template`` (absolute, ``%(ext)s`` allowed), remuxed to mp4.

    Returns the sanitized info dict; ``info['_shortkit_filepath']`` is the final file."""
    import yt_dlp

    log = _YdlLog()
    opts = {
        "quiet": True, "no_warnings": False, "logger": log, "noprogress": True,
        "outtmpl": out_template, "format": YTDLP_FORMAT, "merge_output_format": "mp4",
        "postprocessors": [{"key": "FFmpegVideoRemuxer", "preferedformat": "mp4"}],
        "noplaylist": True, "socket_timeout": 30, "retries": 2, "overwrites": True,
    }
    if cookie:
        opts["cookiefile"] = cookie
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        fp = None
        for d in (info or {}).get("requested_downloads") or []:
            fp = d.get("filepath") or fp
        info = ydl.sanitize_info(info)
    info["_shortkit_filepath"] = fp
    if log.warnings:
        info["_shortkit_warnings"] = log.warnings[:10]
    return info


def http_get_json(url: str, *, headers: dict | None = None, timeout: float = 20.0) -> Any:
    """Plain HTTPS GET returning parsed JSON (honours HTTPS_PROXY). Raises on HTTP/network errors."""
    req = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read()
    return json.loads(body.decode("utf-8"))


def extractor_status(url: str) -> tuple[str | None, bool | None]:
    """(yt-dlp extractor name, is it marked working) for a URL; generic is ignored."""
    try:
        from yt_dlp.extractor import gen_extractor_classes

        for ie in gen_extractor_classes():
            if ie.IE_NAME == "generic":
                continue
            if ie.suitable(url):
                return ie.IE_NAME, bool(getattr(ie, "_WORKING", True))
    except Exception:
        pass
    return None, None


def broken_extractor_note(url: str) -> str | None:
    name, working = extractor_status(url)
    if name and working is False:
        return (f"yt-dlp 가 '{name}' 추출기를 작동 안 함(_WORKING=False)으로 표시함 — "
                "결과가 비어 있거나 오류일 수 있음")
    return None


# working routes to suggest when a listing extractor is marked broken (yt-dlp 2026.08.19: tiktok:tag, instagram:user)
BROKEN_ALTERNATIVES = {
    "tiktok": "대안: 레퍼런스 추적 계정 `@계정` 검색(yt-dlp tiktok:user) 또는 찾은 영상 URL 을 `source add-url` 로 직접 입력",
    "instagram": "대안: 해시태그 검색(`#태그`, 로그인 쿠키 필요) 또는 게시물/릴스 URL 을 `source add-url` 로 직접 입력",
}


def broken_listing_access(platform: str, broken: str, mode: str) -> dict:
    """Access for an EMPTY listing from an extractor yt-dlp marks as not working: an empty result there does
    not mean 'no videos', so it is recorded as ``error`` (never 'ok, 0 results')."""
    return access(ERROR, f"{broken} — {mode} 목록이 비어 있음: 작동 안 하는 추출기라 '결과 0건'으로 볼 수 없음(못 잼). "
                         + BROKEN_ALTERNATIVES.get(platform, "대안: 영상 URL 을 `source add-url` 로 직접 입력"))


# ----------------------------------------------------------------------------- field helpers
def int_or_none(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v == v:
        return int(v)
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None


def float_or_none(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def epoch_to_iso(ts: Any) -> str | None:
    f = float_or_none(ts)
    if f is None or f <= 0:
        return None
    return _dt.datetime.fromtimestamp(f, _dt.timezone.utc).replace(microsecond=0).isoformat()


def yyyymmdd_to_iso(s: Any) -> str | None:
    if not isinstance(s, str) or not re.fullmatch(r"\d{8}", s):
        return None
    return f"{s[:4]}-{s[4:6]}-{s[6:]}"


def published_from_info(info: dict) -> tuple[str | None, str | None]:
    """(published_at, source field). timestamp beats upload_date (date only)."""
    for k in ("timestamp", "release_timestamp"):
        iso = epoch_to_iso(info.get(k))
        if iso:
            return iso, k
    for k in ("upload_date", "release_date"):
        iso = yyyymmdd_to_iso(info.get(k))
        if iso:
            return iso, k
    return None, None


def views_from_info(info: dict, fields: tuple[str, ...]) -> tuple[int | None, str | None]:
    """First present integer among the platform's *view/play* fields. Likes are never consulted."""
    for f in fields:
        v = int_or_none(info.get(f))
        if v is not None and v >= 0:
            return v, f
    return None, None


def common_from_info(info: dict, platform: str, view_fields: tuple[str, ...]) -> dict:
    """Normalize a yt-dlp info dict (documented field names) into a candidate dict."""
    views, vfield = views_from_info(info, view_fields)
    pub, pub_src = published_from_info(info)
    w, h = int_or_none(info.get("width")), int_or_none(info.get("height"))
    if (not w or not h) and info.get("formats"):
        best = max((f for f in info["formats"] if int_or_none(f.get("height"))),
                   key=lambda f: int_or_none(f.get("height")) or 0, default=None)
        if best:
            w, h = int_or_none(best.get("width")), int_or_none(best.get("height"))
    return {
        "platform": platform,
        "platform_id": str(info.get("id") or ""),
        "url": info.get("webpage_url") or info.get("original_url") or info.get("url"),
        "title": info.get("title") or info.get("fulltitle"),
        "description": (info.get("description") or "")[:4000] or None,
        "uploader": info.get("uploader") or info.get("channel") or info.get("creator"),
        "uploader_id": info.get("uploader_id") or info.get("channel_id"),
        "uploader_url": info.get("uploader_url") or info.get("channel_url"),
        "channel": info.get("channel"),
        "channel_id": info.get("channel_id"),
        "views": views,
        "views_source": "platform_metadata" if views is not None else "unavailable",
        "views_field": vfield,
        "views_note": None if views is not None else "메타데이터에 조회수 필드 없음",
        "likes": int_or_none(info.get("like_count")),
        "comments": int_or_none(info.get("comment_count")),
        "published_at": pub,
        "published_at_source": pub_src,
        "duration": float_or_none(info.get("duration")),
        "width": w,
        "height": h,
        "fps": float_or_none(info.get("fps")),
        "tags": list(info.get("tags") or [])[:30],
        "original_url": None,
        "original_author_hint": None,
        "extra": {"extractor": info.get("extractor_key") or info.get("extractor"),
                  "warnings": info.get("_shortkit_warnings") or []},
    }


# ----------------------------------------------------------------------------- URL helpers
_YT_ID = r"([A-Za-z0-9_-]{11})(?![A-Za-z0-9_-])"


def detect_platform(url: str) -> str | None:
    host = (urllib.parse.urlsplit(url).hostname or "").lower()
    if host.endswith("youtube.com") or host == "youtu.be" or host.endswith("youtube-nocookie.com"):
        return "youtube"
    if host.endswith("tiktok.com") or host.endswith("tiktokv.com"):
        return "tiktok"
    if host.endswith("instagram.com"):
        return "instagram"
    if host.endswith("reddit.com") or host == "redd.it" or host.endswith("redditmedia.com"):
        return "reddit"
    return None


def url_key(url: str | None) -> str | None:
    """Canonical identity of a URL for equality rules: 'youtube:<id>', 'tiktok:<id>', ...,
    otherwise host+path (lower-case host, no www/m., no query/fragment, no trailing slash)."""
    if not url or not isinstance(url, str):
        return None
    u = url.strip()
    if "://" not in u:
        u = "https://" + u
    sp = urllib.parse.urlsplit(u)
    host = (sp.hostname or "").lower()
    for pre in ("www.", "m.", "mobile.", "old.", "new.", "vm."):
        if host.startswith(pre):
            host = host[len(pre):]
    path = sp.path or ""
    q = urllib.parse.parse_qs(sp.query)
    if host.endswith("youtube.com") or host.endswith("youtube-nocookie.com"):
        if q.get("v") and re.fullmatch(r"[A-Za-z0-9_-]{11}", q["v"][0]):
            return f"youtube:{q['v'][0]}"
        m = re.match(rf"^/(?:shorts|embed|live|v)/{_YT_ID}", path)
        if m:
            return f"youtube:{m.group(1)}"
    if host == "youtu.be":
        m = re.match(rf"^/{_YT_ID}", path)
        if m:
            return f"youtube:{m.group(1)}"
    if host.endswith("tiktok.com"):
        m = re.search(r"/video/(\d+)", path)
        if m:
            return f"tiktok:{m.group(1)}"
    if host.endswith("instagram.com"):
        m = re.search(r"/(?:p|reels?|tv)/([^/?#&]+)", path)
        if m:
            return f"instagram:{m.group(1)}"
    if host.endswith("reddit.com"):
        m = re.search(r"/comments/([a-z0-9]+)", path)
        if m:
            return f"reddit:{m.group(1)}"
    if host == "redd.it":
        m = re.match(r"^/([a-z0-9]+)", path)
        if m:
            return f"reddit:{m.group(1)}"
    # generic fallback keeps the (non-tracking) query so different items never collapse into one key
    keep = sorted((k, v) for k, vs in q.items() for v in vs
                  if not k.lower().startswith("utm_") and k.lower() not in _TRACKING_PARAMS)
    qs = ("?" + urllib.parse.urlencode(keep)) if keep else ""
    return f"{host}{path.rstrip('/')}{qs}"


_TRACKING_PARAMS = {"si", "feature", "t", "lang", "is_from_webapp", "sender_device", "igsh", "igshid",
                    "share_id", "ref", "ref_src", "context"}

_IG_RESERVED = {"p", "reel", "reels", "tv", "explore", "stories", "accounts", "direct", "about", "developer"}


def handle_from_url(url: str | None) -> str | None:
    """The posting account named in a platform URL path ('@handle'), or None.

    tiktok.com/@user/video/<id>, youtube.com/@handle[/shorts|/videos], instagram.com/<user>/(reel|p)/<code>,
    instagram.com/<user>/, reddit.com/(user|u)/<name>.  A YouTube /shorts/<id> or instagram /reel/<code> URL
    without a user segment names no account (None)."""
    if not url or not isinstance(url, str):
        return None
    sp = urllib.parse.urlsplit(url.strip() if "://" in url else "https://" + url.strip())
    host = (sp.hostname or "").lower()
    parts = [x for x in (sp.path or "").split("/") if x]
    if not parts:
        return None
    if host.endswith("tiktok.com") or host.endswith("youtube.com"):
        if parts[0].startswith("@") and len(parts[0]) > 1:
            return "@" + urllib.parse.unquote(parts[0][1:])
        return None
    if host.endswith("instagram.com"):
        if parts[0].lower() not in _IG_RESERVED and re.fullmatch(r"[A-Za-z0-9_.]{1,30}", parts[0]):
            return "@" + parts[0]
        return None
    if host.endswith("reddit.com") and len(parts) >= 2 and parts[0].lower() in ("user", "u"):
        return "u/" + parts[1]
    return None


def get_adapter(platform: str):
    import importlib

    if platform not in PLATFORMS:
        raise KeyError(f"알 수 없는 플랫폼: {platform} (가능: {', '.join(PLATFORMS)})")
    return importlib.import_module(f"{__name__}.{platform}")


def drop_known_old(res: SearchResult) -> SearchResult:
    """Client-side ``recent_only`` for platforms without a server-side date filter: drop items whose
    published date is KNOWN to be outside the recency window; unknown dates are kept (the warehouse
    labels them 'unknown', never 'recent')."""
    from ..score import recency

    kept, dropped = [], 0
    for c in res.candidates:
        r = recency(c.get("published_at"))
        if r["label"] == "old":
            dropped += 1
            continue
        kept.append(c)
    res.candidates = kept
    res.notes.append(f"recent_only: 플랫폼에 날짜 필터가 없어 수집 후 게시일로 거름(오래된 {dropped}건 제외, "
                     "게시일 모름은 유지)")
    return res
