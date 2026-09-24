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
        out.append({"video_id": r["video_id"], "t": r.get("t"), "value": r["value"], "frame": r.get("frame")})
        if len(out) >= k:
            break
    return out


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


def aggregate(preset: str, ids: list[str] | None = None) -> dict:
    pr = load_preset(preset)
    Wc, Hc = int(pr.get("canvas.width")), int(pr.get("canvas.height"))
    roles = [r for r in pr.section("text.roles").keys()]
    membership = load_membership(preset)
    snap = load_snapshot(preset) or {}
    ids = ids if ids is not None else resolve_ids(preset, set_name="analyzed")
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
        G.append(num_item(pre + "anchor.y", R.get("anchor.y", []), "px", "잉크 상자(여러 줄은 전체) 세로 중심, " + m, rb,
                          canvas_res, digits=1))
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
            addm("motion.zoom.dur_s", round(float(np.median([e["dur_s"] for e in zi])), 3), zi[0]["t"])
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
            cf = [x for x in cuts if x["type"] == "crossfade"]
            if cf:
                addm("motion.transitions.crossfade.dur_s", round(float(np.median([x["dur"] for x in cf])), 3), cf[0]["t"])
    G = groups["visual_motion"]
    pz = {"presence": {k: dict(v) for k, v in pres.items()}}
    G.append(num_item("motion.zoom.scale_to", M.get("motion.zoom.scale_to", []), "ratio",
                      "영상별 확대(zoom_in) 배율 중앙값(ORB 유사변환 누적; 원본 카메라 줌과 구분 못 함)",
                      blk("확대가 검출된 영상 없음"), digits=4, extra=pz))
    G.append(num_item("motion.zoom.dur_s", M.get("motion.zoom.dur_s", []), "s", "영상별 확대 길이 중앙값",
                      blk("확대가 검출된 영상 없음"), digits=3))
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
    G.append(num_item("motion.transitions.crossfade.dur_s", M.get("motion.transitions.crossfade.dur_s", []), "s",
                      "섞임 구간(블렌드 가중치 0→1) 길이 중앙값", blk("크로스페이드가 검출된 영상 없음"), digits=3))
    # ---------------------------------------------------------------- structure
    S: list[dict] = []
    snap_ok = snap.get("status") in ("ok", "partial")
    if snap_ok:
        for v in snap.get("videos") or []:
            if v.get("duration") is not None:
                S.append({"video_id": v["video_id"], "format_id": membership.get(v["video_id"]),
                          "value": float(v["duration"]), "t": None, "frame": None})
    else:
        for vid, d in videos.items():
            dur = (d.get("shots") or {}).get("duration") or (d.get("captions") or {}).get("duration")
            if dur:
                S.append({"video_id": vid, "format_id": d["format_id"], "value": float(dur), "t": None, "frame": None})
    dur_item = num_item("structure.duration_s", S, "s",
                        "latest100 스냅샷의 영상 길이(플랫폼 메타데이터)" if snap_ok else "분석한 영상 파일의 길이",
                        snapshot_blocker(preset) if not S else "", digits=2)
    if dur_item["status"] == "measured":
        # the preset stores the whole distribution under this key
        dur_item["value"] = {k: dur_item["overall"][k] for k in ("n", "p10", "p50", "p90")}
        for fmt, st in dur_item["by_format"].items():
            st["value"] = {k: st[k] for k in ("n", "p10", "p50", "p90")}
    groups["visual_structure"].append(dur_item)
    F = []
    for vid, d in videos.items():
        items = [c for c in (d.get("captions") or {}).get("items") or [] if c["role"] not in ("title", "description")]
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
    return {"videos": len(videos), "groups": written}


_ = (ROLES, Callable, Path)
