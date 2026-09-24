# 음악 창고 (사용자 제공)

- 여기에 **깨끗한 원본 음악 파일**(wav/flac/mp3)을 둔다. 레퍼런스 영상에서 분리한 음원은 제작용으로 쓰지 않는다.
- `index.yaml` 에 곡 정보를 적는다:

```yaml
tracks:
  - track_id: example_song_original      # 프리셋 audio.bgm.track_id 가 가리키는 값
    file: example_song.wav               # 이 폴더 기준 상대 경로
    title: "곡명"
    artist: "아티스트"
    version: original                    # original | sped_up | slowed | remix | instrumental ...
    license: "라이선스/구매 증빙 위치"
```

- 곡 식별(`shortkit ref bgm-identify`)과 구간·속도 정렬(`shortkit ref bgm-align`)은 이 창고의 파일과 레퍼런스를 비교한다.
- 2026-09-24 기준: 제공된 파일 없음.
