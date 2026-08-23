#!/usr/bin/env python3
"""
One-time backfill of fetch_log from existing data sources.

  Step 1 — Forecast successes:  from distinct fetched_at in forecasts table
  Step 2 — Forecast inferred errors: scheduled runs (03/09/15/21 UTC) with no
            matching fetched_at (±90 min) are recorded as inferred errors
  Step 3 — Actuals successes:   parsed from logs/actuals.log via regex
  Step 4 — Actuals inferred errors: daily 03:00 UTC runs with no log entry

All four steps use NOT EXISTS / set guards — safe to re-run.

Run once from the project root:
    python3 backfill_fetch_log.py
"""

import datetime
import os
import re
from zoneinfo import ZoneInfo  # stdlib since Python 3.9

import config
import db

_LOCAL_TZ = ZoneInfo(config.TIMEZONE)

# ── schedules (from systemd timers) ──────────────────────────────────────────
FORECAST_HOURS_LOCAL = [3, 9, 15, 21]   # local time per weather-forecast.timer
ACTUALS_HOURS_LOCAL  = [3]               # local time per weather-actuals.timer

TOLERANCE  = datetime.timedelta(minutes=90)
INFERRED_MSG = "[inferred] No data written for this scheduled run — likely a script error"

# ── actuals log ───────────────────────────────────────────────────────────────
ACTUALS_LOG = os.path.join(config.BASE_DIR, "logs", "actuals.log")

# Matches: [fetch_actuals] 2026-08-21T10:00:06.843492+00:00: ... 46 inserted/updated.
_ACTUALS_SUCCESS_RE = re.compile(
    r"\[fetch_actuals\] "
    r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}[\d.]*[+-]\d{2}:\d{2})"
    r":.+?(\d+) inserted/updated\."
)


# ── helpers ───────────────────────────────────────────────────────────────────

def as_utc(ts_str):
    dt = datetime.datetime.fromisoformat(ts_str)
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def expected_run_times(scheduled_hours_local, start_dt, end_dt):
    """Yield expected UTC datetimes; hours are interpreted in the local timezone."""
    current = start_dt.astimezone(_LOCAL_TZ).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    while True:
        for hour in scheduled_hours_local:
            expected_local = current.replace(hour=hour)
            expected_utc = expected_local.astimezone(datetime.timezone.utc)
            if start_dt <= expected_utc <= end_dt:
                yield expected_utc
        current = (current + datetime.timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        if current.astimezone(datetime.timezone.utc) > end_dt:
            break


def infer_gaps(scheduled_hours, known_times, first_at, now_utc, already_logged):
    """Return list of (iso_str, error_msg) for scheduled slots with no data."""
    rows = []
    for expected in expected_run_times(scheduled_hours, first_at, now_utc):
        close_enough = any(
            abs((expected - f).total_seconds()) <= TOLERANCE.total_seconds()
            for f in known_times
        )
        if not close_enough and expected not in already_logged:
            rows.append((expected.isoformat(), INFERRED_MSG))
    return rows


# ── main ──────────────────────────────────────────────────────────────────────

def main():
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    with db.get_conn() as conn:

        # ------------------------------------------------------------------
        # Step 1: forecast successes (from forecasts table)
        # ------------------------------------------------------------------
        fc_success = conn.execute(
            """
            SELECT f.fetched_at, COUNT(*) AS rows_affected
            FROM forecasts f
            WHERE NOT EXISTS (
                SELECT 1 FROM fetch_log fl
                WHERE fl.fetch_type = 'forecast' AND fl.started_at = f.fetched_at
            )
            GROUP BY f.fetched_at
            ORDER BY f.fetched_at
            """
        ).fetchall()

        if fc_success:
            conn.executemany(
                "INSERT INTO fetch_log (fetch_type, started_at, status, rows_affected) "
                "VALUES ('forecast', ?, 'success', ?)",
                fc_success,
            )
            print(f"Step 1: backfilled {len(fc_success)} forecast successes.")
        else:
            print("Step 1: nothing new to backfill (forecast successes).")

        # ------------------------------------------------------------------
        # Step 2: forecast inferred errors (gaps in schedule)
        # ------------------------------------------------------------------
        bounds = conn.execute("SELECT MIN(fetched_at), MAX(fetched_at) FROM forecasts").fetchone()

        if bounds[0]:
            fc_times = [as_utc(r[0]) for r in conn.execute("SELECT fetched_at FROM forecasts").fetchall()]
            fc_logged_errors = {
                as_utc(r[0]) for r in conn.execute(
                    "SELECT started_at FROM fetch_log WHERE fetch_type='forecast' AND status='error'"
                ).fetchall()
            }
            fc_errors = infer_gaps(FORECAST_HOURS_LOCAL, fc_times, as_utc(bounds[0]), now_utc, fc_logged_errors)
            if fc_errors:
                conn.executemany(
                    "INSERT INTO fetch_log (fetch_type, started_at, status, rows_affected, error_msg) "
                    "VALUES ('forecast', ?, 'error', 0, ?)",
                    fc_errors,
                )
                print(f"Step 2: inserted {len(fc_errors)} inferred forecast error entries.")
            else:
                print("Step 2: no forecast gaps detected.")
        else:
            print("Step 2: no forecast data found, skipping.")

        # ------------------------------------------------------------------
        # Step 3: actuals successes (parsed from logs/actuals.log)
        # ------------------------------------------------------------------
        if not os.path.exists(ACTUALS_LOG):
            print(f"Step 3: {ACTUALS_LOG} not found, skipping.")
            act_times = []
        else:
            already_logged_act = {
                r[0] for r in conn.execute(
                    "SELECT started_at FROM fetch_log WHERE fetch_type='actuals' AND status='success'"
                ).fetchall()
            }

            act_success = []
            act_times   = []
            with open(ACTUALS_LOG, encoding="utf-8", errors="replace") as fh:
                for line in fh:
                    m = _ACTUALS_SUCCESS_RE.search(line)
                    if not m:
                        continue
                    ts_str, rows_str = m.group(1), m.group(2)
                    act_times.append(as_utc(ts_str))
                    if ts_str not in already_logged_act:
                        act_success.append((ts_str, int(rows_str)))

            if act_success:
                conn.executemany(
                    "INSERT INTO fetch_log (fetch_type, started_at, status, rows_affected) "
                    "VALUES ('actuals', ?, 'success', ?)",
                    act_success,
                )
                print(f"Step 3: backfilled {len(act_success)} actuals successes from log.")
            else:
                print("Step 3: nothing new to backfill (actuals successes).")

        # ------------------------------------------------------------------
        # Step 4: actuals inferred errors (gaps in daily schedule)
        # ------------------------------------------------------------------
        if act_times:
            act_logged_errors = {
                as_utc(r[0]) for r in conn.execute(
                    "SELECT started_at FROM fetch_log WHERE fetch_type='actuals' AND status='error'"
                ).fetchall()
            }
            act_errors = infer_gaps(ACTUALS_HOURS_LOCAL, act_times, min(act_times), now_utc, act_logged_errors)
            if act_errors:
                conn.executemany(
                    "INSERT INTO fetch_log (fetch_type, started_at, status, rows_affected, error_msg) "
                    "VALUES ('actuals', ?, 'error', 0, ?)",
                    act_errors,
                )
                print(f"Step 4: inserted {len(act_errors)} inferred actuals error entries.")
            else:
                print("Step 4: no actuals gaps detected.")
        else:
            print("Step 4: no actuals times available, skipping gap analysis.")

        print("\nDone.")


if __name__ == "__main__":
    main()


import datetime

import db

SCHEDULED_HOURS_UTC = [3, 9, 15, 21]  # from weather-forecast.timer
TOLERANCE = datetime.timedelta(minutes=90)
INFERRED_MSG = "[inferred] No data written for this scheduled run — likely a script error"


def expected_run_times(start_dt, end_dt):
    """Yield all scheduled UTC datetimes in [start_dt, end_dt]."""
    day = start_dt.replace(hour=0, minute=0, second=0, microsecond=0)
    while day <= end_dt:
        for hour in SCHEDULED_HOURS_UTC:
            t = day.replace(hour=hour)
            if start_dt <= t <= end_dt:
                yield t
        day += datetime.timedelta(days=1)


def as_utc(ts_str):
    dt = datetime.datetime.fromisoformat(ts_str)
    return dt if dt.tzinfo else dt.replace(tzinfo=datetime.timezone.utc)


def main():
    now_utc = datetime.datetime.now(datetime.timezone.utc)

    with db.get_conn() as conn:
        # ------------------------------------------------------------------
        # Step 1: backfill successes
        # ------------------------------------------------------------------
        success_rows = conn.execute(
            """
            SELECT f.fetched_at, COUNT(*) AS rows_affected
            FROM forecasts f
            WHERE NOT EXISTS (
                SELECT 1 FROM fetch_log fl
                WHERE fl.fetch_type = 'forecast'
                  AND fl.started_at = f.fetched_at
            )
            GROUP BY f.fetched_at
            ORDER BY f.fetched_at
            """
        ).fetchall()

        if success_rows:
            conn.executemany(
                "INSERT INTO fetch_log (fetch_type, started_at, status, rows_affected) "
                "VALUES ('forecast', ?, 'success', ?)",
                success_rows,
            )
            print(f"Backfilled {len(success_rows)} successful forecast fetch events.")
        else:
            print("Successes: nothing new to backfill.")

        # ------------------------------------------------------------------
        # Step 2: infer error runs from gaps in the schedule
        # ------------------------------------------------------------------
        bounds = conn.execute(
            "SELECT MIN(fetched_at), MAX(fetched_at) FROM forecasts"
        ).fetchone()

        if not bounds[0]:
            print("No forecast data found — skipping gap analysis.")
            return

        first_at = as_utc(bounds[0])

        fetched_times = [as_utc(r[0]) for r in conn.execute("SELECT fetched_at FROM forecasts").fetchall()]

        already_logged = {
            as_utc(r[0])
            for r in conn.execute(
                "SELECT started_at FROM fetch_log WHERE fetch_type = 'forecast' AND status = 'error'"
            ).fetchall()
        }

        error_rows = []
        for expected in expected_run_times(first_at, now_utc):
            close_enough = any(
                abs((expected - f).total_seconds()) <= TOLERANCE.total_seconds()
                for f in fetched_times
            )
            if close_enough or expected in already_logged:
                continue
            error_rows.append((expected.isoformat(), INFERRED_MSG))

        if error_rows:
            conn.executemany(
                "INSERT INTO fetch_log (fetch_type, started_at, status, rows_affected, error_msg) "
                "VALUES ('forecast', ?, 'error', 0, ?)",
                error_rows,
            )
            print(f"Inserted {len(error_rows)} inferred error entries for missed scheduled runs.")
        else:
            print("Errors: no gaps detected.")

        print("Done. Actuals fetch history starts from the next cron run.")


if __name__ == "__main__":
    main()

