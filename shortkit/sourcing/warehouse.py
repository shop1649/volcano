"""New-source warehouse: ``warehouse/candidates.jsonl`` + ``warehouse/search_log.jsonl`` (CONTRACT §9).

One record per candidate, upserted by (platform, platform_id).  Field rules:
  - ``views`` is an int only when it came from platform metadata (``views_source='platform_metadata'``)
    together with ``views_checked_at``; otherwise ``None`` / ``'unavailable'``.  Every confirmed value is
    also appended to ``views_history``.  A later fetch without views never erases a confirmed value.
  - ``likes`` (and Reddit ``reddit_score``) are stored separately and are never converted to views.
  - ``published_at`` is the platform publish time; ``first_seen_at`` is when WE first saw it (never used
    for recency).
  - ``original_author`` vs ``reposter``: from metadata + description credits ('출처', 'credit', 'via', '@');
    ``original_author_basis`` says how it was decided.
  - all stored paths are root-relative.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from .. import paths
from ..util.hashing import short_id
from ..util.jsonio import append_jsonl, now_iso, read_jsonl, write_jsonl
from . import exclusions
from .platforms import (PLATFORMS, SearchResult, access, classify_error, detect_platform, get_adapter, scrub,
                        url_key)

CANDIDATES = "warehouse/candidates.jsonl"
SEARCH_LOG = "warehouse/search_log.jsonl"
SOURCES_DIR = "warehouse/sources"
SOURCE_ACCOUNTS = "warehouse/source_accounts.json"
STATUSES = ("candidate", "selected", "rejected", "used", "excluded")
STATUS_KO = {"candidate": "후보", "selected": "선택됨", "rejected": "탈락", "used": "사용함", "excluded": "제외(레퍼런스와 같은 녹화)"}
# fields refreshed from a new metadata fetch when the new value is not None
_META_FIELDS = ("url", "title", "description", "uploader", "uploader_id", "uploader_url", "channel", "duration",
                "width", "height", "fps", "tags", "published_at", "published_at_source", "comments")


# ----------------------------------------------------------------------------- storage
def candidate_id(platform: str, platform_id: str) -> str:
    raw = str(platform_id)
    pid = re.sub(r"[^A-Za-z0-9_-]", "_", raw)
    if pid != raw:                      # keep distinct ids distinct after sanitising
        pid = f"{pid}_{short_id(raw, 6)}"
    return f"{platform}_{pid}"


def load() -> list[dict]:
    return read_jsonl(paths.absp(CANDIDATES))


def scrub_obj(o: Any) -> Any:
    """Safety net for the 'no machine-specific absolute paths in stored files' rule: every string that is
    written to candidates.jsonl / search_log.jsonl goes through platforms.scrub (error texts can quote
    absolute paths of ffmpeg commands, temp files, home directories)."""
    if isinstance(o, str):
        return scrub(o) if ("/" in o or "\\" in o) else o
    if isinstance(o, dict):
        return {k: scrub_obj(v) for k, v in o.items()}
    if isinstance(o, list):
        return [scrub_obj(v) for v in o]
    return o


def save(rows: list[dict]) -> None:
    rows = sorted(rows, key=lambda r: (r.get("first_seen_at") or "", r.get("id") or ""))
    write_jsonl(paths.absp(CANDIDATES), [scrub_obj(r) for r in rows])


def get(cid: str, rows: list[dict] | None = None) -> dict:
    for r in rows if rows is not None else load():
        if r.get("id") == cid:
            return r
    raise KeyError(f"창고에 없는 후보 ID: {cid} (`shortkit source list` 로 확인)")


def find(rows: list[dict], platform: str, platform_id: str) -> dict | None:
    for r in rows:
        if r.get("platform") == platform and str(r.get("platform_id")) == str(platform_id):
            return r
    return None


def put(rec: dict) -> dict:
    rows = load()
    for i, r in enumerate(rows):
        if r.get("id") == rec["id"]:
            rows[i] = rec
            break
    else:
        rows.append(rec)
    save(rows)
    return rec


class SelectionError(RuntimeError):
    pass


def set_status(rec: dict, status: str, by: str, reason: str) -> dict:
    """Status change with the hard rules enforced at the lowest level (no path around them)."""
    if status not in STATUSES:
        raise ValueError(status)
    if status == "selected":
        from .score import review_of

        if review_of(rec) is None:
            raise SelectionError("검토 기록(watched_by, notes, 강도/반전/형식 적합) 없이 'selected' 불가")
        if (rec.get("reference_overlap") or {}).get("excluded") is True or rec.get("status") == "excluded":
            raise SelectionError("레퍼런스와 같은 녹화로 제외된 후보는 'selected' 불가")
    if status == "used" and rec.get("status") not in ("selected", "used"):
        raise SelectionError("'selected' 가 아닌 후보는 'used' 로 바꿀 수 없음")
    rec["status"] = status
    rec.setdefault("status_history", []).append({"status": status, "at": now_iso(), "by": by, "reason": reason})
    return rec


# ----------------------------------------------------------------------------- credits / authorship
_URL = r"https?://[^\s)\]>\"']+"
_HANDLE = r"@?[\w][\w.\-]{1,40}"
_SEP = r"(?:\s*[:：=\-]\s*|\s+(?=@|https?://))"      # explicit separator, or directly an @handle / URL
_CREDIT_RES = [
    ("출처", re.compile(rf"출처{_SEP}({_URL}|{_HANDLE})")),
    ("credit", re.compile(rf"(?i)\b(?:credits?|cr|source){_SEP}(?:to\s+)?({_URL}|{_HANDLE})")),
    ("credit", re.compile(rf"(?i)\b(?:video|filmed|shot|recorded|original(?:ly)?(?: posted)?) by\s+({_URL}|{_HANDLE})")),
    ("via", re.compile(rf"(?i)\bvia\s+({_URL}|{_HANDLE})")),
]
_MENTION_RE = re.compile(r"(?<![\w@])@([A-Za-z0-9_][A-Za-z0-9_.]{1,29})")


def _norm_handle(s: str | None) -> str:
    return re.sub(r"[^0-9a-z가-힣_.]", "", str(s or "").lower().lstrip("@"))


def extract_credits(*texts: str | None) -> list[dict]:
    """Credit mentions in title/description: ``[{kind: 출처|credit|via|mention, value, is_url}]``."""
    out: list[dict] = []
    seen = set()
    for text in texts:
        if not text:
            continue
        for kind, rx in _CREDIT_RES:
            for m in rx.finditer(text):
                v = m.group(1).rstrip(".,;:!)")
                key = (kind, v.lower())
                if key not in seen:
                    seen.add(key)
                    out.append({"kind": kind, "value": v, "is_url": v.startswith("http")})
        explicit = {_norm_handle(c["value"]) for c in out if not c["is_url"]}
        for m in _MENTION_RE.finditer(text):
            v = "@" + m.group(1).rstrip(".")
            if _norm_handle(v) in explicit:
                continue
            key = ("mention", v.lower())
            if key not in seen:
                seen.add(key)
                out.append({"kind": "mention", "value": v, "is_url": False})
    return out


def authorship(item: dict, credits: list[dict]) -> dict:
    """Decide original_author / original_url / reposter from metadata + credits (with the basis)."""
    uploader = item.get("uploader")
    up_norm = _norm_handle(uploader)
    up_id_norm = _norm_handle(item.get("uploader_id"))
    explicit = [c for c in credits if c["kind"] != "mention"]
    urls = [c["value"] for c in explicit if c["is_url"]]
    names = [c["value"] for c in explicit if not c["is_url"]]
    mentions = sorted({c["value"] for c in credits if c["kind"] == "mention"})
    original_url = item.get("original_url") or (urls[0] if urls else None)
    hint = item.get("original_author_hint") or {}

    def _differs(name: str) -> bool:
        n = _norm_handle(name)
        return bool(n) and n not in (up_norm, up_id_norm)

    if names:
        oa, basis = names[0], "description_credit"
    elif hint.get("name"):
        oa, basis = hint["name"], hint.get("basis") or "metadata"
        original_url = original_url or hint.get("url")
    elif len(mentions) == 1 and _differs(mentions[0]):
        oa, basis = mentions[0], "description_mention(약한 근거: 설명의 유일한 @언급)"
    elif item.get("original_url"):
        oa, basis = None, "external_link(원 게시자 모름: 원본 URL 을 add-url 로 따로 확인)"
    elif uploader:
        oa, basis = uploader, "uploader(원작자 여부 미확인: 크레딧 표기 없음)"
    else:
        oa, basis = None, "unknown(메타데이터 없음)"
    reposter = None
    if uploader and (oa is None or _differs(oa)):
        reposter = uploader
    return {"original_author": oa, "original_author_basis": basis, "original_url": original_url,
            "reposter": reposter}


# ----------------------------------------------------------------------------- records
def orientation(w: Any, h: Any) -> str | None:
    from .score import orientation as _o

    return _o(w, h)


def _clean_item(item: dict) -> dict:
    return {k: v for k, v in item.items() if not k.startswith("_")}


def _overlap_unchecked() -> dict:
    return {"excluded": None, "matched_video_id": None, "method": None, "distance": None,
            "checked_at": None, "note": "아직 검사 안 함"}


def compact_scores(s: dict) -> dict:
    keys = ("recency", "intensity", "reversal", "quality", "format_fit", "total", "recency_label", "age_days",
            "recency_basis", "recency_threshold_days", "checked_at", "unmeasured", "review_by", "format_facts")
    return {k: s.get(k) for k in keys}


def refresh_scores(rec: dict) -> dict:
    from .score import compute_scores

    rec["scores"] = compact_scores(compute_scores(rec))
    return rec


def build_record(item: dict, *, keywords: Iterable[str] = (), acc: dict | None = None,
                 now: str | None = None, found_by: str = "search") -> dict:
    now = now or now_iso()
    it = _clean_item(item)
    acc = acc or item.get("_item_access") or access("ok")
    credits = extract_credits(it.get("title"), it.get("description"))
    views = it.get("views")
    rec: dict[str, Any] = {
        "id": candidate_id(it["platform"], it["platform_id"]),
        "platform": it["platform"],
        "platform_id": str(it["platform_id"]),
        "url": it.get("url"),
        "title": it.get("title"),
        "description": it.get("description"),
        "uploader": it.get("uploader"),
        "uploader_id": it.get("uploader_id"),
        "uploader_url": it.get("uploader_url"),
        "channel": it.get("channel"),
        **authorship(it, credits),
        "credits": credits,
        "keywords": sorted({k for k in keywords if k}),
        "views": views if views is not None and it.get("views_source") == "platform_metadata" else None,
        "views_checked_at": now if views is not None and it.get("views_source") == "platform_metadata" else None,
        "views_source": "platform_metadata" if views is not None and it.get("views_source") == "platform_metadata"
        else "unavailable",
        "views_field": it.get("views_field"),
        "views_note": it.get("views_note"),
        "views_history": ([{"views": views, "checked_at": now, "field": it.get("views_field")}]
                          if views is not None and it.get("views_source") == "platform_metadata" else []),
        "likes": it.get("likes"),
        "likes_checked_at": now if it.get("likes") is not None else None,
        "comments": it.get("comments"),
        "published_at": it.get("published_at"),
        "published_at_source": it.get("published_at_source"),
        "first_seen_at": now,
        "last_checked_at": now,
        "duration": it.get("duration"),
        "width": it.get("width"),
        "height": it.get("height"),
        "fps": it.get("fps"),
        "orientation": orientation(it.get("width"), it.get("height")),
        "tags": it.get("tags") or [],
        "download_path": None,
        "sha256": None,
        "download": None,
        "quality": None,
        "reference_overlap": _overlap_unchecked(),
        "reviews": [],
        "scores": None,
        "selection_reason": None,
        "status": "candidate",
        "status_history": [{"status": "candidate", "at": now, "by": found_by, "reason": "수집"}],
        "access": {**acc, "checked_at": now},
        "extra": it.get("extra") or {},
    }
    if it["platform"] == "reddit" or it.get("reddit_score") is not None:
        rec["reddit_score"] = it.get("reddit_score")
        rec["reddit_score_checked_at"] = now if it.get("reddit_score") is not None else None
        rec["reddit_upvote_ratio"] = it.get("reddit_upvote_ratio")
    return refresh_scores(rec)


def merge_record(old: dict, item: dict, *, keywords: Iterable[str] = (), acc: dict | None = None,
                 now: str | None = None) -> dict:
    """Update an existing record with a new fetch. Keeps first_seen_at, status, reviews, download,
    overlap; views/likes only replaced by new confirmed values (history kept)."""
    now = now or now_iso()
    it = _clean_item(item)
    rec = dict(old)
    acc = acc or item.get("_item_access") or access("ok")
    for k in _META_FIELDS:
        if it.get(k) not in (None, "", []):
            rec[k] = it[k]
    rec["orientation"] = orientation(rec.get("width"), rec.get("height"))
    if it.get("views") is not None and it.get("views_source") == "platform_metadata":
        rec["views"] = it["views"]
        rec["views_checked_at"] = now
        rec["views_source"] = "platform_metadata"
        rec["views_field"] = it.get("views_field")
        rec["views_note"] = None
        rec.setdefault("views_history", []).append({"views": it["views"], "checked_at": now,
                                                    "field": it.get("views_field")})
    elif rec.get("views") is None:
        rec["views_note"] = it.get("views_note") or rec.get("views_note")
    if it.get("likes") is not None:
        rec["likes"] = it["likes"]
        rec["likes_checked_at"] = now
    if it.get("reddit_score") is not None:
        rec["reddit_score"] = it["reddit_score"]
        rec["reddit_score_checked_at"] = now
        rec["reddit_upvote_ratio"] = it.get("reddit_upvote_ratio")
    rec["keywords"] = sorted(set(rec.get("keywords") or []) | {k for k in keywords if k})
    credits = extract_credits(rec.get("title"), rec.get("description"))
    rec["credits"] = credits
    rec.update(authorship({**rec, "original_url": it.get("original_url") or old.get("original_url"),
                           "original_author_hint": it.get("original_author_hint")}, credits))
    rec["last_checked_at"] = now
    rec["access"] = {**acc, "checked_at": now}
    if it.get("extra"):
        rec["extra"] = {**(rec.get("extra") or {}), **it["extra"]}
    return refresh_scores(rec)


def apply_overlap(rec: dict, result: dict, by: str = "exclusions") -> dict:
    """Store an exclusions.check() result in the §9 shape; excluded -> status 'excluded'."""
    rec["reference_overlap"] = {
        "excluded": result.get("excluded"),
        "matched_video_id": result.get("matched_ref_video_id"),
        "method": result.get("method"),
        "distance": result.get("distance"),
        "matched_keyframes": result.get("matched_keyframes"),
        "n_keyframes": result.get("n_keyframes"),
        "n_refs": result.get("n_refs"),
        "checked_at": result.get("checked_at") or now_iso(),
        "note": result.get("note"),
    }
    if result.get("excluded") is True and rec.get("status") != "excluded":
        set_status(rec, "excluded", by, result.get("note") or "레퍼런스와 같은 녹화")
    return rec


def upsert(items: Iterable[dict], *, keywords: Iterable[str] = (), now: str | None = None,
           found_by: str = "search") -> dict:
    """Insert or update candidates by (platform, platform_id). Returns {'new': [...], 'updated': [...]}."""
    now = now or now_iso()
    rows = load()
    kw = list(keywords)
    new, upd = [], []
    try:
        ex_entries = exclusions.load()
    except Exception:  # noqa: BLE001 - a broken exclusions file must not lose search results
        ex_entries = []
    for item in items:
        if not item.get("platform_id"):
            continue
        old = find(rows, item["platform"], item["platform_id"])
        if old is None:
            rec = build_record(item, keywords=kw, now=now, found_by=found_by)
            rows.append(rec)
            new.append(rec["id"])
        else:
            rec = merge_record(old, item, keywords=kw, now=now)
            rows[rows.index(old)] = rec
            upd.append(rec["id"])
        hit = exclusions.check_urls([rec.get("url"), rec.get("original_url")], ex_entries)
        if hit:
            apply_overlap(rec, {**hit, "checked_at": now}, by="exclusions:url")
    save(rows)
    return {"new": new, "updated": upd}


# ----------------------------------------------------------------------------- search log
def _tool_version(platform: str) -> str:
    if platform == "reddit":
        return "urllib (reddit public JSON)"
    try:
        import yt_dlp

        return f"yt-dlp {yt_dlp.version.__version__}"
    except Exception:  # noqa: BLE001
        return "yt-dlp (not importable)"


def log_search(res: SearchResult, *, limit: int | None, recent_only: bool, new: list[str],
               updated: list[str], note: str | None = None, kind: str = "search") -> dict:
    row = {
        "at": res.started_at, "finished_at": res.finished_at or now_iso(), "kind": kind,
        "platform": res.platform, "query": res.query, "mode": res.mode, "request": res.request,
        "limit": limit, "recent_only": recent_only,
        "result_count": len(res.candidates), "new_count": len(new), "updated_count": len(updated),
        "ids": [*new, *updated],
        "access": res.access,
        "item_errors": len(res.item_errors),
        "item_error_samples": res.item_errors[:3],
        "notes": res.notes,
        "note": note,
        "tool": _tool_version(res.platform),
    }
    row = scrub_obj(row)
    append_jsonl(paths.absp(SEARCH_LOG), row)
    return row


def read_log(platform: str | None = None) -> list[dict]:
    rows = read_jsonl(paths.absp(SEARCH_LOG))
    return [r for r in rows if not platform or r.get("platform") == platform]


# ----------------------------------------------------------------------------- orchestration
def run_search(query: str, platforms: Iterable[str] = PLATFORMS, limit: int = 10, recent_only: bool = False,
               note: str | None = None) -> list[dict]:
    """Search every platform, upsert results, log every call (also failures). Never raises for a
    platform failure: the next platform is still searched."""
    out = []
    for pf in platforms:
        try:
            res = get_adapter(pf).search(query, limit=limit, recent_only=recent_only)
        except Exception as e:  # noqa: BLE001 - unexpected adapter bug: still log it honestly
            res = SearchResult(platform=pf, query=query, mode="?", request="", access=classify_error(e)).done()
        ids = upsert(res.candidates, keywords=[query]) if res.candidates else {"new": [], "updated": []}
        row = log_search(res, limit=limit, recent_only=recent_only, new=ids["new"], updated=ids["updated"],
                         note=note)
        out.append(row)
    return out


def stub_from_url(url: str, platform: str, acc: dict) -> dict:
    """Minimal item for a URL whose metadata could not be fetched (views unknown, never guessed)."""
    k = url_key(url) or url
    pid = k.split(":", 1)[1] if ":" in k and not k.startswith("http") else short_id(k)
    return {"platform": platform, "platform_id": pid, "url": url, "title": None, "description": None,
            "uploader": None, "views": None, "views_source": "unavailable",
            "views_note": f"메타데이터를 받지 못함({acc.get('platform_status')}) → 조회수 모름",
            "likes": None, "published_at": None, "_item_access": acc,
            "extra": {"manual_intake": True}}


def intake_url(url: str, *, keywords: Iterable[str] = (), note: str | None = None) -> tuple[dict, dict]:
    """Manual intake of one URL: fetch metadata (if reachable) and upsert. Returns (record, log row)."""
    platform = detect_platform(url) or "other"
    if platform in PLATFORMS:
        try:
            res = get_adapter(platform).fetch_url(url)
        except Exception as e:  # noqa: BLE001
            res = SearchResult(platform=platform, query=url, mode="url", request=url, access=classify_error(e)).done()
    else:
        res = _fetch_other(url)
    items = res.candidates or [stub_from_url(url, platform, res.access)]
    for it in items:
        it.setdefault("_item_access", res.access)
    ids = upsert(items, keywords=list(keywords), found_by="add-url")
    row = log_search(res, limit=1, recent_only=False, new=ids["new"], updated=ids["updated"], note=note,
                     kind="manual_intake")
    rec = get((ids["new"] + ids["updated"])[0])
    return rec, row


def _fetch_other(url: str) -> SearchResult:
    from . import platforms as base

    res = SearchResult(platform="other", query=url, mode="url", request=url, access=access("ok"))
    try:
        info = base.ytdlp_extract(url)
    except Exception as e:  # noqa: BLE001
        res.access = classify_error(e)
        return res.done()
    c = base.common_from_info(info, "other", ("view_count",))
    c["_item_access"] = access("ok")
    res.candidates.append(c)
    return res.done()


# ----------------------------------------------------------------------------- selection
def select(cid: str, *, by: str = "user", accept: Iterable[str] | None = None,
           reason: str | None = None) -> tuple[bool, dict, list[str]]:
    """Final selection. Hard blockers (no review, excluded, rejected/used) always refuse; unmeasured items
    (reference overlap, recency, quality) refuse unless listed in ``accept`` with a ``reason``, which is
    recorded with its production impact. Returns (ok, record, Korean messages)."""
    from . import score

    c = get(cid)
    s = score.compute_scores(c)
    hard, soft = score.selection_blockers(c, s)
    msgs: list[str] = []
    acc = [a.strip() for a in (accept or []) if a and a.strip()]
    msgs += [f"선택 불가: {h}" for h in hard]
    missing = [b for b in soft if b["key"] not in acc]
    msgs += [f"선택 불가(못 잼): {b['text']} (영향: {b['impact']}) — 알고 선택하려면 "
             f"--accept-unmeasured {b['key']} --reason '...'" for b in missing]
    if soft and not missing and not (reason or "").strip():
        msgs.append("선택 불가: --accept-unmeasured 에는 --reason(사유)이 필요함")
    if msgs:
        return False, c, msgs
    now = now_iso()
    accepted = [{"key": b["key"], "text": b["text"], "impact": b["impact"], "reason": reason, "by": by, "at": now}
                for b in soft]
    c["scores"] = compact_scores(s)
    c["selection_reason"] = score.selection_reason(c, s, accepted)
    c["selection"] = {"at": now, "by": by, "accepted_unmeasured": accepted,
                      "scores_detail": {"quality": s["quality_detail"], "weights": s["weights"],
                                        "recency_basis": s.get("recency_basis")}}
    set_status(c, "selected", by, c["selection_reason"])
    put(c)
    return True, c, [f"{c['id']} 선택됨", f"선택 이유: {c['selection_reason']}"]


def mark_used(cid: str, episode_id: str, by: str = "user") -> dict:
    """Record that a selected candidate is used in an episode (plan.yaml sources[].warehouse_id)."""
    c = get(cid)
    set_status(c, "used", by, f"에피소드 {episode_id} 에 사용")
    eps = c.setdefault("used_in", [])
    if episode_id not in eps:
        eps.append(episode_id)
    put(c)
    return c
