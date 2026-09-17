from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.analysis.export_public import export_public_artifacts, load_public_daily_counts, load_public_signals
from src.analysis.insights import (
    WEEKDAY_ORDER,
    delay_disruption_counts,
    detect_ridership_anomalies,
    incident_hour_distribution,
    phrase_mentions,
    ridge_forecast,
    signal_ridership_lag_correlation,
    trend_split,
    weekday_seasonality,
)
from src.analysis.merged import daily_signal_counts, load_ridership_headline, merge_daily_panel
from src.analysis.supabase_sync import (
    _naive_utc,
    dedupe_key,
    push_signals,
    rows_from_signals,
    rows_to_dataframe,
)


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


def test_incident_hour_distribution_buckets_by_local_time() -> None:
    signals = pd.DataFrame(
        [
            {"text": "lrt sesak", "category": "crowding", "observed_at": "2026-08-01T22:50:00+00:00"},  # 06:50 MY
            {"text": "lrt delay", "category": "delay", "observed_at": "2026-08-01T02:00:00+00:00"},       # 10:00 MY
            {"text": "lrt rosak", "category": "disruption", "observed_at": "2026-08-02T12:00:00+00:00"},  # 20:00 MY
        ]
    )
    dist = incident_hour_distribution(signals)
    buckets = dist.set_index("window")["posts"].to_dict()
    assert buckets["Morning rush 6-9"] == 1
    assert buckets["Late morning 9-12"] == 1
    assert buckets["Night 19-24"] == 1


def test_public_export_strips_text_and_authors(tmp_path) -> None:
    signals = pd.concat(
        [
            _synthetic_signals(),
            pd.DataFrame(
                [
                    {
                        "text": "saya tulis rahsia ini",  # must never reach the public CSVs
                        "category": "disruption",
                        "station": "KJ9",
                        "author_id": "secretuser",
                        "observed_at": "2026-09-02T01:00:00+00:00",
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    artifacts = export_public_artifacts(signals, tmp_path)
    incidents = pd.read_csv(artifacts["incidents_posts"])
    assert "text" not in incidents.columns
    assert "author_id" not in incidents.columns
    assert "secret" not in "\n".join(incidents.astype(str).to_string().splitlines())
    daily = load_public_daily_counts(tmp_path)
    assert {"disruption", "crowding", "total"}.issubset(daily.columns)
    loaded = load_public_signals(tmp_path)
    assert len(loaded) == len(signals[signals["category"].isin(["crowding", "delay", "disruption"])])
    assert loaded["text"].eq("").all()
    assert loaded["author_id"].isna().all()


def test_dedupe_key_is_stable_and_case_insensitive() -> None:
    assert dedupe_key("UserA", "LRT SESAK") == dedupe_key("usera", "lrt sesak")
    assert dedupe_key("UserA", "LRT SESAK") != dedupe_key("UserA", "lrt sesak juga")
    assert len(dedupe_key(None, "text")) == 40


def test_rows_from_signals_dedupeable_and_roundtrips() -> None:
    signals = _synthetic_signals()
    rows = rows_from_signals(signals)
    assert len(rows) == len(signals)
    assert {col in rows[0] for col in ("dedupe_key", "text", "category", "station", "author_id", "observed_at")} == {True}
    keys = [row["dedupe_key"] for row in rows]
    assert len(keys) == len(set(keys))
    restored = rows_to_dataframe(rows)
    assert set(restored.columns) == {"text", "category", "station", "author_id", "observed_at"}
    assert restored["text"].tolist() == signals["text"].tolist()


def test_push_signals_batches_and_deduplicates(monkeypatch) -> None:
    captured: list[dict] = []
    import requests

    def fake_post(url, params=None, headers=None, json=None, timeout=None):
        assert params.get("on_conflict") == "dedupe_key"
        assert "signals" in url
        assert headers["Prefer"].startswith("resolution=merge-duplicates")
        captured.append({"url": url, "payload": json})
        return type("R", (), {"raise_for_status": lambda self: None})()

    monkeypatch.setattr(requests, "post", fake_post)
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "service-key")

    signals = pd.concat([_synthetic_signals(), _synthetic_signals()], ignore_index=True)
    pushed = push_signals(signals, chunk_size=100)
    assert pushed == len(signals)
    assert len(captured) == 1
    deduped = {row["dedupe_key"] for batch in captured for row in batch["payload"]}
    assert len(deduped) == 4  # not 8: same dedupe_key sent once thanks to dedupe_key identity


def test_naive_utc_handles_z_and_offset() -> None:
    assert _naive_utc("2026-09-01T00:30:00Z") == pd.Timestamp("2026-09-01T00:30:00").to_pydatetime()
    assert _naive_utc("2026-09-01T00:30:00+08:00") == pd.Timestamp("2026-08-31T16:30:00").to_pydatetime()