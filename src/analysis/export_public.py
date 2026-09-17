from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from ..storage import SignalRepository
from .merged import daily_signal_counts, malaysia_date

PUBLIC_DIR = Path(__file__).resolve().parents[2] / "data" / "published"
PRIVATE_COLUMNS = ("text", "author_id")


def export_public_artifacts(
    signals: pd.DataFrame,
    output_dir: str | Path = PUBLIC_DIR,
) -> dict[str, Path]:
    """Write privacy-safe aggregate artifacts (no post text, no author IDs).

    Returns a mapping of artifact name -> path.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    daily = daily_signal_counts(signals).assign(date=lambda f: f["date"].dt.normalize())
    daily.to_csv(output_dir / "signals_daily.csv", index=False)

    incident = signals[signals["category"].isin(["crowding", "delay", "disruption"])].copy()
    incident["date_malaysia"] = malaysia_date(incident)
    minimal = incident[["date_malaysia", "category", "station"]].rename(columns={"date_malaysia": "date"})
    minimal.to_csv(output_dir / "incidents_posts.csv", index=False)

    stations = (
        signals[signals["station"].notna() & signals["station"].ne("")]
        .groupby("station")
        .size()
        .rename("posts")
        .reset_index()
        .sort_values("posts", ascending=False)
    )
    stations.to_csv(output_dir / "stations_mentions.csv", index=False)

    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "signals_total": int(len(signals)),
        "signals_unique_postings": int(daily["total"].sum()),
        "date_range": [daily["date"].min().isoformat(), daily["date"].max().isoformat()],
        "categories": {cat: int(signals["category"].eq(cat).sum()) for cat in ("crowding", "delay", "disruption", "other", "normal")},
        "note": "Aggregates only. Post text and author identities are excluded and kept private.",
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    return {
        "signals_daily": output_dir / "signals_daily.csv",
        "incidents_posts": output_dir / "incidents_posts.csv",
        "stations_mentions": output_dir / "stations_mentions.csv",
        "summary": output_dir / "summary.json",
    }


def load_public_signals(public_dir: str | Path = PUBLIC_DIR) -> pd.DataFrame:
    """Reconstruct the analysis frame from public artifacts (text/author empty)."""
    public_dir = Path(public_dir)
    incidents = pd.read_csv(public_dir / "incidents_posts.csv", dtype=str)
    incidents["observed_at"] = pd.to_datetime(incidents["date"], errors="coerce", format="mixed")
    incidents["text"] = ""
    incidents["author_id"] = None
    incidents["date"] = pd.to_datetime(incidents["date"], errors="coerce")
    return incidents[["text", "category", "station", "author_id", "observed_at"]]


def load_public_daily_counts(public_dir: str | Path = PUBLIC_DIR) -> pd.DataFrame:
    public_dir = Path(public_dir)
    frame = pd.read_csv(public_dir / "signals_daily.csv")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    return frame


def summary_exists(public_dir: str | Path = PUBLIC_DIR) -> bool:
    return (Path(public_dir) / "summary.json").exists()


def main() -> int:
    import os

    from dotenv import load_dotenv

    load_dotenv()
    db = os.getenv("LRT_DATABASE_PATH", "data/lrt_monitor.db")
    repo = SignalRepository(db)
    signals = pd.DataFrame(
        [
            {
                "text": row["text"],
                "category": row["category"],
                "station": row["station"] or None,
                "author_id": row["author_id"] or None,
                "observed_at": pd.Timestamp(row["observed_at"]),
            }
            for row in repo.all_signals()
        ]
    )
    artifacts = export_public_artifacts(signals)
    for name, path in artifacts.items():
        print(f"{name}: {path}")
    print(json.dumps(json.loads((artifacts["summary"]).read_text(encoding="utf-8")), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())