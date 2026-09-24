"""Aggregate per-video visual analysis into preset measurements (docs/CONTRACT.md section 2).

Reads ``analysis/<id>/{layout,captions,motion,shots}.json`` of the analysed reference videos and
format membership from ``formats.yaml`` and writes ``presets/<name>/measurements/visual_*.json``
items keyed by preset keys.  Every numeric item carries ``overall`` and ``by_format``
``{n, p10, p50, p90}``; categorical items carry counts / mode; coordinates and sizes are scaled
from each video's resolution to the preset canvas and stored with ``resolution``.  Keys without
data are written as ``status: unmeasured`` with a ``blocker`` -- never a default value.

Unit of observation: one value per video (the video's median / mode / max for the role, as the
method says), so long videos do not dominate; ``n`` = number of videos contributing.
"""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any, Callable

import numpy as np

from .. import paths
from ..config import load_preset
from ..util.jsonio import now_iso, read_json, write_json
from ..util.stats import categorical, pstats
from .classify import load_membership
from .common import ROLES, analysis_dir, color_mode, load_snapshot, resolve_ids, say, snapshot_blocker

SCHEMA = "shortkit.measurement/1"
NARRATION_ROLES = ("title", "description", "situation", "reaction")
REGISTER_MAP = {"반말": "반말_구어체", "해요체": "해요체", "음슴체": "음슴체", "합쇼체": "합쇼체"}


# ============================================================================= item builders
def _stats_with_value(vals: list[float], rule: str, digits: int, as_int: bool) -> dict:
    st = pstats(vals, digits)
    if st["n"]:
        if rule == "mode":
            v = Counter(round(float(x), digits) for x in vals).most_common(1)[0][0]
        else:
            v = st[rule] if rule in ("p10", "p50", "p90") else (max(vals) if rule == "max" else min(vals))
        st["value"] = int(round(v)) if as_int else round(float(v), digits)
    else:
        st["value"] = None
    return st


def num_item(key: str, rows: list[dict], unit: str | None, method: str, blocker: str, resolution=None,
             rule: str = "p50", digits: int = 3, as_int: bool = False, extra: dict | None = None) -> dict:
    vals = [r["value"] for r in rows if r.get("value") is not None]
    it: dict[str, Any] = {"key": key, "unit": unit, "resolution": resolution, "method": method,
                          "value_rule": rule, "measured_at": now_iso()}
    if not vals:
        it.update({"status": "unmeasured", "value": None, "overall": {"n": 0, "p10": None, "p50": None, "p90": None},
                   "by_format": {}, "evidence": [], "blocker": blocker})
    else:
        ov = _stats_with_value(vals, rule, digits, as_int)
        byf = {}
        for fmt in sorted({r["format_id"] for r in rows if r.get("format_id") and r.get("value") is not None}):
            byf[fmt] = _stats_with_value([r["value"] for r in rows if r.get("format_id") == fmt
                                          and r.get("value") is not None], rule, digits, as_int)
        it.update({"status": "measured", "value": ov.pop("value"), "overall": ov, "by_format": byf,
                   "evidence": _evidence(rows), "blocker": None})
    if extra:
        it.update(extra)
    return it


def cat_item(key: str, rows: list[dict], method: str, blocker: str, extra: dict | None = None) -> dict:
    vals = [r["value"] for r in rows if r.get("value") is not None]
    it: dict[str, Any] = {"key": key, "unit": None, "resolution": None, "method": method, "value_rule": "mode",
                          "measured_at": now_iso()}
    if not vals:
        it.update({"status": "unmeasured", "value": None, "overall": {"n": 0, "counts": {}, "mode": None},
                   "by_format": {}, "evidence": [], "blocker": blocker})
    else:
        ov = categorical(vals)
        byf = {}
        for fmt in sorted({r["format_id"] for r in rows if r.get("format_id") and r.get("value") is not None}):
            c = categorical([r["value"] for r in rows if r.get("format_id") == fmt and r.get("value") is not None])
            c["value"] = c["mode"]
            byf[fmt] = c
        it.update({"status": "measured", "value": ov["mode"], "overall": ov, "by_format": byf,
                   "evidence": _evidence(rows), "blocker": None})
    if extra:
        it.update(extra)
    return it


def color_item(key: str, rows: list[dict], method: str, blocker: str, extra: dict | None = None) -> dict:
    vals = [r["value"] for r in rows if r.get("value")]
    it: dict[str, Any] = {"key": key, "unit": "rgb_hex", "resolution": None, "method": method,
                          "value_rule": "mode of color clusters (RGB distance <= 28)", "measured_at": now_iso()}
    if not vals:
        it.update({"status": "unmeasured", "value": None, "overall": {"n": 0, "clusters": [], "mode": None},
                   "by_format": {}, "evidence": [], "blocker": blocker})
    else:
        ov = color_mode(vals)
        byf = {}
        for fmt in sorted({r["format_id"] for r in rows if r.get("format_id") and r.get("value")}):
            c = color_mode([r["value"] for r in rows if r.get("format_id") == fmt and r.get("value")])
            c["value"] = c["mode"]
            byf[fmt] = c
        it.update({"status": "measured", "value": ov["mode"], "overall": ov, "by_format": byf,
                   "evidence": _evidence(rows), "blocker": None})
    if extra:
        it.update(extra)
    return it


def unmeasured(key: str, blocker: str, method: str | None = None) -> dict:
    return {"key": key, "status": "unmeasured", "value": None, "unit": None, "resolution": None,
            "overall": {"n": 0, "p10": None, "p50": None, "p90": None}, "by_format": {}, "evidence": [],
            "method": method, "measured_at": now_iso(), "blocker": blocker}


def _evidence(rows: list[dict], k: int = 5) -> list[dict]:
    out, seen = [], set()
    for r in rows:
        if r.get("value") is None or r["video_id"] in seen:
            continue
        seen.add(r["video_id"])
        e = {"video_id": r["video_id"], "t": r.get("t"), "value": r["value"], "frame": r.get("frame")}
        if r.get("note"):
            e["note"] = r["note"]
        out.append(e)
        if len(out) >= k:
            break
    return out


def _video_mode(vals: list) -> Any:
    """Per-video categorical value: the most common observation (ties -> the first observed)."""
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    c = Counter(vals)
    top = max(c.values())
    return next(v for v in vals if c[v] == top)


# ============================================================================= canvas size (downloads + probe)
_CAP_RE = re.compile(r"\b(height|width)\s*<=\s*(\d+)")
FULL_HD_SHORT_SIDE = 1080     # a rendition whose short side is >= this is accepted even when a cap binds
RUNG = 1.45                   # YouTube rendition ladder: the next rendition is ~1.5x taller (854 -> 1280 -> 1920)


def download_cap_issue(row: dict) -> str | None:
    """Why a downloaded file's size / frame rate may be a LOWER rendition than the reference serves
    (None = usable).

    ``shortkit ref download`` records the yt-dlp format string it requested.  A ``height<=N`` /
    ``width<=N`` filter binds when the next rendition up (~1.45x) would exceed N; on a portrait Short a
    ``height<=1080`` filter binds on the LONG side and yields a 608x1080 / 480x854 file instead of
    1080x1920 (and YouTube's 60 fps renditions exist only at >= 720p).  Such a file is excluded when
    its short side is below full HD; a binding cap on a >= 1080-short-side rendition is accepted and
    noted (the upload may be larger, the value is the largest rendition up to the cap)."""
    fmt = str(row.get("requested_format") or "")
    caps = [(m.group(1), int(m.group(2))) for m in _CAP_RE.finditer(fmt)]
    if not caps:
        return None
    w, h = row.get("width"), row.get("height")
    if not w or not h:
        return "다운로드 기록에 해상도 없음"
    binding = [(d, n) for d, n in caps if RUNG * (h if d == "height" else w) > n]
    if not binding or min(w, h) >= FULL_HD_SHORT_SIDE:
        return None
    d, n = binding[0]
    return (f"형식 제한({d}<={n})이 걸린 {w}x{h} 파일(짧은 변 {min(w, h)} < {FULL_HD_SHORT_SIDE}) → 레퍼런스가 더 큰 "
            "렌디션을 제공했을 수 있어 해상도·fps 의 하한값일 뿐(세로 영상의 height<=N 은 긴 변을 자름)")


def download_cap_note(row: dict) -> str | None:
    fmt = str(row.get("requested_format") or "")
    w, h = row.get("width"), row.get("height")
    if not (w and h):
        return None
    binding = [(m.group(1), int(m.group(2))) for m in _CAP_RE.finditer(fmt)
               if RUNG * (h if m.group(1) == "height" else w) > int(m.group(2))]
    return f"형식 제한 {binding[0][0]}<={binding[0][1]} 에 닿은 렌디션(원본 업로드는 더 클 수 있음)" if binding else None


def canvas_resolution_rows(preset: str, snap: dict, include_long: bool,
                           membership: dict[str, str]) -> tuple[dict[str, list[dict]], list[dict], dict]:
    """Per-video (width, height, fps) of the snapshot's downloaded Shorts: the latest
    reference/downloads.jsonl record, re-probed from the file when it is present."""
    from ..util.jsonio import read_jsonl
    from ..util.media import probe
    from .common import reference_dir, video_path

    recs: dict[str, dict] = {}
    for r in read_jsonl(reference_dir(preset) / "downloads.jsonl"):
        if r.get("video_id"):
            recs[r["video_id"]] = r
    rows: dict[str, list[dict]] = {"width": [], "height": [], "fps": []}
    excluded: list[dict] = []
    aspects: Counter = Counter()
    snap_videos = (snap.get("videos") or []) if snap.get("status") in ("ok", "partial") else []
    for v in snap_videos:
        vid = v.get("video_id")
        if not vid or (v.get("kind") == "video" and not include_long) or vid not in recs:
            continue
        rec = dict(recs[vid])
        src = "reference/downloads.jsonl"
        try:
            f = video_path(preset, vid)
        except ValueError:
            f = None
        if f is not None:
            pi = probe(f)
            if pi.width and pi.height:
                rec.update(width=int(pi.width), height=int(pi.height), fps=round(float(pi.fps), 3) if pi.fps else None)
                src = "ffprobe " + paths.relp(f)
        issue = download_cap_issue(rec)
        if issue:
            excluded.append({"video_id": vid, "reason": issue, "width": rec.get("width"), "height": rec.get("height"),
                             "fps": rec.get("fps"), "requested_format": rec.get("requested_format")})
            continue
        note = f"스트림 속성(파일 전체), {src}; 형식 {rec.get('format_id')}"
        if download_cap_note(rec):
            note += "; " + download_cap_note(rec)
        base = {"video_id": vid, "format_id": membership.get(vid), "t": 0.0, "frame": None, "note": note}
        if rec.get("width") and rec.get("height"):
            rows["width"].append({**base, "value": int(rec["width"])})
            rows["height"].append({**base, "value": int(rec["height"])})
            aspects[_aspect(int(rec["width"]), int(rec["height"]))] += 1
        if rec.get("fps"):
            rows["fps"].append({**base, "value": float(rec["fps"])})
    return rows, excluded, {"counts": dict(aspects.most_common()),
                            "mode": aspects.most_common(1)[0][0] if aspects else None}


def _aspect(w: int, h: int) -> str:
    for a, b in ((9, 16), (16, 9), (1, 1), (4, 5), (3, 4), (4, 3), (2, 3)):
        if abs(w / h - a / b) <= 0.01:
            return f"{a}:{b}"
    g = math.gcd(w, h)
    return f"{w // g}:{h // g}"


CANVAS_SIZE_METHOD = (
    "reference/downloads.jsonl 의 영상별 최신 기록(파일이 있으면 ffprobe 로 다시 확인)의 {what} → 스냅샷 쇼츠 영상 간 최빈값"
    "(value_rule=mode; n/p10/p50/p90 은 분포 확인용). 형식 제한(height<=N 등)이 걸려 짧은 변이 1080 미만인 파일은 낮은 "
    "렌디션일 수 있어 제외(excluded; 세로 영상의 height<=1080 은 608x1080·480x854 가 됨). 좌표 규칙: 모든 좌표·크기 항목은 각 영상 자신의 해상도에서 측정되고, 종횡비가 캔버스와 같은 영상만 "
    "x·폭 ×(canvas.width/영상 너비), y·높이 ×(canvas.height/영상 높이) 로 환산해 그 항목의 resolution 과 함께 저장된다. "
    "캔버스가 그 resolution 과 다르면 소비하는 쪽이 x·폭 ×(canvas.width/resolution[0]), y·높이 ×(canvas.height/"
    "resolution[1]) 로 다시 환산한다(종횡비가 다른 영상은 좌표 집계에서 제외).")


# ============================================================================= safe margins
SAFE_MARGIN_METHOD = (
    "영상별로 모든 자막 역할(제목·설명·상황·인물·대사·반응; 채널 식별 문구 제외)의 잉크 상자 ∪ 배경 박스"
    "(episode validate 의 caption_outside_safe 와 같은 사각형)의 최소/최대 끝 → 화면 가장자리까지 거리(영상별 최소 여백) → "
    "캔버스 해상도로 환산 → 영상 간 p10(value_rule=p10: 레퍼런스 영상의 90% 가 이 여백보다 안쪽에 자막을 둠)")


def safe_margin_rows(videos: dict[str, dict], scale: Callable) -> dict[str, list[dict]]:
    rows: dict[str, list[dict]] = {k: [] for k in ("left", "right", "top", "bottom")}
    for vid, d in videos.items():
        cap = d.get("captions") or {}
        sc = scale(d)
        res = cap.get("resolution") or d.get("resolution")
        if not sc or not res:
            continue
        W, H = res
        ext = []
        for it in cap.get("items") or []:
            if it.get("role") not in ROLES or not it.get("bbox"):
                continue
            x, y, w, h = it["bbox"]
            x0, y0, x1, y1 = x, y, x + w, y + h
            bx = ((it.get("style") or {}).get("box") or {})
            if bx.get("present") == "present" and bx.get("bbox"):
                X, Y, BW, BH = bx["bbox"]
                x0, y0, x1, y1 = min(x0, X), min(y0, Y), max(x1, X + BW), max(y1, Y + BH)
            ext.append((x0, y0, x1, y1, it))
        if not ext:
            continue
        for side, val, s_ in (("left", lambda e: e[0], sc[0]), ("right", lambda e: W - e[2], sc[0]),
                              ("top", lambda e: e[1], sc[1]), ("bottom", lambda e: H - e[3], sc[1])):
            e = min(ext, key=val)
            it = e[4]
            rows[side].append({"video_id": vid, "format_id": d["format_id"], "value": round(val(e) * s_, 1),
                               "t": it.get("t_rep", it.get("start")), "frame": it.get("frame"),
                               "note": f"{it.get('role')} 자막 '{str(it.get('text') or '')[:20]}'"})
    return rows


def _zoom_dur(e: dict) -> float:
    """Full eased zoom duration when the ease fit is decisive (the threshold run misses the slow
    start / end of an eased curve), else the threshold run length."""
    fit = e.get("ease_fit") or {}
    return float(fit["dur_s"]) if fit.get("ease") and fit.get("dur_s") else float(e["dur_s"])


# ============================================================================= dialogue quote marks
QUOTE_METHOD = (
    "대사(dialogue) 자막 OCR 텍스트의 첫 글자·마지막 글자가 따옴표인지(textboxes.quote_pair): 양쪽 다 → 그 쌍, 양쪽 다 없음 → "
    "없음([]), 한쪽만 → OCR 누락으로 보고 제외 → 영상별 최빈 쌍 → 영상 간 최빈(value = [여는 문자, 닫는 문자] 또는 []). "
    "한계: 대사 역할 판정 자체가 따옴표를 근거로 쓰므로 따옴표 없는 대사는 말소리 겹침(audio/original.json)이나 글자색으로 "
    "대사로 잡힌 경우에만 관측됨; OCR 은 “ 와 \" 를 혼동할 수 있음(글자 모양 확인은 사람 관찰로)")


def _pair_key(q: dict) -> str:
    return "none" if q["kind"] == "none" else f"{q['open']}…{q['close']}"


def _pair_value(key: str | None) -> list[str] | None:
    if key is None:
        return None
    if key == "none":
        return []
    o, c = key.split("…", 1)
    return [o, c]


def quote_marks_item(videos: dict[str, dict], blocker: str) -> dict:
    from .textboxes import quote_pair

    rows, partial, reasons = [], 0, Counter()
    for vid, d in videos.items():
        keys, first = [], None
        for it in (d.get("captions") or {}).get("items") or []:
            if it.get("role") != "dialogue":
                continue
            q = quote_pair(it.get("text") or "")
            reasons["따옴표" if "따옴표" in str(it.get("role_reason") or "") else "말소리/글자색"] += 1
            if q["kind"] == "partial":
                partial += 1
                continue
            keys.append(_pair_key(q))
            if first is None:
                first = it
        if keys:
            rows.append({"video_id": vid, "format_id": d["format_id"], "value": _video_mode(keys),
                         "t": first.get("t_rep", first.get("start")), "frame": first.get("frame")})
    it = cat_item("text.roles.dialogue.quote_marks", rows, QUOTE_METHOD, blocker,
                  extra={"value_encoding": "counts 의 키 '<여는>…<닫는>' 또는 'none' → value [여는, 닫는] 또는 []",
                         "partial_items_excluded": partial, "dialogue_basis": dict(reasons)})
    it["value"] = _pair_value(it["value"])
    for st in it["by_format"].values():
        st["value"] = _pair_value(st.get("value"))
    for e in it["evidence"]:
        e["value"] = _pair_value(e["value"])
    return it


# ============================================================================= tone
def ending_class(text: str) -> tuple[str, str] | None:
    """(class, last word) of a caption line by its sentence ending."""
    t = re.sub(r"[\s\"'“”‘’「」『』.,!?~…·ㅋㅎ\U0001F300-\U0001FAFF]+$", "", (text or "").strip())
    if not t:
        return None
    w = t.split()[-1]
    if not re.search(r"[가-힣]$", w):
        return "명사형/기타", w
    if re.search(r"(습니다|습니까|ㅂ니다|입니다|합니다|됩니다|니다)$", w):
        return "합쇼체", w
    if re.search(r"(요|죠)$", w):
        return "해요체", w
    last = w[-1]
    jong = (ord(last) - 0xAC00) % 28
    if jong == 16 and len(w) >= 2 and not re.search(r"(사람|마음|처음|다음|이름|요즘|지금|아이템)$", w):
        return "음슴체", w          # -(으)ㅁ nominal ending: 있음, 했음, 없음
    if re.search(r"(다|냐|니|야|어|아|지|네|자|래|걸|군|나|까|게|대|더라|거든|잖아)$", w):
        return "반말", w
    return "명사형/기타", w


def tone_items(videos: dict[str, dict], blocker: str) -> list[dict]:
    rows_reg, ends, ev = [], Counter(), []
    per_class = Counter()
    for vid, d in videos.items():
        caps = d.get("captions") or {}
        cls = Counter()
        for c in caps.get("items") or []:
            if c.get("role") not in NARRATION_ROLES:
                continue
            for line in (c.get("text") or "").split("\n")[-1:]:
                r = ending_class(line)
                if r is None:
                    continue
                cls[r[0]] += 1
                per_class[r[0]] += 1
                if r[0] != "명사형/기타":
                    ends[r[1][-2:] if len(r[1]) >= 2 else r[1]] += 1
                    if len(ev) < 5:
                        ev.append({"video_id": vid, "t": c.get("start"), "value": line, "frame": c.get("frame")})
        sent = {k: v for k, v in cls.items() if k != "명사형/기타"}
        if sent:
            top, n = max(sent.items(), key=lambda kv: kv[1])
            reg = REGISTER_MAP[top] if n / sum(sent.values()) >= 0.6 else "혼합"
            rows_reg.append({"video_id": vid, "format_id": d.get("format_id"), "value": reg})
    method = ("주 자막(제목·설명·상황·반응) 마지막 어절의 종결 어미 분류(합쇼체/해요체/음슴체/반말/명사형) → 영상별 최빈 "
              "종결(60% 이상이면 그 말투, 아니면 혼합) → 영상 간 최빈값. OCR 오인식 영향 있음")
    reg_item = cat_item("text.tone.register", rows_reg, method, blocker,
                        extra={"ending_counts": dict(per_class.most_common())})
    if ev:
        reg_item["evidence"] = ev
    ex_item = {"key": "text.tone.sentence_end_examples", "unit": None, "resolution": None,
               "method": "종결 어미(마지막 두 글자) 빈도 상위 8개", "measured_at": now_iso()}
    if ends:
        ex_item.update({"status": "measured", "value": [e for e, _ in ends.most_common(8)],
                        "overall": {"n": sum(ends.values()), "counts": dict(ends.most_common(20))},
                        "by_format": {}, "evidence": ev, "blocker": None})
    else:
        ex_item.update({"status": "unmeasured", "value": None, "overall": {"n": 0}, "by_format": {}, "evidence": [],
                        "blocker": blocker})
    return [reg_item, ex_item]


# ============================================================================= main
def _load_videos(preset: str, ids: list[str], membership: dict[str, str]) -> dict[str, dict]:
    out = {}
    for vid in ids:
        d = analysis_dir(preset, vid)
        data = {n: read_json(d / f"{n}.json") for n in ("layout", "captions", "motion", "shots")}
        if not any(data.values()):
            continue
        res = None
        for n in ("layout", "captions", "motion", "shots"):
            if data[n] and data[n].get("resolution"):
                res = data[n]["resolution"]
                break
        data["resolution"] = res
        data["format_id"] = membership.get(vid)
        out[vid] = data
    return out


def aggregate(preset: str, ids: list[str] | None = None, include_long: bool = False) -> dict:
    """``include_long``: also use long-form (``kind: video``) uploads; by default only Shorts (and
    videos whose kind is unknown) are measured, because this preset reproduces Shorts editing."""
    pr = load_preset(preset)
    Wc, Hc = int(pr.get("canvas.width")), int(pr.get("canvas.height"))
    roles = [r for r in pr.section("text.roles").keys()]
    membership = load_membership(preset)
    snap = load_snapshot(preset) or {}
    ids = ids if ids is not None else resolve_ids(preset, set_name="analyzed")
    kinds = {v["video_id"]: v.get("kind") for v in snap.get("videos") or []}
    excluded_long = [v for v in ids if kinds.get(v) == "video"] if not include_long else []
    ids = [v for v in ids if v not in excluded_long]
    videos = _load_videos(preset, ids, membership)
    no_data = snapshot_blocker(preset) if not videos else None
    canvas_res = [Wc, Hc]

    def blk(specific: str) -> str:
        return no_data or specific

    def scale(d: dict) -> tuple[float, float] | None:
        res = d.get("resolution")
        if not res:
            return None
        W, H = res
        if abs(W / H - Wc / Hc) > 0.01:
            return None           # different aspect ratio: coordinates cannot be mapped
        return Wc / W, Hc / H

    groups: dict[str, list[dict]] = {"visual_canvas": [], "visual_text": [], "visual_tone": [], "visual_motion": [],
                                     "visual_structure": []}
    # ---------------------------------------------------------------- canvas
    rows: dict[str, list[dict]] = {k: [] for k in ("x", "y", "w", "h", "type", "color")}
    for vid, d in videos.items():
        lay = d.get("layout") or {}
        sc = scale(d)
        vr = lay.get("video_region")
        ev = {"video_id": vid, "format_id": d["format_id"], "t": None, "frame": None}
        if vr and sc:
            for k, s in (("x", sc[0]), ("y", sc[1]), ("w", sc[0]), ("h", sc[1])):
                rows[k].append({**ev, "value": round(vr[k] * s, 1)})
        if lay.get("background") not in (None, "unmeasured"):
            rows["type"].append({**ev, "value": lay["background"]})
            if lay["background"] == "color" and lay.get("background_color"):
                rows["color"].append({**ev, "value": lay["background_color"]})
    m_reg = "영상 밖 정적 배경 대비 움직이는 영역(프레임 간 변화 비율 >50% 행·열) → 캔버스 해상도로 환산"
    for k in ("x", "y", "w", "h"):
        groups["visual_canvas"].append(num_item(f"canvas.video_region.{k}", rows[k], "px", m_reg,
                                                blk("영상 영역을 찾은 영상 없음"), canvas_res, digits=1, as_int=True))
    groups["visual_canvas"].append(cat_item("canvas.background.type", rows["type"],
                                            "영상 밖 영역: 정지+단색 → color, 변하지만 흐림 → blur_source",
                                            blk("배경이 보이는 영상 없음")))
    groups["visual_canvas"].append(color_item("canvas.background.color", rows["color"], "영상 밖 정지 영역의 중앙값 색",
                                              blk("단색 배경 영상 없음")))
    groups["visual_canvas"].append(unmeasured("canvas.video_region.fit", blk(
        "결과 화면만으로는 원본 비율을 알 수 없어 cover/contain 판정 불가(원본 추적 후 비교 필요)")))
    groups["visual_canvas"].append(unmeasured("canvas.background.blur_sigma", blk(
        "흐림 배경의 흐림 정도를 원본 없이 역산하는 방법 없음")))
    # ---------------------------------------------------------------- canvas size / fps (downloads + probe)
    crow, cexcl, aspect = canvas_resolution_rows(preset, snap, include_long, membership)
    if snap.get("status") not in ("ok", "partial"):
        cblk = snapshot_blocker(preset)
    elif cexcl and not crow["width"]:
        cblk = ("받은 파일이 모두 낮은 렌디션일 수 있음: " + cexcl[0]["reason"] + " → `shortkit ref download` 형식을 짧은 변 "
                "기준으로 바꿔 다시 받아야 함")
    else:
        cblk = "스냅샷 쇼츠 중 받은 영상 없음(`shortkit ref download --set latest100` 필요)"
    cextra = {"aspect": aspect, "excluded": cexcl}
    for key, rk, unit, what, digits in (("canvas.width", "width", "px", "너비", 0),
                                        ("canvas.height", "height", "px", "높이", 0),
                                        ("canvas.fps", "fps", "fps", "프레임률", 3)):
        groups["visual_canvas"].append(num_item(key, crow[rk], unit, CANVAS_SIZE_METHOD.format(what=what), cblk,
                                                rule="mode", digits=digits, as_int=(digits == 0), extra=cextra))
    # ---------------------------------------------------------------- safe margins
    smr = safe_margin_rows(videos, scale)
    for side in ("left", "right", "top", "bottom"):
        groups["visual_canvas"].append(num_item(f"canvas.safe_margin.{side}", smr[side], "px", SAFE_MARGIN_METHOD,
                                                blk("자막(역할 판정됨)이 검출된, 캔버스와 종횡비가 같은 영상 없음"),
                                                canvas_res, rule="p10", digits=1))
    # ---------------------------------------------------------------- text roles
    for role in roles:
        R: dict[str, list[dict]] = {}

        def add(k, vid, d, value, t=None, frame=None):
            R.setdefault(k, []).append({"video_id": vid, "format_id": d["format_id"], "value": value, "t": t,
                                        "frame": frame})

        present = 0
        for vid, d in videos.items():
            lay = (d.get("layout") or {}).get("roles", {}).get(role)
            if not lay:
                continue
            present += 1
            sc = scale(d)
            evd = (lay.get("evidence") or [{}])[0]
            t, fr = evd.get("t"), evd.get("frame")
            if sc:
                if lay.get("size_px") is not None:
                    add("size_px", vid, d, round(lay["size_px"] * sc[1], 2), t, fr)
                if lay.get("anchor", {}).get("x") is not None:
                    add("anchor.x", vid, d, round(lay["anchor"]["x"] * sc[0], 1), t, fr)
                if lay.get("anchor", {}).get("y") is not None:
                    add("anchor.y", vid, d, round(lay["anchor"]["y"] * sc[1], 1), t, fr)
                if lay.get("outline_px") is not None:
                    add("outline_px", vid, d, round(lay["outline_px"] * sc[1], 2), t, fr)
                if lay.get("shadow_px") is not None:
                    add("shadow_px", vid, d, round(lay["shadow_px"] * sc[1], 2), t, fr)
                bx = lay.get("box") or {}
                if bx.get("pad_x") is not None:
                    add("box.pad_x", vid, d, round(bx["pad_x"] * sc[0], 1), t, fr)
                if bx.get("pad_y") is not None:
                    add("box.pad_y", vid, d, round(bx["pad_y"] * sc[1], 1), t, fr)
                if lay.get("max_width_px") is not None:
                    add("max_width_px", vid, d, round(lay["max_width_px"] * sc[0], 1), t, fr)
            if lay.get("align") not in (None, "unmeasured"):
                add("anchor.align", vid, d, lay["align"], t, fr)
            if lay.get("valign") not in (None, "unmeasured"):
                add("anchor.valign", vid, d, lay["valign"], t, fr)
            add("color", vid, d, lay.get("color"), t, fr)
            if lay.get("highlight_color"):
                add("highlight_color", vid, d, lay["highlight_color"], t, fr)
            if lay.get("outline_color") and lay.get("outline_visibility") == "visible":
                add("outline_color", vid, d, lay["outline_color"], t, fr)
            if lay.get("shadow_color"):
                add("shadow_color", vid, d, lay["shadow_color"], t, fr)
            bx = lay.get("box") or {}
            if bx.get("present") in ("present", "absent"):
                add("box.enabled", vid, d, bx["present"] == "present", t, fr)
            if bx.get("color"):
                add("box.color", vid, d, bx["color"], t, fr)
            if bx.get("alpha") is not None:
                add("box.alpha", vid, d, bx["alpha"], t, fr)
            if lay.get("line_spacing") is not None:
                add("line_spacing", vid, d, lay["line_spacing"], t, fr)
            if lay.get("max_chars_per_line") is not None:
                add("max_chars_per_line", vid, d, lay["max_chars_per_line"], t, fr)
            if lay.get("max_lines") is not None:
                add("max_lines", vid, d, lay["max_lines"], t, fr)
            mi, mo = lay.get("motion_in") or {}, lay.get("motion_out") or {}
            if mi.get("type"):
                add("motion_in.type", vid, d, mi["type"], t, fr)
            if mi.get("dur_s") is not None:
                add("motion_in.dur_s", vid, d, mi["dur_s"], t, fr)
            if mi.get("scale_from") is not None:
                add("motion_in.scale_from", vid, d, mi["scale_from"], t, fr)
            if mi.get("offset_px") is not None and sc:
                add("motion_in.offset_px", vid, d, round(mi["offset_px"] * sc[1], 1), t, fr)
            if mo.get("type"):
                add("motion_out.type", vid, d, mo["type"], t, fr)
            if mo.get("dur_s") is not None:
                add("motion_out.dur_s", vid, d, mo["dur_s"], t, fr)
            tm = lay.get("timing") or {}
            if tm.get("min_dur_s") is not None and lay.get("persist") != "whole_video":
                add("timing.min_dur_s", vid, d, tm["min_dur_s"], t, fr)
            if tm.get("lead_s") is not None:
                add("timing.lead_s", vid, d, tm["lead_s"], t, fr)
            if lay.get("persist"):
                add("persist", vid, d, lay["persist"], t, fr)
        rb = blk(f"'{role}' 역할 자막이 검출된 영상 없음")
        pre = f"text.roles.{role}."
        G = groups["visual_text"]
        m = "영상별 역할 중앙값 → 영상 간 분포"
        G.append(num_item(pre + "size_px", R.get("size_px", []), "px",
                          "한글 잉크 높이 / 보정 글꼴(libass 렌더) 잉크 비율 → libass Fontsize, " + m, rb, canvas_res, digits=2))
        G.append(num_item(pre + "anchor.x", R.get("anchor.x", []), "px",
                          "정렬 기준점(가운데 정렬=잉크 상자 중심, 왼쪽=왼쪽 끝) x, " + m, rb, canvas_res, digits=1))
        G.append(num_item(pre + "anchor.y", R.get("anchor.y", []), "px",
                          "세로 기준점(valign 측정값: top=잉크 상자 위, middle=중심, bottom=아래; 못 잰 영상은 중심), " + m, rb,
                          canvas_res, digits=1))
        G.append(cat_item(pre + "anchor.valign", R.get("anchor.valign", []),
                          "한 줄/여러 줄 자막 사이에 고정되는 가장자리(위·중심·아래)", blk(
                              f"'{role}': 한 줄과 여러 줄 자막이 모두 있는 영상 없음")))
        G.append(cat_item(pre + "anchor.align", R.get("anchor.align", []),
                          "여러 줄 자막(또는 폭이 다른 자막들)의 왼쪽/가운데/오른쪽 끝 표준편차 최소", blk(
                              f"'{role}': 정렬을 가를 수 있는 자료(여러 줄·폭이 다른 자막) 없음")))
        G.append(color_item(pre + "color", R.get("color", []), "획 중심 픽셀의 주 색(k-means 2)", rb))
        G.append(color_item(pre + "highlight_color", R.get("highlight_color", []),
                            "획 중심 픽셀의 두 번째 색(12% 이상, 외곽선 혼합색 제외)",
                            blk(f"'{role}': 강조색 사용 사례 없음(검출 {present}편)")))
        G.append(num_item(pre + "outline_px", R.get("outline_px", []), "px",
                          "채움 경계에서 바깥으로 거리 고리별 외곽선색 비율의 합, " + m,
                          blk(f"'{role}': 외곽선을 배경과 구분할 수 있는 사례 없음"), canvas_res, digits=2))
        G.append(color_item(pre + "outline_color", R.get("outline_color", []), "채움 바로 바깥 1~2px 고리의 중앙값 색",
                            blk(f"'{role}': 보이는 외곽선 사례 없음")))
        G.append(num_item(pre + "shadow_px", R.get("shadow_px", []), "px", "오른쪽 아래 방향 비대칭 어두운 복사본 거리",
                          blk(f"'{role}': 배경이 복잡해 그림자 판정 불가"), canvas_res, digits=2))
        G.append(color_item(pre + "shadow_color", R.get("shadow_color", []), "그림자 영역 중앙값 색",
                            blk(f"'{role}': 그림자 사례 없음")))
        G.append(cat_item(pre + "box.enabled", R.get("box.enabled", []), "잉크 상자 4변 밖 밝기 계단(>=15, 같은 부호)",
                          rb))
        G.append(color_item(pre + "box.color", R.get("box.color", []),
                            "박스 = a*C + (1-a)*배경 회귀(나타나기 전 프레임 대비)", blk(f"'{role}': 박스 색·투명도 회귀 가능한 사례 없음")))
        G.append(num_item(pre + "box.alpha", R.get("box.alpha", []), "ratio",
                          "박스 = a*C + (1-a)*배경 회귀(정지 배경 픽셀)", blk(f"'{role}': 박스 투명도 회귀 가능한 사례 없음")))
        G.append(num_item(pre + "box.pad_x", R.get("box.pad_x", []), "px", "박스 가장자리 - 잉크 가장자리(좌우 평균)",
                          blk(f"'{role}': 박스 사례 없음"), canvas_res, digits=1))
        G.append(num_item(pre + "box.pad_y", R.get("box.pad_y", []), "px", "박스 가장자리 - 잉크 가장자리(위아래 평균)",
                          blk(f"'{role}': 박스 사례 없음"), canvas_res, digits=1))
        G.append(num_item(pre + "line_spacing", R.get("line_spacing", []), "ratio",
                          "여러 줄 자막의 줄 중심 간격 / size_px", blk(f"'{role}': 여러 줄 자막 사례 없음"), digits=3))
        G.append(num_item(pre + "max_chars_per_line", R.get("max_chars_per_line", []), "chars",
                          "영상별 한 줄 최대 글자 수(OCR, 공백 포함) → 영상 간 p90", rb, rule="p90", as_int=True))
        G.append(num_item(pre + "max_lines", R.get("max_lines", []), "lines", "영상별 최대 줄 수 → 영상 간 p90", rb,
                          rule="p90", as_int=True))
        G.append(num_item(pre + "max_width_px", R.get("max_width_px", []), "px", "영상별 최대 잉크 폭 → 영상 간 p90", rb,
                          canvas_res, rule="p90", digits=1))
        G.append(cat_item(pre + "motion_in.type", R.get("motion_in.type", []),
                          "원래 프레임률에서 등장 궤적(크기·위치·알파) 분류 → 영상별 최빈", blk(
                              f"'{role}': 등장 모션을 볼 수 있는 사례 없음")))
        G.append(num_item(pre + "motion_in.dur_s", R.get("motion_in.dur_s", []), "s",
                          "첫 보이는 프레임 → 정지 상태 도달(±1프레임)", blk(f"'{role}': 등장 모션 사례 없음"), digits=3))
        G.append(num_item(pre + "motion_in.scale_from", R.get("motion_in.scale_from", []), "ratio",
                          "pop 첫 프레임 크기 / 정지 크기", blk(f"'{role}': pop 등장 사례 없음"), digits=3))
        G.append(num_item(pre + "motion_in.offset_px", R.get("motion_in.offset_px", []), "px",
                          "slide 첫 프레임 위치 차이", blk(f"'{role}': slide 등장 사례 없음"), canvas_res, digits=1))
        G.append(cat_item(pre + "motion_out.type", R.get("motion_out.type", []), "퇴장 궤적 분류 → 영상별 최빈",
                          blk(f"'{role}': 퇴장 모션을 볼 수 있는 사례 없음")))
        G.append(num_item(pre + "motion_out.dur_s", R.get("motion_out.dur_s", []), "s", "정지 상태 → 마지막 보이는 프레임",
                          blk(f"'{role}': 퇴장 모션 사례 없음"), digits=3))
        G.append(num_item(pre + "timing.min_dur_s", R.get("timing.min_dur_s", []), "s",
                          "영상별 가장 짧은 표시 시간 → 영상 간 p50", blk(f"'{role}': 시간제 자막 사례 없음"), digits=3))
        G.append(num_item(pre + "timing.lead_s", R.get("timing.lead_s", []), "s",
                          "대사 자막 시작 - 겹치는 원음 말소리 시작(오디오 분석 필요)",
                          blk(f"'{role}': 기준 사건(말소리 시작)과 짝지을 수 있는 사례 없음 — 대사 외 역할은 기준 사건 정의 없음"),
                          digits=3))
        G.append(cat_item(pre + "persist", R.get("persist", []), "영상 길이의 90% 이상 표시되면 whole_video", rb))
    # ---------------------------------------------------------------- dialogue quote marks
    groups["visual_text"].append(quote_marks_item(videos, blk("'dialogue' 역할 자막이 검출된 영상 없음")))
    # ---------------------------------------------------------------- tone
    groups["visual_tone"] += tone_items(videos, blk("나레이션 자막 OCR 텍스트 없음"))
    # ---------------------------------------------------------------- motion
    M: dict[str, list[dict]] = {}
    pres = {k: Counter() for k in ("zoom", "freeze", "speed", "flash")}
    for vid, d in videos.items():
        mot = d.get("motion") or {}
        shots = d.get("shots") or {}
        for k in pres:
            if mot.get("presence"):
                pres[k][mot["presence"].get(k, "unmeasured")] += 1
        ev = mot.get("events") or []
        zi = [e for e in ev if e["type"] == "zoom_in"]

        def addm(k, value, t=None):
            M.setdefault(k, []).append({"video_id": vid, "format_id": d["format_id"], "value": value, "t": t,
                                        "frame": None})

        if zi:
            addm("motion.zoom.scale_to", round(float(np.median([e["scale_to"] for e in zi])), 4), zi[0]["t"])
            addm("motion.zoom.dur_s", round(float(np.median([_zoom_dur(e) for e in zi])), 3), zi[0]["t"])
        zz = [e for e in ev if e["type"] in ("zoom_in", "zoom_out")]
        eases = [(e["ease_fit"] or {}).get("ease") for e in zz if e.get("ease_fit")]
        if any(eases):
            first = next(e for e in zz if (e.get("ease_fit") or {}).get("ease"))
            addm("motion.zoom.ease", _video_mode(eases), first["t"])
        rcs = [(e.get("recenter_fit") or {}).get("recenter") for e in zz]
        if any(r is not None for r in rcs):
            first = next(e for e in zz if (e.get("recenter_fit") or {}).get("recenter") is not None)
            addm("motion.zoom.recenter", _video_mode(rcs), first["t"])
        fz = [e for e in ev if e["type"] == "freeze"]
        if fz:
            addm("motion.freeze.hold_s", round(float(np.median([e["hold_s"] for e in fz])), 3), fz[0]["t"])
        sp = [e for e in ev if e["type"] == "speed" and e.get("factor") and e["factor"] < 1]
        if sp:
            addm("motion.speed.slowmo_factor", round(float(np.median([e["factor"] for e in sp])), 3), sp[0]["t"])
        cuts = shots.get("cuts") or []
        if shots:
            if cuts:
                c = Counter(x["type"] for x in cuts).most_common(1)[0][0]
                addm("motion.transitions.default", c, cuts[0]["t"])
            fl = [x for x in cuts if x["type"] == "flash"]
            if fl:
                addm("motion.transitions.flash.dur_s", round(float(np.median([x["dur"] for x in fl])), 3), fl[0]["t"])
                addm("motion.transitions.flash.color", color_mode([x.get("color") for x in fl])["mode"], fl[0]["t"])
                scopes = [(x.get("scope") or {}).get("value") for x in fl]
                if any(scopes):
                    first = next(x for x in fl if (x.get("scope") or {}).get("value"))
                    addm("motion.transitions.flash.scope", _video_mode(scopes), first["t"])
            cf = [x for x in cuts if x["type"] == "crossfade"]
            if cf:
                addm("motion.transitions.crossfade.dur_s", round(float(np.median([x["dur"] for x in cf])), 3), cf[0]["t"])
    G = groups["visual_motion"]
    pz = {"presence": {k: dict(v) for k, v in pres.items()}}
    G.append(num_item("motion.zoom.scale_to", M.get("motion.zoom.scale_to", []), "ratio",
                      "영상별 확대(zoom_in) 배율 중앙값(ORB 유사변환 누적; 원본 카메라 줌과 구분 못 함)",
                      blk("확대가 검출된 영상 없음"), digits=4, extra=pz))
    G.append(num_item("motion.zoom.dur_s", M.get("motion.zoom.dur_s", []), "s",
                      "영상별 확대 길이 중앙값(ease 곡선 맞춤이 판정된 사건은 맞춘 곡선의 전체 길이 — 느린 시작·끝 포함, "
                      "아니면 프레임당 0.3% 이상 변하는 구간 길이)", blk("확대가 검출된 영상 없음"), digits=3))
    zev = [e for d in videos.values() for e in ((d.get("motion") or {}).get("events") or [])
           if e.get("type") in ("zoom_in", "zoom_out")]
    zst = {"zoom_events": len(zev), "ramps_fitted": sum(1 for e in zev if e.get("ease_fit")),
           "ease_decided": sum(1 for e in zev if (e.get("ease_fit") or {}).get("ease")),
           "recenter_decided": sum(1 for e in zev if (e.get("recenter_fit") or {}).get("recenter") is not None)}
    G.append(cat_item("motion.zoom.ease", M.get("motion.zoom.ease", []),
                      "확대 사건마다 누적 배율 곡선(사건 ±0.5초, 같은 샷)을 렌더러 ease(linear=u, in=u^3, "
                      "out=1-(1-u)^3, inout) 곡선 c0+A*ease((t-t0)/dur) 에 맞춤(t0·dur 1/4프레임 격자, c0·A 최소제곱) → "
                      "두 번째로 좋은 곡선보다 SSE 1.5배 이상 좋고 잔차 ≤ 진폭 8% 일 때만 그 ease → 영상별 최빈 → 영상 간 최빈",
                      blk("ease 를 판정할 수 있는 확대(느린 램프, 잡음 적음)가 검출된 영상 없음"), extra={"basis": zst}))
    G.append(cat_item("motion.zoom.recenter", M.get("motion.zoom.recenter", []),
                      "확대 사건의 누적 유사변환 T_k 와 (1-z_k) 로 겉보기 고정점 맞춤: 순수 확대이고 고정점이 영상 영역 안(중심 "
                      "근처 제외) → false(고정점 제자리 = 렌더러 recenter=false 로 그대로 재현), 고정점이 영역 밖이거나 확대 중 "
                      "화면 중심 쪽으로 이동 → true(렌더러 recenter=true: 목표점이 같은 ease 로 중심으로 이동). 중심 근처 확대는 "
                      "두 방식 결과가 같아 제외. 한계: 목표점이 중심 가까이 있던 recenter=true 확대도 '영역 안 고정점'으로 보임",
                      blk("고정점을 판정할 수 있는 확대(중심에서 떨어진 확대)가 검출된 영상 없음"), extra={"basis": zst}))
    G.append(num_item("motion.freeze.hold_s", M.get("motion.freeze.hold_s", []), "s",
                      "영상별 정지(프레임 반복, 앞뒤 움직임 있음) 길이 중앙값", blk("정지 화면이 검출된 영상 없음"), digits=3))
    G.append(num_item("motion.speed.slowmo_factor", M.get("motion.speed.slowmo_factor", []), "ratio",
                      "프레임 복제율 변화로 본 재생 속도 비(프레임 보간 슬로모션은 검출 못 함)",
                      blk("프레임 복제식 속도 변화가 검출된 영상 없음(보간식은 측정 방법 없음)"), digits=3))
    G.append(cat_item("motion.transitions.default", M.get("motion.transitions.default", []),
                      "영상별 가장 많은 전환 종류(cut/flash/crossfade)", blk("컷 분석 결과 없음")))
    G.append(num_item("motion.transitions.flash.dur_s", M.get("motion.transitions.flash.dur_s", []), "s",
                      "플래시(밝기 급등) 길이 중앙값", blk("플래시가 검출된 영상 없음"), digits=3))
    G.append(color_item("motion.transitions.flash.color", M.get("motion.transitions.flash.color", []),
                        "플래시 최고 밝기 프레임의 평균 색", blk("플래시가 검출된 영상 없음")))
    G.append(cat_item("motion.transitions.flash.scope", M.get("motion.transitions.flash.scope", []),
                      "플래시 최고 밝기 프레임 vs 앞뒤 0.1~0.25초 프레임 중앙값: 영상 영역 밖(가장자리 2% 제외, 밝아질 여유 "
                      "있는 픽셀) 중 영역 안 평균 상승의 40%(최소 15) 이상 밝아진 비율 ≥ 0.6 → canvas(화면 전체), ≤ 0.15 → "
                      "region(영상 영역만), 그 사이·영상이 화면 전체 → 판정 안 함 → 영상별 최빈 → 영상 간 최빈",
                      blk("플래시가 검출되고 영상 영역 밖이 보이는 영상 없음")))
    G.append(num_item("motion.transitions.crossfade.dur_s", M.get("motion.transitions.crossfade.dur_s", []), "s",
                      "섞임 구간(블렌드 가중치 0→1) 길이 중앙값", blk("크로스페이드가 검출된 영상 없음"), digits=3))
    # ---------------------------------------------------------------- structure
    S: list[dict] = []
    snap_ok = snap.get("status") in ("ok", "partial")
    if snap_ok:
        for v in snap.get("videos") or []:
            if v.get("kind") == "video" and not include_long:
                continue
            if v.get("duration") is not None:
                S.append({"video_id": v["video_id"], "format_id": membership.get(v["video_id"]),
                          "value": float(v["duration"]), "t": None, "frame": None})
    else:
        for vid, d in videos.items():
            dur = (d.get("shots") or {}).get("duration") or (d.get("captions") or {}).get("duration")
            if dur:
                S.append({"video_id": vid, "format_id": d["format_id"], "value": float(dur), "t": None, "frame": None})
    # the preset stores the distribution itself (structure.duration_s.{n,p10,p50,p90}): one item per leaf
    dmethod = ("latest100 스냅샷의 영상 길이(플랫폼 메타데이터)" if snap_ok else "분석한 영상 파일의 길이")
    dblk = snapshot_blocker(preset) if not S else ""
    for leaf in ("p10", "p50", "p90"):
        groups["visual_structure"].append(num_item(f"structure.duration_s.{leaf}", S, "s", dmethod + f" → {leaf}",
                                                   dblk, rule=leaf, digits=2))
    n_item = num_item("structure.duration_s.n", S, "videos", dmethod + " → 표본 수", dblk, digits=0)
    if n_item["status"] == "measured":
        n_item["value"] = int(n_item["overall"]["n"])
        for st in n_item["by_format"].values():
            st["value"] = int(st["n"])
    groups["visual_structure"].append(n_item)
    F = []
    for vid, d in videos.items():
        items = [c for c in (d.get("captions") or {}).get("items") or []
                 if c["role"] not in ("title", "description", "identity_mark", "unknown")]
        if items:
            first = min(items, key=lambda c: c["start"])
            F.append({"video_id": vid, "format_id": d["format_id"], "value": first["start"], "t": first["start"],
                      "frame": first.get("frame")})
    groups["visual_structure"].append(num_item("structure.first_caption_at_s", F, "s",
                                               "영상별 첫 시간제 자막(제목·설명 제외) 시작 시각", blk("시간제 자막 없음"),
                                               digits=3))
    # ---------------------------------------------------------------- write
    mdir = paths.preset_dir(preset) / "measurements"
    written = {}
    basis = {"n_videos_analyzed": len(videos), "video_ids": sorted(videos)[:200],
             "excluded_long_form": excluded_long,
             "formats_assigned": sum(1 for d in videos.values() if d["format_id"]),
             "canvas_resolution": canvas_res}
    for group, items in groups.items():
        out = {"schema": SCHEMA, "group": group, "preset_id": pr.preset_id,
               "source_snapshot": snap.get("captured_at"), "source_snapshot_status": snap.get("status"),
               "generated_at": now_iso(), "generated_by": "shortkit ref aggregate", "basis": basis, "items": items}
        write_json(mdir / f"{group}.json", out)
        written[group] = {"items": len(items), "measured": sum(i["status"] == "measured" for i in items)}
    tot = sum(v["items"] for v in written.values())
    meas = sum(v["measured"] for v in written.values())
    say(f"측정 집계: 영상 {len(videos)}편, 항목 {tot}개 중 측정 {meas}개 / 못 잼 {tot - meas}개 → {paths.relp(mdir)}/visual_*.json")
    # manual.json holds the decoration keys, whose automatic detector output lives in the same
    # analysis files: refresh it together so it never lags behind the analysis
    from .manual import aggregate_manual
    man = aggregate_manual(preset, include_long=include_long, ids=list(videos))
    written["manual"] = {"items": man["items"], "measured": man["measured"]}
    return {"videos": len(videos), "groups": written}


_ = (ROLES, Callable, Path)
