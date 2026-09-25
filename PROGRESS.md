# 진행 기록 / 재개 지점

## 환경 사실 (2026-09-24 첫 작업 환경)
- 네트워크 정책이 www.youtube.com, *.googlevideo.com, i.ytimg.com, www.tiktok.com, www.instagram.com, www.reddit.com,
  v.redd.it, lens.google.com, www.google.com, namu.wiki, open.subsub.io, youtube-rank.com, freesound.org, pixabay.com,
  dl.fbaipublicfiles.com(Demucs 가중치), huggingface.co, archive.org 를 403 으로 차단. WebFetch 도 같은 정책으로 차단.
- 허용: github.com / raw.githubusercontent.com(공개 저장소 읽기), pypi, npm, Ubuntu apt.
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

## 진행 중 (2026-09-25 저녁)
- 최종 복원 검증: PRESET_BUNDLE.md → 빈 폴더에 복원(내장 복원 블록 그대로) → setup.sh → doctor --network → 테스트 자산 →
  새 에피소드 test-restore-001(로고·출처·원어 자막을 합성한 dirty-source, clean detect/plan) → 렌더·내보내기·melt 대조·QA → pytest.
  기록: docs/validation/final_restore_log.md.
- 문서: docs/VALIDATION.md(검증 환경·결과·미검증 환경), docs/DELIVERABLES.md(납품물 위치). mockloop.md 에 측정 시점 주의 추가.

## 남은 단계
1. 복원 검증 결과를 docs/VALIDATION.md 4절·DELIVERABLES.md 표에 채움.
2. PRESET_BUNDLE.md 다시 생성(최종 문서 포함) → 빠른 재복원 확인(파일 목록이 git HEAD 와 같은지) → 커밋·푸시.

## 재개 방법
- `git log --oneline | head` 로 마지막 커밋 확인 → 위 "남은 단계"의 첫 항목부터.
- 네트워크가 열린 환경이면: `python -m shortkit doctor --network` → AGENTS.md 5장 A(레퍼런스 분석)부터.
- 테스트 전체: `OMP_THREAD_LIMIT=1 python -m pytest -q` (느린 테스트 제외: `-m "not slow"`).
