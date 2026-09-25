# 새 소재 창고 (warehouse/)

레퍼런스 채널과 **같은 편집 구조**로 만들되 **다른 녹화본**을 쓰기 위한 소재 수집·선별 창고.
흐름: 검색 → 레퍼런스 영상 제외 → 확인된 조회수로 순위 → (직접 보고) 검토 → 선택 → 다운로드(출처 기록).

코드: `shortkit/sourcing/` · 명령: `python -m shortkit source ...` · 인터페이스: `docs/CONTRACT.md` §9, §11

## 파일

| 파일 | 내용 | 누가 쓰나 |
|---|---|---|
| `candidates.jsonl` | 후보 1건 = 1줄. (platform, platform_id) 기준으로 갱신(upsert) | `source search/add-url/review/select/download` |
| `search_log.jsonl` | **모든** 검색 호출: 검색어, 플랫폼, 시각, 요청 URL, 결과 수, 접속 상태(ok/blocked/login_required/error)와 오류 원문 | `source search/add-url` |
| `exclusions.jsonl` | 레퍼런스 영상 지문(pHash)과 URL 규칙 | 레퍼런스 추적 단계, `source exclude-add` |
| `source_accounts.json` | 레퍼런스가 반복해서 쓰는 소스 계정·키워드(추적 결과) | 레퍼런스 추적 단계 (현재 **없음 = 미확보(못 잼)**) |
| `queries.yaml` | 검색어: `reference_derived`(추적분, 손으로 채우지 않음) / `user_generic`(사용자 추가) / `selection`(선택 기준) | `source queries --add` |
| `sources/` | 받은 영상 `<platform>_<id>.mp4` (git 제외, 출처·sha256 은 candidates.jsonl 에) | `source download`, `source add-url --file` |
| `overlays/<sha256>.json` | 소스 파일의 원본 로고·워터마크·원어 자막 기록(`clean detect`, 알고리즘 `shortkit.clean.detect/2`). 워터마크 계정(@handle)은 재업로드 근거로도 쓰임 | `clean detect/plan/apply` |

## candidates.jsonl 필드

| 필드 | 뜻 / 규칙 |
|---|---|
| `id`, `platform`, `platform_id`, `url` | `id = <platform>_<platform_id>` |
| `views` | **플랫폼 메타데이터의 조회수(재생수)만**. 없으면 `null` — 추정하지 않음 |
| `views_checked_at` | 그 조회수를 확인한 시각(UTC). 조회수는 반드시 날짜와 함께 읽는다 |
| `views_source` | `platform_metadata` 또는 `unavailable` |
| `views_field`, `views_history[]` | 숫자를 가져온 필드(view_count/play_count), 확인할 때마다의 기록 |
| `likes`, `likes_checked_at` | 좋아요. **조회수와 별개이며 절대 조회수로 바꾸지 않음** |
| `reddit_score` | Reddit 추천 점수. Reddit 은 공개 조회수가 없어서 `views` 는 항상 `null`. 점수는 **조회수가 아님** |
| `published_at` (+`_source`) | 플랫폼 게시 시각(timestamp 우선, 없으면 upload_date 날짜) |
| `first_seen_at` | 우리가 처음 본 시각. **최근성 판단에 쓰지 않음** |
| `original_author`, `original_author_basis`, `original_url`, `reposter`, `credits[]` | 메타데이터 + 설명의 출처 표기('출처', 'credit', 'via', '@')로 원작자와 재업로더를 나눔(`authorship_base`). 그 위에 재업로드 근거(`repost_evidence[]`)와 검토자의 원본 업로드 답을 적용. 근거(`basis`)를 함께 기록. 크레딧·근거가 없으면 업로더를 원작자로 두되 "원작자 여부 미확인"으로 표시 |
| `repost_evidence[]` | 화면에 박힌 계정 표시 `{handle, variants, sources[], where, same_as_uploader}`. 출처: 다운로드 때 모서리 OCR(`download_ocr_hint`), `clean detect` 기록(`clean_detect:ov1`), 검토자의 `--watermark-handle`. 업로더와 **다른** 계정이면 재업로드: `reposter`=업로더, `original_author`=그 계정(basis `watermark_ocr(...)`, 그 계정이 원작자인지는 미확인) |
| `alternates[]`, `alternate_of[]` | 같은 녹화의 깨끗한 원본 연결(`source link-original`): `{id, linked_by, linked_at, note, basis}`. `clean plan` 이 1순위(원본 교체)로 씀 |
| `manual_provenance[]`, `views_manual`, `original_author_hint` | 플랫폼이 막혀 사람이 직접 확인한 출처(`add-url --observed-by ...`). 플랫폼 메타데이터와 따로 기록: `views` 는 계속 플랫폼 값만, 사람이 본 조회수는 `views_manual {views, checked_at, observed_by, where}` |
| `extra.uploader_source` | 업로더를 어디서 알았나: `url_path`(URL 의 @계정), `manual_observation:<이름>` |
| `duration`, `width`, `height`, `fps`, `orientation` | 길이·해상도·방향(세로/가로/정사각) |
| `download_path`, `sha256`, `download{}` | 루트 기준 상대 경로, 파일 해시, 받은 방법·형식(format_id, 코덱, tbr)·ffprobe 결과. 실패도 `download.status=failed` 로 기록 |
| `quality{}` | 받은 파일에서 측정: 해상도, 비트레이트, bpp, 선명도(Laplacian 분산), 워터마크 힌트(모서리 OCR) |
| `reference_overlap{}` | `excluded`(true/false/null=못 잼), `matched_video_id`, `method`, `distance`, 일치 키프레임 수, 확인 시각 |
| `reviews[]` | 영상을 **직접 본** 사람/에이전트의 기록: `watched_by`, `watched_at`, `intensity`, `reversal`, `format_fit`(1-5), `notes`, `watermark`, `original_upload`(yes/no/unknown: 원본 업로드인가), `watermark_handle` |
| `scores{}` | `recency`, `intensity`, `reversal`, `quality`, `format_fit`, `total`, `recency_label`, `age_days`, `upload_age_days`, `originality`, `unmeasured[]` |
| `selection_reason` | 선택 이유 문장. 저장된 필드 값으로만 만들어짐 |
| `status` (+`status_history`) | `candidate`/`selected`/`rejected`/`used`/`excluded` |
| `access{}` | 마지막 플랫폼 접속 결과 `platform_status`(ok/blocked/login_required/error), 오류 원문 `note`, 시각 |

## 규칙 (코드에서 강제됨)

1. **조회수는 날짜와 함께**: `views` 는 항상 `views_checked_at` 과 한 쌍. 나중에 조회수 없이 다시 받아도 확인된 값은 지우지 않음.
2. **좋아요 ≠ 조회수**: `likes`, `reddit_score` 는 따로 저장. 순위·선택 이유 어디에서도 조회수로 쓰지 않음.
3. **순위는 플랫폼별, 확인된 조회수로만**: 조회수를 모르는 후보는 순위 없이 뒤에 `views_unknown` 표시로 나열. 사람이 게시 페이지에서 직접 본 조회수(`views_manual`, 본 사람·날짜 필수)도 확인된 값으로 같이 순위에 넣되 `views_manual_observation` 로 표시. `source list --sort views` 의 `--limit` 은 **플랫폼마다** 적용(한 플랫폼 후보가 많아도 다른 플랫폼 순위가 가려지지 않음, 가려진 수를 표시).
4. **오래된 바이럴은 최근이 아님**: 최근성은 확인 시각 기준 게시일 경과일로만 판정(기본 30일, `queries.yaml` 의 `selection.recent_days`). 조회수나 우리가 처음 본 날짜는 영향을 주지 않음. 게시일을 모르면 "게시일 모름"(최근 아님).
   - **재업로드**(원작자 ≠ 업로더, 원본 URL 이 따로 있음, 화면에 **다른 계정 워터마크**가 박힘, 또는 검토자가 `--original-upload no`)는 재업로드 날짜가 아니라 원본 게시일로 판정하며, 원본 게시일을 모르면 "재업로드: 원본 게시일 모름"(최근 아님). 원본 게시일은 검토 때 `--original-published-at`.
   - 크레딧도 워터마크도 없는 영상은 메타데이터만으로 옛 바이럴 재업로드와 구분할 수 없음 → 게시일이 최근이어도 영상을 본 검토자가 `--original-upload yes` 로 답하기 전에는 "최근 게시 — 원본 업로드인지 미확인"(최근성 못 잼). 게시일이 오래됐으면 답과 상관없이 "오래됨".
   - 워터마크 계정은 OCR 오차를 허용해 업로더와 비교(같은 계정의 워터마크는 재업로드 근거가 아님). 검토자의 `--original-upload yes` 는 워터마크 근거보다 우선하지만(예: 같은 사람의 옛 계정), 설명란이 다른 계정을 출처로 밝힌 경우는 그대로 재업로드.
5. **같은 키워드는 괜찮지만 같은 녹화는 제외**: 후보 키프레임 pHash 가 레퍼런스 지문과 해밍 거리 ≤ 10 인 키프레임이 3장 이상이면 제외. 원본/좌우 반전/세로 영상 가운데 16:9 띠를 모두 비교하고 검은 여백은 잘라서 비교. URL(원본 URL 포함)이 같아도 제외. 지문이 없으면 `excluded=null`(못 잼) — "다름"으로 치지 않음. 다운로드/파일 연결 때마다 자동 검사.
6. **검토 없이는 선택 불가**: 사건 강도·반전·형식 적합은 영상을 직접 본 사람의 기록(`watched_by` + `notes` + 1-5 점수)이 있어야 측정된 것으로 봄. 없으면 못 잼이며 `select` 가 거부함(상태 변경 함수 자체가 막으므로 우회 경로 없음). 제외된 후보는 어떤 경우에도 선택 불가, `used` 는 선택된 후보만.
7. **못 잼 항목은 명시적으로만 넘김**: 레퍼런스 중복 여부·게시일·화질이 못 잼이면 `select` 가 거부. 알고도 고르려면 `--accept-unmeasured <항목> --reason "..."` 를 줘야 하고, 그 사실과 사유가 `selection.accepted_unmeasured` 와 `selection_reason` 에 남음. 종합 점수(`total`)는 모든 항목이 측정됐을 때만 계산.
8. **차단은 차단으로 기록**: 막힌 플랫폼은 `blocked`, 로그인이 필요하면 `login_required`, 그 외는 `error` 와 오류 원문을 기록하고 다음 플랫폼/후보로 넘어감. 성공한 척하지 않음. 우회(미러·프록시·Invidious 등)하지 않음. yt-dlp 가 **작동 안 함**으로 표시한 추출기(`tiktok:tag`, `instagram:user`)가 빈 목록을 주면 "결과 0건"이 아니라 `error`(못 잼)로 기록하고 대안 경로를 적음.
9. **경로는 루트 기준 상대 경로만** 저장.
10. **막힌 플랫폼의 수동 수집도 출처를 남김**: `add-url` 은 URL 의 계정(`tiktok.com/@계정/video/...`, `instagram.com/<계정>/reel/...`, `youtube.com/@계정`)을 업로더로 기록. 사람이 게시 페이지에서 본 원작자·업로더·게시일·원본 URL·조회수는 `--observed-by` 와 함께 넣고, 플랫폼 메타데이터와 따로(`manual_provenance[]`) 기록. 나중에 받은 플랫폼 메타데이터가 있으면 그 값이 우선.
11. **깨끗한 원본이 1순위**: 워터마크·자막 붙은 후보와 같은 녹화의 깨끗한 원본을 찾으면 `source link-original` 로 연결. `clean plan` 이 원본의 오버레이를 따로 검사해 깨끗하면 **원본 교체** 블록(`path`·`sha256`·`warehouse_id` 모두 원본 것)을 출력. 교체 원본도 검토·선택(selected)된 후보여야 production 에서 쓸 수 있음.

형식 적합(`format_fit`)은 검토자가 매기지만, 참고용 "형식 사실"(방향, 소스 길이 vs 레퍼런스 출력 길이 분포
`structure.duration_s` 의 p10 — 프리셋 API 로 읽음, 프리셋 이름은 `queries.yaml` 의 `selection.preset`)을 함께 계산해
선택 이유에 적는다. 소스가 레퍼런스 p10 보다 짧으면 "짧음"(반복·늘리기로 채우면 안 됨)으로 표시. 분포가 미측정이면 못 잼.

선택 점수의 정규화(해상도 짧은 변 1080 = 1, bpp 0.05 = 1, 선명도 150 = 1, 워터마크 있으면 ×0.7)와 가중치는
이 도구가 정한 제작 기준이며 레퍼런스 측정값이 아니다(`queries.yaml` 의 `selection` 에서 조정).

## 플랫폼별 수집 방식

| 플랫폼 | 검색 | 조회수 | 비고 |
|---|---|---|---|
| YouTube | yt-dlp `ytsearchN:` (최근: `ytsearchdateN:`) 목록 → 항목별 전체 메타데이터 | `view_count` | 목록의 대략적 조회수는 쓰지 않음 |
| TikTok | 키워드 → 해시태그 `tiktok.com/tag/<tag>`(yt-dlp 에 TikTok 키워드 검색이 없음), `@user`, 영상 URL | `view_count`/`play_count` (재생수) | 설치된 yt-dlp(2026.08.19)가 `tiktok:tag` 추출기를 작동 안 함으로 표시 → 빈 목록이면 `error`(0건 아님). **되는 경로**: 레퍼런스 추적 계정 `@user`(tiktok:user), 찾은 영상 URL 의 `add-url`. 날짜 필터 없음(최근: 게시일로 거름) |
| Instagram | 게시물/릴스 URL. 해시태그·계정은 로그인 필요 | 메타데이터에 있을 때만 | `local.yaml` 의 `sourcing.cookies.instagram` 이 없으면 요청하지 않고 `login_required`. `instagram:user`(계정 목록)는 yt-dlp 가 작동 안 함으로 표시 → 빈 목록이면 `error`; 해시태그(쿠키) 또는 게시물 URL 로 |
| Reddit | `https://www.reddit.com/search.json?q=..&sort=top&t=month` (최근: `sort=new&t=week`), 설명적인 User-Agent | 없음(항상 `null`) | 영상 게시물만(v.redd.it, rich:video, 알려진 영상 호스트). 외부 링크는 `original_url` |

`local.yaml`(git 제외, 기계별) 예:
```yaml
sourcing:
  cookies: {instagram: cookies_instagram.txt}   # 루트 기준 또는 절대 경로
  user_agent: "python:mychannel-sourcing:0.1 (by /u/내계정)"
```

## 작업 순서

```bash
python -m shortkit source queries                         # 검색어(레퍼런스 추적분은 현재 미확보(못 잼))
python -m shortkit source queries --add "검색어" --platform youtube tiktok
python -m shortkit source search -q "검색어" --platform all --limit 10 [--recent]
python -m shortkit source log                             # 모든 검색과 접속 상태
python -m shortkit source list --sort views               # 플랫폼별 확인된 조회수 순위(모르는 것은 뒤)
python -m shortkit source add-url URL [--file 직접받은.mp4]  # 수동 수집(URL 의 @계정 = 업로더로 기록)
#   막힌 플랫폼에서 사람이 직접 본 정보: --observed-by 이름 [--uploader @계정] [--original-author @원작자]
#   [--original-url URL] [--published-at 날짜] [--original-published-at 날짜] [--views N --views-checked-at 날짜]
python -m shortkit source download ID [ID ...]            # sources/<platform>_<id>.mp4 + sha256 + 중복 검사
python -m shortkit source exclude-check ID|파일           # 레퍼런스와 같은 녹화인지
python -m shortkit source review ID --watched-by 이름 --intensity 4 --reversal 3 --format-fit 5 --notes "본 내용" \
    --original-upload yes|no [--watermark-handle @계정] [--original-published-at 날짜]   # 원본 업로드인가?
python -m shortkit source select ID [--accept-unmeasured reference_overlap --reason "..."]
python -m shortkit source list --sort score               # 검토된 후보 종합 순위
python -m shortkit source use ID --episode <에피소드 id>     # 사용 기록(status used)
```
에피소드 `plan.yaml` 의 `sources[]` 에는 `path`(= `download_path`), `sha256`, `warehouse_id`(= `id`)를 적는다.

### 원본 로고·자막 정리 (1순위 깨끗한 원본 → 2순위 잘라내기 → 3순위 국소 복원)

```bash
python -m shortkit clean detect --source warehouse/sources/<파일>   # overlays/<sha256>.json (다른 계정 워터마크면 후보에 재업로드로 기록)
# 깨끗한 원본을 찾았으면(원본 URL·원작자 계정·렌즈):
python -m shortkit source add-url <원본 URL> [--file 원본.mp4]  &&  python -m shortkit source download <원본 ID>
python -m shortkit source link-original <더러운 ID> <원본 ID> --by 이름 --note "두 영상 모두 봄: 같은 장면"
python -m shortkit clean plan --source warehouse/sources/<더러운 파일>   # 원본이 깨끗하면 '원본 교체' 블록, 아니면 잘라내기/복원
#   출력 블록(path·sha256·warehouse_id·clean·protected)을 plan.yaml 의 sources[] 에 **통째로** 붙인다
#   (path/sha256 만 바꾸고 warehouse_id 를 두면 validate 가 provenance_sha_mismatch). 원본이 없으면 찾는 방법을 제안함.
python -m shortkit clean coverage --plan episodes/<id>/plan.yaml     # clean 블록이 기록된 오버레이를 모두 덮는지(아니면 exit 1)
```
`clean coverage` 는 타임라인이 쓰는 원본 구간만 검사하고(`--all-time` 은 전체), 이전 검출 알고리즘 기록·기록 없음은
오류로, OCR 못 잼·확인 필요 후보는 경고로 보고한다. `clean plan` 도 출력 직후 같은 검사를 한다.

## 현재 상태 (2026-09-24, 이 작업 환경)

- youtube.com / tiktok.com / reddit.com 은 네트워크 정책으로 차단(프록시 CONNECT 403). 실제 검색 1회를 실행했고
  `search_log.jsonl` 에 `blocked`(Instagram 은 쿠키 없음 → `login_required`, 요청 안 함)로 기록됨. 실제 플랫폼 응답으로는
  한 번도 검증하지 못했다(합성 데이터로만 단위 테스트).
- `exclusions.jsonl` 의 레퍼런스 지문, `source_accounts.json` 모두 없음 → 레퍼런스 중복 검사와 레퍼런스 추적 검색어는 못 잼.
