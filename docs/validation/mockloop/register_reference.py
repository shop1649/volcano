"""SYNTHETIC mockloop: register the 5 rendered mock episodes as the scratch project's "reference channel".

    SHORTKIT_ROOT=<scratch> PYTHONPATH=<repo> python docs/validation/mockloop/register_reference.py snapshot
    SHORTKIT_ROOT=<scratch> PYTHONPATH=<repo> python docs/validation/mockloop/register_reference.py labels

``snapshot`` writes presets/joshuamagazine/reference/latest100.json of the SCRATCH project (status ok,
5 videos, fake ids SYNTHmock01..05, every field labelled synthetic) and copies the mock MP4s to
reference/videos/<id>.mp4 (``shortkit ref download --ids ...`` then registers them as pre-existing files).
``labels`` fills format_labels.csv (written by ``ref classify prepare``): the structure of each mock is
known because we generated it (labeled_by 'mockloop (synthetic truth)', watched yes).
Never run this against the real project root.
"""
from __future__ import annotations

import csv
import json
import os
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
VIDS = {n: f"SYNTHmock{n:02d}" for n in range(1, 6)}


def root() -> Path:
    r = Path(os.environ["SHORTKIT_ROOT"]).resolve()
    if r == REPO.resolve():
        raise SystemExit("refusing to write synthetic reference data into the real project root")
    return r


def snapshot() -> None:
    r = root()
    rd = r / "presets/joshuamagazine/reference"
    vd = rd / "videos"
    vd.mkdir(parents=True, exist_ok=True)
    vids = []
    for n, vid in VIDS.items():
        src = r / "episodes" / f"mockref-{n:03d}" / "output" / f"mockref-{n:03d}.mp4"
        shutil.copy(src, vd / f"{vid}.mp4")
        rep = json.loads((r / "episodes" / f"mockref-{n:03d}" / "build/render_report.json").read_text(encoding="utf-8"))
        vids.append({"rank": 6 - n, "video_id": vid, "url": f"synthetic://mockloop/{vid}",
                     "title": f"SYNTHETIC mock reference {n} (mockloop)",
                     "published_at": f"2026-09-{10 + n:02d}T09:00:00+00:00", "upload_date": f"202609{10 + n:02d}",
                     "duration": rep["probe"]["duration"], "view_count": None, "view_count_checked_at": None,
                     "kind": "short", "synthetic": True, "source_episode": f"episodes/mockref-{n:03d}"})
    vids.sort(key=lambda v: v["rank"])
    snap = {"schema": "shortkit.ref_snapshot/1", "preset_id": "joshuamagazine-v1", "latest_n": 100, "status": "ok",
            "blocker": None, "synthetic": True,
            "captured_at": "2026-09-24T21:00:00+00:00", "method": "SYNTHETIC mockloop (no platform access)",
            "channel_url": "synthetic://mocktruth", "n": len(vids),
            "notes": ["SYNTHETIC: 이 스냅샷은 mockloop 검증용 가짜 레퍼런스다(우리 렌더러 + presets/mocktruth). "
                      "실제 채널 데이터가 아니며 scratch 프로젝트에만 있다.",
                      "view_count 는 없음(null): 합성 영상에는 조회수가 없다."],
            "videos": vids}
    (rd / "latest100.json").write_text(json.dumps(snap, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"SYNTHETIC snapshot: {len(vids)} videos -> {rd / 'latest100.json'}")
    print("ids: " + ",".join(v["video_id"] for v in vids))


def labels() -> None:
    r = root()
    p = r / "presets/joshuamagazine/format_labels.csv"
    rows = list(csv.DictReader(p.open(encoding="utf-8-sig")))
    notes = {
        "SYNTHmock01": "SYNTHETIC mockref-001: 확대 도입 → flash 전개 → 살린 대사 → 느린 재생(같은 샷) → 걷는 중 정지+반응",
        "SYNTHmock02": "SYNTHETIC mockref-002: 확대 도입+걷는 중 정지·반응 → 전개 → flash 살린 대사 → 전개 → 느린 재생 마무리",
        "SYNTHmock03": "SYNTHETIC mockref-003: 확대 도입 → flash 걷는 중 정지·반응 → 전개 → 크로스페이드 살린 대사 → 정적 뒤 마무리",
        "SYNTHmock04": "SYNTHETIC mockref-004: 확대 도입 → 전개 → 느린 재생 → 걷는 중 정지·반응 → 크로스페이드 마무리(대사 없음)",
        "SYNTHmock05": "SYNTHETIC mockref-005: 확대 도입+걷는 중 정지·반응 → 전개 → flash 살린 대사 → 전개 → 느린 재생 마무리",
    }
    for row in rows:
        if row["video_id"] in notes:
            row.update({"intro_type": "walk_in_zoom", "structure_type": "hook_build_reaction_outro",
                        "notes": notes[row["video_id"]], "labeled_by": "mockloop (synthetic truth)", "watched": "yes"})
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"labels: {sum(1 for x in rows if x['video_id'] in notes)} rows -> {p}")


def manual() -> None:
    """Watched observations for the keys NO automatic analyzer measures (cover.source, cover.text_role,
    text.tone.emoji) -- made by looking at each mock's first frame and review contact sheet.  They are the
    human channel of the chain, not analyzer accuracy (mockloop.md lists them separately)."""
    r = root()
    p = r / "presets/joshuamagazine/manual_observations.csv"
    rows = list(csv.DictReader(p.open(encoding="utf-8-sig"))) if p.is_file() else []
    by = "mockloop (synthetic truth)"
    for vid in VIDS.values():
        rows = [x for x in rows if x.get("video_id") != vid]
        rows += [{"video_id": vid, "t": "0.0", "key": "cover.source", "value": "first_frame", "observed_by": by,
                  "watched": "yes", "note": "SYNTHETIC: 첫 프레임(0.0s)에 제목이 보이는 화면이 표지"},
                 {"video_id": vid, "t": "0.0", "key": "cover.text_role", "value": "title", "observed_by": by,
                  "watched": "yes", "note": "SYNTHETIC: 표지 글자 = 상단 제목 자막"},
                 {"video_id": vid, "t": "1.0", "key": "text.tone.emoji", "value": "no", "observed_by": by,
                  "watched": "yes", "note": "SYNTHETIC: 자막 전체에 이모지 없음(검토 밀착 인화로 확인)"}]
    with p.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["video_id", "t", "key", "value", "observed_by", "watched", "note"])
        w.writeheader()
        w.writerows(rows)
    print(f"manual observations: {len(rows)} rows -> {p}")


if __name__ == "__main__":
    {"snapshot": snapshot, "labels": labels, "manual": manual}[sys.argv[1]]()
