from pathlib import Path
from zipfile import ZipFile

from src.processing.gtfs import load_gtfs_tables, route_ids_matching, stations_for_routes


def test_gtfs_route_to_station_mapping(tmp_path: Path) -> None:
    feed = tmp_path / "feed.zip"
    tables = {
        "routes": "route_id,route_short_name,route_long_name\nr1,KJ,LRT Kelana Jaya Line\nr2,SB,Sunway Bus\n",
        "trips": "route_id,service_id,trip_id\nr1,weekday,t1\nr2,weekday,t2\n",
        "stops": "stop_id,stop_name\ns1,Kelana Jaya\ns2,Pasar Seni\n",
        "stop_times": "trip_id,arrival_time,departure_time,stop_id,stop_sequence\nt1,07:00:00,07:01:00,s1,1\nt1,07:10:00,07:11:00,s2,2\nt2,07:00:00,07:01:00,s2,1\n",
    }
    with ZipFile(feed, "w") as archive:
        for name, content in tables.items():
            archive.writestr(f"{name}.txt", content)

    loaded = load_gtfs_tables(feed)
    route_ids = route_ids_matching(loaded["routes"])
    stations = stations_for_routes(loaded, route_ids)

    assert route_ids == {"r1"}
    assert stations["stop_name"].tolist() == ["Kelana Jaya", "Pasar Seni"]