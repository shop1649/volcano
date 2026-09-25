"""Format classification of the reference videos.

``prepare``  builds a review packet per analysed video (``analysis/<id>/review/``: 1-fps contact
             sheet, caption timeline, cut list, screen motion, audio events if the audio analysis
             exists) and adds the video to ``presets/<name>/format_labels.csv``
             (video_id, intro_type, structure_type, notes, labeled_by, watched) with ``watched=no``
             and EMPTY labels.  The labels are filled ONLY by someone who actually watched and
             listened to the video; nothing here guesses a label.
``build``    reads the labels (rows with ``watched=yes``, a ``structure_type`` and ``labeled_by``) of
             MEMBERS of the fixed latest-N snapshot only (labels of other videos are kept apart under
             ``outside_snapshot_labels`` and never create a format or change a share)
             and writes ``formats.yaml``: one format per distinct development structure; intro-only
             differences are ``intro_variants`` inside the format; per format n, share, members and
             a representative video = medoid of per-video feature vectors (z-scored, NaN-aware
             Euclidean) among the members, ties -> higher view count, with the reason.  Without any
             valid label the file stays ``status: unmeasured`` with a blocker; ``measured`` requires every
             snapshot member labelled AND a representative for every format (else ``partial``).
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .. import paths
from ..config import load_preset
from ..util.jsonio import now_iso, read_json, read_yaml, write_json, write_yaml
from .common import (ROLE_KO, ROLES, analysis_dir, load_snapshot, read_csv_rows, say, snapshot_blocker,
                     snapshot_members, video_path, views_of, warn, write_csv_rows)

LABEL_HEADER = ["video_id", "intro_type", "structure_type", "notes", "labeled_by", "watched"]
FORMATS_SCHEMA = "shortkit.formats/1"
FORMAT_RULE = "전개 구조가 실제로 다른 것만 별도 포맷. 도입 방식만 다른 것은 같은 포맷의 intro_variants 로 기록"
FEATURE_KEYS = ["duration_s", "cuts_per_10s", "flash_per_10s", "crossfade_per_10s", "captions_per_10s",
                "caption_mean_dur_s", "share_situation", "share_dialogue", "share_reaction", "share_speaker",
                "has_title", "has_description", "zoom_per_10s", "freeze_per_10s", "speed_events", "sfx_per_10s"]


def labels_path(preset: str) -> Path:
    return paths.preset_dir(preset) / "format_labels.csv"


# ============================================================================= features
def video_features(preset: str, vid: str) -> dict | None:
    d = analysis_dir(preset, vid)
    shots = read_json(d / "shots.json")
    caps = read_json(d / "captions.json")
    mot = read_json(d / "motion.json")
    sfx = read_json(d / "audio" / "sfx_events.json")
    if not (shots or caps or mot):
        return None
    dur = None
    for src in (shots, caps, mot):
        if src and src.get("duration"):
            dur = float(src["duration"])
            break
    f: dict[str, float | None] = {k: None for k in FEATURE_KEYS}
    f["duration_s"] = dur
    per10 = (lambda n: round(10.0 * n / dur, 4)) if dur else (lambda n: None)  # noqa: E731
    if shots:
        cuts = shots.get("cuts") or []
        f["cuts_per_10s"] = per10(sum(c["type"] == "cut" for c in cuts))
        f["flash_per_10s"] = per10(sum(c["type"] == "flash" for c in cuts))
        f["crossfade_per_10s"] = per10(sum(c["type"] == "crossfade" for c in cuts))
    if caps:
        items = caps.get("items") or []
        timed = [c for c in items if c["role"] not in ("title", "description", "identity_mark", "unknown")]
        f["captions_per_10s"] = per10(len(timed))
        f["caption_mean_dur_s"] = round(float(np.mean([c["end"] - c["start"] for c in timed])), 3) if timed else 0.0
        for r in ("situation", "dialogue", "reaction", "speaker"):
            f[f"share_{r}"] = round(sum(c["role"] == r for c in timed) / len(timed), 4) if timed else 0.0
        f["has_title"] = float(any(c["role"] == "title" for c in items))
        f["has_description"] = float(any(c["role"] == "description" for c in items))
    if mot:
        ev = mot.get("events") or []
        f["zoom_per_10s"] = per10(sum(e["type"].startswith("zoom") for e in ev))
        f["freeze_per_10s"] = per10(sum(e["type"] == "freeze" for e in ev))
        f["speed_events"] = float(sum(e["type"] == "speed" for e in ev))
    if sfx:
        f["sfx_per_10s"] = per10(len(sfx.get("events") or []))
    return f


def medoid(members: list[str], feats: dict[str, dict], views: dict[str, int]) -> tuple[str | None, str, dict]:
    """Representative = member with the smallest mean distance to the other members."""
    have = [m for m in members if feats.get(m)]
    if not have:
        return None, "구성원의 분석 파일(shots/captions/motion.json)이 없어 대표 영상을 정하지 못함(못 잼)", {}
    keys = [k for k in FEATURE_KEYS if any(feats[m].get(k) is not None for m in have)]
    X = np.array([[np.nan if feats[m].get(k) is None else float(feats[m][k]) for k in keys] for m in have])
    # z-score over the members (dimensions without spread carry no information)
    mu = np.nanmean(X, axis=0)
    sd = np.nanstd(X, axis=0)
    ok = sd > 1e-9
    Z = (X[:, ok] - mu[ok]) / sd[ok] if ok.any() else np.zeros((len(have), 0))
    n = len(have)
    if n == 1:
        return have[0], "구성원 1편", {have[0]: 0.0}
    mean_d = {}
    for i in range(n):
        ds = []
        for j in range(n):
            if i == j:
                continue
            diff = Z[i] - Z[j]
            diff = diff[~np.isnan(diff)]
            ds.append(float(math.sqrt(float((diff ** 2).mean()))) if diff.size else 0.0)
        mean_d[have[i]] = round(float(np.mean(ds)), 4)
    best = min(mean_d.values())
    tied = [m for m in have if abs(mean_d[m] - best) <= 1e-6]
    rep = max(tied, key=lambda m: (views.get(m, -1), m))
    reason = (f"구성원 {len(have)}편의 특징 벡터({', '.join(k for k, o in zip(keys, ok) if o)}; 표준화) 중 "
              f"다른 구성원까지 평균 거리가 가장 작음({best:.3f})")
    if len(tied) > 1:
        reason += f"; 동률 {len(tied)}편 중 조회수가 가장 높은 영상"
    missing = [m for m in members if m not in have]
    if missing:
        reason += f"; 분석 파일 없는 구성원 {len(missing)}편은 비교에서 제외"
    return rep, reason, mean_d


# ============================================================================= prepare
def prepare(preset: str, ids: list[str]) -> dict:
    snap = load_snapshot(preset) or {}
    by_id = {v["video_id"]: v for v in snap.get("videos") or []}
    done, skipped = [], []
    for vid in ids:
        d = analysis_dir(preset, vid)
        video = video_path(preset, vid)
        if video is None and not (d / "captions.json").is_file():
            skipped.append({"video_id": vid, "reason": "영상 파일도 분석 파일도 없음"})
            continue
        rdir = d / "review"
        rdir.mkdir(parents=True, exist_ok=True)
        sheet = None
        if video is not None:
            sheet = contact_sheet(video, rdir / "contact_sheet.jpg")
        md = timeline_markdown(preset, vid, by_id.get(vid), sheet is not None)
        (rdir / "timeline.md").write_text(md, encoding="utf-8")
        write_json(rdir / "packet.json", {"video_id": vid, "built_at": now_iso(),
                                          "features": video_features(preset, vid),
                                          "files": {"contact_sheet": paths.relp(sheet) if sheet else None,
                                                    "timeline": paths.relp(rdir / "timeline.md")},
                                          "note": "자동 분석 요약. 라벨은 영상을 실제로 보고 들은 사람만 채움."})
        done.append(vid)
    lp = labels_path(preset)
    rows = read_csv_rows(lp)
    have = {r.get("video_id") for r in rows}
    added = 0
    for vid in done:
        if vid not in have:
            rows.append({"video_id": vid, "intro_type": "", "structure_type": "", "notes": "", "labeled_by": "",
                         "watched": "no"})
            added += 1
    if added or not lp.exists():
        write_csv_rows(lp, LABEL_HEADER, rows)
    say(f"검토 자료 {len(done)}편 생성, 라벨 파일에 새 행 {added}개 추가({paths.relp(lp)}). "
        "라벨은 영상을 끝까지 보고 들은 사람이 intro_type·structure_type·labeled_by 를 채우고 watched=yes 로 표시합니다.")
    if skipped:
        warn("건너뜀: " + ", ".join(f"{s['video_id']}({s['reason']})" for s in skipped[:10]))
    return {"prepared": done, "skipped": skipped, "labels_added": added}


def contact_sheet(video: Path, out: Path, fps: float = 1.0, width: int = 180, cols: int = 6) -> Path:
    import cv2

    from ..util.media import iter_frames

    tiles = []
    for t, fr in iter_frames(video, fps=fps, width=width):
        img = cv2.cvtColor(fr, cv2.COLOR_RGB2BGR).copy()
        cv2.rectangle(img, (0, 0), (70, 22), (0, 0, 0), -1)
        cv2.putText(img, f"{t:5.1f}s", (3, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1, cv2.LINE_AA)
        tiles.append(img)
    if not tiles:
        raise RuntimeError("no frames")
    h, w = tiles[0].shape[:2]
    rows = int(math.ceil(len(tiles) / cols))
    sheet = np.zeros((rows * h, cols * w, 3), np.uint8)
    for i, tl in enumerate(tiles):
        r, c = divmod(i, cols)
        sheet[r * h:r * h + tl.shape[0], c * w:c * w + tl.shape[1]] = tl[:h, :w]
    out.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(out), sheet, [cv2.IMWRITE_JPEG_QUALITY, 80])
    return out


def timeline_markdown(preset: str, vid: str, snap_rec: dict | None, has_sheet: bool) -> str:
    d = analysis_dir(preset, vid)
    shots = read_json(d / "shots.json") or {}
    caps = read_json(d / "captions.json") or {}
    mot = read_json(d / "motion.json") or {}
    L = [f"# 검토 자료: {vid}", ""]
    if snap_rec:
        L += [f"- 제목: {snap_rec.get('title')}", f"- 주소: {snap_rec.get('url')}",
              f"- 게시: {snap_rec.get('published_at') or snap_rec.get('upload_date')}",
              f"- 길이: {snap_rec.get('duration')} 초", f"- 조회수: {snap_rec.get('view_count')} "
              f"(확인 {snap_rec.get('view_count_checked_at')})"]
    L += ["", "> 자동 분석 결과의 요약입니다. `format_labels.csv` 의 라벨(도입 방식·전개 구조)은 **영상을 실제로 보고 "
          "들은 사람만** 채우고 `watched=yes` 로 표시합니다. 이 문서만 보고 라벨을 채우지 마세요.", ""]
    if has_sheet:
        L += ["## 1초 간격 밀착 인화", "", "![contact sheet](contact_sheet.jpg)", ""]
    L += ["## 컷 목록", ""]
    if shots:
        L += ["| 시각(초) | 종류 | 점수 | 길이 |", "|---:|---|---:|---:|"]
        for c in shots.get("cuts") or []:
            L.append(f"| {c['t']:.2f} | {c['type']} | {c.get('score')} | {c.get('dur', '')} |")
        if not shots.get("cuts"):
            L.append("| - | 검출 없음 | | |")
    else:
        L.append("shots.json 없음(못 잼)")
    L += ["", "## 자막 타임라인", ""]
    if caps:
        L += ["| 시작 | 끝 | 역할 | 등장 | 텍스트(OCR) |", "|---:|---:|---|---|---|"]
        for c in caps.get("items") or []:
            txt = (c.get("text") or "").replace("\n", " / ").replace("|", "\\|")
            L.append(f"| {c['start']:.2f} | {c['end']:.2f} | {ROLE_KO.get(c['role'], c['role'])} | "
                     f"{c.get('motion_in')} | {txt} |")
    else:
        L.append("captions.json 없음(못 잼)")
    L += ["", "## 화면 모션", ""]
    if mot:
        for e in mot.get("events") or []:
            L.append(f"- {e['t']:.2f}–{e.get('end', e['t']):.2f}s {e['type']} 값={e.get('value')}")
        if not mot.get("events"):
            L.append("- 검출 없음")
        L.append(f"- 존재 요약: {mot.get('presence')}")
    else:
        L.append("motion.json 없음(못 잼)")
    L += ["", "## 오디오 사건", ""]
    adir = d / "audio"
    found = False
    for name in ("bgm.json", "original.json", "sfx_events.json"):
        a = read_json(adir / name)
        if a:
            found = True
            L.append(f"### {name}")
            for e in (a.get("events") or [])[:80]:
                L.append(f"- {float(e.get('t', 0)):.2f}s {e.get('class') or ''} {e.get('type_id') or ''} "
                         f"dur={e.get('dur')}")
    if not found:
        L.append("오디오 분석 파일 없음(못 잼)")
    return "\n".join(L) + "\n"


# ============================================================================= build
def build(preset: str) -> dict:
    pr = load_preset(preset)
    fpath = paths.absp(pr.get("structure.formats_file"))
    old = read_yaml(fpath, {}) or {}
    snap = load_snapshot(preset) or {}
    lp = labels_path(preset)
    rows = read_csv_rows(lp)
    valid, rejected = [], []
    for r in rows:
        vid = (r.get("video_id") or "").strip()
        st = (r.get("structure_type") or "").strip()
        watched = (r.get("watched") or "").strip().lower() == "yes"
        by = (r.get("labeled_by") or "").strip()
        if not vid:
            continue
        if st and watched and by:
            valid.append({"video_id": vid, "structure_type": st, "intro_type": (r.get("intro_type") or "").strip(),
                          "notes": (r.get("notes") or "").strip(), "labeled_by": by})
        elif st or (r.get("intro_type") or "").strip():
            rejected.append({"video_id": vid, "reason": "watched=yes 와 labeled_by 가 모두 있어야 함"})
    snap_ids, _ = snapshot_members(preset)
    mset = set(snap_ids)
    outside = [v for v in valid if v["video_id"] not in mset]
    valid = [v for v in valid if v["video_id"] in mset]
    basis = {"snapshot_file": paths.relp(paths.preset_dir(preset) / "reference" / "latest100.json"),
             "captured_at": snap.get("captured_at"), "snapshot_status": snap.get("status"),
             "n_videos": len(snap_ids), "labeled": len(valid), "labels_file": paths.relp(lp),
             "rejected_labels": len(rejected), "outside_snapshot_labels": len(outside),
             "missing_members": [m.get("video_id") for m in snap.get("missing_members") or [] if isinstance(m, dict)],
             "rule": "포맷 표·비율·대표 영상은 고정된 최신 100편 스냅샷 구성원의 라벨만으로 만든다(그 밖의 라벨은 참고로만 보관)"}
    outside_rows = [{"video_id": v["video_id"], "structure_type": v["structure_type"], "intro_type": v["intro_type"],
                     "labeled_by": v["labeled_by"], "reason": "최신 100편 스냅샷 밖 영상 — 포맷 표에 넣지 않음(참고용)"}
                    for v in outside]
    if not valid:
        why = ("본 사람이 채운 라벨 없음(format_labels.csv: watched=yes·structure_type·labeled_by)"
               if rows else "라벨 파일 없음 — `shortkit ref classify prepare` 후 영상을 본 사람이 채워야 함")
        if outside and snap_ids:
            why = f"스냅샷 구성원의 라벨 없음(스냅샷 밖 영상 라벨 {len(outside)}개는 포맷 표에 쓰지 않음)"
        elif not snap_ids:
            why = "고정된 최신 100편 스냅샷이 없어 포맷 표를 만들 수 없음(포맷은 스냅샷 구성원으로만)"
        base = old.get("blocker") if (old.get("status") == "unmeasured" and old.get("blocker")) else \
            snapshot_blocker(preset)
        out = {"schema": FORMATS_SCHEMA, "preset_id": pr.preset_id, "status": "unmeasured",
               "blocker": base if why in base else f"{base}; {why}",
               "basis": basis, "rule": FORMAT_RULE, "table": [], "assignments": {},
               "outside_snapshot_labels": outside_rows, "built_at": now_iso()}
        write_yaml(fpath, out)
        say("포맷 표: 라벨이 없어 '못 잼(unmeasured)' 상태로 유지했습니다.")
        return out
    old_ids = {row.get("structure_type"): row.get("format_id") for row in old.get("table") or []
               if row.get("structure_type") and row.get("format_id")}
    groups: dict[str, list[dict]] = {}
    for v in valid:
        groups.setdefault(v["structure_type"], []).append(v)
    order = sorted(groups, key=lambda s: (-len(groups[s]), s))
    used = set(old_ids.values())
    nxt = 1
    feats = {v["video_id"]: video_features(preset, v["video_id"]) for v in valid}
    views = views_of(preset)
    table, assignments = [], {}
    total = len(valid)
    for st in order:
        fid = old_ids.get(st)
        if not fid:
            while f"F{nxt}" in used:
                nxt += 1
            fid = f"F{nxt}"
            used.add(fid)
        mem = sorted(v["video_id"] for v in groups[st])
        intro: dict[str, list[str]] = {}
        for v in groups[st]:
            intro.setdefault(v["intro_type"] or "미기재", []).append(v["video_id"])
        rep, reason, dists = medoid(mem, feats, views)
        table.append({"format_id": fid, "structure_type": st, "n": len(mem), "share": round(len(mem) / total, 4),
                      "members": mem, "videos": mem,
                      "intro_variants": [{"intro_type": k, "n": len(vs), "members": sorted(vs)}
                                         for k, vs in sorted(intro.items(), key=lambda kv: (-len(kv[1]), kv[0]))],
                      "representative": {"video_id": rep, "reason": reason, "view_count": views.get(rep) if rep else None,
                                         "mean_distance": dists.get(rep) if rep else None},
                      "labeled_by": sorted({v["labeled_by"] for v in groups[st]})})
        for m in mem:
            assignments[m] = fid
    unlabeled = [v for v in snap_ids if v not in assignments]
    no_rep = [row["format_id"] for row in table if not (row.get("representative") or {}).get("video_id")]
    status = "measured" if snap_ids and not unlabeled and not no_rep else "partial"
    why = []
    if unlabeled:
        why.append(f"최신 스냅샷 {len(snap_ids)}편 중 라벨 없는 영상 {len(unlabeled)}편")
    if no_rep:
        why.append(f"대표 영상을 정하지 못한 포맷 {', '.join(no_rep)}(구성원 분석 파일 없음 — 못 잼)")
    out = {"schema": FORMATS_SCHEMA, "preset_id": pr.preset_id, "status": status,
           "blocker": None if status == "measured" else "; ".join(why),
           "basis": basis, "rule": FORMAT_RULE, "table": table, "assignments": assignments,
           "unlabeled": unlabeled[:200], "rejected_labels": rejected, "outside_snapshot_labels": outside_rows,
           "formats_without_representative": no_rep, "built_at": now_iso()}
    write_yaml(fpath, out)
    say(f"포맷 표: {len(table)}개 포맷, 라벨 {total}편(스냅샷 밖 라벨 {len(outside)}개 제외), 상태 {status} → "
        f"{paths.relp(fpath)}" + (f" — {out['blocker']}" if out["blocker"] else ""))
    return out


def load_membership(preset: str) -> dict[str, str]:
    """video_id -> format_id from formats.yaml (assignments, else table members)."""
    try:
        pr = load_preset(preset)
        fy = read_yaml(paths.absp(pr.get("structure.formats_file")), {}) or {}
    except Exception:
        return {}
    out = {str(k): str(v) for k, v in (fy.get("assignments") or {}).items()}
    for row in fy.get("table") or []:
        for m in row.get("members") or row.get("videos") or []:
            out.setdefault(str(m), str(row.get("format_id")))
    return out


_ = ROLES
