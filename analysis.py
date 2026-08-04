"""
Query helpers that join forecasts to actuals and compute bias.
Kept separate from dashboard.py so you can also run these from a notebook
or a plain python shell for ad-hoc digging.

Bias convention used throughout: error = forecast - actual
    positive error -> forecast ran too WARM
    negative error -> forecast ran too COLD
"""

import pandas as pd

import config


def load_joined(conn):
    """Return a DataFrame with one row per (forecast, actual) match on the
    same target hour. Multiple forecast vintages (different fetched_at /
    lead_hours) for the same target hour will each get their own row."""
    query = """
        SELECT
            f.fetched_at,
            f.target_time,
            f.lead_hours,
            f.temperature_c   AS forecast_temp_c,
            f.apparent_temperature_c,
            f.model,
            a.temperature_c   AS actual_temp_c,
            a.station_id
        FROM forecasts f
        JOIN actuals a ON a.observed_time = f.target_time
        ORDER BY f.target_time, f.lead_hours
    """
    df = pd.read_sql_query(query, conn, parse_dates=["fetched_at", "target_time"])
    df["error_c"] = df["forecast_temp_c"] - df["actual_temp_c"]
    return df


def bucket_lead_hours(df, bin_hours=24):
    """Group lead_hours into day-ish buckets, e.g. 0-24h, 24-48h, 48-72h..."""
    df = df.copy()
    df["lead_bucket"] = (df["lead_hours"] // bin_hours * bin_hours).astype(int)
    return df


def bias_by_lead_bucket(df, bin_hours=24):
    df = bucket_lead_hours(df, bin_hours)
    summary = (
        df.groupby("lead_bucket")["error_c"]
        .agg(mean_error="mean", mean_abs_error=lambda s: s.abs().mean(),
             n="count", std="std")
        .reset_index()
        .sort_values("lead_bucket")
    )
    summary["lead_bucket_label"] = summary["lead_bucket"].apply(
        lambda h: f"{h}-{h + bin_hours}h"
    )
    return summary


def decade_temp_buckets(df, bucket_size=10, temp_col="actual_temp_c"):
    """Bucket by the ACTUAL temperature into fixed-width bins (default 10°C)
    anchored to multiples of bucket_size, e.g. [-10,0), [0,10), [10,20)...
    This is an objective split (no 'hot'/'cold' judgment calls) and adapts
    automatically to whatever temperature range is actually in the data.
    Returns (df_with_bucket_col, ordered_category_list).
    """
    df = df.copy()
    lo = (df[temp_col].min() // bucket_size) * bucket_size
    hi = (df[temp_col].max() // bucket_size + 1) * bucket_size
    edges = list(range(int(lo), int(hi) + bucket_size, bucket_size))
    labels = [f"{edges[i]} to {edges[i+1]}°C" for i in range(len(edges) - 1)]

    df["actual_temp_bucket"] = pd.cut(
        df[temp_col], bins=edges, labels=labels, right=False
    )
    return df, labels


def bias_by_temp_bucket(df, bucket_size=10):
    """Summary stats of error grouped by fixed-width actual-temperature bucket."""
    df, order = decade_temp_buckets(df, bucket_size)
    summary = (
        df.groupby("actual_temp_bucket", observed=True)["error_c"]
        .agg(mean_error="mean", mean_abs_error=lambda s: s.abs().mean(), n="count")
        .reindex(order)
        .dropna(how="all")
        .reset_index()
    )
    return summary


def bias_by_temp_and_lead(df, bin_hours=24, bucket_size=10):
    """Cross-tab: mean error by actual-temperature decade bucket AND
    lead-time bucket."""
    df = bucket_lead_hours(df, bin_hours)
    df, order = decade_temp_buckets(df, bucket_size)

    pivot = df.pivot_table(
        index="actual_temp_bucket",
        columns="lead_bucket",
        values="error_c",
        aggfunc="mean",
        observed=True,
    )
    return pivot.reindex(order).dropna(how="all")


def target_time_completeness(df):
    """For each target_time, how many forecast vintages (fetch runs) we
    have on record. Returns a per-target_time DataFrame plus the max
    vintage count seen, so callers can define 'complete' records as those
    at that max (i.e. we caught every scheduled forecast run before the
    hour passed and also have an actual to compare against, since df is
    already the forecast/actual join)."""
    counts = (
        df.groupby("target_time")
        .size()
        .rename("vintage_count")
        .reset_index()
    )
    max_count = int(counts["vintage_count"].max()) if not counts.empty else 0
    counts["is_complete"] = counts["vintage_count"] == max_count
    return counts, max_count


def load_coverage(conn):
    """Build a per-target-hour coverage table across ALL forecast data,
    not just rows that already have a matching actual - this is what
    lets the coverage view show 'forecast only' (e.g. future hours, or
    an actuals fetch that hasn't run yet) distinctly from 'both'."""
    forecasts = pd.read_sql_query(
        "SELECT target_time, COUNT(*) AS vintage_count, MIN(lead_hours) AS min_lead_hours "
        "FROM forecasts GROUP BY target_time",
        conn,
        parse_dates=["target_time"],
    )
    actuals = pd.read_sql_query(
        "SELECT observed_time, temperature_c AS actual_temp_c FROM actuals",
        conn,
        parse_dates=["observed_time"],
    )

    merged = forecasts.merge(
        actuals, left_on="target_time", right_on="observed_time", how="left"
    )
    merged["has_actual"] = merged["actual_temp_c"].notna()
    # status: 2 = forecast + actual, 1 = forecast only (0/"no data at all"
    # isn't representable here since this table is seeded from forecasts -
    # there's simply no row for hours we have literally nothing for)
    merged["status"] = merged["has_actual"].map({True: 2, False: 1})
    merged["date"] = merged["target_time"].dt.date
    merged["hour"] = merged["target_time"].dt.hour
    return merged
