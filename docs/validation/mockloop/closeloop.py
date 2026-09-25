"""SYNTHETIC mockloop, step 5: one episode from a DIFFERENT source, rendered with the scratch project's
joshuamagazine preset (whose style values now come from measurements of the SYNTHETIC mock references),
then QA'd against mockref-001.

    SHORTKIT_ROOT=<scratch> PYTHONPATH=<repo> python docs/validation/mockloop/closeloop.py plan
    SHORTKIT_ROOT=<scratch> PYTHONPATH=<repo> python -m shortkit episode all mockloop-qa-001
    SHORTKIT_ROOT=<scratch> PYTHONPATH=<repo> python -m shortkit qa run --episode mockloop-qa-001 \
        --reference presets/joshuamagazine/reference/videos/SYNTHmock01.mp4 --reference-id SYNTHmock01

The edit (cuts, caption texts and timing, sfx events) is the repo's test episode
episodes/test-pipeline-001/plan.yaml (classroom_voice.mp4 + head-pose clip -- the mocks used the
people-detection and face-demographics clips), read-only.  Changed for the loop:
  * format F1 (the only format of the synthetic reference set), episode id mockloop-qa-001;
  * sfx types = the reference catalog's types (edit_01 whoosh-like, edit_03 ding-like, edit_05 pop-like),
    NO file and NO gain in the plan: file via sfx_map.yaml, level via the preset (measured); the boing
    event is dropped (no such type in the catalog; per-type counts full);
  * BGM = the scratch music library's bed_b (identified as the references' track); silences kept;
  * every style value (fonts, sizes, positions, zoom, freeze hold, transitions, loudness...) comes from the
    preset -- nothing style-related is written into the plan.
Never run against the real project root.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[3]
EP = "mockloop-qa-001"
# reference catalog type per original sfx event kind (what the mocks used for the same kind of event);
# None = dropped: the catalog has no boing-like type and its per-video counts (edit_05 1..2.6, edit_03 and
# edit_01 at most 1 in F1) are already used by the other four events
SFX_TYPE = {"whoosh": "edit_01", "click": "edit_05", "pop": "edit_05", "ding": "edit_03", "boing": None}


# Editor adjustments to the MEASURED style (content only -- the values they respond to come from the preset):
# the test episode's texts were written for the provisional preset; with the measured sizes/limits they wrap
# or break the measured tone, so the loop's editor rewrites them (same meaning, same grounding and timing).
TEXT = {
    "c_title": ("교실의 순간들", "제목 최대 폭 699 px / 98.5 px 글꼴에서 한 줄(원문 '움직임 테스트 영상'은 두 줄 → 설명과 겹침·위 여백 밖)"),
    "c_desc": ("교실에서 생긴 일", "설명 max_lines 1, 최대 폭 370 px(원문은 두 줄)"),
    "c_sit1": ("창가 남성이 일어서요", "측정 말투 해요체"),
    "c_sit2": ("다시 자리에 앉아요", "측정 말투 해요체"),
    "c_sit3": ("뒷줄 남성이 손을 들어요", "측정 말투 해요체"),
    "c_sit4": ("두 사람이 고개를 기울여요", "측정 말투 해요체"),
    "c_rx": ("갸웃", "반응 자막 최대 2자·한 줄(원문 '갸우뚱?'은 두 줄)"),
}
HIGHLIGHT = {"c_sit4": ["기울여요"]}
POS = {"c_spk": ([740, 712], "측정 크기의 이름표가 창가 남성 얼굴·몸(보호 영역)을 가리지 않도록 머리 위로")}
# the measured freeze hold / transition durations move everything after s2 by -0.13 s (validator:
# sfx_event_time_drift) -> the events' output times and their sounds move with them (same sound-to-event offset)
SFX_SHIFT = {"fx3": -0.13, "fx4": -0.13}


def root() -> Path:
    r = Path(os.environ["SHORTKIT_ROOT"]).resolve()
    if r == REPO.resolve():
        raise SystemExit("refusing to write the mockloop episode into the real project root")
    return r


def plan() -> None:
    r = root()
    src = yaml.safe_load((REPO / "episodes/test-pipeline-001/plan.yaml").read_text(encoding="utf-8"))
    p = dict(src)
    p["episode_id"] = EP
    p["preset_id"] = "joshuamagazine-v1"
    p["format_id"] = "F1"
    p["mode"] = "test"
    p["episode_index"] = 1
    p["notes"] = ("SYNTHETIC mockloop 닫힌 고리 검증 편: 편집(컷·자막 문구·효과음 사건)은 episodes/test-pipeline-001 과 같고, "
                  "스타일 값은 전부 scratch 프로젝트의 joshuamagazine 프리셋(합성 모의 레퍼런스 5편에서 측정)에서 온다. "
                  "게시용 아님.")
    edits = []
    caps = []
    for c in src.get("captions") or []:
        c = dict(c)
        if c["id"] in TEXT:
            edits.append(f"{c['id']}: '{c['text']}' → '{TEXT[c['id']][0]}' ({TEXT[c['id']][1]})")
            c["text"] = TEXT[c["id"]][0]
            if c["id"] in HIGHLIGHT:
                c["highlight"] = HIGHLIGHT[c["id"]]
        if c["id"] in POS:
            edits.append(f"{c['id']}: pos {c.get('pos')} → {POS[c['id']][0]} ({POS[c['id']][1]})")
            c["pos"] = POS[c["id"]][0]
        caps.append(c)
    p["captions"] = caps
    p["cover"] = {"text": TEXT["c_title"][0], "frame_t": 0.0}
    p["title_candidates"] = [TEXT["c_title"][0], "창가 남성이 일어섰다 앉기까지", "손을 든 뒷줄, 고개를 기울인 두 사람"]
    sfx = []
    for fx in src.get("sfx") or []:
        if SFX_TYPE[fx["type"]] is None:
            continue
        f = {k: v for k, v in fx.items() if k not in ("file", "gain_db", "type")}
        f["type"] = SFX_TYPE[fx["type"]]
        if fx["id"] in SFX_SHIFT:
            d = SFX_SHIFT[fx["id"]]
            f["t"] = round(float(fx["t"]) + d, 3)
            f["event"] = dict(fx["event"], t=round(float(fx["event"]["t"]) + d, 3))
            edits.append(f"{fx['id']}: t {fx['t']} → {f['t']} (사건 출력 시각이 측정 정지·전환 길이로 {d:+.2f}s 이동)")
        sfx.append(f)
    p["sfx"] = sfx
    p["notes"] += " 측정 스타일에 맞춘 문구·위치·시각 조정: " + "; ".join(edits)
    bgm = dict(src.get("bgm") or {})
    bgm["path"] = "assets/library/music/music_bed_b.wav"
    p["bgm"] = bgm
    ed = r / "episodes" / EP
    ed.mkdir(parents=True, exist_ok=True)
    head = ("# SYNTHETIC mockloop close-loop episode (docs/validation/mockloop/closeloop.py 가 생성).\n"
            "# 편집은 episodes/test-pipeline-001/plan.yaml 복사, 효과음 종류는 레퍼런스 카탈로그 종류로 바꿈(파일·이득은 sfx_map·프리셋),\n"
            "# BGM 은 scratch 음악 라이브러리 bed_b. 스타일 값은 plan 에 쓰지 않음(프리셋 측정값 사용).\n")
    (ed / "plan.yaml").write_text(head + yaml.safe_dump(p, allow_unicode=True, sort_keys=False), encoding="utf-8")
    print(f"plan -> {ed / 'plan.yaml'}")


if __name__ == "__main__":
    {"plan": plan}[sys.argv[1]]()
