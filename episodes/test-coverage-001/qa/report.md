# QA 보고서 — test-coverage-001

- 측정 대상: `episodes/test-coverage-001/output/test-coverage-001.mp4` (sha256 `a8b0f3006c3b740d…`, 1080x1920, 22.50s)
- 원칙: 최종 MP4 만 측정(타임라인/코드가 맞다고 출력이 맞다고 보지 않음)
- 프리셋: joshuamagazine-v1 / 포맷 UNCLASSIFIED / 모드 **test**
- 레퍼런스(같은 절대 시각 비교): 없음(못 잼) (분석 파일: 없음)
- 포맷 UNCLASSIFIED 대표 영상(formats.yaml): 못 잼 — 에피소드 포맷이 정해지지 않음(UNCLASSIFIED) — 대표 영상을 고를 수 없음 (formats.yaml 상태 unmeasured: 2026-09-24: youtube.com/googlevideo.com 차단으로 최신 100편 목록·영상 미확보 → 포맷 분류 못 함; 라벨 파일 없음 — `shortkit ref classify prepare` 후 영상을 본 사람이 채워야 함; 고정된 최신 100편 스냅샷이 없어 포맷)
- 측정 시각: 2026-09-25T12:06:17+00:00 / 도구: OCR=5.3.4, 얼굴검출=shortkit.clean.faces haar frontal+profile (shortkit.HaarCascade(numpy))

## 최종 관문: **불합격 — 못 잼 71건(필수 1, 참고 70)**
- ✗ G2: 필수 항목 못 잼 1건 — 못 잼은 완료가 아님 — caption.reveal:reveal
- △ R1: 레퍼런스 같은 시각 비교 없음/불충분: 레퍼런스 영상 없음 — 에피소드 포맷이 정해지지 않음(UNCLASSIFIED) — 대표 영상을 고를 수 없음 (formats.yaml 상태 unmeasured: 2026-09-24: youtube.com/googlevideo.com 차단으로 최신 100편 목록·영상 미확보 → 포맷 분류 못 함; 라벨 파일 없음 — `shortkit ref classify prepare` 후 영상을 본 사람이 채워야 함; 고정된 최신 100편 스냅샷이 없어 포맷)
- △ P1: 프리셋 미측정(임시값) 키 266개
- △ P2: 레퍼런스 대비 못 잼 64건
- △ P3: 테스트 모드 출력(파이프라인 검증용) — 게시 불가
- △ P4: 필수 표시가 없는 못 잼 6건 — 못 잰 항목은 완료로 치지 않음

## 요약
- 전체 218행: 같다 147 / 다르다 0 (의도한 변경 0, 의도하지 않음 0) / 못 잼 71
- 계획 대비(출력이 계획대로인가): {'same': 147, 'unmeasured': 7}
- 레퍼런스 대비(레퍼런스와 같은가): {'unmeasured': 64}
- 프리셋 미측정(임시값) 키: 266개

| 분류 | 같다 | 다르다 | 못 잼 |
|---|---:|---:|---:|
| 화면 구성 | 4 | 0 | 5 |
| 글자 위치 | 14 | 0 | 8 |
| 자막 내용·말투 | 9 | 0 | 3 |
| 자막 스타일 | 7 | 0 | 4 |
| 폰트 | 11 | 0 | 4 |
| 자막 타이밍 | 7 | 0 | 4 |
| 자막 등장·퇴장 모션 | 13 | 0 | 4 |
| 컷 | 11 | 0 | 2 |
| 모션(확대·정지·전환) | 14 | 0 | 9 |
| 움직이는 장식(위치/밝기 각각) | 6 | 0 | 3 |
| 식별 요소 | 1 | 0 | 2 |
| 로고 잔류 | 1 | 0 | 2 |
| 얼굴·손·물체 가림 | 18 | 0 | 0 |
| 음악 구간 | 11 | 0 | 6 |
| 원음 | 1 | 0 | 2 |
| 효과음 종류별 개수 | 9 | 0 | 5 |
| 사건과의 시차 | 3 | 0 | 0 |
| 사건 없는 효과음 0 | 3 | 0 | 0 |
| 음량 | 2 | 0 | 1 |
| 구성·표지 | 2 | 0 | 3 |
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
| 자막이 안전 여백 안에 있음 | 못 잼 | {"left":54,"right":54,"top":110,"bottom":250} | {"min_margin_px":{"left":81,"top":297,"right":79,"bottom":455}} | 같다 (참고) | 아니오 | — |
| 영상 영역 채우기(cover/contain) | — | {"s1":"cover","s2":"cover","s3":"cover","s4":"cover","s5":"cover"} | {"clips":[{"clip_id":"s1","t":2.4,"status":"unmeasured","fit":null,"err":null,"band_share… | 못 잼 (참고) | 아니오 | 모든 클립에서 cover 와 contain 렌더링이 같아(소스 비율 = 영역 비율) 채우기 방식을 출력에서 구별할 수 없음 |
| 영상 영역 채우기 (레퍼런스 대비) | 못 잼 | {"canvas.video_region.fit":"cover"} | — | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: canvas.video_region.fit — 출력이 임시값과 같아도 레퍼런스와 같다고 … |

### 글자 위치

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 위치 [c_title·title] "빈 방에 들어온 사람들" | 못 잼 | {"center":[539.9,335.1],"bbox":[157.4,288.6,765.0,93.0],"resolution":[1080,1920]} | {"center":[542.5,335.5],"bbox":[172,297,741,77],"resolution":[1080,1920],"dx":2.6,"dy":0.… | 같다 | 아니오 | t=0.12s [프레임](frames/cap_c_title_0000120.png) |
| 자막 크기·줄 수 [c_title·title] "빈 방에 들어온 사람들" | 못 잼 | {"fill_h":81.0,"lines":1,"max_width_px":980.0,"max_lines":2,"size_px":84.0,"max_chars_per… | {"fill_h":77,"fill_w":741,"lines":1,"size_px_est":79.9,"max_chars_line":9} | 같다 | 아니오 | t=0.12s [프레임](frames/cap_c_title_0000120.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_desc·description] "설정 연결 검증 테스트 2편" | 못 잼 | {"center":[540.0,503.1],"bbox":[290.0,477.1,500.0,52.0],"resolution":[1080,1920]} | {"center":[539.5,503.5],"bbox":[297,483,485,41],"resolution":[1080,1920],"dx":-0.5,"dy":0… | 같다 | 아니오 | t=0.32s [프레임](frames/cap_c_desc_0000320.png) |
| 자막 크기·줄 수 [c_desc·description] "설정 연결 검증 테스트 2편" | 못 잼 | {"fill_h":44.0,"lines":1,"max_width_px":980.0,"max_lines":1,"size_px":46.0,"max_chars_per… | {"fill_h":41,"fill_w":485,"lines":1,"size_px_est":42.9,"max_chars_line":11} | 같다 | 아니오 | t=0.32s [프레임](frames/cap_c_desc_0000320.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_sit1·situation] "한 사람이 빈 방을 가로질러 나간" | 못 잼 | {"center":[540.2,1433.8],"bbox":[71.2,1395.8,938.0,76.0],"resolution":[1080,1920]} | {"center":[541.0,1434.0],"bbox":[81,1403,920,62],"resolution":[1080,1920],"dx":0.8,"dy":0… | 같다 | 아니오 | t=0.54s [프레임](frames/cap_c_sit1_0000540.png) |
| 자막 크기·줄 수 [c_sit1·situation] "한 사람이 빈 방을 가로질러 나간" | 못 잼 | {"fill_h":64.0,"lines":1,"max_width_px":960.0,"max_lines":2,"size_px":66.0,"max_chars_per… | {"fill_h":62,"fill_w":920,"lines":1,"size_px_est":63.9,"max_chars_line":14} | 같다 | 아니오 | t=0.54s [프레임](frames/cap_c_sit1_0000540.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_sit2·situation] "한 남성이 카메라 앞까지 걸어온다" | 못 잼 | {"center":[540.2,1433.8],"bbox":[78.8,1395.8,923.0,76.0],"resolution":[1080,1920]} | {"center":[541.0,1434.0],"bbox":[88,1403,906,62],"resolution":[1080,1920],"dx":0.8,"dy":0… | 같다 | 아니오 | t=5.24s [프레임](frames/cap_c_sit2_0005240.png) |
| 자막 크기·줄 수 [c_sit2·situation] "한 남성이 카메라 앞까지 걸어온다" | 못 잼 | {"fill_h":64.0,"lines":1,"max_width_px":960.0,"max_lines":2,"size_px":66.0,"max_chars_per… | {"fill_h":62,"fill_w":906,"lines":1,"size_px_est":63.9,"max_chars_line":14} | 같다 | 아니오 | t=5.24s [프레임](frames/cap_c_sit2_0005240.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_rx·reaction] "빤히" | 못 잼 | {"center":[540.1,1144.6],"bbox":[463.1,1101.1,154.0,87.0],"resolution":[1080,1920]} | {"center":[538.0,1145.5],"bbox":[474,1111,128,69],"resolution":[1080,1920],"dx":-2.1,"dy"… | 같다 | 아니오 | t=10.22s [프레임](frames/cap_c_rx_0010219.png) |
| 자막 크기·줄 수 [c_rx·reaction] "빤히" | 못 잼 | {"fill_h":73.0,"lines":1,"max_width_px":900.0,"max_lines":1,"size_px":76.0,"max_chars_per… | {"fill_h":69,"fill_w":128,"lines":1,"size_px_est":71.8,"max_chars_line":2} | 같다 | 아니오 | t=10.22s [프레임](frames/cap_c_rx_0010219.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_sit3·situation] "두 사람이 나란히 와서 선다" | 못 잼 | {"center":[539.8,1433.8],"bbox":[169.8,1395.8,740.0,76.0],"resolution":[1080,1920]} | {"center":[541.5,1434.0],"bbox":[180,1403,723,62],"resolution":[1080,1920],"dx":1.7,"dy":… | 같다 | 아니오 | t=13.94s [프레임](frames/cap_c_sit3_0013939.png) |
| 자막 크기·줄 수 [c_sit3·situation] "두 사람이 나란히 와서 선다" | 못 잼 | {"fill_h":64.0,"lines":1,"max_width_px":960.0,"max_lines":2,"size_px":66.0,"max_chars_per… | {"fill_h":62,"fill_w":723,"lines":1,"size_px_est":63.9,"max_chars_line":11} | 같다 | 아니오 | t=13.94s [프레임](frames/cap_c_sit3_0013939.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_sit4·situation] "그리고 둘 다 떠난다" | 못 잼 | {"center":[540.0,1433.8],"bbox":[268.5,1395.8,543.0,76.0],"resolution":[1080,1920]} | {"center":[541.0,1434.0],"bbox":[278,1403,526,62],"resolution":[1080,1920],"dx":1.0,"dy":… | 같다 | 아니오 | t=18.94s [프레임](frames/cap_c_sit4_0018940.png) |
| 자막 크기·줄 수 [c_sit4·situation] "그리고 둘 다 떠난다" | 못 잼 | {"fill_h":64.0,"lines":1,"max_width_px":960.0,"max_lines":2,"size_px":66.0,"max_chars_per… | {"fill_h":62,"fill_w":526,"lines":1,"size_px_est":63.9,"max_chars_line":8} | 같다 | 아니오 | t=18.94s [프레임](frames/cap_c_sit4_0018940.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [description] (레퍼런스 대비) | 못 잼 | {"text.roles.description.anchor.x":540,"text.roles.description.anchor.y":500} | {"x":539.5,"y":503.5} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.description.anchor.x, text.roles.descr… |
| 자막 크기 [description] (레퍼런스 대비) | 못 잼 | {"text.roles.description.size_px":46} | {"size_px_est":42.9} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.roles.description.size_px — 출력이 임시값과 같아도 레퍼런… |
| 자막 위치 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.anchor.x":540,"text.roles.reaction.anchor.y":1140} | {"x":538.0,"y":1145.5} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.reaction.anchor.x, text.roles.reaction… |
| 자막 크기 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.size_px":76} | {"size_px_est":71.8} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.roles.reaction.size_px — 출력이 임시값과 같아도 레퍼런스와 … |
| 자막 위치 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.anchor.x":540,"text.roles.situation.anchor.y":1430} | {"x":541.0,"y":1434.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.situation.anchor.x, text.roles.situati… |
| 자막 크기 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.size_px":66} | {"size_px_est":63.9} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.roles.situation.size_px — 출력이 임시값과 같아도 레퍼런스와… |
| 자막 위치 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.anchor.x":540,"text.roles.title.anchor.y":330} | {"x":542.5,"y":335.5} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.title.anchor.x, text.roles.title.ancho… |
| 자막 크기 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.size_px":84} | {"size_px_est":79.9} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.roles.title.size_px — 출력이 임시값과 같아도 레퍼런스와 같다고… |

### 자막 내용·말투

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 문구(OCR) [c_title·title] "빈 방에 들어온 사람들" | — | 빈 방에 들어온 사람들 | {"ocr":"빈 방 에 들어온 사람들","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=0.12s [프레임](frames/cap_c_title_0000120.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_desc·description] "설정 연결 검증 테스트 2편" | — | 설정 연결 검증 테스트 2편 | {"ocr":"설정 연결 검증 테스트 2 편","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=0.32s [프레임](frames/cap_c_desc_0000320.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_sit1·situation] "한 사람이 빈 방을 가로질러 나간" | — | 한 사람이 빈 방을 가로질러 나간다 | {"ocr":"한 사 람 이 빈 방 을 가 로 질 러 나간다","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=0.54s [프레임](frames/cap_c_sit1_0000540.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_sit2·situation] "한 남성이 카메라 앞까지 걸어온다" | — | 한 남성이 카메라 앞까지 걸어온다 | {"ocr":"한 남 성 이 카메라 앞 까지 걸 어 온 다","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=5.24s [프레임](frames/cap_c_sit2_0005240.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_rx·reaction] "빤히" | — | 빤히 | {"ocr":"","similarity":0.0,"match":"geometry(짧은 문구 OCR 실패)","shape":{"iou":0.9757,"glyph_… | 같다 | 아니오 | t=10.22s [프레임](frames/cap_c_rx_0010219.png) 짧은 문구를 OCR 이 읽지 못해 글자 모양으로 확인: 기대 문구를 기대 글꼴로 렌더한 모양과 글자별 IoU 모두 하한 이상… |
| 자막 문구(OCR) [c_sit3·situation] "두 사람이 나란히 와서 선다" | — | 두 사람이 나란히 와서 선다 | {"ocr":"두 사 람 이 나란히 와서 선다","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=13.94s [프레임](frames/cap_c_sit3_0013939.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_sit4·situation] "그리고 둘 다 떠난다" | — | 그리고 둘 다 떠난다 | {"ocr":"그리고 둘 다 떠난다","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=18.94s [프레임](frames/cap_c_sit4_0018940.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 반전 전에 반전 내용을 미리 말하지 않음 | — | {"reveal":{"none":true,"reason":"빈 방에 사람이 들어와 걸어 나가고(people-detection 2.0~6.8s), 남성이 카메라 … | — | 못 잼 | 아니오 | plan 이 '반전 없음'(reveal.none: 빈 방에 사람이 들어와 걸어 나가고(people-detection 2.0~… |
| 자막 말투(종결어미, OCR) | 못 잼 | 반말_구어체 | {"n":4,"counts":{"명사형/기타":2,"반말":4},"mode":"반말_구어체","items":[{"text":"빈 방 에 들어온 사람들","cla… | 같다 (참고) | 아니오 | OCR 문구의 종결 어미를 레퍼런스 분석기·validate 와 같은 분류기(reference.aggregate.ending_… |
| 자막 이모지(색 글리프) — 계획 대비 | — | {"planned_emoji":{"c_title":0,"c_desc":0,"c_sit1":0,"c_sit2":0,"c_rx":0,"c_sit3":0,"c_sit… | {"per_caption":[{"caption":"c_title","planned":0,"observed":0,"status":"measured"},{"capt… | 같다 (참고) | 아니오 | 자막이 그린 화소 중 표시 중 정지·채도 높음·자막 색(채움·강조·외곽선·그림자·박스)과 그 혼합이 아닌 덩어리를 색 글리프… |
| 자막 이모지 (레퍼런스 대비) | 못 잼 | {"text.tone.emoji":false} | {"captions_with_emoji":0,"unmeasured_captions":[]} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.tone.emoji — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.… |
| 자막 말투 (레퍼런스 대비) | 못 잼 | {"text.tone.register":"반말_구어체"} | {"register":"반말_구어체"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.tone.register — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 … |

### 자막 스타일

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 색·외곽선·그림자·박스 [c_title·title] "빈 방에 들어온 사람들" | 못 잼 | {"color":"#FFFFFF","outline_px":6.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FFFFFF","outline_px":16,"outline_color":"#000000","box_alpha":null,"highl… | 같다 | 아니오 | t=0.12s [프레임](frames/cap_c_title_0000120.png) 배경이 외곽선 색과 같아 외곽선 두께·색은 못 잼(판정에서 뺌); 그림자 못 잼(판정에서 뺌): 배경이 어두워(휘도 < 50… |
| 자막 색·외곽선·그림자·박스 [c_desc·description] "설정 연결 검증 테스트 2편" | 못 잼 | {"color":"#E6E6E6","outline_px":4.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#E5E5E5","outline_px":11,"outline_color":"#000000","box_alpha":null,"highl… | 같다 | 아니오 | t=0.32s [프레임](frames/cap_c_desc_0000320.png) 배경이 외곽선 색과 같아 외곽선 두께·색은 못 잼(판정에서 뺌); 그림자 못 잼(판정에서 뺌): 배경이 어두워(휘도 < 50… |
| 자막 색·외곽선·그림자·박스 [c_sit1·situation] "한 사람이 빈 방을 가로질러 나간" | 못 잼 | {"color":"#FFFFFF","outline_px":6.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FFFFFF","outline_px":16,"outline_color":"#000000","box_alpha":null,"highl… | 같다 | 아니오 | t=0.54s [프레임](frames/cap_c_sit1_0000540.png) 배경이 외곽선 색과 같아 외곽선 두께·색은 못 잼(판정에서 뺌); 그림자 못 잼(판정에서 뺌): 배경이 어두워(휘도 < 50… |
| 자막 색·외곽선·그림자·박스 [c_sit2·situation] "한 남성이 카메라 앞까지 걸어온다" | 못 잼 | {"color":"#FFFFFF","outline_px":6.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FFFFFF","outline_px":16,"outline_color":"#000000","box_alpha":null,"highl… | 같다 | 아니오 | t=5.24s [프레임](frames/cap_c_sit2_0005240.png) 배경이 외곽선 색과 같아 외곽선 두께·색은 못 잼(판정에서 뺌); 그림자 못 잼(판정에서 뺌): 배경이 어두워(휘도 < 50… |
| 자막 색·외곽선·그림자·박스 [c_rx·reaction] "빤히" | 못 잼 | {"color":"#FFE400","outline_px":7.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FEE300","outline_px":7,"outline_color":"#040000","box_alpha":0.024,"highl… | 같다 | 아니오 | t=10.22s [프레임](frames/cap_c_rx_0010219.png) |
| 자막 색·외곽선·그림자·박스 [c_sit3·situation] "두 사람이 나란히 와서 선다" | 못 잼 | {"color":"#FFFFFF","outline_px":6.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FFFFFF","outline_px":16,"outline_color":"#000000","box_alpha":null,"highl… | 같다 | 아니오 | t=13.94s [프레임](frames/cap_c_sit3_0013939.png) 배경이 외곽선 색과 같아 외곽선 두께·색은 못 잼(판정에서 뺌); 그림자 못 잼(판정에서 뺌): 배경이 어두워(휘도 < 50… |
| 자막 색·외곽선·그림자·박스 [c_sit4·situation] "그리고 둘 다 떠난다" | 못 잼 | {"color":"#FFFFFF","outline_px":6.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FFFFFF","outline_px":16,"outline_color":"#000000","box_alpha":null,"highl… | 같다 | 아니오 | t=18.94s [프레임](frames/cap_c_sit4_0018940.png) 배경이 외곽선 색과 같아 외곽선 두께·색은 못 잼(판정에서 뺌); 그림자 못 잼(판정에서 뺌): 배경이 어두워(휘도 < 50… |
| 자막 색·외곽선·그림자·박스 [description] (레퍼런스 대비) | 못 잼 | {"text.roles.description.color":"#E6E6E6"} | {"fill_color":"#E5E5E5"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.roles.description.color — 출력이 임시값과 같아도 레퍼런스와… |
| 자막 색·외곽선·그림자·박스 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.color":"#FFE400","text.roles.reaction.outline_px":7,"text.roles.rea… | {"fill_color":"#FEE300","outline_px":7.0,"outline_color":"#040000","box_alpha":0.024,"sha… | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 5개: text.roles.reaction.color, text.roles.reaction.ou… |
| 자막 색·외곽선·그림자·박스 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.color":"#FFFFFF"} | {"fill_color":"#FFFFFF"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.roles.situation.color — 출력이 임시값과 같아도 레퍼런스와 같… |
| 자막 색·외곽선·그림자·박스 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.color":"#FFFFFF"} | {"fill_color":"#FFFFFF"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.roles.title.color — 출력이 임시값과 같아도 레퍼런스와 같다고 판… |

### 폰트

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 글꼴 [c_title·title] "빈 방에 들어온 사람들" (자막 1개·정지 프레임 1장, 참고) | 못 잼 | Noto Sans CJK KR Black | {"method":"정확 위치 재렌더","verdict":"identical","mae_planned":0.0,"noise_mae":0.0449,"mae_alt… | 같다 (참고; 판정은 caption.font:role_title) | 아니오 | t=0.12s [프레임](frames/cap_c_title_0000120.png) 참고 행(필수 아님): 한 crop 의 판정은 잡음이 커서 필수 판정은 역할 단위 합동 행 caption.font:role_… |
| 자막 글꼴 [c_desc·description] "설정 연결 검증 테스트 2편" (자막 1개·정지 프레임 … | 못 잼 | Noto Sans CJK KR Bold | {"method":"정확 위치 재렌더","verdict":"identical","mae_planned":0.0,"noise_mae":0.8283,"mae_alt… | 같다 (참고; 판정은 caption.font:role_description) | 아니오 | t=0.32s [프레임](frames/cap_c_desc_0000320.png) 참고 행(필수 아님): 한 crop 의 판정은 잡음이 커서 필수 판정은 역할 단위 합동 행 caption.font:role_… |
| 자막 글꼴 [c_sit1·situation] "한 사람이 빈 방을 가로질러 나간" (자막 1개·정지 프레임… | 못 잼 | Noto Sans CJK KR Black | {"method":"정확 위치 재렌더","verdict":"identical","mae_planned":0.0,"noise_mae":0.0273,"mae_alt… | 같다 (참고; 판정은 caption.font:role_situation) | 아니오 | t=0.54s [프레임](frames/cap_c_sit1_0000540.png) 참고 행(필수 아님): 한 crop 의 판정은 잡음이 커서 필수 판정은 역할 단위 합동 행 caption.font:role_… |
| 자막 글꼴 [c_sit2·situation] "한 남성이 카메라 앞까지 걸어온다" (자막 1개·정지 프레임… | 못 잼 | Noto Sans CJK KR Black | {"method":"정확 위치 재렌더","verdict":"identical","mae_planned":0.0,"noise_mae":0.3986,"mae_alt… | 같다 (참고; 판정은 caption.font:role_situation) | 아니오 | t=5.24s [프레임](frames/cap_c_sit2_0005240.png) 참고 행(필수 아님): 한 crop 의 판정은 잡음이 커서 필수 판정은 역할 단위 합동 행 caption.font:role_… |
| 자막 글꼴 [c_rx·reaction] "빤히" (자막 1개·정지 프레임 1장, 참고) | 못 잼 | Noto Sans CJK KR Black | {"method":"정확 위치 재렌더","verdict":"identical","mae_planned":0.0,"noise_mae":1.0453,"mae_alt… | 같다 (참고; 판정은 caption.font:role_reaction) | 아니오 | t=10.22s [프레임](frames/cap_c_rx_0010219.png) 참고 행(필수 아님): 한 crop 의 판정은 잡음이 커서 필수 판정은 역할 단위 합동 행 caption.font:role_… |
| 자막 글꼴 [c_sit3·situation] "두 사람이 나란히 와서 선다" (자막 1개·정지 프레임 1장… | 못 잼 | Noto Sans CJK KR Black | {"method":"정확 위치 재렌더","verdict":"identical","mae_planned":0.0,"noise_mae":0.2974,"mae_alt… | 같다 (참고; 판정은 caption.font:role_situation) | 아니오 | t=13.94s [프레임](frames/cap_c_sit3_0013939.png) 참고 행(필수 아님): 한 crop 의 판정은 잡음이 커서 필수 판정은 역할 단위 합동 행 caption.font:role_… |
| 자막 글꼴 [c_sit4·situation] "그리고 둘 다 떠난다" (자막 1개·정지 프레임 1장, 참고) | 못 잼 | Noto Sans CJK KR Black | {"method":"정확 위치 재렌더","verdict":"identical","mae_planned":0.0,"noise_mae":0.2677,"mae_alt… | 같다 (참고; 판정은 caption.font:role_situation) | 아니오 | t=18.94s [프레임](frames/cap_c_sit4_0018940.png) 참고 행(필수 아님): 한 crop 의 판정은 잡음이 커서 필수 판정은 역할 단위 합동 행 caption.font:role_… |
| 자막 글꼴 [description] (역할 단위: 자막 1개의 정지 프레임 합동) | 못 잼 | Noto Sans CJK KR Bold | {"verdict":"identical","verdict_ko":"동일","iou_expected_median":0.9506,"iou_stats":{"n":4,… | 같다 | 아니오 | t=0.33s 판정: 동일(identical) — 정확 위치 재렌더: 계획 글꼴이 출력을 재현(잡음 이내)하고 대안보다 잡음 이상 가까움 … |
| 자막 글꼴 [reaction] (역할 단위: 자막 1개의 정지 프레임 합동) | 못 잼 | Noto Sans CJK KR Black | {"verdict":"identical","verdict_ko":"동일","iou_expected_median":0.9759,"iou_stats":{"n":4,… | 같다 | 아니오 | t=10.23s 판정: 동일(identical) — 정확 위치 재렌더: 계획 글꼴이 출력을 재현(잡음 이내)하고 대안보다 잡음 이상 가까움 … |
| 자막 글꼴 [situation] (역할 단위: 자막 4개의 정지 프레임 합동) | 못 잼 | Noto Sans CJK KR Black | {"verdict":"identical","verdict_ko":"동일","iou_expected_median":0.967,"iou_stats":{"n":16,… | 같다 | 아니오 | t=0.57s 판정: 동일(identical) — 정확 위치 재렌더: 계획 글꼴이 출력을 재현(잡음 이내)하고 대안보다 잡음 이상 가까움 … |
| 자막 글꼴 [title] (역할 단위: 자막 1개의 정지 프레임 합동) | 못 잼 | Noto Sans CJK KR Black | {"verdict":"identical","verdict_ko":"동일","iou_expected_median":0.9855,"iou_stats":{"n":4,… | 같다 | 아니오 | t=0.13s 판정: 동일(identical) — 정확 위치 재렌더: 계획 글꼴이 출력을 재현(잡음 이내)하고 대안보다 잡음 이상 가까움 … |
| 자막 글꼴·굵기 [description] (레퍼런스 대비) | 못 잼 | {"text.roles.description.font_name":"Noto Sans CJK KR Bold","text.roles.description.bold"… | {"best":"Noto Sans CJK KR Bold","weight_class":700,"bold":true} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.description.font_name, text.roles.desc… |
| 자막 글꼴·굵기 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.font_name":"Noto Sans CJK KR Black","text.roles.reaction.bold":true} | {"best":"Noto Sans CJK KR Black","weight_class":900,"bold":true} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.reaction.font_name, text.roles.reactio… |
| 자막 글꼴·굵기 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.font_name":"Noto Sans CJK KR Black","text.roles.situation.bold":tr… | {"best":"Noto Sans CJK KR Black","weight_class":900,"bold":true} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.situation.font_name, text.roles.situat… |
| 자막 글꼴·굵기 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.font_name":"Noto Sans CJK KR Black","text.roles.title.bold":true} | {"best":"Noto Sans CJK KR Black","weight_class":900,"bold":true} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.title.font_name, text.roles.title.bold… |

### 자막 타이밍

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 등장·퇴장 시각 [c_title·title] "빈 방에 들어온 사람들" | — | {"start":0.0,"end":22.5} | {"onset":0.0,"offset":22.5} | 같다 | 아니오 | t=0.00s [프레임](frames/cap_c_title_0000120.png) |
| 자막 등장·퇴장 시각 [c_desc·description] "설정 연결 검증 테스트 2편" | — | {"start":0.0,"end":4.0} | {"onset":0.0,"offset":4.0} | 같다 | 아니오 | t=0.00s [프레임](frames/cap_c_desc_0000320.png) |
| 자막 등장·퇴장 시각 [c_sit1·situation] "한 사람이 빈 방을 가로질러 나간" | — | {"start":0.3,"end":4.8} | {"onset":0.2667,"offset":4.8} | 같다 | 아니오 | t=0.27s [프레임](frames/cap_c_sit1_0000540.png) |
| 자막 등장·퇴장 시각 [c_sit2·situation] "한 남성이 카메라 앞까지 걸어온다" | — | {"start":5.0,"end":9.8} | {"onset":4.9667,"offset":9.8} | 같다 | 아니오 | t=4.97s [프레임](frames/cap_c_sit2_0005240.png) |
| 자막 등장·퇴장 시각 [c_rx·reaction] "빤히" | — | {"start":10.0,"end":12.6} | {"onset":9.9667,"offset":12.6} | 같다 | 아니오 | t=9.97s [프레임](frames/cap_c_rx_0010219.png) |
| 자막 등장·퇴장 시각 [c_sit3·situation] "두 사람이 나란히 와서 선다" | — | {"start":13.7,"end":18.5} | {"onset":13.6667,"offset":18.5} | 같다 | 아니오 | t=13.67s [프레임](frames/cap_c_sit3_0013939.png) |
| 자막 등장·퇴장 시각 [c_sit4·situation] "그리고 둘 다 떠난다" | — | {"start":18.7,"end":22.3} | {"onset":18.6667,"offset":22.3} | 같다 | 아니오 | t=18.67s [프레임](frames/cap_c_sit4_0018940.png) |
| 자막 표시 시간 [description] (레퍼런스 대비) | 못 잼 | {"text.roles.description.timing.min_dur_s":1.0,"text.roles.description.persist":"timed"} | {"min_dur_s":4.0,"max_dur_s":4.0,"persist":"timed","first_onset":0.0,"last_offset":4.0,"d… | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.description.timing.min_dur_s, text.rol… |
| 자막 표시 시간 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.timing.min_dur_s":0.6,"text.roles.reaction.persist":"timed"} | {"min_dur_s":2.633,"max_dur_s":2.633,"persist":"timed","first_onset":9.967,"last_offset":… | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.reaction.timing.min_dur_s, text.roles.… |
| 자막 표시 시간 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.timing.min_dur_s":0.9,"text.roles.situation.persist":"timed"} | {"min_dur_s":3.633,"max_dur_s":4.833,"persist":"timed","first_onset":0.267,"last_offset":… | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.situation.timing.min_dur_s, text.roles… |
| 자막 표시 시간 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.persist":"whole_video"} | {"min_dur_s":22.5,"max_dur_s":22.5,"persist":"whole_video","first_onset":0.0,"last_offset… | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.roles.title.persist — 출력이 임시값과 같아도 레퍼런스와 같다고… |

### 자막 등장·퇴장 모션

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 등장 모션 [c_title·title] "빈 방에 들어온 사람들" | 못 잼 | {"type":"none","dur_s":0.0,"scale_from":1.0} | {"type":"none","note":"첫 프레임부터 완전히 표시(등장 모션 없음)","dur_s_compared":null} | 같다 | 아니오 | t=0.00s [프레임](frames/cap_c_title_0000120.png) |
| 자막 등장 모션 [c_desc·description] "설정 연결 검증 테스트 2편" | 못 잼 | {"type":"fade","dur_s":0.2,"scale_from":1.0} | {"type":"fade","scale_first":null,"presence_first":0.166,"dur_s":0.133,"scales":[null,nul… | 같다 | 아니오 | t=0.00s [프레임](frames/cap_c_desc_0000320.png) |
| 자막 퇴장 모션 [c_desc·description] "설정 연결 검증 테스트 2편" | 못 잼 | {"type":"none","dur_s":0.0} | {"type":"none","dur_s":0.0,"expected":"none","fade_dur_s":0.033,"dur_s_compared":null} | 같다 | 아니오 | t=4.00s |
| 자막 등장 모션 [c_sit1·situation] "한 사람이 빈 방을 가로질러 나간" | 못 잼 | {"type":"pop","dur_s":0.12,"scale_from":0.85} | {"type":"pop","scale_first":0.852,"presence_first":0.473,"dur_s":0.133,"scales":[0.852,0.… | 같다 | 아니오 | t=0.27s [프레임](frames/cap_c_sit1_0000540.png) |
| 자막 퇴장 모션 [c_sit1·situation] "한 사람이 빈 방을 가로질러 나간" | 못 잼 | {"type":"none","dur_s":0.0} | {"type":"none","dur_s":0.0,"expected":"none","fade_dur_s":0.033,"dur_s_compared":null} | 같다 | 아니오 | t=4.80s |
| 자막 등장 모션 [c_sit2·situation] "한 남성이 카메라 앞까지 걸어온다" | 못 잼 | {"type":"pop","dur_s":0.12,"scale_from":0.85} | {"type":"pop","scale_first":0.852,"presence_first":0.516,"dur_s":0.133,"scales":[0.852,0.… | 같다 | 아니오 | t=4.97s [프레임](frames/cap_c_sit2_0005240.png) |
| 자막 퇴장 모션 [c_sit2·situation] "한 남성이 카메라 앞까지 걸어온다" | 못 잼 | {"type":"none","dur_s":0.0} | {"type":"none","dur_s":0.0,"expected":"none","fade_dur_s":0.033,"dur_s_compared":null} | 같다 | 아니오 | t=9.80s |
| 자막 등장 모션 [c_rx·reaction] "빤히" | 못 잼 | {"type":"pop","dur_s":0.1,"scale_from":1.35} | {"type":"pop","scale_first":1.37,"presence_first":0.815,"dur_s":0.1,"scales":[1.37,1.244,… | 같다 | 아니오 | t=9.97s [프레임](frames/cap_c_rx_0010219.png) |
| 자막 퇴장 모션 [c_rx·reaction] "빤히" | 못 잼 | {"type":"none","dur_s":0.0} | {"type":"none","dur_s":0.0,"expected":"none","fade_dur_s":0.033,"dur_s_compared":null} | 같다 | 아니오 | t=12.60s |
| 자막 등장 모션 [c_sit3·situation] "두 사람이 나란히 와서 선다" | 못 잼 | {"type":"pop","dur_s":0.12,"scale_from":0.85} | {"type":"pop","scale_first":0.852,"presence_first":0.477,"dur_s":0.133,"scales":[0.852,0.… | 같다 | 아니오 | t=13.67s [프레임](frames/cap_c_sit3_0013939.png) |
| 자막 퇴장 모션 [c_sit3·situation] "두 사람이 나란히 와서 선다" | 못 잼 | {"type":"none","dur_s":0.0} | {"type":"none","dur_s":0.0,"expected":"none","fade_dur_s":0.033,"dur_s_compared":null} | 같다 | 아니오 | t=18.50s |
| 자막 등장 모션 [c_sit4·situation] "그리고 둘 다 떠난다" | 못 잼 | {"type":"pop","dur_s":0.12,"scale_from":0.85} | {"type":"pop","scale_first":0.851,"presence_first":0.553,"dur_s":0.1,"scales":[0.851,0.89… | 같다 | 아니오 | t=18.67s [프레임](frames/cap_c_sit4_0018940.png) |
| 자막 퇴장 모션 [c_sit4·situation] "그리고 둘 다 떠난다" | 못 잼 | {"type":"none","dur_s":0.0} | {"type":"none","dur_s":0.0,"expected":"none","fade_dur_s":0.033,"dur_s_compared":null} | 같다 | 아니오 | t=22.30s |
| 자막 등장·퇴장 모션 [description] (레퍼런스 대비) | 못 잼 | {"text.roles.description.motion_in.type":"fade","text.roles.description.motion_in.dur_s":… | {"in_type":"fade","in_dur_s":0.2,"out_type":"none"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: text.roles.description.motion_in.type, text.roles… |
| 자막 등장·퇴장 모션 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.motion_in.type":"pop","text.roles.reaction.motion_in.dur_s":0.1,"te… | {"in_type":"pop","in_dur_s":0.1,"in_scale_first":1.37,"out_type":"none"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: text.roles.reaction.motion_in.type, text.roles.re… |
| 자막 등장·퇴장 모션 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.motion_in.type":"pop","text.roles.situation.motion_in.dur_s":0.12,… | {"in_type":"pop","in_dur_s":0.133,"in_scale_first":0.852,"out_type":"none"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: text.roles.situation.motion_in.type, text.roles.s… |
| 자막 등장·퇴장 모션 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.motion_in.type":"none"} | {"in_type":"none"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: text.roles.title.motion_in.type — 출력이 임시값과 같아도 레퍼… |

### 컷

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 컷 위치 [s2 시작] | — | {"t":4.8} | {"t":4.8,"type":"cut"} | 같다 | 아니오 | t=4.80s |
| 컷 위치 [s3 시작 — 같은 장면 이어짐] | — | {"t":9.8,"visible_change":false,"continuous":true} | {"t":null,"type":"none","score":0.5} | 같다 | 아니오 | t=9.80s 계획상 같은 장면이 이어지는 편집점 — 화면 변화가 없어야 맞음 |
| 컷 위치 [s4 시작] | — | {"t":13.5} | {"t":13.4667,"type":"flash"} | 같다 | 아니오 | t=13.47s |
| 컷 위치 [s5 시작] | — | {"t":18.5} | {"t":18.5,"type":"cut"} | 같다 | 아니오 | t=18.50s |
| 계획에 없는 컷·플래시 | — | [] | [] | 같다 | 아니오 | — |
| 소스 구간 [s1] | — | {"src_in":2.0,"src_out":6.8,"source":"assets/test/generated/video/people-detection.mp4"} | {"offset_s":-0.05,"samples":[{"t":1.0,"expected_src_t":3.0,"matched_src_t":3.0,"ncc":0.98… | 같다 | 아니오 | t=1.00s |
| 소스 구간 [s2] | — | {"src_in":5.0,"src_out":10.0,"source":"assets/test/generated/video/face-demographics-walk… | {"offset_s":-0.04,"samples":[{"t":5.84,"expected_src_t":6.04,"matched_src_t":6.0,"ncc":0.… | 같다 | 아니오 | t=5.84s |
| 소스 구간 [s3] | — | {"src_in":10.0,"src_out":13.0,"source":"assets/test/generated/video/face-demographics-wal… | {"mode":"still_match","ncc_planned_min":0.9945,"ncc_planned":[0.9955,0.9946,0.996,0.9968,… | 같다 | 아니오 | t=10.05s 정지 장면: 계획 구간과 시각적으로 동일 (시점 특정 불가) |
| 소스 구간 [s4] | — | {"src_in":32.0,"src_out":37.0,"source":"assets/test/generated/video/face-demographics-wal… | {"offset_s":-0.056,"samples":[{"t":14.636,"expected_src_t":33.136,"matched_src_t":33.083,… | 같다 | 아니오 | t=14.64s |
| 소스 구간 [s5] | — | {"src_in":42.0,"src_out":44.0,"source":"assets/test/generated/video/face-demographics-wal… | {"offset_s":-0.037,"samples":[{"t":19.34,"expected_src_t":42.42,"matched_src_t":42.417,"n… | 같다 | 아니오 | t=19.34s |
| 같은 원본 장면 반복(표시 없는 다시보기) 0 | — | {"unmarked_repeats":0,"min_overlap_s":0.05} | {"repeats":[],"not_measured":[]} | 같다 | 아니오 | 출력에서 잰 클립별 소스 구간이 서로 겹치지 않음 |
| 컷 밀도: 10초당 전환 수 (레퍼런스 포맷 분포 대비) | 못 잼 | {"structure.cuts_per_10s.p10":null,"structure.cuts_per_10s.p50":null,"structure.cuts_per_… | {"cuts_per_10s":1.333,"n_cuts":3,"duration":22.5,"types":["cut","flash"]} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: structure.cuts_per_10s.p10, structure.cuts_per_10… |
| 샷 길이 중앙값 (레퍼런스 포맷 분포 대비) | 못 잼 | {"structure.shot_len_s.p10":null,"structure.shot_len_s.p50":null,"structure.shot_len_s.p9… | {"shot_len_median_s":4.917,"shots_s":[4.8,8.667,5.033,4.0]} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: structure.shot_len_s.p10, structure.shot_len_s.p5… |

### 모션(확대·정지·전환)

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 전환 종류·길이 [s2] | 못 잼 | {"type":"cut","dur":0.0} | {"type":"cut","dur":0.0,"score":48.27} | 같다 | 아니오 | t=4.80s |
| 전환 종류·길이 [s3] | 못 잼 | {"type":"cut","dur":0.0,"visible":"none"} | {"type":"none","dur":null,"score":0.5} | 같다 | 아니오 | t=9.80s 같은 장면이 이어지는 편집점: 보이는 전환이 없어야 맞음(계획 cut = 이어 붙이기) |
| 전환 종류·길이 [s4] | 못 잼 | {"type":"flash","dur":0.12,"color":"#FFFFFF","scope":"region"} | {"type":"flash","dur":0.1,"score":122.6,"color":"#FDFDFD","scope":"region","scope_measure… | 같다 | 아니오 | t=13.47s 플래시 최대 밝기 시 영상 영역 평균색 #FDFDFD (기대 #FFFFFF, 거리 ≤ 45); 플래시 범위 region (기… |
| 전환 종류·길이 [s5] | 못 잼 | {"type":"cut","dur":0.0} | {"type":"cut","dur":0.0,"score":10.49} | 같다 | 아니오 | t=18.50s |
| 재생 속도 [s5] | 못 잼 | 0.5 | {"speed":0.499,"samples":11,"quantisation_frac":0.0476} | 같다 | 아니오 | — |
| 줌 없음 확인 [s1] | — | {"final_ratio":1.0} | {"max_dev":0.0003,"final_ratio":1.0,"source_ratio":0.9999,"corrected":1.0001,"median_inli… | 같다 (참고) | 아니오 | 소스 자체의 카메라 줌도 여기에 잡힘 |
| 줌 없음 확인 [s2] | — | {"final_ratio":1.0} | {"max_dev":0.2707,"final_ratio":1.2605,"source_ratio":1.0,"corrected":1.2605,"median_inli… | 같다 (참고) | 아니오 | 특징점 배율 곡선은 0.27 움직였지만, 출력 프레임이 계획 기하(줌 없음)로 놓은 소스 프레임과 같음 (NCC 중앙 0.9… |
| 줌 없음 확인 [s3] | — | {"final_ratio":1.0} | {"max_dev":0.0034,"final_ratio":0.9988,"source_ratio":0.9989,"corrected":0.9999,"median_i… | 같다 (참고) | 아니오 | 소스 자체의 카메라 줌도 여기에 잡힘 |
| 줌 없음 확인 [s4] | — | {"final_ratio":1.0} | {"max_dev":0.7453,"final_ratio":1.1449,"source_ratio":0.9988,"corrected":1.1462,"median_i… | 같다 (참고) | 아니오 | 특징점 배율 곡선은 0.75 움직였지만, 출력 프레임이 계획 기하(줌 없음)로 놓은 소스 프레임과 같음 (NCC 중앙 0.9… |
| 줌 없음 확인 [s5] | — | {"final_ratio":1.0} | {"max_dev":0.1897,"final_ratio":1.1884,"source_ratio":1.0003,"corrected":1.188,"median_in… | 같다 (참고) | 아니오 | 특징점 배율 곡선은 0.19 움직였지만, 출력 프레임이 계획 기하(줌 없음)로 놓은 소스 프레임과 같음 (NCC 중앙 0.9… |
| 연속 세그먼트 줌 횟수(같은 효과 쌓기 금지) | 못 잼 | {"max":1} | {"measured":0} | 같다 | 아니오 | — |
| 줌 배율·길이·가속 곡선·고정점 규칙 (레퍼런스 대비) | 못 잼 | {"motion.zoom.scale_to":1.25} | — | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: motion.zoom.scale_to — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하… |
| 정지(프리즈) [s3] | 못 잼 | {"start":10.8,"hold":0.7} | {"presence":"present","start":10.8,"hold":0.7,"mean_diff":0.0182} | 같다 | 아니오 | t=10.80s |
| 계획에 없는 정지 화면 | — | [] | [] | 같다 | 아니오 | 소스도 정지해 있으면 제외; 판단 불가(소스 없음)면 포함 |
| 영상당 정지 횟수 | 못 잼 | {"max":2} | {"count":1} | 같다 | 아니오 | — |
| 정지 길이 (레퍼런스 대비) | 못 잼 | {"motion.freeze.hold_s":0.7} | {"hold_s":0.7} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: motion.freeze.hold_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하… |
| 전환 종류·길이·플래시 색·범위 (레퍼런스 대비) | 못 잼 | {"motion.transitions.default":"cut","motion.transitions.flash.dur_s":0.12,"motion.transit… | {"mode":"cut","flash_dur":0.1,"flash_color":"#FDFDFD","flash_scope":"region"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: motion.transitions.default, motion.transitions.fl… |
| 느린 재생 배율 (레퍼런스 대비) | 못 잼 | {"motion.speed.slowmo_factor":0.5} | {"slowmo":0.499} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: motion.speed.slowmo_factor — 출력이 임시값과 같아도 레퍼런스와 같… |
| 확대(줌) 있다/없다 (레퍼런스 대비) | 못 잼 | {"presence.zoom":"unmeasured"} | {"presence":"absent","basis":"모든 클립에서 배율 변화 없음(출력 측정)","reference_share":null} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: presence.zoom — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레… |
| 정지 있다/없다 (레퍼런스 대비) | 못 잼 | {"presence.freeze":"unmeasured"} | {"presence":"present","basis":"출력의 반복 프레임 구간 1개","reference_share":null} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: presence.freeze — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.… |
| 속도 변화 있다/없다 (레퍼런스 대비) | 못 잼 | {"presence.speed_change":"unmeasured"} | {"presence":"present","basis":"출력에서 잰 재생 속도 ≠ 1: s5","reference_share":null} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: presence.speed_change — 출력이 임시값과 같아도 레퍼런스와 같다고 판정… |
| 플래시 전환 있다/없다 (레퍼런스 대비) | 못 잼 | {"presence.flash":"unmeasured"} | {"presence":"present","basis":"출력에서 잰 flash 1개","reference_share":null} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: presence.flash — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. … |
| 크로스페이드 있다/없다 (레퍼런스 대비) | 못 잼 | {"presence.crossfade":"unmeasured"} | {"presence":"absent","basis":"출력 전체에서 crossfade 없음(프레임 차이·밝기 검사)","reference_share":null} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: presence.crossfade — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 … |

### 움직이는 장식(위치/밝기 각각)

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 장식 위치·이동 경로 [d_circle·circle] | — | {"keyframes":[{"t":8.5,"x":533.0,"y":895.0,"w":290,"h":340,"rotation":null}],"anchor":"화살… | {"abs_err_p50":1.0,"abs_err_p90":1.0,"path_err_p90":0.0,"size":[288.0,338.0],"color":"#FD… | 같다 | 아니오 | t=8.53s 위치는 밝기와 별도로 판정(보이는 프레임만) |
| 장식 밝기·깜빡임 [d_circle·circle] | 못 잼 | {"blink_hz":0.0,"start":8.5,"end":11.5} | {"blink_hz":0.0,"on_fraction":1.0,"on_events":1,"curve_sample":[[8.533,0.998],[8.567,0.99… | 같다 | 아니오 | t=8.50s 밝기 곡선은 위치와 별도로 판정 |
| 장식 색·선 두께·크기 [d_circle·circle] | 못 잼 | {"color":"#FF2A2A","stroke_px":10} | {"color":"#FD2828","stroke_px":9.3} | 같다 | 아니오 | t=8.50s |
| 장식 스타일 [circle] (레퍼런스 대비) | 못 잼 | {"decorations.circle.color":"#FF2A2A","decorations.circle.stroke_px":10,"decorations.circ… | {"color":"#FD2828","stroke_px":9.3,"blink_hz":0.0,"on_fraction":1.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: decorations.circle.color, decorations.circle.stro… |
| 장식 위치·이동 경로 [d_box·box] | — | {"keyframes":[{"t":16.5,"x":183.0,"y":959.0,"w":252,"h":280,"rotation":null}],"anchor":"화… | {"abs_err_p50":1.0,"abs_err_p90":1.0,"path_err_p90":0.0,"size":[252.0,278.0],"color":"#FC… | 같다 | 아니오 | t=16.53s 위치는 밝기와 별도로 판정(보이는 프레임만) |
| 장식 밝기·깜빡임 [d_box·box] | 못 잼 | {"blink_hz":0.0,"start":16.5,"end":18.5} | {"blink_hz":0.0,"on_fraction":1.0,"on_events":1,"curve_sample":[[16.533,0.986],[16.567,0.… | 같다 | 아니오 | t=16.50s 밝기 곡선은 위치와 별도로 판정 |
| 장식 색·선 두께·크기 [d_box·box] | 못 잼 | {"color":"#FF2A2A","stroke_px":8} | {"color":"#FC2725","stroke_px":7.6} | 같다 | 아니오 | t=16.50s |
| 장식 스타일 [box] (레퍼런스 대비) | 못 잼 | {"decorations.box.color":"#FF2A2A","decorations.box.stroke_px":8,"decorations.box.blink_h… | {"color":"#FC2725","stroke_px":7.6,"blink_hz":0.0,"on_fraction":1.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: decorations.box.color, decorations.box.stroke_px,… |
| 움직이는 장식 있다/없다 (레퍼런스 대비) | 못 잼 | {"presence.decorations":"unmeasured"} | {"presence":"present","basis":"출력에서 잰 장식 d_circle, d_box","reference_share":null} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: presence.decorations — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하… |

### 식별 요소

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 레퍼런스 채널명·식별 문구 없음 | {"identity_exclusions.forbidden_text":"해당 없음(rule… | {"absent":["조슈아매거진","조슈아 매거진","joshuamagazine","joshua magazine","JOSHUA MAGAZINE"]} | {"hits":[],"frames_ocr":26} | 같다 | 아니오 | 1초 간격 전체 프레임 + 각 클립 중간 OCR |
| 레퍼런스 로고 템플릿 없음 | {"identity_exclusions.logo_templates_dir":"해당 없음(… | {"templates_dir":"presets/joshuamagazine/reference/identity_templates","manifest":"preset… | {"manifest":{"file":"presets/joshuamagazine/reference/identity_templates/manifest.json","… | 못 잼 (참고) | 아니오 | 식별 템플릿 기록이 완전하지 않음(상태 unmeasured): 레퍼런스 목록 수집 차단(2026-09-24T17:56:07+… |
| 레퍼런스와 같은 녹화(영상) 재사용 없음 | — | {"same_recording_as_reference":false} | {"excluded":null,"matched_ref_video_id":null,"distance":null,"matched_keyframes":0,"n_key… | 못 잼 (참고) | 아니오 | 레퍼런스 영상 지문(exclusions.jsonl reference_footage) 없음 → 같은 녹화 여부 못 잼 (URL… |

### 로고 잔류

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 모서리·하단 잔여 글자(출처 표기·워터마크·원어 자막) | — | [] | {"persistent":[],"single_hits":[{"zone":"video_bottom","clip_id":"s3","text":"ae","times"… | 같다 | 아니오 | 한 번만 잡힌 글자는 장면 속 글자/OCR 잡음일 수 있어 참고로만 표시 |
| 원본 오버레이 검출 기록 [v_room] | — | {"record":"warehouse/overlays/<sha256>.json","sha256":"18ffe8672d741e3e29c9d891d22c59d453… | — | 못 잼 (참고) | 아니오 | 출처 기록 없음(warehouse/overlays/18ffe8672d74….json) — `python -m shortkit… |
| 원본 오버레이 검출 기록 [v_face] | — | {"record":"warehouse/overlays/<sha256>.json","sha256":"d88ab9aa03634f66f8815db3dc940e1cdd… | — | 못 잼 (참고) | 아니오 | 출처 기록 없음(warehouse/overlays/d88ab9aa0363….json) — `python -m shortkit… |

### 얼굴·손·물체 가림

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 보호 영역 가림·잘림 [걸어가는 사람(들어옴)·s1] | — | {"rect":[337.3,850.2,222.4,413.8],"resolution":[1080,1920],"t":[0.0,0.6],"covered":false,… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=0.00s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [걸어가는 사람(가운데)·s1] | — | {"rect":[407.7,774.2,259.0,391.3],"resolution":[1080,1920],"t":[0.5,1.6],"covered":false,… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=0.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [걸어가는 사람(오른쪽으로)·s1] | — | {"rect":[562.5,761.6,287.1,301.2],"resolution":[1080,1920],"t":[1.5,2.6],"covered":false,… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=1.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [걸어가는 사람(오른쪽 벽 앞)·s1] | — | {"rect":[725.8,763.0,273.0,250.5],"resolution":[1080,1920],"t":[2.5,3.6],"covered":false,… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=2.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [걸어가는 사람(나가는 중)·s1] | — | {"rect":[860.9,779.9,219.1,219.6],"resolution":[1080,1920],"t":[3.5,4.8],"covered":false,… | {"hits":[],"visible_frac":0.998} | 같다 | 아니오 | t=3.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [남성 얼굴(걸어옴)·s2] | — | {"rect":[464.0,853.0,154.8,126.7],"resolution":[1080,1920],"t":[4.8,6.2],"covered":false,… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=4.80s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [남성 얼굴(가까이 옴)·s2] | — | {"rect":[447.1,822.1,152.0,171.7],"resolution":[1080,1920],"t":[6.1,7.5],"covered":false,… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=6.10s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [남성 얼굴(정면으로 섬)·s2] | — | {"rect":[447.1,789.7,171.7,211.1],"resolution":[1080,1920],"t":[7.4,9.8],"covered":false,… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=7.40s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [남성 얼굴(정면으로 섬)·s3] | — | {"rect":[447.1,789.7,171.7,211.1],"resolution":[1080,1920],"t":[9.8,12.8],"covered":false… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=9.80s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [왼쪽 여성 얼굴(걸어 들어옴)·s4] | — | {"rect":[157.2,867.1,219.6,168.9],"resolution":[1080,1920],"t":[13.5,14.6],"covered":fals… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=13.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [왼쪽 여성 얼굴(다가옴)·s4] | — | {"rect":[89.6,850.2,211.1,213.9],"resolution":[1080,1920],"t":[14.5,16.3],"covered":false… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=14.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [왼쪽 여성 얼굴(섬)·s4] | — | {"rect":[77.0,839.0,211.1,239.3],"resolution":[1080,1920],"t":[16.2,18.5],"covered":false… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=16.20s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [오른쪽 남성 얼굴(걸어 들어옴)·s4] | — | {"rect":[576.6,768.6,166.1,183.0],"resolution":[1080,1920],"t":[13.5,14.6],"covered":fals… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=13.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [오른쪽 남성 얼굴(다가옴)·s4] | — | {"rect":[604.7,709.5,197.0,242.1],"resolution":[1080,1920],"t":[14.5,16.3],"covered":fals… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=14.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [오른쪽 남성 얼굴(섬)·s4] | — | {"rect":[618.8,712.3,168.9,232.2],"resolution":[1080,1920],"t":[16.2,18.5],"covered":fals… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=16.20s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [왼쪽 여성 얼굴(섬)·s5] | — | {"rect":[77.0,839.0,211.1,239.3],"resolution":[1080,1920],"t":[18.5,18.9],"covered":false… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=18.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [오른쪽 남성 얼굴(섬)·s5] | — | {"rect":[618.8,712.3,168.9,232.2],"resolution":[1080,1920],"t":[18.5,18.9],"covered":fals… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=18.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 얼굴 가림(얼굴 검출) | — | {"covered":0} | {"detector":"shortkit.clean.faces haar frontal+profile (shortkit.HaarCascade(numpy))","fr… | 같다 | 아니오 | 얼굴: 출력 프레임 + 같은 순간의 소스 프레임(자막이 덮은 얼굴은 출력에서 안 보임)을 캔버스 좌표로 옮겨 검출; 자막 상… |

### 음악 구간

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| BGM 은 깨끗한 음원(레퍼런스에서 분리한 스템 금지) | — | {"clean_music_file":true,"not_a_copy_of":"presets/*/analysis/*/stems/*, reference media"} | {"path":"assets/test/generated/music_bed_b.wav","reference_stems_compared":0,"reference_h… | 못 잼 (참고) | 아니오 | 레퍼런스 분리 음원 파일(presets/*/analysis/*/stems)이 하나도 없어 파형 대조 대상이 없음 — `ref… |
| BGM 곡·버전 일치(파형 대조) | 못 잼 | {"path":"assets/test/generated/music_bed_b.wav","track_id":null} | {"presence":"present","waveform_ncc":0.9803,"local_match":{"n":90,"q95":0.9999,"q70":0.99… | 같다 | 아니오 | 출력 믹스에서 계획한 음악 파일의 파형을 찾음 ／ is_match 4요소: 곡=같다, 버전=같다, 속도=같다, 구간=같다 |
| BGM 일치(곡 AND 버전 AND 속도 AND 구간, audio_bgm.is_match) | 못 잼 | {"track_id":"assets/test/generated/music_bed_b.wav","version":"file:assets/test/generated… | {"observed":{"track_id":"assets/test/generated/music_bed_b.wav","version":"file:assets/te… | 같다 | 아니오 | t=0.00s 곡=같다, 버전=같다, 속도=같다, 구간=같다 — 계획한 음원 파일의 파형이 출력에서 확인됨(같은 녹음 → 곡·버전 같음) |
| BGM 속도(버전) | 못 잼 | 1.0 | 1.0 | 같다 | 아니오 | 후보 템포 상위: [[1.0, 0.9356], [0.995, 0.2539], [1.005, 0.251], [0.99, 0.1… |
| BGM 사용 구간 | 못 잼 | {"section_start_s":0.0} | {"section_start_s":0.0,"used_section":[0.025,22.465],"runner_up":{"section_start_s":20.0,… | 같다 | 아니오 | t=0.00s 파형이 거의 똑같이 반복되는 곡이라 다른 위치도 같은 소리(상관 차 ≤ 0.005) — 구간 구별 한계 |
| BGM 페이드 인/아웃 | 못 잼 | {"fade_in_s":0.0,"fade_out_s":0.8} | {"fade_in_s":0.0,"fade_out_s":0.683,"audible_span":[0.025,22.465]} | 같다 (참고) | 아니오 | 0.05초 창 LS 이득 곡선에서 측정 |
| BGM 곡·버전·속도·구간 (레퍼런스 대비) | 못 잼 | {"audio.bgm.track_id":null,"audio.bgm.title":null,"audio.bgm.version":null,"audio.bgm.tem… | {"track_id":null,"title":null,"version":null,"tempo_ratio":1.0,"section_start_s":0.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 5개: audio.bgm.track_id, audio.bgm.title, audio.bgm.ve… |
| 보존 대사 구간의 BGM 덕킹 | — | {"duck_ranges":[],"depth_db":10.0} | {"ducked_ranges":[[22.04,22.49]],"coverage":[]} | 같다 (참고) | 아니오 | 계획의 덕킹 구간이 출력에 있는지(깊이는 depth 행) |
| 보존 대사 밖에서 BGM 낮춤 없음(효과음·컷 때문에 덕킹 금지) | {"audio.ducking.only_under_kept_dialogue":"해당 없음(… | {"ducking_only_in":[]} | {"ducking_outside":[]} | 같다 | 아니오 | — |
| 덕킹은 출력에서 잰 말소리 밑에서만 | {"audio.ducking.only_under_kept_dialogue":"해당 없음(… | {"planned_speech_out":[],"max_without_speech_s":0.25} | {"ducks":[],"speech_out":[],"speech_status":"measured"} | 같다 | 아니오 | 출력에서 잰 덕킹 없음(시작·끝 페이드·의도적 정적 제외) |
| 덕킹은 원음이 실제로 들리는 곳에서만 | — | 덕킹 구간 ⊆ 원음 존재 구간 | {"ducks_without_original":[],"original_present":[]} | 같다 | 아니오 | — |
| 계획에 없는 BGM 끊김 | — | [] | [] | 같다 | 아니오 | — |
| BGM 크기(최종 프로그램 음량 기준) | 못 잼 | {"gain_db":0.0,"definition":"깨끗한 음원 대비 dB, 최종 프로그램 음량에서"} | {"level_db":0.63,"ls_gain_db":-0.07,"mix_lufs":-14.7,"target_lufs":-14.0} | 같다 | 아니오 | t=0.00s 깨끗한 음원 LS 이득(0.25 s 창 이득의 p90 = BGM 기준 레벨, dB) + 목표 LUFS − 출력 통합 LUFS… |
| BGM 크기 (레퍼런스 대비) | 못 잼 | {"audio.bgm.gain_db":0.0} | {"level_db":0.63} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: audio.bgm.gain_db — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않… |
| BGM 있다/없다 (레퍼런스 대비) | 못 잼 | {"presence.bgm":"unmeasured"} | {"presence":"present","basis":"계획한 음원 파형을 출력에서 찾음","reference_share":null} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: presence.bgm — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼… |
| 덕킹 있다/없다 (레퍼런스 대비) | 못 잼 | {"presence.ducking":"unmeasured"} | {"presence":"present","basis":"출력에서 잰 BGM 낮춤 1구간","reference_share":null} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: presence.ducking — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음… |
| 의도적 정적 있다/없다 (레퍼런스 대비) | 못 잼 | {"presence.intentional_silence":"unmeasured"} | {"presence":"absent","basis":"BGM 이득 곡선에 끊김 없음(시작·끝 페이드 제외)","reference_share":null} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: presence.intentional_silence — 출력이 임시값과 같아도 레퍼런스와… |

### 원음

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 원음 OFF 구간에 원음 없음(기본 OFF) | {"audio.original.default":"해당 없음(rule)"} | {"kept_only":[]} | {"presence_outside_kept":"absent","leak_windows":[],"sources_without_audio":[]} | 같다 | 아니오 | — |
| 보존 원음 크기 (레퍼런스 대비) | 못 잼 | {"audio.original.keep_gain_db":0.0} | — | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: audio.original.keep_gain_db — 출력이 임시값과 같아도 레퍼런스와 … |
| 원음 있다/없다 (레퍼런스 대비) | 못 잼 | {"presence.original_audio":"unmeasured"} | {"presence":"unmeasured","basis":"원음 창을 재지 못함","reference_share":null} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: presence.original_audio — 출력이 임시값과 같아도 레퍼런스와 같다고 … |

### 효과음 종류별 개수

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 효과음 [fx1·whoosh] 위치 | — | {"t":4.55,"type":"whoosh"} | {"t":4.5522,"ncc":0.912} | 같다 | 아니오 | t=4.55s |
| 효과음 [fx1·whoosh] 크기 | 못 잼 | {"gain_db":-8.0} | {"gain_db_mix_scale":-8.99,"reference":"local_bgm"} | 같다 (참고) | 아니오 | t=4.55s |
| 효과음 [fx2·click] 위치 | — | {"t":10.8,"type":"click"} | {"t":10.8,"ncc":0.991} | 같다 | 아니오 | t=10.80s |
| 효과음 [fx2·click] 크기 | 못 잼 | {"gain_db":-8.0} | {"gain_db_mix_scale":-8.11,"reference":"local_bgm"} | 같다 (참고) | 아니오 | t=10.80s |
| 효과음 [fx3·ding] 위치 | — | {"t":16.3,"type":"ding"} | {"t":16.3,"ncc":0.999} | 같다 | 아니오 | t=16.30s |
| 효과음 [fx3·ding] 크기 | 못 잼 | {"gain_db":-8.0} | {"gain_db_mix_scale":-8.01,"reference":"local_bgm"} | 같다 (참고) | 아니오 | t=16.30s |
| 효과음 개수 [click] (계획 대비) | — | 1 | 1 | 같다 | 아니오 | t=10.80s |
| 효과음 개수 [ding] (계획 대비) | — | 1 | 1 | 같다 | 아니오 | t=16.30s |
| 효과음 개수 [whoosh] (계획 대비) | — | 1 | 1 | 같다 | 아니오 | t=4.55s |
| 효과음 [fx1] 종류 = 소리 지문(카탈로그 대비) | 못 잼 | {"type":"whoosh"} | {"catalog_type":null,"status":"unmeasured","type_id":null,"reason":"효과음 카탈로그 미측정(상태 unmea… | 못 잼 (참고) | 아니오 | t=4.55s 소리 지문으로 종류를 정하지 못함: 효과음 카탈로그 미측정(상태 unmeasured: 2026-09-24: 레퍼런스 최신 5… |
| 효과음 [fx2] 종류 = 소리 지문(카탈로그 대비) | 못 잼 | {"type":"click"} | {"catalog_type":null,"status":"unmeasured","type_id":null,"reason":"효과음 카탈로그 미측정(상태 unmea… | 못 잼 (참고) | 아니오 | t=10.80s 소리 지문으로 종류를 정하지 못함: 효과음 카탈로그 미측정(상태 unmeasured: 2026-09-24: 레퍼런스 최신 5… |
| 효과음 [fx3] 종류 = 소리 지문(카탈로그 대비) | 못 잼 | {"type":"ding"} | {"catalog_type":null,"status":"unmeasured","type_id":null,"reason":"효과음 카탈로그 미측정(상태 unmea… | 못 잼 (참고) | 아니오 | t=16.30s 소리 지문으로 종류를 정하지 못함: 효과음 카탈로그 미측정(상태 unmeasured: 2026-09-24: 레퍼런스 최신 5… |
| 효과음 종류별 개수 (레퍼런스 포맷 범위 대비) | 못 잼 | 레퍼런스 카탈로그의 포맷별 관측 범위 | {"종류 못 정함":3} | 못 잼 (참고) | 아니오 | sfx_catalog.json 미측정: 2026-09-24: 레퍼런스 최신 50편 다운로드 불가(youtube 차단), De… |
| 효과음 크기 (레퍼런스 대비) | 못 잼 | {"audio.sfx.gain_db_default":-8.0} | {"gain_db":-8.11} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: audio.sfx.gain_db_default — 출력이 임시값과 같아도 레퍼런스와 같다… |

### 사건과의 시차

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 효과음 [fx1] 사건과의 시차 (걷던 사람이 오른쪽 화면 밖으로 나감) | {"audio.sfx.max_event_offset_s":"해당 없음(rule)"} | {"event_t":4.6,"max_abs_offset":0.3} | {"sfx_t":4.5522,"offset":-0.048} | 같다 | 아니오 | t=4.55s 사건 시각은 plan 의 선언(화면 사건), 효과음 시각은 출력에서 측정 |
| 효과음 [fx2] 사건과의 시차 (정면을 보고 선 순간 화면이 멈춤) | {"audio.sfx.max_event_offset_s":"해당 없음(rule)"} | {"event_t":10.8,"max_abs_offset":0.3} | {"sfx_t":10.8,"offset":0.0} | 같다 | 아니오 | t=10.80s 사건 시각은 plan 의 선언(화면 사건), 효과음 시각은 출력에서 측정 |
| 효과음 [fx3] 사건과의 시차 (걸어 들어온 두 사람이 나란히 멈춰 ) | {"audio.sfx.max_event_offset_s":"해당 없음(rule)"} | {"event_t":16.3,"max_abs_offset":0.3} | {"sfx_t":16.3,"offset":0.0} | 같다 | 아니오 | t=16.30s 사건 시각은 plan 의 선언(화면 사건), 효과음 시각은 출력에서 측정 |

### 사건 없는 효과음 0

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 컷 위에 놓인 효과음(사건 없이 컷 때문인지) | — | {"on_cut_without_evidence":0} | {"on_cut":[],"cuts_measured":3} | 같다 (참고) | 아니오 | 컷 위 효과음 없음 |
| 사건 없는 효과음 0 | {"audio.sfx.require_event":"해당 없음(rule)"} | 0 | {"count":0,"items":[]} | 같다 | 아니오 | — |
| 알려진 소리로 설명되지 않는 소리 시작점 | — | 0 | {"count":0,"onsets":[]} | 같다 | 아니오 | BGM·원음·검출된 효과음을 뺀 잔차에서 급격한 에너지 상승(보존 원음 구간 제외) |

### 음량

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 통합 음량(LUFS)·트루피크 | 못 잼 | {"integrated_lufs":-14.0,"true_peak_db":-1.5} | {"integrated_lufs":-14.7,"lra":0.6,"true_peak_db":-2.0} | 같다 | 아니오 | — |
| 음량 (레퍼런스 대비) | 못 잼 | {"audio.loudness.integrated_lufs":-14.0,"audio.loudness.true_peak_db":-1.5} | {"integrated_lufs":-14.7,"true_peak_db":-2.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: audio.loudness.integrated_lufs, audio.loudness.tr… |
| 출력 오디오 표본율 | {"audio.sample_rate":"해당 없음(infra)"} | 48000 | 48000 | 같다 | 아니오 | ffprobe 로 읽은 출력 MP4 의 오디오 표본율 |

### 구성·표지

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 영상 길이 | — | 22.5 | 22.5 | 같다 | 아니오 | — |
| 영상 길이 (레퍼런스 분포 대비) | 못 잼 | {"structure.duration_s.p10":null,"structure.duration_s.p50":null,"structure.duration_s.p9… | {"duration":22.5} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: structure.duration_s.p10, structure.duration_s.p5… |
| 첫 시간제 자막 시각 (레퍼런스 대비) | 못 잼 | {"structure.first_caption_at_s":0.0} | {"first_caption_at_s":0.267,"caption":"c_sit1","role":"situation"} | 못 잼 (참고) | 아니오 | t=0.27s 레퍼런스 미측정(임시값) 키 1개: structure.first_caption_at_s — 출력이 임시값과 같아도 레퍼런스와… |
| 표지 프레임에 제목 문구 표시 | 못 잼 | {"t":0.0,"text":"빈 방에 들어온 사람들","role":"title","source":"first_frame"} | {"ocr":"빈 방 에 들어온 사람들","similarity":1.0,"role_caption_visible":true} | 같다 (참고) | 아니오 | t=0.00s |
| 표지 구성 (레퍼런스 대비) | 못 잼 | {"cover.source":"first_frame","cover.text_role":"title"} | {"t":0.0,"source":"first_frame","text_role":"title","text_role_visible":true,"similarity"… | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: cover.source, cover.text_role — 출력이 임시값과 같아도 레퍼런스… |

### 레퍼런스 같은 시각 비교(1초 격자)

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 역할·표시 (레퍼런스와 같은 절대 시각 1초 격자) | 못 잼 | — | — | 못 잼 (참고) | 아니오 | 레퍼런스 영상 없음: 에피소드 포맷이 정해지지 않음(UNCLASSIFIED) — 대표 영상을 고를 수 없음 (formats.… |
| 컷·전환 위치 (레퍼런스와 같은 절대 시각 1초 격자) | 못 잼 | — | — | 못 잼 (참고) | 아니오 | 레퍼런스 영상 없음: 에피소드 포맷이 정해지지 않음(UNCLASSIFIED) — 대표 영상을 고를 수 없음 (formats.… |
| 효과음 종류·자리 (레퍼런스와 같은 절대 시각 0.5초 격자) | 못 잼 | — | — | 못 잼 (참고) | 아니오 | 레퍼런스 영상 없음: 에피소드 포맷이 정해지지 않음(UNCLASSIFIED) — 대표 영상을 고를 수 없음 (formats.… |
| 레퍼런스 1편과 같은 절대 시각 1초 격자 비교 시트 | {"video_id":null} | {"reference":null,"grid_s":1.0,"sfx_strip_s":0.5} | {"sheets":["episodes/test-coverage-001/qa/compare_sheet.png","episodes/test-coverage-001/… | 못 잼 (참고) | 아니오 | 레퍼런스 MP4 없음 — 시트의 레퍼런스 줄이 '못 잼'으로 그려짐: 에피소드 포맷이 정해지지 않음(UNCLASSIFIED)… |

## 못 잼 항목과 이유

- 화면 해상도·프레임레이트 (레퍼런스 대비) (`canvas.format:format_ref`): 레퍼런스 미측정(임시값) 키 3개: canvas.width, canvas.height, canvas.fps — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치
- 영상 영역 (레퍼런스 대비) (`canvas.video_region:region_ref`): 레퍼런스 미측정(임시값) 키 4개: canvas.video_region.x, canvas.video_region.y, canvas.video_region.w, canvas.video_region.h — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치
- 배경 (레퍼런스 대비) (`canvas.background:background_ref`): 레퍼런스 미측정(임시값) 키 2개: canvas.background.type, canvas.background.color — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 적용되지 않아 판정에서 뺀 키: canvas.background.blur_sigma — background.type=color(흐린 원본 배경 아님) → 흐림 정도가 쓰이지 않음. — 제작 영향: 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치
- 영상 영역 채우기(cover/contain) (`canvas.video_region:fit`): 모든 클립에서 cover 와 contain 렌더링이 같아(소스 비율 = 영역 비율) 채우기 방식을 출력에서 구별할 수 없음 — 제작 영향: 화면 구성을 확인하지 못함
- 영상 영역 채우기 (레퍼런스 대비) (`canvas.video_region:fit_ref`): 레퍼런스 미측정(임시값) 키 1개: canvas.video_region.fit — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 출력에서 구별 가능한 클립의 채우기 방식(최빈) — 제작 영향: 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치
- **필수** 반전 전에 반전 내용을 미리 말하지 않음 (`caption.reveal:reveal`): plan 이 '반전 없음'(reveal.none: 빈 방에 사람이 들어와 걸어 나가고(people-detection 2.0~6.8s), 남성이 카메라 앞까지 와서 서 있다가(face-demographics 5.0~13.0s), 두 사람이 들어와 나란히 선 뒤 떠나는(32.0~37.0s, 42.0~44.0s) 순서대로 보이는 장면뿐 — 뒤에서 드러나는 예상 밖 사건·정체가 없어 앞 자막이 미리 말할 반전이 없음. 구간 목적도 context → build → reaction → build → outro 로 reveal 구간 없음)이라고 적었을 뿐 출력에서 잰 것이 아님 — 보호할 키워드가 없어 자막을 대조할 수 없음; 사람이 보고 `shortkit qa human-check --kind watch` 로 기록 — 제작 영향: 자막 문구·말투를 확인하지 못함
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
- 자막 위치 [title] (레퍼런스 대비) (`caption.position:title_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.title.anchor.x, text.roles.title.anchor.y — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 제목/자막 위치 불일치
- 자막 크기 [title] (레퍼런스 대비) (`caption.size:title_ref`): 레퍼런스 미측정(임시값) 키 1개: text.roles.title.size_px — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글자 크기 불일치 → 줄 수·가림 영역 변화
- 자막 색·외곽선·그림자·박스 [title] (레퍼런스 대비) (`caption.style:title_ref`): 레퍼런스 미측정(임시값) 키 1개: text.roles.title.color — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 측정한 채움색·외곽선(배경과 구별될 때)·박스 불투명도의 중앙값 + 레퍼런스 분석기와 같은 정의(reference.textboxes.measure_line / box_alpha; 그림자는 레퍼런스와 같은 추정기 shortkit.util.textmeasure.drop_shadow)로 잰 그림자·박스 여백(박스 경계 − 보이는 잉크)·박스 색; 재지 못한 키(어두운 배경의 그림자, 박스가 안 보이는 경우 등)는 행에서 뺌 — 제작 영향: 글자 색 불일치
- 자막 글꼴·굵기 [title] (레퍼런스 대비) (`caption.font:title_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.title.font_name, text.roles.title.bold — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 글꼴 = 역할 합동 판정이 동일(identical)인 면; 굵기 = 그 면의 OS/2 굵기 ≥ typography.BOLD_MIN_WEIGHT(ref fonts 와 같은 규칙) — 제작 영향: 글꼴이 레퍼런스와 다를 수 있음 → 글자 인상·폭·줄바꿈 불일치
- 자막 표시 시간 [title] (레퍼런스 대비) (`caption.timing:title_ref`): 레퍼런스 미측정(임시값) 키 1개: text.roles.title.persist — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 적용되지 않아 판정에서 뺀 키: timing.lead_s — 정의: lead_s = 겹치는 말소리 시작 − 대사 자막 시작 → 대사 외 역할은 기준 사건이 없음(값 0); timing.min_dur_s — persist=whole_video(영상 전체에 떠 있음). persist: 역할 자막 하나가 영상 길이의 90% 이상 보이면 whole_video(레퍼런스 분석기와 같은 정의); — 제작 영향: 레퍼런스와의 일치 여부를 판정할 수 없음
- 자막 등장·퇴장 모션 [title] (레퍼런스 대비) (`caption.motion:title_ref`): 레퍼런스 미측정(임시값) 키 1개: text.roles.title.motion_in.type — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼런스 대비 등장·퇴장 모션: 측정한 최빈 종류와 길이(중앙값)·pop 첫 배율·slide 첫 프레임 이동을 비교(레퍼런스 분석기와 렌더러가 같은 용어: slide_up = 아래에서 위로 등장; 다른 방향의 slide_* 는 렌더러가 그리지 못해 resolve 가 거부); 측정 못 한 키는 행에서 뺌 — 제작 영향: 자막 등장·퇴장 모션 불일치
- 자막 말투 (레퍼런스 대비) (`caption.tone:tone_ref`): 레퍼런스 미측정(임시값) 키 1개: text.tone.register — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 자막 종결 어미(말투) 검사 기준이 임시값 → 대본 말투가 레퍼런스와 다를 수 있음
- 줌 배율·길이·가속 곡선·고정점 규칙 (레퍼런스 대비) (`video.zoom:zoom_ref`): 레퍼런스 미측정(임시값) 키 1개: motion.zoom.scale_to — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 고정점 규칙(recenter) = 출력에서 잰 줌 고정점이 렌더러 규칙(edit.resolve.src_to_region)의 false/true 중 어느 쪽과 맞는지; 재지 못한 키는 행에서 뺌 — 제작 영향: 확대·정지·전환의 크기/길이 불일치
- 정지 길이 (레퍼런스 대비) (`video.freeze:freeze_ref`): 레퍼런스 미측정(임시값) 키 1개: motion.freeze.hold_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 확대·정지·전환의 크기/길이 불일치
- 전환 종류·길이·플래시 색·범위 (레퍼런스 대비) (`video.transitions:transitions_ref`): 레퍼런스 미측정(임시값) 키 4개: motion.transitions.default, motion.transitions.flash.dur_s, motion.transitions.flash.color, motion.transitions.flash.scope — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 플래시 범위 = 플래시 정점에서 영상 영역 밖(자막·장식 제외)이 플래시 색으로 밝아졌는지(canvas) 아닌지(region); 재지 못한 키는 행에서 뺌 — 제작 영향: 확대·정지·전환의 크기/길이 불일치
- 느린 재생 배율 (레퍼런스 대비) (`video.speed:speed_ref`): 레퍼런스 미측정(임시값) 키 1개: motion.speed.slowmo_factor — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 확대·정지·전환의 크기/길이 불일치
- 장식 스타일 [circle] (레퍼런스 대비) (`decor.style:d_circle_ref`): 레퍼런스 미측정(임시값) 키 3개: decorations.circle.color, decorations.circle.stroke_px, decorations.circle.blink_hz — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 화살표·원 등 장식 스타일 불일치
- 장식 스타일 [box] (레퍼런스 대비) (`decor.style:d_box_ref`): 레퍼런스 미측정(임시값) 키 3개: decorations.box.color, decorations.box.stroke_px, decorations.box.blink_hz — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 화살표·원 등 장식 스타일 불일치
- 레퍼런스 로고 템플릿 없음 (`identity.logo_templates:all`): 식별 템플릿 기록이 완전하지 않음(상태 unmeasured): 레퍼런스 목록 수집 차단(2026-09-24T17:56:07+00:00, yt-dlp 2026.08.19): https://youtube.com/@joshuamagazine/shorts: DownloadError: ERROR: [youtube:tab] @joshuamagazine/shorts: Unable to download API page: ('Unable to connect to proxy', OSError('Tunnel connection failed: 403 Forbidden')) (caused by ProxyError("('Unable to connect to proxy', OSError('Tunnel connection fai — 제작 측정은 고정된 최신 100편 스냅샷 구성원만 사용 — `shortkit ref identity-templates` 다시 실행 — 글자 없는 로고는 OCR 검사(identity.forbidden_text)로 잡히지 않음 — 제작 영향: 레퍼런스 채널 식별 요소·같은 녹화 재사용 여부를 확인하지 못함 → 게시 위험
- 레퍼런스와 같은 녹화(영상) 재사용 없음 (`identity.reference_footage:all`): 레퍼런스 영상 지문(exclusions.jsonl reference_footage) 없음 → 같은 녹화 여부 못 잼 (URL 규칙만 확인) — 제작 영향: 레퍼런스 채널 식별 요소·같은 녹화 재사용 여부를 확인하지 못함 → 게시 위험
- 원본 오버레이 검출 기록 [v_room] (`clean.residual:prov:v_room`): 출처 기록 없음(warehouse/overlays/18ffe8672d74….json) — `python -m shortkit clean detect --source assets/test/generated/video/people-detection.mp4` — 원본 로고·오버레이가 남았는지 출처 기록으로 대조할 수 없음(모서리 OCR 검사만 적용) — 제작 영향: 원본 로고·출처 표기가 남아 있는지 확인하지 못함 → 게시 위험
- 원본 오버레이 검출 기록 [v_face] (`clean.residual:prov:v_face`): 출처 기록 없음(warehouse/overlays/d88ab9aa0363….json) — `python -m shortkit clean detect --source assets/test/generated/video/face-demographics-walking-and-pause.mp4` — 원본 로고·오버레이가 남았는지 출처 기록으로 대조할 수 없음(모서리 OCR 검사만 적용) — 제작 영향: 원본 로고·출처 표기가 남아 있는지 확인하지 못함 → 게시 위험
- BGM 은 깨끗한 음원(레퍼런스에서 분리한 스템 금지) (`audio.bgm:clean_file`): 레퍼런스 분리 음원 파일(presets/*/analysis/*/stems)이 하나도 없어 파형 대조 대상이 없음 — `ref audio-analyze` 뒤 다시 검사 — 제작 영향: BGM 곡·구간·덕킹을 확인하지 못함 → 음악 일치 판정 불가
- BGM 곡·버전·속도·구간 (레퍼런스 대비) (`audio.bgm:bgm_ref`): 레퍼런스 미측정(임시값) 키 5개: audio.bgm.track_id, audio.bgm.title, audio.bgm.version, audio.bgm.tempo_ratio, audio.bgm.section_start_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. audio_bgm.is_match: 곡(track_id/제목)·버전·속도·구간이 모두 레퍼런스와 같아야 같다; 계획이 파일 경로로 BGM 을 지정해 라이브러리 곡 id 가 없음 → 곡 일치는 못 잼 — 제작 영향: BGM 곡/버전/속도/구간/크기 불일치 → 음악 일치 판정 불가
- BGM 크기 (레퍼런스 대비) (`audio.bgm:level_ref`): 레퍼런스 미측정(임시값) 키 1개: audio.bgm.gain_db — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼런스와 같은 정의(ref audio-measure: 깨끗한 음원 LS 이득 + 목표 LUFS − 믹스 LUFS) — 제작 영향: BGM 곡/버전/속도/구간/크기 불일치 → 음악 일치 판정 불가
- 보존 원음 크기 (레퍼런스 대비) (`audio.original:orig_ref`): 레퍼런스 미측정(임시값) 키 1개: audio.original.keep_gain_db — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 크기 = 보존 원음 통합 음량 − 프로그램 통합 음량(LU), ref audio-measure 와 같은 정의 — 제작 영향: 보존 원음 크기 불일치
- 효과음 [fx1] 종류 = 소리 지문(카탈로그 대비) (`audio.sfx.type:fx1`): 소리 지문으로 종류를 정하지 못함: 효과음 카탈로그 미측정(상태 unmeasured: 2026-09-24: 레퍼런스 최신 50편 다운로드 불가(youtube 차단), Demucs 가중치 호스트(dl.fbaipublicfiles.com) 차단) — 종류 지문 없음 — 제작 영향: 레퍼런스와의 일치 여부를 판정할 수 없음
- 효과음 [fx2] 종류 = 소리 지문(카탈로그 대비) (`audio.sfx.type:fx2`): 소리 지문으로 종류를 정하지 못함: 효과음 카탈로그 미측정(상태 unmeasured: 2026-09-24: 레퍼런스 최신 50편 다운로드 불가(youtube 차단), Demucs 가중치 호스트(dl.fbaipublicfiles.com) 차단) — 종류 지문 없음 — 제작 영향: 레퍼런스와의 일치 여부를 판정할 수 없음
- 효과음 [fx3] 종류 = 소리 지문(카탈로그 대비) (`audio.sfx.type:fx3`): 소리 지문으로 종류를 정하지 못함: 효과음 카탈로그 미측정(상태 unmeasured: 2026-09-24: 레퍼런스 최신 50편 다운로드 불가(youtube 차단), Demucs 가중치 호스트(dl.fbaipublicfiles.com) 차단) — 종류 지문 없음 — 제작 영향: 레퍼런스와의 일치 여부를 판정할 수 없음
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
- `episodes/test-coverage-001/qa/compare_sheet.png`
- `episodes/test-coverage-001/qa/compare_sheet_p02.png`

## 결함 기록 (defects.jsonl)
- 열림 1 / 이번에 고침 확인 0 / 재발 0 / 새로 등록 0 / 고침 기록 필요(resolved_without_fix·fixed_unrechecked) 1 / 못 잼으로 바뀌어 열린 채 0 / 이전 규칙으로 닫혔다가 재분류 0
- 같은 검사 재확인: test-pipeline-001: caption.font=ok, caption.reveal=ok
- 같은 검사 재확인: test-qa-bad: caption.font=problem, caption.reveal=problem
- 같은 검사 재확인: test-qa-good: caption.font=ok, caption.reveal=problem

---
판정 기준: 같다=허용오차 안, 다르다=허용오차 밖, 못 잼=측정 불가(완료로 치지 않음 — 필수 표시가 없는 '참고' 못 잼도 production 최종 관문 P4 에서 완료를 막는다; 다른 필수 행이 같은 판정을 하는 경우만 예외). 레퍼런스 열의 '못 잼'은 레퍼런스에서 측정되지 않은 임시값이라는 뜻이다.

오디오 판정은 모두 기계 측정(파형 대조·최소제곱·정합 필터·EBU R128)이다. 사람이 직접 들어 본 청취 확인은 이 보고서에 포함되어 있지 않다.
