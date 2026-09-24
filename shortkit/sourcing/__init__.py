"""New-source warehouse (source discovery -> exclusion of reference footage -> ranking -> selection ->
download with provenance).  See warehouse/README.md (Korean) and docs/CONTRACT.md §9 / §11.

Modules:
  platforms/   search adapters (YouTube, TikTok, Instagram via yt-dlp; Reddit public JSON)
  warehouse    candidates.jsonl / search_log.jsonl records, upsert by (platform, id)
  exclusions   reference-footage fingerprints (pHash) and URL rules
  score        views ranking (confirmed only), recency, review-based items, quality, selection rules
  download     yt-dlp download + sha256 + format info (+ manual file intake)
  keywords     query sets (reference-derived vs user-added)
  cli          `shortkit source ...`
"""
