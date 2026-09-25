# test-coverage-001 편집 프로젝트

- 생성 2026-09-24T21:51:25+00:00 · 프리셋 `joshuamagazine-v1` · 포맷 `UNCLASSIFIED` · 모드 `test` (테스트: 파이프라인 검증용, 게시용 아님)
- 캔버스 1080x1920 @ 30fps · 길이 22.50s · 마스터 `episodes/test-coverage-001/output/test-coverage-001.mp4`
- 이 문서는 내보내기 코드가 실제로 내린 결정(`export_decisions.json`)과 검증 결과(`verify.json`)로 자동 생성됨. 적혀 있지 않은 것은 확인하지 않은 것임.

## 파일

| 파일 | 용도 | 검증 |
|---|---|---|
| `test-coverage-001.mlt` | Shotcut (MLT XML) 편집 프로젝트 | melt 렌더 비교: 통과 |
| `test-coverage-001.fcpxml` | DaVinci Resolve / Final Cut Pro 가져오기(FCPXML 1.9) | 못 잼 (프로그램 없음; 형식·시간 일관성만 테스트) |
| `test-coverage-001.otio` | OpenTimelineIO 교환 파일 | 못 잼 (렌더러 없음; 쓰기→읽기 왕복만 테스트) |
| `captions.ass` | 자막 + 장식 전체(한 레이어). Aegisub/텍스트 편집기로 수정 | 마스터 렌더와 같은 파일(복사본) |
| `captions.srt` | 모든 역할의 자막 텍스트·시간(7개) | 텍스트/시간만(스타일 없음) |
| `media/` | 미리 렌더된 중간 파일 1개(아래 '굽혀 있는 것') | - |
| `verify.json` | melt 렌더 비교 수치(초별 행 포함) | 통과 |
| `export_decisions.json` | 내보내기 결정 기록(이 README 의 근거) | - |

미디어 경로는 모두 **이 폴더 기준 상대 경로**다. 폴더 구조(프로젝트 루트 아래 `assets/`, `episodes/`, `warehouse/`)를 유지한 채로 열어야 한다.

## Shotcut 에서 편집할 수 있는 것 (MLT)

- 클립 순서·길이·트림(V2 영상 트랙의 각 조각)
- 클립별 위치/크기/줌(Size, Position & Rotate = affine 키프레임)
- 원본 정리 crop(Crop: Source)·delogo(avfilter.delogo) 수치
- 영상 영역 마스크(Crop: Rectangle = qtcrop)
- crossfade 전환(luma+mix 전환 트랙)
- 플래시(V3 트랙의 색 클립, Opacity 키프레임)
- BGM 시작점·이득·덕킹 envelope·페이드(volume 필터)
- 효과음 위치·이득(A2)
- 원본 소리 구간·이득·페이드(A3)
- 전체 음량 이득(타임라인 volume 필터)

트랙 구성:

| 트랙 | 종류 | 클립 수 |
|---|---|---|
| V1 배경 | 영상 | 1 |
| V2 영상 | 영상 | 7 |
| V3 플래시 | 영상 | 1 |
| A1 BGM | 소리 | 1 |
| A2 효과음 | 소리 | 3 |

- 전체 음량: 타임라인 volume 필터 -0.07 dB (출처: episodes/test-coverage-001/build/render_report.json)
- 효과음/원본 소리 안전 리미터: 마스터가 줄이지 않음(최대 0.0 dB, 출처 `episodes/test-coverage-001/build/fg_gain.json`) → 키프레임 없음
- 모노 오디오 3개: melt 7.22 는 모노 파일을 스테레오 프로젝트에 채널마다 -3.01 dB 로 올림(이 기계에서 측정: 비 0.70704, L=R); 마스터(shortkit.util.media.read_audio)는 모노를 양쪽 채널에 같은 크기(0 dB)로 넣음 → 모노 파일 클립마다 +3.01 dB volume 필터(역할: mono->stereo upmix compensation)
- 플래시 s4: 범위 영상 영역(region) rect [0, 656, 1080, 608] @ [1080, 1920], 프레임 [404, 407]

### Kdenlive

- 이 `.mlt` 는 Shotcut 구조의 MLT XML 이다. Kdenlive 는 자체 형식(.kdenlive)을 편집 타임라인으로 열고, 일반 MLT XML 은 보통 하나의 클립(재생목록)으로 불러온다(개별 클립 편집 불가) — Kdenlive 문서 기준이며 이 기계에서 확인하지 못함.
- Kdenlive 에서 클립 단위로 편집하려면 `.otio` 가져오기(OpenTimelineIO 지원 버전)를 쓴다. 이 기계에는 Kdenlive 가 없어 **확인하지 못함(못 잼)**.

## DaVinci Resolve / Final Cut Pro 에서 편집할 수 있는 것 (FCPXML)

- 클립 순서·트림·속도/정지(timeMap)
- crossfade(Cross Dissolve)
- 위치·크기·줌 키프레임
- clean crop(adjust-crop trim)
- 오디오 클립별 음량 키프레임(BGM 덕킹·페이드, 효과음, 원본 소리)
- 자막 텍스트(caption 요소, 스타일 없음)

FCPXML 로 표현하지 못해 빠지거나 대체된 것:

- 영상 영역 마스크(trim-rect 로 영역 밖 소스를 잘라 대신함; 화면 가장자리 처리 차이 가능)
- delogo/blur (미리 정리한 중간 파일로 대체)
- 자막·장식의 스타일/위치/모션(captions.ass 에만 있음)
- 마스터의 샘플 단위 전경 리미터(프레임 단위 음량 키프레임으로 근사)

확인하지 못한 가정(못 잼):

- adjust-transform position 단위 = 시퀀스 프레임 높이의 %, y 는 위쪽이 + (FCPXML 관례로 알려진 값; 이 기계에서 확인 못 함)
- adjust-crop trim-rect 단위 = 소스 가로/세로 각각의 %, trim-rect 의 left/top/right/bottom param 키프레임 애니메이션(줌 중 영상 영역 마스크 대용) (확인 못 함)
- 줌: 움직이는 동안 프레임마다 linear 키프레임(마스터의 3차 easing·recenter 를 프레임 격자에서 그대로 재현; FCP 쪽 해석은 확인 못 함)
- timeMap 의 time 은 클립 로컬 시간(start 기준), value 는 소스 시간
- 모노 오디오 파일: 마스터는 양쪽 채널에 같은 크기(0 dB)로 넣음(shortkit.util.media.read_audio) — Resolve/FCP 가 모노를 어떻게 스테레오에 놓는지(팬/레벨) 확인 못 함
- 효과음/원본 소리 음량 키프레임에 마스터 전경 안전 리미터(build/fg_gain.json)를 프레임 단위로 더함
- 전체 음량 이득 -0.07 dB 를 각 오디오 클립 음량에 더해 넣음(마스터 버스 없음)
- 미디어 경로: 상대 URL — 가져오기에서 미디어를 못 찾으면 `export --absolute` 로 이 컴퓨터 전용 파일을 만든다
- 검증: 이 기계에 DaVinci Resolve / Final Cut Pro 가 없어 가져오기·렌더 확인 못 함(못 잼). XML 형식과 시간 일관성만 테스트함

## OpenTimelineIO

- 트랙: V1 배경(1), V2 영상(7), V3 플래시(2), A1 BGM(1), A2 효과음(6)
- 마커: 자막 7개(V2), 효과음 사건 3개(A2)
- 줌·정지·원본 정리(crop/delogo/inpaint/blur) 수치는 각 클립 metadata['shortkit'] 에 있음
- 검증: OTIO 는 자체 렌더러가 없어 렌더 동등성 못 잼; 쓰기→읽기 왕복과 구조만 테스트함

## 굽혀 있어(미리 합성되어) 개별 편집이 안 되는 것

- **자막과 장식은 전부 `captions.ass` 한 파일, 한 레이어**로 그려진다(마스터 렌더와 같은 libass). NLE 의 개별 텍스트 클립이 아니므로 글자·위치·시간·스타일은 `captions.ass` 를 Aegisub 나 텍스트 편집기로 고친 뒤 다시 렌더/내보내기 해야 한다. `captions.srt` 는 텍스트·시간 참고용이다.

| id | 역할 | 시간(s) | 텍스트 |
|---|---|---|---|
| c_title | 제목 | 0.00–22.50 | 빈 방에 들어온 사람들 |
| c_desc | 설명 | 0.00–4.00 | 설정 연결 검증 테스트 2편 |
| c_sit1 | 상황 | 0.30–4.80 | 한 사람이 빈 방을 가로질러 나간다 |
| c_sit2 | 상황 | 5.00–9.80 | 한 남성이 카메라 앞까지 걸어온다 |
| c_rx | 반응 | 10.00–12.60 | 빤히 |
| c_sit3 | 상황 | 13.70–18.50 | 두 사람이 나란히 와서 선다 |
| c_sit4 | 상황 | 18.70–22.30 | 그리고 둘 다 떠난다 |

장식(같은 ASS 레이어):

| id | 종류 | 시간(s) |
|---|---|---|
| d_circle | circle | 8.50–11.50 |
| d_box | box | 16.50–18.50 |

- `media/s3_hold_b88f1cbb0d8e.png` — 정지(freeze)는 원본의 한 프레임을 이미지로 뽑아 이미지 클립으로 넣음 (melt 7.22 의 freeze 필터는 렌더가 멈추는 문제가 있어 사용하지 않음)

## 검증한 것

- MLT 프로젝트를 melt 로 실제 렌더해 마스터 MP4 와 같은 시각 1초 격자로 비교: **통과**
  - 화면 SSIM 전체 0.9923 (기준 ≥ 0.95), 가장 낮은 1초 0.9797 (기준 ≥ 0.9), 평균 절대차 0.691 (1초 기준 ≤ 10.0)
  - 1초별 SSIM 분포: n=23, p10 0.984 / p50 0.995 / p90 0.996
  - 소리 RMS 포락선 상관 0.9999 (기준 ≥ 0.9), 초별 레벨 차 최대 0.03 dB
  - 길이: 마스터 22.5s / 프로젝트 22.5s, 비교 프레임 675/675
  - 렌더 방식: `xvfb-run -a …` (xvfb-run), 결과 파일 episodes/test-coverage-001/build/verify/test-coverage-001.melt.mkv

초별 비교(같은 절대 시각):

| 초 | SSIM | 평균 절대차 | 레벨 차(dB) | 화면 | 소리 |
|---|---|---|---|---|---|
| 0 | 0.993 | 0.66 | -0.02 | 통과 | 통과 |
| 1 | 0.9941 | 0.594 | 0.01 | 통과 | 통과 |
| 2 | 0.9941 | 0.54 | 0.02 | 통과 | 통과 |
| 3 | 0.995 | 0.468 | 0.02 | 통과 | 통과 |
| 4 | 0.9958 | 0.452 | 0.03 | 통과 | 통과 |
| 5 | 0.995 | 0.538 | 0.02 | 통과 | 통과 |
| 6 | 0.9948 | 0.518 | 0.03 | 통과 | 통과 |
| 7 | 0.9949 | 0.539 | 0.03 | 통과 | 통과 |
| 8 | 0.9945 | 0.55 | 0.01 | 통과 | 통과 |
| 9 | 0.9955 | 0.532 | 0.01 | 통과 | 통과 |
| 10 | 0.9961 | 0.488 | 0.02 | 통과 | 통과 |
| 11 | 0.9967 | 0.376 | 0.01 | 통과 | 통과 |
| 12 | 0.997 | 0.45 | 0.02 | 통과 | 통과 |
| 13 | 0.9925 | 0.546 | 0.01 | 통과 | 통과 |
| 14 | 0.9837 | 0.903 | 0.01 | 통과 | 통과 |
| 15 | 0.9893 | 0.657 | 0.01 | 통과 | 통과 |
| 16 | 0.9949 | 0.544 | 0.02 | 통과 | 통과 |
| 17 | 0.9963 | 0.494 | 0.02 | 통과 | 통과 |
| 18 | 0.9929 | 0.545 | 0.02 | 통과 | 통과 |
| 19 | 0.9854 | 0.749 | 0.02 | 통과 | 통과 |
| 20 | 0.9797 | 1.499 | 0.02 | 통과 | 통과 |
| 21 | 0.9803 | 2.154 | 0.0 | 통과 | 통과 |
| 22 | 0.9891 | 1.487 | 0.0 | 통과 | 통과 |

## 검증하지 못한 것 (못 잼)

- Shotcut/Kdenlive GUI 에서 실제로 열어 보기(이 기계에 GUI 없음)
- 사람이 직접 보고 들은 확인(청취·시청 확인 안 함)
- DaVinci Resolve / Final Cut Pro 에서 FCPXML 가져오기·재생(프로그램 없음)
- OTIO 를 다른 편집기로 가져오기(Kdenlive/Resolve 어댑터 없음)
- fcpxml: FCPXML 은 DaVinci Resolve / Final Cut Pro 에서 열어야 렌더할 수 있는데 이 기계에는 둘 다 없음 → 렌더 동등성은 못 잼(구조·시간 일관성만 테스트에서 확인) — 영향: Resolve/FCP 로 가져온 타임라인이 마스터와 다를 수 있음(위치·자르기 단위, easing 곡선, 영역 마스크 없음) → 그 프로그램에서 내보낸 영상은 QA 를 다시 받아야 함
- otio: OTIO 는 교환용 타임라인이라 자체 렌더러가 없음(가져오는 NLE 에서만 재생 가능) → 렌더 동등성은 못 잼(구조·시간 일관성만 테스트에서 확인) — 영향: 가져오는 편집기마다 해석이 달라 결과가 마스터와 다를 수 있음 → 내보낸 영상은 QA 를 다시 받아야 함

## 주의

- 원본 소리는 기본 OFF: 영상 트랙의 소리는 모두 꺼져 있고, 살린 대사만 A3 트랙에 따로 있다.
- BGM 덕킹은 살린 대사 구간에서만 걸려 있다(효과음·컷 때문에 낮추지 않음). 정적 구간은 envelope 로 무음.
- 자막 글꼴: `episodes/test-coverage-001/build/fonts` (git 에 없는 build 폴더). melt 는 이 폴더(프로젝트 폴더 기준 상대 경로 av.fontsdir)를 쓰는데, 이 상대 경로는 실행 위치 기준으로 해석되므로 Shotcut 에서 글꼴이 다르게 보이면 해당 글꼴을 시스템에 설치한다.
- 계획 단계 경고:
  - [format_unclassified] 테스트 모드: 포맷 미분류(UNCLASSIFIED) — 포맷별 범위 검사는 못 함
  - [provenance_missing] warehouse_id 없음: 출처 기록(창고 레코드)이 연결되지 않았습니다
  - [provenance_missing] warehouse_id 없음: 출처 기록(창고 레코드)이 연결되지 않았습니다
  - [duration_unmeasured] 영상 길이 분포 미측정(못 잼, n=0, p10=None, p50=None, p90=None): 22.50s 의 적합성 판정 불가
  - [sfx_range_unmeasured] 효과음 카탈로그 미측정(못 잼): 종류별 개수·분포가 포맷 관측 범위 안인지 판정 불가 (2026-09-24: 레퍼런스 최신 50편 다운로드 불가(youtube 차단), Demucs 가중치 호스트(dl.fbaipublicfiles.com) 차단)
  - [bgm_identity_unmeasured] 프리셋 BGM 제목·버전 미식별(못 잼: title=None, version=None): 쓰는 음악 파일이 레퍼런스 곡·버전과 같은지 판정 불가
  - [preset_unmeasured] 테스트 모드: 프리셋 미측정(못 잼) 키 255개로 렌더합니다(레퍼런스 일치 아님)
- 프리셋 미측정(못 잼) 값 183개로 만든 편집이다(레퍼런스 일치 아님).
- plan sha256 `cf4e680edc8b03942142df990b5df75bc546fec434dc0e2de2d7f4315dfaa362`
- 승인 상태: 필요=False 승인됨=False
- 소스 v_room: `assets/test/generated/video/people-detection.mp4` sha256=18ffe8672d741e3e… 창고 id=None
- 소스 v_face: `assets/test/generated/video/face-demographics-walking-and-pause.mp4` sha256=d88ab9aa03634f66… 창고 id=None

## 다시 만들기

```
python -m shortkit episode export test-coverage-001
# 또는 이 모듈만: python -m shortkit.edit.project_readme export --episode test-coverage-001
```
