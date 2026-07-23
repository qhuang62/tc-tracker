# web/ — built 2026-07-22

`index.html` — single self-contained static page (Leaflet via CDN, no build step). Fetches
`../publish/manifest.json` then each storm's `../publish/<name>_track.json`, draws the dashed
track plus a color-coded circle marker per timestep (color = Aurora's own raw 10m wind,
Saffir-Simpson-style bucketing) with a popup (valid time, position, wind, MSLP, source,
generated_at). Fits the map bounds to whatever storms are in the manifest.

Must be served over HTTP (`python -m http.server` from the repo root, then open
`http://localhost:8000/web/`) — opening the file directly (`file://`) will not work, browsers
block `fetch()` of local files under that protocol. This wasn't solved, just not needed yet
since "no backend" only ruled out a server-side app, not `python -m http.server`.

Not yet done, deferred until there's a reason to need them:
- Time slider / lead-time frame scrubbing (all points currently render at once).
- Model toggle (Aurora / IFS / AIFS / NHC-JTWC) — only Aurora exists right now.
- The ENSO Tracker Cyclone Tracker page's exact interaction pattern wasn't reverse-engineered;
  this is a simpler first pass, same color convention only.
