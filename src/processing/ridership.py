from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = {"service_date", "station", "hour", "passenger_count"}


def load_ridership(path: str | Path | object) -> pd.DataFrame:
    frame = pd.read_csv(path)
    missing = REQUIRED_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"Missing ridership columns: {sorted(missing)}")
    frame = frame.copy()
    frame["service_date"] = pd.to_datetime(frame["service_date"], errors="raise")
    frame["hour"] = pd.to_numeric(frame["hour"], errors="raise").astype(int)
    frame["passenger_count"] = pd.to_numeric(frame["passenger_count"], errors="raise")
    if not frame["hour"].between(0, 23).all():
        raise ValueError("hour must be between 0 and 23")
    if (frame["passenger_count"] < 0).any():
        raise ValueError("passenger_count cannot be negative")
    return frame.sort_values(["station", "service_date", "hour"]).reset_index(drop=True)


def hourly_baseline(frame: pd.DataFrame) -> pd.DataFrame:
    required = REQUIRED_COLUMNS.difference(frame.columns)
    if required:
        raise ValueError(f"Missing ridership columns: {sorted(required)}")
    return (
        frame.groupby(["station", "hour"], as_index=False)["passenger_count"]
        .agg(expected_passenger_count="mean", observations="count")
        .sort_values(["station", "hour"])
        .reset_index(drop=True)
    )


def demand_index(passenger_count: float, expected_passenger_count: float) -> float:
    if expected_passenger_count <= 0:
        raise ValueError("expected_passenger_count must be positive")
    return round(max(0.0, passenger_count / expected_passenger_count), 3)


def historical_demand_signal(frame: pd.DataFrame, station: str, hour: int) -> float:
    """Normalize a station-hour baseline against that station's observed peak."""
    baseline = hourly_baseline(frame)
    selected = baseline[(baseline["station"] == station) & (baseline["hour"] == hour)]
    station_values = baseline.loc[baseline["station"] == station, "expected_passenger_count"]
    if selected.empty or station_values.empty or station_values.max() <= 0:
        return 0.5
    value = float(selected.iloc[0]["expected_passenger_count"])
    return round(max(0.0, min(1.0, value / float(station_values.max()))), 3)
