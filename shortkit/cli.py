"""`shortkit` / `python -m shortkit` command-line entry point.

Each area owns its own sub-commands in ``shortkit/<area>/cli.py`` exposing
``register(subparsers)``; areas are imported lazily so a missing optional dependency in one
area never breaks the others.
"""
from __future__ import annotations

import argparse
import importlib
import sys

AREAS = [
    # (command, module, help)
    ("doctor", "shortkit.doctor", "필수 프로그램·의존성 확인 / 초기 설정 점검"),
    ("preset", "shortkit.preset_cli", "프리셋 레지스트리 동기화·감사·측정값 반영"),
    ("ref", "shortkit.reference.cli", "레퍼런스 채널 수집·스냅샷·측정·포맷 분류·효과음 카탈로그"),
    ("source", "shortkit.sourcing.cli", "새 소재 창고: 검색·제외 목록·선별·다운로드·출처 기록"),
    ("clean", "shortkit.clean.cli", "원본 로고·출처 오버레이·원어 자막 검출과 제거"),
    ("episode", "shortkit.edit.cli", "에피소드 기획·검증·승인·렌더·편집 프로젝트 내보내기"),
    ("qa", "shortkit.qa.cli", "최종 MP4 기준 출력 검수·비교 시트·최종 관문"),
    ("bundle", "shortkit.bundle", "단일 MD 프리셋 번들 생성·복원"),
    ("testassets", "shortkit.testassets", "파이프라인 검증용 합성 테스트 자산 생성"),
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="shortkit", description="레퍼런스 기반 쇼츠 제작 프리셋 시스템")
    sub = parser.add_subparsers(dest="area", required=True)
    broken: dict[str, str] = {}
    for cmd, mod, help_ in AREAS:
        try:
            m = importlib.import_module(mod)
        except Exception as e:  # keep other areas usable
            broken[cmd] = f"{type(e).__name__}: {e}"
            p = sub.add_parser(cmd, help=f"{help_} (불러오기 실패)")
            p.set_defaults(func=lambda a, _c=cmd: _broken(_c, broken[_c]))
            continue
        m.register(sub.add_parser(cmd, help=help_))
    args = parser.parse_args(argv)
    rc = args.func(args)
    return int(rc or 0)


def _broken(cmd: str, err: str) -> int:
    print(f"[shortkit] '{cmd}' 모듈을 불러오지 못했습니다: {err}\n`shortkit doctor` 로 의존성을 확인하세요.",
          file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
