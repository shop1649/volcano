# 제안서 — test-restore-001

- 프리셋: `joshuamagazine-v1` / 포맷: `UNCLASSIFIED` / 도입 방식: `못 잼` / 모드: `test` / 회차: 1
- plan_sha256: `11d5216835ca38242365a6ee3ea79dc45379238b860bbdbc55f4044e86b0d996`
- 작성 시각(UTC): 2026-09-25T13:13:37+00:00
- 승인: 불필요(test 모드) / 현재 미승인
- 승인 방법: `python -m shortkit episode approve test-restore-001 --by 이름` (승인 뒤 수정은 기록만 하고 다시 승인받지 않음)
- 검증 결과: 오류 0건, 경고 19건
- 메모: 테스트 모드(복원 검증). 프리셋 스타일 값은 전부 임시값(못 잼)이라 레퍼런스와 같다고 말할 수 없음. 소리는 에이전트가 듣지 못했음(기계 측정만) — 청취 검수 완료 아님.

## 소재

| 소스 id | 파일 | sha256 | 플랫폼 | URL | 원작자 | 재게시자 | 조회수(확인 시각) | 게시일 | 선정 이유 |
|---|---|---|---|---|---|---|---|---|---|
| v_hall | assets/test/generated/dirty_source_facewalk.mp4 | b861fc2d9ea59f5b… | 못 잼 | 못 잼 | 못 잼 | 못 잼 | 못 잼 (창고 기록 없음) | 못 잼 | 못 잼 |
| v_room | assets/test/generated/video/people-detection.mp4 | 18ffe8672d741e3e… | 못 잼 | 못 잼 | 못 잼 | 못 잼 | 못 잼 (창고 기록 없음) | 못 잼 | 못 잼 |

- v_hall: 창고 레코드 없음(warehouse_id=None) → 출처 정보 못 잼
- v_room: 창고 레코드 없음(warehouse_id=None) → 출처 정보 못 잼

### 가리면 안 되는 곳(보호 영역, 원본 px·원본 시각)

- v_hall: 남성 얼굴(복도 끝) x=470 y=170 w=90 h=50 (3.3~4.1s)
- v_hall: 남성 얼굴(걸어옴 1) x=420 y=165 w=95 h=57 (4.0~4.9s)
- v_hall: 남성 얼굴(걸어옴 2) x=360 y=155 w=90 h=70 (4.8~5.9s)
- v_hall: 남성 얼굴(걸어옴 3) x=325 y=145 w=100 h=82 (5.8~7.1s)
- v_hall: 남성 얼굴(가까이 옴) x=310 y=128 w=122 h=100 (7.0~8.1s)
- v_hall: 남성 얼굴(정면으로 섬) x=310 y=120 w=140 h=125 (8.0~18.3s)
- v_hall: 남성 얼굴(오른쪽으로 나감) x=340 y=95 w=300 h=180 (18.2~18.9s)
- v_hall: 남성 얼굴(화면 가장자리) x=640 y=40 w=128 h=200 (18.9~19.5s)
- v_hall: 남성 두 손(걸어올 때 1) x=390 y=295 w=110 h=60 (4.5~5.4s)
- v_hall: 남성 두 손(걸어올 때 2) x=300 y=320 w=185 h=85 (5.3~6.2s)
- v_room: 들어오는 세 사람 x=150 y=120 w=500 h=312 (28.2~29.6s)
- v_room: 걸어가는 세 사람 x=170 y=95 w=430 h=337 (29.5~30.6s)
- v_room: 갈라지기 직전 세 사람 x=180 y=55 w=430 h=330 (30.5~31.6s)
- v_room: 왼쪽으로 가는 남성 x=90 y=30 w=130 h=240 (31.5~32.6s)
- v_room: 오른쪽으로 가는 두 사람 x=460 y=60 w=220 h=270 (31.5~32.6s)
- v_room: 왼쪽 벽 앞 남성 x=0 y=60 w=140 h=200 (32.5~33.1s)
- v_room: 오른쪽 벽 앞 두 사람 x=560 y=60 w=208 h=250 (32.5~34.6s)

## 구간 시트

| 구간 | 소스 | 원본 시간(s) | 출력 시간(s) | 목적 | 확대 | 정지 | 들어오는 전환 | 원음 |
|---|---|---|---|---|---|---|---|---|
| s1 | v_hall | 2.80–12.30 | 0.00–9.50 | hook | 1.0→1.25 @+5.8s 0.35s out | 없음 | cut | 끔 |
| s2 | v_hall | 17.90–19.60 | 9.50–11.20 | build | 없음 | 없음 | cut | 끔 |
| s3 | v_room | 28.00–34.60 | 11.20–18.50 | outro | 없음 | 0.7s (원본 31.00s) | flash 0.12s | 끔 |

전체 길이: 18.50s

## 표지 문구

- 문구: 카메라 앞에 선 남자
- 표지 프레임: 0.0s / 프리셋 표지 방식: first_frame, 글자 역할: title

## 제목 후보 3종

1. 카메라 앞에 선 남자
2. 복도 끝에서 걸어온 남자
3. 다가와 멈췄다가 떠난 사람들

## 자막

### 말투 안내 (프리셋 text.tone)

- 말투: 반말_구어체 (임시값·못 잼) — 제목·설명·상황·반응 자막에 검사(`episode validate`의 tone_register), 대사는 예외
- 이모지: 쓰지 않음 (임시값·못 잼)
- 종결 어미 예시(레퍼런스 빈도 순): 못 잼(측정 전 — 예시 없음, 말투는 위 기준만 검사)

### 제목 (title)

| id | 시간(s) | 문구 | 근거 |
|---|---|---|---|
| c_title | 0.00–18.50 | 카메라 앞에 선 남자 | 편집 틀 · 편집 틀 제목 — v_hall 8.3~18.2s 남성이 카메라 바로 앞에 서 있음 |

### 설명 (description)

| id | 시간(s) | 문구 | 근거 |
|---|---|---|---|
| c_desc | 0.00–4.00 | 복원 검증용 테스트 영상 | 편집 틀 · 이 영상이 깨끗한 폴더 복원 검증용 테스트라는 설명 |

### 상황 (situation)

| id | 시간(s) | 문구 | 근거 |
|---|---|---|---|
| c_sit1 | 0.70–5.20 | 복도 끝에서 한 남자가 걸어온다 | 화면에서 봄 · v_hall@5.0s · 3.4s 복도 끝에 처음 보이고 카메라 쪽으로 걸어옴 |
| c_sit2 | 5.30–9.30 | 카메라 바로 앞에서 멈춰 선다 | 화면에서 봄 · v_hall@8.5s |
| c_sit3 | 9.50–11.10 | 그러더니 옆으로 휙 나간다 | 화면에서 봄 · v_hall@18.7s |
| c_sit4 | 11.40–14.80 | 빈 방에 세 명이 들어온다 | 화면에서 봄 · v_room@29.5s |
| c_sit5 | 15.00–18.30 | 한 명은 왼쪽, 둘은 오른쪽 | 화면에서 봄 · v_room@32.0s |

### 인물 (speaker)

| id | 시간(s) | 문구 | 근거 |
|---|---|---|---|
| c_spk | 5.70–8.20 | 남색 티셔츠 남성 | 화면에서 봄 · v_hall@9.0s · 남색 반팔 티셔츠를 입은 안경 쓴 남성 |

### 반응 (reaction)

| id | 시간(s) | 문구 | 근거 |
|---|---|---|---|
| c_rx | 6.80–9.30 | 멀뚱멀뚱 | 화면에서 봄 · v_hall@10.5s · 정면을 보고 가만히 서 있음 |

반전 보호: Nones 전 자막에 None 금지 — 

## 효과음 배치표

| id | t(s) | 종류 | 사건 t(s) | 사건 | 차이(s) | 감정 | 파일 | 맵 상태 |
|---|---|---|---|---|---|---|---|---|
| fx1 | 0.60 | pop | 0.60 | 복도 끝 유리문 쪽에 남성이 처음 보임 | +0.00 | curiosity | assets/test/generated/sfx/pop.wav | 못 잼 |
| fx2 | 5.50 | ding | 5.50 | 카메라 바로 앞에서 걸음을 멈춤 | +0.00 | emphasis | assets/test/generated/sfx/ding.wav | 못 잼 |
| fx3 | 10.05 | whoosh | 10.10 | 남성이 오른쪽으로 빠르게 걸어 화면을 벗어남 | -0.05 | surprise | assets/test/generated/sfx/whoosh.wav | 못 잼 |
| fx4 | 14.20 | click | 14.20 | 세 사람이 양쪽으로 갈라지기 직전 화면이 멈춤 | +0.00 | emphasis | assets/test/generated/sfx/click.wav | 못 잼 |

효과음 4개. 컷 때문에 넣은 효과음은 없어야 하며, 모든 효과음은 사건과 ±0.3s 안.

## BGM

- 파일: assets/test/generated/music_bed_a.wav / track_id: -
- 프리셋 곡 정보: 제목 못 잼, 버전 못 잼
- 사용 구간 시작: 0.0s / 속도 비율: 1.0 / 레벨: 0.0 dB / 페이드 인 0.0s · 아웃 0.8s
- 덕킹(보존 대사 구간에서만): 없음
- 의도적 정적: 없음
- 원음 살린 구간: 없음
- 목표 음량: -14.0 LUFS, 최대 -1.5 dBTP

## 미측정 영향

이 에피소드가 읽은 프리셋 값 중 198개가 미측정(못 잼, 임시값)입니다. 아래 값은 레퍼런스와 같다고 말할 수 없습니다.

| 키 | 현재(임시)값 | 영향 |
|---|---|---|
| `audio.bgm.fade_in_s` | 0.0 | BGM 곡/버전/속도/구간/크기 불일치 → 음악 일치 판정 불가 |
| `audio.bgm.fade_out_s` | 0.8 | BGM 곡/버전/속도/구간/크기 불일치 → 음악 일치 판정 불가 |
| `audio.bgm.gain_db` | 0.0 | BGM 곡/버전/속도/구간/크기 불일치 → 음악 일치 판정 불가 |
| `audio.bgm.loop` | False | BGM 곡/버전/속도/구간/크기 불일치 → 음악 일치 판정 불가 |
| `audio.bgm.section_start_s` | 0.0 | BGM 곡/버전/속도/구간/크기 불일치 → 음악 일치 판정 불가 |
| `audio.bgm.tempo_ratio` | 1.0 | BGM 곡/버전/속도/구간/크기 불일치 → 음악 일치 판정 불가 |
| `audio.bgm.title` | None | BGM 곡 제목 미식별 → 음악 라이브러리 파일이 그 곡인지 판정 불가 |
| `audio.bgm.track_id` | None | BGM 곡/버전/속도/구간/크기 불일치 → 음악 일치 판정 불가 |
| `audio.bgm.version` | None | BGM 버전 미식별 → 같은 곡의 다른 버전(다른 트랙)을 쓸 위험 |
| `audio.ducking.attack_s` | 0.08 | 보존 대사 구간의 BGM 덕킹 깊이·속도 불일치 |
| `audio.ducking.depth_db` | 10.0 | 보존 대사 구간의 BGM 덕킹 깊이·속도 불일치 |
| `audio.ducking.release_s` | 0.3 | 보존 대사 구간의 BGM 덕킹 깊이·속도 불일치 |
| `audio.loudness.integrated_lufs` | -14.0 | 최종 음량 불일치 |
| `audio.loudness.true_peak_db` | -1.5 | 최종 음량 불일치 |
| `audio.original.fade_s` | 0.04 | 원음 켜고 끄는 경계 처리 불일치 |
| `audio.original.keep_gain_db` | 0.0 | 보존 원음 크기 불일치 |
| `audio.sfx.gain_db_default` | -8.0 | 효과음 크기 불일치 |
| `audio.silence.fade_s` | 0.05 | 의도적 정적 처리 불일치 |
| `canvas.background.blur_sigma` | 30 | 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치 |
| `canvas.background.color` | #000000 | 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치 |
| `canvas.background.type` | color | 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치 |
| `canvas.fps` | 30 | 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치 |
| `canvas.height` | 1920 | 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치 |
| `canvas.safe_margin.bottom` | 250 | 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치 |
| `canvas.safe_margin.left` | 54 | 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치 |
| `canvas.safe_margin.right` | 54 | 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치 |
| `canvas.safe_margin.top` | 110 | 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치 |
| `canvas.video_region.fit` | cover | 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치 |
| `canvas.video_region.h` | 608 | 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치 |
| `canvas.video_region.w` | 1080 | 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치 |
| `canvas.video_region.x` | 0 | 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치 |
| `canvas.video_region.y` | 656 | 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치 |
| `canvas.width` | 1080 | 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치 |
| `motion.freeze.hold_s` | 0.7 | 확대·정지·전환의 크기/길이 불일치 |
| `motion.transitions.crossfade.dur_s` | 0.25 | 확대·정지·전환의 크기/길이 불일치 |
| `motion.transitions.default` | cut | 확대·정지·전환의 크기/길이 불일치 |
| `motion.transitions.flash.color` | #FFFFFF | 확대·정지·전환의 크기/길이 불일치 |
| `motion.transitions.flash.dur_s` | 0.12 | 확대·정지·전환의 크기/길이 불일치 |
| `motion.transitions.flash.scope` | region | 확대·정지·전환의 크기/길이 불일치 |
| `motion.zoom.dur_s` | 0.35 | 확대·정지·전환의 크기/길이 불일치 |
| `motion.zoom.ease` | out | 확대·정지·전환의 크기/길이 불일치 |
| `motion.zoom.recenter` | False | 확대·정지·전환의 크기/길이 불일치 |
| `motion.zoom.scale_to` | 1.25 | 확대·정지·전환의 크기/길이 불일치 |
| `text.roles.description.anchor.align` | center | 제목/자막 위치 불일치 |
| `text.roles.description.anchor.valign` | middle | 제목/자막 위치 불일치 |
| `text.roles.description.anchor.x` | 540 | 제목/자막 위치 불일치 |
| `text.roles.description.anchor.y` | 500 | 제목/자막 위치 불일치 |
| `text.roles.description.bold` | True | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.description.box.alpha` | 0.0 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.description.box.color` | #000000 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.description.box.enabled` | False | 자막 박스 유무·색·여백 불일치 |
| `text.roles.description.box.pad_x` | 14 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.description.box.pad_y` | 8 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.description.color` | #E6E6E6 | 글자 색 불일치 |
| `text.roles.description.font_name` | Noto Sans CJK KR Bold | 글꼴이 레퍼런스와 다를 수 있음 → 글자 인상·폭·줄바꿈 불일치 |
| `text.roles.description.highlight_color` | #FFE400 | 강조 색 불일치 |
| `text.roles.description.line_spacing` | 1.15 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.description.max_chars_per_line` | 20 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.description.max_lines` | 1 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.description.max_width_px` | 980 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.description.motion_in.dur_s` | 0.2 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.description.motion_in.offset_px` | 0 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.description.motion_in.scale_from` | 1.0 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.description.motion_in.type` | fade | 자막 등장·퇴장 모션 불일치 |
| `text.roles.description.motion_out.dur_s` | 0.0 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.description.motion_out.type` | none | 자막 등장·퇴장 모션 불일치 |
| `text.roles.description.outline_color` | #000000 | 외곽선 두께·색 불일치 |
| `text.roles.description.outline_px` | 4 | 외곽선 두께·색 불일치 |
| `text.roles.description.persist` | timed | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.description.shadow_color` | #000000 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.description.shadow_px` | 0 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.description.size_px` | 46 | 글자 크기 불일치 → 줄 수·가림 영역 변화 |
| `text.roles.description.timing.lead_s` | 0.0 | 자막 등장 타이밍 불일치 |
| `text.roles.description.timing.min_dur_s` | 1.0 | 자막 등장 타이밍 불일치 |
| `text.roles.reaction.anchor.align` | center | 제목/자막 위치 불일치 |
| `text.roles.reaction.anchor.valign` | middle | 제목/자막 위치 불일치 |
| `text.roles.reaction.anchor.x` | 540 | 제목/자막 위치 불일치 |
| `text.roles.reaction.anchor.y` | 1140 | 제목/자막 위치 불일치 |
| `text.roles.reaction.bold` | True | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.reaction.box.alpha` | 0.0 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.reaction.box.color` | #000000 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.reaction.box.enabled` | False | 자막 박스 유무·색·여백 불일치 |
| `text.roles.reaction.box.pad_x` | 16 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.reaction.box.pad_y` | 8 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.reaction.color` | #FFE400 | 글자 색 불일치 |
| `text.roles.reaction.font_name` | Noto Sans CJK KR Black | 글꼴이 레퍼런스와 다를 수 있음 → 글자 인상·폭·줄바꿈 불일치 |
| `text.roles.reaction.highlight_color` | #FFFFFF | 강조 색 불일치 |
| `text.roles.reaction.line_spacing` | 1.1 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.reaction.max_chars_per_line` | 10 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.reaction.max_lines` | 1 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.reaction.max_width_px` | 900 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.reaction.motion_in.dur_s` | 0.1 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.reaction.motion_in.offset_px` | 0 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.reaction.motion_in.scale_from` | 1.35 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.reaction.motion_in.type` | pop | 자막 등장·퇴장 모션 불일치 |
| `text.roles.reaction.motion_out.dur_s` | 0.0 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.reaction.motion_out.type` | none | 자막 등장·퇴장 모션 불일치 |
| `text.roles.reaction.outline_color` | #000000 | 외곽선 두께·색 불일치 |
| `text.roles.reaction.outline_px` | 7 | 외곽선 두께·색 불일치 |
| `text.roles.reaction.persist` | timed | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.reaction.shadow_color` | #000000 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.reaction.shadow_px` | 0 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.reaction.size_px` | 76 | 글자 크기 불일치 → 줄 수·가림 영역 변화 |
| `text.roles.reaction.timing.lead_s` | 0.0 | 자막 등장 타이밍 불일치 |
| `text.roles.reaction.timing.min_dur_s` | 0.6 | 자막 등장 타이밍 불일치 |
| `text.roles.situation.anchor.align` | center | 제목/자막 위치 불일치 |
| `text.roles.situation.anchor.valign` | middle | 제목/자막 위치 불일치 |
| `text.roles.situation.anchor.x` | 540 | 제목/자막 위치 불일치 |
| `text.roles.situation.anchor.y` | 1430 | 제목/자막 위치 불일치 |
| `text.roles.situation.bold` | True | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.situation.box.alpha` | 0.0 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.situation.box.color` | #000000 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.situation.box.enabled` | False | 자막 박스 유무·색·여백 불일치 |
| `text.roles.situation.box.pad_x` | 16 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.situation.box.pad_y` | 8 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.situation.color` | #FFFFFF | 글자 색 불일치 |
| `text.roles.situation.font_name` | Noto Sans CJK KR Black | 글꼴이 레퍼런스와 다를 수 있음 → 글자 인상·폭·줄바꿈 불일치 |
| `text.roles.situation.highlight_color` | #FFE400 | 강조 색 불일치 |
| `text.roles.situation.line_spacing` | 1.15 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.situation.max_chars_per_line` | 14 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.situation.max_lines` | 2 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.situation.max_width_px` | 960 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.situation.motion_in.dur_s` | 0.12 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.situation.motion_in.offset_px` | 0 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.situation.motion_in.scale_from` | 0.85 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.situation.motion_in.type` | pop | 자막 등장·퇴장 모션 불일치 |
| `text.roles.situation.motion_out.dur_s` | 0.0 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.situation.motion_out.type` | none | 자막 등장·퇴장 모션 불일치 |
| `text.roles.situation.outline_color` | #000000 | 외곽선 두께·색 불일치 |
| `text.roles.situation.outline_px` | 6 | 외곽선 두께·색 불일치 |
| `text.roles.situation.persist` | timed | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.situation.shadow_color` | #000000 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.situation.shadow_px` | 0 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.situation.size_px` | 66 | 글자 크기 불일치 → 줄 수·가림 영역 변화 |
| `text.roles.situation.timing.lead_s` | 0.0 | 자막 등장 타이밍 불일치 |
| `text.roles.situation.timing.min_dur_s` | 0.9 | 자막 등장 타이밍 불일치 |
| `text.roles.speaker.anchor.align` | center | 제목/자막 위치 불일치 |
| `text.roles.speaker.anchor.valign` | middle | 제목/자막 위치 불일치 |
| `text.roles.speaker.anchor.x` | 540 | 제목/자막 위치 불일치 |
| `text.roles.speaker.anchor.y` | 700 | 제목/자막 위치 불일치 |
| `text.roles.speaker.bold` | True | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.speaker.box.alpha` | 0.65 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.speaker.box.color` | #000000 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.speaker.box.enabled` | True | 자막 박스 유무·색·여백 불일치 |
| `text.roles.speaker.box.pad_x` | 14 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.speaker.box.pad_y` | 6 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.speaker.color` | #FFFFFF | 글자 색 불일치 |
| `text.roles.speaker.font_name` | Noto Sans CJK KR Bold | 글꼴이 레퍼런스와 다를 수 있음 → 글자 인상·폭·줄바꿈 불일치 |
| `text.roles.speaker.highlight_color` | #FFE400 | 강조 색 불일치 |
| `text.roles.speaker.line_spacing` | 1.1 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.speaker.max_chars_per_line` | 10 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.speaker.max_lines` | 1 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.speaker.max_width_px` | 420 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.speaker.motion_in.dur_s` | 0.15 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.speaker.motion_in.offset_px` | 0 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.speaker.motion_in.scale_from` | 1.0 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.speaker.motion_in.type` | fade | 자막 등장·퇴장 모션 불일치 |
| `text.roles.speaker.motion_out.dur_s` | 0.15 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.speaker.motion_out.type` | fade | 자막 등장·퇴장 모션 불일치 |
| `text.roles.speaker.outline_color` | #000000 | 외곽선 두께·색 불일치 |
| `text.roles.speaker.outline_px` | 0 | 외곽선 두께·색 불일치 |
| `text.roles.speaker.persist` | timed | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.speaker.shadow_color` | #000000 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.speaker.shadow_px` | 0 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.speaker.size_px` | 40 | 글자 크기 불일치 → 줄 수·가림 영역 변화 |
| `text.roles.speaker.timing.lead_s` | 0.0 | 자막 등장 타이밍 불일치 |
| `text.roles.speaker.timing.min_dur_s` | 1.0 | 자막 등장 타이밍 불일치 |
| `text.roles.title.anchor.align` | center | 제목/자막 위치 불일치 |
| `text.roles.title.anchor.valign` | middle | 제목/자막 위치 불일치 |
| `text.roles.title.anchor.x` | 540 | 제목/자막 위치 불일치 |
| `text.roles.title.anchor.y` | 330 | 제목/자막 위치 불일치 |
| `text.roles.title.bold` | True | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.title.box.alpha` | 0.0 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.title.box.color` | #000000 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.title.box.enabled` | False | 자막 박스 유무·색·여백 불일치 |
| `text.roles.title.box.pad_x` | 18 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.title.box.pad_y` | 10 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.title.color` | #FFFFFF | 글자 색 불일치 |
| `text.roles.title.font_name` | Noto Sans CJK KR Black | 글꼴이 레퍼런스와 다를 수 있음 → 글자 인상·폭·줄바꿈 불일치 |
| `text.roles.title.highlight_color` | #FFE400 | 강조 색 불일치 |
| `text.roles.title.line_spacing` | 1.18 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.title.max_chars_per_line` | 13 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.title.max_lines` | 2 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.title.max_width_px` | 980 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.title.motion_in.dur_s` | 0.0 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.title.motion_in.offset_px` | 0 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.title.motion_in.scale_from` | 1.0 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.title.motion_in.type` | none | 자막 등장·퇴장 모션 불일치 |
| `text.roles.title.motion_out.dur_s` | 0.0 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.title.motion_out.type` | none | 자막 등장·퇴장 모션 불일치 |
| `text.roles.title.outline_color` | #000000 | 외곽선 두께·색 불일치 |
| `text.roles.title.outline_px` | 6 | 외곽선 두께·색 불일치 |
| `text.roles.title.persist` | whole_video | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.title.shadow_color` | #000000 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.title.shadow_px` | 0 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.title.size_px` | 84 | 글자 크기 불일치 → 줄 수·가림 영역 변화 |
| `text.roles.title.timing.lead_s` | 0.0 | 자막 등장 타이밍 불일치 |
| `text.roles.title.timing.min_dur_s` | 1.0 | 자막 등장 타이밍 불일치 |

검증에서 나온 미측정 항목:
- intro_variants_unmeasured: 테스트 모드(포맷 미분류): 도입 방식을 레퍼런스 포맷의 도입 변형과 비교 못 함
- duration_unmeasured: 영상 길이 분포 미측정(못 잼, n=0, p10=None, p50=None, p90=None): 18.50s 의 적합성 판정 불가
- cuts_per_10s_unmeasured: structure.cuts_per_10s 분포 미측정(못 잼, n=0, p10=None, p50=None, p90=None): 계획의 컷 밀도(10초당 전환 수) 1.081개 (전환 2개: cut@9.50s, flash@11.20s / 18.50s) 적합성 판정 불가
- shot_len_s_unmeasured: structure.shot_len_s 분포 미측정(못 잼, n=0, p10=None, p50=None, p90=None): 계획의 샷 길이 중앙값 7.3s (전환 2개: cut@9.50s, flash@11.20s / 18.50s) 적합성 판정 불가
- first_caption_unmeasured: 첫 시간제 자막 시각(structure.first_caption_at_s = 0.0) 미측정(못 잼, 임시값): 이 plan 의 첫 시간제 자막 0.70s 을 레퍼런스와 비교 못 함
- reveal_order_unmeasured: 테스트 모드(포맷 미분류): 정보 공개 순서를 레퍼런스 포맷과 비교 못 함
- sfx_range_unmeasured: 효과음 카탈로그 미측정(못 잼): 종류별 개수·분포가 포맷 관측 범위 안인지 판정 불가 (2026-09-24: 레퍼런스 최신 50편 다운로드 불가(youtube 차단), Demucs 가중치 호스트(dl.fbaipublicfiles.com) 차단)
- sfx_file_type_unmeasured: 명시 파일 assets/test/generated/sfx/pop.wav 이 종류 'pop' 소리인지 비교할 카탈로그 지문이 없음(못 잼)
- sfx_file_type_unmeasured: 명시 파일 assets/test/generated/sfx/ding.wav 이 종류 'ding' 소리인지 비교할 카탈로그 지문이 없음(못 잼)
- sfx_file_type_unmeasured: 명시 파일 assets/test/generated/sfx/whoosh.wav 이 종류 'whoosh' 소리인지 비교할 카탈로그 지문이 없음(못 잼)
- sfx_file_type_unmeasured: 명시 파일 assets/test/generated/sfx/click.wav 이 종류 'click' 소리인지 비교할 카탈로그 지문이 없음(못 잼)
- bgm_identity_unmeasured: 프리셋 BGM 제목·버전 미식별(못 잼: title=None, version=None): 쓰는 음악 파일이 레퍼런스 곡·버전과 같은지 판정 불가
- presence_unmeasured: 레퍼런스의 효과 사용 여부 못 잼: zoom(씀), freeze(씀), speed_change(안 씀), flash(씀), crossfade(안 씀), decorations(안 씀), bgm(씀), original_audio(안 씀), ducking(안 씀), intentional_silence(안 씀) — 이 plan 의 선택을 레퍼런스와 비교할 수 없음
- preset_unmeasured: 테스트 모드: 프리셋 미측정(못 잼) 키 266개로 렌더합니다(레퍼런스 일치 아님)

_범례: 있다/없다/못 잼 = 있다/없다/못 잼_
