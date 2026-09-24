from __future__ import annotations

import hashlib
import os
from pathlib import Path


def sha256_file(path: str | os.PathLike, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            b = f.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def short_id(text: str, n: int = 12) -> str:
    return sha256_text(text)[:n]


def file_matches(path: str | os.PathLike, sha256: str | None) -> bool:
    p = Path(path)
    return bool(sha256) and p.is_file() and sha256_file(p) == sha256
