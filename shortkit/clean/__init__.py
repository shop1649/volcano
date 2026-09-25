"""Source overlay cleaning: original logos, watermarks, source overlays, foreign burned-in subtitles.

    detect.py         overlays.json per source (warehouse/overlays/<sha256>.json, provenance kept)
    faces.py          protected regions (OpenCV Haar frontal + profile cascades) merged over time
    strategy.py       per-overlay decision: clean original -> crop -> delogo/inpaint -> blur (last resort)
    apply.py          inpaint_video (used by the resolver), apply_clean, ffmpeg filter chain
    verify.py         residual_score (template match + OCR) for cleaned files and the final MP4
    plan_coverage.py  coverage(): does a plan's clean block remove every recorded overlay?
    cli.py            `shortkit clean detect|faces|plan|coverage|apply|verify|show|fetch-models`

All rects are SOURCE px with the resolution they refer to; times are SOURCE seconds.
"""


def coverage(source_path, clean_block, **kw) -> list:
    """Recorded overlays (warehouse/overlays/<sha256>.json) of ``source_path`` that ``clean_block``
    (plan.yaml ``sources[].clean``) does not remove; ``[]`` = all covered.  Entries with
    ``blocking: True`` must make ``episode validate`` fail.  See :mod:`shortkit.clean.plan_coverage`."""
    from .plan_coverage import coverage as _coverage

    return _coverage(source_path, clean_block, **kw)


def coverage_report(source_path, clean_block, **kw) -> dict:
    """Like :func:`coverage` with the covered overlays and record metadata."""
    from .plan_coverage import coverage_report as _report

    return _report(source_path, clean_block, **kw)
