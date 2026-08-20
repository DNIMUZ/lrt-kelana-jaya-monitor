from __future__ import annotations

from collections.abc import Sequence

from .models import OfficialFact, PublicSignal, SignalCategory, StatusEstimate, StatusLevel
from .processing.signal_aggregation import deduplicate_signals


def estimate_status(
    expected_demand: float,
    signals: Sequence[PublicSignal],
    official_fact: OfficialFact | None = None,
) -> StatusEstimate:
    """Produce an explainable estimate; inputs are normalized to 0..1 where needed."""
    expected_demand = max(0.0, min(1.0, expected_demand))
    signals = deduplicate_signals(signals)
    crowding = sum(signal.category == SignalCategory.CROWDING for signal in signals)
    delays = sum(signal.category == SignalCategory.DELAY for signal in signals)
    disruptions = sum(signal.category == SignalCategory.DISRUPTION for signal in signals)
    independent = sum(
        signal.independent_author and signal.category in {
            SignalCategory.CROWDING,
            SignalCategory.DELAY,
            SignalCategory.DISRUPTION,
        }
        for signal in signals
    )

    rationale = [f"Historical demand signal: {expected_demand:.0%}"]
    if official_fact and (not official_fact.service_operating or official_fact.disruption_message):
        message = official_fact.disruption_message or "Official service interruption reported"
        return StatusEstimate(StatusLevel.DISRUPTION, 1.0, 0.98, [f"Official fact: {message}"])

    crowding_signal = min(1.0, crowding / 10) * 0.55
    delay_signal = min(1.0, delays / 5) * 0.10
    independent_bonus = min(0.15, independent * 0.01)
    score = min(1.0, expected_demand * 0.35 + crowding_signal + delay_signal + independent_bonus)
    if score >= 0.75:
        level = StatusLevel.VERY_BUSY
    elif score >= 0.50:
        level = StatusLevel.BUSY
    elif score >= 0.25:
        level = StatusLevel.MODERATE
    else:
        level = StatusLevel.NORMAL

    rationale.append(f"{crowding} crowding, {delays} delay, and {disruptions} disruption signals")
    confidence = min(0.95, 0.55 + min(0.30, independent * 0.02) + (0.10 if official_fact else 0))
    return StatusEstimate(level, round(score, 3), round(confidence, 3), rationale)
