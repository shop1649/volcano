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

# ----------------------------------------------------------------------------- selection policy
# Secrets / machine-local files: NEVER packed, whatever git says.
HARD_EXCLUDE = ["local.yaml", "cookies/**", "*cookies*", ".venv/**", "venv/**", ".git/**", "**/__pycache__/**", "*.pyc",
                "*.log", "PRESET_BUNDLE.md", ".pytest_cache/**"]
# Media / regenerable / third-party footage: excluded BY PATH (re-created or fetched after restore).
MEDIA_EXCLUDE = ["warehouse/sources/**", "warehouse/cache/**", "warehouse/overlays/*/**",
                 "presets/*/reference/videos/**", "presets/*/analysis/*/stems/**", "presets/*/analysis/*/frames/**",
                 "presets/*/analysis/*/review/**", "presets/*/analysis/*/lens/**", "presets/*/analysis/*/audio/sfx_fp/**",
                 "episodes/*/build/**", "episodes/*/output/**", "episodes/*/project/media/**", "episodes/*/qa/frames/**",
                 "episodes/*/qa/*.png", "assets/test/generated/**", "assets/fonts/*.ttf", "assets/fonts/*.otf",
                 "assets/fonts/*.ttc", "assets/library/music/**", "assets/library/sfx/**", "docs/validation/mockloop/**", "docs/**/*.png"]
# Always packed even when binary: small preset assets production needs (SFX catalog fingerprints, logo templates).
ALWAYS_INCLUDE = ["presets/*/sfx_fp/*", "presets/*/reference/identity_templates/*",
                  "assets/library/music/README.md", "assets/library/music/index.yaml", "assets/library/sfx/README.md"]
BINARY_MAX_BYTES = 2_000_000
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".json", ".jsonl", ".csv", ".txt", ".toml", ".sh", ".ps1", ".ass", ".srt",
                 ".mlt", ".fcpxml", ".otio", ".root", ""}
# Losing any of these would silently change the preset: the build fails instead.
MUST_KEEP = ["presets/**", "warehouse/*.json", "warehouse/*.jsonl", "warehouse/*.yaml", "episodes/*/plan.yaml"]


def _glob_re(pat: str) -> re.Pattern:
    """gitignore-like glob -> regex (supports **, *, ?; a pattern without '/' matches any path component)."""
    anchored = "/" in pat.rstrip("/")
    p = pat.rstrip("/")
    out, i = "", 0
    while i < len(p):
        c = p[i]
        if p.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
            continue
        if p.startswith("**", i):
            out += ".*"
            i += 2
            continue
        out += "[^/]*" if c == "*" else "[^/]" if c == "?" else re.escape(c)
        i += 1
    if anchored:
        return re.compile("^" + out.lstrip("/") + "(?:/.*)?$")
    return re.compile("(?:^|.*/)" + out + "(?:/.*)?$")


def _matches(path: str, patterns) -> bool:
    return any(_glob_re(p).match(path) for p in patterns)


def _gitignore_patterns(root: Path) -> list[tuple[bool, re.Pattern]]:
    gi = root / ".gitignore"
    pats = []
    if gi.exists():
        for line in gi.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            neg = line.startswith("!")
            pats.append((neg, _glob_re(line[1:] if neg else line)))
    return pats


def _gitignored(path: str, pats) -> bool:
    ignored = False
    for neg, rx in pats:
        if rx.match(path):
            ignored = not neg
    return ignored


def _local_cookie_paths(root: Path) -> list[str]:
    try:
        import yaml

        d = yaml.safe_load((root / "local.yaml").read_text(encoding="utf-8")) or {}
    except Exception:
        return []
    ck = ((d.get("sourcing") or {}).get("cookies") or {}) if isinstance(d, dict) else {}
    return [str(v).replace("\\", "/") for v in ck.values() if v]


def select_files(root: Path) -> tuple[list[str], list[tuple[str, str]]]:
    """(files to pack, [(skipped path, reason)]).  Uses git when available, else the project's .gitignore."""
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "-co", "--exclude-standard"], capture_output=True,
                             text=True, check=True).stdout
        files = [f for f in out.splitlines() if f]
    except Exception:
        pats = _gitignore_patterns(root)
        files = [p.relative_to(root).as_posix() for p in root.rglob("*") if p.is_file()]
        files = [f for f in files if not _gitignored(f, pats)]
    secrets = HARD_EXCLUDE + _local_cookie_paths(root)
    keep, skipped = [], []
    for f in sorted(set(files)):
        p = root / f
        if not p.is_file():
            continue
        if _matches(f, secrets):
            skipped.append((f, "secret/machine-local"))
            continue
        always = _matches(f, ALWAYS_INCLUDE)
        if not always and _matches(f, MEDIA_EXCLUDE):
            skipped.append((f, "media/regenerable"))
            continue
        is_text = Path(f).suffix.lower() in TEXT_SUFFIXES
        if not is_text and not always and p.stat().st_size > BINARY_MAX_BYTES:
            skipped.append((f, f"binary > {BINARY_MAX_BYTES} bytes"))
            continue
        keep.append(f)
    return keep, skipped


RESTORE_SNIPPET = r'''python3 - "PRESET_BUNDLE.md" "shortkit-preset" <<'PY'
import base64, hashlib, io, re, sys, tarfile, pathlib
md, dest = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
text = md.read_text(encoding="utf-8")
b = text.rindex("<!-- SHORTKIT-PAYLOAD-" + "BEGIN"); b = text.index("\n", b) + 1   # last marker = the real one
e = text.rindex("<!-- SHORTKIT-PAYLOAD-" + "END -->")
raw = base64.b64decode("".join(text[b:e].split()))
want = re.search(r"payload_sha256: ([0-9a-f]{64})", text).group(1)
got = hashlib.sha256(raw).hexdigest()
assert got == want, f"sha256 mismatch {got} != {want}"
dest.mkdir(parents=True, exist_ok=True)
assert not any(dest.iterdir()), f"{dest} is not empty"
with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as t:
    members = t.getmembers()
    for m in members:
        assert not m.name.startswith(("/", "..")) and ".." not in pathlib.PurePosixPath(m.name).parts, m.name
    t.extractall(dest)
print(f"restored {len(members)} files into {dest} (sha256 ok)")
PY'''


def build_payload(root: Path) -> tuple[bytes, list[str]]:
    files, skipped = select_files(root)
    # media under presets/ (reference videos, stems, frames) is excluded on purpose; anything else lost is an error
    lost = [(f, why) for f, why in skipped if why.startswith("binary") and _matches(f, MUST_KEEP)]
    if lost:
        raise ValueError("preset files would be dropped from the bundle: " + ", ".join(f"{f} ({w})" for f, w in lost))
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
    top = (f"> **에이전트: 이 파일은 1–@@READ@@ 줄만 읽는다.** @@NEXT@@ 줄부터는 base64 payload 이며 읽지 말고 아래 복원 명령으로 푼다.\n\n"
           f"{header_md.rstrip()}\n\n"
           f"## 복원 명령 (payload 본문을 읽지 말고 이 명령만 실행)\n\n"
           f"새 빈 폴더에서, 이 MD 파일이 있는 위치를 기준으로:\n\n```bash\n{RESTORE_SNIPPET}\n```\n\n"
           f"Windows PowerShell 등 heredoc 이 없는 환경: 위 python 코드 부분(PY 사이)을 restore.py 로 저장한 뒤 "
           f"`python restore.py PRESET_BUNDLE.md shortkit-preset`. shortkit 이 설치된 환경이면 "
           f"`python -m shortkit bundle restore --md PRESET_BUNDLE.md --dest shortkit-preset` 도 같다.\n\n"
           f"## 번들 정보\n\n- shortkit {__version__}, built_at: {now_iso()}\n- files: {len(files)}\n"
           f"- payload_sha256: {sha} \n- payload_bytes: {len(payload)}\n\n"
           f"<details><summary>포함 파일 목록</summary>\n\n{manifest}\n\n</details>\n\n")
    n_read = top.count("\n")          # lines before the BEGIN marker line
    top = top.replace("@@READ@@", str(n_read), 1).replace("@@NEXT@@", str(n_read + 2), 1)
    return f"{top}{BEGIN}\n{body}\n{END}\n"


def header_text(root: Path) -> str:
    hdr = root / "docs" / "BUNDLE_HEADER.md"
    if hdr.exists():
        return hdr.read_text(encoding="utf-8")
    return "# shortkit preset bundle\n"


def cmd_build(args) -> int:
    root = paths.project_root()
    _, skipped = select_files(root)
    by_reason: dict[str, list[str]] = {}
    for f, why in skipped:
        by_reason.setdefault(why, []).append(f)
    for why, fs in sorted(by_reason.items()):
        print(f"제외({why}): {len(fs)}개" + ("" if why == "media/regenerable" else " — " + ", ".join(fs[:20])))
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
    raw = _payload(text)
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


def _payload(text: str) -> bytes:
    # the LAST marker pair is the real one (the restore snippet above quotes the marker names)
    b = text.index("\n", text.rindex(BEGIN)) + 1
    e = text.rindex(END)
    if e < b:
        raise ValueError("payload markers out of order")
    return base64.b64decode("".join(text[b:e].split()))


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
    raw = _payload(text)
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
