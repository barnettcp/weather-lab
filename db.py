"""
SQLite schema and small helper functions shared by the fetch scripts and
the dashboard. Everything is stored in UTC as ISO-8601 strings
(e.g. "2026-07-19T14:00:00+00:00") so comparisons/joins are unambiguous.
"""

import sqlite3
from contextlib import contextmanager

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS forecasts (
    id                      INTEGER PRIMARY KEY AUTOINCREMENT,
    fetched_at              TEXT NOT NULL,   -- when we called the API (UTC)
    target_time             TEXT NOT NULL,   -- hour being predicted (UTC)
    lead_hours              REAL NOT NULL,   -- target_time - fetched_at, in hours
    temperature_c           REAL,
    apparent_temperature_c  REAL,
    model                   TEXT NOT NULL,
    latitude                REAL NOT NULL,
    longitude               REAL NOT NULL,
    UNIQUE(fetched_at, target_time, model, latitude, longitude)
);

CREATE INDEX IF NOT EXISTS idx_forecasts_target ON forecasts(target_time);
CREATE INDEX IF NOT EXISTS idx_forecasts_lead ON forecasts(lead_hours);

CREATE TABLE IF NOT EXISTS actuals (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    observed_time   TEXT NOT NULL,   -- hour bucket, UTC (floored to the hour)
    temperature_c   REAL,
    station_id      TEXT NOT NULL,
    UNIQUE(observed_time, station_id)
);

CREATE INDEX IF NOT EXISTS idx_actuals_time ON actuals(observed_time);

CREATE TABLE IF NOT EXISTS meta (
    key     TEXT PRIMARY KEY,
    value   TEXT
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(config.DB_PATH)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def get_meta(key, default=None):
    with get_conn() as conn:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else default


def set_meta(key, value):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


def insert_forecasts(rows):
    """rows: list of dicts matching the forecasts columns (minus id)."""
    if not rows:
        return 0
    with get_conn() as conn:
        cur = conn.executemany(
            """
            INSERT OR IGNORE INTO forecasts
                (fetched_at, target_time, lead_hours, temperature_c,
                 apparent_temperature_c, model, latitude, longitude)
            VALUES
                (:fetched_at, :target_time, :lead_hours, :temperature_c,
                 :apparent_temperature_c, :model, :latitude, :longitude)
            """,
            rows,
        )
        return cur.rowcount


def insert_actuals(rows):
    """rows: list of dicts matching the actuals columns (minus id)."""
    if not rows:
        return 0
    with get_conn() as conn:
        cur = conn.executemany(
            """
            INSERT INTO actuals (observed_time, temperature_c, station_id)
            VALUES (:observed_time, :temperature_c, :station_id)
            ON CONFLICT(observed_time, station_id)
            DO UPDATE SET temperature_c = excluded.temperature_c
            """,
            rows,
        )
        return cur.rowcount


if __name__ == "__main__":
    init_db()
    print(f"Initialized database at {config.DB_PATH}")
