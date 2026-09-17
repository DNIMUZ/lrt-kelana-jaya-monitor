from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analysis.insights import (
    WEEKDAY_ORDER,
    delay_disruption_counts,
    detect_ridership_anomalies,
    phrase_mentions,
    ridge_forecast,
    signal_ridership_lag_correlation,
    trend_split,
    weekday_seasonality,
)
from src.analysis.merged import daily_signal_counts, load_ridership_headline, merge_daily_panel


def _synthetic_signals() -> pd.DataFrame:
    rows = [
        {"text": "lrt sesak pagi", "category": "crowding", "station": "KJ24", "author_id": "a1", "observed_at": "2026-09-01T00:30:00+00:00"},
        {"text": "lrt kelana jaya rosak", "category": "disruption", "station": "KJ24", "author_id": "a2", "observed_at": "2026-09-01T01:00:00+00:00"},
        {"text": "lrt delay", "category": "delay", "station": None, "author_id": "a3", "observed_at": "2026-09-02T12:00:00+00:00"},
        {"text": "naik mrt", "category": "other", "station": "KJ1", "author_id": "a1", "observed_at": "2026-09-02T13:00:00+00:00"},
    ]
    return pd.DataFrame(rows)


def _spread_signals(start: str = "2026-08-01", days: int = 14, every: int = 1) -> pd.DataFrame:
    rows = []
    for offset in range(days):
        day = pd.Timestamp(start) + pd.Timedelta(days=offset)
        if offset % every != 0:
            continue
        rows.append(
            {
                "text": f"lrt problem hari ke-{offset}",
                "category": "disruption",
                "station": "KJ24" if offset % 2 == 0 else "KJ1",
                "author_id": f"author{offset}",
                "observed_at": (day + pd.Timedelta(hours=offset % 24)).isoformat(),
            }
        )
    return pd.DataFrame(rows)


def _overlapping_ridership(start: str = "2026-07-25", days: int = 50) -> pd.DataFrame:
    dates = pd.date_range(start, periods=days, freq="D")
    values = np.where(dates.dayofweek < 5, 200_000, 110_000).astype(float)
    return pd.DataFrame({"date": dates, "rail_lrt_kj": values})


def _synthetic_ridership(days: int = 400) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=days, freq="D")
    values = np.where(dates.dayofweek < 5, 200_000, 110_000).astype(float)
    values = values + np.random.default_rng(7).normal(0, 6000, days)
    values = np.clip(values, 40_000, 400_000)
    values[100:104] = 80_000
    return pd.DataFrame({"date": dates, "rail_lrt_kj": values})


def test_malaysia_timezone_bucketing() -> None:
    signals = _synthetic_signals()
    counts = daily_signal_counts(signals)
    assert counts["date"].iloc[0].date().isoformat() == "2026-09-01"
    first_day = counts[counts["date"] == pd.Timestamp("2026-09-01")].iloc[0]
    assert first_day["disruption"] == 1
    assert first_day["crowding"] == 1


def test_merge_panel_aligns_dates_and_zero_fills() -> None:
    signals = _spread_signals()
    panel = merge_daily_panel(signals, _overlapping_ridership())
    assert (panel["disruption"] == 0).sum() > 10
    assert panel[panel["disruption"] == 1]["ridership"].notna().all()


def test_weekday_seasonality_order() -> None:
    panel = merge_daily_panel(_synthetic_signals(), _synthetic_ridership())
    stats = weekday_seasonality(panel)
    assert list(stats["weekday"]) == WEEKDAY_ORDER
    assert stats.loc[stats["weekday"] == "Saturday", "average"].iloc[0] < 200_000


def test_anomaly_detection_flags_synthetic_dip() -> None:
    panel = merge_daily_panel(_synthetic_signals(), _synthetic_ridership())
    flagged = detect_ridership_anomalies(panel, z_threshold=-2)
    dip_days = flagged[flagged["anomalous"]]["date"].dt.date
    assert any(pd.Timestamp("2025-04-10").date() <= day <= pd.Timestamp("2025-04-14").date() for day in dip_days)


def test_lag_correlation_structure() -> None:
    panel = merge_daily_panel(_spread_signals(), _overlapping_ridership())
    corr = signal_ridership_lag_correlation(panel)
    assert len(corr) >= 8
    assert set(corr["lag_days"]).issubset(set(range(-5, 6)))
    assert corr["correlation"].between(-1, 1).all()
    assert 0 in set(corr["lag_days"])


def test_forecast_returns_metrics_and_horizon() -> None:
    panel = merge_daily_panel(_synthetic_signals(), _synthetic_ridership(300))
    result = ridge_forecast(panel, horizon=7)
    assert "error" not in result
    assert result["metrics"]["mae"] > 0
    assert len(result["forecast"]) == 7
    assert result["metrics"]["mape_pct"] < 60


def test_ridership_loader_parses_gov_csv(tmp_path) -> None:
    path = tmp_path / "ridership.csv"
    path.write_text(
        "date,rail_lrt_kj,rail_mrt_kajang\n2025-01-01,200000,150000\n2025-01-02,190000,140000\n",
        encoding="utf-8",
    )
    frame = load_ridership_headline(path)
    assert len(frame) == 2
    assert frame["rail_lrt_kj"].dtype in (np.float64, np.int64)


def test_delay_disruption_counts_rolling_window() -> None:
    signals = _spread_signals(days=10, every=1)
    trend = delay_disruption_counts(signals, rolling=3)
    assert len(trend) == 10
    assert int(trend["posts"].sum()) == 10
    assert trend["rolling_3d"].iloc[-1] > 0
    assert "rolling_3d" in trend.columns


def test_trend_split_reports_growth() -> None:
    signals = _spread_signals(days=6, every=1)
    split = trend_split(signals, split="2026-08-03")
    assert split["early_daily"] == 1.0
    assert split["late_daily"] == 1.0
    assert split["change_pct"] == 0.0
    assert split["total_posts"] == 6


def test_phrase_mentions_counts_by_category() -> None:
    signals = pd.DataFrame(
        [
            {"text": "lrt sesak gila masa shah alam crowd", "category": "crowding", "observed_at": "2026-08-01T00:00:00+00:00"},
            {"text": "naik lrt3 malam ni", "category": "other", "observed_at": "2026-08-02T00:00:00+00:00"},
            {"text": "cuaca panas hari ini", "category": "other", "observed_at": "2026-08-03T00:00:00+00:00"},
        ]
    )
    mentions = phrase_mentions(signals, ["shah ala", "lrt3"])
    assert mentions.set_index("category")["posts"].to_dict() == {"crowding": 1, "other": 1}
    assert phrase_mentions(signals, ["monorail"]).empty