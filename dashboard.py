"""
Streamlit dashboard for the weather-bias-tracker data.

Run with:
    streamlit run dashboard.py

Kept intentionally simple/functional per project priorities - the goal
right now is a correct, readable view of the data, not a polished UI.
"""

import pandas as pd
import streamlit as st

import analysis
import config
import db

st.set_page_config(page_title="Weather Forecast Bias Tracker", layout="wide")
st.title("Weather Forecast Bias Tracker")
st.caption(
    f"Location: {config.LATITUDE}, {config.LONGITUDE} | "
    f"Forecast model: {config.FORECAST_MODEL} | DB: {config.DB_PATH}"
)


@st.cache_data(ttl=300)
def load_data():
    with db.get_conn() as conn:
        df = analysis.load_joined(conn)
    return df


df = load_data()

if df.empty:
    st.warning(
        "No matched forecast/actual data yet. Once `fetch_forecast.py` and "
        "`fetch_actuals.py` have both run for a few days, matching rows "
        "will start showing up here (a forecast only becomes checkable "
        "once its target hour has actually happened)."
    )
    st.stop()

# --- Top-line stats ----------------------------------------------------
col1, col2, col3, col4 = st.columns(4)
col1.metric("Matched forecast/actual rows", f"{len(df):,}")
col2.metric("Mean error (°C)", f"{df['error_c'].mean():.2f}")
col3.metric("Mean absolute error (°C)", f"{df['error_c'].abs().mean():.2f}")
col4.metric(
    "Date range",
    f"{df['target_time'].min().date()} → {df['target_time'].max().date()}",
)

st.divider()

# --- Bias by lead time ---------------------------------------------------
st.subheader("Bias by lead time")
st.caption(
    "error = forecast − actual. Positive = forecast ran too warm, "
    "negative = forecast ran too cold. Lead time is how far in advance "
    "the forecast was made."
)
bin_hours = st.select_slider(
    "Lead time bucket size (hours)", options=[6, 12, 24, 48], value=24
)
lead_summary = analysis.bias_by_lead_bucket(df, bin_hours=bin_hours)

lc1, lc2 = st.columns([2, 1])
with lc1:
    st.bar_chart(
        lead_summary.set_index("lead_bucket_label")[["mean_error"]],
    )
with lc2:
    st.dataframe(
        lead_summary[["lead_bucket_label", "mean_error", "mean_abs_error", "n"]]
        .rename(columns={"lead_bucket_label": "lead bucket"})
        .round(2),
        hide_index=True,
        use_container_width=True,
    )

st.divider()

# --- Bias by actual temperature (hot vs cold asymmetry) ------------------
st.subheader("Bias by actual temperature (hot vs. cold days)")
st.caption(
    "Buckets are based on the ACTUAL recorded temperature, so this shows "
    "whether forecasts are systematically off in a particular direction "
    "when it turns out to be hot vs. cold."
)
temp_summary = analysis.bias_by_temp_bucket(df)

tc1, tc2 = st.columns([2, 1])
with tc1:
    st.bar_chart(temp_summary.set_index("actual_temp_bucket")[["mean_error"]])
with tc2:
    st.dataframe(
        temp_summary.rename(columns={"actual_temp_bucket": "actual temp range"})
        .round(2),
        hide_index=True,
        use_container_width=True,
    )

st.divider()

# --- Cross-tab: temperature bucket x lead time ----------------------------
st.subheader("Mean error: temperature bucket × lead time")
st.caption(
    "Each cell is the mean forecast error (°C) for that combination. "
    "Watch for hot-weather rows getting more negative (colder-than-actual "
    "forecasts) as lead time increases, if that's the pattern you suspect."
)
cross = analysis.bias_by_temp_and_lead(df, bin_hours=bin_hours)
st.dataframe(cross.round(2), use_container_width=True)

st.divider()

# --- Raw data / recent matches --------------------------------------------
st.subheader("Recent matched rows")
recent = df.sort_values("target_time", ascending=False).head(200)
st.dataframe(
    recent[
        ["target_time", "lead_hours", "forecast_temp_c", "actual_temp_c", "error_c"]
    ].round(2),
    hide_index=True,
    use_container_width=True,
)
