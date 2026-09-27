"""
Fetch hourly forecasts from Open-Meteo for every configured station and
forecast model, storing each as its own set of rows stamped with the fetch
time. Run via cron - e.g. at 06:00 and 18:00 UTC to capture lead-time
evolution for each target hour.

Usage:
    python3 fetch_forecast.py
"""

import sys
from datetime import datetime, timezone

import requests

import config
import db


def _get(lst, i):
    return lst[i] if i < len(lst) else None


def fetch_forecast(station, model):
    params = {
        "latitude":         station["latitude"],
        "longitude":        station["longitude"],
        "hourly":           ("temperature_2m,apparent_temperature,cloud_cover,"
                             "wind_speed_10m,wind_direction_10m,"
                             "wind_gusts_10m,precipitation"),
        "temperature_unit": "celsius",
        "timezone":         "UTC",
        "forecast_days":    config.FORECAST_DAYS,
        "models":           model,
    }
    resp = requests.get(config.OPEN_METEO_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def to_rows(payload, fetched_at, station, model):
    hourly     = payload.get("hourly", {})
    times      = hourly.get("time", [])
    temps      = hourly.get("temperature_2m", [])
    apparent   = hourly.get("apparent_temperature", [])
    cloud      = hourly.get("cloud_cover", [])
    wind_speed = hourly.get("wind_speed_10m", [])
    wind_dir   = hourly.get("wind_direction_10m", [])
    wind_gusts = hourly.get("wind_gusts_10m", [])
    precip     = hourly.get("precipitation", [])

    rows = []
    for i, t in enumerate(times):
        target_time = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
        lead_hours = (target_time - fetched_at).total_seconds() / 3600.0

        if target_time <= fetched_at:
            continue

        rows.append({
            "fetched_at":             fetched_at.isoformat(),
            "target_time":            target_time.isoformat(),
            "lead_hours":             round(lead_hours),
            "temperature_c":          _get(temps, i),
            "apparent_temperature_c": _get(apparent, i),
            "cloud_cover_pct":        _get(cloud, i),
            "wind_speed_kmh":         _get(wind_speed, i),
            "wind_direction_deg":     _get(wind_dir, i),
            "wind_gusts_kmh":         _get(wind_gusts, i),
            "precipitation_mm":       _get(precip, i),
            "model":                  model,
            "station_id":             station["id"],
            "latitude":               station["latitude"],
            "longitude":              station["longitude"],
        })
    return rows


def main():
    db.init_db()
    fetched_at = datetime.now(timezone.utc)

    for station in config.STATIONS:
        for model in config.FORECAST_MODELS:
            try:
                payload = fetch_forecast(station, model)
            except requests.RequestException as e:
                print(f"[fetch_forecast] ERROR {station['id']}/{model}: {e}",
                      file=sys.stderr)
                db.insert_fetch_log("forecast", fetched_at.isoformat(), "error",
                                    0, str(e), station["id"])
                continue

            rows = to_rows(payload, fetched_at, station, model)
            inserted = db.insert_forecasts(rows)
            db.insert_fetch_log("forecast", fetched_at.isoformat(), "success",
                                 inserted, station_id=station["id"])
            print(f"[fetch_forecast] {station['id']}/{model}: "
                  f"{len(rows)} hourly points, {inserted} new rows.")


if __name__ == "__main__":
    main()
