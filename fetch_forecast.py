"""
Fetch the current hourly forecast from Open-Meteo and store every hour of
it, stamped with the time we fetched it. Run this via cron - once a day is
enough to build a bias dataset, but running it a few times a day (e.g.
06:00 and 18:00) lets you see how the forecast for the same target hour
changes as the lead time shrinks.

Usage:
    python3 fetch_forecast.py
"""

import sys
from datetime import datetime, timezone

import requests

import config
import db


def fetch_forecast():
    params = {
        "latitude": config.LATITUDE,
        "longitude": config.LONGITUDE,
        "hourly": "temperature_2m,apparent_temperature",
        "temperature_unit": "celsius",
        "timezone": "UTC",           # keep everything in UTC in the DB
        "forecast_days": config.FORECAST_DAYS,
        "models": config.FORECAST_MODEL,
    }
    resp = requests.get(config.OPEN_METEO_URL, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def to_rows(payload, fetched_at):
    hourly = payload.get("hourly", {})
    times = hourly.get("time", [])
    temps = hourly.get("temperature_2m", [])
    apparent = hourly.get("apparent_temperature", [])

    rows = []
    for i, t in enumerate(times):
        # Open-Meteo returns naive ISO strings like "2026-07-19T14:00"
        # when timezone=UTC; treat them as UTC explicitly.
        target_time = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
        lead_hours = (target_time - fetched_at).total_seconds() / 3600.0

        rows.append({
            "fetched_at": fetched_at.isoformat(),
            "target_time": target_time.isoformat(),
            "lead_hours": round(lead_hours, 3),
            "temperature_c": temps[i] if i < len(temps) else None,
            "apparent_temperature_c": apparent[i] if i < len(apparent) else None,
            "model": config.FORECAST_MODEL,
            "latitude": config.LATITUDE,
            "longitude": config.LONGITUDE,
        })
    return rows


def main():
    db.init_db()
    fetched_at = datetime.now(timezone.utc)

    try:
        payload = fetch_forecast()
    except requests.RequestException as e:
        print(f"[fetch_forecast] ERROR calling Open-Meteo: {e}", file=sys.stderr)
        sys.exit(1)

    rows = to_rows(payload, fetched_at)
    inserted = db.insert_forecasts(rows)
    print(f"[fetch_forecast] {fetched_at.isoformat()}: "
          f"fetched {len(rows)} hourly points, inserted {inserted} new rows.")


if __name__ == "__main__":
    main()
