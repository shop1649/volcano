# 깨끗한 별도 폴더 복원 검증 기록 (요청문 11절)

이 컴퓨터(Ubuntu 24.04.4 컨테이너)에서 실제로 실행한 기록이다. 소리는 전부 기계 측정이다.
**청취 검수는 하지 않았다(사람 청취 필요).** 에이전트는 영상 프레임만 보았다.
원자료(명령·종료 코드·출력 원문)는 작업 컴퓨터의 scratchpad `frlog/commands.md`, `frlog/out/001–042.txt` 에 있다.
저장소에는 이 요약만 둔다.

## 1차 검증 (2026-09-25 12:32–13:33 UTC)

### 0. 범위

- 검증한 번들: 커밋 17e4e0a 의 `PRESET_BUNDLE.md`.
  - built_at 2026-09-25T12:32:57Z, 파일 323개, payload sha256 `2121b7a8…34a3ac`.
  - MD 2,181,063 B, payload 1,609,104 B.
- 이 검증에서 찾은 문제는 뒤의 커밋에서 고쳤다. 고친 번들은 2차 검증(아래)에서 다시 복원했다.

### 1. 번들 생성 → 빈 폴더 복원

- `python -m shortkit bundle build`: 종료 0.
  - 제외 `media/regenerable` 12개: 예제 MP4 2개, 비교 시트, mockloop 폴더, PNG.
- 빈 폴더에는 MD 하나만 복사했다.
  - MD 첫 줄 지시대로 1–391 행만 읽었다.
  - 인쇄된 bash 복원 블록을 **수정 없이** 실행했다: 종료 0, `restored 323 files (sha256 ok)`.
  - 복원된 323개 파일이 저장소 파일과 바이트 단위로 같다.

### 2. 초기 설정·점검

- `bash scripts/setup.sh` (`--with-apt` 없음): 종료 0.
  - pip 가 이 컴퓨터의 로컬 캐시를 썼다. PyPI 에서 처음 받는 상황은 검증하지 않았다.
  - 글꼴: 11개 받음(sha256 일치). 6개는 설계상 미확보(시스템 글꼴 또는 라이선스상 받지 않음).
  - 얼굴 검출 모델을 받았다.
- `python -m shortkit doctor --network`: 필수 미충족 0. demucs·torch 는 없다(선택).
  - 차단(403): www.youtube.com, rr1---sn-a5mekn6k.googlevideo.com, i.ytimg.com, www.tiktok.com,
    www.instagram.com, www.reddit.com, v.redd.it, dl.fbaipublicfiles.com.
  - 접속됨: raw.githubusercontent.com, www.googleapis.com. googleapis.com 은 API 키가 없어 쓰지 못했다.

### 3. 테스트 자산

| 명령 | 결과 |
|---|---|
| `testassets synth` | 종료 0 (14개) |
| `testassets fetch-video` (로컬 폴더 없이) | **종료 1**: GitHub LFS 미디어 4개 모두 HTTP 403 |
| `testassets fetch-video --local-dir <git clone>` | 종료 0 (4개 복사, sha256 일치) |
| `episode test-source` | 종료 0 (classroom_voice.mp4 `7ca6f09c…`) |
| `testassets dirty-source --video face-demographics-walking-and-pause.mp4` | 종료 0 (768x432, 12 fps, 20 s, `b861fc2d…`) |

`dirty-source` 는 출력 이름이 `dirty_source.mp4` 로 고정되어 있었다. 그래서 결과를 손으로 `dirty_source_facewalk.mp4` 로
옮겼다. 이후 `--out` 옵션을 추가했다(2차 검증 참고).

### 4. 새 에피소드 test-restore-001 (test 모드)

**소스**

| 소스 | 내용 |
|---|---|
| v_hall | `dirty_source_facewalk.mp4`: 워터마크 '@fake_repost', 영어 번인 자막, 음악, 합성 말소리가 섞인 소스. 예제 에피소드가 쓰지 않은 새 파일 |
| v_room | `people-detection.mp4` 28.0–34.6 s. test-coverage-001 과 같은 파일이지만 쓰지 않은 구간 |

**원본 정리**

- `clean detect`: 워터마크 (15,13,214,46 / 0–20 s), 자막 (241,356,279,47 / 2.00–6.08 s), 말줄임표 조각을 찾았다.
- `clean plan`: 잘라내기는 보호 영역을 자르므로 거부했다. inpaint 3건. 덮개 검사를 통과했다.

**plan 반복**

- v1: `embedded_music_raw` 오류로 막혔다.
  - 음악이 섞인 원음을 raw 로 살리려 했다.
  - demucs 가 없어 보컬을 분리할 수 없다. 그래서 원음을 끄고 대사 자막도 쓰지 않았다.
- v2–v4: 에이전트가 만든 문제를 고쳤다.
  - 구간 경계를 옮기고, 효과음이 컷 위에 붙던 문제를 고쳤다.
  - 걸어오는 동안의 두 손을 보호 영역에 넣었다.
- v4: 오류 0.

**결과물**

- 에피소드: 클립 3개, 18.50 s, 자막 9개(역할 5종), 줌 1.25배, 정지 0.7 s, 플래시 전환, 사건에 붙은 효과음 4개, BGM `music_bed_a`.
- 렌더: 1080x1920 30 fps 18.50 s.
  - **−14.4 LUFS / −1.7 dBTP**. 목표 대비 0.4 LU 부족이지만 허용 범위다.
  - 전경 리미터가 효과음 ding 에서 한도 3.0 dB 에 닿았다.
- 편집 프로젝트 MLT: melt 로 렌더해 대조했고 통과했다.
  - 프레임 555/555, SSIM 전체 0.9942, 가장 낮은 1초 0.9885.
  - 1초별 SSIM p10/p50/p90 0.989/0.995/0.997 (n=19).
  - 소리 포락선 상관 0.9998.
- FCPXML·OTIO: 파일은 만들었다. 편집기가 없어 열어 보지 못했다(**못 잼**).

**QA (번들 안의 코드)**

- 246행: 같다 160 / 다르다 2 / 못 잼 84. 관문 불합격.
- G1 `video.zoom:s1`, `video.speed:s3`: 둘 다 QA 오탐이었다.
  - 줌: 카메라로 걸어오는 사람이 특징점 배율을 속였다.
  - 속도: 0.7 s 정지 구간을 사이에 둔 채로 기울기를 쟀다.
  - 에이전트가 계획 기하로 대조했다: 자막을 가리고 추가 배율 1.00, NCC 0.996–0.998.
    정지 앞뒤 소스 시각도 계획과 1프레임 안이었다.
- G2 필수 못 잼 11건: 반전 없음 선언, 고정 카메라 소스의 글자 없는 로고 검사 10건.
  - 모두 사람이 확인해야 한다.
  - 에이전트는 코너 캡처 8장을 보았다. '@fake_repost' 외의 로고는 보이지 않았다. 이것은 사람 확인이 아니다.
- 원본 로고·자막 잔류: `clean.residual` 8행 모두 같다.
  - 경사 NCC 최대 0.12–0.32, 칸별 최대 0.33–0.36, OCR 0건.
  - 에이전트가 본 출력 프레임에도 '@fake_repost' 와 'WAIT FOR IT' 는 없다.
- 에이전트가 출력에서 본 복원 흔적:
  - 워터마크 자리에 옅은 얼룩, 자막 자리에 번진 띠가 있다.
  - **출력 2.5–3.3 s 에 걸어오는 남성의 두 손·허리가 번졌다**(자막 inpaint 가 보호 영역과 겹침).
  - 당시 validate 와 QA 는 이를 잡지 못했다.

### 5. pytest (복원 폴더, `-m "not slow"`)

- 7 failed / 812 passed / 2 skipped / 162 deselected (537.55 s).
- 원인은 모두 테스트의 선행 조건이었다.
  - 2개: 번들에서 빠지는 `episodes/*/build/resolved.json` 을 읽었다.
  - 4개: git 제외인 `episodes/test-qa-good`(slow 테스트가 만듦)을 읽었다.
  - 1개: 선언하지 않은 `soundfile` 을 import 했다.
- 선행 조건을 만들어 준 뒤 그 7개는 통과했다.

### 6. 이 검증으로 고친 것

| 문제 | 고침 | 커밋 |
|---|---|---|
| 줌 오탐(걸어오는 사람) | 줌 행이 계획 기하를 직접 확인한다: 줌 진행 중 3개 시각 포함, 자막·장식 가림, ±4% 대안보다 나아야 함. 표시 프레임 시각에 맞춤 | 80ca995 |
| 속도 오탐(정지 구간) | 정지 시간을 뺀 재생 시계로 기울기를 잰다. 1배속 클립도 속도 행을 남겨 결함을 다시 잴 수 있게 함 | 80ca995, d9b6b63 |
| 테스트 7개 선행 조건 | 합성 IR 을 메모리에서 만든다. 커밋된 에피소드는 `episode resolve` 로 다시 만든다. WAV 는 ffmpeg 로 쓴다 | e9245b6 |
| 보호 영역 위 국소 복원(손 번짐) | validate 경고 `clean_overlaps_protected` 추가. QA 필수 행 `clean.protected_overlap` 추가: 사람이 출력을 보고 판정할 때까지 못 잼 | d9b6b63 |
| validate `zoom_cuts_protected` 오경고 | 보호 영역의 시간 창을 본다. 줌 전에 화면을 떠난 손은 제외 | d9b6b63 |
| `dirty-source` 출력 이름 고정 | `--out <이름>` 추가 | d9b6b63 |
| mockloop 스크립트가 번들에서 빠짐 | 번들에 포함. `mockloop.md` 가 실행하라고 하는 스크립트다 | d9b6b63 |

### 7. 검증하지 못한 것

- GitHub LFS 미디어 직접 받기(403): 우회하지 않았고, git clone 한 폴더를 썼다.
- 원음 보존·덕킹 경로: demucs 가 없어 보컬 분리를 못 했다.
- 레퍼런스와 같은 시각 비교: 레퍼런스가 없어 68행이 못 잼이다.
- NLE: FCPXML·OTIO 를 편집기에서 열어 보지 않았다. Shotcut GUI 도 확인하지 않았다.
- 청취 없음. 사람 확인 12건이 남아 있다(반전 1, 코너 로고 10, 손 번짐 1).

## 2차 검증 (고친 번들, 2026-09-25 15:13–15:36 UTC)

검증한 번들은 커밋 c9fa60e 의 `PRESET_BUNDLE.md`(파일 364개)다. 1차에서 고친 것이 모두 들어 있다.
이번에는 에이전트 대신 스크립트가 단계마다 명령·종료 코드·출력을 기록했다(scratchpad `fr2/commands.md`, `fr2/out/*.txt`).

| 단계 | 결과 |
|---|---|
| 복원 | MD 첫 줄이 읽으라는 1–436 행 안의 첫 bash 블록(38–56 행)을 뽑아 **수정 없이** 실행: 종료 0, 파일 364개, 저장소 파일과 바이트 차이 0 |
| `setup.sh` | 종료 0 |
| `doctor --network` | 필수 미충족 0 (차단 호스트는 1차와 같음) |
| 테스트 자산 | synth · fetch-video `--local-dir` · test-source · dirty-source(기본) · dirty-source `--out dirty_source_facewalk` 모두 종료 0. facewalk sha256 `b861fc2d…` — 1차와 같은 파일 |
| `pytest -m "not slow"` (선행 조건을 손으로 만들지 않음) | 827 passed / **2 failed** / 2 skipped / 162 deselected (664 s) |
| test-restore-001 validate | 오류 0 · 경고 19. 새 경고 `clean_overlaps_protected`: 자막 inpaint 가 '남성 두 손' 의 60% 를 원본 5.30–6.08 s 동안 덮음 |
| resolve + render | 종료 0. **MP4 sha256 `6a1cd845…` — 1차 복원에서 만든(저장소에 커밋된) MP4 와 바이트 단위로 같음** |
| export + melt 대조 | 통과: SSIM 0.9942(최저 1초 0.9885), 소리 상관 0.9998, 프레임 555/555 |
| QA | 249행 같다 164 / 다르다 0 / 못 잼 85 — 저장소에서 잰 값과 같음 |
| 관문 | 불합격: G2 필수 못 잼 12건. 사람 확인 필요 — 반전 1, 글자 없는 로고 10, 손 위 복원 1 |

- pytest 실패 2건(`test_every_style_compare_reads_every_key_it_lists[test-pipeline-001/test-coverage-001]`)의 원인:
  - 예제 에피소드의 출력 MP4 는 번들에 넣지 않는다(다시 만들 수 있는 미디어). 테스트가 그 MP4 를 요구했다.
  - 커밋 b214659 에서 MP4 가 없으면 다시 만드는 명령과 함께 건너뛰게 고쳤다.
  - 고친 테스트 파일을 같은 복원 폴더에서 돌린 결과: 22 passed, 4 skipped(이유 표시).
- 환경: Ubuntu 24.04.4 LTS, 커널 6.18.44, Python 3.11.15, ffmpeg 6.1.1, melt 7.22.0, tesseract 5.3.4.
- 이 뒤의 번들은 위 테스트 고침과 문서(VALIDATION·이 기록·PROGRESS)만 달라진다. 최종 번들은 복원 블록·바이트 대조·그 테스트 파일만
  다시 확인했다(아래 3절).
