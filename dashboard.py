"""
Weather Lab - Forecasts vs Actuals

Run with:
    streamlit run dashboard.py

Structure:
    Top of page   - hourly actual vs forecast line chart with lead-time selector
    Data Overview - first/last coverage tiles, last refresh, multi-lead comparison
    Process Health- daily fetch/actual counts, last fetch metrics
    Convergence   - error distributions + convergence plots (stub for future work)
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

import analysis
import config
import db

LOCAL_TZ = config.TIMEZONE

st.set_page_config(page_title="Weather Lab - Forecasts vs Actuals", layout="wide")
st.title("Weather Lab — Forecasts vs Actuals")

with st.expander("About this project", expanded=True):
    st.markdown(
        "Welcome to Weather Lab. This is a playground as I develop a process to capture "
        "forecasts and actuals using my Raspberry Pi 4. The hope is to build interesting "
        "and intuitive visualizations with weather forecasts, which is something we all "
        "have experience with."
    )

with st.expander("AI Disclosure"):
    st.markdown(
        "This project was built with AI assistance, mostly Claude models accessed via "
        "GitHub Copilot. I take responsibility for the outcome, but want to be transparent "
        "about its use. The initial repo contents were generated at my direction. From there, "
        "I have carefully and thoughtfully worked on the project both using Copilot and by "
        "hand in uncommitted notebooks."
    )



# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def to_local(series):
    """Convert a UTC datetime Series to the configured local timezone."""
    if series.dt.tz is None:
        series = series.dt.tz_localize("UTC")
    return series.dt.tz_convert(LOCAL_TZ)


def parse_utc_str(s):
    """Parse a UTC timestamp string from SQLite into a local-tz Timestamp."""
    if s is None:
        return None
    ts = pd.Timestamp(s)
    if ts.tz is None:
        ts = ts.tz_localize("UTC")
    return ts.tz_convert(LOCAL_TZ)


DATE_RANGE_OPTIONS = ["All Time", "Year to Date", "Last 90 Days", "Last 30 Days", "Last 7 Days"]


def filter_by_date_range(df, range_label):
    """Return df rows whose target_time falls within the chosen window."""
    if range_label == "All Time" or df.empty:
        return df
    now = pd.Timestamp.now("UTC").tz_convert(LOCAL_TZ)
    cutoffs = {
        "Year to Date": pd.Timestamp(f"{now.year}-01-01", tz=LOCAL_TZ),
        "Last 90 Days": now - pd.Timedelta(days=90),
        "Last 30 Days": now - pd.Timedelta(days=30),
        "Last 7 Days":  now - pd.Timedelta(days=7),
    }
    cutoff = cutoffs.get(range_label)
    return df if cutoff is None else df[df["target_time"] >= cutoff]


# ---------------------------------------------------------------------------
# Data loading (cached)
# ---------------------------------------------------------------------------

@st.cache_data(ttl=300)
def load_data():
    with db.get_conn() as conn:
        df            = analysis.load_joined(conn)
        health        = analysis.process_health_daily(conn)
        extents       = analysis.get_data_extents(conn)
        last_fc, last_act = analysis.get_last_fetches(conn)
        raw_fc_df     = analysis.load_raw_forecasts(conn)
        raw_act_df    = analysis.load_raw_actuals(conn)
        fetch_log_df  = analysis.load_fetch_log(conn)
    if not df.empty:
        df["target_time"] = to_local(df["target_time"])
        df["fetched_at"]  = to_local(df["fetched_at"])
    if not raw_fc_df.empty:
        raw_fc_df["fetched_at"]  = to_local(raw_fc_df["fetched_at"])
        raw_fc_df["target_time"] = to_local(raw_fc_df["target_time"])
    if not raw_act_df.empty:
        raw_act_df["observed_time"] = to_local(raw_act_df["observed_time"])
    if not fetch_log_df.empty:
        fetch_log_df["started_at"] = to_local(fetch_log_df["started_at"])
    return df, health, extents, last_fc, last_act, raw_fc_df, raw_act_df, fetch_log_df


df, health_df, extents, last_fc, last_act, raw_fc_df, raw_act_df, fetch_log_df = load_data()

if health_df.empty:
    st.warning(
        "No forecast data yet. Once `fetch_forecast.py` has run at least "
        "once, data will appear here."
    )
    st.stop()


# ---------------------------------------------------------------------------
# Main chart: hourly actual vs forecast at a chosen lead time
# ---------------------------------------------------------------------------

st.divider()

LEAD_OPTIONS = [12, 24, 36, 48, 72, 96, 120]

_, col_date, col_lead = st.columns([3, 1.5, 1])
with col_date:
    date_range = st.selectbox("Date range", DATE_RANGE_OPTIONS, index=0)
with col_lead:
    selected_lead = st.selectbox("Lead time", LEAD_OPTIONS, index=1, format_func=lambda h: f"{h}h")

df_filtered = filter_by_date_range(df, date_range)

if df.empty:
    st.info(
        "No matched forecast/actual pairs yet — actuals will appear once "
        "target hours have passed and `fetch_actuals.py` has run."
    )
elif df_filtered.empty:
    st.info(f"No data in the selected date range ({date_range}). Try 'All Time'.")
else:
    line_df = analysis.load_actuals_vs_forecast_by_lead(df_filtered, lead_hours_target=selected_lead)
    if line_df.empty:
        st.info(
            f"No forecasts found near {selected_lead}h lead time. "
            "Try a different lead time or wait for more data."
        )
    else:
        fig_main = go.Figure()
        fig_main.add_trace(go.Scatter(
            x=line_df["target_time"], y=line_df["actual_temp_c"],
            mode="lines", name="Actual",
            line=dict(color="#2ecc71", width=2.5),
        ))
        fig_main.add_trace(go.Scatter(
            x=line_df["target_time"], y=line_df["forecast_temp_c"],
            mode="lines", name=f"Forecast (~{selected_lead}h lead)",
            line=dict(color="#3498db", width=1.5, dash="dot"),
        ))
        fig_main.update_layout(
            xaxis_title=f"Time ({LOCAL_TZ})",
            yaxis_title="Temperature (°C)",
            height=450,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            margin=dict(t=40, b=40),
        )
        st.plotly_chart(fig_main, use_container_width=True)


# ---------------------------------------------------------------------------
# Tabs
# ---------------------------------------------------------------------------

tab_overview, tab_health, tab_convergence = st.tabs(
    ["Data Overview", "Process Health", "Convergence"]
)


# ============================================================================
# TAB 1 – DATA OVERVIEW
# ============================================================================
with tab_overview:
    first_both   = parse_utc_str(extents[0] if extents else None)
    last_both    = parse_utc_str(extents[1] if extents else None)
    last_refresh = parse_utc_str(last_fc[0] if last_fc else None)

    c1, c2, c3 = st.columns(3)
    c1.metric(
        "First hour with both",
        first_both.strftime("%Y-%m-%d %H:%M") if first_both else "—",
    )
    c2.metric(
        "Last hour with both",
        last_both.strftime("%Y-%m-%d %H:%M") if last_both else "—",
    )
    c3.metric(
        "Last forecast refresh",
        last_refresh.strftime("%Y-%m-%d %H:%M") if last_refresh else "—",
    )

    st.divider()

    st.subheader("Actual vs Multiple Forecast Lead Times")
    st.caption(
        "Each dotted line shows the forecast made ~N hours before the target time. "
        "The solid green line is what actually happened."
    )

    if df.empty:
        st.info("No matched forecast/actual rows yet.")
    elif df_filtered.empty:
        st.info(f"No data in the selected date range ({date_range}). Try 'All Time'.")
    else:
        multi_df = analysis.load_multi_lead_comparison(df_filtered, lead_buckets=[24, 48, 72, 96])
        if multi_df.empty:
            st.info("Not enough data for multi-lead comparison yet.")
        else:
            SERIES_COLORS = {
                "Actual":       "#2ecc71",
                "24h forecast": "#3498db",
                "48h forecast": "#e67e22",
                "72h forecast": "#9b59b6",
                "96h forecast": "#e74c3c",
            }
            fig_multi = go.Figure()
            for name, color in SERIES_COLORS.items():
                sub = multi_df[multi_df["series"] == name]
                if sub.empty:
                    continue
                is_actual = name == "Actual"
                fig_multi.add_trace(go.Scatter(
                    x=sub["target_time"],
                    y=sub["temperature_c"],
                    mode="lines",
                    name=name,
                    line=dict(
                        color=color,
                        width=2.5 if is_actual else 1.5,
                        dash="solid" if is_actual else "dot",
                    ),
                ))
            fig_multi.update_layout(
                xaxis_title=f"Time ({LOCAL_TZ})",
                yaxis_title="Temperature (°C)",
                height=500,
                legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
                margin=dict(t=40, b=40),
            )
            st.plotly_chart(fig_multi, use_container_width=True)

    st.divider()
    st.subheader("Raw Data")

    rows_shown = min(100, len(df_filtered))
    with st.expander(
        f"Joined dataset — {len(df):,} total rows; showing {rows_shown:,} most recent (date filter applied)"
    ):
        if df_filtered.empty:
            st.info(f"No data in the selected date range ({date_range}).")
        else:
            st.dataframe(
                df_filtered.sort_values("target_time", ascending=False).head(100),
                use_container_width=True,
            )

    with st.expander(f"Forecasts table — {len(raw_fc_df):,} most recent rows"):
        st.dataframe(raw_fc_df, use_container_width=True)

    with st.expander(f"Actuals table — {len(raw_act_df):,} most recent rows"):
        st.dataframe(raw_act_df, use_container_width=True)


# ============================================================================
# TAB 2 – PROCESS HEALTH
# ============================================================================
with tab_health:
    h1, h2, h3 = st.columns(3)

    if last_fc:
        fc_time = parse_utc_str(last_fc[0])
        h1.metric("Last forecast fetch", fc_time.strftime("%Y-%m-%d %H:%M") if fc_time else "—")
        h1.caption(f"{last_fc[1]} rows in that fetch")
    else:
        h1.metric("Last forecast fetch", "—")

    if last_act and last_act[0]:
        act_time = parse_utc_str(last_act[0])
        h2.metric("Last actual observation", act_time.strftime("%Y-%m-%d %H:%M") if act_time else "—")
        h2.caption(f"{last_act[1]} observations in last 48h")
    else:
        h2.metric("Last actual observation", "—")

    if not fetch_log_df.empty:
        seven_days_ago = pd.Timestamp.now("UTC").tz_convert(LOCAL_TZ) - pd.Timedelta(days=7)
        n_errors = int(
            ((fetch_log_df["status"] == "error") & (fetch_log_df["started_at"] >= seven_days_ago)).sum()
        )
        h3.metric("Fetch errors (last 7 days)", n_errors)
    else:
        h3.metric("Fetch errors (last 7 days)", "—")

    st.divider()

    st.subheader("Daily Data Collection")

    fig_fc = go.Figure(go.Bar(
        x=health_df["date"],
        y=health_df["fetch_runs"],
        marker_color="#3498db",
    ))
    fig_fc.update_layout(
        title="Forecast Fetch Runs per Day",
        xaxis_title="Date",
        yaxis_title="Fetch runs",
        height=260,
        showlegend=False,
        margin=dict(t=40, b=10),
    )
    st.plotly_chart(fig_fc, use_container_width=True)
    st.caption("Distinct API calls per day — typically 1–2 when the cron job is healthy.")

    fig_act = go.Figure(go.Bar(
        x=health_df["date"],
        y=health_df["actual_rows"],
        marker_color="#2ecc71",
    ))
    fig_act.update_layout(
        title="Actual Observations per Day",
        xaxis_title="Date",
        yaxis_title="Hourly observations",
        height=260,
        showlegend=False,
        margin=dict(t=40, b=40),
    )
    st.plotly_chart(fig_act, use_container_width=True)
    st.caption("Hourly NWS records stored per day — 24 means full-day coverage.")

    st.divider()
    st.subheader("Fetch History")

    if fetch_log_df.empty:
        st.info("No fetch history yet — will populate after the next cron run.")
    else:
        def _highlight_errors(row):
            bg = "background-color: #ffebee" if row["status"] == "error" else ""
            return [bg] * len(row)

        st.dataframe(
            fetch_log_df.style.apply(_highlight_errors, axis=1),
            use_container_width=True,
            hide_index=True,
        )


# ============================================================================
# TAB 3 – CONVERGENCE
# ============================================================================
with tab_convergence:
    st.info(
        "**Planned:** visualizations of how forecasts for a given hour converge toward "
        "the actual as the lead time shrinks — e.g. is the 96h forecast systematically "
        "off in ways the 24h forecast is not? The views below are a starting point."
    )

    if not df.empty:
        # -- Error distributions --
        st.subheader("Forecast error by lead time")
        st.caption("error = forecast − actual (°C). Boxes should narrow and center on 0 as lead time shrinks.")

        bin_hours = st.select_slider(
            "Lead time bucket size (hours)", options=[6, 12, 24, 48], value=24,
            key="conv_bin_hours",
        )
        lead_df = analysis.bucket_lead_hours(df, bin_hours=bin_hours)
        lead_df["lead_bucket_label"] = lead_df["lead_bucket"].apply(
            lambda h: f"{h}–{h + bin_hours}h"
        )
        order = [f"{h}–{h + bin_hours}h" for h in sorted(lead_df["lead_bucket"].unique())]
        fig_box = px.box(
            lead_df, x="lead_bucket_label", y="error_c",
            category_orders={"lead_bucket_label": order},
            points="outliers",
            labels={"lead_bucket_label": "Lead time bucket", "error_c": "Error (°C)"},
        )
        fig_box.add_hline(y=0, line_dash="dot", line_color="gray")
        st.plotly_chart(fig_box, use_container_width=True)

        st.divider()

        st.subheader("Forecast error by actual temperature (10°C buckets)")
        st.caption(
            "Bucketed by ACTUAL temperature so the split itself can't be biased by forecast error. "
            "Violin shows full distribution shape; box inside shows quartiles."
        )
        temp_df, temp_order = analysis.decade_temp_buckets(df)
        fig_violin = px.violin(
            temp_df, x="actual_temp_bucket", y="error_c", box=True, points="outliers",
            category_orders={"actual_temp_bucket": temp_order},
            labels={"actual_temp_bucket": "Actual temp bucket", "error_c": "Error (°C)"},
        )
        fig_violin.add_hline(y=0, line_dash="dot", line_color="gray")
        st.plotly_chart(fig_violin, use_container_width=True)

        st.divider()

        # -- Convergence toward actual --
        st.subheader("Forecast convergence toward the actual")

        counts, max_vintages = analysis.target_time_completeness(df)
        complete_times = counts.loc[counts["is_complete"], "target_time"]

        view_mode = st.radio(
            "View",
            [
                f"All complete records ({len(complete_times)} hours with all "
                f"{max_vintages} vintages + an actual)",
                "One specific hour",
            ],
            index=0,
            key="conv_mode",
        )

        if view_mode.startswith("All"):
            plot_df = df[df["target_time"].isin(complete_times)].copy()
            agg = (
                plot_df.groupby("lead_hours")["error_c"]
                .agg(
                    median="median",
                    q25=lambda s: s.quantile(0.25),
                    q75=lambda s: s.quantile(0.75),
                    n="count",
                )
                .reset_index()
                .sort_values("lead_hours")
            )
            fig_conv = go.Figure()
            fig_conv.add_trace(go.Scatter(
                x=agg["lead_hours"], y=agg["q75"],
                mode="lines", line=dict(width=0), showlegend=False, hoverinfo="skip",
            ))
            fig_conv.add_trace(go.Scatter(
                x=agg["lead_hours"], y=agg["q25"],
                mode="lines", line=dict(width=0),
                fill="tonexty", fillcolor="rgba(31,78,121,0.2)",
                name="IQR (25th–75th pct)",
            ))
            fig_conv.add_trace(go.Scatter(
                x=agg["lead_hours"], y=agg["median"],
                mode="lines+markers", line=dict(color="#1f4e79"),
                name="Median error",
            ))
            fig_conv.add_hline(y=0, line_dash="dot", line_color="gray")
            fig_conv.update_xaxes(autorange="reversed", title="Lead time (hours) — further out ←")
            fig_conv.update_yaxes(title="Error, forecast − actual (°C)")
            fig_conv.update_layout(height=500)
            st.plotly_chart(fig_conv, use_container_width=True)
            st.caption(
                f"{agg['n'].sum():,} forecast points across {len(complete_times)} complete target hours. "
                "Only hours where every scheduled vintage was captured AND an actual is on file."
            )
        else:
            options = (
                df[df["target_time"].isin(complete_times)]["target_time"]
                .drop_duplicates().sort_values(ascending=False)
            )
            if options.empty:
                st.info("No fully-complete hours yet to pick from.")
            else:
                picked = st.selectbox(
                    "Target hour (local time)",
                    options,
                    format_func=lambda t: t.strftime("%Y-%m-%d %H:%M %Z"),
                    key="conv_hour_pick",
                )
                day_df = df[df["target_time"] == picked].sort_values("lead_hours")
                actual_temp = day_df["actual_temp_c"].iloc[0]

                fig_single = go.Figure()
                fig_single.add_trace(go.Scatter(
                    x=day_df["lead_hours"], y=day_df["forecast_temp_c"],
                    mode="lines+markers", name="Forecast temp",
                    line=dict(color="#1f4e79"),
                ))
                fig_single.add_hline(
                    y=actual_temp, line_dash="dash", line_color="#c0392b",
                    annotation_text=f"Actual: {actual_temp:.1f}°C",
                )
                fig_single.update_xaxes(autorange="reversed", title="Lead time (hours) — further out ←")
                fig_single.update_yaxes(title="Temperature (°C)")
                fig_single.update_layout(height=500)
                st.plotly_chart(fig_single, use_container_width=True)
