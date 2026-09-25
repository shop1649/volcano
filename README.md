# volcano — 레퍼런스 기반 쇼츠 제작 프리셋 (shortkit)

레퍼런스 채널(<https://youtube.com/@joshuamagazine>)의 편집 구조를 재현하면서 **다른 촬영본**으로 쇼츠를 만드는 실행 가능한 제작 시스템.

- 에이전트(Claude Code / Codex) 지침: [`AGENTS.md`](AGENTS.md)
- 현재 미확정 항목과 제작 영향: [`presets/joshuamagazine/unresolved.md`](presets/joshuamagazine/unresolved.md)
- 검증 범위(무엇을 실제로 돌려 봤는지): [`docs/VALIDATION.md`](docs/VALIDATION.md)
- 납품물 위치(영상·편집 프로젝트·QA·창고, 무엇이 테스트용인지): [`docs/DELIVERABLES.md`](docs/DELIVERABLES.md)
- 진행 기록·재개 지점: [`PROGRESS.md`](PROGRESS.md)
- 다른 컴퓨터로 옮길 단일 파일: [`PRESET_BUNDLE.md`](PRESET_BUNDLE.md) (복원 명령이 파일 맨 위에 있음)

## 빠른 시작

```bash
bash scripts/setup.sh --with-apt      # Ubuntu. macOS 는 --with-brew, Windows 는 scripts/setup.ps1(미검증)
source .venv/bin/activate
python -m shortkit doctor --network   # 무엇이 빠졌는지, 어떤 플랫폼에 접속되는지
```

그다음은 `AGENTS.md` 5장 A(레퍼런스 분석) → B(소재 창고) → C(에피소드 제작) 순서.

## 중요: 레퍼런스 측정은 아직 안 됨

첫 작업 환경(2026-09-24)에서 YouTube·TikTok·Instagram·Reddit 등이 네트워크 정책으로 차단되어 레퍼런스 영상을 받지 못했다.
프리셋의 스타일 값은 모두 임시값이며 `못 잼` 상태로 표시되어 있다. 시스템은 이 상태에서 production 렌더를 막는다.
