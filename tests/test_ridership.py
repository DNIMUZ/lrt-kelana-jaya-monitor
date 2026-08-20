from pathlib import Path

import pytest

from src.processing.ridership import demand_index, historical_demand_signal, hourly_baseline, load_ridership


DATA_PATH = Path(__file__).parents[1] / "data" / "external" / "demo_ridership.csv"


def test_demo_ridership_creates_station_hour_baseline() -> None:
    frame = load_ridership(DATA_PATH)
    baseline = hourly_baseline(frame)
    assert len(frame) == 18
    assert len(baseline) == 6
    pasar_seni_8 = baseline[(baseline.station == "Pasar Seni") & (baseline.hour == 8)].iloc[0]
    assert pasar_seni_8.expected_passenger_count == pytest.approx(6116.67, abs=0.01)
    assert pasar_seni_8.observations == 3


def test_demand_index_compares_current_to_expected() -> None:
    assert demand_index(750, 500) == 1.5
    with pytest.raises(ValueError):
        demand_index(100, 0)


def test_historical_demand_signal_uses_station_peak() -> None:
    frame = load_ridership(DATA_PATH)
    assert historical_demand_signal(frame, "Pasar Seni", 8) == 1.0
    assert historical_demand_signal(frame, "Pasar Seni", 7) == pytest.approx(0.687, abs=0.001)
