"""Optional speech recognition of reference videos -> ``analysis/<id>/audio/transcript.json``.

    shortkit ref transcribe [--set reference|latest100|high_views|...] [--model small] [--language ko]

The reference's SCRIPT for tracing is first of all its own on-screen caption text
(``analysis/<id>/captions.json`` written by `ref analyze`; `ref trace` reads it as the script channel).
Spoken words are an extra source: when the optional ASR engine ``faster-whisper`` is installed AND its
model weights are available locally, this writes::

    {"schema": "shortkit.transcript/1", "video_id", "status": "measured", "engine": "faster-whisper <ver>",
     "model", "language", "audio_file", "segments": [{"start", "end", "text"}], "text", "created_at",
     "note": "기계 음성 인식 결과(사람이 들어 확인한 것이 아님)"}

`ref trace` then adds its frequent words (with the first segment time) to the script keywords.  Without
the engine NOTHING is written (no empty / guessed transcript); the command reports 못 잼 with the reason.
Not live-tested on the first build machine (faster-whisper not installed; its weight host was blocked).
"""
from __future__ import annotations

from typing import Callable

from .. import paths
from ..util.jsonio import now_iso, read_json, write_json
from .common import analysis_dir, say, video_path, warn

SCHEMA = "shortkit.transcript/1"


def transcript_path(preset: str, vid: str):
    return analysis_dir(preset, vid) / "audio" / "transcript.json"


def asr_engine() -> tuple[Callable | None, str | None, str | None]:
    """(engine(audio_path, model, language) -> [segments], label, blocker)."""
    try:
        import faster_whisper  # type: ignore
    except ImportError:
        return None, None, ("faster-whisper 미설치 — `pip install faster-whisper` 와 모델 가중치(로컬 파일)가 있어야 음성 "
                            "전사 가능. 대본 추적은 레퍼런스 자막(captions.json)으로 계속함")
    ver = getattr(faster_whisper, "__version__", "?")

    def run(audio: str, model: str, language: str) -> list[dict]:
        m = faster_whisper.WhisperModel(model, device="cpu", compute_type="int8")
        segs, _info = m.transcribe(audio, language=language, vad_filter=True)
        return [{"start": round(float(s.start), 3), "end": round(float(s.end), 3), "text": str(s.text).strip()}
                for s in segs]

    return run, f"faster-whisper {ver}", None


def transcribe_video(preset: str, vid: str, model: str = "small", language: str = "ko", force: bool = False,
                     engine: Callable | None = None, engine_label: str | None = None) -> dict:
    out = transcript_path(preset, vid)
    if out.is_file() and not force:
        d = read_json(out) or {}
        if d.get("status") == "measured":
            return {"video_id": vid, "status": "cached", "file": paths.relp(out)}
    if engine is None:
        engine, engine_label, blocker = asr_engine()
        if engine is None:
            return {"video_id": vid, "status": "unmeasured", "blocker": blocker}
    video = video_path(preset, vid)
    if video is None:
        return {"video_id": vid, "status": "unmeasured", "blocker": "레퍼런스 영상 파일 없음(`shortkit ref download` 필요)"}
    try:
        segs = engine(str(video), model, language)
    except Exception as e:  # noqa: BLE001 - a failed ASR run is 못 잼, never an empty transcript
        return {"video_id": vid, "status": "unmeasured", "blocker": f"음성 인식 실패: {type(e).__name__}: {e}"[:300]}
    segs = [s for s in segs if str(s.get("text") or "").strip()]
    rec = {"schema": SCHEMA, "video_id": vid, "status": "measured", "engine": engine_label or "custom",
           "model": model, "language": language, "audio_file": paths.relp(video), "segments": segs,
           "text": " ".join(s["text"] for s in segs), "created_at": now_iso(),
           "note": "기계 음성 인식 결과(사람이 들어 확인한 것이 아님) — 소재 역추적 검색어 단서로만 사용"}
    write_json(out, rec)
    return {"video_id": vid, "status": "measured", "file": paths.relp(out), "segments": len(segs)}


def transcribe_many(preset: str, ids: list[str], model: str = "small", language: str = "ko", force: bool = False,
                    engine: Callable | None = None, engine_label: str | None = None) -> dict:
    res = [transcribe_video(preset, v, model, language, force, engine, engine_label) for v in ids]
    written = [r for r in res if r["status"] == "measured"]
    blocked = [r for r in res if r["status"] == "unmeasured"]
    say(f"음성 전사: 대상 {len(ids)}편, 새로 씀 {len(written)}편, 기존 {sum(r['status'] == 'cached' for r in res)}편, "
        f"못 잼 {len(blocked)}편")
    if blocked:
        warn(f"  못 잼 사유(첫 건): {blocked[0]['blocker']}")
    return {"written": len(written), "results": res}
