from __future__ import annotations

import hashlib
import os
import ssl
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

import pandas as pd

from ..models import PublicSignal, SignalCategory
from ..storage import SignalRepository

SIGNALS_TABLE = "signals"
SCHEMA_SQL = f"""
CREATE TABLE IF NOT EXISTS public.{SIGNALS_TABLE} (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    dedupe_key text NOT NULL UNIQUE,
    text text NOT NULL,
    category text NOT NULL,
    station text,
    author_id text,
    observed_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.{SIGNALS_TABLE} ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role full access" ON public.{SIGNALS_TABLE};
CREATE POLICY "service_role full access" ON public.{SIGNALS_TABLE}
    FOR ALL TO authenticated, service_role USING (true) WITH CHECK (true);
"""
UPSERT_PREFIX = (
    f"INSERT INTO public.{SIGNALS_TABLE} (dedupe_key, text, category, station, author_id, observed_at) VALUES "
)
UPSERT_CONFLICT = (
    "ON CONFLICT (dedupe_key) DO UPDATE SET "
    "text = EXCLUDED.text, category = EXCLUDED.category, station = EXCLUDED.station, "
    "author_id = EXCLUDED.author_id, observed_at = EXCLUDED.observed_at;"
)


def _require_ssl(parsed: Any) -> ssl.SSLContext | None:
    mode = "require"
    for item in (parsed.query or "").split("&"):
        if "=" in item:
            key, _, value = item.partition("=")
            if key == "sslmode":
                mode = value
    if mode == "disable":
        return None
    if mode in ("verify-full", "verify-ca"):
        return ssl.create_default_context()
    return ssl._create_unverified_context()


def _dsn() -> str:
    """Connection string from Streamlit secrets first, then .env (F1-style)."""
    try:
        import streamlit as st

        url = st.secrets.get("SUPABASE_DATABASE_URL")
        if url:
            return url.strip()
    except Exception:
        pass
    return os.getenv("SUPABASE_DATABASE_URL", "").strip()


def supabase_creds() -> dict[str, Any] | None:
    """Parse the Postgres connection URI into connect kwargs."""
    url = _dsn()
    if not url:
        return None
    parsed = urlparse(url)
    if not parsed.hostname:
        return None
    return {
        "host": parsed.hostname,
        "port": parsed.port or 5432,
        "user": unquote(parsed.username or "postgres"),
        "password": unquote(parsed.password or ""),
        "database": parsed.path.lstrip("/") or "postgres",
        "ssl": _require_ssl(parsed),
    }


def _connect():
    import pg8000

    creds = supabase_creds()
    if not creds:
        raise RuntimeError("SUPABASE_DATABASE_URL is not set. Add it to .env (see README).")
    kwargs = {key: creds[key] for key in ("host", "port", "user", "password", "database")}
    kwargs["timeout"] = 30
    if creds["ssl"]:
        try:
            return pg8000.connect(**kwargs, ssl_context=creds["ssl"])
        except pg8000.exceptions.InterfaceError:
            return pg8000.connect(**kwargs)
    return pg8000.connect(**kwargs)


def ensure_schema(connection) -> None:
    """Create table + row-level-security policy (idempotent)."""
    with connection.cursor() as cursor:
        cursor.execute(SCHEMA_SQL)
    connection.commit()


def dedupe_key(author_id: str | None, text: str) -> str:
    """Stable fingerprint of a posting, case-insensitive, safe for Postgres unique."""
    raw = f"{author_id or ''}|{text}".lower()
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _as_utc(value: Any) -> datetime:
    timestamp = pd.Timestamp(value)
    if timestamp.tzinfo is None:
        timestamp = timestamp.tz_localize("UTC")
    else:
        timestamp = timestamp.tz_convert("UTC")
    return timestamp.to_pydatetime()


def rows_from_signals(signals: pd.DataFrame) -> list[dict[str, Any]]:
    """Map the analysis DataFrame to (dedupe_key, text, category, station, author_id, observed_at)."""
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
                "observed_at": _as_utc(signal.get("observed_at")),
            }
        )
    return rows


def _bind_rows(rows: list[dict[str, Any]]) -> list[tuple[Any, ...]]:
    return [
        (
            row["dedupe_key"],
            row["text"],
            row["category"],
            row["station"],
            row["author_id"],
            row["observed_at"],
        )
        for row in rows
    ]


def rows_to_dataframe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Convert result rows back into the standard signal DataFrame."""
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
    rows = _bind_rows(rows_from_signals(signals))
    connection = _connect()
    try:
        ensure_schema(connection)
        for start in range(0, len(rows), chunk_size):
            batch = rows[start : start + chunk_size]
            sql = UPSERT_PREFIX + ", ".join(["(%s, %s, %s, %s, %s, %s)"] * len(batch)) + " " + UPSERT_CONFLICT
            flat = [value for row in batch for value in row]
            with connection.cursor() as cursor:
                cursor.execute(sql, flat)
        connection.commit()
    finally:
        connection.close()
    return len(rows)


def fetch_signals() -> pd.DataFrame:
    """Download every signal from Supabase, oldest first (full mode)."""
    connection = _connect()
    rows: list[dict[str, Any]] = []
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"SELECT text, category, station, author_id, observed_at "
                f"FROM public.{SIGNALS_TABLE} ORDER BY observed_at ASC"
            )
            for record in cursor:
                rows.append(
                    {
                        "text": record[0],
                        "category": record[1],
                        "station": record[2],
                        "author_id": record[3],
                        "observed_at": record[4],
                    }
                )
    finally:
        connection.close()
    frame = rows_to_dataframe(rows)
    frame["observed_at"] = pd.to_datetime(frame["observed_at"], errors="coerce", format="mixed", utc=True)
    return frame


def fetch_public_signals() -> pd.DataFrame | None:
    """Privacy-safe public frame: timestamps/categories/stations only (no text, no authors)."""
    try:
        connection = _connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT observed_at, category, station FROM public.{SIGNALS_TABLE} "
                    f"WHERE category IN ('crowding', 'delay', 'disruption') ORDER BY observed_at"
                )
                records = cursor.fetchall()
        finally:
            connection.close()
    except Exception:
        return None
    if not records:
        return pd.DataFrame(columns=["text", "category", "station", "author_id", "observed_at"])
    frame = pd.DataFrame(records, columns=["observed_at", "category", "station"])
    frame["text"] = ""
    frame["author_id"] = None
    return frame[["text", "category", "station", "author_id", "observed_at"]]


def fetch_public_daily_counts() -> pd.DataFrame | None:
    """Daily category counts + unique authors, computed inside Postgres (authors never leave the DB)."""
    try:
        connection = _connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT (observed_at AT TIME ZONE 'Asia/Kuala_Lumpur')::date AS date,
                           category, count(*) AS posts
                    FROM public.{SIGNALS_TABLE}
                    GROUP BY 1, 2
                    """
                )
                category_rows = cursor.fetchall()
                cursor.execute(
                    f"""
                    SELECT (observed_at AT TIME ZONE 'Asia/Kuala_Lumpur')::date AS date,
                           count(DISTINCT author_id) AS unique_authors
                    FROM public.{SIGNALS_TABLE}
                    GROUP BY 1
                    """
                )
                author_rows = cursor.fetchall()
        finally:
            connection.close()
    except Exception:
        return None
    empty = pd.DataFrame(columns=["date", "total", "unique_authors", "normal", "crowding", "delay", "disruption", "other"])
    if not category_rows:
        return empty
    pivoted = pd.DataFrame(category_rows, columns=["date", "category", "posts"]).pivot_table(
        index="date", columns="category", values="posts", aggfunc="sum", fill_value=0
    )
    authors = pd.DataFrame(author_rows, columns=["date", "unique_authors"])
    result = pivoted.rename_axis(columns=None).reset_index().merge(authors, on="date", how="left")
    result["unique_authors"] = result["unique_authors"].fillna(0).astype(int)
    result["total"] = result[
        [column for column in result.columns if column not in ("date", "unique_authors")]
    ].sum(axis=1)
    for name in ("normal", "crowding", "delay", "disruption", "other"):
        if name not in result.columns:
            result[name] = 0
    result["date"] = pd.to_datetime(result["date"])
    return result[["date", "total", "unique_authors", "normal", "crowding", "delay", "disruption", "other"]].sort_values("date")


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
    if not supabase_creds():
        print("Set SUPABASE_DATABASE_URL in .env first (see README).")
        return 1

    db = os.getenv("LRT_DATABASE_PATH", "data/lrt_monitor.db")
    if command == "init":
        connection = _connect()
        try:
            ensure_schema(connection)
        finally:
            connection.close()
        print(f"Schema ready on Supabase ({SIGNALS_TABLE} table + RLS policy).")
        return 0

    sessions = SignalRepository(db)
    if command == "push":
        signals = pd.DataFrame(
            [
                {
                    "text": str(row["text"]),
                    "category": str(row["category"]),
                    "station": row["station"] or None,
                    "author_id": row["author_id"] or None,
                    "observed_at": _as_utc(row["observed_at"]),
                }
                for row in sessions.all_signals()
            ]
        )
        count = push_signals(signals)
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