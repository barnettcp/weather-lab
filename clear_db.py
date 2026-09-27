#!/usr/bin/env python3
"""
Wipe all data rows from the weather database, preserving the schema.
Intended for use after a smoke test run before starting production collection.
"""
import sys

import db

_TABLES = ["forecasts", "actuals", "fetch_log", "meta"]


def main():
    with db.get_conn() as conn:
        counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in _TABLES}

    print("Current row counts:")
    for table, count in counts.items():
        print(f"  {table}: {count}")

    if sum(counts.values()) == 0:
        print("Database is already empty.")
        return

    print("\nThis will delete all rows. Type 'yes' to continue: ", end="", flush=True)
    if input().strip().lower() != "yes":
        print("Aborted.")
        sys.exit(0)

    with db.get_conn() as conn:
        for table in _TABLES:
            conn.execute(f"DELETE FROM {table}")

    print("All data cleared. Schema preserved.")


if __name__ == "__main__":
    main()
