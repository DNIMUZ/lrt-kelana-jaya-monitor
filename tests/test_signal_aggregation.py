from datetime import datetime, timedelta, timezone

import pytest

from src.models import PublicSignal, SignalCategory
from src.processing.signal_aggregation import aggregate_signals, deduplicate_signals


def test_aggregation_counts_station_categories_and_authors() -> None:
    end = datetime(2026, 8, 20, 12, 0, tzinfo=timezone.utc)
    signals = [
        PublicSignal("packed", SignalCategory.CROWDING, "KJ14", end - timedelta(minutes=3), author_id="a"),
        PublicSignal("packed", SignalCategory.CROWDING, "KJ14", end - timedelta(minutes=4), author_id="b"),
        PublicSignal("delay", SignalCategory.DELAY, "KJ14", end - timedelta(minutes=5), author_id="a"),
        PublicSignal("old", SignalCategory.CROWDING, "KJ14", end - timedelta(minutes=16), author_id="c"),
    ]

    summary = aggregate_signals(signals, window_end=end)[0]

    assert summary.station == "KJ14"
    assert summary.total_observations == 3
    assert summary.independent_observations == 3
    assert summary.unique_authors == 2
    assert summary.crowding_reports == 2
    assert summary.delay_reports == 1


def test_aggregation_rejects_non_positive_windows() -> None:
    with pytest.raises(ValueError):
        aggregate_signals([], window_minutes=0)


def test_deduplication_keeps_anonymous_observations_but_limits_authors() -> None:
    signals = [
        PublicSignal("one", SignalCategory.CROWDING, "KJ14", author_id="a"),
        PublicSignal("same author repost", SignalCategory.CROWDING, "KJ14", author_id="a"),
        PublicSignal("anonymous", SignalCategory.CROWDING, "KJ14"),
    ]
    deduplicated = deduplicate_signals(signals)
    assert len(deduplicated) == 2