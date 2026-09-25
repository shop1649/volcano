# 납품물 위치 (요청문 11절)

요청문(`docs/REQUEST.md`) 11절의 납품물이 어디에 있는지, 그리고 **무엇이 테스트용인지** 정리한다.

> **먼저 알아 둘 것.** 첫 작업 환경(2026-09-24~25)의 네트워크 정책이 YouTube·TikTok·Instagram·Reddit·Google Lens·Demucs 가중치
> 호스트를 막았다. 그래서 레퍼런스 영상은 한 편도 받지 못했고, 플랫폼에서 새 소재도 받지 못했다.
> 이 저장소의 영상·편집 프로젝트·QA 결과는 **모두 테스트 모드(`mode: test`)** 다. 공개(CC BY 4.0) Intel 샘플 영상과 합성 소리로
> 파이프라인을 검증한 것이며, 게시용 쇼츠가 아니다. 게시용(production) 에피소드는 **0편**이다. 프리셋이 미측정 상태라
> `episode render` 가 production 모드를 거부하고, `qa gate --production` 도 통과시키지 않는다.

## 1. 영상 (최종 MP4)

| 파일 | 소스 | 모드 | 비고 |
|---|---|---|---|
| `episodes/test-pipeline-001/output/test-pipeline-001.mp4` | Intel `classroom`(+ espeak-ng TTS 한 줄) + `head-pose-face-detection` (CC BY 4.0) | test | 19.25 s, 1080×1920 30 fps. QA 관문 통과, 완료 아님 |
| `episodes/test-coverage-001/output/test-coverage-001.mp4` | Intel `people-detection` + `face-demographics-walking-and-pause` (CC BY 4.0) | test | 22.5 s. QA 관문 **실패**(G2: 반전 보호·고정 카메라 소스의 글자 없는 로고 — 사람 확인 필요) |
| `episodes/test-restore-001/output/test-restore-001.mp4` | 깨끗한 폴더에 번들을 복원한 뒤 앞의 두 편과 **다른** 소스로 만든 편. 소스는 로고·출처 표시·원어 자막을 일부러 합성한 `dirty-source` 로, 오버레이 제거 단계까지 거친다 | test | 18.50 s. QA 관문 **실패**(G2 12건: 사람 확인 필요 — 반전, 글자 없는 로고 10, 복원이 손을 덮음 1). 기록: `docs/validation/final_restore_log.md` |

영상마다 평가 모드, 소스 출처, 해시가 `episodes/<id>/qa/report.json` 의 `inputs`, `output` 에 있다.

## 2. 편집 가능한 프로젝트

`episodes/<id>/project/`:

| 파일 | 열 수 있는 프로그램 | 검증 |
|---|---|---|
| `<id>.mlt` | Shotcut (MLT XML) | **melt 로 실제 렌더해 마스터와 1초 격자 비교**. test-pipeline-001 SSIM 0.9975 · 소리 포락선 상관 0.9966, test-coverage-001 SSIM 0.9923 · 0.9999, test-restore-001 SSIM 0.9942 · 0.9998 (`verify.json`) |
| `<id>.fcpxml` | DaVinci Resolve / Final Cut Pro (FCPXML 1.9) | **못 잼**: 이 기계에 두 프로그램이 없음. 형식·시간 일관성만 테스트 |
| `<id>.otio` | OpenTimelineIO 를 읽는 편집기(Kdenlive 등) | **못 잼**: 자체 렌더러 없음. 쓰기→읽기 왕복만 테스트 |
| `captions.ass` | Aegisub / 텍스트 편집기 | 마스터 렌더가 쓴 파일과 같음 |
| `captions.srt` | 아무 편집기 | 텍스트·시간만 |
| `README.md` | — | 이 프로젝트에서 편집할 수 있는 것과 없는 것(아래 3절), 검증 수치 |
| `export_decisions.json`, `verify.json` | — | 내보내기 결정과 melt 대조 결과 |

`project/media/`(정지 프레임 PNG 같은 중간 파일)와 소스 영상(`assets/test/generated/`)은 용량 때문에 git 에 넣지 않았다.
다시 만들려면 `python -m shortkit testassets fetch-video ...`, `python -m shortkit episode export <id>` 를 실행한다.
test-restore-001 은 소스를 `python -m shortkit testassets dirty-source --video face-demographics-walking-and-pause.mp4
--out dirty_source_facewalk` 로 먼저 만든다. 이 컴퓨터에서는 같은 sha256 `b861fc2d…` 로 다시 만들어졌다.
명령은 `docs/validation/final_restore_log.md` 에 있다.

## 3. 미리 합성되어 개별 편집이 안 되는 부분

- **자막과 장식(화살표 등)은 `captions.ass` 한 파일, 한 레이어**로 그려진다. 마스터와 같은 libass 를 쓴다.
  NLE 의 개별 텍스트 클립이 아니다. 글자·위치·시간·스타일은 `captions.ass` 를 고친 뒤 다시 렌더하거나 내보내야 한다.
- **정지(freeze)** 는 원본의 한 프레임을 이미지로 뽑아 이미지 클립으로 넣는다. melt 의 freeze 필터는 렌더가 멈춰서 쓰지 않았다.
- **로고 국소 복원(inpaint)과 blur** 는 FCPXML 로 표현할 수 없어 미리 정리한 중간 파일로 대체된다. MLT 에서는 crop/delogo 수치로 남는다.
- **효과음·원본 소리의 안전 리미터** 는 마스터에서 샘플 단위로 걸린다. 편집 프로젝트에서는 프레임 단위 음량 키프레임으로 근사한다.
- 에피소드별 목록은 각 `project/README.md` 의 "굽혀 있어(미리 합성되어) 개별 편집이 안 되는 것" 절에 있다.

## 4. 실행 가능한 프리셋

| 경로 | 내용 |
|---|---|
| `shortkit/` | 제작 시스템 코드(`python -m shortkit <영역> <명령>`) |
| `presets/joshuamagazine/preset.yaml` | 고정 스타일. **모든 값이 임시값(못 잼)** |
| `presets/joshuamagazine/settings_registry.yaml` | 설정마다 근거→측정값→제작 코드→출력 검사의 연결. `preset audit --test` 결과는 no_code 0 · no_qa 0 · 미측정 266 |
| `presets/joshuamagazine/requested_changes.yaml` | 사용자가 지정한 변경. 요청문에서 비어 있어 **비어 있음** |
| `presets/joshuamagazine/unresolved.md` | 미확정 항목, 제작 영향, 해결 상태 |
| `AGENTS.md` (Codex) / `CLAUDE.md` (Claude Code) | 두 에이전트가 함께 쓰는 실행 지침(5장 A → B → C) |
| `scripts/setup.sh`, `scripts/setup.ps1`(미검증) | 설치. `python -m shortkit doctor --network` 로 점검 |
| `PRESET_BUNDLE.md` | 다른 컴퓨터용 단일 MD. 맨 위의 복원 블록을 실행하면 내장 페이로드가 풀린다. 에이전트가 페이로드를 읽지 않아도 된다 |
| `docs/CONTRACT.md` | 모듈 사이 인터페이스 계약 |

## 5. 소재 창고

| 경로 | 내용 |
|---|---|
| `warehouse/README.md` | 창고 규칙(조회수와 확인일은 한 쌍, 좋아요≠조회수, 최근성은 원본 업로드 확인이 있어야 함, 출처 필드) |
| `warehouse/search_log.jsonl` | 플랫폼 검색 시도와 **차단 기록**(403 원문) |
| `warehouse/queries.yaml` | 검색어. 레퍼런스 역추적분은 비어 있음(추적 못 함) |
| `warehouse/source_accounts.json` | 레퍼런스가 쓰는 소스 계정. **못 잼**(레퍼런스 미확보) |
| `warehouse/candidates.jsonl` | 후보(첫 후보가 들어올 때 생김). 이 환경에서는 플랫폼 접속이 전부 막혀 **0건이라 파일이 없다**. 테스트 소스는 창고가 아니라 `assets/test/generated/` 로 받음 |

## 6. 비교 시트와 QA 결과

| 경로 | 내용 |
|---|---|
| `episodes/<id>/qa/report.md`, `report.json` | 최종 MP4 기준 검수표. 같다/다르다/못 잼, 의도한 변경과 미재현 결함을 구분, 관문 결과 |
| `episodes/<id>/qa/compare_sheet*.png` | 1초 격자 비교 시트(자막 띠 + 0.5초 효과음 띠). 레퍼런스가 없어 레퍼런스 열은 "못 잼" |
| `episodes/<id>/qa/defects.jsonl` | 결함별 고침 → 같은 사례 재검사 → 최종 관문 |
| `docs/validation/mockloop.md`, `mockloop_compare_sheet_p01.png` | **합성** 레퍼런스(참값을 아는 5편)로 레퍼런스와 같은 절대 시각 비교까지 돌린 기록. 실제 채널 영상이 아님 |

QA 요약(테스트 모드):

| 에피소드 | 행 | 같다 | 다르다 | 못 잼 | 관문 |
|---|---|---|---|---|---|
| test-pipeline-001 | 273 | 184 | 0 | 89 | 통과, 완료 아님(P1 미측정 프리셋, R1 레퍼런스 비교 없음) |
| test-coverage-001 | 226 | 151 | 0 | 75 | 실패(G2 6건: 사람 확인 필요) |
| test-restore-001 | 249 | 164 | 0 | 85 | 실패(G2 12건: 사람 확인 필요 — 그중 1건은 국소 복원이 손을 덮은 곳) |

"못 잼"은 완료로 올리지 않는다. 오디오는 모두 기계 측정이다. **사람이 들어서 확인한 것은 없다(사람 청취 필요).**

## 7. 레퍼런스 분석 결과

| 경로 | 상태 |
|---|---|
| `presets/joshuamagazine/reference/latest100.json` | status `blocked`(yt-dlp 403 원문). 최신 100편 목록·게시일을 고정하지 못함 |
| `presets/joshuamagazine/reference/high_views.json`, `high_views_report.{json,md}` | 조회수 80만 이상 목록과 분석 현황. **못 잼**(채널 목록 미확보) |
| `presets/joshuamagazine/reference/web_search_observations.md` | 웹 검색 스니펫. 미검증 참고용이며 측정값으로 쓰지 않음 |
| `presets/joshuamagazine/measurements/*.json`, `formats.yaml`, `sfx_catalog.json`, `fonts_report.json` | 전부 못 잼. 이유(blocker)가 기록됨 |

## 8. 첫 편 기획안(승인용)

실제 첫 편 기획안(소재·구간 시트·표지 문구·제목 후보 3종·효과음 배치표)은 **아직 만들 수 없다**. 레퍼런스 측정값(포맷·효과음 분포)과
플랫폼에서 받은 새 소재가 둘 다 없기 때문이다. 기획안 양식은 테스트 에피소드의 `episodes/<id>/proposal.md` 에서 볼 수 있다.
네트워크가 열린 환경에서 `AGENTS.md` 5장 A → B 를 마친 뒤 `episode proposal` 로 만든다.
