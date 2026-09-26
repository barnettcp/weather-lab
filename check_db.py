#!/usr/bin/env python3
"""
Quick database status check: row counts per table, broken down by station and model.
Useful for verifying a smoke test landed data before clearing for production.
"""
import db


def main():
    with db.get_conn() as conn:
        for table in ("forecasts", "actuals", "fetch_log"):
            n = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            print(f"{table}: {n} rows")

        print()

        rows = conn.execute(
            "SELECT station_id, model, COUNT(*) FROM forecasts"
            " GROUP BY station_id, model ORDER BY station_id, model"
        ).fetchall()
        if rows:
            print("forecasts by station/model:")
            for station_id, model, count in rows:
                print(f"  {station_id}/{model}: {count}")
            print()

        rows = conn.execute(
            "SELECT station_id, COUNT(*) FROM actuals"
            " GROUP BY station_id ORDER BY station_id"
        ).fetchall()
        if rows:
            print("actuals by station:")
            for station_id, count in rows:
                print(f"  {station_id}: {count}")


if __name__ == "__main__":
    main()
