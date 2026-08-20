from __future__ import annotations

from collections.abc import Sequence

from ..models import PublicSignal, SignalCategory


def signal_counts(signals: Sequence[PublicSignal]) -> dict[str, int]:
    return {
        category.value: sum(signal.category == category for signal in signals)
        for category in SignalCategory
    }
