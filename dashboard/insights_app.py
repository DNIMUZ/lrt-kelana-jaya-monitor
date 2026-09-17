from __future__ import annotations

from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

from src.analysis.insights import (
    WEEKDAY_ORDER,
    author_activity,
    detect_ridership_anomalies,
    ridge_forecast,
    signal_ridership_lag_correlation,
    station_mention_counts,
    weekday_seasonality,
)
from src.analysis.merged import (
    daily_signal_counts,
    load_ridership_headline,
    load_signals_dataframe,
    merge_daily_panel,
)

ROOT = Path(__file__).parents[1]
DEFAULT_DB = ROOT / "data" / "lrt_monitor.db"
DEFAULT_RIDERSHIP = ROOT / "data" / "ridership_headline.csv"
RIDERSHIP_LABEL = "rail_lrt_kj ridership"

st.set_page_config(page_title="LRT Kelana Jaya | Insights", page_icon="LRT", layout="wide")
st.title("Kelana Jaya Line - Social & Ridership Insights")
st.caption("Public Threads signals x data.gov.my daily ridership | signals are estimates, not official announcements")

with st.sidebar:
    st.header("Data sources")
    ridership_path = st.text_input("Gov ridership CSV (daily)", value=str(DEFAULT_RIDERSHIP))
    db_path = st.text_input("Signals SQLite DB", value=str(DEFAULT_DB))
    allowed = st.multiselect(
        "Ridership series to compare",
        ["rail_lrt_kj", "rail_lrt_ampang", "rail_mrt_kajang", "rail_mrt_pjy", "rail_lrt_shah_alam", "rail_monorail"],
        default=["rail_lrt_kj"],
        help="Monitor compares all against signal/history; focus stays on rail_lrt_kj.",
    )


@st.cache_data(show_spinner=False)
def load_data(ridership_path: str, db_path: str):
    signals = load_signals_dataframe(db_path)
    ridership = load_ridership_headline(ridership_path)
    panel = merge_daily_panel(signals, ridership)
    counts = daily_signal_counts(signals)
    return signals, ridership, panel, counts


signals, ridership, panel, counts = load_data(ridership_path, db_path)
latest_ridership = panel["date"].max()
kj = panel.dropna(subset=["ridership"])

if signals.empty:
    st.warning("No signals in the database. Run `python -m src.collectors.threads_bulk` or `threads_scraper` first.")

overview_tab, season_tab, social_tab, correlation_tab = st.tabs(
    ["Overview", "Seasonality & Anomalies", "Social Signals", "Correlation & Forecast"]
)

with overview_tab:
    st.subheader("Rail Kelana Jaya - headline indicators")
    this_year = kj[kj["date"].dt.year == 2026]
    last_year = kj[kj["date"].dt.year == 2025]
    top, kpi_a, kpi_b, kpi_c, kpi_d = st.columns([1, 1, 1, 1, 1])
    top.markdown("**Averages (2026 to date)**")
    kpi_a.metric("Avg daily ridership", f"{this_year['ridership'].mean():,.0f}")
    kpi_b.metric(
        "Vs same period 2025",
        f"{(this_year['ridership'].mean() / last_year['ridership'].mean() - 1) * 100:.1f}%",
        delta_color="inverse",
    )
    kpi_c.metric("Peak day 2026", f"{this_year['ridership'].max():,.0f}")
    kpi_d.metric("Busiest weekday", weekday_seasonality(kj).sort_values("average", ascending=False).iloc[0]["weekday"])

    chart = alt.Chart(kj).mark_line().encode(
        x=alt.X("date:T", title="Date"),
        y=alt.Y("ridership:Q", title="Daily passengers"),
        tooltip=["date", "ridership"],
    ) + alt.Chart(panel).mark_point(size=30).encode(
        x="date:T", y="ridership:Q", color=alt.condition("datum.disruption > 0", alt.value("red"), alt.value("steelblue"))
    )
    st.altair_chart(chart.properties(height=360), width="stretch")
    st.caption("Red dots mark days with at least one Threads disruption mention - most are shared-station chatter.")

    week_stats = weekday_seasonality(kj)
    bar = (
        alt.Chart(week_stats)
        .mark_bar()
        .encode(
            x=alt.X("weekday:N", sort=WEEKDAY_ORDER),
            y="average:Q",
            tooltip=["weekday", "average", "days"],
        )
    )
    st.altair_chart(bar.properties(height=300, title="Average ridership by weekday"), width="stretch")

with season_tab:
    st.subheader("Seasonality & anomaly days")
    anomalies = detect_ridership_anomalies(kj)
    anomalous_days = anomalies[anomalies["anomalous"]]
    st.metric("Unusually-low ridership days detected", len(anomalous_days))
    amount = kj["ridership"].mean() if len(kj) else 0
    if not anomalous_days.empty:
        low_col, sample_col = st.columns([1, 2])
        with low_col:
            st.write("**Days flagged (z-score below -2 vs 28-day trend)**")
            st.dataframe(
                anomalous_days[["date", "ridership", "baseline", "z_score", "disruption"]]
                .sort_values("z_score")
                .reset_index(drop=True),
                hide_index=True,
                width="stretch",
            )
        with sample_col:
            annotated = alt.Chart(anomalous_days).mark_circle(size=80).encode(
                x=alt.X("date:T"),
                y=alt.Y("ridership:Q"),
                color="z_score:Q",
                tooltip=["date", "ridership", "z_score", "disruption"],
            )
            trend = alt.Chart(kj).mark_line(opacity=0.4).encode(x="date:T", y="baseline:Q")
            st.altair_chart((trend + annotated).properties(height=320), width="stretch")
        st.info(
            f"Detected {len(anomalous_days)} low-demand days ({len(anomalous_days) / max(len(kj), 1):.1%} of all days). "
            f"Hover the annotated chart to see coinciding social chatter. Typical cause: public holidays and long weekends."
        )
    else:
        st.write("No unusual days found in the current window.")
    monthly = panel.dropna(subset=["ridership"]).groupby(["year", "month"])["ridership"].mean().reset_index()
    heat = (
        alt.Chart(monthly)
        .mark_rect()
        .encode(
            x=alt.X("month:O", title="Month"),
            y=alt.Y("year:O", title="Year"),
            color=alt.Color("ridership:Q", scale=alt.Scale(scheme="blues")),
            tooltip=["year", "month", "ridership"],
        )
    )
    st.altair_chart(heat.properties(height=320, title="Ridership heatmap (avg per year-month)"), width="stretch")

with social_tab:
    st.subheader("Threads social signals")
    if counts.empty:
        st.info("No signals available yet - scrape first.")
    else:
        col_a, col_b, col_c = st.columns(3)
        col_a.metric("Total posts", int(counts["total"].sum()))
        col_b.metric("Unique authors", int(counts["unique_authors"].sum()))
        col_c.metric("Disruption posts", int(counts["disruption"].sum()))

        category_tall = counts[["date", "normal", "crowding", "delay", "disruption", "other"]].melt(
            id_vars="date", var_name="category", value_name="posts"
        )
        stacked = (
            alt.Chart(category_tall)
            .mark_area()
            .encode(
                x=alt.X("date:T", title="Date"),
                y=alt.Y("posts:Q", stack="zero", title="Posts per day"),
                color=alt.Color(
                    "category:N",
                    scale=alt.Scale(
                        domain=["disruption", "delay", "crowding", "normal", "other"],
                        range=["#d62728", "#ff7f0e", "#9467bd", "#1f77b4", "#bbbbbb"],
                    ),
                ),
                tooltip=["date", "category", "posts"],
            )
        )
        st.altair_chart(stacked.properties(height=320, title="Daily posts by category"), width="stretch")

        station_col, author_col = st.columns(2)
        with station_col:
            mentions = station_mention_counts(signals)
            if mentions.empty:
                st.info("No station-detected posts.")
            else:
                st.altair_chart(
                    alt.Chart(mentions.head(12)).mark_bar().encode(
                        y=alt.Y("station:N", sort="-x", title="Station"),
                        x=alt.X("posts:Q", title="Posts"),
                        tooltip=["station", "posts"],
                    ).properties(height=360, title="Most-mentioned stations"),
                    width="stretch",
                )
        with author_col:
            authors = author_activity(signals)
            if authors.empty:
                st.info("No author IDs recorded.")
            else:
                st.altair_chart(
                    alt.Chart(authors.head(12)).mark_bar().encode(
                        y=alt.Y("author_id:N", sort="-x", title="Author"),
                        x=alt.X("posts:Q", title="Posts"),
                        tooltip=["author_id", "posts"],
                    ).properties(height=360, title="Most active authors"),
                    width="stretch",
                )

        st.subheader("Sample signal text")
        st.dataframe(
            signals.sort_values("observed_at", ascending=False)[["observed_at", "category", "station", "text"]].head(25).reset_index(
                drop=True
            ),
            hide_index=True,
            width="stretch",
        )

def render_forecast(kj: pd.DataFrame, panel: pd.DataFrame) -> None:
    st.subheader("7-28 day ridership forecast (weekday-driven ridge model)")
    with st.spinner("Training forecast model..."):
        result = ridge_forecast(panel)
    if "error" in result:
        st.warning(result["error"])
        return
    metrics = result["metrics"]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Holdout MAE", f"{metrics['mae']:,.0f} passengers")
    m2.metric("Holdout MAPE", f"{metrics['mape_pct']:.1f}%")
    m3.metric("Holdout R²", f"{metrics['r2']:.3f}")
    m4.metric("Test horizon", f"{result['test_days']} days")

    history = kj[["date", "ridership"]].tail(120)
    test = result["actual_test"].rename_axis("date").reset_index()
    test["kind"] = "actual"
    test_pred = result["predicted_test"].rename_axis("date").reset_index()
    test_pred["kind"] = "predicted"
    future = result["forecast"].rename(columns={"forecast": "ridership"})
    future["kind"] = "forecast"

    view = pd.concat([history.reset_index(drop=True), test_pred.reset_index(drop=True), future.reset_index(drop=True)], ignore_index=True)
    lines = (
        alt.Chart(view)
        .mark_line()
        .encode(
            x="date:T",
            y="ridership:Q",
            color=alt.Color("kind:N"),
            strokeDash=alt.StrokeDash("kind:N", sort=["actual", "predicted", "forecast"]),
            tooltip=["date", "ridership", "kind"],
        )
    )
    st.altair_chart(lines.properties(height=340), width="stretch")
    st.caption(
        "Features: weekday, month, is_weekend, days elapsed, previous-day ridership, 7-day average. "
        "The social-feature overlap window is short (≈30 days), so weekday seasonality dominates; "
        "prediction improves when the Threads corpus grows."
    )


with correlation_tab:
    st.subheader("Social chatter x ridership")
    signal_span = f"{counts['date'].min().date()} to {counts['date'].max().date()}" if not counts.empty else "no signal dates"
    ridership_span = f"{kj['date'].min().date()} to {kj['date'].max().date()}" if not kj.empty else "no ridership dates"
    shared_days = int((kj["disruption"].gt(0)).sum())
    st.write(f"Threads signals cover **{signal_span}** | official ridership covers **{ridership_span}**")
    if shared_days == 0:
        st.warning(
            "The official data.gov.my ridership series is published ~6-8 weeks behind. It currently ends before the "
            "Threads window, so the direct same-day correlation is not yet measurable. The forecast above still works "
            "on ridership alone; re-open this tab after the next official publication and the correlation unlocks "
            "automatically."
        )
    if counts.empty:
        st.info("Add Threads data to unlock the correlation and forecast views.")
    elif shared_days > 0:
        overlap = panel.dropna(subset=["ridership"]).loc[panel["disruption"] > 0]
        corr = signal_ridership_lag_correlation(panel)
        if not corr.empty:
            st.write("**Correlation: daily disruption mentions vs rail_lrt_kj ridership (by lag)**")
            lag_chart = (
                alt.Chart(corr)
                .mark_bar()
                .encode(
                    x=alt.X("lag_days:O", title="Lag (days)"),
                    y=alt.Y("correlation:Q", title="Pearson r"),
                    tooltip=["lag_days", "correlation"],
                    color=alt.condition(alt.datum.correlation >= 0, alt.value("#1f77b4"), alt.value("#d62728")),
                )
            )
            st.altair_chart(lag_chart.properties(height=280), width="stretch")
            best = corr.loc[corr["correlation"].abs().idxmax()]
            st.caption(
                f"Strongest link at lag {int(best['lag_days'])}d (r={best['correlation']:.2f}) - read as the social "
                f"signal leading/trailing ridership changes, not causation."
            )

        scatter = (
            alt.Chart(overlap)
            .mark_circle(size=60)
            .encode(
                x=alt.X("ridership:Q", title="Daily ridership (rail_lrt_kj)"),
                y=alt.Y("disruption:Q", title="Disruption posts"),
                tooltip=["date", "ridership", "disruption"],
            )
        )
        st.altair_chart(scatter.properties(height=280, title="Ridership vs same-day disruption posts"), width="stretch")
    else:
        expected = weekday_seasonality(kj)
        mapping = expected.set_index("weekday")["average"]
        predicted_rows = [
            {"date": day, "expected_ridership": mapping[day.day_name()]}
            for day in counts[counts["disruption"] > 0]["date"]
        ]
        predicted = pd.DataFrame(predicted_rows)
        if not predicted.empty:
            col_p1, col_p2 = st.columns(2)
            with col_p1:
                st.metric("Disruption-signal days in window", len(predicted))
            with col_p2:
                chaotic = predicted["expected_ridership"].mean()
                st.metric("Hypothetical avg weekday ridership", f"{chaotic:,.0f}", help="Historical weekday average applied to the signal window")
            st.caption(
                "These are counterfactual, not observed: applying the 2019-2026 weekday average to the days Threads "
                "reported disruptions. Rabu/Khamis (mid-week) historically carry the highest volume ~220k; weekend "
                "nights drop to ~115k. When the official series catches up you get the true comparison."
            )
    render_forecast(kj, panel)