from pathlib import Path

from src.processing.station_mapping import find_station_mentions, load_station_mapping, station_names


DATA_PATH = Path(__file__).parents[1] / "data" / "external" / "kelana_jaya_stations.csv"


def test_official_station_mapping_contains_37_stations() -> None:
    mapping = load_station_mapping(DATA_PATH)
    assert len(mapping) == 37
    assert "PASAR SENI" in station_names(mapping)
    assert "KELANA JAYA" in station_names(mapping)


def test_station_mentions_normalize_ids_and_interchange_names() -> None:
    mapping = load_station_mapping(DATA_PATH)
    assert find_station_mentions("Crowded at KJ14 and KJ 24", mapping) == ["KJ14", "KJ24"]
    assert find_station_mentions("Waiting near KL Sentral", mapping) == ["KJ15"]
    assert find_station_mentions("At KJ1, not KJ10", mapping) == ["KJ1", "KJ10"]
