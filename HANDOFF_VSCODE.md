# 내 PC(VS Code + Claude Code)에서 이어서 작업하기

클라우드 작업 환경에서는 YouTube 가 서버 IP 를 "로봇이 아님을 확인하려면 로그인하세요"로 막아서 레퍼런스 영상을 받지 못했다.
집·사무실 PC 는 보통 이 확인에 걸리지 않고, `W:\내 드라이브\효과음` 도 바로 읽을 수 있다. 그래서 여기서 이어서 한다.

---

## 0. 지금 상태 (2026-10-01)

| 항목 | 상태 |
|---|---|
| 제작 시스템(렌더·편집 프로젝트·검수·번들) | **완성·검증됨** (테스트 993개 통과, 깨끗한 폴더 복원 2회 검증) |
| 채널 목록 | 510편 목록 고정. 최신 100편 고정(그중 80편은 게시일·조회수 메타데이터가 봇 확인에 막혀 비어 있음) |
| 조회수 80만 이상 | 198편 확정, 124편 미확인(같은 이유) |
| 레퍼런스 영상 받기·분석 | **아직 0편** — 이 PC 에서 시작 |
| 효과음 창고 | 아직 연결 안 됨 — 이 PC 의 `W:\내 드라이브\효과음` 을 연결 |
| 새 소재·첫 편 | 레퍼런스 분석 뒤 |

자세한 진행 기록: `PROGRESS.md` · 에이전트 규칙: `AGENTS.md` (Claude Code 는 `CLAUDE.md` 를 통해 자동으로 읽음)

---

## 1. 준비 — 둘 중 하나

### 방법 A (권장): WSL2 Ubuntu
검증한 환경(Ubuntu 24.04)과 같아서 가장 안전하다.

1. PowerShell(관리자)에서 `wsl --install -d Ubuntu-24.04` → 재부팅 → Ubuntu 사용자 만들기
2. VS Code 에 **WSL** 확장 설치 → 왼쪽 아래 `><` 버튼 → "Connect to WSL"
3. Ubuntu 터미널에서:
   ```bash
   sudo apt-get update && sudo apt-get install -y git python3-venv unzip
   ```
4. 구글 드라이브(W:) 를 WSL 에서 보이게 하기(재부팅마다 한 번):
   ```bash
   sudo mkdir -p /mnt/w && sudo mount -t drvfs W: /mnt/w
   ls "/mnt/w/내 드라이브/효과음" | head     # 효과음 파일이 보이면 성공
   ```
   마운트가 안 되면(구글 드라이브 가상 드라이브는 PC 에 따라 안 될 수 있음): 탐색기에서 `효과음` 폴더를
   `C:\shortkit_sfx` 로 복사한 뒤 `/mnt/c/shortkit_sfx` 를 쓴다.

### 방법 B: Windows 에 바로 설치 (미검증)
`scripts/setup.ps1` 은 Windows 에서 실행해 본 적이 없다. 문제가 생기면 방법 A 로.
```powershell
winget install Python.Python.3.11 Git.Git Gyan.FFmpeg UB-Mannheim.TesseractOCR DenoLand.Deno
# Tesseract 설치 중 "Additional language data" 에서 Korean 선택
```

---

## 2. 코드 받기

이 저장소는 비공개이므로 GitHub 에 로그인된 상태여야 한다(처음 clone 할 때 로그인 창이 뜸).
```bash
git clone -b claude/youtube-preset-system-etbnh9 https://github.com/shop1649/volcano.git
cd volcano
```
(git 이 어려우면: 저장소의 `PRESET_BUNDLE.md` 하나만 받아서 맨 위 복원 명령을 실행해도 된다. 단 커밋 이력은 없다.)

---

## 3. 설치

### WSL(방법 A)
```bash
bash scripts/setup.sh --with-apt --demucs     # 시스템 프로그램 + 파이썬 의존성 + 글꼴 + Demucs(CPU) — 처음 한 번, 10~30분
source .venv/bin/activate
curl -fsSL https://deno.land/install.sh | sh  # YouTube 추출용 JS 런타임(yt-dlp 권장)
python -m shortkit doctor --network           # "필수 항목 미충족: 0개" 확인
```

### Windows(방법 B)
```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
.\.venv\Scripts\python.exe -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install demucs
.\.venv\Scripts\Activate.ps1
python -m shortkit doctor --network
```

---

## 4. 이 PC 전용 설정 — `local.yaml`

`setup` 이 `local.example.yaml` 을 `local.yaml` 로 복사해 둔다(`local.yaml` 은 git 에 올라가지 않음). 이렇게 고친다:

```yaml
# WSL(방법 A)
sfx_library_root: "/mnt/w/내 드라이브/효과음"
# Windows(방법 B) 라면 대신:
# sfx_library_root: "W:/내 드라이브/효과음"

music_library_root: assets/library/music     # 깨끗한 BGM 원본이 있으면 여기에 + index.yaml (assets/library/music/README.md)
```

### YouTube 가 이 PC 에서도 "로봇 확인"을 띄울 때만
1. 크롬에서 YouTube 로그인(부계정 권장) → "Get cookies.txt LOCALLY" 확장으로 youtube.com 쿠키 내보내기
2. 파일을 프로젝트의 `cookies/youtube.txt` 로 저장(이 폴더는 git·번들에서 제외됨)
3. `local.yaml` 의 `sourcing.cookies.youtube: cookies/youtube.txt`, 명령에는 `--cookies cookies/youtube.txt`
4. 작업이 끝나면 그 브라우저에서 로그아웃(쿠키 무효화)

---

## 5. Claude Code 시작

설치(공식 안내: <https://code.claude.com/docs>):
- WSL/macOS/Linux: `curl -fsSL https://claude.ai/install.sh | bash`
- Windows PowerShell: `irm https://claude.ai/install.ps1 | iex`

VS Code 터미널에서 프로젝트 폴더(`volcano`)로 이동한 뒤 `claude` 실행. 그리고 아래를 **그대로 붙여 넣는다**:

```text
PROGRESS.md 와 HANDOFF_VSCODE.md 를 읽고 이어서 진행해. 지금 PC 는 YouTube 접속이 되는 내 컴퓨터야.
1) AGENTS.md 5장 A(레퍼런스 분석)를 처음부터 끝까지 실행해:
   ref collect(빠진 80편 메타데이터·80만+ 미확인 124편 다시 확인) → ref download(latest100, high_views)
   → audio-analyze → analyze → identity-templates → classify prepare → (네가 review 자료를 직접 보고) format_labels.csv
   → classify build → fonts → aggregate → sfx-catalog → sfx-map(local.yaml 의 효과음 창고) → audio-measure
   → manual 관찰 → trace → high-views-report → apply-measurements → sync → audit → unresolved.
2) 그다음 5장 B(소재 창고)와 C(첫 편 기획안)까지 하고, 첫 편 기획안을 나한테 보여 주고 승인을 기다려.
규칙: 못 잰 것은 못 잼으로 두고, 단계마다 PROGRESS.md 갱신·커밋·푸시. 소리는 기계 측정만이고 청취 확인은 내가 한다.
```

---

## 6. 무엇이 얼마나 걸리나 (대략, CPU 기준)

| 단계 | 시간 | 누가 |
|---|---|---|
| 영상 받기(최신 100 + 80만 이상, 약 300편) | 1~2시간 | Claude Code |
| 음성 분리(Demucs)·화면 분석 | 6~10시간 | Claude Code (PC 를 켜 둘 것) |
| 포맷 분류(프레임을 보고 라벨) → 측정값 확정 | 2~3시간 | Claude Code |
| 새 소재 찾기 + **첫 편 기획안** | 3~4시간 | Claude Code |
| 기획안 승인 | 몇 분 | **당신** |
| 렌더·편집 프로젝트·검수 | 편당 약 1시간 | Claude Code |
| 청취·시청 확인(BGM·대사·반전·로고 코너) | 편당 몇 분 | **당신** — 최종 MP4 를 보고 듣고 `python -m shortkit qa human-check --episode <id> --row <검사 행> --kind listen\|watch --verdict same\|different --by <이름> --note "..."` |

---

## 7. 막힐 때

| 증상 | 할 일 |
|---|---|
| YouTube "Sign in to confirm you're not a bot" | 4절의 쿠키 방법 |
| `No supported JavaScript runtime` 경고 | Deno 설치(3절) |
| Instagram `login_required` | `cookies/instagram.txt` 를 같은 방법으로 → `local.yaml` 의 `sourcing.cookies.instagram` |
| Reddit 403 | Reddit 은 건너뛰고 다른 플랫폼 또는 `source add-url`(직접 찾은 URL) |
| TikTok 키워드 검색 0건 | yt-dlp 의 TikTok 태그 검색 자체가 고장. @계정·영상 URL 로 검색하거나 `source add-url` |
| 효과음이 `없음`으로만 나옴 | `local.yaml` 의 `sfx_library_root` 경로 확인(WSL 은 `/mnt/w` 마운트 먼저) |
| 디스크 부족 | 영상 300편 ≈ 1.5GB + 분리 음원 ≈ 4GB + torch ≈ 1GB. 여유 15GB 이상 권장 |

결과는 같은 브랜치(`claude/youtube-preset-system-etbnh9`)에 커밋·푸시된다. 영상·쿠키·분리 음원은 git 에 올라가지 않는다(`.gitignore`).
