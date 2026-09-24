# AGENTS.md — 쇼츠 제작 프리셋 시스템 (Claude Code · Codex 공통 지침)

이 파일은 Claude Code(`CLAUDE.md` 가 이 파일을 불러옴)와 Codex(`AGENTS.md` 를 직접 읽음)가 **같은 규칙**으로
작업하도록 만든 공통 지침이다. 사람이 읽어도 된다.

## 1. 무엇을 하는 저장소인가

레퍼런스 채널 <https://youtube.com/@joshuamagazine> 의 **편집 구조**를 그대로 따르되 **다른 촬영본**으로 쇼츠를 만드는
재사용 가능한 제작 시스템이다.

```
새 소재 탐색 → 선별 → 대본·컷 구성(plan.yaml) → 편집(렌더 + 편집 프로젝트) → 출력 검수(최종 MP4 기준 QA)
```

구성: 파이썬 패키지 `shortkit`(명령: `python -m shortkit <영역> <명령>`), 채널 프리셋 `presets/joshuamagazine/`,
소재 창고 `warehouse/`, 에피소드 `episodes/<id>/`, 인터페이스 계약 `docs/CONTRACT.md`.

## 2. 현재 상태 — 먼저 읽을 것

- **레퍼런스 측정값이 아직 하나도 없다.** 2026-09-24 첫 작업 환경의 네트워크 정책이 youtube.com / googlevideo.com /
  i.ytimg.com / tiktok / instagram / reddit / Google Lens / Demucs 가중치 호스트를 차단했다(`PROGRESS.md`,
  `presets/joshuamagazine/unresolved.md`, `presets/joshuamagazine/reference/latest100.json` 의 blocker 기록).
- 그래서 `presets/joshuamagazine/preset.yaml` 의 스타일 값은 전부 **임시값(provisional)** 이다. 레지스트리
  (`settings_registry.yaml`)에서 상태가 `unmeasured`(못 잼)이다. production 렌더와 QA 최종 관문은 이 상태에서 통과하지 않는다.
- 파이프라인 자체(렌더·편집 프로젝트·QA·분석기·소재 창고·로고 제거)는 합성/공개 테스트 소스로 실제 실행해 검증했다.
  검증 범위는 `docs/VALIDATION.md`.
- 네트워크가 열린 컴퓨터에서 아래 **5장 A → B → C** 순서대로 실행하면 미측정 항목이 채워진다.

## 3. 절대 규칙 (사용자 요구사항 — 위반 시 작업 실패)

1. 접근·측정하지 못한 항목을 추측으로 채우거나 완료라고 하지 않는다. `못 잼` 으로 두고 제작 영향과 해결 상태를 기록한다.
2. 기준 표본: 분석 시점의 **최신 100편**을 `reference/latest100.json` 에 고정(목록·게시일). 전체 영상은 참고이며 충돌 시 최신 100편 우선.
   조회수 80만 이상 영상은 `reference/high_views.json` 으로 전부 분석한다.
3. 수치 항목은 전체 및 포맷별 p10/p50/p90 + 표본 수. 좌표는 해상도와 함께 저장.
4. 모션·전환·BGM·원음은 있다/없다/못 잼.
5. 모든 설정은 "근거 영상·시각 → 측정값 → 제작 코드의 설정 → 출력 검사"로 연결된다. `shortkit preset audit` 이 연결되지 않은
   설정(보고서에만 있는 값)을 잡아낸다. 고정 스타일(preset)과 새 소재마다 다시 판단할 좌표·시각(plan)을 분리한다.
6. 소재는 반드시 레퍼런스와 **다른 촬영본**. 원 채널의 채널명·로고 등 고유 식별 요소는 복제하지 않는다
   (`identity_exclusions`, QA 가 OCR 로 검사). 다른 프로젝트의 프리셋을 섞지 않는다(`preset_id` 가드).
7. 사용자가 별도로 지정한 변경은 `requested_changes.yaml` 에만 넣는다. QA 표에서 "의도한 변경"과 "미재현 결함"을 구분한다.
   (2026-09-24 요청문에는 별도 변경이 비어 있었다.)
8. 자막: 장면을 실제로 보고 들은 뒤 작성. 짧고 자연스러운 한국어. 영상에 없는 관계·동기·대사 금지(`grounding` 필수).
   역할 구분: 제목 / 설명 / 상황 설명 / 인물 식별 / 실제 대사 / 반응·효과. 반전을 미리 말하지 않는다(`reveal` 가드).
   얼굴·손·핵심 물체를 가리지 않는다(`protected`). 의미가 끝난 꼬리는 자르되 중요한 동작은 자르지 않는다.
   같은 효과를 연속으로 쌓거나 분량을 채우려 반복하지 않는다.
9. BGM: 곡명·버전·속도·실제 사용 구간까지 확인(같은 곡의 다른 부분은 불일치). 깨끗한 음악 파일만 사용(레퍼런스에서 분리한 음원 금지).
10. 원본 소리는 기본 OFF. 중요한 대사·말하는 구간만 살린다. 원본에 붙은 음악은 분리 후 음질 검사. 덕킹은 보존한 대사 구간에서만.
    효과음이나 컷은 덕킹 이유가 아니다. **직접 듣지 못했으면 청취 검수 완료라고 하지 않는다**(에이전트는 소리를 듣지 못한다 —
    자동 측정 결과와 "사람 청취 필요"를 구분해 적는다).
11. 효과음은 사건 때문에 넣는다(컷 때문이 아님). 사건 없는 효과음 0개, 사건과 ±0.3초 이내, 편당 개수·종류 분포는 포맷 관측 범위.
12. 원본 로고·출처 오버레이·원어 자막은 최종 화면에 남기지 않는다(상단 좌우·내부 컷 검사). 순서: 깨끗한 원본 → 크롭 → 국소 복원.
    로고 때문에 인물·동작을 잘라내지 않는다. 출처 기록은 따로 보존.
13. 첫 편만 기획(소재·구간 시트·표지 문구·제목 후보 3종·효과음 배치표)을 제시하고 **승인 뒤 렌더**. 승인된 기획·수정은 재승인 불요.
    첫 편에서 확인된 수정은 프리셋과 후속편에 함께 반영. 이후는 지정 포맷·편수까지 불필요한 질문 없이 완료.
14. 검수는 최종 MP4 기준. 레퍼런스 1편과 같은 절대 시각 1초 격자 비교, 자막 띠 아래 0.5초 효과음 띠. 같다/다르다/못 잼.
    못 잰 항목은 완료로 승격하지 않는다. 결함마다 고침·동일 사례 재검사·최종 관문 결과를 남긴다.
15. 플랫폼 접근이 막히면 성공한 척하지 말고 다른 경로로 소재 확보를 계속한다. 차단을 우회(미러·프록시 등)하지 않는다.
16. 컨텍스트가 차기 전에 `PROGRESS.md` 에 진행 기록과 재개 지점을 쓰고 커밋한다.

## 4. 초기 설정

```bash
bash scripts/setup.sh            # Linux/macOS: .venv + 파이썬 의존성 + 글꼴 받기 + doctor
#   --with-apt (Ubuntu) / --with-brew (macOS) 로 시스템 프로그램 설치, --demucs 로 효과음 카탈로그용 demucs 설치
powershell -File scripts/setup.ps1   # Windows (미검증)
python -m shortkit doctor --network  # 필수 프로그램·의존성·글꼴·플랫폼 접속 점검 (로그인은 자동으로 되지 않음)
cp local.example.yaml local.yaml     # 효과음/음악 창고, 쿠키 경로
```

필수: Python ≥3.10, ffmpeg/ffprobe(libass, libx264), tesseract + kor. 선택: melt(편집 프로젝트 렌더 검증), demucs+torch
(효과음 카탈로그), fpcalc, espeak-ng(테스트 TTS).

## 5. 실행 순서

(명령 상세는 각 `python -m shortkit <영역> -h`.)

### A. 레퍼런스 분석 (네트워크 필요)

<!-- COMMANDS-A -->

### B. 새 소재 창고

<!-- COMMANDS-B -->

### C. 에피소드 제작 (첫 편 승인 → 후속편)

<!-- COMMANDS-C -->

## 6. 파일 지도

<!-- FILEMAP -->

## 7. 재개

- `PROGRESS.md` 의 마지막 [진행] 단계부터. `git log --oneline` 으로 마지막 커밋 확인.
- 미확정 항목 현황: `python -m shortkit preset unresolved` → `presets/joshuamagazine/unresolved.md`.
