"""Font manifest, exact font lookup and fetching.

Rules (docs/CONTRACT.md section 7 and the user's "never guess" rule):

* ``find_font(name)`` returns a file only when one of its faces carries exactly that name
  (fontconfig comparison semantics: case and blanks ignored).  Unlike ``fc-match`` there is
  **no fallback**: a missing font is ``None`` and the caller must report it.
* Accepted names of a face: its full names, its PostScript name, and every
  ``"<family> <style>"`` pair fontconfig reports for the same language (``"<family>"`` alone
  when the paired style is Regular).  E.g. ``Noto Sans CJK KR Black`` (ttc index 1),
  ``NanumGothic ExtraBold``, ``Pretendard Black``, ``Black Han Sans``.
* Search tiers: sha256-verified manifest files in ``assets/fonts`` -> other font files in
  ``assets/fonts`` (and ``extra_dirs``) -> system fonts via fontconfig.  The first tier with a
  match wins; two *different* faces matching inside one tier is ambiguous -> ``None``.
* ``.ttc`` collections: :func:`font_face_index` returns the face index to load.
* ``fetch_all()`` downloads the manifest's fonts (canonical URLs) and verifies sha256.  A
  local directory holding identical files may be passed to avoid the network (the file is
  still sha256-verified).  Network failures are reported per font, never hidden.
"""
from __future__ import annotations

import argparse
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Iterable

from . import paths
from .util.hashing import sha256_file
from .util.jsonio import now_iso, read_yaml

log = logging.getLogger("shortkit.fonts")

MANIFEST = "assets/fonts/manifest.yaml"
FONT_DIR = "assets/fonts"
FONT_EXTS = {".ttf", ".otf", ".ttc", ".otc"}
REGULAR_STYLES = {"regular", "normal", "book", "roman", "standard"}
_SEP = "\x1f"  # field separator for fc-query/fc-list output


# ----------------------------------------------------------------------------- name handling
def norm_name(name: str) -> str:
    """fontconfig-style comparison key: case-insensitive, blanks ignored."""
    return "".join(str(name).split()).casefold()


def _split_fc_list(value: str) -> list[str]:
    """Split a fontconfig multi-value string on unescaped commas."""
    out, cur, esc = [], [], False
    for ch in value:
        if esc:
            cur.append(ch)
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ",":
            out.append("".join(cur))
            cur = []
        else:
            cur.append(ch)
    out.append("".join(cur))
    return [s.strip() for s in out if s.strip()]


@dataclass
class FontFace:
    path: Path
    index: int
    family: str                      # primary family (FreeType / first fontconfig family)
    style: str
    names: list[str] = field(default_factory=list)   # every accepted exact name
    fullname: str | None = None
    postscript: str | None = None
    source: str = ""                  # manifest | assets | dir | system
    sha256: str | None = None

    @property
    def canonical(self) -> str:
        return self.family if self.style.casefold() in REGULAR_STYLES else f"{self.family} {self.style}"

    def matches(self, name: str) -> bool:
        k = norm_name(name)
        return any(norm_name(n) == k for n in self.names)

    def key(self) -> str:
        """Identity of the face independent of where the file lives."""
        return norm_name(self.postscript or self.fullname or self.canonical)

    def to_dict(self) -> dict:
        d = {"path": _display_path(self.path), "index": self.index, "family": self.family, "style": self.style,
             "canonical": self.canonical, "fullname": self.fullname, "postscript": self.postscript,
             "source": self.source}
        if self.sha256:
            d["sha256"] = self.sha256
        return d


def _display_path(p: Path) -> str:
    """Root-relative when inside the project; system fonts are shown by file name only
    (machine-specific install locations must not be stored)."""
    try:
        return paths.relp(p)
    except (ValueError, RuntimeError):
        return f"<system>/{Path(p).name}"


def _pair_names(families: list[str], flangs: list[str], styles: list[str], slangs: list[str]) -> list[str]:
    names: list[str] = []
    by_lang_f: dict[str, list[str]] = {}
    by_lang_s: dict[str, list[str]] = {}
    for i, f in enumerate(families):
        by_lang_f.setdefault(flangs[i] if i < len(flangs) else "", []).append(f)
    for i, s in enumerate(styles):
        by_lang_s.setdefault(slangs[i] if i < len(slangs) else "", []).append(s)
    en_styles = by_lang_s.get("en") or (styles if len(set(slangs)) <= 1 else [])
    for lang, fams in by_lang_f.items():
        sts = by_lang_s.get(lang)
        if not sts or len(sts) != len(fams):
            sts = en_styles if len(en_styles) == len(fams) else None
        if not sts:
            continue
        for fam, sty in zip(fams, sts):
            names.append(f"{fam} {sty}")
            if sty.casefold() in REGULAR_STYLES:
                names.append(fam)
    return names


def _pil_name(path: Path, index: int) -> tuple[str, str] | None:
    try:
        from PIL import ImageFont

        return ImageFont.truetype(str(path), 12, index=index).getname()
    except Exception:
        return None


def _pil_face_count(path: Path) -> int:
    n = 0
    while n < 64:
        if _pil_name(path, n) is None:
            break
        n += 1
    return n


_FC_FMT = _SEP.join(["%{file}", "%{index}", "%{family}", "%{familylang}", "%{style}", "%{stylelang}",
                     "%{fullname}", "%{postscriptname}"]) + "\\n"


def _parse_fc_line(line: str) -> dict | None:
    parts = line.split(_SEP)
    if len(parts) != 8:
        return None
    file, index, fam, flang, sty, slang, full, ps = parts
    try:
        idx = int(index)
    except ValueError:
        idx = 0
    return {"file": file, "index": idx, "families": _split_fc_list(fam), "flangs": _split_fc_list(flang),
            "styles": _split_fc_list(sty), "slangs": _split_fc_list(slang), "fullnames": _split_fc_list(full),
            "postscript": ps.strip() or None}


def _face_from_fc(rec: dict, source: str) -> FontFace:
    path = Path(rec["file"])
    pil = _pil_name(path, rec["index"])
    names = _pair_names(rec["families"], rec["flangs"], rec["styles"], rec["slangs"])
    names += rec["fullnames"]
    if rec["postscript"]:
        names.append(rec["postscript"])
    if pil:
        fam, sty = pil
        names.append(f"{fam} {sty}")
        if sty.casefold() in REGULAR_STYLES:
            names.append(fam)
    else:
        fam = rec["families"][0] if rec["families"] else path.stem
        sty = rec["styles"][0] if rec["styles"] else "Regular"
    seen, uniq = set(), []
    for n in names:
        if n and n not in seen:
            seen.add(n)
            uniq.append(n)
    return FontFace(path=path, index=rec["index"], family=fam, style=sty, names=uniq,
                    fullname=(rec["fullnames"] or [None])[0], postscript=rec["postscript"], source=source)


def has_fontconfig() -> bool:
    return shutil.which("fc-query") is not None and shutil.which("fc-list") is not None


@lru_cache(maxsize=512)
def _faces_cached(path_str: str, mtime: float, source: str) -> tuple[FontFace, ...]:
    path = Path(path_str)
    faces: list[FontFace] = []
    if has_fontconfig():
        try:
            out = subprocess.run(["fc-query", "-f", _FC_FMT, path_str], capture_output=True, text=True,
                                 timeout=30).stdout
            for line in out.splitlines():
                rec = _parse_fc_line(line)
                if rec:
                    rec["file"] = path_str
                    faces.append(_face_from_fc(rec, source))
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("fc-query failed for %s: %s", path, e)
    if not faces:  # PIL-only fallback for *reading names* (not a font fallback)
        for i in range(_pil_face_count(path)):
            pn = _pil_name(path, i)
            if not pn:
                continue
            fam, sty = pn
            names = [f"{fam} {sty}"] + ([fam] if sty.casefold() in REGULAR_STYLES else [])
            faces.append(FontFace(path=path, index=i, family=fam, style=sty, names=names, source=source))
    return tuple(faces)


def face_infos(path: str | os.PathLike, source: str = "file") -> list[FontFace]:
    """All faces in a font file with the names they answer to."""
    p = Path(path)
    if not p.is_file():
        return []
    return [FontFace(**{**f.__dict__, "source": source}) for f in _faces_cached(str(p.resolve()), p.stat().st_mtime,
                                                                               source)]


@lru_cache(maxsize=1)
def _system_faces_cached() -> tuple[FontFace, ...]:
    if not has_fontconfig():
        return ()
    try:
        out = subprocess.run(["fc-list", "-f", _FC_FMT], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("fc-list failed: %s", e)
        return ()
    faces = []
    for line in out.splitlines():
        rec = _parse_fc_line(line)
        if rec and Path(rec["file"]).suffix.lower() in FONT_EXTS:
            faces.append(_face_from_fc(rec, "system"))
    return tuple(faces)


def system_faces() -> list[FontFace]:
    return list(_system_faces_cached())


def clear_caches() -> None:
    _faces_cached.cache_clear()
    _system_faces_cached.cache_clear()


# ----------------------------------------------------------------------------- manifest
def load_manifest() -> dict:
    m = read_yaml(paths.absp(MANIFEST), {}) or {}
    m.setdefault("fonts", [])
    m.setdefault("system", [])
    return m


def manifest_entries(status: str | None = None) -> list[dict]:
    ents = load_manifest()["fonts"]
    return [e for e in ents if status is None or e.get("status") == status]


def candidate_names(include_system: bool = True) -> list[str]:
    """Names of every candidate font the manifest knows how to obtain (acquirable + system)."""
    m = load_manifest()
    names = [e["name"] for e in m["fonts"] if e.get("status") == "acquirable"]
    if include_system:
        names += [e["name"] for e in m["system"]]
    return names


def not_acquired_names() -> list[str]:
    return [e["name"] for e in manifest_entries("not_acquired")]


def _manifest_file_state(entry: dict) -> tuple[Path | None, str]:
    """(path, state): state = ok | missing | sha256_mismatch | no_file."""
    if not entry.get("file"):
        return None, "no_file"
    p = paths.absp(entry["file"])
    if not p.is_file():
        return p, "missing"
    if entry.get("sha256") and sha256_file(p) != entry["sha256"]:
        return p, "sha256_mismatch"
    return p, "ok"


# ----------------------------------------------------------------------------- lookup
def _dir_font_files(d: Path) -> list[Path]:
    if not d.is_dir():
        return []
    return sorted(p for p in d.rglob("*") if p.is_file() and p.suffix.lower() in FONT_EXTS)


def _tiers(extra_dirs: Iterable[str | os.PathLike] | None) -> Iterable[tuple[str, list[FontFace]]]:
    # tier 1: manifest files (sha256 verified)
    man_faces: list[FontFace] = []
    man_files: set[Path] = set()
    for e in manifest_entries("acquirable"):
        p, state = _manifest_file_state(e)
        if p is not None:
            man_files.add(p.resolve())
        if state == "sha256_mismatch":
            log.warning("manifest font '%s' at %s has a different sha256 -> not used", e["name"], e["file"])
        if state != "ok":
            continue
        faces = face_infos(p, "manifest")
        for f in faces:
            f.sha256 = e.get("sha256")
        if not any(f.matches(e["name"]) for f in faces):
            log.warning("manifest entry '%s' does not match any face name in %s -> ignored", e["name"], e["file"])
            continue
        man_faces.extend(faces)
    yield "manifest", man_faces
    # tier 2: any other font file in assets/fonts and extra dirs (manifest files with a wrong sha excluded)
    dir_faces: list[FontFace] = []
    dirs = [paths.absp(FONT_DIR)] + [paths.absp(d) for d in (extra_dirs or [])]
    seen: set[Path] = set()
    for d in dirs:
        for f in _dir_font_files(d):
            r = f.resolve()
            if r in man_files or r in seen:
                continue
            seen.add(r)
            dir_faces.extend(face_infos(f, "assets" if d == dirs[0] else "dir"))
    yield "dir", dir_faces
    yield "system", system_faces()


def resolve_font(name: str, extra_dirs: Iterable[str | os.PathLike] | None = None) -> FontFace | None:
    """Exact face lookup (see module doc).  None when absent or ambiguous."""
    if not name or not str(name).strip():
        return None
    for tier, faces in _tiers(extra_dirs):
        hits = [f for f in faces if f.matches(name)]
        if not hits:
            continue
        distinct = {h.key() for h in hits}
        if len(distinct) > 1:
            log.warning("font name '%s' is ambiguous in tier %s: %s -> refused", name, tier,
                        sorted({h.canonical + ' @ ' + h.path.name for h in hits}))
            return None
        return hits[0]
    return None


def find_font(name: str, extra_dirs: Iterable[str | os.PathLike] | None = None) -> Path | None:
    """Path of the font file whose face is exactly ``name``; None if not installed/fetched.

    Never returns a substitute.  For ``.ttc`` use :func:`font_face_index` to get the face index.
    """
    f = resolve_font(name, extra_dirs)
    return f.path if f else None


def font_face_index(path: str | os.PathLike, name: str) -> int | None:
    """Index of the face called ``name`` inside ``path`` (0 for single-face files); None if absent."""
    for f in face_infos(path):
        if f.matches(name):
            return f.index
    return None


def explain_font(name: str, extra_dirs: Iterable[str | os.PathLike] | None = None) -> dict:
    """Human-oriented lookup trace: what matched, and what fontconfig *would* have substituted."""
    face = resolve_font(name, extra_dirs)
    out: dict = {"name": name, "found": face is not None, "face": face.to_dict() if face else None}
    if face is None:
        out["manifest_status"] = next((e.get("status") for e in load_manifest()["fonts"]
                                       if norm_name(e["name"]) == norm_name(name)), None)
        if shutil.which("fc-match"):
            try:
                sub = subprocess.run(["fc-match", "-f", "%{family} %{style}", name], capture_output=True,
                                     text=True, timeout=20).stdout.strip()
                out["fc_match_would_substitute"] = sub or None
                out["substitute_accepted"] = False
            except (OSError, subprocess.SubprocessError):
                pass
    return out


# ----------------------------------------------------------------------------- fetching
def fetch_all(local_dir: str | os.PathLike | None = None, timeout: float = 60.0,
              names: Iterable[str] | None = None) -> dict:
    """Download every ``acquirable`` manifest font into assets/fonts and verify sha256.

    ``local_dir`` (or env ``SHORTKIT_FONT_CACHE``): a folder that may already hold identical files
    (checked by sha256, never trusted by name).  Returns ``{name: {status, detail, file}}`` with
    status in ok_cached | ok_copied | ok_downloaded | failed | sha256_mismatch | not_acquired.
    """
    local = local_dir or os.environ.get("SHORTKIT_FONT_CACHE")
    want = {norm_name(n) for n in names} if names else None
    out_dir = paths.ensure_dir(FONT_DIR)
    res: dict[str, dict] = {}
    for e in manifest_entries():
        name = e["name"]
        if want is not None and norm_name(name) not in want:
            continue
        if e.get("status") != "acquirable":
            res[name] = {"status": e.get("status") or "unknown", "detail": e.get("note") or "", "file": None}
            continue
        dst = paths.absp(e["file"])
        rel = e["file"]
        sha = e.get("sha256")
        if dst.is_file() and sha256_file(dst) == sha:
            res[name] = {"status": "ok_cached", "detail": "sha256 일치", "file": rel}
            continue
        src = Path(local) / Path(e["file"]).name if local else None
        if src is not None and src.is_file() and sha256_file(src) == sha:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dst)
            res[name] = {"status": "ok_copied", "detail": "로컬 캐시에서 복사(sha256 일치)", "file": rel}
            continue
        try:
            fd, tmp = tempfile.mkstemp(prefix=".fontdl-", dir=str(out_dir))
            os.close(fd)
            try:
                req = urllib.request.Request(e["url"], headers={"User-Agent": "shortkit-fonts/1"})
                with urllib.request.urlopen(req, timeout=timeout) as r, open(tmp, "wb") as f:
                    shutil.copyfileobj(r, f)
                got = sha256_file(tmp)
                if got != sha:
                    res[name] = {"status": "sha256_mismatch", "file": None,
                                 "detail": f"받은 파일 sha256={got} (기대 {sha}) — 사용하지 않음"}
                    continue
                os.replace(tmp, dst)
                os.chmod(dst, 0o644)
                res[name] = {"status": "ok_downloaded", "detail": e["url"], "file": rel}
            finally:
                if os.path.exists(tmp):
                    os.unlink(tmp)
        except Exception as ex:  # network blocked / DNS / HTTP error: report, never pretend
            res[name] = {"status": "failed", "detail": f"{type(ex).__name__}: {ex}", "file": None}
    clear_caches()
    return {"fetched_at": now_iso(), "results": res,
            "ok": all(r["status"].startswith("ok") for r in res.values()
                      if r["status"] not in ("not_acquired",))}


def verify_all() -> dict:
    """State of every manifest/system font on this machine (no network)."""
    m = load_manifest()
    rows = []
    for e in m["fonts"]:
        if e.get("status") != "acquirable":
            rows.append({"name": e["name"], "kind": "manifest", "state": e.get("status"), "file": None})
            continue
        p, state = _manifest_file_state(e)
        face = resolve_font(e["name"]) if state == "ok" else None
        rows.append({"name": e["name"], "kind": "manifest", "state": state if face or state != "ok" else "name_mismatch",
                     "file": e.get("file"), "found": face.to_dict() if face else None})
    for e in m["system"]:
        face = resolve_font(e["name"])
        rows.append({"name": e["name"], "kind": "system", "state": "ok" if face else "missing",
                     "found": face.to_dict() if face else None, "package": e.get("package")})
    return {"checked_at": now_iso(), "fontconfig": has_fontconfig(), "fonts": rows}


# ----------------------------------------------------------------------------- CLI (python -m shortkit.fonts)
_STATE_KO = {"ok": "있음", "missing": "없음", "sha256_mismatch": "해시 불일치(사용 안 함)", "no_file": "파일 없음",
             "not_acquired": "확보 못 함", "name_mismatch": "이름 불일치(사용 안 함)"}


def _cmd_list(args) -> int:
    r = verify_all()
    for row in r["fonts"]:
        st = _STATE_KO.get(row["state"], row["state"])
        where = (row.get("found") or {}).get("path") or row.get("file") or ""
        print(f"{row['kind']:<8} {row['name']:<28} {st:<14} {where}")
    if not r["fontconfig"]:
        print("fontconfig 없음: 시스템 글꼴은 찾지 않음(assets/fonts 파일만 사용)")
    return 0


def _cmd_fetch(args) -> int:
    r = fetch_all(local_dir=args.local_dir)
    for name, row in r["results"].items():
        print(f"{name:<28} {row['status']:<16} {row['detail']}")
    print("결과:", "모두 확보" if r["ok"] else "일부 실패(위 목록 확인)")
    return 0 if r["ok"] else 1


def _cmd_find(args) -> int:
    info = explain_font(args.name)
    if info["found"]:
        f = info["face"]
        print(f"찾음: {f['canonical']}  file={f['path']} index={f['index']} ({f['source']})")
        return 0
    print(f"없음: '{args.name}' (대체 글꼴 자동 사용 안 함)")
    if info.get("fc_match_would_substitute"):
        print(f"  fc-match 는 '{info['fc_match_would_substitute']}' 로 대체하려 하지만 받아들이지 않음")
    if info.get("manifest_status"):
        print(f"  manifest 상태: {info['manifest_status']}")
    return 1


def register(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("list", help="manifest/시스템 후보 글꼴 상태")
    s.set_defaults(func=_cmd_list)
    s = sub.add_parser("fetch", help="manifest 글꼴 다운로드 + sha256 검증")
    s.add_argument("--local-dir", default=None, help="같은 파일이 있는 로컬 폴더(sha256 로 확인 후 복사)")
    s.set_defaults(func=_cmd_fetch)
    s = sub.add_parser("find", help="이름과 정확히 일치하는 글꼴 찾기(대체 없음)")
    s.add_argument("name")
    s.set_defaults(func=_cmd_find)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(prog="python -m shortkit.fonts")
    register(ap)
    a = ap.parse_args()
    sys.exit(a.func(a))
