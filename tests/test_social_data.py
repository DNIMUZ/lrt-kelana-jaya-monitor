from io import StringIO
from pathlib import Path

from src.collectors.social_data import load_public_reports
from src.models import SignalCategory
from src.processing.station_mapping import load_station_mapping


STATIONS = Path(__file__).parents[1] / "data" / "external" / "kelana_jaya_stations.csv"


def test_load_public_reports_classifies_and_maps_station() -> None:
    upload = StringIO(
        "text,observed_at,author_id,source\n"
        "LRT KJ14 sangat sesak,2026-08-20T12:00:00Z,user-1,public\n"
    )
    signals = load_public_reports(upload, load_station_mapping(STATIONS))
    assert len(signals) == 1
    assert signals[0].category == SignalCategory.CROWDING
    assert signals[0].station == "KJ14"
    assert signals[0].author_id == "user-1"
