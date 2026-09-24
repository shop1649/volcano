"""`shortkit doctor`: check required programs / Python packages / fonts / platform reachability.

It only *checks* and prints how to fix things.  It never claims that a login, an install or a
network permission is done unless it actually verified it.
"""
from __future__ import annotations

import argparse
import importlib
import json
import platform
import shutil
import socket
import ssl
import subprocess
import sys
import urllib.request
from dataclasses import asdict, dataclass

from . import paths

REQUIRED_PY = ["numpy", "scipy", "cv2", "PIL", "yaml", "jsonschema", "yt_dlp", "imagehash"]
OPTIONAL_PY = {
    "pytesseract": "OCR(자막·워터마크·글자 위치 측정) — pip install pytesseract + tesseract 프로그램",
    "opentimelineio": "OTIO 편집 프로젝트 내보내기 — pip install opentimelineio",
    "demucs": "효과음 카탈로그/원음 분리 — pip install demucs (torch 필요, 첫 실행 때 가중치 다운로드)",
    "torch": "demucs 실행 — pip install torch",
    "pytest": "테스트 — pip install pytest",
}
FFMPEG_FILTERS = ["ass", "subtitles", "xfade", "delogo", "zoompan", "atempo", "ebur128", "loudnorm"]
HOSTS = {
    "www.youtube.com": "레퍼런스 목록/메타데이터, YouTube 소재 검색",
    "rr1---sn-a5mekn6k.googlevideo.com": "YouTube 영상 다운로드(영상 데이터 호스트)",
    "i.ytimg.com": "썸네일",
    "www.tiktok.com": "TikTok 소재",
    "www.instagram.com": "Instagram 소재",
    "www.reddit.com": "Reddit 소재",
    "v.redd.it": "Reddit 영상 다운로드",
    "dl.fbaipublicfiles.com": "Demucs 가중치 다운로드",
    "raw.githubusercontent.com": "후보 글꼴/테스트 영상 다운로드",
    "www.googleapis.com": "YouTube Data API(선택)",
}

INSTALL_HINTS = {
    "Linux": {
        "ffmpeg": "sudo apt-get install ffmpeg", "ffprobe": "sudo apt-get install ffmpeg",
        "melt": "sudo apt-get install melt", "tesseract": "sudo apt-get install tesseract-ocr tesseract-ocr-kor",
        "fpcalc": "sudo apt-get install libchromaprint-tools", "espeak-ng": "sudo apt-get install espeak-ng",
        "fc-match": "sudo apt-get install fontconfig", "fonts": "sudo apt-get install fonts-noto-cjk fonts-noto-cjk-extra",
    },
    "Darwin": {
        "ffmpeg": "brew install ffmpeg", "ffprobe": "brew install ffmpeg", "melt": "brew install mlt (또는 Shotcut 설치 후 번들 melt)",
        "tesseract": "brew install tesseract tesseract-lang", "fpcalc": "brew install chromaprint",
        "espeak-ng": "brew install espeak-ng", "fc-match": "brew install fontconfig",
        "fonts": "brew install --cask font-noto-sans-cjk-kr",
    },
    "Windows": {
        "ffmpeg": "winget install Gyan.FFmpeg", "ffprobe": "winget install Gyan.FFmpeg",
        "melt": "Shotcut 설치(https://shotcut.org) 후 melt.exe 경로를 PATH 에 추가",
        "tesseract": "winget install UB-Mannheim.TesseractOCR (Korean 언어 데이터 선택)",
        "fpcalc": "https://acoustid.org/chromaprint 에서 fpcalc.exe", "espeak-ng": "winget install eSpeak-NG.eSpeak-NG",
        "fc-match": "(선택) fontconfig 없으면 assets/fonts 의 파일 경로로 글꼴을 찾음",
        "fonts": "Noto Sans CJK KR 설치 또는 `shortkit doctor --fetch-fonts`",
    },
}


@dataclass
class Item:
    group: str
    name: str
    required: bool
    ok: bool | None          # None = not checked
    detail: str
    fix: str = ""


def _hint(tool: str) -> str:
    return INSTALL_HINTS.get(platform.system(), INSTALL_HINTS["Linux"]).get(tool, "")


def _run(cmd: list[str], timeout: float = 20) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except FileNotFoundError:
        return 127, "not found"
    except subprocess.TimeoutExpired:
        return 124, "timeout"


def check_python() -> list[Item]:
    v = sys.version_info
    items = [Item("python", "python>=3.10", True, v >= (3, 10), platform.python_version(),
                  "Python 3.10 이상 설치")]
    for m in REQUIRED_PY:
        try:
            mod = importlib.import_module(m)
            items.append(Item("python", m, True, True, getattr(mod, "__version__", "ok")))
        except Exception as e:
            items.append(Item("python", m, True, False, f"{type(e).__name__}: {e}", "pip install -e ."))
    for m, why in OPTIONAL_PY.items():
        try:
            mod = importlib.import_module(m)
            items.append(Item("python", m, False, True, getattr(mod, "__version__", "ok")))
        except Exception:
            items.append(Item("python", m, False, False, "없음", why))
    try:
        import yt_dlp  # noqa

        ver = yt_dlp.version.__version__
        items.append(Item("python", "yt-dlp 최신성", False, None,
                          f"{ver} — YouTube/TikTok 변경에 자주 깨지므로 작업 전 `pip install -U yt-dlp` 권장"))
    except Exception:
        pass
    return items


def check_tools() -> list[Item]:
    items: list[Item] = []
    ff = shutil.which("ffmpeg")
    items.append(Item("tool", "ffmpeg", True, bool(ff), ff or "없음", _hint("ffmpeg")))
    items.append(Item("tool", "ffprobe", True, bool(shutil.which("ffprobe")), shutil.which("ffprobe") or "없음",
                      _hint("ffprobe")))
    if ff:
        rc, out = _run([ff, "-hide_banner", "-filters"])
        have = {ln.split()[1] for ln in out.splitlines() if len(ln.split()) > 2 and ln.startswith(" ")}
        for f in FFMPEG_FILTERS:
            items.append(Item("tool", f"ffmpeg filter:{f}", True, f in have, "ok" if f in have else "없음",
                              "libass/필터가 포함된 ffmpeg 빌드 필요 (" + _hint("ffmpeg") + ")"))
        rc, out = _run([ff, "-hide_banner", "-encoders"])
        items.append(Item("tool", "ffmpeg encoder:libx264", True, "libx264" in out, "ok" if "libx264" in out else "없음",
                          "libx264 포함 ffmpeg 필요"))
    melt = shutil.which("melt") or shutil.which("melt.exe")
    items.append(Item("tool", "melt", False, bool(melt), melt or "없음 — 편집 프로젝트(MLT) 렌더 검증 불가(프로젝트 생성은 됨)",
                      _hint("melt")))
    tess = shutil.which("tesseract")
    if tess:
        rc, out = _run([tess, "--list-langs"])
        items.append(Item("tool", "tesseract", True, True, tess))
        for lang in ("kor", "eng"):
            items.append(Item("tool", f"tesseract lang:{lang}", True, lang in out.split(),
                              "ok" if lang in out.split() else "없음", _hint("tesseract")))
    else:
        items.append(Item("tool", "tesseract", True, False, "없음 — 글자 위치·자막·워터마크 측정/QA 불가", _hint("tesseract")))
    for t, req, why in [("fpcalc", False, "BGM 지문(선택)"), ("espeak-ng", False, "테스트용 한국어 TTS(선택)"),
                        ("fc-match", False, "시스템 글꼴 찾기")]:
        w = shutil.which(t)
        items.append(Item("tool", t, req, bool(w), w or f"없음 — {why}", _hint(t)))
    return items


def check_fonts() -> list[Item]:
    items: list[Item] = []
    try:
        from .config import load_preset

        pr = load_preset("joshuamagazine")
        roles = pr.data["text"]["roles"]
        names = sorted({r.get("font_name") for r in roles.values() if r.get("font_name")})
    except Exception as e:
        return [Item("font", "preset", True, False, f"프리셋을 읽지 못함: {e}")]
    try:
        from .fonts import find_font  # written by the typography module
    except Exception as e:
        return [Item("font", "shortkit.fonts", True, False, f"불러오기 실패: {e}")]
    for n in names:
        p = find_font(n)
        items.append(Item("font", n, True, p is not None, str(p) if p else "없음(대체 글꼴 자동 사용 안 함)",
                          _hint("fonts") + " 또는 `shortkit doctor --fetch-fonts`"))
    return items


def check_network(timeout: float = 8.0) -> list[Item]:
    items: list[Item] = []
    ctx = ssl.create_default_context()
    for host, why in HOSTS.items():
        try:
            req = urllib.request.Request(f"https://{host}/", method="HEAD", headers={"User-Agent": "shortkit-doctor"})
            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
                code = r.status
            items.append(Item("network", host, False, True, f"HTTP {code} — {why}"))
        except urllib.error.HTTPError as e:
            # the host answered: reachable (4xx on HEAD / is normal); 403 from a proxy CONNECT shows as URLError
            items.append(Item("network", host, False, e.code < 500, f"HTTP {e.code} — {why}"))
        except (urllib.error.URLError, socket.timeout, OSError) as e:
            items.append(Item("network", host, False, False, f"접속 실패({getattr(e, 'reason', e)}) — {why}",
                              "네트워크/프록시 정책에서 이 호스트를 허용해야 함"))
    return items


def check_project() -> list[Item]:
    items = []
    try:
        root = paths.project_root()
        items.append(Item("project", "root", True, True, str(root)))
    except Exception as e:
        return [Item("project", "root", True, False, str(e), "프리셋 폴더 안에서 실행하거나 SHORTKIT_ROOT 지정")]
    local = root / "local.yaml"
    items.append(Item("project", "local.yaml", False, local.exists(),
                      "있음" if local.exists() else "없음 — local.example.yaml 을 복사해 효과음/음악 창고·쿠키 경로 지정",
                      "cp local.example.yaml local.yaml"))
    for d in ["assets/library/sfx", "assets/library/music"]:
        p = root / d
        n = len([x for x in p.glob("*") if x.is_file() and x.name != "README.md"]) if p.exists() else 0
        items.append(Item("project", d, False, n > 0, f"파일 {n}개" + ("" if n else " — 사용자 제공 자산 필요(깨끗한 원본)")))
    items.append(Item("project", "로그인/쿠키", False, None,
                      "플랫폼 로그인은 자동으로 되지 않음. 필요 시 브라우저에서 쿠키를 내보내 local.yaml 에 경로 지정"))
    return items


def check_models(load_demucs: bool = False) -> list[Item]:
    items: list[Item] = []
    try:
        from .clean import faces

        for kind in ("frontal", "profile"):
            p = faces.find_cascade(kind)
            items.append(Item("model", f"face cascade:{kind}", False, p is not None,
                              "ok" if p else "없음 — 얼굴 가림/크롭 보호 검사가 못 잼으로 남음",
                              "python -m shortkit clean fetch-models (PyPI wheel 에서 sha256 고정 XML 추출)"))
    except Exception as e:
        items.append(Item("model", "face cascade", False, False, f"확인 실패: {e}"))
    try:
        import importlib.util as ilu

        have = ilu.find_spec("demucs") is not None and ilu.find_spec("torch") is not None
        if not have:
            items.append(Item("model", "demucs(htdemucs)", False, False, "demucs/torch 미설치 — 효과음 카탈로그·원음 분리 못 잼",
                              "bash scripts/setup.sh --demucs (또는 pip install demucs)"))
        elif load_demucs:
            from .reference.separation import SeparationUnavailable, get_separator

            try:
                get_separator("demucs")._load()
                items.append(Item("model", "demucs(htdemucs)", False, True, "모델 로드 성공"))
            except SeparationUnavailable as e:
                items.append(Item("model", "demucs(htdemucs)", False, False, str(e),
                                  "dl.fbaipublicfiles.com 접속 허용 필요(첫 실행 때 가중치 다운로드)"))
        else:
            items.append(Item("model", "demucs(htdemucs)", False, None,
                              "설치됨 — 가중치 로드는 `doctor --load-demucs` 로 확인(첫 실행 때 다운로드)"))
    except Exception as e:
        items.append(Item("model", "demucs", False, False, f"확인 실패: {e}"))
    return items


def run_all(network: bool, load_demucs: bool = False) -> list[Item]:
    items = check_python() + check_tools() + check_fonts() + check_models(load_demucs) + check_project()
    if network:
        items += check_network()
    return items


def register(p: argparse.ArgumentParser) -> None:
    p.add_argument("--network", action="store_true", help="플랫폼 호스트 접속 가능 여부도 점검")
    p.add_argument("--fetch-fonts", action="store_true", help="assets/fonts/manifest.yaml 의 후보 글꼴 다운로드(sha256 검증)")
    p.add_argument("--load-demucs", action="store_true", help="demucs 가중치까지 실제로 불러와 확인(네트워크 필요할 수 있음)")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_doctor)


def cmd_doctor(args) -> int:
    if args.fetch_fonts:
        try:
            from .fonts import fetch_all

            res = fetch_all()
            print(json.dumps(res, ensure_ascii=False, indent=1, default=str))
        except Exception as e:
            print(f"글꼴 다운로드 실패: {e}")
    items = run_all(args.network, args.load_demucs)
    if args.json:
        print(json.dumps([asdict(i) for i in items], ensure_ascii=False, indent=1))
    else:
        cur = None
        for it in items:
            if it.group != cur:
                cur = it.group
                print(f"\n[{cur}]")
            mark = "OK " if it.ok else ("?  " if it.ok is None else ("NO " if it.required else "-- "))
            req = "필수" if it.required else "선택"
            print(f" {mark} {it.name:<28} ({req}) {it.detail}" + (f"\n      → {it.fix}" if (not it.ok and it.fix) else ""))
    missing = [i for i in items if i.required and i.ok is False]
    print(f"\n필수 항목 미충족: {len(missing)}개" + ("" if not missing else " — 위의 → 안내대로 설치 후 다시 실행"))
    print(f"검사 환경: {platform.system()} {platform.release()} / Python {platform.python_version()}")
    return 1 if missing else 0
