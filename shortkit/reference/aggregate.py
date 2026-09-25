"""Aggregate per-video visual analysis into preset measurements (docs/CONTRACT.md section 2).

Reads ``analysis/<id>/{layout,captions,motion,shots}.json`` of the analysed reference videos and
format membership from ``formats.yaml`` and writes ``presets/<name>/measurements/visual_*.json``
items keyed by preset keys.  Every numeric item carries ``overall`` and ``by_format``
``{n, p10, p50, p90}``; categorical items carry counts / mode; coordinates and sizes are scaled
from each video's resolution to the preset canvas and stored with ``resolution``.  Keys without
data are written as ``status: unmeasured`` with a ``blocker`` -- never a default value.

Unit of observation: one value per video (the video's median / mode / max for the role, as the
method says), so long videos do not dominate; ``n`` = number of videos contributing.

Basis: ONLY members of the fixed latest-N snapshot (``common.production_basis``); other analysed videos
(older high-view videos ...) are listed in ``basis.excluded_non_snapshot`` and never enter a value.
Coordinates: every px item keeps the per-video values in their own pixels (``native.by_resolution``)
and is scaled to ``scaled_to`` = the MEASURED canvas (canvas.width/height mode) when measured, else the
preset canvas (recorded as such).  ``visual_presence.json`` holds channel-level tri-state items
``presence.{zoom,freeze,speed_change,flash,crossfade,decorations}``.
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
from .common import (ROLES, analysis_dir, basis_record, color_mode, load_snapshot, production_basis, region_evidence,
                     say, snapshot_blocker, video_path)

SCHEMA = "shortkit.measurement/1"
NARRATION_ROLES = ("title", "description", "situation", "reaction")
REGISTER_MAP = {"반말": "반말_구어체", "해요체": "해요체", "음슴체": "음슴체", "합쇼체": "합쇼체"}
# structure.first_caption_at_s = each video's first TIMED caption: roles that frame the whole video (title,
# description), the channel's identity marks and unclassified lines are left out.  Shared definition: episode validate
# (edit.validate.first_caption_excluded_roles) and QA (qa.checks.first_timed_caption) use the same roles.
FIRST_CAPTION_EXCLUDED_ROLES = ("title", "description", "identity_mark", "unknown")


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
        nat = native_stats(rows, rule, digits)
        if nat:
            it["native"] = nat
    if extra:
        it.update(extra)
    return it


def native_stats(rows: list[dict], rule: str = "p50", digits: int = 3) -> dict | None:
    """Coordinates / sizes in each video's OWN pixels (before scaling to the canvas), grouped by that
    native resolution: {"WxH": {n, p10, p50, p90, value}} -- the stored value is the scaled one; this
    keeps the measurement with the resolution it was taken at (AGENTS.md rule 3)."""
    nat = [r for r in rows if r.get("native") is not None and r.get("native_res")]
    if not nat:
        return None
    out = {}
    for res in sorted({r["native_res"] for r in nat}):
        out[res] = _stats_with_value([float(r["native"]) for r in nat if r["native_res"] == res], rule, digits, False)
    return {"by_resolution": out, "note": "각 영상 자체 해상도(환산 전)의 값 — 해상도별 분포"}


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
                               "native": round(float(val(e)), 1), "native_res": f"{W}x{H}",
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
# 음슴체 = a predicate nominalised with -(으)ㅁ (했음, 들킴, 발견됨, 당황함, 실화임).  The same -ㅁ also ends
# ordinary nouns -- many of them lexicalised nominalisations (모음 'collection', 싸움, 웃음, 느낌, 모임) or
# Sino-Korean nouns (긴장감, 관심, 작품, 책임) -- and a noun phrase is register-NEUTRAL.  A wrong 음슴체 shifts
# the measured register of the reference (and what validate / QA enforce); a missed one only drops a sample,
# so an ambiguous word is classified 명사형/기타.  A word equal to, or ending in, one of these nouns is a noun.
_M_NOUNS = frozenset("""
모음 마음 처음 다음 소음 싸움 도움 배움 어려움 웃음 울음 걸음 믿음 얼음 죽음 젊음 묶음 볶음 졸음 물음 잡음 녹음 발음
복음 굉음 방음 폭음 그림 느낌 기쁨 슬픔 아픔 외침 떨림 울림 흐름 소름 다짐 만남 어둠 오줌 아침 기침 점심
사람 이름 요즘 지금 조금 소금 가슴 여름 구름 기름 보름 바람 알람 새봄 올봄 늦봄
아이템 시스템 프로그램 크림 드림 볼륨 앨범 게임 모임 움직임 타임 라임
고함 포함 결함 전함 군함 잠수함 책임 담임 신임 후임 전임 선임 주임 취임 사임 부임 해임 방임
체험 시험 실험 경험 모험 보험 위험 관심 진심 욕심 결심 중심 조심 양심 의심 호기심 작품 제품 상품 명품 농담 상담
장점 단점 약점 강점 요점 시점 지점 관점 초점 만점 정점 허점 결점 문제점 공통점 차이점
공감 호감 반감 쾌감 영감 예감 실감 직감 식감 촉감 질감 색감 동감 유감 긴장감 존재감 자신감 책임감 만족감 안도감
배신감 위기감 불안감 기대감 거리감 속도감 무게감 현장감 소속감 박탈감 죄책감 열등감 우월감 해방감 친근감 이질감
입체감 몰입감 성취감 절망감 좌절감 허탈감 상실감 압박감 부담감
""".split())
# 2+-syllable Sino-Korean nouns ending in 의 (not the genitive particle -의)
_UI_NOUNS = frozenset("거의 회의 주의 동의 합의 강의 논의 문의 정의 예의 의의 협의 건의 결의 제의 호의 편의 성의 고의 모의".split())
_JONG_SS, _JONG_BS, _JONG_M = 20, 18, 16          # ㅆ, ㅄ, ㅁ final-consonant indices of a Hangul syllable


def _jong(ch: str) -> int | None:
    o = ord(ch) - 0xAC00
    return o % 28 if 0 <= o < 11172 else None


def _is_eumseum(w: str, prev: str | None = None) -> bool:
    """Is the (Hangul-final) word ``w`` a predicate nominalised with -(으)ㅁ?  ``prev`` = the word before it.

    0. not closed by ㅁ -> no; a known noun (``_M_NOUNS``: the word or its ending) -> no
    1. ``됨`` (only ever 되- + ㅁ): 됨, 안됨, 발견됨 -> yes
    2. ``함`` (하- + ㅁ): 함, 당황함, 도착함 -> yes
    3. ``임`` after a noun (이- + ㅁ): 실화임, 레전드임, 보임 -> yes; a bare 임 -> no
    4. ``음`` after a syllable closed by ㅆ/ㅄ (past / future / existence stem): 했음, 있음, 없음, 갔음, 겠음 -> yes
    ---- below: the word could also be a noun; a genitive ``prev`` (X의 + word = noun phrase) -> no
    5. ``음`` after any other closed syllable (consonant stem + 음): 좋음, 같음, 먹음, 괜찮음 -> yes
    6. ``음`` right after an open syllable: a vowel stem takes -ㅁ, not -음, so this is a 으-stem nominal that reads
       as a noun in practice (모음, 마음, 처음, 다음, 소음) -> no
    7. the honorific suffix ``님`` (사장님, 선생님) -> no, except 아님 (아니- + ㅁ)
    8. another syllable closed by ㅁ after an open verb stem (들키- 들킴, 모르- 모름, 사라지- 사라짐, 끝나- 끝남): yes
       when the word has >= 2 syllables; a one-syllable word (감, 봄, 옴, 잠, 참, 꿈, 밤 ...) -> no
    """
    if not w or _jong(w[-1]) != _JONG_M:
        return False
    if any(w == n or w.endswith(n) for n in _M_NOUNS):
        return False
    last = w[-1]
    if last in ("됨", "함"):
        return True
    if last == "임":
        return len(w) >= 2
    if last == "음" and len(w) >= 2 and _jong(w[-2]) in (_JONG_SS, _JONG_BS):
        return True
    if prev and len(prev) >= 2 and prev.endswith("의") and prev not in _UI_NOUNS:
        return False                      # genitive: "고양이의 귀여움" is a noun phrase
    if last == "음":
        return len(w) >= 2 and bool(_jong(w[-2]))         # rules 5 / 6
    if last == "님":
        return w.endswith("아님")
    return len(w) >= 2                    # rule 8


def ending_class(text: str) -> tuple[str, str] | None:
    """(class, last word) of a caption line by its sentence ending.  Shared by the reference analyzer
    (``tone_items``), ``shortkit.edit.validate.check_tone`` and QA (``shortkit.qa.probes_text.classify_register``);
    음슴체 rules: ``_is_eumseum``."""
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
    words = t.split()
    if _is_eumseum(w, words[-2] if len(words) >= 2 else None):
        return "음슴체", w          # -(으)ㅁ nominalised predicate: 있음, 했음, 들킴, 발견됨, 당황함, 실화임
    if _jong(w[-1]) == _JONG_M:
        return "명사형/기타", w      # ㅁ-final noun (모음, 사람, 게임 ...): register-neutral
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


# ============================================================================= channel-level presence
# presence.* are preset style keys (added in review-fix wave 2, together with the reclassification of
# motion.zoom.max_consecutive / motion.freeze.max_per_video from 'rule' to measured style keys).
PRESENCE_VISUAL_KEYS = tuple(f"presence.{k}" for k in ("zoom", "freeze", "speed_change", "flash", "crossfade",
                                                       "decorations"))
PRESENCE_RULE = ("영상별 있다/없다/못 잼 → 채널 값: 측정된 영상 중 한 편이라도 있다 → present, 측정된 영상이 모두 없다 → absent, "
                 "측정된 영상 없음 → 못 잼(unmeasured). n = 있다/없다가 측정된 영상 수, n_present·share = 있다 영상 수·비율 "
                 "(n_unmeasured = 못 잰 영상 수, 포맷별도 같은 규칙)")


def _presence_summary(rows: list[dict]) -> dict:
    meas = [r for r in rows if r.get("value") in ("present", "absent")]
    n_p = sum(1 for r in meas if r["value"] == "present")
    n = len(meas)
    return {"n": n, "n_present": n_p, "n_absent": n - n_p, "n_unmeasured": len(rows) - n,
            "share": round(n_p / n, 4) if n else None,
            "value": "present" if n_p else ("absent" if n else None)}


def presence_item(key: str, rows: list[dict], method: str, blocker: str, extra: dict | None = None) -> dict:
    """Channel-level tri-state measurement item (present|absent; unmeasured when no video was measured).

    rows: one per video {video_id, format_id, value: present|absent|unmeasured, t, frame, note}."""
    ov = _presence_summary(rows)
    byf = {f: _presence_summary([r for r in rows if r.get("format_id") == f])
           for f in sorted({r["format_id"] for r in rows if r.get("format_id")})}
    it: dict[str, Any] = {"key": key, "unit": "tri_state", "resolution": None, "method": method,
                          "value_rule": PRESENCE_RULE, "measured_at": now_iso(), "overall": ov, "by_format": byf}
    ev = [r for r in rows if r.get("value") == "present"] or [r for r in rows if r.get("value") == "absent"]
    evidence = [{"video_id": r["video_id"], "t": r.get("t"), "value": r["value"], "frame": r.get("frame"),
                 **({"note": r["note"]} if r.get("note") else {})} for r in ev[:5]]
    if ov["value"] is None:
        why = Counter(str(r.get("note") or "못 잼") for r in rows)
        it.update({"status": "unmeasured", "value": None, "presence": "unmeasured", "evidence": [],
                   "blocker": blocker + (" (영상별 사유: " + "; ".join(f"{k} {v}편" for k, v in why.most_common(3)) + ")"
                                         if rows else "")})
    else:
        it.update({"status": "measured", "value": ov["value"], "presence": ov["value"], "evidence": evidence,
                   "blocker": None})
    if extra:
        it.update(extra)
    return it


def _first_t(events: list[dict], pred) -> float | None:
    ts = [float(e["t"]) for e in events if pred(e) and e.get("t") is not None]
    return round(min(ts), 3) if ts else None


def visual_presence_rows(videos: dict[str, dict], manual_deco: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """Per-video tri-states for presence.{zoom, freeze, speed_change, flash, crossfade, decorations}."""
    out: dict[str, list[dict]] = {k: [] for k in ("zoom", "freeze", "speed_change", "flash", "crossfade",
                                                  "decorations")}
    for vid, d in videos.items():
        mot, shots = d.get("motion"), d.get("shots")
        base = {"video_id": vid, "format_id": d["format_id"], "frame": None}
        mev = (mot or {}).get("events") or []
        cuts = (shots or {}).get("cuts") or []
        mp = (mot or {}).get("presence") or {}
        sp = (shots or {}).get("presence") or {}
        no_rec = "presence 기록 없음(이전 형식 분석 — `ref analyze` 재실행 필요)"
        spec = [("zoom", mp.get("zoom") if mot else None, _first_t(mev, lambda e: str(e.get("type", "")).startswith("zoom")),
                 no_rec if mot else "motion.json 없음"),
                ("freeze", mp.get("freeze") if mot else None, _first_t(mev, lambda e: e.get("type") == "freeze"),
                 no_rec if mot else "motion.json 없음"),
                ("speed_change", mp.get("speed") if mot else None, _first_t(mev, lambda e: e.get("type") == "speed"),
                 no_rec if mot else "motion.json 없음"),
                ("flash", sp.get("flash") if shots else (mp.get("flash") if mot else None),
                 _first_t(cuts or mev, lambda c: c.get("type") == "flash"), no_rec if (shots or mot) else "shots.json 없음"),
                ("crossfade", sp.get("crossfade") if shots else None,
                 _first_t(cuts, lambda c: c.get("type") == "crossfade"), no_rec if shots else "shots.json 없음")]
        for k, val, t, missing in spec:
            val = val if val in ("present", "absent", "unmeasured") else None
            note = None
            if val is None:
                val, note = "unmeasured", missing
            elif val == "unmeasured":
                note = ("프레임 복제식이 아닌 속도 변화는 검출 못 함(못 찾으면 못 잼)" if k == "speed_change"
                        else "검출기가 이 영상에서 판정 못 함")
            elif val == "absent":
                note, t = "영상 전체를 검사해 찾지 못함(검출기 기준)", 0.0
            out[k].append({**base, "value": val, "t": t, "note": note})
        # decorations: the automatic detector is EXPERIMENTAL -> it can confirm presence, never absence
        items = ((mot or {}).get("decorations") or {}).get("items") or []
        man = manual_deco.get(vid) or []
        if items:
            it0 = min(items, key=lambda i: float(i.get("t") or 0))
            out["decorations"].append({**base, "value": "present", "t": it0.get("frame_t", it0.get("t")),
                                       "note": f"자동 검출 {it0.get('kind')} (실험 기능)"})
        elif man:
            r0 = min(man, key=lambda r: r["t"])
            out["decorations"].append({**base, "value": "present", "t": r0["t"],
                                       "note": f"사람 관찰 {r0['key']} ({r0.get('observed_by')})"})
        else:
            out["decorations"].append({**base, "value": "unmeasured", "t": None,
                                       "note": "장식 자동 검출기는 실험 기능이라 '없다'를 확정하지 못함(사람 관찰 필요)"})
    return out


PRESENCE_VISUAL_METHOD = {
    "zoom": "analysis/<id>/motion.json presence.zoom (ORB 유사변환 누적 배율; 원본 카메라 줌과 구분 못 함)",
    "freeze": "motion.json presence.freeze (프레임 반복 + 앞뒤 움직임)",
    "speed_change": "motion.json presence.speed (프레임 복제율 변화; 보간식 슬로모션은 검출 못 해 '없다' 대신 못 잼)",
    "flash": "shots.json presence.flash (밝기 급등 전환)",
    "crossfade": "shots.json presence.crossfade (블렌드 가중치 0→1 전환)",
    "decorations": ("motion.json decorations(실험 자동 검출: 화살표·원·네모) 또는 manual_observations.csv 의 decorations.* "
                    "관찰 행 → 있다; 자동 검출기로는 '없다'를 확정할 수 없어 나머지는 못 잼"),
}


# ============================================================================= per-video counts (S1-12)
def _segments_zoomed(shots: dict, events: list[dict], duration: float | None) -> list[bool]:
    """Shots (between transitions: cut / flash / crossfade) in order -> does a zoom_in/zoom_out start in it."""
    bounds = sorted({float(c["t"]) for c in shots.get("cuts") or [] if c.get("t") is not None})
    edges = [0.0] + bounds + [float(duration) if duration else float("inf")]
    zt = [float(e["t"]) for e in events if str(e.get("type", "")).startswith("zoom")]
    return [any(a <= t < b for t in zt) for a, b in zip(edges[:-1], edges[1:]) if b > a]


def _longest_run(flags: list[bool]) -> int:
    run = best = 0
    for f in flags:
        run = run + 1 if f else 0
        best = max(best, run)
    return best


def count_rows(videos: dict[str, dict]) -> tuple[list[dict], list[dict]]:
    """(freeze count per video, longest run of consecutive zoomed shots per video)."""
    fr, zc = [], []
    for vid, d in videos.items():
        mot, shots = d.get("motion") or {}, d.get("shots")
        pres = mot.get("presence") or {}
        ev = mot.get("events") or []
        if pres.get("freeze") in ("present", "absent"):
            fz = [e for e in ev if e.get("type") == "freeze"]
            fr.append({"video_id": vid, "format_id": d["format_id"], "value": len(fz),
                       "t": round(float(fz[0]["t"]), 3) if fz else 0.0, "frame": None,
                       "note": None if fz else "영상 전체에서 0회"})
        if pres.get("zoom") in ("present", "absent") and shots:
            dur = shots.get("duration") or mot.get("duration")
            flags = _segments_zoomed(shots, ev, dur)
            best = _longest_run(flags)
            zt = [float(e["t"]) for e in ev if str(e.get("type", "")).startswith("zoom")]
            zc.append({"video_id": vid, "format_id": d["format_id"], "value": best,
                       "t": round(min(zt), 3) if zt else 0.0, "frame": None,
                       "note": f"샷 {len(flags)}개 중 확대 샷 {sum(flags)}개, 최장 연속 {best}개"})
    return fr, zc


# ============================================================================= cut structure (S2QA-15)
# Transitions counted as shot boundaries: every type shots.json records.  QA ``structure.cuts`` counts the same three
# types in the output (grid.our_cuts), so the reference distribution and the output value share one definition.
TRANSITION_TYPES = ("cut", "flash", "crossfade")
PARTIAL_ANALYSIS_TOL_S = 1.5          # analysed span shorter than the platform duration by more -> partial analysis
CUT_RATE_METHOD = ("영상별 전환 수(shots.json cuts 의 cut·flash·crossfade, 0초 < t < 분석 길이 — QA structure.cuts 가 출력에서 "
                   "세는 것과 같은 정의) / 분석 길이(shots.json duration) × 10 → 영상 간 분포")
SHOT_LEN_METHOD = ("영상별 샷 길이 = 전환 시각 사이 간격(0초~첫 전환, 마지막 전환~영상 끝 포함; 전환 없는 영상은 영상 길이 "
                   "1개) → 영상별 중앙값 → 영상 간 분포 (QA structure.cuts 의 '샷 길이 중앙값'과 같은 단위)")


def cut_structure_rows(videos: dict[str, dict], platform_durations: dict[str, float]) -> dict:
    """Per-video cut density and median shot length from ``shots.json``.

    -> {"rate": rows, "shot_len": rows, "excluded": [{video_id, reason}], "pooled_shot_len": [all shot lengths],
        "types": Counter of counted transition types, "per_video": {vid: {...}}}.
    A video is left out (with the reason) when its cuts were not measured (no shots.json, too few frames, no
    duration) or when shots.json covers only part of the video (analysed span shorter than the platform duration by
    more than PARTIAL_ANALYSIS_TOL_S or 5 %): a rate / last shot of a partial analysis would describe another length."""
    rate, slen, excluded, pooled, per = [], [], [], [], {}
    types: Counter = Counter()
    for vid, d in videos.items():
        sh = d.get("shots")
        if not sh:
            excluded.append({"video_id": vid, "reason": "shots.json 없음(`shortkit ref analyze --only shots`)"})
            continue
        pres = sh.get("presence") or {}
        if pres and all(pres.get(k) == "unmeasured" for k in TRANSITION_TYPES):
            excluded.append({"video_id": vid, "reason": f"컷 검출 못 잼({sh.get('note') or 'presence 전부 unmeasured'})"})
            continue
        try:
            dur = float(sh.get("duration") or 0.0)
        except (TypeError, ValueError):
            dur = 0.0
        if dur <= 0:
            excluded.append({"video_id": vid, "reason": "shots.json duration 없음"})
            continue
        ref = platform_durations.get(vid)
        if ref and dur < ref - max(PARTIAL_ANALYSIS_TOL_S, 0.05 * ref):
            excluded.append({"video_id": vid, "reason": f"부분 분석: shots.json 분석 길이 {dur:.2f}s < 영상 길이 {ref:.2f}s "
                                                        "(전체를 다시 분석해야 함)"})
            continue
        cuts = [c for c in sh.get("cuts") or [] if c.get("type") in TRANSITION_TYPES and c.get("t") is not None
                and 0.0 < float(c["t"]) < dur]
        ts = sorted(float(c["t"]) for c in cuts)
        types.update(c["type"] for c in cuts)
        edges = [0.0] + ts + [dur]
        shots = [round(b - a, 3) for a, b in zip(edges, edges[1:]) if b - a > 1e-3]
        pooled += shots
        r = round(len(ts) / dur * 10.0, 3)
        m = round(float(np.median(shots)), 3)
        base = {"video_id": vid, "format_id": d["format_id"], "frame": None}
        rate.append({**base, "value": r, "t": round(ts[0], 3) if ts else 0.0,
                     "note": f"전환 {len(ts)}개 / {dur:.2f}s"})
        slen.append({**base, "value": m, "t": round(ts[0], 3) if ts else 0.0,
                     "note": f"샷 {len(shots)}개(첫·마지막 샷 포함), 중앙값 {m}s"})
        per[vid] = {"format_id": d["format_id"], "duration": round(dur, 3), "n_transitions": len(ts),
                    "cuts_per_10s": r, "shot_len_median_s": m, "n_shots": len(shots)}
    return {"rate": rate, "shot_len": slen, "excluded": excluded, "pooled_shot_len": pooled, "types": types,
            "per_video": per}


def distribution_items(base: str, rows: list[dict], unit: str, method: str, blocker: str, digits: int,
                       extra: dict | None = None) -> list[dict]:
    """A preset distribution ``<base>.{p10,p50,p90,n}`` (the preset stores the distribution itself): one item per
    leaf, each with overall + by_format {n, p10, p50, p90}; the ``n`` item's value is the sample count."""
    out = [num_item(f"{base}.{leaf}", rows, unit, method + f" → {leaf}", blocker, rule=leaf, digits=digits, extra=extra)
           for leaf in ("p10", "p50", "p90")]
    # same distribution (same digits) as the leaf items; only the value is the sample count
    n_item = num_item(f"{base}.n", rows, "videos", method + " → 표본 수", blocker, digits=digits, extra=extra)
    if n_item["status"] == "measured":
        n_item["value"] = int(n_item["overall"]["n"])
        for st in n_item["by_format"].values():
            st["value"] = int(st["n"])
    return out + [n_item]


# ============================================================================= target canvas (S1-09)
def target_canvas(pr, canvas_items: dict[str, dict]) -> tuple[list[int], dict]:
    """Canvas the coordinates are scaled to: the MEASURED canvas (canvas.width / canvas.height mode of the
    snapshot's downloads) when both are measured, else the preset canvas (provisional).  -> ([W, H], scaled_to)."""
    w, h = canvas_items.get("canvas.width") or {}, canvas_items.get("canvas.height") or {}
    if w.get("status") == "measured" and h.get("status") == "measured" and w.get("value") and h.get("value"):
        res = [int(w["value"]), int(h["value"])]
        return res, {"resolution": res, "source": "measured",
                     "note": "측정한 캔버스(canvas.width/height = 스냅샷 다운로드 해상도 최빈값)로 환산"}
    res = [int(pr.get("canvas.width")), int(pr.get("canvas.height"))]
    return res, {"resolution": res, "source": f"preset ({pr.origin('canvas.width')})",
                 "note": "캔버스 크기가 측정되지 않아 프리셋 canvas.width/height(임시값일 수 있음)로 환산 — 측정 후 다시 집계"}


def aggregate(preset: str, ids: list[str] | None = None, include_long: bool = False) -> dict:
    """``include_long``: also use long-form (``kind: video``) uploads; by default only Shorts (and
    videos whose kind is unknown) are measured, because this preset reproduces Shorts editing.

    Only members of the fixed latest-N snapshot are used (``production_basis``): any other video
    (older high-view videos, whole-channel analyses) is listed under ``basis.excluded_non_snapshot`` and
    reported only in ``reference/high_views_report.json``."""
    pr = load_preset(preset)
    roles = [r for r in pr.section("text.roles").keys()]
    membership = load_membership(preset)
    snap = load_snapshot(preset) or {}
    pb = production_basis(preset, ids, include_long=include_long)
    videos = _load_videos(preset, pb["ids"], membership)
    no_data = (pb["blocker"] or snapshot_blocker(preset)) if not videos else None

    def blk(specific: str) -> str:
        return no_data or specific

    groups: dict[str, list[dict]] = {"visual_canvas": [], "visual_text": [], "visual_tone": [], "visual_motion": [],
                                     "visual_structure": [], "visual_presence": []}
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
    csize = {}
    for key, rk, unit, what, digits in (("canvas.width", "width", "px", "너비", 0),
                                        ("canvas.height", "height", "px", "높이", 0),
                                        ("canvas.fps", "fps", "fps", "프레임률", 3)):
        csize[key] = num_item(key, crow[rk], unit, CANVAS_SIZE_METHOD.format(what=what), cblk,
                              rule="mode", digits=digits, as_int=(digits == 0), extra=cextra)
    canvas_res, scaled_to = target_canvas(pr, csize)
    Wc, Hc = canvas_res
    sx_extra = {"scaled_to": scaled_to}

    def scale(d: dict) -> tuple[float, float] | None:
        res = d.get("resolution")
        if not res:
            return None
        W, H = res
        if abs(W / H - Wc / Hc) > 0.01:
            return None           # different aspect ratio: coordinates cannot be mapped
        return Wc / W, Hc / H

    def nres(d: dict) -> str | None:
        r = d.get("resolution")
        return f"{int(r[0])}x{int(r[1])}" if r else None

    # ---------------------------------------------------------------- canvas region / background
    rows: dict[str, list[dict]] = {k: [] for k in ("x", "y", "w", "h", "type", "color")}
    for vid, d in videos.items():
        lay = d.get("layout") or {}
        sc = scale(d)
        vr = lay.get("video_region")
        rd = lay.get("region_detection") or {}
        evd = rd.get("evidence")
        if not evd:            # analysis made before the evidence frame was stored: add it now
            dur = (d.get("shots") or {}).get("duration") or (d.get("captions") or {}).get("duration")
            try:
                vfile = video_path(preset, vid)
            except ValueError:
                vfile = None
            evd = region_evidence(preset, vid, vfile, {"video_region": vr, **rd}, dur)
        ev = {"video_id": vid, "format_id": d["format_id"], "t": evd.get("t"), "frame": evd.get("frame"),
              "note": evd.get("note")}
        if vr and sc:
            for k, s in (("x", sc[0]), ("y", sc[1]), ("w", sc[0]), ("h", sc[1])):
                rows[k].append({**ev, "value": round(vr[k] * s, 1), "native": vr[k], "native_res": nres(d)})
        if lay.get("background") not in (None, "unmeasured"):
            rows["type"].append({**ev, "value": lay["background"]})
            if lay["background"] == "color" and lay.get("background_color"):
                rows["color"].append({**ev, "value": lay["background_color"]})
    m_reg = "영상 밖 정적 배경 대비 움직이는 영역(프레임 간 변화 비율 >50% 행·열) → 캔버스 해상도로 환산"
    for k in ("x", "y", "w", "h"):
        groups["visual_canvas"].append(num_item(f"canvas.video_region.{k}", rows[k], "px", m_reg,
                                                blk("영상 영역을 찾은 영상 없음"), canvas_res, digits=1, as_int=True,
                                                extra=sx_extra))
    groups["visual_canvas"].append(cat_item("canvas.background.type", rows["type"],
                                            "영상 밖 영역: 정지+단색 → color, 변하지만 흐림 → blur_source",
                                            blk("배경이 보이는 영상 없음")))
    groups["visual_canvas"].append(color_item("canvas.background.color", rows["color"], "영상 밖 정지 영역의 중앙값 색",
                                              blk("단색 배경 영상 없음")))
    groups["visual_canvas"].append(unmeasured("canvas.video_region.fit", blk(
        "결과 화면만으로는 원본 비율을 알 수 없어 cover/contain 판정 불가(원본 추적 후 비교 필요)")))
    groups["visual_canvas"].append(unmeasured("canvas.background.blur_sigma", blk(
        "흐림 배경의 흐림 정도를 원본 없이 역산하는 방법 없음")))
    groups["visual_canvas"] += list(csize.values())
    # ---------------------------------------------------------------- safe margins
    smr = safe_margin_rows(videos, scale)
    for side in ("left", "right", "top", "bottom"):
        groups["visual_canvas"].append(num_item(f"canvas.safe_margin.{side}", smr[side], "px", SAFE_MARGIN_METHOD,
                                                blk("자막(역할 판정됨)이 검출된, 캔버스와 종횡비가 같은 영상 없음"),
                                                canvas_res, rule="p10", digits=1, extra=sx_extra))
    # ---------------------------------------------------------------- text roles
    for role in roles:
        R: dict[str, list[dict]] = {}

        def add(k, vid, d, value, t=None, frame=None, native=None):
            row = {"video_id": vid, "format_id": d["format_id"], "value": value, "t": t, "frame": frame}
            if native is not None:
                row.update(native=native, native_res=nres(d))
            R.setdefault(k, []).append(row)

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
                for k, raw, s_, dg in (("size_px", lay.get("size_px"), sc[1], 2),
                                       ("anchor.x", (lay.get("anchor") or {}).get("x"), sc[0], 1),
                                       ("anchor.y", (lay.get("anchor") or {}).get("y"), sc[1], 1),
                                       ("outline_px", lay.get("outline_px"), sc[1], 2),
                                       ("shadow_px", lay.get("shadow_px"), sc[1], 2),
                                       ("box.pad_x", (lay.get("box") or {}).get("pad_x"), sc[0], 1),
                                       ("box.pad_y", (lay.get("box") or {}).get("pad_y"), sc[1], 1),
                                       ("max_width_px", lay.get("max_width_px"), sc[0], 1)):
                    if raw is not None:
                        add(k, vid, d, round(raw * s_, dg), t, fr, native=raw)
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
                add("motion_in.offset_px", vid, d, round(mi["offset_px"] * sc[1], 1), t, fr, native=mi["offset_px"])
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
                          "한글 잉크 높이 / 보정 글꼴(libass 렌더) 잉크 비율 → libass Fontsize, " + m, rb, canvas_res, digits=2,
                          extra=sx_extra))
        G.append(num_item(pre + "anchor.x", R.get("anchor.x", []), "px",
                          "정렬 기준점(가운데 정렬=잉크 상자 중심, 왼쪽=왼쪽 끝) x, " + m, rb, canvas_res, digits=1,
                          extra=sx_extra))
        G.append(num_item(pre + "anchor.y", R.get("anchor.y", []), "px",
                          "세로 기준점(valign 측정값: top=잉크 상자 위, middle=중심, bottom=아래; 못 잰 영상은 중심), " + m, rb,
                          canvas_res, digits=1, extra=sx_extra))
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
                          blk(f"'{role}': 외곽선을 배경과 구분할 수 있는 사례 없음"), canvas_res, digits=2, extra=sx_extra))
        G.append(color_item(pre + "outline_color", R.get("outline_color", []), "채움 바로 바깥 1~2px 고리의 중앙값 색",
                            blk(f"'{role}': 보이는 외곽선 사례 없음")))
        G.append(num_item(pre + "shadow_px", R.get("shadow_px", []), "px", "오른쪽 아래 방향 비대칭 어두운 복사본 거리",
                          blk(f"'{role}': 배경이 복잡해 그림자 판정 불가"), canvas_res, digits=2, extra=sx_extra))
        G.append(color_item(pre + "shadow_color", R.get("shadow_color", []), "그림자 영역 중앙값 색",
                            blk(f"'{role}': 그림자 사례 없음")))
        G.append(cat_item(pre + "box.enabled", R.get("box.enabled", []), "잉크 상자 4변 밖 밝기 계단(>=15, 같은 부호)",
                          rb))
        G.append(color_item(pre + "box.color", R.get("box.color", []),
                            "박스 = a*C + (1-a)*배경 회귀(나타나기 전 프레임 대비)", blk(f"'{role}': 박스 색·투명도 회귀 가능한 사례 없음")))
        G.append(num_item(pre + "box.alpha", R.get("box.alpha", []), "ratio",
                          "박스 = a*C + (1-a)*배경 회귀(정지 배경 픽셀)", blk(f"'{role}': 박스 투명도 회귀 가능한 사례 없음")))
        G.append(num_item(pre + "box.pad_x", R.get("box.pad_x", []), "px", "박스 가장자리 - 잉크 가장자리(좌우 평균)",
                          blk(f"'{role}': 박스 사례 없음"), canvas_res, digits=1, extra=sx_extra))
        G.append(num_item(pre + "box.pad_y", R.get("box.pad_y", []), "px", "박스 가장자리 - 잉크 가장자리(위아래 평균)",
                          blk(f"'{role}': 박스 사례 없음"), canvas_res, digits=1, extra=sx_extra))
        G.append(num_item(pre + "line_spacing", R.get("line_spacing", []), "ratio",
                          "여러 줄 자막의 줄 중심 간격 / size_px", blk(f"'{role}': 여러 줄 자막 사례 없음"), digits=3))
        G.append(num_item(pre + "max_chars_per_line", R.get("max_chars_per_line", []), "chars",
                          "영상별 한 줄 최대 글자 수(OCR, 공백 포함) → 영상 간 p90", rb, rule="p90", as_int=True))
        G.append(num_item(pre + "max_lines", R.get("max_lines", []), "lines", "영상별 최대 줄 수 → 영상 간 p90", rb,
                          rule="p90", as_int=True))
        G.append(num_item(pre + "max_width_px", R.get("max_width_px", []), "px", "영상별 최대 잉크 폭 → 영상 간 p90", rb,
                          canvas_res, rule="p90", digits=1, extra=sx_extra))
        G.append(cat_item(pre + "motion_in.type", R.get("motion_in.type", []),
                          "원래 프레임률에서 등장 궤적(크기·위치·알파) 분류 → 영상별 최빈", blk(
                              f"'{role}': 등장 모션을 볼 수 있는 사례 없음")))
        G.append(num_item(pre + "motion_in.dur_s", R.get("motion_in.dur_s", []), "s",
                          "첫 보이는 프레임 → 정지 상태 도달(±1프레임)", blk(f"'{role}': 등장 모션 사례 없음"), digits=3))
        G.append(num_item(pre + "motion_in.scale_from", R.get("motion_in.scale_from", []), "ratio",
                          "pop 첫 프레임 크기 / 정지 크기", blk(f"'{role}': pop 등장 사례 없음"), digits=3))
        G.append(num_item(pre + "motion_in.offset_px", R.get("motion_in.offset_px", []), "px",
                          "slide 첫 프레임 위치 차이", blk(f"'{role}': slide 등장 사례 없음"), canvas_res, digits=1,
                          extra=sx_extra))
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
    fr_rows, zc_rows = count_rows(videos)
    G.append(num_item("motion.zoom.max_consecutive", zc_rows, "segments",
                      "영상별로 전환(cut/flash/crossfade) 사이 샷을 순서대로 보고 확대(zoom_in/zoom_out) 사건이 시작되는 샷이 "
                      "연속되는 최대 개수(episode validate 의 zoom_stacked·QA video.zoom 과 같은 정의: 연속 세그먼트의 줌) → "
                      "영상 간 p90(value_rule=p90, 정수; 확대 판정이 있다/없다로 측정된 영상만, 0 포함). 한계: 원본 카메라 줌도 확대로 보임",
                      blk("컷(shots.json)과 확대 판정(motion.json presence.zoom 있다/없다)이 모두 있는 영상 없음"),
                      rule="p90", as_int=True))
    G.append(num_item("motion.freeze.max_per_video", fr_rows, "count",
                      "영상별 정지 화면(프레임 반복, 앞뒤 움직임 있음) 횟수 → 영상 간 p90(value_rule=p90, 정수; 정지 판정이 "
                      "있다/없다로 측정된 영상만, 0회 포함; episode validate 의 freeze_count 와 같은 단위)",
                      blk("정지 판정(motion.json presence.freeze 있다/없다)이 측정된 영상 없음"), rule="p90", as_int=True))
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
    # ---------------------------------------------------------------- channel-level presence (tri-state)
    try:
        from .manual import read_observations
        obs, _ = read_observations(preset, include_long)
    except Exception:  # noqa: BLE001 - a broken CSV must not stop the visual aggregate
        obs = []
    mdeco: dict[str, list[dict]] = {}
    for r in obs:
        if str(r.get("key", "")).startswith("decorations."):
            mdeco.setdefault(r["video_id"], []).append(r)
    prow = visual_presence_rows(videos, mdeco)
    for k in ("zoom", "freeze", "speed_change", "flash", "crossfade", "decorations"):
        groups["visual_presence"].append(presence_item(
            f"presence.{k}", prow[k], PRESENCE_VISUAL_METHOD[k],
            blk(f"'{k}' 있다/없다가 측정된 스냅샷 영상 없음")))
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
    dmethod = "latest100 스냅샷의 영상 길이(플랫폼 메타데이터)"
    dblk = (pb["blocker"] or snapshot_blocker(preset)) if not S else ""
    # the preset stores the distribution itself (structure.duration_s.{n,p10,p50,p90}): one item per leaf
    groups["visual_structure"] += distribution_items("structure.duration_s", S, "s", dmethod, dblk, digits=2)
    # cut density / shot length (S2QA-15): per-video values from shots.json of the snapshot members
    pdur = {r["video_id"]: r["value"] for r in S}
    cs = cut_structure_rows(videos, pdur)
    cblk_s = blk("컷 분석(shots.json)이 전체 길이로 측정된 스냅샷 영상 없음"
                 + (f" — 제외 {len(cs['excluded'])}편: " + "; ".join(f"{x['video_id']}: {x['reason']}"
                                                                 for x in cs["excluded"][:5]) if cs["excluded"] else ""))
    cextra = {"basis": {"n_videos": len(cs["per_video"]), "excluded": cs["excluded"],
                        "transition_types": dict(cs["types"]), "per_video": cs["per_video"],
                        "pooled_shot_len_s": pstats(cs["pooled_shot_len"], 3),
                        "note": "pooled_shot_len_s = 모든 샷을 한데 모은 분포(참고). 제작·QA 값은 영상별 값(한 영상 = 1표본)의 분포"}}
    groups["visual_structure"] += distribution_items("structure.cuts_per_10s", cs["rate"], "cuts/10s", CUT_RATE_METHOD,
                                                     cblk_s, digits=3, extra=cextra)
    groups["visual_structure"] += distribution_items("structure.shot_len_s", cs["shot_len"], "s", SHOT_LEN_METHOD,
                                                     cblk_s, digits=3, extra=cextra)
    F = []
    for vid, d in videos.items():
        items = [c for c in (d.get("captions") or {}).get("items") or []
                 if c["role"] not in FIRST_CAPTION_EXCLUDED_ROLES]
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
             "excluded_long_form": pb["excluded_long_form"],
             "excluded_non_snapshot": pb["excluded_non_snapshot"],
             "formats_assigned": sum(1 for d in videos.values() if d["format_id"]),
             "canvas_resolution": canvas_res, "scaled_to": scaled_to, **basis_record(pb)}
    for group, items in groups.items():
        out = {"schema": SCHEMA, "group": group, "preset_id": pr.preset_id,
               "source_snapshot": snap.get("captured_at"), "source_snapshot_status": snap.get("status"),
               "generated_at": now_iso(), "generated_by": "shortkit ref aggregate", "basis": basis, "items": items}
        write_json(mdir / f"{group}.json", out)
        written[group] = {"items": len(items), "measured": sum(i["status"] == "measured" for i in items)}
    tot = sum(v["items"] for v in written.values())
    meas = sum(v["measured"] for v in written.values())
    say(f"측정 집계: 스냅샷 영상 {len(videos)}편(스냅샷 밖 제외 {len(pb['excluded_non_snapshot'])}편), 항목 {tot}개 중 측정 "
        f"{meas}개 / 못 잼 {tot - meas}개 → {paths.relp(mdir)}/visual_*.json (좌표 환산 캔버스 {canvas_res[0]}x{canvas_res[1]}, "
        f"{scaled_to['source']})")
    # manual.json holds the decoration keys, whose automatic detector output lives in the same
    # analysis files: refresh it together so it never lags behind the analysis
    from .manual import aggregate_manual
    man = aggregate_manual(preset, include_long=include_long, ids=list(videos))
    written["manual"] = {"items": man["items"], "measured": man["measured"]}
    return {"videos": len(videos), "groups": written, "excluded_non_snapshot": pb["excluded_non_snapshot"]}


_ = (ROLES, Callable, Path)
