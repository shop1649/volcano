"""Human check records: ``episodes/<id>/qa/human_checks.jsonl``.

Some QA items cannot be decided by a machine measurement of the MP4 -- the separation quality of a kept voice stem
(was the embedded music really removed?), whether a sound that sits on a cut really follows an on-screen event.
Those rows stay ``못 잼`` until a PERSON has listened to / watched the final MP4 and recorded the verdict here::

    {row_id, kind: listen|watch, verdict: same|different, by, at, note, mp4_sha256}

A record is valid only for the MP4 it was made on (sha256).  An agent cannot listen to audio: agents never write
these records (AGENTS.md rule 10 -- never claim a listening check that was not done).  ``shortkit qa human-check``
writes them for the person who did the check.
"""
from __future__ import annotations

from pathlib import Path

KINDS = ("listen", "watch")
VERDICTS = ("same", "different")


def path_for(episode_id: str) -> Path:
    from .. import paths

    return paths.episode_dir(episode_id) / "qa" / "human_checks.jsonl"


def load(episode_id: str) -> list[dict]:
    from ..util.jsonio import read_jsonl

    return read_jsonl(path_for(episode_id))


def record(episode_id: str, row_id: str, kind: str, verdict: str, by: str, note: str, mp4_sha256: str) -> dict:
    from ..util.jsonio import now_iso, write_jsonl

    if kind not in KINDS:
        raise ValueError(f"kind 는 {KINDS} 중 하나")
    if verdict not in VERDICTS:
        raise ValueError(f"verdict 는 {VERDICTS} 중 하나")
    if not (by or "").strip():
        raise ValueError("--by (직접 듣거나 본 사람) 필요")
    if not (note or "").strip():
        raise ValueError("--note (무엇을 듣고/보고 판단했는지) 필요")
    items = load(episode_id)
    rec = {"row_id": row_id, "kind": kind, "verdict": verdict, "by": by.strip(), "at": now_iso(), "note": note.strip(),
           "mp4_sha256": mp4_sha256}
    items.append(rec)
    write_jsonl(path_for(episode_id), items)
    return rec


def latest(records: list[dict], row_id: str, mp4_sha256: str | None, kind: str | None = None) -> dict | None:
    """The newest record for ``row_id`` made on this exact MP4 (None if there is none)."""
    got = [r for r in records if r.get("row_id") == row_id and r.get("mp4_sha256") == mp4_sha256
           and (kind is None or r.get("kind") == kind)]
    return got[-1] if got else None
