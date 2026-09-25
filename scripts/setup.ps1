# shortkit 초기 설정 (Windows PowerShell). 미검증 환경 — 이 스크립트는 Windows 에서 실행해 보지 않았다.
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
# 시스템 프로그램(ffmpeg, tesseract+Korean, melt(Shotcut), chromaprint)은 winget 으로 직접 설치:
#   winget install Gyan.FFmpeg
#   winget install UB-Mannheim.TesseractOCR      (설치 중 Korean 언어 데이터 선택)
#   Shotcut 설치 후 melt.exe 가 있는 폴더를 PATH 에 추가
# 로그인·쿠키·API 키는 자동으로 만들어지지 않는다.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
$py = if ($env:PYTHON) { $env:PYTHON } else { "python" }
& $py -c "import sys; assert sys.version_info >= (3,10), 'Python 3.10+ required'"
if (-not (Test-Path .venv)) { & $py -m venv .venv }
& .\.venv\Scripts\python.exe -m pip install -U pip
& .\.venv\Scripts\python.exe -m pip install -e ".[ocr,otio,test]"
& .\.venv\Scripts\python.exe -m pip install -U yt-dlp
if (-not (Test-Path local.yaml)) { Copy-Item local.example.yaml local.yaml }
& .\.venv\Scripts\python.exe -m shortkit doctor --fetch-fonts
& .\.venv\Scripts\python.exe -m shortkit clean fetch-models
& .\.venv\Scripts\python.exe -m shortkit doctor --network
Write-Host "다음: .\.venv\Scripts\Activate.ps1 후 AGENTS.md 의 '실행 순서'를 따르세요."
