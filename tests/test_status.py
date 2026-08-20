from src.models import OfficialFact, PublicSignal, SignalCategory, StatusLevel
from src.status import estimate_status


def test_official_disruption_overrides_public_signal() -> None:
    estimate = estimate_status(
        0.2,
        [PublicSignal("normal journey", SignalCategory.NORMAL)],
        OfficialFact(service_operating=False, disruption_message="Service interruption"),
    )
    assert estimate.level == StatusLevel.DISRUPTION
    assert estimate.confidence == 0.98


def test_independent_crowding_reports_raise_status() -> None:
    signals = [PublicSignal(f"packed train {index}", SignalCategory.CROWDING) for index in range(12)]
    estimate = estimate_status(0.8, signals)
    assert estimate.level == StatusLevel.VERY_BUSY
    assert estimate.crowding_score >= 0.75
