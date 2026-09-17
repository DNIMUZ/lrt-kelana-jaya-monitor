from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests

from ..models import PublicSignal, SignalCategory
from ..storage import SignalRepository

SIGNALS_TABLE = "signals"
SIGNALS_DDL = """
create table public.signals (
    id bigint generated always as identity primary key,
    dedupe_key text unique not null,
    text text not null,
    category text not null,
    station text,
    author_id text,
    observed_at timestamptz not null,
    created_at timestamptz not null default now()
);

alter table public.signals enable row level security;

-- Read/write only for the service-role (server-side) key. The anon key gets nothing.
create policy "service role full access"
on public.signals
for all
to authenticated, service_role
using (true)
with check (true);
"""


def supabase_creds() -> dict[str, str] | None:
    """Read Supabase connection details from the environment / .env file."""
    url = os.getenv("SUPABASE_URL", "").strip().rstrip("/")
    key = os.getenv("SUPABASE_KEY", "").strip()
    if not (url and key):
        return None
    return {"url": url, "key": key}


def dedupe_key(author_id: str | None, text: str) -> str:
    """Stable fingerprint of a posting, case-insensitive, safe for Postgres unique."""
    raw = f"{author_id or ''}|{text}".lower()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def rows_from_signals(signals: pd.DataFrame) -> list[dict[str, Any]]:
    """Map the analysis DataFrame to PostgREST upsert rows."""
    rows: list[dict[str, Any]] = []
    for _, signal in signals.iterrows():
        text = str(signal.get("text", ""))
        author_id = signal.get("author_id")
        rows.append(
            {
                "dedupe_key": dedupe_key(str(author_id) if author_id else None, text),
                "text": text,
                "category": str(signal.get("category")),
                "station": signal.get("station") or None,
                "author_id": str(author_id) if author_id else None,
                "observed_at": pd.Timestamp(signal.get("observed_at")).isoformat(),
            }
        )
    return rows


def rows_to_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert PostgREST rows back into the standard signal DataFrame."""
    return pd.DataFrame(
        [
            {
                "text": row.get("text") or "",
                "category": row.get("category") or "other",
                "station": row.get("station") or None,
                "author_id": row.get("author_id") or None,
                "observed_at": row.get("observed_at"),
            }
            for row in rows
        ],
        columns=["text", "category", "station", "author_id", "observed_at"],
    )


def push_signals(signals: pd.DataFrame, chunk_size: int = 400) -> int:
    """Upsert all signal rows into Supabase (idempotent via dedupe_key). Returns rows pushed."""
    creds = supabase_creds()
    if not creds:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY not set. Add them to .env")
    rows = rows_from_signals(signals)
    pushed = 0
    for start in range(0, len(rows), chunk_size):
        batch = rows[start : start + chunk_size]
        response = requests.post(
            f"{creds['url']}/rest/v1/{SIGNALS_TABLE}",
            params={"on_conflict": "dedupe_key"},
            headers={
                "apikey": creds["key"],
                "Authorization": f"Bearer {creds['key']}",
                "Content-Type": "application/json",
                "Prefer": "resolution=merge-duplicates,count=exact",
            },
            json=batch,
            timeout=60,
        )
        response.raise_for_status()
        pushed += len(batch)
    return pushed


def fetch_signals() -> pd.DataFrame:
    """Download every signal from Supabase, oldest first."""
    creds = supabase_creds()
    if not creds:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY not set. Add them to .env")
    url = f"{creds['url']}/rest/v1/{SIGNALS_TABLE}?select=*&order=observed_at.asc"
    rows: list[dict[str, Any]] = []
    while url:
        response = requests.get(
            url,
            headers={
                "apikey": creds["key"],
                "Authorization": f"Bearer {creds['key']}",
                "Accept": "application/json",
            },
            timeout=60,
        )
        response.raise_for_status()
        chunk = response.json()
        rows.extend(chunk)
        url = None
        if len(chunk) == 1000:
            last = str(chunk[-1]["observed_at"])
            url = f"{creds['url']}/rest/v1/{SIGNALS_TABLE}?select=*&order=observed_at.asc&observed_at=gt.{last}"

    frame = rows_to_dataframe(rows)
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], errors="coerce", format="mixed", utc=True)
    return frame


def _naive_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def main() -> int:
    import sys

    from dotenv import load_dotenv

    load_dotenv()
    command = sys.argv[1] if len(sys.argv) > 1 else "push"
    creds = supabase_creds()
    if not creds:
        print("Set SUPABASE_URL and SUPABASE_KEY in .env first (see README).")
        return 1

    db = os.getenv("LRT_DATABASE_PATH", "data/lrt_monitor.db")
    if command == "init":
        print("Create table in the Supabase SQL editor, then run 'push':")
        print(SIGNALS_DDL)
        return 0

    sessions = SignalRepository(db)
    if command == "push":
        rows = [
            {
                "text": str(row["text"]),
                "category": str(row["category"]),
                "station": row["station"] or None,
                "author_id": row["author_id"] or None,
                "observed_at": pd.Timestamp(row["observed_at"]),
            }
            for row in sessions.all_signals()
        ]
        count = push_signals(pd.DataFrame(rows))
        print(f"Pushed {count} signal rows to Supabase ({SIGNALS_TABLE}).")
        return 0

    if command == "pull":
        signals = fetch_signals()
        if signals.empty:
            print("No rows in Supabase to pull.")
            return 1
        before = len(sessions.all_signals())
        for _, signal in signals.iterrows():
            sessions.add_signal(
                PublicSignal(
                    text=str(signal["text"]),
                    category=SignalCategory(str(signal["category"])),
                    station=signal["station"],
                    observed_at=_naive_utc(str(signal["observed_at"])),
                    source="supabase",
                    independent_author=True,
                    author_id=signal["author_id"],
                )
            )
        after = len(sessions.all_signals())
        print(f"Pulled {len(signals)} remote rows into {db} ({before} -> {after} unique locally).")
        return 0

    print(f"Unknown command: {command}. Use push | pull | init")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())