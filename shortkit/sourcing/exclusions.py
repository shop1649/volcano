"""Reference-footage exclusion list (``warehouse/exclusions.jsonl``, CONTRACT §11).

The same *keyword* as the reference is fine; the same *recording* is not.  Entries::

    {"kind": "reference_footage", "ref_video_id", "ref_url", "original_urls": [], "phash": ["<16 hex>"...],
     "frame_times": [...], "added_at", "added_by"}
    {"kind": "url", "url", "reason", "added_at", "added_by"}

Match rule: candidate keyframe pHash vs an entry's pHashes, Hamming distance <= 10 on >= 3 candidate
keyframes -> excluded; or URL / original_url equality (canonical ``url_key``) -> excluded.

Keyframes: uniformly sampled frames (flat/black frames skipped, black borders trimmed).  Each candidate
keyframe is compared as-is, horizontally mirrored, and -- for vertical frames -- as the centred 16:9
band (the usual layout of a landscape clip reposted as a 9:16 Short).  Heavy crops, blurred-background
layouts that shrink the clip, or overlays covering most of the frame are NOT guaranteed to match; a
reviewer still watches the candidate.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

import numpy as np

from .. import paths
from ..util.jsonio import append_jsonl, now_iso, read_jsonl
from .platforms import scrub, url_key

EXCLUSIONS = "warehouse/exclusions.jsonl"
PHASH_MAX_DIST = 10
MIN_MATCH_KEYFRAMES = 3
DEFAULT_KEYFRAMES = 24
METHOD = f"phash(hamming<={PHASH_MAX_DIST}, >={MIN_MATCH_KEYFRAMES} keyframes; as-is/mirrored/16:9 centre band)"


# ----------------------------------------------------------------------------- storage
def load(path: str | Path | None = None) -> list[dict]:
    return [e for e in read_jsonl(paths.absp(path or EXCLUSIONS)) if isinstance(e, dict)]


def add_url(url: str, reason: str, added_by: str, path: str | Path | None = None) -> dict:
    e = {"kind": "url", "url": url, "reason": reason, "added_at": now_iso(), "added_by": added_by}
    append_jsonl(paths.absp(path or EXCLUSIONS), e)
    return e


def add_reference_footage(video: str | Path, ref_video_id: str, *, ref_url: str | None = None,
                          original_urls: Iterable[str] = (), added_by: str = "shortkit",
                          n_frames: int = 40, region: dict | None = None,
                          path: str | Path | None = None) -> dict:
    """Fingerprint a reference video file and append a ``reference_footage`` entry.

    ``region`` = the footage area inside the reference frame ``{x, y, w, h}`` in the reference video's own
    pixels (e.g. ``layout.json`` ``video_region``), so titles/captions around the footage are not hashed.
    It is stored together with the resolution it refers to."""
    from ..util.media import probe

    kf = keyframe_hashes(video, n=n_frames, variants=False, region=region)
    info = probe(video)
    e = {"kind": "reference_footage", "ref_video_id": ref_video_id, "ref_url": ref_url,
         "original_urls": list(original_urls), "phash": [k["phash"] for k in kf],
         "frame_times": [k["t"] for k in kf], "added_at": now_iso(), "added_by": added_by,
         "region": ({**{k: region[k] for k in ("x", "y", "w", "h")}, "resolution": [info.width, info.height]}
                    if region else None),
         "method": "imagehash.phash 64-bit (16 hex) of grayscale frames (<=480 px wide), flat frames skipped, "
                   "black borders trimmed" + (", footage region cropped" if region else "")}
    append_jsonl(paths.absp(path or EXCLUSIONS), e)
    return e


# ----------------------------------------------------------------------------- hashing
def _trim_borders(gray: np.ndarray, thr: float = 18.0) -> np.ndarray:
    """Remove uniform dark borders (letterbox/pillarbox)."""
    h, w = gray.shape
    rows = np.where((gray.mean(axis=1) > thr) | (gray.std(axis=1) > 8))[0]
    cols = np.where((gray.mean(axis=0) > thr) | (gray.std(axis=0) > 8))[0]
    if rows.size == 0 or cols.size == 0:
        return gray
    y0, y1, x0, x1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
    if (y1 - y0) < h * 0.3 or (x1 - x0) < w * 0.3:
        return gray
    return gray[y0:y1, x0:x1]


def phash_gray(gray: np.ndarray) -> str:
    import imagehash
    from PIL import Image

    return str(imagehash.phash(Image.fromarray(gray)))


def hamming(a: str, b: str) -> int:
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def _is_flat(gray: np.ndarray) -> bool:
    return float(gray.std()) < 6.0


def frame_hashes(rgb_or_gray: np.ndarray, variants: bool = True) -> list[str]:
    """pHash of a frame (+ mirrored, + centred 16:9 band for vertical frames when ``variants``)."""
    g = rgb_or_gray
    if g.ndim == 3:
        g = (0.299 * g[..., 0] + 0.587 * g[..., 1] + 0.114 * g[..., 2]).astype(np.uint8)
    g = _trim_borders(g)
    out = [phash_gray(g)]
    if variants:
        out.append(phash_gray(np.ascontiguousarray(g[:, ::-1])))
        h, w = g.shape
        if h > w * 1.2:
            bh = int(round(w * 9 / 16))
            y0 = (h - bh) // 2
            band = _trim_borders(g[y0:y0 + bh])
            out.append(phash_gray(band))
            out.append(phash_gray(np.ascontiguousarray(band[:, ::-1])))
    return out


def keyframe_hashes(video: str | Path, n: int = DEFAULT_KEYFRAMES, variants: bool = True,
                    region: dict | None = None) -> list[dict]:
    """Uniformly sampled, non-flat keyframes: ``[{t, phash, variants?}]``.

    ``region`` ({x, y, w, h} in the video's own pixels) crops each frame before hashing."""
    from ..util.media import iter_frames, probe

    info = probe(video)
    if not info.width or not info.height or info.duration <= 0:
        return []
    fps = max(0.05, min(10.0, n / max(info.duration, 0.1)))
    width = min(info.width, 480)
    k = width / info.width
    out = []
    for t, fr in iter_frames(video, fps=fps, width=width, gray=True):
        if region:
            x0, y0 = int(round(region["x"] * k)), int(round(region["y"] * k))
            x1, y1 = int(round((region["x"] + region["w"]) * k)), int(round((region["y"] + region["h"]) * k))
            fr = np.ascontiguousarray(fr[max(0, y0):y1, max(0, x0):x1])
            if fr.size == 0:
                continue
        if _is_flat(fr):
            continue
        hs = frame_hashes(fr, variants=variants)
        row = {"t": round(float(t), 3), "phash": hs[0]}
        if variants:
            row["variants"] = hs
        out.append(row)
        if len(out) >= n:
            break
    return out


# ----------------------------------------------------------------------------- checks
def check_urls(urls: Iterable[str | None], entries: list[dict] | None = None) -> dict | None:
    """URL rule: canonical equality of any candidate URL with an exclusion URL / reference URL."""
    entries = load() if entries is None else entries
    keys = {url_key(u): u for u in urls if u}
    keys.pop(None, None)
    if not keys:
        return None
    for e in entries:
        if e.get("kind") == "url":
            ex = [e.get("url")]
            ref_id = e.get("ref_video_id")
        elif e.get("kind") == "reference_footage":
            ex = [e.get("ref_url"), *(e.get("original_urls") or [])]
            ref_id = e.get("ref_video_id")
        else:
            continue
        for u in ex:
            k = url_key(u)
            if k and k in keys:
                return {"excluded": True, "matched_ref_video_id": ref_id, "distance": 0, "method": "url",
                        "matched_url": u, "note": e.get("reason") or "레퍼런스(또는 그 원본) URL 과 같음"}
    return None


def check(candidate: dict | None = None, *, video_path: str | Path | None = None,
          keyframes: list[dict] | None = None, urls: Iterable[str] | None = None,
          entries: list[dict] | None = None, n_keyframes: int = DEFAULT_KEYFRAMES) -> dict:
    """Is this candidate the same recording as reference footage?

    Returns ``{excluded: True|False|None, matched_ref_video_id, distance, method, matched_keyframes,
    n_keyframes, checked_at, note}``.  ``excluded=None`` means 못 잼 (no fingerprints / no frames)."""
    entries = load() if entries is None else entries
    now = now_iso()
    cand_urls = list(urls or [])
    if candidate:
        cand_urls += [candidate.get("url"), candidate.get("original_url")]
        if video_path is None and candidate.get("download_path"):
            video_path = candidate["download_path"]
    hit = check_urls(cand_urls, entries)
    if hit:
        return {**hit, "matched_keyframes": None, "n_keyframes": None, "checked_at": now}
    refs = []
    for e in entries:
        if e.get("kind") != "reference_footage":
            continue
        ints = []
        for h in e.get("phash") or []:
            try:
                ints.append(int(str(h), 16))
            except ValueError:
                continue
        if ints:
            refs.append((e, ints))
    base = {"excluded": None, "matched_ref_video_id": None, "distance": None, "method": METHOD,
            "matched_keyframes": 0, "n_keyframes": 0, "n_refs": len(refs), "checked_at": now}
    if not refs:
        return {**base, "method": "url_only" if any(cand_urls) else "none",
                "note": "레퍼런스 영상 지문(exclusions.jsonl reference_footage) 없음 → 같은 녹화 여부 못 잼 "
                        "(URL 규칙만 확인)"}
    if keyframes is None:
        if video_path is None:
            return {**base, "note": "영상 파일/키프레임 없음 → 지문 비교 못 함(다운로드 후 다시 검사)"}
        vp = paths.absp(video_path)
        if not vp.is_file():
            return {**base, "note": scrub(f"파일 없음: {video_path}")}
        keyframes = keyframe_hashes(vp, n=n_keyframes)
    base["n_keyframes"] = len(keyframes)
    if len(keyframes) < MIN_MATCH_KEYFRAMES:
        return {**base, "note": f"쓸 수 있는 키프레임이 {len(keyframes)}장뿐(<{MIN_MATCH_KEYFRAMES}) → 못 잼"}
    best = None
    for e, ref_ints in refs:
        dists = []
        for k in keyframes:
            hs = k.get("variants") or [k["phash"]]
            d = min(bin(int(h, 16) ^ r).count("1") for h in hs for r in ref_ints)
            dists.append(d)
        matched = [d for d in dists if d <= PHASH_MAX_DIST]
        row = {"ref": e.get("ref_video_id"), "matched": len(matched),
               "median_matched": int(np.median(matched)) if matched else None, "min": min(dists)}
        key = (row["matched"], -row["min"])
        if best is None or key > best[0]:
            best = (key, row)
    row = best[1]
    if row["matched"] >= MIN_MATCH_KEYFRAMES:
        return {**base, "excluded": True, "matched_ref_video_id": row["ref"], "distance": row["median_matched"],
                "matched_keyframes": row["matched"],
                "note": f"키프레임 {row['matched']}/{len(keyframes)}장이 레퍼런스 {row['ref']} 와 거리 "
                        f"<= {PHASH_MAX_DIST} → 같은 녹화"}
    return {**base, "excluded": False, "matched_ref_video_id": None, "distance": row["min"],
            "matched_keyframes": row["matched"], "closest_ref_video_id": row["ref"],
            "note": f"등록된 레퍼런스 지문 {len(refs)}편 기준 — 가장 가까운 {row['ref']}: 최소 거리 {row['min']}, "
                    f"일치 키프레임 {row['matched']}장(<{MIN_MATCH_KEYFRAMES}) → 다른 녹화. 지문이 등록되지 않은 레퍼런스 "
                    "영상과의 중복은 판단 못 함(그림 로고/크롭 변형은 검토자 확인 필요)"}
