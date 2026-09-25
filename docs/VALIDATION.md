# 검증 기록 — 무엇을 실제로 돌려 봤고 무엇을 못 했나

이 문서는 **실제로 실행한 것만** 적는다. 적혀 있지 않으면 확인하지 않은 것이다.
소리는 전부 기계 측정이다. **사람이 직접 보고 들어서 확인한 것은 없다**(에이전트는 소리를 듣지 못함 → "사람 청취 필요").

## 0. 요약

| 영역 | 실제로 돌려 봄 | 결과 | 검증 못 함 |
|---|---|---|---|
| 레퍼런스 채널 분석(최신 100편·80만 이상 전편) | 수집 시도(`ref collect`) | **차단**(yt-dlp 403). 측정값 0개 | 실제 채널 영상 전부 |
| 레퍼런스 분석기(컷·자막·모션·장식·오디오·글꼴·분류) | 참값을 아는 **합성** 레퍼런스 5편(mockloop) | 222키 중 pass 153 · 방법 한계 fail 11 · 오탐 0(측정 시점 주의, 3절) | 실제 채널 영상의 잡음·압축·다양한 글꼴 |
| 렌더(마스터 MP4) | 테스트 에피소드 3편 | 렌더·글꼴 선택 검사·음량·true peak 통과 | production 모드(프리셋 미측정이라 거부됨) |
| 편집 프로젝트 MLT | melt 로 실제 렌더해 마스터와 1초 격자 비교 | SSIM 0.99 이상, 소리 포락선 상관 0.99 이상 | Shotcut·Kdenlive GUI 로 열어 보기 |
| 편집 프로젝트 FCPXML / OTIO | 형식·시간 일관성 테스트, OTIO 쓰기→읽기 왕복 | 테스트 통과 | Resolve·Final Cut Pro·OTIO 지원 편집기로 가져오기(**못 잼**) |
| 출력 QA(최종 MP4 기준) | 테스트 에피소드 3편 + 일부러 망가뜨린 편(test-qa-bad) | 다르다 0(좋은 편), 망가뜨린 편은 관문 실패 | 레퍼런스 실물과 같은 시각 비교(레퍼런스 없음) |
| 로고·오버레이 제거 | 로고·출처 표시·원어 자막을 합성해 넣은 소스(`dirty-source`) | 검출 → 크롭/국소 복원 → 잔류 검사: 워터마크·영어 자막 잔류 0. 단, 자막 자리 복원이 걸어오는 사람의 손을 번지게 함 → 이제 validate 경고 + QA 사람 확인 필수 행 | 실제 플랫폼 워터마크, 복원 흔적의 자동 판정 |
| 소재 창고(플랫폼 검색·다운로드) | 접속 시도(차단 기록) + **합성 픽스처** 단위 테스트 | 차단 상태를 정직하게 기록 | YouTube·TikTok·Instagram·Reddit **실제 접속** |
| Demucs 분리 | 설치·가중치 받기 불가 | 분리기 없음을 알리는 경로만 테스트 | 실제 분리(효과음 카탈로그·BGM 음원·보컬 품질) |
| 단일 MD 번들 | 빈 폴더에 복원 → 설치 → 점검 → 새 에피소드 → 테스트 | 4절 | macOS·Windows |

## 1. 검증한 환경 (하나뿐)

| 항목 | 값 |
|---|---|
| OS | Ubuntu 24.04.4 LTS (클라우드 컨테이너), x86_64, CPU 4개, **GPU 없음** |
| Python | 3.11.15 |
| ffmpeg / ffprobe | 6.1.1-3ubuntu5 (libass, libx264) |
| tesseract | 5.3.4 (kor, eng) |
| melt | 7.22.0 (qtcrop 때문에 `xvfb-run` 으로 실행) |
| 그 밖 | fpcalc 1.5.1, espeak-ng 1.51, sox 14.4.2, Noto Sans CJK KR |
| 파이썬 패키지 | numpy 2.4.6, opencv 5.0.0, scipy 1.17.1, pillow 12.3.0, PyYAML 6.0.1(libyaml 없음 → 순수 파이썬 로더로 동작), jsonschema 4.26.0, yt-dlp 2026.08.19, opentimelineio 0.18.1 |
| 설치 안 됨 | torch, demucs(가중치 호스트 차단), faster-whisper |
| 네트워크 | youtube.com, googlevideo.com, i.ytimg.com, tiktok.com, instagram.com, reddit.com, lens.google.com, dl.fbaipublicfiles.com(Demucs 가중치), huggingface.co, archive.org 등이 정책으로 403. github.com 의 git clone, pypi, Ubuntu apt 는 허용. GitHub 의 `raw/` 파일 직접 받기(`testassets fetch-video`)도 403 → git clone 한 폴더를 `--local-dir` 로 넘겨서 받음. `www.googleapis.com`(YouTube Data API v3)은 접속되지만 API 키가 없어 403 PERMISSION_DENIED — 키가 있으면 `ref collect --method api` 로 목록·조회수는 받을 수 있음(영상은 못 받음) |

### 검증하지 않은 환경

- **macOS**(`setup.sh --with-brew`), **Windows**(`scripts/setup.ps1`): 한 번도 실행하지 않음.
- 다른 리눅스 배포판, Python 3.10 / 3.12 이상, GPU(Demucs CUDA).
- `setup.sh --with-apt`: 이번 복원에서는 실행하지 않음. 이 컨테이너에는 필요한 시스템 프로그램이 이미 있었다. apt 패키지 목록은
  이 컨테이너에 설치된 이름과 맞춰 두었지만 빈 시스템에서 설치해 보지는 않았다.
- `setup.sh --demucs`(torch·demucs 설치, 가중치 받기).
- 편집 프로그램: Shotcut·Kdenlive GUI, DaVinci Resolve, Final Cut Pro.

## 2. 테스트 에피소드 (저장소에 커밋된 결과)

모두 `mode: test` 다. 공개(CC BY 4.0) Intel 샘플 영상 + 합성 소리(espeak-ng TTS, 생성한 음악·효과음)를 쓴 **파이프라인 검증용**이며
게시용이 아니다. 프리셋이 미측정(임시값)이라 관문은 "통과했어도 완료 아님"이다.

| 에피소드 | 길이 | QA 행 | 같다 / 다르다 / 못 잼 | 관문 | MLT(melt) 대조 |
|---|---|---|---|---|---|
| test-pipeline-001 | 19.25 s | 273 | 184 / 0 / 89 | 통과, 완료 아님(P1 미측정 키 266, R1 레퍼런스 비교 없음) | SSIM 0.9975(최저 1초 0.9939), 소리 상관 0.9966, 프레임 578/578 |
| test-coverage-001 | 22.5 s | 226 | 151 / 0 / 75 | **실패**: G2 필수 못 잼 6건 — `caption.reveal`(사람의 시청 기록 필요), people-detection 소스의 글자 없는 로고 검사 5건(고정 카메라: 사람이 코너 캡처 확인) | SSIM 0.9923(최저 1초 0.9797), 소리 상관 0.9999, 프레임 675/675 |
| test-restore-001 (깨끗한 폴더 복원에서 만든 편) | 18.50 s | 249 | 164 / 0 / 85 | **실패**: G2 필수 못 잼 12건 — 반전 1, 두 소스의 글자 없는 로고 검사 10, **국소 복원이 걸어오는 남성의 손을 덮음 1**(에이전트가 출력 2.5–3.3 s 에서 번짐을 봄; 사람 판정 필요) | SSIM 0.9942(최저 1초 0.9885), 소리 상관 0.9998, 프레임 555/555 |
| test-qa-bad (git 제외, 테스트가 다시 만듦) | — | — | 결함을 일부러 넣음 | 실패(G1 15건) — 검사가 결함을 잡는지 확인 | — |

- 렌더 전 검사: libass 가 요청한 글꼴을 실제로 골랐는지 확인(`fontselect`)하고, 다르면 렌더를 거부한다. 2026-09-25 에 후보 글꼴 19종으로 통과했다.
- 음량: 출력 MP4 에서 통합 음량(LUFS)과 true peak 를 잰다. AAC 첫 프레임 오버슈트는 시험 인코딩과 1024샘플 시작 경사로 막는다.
- 결함 기록(`qa/defects.jsonl`): 결함마다 고침 → 같은 사례 재검사 → 최종 관문. 고친 기록과 재검사가 없으면 "고침"으로 올리지 않는다.
  - test-restore-001: 결함 22건 중 10건 고침 확인(고침 기록 + 다른 에피소드 같은 검사 재확인), 12건 열림(위 G2 12건).
  - test-pipeline-001 에는 2026-09-24 QA 모듈을 만드는 도중(커밋 d00f780–986568e)에 닫힌 결함 41건이 **"고침 기록 없이 해소"**
    상태로 남아 있다. 그때는 고침 기록을 요구하지 않았고, 결함마다 무엇을 고쳤는지 기록이 없다. 그래서 "고침"으로 바꾸지 않았다.
    같은 행은 매 QA 실행에서 다시 측정되며, 지금은 다르다 0 이다.
- 이 표의 수치는 커밋 d9b6b63 이후 코드로 다시 잰 것이다. 1차 복원 때 번들 안의 옛 코드는 test-restore-001 에서 다르다 2
  (둘 다 QA 오탐)를 냈다.

## 3. 합성 레퍼런스 고리 (mockloop)

`docs/validation/mockloop.md`. 참값을 아는 프리셋(`mocktruth`)으로 렌더한 5편을 "레퍼런스"로 등록했다.
분석기 → 측정(n/p10/p50/p90) → `preset apply-measurements` → 렌더 → `qa run --reference`(레퍼런스와 같은 절대 시각 1초 격자) 순서로
끝까지 돌렸다.

- 결과: 키 222개 중 **pass 153 / fail 11(모두 방법 한계로 원인 확인) / 못 잼 30 / 참값에 없음 28 / 오탐 0**.
- 닫힌 고리 QA: 레퍼런스와 같은 시각 비교까지 돌아감(`docs/validation/mockloop_compare_sheet_p01.png`).
- **측정 시점 주의**: 이 수치는 커밋 c8d90e7 시점의 분석기로 잰 것이다. 그 뒤 적대적 검토에서 분석기가 여러 번 바뀌었다
  (그림자 추정기 공용화 — 레퍼런스 그림자가 항상 0으로 나오던 결함 수정, 대사 lead_s 부호 통일, 컷 구조·정보 공개 순서 추가 등).
  바뀐 분석기로 이 표를 다시 재지는 않았다. 바뀐 부분은 각 단위 테스트로만 확인했다. 실제 레퍼런스로 A 단계를 돌릴 때 새로 잰 값이 기준이다.
- 한계: 레퍼런스가 우리 렌더러의 출력이므로 글꼴·압축·배경이 실제 채널보다 쉽다. 허용 오차도 합성 렌더에서만 확인했다
  (`docs/CONTRACT.md` 의 허용 오차 절). 실제 레퍼런스를 받으면 잡음에 맞춰 다시 확인해야 한다.

## 4. 단일 MD 번들 → 깨끗한 폴더 복원 → 새 에피소드

(기록: `docs/validation/final_restore_log.md` — 명령·종료 코드·출력 원문)

### 1차 (커밋 17e4e0a 의 번들)

- 복원: 빈 폴더에 MD 하나만 두고, MD 가 읽으라는 1–391 행 안의 bash 블록을 수정 없이 실행했다.
  - 파일 323개가 sha256 일치로 풀렸다. 저장소 파일과 바이트 단위로 같다.
- `setup.sh` 종료 0. `doctor --network` 필수 미충족 0.
- 테스트 자산: `fetch-video` 가 GitHub 파일 직접 받기에서 403 이었다. git clone 폴더(`--local-dir`)로 받았다.
- 새 에피소드 test-restore-001: 소스는 예제가 쓰지 않은 파일이다.
  - 로고·출처 표시·영어 자막·음악·말소리를 합성한 `dirty_source_facewalk`.
  - people-detection 의 다른 구간.
- 흐름: clean detect → clean plan(inpaint 3건) → plan v1–v4 → render → export → melt 대조 → QA.
- 결과:
  - 렌더 −14.4 LUFS / −1.7 dBTP.
  - MLT melt 대조 통과: SSIM 0.9942, 소리 상관 0.9998, 프레임 555/555.
  - 원본 워터마크·영어 자막 잔류 0.
- 이 실행이 찾은 문제 7가지는 모두 고쳤다(`docs/validation/final_restore_log.md` 6절).
  - QA 오탐 2: 걸어오는 사람 때문에 줌을 잘못 잼, 정지 구간 때문에 속도를 잘못 잼.
  - 깨끗한 복원에서 실패하던 테스트 7개.
  - **국소 복원이 보호 영역(손)을 덮는 것을 잡는 검사가 없었음**: 출력에서 손이 번졌다.
  - validate 오경고 1.
  - `dirty-source` 출력 이름 고정.
  - mockloop 스크립트가 번들에서 빠짐.
- 같은 MP4 를 고친 코드로 다시 QA 한 결과는 2절 표에 있다.

### 2차 (고친 번들)

(2차 복원 결과 — 아래에 기록)

## 5. 프리셋 연결 감사

`python -m shortkit preset audit --test` (2026-09-25):

- 레지스트리 설정 313개: 미측정 266 · 해당 없음 28 · 규칙으로 고정 14 · 조건부 해당 없음 5
- **no_code 0, no_qa 0**: 모든 스타일 설정이 제작 코드에서 실제로 읽히고(추적된 접근 기록) 출력 검사 행에 연결된다.
  보고서에만 있는 설정은 없다.
- 미측정 266개는 전부 레퍼런스 차단 때문이다. production 렌더와 `qa gate --production` 은 이 상태에서 통과하지 않는다.

## 6. 사람이 해야 하는 확인 (에이전트가 할 수 없음)

- **청취**: BGM 곡·버전·구간, 덕킹, 살린 대사, 효과음. 전부 기계 측정만 있다.
- **시청**: 포맷 라벨(`format_labels.csv`), 효과음 감정(`sfx_emotion_labels.csv`), 수동 관찰(`manual_observations.csv`),
  반전 보호(`caption.reveal`), 소재 검토(`source review`). 본 사람의 기록만 받는다.
- **Google Lens 역추적**: 자동화하지 않는다. `analysis/<id>/lens/` 키프레임으로 사람이 찾은 결과를 `source add-url` 로 넣는다.
- **로그인·쿠키**: 자동으로 되지 않는다(`local.yaml` 의 쿠키 경로는 사람이 채움).
