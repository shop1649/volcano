"""QA run orchestration and the report files (report.json / report.md / probes/*.json)."""
from __future__ import annotations

import json
import time
from collections import Counter, OrderedDict
from pathlib import Path

from . import QA_SCHEMA, QAContext, load_context
from .checks import CAT, REQUIRED_CATEGORIES, build_rows, families_for

KO = {"same": "같다", "different": "다르다", "unmeasured": "못 잼"}


def run_probes(ctx: QAContext, families: set[str], quiet: bool = False) -> tuple[dict, dict]:
    probes: dict = {}
    timing: dict = {}

    def say(msg):
        if not quiet:
            print(msg, flush=True)

    if "text" in families:
        from .probes_text import probe_text

        t = time.time()
        say("[qa] 자막·식별 문구 OCR 측정 중…")
        probes["text"] = probe_text(ctx)
        timing["text_s"] = round(time.time() - t, 1)
    if "video" in families:
        from .probes_video import analyze_layout, probe_video

        t = time.time()
        say("[qa] 영상(컷·줌·정지·장식·잔류) 측정 중…")
        v = probe_video(ctx)
        sc = v.pop("_scan", None)
        if sc is not None:
            boxes = [c["bbox_obs"] for c in (probes.get("text") or {}).get("captions") or [] if c.get("bbox_obs")]
            try:
                v["layout"] = analyze_layout(ctx, sc, boxes)
            except Exception as e:
                v.setdefault("errors", {})["layout"] = f"{type(e).__name__}: {e}"
        probes["video"] = v
        timing["video_s"] = round(time.time() - t, 1)
    if "audio" in families:
        from .probes_audio import probe_audio

        t = time.time()
        say("[qa] 오디오(BGM·원음·효과음·음량) 측정 중…")
        try:
            probes["audio"] = probe_audio(ctx)
        except Exception as e:
            probes["audio"] = {"status": "error", "errors": {"audio": f"{type(e).__name__}: {e}"}}
        timing["audio_s"] = round(time.time() - t, 1)
    return probes, timing


def measurement_stats(ctx: QAContext, rows: list[dict], probes: dict) -> dict:
    """{n, p10, p50, p90} of the measured errors, overall and for this episode's format."""
    from ..util.stats import pstats

    def errs(check, fn):
        out = []
        for r in rows:
            if r["check_id"] == check and r.get("observed") and r["status"] != "unmeasured":
                try:
                    v = fn(r)
                except (KeyError, TypeError, IndexError):
                    v = None
                if v is not None:
                    out.append(abs(float(v)))
        return out

    import math

    series = {
        "caption_center_error_px": errs("caption.position", lambda r: math.hypot(r["observed"].get("dx") or 0,
                                                                                r["observed"].get("dy") or 0)),
        "caption_onset_error_s": errs("caption.timing", lambda r: (r["observed"]["onset"] - r["expected"]["start"])
                                      if r["observed"].get("onset") is not None else None),
        "caption_offset_error_s": errs("caption.timing", lambda r: (r["observed"]["offset"] - r["expected"]["end"])
                                       if r["observed"].get("offset") is not None else None),
        "sfx_time_error_s": errs("audio.sfx.placement", lambda r: (r["observed"]["t"] - r["expected"]["t"])
                                 if "t" in (r.get("observed") or {}) else None),
        "sfx_event_offset_s": errs("audio.sfx.offset", lambda r: r["observed"]["offset"]),
        "cut_time_error_s": errs("video.cuts", lambda r: (r["observed"]["t"] - r["expected"]["t"])
                                 if isinstance(r.get("expected"), dict) and r["observed"].get("t") is not None else None),
    }
    fmt = ctx.resolved.format_id or "UNCLASSIFIED"
    return {k: {"overall": pstats(v, 4), "by_format": {fmt: pstats(v, 4)}} for k, v in series.items()}


def summarize(rows: list[dict]) -> dict:
    c = Counter(r["status"] for r in rows)
    by_cat: dict = OrderedDict()
    for r in rows:
        d = by_cat.setdefault(r["category"], {"same": 0, "different": 0, "unmeasured": 0})
        d[r["status"]] += 1
    return {"total": len(rows), "same": c.get("same", 0), "different": c.get("different", 0),
            "unmeasured": c.get("unmeasured", 0),
            "intended_change": sum(1 for r in rows if r.get("intended_change")),
            "different_unintended": sum(1 for r in rows if r["status"] == "different" and not r.get("intended_change")),
            "by_category": by_cat,
            "by_kind": {k: dict(Counter(r["status"] for r in rows if r.get("kind") == k))
                        for k in ("output_vs_plan", "style_vs_reference")}}


def _canon_sha(path) -> str | None:
    """sha256 of a judging-input file: YAML/JSON by their parsed content (comments / formatting do not count),
    anything else by its bytes; None when the file does not exist."""
    import hashlib

    from ..util.hashing import sha256_file
    from ..util.jsonio import read_json, read_yaml

    p = Path(path)
    if not p.is_file():
        return None
    try:
        if p.suffix in (".yaml", ".yml"):
            data = read_yaml(p)
        elif p.suffix == ".json":
            data = read_json(p)
        else:
            return sha256_file(p)
        return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()
    except Exception:
        return sha256_file(p)


def input_fingerprints(episode_id: str, preset) -> dict:
    """{root-relative path: sha256 | None} of every file the QA rows are judged against: the preset layers
    (preset.yaml, measured.yaml, requested_changes.yaml), formats.yaml (reference choice), the SFX catalog and map,
    the plan, the resolved edit and its ASS, and the human check records.  The gate (G6) refuses a report whose
    inputs changed after the run."""
    from .. import paths

    ep = paths.episode_dir(episode_id)
    files = [preset.dir / "preset.yaml", preset.dir / "measured.yaml", preset.dir / "requested_changes.yaml"]
    for key in ("structure.formats_file", "audio.sfx.catalog", "audio.sfx.map"):
        try:
            v = preset.get(key)
        except KeyError:
            v = None
        if v:
            files.append(paths.absp(v))
    files += [ep / "plan.yaml", ep / "build" / "resolved.json", ep / "build" / "captions.ass",
              ep / "qa" / "human_checks.jsonl"]
    out = {}
    for f in files:
        try:
            k = paths.relp(f)
        except ValueError:
            k = Path(f).name
        out[k] = _canon_sha(f)
    return out


def reference_record(ctx: QAContext, sheets: list[str]) -> dict:
    ri = ctx.reference_info or {}
    rep = ri.get("representative") or {}
    return {"path": _safe_rel(ctx.reference_mp4), "video_id": ctx.reference_id,
            "analysis_files": sorted(ctx.reference_analysis.keys()),
            "representative": {k: rep.get(k) for k in ("format_id", "video_id", "path", "source", "reason")},
            "is_representative": bool(ctx.reference_id and rep.get("video_id") == ctx.reference_id),
            "chosen_by": ri.get("chosen_by"), "override_reason": ri.get("override_reason"),
            "sheets": list(sheets)}


def run_and_write(episode_id: str, reference: str | None = None, sheet_seconds: float = 15.0, mp4: str | None = None,
                  reference_id: str | None = None, only: list[str] | None = None, recheck_others: bool = True,
                  quiet: bool = False, write: bool = True, reference_override_reason: str | None = None) -> dict:
    from .. import paths
    from ..util.hashing import sha256_file
    from ..util.jsonio import now_iso, write_json
    from . import gate as gate_mod
    from . import grid as grid_mod
    from . import human as human_mod
    from .sheet import make_sheets

    t0 = time.time()
    ctx = load_context(episode_id, reference=reference, mp4=mp4, reference_id=reference_id,
                       reference_override_reason=reference_override_reason)
    sha = sha256_file(ctx.mp4)
    ctx.options["mp4_sha256"] = sha
    ctx.options["human_checks"] = human_mod.load(episode_id)
    inputs = input_fingerprints(episode_id, ctx.preset)
    fams = families_for(only) if only else {"text", "video", "audio"}
    probes, timing = run_probes(ctx, fams, quiet=quiet)
    rows = build_rows(ctx, probes, only)
    if only or not write:
        return {"episode_id": episode_id, "partial": True, "only": only, "rows": rows,
                "output": {"path": paths.relp(ctx.mp4), "sha256": sha}}
    sheets = []
    sheet_error = None
    try:
        sheets = make_sheets(ctx, probes.get("text"), probes.get("audio"), sheet_seconds)
    except Exception as e:
        sheet_error = f"{type(e).__name__}: {e}"
        probes.setdefault("errors", {})["sheet"] = sheet_error
    reference_rec = reference_record(ctx, sheets)
    grid_mod.sheet_row(ctx, rows, reference_rec, sheet_error)
    probe_files = {}
    pdir = ctx.qa_dir / "probes"
    for name, data in probes.items():
        if name == "errors":
            continue
        f = pdir / f"{name}.json"
        write_json(f, data)
        probe_files[name] = paths.relp(f)
    unmeasured_keys = ctx.preset.unmeasured_keys()
    deliverable = paths.relp(paths.absp(ctx.resolved.output_path or f"episodes/{episode_id}/output/{episode_id}.mp4"))
    rep = {
        "schema": QA_SCHEMA, "episode_id": episode_id, "preset_id": ctx.resolved.preset_id,
        "preset_name": ctx.resolved.preset_name, "format_id": ctx.resolved.format_id, "mode": ctx.resolved.mode,
        "measured_at": now_iso(),
        "principle": "최종 MP4 만 측정(타임라인/코드가 맞다고 출력이 맞다고 보지 않음)",
        "output": {"path": paths.relp(ctx.mp4), "sha256": sha, "duration": round(ctx.info.duration, 4),
                   "resolution": [ctx.info.width, ctx.info.height], "fps": ctx.info.fps,
                   "has_audio": ctx.info.has_audio, "deliverable": deliverable, "is_deliverable": ctx.deliverable},
        "reference": reference_rec,
        "inputs": inputs,
        "human_checks_used": [h for h in ctx.options.get("human_checks") or [] if h.get("mp4_sha256") == sha],
        "tools": _tools(probes),
        "timing_s": {**timing, "total_s": round(time.time() - t0, 1)},
        "summary": summarize(rows),
        "required_categories": {c: ("있음" if any(r["category"] == c for r in rows) else "해당 없음")
                                for c in REQUIRED_CATEGORIES},
        "unmeasured": [{"row_id": r["row_id"], "item": r["item"], "required": r["required"], "kind": r["kind"],
                        "reason": r.get("note") or "", "impact": r.get("impact") or "",
                        "covered_by": r.get("covered_by")}
                       for r in rows if r["status"] == "unmeasured"],
        "stats": measurement_stats(ctx, rows, probes),
        "preset_unmeasured_keys": {"count": len(unmeasured_keys), "keys": unmeasured_keys},
        "rows": rows, "sheets": sheets, "probes": probe_files,
        "probe_errors": {k: v.get("errors") for k, v in probes.items() if isinstance(v, dict) and v.get("errors")},
    }
    rep["gate"] = gate_mod.evaluate(rows, mode=ctx.resolved.mode, mp4_sha_measured=sha, mp4_sha_now=sha,
                                    unmeasured_preset_keys=unmeasured_keys, plan=ctx.plan, reference=reference_rec,
                                    measured_path=paths.relp(ctx.mp4), deliverable_path=deliverable,
                                    inputs_measured=inputs, inputs_now=inputs,
                                    approval=gate_mod.approval_facts(ctx.plan, ctx.preset))
    write_json(ctx.qa_dir / "report.json", rep)
    if ctx.deliverable:
        try:
            from . import defects

            rep["defects"] = defects.sync(ctx, rep, recheck_others=recheck_others, quiet=quiet)
            write_json(ctx.qa_dir / "report.json", rep)
        except Exception as e:
            rep["defects"] = {"error": f"{type(e).__name__}: {e}"}
    else:
        rep["defects"] = {"skipped": "납품 MP4 가 아닌 파일(--mp4)의 검수 — 결함 기록·최종 관문에 쓰지 않음"}
        write_json(ctx.qa_dir / "report.json", rep)
    (ctx.qa_dir / "report.md").write_text(render_md(rep), encoding="utf-8")
    # the preset keys this QA run read (-> settings_registry code links; config.ACCESS_LOG_GLOBS collects it).
    # Only full runs write it: a partial re-check (only=..., write=False) returns above without touching it.
    ctx.preset.save_access_log(ctx.qa_dir / "preset_access.json")
    return rep


def _safe_rel(p) -> str | None:
    """Root-relative path for storage; a file outside the project is recorded by name only
    (absolute / machine-specific paths are never stored)."""
    from .. import paths

    if p is None:
        return None
    try:
        return paths.relp(p)
    except ValueError:
        return f"(프로젝트 밖 파일: {Path(p).name})"


def _tools(probes: dict) -> dict:
    t = probes.get("text") or {}
    v = probes.get("video") or {}
    return {"ocr": t.get("ocr_engine") or t.get("reason"), "face_detector": (v.get("faces") or {}).get("detector")
            or (v.get("faces") or {}).get("reason"),
            "clean_verify": (v.get("residual") or {}).get("clean_verify_available")}


# ----------------------------------------------------------------------------- markdown
def _fmt(v, n: int = 90) -> str:
    if v is None:
        return "—"
    if isinstance(v, str):
        s = v
    else:
        try:
            s = json.dumps(v, ensure_ascii=False, separators=(",", ":"), default=str)
        except Exception:
            s = str(v)
    s = s.replace("|", "／").replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def _ev(r: dict, base: str | None = None) -> str:
    import os

    e = r.get("evidence") or {}
    parts = []
    if e.get("t") is not None:
        try:
            parts.append(f"t={float(e['t']):.2f}s")
        except (TypeError, ValueError):
            parts.append(f"t={e['t']}")
    if e.get("frame"):
        link = os.path.relpath(e["frame"], base).replace(os.sep, "/") if base else e["frame"]
        parts.append(f"[프레임]({link})")
    if r.get("note"):
        parts.append(_fmt(r["note"], 70))
    return " ".join(parts) or "—"


def render_md(rep: dict) -> str:
    s = rep["summary"]
    g = rep["gate"]
    L = []
    base = f"episodes/{rep['episode_id']}/qa"
    L.append(f"# QA 보고서 — {rep['episode_id']}")
    L.append("")
    L.append(f"- 측정 대상: `{rep['output']['path']}` (sha256 `{rep['output']['sha256'][:16]}…`, "
             f"{rep['output']['resolution'][0]}x{rep['output']['resolution'][1]}, {rep['output']['duration']:.2f}s)")
    if rep["output"].get("is_deliverable") is False:
        L.append(f"- **납품 MP4 가 아님** (납품: `{rep['output'].get('deliverable')}`) — 이 보고서는 결함 기록·최종 관문에 쓰이지 않음")
    L.append(f"- 원칙: {rep['principle']}")
    L.append(f"- 프리셋: {rep['preset_id']} / 포맷 {rep['format_id']} / 모드 **{rep['mode']}**")
    ref = rep["reference"]
    rp = ref.get("representative") or {}
    L.append(f"- 레퍼런스(같은 절대 시각 비교): {ref.get('video_id') or '없음(못 잼)'}"
             + (f" `{ref['path']}`" if ref.get("path") else "")
             + f" (분석 파일: {', '.join(ref.get('analysis_files') or []) or '없음'})")
    L.append(f"- 포맷 {rp.get('format_id')} 대표 영상(formats.yaml): {rp.get('video_id') or '못 잼'}"
             + (f" — {rp['reason']}" if rp.get("reason") else "")
             + ("" if not ref.get("video_id") else (" · 대표 영상과 같음" if ref.get("is_representative") else
                                                  f" · 대표 영상이 아님(사유: {ref.get('override_reason') or '기록 없음'})")))
    L.append(f"- 측정 시각: {rep['measured_at']} / 도구: OCR={rep['tools'].get('ocr')}, 얼굴검출={rep['tools'].get('face_detector')}")
    L.append("")
    L.append(f"## 최종 관문: **{g['verdict_ko']}**")
    for f in g["failures"]:
        L.append(f"- ✗ {f['rule']}: {f['message']}" + (f" — {', '.join(map(str, f['rows'][:8]))}{' …' if len(f['rows']) > 8 else ''}"
                                                      if f.get("rows") else ""))
    for w in g["warnings"]:
        L.append(f"- △ {w['rule']}: {w['message']}")
    L.append("")
    L.append("## 요약")
    L.append(f"- 전체 {s['total']}행: 같다 {s['same']} / 다르다 {s['different']} (의도한 변경 {s['intended_change']}, "
             f"의도하지 않음 {s['different_unintended']}) / 못 잼 {s['unmeasured']}")
    L.append(f"- 계획 대비(출력이 계획대로인가): {s['by_kind'].get('output_vs_plan')}")
    L.append(f"- 레퍼런스 대비(레퍼런스와 같은가): {s['by_kind'].get('style_vs_reference')}")
    L.append(f"- 프리셋 미측정(임시값) 키: {rep['preset_unmeasured_keys']['count']}개")
    L.append("")
    L.append("| 분류 | 같다 | 다르다 | 못 잼 |")
    L.append("|---|---:|---:|---:|")
    for cat, d in s["by_category"].items():
        L.append(f"| {cat} | {d['same']} | {d['different']} | {d['unmeasured']} |")
    miss = [c for c, v in rep.get("required_categories", {}).items() if v != "있음"]
    if miss:
        L.append("")
        L.append("이 에피소드에 해당 행이 없는 필수 분류(해당 없음): " + ", ".join(miss))
    L.append("")
    L.append("## 검사표")
    order = list(dict.fromkeys([r["category"] for r in rep["rows"]]))
    for cat in order:
        L.append("")
        L.append(f"### {cat}")
        L.append("")
        L.append("| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |")
        L.append("|---|---|---|---|---|---|---|")
        for r in rep["rows"]:
            if r["category"] != cat:
                continue
            verdict = KO[r["status"]] + ("" if r.get("required") else
                                         (f" (참고; 판정은 {r['covered_by']})" if r.get("covered_by") else " (참고)"))
            ic = ("예 — " + _fmt(r.get("change_ref"), 40)) if r.get("intended_change") else "아니오"
            L.append(f"| {_fmt(r['item'], 60)} | {_fmt(r['reference'], 50)} | {_fmt(r['expected'])} | {_fmt(r['observed'])} | "
                     f"{verdict} | {ic} | {_ev(r, base)} |")
    L.append("")
    L.append("## 못 잼 항목과 이유")
    L.append("")
    un = rep["unmeasured"]
    if not un:
        L.append("- 없음")
    for u in un:
        L.append(f"- {'**필수** ' if u['required'] else ''}{u['item']} (`{u['row_id']}`): {u['reason'] or '이유 기록 없음'}"
                 + (f" — 제작 영향: {u['impact']}" if u.get("impact") else ""))
    if rep.get("probe_errors"):
        L.append("")
        L.append("## 측정 오류")
        for k, v in rep["probe_errors"].items():
            L.append(f"- {k}: {_fmt(v, 300)}")
    L.append("")
    L.append("## 비교 시트")
    for sh in rep.get("sheets") or []:
        L.append(f"- `{sh}`")
    d = rep.get("defects") or {}
    if d:
        L.append("")
        L.append("## 결함 기록 (defects.jsonl)")
        if d.get("skipped"):
            L.append(f"- {d['skipped']}")
        L.append(f"- 열림 {d.get('open', 0)} / 이번에 고침 확인 {d.get('verified_now', 0)} / 재발 {d.get('reopened', 0)} / "
                 f"새로 등록 {d.get('new', 0)} / 고침 기록 필요(resolved_without_fix·fixed_unrechecked) {d.get('needs_record', 0)} / "
                 f"못 잼으로 바뀌어 열린 채 {d.get('unmeasured_now', 0)} / 이전 규칙으로 닫혔다가 재분류 {d.get('reclassified', 0)}")
        for rc in d.get("rechecked_other_episodes") or []:
            L.append(f"- 같은 검사 재확인: {rc}")
    L.append("")
    L.append("---")
    L.append("판정 기준: 같다=허용오차 안, 다르다=허용오차 밖, 못 잼=측정 불가(완료로 치지 않음 — 필수 표시가 없는 '참고' 못 잼도 "
             "production 최종 관문 P4 에서 완료를 막는다; 다른 필수 행이 같은 판정을 하는 경우만 예외). "
             "레퍼런스 열의 '못 잼'은 레퍼런스에서 측정되지 않은 임시값이라는 뜻이다.")
    L.append("")
    hc = rep.get("human_checks_used") or []
    if hc:
        L.append("오디오 판정은 기계 측정(파형 대조·최소제곱·정합 필터·EBU R128)이며, 아래 행만 사람이 직접 듣거나 본 기록"
                 "(qa/human_checks.jsonl, 이 MP4 sha256 에 대해)으로 판정했다: "
                 + "; ".join(f"{h['row_id']} {h['kind']} {h['verdict']} ({h['by']}, {h['at']})" for h in hc))
    else:
        L.append("오디오 판정은 모두 기계 측정(파형 대조·최소제곱·정합 필터·EBU R128)이다. 사람이 직접 들어 본 청취 확인은 "
                 "이 보고서에 포함되어 있지 않다.")
    return "\n".join(L) + "\n"
