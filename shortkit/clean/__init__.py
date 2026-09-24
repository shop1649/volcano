"""Source overlay cleaning: original logos, watermarks, source overlays, foreign burned-in subtitles.

    detect.py    overlays.json per source (warehouse/overlays/<sha256>.json, provenance kept)
    faces.py     protected regions (OpenCV Haar frontal + profile cascades) merged over time
    strategy.py  per-overlay decision: clean original -> crop -> delogo/inpaint -> blur (last resort)
    apply.py     inpaint_video (used by the resolver), apply_clean, ffmpeg filter chain
    verify.py    residual_score (template match + OCR) for cleaned files and the final MP4
    cli.py       `shortkit clean detect|faces|plan|apply|verify|show|fetch-models`

All rects are SOURCE px with the resolution they refer to; times are SOURCE seconds.
"""
