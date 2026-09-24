# AGENTS.md — 쇼츠 제작 프리셋 시스템 (Claude Code · Codex 공통 지침)

이 파일은 Claude Code(`CLAUDE.md` 가 이 파일을 불러옴)와 Codex(`AGENTS.md` 를 직접 읽음)가 **같은 규칙**으로
작업하도록 만든 공통 지침이다. 사람이 읽어도 된다.

## 1. 무엇을 하는 저장소인가

레퍼런스 채널 <https://youtube.com/@joshuamagazine> 의 **편집 구조**를 그대로 따르되 **다른 촬영본**으로 쇼츠를 만드는
재사용 가능한 제작 시스템이다.

```
새 소재 탐색 → 선별 → 대본·컷 구성(plan.yaml) → 편집(렌더 + 편집 프로젝트) → 출력 검수(최종 MP4 기준 QA)
```

원 요청문: `docs/REQUEST.md` (모든 검수 기준의 근거).

구성: 파이썬 패키지 `shortkit`(명령: `python -m shortkit <영역> <명령>`), 채널 프리셋 `presets/joshuamagazine/`,
소재 창고 `warehouse/`, 에피소드 `episodes/<id>/`, 인터페이스 계약 `docs/CONTRACT.md`.

## 2. 현재 상태 — 먼저 읽을 것

- **레퍼런스 측정값이 아직 하나도 없다.** 2026-09-24 첫 작업 환경의 네트워크 정책이 youtube.com / googlevideo.com /
  i.ytimg.com / tiktok / instagram / reddit / Google Lens / Demucs 가중치 호스트를 차단했다(`PROGRESS.md`,
  `presets/joshuamagazine/unresolved.md`, `presets/joshuamagazine/reference/latest100.json` 의 blocker 기록).
- 그래서 `presets/joshuamagazine/preset.yaml` 의 스타일 값은 전부 **임시값(provisional)** 이다. 레지스트리
  (`settings_registry.yaml`)에서 상태가 `unmeasured`(못 잼)이다. production 렌더와 QA 최종 관문은 이 상태에서 통과하지 않는다.
- 파이프라인 자체(렌더·편집 프로젝트·QA·분석기·소재 창고·로고 제거)는 합성/공개 테스트 소스로 실제 실행해 검증했다.
  검증 범위는 `docs/VALIDATION.md`.
- 네트워크가 열린 컴퓨터에서 아래 **5장 A → B → C** 순서대로 실행하면 미측정 항목이 채워진다.

## 3. 절대 규칙 (사용자 요구사항 — 위반 시 작업 실패)

1. 접근·측정하지 못한 항목을 추측으로 채우거나 완료라고 하지 않는다. `못 잼` 으로 두고 제작 영향과 해결 상태를 기록한다.
2. 기준 표본: 분석 시점의 **최신 100편**을 `reference/latest100.json` 에 고정(목록·게시일). 전체 영상은 참고이며 충돌 시 최신 100편 우선.
   조회수 80만 이상 영상은 `reference/high_views.json` 으로 전부 분석한다.
3. 수치 항목은 전체 및 포맷별 p10/p50/p90 + 표본 수. 좌표는 해상도와 함께 저장.
4. 모션·전환·BGM·원음은 있다/없다/못 잼.
5. 모든 설정은 "근거 영상·시각 → 측정값 → 제작 코드의 설정 → 출력 검사"로 연결된다. `shortkit preset audit` 이 연결되지 않은
   설정(보고서에만 있는 값)을 잡아낸다. 고정 스타일(preset)과 새 소재마다 다시 판단할 좌표·시각(plan)을 분리한다.
6. 소재는 반드시 레퍼런스와 **다른 촬영본**. 원 채널의 채널명·로고 등 고유 식별 요소는 복제하지 않는다
   (`identity_exclusions`, QA 가 OCR 로 검사). 다른 프로젝트의 프리셋을 섞지 않는다(`preset_id` 가드).
7. 사용자가 별도로 지정한 변경은 `requested_changes.yaml` 에만 넣는다. QA 표에서 "의도한 변경"과 "미재현 결함"을 구분한다.
   (2026-09-24 요청문에는 별도 변경이 비어 있었다.)
8. 자막: 장면을 실제로 보고 들은 뒤 작성. 짧고 자연스러운 한국어. 영상에 없는 관계·동기·대사 금지(`grounding` 필수).
   역할 구분: 제목 / 설명 / 상황 설명 / 인물 식별 / 실제 대사 / 반응·효과. 반전을 미리 말하지 않는다(`reveal` 가드).
   얼굴·손·핵심 물체를 가리지 않는다(`protected`). 의미가 끝난 꼬리는 자르되 중요한 동작은 자르지 않는다.
   같은 효과를 연속으로 쌓거나 분량을 채우려 반복하지 않는다.
9. BGM: 곡명·버전·속도·실제 사용 구간까지 확인(같은 곡의 다른 부분은 불일치). 깨끗한 음악 파일만 사용(레퍼런스에서 분리한 음원 금지).
10. 원본 소리는 기본 OFF. 중요한 대사·말하는 구간만 살린다. 원본에 붙은 음악은 분리 후 음질 검사. 덕킹은 보존한 대사 구간에서만.
    효과음이나 컷은 덕킹 이유가 아니다. **직접 듣지 못했으면 청취 검수 완료라고 하지 않는다**(에이전트는 소리를 듣지 못한다 —
    자동 측정 결과와 "사람 청취 필요"를 구분해 적는다).
11. 효과음은 사건 때문에 넣는다(컷 때문이 아님). 사건 없는 효과음 0개, 사건과 ±0.3초 이내, 편당 개수·종류 분포는 포맷 관측 범위.
12. 원본 로고·출처 오버레이·원어 자막은 최종 화면에 남기지 않는다(상단 좌우·내부 컷 검사). 순서: 깨끗한 원본 → 크롭 → 국소 복원.
    로고 때문에 인물·동작을 잘라내지 않는다. 출처 기록은 따로 보존.
13. 첫 편만 기획(소재·구간 시트·표지 문구·제목 후보 3종·효과음 배치표)을 제시하고 **승인 뒤 렌더**. 승인된 기획·수정은 재승인 불요.
    첫 편에서 확인된 수정은 프리셋과 후속편에 함께 반영. 이후는 지정 포맷·편수까지 불필요한 질문 없이 완료.
14. 검수는 최종 MP4 기준. 레퍼런스 1편과 같은 절대 시각 1초 격자 비교, 자막 띠 아래 0.5초 효과음 띠. 같다/다르다/못 잼.
    못 잰 항목은 완료로 승격하지 않는다. 결함마다 고침·동일 사례 재검사·최종 관문 결과를 남긴다.
15. 플랫폼 접근이 막히면 성공한 척하지 말고 다른 경로로 소재 확보를 계속한다. 차단을 우회(미러·프록시 등)하지 않는다.
16. 컨텍스트가 차기 전에 `PROGRESS.md` 에 진행 기록과 재개 지점을 쓰고 커밋한다.

## 4. 초기 설정

```bash
bash scripts/setup.sh            # Linux/macOS: .venv + 파이썬 의존성 + 글꼴 받기 + doctor
#   --with-apt (Ubuntu) / --with-brew (macOS) 로 시스템 프로그램 설치, --demucs 로 효과음 카탈로그용 demucs 설치
powershell -File scripts/setup.ps1   # Windows (미검증)
python -m shortkit doctor --network  # 필수 프로그램·의존성·글꼴·플랫폼 접속 점검 (로그인은 자동으로 되지 않음)
cp local.example.yaml local.yaml     # 효과음/음악 창고, 쿠키 경로
```

필수: Python ≥3.10, ffmpeg/ffprobe(libass, libx264), tesseract + kor. 선택: melt(편집 프로젝트 렌더 검증), demucs+torch
(효과음 카탈로그), fpcalc, espeak-ng(테스트 TTS).

## 5. 실행 순서

(명령 상세는 각 `python -m shortkit <영역> -h`.)

### A. 레퍼런스 분석 (네트워크 필요)

먼저 `python -m shortkit doctor --network` 로 youtube.com·googlevideo.com 접속을 확인한다. 막혀 있으면 A 는 진행하지 말고
그 사실을 기록한다(성공한 척 금지).

```bash
python -m shortkit ref collect                     # 최신 100편·게시일·조회수 고정 → reference/latest100.json (이미 ok 스냅샷이면 유지)
                                                   #   + all_videos.json(참고), high_views.json(조회수 ≥ 800,000, 확인일 포함)
python -m shortkit ref download --set latest100    # 영상 받기(≤1080p, 소리 포함) → reference/videos/, downloads.jsonl(sha256)
python -m shortkit ref download --set high_views   # 80만 이상 영상 전부
python -m shortkit ref analyze  --set downloaded   # 컷·자막(위치/크기/색/외곽선/박스/모션/역할)·화면 모션 → analysis/<id>/
python -m shortkit ref audio-analyze --all         # 최신 50편: Demucs 분리 → BGM 식별 → 원음·덕킹 → 효과음 이벤트
python -m shortkit ref classify prepare --set latest100   # 영상별 검토 자료 + format_labels.csv(빈 줄)
#  ▶ 에이전트/사람이 analysis/<id>/review/ 를 "실제로 보고" format_labels.csv 를 채운다
#    (intro_type=도입 방식, structure_type=전개 구조, watched=yes, labeled_by=이름). 안 본 영상은 채우지 않는다.
python -m shortkit ref classify build              # formats.yaml: 전개 구조별 포맷, 도입만 다른 것은 intro_variants, 대표 영상
python -m shortkit ref aggregate                   # measurements/visual_*.json (전체·포맷별 n/p10/p50/p90, 해상도, 근거 시각)
python -m shortkit ref audio-measure               # measurements/audio.json (BGM 곡·버전·속도·구간·크기·반복, 덕킹, 음량, 원음·정적 페이드, 효과음 크기)
#  ▶ 자동 측정이 안 되는 항목(장식 스타일·이모지·표지)은 영상을 본 사람이 manual_observations.csv 에 (video_id, t, key, value,
#    observed_by, watched=yes) 로 기록 → 
python -m shortkit ref manual-aggregate            # measurements/manual.json
python -m shortkit ref fonts                       # 글꼴: IoU 상한(같은 글꼴의 한계) 먼저 → 후보 검증(동일/유사/다름)
python -m shortkit ref sfx-catalog --emotion-template   # 효과음 카탈로그(편당 개수 p10/p50/p90, 직전 자막, 화면 사건, 감정, 자리 규칙, 표본 3편)
#  ▶ 감정(emotion)은 영상을 본 사람이 sfx_emotion_labels.csv 에 채운 것만 사용
python -m shortkit ref sfx-map                     # 효과음 창고(local.yaml sfx_library_root)와 연결: 있음/없음/못 잼
python -m shortkit ref bgm-identify --video <id>   # 깨끗한 음악 창고(assets/library/music/index.yaml)와 대조
python -m shortkit ref trace                       # 설명란·워터마크 OCR·렌즈용 키프레임 → warehouse/source_accounts.json, exclusions.jsonl
python -m shortkit preset apply-measurements       # 측정값 → measured.yaml (preset.yaml 은 그대로, 층으로 덮음)
python -m shortkit preset sync                     # 레지스트리: 근거→측정값→코드→검사 연결 갱신
python -m shortkit preset audit                    # 미측정·코드 미연결·검사 미연결 키 확인
python -m shortkit preset unresolved               # unresolved.md 갱신
```

- `ref collect/download/analyze/aggregate/trace/classify` 의 종료 코드 3 = 레퍼런스 데이터 없음(차단/비어 있음). 못 잼 파일은 기록된다.
- Google Lens 는 자동화하지 않는다: `analysis/<id>/lens/` 키프레임으로 사람이/에이전트가 검색한 결과를 `source add-url` 로 넣는다.
- BGM 은 곡명만 맞으면 안 된다: `bgm.json` 의 track·version·tempo·section 네 항목이 모두 일치해야 일치.


### B. 새 소재 창고

```bash
python -m shortkit source queries                  # 검색어: 레퍼런스 역추적분(source_accounts.json) + 사용자 추가분
python -m shortkit source search -q "<키워드>" --platform youtube tiktok instagram reddit --limit 30 [--recent]
python -m shortkit source log                      # 플랫폼별 접속 상태(ok/blocked/login_required) — 막히면 다른 플랫폼/수동 URL 로 계속
python -m shortkit source add-url <URL> [--file <직접 받은 파일>]   # 수동 수집(렌즈·다른 경로로 찾은 원본)
python -m shortkit source list --sort views        # 플랫폼별 "확인된" 조회수 순(조회수 모름은 뒤, 좋아요≠조회수, 확인일 표시)
python -m shortkit source exclude-check <ID|파일>   # 레퍼런스가 쓴 촬영본과 같은 녹화면 제외(키워드는 같아도 됨)
#  ▶ 후보 영상을 실제로 보고 기록(강도·반전·포맷 적합). 보지 않은 후보는 선택할 수 없다.
python -m shortkit source review <ID> --watched-by <이름> --intensity 1-5 --reversal 1-5 --format-fit 1-5 --notes "몇 초에 무슨 일"
python -m shortkit source select <ID> --by <이름>   # 최신성·강도·반전·화질·포맷 적합으로 최종 선별(선정 이유 자동 기록)
python -m shortkit source download <ID>            # warehouse/sources/ + sha256 + 제외 재검사 (원작자·재게시자·URL 기록 유지)
python -m shortkit clean detect --source warehouse/sources/<파일>   # 원본 로고·출처 오버레이·원어 자막(상단 좌우·내부 컷)
python -m shortkit clean plan   --source warehouse/sources/<파일>   # 깨끗한 원본 → 크롭(인물·동작 보호) → 국소 복원 순으로 결정
```


### C. 에피소드 제작 (첫 편 승인 → 후속편)

```bash
python -m shortkit episode new <ep-id> --mode production --format <F?> --index 1   # 첫 편
#  ▶ plan.yaml 작성 규칙
#    - 소스 영상을 처음부터 끝까지 보고 들은 뒤 작성. 모든 자막에 grounding(무엇을 보고/들었는지) 기록.
#    - 역할 구분(title/description/situation/speaker/dialogue/reaction), 반전은 reveal 로 보호.
#    - 얼굴·손·핵심 물체는 sources[].protected 에 기록(자막이 가리면 검증 실패).
#    - 원음은 기본 OFF. 살릴 구간만 timeline[].original_audio.keep + reason. 원본 음악 여부 has_embedded_music 기록.
#    - 효과음은 사건(event t/desc)이 있을 때만, 사건과 ±0.3초, 포맷 관측 범위 안의 개수·종류.
#    - clean 블록은 `clean plan` 결과를 붙인다.
python -m shortkit episode validate <ep-id>
python -m shortkit episode proposal <ep-id>        # 첫 편 승인용: 소재·구간 시트·표지 문구·제목 후보 3종·효과음 배치표
#  ▶ 사용자 승인 후에만:
python -m shortkit episode approve <ep-id> --by <승인자>
python -m shortkit episode render <ep-id>          # 마스터 MP4 (미측정 프리셋·미승인·미해결 효과음이면 거부)
python -m shortkit episode export <ep-id>          # 편집 프로젝트: MLT(Shotcut/Kdenlive, melt 렌더로 검증), FCPXML, OTIO, captions.ass/srt
python -m shortkit qa run --episode <ep-id> --reference presets/joshuamagazine/reference/videos/<대표영상>.mp4 --reference-id <id>
python -m shortkit qa defects list --episode <ep-id>   # 결함마다 고침 → 같은 사례 재검사 → 최종 관문
python -m shortkit qa gate --episode <ep-id> --production
```

- 첫 편에서 고친 스타일은 프리셋(요청 변경이면 requested_changes.yaml, 측정 오류면 재측정)에 반영하고 후속편은 같은 프리셋으로 만든다.
- 후속편(`--index 2..`)은 승인 없이 지정 포맷·편수까지 진행한다. 이미 승인된 기획의 수정은 재승인하지 않는다.
- 검수표의 "다르다" 중 요청하지 않은 차이는 고친 뒤 다시 검사한다. "못 잼"은 완료로 올리지 않는다.
- 에이전트는 소리를 듣지 못한다. 오디오는 기계 측정만 기록하고 "사람 청취 필요"를 남긴다.


## 6. 파일 지도

| 경로 | 내용 |
|---|---|
| `shortkit/` | 코드. `reference/`(수집·측정·분류·글꼴·오디오·효과음), `sourcing/`(소재 창고), `clean/`(로고·자막 제거), `edit/`(plan·렌더·편집 프로젝트), `qa/`(출력 검수) |
| `presets/joshuamagazine/preset.yaml` | 고정 스타일(현재 전부 임시값) |
| `presets/joshuamagazine/measured.yaml` | 측정값 층(apply-measurements 가 생성) |
| `presets/joshuamagazine/requested_changes.yaml` | 사용자가 지정한 변경(의도한 변경) |
| `presets/joshuamagazine/settings_registry.yaml` | 설정별 근거→측정→코드→검사 연결과 상태 |
| `presets/joshuamagazine/reference/` | 최신 100편 스냅샷, 전체 목록, 80만+ 목록, 수집 로그, WebSearch 참고 기록 |
| `presets/joshuamagazine/{formats.yaml, sfx_catalog.json, sfx_map.yaml, fonts_report.json, measurements/}` | 포맷 분류, 효과음 카탈로그·창고 연결, 글꼴, 측정값 |
| `presets/joshuamagazine/unresolved.md` | 미확정 항목·제작 영향·해결 상태 |
| `warehouse/` | 소재 후보(candidates.jsonl), 검색 기록, 제외 목록, 출처 계정, 오버레이 기록 |
| `episodes/<id>/` | plan.yaml, proposal.md, output/*.mp4, project/(편집 프로젝트), qa/(검수표·비교 시트·결함) |
| `assets/fonts/manifest.yaml` | 후보 글꼴(sha256 고정, `doctor --fetch-fonts`) |
| `assets/library/{music,sfx}/` | 사용자 제공 깨끗한 음악·효과음 창고 |
| `docs/CONTRACT.md` | 모듈 간 인터페이스 계약 |
| `docs/VALIDATION.md` | 실제로 돌려 본 검증과 검증하지 않은 환경 |
| `PRESET_BUNDLE.md` | 다른 컴퓨터용 단일 MD(복원 명령 포함) |


## 7. 재개

- `PROGRESS.md` 의 마지막 [진행] 단계부터. `git log --oneline` 으로 마지막 커밋 확인.
- 미확정 항목 현황: `python -m shortkit preset unresolved` → `presets/joshuamagazine/unresolved.md`.
