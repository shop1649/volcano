# 미확정 항목·제작 영향·해결 상태

자동 생성: `shortkit preset unresolved` (2026-09-25T03:56:50+00:00). 손으로 고치지 말 것 — 원본은 settings_registry.yaml 과 각 산출물(단계 표는 유효 프리셋 = preset.yaml + measured.yaml + requested_changes.yaml 과 각 단계 파일에서 다시 평가).

못 잼 = 측정하지 못함. 못 잼 항목은 임시값으로만 테스트 렌더가 가능하고, QA 에서 완료로 승격되지 않는다.

## 1. 단계 단위 미확정

| 항목 | 상태 | 제작 영향 | 해결 상태 | 근거 |
|---|---|---|---|---|
| 최신 100편 목록·게시일 고정 | 못 잼 | 포맷 분류·모든 측정의 기준 표본이 없음 → 모든 스타일 값이 임시값 | blocked_network | presets/joshuamagazine/reference/latest100.json status=blocked videos=0 blocker=https://youtube.com/@joshuamagazine/shorts: DownloadError: ERROR: [youtube:tab] @joshuamagazine/shorts: Unable to download API page: ('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')) (caused by ProxyError("('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden'))")); please report this issue on  https://github.com/yt-dlp/yt-dlp/issues?q= , filling out the appropriate issue template. Confirm you are on the latest version using  yt-dlp -U |
| 조회수 80만 이상 영상 전체 분석 | 못 잼 | 고조회 영상의 공통 구조·BGM·효과음·출처를 확인하지 못한 영상이 있음 → 고조회 소재 제외 목록·참고 보고서가 불완전 | blocked_network | reference/high_views_report.json: 목록 0편(high_views.json status=blocked, 확인 못 함 0편), 영상 받기 0/0, 시각 분석(ref analyze) 0/0, 오디오 분석(ref audio-analyze) 0/0, 출처 추적·지문(ref trace) 0/0 |
| 포맷 분류표·포맷별 대표 영상 | 못 잼 | 포맷별 p10/p50/p90, 효과음 개수 범위, 대표 영상 비교(QA)를 쓸 수 없음 → 에피소드는 test 모드(UNCLASSIFIED)만 가능 | blocked_network | formats.yaml status=unmeasured blocker=2026-09-24: youtube.com/googlevideo.com 차단으로 최신 100편 목록·영상 미확보 → 포맷 분류 못 함; 라벨 파일 없음 — `shortkit ref classify prepare` 후 영상을 본 사람이 채워야 함 |
| 효과음 카탈로그(최신 50편 Demucs) | 못 잼 | 효과음 종류·편당 개수·자리 규칙이 없음 → 효과음 개수/분포 검사는 못 잼 | blocked_network | sfx_catalog.json status=unmeasured blocker=2026-09-24: 레퍼런스 최신 50편 다운로드 불가(youtube 차단), Demucs 가중치 호스트(dl.fbaipublicfiles.com) 차단 |
| 효과음 창고 연결(sfx_map) | 못 잼 | 제작에 쓸 효과음 파일이 정해지지 않음 → production 렌더 불가 | open_user_asset | sfx_map.yaml library_status=not_provided have=0/0 |
| BGM 곡·버전·속도·사용 구간 식별 | 못 잼 | 음악 구간 일치 판정 불가, 깨끗한 음악 파일 확보 불가 | blocked_network | track_id=None(provisional), title=None(provisional), version=None(provisional), tempo_ratio=1.0(provisional), section_start_s=0.0(provisional); presence.bgm=unmeasured(provisional); 못 잰 항목=['track_id', 'title', 'version', 'tempo_ratio', 'section_start_s']; 음악 라이브러리 트랙 없음 |
| 글꼴 식별(IoU 상한 + 후보 검증) | 못 잼 | 글꼴이 레퍼런스와 같은지 판정 불가(동일 판정 없는 역할은 임시 글꼴) | blocked_network | fonts_report.json status=ceiling_only: reference crops unmeasured (못 잼); 역할별 판정/값 출처: title=못 잼/provisional, description=못 잼/provisional, situation=못 잼/provisional, speaker=못 잼/provisional, dialogue=못 잼/provisional, reaction=못 잼/provisional |
| 레퍼런스 소재 출처·반복 계정·키워드 역추적 | 못 잼 | 새 소재 검색어/계정 목록이 없음, 레퍼런스 촬영본 제외 목록이 비어 있음 | blocked_network | warehouse/source_accounts.json stage: 추적 기록 없음; 제외 지문 0건; accounts=0 |

## 2. 모션·전환·BGM·원음 있다/없다/못 잼 (채널 단위, 전체·포맷별)

| 항목 | 전체 | n(있다/측정) | 근거 |
|---|---|---|---|
| `presence.bgm` | 못 잼 | 0/0 | 레퍼런스 목록 수집 차단(2026-09-24T17:56:07+00:00, yt-dlp 2026.08.19): https://youtube.com |
| `presence.crossfade` | 못 잼 | 0/0 | 레퍼런스 목록 수집 차단(2026-09-24T17:56:07+00:00, yt-dlp 2026.08.19): https://youtube.com |
| `presence.decorations` | 못 잼 | 0/0 | 레퍼런스 목록 수집 차단(2026-09-24T17:56:07+00:00, yt-dlp 2026.08.19): https://youtube.com |
| `presence.ducking` | 못 잼 | 0/0 | 레퍼런스 목록 수집 차단(2026-09-24T17:56:07+00:00, yt-dlp 2026.08.19): https://youtube.com |
| `presence.flash` | 못 잼 | 0/0 | 레퍼런스 목록 수집 차단(2026-09-24T17:56:07+00:00, yt-dlp 2026.08.19): https://youtube.com |
| `presence.freeze` | 못 잼 | 0/0 | 레퍼런스 목록 수집 차단(2026-09-24T17:56:07+00:00, yt-dlp 2026.08.19): https://youtube.com |
| `presence.intentional_silence` | 못 잼 | 0/0 | 레퍼런스 목록 수집 차단(2026-09-24T17:56:07+00:00, yt-dlp 2026.08.19): https://youtube.com |
| `presence.original_audio` | 못 잼 | 0/0 | 레퍼런스 목록 수집 차단(2026-09-24T17:56:07+00:00, yt-dlp 2026.08.19): https://youtube.com |
| `presence.speed_change` | 못 잼 | 0/0 | 레퍼런스 목록 수집 차단(2026-09-24T17:56:07+00:00, yt-dlp 2026.08.19): https://youtube.com |
| `presence.zoom` | 못 잼 | 0/0 | 레퍼런스 목록 수집 차단(2026-09-24T17:56:07+00:00, yt-dlp 2026.08.19): https://youtube.com |

## 3. 프리셋 설정 키 단위

상태별 개수: fixed_by_rule=14, not_applicable=24, not_applicable_given=5, unmeasured=262

못 잼 키의 해결 상태: blocked_network=260, no_method=2

| 제작 영향 | 못 잼 키 수 | 해결 상태 | 키 |
|---|---|---|---|
| 레퍼런스와의 일치 여부를 판정할 수 없음 | 49 | blocked_network | `text.roles.description.bold`, `text.roles.description.line_spacing`, `text.roles.description.max_chars_per_line`, `text.roles.description.max_lines`, `text.roles.description.max_width_px`, `text.roles.description.persist`, `text.roles.description.shadow_color`, `text.roles.description.shadow_px`, `text.roles.dialogue.bold`, `text.roles.dialogue.line_spacing`, `text.roles.dialogue.max_chars_per_line`, `text.roles.dialogue.max_lines` … |
| 자막 등장·퇴장 모션 불일치 | 36 | blocked_network | `text.roles.description.motion_in.dur_s`, `text.roles.description.motion_in.offset_px`, `text.roles.description.motion_in.scale_from`, `text.roles.description.motion_in.type`, `text.roles.description.motion_out.dur_s`, `text.roles.description.motion_out.type`, `text.roles.dialogue.motion_in.dur_s`, `text.roles.dialogue.motion_in.offset_px`, `text.roles.dialogue.motion_in.scale_from`, `text.roles.dialogue.motion_in.type`, `text.roles.dialogue.motion_out.dur_s`, `text.roles.dialogue.motion_out.type` … |
| 자막 박스 유무·색·여백 불일치 | 30 | blocked_network | `text.roles.description.box.alpha`, `text.roles.description.box.color`, `text.roles.description.box.enabled`, `text.roles.description.box.pad_x`, `text.roles.description.box.pad_y`, `text.roles.dialogue.box.alpha`, `text.roles.dialogue.box.color`, `text.roles.dialogue.box.enabled`, `text.roles.dialogue.box.pad_x`, `text.roles.dialogue.box.pad_y`, `text.roles.reaction.box.alpha`, `text.roles.reaction.box.color` … |
| 제목/자막 위치 불일치 | 24 | blocked_network | `text.roles.description.anchor.align`, `text.roles.description.anchor.valign`, `text.roles.description.anchor.x`, `text.roles.description.anchor.y`, `text.roles.dialogue.anchor.align`, `text.roles.dialogue.anchor.valign`, `text.roles.dialogue.anchor.x`, `text.roles.dialogue.anchor.y`, `text.roles.reaction.anchor.align`, `text.roles.reaction.anchor.valign`, `text.roles.reaction.anchor.x`, `text.roles.reaction.anchor.y` … |
| 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치 | 15 | blocked_network, no_method | `canvas.background.blur_sigma`, `canvas.background.color`, `canvas.background.type`, `canvas.fps`, `canvas.height`, `canvas.safe_margin.bottom`, `canvas.safe_margin.left`, `canvas.safe_margin.right`, `canvas.safe_margin.top`, `canvas.video_region.fit`, `canvas.video_region.h`, `canvas.video_region.w` … |
| 화살표·원 등 장식 스타일 불일치 | 14 | blocked_network | `decorations.arrow.blink_hz`, `decorations.arrow.color`, `decorations.arrow.head_len_ratio`, `decorations.arrow.head_width_ratio`, `decorations.arrow.outline_color`, `decorations.arrow.outline_px`, `decorations.arrow.shaft_width_ratio`, `decorations.arrow.size_px`, `decorations.box.blink_hz`, `decorations.box.color`, `decorations.box.stroke_px`, `decorations.circle.blink_hz` … |
| 외곽선 두께·색 불일치 | 12 | blocked_network | `text.roles.description.outline_color`, `text.roles.description.outline_px`, `text.roles.dialogue.outline_color`, `text.roles.dialogue.outline_px`, `text.roles.reaction.outline_color`, `text.roles.reaction.outline_px`, `text.roles.situation.outline_color`, `text.roles.situation.outline_px`, `text.roles.speaker.outline_color`, `text.roles.speaker.outline_px`, `text.roles.title.outline_color`, `text.roles.title.outline_px` |
| 확대·정지·전환의 크기/길이 불일치 | 11 | blocked_network | `motion.freeze.hold_s`, `motion.speed.slowmo_factor`, `motion.transitions.crossfade.dur_s`, `motion.transitions.default`, `motion.transitions.flash.color`, `motion.transitions.flash.dur_s`, `motion.transitions.flash.scope`, `motion.zoom.dur_s`, `motion.zoom.ease`, `motion.zoom.recenter`, `motion.zoom.scale_to` |
| 레퍼런스에 이 효과가 있는지 없는지 몰라 과용/누락을 판정할 수 없음 | 10 | blocked_network | `presence.bgm`, `presence.crossfade`, `presence.decorations`, `presence.ducking`, `presence.flash`, `presence.freeze`, `presence.intentional_silence`, `presence.original_audio`, `presence.speed_change`, `presence.zoom` |
| 자막 등장 타이밍 불일치 | 7 | blocked_network | `text.roles.description.timing.min_dur_s`, `text.roles.dialogue.timing.lead_s`, `text.roles.dialogue.timing.min_dur_s`, `text.roles.reaction.timing.min_dur_s`, `text.roles.situation.timing.min_dur_s`, `text.roles.speaker.timing.min_dur_s`, `text.roles.title.timing.min_dur_s` |
| BGM 곡/버전/속도/구간/크기 불일치 → 음악 일치 판정 불가 | 7 | blocked_network | `audio.bgm.fade_in_s`, `audio.bgm.fade_out_s`, `audio.bgm.gain_db`, `audio.bgm.loop`, `audio.bgm.section_start_s`, `audio.bgm.tempo_ratio`, `audio.bgm.track_id` |
| 글꼴이 레퍼런스와 다를 수 있음 → 글자 인상·폭·줄바꿈 불일치 | 6 | blocked_network | `text.roles.description.font_name`, `text.roles.dialogue.font_name`, `text.roles.reaction.font_name`, `text.roles.situation.font_name`, `text.roles.speaker.font_name`, `text.roles.title.font_name` |
| 글자 크기 불일치 → 줄 수·가림 영역 변화 | 6 | blocked_network | `text.roles.description.size_px`, `text.roles.dialogue.size_px`, `text.roles.reaction.size_px`, `text.roles.situation.size_px`, `text.roles.speaker.size_px`, `text.roles.title.size_px` |
| 글자 색 불일치 | 6 | blocked_network | `text.roles.description.color`, `text.roles.dialogue.color`, `text.roles.reaction.color`, `text.roles.situation.color`, `text.roles.speaker.color`, `text.roles.title.color` |
| 강조 색 불일치 | 6 | blocked_network | `text.roles.description.highlight_color`, `text.roles.dialogue.highlight_color`, `text.roles.reaction.highlight_color`, `text.roles.situation.highlight_color`, `text.roles.speaker.highlight_color`, `text.roles.title.highlight_color` |
| 영상 길이 관측 범위(p10..p90)가 없어 길이 적합성 판정 불가 → 너무 길거나 짧은 편집 가능 | 4 | blocked_network | `structure.duration_s.n`, `structure.duration_s.p10`, `structure.duration_s.p50`, `structure.duration_s.p90` |
| 보존 대사 구간의 BGM 덕킹 깊이·속도 불일치 | 3 | blocked_network | `audio.ducking.attack_s`, `audio.ducking.depth_db`, `audio.ducking.release_s` |
| 최종 음량 불일치 | 2 | blocked_network | `audio.loudness.integrated_lufs`, `audio.loudness.true_peak_db` |
| 표지 구성 불일치 | 2 | blocked_network | `cover.source`, `cover.text_role` |
| 자막 종결 어미(말투) 검사 기준이 임시값 → 대본 말투가 레퍼런스와 다를 수 있음 | 1 | blocked_network | `text.tone.register` |
| 제안서의 말투 안내(종결 어미 예시)가 비어 있음 → 대본 말투가 레퍼런스와 다를 수 있음 | 1 | blocked_network | `text.tone.sentence_end_examples` |
| 자막 이모지 허용 여부가 임시값 → 이모지 사용이 레퍼런스와 다를 수 있음 | 1 | blocked_network | `text.tone.emoji` |
| 연속 확대 허용 횟수가 레퍼런스와 다를 수 있음(임시값 1) | 1 | blocked_network | `motion.zoom.max_consecutive` |
| 편당 정지 허용 횟수가 레퍼런스와 다를 수 있음(임시값 2) | 1 | blocked_network | `motion.freeze.max_per_video` |
| BGM 곡 제목 미식별 → 음악 라이브러리 파일이 그 곡인지 판정 불가 | 1 | blocked_network | `audio.bgm.title` |
| BGM 버전 미식별 → 같은 곡의 다른 버전(다른 트랙)을 쓸 위험 | 1 | blocked_network | `audio.bgm.version` |
| 보존 원음 크기 불일치 | 1 | blocked_network | `audio.original.keep_gain_db` |
| 원음 켜고 끄는 경계 처리 불일치 | 1 | blocked_network | `audio.original.fade_s` |
| 효과음 크기 불일치 | 1 | blocked_network | `audio.sfx.gain_db_default` |
| 의도적 정적 처리 불일치 | 1 | blocked_network | `audio.silence.fade_s` |
| 영상 길이·전개 구조 불일치 | 1 | blocked_network | `structure.first_caption_at_s` |

### 자동 측정 방법이 없는 키(관찰 경로)

| 키 | 해결 상태 | 측정 경로 |
|---|---|---|
| `canvas.background.blur_sigma` | no_method | 흐림 배경(background.type=blur_source)일 때만 필요. 원본 없이 흐림 정도를 역산하는 방법 없음 → 후보 sigma 로 렌더한 배경과 레퍼런스 배경을 나란히 보고 가장 가까운 값을 manual_observations.csv 에 기록 — shortkit.reference.manual.MANUAL_KEYS 에 이 키가 없어 관찰 기록을 아직 받을 수 없음 |
| `canvas.video_region.fit` | no_method | 결과 화면만으로는 원본 비율을 알 수 없어 자동 측정 방법 없음 → 레퍼런스 화면과 역추적한 원 촬영본(ref trace)을 나란히 보고, 영상 영역에서 원본 가장자리가 잘렸으면 cover, 여백이 있으면 contain 을 manual_observations.csv 에 기록 — shortkit.reference.manual.MANUAL_KEYS 에 이 키가 없어 관찰 기록을 아직 받을 수 없음 |
| `cover.source` | blocked_network | manual_observations.csv → ref manual-aggregate |
| `cover.text_role` | blocked_network | manual_observations.csv → ref manual-aggregate |
| `decorations.arrow.blink_hz` | blocked_network | manual_observations.csv(영상을 본 사람: watched=yes, observed_by) → ref manual-aggregate (자동 장식 검출은 합성 모의 영상으로만 검증된 실험 기능) |
| `decorations.arrow.color` | blocked_network | manual_observations.csv(영상을 본 사람: watched=yes, observed_by) → ref manual-aggregate (자동 장식 검출은 합성 모의 영상으로만 검증된 실험 기능) |
| `decorations.arrow.head_len_ratio` | blocked_network | manual_observations.csv(영상을 본 사람: watched=yes, observed_by) → ref manual-aggregate (자동 장식 검출은 합성 모의 영상으로만 검증된 실험 기능) |
| `decorations.arrow.head_width_ratio` | blocked_network | manual_observations.csv(영상을 본 사람: watched=yes, observed_by) → ref manual-aggregate (자동 장식 검출은 합성 모의 영상으로만 검증된 실험 기능) |
| `decorations.arrow.outline_color` | blocked_network | manual_observations.csv(영상을 본 사람: watched=yes, observed_by) → ref manual-aggregate (자동 장식 검출은 합성 모의 영상으로만 검증된 실험 기능) |
| `decorations.arrow.outline_px` | blocked_network | manual_observations.csv(영상을 본 사람: watched=yes, observed_by) → ref manual-aggregate (자동 장식 검출은 합성 모의 영상으로만 검증된 실험 기능) |
| `decorations.arrow.shaft_width_ratio` | blocked_network | manual_observations.csv(영상을 본 사람: watched=yes, observed_by) → ref manual-aggregate (자동 장식 검출은 합성 모의 영상으로만 검증된 실험 기능) |
| `decorations.arrow.size_px` | blocked_network | manual_observations.csv(영상을 본 사람: watched=yes, observed_by) → ref manual-aggregate (자동 장식 검출은 합성 모의 영상으로만 검증된 실험 기능) |
| `decorations.box.blink_hz` | blocked_network | manual_observations.csv(영상을 본 사람: watched=yes, observed_by) → ref manual-aggregate (자동 장식 검출은 합성 모의 영상으로만 검증된 실험 기능) |
| `decorations.box.color` | blocked_network | manual_observations.csv(영상을 본 사람: watched=yes, observed_by) → ref manual-aggregate (자동 장식 검출은 합성 모의 영상으로만 검증된 실험 기능) |
| `decorations.box.stroke_px` | blocked_network | manual_observations.csv(영상을 본 사람: watched=yes, observed_by) → ref manual-aggregate (자동 장식 검출은 합성 모의 영상으로만 검증된 실험 기능) |
| `decorations.circle.blink_hz` | blocked_network | manual_observations.csv(영상을 본 사람: watched=yes, observed_by) → ref manual-aggregate (자동 장식 검출은 합성 모의 영상으로만 검증된 실험 기능) |
| `decorations.circle.color` | blocked_network | manual_observations.csv(영상을 본 사람: watched=yes, observed_by) → ref manual-aggregate (자동 장식 검출은 합성 모의 영상으로만 검증된 실험 기능) |
| `decorations.circle.stroke_px` | blocked_network | manual_observations.csv(영상을 본 사람: watched=yes, observed_by) → ref manual-aggregate (자동 장식 검출은 합성 모의 영상으로만 검증된 실험 기능) |
| `text.tone.emoji` | blocked_network | manual_observations.csv → ref manual-aggregate |

### 다른 측정값 때문에 해당 없는 키

| 키 | 근거 키 = 값 | 이유 | 제작에서 |
|---|---|---|---|
| `text.roles.description.timing.lead_s` | `정의` = None | 정의: lead_s = 대사 자막 시작 − 겹치는 말소리 시작 → 대사(dialogue) 외 역할에는 기준 사건이 없음 | 0(계획 plan 의 자막 시각 그대로) |
| `text.roles.reaction.timing.lead_s` | `정의` = None | 정의: lead_s = 대사 자막 시작 − 겹치는 말소리 시작 → 대사(dialogue) 외 역할에는 기준 사건이 없음 | 0(계획 plan 의 자막 시각 그대로) |
| `text.roles.situation.timing.lead_s` | `정의` = None | 정의: lead_s = 대사 자막 시작 − 겹치는 말소리 시작 → 대사(dialogue) 외 역할에는 기준 사건이 없음 | 0(계획 plan 의 자막 시각 그대로) |
| `text.roles.speaker.timing.lead_s` | `정의` = None | 정의: lead_s = 대사 자막 시작 − 겹치는 말소리 시작 → 대사(dialogue) 외 역할에는 기준 사건이 없음 | 0(계획 plan 의 자막 시각 그대로) |
| `text.roles.title.timing.lead_s` | `정의` = None | 정의: lead_s = 대사 자막 시작 − 겹치는 말소리 시작 → 대사(dialogue) 외 역할에는 기준 사건이 없음 | 0(계획 plan 의 자막 시각 그대로) |

## 4. 해결 방법

1. 네트워크가 열린 컴퓨터(또는 환경 설정에서 youtube.com, *.googlevideo.com, i.ytimg.com, tiktok.com, instagram.com, reddit.com, v.redd.it, dl.fbaipublicfiles.com 허용)에서 AGENTS.md 의 '레퍼런스 분석 실행 순서'를 실행.
2. 효과음 창고·깨끗한 음악 파일을 assets/library/ 또는 local.yaml 경로에 제공.
3. 관찰 경로 키(위 표)는 영상을 본 사람이 manual_observations.csv 에 기록 → `shortkit ref manual-aggregate`.
4. 측정 후 `shortkit preset apply-measurements` → `shortkit preset sync` → `shortkit preset unresolved` 로 이 문서 갱신.
