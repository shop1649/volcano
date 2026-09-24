# 제안서 — test-pipeline-001

- 프리셋: `joshuamagazine-v1` / 포맷: `UNCLASSIFIED` / 모드: `test` / 회차: 1
- plan_sha256: `5c00390ef4fa49f7f83c2d37a9544841391b131e13c9b6def787b438a4ca790f`
- 작성 시각(UTC): 2026-09-24T18:03:22+00:00
- 승인: 불필요(첫 에피소드 production 이 아님) / 현재 미승인
- 승인 방법: `python -m shortkit episode approve test-pipeline-001 --by 이름` (승인 뒤 수정은 기록만 하고 다시 승인받지 않음)
- 검증 결과: 오류 0건, 경고 7건
- 메모: 테스트 모드. 프리셋 스타일 값은 전부 임시값(못 잼)이라 레퍼런스와 같다고 말할 수 없음.

## 소재

| 소스 id | 파일 | sha256 | 플랫폼 | URL | 원작자 | 재게시자 | 조회수(확인 시각) | 게시일 | 선정 이유 |
|---|---|---|---|---|---|---|---|---|---|
| v_class | assets/test/generated/classroom_voice.mp4 | 7ca6f09cb32cf87c… | 못 잼 | 못 잼 | 못 잼 | 못 잼 | 못 잼 (창고 기록 없음) | 못 잼 | 못 잼 |
| v_pair | assets/test/generated/video/head-pose-face-detection-female-and-male.mp4 | 650166430c4bf9dd… | 못 잼 | 못 잼 | 못 잼 | 못 잼 | 못 잼 (창고 기록 없음) | 못 잼 | 못 잼 |

- v_class: 창고 레코드 없음(warehouse_id=None) → 출처 정보 못 잼
- v_pair: 창고 레코드 없음(warehouse_id=None) → 출처 정보 못 잼

## 구간 시트

| 구간 | 소스 | 원본 시간(s) | 출력 시간(s) | 목적 | 확대 | 정지 | 들어오는 전환 | 원음 |
|---|---|---|---|---|---|---|---|---|
| s1 | v_class | 1.50–5.50 | 0.00–4.00 | hook | 1.0→1.25 @+1.3s 0.35s out | 없음 | cut | 끔 |
| s2 | v_class | 14.00–16.80 | 4.00–7.50 | build | 없음 | 0.7s (원본 16.80s) | cut | 끔 |
| s3 | v_class | 17.00–22.50 | 7.50–13.00 | build | 없음 | 없음 | flash 0.12s | 살림: 소스에 들어 있는 대사 한 줄(합성 TTS)을 살림 — 원음 보존·덕킹 경로 검증 (raw, 범위 [[19.5, 21.8]]) |
| s4 | v_pair | 3.00–11.50 | 12.75–21.25 | reveal | 없음 | 없음 | crossfade 0.25s | 끔 |

전체 길이: 21.25s

## 표지 문구

- 문구: 교실과 벽 앞, 사람들의 움직임
- 표지 프레임: 0.0s / 프리셋 표지 방식: first_frame, 글자 역할: title

## 제목 후보 3종

1. 창가 남성이 일어섰다 앉기까지
2. 손을 든 뒷줄, 고개를 기울인 두 사람
3. 움직임 테스트 영상

## 자막

### 제목 (title)

| id | 시간(s) | 문구 | 근거 |
|---|---|---|---|
| c_title | 0.00–21.25 | 움직임 테스트 영상 | 근거 불필요(편집 틀 문구) |

### 설명 (description)

| id | 시간(s) | 문구 | 근거 |
|---|---|---|---|
| c_desc | 0.00–4.00 | 파이프라인 검증용 합성 샘플 | 근거 불필요(편집 틀 문구) |

### 상황 (situation)

| id | 시간(s) | 문구 | 근거 |
|---|---|---|---|
| c_sit1 | 1.30–3.90 | 창가 남성이 일어선다 | 화면에서 봄 · v_class@3.5s |
| c_sit2 | 4.10–7.40 | 다시 자리에 앉는다 | 화면에서 봄 · v_class@15.8s |
| c_sit3 | 7.70–9.90 | 뒷줄 남성이 손을 든다 | 화면에서 봄 · v_class@17.3s |
| c_sit4 | 15.10–19.00 | 두 사람이 고개를 기울인다 | 화면에서 봄 · v_pair@5.5s |

### 인물 (speaker)

| id | 시간(s) | 문구 | 근거 |
|---|---|---|---|
| c_spk | 0.30–3.90 | 창가 남성 | 화면에서 봄 · v_class@2.0s · 창가 쪽 책상에 앉은 남성 |

### 대사 (dialogue)

| id | 시간(s) | 문구 | 근거 |
|---|---|---|---|
| c_dlg | 10.10–12.30 | "저기 봐, 들어온다!" | 들림 · v_class@19.6s · 소스 오디오에 들어 있는 합성 TTS 한 줄(화면 인물의 말이라고 주장하지 않음) |

### 반응 (reaction)

| id | 시간(s) | 문구 | 근거 |
|---|---|---|---|
| c_rx | 15.10–17.50 | 갸우뚱? | 화면에서 봄 · v_pair@5.5s · 두 사람이 고개를 옆으로 기울임 |

반전 보호: 15.0s 전 자막에 ['기울', '갸우뚱'] 금지 — 마지막 장면의 동작을 앞 자막에서 미리 말하지 않음

## 효과음 배치표

| id | t(s) | 종류 | 사건 t(s) | 사건 | 차이(s) | 감정 | 파일 | 맵 상태 |
|---|---|---|---|---|---|---|---|---|
| fx1 | 1.25 | whoosh | 1.30 | 창가 남성이 일어서기 시작함(확대 시작) | -0.05 | anticipation | assets/test/generated/sfx/whoosh.wav | 못 잼 |
| fx2 | 6.80 | click | 6.80 | 다시 앉은 순간 화면이 멈춤 | +0.00 | emphasis | assets/test/generated/sfx/click.wav | 못 잼 |
| fx3 | 7.75 | pop | 7.75 | 뒷줄 남성이 손을 들어 올림 | +0.00 | surprise | assets/test/generated/sfx/pop.wav | 못 잼 |
| fx4 | 10.90 | ding | 11.00 | 뒷줄 남성이 자리에서 일어섬 | -0.10 | surprise | assets/test/generated/sfx/ding.wav | 못 잼 |
| fx5 | 15.00 | boing | 15.05 | 두 사람이 동시에 고개를 옆으로 기울임 | -0.05 | funny | assets/test/generated/sfx/boing.wav | 못 잼 |

효과음 5개. 컷 때문에 넣은 효과음은 없어야 하며, 모든 효과음은 사건과 ±0.3s 안.

## BGM

- 파일: assets/test/generated/music_bed_a.wav / track_id: -
- 프리셋 곡 정보: 제목 못 잼, 버전 못 잼
- 사용 구간 시작: 12.0s / 속도 비율: 1.0 / 레벨: -20.0 dB / 페이드 인 0.0s · 아웃 0.8s
- 덕킹(보존 대사 구간에서만): [(10.0, 12.3)]
- 의도적 정적: [(6.8, 7.45)]
- 원음 살린 구간: [('s3', 10.0, 12.3, '소스에 들어 있는 대사 한 줄(합성 TTS)을 살림 — 원음 보존·덕킹 경로 검증')]
- 목표 음량: -14.0 LUFS, 최대 -1.5 dBTP

## 미측정 영향

이 에피소드가 읽은 프리셋 값 중 230개가 미측정(못 잼, 임시값)입니다. 아래 값은 레퍼런스와 같다고 말할 수 없습니다.

| 키 | 현재(임시)값 | 영향 |
|---|---|---|
| `audio.bgm.fade_in_s` | 0.0 | BGM 곡/버전/속도/구간/크기 불일치 → 음악 일치 판정 불가 |
| `audio.bgm.fade_out_s` | 0.8 | BGM 곡/버전/속도/구간/크기 불일치 → 음악 일치 판정 불가 |
| `audio.bgm.gain_db` | -20.0 | BGM 곡/버전/속도/구간/크기 불일치 → 음악 일치 판정 불가 |
| `audio.bgm.loop` | False | BGM 곡/버전/속도/구간/크기 불일치 → 음악 일치 판정 불가 |
| `audio.bgm.tempo_ratio` | 1.0 | BGM 곡/버전/속도/구간/크기 불일치 → 음악 일치 판정 불가 |
| `audio.bgm.track_id` | None | BGM 곡/버전/속도/구간/크기 불일치 → 음악 일치 판정 불가 |
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
| `decorations.arrow.blink_hz` | 0.0 | 화살표·원 등 장식 스타일 불일치 |
| `decorations.arrow.color` | #FF2A2A | 화살표·원 등 장식 스타일 불일치 |
| `decorations.arrow.outline_color` | #FFFFFF | 화살표·원 등 장식 스타일 불일치 |
| `decorations.arrow.outline_px` | 6 | 화살표·원 등 장식 스타일 불일치 |
| `decorations.arrow.size_px` | 120 | 화살표·원 등 장식 스타일 불일치 |
| `motion.freeze.hold_s` | 0.7 | 확대·정지·전환의 크기/길이 불일치 |
| `motion.transitions.crossfade.dur_s` | 0.25 | 확대·정지·전환의 크기/길이 불일치 |
| `motion.transitions.default` | cut | 확대·정지·전환의 크기/길이 불일치 |
| `motion.transitions.flash.color` | #FFFFFF | 확대·정지·전환의 크기/길이 불일치 |
| `motion.transitions.flash.dur_s` | 0.12 | 확대·정지·전환의 크기/길이 불일치 |
| `motion.zoom.dur_s` | 0.35 | 확대·정지·전환의 크기/길이 불일치 |
| `motion.zoom.ease` | out | 확대·정지·전환의 크기/길이 불일치 |
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
| `text.roles.dialogue.anchor.align` | center | 제목/자막 위치 불일치 |
| `text.roles.dialogue.anchor.valign` | middle | 제목/자막 위치 불일치 |
| `text.roles.dialogue.anchor.x` | 540 | 제목/자막 위치 불일치 |
| `text.roles.dialogue.anchor.y` | 1430 | 제목/자막 위치 불일치 |
| `text.roles.dialogue.bold` | True | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.dialogue.box.alpha` | 0.0 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.dialogue.box.color` | #000000 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.dialogue.box.enabled` | False | 자막 박스 유무·색·여백 불일치 |
| `text.roles.dialogue.box.pad_x` | 16 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.dialogue.box.pad_y` | 8 | 자막 박스 유무·색·여백 불일치 |
| `text.roles.dialogue.color` | #FFE400 | 글자 색 불일치 |
| `text.roles.dialogue.font_name` | Noto Sans CJK KR Black | 글꼴이 레퍼런스와 다를 수 있음 → 글자 인상·폭·줄바꿈 불일치 |
| `text.roles.dialogue.highlight_color` | #FFFFFF | 강조 색 불일치 |
| `text.roles.dialogue.line_spacing` | 1.15 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.dialogue.max_chars_per_line` | 15 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.dialogue.max_lines` | 2 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.dialogue.max_width_px` | 960 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.dialogue.motion_in.dur_s` | 0.0 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.dialogue.motion_in.offset_px` | 0 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.dialogue.motion_in.scale_from` | 1.0 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.dialogue.motion_in.type` | none | 자막 등장·퇴장 모션 불일치 |
| `text.roles.dialogue.motion_out.dur_s` | 0.0 | 자막 등장·퇴장 모션 불일치 |
| `text.roles.dialogue.motion_out.type` | none | 자막 등장·퇴장 모션 불일치 |
| `text.roles.dialogue.outline_color` | #000000 | 외곽선 두께·색 불일치 |
| `text.roles.dialogue.outline_px` | 6 | 외곽선 두께·색 불일치 |
| `text.roles.dialogue.persist` | timed | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.dialogue.quote_marks` | ['"', '"'] | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.dialogue.shadow_color` | #000000 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.dialogue.shadow_px` | 0 | 레퍼런스와의 일치 여부를 판정할 수 없음 |
| `text.roles.dialogue.size_px` | 62 | 글자 크기 불일치 → 줄 수·가림 영역 변화 |
| `text.roles.dialogue.timing.lead_s` | 0.0 | 자막 등장 타이밍 불일치 |
| `text.roles.dialogue.timing.min_dur_s` | 0.8 | 자막 등장 타이밍 불일치 |
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
- duration_unmeasured: 영상 길이 분포 미측정(못 잼): 21.25s 의 적합성 판정 불가
- sfx_range_unmeasured: 효과음 카탈로그 미측정(못 잼): 종류별 개수·분포가 포맷 관측 범위 안인지 판정 불가 (2026-09-24: 레퍼런스 최신 50편 다운로드 불가(youtube 차단), Demucs 가중치 호스트(dl.fbaipublicfiles.com) 차단)
- preset_unmeasured: 테스트 모드: 프리셋 미측정(못 잼) 키 251개로 렌더합니다(레퍼런스 일치 아님)

_범례: 있다/없다/못 잼 = 있다/없다/못 잼_
