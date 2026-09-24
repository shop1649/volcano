# QA 보고서 — test-qa-good

- 측정 대상: `episodes/test-qa-good/output/test-qa-good.mp4` (sha256 `0d83f4ecc33c3487…`, 720x1280, 7.80s)
- 원칙: 최종 MP4 만 측정(타임라인/코드가 맞다고 출력이 맞다고 보지 않음)
- 프리셋: joshuamagazine-v1 / 포맷 UNCLASSIFIED / 모드 **test**
- 레퍼런스: 없음(못 잼)
- 측정 시각: 2026-09-24T18:29:28+00:00 / 도구: OCR=5.3.4, 얼굴검출=얼굴 검출기 없음: 이 OpenCV 빌드(cv2 5.0.0)에는 Haar cascade(CascadeClassifier/cv2.data)가 없고, 얼굴 모델 파일(assets/models/face_detection_yunet*.onnx 또는 $SHORTKIT_FACE_MODEL)도 없음

## 최종 관문: **불합격**
- ✗ G1: 의도하지 않은 차이(다르다) 1건 — audio.sfx.placement:fx2:gain
- ✗ G2: 필수 항목 못 잼 3건 — 못 잼은 완료가 아님 — caption.font:k1, caption.text:r1, video.mapping:c3
- △ P1: 프리셋 미측정(임시값) 키 251개
- △ P2: 레퍼런스 대비 못 잼 47건
- △ P3: 테스트 모드 출력(파이프라인 검증용) — 게시 불가

## 요약
- 전체 144행: 같다 89 / 다르다 1 (의도한 변경 0, 의도하지 않음 1) / 못 잼 54
- 계획 대비(출력이 계획대로인가): {'same': 89, 'unmeasured': 7, 'different': 1}
- 레퍼런스 대비(레퍼런스와 같은가): {'unmeasured': 47}
- 프리셋 미측정(임시값) 키: 251개

| 분류 | 같다 | 다르다 | 못 잼 |
|---|---:|---:|---:|
| 화면 구성 | 4 | 0 | 3 |
| 글자 위치 | 10 | 0 | 10 |
| 자막 내용·말투 | 5 | 0 | 3 |
| 자막 스타일 | 5 | 0 | 5 |
| 폰트 | 4 | 0 | 6 |
| 자막 타이밍 | 5 | 0 | 5 |
| 자막 등장·퇴장 모션 | 5 | 0 | 5 |
| 컷 | 5 | 0 | 1 |
| 모션(확대·정지·전환) | 8 | 0 | 4 |
| 움직이는 장식(위치/밝기 각각) | 2 | 0 | 1 |
| 식별 요소 | 1 | 0 | 1 |
| 로고 잔류 | 2 | 0 | 0 |
| 얼굴·손·물체 가림 | 1 | 0 | 1 |
| 음악 구간 | 10 | 0 | 2 |
| 원음 | 2 | 0 | 1 |
| 효과음 종류별 개수 | 11 | 1 | 2 |
| 사건과의 시차 | 4 | 0 | 0 |
| 사건 없는 효과음 0 | 2 | 0 | 0 |
| 음량 | 1 | 0 | 1 |
| 구성·표지 | 2 | 0 | 3 |

## 검사표

### 화면 구성

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 화면 해상도·프레임레이트 | 못 잼 | {"width":720,"height":1280,"fps":30.0} | {"width":720,"height":1280,"fps":30.0} | 같다 | 아니오 | — |
| 화면 해상도·프레임레이트 (레퍼런스 대비) | 못 잼 | {"canvas.width":1080,"canvas.height":1920,"canvas.fps":30} | {"width":720,"height":1280,"fps":30.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: canvas.width, canvas.height, canvas.fps — 출력이 임시값… |
| 영상 영역 위치·크기 | 못 잼 | {"rect":[0.0,437.0,720.0,405.0],"resolution":[720,1280]} | {"rect":[0.0,436.0,720.0,406.7],"resolution":[720,1280]} | 같다 (참고) | 아니오 | 움직이는 화소·배경색 차이로 측정(휴리스틱) |
| 영상 영역 (레퍼런스 대비) | 못 잼 | {"canvas.video_region.x":0,"canvas.video_region.y":656,"canvas.video_region.w":1080,"canv… | {"rect":[0.0,436.0,720.0,406.7]} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 5개: canvas.video_region.x, canvas.video_region.y, can… |
| 배경(색/소스 블러) | 못 잼 | {"type":"color","color":"#000000"} | {"type":"color","color":"#000000","temporal_std":0.0} | 같다 (참고) | 아니오 | blur_sigma 는 측정하지 않음 |
| 배경 (레퍼런스 대비) | 못 잼 | {"canvas.background.type":"color","canvas.background.color":"#000000","canvas.background.… | {"type":"color","color":"#000000","temporal_std":0.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: canvas.background.type, canvas.background.color, … |
| 자막이 안전 여백 안에 있음 | 못 잼 | {"left":54,"right":54,"top":110,"bottom":250} | {"min_margin_px":{"left":140,"top":197,"right":118,"bottom":304}} | 같다 (참고) | 아니오 | — |

### 글자 위치

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 위치 [t1·title] "실험 영상 모음" | — | {"center":[359.5,223.0],"bbox":[187.0,193.0,345.0,60.0],"resolution":[720,1280]} | {"center":[359.5,223.0],"bbox":[191,197,337,52],"resolution":[720,1280],"dx":0.0,"dy":0.0} | 같다 | 아니오 | t=0.12s [프레임](frames/cap_t1_0000120.png) 에피소드 위치 지정(pos) |
| 자막 크기·줄 수 [t1·title] "실험 영상 모음" | 못 잼 | {"fill_h":52.0,"lines":1,"max_width_px":980.0,"max_lines":2,"size_px":56.0} | {"fill_h":52,"fill_w":337,"lines":1,"size_px_est":56.0} | 같다 | 아니오 | t=0.12s [프레임](frames/cap_t1_0000120.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [s1·situation] "두 사람이 고개를 돌린다" | — | {"center":[360.0,955.5],"bbox":[136.0,931.0,448.0,49.0],"resolution":[720,1280]} | {"center":[360.0,956.0],"bbox":[140,936,440,40],"resolution":[720,1280],"dx":0.0,"dy":0.5} | 같다 | 아니오 | t=1.04s [프레임](frames/cap_s1_0001040.png) 에피소드 위치 지정(pos) |
| 자막 크기·줄 수 [s1·situation] "두 사람이 고개를 돌린다" | 못 잼 | {"fill_h":41.0,"lines":1,"max_width_px":960.0,"max_lines":2,"size_px":44.0} | {"fill_h":40,"fill_w":440,"lines":1,"size_px_est":42.9} | 같다 | 아니오 | t=1.04s [프레임](frames/cap_s1_0001040.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [k1·speaker] "선생님" | — | {"center":[558.5,481.5],"bbox":[516.0,468.0,85.0,27.0],"resolution":[720,1280]} | {"center":[559.0,481.5],"bbox":[516,468,86,27],"resolution":[720,1280],"dx":0.5,"dy":0.0} | 같다 | 아니오 | t=3.07s [프레임](frames/cap_k1_0003070.png) 에피소드 위치 지정(pos) |
| 자막 크기·줄 수 [k1·speaker] "선생님" | 못 잼 | {"fill_h":27.0,"lines":1,"max_width_px":420.0,"max_lines":1,"size_px":27.0} | {"fill_h":27,"fill_w":86,"lines":1,"size_px_est":27.0} | 같다 | 아니오 | t=3.07s [프레임](frames/cap_k1_0003070.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [d1·dialogue] ""잠깐만요 진짜예요?"" | — | {"center":[360.0,954.5],"bbox":[166.0,931.0,388.0,47.0],"resolution":[720,1280]} | {"center":[360.0,955.5],"bbox":[170,937,380,37],"resolution":[720,1280],"dx":0.0,"dy":1.0} | 같다 | 아니오 | t=2.92s [프레임](frames/cap_d1_0002920.png) 에피소드 위치 지정(pos) |
| 자막 크기·줄 수 [d1·dialogue] ""잠깐만요 진짜예요?"" | 못 잼 | {"fill_h":39.0,"lines":1,"max_width_px":960.0,"max_lines":2,"size_px":41.0} | {"fill_h":37,"fill_w":380,"lines":1,"size_px_est":38.9} | 같다 | 아니오 | t=2.92s [프레임](frames/cap_d1_0002920.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [r1·reaction] "헉!" | — | {"center":[358.5,763.0],"bbox":[324.0,734.0,69.0,58.0],"resolution":[720,1280]} | {"center":[358.5,763.0],"bbox":[329,740,59,46],"resolution":[720,1280],"dx":0.0,"dy":0.0} | 같다 | 아니오 | t=5.62s [프레임](frames/cap_r1_0005620.png) 에피소드 위치 지정(pos) |
| 자막 크기·줄 수 [r1·reaction] "헉!" | 못 잼 | {"fill_h":48.0,"lines":1,"max_width_px":900.0,"max_lines":1,"size_px":51.0} | {"fill_h":46,"fill_w":59,"lines":1,"size_px_est":48.9} | 같다 | 아니오 | t=5.62s [프레임](frames/cap_r1_0005620.png) 채움색 화소 높이 vs (기대 bbox 높이 − 2×외곽선) |
| 자막 위치 [dialogue] (레퍼런스 대비) | 못 잼 | {"text.roles.dialogue.anchor.x":540,"text.roles.dialogue.anchor.y":1430,"text.roles.dialo… | — | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 5개: text.roles.dialogue.anchor.x, text.roles.dialogue… |
| 자막 크기 [dialogue] (레퍼런스 대비) | 못 잼 | {"text.roles.dialogue.size_px":62,"text.roles.dialogue.line_spacing":1.15,"text.roles.dia… | {"size_px_est":38.9} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: text.roles.dialogue.size_px, text.roles.dialogue.… |
| 자막 위치 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.anchor.x":540,"text.roles.reaction.anchor.y":1140,"text.roles.react… | — | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 5개: text.roles.reaction.anchor.x, text.roles.reaction… |
| 자막 크기 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.size_px":76,"text.roles.reaction.line_spacing":1.1,"text.roles.reac… | {"size_px_est":48.9} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: text.roles.reaction.size_px, text.roles.reaction.… |
| 자막 위치 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.anchor.x":540,"text.roles.situation.anchor.y":1430,"text.roles.sit… | — | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 5개: text.roles.situation.anchor.x, text.roles.situati… |
| 자막 크기 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.size_px":66,"text.roles.situation.line_spacing":1.15,"text.roles.s… | {"size_px_est":42.9} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: text.roles.situation.size_px, text.roles.situatio… |
| 자막 위치 [speaker] (레퍼런스 대비) | 못 잼 | {"text.roles.speaker.anchor.x":540,"text.roles.speaker.anchor.y":700,"text.roles.speaker.… | — | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 5개: text.roles.speaker.anchor.x, text.roles.speaker.a… |
| 자막 크기 [speaker] (레퍼런스 대비) | 못 잼 | {"text.roles.speaker.size_px":40,"text.roles.speaker.line_spacing":1.1,"text.roles.speake… | {"size_px_est":27.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: text.roles.speaker.size_px, text.roles.speaker.li… |
| 자막 위치 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.anchor.x":540,"text.roles.title.anchor.y":330,"text.roles.title.anchor… | — | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 5개: text.roles.title.anchor.x, text.roles.title.ancho… |
| 자막 크기 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.size_px":84,"text.roles.title.line_spacing":1.18,"text.roles.title.max… | {"size_px_est":56.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: text.roles.title.size_px, text.roles.title.line_s… |

### 자막 내용·말투

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 문구(OCR) [t1·title] "실험 영상 모음" | — | 실험 영상 모음 | {"ocr":"실험 영상 모음","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=0.12s [프레임](frames/cap_t1_0000120.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [s1·situation] "두 사람이 고개를 돌린다" | — | 두 사람이 고개를 돌린다 | {"ocr":"두 사 람 이 WHS 돌린다","similarity":0.7,"match":"ocr"} | 같다 | 아니오 | t=1.04s [프레임](frames/cap_s1_0001040.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [k1·speaker] "선생님" | — | 선생님 | {"ocr":"선생님","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=3.07s [프레임](frames/cap_k1_0003070.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [d1·dialogue] ""잠깐만요 진짜예요?"" | 못 잼 | "잠깐만요 진짜예요?" | {"ocr":"\"' 잠 깐 만요 진 짜 예 요 ?''","similarity":1.0,"match":"ocr"} | 같다 | 아니오 | t=2.92s [프레임](frames/cap_d1_0002920.png) 굵은 글꼴 OCR 오차가 있어 유사도로 판정 |
| 자막 문구(OCR) [r1·reaction] "헉!" | — | 헉! | {"ocr":"a!","similarity":0.0,"match":"geometry(짧은 문구 OCR 실패)"} | 못 잼 | 아니오 | t=5.62s [프레임](frames/cap_r1_0005620.png) 짧은 문구를 OCR 이 읽지 못해 위치·색으로만 찾음 — 문구 일치는 못 잼 |
| 자막 말투(종결어미, OCR) | 못 잼 | 반말_구어체 | {"n":1,"counts":{"반말_구어체":1},"mode":"반말_구어체","note":"기타(감탄사·명사 끝)는 판정에서 제외","roles_used":… | 같다 (참고) | 아니오 | OCR 문구의 마지막 글자로 분류(휴리스틱) |
| 자막 이모지 사용 | 못 잼 | false | — | 못 잼 (참고) | 아니오 | 출력 화면에서 이모지를 판별하는 방법 없음(OCR 미지원) |
| 자막 말투 (레퍼런스 대비) | 못 잼 | {"text.tone.register":"반말_구어체","text.tone.sentence_end_examples":[],"text.tone.emoji":fal… | {"register":"반말_구어체"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: text.tone.register, text.tone.sentence_end_exampl… |

### 자막 스타일

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 색·외곽선·박스 [t1·title] "실험 영상 모음" | 못 잼 | {"color":"#FFFFFF","outline_px":4.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FFFFFF","outline_px":11,"outline_color":"#000000","box_alpha":null,"highl… | 같다 | 아니오 | t=0.12s [프레임](frames/cap_t1_0000120.png) 배경이 외곽선 색과 같아 외곽선 두께는 못 잼 |
| 자막 색·외곽선·박스 [s1·situation] "두 사람이 고개를 돌린다" | 못 잼 | {"color":"#FFFFFF","outline_px":4.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FFFFFF","outline_px":11,"outline_color":"#000000","box_alpha":null,"highl… | 같다 | 아니오 | t=1.04s [프레임](frames/cap_s1_0001040.png) 배경이 외곽선 색과 같아 외곽선 두께는 못 잼 |
| 자막 색·외곽선·박스 [k1·speaker] "선생님" | 못 잼 | {"color":"#FFFFFF","outline_px":0.0,"outline_color":"#000000","box":true,"box_alpha":0.65… | {"fill_color":"#FEFDFD","outline_px":0,"outline_color":"#575757","box_alpha":0.503,"highl… | 같다 | 아니오 | t=3.07s [프레임](frames/cap_k1_0003070.png) |
| 자막 색·외곽선·박스 [d1·dialogue] ""잠깐만요 진짜예요?"" | 못 잼 | {"color":"#FFE400","outline_px":4.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FDE300","outline_px":11,"outline_color":"#020000","box_alpha":null,"highl… | 같다 | 아니오 | t=2.92s [프레임](frames/cap_d1_0002920.png) 배경이 외곽선 색과 같아 외곽선 두께는 못 잼 |
| 자막 색·외곽선·박스 [r1·reaction] "헉!" | 못 잼 | {"color":"#FFE400","outline_px":5.0,"outline_color":"#000000","box":false,"box_alpha":nul… | {"fill_color":"#FDE400","outline_px":6,"outline_color":"#030000","box_alpha":0.0,"highlig… | 같다 | 아니오 | t=5.62s [프레임](frames/cap_r1_0005620.png) |
| 자막 색·외곽선·박스 [dialogue] (레퍼런스 대비) | 못 잼 | {"text.roles.dialogue.color":"#FFE400","text.roles.dialogue.highlight_color":"#FFFFFF","t… | {"fill_color":"#FDE300"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 11개: text.roles.dialogue.color, text.roles.dialogue.h… |
| 자막 색·외곽선·박스 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.color":"#FFE400","text.roles.reaction.highlight_color":"#FFFFFF","t… | {"fill_color":"#FDE400"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 11개: text.roles.reaction.color, text.roles.reaction.h… |
| 자막 색·외곽선·박스 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.color":"#FFFFFF","text.roles.situation.highlight_color":"#FFE400",… | {"fill_color":"#FFFFFF"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 11개: text.roles.situation.color, text.roles.situation… |
| 자막 색·외곽선·박스 [speaker] (레퍼런스 대비) | 못 잼 | {"text.roles.speaker.color":"#FFFFFF","text.roles.speaker.highlight_color":"#FFE400","tex… | {"fill_color":"#FEFDFD"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 11개: text.roles.speaker.color, text.roles.speaker.hig… |
| 자막 색·외곽선·박스 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.color":"#FFFFFF","text.roles.title.highlight_color":"#FFE400","text.ro… | {"fill_color":"#FFFFFF"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 11개: text.roles.title.color, text.roles.title.highlig… |

### 폰트

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 글꼴 [t1·title] "실험 영상 모음" | 못 잼 | Noto Sans CJK KR Black | {"best":"Noto Sans CJK KR Black","iou_expected":0.8983,"scores":[{"font":"Noto Sans CJK K… | 같다 | 아니오 | t=0.12s [프레임](frames/cap_t1_0000120.png) |
| 자막 글꼴 [s1·situation] "두 사람이 고개를 돌린다" | 못 잼 | Noto Sans CJK KR Black | {"best":"Noto Sans CJK KR Black","iou_expected":0.8765,"scores":[{"font":"Noto Sans CJK K… | 같다 | 아니오 | t=1.04s [프레임](frames/cap_s1_0001040.png) |
| 자막 글꼴 [k1·speaker] "선생님" | 못 잼 | Noto Sans CJK KR Bold | {"best":"Noto Sans CJK KR Regular","iou_expected":0.497,"scores":[{"font":"Noto Sans CJK … | 못 잼 | 아니오 | t=3.07s [프레임](frames/cap_k1_0003070.png) 다른 글꼴(Noto Sans CJK KR Regular)이 약간 더 맞지만 IoU<0.6 이라 판별 불확실 |
| 자막 글꼴 [d1·dialogue] ""잠깐만요 진짜예요?"" | 못 잼 | Noto Sans CJK KR Black | {"best":"Noto Sans CJK KR Black","iou_expected":0.8904,"scores":[{"font":"Noto Sans CJK K… | 같다 | 아니오 | t=2.92s [프레임](frames/cap_d1_0002920.png) |
| 자막 글꼴 [r1·reaction] "헉!" | 못 잼 | Noto Sans CJK KR Black | {"best":"Noto Sans CJK KR Black","iou_expected":0.9561,"scores":[{"font":"Noto Sans CJK K… | 같다 | 아니오 | t=5.62s [프레임](frames/cap_r1_0005620.png) |
| 자막 글꼴 [dialogue] (레퍼런스 대비) | 못 잼 | {"text.roles.dialogue.font_name":"Noto Sans CJK KR Black","text.roles.dialogue.bold":true} | {"best":"Noto Sans CJK KR Black"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.dialogue.font_name, text.roles.dialogu… |
| 자막 글꼴 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.font_name":"Noto Sans CJK KR Black","text.roles.reaction.bold":true} | {"best":"Noto Sans CJK KR Black"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.reaction.font_name, text.roles.reactio… |
| 자막 글꼴 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.font_name":"Noto Sans CJK KR Black","text.roles.situation.bold":tr… | {"best":"Noto Sans CJK KR Black"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.situation.font_name, text.roles.situat… |
| 자막 글꼴 [speaker] (레퍼런스 대비) | 못 잼 | {"text.roles.speaker.font_name":"Noto Sans CJK KR Bold","text.roles.speaker.bold":true} | {"best":"Noto Sans CJK KR Regular"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.speaker.font_name, text.roles.speaker.… |
| 자막 글꼴 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.font_name":"Noto Sans CJK KR Black","text.roles.title.bold":true} | {"best":"Noto Sans CJK KR Black"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: text.roles.title.font_name, text.roles.title.bold… |

### 자막 타이밍

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 등장·퇴장 시각 [t1·title] "실험 영상 모음" | 못 잼 | {"start":0.0,"end":7.8} | {"onset":0.0,"offset":7.8} | 같다 | 아니오 | t=0.00s [프레임](frames/cap_t1_0000120.png) |
| 자막 등장·퇴장 시각 [s1·situation] "두 사람이 고개를 돌린다" | 못 잼 | {"start":0.8,"end":2.3} | {"onset":0.7667,"offset":2.3} | 같다 | 아니오 | t=0.77s [프레임](frames/cap_s1_0001040.png) |
| 자막 등장·퇴장 시각 [k1·speaker] "선생님" | 못 잼 | {"start":2.8,"end":4.6} | {"onset":2.8333,"offset":4.5591} | 같다 | 아니오 | t=2.83s [프레임](frames/cap_k1_0003070.png) |
| 자막 등장·퇴장 시각 [d1·dialogue] ""잠깐만요 진짜예요?"" | 못 잼 | {"start":2.8,"end":5.0} | {"onset":2.8,"offset":5.0} | 같다 | 아니오 | t=2.80s [프레임](frames/cap_d1_0002920.png) |
| 자막 등장·퇴장 시각 [r1·reaction] "헉!" | 못 잼 | {"start":5.4,"end":6.6} | {"onset":5.4,"offset":6.6} | 같다 | 아니오 | t=5.40s [프레임](frames/cap_r1_0005620.png) |
| 자막 표시 시간 [dialogue] (레퍼런스 대비) | 못 잼 | {"text.roles.dialogue.timing.lead_s":0.0,"text.roles.dialogue.timing.min_dur_s":0.8,"text… | {"min_dur_s":2.2} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: text.roles.dialogue.timing.lead_s, text.roles.dia… |
| 자막 표시 시간 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.timing.lead_s":0.0,"text.roles.reaction.timing.min_dur_s":0.6,"text… | {"min_dur_s":1.2} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: text.roles.reaction.timing.lead_s, text.roles.rea… |
| 자막 표시 시간 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.timing.lead_s":0.0,"text.roles.situation.timing.min_dur_s":0.9,"te… | {"min_dur_s":1.533} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: text.roles.situation.timing.lead_s, text.roles.si… |
| 자막 표시 시간 [speaker] (레퍼런스 대비) | 못 잼 | {"text.roles.speaker.timing.lead_s":0.0,"text.roles.speaker.timing.min_dur_s":1.0,"text.r… | {"min_dur_s":1.726} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: text.roles.speaker.timing.lead_s, text.roles.spea… |
| 자막 표시 시간 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.timing.lead_s":0.0,"text.roles.title.timing.min_dur_s":1.0,"text.roles… | {"min_dur_s":7.8} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: text.roles.title.timing.lead_s, text.roles.title.… |

### 자막 등장·퇴장 모션

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 자막 등장 모션 [t1·title] "실험 영상 모음" | 못 잼 | {"type":"none","dur_s":0.0,"scale_from":1.0} | {"type":"none","note":"첫 프레임부터 완전히 표시(등장 모션 없음)"} | 같다 | 아니오 | t=0.00s [프레임](frames/cap_t1_0000120.png) |
| 자막 등장 모션 [s1·situation] "두 사람이 고개를 돌린다" | 못 잼 | {"type":"pop","dur_s":0.12,"scale_from":0.85} | {"type":"pop","scale_first":0.854,"presence_first":0.456,"dur_s":0.133,"scales":[0.854,0.… | 같다 | 아니오 | t=0.77s [프레임](frames/cap_s1_0001040.png) |
| 자막 등장 모션 [k1·speaker] "선생님" | 못 잼 | {"type":"fade","dur_s":0.15,"scale_from":1.0} | {"type":"fade","scale_first":null,"presence_first":0.244,"dur_s":0.067,"scales":[null,nul… | 같다 | 아니오 | t=2.83s [프레임](frames/cap_k1_0003070.png) |
| 자막 등장 모션 [d1·dialogue] ""잠깐만요 진짜예요?"" | 못 잼 | {"type":"none","dur_s":0.0,"scale_from":1.0} | {"type":"none","scale_first":1.003,"presence_first":1.0,"dur_s":0.0,"scales":[1.003,1.003… | 같다 | 아니오 | t=2.80s [프레임](frames/cap_d1_0002920.png) |
| 자막 등장 모션 [r1·reaction] "헉!" | 못 잼 | {"type":"pop","dur_s":0.1,"scale_from":1.35} | {"type":"pop","scale_first":1.379,"presence_first":0.924,"dur_s":0.1,"scales":[1.379,1.25… | 같다 | 아니오 | t=5.40s [프레임](frames/cap_r1_0005620.png) |
| 자막 등장·퇴장 모션 [dialogue] (레퍼런스 대비) | 못 잼 | {"text.roles.dialogue.motion_in.type":"none","text.roles.dialogue.motion_in.dur_s":0.0,"t… | {"type":"none"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 6개: text.roles.dialogue.motion_in.type, text.roles.di… |
| 자막 등장·퇴장 모션 [reaction] (레퍼런스 대비) | 못 잼 | {"text.roles.reaction.motion_in.type":"pop","text.roles.reaction.motion_in.dur_s":0.1,"te… | {"type":"pop"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 6개: text.roles.reaction.motion_in.type, text.roles.re… |
| 자막 등장·퇴장 모션 [situation] (레퍼런스 대비) | 못 잼 | {"text.roles.situation.motion_in.type":"pop","text.roles.situation.motion_in.dur_s":0.12,… | {"type":"pop"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 6개: text.roles.situation.motion_in.type, text.roles.s… |
| 자막 등장·퇴장 모션 [speaker] (레퍼런스 대비) | 못 잼 | {"text.roles.speaker.motion_in.type":"fade","text.roles.speaker.motion_in.dur_s":0.15,"te… | {"type":"fade"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 6개: text.roles.speaker.motion_in.type, text.roles.spe… |
| 자막 등장·퇴장 모션 [title] (레퍼런스 대비) | 못 잼 | {"text.roles.title.motion_in.type":"none","text.roles.title.motion_in.dur_s":0.0,"text.ro… | {"type":"none"} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 6개: text.roles.title.motion_in.type, text.roles.title… |

### 컷

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 컷 위치 [c2 시작] | — | {"t":2.2} | {"t":2.1998,"type":"crossfade"} | 같다 | 아니오 | t=2.20s |
| 컷 위치 [c3 시작] | — | {"t":5.2} | {"t":5.1667,"type":"flash"} | 같다 | 아니오 | t=5.17s |
| 계획에 없는 컷·플래시 | — | [] | [] | 같다 | 아니오 | — |
| 소스 구간 [c1] | — | {"src_in":10.0,"src_out":12.5,"source":"assets/test/generated/video/head-pose-face-detect… | {"offset_s":-0.053,"samples":[{"t":0.48,"expected_src_t":10.48,"matched_src_t":10.417,"nc… | 같다 | 아니오 | t=0.48s |
| 소스 구간 [c2] | — | {"src_in":7.5,"src_out":10.5,"source":"assets/test/generated/dirty_source.mp4"} | {"offset_s":0.015,"samples":[{"t":3.08,"expected_src_t":8.38,"matched_src_t":8.3,"ncc":0.… | 같다 | 아니오 | t=3.08s |
| 소스 구간 [c3] | — | {"src_in":24.0,"src_out":26.0} | — | 못 잼 | 아니오 | 장면이 거의 정지해 있어 어느 소스 시각인지 구별되지 않음(NCC 곡선이 평평함) |

### 모션(확대·정지·전환)

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 전환 종류·길이 [c2] | 못 잼 | {"type":"crossfade","dur":0.3} | {"type":"crossfade","dur":0.3,"score":0.99} | 같다 | 아니오 | t=2.20s |
| 전환 종류·길이 [c3] | 못 잼 | {"type":"flash","dur":0.12} | {"type":"flash","dur":0.1,"score":123.4} | 같다 | 아니오 | t=5.17s 플래시 최대 밝기 시 영상 영역 평균색 #FDFDFD (기대 #FFFFFF) |
| 줌 없음 확인 [c1] | — | {"final_ratio":1.0} | {"max_dev":0.1684,"median_inliers":109.5,"spread":0.0295} | 못 잼 (참고) | 아니오 | 소스 자체의 카메라 줌도 여기에 잡힘; 특징점 추정이 불안정해 판정 보류 |
| 줌 없음 확인 [c2] | — | {"final_ratio":1.0} | {"max_dev":0.0007,"median_inliers":431.0,"spread":0.0002} | 같다 (참고) | 아니오 | 소스 자체의 카메라 줌도 여기에 잡힘 |
| 확대(줌) [c3] | 못 잼 | {"final_ratio":1.3,"t50":5.706,"dur":0.5,"ease":"out","center_canvas":[360.0,639.5]} | {"measured_final_ratio":1.298,"measured_t50":5.733,"measured_dur":0.476,"measured_ease":"… | 같다 | 아니오 | t=5.73s ORB+RANSAC 유사변환 배율(출력 프레임끼리 비교) |
| 연속 세그먼트 줌 횟수(같은 효과 쌓기 금지) | {"motion.zoom.max_consecutive":"해당 없음(rule)"} | {"max":1} | {"measured":1} | 같다 | 아니오 | — |
| 줌 배율·길이 (레퍼런스 대비) | 못 잼 | {"motion.zoom.scale_to":1.25,"motion.zoom.dur_s":0.35,"motion.zoom.ease":"out"} | {"final_ratio":1.298} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: motion.zoom.scale_to, motion.zoom.dur_s, motion.z… |
| 정지(프리즈) [c3] | 못 잼 | {"start":7.2,"hold":0.6} | {"start":7.2,"hold":0.6,"mean_diff":0.0053} | 같다 | 아니오 | t=7.20s |
| 계획에 없는 정지 화면 | — | [] | [] | 같다 | 아니오 | 소스도 정지해 있으면 제외; 판단 불가(소스 없음)면 포함 |
| 영상당 정지 횟수 | {"motion.freeze.max_per_video":"해당 없음(rule)"} | {"max":2} | {"count":1} | 같다 | 아니오 | — |
| 정지 길이 (레퍼런스 대비) | 못 잼 | {"motion.freeze.hold_s":0.7} | {"hold_s":0.6} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: motion.freeze.hold_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하… |
| 전환 종류·길이 (레퍼런스 대비) | 못 잼 | {"motion.transitions.default":"cut","motion.transitions.flash.dur_s":0.12,"motion.transit… | {"mode":"crossfade","flash_dur":0.1,"crossfade_dur":0.3} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: motion.transitions.default, motion.transitions.fl… |

### 움직이는 장식(위치/밝기 각각)

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 장식 위치·이동 경로 [dc1·circle] | 못 잼 | {"keyframes":[{"t":3.0,"x":200.0,"y":600.0,"w":90.0,"h":90.0,"rotation":null},{"t":4.5,"x… | {"abs_err_p50":0.5,"abs_err_p90":0.6,"path_err_p90":1.0,"size":[88.0,89.3],"color":"#FB2A… | 같다 | 아니오 | t=3.03s 위치는 밝기와 별도로 판정(보이는 프레임만) |
| 장식 밝기·깜빡임 [dc1·circle] | 못 잼 | {"blink_hz":2.0,"start":3.0,"end":4.5} | {"blink_hz":2.0,"on_fraction":0.523,"on_events":3,"curve_sample":[[3.033,0.981],[3.067,0.… | 같다 | 아니오 | t=3.00s 밝기 곡선은 위치와 별도로 판정 |
| 장식 스타일 [circle] (레퍼런스 대비) | 못 잼 | {"decorations.circle.color":"#FF2A2A","decorations.circle.stroke_px":10,"decorations.circ… | {"color":"#FB2A2F","blink_hz":2.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: decorations.circle.color, decorations.circle.stro… |

### 식별 요소

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 레퍼런스 채널명·식별 문구 없음 | {"identity_exclusions.forbidden_text":"해당 없음(rule… | {"absent":["조슈아매거진","조슈아 매거진","joshuamagazine","joshua magazine","JOSHUA MAGAZINE"]} | {"hits":[],"frames_ocr":9} | 같다 | 아니오 | 1초 간격 전체 프레임 + 각 클립 중간 OCR |
| 레퍼런스 로고 템플릿 없음 | {"identity_exclusions.logo_templates_dir":"해당 없음(… | {"templates_dir":"presets/joshuamagazine/reference/identity_templates"} | — | 못 잼 (참고) | 아니오 | 레퍼런스 로고 템플릿이 없어 로고 대조 못 함(레퍼런스 미확보) |

### 로고 잔류

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 모서리·하단 잔여 글자(출처 표기·워터마크·원어 자막) | — | [] | {"persistent":[],"single_hits":[{"zone":"video_bottom","clip_id":"c2","text":"yo","times"… | 같다 | 아니오 | 한 번만 잡힌 글자는 장면 속 글자/OCR 잡음일 수 있어 참고로만 표시 |
| 정리한 영역 잔류 [c2·delogo] | — | {"rect_src":[16,14,190,44],"src_range":[7.5,10.5],"residual":false} | {"residual":false,"edge_ncc":0.106,"text_src":"@fake_repos","text_out":"해","rect_out":[6.… | 같다 | 아니오 | t=3.85s |

### 얼굴·손·물체 가림

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 보호 영역 가림 [남성 얼굴·c1] | — | {"rect":[427.5,512.0,127.5,159.4],"t":[0.0,2.5],"covered":false} | {"hits":[]} | 같다 | 아니오 | t=0.00s 보호 영역은 plan 의 선언(소스 좌표)을 출력 좌표로 옮긴 것, 자막·장식 bbox 는 출력에서 측정 |
| 얼굴 가림(얼굴 검출) | — | — | — | 못 잼 (참고) | 아니오 | 얼굴 검출기 없음: 이 OpenCV 빌드(cv2 5.0.0)에는 Haar cascade(CascadeClassifier/cv… |

### 음악 구간

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| BGM 곡·버전 일치(파형 대조) | 못 잼 | {"path":"assets/test/generated/music_bed_a.wav","track_id":"synthetic_bed_a"} | {"waveform_ncc":0.2453,"local_match":{"n":31,"q95":0.9999,"q70":0.9875,"explained":0.0776… | 같다 | 아니오 | 출력 믹스에서 계획한 음악 파일의 파형을 찾음 |
| BGM 속도(버전) | 못 잼 | 1.0 | 1.0 | 같다 | 아니오 | 후보 템포 상위: [[0.825, 0.2792], [0.8, 0.2692], [1.115, 0.2405], [1.02, 0.… |
| BGM 사용 구간 | 못 잼 | {"section_start_s":12.0} | {"section_start_s":12.0,"used_section":[12.025,19.771],"runner_up":{"section_start_s":52.… | 같다 | 아니오 | t=0.00s 파형이 거의 똑같이 반복되는 곡이라 다른 위치도 같은 소리(상관 차 ≤ 0.005) — 구간 구별 한계 |
| BGM 페이드 인/아웃 | 못 잼 | {"fade_in_s":0.0,"fade_out_s":0.5} | {"fade_in_s":0.0,"fade_out_s":0.43,"audible_span":[0.025,7.771]} | 같다 (참고) | 아니오 | 0.05초 창 LS 이득 곡선에서 측정 |
| BGM 곡·버전·속도·구간 (레퍼런스 대비) | 못 잼 | {"audio.bgm.track_id":null,"audio.bgm.title":null,"audio.bgm.version":null,"audio.bgm.tem… | {"tempo":1.0,"section_start_s":12.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 9개: audio.bgm.track_id, audio.bgm.title, audio.bgm.ve… |
| 보존 대사 구간의 BGM 덕킹 | 못 잼 | {"duck_ranges":[[2.7,5.0]],"depth_db":10.0} | {"ducked_ranges":[[2.649,5.148],[7.497,7.796]],"coverage":[1.0]} | 같다 | 아니오 | t=2.70s |
| 보존 대사 밖에서 BGM 낮춤 없음(효과음·컷 때문에 덕킹 금지) | {"audio.ducking.only_under_kept_dialogue":"해당 없음(… | {"ducking_only_in":[[2.7,5.0]]} | {"ducking_outside":[]} | 같다 | 아니오 | — |
| 덕킹은 원음이 실제로 들리는 곳에서만 | — | 덕킹 구간 ⊆ 원음 존재 구간 | {"ducks_without_original":[],"original_present":[[2.75,5.0]]} | 같다 | 아니오 | — |
| 덕킹 깊이 | 못 잼 | {"depth_db":-10.0} | {"depth_db":-9.98} | 같다 | 아니오 | — |
| 덕킹 깊이·속도 (레퍼런스 대비) | 못 잼 | {"audio.ducking.depth_db":10.0,"audio.ducking.attack_s":0.08,"audio.ducking.release_s":0.… | {"depth_db":-9.98} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 3개: audio.ducking.depth_db, audio.ducking.attack_s, a… |
| 의도적 정적 6.30–6.80s (BGM 없음) | 못 잼 | {"range":[6.3,6.8],"bgm_db_rel":"≤ -30.0"} | {"max_bgm_db_rel":-46.5} | 같다 | 아니오 | t=6.30s |
| 계획에 없는 BGM 끊김 | — | [[6.3,6.8]] | [] | 같다 | 아니오 | — |

### 원음

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 보존 원음 [c2 2.70–5.00s] | 못 잼 | {"present":true,"gain_db":0.0,"stem":"raw","reason":"말하는 사람의 실제 대사"} | {"present_fraction":1.0,"gain_db_mix_scale":-0.02} | 같다 | 아니오 | t=2.70s 원음 이득은 BGM 기준 믹스 척도 추정(BGM 없으면 없음) |
| 원음 OFF 구간에 원음 없음(기본 OFF) | {"audio.original.default":"해당 없음(rule)"} | {"kept_only":[[2.7,5.0]]} | {"leak_windows":[],"sources_without_audio":["c3"]} | 같다 | 아니오 | 소스에 소리가 없는 클립: c3 |
| 보존 원음 크기·경계 (레퍼런스 대비) | 못 잼 | {"audio.original.keep_gain_db":0.0,"audio.original.fade_s":0.04} | {"gain_db":-0.02} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: audio.original.keep_gain_db, audio.original.fade_… |

### 효과음 종류별 개수

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 효과음 [fx1·pop] 위치 | — | {"t":0.8,"type":"pop"} | {"t":0.8,"ncc":0.999} | 같다 | 아니오 | t=0.80s |
| 효과음 [fx1·pop] 크기 | 못 잼 | {"gain_db":-6.0} | {"gain_db_mix_scale":-5.96,"reference":"local_bgm"} | 같다 (참고) | 아니오 | t=0.80s |
| 효과음 [fx2·whoosh] 위치 | — | {"t":2.25,"type":"whoosh"} | {"t":2.2522,"ncc":0.668} | 같다 | 아니오 | t=2.25s |
| 효과음 [fx2·whoosh] 크기 | 못 잼 | {"gain_db":-8.0} | {"gain_db_mix_scale":-11.19,"reference":"local_bgm"} | 다르다 (참고) | 아니오 | t=2.25s |
| 효과음 [fx3·ding] 위치 | — | {"t":5.4,"type":"ding"} | {"t":5.4,"ncc":0.65} | 같다 | 아니오 | t=5.40s |
| 효과음 [fx3·ding] 크기 | 못 잼 | {"gain_db":-8.0} | {"gain_db_mix_scale":-7.98,"reference":"local_bgm"} | 같다 (참고) | 아니오 | t=5.40s |
| 효과음 [fx4·boom] 위치 | — | {"t":5.95,"type":"boom"} | {"t":5.95,"ncc":0.943} | 같다 | 아니오 | t=5.95s |
| 효과음 [fx4·boom] 크기 | 못 잼 | {"gain_db":-10.0} | {"gain_db_mix_scale":-10.53,"reference":"local_bgm"} | 같다 (참고) | 아니오 | t=5.95s |
| 효과음 개수 [boom] (계획 대비) | — | 1 | 1 | 같다 | 아니오 | t=5.95s |
| 효과음 개수 [ding] (계획 대비) | — | 1 | 1 | 같다 | 아니오 | t=5.40s |
| 효과음 개수 [pop] (계획 대비) | — | 1 | 1 | 같다 | 아니오 | t=0.80s |
| 효과음 개수 [whoosh] (계획 대비) | — | 1 | 1 | 같다 | 아니오 | t=2.25s |
| 효과음 종류별 개수 (레퍼런스 포맷 범위 대비) | 못 잼 | 레퍼런스 카탈로그의 포맷별 p10–p90 | {"pop":1,"whoosh":1,"ding":1,"boom":1} | 못 잼 (참고) | 아니오 | sfx_catalog.json 미측정: 2026-09-24: 레퍼런스 최신 50편 다운로드 불가(youtube 차단), De… |
| 효과음 크기 (레퍼런스 대비) | 못 잼 | {"audio.sfx.gain_db_default":-8.0} | {"gain_db":-9.25} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: audio.sfx.gain_db_default — 출력이 임시값과 같아도 레퍼런스와 같다… |

### 사건과의 시차

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 효과음 [fx1] 사건과의 시차 (상황 자막이 튀어나옴) | {"audio.sfx.max_event_offset_s":"해당 없음(rule)"} | {"event_t":0.8,"max_abs_offset":0.3} | {"sfx_t":0.8,"offset":0.0} | 같다 | 아니오 | t=0.80s 사건 시각은 plan 의 선언(화면 사건), 효과음 시각은 출력에서 측정 |
| 효과음 [fx2] 사건과의 시차 (교사가 화면 안으로 걸어 들어옴) | {"audio.sfx.max_event_offset_s":"해당 없음(rule)"} | {"event_t":2.3,"max_abs_offset":0.3} | {"sfx_t":2.2522,"offset":-0.048} | 같다 | 아니오 | t=2.25s 사건 시각은 plan 의 선언(화면 사건), 효과음 시각은 출력에서 측정 |
| 효과음 [fx3] 사건과의 시차 (반응 자막 '헉!' 등장) | {"audio.sfx.max_event_offset_s":"해당 없음(rule)"} | {"event_t":5.4,"max_abs_offset":0.3} | {"sfx_t":5.4,"offset":0.0} | 같다 | 아니오 | t=5.40s 사건 시각은 plan 의 선언(화면 사건), 효과음 시각은 출력에서 측정 |
| 효과음 [fx4] 사건과의 시차 (교실 확대가 끝나며 강조) | {"audio.sfx.max_event_offset_s":"해당 없음(rule)"} | {"event_t":6.0,"max_abs_offset":0.3} | {"sfx_t":5.95,"offset":-0.05} | 같다 | 아니오 | t=5.95s 사건 시각은 plan 의 선언(화면 사건), 효과음 시각은 출력에서 측정 |

### 사건 없는 효과음 0

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 사건 없는 효과음 0 | {"audio.sfx.require_event":"해당 없음(rule)"} | 0 | {"count":0,"items":[]} | 같다 | 아니오 | — |
| 알려진 소리로 설명되지 않는 소리 시작점 | — | 0 | {"count":0,"onsets":[]} | 같다 | 아니오 | BGM·원음·검출된 효과음을 뺀 잔차에서 급격한 에너지 상승(보존 원음 구간 제외) |

### 음량

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 통합 음량(LUFS)·트루피크 | 못 잼 | {"integrated_lufs":-18.0,"true_peak_db":-1.0} | {"integrated_lufs":-18.4,"lra":2.6,"true_peak_db":-3.4} | 같다 | 아니오 | — |
| 음량 (레퍼런스 대비) | 못 잼 | {"audio.loudness.integrated_lufs":-14.0,"audio.loudness.true_peak_db":-1.5} | {"integrated_lufs":-18.4} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: audio.loudness.integrated_lufs, audio.loudness.tr… |

### 구성·표지

| 항목 | 레퍼런스 | 기대 | 출력 측정 | 판정(같다/다르다/못 잼) | 의도한 변경 | 근거 |
|---|---|---|---|---|---|---|
| 영상 길이 | — | 7.8 | 7.8 | 같다 | 아니오 | — |
| 영상 길이 (레퍼런스 분포 대비) | 못 잼 | {"structure.duration_s.p10":null,"structure.duration_s.p50":null,"structure.duration_s.p9… | {"duration":7.8} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 4개: structure.duration_s.p10, structure.duration_s.p5… |
| 첫 자막 시각 (레퍼런스 대비) | 못 잼 | {"structure.first_caption_at_s":0.0} | {"first_caption_at_s":0.0} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 1개: structure.first_caption_at_s — 출력이 임시값과 같아도 레퍼런스와… |
| 표지 프레임에 제목 문구 표시 | 못 잼 | {"t":0.0,"text":"실험 영상 모음","role":"title"} | {"ocr":"실험 영상 모음","similarity":1.0,"role_caption_visible":true} | 같다 (참고) | 아니오 | t=0.00s |
| 표지 구성 (레퍼런스 대비) | 못 잼 | {"cover.source":"first_frame","cover.text_role":"title"} | {"text_role_visible":true} | 못 잼 (참고) | 아니오 | 레퍼런스 미측정(임시값) 키 2개: cover.source, cover.text_role — 출력이 임시값과 같아도 레퍼런스… |

## 못 잼 항목과 이유

- 화면 해상도·프레임레이트 (레퍼런스 대비) (`canvas.format:format_ref`): 레퍼런스 미측정(임시값) 키 3개: canvas.width, canvas.height, canvas.fps — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 영상 영역 (레퍼런스 대비) (`canvas.video_region:region_ref`): 레퍼런스 미측정(임시값) 키 5개: canvas.video_region.x, canvas.video_region.y, canvas.video_region.w, canvas.video_region.h, canvas.video_region.fit — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 배경 (레퍼런스 대비) (`canvas.background:background_ref`): 레퍼런스 미측정(임시값) 키 3개: canvas.background.type, canvas.background.color, canvas.background.blur_sigma — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- **필수** 자막 글꼴 [k1·speaker] "선생님" (`caption.font:k1`): 다른 글꼴(Noto Sans CJK KR Regular)이 약간 더 맞지만 IoU<0.6 이라 판별 불확실
- **필수** 자막 문구(OCR) [r1·reaction] "헉!" (`caption.text:r1`): 짧은 문구를 OCR 이 읽지 못해 위치·색으로만 찾음 — 문구 일치는 못 잼
- 자막 이모지 사용 (`caption.tone:emoji`): 출력 화면에서 이모지를 판별하는 방법 없음(OCR 미지원)
- 자막 위치 [dialogue] (레퍼런스 대비) (`caption.position:dialogue_ref`): 레퍼런스 미측정(임시값) 키 5개: text.roles.dialogue.anchor.x, text.roles.dialogue.anchor.y, text.roles.dialogue.anchor.align, text.roles.dialogue.anchor.valign, text.roles.dialogue.max_width_px — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 크기 [dialogue] (레퍼런스 대비) (`caption.size:dialogue_ref`): 레퍼런스 미측정(임시값) 키 4개: text.roles.dialogue.size_px, text.roles.dialogue.line_spacing, text.roles.dialogue.max_lines, text.roles.dialogue.max_chars_per_line — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 색·외곽선·박스 [dialogue] (레퍼런스 대비) (`caption.style:dialogue_ref`): 레퍼런스 미측정(임시값) 키 11개: text.roles.dialogue.color, text.roles.dialogue.highlight_color, text.roles.dialogue.outline_px, text.roles.dialogue.outline_color, text.roles.dialogue.shadow_px, text.roles.dialogue.shadow_color … — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 글꼴 [dialogue] (레퍼런스 대비) (`caption.font:dialogue_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.dialogue.font_name, text.roles.dialogue.bold — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 표시 시간 [dialogue] (레퍼런스 대비) (`caption.timing:dialogue_ref`): 레퍼런스 미측정(임시값) 키 3개: text.roles.dialogue.timing.lead_s, text.roles.dialogue.timing.min_dur_s, text.roles.dialogue.persist — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 등장·퇴장 모션 [dialogue] (레퍼런스 대비) (`caption.motion:dialogue_ref`): 레퍼런스 미측정(임시값) 키 6개: text.roles.dialogue.motion_in.type, text.roles.dialogue.motion_in.dur_s, text.roles.dialogue.motion_in.scale_from, text.roles.dialogue.motion_in.offset_px, text.roles.dialogue.motion_out.type, text.roles.dialogue.motion_out.dur_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 위치 [reaction] (레퍼런스 대비) (`caption.position:reaction_ref`): 레퍼런스 미측정(임시값) 키 5개: text.roles.reaction.anchor.x, text.roles.reaction.anchor.y, text.roles.reaction.anchor.align, text.roles.reaction.anchor.valign, text.roles.reaction.max_width_px — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 크기 [reaction] (레퍼런스 대비) (`caption.size:reaction_ref`): 레퍼런스 미측정(임시값) 키 4개: text.roles.reaction.size_px, text.roles.reaction.line_spacing, text.roles.reaction.max_lines, text.roles.reaction.max_chars_per_line — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 색·외곽선·박스 [reaction] (레퍼런스 대비) (`caption.style:reaction_ref`): 레퍼런스 미측정(임시값) 키 11개: text.roles.reaction.color, text.roles.reaction.highlight_color, text.roles.reaction.outline_px, text.roles.reaction.outline_color, text.roles.reaction.shadow_px, text.roles.reaction.shadow_color … — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 글꼴 [reaction] (레퍼런스 대비) (`caption.font:reaction_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.reaction.font_name, text.roles.reaction.bold — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 표시 시간 [reaction] (레퍼런스 대비) (`caption.timing:reaction_ref`): 레퍼런스 미측정(임시값) 키 3개: text.roles.reaction.timing.lead_s, text.roles.reaction.timing.min_dur_s, text.roles.reaction.persist — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 등장·퇴장 모션 [reaction] (레퍼런스 대비) (`caption.motion:reaction_ref`): 레퍼런스 미측정(임시값) 키 6개: text.roles.reaction.motion_in.type, text.roles.reaction.motion_in.dur_s, text.roles.reaction.motion_in.scale_from, text.roles.reaction.motion_in.offset_px, text.roles.reaction.motion_out.type, text.roles.reaction.motion_out.dur_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 위치 [situation] (레퍼런스 대비) (`caption.position:situation_ref`): 레퍼런스 미측정(임시값) 키 5개: text.roles.situation.anchor.x, text.roles.situation.anchor.y, text.roles.situation.anchor.align, text.roles.situation.anchor.valign, text.roles.situation.max_width_px — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 크기 [situation] (레퍼런스 대비) (`caption.size:situation_ref`): 레퍼런스 미측정(임시값) 키 4개: text.roles.situation.size_px, text.roles.situation.line_spacing, text.roles.situation.max_lines, text.roles.situation.max_chars_per_line — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 색·외곽선·박스 [situation] (레퍼런스 대비) (`caption.style:situation_ref`): 레퍼런스 미측정(임시값) 키 11개: text.roles.situation.color, text.roles.situation.highlight_color, text.roles.situation.outline_px, text.roles.situation.outline_color, text.roles.situation.shadow_px, text.roles.situation.shadow_color … — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 글꼴 [situation] (레퍼런스 대비) (`caption.font:situation_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.situation.font_name, text.roles.situation.bold — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 표시 시간 [situation] (레퍼런스 대비) (`caption.timing:situation_ref`): 레퍼런스 미측정(임시값) 키 3개: text.roles.situation.timing.lead_s, text.roles.situation.timing.min_dur_s, text.roles.situation.persist — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 등장·퇴장 모션 [situation] (레퍼런스 대비) (`caption.motion:situation_ref`): 레퍼런스 미측정(임시값) 키 6개: text.roles.situation.motion_in.type, text.roles.situation.motion_in.dur_s, text.roles.situation.motion_in.scale_from, text.roles.situation.motion_in.offset_px, text.roles.situation.motion_out.type, text.roles.situation.motion_out.dur_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 위치 [speaker] (레퍼런스 대비) (`caption.position:speaker_ref`): 레퍼런스 미측정(임시값) 키 5개: text.roles.speaker.anchor.x, text.roles.speaker.anchor.y, text.roles.speaker.anchor.align, text.roles.speaker.anchor.valign, text.roles.speaker.max_width_px — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 크기 [speaker] (레퍼런스 대비) (`caption.size:speaker_ref`): 레퍼런스 미측정(임시값) 키 4개: text.roles.speaker.size_px, text.roles.speaker.line_spacing, text.roles.speaker.max_lines, text.roles.speaker.max_chars_per_line — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 색·외곽선·박스 [speaker] (레퍼런스 대비) (`caption.style:speaker_ref`): 레퍼런스 미측정(임시값) 키 11개: text.roles.speaker.color, text.roles.speaker.highlight_color, text.roles.speaker.outline_px, text.roles.speaker.outline_color, text.roles.speaker.shadow_px, text.roles.speaker.shadow_color … — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 글꼴 [speaker] (레퍼런스 대비) (`caption.font:speaker_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.speaker.font_name, text.roles.speaker.bold — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 표시 시간 [speaker] (레퍼런스 대비) (`caption.timing:speaker_ref`): 레퍼런스 미측정(임시값) 키 3개: text.roles.speaker.timing.lead_s, text.roles.speaker.timing.min_dur_s, text.roles.speaker.persist — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 등장·퇴장 모션 [speaker] (레퍼런스 대비) (`caption.motion:speaker_ref`): 레퍼런스 미측정(임시값) 키 6개: text.roles.speaker.motion_in.type, text.roles.speaker.motion_in.dur_s, text.roles.speaker.motion_in.scale_from, text.roles.speaker.motion_in.offset_px, text.roles.speaker.motion_out.type, text.roles.speaker.motion_out.dur_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 위치 [title] (레퍼런스 대비) (`caption.position:title_ref`): 레퍼런스 미측정(임시값) 키 5개: text.roles.title.anchor.x, text.roles.title.anchor.y, text.roles.title.anchor.align, text.roles.title.anchor.valign, text.roles.title.max_width_px — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 크기 [title] (레퍼런스 대비) (`caption.size:title_ref`): 레퍼런스 미측정(임시값) 키 4개: text.roles.title.size_px, text.roles.title.line_spacing, text.roles.title.max_lines, text.roles.title.max_chars_per_line — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 색·외곽선·박스 [title] (레퍼런스 대비) (`caption.style:title_ref`): 레퍼런스 미측정(임시값) 키 11개: text.roles.title.color, text.roles.title.highlight_color, text.roles.title.outline_px, text.roles.title.outline_color, text.roles.title.shadow_px, text.roles.title.shadow_color … — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 글꼴 [title] (레퍼런스 대비) (`caption.font:title_ref`): 레퍼런스 미측정(임시값) 키 2개: text.roles.title.font_name, text.roles.title.bold — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 표시 시간 [title] (레퍼런스 대비) (`caption.timing:title_ref`): 레퍼런스 미측정(임시값) 키 3개: text.roles.title.timing.lead_s, text.roles.title.timing.min_dur_s, text.roles.title.persist — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 등장·퇴장 모션 [title] (레퍼런스 대비) (`caption.motion:title_ref`): 레퍼런스 미측정(임시값) 키 6개: text.roles.title.motion_in.type, text.roles.title.motion_in.dur_s, text.roles.title.motion_in.scale_from, text.roles.title.motion_in.offset_px, text.roles.title.motion_out.type, text.roles.title.motion_out.dur_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 자막 말투 (레퍼런스 대비) (`caption.tone:tone_ref`): 레퍼런스 미측정(임시값) 키 4개: text.tone.register, text.tone.sentence_end_examples, text.tone.emoji, text.tone.notes — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- **필수** 소스 구간 [c3] (`video.mapping:c3`): 장면이 거의 정지해 있어 어느 소스 시각인지 구별되지 않음(NCC 곡선이 평평함)
- 줌 없음 확인 [c1] (`video.zoom:c1`): 소스 자체의 카메라 줌도 여기에 잡힘; 특징점 추정이 불안정해 판정 보류
- 줌 배율·길이 (레퍼런스 대비) (`video.zoom:zoom_ref`): 레퍼런스 미측정(임시값) 키 3개: motion.zoom.scale_to, motion.zoom.dur_s, motion.zoom.ease — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 정지 길이 (레퍼런스 대비) (`video.freeze:freeze_ref`): 레퍼런스 미측정(임시값) 키 1개: motion.freeze.hold_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 전환 종류·길이 (레퍼런스 대비) (`video.transitions:transitions_ref`): 레퍼런스 미측정(임시값) 키 4개: motion.transitions.default, motion.transitions.flash.dur_s, motion.transitions.flash.color, motion.transitions.crossfade.dur_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 장식 스타일 [circle] (레퍼런스 대비) (`decor.position:dc1_ref`): 레퍼런스 미측정(임시값) 키 3개: decorations.circle.color, decorations.circle.stroke_px, decorations.circle.blink_hz — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 레퍼런스 로고 템플릿 없음 (`identity.logo_templates:all`): 레퍼런스 로고 템플릿이 없어 로고 대조 못 함(레퍼런스 미확보)
- 얼굴 가림(얼굴 검출) (`cover_up.faces:detector`): 얼굴 검출기 없음: 이 OpenCV 빌드(cv2 5.0.0)에는 Haar cascade(CascadeClassifier/cv2.data)가 없고, 얼굴 모델 파일(assets/models/face_detection_yunet*.onnx 또는 $SHORTKIT_FACE_MODEL)도 없음 — plan 보호 영역 검사로 대체
- BGM 곡·버전·속도·구간 (레퍼런스 대비) (`audio.bgm:bgm_ref`): 레퍼런스 미측정(임시값) 키 9개: audio.bgm.track_id, audio.bgm.title, audio.bgm.version, audio.bgm.tempo_ratio, audio.bgm.section_start_s, audio.bgm.gain_db … — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음. 레퍼런스 곡 식별(제목·버전·속도·구간)이 필요
- 덕킹 깊이·속도 (레퍼런스 대비) (`audio.ducking:ducking_ref`): 레퍼런스 미측정(임시값) 키 3개: audio.ducking.depth_db, audio.ducking.attack_s, audio.ducking.release_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 보존 원음 크기·경계 (레퍼런스 대비) (`audio.original:orig_ref`): 레퍼런스 미측정(임시값) 키 2개: audio.original.keep_gain_db, audio.original.fade_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 효과음 종류별 개수 (레퍼런스 포맷 범위 대비) (`audio.sfx.count:catalog`): sfx_catalog.json 미측정: 2026-09-24: 레퍼런스 최신 50편 다운로드 불가(youtube 차단), Demucs 가중치 호스트(dl.fbaipublicfiles.com) 차단
- 효과음 크기 (레퍼런스 대비) (`audio.sfx.placement:sfx_gain_ref`): 레퍼런스 미측정(임시값) 키 1개: audio.sfx.gain_db_default — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 음량 (레퍼런스 대비) (`audio.loudness:loudness_ref`): 레퍼런스 미측정(임시값) 키 2개: audio.loudness.integrated_lufs, audio.loudness.true_peak_db — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 영상 길이 (레퍼런스 분포 대비) (`structure.duration:duration_ref`): 레퍼런스 미측정(임시값) 키 4개: structure.duration_s.p10, structure.duration_s.p50, structure.duration_s.p90, structure.duration_s.n — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 첫 자막 시각 (레퍼런스 대비) (`structure.duration:first_caption_ref`): 레퍼런스 미측정(임시값) 키 1개: structure.first_caption_at_s — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.
- 표지 구성 (레퍼런스 대비) (`cover.frame:cover_ref`): 레퍼런스 미측정(임시값) 키 2개: cover.source, cover.text_role — 출력이 임시값과 같아도 레퍼런스와 같다고 판정하지 않음.

## 비교 시트
- `episodes/test-qa-good/qa/compare_sheet.png`

## 결함 기록 (defects.jsonl)
- 열림 6 / 이번에 해결 확인 8 / 재발 1 / 새로 등록 0

---
판정 기준: 같다=허용오차 안, 다르다=허용오차 밖, 못 잼=측정 불가(완료로 치지 않음). 레퍼런스 열의 '못 잼'은 레퍼런스에서 측정되지 않은 임시값이라는 뜻이다.
