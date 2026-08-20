from __future__ import annotations

from collections.abc import Iterable
from typing import BinaryIO

import pandas as pd

from ..models import PublicSignal
from ..nlp.classifier import classify_text


def classify_public_posts(posts: Iterable[str], station_mapping: object = None) -> list[PublicSignal]:
    """Classify already lawfully collected public text without claiming verification."""
    return [classify_text(post, station_mapping=station_mapping) for post in posts]


def load_public_reports(upload: BinaryIO, station_mapping: object = None) -> list[PublicSignal]:
    """Load a user-provided CSV of public reports after basic schema validation."""
    frame = pd.read_csv(upload)
    required = {"text", "observed_at"}
    missing = required.difference(frame.columns)
    if missing:
        raise ValueError(f"Missing public report columns: {sorted(missing)}")
    observed_at = pd.to_datetime(frame["observed_at"], errors="raise", utc=True)
    signals: list[PublicSignal] = []
    for index, row in frame.iterrows():
        signal = classify_text(
            str(row["text"]),
            station=str(row["station"]) if "station" in frame.columns and pd.notna(row["station"]) else None,
            station_mapping=station_mapping,
        )
        signals.append(
            PublicSignal(
                text=signal.text,
                category=signal.category,
                station=signal.station,
                observed_at=observed_at.iloc[index].to_pydatetime(),
                source=str(row["source"]) if "source" in frame.columns and pd.notna(row["source"]) else "uploaded_public_report",
                author_id=str(row["author_id"]) if "author_id" in frame.columns and pd.notna(row["author_id"]) else None,
            )
        )
    return signals
