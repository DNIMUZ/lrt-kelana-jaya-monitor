from __future__ import annotations

from ..models import PublicSignal, SignalCategory
from ..processing.station_mapping import find_station_mentions

_KEYWORDS = {
    SignalCategory.DISRUPTION: ("breakdown", "rosak", "ditutup", "shutdown", "interruption", "problem", "masalah", "bermasalah", "gangguan"),
    SignalCategory.DELAY: ("delay", "lambat", "waiting", "tunggu", "slow"),
    SignalCategory.CROWDING: ("crowded", "sesak", "packed", "queue", "beratur", "busy"),
}


def classify_text(text: str, station: str | None = None, station_mapping: object = None) -> PublicSignal:
    lowered = text.casefold()
    if station is None and station_mapping is not None:
        mentions = find_station_mentions(text, station_mapping)
        station = mentions[0] if mentions else None
    for category, keywords in _KEYWORDS.items():
        if any(keyword in lowered for keyword in keywords):
            return PublicSignal(text=text, category=category, station=station)
    return PublicSignal(text=text, category=SignalCategory.OTHER, station=station)
