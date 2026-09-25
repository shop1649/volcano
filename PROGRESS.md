# 진행 기록 / 재개 지점

## 환경 사실 (2026-09-24 첫 작업 환경)
- 네트워크 정책이 www.youtube.com, *.googlevideo.com, i.ytimg.com, www.tiktok.com, www.instagram.com, www.reddit.com,
  v.redd.it, lens.google.com, www.google.com, namu.wiki, open.subsub.io, youtube-rank.com, freesound.org, pixabay.com,
  dl.fbaipublicfiles.com(Demucs 가중치), huggingface.co, archive.org 를 403 으로 차단. WebFetch 도 같은 정책으로 차단.
- 허용: github.com / raw.githubusercontent.com(공개 저장소 읽기), pypi, npm, Ubuntu apt.
- 2026-09-25 확인: www.googleapis.com(YouTube Data API v3)은 접속됨 — 키가 없어 403 PERMISSION_DENIED.
  `YOUTUBE_API_KEY` 를 환경 변수로 넣으면 `ref collect` 가 최신 100편 목록·게시일·조회수(80만+ 목록 포함)를 API 로 고정할 수 있음.
  영상 받기는 여전히 youtube.com·googlevideo.com 허용이 필요.
- 결과: 레퍼런스 영상 목록·게시일·조회수·영상/음성 원본을 한 건도 확보하지 못함 → 모든 스타일 값은 임시값(못 잼).
  `ref collect` 실행 기록: presets/joshuamagazine/reference/latest100.json (status blocked, yt-dlp 403 원문).
- WebSearch 스니펫만 확인(미검증): presets/joshuamagazine/reference/web_search_observations.md.
- 기존 조사·원본·측정값: 저장소가 비어 있었음(재사용할 자료 없음).
- 사용자 효과음 창고·깨끗한 음악 파일: 제공되지 않음. "내가 별도로 지정한 변경": 요청문에서 비어 있음.

## 완료
1. 핵심 골격(경로·유틸·프리셋 층·레지스트리·접근 추적·plan 스키마·IR·계약서).
2. 모듈: edit(검증·해석·ASS 자막·numpy 오디오 믹스·ffmpeg 렌더·제안서), export(MLT/FCPXML/OTIO + melt 검증),
   qa(최종 MP4 측정·검사표·비교 시트·관문·결함), clean(오버레이 검출·전략·inpaint·잔류 검사·얼굴), reference(수집·다운로드·
   컷/자막/모션/장식 측정·포맷 분류·집계·출처 역추적·글꼴 IoU 상한·Demucs·BGM·원음·효과음 카탈로그·sfx_map·수동 관찰),
   sourcing(4개 플랫폼 어댑터·창고·제외 목록·점수·검토 게이트·다운로드).
3. 통합 결함 수정: libass 대체 글꼴(PostScript 이름 + 렌더 전 fontselect 검사), size_px 단위 통일, 모노 효과음 -3 dB,
   리미터가 BGM 을 누르던 문제, 박스 여백, AAC true peak, 측정 파일 중복 키, 테스트 전체 실행.
4. 적용 범위: `preset audit --test` → no_code 0, no_qa 0 (모든 설정이 코드와 출력 검사에 연결). 미측정 255(네트워크 차단).
5. 검증: test-pipeline-001 / test-coverage-001 렌더·편집 프로젝트(melt SSIM 0.997)·QA(다르다 0),
   합성 정답 레퍼런스 5편으로 측정→적용→렌더→QA 전체 고리(docs/validation/mockloop.md: 222키 중 153 통과·11 방법 한계·0 오탐).

## 적대적 검토 (2026-09-25 완료)
- 요청문 11개 절 × 6개 조각 검토 → 회의적 검증 → 확정 결함 79건(치명 4·주요 54·경미 21) → 전부 수정 또는 "못 잼"으로 기록.
- 뒤이은 수정: QA 출력 검사 61개 키 추가(`preset audit --test`: no_code 0 · no_qa 0), 공용 그림자 추정기, 슬라이드 어휘,
  lead_s 정의 통일(27fb18b), 테스트 기대값 정리(e4a30b6).

## 깨끗한 폴더 복원 검증 (2026-09-25, 완료)
- 1차(번들 17e4e0a): 복원·setup·doctor·새 에피소드 test-restore-001(MP4·편집 프로젝트·melt 대조 통과)·QA·pytest.
  찾은 문제 7가지를 모두 고침: QA 오탐 2(80ca995), 깨끗한 복원 테스트 7개(e9245b6), 보호 영역 위 국소 복원 검사·zoom 경고 시간 창·
  dirty-source --out·번들 mockloop 스크립트·속도 행(d9b6b63).
- 2차(번들 c9fa60e, 364개): 복원 바이트 일치, setup·doctor 통과, test-restore-001 재렌더 MP4 가 1차와 sha256 까지 같음,
  melt 대조 통과, QA 164/0/85. pytest 실패 2(번들에 없는 예제 MP4 요구) → b214659 에서 건너뛰게 고침.
- 저장소 전체 테스트 993개 통과(느린 테스트 포함). `preset audit --test`: no_code 0 · no_qa 0 · 미측정 266.
- 기록: docs/validation/final_restore_log.md, docs/VALIDATION.md, docs/DELIVERABLES.md.

## 남은 일 (이 환경에서 할 수 없는 것 — 사용자/네트워크 필요)
1. 레퍼런스: youtube.com·googlevideo.com 허용(또는 `YOUTUBE_API_KEY` 로 목록·조회수만) → AGENTS.md 5장 A.
2. 사용자 자산: 깨끗한 효과음·음악 창고(`assets/library/`), "별도로 지정한 변경"(requested_changes.yaml).
3. 사람 확인: 테스트 에피소드의 반전·글자 없는 로고·손 위 복원(qa human-check), 청취.
4. 첫 편 기획안: A·B 가 끝난 뒤 `episode proposal` → 승인 → 렌더.

## 재개 방법
- `git log --oneline | head` 로 마지막 커밋 확인 → 위 "남은 일".
- 네트워크가 열린 환경이면: `python -m shortkit doctor --network` → AGENTS.md 5장 A(레퍼런스 분석)부터.
- 테스트 전체: `OMP_THREAD_LIMIT=1 python -m pytest -q` (느린 테스트 제외: `-m "not slow"`).
