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

Information-disclosure order (user: "반전을 미리 설명하지 말고 레퍼런스의 정보 공개 순서를 따른다") is measured from
two more label columns filled by the same person who watched the video:

``beats``     the video's segment purposes in order, from the vocabulary of plan ``timeline[].purpose``
              (BEATS: hook, context, build, reveal, reaction, outro; Korean aliases in BEAT_ALIASES), joined by
              ``>`` (``→``, ``->``, ``,``, ``/`` also accepted); repeated neighbours collapse.
``reveal_t``  seconds from the video start at which the twist is first shown, or ``none`` when the video has no
              twist.  A numeric reveal_t needs a ``reveal`` beat and ``none`` forbids one.

Per format ``table[]`` gets (the fields ``episode validate`` reads -- shortkit/edit/validate.py check_reveal):
``beats`` (one ordered list, or None) and ``reveal_frac`` {n, p10, p50, p90} (reveal_t / video duration over the
members with a twist), plus ``reveal_t_s``, ``reveal_presence`` and ``disclosure`` {status, order, evidence,
missing, blocker}.  Nothing is inferred: the values are published only when EVERY member of the format has valid
disclosure labels (else ``partial``, the statistics of the labelled members kept under
``disclosure.partial_stats``), and ``beats`` only when the members' orders form one total order (``conflict``
when two members order a pair differently, ``partial_order`` when a pair never occurs together, even through
other beats).  The format table's own ``status`` stays the structure classification; ``disclosure_order`` at the
top level holds the disclosure status of the whole table.
"""
from __future__ import annotations

import csv
import math
import re
from pathlib import Path

import numpy as np

from .. import paths
from ..config import load_preset
from ..util.jsonio import now_iso, read_json, read_yaml, write_json, write_yaml
from ..util.stats import pstats
from .common import (ROLE_KO, ROLES, analysis_dir, load_snapshot, read_csv_rows, say, snapshot_blocker,
                     snapshot_members, video_path, views_of, warn, write_csv_rows)

LABEL_HEADER = ["video_id", "intro_type", "structure_type", "beats", "reveal_t", "notes", "labeled_by", "watched"]
# segment purposes: the vocabulary of plan timeline[].purpose (shortkit/schema/plan.schema.json)
BEATS = ("hook", "context", "build", "reveal", "reaction", "outro")
BEAT_ALIASES = {"훅": "hook", "후킹": "hook", "도입": "hook", "상황": "context", "배경": "context", "맥락": "context",
                "설명": "context", "전개": "build", "빌드업": "build", "고조": "build", "반전": "reveal", "공개": "reveal",
                "반응": "reaction", "리액션": "reaction", "마무리": "outro", "아웃트로": "outro", "끝": "outro"}
BEAT_SEP_RE = re.compile(r"\s*(?:>|→|->|,|/|\|)\s*")
NO_REVEAL = ("none", "no", "없음", "-")
LABEL_COLUMNS = {
    "video_id": "레퍼런스 영상 ID(최신 100편 스냅샷 구성원만 포맷 표에 쓰임)",
    "intro_type": "도입 방식(도입만 다른 영상은 같은 포맷의 intro_variants)",
    "structure_type": "전개 구조(전개 구조가 실제로 다를 때만 다른 포맷)",
    "beats": ("구간 목적 순서: " + " / ".join(BEATS) + " 중에서 '>' 로 이음(예: hook>build>reveal>reaction). "
              "한국어 별칭: " + ", ".join(f"{k}={v}" for k, v in BEAT_ALIASES.items())),
    "reveal_t": "반전이 처음 보이는 시각(영상 시작부터 초, 예: 17.5). 반전이 없는 영상은 none",
    "notes": "메모(선택)",
    "labeled_by": "영상을 끝까지 보고 들은 사람 이름(필수)",
    "watched": "yes = 실제로 보고 들음(그 외 값의 행은 쓰지 않음)"}
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


# ============================================================================= disclosure order
def parse_beats(text: str | None) -> tuple[list[str] | None, str | None]:
    """'hook > build > reveal' -> (["hook", "build", "reveal"], None); unknown purpose -> (None, reason)."""
    toks = [t for t in BEAT_SEP_RE.split((text or "").strip()) if t]
    out: list[str] = []
    for tok in toks:
        b = tok.strip().casefold()
        b = BEAT_ALIASES.get(b, b)
        if b not in BEATS:
            return None, f"알 수 없는 구간 목적 '{tok}' (허용: {', '.join(BEATS)} 또는 한국어 별칭)"
        if not out or out[-1] != b:
            out.append(b)
    return (out, None) if out else (None, None)


def parse_reveal_t(text: str | None) -> tuple[float | str | None, str | None]:
    """'17.5' -> (17.5, None); 'none'/'없음' -> ('none', None); '' -> (None, None); bad -> (None, reason)."""
    v = (text or "").strip()
    if not v:
        return None, None
    if v.casefold() in NO_REVEAL:
        return "none", None
    try:
        t = float(v)
    except ValueError:
        return None, f"reveal_t '{v}' 는 초(숫자) 또는 none 이어야 함"
    if not math.isfinite(t) or t < 0:
        return None, f"reveal_t '{v}' 는 0 이상의 초여야 함"
    return t, None


def video_duration(preset: str, vid: str, snap_rec: dict | None) -> tuple[float | None, str | None]:
    """Duration of the analysed file (shots/captions/motion.json), else the snapshot's listed duration."""
    d = analysis_dir(preset, vid)
    for name in ("shots.json", "captions.json", "motion.json"):
        x = read_json(d / name) or {}
        if x.get("duration"):
            return float(x["duration"]), "analysis"
    if snap_rec and snap_rec.get("duration"):
        return float(snap_rec["duration"]), "snapshot"
    return None, None


def disclosure_label(row: dict, duration: tuple[float | None, str | None]) -> tuple[dict | None, str | None]:
    """One watched label row -> ({beats, reveal_t, reveal_frac, duration, duration_source}, None), (None, reason)
    for an invalid label, or (None, None) when the disclosure columns were not filled in."""
    braw, rraw = (row.get("beats") or "").strip(), (row.get("reveal_t") or "").strip()
    if not braw and not rraw:
        return None, None
    beats, err = parse_beats(braw)
    if err:
        return None, err
    rt, err = parse_reveal_t(rraw)
    if err:
        return None, err
    if beats is None:
        return None, "beats(구간 목적 순서)가 비어 있음"
    if rt is None:
        return None, "reveal_t 가 비어 있음(반전이 없는 영상이면 none)"
    if rt == "none" and "reveal" in beats:
        return None, "reveal_t=none 인데 beats 에 reveal 이 있음"
    if rt != "none" and "reveal" not in beats:
        return None, f"reveal_t={rt} 인데 beats 에 reveal 이 없음"
    dur, src = duration
    frac = None
    if rt != "none":
        if dur is None:
            return None, "영상 길이를 몰라 반전 시각 비율을 계산할 수 없음(분석 파일·스냅샷 길이 없음)"
        if rt > dur + 1e-6:
            return None, f"reveal_t={rt} 가 영상 길이 {dur:g}s 보다 김"
        frac = rt / dur
    return {"beats": beats, "reveal_t": rt, "reveal_frac": frac, "duration": dur, "duration_source": src}, None


def beat_order(seqs: dict[str, list[str]]) -> dict:
    """One total order of the beats seen in the members' sequences, or why there is none.
    status measured (beats = the order) | conflict (a pair ordered both ways) | partial_order (a pair never
    ordered, even through other beats)."""
    before: dict[tuple[str, str], list[str]] = {}
    for vid, seq in seqs.items():
        for i, a in enumerate(seq):
            for b in seq[i + 1:]:
                if a != b:
                    before.setdefault((a, b), [])
                    if vid not in before[(a, b)]:
                        before[(a, b)].append(vid)
    nodes = sorted({b for seq in seqs.values() for b in seq}, key=BEATS.index)
    prec = [{"pair": [a, b], "n": len(v), "videos": sorted(v)} for (a, b), v in
            sorted(before.items(), key=lambda kv: (BEATS.index(kv[0][0]), BEATS.index(kv[0][1])))]
    res: dict = {"status": None, "beats": None, "nodes": nodes, "precedence": prec, "conflicts": [],
                 "unknown_pairs": []}
    conf = [(a, b) for (a, b) in before if (b, a) in before and BEATS.index(a) < BEATS.index(b)]
    reach = {a: {b for (x, b) in before if x == a} for a in nodes}
    for k in nodes:                                   # transitive closure (Floyd-Warshall on <= 6 nodes)
        for i in nodes:
            if k in reach[i]:
                reach[i] |= reach[k]
    cyc = [a for a in nodes if a in reach[a]]
    if conf or cyc:
        res["status"] = "conflict"
        res["conflicts"] = ([{"pair": [a, b], "a_before_b": sorted(before[(a, b)]), "b_before_a": sorted(before[(b, a)])}
                             for a, b in sorted(conf, key=lambda z: (BEATS.index(z[0]), BEATS.index(z[1])))]
                            or [{"cycle": cyc}])
        return res
    unknown = [[a, b] for i, a in enumerate(nodes) for b in nodes[i + 1:] if b not in reach[a] and a not in reach[b]]
    if unknown:
        res["status"], res["unknown_pairs"] = "partial_order", unknown
        return res
    res["status"] = "measured"
    res["beats"] = sorted(nodes, key=lambda x: -len(reach[x]))
    return res


def _presence(labs: list[dict]) -> dict:
    n = len(labs)
    nr = sum(1 for x in labs if x["reveal_t"] != "none")
    return {"n": n, "n_reveal": nr, "n_none": n - nr, "share": round(nr / n, 4) if n else None}


def format_disclosure(members: list[str], labels: dict[str, dict], invalid: dict[str, str]) -> dict:
    """Per-format disclosure fields for formats.yaml (see the module docstring)."""
    ok = {m: labels[m] for m in members if m in labels}
    missing = [m for m in members if m not in ok]
    labs = list(ok.values())
    fracs = [x["reveal_frac"] for x in labs if x["reveal_frac"] is not None]
    times = [x["reveal_t"] for x in labs if x["reveal_t"] != "none"]
    order = beat_order({m: x["beats"] for m, x in ok.items()}) if ok else {"status": None, "beats": None}
    stats = {"reveal_frac": pstats(fracs, digits=6), "reveal_t_s": pstats(times, digits=3),
             "reveal_presence": _presence(labs), "beats": order.get("beats")}
    ev = [{"video_id": m, "beats": x["beats"], "reveal_t": x["reveal_t"],
           "reveal_frac": round(x["reveal_frac"], 6) if x["reveal_frac"] is not None else None,
           "duration": x["duration"], "duration_source": x["duration_source"], "labeled_by": x["labeled_by"]}
          for m, x in sorted(ok.items())]
    why = []
    if missing:
        why.append(f"정보 공개 순서 라벨(beats·reveal_t)이 없거나 잘못된 구성원 {len(missing)}편: "
                   + ", ".join(f"{m}({invalid[m]})" if m in invalid else m for m in missing[:10])
                   + ("…" if len(missing) > 10 else ""))
    if ok and order["status"] == "conflict":
        why.append("구성원 영상마다 구간 순서가 다름(" + "; ".join(
            f"{c['pair'][0]}→{c['pair'][1]}: {', '.join(c['a_before_b'])} / 반대: {', '.join(c['b_before_a'])}"
            if "pair" in c else f"순환 {c['cycle']}" for c in order["conflicts"]) + ") — 한 줄 순서로 못 정함; 포맷 라벨 확인")
    elif ok and order["status"] == "partial_order":
        why.append("함께 나온 적이 없어 순서를 모르는 목적 쌍 " + ", ".join(f"{a}/{b}" for a, b in order["unknown_pairs"]))
    complete = not missing
    status = ("measured" if complete and order["status"] == "measured" else
              "unmeasured" if not ok else "partial")
    out = {"beats": order.get("beats") if complete and order["status"] == "measured" else None,
           "reveal_frac": stats["reveal_frac"] if complete else pstats([]),
           "reveal_t_s": stats["reveal_t_s"] if complete else pstats([]),
           "reveal_presence": stats["reveal_presence"] if complete else _presence([]),
           "disclosure": {"status": status, "blocker": "; ".join(why) or None, "n_members": len(members),
                          "n_labeled": len(ok), "missing": missing, "order": order, "evidence": ev,
                          "method": "영상을 본 사람의 라벨(beats·reveal_t) → 포맷 구성원 전부의 순서가 하나로 정해질 때만 beats; "
                                    "reveal_frac = reveal_t / 영상 길이(반전 있는 구성원), p10/p50/p90"}}
    if not complete:
        out["disclosure"]["partial_stats"] = stats
    return out


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
    old_header = _csv_header(lp)
    extra_cols = [c for c in old_header if c not in LABEL_HEADER]        # never drop a column someone added
    have = {r.get("video_id") for r in rows}
    added = 0
    for vid in done:
        if vid not in have:
            rows.append({"video_id": vid, "intro_type": "", "structure_type": "", "beats": "", "reveal_t": "",
                         "notes": "", "labeled_by": "", "watched": "no"})
            added += 1
    upgraded = bool(old_header) and any(c not in old_header for c in LABEL_HEADER)
    if added or upgraded or not lp.exists():
        write_csv_rows(lp, LABEL_HEADER + extra_cols, rows)
    say(f"검토 자료 {len(done)}편 생성, 라벨 파일에 새 행 {added}개 추가({paths.relp(lp)})"
        + (" — 예전 라벨 파일에 새 열(beats, reveal_t)을 추가함" if upgraded else "") + ". "
        "라벨은 영상을 끝까지 보고 들은 사람이 intro_type·structure_type·beats·reveal_t·labeled_by 를 채우고 "
        "watched=yes 로 표시합니다(열 설명: 각 영상 review/timeline.md, formats.yaml label_columns).")
    if skipped:
        warn("건너뜀: " + ", ".join(f"{s['video_id']}({s['reason']})" for s in skipped[:10]))
    return {"prepared": done, "skipped": skipped, "labels_added": added}


def _csv_header(path: Path) -> list[str]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8-sig", newline="") as f:
        return next(csv.reader(f), []) or []


def label_instructions() -> list[str]:
    """How to fill format_labels.csv (review packet section; same text as formats.yaml label_columns)."""
    L = ["## 라벨 채우는 법 (format_labels.csv)", "",
         "영상을 **처음부터 끝까지 보고 들은 뒤** 이 영상의 행을 채웁니다. 이 문서의 자동 분석만 보고 채우지 않습니다.", "",
         "| 열 | 내용 |", "|---|---|"]
    L += [f"| `{k}` | {v} |" for k, v in LABEL_COLUMNS.items()]
    L += ["", "- `beats` 와 `reveal_t` 는 포맷별 정보 공개 순서(구간 목적 순서, 반전 시각 비율 p10/p50/p90)를 재는 데 쓰입니다.",
          "- 반전이 있는 영상: beats 에 `reveal` 이 있어야 하고 reveal_t 는 반전이 처음 보이는 시각(초).",
          "- 반전이 없는 영상: beats 에 `reveal` 을 넣지 않고 reveal_t 는 `none`.", ""]
    return L


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
    L += ["", "> 자동 분석 결과의 요약입니다. `format_labels.csv` 의 라벨(도입 방식·전개 구조·구간 목적 순서·반전 시각)은 "
          "**영상을 실제로 보고 들은 사람만** 채우고 `watched=yes` 로 표시합니다. 이 문서만 보고 라벨을 채우지 마세요.", ""]
    L += label_instructions()
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
                          "notes": (r.get("notes") or "").strip(), "labeled_by": by,
                          "beats": (r.get("beats") or "").strip(), "reveal_t": (r.get("reveal_t") or "").strip()})
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
               "disclosure_order": {"status": "unmeasured", "blocker": "포맷 표 없음(라벨 없음) — 정보 공개 순서 못 잼",
                                    "vocabulary": list(BEATS), "rule": DISCLOSURE_RULE},
               "label_columns": LABEL_COLUMNS,
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
    snap_by = {x.get("video_id"): x for x in snap.get("videos") or [] if isinstance(x, dict)}
    disc, disc_invalid = {}, {}
    for v in valid:
        d, err = disclosure_label(v, video_duration(preset, v["video_id"], snap_by.get(v["video_id"])))
        if d is not None:
            disc[v["video_id"]] = d | {"labeled_by": v["labeled_by"]}
        elif err:
            disc_invalid[v["video_id"]] = err
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
                      "labeled_by": sorted({v["labeled_by"] for v in groups[st]}),
                      **format_disclosure(mem, disc, disc_invalid)})
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
           "disclosure_order": disclosure_summary(table, disc, disc_invalid),
           "label_columns": LABEL_COLUMNS,
           "unlabeled": unlabeled[:200], "rejected_labels": rejected, "outside_snapshot_labels": outside_rows,
           "formats_without_representative": no_rep, "built_at": now_iso()}
    write_yaml(fpath, out)
    say(f"포맷 표: {len(table)}개 포맷, 라벨 {total}편(스냅샷 밖 라벨 {len(outside)}개 제외), 상태 {status} → "
        f"{paths.relp(fpath)}" + (f" — {out['blocker']}" if out["blocker"] else ""))
    do = out["disclosure_order"]
    say(f"정보 공개 순서(beats·reveal_frac): {do['status']}" + (f" — {do['blocker']}" if do.get("blocker") else ""))
    return out


DISCLOSURE_RULE = ("포맷별 구간 목적 순서(beats)와 반전 시각 비율(reveal_frac = reveal_t / 영상 길이)은 영상을 본 사람의 라벨로만 잰다. "
                   "포맷 구성원 전부가 유효한 라벨을 가질 때만 값을 싣고(아니면 partial_stats 에만), beats 는 구성원의 순서가 "
                   "하나의 전체 순서로 정해질 때만(순서 충돌·모르는 쌍이면 None)")


def disclosure_summary(table: list[dict], disc: dict[str, dict], invalid: dict[str, str]) -> dict:
    """Top-level disclosure status of the format table (overall reveal_frac only when every format is complete)."""
    sts = [r["disclosure"]["status"] for r in table]
    status = ("measured" if sts and all(x == "measured" for x in sts) else
              "unmeasured" if not sts or all(x == "unmeasured" for x in sts) else "partial")
    members = [m for r in table for m in r.get("members") or []]
    complete = all(not r["disclosure"]["missing"] for r in table)
    fr = [disc[m]["reveal_frac"] for m in members if m in disc and disc[m]["reveal_frac"] is not None]
    blockers = [f"{r['format_id']}: {r['disclosure']['blocker']}" for r in table if r["disclosure"].get("blocker")]
    return {"status": status, "blocker": "; ".join(blockers) or None,
            "n_members": len(members), "n_labeled": sum(1 for m in members if m in disc),
            "missing": [m for r in table for m in r["disclosure"]["missing"]],
            "rejected": [{"video_id": v, "reason": why} for v, why in sorted(invalid.items())],
            "reveal_frac_overall": pstats(fr if complete else [], digits=6),
            "vocabulary": list(BEATS), "rule": DISCLOSURE_RULE}


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
