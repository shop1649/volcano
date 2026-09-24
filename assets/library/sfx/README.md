# 효과음 창고 (사용자 제공)

- 사용자가 가진 효과음 파일(wav/flac/mp3/ogg)을 이 폴더(또는 local.yaml 의 `sfx_library_root`)에 둔다. 하위 폴더 허용.
- `shortkit ref sfx-map` 이 레퍼런스 효과음 카탈로그의 종류마다 가장 비슷한 파일을 찾아 `presets/joshuamagazine/sfx_map.yaml` 에 연결한다.
  - 있음(have): 비슷한 파일을 찾음 / 없음(none): 창고를 확인했지만 같은 계열이 없음 → 필요한 자산 설명 기록 /
    못 잼(unmeasured): 카탈로그가 아직 측정되지 않았거나 창고가 없음.
- 2026-09-24 기준: 효과음 창고가 제공되지 않았음(`library_status: not_provided`).
