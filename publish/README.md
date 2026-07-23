# publish/ — built 2026-07-22, extended 2026-07-22 (session 4)

`generate.py` reads every `*_track.json` (Aurora 0.25 Fine-Tuned, via `sol/run_aurora_tc.py`)
and `*_track_v15.json` (Aurora 1.5 + precipitation, via `sol/run_aurora_tc_v15.py`) GeoJSON
actually present in `sol/output/`, sanitizes bare `NaN`/`Infinity` floats to `null` (Python's
`json` module writes those by default but browser `JSON.parse` throws on them -- fixed at the
source too, in both drivers' GeoJSON writers, but this sanitizes any pre-fix file too), stamps
`source` (`aurora-0.25-finetuned` for the first kind; the v1.5 driver already stamps
`aurora-1.5` and `approximated_input_vars` itself, left as-is) and `generated_at`, and writes a
`manifest.json` listing every published storm/model combination (`has_precip` flags which ones
carry `peak_precip_mm_1h`). No fallback path invents a track for a storm that isn't in
`sol/output/` -- a storm with no file just doesn't appear in the manifest, per this file's
original no-fabrication rule.

Run manually for now: `python3 publish/generate.py` after either Sol driver produces new
tracks. Not wired into any automation yet (that's Phase 1, per the top-level README roadmap).
