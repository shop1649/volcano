"""Single-file preset bundle: PRESET_BUNDLE.md = readable instructions + an embedded payload.

The payload (tar.gz of the preset system, base64) sits at the very END of the markdown between
two marker lines, so an agent reads only the instructions at the top and restores the payload
with a command, never reading the long base64 body.

    shortkit bundle build   [--out PRESET_BUNDLE.md]
    shortkit bundle restore --md PRESET_BUNDLE.md --dest <empty folder>
    shortkit bundle verify  --md PRESET_BUNDLE.md

Restore also works WITHOUT shortkit installed (see RESTORE_SNIPPET, embedded in the MD).
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import os
import re
import subprocess
import tarfile
import textwrap
from pathlib import Path

from . import __version__, paths
from .util.jsonio import now_iso

BEGIN = "<!-- SHORTKIT-PAYLOAD-BEGIN (base64 tar.gz; do not read — restore with the command above) -->"
END = "<!-- SHORTKIT-PAYLOAD-END -->"

# Media and heavy/generated files never go into the bundle; they are re-created or fetched.
EXCLUDE_SUFFIXES = {".mp4", ".mov", ".mkv", ".webm", ".wav", ".mp3", ".m4a", ".aac", ".flac", ".png", ".jpg", ".jpeg",
                    ".npy", ".otf", ".ttf", ".ttc", ".woff", ".woff2", ".pyc"}
EXCLUDE_PREFIXES = ("PRESET_BUNDLE.md", ".git/", "warehouse/sources/", "warehouse/cache/")
MAX_FILE_BYTES = 400_000

RESTORE_SNIPPET = r'''python3 - "PRESET_BUNDLE.md" "shortkit-preset" <<'PY'
import base64, hashlib, io, re, sys, tarfile, pathlib
md, dest = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
text = md.read_text(encoding="utf-8")
b = text.index("<!-- SHORTKIT-PAYLOAD-BEGIN"); b = text.index("\n", b) + 1
e = text.index("<!-- SHORTKIT-PAYLOAD-END -->")
raw = base64.b64decode("".join(text[b:e].split()))
want = re.search(r"payload_sha256: ([0-9a-f]{64})", text).group(1)
got = hashlib.sha256(raw).hexdigest()
assert got == want, f"sha256 mismatch {got} != {want}"
dest.mkdir(parents=True, exist_ok=True)
assert not any(dest.iterdir()), f"{dest} is not empty"
with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as t:
    for m in t.getmembers():
        assert not m.name.startswith(("/", "..")) and ".." not in pathlib.PurePosixPath(m.name).parts, m.name
    t.extractall(dest)
print(f"restored {len(t.getmembers())} files into {dest} (sha256 ok)")
PY'''


def _tracked_files(root: Path) -> list[str]:
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-co", "--exclude-standard"], capture_output=True,
                             text=True, check=True).stdout
        files = [f for f in out.splitlines() if f]
    except Exception:
        files = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
    keep = []
    for f in sorted(set(files)):
        p = root / f
        if not p.is_file():
            continue
        if f.startswith(EXCLUDE_PREFIXES) or Path(f).suffix.lower() in EXCLUDE_SUFFIXES:
            continue
        if p.stat().st_size > MAX_FILE_BYTES:
            continue
        keep.append(f)
    return keep


def build_payload(root: Path) -> tuple[bytes, list[str]]:
    files = _tracked_files(root)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", compresslevel=9) as t:
        for f in files:
            info = t.gettarinfo(str(root / f), arcname=f)
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            info.mtime = 0
            with open(root / f, "rb") as fh:
                t.addfile(info, fh)
    return buf.getvalue(), files


def render_md(payload: bytes, files: list[str], header_md: str) -> str:
    sha = hashlib.sha256(payload).hexdigest()
    b64 = base64.b64encode(payload).decode("ascii")
    body = "\n".join(textwrap.wrap(b64, 120))
    manifest = "\n".join(f"- `{f}`" for f in files)
    return (f"{header_md.rstrip()}\n\n"
            f"## 번들 정보\n\n- shortkit {__version__}, built_at: {now_iso()}\n- files: {len(files)}\n"
            f"- payload_sha256: {sha} \n- payload_bytes: {len(payload)}\n\n"
            f"## 복원 명령 (에이전트는 아래 payload 본문을 읽지 말고 이 명령만 실행)\n\n"
            f"새 빈 폴더에서, 이 MD 파일이 있는 위치를 기준으로:\n\n```bash\n{RESTORE_SNIPPET}\n```\n\n"
            f"Windows PowerShell 등 heredoc 이 없는 환경: 위 python 코드 부분을 restore.py 로 저장한 뒤 "
            f"`python restore.py PRESET_BUNDLE.md shortkit-preset`.\n\n"
            f"<details><summary>포함 파일 목록</summary>\n\n{manifest}\n\n</details>\n\n"
            f"{BEGIN}\n{body}\n{END}\n")


def header_text(root: Path) -> str:
    hdr = root / "docs" / "BUNDLE_HEADER.md"
    if hdr.exists():
        return hdr.read_text(encoding="utf-8")
    return "# shortkit preset bundle\n"


def cmd_build(args) -> int:
    root = paths.project_root()
    payload, files = build_payload(root)
    md = render_md(payload, files, header_text(root))
    out = Path(args.out) if args.out else root / "PRESET_BUNDLE.md"
    out.write_text(md, encoding="utf-8")
    print(f"{out.name}: {len(files)} files, payload {len(payload)/1024:.0f} KiB, md {len(md)/1024:.0f} KiB")
    if len(payload) > 2_000_000:
        print("경고: payload 가 2MB 를 넘음 — 제외 규칙을 확인하세요")
    return 0


def extract(md_path: Path, dest: Path) -> int:
    text = md_path.read_text(encoding="utf-8")
    b = text.index("\n", text.index(BEGIN)) + 1
    e = text.index(END)
    raw = base64.b64decode("".join(text[b:e].split()))
    want = _payload_sha(text)
    got = hashlib.sha256(raw).hexdigest()
    if got != want:
        raise ValueError(f"payload sha256 mismatch: {got} != {want}")
    dest.mkdir(parents=True, exist_ok=True)
    if any(dest.iterdir()):
        raise ValueError(f"{dest} is not empty")
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as t:
        members = t.getmembers()
        for m in members:
            parts = Path(m.name).parts
            if m.name.startswith("/") or ".." in parts:
                raise ValueError(f"unsafe path in bundle: {m.name}")
        t.extractall(dest)
    return len(members)


def _payload_sha(text: str) -> str:
    m = re.search(r"payload_sha256: ([0-9a-f]{64})", text)
    if not m:
        raise ValueError("payload_sha256 line not found")
    return m.group(1)


def cmd_restore(args) -> int:
    n = extract(Path(args.md), Path(args.dest))
    print(f"restored {n} files into {args.dest}")
    return 0


def cmd_verify(args) -> int:
    text = Path(args.md).read_text(encoding="utf-8")
    b = text.index("\n", text.index(BEGIN)) + 1
    e = text.index(END)
    raw = base64.b64decode("".join(text[b:e].split()))
    want = _payload_sha(text)
    ok = hashlib.sha256(raw).hexdigest() == want
    print("payload sha256", "OK" if ok else "MISMATCH")
    return 0 if ok else 1


def register(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", default=None)
    b.set_defaults(func=cmd_build)
    r = sub.add_parser("restore")
    r.add_argument("--md", required=True)
    r.add_argument("--dest", required=True)
    r.set_defaults(func=cmd_restore)
    v = sub.add_parser("verify")
    v.add_argument("--md", required=True)
    v.set_defaults(func=cmd_verify)
