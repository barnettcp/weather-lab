"""
Fetch actual recorded observations from NWS stations defined in config.STATIONS
and store one row per UTC hour per station. Station IDs are explicit in config;
no dynamic discovery is needed. Run via cron - the rolling ACTUALS_LOOKBACK_HOURS
window ensures resilience to missed runs.

Usage:
    python3 fetch_actuals.py
"""

import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import requests

import config
import db

HEADERS = {"User-Agent": config.NWS_USER_AGENT, "Accept": "application/geo+json"}

# NWS cloud cover codes mapped to approximate percentage midpoints.
_CLOUD_PCT = {"SKC": 0, "CLR": 0, "FEW": 19, "SCT": 44, "BKN": 69, "OVC": 100, "VV": 100}


def _nws_val(props, key):
    """Extract the numeric value from an NWS quantity object, or None."""
    obj = props.get(key) or {}
    return obj.get("value")


def _cloud_cover_from_layers(layers):
    """Return the highest cloud cover percentage from a cloudLayers list."""
    if not layers:
        return None
    pcts = [_CLOUD_PCT[lyr["amount"]] for lyr in layers if lyr.get("amount") in _CLOUD_PCT]
    return max(pcts) if pcts else None


def _avg(lst):
    return round(sum(lst) / len(lst), 2) if lst else None


def _max(lst):
    return round(max(lst), 2) if lst else None


def fetch_observations(station_id, start, end):
    url = f"{config.NWS_BASE_URL}/stations/{station_id}/observations"
    params = {"start": start.isoformat(), "end": end.isoformat()}
    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("features", [])


def to_hourly_rows(features, station_id):
    """Bucket raw observations into top-of-the-hour UTC buckets."""
    buckets = defaultdict(lambda: defaultdict(list))

    for feature in features:
        props = feature.get("properties", {})
        ts = props.get("timestamp")
        if ts is None:
            continue

        obs_time = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
        hour_bucket = obs_time.replace(minute=0, second=0, microsecond=0)
        b = buckets[hour_bucket]

        temp = _nws_val(props, "temperature")
        if temp is not None:
            b["temperature_c"].append(temp)

        ws = _nws_val(props, "windSpeed")
        if ws is not None:
            b["wind_speed_kmh"].append(ws * 3.6)

        wd = _nws_val(props, "windDirection")
        if wd is not None:
            b["wind_direction_deg"].append(wd)  # simple avg; imprecise near 0°/360° boundary

        wg = _nws_val(props, "windGust")
        if wg is not None:
            b["wind_gusts_kmh"].append(wg * 3.6)

        precip = _nws_val(props, "precipitationLastHour")
        if precip is not None:
            b["precipitation_mm"].append(precip * 1000)

        cloud_pct = _cloud_cover_from_layers(props.get("cloudLayers") or [])
        if cloud_pct is not None:
            b["cloud_cover_pct"].append(cloud_pct)

    rows = []
    for hour, fields in buckets.items():
        rows.append({
            "observed_time":      hour.isoformat(),
            "station_id":         station_id,
            "temperature_c":      _avg(fields.get("temperature_c", [])),
            "cloud_cover_pct":    _avg(fields.get("cloud_cover_pct", [])),
            "wind_speed_kmh":     _avg(fields.get("wind_speed_kmh", [])),
            "wind_direction_deg": _avg(fields.get("wind_direction_deg", [])),
            "wind_gusts_kmh":     _max(fields.get("wind_gusts_kmh", [])),
            "precipitation_mm":   _avg(fields.get("precipitation_mm", [])),
        })
    return rows


def main():
    db.init_db()
    started_at = datetime.now(timezone.utc)
    end = started_at
    start = end - timedelta(hours=config.ACTUALS_LOOKBACK_HOURS)

    for station in config.STATIONS:
        station_id = station["id"]
        try:
            features = fetch_observations(station_id, start, end)
        except requests.RequestException as e:
            print(f"[fetch_actuals] ERROR {station_id}: {e}", file=sys.stderr)
            db.insert_fetch_log("actuals", started_at.isoformat(), "error",
                                0, str(e), station_id)
            continue

        rows = to_hourly_rows(features, station_id)
        inserted = db.insert_actuals(rows)
        db.insert_fetch_log("actuals", started_at.isoformat(), "success",
                             inserted, station_id=station_id)
        print(f"[fetch_actuals] {station_id}: {len(features)} raw obs "
              f"-> {len(rows)} hourly rows, {inserted} inserted/updated.")


if __name__ == "__main__":
    main()
