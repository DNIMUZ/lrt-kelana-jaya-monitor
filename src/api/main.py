from __future__ import annotations

import os
from dataclasses import asdict
from datetime import datetime
from typing import Dict

from fastapi import FastAPI, Query

from ..models import OfficialFact, PublicSignal, SignalCategory
from ..processing.signal_aggregation import aggregate_signals
from ..status import estimate_status
from ..storage import SignalRepository

app = FastAPI(title="LRT Kelana Jaya Monitor", version="0.1.0")
repository = SignalRepository(os.getenv("LRT_DATABASE_PATH", "data/lrt_monitor.db"))


def _signals_from_rows(rows: list[dict[str, object]]) -> list[PublicSignal]:
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


@app.get("/health")
def health() -> Dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/status")
def current_status(expected_demand: float = Query(0.5, ge=0, le=1)) -> Dict[str, object]:
    rows = repository.recent_signals()
    signals = _signals_from_rows(rows)
    estimate = estimate_status(expected_demand, signals, OfficialFact())
    return {"data_classification": "ESTIMATION", **asdict(estimate)}


@app.get("/api/v1/signals")
def recent_signals(limit: int = Query(20, ge=1, le=100)) -> Dict[str, object]:
    return {"data_classification": "SIGNAL", "items": repository.recent_signals(limit)}


@app.get("/api/v1/signals/summary")
def signal_summary(window_minutes: int = Query(15, ge=1, le=1440)) -> Dict[str, object]:
    signals = _signals_from_rows(repository.recent_signals(500))
    summaries = aggregate_signals(signals, window_minutes=window_minutes)
    return {
        "data_classification": "SIGNAL",
        "window_minutes": window_minutes,
        "items": [asdict(summary) for summary in summaries],
    }
