from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Sequence

from .models import PublicSignal, SignalCategory


class SignalRepository:
    def __init__(self, database_path: str = "data/lrt_monitor.db") -> None:
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _initialize(self) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute("""
                CREATE TABLE IF NOT EXISTS public_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    text TEXT NOT NULL,
                    category TEXT NOT NULL,
                    station TEXT,
                    observed_at TEXT NOT NULL,
                    source TEXT NOT NULL,
                    independent_author INTEGER NOT NULL,
                    author_id TEXT
                )
            """)
            columns = {row[1] for row in connection.execute("PRAGMA table_info(public_signals)")}
            if "author_id" not in columns:
                connection.execute("ALTER TABLE public_signals ADD COLUMN author_id TEXT")

    def add_signal(self, signal: PublicSignal) -> None:
        with sqlite3.connect(self.database_path) as connection:
            connection.execute(
                "INSERT INTO public_signals(text, category, station, observed_at, source, independent_author, author_id) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (signal.text, signal.category.value, signal.station, signal.observed_at.isoformat(), signal.source, int(signal.independent_author), signal.author_id),
            )

    def recent_signals(self, limit: int = 50) -> list[dict[str, object]]:
        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(
                "SELECT text, category, station, observed_at, source, independent_author, author_id FROM public_signals ORDER BY observed_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    def all_signals(self, limit: int | None = None) -> list[dict[str, object]]:
        """All stored signals, oldest first. Optional row cap for large stores."""
        with sqlite3.connect(self.database_path) as connection:
            connection.row_factory = sqlite3.Row
            if limit is None:
                rows = connection.execute(
                    "SELECT text, category, station, observed_at, source, independent_author, author_id FROM public_signals ORDER BY observed_at ASC"
                ).fetchall()
            else:
                rows = connection.execute(
                    "SELECT text, category, station, observed_at, source, independent_author, author_id FROM public_signals ORDER BY observed_at ASC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [dict(row) for row in rows]

    def recent_signals_typed(self, limit: int = 50) -> list[PublicSignal]:
        rows = self.recent_signals(limit)
        return [
            PublicSignal(
                text=str(row["text"]),
                category=SignalCategory(str(row["category"])),
                station=str(row["station"]) if row["station"] else None,
                observed_at=datetime.fromisoformat(str(row["observed_at"])),
                source=str(row["source"]),
                independent_author=bool(row["independent_author"]),
                author_id=str(row["author_id"]) if row["author_id"] else None,
            )
            for row in rows
        ]
