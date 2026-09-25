# shortkit — implementation contract (for every agent that writes code here)

This file is the single source of truth for interfaces between modules. Read it fully before
writing code. If you need a change to a shared interface, do NOT edit another module's files:
describe the change under "REQUESTED SHARED CHANGES" in your final report.

## 0. What the system is for

A reusable production system (not a report) that makes YouTube Shorts with the *same editing
structure* as a reference channel (https://youtube.com/@joshuamagazine) using *different
footage*:

    new-source discovery → selection → script & cut plan → edit/render → output QA

Hard rules from the user (verbatim intent; they are acceptance criteria):
- Never fill an unmeasured item with a guess or call it done. Everything that could not be
  measured is status `unmeasured` (Korean label **못 잼**) with its production impact.
- Numeric measurements: `{n, p10, p50, p90}` overall AND per format (`shortkit.util.stats`).
- Screen/text coordinates are always stored with the resolution they refer to.
- Presence items (motion, transitions, BGM, original audio…): `present/absent/unmeasured`
  (있다/없다/못 잼).
- Every setting links: evidence (video, time) → measured value → production-code setting →
  output check. No setting may exist only in a report (enforced by `shortkit preset audit`).
- Fixed style lives in the preset; per-episode coordinates/times live in the episode plan.
- Footage must be different recordings from the reference's; never reproduce the reference
  channel's name/logo/identity marks.
- Captions: written only after actually watching/listening; short natural Korean; never invent
  relations/motives/lines not in the footage; separate roles: title / description / situation /
  speaker (person id) / dialogue (real line) / reaction; do not pre-announce the twist; never
  cover faces/hands/key objects; trim meaningless tails but never cut an important action; do
  not stack the same effect repeatedly or repeat to pad length.
- Audio: BGM identified by title AND version AND speed AND used section; a different part of
  the same song is NOT a match; use a clean music file (never the stem separated from the
  reference). Original sound OFF by default; keep only important lines / a person speaking.
  Remove music already embedded in the source (separate, then check quality). Duck BGM only
  under kept dialogue; no ducking where original audio is off; SFX or cuts are never a reason to
  duck. Never claim a listening check that was not done.
- SFX: placed because of an on-screen *event*, never because of a cut. Per-episode counts and
  type distribution must fall in the format's observed range; SFX without an event = 0;
  |sfx.t − event.t| ≤ 0.3 s.
- Source overlays: no original logo / source overlay / foreign-language burned subtitles in
  the final frame (check top-left/top-right and inner cuts). Order: clean original → crop →
  local restoration. Never crop away the important person/action. Keep provenance records.
- First episode: proposal (source, segment sheet, cover text, 3 title candidates, SFX sheet)
  must be approved before rendering; later episodes need no re-approval.
- QA on the final MP4 only (never "the code/timeline is right so the output is right").
  Same-absolute-time 1-second grid reference vs ours; caption strip; under it a 0.5-second SFX
  strip. Table: 같다/다르다/못 잼, intended changes marked separately. Unmeasured never becomes
  complete.

### Environment
- Platform access depends on the machine's network policy: check with `python -m shortkit doctor --network`. Code that
  talks to YouTube/TikTok/Instagram/Reddit/YouTube Data API must record access status honestly (ok / blocked /
  login_required / error) and never route around a block (no mirrors/proxies). The first build machine's facts are in
  Appendix A.

## 1. Conventions
- Package `shortkit` (Python ≥3.10). CLI `python -m shortkit <area> <cmd>`; each area
  implements `register(parser)` in `shortkit/<area>/cli.py` (see `shortkit/cli.py`).
- Paths: stored paths are root-relative POSIX (`shortkit.paths.relp/absp`). Never write
  absolute paths, user names or machine-specific locations to any stored file.
- JSON/YAML I/O via `shortkit.util.jsonio`; media via `shortkit.util.media` (probe, read_audio,
  write_wav, read_frames, iter_frames, lufs, ffmpeg); hashing via `shortkit.util.hashing`.
- Stats via `shortkit.util.stats` (`pstats`, `pstats_by_group`, `categorical`, `tri_state`,
  labels `TRI_KO`, `QA_KO`).
- Preset access: `shortkit.config.load_preset(name, format_id)` → `Preset`. **Read style values
  only through `preset.get("a.b.c")` / `preset.section("a.b")`** — reads are traced to the
  calling function and become the registry's `code` link. Do not read preset.yaml directly.
- Status vocab (stored English, reported Korean):
  measurement `measured|unmeasured`; presence `present|absent|unmeasured`;
  QA `same|different|unmeasured`; sfx map `have|none|unmeasured` (있음/없음/못 잼).
- Timestamps: UTC ISO-8601 (`jsonio.now_iso()`); times in media are float seconds.
- Output text for humans (reports, tables, CLI summaries) is Korean. Code/comments English.
- Tests: `tests/<area>/test_*.py` (pytest). Heavy ones marked `@pytest.mark.slow`. Tests must
  create their own temporary project root when they write files (copy `shortkit.root` marker
  into `tmp_path` and set `SHORTKIT_ROOT`), or write only under `assets/test/generated/` /
  `episodes/_pytest_*`. Test media: run `python -m shortkit testassets synth`,
  `... fetch-video [--local-dir <folder with the Intel sample-videos clips>]`, `... dirty-source`, and
  `python -m shortkit episode test-source`.
- Multi-agent builds only: when several agents edit the tree at once, each edits only its own files and the orchestrator
  commits (Appendix A). A single agent follows AGENTS.md rule 16 (commit progress and the resume point).

## 2. Preset layers and registry (implemented: `shortkit/config.py`, `shortkit/preset_cli.py`)
`presets/<name>/preset.yaml` (base, PROVISIONAL) ← `measured.yaml` (generated from
`measurements/*.json`) ← `requested_changes.yaml` (user-requested changes, `changes:` subtree).
`settings_registry.yaml` is generated by `shortkit preset sync`.

### Measurement file format — `presets/<name>/measurements/<group>.json`
```json
{"schema": "shortkit.measurement/1", "group": "text_layout", "source_snapshot": "<latest100 captured_at>",
 "items": [
  {"key": "text.roles.title.size_px", "status": "measured|unmeasured", "value": 84,
   "unit": "px", "resolution": [1080, 1920],
   "overall": {"n": 37, "p10": 80, "p50": 84, "p90": 90},
   "by_format": {"F1": {"n": 20, "p10": 80, "p50": 84, "p90": 88, "value": 84}},
   "evidence": [{"video_id": "abc", "t": 1.0, "value": 84, "frame": "presets/.../frames/abc_0001.png"}],
   "method": "OCR bbox cap-height → px", "measured_at": "…", "blocker": null}
 ]}
```
`value` is what production uses (numeric: p50 unless the method says otherwise; categorical:
mode). `shortkit preset apply-measurements` writes these into `measured.yaml`.

### QA check declarations
`shortkit/qa/checks.py` must expose `declarations() -> dict[check_id, list[preset-key glob]]`
so the registry links each style key to the checks that verify it in the output MP4.

## 3. Episode plan — `episodes/<episode_id>/plan.yaml`
JSON Schema: `shortkit/schema/plan.schema.json` (authoritative). Key points:
- `sources[]`: root-relative path + sha256 + warehouse_id; `clean` ops in SOURCE px/time;
  `protected` rects (faces/hands/objects) in SOURCE px/time.
- `timeline[]`: ordered segments (src_in/src_out/speed/zoom/freeze/transition_in/original_audio).
  Output times are derived by the resolver. Crossfade overlaps the previous clip by `dur`.
- `captions[]`: OUTPUT time; role ∈ title/description/situation/speaker/dialogue/reaction;
  `pos` optional canvas-px override; `grounding` = what in the footage supports the line.
- `decorations[]`: arrow/circle/box with keyframes (t relative to decoration start).
- `sfx[]`: type (catalog id), t (OUTPUT), `event {t, desc, kind…}` (required; kind ≠ "cut").
- `bgm`: overrides + `silences` (intentional silence ranges).
- `reveal {t, keywords}`: captions starting before t must not contain the keywords.
- `approval`: first episode (`episode_index: 1`, mode production) must be approved before
  `shortkit episode render`; test mode never needs approval.

## 4. ResolvedEdit IR — `shortkit/edit/ir.py` (authoritative)
`resolve(plan, preset) -> ResolvedEdit`, saved to `episodes/<id>/build/resolved.json`.
Renderer, exporters and QA consume only this IR (+ the output files). Captions and decorations
are rendered by libass from ONE ASS file (`ass_path`) so ffmpeg and MLT draw identical text.

## 5. Episode folder layout
```
episodes/<id>/plan.yaml
episodes/<id>/proposal.md                 # first-episode approval sheet
episodes/<id>/build/{resolved.json, captions.ass, preset_access.json, *.wav}
episodes/<id>/output/<id>.mp4             # master render (ffmpeg)
episodes/<id>/project/{<id>.mlt, <id>.fcpxml, <id>.otio, captions.ass, captions.srt, README.md}
episodes/<id>/qa/{report.json, report.md, compare_sheet.png, defects.jsonl, probes/*.json}
```

## 6. Reference data — `presets/<name>/`
```
reference/latest100.json      snapshot (fixed at analysis time): rank, video_id, url, title,
                              published_at/upload_date, duration, view_count,
                              view_count_checked_at, kind(short|video); plus status/blocker
reference/all_videos.json     whole channel listing (reference only; latest100 wins on conflict)
reference/high_views.json     videos with view_count ≥ 800000 (+ checked_at)
reference/videos/             downloads (git-ignored), reference/downloads.jsonl (sha256, format)
analysis/<video_id>/…         per-video analysis outputs
formats.yaml                  format table (structure vs intro-only variants, representative video)
measurements/*.json           §2
sfx_catalog.json              §8
sfx_map.yaml                  §8
fonts_report.json             font identification (IoU ceiling + candidates)
unresolved.md                 unmeasured items, production impact, resolution state
```

## 7. Fonts
`assets/fonts/manifest.yaml` lists candidate fonts `{name, file, url, sha256, license}`;
`shortkit doctor --fetch-fonts` downloads into `assets/fonts/` (git-ignored) and verifies
sha256. System fonts are found with fontconfig (`fc-match`/`fc-list`) when available.

## 8. SFX catalog and map
`sfx_catalog.json`:
```json
{"schema": "shortkit.sfx_catalog/1", "preset_id": "joshuamagazine-v1", "status": "measured|unmeasured",
 "blocker": null, "basis": {"videos": ["..."], "n_videos": 50, "separator": "demucs htdemucs"},
 "types": [{
   "type_id": "whoosh_a", "label": "휙(스윕)", "class": "edit_sfx|onsite_sound|intentional_silence",
   "fingerprint": {"method": "...", "centroid": "presets/.../sfx_fp/whoosh_a.npy"},
   "per_video_count": {"overall": {"n":50,"p10":0,"p50":1,"p90":3}, "by_format": {"F1": {...}}},
   "prev_caption_role": {"n":…, "counts": {...}, "mode": "reaction"},
   "screen_event": {"n":…, "counts": {"text_pop": 5, "zoom_in": 3}, "mode": "text_pop"},
   "emotion": {"n":…, "counts": {"surprise": 4}, "mode": "surprise"},
   "placement_rule": "…",
   "offset_to_event_s": {"n":…, "p10":…, "p50":…, "p90":…},
   "gain_db_rel_mix": {"n":…, "p10":…, "p50":…, "p90":…},
   "examples": [{"video_id": "…", "t": 12.5}, … at least 3 distinct videos]}]}
```
`sfx_map.yaml`: `types: {type_id: {status: have|none|unmeasured, file, similarity, method,
alternatives, needed_asset}}` + `library_root` (user-provided SFX warehouse; overridable in
`local.yaml`).

## 9. Source warehouse — `warehouse/`
`candidates.jsonl` one record per candidate:
```
{id, platform, url, title, original_author, original_url, reposter, keywords[],
 views (int|null), views_checked_at, views_source ('platform_metadata'|'unavailable'),
 likes (separate; NEVER converted to views), published_at, first_seen_at,
 duration, width, height, download_path, sha256, reference_overlap {excluded, matched_video_id, method, distance},
 scores {recency, intensity, reversal, quality, format_fit, total}, selection_reason, status
 (candidate|selected|rejected|used|excluded), access {platform_status: ok|blocked|login_required|error, note}}
```
`exclusions.jsonl` (reference footage fingerprints / URLs), `search_log.jsonl` (every query,
platform, time, result count, access status), `source_accounts.json` (repeatedly used source
accounts/keywords traced from the reference).

## 10. QA
`shortkit qa run --episode <id> [--reference <mp4>]` measures the final MP4 and writes rows:
```
{check_id, item (Korean), category, reference, expected, observed, tolerance,
 status: same|different|unmeasured, intended_change: bool, change_ref, evidence {t, frame}, note}
```
Gate passes only when no row is `different` without `intended_change`, required rows are not
`unmeasured`, SFX-without-event = 0, every SFX within ±0.3 s of its event. Defects go to
`defects.jsonl` with {id, check_id, found, fix, recheck_same_cases[], final_gate}.
Compare sheet: 1-second grid at the same absolute times (reference row / ours row), each with a
caption strip, and under it a 0.5-second SFX strip.

## 11. Cross-module APIs and files (agreed names — implement exactly)

### Per-reference-video analysis files (written by reference visual/audio modules)
`presets/<name>/analysis/<video_id>/`
- `shots.json` `{"video_id", "resolution": [w,h], "fps", "duration", "cuts": [{"t", "type": "cut|flash|crossfade", "score"}]}`
- `captions.json` `{"video_id", "resolution": [w,h], "items": [{"start", "end", "role", "text", "bbox": [x,y,w,h], "motion_in": "pop|fade|slide|none|unmeasured", "style": {...measured style...}}]}`
- `motion.json` `{"video_id", "resolution": [w,h], "events": [{"t", "end", "type": "zoom_in|zoom_out|freeze|speed|flash", "value"}]}`
- `layout.json` `{"video_id", "resolution": [w,h], "video_region": {x,y,w,h}|null, "background": "color|blur_source|unmeasured", "roles": {role: {...measured style...}}}`
- `audio/bgm.json`, `audio/original.json`, `audio/sfx_events.json` `{"video_id", "events": [{"t", "dur", "type_id"|null, "class", "gain_db", "fp": "<npy path>"}]}`
- `review/` contact sheet + packet for human/agent viewing; `labels` are filled only by someone who actually watched.

### Exclusions — `warehouse/exclusions.jsonl` (written by reference trace step, read by sourcing)
`{"kind": "reference_footage", "ref_video_id", "ref_url", "original_urls": [], "phash": ["<16-hex imagehash.phash>"...],
  "frame_times": [...], "added_at", "added_by"}` and `{"kind": "url", "url", "reason", "added_at", "added_by"}`.
Match rule (sourcing): candidate keyframe phash vs any exclusion phash Hamming ≤ 10 on ≥ 3 keyframes, or URL/original_url equality → excluded.

### Function names
- `shortkit.clean.apply.inpaint_video(src: Path, rects: list[dict], out: Path) -> dict`  (rects: {x,y,w,h,start,end} SOURCE px/time)
- `shortkit.clean.verify.residual_score(video: Path, rect: dict, template_png: Path|None, times: list[float], text: str|None) -> dict`
- `shortkit.reference.typography.font_iou(crop_rgb, text, font_path, size_hint_px, fill_rgb=None, outline_rgb=None) -> dict {iou, scale, dx, dy}`
- `shortkit.reference.typography.register(subparsers)` and `shortkit.reference.audio_cli.register(subparsers)` —
  called by `shortkit/reference/cli.py` (inside try/except ImportError) to add their `ref` sub-commands.
- `shortkit.fonts.find_font(name) -> Path|None` (exact family match; never silently accept a fallback),
  `shortkit.fonts.fetch_all() -> dict`.
- `shortkit.edit.export_mlt.export(resolved, out_dir: Path) -> Path`, same for `export_fcpxml`, `export_otio`;
  `shortkit.edit.verify_project.verify(resolved, master_mp4: Path, project_file: Path) -> dict`;
  `shortkit.edit.project_readme.write(resolved, out_dir: Path, decisions: dict) -> Path`.
- `shortkit.qa.checks.declarations() -> dict[str, list[str]]`.
- `shortkit.edit.resolve.resolve_episode(episode_id) -> ResolvedEdit` (writes build/resolved.json, captions.ass, preset_access.json);
  `shortkit.edit.render.render(resolved) -> Path`.

## 12. As-built conventions (decided during integration — binding)

- **Font names in ASS**: styles name a face the way libass 0.17 matches it (Windows/GDI rule): PostScript name for CFF
  outlines, Windows full name (name id 4) for TrueType outlines; the resolver confirms the name against libass's fontselect
  log (`captions.probe_ass_names`). The style Bold field is −1 only for faces of weight ≥ 550, else 0 (libass reads it as a
  boolean and would embolden synthetically). `render.check_output_fonts` checks the exact face (PostScript name, index,
  file) with the characters each style really renders and refuses glyph fallback and synthetic bold.
- **size_px** = font EM size in canvas px (renderer: ASS Fontsize = size_px × (winAscent+winDescent)/unitsPerEm;
  line pitch = size_px × line_spacing). The reference analyzer writes size_px in the same unit (plus `ass_fontsize`).
- **box.pad_x/pad_y** = box edge − visible ink edge (ink incl. outline).
- **Audio gain semantics**: `audio.bgm.gain_db`, `audio.sfx.gain_db_default`, plan `sfx[].gain_db`, `audio.original.keep_gain_db`
  are levels at the FINAL program loudness; final loudness normalisation is a small trim. BGM is never reduced by a limiter.
- **Measurement groups** (file names under measurements/): `visual_{canvas,text,tone,motion,structure}` (reference visual),
  `audio` (`ref audio-measure`), `font_identity` (`ref fonts`; value only when the verdict is identical).
- **captions.json** items may carry `role_reason, t_rep, lines[] {text,bbox,ink_h,ocr_conf,hangul_share}, frame, ocr_conf,
  motion_out, style{...}`; role `identity_mark` = text matching `identity_exclusions.forbidden_text` (never a style sample).
- **formats.yaml**: `table[].members` (alias `videos`) and top-level `assignments {video_id: format_id}`.
- **Exclusions**: reference footage is registered with `shortkit.sourcing.exclusions.add_reference_footage(...)` so reference and
  candidate hashing are identical (grayscale ≤480 px, flat frames skipped, borders trimmed, footage-region crop).
- **source_accounts.json**: `{status, blocker, traced_at, accounts:[{platform, handle, url, count, evidence:[{ref_video_id,t}],
  verified_by_text}], keywords:[{keyword, platforms, count, evidence}]}`.
- **candidates.jsonl** extra fields: platform_id, views_field, views_history[], views_note, likes_checked_at, reddit_score,
  original_author_basis, credits[], reviews[] {watched_by, watched_at, intensity, reversal, format_fit, notes, watermark, format_id,
  original_published_at, watched_file_sha256}, selection {at, by, accepted_unmeasured[]}, status_history[], used_in[], download{},
  quality{}, optional `alternates` (clean originals of the same content). Status transitions are enforced in code.
- **Library paths** outside the project are stored as `$music_library_root/...` / `$sfx_library_root/...` tokens
  (expanded with `shortkit.reference.separation.resolve_stored`), never as absolute paths.
- **sfx_events.json** `events` also contain `class: intentional_silence` (fp null); `unmeasured_coverage` lists intervals where SFX
  could not be measured (no vocals stem) — per-video counts there are lower bounds.
- **Project export**: `project/verify.json` holds the MLT melt-render comparison at top level; FCPXML/OTIO are under `other_formats`
  (always unmeasured here — no NLE available); `project/export_decisions.json` records every export decision (keys mlt/fcpxml/otio)
  and feeds the generated project README.
- **Overlay provenance**: `warehouse/overlays/<source sha256>.json` (tracked) + `warehouse/overlays/<sha>/` crops (ignored).
- **OCR**: run tesseract with `OMP_THREAD_LIMIT=1` (shared machines otherwise stall).
- **Faces**: OpenCV ≥5 wheels have no Haar cascades; `shortkit clean fetch-models` stores sha256-pinned XMLs in
  `warehouse/cache/models/haarcascades/`; `shortkit.clean.faces` runs them (numpy implementation if cv2 lacks CascadeClassifier).

- **SFX count rule**: per-episode SFX counts count only catalog types of class `edit_sfx` (plus `intentional_silence` when
  the plan has `bgm.silences`); `onsite_sound` types are the reference footage's own sound — never counted, never placeable.
  Allowed count per type and for the total = [floor(p10), ceil(p90)] of the observed per-video counts of the plan's format
  (by_format[F], else overall) OR any count observed in at least one of those reference videos; counts from
  lower_bound_videos are lower bounds (warning).
- **QA font rows**: the REQUIRED font row is per role (`caption.font:role_<role>`): pooled rest-frame crops of all captions of
  the role vs the bootstrapped ceiling of the pooled median. Per-caption font rows are informational (a per-caption
  'different' still fails the gate). Defects can be `superseded` when a check id is replaced.

### 12.1 Coverage-round additions
- **Access logs**: every episode command saves `episodes/<id>/build/preset_access_<command>.json`; QA saves
  `episodes/<id>/qa/preset_access.json`; `config.all_access_logs()` collects all of them for `preset sync`.
  API: `resolve_episode(episode_id, preset=None)`, `render(resolved, *, allow_unmeasured=False, preset=None)`,
  `plan.approval_state_for(plan, preset)` is the approval gate (a production plan without episode_index counts as a first episode).
- **Measurement groups** add `manual` (`presets/<p>/manual_observations.csv` rows with `watched=yes` + `observed_by`
  → `ref manual-aggregate` → `measurements/manual.json`) for decoration style, `text.tone.emoji`, `cover.*`.
  `config.load_measurement_items` is the only loader: measured beats unmeasured; two measured items for one key raise.
- **New per-video analysis fields**: motion.json zoom events `ease_fit`, `recenter_fit`, `scale_curve`, `decorations` (experimental
  automatic detector); shots.json flash `scope`; `analysis/<id>/audio/loudness.json`; bgm.json `match.loop`; original.json
  `original_edges`, `kept_speech_level`, `silences.items[].ramps`. Re-run `ref analyze` without `--skip-existing` for old analyses.
- **Level semantics**: `audio.original.keep_gain_db` = kept speech loudness relative to programme loudness (LU); renderer gain
  = T + keep_gain_db − L_src. Ramp keys are expressed in the renderer's shapes (silence: dB-linear 0→−120 dB; kept originals: linear amplitude).
- **Exporters** read `build/fg_gain.json` (fallback: stems / `render.pre_norm_stems`); MLT adds +3.01 dB to mono clips because
  melt upmixes mono at −3 dB (measured on melt 7.22). `project/verify.json` carries `master_sha256` and warns when the master is older
  than resolved.json.
- **Reference download** caps the SHORT side (`format_sort res:<N>`), so vertical Shorts come at 1080×1920.
- **Exit code 3** from `ref collect/download/analyze/aggregate/trace/classify` means "no reference data (blocked or empty)" — the
  unmeasured files were still written.


## Appendix A. First build record (2026-09-24) — historical, does not apply to other machines

### Environment facts of the first build machine
- Network policy blocks youtube.com, googlevideo.com, i.ytimg.com, tiktok.com, instagram.com,
  reddit.com, lens.google.com, namu.wiki, freesound.org, pixabay.com, dl.fbaipublicfiles.com
  (Demucs weights), huggingface.co, archive.org. Allowed: github.com / raw.githubusercontent.com
  (public repos), pypi, npm, ubuntu apt.
- Therefore: code that talks to those platforms must be written against their documented
  formats (yt-dlp info-dict fields, Reddit JSON, YouTube Data API v3) and unit-tested with
  **clearly labelled synthetic fixtures**; mark such paths "not live-tested here". Never try to
  route around the block (no mirrors/proxies/Invidious etc.).
- Installed: Python 3.11, ffmpeg 6.1.1 (libass, libx264, xfade, delogo, zoompan, loudnorm,
  rubberband, sidechaincompress), melt 7.22 (affine, freeze, volume, qtblend, avfilter.subtitles,
  avfilter.ass, kdenlivetitle), tesseract 5 (kor, eng), fpcalc (chromaprint), espeak-ng (ko),
  sox, Korean fonts (Noto Sans CJK KR all weights, Nanum*), numpy/scipy/opencv-headless/pillow/
  pyyaml/jsonschema/yt-dlp/pytesseract/opentimelineio/imagehash/pytest. NOT installed: torch,
  demucs (weights host blocked). 4 CPUs, no GPU.
- Candidate OFL Korean fonts (sha256-pinned) are cached in `/home/user/fontcache` on this
  machine only; code must fetch them via a manifest (see §7), never hard-code that path.


- The system was built by an orchestrator running several agents in parallel on one working tree; each agent owned a
  disjoint set of files, did not run git state commands, and the orchestrator committed. Paths such as `/home/user/...`
  above existed only on that machine.
