"""
Fetch actual recorded temperatures from the nearest NWS observation station
and store one row per UTC hour (averaging if a station reported more than
once within the hour). Run this via cron, e.g. once a day - it always pulls
the last ACTUALS_LOOKBACK_HOURS hours, so a missed run or two just gets
backfilled next time.

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


def discover_station():
    """Find the nearest observation station for the configured lat/lon and
    cache it in the meta table so we don't re-discover it every run."""
    cached = db.get_meta("nws_station_id")
    if cached:
        return cached

    url = f"{config.NWS_BASE_URL}/points/{config.LATITUDE},{config.LONGITUDE}/stations"
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    features = resp.json().get("features", [])
    if not features:
        raise RuntimeError("NWS returned no observation stations for this location.")

    # Stations are returned nearest-first.
    station_id = features[0]["properties"]["stationIdentifier"]
    db.set_meta("nws_station_id", station_id)
    print(f"[fetch_actuals] Discovered nearest station: {station_id} "
          f"({features[0]['properties'].get('name', '')})")
    return station_id


def fetch_observations(station_id, start, end):
    url = f"{config.NWS_BASE_URL}/stations/{station_id}/observations"
    params = {"start": start.isoformat(), "end": end.isoformat()}
    resp = requests.get(url, headers=HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json().get("features", [])


def to_hourly_rows(features, station_id):
    """Bucket raw observations (which can arrive every 20-60 min) into
    top-of-the-hour UTC buckets, averaging temperature within each bucket."""
    buckets = defaultdict(list)

    for feature in features:
        props = feature.get("properties", {})
        ts = props.get("timestamp")
        temp = props.get("temperature", {}).get("value")
        if ts is None or temp is None:
            continue  # station sometimes reports without a valid temp

        obs_time = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(timezone.utc)
        hour_bucket = obs_time.replace(minute=0, second=0, microsecond=0)
        buckets[hour_bucket].append(temp)

    rows = []
    for hour, temps in buckets.items():
        rows.append({
            "observed_time": hour.isoformat(),
            "temperature_c": round(sum(temps) / len(temps), 2),
            "station_id": station_id,
        })
    return rows


def main():
    db.init_db()

    try:
        station_id = discover_station()
    except requests.RequestException as e:
        print(f"[fetch_actuals] ERROR discovering station: {e}", file=sys.stderr)
        sys.exit(1)

    end = datetime.now(timezone.utc)
    start = end - timedelta(hours=config.ACTUALS_LOOKBACK_HOURS)

    try:
        features = fetch_observations(station_id, start, end)
    except requests.RequestException as e:
        print(f"[fetch_actuals] ERROR fetching observations: {e}", file=sys.stderr)
        sys.exit(1)

    rows = to_hourly_rows(features, station_id)
    inserted = db.insert_actuals(rows)
    print(f"[fetch_actuals] {end.isoformat()}: station {station_id}, "
          f"{len(features)} raw observations -> {len(rows)} hourly rows, "
          f"{inserted} inserted/updated.")


if __name__ == "__main__":
    main()
