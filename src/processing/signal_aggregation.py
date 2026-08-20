from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from ..models import PublicSignal, SignalCategory


@dataclass(frozen=True)
class StationSignalSummary:
    station: str
    total_observations: int
    independent_observations: int
    unique_authors: int
    crowding_reports: int
    delay_reports: int
    disruption_reports: int


def deduplicate_signals(signals: Sequence[PublicSignal]) -> list[PublicSignal]:
    """Keep one signal per identified author, station, and category."""
    seen: set[tuple[str, str, SignalCategory]] = set()
    result: list[PublicSignal] = []
    for signal in signals:
        if not signal.author_id:
            result.append(signal)
            continue
        key = (signal.author_id, signal.station or "unknown", signal.category)
        if key not in seen:
            seen.add(key)
            result.append(signal)
    return result


def aggregate_signals(
    signals: Sequence[PublicSignal],
    window_minutes: int = 15,
    window_end: datetime | None = None,
) -> list[StationSignalSummary]:
    """Summarize public signals by station inside a trailing time window."""
    if window_minutes <= 0:
        raise ValueError("window_minutes must be positive")
    end = window_end or datetime.now(timezone.utc)
    start = end - timedelta(minutes=window_minutes)
    recent = [signal for signal in signals if start <= signal.observed_at <= end]
    grouped: dict[str, list[PublicSignal]] = {}
    for signal in recent:
        grouped.setdefault(signal.station or "unknown", []).append(signal)

    summaries: list[StationSignalSummary] = []
    for station, station_signals in sorted(grouped.items()):
        author_ids = {
            author_id
            for signal in station_signals
            for author_id in [getattr(signal, "author_id", None)]
            if author_id
        }
        summaries.append(
            StationSignalSummary(
                station=station,
                total_observations=len(station_signals),
                independent_observations=sum(signal.independent_author for signal in station_signals),
                unique_authors=len(author_ids),
                crowding_reports=sum(signal.category == SignalCategory.CROWDING for signal in station_signals),
                delay_reports=sum(signal.category == SignalCategory.DELAY for signal in station_signals),
                disruption_reports=sum(signal.category == SignalCategory.DISRUPTION for signal in station_signals),
            )
        )
    return summaries


def summaries_as_dicts(summaries: Sequence[StationSignalSummary]) -> list[dict[str, object]]:
    return [asdict(summary) for summary in summaries]