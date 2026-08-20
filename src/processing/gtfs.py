from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile

import pandas as pd


GTFS_TABLES = ("routes", "trips", "stops", "stop_times")


def load_gtfs_tables(zip_path: str | Path) -> dict[str, pd.DataFrame]:
    """Load the GTFS tables needed for route-to-station mapping."""
    tables: dict[str, pd.DataFrame] = {}
    with ZipFile(zip_path) as archive:
        available = set(archive.namelist())
        for table in GTFS_TABLES:
            filename = f"{table}.txt"
            if filename not in available:
                raise ValueError(f"GTFS feed is missing {filename}")
            with archive.open(filename) as stream:
                tables[table] = pd.read_csv(stream, dtype=str)
    return tables


def route_ids_matching(routes: pd.DataFrame, phrase: str = "kelana jaya") -> set[str]:
    """Find route IDs using the official route short or long name."""
    searchable = routes[["route_id", "route_short_name", "route_long_name"]].fillna("")
    matched = searchable.apply(
        lambda row: phrase.casefold() in f"{row['route_short_name']} {row['route_long_name']}".casefold(),
        axis=1,
    )
    return set(searchable.loc[matched, "route_id"])


def stations_for_routes(tables: dict[str, pd.DataFrame], route_ids: set[str]) -> pd.DataFrame:
    """Map selected route IDs to their ordered, unique stops."""
    trips = tables["trips"]
    stop_times = tables["stop_times"]
    stops = tables["stops"]
    selected_trip_ids = set(trips.loc[trips["route_id"].isin(route_ids), "trip_id"])
    selected_times = stop_times[stop_times["trip_id"].isin(selected_trip_ids)].copy()
    selected_times["stop_sequence"] = pd.to_numeric(selected_times["stop_sequence"], errors="coerce")
    mapped = selected_times.merge(stops, on="stop_id", how="inner")
    return (
        mapped.sort_values(["stop_sequence", "stop_id"])[["stop_id", "stop_name"]]
        .drop_duplicates("stop_id")
        .reset_index(drop=True)
    )