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
    "ref_grid": "레퍼런스 같은 시각 비교(1초 격자)",
}
REQUIRED_CATEGORIES = [CAT[k] for k in ("text_pos", "font", "cap_timing", "cut", "motion", "music", "original", "logo",
                                        "sfx_count", "sfx_offset", "sfx_no_event", "deco", "identity", "cover_up",
                                        "loudness", "ref_grid")]

# ----------------------------------------------------------------------------- declarations
# check_id -> the preset keys that check COMPARES in the output MP4 (a row's ``keys``).  Exact keys only, NO glob:
# the registry matches with fnmatch, whose '*' also spans dots (text.roles.*.color would claim text.roles.X.box.color),
# so role / decoration-kind keys are spelled out for every role (edit.resolve.ROLES) and kind the renderer draws.
# A key no check measures is NOT listed -- `preset audit` then reports it as no_qa.  Since wave 5 every style key has
# an output check; the only keys without one are the writing guide text.tone.sentence_end_examples (meta) and the
# sample counts structure.*.n (measurement metadata), both classified in shortkit.config.
# tests/qa/test_qa_review_d.py keeps this list equal to the keys the rows really carry.
ROLES = ("title", "description", "situation", "speaker", "dialogue", "reaction")     # = shortkit.edit.resolve.ROLES
DECO_KINDS = ("arrow", "box", "circle")                                             # captions.deco_shape kinds


def _roles(*leaves: str) -> list[str]:
    return [f"text.roles.{r}.{leaf}" for leaf in leaves for r in ROLES]


def _kinds(*leaves: str, kinds: tuple[str, ...] = DECO_KINDS) -> list[str]:
    return [f"decorations.{k}.{leaf}" for leaf in leaves for k in kinds]


_DECL: dict[str, list[str]] = {
    "canvas.format": ["canvas.width", "canvas.height", "canvas.fps"],
    "canvas.background": ["canvas.background.type", "canvas.background.color", "canvas.background.blur_sigma"],
    "canvas.video_region": ["canvas.video_region.x", "canvas.video_region.y", "canvas.video_region.w",
                            "canvas.video_region.h", "canvas.video_region.fit"],
    "canvas.safe_margin": ["canvas.safe_margin.left", "canvas.safe_margin.right", "canvas.safe_margin.top",
                           "canvas.safe_margin.bottom"],
    "caption.position": _roles("anchor.x", "anchor.y", "anchor.align", "anchor.valign"),
    "caption.size": _roles("size_px", "max_width_px", "max_lines", "line_spacing", "max_chars_per_line"),
    "caption.style": _roles("color", "outline_px", "outline_color", "box.enabled", "box.alpha", "highlight_color",
                            "shadow_px", "shadow_color", "box.color", "box.pad_x", "box.pad_y"),
    "caption.font": _roles("font_name", "bold"),
    "caption.timing": _roles("timing.min_dur_s", "persist", "timing.lead_s"),
    "caption.motion": _roles("motion_in.type", "motion_in.dur_s", "motion_in.scale_from", "motion_in.offset_px",
                             "motion_out.type", "motion_out.dur_s"),
    "caption.text": [],
    "caption.tone": ["text.tone.register", "text.tone.emoji"],
    "caption.quote": ["text.roles.dialogue.quote_marks"],
    "caption.reveal": [],
    "video.cuts": [],
    "video.mapping": [],
    "video.replay": [],
    "video.transitions": ["motion.transitions.default", "motion.transitions.flash.dur_s",
                          "motion.transitions.flash.color", "motion.transitions.crossfade.dur_s",
                          "motion.transitions.flash.scope"],
    "video.zoom": ["motion.zoom.scale_to", "motion.zoom.dur_s", "motion.zoom.ease", "motion.zoom.max_consecutive",
                   "motion.zoom.recenter"],
    "video.freeze": ["motion.freeze.hold_s", "motion.freeze.max_per_video"],
    "video.speed": ["motion.speed.slowmo_factor"],
    "decor.position": [],
    "decor.brightness": _kinds("blink_hz"),
    "decor.style": (_kinds("color", "blink_hz") + _kinds("stroke_px", kinds=("box", "circle"))
                    + _kinds("size_px", "head_len_ratio", "head_width_ratio", "shaft_width_ratio", "outline_px",
                             "outline_color", kinds=("arrow",))),
    "identity.forbidden_text": ["identity_exclusions.forbidden_text"],
    "identity.logo_templates": ["identity_exclusions.logo_templates_dir"],
    "identity.reference_footage": [],
    "clean.corners": [],
    "clean.residual": ["render.clean.blur_sigma_ratio"],   # blur ops: the blurred overlay must not be readable
    "cover_up.protected": [],
    "cover_up.faces": [],
    "audio.bgm": ["audio.bgm.track_id", "audio.bgm.title", "audio.bgm.version", "audio.bgm.tempo_ratio",
                  "audio.bgm.section_start_s", "audio.bgm.fade_in_s", "audio.bgm.fade_out_s", "audio.bgm.loop",
                  "audio.bgm.gain_db"],
    "audio.ducking": ["audio.ducking.depth_db", "audio.ducking.only_under_kept_dialogue", "audio.ducking.attack_s",
                      "audio.ducking.release_s"],
    "audio.silence": ["audio.silence.fade_s"],
    "audio.original": ["audio.original.keep_gain_db", "audio.original.default", "audio.original.remove_embedded_music",
                       "audio.original.fade_s"],
    "audio.sfx.placement": ["audio.sfx.gain_db_default"],
    "audio.sfx.count": ["audio.sfx.catalog"],
    "audio.sfx.type": ["audio.sfx.catalog"],
    "audio.sfx.offset": ["audio.sfx.max_event_offset_s"],
    "audio.sfx.no_event": ["audio.sfx.require_event"],
    "audio.sfx.on_cut": [],
    "audio.sfx.unexplained": [],
    "audio.loudness": ["audio.loudness.integrated_lufs", "audio.loudness.true_peak_db", "audio.sample_rate"],
    "structure.duration": ["structure.duration_s.p10", "structure.duration_s.p50", "structure.duration_s.p90",
                           "structure.first_caption_at_s"],
    "structure.cuts": ["structure.cuts_per_10s.p10", "structure.cuts_per_10s.p50", "structure.cuts_per_10s.p90",
                       "structure.shot_len_s.p10", "structure.shot_len_s.p50", "structure.shot_len_s.p90"],
    "cover.frame": ["cover.source", "cover.text_role"],
    "presence": [f"presence.{k}" for k in ("zoom", "freeze", "speed_change", "flash", "crossfade", "decorations",
                                           "bgm", "original_audio", "ducking", "intentional_silence")],
    "ref_grid.captions": [],
    "ref_grid.cuts": [],
    "ref_grid.sfx": [],
    "ref_grid.sheet": [],
}

# probe families each check needs (for selective re-runs)
FAMILY = {
    "canvas.": ("video", "text"), "caption.": ("text",), "caption.timing": ("text", "audio"), "video.": ("video",),
    "decor.": ("video",),
    "identity.": ("text",), "clean.corners": ("text",), "clean.residual": ("video",), "cover_up.": ("text", "video"),
    "audio.sfx.on_cut": ("audio", "video", "text"), "audio.": ("audio",), "structure.": ("text", "audio", "video"),
    "cover.": ("text",), "presence": ("video", "audio"), "ref_grid.": ("text", "video", "audio"),
}


def declarations() -> dict[str, list[str]]:
    """check_id -> the preset keys that check compares in the output MP4 (exact keys, no globs)."""
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
    # kept-original level estimator (probes_audio.kept_levels_obs) method noise: 24 synthetic mixes (3 TTS lines x
    # speech -6/0/+6/+10 dB x BGM ducked/not, AAC 192k) -> |error| p90 0.36 LU, max 0.45 LU; + test-pipeline-001
    # vs its own stems 0.12 LU.  The row tolerance adds audio.loudness.tolerance_lu: the renderer places kept speech
    # at T + keep_gain_db (T = target), so a programme accepted within +-tolerance_lu of T shifts it by as much.
    "orig_level_noise_lu": 0.5,
    # BGM level (plateau LS gain of the clean file): test-pipeline-001 plateau -0.24 dB vs the renderer's normalisation
    # gain -0.237 dB; the row tolerance adds audio.loudness.tolerance_lu (the definition adds target - mix LUFS)
    "bgm_level_noise_db": 0.3,
    # edge ramps (silence / ducking / kept original) against the SAME measurement run on the planned signal:
    # test-pipeline-001 silence 0.0484 / 0.0514 s vs planned reading 0.049 / 0.051 s, attack 0.081 vs 0.081 s,
    # release 0.298 vs 0.299 s; tests/qa/test_qa_outputs.py synthetic ramps
    "ramp_abs_s": 0.01, "ramp_frac": 0.15,
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


def _cwithin(a, b, tol: float) -> bool | None:
    """Colour distance within ``tol``; None (못 잼) when either colour is missing.  An exact match has distance 0.0,
    which must count as a match (never ``(d or 999)``)."""
    d = _cdist(a, b)
    return None if d is None else d <= tol


def _all(*parts) -> bool | None:
    """Combine the sub-verdicts of a style row, each computed for its own preset key (no short-circuit: every listed
    key is compared even when an earlier one already differs): False if any is False, None (못 잼) if any is None."""
    if any(p is not None and not bool(p) for p in parts):
        return False
    if any(p is None for p in parts):
        return None
    return True


class _KeyReads(dict):
    """The expected-values dict handed to a style row's compare function; records which preset keys the function
    really read.  A row may only list keys its compare reads (``RowBuilder._compare``)."""

    def __init__(self, *a, **kw) -> None:
        super().__init__(*a, **kw)
        self.read: set[str] = set()

    def __getitem__(self, k):
        self.read.add(k)
        return super().__getitem__(k)

    def get(self, k, default=None):
        self.read.add(k)
        return super().get(k, default)

    def __contains__(self, k) -> bool:
        self.read.add(k)
        return super().__contains__(k)


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

            from ..config import load_measurement_items

            self._meas = load_measurement_items(self.ctx.preset.dir, strict=False)
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
            change_ref: str | None = None, reference: Any = "__auto__", covered_by: str | None = None) -> dict:
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
        if covered_by:
            row["covered_by"] = covered_by
        self.rows.append(row)
        return row

    def style_row(self, check_id: str, subject: str, item: str, category: str, keys: list[str], observed: Any,
                  compare, *, evidence=None, note: str = "", required: bool | None = None,
                  na: dict[str, str] | None = None) -> dict:
        """style-vs-reference row: compare the OUTPUT measurement with the reference value.
        ``na``: {key: reason} keys that do not APPLY here (e.g. box.* of a role without a box) -- left out of the row
        (their provisional state cannot make it unmeasured) and listed in the note with the reason."""
        na = {k: v for k, v in (na or {}).items() if k in keys}
        if na:
            note = ("적용되지 않아 판정에서 뺀 키: " + "; ".join(f"{_short_key(k)} — {v}" for k, v in na.items())
                    + ". " + note).strip()
        row = self._style_row(check_id, subject, item, category, [k for k in keys if k not in na], observed, compare,
                              evidence=evidence, note=note, required=required)
        if na:
            row["not_applicable"] = dict(na)
        return row

    def _style_row(self, check_id: str, subject: str, item: str, category: str, keys: list[str], observed: Any,
                   compare, *, evidence=None, note: str = "", required: bool | None = None) -> dict:
        missing = [k for k in keys if not self._has(k)]
        keys = [k for k in keys if self._has(k)]
        ref, prov, req = self.reference_of(keys)
        expected = {k: self.pget(k) for k in keys}
        mode = getattr(self.ctx.resolved, "mode", "test")
        if required is None:
            required = mode == "production"
        if not keys:
            return self.add(check_id, subject, item, category, expected=None, observed=observed, status="unmeasured",
                            kind="style_vs_reference", required=False, reference="못 잼",
                            note=("프리셋에 해당 키 없음" + (f"({', '.join(missing)})" if missing else "")
                                  + (" — " + note if note else "")).strip())
        if req:
            # every key of the row is compared at its EFFECTIVE value (requested values override the reference values;
            # the other keys keep theirs): a compare that reads a key the row did not pass falls back to a default and
            # would call a correctly applied single-key change unintended
            ok, unread = (None, []) if observed is None else self._compare(compare, observed, keys)
            if unread:
                note = (note + f" 비교 함수가 읽지 않은 키(행에서 뺌): {', '.join(unread)}").strip()
                keys = [k for k in keys if k not in unread]
                req = [k for k in req if k not in unread]
                expected = {k: expected[k] for k in keys}
                if not req:
                    return self.add(check_id, subject, item, category, expected=expected, observed=observed,
                                    status="unmeasured", keys=keys, kind="style_vs_reference", required=required,
                                    evidence=evidence, reference=ref,
                                    note=(note + " 요청 변경 키를 출력에서 비교하지 못함").strip())
            change_ref = ", ".join(f"presets/{self.ctx.preset.name}/requested_changes.yaml#changes.{k}" for k in req)
            others = [k for k in keys if k not in req]
            if ok is not True:
                return self.add(check_id, subject, item, category, expected=expected, observed=observed,
                                status="unmeasured" if ok is None else "different", keys=keys, kind="style_vs_reference",
                                required=required, intended_change=False, change_ref=change_ref, evidence=evidence,
                                reference=ref, note=(note + (" 출력에서 측정 못 함" if ok is None else
                                                              " 출력이 요청 변경을 포함한 기대값과 다름(요청 변경이 반영되지 "
                                                              "않았거나 요청 밖 키가 다름)")).strip())
            # the output shows the requested values: the requested part is an intended change; the rest of the row is
            # judged against the reference on its own (a provisional remaining key stays 못 잼)
            row = self.add(check_id, subject, item + " — 요청 변경", category, expected={k: expected[k] for k in req},
                           observed=observed, status="different", keys=req, kind="style_vs_reference",
                           required=required, intended_change=True, change_ref=change_ref, evidence=evidence,
                           reference=self.reference_of(req)[0], note=(note + " 요청 변경이 출력에 반영됨").strip())
            if others:
                o_ref, o_prov, _ = self.reference_of(others)
                self.add(check_id, f"{subject}:others", item + " — 요청 변경 밖 키", category,
                         expected={k: expected[k] for k in others}, observed=observed,
                         status="unmeasured" if o_prov else "same", keys=others, kind="style_vs_reference",
                         required=required, evidence=evidence, reference=o_ref,
                         note=(f"레퍼런스 미측정(임시값) 키 {len(o_prov)}개: {', '.join(o_prov[:6])} — 요청 변경 밖 키는 "
                               "레퍼런스와 같다고 판정하지 않음" if o_prov else
                               "요청 변경 밖 키: 요청 값과 함께 비교한 출력이 레퍼런스 측정값과 같음"))
            return row
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
        ok, unread = self._compare(compare, observed, keys)
        if unread:
            keys = [k for k in keys if k not in unread]
            expected = {k: expected[k] for k in keys}
            ref = self.reference_of(keys)[0]
            note = (note + f" 비교 함수가 읽지 않은 키(행에서 뺌): {', '.join(unread)}").strip()
        st = "unmeasured" if ok is None else ("same" if ok else "different")
        row = self.add(check_id, subject, item, category, expected=expected, observed=observed, status=st, keys=keys,
                       kind="style_vs_reference", required=required, evidence=evidence, reference=ref, note=note)
        if unread:
            row["keys_not_compared"] = unread
        return row

    def _compare(self, compare, observed, keys: list[str]) -> tuple[Any, list[str]]:
        """Run a style row's compare with the effective preset values of ``keys``; -> (verdict, keys it did not read).
        A 'same' verdict that never looked at a listed key did not verify it: the caller drops such keys from the row
        (the registry must not link a key to a check that does not compare it)."""
        r = _KeyReads({k: self.pget(k) for k in keys})
        ok = compare(observed, r)
        unread = [k for k in keys if k not in r.read] if ok is True else []
        return ok, unread

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


def _short_key(k: str) -> str:
    """'text.roles.speaker.box.alpha' -> 'box.alpha' (the row already names the role)."""
    parts = k.split(".")
    return ".".join(parts[3:]) if k.startswith("text.roles.") and len(parts) > 3 else k


def _num(v, default: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def role_not_applicable(b: "RowBuilder", role: str, caps: list) -> dict[str, str]:
    """{preset key: reason} of the role's style keys that do not APPLY to this role -- decided from the preset's role
    style (the value the renderer uses) and the plan's captions of that role.  The governing key itself (box.enabled,
    shadow_px, motion_in.type, max_lines, persist ...) stays in its row, so a provisional governing key still makes the
    row 못 잼."""
    k = lambda n: f"text.roles.{role}.{n}"   # noqa: E731
    na: dict[str, str] = {}
    if not b.pget(k("box.enabled")):
        for n in ("box.color", "box.alpha", "box.pad_x", "box.pad_y"):
            na[k(n)] = "box.enabled=false(박스 없음)"
    if _num(b.pget(k("shadow_px"))) <= 0:
        na[k("shadow_color")] = "shadow_px=0(그림자 없음)"
    if _num(b.pget(k("outline_px"))) <= 0:
        na[k("outline_color")] = "outline_px=0(외곽선 없음)"
    if not any(getattr(c, "highlight", None) for c in caps):
        na[k("highlight_color")] = "이 편의 이 역할 자막에 강조 단어 없음(계획)"
    lines = [len([ln for ln in (getattr(c, "lines", None) or str(getattr(c, "text", "")).split("\n")) if str(ln).strip()])
             for c in caps]
    if int(_num(b.pget(k("max_lines")), 99)) <= 1 and all(n <= 1 for n in lines):
        na[k("line_spacing")] = "max_lines=1 이고 이 편의 자막도 한 줄(줄 간격이 없음)"
    if role != "dialogue" and abs(_num(b.pget(k("timing.lead_s")), 0.0)) < 1e-9:
        # the registry's applicability rule (config.APPLICABILITY: definition, neutral value 0)
        na[k("timing.lead_s")] = "정의: lead_s = 대사 자막 시작 − 겹치는 말소리 시작 → 대사 외 역할은 기준 사건이 없음(값 0)"
    if b.pget(k("persist")) == "whole_video":
        na[k("timing.min_dur_s")] = "persist=whole_video(영상 전체에 떠 있음)"
    mi = b.pget(k("motion_in.type"))
    if mi in (None, "none"):
        na[k("motion_in.dur_s")] = "motion_in.type=none"
    if mi != "pop":
        na[k("motion_in.scale_from")] = f"motion_in.type={mi}(pop 아님)"
    if _mi_type(mi) != "slide_up":
        na[k("motion_in.offset_px")] = f"motion_in.type={mi}(slide_up 아님 → 이동 거리가 쓰이지 않음)"
    if b.pget(k("motion_out.type")) in (None, "none"):
        na[k("motion_out.dur_s")] = "motion_out.type=none"
    return na


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
                lambda o, r: _all(o["width"] == r.get("canvas.width"), o["height"] == r.get("canvas.height"),
                                  abs(float(o["fps"] or 0) - float(r.get("canvas.fps") or 0)) < 0.01))
    lay = (probes.get("video") or {}).get("layout") or {}
    # the rectangle here; the fit mode (cover/contain) in canvas.video_region:fit (_rows_canvas_geometry)
    vr_keys = [f"canvas.video_region.{k}" for k in ("x", "y", "w", "h")]
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
                  keys=["canvas.background.type"] + (["canvas.background.color"] if ebg.get("type") == "color" else []),
                  required=False, note="흐림 정도(blur_sigma)는 canvas.background:blur 행")
        btype = b.pget("canvas.background.type")

        def _bg_same(ob, r):
            t_ok = ob.get("type") == r.get("canvas.background.type")
            return _all(t_ok, True if btype != "color" else
                        _cwithin(ob.get("color"), r.get("canvas.background.color"), TOL["bg_rgb"]))
        b.style_row("canvas.background", "background_ref", "배경 (레퍼런스 대비)", CAT["canvas"],
                    ["canvas.background.type"] + (["canvas.background.color"] if btype == "color" else [])
                    + ([] if btype == "blur_source" else ["canvas.background.blur_sigma"]),
                    bg if bg.get("color") else None, _bg_same,
                    na=({} if btype == "blur_source" else
                        {"canvas.background.blur_sigma": f"background.type={btype}(흐린 원본 배경 아님) → 흐림 정도가 쓰이지 않음"}),
                    note=("" if btype == "color" else "흐림 정도(blur_sigma)는 canvas.background:blur 행"))
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
    _rows_canvas_geometry(b, probes)


BLUR_SIGMA_TOL = (2.0, 0.15)     # canvas.background.blur_sigma: max(2 px, 15 %) (tests/qa/test_qa_outputs.py renders)


def _blur_tol(v) -> float:
    return max(BLUR_SIGMA_TOL[0], BLUR_SIGMA_TOL[1] * abs(float(v or 0.0)))


def _rows_canvas_geometry(b: RowBuilder, probes: dict) -> None:
    """canvas.video_region:fit -- cover / contain of every clip measured from the footage edges in the region (the
    output vs the renderer's cover and contain renderings where they differ); canvas.background:blur -- the blur sigma
    of a blur_source background (the output vs the renderer's background at candidate sigmas)."""
    ctx = b.ctx
    vp = probes.get("video") or {}
    cg = vp.get("canvas_geometry")
    err = (vp.get("errors") or {}).get("canvas_geometry")
    pf = b.pget("canvas.video_region.fit")
    fits = (cg or {}).get("fit") or []
    meas = [f for f in fits if f.get("status") == "measured"]
    bad = [f for f in meas if f.get("fit") != f.get("expected")]
    from_preset = all(f.get("expected") == pf for f in meas) and bool(meas)
    b.add("canvas.video_region", "fit", "영상 영역 채우기(cover/contain)", CAT["canvas"],
          expected={f["clip_id"]: f.get("expected") for f in fits} or None,
          observed={"clips": [{k: f.get(k) for k in ("clip_id", "t", "status", "fit", "err", "band_share", "reason")}
                              for f in fits]} if cg else None,
          tolerance="잰 클립마다 출력이 계획한 채우기 방식의 렌더링과 맞음(다른 방식 오차의 절반 이하)",
          status=("unmeasured" if not meas else ("different" if bad else "same")),
          keys=["canvas.video_region.fit"] if meas and from_preset else [], required=False,
          evidence={"t": (bad or meas or [{}])[0].get("t")},
          note=(err or ("모든 클립에서 cover 와 contain 렌더링이 같아(소스 비율 = 영역 비율) 채우기 방식을 출력에서 구별할 수 없음"
                        if fits and not meas else "") or
                "영역 안에서 cover·contain 렌더링(edit.render.Compositor)이 다른 화소(영상 가장자리)로 판정"))
    b.style_row("canvas.video_region", "fit_ref", "영상 영역 채우기 (레퍼런스 대비)", CAT["canvas"], ["canvas.video_region.fit"],
                {"fit": _mode([f["fit"] for f in meas])} if meas else None,
                lambda o, r: o["fit"] == r["canvas.video_region.fit"],
                note="출력에서 구별 가능한 클립의 채우기 방식(최빈)")
    bg = (ctx.resolved.canvas or {}).get("background") or {}
    if bg.get("type") != "blur_source":
        return
    bl = (cg or {}).get("blur") or {}
    exp = bg.get("blur_sigma")
    obs = bl.get("sigma")
    pv = b.pget("canvas.background.blur_sigma")
    b.add("canvas.background", "blur", "흐린 원본 배경의 흐림 정도(sigma)", CAT["canvas"], expected={"blur_sigma": exp},
          observed={"blur_sigma": obs, "per_clip": bl.get("per_clip")} if bl else None,
          tolerance=f"±max({BLUR_SIGMA_TOL[0]:g}, {int(BLUR_SIGMA_TOL[1] * 100)}%)",
          status="unmeasured" if obs is None or exp is None else ("same" if abs(float(obs) - float(exp)) <= _blur_tol(exp)
                                                                  else "different"),
          keys=["canvas.background.blur_sigma"] if obs is not None and pv is not None and exp is not None
          and abs(float(exp) - float(pv)) < 1e-9 else [], required=False,
          note=err or bl.get("method") or "")
    b.style_row("canvas.background", "blur_ref", "흐림 정도 (레퍼런스 대비)", CAT["canvas"], ["canvas.background.blur_sigma"],
                {"blur_sigma": obs} if obs is not None else None,
                lambda o, r: abs(float(o["blur_sigma"]) - float(r["canvas.background.blur_sigma"]))
                <= _blur_tol(r["canvas.background.blur_sigma"]))


# ----------------------------------------------------------------------------- captions
def rows_captions(b: RowBuilder, probes: dict) -> None:
    ctx = b.ctx
    tp = probes.get("text") or {}
    fr = 1.0 / ctx.fps
    if tp.get("status") != "measured":
        for cap in ctx.resolved.captions:
            for cid, it, cat in (("caption.position", "자막 위치", CAT["text_pos"]),
                                 ("caption.timing", "자막 타이밍", CAT["cap_timing"])):
                b.add(cid, cap.id, f"{it} [{cap.id}]", cat, status="unmeasured", note=tp.get("reason") or "문자 검사 실패")
        _font_role_rows(b, {}, tp.get("reason") or "문자 검사 실패")
        b.add("caption.reveal", "reveal", "반전 전에 반전 내용을 미리 말하지 않음", CAT["cap_text"],
              expected={"reveal": (ctx.plan or {}).get("reveal")}, status="unmeasured", required=True,
              note="문자 검사(OCR) 실패로 반전 전 자막의 문구를 확인하지 못함: " + str(tp.get("reason") or ""))
        return
    meas = {c["id"]: c for c in tp.get("captions") or []}
    text_confirmed: dict[str, bool] = {}
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
        # text similarity (OCR) -- first: the size row uses whether the line texts are the output's
        sim = m.get("similarity") or 0.0
        geo = str(m.get("match") or "").startswith("geometry")
        shape = _shape_text_evidence(m) if geo and sim < TOL["text_sim"] else None
        shape_ok = bool(shape and shape.get("glyph_pass") and shape.get("verdict") in ("identical", "similar"))
        obs_t = {"ocr": m.get("ocr"), "similarity": sim, "match": m.get("match")}
        if shape:
            obs_t["shape"] = shape
        if sim >= TOL["text_sim"]:
            st_t, note_t = "same", "굵은 글꼴 OCR 오차가 있어 유사도로 판정"
        elif shape_ok:
            # tesseract cannot read some short bold captions ("빤히" -> 반 히): the expected text rendered in the
            # expected face is compared glyph by glyph with the output crop instead (a one-syllable change drops
            # that glyph's IoU far below the floor: 빤 0.966 vs 반 0.715 on test-coverage-001 c_rx)
            st_t, note_t = "same", ("짧은 문구를 OCR 이 읽지 못해 글자 모양으로 확인: 기대 문구를 기대 글꼴로 렌더한 모양과 "
                                    f"글자별 IoU 모두 하한 이상(전체 IoU {shape.get('iou')}, 글꼴 판정 {shape.get('verdict')})")
        elif geo:
            st_t, note_t = "unmeasured", "짧은 문구를 OCR 이 읽지 못해 위치·색으로만 찾음 — 문구 일치는 못 잼" + \
                ("" if not shape else f" (글자 모양 대조도 통과 못 함: {shape})")
        else:
            st_t, note_t = "different", "굵은 글꼴 OCR 오차가 있어 유사도로 판정"
        text_confirmed[cap.id] = st_t == "same"
        # size / lines / width
        # IR bbox includes the outline stroke; the measured ink is the fill only
        exp_fill_h = max(1.0, cap.bbox.h - 2 * float(cap.outline_px or 0))
        tol_h = TOL["size_frac"] * exp_fill_h + 3
        dh = ob[3] - exp_fill_h
        lines_ok = m.get("lines_found") == m.get("lines_expected")
        maxw = float(b.pget(f"text.roles.{role}.max_width_px", 1e9) or 1e9)
        maxl = int(b.pget(f"text.roles.{role}.max_lines", 99) or 99)
        size_ok = abs(dh) <= tol_h and lines_ok and ob[2] <= maxw + 4 and (m.get("lines_found") or 0) <= maxl
        size_keys = _role_keys(role, ["size_px", "max_width_px", "max_lines"])
        plan_lines = [ln for ln in (cap.lines or str(cap.text).split("\n")) if str(ln).strip()]
        if len(plan_lines) > 1:
            # a multi-line fill height is line pitch (size_px x line_spacing) + the last line's ink
            size_keys.append(f"text.roles.{role}.line_spacing")
        size_notes = ["채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선)"]
        mcpl = b.pget(f"text.roles.{role}.max_chars_per_line")
        chars_obs = None
        if mcpl is not None and st_t == "same" and lines_ok:
            # the output's lines: the text is confirmed in the output (OCR / glyph shapes) and the line count too,
            # so the planned line texts are the lines on screen; characters counted without spaces (renderer rule)
            chars_obs = max(len(str(ln).replace(" ", "")) for ln in plan_lines) if plan_lines else 0
            size_keys.append(f"text.roles.{role}.max_chars_per_line")
            if chars_obs > int(mcpl):
                size_ok = False
                size_notes.append(f"한 줄 {chars_obs}자 > max_chars_per_line {mcpl}")
        elif mcpl is not None:
            size_notes.append("문구·줄 수가 출력에서 확인되지 않아 줄당 글자 수는 판정에서 뺌")
        b.add("caption.size", cap.id, f"자막 크기·줄 수 {label}", CAT["text_pos"],
              expected={"fill_h": _r(exp_fill_h, 1), "lines": m.get("lines_expected"), "max_width_px": maxw, "max_lines": maxl,
                        "size_px": cap.size_px, "max_chars_per_line": mcpl},
              observed={"fill_h": ob[3], "fill_w": ob[2], "lines": m.get("lines_found"),
                        "size_px_est": _r(cap.size_px * ob[3] / exp_fill_h, 1), "max_chars_line": chars_obs},
              tolerance=f"높이 ±{tol_h:.0f}px, 줄 수 일치, 폭 ≤ max_width_px, 줄당 글자 ≤ max_chars_per_line",
              status="same" if size_ok else "different", keys=size_keys, evidence=ev, required=True,
              note="; ".join(size_notes))
        b.add("caption.text", cap.id, f"자막 문구(OCR) {label}", CAT["cap_text"], expected=cap.text,
              observed=obs_t, tolerance=f"OCR 유사도 ≥ {TOL['text_sim']} (짧은 문구 OCR 실패 시 글자별 모양 대조)",
              status=st_t, evidence=ev, note=note_t)
        # colour / outline / box
        fill = m.get("fill_color")
        dcol = _cdist(fill, cap.color)
        style_ok = dcol is not None and dcol <= TOL["color_rgb"]
        oobs = m.get("outline_px_obs")
        outline_measurable = (m.get("outline_bg_same_color_frac") or 0) < 0.5
        notes = []
        st_keys = _role_keys(role, ["color"])
        if cap.outline_px and outline_measurable and oobs is not None:
            st_keys.append(f"text.roles.{role}.outline_px")
            if abs(oobs - float(cap.outline_px)) > max(2.0, 0.35 * float(cap.outline_px)):
                style_ok = False
                notes.append(f"외곽선 두께 {oobs}px (기대 {cap.outline_px}px)")
            oc_ok = _cwithin(m.get("outline_color"), cap.outline_color, TOL["color_rgb"])
            if oc_ok is not None:
                st_keys.append(f"text.roles.{role}.outline_color")
                if not oc_ok:
                    style_ok = False
                    notes.append(f"외곽선 색 {m.get('outline_color')} (기대 {cap.outline_color})")
        elif cap.outline_px:
            notes.append("배경이 외곽선 색과 같아 외곽선 두께·색은 못 잼(판정에서 뺌)")
        elif oobs:
            st_keys.append(f"text.roles.{role}.outline_px")
            if oobs > 2:
                style_ok = False
                notes.append(f"계획에 없는 외곽선 {oobs}px")
        box = cap.box or {}
        ba = box_alpha_obs(m)
        if box.get("enabled"):
            ea = float(box.get("alpha") if box.get("alpha") is not None else 1.0)
            if ba is None:
                notes.append("배경이 어두워 자막 박스 투명도는 못 잼(판정에서 뺌)")
            else:
                st_keys += _role_keys(role, ["box.enabled", "box.alpha"])
                if abs(ba - ea) > 0.2:
                    style_ok = False
                    notes.append(f"자막 박스 불투명도 {ba} (기대 {ea})" if ba >= 0.15 else "자막 박스가 보이지 않음")
        elif ba is not None:
            st_keys.append(f"text.roles.{role}.box.enabled")
            if ba > 0.3:
                style_ok = False
                notes.append(f"계획에 없는 어두운 박스(불투명도 {ba})")
        if cap.highlight:
            st_keys.append(f"text.roles.{role}.highlight_color")
            if not m.get("highlight_px"):
                style_ok = False
                notes.append("강조색 화소 없음")
        xo, xe, xkeys, xnotes, xok = _style_extras(cap, m, role)
        st_keys += xkeys
        notes += xnotes
        style_ok = style_ok and xok
        b.add("caption.style", cap.id, f"자막 색·외곽선·그림자·박스 {label}", CAT["cap_style"],
              expected={"color": cap.color, "outline_px": cap.outline_px, "outline_color": cap.outline_color,
                        "box": bool(box.get("enabled")), "box_alpha": box.get("alpha") if box.get("enabled") else None,
                        "highlight": cap.highlight, **xe},
              observed={"fill_color": fill, "outline_px": oobs, "outline_color": m.get("outline_color"),
                        "box_alpha": ba, "highlight_px": m.get("highlight_px"), **xo},
              tolerance=(f"색 거리 ≤ {TOL['color_rgb']:.0f}, 외곽선 ±max(2px,35%), 그림자 ±{SHADOW_TOL_PX:g}px, "
                         f"박스 여백 ±{PAD_TOL_PX:g}px"),
              status="unmeasured" if fill is None else ("same" if style_ok else "different"),
              keys=st_keys, evidence=ev, note="; ".join(notes))
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
              evidence={"t": on, "frame": m.get("evidence_frame")}, note="; ".join(notes))
        # motion in / out
        _motion_rows(b, cap, m, role, label, ev, fr)
    # font: the REQUIRED rows are per role (every caption of a role uses one face); per-caption rows are informational
    _font_role_rows(b, tp.get("font_roles") or {}, (tp.get("errors") or {}).get("font_roles"))
    # information order: captions shown before the reveal must not contain its keywords
    rv = (ctx.plan or {}).get("reveal") or {}
    if not (rv.get("t") is not None and rv.get("keywords")):
        _reveal_undeclared_row(b, rv)
    else:
        from .probes_text import _fuzzy_contains

        hits, unconfirmed = [], []
        for cap in ctx.resolved.captions:
            m = meas.get(cap.id) or {}
            if m.get("onset") is None:
                # the onset was not measured: the caption may have been on screen before the reveal
                if cap.start < float(rv["t"]) + 0.5:
                    unconfirmed.append({"caption": cap.id, "why": "출력 등장 시각 못 잼"})
                continue
            on = float(m["onset"])
            if on >= float(rv["t"]) - 1e-6:
                continue
            ocr_ok = m.get("found") and (m.get("similarity") or 0) >= TOL["text_sim"]
            if ocr_ok:
                txt, basis = m.get("ocr"), "OCR"
            elif text_confirmed.get(cap.id):
                # the plan text is confirmed in the output by the glyph-shape comparison (caption.text 'same')
                txt, basis = cap.text, "글자 모양으로 확인한 문구"
            else:
                unconfirmed.append({"caption": cap.id, "why": "출력에서 문구를 확인하지 못함(OCR·글자 모양 모두 실패)"})
                continue
            for kw in rv["keywords"]:
                if _fuzzy_contains(txt or "", kw) >= 0.85:
                    hits.append({"caption": cap.id, "onset": on, "keyword": kw, "basis": basis})
        st = "different" if hits else ("unmeasured" if unconfirmed else "same")
        b.add("caption.reveal", "reveal", "반전 전에 반전 내용을 미리 말하지 않음", CAT["cap_text"],
              expected={"reveal_t": rv["t"], "keywords": rv["keywords"]},
              observed={"hits": hits, "unconfirmed_captions": unconfirmed}, tolerance="반전 시각 전 자막에 키워드 0건",
              status=st, evidence={"t": hits[0]["onset"]} if hits else {"t": rv["t"]},
              note=("출력에서 확인한 문구(OCR 또는 글자 모양)만으로 판정" if st != "unmeasured" else
                    "반전 전 자막 중 출력에서 문구·시각을 확인하지 못한 것이 있음 — 계획 문구로 '같다'고 하지 않음"))
    # tone
    tone = tp.get("tone") or {}
    reg = b.pget("text.tone.register")
    b.add("caption.tone", "register", "자막 말투(종결어미, OCR)", CAT["cap_text"], expected=reg,
          observed=tone or None, tolerance="최빈 말투 일치",
          status="unmeasured" if not tone.get("n") else ("same" if tone.get("mode") == reg else "different"),
          keys=["text.tone.register"], required=False,
          note=("OCR 문구의 종결 어미를 레퍼런스 분석기·validate 와 같은 분류기(reference.aggregate.ending_class)로 분류"
                if tone.get("n") else "종결 어미로 말투를 판정할 수 있는 해설 자막(OCR)이 없음(명사형만 있거나 OCR 실패)"))
    _emoji_rows(b, meas)
    _quote_rows(b, meas)
    # style vs reference per role present in the episode
    roles = sorted({c.role for c in ctx.resolved.captions})
    for role in roles:
        rc = [meas.get(c.id) or {} for c in ctx.resolved.captions if c.role == role]
        rc_found = [m for m in rc if m.get("found")]
        caps_r = [c for c in ctx.resolved.captions if c.role == role]
        na = role_not_applicable(b, role, caps_r)
        no_override = [m for m, c in zip(rc, caps_r) if m.get("found") and not _has_pos_override(b, c)]
        obs_anchor = ({"x": _r(_median([m["bbox_obs"][0] + m["bbox_obs"][2] / 2 for m in no_override]), 1),
                       "y": _r(_median([m["bbox_obs"][1] + m["bbox_obs"][3] / 2 for m in no_override]), 1)}
                      if no_override else None)
        tol_px = TOL["pos_px_min"] * 2
        b.style_row("caption.position", f"{role}_ref", f"자막 위치 [{role}] (레퍼런스 대비)", CAT["text_pos"],
                    _role_keys(role, ["anchor.x", "anchor.y"]),
                    obs_anchor, lambda o, r, role=role: _all(abs(o["x"] - float(r[f"text.roles.{role}.anchor.x"])) <= tol_px,
                                                             abs(o["y"] - float(r[f"text.roles.{role}.anchor.y"])) <= tol_px))
        size_obs = _median([c.size_px * m["bbox_obs"][3] / max(1.0, c.bbox.h - 2 * float(c.outline_px or 0))
                            for m, c in zip(rc, caps_r) if m.get("found") and c.bbox.h])
        b.style_row("caption.size", f"{role}_ref", f"자막 크기 [{role}] (레퍼런스 대비)", CAT["text_pos"],
                    _role_keys(role, ["size_px"]),
                    {"size_px_est": _r(size_obs, 1)} if size_obs else None,
                    lambda o, r, role=role: abs(o["size_px_est"] - float(r[f"text.roles.{role}.size_px"])) <=
                    0.08 * float(r[f"text.roles.{role}.size_px"]), na=na)
        _style_ref_row(b, role, rc_found, caps_r, na)
        # only the role's pooled 'identical' verdict names the output font (similar/different/per-caption do not);
        # bold = the identified face's OS/2 weight >= typography.BOLD_MIN_WEIGHT (the rule `ref fonts` measures with)
        fonts = [r.get("expected_canonical") for r in (tp.get("font_roles") or {}).values()
                 if r.get("role") == role and r.get("verdict") == "identical"]
        f_obs = _font_obs(fonts[0]) if len(fonts) == 1 else None

        def _font_same(o, r, role=role):
            name_ok = str(o["best"]).replace(" ", "").lower() == \
                str(r.get(f"text.roles.{role}.font_name")).replace(" ", "").lower()
            want_bold = r.get(f"text.roles.{role}.bold")
            return _all(name_ok, None if o.get("bold") is None else bool(o["bold"]) == bool(want_bold))
        b.style_row("caption.font", f"{role}_ref", f"자막 글꼴·굵기 [{role}] (레퍼런스 대비)", CAT["font"],
                    _role_keys(role, ["font_name", "bold"]), f_obs, _font_same,
                    note="글꼴 = 역할 합동 판정이 동일(identical)인 면; 굵기 = 그 면의 OS/2 굵기 ≥ "
                         "typography.BOLD_MIN_WEIGHT(ref fonts 와 같은 규칙)")
        spans = [(m.get("onset"), m.get("offset")) for m in rc_found if m.get("onset") is not None and m.get("offset") is not None]
        durs = [b_ - a for a, b_ in spans]
        whole = b.pget(f"text.roles.{role}.persist") == "whole_video"
        dur_v = float(ctx.info.duration)
        # persist as the reference analyzer defines it (reference.textboxes): whole_video when a caption of the role
        # is shown for >= 90 % of the video, else timed
        t_obs = ({"min_dur_s": _r(min(durs), 3), "max_dur_s": _r(max(durs), 3),
                  "persist": "whole_video" if any(d >= 0.9 * dur_v for d in durs) else "timed",
                  "first_onset": _r(min(a for a, _ in spans), 3), "last_offset": _r(max(b_ for _, b_ in spans), 3),
                  "duration": _r(dur_v, 3)} if durs else None)

        def _timing_ok(o, r, role=role):
            p_ok = o["persist"] == r.get(f"text.roles.{role}.persist")
            lead = []
            if f"text.roles.{role}.timing.lead_s" in r:
                # a non-dialogue role whose lead_s is not 0: the definition has no reference event for it -> 못 잼
                lead = [None]
            if r.get(f"text.roles.{role}.persist") == "whole_video":
                return _all(p_ok, *lead)   # min_dur_s does not apply (role_not_applicable leaves it out of the row)
            return _all(p_ok, o["min_dur_s"] >= float(r.get(f"text.roles.{role}.timing.min_dur_s") or 0) - 0.05, *lead)
        # dialogue timing.lead_s (lead over the speech onset measured in the output): its own row (_lead_ref_row); for the
        # other roles lead_s is 0 by definition (role_not_applicable -> the row's not_applicable)
        b.style_row("caption.timing", f"{role}_ref", f"자막 표시 시간 [{role}] (레퍼런스 대비)", CAT["cap_timing"],
                    _role_keys(role, ["timing.min_dur_s", "persist"] + ([] if role == "dialogue" else ["timing.lead_s"])),
                    t_obs, _timing_ok, na=na,
                    note="persist: 역할 자막 하나가 영상 길이의 90% 이상 보이면 whole_video(레퍼런스 분석기와 같은 정의); "
                         + ("" if whole else "timed 이면 측정한 최소 표시 시간 ≥ timing.min_dur_s − 0.05 s"))
        if role == "dialogue":
            _lead_ref_row(b, caps_r, meas, probes, fr)
        _motion_ref_row(b, role, rc_found, na, fr)
    b.style_row("caption.tone", "tone_ref", "자막 말투 (레퍼런스 대비)", CAT["cap_text"], ["text.tone.register"],
                {"register": tone.get("mode")} if tone.get("n") else None,
                lambda o, r: o["register"] == r.get("text.tone.register"))


def _emoji_rows(b: RowBuilder, meas: dict) -> None:
    """caption.tone:emoji -- colour glyphs measured inside every caption of the output (probes_text.emoji_obs) vs the
    emoji the plan's caption texts contain (edit.validate.EMOJI_RE); caption.tone:emoji_ref -- vs text.tone.emoji
    (false: no colour glyph in any caption; true: allowed)."""
    from ..edit.validate import EMOJI_RE

    ctx = b.ctx
    per, bad, unk = [], [], []
    for cap in ctx.resolved.captions:
        m = meas.get(cap.id) or {}
        eo = m.get("emoji") or {}
        n_exp = len(EMOJI_RE.findall(cap.text or ""))
        rec = {"caption": cap.id, "planned": n_exp, "observed": eo.get("n_blobs"), "status": eo.get("status") or "unmeasured"}
        if eo.get("status") != "measured":
            rec["reason"] = eo.get("reason") or ("자막을 찾지 못함" if not m.get("found") else "측정 없음")
            unk.append(rec)
        elif (n_exp == 0) != (int(eo.get("n_blobs") or 0) == 0):
            rec["blobs"] = eo.get("blobs")
            bad.append(rec)
        per.append(rec)
    st = "different" if bad else ("unmeasured" if unk or not per else "same")
    b.add("caption.tone", "emoji", "자막 이모지(색 글리프) — 계획 대비", CAT["cap_text"],
          expected={"planned_emoji": {r["caption"]: r["planned"] for r in per}},
          observed={"per_caption": per}, tolerance="계획에 이모지가 없는 자막에 색 글리프 0개, 있는 자막에 1개 이상",
          status=st, required=False, evidence={"t": None},
          note=("자막이 그린 화소 중 표시 중 정지·채도 높음·자막 색(채움·강조·외곽선·그림자·박스)과 그 혼합이 아닌 덩어리를 색 글리프로 셈"
                + (f"; 못 잰 자막: {', '.join(r['caption'] for r in unk)}" if unk else "")))
    meas_n = [r for r in per if r["status"] == "measured"]

    def _cmp(o, r):
        allowed = r["text.tone.emoji"]
        if allowed is True:
            return True                   # allowed: any count is inside the reference's use
        if o["unmeasured_captions"]:
            return None                   # a caption not checked could hold one
        return o["captions_with_emoji"] == 0
    b.style_row("caption.tone", "emoji_ref", "자막 이모지 (레퍼런스 대비)", CAT["cap_text"], ["text.tone.emoji"],
                {"captions_with_emoji": sum(1 for r in meas_n if (r["observed"] or 0) > 0),
                 "unmeasured_captions": [r["caption"] for r in unk]} if meas_n else None, _cmp,
                note="text.tone.emoji=false → 모든 자막에 색 글리프 0개(못 잰 자막이 있으면 못 잼); true → 허용")


def _planned_quotes(text: str) -> list:
    """[open, close] quote characters at the ends of a planned caption text (None = no quote at that end), with the
    reference analyzer's own rule (reference.textboxes.quote_pair)."""
    from ..reference.textboxes import quote_pair

    q = quote_pair(text or "")
    return [q["open"] or None, q["close"] or None]


def _observed_quote_end(qo: dict, side: str) -> tuple[str, str | None]:
    """(state, glyph) of one end: 'glyph' (shape-confirmed character), 'present' (a quote-like mark, character not
    confirmed), 'absent', 'unknown'.  Shape check first; OCR (reference definition quote_pair) only when the shape
    check could not run."""
    sh = (qo.get("shape") or {})
    if sh.get("status") == "measured":
        e = sh.get(side) or {}
        if not e.get("present"):
            return "absent", None
        return ("glyph", e["glyph"]) if e.get("glyph") else ("present", None)
    ocr = qo.get("ocr") or {}
    ch = ocr.get("open" if side == "open" else "close")
    if ch:
        return "glyph", ch
    return "unknown", None


def _quote_rows(b: RowBuilder, meas: dict) -> None:
    """caption.quote -- quote marks of every rendered dialogue caption (probes_text.quote_marks_obs: glyph shapes of the
    small marks at the line ends against the quote glyphs rendered in the caption's face, OCR quote_pair when the
    shape check cannot run) vs the plan text (resolve adds text.roles.dialogue.quote_marks), and vs the reference."""
    ctx = b.ctx
    dl = [c for c in ctx.resolved.captions if c.role == "dialogue"]
    if not dl:
        return
    pq = b.pget("text.roles.dialogue.quote_marks")
    pq_l = list(pq) if isinstance(pq, (list, tuple)) else ([] if not pq else None)
    pairs = []
    for cap in dl:
        m = meas.get(cap.id) or {}
        qo = m.get("quote_marks")
        exp = _planned_quotes(cap.text)
        label = f"[{cap.id}·dialogue] \"{cap.text[:18]}\""
        if not qo:
            b.add("caption.quote", cap.id, f"대사 따옴표 {label}", CAT["cap_text"], expected={"open": exp[0], "close": exp[1]},
                  observed=None, status="unmeasured", required=False,
                  note="자막을 출력에서 찾지 못해 따옴표 못 잼" if not m.get("found") else "따옴표 측정 없음")
            continue
        parts, obs = [], {}
        for i, side in enumerate(("open", "close")):
            state, g = _observed_quote_end(qo, side)
            obs[side] = {"state": state, "glyph": g}
            e = exp[i]
            if state == "absent":
                parts.append(e is None)
            elif state == "glyph":
                parts.append(e is not None and g == e)
            elif state == "present":
                parts.append(False if e is None else None)
            else:
                parts.append(None)
        ok = _all(*parts)
        if obs["open"]["state"] in ("glyph", "absent") and obs["close"]["state"] in ("glyph", "absent"):
            pairs.append([obs["open"]["glyph"], obs["close"]["glyph"]] if obs["open"]["glyph"] or obs["close"]["glyph"] else [])
        from_preset = pq_l is not None and ([x for x in exp if x] == [x for x in pq_l] if pq_l else exp == [None, None])
        b.add("caption.quote", cap.id, f"대사 따옴표 {label}", CAT["cap_text"],
              expected={"open": exp[0], "close": exp[1], "source": "IR 자막 문구(resolve 가 quote_marks 를 붙인 뒤)"},
              observed={**obs, "shape": qo.get("shape"), "ocr": qo.get("ocr")},
              tolerance="양 끝마다: 따옴표 있음/없음 일치 + 글자 모양으로 확인한 문자가 계획 문자와 같음",
              status="unmeasured" if ok is None else ("same" if ok else "different"),
              keys=["text.roles.dialogue.quote_marks"] if from_preset and ok is not None else [], required=False,
              evidence={"t": m.get("t_rest"), "frame": m.get("evidence_frame")},
              note="글자 모양: 줄 끝의 작은 윗부분 표시를 자막 글꼴로 렌더한 따옴표 후보들과 IoU 비교(OCR 은 “ 와 \" 를 혼동)")

    def _cmp(o, r):
        want = r["text.roles.dialogue.quote_marks"]
        want = list(want) if isinstance(want, (list, tuple)) else ([] if not want else None)
        return None if want is None else o["pair"] == want
    from collections import Counter

    pm = Counter(tuple(p) for p in pairs).most_common(1)[0][0] if pairs else None   # () = no quotes (kept, not falsy-dropped)
    b.style_row("caption.quote", "dialogue_ref", "대사 따옴표 (레퍼런스 대비)", CAT["cap_text"],
                ["text.roles.dialogue.quote_marks"], {"pair": list(pm), "per_caption": pairs} if pm is not None else None, _cmp,
                note="출력 대사 자막마다 양 끝 따옴표(글자 모양 확인 또는 OCR)의 최빈 쌍 vs 레퍼런스 값(reference.aggregate "
                     "quote_marks: [여는, 닫는] 또는 [])")


# motion types the output probe can tell apart (probes_text.measure_timing / slide_track)
MEASURABLE_MOTION_IN = ("none", "pop", "fade", "slide_up")
MEASURABLE_MOTION_OUT = ("none", "fade")
MOTION_DUR_TOL_FRAMES = 1.5
SLIDE_OFFSET_TOL = (3.0, 0.1)    # slide start offset: max(3 px, 10 %) + one frame of travel (onset off the frame grid)


def _mi_type(v):
    """Entrance type name: the reference analyzer reports a slide as 'slide' (reference.textboxes), the renderer draws
    'slide_up' (edit.resolve.MOTION_IN_TYPES) -- the same upward slide."""
    return "slide_up" if v in ("slide", "slide_up") else v


def slide_offset_tol(offset_px: float, dur_s: float, fr: float) -> float:
    off = abs(float(offset_px or 0.0))
    travel = off * fr / float(dur_s) if dur_s and float(dur_s) > 0 else 0.0
    return max(SLIDE_OFFSET_TOL[0], SLIDE_OFFSET_TOL[1] * off) + travel


def _human_record(b: "RowBuilder", row_id: str, kind: str) -> dict | None:
    """A person's watch / listen record for this row made on THIS mp4 (qa/human_checks.jsonl), or None."""
    from .human import latest

    opts = getattr(b.ctx, "options", None) or {}
    return latest(opts.get("human_checks") or [], row_id, opts.get("mp4_sha256"), kind=kind)


def _reveal_undeclared_row(b: "RowBuilder", rv: dict) -> None:
    """caption.reveal without a protected reveal (plan reveal {t, keywords}): nothing tells the output check what must
    not be said early.  Required and 못 잼 -- also for ``reveal: {none: true, reason}`` (the author's statement that the
    story has no twist is not a measurement of the output) -- until a person who watched the final MP4 records the
    verdict (`shortkit qa human-check --kind watch --row caption.reveal:reveal`)."""
    rec = _human_record(b, "caption.reveal:reveal", "watch")
    declared_none = bool(rv.get("none"))
    if rec is not None:
        st, note = rec["verdict"], f"사람이 최종 MP4 를 보고 기록({rec['by']}, {rec['at']}): {rec['note']}"
    elif declared_none:
        st, note = "unmeasured", (f"plan 이 '반전 없음'(reveal.none: {rv.get('reason') or '이유 없음'})이라고 적었을 뿐 출력에서 잰 것이 아님 — "
                                  "보호할 키워드가 없어 자막을 대조할 수 없음; 사람이 보고 `shortkit qa human-check --kind watch` 로 기록")
    else:
        st, note = "unmeasured", ("plan 에 반전 보호(reveal: t, keywords)도 '반전 없음'(reveal.none) 선언도 없음 — 반전을 미리 말하는지 "
                                  "출력에서 판정할 기준이 없음")
    b.add("caption.reveal", "reveal", "반전 전에 반전 내용을 미리 말하지 않음", CAT["cap_text"],
          expected={"reveal": rv or None}, observed={"human_check": rec} if rec else None,
          tolerance="반전 시각 전 자막에 반전 키워드 0건", status=st, required=True, note=note)


def _motion_rows(b: "RowBuilder", cap, m: dict, role: str, label: str, ev: dict, fr: float) -> None:
    """caption.motion rows of one caption: entrance (type, duration, pop start scale, slide_up start offset) and exit
    (type, fade length), each measured in the output; a motion type the probe cannot measure is 못 잼, never 같다."""
    ctx = b.ctx
    mi = cap.motion_in or {}
    et = (mi.get("type") or "none")
    mo = m.get("motion_in_obs")
    tol_d = MOTION_DUR_TOL_FRAMES * fr + 0.005
    keys = [f"text.roles.{role}.motion_in.type"]
    if et not in MEASURABLE_MOTION_IN:
        b.add("caption.motion", cap.id, f"자막 등장 모션 {label}", CAT["cap_motion"], expected=mi, observed=mo,
              status="unmeasured", evidence=ev,
              note=f"등장 모션 '{et}' 은 출력에서 측정하지 않음(pop/fade/slide_up/none 만 측정) — 같다고 판정하지 않음")
    elif mo is None:
        b.add("caption.motion", cap.id, f"자막 등장 모션 {label}", CAT["cap_motion"], expected=mi, observed=None,
              status="unmeasured", keys=keys, evidence=ev, note="등장 시점을 측정하지 못해 모션 판정 불가")
    elif et == "slide_up" and not mo.get("slide_measured"):
        # the slide track (probes_text.slide_track) did not run or failed: the classic presence classification cannot
        # see a slide -- never judged from it
        b.add("caption.motion", cap.id, f"자막 등장 모션 {label}", CAT["cap_motion"], expected=mi, observed=mo,
              status="unmeasured", keys=keys, evidence=ev,
              note="slide_up 이동 추적 실패: " + str((m.get("slide_track") or {}).get("reason") or "측정 없음"))
    else:
        ok = _mi_type(mo["type"]) == et
        notes = []
        if ok and et == "slide_up":
            d_s = mo.get("dur_s")
            if d_s is not None:
                keys.append(f"text.roles.{role}.motion_in.dur_s")
                if abs(float(d_s) - float(mi.get("dur_s") or 0.0)) > tol_d:
                    ok = False
                    notes.append(f"등장 길이 {d_s}s (기대 {mi.get('dur_s')}s)")
            else:
                notes.append("등장 길이는 측정하지 못해 판정에서 뺌")
            if mo.get("offset_px") is not None:
                keys.append(f"text.roles.{role}.motion_in.offset_px")
                tol_o = slide_offset_tol(mi.get("offset_px"), mi.get("dur_s"), fr)
                if abs(float(mo["offset_px"]) - abs(float(mi.get("offset_px") or 0.0))) > tol_o:
                    ok = False
                    notes.append(f"첫 프레임 이동 {mo['offset_px']}px (기대 {mi.get('offset_px')}px, ±{tol_o:.1f})")
        if ok and et == "pop" and mo.get("scale_first") is not None:
            keys.append(f"text.roles.{role}.motion_in.scale_from")
            ok = abs(mo["scale_first"] - float(mi.get("scale_from") or 1.0)) <= TOL["scale_first"] + \
                abs(float(mi.get("scale_from") or 1.0) - 1.0) * 0.35
        d_obs = mo.get("fade_dur_s") if et == "fade" else (mo.get("dur_s") if et == "pop" else None)
        if ok and et in ("pop", "fade"):
            if d_obs is None:
                notes.append("등장 길이는 측정하지 못해 판정에서 뺌")
            else:
                keys.append(f"text.roles.{role}.motion_in.dur_s")
                if abs(float(d_obs) - float(mi.get("dur_s") or 0.0)) > tol_d:
                    ok = False
                    notes.append(f"등장 길이 {d_obs}s (기대 {mi.get('dur_s')}s)")
        if et == "slide_up":
            d_obs = mo.get("dur_s")
        b.add("caption.motion", cap.id, f"자막 등장 모션 {label}", CAT["cap_motion"],
              expected={"type": et, "dur_s": mi.get("dur_s"), "scale_from": mi.get("scale_from"),
                        **({"offset_px": mi.get("offset_px")} if et == "slide_up" else {})},
              observed={**mo, "dur_s_compared": d_obs},
              tolerance=(f"종류 일치, 길이 ±{MOTION_DUR_TOL_FRAMES:g}프레임, pop 첫 프레임 배율 오차 ≤ 0.08(+35% 여유), "
                         f"slide 첫 프레임 이동 ±max({SLIDE_OFFSET_TOL[0]:g}px, {int(SLIDE_OFFSET_TOL[1] * 100)}%)+1프레임 이동량"),
              status="same" if ok else "different", keys=keys,
              evidence={"t": m.get("onset"), "frame": m.get("evidence_frame")}, note="; ".join(notes))
    # exit
    mout = cap.motion_out or {}
    xt = (mout.get("type") or "none")
    xo = m.get("motion_out_obs")
    if cap.end >= float(ctx.info.duration) - 1.5 * fr:
        return                                  # on screen to the last frame: there is no exit to see
    okeys = [f"text.roles.{role}.motion_out.type"]
    item = f"자막 퇴장 모션 {label}"
    if xt not in MEASURABLE_MOTION_OUT:
        b.add("caption.motion", f"{cap.id}:out", item, CAT["cap_motion"], expected=mout, observed=xo,
              status="unmeasured", evidence={"t": cap.end},
              note=f"퇴장 모션 '{xt}' 은 출력에서 측정하지 않음(fade/none 만 측정) — 같다고 판정하지 않음")
        return
    if xo is None:
        b.add("caption.motion", f"{cap.id}:out", item, CAT["cap_motion"], expected=mout, observed=None,
              status="unmeasured", keys=okeys, evidence={"t": cap.end},
              note=m.get("offset_note") or "퇴장 시점을 측정하지 못해 퇴장 모션 판정 불가")
        return
    ok = xo.get("type") == xt
    notes = []
    d_obs = xo.get("fade_dur_s") if xt == "fade" else None
    if ok and xt == "fade":
        if d_obs is None:
            notes.append("페이드 길이는 측정하지 못해 판정에서 뺌")
        else:
            okeys.append(f"text.roles.{role}.motion_out.dur_s")
            if abs(float(d_obs) - float(mout.get("dur_s") or 0.0)) > tol_d:
                ok = False
                notes.append(f"페이드 길이 {d_obs}s (기대 {mout.get('dur_s')}s)")
    b.add("caption.motion", f"{cap.id}:out", item, CAT["cap_motion"],
          expected={"type": xt, "dur_s": mout.get("dur_s")}, observed={**xo, "dur_s_compared": d_obs},
          tolerance=f"종류 일치(fade/none), 페이드 길이 ±{MOTION_DUR_TOL_FRAMES:g}프레임(완전 표시 마지막 프레임 → 완전 소거 첫 프레임)",
          status="same" if ok else "different", keys=okeys, evidence={"t": m.get("offset")}, note="; ".join(notes))


def _motion_ref_row(b: "RowBuilder", role: str, rc_found: list[dict], na: dict, fr: float) -> None:
    """Entrance AND exit motion of a role vs the reference: the modal measured types (and the median durations /
    pop start scale when measured) against the preset.  Keys that were not measured are left out of the row."""
    tin = [(m.get("motion_in_obs") or {}) for m in rc_found if m.get("motion_in_obs")]
    tout = [(m.get("motion_out_obs") or {}) for m in rc_found if m.get("motion_out_obs")]
    k = lambda n: f"text.roles.{role}.{n}"   # noqa: E731
    obs: dict = {}
    keys: list[str] = []
    if tin:
        obs["in_type"] = _mode([_mi_type(x.get("type")) for x in tin])
        keys.append(k("motion_in.type"))
        pin = _mi_type(b.pget(k("motion_in.type")))
        if pin not in MEASURABLE_MOTION_IN:
            obs = None
    if obs is not None and tin and obs.get("in_type") == "slide_up":
        sl = [x for x in tin if _mi_type(x.get("type")) == "slide_up" and x.get("slide_measured")]
        ds = [x.get("dur_s") for x in sl if x.get("dur_s") is not None]
        if ds:
            obs["in_dur_s"] = _r(_median(ds), 3)
            keys.append(k("motion_in.dur_s"))
        so = [x.get("offset_px") for x in sl if x.get("offset_px") is not None]
        if so and k("motion_in.offset_px") not in na:
            obs["in_offset_px"] = _r(_median(so), 2)
            keys.append(k("motion_in.offset_px"))
    if obs is not None and tin and obs.get("in_type") in ("pop", "fade"):
        ds = [x.get("fade_dur_s") if obs["in_type"] == "fade" else x.get("dur_s") for x in tin if x.get("type") == obs["in_type"]]
        ds = [d for d in ds if d is not None]
        if ds:
            obs["in_dur_s"] = _r(_median(ds), 3)
            keys.append(k("motion_in.dur_s"))
        sf = [x.get("scale_first") for x in tin if x.get("type") == "pop" and x.get("scale_first") is not None]
        if obs["in_type"] == "pop" and sf:
            obs["in_scale_first"] = _r(_median(sf), 3)
            keys.append(k("motion_in.scale_from"))
    if obs is not None and tout:
        obs["out_type"] = _mode([x.get("type") for x in tout])
        keys.append(k("motion_out.type"))
        pout = b.pget(k("motion_out.type"))
        if pout not in MEASURABLE_MOTION_OUT:
            obs = None
        elif obs["out_type"] == "fade":
            ds = [x.get("fade_dur_s") for x in tout if x.get("type") == "fade" and x.get("fade_dur_s") is not None]
            if ds:
                obs["out_dur_s"] = _r(_median(ds), 3)
                keys.append(k("motion_out.dur_s"))
    tol_d = MOTION_DUR_TOL_FRAMES * fr + 0.005

    def cmp(o, r):
        parts = []
        if "in_type" in o:
            parts.append(o["in_type"] == _mi_type(r.get(k("motion_in.type"))))
        if "in_offset_px" in o:
            ro_ = abs(float(r.get(k("motion_in.offset_px")) or 0.0))
            parts.append(abs(o["in_offset_px"] - ro_) <= slide_offset_tol(ro_, b.pget(k("motion_in.dur_s")), fr))
        if "out_type" in o:
            parts.append(o["out_type"] == r.get(k("motion_out.type")))
        if "in_dur_s" in o:
            parts.append(abs(o["in_dur_s"] - float(r.get(k("motion_in.dur_s")) or 0)) <= tol_d)
        if "out_dur_s" in o:
            parts.append(abs(o["out_dur_s"] - float(r.get(k("motion_out.dur_s")) or 0)) <= tol_d)
        if "in_scale_first" in o:
            sf = float(r.get(k("motion_in.scale_from")) or 1.0)
            parts.append(abs(o["in_scale_first"] - sf) <= TOL["scale_first"] + abs(sf - 1.0) * 0.35)
        return _all(*parts)
    note = ("레퍼런스 대비 등장·퇴장 모션: 측정한 최빈 종류와 길이(중앙값)·pop 첫 배율·slide 첫 프레임 이동을 비교"
            "(레퍼런스의 'slide' = 렌더러의 'slide_up'); 측정 못 한 키는 행에서 뺌"
            if obs is not None else "프리셋 모션 종류가 출력에서 측정하지 않는 종류 — 못 잼")
    b.style_row("caption.motion", f"{role}_ref", f"자막 등장·퇴장 모션 [{role}] (레퍼런스 대비)", CAT["cap_motion"],
                keys or [k("motion_in.type"), k("motion_out.type")], obs if obs else None, cmp, na=na, note=note)


LEAD_TOL_S = 0.1     # + one frame: the speech edges come from the energy-extent speech detector shared with the
                    # reference analyzer (edit.audio_checks.speech_spans = reference.audio_original segments)


def dialogue_leads(caps: list, meas: dict, speech: dict) -> list[dict]:
    """lead_s of each dialogue caption in the OUTPUT with the reference analyzer's definition (reference.textboxes:
    caption start - start of the earliest speech span overlapping the caption): caption onset measured in the output,
    speech = the kept voice measured in the output (mix minus BGM and SFX, probes_audio.kept_audio_checks)."""
    out = []
    spans = [(float(a), float(c)) for a, c in (speech.get("spans") or [])] if speech.get("status") == "measured" else None
    for cap in caps:
        m = meas.get(cap.id) or {}
        on, off = m.get("onset"), m.get("offset")
        rec = {"caption": cap.id, "onset": on, "offset": off}
        if on is None:
            rec["reason"] = "자막 등장 시각 못 잼"
        elif spans is None:
            rec["reason"] = "출력 말소리 못 잼: " + str(speech.get("reason") or "오디오 측정 없음")
        else:
            end = float(off if off is not None else cap.end)
            ov = [(a, c) for a, c in spans if min(end, c) - max(float(on), a) > 0]
            if not ov:
                rec["reason"] = "자막과 겹치는 출력 말소리 없음(기준 사건 없음)"
            else:
                a0 = min(a for a, _ in ov)
                rec.update({"speech_onset": _r(a0, 3), "lead_s": _r(float(on) - a0, 3)})
        out.append(rec)
    return out


def _lead_ref_row(b: "RowBuilder", caps_r: list, meas: dict, probes: dict, fr: float) -> None:
    """caption.timing:dialogue_lead_ref -- text.roles.dialogue.timing.lead_s vs the leads measured in the output."""
    sp = ((((probes.get("audio") or {}).get("originals") or {}).get("voice_out") or {}).get("speech") or {})
    leads = dialogue_leads(caps_r, meas, sp)
    got = [x["lead_s"] for x in leads if x.get("lead_s") is not None]
    tol = LEAD_TOL_S + fr
    b.style_row("caption.timing", "dialogue_lead_ref", "대사 자막 등장 − 말소리 시작 (레퍼런스 대비)", CAT["cap_timing"],
                ["text.roles.dialogue.timing.lead_s"],
                {"lead_s": _r(_median(got), 3), "per_caption": leads} if got else None,
                lambda o, r: abs(o["lead_s"] - float(r["text.roles.dialogue.timing.lead_s"] or 0.0)) <= tol,
                evidence={"t": next((x["onset"] for x in leads if x.get("lead_s") is not None), None)},
                note=(f"정의(레퍼런스 분석기와 같음): 대사 자막 시작 − 겹치는 말소리 시작, 둘 다 출력에서 잼(자막 등장 = 문자 검사, "
                      f"말소리 = 출력 − BGM·효과음의 음성 구간); 허용 ±{tol:.3f}s"
                      + ("" if got else " — " + "; ".join(f"{x['caption']}: {x.get('reason')}" for x in leads))))


def _style_ref_row(b: "RowBuilder", role: str, rc_found: list[dict], caps_r: list, na: dict) -> None:
    """Colour / outline / box of a role vs the reference: medians of what was measured in the output (fill colour,
    outline thickness and colour where the outline stands out from the background, box opacity where measurable)."""
    k = lambda n: f"text.roles.{role}.{n}"   # noqa: E731
    fills = [m.get("fill_color") for m in rc_found if m.get("fill_color")]
    if not fills:
        b.style_row("caption.style", f"{role}_ref", f"자막 색·외곽선·박스 [{role}] (레퍼런스 대비)", CAT["cap_style"],
                    [k("color")], None, lambda o, r: None, na=na)
        return
    from . import hex_rgb, rgb_hex

    med = lambda cs: rgb_hex(tuple(_median([hex_rgb(c)[i] for c in cs]) for i in range(3)))   # noqa: E731
    obs: dict = {"fill_color": med(fills)}
    keys = [k("color")]
    meas_ol = [m for m in rc_found if (m.get("outline_bg_same_color_frac") or 0) < 0.5 and m.get("outline_px_obs") is not None]
    if meas_ol:
        obs["outline_px"] = _median([float(m["outline_px_obs"]) for m in meas_ol])
        keys.append(k("outline_px"))
        ocs = [m.get("outline_color") for m in meas_ol if m.get("outline_color")]
        if ocs and k("outline_color") not in na:
            obs["outline_color"] = med(ocs)
            keys.append(k("outline_color"))
    bas = [box_alpha_obs(m) for m in rc_found if box_alpha_obs(m) is not None]
    if bas:
        obs["box_alpha"] = _median(bas)
        keys.append(k("box.enabled"))
        if k("box.alpha") not in na:
            keys.append(k("box.alpha"))
    lss = [line_style_summary(m) for m in rc_found]
    sh = [x["shadow_px"] for x in lss if x["shadow_px"] is not None]
    if sh:
        obs["shadow_px"] = _median(sh)
        keys.append(k("shadow_px"))
        shc = [x["shadow_color"] for x in lss if (x["shadow_px"] or 0) > 0 and x["shadow_color"]]
        if shc and k("shadow_color") not in na:
            obs["shadow_color"] = med(shc)
            keys.append(k("shadow_color"))
    # box padding in the reference analyzer's definition (box edge - visible ink edge: a visible outline subtracted)
    pads = [(float(x["box"]["pad_x"]), float(x["box"]["pad_y"])) for x in lss if x["box"].get("present") == "present"]
    if pads and k("box.pad_x") not in na:
        obs["box_pad"] = [_median([p[0] for p in pads]), _median([p[1] for p in pads])]
        keys += [k("box.pad_x"), k("box.pad_y")]
    bcs = [(m.get("box_color") or {}).get("color") for m in rc_found if (m.get("box_color") or {}).get("status") == "measured"]
    if bcs and k("box.color") not in na:
        obs["box_color"] = med(bcs)
        keys.append(k("box.color"))

    def cmp(o, r):
        parts = [_cwithin(o["fill_color"], r.get(k("color")), TOL["color_rgb"])]
        if "outline_px" in o:
            eo = float(r.get(k("outline_px")) or 0)
            parts.append(abs(o["outline_px"] - eo) <= max(2.0, 0.35 * eo))
        if "outline_color" in o:
            parts.append(_cwithin(o["outline_color"], r.get(k("outline_color")), TOL["color_rgb"]))
        if "box_alpha" in o:
            if not r.get(k("box.enabled")):
                parts.append(o["box_alpha"] <= 0.3)
            elif k("box.alpha") in r:
                ea = r[k("box.alpha")]
                parts.append(abs(o["box_alpha"] - float(ea if ea is not None else 1)) <= 0.2)
        if "shadow_px" in o:
            parts.append(abs(o["shadow_px"] - float(r[k("shadow_px")] or 0)) <= SHADOW_TOL_PX)
        if "shadow_color" in o:
            parts.append(_cwithin(o["shadow_color"], r[k("shadow_color")], TOL["color_rgb"]))
        if "box_pad" in o:
            parts.append(abs(o["box_pad"][0] - float(r[k("box.pad_x")] or 0)) <= PAD_TOL_PX)
            parts.append(abs(o["box_pad"][1] - float(r[k("box.pad_y")] or 0)) <= PAD_TOL_PX)
        if "box_color" in o:
            parts.append(_cwithin(o["box_color"], r[k("box.color")], TOL["color_rgb"]))
        return _all(*parts)
    b.style_row("caption.style", f"{role}_ref", f"자막 색·외곽선·그림자·박스 [{role}] (레퍼런스 대비)", CAT["cap_style"],
                keys, obs, cmp, na=na,
                note="측정한 채움색·외곽선(배경과 구별될 때)·박스 불투명도의 중앙값 + 레퍼런스 분석기와 같은 정의"
                     "(reference.textboxes.measure_line / box_alpha)로 잰 그림자·박스 여백(박스 경계 − 보이는 잉크)·박스 색; "
                     "재지 못한 키(어두운 배경의 그림자, 박스가 안 보이는 경우 등)는 행에서 뺌")


def box_alpha_obs(m: dict) -> float | None:
    """Caption box opacity in the output: the reference analyzer's regression (reference.textboxes.box_alpha, frame
    before the box vs at rest, colour-independent) when it could run, else the luminance ratio of _style_at_rest
    (1 - inside / outside luma: exact for a black box only)."""
    bc = m.get("box_color") or {}
    if bc.get("status") == "measured" and bc.get("alpha") is not None:
        return float(bc["alpha"])
    return m.get("box_alpha_obs")


SHADOW_TOL_PX = 1.0     # probes_text.drop_shadow: whole-pixel IoU search + sub-pixel parabola
PAD_TOL_PX = 2.0        # docs/validation/mockloop.md pad_px tolerance (the reference's box pad on renderer-drawn boxes)


def line_style_summary(m: dict) -> dict:
    """Drop shadow and box of one caption from its reference-definition line measurements (probes_text
    .caption_line_styles): shadow = median over the lines that could be read; box = the block box of a multi-line
    caption, else the line's box."""
    ls = m.get("line_style") or {}
    lines = [ln for ln in ls.get("lines") or [] if ln.get("status") == "measured"]
    out: dict = {"shadow_px": None, "shadow_color": None, "shadow_reason": None, "box": {}}
    sh = [float(ln["shadow_px"]) for ln in lines if ln.get("shadow_px") is not None]
    if sh:
        out["shadow_px"] = _median(sh)
        cols = [ln.get("shadow_color") for ln in lines if (ln.get("shadow_px") or 0) > 0 and ln.get("shadow_color")]
        out["shadow_color"] = cols[0] if cols else None
    elif not lines:
        out["shadow_reason"] = ls.get("error") or "줄 스타일 측정 실패(measure_line)"
    else:
        out["shadow_reason"] = "; ".join(sorted({str((ln.get("shadow") or {}).get("reason") or "측정 없음") for ln in lines}))
    blk = ls.get("block_box") or {}
    if blk.get("present") == "present":
        out["box"] = blk
    else:
        bxs = [ln.get("box") or {} for ln in lines]
        pres = [bx for bx in bxs if bx.get("present") == "present"]
        out["box"] = pres[0] if len(lines) == 1 and pres else ({"present": "absent"} if bxs and not pres else
                                                               {"present": "unmeasured"})
    return out


def _style_extras(cap, m: dict, role: str) -> tuple[dict, dict, list[str], list[str], bool]:
    """(observed, expected, keys, notes, ok) of the drop shadow, the box padding and the box colour of one caption in
    the output vs the IR (reference definitions: ``line_style_summary``, ``m['box_color']``)."""
    k = lambda n: f"text.roles.{role}.{n}"   # noqa: E731
    ls = line_style_summary(m)
    obs, exp, keys, notes, ok = {}, {"shadow_px": cap.shadow_px}, [], [], True
    esh = float(cap.shadow_px or 0.0)
    if esh > 0:
        exp["shadow_color"] = getattr(cap, "shadow_color", None)
    if ls["shadow_px"] is None:
        notes.append("그림자 못 잼(판정에서 뺌): " + str(ls["shadow_reason"]))
    else:
        obs["shadow_px"] = ls["shadow_px"]
        keys.append(k("shadow_px"))
        if abs(ls["shadow_px"] - esh) > SHADOW_TOL_PX:
            ok = False
            notes.append(f"그림자 {ls['shadow_px']}px (기대 {esh:g}px)")
        if esh > 0 and ls["shadow_px"] > 0:
            obs["shadow_color"] = ls["shadow_color"]
            c = _cwithin(ls["shadow_color"], getattr(cap, "shadow_color", None), TOL["color_rgb"])
            if c is not None:
                keys.append(k("shadow_color"))
                if not c:
                    ok = False
                    notes.append(f"그림자 색 {ls['shadow_color']} (기대 {getattr(cap, 'shadow_color', None)})")
    box = cap.box or {}
    if box.get("enabled"):
        op = float(cap.outline_px or 0.0)
        exp.update({"box_pad": [box.get("pad_x"), box.get("pad_y")], "box_pad_from_fill": [
            _r(float(box.get("pad_x") or 0) + op, 1), _r(float(box.get("pad_y") or 0) + op, 1)], "box_color": box.get("color")})
        bo = ls["box"]
        if bo.get("present") == "present":
            fx, fy = float(bo.get("pad_fill_x", bo.get("pad_x"))), float(bo.get("pad_fill_y", bo.get("pad_y")))
            obs.update({"box_pad_from_fill": [fx, fy], "box_pad": [bo.get("pad_x"), bo.get("pad_y")], "box_rect": bo.get("bbox")})
            keys += [k("box.pad_x"), k("box.pad_y")]
            ex_, ey_ = float(box.get("pad_x") or 0) + op, float(box.get("pad_y") or 0) + op
            if abs(fx - ex_) > PAD_TOL_PX or abs(fy - ey_) > PAD_TOL_PX:
                ok = False
                notes.append(f"박스 여백(글자 채움 기준) {fx:g}/{fy:g}px (기대 {ex_:g}/{ey_:g} = pad + 외곽선)")
        else:
            notes.append("박스 경계(4면 밝기 단차)를 출력에서 찾지 못해 박스 여백 못 잼(판정에서 뺌)")
        bc = m.get("box_color") or {}
        if bc.get("status") == "measured":
            obs["box_color"] = bc.get("color")
            obs["box_alpha_regression"] = bc.get("alpha")
            c = _cwithin(bc.get("color"), box.get("color"), TOL["color_rgb"])
            if c is not None:
                keys.append(k("box.color"))
                if not c:
                    ok = False
                    notes.append(f"박스 색 {bc.get('color')} (기대 {box.get('color')})")
        else:
            notes.append("박스 색 못 잼(판정에서 뺌): " + str(bc.get("reason") or "측정 없음"))
    return obs, exp, keys, notes, ok


def _shape_text_evidence(m: dict) -> dict | None:
    """Glyph-shape evidence of the caption TEXT from the font identification of the same crop: the expected
    text rendered in the expected face, per-glyph IoU vs the output (typography.identify_many)."""
    idt = ((m.get("font") or {}).get("identify") or {})
    if idt.get("status") != "measured":
        return None
    exp = str(idt.get("expected_canonical") or "").replace(" ", "").lower()
    er = next((r for r in idt.get("ranked") or [] if str(r.get("font") or "").replace(" ", "").lower() == exp), None)
    if er is None:
        return None
    return {"iou": er.get("iou"), "glyph_pass": er.get("glyph_pass"), "verdict": er.get("verdict"),
            "method": "기대 문구·기대 글꼴 렌더와 글자별 IoU(typography.identify_many)"}


FONT_VERDICT_STATUS = {"identical": "same", "different": "different", "similar": "unmeasured", "unmeasured": "unmeasured"}


def _font_row(b: RowBuilder, cap, m: dict, label: str, role: str, ev: dict) -> dict:
    """caption.font row.  'same' ONLY for typography's verdict ``identical`` (IoU >= the same-font
    ceiling p10 measured under the output's encode settings, margin over the nearest look-alike >
    noise, per-glyph check passed).  ``similar`` -> 못 잼; ``different`` -> 다르다.  The raw
    font_iou fallback (no ceiling experiment possible) can report 'different' or 못 잼, never 'same'."""
    fnt = m.get("font") or {}
    idt = fnt.get("identify") or {}
    keys = _role_keys(role, ["font_name", "bold"])
    item = f"자막 글꼴 {label} (자막 1개·정지 프레임 1장, 참고)"
    info = (f"참고 행(필수 아님): 한 crop 의 판정은 잡음이 커서 필수 판정은 역할 단위 합동 행 caption.font:role_{role} 이 "
            "한다 — 이 행의 못 잼은 관문을 막지 않지만 '다르다'는 그대로 관문(G1)에 걸린다(한 자막만 다른 글꼴일 수 있음). ")
    add = b.add

    n_fonts = len({c.font_name for c in (getattr(b.ctx.resolved, "captions", None) or []) if c.role == role})
    cover_row = f"caption.font:role_{role if n_fonts <= 1 else role + ':' + str(cap.font_name)}"

    def _add(*a, **kw):            # every per-caption font row is informational
        kw["required"] = False
        kw["note"] = info + (kw.get("note") or "")
        r = add(*a, **kw)
        r["covered_by"] = cover_row
        return r
    ex = m.get("font_exact") or {}
    if ex.get("status") == "measured":
        v = ex.get("verdict")
        st = {"identical": "same", "different": "different"}.get(v, "unmeasured")
        return _add("caption.font", cap.id, item, CAT["font"], expected=cap.font_name,
                    observed={"method": "정확 위치 재렌더", **{k: ex.get(k) for k in (
                        "verdict", "mae_planned", "noise_mae", "mae_alternatives", "best_alternative", "margin",
                        "start_frame", "crop_frames", "crop_box", "conditions")},
                              "single_crop_verdict": idt.get("verdict")},
                    tolerance="계획 글꼴 재렌더 MAE ≤ 재인코딩 잡음이고 대안보다 잡음 이상 가까우면 같다, 대안이 잡음 이상 더 가까우면 다르다",
                    status=st, keys=keys, evidence=ev, note=str(ex.get("reason") or ""))
    if idt.get("status") == "measured":
        v = idt.get("verdict") or "unmeasured"
        # a single-crop 'identical' is not confirmed by the exact re-render here: at most 못 잼
        st = FONT_VERDICT_STATUS.get(v, "unmeasured") if v != "identical" else "unmeasured"
        top = idt.get("top")
        top_is_exp = str(top or "").replace(" ", "").lower() == str(idt.get("expected_canonical") or "").replace(" ", "").lower()
        reasons = "; ".join(idt.get("reasons") or [])
        if v == "identical":
            note = f"한 crop 판정은 동일(identical)이나 정확 위치 재렌더로 확인되지 않아 같다고 쓰지 않음 — {reasons}"
        elif v == "similar":
            note = ("판정: 유사(similar, 동일 확정 불가) — 같다고 쓰지 않음. " + reasons +
                    ("" if top_is_exp else f"; 가장 잘 맞는 후보는 {top}"))
        elif v == "different":
            note = f"판정: 다름(different) — {reasons}" + ("" if top_is_exp else f"; 가장 잘 맞는 후보 {top}")
        else:
            note = "판정 못 잼: " + (reasons or idt.get("reason") or "")
        cond = idt.get("conditions") or {}
        ce = idt.get("ceiling") or {}
        return _add("caption.font", cap.id, item, CAT["font"], expected=cap.font_name,
                     observed={"verdict": v, "verdict_ko": idt.get("verdict_ko"), "iou_expected": idt.get("iou_expected"),
                               "margin": idt.get("margin"), "top": top, "top_verdict": idt.get("top_verdict"),
                               "ranked": (idt.get("ranked") or [])[:5],
                               "ceiling": {"p10": ce.get("p10"), "p50": ce.get("p50"), "noise_p90": ce.get("noise_p90"),
                                           "n": ce.get("n"), "size_px": ce.get("size_px"),
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
        return _add("caption.font", cap.id, item, CAT["font"], expected=cap.font_name,
                     observed={"method": "font_iou(대체 방법)", "best": fnt.get("best"), "iou_expected": exp_iou,
                               "scores": fnt.get("scores"), "same_font_ceiling_p10(fonts_report)": ceil,
                               "glyph_h": _r(glyph_h, 1)},
                     tolerance="대체 방법: 다른 글꼴이 0.03 넘게 더 잘 맞거나 IoU<0.7(글자 ≥30px) → 다르다, 그 밖은 못 잼(같다 없음)",
                     status=st, keys=keys, evidence=ev, note=note)
    return _add("caption.font", cap.id, item, CAT["font"], expected=cap.font_name, observed=None,
                 status="unmeasured", keys=keys, evidence=ev,
                 note=fnt.get("reason") or idt.get("reason") or "글꼴 비교 못 함")


def _font_role_rows(b: RowBuilder, roles: dict, error: str | None = None) -> None:
    """caption.font:role_<role> -- the REQUIRED font rows.  'same' ONLY for the pooled verdict ``identical``
    (font_id.identify_role_font: median IoU of every rest-frame crop of the role >= the p10 of the median of as many
    true-font crops (bootstrap from the ceiling samples), margin over the runner-up > noise, per-glyph rule passed);
    ``different`` -> 다르다; ``similar`` / unmeasured -> 못 잼."""
    ctx = b.ctx
    by_role: dict[str, list] = {}
    for cap in ctx.resolved.captions:
        by_role.setdefault(cap.role, []).append(cap)
    done = set()
    for subject, r in sorted(roles.items()):
        role = r.get("role") or subject.split(":")[0]
        done.add(role)
        caps = [c for c in by_role.get(role, []) if ":" not in subject or c.font_name == subject.split(":", 1)[1]]
        keys = _role_keys(role, ["font_name", "bold"])
        item = f"자막 글꼴 [{subject}] (역할 단위: 자막 {len(caps)}개의 정지 프레임 합동)"
        v = r.get("verdict") or "unmeasured"
        st = FONT_VERDICT_STATUS.get(v, "unmeasured") if r.get("status") == "measured" else "unmeasured"
        crops = r.get("crops") or []
        ev_crop = next((c for c in crops if c.get("iou_expected") is not None), None)
        ev = {"t": ev_crop.get("t") if ev_crop else None}
        miss = r.get("captions_without_crops") or []
        tail = (f" crop 을 얻지 못한 자막: {', '.join(miss)}." if miss else "")
        if r.get("status") != "measured":
            b.add("caption.font", f"role_{subject}", item, CAT["font"], expected=r.get("expected"), observed=None,
                  status="unmeasured", keys=keys, evidence=ev, required=True,
                  note=("판정 못 잼: " + (r.get("reason") or "") + tail).strip())
            continue
        reasons = "; ".join(r.get("reasons") or [])
        top_is_exp = str(r.get("top") or "").replace(" ", "").lower() == \
            str(r.get("expected_canonical") or "").replace(" ", "").lower()
        if v == "identical":
            note = f"판정: 동일(identical) — {reasons}"
        elif v == "similar":
            note = "판정: 유사(similar, 동일 확정 불가) — 같다고 쓰지 않음. " + reasons + \
                ("" if top_is_exp else f"; 가장 잘 맞는 후보는 {r.get('top')}")
        elif v == "different":
            note = f"판정: 다름(different) — {reasons}" + ("" if top_is_exp else f"; 가장 잘 맞는 후보 {r.get('top')}")
        else:
            note = "판정 못 잼: " + reasons
        ce = r.get("ceiling") or {}
        cond = r.get("conditions") or {}
        b.add("caption.font", f"role_{subject}", item, CAT["font"], expected=r.get("expected"),
              observed={"verdict": v, "verdict_ko": r.get("verdict_ko"), "iou_expected_median": r.get("iou_expected"),
                        "iou_stats": r.get("iou_stats"), "n_crops": r.get("n_crops"), "n_captions": r.get("n_captions"),
                        "margin": r.get("margin"), "runner_up": r.get("runner_up"), "top": r.get("top"),
                        "ranked": (r.get("ranked") or [])[:5],
                        "ceiling_of_median": {k: ce.get(k) for k in ("p10", "p50", "p90", "noise_p90", "n_crops", "method")},
                        "glyph": r.get("glyph"),
                        "crops": [{k: c.get(k) for k in ("caption", "delay_frames", "t", "iou_expected")} for c in crops],
                        "other_font": r.get("other_font"),
                        "exact_render": _exact_summary(r.get("exact")),
                        "conditions": {k: cond.get(k) for k in ("label", "crf", "x264_preset", "renderer", "assumed",
                                                                "source")}},
              tolerance="같다 = 정확 위치 재렌더(계획 글꼴로 출력과 같은 ASS 이벤트·libass·bt709·x264 설정·같은 키 프레임에서 "
                        "다시 그림)가 출력 crop 과 재인코딩 잡음 이내로 같고 대안 글꼴 재렌더보다 잡음 이상 가까움(합동 통계가 '다름'이 아닐 때); "
                        "다르다 = 대안 글꼴 재렌더가 잡음 이상 더 가깝거나 합동 통계가 다름; 그 밖(합동 통계만 동일·유사)은 못 잼",
              status=st, keys=keys, evidence=ev, required=True, note=(note + tail).strip())
    for role in sorted(by_role):
        if role in done:
            continue
        b.add("caption.font", f"role_{role}", f"자막 글꼴 [{role}] (역할 단위)", CAT["font"],
              expected=by_role[role][0].font_name, observed=None, status="unmeasured",
              keys=_role_keys(role, ["font_name", "bold"]), required=True,
              note="판정 못 잼: " + (error or "역할 단위 글꼴 측정 결과 없음"))


def _exact_summary(ex: dict | None) -> dict | None:
    if not ex:
        return None
    return {"role_verdict": ex.get("exact_role_verdict"), "pooled_verdict": ex.get("pooled_verdict"),
            "alternatives": ex.get("alternatives"), "error": ex.get("error"),
            "captions": {cid: {k: e.get(k) for k in ("verdict", "mae_planned", "noise_mae", "mae_alternatives",
                                                   "best_alternative", "margin", "start_frame", "crop_frames", "reason")}
                         for cid, e in (ex.get("captions") or {}).items()}}


def _font_obs(face: str | None) -> dict | None:
    """Observed font of a role for the reference row: the identified face and whether it is bold (its OS/2 weight
    >= typography.BOLD_MIN_WEIGHT, read with the renderer's parser); bold None when the weight cannot be read."""
    if not face:
        return None
    try:
        from ..reference.typography import BOLD_MIN_WEIGHT, face_weight

        w, why = face_weight(face)
    except Exception as e:  # never a guessed weight
        w, why, BOLD_MIN_WEIGHT = None, f"{type(e).__name__}: {e}", None
    return {"best": face, "weight_class": w, "bold": None if w is None else bool(w >= BOLD_MIN_WEIGHT),
            **({"weight_note": why} if w is None else {})}


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
ZOOM_DUR_TOL_FRAMES = 2.0     # measured on the test renders: 0.357 vs 0.35 s, 0.467 / 0.476 vs 0.5 s (30 fps)


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
            if e.get("continuous"):
                # same shot continues (next source frame, same source/speed/geometry): nothing may jump here
                t_ok = o.get("type") == "none"
                b.add("video.cuts", bd["clip_id"], f"컷 위치 [{bd['clip_id']} 시작 — 같은 장면 이어짐]", CAT["cut"],
                      expected={"t": e["t"], "visible_change": False, "continuous": True},
                      observed={"t": o.get("t"), "type": o.get("type"), "score": o.get("score")},
                      tolerance="끊김 없음(같은 소스의 다음 프레임으로 이어지는 편집점)", status="same" if t_ok else "different",
                      evidence={"t": e["t"]},
                      note="계획상 같은 장면이 이어지는 편집점 — 화면 변화가 없어야 맞음" +
                           ("" if t_ok else "; 출력에서 끊김(컷)이 보임"))
            else:
                t_ok = o.get("t") is not None and (abs(o["t"] - e["t"]) <= fr + 1e-3 if e["type"] != "flash"
                                                   else bd.get("timing_ok"))
                mb = o.get("mapping") or {}
                b.add("video.cuts", bd["clip_id"], f"컷 위치 [{bd['clip_id']} 시작]", CAT["cut"],
                      expected={"t": e["t"]}, observed={"t": o.get("t"), "type": o.get("type"),
                                                        **({"method": "mapping"} if o.get("method") == "mapping" else {})},
                      tolerance="±1프레임(플래시는 플래시 구간 안)", status="same" if t_ok else "different",
                      evidence={"t": o.get("t") if o.get("t") is not None else e["t"]},
                      note=("화면 차이 급변은 약하지만(비슷한 두 장면) 경계 앞뒤 프레임이 각각 계획한 소스 프레임과 맞음"
                            if o.get("method") == "mapping" else
                            "" if o.get("type") != "none" else
                            "경계에서 화면 변화가 감지되지 않음" + (f" (경계 앞뒤 소스 대조로도 구별 못 함: {mb.get('reason') or mb})"
                                                           if mb else "")))
            ttype = e["type"]
            # the row verifies a preset key only where this boundary uses the preset's value (a plan's own choice of
            # transition / duration / colour is verified against the plan, not credited to the preset key)
            keys = ["motion.transitions.default"] if ttype == b.pget("motion.transitions.default") else []
            if ttype in ("flash", "crossfade") and bd["type_ok"] and bd.get("timing_ok") is not None and \
                    abs(float(e.get("dur") or 0) - _num(b.pget(f"motion.transitions.{ttype}.dur_s"), -1.0)) < 1e-3:
                keys.append(f"motion.transitions.{ttype}.dur_s")
            okk = bd["type_ok"] and (bd.get("timing_ok") is not False)
            note = ""
            scope_obs = None
            if ttype == "flash" and o.get("type") == "flash" and e.get("color"):
                cok = _cwithin(o.get("color"), e.get("color"), TOL["color_rgb"])
                if cok is not None:
                    if _cwithin(e.get("color"), b.pget("motion.transitions.flash.color"), 1.0):
                        keys.append("motion.transitions.flash.color")
                    okk = okk and cok
                note = (f"플래시 최대 밝기 시 영상 영역 평균색 {o.get('color')} (기대 {e.get('color')}, 거리 ≤ {TOL['color_rgb']:.0f})"
                        + ("" if cok is not None else " — 색을 재지 못해 판정에서 뺌"))
            if ttype == "flash" and o.get("type") == "flash":
                so = o.get("scope_obs") or {}
                scope_obs = so.get("scope") if so.get("status") == "measured" else None
                if scope_obs is not None:
                    okk = okk and scope_obs == e.get("scope")
                    if e.get("scope") == b.pget("motion.transitions.flash.scope"):
                        keys.append("motion.transitions.flash.scope")
                    note += (f"; 플래시 범위 {scope_obs} (기대 {e.get('scope')}): 영상 영역 밖 밝아짐 "
                             f"{so.get('progress_outside')} / 안 {so.get('progress_inside')}")
                else:
                    note += "; 플래시 범위(scope)는 못 잼(판정에서 뺌): " + str(so.get("reason") or "측정 없음")
            if e.get("continuous"):
                note = "같은 장면이 이어지는 편집점: 보이는 전환이 없어야 맞음(계획 cut = 이어 붙이기)"
            b.add("video.transitions", bd["clip_id"], f"전환 종류·길이 [{bd['clip_id']}]", CAT["motion"],
                  expected={"type": ttype, "dur": e.get("dur"), **({"visible": "none"} if e.get("continuous") else {}),
                            **({"color": e.get("color"), "scope": e.get("scope")} if ttype == "flash" else {})},
                  observed={"type": o.get("type"), "dur": o.get("dur"), "score": o.get("score"),
                            **({"color": o.get("color"), "scope": scope_obs, "scope_measure": o.get("scope_obs")}
                               if o.get("type") == "flash" else {})},
                  tolerance="종류 일치, 길이 ±2프레임, 플래시 색 거리, 플래시 범위(영역/화면) 일치", status="same" if okk else "different",
                  keys=keys,
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
        if it.get("mode") in ("still_match", "still_mismatch"):
            stl = it.get("still") or {}
            same = it["mode"] == "still_match"
            b.add("video.mapping", c.id, f"소스 구간 [{c.id}]", CAT["cut"],
                  expected={"src_in": c.src_in, "src_out": c.src_out, "source": c.source_path},
                  observed={"mode": it["mode"], "ncc_planned_min": stl.get("ncc_planned_min"),
                            "ncc_planned": stl.get("ncc_planned"), "n_samples": stl.get("n_samples"),
                            **({"mismatch_times": it.get("mismatch_times")} if not same else {})},
                  tolerance=f"정지 장면(어느 시각도 두드러지지 않음): 모든 표본 시각에서 계획한 소스 프레임과 NCC ≥ "
                            f"{stl.get('threshold')} (자막·장식·가림 영역 제외)",
                  status="same" if same else "different",
                  evidence={"t": (it.get("mismatch_times") or [None])[0] if not same else
                            (it.get("samples") or [{}])[0].get("t")},
                  note="정지 장면: 계획 구간과 시각적으로 동일 (시점 특정 불가)" if same else it.get("reason", ""))
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
                # the slope comes from matched WHOLE source frames: it cannot be known better than one source frame
                # over the sampled source span (measured: 12 fps source, 1.08 s span -> 7.7 %)
                qf = float(it.get("speed_quant_frac") or 0.0)
                tolf = max(TOL["speed_frac"], qf)
                b.add("video.speed", c.id, f"재생 속도 [{c.id}]", CAT["motion"], expected=c.speed,
                      observed={"speed": so, "samples": it.get("speed_samples"), "quantisation_frac": it.get("speed_quant_frac")}
                      if so is not None else None,
                      tolerance=f"±{tolf * 100:.1f}% (기본 {int(TOL['speed_frac'] * 100)}%, 소스 1프레임/표본 구간 {qf * 100:.1f}% 중 큰 값)",
                      status="unmeasured" if so is None else ("same" if abs(so - c.speed) <= tolf * c.speed else "different"),
                      keys=["motion.speed.slowmo_factor"] if c.speed < 1 else [])
    _rows_replay(b, mp, err)
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
                znotes = ["ORB+RANSAC 유사변환 배율(출력 프레임끼리 비교, 소스 자체의 배율 변화로 나눔)"]
                keys = ["motion.zoom.scale_to"]
                if it.get("measured_dur") is not None:
                    keys.append("motion.zoom.dur_s")
                    if abs(float(it["measured_dur"]) - float(exp["dur"])) > ZOOM_DUR_TOL_FRAMES * fr + 0.005:
                        t50_ok = False
                        znotes.append(f"줌 길이 {it['measured_dur']}s (기대 {exp['dur']}s)")
                else:
                    znotes.append("줌 길이는 측정하지 못해 판정에서 뺌")
                if it.get("measured_ease"):
                    keys.append("motion.zoom.ease")
                    if str(it["measured_ease"]) != str(exp.get("ease")):
                        t50_ok = False
                        znotes.append(f"줌 가속 곡선 {it['measured_ease']} (기대 {exp.get('ease')})")
                else:
                    znotes.append("줌 가속 곡선은 측정하지 못해 판정에서 뺌")
                ro = it.get("recenter_obs") or {}
                exp_rc = bool(getattr(c.zoom, "recenter", False))
                if ro.get("status") == "measured":
                    if exp_rc == bool(b.pget("motion.zoom.recenter")):
                        keys.append("motion.zoom.recenter")
                    if bool(ro["recenter"]) != exp_rc:
                        t50_ok = False
                        znotes.append(f"줌 고정점 규칙 recenter={ro['recenter']} (기대 {exp_rc}; 측정 고정점 오차 false "
                                      f"{ro.get('err_false_px')}px / true {ro.get('err_true_px')}px)")
                    else:
                        znotes.append(f"줌 고정점이 렌더러 규칙 recenter={exp_rc} 와 맞음(오차 {ro.get('err_true_px') if exp_rc else ro.get('err_false_px')}px, "
                                      f"허용 {ro.get('tolerance_px')}px)")
                else:
                    znotes.append("줌 고정점 규칙(recenter)은 못 잼(판정에서 뺌): " + str(ro.get("reason") or "측정 없음"))
                obs = {k: it.get(k) for k in ("measured_final_ratio", "source_ratio", "zoom_ratio_corrected", "measured_t50",
                                              "measured_dur", "measured_ease", "measured_center_canvas", "max_abs_err")}
                obs["recenter"] = ro.get("recenter") if ro.get("status") == "measured" else None
                b.add("video.zoom", c.id, f"확대(줌) [{c.id}]", CAT["motion"],
                      expected={"final_ratio": it["expected_final_ratio"], "t50": it.get("expected_t50"),
                                "dur": exp["dur"], "ease": exp["ease"], "center_canvas": exp.get("center_canvas"),
                                "recenter": exp_rc},
                      observed=obs, tolerance=(f"배율 ±{TOL['zoom_ratio']}, 중간 시점 ±{it['tolerance']['t50_s']:.2f}s, "
                                               f"길이 ±{ZOOM_DUR_TOL_FRAMES:g}프레임, 가속 곡선 일치"),
                      status="same" if ratio_ok and t50_ok else "different", keys=keys,
                      evidence={"t": it.get("measured_t50")}, note="; ".join(znotes))
            else:
                dev = it.get("measured_max_dev") or 0.0
                corr = it.get("zoom_ratio_corrected")
                geo = it.get("geometry") or {}
                st, note = _no_zoom_status(it)
                b.add("video.zoom", c.id, f"줌 없음 확인 [{c.id}]", CAT["motion"], expected={"final_ratio": 1.0},
                      observed={"max_dev": dev, "final_ratio": it.get("measured_final_ratio"), "source_ratio": it.get("source_ratio"),
                                "corrected": corr, "median_inliers": it.get("median_inliers"), "spread": it.get("measured_spread"),
                                **({"geometry": {k: geo.get(k) for k in ("confirmed", "ncc_median", "ncc_min", "alt_gap_median")}}
                                   if geo else {})},
                      tolerance="배율 변화 ≤ 5% (8% 초과 + 안정 추정일 때만 다르다); 계획 기하 NCC ≥ 0.95 + 4% 확대보다 0.02 높으면 줌 없음",
                      status=st, required=False, note=note)
        mc = b.pget("motion.zoom.max_consecutive")
        if mc is not None:
            b.add("video.zoom", "max_consecutive", "연속 세그먼트 줌 횟수(같은 효과 쌓기 금지)", CAT["motion"],
                  expected={"max": mc}, observed={"measured": zm.get("max_consecutive_measured")}, tolerance="이하",
                  status="same" if (zm.get("max_consecutive_measured") or 0) <= int(mc) else "different",
                  keys=["motion.zoom.max_consecutive"])
        zm_meas = [it for it in zm["clips"] if it.get("expected") and it.get("status") == "measured"]
        zoom_obs = [it["measured_final_ratio"] for it in zm_meas]
        z_obs = {"final_ratio": _median(zoom_obs)} if zoom_obs else None
        z_keys = ["motion.zoom.scale_to"]
        if z_obs is not None:
            zd = [it["measured_dur"] for it in zm_meas if it.get("measured_dur") is not None]
            ze = [it["measured_ease"] for it in zm_meas if it.get("measured_ease")]
            if zd:
                z_obs["dur_s"] = _r(_median(zd), 3)
                z_keys.append("motion.zoom.dur_s")
            if ze:
                z_obs["ease"] = _mode(ze)
                z_keys.append("motion.zoom.ease")
            zr = [bool((it.get("recenter_obs") or {})["recenter"]) for it in zm_meas
                  if (it.get("recenter_obs") or {}).get("status") == "measured"]
            if zr:
                z_obs["recenter"] = _mode(zr)
                z_keys.append("motion.zoom.recenter")

        def _zoom_same(o, r):
            parts = [abs(o["final_ratio"] - float(r["motion.zoom.scale_to"])) <= TOL["zoom_ratio"]]
            if "dur_s" in o:
                parts.append(abs(o["dur_s"] - float(r["motion.zoom.dur_s"])) <= ZOOM_DUR_TOL_FRAMES * fr + 0.005)
            if "ease" in o:
                parts.append(str(o["ease"]) == str(r["motion.zoom.ease"]))
            if "recenter" in o:
                parts.append(bool(o["recenter"]) == bool(r["motion.zoom.recenter"]))
            return _all(*parts)
        b.style_row("video.zoom", "zoom_ref", "줌 배율·길이·가속 곡선·고정점 규칙 (레퍼런스 대비)", CAT["motion"], z_keys, z_obs,
                    _zoom_same, note="고정점 규칙(recenter) = 출력에서 잰 줌 고정점이 렌더러 규칙(edit.resolve.src_to_region)의 "
                                     "false/true 중 어느 쪽과 맞는지; 재지 못한 키는 행에서 뺌")
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
        fl = [bd["observed"].get("dur") for bd in tr["boundaries"] if bd["observed"].get("type") == "flash"
              and bd["observed"].get("dur") is not None]
        fc = [bd["observed"].get("color") for bd in tr["boundaries"] if bd["observed"].get("type") == "flash"
              and bd["observed"].get("color")]
        cf = [bd["observed"].get("dur") for bd in tr["boundaries"] if bd["observed"].get("type") == "crossfade"
              and bd["observed"].get("dur") is not None]
        fsc = [((bd["observed"].get("scope_obs") or {}).get("scope")) for bd in tr["boundaries"]
               if bd["observed"].get("type") == "flash" and (bd["observed"].get("scope_obs") or {}).get("status") == "measured"]
        types = [bd["observed"].get("type") for bd in tr["boundaries"] if bd["observed"].get("type") != "none"]
        t_obs = {"mode": _mode(types)} if types else None
        t_keys = ["motion.transitions.default"]
        if t_obs is not None:
            if fl:
                t_obs["flash_dur"] = _r(_median(fl), 3)
                t_keys.append("motion.transitions.flash.dur_s")
            if fc:
                t_obs["flash_color"] = fc[0]
                t_keys.append("motion.transitions.flash.color")
            if cf:
                t_obs["crossfade_dur"] = _r(_median(cf), 3)
                t_keys.append("motion.transitions.crossfade.dur_s")
            if fsc:
                t_obs["flash_scope"] = _mode(fsc)
                t_keys.append("motion.transitions.flash.scope")

        def _tr_same(o, r):
            parts = [o["mode"] == r["motion.transitions.default"]]
            if "flash_dur" in o:
                parts.append(abs(o["flash_dur"] - float(r["motion.transitions.flash.dur_s"])) <= 2 * fr + 1e-3)
            if "crossfade_dur" in o:
                parts.append(abs(o["crossfade_dur"] - float(r["motion.transitions.crossfade.dur_s"])) <= 2 * fr + 1e-3)
            if "flash_color" in o:
                parts.append(_cwithin(o["flash_color"], r["motion.transitions.flash.color"], TOL["color_rgb"]))
            if "flash_scope" in o:
                parts.append(o["flash_scope"] == r["motion.transitions.flash.scope"])
            return _all(*parts)
        b.style_row("video.transitions", "transitions_ref", "전환 종류·길이·플래시 색·범위 (레퍼런스 대비)", CAT["motion"],
                    t_keys, t_obs, _tr_same,
                    note="플래시 범위 = 플래시 정점에서 영상 영역 밖(자막·장식 제외)이 플래시 색으로 밝아졌는지(canvas) 아닌지(region); "
                         "재지 못한 키는 행에서 뺌")
    if ctx.resolved.clips and any(abs(float(c.speed or 1) - 1) > 1e-3 for c in ctx.resolved.clips):
        sp = [x.get("speed_obs") for x in (mp or {}).get("clips", []) if x.get("speed_obs") is not None]
        slow = [s for s in sp if s < 0.95]
        b.style_row("video.speed", "speed_ref", "느린 재생 배율 (레퍼런스 대비)", CAT["motion"], ["motion.speed.slowmo_factor"],
                    {"slowmo": _median(slow)} if slow else None,
                    lambda o, r: abs(o["slowmo"] - float(r.get("motion.speed.slowmo_factor", 1))) <= 0.05)


REPLAY_MIN_OVERLAP_S = 0.05    # = edit.validate segment_repeat: a source span shown twice for longer than this


def _measured_src_span(it: dict | None) -> tuple[float, float] | None:
    """The SOURCE span a clip showed in the output, from the mapping probe: the planned span shifted by the measured
    offset (a still scene that matched its planned frames: the planned span); None = not measured."""
    if not it or it.get("status") != "measured" or not it.get("expected_src"):
        return None
    a, b_ = (float(x) for x in it["expected_src"][:2])
    if it.get("mode") == "still_match":
        return a, b_
    if it.get("mode") == "still_mismatch" or it.get("offset_p50") is None:
        return None
    off = float(it["offset_p50"])
    return a + off, b_ + off


def _rows_replay(b: RowBuilder, mp: dict | None, err: dict) -> None:
    """video.replay: the same source frames shown twice in the output (measured source spans of two clips of one
    source overlap).  A deliberate replay is marked in the plan (the later segment's ``replay_of`` = the earlier one
    + ``replay_reason``); an unmarked repeat (padding the length) is 다르다.  A pair with a clip whose source span was
    not measured is 못 잼 when the plan spans could overlap."""
    ctx = b.ctx
    segs = {s_.get("id"): s_ for s_ in ((ctx.plan or {}).get("timeline") or [])}
    items = {x.get("clip_id"): x for x in ((mp or {}).get("clips") or [])}
    clips = list(ctx.resolved.clips)
    pairs, blind = [], []
    for i, a in enumerate(clips):
        for c in clips[i + 1:]:
            if a.source_path != c.source_path:
                continue
            plan_ov = min(a.src_out, c.src_out) - max(a.src_in, c.src_in)
            sa, sc = _measured_src_span(items.get(a.id)), _measured_src_span(items.get(c.id))
            if sa is None or sc is None:
                if plan_ov > -0.5:          # the spans are close enough that a measured shift could make them overlap
                    blind.append({"clips": [a.id, c.id], "why": "소스 구간을 출력에서 재지 못한 클립이 있음"})
                continue
            ov = min(sa[1], sc[1]) - max(sa[0], sc[0])
            if ov <= REPLAY_MIN_OVERLAP_S:
                continue
            seg = segs.get(c.id) or {}
            marked = seg.get("replay_of") == a.id and bool(str(seg.get("replay_reason") or "").strip())
            pairs.append({"first": a.id, "again": c.id, "overlap_s": _r(ov, 3), "src_first": [_r(x, 3) for x in sa],
                          "src_again": [_r(x, 3) for x in sc], "marked_replay": marked,
                          **({"replay_reason": seg.get("replay_reason")} if marked else {}), "t": _r(c.out_start, 3)})
    unmarked = [x for x in pairs if not x["marked_replay"]]
    st = "different" if unmarked else ("unmeasured" if blind else "same")
    if mp is None:
        st = "unmeasured"
    b.add("video.replay", "all", "같은 원본 장면 반복(표시 없는 다시보기) 0", CAT["cut"],
          expected={"unmarked_repeats": 0, "min_overlap_s": REPLAY_MIN_OVERLAP_S},
          observed={"repeats": pairs, "not_measured": blind} if mp is not None else None,
          tolerance=f"같은 소스 구간이 두 번 {REPLAY_MIN_OVERLAP_S}s 넘게 보이면 plan replay_of + replay_reason 표시가 있어야 함",
          status=st, required=True, evidence={"t": unmarked[0]["t"]} if unmarked else {},
          note=("측정 실패: " + str(err.get("mapping") or err.get("scan") or "")) if mp is None else
          ("표시 없는 반복(분량 채우기 금지): " + ", ".join(f"{x['first']}→{x['again']} {x['overlap_s']}s" for x in unmarked)
           if unmarked else ("의도한 다시보기(plan 표시): " + ", ".join(f"{x['first']}→{x['again']}" for x in pairs)
                             if pairs else "출력에서 잰 클립별 소스 구간이 서로 겹치지 않음")))


# ----------------------------------------------------------------------------- decorations
DECO_STROKE_TOL_PX = 2.0      # test-coverage-001: circle 9.3 px vs 10, box 7.6 px vs 8 (anti-aliased ring width)
DECO_SIZE_TOL_FRAC = 0.1      # test-pipeline-001 arrow: longest side 118 px vs size_px 120


ARROW_GEOMETRY = ("head_len_ratio", "head_width_ratio", "shaft_width_ratio")


def _deco_style(b: RowBuilder, d, m: dict, ag: dict | None = None) -> tuple[dict, list[str], list[str], bool]:
    """(observed, compared preset keys, notes, ok) of a decoration's own look in the output: colour for every kind,
    ring width (stroke_px) of circles / boxes, length (size_px) of arrows, and for arrows the head / shaft proportions
    and the outline width / colour measured by the reference analyzer's detector on the output (``ag``:
    probes_video.analyze_arrow_geometry item).  A preset key is listed only when the plan's value is the preset's."""
    kk = d.kind
    st = d.style or {}
    obs = {"color": m.get("color_obs")}
    keys, notes, ok = [], [], True
    c = _cwithin(m.get("color_obs"), st.get("color"), TOL["color_rgb"])
    if c is not None:
        keys.append(f"decorations.{kk}.color")
        ok = ok and c
        if not c:
            notes.append(f"색 {m.get('color_obs')} (기대 {st.get('color')})")
    if kk in ("circle", "box") and m.get("stroke_px_obs") is not None and st.get("stroke_px") is not None:
        obs["stroke_px"] = m["stroke_px_obs"]
        keys.append(f"decorations.{kk}.stroke_px")
        if abs(float(m["stroke_px_obs"]) - float(st["stroke_px"])) > DECO_STROKE_TOL_PX:
            ok = False
            notes.append(f"선 두께 {m['stroke_px_obs']}px (기대 {st['stroke_px']}px)")
    so = ((m.get("position") or {}).get("size_obs"))
    if kk == "arrow" and so and st.get("size_px"):
        obs["length_px"] = max(so)
        keys.append(f"decorations.{kk}.size_px")
        if abs(max(so) - float(st["size_px"])) > DECO_SIZE_TOL_FRAC * float(st["size_px"]):
            ok = False
            notes.append(f"화살표 길이 {max(so)}px (기대 {st['size_px']}px)")
    if kk == "arrow":
        from .probes_video import ARROW_OUTLINE_TOL_PX, ARROW_RATIO_TOL

        ag = ag or {}
        if ag.get("status") != "measured":
            notes.append("화살표 머리·몸통 비율·외곽선 못 잼(판정에서 뺌): " + str(ag.get("reason") or "측정 없음"))
        else:
            for k in ARROW_GEOMETRY:
                if ag.get(k) is None or st.get(k) is None:
                    continue
                obs[k] = ag[k]
                keys.append(f"decorations.arrow.{k}")
                if abs(float(ag[k]) - float(st[k])) > ARROW_RATIO_TOL:
                    ok = False
                    notes.append(f"{k} {ag[k]} (기대 {st[k]})")
            eo = st.get("outline_px")
            if ag.get("outline_px") is not None and eo is not None:
                obs["outline_px"] = ag["outline_px"]
                keys.append("decorations.arrow.outline_px")
                if abs(float(ag["outline_px"]) - float(eo)) > ARROW_OUTLINE_TOL_PX:
                    ok = False
                    notes.append(f"외곽선 {ag['outline_px']}px (기대 {eo}px)")
                if float(eo) > 0 and ag.get("outline_color"):
                    obs["outline_color"] = ag["outline_color"]
                    oc = _cwithin(ag["outline_color"], st.get("outline_color"), TOL["color_rgb"])
                    if oc is not None:
                        keys.append("decorations.arrow.outline_color")
                        if not oc:
                            ok = False
                            notes.append(f"외곽선 색 {ag['outline_color']} (기대 {st.get('outline_color')})")
            elif eo is not None:
                notes.append("화살표 외곽선이 배경과 구별되지 않아 못 잼(판정에서 뺌)")
    return obs, keys, notes, ok


def rows_decorations(b: RowBuilder, probes: dict) -> None:
    ctx = b.ctx
    vp = probes.get("video") or {}
    dd = {d["id"]: d for d in ((vp.get("decorations") or {}).get("items") or [])}
    ag_all = {it["id"]: it for it in ((vp.get("arrows") or {}).get("items") or [])}
    if vp.get("errors", {}).get("arrows"):
        ag_all = {d.id: {"status": "unmeasured", "reason": vp["errors"]["arrows"]} for d in ctx.resolved.decorations}
    for d in ctx.resolved.decorations:
        m = dd.get(d.id)
        kk = d.kind
        if m is None or m.get("status") != "measured":
            for cid, it in (("decor.position", "장식 위치"), ("decor.brightness", "장식 밝기·깜빡임"),
                            ("decor.style", "장식 색·선 두께·크기")):
                b.add(cid, d.id, f"{it} [{d.id}·{kk}]", CAT["deco"], status="unmeasured",
                      note=(m or {}).get("reason") or (vp.get("errors") or {}).get("decorations") or "측정 실패")
            continue
        pos = m.get("position")
        # position / path: the plan's keyframes (canvas px), no preset key
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
                  status="same" if ok else "different", evidence={"t": pos["track"][0][0] if pos["track"] else d.start},
                  note="위치는 밝기와 별도로 판정(보이는 프레임만)")
        else:
            b.add("decor.position", d.id, f"장식 위치·이동 경로 [{d.id}·{kk}]", CAT["deco"],
                  expected={"keyframes": d.keyframes}, observed={"visible_fraction": m.get("visible_fraction")},
                  status="different", note="장식 색 화소를 찾지 못함(보이지 않음)")
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
        sobs, skeys, snotes, sok = _deco_style(b, d, m, ag_all.get(d.id))
        from .probes_video import ARROW_OUTLINE_TOL_PX, ARROW_RATIO_TOL

        b.add("decor.style", d.id, f"장식 색·선 두께·크기{'·머리·몸통·외곽선' if kk == 'arrow' else ''} [{d.id}·{kk}]", CAT["deco"],
              expected={k: (d.style or {}).get(k) for k in ("color", "stroke_px", "size_px", *ARROW_GEOMETRY, "outline_px",
                                                             "outline_color") if (d.style or {}).get(k) is not None},
              observed=sobs, tolerance=(f"색 거리 ≤ {TOL['color_rgb']:.0f}, 선 두께 ±{DECO_STROKE_TOL_PX:g}px, "
                                        f"화살표 길이 ±{int(DECO_SIZE_TOL_FRAC * 100)}%"
                                        + (f", 머리·몸통 비율 ±{ARROW_RATIO_TOL:g}, 외곽선 ±{ARROW_OUTLINE_TOL_PX:g}px"
                                           if kk == "arrow" else "")),
              status=("unmeasured" if not skeys else ("same" if sok else "different")), keys=skeys,
              evidence={"t": (ag_all.get(d.id) or {}).get("frame_t") or d.start},
              note="; ".join(snotes + (["머리·몸통 비율·외곽선 = 참고 분석기 검출기(reference.motion.detect_decorations)를 출력에 적용"]
                                       if kk == "arrow" else [])))
        rkeys = skeys + [f"decorations.{kk}.blink_hz"]
        robs = {**sobs, "blink_hz": oh, "on_fraction": br.get("on_fraction")}

        def _ref_same(o, r, kk=kk):
            parts = []
            if f"decorations.{kk}.color" in r:
                parts.append(_cwithin(o.get("color"), r.get(f"decorations.{kk}.color"), TOL["color_rgb"]))
            if "stroke_px" in o:
                parts.append(abs(float(o["stroke_px"]) - float(r[f"decorations.{kk}.stroke_px"])) <= DECO_STROKE_TOL_PX)
            if "length_px" in o:
                parts.append(abs(o["length_px"] - float(r[f"decorations.{kk}.size_px"])) <=
                             DECO_SIZE_TOL_FRAC * float(r[f"decorations.{kk}.size_px"]))
            for g in ARROW_GEOMETRY:
                if g in o:
                    parts.append(abs(float(o[g]) - float(r[f"decorations.arrow.{g}"])) <= ARROW_RATIO_TOL)
            if "outline_px" in o:
                parts.append(abs(float(o["outline_px"]) - float(r["decorations.arrow.outline_px"])) <= ARROW_OUTLINE_TOL_PX)
            if "outline_color" in o:
                parts.append(_cwithin(o["outline_color"], r["decorations.arrow.outline_color"], TOL["color_rgb"]))
            hz = float(r.get(f"decorations.{kk}.blink_hz") or 0)
            if hz <= 0:              # no blinking: lit (almost) the whole time it is shown, like decor.brightness
                parts.append(False if o.get("blink_hz") is not None else
                             (None if o.get("on_fraction") is None else float(o["on_fraction"]) >= 0.9))
            else:
                parts.append(None if o.get("blink_hz") is None else
                             abs(float(o["blink_hz"]) - hz) <= max(TOL["blink_frac"] * hz, 0.05))
            return _all(*parts)
        b.style_row("decor.style", f"{d.id}_ref", f"장식 스타일 [{kk}] (레퍼런스 대비)", CAT["deco"], rkeys, robs, _ref_same)


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


def _logo_template_record(ctx, tdir) -> dict:
    """State of ``<logo_templates_dir>/manifest.json`` (written by `shortkit ref identity-templates`), read through the
    registry's own reader (``config.artifact_record``: status measured | partial | unmeasured, blocker, and 'stale' when
    the manifest's snapshot is not the preset's fixed snapshot)."""
    from .. import config

    if not tdir:
        return {"file": None, "status": "unmeasured", "blocker": "identity_exclusions.logo_templates_dir 없음"}
    try:
        ident = config.preset_identity(ctx.preset.dir)
    except Exception:
        ident = {}
    rec = config.artifact_record("identity_exclusions.logo_templates_dir", tdir, ident)
    return rec or {"file": f"{tdir}/manifest.json", "status": "unmeasured",
                   "blocker": "기록 없음(`shortkit ref identity-templates` 미실행)"}


def _logo_template_check(ctx, tdir) -> dict:
    """identity.logo_templates: no final frame reproduces a persistent identity mark of the reference channel.
    Templates and their completeness come from the manifest of `shortkit ref identity-templates`:
      measured, templates []  -> 'same': the snapshot's reference videos carry no persistent mark (nothing to find);
      measured, templates     -> template matching over the output (normalised correlation >= 0.8 = different);
      partial / stale / unmeasured -> the template set is incomplete: a hit is still 'different', otherwise 못 잼
      (partial and stale: required, with the manifest blocker; no usable manifest: required in production)."""
    from .. import paths

    mode = getattr(ctx.resolved, "mode", "test")
    keys = ["identity_exclusions.logo_templates_dir"]
    rec = _logo_template_record(ctx, tdir)
    st_m = rec.get("status") or "unmeasured"
    stale = bool(rec.get("stale"))
    man_obs = {k: rec.get(k) for k in ("file", "status", "blocker", "source_snapshot", "templates", "review", "stale")
               if rec.get(k) is not None}
    d = paths.absp(tdir) if tdir else None
    pngs = sorted(list(d.glob("*.png")) + list(d.glob("*.jpg"))) if d and d.is_dir() else []
    complete = st_m == "measured" and not stale
    incomplete_note = ("식별 템플릿 기록이 완전하지 않음(" + ("스냅샷이 바뀜(stale)" if stale else f"상태 {st_m}") + "): "
                       + str(rec.get("blocker") or "blocker 없음") + " — `shortkit ref identity-templates` 다시 실행")
    if complete and not pngs and not rec.get("templates"):
        return {"expected": {"manifest": rec.get("file"), "persistent_marks_in_reference": 0},
                "observed": {"manifest": man_obs, "templates_compared": 0}, "status": "same", "keys": keys,
                "required": True, "tolerance": "레퍼런스 스냅샷 영상에 반복되는 식별 표시가 없으면 대조할 템플릿도 없음",
                "note": ("`shortkit ref identity-templates` 가 고정 스냅샷의 레퍼런스 영상을 모두 검사해 반복되는 채널 로고·"
                         "워터마크·핸들을 찾지 못함(templates: []) → 출력에 옮겨 올 레퍼런스 고유 표시가 없음")}
    if not pngs:
        why = ("템플릿 기록은 완료인데 템플릿 파일이 폴더에 없음: " + str(rec.get("templates")) if complete else incomplete_note)
        return {"expected": {"templates_dir": tdir, "manifest": rec.get("file")}, "observed": {"manifest": man_obs},
                "status": "unmeasured", "keys": keys,
                "required": True if (st_m == "partial" or stale or complete) else (mode == "production"),
                "note": why + " — 글자 없는 로고는 OCR 검사(identity.forbidden_text)로 잡히지 않음"}
    import cv2

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
    if hits:
        st, note = "different", "레퍼런스 식별 템플릿과 같은 모양이 출력에 있음"
    elif complete:
        st, note = "same", "기록 완료된 템플릿 전부와 대조: 일치 0건"
    else:
        st, note = "unmeasured", "있는 템플릿과는 일치 0건이지만 " + incomplete_note
    return {"expected": {"templates": [p.name for p in pngs[:20]], "manifest": rec.get("file")},
            "observed": {"hits": hits, "manifest": man_obs}, "status": st, "keys": keys, "required": True,
            "tolerance": "정규화 상관 ≥ 0.8 인 위치 0건", "evidence": {"t": hits[0]["t"]} if hits else {}, "note": note}


def rows_residual(b: RowBuilder, probes: dict) -> None:
    vp = probes.get("video") or {}
    _rows_provenance(b, vp)
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
        cvr = {}
        for smp_ in smp:
            raw = ((smp_.get("clean_verify") or {}).get("raw") or {})
            for k_ in ("max_ncc", "max_tile_ncc"):
                if raw.get(k_) is not None:
                    cvr[k_] = max(cvr.get(k_, -1.0), float(raw[k_]))
            for k_ in ("ocr_hits", "ocr_partial_hits"):
                cvr[k_] = cvr.get(k_, 0) + int(raw.get(k_) or 0)
        b.add("clean.residual", subj, f"정리한 영역 잔류 [{it['clip_id']}·{it['op']}]", CAT["logo"],
              expected={"rect_src": it["rect_src"], "src_range": it["src_range"], "residual": False},
              observed={"residual": it.get("residual"), "edge_ncc": best.get("edge_ncc"), "text_src": best.get("text_src"),
                        "text_out": best.get("text_out"), "rect_out": best.get("rect_out"),
                        **({"clean_verify": cvr} if cvr else {})},
              tolerance=("원본 오버레이와 경계 NCC < 0.55, 같은 글자 OCR 없음, 그리고 clean.verify.residual_score: 전체 경사 NCC "
                         "< 0.5, 칸(tile)별 경사 NCC 모두 < 0.6, 원래 글자와 비슷한 OCR 0건·글자 일부(부분 OCR) 0건"),
              status="different" if it.get("residual") else "same",
              keys=["render.clean.blur_sigma_ratio"] if it.get("op") == "blur" else [],
              evidence={"t": best.get("t")}, note=it.get("note", "") +
              ("" if rs.get("clean_verify_available") else " (shortkit.clean.verify 없음 → 자체 측정)"))


KIND_KO = {"logo": "로고", "watermark": "워터마크", "source_overlay": "출처 오버레이", "burned_subtitle": "원어 자막"}
CORNER_KO = {"top_left": "좌상단", "top_right": "우상단", "bottom_left": "좌하단", "bottom_right": "우하단"}


def _rows_provenance(b: RowBuilder, vp: dict) -> None:
    """Rows from the overlay provenance records (warehouse/overlays/<source sha256>.json): every
    recorded original overlay in the part of a source the episode uses is looked for in the final
    MP4; the record's own unmeasured checks (text-free static logos, corners) stay 못 잼 here."""
    ctx = b.ctx
    mode = getattr(ctx.resolved, "mode", "test")
    pv = vp.get("provenance")
    if pv is None:
        err = (vp.get("errors") or {}).get("provenance")
        if err:
            b.add("clean.residual", "prov:error", "원본 오버레이 잔류(출처 기록 대조)", CAT["logo"], status="unmeasured",
                  note=err)
        return
    if pv.get("status") != "measured":
        b.add("clean.residual", "prov:unavailable", "원본 오버레이 잔류(출처 기록 대조)", CAT["logo"], status="unmeasured",
              required=mode == "production", note=pv.get("reason") or "")
        return
    for ent in pv.get("sources") or []:
        sid = ent["source_id"]
        if ent.get("status") != "measured":
            b.add("clean.residual", f"prov:{sid}", f"원본 오버레이 검출 기록 [{sid}]", CAT["logo"],
                  expected={"record": "warehouse/overlays/<sha256>.json", "sha256": ent.get("sha256")}, observed=None,
                  status="unmeasured", required=mode == "production",
                  note=(ent.get("reason") or "") + " — 원본 로고·오버레이가 남았는지 출처 기록으로 대조할 수 없음(모서리 OCR 검사만 적용)")
            continue
        for it in ent.get("items") or []:
            kind = KIND_KO.get(it.get("kind"), it.get("kind"))
            subj = f"prov:{sid}:{it['overlay_id']}@{it['clip_id']}"
            label = f"원본 {kind} 잔류 [{it['overlay_id']} {str(it.get('text') or '')[:14]}·{it['clip_id']}] (출처 기록 대조)"
            exp = {"residual": False, "rect_src": it.get("rect_src"), "resolution_src": it.get("resolution_src"),
                   "src_range_used": it.get("src_range_used"), "record": ent.get("record")}
            if it.get("status") != "measured":
                b.add("clean.residual", subj, label, CAT["logo"], expected=exp, observed=None, status="unmeasured",
                      note=it.get("reason") or "")
                continue
            obs = {"residual": it.get("residual"), "how": it.get("how"), "max_ncc": it.get("max_ncc"),
                   "max_tile_ncc": it.get("max_tile_ncc"), "ocr_hits": it.get("ocr_hits"),
                   "ocr_partial_hits": it.get("ocr_partial_hits"), "rect_out": it.get("rect_out"),
                   "resolution_out": it.get("resolution_out"), "times": it.get("times"), "mapping": it.get("mapping")}
            thr = it.get("thresholds") or {}
            b.add("clean.residual", subj, label, CAT["logo"], expected=exp, observed=obs,
                  tolerance=(f"clean.verify.residual_score: 전체 경사 NCC < {thr.get('ncc', 0.5)}, 칸(tile)별 경사 NCC 모두 "
                             f"< {thr.get('tile_ncc', 0.6)}, 원래 글자와 비슷한 OCR(유사도 ≥ {thr.get('text_sim', 0.6)}) 0건, "
                             "글자 일부만 읽힌 부분 OCR 0건"
                             if it.get("how") == "pixels" else "잘라내기로 화면 밖(기하 계산)"),
                  status="different" if it.get("residual") else "same",
                  evidence={"t": (it.get("times") or [None])[0]},
                  note=("원본 오버레이가 최종 화면에 남아 있음" if it.get("residual") else
                        ("잘라내기로 제거됨" if it.get("how") == "removed_by_crop" else "")))
        for cu in ent.get("carried_unmeasured") or []:
            chk = cu["check"]
            if chk == "static_graphics":
                item = f"글자 없는 고정 로고 검사 [{sid}] (출처 기록)"
            elif chk == "text_overlays":
                item = f"글자 오버레이 검사 [{sid}] (출처 기록)"
            else:
                cn = chk.split(":", 1)[1]
                what = "·".join({"text": "글자", "graphic": "글자 없는 로고"}[k] for k in cu.get("unmeasured") or [])
                item = f"원본 {CORNER_KO.get(cn, cn)} {what} [{sid}] (출처 기록)"
            b.add("clean.residual", f"prov:{sid}:{chk}", item, CAT["logo"],
                  expected={"checked": True}, observed={k: v for k, v in cu.items() if k not in ("reason", "impact")},
                  status="unmeasured", required=True,
                  note="출처 기록에서 못 잼: " + str(cu.get("reason") or cu.get("doc_status") or "") +
                       (f" — 제작 영향: {cu['impact']}" if cu.get("impact") else "") +
                       (f" (코너 캡처: {cu['crop']})" if cu.get("crop") else ""))


def _protected_none_row(b: RowBuilder) -> None:
    """No protected region (faces / hands / key objects, plan sources[].protected) is shown in the output: the
    cover-up check has nothing to compare the captions and decorations with.  Required and 못 잼 -- also when the plan
    records that someone looked and found nothing to protect (``protected_reviewed``: a statement, not a measurement)
    -- until a person who watched the final MP4 records the verdict (kind watch, row cover_up.protected:none)."""
    plan = b.ctx.plan or {}
    used = {seg.get("source") for seg in plan.get("timeline") or []}
    reviewed = {s.get("id"): s.get("protected_reviewed") for s in plan.get("sources") or []
                if s.get("id") in used and s.get("protected_reviewed")}
    declared = [s.get("id") for s in plan.get("sources") or [] if s.get("id") in used and s.get("protected")]
    rec = _human_record(b, "cover_up.protected:none", "watch")
    if rec is not None:
        st, note = rec["verdict"], f"사람이 최종 MP4 를 보고 기록({rec['by']}, {rec['at']}): {rec['note']}"
    elif reviewed and len(reviewed) == len(used - {None}):
        st, note = "unmeasured", ("plan 에 '보호할 것 없음' 검토 기록(protected_reviewed)만 있음 — 선언이지 출력 측정이 아님; 손·핵심 물체를 "
                                  "가리는지는 출력에서 잴 기준이 없음(얼굴은 cover_up.faces). 사람이 보고 `shortkit qa human-check "
                                  "--kind watch --row cover_up.protected:none` 로 기록")
    elif declared:
        st, note = "unmeasured", ("plan 의 보호 영역이 출력에 보이는 구간에 없거나 출력 좌표로 옮기지 못함(보호 영역 측정 결과 없음): "
                                  + ", ".join(declared))
    else:
        st, note = "unmeasured", "plan 에 보호 영역(sources[].protected)도 '보호할 것 없음' 검토 기록도 없음 — 가림 검사 불가"
    b.add("cover_up.protected", "none", "보호 영역(얼굴·손·물체) 가림", CAT["cover_up"],
          expected={"protected_declared": declared, "protected_reviewed": reviewed or None},
          observed={"human_check": rec} if rec else None, status=st, required=True, note=note)


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
        _protected_none_row(b)
    try:
        from .probes_video import analyze_faces

        fres = analyze_faces(ctx, overlays) if ctx.options.get("faces", True) else {"status": "unmeasured", "reason": "비활성"}
    except Exception as e:
        fres = {"status": "unmeasured", "reason": f"{type(e).__name__}: {e}"}
    probes.setdefault("video", {})["faces"] = fres
    if fres.get("status") == "measured":
        hits = fres.get("covered") or []
        unsampled = fres.get("unsampled_captions") or []
        n_faces = sum(len(x.get("faces") or []) for x in fres.get("faces") or [])
        b.add("cover_up.faces", "detector", "얼굴 가림(얼굴 검출)", CAT["cover_up"], expected={"covered": 0},
              observed={"detector": fres.get("detector"), "frames": fres.get("frames"),
                        "sample_times": fres.get("sample_times"), "faces_detected": n_faces, "hits": hits[:10],
                        "unsampled_captions": unsampled,
                        "min_face_px_canvas": fres.get("min_face_px_canvas"), "resolution": fres.get("resolution")},
              tolerance="얼굴 면적 10% 초과 가림 0건 (자막이 영상 위에 보이는 동안 ≤1초 간격 검사)",
              status="different" if hits else ("unmeasured" if unsampled else "same"),
              evidence={"t": hits[0]["t"]} if hits else {},
              note=(fres.get("method") or "") +
                   ("" if (fres.get("frames") or unsampled) else " — 영상 위에 겹친 자막이 없어 가릴 수 있는 얼굴 없음") +
                   (" — 초당 1장 한도 때문에 검사하지 못한 짧은 자막: " +
                    ", ".join(f"{u['overlay']}({u['start']}–{u['end']}s)" for u in unsampled) if unsampled else ""))
    else:
        # the face check is required whether or not protected regions were declared: declared rects are the plan's,
        # the detector is the output's own evidence -- without it the row stays 못 잼 and the gate fails (G2)
        b.add("cover_up.faces", "detector", "얼굴 가림(얼굴 검출)", CAT["cover_up"], status="unmeasured",
              required=True, note=(fres.get("reason") or "얼굴 검출기 사용 불가") +
              (" — plan 보호 영역 검사가 있어도 출력의 얼굴 검출을 대신하지 않음" if checked_protected else
               " — 보호 영역 선언도 없어 가림 여부를 확인할 수 없음"))


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
    # the reference comparison is audio_bgm.is_match: track (id / title), version, tempo, used section.  Fades and the
    # loop are judged against the plan in their own rows; the BGM level (gain_db) in audio.bgm:level / level_ref.
    bkeys = [f"audio.bgm.{k}" for k in ("track_id", "title", "version", "tempo_ratio", "section_start_s")]
    if bi.get("status") == "not_planned":
        b.add("audio.bgm", "file", "BGM", CAT["music"], expected="BGM 없음(계획)", observed=None, status="unmeasured",
              required=False, note="계획에 BGM 이 없어 출력에서 찾을 파일이 없음(모르는 음악의 부재는 증명 못 함)")
    elif bi.get("status") != "measured":
        b.add("audio.bgm", "file", "BGM 곡·버전 일치", CAT["music"], expected={"path": bgm.path if bgm else None},
              observed=None, status="unmeasured", keys=bkeys[:3], note=bi.get("reason", ""))
        _bgm_match_row(b, bgm, bi)
    else:
        found = bool(bi.get("found"))
        bm = _bgm_match(b, bgm, bi)
        _bgm_clean_file_row(b, bgm, found)
        b.add("audio.bgm", "file", "BGM 곡·버전 일치(파형 대조)", CAT["music"],
              expected={"path": bgm.path, "track_id": bgm.track_id},
              observed={"presence": "present" if found else "absent", "waveform_ncc": bi.get("waveform_ncc"),
                        "local_match": bi.get("local_match"),
                        "tempo_candidates": bi.get("tempo_candidates")},
              tolerance="0.25초 창별 파형 상관 q95 ≥ 0.7 (무관한 음악 < 0.5)", status="same" if found else "different",
              keys=["audio.bgm.track_id", "audio.bgm.title", "audio.bgm.version"],
              note=("출력 믹스에서 계획한 음악 파일의 파형을 찾음" if found else
                    "계획한 음악 파일의 파형이 출력에서 확인되지 않음(다른 곡/버전?)") + f" | is_match 4요소: {bm['parts_ko']}")
        _bgm_match_row(b, bgm, bi, bm)
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
        _bgm_loop_row(b, bgm, bi)
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
        lib = _library_entry(bgm.track_id)
        # found in the mix = the library file of that track id -> its library title/version apply
        ref_obs = {"track_id": bgm.track_id, "title": lib.get("title"), "version": lib.get("version"),
                   "tempo_ratio": to, "section_start_s": so} if to is not None else None
        b.style_row("audio.bgm", "bgm_ref", "BGM 곡·버전·속도·구간 (레퍼런스 대비)", CAT["music"], bkeys, ref_obs,
                    _bgm_ref_compare,
                    note="audio_bgm.is_match: 곡(track_id/제목)·버전·속도·구간이 모두 레퍼런스와 같아야 같다"
                         + ("" if bgm.track_id else "; 계획이 파일 경로로 BGM 을 지정해 라이브러리 곡 id 가 없음 → 곡 일치는 못 잼"))
        _rows_ducking(b, ap, bi)
        _rows_bgm_level(b, bgm, bi)
        _rows_bgm_ramps(b, bi)
    _rows_original(b, ap)
    _rows_sfx(b, ap, probes)
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
                    ["audio.loudness.integrated_lufs", "audio.loudness.true_peak_db"],
                    {"integrated_lufs": il, "true_peak_db": tp_},
                    lambda o, r: _all(abs(o["integrated_lufs"] - float(r["audio.loudness.integrated_lufs"])) <= tol_lu,
                                      None if o["true_peak_db"] is None else
                                      o["true_peak_db"] <= float(r["audio.loudness.true_peak_db"]) + 0.5))
    sr_exp = b.pget("audio.sample_rate")
    sr_obs = getattr(ctx.info, "audio_rate", None)
    if sr_exp is not None:
        b.add("audio.loudness", "sample_rate", "출력 오디오 표본율", CAT["loudness"], expected=sr_exp, observed=sr_obs,
              tolerance="정확히 일치", status="unmeasured" if not sr_obs else ("same" if int(sr_obs) == int(sr_exp) else "different"),
              keys=["audio.sample_rate"], note="ffprobe 로 읽은 출력 MP4 의 오디오 표본율")


def _bgm_clean_file_row(b: RowBuilder, bgm, found: bool) -> None:
    """audio.bgm:clean_file -- the BGM heard in the output (its waveform found in the mix: row audio.bgm:file) is a
    clean music file, not audio taken from a reference video: path rule + the ONE rule shared with `episode validate`
    and the music library (``edit.audio_checks.reference_stem_match`` = ``reference.audio_bgm.reference_audio_copy``:
    sha256 against stem files, stem hashes kept in separation records and the reference media; waveform containment
    inside one stem + following that stem's level changes).  The waveform rule needs stem FILES: without any, a
    re-encoded stem copy cannot be excluded -> 못 잼 (required in production), even when a byte comparison ran."""
    ctx = b.ctx
    mode = getattr(ctx.resolved, "mode", "test")
    pth = str(bgm.path or "").replace("\\", "/")
    try:
        from ..edit.audio_checks import reference_stem_files, reference_stem_match
        from ..reference.audio_bgm import STEM_COPY_NCC, ReferenceAudio

        stems = reference_stem_files()
        n_hashes = len(ReferenceAudio.scan().hashes)
        match = reference_stem_match(pth) if (stems or n_hashes) else None
        err = None
    except Exception as e:  # never a silent pass
        stems, n_hashes, match, err, STEM_COPY_NCC = [], 0, None, f"{type(e).__name__}: {e}", None
    from .. import paths

    obs = {"path": pth, "reference_stems_compared": len(stems), "reference_hashes_compared": n_hashes,
           "stem_match": match, "stem_dirs": sorted({paths.relp(f.parent) for f in stems})[:10]}
    # the path rule of edit.validate check_audio (bgm_from_reference)
    path_bad = (pth.startswith("presets/") and ("/analysis/" in pth or "/reference/" in pth)) or "/stems/" in pth
    if path_bad or match:
        st = "different"
        note = ("레퍼런스 분석 폴더/스템 경로의 파일을 BGM 으로 사용함" if path_bad else
                f"BGM 파일이 레퍼런스에서 나온 음원: {match.get('reason') or match['stem']} (방법 {match.get('method')})")
    elif err:
        st, note = "unmeasured", f"레퍼런스 분리 음원과 대조하지 못함: {err}"
    elif not stems:
        st, note = "unmeasured", ("레퍼런스 분리 음원 파일(presets/*/analysis/*/stems)이 하나도 없어 파형 대조 대상이 없음"
                                  + (f"(sha256 {n_hashes}개와는 대조: 같은 바이트 아님)" if n_hashes else "")
                                  + " — `ref audio-analyze` 뒤 다시 검사")
    else:
        st, note = "same", (f"레퍼런스 분리 음원 {len(stems)}개·sha256 {n_hashes}개와 대조(바이트 동일·스템 안에 포함되며 "
                            "음량 변화까지 따라가는 파형): 사본 아님")
    if not found and st == "same":
        note += " (단, 출력에서 이 파일의 파형을 찾지 못함 — audio.bgm:file 행)"
    b.add("audio.bgm", "clean_file", "BGM 은 깨끗한 음원(레퍼런스에서 분리한 스템 금지)", CAT["music"],
          expected={"clean_music_file": True, "not_a_copy_of": "presets/*/analysis/*/stems/*, reference media"},
          observed=obs,
          tolerance=("레퍼런스 음원과 sha256 같음, 또는 한 스템 안에 포함(상관 ≥ "
                     f"{STEM_COPY_NCC})되고 그 스템의 음량 변화를 따라가는 파일 0개 (reference.audio_bgm.reference_audio_copy)"),
          status=st, required=(mode == "production") or st == "different", note=note)


def _bgm_loop_row(b: RowBuilder, bgm, bi: dict) -> None:
    """audio.bgm.loop: the music is shorter than the episode and loops back to section_start (plan geometry:
    ``probes_audio._planned_loop``).  Every repeat is aligned on its own in the output; each piece must start
    at section_start (same tolerance as the used section), i.e. the loop really goes back to the start of the
    used section -- a jump to another part of the song is a different section (user rule)."""
    lp = bi.get("loop")
    if not lp:
        return
    planned = lp.get("planned") or {}
    pieces = lp.get("pieces") or []
    exp_s = float(bgm.section_start_s)
    measured = [pc for pc in pieces if pc.get("section_start_obs") is not None]
    bad = [pc for pc in measured if not pc.get("found") or abs(pc["section_start_obs"] - exp_s) > TOL["bgm_section_s"]]
    repeats_measured = [pc for pc in measured if pc["piece"] > 0]
    if planned.get("error"):
        st, note = "unmeasured", planned["error"]
    elif bad:
        st, note = "different", "되감긴 조각의 시작이 사용 구간 시작과 다름: " + ", ".join(
            f"조각 {pc['piece']} {pc['section_start_obs']}s" for pc in bad)
    elif not repeats_measured:
        st, note = "unmeasured", "되감긴 조각을 잴 수 있을 만큼 길지 않음(< 0.5 s)"
    else:
        st, note = "same", ""
    b.add("audio.bgm", "loop", "BGM 반복(되감기): 조각마다 사용 구간 시작부터", CAT["music"],
          expected={"loop": True, "section_start_s": exp_s, "loop_starts_out_s": planned.get("starts_out_s"),
                    "xfade_s": planned.get("xfade_s"), "segment_s": planned.get("segment_s")},
          observed={"pieces": [{k: pc.get(k) for k in ("piece", "out", "section_start_obs", "q95", "found", "reason")}
                               for pc in pieces]},
          tolerance=f"조각마다 시작 ±{TOL['bgm_section_s']}s, 창별 파형 상관 q95 ≥ 0.7", status=st,
          keys=["audio.bgm.loop", "audio.bgm.section_start_s"],
          evidence={"t": (planned.get("starts_out_s") or [0.0])[0]}, note=note)


BGM_PART_KO = {"track_id": "곡", "song": "곡", "title": "곡(제목)", "version": "버전", "tempo_ratio": "속도",
               "section_start_s": "구간"}


def _bgm_parts_ko(checks: dict) -> str:
    ko = {True: "같다", False: "다르다", None: "못 잼"}
    return ", ".join(f"{BGM_PART_KO.get(k, k)}={ko[v]}" for k, v in checks.items())


def _bgm_match(b: RowBuilder, bgm, bi: dict) -> dict:
    """The user's BGM rule through ``shortkit.reference.audio_bgm.is_match``: same track AND same
    version AND tempo within tolerance AND same section (a different part of the same song is NOT a
    match).  Expected = the plan (file/library track, tempo, section); observed = the output mix.
    The planned file's waveform found in the mix identifies the recording (= that track and that
    version); its absence says the recording differs without telling which of the two."""
    ident = (bgm.track_id or bgm.path) if bgm is not None else None
    # the planned recording IS one version of the song: the file identifies it
    ver = f"file:{bgm.path}" if bgm is not None and bgm.path else None
    expected = {"track_id": ident, "version": ver,
                "tempo_ratio": float(bgm.tempo_ratio) if bgm is not None else None,
                "section_start_s": float(bgm.section_start_s) if bgm is not None else None}
    st = bi.get("status")
    if st == "measured" and bi.get("found"):
        so = bi.get("section_start_obs")
        ru = bi.get("runner_up_section")
        q_best = (bi.get("local_match") or {}).get("q95") or 0.0
        n_best = bi.get("waveform_ncc") or 0.0
        equiv = ru is not None and (ru.get("q95") or 0) >= q_best - 0.01 and (ru.get("ncc") or 0) >= n_best - 0.005
        sec = so
        if (so is not None and expected["section_start_s"] is not None and equiv
                and abs(so - expected["section_start_s"]) > TOL["bgm_section_s"]
                and abs(ru["section_start_s"] - expected["section_start_s"]) <= TOL["bgm_section_s"]):
            sec = ru["section_start_s"]          # the music repeats exactly: both positions sound the same
        observed = {"track_id": ident, "version": ver, "tempo_ratio": bi.get("tempo_obs"), "section_start_s": sec}
        basis = "계획한 음원 파일의 파형이 출력에서 확인됨(같은 녹음 → 곡·버전 같음)"
    elif st == "measured":
        observed = {"track_id": "(계획한 음원의 파형 없음)", "version": None, "tempo_ratio": None, "section_start_s": None}
        basis = "계획한 음원 파일의 파형이 출력에 없음 → 곡 또는 버전이 다름(둘 중 무엇인지는 못 잼)"
    else:
        observed = {"track_id": None, "version": None, "tempo_ratio": None, "section_start_s": None}
        basis = bi.get("reason") or "BGM 측정 실패"
    try:
        from ..reference.audio_bgm import is_match

        r = is_match(expected, observed, tempo_tol=TOL["bgm_tempo"], offset_tol_s=TOL["bgm_section_s"])
    except Exception as e:  # the rule itself must not be re-implemented silently
        return {"status": "unmeasured", "checks": {}, "expected": expected, "observed": observed,
                "parts_ko": "판정 못 함", "basis": f"shortkit.reference.audio_bgm.is_match 사용 불가: {type(e).__name__}: {e}"}
    return {"status": r["status"], "checks": r["checks"], "expected": expected, "observed": observed,
            "tolerance": r.get("tolerance"), "parts_ko": _bgm_parts_ko(r["checks"]), "basis": basis}


def _bgm_match_row(b: RowBuilder, bgm, bi: dict, bm: dict | None = None) -> None:
    if bgm is None or not getattr(bgm, "path", None):
        return
    bm = bm or _bgm_match(b, bgm, bi)
    b.add("audio.bgm", "match", "BGM 일치(곡 AND 버전 AND 속도 AND 구간, audio_bgm.is_match)", CAT["music"],
          expected=bm["expected"], observed={"observed": bm["observed"], "checks": bm["checks"]},
          tolerance=f"네 요소가 모두 같아야 같다(속도 ±{TOL['bgm_tempo']}, 구간 시작 ±{TOL['bgm_section_s']}s; 같은 곡 다른 부분은 다르다)",
          status=bm["status"], keys=["audio.bgm.track_id", "audio.bgm.version", "audio.bgm.tempo_ratio",
                                     "audio.bgm.section_start_s"],
          evidence={"t": 0.0}, note=f"{bm['parts_ko']} — {bm['basis']}")


def _library_entry(track_id: str | None) -> dict:
    if not track_id:
        return {}
    try:
        from ..edit.audio import lookup_track

        return dict(lookup_track(track_id)[1] or {})
    except Exception:
        return {}


def _bgm_ref_compare(o: dict, r: dict):
    """style_row compare for the reference BGM: audio_bgm.is_match against the measured preset values."""
    from ..reference.audio_bgm import is_match

    exp = {"track_id": r.get("audio.bgm.track_id"), "title": r.get("audio.bgm.title"), "version": r.get("audio.bgm.version"),
           "tempo_ratio": r.get("audio.bgm.tempo_ratio"), "section_start_s": r.get("audio.bgm.section_start_s")}
    res = is_match(exp, o, tempo_tol=TOL["bgm_tempo"], offset_tol_s=TOL["bgm_section_s"])
    return {"same": True, "different": False}.get(res["status"])


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
          keys=[], evidence={"t": exp[0][0]} if exp else {}, required=bool(exp),
          note="계획의 덕킹 구간이 출력에 있는지(깊이는 depth 행)")
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
    # 2b) the BGM ducks only under SPEECH measured in the output (the kept voice = mix minus BGM and SFX), not under
    # a kept range as a whole nor anywhere else (user rule; IR OriginalAudio.speech is what the renderer ducked under)
    _duck_speech_row(b, ap, obs, sil, fades, att, rel)
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
        # attack / release: audio.ducking:ramps rows (reference.audio_original.measure_ducking on the output)
        b.style_row("audio.ducking", "ducking_ref", "덕킹 깊이 (레퍼런스 대비)", CAT["music"],
                    ["audio.ducking.depth_db"],
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
              ("same" if mx <= TOL["silence_db"] else "different"), evidence={"t": a},
              note="정적 안의 BGM 크기(정적 앞뒤 경사 길이 audio.silence.fade_s 는 audio.silence:ramps 행)")
    span = bi.get("audible_span_obs")
    fo = float(bgm.fade_out_s or 0)
    unexpected_sil = [(x, y) for x, y in sil_obs if not any(overlaps(x, y, a - 0.15, c + 0.15) > 0.5 * (y - x) for a, c in sil)
                      and (span is None or (x > span[0] + 0.1 and y < span[1] - fo - 0.1))]
    b.add("audio.silence", "unexpected", "계획에 없는 BGM 끊김", CAT["music"], expected=[list(x) for x in sil],
          observed=[list(x) for x in unexpected_sil], tolerance="0건", status="same" if not unexpected_sil else "different",
          evidence={"t": unexpected_sil[0][0]} if unexpected_sil else {})


def _ramp_tol(planned: float | None) -> float:
    return TOL["ramp_abs_s"] + TOL["ramp_frac"] * abs(float(planned or 0.0))


def _rows_bgm_level(b: RowBuilder, bgm, bi: dict) -> None:
    """audio.bgm:level -- the BGM level at the final programme loudness measured in the output with the definition of
    `ref audio-measure` (LS gain of the clean file + target LUFS - mix LUFS) vs the planned gain_db (IR), and the
    same number vs the reference (audio.bgm.gain_db)."""
    lv = bi.get("level") or {}
    tol = float(b.pget("audio.loudness.tolerance_lu", 1.0) or 1.0) + TOL["bgm_level_noise_db"]
    obs = lv.get("level_db")
    exp = float(bgm.gain_db) if bgm is not None and bgm.gain_db is not None else None
    pv = b.pget("audio.bgm.gain_db")
    from_preset = exp is not None and pv is not None and abs(exp - float(pv)) < 1e-6
    st = "unmeasured" if obs is None or exp is None else ("same" if abs(obs - exp) <= tol else "different")
    b.add("audio.bgm", "level", "BGM 크기(최종 프로그램 음량 기준)", CAT["music"],
          expected={"gain_db": exp, "definition": "깨끗한 음원 대비 dB, 최종 프로그램 음량에서"},
          observed={k: lv.get(k) for k in ("level_db", "ls_gain_db", "mix_lufs", "target_lufs")} if lv else None,
          tolerance=f"±{tol:g} dB (audio.loudness.tolerance_lu + LS 측정 잡음 {TOL['bgm_level_noise_db']:g})",
          status=st, keys=["audio.bgm.gain_db"] if from_preset else [], required=True, evidence={"t": 0.0},
          note=(lv.get("method") or "") + ("" if from_preset or exp is None else " — 계획이 정한 gain_db(프리셋 값 아님)")
          + (f"; {lv.get('reason')}" if lv.get("reason") else ""))
    b.style_row("audio.bgm", "level_ref", "BGM 크기 (레퍼런스 대비)", CAT["music"], ["audio.bgm.gain_db"],
                {"level_db": obs} if obs is not None else None,
                lambda o, r: abs(o["level_db"] - float(r["audio.bgm.gain_db"])) <= tol,
                note="레퍼런스와 같은 정의(ref audio-measure: 깨끗한 음원 LS 이득 + 목표 LUFS − 믹스 LUFS)")


def _rows_bgm_ramps(b: RowBuilder, bi: dict) -> None:
    """Edge ramps of the BGM measured in the output with the reference's own functions (probes_audio.bgm_ramps):
      audio.silence:ramps<i>  ramp into / out of each planned intentional silence (renderer units, audio.silence.fade_s)
      audio.ducking:ramps<i>  attack / release of each duck under the speech measured in the output
    Expected = the same measurement run on the planned BGM signal (IR envelope), so window blur cancels out."""
    rp = bi.get("ramps") or {}
    sil = rp.get("silences") or {}
    fade_pre = b.pget("audio.silence.fade_s")
    obs_f = []
    for i, it in enumerate(sil.get("items") or []):
        o, p = it.get("observed") or {}, it.get("planned_reading") or {}
        parts, obs, exp = [], {}, {}
        for side in ("into", "out_of"):
            os_, ps_ = o.get(side) or {}, p.get(side) or {}
            obs[side] = os_.get("fade_s") if os_.get("status") == "measured" else None
            exp[side] = ps_.get("fade_s") if ps_.get("status") == "measured" else None
            if obs[side] is not None:
                obs_f.append(obs[side])
            if obs[side] is not None and exp[side] is not None:
                parts.append(abs(obs[side] - exp[side]) <= _ramp_tol(exp[side]))
        st = "unmeasured" if not parts else ("same" if all(parts) else "different")
        blk = "; ".join(f"{sd}: {(o.get(sd) or {}).get('blocker')}" for sd in ("into", "out_of")
                        if (o.get(sd) or {}).get("status") != "measured")
        b.add("audio.silence", f"ramps{i}", f"의도적 정적 앞뒤 BGM 경사 {it['range'][0]:.2f}–{it['range'][1]:.2f}s",
              CAT["music"], expected={"fade_s_planned_reading": exp, "fade_s_preset": fade_pre},
              observed={"fade_s": obs}, tolerance=f"±({TOL['ramp_abs_s']:g} s + {int(TOL['ramp_frac'] * 100)}%)",
              status=st, keys=["audio.silence.fade_s"] if parts else [], required=False,
              evidence={"t": it["range"][0]},
              note=("reference.audio_original.measure_silence_ramps 를 출력(믹스 − 원음·효과음 맞춤)과 계획 BGM 신호에 똑같이 "
                    "적용(렌더러 모양 dB 선형 0→−120 dB 단위)") + (f"; 못 잰 쪽: {blk}" if blk else "")
              + (f"; {sil.get('blocker')}" if sil.get("blocker") else ""))
    if sil.get("items"):
        b.style_row("audio.silence", "fade_ref", "의도적 정적 경사 길이 (레퍼런스 대비)", CAT["music"], ["audio.silence.fade_s"],
                    {"fade_s": _r(_median(obs_f), 4)} if obs_f else None,
                    lambda o, r: abs(o["fade_s"] - float(r["audio.silence.fade_s"])) <= _ramp_tol(r["audio.silence.fade_s"]),
                    note="레퍼런스와 같은 함수(measure_silence_ramps)·같은 단위")
    dk = rp.get("ducking") or {}
    att_obs, rel_obs = [], []
    for i, seg in enumerate(dk.get("per_segment") or []):
        pr = seg.get("planned_reading") or {}
        parts, keys = [], []
        for k in ("attack_s", "release_s"):
            if seg.get(k) is not None:
                (att_obs if k == "attack_s" else rel_obs).append(seg[k])
            if seg.get(k) is not None and pr.get(k) is not None:
                parts.append(abs(float(seg[k]) - float(pr[k])) <= _ramp_tol(pr[k]))
                keys.append(f"audio.ducking.{k}")
        st = "unmeasured" if not parts else ("same" if all(parts) else "different")
        b.add("audio.ducking", f"ramps{i}", f"덕킹 경사(어택·릴리스) [말소리 {seg['start']:.2f}–{seg['end']:.2f}s]", CAT["music"],
              expected={"planned_reading": {k: pr.get(k) for k in ("attack_s", "release_s", "depth_db")},
                        "preset": {k: b.pget(f"audio.ducking.{k}") for k in ("attack_s", "release_s")}},
              observed={k: seg.get(k) for k in ("attack_s", "release_s", "depth_db", "status", "blocker")},
              tolerance=f"±({TOL['ramp_abs_s']:g} s + {int(TOL['ramp_frac'] * 100)}%)", status=st, keys=keys,
              required=False, evidence={"t": seg["start"]},
              note="reference.audio_original.measure_ducking(10→90 % 경사 시간/0.8)을 출력 BGM 이득 곡선과 계획 BGM 신호에 "
                   "똑같이 적용; 말소리 = 출력에서 잰 말소리" + ("" if parts else " — 경사를 재지 못함(앞뒤 BGM 부족·깊이 < 3 dB)"))
    planned_ducks = bool(getattr(b.ctx.resolved.audio.bgm, "duck_ranges", None))
    if dk.get("per_segment") or planned_ducks:
        obs = {}
        if att_obs:
            obs["attack_s"] = _r(_median(att_obs), 3)
        if rel_obs:
            obs["release_s"] = _r(_median(rel_obs), 3)
        keys = [f"audio.ducking.{k}" for k in ("attack_s", "release_s") if k in obs]

        def _dk_same(o, r):
            return _all(*[abs(o[k] - float(r[f"audio.ducking.{k}"])) <= _ramp_tol(r[f"audio.ducking.{k}"])
                          for k in ("attack_s", "release_s") if k in o])
        b.style_row("audio.ducking", "ramps_ref", "덕킹 어택·릴리스 (레퍼런스 대비)", CAT["music"],
                    keys or ["audio.ducking.attack_s", "audio.ducking.release_s"], obs or None, _dk_same,
                    note="레퍼런스와 같은 함수(measure_ducking)·같은 단위; 재지 못한 키는 행에서 뺌"
                    + ("" if dk.get("per_segment") else f" — {((dk.get('observed') or {}).get('blocker'))}"))


DUCK_NO_SPEECH_MAX_S = 0.25      # ducked BGM time allowed outside the (attack/release-padded) speech of one ducked range


def _duck_speech_row(b: RowBuilder, ap: dict, obs: list, sil: list, fades: list, att: float, rel: float) -> None:
    from . import overlaps

    ctx = b.ctx
    sp = _speech_out(ap)
    ducks = [(x, y) for x, y in obs if not any(overlaps(x, y, a - 0.1, c + 0.1) >= 0.8 * (y - x) for a, c in sil)
             and not any(overlaps(x, y, a, c) >= 0.8 * (y - x) for a, c in fades)]
    planned = [x for o in ctx.resolved.audio.originals for x in _planned_speech_out(o)]
    if not ducks:
        st, items, note = "same", [], "출력에서 잰 덕킹 없음(시작·끝 페이드·의도적 정적 제외)"
    elif sp.get("status") != "measured":
        st, items, note = "unmeasured", [], "출력의 말소리를 재지 못해 덕킹이 말소리 밑인지 판정 못 함: " + str(sp.get("reason") or "")
    else:
        spans = [(float(a) - att - 0.05, float(c) + rel + 0.05) for a, c in sp.get("spans") or []]
        items = []
        for x, y in ducks:
            inside = sum(overlaps(x, y, a, c) for a, c in merge_spans(spans))
            items.append({"range": [_r(x, 3), _r(y, 3)], "without_speech_s": _r(max(0.0, (y - x) - inside), 3)})
        bad = [it for it in items if it["without_speech_s"] > DUCK_NO_SPEECH_MAX_S]
        st = "different" if bad else "same"
        note = (f"말소리 없이 낮춘 BGM: " + ", ".join(f"{it['range']} ({it['without_speech_s']}s)" for it in bad)) if bad else \
            "덕킹마다 출력 말소리(+어택·릴리스) 안"
    b.add("audio.ducking", "speech", "덕킹은 출력에서 잰 말소리 밑에서만", CAT["music"],
          expected={"planned_speech_out": planned, "max_without_speech_s": DUCK_NO_SPEECH_MAX_S},
          observed={"ducks": items or [[_r(x, 3), _r(y, 3)] for x, y in ducks],
                    "speech_out": sp.get("spans"), "speech_status": sp.get("status")},
          tolerance=f"덕킹 구간마다 말소리(± 어택 {att}s·릴리스 {rel}s) 밖 ≤ {DUCK_NO_SPEECH_MAX_S}s",
          status=st, keys=["audio.ducking.only_under_kept_dialogue"], required=True,
          evidence={"t": ducks[0][0]} if ducks else {}, note=note)


def merge_spans(spans):
    from . import merge_ranges

    return [tuple(x) for x in merge_ranges(spans)]


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
                  expected={"present": True, "applied_gain_db": o.gain_db}, observed=None, status="unmeasured",
                  note="소스 오디오를 읽지 못했거나 구간이 너무 짧음" + (" (소스에 소리 없음)" if o.clip_id in silent_src else ""))
            continue
        frac = sum(1 for w in ws if w["present"]) / len(ws)
        g = _median([w.get("gain_db_mix_scale") for w in ws if w["present"]])
        ok = frac >= TOL["orig_present_frac"]
        b.add("audio.original", f"kept{i}", f"보존 원음 [{o.clip_id} {o.out_start:.2f}–{o.out_end:.2f}s]", CAT["original"],
              expected={"present": True, "applied_gain_db": o.gain_db, "stem": o.stem, "reason": o.reason},
              observed={"presence": "present" if frac >= TOL["orig_present_frac"] else ("absent" if frac == 0 else "partial"),
                        "present_fraction": _r(frac, 3), "gain_db_mix_scale": _r(g, 2)},
              tolerance=f"창의 {int(TOL['orig_present_frac'] * 100)}% 이상에서 원음 확인", status="same" if ok else "different",
              evidence={"t": o.out_start},
              note="원음이 계획한 구간에 있는지(크기는 level 행, 경계 경사는 fade 행). "
                   "원음 이득은 BGM 기준 믹스 척도 추정(BGM 없으면 없음)")
    # music embedded in the source must be removed from kept original sound (separate first): measured on the OUTPUT --
    # the mix minus the fitted BGM and SFX in each kept range, with edit.audio_checks.music_presence (the detector
    # validate runs on the source).  The plan's has_embedded_music is shown, never the verdict.
    _rows_kept_voice(b, ap)
    # level: kept speech loudness relative to the programme (the definition of audio.original.keep_gain_db)
    levels = {lv["index"]: lv for lv in og.get("levels") or []}
    plan_segs = {s_.get("id"): s_ for s_ in ((ctx.plan or {}).get("timeline") or [])}
    tol_lu = float(b.pget("audio.loudness.tolerance_lu", 1.0) or 1.0) + TOL["orig_level_noise_lu"]
    keep_default = b.pget("audio.original.keep_gain_db")
    rel_obs_all = []
    for i, o in enumerate(ctx.resolved.audio.originals):
        seg_oa = (plan_segs.get(o.clip_id) or {}).get("original_audio") or {}
        override = seg_oa.get("gain_db") is not None
        exp_rel = float(seg_oa["gain_db"]) if override else (None if keep_default is None else float(keep_default))
        lv = levels.get(i) or {}
        obs = lv.get("rel_lu_obs")
        if obs is not None:
            rel_obs_all.append(obs)
        st = "unmeasured" if (obs is None or exp_rel is None) else ("same" if abs(obs - exp_rel) <= tol_lu else "different")
        b.add("audio.original", f"level{i}", f"보존 원음 크기(프로그램 음량 대비) [{o.clip_id} {o.out_start:.2f}–{o.out_end:.2f}s]",
              CAT["original"], expected={"rel_lu": exp_rel, "source": "plan original_audio.gain_db" if override
                                         else "audio.original.keep_gain_db",
                                         "definition": "보존 원음 통합 음량 − 프로그램 통합 음량 (LU)"},
              observed={k: lv.get(k) for k in ("rel_lu_obs", "src_lufs", "src_scope", "fit_gain_db", "n_windows",
                                               "mix_lufs")} if lv else None,
              tolerance=f"±{tol_lu:g} LU (audio.loudness.tolerance_lu + 측정 잡음 {TOL['orig_level_noise_lu']:g})",
              status=st, keys=[] if override else ["audio.original.keep_gain_db"], evidence={"t": o.out_start},
              note=lv.get("reason") or "L_src(소스 통합 음량) + 출력 믹스 속 원음 이득(창별 최소제곱 중앙값) − 출력 통합 음량")
    leak = [w for w in wins if w["present"] and not any(a - fade - 0.2 <= w["t"] <= c + fade + 0.2 for a, c in kept)]
    leak_r = [[_r(w["t"] - 0.125), _r(w["t"] + 0.125)] for w in leak]
    b.add("audio.original", "off", "원음 OFF 구간에 원음 없음(기본 OFF)", CAT["original"],
          expected={"kept_only": [list(x) for x in kept]},
          observed={"presence_outside_kept": "present" if leak else "absent", "leak_windows": leak_r[:20],
                    "sources_without_audio": silent_src},
          tolerance="0개 창", status="same" if not leak else "different", keys=["audio.original.default"],
          evidence={"t": leak[0]["t"]} if leak else {},
          note=("소스에 소리가 없는 클립: " + ", ".join(silent_src)) if silent_src else "")
    _rows_original_ramps(b, og)
    b.style_row("audio.original", "orig_ref", "보존 원음 크기 (레퍼런스 대비)", CAT["original"],
                ["audio.original.keep_gain_db"],
                {"rel_lu": _r(_median(rel_obs_all), 2)} if rel_obs_all else None,
                lambda o, r: abs(o["rel_lu"] - float(r.get("audio.original.keep_gain_db"))) <= tol_lu,
                note="크기 = 보존 원음 통합 음량 − 프로그램 통합 음량(LU), ref audio-measure 와 같은 정의")


def _rows_original_ramps(b: RowBuilder, og: dict) -> None:
    """audio.original:fade<i> -- the on/off edge ramps of each kept original range measured in the output with
    reference.audio_original.measure_original_ramps (renderer units: linear amplitude) vs the IR fade_s.  Only an edge
    followed by stationary sound can be read (speech starting at the edge shows its own attack): otherwise 못 잼."""
    ctx = b.ctx
    rp = {it["index"]: it for it in ((og.get("ramps") or {}).get("items") or [])}
    pre = b.pget("audio.original.fade_s")
    obs_all = []
    for i, o in enumerate(ctx.resolved.audio.originals):
        it = rp.get(i) or {}
        meas = [e for e in it.get("edges") or [] if e.get("status") == "measured"]
        obs_all += [float(e["fade_s"]) for e in meas]
        fs = getattr(o, "fade_s", None)
        parts = [abs(float(e["fade_s"]) - float(fs)) <= _ramp_tol(fs) for e in meas] if fs is not None else []
        why = "; ".join(f"{e.get('edge')}: {e.get('reason')}" for e in it.get("edges") or [] if e.get("status") != "measured")
        from_preset = pre is not None and fs is not None and abs(float(fs) - float(pre)) < 1e-9
        b.add("audio.original", f"fade{i}", f"보존 원음 경계 경사 [{o.clip_id} {o.out_start:.2f}–{o.out_end:.2f}s]", CAT["original"],
              expected={"fade_s": fs}, observed={"edges": [{k: e.get(k) for k in ("edge", "edge_t", "status", "fade_s",
                                                                                         "span_s", "reason")}
                                                                  for e in it.get("edges") or []]} if it else None,
              tolerance=f"±({TOL['ramp_abs_s']:g} s + {int(TOL['ramp_frac'] * 100)}%)",
              status="unmeasured" if not parts else ("same" if all(parts) else "different"),
              keys=["audio.original.fade_s"] if parts and from_preset else [], required=False,
              evidence={"t": o.out_start},
              note=("reference.audio_original.measure_original_ramps(출력 − 찾은 BGM·효과음, 렌더러 선형 진폭 단위)"
                    + (f"; 못 잰 경계: {why}" if why else "")
                    + ("" if it else "; " + str((og.get("ramps") or {}).get("reason") or "경사 측정 결과 없음"))))
    if ctx.resolved.audio.originals:
        b.style_row("audio.original", "fade_ref", "보존 원음 경계 경사 (레퍼런스 대비)", CAT["original"],
                    ["audio.original.fade_s"], {"fade_s": _r(_median(obs_all), 4)} if obs_all else None,
                    lambda o, r: abs(o["fade_s"] - float(r["audio.original.fade_s"])) <= _ramp_tol(r["audio.original.fade_s"]),
                    note="레퍼런스와 같은 함수(measure_original_ramps)·같은 단위; 소리가 경계에서 시작하는 경계는 못 잼")


def _planned_speech_out(o) -> list[list[float]]:
    """IR OriginalAudio.speech (SOURCE s) mapped to output seconds (what the renderer ducked under)."""
    sp, s0 = float(getattr(o, "speed", 1.0) or 1.0), float(getattr(o, "src_start", 0.0) or 0.0)
    return [[_r(o.out_start + (a - s0) / sp, 3), _r(o.out_start + (b_ - s0) / sp, 3)]
            for a, b_ in (getattr(o, "speech", None) or [])]


def _speech_out(ap: dict) -> dict:
    return (((ap.get("originals") or {}).get("voice_out") or {}).get("speech") or {})


def _rows_kept_voice(b: RowBuilder, ap: dict) -> None:
    """Rows on the kept original sound AS IT IS IN THE OUTPUT (probes_audio.kept_audio_checks: mix minus the fitted BGM
    and SFX):
      audio.original:music<i>     music left in the kept range (embedded music not removed) -- music_presence
      audio.original:speech<i>    the kept range is speech (>= validate.KEPT_SPEECH_MIN_SHARE of it) -- speech_spans;
                                  the planned speech (IR OriginalAudio.speech, source s -> output s) is shown
      audio.original:vocals_qc<i> a kept vocals stem carries a passing automatic quality record (quality.json of the
                                  separation, validate.vocals_quality) -- automatic, not a listening check
    Nothing here is a listening check; a person's listening record (qa human-check --kind listen) only decides a
    music row the detector left 못 잼."""
    from ..edit.audio_checks import overlap

    ctx = b.ctx
    vo = (ap.get("originals") or {}).get("voice_out") or {}
    music = {m.get("index"): m for m in vo.get("music") or []}
    sp = vo.get("speech") or {}
    srcs = {x.get("id"): x for x in ((ctx.plan or {}).get("sources") or [])}
    try:
        from ..edit.validate import KEPT_SPEECH_MIN_SHARE, vocals_quality
    except Exception as e:  # the rule is never re-implemented silently
        KEPT_SPEECH_MIN_SHARE, vocals_quality = None, None
        vq_err = f"{type(e).__name__}: {e}"
    else:
        vq_err = None
    for i, o in enumerate(ctx.resolved.audio.originals):
        c = next((x for x in ctx.resolved.clips if x.id == o.clip_id), None)
        src = srcs.get(c.source_id) if c is not None else None
        hem = (src or {}).get("has_embedded_music")
        # --- music left in the kept voice
        rid = f"audio.original:music{i}"
        m = music.get(i) or {}
        rec = _human_record(b, rid, "listen")
        mst = m.get("status")
        if mst == "present":
            st, basis, note = "different", "출력 측정", "보존 원음 구간(출력 − BGM·효과음)에서 음악(지속 화음)이 잡힘 — 음악을 분리해 빼야 함"
        elif mst == "absent":
            st, basis, note = "same", "출력 측정", "보존 원음 구간(출력 − BGM·효과음)에서 음악이 잡히지 않음"
        elif rec is not None:
            st, basis = rec["verdict"], "사람 청취 기록"
            note = f"자동 검사 못 잼({m.get('reason')}) → 사람 청취 기록({rec['by']}, {rec['at']}, 이 MP4 sha256): {rec['note']}"
        else:
            st, basis = "unmeasured", "못 잼"
            note = ("보존 원음 구간의 음악 여부를 출력에서 판정하지 못함: " + str(m.get("reason") or vo.get("error")
                                                                  or "측정 결과 없음(오디오 측정 실패)"))
        if hem is True and o.stem == "raw" and st != "different":
            st, basis = "different", "plan+IR"
            note = "음악이 섞였다고 기록된 원본 소리를 분리하지 않고 그대로 사용(plan: has_embedded_music=true, stem=raw); " + note
        b.add("audio.original", f"music{i}", f"보존 원음 속 음악 제거 [{o.clip_id} {o.out_start:.2f}–{o.out_end:.2f}s]",
              CAT["original"], expected={"embedded_music_in_output": "absent"},
              observed={"music_obs": {k: m.get(k) for k in ("status", "polyphonic_share", "sustained_share", "active_s",
                                                             "range_out")} if m else None,
                        "has_embedded_music_plan": hem, "stem": o.stem, "basis": basis,
                        **({"human_check": rec} if rec else {})},
              tolerance="동시 지속 부분음 비율 < 0.03 → 없음(같다), ≥ 0.10 → 있음(다르다), 사이 → 못 잼",
              status=st, keys=["audio.original.remove_embedded_music"], required=True, evidence={"t": o.out_start},
              note=(note + " (기계 측정; 사람 청취 확인 아님)") if basis != "사람 청취 기록" else note)
        # --- the kept range is speech (and the planned speech is where it was planned)
        rng = (float(o.out_start), float(o.out_end))
        planned = _planned_speech_out(o)
        if sp.get("status") != "measured" or KEPT_SPEECH_MIN_SHARE is None:
            st, share, cov = "unmeasured", None, None
            note = "출력의 말소리를 재지 못함: " + str(sp.get("reason") or vq_err or "측정 결과 없음")
        else:
            spans = [tuple(x) for x in sp.get("spans") or []]
            share = overlap(rng[0], rng[1], spans) / max(1e-6, rng[1] - rng[0])
            tot_p = sum(y - x for x, y in planned)
            cov = (sum(overlap(x, y, spans) for x, y in planned) / tot_p) if tot_p > 0 else None
            st = "same" if share >= KEPT_SPEECH_MIN_SHARE else "different"
            note = (f"보존 구간의 {share:.0%} 에서 출력 말소리 검출(기준 ≥ {KEPT_SPEECH_MIN_SHARE:.0%}: 중요한 대사·말하는 구간만 살림)"
                    + (f"; 계획한 말소리 구간(IR speech)의 {cov:.0%} 가 출력에서 말소리" if cov is not None else
                       f"; 계획 말소리 {getattr(o, 'speech_status', 'unmeasured')}"))
        b.add("audio.original", f"speech{i}", f"보존 원음은 말소리 [{o.clip_id} {o.out_start:.2f}–{o.out_end:.2f}s]",
              CAT["original"], expected={"speech_share_min": KEPT_SPEECH_MIN_SHARE, "planned_speech_out": planned,
                                         "planned_speech_status": getattr(o, "speech_status", "unmeasured")},
              observed={"speech_share": _r(share, 3), "planned_speech_covered": _r(cov, 3),
                        "speech_out": [s_ for s_ in (sp.get("spans") or []) if s_[1] > rng[0] and s_[0] < rng[1]]},
              tolerance=f"보존 구간 중 말소리 ≥ {KEPT_SPEECH_MIN_SHARE}", status=st, required=True,
              evidence={"t": o.out_start}, note=note)
        # --- a vocals stem needs its automatic separation quality record
        if o.stem == "vocals":
            rid = f"vocals_qc{i}"
            if vocals_quality is None or src is None:
                vst, vq, vnote = "unmeasured", None, ("소스 기록 없음" if src is None else f"validate.vocals_quality 사용 불가: {vq_err}")
            else:
                try:
                    vq = vocals_quality(src, o.path)
                except Exception as e:  # never a silent pass
                    vq, vst, vnote = None, "unmeasured", f"품질 기록을 읽지 못함: {type(e).__name__}: {e}"
                else:
                    vst = "same" if vq["ok"] else ("unmeasured" if vq["missing"] else "different")
                    vnote = ("분리 품질 자동 검사 합격(quality.json)" if vq["ok"] else "; ".join(vq["problems"]))
            from .. import paths
            from ..util.jsonio import read_json

            qrec = read_json(paths.absp(vq["record"])) if vq and vq.get("record") else None
            b.add("audio.original", rid, f"분리한 목소리(vocals stem) 품질 기록 [{o.clip_id}]", CAT["original"],
                  expected={"quality_json": "passed=true, usable=true, 이 소스(sha256)·이 stem 의 기록"},
                  observed={"record": (vq or {}).get("record"), "quality": (qrec or {}).get("quality"),
                            "usable": (qrec or {}).get("usable"), "status": (qrec or {}).get("status"),
                            "source_sha256": (qrec or {}).get("source_sha256"), "vocals": (qrec or {}).get("vocals")},
                  status=vst, required=True, evidence={"t": o.out_start},
                  note=vnote + " — 자동 품질 검사이며 사람 청취가 아님(분리 음질은 사람이 들어야 함)")


def _rows_sfx(b: RowBuilder, ap: dict, probes: dict | None = None) -> None:
    ctx = b.ctx
    sf = ap.get("sfx") or {}
    dets = list(sf.get("detections") or [])
    plan_sfx = {s.get("id"): s for s in ((ctx.plan or {}).get("sfx") or [])}
    max_off = float(b.pget("audio.sfx.max_event_offset_s", 0.3) or 0.3)
    used = set()
    no_event = []
    placed: list = []
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
            placed.append((s, d))
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
    _sfx_on_cut_rows(b, placed, probes or {})
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
    # the TYPE of every placed SFX by its sound (catalog fingerprint centroid, probes_audio.classify_sfx_detections),
    # not by the plan's label
    _sfx_type_rows(b, placed)
    # counts per type vs the reference catalog range for this format -- the SAME rule as `episode validate`
    # (docs/CONTRACT.md 12 "SFX count rule"): only edit_sfx types (+ intentional silences when there are any), allowed
    # = [floor(p10), ceil(p90)] or a count observed in a reference video; counts in lower-bound videos are lower bounds.
    # The types counted are the catalog classification of the detected sounds.
    _rows_sfx_catalog(b, ap, catalog_counts(dets))
    gains = [d.get("gain_db_mix_scale") for d in dets if d.get("gain_db_mix_scale") is not None]
    b.style_row("audio.sfx.placement", "sfx_gain_ref", "효과음 크기 (레퍼런스 대비)", CAT["sfx_count"],
                ["audio.sfx.gain_db_default"], {"gain_db": _r(_median(gains), 2)} if gains else None,
                lambda o, r: abs(o["gain_db"] - float(r.get("audio.sfx.gain_db_default"))) <= TOL["sfx_gain_db"])


UNCLASSIFIED = "(카탈로그 밖 소리)"


def catalog_type_of(d: dict) -> str | None:
    """Catalog type id of a detection from its fingerprint (probes_audio.classify_sfx_detections); UNCLASSIFIED when it
    was measured and matches no type; None when it could not be classified (못 잼)."""
    ct = d.get("catalog_type") or {}
    if ct.get("status") != "measured":
        return None
    return ct.get("type_id") or UNCLASSIFIED


def catalog_counts(dets: list[dict]):
    """Counter of the detected SFX by catalog type (UNCLASSIFIED / None keys kept: callers report them)."""
    from collections import Counter

    return Counter(catalog_type_of(d) for d in dets)


def _sfx_type_rows(b: RowBuilder, placed: list) -> None:
    """audio.sfx.type:<id> -- the planned type of each placed SFX vs the catalog type its sound has in the output
    (fingerprint of the detected file against every catalog centroid, reference.sfx_map's threshold)."""
    mode = getattr(b.ctx.resolved, "mode", "test")
    for s_, d in placed:
        ct = d.get("catalog_type") or {}
        got = catalog_type_of(d)
        if got is None:
            st, note = "unmeasured", "소리 지문으로 종류를 정하지 못함: " + str(ct.get("reason") or "분류 결과 없음(이전 측정)")
        elif got == s_.type:
            st, note = "same", f"지문 유사도 {ct.get('similarity')} ≥ {ct.get('threshold')}"
        else:
            st = "different"
            note = (f"소리 지문이 '{got}' 에 가장 가까움(유사도 {ct.get('similarity')})" if got != UNCLASSIFIED else
                    f"어느 카탈로그 종류와도 유사도 {ct.get('threshold')} 미만(가장 가까운 '{ct.get('best_candidate')}' "
                    f"{ct.get('similarity')})") + " — 계획의 종류 이름과 실제 소리가 다름"
        b.add("audio.sfx.type", s_.id, f"효과음 [{s_.id}] 종류 = 소리 지문(카탈로그 대비)", CAT["sfx_count"],
              kind="style_vs_reference", expected={"type": s_.type}, observed={"catalog_type": got, **ct},
              tolerance="레퍼런스 카탈로그 종류 지문과 유사도 ≥ 문턱(reference.sfx_map.MATCH_THRESHOLD)",
              status=st, keys=["audio.sfx.catalog"], required=mode == "production", evidence={"t": d.get("t")},
              reference="못 잼" if got is None else None, note=note)


SFX_ON_CUT_S = 0.1          # an SFX this close to a measured cut sits ON the cut (the output cannot tell cut vs event)


def _sfx_on_cut_rows(b: RowBuilder, placed: list, probes: dict) -> None:
    """audio.sfx.on_cut: an SFX measured within 0.1 s of a cut measured in the output is placed ON a cut.  Its event
    time is only the plan's declaration, so unless something else measured in the output happens there (a caption
    onset, a freeze start, a decoration appearing) within the event tolerance, the rule 'SFX for an event, never for a
    cut' is not shown by the output: 못 잼 until a person watched it (`shortkit qa human-check --kind watch`)."""
    from .grid import our_cuts
    from .human import latest as _human_latest

    ctx = b.ctx
    mode = getattr(ctx.resolved, "mode", "test")
    cuts = our_cuts(probes.get("video") or {})
    if cuts is None:
        b.add("audio.sfx.on_cut", "all", "컷 위에 놓인 효과음(사건 없이 컷 때문인지)", CAT["sfx_no_event"],
              status="unmeasured", required=mode == "production", note="출력 컷 측정 실패 — 효과음이 컷 위에 있는지 못 잼")
        return
    max_off = float(b.pget("audio.sfx.max_event_offset_s", 0.3) or 0.3)
    tp = probes.get("text") or {}
    marks = [("자막 등장", float(c["onset"])) for c in tp.get("captions") or [] if c.get("found") and c.get("onset") is not None]
    fz = (probes.get("video") or {}).get("freezes") or {}
    marks += [("정지 시작", float(e["observed"]["start"])) for e in fz.get("expected") or [] if e.get("observed")]
    for it in ((probes.get("video") or {}).get("decorations") or {}).get("items") or []:
        tr = (it.get("position") or {}).get("track") or []
        if tr:
            marks.append(("장식 등장", float(tr[0][0])))
    opts = getattr(ctx, "options", None) or {}
    hcs = opts.get("human_checks") or []
    sha = opts.get("mp4_sha256")
    on_cut = []
    for s_, d in placed:
        near = [c for c in cuts if abs(float(c["t"]) - float(d["t"])) <= SFX_ON_CUT_S]
        if not near:
            continue
        ev_t = float(s_.event_t) if s_.event_t is not None else float(d["t"])
        indep = [{"what": w, "t": round(t, 3)} for w, t in marks if abs(t - ev_t) <= max_off]
        rid = f"audio.sfx.on_cut:{s_.id}"
        rec = _human_latest(hcs, rid, sha, kind="watch")
        if rec is not None:
            st, note = rec["verdict"], f"사람이 영상을 보고 기록({rec['by']}, {rec['at']}): {rec['note']}"
        elif indep:
            st, note = "same", "컷과 겹치지만 사건 시각에 출력에서 따로 잰 변화가 있음: " + ", ".join(
                f"{x['what']} {x['t']}s" for x in indep)
        else:
            st, note = "unmeasured", ("효과음이 측정된 컷 위(±0.1 s)에 있고 사건은 plan 선언뿐 — 출력에서 사건을 따로 확인하지 못함. "
                                      "사람이 보고 `shortkit qa human-check --kind watch` 로 기록해야 함")
        on_cut.append(s_.id)
        b.add("audio.sfx.on_cut", s_.id, f"컷 위의 효과음 [{s_.id}·{s_.type}] — 사건 때문인지", CAT["sfx_no_event"],
              expected={"event_t": s_.event_t, "event": s_.event_desc, "not_because_of_cut": True},
              observed={"sfx_t": d["t"], "cuts_near": near, "independent_evidence": indep},
              tolerance=f"컷 ±{SFX_ON_CUT_S}s 안의 효과음은 사건 시각 ±{max_off}s 안에 출력에서 잰 변화가 있어야 함",
              status=st, required=mode == "production", evidence={"t": d["t"]}, note=note)
    b.add("audio.sfx.on_cut", "all", "컷 위에 놓인 효과음(사건 없이 컷 때문인지)", CAT["sfx_no_event"],
          expected={"on_cut_without_evidence": 0}, observed={"on_cut": on_cut, "cuts_measured": len(cuts)},
          status="same", required=False,
          note=("컷 위 효과음 없음" if not on_cut else f"컷 위 효과음 {len(on_cut)}개는 각각의 행에서 판정"))


def _rows_sfx_catalog(b: RowBuilder, ap: dict, obs_c) -> None:
    """Per-type and total SFX counts of the output vs the format's observed range, through the functions of
    ``shortkit.edit.validate`` (one rule for plan and output: edit_sfx types only, + intentional silences measured in
    the output when there are any; onsite_sound types are never counted; [floor(p10), ceil(p90)] or a count observed in
    a reference video; lower-bound videos -> 못 잼)."""
    ctx = b.ctx
    cat = _catalog(b)
    mode = getattr(ctx.resolved, "mode", "test")
    req = mode == "production"
    try:
        from ..edit import sfxmap
        from ..edit import validate as V
        from ..util.stats import pstats_by_group
    except Exception as e:     # the rule itself is never re-implemented silently
        b.add("audio.sfx.count", "catalog", "효과음 종류별 개수 (레퍼런스 포맷 범위 대비)", CAT["sfx_count"],
              kind="style_vs_reference", status="unmeasured", keys=["audio.sfx.catalog"], required=req,
              note=f"shortkit.edit.validate 의 개수 규칙을 쓸 수 없음: {type(e).__name__}: {e}"[:300])
        return
    # the count rule runs whenever the per-video counts cover every target video: status measured, or partial
    # (every video counted; a per-type column such as emotion unmeasured) -- validate's catalog_counts_measured
    if not cat or not cat.get("types") or not V.catalog_counts_measured(cat):
        b.add("audio.sfx.count", "catalog", "효과음 종류별 개수 (레퍼런스 포맷 범위 대비)", CAT["sfx_count"], kind="style_vs_reference",
              expected="레퍼런스 카탈로그의 포맷별 관측 범위",
              observed={("종류 못 정함" if k is None else str(k)): v for k, v in obs_c.items()}, status="unmeasured",
              keys=["audio.sfx.catalog"], required=req, reference="못 잼",
              note="sfx_catalog.json 미측정: " + str((cat or {}).get("blocker") or "카탈로그 없음"))
        return
    if cat.get("status") != "measured":
        # partial: the count rows below are real verdicts, but the catalog itself is not complete -> production stays
        # blocked by this required 못 잼 row until every per-type column is measured
        gaps = V.catalog_unmeasured_columns(cat)
        b.add("audio.sfx.count", "catalog", "효과음 카탈로그 완성도 (종류별 열 전부 측정)", CAT["sfx_count"],
              kind="style_vs_reference", expected={"status": "measured"},
              observed={"status": cat.get("status"), "unmeasured_columns": gaps,
                        "column_status": cat.get("column_status")},
              status="unmeasured", keys=["audio.sfx.catalog"], required=req, reference="못 잼",
              note=("카탈로그 일부 못 잼(partial): 편당 개수는 모든 대상 영상에서 셌으므로 아래 개수 행은 판정함. 못 잰 열: "
                    + (", ".join(f"{c}({len(v)}종류)" for c, v in gaps.items()) or "?")
                    + f" — {str(cat.get('blocker') or '')[:200]}"))
    fid = ctx.resolved.format_id
    types = {t.get("type_id"): t for t in cat.get("types") or [] if t.get("type_id")}
    bi = ap.get("bgm") or {}
    span = bi.get("audible_span_obs")
    fo = float(getattr(ctx.resolved.audio.bgm, "fade_out_s", 0) or 0) if ctx.resolved.audio.bgm else 0.0
    sil_obs = [list(x) for x in bi.get("silent_ranges_obs") or []
               if span is None or (x[0] > span[0] + 0.1 and x[1] < span[1] - fo - 0.1)]
    sil_measurable = bi.get("status") == "measured" and bool(bi.get("found"))
    counted = {V.COUNTED_SFX_CLASS} | ({V.SILENCE_CLASS} if sil_obs else set())
    obs = V.observed_sfx_counts(cat, ctx.preset, fid)
    obs_ok = obs["problem"] is None
    n_blind = int(obs_c.pop(None, 0))
    if n_blind:
        b.add("audio.sfx.count", "catalog:unclassified", "종류를 정하지 못한 효과음", CAT["sfx_count"],
              kind="style_vs_reference", expected=0, observed=n_blind, status="unmeasured", keys=["audio.sfx.catalog"],
              required=req, note="검출된 효과음의 소리 지문을 카탈로그와 대조하지 못함 — 종류별 개수는 하한값")
    for tid in sorted(obs_c):
        if tid not in types:
            b.add("audio.sfx.count", "catalog:unknown", "카탈로그에 없는 효과음 종류", CAT["sfx_count"], kind="style_vs_reference",
                  expected=[], observed=[t for t in obs_c if t not in types], status="different", keys=["audio.sfx.catalog"],
                  required=req)
            break
    for tid in sorted(obs_c):
        if types.get(tid, {}).get("class") == V.ONSITE_CLASS:
            b.add("audio.sfx.count", f"catalog:{tid}", f"효과음 [{tid}] — 현장음 종류", CAT["sfx_count"], kind="style_vs_reference",
                  expected=0, observed=obs_c[tid], status="different", keys=["audio.sfx.catalog"], required=req,
                  note="현장음(onsite_sound)은 레퍼런스 원본의 소리 — 편집 효과음으로 넣을 수 없음")
    counted_types = [t for t, e in types.items() if e.get("class") in counted]
    has_silence_type = any(types[t].get("class") == V.SILENCE_CLASS for t in counted_types)

    def verdict1(what, cnt, st, basis, pv):
        out: list[dict] = []
        V._count_verdict(out, what, cnt, st, basis, pv, obs["lower_bound"], obs_ok, "sfx_count_range", "warn")
        if not out:
            return "same", ""
        iss = out[0]
        code = str(iss.get("code") or "")
        msg = str(iss.get("message_ko") or iss)
        if iss.get("severity") == "error":
            return "different", msg
        return "unmeasured", msg + (" (하한값 영상에서만 관측된 개수 — 범위 안이라고 확정 못 함)" if code.endswith("lower_bound") else "")

    def verdict(what, cnt, st, basis, pv):
        """Detections whose type could not be told (n_blind) may belong to any type: the true count lies in
        [cnt, cnt + n_blind].  same / different only when every count in that interval gets the same verdict."""
        res = [verdict1(what, c, st, basis, pv) for c in range(cnt, cnt + n_blind + 1)]
        sts = {r_[0] for r_ in res}
        if len(sts) == 1:
            return res[0]
        return "unmeasured", (f"종류를 정하지 못한 효과음 {n_blind}개 때문에 실제 개수는 {cnt}~{cnt + n_blind}개 — "
                              "그 사이에서 판정이 갈림: " + "; ".join(f"{c}개→{r_[0]}" for c, r_ in zip(range(cnt, cnt + n_blind + 1), res)))
    if sil_obs and not has_silence_type:
        b.add("audio.sfx.count", "catalog:intentional_silence", "의도적 정적 개수 (레퍼런스 포맷 범위 대비)", CAT["sfx_count"],
              kind="style_vs_reference", expected=0, observed=len(sil_obs), status="different", keys=["audio.sfx.catalog"],
              required=req, note="출력에 의도적 정적이 있으나 측정된 카탈로그에 의도적 정적 종류가 없음(레퍼런스 영상 모두 0개)")
    for tid in counted_types:
        ent = types[tid]
        is_sil = ent.get("class") == V.SILENCE_CLASS
        cnt = len(sil_obs) if is_sil else int(obs_c.get(tid, 0))
        st, basis = sfxmap.count_range(ent.get("per_video_count"), fid)
        pv = (obs["types"] if basis.startswith("by_format") else obs["all_types"]).get(tid)
        status, msg = (verdict1 if is_sil else verdict)(f"'{tid}'", cnt, st, basis, pv)
        if is_sil and not sil_measurable:
            status, msg = "unmeasured", "BGM 을 출력에서 찾지 못해 의도적 정적(BGM 끊김)을 셀 수 없음"
        lo_hi = V.allowed_count_range(st) if st and st.get("p10") is not None and st.get("p90") is not None else None
        b.add("audio.sfx.count", f"catalog:{tid}", f"{'의도적 정적' if is_sil else '효과음'} 개수 [{tid}] (레퍼런스 {fid} 범위 대비)",
              CAT["sfx_count"], kind="style_vs_reference", reference=st or "못 잼",
              expected={"allowed": lo_hi, "p10": (st or {}).get("p10"), "p90": (st or {}).get("p90"), "basis": basis,
                        "observed_in_reference": sorted(set((pv or {}).values())) if obs_ok else None},
              observed=cnt, tolerance="[floor(p10), ceil(p90)] 또는 레퍼런스 영상에서 관측된 개수(하한값 영상은 못 잼)",
              status=status, keys=["audio.sfx.catalog"], required=req, note=msg)
    # total of the counted classes, per-video totals from the same per-video counts (validate's rule)
    n_all = sum(int(obs_c.get(t, 0)) for t in counted_types if types[t].get("class") == V.COUNTED_SFX_CLASS)
    n_all += len(sil_obs) if has_silence_type else 0
    tot_st, tot_basis, per_video_tot = None, "none", None
    if obs_ok:
        allc = obs["all_types"]
        rows_ = [{"format_id": obs["formats"].get(v), "count": sum(allc.get(t, {}).get(v, 0) for t in counted_types)}
                 for v in obs["all_videos"]]
        tot_st, tot_basis = sfxmap.count_range(pstats_by_group(rows_, "count"), fid)
        vset = obs["videos"] if tot_basis.startswith("by_format") else obs["all_videos"]
        per_video_tot = {v: sum(allc.get(t, {}).get(v, 0) for t in counted_types) for v in vset}
    elif cat.get("per_video_total"):
        tot_st, tot_basis = sfxmap.count_range(cat.get("per_video_total"), fid)
    status, msg = verdict("효과음 총", n_all, tot_st, tot_basis, per_video_tot)
    b.add("audio.sfx.count", "catalog:total", f"효과음 총 개수 (레퍼런스 {fid} 범위 대비)", CAT["sfx_count"],
          kind="style_vs_reference", reference=tot_st or "못 잼",
          expected={"allowed": V.allowed_count_range(tot_st) if tot_st else None, "basis": tot_basis,
                    "classes": sorted(counted)},
          observed=n_all, tolerance="[floor(p10), ceil(p90)] 또는 레퍼런스 영상에서 관측된 총 개수",
          status=status, keys=["audio.sfx.catalog"], required=req,
          note=(msg + ("" if obs_ok else f" — 영상별 관측 개수를 쓸 수 없어 범위만 검사: {obs['problem']}")).strip())


def _catalog(b: RowBuilder) -> dict | None:
    from .. import paths
    from ..util.jsonio import read_json

    rel = b.pget("audio.sfx.catalog")
    if not rel:
        return None
    return read_json(paths.absp(rel))


# ----------------------------------------------------------------------------- structure / cover
# structure.first_caption_at_s is measured by the reference analyzer (shortkit.reference.aggregate) as the start of each
# video's first TIMED caption: captions whose role is one of ``reference.aggregate.FIRST_CAPTION_EXCLUDED_ROLES`` are
# left out (title and description frame the whole video).  QA applies the identical definition to the output
# (tests/qa/test_qa_rows2.py runs both on one set).  ``checks.FIRST_CAPTION_EXCLUDED_ROLES`` IS that tuple (module
# __getattr__ below: imported on first use so that this module stays import-light for shortkit.config).
FIRST_CAPTION_TOL_S = 0.2


def _first_caption_excluded_roles() -> tuple[str, ...]:
    from ..reference.aggregate import FIRST_CAPTION_EXCLUDED_ROLES

    return FIRST_CAPTION_EXCLUDED_ROLES


def __getattr__(name: str):          # PEP 562: checks.FIRST_CAPTION_EXCLUDED_ROLES -> the aggregate's own tuple
    if name == "FIRST_CAPTION_EXCLUDED_ROLES":
        return _first_caption_excluded_roles()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def first_timed_caption(captions, measured: list[dict]) -> dict:
    """Onset measured in the output of the first timed caption (roles not in FIRST_CAPTION_EXCLUDED_ROLES).
    ``captions``: the ResolvedEdit captions (roles); ``measured``: text-probe caption items (id, onset).  If a timed
    caption whose onset could not be measured is planned early enough to have been the first one, the value is
    None (unmeasured) -- a later caption must not stand in for it."""
    on = {m.get("id"): m.get("onset") for m in measured}
    excluded = _first_caption_excluded_roles()
    timed = [c for c in captions if c.role not in excluded]
    got = [(float(on[c.id]), c) for c in timed if on.get(c.id) is not None]
    base = "정의: 제목·설명을 뺀 첫 시간제 자막의 출력 등장 시각(레퍼런스 분석기 structure.first_caption_at_s 와 같음)"
    if not timed:
        return {"t": None, "caption": None, "role": None, "note": base + " — 시간제 자막이 없음"}
    t0, c0 = min(got, key=lambda x: x[0]) if got else (None, None)
    blind = [c.id for c in timed if on.get(c.id) is None and (t0 is None or float(c.start) < t0 + FIRST_CAPTION_TOL_S)]
    if blind:
        return {"t": None, "caption": None, "role": None,
                "note": base + f" — 먼저 나왔을 수 있는 자막의 등장 시각을 측정하지 못함: {', '.join(blind)}"}
    return {"t": round(t0, 3), "caption": c0.id, "role": c0.role, "note": base}


def rows_structure(b: RowBuilder, probes: dict) -> None:
    ctx = b.ctx
    fr = 1.0 / ctx.fps
    d_obs = ctx.info.duration
    b.add("structure.duration", "duration", "영상 길이", CAT["structure"], expected=_r(ctx.resolved.duration, 3),
          observed=_r(d_obs, 3), tolerance="±2프레임", status="same" if abs(d_obs - ctx.resolved.duration) <= 2 * fr + 0.01 else "different")
    b.style_row("structure.duration", "duration_ref", "영상 길이 (레퍼런스 분포 대비)", CAT["structure"],
                ["structure.duration_s.p10", "structure.duration_s.p50", "structure.duration_s.p90"],
                {"duration": _r(d_obs, 2)}, lambda o, r: _in_distribution(o, "duration", r, "structure.duration_s"),
                note=DIST_NOTE)
    fc = first_timed_caption(ctx.resolved.captions, (probes.get("text") or {}).get("captions") or [])
    b.style_row("structure.duration", "first_caption_ref", "첫 시간제 자막 시각 (레퍼런스 대비)", CAT["structure"],
                ["structure.first_caption_at_s"],
                {"first_caption_at_s": fc["t"], "caption": fc["caption"], "role": fc["role"]} if fc["t"] is not None else None,
                lambda o, r: abs(o["first_caption_at_s"] - float(r.get("structure.first_caption_at_s") or 0)) <= FIRST_CAPTION_TOL_S,
                evidence={"t": fc["t"]}, note=fc["note"])
    _rows_cut_structure(b, probes)
    cov = (probes.get("text") or {}).get("cover")
    if cov:
        sim = cov.get("similarity")
        b.add("cover.frame", "frame", "표지 프레임에 제목 문구 표시", CAT["structure"],
              expected={"t": cov.get("t"), "text": cov.get("expected_text"), "role": cov.get("text_role"),
                        "source": cov.get("source")},
              observed={"ocr": cov.get("ocr"), "similarity": sim, "role_caption_visible": cov.get("role_caption_visible")},
              tolerance="OCR 유사도 ≥ 0.5 (cover.source=first_frame 이면 첫 프레임)",
              status="unmeasured" if sim is None else ("same" if sim >= 0.5 else "different"),
              keys=["cover.source", "cover.text_role"], required=False, evidence={"t": cov.get("t")},
              note=cov.get("note") or "")
        def _cover_same(o, r):
            src_ok = o["source"] == r.get("cover.source") and (o["source"] != "first_frame" or float(o["t"] or 0) == 0.0)
            role_ok = o["text_role"] == r.get("cover.text_role") and bool(o["text_role_visible"])
            return _all(src_ok, role_ok, None if o["similarity"] is None else o["similarity"] >= 0.5)
        b.style_row("cover.frame", "cover_ref", "표지 구성 (레퍼런스 대비)", CAT["structure"], ["cover.source", "cover.text_role"],
                    {"t": cov.get("t"), "source": cov.get("source"), "text_role": cov.get("text_role"),
                     "text_role_visible": cov.get("role_caption_visible"), "similarity": sim}, _cover_same,
                    note="표지 프레임(cover.source: first_frame = 0초)에서 cover.text_role 역할 자막의 문구를 OCR 로 확인")


CUT_STRUCTURE_KEYS = ("structure.cuts_per_10s.p10", "structure.cuts_per_10s.p50", "structure.cuts_per_10s.p90",
                      "structure.shot_len_s.p10", "structure.shot_len_s.p50", "structure.shot_len_s.p90")
DIST_NOTE = ("판정: 레퍼런스 영상별 값의 p10 ≤ 출력 ≤ p90 이면 같다; 레퍼런스 중앙값(p50) 대비 위치(observed.vs_reference_median)"
             "를 함께 적음 — p50 이 [p10, p90] 밖이면 분포 기록이 잘못된 것이라 못 잼")


def _in_distribution(o: dict, field: str, r, stem: str) -> bool | None:
    """Output value ``o[field]`` inside the reference distribution [p10, p90] of ``stem`` (every one of p10, p50, p90
    is read).  The position against the reference median is written into the observed dict (``vs_reference_median``:
    difference and side); a p50 outside [p10, p90] (an inconsistent distribution record) makes the row 못 잼."""
    p10, p50, p90 = r.get(f"{stem}.p10"), r.get(f"{stem}.p50"), r.get(f"{stem}.p90")
    v = o.get(field)
    if v is None or p10 is None or p50 is None or p90 is None:
        return None
    p10, p50, p90, v = float(p10), float(p50), float(p90), float(v)
    o["vs_reference_median"] = {"p50": _r(p50, 3), "diff": _r(v - p50, 3),
                                "side": "중앙값" if abs(v - p50) < 1e-9 else ("중앙값 위" if v > p50 else "중앙값 아래"),
                                "range": [_r(p10, 3), _r(p90, 3)]}
    if not p10 <= p50 <= p90:
        o["vs_reference_median"]["note"] = "p50 이 [p10, p90] 밖: 분포 기록 불일치"
        return None
    return p10 <= v <= p90


def _rows_cut_structure(b: RowBuilder, probes: dict) -> None:
    """Cut structure of the OUTPUT vs the format's reference distribution (S2QA-15).  One definition for the reference
    (``reference.aggregate.cut_structure_rows``: per video, transitions cut/flash/crossfade with 0 < t < duration ->
    transitions per 10 s, and the median of the shot lengths between 0, the transitions and the end), the plan
    (``edit.validate.check_cut_structure``) and the output here (``edit.validate.cut_structure`` over the transitions
    MEASURED in the MP4: planned boundaries seen in the output + unplanned cuts, ``grid.our_cuts``).  Keys compared,
    exactly: structure.cuts_per_10s.p10/.p50/.p90 and structure.shot_len_s.p10/.p50/.p90 (inside [p10, p90] = same; the
    position against p50 is reported in the row); unmeasured preset keys -> 못 잼."""
    from ..edit.validate import cut_structure
    from .grid import our_cuts

    ctx = b.ctx
    d_obs = float(ctx.info.duration)
    cuts = our_cuts(probes.get("video") or {})
    obs_rate = obs_len = None
    if cuts is not None and d_obs > 0:
        cs = cut_structure([float(c["t"]) for c in cuts], d_obs)
        obs_rate = {"cuts_per_10s": cs["cuts_per_10s"], "n_cuts": cs["n_cuts"], "duration": cs["duration"],
                    "types": sorted({c["type"] for c in cuts if 0.0 < float(c["t"]) < d_obs})}
        obs_len = {"shot_len_median_s": cs["shot_len_median_s"], "shots_s": cs["shots_s"]}
    how = ("레퍼런스 값 = `shortkit ref aggregate` 의 영상별 값(한 영상 = 1표본) 분포, 출력 값 = 같은 정의로 출력 MP4 에서 잰 값"
           "(reference.aggregate.CUT_RATE_METHOD / SHOT_LEN_METHOD)")
    b.style_row("structure.cuts", "rate_ref", "컷 밀도: 10초당 전환 수 (레퍼런스 포맷 분포 대비)", CAT["cut"],
                list(CUT_STRUCTURE_KEYS[:3]), obs_rate,
                lambda o, r: _in_distribution(o, "cuts_per_10s", r, "structure.cuts_per_10s"),
                note="출력에서 잰 전환(cut·flash·crossfade: 계획 경계에서 보인 것 + 계획 밖 컷) 기준. " + how + ". " + DIST_NOTE)
    b.style_row("structure.cuts", "shot_len_ref", "샷 길이 중앙값 (레퍼런스 포맷 분포 대비)", CAT["cut"],
                list(CUT_STRUCTURE_KEYS[3:]), obs_len,
                lambda o, r: _in_distribution(o, "shot_len_median_s", r, "structure.shot_len_s"),
                note="출력에서 잰 전환 사이 샷 길이(첫·마지막 샷 포함)의 중앙값. " + how + ". " + DIST_NOTE)


# ----------------------------------------------------------------------------- presence (있다/없다/못 잼)
PRESENCE_ITEMS = {"zoom": "motion", "freeze": "motion", "speed_change": "motion", "flash": "motion",
                  "crossfade": "motion", "decorations": "deco", "bgm": "music", "original_audio": "original",
                  "ducking": "music", "intentional_silence": "music"}
PRESENCE_KO = {"zoom": "확대(줌)", "freeze": "정지", "speed_change": "속도 변화", "flash": "플래시 전환",
               "crossfade": "크로스페이드", "decorations": "움직이는 장식", "bgm": "BGM", "original_audio": "원음",
               "ducking": "덕킹", "intentional_silence": "의도적 정적"}


def _no_zoom_status(it: dict) -> tuple[str, str]:
    """No zoom planned in a clip: 'same' (no zoom in the output) / 'different' (a zoom seen) / 'unmeasured'."""
    dev = it.get("measured_max_dev") or 0.0
    reliable = (it.get("n_samples") or 0) >= 10 and (it.get("median_inliers") or 0) >= 40 and \
        (it.get("measured_spread") or 0) <= 0.02
    corr = it.get("zoom_ratio_corrected")
    geo = it.get("geometry") or {}
    note = "소스 자체의 카메라 줌도 여기에 잡힘"
    if dev > 0.05 and geo.get("confirmed") is True:
        # direct evidence wins over the feature scale curve (fooled by subjects walking to the camera)
        return "same", (f"특징점 배율 곡선은 {dev:.2f} 움직였지만, 출력 프레임이 계획 기하(줌 없음)로 놓은 소스 프레임과 같음 "
                        f"(NCC 중앙 {geo.get('ncc_median')}, 4% 확대 대안보다 {geo.get('alt_gap_median')} 높음) → 피사체 움직임")
    if dev > 0.05 and corr is not None and abs(corr - 1.0) <= 0.05:
        return "same", note                 # the source itself changed scale (subject/camera motion)
    if dev <= 0.05:
        return "same", note
    if dev > 0.08 and reliable and corr is not None and abs(corr - 1.0) > 0.08:
        return "different", note
    return "unmeasured", note + "; 특징점 추정이 불안정해 판정 보류"


def presence_observed(ctx, probes: dict) -> dict[str, tuple[str, str]]:
    """{item: (present|absent|unmeasured, basis)} of the OUTPUT, from the probes of the final MP4."""
    vp = probes.get("video") or {}
    ap = probes.get("audio") or {}
    out: dict[str, tuple[str, str]] = {}
    zm = vp.get("zoom")
    if zm is None:
        out["zoom"] = ("unmeasured", "줌 측정 실패")
    else:
        pres = [it["clip_id"] for it in zm["clips"] if it.get("expected") and it.get("status") == "measured"
                and abs(float(it.get("zoom_ratio_corrected") or it.get("measured_final_ratio") or 1.0) - 1.0) > TOL["zoom_ratio"]]
        st_no = [(_no_zoom_status(it)[0] if it.get("status") == "measured" else "unmeasured")
                 for it in zm["clips"] if not it.get("expected")]
        unplanned = "different" in st_no
        if pres or unplanned:
            out["zoom"] = ("present", "출력에서 잰 줌: " + ", ".join(pres) + (" + 계획에 없는 줌" if unplanned else ""))
        elif all(x == "same" for x in st_no) and all(it.get("status") == "measured" for it in zm["clips"]):
            out["zoom"] = ("absent", "모든 클립에서 배율 변화 없음(출력 측정)")
        else:
            out["zoom"] = ("unmeasured", "일부 클립의 줌 여부를 판정하지 못함")
    fz = vp.get("freezes")
    if fz is None:
        out["freeze"] = ("unmeasured", "정지 측정 실패")
    else:
        seen = [e["clip_id"] for e in fz.get("expected") or [] if e.get("observed")]
        un = [r for r in fz.get("unexpected") or [] if r.get("source_static") is not True]
        blind = [e["clip_id"] for e in fz.get("expected") or [] if e.get("distinguishable") is False]
        if seen or un:
            out["freeze"] = ("present", f"출력의 반복 프레임 구간 {len(seen) + len(un)}개")
        elif blind:
            out["freeze"] = ("unmeasured", "정지 직전 소스가 거의 움직이지 않아 구별 못 함: " + ", ".join(blind))
        else:
            out["freeze"] = ("absent", "출력에 반복 프레임 구간 없음(소스가 멈춘 구간 제외)")
    mp = vp.get("mapping") or {}
    items = mp.get("clips") or []
    sp_seen = [x["clip_id"] for x in items if x.get("speed_obs") is not None and abs(float(x["speed_obs"]) - 1.0) > 0.1]
    if sp_seen:
        out["speed_change"] = ("present", "출력에서 잰 재생 속도 ≠ 1: " + ", ".join(sp_seen))
    elif items and len(items) == len(ctx.resolved.clips) and all(x.get("status") == "measured" and (
            x.get("mode") == "still_match" or (x.get("offset_p50") is not None and abs(float(x["offset_p50"])) <= 0.1))
            for x in items) and all(abs(float(c.speed or 1.0) - 1.0) <= 1e-3 for c in ctx.resolved.clips):
        out["speed_change"] = ("absent", "모든 클립이 계획한 소스 시각대로(속도 1) 나옴(소스 대조)")
    else:
        out["speed_change"] = ("unmeasured", "클립별 재생 속도를 모두 확인하지 못함")
    tr = vp.get("transitions")
    for k in ("flash", "crossfade"):
        if tr is None:
            out[k] = ("unmeasured", "전환 측정 실패")
            continue
        n = sum(1 for bd in tr.get("boundaries") or [] if (bd.get("observed") or {}).get("type") == k) + \
            sum(1 for x in tr.get("unexpected") or [] if x.get("type") == k)
        out[k] = ("present", f"출력에서 잰 {k} {n}개") if n else ("absent", f"출력 전체에서 {k} 없음(프레임 차이·밝기 검사)")
    deco = [it for it in ((vp.get("decorations") or {}).get("items") or []) if it.get("status") == "measured"
            and it.get("position")]
    out["decorations"] = (("present", "출력에서 잰 장식 " + ", ".join(it["id"] for it in deco)) if deco else
                          ("unmeasured", "계획에 없는 장식을 출력에서 찾는 검출기가 없어 '없다'를 확정하지 못함"))
    if ap.get("status") == "no_audio":
        for k in ("bgm", "original_audio", "ducking", "intentional_silence"):
            out[k] = ("absent", "오디오 트랙 없음")
        return out
    if ap.get("status") != "measured":
        for k in ("bgm", "original_audio", "ducking", "intentional_silence"):
            out[k] = ("unmeasured", "오디오 측정 실패")
        return out
    bi = ap.get("bgm") or {}
    found = bi.get("status") == "measured" and bool(bi.get("found"))
    out["bgm"] = (("present", "계획한 음원 파형을 출력에서 찾음") if found else
                  ("unmeasured", "모르는 음악의 부재는 증명 못 함" if bi.get("status") == "not_planned" else
                   "계획한 BGM 을 출력에서 찾지 못함"))
    og = ap.get("originals") or {}
    wins = og.get("windows") or []
    has_src_audio = any(t.get("has_audio") for t in og.get("tracks") or [])
    if any(w.get("present") for w in wins):
        out["original_audio"] = ("present", "출력 믹스에서 원음 확인(창별 최소제곱)")
    elif not has_src_audio and og.get("tracks") is not None:
        out["original_audio"] = ("absent", "소스에 소리가 없음")
    elif wins:
        out["original_audio"] = ("absent", "원음 창 모두 없음")
    else:
        out["original_audio"] = ("unmeasured", "원음 창을 재지 못함")
    if found:
        span = bi.get("audible_span_obs")
        fo = float(getattr(ctx.resolved.audio.bgm, "fade_out_s", 0) or 0) if ctx.resolved.audio.bgm else 0.0
        sil = [x for x in bi.get("silent_ranges_obs") or [] if span is None or (x[0] > span[0] + 0.1 and x[1] < span[1] - fo - 0.1)]
        out["ducking"] = (("present", f"출력에서 잰 BGM 낮춤 {len(bi.get('ducked_ranges_obs') or [])}구간")
                          if bi.get("ducked_ranges_obs") else ("absent", "BGM 이득 곡선에 낮춤 없음"))
        out["intentional_silence"] = (("present", f"출력에서 잰 BGM 끊김 {len(sil)}구간") if sil else
                                      ("absent", "BGM 이득 곡선에 끊김 없음(시작·끝 페이드 제외)"))
    else:
        out["ducking"] = ("unmeasured", "BGM 을 출력에서 찾지 못해 덕킹 여부 못 잼")
        out["intentional_silence"] = ("unmeasured", "BGM 을 출력에서 찾지 못해 정적 여부 못 잼")
    return out


def rows_presence(b: RowBuilder, probes: dict) -> None:
    """presence.<item>: the channel-level 있다/없다 of the reference (preset key, from `ref aggregate` /
    `ref audio-measure`) vs the same item in our output.  Reference absent -> ours must be absent; reference present in
    every measured video of the format -> ours must be present; reference present in some videos only -> either state
    is inside the observed range."""
    obs = presence_observed(b.ctx, probes)
    meas = b.measurements()
    fmt = b.ctx.preset.format_id
    for k, cat in PRESENCE_ITEMS.items():
        key = f"presence.{k}"
        m = meas.get(key) or {}
        st = ((m.get("by_format") or {}).get(fmt or "") if fmt else None) or m.get("overall") or {}
        share = st.get("share")
        ours, basis = obs.get(k, ("unmeasured", "측정 없음"))

        def cmp(o, r, key=key, share=share):
            ref = r.get(key)
            if ref not in ("present", "absent"):
                return None
            if ref == "absent":
                return None if o["presence"] == "unmeasured" else o["presence"] == "absent"
            if share is not None and float(share) >= 1.0:
                return None if o["presence"] == "unmeasured" else o["presence"] == "present"
            return True
        b.style_row("presence", k, f"{PRESENCE_KO[k]} 있다/없다 (레퍼런스 대비)", CAT[cat], [key],
                    {"presence": ours, "basis": basis, "reference_share": share}, cmp,
                    note=("레퍼런스가 없다 → 우리도 없어야 같다; 레퍼런스 영상 모두 있다 → 우리도 있어야 같다; 일부 영상에만 있다 → "
                          "있다/없다 모두 관측 범위 안"))


# ----------------------------------------------------------------------------- entry
def _grid_rows(b: RowBuilder, probes: dict) -> None:
    from .grid import rows_reference_grid

    rows_reference_grid(b, probes)


BUILDERS = [(("canvas.",), rows_canvas), (("caption.",), rows_captions), (("video.",), rows_video),
            (("decor.",), rows_decorations), (("identity.", "clean.corners"), rows_identity),
            (("clean.residual",), rows_residual), (("cover_up.",), rows_cover_up), (("audio.",), rows_audio),
            (("structure.", "cover."), rows_structure), (("presence",), rows_presence), (("ref_grid.",), _grid_rows)]


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
