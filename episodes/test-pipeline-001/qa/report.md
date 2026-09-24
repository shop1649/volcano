# QA 보고서 — test-pipeline-001

- 측정 대상: `episodes/test-pipeline-001/output/test-pipeline-001.mp4` (sha256 `c391c32bb3574c40…`, 1080x1920, 21.27s)
- 원칙: 최종 MP4 만 측정(타임라인/코드가 맞다고 출력이 맞다고 보지 않음)
- 프리셋: joshuamagazine-v1 / 포맷 UNCLASSIFIED / 모드 **test**
- 레퍼런스: 없음(못 잼)
- 측정 시각: 2026-09-24T19:51:32+00:00 / 도구: OCR=5.3.4, 얼굴검출=shortkit.clean.faces haar frontal+profile (shortkit.HaarCascade(numpy))

## 최종 관문: **불합격**
- ✗ G1: 의도하지 않은 차이(다르다) 6건 — caption.font:c_sit4, audio.sfx.placement:fx1:gain, audio.sfx.placement:fx2:gain, audio.sfx.placement:fx3:gain, audio.sfx.placement:fx4:gain, audio.sfx.placement:fx5:gain
- ✗ G2: 필수 항목 못 잼 1건 — 못 잼은 완료가 아님 — caption.font:c_sit3
- △ P1: 프리셋 미측정(임시값) 키 257개
- △ P2: 레퍼런스 대비 못 잼 53건
- △ P3: 테스트 모드 출력(파이프라인 검증용) — 게시 불가

## 요약
- 전체 212행: 같다 147 / 다르다 6 (의도한 변경 0, 의도하지 않음 6) / 못 잼 59
- 계획 대비(출력이 계획대로인가): {'same': 147, 'unmeasured': 6, 'different': 6}
- 레퍼런스 대비(레퍼런스와 같은가): {'unmeasured': 53}
- 프리셋 미측정(임시값) 키: 257개

| 분류 | 같다 | 다르다 | 못 잼 |
|---|---:|---:|---:|
| 화면 구성 | 4 | 0 | 3 |
| 글자 위치 | 18 | 0 | 12 |
| 자막 내용·말투 | 11 | 0 | 2 |
| 자막 스타일 | 9 | 0 | 6 |
| 폰트 | 7 | 1 | 7 |
| 자막 타이밍 | 9 | 0 | 6 |
| 자막 등장·퇴장 모션 | 9 | 0 | 6 |
| 컷 | 8 | 0 | 0 |
| 모션(확대·정지·전환) | 11 | 0 | 3 |
| 움직이는 장식(위치/밝기 각각) | 2 | 0 | 1 |
| 식별 요소 | 1 | 0 | 2 |
| 로고 잔류 | 1 | 0 | 2 |
| 얼굴·손·물체 가림 | 23 | 0 | 0 |
| 음악 구간 | 11 | 0 | 2 |
| 원음 | 3 | 0 | 1 |
| 효과음 종류별 개수 | 10 | 5 | 2 |
| 사건과의 시차 | 5 | 0 | 0 |
| 사건 없는 효과음 0 | 2 | 0 | 0 |
| 음량 | 1 | 0 | 1 |
| 구성·표지 | 2 | 0 | 3 |

## 검사표

### 화면 구성

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 화면 해상도·프레임레이트 | 못 잼 | {"width":1080,"height":1920,"fps":30.0} | {"width":1080,"height":1920,"fps":30.0} | 같다 | 아니오 | — |
| 화면 해상도·프레임레이트 (레퍼런스 대비) | 못 잼 | {"canvas.width":1080,"canvas.height":1920,"canvas.fps":30} | {"width":1080,"height":1920,"fps":30.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: canvas.width, canvas.height, canvas.fps — 출력이 임시값… |
| 영상 영역 위치·크기 | 못 잼 | {"rect":[0.0,656.0,1080.0,608.0],"resolution":[1080,1920]} | {"rect":[0.0,656.0,1080.0,608.0],"resolution":[1080,1920]} | 같다 (참고) | 아니오 | 움직이는 화소·배경색 차이로 측정(휴리스틱) |
| 영상 영역 (레퍼런스 대비) | 못 잼 | {"canvas.video_region.x":0,"canvas.video_region.y":656,"canvas.video_region.w":1080,"canv… | {"rect":[0.0,656.0,1080.0,608.0]} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 5개: canvas.video_region.x, canvas.video_region.y, can… |
| 배경(색/소스 블러) | 못 잼 | {"type":"color","color":"#000000"} | {"type":"color","color":"#000000","temporal_std":0.01} | 같다 (참고) | 아니오 | blur_sigma 는 측정하지 않음 |
| 배경 (레퍼런스 대비) | 못 잼 | {"canvas.background.type":"color","canvas.background.color":"#000000","canvas.background.… | {"type":"color","color":"#000000","temporal_std":0.01} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: canvas.background.type, canvas.background.color, … |
| 자막이 안전 여백 안에 있음 | 못 잼 | {"left":54,"right":54,"top":110,"bottom":250} | {"min_margin_px":{"left":187,"top":297,"right":185,"bottom":450}} | 같다 (참고) | 아니오 | — |

### 글자 위치

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 위치 [c_title·title] "움직임 테스트 영상" | 못 잼 | {"center":[540.1,335.1],"bbox":[205.6,288.6,669.0,93.0],"resolution":[1080,1920]} | {"center":[541.0,335.5],"bbox":[216,297,650,77],"resolution":[1080,1920],"dx":0.9,"dy":0.… | 같다 | 아니오 | t=0.12s [프레임](frames/cap_c_title_0000120.png) |
| 자막 크기·줄 수 [c_title·title] "움직임 테스트 영상" | 못 잼 | {"fill_h":81.0,"lines":1,"max_width_px":980.0,"max_lines":2,"size_px":84.0} | {"fill_h":77,"fill_w":650,"lines":1,"size_px_est":79.9} | 같다 | 아니오 | t=0.12s [프레임](frames/cap_c_title_0000120.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_desc·description] "파이프라인 검증용 합성 샘플" | 못 잼 | {"center":[540.0,503.6],"bbox":[266.5,477.1,547.0,53.0],"resolution":[1080,1920]} | {"center":[540.0,503.0],"bbox":[273,482,534,42],"resolution":[1080,1920],"dx":0.0,"dy":-0… | 같다 | 아니오 | t=0.32s [프레임](frames/cap_c_desc_0000320.png) |
| 자막 크기·줄 수 [c_desc·description] "파이프라인 검증용 합성 샘플" | 못 잼 | {"fill_h":45.0,"lines":1,"max_width_px":980.0,"max_lines":1,"size_px":46.0} | {"fill_h":42,"fill_w":534,"lines":1,"size_px_est":42.9} | 같다 | 아니오 | t=0.32s [프레임](frames/cap_c_desc_0000320.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_spk·speaker] "창가 남성" | — | {"center":[739.0,772.5],"bbox":[664.0,754.0,150.0,37.0],"resolution":[1080,1920]} | {"center":[739.5,772.5],"bbox":[665,754,149,37],"resolution":[1080,1920],"dx":0.5,"dy":0.… | 같다 | 아니오 | t=0.57s [프레임](frames/cap_c_spk_0000570.png) 에피소드 위치 지정(pos) |
| 자막 크기·줄 수 [c_spk·speaker] "창가 남성" | 못 잼 | {"fill_h":37.0,"lines":1,"max_width_px":420.0,"max_lines":1,"size_px":40.0} | {"fill_h":37,"fill_w":149,"lines":1,"size_px_est":40.0} | 같다 | 아니오 | t=0.57s [프레임](frames/cap_c_spk_0000570.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_sit1·situation] "창가 남성이 일어선다" | 못 잼 | {"center":[540.2,1433.8],"bbox":[245.7,1395.8,589.0,76.0],"resolution":[1080,1920]} | {"center":[541.0,1434.0],"bbox":[255,1403,572,62],"resolution":[1080,1920],"dx":0.8,"dy":… | 같다 | 아니오 | t=1.54s [프레임](frames/cap_c_sit1_0001540.png) |
| 자막 크기·줄 수 [c_sit1·situation] "창가 남성이 일어선다" | 못 잼 | {"fill_h":64.0,"lines":1,"max_width_px":960.0,"max_lines":2,"size_px":66.0} | {"fill_h":62,"fill_w":572,"lines":1,"size_px_est":63.9} | 같다 | 아니오 | t=1.54s [프레임](frames/cap_c_sit1_0001540.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_sit2·situation] "다시 자리에 앉는다" | 못 잼 | {"center":[540.0,1433.8],"bbox":[276.0,1395.8,528.0,76.0],"resolution":[1080,1920]} | {"center":[542.5,1434.0],"bbox":[288,1403,509,62],"resolution":[1080,1920],"dx":2.5,"dy":… | 같다 | 아니오 | t=4.34s [프레임](frames/cap_c_sit2_0004340.png) |
| 자막 크기·줄 수 [c_sit2·situation] "다시 자리에 앉는다" | 못 잼 | {"fill_h":64.0,"lines":1,"max_width_px":960.0,"max_lines":2,"size_px":66.0} | {"fill_h":62,"fill_w":509,"lines":1,"size_px_est":63.9} | 같다 | 아니오 | t=4.34s [프레임](frames/cap_c_sit2_0004340.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_sit3·situation] "뒷줄 남성이 손을 든다" | 못 잼 | {"center":[540.1,1433.8],"bbox":[238.1,1395.8,604.0,76.0],"resolution":[1080,1920]} | {"center":[541.5,1434.0],"bbox":[248,1403,587,62],"resolution":[1080,1920],"dx":1.4,"dy":… | 같다 | 아니오 | t=7.94s [프레임](frames/cap_c_sit3_0007940.png) |
| 자막 크기·줄 수 [c_sit3·situation] "뒷줄 남성이 손을 든다" | 못 잼 | {"fill_h":64.0,"lines":1,"max_width_px":960.0,"max_lines":2,"size_px":66.0} | {"fill_h":62,"fill_w":587,"lines":1,"size_px_est":63.9} | 같다 | 아니오 | t=7.94s [프레임](frames/cap_c_sit3_0007940.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_dlg·dialogue] ""저기 봐, 들어온다!"" | 못 잼 | {"center":[539.8,1437.0],"bbox":[257.8,1397.0,564.0,80.0],"resolution":[1080,1920]} | {"center":[540.0,1437.5],"bbox":[270,1405,540,65],"resolution":[1080,1920],"dx":0.2,"dy":… | 같다 | 아니오 | t=10.22s [프레임](frames/cap_c_dlg_0010219.png) |
| 자막 크기·줄 수 [c_dlg·dialogue] ""저기 봐, 들어온다!"" | 못 잼 | {"fill_h":68.0,"lines":1,"max_width_px":960.0,"max_lines":2,"size_px":62.0} | {"fill_h":65,"fill_w":540,"lines":1,"size_px_est":59.3} | 같다 | 아니오 | t=10.22s [프레임](frames/cap_c_dlg_0010219.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_rx·reaction] "갸우뚱?" | 못 잼 | {"center":[540.2,1144.6],"bbox":[407.8,1101.1,265.0,87.0],"resolution":[1080,1920]} | {"center":[540.0,1145.5],"bbox":[419,1111,242,69],"resolution":[1080,1920],"dx":-0.2,"dy"… | 같다 | 아니오 | t=15.32s [프레임](frames/cap_c_rx_0015319.png) |
| 자막 크기·줄 수 [c_rx·reaction] "갸우뚱?" | 못 잼 | {"fill_h":73.0,"lines":1,"max_width_px":900.0,"max_lines":1,"size_px":76.0} | {"fill_h":69,"fill_w":242,"lines":1,"size_px_est":71.8} | 같다 | 아니오 | t=15.32s [프레임](frames/cap_c_rx_0015319.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [c_sit4·situation] "두 사람이 고개를 기울인다" | 못 잼 | {"center":[539.9,1433.8],"bbox":[177.4,1395.8,725.0,76.0],"resolution":[1080,1920]} | {"center":[541.0,1434.0],"bbox":[187,1403,708,62],"resolution":[1080,1920],"dx":1.1,"dy":… | 같다 | 아니오 | t=15.34s [프레임](frames/cap_c_sit4_0015339.png) |
| 자막 크기·줄 수 [c_sit4·situation] "두 사람이 고개를 기울인다" | 못 잼 | {"fill_h":64.0,"lines":1,"max_width_px":960.0,"max_lines":2,"size_px":66.0} | {"fill_h":62,"fill_w":708,"lines":1,"size_px_est":63.9} | 같다 | 아니오 | t=15.34s [프레임](frames/cap_c_sit4_0015339.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [description] (레퍼런스 대비) | 못 잼 | {"text.roles.description.anchor.x":540,"text.roles.description.anchor.y":500,"text.roles.… | {"x":540.0,"y":503.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 5개: text.roles.description.anchor.x, text.roles.descr… |
| 자막 크기 [description] (레퍼런스 대비) | 못 잼 | {"text.roles.description.size_px":46,"text.roles.description.line_spacing":1.15,"text.rol… | {"size_px_est":42.9} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: text.roles.description.size_px, text.roles.descri… |
| 자막 위치 [dialogue] (레퍼런스 대비) | 못 잼 | {"text.roles.dialogue.anchor.x":540,"text.roles.dialogue.anchor.y":1430,"text.roles.dialo… | {"x":540.0,"y":1437.5} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 5개: text.roles.dialogue.anchor.x, text.roles.dialogue… |
| 자막 크기 [dialogue] (레퍼런스 대비) | 못 잼 | {"text.roles.dialogue.size_px":62,"text.roles.dialogue.line_spacing":1.15,"text.roles.dia… | {"size_px_est":59.3} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: text.roles.dialogue.size_px, text.roles.dialogue.… |
| 자막 위치 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.anchor.x":540,"text.roles.reaction.anchor.y":1140,"text.roles.react… | {"x":540.0,"y":1145.5} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 5개: text.roles.reaction.anchor.x, text.roles.reaction… |
| 자막 크기 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.size_px":76,"text.roles.reaction.line_spacing":1.1,"text.roles.reac… | {"size_px_est":71.8} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: text.roles.reaction.size_px, text.roles.reaction.… |
| 자막 위치 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.anchor.x":540,"text.roles.situation.anchor.y":1430,"text.roles.sit… | {"x":541.2,"y":1434.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 5개: text.roles.situation.anchor.x, text.roles.situati… |
| 자막 크기 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.size_px":66,"text.roles.situation.line_spacing":1.15,"text.roles.s… | {"size_px_est":63.9} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: text.roles.situation.size_px, text.roles.situatio… |
| 자막 위치 [speaker] (레퍼런스 대비) | 못 잼 | {"text.roles.speaker.anchor.x":540,"text.roles.speaker.anchor.y":700,"text.roles.speaker.… | — | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 5개: text.roles.speaker.anchor.x, text.roles.speaker.a… |
| 자막 크기 [speaker] (레퍼런스 대비) | 못 잼 | {"text.roles.speaker.size_px":40,"text.roles.speaker.line_spacing":1.1,"text.roles.speake… | {"size_px_est":40.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: text.roles.speaker.size_px, text.roles.speaker.li… |
| 자막 위치 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.anchor.x":540,"text.roles.title.anchor.y":330,"text.roles.title.anchor… | {"x":541.0,"y":335.5} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 5개: text.roles.title.anchor.x, text.roles.title.ancho… |
| 자막 크기 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.size_px":84,"text.roles.title.line_spacing":1.18,"text.roles.title.max… | {"size_px_est":79.9} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: text.roles.title.size_px, text.roles.title.line_s… |

### 자막 내용·말투

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 문구(OCR) [c_title·title] "움직임 테스트 영상" | — | 움직임 테스트 영상 | {"ocr":"움직임 테스트 영상","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=0.12s [프레임](frames/cap_c_title_0000120.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_desc·description] "파이프라인 검증용 합성 샘플" | — | 파이프라인 검증용 합성 샘플 | {"ocr":"파 이 프 라인 ASS 합성 샘플","similarity":0.75,"match":"ocr"} | 같다 | 아니오 | t=0.32s [프레임](frames/cap_c_desc_0000320.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_spk·speaker] "창가 남성" | — | 창가 남성 | {"ocr":"창가 남성","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=0.57s [프레임](frames/cap_c_spk_0000570.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_sit1·situation] "창가 남성이 일어선다" | — | 창가 남성이 일어선다 | {"ocr":"창가 남 성 이 일 어 선다","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=1.54s [프레임](frames/cap_c_sit1_0001540.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_sit2·situation] "다시 자리에 앉는다" | — | 다시 자리에 앉는다 | {"ocr":"다시 자 리 에 앉는다","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=4.34s [프레임](frames/cap_c_sit2_0004340.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_sit3·situation] "뒷줄 남성이 손을 든다" | — | 뒷줄 남성이 손을 든다 | {"ocr":"뒷 줄 남 성 이 손 을 든다","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=7.94s [프레임](frames/cap_c_sit3_0007940.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_dlg·dialogue] ""저기 봐, 들어온다!"" | 못 잼 | "저기 봐, 들어온다!" | {"ocr":"봐 , 들어온다!\"","similarity":0.833,"match":"ocr"} | 같다 | 아니오 | t=10.22s [프레임](frames/cap_c_dlg_0010219.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_rx·reaction] "갸우뚱?" | — | 갸우뚱? | {"ocr":"가 우 뚱 ?","similarity":0.667,"match":"ocr"} | 같다 | 아니오 | t=15.32s [프레임](frames/cap_c_rx_0015319.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [c_sit4·situation] "두 사람이 고개를 기울인다" | — | 두 사람이 고개를 기울인다 | {"ocr":"두 사 람 이 고 개 를 기울인다","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=15.34s [프레임](frames/cap_c_sit4_0015339.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 반전 전에 반전 내용을 미리 말하지 않음 | — | {"reveal_t":15.0,"keywords":["기울","갸우뚱"]} | {"hits":[]} | 같다 | 아니오 | t=15.00s 출력 OCR 문구로 확인 |
| 자막 말투(종결어미, OCR) | 못 잼 | 반말_구어체 | {"n":4,"counts":{"기타":2,"반말_구어체":4},"mode":"반말_구어체","note":"기타(감탄사·명사 끝)는 판정에서 제외","roles… | 같다 (참고) | 아니오 | OCR 문구의 마지막 글자로 분류(휴리스틱) |
| 자막 이모지 사용 | 못 잼 | false | — | 못 잼 (참고) | 아니오 | 출력 화면에서 이모지를 판별하는 방법 없음(OCR 미지원) |
| 자막 말투 (레퍼런스 대비) | 못 잼 | {"text.tone.register":"반말_구어체","text.tone.sentence_end_examples":[],"text.tone.emoji":fal… | {"register":"반말_구어체"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: text.tone.register, text.tone.sentence_end_exampl… |

### 자막 스타일

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 색·외곽선·박스 [c_title·title] "움직임 테스트 영상" | 못 잼 | {"color":"#FFFFFF","outline_px":6.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FFFFFF","outline_px":16,"outline_color":"#000000","box_alpha":null,"highl… | 같다 | 아니오 | t=0.12s [프레임](frames/cap_c_title_0000120.png) 배경이 외곽선 색과 같아 외곽선 두께는 못 잼 |
| 자막 색·외곽선·박스 [c_desc·description] "파이프라인 검증용 합성 샘플" | 못 잼 | {"color":"#E6E6E6","outline_px":4.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#E5E5E5","outline_px":11,"outline_color":"#000000","box_alpha":null,"highl… | 같다 | 아니오 | t=0.32s [프레임](frames/cap_c_desc_0000320.png) 배경이 외곽선 색과 같아 외곽선 두께는 못 잼 |
| 자막 색·외곽선·박스 [c_spk·speaker] "창가 남성" | 못 잼 | {"color":"#FFFFFF","outline_px":0.0,"outline_color":"#000000","box":true,"box_alpha":0.65… | {"fill_color":"#FFFFFF","outline_px":0,"outline_color":"#504E4C","box_alpha":0.629,"highl… | 같다 | 아니오 | t=0.57s [프레임](frames/cap_c_spk_0000570.png) |
| 자막 색·외곽선·박스 [c_sit1·situation] "창가 남성이 일어선다" | 못 잼 | {"color":"#FFFFFF","outline_px":6.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FFFFFF","outline_px":16,"outline_color":"#000000","box_alpha":null,"highl… | 같다 | 아니오 | t=1.54s [프레임](frames/cap_c_sit1_0001540.png) 배경이 외곽선 색과 같아 외곽선 두께는 못 잼 |
| 자막 색·외곽선·박스 [c_sit2·situation] "다시 자리에 앉는다" | 못 잼 | {"color":"#FFFFFF","outline_px":6.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FFFFFF","outline_px":16,"outline_color":"#000000","box_alpha":null,"highl… | 같다 | 아니오 | t=4.34s [프레임](frames/cap_c_sit2_0004340.png) 배경이 외곽선 색과 같아 외곽선 두께는 못 잼 |
| 자막 색·외곽선·박스 [c_sit3·situation] "뒷줄 남성이 손을 든다" | 못 잼 | {"color":"#FFFFFF","outline_px":6.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FFFFFF","outline_px":16,"outline_color":"#000000","box_alpha":null,"highl… | 같다 | 아니오 | t=7.94s [프레임](frames/cap_c_sit3_0007940.png) 배경이 외곽선 색과 같아 외곽선 두께는 못 잼 |
| 자막 색·외곽선·박스 [c_dlg·dialogue] ""저기 봐, 들어온다!"" | 못 잼 | {"color":"#FFE400","outline_px":6.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FDE300","outline_px":16,"outline_color":"#020000","box_alpha":null,"highl… | 같다 | 아니오 | t=10.22s [프레임](frames/cap_c_dlg_0010219.png) 배경이 외곽선 색과 같아 외곽선 두께는 못 잼 |
| 자막 색·외곽선·박스 [c_rx·reaction] "갸우뚱?" | 못 잼 | {"color":"#FFE400","outline_px":7.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FEE300","outline_px":7,"outline_color":"#050000","box_alpha":0.0,"highlig… | 같다 | 아니오 | t=15.32s [프레임](frames/cap_c_rx_0015319.png) |
| 자막 색·외곽선·박스 [c_sit4·situation] "두 사람이 고개를 기울인다" | 못 잼 | {"color":"#FFFFFF","outline_px":6.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FFFFFF","outline_px":16,"outline_color":"#010000","box_alpha":null,"highl… | 같다 | 아니오 | t=15.34s [프레임](frames/cap_c_sit4_0015339.png) 배경이 외곽선 색과 같아 외곽선 두께는 못 잼 |
| 자막 색·외곽선·박스 [description] (레퍼런스 대비) | 못 잼 | {"text.roles.description.color":"#E6E6E6","text.roles.description.highlight_color":"#FFE4… | {"fill_color":"#E5E5E5"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 11개: text.roles.description.color, text.roles.descrip… |
| 자막 색·외곽선·박스 [dialogue] (레퍼런스 대비) | 못 잼 | {"text.roles.dialogue.color":"#FFE400","text.roles.dialogue.highlight_color":"#FFFFFF","t… | {"fill_color":"#FDE300"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 11개: text.roles.dialogue.color, text.roles.dialogue.h… |
| 자막 색·외곽선·박스 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.color":"#FFE400","text.roles.reaction.highlight_color":"#FFFFFF","t… | {"fill_color":"#FEE300"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 11개: text.roles.reaction.color, text.roles.reaction.h… |
| 자막 색·외곽선·박스 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.color":"#FFFFFF","text.roles.situation.highlight_color":"#FFE400",… | {"fill_color":"#FFFFFF"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 11개: text.roles.situation.color, text.roles.situation… |
| 자막 색·외곽선·박스 [speaker] (레퍼런스 대비) | 못 잼 | {"text.roles.speaker.color":"#FFFFFF","text.roles.speaker.highlight_color":"#FFE400","tex… | {"fill_color":"#FFFFFF"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 11개: text.roles.speaker.color, text.roles.speaker.hig… |
| 자막 색·외곽선·박스 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.color":"#FFFFFF","text.roles.title.highlight_color":"#FFE400","text.ro… | {"fill_color":"#FFFFFF"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 11개: text.roles.title.color, text.roles.title.highlig… |

### 폰트

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 글꼴 [c_title·title] "움직임 테스트 영상" | 못 잼 | Noto Sans CJK KR Black | {"verdict":"identical","verdict_ko":"동일","iou_expected":0.9883,"margin":0.0727,"top":"Not… | 같다 | 아니오 | t=0.12s [프레임](frames/cap_c_title_0000120.png) 판정: 동일(identical) — IoU 0.988 >= 천장 p10 0.973; 차순위 대비 차이 +0.073 > 잡음 … |
| 자막 글꼴 [c_desc·description] "파이프라인 검증용 합성 샘플" | 못 잼 | Noto Sans CJK KR Bold | {"verdict":"identical","verdict_ko":"동일","iou_expected":0.9511,"margin":0.0573,"top":"Not… | 같다 | 아니오 | t=0.32s [프레임](frames/cap_c_desc_0000320.png) 판정: 동일(identical) — IoU 0.951 >= 천장 p10 0.930; 차순위 대비 차이 +0.057 > 잡음 … |
| 자막 글꼴 [c_spk·speaker] "창가 남성" | 못 잼 | Noto Sans CJK KR Bold | {"verdict":"identical","verdict_ko":"동일","iou_expected":0.9587,"margin":0.0532,"top":"Not… | 같다 | 아니오 | t=0.57s [프레임](frames/cap_c_spk_0000570.png) 판정: 동일(identical) — IoU 0.959 >= 천장 p10 0.945; 차순위 대비 차이 +0.053 > 잡음 … |
| 자막 글꼴 [c_sit1·situation] "창가 남성이 일어선다" | 못 잼 | Noto Sans CJK KR Black | {"verdict":"identical","verdict_ko":"동일","iou_expected":0.9729,"margin":0.0531,"top":"Not… | 같다 | 아니오 | t=1.54s [프레임](frames/cap_c_sit1_0001540.png) 판정: 동일(identical) — IoU 0.973 >= 천장 p10 0.966; 차순위 대비 차이 +0.053 > 잡음 … |
| 자막 글꼴 [c_sit2·situation] "다시 자리에 앉는다" | 못 잼 | Noto Sans CJK KR Black | {"verdict":"identical","verdict_ko":"동일","iou_expected":0.9701,"margin":0.0621,"top":"Not… | 같다 | 아니오 | t=4.34s [프레임](frames/cap_c_sit2_0004340.png) 판정: 동일(identical) — IoU 0.970 >= 천장 p10 0.966; 차순위 대비 차이 +0.062 > 잡음 … |
| 자막 글꼴 [c_sit3·situation] "뒷줄 남성이 손을 든다" | 못 잼 | Noto Sans CJK KR Black | {"verdict":"similar","verdict_ko":"유사(동일 확정 불가)","iou_expected":0.9634,"margin":0.0513,"t… | 못 잼 | 아니오 | t=7.94s [프레임](frames/cap_c_sit3_0007940.png) 판정: 유사(similar, 동일 확정 불가) — 같다고 쓰지 않음. IoU 0.963 < 천장 p10 0.966; 차순위 … |
| 자막 글꼴 [c_dlg·dialogue] ""저기 봐, 들어온다!"" | 못 잼 | Noto Sans CJK KR Black | {"verdict":"identical","verdict_ko":"동일","iou_expected":0.9622,"margin":0.1321,"top":"Not… | 같다 | 아니오 | t=10.22s [프레임](frames/cap_c_dlg_0010219.png) 판정: 동일(identical) — IoU 0.962 >= 천장 p10 0.953; 차순위 대비 차이 +0.132 > 잡음 … |
| 자막 글꼴 [c_rx·reaction] "갸우뚱?" | 못 잼 | Noto Sans CJK KR Black | {"verdict":"identical","verdict_ko":"동일","iou_expected":0.9802,"margin":0.0842,"top":"Not… | 같다 | 아니오 | t=15.32s [프레임](frames/cap_c_rx_0015319.png) 판정: 동일(identical) — IoU 0.980 >= 천장 p10 0.963; 차순위 대비 차이 +0.084 > 잡음 … |
| 자막 글꼴 [c_sit4·situation] "두 사람이 고개를 기울인다" | 못 잼 | Noto Sans CJK KR Black | {"verdict":"different","verdict_ko":"다름","iou_expected":0.8462,"margin":0.0377,"top":"Not… | 다르다 | 아니오 | t=15.34s [프레임](frames/cap_c_sit4_0015339.png) 판정: 다름(different) — IoU 0.846 < 천장 p10 0.966 - 잡음 0.006; 글자별 하한(0.86)… |
| 자막 글꼴 [description] (레퍼런스 대비) | 못 잼 | {"text.roles.description.font_name":"Noto Sans CJK KR Bold","text.roles.description.bold"… | {"best":"Noto Sans CJK KR Bold"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.description.font_name, text.roles.desc… |
| 자막 글꼴 [dialogue] (레퍼런스 대비) | 못 잼 | {"text.roles.dialogue.font_name":"Noto Sans CJK KR Black","text.roles.dialogue.bold":true} | {"best":"Noto Sans CJK KR Black"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.dialogue.font_name, text.roles.dialogu… |
| 자막 글꼴 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.font_name":"Noto Sans CJK KR Black","text.roles.reaction.bold":true} | {"best":"Noto Sans CJK KR Black"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.reaction.font_name, text.roles.reactio… |
| 자막 글꼴 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.font_name":"Noto Sans CJK KR Black","text.roles.situation.bold":tr… | {"best":"Noto Sans CJK KR Black"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.situation.font_name, text.roles.situat… |
| 자막 글꼴 [speaker] (레퍼런스 대비) | 못 잼 | {"text.roles.speaker.font_name":"Noto Sans CJK KR Bold","text.roles.speaker.bold":true} | {"best":"Noto Sans CJK KR Bold"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.speaker.font_name, text.roles.speaker.… |
| 자막 글꼴 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.font_name":"Noto Sans CJK KR Black","text.roles.title.bold":true} | {"best":"Noto Sans CJK KR Black"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.title.font_name, text.roles.title.bold… |

### 자막 타이밍

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 등장·퇴장 시각 [c_title·title] "움직임 테스트 영상" | 못 잼 | {"start":0.0,"end":21.25} | {"onset":0.0,"offset":21.2667} | 같다 | 아니오 | t=0.00s [프레임](frames/cap_c_title_0000120.png) |
| 자막 등장·퇴장 시각 [c_desc·description] "파이프라인 검증용 합성 샘플" | 못 잼 | {"start":0.0,"end":4.0} | {"onset":0.0,"offset":4.0} | 같다 | 아니오 | t=0.00s [프레임](frames/cap_c_desc_0000320.png) |
| 자막 등장·퇴장 시각 [c_spk·speaker] "창가 남성" | 못 잼 | {"start":0.3,"end":3.9} | {"onset":0.3333,"offset":3.8667} | 같다 | 아니오 | t=0.33s [프레임](frames/cap_c_spk_0000570.png) |
| 자막 등장·퇴장 시각 [c_sit1·situation] "창가 남성이 일어선다" | 못 잼 | {"start":1.3,"end":3.9} | {"onset":1.2667,"offset":3.9} | 같다 | 아니오 | t=1.27s [프레임](frames/cap_c_sit1_0001540.png) |
| 자막 등장·퇴장 시각 [c_sit2·situation] "다시 자리에 앉는다" | 못 잼 | {"start":4.1,"end":7.4} | {"onset":4.0667,"offset":7.4333} | 같다 | 아니오 | t=4.07s [프레임](frames/cap_c_sit2_0004340.png) |
| 자막 등장·퇴장 시각 [c_sit3·situation] "뒷줄 남성이 손을 든다" | 못 잼 | {"start":7.7,"end":9.9} | {"onset":7.6667,"offset":9.9} | 같다 | 아니오 | t=7.67s [프레임](frames/cap_c_sit3_0007940.png) |
| 자막 등장·퇴장 시각 [c_dlg·dialogue] ""저기 봐, 들어온다!"" | 못 잼 | {"start":10.1,"end":12.3} | {"onset":10.1,"offset":12.3} | 같다 | 아니오 | t=10.10s [프레임](frames/cap_c_dlg_0010219.png) |
| 자막 등장·퇴장 시각 [c_rx·reaction] "갸우뚱?" | 못 잼 | {"start":15.1,"end":17.5} | {"onset":15.0667,"offset":17.5} | 같다 | 아니오 | t=15.07s [프레임](frames/cap_c_rx_0015319.png) |
| 자막 등장·퇴장 시각 [c_sit4·situation] "두 사람이 고개를 기울인다" | 못 잼 | {"start":15.1,"end":19.0} | {"onset":15.0667,"offset":19.0} | 같다 | 아니오 | t=15.07s [프레임](frames/cap_c_sit4_0015339.png) |
| 자막 표시 시간 [description] (레퍼런스 대비) | 못 잼 | {"text.roles.description.timing.lead_s":0.0,"text.roles.description.timing.min_dur_s":1.0… | {"min_dur_s":4.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: text.roles.description.timing.lead_s, text.roles.… |
| 자막 표시 시간 [dialogue] (레퍼런스 대비) | 못 잼 | {"text.roles.dialogue.timing.lead_s":0.0,"text.roles.dialogue.timing.min_dur_s":0.8,"text… | {"min_dur_s":2.2} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: text.roles.dialogue.timing.lead_s, text.roles.dia… |
| 자막 표시 시간 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.timing.lead_s":0.0,"text.roles.reaction.timing.min_dur_s":0.6,"text… | {"min_dur_s":2.433} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: text.roles.reaction.timing.lead_s, text.roles.rea… |
| 자막 표시 시간 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.timing.lead_s":0.0,"text.roles.situation.timing.min_dur_s":0.9,"te… | {"min_dur_s":2.233} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: text.roles.situation.timing.lead_s, text.roles.si… |
| 자막 표시 시간 [speaker] (레퍼런스 대비) | 못 잼 | {"text.roles.speaker.timing.lead_s":0.0,"text.roles.speaker.timing.min_dur_s":1.0,"text.r… | {"min_dur_s":3.533} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: text.roles.speaker.timing.lead_s, text.roles.spea… |
| 자막 표시 시간 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.timing.lead_s":0.0,"text.roles.title.timing.min_dur_s":1.0,"text.roles… | {"min_dur_s":21.267} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: text.roles.title.timing.lead_s, text.roles.title.… |

### 자막 등장·퇴장 모션

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 등장 모션 [c_title·title] "움직임 테스트 영상" | 못 잼 | {"type":"none","dur_s":0.0,"scale_from":1.0} | {"type":"none","note":"첫 프레임부터 완전히 표시(등장 모션 없음)"} | 같다 | 아니오 | t=0.00s [프레임](frames/cap_c_title_0000120.png) |
| 자막 등장 모션 [c_desc·description] "파이프라인 검증용 합성 샘플" | 못 잼 | {"type":"fade","dur_s":0.2,"scale_from":1.0} | {"type":"fade","scale_first":null,"presence_first":0.166,"dur_s":0.133,"scales":[null,nul… | 같다 | 아니오 | t=0.00s [프레임](frames/cap_c_desc_0000320.png) |
| 자막 등장 모션 [c_spk·speaker] "창가 남성" | 못 잼 | {"type":"fade","dur_s":0.15,"scale_from":1.0} | {"type":"fade","scale_first":null,"presence_first":0.27,"dur_s":0.067,"scales":[null,null… | 같다 | 아니오 | t=0.33s [프레임](frames/cap_c_spk_0000570.png) |
| 자막 등장 모션 [c_sit1·situation] "창가 남성이 일어선다" | 못 잼 | {"type":"pop","dur_s":0.12,"scale_from":0.85} | {"type":"pop","scale_first":0.853,"presence_first":0.512,"dur_s":0.133,"scales":[0.853,0.… | 같다 | 아니오 | t=1.27s [프레임](frames/cap_c_sit1_0001540.png) |
| 자막 등장 모션 [c_sit2·situation] "다시 자리에 앉는다" | 못 잼 | {"type":"pop","dur_s":0.12,"scale_from":0.85} | {"type":"pop","scale_first":0.852,"presence_first":0.533,"dur_s":0.1,"scales":[0.852,0.89… | 같다 | 아니오 | t=4.07s [프레임](frames/cap_c_sit2_0004340.png) |
| 자막 등장 모션 [c_sit3·situation] "뒷줄 남성이 손을 든다" | 못 잼 | {"type":"pop","dur_s":0.12,"scale_from":0.85} | {"type":"pop","scale_first":0.852,"presence_first":0.471,"dur_s":0.1,"scales":[0.852,0.89… | 같다 | 아니오 | t=7.67s [프레임](frames/cap_c_sit3_0007940.png) |
| 자막 등장 모션 [c_dlg·dialogue] ""저기 봐, 들어온다!"" | 못 잼 | {"type":"none","dur_s":0.0,"scale_from":1.0} | {"type":"none","scale_first":1.002,"presence_first":1.0,"dur_s":0.0,"scales":[1.002,1.002… | 같다 | 아니오 | t=10.10s [프레임](frames/cap_c_dlg_0010219.png) |
| 자막 등장 모션 [c_rx·reaction] "갸우뚱?" | 못 잼 | {"type":"pop","dur_s":0.1,"scale_from":1.35} | {"type":"pop","scale_first":1.369,"presence_first":0.751,"dur_s":0.1,"scales":[1.369,1.25… | 같다 | 아니오 | t=15.07s [프레임](frames/cap_c_rx_0015319.png) |
| 자막 등장 모션 [c_sit4·situation] "두 사람이 고개를 기울인다" | 못 잼 | {"type":"pop","dur_s":0.12,"scale_from":0.85} | {"type":"pop","scale_first":0.853,"presence_first":0.513,"dur_s":0.133,"scales":[0.853,0.… | 같다 | 아니오 | t=15.07s [프레임](frames/cap_c_sit4_0015339.png) |
| 자막 등장·퇴장 모션 [description] (레퍼런스 대비) | 못 잼 | {"text.roles.description.motion_in.type":"fade","text.roles.description.motion_in.dur_s":… | {"type":"fade"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 6개: text.roles.description.motion_in.type, text.roles… |
| 자막 등장·퇴장 모션 [dialogue] (레퍼런스 대비) | 못 잼 | {"text.roles.dialogue.motion_in.type":"none","text.roles.dialogue.motion_in.dur_s":0.0,"t… | {"type":"none"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 6개: text.roles.dialogue.motion_in.type, text.roles.di… |
| 자막 등장·퇴장 모션 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.motion_in.type":"pop","text.roles.reaction.motion_in.dur_s":0.1,"te… | {"type":"pop"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 6개: text.roles.reaction.motion_in.type, text.roles.re… |
| 자막 등장·퇴장 모션 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.motion_in.type":"pop","text.roles.situation.motion_in.dur_s":0.12,… | {"type":"pop"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 6개: text.roles.situation.motion_in.type, text.roles.s… |
| 자막 등장·퇴장 모션 [speaker] (레퍼런스 대비) | 못 잼 | {"text.roles.speaker.motion_in.type":"fade","text.roles.speaker.motion_in.dur_s":0.15,"te… | {"type":"fade"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 6개: text.roles.speaker.motion_in.type, text.roles.spe… |
| 자막 등장·퇴장 모션 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.motion_in.type":"none","text.roles.title.motion_in.dur_s":0.0,"text.ro… | {"type":"none"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 6개: text.roles.title.motion_in.type, text.roles.title… |

### 컷

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 컷 위치 [s2 시작] | — | {"t":4.0} | {"t":4.0,"type":"cut"} | 같다 | 아니오 | t=4.00s |
| 컷 위치 [s3 시작] | — | {"t":7.5} | {"t":7.4667,"type":"flash"} | 같다 | 아니오 | t=7.47s |
| 컷 위치 [s4 시작] | — | {"t":12.75} | {"t":12.7489,"type":"crossfade"} | 같다 | 아니오 | t=12.75s |
| 계획에 없는 컷·플래시 | — | [] | [] | 같다 | 아니오 | — |
| 소스 구간 [s1] | — | {"src_in":1.5,"src_out":5.5,"source":"assets/test/generated/classroom_voice.mp4"} | {"offset_s":0.003,"samples":[{"t":0.84,"expected_src_t":2.34,"matched_src_t":2.3,"ncc":0.… | 같다 | 아니오 | t=0.84s |
| 소스 구간 [s2] | — | {"src_in":14.0,"src_out":16.8,"source":"assets/test/generated/classroom_voice.mp4"} | {"offset_s":-0.012,"samples":[{"t":4.607,"expected_src_t":14.607,"matched_src_t":14.633,"… | 같다 | 아니오 | t=4.61s |
| 소스 구간 [s3] | — | {"src_in":17.0,"src_out":22.5,"source":"assets/test/generated/classroom_voice.mp4"} | {"offset_s":0.016,"samples":[{"t":8.686,"expected_src_t":18.186,"matched_src_t":18.233,"n… | 같다 | 아니오 | t=8.69s |
| 소스 구간 [s4] | — | {"src_in":3.0,"src_out":11.5,"source":"assets/test/generated/video/head-pose-face-detecti… | {"offset_s":-0.023,"samples":[{"t":14.69,"expected_src_t":4.94,"matched_src_t":4.917,"ncc… | 같다 | 아니오 | t=14.69s |

### 모션(확대·정지·전환)

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 전환 종류·길이 [s2] | 못 잼 | {"type":"cut","dur":0.0} | {"type":"cut","dur":0.0,"score":39.09} | 같다 | 아니오 | t=4.00s |
| 전환 종류·길이 [s3] | 못 잼 | {"type":"flash","dur":0.12} | {"type":"flash","dur":0.1,"score":120.9} | 같다 | 아니오 | t=7.47s 플래시 최대 밝기 시 영상 영역 평균색 #FDFDFD (기대 #FFFFFF) |
| 전환 종류·길이 [s4] | 못 잼 | {"type":"crossfade","dur":0.25} | {"type":"crossfade","dur":0.2519,"score":0.994} | 같다 | 아니오 | t=12.75s |
| 확대(줌) [s1] | 못 잼 | {"final_ratio":1.25,"t50":1.374,"dur":0.35,"ease":"out","center_canvas":[731.4,971.3]} | {"measured_final_ratio":1.2506,"source_ratio":1.0001,"zoom_ratio_corrected":1.2504,"measu… | 같다 | 아니오 | t=1.40s ORB+RANSAC 유사변환 배율(출력 프레임끼리 비교, 소스 자체의 배율 변화로 나눔) |
| 줌 없음 확인 [s2] | — | {"final_ratio":1.0} | {"max_dev":0.0005,"final_ratio":0.9996,"source_ratio":0.9994,"corrected":1.0002,"median_i… | 같다 (참고) | 아니오 | 소스 자체의 카메라 줌도 여기에 잡힘 |
| 줌 없음 확인 [s3] | — | {"final_ratio":1.0} | {"max_dev":0.0009,"final_ratio":1.0002,"source_ratio":1.0002,"corrected":1.0,"median_inli… | 같다 (참고) | 아니오 | 소스 자체의 카메라 줌도 여기에 잡힘 |
| 줌 없음 확인 [s4] | — | {"final_ratio":1.0} | {"max_dev":0.2638,"final_ratio":0.9519,"source_ratio":0.987,"corrected":0.9645,"median_in… | 같다 (참고) | 아니오 | 소스 자체의 카메라 줌도 여기에 잡힘 |
| 연속 세그먼트 줌 횟수(같은 효과 쌓기 금지) | {"motion.zoom.max_consecutive":"해당 없음(rule)"} | {"max":1} | {"measured":1} | 같다 | 아니오 | — |
| 줌 배율·길이 (레퍼런스 대비) | 못 잼 | {"motion.zoom.scale_to":1.25,"motion.zoom.dur_s":0.35,"motion.zoom.ease":"out"} | {"final_ratio":1.2506} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: motion.zoom.scale_to, motion.zoom.dur_s, motion.z… |
| 정지(프리즈) [s2] | 못 잼 | {"start":6.8,"hold":0.7} | {"presence":"present","start":6.7667,"hold":0.7,"mean_diff":0.0132} | 같다 | 아니오 | t=6.80s |
| 계획에 없는 정지 화면 | — | [] | [] | 같다 | 아니오 | 소스도 정지해 있으면 제외; 판단 불가(소스 없음)면 포함 |
| 영상당 정지 횟수 | {"motion.freeze.max_per_video":"해당 없음(rule)"} | {"max":2} | {"count":1} | 같다 | 아니오 | — |
| 정지 길이 (레퍼런스 대비) | 못 잼 | {"motion.freeze.hold_s":0.7} | {"hold_s":0.7} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: motion.freeze.hold_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하… |
| 전환 종류·길이 (레퍼런스 대비) | 못 잼 | {"motion.transitions.default":"cut","motion.transitions.flash.dur_s":0.12,"motion.transit… | {"mode":"cut","flash_dur":0.1,"crossfade_dur":0.2519} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: motion.transitions.default, motion.transitions.fl… |

### 움직이는 장식(위치/밝기 각각)

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 장식 위치·이동 경로 [d_arrow·arrow] | 못 잼 | {"keyframes":[{"t":8.0,"x":543.0,"y":850.0,"w":null,"h":null,"rotation":null},{"t":10.4,"… | {"abs_err_p50":3.5,"abs_err_p90":5.1,"path_err_p90":1.9,"size":[70.0,118.0],"color":"#FC2… | 같다 | 아니오 | t=8.03s 위치는 밝기와 별도로 판정(보이는 프레임만) |
| 장식 밝기·깜빡임 [d_arrow·arrow] | 못 잼 | {"blink_hz":2.0,"start":8.0,"end":12.5} | {"blink_hz":2.0,"on_fraction":0.53,"on_events":9,"curve_sample":[[8.033,0.978],[8.1,0.978… | 같다 | 아니오 | t=8.00s 밝기 곡선은 위치와 별도로 판정 |
| 장식 스타일 [arrow] (레퍼런스 대비) | 못 잼 | {"decorations.arrow.color":"#FF2A2A","decorations.arrow.size_px":120,"decorations.arrow.o… | {"color":"#FC2827","blink_hz":2.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 5개: decorations.arrow.color, decorations.arrow.size_p… |

### 식별 요소

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 레퍼런스 채널명·식별 문구 없음 | {"identity_exclusions.forbidden_text":"해당 없음(rule… | {"absent":["조슈아매거진","조슈아 매거진","joshuamagazine","joshua magazine","JOSHUA MAGAZINE"]} | {"hits":[],"frames_ocr":25} | 같다 | 아니오 | 1초 간격 전체 프레임 + 각 클립 중간 OCR |
| 레퍼런스 로고 템플릿 없음 | {"identity_exclusions.logo_templates_dir":"해당 없음(… | {"templates_dir":"presets/joshuamagazine/reference/identity_templates"} | — | 못 잼 (참고) | 아니오 | 레퍼런스 로고 템플릿이 없어 로고 대조 못 함(레퍼런스 미확보) |
| 레퍼런스와 같은 녹화(영상) 재사용 없음 | — | {"same_recording_as_reference":false} | {"excluded":null,"matched_ref_video_id":null,"distance":null,"matched_keyframes":0,"n_key… | 못 잼 (참고) | 아니오 | 레퍼런스 영상 지문(exclusions.jsonl reference_footage) 없음 → 같은 녹화 여부 못 잼 (URL… |

### 로고 잔류

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 모서리·하단 잔여 글자(출처 표기·워터마크·원어 자막) | — | [] | {"persistent":[],"single_hits":[{"zone":"video_top_left","clip_id":"s1","text":"pe","time… | 같다 | 아니오 | 한 번만 잡힌 글자는 장면 속 글자/OCR 잡음일 수 있어 참고로만 표시 |
| 원본 오버레이 검출 기록 [v_class] | — | {"record":"warehouse/overlays/<sha256>.json","sha256":"7ca6f09cb32cf87c942cd9b56d5067a3ee… | — | 못 잼 (참고) | 아니오 | 출처 기록 없음(warehouse/overlays/7ca6f09cb32c….json) — `python -m shortkit… |
| 원본 오버레이 검출 기록 [v_pair] | — | {"record":"warehouse/overlays/<sha256>.json","sha256":"650166430c4bf9ddc470ac17a86d1fcbd6… | — | 못 잼 (참고) | 아니오 | 출처 기록 없음(warehouse/overlays/650166430c4b….json) — `python -m shortkit… |

### 얼굴·손·물체 가림

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 보호 영역 가림·잘림 [창가 남성 얼굴(앉음)·s1] | — | {"rect":[675.1,960.0,78.8,90.1],"resolution":[1080,1920],"t":[0.0,1.3],"covered":false,"v… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=0.00s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [창가 남성 손(책상 위)·s1] | — | {"rect":[686.4,1106.4,112.6,61.9],"resolution":[1080,1920],"t":[0.0,1.3],"covered":false,… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=0.00s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [창가 남성(일어서는 중)·s1] | — | {"rect":[661.0,809.4,211.1,267.4],"resolution":[1080,1920],"t":[1.3,3.5],"covered":false,… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=1.30s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [창가 남성 얼굴(선 자세)·s1] | — | {"rect":[752.5,816.4,119.6,119.6],"resolution":[1080,1920],"t":[3.5,4.0],"covered":false,… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=3.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [뒷줄 남성 얼굴(앉음)·s1] | — | {"rect":[453.4,904.4,84.4,98.5],"resolution":[1080,1920],"t":[0.0,4.0],"covered":false,"v… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=0.00s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [뒤 왼쪽 남성 얼굴·s1] | — | {"rect":[161.4,907.9,84.4,91.5],"resolution":[1080,1920],"t":[0.0,4.0],"covered":false,"v… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=0.00s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [왼쪽 남성 얼굴·s1] | — | {"rect":[0.0,964.2,84.0,105.6],"resolution":[1080,1920],"t":[0.0,4.0],"covered":false,"vi… | {"hits":[],"visible_frac":0.918} | 같다 | 아니오 | t=0.00s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [창가 남성 얼굴(선 자세)·s2] | — | {"rect":[748.3,847.4,95.7,95.7],"resolution":[1080,1920],"t":[4.0,4.2],"covered":false,"v… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=4.00s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [창가 남성(앉는 중)·s2] | — | {"rect":[675.1,841.8,168.9,213.9],"resolution":[1080,1920],"t":[4.2,6.5],"covered":false,… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=4.20s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [창가 남성 얼굴(다시 앉음)·s2] | — | {"rect":[675.1,943.1,84.4,101.3],"resolution":[1080,1920],"t":[6.5,6.8],"covered":false,"… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=6.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [뒷줄 남성 얼굴(앉음)·s2] | — | {"rect":[509.0,917.8,67.6,78.8],"resolution":[1080,1920],"t":[4.0,6.8],"covered":false,"v… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=4.00s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [뒤 왼쪽 남성 얼굴·s2] | — | {"rect":[275.4,920.6,67.6,73.2],"resolution":[1080,1920],"t":[4.0,6.8],"covered":false,"v… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=4.00s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [왼쪽 남성 얼굴·s2] | — | {"rect":[140.3,965.6,73.2,84.4],"resolution":[1080,1920],"t":[4.0,6.8],"covered":false,"v… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=4.00s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [창가 남성 얼굴(다시 앉음)·s3] | — | {"rect":[675.1,943.1,84.4,101.3],"resolution":[1080,1920],"t":[7.5,13.0],"covered":false,… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=7.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [뒷줄 남성 얼굴(앉음)·s3] | — | {"rect":[509.0,917.8,67.6,78.8],"resolution":[1080,1920],"t":[7.5,10.5],"covered":false,"… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=7.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [뒷줄 남성 손(듦)·s3] | — | {"rect":[472.4,892.4,39.4,50.7],"resolution":[1080,1920],"t":[7.6,10.3],"covered":false,"… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=7.60s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [뒷줄 남성(일어서는 중)·s3] | — | {"rect":[438.7,864.3,135.1,112.6],"resolution":[1080,1920],"t":[10.5,11.5],"covered":fals… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=10.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [뒷줄 남성 얼굴(선 자세)·s3] | — | {"rect":[433.0,839.0,56.3,61.9],"resolution":[1080,1920],"t":[11.5,13.0],"covered":false,… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=11.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [뒤 왼쪽 남성 얼굴·s3] | — | {"rect":[275.4,920.6,67.6,73.2],"resolution":[1080,1920],"t":[7.5,13.0],"covered":false,"… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=7.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [왼쪽 남성 얼굴·s3] | — | {"rect":[140.3,965.6,73.2,84.4],"resolution":[1080,1920],"t":[7.5,13.0],"covered":false,"… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=7.50s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [여성 얼굴·s4] | — | {"rect":[55.9,733.4,281.5,295.6],"resolution":[1080,1920],"t":[12.75,21.25],"covered":fal… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=12.75s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 보호 영역 가림·잘림 [남성 얼굴·s4] | — | {"rect":[625.9,719.3,281.5,281.5],"resolution":[1080,1920],"t":[12.75,21.25],"covered":fa… | {"hits":[],"visible_frac":1.0} | 같다 | 아니오 | t=12.75s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것(잘림 비율도 계획 좌표로 계산), 자막·장식 bbox 는 … |
| 얼굴 가림(얼굴 검출) | — | {"covered":0} | {"detector":"shortkit.clean.faces haar frontal+profile (shortkit.HaarCascade(numpy))","fr… | 같다 | 아니오 | 얼굴: 출력 프레임 + 같은 순간의 소스 프레임(자막이 덮은 얼굴은 출력에서 안 보임)을 캔버스 좌표로 옮겨 검출; 자막 상… |

### 음악 구간

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| BGM 곡·버전 일치(파형 대조) | 못 잼 | {"path":"assets/test/generated/music_bed_a.wav","track_id":null} | {"presence":"present","waveform_ncc":0.9181,"local_match":{"n":84,"q95":0.9999,"q70":0.99… | 같다 | 아니오 | 출력 믹스에서 계획한 음악 파일의 파형을 찾음 ／ is_match 4요소: 곡=같다, 버전=같다, 속도=같다, 구간=같다 |
| BGM 일치(곡 AND 버전 AND 속도 AND 구간, audio_bgm.is_match) | 못 잼 | {"track_id":"assets/test/generated/music_bed_a.wav","version":"file:assets/test/generated… | {"observed":{"track_id":"assets/test/generated/music_bed_a.wav","version":"file:assets/te… | 같다 | 아니오 | t=0.00s 곡=같다, 버전=같다, 속도=같다, 구간=같다 — 계획한 음원 파일의 파형이 출력에서 확인됨(같은 녹음 → 곡·버전 같음) |
| BGM 속도(버전) | 못 잼 | 1.0 | 1.0 | 같다 | 아니오 | 후보 템포 상위: [[1.0, 0.8094], [1.005, 0.256], [0.995, 0.2381], [0.99, 0.1… |
| BGM 사용 구간 | 못 잼 | {"section_start_s":12.0} | {"section_start_s":12.0,"used_section":[12.025,33.215],"runner_up":{"section_start_s":36.… | 같다 | 아니오 | t=0.00s 파형이 거의 똑같이 반복되는 곡이라 다른 위치도 같은 소리(상관 차 ≤ 0.005) — 구간 구별 한계 |
| BGM 페이드 인/아웃 | 못 잼 | {"fade_in_s":0.0,"fade_out_s":0.8} | {"fade_in_s":0.0,"fade_out_s":0.689,"audible_span":[0.025,21.215]} | 같다 (참고) | 아니오 | 0.05초 창 LS 이득 곡선에서 측정 |
| BGM 곡·버전·속도·구간 (레퍼런스 대비) | 못 잼 | {"audio.bgm.track_id":null,"audio.bgm.title":null,"audio.bgm.version":null,"audio.bgm.tem… | {"track_id":null,"title":null,"version":null,"tempo_ratio":1.0,"section_start_s":12.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 9개: audio.bgm.track_id, audio.bgm.title, audio.bgm.ve… |
| 보존 대사 구간의 BGM 덕킹 | 못 잼 | {"duck_ranges":[[10.0,12.3]],"depth_db":10.0} | {"ducked_ranges":[[9.945,12.444],[20.791,21.24]],"coverage":[1.0]} | 같다 | 아니오 | t=10.00s |
| 보존 대사 밖에서 BGM 낮춤 없음(효과음·컷 때문에 덕킹 금지) | {"audio.ducking.only_under_kept_dialogue":"해당 없음(… | {"ducking_only_in":[[10.0,12.3]]} | {"ducking_outside":[]} | 같다 | 아니오 | — |
| 덕킹은 원음이 실제로 들리는 곳에서만 | — | 덕킹 구간 ⊆ 원음 존재 구간 | {"ducks_without_original":[],"original_present":[[9.999,11.999]]} | 같다 | 아니오 | — |
| 덕킹 깊이 | 못 잼 | {"depth_db":-10.0} | {"depth_db":-10.0} | 같다 | 아니오 | — |
| 덕킹 깊이·속도 (레퍼런스 대비) | 못 잼 | {"audio.ducking.depth_db":10.0,"audio.ducking.attack_s":0.08,"audio.ducking.release_s":0.… | {"depth_db":-10.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: audio.ducking.depth_db, audio.ducking.attack_s, a… |
| 의도적 정적 6.80–7.45s (BGM 없음) | 못 잼 | {"range":[6.8,7.45],"bgm_db_rel":"≤ -30.0"} | {"max_bgm_db_rel":-120.0} | 같다 | 아니오 | t=6.80s |
| 계획에 없는 BGM 끊김 | — | [[6.8,7.45]] | [] | 같다 | 아니오 | — |

### 원음

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 보존 원음 [s3 10.00–12.30s] | 못 잼 | {"present":true,"gain_db":0.0,"stem":"raw","reason":"소스에 들어 있는 대사 한 줄(합성 TTS)을 살림 — 원음 보존… | {"presence":"present","present_fraction":1.0,"gain_db_mix_scale":-0.01} | 같다 | 아니오 | t=10.00s 원음 이득은 BGM 기준 믹스 척도 추정(BGM 없으면 없음) |
| 보존 원음 속 음악 제거 [s3] | {"audio.original.remove_embedded_music":"해당 없음(ru… | {"embedded_music_removed":true} | {"has_embedded_music":false,"stem":"raw","path":"assets/test/generated/classroom_voice.mp… | 같다 (참고) | 아니오 | 소스에 음악 없음(plan 기록) |
| 원음 OFF 구간에 원음 없음(기본 OFF) | {"audio.original.default":"해당 없음(rule)"} | {"kept_only":[[10.0,12.3]]} | {"presence_outside_kept":"absent","leak_windows":[],"sources_without_audio":[]} | 같다 | 아니오 | — |
| 보존 원음 크기·경계 (레퍼런스 대비) | 못 잼 | {"audio.original.keep_gain_db":0.0,"audio.original.fade_s":0.04} | {"gain_db":-0.01} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: audio.original.keep_gain_db, audio.original.fade_… |

### 효과음 종류별 개수

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 효과음 [fx1·whoosh] 위치 | — | {"t":1.25,"type":"whoosh"} | {"t":1.2522,"ncc":0.915} | 같다 | 아니오 | t=1.25s |
| 효과음 [fx1·whoosh] 크기 | 못 잼 | {"gain_db":-12.0} | {"gain_db_mix_scale":-15.97,"reference":"local_bgm"} | 다르다 (참고) | 아니오 | t=1.25s |
| 효과음 [fx2·click] 위치 | — | {"t":6.8,"type":"click"} | {"t":6.8,"ncc":0.994} | 같다 | 아니오 | t=6.80s |
| 효과음 [fx2·click] 크기 | 못 잼 | {"gain_db":-8.0} | {"gain_db_mix_scale":-11.05,"reference":"bgm_plateau (BGM 없음/정적 구간)"} | 다르다 (참고) | 아니오 | t=6.80s |
| 효과음 [fx3·pop] 위치 | — | {"t":7.75,"type":"pop"} | {"t":7.7501,"ncc":0.991} | 같다 | 아니오 | t=7.75s |
| 효과음 [fx3·pop] 크기 | 못 잼 | {"gain_db":-8.0} | {"gain_db_mix_scale":-11.74,"reference":"local_bgm"} | 다르다 (참고) | 아니오 | t=7.75s |
| 효과음 [fx4·ding] 위치 | — | {"t":10.9,"type":"ding"} | {"t":10.9,"ncc":0.998} | 같다 | 아니오 | t=10.90s |
| 효과음 [fx4·ding] 크기 | 못 잼 | {"gain_db":-8.0} | {"gain_db_mix_scale":-11.91,"reference":"local_bgm"} | 다르다 (참고) | 아니오 | t=10.90s |
| 효과음 [fx5·boing] 위치 | — | {"t":15.0,"type":"boing"} | {"t":15.0,"ncc":0.992} | 같다 | 아니오 | t=15.00s |
| 효과음 [fx5·boing] 크기 | 못 잼 | {"gain_db":-8.0} | {"gain_db_mix_scale":-11.19,"reference":"local_bgm"} | 다르다 (참고) | 아니오 | t=15.00s |
| 효과음 개수 [boing] (계획 대비) | — | 1 | 1 | 같다 | 아니오 | t=15.00s |
| 효과음 개수 [click] (계획 대비) | — | 1 | 1 | 같다 | 아니오 | t=6.80s |
| 효과음 개수 [ding] (계획 대비) | — | 1 | 1 | 같다 | 아니오 | t=10.90s |
| 효과음 개수 [pop] (계획 대비) | — | 1 | 1 | 같다 | 아니오 | t=7.75s |
| 효과음 개수 [whoosh] (계획 대비) | — | 1 | 1 | 같다 | 아니오 | t=1.25s |
| 효과음 종류별 개수 (레퍼런스 포맷 범위 대비) | 못 잼 | 레퍼런스 카탈로그의 포맷별 p10–p90 | {"whoosh":1,"click":1,"pop":1,"ding":1,"boing":1} | 못 잼 (참고) | 아니오 | sfx_catalog.json 미측정: 2026-09-24: 레퍼런스 최신 50편 다운로드 불가(youtube 차단), De… |
| 효과음 크기 (레퍼런스 대비) | 못 잼 | {"audio.sfx.gain_db_default":-8.0} | {"gain_db":-11.74} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: audio.sfx.gain_db_default — 출력이 임시값과 같아도 레퍼런스와 같다… |

### 사건과의 시차

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 효과음 [fx1] 사건과의 시차 (창가 남성이 일어서기 시작함(확대 시) | {"audio.sfx.max_event_offset_s":"해당 없음(rule)"} | {"event_t":1.3,"max_abs_offset":0.3} | {"sfx_t":1.2522,"offset":-0.048} | 같다 | 아니오 | t=1.25s 사건 시각은 plan 의 선언(화면 사건), 효과음 시각은 출력에서 측정 |
| 효과음 [fx2] 사건과의 시차 (다시 앉은 순간 화면이 멈춤) | {"audio.sfx.max_event_offset_s":"해당 없음(rule)"} | {"event_t":6.8,"max_abs_offset":0.3} | {"sfx_t":6.8,"offset":0.0} | 같다 | 아니오 | t=6.80s 사건 시각은 plan 의 선언(화면 사건), 효과음 시각은 출력에서 측정 |
| 효과음 [fx3] 사건과의 시차 (뒷줄 남성이 손을 들어 올림) | {"audio.sfx.max_event_offset_s":"해당 없음(rule)"} | {"event_t":7.75,"max_abs_offset":0.3} | {"sfx_t":7.7501,"offset":0.0} | 같다 | 아니오 | t=7.75s 사건 시각은 plan 의 선언(화면 사건), 효과음 시각은 출력에서 측정 |
| 효과음 [fx4] 사건과의 시차 (뒷줄 남성이 자리에서 일어섬) | {"audio.sfx.max_event_offset_s":"해당 없음(rule)"} | {"event_t":11.0,"max_abs_offset":0.3} | {"sfx_t":10.9,"offset":-0.1} | 같다 | 아니오 | t=10.90s 사건 시각은 plan 의 선언(화면 사건), 효과음 시각은 출력에서 측정 |
| 효과음 [fx5] 사건과의 시차 (두 사람이 동시에 고개를 옆으로 기울) | {"audio.sfx.max_event_offset_s":"해당 없음(rule)"} | {"event_t":15.05,"max_abs_offset":0.3} | {"sfx_t":15.0,"offset":-0.05} | 같다 | 아니오 | t=15.00s 사건 시각은 plan 의 선언(화면 사건), 효과음 시각은 출력에서 측정 |

### 사건 없는 효과음 0

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 사건 없는 효과음 0 | {"audio.sfx.require_event":"해당 없음(rule)"} | 0 | {"count":0,"items":[]} | 같다 | 아니오 | — |
| 알려진 소리로 설명되지 않는 소리 시작점 | — | 0 | {"count":0,"onsets":[]} | 같다 | 아니오 | BGM·원음·검출된 효과음을 뺀 잔차에서 급격한 에너지 상승(보존 원음 구간 제외) |

### 음량

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 통합 음량(LUFS)·트루피크 | 못 잼 | {"integrated_lufs":-14.0,"true_peak_db":-1.5} | {"integrated_lufs":-14.9,"lra":2.0,"true_peak_db":-2.0} | 같다 | 아니오 | — |
| 음량 (레퍼런스 대비) | 못 잼 | {"audio.loudness.integrated_lufs":-14.0,"audio.loudness.true_peak_db":-1.5} | {"integrated_lufs":-14.9} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: audio.loudness.integrated_lufs, audio.loudness.tr… |

### 구성·표지

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 영상 길이 | — | 21.25 | 21.267 | 같다 | 아니오 | — |
| 영상 길이 (레퍼런스 분포 대비) | 못 잼 | {"structure.duration_s.p10":null,"structure.duration_s.p50":null,"structure.duration_s.p9… | {"duration":21.27} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: structure.duration_s.p10, structure.duration_s.p5… |
| 첫 자막 시각 (레퍼런스 대비) | 못 잼 | {"structure.first_caption_at_s":0.0} | {"first_caption_at_s":0.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: structure.first_caption_at_s — 출력이 임시값과 같아도 레퍼런스와… |
| 표지 프레임에 제목 문구 표시 | 못 잼 | {"t":0.0,"text":"움직임 테스트 영상","role":"title"} | {"ocr":"움직임 테스트 영상","similarity":1.0,"role_caption_visible":true} | 같다 (참고) | 아니오 | t=0.00s |
| 표지 구성 (레퍼런스 대비) | 못 잼 | {"cover.source":"first_frame","cover.text_role":"title"} | {"text_role_visible":true} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: cover.source, cover.text_role — 출력이 임시값과 같아도 레퍼런스… |

## 못 잼 항목과 이유

- 화면 해상도·프레임레이트 (레퍼런스 대비) (`canvas.format:format_ref`): 레퍼런스 미측정(임시값) 키 3개: canvas.width, canvas.height, canvas.fps — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치
- 영상 영역 (레퍼런스 대비) (`canvas.video_region:region_ref`): 레퍼런스 미측정(임시값) 키 5개: canvas.video_region.x, canvas.video_region.y, canvas.video_region.w, canvas.video_region.h, canvas.video_region.fit — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치
- 배경 (레퍼런스 대비) (`canvas.background:background_ref`): 레퍼런스 미측정(임시값) 키 3개: canvas.background.type, canvas.background.color, canvas.background.blur_sigma — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 화면 비율·영상 영역·여백이 레퍼런스와 다를 수 있음 → 구도 불일치
- **필수** 자막 글꼴 [c_sit3·situation] "뒷줄 남성이 손을 든다" (`caption.font:c_sit3`): 판정: 유사(similar, 동일 확정 불가) — 같다고 쓰지 않음. IoU 0.963 < 천장 p10 0.966; 차순위 대비 차이 +0.051 > 잡음 0.006; 글자별 검사 통과 — 제작 영향: 글꼴이 맞는지 확인하지 못함 → 글자 인상이 다를 수 있음
- 자막 이모지 사용 (`caption.tone:emoji`): 출력 화면에서 이모지를 판별하는 방법 없음(OCR 미지원) — 제작 영향: 자막 문구·말투를 확인하지 못함
- 자막 위치 [description] (레퍼런스 대비) (`caption.position:description_ref`): 레퍼런스 미측정(임시값) 키 5개: text.roles.description.anchor.x, text.roles.description.anchor.y, text.roles.description.anchor.align, text.roles.description.anchor.valign, text.roles.description.max_width_px — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 제목/자막 위치 불일치
- 자막 크기 [description] (레퍼런스 대비) (`caption.size:description_ref`): 레퍼런스 미측정(임시값) 키 4개: text.roles.description.size_px, text.roles.description.line_spacing, text.roles.description.max_lines, text.roles.description.max_chars_per_line — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글자 크기 불일치 → 줄 수·가림 영역 변화
- 자막 색·외곽선·박스 [description] (레퍼런스 대비) (`caption.style:description_ref`): 레퍼런스 미측정(임시값) 키 11개: text.roles.description.color, text.roles.description.highlight_color, text.roles.description.outline_px, text.roles.description.outline_color, text.roles.description.shadow_px, text.roles.description.shadow_color … — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글자 색 불일치
- 자막 글꼴 [description] (레퍼런스 대비) (`caption.font:description_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.description.font_name, text.roles.description.bold — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글꼴이 레퍼런스와 다를 수 있음 → 글자 인상·폭·줄바꿈 불일치
- 자막 표시 시간 [description] (레퍼런스 대비) (`caption.timing:description_ref`): 레퍼런스 미측정(임시값) 키 3개: text.roles.description.timing.lead_s, text.roles.description.timing.min_dur_s, text.roles.description.persist — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 자막 등장 타이밍 불일치
- 자막 등장·퇴장 모션 [description] (레퍼런스 대비) (`caption.motion:description_ref`): 레퍼런스 미측정(임시값) 키 6개: text.roles.description.motion_in.type, text.roles.description.motion_in.dur_s, text.roles.description.motion_in.scale_from, text.roles.description.motion_in.offset_px, text.roles.description.motion_out.type, text.roles.description.motion_out.dur_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 자막 등장·퇴장 모션 불일치
- 자막 위치 [dialogue] (레퍼런스 대비) (`caption.position:dialogue_ref`): 레퍼런스 미측정(임시값) 키 5개: text.roles.dialogue.anchor.x, text.roles.dialogue.anchor.y, text.roles.dialogue.anchor.align, text.roles.dialogue.anchor.valign, text.roles.dialogue.max_width_px — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 제목/자막 위치 불일치
- 자막 크기 [dialogue] (레퍼런스 대비) (`caption.size:dialogue_ref`): 레퍼런스 미측정(임시값) 키 4개: text.roles.dialogue.size_px, text.roles.dialogue.line_spacing, text.roles.dialogue.max_lines, text.roles.dialogue.max_chars_per_line — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글자 크기 불일치 → 줄 수·가림 영역 변화
- 자막 색·외곽선·박스 [dialogue] (레퍼런스 대비) (`caption.style:dialogue_ref`): 레퍼런스 미측정(임시값) 키 11개: text.roles.dialogue.color, text.roles.dialogue.highlight_color, text.roles.dialogue.outline_px, text.roles.dialogue.outline_color, text.roles.dialogue.shadow_px, text.roles.dialogue.shadow_color … — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글자 색 불일치
- 자막 글꼴 [dialogue] (레퍼런스 대비) (`caption.font:dialogue_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.dialogue.font_name, text.roles.dialogue.bold — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글꼴이 레퍼런스와 다를 수 있음 → 글자 인상·폭·줄바꿈 불일치
- 자막 표시 시간 [dialogue] (레퍼런스 대비) (`caption.timing:dialogue_ref`): 레퍼런스 미측정(임시값) 키 3개: text.roles.dialogue.timing.lead_s, text.roles.dialogue.timing.min_dur_s, text.roles.dialogue.persist — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 자막 등장 타이밍 불일치
- 자막 등장·퇴장 모션 [dialogue] (레퍼런스 대비) (`caption.motion:dialogue_ref`): 레퍼런스 미측정(임시값) 키 6개: text.roles.dialogue.motion_in.type, text.roles.dialogue.motion_in.dur_s, text.roles.dialogue.motion_in.scale_from, text.roles.dialogue.motion_in.offset_px, text.roles.dialogue.motion_out.type, text.roles.dialogue.motion_out.dur_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 자막 등장·퇴장 모션 불일치
- 자막 위치 [reaction] (레퍼런스 대비) (`caption.position:reaction_ref`): 레퍼런스 미측정(임시값) 키 5개: text.roles.reaction.anchor.x, text.roles.reaction.anchor.y, text.roles.reaction.anchor.align, text.roles.reaction.anchor.valign, text.roles.reaction.max_width_px — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 제목/자막 위치 불일치
- 자막 크기 [reaction] (레퍼런스 대비) (`caption.size:reaction_ref`): 레퍼런스 미측정(임시값) 키 4개: text.roles.reaction.size_px, text.roles.reaction.line_spacing, text.roles.reaction.max_lines, text.roles.reaction.max_chars_per_line — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글자 크기 불일치 → 줄 수·가림 영역 변화
- 자막 색·외곽선·박스 [reaction] (레퍼런스 대비) (`caption.style:reaction_ref`): 레퍼런스 미측정(임시값) 키 11개: text.roles.reaction.color, text.roles.reaction.highlight_color, text.roles.reaction.outline_px, text.roles.reaction.outline_color, text.roles.reaction.shadow_px, text.roles.reaction.shadow_color … — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글자 색 불일치
- 자막 글꼴 [reaction] (레퍼런스 대비) (`caption.font:reaction_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.reaction.font_name, text.roles.reaction.bold — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글꼴이 레퍼런스와 다를 수 있음 → 글자 인상·폭·줄바꿈 불일치
- 자막 표시 시간 [reaction] (레퍼런스 대비) (`caption.timing:reaction_ref`): 레퍼런스 미측정(임시값) 키 3개: text.roles.reaction.timing.lead_s, text.roles.reaction.timing.min_dur_s, text.roles.reaction.persist — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 자막 등장 타이밍 불일치
- 자막 등장·퇴장 모션 [reaction] (레퍼런스 대비) (`caption.motion:reaction_ref`): 레퍼런스 미측정(임시값) 키 6개: text.roles.reaction.motion_in.type, text.roles.reaction.motion_in.dur_s, text.roles.reaction.motion_in.scale_from, text.roles.reaction.motion_in.offset_px, text.roles.reaction.motion_out.type, text.roles.reaction.motion_out.dur_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 자막 등장·퇴장 모션 불일치
- 자막 위치 [situation] (레퍼런스 대비) (`caption.position:situation_ref`): 레퍼런스 미측정(임시값) 키 5개: text.roles.situation.anchor.x, text.roles.situation.anchor.y, text.roles.situation.anchor.align, text.roles.situation.anchor.valign, text.roles.situation.max_width_px — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 제목/자막 위치 불일치
- 자막 크기 [situation] (레퍼런스 대비) (`caption.size:situation_ref`): 레퍼런스 미측정(임시값) 키 4개: text.roles.situation.size_px, text.roles.situation.line_spacing, text.roles.situation.max_lines, text.roles.situation.max_chars_per_line — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글자 크기 불일치 → 줄 수·가림 영역 변화
- 자막 색·외곽선·박스 [situation] (레퍼런스 대비) (`caption.style:situation_ref`): 레퍼런스 미측정(임시값) 키 11개: text.roles.situation.color, text.roles.situation.highlight_color, text.roles.situation.outline_px, text.roles.situation.outline_color, text.roles.situation.shadow_px, text.roles.situation.shadow_color … — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글자 색 불일치
- 자막 글꼴 [situation] (레퍼런스 대비) (`caption.font:situation_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.situation.font_name, text.roles.situation.bold — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글꼴이 레퍼런스와 다를 수 있음 → 글자 인상·폭·줄바꿈 불일치
- 자막 표시 시간 [situation] (레퍼런스 대비) (`caption.timing:situation_ref`): 레퍼런스 미측정(임시값) 키 3개: text.roles.situation.timing.lead_s, text.roles.situation.timing.min_dur_s, text.roles.situation.persist — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 자막 등장 타이밍 불일치
- 자막 등장·퇴장 모션 [situation] (레퍼런스 대비) (`caption.motion:situation_ref`): 레퍼런스 미측정(임시값) 키 6개: text.roles.situation.motion_in.type, text.roles.situation.motion_in.dur_s, text.roles.situation.motion_in.scale_from, text.roles.situation.motion_in.offset_px, text.roles.situation.motion_out.type, text.roles.situation.motion_out.dur_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 자막 등장·퇴장 모션 불일치
- 자막 위치 [speaker] (레퍼런스 대비) (`caption.position:speaker_ref`): 레퍼런스 미측정(임시값) 키 5개: text.roles.speaker.anchor.x, text.roles.speaker.anchor.y, text.roles.speaker.anchor.align, text.roles.speaker.anchor.valign, text.roles.speaker.max_width_px — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 제목/자막 위치 불일치
- 자막 크기 [speaker] (레퍼런스 대비) (`caption.size:speaker_ref`): 레퍼런스 미측정(임시값) 키 4개: text.roles.speaker.size_px, text.roles.speaker.line_spacing, text.roles.speaker.max_lines, text.roles.speaker.max_chars_per_line — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글자 크기 불일치 → 줄 수·가림 영역 변화
- 자막 색·외곽선·박스 [speaker] (레퍼런스 대비) (`caption.style:speaker_ref`): 레퍼런스 미측정(임시값) 키 11개: text.roles.speaker.color, text.roles.speaker.highlight_color, text.roles.speaker.outline_px, text.roles.speaker.outline_color, text.roles.speaker.shadow_px, text.roles.speaker.shadow_color … — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글자 색 불일치
- 자막 글꼴 [speaker] (레퍼런스 대비) (`caption.font:speaker_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.speaker.font_name, text.roles.speaker.bold — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글꼴이 레퍼런스와 다를 수 있음 → 글자 인상·폭·줄바꿈 불일치
- 자막 표시 시간 [speaker] (레퍼런스 대비) (`caption.timing:speaker_ref`): 레퍼런스 미측정(임시값) 키 3개: text.roles.speaker.timing.lead_s, text.roles.speaker.timing.min_dur_s, text.roles.speaker.persist — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 자막 등장 타이밍 불일치
- 자막 등장·퇴장 모션 [speaker] (레퍼런스 대비) (`caption.motion:speaker_ref`): 레퍼런스 미측정(임시값) 키 6개: text.roles.speaker.motion_in.type, text.roles.speaker.motion_in.dur_s, text.roles.speaker.motion_in.scale_from, text.roles.speaker.motion_in.offset_px, text.roles.speaker.motion_out.type, text.roles.speaker.motion_out.dur_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 자막 등장·퇴장 모션 불일치
- 자막 위치 [title] (레퍼런스 대비) (`caption.position:title_ref`): 레퍼런스 미측정(임시값) 키 5개: text.roles.title.anchor.x, text.roles.title.anchor.y, text.roles.title.anchor.align, text.roles.title.anchor.valign, text.roles.title.max_width_px — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 제목/자막 위치 불일치
- 자막 크기 [title] (레퍼런스 대비) (`caption.size:title_ref`): 레퍼런스 미측정(임시값) 키 4개: text.roles.title.size_px, text.roles.title.line_spacing, text.roles.title.max_lines, text.roles.title.max_chars_per_line — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글자 크기 불일치 → 줄 수·가림 영역 변화
- 자막 색·외곽선·박스 [title] (레퍼런스 대비) (`caption.style:title_ref`): 레퍼런스 미측정(임시값) 키 11개: text.roles.title.color, text.roles.title.highlight_color, text.roles.title.outline_px, text.roles.title.outline_color, text.roles.title.shadow_px, text.roles.title.shadow_color … — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글자 색 불일치
- 자막 글꼴 [title] (레퍼런스 대비) (`caption.font:title_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.title.font_name, text.roles.title.bold — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 글꼴이 레퍼런스와 다를 수 있음 → 글자 인상·폭·줄바꿈 불일치
- 자막 표시 시간 [title] (레퍼런스 대비) (`caption.timing:title_ref`): 레퍼런스 미측정(임시값) 키 3개: text.roles.title.timing.lead_s, text.roles.title.timing.min_dur_s, text.roles.title.persist — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 자막 등장 타이밍 불일치
- 자막 등장·퇴장 모션 [title] (레퍼런스 대비) (`caption.motion:title_ref`): 레퍼런스 미측정(임시값) 키 6개: text.roles.title.motion_in.type, text.roles.title.motion_in.dur_s, text.roles.title.motion_in.scale_from, text.roles.title.motion_in.offset_px, text.roles.title.motion_out.type, text.roles.title.motion_out.dur_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 자막 등장·퇴장 모션 불일치
- 자막 말투 (레퍼런스 대비) (`caption.tone:tone_ref`): 레퍼런스 미측정(임시값) 키 4개: text.tone.register, text.tone.sentence_end_examples, text.tone.emoji, text.tone.notes — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 자막 말투가 레퍼런스와 다를 수 있음
- 줌 배율·길이 (레퍼런스 대비) (`video.zoom:zoom_ref`): 레퍼런스 미측정(임시값) 키 3개: motion.zoom.scale_to, motion.zoom.dur_s, motion.zoom.ease — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 확대·정지·전환의 크기/길이 불일치
- 정지 길이 (레퍼런스 대비) (`video.freeze:freeze_ref`): 레퍼런스 미측정(임시값) 키 1개: motion.freeze.hold_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 확대·정지·전환의 크기/길이 불일치
- 전환 종류·길이 (레퍼런스 대비) (`video.transitions:transitions_ref`): 레퍼런스 미측정(임시값) 키 4개: motion.transitions.default, motion.transitions.flash.dur_s, motion.transitions.flash.color, motion.transitions.crossfade.dur_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 확대·정지·전환의 크기/길이 불일치
- 장식 스타일 [arrow] (레퍼런스 대비) (`decor.position:d_arrow_ref`): 레퍼런스 미측정(임시값) 키 5개: decorations.arrow.color, decorations.arrow.size_px, decorations.arrow.outline_px, decorations.arrow.outline_color, decorations.arrow.blink_hz — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 화살표·원 등 장식 스타일 불일치
- 레퍼런스 로고 템플릿 없음 (`identity.logo_templates:all`): 레퍼런스 로고 템플릿이 없어 로고 대조 못 함(레퍼런스 미확보) — 제작 영향: 레퍼런스 채널 식별 요소·같은 녹화 재사용 여부를 확인하지 못함 → 게시 위험
- 레퍼런스와 같은 녹화(영상) 재사용 없음 (`identity.reference_footage:all`): 레퍼런스 영상 지문(exclusions.jsonl reference_footage) 없음 → 같은 녹화 여부 못 잼 (URL 규칙만 확인) — 제작 영향: 레퍼런스 채널 식별 요소·같은 녹화 재사용 여부를 확인하지 못함 → 게시 위험
- 원본 오버레이 검출 기록 [v_class] (`clean.residual:prov:v_class`): 출처 기록 없음(warehouse/overlays/7ca6f09cb32c….json) — `python -m shortkit clean detect --source assets/test/generated/classroom_voice.mp4` — 원본 로고·오버레이가 남았는지 출처 기록으로 대조할 수 없음(모서리 OCR 검사만 적용) — 제작 영향: 원본 로고·출처 표기가 남아 있는지 확인하지 못함 → 게시 위험
- 원본 오버레이 검출 기록 [v_pair] (`clean.residual:prov:v_pair`): 출처 기록 없음(warehouse/overlays/650166430c4b….json) — `python -m shortkit clean detect --source assets/test/generated/video/head-pose-face-detection-female-and-male.mp4` — 원본 로고·오버레이가 남았는지 출처 기록으로 대조할 수 없음(모서리 OCR 검사만 적용) — 제작 영향: 원본 로고·출처 표기가 남아 있는지 확인하지 못함 → 게시 위험
- BGM 곡·버전·속도·구간 (레퍼런스 대비) (`audio.bgm:bgm_ref`): 레퍼런스 미측정(임시값) 키 9개: audio.bgm.track_id, audio.bgm.title, audio.bgm.version, audio.bgm.tempo_ratio, audio.bgm.section_start_s, audio.bgm.gain_db … — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. audio_bgm.is_match: 곡(track_id/제목)·버전·속도·구간이 모두 레퍼런스와 같아야 같다; 계획이 파일 경로로 BGM 을 지정해 라이브러리 곡 id 가 없음 → 곡 일치는 못 잼 — 제작 영향: BGM 곡/버전/속도/구간/크기 불일치 → 음악 일치 판정 불가
- 덕킹 깊이·속도 (레퍼런스 대비) (`audio.ducking:ducking_ref`): 레퍼런스 미측정(임시값) 키 3개: audio.ducking.depth_db, audio.ducking.attack_s, audio.ducking.release_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 보존 대사 구간의 BGM 덕킹 깊이·속도 불일치
- 보존 원음 크기·경계 (레퍼런스 대비) (`audio.original:orig_ref`): 레퍼런스 미측정(임시값) 키 2개: audio.original.keep_gain_db, audio.original.fade_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 보존 원음 크기 불일치
- 효과음 종류별 개수 (레퍼런스 포맷 범위 대비) (`audio.sfx.count:catalog`): sfx_catalog.json 미측정: 2026-09-24: 레퍼런스 최신 50편 다운로드 불가(youtube 차단), Demucs 가중치 호스트(dl.fbaipublicfiles.com) 차단 — 제작 영향: 레퍼런스와의 일치 여부를 판정할 수 없음
- 효과음 크기 (레퍼런스 대비) (`audio.sfx.placement:sfx_gain_ref`): 레퍼런스 미측정(임시값) 키 1개: audio.sfx.gain_db_default — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 효과음 크기 불일치
- 음량 (레퍼런스 대비) (`audio.loudness:loudness_ref`): 레퍼런스 미측정(임시값) 키 2개: audio.loudness.integrated_lufs, audio.loudness.true_peak_db — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 최종 음량 불일치
- 영상 길이 (레퍼런스 분포 대비) (`structure.duration:duration_ref`): 레퍼런스 미측정(임시값) 키 4개: structure.duration_s.p10, structure.duration_s.p50, structure.duration_s.p90, structure.duration_s.n — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 영상 길이·전개 구조 불일치
- 첫 자막 시각 (레퍼런스 대비) (`structure.duration:first_caption_ref`): 레퍼런스 미측정(임시값) 키 1개: structure.first_caption_at_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 영상 길이·전개 구조 불일치
- 표지 구성 (레퍼런스 대비) (`cover.frame:cover_ref`): 레퍼런스 미측정(임시값) 키 2개: cover.source, cover.text_role — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. — 제작 영향: 표지 구성 불일치

## 비교 시트
- `episodes/test-pipeline-001/qa/compare_sheet.png`
- `episodes/test-pipeline-001/qa/compare_sheet_p02.png`

## 결함 기록 (defects.jsonl)
- 열림 7 / 이번에 해결 확인 3 / 재발 0 / 새로 등록 2

---
판정 기준: 같다=허용오차 안, 다르다=허용오차 밖, 못 잼=측정 불가(완료로 치지 않음). 레퍼런스 열의 '못 잼'은 레퍼런스에서 측정되지 않은 임시값이라는 뜻이다.

오디오 판정은 모두 기계 측정(파형 대조·최소제곱·정합 필터·EBU R128)이다. 사람이 직접 들어 본 청취 확인은 이 보고서에 포함되어 있지 않다.
