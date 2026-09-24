# 레퍼런스 채널 — WebSearch 스니펫 기록 (미검증 참고 정보)

- 수집일: 2026-09-24 (UTC)
- 방법: Claude Code WebSearch 도구의 검색 결과 제목·요약만 기록. 링크된 페이지는 **열어 보지 못함**
  (youtube.com, namu.wiki, open.subsub.io, youtube-rank.com 모두 이 환경의 네트워크 정책에서 차단 — WebFetch 도 EGRESS_BLOCKED).
- 용도: 채널 식별 보조. **측정값·포맷·스타일·소재 판단의 근거로 쓰지 않는다.** 최신 100편 목록·게시일·조회수는 이 파일로 대신하지 않는다.

| 관찰 | 출처(검색 결과 링크) | 상태 |
|---|---|---|
| 채널명 표기 "조슈아매거진", 핸들 @joshuamagazine | https://www.youtube.com/@joshuamagazine (검색 결과 제목) | 페이지 미확인 |
| 채널 ID 후보 UC_TL4XPdPb0WnAudbMMS2_g | https://www.youtube.com/channel/UC_TL4XPdPb0WnAudbMMS2_g (검색 결과 링크, 제목 "조슈아매거진") | 페이지 미확인 — 핸들과 같은 채널인지 확인 필요 |
| 검색 요약: "한국 이슈 유튜버, 해외 이슈 쇼츠" 성격 | https://namu.wiki/w/조슈아매거진 (검색 요약) | 페이지 미확인 |
| 검색 요약: 구독자 약 34만, 총 조회수 16억+, 영상 483개, 채널 소개 "인터넷 모퉁이에 숨겨진 흥미로운 이야기들이 올라옵니다👍" | 검색 도구 요약(근거 링크 불명확: youtube-rank.com / subsub 통계 페이지로 추정) | 시점 불명·미검증 — 사용 금지 |
| TikTok 계정 @joshuamagazine | https://www.tiktok.com/@joshuamagazine | 페이지 미확인 |
| Instagram 계정 @joshuamagazine2 | https://www.instagram.com/joshuamagazine2/ | 페이지 미확인 |
| TikTok 검색 주제 페이지 "조슈아매거진 어린이 빌런", "조슈아매거진 생존 영상" | tiktok.com/discover/… (검색 결과 제목) | 주제 페이지 제목일 뿐, 채널의 실제 포맷 근거 아님 |

## 채널 식별 요소(원 채널 고유 요소 — 우리 영상에 복제 금지)
- 채널명 텍스트 "조슈아매거진"/"joshuamagazine" 은 preset.yaml `identity_exclusions.forbidden_text` 에 등록되어 QA 가 OCR 로 검사한다.
- 로고·워터마크 이미지는 레퍼런스 영상을 받은 뒤 `presets/joshuamagazine/reference/identity_templates/` 에 추출해야 한다(못 잼).
