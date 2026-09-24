# 제안서 — test-coverage-001

- 프리셋: `joshuamagazine-v1` / 포맷: `UNCLASSIFIED` / 모드: `test` / 회차: 2
- plan_sha256: `cf4e680edc8b03942142df990b5df75bc546fec434dc0e2de2d7f4315dfaa362`
- 작성 시각(UTC): 2026-09-24T20:33:07+00:00
- 승인: 불필요(test 모드) / 현재 미승인
- 승인 방법: `python -m shortkit episode approve test-coverage-001 --by 이름` (승인 뒤 수정은 기록만 하고 다시 승인받지 않음)
- 검증 결과: 오류 0건, 경고 7건
- 메모: 테스트 모드(설정 연결 검증). 프리셋 스타일 값은 전부 임시값(못 잼)이라 레퍼런스와 같다고 말할 수 없음.

## 소재

| 소스 id | 파일 | sha256 | 플랫폼 | URL | 원작자 | 재게시자 | 조회수(확인 시각) | 게시일 | 선정 이유 |
|---|---|---|---|---|---|---|---|---|---|
| v_room | assets/test/generated/video/people-detection.mp4 | 18ffe8672d741e3e… | 못 잼 | 못 잼 | 못 잼 | 못 잼 | 못 잼 (창고 기록 없음) | 못 잼 | 못 잼 |
| v_face | assets/test/generated/video/face-demographics-walking-and-pause.mp4 | d88ab9aa03634f66… | 못 잼 | 못 잼 | 못 잼 | 못 잼 | 못 잼 (창고 기록 없음) | 못 잼 | 못 잼 |

- v_room: 창고 레코드 없음(warehouse_id=None) → 출처 정보 못 잼
- v_face: 창고 레코드 없음(warehouse_id=None) → 출처 정보 못 잼

## 구간 시트

| 구간 | 소스 | 원본 시간(s) | 출력 시간(s) | 목적 | 확대 | 정지 | 들어오는 전환 | 원음 |
|---|---|---|---|---|---|---|---|---|
| s1 | v_room | 2.00–6.80 | 0.00–4.80 | context | 없음 | 없음 | cut | 끔 |
| s2 | v_face | 5.00–10.00 | 4.80–9.80 | build | 없음 | 없음 | cut | 끔 |
| s3 | v_face | 10.00–13.00 | 9.80–13.50 | reaction | 없음 | 0.7s (원본 11.00s) | cut | 끔 |
| s4 | v_face | 32.00–37.00 | 13.50–18.50 | build | 없음 | 없음 | flash 0.12s | 끔 |
| s5 | v_face | 42.00–44.00 ×0.5 | 18.50–22.50 | outro | 없음 | 없음 | cut | 끔 |

전체 길이: 22.50s

## 표지 문구

- 문구: 빈 방에 들어온 사람들
- 표지 프레임: 0.0s / 프리셋 표지 방식: first_frame, 글자 역할: title

## 제목 후보 3종

1. 빈 방에 들어온 사람들
2. 카메라 앞에 멈춰 선 남성
3. 나란히 섰다가 떠난 두 사람

## 자막

### 말투 안내 (프리셋 text.tone)

- 말투: 반말_구어체 (임시값·못 잼) — 제목·설명·상황·반응 자막에 검사(`episode validate`의 tone_register), 대사는 예외
- 이모지: 쓰지 않음 (임시값·못 잼)
- 종결 어미 예시(레퍼런스 빈도 순): 못 잼(측정 전 — 예시 없음, 말투는 위 기준만 검사)

### 제목 (title)

| id | 시간(s) | 문구 | 근거 |
|---|---|---|---|
| c_title | 0.00–22.50 | 빈 방에 들어온 사람들 | 근거 불필요(편집 틀 문구) |

### 설명 (description)

| id | 시간(s) | 문구 | 근거 |
|---|---|---|---|
| c_desc | 0.00–4.00 | 설정 연결 검증 테스트 2편 | 근거 불필요(편집 틀 문구) |

### 상황 (situation)

| id | 시간(s) | 문구 | 근거 |
|---|---|---|---|
| c_sit1 | 0.30–4.80 | 한 사람이 빈 방을 가로질러 나간다 | 화면에서 봄 · v_room@4.0s · 아래쪽에서 들어와 오른쪽 벽 쪽으로 걸어가 6.8s 에 화면 밖 |
| c_sit2 | 5.00–9.80 | 한 남성이 카메라 앞까지 걸어온다 | 화면에서 봄 · v_face@7.0s |
| c_sit3 | 13.70–18.50 | 두 사람이 나란히 와서 선다 | 화면에서 봄 · v_face@34.8s |
| c_sit4 | 18.70–22.30 | 그리고 둘 다 떠난다 | 화면에서 봄 · v_face@43.0s |

### 반응 (reaction)

| id | 시간(s) | 문구 | 근거 |
|---|---|---|---|
| c_rx | 10.00–12.60 | 빤히 | 화면에서 봄 · v_face@11.0s · 카메라 정면을 보고 서 있음 |

## 효과음 배치표

| id | t(s) | 종류 | 사건 t(s) | 사건 | 차이(s) | 감정 | 파일 | 맵 상태 |
|---|---|---|---|---|---|---|---|---|
| fx1 | 4.55 | whoosh | 4.60 | 걷던 사람이 오른쪽 화면 밖으로 나감 | -0.05 | 못 잼 | assets/test/generated/sfx/whoosh.wav | 못 잼 |
| fx2 | 10.80 | click | 10.80 | 정면을 보고 선 순간 화면이 멈춤 | +0.00 | 못 잼 | assets/test/generated/sfx/click.wav | 못 잼 |
| fx3 | 16.30 | ding | 16.30 | 걸어 들어온 두 사람이 나란히 멈춰 섬 | +0.00 | 못 잼 | assets/test/generated/sfx/ding.wav | 못 잼 |

효과음 3개. 컷 때문에 넣은 효과음은 없어야 하며, 모든 효과음은 사건과 ±0.3s 안.

## BGM

- 파일: assets/test/generated/music_bed_b.wav / track_id: -
- 프리셋 곡 정보: 제목 못 잼, 버전 못 잼
- 사용 구간 시작: 0.0s / 속도 비율: 1.0 / 레벨: 0.0 dB / 페이드 인 0.0s · 아웃 0.8s
- 덕킹(보존 대사 구간에서만): 없음
- 의도적 정적: 없음
- 원음 살린 구간: 없음
- 목표 음량: -14.0 LUFS, 최대 -1.5 dBTP

## 미측정 영향

이 에피소드가 읽은 프리셋 값 중 173개가 미측정(못 잼, 임시값)입니다. 아래 값은 레퍼런스와 같다고 말할 수 없습니다.

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
| `decorations.box.blink_hz` | 0.0 | 화살표·원 등 장식 스타일 불일치 |
| `decorations.box.color` | #FF2A2A | 화살표·원 등 장식 스타일 불일치 |
| `decorations.box.stroke_px` | 8 | 화살표·원 등 장식 스타일 불일치 |
| `decorations.circle.blink_hz` | 0.0 | 화살표·원 등 장식 스타일 불일치 |
| `decorations.circle.color` | #FF2A2A | 화살표·원 등 장식 스타일 불일치 |
| `decorations.circle.stroke_px` | 10 | 화살표·원 등 장식 스타일 불일치 |
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
- duration_unmeasured: 영상 길이 분포 미측정(못 잼, n=0, p10=None, p50=None, p90=None): 22.50s 의 적합성 판정 불가
- sfx_range_unmeasured: 효과음 카탈로그 미측정(못 잼): 종류별 개수·분포가 포맷 관측 범위 안인지 판정 불가 (2026-09-24: 레퍼런스 최신 50편 다운로드 불가(youtube 차단), Demucs 가중치 호스트(dl.fbaipublicfiles.com) 차단)
- bgm_identity_unmeasured: 프리셋 BGM 제목·버전 미식별(못 잼: title=None, version=None): 쓰는 음악 파일이 레퍼런스 곡·버전과 같은지 판정 불가
- preset_unmeasured: 테스트 모드: 프리셋 미측정(못 잼) 키 255개로 렌더합니다(레퍼런스 일치 아님)

_범례: 있다/없다/못 잼 = 있다/없다/못 잼_
