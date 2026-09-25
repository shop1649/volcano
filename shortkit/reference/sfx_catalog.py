"""SFX catalog over the newest N reference videos (default: preset reference.sfx_catalog_latest_n = 50).

Input per video: ``analysis/<id>/audio/sfx_events.json`` (+ fingerprints), and when available the
visual analysis files ``shots.json`` / ``motion.json`` / ``captions.json`` of the same video.

1. Cluster all SFX-event fingerprints (agglomerative, average linkage, cosine distance on log-mel
   patches with +-3 frame shift tolerance; threshold SIM_THRESHOLD).
2. Class: ``edit_sfx`` when the SAME waveform (normalised cross-correlation >= EDIT_XCORR) recurs
   in >= 2 videos; otherwise ``onsite_sound`` (unique / tied to one source).  Intentional silences
   (mix below floor >= 0.3 s mid-video with BGM cut) form the ``intentional_silence`` type.
3. Per type: per-video count pstats (overall + by format), previous caption role, nearest screen
   event within +-audio.sfx.max_event_offset_s (cut/flash/zoom_in/freeze/text_pop ...), emotion
   (ONLY from ``presets/<name>/sfx_emotion_labels.csv`` filled by someone who watched; otherwise
   unmeasured), placement rule text derived from those stats, offset to the event, gain relative to
   the mix, 3 examples from distinct videos.

Labels are acoustic descriptions computed from the fingerprints ("짧은 고역 타격음 ..."), never a
listening judgement.  With no analysed video the catalog stays ``unmeasured`` with the blocker.
"""
from __future__ import annotations

import csv
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from .. import paths
from ..config import load_preset
from ..util.jsonio import now_iso, read_json, read_yaml, write_json
from ..util.stats import categorical, pstats_by_group
from .separation import DEFAULT_PRESET, analysis_dir
from .sfx_events import SR, similarity_matrix, sfx_events_path, wave_xcorr

SCHEMA = "shortkit.sfx_catalog/1"
SIM_THRESHOLD = 0.80          # fingerprint similarity for the same cluster (distance 0.20)
EDIT_XCORR = 0.70             # same waveform across videos
XCORR_SNIPPET_S = 0.4
XCORR_NEIGHBOURS = 8
EMOTION_MATCH_S = 0.2
CUT_KINDS = ("cut", "crossfade")


# ============================================================================ inputs
def _snapshot_items(pr) -> tuple[list[dict], str | None]:
    snap_rel = pr.get("reference.snapshot_file")
    snap = read_json(paths.absp(snap_rel))
    if snap is None:
        return [], f"스냅샷 없음({snap_rel})"
    if isinstance(snap, dict):
        items = snap.get("videos") or snap.get("items") or []
        if not items:
            return [], (f"스냅샷({snap_rel}) 영상 0편, status={snap.get('status')}: "
                        f"{str(snap.get('blocker') or '')[:200]}")
    else:
        items = snap
    return [x for x in items if isinstance(x, dict) and x.get("video_id")], None


def newest_video_ids(preset_name: str, n: int | None = None) -> tuple[list[str], int, str | None]:
    """Newest ``n`` shorts of the snapshot (published_at/upload_date desc, else rank)."""
    pr = load_preset(preset_name)
    n = int(n if n is not None else pr.get("reference.sfx_catalog_latest_n"))
    items, blocker = _snapshot_items(pr)
    if not items:
        return [], n, blocker or "스냅샷에 영상 없음"
    if any(x.get("kind") for x in items):
        items = [x for x in items if (x.get("kind") or "short") == "short"]

    def key(x):
        d = str(x.get("published_at") or x.get("upload_date") or "")
        return (d, -float(x.get("rank") or 0))

    if any(x.get("published_at") or x.get("upload_date") for x in items):
        items = sorted(items, key=key, reverse=True)
    else:
        items = sorted(items, key=lambda x: float(x.get("rank") or 1e9))
    return [str(x["video_id"]) for x in items[:n]], n, None


def video_formats(preset_name: str) -> dict[str, str]:
    """video_id -> format_id from formats.yaml (``assignments`` map or ``table[].videos``) or the snapshot."""
    pr = load_preset(preset_name)
    out: dict[str, str] = {}
    fy = read_yaml(paths.absp(pr.get("structure.formats_file")), {}) or {}
    for vid, fmt in (fy.get("assignments") or {}).items():
        out[str(vid)] = str(fmt)
    for row in fy.get("table") or []:
        fid = row.get("format_id") or row.get("id")
        for vid in row.get("videos") or []:
            out.setdefault(str(vid), str(fid))
    items, _ = _snapshot_items(pr)
    for x in items:
        if x.get("format_id"):
            out.setdefault(str(x["video_id"]), str(x["format_id"]))
    return out


def _read_analysis(preset_name: str, vid: str, name: str) -> dict | None:
    d = read_json(analysis_dir(preset_name, vid) / name)
    if not d or d.get("status") == "unmeasured":
        return None
    return d


def screen_events(preset_name: str, vid: str) -> dict:
    """Screen events of one video from the visual analysis files (None status if none exist)."""
    evs: list[tuple[float, str]] = []
    sources = []
    shots = _read_analysis(preset_name, vid, "shots.json")
    if shots is not None:
        sources.append("shots")
        for c in shots.get("cuts") or []:
            evs.append((float(c["t"]), str(c.get("type") or "cut")))
    motion = _read_analysis(preset_name, vid, "motion.json")
    if motion is not None:
        sources.append("motion")
        for m in motion.get("events") or []:
            evs.append((float(m["t"]), str(m.get("type") or "motion")))
    caps = _read_analysis(preset_name, vid, "captions.json")
    if caps is not None:
        sources.append("captions")
        for c in caps.get("items") or []:
            mi = c.get("motion_in")
            kind = "text_pop" if mi == "pop" else (f"text_{mi}" if mi and mi not in ("none", "unmeasured") else "text_on")
            evs.append((float(c["start"]), kind))
    return {"status": "measured" if sources else "unmeasured", "sources": sources, "events": sorted(evs),
            "captions": (caps or {}).get("items") if caps is not None else None}


def nearest_screen_event(se: dict, t: float, window: float) -> tuple[str | None, float | None]:
    """(kind, event_t) of the nearest screen event within +-window; ("none", None) if nothing;
    (None, None) when the video's screen events were not measured."""
    if se["status"] != "measured":
        return None, None
    near = sorted((abs(et - t), kind, et) for et, kind in se["events"] if abs(et - t) <= window)
    if not near:
        return "none", None
    # a bare cut is never the reason for an SFX (user rule): when a non-cut screen event is (almost)
    # as close, it is the event this sound belongs to
    non_cut = [z for z in near if z[1] not in CUT_KINDS]
    best = non_cut[0] if non_cut and non_cut[0][0] <= near[0][0] + 0.1 else near[0]
    return best[1], best[2]


def prev_caption_role(captions: list[dict] | None, t: float) -> str | None:
    if captions is None:
        return None
    prev = [c for c in captions if float(c["start"]) <= t + 0.05]
    if not prev:
        return "none"
    return str(max(prev, key=lambda c: float(c["start"])).get("role") or "unknown")


def emotion_labels(preset_name: str) -> tuple[list[dict] | None, str]:
    """Rows of sfx_emotion_labels.csv that name who labelled them (someone who watched)."""
    p = paths.absp(f"presets/{preset_name}/sfx_emotion_labels.csv")
    rel = f"presets/{preset_name}/sfx_emotion_labels.csv"
    if not p.is_file():
        return None, f"감정 라벨 파일 없음({rel}) — 영상을 실제로 본 사람이 채워야 함"
    rows = []
    with p.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if (r.get("emotion") or "").strip() and (r.get("labeled_by") or "").strip() and r.get("video_id"):
                try:
                    rows.append({"video_id": r["video_id"].strip(), "t": float(r["t"]),
                                 "emotion": r["emotion"].strip(), "labeled_by": r["labeled_by"].strip()})
                except (TypeError, ValueError):
                    continue
    if not rows:
        return None, f"{rel} 에 labeled_by 가 있는 감정 라벨 없음"
    return rows, rel


# ============================================================================ clustering
def cluster_fingerprints(patches: list[np.ndarray], threshold: float = SIM_THRESHOLD) -> np.ndarray:
    """Agglomerative clustering (average linkage) on 1 - similarity; returns labels 0..k-1."""
    n = len(patches)
    if n == 0:
        return np.zeros(0, int)
    if n == 1:
        return np.zeros(1, int)
    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import squareform

    S = similarity_matrix(patches)
    S = np.maximum(S, S.T)
    D = np.clip(1.0 - S, 0.0, 2.0)
    np.fill_diagonal(D, 0.0)
    Z = linkage(squareform(D, checks=False), method="average")
    lab = fcluster(Z, t=1.0 - threshold, criterion="distance")
    _, lab = np.unique(lab, return_inverse=True)
    return lab


def _components(n: int, edges: list[tuple[int, int]]) -> list[list[int]]:
    parent = list(range(n))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a, b in edges:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)
    return list(groups.values())


def split_edit_vs_onsite(members: list[dict], sim: np.ndarray) -> tuple[list[list[int]], list[int], list[dict]]:
    """Inside one spectral cluster: groups of events whose waveforms match across >= 2 videos
    (edit SFX), and the rest (onsite).  Returns (edit_groups, onsite_indices, pair_log)."""
    n = len(members)
    edges, log = [], []
    done: set[tuple[int, int]] = set()
    snip = int(XCORR_SNIPPET_S * SR)
    for i in range(n):
        others = [j for j in range(n) if members[j]["video_id"] != members[i]["video_id"]]
        others.sort(key=lambda j: -sim[i, j])
        for j in others[:XCORR_NEIGHBOURS]:
            if (min(i, j), max(i, j)) in done:
                continue
            done.add((min(i, j), max(i, j)))
            x = wave_xcorr(members[i]["wave_arr"][:snip], members[j]["wave_arr"][:snip])
            if x >= EDIT_XCORR:
                edges.append((i, j))
            if len(log) < 50:
                log.append({"a": [members[i]["video_id"], members[i]["t"]], "b": [members[j]["video_id"],
                                                                               members[j]["t"]],
                            "xcorr": round(x, 3)})
    edit_groups, onsite = [], []
    for comp in _components(n, edges):
        vids = {members[k]["video_id"] for k in comp}
        if len(comp) >= 2 and len(vids) >= 2:
            edit_groups.append(comp)
        else:
            onsite.extend(comp)
    return edit_groups, onsite, log


# ============================================================================ descriptors / stats
def acoustic_label(stats: list[dict], cls: str) -> str:
    def med(k):
        v = [s.get(k) for s in stats if s.get(k) is not None]
        return float(np.median(v)) if v else None

    dur, cen, flat, att = med("dur_s"), med("centroid_hz"), med("flatness"), med("attack_s")
    parts = []
    if dur is not None:
        parts.append("짧은" if dur < 0.15 else ("긴" if dur > 0.6 else "중간 길이"))
    if cen is not None:
        parts.append("저역" if cen < 500 else ("고역" if cen > 2000 else "중역"))
    if flat is not None:
        parts.append("음정 있는" if flat < 0.1 else ("잡음성" if flat > 0.3 else ""))
    if att is not None:
        parts.append("타격음" if att < 0.03 else "서서히 커지는 소리")
    head = " ".join(p for p in parts if p)
    tail = []
    if dur is not None:
        tail.append(f"{dur:.2f} s")
    if cen is not None:
        tail.append(f"중심 {cen:.0f} Hz")
    base = f"{head} ({', '.join(tail)})" if tail else head
    return ("현장음: " if cls == "onsite_sound" else "") + base


def _cat(values: list) -> dict:
    c = categorical(values)
    c["status"] = "measured" if c["n"] else "unmeasured"
    return c


def placement_rule(t: dict) -> str:
    cls = t["class"]
    pv = t["per_video_count"]["overall"]
    count_txt = (f"영상당 p50 {pv['p50']:g}회 (p10 {pv['p10']:g} ~ p90 {pv['p90']:g}, n={pv['n']})"
                 if pv["n"] else "영상당 횟수 못 잼")
    if cls == "onsite_sound":
        return (f"원본 현장음 — 효과음 창고에서 새로 배치하지 않음(원음을 살릴 때만 들림). {count_txt}")
    se = t["screen_event"]
    if se["n"]:
        mode = se["mode"]
        share = se["share"].get(mode, 0) * 100
        off = t["offset_to_event_s"]
        off_txt = f", 이벤트 대비 {off['p50']:+.2f} s (p10 {off['p10']:+.2f} ~ p90 {off['p90']:+.2f})" if off["n"] else ""
        se_txt = (f"화면 이벤트 '{mode}' 에 맞춤({share:.0f} %{off_txt})" if mode != "none"
                  else f"±{t['event_window_s']} s 안에 화면 이벤트 없음이 가장 많음({share:.0f} %) — 이벤트 근거 확인 필요")
        if mode in CUT_KINDS:
            se_txt += (" — 제작 규칙: 컷만으로는 효과음을 넣지 않음, 같은 순간의 화면 이벤트(줌·플래시·자막 등장·"
                       "동작)가 있을 때만 배치")
    else:
        se_txt = "화면 이벤트 못 잼(시각 분석 없음) → 배치 근거 미확정"
    pc = t["prev_caption_role"]
    pc_txt = (f"직전 자막 역할 '{pc['mode']}' ({pc['share'].get(pc['mode'], 0) * 100:.0f} %)" if pc["n"]
              else "직전 자막 역할 못 잼")
    em = t["emotion"]
    em_txt = f"감정 '{em['mode']}'" if em["n"] else "감정 못 잼(시청 라벨 없음)"
    if cls == "intentional_silence":
        d = t.get("duration_s") or {}
        dtxt = f"{d.get('p50'):.2f} s" if d.get("n") else "길이 못 잼"
        return f"BGM 을 끊고 {dtxt} 정적. {count_txt}; {se_txt}; {pc_txt}; {em_txt}"
    return f"{count_txt}; {se_txt}; {pc_txt}; {em_txt}"


# ============================================================================ build
def catalog_path(preset_name: str) -> Path:
    pr = load_preset(preset_name)
    return paths.absp(pr.get("audio.sfx.catalog"))


def build_catalog(preset_name: str = DEFAULT_PRESET, video_ids: list[str] | None = None,
                  latest_n: int | None = None, write: bool = True) -> dict:
    pr = load_preset(preset_name)
    window = float(pr.get("audio.sfx.max_event_offset_s"))
    excluded: list[str] = []
    if video_ids is None:
        video_ids, target_n, snap_blocker = newest_video_ids(preset_name, latest_n)
        basis_note = f"스냅샷 최신 {target_n}편"
    else:
        # an explicit list is still restricted to snapshot members (production basis); others are recorded
        from .common import production_basis

        pb = production_basis(preset_name, list(video_ids))
        excluded = pb["excluded_non_snapshot"] + pb["excluded_long_form"]
        video_ids = pb["ids"]
        target_n, snap_blocker = len(video_ids), (pb["blocker"] if not video_ids else None)
        basis_note = "지정한 영상 목록(스냅샷 구성원만)"
    out: dict = {"schema": SCHEMA, "preset_id": pr.preset_id, "generated_at": now_iso(),
                 "params": {"sim_threshold": SIM_THRESHOLD, "edit_xcorr": EDIT_XCORR, "event_window_s": window,
                            "clustering": "agglomerative average-linkage, 1 - fingerprint similarity"}}
    analyzed, missing, per_video = [], [], {}
    for vid in video_ids:
        d = read_json(sfx_events_path(preset_name, vid))
        if d and d.get("status") in ("measured", "partial"):     # partial = speech intervals not measured
            analyzed.append(vid)
            per_video[vid] = d
        else:
            missing.append(vid)
    fmts = video_formats(preset_name)
    seps = sorted({str((d.get("separator") or {}).get("model") or "none") for d in per_video.values()})
    partial = sorted(v for v, d in per_video.items() if d.get("unmeasured_coverage"))
    out["basis"] = {"videos": analyzed, "n_videos": len(analyzed), "target_n": target_n, "selection": basis_note,
                    "missing": missing, "separator": ", ".join(seps) if seps else None,
                    "videos_with_unmeasured_intervals": partial, "excluded_non_snapshot": excluded}
    if not analyzed:
        out.update({"status": "unmeasured", "types": [],
                    "blocker": snap_blocker or "분석된 레퍼런스 영상 없음(sfx_events.json 전무)"})
        if write:
            write_json(catalog_path(preset_name), out)
        return out
    # ------------------------------------------------------------ gather events
    events = []
    for vid in analyzed:
        for e in per_video[vid].get("events") or []:
            if e.get("class") == "intentional_silence":
                events.append({**e, "video_id": vid, "kind": "silence"})
                continue
            if not e.get("fp"):
                continue
            fp = paths.absp(e["fp"])
            wv = paths.absp(e["wave"]) if e.get("wave") else None
            if not fp.is_file():
                continue
            events.append({**e, "video_id": vid, "kind": "sfx", "patch": np.load(fp).astype(np.float32),
                           "wave_arr": (np.load(wv).astype(np.float32) if wv and wv.is_file()
                                        else np.zeros(0, np.float32))})
    sfx = [e for e in events if e["kind"] == "sfx"]
    sil = [e for e in events if e["kind"] == "silence"]
    types: list[dict] = []
    assign: dict[tuple[str, str], tuple[str, str]] = {}
    # ------------------------------------------------------------ cluster + classify
    groups: list[tuple[str, list[dict]]] = []
    pair_logs = []
    if sfx:
        lab = cluster_fingerprints([e["patch"] for e in sfx])
        S_all = similarity_matrix([e["patch"] for e in sfx])
        onsite_left: list[list[dict]] = []
        for c in range(int(lab.max()) + 1):
            idx = np.nonzero(lab == c)[0]
            mem = [sfx[i] for i in idx]
            sim = S_all[np.ix_(idx, idx)]
            eg, ons, log = split_edit_vs_onsite(mem, sim)
            pair_logs.extend(log[:10])
            for g in eg:
                groups.append(("edit_sfx", [mem[k] for k in g]))
            if ons:
                onsite_left.append([mem[k] for k in ons])
        singles = []
        for grp in onsite_left:
            if len(grp) >= 2:
                groups.append(("onsite_sound", grp))
            else:
                singles.extend(grp)
        if singles:
            groups.append(("onsite_misc", singles))
    groups.sort(key=lambda g: ({"edit_sfx": 0, "onsite_sound": 1}.get(g[0], 2), -len({e["video_id"] for e in g[1]}),
                               -len(g[1])))
    labels_rows, emo_src = emotion_labels(preset_name)
    se_cache = {vid: screen_events(preset_name, vid) for vid in analyzed}
    fp_dir = paths.absp(f"presets/{preset_name}/sfx_fp")
    ids = stable_type_ids(preset_name, groups)
    for (cls, mem), tid in zip(groups, ids):
        if cls == "onsite_misc":
            cls = "onsite_sound"
        t = _type_stats(tid, cls, mem, analyzed, fmts, se_cache, window, labels_rows, emo_src)
        if partial:
            t["per_video_count"]["lower_bound_videos"] = partial
            t["per_video_count"]["note"] = "대사 구간 효과음 못 잼인 영상 포함 — 그 영상의 횟수는 하한값"
        if tid == "onsite_misc":
            t["label"] = "현장음: 1회성 소리 모음(서로 다른 소리) — " + t["label"].replace("현장음: ", "")
        if write:
            fp_dir.mkdir(parents=True, exist_ok=True)
            cen = np.mean([m["patch"] for m in mem], axis=0).astype(np.float32)
            np.save(fp_dir / f"{tid}.npy", cen)
            med = _medoid(mem)
            np.save(fp_dir / f"{tid}_wave.npy", med["wave_arr"].astype(np.float32))
            t["fingerprint"] = {"method": "log-mel 64 patch 평균(onset-0.02..+0.5 s, dB re max) + medoid 파형",
                                "centroid": paths.relp(fp_dir / f"{tid}.npy"),
                                "medoid_wave": paths.relp(fp_dir / f"{tid}_wave.npy"),
                                "medoid_example": {"video_id": med["video_id"], "t": med["t"]}}
        types.append(t)
        for m in mem:
            assign[(m["video_id"], m["id"])] = (tid, cls)
    if sil:
        t = _type_stats("silence_cut", "intentional_silence", sil, analyzed, fmts, se_cache, window, labels_rows,
                        emo_src)
        t["fingerprint"] = {"method": "믹스 레벨 바닥 이하 >= 0.3 s + BGM 끊김(지문 없음)", "centroid": None}
        types.append(t)
        for m in sil:
            assign[(m["video_id"], m["id"])] = ("silence_cut", "intentional_silence")
    if write and fp_dir.is_dir():                 # drop centroid files of types that no longer exist
        keep = {t["type_id"] for t in types}
        for f in fp_dir.glob("*.npy"):
            if f.stem.removesuffix("_wave") not in keep:
                f.unlink()
    # the catalog is 'measured' only when every target video was analysed AND no analysed video has intervals
    # where SFX could not be measured (no Demucs vocals stem -> SFX under speech unmeasured, counts are lower
    # bounds); the production gate (episode validate) treats anything else as unmeasured
    blockers = []
    if missing:
        blockers.append(f"부분 분석 {len(analyzed)}/{target_n}편 — 누락: {', '.join(missing[:10])}"
                        + ("…" if len(missing) > 10 else ""))
    if partial:
        blockers.append(f"Demucs 분리 없음: 대사 밑 효과음 못 잼({len(partial)}편: {', '.join(partial[:10])}"
                        + ("…" if len(partial) > 10 else "") + ") — 종류별 편당 개수는 하한값")
    out.update({"status": "unmeasured" if blockers else "measured", "blocker": "; ".join(blockers) or None,
                "counts_are_lower_bounds": bool(partial),
                "types": types, "xcorr_samples": pair_logs[:30]})
    if write:
        write_json(catalog_path(preset_name), out)
        for vid in analyzed:                      # write type ids back to the per-video event files
            d = per_video[vid]
            for e in d.get("events") or []:
                if (vid, e.get("id")) in assign:
                    e["type_id"], e["class"] = assign[(vid, e["id"])]
            d["catalog"] = {"file": paths.relp(catalog_path(preset_name)), "assigned_at": now_iso()}
            write_json(sfx_events_path(preset_name, vid), d)
    return out


def _pst(rows: list[dict]) -> dict:
    """{n, p10, p50, p90} overall plus ``by_format`` (same shape per format)."""
    g = pstats_by_group(rows, "v")
    return {**g["overall"], "by_format": g["by_format"]}


def stable_type_ids(preset_name: str, groups: list[tuple[str, list[dict]]]) -> list[str]:
    """Type ids for the new groups, reusing the previous catalog's id when a group's centroid matches a
    previous type of the same class (similarity >= SIM_THRESHOLD), so episode plans that reference a
    type id stay valid when the catalog is rebuilt with more videos."""
    prev = read_json(catalog_path(preset_name)) or {}
    prev_ids, prev_cls, prev_cen = [], [], []
    for t in prev.get("types") or []:
        c = (t.get("fingerprint") or {}).get("centroid")
        if t.get("type_id") in ("onsite_misc", "silence_cut") or not c or not paths.absp(c).is_file():
            continue
        prev_ids.append(t["type_id"])
        prev_cls.append(t.get("class"))
        prev_cen.append(np.load(paths.absp(c)).astype(np.float32))
    new_cen = [np.mean([m["patch"] for m in mem], axis=0) for _, mem in groups]
    out: list[str | None] = [None] * len(groups)
    for i, (cls, _) in enumerate(groups):
        if cls == "onsite_misc":
            out[i] = "onsite_misc"
    if prev_cen:
        S = similarity_matrix(new_cen, prev_cen)
        pairs = sorted(((S[i, j], i, j) for i in range(len(groups)) for j in range(len(prev_ids))
                        if out[i] is None and groups[i][0] == prev_cls[j] and S[i, j] >= SIM_THRESHOLD), reverse=True)
        used_i, used_j = set(), set()
        for _, i, j in pairs:
            if i in used_i or j in used_j:
                continue
            out[i] = prev_ids[j]
            used_i.add(i)
            used_j.add(j)
    taken = set(prev_ids) | {x for x in out if x}

    def nxt(prefix: str) -> str:
        k = 1
        while f"{prefix}_{k:02d}" in taken:
            k += 1
        taken.add(f"{prefix}_{k:02d}")
        return f"{prefix}_{k:02d}"

    for i, (cls, _) in enumerate(groups):
        if out[i] is None:
            out[i] = nxt("edit" if cls == "edit_sfx" else "onsite")
    return [str(x) for x in out]


def _medoid(mem: list[dict]) -> dict:
    if len(mem) <= 2:
        return mem[0]
    S = similarity_matrix([m["patch"] for m in mem])
    return mem[int(np.argmax(S.sum(1)))]


def _type_stats(tid: str, cls: str, mem: list[dict], analyzed: list[str], fmts: dict, se_cache: dict,
                window: float, labels_rows: list[dict] | None, emo_src: str) -> dict:
    counts = Counter(m["video_id"] for m in mem)
    rows = [{"video_id": v, "format_id": fmts.get(v), "count": counts.get(v, 0)} for v in analyzed]
    pvc = pstats_by_group(rows, "count")
    roles, kinds, offsets, emos = [], [], [], []
    for m in mem:
        se = se_cache[m["video_id"]]
        roles.append(prev_caption_role(se["captions"], m["t"]))
        kind, et = nearest_screen_event(se, m["t"], window)
        kinds.append(kind)
        if et is not None:
            offsets.append({"format_id": fmts.get(m["video_id"]), "v": round(m["t"] - et, 4)})
        if labels_rows is not None:
            cand = [r for r in labels_rows if r["video_id"] == m["video_id"] and abs(r["t"] - m["t"]) <= EMOTION_MATCH_S]
            emos.append(min(cand, key=lambda r: abs(r["t"] - m["t"]))["emotion"] if cand else None)
    emo = _cat(emos)
    if not emo["n"]:
        emo["blocker"] = emo_src if labels_rows is None else "라벨 파일에 이 종류의 이벤트와 맞는 행 없음"
    else:
        emo["source"] = emo_src
    se_cat = _cat(kinds)
    if not se_cat["n"]:
        se_cat["blocker"] = "시각 분석 파일(shots/motion/captions.json) 없음"
    pc = _cat(roles)
    if not pc["n"]:
        pc["blocker"] = "captions.json 없음"
    ex, seen = [], set()
    for m in sorted(mem, key=lambda m: (m["video_id"], m["t"])):
        if m["video_id"] not in seen:
            ex.append({"video_id": m["video_id"], "t": round(float(m["t"]), 3)})
            seen.add(m["video_id"])
        if len(ex) >= 3:
            break
    t = {"type_id": tid, "class": cls,
         "label": (acoustic_label([m.get("stats") or {} for m in mem], cls) if cls != "intentional_silence"
                   else "의도적 정적(BGM 끊김)"),
         "label_source": "acoustic_descriptor (청취 라벨 아님)" if cls != "intentional_silence" else "level_rule",
         "n_events": len(mem), "n_videos": len(counts),
         "per_video_count": pvc,
         "prev_caption_role": pc, "screen_event": se_cat, "emotion": emo,
         "event_window_s": window,
         "offset_to_event_s": _pst(offsets),
         "gain_db_rel_mix": _pst([{"format_id": fmts.get(m["video_id"]), "v": m.get("gain_db")} for m in mem]
                                 if cls != "intentional_silence" else []),
         "examples": ex, "examples_distinct_videos": len(ex)}
    if cls == "intentional_silence":
        t["duration_s"] = _pst([{"format_id": fmts.get(m["video_id"]), "v": m.get("dur")} for m in mem])
        t["level_dbfs"] = _pst([{"format_id": fmts.get(m["video_id"]), "v": m.get("gain_db")} for m in mem])
    else:
        t["duration_s"] = _pst([{"format_id": fmts.get(m["video_id"]), "v": (m.get("stats") or {}).get("dur_s")}
                                for m in mem])
    t["placement_rule"] = placement_rule(t)
    return t


def write_emotion_template(preset_name: str = DEFAULT_PRESET) -> Path:
    """CSV template (one row per catalogued event) for someone who WATCHES the videos to fill in.

    The template is a separate file; the catalog only reads ``sfx_emotion_labels.csv``."""
    cat = read_json(catalog_path(preset_name)) or {}
    out = paths.absp(f"presets/{preset_name}/sfx_emotion_labels.template.csv")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["video_id", "t", "type_id", "emotion", "labeled_by", "note"])
        for vid in (cat.get("basis") or {}).get("videos") or []:
            d = read_json(sfx_events_path(preset_name, vid)) or {}
            for e in d.get("events") or []:
                w.writerow([vid, f"{float(e['t']):.3f}", e.get("type_id") or "", "", "", ""])
    return out
