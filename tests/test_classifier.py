from pathlib import Path

from src.nlp.classifier import classify_text
from src.processing.station_mapping import load_station_mapping


DATA_PATH = Path(__file__).parents[1] / "data" / "external" / "kelana_jaya_stations.csv"


def test_public_report_gets_official_station_id() -> None:
    mapping = load_station_mapping(DATA_PATH)
    signal = classify_text("LRT KJ14 sangat sesak", station_mapping=mapping)
    assert signal.category.value == "crowding"
    assert signal.station == "KJ14"


def test_lrt_problem_is_disruption() -> None:
    signal = classify_text("LRT Kelana Jaya line ada problem lagi hari ni", station_mapping=None)
    assert signal.category.value == "disruption"