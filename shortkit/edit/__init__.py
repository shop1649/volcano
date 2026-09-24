"""Edit core: plan -> validation -> ResolvedEdit -> ffmpeg master render; first-episode proposal.

Modules (import lazily; heavy deps only where needed):
  plan       plan.yaml load + JSON-schema validation + canonical sha256 + approval block
  validate   rule checks -> issues [{severity, code, message_ko, where}]
  resolve    plan + preset -> ResolvedEdit (ir.py); writes build/{resolved.json, captions.ass, ...}
  captions   exact font resolution, metrics, layout, the ONE ASS file (captions + decorations)
  audio      audio plan (BGM, ducking only under kept dialogue, silences, originals, SFX)
  sfxmap     sfx_catalog.json / sfx_map.yaml access
  render     numpy/OpenCV compositor + libass + numpy audio mix -> MP4
  proposal   first-episode approval sheet (Korean)
  cli        `shortkit episode ...`
"""
