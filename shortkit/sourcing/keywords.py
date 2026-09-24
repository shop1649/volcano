"""Search query sets: ``warehouse/queries.yaml``.

Two strictly separated origins:
  reference_derived  keywords / source accounts traced from the reference channel.  They come ONLY
                     from ``warehouse/source_accounts.json`` (written by the reference trace step).
                     While that file is missing or unmeasured, this set is empty and reported as
                     미확보(못 잼) -- nothing is invented from the channel name or guesses.
  user_generic       queries the user adds by hand (``shortkit source queries --add``).

``source_accounts.json`` accepted shape (written by the reference module)::

    {"status": "measured|unmeasured", "blocker": null|"...", "traced_at": "...",
     "accounts": [{"platform", "handle", "url", "count", "evidence": [{"ref_video_id", "t"}]}],
     "keywords": [{"keyword", "platforms": [...], "count", "evidence": [...]}]}
"""
from __future__ import annotations

import re
from typing import Iterable

from .. import paths
from ..util.jsonio import now_iso, read_json, read_yaml, write_yaml
from .platforms import PLATFORMS

QUERIES = "warehouse/queries.yaml"
SOURCE_ACCOUNTS = "warehouse/source_accounts.json"
UNMEASURED_KO = "미확보(못 잼)"


def load_queries() -> dict:
    d = read_yaml(paths.absp(QUERIES), {}) or {}
    d.setdefault("user_generic", [])
    return d


def reference_derived() -> dict:
    """Reference-traced keywords/accounts, or an explicit 미확보(못 잼) status."""
    p = paths.absp(SOURCE_ACCOUNTS)
    data = read_json(p, None)
    if not data:
        return {"status": "unmeasured", "label": UNMEASURED_KO, "queries": [], "accounts": [],
                "note": f"{SOURCE_ACCOUNTS} 없음 — 레퍼런스 추적 단계가 아직 소스 계정/키워드를 기록하지 않음"}
    if data.get("status") != "measured":
        return {"status": "unmeasured", "label": UNMEASURED_KO, "queries": [], "accounts": [],
                "note": data.get("blocker") or f"{SOURCE_ACCOUNTS} 상태가 measured 아님"}
    qs = []
    for k in data.get("keywords") or []:
        if isinstance(k, dict) and k.get("keyword"):
            qs.append({"query": k["keyword"], "platforms": list(k.get("platforms") or PLATFORMS),
                       "origin": "reference_derived", "count": k.get("count"), "evidence": k.get("evidence") or []})
    accts = []
    for a in data.get("accounts") or []:
        if isinstance(a, dict) and (a.get("handle") or a.get("url")):
            pf = a.get("platform")
            q = a.get("url") or ("@" + str(a["handle"]).lstrip("@"))
            accts.append({"query": q, "platforms": [pf] if pf in PLATFORMS else list(PLATFORMS),
                          "origin": "reference_derived_account", "count": a.get("count"),
                          "evidence": a.get("evidence") or []})
    return {"status": "measured", "label": "확보", "queries": qs, "accounts": accts,
            "note": f"{SOURCE_ACCOUNTS} ({data.get('traced_at')})"}


def user_queries() -> list[dict]:
    out = []
    for q in load_queries().get("user_generic") or []:
        if isinstance(q, str):
            q = {"query": q}
        if isinstance(q, dict) and q.get("query"):
            out.append({"query": str(q["query"]), "platforms": list(q.get("platforms") or PLATFORMS),
                        "origin": "user_generic", "added_by": q.get("added_by"), "added_at": q.get("added_at"),
                        "note": q.get("note")})
    return out


def all_queries() -> list[dict]:
    ref = reference_derived()
    return [*ref["queries"], *ref["accounts"], *user_queries()]


def add_user_query(query: str, platforms: Iterable[str] | None = None, added_by: str = "user",
                   note: str | None = None) -> dict:
    q = query.strip()
    if not q:
        raise ValueError("빈 검색어")
    pfs = [p for p in (platforms or PLATFORMS)]
    bad = [p for p in pfs if p not in PLATFORMS]
    if bad:
        raise ValueError(f"알 수 없는 플랫폼: {bad}")
    d = load_queries()
    for e in d["user_generic"]:
        if isinstance(e, dict) and e.get("query") == q:
            e["platforms"] = sorted(set(e.get("platforms") or []) | set(pfs))
            write_yaml(paths.absp(QUERIES), d)
            return e
    e = {"query": q, "platforms": pfs, "added_by": added_by, "added_at": now_iso(), "note": note}
    d["user_generic"].append(e)
    write_yaml(paths.absp(QUERIES), d)
    return e


def to_hashtag(keyword: str) -> str:
    k = re.sub(r"[\s\-]+", "", keyword.strip().lstrip("#"))
    return re.sub(r"[^\w]", "", k, flags=re.UNICODE).lower()
