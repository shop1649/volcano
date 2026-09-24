"""Project-root-relative path handling.

Rules (see docs/CONTRACT.md):
- Every path that is *stored* (yaml/json/jsonl/plan/project files) is relative to the
  project root and uses POSIX separators.  No absolute paths, user names or
  machine-specific install locations are ever written to stored files.
- Absolute paths exist only at runtime (``absp``).
- The project root is ``$SHORTKIT_ROOT`` if set, otherwise the nearest parent directory of
  the current working directory (or of this package) that contains ``shortkit.root``.
"""
from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

MARKER = "shortkit.root"


def _find_root(start: Path) -> Path | None:
    start = start.resolve()
    for p in [start, *start.parents]:
        if (p / MARKER).is_file():
            return p
    return None


def project_root() -> Path:
    env = os.environ.get("SHORTKIT_ROOT")
    if env:
        root = Path(env).expanduser().resolve()
        if not (root / MARKER).is_file():
            raise RuntimeError(f"SHORTKIT_ROOT={env} does not contain {MARKER}")
        return root
    for start in (Path.cwd(), Path(__file__).parent):
        r = _find_root(start)
        if r is not None:
            return r
    raise RuntimeError(
        f"project root not found: run inside the preset folder (it contains {MARKER}) or set SHORTKIT_ROOT"
    )


def absp(rel: str | os.PathLike) -> Path:
    """Stored (root-relative) path -> absolute runtime path. Absolute input is returned as-is."""
    p = Path(rel)
    if p.is_absolute():
        return p
    return project_root() / Path(*PurePosixPath(str(rel).replace("\\", "/")).parts)


def relp(path: str | os.PathLike) -> str:
    """Runtime path -> root-relative POSIX string for storage.

    Raises ValueError for paths outside the project root: callers must copy/link such
    files into the project (e.g. warehouse/sources, assets/library) before storing them.
    """
    p = Path(path)
    if not p.is_absolute():
        p = (Path.cwd() / p)
    p = p.resolve()
    root = project_root()
    try:
        return p.relative_to(root).as_posix()
    except ValueError:
        raise ValueError(f"path is outside the project root, refuse to store it: {p}") from None


def ensure_dir(rel_or_abs: str | os.PathLike) -> Path:
    p = absp(rel_or_abs)
    p.mkdir(parents=True, exist_ok=True)
    return p


def preset_dir(preset_name: str) -> Path:
    return absp(f"presets/{preset_name}")


def episode_dir(episode_id: str) -> Path:
    return absp(f"episodes/{episode_id}")
