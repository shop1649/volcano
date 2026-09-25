"""Trace where the reference channel's footage comes from, and fence it off for sourcing.

Default targets (`ref trace`): latest100 ∪ high_views ∪ downloaded.  Per reference video:
  * description credits: lines with 출처/원본/source/credit/cr./via/©, @handles, u/ r/ names,
    URLs (platform + account parsed from tiktok/instagram/reddit/youtube/x/facebook URLs), hashtags;
    EVERY URL that is not the reference channel itself goes to the URL exclusions (YouTube included;
    ``credit_line`` recorded as a field, never used as a filter);
  * script: the reference's own on-screen caption text (``analysis/<id>/captions.json`` from `ref analyze`
    -- for these captioned shorts the captions ARE the script) and, when present,
    ``analysis/<id>/audio/transcript.json`` (`ref transcribe`, optional faster-whisper ASR);
  * on-screen credits: static overlay lines over the WHOLE frame (credits are often printed in the
    bands around the footage) read with tesseract ``eng --psm 7`` (TikTok / Instagram / Reddit style
    ``@user``, ``u/user``), kept when seen in >= 2 frames or with confidence >= 70, plus handle /
    credit lines found in the reference's captions.json;
  * keyframes for a manual Google Lens search: ``analysis/<id>/lens/*.jpg`` + ``lens_queries.md``
    + ``lens_results.csv`` (filled by the person who ran the search; rows with ``checked_by`` count
    as searched, a filled ``original_url`` is read back as a traced original).  Lens itself is not
    automated (and is blocked here).
Every upload of the reference channel (all_videos.json) becomes a URL exclusion, and an ``account`` row
names the reference channel itself (sourcing rejects the channel's own uploads).

Aggregates ``warehouse/source_accounts.json`` (shape read by
``shortkit.sourcing.keywords.reference_derived``)::

    {"status": "measured|unmeasured", "blocker", "traced_at",
     "stage": {"status", "blocker", "channels": {description|script|on_screen|lens|fingerprint:
               {covered, target, missing}}, "impact", "state", "exclusion_fingerprints"},
     "accounts": [{"platform", "handle", "url", "count", "evidence": [{"ref_video_id", "t", ...}],
                   "verified_by_text"}],
     "keywords": [{"keyword", "platforms", "count", "evidence": [{"ref_video_id", "t", ...}]}]}

``status`` says the listed accounts / keywords are measured results (sourcing uses them); whether the
reverse-trace STAGE is complete is ``stage.status`` (every channel over every target video) --
``stage_status()`` gives the row for `shortkit preset unresolved`.

``count`` = number of distinct reference videos; ``t`` = time in the reference video (null for
description text, which has no time).  With no traced video the file is still written, as
``status: unmeasured`` with the blocker (e.g. the ``ref collect`` block recorded in latest100.json).

Reference-footage exclusions go to ``warehouse/exclusions.jsonl`` (docs/CONTRACT.md section 11)
through ``shortkit.sourcing.exclusions.add_reference_footage`` -- the SAME keyframe hashing the
sourcing side applies to candidates (grayscale <= 480 px wide, flat frames skipped, black borders
trimmed, cropped to the footage region stored with its resolution) -- plus the reference URL and
every traced original URL.  The reference channel's own handles are never reported as sources.
"""
from __future__ import annotations

import difflib
import re
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import urlparse

import numpy as np

from .. import paths
from ..config import load_preset
from ..sourcing import exclusions as X
from ..sourcing.platforms import PLATFORMS as SOURCE_PLATFORMS
from ..sourcing.platforms import url_key
from ..util.jsonio import append_jsonl, now_iso, read_json, write_json
from ..util.media import probe, read_frames
from .common import (analysis_dir, detect_video_region, load_snapshot, read_csv_rows, reference_dir, region_or_full,
                     say, snapshot_blocker, video_path, warn, write_csv_rows)

ADDED_BY = "shortkit ref trace"
SOURCE_ACCOUNTS_SCHEMA = "shortkit.source_accounts/2"
N_KEYFRAMES = 60          # reference keyframes fingerprinted per video (candidates use sourcing's default)
URL_RE = re.compile(r"https?://[^\s)>\]\"'<>，、]+", re.I)
HANDLE_RE = re.compile(r"(?<![\w@.])@([A-Za-z0-9_](?:[A-Za-z0-9_.]{0,28}[A-Za-z0-9_])?)")
REDDIT_RE = re.compile(r"(?<![\w/])(u|r)/([A-Za-z0-9_]{2,24})")
HASHTAG_RE = re.compile(r"#([0-9A-Za-z_가-힣]{2,30})")
CREDIT_RE = re.compile(r"(출처|원본|영상\s*출처|원작|제보|source|credits?|cr\.|via|©|ⓒ|original)", re.I)
PLATFORM_WORDS = {"tiktok": ("tiktok", "틱톡", "douyin", "도우인"), "instagram": ("instagram", "인스타", "insta", "ig "),
                  "reddit": ("reddit", "레딧"), "youtube": ("youtube", "유튜브"), "x": ("twitter", "트위터", " x "),
                  "facebook": ("facebook", "페이스북")}
LENS_HEADER = ["image", "original_url", "platform", "account", "checked_by", "checked_at", "notes"]
STOP = {"영상", "출처", "구독", "좋아요", "댓글", "shorts", "short", "the", "and", "for", "you", "this", "that"}


# ============================================================================= parsing
def platform_of_url(url: str) -> tuple[str | None, str | None]:
    """(platform, account) from a URL; account None when the URL does not name one."""
    try:
        u = urlparse(url)
    except ValueError:
        return None, None
    host = (u.netloc or "").lower().split(":")[0]
    host = host[4:] if host.startswith("www.") else host
    host = host[2:] if host.startswith("m.") else host
    parts = [p for p in (u.path or "").split("/") if p]
    if host.endswith("tiktok.com"):
        acc = next((p for p in parts if p.startswith("@")), None)
        return "tiktok", acc
    if host.endswith("instagram.com"):
        if parts and parts[0] not in ("p", "reel", "reels", "tv", "stories", "explore"):
            return "instagram", "@" + parts[0]
        if len(parts) >= 2 and parts[0] == "stories":
            return "instagram", "@" + parts[1]
        return "instagram", None
    if host.endswith("reddit.com") or host == "redd.it":
        if len(parts) >= 2 and parts[0] in ("r", "u", "user"):
            return "reddit", ("u/" if parts[0] in ("u", "user") else "r/") + parts[1]
        return "reddit", None
    if host.endswith("youtube.com") or host == "youtu.be":
        acc = next((p for p in parts if p.startswith("@")), None)
        if not acc and len(parts) >= 2 and parts[0] in ("channel", "c", "user"):
            acc = f"{parts[0]}/{parts[1]}"
        return "youtube", acc
    if host in ("twitter.com", "x.com"):
        return "x", ("@" + parts[0]) if parts and parts[0] not in ("i", "search", "hashtag") else None
    if host.endswith("facebook.com") or host == "fb.watch":
        return "facebook", parts[0] if parts and parts[0] not in ("watch", "reel", "share") else None
    return (host or None), None


def _platform_hint(line: str) -> str | None:
    low = f" {line.lower()} "
    for p, words in PLATFORM_WORDS.items():
        if any(w in low for w in words):
            return p
    return None


def parse_description(text: str, own: set[str]) -> dict:
    """Credits, handles, urls and hashtags from a video description."""
    accounts, urls, tags, credit_lines = [], [], [], []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        is_credit = bool(CREDIT_RE.search(line))
        if is_credit:
            credit_lines.append(line)
        hint = _platform_hint(line)
        for u in URL_RE.findall(line):
            u = u.rstrip(".,;:!?")
            plat, acc = platform_of_url(u)
            urls.append({"url": u, "platform": plat, "account": acc, "credit_line": is_credit})
            if acc and not _is_own(acc, own):
                accounts.append({"platform": plat, "account": acc, "kind": "description_url", "text": line[:200],
                                 "url": profile_url_from(u, plat, acc)})
        stripped = URL_RE.sub(" ", line)
        for h in HANDLE_RE.findall(stripped):
            acc = "@" + h
            if _is_own(acc, own):
                continue
            accounts.append({"platform": hint or "unknown", "account": acc,
                             "kind": "description_credit" if is_credit else "description_handle", "text": line[:200]})
        for kind, name in REDDIT_RE.findall(stripped):
            accounts.append({"platform": "reddit", "account": f"{kind}/{name}", "kind": "description_reddit",
                             "text": line[:200]})
        tags += [t for t in HASHTAG_RE.findall(stripped) if t.lower() not in STOP and not _is_own(t, own)]
    return {"accounts": accounts, "urls": urls, "hashtags": tags, "credit_lines": credit_lines}


def profile_url_from(url: str, platform: str | None, account: str | None) -> str | None:
    """The account part of an OBSERVED post/profile URL (``https://www.tiktok.com/@u/video/1`` ->
    ``https://www.tiktok.com/@u``).  Only a prefix of the URL that was actually read is returned;
    nothing is built from a bare handle."""
    if not url or not account:
        return None
    try:
        u = urlparse(url)
    except ValueError:
        return None
    parts = [p for p in (u.path or "").split("/") if p]
    name = account.lstrip("@").split("/")[-1]
    for i, p in enumerate(parts):
        if p.lstrip("@") == name:
            return f"{u.scheme or 'https'}://{u.netloc}/" + "/".join(parts[:i + 1])
    return None


def reddit_url(handle: str) -> str | None:
    """``r/sub`` / ``u/name`` ARE Reddit paths, so their address is fixed by the handle itself."""
    m = re.fullmatch(r"([ur])/([A-Za-z0-9_]{2,24})", handle or "")
    if not m:
        return None
    return f"https://www.reddit.com/{'r' if m.group(1) == 'r' else 'user'}/{m.group(2)}/"


def _norm(s: str) -> str:
    return re.sub(r"[^0-9a-z가-힣]", "", (s or "").lower())


def _is_own(acc: str, own: set[str]) -> bool:
    a = _norm(acc)
    return bool(a) and any(o and (o in a) for o in own)


def own_identity(preset: str) -> set[str]:
    pr = load_preset(preset)
    own = {_norm(pr.get("reference.channel_handle", "") or "")}
    for t in pr.get("identity_exclusions.forbidden_text", []) or []:
        n = _norm(t)
        if n and re.fullmatch(r"[0-9a-z]+", n):
            own.add(n)
    return {o for o in own if len(o) >= 4}


# ============================================================================= watermark OCR
def ocr_watermarks(video: Path, region: dict, fps: float = 0.5, own: set[str] | None = None) -> list[dict]:
    """Burned-in handles (``@user``, ``u/user``, ``r/sub``) inside the footage region.

    Static overlay lines are found with the caption line detector (pixels unchanged between two
    samples 1/fps apart -- a reposter's watermark stays while the footage moves), each line is
    binarized and read with tesseract ``eng --psm 7``.
    """
    import cv2

    from .textboxes import detect_lines

    info = probe(video)
    times = [float(t) for t in np.arange(0.25, max(0.3, info.duration - 0.1), 1.0 / fps)]
    x0, y0, w0, h0 = region["x"], region["y"], region["w"], region["h"]
    hits: dict[str, list[dict]] = defaultdict(list)
    prev = None
    for t in times:
        try:
            fr = read_frames(video, [t])[0]
        except Exception:
            continue
        crop = np.ascontiguousarray(fr[y0:y0 + h0, x0:x0 + w0])
        gray = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
        if prev is None or prev.shape != gray.shape:
            prev = gray
            continue
        boxes, _ = detect_lines(crop, prev)
        prev = gray
        for (bx, by, bw, bh) in boxes:
            if bh > 0.08 * h0:
                continue
            for acc, conf in _read_handles(crop, (bx, by, bw, bh)):
                if own and _is_own(acc, own):
                    continue
                if any(h["t"] == round(t, 2) for h in hits[acc]):
                    continue
                hits[acc].append({"t": round(t, 2), "conf": conf, "text": acc, "bbox": [bx + x0, by + y0, bw, bh]})
    # partial readings of one handle ("@fake_re", "@fakere", "@fake_repos") are merged by their
    # normalized prefix; the most frequent longest reading is reported, all variants are kept
    groups: list[dict] = []
    for acc in sorted(hits, key=lambda a: -len(_norm(a))):
        k = _norm(acc)
        g = next((g for g in groups if g["key"].startswith(k) or
                  (min(len(k), len(g["key"])) >= 6 and
                   difflib.SequenceMatcher(None, k, g["key"][:max(len(k), 1)]).ratio() >= 0.85)), None)
        if g is None:
            groups.append({"key": k, "reads": list(hits[acc]), "variants": {acc: len(hits[acc])}})
        else:
            g["reads"].extend(hits[acc])
            g["variants"][acc] = g["variants"].get(acc, 0) + len(hits[acc])
    out = []
    for g in groups:
        hs = g["reads"]
        frames = sorted({h["t"] for h in hs})
        if len(frames) >= 2 or max(h["conf"] for h in hs) >= 70:
            best = max(g["variants"], key=lambda v: (g["variants"][v], len(_norm(v))))
            out.append({"platform": "reddit" if re.match(r"[ur]/", best) else "unknown(watermark)",
                        "account": best, "kind": "watermark_ocr", "verified": False,
                        "note": "OCR 판독(끝 글자·밑줄 누락 가능) — 검색 단서로만 사용",
                        "variants": g["variants"], "frames": frames[:20], "bbox": hs[0]["bbox"],
                        "conf": round(float(np.mean([h["conf"] for h in hs])), 1), "text": best, "reads": len(hs)})
    return out


_HANDLE_IN_TEXT = re.compile(r"(@[A-Za-z0-9_][A-Za-z0-9_.]{2,29}|(?<![A-Za-z0-9])[ur]/[A-Za-z0-9_]{2,24})")


def _read_handles(crop: np.ndarray, box) -> list[tuple[str, float]]:
    """Handle readings of one overlay line.  The line is read at two widths (a watermark that
    overruns its backing box gets glued to the box edge and cut short by the line detector, but a
    very wide crop picks up scenery), from its fill mask and from the gray crop in both
    polarities.  Every reading with confidence >= 60 is returned; the caller keeps the variant
    seen in the most frames."""
    import cv2
    import pytesseract

    from .textboxes import _ocr_once, segment_line

    bx, by, bw, bh = box
    H, W = crop.shape[:2]
    best: dict[str, float] = {}
    for fac in (1.0, 2.0):
        ex = int(fac * bh)
        pad = max(6, bh // 2)
        x0, y0 = max(0, bx - ex - pad), max(0, by - pad)
        x1, y1 = min(W, bx + bw + ex + pad), min(H, by + bh + pad)
        sub = crop[y0:y1, x0:x1]
        reads: list[tuple[str, float]] = []
        cx = max(0, bx - ex - x0)
        seg = segment_line(sub, (cx, by - y0, min(bw + 2 * ex, x1 - x0 - cx), bh))
        if seg is not None:
            reads.append(_ocr_once(seg["fill"], seg["fill_bbox"], 40.0, "eng"))
        g = cv2.cvtColor(sub, cv2.COLOR_RGB2GRAY)
        g = cv2.resize(g, None, fx=40.0 / max(1, bh), fy=40.0 / max(1, bh), interpolation=cv2.INTER_CUBIC)
        for img in (255 - g, g):
            try:
                d = pytesseract.image_to_data(img, lang="eng", config="--psm 7", output_type=pytesseract.Output.DICT,
                                              timeout=30)
            except Exception:
                continue
            words = [(w, float(c)) for w, c in zip(d.get("text", []), d.get("conf", [])) if (w or "").strip()]
            if words:
                reads.append(("".join(w for w, _ in words), float(np.mean([c for _, c in words]))))
        for txt, conf in reads:
            if conf < 60:
                continue
            for m in _HANDLE_IN_TEXT.finditer(txt or ""):
                acc = m.group(1).rstrip(".:")
                best[acc] = max(best.get(acc, 0.0), conf)
    return sorted(best.items(), key=lambda kv: -kv[1])


# ============================================================================= footage region / fingerprint
def footage_region(preset: str, vid: str, video: Path) -> tuple[dict | None, dict]:
    """Rectangle where the footage plays inside the reference frame, in THIS file's pixels, or None
    when the footage fills the frame (or no region was found: the whole frame is then hashed, black
    borders trimmed).  Taken from ``analysis/<id>/layout.json`` (``ref analyze``; rescaled when that
    analysis ran on a file of another resolution), else detected now with the same detector."""
    info = probe(video)
    W, H = int(info.width), int(info.height)
    lay = read_json(analysis_dir(preset, vid) / "layout.json") or {}
    if "video_region" in lay:
        r = lay.get("video_region")
        src = "analysis/<id>/layout.json"
        res = lay.get("resolution")
        if r and res and [int(res[0]), int(res[1])] != [W, H]:
            sx, sy = W / float(res[0]), H / float(res[1])
            r = {"x": r["x"] * sx, "y": r["y"] * sy, "w": r["w"] * sx, "h": r["h"] * sy}
            src += f" (해상도 {res[0]}x{res[1]} → {W}x{H} 환산)"
    else:
        det = detect_video_region(video)
        r = det.get("video_region")
        src = "common.detect_video_region (layout.json 없음 → 지금 검출)"
    if r:
        x0, y0 = max(0, int(round(r["x"]))), max(0, int(round(r["y"])))
        x1, y1 = min(W, int(round(r["x"] + r["w"]))), min(H, int(round(r["y"] + r["h"])))
        r = {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}
        if r["w"] <= 0 or r["h"] <= 0 or (r["w"] >= 0.99 * W and r["h"] >= 0.99 * H):
            r = None
    return r, {"source": src, "resolution": [W, H], "region": r,
               "note": None if r else "영상 영역 = 화면 전체(또는 검출 못 함) → 화면 전체를 지문으로(검은 테두리 제거)"}


def fingerprint_reference(vid: str, video: Path, region: dict | None, ref_url: str | None,
                          original_urls: list[str], existing: list[dict]) -> dict:
    """Append the reference video's keyframe fingerprint through the sourcing API
    (``exclusions.add_reference_footage``) unless an entry for the same video and region already exists."""
    info = probe(video)
    want = ({**{k: int(region[k]) for k in ("x", "y", "w", "h")}, "resolution": [int(info.width), int(info.height)]}
            if region else None)
    for e in existing:
        if e.get("kind") == "reference_footage" and e.get("ref_video_id") == vid and "method" in e \
                and e.get("region") == want:
            return {"status": "exists", "added_at": e.get("added_at"), "n_phash": len(e.get("phash") or []),
                    "region": want}
    e = X.add_reference_footage(video, vid, ref_url=ref_url, original_urls=sorted(set(original_urls)),
                                added_by=ADDED_BY, n_frames=N_KEYFRAMES, region=region)
    existing.append(e)
    return {"status": "added", "added_at": e.get("added_at"), "n_phash": len(e.get("phash") or []), "region": want,
            "method": e.get("method")}


def export_lens(preset: str, vid: str, video: Path, region: dict, shots: dict | None, snap_rec: dict | None,
                max_frames: int = 8) -> dict:
    import cv2
    d = analysis_dir(preset, vid) / "lens"
    d.mkdir(parents=True, exist_ok=True)
    info = probe(video)
    cand = [((float(s["end"]) - float(s["start"])), (float(s["start"]) + float(s["end"])) / 2)
            for s in (shots or {}).get("shots") or []]
    if not cand:
        cand = [(1.0, float(t)) for t in np.linspace(0.5, max(0.6, info.duration - 0.5), max_frames)]
    picks = sorted(t for _, t in sorted(cand, key=lambda c: -c[0])[:max_frames])
    files = []
    for i, t in enumerate(picks, 1):
        try:
            fr = read_frames(video, [t])[0]
        except Exception:
            continue
        x, y, w, h = region["x"], region["y"], region["w"], region["h"]
        p = d / f"shot_{i:02d}_{int(round(t * 1000)):06d}.jpg"
        cv2.imwrite(str(p), cv2.cvtColor(fr[y:y + h, x:x + w], cv2.COLOR_RGB2BGR), [cv2.IMWRITE_JPEG_QUALITY, 90])
        files.append({"image": p.name, "t": round(t, 3)})
    title = (snap_rec or {}).get("title") or ""
    md = [f"# Google Lens 원본 찾기: {vid}", "",
          "Google Lens 는 이 도구가 자동으로 부를 수 없습니다(수동 작업, 이 작업 환경에서는 lens.google.com 접속 차단).", "",
          "1. 아래 이미지를 https://lens.google.com 에 하나씩 올립니다(자막을 뺀 영상 영역만 잘라 둠).",
          "2. TikTok·Instagram·Reddit·YouTube 등에서 **같은 장면의 원본 게시물**을 찾으면 주소를 확인합니다.",
          "3. `lens_results.csv` 에 image, original_url, platform, account 를 적고 **checked_by(확인한 사람)**, "
          "checked_at 을 채웁니다. 확인하지 않은 추측은 적지 않습니다. 검색했지만 원본을 못 찾았으면 original_url 을 비우고 "
          "checked_by·checked_at·notes(못 찾음)만 채웁니다(검색한 사실이 '렌즈' 경로 범위로 집계됨).",
          "4. `shortkit ref trace` 를 다시 실행하면 확인된 주소가 warehouse/exclusions.jsonl 과 source_accounts.json 에 반영됩니다.",
          "", f"- 레퍼런스 영상: {(snap_rec or {}).get('url') or vid}", f"- 제목(검색어 힌트): {title}", "",
          "| 이미지 | 시각(초) |", "|---|---:|"]
    md += [f"| {f['image']} | {f['t']} |" for f in files]
    (d / "lens_queries.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    res_csv = d / "lens_results.csv"
    if not res_csv.exists():
        write_csv_rows(res_csv, LENS_HEADER, [{"image": f["image"]} for f in files])
    return {"dir": paths.relp(d), "images": files}


def lens_results(preset: str, vid: str) -> list[dict]:
    rows = read_csv_rows(analysis_dir(preset, vid) / "lens" / "lens_results.csv")
    return [r for r in rows if (r.get("original_url") or "").strip() and (r.get("checked_by") or "").strip()]


# ============================================================================= transcript
def transcript_keywords(preset: str, vid: str, k: int = 10) -> dict:
    """Most frequent words of ``analysis/<id>/audio/transcript.json`` (``times``: first segment start
    per word when the transcript has timed segments)."""
    tj = read_json(analysis_dir(preset, vid) / "audio" / "transcript.json")
    if not tj or tj.get("status") not in (None, "measured"):
        return {"status": "unmeasured", "note": "전사 파일 없음(analysis/<id>/audio/transcript.json — 선택 단계 "
                                                "`shortkit ref transcribe`, faster-whisper 필요)", "keywords": [], "times": {}}
    segs = [sg for sg in tj.get("segments") or [] if isinstance(sg, dict)]
    text = tj.get("text") or " ".join(sg.get("text", "") for sg in segs)
    words = [w for w in re.findall(r"[0-9A-Za-z가-힣]{2,}", text) if w.lower() not in STOP]
    top = [w for w, _ in Counter(words).most_common(k)]
    times: dict[str, float | None] = {}
    for w in top:
        times[w] = next((round(float(sg["start"]), 3) for sg in segs
                         if w in (sg.get("text") or "") and isinstance(sg.get("start"), (int, float))), None)
    return {"status": "measured", "keywords": top, "times": times}


_LENS_T = re.compile(r"_(\d{6})\.jpg$")


def _lens_t(image: str | None) -> float | None:
    m = _LENS_T.search(image or "")
    return int(m.group(1)) / 1000.0 if m else None


# ============================================================================= script (on-screen captions) / credits
SCRIPT_ROLES = ("title", "description", "situation", "speaker", "dialogue", "reaction", "unknown")


def caption_script(preset: str, vid: str, own: set[str], k: int = 10) -> dict:
    """The reference's own on-screen caption text (``analysis/<id>/captions.json`` from `ref analyze`) IS its
    script for these captioned shorts: most frequent words (with the first caption time that shows each)
    plus handle / credit lines found in any caption (inside or outside the footage region).  The channel's
    own identity marks (role ``identity_mark`` or an own handle) are skipped."""
    cj = read_json(analysis_dir(preset, vid) / "captions.json")
    if not cj:
        return {"status": "unmeasured", "note": "자막 분석 없음(analysis/<id>/captions.json — `shortkit ref analyze` 필요)",
                "keywords": [], "times": {}, "credits": [], "n_items": 0}
    items = [c for c in cj.get("items") or [] if c.get("role") in SCRIPT_ROLES and (c.get("text") or "").strip()]
    words: list[str] = []
    first_t: dict[str, float] = {}
    credits: list[dict] = []
    for c in items:
        txt = str(c.get("text") or "")
        for w in re.findall(r"[0-9A-Za-z가-힣]{2,}", txt):
            if w.lower() in STOP or _is_own(w, own):
                continue
            words.append(w)
            first_t.setdefault(w, round(float(c.get("start") or 0.0), 3))
        for line in txt.splitlines():
            hs = [m.group(1).rstrip(".:") for m in _HANDLE_IN_TEXT.finditer(line)]
            hs = [h for h in hs if not _is_own(h, own)]
            if hs or CREDIT_RE.search(line):
                credits.append({"text": line.strip()[:200], "handles": hs, "t": round(float(c.get("start") or 0.0), 3),
                                "role": c.get("role"), "bbox": c.get("bbox"), "platform": _platform_hint(line)})
    top = [w for w, _ in Counter(words).most_common(k)]
    return {"status": "measured", "keywords": top, "times": {w: first_t.get(w) for w in top}, "credits": credits,
            "n_items": len(items), "source": "analysis/<id>/captions.json (레퍼런스 화면 자막 = 대본)"}


def _own_video_ids(preset: str) -> set[str]:
    ids: set[str] = set()
    for name in ("all_videos", "latest100", "high_views"):
        for v in (read_json(reference_dir(preset) / f"{name}.json") or {}).get("videos") or []:
            if v.get("video_id"):
                ids.add(str(v["video_id"]))
    return ids


def _own_channel_ids(preset: str) -> set[str]:
    pr = load_preset(preset)
    out = {str(pr.get("reference.channel_id_hint", "") or "")}
    for f in (reference_dir(preset) / "meta").glob("*.json") if (reference_dir(preset) / "meta").is_dir() else []:
        m = read_json(f) or {}
        if m.get("channel_id"):
            out.add(str(m["channel_id"]))
    return {x for x in out if x}


def is_own_profile_url(url: str, own: set[str], own_channel_ids: set[str]) -> bool:
    """A link to the reference channel ITSELF (profile / channel page), not to footage."""
    plat, acc = platform_of_url(url)
    if plat != "youtube":
        return False
    if acc and _is_own(acc, own):
        return True
    return any(cid and cid in url for cid in own_channel_ids)


def lens_checked(preset: str, vid: str) -> list[dict]:
    """Lens rows signed by the person who searched (``checked_by``), whether or not an original was found."""
    rows = read_csv_rows(analysis_dir(preset, vid) / "lens" / "lens_results.csv")
    return [r for r in rows if (r.get("checked_by") or "").strip()]


# ============================================================================= main
def trace(preset: str, ids: list[str], ocr_fps: float = 0.5, do_ocr: bool = True, lens: bool = True) -> dict:
    """Trace ``ids`` (default CLI set = latest100 ∪ high_views ∪ downloaded) and fence the reference off:

    * every reference-channel upload in all_videos.json becomes a URL exclusion (plus an ``account`` row
      naming the channel itself, for sourcing to reject the channel's own uploads);
    * every non-own URL in a traced description becomes a URL exclusion (YouTube included; ``credit_line``
      is recorded, not used as a filter); credited URLs are also the fingerprint entry's ``original_urls``;
    * on-screen credits: handle OCR over the WHOLE reference frame (credits are often printed in the bands
      around the footage) + handle/credit lines of the reference's own captions (captions.json);
    * script: the reference's caption text (captions.json) and, when present, audio/transcript.json;
    * fingerprints of the footage region (keyframe pHash) through the sourcing API."""
    own = own_identity(preset)
    own_ch = _own_channel_ids(preset)
    own_vids = _own_video_ids(preset)
    snap = load_snapshot(preset) or {}
    by_id: dict[str, dict] = {}
    for name in ("all_videos", "high_views"):             # reference only; latest100 wins below
        for v in (read_json(reference_dir(preset) / f"{name}.json") or {}).get("videos") or []:
            if v.get("video_id"):
                by_id[v["video_id"]] = v
    by_id.update({v["video_id"]: v for v in snap.get("videos") or [] if v.get("video_id")})
    paths.ensure_dir("warehouse")
    existing = X.load()
    have_urls = {url_key(r.get("url")) for r in existing if r.get("kind") == "url"}
    have_urls.discard(None)
    per_video, url_rows, n_fp = [], [], 0

    def add_url(u: str | None, reason: str, vid: str | None, **extra) -> None:
        k = url_key(u) if u else None
        if u and k and k not in have_urls:
            url_rows.append({"kind": "url", "url": u, "reason": reason, "ref_video_id": vid, "added_at": now_iso(),
                             "added_by": ADDED_BY, **extra})
            have_urls.add(k)

    # the reference channel's own uploads (whole listing) and the channel itself
    for vid_all, v in sorted(by_id.items()):
        add_url(v.get("url") or f"https://www.youtube.com/watch?v={vid_all}", "레퍼런스 채널 자체 업로드(all_videos)",
                vid_all, source="all_videos")
    pr = load_preset(preset)
    # the channel itself: a new row whenever no earlier row already carries this handle, page and EVERY channel id
    # known now (ids learned after a blocked first trace -- meta/<id>.json from collect -- must reach sourcing)
    if not any(e.get("kind") == "account" and e.get("added_by") == ADDED_BY
               and e.get("handle") == pr.get("reference.channel_handle", None)
               and e.get("channel_url") == pr.get("reference.channel_url", None)
               and own_ch <= set(e.get("channel_ids") or []) for e in existing):
        url_rows.append({"kind": "account", "platform": "youtube", "handle": pr.get("reference.channel_handle", None),
                         "channel_url": pr.get("reference.channel_url", None), "channel_ids": sorted(own_ch),
                         "reason": "레퍼런스 채널 자체 — 이 채널의 업로드는 소재 후보가 될 수 없음(재게시 포함)",
                         "added_at": now_iso(), "added_by": ADDED_BY})
    for vid in ids:
        rec = by_id.get(vid) or {}
        meta_path = reference_dir(preset) / "meta" / f"{vid}.json"
        meta = read_json(meta_path) or {}
        ref_url = rec.get("url") or (f"https://www.youtube.com/watch?v={vid}" if (meta or vid in own_vids) else None)
        desc = parse_description(meta.get("description") or "", own)
        examined: list[str] = []
        if meta_path.is_file():
            examined.append("description")             # metadata read (an empty description is a result too)
        found: dict = {"video_id": vid, "ref_url": ref_url,
                       "description": {"available": bool(meta.get("description")), "metadata_read": meta_path.is_file(),
                                       **desc}}
        accs = [{"platform": a["platform"] or "unknown", "account": a["account"], "kind": a["kind"],
                 "t": None, "text": a["text"], "url": a.get("url")} for a in desc["accounts"]]
        kws = [{"keyword": t, "kind": "hashtag", "t": None} for t in desc["hashtags"]]
        # script: the reference's own caption text + optional ASR transcript
        cs = caption_script(preset, vid, own)
        found["script_captions"] = {k: v for k, v in cs.items() if k != "credits"}
        tk = transcript_keywords(preset, vid)
        found["transcript"] = tk
        if cs["status"] == "measured" or tk["status"] == "measured":
            examined.append("script")
        if tk["status"] == "measured":
            examined.append("transcript")
        kws += [{"keyword": w, "kind": "caption_script", "t": cs["times"].get(w)} for w in cs["keywords"]]
        kws += [{"keyword": w, "kind": "transcript", "t": tk["times"].get(w)} for w in tk["keywords"]]
        # on-screen credits from the reference's captions (anywhere on the frame, incl. the bands around the footage)
        found["caption_credits"] = cs["credits"]
        for c in cs["credits"]:
            for h in c["handles"]:
                accs.append({"platform": ("reddit" if re.match(r"[ur]/", h) else (c.get("platform") or "unknown")),
                             "account": h, "kind": "on_screen_caption", "t": c["t"], "text": c["text"], "url": None,
                             "verified": False})
        # description URLs: every non-own URL is fenced off (credit line or not); credited ones are originals
        original_urls = []
        for u in desc["urls"]:
            if is_own_profile_url(u["url"], own, own_ch):
                continue
            add_url(u["url"], f"레퍼런스 {vid} 설명란 주소" + (" (출처 줄)" if u["credit_line"] else ""), vid,
                    credit_line=bool(u["credit_line"]), platform=u.get("platform"), source="description")
            if u["credit_line"]:
                original_urls.append(u["url"])
        video = video_path(preset, vid)
        if video is not None:
            info = probe(video)
            region, reg_info = footage_region(preset, vid, video)
            found["footage_region"] = reg_info
            view = region_or_full({"video_region": region}, int(info.width), int(info.height))
            full = {"x": 0, "y": 0, "w": int(info.width), "h": int(info.height)}
            shots = read_json(analysis_dir(preset, vid) / "shots.json")
            if do_ocr:
                # credits / reposter handles can sit anywhere: OCR the WHOLE frame (the footage-region crop is
                # used for fingerprinting only)
                wm = ocr_watermarks(video, full, ocr_fps, own)
                found["watermarks"] = wm
                found["watermark_ocr_area"] = "full_frame"
                examined.append("watermark_ocr")
                accs += [{"platform": a["platform"], "account": a["account"], "kind": "watermark_ocr",
                          "t": a["frames"][0], "text": a["text"], "verified": False, "url": None} for a in wm]
            else:
                found["watermarks"] = None
            if lens:
                found["lens"] = export_lens(preset, vid, video, view, shots, rec)
            signed = lens_checked(preset, vid)
            if signed:
                examined.append("lens_manual")
            found["lens_checked_rows"] = len(signed)
            for r in signed:
                ou = (r.get("original_url") or "").strip()
                if not ou:
                    continue                      # searched, nothing found (recorded by the person)
                original_urls.append(ou)
                add_url(ou, f"레퍼런스 {vid} 의 원본(렌즈 확인: {r['checked_by']})", vid, source="lens_manual")
                plat, acc = platform_of_url(ou)
                if acc and not _is_own(acc, own):
                    accs.append({"platform": r.get("platform") or plat or "unknown", "account": r.get("account") or acc,
                                 "kind": "lens_manual", "t": _lens_t(r.get("image")), "text": ou,
                                 "checked_by": r["checked_by"], "url": profile_url_from(ou, plat, acc)})
            try:
                fp = fingerprint_reference(vid, video, region, ref_url, original_urls, existing)
            except Exception as e:  # one unreadable file must not stop the batch -- but say so
                fp = {"status": "error", "n_phash": 0, "note": f"{type(e).__name__}: {e}"[:300]}
                warn(f"{vid}: 지문(phash) 실패 → 제외 목록에 영상 지문 없음(못 잼): {fp['note']}")
            n_fp += fp["status"] == "added"
            found["fingerprint"] = fp
            found["phash_count"] = fp["n_phash"]
            if fp["n_phash"]:
                examined.append("fingerprint")
            else:
                warn(f"{vid}: 쓸 수 있는 키프레임 없음 → 같은 녹화 판정 못 함(URL 규칙만 적용)")
        else:
            found["note"] = "영상 파일 없음 → 화면 출처 OCR·렌즈 키프레임·지문(phash) 못 함(못 잼)"
        add_url(ref_url, "레퍼런스 영상", vid, source="reference")
        for u in sorted(set(original_urls)):
            add_url(u, f"레퍼런스 {vid} 의 원본(추적)", vid, source="traced_original")
        found["original_urls"] = sorted(set(original_urls))
        found["accounts_found"] = accs
        found["keywords_found"] = kws
        found["sources_examined"] = examined
        write_json(analysis_dir(preset, vid) / "trace.json", {**found, "traced_at": now_iso()})
        per_video.append(found)
    if url_rows:
        append_jsonl(paths.absp(X.EXCLUSIONS), url_rows)
    out = build_source_accounts(preset, ocr_fps)
    stg = out.get("stage") or {}
    say(f"출처 추적: 이번 {len(per_video)}편(누적 {out['videos_traced']}편), 계정 {len(out['accounts'])}개, "
        f"키워드 {len(out['keywords'])}개, 제외 목록에 새 지문 {n_fp}건·새 주소/계정 {len(url_rows)}건 → warehouse/")
    say(f"  단계 상태: {'측정' if stg.get('status') == 'measured' else '못 잼(일부만)'} — "
        + ", ".join(f"{CHANNEL_KO[c]} {v['covered']}/{v['target']}" for c, v in (stg.get("channels") or {}).items()))
    if stg.get("status") != "measured":
        warn(f"출처 추적 단계 = 못 잼: {stg.get('blocker')}")
    out["traced_now"] = len(per_video)
    return out


CHANNEL_KO = {"description": "설명란", "script": "대본(자막·전사)", "on_screen": "화면 출처 OCR",
              "lens": "렌즈(수동)", "fingerprint": "지문"}
REQUIRED_CHANNELS = tuple(CHANNEL_KO)


def _examined(d: dict) -> list[str]:
    if "sources_examined" in d:
        ex = list(d["sources_examined"] or [])
    else:
        ex = []                                  # trace.json written before sources_examined existed
        if (d.get("description") or {}).get("available"):
            ex.append("description")
        if d.get("watermarks") is not None:
            ex.append("watermark_ocr")
        if (d.get("transcript") or {}).get("status") == "measured":
            ex.append("transcript")
    if d.get("phash_count") and "fingerprint" not in ex:
        ex.append("fingerprint")
    return ex


def _channels_of(d: dict) -> set[str]:
    ex = set(_examined(d))
    ch = set()
    if "description" in ex:
        ch.add("description")
    if "script" in ex or "transcript" in ex:
        ch.add("script")
    if "watermark_ocr" in ex and d.get("watermark_ocr_area") == "full_frame":
        ch.add("on_screen")
    if "lens_manual" in ex:
        ch.add("lens")
    if "fingerprint" in ex:
        ch.add("fingerprint")
    return ch


def trace_stage(preset: str, traced: dict[str, set[str]], n_fp_entries: int, n_accounts: int, n_keywords: int) -> dict:
    """Per-channel coverage over the videos that must be traced (latest100 ∪ high_views): the stage is
    ``measured`` only when EVERY channel covers EVERY target video."""
    from .common import resolve_ids

    target = resolve_ids(preset, set_name="latest100")
    for v in resolve_ids(preset, set_name="high_views"):
        if v not in target:
            target.append(v)
    snap = load_snapshot(preset) or {}
    chans = {}
    for c in REQUIRED_CHANNELS:
        cov = [v for v in target if c in traced.get(v, set())]
        chans[c] = {"covered": len(cov), "target": len(target),
                    "missing": [v for v in target if v not in cov][:50]}
    complete = bool(target) and all(v["covered"] == v["target"] for v in chans.values())
    missing_ch = [c for c, v in chans.items() if v["covered"] < v["target"]]
    if not target:
        blocker = snapshot_blocker(preset) if (snap.get("status") == "blocked" or not snap) else \
            "추적 대상(최신 100편·조회수 기준 이상 영상) 목록이 비어 있음"
    elif missing_ch:
        blocker = "추적이 덜 된 경로: " + ", ".join(f"{CHANNEL_KO[c]} {chans[c]['covered']}/{chans[c]['target']}"
                                                  for c in missing_ch)
    else:
        blocker = None
    impact = []
    if chans["fingerprint"]["covered"] < len(target) or not target:
        impact.append(f"레퍼런스 촬영본 지문 제외가 {chans['fingerprint']['covered']}/{len(target)}편만 적용"
                      f"(제외 목록 지문 항목 {n_fp_entries}건) → 나머지 레퍼런스 촬영본을 같은 녹화로 걸러내지 못함")
    if any(chans[c]["covered"] < len(target) for c in ("description", "script", "on_screen", "lens")) or not target:
        impact.append(f"새 소재 검색어/계정이 일부 경로에서만 추적됨(계정 {n_accounts}개, 키워드 {n_keywords}개)")
    if snap.get("status") == "blocked" or not snap:
        state = "blocked_network"
    elif complete:
        state = "resolved"
    elif missing_ch == ["lens"]:
        state = "open_manual_lens"
    else:
        state = "open"
    return {"status": "measured" if complete else "unmeasured", "blocker": blocker, "channels": chans,
            "target_set": "latest100 ∪ high_views", "n_target": len(target), "exclusion_fingerprints": n_fp_entries,
            "impact": "; ".join(impact) or "없음", "state": state,
            "rule": "경로(설명란·대본·화면 출처 OCR(화면 전체)·렌즈 수동 확인·지문)마다 대상 영상 전부가 확인되어야 '측정'"}


def stage_status(preset: str) -> dict:
    """Row for `shortkit preset unresolved` (item, status, impact, state, evidence) computed from
    warehouse/source_accounts.json ``stage`` -- never from 'any account found'."""
    acc = read_json(paths.absp("warehouse/source_accounts.json")) or {}
    stg = acc.get("stage") or {}
    ch = stg.get("channels") or {}
    ev = ", ".join(f"{CHANNEL_KO.get(c, c)} {v.get('covered')}/{v.get('target')}" for c, v in ch.items())
    return {"item": "레퍼런스 소재 출처·반복 계정·키워드 역추적",
            "status": stg.get("status") or "unmeasured",
            "impact": stg.get("impact") or "새 소재 검색어/계정 목록이 없음, 레퍼런스 촬영본 제외 목록이 비어 있음",
            "state": stg.get("state") or "blocked_network",
            "evidence": (f"warehouse/source_accounts.json stage: {ev or '추적 기록 없음'}; 제외 지문 "
                         f"{stg.get('exclusion_fingerprints', 0)}건; accounts={len(acc.get('accounts') or [])}")}


def build_source_accounts(preset: str, ocr_fps: float = 0.5) -> dict:
    """Write ``warehouse/source_accounts.json`` from every ``analysis/*/trace.json`` (so tracing a
    subset of videos never drops what earlier runs found).

    ``status`` (read by sourcing): ``measured`` when at least one reference video had a source actually
    examined -- the accounts / keywords listed ARE measured, but that says nothing about completeness.
    ``stage`` = completeness of the reverse-trace STAGE: per channel (description / script / on-screen /
    Lens / fingerprint) coverage over latest100 ∪ high_views; ``stage.status`` is measured only when every
    channel covers every target video (this is what the unresolved table must report).  An existing
    measured file is never replaced by an unmeasured one."""
    pr = load_preset(preset)
    acc_ev: dict[tuple[str, str], list[dict]] = defaultdict(list)
    acc_url: dict[tuple[str, str], str] = {}
    kw_ev: dict[str, list[dict]] = defaultdict(list)
    kw_plat: dict[str, set[str]] = defaultdict(set)
    traced, examined, coverage = [], [], Counter()
    chan_of: dict[str, set[str]] = {}
    for tj in sorted((paths.preset_dir(preset) / "analysis").glob("*/trace.json")):
        d = read_json(tj) or {}
        vid = d.get("video_id") or tj.parent.name
        traced.append(vid)
        ex = _examined(d)
        coverage.update(ex)
        chan_of[vid] = _channels_of(d)
        if ex:
            examined.append(vid)
        plats = set()
        for a in d.get("accounts_found") or []:
            key = (a.get("platform") or "unknown", a["account"])
            ev = {"ref_video_id": vid, "t": a.get("t"), "kind": a.get("kind"), "text": a.get("text")}
            if a.get("checked_by"):
                ev["checked_by"] = a["checked_by"]
            acc_ev[key].append(ev)
            url = a.get("url") or (reddit_url(a["account"]) if key[0] == "reddit" else None)
            if url:
                acc_url.setdefault(key, url)
            if key[0] in SOURCE_PLATFORMS:
                plats.add(key[0])
        for k in d.get("keywords_found") or []:
            kw_ev[k["keyword"]].append({"ref_video_id": vid, "t": k.get("t"), "kind": k.get("kind")})
            kw_plat[k["keyword"]] |= plats
    accounts = []
    for (plat, acc), evs in acc_ev.items():
        vids = {e["ref_video_id"] for e in evs}
        accounts.append({"platform": plat, "handle": acc, "url": acc_url.get((plat, acc)), "count": len(vids),
                         "mentions": len(evs),
                         "verified_by_text": any(e.get("kind") not in ("watermark_ocr", "on_screen_caption")
                                                 for e in evs),
                         "evidence": evs[:20]})
    accounts.sort(key=lambda a: (-a["count"], -a["mentions"], a["handle"].lower()))
    keywords = [{"keyword": k, "platforms": sorted(kw_plat[k]), "count": len({e["ref_video_id"] for e in evs}),
                 "evidence": evs[:10]} for k, evs in kw_ev.items()]
    keywords.sort(key=lambda k: (-k["count"], k["keyword"]))
    snap = load_snapshot(preset) or {}
    if examined:
        blocker = None
    elif traced:
        blocker = (f"추적한 레퍼런스 {len(traced)}편 모두 설명란(reference/meta)·자막 대본·화면 출처 OCR·전사·서명된 렌즈 "
                   "결과가 없음(`shortkit ref collect` 로 설명란, `ref analyze` 로 자막, `ref download` 후 OCR 포함 "
                   "`ref trace` 필요)")
        if snap.get("status") == "blocked" or not snap:
            blocker += f" — {snapshot_blocker(preset)}"
    elif snap.get("status") == "blocked" or not snap:
        blocker = snapshot_blocker(preset)
    else:
        blocker = "추적한 레퍼런스 영상 없음(`shortkit ref trace` 미실행 또는 대상 영상 없음)"
    n_fp_entries = sum(1 for e in X.load() if e.get("kind") == "reference_footage" and e.get("phash"))
    stage = trace_stage(preset, chan_of, n_fp_entries, len(accounts), len(keywords[:100]))
    out = {"status": "measured" if examined else "unmeasured", "blocker": blocker, "traced_at": now_iso(),
           "status_meaning": "status = 아래 계정·키워드가 실제로 확인된 결과인지(소재 검색에 사용). 역추적 단계가 "
                             "끝났는지는 stage.status(경로별 범위)",
           "stage": stage,
           "accounts": accounts, "keywords": keywords[:100],
           "schema": SOURCE_ACCOUNTS_SCHEMA, "preset_id": pr.preset_id,
           "source_snapshot": snap.get("captured_at"), "source_snapshot_status": snap.get("status"),
           "videos_traced": len(traced), "videos_examined": len(examined), "video_ids": traced[:500],
           "coverage": dict(coverage),
           "methods": {"description": "설명란 출처 줄·@핸들·URL·해시태그(채널 자체 핸들 제외); 채널 자체가 아닌 모든 URL 은 "
                                      "제외 목록(출처 줄 여부는 credit_line 으로 기록)",
                       "script": "레퍼런스 화면 자막(analysis/<id>/captions.json, `ref analyze`)의 단어 빈도 = 대본 키워드; "
                                 "audio/transcript.json(`ref transcribe`, 선택 음성 인식)이 있으면 함께",
                       "on_screen": f"화면 전체의 정지 오버레이 줄(자막 줄 검출기) → tesseract eng psm 7, {ocr_fps} fps, "
                                    "2프레임 이상 또는 신뢰도 70 이상, 비슷한 판독은 병합(검색 단서, 미확인) + 레퍼런스 자막 "
                                    "중 @핸들·출처 줄",
                       "lens": "수동(lens_results.csv 에 checked_by 가 있는 행: 찾은 원본 주소 또는 '못 찾음')",
                       "fingerprint": "영상 영역 키프레임 pHash(shortkit.sourcing.exclusions)",
                       "count": "그 계정/키워드가 나온 레퍼런스 영상 수",
                       "t": "레퍼런스 영상 안 시각(초). 설명란 텍스트는 시각이 없어 null"}}
    wh = paths.ensure_dir("warehouse")
    old = read_json(wh / "source_accounts.json") or {}
    if out["status"] != "measured" and old.get("status") == "measured":
        warn("기존 측정된 source_accounts.json 을 그대로 둡니다(이번 빌드에는 추적 결과가 없음).")
        return {**old, "videos_traced": old.get("videos_traced", 0), "kept_existing": True}
    write_json(wh / "source_accounts.json", out)
    return out
