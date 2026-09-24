"""Map catalogued SFX types to files in the user's SFX library -> ``presets/<name>/sfx_map.yaml``.

Library root: ``local.yaml: sfx_library_root`` (user machine, runtime only) overrides
``sfx_map.yaml: library_root`` (root-relative, default ``assets/library/sfx``).  Files outside the
project are stored as ``$sfx_library_root/<relative path>`` (never absolute).

Per catalog type of class ``edit_sfx``:
  have       best library fingerprint similarity >= threshold (file, similarity, alternatives)
  none       library scanned, nothing close enough -> ``needed_asset`` describes what to get
  unmeasured the type itself is unmeasured, or the library is missing/has no audio files
             (``library_status: not_provided|scanned``)
``onsite_sound`` / ``intentional_silence`` types are not placed from a library; they are listed in
``not_mapped`` with the reason.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from .. import paths
from ..config import load_preset
from ..util.hashing import sha256_file
from ..util.jsonio import now_iso, read_json, read_yaml, write_yaml
from .separation import AUDIO_EXT, DEFAULT_PRESET, load_mono, local_settings, store_path
from .sfx_events import SR, _short_env_db, fingerprint_clip, similarity_matrix

SCHEMA = "shortkit.sfx_map/1"
MATCH_THRESHOLD = 0.80
SFX_AUDIO_EXT = tuple(e for e in AUDIO_EXT if e not in (".mp4", ".mkv", ".mov", ".webm"))
MAX_FILE_S = 20.0


def map_path(preset_name: str) -> Path:
    pr = load_preset(preset_name)
    return paths.absp(pr.get("audio.sfx.map"))


def library_root(preset_name: str) -> dict:
    """{root: Path|None, token, stored_root, source}."""
    cur = read_yaml(map_path(preset_name), {}) or {}
    loc = local_settings().get("sfx_library_root")
    if loc:
        return {"root": Path(os.path.expanduser(str(loc))), "token": "$sfx_library_root",
                "stored_root": "$sfx_library_root", "source": "local.yaml sfx_library_root"}
    rel = cur.get("library_root") or "assets/library/sfx"
    return {"root": paths.absp(rel), "token": None, "stored_root": rel, "source": "sfx_map.yaml library_root"}


def onset_of(x: np.ndarray, sr: int = SR, rel_db: float = 40.0) -> float:
    """First time the 5 ms envelope is within `rel_db` of the file's peak (skips leading silence)."""
    if not len(x):
        return 0.0
    t, env = _short_env_db(x, sr)
    above = np.nonzero(env > float(env.max()) - rel_db)[0]
    return max(0.0, float(t[above[0]]) - 0.0025) if len(above) else 0.0


def scan_library(root: Path, token: str | None = None) -> tuple[list[dict], list[dict]]:
    files, errors = [], []
    for f in sorted(root.rglob("*")):
        if not f.is_file() or f.suffix.lower() not in SFX_AUDIO_EXT or f.name.startswith("."):
            continue
        try:
            x = load_mono(f, SR)
        except Exception as e:  # unreadable file: report, do not guess
            errors.append({"file": f.name, "error": f"{type(e).__name__}: {str(e)[:120]}"})
            continue
        if not len(x) or float(np.max(np.abs(x))) < 1e-5:
            errors.append({"file": f.name, "error": "silent or empty"})
            continue
        x = x[: int(MAX_FILE_S * SR)]
        on = onset_of(x)
        fp = fingerprint_clip(x, SR, on)
        files.append({"file": f, "stored": store_path(f, token, root), "onset_s": round(on, 4), "patch": fp["patch"],
                      "stats": fp["stats"]})
    return files, errors


def _needed(t: dict, best: dict | None, threshold: float) -> str:
    d = t.get("duration_s") or {}
    ex = ", ".join(f"{e['video_id']}@{e['t']:.2f}s" for e in (t.get("examples") or [])[:3])
    txt = f"필요한 효과음: {t.get('label')}"
    if d.get("n"):
        txt += f"; 길이 p50 {d['p50']:.2f} s"
    if ex:
        txt += f"; 레퍼런스 예(직접 들어보고 고를 것): {ex}"
    if best:
        txt += f"; 가장 가까운 라이브러리 파일 {best['stored']} (유사도 {best['similarity']:.2f} < 기준 {threshold})"
    return txt


def build_map(preset_name: str = DEFAULT_PRESET, threshold: float = MATCH_THRESHOLD, write: bool = True) -> dict:
    pr = load_preset(preset_name)
    cat_rel = pr.get("audio.sfx.catalog")
    cat = read_json(paths.absp(cat_rel)) or {}
    lib = library_root(preset_name)
    root: Path = lib["root"]
    out: dict = {"schema": SCHEMA, "preset_id": pr.preset_id, "library_root": lib["stored_root"],
                 "library_root_source": lib["source"], "updated_at": now_iso(), "threshold": threshold,
                 "method": "log-mel 64 지문 유사도(이득·EQ 불변 코사인 평균, ±3 프레임 이동) — 카탈로그 중심 지문 대 "
                           "라이브러리 파일(선행 무음 제거)",
                 "catalog": {"file": cat_rel, "status": cat.get("status", "unmeasured"),
                             "blocker": cat.get("blocker")},
                 "listening_check": "not_done"}
    types = [t for t in (cat.get("types") or [])]
    mappable = [t for t in types if t.get("class") == "edit_sfx"]
    out["not_mapped"] = {t["type_id"]: ("원본 현장음 — 라이브러리로 대체하지 않음" if t.get("class") == "onsite_sound"
                                        else "의도적 정적 — 파일 없음(BGM 끊기)")
                         for t in types if t.get("class") != "edit_sfx"}
    if not root.is_dir():
        out.update({"library_status": "not_provided", "library_files": 0,
                    "types": {t["type_id"]: {"status": "unmeasured", "file": None, "similarity": None,
                                             "method": None, "alternatives": [],
                                             "needed_asset": _needed(t, None, threshold),
                                             "blocker": "효과음 창고 미제공"} for t in mappable}})
        if not mappable:
            out["note"] = "카탈로그에 효과음 종류가 없음(못 잼) + 효과음 창고 미제공"
        if write:
            write_yaml(map_path(preset_name), out)
        return out
    files, errors = scan_library(root, lib["token"])
    out.update({"library_status": "scanned" if files else "not_provided", "library_files": len(files),
                "scanned_at": now_iso(), "unreadable": errors})
    if not files:
        out["library_note"] = "창고 폴더는 있으나 읽을 수 있는 효과음 파일이 없음(사용자 미제공)"
        out["types"] = {t["type_id"]: {"status": "unmeasured", "file": None, "similarity": None, "method": None,
                                       "alternatives": [], "needed_asset": _needed(t, None, threshold),
                                       "blocker": "효과음 창고에 파일 없음"} for t in mappable}
        if write:
            write_yaml(map_path(preset_name), out)
        return out
    res: dict = {}
    usable, patches = [], []
    for t in mappable:
        c = (t.get("fingerprint") or {}).get("centroid")
        if not c or not paths.absp(c).is_file():
            res[t["type_id"]] = {"status": "unmeasured", "file": None, "similarity": None, "method": None,
                                 "alternatives": [], "needed_asset": _needed(t, None, threshold),
                                 "blocker": "카탈로그 지문(centroid) 파일 없음"}
            continue
        usable.append(t)
        patches.append(np.load(paths.absp(c)).astype(np.float32))
    if usable:
        S = similarity_matrix(patches, [f["patch"] for f in files])
        for t, row in zip(usable, S):
            order = np.argsort(row)[::-1]
            best = {"stored": files[order[0]]["stored"], "similarity": float(row[order[0]])}
            alts = [{"file": files[j]["stored"], "similarity": round(float(row[j]), 3)} for j in order[1:4]]
            if best["similarity"] >= threshold:
                f = files[order[0]]
                res[t["type_id"]] = {"status": "have", "file": best["stored"], "similarity": round(best["similarity"], 3),
                                     "sha256": sha256_file(f["file"]), "onset_s": f["onset_s"],
                                     "method": "fingerprint", "alternatives": alts, "needed_asset": None,
                                     "label": t.get("label")}
            else:
                res[t["type_id"]] = {"status": "none", "file": None, "similarity": round(best["similarity"], 3),
                                     "method": "fingerprint", "alternatives": [{"file": best["stored"],
                                                                                 "similarity": round(best["similarity"], 3)}]
                                     + alts, "needed_asset": _needed(t, best, threshold), "label": t.get("label")}
    out["types"] = res
    if write:
        write_yaml(map_path(preset_name), out)
    return out
