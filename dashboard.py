"""
Streamlit dashboard for the weather-bias-tracker data.

Run with:
    streamlit run dashboard.py

Four tabs:
    Coverage     - at-a-glance view of what data exists (forecast only vs.
                   forecast + actual), by date and hour.
    Distributions- box/violin plots of forecast error, by lead time and by
                   actual-temperature bucket.
    Convergence  - watch forecasts for a given hour approach the actual as
                   lead time shrinks, either for one specific hour or
                   aggregated (median + IQR band) across all complete records.
    Bias Summary - the original mean-error tables, kept for later when it's
                   time to think about bias correction / ML.
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
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
def load_joined():
    with db.get_conn() as conn:
        return analysis.load_joined(conn)


@st.cache_data(ttl=300)
def load_coverage():
    with db.get_conn() as conn:
        return analysis.load_coverage(conn)


df = load_joined()
coverage_df = load_coverage()

if coverage_df.empty:
    st.warning(
        "No forecast data yet. Once `fetch_forecast.py` has run at least "
        "once, coverage info will show up here."
    )
    st.stop()

tab_coverage, tab_dist, tab_convergence, tab_bias = st.tabs(
    ["Coverage", "Distributions", "Convergence", "Bias Summary"]
)

# ============================================================================
# TAB 1: COVERAGE
# ============================================================================
with tab_coverage:
    st.subheader("Data coverage: hour x date")
    st.caption(
        "Each cell is one target hour. Dark = forecast + actual both on "
        "file. Light = forecast only (usually future hours, or actuals "
        "just haven't been fetched yet). Blank = no forecast at all for "
        "that hour (e.g. a missed cron run, or before you started collecting)."
    )

    grid = coverage_df.pivot_table(
        index="hour", columns="date", values="status", aggfunc="max"
    )
    vintage_grid = coverage_df.pivot_table(
        index="hour", columns="date", values="vintage_count", aggfunc="max"
    )

    fig = go.Figure(
        data=go.Heatmap(
            z=grid.values,
            x=[str(d) for d in grid.columns],
            y=grid.index,
            customdata=vintage_grid.values,
            colorscale=[[0, "#f0f2f6"], [0.5, "#f0f2f6"], [0.5, "#ffd9a8"], [1, "#1f4e79"]],
            zmin=0, zmax=2,
            colorbar=dict(
                tickvals=[1, 2],
                ticktext=["Forecast only", "Forecast + actual"],
            ),
            hovertemplate=(
                "date=%{x}<br>hour=%{y}:00 UTC<br>"
                "vintages on file=%{customdata}<extra></extra>"
            ),
        )
    )
    fig.update_layout(
        xaxis_title="Date", yaxis_title="Hour (UTC)",
        yaxis=dict(dtick=2), height=500,
    )
    st.plotly_chart(fig, use_container_width=True)

    c1, c2, c3 = st.columns(3)
    total_hours = len(coverage_df)
    both = (coverage_df["status"] == 2).sum()
    forecast_only = (coverage_df["status"] == 1).sum()
    c1.metric("Target hours with forecast data", f"{total_hours:,}")
    c2.metric("...with a matching actual", f"{both:,}")
    c3.metric("...forecast only (so far)", f"{forecast_only:,}")

# ============================================================================
# TAB 2: DISTRIBUTIONS
# ============================================================================
with tab_dist:
    if df.empty:
        st.info(
            "No matched forecast/actual rows yet - once some forecast "
            "target hours are in the past and actuals have been fetched "
            "for them, distributions will show up here."
        )
    else:
        st.subheader("Forecast error by lead time")
        st.caption(
            "error = forecast - actual, in C. Each box is one lead-time "
            "bucket. Watch for the boxes narrowing and centering on 0 as "
            "lead time shrinks."
        )
        bin_hours = st.select_slider(
            "Lead time bucket size (hours)", options=[6, 12, 24, 48], value=24,
            key="dist_bin_hours",
        )
        lead_df = analysis.bucket_lead_hours(df, bin_hours=bin_hours)
        lead_df["lead_bucket_label"] = lead_df["lead_bucket"].apply(
            lambda h: f"{h}-{h + bin_hours}h"
        )
        # Sort by numeric lead_bucket values, then create ordered labels
        order = [f"{h}-{h + bin_hours}h" for h in sorted(lead_df["lead_bucket"].unique())]
        fig_box = px.box(
            lead_df, x="lead_bucket_label", y="error_c",
            category_orders={"lead_bucket_label": order},
            points="outliers",
            labels={"lead_bucket_label": "Lead time bucket", "error_c": "Error (C)"},
        )
        fig_box.add_hline(y=0, line_dash="dot", line_color="gray")
        st.plotly_chart(fig_box, use_container_width=True)

        st.divider()

        st.subheader("Forecast error by actual temperature (10C buckets)")
        st.caption(
            "Buckets are fixed 10C-wide bins based on the ACTUAL recorded "
            "temperature (not the forecast), so the bucketing itself can't "
            "be biased by forecast error. Violin shows the full error "
            "distribution shape - useful for spotting skew/asymmetry that "
            "a box plot's quartiles alone can hide."
        )
        temp_df, temp_order = analysis.decade_temp_buckets(df, bucket_size=10)
        fig_violin = px.violin(
            temp_df, x="actual_temp_bucket", y="error_c", box=True, points="outliers",
            category_orders={"actual_temp_bucket": temp_order},
            labels={"actual_temp_bucket": "Actual temperature bucket", "error_c": "Error (C)"},
        )
        fig_violin.add_hline(y=0, line_dash="dot", line_color="gray")
        st.plotly_chart(fig_violin, use_container_width=True)

# ============================================================================
# TAB 3: CONVERGENCE
# ============================================================================
with tab_convergence:
    if df.empty:
        st.info("No matched forecast/actual rows yet.")
    else:
        st.subheader("Forecast convergence toward the actual")

        counts, max_vintages = analysis.target_time_completeness(df)
        complete_times = counts.loc[counts["is_complete"], "target_time"]

        mode = st.radio(
            "View",
            [
                f"All complete records ({len(complete_times)} hours with all "
                f"{max_vintages} vintages + an actual)",
                "One specific hour",
            ],
            index=0,
        )

        if mode.startswith("All complete"):
            plot_df = df[df["target_time"].isin(complete_times)].copy()
            plot_df = plot_df.sort_values("lead_hours")

            agg = (
                plot_df.groupby("lead_hours")["error_c"]
                .agg(median="median", q25=lambda s: s.quantile(0.25),
                     q75=lambda s: s.quantile(0.75), n="count")
                .reset_index()
                .sort_values("lead_hours")
            )

            fig = go.Figure()
            fig.add_trace(go.Scatter(
                x=agg["lead_hours"], y=agg["q75"], mode="lines",
                line=dict(width=0), showlegend=False, hoverinfo="skip",
            ))
            fig.add_trace(go.Scatter(
                x=agg["lead_hours"], y=agg["q25"], mode="lines",
                line=dict(width=0), fill="tonexty", fillcolor="rgba(31,78,121,0.2)",
                name="IQR (25th-75th pct)",
            ))
            fig.add_trace(go.Scatter(
                x=agg["lead_hours"], y=agg["median"], mode="lines+markers",
                line=dict(color="#1f4e79"), name="Median error",
            ))
            fig.add_hline(y=0, line_dash="dot", line_color="gray")
            fig.update_xaxes(autorange="reversed", title="Lead time (hours, further out to the left)")
            fig.update_yaxes(title="Error, forecast - actual (C)")
            fig.update_layout(height=500)
            st.plotly_chart(fig, use_container_width=True)
            st.caption(
                f"n = {agg['n'].sum():,} forecast points across "
                f"{len(complete_times)} complete target hours. "
                "Only hours where every scheduled forecast run was captured "
                "AND an actual is on file are included, so lead-time "
                "coverage is apples-to-apples across the x-axis."
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
                    "Target hour (UTC)",
                    options,
                    format_func=lambda t: t.strftime("%Y-%m-%d %H:%M UTC"),
                )
                day_df = df[df["target_time"] == picked].sort_values("lead_hours")
                actual_temp = day_df["actual_temp_c"].iloc[0]

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=day_df["lead_hours"], y=day_df["forecast_temp_c"],
                    mode="lines+markers", name="Forecast temp",
                    line=dict(color="#1f4e79"),
                ))
                fig.add_hline(
                    y=actual_temp, line_dash="dash", line_color="#c0392b",
                    annotation_text=f"Actual: {actual_temp:.1f}C",
                )
                fig.update_xaxes(autorange="reversed", title="Lead time (hours, further out to the left)")
                fig.update_yaxes(title="Temperature (C)")
                fig.update_layout(height=500)
                st.plotly_chart(fig, use_container_width=True)

# ============================================================================
# TAB 4: BIAS SUMMARY
# ============================================================================
with tab_bias:
    if df.empty:
        st.info("No matched forecast/actual rows yet.")
    else:
        st.caption(
            "Plain summary tables - handy reference for later when it's "
            "time to think about bias correction. error = forecast - actual."
        )
        col1, col2, col3 = st.columns(3)
        col1.metric("Matched rows", f"{len(df):,}")
        col2.metric("Mean error (C)", f"{df['error_c'].mean():.2f}")
        col3.metric("Mean absolute error (C)", f"{df['error_c'].abs().mean():.2f}")

        st.subheader("Mean error by lead-time bucket")
        st.dataframe(
            analysis.bias_by_lead_bucket(df, bin_hours=24).round(2),
            hide_index=True, use_container_width=True,
        )

        st.subheader("Mean error by actual-temperature bucket (10C)")
        st.dataframe(
            analysis.bias_by_temp_bucket(df, bucket_size=10).round(2),
            hide_index=True, use_container_width=True,
        )

        st.subheader("Cross-tab: temperature bucket x lead-time bucket")
        st.dataframe(
            analysis.bias_by_temp_and_lead(df, bin_hours=24, bucket_size=10).round(2),
            use_container_width=True,
        )
