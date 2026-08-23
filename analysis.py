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


def daily_coverage_summary(conn):
    """Aggregate coverage data by day to show daily completion statistics.
    
    Returns a DataFrame with one row per date containing:
    - date: the calendar date
    - hours_no_data: count of hours (0-24) with no forecast at all
    - hours_forecast_only: count of hours with forecast but no actual
    - hours_both: count of hours with both forecast and actual
    - total_hours_with_data: hours_forecast_only + hours_both
    - completion_pct: (hours_both / 24) * 100
    - calendar_value: special encoding for visualization:
        -1 = no data, 0 = forecast only, 1-24 = hours with actuals
    - day_of_week: 0=Monday, 6=Sunday (for calendar layout)
    """
    coverage = load_coverage(conn)
    
    # Group by date and count status types
    daily = (
        coverage.groupby("date")["status"]
        .agg(
            hours_forecast_only=lambda x: (x == 1).sum(),
            hours_both=lambda x: (x == 2).sum(),
        )
        .reset_index()
    )
    
    # Calculate derived metrics
    daily["total_hours_with_data"] = (
        daily["hours_forecast_only"] + daily["hours_both"]
    )
    daily["hours_no_data"] = 24 - daily["total_hours_with_data"]
    daily["completion_pct"] = (daily["hours_both"] / 24) * 100
    
    # Create calendar_value for visualization:
    # -1 = no data at all, 0 = forecast only, 1-24 = hours with actuals
    daily["calendar_value"] = daily["hours_both"]
    daily.loc[daily["hours_both"] == 0, "calendar_value"] = 0  # Forecast only
    
    # Add calendar positioning info
    daily["date"] = pd.to_datetime(daily["date"])
    daily["day_of_week"] = daily["date"].dt.dayofweek  # 0=Monday, 6=Sunday
    daily["week_of_year"] = daily["date"].dt.isocalendar().week
    daily["month"] = daily["date"].dt.month
    daily["year"] = daily["date"].dt.year
    
    return daily


def load_actuals_vs_forecast_by_lead(df, lead_hours_target=24, tolerance=12):
    """From the joined df, return one row per target_time using the forecast
    vintage whose lead_hours is closest to lead_hours_target (within ±tolerance).
    Useful for the 'actual vs one lead time' line chart."""
    d = df.copy()
    d["_lead_dist"] = (d["lead_hours"] - lead_hours_target).abs()
    d = d[d["_lead_dist"] <= tolerance]
    if d.empty:
        return d.drop(columns=["_lead_dist"])
    idx = d.groupby("target_time")["_lead_dist"].idxmin()
    return (
        d.loc[idx]
        .drop(columns=["_lead_dist"])
        .sort_values("target_time")
        .reset_index(drop=True)
    )


def load_multi_lead_comparison(df, lead_buckets=None, tolerance=12):
    """Return a long-form DataFrame with an 'Actual' series plus one series per
    entry in lead_buckets, suitable for a multi-line temperature chart.

    Columns: target_time, temperature_c, series
    """
    if lead_buckets is None:
        lead_buckets = [24, 48, 72, 96]

    frames = []

    actuals = (
        df[["target_time", "actual_temp_c"]]
        .drop_duplicates("target_time")
        .rename(columns={"actual_temp_c": "temperature_c"})
        .assign(series="Actual")
    )
    frames.append(actuals[["target_time", "temperature_c", "series"]])

    for lead in lead_buckets:
        sub = load_actuals_vs_forecast_by_lead(df, lead_hours_target=lead, tolerance=tolerance)
        if sub.empty:
            continue
        frames.append(
            sub[["target_time", "forecast_temp_c"]]
            .rename(columns={"forecast_temp_c": "temperature_c"})
            .assign(series=f"{lead}h forecast")
            [["target_time", "temperature_c", "series"]]
        )

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def process_health_daily(conn):
    """Return a DataFrame with one row per day showing how many forecast
    fetch runs and actual observations were recorded."""
    forecasts_daily = pd.read_sql_query(
        """
        SELECT date(fetched_at) AS date,
               COUNT(DISTINCT fetched_at) AS fetch_runs,
               COUNT(*) AS forecast_rows
        FROM forecasts
        GROUP BY date(fetched_at)
        ORDER BY date
        """,
        conn,
        parse_dates=["date"],
    )
    actuals_daily = pd.read_sql_query(
        """
        SELECT date(observed_time) AS date,
               COUNT(*) AS actual_rows
        FROM actuals
        GROUP BY date(observed_time)
        ORDER BY date
        """,
        conn,
        parse_dates=["date"],
    )
    merged = (
        forecasts_daily
        .merge(actuals_daily, on="date", how="outer")
        .sort_values("date")
    )
    for col in ("fetch_runs", "forecast_rows", "actual_rows"):
        merged[col] = merged[col].fillna(0).astype(int)
    return merged


def get_data_extents(conn):
    """Return (first_time_str, last_time_str, matched_hours) for target hours
    where both a forecast and an actual exist."""
    return conn.execute(
        """
        SELECT MIN(f.target_time) AS first_time,
               MAX(f.target_time) AS last_time,
               COUNT(DISTINCT f.target_time) AS matched_hours
        FROM forecasts f
        JOIN actuals a ON a.observed_time = f.target_time
        """
    ).fetchone()


def get_last_fetches(conn):
    """Return (last_forecast_row, last_actual_row) where:
      last_forecast_row = (fetched_at_str, row_count_in_that_fetch)
      last_actual_row   = (last_observed_str, obs_count_last_48h)
    """
    last_forecast = conn.execute(
        """
        SELECT fetched_at, COUNT(*) AS rows
        FROM forecasts
        GROUP BY fetched_at
        ORDER BY fetched_at DESC
        LIMIT 1
        """
    ).fetchone()
    last_actual = conn.execute(
        """
        SELECT MAX(observed_time) AS last_observed,
               SUM(CASE WHEN datetime(observed_time) >= datetime('now', '-2 days')
                        THEN 1 ELSE 0 END) AS recent_rows
        FROM actuals
        """
    ).fetchone()
    return last_forecast, last_actual


def load_raw_forecasts(conn):
    """Load the 100 most-recent forecast rows for the data explorer."""
    return pd.read_sql_query(
        """
        SELECT fetched_at, target_time,
               ROUND(lead_hours, 1) AS lead_hours,
               temperature_c, apparent_temperature_c, model
        FROM forecasts
        ORDER BY fetched_at DESC, target_time
        LIMIT 100
        """,
        conn,
        parse_dates=["fetched_at", "target_time"],
    )


def load_raw_actuals(conn):
    """Load the 100 most-recent actual observation rows for the data explorer."""
    return pd.read_sql_query(
        """
        SELECT observed_time, temperature_c, station_id
        FROM actuals
        ORDER BY observed_time DESC
        LIMIT 100
        """,
        conn,
        parse_dates=["observed_time"],
    )


def load_fetch_log(conn, limit=50):
    """Return the most-recent fetch log entries, newest first.
    Returns an empty DataFrame if the fetch_log table doesn't exist yet."""
    try:
        df = pd.read_sql_query(
            f"SELECT fetch_type, started_at, status, rows_affected, error_msg "
            f"FROM fetch_log ORDER BY started_at DESC LIMIT {limit}",
            conn,
        )
        if not df.empty:
            df["started_at"] = pd.to_datetime(df["started_at"], utc=True)
        return df
    except Exception:
        return pd.DataFrame(
            columns=["fetch_type", "started_at", "status", "rows_affected", "error_msg"]
        )
