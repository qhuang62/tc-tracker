"""Turn sol/output/*_track.json into what web/ actually reads.

Per this directory's README: every published layer carries its own
source/timestamp, and a cycle with no data must never be backfilled or
faked. This script only ever copies tracks that actually exist in
sol/output/ -- it has no fallback path that invents one.

Also sanitizes bare NaN/Infinity floats (which Python's json module writes
by default but browser JSON.parse rejects) to null, for any track written
before that was fixed at the source in sol/run_aurora_tc.py.
"""

from __future__ import annotations

import json
import math
import shutil
from datetime import datetime, timezone
from pathlib import Path

SOL_OUTPUT_DIR = Path(__file__).parent.parent / "sol" / "output"
PUBLISH_DIR = Path(__file__).parent
FINETUNED_SOURCE = "aurora-0.25-finetuned"

# ATCF basin-code prefix (first 2 letters of an id like "al022026") -> the
# web UI's region label. al/ep/cp are all NHC's area of responsibility
# (Atlantic + both Pacific sub-basins NHC itself advises on); wp is JTWC's
# Western Pacific -- kept here as the single place that maps a basin to a
# display region, rather than repeating basin logic in the frontend.
REGION_BY_BASIN = {
    "al": "North Atlantic (U.S. East Coast)", "ep": "North Atlantic (U.S. East Coast)",
    "cp": "North Atlantic (U.S. East Coast)", "wp": "Western North Pacific (East Asia)",
}
# Storms with no fetchable ATCF id yet (e.g. a JTWC-tracked system before a
# JTWC ingest module exists) -- set explicitly here rather than leaving them
# unclassified. Remove an entry once that storm has a real ingest path
# supplying its own atcf_id.
REGION_OVERRIDES: dict[str, str] = {}


def _region_for(storm_name: str) -> str:
    observed_path = SOL_OUTPUT_DIR / f"{storm_name}_observed.json"
    if observed_path.exists():
        try:
            geojson = json.loads(observed_path.read_text())
            line_feature = next(f for f in geojson["features"] if f["geometry"]["type"] == "LineString")
            atcf_id = line_feature["properties"].get("atcf_id")
            if atcf_id:
                return REGION_BY_BASIN.get(atcf_id[:2].lower(), "Other")
        except (json.JSONDecodeError, KeyError, StopIteration):
            pass
    return REGION_OVERRIDES.get(storm_name, "Other")


def _sanitize(obj):
    if isinstance(obj, float):
        return None if (math.isnan(obj) or math.isinf(obj)) else obj
    if isinstance(obj, dict):
        return {k: _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    return obj


def _publish_one(track_path: Path, storm_name: str, default_source: str, generated_at: str) -> dict:
    geojson = _sanitize(json.loads(track_path.read_text()))
    line_feature = next(f for f in geojson["features"] if f["geometry"]["type"] == "LineString")
    # run_aurora_tc_v15.py already stamps its own source/approximated_input_vars;
    # run_aurora_tc.py (Fine-Tuned) doesn't, so fill in the default here.
    line_feature["properties"].setdefault("source", default_source)
    line_feature["properties"]["generated_at"] = generated_at

    out_path = PUBLISH_DIR / track_path.name
    out_path.write_text(json.dumps(geojson, indent=2))

    point_features = [f for f in geojson["features"] if f["geometry"]["type"] == "Point"]
    has_precip = any(p["properties"].get("peak_precip_mm_1h") is not None for p in point_features)
    entry = {
        "storm_name": storm_name,
        "region": _region_for(storm_name),
        "file": out_path.name,
        "source": line_feature["properties"]["source"],
        "generated_at": generated_at,
        "n_points": len(point_features),
        "init_time": point_features[0]["properties"]["time"] if point_features else None,
        "has_precip": has_precip,
    }
    if "approximated_input_vars" in line_feature["properties"]:
        entry["approximated_input_vars"] = line_feature["properties"]["approximated_input_vars"]
    print(f"Published {out_path} ({len(point_features)} points, source={entry['source']})")
    return entry


def _publish_field_layers(storm_name: str, tag: str) -> list[dict]:
    """Copy every gridded-field manifest + its PNG frames (e.g.
    bertha_v15_precip_field/, bertha_ft_wind_field/) into publish/, for
    whichever field layers this storm's driver produced. `tag` ("ft" or
    "v15") restricts the glob to this driver's own files -- both drivers can
    produce a wind field for the *same* storm_name, so without the tag this
    would cross-attribute one driver's field layer onto the other's track
    entry (real bug, found 2026-07-22: the v1.5 precip field was showing up
    on the Fine-Tuned bertha entry too, since Fine-Tuned has no precip at
    all).
    """
    layers = []
    for manifest_path in sorted(SOL_OUTPUT_DIR.glob(f"{storm_name}_{tag}_*_field_manifest.json")):
        field_manifest = json.loads(manifest_path.read_text())
        # e.g. "bertha_precip_field_manifest.json" -> "bertha_precip_field"
        dir_name = manifest_path.stem.removesuffix("_manifest")
        src_dir = SOL_OUTPUT_DIR / dir_name
        dst_dir = PUBLISH_DIR / dir_name
        dst_dir.mkdir(exist_ok=True)
        for frame in field_manifest["frames"]:
            shutil.copy2(src_dir / Path(frame["file"]).name, dst_dir / Path(frame["file"]).name)
        out_path = PUBLISH_DIR / manifest_path.name
        out_path.write_text(json.dumps(field_manifest, indent=2))
        print(f"Published {out_path} ({len(field_manifest['frames'])} frames)")
        layers.append({"field": field_manifest["field"], "manifest": out_path.name})
    return layers


def _publish_ensemble(storm_name: str) -> str | None:
    """Copy a run_aurora_tc_v15_ensemble.py output (per-lead-time member
    spread envelope) into publish/, if one exists for this storm."""
    src_path = SOL_OUTPUT_DIR / f"{storm_name}_ensemble.json"
    if not src_path.exists():
        return None
    data = _sanitize(json.loads(src_path.read_text()))
    out_path = PUBLISH_DIR / src_path.name
    out_path.write_text(json.dumps(data, indent=2))
    print(f"Published {out_path} ({data.get('n_members')} members, {len(data.get('steps', []))} steps)")
    return out_path.name


def _publish_observed(storm_name: str, generated_at: str) -> dict | None:
    """Copy an observed-track ingest output (build_observed_track.py for NHC,
    build_observed_track_jtwc.py for JTWC) into publish/, if one exists for
    this storm. Its own manifest entry -- not a model track, so it has no
    field_layers/ensemble, and the web UI groups it as "Observed" rather than
    under "Models". `source` is read from the file itself ("nhc-best-track"
    or "jtwc-best-track", whichever ingest script wrote it) rather than
    assumed -- hardcoding "nhc-best-track" here was a real bug (found
    2026-07-23) that mislabeled a real JTWC-sourced track as NHC's.
    """
    src_path = SOL_OUTPUT_DIR / f"{storm_name}_observed.json"
    if not src_path.exists():
        return None
    geojson = _sanitize(json.loads(src_path.read_text()))
    line_feature = next(f for f in geojson["features"] if f["geometry"]["type"] == "LineString")
    line_feature["properties"]["generated_at"] = generated_at
    out_path = PUBLISH_DIR / src_path.name
    out_path.write_text(json.dumps(geojson, indent=2))

    point_features = [f for f in geojson["features"] if f["geometry"]["type"] == "Point"]
    entry = {
        "storm_name": storm_name,
        "region": _region_for(storm_name),
        "file": out_path.name,
        "source": line_feature["properties"].get("source", "nhc-best-track"),
        "generated_at": generated_at,
        "n_points": len(point_features),
        "init_time": point_features[0]["properties"]["time"] if point_features else None,
    }
    print(f"Published {out_path} ({len(point_features)} observed points, source={entry['source']})")
    return entry


def _publish_global_weather() -> list[dict]:
    """Copy run_aurora_weather_global.py's global field manifests + PNG
    frames into publish/ -- the "Weather" mode's data, independent of any
    tracked storm. If multiple cycles exist (repeated pipeline runs), only
    the newest per field is published, so the web UI always shows one
    current global snapshot rather than an ever-growing pile of old cycles.
    """
    by_field: dict[str, Path] = {}
    for manifest_path in sorted(SOL_OUTPUT_DIR.glob("global_*_*_field_manifest.json")):
        field = json.loads(manifest_path.read_text())["field"]
        # Filenames sort by cycle timestamp (global_<YYYYMMDDHH>_...), so the
        # last match per field in sorted order is the newest cycle.
        by_field[field] = manifest_path

    layers = []
    for field, manifest_path in by_field.items():
        field_manifest = json.loads(manifest_path.read_text())
        dir_name = manifest_path.stem.removesuffix("_manifest")
        src_dir = SOL_OUTPUT_DIR / dir_name
        dst_dir = PUBLISH_DIR / dir_name
        dst_dir.mkdir(exist_ok=True)
        for frame in field_manifest["frames"]:
            shutil.copy2(src_dir / Path(frame["file"]).name, dst_dir / Path(frame["file"]).name)
        out_path = PUBLISH_DIR / manifest_path.name
        out_path.write_text(json.dumps(field_manifest, indent=2))
        print(f"Published {out_path} ({len(field_manifest['frames'])} frames, init_time={field_manifest['init_time']})")
        layers.append({"field": field, "manifest": out_path.name, "init_time": field_manifest["init_time"]})
    return layers


def publish_all() -> list[dict]:
    generated_at = datetime.now(timezone.utc).isoformat()
    manifest_entries = []

    for track_path in sorted(SOL_OUTPUT_DIR.glob("*_track.json")):
        storm_name = track_path.stem.removesuffix("_track")
        entry = _publish_one(track_path, storm_name, FINETUNED_SOURCE, generated_at)
        field_layers = _publish_field_layers(storm_name, "ft")
        if field_layers:
            entry["field_layers"] = field_layers
        manifest_entries.append(entry)

    for track_path in sorted(SOL_OUTPUT_DIR.glob("*_track_v15.json")):
        storm_name = track_path.stem.removesuffix("_track_v15")
        # Fallback default_source unused in practice -- run_aurora_tc_v15.py
        # always stamps "aurora-1.5" itself, this only covers a hand-edited file.
        entry = _publish_one(track_path, storm_name, "aurora-1.5", generated_at)
        field_layers = _publish_field_layers(storm_name, "v15")
        if field_layers:
            entry["field_layers"] = field_layers
        ensemble_file = _publish_ensemble(storm_name)
        if ensemble_file:
            entry["ensemble"] = ensemble_file
        manifest_entries.append(entry)

    # Observed tracks can exist for a storm with no Aurora run yet (or vice
    # versa) -- glob independently rather than only checking storm_names_seen.
    for observed_path in sorted(SOL_OUTPUT_DIR.glob("*_observed.json")):
        storm_name = observed_path.stem.removesuffix("_observed")
        entry = _publish_observed(storm_name, generated_at)
        if entry:
            manifest_entries.append(entry)

    weather_layers = _publish_global_weather()

    manifest = {"generated_at": generated_at, "storms": manifest_entries, "weather_layers": weather_layers}
    (PUBLISH_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {PUBLISH_DIR / 'manifest.json'} ({len(manifest_entries)} storms, {len(weather_layers)} weather layers)")
    return manifest_entries


if __name__ == "__main__":
    if not any(SOL_OUTPUT_DIR.glob("*_track*.json")):
        raise SystemExit(
            f"No tracks found in {SOL_OUTPUT_DIR} -- run sol/run_aurora_tc.py "
            "or sol/run_aurora_tc_v15.py first."
        )
    publish_all()
