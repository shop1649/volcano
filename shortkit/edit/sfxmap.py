"""SFX catalog / map access (presets/<p>/sfx_catalog.json, sfx_map.yaml).

sfx_map.yaml ``types: {type_id: {status: have|none|unmeasured, file, similarity, method,
alternatives, needed_asset}}`` + ``library_root`` (overridable by ``sfx_library_root`` in the
git-ignored ``local.yaml``).  A type missing from the map is ``unmeasured`` (못 잼) -- never
treated as available.
"""
from __future__ import annotations

from pathlib import Path

from .. import config, paths
from ..util.jsonio import read_json, read_yaml

MAP_STATUS = ("have", "none", "unmeasured")
MAP_STATUS_KO = {"have": "있음", "none": "없음", "unmeasured": "못 잼"}


def local_settings() -> dict:
    return read_yaml(paths.absp("local.yaml"), {}) or {}


def load_catalog(preset: config.Preset) -> dict:
    rel = preset.get("audio.sfx.catalog")
    cat = read_json(paths.absp(rel), None)
    if cat is None:
        return {"status": "unmeasured", "blocker": f"{rel} 없음", "types": [], "_path": rel, "_missing": True}
    if cat.get("preset_id"):
        preset.assert_same_preset(cat["preset_id"], rel)
    cat["_path"] = rel
    return cat


def load_map(preset: config.Preset) -> dict:
    rel = preset.get("audio.sfx.map")
    m = read_yaml(paths.absp(rel), None)
    if m is None:
        return {"types": {}, "library_root": None, "_path": rel, "_missing": True}
    if m.get("preset_id"):
        preset.assert_same_preset(m["preset_id"], rel)
    m["_path"] = rel
    m.setdefault("types", {})
    return m


def library_root(smap: dict) -> str | None:
    return local_settings().get("sfx_library_root") or smap.get("library_root")


def _abs(stored: str) -> Path | None:
    """Root-relative path or ``$sfx_library_root/...`` / ``$music_library_root/...`` token path
    (``shortkit.reference.separation.resolve_stored``) -> absolute path (None: token root not set)."""
    if stored.startswith("$"):
        from ..reference.separation import resolve_stored

        try:
            return Path(resolve_stored(stored))
        except FileNotFoundError:
            return None
    return paths.absp(stored)


def _resolve_file(file: str, lib_root: str | None) -> str | None:
    """Map file -> root-relative path if it exists (as root-relative / token path, or relative to
    library_root, which may itself be a token).  Files outside the project cannot be stored."""
    cands = [file]
    if lib_root and not file.startswith("$"):
        cands.append(f"{str(lib_root).rstrip('/')}/{file}")
    for c in cands:
        p = _abs(c)
        if p is not None and p.is_file():
            try:
                return paths.relp(p)
            except ValueError:
                return None  # outside the project: cannot be stored (copy it into assets/library/sfx)
    return None


def lookup(preset: config.Preset, type_id: str, smap: dict | None = None) -> dict:
    """{status, file (root-relative or None), similarity, method, needed_asset, note}"""
    smap = smap if smap is not None else load_map(preset)
    ent = (smap.get("types") or {}).get(type_id)
    if not ent:
        return {"status": "unmeasured", "file": None, "similarity": None, "method": None,
                "needed_asset": None, "note": f"sfx_map 에 '{type_id}' 항목 없음"}
    st = ent.get("status") if ent.get("status") in MAP_STATUS else "unmeasured"
    f = None
    note = ""
    if st == "have":
        if ent.get("file"):
            f = _resolve_file(ent["file"], library_root(smap))
            if f is None:
                note = f"맵 파일 {ent['file']} 을 찾을 수 없음(또는 프로젝트 밖)"
        else:
            note = "status=have 인데 file 이 비어 있음"
    return {"status": st, "file": f, "similarity": ent.get("similarity"), "method": ent.get("method"),
            "needed_asset": ent.get("needed_asset"), "note": note}


def catalog_type(cat: dict, type_id: str) -> dict | None:
    for t in cat.get("types") or []:
        if t.get("type_id") == type_id:
            return t
    return None


def count_range(entry: dict | None, format_id: str | None) -> tuple[dict | None, str]:
    """Observed per-video count stats for a catalog entry: by_format[format_id] if present, else overall."""
    if not entry:
        return None, "none"
    by = (entry.get("by_format") or {})
    if format_id and by.get(format_id) and by[format_id].get("n"):
        return by[format_id], f"by_format.{format_id}"
    ov = entry.get("overall")
    if ov and ov.get("n"):
        return ov, "overall"
    return None, "none"
