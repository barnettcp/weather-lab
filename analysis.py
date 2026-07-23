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


def bias_by_temp_bucket(df, edges=None):
    """Bucket by the ACTUAL temperature (so 'hot days' / 'cold days' reflect
    what really happened, not what was forecast) and look at mean error.
    Default edges roughly split cold / mild / warm / hot in Celsius."""
    if edges is None:
        edges = [-50, 0, 10, 20, 27, 50]
    labels = [f"{edges[i]} to {edges[i+1]}°C" for i in range(len(edges) - 1)]

    df = df.copy()
    df["actual_temp_bucket"] = pd.cut(df["actual_temp_c"], bins=edges, labels=labels)

    summary = (
        df.groupby("actual_temp_bucket", observed=True)["error_c"]
        .agg(mean_error="mean", mean_abs_error=lambda s: s.abs().mean(), n="count")
        .reset_index()
    )
    return summary


def bias_by_temp_and_lead(df, bin_hours=24, edges=None):
    """Cross-tab: mean error by actual-temperature bucket AND lead-time
    bucket. This is the table that will show whether hot-day underforecast
    bias is worse (or better) at longer lead times."""
    if edges is None:
        edges = [-50, 0, 10, 20, 27, 50]
    labels = [f"{edges[i]} to {edges[i+1]}°C" for i in range(len(edges) - 1)]

    df = bucket_lead_hours(df, bin_hours).copy()
    df["actual_temp_bucket"] = pd.cut(df["actual_temp_c"], bins=edges, labels=labels)

    pivot = df.pivot_table(
        index="actual_temp_bucket",
        columns="lead_bucket",
        values="error_c",
        aggfunc="mean",
        observed=True,
    )
    return pivot
