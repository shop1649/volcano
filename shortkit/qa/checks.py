"""QA checks: turn probe measurements into report rows, and declare which preset keys each
check verifies (``declarations()`` -> settings_registry.yaml ``qa_checks``).

Row format (docs/CONTRACT.md section 10)::

    {check_id, row_id, item (Korean), category, kind, reference, expected, observed, tolerance,
     status: same|different|unmeasured, intended_change, change_ref, evidence {t, frame}, note,
     required, keys}

Two kinds of rows:
* ``output_vs_plan``      did the MP4 render what the plan / ResolvedEdit says?
* ``style_vs_reference``  does the output match the reference channel?  Preset keys whose
                          origin is ``provisional`` (never measured on the reference) make the
                          row ``unmeasured`` (못 잼) even when output == expected.  Keys in
                          ``requested_changes.yaml`` are reported as intended changes.
This module must stay import-light (``shortkit.config`` imports ``declarations``).
"""
from __future__ import annotations

import math
from typing import Any

# ----------------------------------------------------------------------------- categories
CAT = {
    "text_pos": "글자 위치",
    "font": "폰트",
    "cap_timing": "자막 타이밍",
    "cut": "컷",
    "motion": "모션(확대·정지·전환)",
    "music": "음악 구간",
    "original": "원음",
    "logo": "로고 잔류",
    "sfx_count": "효과음 종류별 개수",
    "sfx_offset": "사건과의 시차",
    "sfx_no_event": "사건 없는 효과음 0",
    "deco": "움직이는 장식(위치/밝기 각각)",
    "identity": "식별 요소",
    "cover_up": "얼굴·손·물체 가림",
    "loudness": "음량",
    # additional categories (beyond the user's required list)
    "cap_style": "자막 스타일",
    "cap_text": "자막 내용·말투",
    "cap_motion": "자막 등장·퇴장 모션",
    "canvas": "화면 구성",
    "structure": "구성·표지",
}
REQUIRED_CATEGORIES = [CAT[k] for k in ("text_pos", "font", "cap_timing", "cut", "motion", "music", "original", "logo",
                                        "sfx_count", "sfx_offset", "sfx_no_event", "deco", "identity", "cover_up",
                                        "loudness")]

# ----------------------------------------------------------------------------- declarations
_DECL: dict[str, list[str]] = {
    "canvas.format": ["canvas.width", "canvas.height", "canvas.fps"],
    "canvas.background": ["canvas.background.*"],
    "canvas.video_region": ["canvas.video_region.*"],
    "canvas.safe_margin": ["canvas.safe_margin.*"],
    "caption.position": ["text.roles.*.anchor.*", "text.roles.*.max_width_px"],
    "caption.size": ["text.roles.*.size_px", "text.roles.*.line_spacing", "text.roles.*.max_lines",
                     "text.roles.*.max_chars_per_line"],
    "caption.style": ["text.roles.*.color", "text.roles.*.highlight_color", "text.roles.*.outline_px",
                      "text.roles.*.outline_color", "text.roles.*.shadow_px", "text.roles.*.shadow_color",
                      "text.roles.*.box.*"],
    "caption.font": ["text.roles.*.font_name", "text.roles.*.bold", "text.roles.*.font_file"],
    "caption.timing": ["text.roles.*.timing.*", "text.roles.*.persist"],
    "caption.motion": ["text.roles.*.motion_in.*", "text.roles.*.motion_out.*"],
    "caption.text": ["text.roles.*.quote_marks"],
    "caption.tone": ["text.tone.*"],
    "video.cuts": [],
    "video.mapping": [],
    "video.transitions": ["motion.transitions.*"],
    "video.zoom": ["motion.zoom.*"],
    "video.freeze": ["motion.freeze.*"],
    "video.speed": ["motion.speed.*"],
    "decor.position": ["decorations.*"],
    "decor.brightness": ["decorations.*.blink_hz", "decorations.*.color"],
    "identity.forbidden_text": ["identity_exclusions.forbidden_text", "identity_exclusions.own_branding"],
    "identity.logo_templates": ["identity_exclusions.logo_templates_dir"],
    "identity.reference_footage": [],
    "caption.reveal": [],
    "clean.corners": [],
    "clean.residual": [],
    "cover_up.protected": [],
    "cover_up.faces": [],
    "audio.bgm": ["audio.bgm.*"],
    "audio.ducking": ["audio.ducking.*"],
    "audio.silence": ["audio.silence.*"],
    "audio.original": ["audio.original.*"],
    "audio.sfx.placement": ["audio.sfx.gain_db_default"],
    "audio.sfx.count": ["audio.sfx.catalog", "audio.sfx.map"],
    "audio.sfx.offset": ["audio.sfx.max_event_offset_s", "audio.sfx.require_event"],
    "audio.sfx.no_event": ["audio.sfx.require_event"],
    "audio.sfx.unexplained": [],
    "audio.loudness": ["audio.loudness.*", "audio.sample_rate"],
    "structure.duration": ["structure.*"],
    "cover.frame": ["cover.*"],
}

# probe families each check needs (for selective re-runs)
FAMILY = {
    "canvas.": ("video", "text"), "caption.": ("text",), "video.": ("video",), "decor.": ("video",),
    "identity.": ("text",), "clean.corners": ("text",), "clean.residual": ("video",), "cover_up.": ("text", "video"),
    "audio.": ("audio",), "structure.": ("text", "audio"), "cover.": ("text",),
}


def declarations() -> dict[str, list[str]]:
    """check_id -> preset key globs verified by that check in the output MP4."""
    return {k: list(v) for k, v in _DECL.items()}


def families_for(check_ids: list[str]) -> set[str]:
    fams: set[str] = set()
    for cid in check_ids:
        for pre, fs in FAMILY.items():
            if cid.startswith(pre):
                fams.update(fs)
    return fams or {"text", "video", "audio"}


# ----------------------------------------------------------------------------- tolerances
TOL = {
    "pos_px_min": 10.0, "pos_frac_line": 0.2, "size_frac": 0.15, "text_sim": 0.6, "time_frames": 1.0,
    "color_rgb": 45.0, "scale_first": 0.08, "zoom_ratio": 0.04, "src_offset_s": 0.07, "speed_frac": 0.05,
    "deco_abs_px": 14.0, "deco_path_px": 10.0, "blink_frac": 0.15, "bgm_tempo": 0.01, "bgm_section_s": 0.1,
    "bgm_ncc": 0.3, "duck_depth_db": 3.0, "silence_db": -30.0, "orig_present_frac": 0.7, "sfx_t_s": 0.05,
    "sfx_gain_db": 3.0, "region_px": 8.0, "bg_rgb": 30.0, "fade_s": 0.15,
}


# ----------------------------------------------------------------------------- helpers
def _r(v, d=3):
    if v is None:
        return None
    try:
        return round(float(v), d)
    except (TypeError, ValueError):
        return v


def _hex_rgb(c):
    from . import hex_rgb

    return hex_rgb(c)


def _cdist(a, b) -> float | None:
    ra, rb = _hex_rgb(a), _hex_rgb(b)
    if ra is None or rb is None:
        return None
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(ra, rb)))


class RowBuilder:
    def __init__(self, ctx) -> None:
        self.ctx = ctx
        self.rows: list[dict] = []
        self._meas = None

    # --- preset access (tracked)
    def pget(self, key: str, default: Any = None) -> Any:
        try:
            v = self.ctx.preset.get(key)
        except KeyError:
            return default
        if hasattr(v, "raw"):
            return v.raw()
        return v

    def measurements(self) -> dict:
        if self._meas is None:
            from ..util.jsonio import read_json

            self._meas = {}
            d = self.ctx.preset.dir / "measurements"
            if d.is_dir():
                for f in sorted(d.glob("*.json")):
                    m = read_json(f) or {}
                    items = m.get("items", []) if isinstance(m, dict) else m
                    for it in items or []:
                        if isinstance(it, dict) and it.get("key"):
                            self._meas[it["key"]] = it
        return self._meas

    def reference_of(self, keys: list[str]) -> tuple[Any, list[str], list[str]]:
        """(reference display, provisional keys, requested keys) for concrete preset keys."""
        prov, req, disp = [], [], {}
        rk = set(self.ctx.preset.requested_keys())
        meas = self.measurements()
        fmt = self.ctx.preset.format_id
        for k in keys:
            o = self.ctx.preset.origin(k)
            if k in rk:
                req.append(k)
            m = meas.get(k)
            if o == "provisional":
                prov.append(k)
                disp[k] = "못 잼"
            elif m and m.get("status") == "measured":
                ent = {"value": m.get("value")}
                bf = (m.get("by_format") or {}).get(fmt or "") if fmt else None
                st = bf or m.get("overall")
                if st:
                    ent.update({kk: st.get(kk) for kk in ("n", "p10", "p50", "p90") if kk in st})
                if m.get("resolution"):
                    ent["resolution"] = m["resolution"]
                disp[k] = ent
            elif o == "requested_change":
                disp[k] = "못 잼(요청 변경 키; 레퍼런스 측정 기록 없음)"
            elif o in ("rule", "infra", "meta"):
                disp[k] = f"해당 없음({o})"
            else:
                disp[k] = "못 잼"
        if keys and all(v == "못 잼" for v in disp.values()):
            return "못 잼", prov, req
        return (disp if keys else None), prov, req

    # --- rows
    def add(self, check_id: str, subject: str, item: str, category: str, *, expected=None, observed=None,
            tolerance=None, status: str, keys: list[str] | None = None, kind: str = "output_vs_plan",
            required: bool = True, evidence: dict | None = None, note: str = "", intended_change: bool = False,
            change_ref: str | None = None, reference: Any = "__auto__") -> dict:
        keys = [k for k in (keys or []) if k]
        if reference == "__auto__":
            reference, _, _ = self.reference_of(keys)
        row = {"check_id": check_id, "row_id": f"{check_id}:{subject}", "item": item, "category": category,
               "kind": kind, "reference": reference, "expected": expected, "observed": observed,
               "tolerance": tolerance, "status": status, "intended_change": bool(intended_change),
               "change_ref": change_ref, "evidence": evidence or {}, "note": note, "required": bool(required),
               "keys": keys}
        if status == "unmeasured":
            row["impact"] = _impact(keys, category, kind)
        self.rows.append(row)
        return row

    def style_row(self, check_id: str, subject: str, item: str, category: str, keys: list[str], observed: Any,
                  compare, *, evidence=None, note: str = "", required: bool | None = None) -> dict:
        """style-vs-reference row: compare the OUTPUT measurement with the reference value."""
        keys = [k for k in keys if self._has(k)]
        ref, prov, req = self.reference_of(keys)
        expected = {k: self.pget(k) for k in keys}
        mode = getattr(self.ctx.resolved, "mode", "test")
        if required is None:
            required = mode == "production"
        if not keys:
            return self.add(check_id, subject, item, category, expected=None, observed=observed, status="unmeasured",
                            kind="style_vs_reference", required=False, note="프리셋에 해당 키 없음", reference="못 잼")
        if req:
            ok = None if observed is None else compare(observed, {k: self.pget(k) for k in req})
            change_ref = ", ".join(f"presets/{self.ctx.preset.name}/requested_changes.yaml#changes.{k}" for k in req)
            if ok is True:
                return self.add(check_id, subject, item, category, expected=expected, observed=observed,
                                status="different", keys=keys, kind="style_vs_reference", required=required,
                                intended_change=True, change_ref=change_ref, evidence=evidence, reference=ref,
                                note=(note + " 요청 변경이 출력에 반영됨").strip())
            return self.add(check_id, subject, item, category, expected=expected, observed=observed,
                            status="unmeasured" if ok is None else "different", keys=keys, kind="style_vs_reference",
                            required=required, intended_change=False, change_ref=change_ref, evidence=evidence,
                            reference=ref, note=(note + (" 출력에서 측정 못 함" if ok is None else
                                                          " 요청 변경이 출력에 반영되지 않음")).strip())
        if prov:
            return self.add(check_id, subject, item, category, expected=expected, observed=observed,
                            status="unmeasured", keys=keys, kind="style_vs_reference", required=required,
                            evidence=evidence, reference=ref,
                            note=(f"레퍼런스 미측정(임시값) 키 {len(prov)}개: {', '.join(prov[:6])}"
                                  f"{' …' if len(prov) > 6 else ''} — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. "
                                  + note).strip())
        if observed is None:
            return self.add(check_id, subject, item, category, expected=expected, observed=None, status="unmeasured",
                            keys=keys, kind="style_vs_reference", required=required, evidence=evidence,
                            reference=ref, note=("출력에서 측정 못 함. " + note).strip())
        ok = compare(observed, {k: self.pget(k) for k in keys})
        st = "unmeasured" if ok is None else ("same" if ok else "different")
        return self.add(check_id, subject, item, category, expected=expected, observed=observed, status=st, keys=keys,
                        kind="style_vs_reference", required=required, evidence=evidence, reference=ref, note=note)

    def _has(self, key: str) -> bool:
        from ..config import get_path

        try:
            get_path(self.ctx.preset.data, key)
            return True
        except KeyError:
            return False


CAT_IMPACT = {
    CAT["text_pos"]: "자막 위치·크기를 출력에서 확인하지 못함 → 가림·어긋남이 남아 있을 수 있음",
    CAT["font"]: "글꼴이 맞는지 확인하지 못함 → 글자 인상이 다를 수 있음",
    CAT["cap_timing"]: "자막 등장·퇴장 시각을 확인하지 못함",
    CAT["cut"]: "컷 위치·소스 구간을 확인하지 못함 → 잘못된 구간이 쓰였을 수 있음",
    CAT["motion"]: "확대·정지·전환이 계획대로인지 확인하지 못함",
    CAT["music"]: "BGM 곡·구간·덕킹을 확인하지 못함 → 음악 일치 판정 불가",
    CAT["original"]: "원음이 필요한 곳에만 나오는지 확인하지 못함",
    CAT["logo"]: "원본 로고·출처 표기가 남아 있는지 확인하지 못함 → 게시 위험",
    CAT["sfx_count"]: "효과음 종류·개수를 확인하지 못함",
    CAT["sfx_offset"]: "효과음과 사건의 시차를 확인하지 못함",
    CAT["sfx_no_event"]: "사건 없는 효과음이 없는지 확인하지 못함",
    CAT["deco"]: "장식 위치·깜빡임을 확인하지 못함",
    CAT["identity"]: "레퍼런스 채널 식별 요소·같은 녹화 재사용 여부를 확인하지 못함 → 게시 위험",
    CAT["cover_up"]: "얼굴·손·핵심 물체를 가리는지 확인하지 못함",
    CAT["loudness"]: "최종 음량을 확인하지 못함",
    CAT["cap_style"]: "자막 색·외곽선·박스를 확인하지 못함",
    CAT["cap_text"]: "자막 문구·말투를 확인하지 못함",
    CAT["cap_motion"]: "자막 등장 모션을 확인하지 못함",
    CAT["canvas"]: "화면 구성을 확인하지 못함",
    CAT["structure"]: "길이·표지 구성을 확인하지 못함",
}


def _impact(keys: list[str], category: str, kind: str = "output_vs_plan") -> str:
    if keys and kind == "style_vs_reference":
        try:
            from ..config import impact_of

            return impact_of(keys[0])
        except Exception:
            pass
    return CAT_IMPACT.get(category, "판정 불가 — 완료로 볼 수 없음")


def _role_keys(role: str, names: list[str]) -> list[str]:
    return [f"text.roles.{role}.{n}" for n in names]


# ----------------------------------------------------------------------------- canvas
def rows_canvas(b: RowBuilder, probes: dict) -> None:
    ctx = b.ctx
    cv = ctx.resolved.canvas or {}
    fr = 1.0 / ctx.fps
    exp = {"width": cv.get("width"), "height": cv.get("height"), "fps": cv.get("fps")}
    obs = {"width": ctx.info.width, "height": ctx.info.height, "fps": _r(ctx.info.fps, 3)}
    ok = obs["width"] == exp["width"] and obs["height"] == exp["height"] and \
        (exp["fps"] is None or abs((obs["fps"] or 0) - float(exp["fps"])) < 0.01)
    b.add("canvas.format", "format", "화면 해상도·프레임레이트", CAT["canvas"], expected=exp, observed=obs,
          tolerance="정확히 일치", status="same" if ok else "different",
          keys=["canvas.width", "canvas.height", "canvas.fps"])
    b.style_row("canvas.format", "format_ref", "화면 해상도·프레임레이트 (레퍼런스 대비)", CAT["canvas"],
                ["canvas.width", "canvas.height", "canvas.fps"], obs,
                lambda o, r: o["width"] == r.get("canvas.width") and o["height"] == r.get("canvas.height")
                and abs(float(o["fps"] or 0) - float(r.get("canvas.fps") or 0)) < 0.01)
    lay = (probes.get("video") or {}).get("layout") or {}
    vr_keys = [f"canvas.video_region.{k}" for k in ("x", "y", "w", "h", "fit")]
    if lay.get("status") == "measured" and lay.get("video_region"):
        regs = {tuple(round(v, 1) for v in (c.region.x, c.region.y, c.region.w, c.region.h)) for c in ctx.resolved.clips}
        er = list(next(iter(regs))) if len(regs) == 1 else None
        o = lay["video_region"]
        if er is not None:
            err = max(abs(a - b_) for a, b_ in zip(o, er))
            b.add("canvas.video_region", "region", "영상 영역 위치·크기", CAT["canvas"],
                  expected={"rect": er, "resolution": [ctx.canvas_w, ctx.canvas_h]},
                  observed={"rect": o, "resolution": [ctx.info.width, ctx.info.height]},
                  tolerance=f"±{TOL['region_px']:.0f}px", status="same" if err <= TOL["region_px"] else "different",
                  keys=vr_keys, required=False, note="움직이는 화소·배경색 차이로 측정(휴리스틱)")
        b.style_row("canvas.video_region", "region_ref", "영상 영역 (레퍼런스 대비)", CAT["canvas"], vr_keys,
                    {"rect": o}, lambda ob, r: max(abs(ob["rect"][i] - float(r.get(f"canvas.video_region.{k}", 0)))
                                                   for i, k in enumerate("xywh")) <= TOL["region_px"])
        bg = lay.get("background") or {}
        ebg = cv.get("background") or {}
        if bg.get("color"):
            dist = _cdist(bg["color"], ebg.get("color"))
            same = bg.get("type") == ebg.get("type") and (ebg.get("type") != "color" or (dist is not None and dist <= TOL["bg_rgb"]))
            b.add("canvas.background", "background", "배경(색/소스 블러)", CAT["canvas"],
                  expected={"type": ebg.get("type"), "color": ebg.get("color")}, observed=bg,
                  tolerance=f"종류 일치, 색 거리 ≤ {TOL['bg_rgb']:.0f}", status="same" if same else "different",
                  keys=["canvas.background.type", "canvas.background.color", "canvas.background.blur_sigma"],
                  required=False, note="blur_sigma 는 측정하지 않음")
        b.style_row("canvas.background", "background_ref", "배경 (레퍼런스 대비)", CAT["canvas"],
                    ["canvas.background.type", "canvas.background.color", "canvas.background.blur_sigma"],
                    bg if bg.get("color") else None,
                    lambda ob, r: ob.get("type") == r.get("canvas.background.type") and
                    (_cdist(ob.get("color"), r.get("canvas.background.color")) or 999) <= TOL["bg_rgb"])
    else:
        b.add("canvas.video_region", "region", "영상 영역 위치·크기", CAT["canvas"], status="unmeasured",
              keys=vr_keys, required=False, note=lay.get("reason") or "레이아웃 측정 실패")
    # safe margins: every measured caption box inside the safe area
    caps = [c for c in (probes.get("text") or {}).get("captions") or [] if c.get("bbox_obs")]
    sm = b.pget("canvas.safe_margin") or {}
    if caps and sm:
        W, H = ctx.info.width, ctx.info.height
        worst = {"left": min(c["bbox_obs"][0] for c in caps), "top": min(c["bbox_obs"][1] for c in caps),
                 "right": min(W - c["bbox_obs"][0] - c["bbox_obs"][2] for c in caps),
                 "bottom": min(H - c["bbox_obs"][1] - c["bbox_obs"][3] for c in caps)}
        viol = {k: v for k, v in worst.items() if v < float(sm.get(k, 0))}
        b.add("canvas.safe_margin", "captions", "자막이 안전 여백 안에 있음", CAT["canvas"],
              expected={k: sm.get(k) for k in ("left", "right", "top", "bottom")}, observed={"min_margin_px": worst},
              tolerance="여백 이상", status="same" if not viol else "different",
              keys=[f"canvas.safe_margin.{k}" for k in ("left", "right", "top", "bottom")], required=False,
              note=("여백 침범: " + ", ".join(viol)) if viol else "")


# ----------------------------------------------------------------------------- captions
def rows_captions(b: RowBuilder, probes: dict) -> None:
    ctx = b.ctx
    tp = probes.get("text") or {}
    fr = 1.0 / ctx.fps
    if tp.get("status") != "measured":
        for cap in ctx.resolved.captions:
            for cid, it, cat in (("caption.position", "자막 위치", CAT["text_pos"]),
                                 ("caption.timing", "자막 타이밍", CAT["cap_timing"]),
                                 ("caption.font", "자막 글꼴", CAT["font"])):
                b.add(cid, cap.id, f"{it} [{cap.id}]", cat, status="unmeasured", note=tp.get("reason") or "문자 검사 실패")
        return
    meas = {c["id"]: c for c in tp.get("captions") or []}
    for cap in ctx.resolved.captions:
        m = meas.get(cap.id) or {}
        role = cap.role
        n_lines = max(1, len([l for l in (cap.lines or []) if l.strip()]) or 1)
        line_h = (cap.bbox.h / n_lines) if cap.bbox.h else cap.size_px * 0.6
        ev = {"t": m.get("t_rest"), "frame": m.get("evidence_frame")}
        res = [ctx.info.width, ctx.info.height]
        exp_c = [cap.bbox.x + cap.bbox.w / 2, cap.bbox.y + cap.bbox.h / 2]
        pos_keys = _role_keys(role, ["anchor.x", "anchor.y", "anchor.align", "anchor.valign"])
        pos_override = abs(cap.anchor[0] - float(b.pget(f"text.roles.{role}.anchor.x", cap.anchor[0]))) > 0.5 or \
            abs(cap.anchor[1] - float(b.pget(f"text.roles.{role}.anchor.y", cap.anchor[1]))) > 0.5
        label = f"[{cap.id}·{role}] \"{cap.text[:18]}\""
        if m.get("error"):
            b.add("caption.position", cap.id, f"자막 위치 {label}", CAT["text_pos"], status="unmeasured",
                  keys=pos_keys, note=m["error"], evidence=ev)
            continue
        if not m.get("found"):
            near = [c for c in m.get("candidates") or []
                    if _iou(c["box"], [cap.bbox.x, cap.bbox.y, cap.bbox.w, cap.bbox.h]) > 0.3]
            st = "unmeasured" if near else "different"
            note = ("예상 위치에 글자 화소는 있으나 OCR 로 문구를 확인하지 못함" if near else
                    "출력 프레임에서 이 자막을 찾지 못함(다른 위치 후보들의 OCR: " +
                    "; ".join(f"{c['ocr'][:12]}@{c['box'][:2]}" for c in (m.get('candidates') or [])[:3]) + ")")
            for cid, it, cat in (("caption.position", "자막 위치", CAT["text_pos"]),
                                 ("caption.timing", "자막 타이밍", CAT["cap_timing"])):
                b.add(cid, cap.id, f"{it} {label}", cat, expected={"bbox": [cap.bbox.x, cap.bbox.y, cap.bbox.w, cap.bbox.h],
                                                                   "resolution": res, "start": cap.start, "end": cap.end},
                      observed=None, status=st, keys=pos_keys if cid == "caption.position" else [], note=note, evidence=ev)
            continue
        ob = m["bbox_obs"]
        obs_c = [ob[0] + ob[2] / 2, ob[1] + ob[3] / 2]
        tol_px = max(TOL["pos_px_min"], TOL["pos_frac_line"] * line_h)
        dx, dy = obs_c[0] - exp_c[0], obs_c[1] - exp_c[1]
        b.add("caption.position", cap.id, f"자막 위치 {label}", CAT["text_pos"],
              expected={"center": [_r(v, 1) for v in exp_c], "bbox": [_r(cap.bbox.x, 1), _r(cap.bbox.y, 1), _r(cap.bbox.w, 1),
                                                                       _r(cap.bbox.h, 1)], "resolution": res},
              observed={"center": [_r(v, 1) for v in obs_c], "bbox": ob, "resolution": res, "dx": _r(dx, 1), "dy": _r(dy, 1)},
              tolerance=f"중심 ±{tol_px:.0f}px", status="same" if abs(dx) <= tol_px and abs(dy) <= tol_px else "different",
              keys=[] if pos_override else pos_keys, evidence=ev,
              note="에피소드 위치 지정(pos)" if pos_override else "")
        # size / lines / width
        # IR bbox includes the outline stroke; the measured ink is the fill only
        exp_fill_h = max(1.0, cap.bbox.h - 2 * float(cap.outline_px or 0))
        tol_h = TOL["size_frac"] * exp_fill_h + 3
        dh = ob[3] - exp_fill_h
        lines_ok = m.get("lines_found") == m.get("lines_expected")
        maxw = float(b.pget(f"text.roles.{role}.max_width_px", 1e9) or 1e9)
        maxl = int(b.pget(f"text.roles.{role}.max_lines", 99) or 99)
        size_ok = abs(dh) <= tol_h and lines_ok and ob[2] <= maxw + 4 and (m.get("lines_found") or 0) <= maxl
        b.add("caption.size", cap.id, f"자막 크기·줄 수 {label}", CAT["text_pos"],
              expected={"fill_h": _r(exp_fill_h, 1), "lines": m.get("lines_expected"), "max_width_px": maxw, "max_lines": maxl,
                        "size_px": cap.size_px},
              observed={"fill_h": ob[3], "fill_w": ob[2], "lines": m.get("lines_found"),
                        "size_px_est": _r(cap.size_px * ob[3] / exp_fill_h, 1)},
              tolerance=f"높이 ±{tol_h:.0f}px, 줄 수 일치, 폭 ≤ max_width_px", status="same" if size_ok else "different",
              keys=_role_keys(role, ["size_px", "max_width_px", "max_lines", "max_chars_per_line", "line_spacing"]),
              evidence=ev, required=True,
              note="채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선)")
        # text similarity (OCR)
        sim = m.get("similarity") or 0.0
        geo = str(m.get("match") or "").startswith("geometry")
        b.add("caption.text", cap.id, f"자막 문구(OCR) {label}", CAT["cap_text"], expected=cap.text,
              observed={"ocr": m.get("ocr"), "similarity": sim, "match": m.get("match")},
              tolerance=f"OCR 유사도 ≥ {TOL['text_sim']}",
              status="same" if sim >= TOL["text_sim"] else ("unmeasured" if geo else "different"), evidence=ev,
              keys=_role_keys(role, ["quote_marks"]) if role == "dialogue" else [],
              note=("짧은 문구를 OCR 이 읽지 못해 위치·색으로만 찾음 — 문구 일치는 못 잼" if geo and sim < TOL["text_sim"]
                    else "굵은 글꼴 OCR 오차가 있어 유사도로 판정"))
        # colour / outline / box
        fill = m.get("fill_color")
        dcol = _cdist(fill, cap.color)
        style_ok = dcol is not None and dcol <= TOL["color_rgb"]
        oobs = m.get("outline_px_obs")
        outline_measurable = (m.get("outline_bg_same_color_frac") or 0) < 0.5
        notes = []
        if cap.outline_px and outline_measurable and oobs is not None:
            if abs(oobs - float(cap.outline_px)) > max(2.0, 0.35 * float(cap.outline_px)):
                style_ok = False
                notes.append(f"외곽선 두께 {oobs}px (기대 {cap.outline_px}px)")
        elif cap.outline_px:
            notes.append("배경이 외곽선 색과 같아 외곽선 두께는 못 잼")
        box = cap.box or {}
        ba = m.get("box_alpha_obs")
        if box.get("enabled"):
            ea = float(box.get("alpha") if box.get("alpha") is not None else 1.0)
            if ba is None:
                notes.append("배경이 어두워 자막 박스 투명도는 못 잼")
            elif abs(ba - ea) > 0.2:
                style_ok = False
                notes.append(f"자막 박스 불투명도 {ba} (기대 {ea})" if ba >= 0.15 else "자막 박스가 보이지 않음")
        elif ba is not None and ba > 0.3:
            style_ok = False
            notes.append(f"계획에 없는 어두운 박스(불투명도 {ba})")
        if cap.highlight:
            if not m.get("highlight_px"):
                style_ok = False
                notes.append("강조색 화소 없음")
        b.add("caption.style", cap.id, f"자막 색·외곽선·박스 {label}", CAT["cap_style"],
              expected={"color": cap.color, "outline_px": cap.outline_px, "outline_color": cap.outline_color,
                        "box": bool(box.get("enabled")), "box_alpha": box.get("alpha") if box.get("enabled") else None,
                        "highlight": cap.highlight},
              observed={"fill_color": fill, "outline_px": oobs, "outline_color": m.get("outline_color"),
                        "box_alpha": ba, "highlight_px": m.get("highlight_px")},
              tolerance=f"색 거리 ≤ {TOL['color_rgb']:.0f}, 외곽선 ±max(2px,35%)",
              status="unmeasured" if fill is None else ("same" if style_ok else "different"),
              keys=_role_keys(role, ["color", "outline_px", "outline_color", "box.enabled", "highlight_color"]),
              evidence=ev, note="; ".join(notes) + ("; 그림자는 측정하지 않음" if cap.shadow_px else ""))
        # font
        _font_row(b, cap, m, label, role, ev)
        # timing
        on, off = m.get("onset"), m.get("offset")
        fade_io = (cap.motion_in or {}).get("type") == "fade" or (cap.motion_out or {}).get("type") == "fade"
        tol_t = (1.5 if fade_io else TOL["time_frames"]) * fr + 0.005
        t_ok = []
        notes = []
        if on is None:
            notes.append(m.get("onset_note") or "등장 시점 측정 못 함")
        else:
            t_ok.append(abs(on - cap.start) <= tol_t)
        if off is None:
            notes.append(m.get("offset_note") or "퇴장 시점 측정 못 함")
        else:
            t_ok.append(abs(off - cap.end) <= tol_t or (cap.end >= ctx.info.duration - fr and off >= ctx.info.duration - fr))
        st = "unmeasured" if len(t_ok) < 2 else ("same" if all(t_ok) else "different")
        if len(t_ok) == 1 and not t_ok[0]:
            st = "different"
        b.add("caption.timing", cap.id, f"자막 등장·퇴장 시각 {label}", CAT["cap_timing"],
              expected={"start": _r(cap.start), "end": _r(cap.end)}, observed={"onset": on, "offset": off},
              tolerance=f"±{TOL['time_frames']:.0f}프레임(페이드 ±1.5프레임: 투명도 경사 외삽)", status=st,
              keys=_role_keys(role, ["timing.lead_s", "timing.min_dur_s", "persist"]),
              evidence={"t": on, "frame": m.get("evidence_frame")}, note="; ".join(notes))
        # motion in / out
        mi = cap.motion_in or {}
        mo = m.get("motion_in_obs")
        et = (mi.get("type") or "none")
        if mo is None:
            b.add("caption.motion", cap.id, f"자막 등장 모션 {label}", CAT["cap_motion"], expected=mi, observed=None,
                  status="unmeasured", keys=_role_keys(role, ["motion_in.type", "motion_in.dur_s", "motion_in.scale_from"]),
                  evidence=ev, note="등장 시점을 측정하지 못해 모션 판정 불가")
        else:
            ok = mo["type"] == (et if et in ("pop", "fade") else "none")
            if ok and et == "pop" and mo.get("scale_first") is not None:
                ok = abs(mo["scale_first"] - float(mi.get("scale_from") or 1.0)) <= TOL["scale_first"] + \
                    abs(float(mi.get("scale_from") or 1.0) - 1.0) * 0.35
            b.add("caption.motion", cap.id, f"자막 등장 모션 {label}", CAT["cap_motion"],
                  expected={"type": et, "dur_s": mi.get("dur_s"), "scale_from": mi.get("scale_from")},
                  observed=mo, tolerance="종류 일치, pop 첫 프레임 배율 오차 ≤ 0.08(+35% 여유)",
                  status="same" if ok else "different",
                  keys=_role_keys(role, ["motion_in.type", "motion_in.dur_s", "motion_in.scale_from", "motion_in.offset_px"]),
                  evidence={"t": m.get("onset"), "frame": m.get("evidence_frame")},
                  note="slide/offset 는 측정하지 않음" if et not in ("pop", "fade", "none") else "")
    # information order: captions shown before the reveal must not contain its keywords
    rv = (ctx.plan or {}).get("reveal") or {}
    if rv.get("t") is not None and rv.get("keywords"):
        from .probes_text import _fuzzy_contains

        hits, basis = [], []
        for cap in ctx.resolved.captions:
            m = meas.get(cap.id) or {}
            on = m.get("onset") if m.get("onset") is not None else cap.start
            if on >= float(rv["t"]) - 1e-6:
                continue
            ocr_ok = m.get("found") and (m.get("similarity") or 0) >= TOL["text_sim"]
            txt = m.get("ocr") if ocr_ok else cap.text
            basis.append("OCR" if ocr_ok else "계획문구")
            for kw in rv["keywords"]:
                if _fuzzy_contains(txt or "", kw) >= 0.85:
                    hits.append({"caption": cap.id, "onset": on, "keyword": kw, "basis": "OCR" if ocr_ok else "계획문구"})
        b.add("caption.reveal", "reveal", "반전 전에 반전 내용을 미리 말하지 않음", CAT["cap_text"],
              expected={"reveal_t": rv["t"], "keywords": rv["keywords"]}, observed={"hits": hits},
              tolerance="반전 시각 전 자막에 키워드 0건", status="same" if not hits else "different",
              evidence={"t": hits[0]["onset"]} if hits else {"t": rv["t"]},
              note=("일부 자막은 OCR 이 불확실해 계획 문구로 확인" if "계획문구" in basis else "출력 OCR 문구로 확인"))
    # tone
    tone = tp.get("tone") or {}
    reg = b.pget("text.tone.register")
    b.add("caption.tone", "register", "자막 말투(종결어미, OCR)", CAT["cap_text"], expected=reg,
          observed=tone or None, tolerance="최빈 말투 일치",
          status="unmeasured" if not tone.get("n") else ("same" if tone.get("mode") == reg else "different"),
          keys=["text.tone.register"], required=False,
          note="OCR 문구의 마지막 글자로 분류(휴리스틱)" if tone.get("n") else "OCR 로 읽힌 자막 없음")
    b.add("caption.tone", "emoji", "자막 이모지 사용", CAT["cap_text"], expected=b.pget("text.tone.emoji"), observed=None,
          status="unmeasured", keys=["text.tone.emoji"], required=False, note="출력 화면에서 이모지를 판별하는 방법 없음(OCR 미지원)")
    # style vs reference per role present in the episode
    roles = sorted({c.role for c in ctx.resolved.captions})
    for role in roles:
        rc = [meas.get(c.id) or {} for c in ctx.resolved.captions if c.role == role]
        rc_found = [m for m in rc if m.get("found")]
        caps_r = [c for c in ctx.resolved.captions if c.role == role]
        no_override = [m for m, c in zip(rc, caps_r) if m.get("found") and not _has_pos_override(b, c)]
        obs_anchor = ({"x": _r(_median([m["bbox_obs"][0] + m["bbox_obs"][2] / 2 for m in no_override]), 1),
                       "y": _r(_median([m["bbox_obs"][1] + m["bbox_obs"][3] / 2 for m in no_override]), 1)}
                      if no_override else None)
        tol_px = TOL["pos_px_min"] * 2
        b.style_row("caption.position", f"{role}_ref", f"자막 위치 [{role}] (레퍼런스 대비)", CAT["text_pos"],
                    _role_keys(role, ["anchor.x", "anchor.y", "anchor.align", "anchor.valign", "max_width_px"]),
                    obs_anchor, lambda o, r, role=role: abs(o["x"] - float(r.get(f"text.roles.{role}.anchor.x", 0))) <= tol_px
                    and abs(o["y"] - float(r.get(f"text.roles.{role}.anchor.y", 0))) <= tol_px)
        size_obs = _median([c.size_px * m["bbox_obs"][3] / max(1.0, c.bbox.h - 2 * float(c.outline_px or 0))
                            for m, c in zip(rc, caps_r) if m.get("found") and c.bbox.h])
        b.style_row("caption.size", f"{role}_ref", f"자막 크기 [{role}] (레퍼런스 대비)", CAT["text_pos"],
                    _role_keys(role, ["size_px", "line_spacing", "max_lines", "max_chars_per_line"]),
                    {"size_px_est": _r(size_obs, 1)} if size_obs else None,
                    lambda o, r, role=role: abs(o["size_px_est"] - float(r.get(f"text.roles.{role}.size_px", 0))) <=
                    0.08 * float(r.get(f"text.roles.{role}.size_px", 1)))
        fills = [m.get("fill_color") for m in rc_found if m.get("fill_color")]
        b.style_row("caption.style", f"{role}_ref", f"자막 색·외곽선·박스 [{role}] (레퍼런스 대비)", CAT["cap_style"],
                    _role_keys(role, ["color", "highlight_color", "outline_px", "outline_color", "shadow_px", "shadow_color",
                                      "box.enabled", "box.color", "box.alpha", "box.pad_x", "box.pad_y"]),
                    {"fill_color": fills[0]} if fills else None,
                    lambda o, r, role=role: (_cdist(o["fill_color"], r.get(f"text.roles.{role}.color")) or 999) <= TOL["color_rgb"])
        # only an 'identical' verdict names the output font (similar/different/fallback scores do not)
        fonts = [((m.get("font") or {}).get("identify") or {}).get("top") for m in rc_found
                 if ((m.get("font") or {}).get("identify") or {}).get("top_verdict") == "identical"]
        b.style_row("caption.font", f"{role}_ref", f"자막 글꼴 [{role}] (레퍼런스 대비)", CAT["font"],
                    _role_keys(role, ["font_name", "bold"]), {"best": fonts[0]} if fonts else None,
                    lambda o, r, role=role: str(o["best"]).replace(" ", "").lower() ==
                    str(r.get(f"text.roles.{role}.font_name")).replace(" ", "").lower())
        durs = [(m.get("offset") - m.get("onset")) for m in rc_found if m.get("onset") is not None and m.get("offset") is not None]
        b.style_row("caption.timing", f"{role}_ref", f"자막 표시 시간 [{role}] (레퍼런스 대비)", CAT["cap_timing"],
                    _role_keys(role, ["timing.lead_s", "timing.min_dur_s", "persist"]),
                    {"min_dur_s": _r(min(durs), 3)} if durs else None,
                    lambda o, r, role=role: o["min_dur_s"] >= float(r.get(f"text.roles.{role}.timing.min_dur_s", 0)) - 0.05)
        mts = [(m.get("motion_in_obs") or {}).get("type") for m in rc_found if m.get("motion_in_obs")]
        b.style_row("caption.motion", f"{role}_ref", f"자막 등장·퇴장 모션 [{role}] (레퍼런스 대비)", CAT["cap_motion"],
                    _role_keys(role, ["motion_in.type", "motion_in.dur_s", "motion_in.scale_from", "motion_in.offset_px",
                                      "motion_out.type", "motion_out.dur_s"]),
                    {"type": _mode(mts)} if mts else None,
                    lambda o, r, role=role: o["type"] == r.get(f"text.roles.{role}.motion_in.type"))
    b.style_row("caption.tone", "tone_ref", "자막 말투 (레퍼런스 대비)", CAT["cap_text"],
                ["text.tone.register", "text.tone.sentence_end_examples", "text.tone.emoji", "text.tone.notes"],
                {"register": tone.get("mode")} if tone.get("n") else None,
                lambda o, r: o["register"] == r.get("text.tone.register"))


FONT_VERDICT_STATUS = {"identical": "same", "different": "different", "similar": "unmeasured", "unmeasured": "unmeasured"}


def _font_row(b: RowBuilder, cap, m: dict, label: str, role: str, ev: dict) -> dict:
    """caption.font row.  'same' ONLY for typography's verdict ``identical`` (IoU >= the same-font
    ceiling p10 measured under the output's encode settings, margin over the nearest look-alike >
    noise, per-glyph check passed).  ``similar`` -> 못 잼; ``different`` -> 다르다.  The raw
    font_iou fallback (no ceiling experiment possible) can report 'different' or 못 잼, never 'same'."""
    fnt = m.get("font") or {}
    idt = fnt.get("identify") or {}
    keys = _role_keys(role, ["font_name", "bold"])
    item = f"자막 글꼴 {label}"
    if idt.get("status") == "measured":
        v = idt.get("verdict") or "unmeasured"
        st = FONT_VERDICT_STATUS.get(v, "unmeasured")
        top = idt.get("top")
        top_is_exp = str(top or "").replace(" ", "").lower() == str(idt.get("expected_canonical") or "").replace(" ", "").lower()
        reasons = "; ".join(idt.get("reasons") or [])
        if v == "identical":
            note = f"판정: 동일(identical) — {reasons}"
        elif v == "similar":
            note = ("판정: 유사(similar, 동일 확정 불가) — 같다고 쓰지 않음. " + reasons +
                    ("" if top_is_exp else f"; 가장 잘 맞는 후보는 {top}"))
        elif v == "different":
            note = f"판정: 다름(different) — {reasons}" + ("" if top_is_exp else f"; 가장 잘 맞는 후보 {top}")
        else:
            note = "판정 못 잼: " + (reasons or idt.get("reason") or "")
        cond = idt.get("conditions") or {}
        ce = idt.get("ceiling") or {}
        return b.add("caption.font", cap.id, item, CAT["font"], expected=cap.font_name,
                     observed={"verdict": v, "verdict_ko": idt.get("verdict_ko"), "iou_expected": idt.get("iou_expected"),
                               "margin": idt.get("margin"), "top": top, "top_verdict": idt.get("top_verdict"),
                               "ranked": (idt.get("ranked") or [])[:5],
                               "ceiling": {"p10": ce.get("p10"), "p50": ce.get("p50"), "noise_p90": ce.get("noise_p90"),
                                           "n": ce.get("n"), "size_bucket": ce.get("size_bucket"),
                                           "cached": idt.get("ceiling_cached")},
                               "conditions": {k: cond.get(k) for k in ("label", "crf", "x264_preset", "renderer",
                                                                       "background", "assumed", "source")}},
                     tolerance="identical(기대 글꼴 IoU ≥ 출력 인코딩 조건의 같은 글꼴 천장 p10, 차순위 대비 차이 > 잡음, "
                               "글자별 검사 통과)만 같다 · different(IoU < 천장 p10 − 잡음)는 다르다 · similar 는 못 잼",
                     status=st, keys=keys, evidence=ev, note=note)
    if fnt.get("status") == "measured" and fnt.get("scores"):
        # fallback: raw IoU vs the fonts_report ceiling (reference conditions, not this output's)
        best_iou = max((s.get("iou") or 0) for s in fnt["scores"])
        exp_iou = fnt.get("iou_expected") or 0
        margin = best_iou - exp_iou
        ceil = _font_ceiling(b, cap.font_name)
        glyph_h = (m.get("bbox_obs") or [0, 0, 0, 0])[3] / max(1, m.get("lines_found") or 1)
        why = (idt.get("reason") or "천장 실험(identify) 불가") + " → font_iou 원점수만으로는 같다고 판정하지 않음"
        if margin > 0.03 and best_iou >= ceil - 0.12:
            st, note = "different", f"다른 글꼴({fnt.get('best')})이 더 잘 맞음. {why}"
        elif exp_iou < 0.7 and glyph_h >= 30:
            st, note = "different", (f"기대 글꼴 IoU {exp_iou} ≪ 같은 글꼴 천장 {ceil} — 다른(대체) 글꼴로 그려진 것으로 보임. {why}")
        else:
            st, note = "unmeasured", why
        return b.add("caption.font", cap.id, item, CAT["font"], expected=cap.font_name,
                     observed={"method": "font_iou(대체 방법)", "best": fnt.get("best"), "iou_expected": exp_iou,
                               "scores": fnt.get("scores"), "same_font_ceiling_p10(fonts_report)": ceil,
                               "glyph_h": _r(glyph_h, 1)},
                     tolerance="대체 방법: 다른 글꼴이 0.03 넘게 더 잘 맞거나 IoU<0.7(글자 ≥30px) → 다르다, 그 밖은 못 잼(같다 없음)",
                     status=st, keys=keys, evidence=ev, note=note)
    return b.add("caption.font", cap.id, item, CAT["font"], expected=cap.font_name, observed=None,
                 status="unmeasured", keys=keys, evidence=ev,
                 note=fnt.get("reason") or idt.get("reason") or "글꼴 비교 못 함")


def _font_ceiling(b: RowBuilder, font_name: str) -> float:
    """Same-font IoU ceiling (p10) from presets/<name>/fonts_report.json (reference typography
    module); 0.85 when there is no report."""
    from ..util.jsonio import read_json

    if not hasattr(b, "_ceil_cache"):
        b._ceil_cache = read_json(b.ctx.preset.dir / "fonts_report.json") or {}
    rep = b._ceil_cache
    vals, allv = [], []
    for cond in (rep.get("ceilings") or {}).values():
        if not isinstance(cond, dict):
            continue
        for fname, ent in cond.items():
            if isinstance(ent, dict) and ent.get("p10") is not None:
                allv.append(float(ent["p10"]))
                if str(fname).replace(" ", "").lower() == str(font_name).replace(" ", "").lower():
                    vals.append(float(ent["p10"]))
    if vals:
        return round(min(vals), 3)
    if allv:
        return round(min(allv), 3)
    return 0.85


def _has_pos_override(b: RowBuilder, cap) -> bool:
    ax = b.pget(f"text.roles.{cap.role}.anchor.x", cap.anchor[0])
    ay = b.pget(f"text.roles.{cap.role}.anchor.y", cap.anchor[1])
    return abs(cap.anchor[0] - float(ax)) > 0.5 or abs(cap.anchor[1] - float(ay)) > 0.5


def _iou(a, b_):
    from . import rect_iou

    return rect_iou(a, b_)


def _median(v):
    v = [x for x in v if x is not None]
    if not v:
        return None
    v = sorted(v)
    n = len(v)
    return v[n // 2] if n % 2 else (v[n // 2 - 1] + v[n // 2]) / 2


def _mode(v):
    from collections import Counter

    v = [x for x in v if x]
    return Counter(v).most_common(1)[0][0] if v else None


# ----------------------------------------------------------------------------- video
def rows_video(b: RowBuilder, probes: dict) -> None:
    ctx = b.ctx
    vp = probes.get("video") or {}
    fr = 1.0 / ctx.fps
    err = vp.get("errors") or {}
    tr = vp.get("transitions")
    if tr is None:
        for c in ctx.resolved.clips[1:]:
            b.add("video.cuts", c.id, f"컷 위치 [{c.id}]", CAT["cut"], status="unmeasured",
                  note=err.get("transitions") or err.get("scan") or "영상 측정 실패")
    else:
        for bd in tr["boundaries"]:
            e, o = bd["expected"], bd["observed"]
            t_ok = o.get("t") is not None and (abs(o["t"] - e["t"]) <= fr + 1e-3 if e["type"] != "flash"
                                               else bd.get("timing_ok"))
            b.add("video.cuts", bd["clip_id"], f"컷 위치 [{bd['clip_id']} 시작]", CAT["cut"],
                  expected={"t": e["t"]}, observed={"t": o.get("t"), "type": o.get("type")},
                  tolerance="±1프레임(플래시는 플래시 구간 안)", status="same" if t_ok else "different",
                  evidence={"t": o.get("t") if o.get("t") is not None else e["t"]},
                  note="" if o.get("type") != "none" else "경계에서 화면 변화가 감지되지 않음")
            ttype = e["type"]
            keys = ["motion.transitions.default"] + ([f"motion.transitions.{ttype}.dur_s"] if ttype in ("flash", "crossfade") else []) + \
                (["motion.transitions.flash.color"] if ttype == "flash" else [])
            okk = bd["type_ok"] and (bd.get("timing_ok") is not False)
            note = ""
            if ttype == "flash" and o.get("type") == "flash" and e.get("color"):
                dcol = _cdist(o.get("color"), e.get("color"))
                note = f"플래시 최대 밝기 시 영상 영역 평균색 {o.get('color')} (기대 {e.get('color')})"
            b.add("video.transitions", bd["clip_id"], f"전환 종류·길이 [{bd['clip_id']}]", CAT["motion"],
                  expected={"type": ttype, "dur": e.get("dur")}, observed={"type": o.get("type"), "dur": o.get("dur"),
                                                                           "score": o.get("score")},
                  tolerance="종류 일치, 길이 ±2프레임", status="same" if okk else "different", keys=keys,
                  evidence={"t": o.get("t") or e["t"]}, note=note)
        unexpected = [x for x in tr.get("unexpected") or [] if not x.get("source_has_cut")]
        explained = [x for x in tr.get("unexpected") or [] if x.get("source_has_cut")]
        b.add("video.cuts", "unexpected", "계획에 없는 컷·플래시", CAT["cut"], expected=[],
              observed=unexpected, tolerance="0개(소스 자체의 컷은 제외)",
              status="same" if not unexpected else "different",
              evidence={"t": unexpected[0]["t"]} if unexpected else {},
              note=(f"소스 자체에 있던 컷 {len(explained)}개 제외" if explained else ""))
    # source mapping (which part of the source is on screen) and speed
    mp = vp.get("mapping")
    for c in ctx.resolved.clips:
        it = next((x for x in (mp or {}).get("clips", []) if x["clip_id"] == c.id), None)
        if it is None or it.get("status") != "measured":
            b.add("video.mapping", c.id, f"소스 구간 [{c.id}]", CAT["cut"],
                  expected={"src_in": c.src_in, "src_out": c.src_out}, observed=None, status="unmeasured",
                  note=(it or {}).get("reason") or err.get("mapping") or "측정 안 됨")
            continue
        tol = max(TOL["src_offset_s"], 1.1 / float(it.get("src_fps") or 30.0))
        off = it.get("offset_p50")
        b.add("video.mapping", c.id, f"소스 구간 [{c.id}]", CAT["cut"],
              expected={"src_in": c.src_in, "src_out": c.src_out, "source": c.source_path},
              observed={"offset_s": off, "samples": it.get("samples")}, tolerance=f"소스 시각 ±{tol:.3f}s(소스 1프레임 이상)",
              status="same" if off is not None and abs(off) <= tol else "different",
              evidence={"t": (it.get("samples") or [{}])[0].get("t")})
        if abs(float(c.speed or 1.0) - 1.0) > 1e-3 or it.get("speed_obs") is not None:
            so = it.get("speed_obs")
            if abs(float(c.speed or 1.0) - 1.0) > 1e-3 or (so is not None and abs(so - 1.0) > 0.1):
                b.add("video.speed", c.id, f"재생 속도 [{c.id}]", CAT["motion"], expected=c.speed, observed=so,
                      tolerance=f"±{int(TOL['speed_frac'] * 100)}%",
                      status="unmeasured" if so is None else ("same" if abs(so - c.speed) <= TOL["speed_frac"] * c.speed else "different"),
                      keys=["motion.speed.slowmo_factor"] if c.speed < 1 else [])
    # zoom
    zm = vp.get("zoom")
    if zm is None:
        b.add("video.zoom", "all", "확대(줌)", CAT["motion"], status="unmeasured", note=err.get("zoom") or "측정 실패")
    else:
        for it in zm["clips"]:
            c = next(x for x in ctx.resolved.clips if x.id == it["clip_id"])
            exp = it.get("expected")
            keys = ["motion.zoom.scale_to", "motion.zoom.dur_s", "motion.zoom.ease"] if exp else []
            if it.get("status") != "measured":
                b.add("video.zoom", c.id, f"확대(줌) [{c.id}]", CAT["motion"], expected=exp or "줌 없음", observed=None,
                      status="unmeasured", keys=keys, note=it.get("reason", ""), required=bool(exp))
                continue
            fin = it.get("zoom_ratio_corrected") or it["measured_final_ratio"]
            if exp:
                ratio_ok = abs(fin - it["expected_final_ratio"]) <= TOL["zoom_ratio"]
                t50_ok = (it.get("measured_t50") is not None and it.get("expected_t50") is not None and
                          abs(it["measured_t50"] - it["expected_t50"]) <= it["tolerance"]["t50_s"])
                obs = {k: it.get(k) for k in ("measured_final_ratio", "source_ratio", "zoom_ratio_corrected", "measured_t50",
                                              "measured_dur", "measured_ease", "measured_center_canvas", "max_abs_err")}
                b.add("video.zoom", c.id, f"확대(줌) [{c.id}]", CAT["motion"],
                      expected={"final_ratio": it["expected_final_ratio"], "t50": it.get("expected_t50"),
                                "dur": exp["dur"], "ease": exp["ease"], "center_canvas": exp.get("center_canvas")},
                      observed=obs, tolerance=f"배율 ±{TOL['zoom_ratio']}, 중간 시점 ±{it['tolerance']['t50_s']:.2f}s",
                      status="same" if ratio_ok and t50_ok else "different", keys=keys,
                      evidence={"t": it.get("measured_t50")},
                      note="ORB+RANSAC 유사변환 배율(출력 프레임끼리 비교, 소스 자체의 배율 변화로 나눔)")
            else:
                dev = it.get("measured_max_dev") or 0.0
                reliable = (it.get("n_samples") or 0) >= 10 and (it.get("median_inliers") or 0) >= 40 and \
                    (it.get("measured_spread") or 0) <= 0.02
                corr = it.get("zoom_ratio_corrected")
                if dev > 0.05 and corr is not None and abs(corr - 1.0) <= 0.05:
                    st = "same"            # the source itself changed scale (subject/camera motion)
                elif dev <= 0.05:
                    st = "same"
                elif dev > 0.08 and reliable and corr is not None and abs(corr - 1.0) > 0.08:
                    st = "different"
                else:
                    st = "unmeasured"
                b.add("video.zoom", c.id, f"줌 없음 확인 [{c.id}]", CAT["motion"], expected={"final_ratio": 1.0},
                      observed={"max_dev": dev, "final_ratio": it.get("measured_final_ratio"), "source_ratio": it.get("source_ratio"),
                                "corrected": corr, "median_inliers": it.get("median_inliers"), "spread": it.get("measured_spread")},
                      tolerance="배율 변화 ≤ 5% (8% 초과 + 안정 추정일 때만 다르다)", status=st, required=False,
                      note="소스 자체의 카메라 줌도 여기에 잡힘" + ("; 특징점 추정이 불안정해 판정 보류" if st == "unmeasured" else ""))
        mc = b.pget("motion.zoom.max_consecutive")
        if mc is not None:
            b.add("video.zoom", "max_consecutive", "연속 세그먼트 줌 횟수(같은 효과 쌓기 금지)", CAT["motion"],
                  expected={"max": mc}, observed={"measured": zm.get("max_consecutive_measured")}, tolerance="이하",
                  status="same" if (zm.get("max_consecutive_measured") or 0) <= int(mc) else "different",
                  keys=["motion.zoom.max_consecutive"])
        zoom_obs = [it["measured_final_ratio"] for it in zm["clips"] if it.get("expected") and it.get("status") == "measured"]
        b.style_row("video.zoom", "zoom_ref", "줌 배율·길이 (레퍼런스 대비)", CAT["motion"],
                    ["motion.zoom.scale_to", "motion.zoom.dur_s", "motion.zoom.ease"],
                    {"final_ratio": _median(zoom_obs)} if zoom_obs else None,
                    lambda o, r: abs(o["final_ratio"] - float(r.get("motion.zoom.scale_to", 1))) <= TOL["zoom_ratio"])
    # freeze
    fz = vp.get("freezes")
    if fz is None:
        b.add("video.freeze", "all", "정지(프리즈)", CAT["motion"], status="unmeasured", note=err.get("freezes") or "측정 실패")
    else:
        for e in fz["expected"]:
            o = e.get("observed")
            if e.get("distinguishable") is False:
                st, note = "unmeasured", "정지 직전 소스도 거의 움직이지 않아 정지 효과를 출력에서 구별할 수 없음"
            else:
                st = "same" if e.get("start_ok") and e.get("hold_ok") else "different"
                note = "" if o else "출력에서 반복 프레임 구간을 찾지 못함"
            b.add("video.freeze", e["clip_id"], f"정지(프리즈) [{e['clip_id']}]", CAT["motion"],
                  expected={"start": e["start"], "hold": e["hold"]},
                  observed={"presence": "present", "start": o["start"], "hold": _r(o["end"] - o["start"], 3),
                            "mean_diff": o.get("mean_diff")} if o else {"presence": "absent"},
                  tolerance="시작 ±2프레임, 길이 ±3프레임(소스가 정지한 구간은 허용)", status=st,
                  keys=["motion.freeze.hold_s"], evidence={"t": e["start"]}, note=note)
        un = [r for r in fz.get("unexpected") or [] if r.get("source_static") is not True]
        b.add("video.freeze", "unexpected", "계획에 없는 정지 화면", CAT["motion"], expected=[], observed=un,
              tolerance="0개(소스 자체가 멈춘 구간 제외)", status="same" if not un else "different", required=True,
              evidence={"t": un[0]["start"]} if un else {},
              note="소스도 정지해 있으면 제외; 판단 불가(소스 없음)면 포함")
        mx = b.pget("motion.freeze.max_per_video")
        n_obs = len([r for r in fz.get("runs") or [] if not any(r is x for x in [])])
        n_frz = len([e for e in fz["expected"] if e.get("observed")]) + len(un)
        if mx is not None:
            b.add("video.freeze", "max_per_video", "영상당 정지 횟수", CAT["motion"], expected={"max": mx},
                  observed={"count": n_frz}, tolerance="이하", status="same" if n_frz <= int(mx) else "different",
                  keys=["motion.freeze.max_per_video"])
        holds = [(e["observed"]["end"] - e["observed"]["start"]) for e in fz["expected"] if e.get("observed")]
        b.style_row("video.freeze", "freeze_ref", "정지 길이 (레퍼런스 대비)", CAT["motion"], ["motion.freeze.hold_s"],
                    {"hold_s": _r(_median(holds), 3)} if holds else None,
                    lambda o, r: abs(o["hold_s"] - float(r.get("motion.freeze.hold_s", 0))) <= 3 * fr)
    if tr is not None:
        fl = [bd["observed"].get("dur") for bd in tr["boundaries"] if bd["observed"].get("type") == "flash"]
        cf = [bd["observed"].get("dur") for bd in tr["boundaries"] if bd["observed"].get("type") == "crossfade"]
        types = [bd["observed"].get("type") for bd in tr["boundaries"]]
        b.style_row("video.transitions", "transitions_ref", "전환 종류·길이 (레퍼런스 대비)", CAT["motion"],
                    ["motion.transitions.default", "motion.transitions.flash.dur_s", "motion.transitions.flash.color",
                     "motion.transitions.crossfade.dur_s"],
                    {"mode": _mode(types), "flash_dur": _median(fl), "crossfade_dur": _median(cf)} if types else None,
                    lambda o, r: o["mode"] == r.get("motion.transitions.default"))
    if ctx.resolved.clips and any(abs(float(c.speed or 1) - 1) > 1e-3 for c in ctx.resolved.clips):
        sp = [x.get("speed_obs") for x in (mp or {}).get("clips", []) if x.get("speed_obs") is not None]
        slow = [s for s in sp if s < 0.95]
        b.style_row("video.speed", "speed_ref", "느린 재생 배율 (레퍼런스 대비)", CAT["motion"], ["motion.speed.slowmo_factor"],
                    {"slowmo": _median(slow)} if slow else None,
                    lambda o, r: abs(o["slowmo"] - float(r.get("motion.speed.slowmo_factor", 1))) <= 0.05)


# ----------------------------------------------------------------------------- decorations
def rows_decorations(b: RowBuilder, probes: dict) -> None:
    ctx = b.ctx
    vp = probes.get("video") or {}
    dd = {d["id"]: d for d in ((vp.get("decorations") or {}).get("items") or [])}
    for d in ctx.resolved.decorations:
        m = dd.get(d.id)
        kk = d.kind
        keys = [f"decorations.{kk}.{x}" for x in ("color", "size_px", "outline_px", "outline_color", "stroke_px")]
        if m is None or m.get("status") != "measured":
            for cid, it in (("decor.position", "장식 위치"), ("decor.brightness", "장식 밝기·깜빡임")):
                b.add(cid, d.id, f"{it} [{d.id}·{kk}]", CAT["deco"], status="unmeasured", keys=keys,
                      note=(m or {}).get("reason") or (vp.get("errors") or {}).get("decorations") or "측정 실패")
            continue
        pos = m.get("position")
        if pos:
            size = max((d.style or {}).get("size_px") or 0, max([k.get("w") or 0 for k in d.keyframes] + [0]))
            tol_abs = max(TOL["deco_abs_px"], 0.1 * size)
            ok = pos["abs_err_p90"] <= tol_abs and pos["path_err_p90"] <= TOL["deco_path_px"]
            b.add("decor.position", d.id, f"장식 위치·이동 경로 [{d.id}·{kk}]", CAT["deco"],
                  expected={"keyframes": d.keyframes, "anchor": "화살표=끝점(tip), 원/상자=중심 (캔버스 px)",
                            "resolution": [ctx.canvas_w, ctx.canvas_h]},
                  observed={"abs_err_p50": pos["abs_err_p50"], "abs_err_p90": pos["abs_err_p90"],
                            "path_err_p90": pos["path_err_p90"], "size": pos.get("size_obs"), "color": m.get("color_obs"),
                            "stroke_px": m.get("stroke_px_obs"), "track_sample": pos["track"][:6]},
                  tolerance=f"절대 오차 p90 ≤ {tol_abs:.0f}px, 경로 오차 p90 ≤ {TOL['deco_path_px']:.0f}px",
                  status="same" if ok else "different", keys=keys, evidence={"t": pos["track"][0][0] if pos["track"] else d.start},
                  note="위치는 밝기와 별도로 판정(보이는 프레임만)")
        else:
            b.add("decor.position", d.id, f"장식 위치·이동 경로 [{d.id}·{kk}]", CAT["deco"],
                  expected={"keyframes": d.keyframes}, observed={"visible_fraction": m.get("visible_fraction")},
                  status="different", keys=keys, note="장식 색 화소를 찾지 못함(보이지 않음)")
        br = m.get("brightness") or {}
        eh = float(d.blink_hz or 0.0)
        oh = br.get("blink_hz_obs")
        if eh <= 0:
            ok = (br.get("on_fraction") or 0) >= 0.9
            tol = "깜빡임 없음: 켜진 비율 ≥ 90%"
        else:
            ok = oh is not None and abs(oh - eh) <= TOL["blink_frac"] * eh
            tol = f"깜빡임 주파수 ±{int(TOL['blink_frac'] * 100)}%"
        b.add("decor.brightness", d.id, f"장식 밝기·깜빡임 [{d.id}·{kk}]", CAT["deco"],
              expected={"blink_hz": eh, "start": d.start, "end": d.end},
              observed={"blink_hz": oh, "on_fraction": br.get("on_fraction"), "on_events": br.get("on_events"),
                        "curve_sample": (br.get("curve") or [])[:12]},
              tolerance=tol, status="same" if ok else "different", keys=[f"decorations.{kk}.blink_hz"],
              evidence={"t": d.start}, note="밝기 곡선은 위치와 별도로 판정")
        b.style_row("decor.position", f"{d.id}_ref", f"장식 스타일 [{kk}] (레퍼런스 대비)", CAT["deco"],
                    keys + [f"decorations.{kk}.blink_hz"], {"color": m.get("color_obs"), "blink_hz": oh},
                    lambda o, r, kk=kk: (_cdist(o.get("color"), r.get(f"decorations.{kk}.color")) or 999) <= TOL["color_rgb"])


# ----------------------------------------------------------------------------- identity / residual / cover-up
def rows_identity(b: RowBuilder, probes: dict) -> None:
    ctx = b.ctx
    tp = probes.get("text") or {}
    idt = tp.get("identity")
    if tp.get("status") != "measured" or idt is None:
        b.add("identity.forbidden_text", "all", "레퍼런스 채널명·식별 문구 없음", CAT["identity"], status="unmeasured",
              keys=["identity_exclusions.forbidden_text"], note=tp.get("reason") or (tp.get("errors") or {}).get("identity", ""))
        b.add("clean.corners", "all", "모서리·하단 잔여 글자(출처 표기·워터마크·원어 자막)", CAT["logo"], status="unmeasured",
              note=tp.get("reason") or "")
    else:
        hits = idt.get("forbidden_hits") or []
        b.add("identity.forbidden_text", "all", "레퍼런스 채널명·식별 문구 없음", CAT["identity"],
              expected={"absent": idt.get("forbidden_terms")}, observed={"hits": hits, "frames_ocr": len(idt.get("sample_times") or [])},
              tolerance="0건", status="same" if not hits else "different", keys=["identity_exclusions.forbidden_text"],
              evidence={"t": hits[0]["t"]} if hits else {"t": None}, note="1초 간격 전체 프레임 + 각 클립 중간 OCR")
        groups = idt.get("leftover_groups") or []
        pers = [g for g in groups if g.get("persistent")]
        b.add("clean.corners", "all", "모서리·하단 잔여 글자(출처 표기·워터마크·원어 자막)", CAT["logo"],
              expected=[], observed={"persistent": pers, "single_hits": [g for g in groups if not g.get("persistent")][:8]},
              tolerance="같은 위치에 2회 이상 반복되는 글자 0건", status="same" if not pers else "different",
              evidence={"t": pers[0]["times"][0]} if pers else {},
              note="한 번만 잡힌 글자는 장면 속 글자/OCR 잡음일 수 있어 참고로만 표시")
    # logo templates of the reference channel
    tdir = b.pget("identity_exclusions.logo_templates_dir")
    b.add("identity.logo_templates", "all", "레퍼런스 로고 템플릿 없음", CAT["identity"],
          **_logo_template_check(ctx, tdir))
    # the footage itself must be a different recording from the reference's
    b.add("identity.reference_footage", "all", "레퍼런스와 같은 녹화(영상) 재사용 없음", CAT["identity"],
          **_reference_footage_check(ctx))


def _reference_footage_check(ctx) -> dict:
    """pHash keyframes of the OUTPUT video region vs warehouse/exclusions.jsonl reference_footage
    fingerprints (sourcing's own match rule).  No fingerprints -> 못 잼."""
    mode = getattr(ctx.resolved, "mode", "test")
    try:
        from ..sourcing import exclusions as ex
        from .probes_video import region_union
    except Exception as e:
        return {"status": "unmeasured", "required": mode == "production", "observed": None,
                "note": f"shortkit.sourcing.exclusions 사용 불가({type(e).__name__})"}
    x, y, w, h = region_union(ctx)
    try:
        kf = ex.keyframe_hashes(ctx.mp4, n=24, region={"x": x, "y": y, "w": w, "h": h})
        res = ex.check(keyframes=kf)
    except Exception as e:
        return {"status": "unmeasured", "required": mode == "production", "observed": None,
                "note": f"지문 비교 실패: {type(e).__name__}: {e}"[:300]}
    obs = {k: res.get(k) for k in ("excluded", "matched_ref_video_id", "distance", "matched_keyframes", "n_keyframes",
                                   "n_refs", "method")}
    obs["region"] = {"rect": [x, y, w, h], "resolution": [ctx.info.width, ctx.info.height]}
    st = "unmeasured" if res.get("excluded") is None else ("different" if res["excluded"] else "same")
    return {"expected": {"same_recording_as_reference": False}, "observed": obs, "status": st,
            "required": mode == "production", "tolerance": "pHash 거리 ≤ 10 인 키프레임 3장 미만",
            "note": res.get("note") or ""}


def _logo_template_check(ctx, tdir) -> dict:
    from .. import paths

    d = paths.absp(tdir) if tdir else None
    pngs = sorted(list(d.glob("*.png")) + list(d.glob("*.jpg"))) if d and d.is_dir() else []
    if not pngs:
        return {"expected": {"templates_dir": tdir}, "observed": None, "status": "unmeasured", "required": False,
                "keys": ["identity_exclusions.logo_templates_dir"],
                "note": "레퍼런스 로고 템플릿이 없어 로고 대조 못 함(레퍼런스 미확보)"}
    import cv2
    import numpy as np

    from .probes_video import grab

    hits = []
    T = ctx.info.duration
    tmpls = []
    for p in pngs[:20]:
        im = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE)
        if im is not None:
            tmpls.append((p.name, im))
    t = 0.5
    while t < T:
        g = cv2.cvtColor(grab(ctx.mp4, t), cv2.COLOR_RGB2GRAY)
        for name, im in tmpls:
            for s in (0.5, 0.75, 1.0, 1.25):
                tm = cv2.resize(im, (max(8, int(im.shape[1] * s)), max(8, int(im.shape[0] * s))))
                if tm.shape[0] >= g.shape[0] or tm.shape[1] >= g.shape[1]:
                    continue
                v = float(cv2.matchTemplate(g, tm, cv2.TM_CCOEFF_NORMED).max())
                if v >= 0.8:
                    hits.append({"t": round(t, 2), "template": name, "scale": s, "score": round(v, 3)})
                    break
        t += 1.0
    return {"expected": {"templates": [p.name for p in pngs[:20]]}, "observed": {"hits": hits},
            "status": "same" if not hits else "different", "keys": ["identity_exclusions.logo_templates_dir"],
            "tolerance": "정규화 상관 ≥ 0.8 인 위치 0건", "evidence": {"t": hits[0]["t"]} if hits else {}}


def rows_residual(b: RowBuilder, probes: dict) -> None:
    vp = probes.get("video") or {}
    rs = vp.get("residual")
    if rs is None:
        if any(c.delogo or c.inpaint or c.blur for c in b.ctx.resolved.clips):
            b.add("clean.residual", "all", "정리한 로고·오버레이 잔류", CAT["logo"], status="unmeasured",
                  note=(vp.get("errors") or {}).get("residual") or "측정 실패")
        return
    for i, it in enumerate(rs.get("items") or []):
        subj = f"{it['clip_id']}#{i}"
        if it.get("status") == "not_applicable":
            continue
        smp = [s for s in it.get("samples") or [] if s.get("visible")]
        best = max(smp, key=lambda s: (s.get("edge_ncc") or 0)) if smp else {}
        if it.get("status") != "measured":
            b.add("clean.residual", subj, f"정리한 영역 잔류 [{it['clip_id']}·{it['op']}]", CAT["logo"],
                  expected={"rect_src": it["rect_src"], "residual": False}, observed=None, status="unmeasured",
                  note=it.get("reason", ""))
            continue
        b.add("clean.residual", subj, f"정리한 영역 잔류 [{it['clip_id']}·{it['op']}]", CAT["logo"],
              expected={"rect_src": it["rect_src"], "src_range": it["src_range"], "residual": False},
              observed={"residual": it.get("residual"), "edge_ncc": best.get("edge_ncc"), "text_src": best.get("text_src"),
                        "text_out": best.get("text_out"), "rect_out": best.get("rect_out")},
              tolerance="원본 오버레이와 경계 NCC < 0.55, 같은 글자 OCR 없음",
              status="different" if it.get("residual") else "same",
              evidence={"t": best.get("t")}, note=it.get("note", "") +
              ("" if rs.get("clean_verify_available") else " (shortkit.clean.verify 없음 → 자체 측정)"))


def rows_cover_up(b: RowBuilder, probes: dict) -> None:
    ctx = b.ctx
    tp = probes.get("text") or {}
    vp = probes.get("video") or {}
    overlays = []
    for c in tp.get("captions") or []:
        if c.get("bbox_obs"):
            on = c.get("onset") if c.get("onset") is not None else c["start"]
            off = c.get("offset") if c.get("offset") is not None else c["end"]
            overlays.append({"id": c["id"], "kind": "caption", "start": on, "end": off, "bbox": c["bbox_obs"]})
    deco_cover = {d["id"]: d.get("protected_cover") or {} for d in (vp.get("decorations") or {}).get("items") or []}
    prot = vp.get("protected")
    checked_protected = False
    if prot:
        checked_protected = True
        from . import rect_intersection

        for i, p in enumerate(prot):
            hits = []
            for o in overlays:
                if p["rect"] is None or min(o["end"], p["end"]) - max(o["start"], p["start"]) <= 0:
                    continue
                inter = rect_intersection(o["bbox"], p["rect"])
                area = p["rect"][2] * p["rect"][3]
                if area > 0 and inter / area > 0.05:
                    hits.append({"overlay": o["id"], "kind": o["kind"], "covered_frac": round(inter / area, 3)})
            for did, pc in deco_cover.items():       # decorations: their own pixels, frame by frame
                v = pc.get(str(i)) or pc.get(i)
                if v and v["max_frac"] > 0.05:
                    hits.append({"overlay": did, "kind": "decoration", "covered_frac": v["max_frac"], "t": v["t"]})
            vis = p.get("visible_frac")
            cropped = vis is not None and vis < 0.5
            b.add("cover_up.protected", f"{p['clip_id']}#{i}", f"보호 영역 가림·잘림 [{p.get('label')}·{p['clip_id']}]", CAT["cover_up"],
                  expected={"rect": p["rect"], "resolution": [ctx.canvas_w, ctx.canvas_h], "t": [p["start"], p["end"]],
                            "covered": False, "visible_frac_min": 0.5},
                  observed={"hits": hits, "visible_frac": vis}, tolerance="보호 영역 면적의 5% 초과 가림 0건, 화면 안에 50% 이상",
                  status="same" if not hits and not cropped else "different", evidence={"t": p["start"]},
                  note="보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), "
                       "자막·장식 bbox 는 출력에서 측정" + ("; 보호 대상이 화면 밖으로 잘림" if cropped else ""))
    else:
        b.add("cover_up.protected", "none", "보호 영역(얼굴·손·물체) 가림", CAT["cover_up"], status="unmeasured",
              required=False, note="plan 에 보호 영역(sources[].protected) 선언 없음")
    try:
        from .probes_video import analyze_faces

        fres = analyze_faces(ctx, overlays) if ctx.options.get("faces", True) else {"status": "unmeasured", "reason": "비활성"}
    except Exception as e:
        fres = {"status": "unmeasured", "reason": f"{type(e).__name__}: {e}"}
    probes.setdefault("video", {})["faces"] = fres
    if fres.get("status") == "measured":
        hits = fres.get("covered") or []
        b.add("cover_up.faces", "detector", "얼굴 가림(얼굴 검출)", CAT["cover_up"], expected={"covered": 0},
              observed={"detector": fres.get("detector"), "frames": fres.get("frames"), "hits": hits[:10]},
              tolerance="얼굴 면적 10% 초과 가림 0건", status="same" if not hits else "different",
              evidence={"t": hits[0]["t"]} if hits else {})
    else:
        b.add("cover_up.faces", "detector", "얼굴 가림(얼굴 검출)", CAT["cover_up"], status="unmeasured",
              required=not checked_protected, note=(fres.get("reason") or "") +
              (" — plan 보호 영역 검사로 대체" if checked_protected else " — 보호 영역 선언도 없어 가림 여부를 확인할 수 없음"))


# ----------------------------------------------------------------------------- audio
def rows_audio(b: RowBuilder, probes: dict) -> None:
    ctx = b.ctx
    ap = probes.get("audio") or {}
    res = ctx.resolved
    if ap.get("status") == "no_audio":
        b.add("audio.loudness", "mix", "음량", CAT["loudness"], status="different", observed="오디오 트랙 없음",
              expected={"integrated_lufs": res.audio.target_lufs})
        return
    if ap.get("status") != "measured":
        for cid, it, cat in (("audio.bgm", "BGM", CAT["music"]), ("audio.original", "원음", CAT["original"]),
                             ("audio.sfx.placement", "효과음", CAT["sfx_count"]), ("audio.loudness", "음량", CAT["loudness"])):
            b.add(cid, "all", it, cat, status="unmeasured", note=str(ap.get("errors") or ap.get("reason") or "오디오 측정 실패"))
        return
    bgm = res.audio.bgm
    bi = ap.get("bgm") or {}
    bkeys = [f"audio.bgm.{k}" for k in ("track_id", "title", "version", "tempo_ratio", "section_start_s", "gain_db",
                                          "fade_in_s", "fade_out_s", "loop")]
    if bi.get("status") == "not_planned":
        b.add("audio.bgm", "file", "BGM", CAT["music"], expected="BGM 없음(계획)", observed=None, status="unmeasured",
              required=False, note="계획에 BGM 이 없어 출력에서 찾을 파일이 없음(모르는 음악의 부재는 증명 못 함)")
    elif bi.get("status") != "measured":
        b.add("audio.bgm", "file", "BGM 곡·버전 일치", CAT["music"], expected={"path": bgm.path if bgm else None},
              observed=None, status="unmeasured", keys=bkeys[:3], note=bi.get("reason", ""))
    else:
        found = bool(bi.get("found"))
        pth = str(bgm.path or "")
        if "/analysis/" in pth or "/stems/" in pth or pth.startswith("presets/"):
            b.add("audio.bgm", "clean_file", "BGM 은 깨끗한 음원(레퍼런스에서 분리한 스템 금지)", CAT["music"],
                  expected="음원 창고의 깨끗한 파일", observed={"path": pth}, status="different",
                  note="레퍼런스 분석 폴더/스템 경로의 파일을 BGM 으로 사용함")
        b.add("audio.bgm", "file", "BGM 곡·버전 일치(파형 대조)", CAT["music"],
              expected={"path": bgm.path, "track_id": bgm.track_id},
              observed={"presence": "present" if found else "absent", "waveform_ncc": bi.get("waveform_ncc"),
                        "local_match": bi.get("local_match"),
                        "tempo_candidates": bi.get("tempo_candidates")},
              tolerance="0.25초 창별 파형 상관 q95 ≥ 0.7 (무관한 음악 < 0.5)", status="same" if found else "different",
              keys=["audio.bgm.track_id", "audio.bgm.title", "audio.bgm.version"],
              note="출력 믹스에서 계획한 음악 파일의 파형을 찾음" if found else "계획한 음악 파일의 파형이 출력에서 확인되지 않음(다른 곡/버전?)")
        if not found:
            for sub, it_ in (("tempo", "BGM 속도(버전)"), ("section", "BGM 사용 구간"), ("ducking", "BGM 덕킹·정적")):
                b.add("audio.bgm" if sub != "ducking" else "audio.ducking", sub, it_, CAT["music"], status="unmeasured",
                      note="계획한 BGM 을 출력에서 찾지 못해 측정 불가")
            b.style_row("audio.bgm", "bgm_ref", "BGM 곡·버전·속도·구간 (레퍼런스 대비)", CAT["music"], bkeys, None,
                        lambda o, r: False, note="출력에서 BGM 을 찾지 못함")
            bgm = None
    if bgm is not None and bi.get("status") == "measured":
        to = bi.get("tempo_obs")
        b.add("audio.bgm", "tempo", "BGM 속도(버전)", CAT["music"], expected=bgm.tempo_ratio, observed=to,
              tolerance=f"±{TOL['bgm_tempo']}",
              status="unmeasured" if to is None else ("same" if abs(to - float(bgm.tempo_ratio)) <= TOL["bgm_tempo"] else "different"),
              keys=["audio.bgm.tempo_ratio", "audio.bgm.version"],
              note=f"후보 템포 상위: {(bi.get('search') or {}).get('top_tempi')}")
        so = bi.get("section_start_obs")
        ru = bi.get("runner_up_section")
        q_best = (bi.get("local_match") or {}).get("q95") or 0.0
        n_best = bi.get("waveform_ncc") or 0.0
        equiv = ru is not None and (ru.get("q95") or 0) >= q_best - 0.01 and (ru.get("ncc") or 0) >= n_best - 0.005
        exp_s = float(bgm.section_start_s)
        if so is None or not found:
            st = "unmeasured"
        elif abs(so - exp_s) <= TOL["bgm_section_s"]:
            st = "same"
        elif equiv and abs(ru["section_start_s"] - exp_s) <= TOL["bgm_section_s"]:
            st = "same"
        else:
            st = "different"
        b.add("audio.bgm", "section", "BGM 사용 구간", CAT["music"],
              expected={"section_start_s": bgm.section_start_s},
              observed={"section_start_s": so, "used_section": bi.get("used_section_obs"), "runner_up": ru},
              tolerance=f"±{TOL['bgm_section_s']}s (같은 곡 다른 부분은 불일치)", status=st,
              keys=["audio.bgm.section_start_s"], evidence={"t": 0.0},
              note=("파형이 거의 똑같이 반복되는 곡이라 다른 위치도 같은 소리(상관 차 ≤ 0.005) — 구간 구별 한계" if equiv else ""))
        # fades
        curve = bi.get("gain_curve_fine") or []
        if curve:
            span = bi.get("audible_span_obs") or [0, 0]
            fi = _fade_len(curve, start=True)
            fo = _fade_len(curve, start=False)
            ok = (fi is None or abs(fi - bgm.fade_in_s) <= TOL["fade_s"] + 0.05) and (fo is None or abs(fo - bgm.fade_out_s) <= TOL["fade_s"] + 0.05)
            b.add("audio.bgm", "fades", "BGM 페이드 인/아웃", CAT["music"],
                  expected={"fade_in_s": bgm.fade_in_s, "fade_out_s": bgm.fade_out_s},
                  observed={"fade_in_s": fi, "fade_out_s": fo, "audible_span": span},
                  tolerance=f"±{TOL['fade_s'] + 0.05:.2f}s", status="same" if ok else "different",
                  keys=["audio.bgm.fade_in_s", "audio.bgm.fade_out_s"], required=False, note="0.05초 창 LS 이득 곡선에서 측정")
        b.style_row("audio.bgm", "bgm_ref", "BGM 곡·버전·속도·구간 (레퍼런스 대비)", CAT["music"], bkeys,
                    {"tempo": to, "section_start_s": so} if to is not None else None,
                    lambda o, r: abs(o["tempo"] - float(r.get("audio.bgm.tempo_ratio") or 1)) <= TOL["bgm_tempo"] and
                    abs(o["section_start_s"] - float(r.get("audio.bgm.section_start_s") or 0)) <= TOL["bgm_section_s"],
                    note="레퍼런스 곡 식별(제목·버전·속도·구간)이 필요")
        _rows_ducking(b, ap, bi)
    _rows_original(b, ap)
    _rows_sfx(b, ap)
    # loudness
    ld = ap.get("loudness") or {}
    tol_lu = float(b.pget("audio.loudness.tolerance_lu", 1.0) or 1.0)
    il, tp_ = ld.get("integrated_lufs"), ld.get("true_peak_db")
    if il is None:
        b.add("audio.loudness", "mix", "통합 음량(LUFS)·트루피크", CAT["loudness"], status="unmeasured",
              note=(ap.get("errors") or {}).get("loudness", "ebur128 측정 실패"))
    else:
        ok = abs(il - res.audio.target_lufs) <= tol_lu and (tp_ is None or tp_ <= res.audio.true_peak_db + 0.5)
        b.add("audio.loudness", "mix", "통합 음량(LUFS)·트루피크", CAT["loudness"],
              expected={"integrated_lufs": res.audio.target_lufs, "true_peak_db": res.audio.true_peak_db},
              observed=ld, tolerance=f"±{tol_lu} LU, 트루피크 ≤ 목표+0.5 dB", status="same" if ok else "different",
              keys=["audio.loudness.integrated_lufs", "audio.loudness.true_peak_db"])
        b.style_row("audio.loudness", "loudness_ref", "음량 (레퍼런스 대비)", CAT["loudness"],
                    ["audio.loudness.integrated_lufs", "audio.loudness.true_peak_db"], {"integrated_lufs": il},
                    lambda o, r: abs(o["integrated_lufs"] - float(r.get("audio.loudness.integrated_lufs"))) <= tol_lu)


def _fade_len(curve, start: bool) -> float | None:
    pts = [(t, v) for t, v in curve if v is not None]
    if len(pts) < 4:
        return None
    seq = pts if start else list(reversed(pts))
    t0 = seq[0][0]
    # first point within 1.5 dB of plateau (0 dB)
    for t, v in seq:
        if v >= -1.5:
            return round(abs(t - t0), 3) if abs(t - t0) > 0.06 else 0.0
    return None


def _rows_ducking(b: RowBuilder, ap: dict, bi: dict) -> None:
    ctx = b.ctx
    bgm = ctx.resolved.audio.bgm
    from . import in_ranges, overlaps

    exp = [tuple(x) for x in (bgm.duck_ranges or [])]
    sil = [tuple(x) for x in (bgm.silences or [])]
    obs = [tuple(x) for x in bi.get("ducked_ranges_obs") or []]
    att = float(b.pget("audio.ducking.attack_s", 0.08) or 0.08)
    rel = float(b.pget("audio.ducking.release_s", 0.3) or 0.3)
    pad = att + rel + 0.12
    # 1) every planned duck is present
    cover = []
    for a, c in exp:
        core = (a + att + 0.05, c - 0.05)
        tot = max(1e-6, core[1] - core[0])
        cov = sum(overlaps(core[0], core[1], x, y) for x, y in obs) / tot if core[1] > core[0] else 1.0
        cover.append(round(cov, 3))
    ok1 = all(cv >= 0.7 for cv in cover)
    b.add("audio.ducking", "planned", "보존 대사 구간의 BGM 덕킹", CAT["music"],
          expected={"duck_ranges": [list(x) for x in exp], "depth_db": b.pget("audio.ducking.depth_db")},
          observed={"ducked_ranges": [list(x) for x in obs], "coverage": cover},
          tolerance="각 구간 70% 이상 덕킹", status="same" if ok1 else "different",
          keys=["audio.ducking.depth_db", "audio.ducking.attack_s", "audio.ducking.release_s"],
          evidence={"t": exp[0][0]} if exp else {}, required=bool(exp))
    # 2) no ducking outside kept dialogue (SFX or cuts are never a reason to duck)
    T = ctx.info.duration
    fades = [(0.0, float(bgm.fade_in_s or 0) + 0.2), (T - float(bgm.fade_out_s or 0) - 0.2, T + 1.0)]
    outside = [(x, y) for x, y in obs if not any(overlaps(x, y, a - pad, c + pad) > 0 for a, c in exp)
               and not any(overlaps(x, y, a - 0.1, c + 0.1) >= 0.8 * (y - x) for a, c in sil)
               and not any(overlaps(x, y, a, c) >= 0.8 * (y - x) for a, c in fades)]
    sfx_t = [d["t"] for d in ((ap.get("sfx") or {}).get("detections") or [])]
    cut_t = [c.out_start for c in ctx.resolved.clips[1:]]
    why = []
    for x, y in outside:
        near = [f"효과음 {t:.2f}s" for t in sfx_t if x - 0.3 <= t <= y] + [f"컷 {t:.2f}s" for t in cut_t if x - 0.3 <= t <= y]
        why.append({"range": [x, y], "near": near})
    b.add("audio.ducking", "outside", "보존 대사 밖에서 BGM 낮춤 없음(효과음·컷 때문에 덕킹 금지)", CAT["music"],
          expected={"ducking_only_in": [list(x) for x in exp]}, observed={"ducking_outside": why},
          tolerance="0건", status="same" if not outside else "different",
          keys=["audio.ducking.only_under_kept_dialogue"], evidence={"t": outside[0][0]} if outside else {})
    # 3) ducking only where original audio is actually audible
    pres = [tuple(x) for x in ((ap.get("originals") or {}).get("present_ranges_obs") or [])]
    no_orig = [(x, y) for x, y in obs if not any(overlaps(x, y, a - pad, c + pad) > 0 for a, c in pres)
               and not any(overlaps(x, y, a - 0.1, c + 0.1) >= 0.8 * (y - x) for a, c in sil)
               and not any(overlaps(x, y, a, c) >= 0.8 * (y - x) for a, c in fades)]
    b.add("audio.ducking", "orig_present", "덕킹은 원음이 실제로 들리는 곳에서만", CAT["music"],
          expected="덕킹 구간 ⊆ 원음 존재 구간", observed={"ducks_without_original": [list(x) for x in no_orig],
                                                   "original_present": [list(x) for x in pres]},
          tolerance="0건", status="same" if not no_orig else "different", evidence={"t": no_orig[0][0]} if no_orig else {})
    # 4) depth
    fine = bi.get("gain_curve_fine") or []
    inside = [v for t, v in fine if v is not None and any(a + att + 0.1 <= t <= c - 0.1 for a, c in exp)]
    if exp:
        d_obs = _median(inside)
        d_exp = -float(b.pget("audio.ducking.depth_db", 10.0))
        b.add("audio.ducking", "depth", "덕킹 깊이", CAT["music"], expected={"depth_db": d_exp},
              observed={"depth_db": _r(d_obs, 2)}, tolerance=f"±{TOL['duck_depth_db']} dB",
              status="unmeasured" if d_obs is None else ("same" if abs(d_obs - d_exp) <= TOL["duck_depth_db"] else "different"),
              keys=["audio.ducking.depth_db"])
        b.style_row("audio.ducking", "ducking_ref", "덕킹 깊이·속도 (레퍼런스 대비)", CAT["music"],
                    ["audio.ducking.depth_db", "audio.ducking.attack_s", "audio.ducking.release_s"],
                    {"depth_db": _r(d_obs, 2)} if d_obs is not None else None,
                    lambda o, r: abs(o["depth_db"] + float(r.get("audio.ducking.depth_db"))) <= TOL["duck_depth_db"])
    # 5) silences
    sil_obs = [tuple(x) for x in bi.get("silent_ranges_obs") or []]
    for i, (a, c) in enumerate(sil):
        core = [v for t, v in fine if v is not None and a + 0.1 <= t <= c - 0.1]
        mx = max(core) if core else None
        b.add("audio.silence", f"s{i}", f"의도적 정적 {a:.2f}–{c:.2f}s (BGM 없음)", CAT["music"],
              expected={"range": [a, c], "bgm_db_rel": f"≤ {TOL['silence_db']}"}, observed={"max_bgm_db_rel": _r(mx, 1)},
              tolerance=f"BGM ≤ {TOL['silence_db']} dB", status="unmeasured" if mx is None else
              ("same" if mx <= TOL["silence_db"] else "different"), keys=["audio.silence.fade_s"], evidence={"t": a})
    span = bi.get("audible_span_obs")
    fo = float(bgm.fade_out_s or 0)
    unexpected_sil = [(x, y) for x, y in sil_obs if not any(overlaps(x, y, a - 0.15, c + 0.15) > 0.5 * (y - x) for a, c in sil)
                      and (span is None or (x > span[0] + 0.1 and y < span[1] - fo - 0.1))]
    b.add("audio.silence", "unexpected", "계획에 없는 BGM 끊김", CAT["music"], expected=[list(x) for x in sil],
          observed=[list(x) for x in unexpected_sil], tolerance="0건", status="same" if not unexpected_sil else "different",
          evidence={"t": unexpected_sil[0][0]} if unexpected_sil else {})


def _rows_original(b: RowBuilder, ap: dict) -> None:
    ctx = b.ctx
    og = ap.get("originals") or {}
    wins = og.get("windows") or []
    kept = [tuple(x) for x in og.get("expected_kept") or []]
    fade = float(b.pget("audio.original.fade_s", 0.04) or 0.04)
    tracks = og.get("tracks") or []
    silent_src = [t["clip_id"] for t in tracks if not t.get("has_audio")]
    for i, o in enumerate(ctx.resolved.audio.originals):
        ws = [w for w in wins if w["clip_id"] == o.clip_id and o.out_start + 0.15 <= w["t"] <= o.out_end - 0.15]
        if not ws:
            b.add("audio.original", f"kept{i}", f"보존 원음 [{o.clip_id} {o.out_start:.2f}–{o.out_end:.2f}s]", CAT["original"],
                  expected={"present": True, "gain_db": o.gain_db}, observed=None, status="unmeasured",
                  note="소스 오디오를 읽지 못했거나 구간이 너무 짧음" + (" (소스에 소리 없음)" if o.clip_id in silent_src else ""))
            continue
        frac = sum(1 for w in ws if w["present"]) / len(ws)
        g = _median([w.get("gain_db_mix_scale") for w in ws if w["present"]])
        ok = frac >= TOL["orig_present_frac"]
        b.add("audio.original", f"kept{i}", f"보존 원음 [{o.clip_id} {o.out_start:.2f}–{o.out_end:.2f}s]", CAT["original"],
              expected={"present": True, "gain_db": o.gain_db, "stem": o.stem, "reason": o.reason},
              observed={"presence": "present" if frac >= TOL["orig_present_frac"] else ("absent" if frac == 0 else "partial"),
                        "present_fraction": _r(frac, 3), "gain_db_mix_scale": _r(g, 2)},
              tolerance=f"창의 {int(TOL['orig_present_frac'] * 100)}% 이상에서 원음 확인", status="same" if ok else "different",
              keys=["audio.original.keep_gain_db", "audio.original.fade_s"], evidence={"t": o.out_start},
              note="원음 이득은 BGM 기준 믹스 척도 추정(BGM 없으면 없음)")
    # music embedded in the source must be removed from kept original sound (separate first)
    srcs = {x.get("id"): x for x in ((ctx.plan or {}).get("sources") or [])}
    for i, o in enumerate(ctx.resolved.audio.originals):
        c = next((x for x in ctx.resolved.clips if x.id == o.clip_id), None)
        src = srcs.get(c.source_id) if c is not None else None
        hem = (src or {}).get("has_embedded_music")
        if hem is False:
            st, note = "same", "소스에 음악 없음(plan 기록)"
        elif hem is None:
            st, note = "unmeasured", "소스에 음악이 섞여 있는지 판정 기록 없음(plan sources[].has_embedded_music)"
        elif o.stem == "raw":
            st, note = "different", "음악이 섞인 원본 소리를 분리하지 않고 그대로 사용"
        else:
            st, note = "unmeasured", "보컬 분리 스템 사용 — 분리 품질은 사람이 들어서 확인해야 함(청취 확인 안 함)"
        b.add("audio.original", f"music{i}", f"보존 원음 속 음악 제거 [{o.clip_id}]", CAT["original"],
              expected={"embedded_music_removed": True}, observed={"has_embedded_music": hem, "stem": o.stem, "path": o.path},
              status=st, keys=["audio.original.remove_embedded_music"], note=note, required=(hem is None or st == "different"))
    leak = [w for w in wins if w["present"] and not any(a - fade - 0.2 <= w["t"] <= c + fade + 0.2 for a, c in kept)]
    leak_r = [[_r(w["t"] - 0.125), _r(w["t"] + 0.125)] for w in leak]
    b.add("audio.original", "off", "원음 OFF 구간에 원음 없음(기본 OFF)", CAT["original"],
          expected={"kept_only": [list(x) for x in kept]},
          observed={"presence_outside_kept": "present" if leak else "absent", "leak_windows": leak_r[:20],
                    "sources_without_audio": silent_src},
          tolerance="0개 창", status="same" if not leak else "different", keys=["audio.original.default"],
          evidence={"t": leak[0]["t"]} if leak else {},
          note=("소스에 소리가 없는 클립: " + ", ".join(silent_src)) if silent_src else "")
    gs = [w.get("gain_db_mix_scale") for w in wins if w["present"] and w.get("kept_expected")]
    b.style_row("audio.original", "orig_ref", "보존 원음 크기·경계 (레퍼런스 대비)", CAT["original"],
                ["audio.original.keep_gain_db", "audio.original.fade_s"],
                {"gain_db": _r(_median(gs), 2)} if gs and _median(gs) is not None else None,
                lambda o, r: abs(o["gain_db"] - float(r.get("audio.original.keep_gain_db"))) <= 3.0)


def _rows_sfx(b: RowBuilder, ap: dict) -> None:
    ctx = b.ctx
    sf = ap.get("sfx") or {}
    dets = list(sf.get("detections") or [])
    plan_sfx = {s.get("id"): s for s in ((ctx.plan or {}).get("sfx") or [])}
    max_off = float(b.pget("audio.sfx.max_event_offset_s", 0.3) or 0.3)
    used = set()
    no_event = []
    for s in ctx.resolved.audio.sfx:
        ps = plan_sfx.get(s.id) or {}
        ev_kind = ((ps.get("event") or {}).get("kind") or "")
        if s.path is None:
            b.add("audio.sfx.placement", s.id, f"효과음 [{s.id}·{s.type}] 위치", CAT["sfx_count"],
                  expected={"t": s.t, "type": s.type}, observed=None, status="unmeasured",
                  note=f"효과음 파일 미확보(sfx_map: {s.map_status}) — 출력에서 대조할 파일 없음")
            b.add("audio.sfx.offset", s.id, f"효과음 [{s.id}] 사건과의 시차", CAT["sfx_offset"],
                  expected={"event_t": s.event_t, "max": max_off}, observed=None, status="unmeasured",
                  keys=["audio.sfx.max_event_offset_s"], note="출력에서 효과음 시각을 측정하지 못함")
            continue
        cand = [(abs(d["t"] - s.t), k) for k, d in enumerate(dets) if k not in used and d["type"] == s.type
                and d.get("file") == s.path and abs(d["t"] - s.t) <= 0.25]
        if not cand:
            cand = [(abs(d["t"] - s.t), k) for k, d in enumerate(dets) if k not in used and d["type"] == s.type
                    and abs(d["t"] - s.t) <= 0.25]
        if cand:
            _, k = min(cand)
            used.add(k)
            d = dets[k]
            ok_t = abs(d["t"] - s.t) <= TOL["sfx_t_s"]
            gm = d.get("gain_db_mix_scale")
            b.add("audio.sfx.placement", s.id, f"효과음 [{s.id}·{s.type}] 위치", CAT["sfx_count"],
                  expected={"t": s.t, "type": s.type}, observed={"t": d["t"], "ncc": _r(d["ncc"], 3)},
                  tolerance=f"같은 파일, 시각 ±{TOL['sfx_t_s']}s", status="same" if ok_t else "different",
                  evidence={"t": d["t"]})
            b.add("audio.sfx.placement", f"{s.id}:gain", f"효과음 [{s.id}·{s.type}] 크기", CAT["sfx_count"],
                  expected={"gain_db": s.gain_db}, observed={"gain_db_mix_scale": gm, "reference": d.get("gain_reference")},
                  tolerance=f"±{TOL['sfx_gain_db']} dB (같은 순간 BGM 대비로 환산)",
                  status="unmeasured" if gm is None else ("same" if abs(gm - s.gain_db) <= TOL["sfx_gain_db"] else "different"),
                  keys=["audio.sfx.gain_db_default"], evidence={"t": d["t"]}, required=False,
                  note="" if gm is not None else "BGM 이 없어 믹스 안 크기를 환산할 기준이 없음")
            off = d["t"] - s.event_t
            b.add("audio.sfx.offset", s.id, f"효과음 [{s.id}] 사건과의 시차 ({s.event_desc[:20]})", CAT["sfx_offset"],
                  expected={"event_t": s.event_t, "max_abs_offset": max_off}, observed={"sfx_t": d["t"], "offset": _r(off, 3)},
                  tolerance=f"|효과음 − 사건| ≤ {max_off}s", status="same" if abs(off) <= max_off + 1e-6 else "different",
                  keys=["audio.sfx.max_event_offset_s"], evidence={"t": d["t"]},
                  note="사건 시각은 plan 의 선언(화면 사건), 효과음 시각은 출력에서 측정")
            if ev_kind == "cut" or not s.event_desc:
                no_event.append({"t": d["t"], "type": s.type, "why": "사건 없음/컷이 사건"})
        else:
            b.add("audio.sfx.placement", s.id, f"효과음 [{s.id}·{s.type}] 위치·크기", CAT["sfx_count"],
                  expected={"t": s.t, "type": s.type, "gain_db": s.gain_db}, observed=None, status="different",
                  evidence={"t": s.t}, note="출력에서 이 효과음을 찾지 못함(정합 필터 NCC < 0.45)")
            b.add("audio.sfx.offset", s.id, f"효과음 [{s.id}] 사건과의 시차", CAT["sfx_offset"],
                  expected={"event_t": s.event_t, "max": max_off}, observed=None, status="unmeasured",
                  keys=["audio.sfx.max_event_offset_s"], note="출력에서 효과음을 찾지 못해 시차 측정 불가")
    extra = [d for k, d in enumerate(dets) if k not in used]
    for d in extra:
        no_event.append({"t": d["t"], "type": d["type"], "file": d.get("file"), "ncc": _r(d["ncc"], 3),
                         "why": "계획(사건 목록)에 없는 효과음"})
    unexpl = ap.get("unexplained_onsets") or []
    b.add("audio.sfx.no_event", "all", "사건 없는 효과음 0", CAT["sfx_no_event"], expected=0,
          observed={"count": len(no_event), "items": no_event}, tolerance="0개",
          status="same" if not no_event else "different", keys=["audio.sfx.require_event"],
          evidence={"t": no_event[0]["t"]} if no_event else {})
    b.add("audio.sfx.unexplained", "all", "알려진 소리로 설명되지 않는 소리 시작점", CAT["sfx_no_event"], expected=0,
          observed={"count": len(unexpl), "onsets": unexpl[:20]}, tolerance="0개",
          status="same" if not unexpl else "different", evidence={"t": unexpl[0]["t"]} if unexpl else {},
          note="BGM·원음·검출된 효과음을 뺀 잔차에서 급격한 에너지 상승(보존 원음 구간 제외)")
    # counts per type: plan vs output
    from collections import Counter

    exp_c = Counter(s.type for s in ctx.resolved.audio.sfx)
    obs_c = Counter(d["type"] for d in dets)
    for t in sorted(set(exp_c) | set(obs_c)):
        b.add("audio.sfx.count", t, f"효과음 개수 [{t}] (계획 대비)", CAT["sfx_count"], expected=exp_c.get(t, 0),
              observed=obs_c.get(t, 0), tolerance="같은 개수", status="same" if exp_c.get(t, 0) == obs_c.get(t, 0) else "different",
              evidence={"t": next((d["t"] for d in dets if d["type"] == t), None)})
    # counts per type vs the reference catalog range for this format
    cat = _catalog(b)
    mode = getattr(ctx.resolved, "mode", "test")
    if not cat or cat.get("status") != "measured" or not cat.get("types"):
        b.add("audio.sfx.count", "catalog", "효과음 종류별 개수 (레퍼런스 포맷 범위 대비)", CAT["sfx_count"], kind="style_vs_reference",
              expected="레퍼런스 카탈로그의 포맷별 p10–p90", observed=dict(obs_c), status="unmeasured",
              keys=["audio.sfx.catalog"], required=mode == "production", reference="못 잼",
              note="sfx_catalog.json 미측정: " + str((cat or {}).get("blocker") or "카탈로그 없음"))
    else:
        fmt = ctx.resolved.format_id
        for tt in cat["types"]:
            tid = tt.get("type_id")
            pv = tt.get("per_video_count") or {}
            st = (pv.get("by_format") or {}).get(fmt) or pv.get("overall") or {}
            n = obs_c.get(tid, 0)
            if not st or not st.get("n"):
                status = "unmeasured"
            else:
                status = "same" if st.get("p10", 0) <= n <= st.get("p90", 0) else "different"
            b.add("audio.sfx.count", f"catalog:{tid}", f"효과음 개수 [{tid}] (레퍼런스 {fmt} 범위 대비)", CAT["sfx_count"],
                  kind="style_vs_reference", reference=st or "못 잼", expected={"p10": st.get("p10"), "p90": st.get("p90")},
                  observed=n, tolerance="p10 ≤ 개수 ≤ p90", status=status, keys=["audio.sfx.catalog"],
                  required=mode == "production")
        unknown = [t for t in obs_c if t not in {x.get("type_id") for x in cat["types"]}]
        if unknown:
            b.add("audio.sfx.count", "catalog:unknown", "카탈로그에 없는 효과음 종류", CAT["sfx_count"], kind="style_vs_reference",
                  expected=[], observed=unknown, status="different", keys=["audio.sfx.catalog"])
    gains = [d.get("gain_db_mix_scale") for d in dets if d.get("gain_db_mix_scale") is not None]
    b.style_row("audio.sfx.placement", "sfx_gain_ref", "효과음 크기 (레퍼런스 대비)", CAT["sfx_count"],
                ["audio.sfx.gain_db_default"], {"gain_db": _r(_median(gains), 2)} if gains else None,
                lambda o, r: abs(o["gain_db"] - float(r.get("audio.sfx.gain_db_default"))) <= TOL["sfx_gain_db"])


def _catalog(b: RowBuilder) -> dict | None:
    from .. import paths
    from ..util.jsonio import read_json

    rel = b.pget("audio.sfx.catalog")
    if not rel:
        return None
    return read_json(paths.absp(rel))


# ----------------------------------------------------------------------------- structure / cover
def rows_structure(b: RowBuilder, probes: dict) -> None:
    ctx = b.ctx
    fr = 1.0 / ctx.fps
    d_obs = ctx.info.duration
    b.add("structure.duration", "duration", "영상 길이", CAT["structure"], expected=_r(ctx.resolved.duration, 3),
          observed=_r(d_obs, 3), tolerance="±2프레임", status="same" if abs(d_obs - ctx.resolved.duration) <= 2 * fr + 0.01 else "different")
    b.style_row("structure.duration", "duration_ref", "영상 길이 (레퍼런스 분포 대비)", CAT["structure"],
                ["structure.duration_s.p10", "structure.duration_s.p50", "structure.duration_s.p90", "structure.duration_s.n"],
                {"duration": _r(d_obs, 2)},
                lambda o, r: r.get("structure.duration_s.p10") is not None and
                float(r["structure.duration_s.p10"]) <= o["duration"] <= float(r["structure.duration_s.p90"]))
    caps = [c for c in (probes.get("text") or {}).get("captions") or [] if c.get("onset") is not None]
    first = min((c["onset"] for c in caps), default=None)
    b.style_row("structure.duration", "first_caption_ref", "첫 자막 시각 (레퍼런스 대비)", CAT["structure"],
                ["structure.first_caption_at_s"], {"first_caption_at_s": first} if first is not None else None,
                lambda o, r: abs(o["first_caption_at_s"] - float(r.get("structure.first_caption_at_s") or 0)) <= 0.2)
    cov = (probes.get("text") or {}).get("cover")
    if cov:
        sim = cov.get("similarity")
        b.add("cover.frame", "frame", "표지 프레임에 제목 문구 표시", CAT["structure"],
              expected={"t": cov.get("t"), "text": cov.get("expected_text"), "role": cov.get("text_role")},
              observed={"ocr": cov.get("ocr"), "similarity": sim, "role_caption_visible": cov.get("role_caption_visible")},
              tolerance="OCR 유사도 ≥ 0.5", status="unmeasured" if sim is None else ("same" if sim >= 0.5 else "different"),
              keys=["cover.source", "cover.text_role"], required=False, evidence={"t": cov.get("t")})
        b.style_row("cover.frame", "cover_ref", "표지 구성 (레퍼런스 대비)", CAT["structure"], ["cover.source", "cover.text_role"],
                    {"text_role_visible": cov.get("role_caption_visible")}, lambda o, r: bool(o["text_role_visible"]))


# ----------------------------------------------------------------------------- entry
BUILDERS = [(("canvas.",), rows_canvas), (("caption.",), rows_captions), (("video.",), rows_video),
            (("decor.",), rows_decorations), (("identity.", "clean.corners"), rows_identity),
            (("clean.residual",), rows_residual), (("cover_up.",), rows_cover_up), (("audio.",), rows_audio),
            (("structure.", "cover."), rows_structure)]


def _wanted(only: list[str] | None, produces: tuple[str, ...]) -> bool:
    if not only:
        return True
    return any(o.startswith(p) or p.startswith(o) for o in only for p in produces)


def build_rows(ctx, probes: dict, only: list[str] | None = None) -> list[dict]:
    b = RowBuilder(ctx)
    for produces, fn in BUILDERS:
        if not _wanted(only, produces):
            continue
        try:
            fn(b, probes)
        except Exception as e:  # a bug in one check must not hide the others: report it as unmeasured
            import traceback

            b.add(produces[0].rstrip("."), "error", f"검사 코드 오류 ({fn.__name__})", "검사 오류", status="unmeasured",
                  note=f"{type(e).__name__}: {e} | {traceback.format_exc(limit=4)[-800:]}")
    rows = b.rows
    if only:
        rows = [r for r in rows if any(r["check_id"].startswith(o) for o in only)]
    return rows
