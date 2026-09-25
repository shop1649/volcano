#!/usr/bin/env bash
# shortkit 초기 설정 (Linux / macOS). 검증: Ubuntu 24.04. macOS 는 미검증.
#   bash scripts/setup.sh              # 가상환경 + 파이썬 의존성 + 점검
#   bash scripts/setup.sh --with-apt   # (Debian/Ubuntu) 시스템 프로그램까지 apt 로 설치 (sudo 필요)
#   bash scripts/setup.sh --with-brew  # (macOS) Homebrew 로 시스템 프로그램 설치
#   bash scripts/setup.sh --demucs     # 효과음 카탈로그용 demucs/torch 설치(수 GB)
# 이 스크립트는 로그인·쿠키·API 키를 대신 만들지 않는다.
set -euo pipefail
cd "$(dirname "$0")/.."

WITH_APT=0; WITH_BREW=0; DEMUCS=0
for a in "$@"; do
  case "$a" in
    --with-apt) WITH_APT=1 ;;
    --with-brew) WITH_BREW=1 ;;
    --demucs) DEMUCS=1 ;;
    *) echo "unknown option $a"; exit 2 ;;
  esac
done

if [ "$WITH_APT" = 1 ]; then
  sudo apt-get update
  sudo apt-get install -y ffmpeg melt tesseract-ocr tesseract-ocr-kor tesseract-ocr-eng fontconfig \
    fonts-noto-cjk fonts-noto-cjk-extra fonts-nanum libchromaprint-tools espeak-ng python3-venv xvfb
fi
if [ "$WITH_BREW" = 1 ]; then
  brew install ffmpeg mlt tesseract tesseract-lang chromaprint espeak-ng fontconfig
  brew install --cask font-noto-sans-cjk-kr || true
fi

PY=${PYTHON:-python3}
"$PY" -c 'import sys; assert sys.version_info >= (3,10), "Python 3.10+ 필요"'
if [ ! -d .venv ]; then "$PY" -m venv .venv; fi
# shellcheck disable=SC1091
. .venv/bin/activate
python -m pip install -U pip
python -m pip install -e ".[ocr,otio,test]"
python -m pip install -U yt-dlp
if [ "$DEMUCS" = 1 ]; then
  python -m pip install demucs
fi
[ -f local.yaml ] || cp local.example.yaml local.yaml

echo
echo "== 후보 글꼴 받기(sha256 검증) =="
python -m shortkit doctor --fetch-fonts 2>&1 | grep -E '"(status|file|error)"|fail|실패' || true
echo
echo "== 얼굴 검출 모델(Haar, sha256 고정) =="
python -m shortkit clean fetch-models || echo "경고: 얼굴 검출 모델을 받지 못함 — QA 얼굴 가림 검사가 못 잼으로 남음"
echo
echo "== 점검 =="
python -m shortkit doctor --network || true
echo
echo "다음: source .venv/bin/activate 후 AGENTS.md 의 '실행 순서'를 따르세요."
