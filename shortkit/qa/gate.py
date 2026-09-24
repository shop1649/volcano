"""Final gate (docs/CONTRACT.md section 10).

The gate passes only when
  G1  no row is ``different`` without ``intended_change``
  G2  no required row is ``unmeasured``
  G3  SFX without an event = 0 (the ``audio.sfx.no_event`` row is ``same``)
  G4  every SFX lies within +-max_event_offset_s of its event (all ``audio.sfx.offset`` rows ``same``)
  G5  the MP4 on disk is the one that was measured (sha256 unchanged since the QA run)
Production additionally requires (``complete``):
  P1  no preset key is still unmeasured (provisional) -- unmeasured never becomes complete
  P2  no style-vs-reference row is ``unmeasured``
  P3  the plan is a production plan (test-mode outputs are never publishable)
"""
from __future__ import annotations

from .checks import CAT


def evaluate(rows: list[dict], *, mode: str, mp4_sha_measured: str | None, mp4_sha_now: str | None,
             unmeasured_preset_keys: list[str], production: bool | None = None, checked_at: str | None = None) -> dict:
    from ..util.jsonio import now_iso

    production = (mode == "production") if production is None else production
    fails: list[dict] = []
    warns: list[dict] = []

    diff = [r for r in rows if r["status"] == "different" and not r.get("intended_change")]
    if diff:
        fails.append({"rule": "G1", "message": f"의도하지 않은 차이(다르다) {len(diff)}건",
                      "rows": [r["row_id"] for r in diff]})
    req_un = [r for r in rows if r["status"] == "unmeasured" and r.get("required")]
    if req_un:
        fails.append({"rule": "G2", "message": f"필수 항목 못 잼 {len(req_un)}건 — 못 잼은 완료가 아님",
                      "rows": [r["row_id"] for r in req_un]})
    ne = [r for r in rows if r["check_id"] == "audio.sfx.no_event"]
    if not ne:
        if any(r["check_id"].startswith("audio.") for r in rows):
            fails.append({"rule": "G3", "message": "사건 없는 효과음 검사 행이 없음", "rows": []})
    elif any(r["status"] != "same" for r in ne):
        fails.append({"rule": "G3", "message": "사건 없는 효과음이 0 이 아님(또는 못 잼)", "rows": [r["row_id"] for r in ne]})
    off = [r for r in rows if r["check_id"] == "audio.sfx.offset" and r["status"] != "same"]
    if off:
        fails.append({"rule": "G4", "message": f"사건과의 시차 초과/못 잼 효과음 {len(off)}건", "rows": [r["row_id"] for r in off]})
    if mp4_sha_now is None:
        fails.append({"rule": "G5", "message": "출력 MP4 가 없음", "rows": []})
    elif mp4_sha_measured and mp4_sha_now != mp4_sha_measured:
        fails.append({"rule": "G5", "message": "QA 이후 출력 MP4 가 바뀜 — 다시 `shortkit qa run` 필요", "rows": []})

    style_un = [r for r in rows if r.get("kind") == "style_vs_reference" and r["status"] == "unmeasured"]
    prod_fail: list[dict] = []
    if unmeasured_preset_keys:
        prod_fail.append({"rule": "P1", "message": f"프리셋 미측정(임시값) 키 {len(unmeasured_preset_keys)}개",
                          "rows": unmeasured_preset_keys[:50]})
    if style_un:
        prod_fail.append({"rule": "P2", "message": f"레퍼런스 대비 못 잼 {len(style_un)}건",
                          "rows": [r["row_id"] for r in style_un]})
    if mode != "production":
        prod_fail.append({"rule": "P3", "message": "테스트 모드 출력(파이프라인 검증용) — 게시 불가", "rows": []})
    if production:
        fails.extend(prod_fail)
    else:
        warns.extend(prod_fail)
    missing_cats = sorted(set(CAT[k] for k in ("text_pos", "cut", "music", "original", "sfx_no_event", "identity",
                                                "loudness")) - {r["category"] for r in rows})
    if missing_cats and len(rows) > 5:
        warns.append({"rule": "W1", "message": "행이 없는 필수 분류: " + ", ".join(missing_cats), "rows": []})
    passed = not fails
    return {"pass": passed, "complete": passed and not prod_fail, "mode": mode, "production_rules": production,
            "checked_at": checked_at or now_iso(), "failures": fails, "warnings": warns,
            "verdict_ko": ("통과" if passed else "불합격") + ("" if (passed and not prod_fail) else
                                                           " (완료 아님: " + ", ".join(p["rule"] for p in prod_fail) + ")"
                                                           if passed else "")}


def gate_episode(episode_id: str, production: bool | None = None) -> dict:
    """Re-evaluate the gate from the saved report + the MP4 currently on disk + the preset now."""
    from .. import paths
    from ..config import load_preset
    from ..util.hashing import sha256_file
    from ..util.jsonio import read_json

    ep = paths.episode_dir(episode_id)
    rep = read_json(ep / "qa" / "report.json")
    if rep is None:
        return {"pass": False, "complete": False, "failures": [{"rule": "G0", "message": "QA 보고서 없음 — 먼저 `shortkit qa run`",
                                                                "rows": []}], "warnings": [], "verdict_ko": "불합격"}
    mp4 = paths.absp(rep["output"]["path"])
    sha_now = sha256_file(mp4) if mp4.is_file() else None
    fmt = rep.get("format_id") if rep.get("format_id") not in (None, "UNCLASSIFIED") else None
    pr = load_preset(rep["preset_name"], fmt)
    return evaluate(rep["rows"], mode=rep.get("mode", "test"), mp4_sha_measured=rep["output"].get("sha256"),
                    mp4_sha_now=sha_now, unmeasured_preset_keys=pr.unmeasured_keys(), production=production)
