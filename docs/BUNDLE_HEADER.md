# 쇼츠 제작 프리셋 — 단일 MD 번들 (shortkit / joshuamagazine)

이 파일 하나로 다른 컴퓨터에서 프리셋 시스템(코드·설정·프리셋·출처 기록·예제 계획·문서)을 복원한다.
Claude Code 와 Codex 모두 이 파일의 **이 윗부분만** 읽고, 맨 아래 payload(base64) 본문은 읽지 않는다.

## 에이전트가 할 일 (순서)

1. 아래 "복원 명령"을 **빈 폴더**에서 실행한다(파이썬 3.10+ 만 있으면 됨, shortkit 설치 불필요). sha256 이 맞아야 풀린다.
2. 복원된 폴더로 이동해 `AGENTS.md` 를 읽는다(공통 지침: 절대 규칙, 실행 순서, 파일 지도). `CLAUDE.md` 는 `AGENTS.md` 를 불러온다.
3. 초기 설정: `bash scripts/setup.sh` (Ubuntu 는 `--with-apt`, macOS 는 `--with-brew`, Windows 는 `scripts/setup.ps1` — 미검증).
   이 스크립트는 로그인·쿠키·API 키를 만들어 주지 않는다. 설치가 저절로 끝났다고 가정하지 말고 `python -m shortkit doctor --network`
   결과를 확인한다.
4. `PROGRESS.md` 의 재개 지점부터 진행한다. 현재 프리셋 스타일 값은 전부 **임시값(못 잼)** 이며, 네트워크가 열린 환경에서
   `AGENTS.md` 5장 A(레퍼런스 분석)를 먼저 실행해야 production 제작이 가능하다.

## 번들에 없는 것 (복원 후 받거나 만들 것)

- 영상·음원·이미지·글꼴 파일(용량): 후보 글꼴은 `python -m shortkit doctor --fetch-fonts`(sha256 고정),
  테스트 자산은 `python -m shortkit testassets synth` / `fetch-video` / `dirty-source`.
- 레퍼런스 영상(`ref download`), 소재 원본(`source download`), 사용자 효과음·음악 창고(`assets/library/`).
- 얼굴 검출 모델(QA 필수): `python -m shortkit clean fetch-models` (setup.sh 가 실행).
- 캐시(`warehouse/cache/`), 레퍼런스 분석 중간 파일(프레임·stem·렌즈 키프레임), 로그인 쿠키·local.yaml(보안상 번들 제외).
- 렌더 결과 MP4 와 편집 프로젝트의 미디어 폴더는 `python -m shortkit episode all <id>` 로 다시 만든다.
- 테스트(`pytest`) 전에 테스트 자산을 만든다: `python -m shortkit testassets synth && python -m shortkit testassets fetch-video
  && python -m shortkit episode test-source && python -m shortkit testassets dirty-source`.
