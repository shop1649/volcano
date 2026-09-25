"""Manual observations -> measurement items for style keys no automatic analyzer measures reliably.

    presets/<name>/manual_observations.csv      (header: video_id,t,key,value,observed_by,watched,note)
    shortkit ref manual-aggregate  ->  presets/<name>/measurements/manual.json

A row is an observation made by a person who WATCHED the reference video at time ``t``:
  * ``watched`` must be yes (yes/y/true/1/예/네/o) and ``observed_by`` non-empty, otherwise the row is
    ignored (listed under ``rows_ignored`` with the reason) -- never counted, never "filled in";
  * ``video_id`` must be a member of the fixed reference snapshot (reference/latest100.json) -- older
    high-view videos are reference-only (reference/high_views_report.json) and never enter production
    measurements; long-form uploads (kind: video) are skipped unless ``--include-long``;
  * ``t`` = seconds into that video where the observation can be checked (the evidence time);
  * ``key`` must be one of ``MANUAL_KEYS``; ``value`` is parsed by the key's type:
      color  '#RRGGBB'          px     number, in the REFERENCE VIDEO's own pixels (as downloaded /
      ratio  number 0..2               analysed); scaled like every other coordinate to the MEASURED
      hz     number >= 0 (0 = no blink)      canvas when canvas.width/height are measured, else the preset
                                             canvas (``scaled_to``; same aspect ratio only), native values kept
      bool   yes/no              enum   one of the listed values

Items use the measurement format of docs/CONTRACT.md section 2: numeric -> ``{n, p10, p50, p90}``
overall and per format (value = p50), colours -> colour clusters (value = mode), categorical /
boolean -> counts (value = mode).  Unit of observation = one value per video (median / mode of that
video's rows), like ``ref aggregate``.  Evidence = the rows themselves (video_id, t, value,
observed_by, note).

Decorations additionally use the EXPERIMENTAL automatic detector
(``analysis/<id>/motion.json`` -> ``decorations``, ``shortkit.reference.motion.detect_decorations``):
per video, a watched manual row wins over the detector for the same key; evidence says which
source each value came from.  The detector has only been validated on decorations drawn by our
own renderer (synthetic mocks), so each item reports how many videos rest on it
(``sources``).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from .. import paths
from ..config import load_preset
from ..util.jsonio import now_iso, read_json, read_jsonl, write_json
from .common import ROLES, analysis_dir, color_mode, load_reference_list, load_snapshot, read_csv_rows, \
    reference_dir, say, snapshot_blocker, write_csv_rows

SCHEMA = "shortkit.measurement/1"
GROUP = "manual"
CSV_NAME = "manual_observations.csv"
MANUAL_HEADER = ["video_id", "t", "key", "value", "observed_by", "watched", "note"]
YES = {"yes", "y", "true", "1", "예", "네", "o", "ㅇ"}
NO = {"no", "n", "false", "0", "아니오", "아니요", "x"}

# key -> value type (+ allowed values for enums).  Every key must be a style leaf of preset.yaml.
MANUAL_KEYS: dict[str, dict[str, Any]] = {
    "decorations.arrow.color": {"type": "color"},
    "decorations.arrow.size_px": {"type": "px"},
    "decorations.arrow.outline_px": {"type": "px"},
    "decorations.arrow.outline_color": {"type": "color"},
    "decorations.arrow.blink_hz": {"type": "hz"},
    "decorations.arrow.head_len_ratio": {"type": "ratio"},
    "decorations.arrow.head_width_ratio": {"type": "ratio"},
    "decorations.arrow.shaft_width_ratio": {"type": "ratio"},
    "decorations.circle.color": {"type": "color"},
    "decorations.circle.stroke_px": {"type": "px"},
    "decorations.circle.blink_hz": {"type": "hz"},
    "decorations.box.color": {"type": "color"},
    "decorations.box.stroke_px": {"type": "px"},
    "decorations.box.blink_hz": {"type": "hz"},
    "text.tone.emoji": {"type": "bool"},
    "cover.source": {"type": "enum", "values": ["first_frame", "chosen_frame"]},
    "cover.text_role": {"type": "enum", "values": list(ROLES)},
}

HOWTO = {
    "decorations.arrow.color": "화살표 채움 색(#RRGGBB)",
    "decorations.arrow.size_px": "화살표 전체 길이(끝~꼬리), 레퍼런스 영상 자체 픽셀",
    "decorations.arrow.outline_px": "화살표 테두리 두께(영상 픽셀, 없으면 0)",
    "decorations.arrow.outline_color": "화살표 테두리 색",
    "decorations.arrow.blink_hz": "초당 깜빡임 횟수(깜빡이지 않으면 0)",
    "decorations.arrow.head_len_ratio": "머리 길이 / 전체 길이",
    "decorations.arrow.head_width_ratio": "머리 폭 / 전체 길이",
    "decorations.arrow.shaft_width_ratio": "몸통 폭 / 전체 길이",
    "decorations.circle.color": "원 테두리 색",
    "decorations.circle.stroke_px": "원 테두리 두께(영상 픽셀)",
    "decorations.circle.blink_hz": "초당 깜빡임 횟수(0 = 안 깜빡임)",
    "decorations.box.color": "네모 테두리 색",
    "decorations.box.stroke_px": "네모 테두리 두께(영상 픽셀)",
    "decorations.box.blink_hz": "초당 깜빡임 횟수(0 = 안 깜빡임)",
    "text.tone.emoji": "자막에 이모지를 쓰는가(yes/no) — 이모지가 보이는 시각 또는 자막 전체를 본 뒤 기록",
    "cover.source": "표지(썸네일)가 첫 프레임인가(first_frame) 따로 고른 프레임인가(chosen_frame)",
    "cover.text_role": "표지 문구가 어느 자막 역할인가(title/description/situation/speaker/dialogue/reaction)",
}

# automatic decoration detector fields -> manual keys
AUTO_FIELDS = {
    "arrow": {"color": "color", "size_px": "px", "outline_px": "px", "outline_color": "color", "blink_hz": "hz",
              "head_len_ratio": "ratio", "head_width_ratio": "ratio", "shaft_width_ratio": "ratio"},
    "circle": {"color": "color", "stroke_px": "px", "blink_hz": "hz"},
    "box": {"color": "color", "stroke_px": "px", "blink_hz": "hz"},
}


def csv_path(preset: str) -> Path:
    return paths.preset_dir(preset) / CSV_NAME


def ensure_template(preset: str) -> Path:
    """Create the header-only CSV when it does not exist (never touches an existing file)."""
    p = csv_path(preset)
    if not p.exists():
        write_csv_rows(p, MANUAL_HEADER, [])
    return p


# ----------------------------------------------------------------------------- parsing
def parse_value(key: str, raw: str) -> tuple[Any, str | None]:
    """(value, error).  Values are returned in the unit of the CSV (px not yet scaled)."""
    spec = MANUAL_KEYS[key]
    s = (raw or "").strip()
    if not s:
        return None, "값이 비어 있음"
    t = spec["type"]
    if t == "color":
        h = s.lstrip("#")
        if not re.fullmatch(r"[0-9A-Fa-f]{6}", h):
            return None, f"색은 #RRGGBB 형식이어야 함: {s!r}"
        return "#" + h.upper(), None
    if t in ("px", "ratio", "hz"):
        try:
            v = float(s.replace(",", "."))
        except ValueError:
            return None, f"숫자가 아님: {s!r}"
        if not math.isfinite(v) or v < 0:
            return None, f"0 이상의 숫자여야 함: {s!r}"
        if t == "ratio" and not (0 < v <= 2):
            return None, f"비율은 0~2 사이여야 함: {s!r}"
        return v, None
    if t == "bool":
        if s.lower() in YES:
            return True, None
        if s.lower() in NO:
            return False, None
        return None, f"yes/no 로 적어야 함: {s!r}"
    if t == "enum":
        if s not in spec["values"]:
            return None, f"허용 값 {spec['values']} 중 하나여야 함: {s!r}"
        return s, None
    return None, f"알 수 없는 형식 {t}"


def video_resolution(preset: str, vid: str) -> list[int] | None:
    """The reference video's own pixel grid: analysis files first, then its download record."""
    d = analysis_dir(preset, vid)
    for n in ("captions", "layout", "shots", "motion"):
        j = read_json(d / f"{n}.json")
        if j and j.get("resolution"):
            return [int(j["resolution"][0]), int(j["resolution"][1])]
    for r in reversed(read_jsonl(reference_dir(preset) / "downloads.jsonl")):
        if r.get("video_id") == vid and r.get("width") and r.get("height"):
            return [int(r["width"]), int(r["height"])]
    return None


def _scale_factor(res: list[int] | None, canvas: list[int]) -> float | None:
    if not res:
        return None
    W, H = res
    if abs(W / H - canvas[0] / canvas[1]) > 0.01:
        return None
    return canvas[1] / H


def read_observations(preset: str, include_long: bool = False) -> tuple[list[dict], list[dict]]:
    """(accepted rows, ignored rows with reasons).  Accepted rows carry parsed ``value`` (CSV unit)."""
    snap = load_snapshot(preset) or {}
    known: dict[str, str | None] = {}
    if snap.get("status") in ("ok", "partial"):
        for v in snap.get("videos") or []:
            if v.get("video_id"):
                known.setdefault(v["video_id"], v.get("kind"))
    outside = {v.get("video_id") for v in (load_reference_list(preset, "high_views") or {}).get("videos") or []}
    ok, bad = [], []
    for i, r in enumerate(read_csv_rows(csv_path(preset)), start=2):     # row 1 = header
        r = {k: (v or "").strip() if isinstance(v, str) else v for k, v in r.items()}
        why = None
        key = r.get("key") or ""
        if (r.get("watched") or "").lower() not in YES:
            why = "watched=yes 가 아님(영상을 본 사람의 관찰만 사용)"
        elif not r.get("observed_by"):
            why = "observed_by(관찰자) 비어 있음"
        elif key not in MANUAL_KEYS:
            why = f"수동 관찰 대상 키가 아님: {key!r} (허용: {', '.join(MANUAL_KEYS)})"
        elif r.get("video_id") not in known:
            why = ("최신 100편 스냅샷(latest100) 밖 영상(조회수 기준 이상 과거 영상 — 참고용, 제작 측정에 섞지 않음)"
                   if r.get("video_id") in outside else "고정 스냅샷(latest100)에 없는 영상")
        elif known.get(r["video_id"]) == "video" and not include_long:
            why = "긴 영상(kind=video) — --include-long 없이는 제외"
        t = None
        if why is None:
            try:
                t = float(r.get("t") or "")
                if not math.isfinite(t) or t < 0:
                    raise ValueError
            except ValueError:
                why = f"t(근거 시각, 초)가 올바르지 않음: {r.get('t')!r}"
        val = None
        if why is None:
            val, why = parse_value(key, r.get("value") or "")
        if why:
            bad.append({"row": i, "video_id": r.get("video_id"), "key": key, "reason": why})
            continue
        ok.append({"row": i, "video_id": r["video_id"], "t": t, "key": key, "value": val,
                   "observed_by": r["observed_by"], "note": r.get("note") or ""})
    return ok, bad


# ----------------------------------------------------------------------------- automatic decoration rows
def auto_decoration_rows(preset: str, ids: list[str]) -> list[dict]:
    """Rows from the experimental detector (analysis/<id>/motion.json -> decorations.items)."""
    out = []
    for vid in ids:
        mot = read_json(analysis_dir(preset, vid) / "motion.json") or {}
        dec = mot.get("decorations") or {}
        for it in dec.get("items") or []:
            fields = AUTO_FIELDS.get(it.get("kind"))
            if not fields:
                continue
            for f in fields:
                if it.get(f) is None:
                    continue
                out.append({"video_id": vid, "t": it.get("frame_t", it.get("t")),
                            "key": f"decorations.{it['kind']}.{f}", "value": it[f], "observed_by": None, "source": "auto",
                            "note": f"자동 검출 {it['kind']} {it.get('t')}~{it.get('end')}s"})
    return out


# ----------------------------------------------------------------------------- aggregation
def _num_stats(vals: list[float], digits: int = 3) -> dict:
    from ..util.stats import pstats
    st = pstats(vals, digits)
    st["value"] = st["p50"]
    return st


def _item(key: str, per_video: list[dict], blocker: str, canvas: list[int], scaled_to: dict | None = None) -> dict:
    """per_video rows: {video_id, format_id, value, t, evidence:[...], native?, native_res?}."""
    from ..util.stats import categorical

    spec = MANUAL_KEYS[key]
    t = spec["type"]
    it: dict[str, Any] = {"key": key, "unit": {"px": "px", "ratio": "ratio", "hz": "Hz", "color": "rgb_hex"}.get(t),
                          "resolution": canvas if t == "px" else None, "method": _method(key),
                          "measured_at": now_iso(), "howto": HOWTO.get(key)}
    if t == "px" and scaled_to:
        it["scaled_to"] = scaled_to
    vals = [r for r in per_video if r["value"] is not None]
    if not vals:
        empty = ({"n": 0, "p10": None, "p50": None, "p90": None} if t in ("px", "ratio", "hz") else
                 {"n": 0, "clusters": [], "mode": None} if t == "color" else {"n": 0, "counts": {}, "mode": None})
        it.update({"status": "unmeasured", "value": None, "value_rule": _rule(t), "overall": empty,
                   "by_format": {}, "evidence": [], "blocker": blocker})
        return it
    fmts = sorted({r["format_id"] for r in vals if r.get("format_id")})
    if t in ("px", "ratio", "hz"):
        digits = 1 if t == "px" else 3
        ov = _num_stats([r["value"] for r in vals], digits)
        byf = {f: _num_stats([r["value"] for r in vals if r.get("format_id") == f], digits) for f in fmts}
    elif t == "color":
        ov = color_mode([r["value"] for r in vals])
        ov["value"] = ov["mode"]
        byf = {}
        for f in fmts:
            c = color_mode([r["value"] for r in vals if r.get("format_id") == f])
            c["value"] = c["mode"]
            byf[f] = c
    else:
        ov = categorical([r["value"] for r in vals])
        ov["value"] = ov["mode"]
        byf = {}
        for f in fmts:
            c = categorical([r["value"] for r in vals if r.get("format_id") == f])
            c["value"] = c["mode"]
            byf[f] = c
    value = ov.pop("value")
    ev = [e for r in vals for e in r["evidence"]]
    it.update({"status": "measured", "value": value, "value_rule": _rule(t), "overall": ov, "by_format": byf,
               "evidence": ev[:20], "evidence_total": len(ev), "blocker": None,
               "sources": dict(Counter(r["source"] for r in vals))})
    if t == "px":
        from .aggregate import native_stats
        nat = native_stats(vals, "p50", 1)
        if nat:
            it["native"] = nat
    return it


def _rule(t: str) -> str:
    return {"px": "p50", "ratio": "p50", "hz": "p50",
            "color": "mode of color clusters (RGB distance <= 28)"}.get(t, "mode")


def _method(key: str) -> str:
    base = ("manual_observations.csv 의 관찰 행(영상을 본 사람: watched=yes + observed_by, 스냅샷 영상, 근거 시각 t) → "
            "영상별 중앙값/최빈값 → 영상 간 분포(수치 p50, 색·범주 최빈값)")
    if MANUAL_KEYS[key]["type"] == "px":
        base += "; px 는 레퍼런스 영상 자체 픽셀로 적고 캔버스 해상도로 환산(종횡비가 같은 영상만, resolution 참고)"
    if key.startswith("decorations."):
        base += ("; 같은 영상에 사람 관찰이 없으면 자동 장식 검출값(analysis/<id>/motion.json decorations — 우리 렌더러가 "
                 "그린 합성 모의 영상으로만 검증된 실험 기능)을 사용, 근거에 source 표시")
    return base


def _target_canvas(pr, preset: str) -> tuple[list[int], dict]:
    """Same target canvas as `ref aggregate`: measured canvas.width/height (visual_canvas.json) else the preset."""
    from .aggregate import target_canvas

    vc = read_json(paths.preset_dir(preset) / "measurements" / "visual_canvas.json") or {}
    items = {i.get("key"): i for i in vc.get("items") or [] if isinstance(i, dict)}
    return target_canvas(pr, items)


def aggregate_manual(preset: str, include_long: bool = False, ids: list[str] | None = None) -> dict:
    pr = load_preset(preset)
    canvas, scaled_to = _target_canvas(pr, preset)
    from .classify import load_membership
    from .common import basis_record, production_basis

    membership = load_membership(preset)
    snap = load_snapshot(preset) or {}
    snap_ok = snap.get("status") in ("ok", "partial")
    ensure_template(preset)
    obs, ignored = read_observations(preset, include_long)
    pb = production_basis(preset, ids, include_long=include_long)
    ids = pb["ids"]
    auto = auto_decoration_rows(preset, ids) if snap_ok else []
    res_cache: dict[str, list[int] | None] = {}

    def factor(vid: str) -> float | None:
        if vid not in res_cache:
            res_cache[vid] = video_resolution(preset, vid)
        return _scale_factor(res_cache[vid], canvas)

    # (video, key) -> rows; manual rows win over automatic rows for the same video and key
    by: dict[tuple[str, str], list[dict]] = {}
    for r in obs:
        by.setdefault((r["video_id"], r["key"]), []).append({**r, "source": "manual"})
    for r in auto:
        if (r["video_id"], r["key"]) not in by or all(x["source"] == "auto" for x in by[(r["video_id"], r["key"])]):
            by.setdefault((r["video_id"], r["key"]), []).append(r)
    per_key: dict[str, list[dict]] = {k: [] for k in MANUAL_KEYS}
    unscaled: list[dict] = []
    for (vid, key), rows in sorted(by.items()):
        t = MANUAL_KEYS[key]["type"]
        vals = [r["value"] for r in rows]
        native = None
        if t == "px":
            f = factor(vid)
            if f is None:
                unscaled.append({"video_id": vid, "key": key, "reason": "영상 해상도를 모르거나 캔버스와 종횡비가 다름"})
                continue
            native = round(float(np.median([float(v) for v in vals])), 3)
            vals = [float(v) * f for v in vals]
        if t in ("px", "ratio", "hz"):
            v = round(float(np.median(vals)), 3)
        elif t == "color":
            v = color_mode(vals)["mode"]
        else:
            c = Counter(vals)
            top = max(c.values())
            v = next(x for x in vals if c[x] == top)
        ev = [{"video_id": vid, "t": r["t"], "value": r["value"], "frame": None, "source": r["source"],
               "observed_by": r.get("observed_by"), "note": r.get("note") or None,
               **({"csv_row": r["row"]} if r.get("row") else {})} for r in rows]
        row = {"video_id": vid, "format_id": membership.get(vid), "value": v, "t": rows[0]["t"],
               "evidence": ev, "source": rows[0]["source"]}
        if native is not None and res_cache.get(vid):
            row.update(native=native, native_res=f"{res_cache[vid][0]}x{res_cache[vid][1]}")
        per_key[key].append(row)
    items = []
    for key in MANUAL_KEYS:
        if not snap_ok:
            blk = snapshot_blocker(preset) + " — 수동 관찰도 스냅샷 영상에만 적을 수 있음"
        elif key.startswith("decorations."):
            blk = (f"{CSV_NAME} 에 이 키의 관찰 행(watched=yes, observed_by) 없음, 자동 장식 검출에서도 "
                   f"'{key.split('.')[1]}' 가 검출된 분석 영상 없음")
        else:
            blk = f"{CSV_NAME} 에 이 키의 관찰 행(watched=yes, observed_by) 없음 — 영상을 본 사람이 채워야 함"
        items.append(_item(key, per_key[key], blk, canvas, scaled_to))
    out = {"schema": SCHEMA, "group": GROUP, "preset_id": pr.preset_id, "source_snapshot": snap.get("captured_at"),
           "source_snapshot_status": snap.get("status"), "generated_at": now_iso(),
           "generated_by": "shortkit ref manual-aggregate",
           "observations_file": paths.relp(csv_path(preset)), "csv_header": MANUAL_HEADER,
           "rows_used": len(obs), "rows_ignored": ignored, "px_rows_not_scaled": unscaled,
           "auto_decoration_rows": len(auto), "canvas_resolution": canvas, "scaled_to": scaled_to,
           "basis": basis_record(pb),
           "instructions": ("영상을 실제로 본 사람만 한 줄에 한 관찰을 적는다: video_id(스냅샷 영상), t(그 관찰을 확인할 수 있는 "
                            "초), key(아래 keys), value, observed_by(이름), watched=yes, note. px 는 레퍼런스 영상 자체 픽셀."),
           "keys": {k: {**MANUAL_KEYS[k], "howto": HOWTO.get(k)} for k in MANUAL_KEYS},
           "items": items}
    mdir = paths.preset_dir(preset) / "measurements"
    write_json(mdir / "manual.json", out)
    meas = sum(i["status"] == "measured" for i in items)
    say(f"수동 관찰 집계: 사용 {len(obs)}행, 무시 {len(ignored)}행, 자동 장식 {len(auto)}행 → 항목 {len(items)}개 중 측정 "
        f"{meas}개 / 못 잼 {len(items) - meas}개 → {paths.relp(mdir / 'manual.json')}")
    for b in ignored[:10]:
        say(f"  무시: {CSV_NAME} {b['row']}행 {b.get('video_id')} {b.get('key')}: {b['reason']}")
    return {"items": len(items), "measured": meas, "rows_used": len(obs), "rows_ignored": len(ignored),
            "auto_rows": len(auto)}
