"""New-source warehouse: ``warehouse/candidates.jsonl`` + ``warehouse/search_log.jsonl`` (CONTRACT §9).

One record per candidate, upserted by (platform, platform_id).  Field rules:
  - ``views`` is an int only when it came from platform metadata (``views_source='platform_metadata'``)
    together with ``views_checked_at``; otherwise ``None`` / ``'unavailable'``.  Every confirmed value is
    also appended to ``views_history``.  A later fetch without views never erases a confirmed value.
  - ``likes`` (and Reddit ``reddit_score``) are stored separately and are never converted to views.
  - ``published_at`` is the platform publish time; ``first_seen_at`` is when WE first saw it (never used
    for recency).
  - ``original_author`` vs ``reposter``: from metadata + description credits ('출처', 'credit', 'via', '@')
    (``authorship_base``), then repost evidence (:func:`refresh_provenance`): a burned-in watermark handle of
    ANOTHER account (download OCR hint, ``clean detect`` overlays, a reviewer's ``watermark_handle``) marks the
    upload as a repost, and a reviewer's ``original_upload`` answer (yes/no) is applied;
    ``original_author_basis`` says how it was decided, ``repost_evidence[]`` keeps the evidence.
  - all stored paths are root-relative.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from .. import paths
from ..util.hashing import short_id
from ..util.jsonio import append_jsonl, now_iso, read_jsonl, write_jsonl
from . import exclusions
from .platforms import (PLATFORMS, SearchResult, access, classify_error, detect_platform, get_adapter,
                        handle_from_url, scrub, url_key)

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


# ----------------------------------------------------------------------------- repost evidence
_WM_HANDLE_RE = re.compile(r"@\s?([A-Za-z0-9_][A-Za-z0-9_.]{1,40})(?: ([A-Za-z0-9_.]{2,24}))?")
ORIGINAL_UPLOAD = ("yes", "no", "unknown")


def _alnum(s: Any) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", str(s or "").lower())


def handles_in_text(text: str | None) -> list[dict]:
    """'@handle' marks in OCR text: ``[{handle, variants}]``.  OCR may split one handle into two words
    ('@fake repost'), so the following word is kept as a variant ('@fakerepost'), never as the handle."""
    out = []
    for line in str(text or "").splitlines():
        for m in _WM_HANDLE_RE.finditer(line):
            first = m.group(1).rstrip(".")
            if len(_alnum(first)) < 3:
                continue
            variants = ["@" + first] + (["@" + first + m.group(2).rstrip(".")] if m.group(2) else [])
            out.append({"handle": "@" + first, "variants": variants})
    return out


def same_account(handle: str | list[str], rec: dict) -> bool | None:
    """Is ``handle`` (or any of its OCR variants) the uploader's account?  None when the uploader is
    unknown.  OCR-tolerant: equal after removing punctuation, one contained in the other (>= 4 chars),
    or similarity >= 0.8."""
    import difflib

    names = [n for n in (_alnum(rec.get(k)) for k in ("uploader", "uploader_id", "channel")) if n]
    if not names:
        return None
    for v in ([handle] if isinstance(handle, str) else list(handle)):
        h = _alnum(v)
        for n in names:
            if h == n or (min(len(h), len(n)) >= 4 and (h in n or n in h)):
                return True
            if difflib.SequenceMatcher(None, h, n).ratio() >= 0.8:
                return True
    return False


def _overlay_doc(sha: str | None) -> dict | None:
    if not sha:
        return None
    try:
        from ..clean.detect import load_overlays

        return load_overlays(sha)
    except Exception:  # noqa: BLE001 - clean area unavailable: read the agreed file directly
        from ..util.jsonio import read_json

        return read_json(paths.absp(f"warehouse/overlays/{sha}.json"))


def repost_evidence(rec: dict) -> list[dict]:
    """Burned-in account marks seen in the file: ``[{kind: watermark_handle, handle, sources[], where,
    same_as_uploader: True|False|None}]`` from the download OCR hint (``quality.watermark_hint``), the
    ``clean detect`` overlay record (warehouse/overlays/<sha256>.json) and reviewers' ``watermark_handle``."""
    found: list[dict] = []

    def add(h: dict, source: str, where: Any = None, text: Any = None) -> None:
        for e in found:
            if _alnum(e["handle"]) == _alnum(h["handle"]):
                if source not in e["sources"]:
                    e["sources"].append(source)
                e["variants"] = list(dict.fromkeys(e["variants"] + h["variants"]))
                return
        found.append({"kind": "watermark_handle", "handle": h["handle"], "variants": list(h["variants"]),
                      "sources": [source], "where": where, "text": text})

    for t in ((rec.get("quality") or {}).get("watermark_hint") or {}).get("texts") or []:
        for h in handles_in_text(t.get("text")):
            add(h, "download_ocr_hint", t.get("corner"), t.get("text"))
    doc = _overlay_doc(rec.get("sha256"))
    for o in (doc or {}).get("overlays") or []:
        if o.get("kind") in ("watermark", "source_overlay") and not o.get("ignored"):
            for h in handles_in_text(o.get("text")):
                add(h, f"clean_detect:{o.get('id')}", o.get("corner") or o.get("band"), o.get("text"))
    for r in rec.get("reviews") or []:
        if isinstance(r, dict) and r.get("watermark_handle"):
            h = "@" + str(r["watermark_handle"]).strip().lstrip("@")
            add({"handle": h, "variants": [h]}, f"review:{r.get('watched_by')}", None, None)
    for e in found:
        e["same_as_uploader"] = same_account(e["variants"], rec)
    return found


def original_upload_answer(rec: dict) -> tuple[str | None, dict | None]:
    """Latest reviewer answer to 'is this upload the original (not a re-upload)?': yes | no | None."""
    for r in reversed(rec.get("reviews") or []):
        if isinstance(r, dict) and r.get("original_upload") in ("yes", "no") and str(r.get("watched_by") or "").strip():
            return r["original_upload"], r
    return None, None


_UPLOADER_IS_AUTHOR = ("uploader(", "unknown(")


def refresh_provenance(rec: dict) -> dict:
    """original_author / reposter = description/metadata authorship (``authorship_base``) + repost evidence.

    - a reviewer who watched says the upload is the original (``original_upload: yes``): the uploader is the
      original author, unless the description itself credits another account (kept as it is);
    - a watermark handle of ANOTHER account burned into the picture, with no credit saying otherwise:
      re-upload -> ``reposter`` = uploader, ``original_author`` = the handle (basis says the handle's
      authorship itself is unverified);
    - a reviewer says it is NOT the original (``original_upload: no``): re-upload even without a watermark.
    Recency of a re-upload is then judged by the original's publish date (score.recency_for)."""
    base = rec.get("authorship_base") or {k: rec.get(k) for k in ("original_author", "original_author_basis",
                                                                  "reposter")}
    rec["authorship_base"] = {k: base.get(k) for k in ("original_author", "original_author_basis", "reposter")}
    oa, basis, reposter = base.get("original_author"), base.get("original_author_basis"), base.get("reposter")
    uploader = rec.get("uploader") or rec.get("uploader_id")
    ev = repost_evidence(rec)
    rec["repost_evidence"] = ev
    ans, rv = original_upload_answer(rec)
    uploader_basis = reposter is None and str(basis or "").startswith(_UPLOADER_IS_AUTHOR)
    other = [e for e in ev if e["same_as_uploader"] is False]
    if ans == "yes" and uploader_basis:
        oa = uploader or oa
        basis = f"review_original_upload({rv.get('watched_by')}: 원본 업로드라고 확인" + \
            (f"; 다른 계정 워터마크 {', '.join(e['handle'] for e in other)} 있음" if other else "") + ")"
    elif ans != "yes" and uploader_basis and other:
        e = other[0]
        oa = e["handle"]
        basis = (f"watermark_ocr(화면에 박힌 다른 계정 워터마크 {e['handle']}({', '.join(e['sources'])}) ≠ 업로더 "
                 f"{uploader} → 재업로드로 봄; 이 계정이 원작자인지는 미확인)")
        reposter = uploader
    if ans == "no" and reposter is None and uploader:
        reposter = uploader
        if _alnum(oa) == _alnum(uploader):
            oa = None
        basis = f"review_not_original({rv.get('watched_by')}: 재업로드라고 확인" + (f", 원작자 {oa}" if oa else ", 원작자 모름") + ")"
    rec.update({"original_author": oa, "original_author_basis": basis, "reposter": reposter})
    return rec


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
            "recency_basis", "recency_threshold_days", "checked_at", "unmeasured", "review_by", "format_facts",
            "upload_age_days", "originality")
    return {k: s.get(k) for k in keys}


def refresh_scores(rec: dict) -> dict:
    from .score import compute_scores

    refresh_provenance(rec)
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
        "authorship_base": authorship(it, credits),
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
    stub = bool((it.get("extra") or {}).get("manual_intake"))
    for k in _META_FIELDS:
        if it.get(k) not in (None, "", []):
            if stub and rec.get(k) not in (None, "", []):
                continue              # a blocked re-intake (URL stub) never overwrites what is already known
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
    base = authorship({**rec, "original_url": it.get("original_url") or old.get("original_url"),
                       "original_author_hint": it.get("original_author_hint") or old.get("original_author_hint")},
                      credits)
    rec["authorship_base"] = base
    rec.update(base)
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
        hit = exclusions.check_account(rec, ex_entries)       # the reference channel's own upload
        if hit:
            apply_overlap(rec, {**hit, "checked_at": now}, by="exclusions:account")
            continue
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
    handle = handle_from_url(url)       # the posting account is part of the canonical URL on some platforms
    return {"platform": platform, "platform_id": pid, "url": url, "title": None, "description": None,
            "uploader": handle, "uploader_id": handle, "views": None, "views_source": "unavailable",
            "views_note": f"메타데이터를 받지 못함({acc.get('platform_status')}) → 조회수 모름",
            "likes": None, "published_at": None, "_item_access": acc,
            "extra": {"manual_intake": True, **({"uploader_source": "url_path"} if handle else {})}}


MANUAL_FIELDS = ("uploader", "original_author", "original_url", "published_at", "original_published_at", "views",
                 "views_checked_at")


def apply_manual_provenance(rec: dict, *, by: str, fields: dict, note: str | None = None) -> tuple[dict, list[str]]:
    """Provenance a person saw on the platform page or elsewhere (a blocked platform's metadata, a credit
    found by Lens, ...).  Kept apart from platform metadata: every entry goes to ``manual_provenance[]``
    with who/when; platform metadata stays authoritative for the fields it has (uploader, published_at);
    ``views`` stays platform-only -- a seen view count goes to ``views_manual`` {views, checked_at,
    observed_by, where} (needs its check date; likes are never views).  Returns (record, Korean notes)."""
    from .score import parse_time

    by = str(by or "").strip()
    f = {k: v for k, v in (fields or {}).items() if k in MANUAL_FIELDS and v not in (None, "")}
    if not f:
        return rec, []
    if not by:
        raise ValueError("수동 출처 정보에는 --observed-by(직접 확인한 사람)가 필요함")
    for k in ("published_at", "original_published_at", "views_checked_at"):
        if k in f and parse_time(str(f[k])) is None:
            raise ValueError(f"--{k.replace('_', '-')} 날짜 형식 오류: {f[k]}")
    if ("views" in f) != ("views_checked_at" in f):
        raise ValueError("--views 와 --views-checked-at(조회수를 본 날짜)은 함께 줘야 함")
    if "views" in f:
        v = f["views"]
        if not (isinstance(v, int) and not isinstance(v, bool) and v >= 0):
            raise ValueError("--views 는 0 이상의 정수(조회수/재생수만, 좋아요 아님)")
    now = now_iso()
    msgs: list[str] = []
    src = f"manual_observation:{by}"
    if "uploader" in f:
        if rec.get("uploader") and _alnum(rec["uploader"]) != _alnum(f["uploader"]) and \
                (rec.get("extra") or {}).get("uploader_source") != "url_path":
            msgs.append(f"업로더: 플랫폼 메타데이터 '{rec['uploader']}' 유지(수동 입력 '{f['uploader']}' 은 기록만)")
        else:
            rec["uploader"] = f["uploader"]
            rec.setdefault("extra", {})["uploader_source"] = src
    if "published_at" in f:
        if rec.get("published_at") and rec.get("published_at_source") and \
                not str(rec.get("published_at_source")).startswith("manual_observation"):
            msgs.append(f"게시일: 플랫폼 메타데이터 {rec['published_at']} 유지(수동 입력 {f['published_at']} 은 기록만)")
        else:
            rec["published_at"], rec["published_at_source"] = str(f["published_at"]), src
    if "original_url" in f:
        rec["original_url"] = f["original_url"]
    if "original_published_at" in f:
        rec["original_published_at"] = str(f["original_published_at"])
        rec["original_published_at_source"] = src
    if "original_author" in f:
        rec["original_author_hint"] = {"name": f["original_author"], "basis": f"manual_observation({by})",
                                       "url": f.get("original_url") or rec.get("original_url")}
    if "views" in f:
        rec["views_manual"] = {"views": f["views"], "checked_at": str(f["views_checked_at"]), "observed_by": by,
                               "where": rec.get("url"), "note": "사람이 직접 본 조회수(플랫폼 메타데이터 아님)"}
    rec.setdefault("manual_provenance", []).append({"at": now, "by": by, "fields": f, "note": note})
    base = authorship(rec, rec.get("credits") or [])
    rec["authorship_base"] = base
    rec.update(base)
    return refresh_scores(rec), msgs


def intake_url(url: str, *, keywords: Iterable[str] = (), note: str | None = None) -> tuple[dict, dict]:
    """Manual intake of one URL: fetch metadata (if reachable) and upsert. Returns (record, log row).
    Provenance a person knows (blocked platform) is added with :func:`apply_manual_provenance`."""
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
    refresh_provenance(c)            # overlay records / reviews added since the last save count too
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


def find_by_url(url: str | None, rows: list[dict] | None = None) -> list[dict]:
    """Records whose own URL is the same item as ``url`` (canonical url_key equality)."""
    k = url_key(url)
    if not k:
        return []
    return [r for r in (rows if rows is not None else load()) if url_key(r.get("url")) == k]


def link_original(dirty_id: str, clean_id: str, *, by: str, note: str, unlink: bool = False) -> tuple[dict, dict]:
    """Record that ``clean_id`` is a clean original (same content, no burned-in overlay) of ``dirty_id``:
    ``dirty.alternates[] = {id, linked_by, linked_at, note, basis}`` and ``clean.alternate_of[]``.

    ``shortkit clean plan`` on the dirty source then checks the clean file with its own overlay
    detection and, when it is clean at the dirty overlays' positions, plans a source replacement
    (step 1 of the required order: clean original -> crop -> local restoration).  ``by`` and ``note``
    are required: the link is a person's statement that both files show the same recording."""
    if dirty_id == clean_id:
        raise ValueError("같은 후보를 자기 자신의 원본으로 연결할 수 없음")
    if not str(by or "").strip() or not str(note or "").strip():
        raise ValueError("--by(확인한 사람)와 --note(어떻게 같은 녹화임을 확인했는지)가 필요함")
    rows = load()
    dirty, clean = get(dirty_id, rows), get(clean_id, rows)
    now = now_iso()
    alts = [a for a in (dirty.get("alternates") or [])
            if (a if isinstance(a, str) else (a.get("id") or a.get("warehouse_id"))) != clean_id]
    back = [x for x in (clean.get("alternate_of") or []) if x != dirty_id]
    if not unlink:
        if clean.get("status") in ("excluded", "rejected") or (clean.get("reference_overlap") or {}).get("excluded") is True:
            raise SelectionError(f"{clean_id} 는 상태가 {clean.get('status')} (레퍼런스와 같은 녹화/탈락) 라서 원본으로 쓸 수 없음")
        alts.append({"id": clean_id, "linked_by": by.strip(), "linked_at": now, "note": note.strip(),
                     "basis": "manual_same_content"})
        back.append(dirty_id)
    dirty["alternates"] = alts
    clean["alternate_of"] = back
    dirty.setdefault("provenance_log", []).append({"at": now, "by": by.strip(), "action": "unlink_original" if unlink
                                                   else "link_original", "other": clean_id, "note": note.strip()})
    save(rows)
    return dirty, clean


def mark_used(cid: str, episode_id: str, by: str = "user") -> dict:
    """Record that a selected candidate is used in an episode (plan.yaml sources[].warehouse_id)."""
    c = get(cid)
    set_status(c, "used", by, f"에피소드 {episode_id} 에 사용")
    eps = c.setdefault("used_in", [])
    if episode_id not in eps:
        eps.append(episode_id)
    put(c)
    return c
