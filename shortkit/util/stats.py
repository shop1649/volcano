"""Distribution summaries used everywhere a measurement is reported.

Every numeric measurement is reported as ``{"n", "p10", "p50", "p90"}`` for the whole
sample and per format (see docs/CONTRACT.md "Measurements").  ``n == 0`` means the value
was not measured (status ``unmeasured`` / 못 잼) -- never fill it with a guess.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable, Mapping, Sequence

import numpy as np

PCTS = (10, 50, 90)


def pstats(values: Iterable[float | int | None], digits: int = 3) -> dict:
    """p10/p50/p90 with linear interpolation (numpy default) and the sample size.

    ``None``/NaN entries are dropped (they are "not measured", not zero).
    """
    arr = np.array([float(v) for v in values if v is not None and not _isnan(v)], dtype=float)
    if arr.size == 0:
        return {"n": 0, "p10": None, "p50": None, "p90": None}
    q = np.percentile(arr, PCTS)
    return {"n": int(arr.size), "p10": round(float(q[0]), digits), "p50": round(float(q[1]), digits),
            "p90": round(float(q[2]), digits)}


def pstats_by_group(rows: Sequence[Mapping], value_key: str, group_key: str = "format_id",
                    digits: int = 3) -> dict:
    """``{"overall": pstats, "by_format": {fmt: pstats}}`` from row dicts."""
    overall = pstats((r.get(value_key) for r in rows), digits)
    groups: dict[str, list] = {}
    for r in rows:
        g = r.get(group_key)
        if g is None:
            continue
        groups.setdefault(str(g), []).append(r.get(value_key))
    return {"overall": overall, "by_format": {g: pstats(v, digits) for g, v in sorted(groups.items())}}


def categorical(values: Iterable[str | None]) -> dict:
    """Counts for categorical measurements (e.g. transition type). None = not measured."""
    vals = [v for v in values if v is not None]
    c = Counter(vals)
    n = len(vals)
    return {"n": n, "counts": dict(c.most_common()),
            "share": {k: round(v / n, 4) for k, v in c.most_common()} if n else {},
            "mode": c.most_common(1)[0][0] if n else None}


def tri_state(observations: Iterable[bool | None]) -> str:
    """Presence summary: 'present' (있다) / 'absent' (없다) / 'unmeasured' (못 잼).

    present if any observation is True; absent only if there is at least one observation and
    all of them are False; unmeasured if nothing was observed.
    """
    obs = [o for o in observations if o is not None]
    if not obs:
        return "unmeasured"
    return "present" if any(obs) else "absent"


TRI_KO = {"present": "있다", "absent": "없다", "unmeasured": "못 잼"}
QA_KO = {"same": "같다", "different": "다르다", "unmeasured": "못 잼"}


def within_observed(value: float, st: Mapping) -> bool | None:
    """Is value inside the observed [p10, p90] range?  None if the range is unmeasured."""
    if not st or st.get("n", 0) == 0 or st.get("p10") is None:
        return None
    return st["p10"] <= value <= st["p90"]


def _isnan(v) -> bool:
    try:
        return bool(np.isnan(v))
    except TypeError:
        return False
