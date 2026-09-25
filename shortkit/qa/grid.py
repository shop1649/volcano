"""Same-absolute-time comparison with ONE reference video (the format's representative, formats.yaml).

The user's rule (docs/REQUEST.md 10): the reference and our episode are compared on a 1-second grid at the SAME
absolute times, with a caption strip and under it a 0.5-second SFX strip, and the table says 같다/다르다/못 잼.  The
compare sheet (``sheet.make_sheets``) draws that grid; this module turns the same grid into QA rows so the
comparison is judged, not only drawn:

    ref_grid.captions  per 1 s cell [t, t+1): the caption roles on screen (reference captions.json vs the output's
                       measured onset/offset of every caption)
    ref_grid.cuts      per 1 s cell: visible cuts / flashes / crossfades (reference shots.json vs the cuts measured
                       in the output: planned boundaries seen in the MP4 + unplanned ones)
    ref_grid.sfx       per 0.5 s cell: edit-SFX types (reference audio/sfx_events.json class edit_sfx, and
                       intentional silences) vs the SFX detected in the output mix and the BGM silences measured in it
    ref_grid.sheet     the sheet itself (reference frames + both strips) was made

A cell is ``same`` when both sides agree, ``different`` when they do not, ``unmeasured`` when either side was not
measured there (reference SFX in ``unmeasured_coverage``, a caption whose onset/offset the output probe could not
measure ...).  A row is ``same`` only when every compared cell is ``same``.  Cells past the end of the shorter video
are listed, not compared (length is judged by structure.duration).  In production these rows are required (a
missing reference is 못 잼 and fails the gate: rule R1 / G2).
"""
from __future__ import annotations

import math

REF_ROLE_SKIP = ("identity_mark",)          # the reference channel's own mark: never reproduced, never compared
SILENCE = "silence"


def _cells(n: int, step: float) -> list[tuple[float, float]]:
    return [(round(k * step, 3), round((k + 1) * step, 3)) for k in range(n)]


def _span_cells(dur_ref: float, dur_ours: float, step: float) -> tuple[int, int]:
    """(cells compared, cells past the shorter video)."""
    n_c = int(math.floor(min(dur_ref, dur_ours) / step + 1e-6))
    n_all = int(math.ceil(max(dur_ref, dur_ours) / step - 1e-6))
    return n_c, max(0, n_all - n_c)


def caption_cells(ref_items: list[dict], ours: list[dict], dur_ref: float, dur_ours: float) -> dict:
    """ref_items: {start, end, role}; ours: {start, end, role, measured} (measured=False: timing not measured)."""
    n, extra = _span_cells(dur_ref, dur_ours, 1.0)
    out = []
    for a, b in _cells(n, 1.0):
        rr = sorted({str(i.get("role") or "unknown") for i in ref_items
                     if float(i["start"]) < b and float(i["end"]) > a and i.get("role") not in REF_ROLE_SKIP})
        oo = [c for c in ours if c["start"] < b and c["end"] > a]
        orl = sorted({c["role"] for c in oo})
        blind = [c["id"] for c in ours if not c.get("measured") and c["plan_start"] < b + 0.5 and c["plan_end"] > a - 0.5]
        if blind:
            st = "unmeasured"
        elif "unknown" in rr:
            st = "same" if bool(rr) == bool(orl) else "different"
        else:
            st = "same" if rr == orl else "different"
        cell = {"t": a, "reference": rr, "ours": orl, "status": st}
        if blind:
            cell["not_measured"] = blind
        if "unknown" in rr:
            cell["note"] = "레퍼런스 역할 미분류(unknown): 자막 유무만 비교"
        out.append(cell)
    return {"cells": out, "past_shorter_video": extra}


def cut_cells(ref_cuts: list[dict], ours: list[dict], dur_ref: float, dur_ours: float) -> dict:
    """ref_cuts / ours: {t, type in cut|flash|crossfade}."""
    n, extra = _span_cells(dur_ref, dur_ours, 1.0)
    out = []
    for a, b in _cells(n, 1.0):
        rr = sorted(str(c.get("type") or "cut") for c in ref_cuts if a <= float(c["t"]) < b)
        oo = sorted(str(c.get("type") or "cut") for c in ours if a <= float(c["t"]) < b)
        out.append({"t": a, "reference": rr, "ours": oo, "status": "same" if rr == oo else "different"})
    return {"cells": out, "past_shorter_video": extra}


def sfx_cells(ref_events: list[dict], ref_blind: list, ours: list[dict], dur_ref: float, dur_ours: float) -> dict:
    """ref_events / ours: {t, type}; ref_blind: [[a, b], ...] where the reference SFX could not be measured."""
    n, extra = _span_cells(dur_ref, dur_ours, 0.5)
    out = []
    for a, b in _cells(n, 0.5):
        rr = sorted(str(e["type"]) for e in ref_events if a <= float(e["t"]) < b)
        mine = [e for e in ours if a <= float(e["t"]) < b]
        oo = sorted(str(e["type"]) for e in mine)
        blind = any(float(x) < b and float(y) > a for x, y in ref_blind or [])
        ours_blind = any(e.get("type") is None for e in mine)
        st = "unmeasured" if (blind or ours_blind) else ("same" if rr == oo else "different")
        out.append({"t": a, "reference": rr, "ours": oo, "status": st, **({"reference_not_measured": True} if blind else {}),
                    **({"ours_type_not_measured": True} if ours_blind else {})})
    return {"cells": out, "past_shorter_video": extra}


def _status(cells: list[dict]) -> str:
    if not cells:
        return "unmeasured"
    if any(c["status"] == "different" for c in cells):
        return "different"
    if any(c["status"] == "unmeasured" for c in cells):
        return "unmeasured"
    return "same"


def _summary(res: dict) -> dict:
    cells = res["cells"]
    diff = [c for c in cells if c["status"] == "different"]
    return {"cells": len(cells), "same": sum(1 for c in cells if c["status"] == "same"), "different": len(diff),
            "unmeasured": sum(1 for c in cells if c["status"] == "unmeasured"),
            "past_shorter_video": res["past_shorter_video"], "different_cells": diff[:40]}


def reference_duration(ctx) -> float | None:
    an = ctx.reference_analysis or {}
    for k in ("shots", "captions"):
        d = (an.get(k) or {}).get("duration")
        if d:
            return float(d)
    if ctx.reference_mp4 is not None:
        try:
            from ..util.media import probe

            return float(probe(ctx.reference_mp4).duration)
        except Exception:
            return None
    return None


def our_captions(ctx, text_probe: dict) -> list[dict]:
    meas = {c["id"]: c for c in (text_probe or {}).get("captions") or []}
    out = []
    for cap in ctx.resolved.captions:
        m = meas.get(cap.id) or {}
        on, off = m.get("onset"), m.get("offset")
        ok = bool(m.get("found")) and on is not None and off is not None
        out.append({"id": cap.id, "role": cap.role, "start": float(on) if ok else float(cap.start),
                    "end": float(off) if ok else float(cap.end), "measured": ok,
                    "plan_start": float(cap.start), "plan_end": float(cap.end)})
    return out


def our_cuts(video_probe: dict) -> list[dict] | None:
    tr = (video_probe or {}).get("transitions")
    if tr is None:
        return None
    out = []
    for bd in tr.get("boundaries") or []:
        o = bd.get("observed") or {}
        if o.get("type") in ("cut", "flash", "crossfade") and o.get("t") is not None:
            out.append({"t": float(o["t"]), "type": o["type"]})
    for x in tr.get("unexpected") or []:
        if x.get("t") is not None:
            out.append({"t": float(x["t"]), "type": x.get("type") or "cut"})
    return out


def our_sfx(audio_probe: dict) -> list[dict] | None:
    """Our SFX by CATALOG type (the fingerprint classification of each detected sound, never the plan's label): type
    None = not classified (the cell is 못 잼); checks.UNCLASSIFIED = a sound matching no catalog type."""
    from .checks import catalog_type_of

    ap = audio_probe or {}
    if ap.get("status") != "measured":
        return None
    out = [{"t": float(d["t"]), "type": catalog_type_of(d), "plan_label": d.get("type")}
           for d in (ap.get("sfx") or {}).get("detections") or []]
    for a, _b in ((ap.get("bgm") or {}).get("silent_ranges_obs") or []):
        out.append({"t": float(a), "type": SILENCE})
    return out


def rows_reference_grid(b, probes: dict) -> None:
    from .checks import CAT

    ctx = b.ctx
    mode = getattr(ctx.resolved, "mode", "test")
    req = mode == "production"
    an = ctx.reference_analysis or {}
    rid = ctx.reference_id
    rep = (ctx.reference_info or {}).get("representative") or {}
    no_ref = ("레퍼런스 영상 없음: " + (rep.get("reason") or "대표 영상 미지정")) if not rid else None
    dur_ref = reference_duration(ctx) if rid else None
    dur_ours = float(ctx.info.duration)
    ref_note = (f"레퍼런스 {rid}" + ("(포맷 대표 영상)" if rid and rid == rep.get("video_id") else
                                   (f"(대표 영상 {rep.get('video_id')} 아님)" if rep.get("video_id") else "")))
    common = dict(kind="style_vs_reference", required=req)

    def unmeasured(check, item, cat, why):
        b.add(check, "grid", item, cat, status="unmeasured", note=why, reference="못 잼", **common)

    # ---- captions
    item = "자막 역할·표시 (레퍼런스와 같은 절대 시각 1초 격자)"
    tp = probes.get("text") or {}
    if no_ref:
        unmeasured("ref_grid.captions", item, CAT["ref_grid"], no_ref)
    elif not an.get("captions") or dur_ref is None:
        unmeasured("ref_grid.captions", item, CAT["ref_grid"], f"{ref_note}: captions.json 없음(`ref analyze` 필요)")
    elif tp.get("status") != "measured":
        unmeasured("ref_grid.captions", item, CAT["ref_grid"], "출력 자막 측정 실패: " + str(tp.get("reason") or ""))
    else:
        res = caption_cells(an["captions"].get("items") or [], our_captions(ctx, tp), dur_ref, dur_ours)
        st = _status(res["cells"])
        b.add("ref_grid.captions", "grid", item, CAT["ref_grid"], status=st,
              expected={"reference_cells": [{"t": c["t"], "roles": c["reference"]} for c in res["cells"]]},
              observed=_summary(res), tolerance="1초 칸마다 화면의 자막 역할 집합이 같음",
              reference={"video_id": rid, "duration": dur_ref},
              evidence={"t": (next((c["t"] for c in res["cells"] if c["status"] == "different"), None))},
              note=f"{ref_note}; 짧은 영상 끝 이후 {res['past_shorter_video']}칸은 비교하지 않음(길이는 structure.duration)",
              **common)
    # ---- cuts
    item = "컷·전환 위치 (레퍼런스와 같은 절대 시각 1초 격자)"
    ours_c = our_cuts(probes.get("video") or {})
    if no_ref:
        unmeasured("ref_grid.cuts", item, CAT["ref_grid"], no_ref)
    elif not an.get("shots") or dur_ref is None:
        unmeasured("ref_grid.cuts", item, CAT["ref_grid"], f"{ref_note}: shots.json 없음(`ref analyze` 필요)")
    elif ours_c is None:
        unmeasured("ref_grid.cuts", item, CAT["ref_grid"], "출력 컷 측정 실패")
    else:
        res = cut_cells(an["shots"].get("cuts") or [], ours_c, dur_ref, dur_ours)
        b.add("ref_grid.cuts", "grid", item, CAT["ref_grid"], status=_status(res["cells"]),
              expected={"reference_cuts": [{"t": c.get("t"), "type": c.get("type")} for c in an["shots"].get("cuts") or []]},
              observed={**_summary(res), "our_cuts": ours_c}, tolerance="1초 칸마다 컷·플래시·크로스페이드 개수와 종류가 같음",
              reference={"video_id": rid, "duration": dur_ref},
              evidence={"t": (next((c["t"] for c in res["cells"] if c["status"] == "different"), None))},
              note=f"{ref_note}; 우리 컷 = 출력에서 측정한 계획 경계 + 계획에 없는 컷(소스 자체 컷 포함 — 레퍼런스 분석도 같은 기준)",
              **common)
    # ---- SFX (0.5 s strip)
    item = "효과음 종류·자리 (레퍼런스와 같은 절대 시각 0.5초 격자)"
    ours_s = our_sfx(probes.get("audio") or {})
    ev = an.get("audio_sfx_events")
    if no_ref:
        unmeasured("ref_grid.sfx", item, CAT["ref_grid"], no_ref)
    elif not ev or dur_ref is None:
        unmeasured("ref_grid.sfx", item, CAT["ref_grid"], f"{ref_note}: audio/sfx_events.json 없음(`ref audio-analyze` 필요)")
    elif ours_s is None:
        unmeasured("ref_grid.sfx", item, CAT["ref_grid"], "출력 오디오 측정 실패")
    else:
        ref_ev = []
        for e in ev.get("events") or []:
            cls = e.get("class")
            if cls == "intentional_silence":
                ref_ev.append({"t": float(e["t"]), "type": SILENCE})
            elif cls == "edit_sfx":
                ref_ev.append({"t": float(e["t"]), "type": e.get("type_id") or "?"})
        res = sfx_cells(ref_ev, ev.get("unmeasured_coverage") or [], ours_s, dur_ref, dur_ours)
        b.add("ref_grid.sfx", "grid", item, CAT["ref_grid"], status=_status(res["cells"]),
              expected={"reference_events": ref_ev}, observed={**_summary(res), "our_events": ours_s},
              tolerance="0.5초 칸마다 편집 효과음 종류(와 의도적 정적)가 같음; 현장음(onsite_sound)은 비교하지 않음",
              reference={"video_id": rid, "duration": dur_ref},
              evidence={"t": (next((c["t"] for c in res["cells"] if c["status"] == "different"), None))},
              note=f"{ref_note}; 레퍼런스에서 효과음을 못 잰 구간(unmeasured_coverage)의 칸은 못 잼", **common)


def sheet_row(ctx, rows: list[dict], reference_rec: dict, sheet_error: str | None) -> None:
    """ref_grid.sheet: the compare sheet with the reference frames and both strips exists (appended after the sheet
    is drawn, so it is judged on the file that was really written)."""
    from .checks import CAT, RowBuilder

    b = RowBuilder(ctx)
    req = getattr(ctx.resolved, "mode", "test") == "production"
    sheets = reference_rec.get("sheets") or []
    if sheet_error:
        st, note = "unmeasured", f"비교 시트를 만들지 못함: {sheet_error}"
    elif not sheets:
        st, note = "unmeasured", "비교 시트 없음"
    elif not reference_rec.get("path"):
        st, note = "unmeasured", ("레퍼런스 MP4 없음 — 시트의 레퍼런스 줄이 '못 잼'으로 그려짐: "
                                  + str((reference_rec.get("representative") or {}).get("reason") or ""))
    else:
        st, note = "same", "레퍼런스 프레임·자막 띠·0.5초 효과음 띠와 우리 편을 같은 절대 시각으로 그림"
    b.add("ref_grid.sheet", "sheet", "레퍼런스 1편과 같은 절대 시각 1초 격자 비교 시트", CAT["ref_grid"], status=st,
          expected={"reference": reference_rec.get("video_id"), "grid_s": 1.0, "sfx_strip_s": 0.5},
          observed={"sheets": sheets, "reference_path": reference_rec.get("path")}, kind="style_vs_reference",
          required=req, reference={"video_id": reference_rec.get("video_id")}, note=note)
    rows.extend(b.rows)
