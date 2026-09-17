from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Sequence

import pandas as pd

from ..storage import SignalRepository

MALAYSIA_OFFSET = timedelta(hours=8)
RIDERSHIP_COLUMNS = (
    "rail_lrt_kj",
    "rail_lrt_ampang",
    "rail_mrt_kajang",
    "rail_mrt_pjy",
    "rail_lrt_shah_alam",
    "rail_monorail",
    "rail_komuter",
    "rail_ets",
)


def load_signals_dataframe(
    database_path: str | Path = "data/lrt_monitor.db",
    limit: int | None = None,
) -> pd.DataFrame:
    """Load stored Threads/public signals into a DataFrame with UTC timestamps."""
    rows = SignalRepository(database_path).all_signals(limit)
    frames = [
        {
            "text": row["text"],
            "category": row["category"],
            "station": row["station"] or None,
            "author_id": row["author_id"] or None,
            "observed_at": pd.Timestamp(row["observed_at"]),
        }
        for row in rows
    ]
    return pd.DataFrame(frames, columns=["text", "category", "station", "author_id", "observed_at"])


def load_ridership_headline(path: str | Path = "data/ridership_headline.csv") -> pd.DataFrame:
    """Parse the data.gov.my ridership headline CSV into a numeric daily panel."""
    frame = pd.read_csv(path, dtype=str)
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce", format="mixed")
    frame = frame.dropna(subset=["date"]).copy()
    for column in RIDERSHIP_COLUMNS:
        if column in frame.columns:
            frame[column] = pd.to_numeric(frame[column], errors="coerce")
    return frame.sort_values("date").reset_index(drop=True)


def malaysia_date(signals: pd.DataFrame) -> pd.Series:
    """Bucket each signal into its Malaysian (UTC+8) calendar date."""
    times = pd.to_datetime(signals["observed_at"], errors="coerce", format="mixed")
    if times.isna().all():
        return times
    if getattr(times.dt, "tz", None) is None:
        times = times.dt.tz_localize("UTC")
    else:
        times = times.dt.tz_convert("UTC")
    return (times + MALAYSIA_OFFSET).dt.normalize().dt.tz_localize(None)


def daily_signal_counts(signals: pd.DataFrame) -> pd.DataFrame:
    """Daily counts of signals per category plus unique authors (MY dates)."""
    if signals.empty:
        return pd.DataFrame(
            columns=[
                "date",
                "total",
                "unique_authors",
                "normal",
                "crowding",
                "delay",
                "disruption",
                "other",
            ]
        )
    work = signals.assign(date=malaysia_date(signals))
    pivoted = work.pivot_table(index="date", columns="category", values="text", aggfunc="count", fill_value=0)
    authors = work.drop_duplicates(subset=["date", "author_id"]).groupby("date")["author_id"].count()
    result = pivoted.rename_axis(columns=None).reset_index()
    result["total"] = result[[column for column in result.columns if column != "date"]].sum(axis=1)
    result["unique_authors"] = authors.reindex(result["date"]).fillna(0).astype(int)
    for category in ("normal", "crowding", "delay", "disruption", "other"):
        if category not in result.columns:
            result[category] = 0
    return result[["date", "total", "unique_authors", "normal", "crowding", "delay", "disruption", "other"]].sort_values("date")


def merge_daily_panel(
    signals: pd.DataFrame,
    ridership: pd.DataFrame,
    ridership_column: str = "rail_lrt_kj",
) -> pd.DataFrame:
    """Outer-join daily signal counts with the government ridership series."""
    counts = daily_signal_counts(signals)
    ridership_key = ridership[["date", ridership_column]].rename(columns={ridership_column: "ridership"})
    panel = ridership_key.merge(counts, on="date", how="outer").sort_values("date").reset_index(drop=True)
    panel["date"] = pd.to_datetime(panel["date"])
    for column in ("total", "unique_authors", "normal", "crowding", "delay", "disruption", "other"):
        panel[column] = pd.to_numeric(panel[column], errors="coerce").fillna(0).astype(int)
    panel["ridership"] = pd.to_numeric(panel["ridership"], errors="coerce")
    panel["weekday"] = panel["date"].dt.day_name()
    panel["weekday_code"] = panel["date"].dt.dayofweek
    panel["month"] = panel["date"].dt.month
    panel["year"] = panel["date"].dt.year
    panel["is_weekend"] = panel["weekday_code"].ge(5).astype(int)
    return panel


def signals_since_signals_frame(paths: Sequence[str] | None = None) -> pd.DataFrame:
    """Convenience: assemble signal frame from one or more processed CSV/JSON files."""
    frames: list[pd.DataFrame] = []
    for path in paths or ():
        frame = pd.read_csv(path)
        frame["observed_at"] = pd.to_datetime(frame["observed_at"], errors="coerce", format="mixed")
        frame["station"] = frame["station"].fillna("")
        frames.append(frame)
    if not frames:
        return pd.DataFrame(columns=["text", "category", "station", "author_id", "observed_at"])
    return pd.concat(frames, ignore_index=True)