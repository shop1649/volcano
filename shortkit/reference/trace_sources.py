"""Trace where the reference channel's footage comes from, and fence it off for sourcing.

Per reference video:
  * description credits: lines with 출처/원본/source/credit/cr./via/©, @handles, u/ r/ names,
    URLs (platform + account parsed from tiktok/instagram/reddit/youtube/x/facebook URLs), hashtags;
  * burned-in watermark handles: static overlay lines inside the footage region (caption line
    detector) read with tesseract ``eng --psm 7``
    (TikTok / Instagram / Reddit style ``@user``, ``u/user``), kept when seen in >= 2 frames or with
    confidence >= 70;
  * transcript keywords when ``analysis/<id>/audio/transcript.json`` exists (else noted as missing);
  * keyframes for a manual Google Lens search: ``analysis/<id>/lens/*.jpg`` + ``lens_queries.md``
    + ``lens_results.csv`` (filled by the person who ran the search; rows with ``checked_by`` are
    read back as traced original URLs).  Lens itself is not automated (and is blocked here).

Aggregates ``warehouse/source_accounts.json`` (accounts + keywords with frequency and evidence)
and appends reference-footage exclusions to ``warehouse/exclusions.jsonl`` (docs/CONTRACT.md
section 11): perceptual hashes (``imagehash.phash``) of keyframes cropped to the footage region,
the reference URL and every traced original URL.  The reference channel's own handles are never
reported as sources.
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
from ..util.jsonio import append_jsonl, now_iso, read_json, read_jsonl, write_json
from ..util.media import probe, read_frames
from .common import (analysis_dir, load_snapshot, read_csv_rows, reference_dir, region_or_full, say, video_path,
                     warn, write_csv_rows)

ADDED_BY = "shortkit ref trace"
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
                accounts.append({"platform": plat, "account": acc, "kind": "description_url", "text": line[:200]})
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
        tags += HASHTAG_RE.findall(line)
    return {"accounts": accounts, "urls": urls, "hashtags": tags, "credit_lines": credit_lines}


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


# ============================================================================= keyframes / phash
def keyframe_times(shots: dict | None, duration: float, per_second: float = 1.0, cap: int = 60) -> list[float]:
    ts = set(round(float(t), 2) for t in np.arange(0.5, max(0.6, duration - 0.2), 1.0 / per_second))
    for s in (shots or {}).get("shots") or []:
        ts.add(round((float(s["start"]) + float(s["end"])) / 2, 2))
    out = sorted(ts)
    if len(out) > cap:
        idx = np.linspace(0, len(out) - 1, cap).round().astype(int)
        out = [out[i] for i in sorted(set(idx))]
    return out


def phashes(video: Path, region: dict, times: list[float]) -> tuple[list[str], list[float]]:
    import imagehash
    from PIL import Image

    hs, ts = [], []
    for t in times:
        try:
            fr = read_frames(video, [t])[0]
        except Exception:
            continue
        x, y, w, h = region["x"], region["y"], region["w"], region["h"]
        crop = fr[y:y + h, x:x + w]
        if crop.size == 0 or float(crop.std()) < 3:
            continue            # blank/flash frames match everything
        hs.append(str(imagehash.phash(Image.fromarray(crop))))
        ts.append(round(float(t), 3))
    return hs, ts


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
          "checked_at 을 채웁니다. 확인하지 않은 추측은 적지 않습니다.",
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
    tj = read_json(analysis_dir(preset, vid) / "audio" / "transcript.json")
    if not tj:
        return {"status": "unmeasured", "note": "전사 파일 없음(analysis/<id>/audio/transcript.json)", "keywords": []}
    text = tj.get("text") or " ".join(s.get("text", "") for s in tj.get("segments") or [])
    words = [w for w in re.findall(r"[0-9A-Za-z가-힣]{2,}", text) if w.lower() not in STOP]
    return {"status": "measured", "keywords": [w for w, _ in Counter(words).most_common(k)]}


# ============================================================================= main
def trace(preset: str, ids: list[str], ocr_fps: float = 0.5, do_ocr: bool = True, lens: bool = True) -> dict:
    pr = load_preset(preset)
    own = own_identity(preset)
    snap = load_snapshot(preset) or {}
    by_id = {v["video_id"]: v for v in snap.get("videos") or []}
    wh = paths.ensure_dir("warehouse")
    excl_path = wh / "exclusions.jsonl"
    existing = read_jsonl(excl_path)
    have_urls = {r.get("url") for r in existing if r.get("kind") == "url"}
    have_ph = {(r.get("ref_video_id"), tuple(r.get("phash") or [])) for r in existing if r.get("kind") == "reference_footage"}
    acc_ev: dict[tuple[str, str], list[dict]] = defaultdict(list)
    kw_ev: dict[str, list[dict]] = defaultdict(list)
    per_video, new_rows = [], []
    for vid in ids:
        rec = by_id.get(vid) or {}
        meta = read_json(reference_dir(preset) / "meta" / f"{vid}.json") or {}
        ref_url = rec.get("url") or (f"https://www.youtube.com/watch?v={vid}" if meta else None)
        desc = parse_description(meta.get("description") or "", own)
        found = {"video_id": vid, "description": {"available": bool(meta.get("description")), **desc}}
        for a in desc["accounts"]:
            acc_ev[(a["platform"] or "unknown", a["account"])].append({"video_id": vid, "kind": a["kind"],
                                                                       "text": a["text"]})
        for tag in desc["hashtags"]:
            kw_ev[tag].append({"video_id": vid, "kind": "hashtag"})
        tk = transcript_keywords(preset, vid)
        found["transcript"] = tk
        for w in tk["keywords"]:
            kw_ev[w].append({"video_id": vid, "kind": "transcript"})
        video = video_path(preset, vid)
        original_urls = [u["url"] for u in desc["urls"] if u["credit_line"] and u["platform"] not in ("youtube",)]
        if video is not None:
            info = probe(video)
            lay = read_json(analysis_dir(preset, vid) / "layout.json") or {}
            region = region_or_full({"video_region": lay.get("video_region")}, int(info.width), int(info.height))
            shots = read_json(analysis_dir(preset, vid) / "shots.json")
            if do_ocr:
                wm = ocr_watermarks(video, region, ocr_fps, own)
                found["watermarks"] = wm
                for a in wm:
                    acc_ev[(a["platform"], a["account"])].append({"video_id": vid, "kind": "watermark_ocr",
                                                                  "t": a["frames"][0], "text": a["text"]})
            else:
                found["watermarks"] = None
            if lens:
                found["lens"] = export_lens(preset, vid, video, region, shots, rec)
            for r in lens_results(preset, vid):
                original_urls.append(r["original_url"].strip())
                plat, acc = platform_of_url(r["original_url"].strip())
                if acc and not _is_own(acc, own):
                    acc_ev[(r.get("platform") or plat or "unknown", r.get("account") or acc)].append(
                        {"video_id": vid, "kind": "lens_manual", "text": r["original_url"], "checked_by": r["checked_by"]})
            hs, ts = phashes(video, region, keyframe_times(shots, float(info.duration)))
            if hs and (vid, tuple(hs)) not in have_ph:
                row = {"kind": "reference_footage", "ref_video_id": vid, "ref_url": ref_url,
                       "original_urls": sorted(set(original_urls)), "phash": hs, "frame_times": ts,
                       "region": region, "resolution": [int(info.width), int(info.height)],
                       "hash": "imagehash.phash (8x8 DCT, 64 bit hex) of the footage region",
                       "added_at": now_iso(), "added_by": ADDED_BY}
                new_rows.append(row)
                have_ph.add((vid, tuple(hs)))
            found["phash_count"] = len(hs)
        else:
            found["note"] = "영상 파일 없음 → 워터마크 OCR·렌즈 키프레임·phash 못 함(못 잼)"
        for u in ([ref_url] if ref_url else []) + sorted(set(original_urls)):
            if u and u not in have_urls:
                new_rows.append({"kind": "url", "url": u, "reason": "레퍼런스 영상" if u == ref_url else
                                 f"레퍼런스 {vid} 의 원본(추적)", "ref_video_id": vid, "added_at": now_iso(),
                                 "added_by": ADDED_BY})
                have_urls.add(u)
        found["original_urls"] = sorted(set(original_urls))
        write_json(analysis_dir(preset, vid) / "trace.json", {**found, "traced_at": now_iso()})
        per_video.append(found)
    if new_rows:
        append_jsonl(excl_path, new_rows)
    accounts = []
    for (plat, acc), evs in acc_ev.items():
        vids = sorted({e["video_id"] for e in evs})
        accounts.append({"platform": plat, "account": acc, "frequency": len(vids), "mentions": len(evs),
                         "evidence": evs[:20]})
    accounts.sort(key=lambda a: (-a["frequency"], -a["mentions"], a["account"].lower()))
    keywords = [{"keyword": k, "frequency": len({e["video_id"] for e in evs}), "evidence": evs[:10]}
                for k, evs in kw_ev.items()]
    keywords.sort(key=lambda k: (-k["frequency"], k["keyword"]))
    old = read_json(wh / "source_accounts.json") or {}
    out = {"schema": "shortkit.source_accounts/1", "preset_id": pr.preset_id, "built_at": now_iso(),
           "videos_traced": len(per_video), "video_ids": [p["video_id"] for p in per_video],
           "status": "measured" if per_video else "unmeasured",
           "blocker": None if per_video else "추적할 레퍼런스 영상 없음(스냅샷·다운로드 필요)",
           "accounts": accounts, "keywords": keywords[:100],
           "methods": {"description": "설명란 출처 줄·@핸들·URL·해시태그(채널 자체 핸들 제외)",
                       "watermark_ocr": f"영상 영역의 정지 오버레이 줄(자막 줄 검출기) → tesseract eng psm 7, {ocr_fps} fps, "
                                        "2프레임 이상 또는 신뢰도 70 이상, 부분 판독은 가장 긴 판독으로 병합",
                       "transcript": "analysis/<id>/audio/transcript.json 이 있을 때만",
                       "lens": "수동(lens_results.csv 에 checked_by 가 있는 행만 반영)"},
           "previous_built_at": old.get("built_at")}
    write_json(wh / "source_accounts.json", out)
    say(f"출처 추적: 영상 {len(per_video)}편, 계정 {len(accounts)}개, 키워드 {len(keywords)}개, "
        f"제외 목록에 새 기록 {len(new_rows)}건 → warehouse/")
    if not per_video:
        warn("추적할 영상이 없습니다(latest100 스냅샷이 차단 상태이거나 영상이 없음).")
    return out
