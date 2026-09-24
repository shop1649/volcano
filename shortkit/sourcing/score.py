"""Ranking and selection of warehouse candidates.

Stage 1 -- shortlist, per platform: rank by CONFIRMED views (``views`` from platform metadata with
its check time).  Candidates whose views are unknown are listed after the ranked ones and flagged
(``views_unknown``); they are never given a guessed number.  Likes / Reddit score are never views.

Stage 2 -- final selection uses:
  recency     age of ``published_at`` at check time (label recent|old|unknown). The label depends ONLY
              on the publish date, so an old viral video is never labelled recent, however many views
              it has or however recently we first saw it.
  intensity   event intensity 1-5   \
  reversal    reversal/twist 1-5     > from a review entry by someone who WATCHED the video
  format_fit  format fit 1-5        /  (watched_by + notes required); otherwise 'unmeasured'
  quality     resolution, bitrate (bits/pixel/frame), sharpness (Laplacian variance), watermark
              presence (review value, or a persistent-corner-text OCR hint that can only say 'present').

A candidate cannot be 'selected' without a valid review.  Other unmeasured items (reference overlap,
publish date, file-based quality) block selection unless the caller explicitly accepts them with a
reason, which is written into the record and into ``selection_reason``.

Normalisation scales below are heuristics chosen for this tool (documented in each ``method``), not
measurements of the reference channel.
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Any, Iterable

from ..util.jsonio import now_iso

RECENT_DAYS_DEFAULT = 30
WEIGHTS = {"recency": 0.20, "intensity": 0.25, "reversal": 0.20, "quality": 0.15, "format_fit": 0.20}
REVIEW_ITEMS = ("intensity", "reversal", "format_fit")
REVIEW_KO = {"intensity": "사건 강도", "reversal": "반전", "format_fit": "형식 적합"}
RECENCY_KO = {"recent": "최근", "old": "오래됨", "unknown": "게시일 모름"}
# production impact of each unmeasured selection item (reported with 못 잼)
UNMEASURED_IMPACT = {
    "recency": "오래된 영상(재업로드된 옛 바이럴 포함)을 최근 소재로 잘못 고를 수 있음",
    "intensity": "사건이 약한 소재를 골라 레퍼런스만큼의 몰입을 못 만들 수 있음",
    "reversal": "반전 구조가 없는 소재를 골라 레퍼런스 전개를 재현하지 못할 수 있음",
    "format_fit": "레퍼런스 포맷(길이·구성)에 안 맞는 소재를 고를 수 있음",
    "quality": "저화질·워터마크 있는 소재를 골라 정리/복원 부담이 커지거나 화질이 떨어질 수 있음",
    "reference_overlap": "레퍼런스와 같은 녹화를 다시 쓸 위험(사용자 규칙 위반)",
}
# quality normalisation (heuristic, see module docstring)
RES_FULL_SHORT_SIDE = 1080          # short side px that scores 1.0
BPP_FULL = 0.05                     # bits per pixel per frame that scores 1.0 (~3.1 Mbps at 1080p30)
SHARP_FULL = 150.0                  # Laplacian variance (frame scaled to 480 px short side) scoring 1.0
WATERMARK_FACTOR = 0.7              # quality multiplier when a watermark/overlay is present


# ----------------------------------------------------------------------------- policy
_POLICY_CACHE: dict = {}


def policy() -> dict:
    """Selection policy: defaults, overridable by ``selection:`` in warehouse/queries.yaml."""
    out = {"recent_days": RECENT_DAYS_DEFAULT, "weights": dict(WEIGHTS), "preset": "joshuamagazine"}
    try:
        from .. import paths
        from .keywords import QUERIES, load_queries

        qp = paths.absp(QUERIES)
        key = (str(qp), qp.stat().st_mtime_ns if qp.exists() else None)
        if _POLICY_CACHE.get("key") == key:
            v = _POLICY_CACHE["val"]
            return {"recent_days": v["recent_days"], "weights": dict(v["weights"]), "preset": v["preset"]}
        sel = (load_queries() or {}).get("selection") or {}
    except Exception:
        key, sel = None, {}
    if isinstance(sel.get("recent_days"), (int, float)) and sel["recent_days"] > 0:
        out["recent_days"] = float(sel["recent_days"])
    if isinstance(sel.get("weights"), dict):
        for k, v in sel["weights"].items():
            if k in WEIGHTS and isinstance(v, (int, float)) and v >= 0:
                out["weights"][k] = float(v)
    if isinstance(sel.get("preset"), str) and sel["preset"]:
        out["preset"] = sel["preset"]
    if key is not None:
        _POLICY_CACHE.update({"key": key, "val": {"recent_days": out["recent_days"], "weights": dict(out["weights"]),
                                                  "preset": out["preset"]}})
    return out


# ----------------------------------------------------------------------------- time
def parse_time(s: Any) -> _dt.datetime | None:
    if not s or not isinstance(s, str):
        return None
    t = s.strip()
    try:
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", t):
            return _dt.datetime.fromisoformat(t).replace(tzinfo=_dt.timezone.utc)
        d = _dt.datetime.fromisoformat(t.replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=_dt.timezone.utc)
    except ValueError:
        return None


def recency(published_at: str | None, checked_at: str | None = None, days: float | None = None) -> dict:
    """Recency of a publish date at check time. Label: recent | old | unknown (never guessed)."""
    days = float(days or policy()["recent_days"])
    chk = parse_time(checked_at) or _dt.datetime.now(_dt.timezone.utc)
    pub = parse_time(published_at)
    base = {"published_at": published_at, "checked_at": chk.replace(microsecond=0).isoformat(),
            "threshold_days": days}
    if pub is None:
        return {**base, "age_days": None, "label": "unknown", "label_ko": RECENCY_KO["unknown"], "score": None,
                "method": "게시일 없음 → 최근성 못 잼(최근으로 취급하지 않음)"}
    age = (chk - pub).total_seconds() / 86400.0
    note = None
    if age < 0:
        note = "게시일이 확인 시각보다 뒤(시계/시간대 차이) → 0일로 계산"
        age = 0.0
    label = "recent" if age <= days else "old"
    score = round(max(0.0, 1.0 - age / (3.0 * days)), 3)
    return {**base, "age_days": round(age, 2), "label": label, "label_ko": RECENCY_KO[label], "score": score,
            "method": f"확인 시각 기준 게시 후 경과일; {days:g}일 이하 = 최근; 점수 = max(0, 1 - 경과일/{3 * days:g})",
            **({"note": note} if note else {})}


def recency_for(c: dict, checked_at: str | None = None, days: float | None = None) -> dict:
    """Recency of a candidate.  A known repost (reposter set / original_url elsewhere) is judged by the
    ORIGINAL's publish date (``original_published_at``, e.g. from a review); if that is unknown the label is
    'unknown' -- a re-upload of an old viral clip must not look recent because the re-upload is new."""
    if c.get("original_published_at"):
        r = recency(c["original_published_at"], checked_at, days)
        r["basis"] = "original_published_at"
        return r
    repost = bool(c.get("reposter")) or bool(c.get("original_url") and c.get("original_url") != c.get("url"))
    r = recency(c.get("published_at"), checked_at, days)
    r["basis"] = "published_at"
    if repost and r["label"] != "old":
        r.update({"label": "unknown", "label_ko": "재업로드: 원본 게시일 모름", "score": None,
                  "method": "재업로드로 보임(원작자≠업로더 또는 원본 URL 따로 있음) → 원본 게시일을 확인해야 최근성 판정 "
                            f"(재업로드 {r['age_days']}일 전; 검토 시 --original-published-at 으로 입력)",
                  "basis": "repost_without_original_date"})
    return r


# ----------------------------------------------------------------------------- stage 1: views
def views_confirmed(c: dict) -> bool:
    v = c.get("views")
    return (isinstance(v, int) and not isinstance(v, bool) and v >= 0
            and c.get("views_source") == "platform_metadata" and bool(c.get("views_checked_at")))


def rank_by_views(cands: Iterable[dict], platform: str | None = None) -> list[dict]:
    """Per-platform ranking rows ``{platform, rank, id, views, views_checked_at, flags, candidate}``.

    Confirmed views first (desc; ties -> more recent check first), then unknown views (rank None,
    flag 'views_unknown'), ordered by first_seen_at. Ranks restart per platform because view counts
    of different platforms are not comparable."""
    rows: list[dict] = []
    by_pf: dict[str, list[dict]] = {}
    for c in cands:
        if platform and c.get("platform") != platform:
            continue
        by_pf.setdefault(c.get("platform") or "?", []).append(c)
    for pf in sorted(by_pf):
        items = by_pf[pf]
        conf = [c for c in items if views_confirmed(c)]
        unk = [c for c in items if not views_confirmed(c)]
        conf.sort(key=lambda c: (-c["views"], _neg_ts(c.get("views_checked_at")), c.get("id", "")))
        unk.sort(key=lambda c: (c.get("first_seen_at") or "", c.get("id", "")))
        for i, c in enumerate(conf, 1):
            rows.append({"platform": pf, "rank": i, "id": c.get("id"), "views": c["views"],
                         "views_checked_at": c.get("views_checked_at"), "flags": [], "candidate": c})
        for c in unk:
            flags = ["views_unknown"]
            if c.get("reddit_score") is not None:
                flags.append("reddit_score_is_not_views")
            rows.append({"platform": pf, "rank": None, "id": c.get("id"), "views": None,
                         "views_checked_at": None, "flags": flags, "candidate": c})
    return rows


def _neg_ts(s: str | None) -> float:
    t = parse_time(s)
    return -t.timestamp() if t else 0.0


# ----------------------------------------------------------------------------- reviews
def validate_review(r: dict) -> list[str]:
    """Problems that make a review entry unusable (Korean)."""
    probs = []
    if not str(r.get("watched_by") or "").strip():
        probs.append("watched_by(직접 본 사람) 없음")
    if not str(r.get("notes") or "").strip():
        probs.append("notes(본 내용 메모) 없음")
    for k in REVIEW_ITEMS:
        v = r.get(k)
        if not (isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= 5):
            probs.append(f"{k}({REVIEW_KO[k]}) 1-5 정수 아님")
    if r.get("watermark") not in (None, "present", "absent"):
        probs.append("watermark 는 present/absent 만 가능")
    return probs


def review_of(c: dict) -> dict | None:
    """Latest valid review entry, or None."""
    for r in reversed(c.get("reviews") or []):
        if isinstance(r, dict) and not validate_review(r):
            return r
    return None


def known_format_ids(preset_name: str = "joshuamagazine") -> tuple[set[str] | None, str]:
    """Format ids from the preset's formats table (path read through the tracked preset API).
    Returns (ids, note); ids is None when the table is unmeasured/missing (format id cannot be checked)."""
    try:
        from ..config import load_preset
        from ..util.jsonio import read_yaml
        from .. import paths

        pr = load_preset(preset_name)
        rel = pr.get("structure.formats_file")
        d = read_yaml(paths.absp(rel), {}) or {}
    except Exception as e:  # noqa: BLE001
        return None, f"포맷 표를 읽지 못함: {type(e).__name__}: {e}"
    ids = {str(r.get("format_id") or r.get("id")) for r in (d.get("table") or []) if isinstance(r, dict)
           and (r.get("format_id") or r.get("id"))}
    if d.get("status") != "measured" or not ids:
        return None, f"{rel} 미측정(status={d.get('status')}) → 포맷 id 검증 못 함"
    return ids, f"{rel} ({len(ids)}개 포맷)"


def format_facts(c: dict, preset_name: str | None = None) -> dict:
    """Measurable format facts that inform (not replace) the reviewer's format_fit score: orientation,
    source duration vs the reference's output-duration distribution (``structure.duration_s``, read through
    the tracked preset API).  A source shorter than the reference's p10 length cannot fill the format
    without padding/repeating, which the production rules forbid."""
    dur = c.get("duration")
    out: dict[str, Any] = {"orientation": orientation(c.get("width"), c.get("height")), "duration": dur,
                           "reference_duration": None, "duration_enough": None}
    name = preset_name or policy().get("preset") or "joshuamagazine"
    try:
        from ..config import load_preset

        st = load_preset(name).get("structure.duration_s")
        st = dict(st) if st else {}
    except Exception as e:  # noqa: BLE001
        out["note"] = f"프리셋 '{name}' 을 읽지 못함: {type(e).__name__}"
        return out
    if not st.get("n") or st.get("p10") is None:
        out["note"] = "레퍼런스 영상 길이 분포 미측정(structure.duration_s n=0) → 길이 적합 못 잼"
        return out
    out["reference_duration"] = {k: st.get(k) for k in ("n", "p10", "p50", "p90")}
    if isinstance(dur, (int, float)):
        out["duration_enough"] = bool(dur >= float(st["p10"]))
        out["note"] = (f"소스 {dur:.1f}s vs 레퍼런스 p10 {st['p10']}s"
                       + ("" if out["duration_enough"] else " → 소스가 짧음(늘리거나 반복해서 채우면 안 됨)"))
    else:
        out["note"] = "소스 길이 모름 → 길이 적합 못 잼"
    return out


# ----------------------------------------------------------------------------- quality
def orientation(w: Any, h: Any) -> str | None:
    if not isinstance(w, (int, float)) or not isinstance(h, (int, float)) or not w or not h:
        return None
    r = h / w
    return "vertical" if r > 1.1 else "horizontal" if r < 0.9 else "square"


def measure_quality(path: str | Path, n_frames: int = 8, ocr: bool = True) -> dict:
    """Measure a downloaded file: resolution, bitrate, bits/pixel/frame, sharpness, watermark hint."""
    import cv2
    import numpy as np

    from ..util.media import iter_frames, probe

    info = probe(path)
    out: dict[str, Any] = {"measured_at": now_iso(), "width": info.width, "height": info.height,
                           "fps": round(info.fps, 3) if info.fps else None, "duration": round(info.duration, 3),
                           "bitrate_bps": None, "bpp": None, "sharpness_lapvar_p50": None,
                           "vcodec": info.vcodec, "has_audio": info.has_audio}
    vs = next((s for s in info.raw.get("streams", []) if s.get("codec_type") == "video"), {})
    br = vs.get("bit_rate") or (info.bit_rate if info.bit_rate else None)
    if br:
        out["bitrate_bps"] = int(br)
        out["bitrate_basis"] = "video stream bit_rate" if vs.get("bit_rate") else "container bit_rate"
    if out["bitrate_bps"] and info.width and info.height and info.fps:
        out["bpp"] = round(out["bitrate_bps"] / (info.width * info.height * info.fps), 4)
    if info.width and info.height and info.duration > 0:
        short = min(info.width, info.height)
        scale_w = int(round(info.width * 480 / short / 2) * 2)
        fps = max(0.05, min(4.0, n_frames / max(info.duration, 0.1)))
        vals = []
        for _, fr in iter_frames(path, fps=fps, width=scale_w, gray=True):
            vals.append(float(cv2.Laplacian(fr, cv2.CV_64F).var()))
            if len(vals) >= n_frames:
                break
        if vals:
            out["sharpness_lapvar_p50"] = round(float(np.median(vals)), 2)
            out["sharpness_method"] = f"Laplacian 분산 중앙값, 짧은 변 480px 로 축소한 프레임 {len(vals)}장"
    out["watermark_hint"] = watermark_hint(path, info) if ocr else {
        "status": "unmeasured", "method": "OCR 생략", "texts": []}
    return out


def watermark_hint(path: str | Path, info=None, n: int = 4) -> dict:
    """Persistent text in the frame corners (typical repost watermark '@account').

    Can only say 'present' (same text -- first 6 letters/digits, OCR noise tolerated -- in the same
    corner on >= 3 of 4 frames).  Otherwise the status stays 'unmeasured': a picture logo without
    text is invisible to this method, and static scene text (signs) can cause a false 'present', so a
    reviewer's watermark field always overrides this hint."""
    import os

    method = "모서리 4곳 OCR(tesseract eng, psm 11), 4장 중 3장 이상 같은 글자(앞 6자) = 워터마크 있음(힌트)"
    os.environ.setdefault("OMP_THREAD_LIMIT", "1")   # tesseract's OpenMP threads thrash on shared CPUs
    try:
        import pytesseract

        from ..util.media import probe, read_frames

        info = info or probe(path)
        if not info.duration or not info.width:
            return {"status": "unmeasured", "method": method, "texts": [], "note": "영상 스트림 없음"}
        times = [info.duration * (i + 1) / (n + 1) for i in range(n)]
        width = min(info.width, 1280)
        frames = read_frames(path, times, width=width)
    except Exception as e:  # noqa: BLE001 - OCR is an optional hint
        return {"status": "unmeasured", "method": method, "texts": [], "note": f"OCR 불가: {type(e).__name__}: {e}"}
    corners: dict[str, dict[str, list[str]]] = {}
    for fr in frames:
        h, w = fr.shape[:2]
        cw, ch = int(w * 0.35), int(h * 0.14)
        boxes = {"top_left": (0, 0), "top_right": (w - cw, 0), "bottom_left": (0, h - ch),
                 "bottom_right": (w - cw, h - ch)}
        for name, (x, y) in boxes.items():
            crop = fr[y:y + ch, x:x + cw]
            try:
                d = pytesseract.image_to_data(crop, lang="eng", config="--psm 11",
                                              output_type=pytesseract.Output.DICT)
            except Exception as e:  # noqa: BLE001
                return {"status": "unmeasured", "method": method, "texts": [], "note": f"OCR 실패: {e}"}
            seen: dict[str, str] = {}
            for txt in d.get("text", []):
                tok = re.sub(r"[^0-9a-z]", "", str(txt).lower())
                if len(tok) >= 5:
                    seen.setdefault(tok[:6], str(txt).strip())
            for key, raw in seen.items():
                corners.setdefault(name, {}).setdefault(key, []).append(raw)
    need = max(2, int(round(len(frames) * 0.75)))
    hits = [{"corner": c, "text": v[0], "frames": len(v)} for c, toks in corners.items()
            for _, v in toks.items() if len(v) >= need]
    if hits:
        return {"status": "present", "method": method, "texts": hits}
    return {"status": "unmeasured", "method": method, "texts": [],
            "note": "모서리에 반복되는 글자 없음 — 그림 로고는 이 방법으로 못 잼(검토자가 확인)"}


def quality_score(c: dict) -> dict:
    """Quality from the file measurement (``c['quality']``) or, failing that, platform metadata."""
    q = c.get("quality") or {}
    basis = "file" if q.get("measured_at") else "metadata"
    w = q.get("width") or c.get("width")
    h = q.get("height") or c.get("height")
    comp: dict[str, Any] = {}
    unmeasured = []
    if w and h:
        comp["resolution"] = round(min(1.0, min(w, h) / RES_FULL_SHORT_SIDE), 3)
    else:
        unmeasured.append("resolution")
    if q.get("bpp") is not None:
        comp["bitrate"] = round(min(1.0, q["bpp"] / BPP_FULL), 3)
    else:
        unmeasured.append("bitrate")
    if q.get("sharpness_lapvar_p50") is not None:
        comp["sharpness"] = round(min(1.0, q["sharpness_lapvar_p50"] / SHARP_FULL), 3)
    else:
        unmeasured.append("sharpness")
    rv = review_of(c)
    wm, wm_src = None, None
    if rv and rv.get("watermark") in ("present", "absent"):
        wm, wm_src = rv["watermark"], f"검토({rv.get('watched_by')})"
    elif (q.get("watermark_hint") or {}).get("status") == "present":
        wm, wm_src = "present", "모서리 OCR"
    if wm is None:
        unmeasured.append("watermark")
    comp["watermark"] = wm or "unmeasured"
    nums = [comp[k] for k in ("resolution", "bitrate", "sharpness") if k in comp]
    score = None
    if nums and not {"resolution", "bitrate", "sharpness"} & set(unmeasured):
        score = sum(nums) / len(nums)
        if wm == "present":
            score *= WATERMARK_FACTOR
        score = round(score, 3)
    return {"score": score, "basis": basis, "components": comp, "watermark_source": wm_src,
            "unmeasured": unmeasured,
            "method": (f"평균(해상도 짧은변/{RES_FULL_SHORT_SIDE}, bpp/{BPP_FULL}, 선명도/{SHARP_FULL:g}) "
                       f"× 워터마크 있으면 {WATERMARK_FACTOR}; 파일 측정값이 모두 있어야 점수 산출")}


# ----------------------------------------------------------------------------- scores
def compute_scores(c: dict, checked_at: str | None = None) -> dict:
    pol = policy()
    rec = recency_for(c, checked_at, pol["recent_days"])
    rv = review_of(c)
    q = quality_score(c)
    s: dict[str, Any] = {
        "recency": rec["score"], "recency_label": rec["label"], "age_days": rec["age_days"],
        "recency_basis": rec.get("basis"), "recency_note": rec["method"] if rec["label"] == "unknown" else None,
        "intensity": rv.get("intensity") if rv else None,
        "reversal": rv.get("reversal") if rv else None,
        "format_fit": rv.get("format_fit") if rv else None,
        "quality": q["score"],
        "total": None,
        "checked_at": rec["checked_at"],
        "recency_threshold_days": rec["threshold_days"],
        "review_by": rv.get("watched_by") if rv else None,
        "quality_detail": q,
        "format_facts": format_facts(c, pol["preset"]),
        "weights": pol["weights"],
    }
    status = {"recency": "measured" if rec["score"] is not None else "unmeasured",
              "quality": "measured" if q["score"] is not None else "unmeasured"}
    for k in REVIEW_ITEMS:
        status[k] = "measured" if rv else "unmeasured"
    s["status"] = status
    s["unmeasured"] = sorted(k for k, v in status.items() if v == "unmeasured")
    if not s["unmeasured"]:
        wsum = sum(pol["weights"].values()) or 1.0
        norm = {"recency": s["recency"], "quality": s["quality"],
                **{k: (s[k] - 1) / 4.0 for k in REVIEW_ITEMS}}
        s["total"] = round(sum(pol["weights"][k] * norm[k] for k in WEIGHTS) / wsum, 4)
    return s


def selection_blockers(c: dict, scores: dict | None = None) -> tuple[list[str], list[dict]]:
    """(hard blockers, soft blockers). Hard ones can never be overridden. Soft ones are unmeasured
    items that may be accepted explicitly with a reason ({key, text})."""
    scores = scores or compute_scores(c)
    hard: list[str] = []
    soft: list[dict] = []
    st = c.get("status")
    if st in ("excluded", "rejected", "used"):
        hard.append(f"상태가 '{st}' 라서 선택할 수 없음")
    ov = c.get("reference_overlap") or {}
    if ov.get("excluded") is True:
        hard.append(f"레퍼런스와 같은 녹화로 판정됨(제외 목록 {ov.get('matched_video_id')}, {ov.get('method')})")
    if review_of(c) is None:
        probs = [p for r in (c.get("reviews") or []) for p in validate_review(r)]
        why = ("검토 기록 없음" if not c.get("reviews") else "검토 기록 불완전: " + ", ".join(sorted(set(probs))))
        hard.append("사건 강도·반전·형식 적합 = 못 잼: 영상을 직접 본 사람의 검토(watched_by, notes, 1-5 점수) 필요 "
                    f"({why}) — 영향: {UNMEASURED_IMPACT['intensity']}")
    if ov.get("excluded") is None:
        soft.append({"key": "reference_overlap", "text": "레퍼런스 중복(같은 녹화) 여부 못 잼: "
                     + (ov.get("note") or "아직 검사 안 함"), "impact": UNMEASURED_IMPACT["reference_overlap"]})
    if scores["recency"] is None:
        soft.append({"key": "recency", "text": "최근성 못 잼: " + (scores.get("recency_note") or "게시일 모름"),
                     "impact": UNMEASURED_IMPACT["recency"]})
    if scores["quality"] is None:
        miss = ", ".join(scores["quality_detail"]["unmeasured"])
        soft.append({"key": "quality", "text": f"화질 못 잼({miss}) — 다운로드 후 측정 필요",
                     "impact": UNMEASURED_IMPACT["quality"]})
    return hard, soft


def _fmt_int(v: Any) -> str:
    return f"{v:,}" if isinstance(v, int) else "?"


def selection_reason(c: dict, scores: dict, accepted: list[dict] | None = None) -> str:
    """Korean one-paragraph reason built only from stored fields."""
    parts = []
    if views_confirmed(c):
        parts.append(f"조회수 {_fmt_int(c['views'])}회({(c.get('views_checked_at') or '')[:10]} 확인, "
                     f"{c.get('platform')} 메타데이터)")
    else:
        extra = f", Reddit 점수 {c['reddit_score']}(조회수 아님)" if c.get("reddit_score") is not None else ""
        parts.append(f"조회수 확인 불가({c.get('views_source') or 'unavailable'}{extra})")
    if c.get("likes") is not None:
        parts.append(f"좋아요 {_fmt_int(c['likes'])}(조회수와 별개)")
    if scores.get("recency_label") in ("recent", "old"):
        what = "원본 게시" if scores.get("recency_basis") == "original_published_at" else "게시"
        parts.append(f"{what} {scores['age_days']:.0f}일 전({RECENCY_KO[scores['recency_label']]}, "
                     f"기준 {scores['recency_threshold_days']:g}일, {scores['checked_at'][:10]} 확인)")
    elif scores.get("recency_basis") == "repost_without_original_date":
        parts.append("재업로드로 보이며 원본 게시일 모름(최근성 못 잼)")
    else:
        parts.append("게시일 모름(최근성 못 잼)")
    ff = scores.get("format_facts") or {}
    if ff:
        o = {"vertical": "세로", "horizontal": "가로", "square": "정사각"}.get(ff.get("orientation") or "", "방향 모름")
        parts.append(f"형식 사실: {o}, " + (ff.get("note") or ""))
    rv = review_of(c)
    if rv:
        parts.append(f"사건 강도 {rv['intensity']}/5 · 반전 {rv['reversal']}/5 · 형식 적합 {rv['format_fit']}/5 "
                     f"(검토: {rv['watched_by']}, {str(rv.get('watched_at') or '')[:10]}, 메모: {rv['notes']})")
    qd = scores.get("quality_detail") or {}
    q = c.get("quality") or {}
    w, h = q.get("width") or c.get("width"), q.get("height") or c.get("height")
    qtxt = f"화질 {w}x{h}" if w and h else "화질 해상도 모름"
    if q.get("bitrate_bps"):
        br = q["bitrate_bps"]
        qtxt += f", {br / 1e6:.1f}Mbps" if br >= 1e6 else f", {br / 1e3:.0f}kbps"
    if q.get("sharpness_lapvar_p50") is not None:
        qtxt += f", 선명도 {q['sharpness_lapvar_p50']:.0f}"
    wm = (qd.get("components") or {}).get("watermark")
    qtxt += {"present": ", 워터마크 있음(정리 필요)", "absent": ", 워터마크 없음"}.get(wm, ", 워터마크 못 잼")
    qtxt += f" → 점수 {scores['quality']}" if scores.get("quality") is not None else " → 점수 못 잼"
    parts.append(qtxt)
    ov = c.get("reference_overlap") or {}
    if ov.get("excluded") is False:
        d = ov.get("distance")
        nref = f"등록 지문 {ov['n_refs']}편 기준, " if ov.get("n_refs") is not None else ""
        parts.append(f"레퍼런스와 다른 녹화({nref}{ov.get('method')}"
                     + (f", 최소 거리 {d}" if d is not None else "") + ")")
    elif ov.get("excluded") is None:
        parts.append("레퍼런스 중복 여부 못 잼")
    if scores.get("total") is not None:
        parts.append(f"종합 {scores['total']:.3f}")
    else:
        parts.append("종합 점수 못 잼(" + ", ".join(scores.get("unmeasured") or []) + ")")
    if accepted:
        parts.append("못 잼 항목을 알고 선택: " + "; ".join(
            f"{a['key']} — 사유: {a['reason']} (영향: {a.get('impact') or UNMEASURED_IMPACT.get(a['key'], '?')})"
            for a in accepted))
    if c.get("original_author") and c.get("reposter"):
        parts.append(f"원작자 {c['original_author']} / 재업로더 {c['reposter']}")
    return " · ".join(parts)


def rank_for_selection(cands: Iterable[dict]) -> list[tuple[dict, dict]]:
    """Reviewed, not excluded/rejected candidates ordered by total (unmeasured totals last)."""
    rows = []
    for c in cands:
        if c.get("status") in ("excluded", "rejected"):
            continue
        if review_of(c) is None:
            continue
        s = compute_scores(c)
        rows.append((c, s))
    rows.sort(key=lambda cs: (cs[1]["total"] is None, -(cs[1]["total"] or 0.0), cs[0].get("id", "")))
    return rows
