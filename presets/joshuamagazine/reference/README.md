# reference/ — 레퍼런스 채널 기준 표본과 참고 자료

이 폴더는 `shortkit ref ...` 명령이 쓰는 레퍼런스 채널(@joshuamagazine) 자료다. 손으로 고치지 않는다.

## 파일

| 파일 | 내용 | 만드는 명령 |
|---|---|---|
| `latest100.json` | **제작 측정의 기준 표본**: 분석 시점 최신 100편(목록·게시일·조회수·확인일)을 고정. `ok` 또는 `partial` 스냅샷은 `--refresh-snapshot` 없이는 바뀌지 않는다. `partial` 이면 `missing_members`(메타데이터를 못 받은 구성원 후보와 이유)가 있고, 다음 `ref collect` 가 그 영상만 다시 조회해 **같은 고정 시각 기준으로** 보완한다(`completions` 기록, 이전 판은 `latest100.completed_<시각>.json`). 교체된 스냅샷은 `latest100.replaced_<시각>.json` | `ref collect` |
| `all_videos.json` | 채널 전체 목록(참고). 스냅샷 구성원의 고정 필드(주소·제목·게시일·길이·종류)는 latest100 을 따르고, **조회수는 이번 수집의 최신값**(스냅샷 당시 값은 `view_count_at_snapshot`) | `ref collect` |
| `high_views.json` | 조회수 기준(`reference.high_view_threshold`, 80만) 이상 **채널 전체** 영상. 각 탭 최신 100편 밖이라도 목록 근사 조회수가 기준의 90% 이상이거나 모르는 영상은 영상별 메타데이터로 정확한 조회수를 확인한다. 확인하지 못한 후보는 `unverified`(이유 포함)이고 그때 `status: partial` | `ref collect` |
| `high_views_report.json` / `.md` | **참고용 보고서**: 기준 이상 영상 전부의 분석 범위(받기·시각·오디오·출처 추적)와 영상별 구조·BGM/원음/효과음·출처 요약. 제작 측정에는 섞지 않는다. `status: measured` 는 목록이 완전하고 모든 영상이 받아지고 분석된 경우뿐 | `ref high-views-report` |
| `meta/<id>.json` | 영상별 제목·설명란·태그(출처 추적용). 최신 100편 + 기준 이상 후보 전부 | `ref collect` |
| `videos/`, `downloads.jsonl` | 받은 영상(git 제외)과 sha256·형식 기록 | `ref download` |
| `collect_log.jsonl` | 수집 시도마다 상태·차단 사유 | `ref collect` |
| `web_search_observations.md` | 첫 작업 환경에서 WebSearch 로 본 참고 기록(측정값 아님) | 수동 |

## 기준 표본 규칙 (AGENTS.md 3장 2)

- `measurements/*.json`(`ref aggregate`, `ref audio-measure`, `ref manual-aggregate`, `ref fonts`)과 `formats.yaml`
  (`ref classify build`)은 **latest100 구성원만** 쓴다. 분석된 다른 영상(80만+ 과거 영상 등)은 각 파일의
  `basis.excluded_non_snapshot`(포맷 표는 `outside_snapshot_labels`)에 기록되고 값에 들어가지 않는다.
- 80만+ 영상은 전부 분석하되 그 결과는 `high_views_report.*` 에만 남긴다.

## 분석 순서(네트워크가 열린 컴퓨터)

```bash
python -m shortkit ref collect
python -m shortkit ref download --set latest100
python -m shortkit ref download --set high_views
python -m shortkit ref audio-analyze --set latest100            # BGM·원음·덕킹·음량(제작 측정 기준 100편)
python -m shortkit ref audio-analyze --set high_views_outside   # 참고 보고서용(스냅샷 밖 80만+)
python -m shortkit ref analyze --set downloaded
python -m shortkit ref transcribe                                # 선택: faster-whisper 가 있으면 음성 전사 → analysis/<id>/audio/transcript.json
python -m shortkit ref trace                                     # 기본 대상 = latest100 ∪ high_views ∪ downloaded
python -m shortkit ref high-views-report                         # 80만+ 전체 분석 범위·참고 요약
```

- 효과음 카탈로그(`ref sfx-catalog`)만 스냅샷 **최신 50편**(`reference.sfx_catalog_latest_n`)을 쓴다. Demucs 보컬
  분리가 없으면 대사 밑 효과음은 못 잼이고 카탈로그는 `unmeasured`(개수는 하한값)로 남는다.
- 출처 추적의 "대본"은 레퍼런스 화면 자막(`analysis/<id>/captions.json`) 자체다. 음성 전사는 선택 단계이며,
  설치돼 있지 않으면 아무 파일도 쓰지 않고 못 잼으로 보고한다.
- 출처 추적 단계의 완료 여부는 `warehouse/source_accounts.json` 의 `stage`(설명란·대본·화면 출처 OCR·렌즈·지문 경로별
  범위)로 본다. 계정이 하나 나왔다고 단계가 끝난 것이 아니다.
