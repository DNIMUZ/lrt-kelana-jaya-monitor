from __future__ import annotations

from pathlib import Path
import re

import pandas as pd

REQUIRED_COLUMNS = {"stop_id", "stop_name"}


def load_station_mapping(path: str | Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype=str).fillna("")
    missing = REQUIRED_COLUMNS.difference(frame.columns)
    if missing:
        raise ValueError(f"Missing station columns: {sorted(missing)}")
    if frame["stop_id"].duplicated().any():
        raise ValueError("stop_id values must be unique")
    return frame[["stop_id", "stop_name"]].drop_duplicates().reset_index(drop=True)


def station_names(frame: pd.DataFrame) -> list[str]:
    return frame["stop_name"].sort_values().tolist()


def normalize_station_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", text.casefold())).strip()


def find_station_mentions(text: str, frame: pd.DataFrame) -> list[str]:
    """Return official stop IDs mentioned by a public report, in feed order."""
    normalized_text = normalize_station_text(text)
    matches: list[str] = []
    for row in frame.itertuples(index=False):
        stop_id = normalize_station_text(row.stop_id)
        stop_name = normalize_station_text(row.stop_name)
        aliases = {stop_id, stop_id.replace("kj", "kj "), stop_name}
        if " - " in row.stop_name:
            aliases.add(normalize_station_text(row.stop_name.split(" - ", 1)[0]))
        if any(
            re.search(rf"(?<![a-z0-9]){re.escape(alias)}(?![a-z0-9])", normalized_text)
            for alias in aliases
            if alias
        ):
            matches.append(row.stop_id)
    return matches
