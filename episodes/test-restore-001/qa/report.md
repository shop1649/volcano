# QA 보고서 — test-restore-001

- 측정 대상: `episodes/test-restore-001/output/test-restore-001.mp4` (sha256 `6a1cd845fb576f58…`, 1080x1920, 18.50s)
- 원칙: 최종 MP4 만 측정(타임라인/코드가 맞다고 출력이 맞다고 보지 않음)
- 프리셋: joshuamagazine-v1 / 포맷 UNCLASSIFIED / 모드 **test**
- 레퍼런스(같은 절대 시각 비교): 없음(못 잼) (분석 파일: 없음)
- 포맷 UNCLASSIFIED 대표 영상(formats.yaml): 못 잼 — 에피소드 포맷이 정해지지 않음(UNCLASSIFIED) — 대표 영상을 고를 수 없음 (formats.yaml 상태 unmeasured: 2026-09-24: youtube.com/googlevideo.com 차단으로 최신 100편 목록·영상 미확보 → 포맷 분류 못 함; 라벨 파일 없음 — `shortkit ref classify prepare` 후 영상을 본 사람이 채워야 함; 고정된 최신 100편 스냅샷이 없어 포맷)
- 측정 시각: 2026-09-25T14:14:45+00:00 / 도구: OCR=5.3.4, 얼굴검출=shortkit.clean.faces haar frontal+profile (shortkit.HaarCascade(numpy))

## 최종 관문: **불합격 — 못 잼 85건(필수 12, 참고 73)**
- ✗ G2: 필수 항목 못 잼 12건 — 못 잼은 완료가 아님 — caption.reveal:reveal, clean.residual:prov:v_hall:static_graphics, clean.residual:prov:v_hall:corner:top_left, clean.residual:prov:v_hall:corner:top_right, clean.residual:prov:v_hall:corner:bottom_left, clean.residual:prov:v_hall:corner:bottom_right, clean.residual:prov:v_room:static_graphics, clean.residual:prov:v_room:corner:top_left …
- △ R1: 레퍼런스 같은 시각 비교 없음/불충분: 레퍼런스 영상 없음 — 에피소드 포맷이 정해지지 않음(UNCLASSIFIED) — 대표 영상을 고를 수 없음 (formats.yaml 상태 unmeasured: 2026-09-24: youtube.com/googlevideo.com 차단으로 최신 100편 목록·영상 미확보 → 포맷 분류 못 함; 라벨 파일 없음 — `shortkit ref classify prepare` 후 영상을 본 사람이 채워야 함; 고정된 최신 100편 스냅샷이 없어 포맷)
- △ P1: 프리셋 미측정(임시값) 키 266개
- △ P2: 레퍼런스 대비 못 잼 68건
- △ P3: 테스트 모드 출력(파이프라인 검증용) — 게시 불가
- △ P4: 필수 표시가 없는 못 잼 4건 — 못 잰 항목은 완료로 치지 않음

## 요약
- 전체 249행: 같다 164 / 다르다 0 (의도한 변경 0, 의도하지 않음 0) / 못 잼 85
- 계획 대비(출력이 계획대로인가): {'same': 164, 'unmeasured': 17}
- 레퍼런스 대비(레퍼런스와 같은가): {'unmeasured': 68}
- 프리셋 미측정(임시값) 키: 266개

| 분류 | 같다 | 다르다 | 못 잼 |
|---|---:|---:|---:|
| 화면 구성 | 4 | 0 | 5 |
| 글자 위치 | 18 | 0 | 10 |
| 자막 내용·말투 | 11 | 0 | 3 |
| 자막 스타일 | 9 | 0 | 5 |
| 폰트 | 13 | 0 | 6 |
| 자막 타이밍 | 9 | 0 | 5 |
| 자막 등장·퇴장 모션 | 17 | 0 | 5 |
| 컷 | 7 | 0 | 2 |
| 모션(확대·정지·전환) | 12 | 0 | 8 |
| 식별 요소 | 1 | 0 | 2 |
| 로고 잔류 | 9 | 0 | 10 |
| 얼굴·손·물체 가림 | 19 | 0 | 1 |
| 음악 구간 | 11 | 0 | 6 |
| 원음 | 1 | 0 | 2 |
| 효과음 종류별 개수 | 12 | 0 | 6 |
| 사건과의 시차 | 4 | 0 | 0 |
| 사건 없는 효과음 0 | 3 | 0 | 0 |
| 음량 | 2 | 0 | 1 |
| 구성·표지 | 2 | 0 | 3 |
| 움직이는 장식(위치/밝기 각각) | 0 | 0 | 1 |
| 레퍼런스 같은 시각 비교(1초 격자) | 0 | 0 | 4 |

## 검사표

### 화면 구성

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 화면 해상도·프레임레이트 | 못 잼 | {"width":1080,"height":1920,"fps":30.0} | {"width":1080,"height":1920,"fps":30.0} | 같다 | 아니오 | — |
| 화면 해상도·프레임레이트 (레퍼런스 대비) | 못 잼 | {"canvas.width":1080,"canvas.height":1920,"canvas.fps":30} | {"width":1080,"height":1920,"fps":30.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: canvas.width, canvas.height, canvas.fps — 출력이 임시값… |
| 영상 영역 위치·크기 | 못 잼 | {"rect":[0.0,656.0,1080.0,608.0],"resolution":[1080,1920]} | {"rect":[0.0,656.0,1080.0,608.0],"resolution":[1080,1920]} | 같다 (참고) | 아니오 | 움직이는 화소·배경색 차이로 측정(휴리스틱) |
| 영상 영역 (레퍼런스 대비) | 못 잼 | {"canvas.video_region.x":0,"canvas.video_region.y":656,"canvas.video_region.w":1080,"canv… | {"rect":[0.0,656.0,1080.0,608.0]} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: canvas.video_region.x, canvas.video_region.y, can… |
| 배경(색/소스 블러) | 못 잼 | {"type":"color","color":"#000000"} | {"type":"color","color":"#000000","temporal_std":0.01} | 같다 (참고) | 아니오 | 흐림 정도(blur_sigma)는 canvas.background:blur 행 |
| 배경 (레퍼런스 대비) | 못 잼 | {"canvas.background.type":"color","canvas.background.color":"#000000"} | {"type":"color","color":"#000000","temporal_std":0.01} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: canvas.background.type, canvas.background.color —… |
| 자막이 안전 여백 안에 있음 | 못 잼 | {"left":54,"right":54,"top":110,"bottom":250} | {"min_margin_px":{"left":119,"top":297,"right":117,"bottom":447}} | 같다 (참고) | 아니오 | — |
| 영상 영역 채우기(cover/contain) | — | {"s1":"cover","s2":"cover","s3":"cover"} | {"clips":[{"clip_id":"s1","t":4.7333,"status":"unmeasured","fit":null,"err":null,"band_sh… | 못 잼 (참고) | 아니오 | 모든 클립에서 cover 와 contain 렌더링이 같아(소스 비율 = 영역 비율) 채우기 방식을 출력에서 구별할 수 없음 |
| 영상 영역 채우기 (레퍼런스 대비) | 못 잼 | {"canvas.video_region.fit":"cover"} | — | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: canvas.video_region.fit — 출력이 임시값과 같아도 레퍼런스와 같다고 … |

### 글자 위치

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 위치 [c_title·title] "카메라 앞에 선 남자" | 못 잼 | {"center":[540.0,335.1],"bbox":[196.0,288.6,688.0,93.0],"resolution":[1080,1920]} | {"center":[541.0,335.5],"bbox":[206,297,670,77],"resolution":[1080,1920],"dx":1.0,"dy":0.… | 같다 | 아니오 | t=0.12s [프레임](frames/cap_c_title_0000120.png) |
| 자막 크기·줄 수 [c_title·title] "카메라 앞에 선 남자" | 못 잼 | {"fill_h":81.0,"lines":1,"max_width_px":980.0,"max_lines":2,"size_px":84.0,"max_chars_per… | {"fill_h":77,"fill_w":670,"lines":1,"size_px_est":79.9,"max_chars_line":8} | 같다 | 아니오 | t=0.12s [프레임](frames/cap_c_title_0000120.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_desc·description] "복원 검증용 테스트 영상" | 못 잼 | {"center":[539.8,503.6],"bbox":[308.8,477.1,462.0,53.0],"resolution":[1080,1920]} | {"center":[541.0,503.0],"bbox":[316,482,450,42],"resolution":[1080,1920],"dx":1.2,"dy":-0… | 같다 | 아니오 | t=0.32s [프레임](frames/cap_c_desc_0000320.png) |
| 자막 크기·줄 수 [c_desc·description] "복원 검증용 테스트 영상" | 못 잼 | {"fill_h":45.0,"lines":1,"max_width_px":980.0,"max_lines":1,"size_px":46.0,"max_chars_per… | {"fill_h":42,"fill_w":450,"lines":1,"size_px_est":42.9,"max_chars_line":10} | 같다 | 아니오 | t=0.32s [프레임](frames/cap_c_desc_0000320.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_sit1·situation] "복도 끝에서 한 남자가 걸어온다" | 못 잼 | {"center":[540.1,1433.8],"bbox":[109.1,1395.8,862.0,76.0],"resolution":[1080,1920]} | {"center":[541.0,1434.0],"bbox":[119,1403,844,62],"resolution":[1080,1920],"dx":0.9,"dy":… | 같다 | 아니오 | t=0.94s [프레임](frames/cap_c_sit1_0000940.png) |
| 자막 크기·줄 수 [c_sit1·situation] "복도 끝에서 한 남자가 걸어온다" | 못 잼 | {"fill_h":64.0,"lines":1,"max_width_px":960.0,"max_lines":2,"size_px":66.0,"max_chars_per… | {"fill_h":62,"fill_w":844,"lines":1,"size_px_est":63.9,"max_chars_line":13} | 같다 | 아니오 | t=0.94s [프레임](frames/cap_c_sit1_0000940.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_spk·speaker] "남색 티셔츠 남성" | — | {"center":[539.5,722.5],"bbox":[405.0,704.0,269.0,37.0],"resolution":[1080,1920]} | {"center":[539.5,722.5],"bbox":[406,704,267,37],"resolution":[1080,1920],"dx":0.0,"dy":0.… | 같다 | 아니오 | t=5.97s [프레임](frames/cap_c_spk_0005970.png) 에피소드 위치 지정(pos) |
| 자막 크기·줄 수 [c_spk·speaker] "남색 티셔츠 남성" | 못 잼 | {"fill_h":37.0,"lines":1,"max_width_px":420.0,"max_lines":1,"size_px":40.0,"max_chars_per… | {"fill_h":37,"fill_w":267,"lines":1,"size_px_est":40.0,"max_chars_line":7} | 같다 | 아니오 | t=5.97s [프레임](frames/cap_c_spk_0005970.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_sit2·situation] "카메라 바로 앞에서 멈춰 선다" | 못 잼 | {"center":[540.0,1433.8],"bbox":[139.5,1395.8,801.0,76.0],"resolution":[1080,1920]} | {"center":[541.0,1434.0],"bbox":[149,1403,784,62],"resolution":[1080,1920],"dx":1.0,"dy":… | 같다 | 아니오 | t=5.54s [프레임](frames/cap_c_sit2_0005540.png) |
| 자막 크기·줄 수 [c_sit2·situation] "카메라 바로 앞에서 멈춰 선다" | 못 잼 | {"fill_h":64.0,"lines":1,"max_width_px":960.0,"max_lines":2,"size_px":66.0,"max_chars_per… | {"fill_h":62,"fill_w":784,"lines":1,"size_px_est":63.9,"max_chars_line":12} | 같다 | 아니오 | t=5.54s [프레임](frames/cap_c_sit2_0005540.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_rx·reaction] "멀뚱멀뚱" | 못 잼 | {"center":[540.2,1144.6],"bbox":[393.2,1101.1,294.0,87.0],"resolution":[1080,1920]} | {"center":[541.5,1145.5],"bbox":[407,1111,269,69],"resolution":[1080,1920],"dx":1.3,"dy":… | 같다 | 아니오 | t=7.02s [프레임](frames/cap_c_rx_0007020.png) |
| 자막 크기·줄 수 [c_rx·reaction] "멀뚱멀뚱" | 못 잼 | {"fill_h":73.0,"lines":1,"max_width_px":900.0,"max_lines":1,"size_px":76.0,"max_chars_per… | {"fill_h":69,"fill_w":269,"lines":1,"size_px_est":71.8,"max_chars_line":4} | 같다 | 아니오 | t=7.02s [프레임](frames/cap_c_rx_0007020.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_sit3·situation] "그러더니 옆으로 휙 나간다" | 못 잼 | {"center":[539.9,1434.3],"bbox":[177.4,1395.8,725.0,77.0],"resolution":[1080,1920]} | {"center":[540.5,1434.0],"bbox":[186,1403,709,62],"resolution":[1080,1920],"dx":0.6,"dy":… | 같다 | 아니오 | t=9.74s [프레임](frames/cap_c_sit3_0009739.png) |
| 자막 크기·줄 수 [c_sit3·situation] "그러더니 옆으로 휙 나간다" | 못 잼 | {"fill_h":65.0,"lines":1,"max_width_px":960.0,"max_lines":2,"size_px":66.0,"max_chars_per… | {"fill_h":62,"fill_w":709,"lines":1,"size_px_est":63.0,"max_chars_line":11} | 같다 | 아니오 | t=9.74s [프레임](frames/cap_c_sit3_0009739.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_sit4·situation] "빈 방에 세 명이 들어온다" | 못 잼 | {"center":[540.2,1433.8],"bbox":[200.2,1395.8,680.0,76.0],"resolution":[1080,1920]} | {"center":[542.5,1434.0],"bbox":[213,1403,659,62],"resolution":[1080,1920],"dx":2.3,"dy":… | 같다 | 아니오 | t=11.64s [프레임](frames/cap_c_sit4_0011639.png) |
| 자막 크기·줄 수 [c_sit4·situation] "빈 방에 세 명이 들어온다" | 못 잼 | {"fill_h":64.0,"lines":1,"max_width_px":960.0,"max_lines":2,"size_px":66.0,"max_chars_per… | {"fill_h":62,"fill_w":659,"lines":1,"size_px_est":63.9,"max_chars_line":10} | 같다 | 아니오 | t=11.64s [프레임](frames/cap_c_sit4_0011639.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_sit5·situation] "한 명은 왼쪽, 둘은 오른쪽" | 못 잼 | {"center":[540.1,1437.8],"bbox":[188.6,1395.8,703.0,84.0],"resolution":[1080,1920]} | {"center":[540.5,1438.5],"bbox":[198,1404,685,69],"resolution":[1080,1920],"dx":0.4,"dy":… | 같다 | 아니오 | t=15.24s [프레임](frames/cap_c_sit5_0015239.png) |
| 자막 크기·줄 수 [c_sit5·situation] "한 명은 왼쪽, 둘은 오른쪽" | 못 잼 | {"fill_h":72.0,"lines":1,"max_width_px":960.0,"max_lines":2,"size_px":66.0,"max_chars_per… | {"fill_h":69,"fill_w":685,"lines":1,"size_px_est":63.2,"max_chars_line":11} | 같다 | 아니오 | t=15.24s [프레임](frames/cap_c_sit5_0015239.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [description] (레퍼런스 대비) | 못 잼 | {"text.roles.description.anchor.x":540,"text.roles.description.anchor.y":500} | {"x":541.0,"y":503.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.description.anchor.x, text.roles.descr… |
| 자막 크기 [description] (레퍼런스 대비) | 못 잼 | {"text.roles.description.size_px":46} | {"size_px_est":42.9} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.roles.description.size_px — 출력이 임시값과 같아도 레퍼런… |
| 자막 위치 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.anchor.x":540,"text.roles.reaction.anchor.y":1140} | {"x":541.5,"y":1145.5} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.reaction.anchor.x, text.roles.reaction… |
| 자막 크기 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.size_px":76} | {"size_px_est":71.8} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.roles.reaction.size_px — 출력이 임시값과 같아도 레퍼런스와 … |
| 자막 위치 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.anchor.x":540,"text.roles.situation.anchor.y":1430} | {"x":541.0,"y":1434.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.situation.anchor.x, text.roles.situati… |
| 자막 크기 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.size_px":66} | {"size_px_est":63.9} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.roles.situation.size_px — 출력이 임시값과 같아도 레퍼런스와… |
| 자막 위치 [speaker] (레퍼런스 대비) | 못 잼 | {"text.roles.speaker.anchor.x":540,"text.roles.speaker.anchor.y":700} | — | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.speaker.anchor.x, text.roles.speaker.a… |
| 자막 크기 [speaker] (레퍼런스 대비) | 못 잼 | {"text.roles.speaker.size_px":40} | {"size_px_est":40.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.roles.speaker.size_px — 출력이 임시값과 같아도 레퍼런스와 같… |
| 자막 위치 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.anchor.x":540,"text.roles.title.anchor.y":330} | {"x":541.0,"y":335.5} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.title.anchor.x, text.roles.title.ancho… |
| 자막 크기 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.size_px":84} | {"size_px_est":79.9} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.roles.title.size_px — 출력이 임시값과 같아도 레퍼런스와 같다고… |

### 자막 내용·말투

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 문구(OCR) [c_title·title] "카메라 앞에 선 남자" | — | 카메라 앞에 선 남자 | {"ocr":"카메라 앞에 선 남자","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=0.12s [프레임](frames/cap_c_title_0000120.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_desc·description] "복원 검증용 테스트 영상" | — | 복원 검증용 테스트 영상 | {"ocr":"복원 검 증 용 테스트 영상","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=0.32s [프레임](frames/cap_c_desc_0000320.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_sit1·situation] "복도 끝에서 한 남자가 걸어온다" | — | 복도 끝에서 한 남자가 걸어온다 | {"ocr":"복도 끝 에 서 한 남 자 가 걸 어 온 다","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=0.94s [프레임](frames/cap_c_sit1_0000940.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_spk·speaker] "남색 티셔츠 남성" | — | 남색 티셔츠 남성 | {"ocr":"남색 티셔츠 남성","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=5.97s [프레임](frames/cap_c_spk_0005970.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_sit2·situation] "카메라 바로 앞에서 멈춰 선다" | — | 카메라 바로 앞에서 멈춰 선다 | {"ocr":"카메라 바로 앞에서 멈 취 선다","similarity":0.917,"match":"ocr"} | 같다 | 아니오 | t=5.54s [프레임](frames/cap_c_sit2_0005540.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_rx·reaction] "멀뚱멀뚱" | — | 멀뚱멀뚱 | {"ocr":"멀 뚱 멀뚱","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=7.02s [프레임](frames/cap_c_rx_0007020.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_sit3·situation] "그러더니 옆으로 휙 나간다" | — | 그러더니 옆으로 휙 나간다 | {"ocr":"그러더니 옆 으로 Sl 나간다","similarity":0.87,"match":"ocr"} | 같다 | 아니오 | t=9.74s [프레임](frames/cap_c_sit3_0009739.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_sit4·situation] "빈 방에 세 명이 들어온다" | — | 빈 방에 세 명이 들어온다 | {"ocr":"빈 방 에 세 명이 들어온다","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=11.64s [프레임](frames/cap_c_sit4_0011639.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_sit5·situation] "한 명은 왼쪽, 둘은 오른쪽" | — | 한 명은 왼쪽, 둘은 오른쪽 | {"ocr":"한 명은 왼쪽, 둘 은 오른쪽","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=15.24s [프레임](frames/cap_c_sit5_0015239.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 반전 전에 반전 내용을 미리 말하지 않음 | — | {"reveal":{"none":true,"reason":"남성이 복도 끝에서 걸어와(v_hall 3.4~8.2s) 카메라 앞에 서 있다가(8.3~18.2s) … | — | 못 잼 | 아니오 | plan 이 '반전 없음'(reveal.none: 남성이 복도 끝에서 걸어와(v_hall 3.4~8.2s) 카메라 앞에 서 … |
| 자막 말투(종결어미, OCR) | 못 잼 | 반말_구어체 | {"n":5,"counts":{"반말":5,"명사형/기타":3},"mode":"반말_구어체","items":[{"text":"카메라 앞에 선 남자","class… | 같다 (참고) | 아니오 | OCR 문구의 종결 어미를 레퍼런스 분석기·validate 와 같은 분류기(reference.aggregate.ending_… |
| 자막 이모지(색 글리프) — 계획 대비 | — | {"planned_emoji":{"c_title":0,"c_desc":0,"c_sit1":0,"c_spk":0,"c_sit2":0,"c_rx":0,"c_sit3… | {"per_caption":[{"caption":"c_title","planned":0,"observed":0,"status":"measured"},{"capt… | 같다 (참고) | 아니오 | 자막이 그린 화소 중 표시 중 정지·채도 높음·자막 색(채움·강조·외곽선·그림자·박스)과 그 혼합이 아닌 덩어리를 색 글리프… |
| 자막 이모지 (레퍼런스 대비) | 못 잼 | {"text.tone.emoji":false} | {"captions_with_emoji":0,"unmeasured_captions":[]} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.tone.emoji — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.… |
| 자막 말투 (레퍼런스 대비) | 못 잼 | {"text.tone.register":"반말_구어체"} | {"register":"반말_구어체"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.tone.register — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 … |

### 자막 스타일

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 색·외곽선·그림자·박스 [c_title·title] "카메라 앞에 선 남자" | 못 잼 | {"color":"#FFFFFF","outline_px":6.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FFFFFF","outline_px":16,"outline_color":"#000000","box_alpha":null,"highl… | 같다 | 아니오 | t=0.12s [프레임](frames/cap_c_title_0000120.png) 배경이 외곽선 색과 같아 외곽선 두께·색은 못 잼(판정에서 뺌); 그림자 못 잼(판정에서 뺌): 배경이 어두워(휘도 < 50… |
| 자막 색·외곽선·그림자·박스 [c_desc·description] "복원 검증용 테스트 영상" | 못 잼 | {"color":"#E6E6E6","outline_px":4.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#E5E5E5","outline_px":11,"outline_color":"#000000","box_alpha":null,"highl… | 같다 | 아니오 | t=0.32s [프레임](frames/cap_c_desc_0000320.png) 배경이 외곽선 색과 같아 외곽선 두께·색은 못 잼(판정에서 뺌); 그림자 못 잼(판정에서 뺌): 배경이 어두워(휘도 < 50… |
| 자막 색·외곽선·그림자·박스 [c_sit1·situation] "복도 끝에서 한 남자가 걸어온다" | 못 잼 | {"color":"#FFFFFF","outline_px":6.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FFFFFF","outline_px":16,"outline_color":"#000000","box_alpha":null,"highl… | 같다 | 아니오 | t=0.94s [프레임](frames/cap_c_sit1_0000940.png) 배경이 외곽선 색과 같아 외곽선 두께·색은 못 잼(판정에서 뺌); 그림자 못 잼(판정에서 뺌): 배경이 어두워(휘도 < 50… |
| 자막 색·외곽선·그림자·박스 [c_spk·speaker] "남색 티셔츠 남성" | 못 잼 | {"color":"#FFFFFF","outline_px":0.0,"outline_color":"#000000","box":true,"box_alpha":0.65… | {"fill_color":"#FFFDFC","outline_px":0,"outline_color":"#2E2C2A","box_alpha":0.537,"highl… | 같다 | 아니오 | t=5.97s [프레임](frames/cap_c_spk_0005970.png) 그림자 못 잼(판정에서 뺌): 박스가 있어 그림자를 따로 재지 않음 |
| 자막 색·외곽선·그림자·박스 [c_sit2·situation] "카메라 바로 앞에서 멈춰 선다" | 못 잼 | {"color":"#FFFFFF","outline_px":6.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FFFFFF","outline_px":16,"outline_color":"#000000","box_alpha":null,"highl… | 같다 | 아니오 | t=5.54s [프레임](frames/cap_c_sit2_0005540.png) 배경이 외곽선 색과 같아 외곽선 두께·색은 못 잼(판정에서 뺌); 그림자 못 잼(판정에서 뺌): 배경이 어두워(휘도 < 50… |
| 자막 색·외곽선·그림자·박스 [c_rx·reaction] "멀뚱멀뚱" | 못 잼 | {"color":"#FFE400","outline_px":7.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FEE300","outline_px":7,"outline_color":"#040000","box_alpha":0.0,"highlig… | 같다 | 아니오 | t=7.02s [프레임](frames/cap_c_rx_0007020.png) |
| 자막 색·외곽선·그림자·박스 [c_sit3·situation] "그러더니 옆으로 휙 나간다" | 못 잼 | {"color":"#FFFFFF","outline_px":6.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FFFFFF","outline_px":16,"outline_color":"#000000","box_alpha":null,"highl… | 같다 | 아니오 | t=9.74s [프레임](frames/cap_c_sit3_0009739.png) 배경이 외곽선 색과 같아 외곽선 두께·색은 못 잼(판정에서 뺌); 그림자 못 잼(판정에서 뺌): 배경이 어두워(휘도 < 50… |
| 자막 색·외곽선·그림자·박스 [c_sit4·situation] "빈 방에 세 명이 들어온다" | 못 잼 | {"color":"#FFFFFF","outline_px":6.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FFFFFF","outline_px":16,"outline_color":"#000000","box_alpha":null,"highl… | 같다 | 아니오 | t=11.64s [프레임](frames/cap_c_sit4_0011639.png) 배경이 외곽선 색과 같아 외곽선 두께·색은 못 잼(판정에서 뺌); 그림자 못 잼(판정에서 뺌): 배경이 어두워(휘도 < 50… |
| 자막 색·외곽선·그림자·박스 [c_sit5·situation] "한 명은 왼쪽, 둘은 오른쪽" | 못 잼 | {"color":"#FFFFFF","outline_px":6.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FFFFFF","outline_px":16,"outline_color":"#000000","box_alpha":null,"highl… | 같다 | 아니오 | t=15.24s [프레임](frames/cap_c_sit5_0015239.png) 배경이 외곽선 색과 같아 외곽선 두께·색은 못 잼(판정에서 뺌); 그림자 못 잼(판정에서 뺌): 배경이 어두워(휘도 < 50… |
| 자막 색·외곽선·그림자·박스 [description] (레퍼런스 대비) | 못 잼 | {"text.roles.description.color":"#E6E6E6"} | {"fill_color":"#E5E5E5"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.roles.description.color — 출력이 임시값과 같아도 레퍼런스와… |
| 자막 색·외곽선·그림자·박스 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.color":"#FFE400","text.roles.reaction.outline_px":7,"text.roles.rea… | {"fill_color":"#FEE300","outline_px":7.0,"outline_color":"#040000","box_alpha":0.0,"shado… | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 5개: text.roles.reaction.color, text.roles.reaction.ou… |
| 자막 색·외곽선·그림자·박스 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.color":"#FFFFFF"} | {"fill_color":"#FFFFFF"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.roles.situation.color — 출력이 임시값과 같아도 레퍼런스와 같… |
| 자막 색·외곽선·그림자·박스 [speaker] (레퍼런스 대비) | 못 잼 | {"text.roles.speaker.color":"#FFFFFF","text.roles.speaker.outline_px":0,"text.roles.speak… | {"fill_color":"#FFFDFC","outline_px":0.0,"box_alpha":0.537,"box_pad":[14.0,7.0],"box_colo… | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 7개: text.roles.speaker.color, text.roles.speaker.outl… |
| 자막 색·외곽선·그림자·박스 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.color":"#FFFFFF"} | {"fill_color":"#FFFFFF"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.roles.title.color — 출력이 임시값과 같아도 레퍼런스와 같다고 판… |

### 폰트

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 글꼴 [c_title·title] "카메라 앞에 선 남자" (자막 1개·정지 프레임 1장, 참고) | 못 잼 | Noto Sans CJK KR Black | {"method":"정확 위치 재렌더","verdict":"identical","mae_planned":0.0,"noise_mae":0.0452,"mae_alt… | 같다 (참고; 판정은 caption.font:role_title) | 아니오 | t=0.12s [프레임](frames/cap_c_title_0000120.png) 참고 행(필수 아님): 한 crop 의 판정은 잡음이 커서 필수 판정은 역할 단위 합동 행 caption.font:role_… |
| 자막 글꼴 [c_desc·description] "복원 검증용 테스트 영상" (자막 1개·정지 프레임 1장… | 못 잼 | Noto Sans CJK KR Bold | {"method":"정확 위치 재렌더","verdict":"identical","mae_planned":0.0,"noise_mae":0.8132,"mae_alt… | 같다 (참고; 판정은 caption.font:role_description) | 아니오 | t=0.32s [프레임](frames/cap_c_desc_0000320.png) 참고 행(필수 아님): 한 crop 의 판정은 잡음이 커서 필수 판정은 역할 단위 합동 행 caption.font:role_… |
| 자막 글꼴 [c_sit1·situation] "복도 끝에서 한 남자가 걸어온다" (자막 1개·정지 프레임 … | 못 잼 | Noto Sans CJK KR Black | {"method":"정확 위치 재렌더","verdict":"identical","mae_planned":0.0,"noise_mae":0.0365,"mae_alt… | 같다 (참고; 판정은 caption.font:role_situation) | 아니오 | t=0.94s [프레임](frames/cap_c_sit1_0000940.png) 참고 행(필수 아님): 한 crop 의 판정은 잡음이 커서 필수 판정은 역할 단위 합동 행 caption.font:role_… |
| 자막 글꼴 [c_spk·speaker] "남색 티셔츠 남성" (자막 1개·정지 프레임 1장, 참고) | 못 잼 | Noto Sans CJK KR Bold | {"method":"정확 위치 재렌더","verdict":"identical","mae_planned":0.0,"noise_mae":1.9301,"mae_alt… | 같다 (참고; 판정은 caption.font:role_speaker) | 아니오 | t=5.97s [프레임](frames/cap_c_spk_0005970.png) 참고 행(필수 아님): 한 crop 의 판정은 잡음이 커서 필수 판정은 역할 단위 합동 행 caption.font:role_… |
| 자막 글꼴 [c_sit2·situation] "카메라 바로 앞에서 멈춰 선다" (자막 1개·정지 프레임 1… | 못 잼 | Noto Sans CJK KR Black | {"method":"정확 위치 재렌더","verdict":"identical","mae_planned":0.0,"noise_mae":0.0405,"mae_alt… | 같다 (참고; 판정은 caption.font:role_situation) | 아니오 | t=5.54s [프레임](frames/cap_c_sit2_0005540.png) 참고 행(필수 아님): 한 crop 의 판정은 잡음이 커서 필수 판정은 역할 단위 합동 행 caption.font:role_… |
| 자막 글꼴 [c_rx·reaction] "멀뚱멀뚱" (자막 1개·정지 프레임 1장, 참고) | 못 잼 | Noto Sans CJK KR Black | {"method":"정확 위치 재렌더","verdict":"identical","mae_planned":0.0,"noise_mae":1.7934,"mae_alt… | 같다 (참고; 판정은 caption.font:role_reaction) | 아니오 | t=7.02s [프레임](frames/cap_c_rx_0007020.png) 참고 행(필수 아님): 한 crop 의 판정은 잡음이 커서 필수 판정은 역할 단위 합동 행 caption.font:role_… |
| 자막 글꼴 [c_sit3·situation] "그러더니 옆으로 휙 나간다" (자막 1개·정지 프레임 1장,… | 못 잼 | Noto Sans CJK KR Black | {"method":"정확 위치 재렌더","verdict":"identical","mae_planned":0.0,"noise_mae":0.4941,"mae_alt… | 같다 (참고; 판정은 caption.font:role_situation) | 아니오 | t=9.74s [프레임](frames/cap_c_sit3_0009739.png) 참고 행(필수 아님): 한 crop 의 판정은 잡음이 커서 필수 판정은 역할 단위 합동 행 caption.font:role_… |
| 자막 글꼴 [c_sit4·situation] "빈 방에 세 명이 들어온다" (자막 1개·정지 프레임 1장,… | 못 잼 | Noto Sans CJK KR Black | {"method":"정확 위치 재렌더","verdict":"identical","mae_planned":0.0,"noise_mae":0.3035,"mae_alt… | 같다 (참고; 판정은 caption.font:role_situation) | 아니오 | t=11.64s [프레임](frames/cap_c_sit4_0011639.png) 참고 행(필수 아님): 한 crop 의 판정은 잡음이 커서 필수 판정은 역할 단위 합동 행 caption.font:role_… |
| 자막 글꼴 [c_sit5·situation] "한 명은 왼쪽, 둘은 오른쪽" (자막 1개·정지 프레임 1장… | 못 잼 | Noto Sans CJK KR Black | {"verdict":"identical","verdict_ko":"동일","iou_expected":0.9856,"margin":0.1357,"top":"Not… | 못 잼 (참고; 판정은 caption.font:role_situation) | 아니오 | t=15.24s [프레임](frames/cap_c_sit5_0015239.png) 참고 행(필수 아님): 한 crop 의 판정은 잡음이 커서 필수 판정은 역할 단위 합동 행 caption.font:role_… |
| 자막 글꼴 [description] (역할 단위: 자막 1개의 정지 프레임 합동) | 못 잼 | Noto Sans CJK KR Bold | {"verdict":"identical","verdict_ko":"동일","iou_expected_median":0.9379,"iou_stats":{"n":4,… | 같다 | 아니오 | t=0.33s 판정: 동일(identical) — 정확 위치 재렌더: 계획 글꼴이 출력을 재현(잡음 이내)하고 대안보다 잡음 이상 가까움 … |
| 자막 글꼴 [reaction] (역할 단위: 자막 1개의 정지 프레임 합동) | 못 잼 | Noto Sans CJK KR Black | {"verdict":"identical","verdict_ko":"동일","iou_expected_median":0.9936,"iou_stats":{"n":4,… | 같다 | 아니오 | t=7.03s 판정: 동일(identical) — 정확 위치 재렌더: 계획 글꼴이 출력을 재현(잡음 이내)하고 대안보다 잡음 이상 가까움 … |
| 자막 글꼴 [situation] (역할 단위: 자막 5개의 정지 프레임 합동) | 못 잼 | Noto Sans CJK KR Black | {"verdict":"identical","verdict_ko":"동일","iou_expected_median":0.9773,"iou_stats":{"n":20… | 같다 | 아니오 | t=0.97s 판정: 동일(identical) — 정확 위치 재렌더: 계획 글꼴이 출력을 재현(잡음 이내)하고 대안보다 잡음 이상 가까움 … |
| 자막 글꼴 [speaker] (역할 단위: 자막 1개의 정지 프레임 합동) | 못 잼 | Noto Sans CJK KR Bold | {"verdict":"identical","verdict_ko":"동일","iou_expected_median":0.971,"iou_stats":{"n":4,"… | 같다 | 아니오 | t=6.00s 판정: 동일(identical) — 정확 위치 재렌더: 계획 글꼴이 출력을 재현(잡음 이내)하고 대안보다 잡음 이상 가까움 … |
| 자막 글꼴 [title] (역할 단위: 자막 1개의 정지 프레임 합동) | 못 잼 | Noto Sans CJK KR Black | {"verdict":"identical","verdict_ko":"동일","iou_expected_median":0.9757,"iou_stats":{"n":4,… | 같다 | 아니오 | t=0.13s 판정: 동일(identical) — 정확 위치 재렌더: 계획 글꼴이 출력을 재현(잡음 이내)하고 대안보다 잡음 이상 가까움 … |
| 자막 글꼴·굵기 [description] (레퍼런스 대비) | 못 잼 | {"text.roles.description.font_name":"Noto Sans CJK KR Bold","text.roles.description.bold"… | {"best":"Noto Sans CJK KR Bold","weight_class":700,"bold":true} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.description.font_name, text.roles.desc… |
| 자막 글꼴·굵기 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.font_name":"Noto Sans CJK KR Black","text.roles.reaction.bold":true} | {"best":"Noto Sans CJK KR Black","weight_class":900,"bold":true} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.reaction.font_name, text.roles.reactio… |
| 자막 글꼴·굵기 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.font_name":"Noto Sans CJK KR Black","text.roles.situation.bold":tr… | {"best":"Noto Sans CJK KR Black","weight_class":900,"bold":true} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.situation.font_name, text.roles.situat… |
| 자막 글꼴·굵기 [speaker] (레퍼런스 대비) | 못 잼 | {"text.roles.speaker.font_name":"Noto Sans CJK KR Bold","text.roles.speaker.bold":true} | {"best":"Noto Sans CJK KR Bold","weight_class":700,"bold":true} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.speaker.font_name, text.roles.speaker.… |
| 자막 글꼴·굵기 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.font_name":"Noto Sans CJK KR Black","text.roles.title.bold":true} | {"best":"Noto Sans CJK KR Black","weight_class":900,"bold":true} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.title.font_name, text.roles.title.bold… |

### 자막 타이밍

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 등장·퇴장 시각 [c_title·title] "카메라 앞에 선 남자" | — | {"start":0.0,"end":18.5} | {"onset":0.0,"offset":18.5} | 같다 | 아니오 | t=0.00s [프레임](frames/cap_c_title_0000120.png) |
| 자막 등장·퇴장 시각 [c_desc·description] "복원 검증용 테스트 영상" | — | {"start":0.0,"end":4.0} | {"onset":0.0,"offset":4.0} | 같다 | 아니오 | t=0.00s [프레임](frames/cap_c_desc_0000320.png) |
| 자막 등장·퇴장 시각 [c_sit1·situation] "복도 끝에서 한 남자가 걸어온다" | — | {"start":0.7,"end":5.2} | {"onset":0.6667,"offset":5.2} | 같다 | 아니오 | t=0.67s [프레임](frames/cap_c_sit1_0000940.png) |
| 자막 등장·퇴장 시각 [c_spk·speaker] "남색 티셔츠 남성" | — | {"start":5.7,"end":8.2} | {"onset":5.7333,"offset":8.1922} | 같다 | 아니오 | t=5.73s [프레임](frames/cap_c_spk_0005970.png) |
| 자막 등장·퇴장 시각 [c_sit2·situation] "카메라 바로 앞에서 멈춰 선다" | — | {"start":5.3,"end":9.3} | {"onset":5.2667,"offset":9.3} | 같다 | 아니오 | t=5.27s [프레임](frames/cap_c_sit2_0005540.png) |
| 자막 등장·퇴장 시각 [c_rx·reaction] "멀뚱멀뚱" | — | {"start":6.8,"end":9.3} | {"onset":6.7667,"offset":9.3} | 같다 | 아니오 | t=6.77s [프레임](frames/cap_c_rx_0007020.png) |
| 자막 등장·퇴장 시각 [c_sit3·situation] "그러더니 옆으로 휙 나간다" | — | {"start":9.5,"end":11.1} | {"onset":9.4667,"offset":11.1} | 같다 | 아니오 | t=9.47s [프레임](frames/cap_c_sit3_0009739.png) |
| 자막 등장·퇴장 시각 [c_sit4·situation] "빈 방에 세 명이 들어온다" | — | {"start":11.4,"end":14.8} | {"onset":11.3667,"offset":14.8333} | 같다 | 아니오 | t=11.37s [프레임](frames/cap_c_sit4_0011639.png) |
| 자막 등장·퇴장 시각 [c_sit5·situation] "한 명은 왼쪽, 둘은 오른쪽" | — | {"start":15.0,"end":18.3} | {"onset":14.9667,"offset":18.3} | 같다 | 아니오 | t=14.97s [프레임](frames/cap_c_sit5_0015239.png) |
| 자막 표시 시간 [description] (레퍼런스 대비) | 못 잼 | {"text.roles.description.timing.min_dur_s":1.0,"text.roles.description.persist":"timed"} | {"min_dur_s":4.0,"max_dur_s":4.0,"persist":"timed","first_onset":0.0,"last_offset":4.0,"d… | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.description.timing.min_dur_s, text.rol… |
| 자막 표시 시간 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.timing.min_dur_s":0.6,"text.roles.reaction.persist":"timed"} | {"min_dur_s":2.533,"max_dur_s":2.533,"persist":"timed","first_onset":6.767,"last_offset":… | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.reaction.timing.min_dur_s, text.roles.… |
| 자막 표시 시간 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.timing.min_dur_s":0.9,"text.roles.situation.persist":"timed"} | {"min_dur_s":1.633,"max_dur_s":4.533,"persist":"timed","first_onset":0.667,"last_offset":… | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.situation.timing.min_dur_s, text.roles… |
| 자막 표시 시간 [speaker] (레퍼런스 대비) | 못 잼 | {"text.roles.speaker.timing.min_dur_s":1.0,"text.roles.speaker.persist":"timed"} | {"min_dur_s":2.459,"max_dur_s":2.459,"persist":"timed","first_onset":5.733,"last_offset":… | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.speaker.timing.min_dur_s, text.roles.s… |
| 자막 표시 시간 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.persist":"whole_video"} | {"min_dur_s":18.5,"max_dur_s":18.5,"persist":"whole_video","first_onset":0.0,"last_offset… | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.roles.title.persist — 출력이 임시값과 같아도 레퍼런스와 같다고… |

### 자막 등장·퇴장 모션

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 등장 모션 [c_title·title] "카메라 앞에 선 남자" | 못 잼 | {"type":"none","dur_s":0.0,"scale_from":1.0} | {"type":"none","note":"첫 프레임부터 완전히 표시(등장 모션 없음)","dur_s_compared":null} | 같다 | 아니오 | t=0.00s [프레임](frames/cap_c_title_0000120.png) |
| 자막 등장 모션 [c_desc·description] "복원 검증용 테스트 영상" | 못 잼 | {"type":"fade","dur_s":0.2,"scale_from":1.0} | {"type":"fade","scale_first":null,"presence_first":0.166,"dur_s":0.133,"scales":[null,nul… | 같다 | 아니오 | t=0.00s [프레임](frames/cap_c_desc_0000320.png) |
| 자막 퇴장 모션 [c_desc·description] "복원 검증용 테스트 영상" | 못 잼 | {"type":"none","dur_s":0.0} | {"type":"none","dur_s":0.0,"expected":"none","fade_dur_s":0.033,"dur_s_compared":null} | 같다 | 아니오 | t=4.00s |
| 자막 등장 모션 [c_sit1·situation] "복도 끝에서 한 남자가 걸어온다" | 못 잼 | {"type":"pop","dur_s":0.12,"scale_from":0.85} | {"type":"pop","scale_first":0.853,"presence_first":0.49,"dur_s":0.133,"scales":[0.853,0.8… | 같다 | 아니오 | t=0.67s [프레임](frames/cap_c_sit1_0000940.png) |
| 자막 퇴장 모션 [c_sit1·situation] "복도 끝에서 한 남자가 걸어온다" | 못 잼 | {"type":"none","dur_s":0.0} | {"type":"none","dur_s":0.0,"expected":"none","fade_dur_s":0.033,"dur_s_compared":null} | 같다 | 아니오 | t=5.20s |
| 자막 등장 모션 [c_spk·speaker] "남색 티셔츠 남성" | 못 잼 | {"type":"fade","dur_s":0.15,"scale_from":1.0} | {"type":"fade","scale_first":null,"presence_first":0.349,"dur_s":0.067,"scales":[null,nul… | 같다 | 아니오 | t=5.73s [프레임](frames/cap_c_spk_0005970.png) |
| 자막 퇴장 모션 [c_spk·speaker] "남색 티셔츠 남성" | 못 잼 | {"type":"fade","dur_s":0.15} | {"type":"fade","dur_s":0.1,"expected":"fade","fade_dur_s":0.133,"dur_s_compared":0.133} | 같다 | 아니오 | t=8.19s |
| 자막 등장 모션 [c_sit2·situation] "카메라 바로 앞에서 멈춰 선다" | 못 잼 | {"type":"pop","dur_s":0.12,"scale_from":0.85} | {"type":"pop","scale_first":0.852,"presence_first":0.525,"dur_s":0.133,"scales":[0.852,0.… | 같다 | 아니오 | t=5.27s [프레임](frames/cap_c_sit2_0005540.png) |
| 자막 퇴장 모션 [c_sit2·situation] "카메라 바로 앞에서 멈춰 선다" | 못 잼 | {"type":"none","dur_s":0.0} | {"type":"none","dur_s":0.0,"expected":"none","fade_dur_s":0.033,"dur_s_compared":null} | 같다 | 아니오 | t=9.30s |
| 자막 등장 모션 [c_rx·reaction] "멀뚱멀뚱" | 못 잼 | {"type":"pop","dur_s":0.1,"scale_from":1.35} | {"type":"pop","scale_first":1.362,"presence_first":0.789,"dur_s":0.1,"scales":[1.362,1.25… | 같다 | 아니오 | t=6.77s [프레임](frames/cap_c_rx_0007020.png) |
| 자막 퇴장 모션 [c_rx·reaction] "멀뚱멀뚱" | 못 잼 | {"type":"none","dur_s":0.0} | {"type":"none","dur_s":0.0,"expected":"none","fade_dur_s":0.033,"dur_s_compared":null} | 같다 | 아니오 | t=9.30s |
| 자막 등장 모션 [c_sit3·situation] "그러더니 옆으로 휙 나간다" | 못 잼 | {"type":"pop","dur_s":0.12,"scale_from":0.85} | {"type":"pop","scale_first":0.852,"presence_first":0.509,"dur_s":0.133,"scales":[0.852,0.… | 같다 | 아니오 | t=9.47s [프레임](frames/cap_c_sit3_0009739.png) |
| 자막 퇴장 모션 [c_sit3·situation] "그러더니 옆으로 휙 나간다" | 못 잼 | {"type":"none","dur_s":0.0} | {"type":"none","dur_s":0.0,"expected":"none","fade_dur_s":0.033,"dur_s_compared":null} | 같다 | 아니오 | t=11.10s |
| 자막 등장 모션 [c_sit4·situation] "빈 방에 세 명이 들어온다" | 못 잼 | {"type":"pop","dur_s":0.12,"scale_from":0.85} | {"type":"pop","scale_first":0.853,"presence_first":0.469,"dur_s":0.1,"scales":[0.853,0.89… | 같다 | 아니오 | t=11.37s [프레임](frames/cap_c_sit4_0011639.png) |
| 자막 퇴장 모션 [c_sit4·situation] "빈 방에 세 명이 들어온다" | 못 잼 | {"type":"none","dur_s":0.0} | {"type":"none","dur_s":0.0,"expected":"none","fade_dur_s":0.033,"dur_s_compared":null} | 같다 | 아니오 | t=14.83s |
| 자막 등장 모션 [c_sit5·situation] "한 명은 왼쪽, 둘은 오른쪽" | 못 잼 | {"type":"pop","dur_s":0.12,"scale_from":0.85} | {"type":"pop","scale_first":0.851,"presence_first":0.485,"dur_s":0.1,"scales":[0.851,0.89… | 같다 | 아니오 | t=14.97s [프레임](frames/cap_c_sit5_0015239.png) |
| 자막 퇴장 모션 [c_sit5·situation] "한 명은 왼쪽, 둘은 오른쪽" | 못 잼 | {"type":"none","dur_s":0.0} | {"type":"none","dur_s":0.0,"expected":"none","fade_dur_s":0.033,"dur_s_compared":null} | 같다 | 아니오 | t=18.30s |
| 자막 등장·퇴장 모션 [description] (레퍼런스 대비) | 못 잼 | {"text.roles.description.motion_in.type":"fade","text.roles.description.motion_in.dur_s":… | {"in_type":"fade","in_dur_s":0.2,"out_type":"none"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: text.roles.description.motion_in.type, text.roles… |
| 자막 등장·퇴장 모션 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.motion_in.type":"pop","text.roles.reaction.motion_in.dur_s":0.1,"te… | {"in_type":"pop","in_dur_s":0.1,"in_scale_first":1.362,"out_type":"none"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: text.roles.reaction.motion_in.type, text.roles.re… |
| 자막 등장·퇴장 모션 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.motion_in.type":"pop","text.roles.situation.motion_in.dur_s":0.12,… | {"in_type":"pop","in_dur_s":0.133,"in_scale_first":0.852,"out_type":"none"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: text.roles.situation.motion_in.type, text.roles.s… |
| 자막 등장·퇴장 모션 [speaker] (레퍼런스 대비) | 못 잼 | {"text.roles.speaker.motion_in.type":"fade","text.roles.speaker.motion_in.dur_s":0.15,"te… | {"in_type":"fade","in_dur_s":0.167,"out_type":"fade","out_dur_s":0.133} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: text.roles.speaker.motion_in.type, text.roles.spe… |
| 자막 등장·퇴장 모션 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.motion_in.type":"none"} | {"in_type":"none"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.roles.title.motion_in.type — 출력이 임시값과 같아도 레퍼… |

### 컷

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 컷 위치 [s2 시작] | — | {"t":9.5} | {"t":9.5,"type":"cut"} | 같다 | 아니오 | t=9.50s |
| 컷 위치 [s3 시작] | — | {"t":11.2} | {"t":11.1667,"type":"flash"} | 같다 | 아니오 | t=11.17s |
| 계획에 없는 컷·플래시 | — | [] | [] | 같다 | 아니오 | — |
| 소스 구간 [s1] | — | {"src_in":2.8,"src_out":12.3,"source":"warehouse/cache/clean/b861fc2d9ea59f5b73542e7ae735… | {"offset_s":-0.061,"samples":[{"t":1.94,"expected_src_t":4.74,"matched_src_t":4.667,"ncc"… | 같다 | 아니오 | t=1.94s |
| 소스 구간 [s2] | — | {"src_in":17.9,"src_out":19.6,"source":"warehouse/cache/clean/b861fc2d9ea59f5b73542e7ae73… | {"offset_s":-0.068,"samples":[{"t":9.88,"expected_src_t":18.28,"matched_src_t":18.25,"ncc… | 같다 | 아니오 | t=9.88s |
| 소스 구간 [s3] | — | {"src_in":28.0,"src_out":34.6,"source":"assets/test/generated/video/people-detection.mp4"} | {"offset_s":-0.067,"samples":[{"t":11.943,"expected_src_t":28.743,"matched_src_t":28.667,… | 같다 | 아니오 | t=11.94s |
| 같은 원본 장면 반복(표시 없는 다시보기) 0 | — | {"unmarked_repeats":0,"min_overlap_s":0.05} | {"repeats":[],"not_measured":[]} | 같다 | 아니오 | 출력에서 잰 클립별 소스 구간이 서로 겹치지 않음 |
| 컷 밀도: 10초당 전환 수 (레퍼런스 포맷 분포 대비) | 못 잼 | {"structure.cuts_per_10s.p10":null,"structure.cuts_per_10s.p50":null,"structure.cuts_per_… | {"cuts_per_10s":1.081,"n_cuts":2,"duration":18.5,"types":["cut","flash"]} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: structure.cuts_per_10s.p10, structure.cuts_per_10… |
| 샷 길이 중앙값 (레퍼런스 포맷 분포 대비) | 못 잼 | {"structure.shot_len_s.p10":null,"structure.shot_len_s.p50":null,"structure.shot_len_s.p9… | {"shot_len_median_s":7.333,"shots_s":[9.5,1.667,7.333]} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: structure.shot_len_s.p10, structure.shot_len_s.p5… |

### 모션(확대·정지·전환)

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 전환 종류·길이 [s2] | 못 잼 | {"type":"cut","dur":0.0} | {"type":"cut","dur":0.0,"score":23.54} | 같다 | 아니오 | t=9.50s |
| 전환 종류·길이 [s3] | 못 잼 | {"type":"flash","dur":0.12,"color":"#FFFFFF","scope":"region"} | {"type":"flash","dur":0.1,"score":135.3,"color":"#FDFDFD","scope":"region","scope_measure… | 같다 | 아니오 | t=11.17s 플래시 최대 밝기 시 영상 영역 평균색 #FDFDFD (기대 #FFFFFF, 거리 ≤ 45); 플래시 범위 region (기… |
| 재생 속도 [s1] | — | 1.0 | {"speed":1.008,"samples":2,"quantisation_frac":0.0294} | 같다 | 아니오 | — |
| 재생 속도 [s2] | — | 1.0 | {"speed":1.064,"samples":2,"quantisation_frac":0.1667} | 같다 | 아니오 | — |
| 재생 속도 [s3] | — | 1.0 | {"speed":1.014,"samples":3,"quantisation_frac":0.0161} | 같다 | 아니오 | — |
| 확대(줌) [s1] | 못 잼 | {"final_ratio":1.25,"t50":5.874,"dur":0.35,"ease":"out","center_canvas":[534.4,912.1],"re… | {"measured_final_ratio":1.8918,"source_ratio":0.9988,"zoom_ratio_corrected":1.8941,"measu… | 같다 | 아니오 | t=5.83s 특징점 배율 곡선(배율 1.8941, 길이 6.774s, 곡선 inout)은 화면 속 움직임에 속음 — 출력 프레임이 계획 … |
| 줌 없음 확인 [s2] | — | {"final_ratio":1.0} | {"max_dev":0.015,"final_ratio":1.0003,"source_ratio":1.0006,"corrected":0.9997,"median_in… | 같다 (참고) | 아니오 | 소스 자체의 카메라 줌도 여기에 잡힘 |
| 줌 없음 확인 [s3] | — | {"final_ratio":1.0} | {"max_dev":0.0574,"final_ratio":0.9961,"source_ratio":1.0,"corrected":0.9961,"median_inli… | 같다 (참고) | 아니오 | 특징점 배율 곡선은 0.06 움직였지만, 출력 프레임이 계획 기하(줌 없음)로 놓은 소스 프레임과 같음 (NCC 중앙 0.9… |
| 연속 세그먼트 줌 횟수(같은 효과 쌓기 금지) | 못 잼 | {"max":1} | {"measured":0} | 같다 | 아니오 | — |
| 줌 배율·길이·가속 곡선·고정점 규칙 (레퍼런스 대비) | 못 잼 | {"motion.zoom.scale_to":1.25,"motion.zoom.dur_s":0.35,"motion.zoom.ease":"out"} | {"final_ratio":1.25,"dur_s":0.35,"ease":"out"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: motion.zoom.scale_to, motion.zoom.dur_s, motion.z… |
| 정지(프리즈) [s3] | 못 잼 | {"start":14.2,"hold":0.7} | {"presence":"present","start":14.2333,"hold":0.767,"mean_diff":0.0106} | 같다 | 아니오 | t=14.20s |
| 계획에 없는 정지 화면 | — | [] | [] | 같다 | 아니오 | 소스도 정지해 있으면 제외; 판단 불가(소스 없음)면 포함 |
| 영상당 정지 횟수 | 못 잼 | {"max":2} | {"count":1} | 같다 | 아니오 | — |
| 정지 길이 (레퍼런스 대비) | 못 잼 | {"motion.freeze.hold_s":0.7} | {"hold_s":0.767} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: motion.freeze.hold_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하… |
| 전환 종류·길이·플래시 색·범위 (레퍼런스 대비) | 못 잼 | {"motion.transitions.default":"cut","motion.transitions.flash.dur_s":0.12,"motion.transit… | {"mode":"cut","flash_dur":0.1,"flash_color":"#FDFDFD","flash_scope":"region"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: motion.transitions.default, motion.transitions.fl… |
| 확대(줌) 있다/없다 (레퍼런스 대비) | 못 잼 | {"presence.zoom":"unmeasured"} | {"presence":"present","basis":"출력에서 잰 줌: s1","reference_share":null} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: presence.zoom — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레… |
| 정지 있다/없다 (레퍼런스 대비) | 못 잼 | {"presence.freeze":"unmeasured"} | {"presence":"present","basis":"출력의 반복 프레임 구간 1개","reference_share":null} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: presence.freeze — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.… |
| 속도 변화 있다/없다 (레퍼런스 대비) | 못 잼 | {"presence.speed_change":"unmeasured"} | {"presence":"absent","basis":"모든 클립이 계획한 소스 시각대로(속도 1) 나옴(소스 대조)","reference_share":null} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: presence.speed_change — 출력이 임시값과 같아도 레퍼런스와 같다고 판정… |
| 플래시 전환 있다/없다 (레퍼런스 대비) | 못 잼 | {"presence.flash":"unmeasured"} | {"presence":"present","basis":"출력에서 잰 flash 1개","reference_share":null} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: presence.flash — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. … |
| 크로스페이드 있다/없다 (레퍼런스 대비) | 못 잼 | {"presence.crossfade":"unmeasured"} | {"presence":"absent","basis":"출력 전체에서 crossfade 없음(프레임 차이·밝기 검사)","reference_share":null} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: presence.crossfade — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 … |

### 식별 요소

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 레퍼런스 채널명·식별 문구 없음 | {"identity_exclusions.forbidden_text":"해당 없음(rule… | {"absent":["조슈아매거진","조슈아 매거진","joshuamagazine","joshua magazine","JOSHUA MAGAZINE"]} | {"hits":[],"frames_ocr":21} | 같다 | 아니오 | 1초 간격 전체 프레임 + 각 클립 중간 OCR |
| 레퍼런스 로고 템플릿 없음 | {"identity_exclusions.logo_templates_dir":"해당 없음(… | {"templates_dir":"presets/joshuamagazine/reference/identity_templates","manifest":"preset… | {"manifest":{"file":"presets/joshuamagazine/reference/identity_templates/manifest.json","… | 못 잼 (참고) | 아니오 | 식별 템플릿 기록이 완전하지 않음(상태 unmeasured): 레퍼런스 목록 수집 차단(2026-09-24T17:56:07+… |
| 레퍼런스와 같은 녹화(영상) 재사용 없음 | — | {"same_recording_as_reference":false} | {"excluded":null,"matched_ref_video_id":null,"distance":null,"matched_keyframes":0,"n_key… | 못 잼 (참고) | 아니오 | 레퍼런스 영상 지문(exclusions.jsonl reference_footage) 없음 → 같은 녹화 여부 못 잼 (URL… |

### 로고 잔류

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 모서리·하단 잔여 글자(출처 표기·워터마크·원어 자막) | — | [] | {"persistent":[],"single_hits":[{"zone":"video_bottom","clip_id":"s1","text":"id","times"… | 같다 | 아니오 | 한 번만 잡힌 글자는 장면 속 글자/OCR 잡음일 수 있어 참고로만 표시 |
| 원본 워터마크 잔류 [ov1 @fake repost·s1] (출처 기록 대조) | — | {"residual":false,"rect_src":{"x":15.0,"y":13.0,"w":214.0,"h":46.0},"resolution_src":[768… | {"residual":false,"how":"pixels","max_ncc":0.2113,"max_tile_ncc":0.3428,"ocr_hits":0,"ocr… | 같다 | 아니오 | t=0.98s |
| 원본 워터마크 잔류 [ov1 @fake repost·s2] (출처 기록 대조) | — | {"residual":false,"rect_src":{"x":15.0,"y":13.0,"w":214.0,"h":46.0},"resolution_src":[768… | {"residual":false,"how":"pixels","max_ncc":0.221,"max_tile_ncc":0.3321,"ocr_hits":0,"ocr_… | 같다 | 아니오 | t=9.83s |
| 원본 원어 자막 잔류 [ov2 WAIT FOR IT·s1] (출처 기록 대조) | — | {"residual":false,"rect_src":{"x":241.0,"y":356.0,"w":279.0,"h":47.0},"resolution_src":[7… | {"residual":false,"how":"pixels","max_ncc":0.1216,"max_tile_ncc":0.3269,"ocr_hits":0,"ocr… | 같다 | 아니오 | t=0.58s |
| 원본 원어 자막 잔류 [ov3 O00·s1] (출처 기록 대조) | — | {"residual":false,"rect_src":{"x":470.0,"y":380.0,"w":49.0,"h":17.0},"resolution_src":[76… | {"residual":false,"how":"pixels","max_ncc":0.317,"max_tile_ncc":0.3641,"ocr_hits":0,"ocr_… | 같다 | 아니오 | t=0.58s |
| 글자 없는 고정 로고 검사 [v_hall] (출처 기록) | — | {"checked":true} | {"check":"static_graphics","status":"unmeasured","doc_status":"unmeasured","shots":[{"id"… | 못 잼 | 아니오 | 출처 기록에서 못 잼: 고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → 코너… |
| 원본 좌상단 글자 없는 로고 [v_hall] (출처 기록) | — | {"checked":true} | {"check":"corner:top_left","status":"unmeasured","unmeasured":["graphic"],"region":{"x":0… | 못 잼 | 아니오 | 출처 기록에서 못 잼: 고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → 코너… |
| 원본 우상단 글자 없는 로고 [v_hall] (출처 기록) | — | {"checked":true} | {"check":"corner:top_right","status":"unmeasured","unmeasured":["graphic"],"region":{"x":… | 못 잼 | 아니오 | 출처 기록에서 못 잼: 고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → 코너… |
| 원본 좌하단 글자 없는 로고 [v_hall] (출처 기록) | — | {"checked":true} | {"check":"corner:bottom_left","status":"unmeasured","unmeasured":["graphic"],"region":{"x… | 못 잼 | 아니오 | 출처 기록에서 못 잼: 고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → 코너… |
| 원본 우하단 글자 없는 로고 [v_hall] (출처 기록) | — | {"checked":true} | {"check":"corner:bottom_right","status":"unmeasured","unmeasured":["graphic"],"region":{"… | 못 잼 | 아니오 | 출처 기록에서 못 잼: 고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → 코너… |
| 글자 없는 고정 로고 검사 [v_room] (출처 기록) | — | {"checked":true} | {"check":"static_graphics","status":"unmeasured","doc_status":"unmeasured","shots":[{"id"… | 못 잼 | 아니오 | 출처 기록에서 못 잼: 고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → 코너… |
| 원본 좌상단 글자 없는 로고 [v_room] (출처 기록) | — | {"checked":true} | {"check":"corner:top_left","status":"unmeasured","unmeasured":["graphic"],"region":{"x":0… | 못 잼 | 아니오 | 출처 기록에서 못 잼: 고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → 코너… |
| 원본 우상단 글자 없는 로고 [v_room] (출처 기록) | — | {"checked":true} | {"check":"corner:top_right","status":"unmeasured","unmeasured":["graphic"],"region":{"x":… | 못 잼 | 아니오 | 출처 기록에서 못 잼: 고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → 코너… |
| 원본 좌하단 글자 없는 로고 [v_room] (출처 기록) | — | {"checked":true} | {"check":"corner:bottom_left","status":"unmeasured","unmeasured":["graphic"],"region":{"x… | 못 잼 | 아니오 | 출처 기록에서 못 잼: 고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → 코너… |
| 원본 우하단 글자 없는 로고 [v_room] (출처 기록) | — | {"checked":true} | {"check":"corner:bottom_right","status":"unmeasured","unmeasured":["graphic"],"region":{"… | 못 잼 | 아니오 | 출처 기록에서 못 잼: 고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → 코너… |
| 정리한 영역 잔류 [s1·inpaint] | — | {"rect_src":[13.0,11.0,218.0,50.0],"src_range":[2.8,12.3],"residual":false} | {"residual":false,"edge_ncc":0.167,"text_src":"@fa ke_repost","text_out":"","rect_out":[1… | 같다 | 아니오 | t=4.75s |
| 정리한 영역 잔류 [s1·inpaint] | — | {"rect_src":[239.0,354.0,283.0,51.0],"src_range":[2.8,6.083],"residual":false} | {"residual":false,"edge_ncc":0.06,"text_src":"FOR IT...","text_out":"—","rect_out":[335.9… | 같다 | 아니오 | t=0.52s |
| 정리한 영역 잔류 [s1·inpaint] | — | {"rect_src":[468.0,378.0,53.0,21.0],"src_range":[2.8,6.083],"residual":false} | {"residual":false,"edge_ncc":0.052,"text_src":"","text_out":"~:","rect_out":[658.2,1188.0… | 같다 | 아니오 | t=0.52s |
| 정리한 영역 잔류 [s2·inpaint] | — | {"rect_src":[13.0,11.0,218.0,50.0],"src_range":[17.9,19.6],"residual":false} | {"residual":false,"edge_ncc":0.165,"text_src":"@fa ke_repost","text_out":"","rect_out":[1… | 같다 | 아니오 | t=9.78s |

### 얼굴·손·물체 가림

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 국소 복원이 보호 영역을 덮음 [남성 두 손(걸어올 때 2)·s1] | — | {"overlaps":0} | {"op":"inpaint","reason":"ov2 burned_subtitle 'WAIT FOR IT'","rect":{"x":239.0,"y":354.0,… | 못 잼 | 아니오 | inpaint 'ov2 burned_subtitle 'WAIT FOR IT'' 가 '남성 두 손(걸어올 때 2)' 의 60%… |
| 보호 영역 가림·잘림 [남성 얼굴(복도 끝)·s1] | — | {"rect":[661.0,895.3,126.7,70.4],"resolution":[1080,1920],"t":[0.5,1.3],"covered":false,"… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=0.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [남성 얼굴(걸어옴 1)·s1] | — | {"rect":[590.7,888.2,133.7,80.2],"resolution":[1080,1920],"t":[1.2,2.1],"covered":false,"… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=1.20s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [남성 얼굴(걸어옴 2)·s1] | — | {"rect":[506.2,874.1,126.7,98.5],"resolution":[1080,1920],"t":[2.0,3.1],"covered":false,"… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=2.00s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [남성 얼굴(걸어옴 3)·s1] | — | {"rect":[457.0,860.1,140.7,115.4],"resolution":[1080,1920],"t":[3.0,4.3],"covered":false,… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=3.00s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [남성 얼굴(가까이 옴)·s1] | — | {"rect":[435.9,836.1,171.7,140.7],"resolution":[1080,1920],"t":[4.2,5.3],"covered":false,… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=4.20s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [남성 얼굴(정면으로 섬)·s1] | — | {"rect":[411.2,803.1,246.3,219.9],"resolution":[1080,1920],"t":[5.2,9.5],"covered":false,… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=5.20s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [남성 두 손(걸어올 때 1)·s1] | — | {"rect":[548.4,1071.2,154.8,84.4],"resolution":[1080,1920],"t":[1.7,2.6],"covered":false,… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=1.70s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [남성 두 손(걸어올 때 2)·s1] | — | {"rect":[421.8,1106.4,260.4,119.6],"resolution":[1080,1920],"t":[2.5,3.4],"covered":false… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=2.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [남성 얼굴(정면으로 섬)·s2] | — | {"rect":[435.9,824.9,197.0,175.9],"resolution":[1080,1920],"t":[9.5,9.9],"covered":false,… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=9.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [남성 얼굴(오른쪽으로 나감)·s2] | — | {"rect":[478.1,789.7,422.2,253.3],"resolution":[1080,1920],"t":[9.8,10.5],"covered":false… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=9.80s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [남성 얼굴(화면 가장자리)·s2] | — | {"rect":[900.3,712.3,179.7,281.5],"resolution":[1080,1920],"t":[10.5,11.1],"covered":fals… | {"hits":[],"visible_frac":0.998} | 같다 | 아니오 | t=10.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [들어오는 세 사람·s3] | — | {"rect":[210.7,824.9,703.7,439.1],"resolution":[1080,1920],"t":[11.4,12.8],"covered":fals… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=11.40s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [걸어가는 세 사람·s3] | — | {"rect":[238.8,789.7,605.2,474.3],"resolution":[1080,1920],"t":[12.7,13.8],"covered":fals… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=12.70s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [갈라지기 직전 세 사람·s3] | — | {"rect":[252.9,733.4,605.2,464.4],"resolution":[1080,1920],"t":[13.7,14.8],"covered":fals… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=13.70s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [왼쪽으로 가는 남성·s3] | — | {"rect":[126.2,698.2,183.0,337.8],"resolution":[1080,1920],"t":[14.7,15.8],"covered":fals… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=14.70s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [오른쪽으로 가는 두 사람·s3] | — | {"rect":[647.0,740.4,309.6,380.0],"resolution":[1080,1920],"t":[14.7,15.8],"covered":fals… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=14.70s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [왼쪽 벽 앞 남성·s3] | — | {"rect":[0.0,740.4,196.6,281.5],"resolution":[1080,1920],"t":[15.7,16.3],"covered":false,… | {"hits":[],"visible_frac":0.998} | 같다 | 아니오 | t=15.70s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [오른쪽 벽 앞 두 사람·s3] | — | {"rect":[787.7,740.4,292.3,351.9],"resolution":[1080,1920],"t":[15.7,17.8],"covered":fals… | {"hits":[],"visible_frac":0.998} | 같다 | 아니오 | t=15.70s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 얼굴 가림(얼굴 검출) | — | {"covered":0} | {"detector":"shortkit.clean.faces haar frontal+profile (shortkit.HaarCascade(numpy))","fr… | 같다 | 아니오 | 얼굴: 출력 프레임 + 같은 순간의 소스 프레임(자막이 덮은 얼굴은 출력에서 안 보임)을 캔버스 좌표로 옮겨 검출; 자막 상… |

### 음악 구간

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| BGM 은 깨끗한 음원(레퍼런스에서 분리한 스템 금지) | — | {"clean_music_file":true,"not_a_copy_of":"presets/*/analysis/*/stems/*, reference media"} | {"path":"assets/test/generated/music_bed_a.wav","reference_stems_compared":0,"reference_h… | 못 잼 (참고) | 아니오 | 레퍼런스 분리 음원 파일(presets/*/analysis/*/stems)이 하나도 없어 파형 대조 대상이 없음 — `ref… |
| BGM 곡·버전 일치(파형 대조) | 못 잼 | {"path":"assets/test/generated/music_bed_a.wav","track_id":null} | {"presence":"present","waveform_ncc":0.9779,"local_match":{"n":74,"q95":0.9999,"q70":0.99… | 같다 | 아니오 | 출력 믹스에서 계획한 음악 파일의 파형을 찾음 ／ is_match 4요소: 곡=같다, 버전=같다, 속도=같다, 구간=같다 |
| BGM 일치(곡 AND 버전 AND 속도 AND 구간, audio_bgm.is_match) | 못 잼 | {"track_id":"assets/test/generated/music_bed_a.wav","version":"file:assets/test/generated… | {"observed":{"track_id":"assets/test/generated/music_bed_a.wav","version":"file:assets/te… | 같다 | 아니오 | t=0.00s 곡=같다, 버전=같다, 속도=같다, 구간=같다 — 계획한 음원 파일의 파형이 출력에서 확인됨(같은 녹음 → 곡·버전 같음) |
| BGM 속도(버전) | 못 잼 | 1.0 | 1.0 | 같다 | 아니오 | 후보 템포 상위: [[1.0, 0.9237], [1.005, 0.298], [0.995, 0.2854], [0.8, 0.15… |
| BGM 사용 구간 | 못 잼 | {"section_start_s":0.0} | {"section_start_s":0.0,"used_section":[0.025,18.467],"runner_up":{"section_start_s":24.0,… | 같다 | 아니오 | t=0.00s 파형이 거의 똑같이 반복되는 곡이라 다른 위치도 같은 소리(상관 차 ≤ 0.005) — 구간 구별 한계 |
| BGM 페이드 인/아웃 | 못 잼 | {"fade_in_s":0.0,"fade_out_s":0.8} | {"fade_in_s":0.0,"fade_out_s":0.687,"audible_span":[0.025,18.467]} | 같다 (참고) | 아니오 | 0.05초 창 LS 이득 곡선에서 측정 |
| BGM 곡·버전·속도·구간 (레퍼런스 대비) | 못 잼 | {"audio.bgm.track_id":null,"audio.bgm.title":null,"audio.bgm.version":null,"audio.bgm.tem… | {"track_id":null,"title":null,"version":null,"tempo_ratio":1.0,"section_start_s":0.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 5개: audio.bgm.track_id, audio.bgm.title, audio.bgm.ve… |
| 보존 대사 구간의 BGM 덕킹 | — | {"duck_ranges":[],"depth_db":10.0} | {"ducked_ranges":[[18.042,18.492]],"coverage":[]} | 같다 (참고) | 아니오 | 계획의 덕킹 구간이 출력에 있는지(깊이는 depth 행) |
| 보존 대사 밖에서 BGM 낮춤 없음(효과음·컷 때문에 덕킹 금지) | {"audio.ducking.only_under_kept_dialogue":"해당 없음(… | {"ducking_only_in":[]} | {"ducking_outside":[]} | 같다 | 아니오 | — |
| 덕킹은 출력에서 잰 말소리 밑에서만 | {"audio.ducking.only_under_kept_dialogue":"해당 없음(… | {"planned_speech_out":[],"max_without_speech_s":0.25} | {"ducks":[],"speech_out":[],"speech_status":"measured"} | 같다 | 아니오 | 출력에서 잰 덕킹 없음(시작·끝 페이드·의도적 정적 제외) |
| 덕킹은 원음이 실제로 들리는 곳에서만 | — | 덕킹 구간 ⊆ 원음 존재 구간 | {"ducks_without_original":[],"original_present":[]} | 같다 | 아니오 | — |
| 계획에 없는 BGM 끊김 | — | [] | [] | 같다 | 아니오 | — |
| BGM 크기(최종 프로그램 음량 기준) | 못 잼 | {"gain_db":0.0,"definition":"깨끗한 음원 대비 dB, 최종 프로그램 음량에서"} | {"level_db":0.27,"ls_gain_db":-0.13,"mix_lufs":-14.4,"target_lufs":-14.0} | 같다 | 아니오 | t=0.00s 깨끗한 음원 LS 이득(0.25 s 창 이득의 p90 = BGM 기준 레벨, dB) + 목표 LUFS − 출력 통합 LUFS… |
| BGM 크기 (레퍼런스 대비) | 못 잼 | {"audio.bgm.gain_db":0.0} | {"level_db":0.27} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: audio.bgm.gain_db — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않… |
| BGM 있다/없다 (레퍼런스 대비) | 못 잼 | {"presence.bgm":"unmeasured"} | {"presence":"present","basis":"계획한 음원 파형을 출력에서 찾음","reference_share":null} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: presence.bgm — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼… |
| 덕킹 있다/없다 (레퍼런스 대비) | 못 잼 | {"presence.ducking":"unmeasured"} | {"presence":"present","basis":"출력에서 잰 BGM 낮춤 1구간","reference_share":null} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: presence.ducking — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음… |
| 의도적 정적 있다/없다 (레퍼런스 대비) | 못 잼 | {"presence.intentional_silence":"unmeasured"} | {"presence":"absent","basis":"BGM 이득 곡선에 끊김 없음(시작·끝 페이드 제외)","reference_share":null} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: presence.intentional_silence — 출력이 임시값과 같아도 레퍼런스와… |

### 원음

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 원음 OFF 구간에 원음 없음(기본 OFF) | {"audio.original.default":"해당 없음(rule)"} | {"kept_only":[]} | {"presence_outside_kept":"absent","leak_windows":[],"sources_without_audio":[]} | 같다 | 아니오 | — |
| 보존 원음 크기 (레퍼런스 대비) | 못 잼 | {"audio.original.keep_gain_db":0.0} | — | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: audio.original.keep_gain_db — 출력이 임시값과 같아도 레퍼런스와 … |
| 원음 있다/없다 (레퍼런스 대비) | 못 잼 | {"presence.original_audio":"unmeasured"} | {"presence":"absent","basis":"원음 창 모두 없음","reference_share":null} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: presence.original_audio — 출력이 임시값과 같아도 레퍼런스와 같다고 … |

### 효과음 종류별 개수

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 효과음 [fx1·pop] 위치 | — | {"t":0.6,"type":"pop"} | {"t":0.6,"ncc":1.0} | 같다 | 아니오 | t=0.60s |
| 효과음 [fx1·pop] 크기 | 못 잼 | {"gain_db":-8.0} | {"gain_db_mix_scale":-8.0,"reference":"local_bgm"} | 같다 (참고) | 아니오 | t=0.60s |
| 효과음 [fx2·ding] 위치 | — | {"t":5.5,"type":"ding"} | {"t":5.5,"ncc":0.997} | 같다 | 아니오 | t=5.50s |
| 효과음 [fx2·ding] 크기 | 못 잼 | {"gain_db":-8.0} | {"gain_db_mix_scale":-8.21,"reference":"local_bgm"} | 같다 (참고) | 아니오 | t=5.50s |
| 효과음 [fx3·whoosh] 위치 | — | {"t":10.05,"type":"whoosh"} | {"t":10.0522,"ncc":0.912} | 같다 | 아니오 | t=10.05s |
| 효과음 [fx3·whoosh] 크기 | 못 잼 | {"gain_db":-8.0} | {"gain_db_mix_scale":-8.95,"reference":"local_bgm"} | 같다 (참고) | 아니오 | t=10.05s |
| 효과음 [fx4·click] 위치 | — | {"t":14.2,"type":"click"} | {"t":14.2,"ncc":0.987} | 같다 | 아니오 | t=14.20s |
| 효과음 [fx4·click] 크기 | 못 잼 | {"gain_db":-8.0} | {"gain_db_mix_scale":-8.22,"reference":"local_bgm"} | 같다 (참고) | 아니오 | t=14.20s |
| 효과음 개수 [click] (계획 대비) | — | 1 | 1 | 같다 | 아니오 | t=14.20s |
| 효과음 개수 [ding] (계획 대비) | — | 1 | 1 | 같다 | 아니오 | t=5.50s |
| 효과음 개수 [pop] (계획 대비) | — | 1 | 1 | 같다 | 아니오 | t=0.60s |
| 효과음 개수 [whoosh] (계획 대비) | — | 1 | 1 | 같다 | 아니오 | t=10.05s |
| 효과음 [fx1] 종류 = 소리 지문(카탈로그 대비) | 못 잼 | {"type":"pop"} | {"catalog_type":null,"status":"unmeasured","type_id":null,"reason":"효과음 카탈로그 미측정(상태 unmea… | 못 잼 (참고) | 아니오 | t=0.60s 소리 지문으로 종류를 정하지 못함: 효과음 카탈로그 미측정(상태 unmeasured: 2026-09-24: 레퍼런스 최신 5… |
| 효과음 [fx2] 종류 = 소리 지문(카탈로그 대비) | 못 잼 | {"type":"ding"} | {"catalog_type":null,"status":"unmeasured","type_id":null,"reason":"효과음 카탈로그 미측정(상태 unmea… | 못 잼 (참고) | 아니오 | t=5.50s 소리 지문으로 종류를 정하지 못함: 효과음 카탈로그 미측정(상태 unmeasured: 2026-09-24: 레퍼런스 최신 5… |
| 효과음 [fx3] 종류 = 소리 지문(카탈로그 대비) | 못 잼 | {"type":"whoosh"} | {"catalog_type":null,"status":"unmeasured","type_id":null,"reason":"효과음 카탈로그 미측정(상태 unmea… | 못 잼 (참고) | 아니오 | t=10.05s 소리 지문으로 종류를 정하지 못함: 효과음 카탈로그 미측정(상태 unmeasured: 2026-09-24: 레퍼런스 최신 5… |
| 효과음 [fx4] 종류 = 소리 지문(카탈로그 대비) | 못 잼 | {"type":"click"} | {"catalog_type":null,"status":"unmeasured","type_id":null,"reason":"효과음 카탈로그 미측정(상태 unmea… | 못 잼 (참고) | 아니오 | t=14.20s 소리 지문으로 종류를 정하지 못함: 효과음 카탈로그 미측정(상태 unmeasured: 2026-09-24: 레퍼런스 최신 5… |
| 효과음 종류별 개수 (레퍼런스 포맷 범위 대비) | 못 잼 | 레퍼런스 카탈로그의 포맷별 관측 범위 | {"종류 못 정함":4} | 못 잼 (참고) | 아니오 | sfx_catalog.json 미측정: 2026-09-24: 레퍼런스 최신 50편 다운로드 불가(youtube 차단), De… |
| 효과음 크기 (레퍼런스 대비) | 못 잼 | {"audio.sfx.gain_db_default":-8.0} | {"gain_db":-8.21} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: audio.sfx.gain_db_default — 출력이 임시값과 같아도 레퍼런스와 같다… |

### 사건과의 시차

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 효과음 [fx1] 사건과의 시차 (복도 끝 유리문 쪽에 남성이 처음 보) | {"audio.sfx.max_event_offset_s":"해당 없음(rule)"} | {"event_t":0.6,"max_abs_offset":0.3} | {"sfx_t":0.6,"offset":0.0} | 같다 | 아니오 | t=0.60s 사건 시각은 plan 의 선언(화면 사건), 효과음 시각은 출력에서 측정 |
| 효과음 [fx2] 사건과의 시차 (카메라 바로 앞에서 걸음을 멈춤) | {"audio.sfx.max_event_offset_s":"해당 없음(rule)"} | {"event_t":5.5,"max_abs_offset":0.3} | {"sfx_t":5.5,"offset":0.0} | 같다 | 아니오 | t=5.50s 사건 시각은 plan 의 선언(화면 사건), 효과음 시각은 출력에서 측정 |
| 효과음 [fx3] 사건과의 시차 (남성이 오른쪽으로 빠르게 걸어 화면을) | {"audio.sfx.max_event_offset_s":"해당 없음(rule)"} | {"event_t":10.1,"max_abs_offset":0.3} | {"sfx_t":10.0522,"offset":-0.048} | 같다 | 아니오 | t=10.05s 사건 시각은 plan 의 선언(화면 사건), 효과음 시각은 출력에서 측정 |
| 효과음 [fx4] 사건과의 시차 (세 사람이 양쪽으로 갈라지기 직전 화) | {"audio.sfx.max_event_offset_s":"해당 없음(rule)"} | {"event_t":14.2,"max_abs_offset":0.3} | {"sfx_t":14.2,"offset":0.0} | 같다 | 아니오 | t=14.20s 사건 시각은 plan 의 선언(화면 사건), 효과음 시각은 출력에서 측정 |

### 사건 없는 효과음 0

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 컷 위에 놓인 효과음(사건 없이 컷 때문인지) | — | {"on_cut_without_evidence":0} | {"on_cut":[],"cuts_measured":2} | 같다 (참고) | 아니오 | 컷 위 효과음 없음 |
| 사건 없는 효과음 0 | {"audio.sfx.require_event":"해당 없음(rule)"} | 0 | {"count":0,"items":[]} | 같다 | 아니오 | — |
| 알려진 소리로 설명되지 않는 소리 시작점 | — | 0 | {"count":0,"onsets":[]} | 같다 | 아니오 | BGM·원음·검출된 효과음을 뺀 잔차에서 급격한 에너지 상승(보존 원음 구간 제외) |

### 음량

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 통합 음량(LUFS)·트루피크 | 못 잼 | {"integrated_lufs":-14.0,"true_peak_db":-1.5} | {"integrated_lufs":-14.4,"lra":0.8,"true_peak_db":-1.7} | 같다 | 아니오 | — |
| 음량 (레퍼런스 대비) | 못 잼 | {"audio.loudness.integrated_lufs":-14.0,"audio.loudness.true_peak_db":-1.5} | {"integrated_lufs":-14.4,"true_peak_db":-1.7} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: audio.loudness.integrated_lufs, audio.loudness.tr… |
| 출력 오디오 표본율 | {"audio.sample_rate":"해당 없음(infra)"} | 48000 | 48000 | 같다 | 아니오 | ffprobe 로 읽은 출력 MP4 의 오디오 표본율 |

### 구성·표지

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 영상 길이 | — | 18.5 | 18.5 | 같다 | 아니오 | — |
| 영상 길이 (레퍼런스 분포 대비) | 못 잼 | {"structure.duration_s.p10":null,"structure.duration_s.p50":null,"structure.duration_s.p9… | {"duration":18.5} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: structure.duration_s.p10, structure.duration_s.p5… |
| 첫 시간제 자막 시각 (레퍼런스 대비) | 못 잼 | {"structure.first_caption_at_s":0.0} | {"first_caption_at_s":0.667,"caption":"c_sit1","role":"situation"} | 못 잼 (참고) | 아니오 | t=0.67s 레퍼런스 미측정(임시값) 키 1개: structure.first_caption_at_s — 출력이 임시값과 같아도 레퍼런스와… |
| 표지 프레임에 제목 문구 표시 | 못 잼 | {"t":0.0,"text":"카메라 앞에 선 남자","role":"title","source":"first_frame"} | {"ocr":"카메라 앞에 선 남자","similarity":1.0,"role_caption_visible":true} | 같다 (참고) | 아니오 | t=0.00s |
| 표지 구성 (레퍼런스 대비) | 못 잼 | {"cover.source":"first_frame","cover.text_role":"title"} | {"t":0.0,"source":"first_frame","text_role":"title","text_role_visible":true,"similarity"… | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: cover.source, cover.text_role — 출력이 임시값과 같아도 레퍼런스… |

### 움직이는 장식(위치/밝기 각각)

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 움직이는 장식 있다/없다 (레퍼런스 대비) | 못 잼 | {"presence.decorations":"unmeasured"} | {"presence":"unmeasured","basis":"계획에 없는 장식을 출력에서 찾는 검출기가 없어 '없다'를 확정하지 못함","reference_sh… | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: presence.decorations — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하… |

### 레퍼런스 같은 시각 비교(1초 격자)

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 역할·표시 (레퍼런스와 같은 절대 시각 1초 격자) | 못 잼 | — | — | 못 잼 (참고) | 아니오 | 레퍼런스 영상 없음: 에피소드 포맷이 정해지지 않음(UNCLASSIFIED) — 대표 영상을 고를 수 없음 (formats.… |
| 컷·전환 위치 (레퍼런스와 같은 절대 시각 1초 격자) | 못 잼 | — | — | 못 잼 (참고) | 아니오 | 레퍼런스 영상 없음: 에피소드 포맷이 정해지지 않음(UNCLASSIFIED) — 대표 영상을 고를 수 없음 (formats.… |
| 효과음 종류·자리 (레퍼런스와 같은 절대 시각 0.5초 격자) | 못 잼 | — | — | 못 잼 (참고) | 아니오 | 레퍼런스 영상 없음: 에피소드 포맷이 정해지지 않음(UNCLASSIFIED) — 대표 영상을 고를 수 없음 (formats.… |
| 레퍼런스 1편과 같은 절대 시각 1초 격자 비교 시트 | {"video_id":null} | {"reference":null,"grid_s":1.0,"sfx_strip_s":0.5} | {"sheets":["episodes/test-restore-001/qa/compare_sheet.png","episodes/test-restore-001/qa… | 못 잼 (참고) | 아니오 | 레퍼런스 MP4 없음 — 시트의 레퍼런스 줄이 '못 잼'으로 그려짐: 에피소드 포맷이 정해지지 않음(UNCLASSIFIED)… |

## 못 잼 항목과 이유

- 화면 해상도·프레임레이트 (레퍼런스 대비) (`canvas.format:format_ref`): 레퍼런스 미측정(임시값) 키 3개: canvas.width, canvas.height, canvas.fps — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치
- 영상 영역 (레퍼런스 대비) (`canvas.video_region:region_ref`): 레퍼런스 미측정(임시값) 키 4개: canvas.video_region.x, canvas.video_region.y, canvas.video_region.w, canvas.video_region.h — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치
- 배경 (레퍼런스 대비) (`canvas.background:background_ref`): 레퍼런스 미측정(임시값) 키 2개: canvas.background.type, canvas.background.color — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 적용되지 않아 판정에서 뺀 키: canvas.background.blur_sigma — background.type=color(흐린 원본 배경 아님) → 흐림 정도가 쓰이지 않음. — 제작 영향: 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치
- 영상 영역 채우기(cover/contain) (`canvas.video_region:fit`): 모든 클립에서 cover 와 contain 렌더링이 같아(소스 비율 = 영역 비율) 채우기 방식을 출력에서 구별할 수 없음 — 제작 영향: 화면 구성을 확인하지 못함
- 영상 영역 채우기 (레퍼런스 대비) (`canvas.video_region:fit_ref`): 레퍼런스 미측정(임시값) 키 1개: canvas.video_region.fit — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 출력에서 구별 가능한 클립의 채우기 방식(최빈) — 제작 영향: 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치
- 자막 글꼴 [c_sit5·situation] "한 명은 왼쪽, 둘은 오른쪽" (자막 1개·정지 프레임 1장, 참고) (`caption.font:c_sit5`): 참고 행(필수 아님): 한 crop 의 판정은 잡음이 커서 필수 판정은 역할 단위 합동 행 caption.font:role_situation 이 한다 — 이 행의 못 잼은 관문을 막지 않지만 '다르다'는 그대로 관문(G1)에 걸린다(한 자막만 다른 글꼴일 수 있음). 한 crop 판정은 동일(identical)이나 정확 위치 재렌더로 확인되지 않아 같다고 쓰지 않음 — IoU 0.986 >= 천장 p10 0.957; 차순위 대비 차이 +0.136 > 잡음 0.022; 글자별 검사 통과 — 제작 영향: 글꼴이 맞는지 확인하지 못함 → 글자 인상이 다를 수 있음
- **필수** 반전 전에 반전 내용을 미리 말하지 않음 (`caption.reveal:reveal`): plan 이 '반전 없음'(reveal.none: 남성이 복도 끝에서 걸어와(v_hall 3.4~8.2s) 카메라 앞에 서 있다가(8.3~18.2s) 옆으로 나가고(18.3~19.4s), 빈 방에 세 사람이 들어와 양쪽으로 갈라져 나가는(v_room 28.0~34.5s) 장면이 보이는 순서대로 나올 뿐 — 뒤에서 드러나는 정체·예상 밖 사건이 없어 앞 자막이 미리 말할 반전이 없음. 구간 목적도 hook → build → outro 로 reveal 구간 없음)이라고 적었을 뿐 출력에서 잰 것이 아님 — 보호할 키워드가 없어 자막을 대조할 수 없음; 사람이 보고 `shortkit qa human-check --kind watch` 로 기록 — 제작 영향: 자막 문구·말투를 확인하지 못함
- 자막 이모지 (레퍼런스 대비) (`caption.tone:emoji_ref`): 레퍼런스 미측정(임시값) 키 1개: text.tone.emoji — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. text.tone.emoji=false → 모든 자막에 색 글리프 0개(못 잰 자막이 있으면 못 잼); true → 허용 — 제작 영향: 자막 이모지 허용 여부가 임시값 → 이모지 사용이 레퍼런스와 다를 수 있음
- 자막 위치 [description] (레퍼런스 대비) (`caption.position:description_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.description.anchor.x, text.roles.description.anchor.y — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 제목/자막 위치 불일치
- 자막 크기 [description] (레퍼런스 대비) (`caption.size:description_ref`): 레퍼런스 미측정(임시값) 키 1개: text.roles.description.size_px — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글자 크기 불일치 → 줄 수·가림 영역 변화
- 자막 색·외곽선·그림자·박스 [description] (레퍼런스 대비) (`caption.style:description_ref`): 레퍼런스 미측정(임시값) 키 1개: text.roles.description.color — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 측정한 채움색·외곽선(배경과 구별될 때)·박스 불투명도의 중앙값 + 레퍼런스 분석기와 같은 정의(reference.textboxes.measure_line / box_alpha; 그림자는 레퍼런스와 같은 추정기 shortkit.util.textmeasure.drop_shadow)로 잰 그림자·박스 여백(박스 경계 − 보이는 잉크)·박스 색; 재지 못한 키(어두운 배경의 그림자, 박스가 안 보이는 경우 등)는 행에서 뺌 — 제작 영향: 글자 색 불일치
- 자막 글꼴·굵기 [description] (레퍼런스 대비) (`caption.font:description_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.description.font_name, text.roles.description.bold — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 글꼴 = 역할 합동 판정이 동일(identical)인 면; 굵기 = 그 면의 OS/2 굵기 ≥ typography.BOLD_MIN_WEIGHT(ref fonts 와 같은 규칙) — 제작 영향: 글꼴이 레퍼런스와 다를 수 있음 → 글자 인상·폭·줄바꿈 불일치
- 자막 표시 시간 [description] (레퍼런스 대비) (`caption.timing:description_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.description.timing.min_dur_s, text.roles.description.persist — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 적용되지 않아 판정에서 뺀 키: timing.lead_s — 정의: lead_s = 겹치는 말소리 시작 − 대사 자막 시작 → 대사 외 역할은 기준 사건이 없음(값 0). persist: 역할 자막 하나가 영상 길이의 90% 이상 보이면 whole_video(레퍼런스 분석기와 같은 정의); timed 이면 측정한 최소 표시 시간 ≥ timing.min_dur_s − 0.05 s — 제작 영향: 자막 등장 타이밍 불일치
- 자막 등장·퇴장 모션 [description] (레퍼런스 대비) (`caption.motion:description_ref`): 레퍼런스 미측정(임시값) 키 3개: text.roles.description.motion_in.type, text.roles.description.motion_in.dur_s, text.roles.description.motion_out.type — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼런스 대비 등장·퇴장 모션: 측정한 최빈 종류와 길이(중앙값)·pop 첫 배율·slide 첫 프레임 이동을 비교(레퍼런스 분석기와 렌더러가 같은 용어: slide_up = 아래에서 위로 등장; 다른 방향의 slide_* 는 렌더러가 그리지 못해 resolve 가 거부); 측정 못 한 키는 행에서 뺌 — 제작 영향: 자막 등장·퇴장 모션 불일치
- 자막 위치 [reaction] (레퍼런스 대비) (`caption.position:reaction_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.reaction.anchor.x, text.roles.reaction.anchor.y — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 제목/자막 위치 불일치
- 자막 크기 [reaction] (레퍼런스 대비) (`caption.size:reaction_ref`): 레퍼런스 미측정(임시값) 키 1개: text.roles.reaction.size_px — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글자 크기 불일치 → 줄 수·가림 영역 변화
- 자막 색·외곽선·그림자·박스 [reaction] (레퍼런스 대비) (`caption.style:reaction_ref`): 레퍼런스 미측정(임시값) 키 5개: text.roles.reaction.color, text.roles.reaction.outline_px, text.roles.reaction.outline_color, text.roles.reaction.box.enabled, text.roles.reaction.shadow_px — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 측정한 채움색·외곽선(배경과 구별될 때)·박스 불투명도의 중앙값 + 레퍼런스 분석기와 같은 정의(reference.textboxes.measure_line / box_alpha; 그림자는 레퍼런스와 같은 추정기 shortkit.util.textmeasure.drop_shadow)로 잰 그림자·박스 여백(박스 경계 − 보이는 잉크)·박스 색; 재지 못한 키(어두운 배경의 그림자, 박스가 안 보이는 경우 등)는 행에서 뺌 — 제작 영향: 글자 색 불일치
- 자막 글꼴·굵기 [reaction] (레퍼런스 대비) (`caption.font:reaction_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.reaction.font_name, text.roles.reaction.bold — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 글꼴 = 역할 합동 판정이 동일(identical)인 면; 굵기 = 그 면의 OS/2 굵기 ≥ typography.BOLD_MIN_WEIGHT(ref fonts 와 같은 규칙) — 제작 영향: 글꼴이 레퍼런스와 다를 수 있음 → 글자 인상·폭·줄바꿈 불일치
- 자막 표시 시간 [reaction] (레퍼런스 대비) (`caption.timing:reaction_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.reaction.timing.min_dur_s, text.roles.reaction.persist — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 적용되지 않아 판정에서 뺀 키: timing.lead_s — 정의: lead_s = 겹치는 말소리 시작 − 대사 자막 시작 → 대사 외 역할은 기준 사건이 없음(값 0). persist: 역할 자막 하나가 영상 길이의 90% 이상 보이면 whole_video(레퍼런스 분석기와 같은 정의); timed 이면 측정한 최소 표시 시간 ≥ timing.min_dur_s − 0.05 s — 제작 영향: 자막 등장 타이밍 불일치
- 자막 등장·퇴장 모션 [reaction] (레퍼런스 대비) (`caption.motion:reaction_ref`): 레퍼런스 미측정(임시값) 키 4개: text.roles.reaction.motion_in.type, text.roles.reaction.motion_in.dur_s, text.roles.reaction.motion_in.scale_from, text.roles.reaction.motion_out.type — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼런스 대비 등장·퇴장 모션: 측정한 최빈 종류와 길이(중앙값)·pop 첫 배율·slide 첫 프레임 이동을 비교(레퍼런스 분석기와 렌더러가 같은 용어: slide_up = 아래에서 위로 등장; 다른 방향의 slide_* 는 렌더러가 그리지 못해 resolve 가 거부); 측정 못 한 키는 행에서 뺌 — 제작 영향: 자막 등장·퇴장 모션 불일치
- 자막 위치 [situation] (레퍼런스 대비) (`caption.position:situation_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.situation.anchor.x, text.roles.situation.anchor.y — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 제목/자막 위치 불일치
- 자막 크기 [situation] (레퍼런스 대비) (`caption.size:situation_ref`): 레퍼런스 미측정(임시값) 키 1개: text.roles.situation.size_px — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글자 크기 불일치 → 줄 수·가림 영역 변화
- 자막 색·외곽선·그림자·박스 [situation] (레퍼런스 대비) (`caption.style:situation_ref`): 레퍼런스 미측정(임시값) 키 1개: text.roles.situation.color — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 측정한 채움색·외곽선(배경과 구별될 때)·박스 불투명도의 중앙값 + 레퍼런스 분석기와 같은 정의(reference.textboxes.measure_line / box_alpha; 그림자는 레퍼런스와 같은 추정기 shortkit.util.textmeasure.drop_shadow)로 잰 그림자·박스 여백(박스 경계 − 보이는 잉크)·박스 색; 재지 못한 키(어두운 배경의 그림자, 박스가 안 보이는 경우 등)는 행에서 뺌 — 제작 영향: 글자 색 불일치
- 자막 글꼴·굵기 [situation] (레퍼런스 대비) (`caption.font:situation_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.situation.font_name, text.roles.situation.bold — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 글꼴 = 역할 합동 판정이 동일(identical)인 면; 굵기 = 그 면의 OS/2 굵기 ≥ typography.BOLD_MIN_WEIGHT(ref fonts 와 같은 규칙) — 제작 영향: 글꼴이 레퍼런스와 다를 수 있음 → 글자 인상·폭·줄바꿈 불일치
- 자막 표시 시간 [situation] (레퍼런스 대비) (`caption.timing:situation_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.situation.timing.min_dur_s, text.roles.situation.persist — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 적용되지 않아 판정에서 뺀 키: timing.lead_s — 정의: lead_s = 겹치는 말소리 시작 − 대사 자막 시작 → 대사 외 역할은 기준 사건이 없음(값 0). persist: 역할 자막 하나가 영상 길이의 90% 이상 보이면 whole_video(레퍼런스 분석기와 같은 정의); timed 이면 측정한 최소 표시 시간 ≥ timing.min_dur_s − 0.05 s — 제작 영향: 자막 등장 타이밍 불일치
- 자막 등장·퇴장 모션 [situation] (레퍼런스 대비) (`caption.motion:situation_ref`): 레퍼런스 미측정(임시값) 키 4개: text.roles.situation.motion_in.type, text.roles.situation.motion_in.dur_s, text.roles.situation.motion_in.scale_from, text.roles.situation.motion_out.type — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼런스 대비 등장·퇴장 모션: 측정한 최빈 종류와 길이(중앙값)·pop 첫 배율·slide 첫 프레임 이동을 비교(레퍼런스 분석기와 렌더러가 같은 용어: slide_up = 아래에서 위로 등장; 다른 방향의 slide_* 는 렌더러가 그리지 못해 resolve 가 거부); 측정 못 한 키는 행에서 뺌 — 제작 영향: 자막 등장·퇴장 모션 불일치
- 자막 위치 [speaker] (레퍼런스 대비) (`caption.position:speaker_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.speaker.anchor.x, text.roles.speaker.anchor.y — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 제목/자막 위치 불일치
- 자막 크기 [speaker] (레퍼런스 대비) (`caption.size:speaker_ref`): 레퍼런스 미측정(임시값) 키 1개: text.roles.speaker.size_px — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글자 크기 불일치 → 줄 수·가림 영역 변화
- 자막 색·외곽선·그림자·박스 [speaker] (레퍼런스 대비) (`caption.style:speaker_ref`): 레퍼런스 미측정(임시값) 키 7개: text.roles.speaker.color, text.roles.speaker.outline_px, text.roles.speaker.box.enabled, text.roles.speaker.box.alpha, text.roles.speaker.box.pad_x, text.roles.speaker.box.pad_y … — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 측정한 채움색·외곽선(배경과 구별될 때)·박스 불투명도의 중앙값 + 레퍼런스 분석기와 같은 정의(reference.textboxes.measure_line / box_alpha; 그림자는 레퍼런스와 같은 추정기 shortkit.util.textmeasure.drop_shadow)로 잰 그림자·박스 여백(박스 경계 − 보이는 잉크)·박스 색; 재지 못한 키(어두운 배경의 그림자, 박스가 안 보이는 경우 등)는 행에서 뺌 — 제작 영향: 글자 색 불일치
- 자막 글꼴·굵기 [speaker] (레퍼런스 대비) (`caption.font:speaker_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.speaker.font_name, text.roles.speaker.bold — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 글꼴 = 역할 합동 판정이 동일(identical)인 면; 굵기 = 그 면의 OS/2 굵기 ≥ typography.BOLD_MIN_WEIGHT(ref fonts 와 같은 규칙) — 제작 영향: 글꼴이 레퍼런스와 다를 수 있음 → 글자 인상·폭·줄바꿈 불일치
- 자막 표시 시간 [speaker] (레퍼런스 대비) (`caption.timing:speaker_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.speaker.timing.min_dur_s, text.roles.speaker.persist — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 적용되지 않아 판정에서 뺀 키: timing.lead_s — 정의: lead_s = 겹치는 말소리 시작 − 대사 자막 시작 → 대사 외 역할은 기준 사건이 없음(값 0). persist: 역할 자막 하나가 영상 길이의 90% 이상 보이면 whole_video(레퍼런스 분석기와 같은 정의); timed 이면 측정한 최소 표시 시간 ≥ timing.min_dur_s − 0.05 s — 제작 영향: 자막 등장 타이밍 불일치
- 자막 등장·퇴장 모션 [speaker] (레퍼런스 대비) (`caption.motion:speaker_ref`): 레퍼런스 미측정(임시값) 키 4개: text.roles.speaker.motion_in.type, text.roles.speaker.motion_in.dur_s, text.roles.speaker.motion_out.type, text.roles.speaker.motion_out.dur_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼런스 대비 등장·퇴장 모션: 측정한 최빈 종류와 길이(중앙값)·pop 첫 배율·slide 첫 프레임 이동을 비교(레퍼런스 분석기와 렌더러가 같은 용어: slide_up = 아래에서 위로 등장; 다른 방향의 slide_* 는 렌더러가 그리지 못해 resolve 가 거부); 측정 못 한 키는 행에서 뺌 — 제작 영향: 자막 등장·퇴장 모션 불일치
- 자막 위치 [title] (레퍼런스 대비) (`caption.position:title_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.title.anchor.x, text.roles.title.anchor.y — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 제목/자막 위치 불일치
- 자막 크기 [title] (레퍼런스 대비) (`caption.size:title_ref`): 레퍼런스 미측정(임시값) 키 1개: text.roles.title.size_px — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글자 크기 불일치 → 줄 수·가림 영역 변화
- 자막 색·외곽선·그림자·박스 [title] (레퍼런스 대비) (`caption.style:title_ref`): 레퍼런스 미측정(임시값) 키 1개: text.roles.title.color — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 측정한 채움색·외곽선(배경과 구별될 때)·박스 불투명도의 중앙값 + 레퍼런스 분석기와 같은 정의(reference.textboxes.measure_line / box_alpha; 그림자는 레퍼런스와 같은 추정기 shortkit.util.textmeasure.drop_shadow)로 잰 그림자·박스 여백(박스 경계 − 보이는 잉크)·박스 색; 재지 못한 키(어두운 배경의 그림자, 박스가 안 보이는 경우 등)는 행에서 뺌 — 제작 영향: 글자 색 불일치
- 자막 글꼴·굵기 [title] (레퍼런스 대비) (`caption.font:title_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.title.font_name, text.roles.title.bold — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 글꼴 = 역할 합동 판정이 동일(identical)인 면; 굵기 = 그 면의 OS/2 굵기 ≥ typography.BOLD_MIN_WEIGHT(ref fonts 와 같은 규칙) — 제작 영향: 글꼴이 레퍼런스와 다를 수 있음 → 글자 인상·폭·줄바꿈 불일치
- 자막 표시 시간 [title] (레퍼런스 대비) (`caption.timing:title_ref`): 레퍼런스 미측정(임시값) 키 1개: text.roles.title.persist — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 적용되지 않아 판정에서 뺀 키: timing.lead_s — 정의: lead_s = 겹치는 말소리 시작 − 대사 자막 시작 → 대사 외 역할은 기준 사건이 없음(값 0); timing.min_dur_s — persist=whole_video(영상 전체에 떠 있음). persist: 역할 자막 하나가 영상 길이의 90% 이상 보이면 whole_video(레퍼런스 분석기와 같은 정의); — 제작 영향: 레퍼런스와의 일치 여부를 판정할 수 없음
- 자막 등장·퇴장 모션 [title] (레퍼런스 대비) (`caption.motion:title_ref`): 레퍼런스 미측정(임시값) 키 1개: text.roles.title.motion_in.type — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼런스 대비 등장·퇴장 모션: 측정한 최빈 종류와 길이(중앙값)·pop 첫 배율·slide 첫 프레임 이동을 비교(레퍼런스 분석기와 렌더러가 같은 용어: slide_up = 아래에서 위로 등장; 다른 방향의 slide_* 는 렌더러가 그리지 못해 resolve 가 거부); 측정 못 한 키는 행에서 뺌 — 제작 영향: 자막 등장·퇴장 모션 불일치
- 자막 말투 (레퍼런스 대비) (`caption.tone:tone_ref`): 레퍼런스 미측정(임시값) 키 1개: text.tone.register — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 자막 종결 어미(말투) 검사 기준이 임시값 → 대본 말투가 레퍼런스와 다를 수 있음
- 줌 배율·길이·가속 곡선·고정점 규칙 (레퍼런스 대비) (`video.zoom:zoom_ref`): 레퍼런스 미측정(임시값) 키 3개: motion.zoom.scale_to, motion.zoom.dur_s, motion.zoom.ease — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 고정점 규칙(recenter) = 출력에서 잰 줌 고정점이 렌더러 규칙(edit.resolve.src_to_region)의 false/true 중 어느 쪽과 맞는지; 재지 못한 키는 행에서 뺌 — 제작 영향: 확대·정지·전환의 크기/길이 불일치
- 정지 길이 (레퍼런스 대비) (`video.freeze:freeze_ref`): 레퍼런스 미측정(임시값) 키 1개: motion.freeze.hold_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 확대·정지·전환의 크기/길이 불일치
- 전환 종류·길이·플래시 색·범위 (레퍼런스 대비) (`video.transitions:transitions_ref`): 레퍼런스 미측정(임시값) 키 4개: motion.transitions.default, motion.transitions.flash.dur_s, motion.transitions.flash.color, motion.transitions.flash.scope — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 플래시 범위 = 플래시 정점에서 영상 영역 밖(자막·장식 제외)이 플래시 색으로 밝아졌는지(canvas) 아닌지(region); 재지 못한 키는 행에서 뺌 — 제작 영향: 확대·정지·전환의 크기/길이 불일치
- 레퍼런스 로고 템플릿 없음 (`identity.logo_templates:all`): 식별 템플릿 기록이 완전하지 않음(상태 unmeasured): 레퍼런스 목록 수집 차단(2026-09-24T17:56:07+00:00, yt-dlp 2026.08.19): https://youtube.com/@joshuamagazine/shorts: DownloadError: ERROR: [youtube:tab] @joshuamagazine/shorts: Unable to download API page: ('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')) (caused by ProxyError("('Unable to connect to proxy', OSError('Tunnel connection fai — 제작 측정은 고정된 최신 100편 스냅샷 구성원만 사용 — `shortkit ref identity-templates` 다시 실행 — 글자 없는 로고는 OCR 검사(identity.forbidden_text)로 잡히지 않음 — 제작 영향: 레퍼런스 채널 식별 요소·같은 녹화 재사용 여부를 확인하지 못함 → 게시 위험
- 레퍼런스와 같은 녹화(영상) 재사용 없음 (`identity.reference_footage:all`): 레퍼런스 영상 지문(exclusions.jsonl reference_footage) 없음 → 같은 녹화 여부 못 잼 (URL 규칙만 확인) — 제작 영향: 레퍼런스 채널 식별 요소·같은 녹화 재사용 여부를 확인하지 못함 → 게시 위험
- **필수** 글자 없는 고정 로고 검사 [v_hall] (출처 기록) (`clean.residual:prov:v_hall:static_graphics`): 출처 기록에서 못 잼: 고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → 코너 캡처를 사람이 확인해야 함 — 제작 영향: 원본 채널 로고(글자 없는 그림)가 최종 화면에 남을 수 있음 → 코너 캡처 확인 필요 — 제작 영향: 원본 로고·출처 표기가 남아 있는지 확인하지 못함 → 게시 위험
- **필수** 원본 좌상단 글자 없는 로고 [v_hall] (출처 기록) (`clean.residual:prov:v_hall:corner:top_left`): 출처 기록에서 못 잼: 고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → 코너 캡처를 사람이 확인해야 함 (코너 캡처: warehouse/overlays/b861fc2d9ea59f5b73542e7ae7351941dce8d8646b370844e66b25a48c7bd971/corner_top_left.png) — 제작 영향: 원본 로고·출처 표기가 남아 있는지 확인하지 못함 → 게시 위험
- **필수** 원본 우상단 글자 없는 로고 [v_hall] (출처 기록) (`clean.residual:prov:v_hall:corner:top_right`): 출처 기록에서 못 잼: 고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → 코너 캡처를 사람이 확인해야 함 (코너 캡처: warehouse/overlays/b861fc2d9ea59f5b73542e7ae7351941dce8d8646b370844e66b25a48c7bd971/corner_top_right.png) — 제작 영향: 원본 로고·출처 표기가 남아 있는지 확인하지 못함 → 게시 위험
- **필수** 원본 좌하단 글자 없는 로고 [v_hall] (출처 기록) (`clean.residual:prov:v_hall:corner:bottom_left`): 출처 기록에서 못 잼: 고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → 코너 캡처를 사람이 확인해야 함 (코너 캡처: warehouse/overlays/b861fc2d9ea59f5b73542e7ae7351941dce8d8646b370844e66b25a48c7bd971/corner_bottom_left.png) — 제작 영향: 원본 로고·출처 표기가 남아 있는지 확인하지 못함 → 게시 위험
- **필수** 원본 우하단 글자 없는 로고 [v_hall] (출처 기록) (`clean.residual:prov:v_hall:corner:bottom_right`): 출처 기록에서 못 잼: 고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → 코너 캡처를 사람이 확인해야 함 (코너 캡처: warehouse/overlays/b861fc2d9ea59f5b73542e7ae7351941dce8d8646b370844e66b25a48c7bd971/corner_bottom_right.png) — 제작 영향: 원본 로고·출처 표기가 남아 있는지 확인하지 못함 → 게시 위험
- **필수** 글자 없는 고정 로고 검사 [v_room] (출처 기록) (`clean.residual:prov:v_room:static_graphics`): 출처 기록에서 못 잼: 고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → 코너 캡처를 사람이 확인해야 함 — 제작 영향: 원본 채널 로고(글자 없는 그림)가 최종 화면에 남을 수 있음 → 코너 캡처 확인 필요 — 제작 영향: 원본 로고·출처 표기가 남아 있는지 확인하지 못함 → 게시 위험
- **필수** 원본 좌상단 글자 없는 로고 [v_room] (출처 기록) (`clean.residual:prov:v_room:corner:top_left`): 출처 기록에서 못 잼: 고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → 코너 캡처를 사람이 확인해야 함 (코너 캡처: warehouse/overlays/18ffe8672d741e3e29c9d891d22c59d453720b086c25b35c88b393d55f92f693/corner_top_left.png) — 제작 영향: 원본 로고·출처 표기가 남아 있는지 확인하지 못함 → 게시 위험
- **필수** 원본 우상단 글자 없는 로고 [v_room] (출처 기록) (`clean.residual:prov:v_room:corner:top_right`): 출처 기록에서 못 잼: 고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → 코너 캡처를 사람이 확인해야 함 (코너 캡처: warehouse/overlays/18ffe8672d741e3e29c9d891d22c59d453720b086c25b35c88b393d55f92f693/corner_top_right.png) — 제작 영향: 원본 로고·출처 표기가 남아 있는지 확인하지 못함 → 게시 위험
- **필수** 원본 좌하단 글자 없는 로고 [v_room] (출처 기록) (`clean.residual:prov:v_room:corner:bottom_left`): 출처 기록에서 못 잼: 고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → 코너 캡처를 사람이 확인해야 함 (코너 캡처: warehouse/overlays/18ffe8672d741e3e29c9d891d22c59d453720b086c25b35c88b393d55f92f693/corner_bottom_left.png) — 제작 영향: 원본 로고·출처 표기가 남아 있는지 확인하지 못함 → 게시 위험
- **필수** 원본 우하단 글자 없는 로고 [v_room] (출처 기록) (`clean.residual:prov:v_room:corner:bottom_right`): 출처 기록에서 못 잼: 고정 카메라 단일 샷(또는 샷이 너무 짧음): 글자 없는 고정 로고를 배경과 구분할 수 없음 → 코너 캡처를 사람이 확인해야 함 (코너 캡처: warehouse/overlays/18ffe8672d741e3e29c9d891d22c59d453720b086c25b35c88b393d55f92f693/corner_bottom_right.png) — 제작 영향: 원본 로고·출처 표기가 남아 있는지 확인하지 못함 → 게시 위험
- **필수** 국소 복원이 보호 영역을 덮음 [남성 두 손(걸어올 때 2)·s1] (`clean.protected_overlap:s1#0`): inpaint 'ov2 burned_subtitle 'WAIT FOR IT'' 가 '남성 두 손(걸어올 때 2)' 의 60% 를 원본 5.3~6.083s 동안 덮음 — 복원 결과(번짐)는 파일에서 잴 수 없음(깨끗한 정답 없음); 사람이 보고 `shortkit qa human-check --kind watch --row clean.protected_overlap:s1#0` 로 기록. 고치는 길: 깨끗한 원본(`source link-original`) → 그 구간을 쓰지 않음 — 제작 영향: 얼굴·손·핵심 물체를 가리는지 확인하지 못함
- BGM 은 깨끗한 음원(레퍼런스에서 분리한 스템 금지) (`audio.bgm:clean_file`): 레퍼런스 분리 음원 파일(presets/*/analysis/*/stems)이 하나도 없어 파형 대조 대상이 없음 — `ref audio-analyze` 뒤 다시 검사 — 제작 영향: BGM 곡·구간·덕킹을 확인하지 못함 → 음악 일치 판정 불가
- BGM 곡·버전·속도·구간 (레퍼런스 대비) (`audio.bgm:bgm_ref`): 레퍼런스 미측정(임시값) 키 5개: audio.bgm.track_id, audio.bgm.title, audio.bgm.version, audio.bgm.tempo_ratio, audio.bgm.section_start_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. audio_bgm.is_match: 곡(track_id/제목)·버전·속도·구간이 모두 레퍼런스와 같아야 같다; 계획이 파일 경로로 BGM 을 지정해 라이브러리 곡 id 가 없음 → 곡 일치는 못 잼 — 제작 영향: BGM 곡/버전/속도/구간/크기 불일치 → 음악 일치 판정 불가
- BGM 크기 (레퍼런스 대비) (`audio.bgm:level_ref`): 레퍼런스 미측정(임시값) 키 1개: audio.bgm.gain_db — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼런스와 같은 정의(ref audio-measure: 깨끗한 음원 LS 이득 + 목표 LUFS − 믹스 LUFS) — 제작 영향: BGM 곡/버전/속도/구간/크기 불일치 → 음악 일치 판정 불가
- 보존 원음 크기 (레퍼런스 대비) (`audio.original:orig_ref`): 레퍼런스 미측정(임시값) 키 1개: audio.original.keep_gain_db — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 크기 = 보존 원음 통합 음량 − 프로그램 통합 음량(LU), ref audio-measure 와 같은 정의 — 제작 영향: 보존 원음 크기 불일치
- 효과음 [fx1] 종류 = 소리 지문(카탈로그 대비) (`audio.sfx.type:fx1`): 소리 지문으로 종류를 정하지 못함: 효과음 카탈로그 미측정(상태 unmeasured: 2026-09-24: 레퍼런스 최신 50편 다운로드 불가(youtube 차단), Demucs 가중치 호스트(dl.fbaipublicfiles.com) 차단) — 종류 지문 없음 — 제작 영향: 레퍼런스와의 일치 여부를 판정할 수 없음
- 효과음 [fx2] 종류 = 소리 지문(카탈로그 대비) (`audio.sfx.type:fx2`): 소리 지문으로 종류를 정하지 못함: 효과음 카탈로그 미측정(상태 unmeasured: 2026-09-24: 레퍼런스 최신 50편 다운로드 불가(youtube 차단), Demucs 가중치 호스트(dl.fbaipublicfiles.com) 차단) — 종류 지문 없음 — 제작 영향: 레퍼런스와의 일치 여부를 판정할 수 없음
- 효과음 [fx3] 종류 = 소리 지문(카탈로그 대비) (`audio.sfx.type:fx3`): 소리 지문으로 종류를 정하지 못함: 효과음 카탈로그 미측정(상태 unmeasured: 2026-09-24: 레퍼런스 최신 50편 다운로드 불가(youtube 차단), Demucs 가중치 호스트(dl.fbaipublicfiles.com) 차단) — 종류 지문 없음 — 제작 영향: 레퍼런스와의 일치 여부를 판정할 수 없음
- 효과음 [fx4] 종류 = 소리 지문(카탈로그 대비) (`audio.sfx.type:fx4`): 소리 지문으로 종류를 정하지 못함: 효과음 카탈로그 미측정(상태 unmeasured: 2026-09-24: 레퍼런스 최신 50편 다운로드 불가(youtube 차단), Demucs 가중치 호스트(dl.fbaipublicfiles.com) 차단) — 종류 지문 없음 — 제작 영향: 레퍼런스와의 일치 여부를 판정할 수 없음
- 효과음 종류별 개수 (레퍼런스 포맷 범위 대비) (`audio.sfx.count:catalog`): sfx_catalog.json 미측정: 2026-09-24: 레퍼런스 최신 50편 다운로드 불가(youtube 차단), Demucs 가중치 호스트(dl.fbaipublicfiles.com) 차단 — 제작 영향: 레퍼런스와의 일치 여부를 판정할 수 없음
- 효과음 크기 (레퍼런스 대비) (`audio.sfx.placement:sfx_gain_ref`): 레퍼런스 미측정(임시값) 키 1개: audio.sfx.gain_db_default — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 효과음 크기 불일치
- 음량 (레퍼런스 대비) (`audio.loudness:loudness_ref`): 레퍼런스 미측정(임시값) 키 2개: audio.loudness.integrated_lufs, audio.loudness.true_peak_db — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 최종 음량 불일치
- 영상 길이 (레퍼런스 분포 대비) (`structure.duration:duration_ref`): 레퍼런스 미측정(임시값) 키 3개: structure.duration_s.p10, structure.duration_s.p50, structure.duration_s.p90 — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 판정: 레퍼런스 영상별 값의 p10 ≤ 출력 ≤ p90 이면 같다; 레퍼런스 중앙값(p50) 대비 위치(observed.vs_reference_median)를 함께 적음 — p50 이 [p10, p90] 밖이면 분포 기록이 잘못된 것이라 못 잼 — 제작 영향: 영상 길이 관측 범위(p10..p90)가 없어 길이 적합성 판정 불가 → 너무 길거나 짧은 편집 가능
- 첫 시간제 자막 시각 (레퍼런스 대비) (`structure.duration:first_caption_ref`): 레퍼런스 미측정(임시값) 키 1개: structure.first_caption_at_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 정의: 제목·설명을 뺀 첫 시간제 자막의 출력 등장 시각(레퍼런스 분석기 structure.first_caption_at_s 와 같음) — 제작 영향: 영상 길이·전개 구조 불일치
- 컷 밀도: 10초당 전환 수 (레퍼런스 포맷 분포 대비) (`structure.cuts:rate_ref`): 레퍼런스 미측정(임시값) 키 3개: structure.cuts_per_10s.p10, structure.cuts_per_10s.p50, structure.cuts_per_10s.p90 — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 출력에서 잰 전환(cut·flash·crossfade: 계획 경계에서 보인 것 + 계획 밖 컷) 기준. 레퍼런스 값 = `shortkit ref aggregate` 의 영상별 값(한 영상 = 1표본) 분포, 출력 값 = 같은 정의로 출력 MP4 에서 잰 값(reference.aggregate.CUT_RATE_METHOD / SHOT_LEN_METHOD). 판정: 레퍼런스 영상별 값의 p10 ≤ 출력 ≤ p90 이면 같다; 레퍼런스 중앙값(p50) 대비 위치(observed.vs_reference_median)를 함께 적음 — p50 이 [p10, p90] 밖이면 분포 기록이 잘못된 것이라 못 잼 — 제작 영향: 영상 길이·전개 구조 불일치
- 샷 길이 중앙값 (레퍼런스 포맷 분포 대비) (`structure.cuts:shot_len_ref`): 레퍼런스 미측정(임시값) 키 3개: structure.shot_len_s.p10, structure.shot_len_s.p50, structure.shot_len_s.p90 — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 출력에서 잰 전환 사이 샷 길이(첫·마지막 샷 포함)의 중앙값. 레퍼런스 값 = `shortkit ref aggregate` 의 영상별 값(한 영상 = 1표본) 분포, 출력 값 = 같은 정의로 출력 MP4 에서 잰 값(reference.aggregate.CUT_RATE_METHOD / SHOT_LEN_METHOD). 판정: 레퍼런스 영상별 값의 p10 ≤ 출력 ≤ p90 이면 같다; 레퍼런스 중앙값(p50) 대비 위치(observed.vs_reference_median)를 함께 적음 — p50 이 [p10, p90] 밖이면 분포 기록이 잘못된 것이라 못 잼 — 제작 영향: 영상 길이·전개 구조 불일치
- 표지 구성 (레퍼런스 대비) (`cover.frame:cover_ref`): 레퍼런스 미측정(임시값) 키 2개: cover.source, cover.text_role — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 표지 프레임(cover.source: first_frame = 0초)에서 cover.text_role 역할 자막의 문구를 OCR 로 확인 — 제작 영향: 표지 구성 불일치
- 확대(줌) 있다/없다 (레퍼런스 대비) (`presence:zoom`): 레퍼런스 미측정(임시값) 키 1개: presence.zoom — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼런스가 없다 → 우리도 없어야 같다; 레퍼런스 영상 모두 있다 → 우리도 있어야 같다; 일부 영상에만 있다 → 있다/없다 모두 관측 범위 안 — 제작 영향: 레퍼런스에 이 효과가 있는지 없는지 몰라 과용/누락을 판정할 수 없음
- 정지 있다/없다 (레퍼런스 대비) (`presence:freeze`): 레퍼런스 미측정(임시값) 키 1개: presence.freeze — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼런스가 없다 → 우리도 없어야 같다; 레퍼런스 영상 모두 있다 → 우리도 있어야 같다; 일부 영상에만 있다 → 있다/없다 모두 관측 범위 안 — 제작 영향: 레퍼런스에 이 효과가 있는지 없는지 몰라 과용/누락을 판정할 수 없음
- 속도 변화 있다/없다 (레퍼런스 대비) (`presence:speed_change`): 레퍼런스 미측정(임시값) 키 1개: presence.speed_change — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼런스가 없다 → 우리도 없어야 같다; 레퍼런스 영상 모두 있다 → 우리도 있어야 같다; 일부 영상에만 있다 → 있다/없다 모두 관측 범위 안 — 제작 영향: 레퍼런스에 이 효과가 있는지 없는지 몰라 과용/누락을 판정할 수 없음
- 플래시 전환 있다/없다 (레퍼런스 대비) (`presence:flash`): 레퍼런스 미측정(임시값) 키 1개: presence.flash — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼런스가 없다 → 우리도 없어야 같다; 레퍼런스 영상 모두 있다 → 우리도 있어야 같다; 일부 영상에만 있다 → 있다/없다 모두 관측 범위 안 — 제작 영향: 레퍼런스에 이 효과가 있는지 없는지 몰라 과용/누락을 판정할 수 없음
- 크로스페이드 있다/없다 (레퍼런스 대비) (`presence:crossfade`): 레퍼런스 미측정(임시값) 키 1개: presence.crossfade — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼런스가 없다 → 우리도 없어야 같다; 레퍼런스 영상 모두 있다 → 우리도 있어야 같다; 일부 영상에만 있다 → 있다/없다 모두 관측 범위 안 — 제작 영향: 레퍼런스에 이 효과가 있는지 없는지 몰라 과용/누락을 판정할 수 없음
- 움직이는 장식 있다/없다 (레퍼런스 대비) (`presence:decorations`): 레퍼런스 미측정(임시값) 키 1개: presence.decorations — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼런스가 없다 → 우리도 없어야 같다; 레퍼런스 영상 모두 있다 → 우리도 있어야 같다; 일부 영상에만 있다 → 있다/없다 모두 관측 범위 안 — 제작 영향: 레퍼런스에 이 효과가 있는지 없는지 몰라 과용/누락을 판정할 수 없음
- BGM 있다/없다 (레퍼런스 대비) (`presence:bgm`): 레퍼런스 미측정(임시값) 키 1개: presence.bgm — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼런스가 없다 → 우리도 없어야 같다; 레퍼런스 영상 모두 있다 → 우리도 있어야 같다; 일부 영상에만 있다 → 있다/없다 모두 관측 범위 안 — 제작 영향: 레퍼런스에 이 효과가 있는지 없는지 몰라 과용/누락을 판정할 수 없음
- 원음 있다/없다 (레퍼런스 대비) (`presence:original_audio`): 레퍼런스 미측정(임시값) 키 1개: presence.original_audio — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼런스가 없다 → 우리도 없어야 같다; 레퍼런스 영상 모두 있다 → 우리도 있어야 같다; 일부 영상에만 있다 → 있다/없다 모두 관측 범위 안 — 제작 영향: 레퍼런스에 이 효과가 있는지 없는지 몰라 과용/누락을 판정할 수 없음
- 덕킹 있다/없다 (레퍼런스 대비) (`presence:ducking`): 레퍼런스 미측정(임시값) 키 1개: presence.ducking — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼런스가 없다 → 우리도 없어야 같다; 레퍼런스 영상 모두 있다 → 우리도 있어야 같다; 일부 영상에만 있다 → 있다/없다 모두 관측 범위 안 — 제작 영향: 레퍼런스에 이 효과가 있는지 없는지 몰라 과용/누락을 판정할 수 없음
- 의도적 정적 있다/없다 (레퍼런스 대비) (`presence:intentional_silence`): 레퍼런스 미측정(임시값) 키 1개: presence.intentional_silence — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼런스가 없다 → 우리도 없어야 같다; 레퍼런스 영상 모두 있다 → 우리도 있어야 같다; 일부 영상에만 있다 → 있다/없다 모두 관측 범위 안 — 제작 영향: 레퍼런스에 이 효과가 있는지 없는지 몰라 과용/누락을 판정할 수 없음
- 자막 역할·표시 (레퍼런스와 같은 절대 시각 1초 격자) (`ref_grid.captions:grid`): 레퍼런스 영상 없음: 에피소드 포맷이 정해지지 않음(UNCLASSIFIED) — 대표 영상을 고를 수 없음 (formats.yaml 상태 unmeasured: 2026-09-24: youtube.com/googlevideo.com 차단으로 최신 100편 목록·영상 미확보 → 포맷 분류 못 함; 라벨 파일 없음 — `shortkit ref classify prepare` 후 영상을 본 사람이 채워야 함; 고정된 최신 100편 스냅샷이 없어 포맷) — 제작 영향: 판정 불가 — 완료로 볼 수 없음
- 컷·전환 위치 (레퍼런스와 같은 절대 시각 1초 격자) (`ref_grid.cuts:grid`): 레퍼런스 영상 없음: 에피소드 포맷이 정해지지 않음(UNCLASSIFIED) — 대표 영상을 고를 수 없음 (formats.yaml 상태 unmeasured: 2026-09-24: youtube.com/googlevideo.com 차단으로 최신 100편 목록·영상 미확보 → 포맷 분류 못 함; 라벨 파일 없음 — `shortkit ref classify prepare` 후 영상을 본 사람이 채워야 함; 고정된 최신 100편 스냅샷이 없어 포맷) — 제작 영향: 판정 불가 — 완료로 볼 수 없음
- 효과음 종류·자리 (레퍼런스와 같은 절대 시각 0.5초 격자) (`ref_grid.sfx:grid`): 레퍼런스 영상 없음: 에피소드 포맷이 정해지지 않음(UNCLASSIFIED) — 대표 영상을 고를 수 없음 (formats.yaml 상태 unmeasured: 2026-09-24: youtube.com/googlevideo.com 차단으로 최신 100편 목록·영상 미확보 → 포맷 분류 못 함; 라벨 파일 없음 — `shortkit ref classify prepare` 후 영상을 본 사람이 채워야 함; 고정된 최신 100편 스냅샷이 없어 포맷) — 제작 영향: 판정 불가 — 완료로 볼 수 없음
- 레퍼런스 1편과 같은 절대 시각 1초 격자 비교 시트 (`ref_grid.sheet:sheet`): 레퍼런스 MP4 없음 — 시트의 레퍼런스 줄이 '못 잼'으로 그려짐: 에피소드 포맷이 정해지지 않음(UNCLASSIFIED) — 대표 영상을 고를 수 없음 (formats.yaml 상태 unmeasured: 2026-09-24: youtube.com/googlevideo.com 차단으로 최신 100편 목록·영상 미확보 → 포맷 분류 못 함; 라벨 파일 없음 — `shortkit ref classify prepare` 후 영상을 본 사람이 채워야 함; 고정된 최신 100편 스냅샷이 없어 포맷) — 제작 영향: 판정 불가 — 완료로 볼 수 없음

## 비교 시트
- `episodes/test-restore-001/qa/compare_sheet.png`
- `episodes/test-restore-001/qa/compare_sheet_p02.png`

## 결함 기록 (defects.jsonl)
- 열림 12 / 이번에 고침 확인 10 / 재발 0 / 새로 등록 0 / 고침 기록 필요(resolved_without_fix·fixed_unrechecked) 0 / 못 잼으로 바뀌어 열린 채 0 / 이전 규칙으로 닫혔다가 재분류 0
- 같은 검사 재확인: test-coverage-001: caption.font=ok, caption.reveal=problem, clean.protected_overlap=ok, clean.residual=problem, cover_up.faces=ok, video.mapping=ok, video.speed=ok, video.zoom=ok
- 같은 검사 재확인: test-pipeline-001: caption.font=ok, caption.reveal=ok, clean.protected_overlap=ok, clean.residual=unmeasured, cover_up.faces=ok, video.mapping=ok, video.speed=ok, video.zoom=ok
- 같은 검사 재확인: test-qa-bad: caption.font=problem, caption.reveal=problem, clean.protected_overlap=ok, clean.residual=problem, cover_up.faces=problem, video.mapping=ok, video.speed=ok, video.zoom=ok
- 같은 검사 재확인: test-qa-good: caption.font=ok, caption.reveal=problem, clean.protected_overlap=ok, clean.residual=ok, cover_up.faces=ok, video.mapping=ok, video.speed=ok, video.zoom=ok

---
판정 기준: 같다=허용오차 안, 다르다=허용오차 밖, 못 잼=측정 불가(완료로 치지 않음 — 필수 표시가 없는 '참고' 못 잼도 production 최종 관문 P4 에서 완료를 막는다; 다른 필수 행이 같은 판정을 하는 경우만 예외). 레퍼런스 열의 '못 잼'은 레퍼런스에서 측정되지 않은 임시값이라는 뜻이다.

오디오 판정은 모두 기계 측정(파형 대조·최소제곱·정합 필터·EBU R128)이다. 사람이 직접 들어 본 청취 확인은 이 보고서에 포함되어 있지 않다.
