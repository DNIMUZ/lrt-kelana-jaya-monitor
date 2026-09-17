from __future__ import annotations

import argparse
import json
import logging
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pandas as pd
from apify_client import ApifyClient
from dotenv import load_dotenv

from ..models import PublicSignal
from ..nlp.classifier import classify_text
from ..nlp.keyword_filter import is_lrt_related
from ..processing.station_mapping import load_station_mapping
from ..storage import SignalRepository

logger = logging.getLogger(__name__)

DEFAULT_ACTOR_ID = "santamaria-automations/threads-search-scraper"
DEFAULT_KEYWORDS = (
    "lrt kelana jaya",
    "kelana jaya line",
    "lrt kj line",
    "kelana jaya lrt",
    "rapid kl lrt",
    "kuala kaya line",
    "#kelanajayaline",
)
STATION_MAPPING_PATH = Path(__file__).resolve().parents[2] / "data" / "external" / "kelana_jaya_stations.csv"


class ThreadsSearchError(RuntimeError):
    pass


def build_client(token: str | None = None) -> ApifyClient:
    token = token or os.getenv("APIFY_TOKEN")
    if not token:
        raise ThreadsSearchError("Missing Apify token: set APIFY_TOKEN in .env")
    return ApifyClient(token)


def _run_input_for(
    actor_id: str,
    keywords: Sequence[str],
    max_results_per_query: int,
    include_replies: bool,
) -> dict[str, object]:
    if "santamaria-automations/threads-search-scraper" in actor_id:
        # Server-rendered (SSR) search actor: no GraphQL doc-id dependency.
        return {
            "searchQueries": list(keywords),
            "maxPostsPerQuery": int(max_results_per_query),
            "maxResults": 0,
        }
    # Generic GraphQL-based search actors.
    return {
        "scrapeType": "search",
        "searchQueries": list(keywords),
        "maxResults": int(max_results_per_query),
        "includeReplies": bool(include_replies),
    }


def run_threads_search(
    client: ApifyClient,
    *,
    keywords: Sequence[str],
    actor_id: str = DEFAULT_ACTOR_ID,
    max_results_per_query: int = 50,
    include_replies: bool = False,
) -> list[dict[str, object]]:
    """Run a keyword search against an Apify Threads actor and return raw items."""
    run_input = _run_input_for(actor_id, keywords, max_results_per_query, include_replies)
    logger.info("Running Threads search with actor=%s queries=%s", actor_id, keywords)
    run = client.actor(actor_id).call(run_input=run_input)
    dataset_id = (run or {}).get("defaultDatasetId")
    if not dataset_id:
        raise ThreadsSearchError("Actor run did not return a default dataset")
    return list(client.dataset(dataset_id).iterate_items())


def _nested(item: dict[str, object], key: str) -> dict[str, object]:
    value = item.get(key)
    return value if isinstance(value, dict) else {}


def _extract_text(item: dict[str, object]) -> str:
    for key in ("text", "caption", "full_text", "post_text"):
        value = item.get(key)
        if value:
            return str(value)
    caption = item.get("caption")
    if isinstance(caption, dict):
        value = caption.get("text")
        if value:
            return str(value)
    for container_key in ("post", "thread"):
        container = _nested(item, container_key)
        for key in ("text", "caption", "full_text"):
            value = container.get(key)
            if value:
                return str(value)
        caption = container.get("caption")
        if isinstance(caption, dict):
            value = caption.get("text")
            if value:
                return str(value)
    return ""


def _extract_author(item: dict[str, object]) -> str:
    user = item.get("user")
    if isinstance(user, dict):
        value = user.get("username")
        if value:
            return str(value)
    for key in ("username", "author", "author_username", "authorUsername"):
        value = item.get(key)
        if value:
            return str(value)
    for container_key in ("post", "thread"):
        container = _nested(item, container_key)
        user = container.get("user")
        if isinstance(user, dict):
            value = user.get("username")
            if value:
                return str(value)
        for key in ("username", "author"):
            value = container.get(key)
            if value:
                return str(value)
    return ""


def _coerce_datetime(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except (ValueError, TypeError, OverflowError):
        return None


def _extract_observed_at(item: dict[str, object]) -> datetime:
    keys = ("timestamp", "taken_at", "created_at", "published_at", "posted_at", "date", "observed_at")
    for key in keys:
        parsed = _coerce_datetime(item.get(key))
        if parsed is not None:
            return parsed
    for container_key in ("post", "thread"):
        container = _nested(item, container_key)
        for key in keys:
            parsed = _coerce_datetime(container.get(key))
            if parsed is not None:
                return parsed
    return datetime.now(timezone.utc)


def normalize_thread_item(
    item: dict[str, object],
    station_mapping: object = None,
    default_source: str = "threads",
) -> PublicSignal | None:
    text = _extract_text(item).strip()
    if not is_lrt_related(text):
        return None
    signal = classify_text(text, station_mapping=station_mapping)
    author_id = _extract_author(item) or None
    return PublicSignal(
        text=signal.text,
        category=signal.category,
        station=signal.station,
        observed_at=_extract_observed_at(item),
        source=default_source,
        independent_author=True,
        author_id=author_id,
    )


def normalize_thread_items(items: Sequence[dict[str, object]], station_mapping: object = None) -> list[PublicSignal]:
    return [signal for item in items if (signal := normalize_thread_item(item, station_mapping)) is not None]


def deduplicate_thread_signals(signals: Sequence[PublicSignal]) -> list[PublicSignal]:
    """Keep one signal per author and normalized text across overlapping queries."""
    seen: set[tuple[str | None, str]] = set()
    result: list[PublicSignal] = []
    for signal in signals:
        key = (signal.author_id, signal.text.casefold())
        if key in seen:
            continue
        seen.add(key)
        result.append(signal)
    return result


def _signal_dicts(signals: Sequence[PublicSignal]) -> list[dict[str, object]]:
    payload: list[dict[str, object]] = []
    for signal in signals:
        record = asdict(signal)
        record["category"] = signal.category.value
        record["observed_at"] = signal.observed_at.isoformat()
        payload.append(record)
    return payload


def store_thread_signals(signals: Sequence[PublicSignal], database_path: str) -> None:
    repository = SignalRepository(database_path)
    for signal in signals:
        repository.add_signal(signal)


def export_thread_signals(signals: Sequence[PublicSignal], output_dir: str | Path) -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"threads_{stamp}.json"
    csv_path = output_dir / f"threads_{stamp}.csv"
    records = _signal_dicts(signals)
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)
    pd.DataFrame(records).to_csv(csv_path, index=False)
    return json_path, csv_path


def load_default_station_mapping() -> object | None:
    if not STATION_MAPPING_PATH.exists():
        logger.warning("Station mapping not found at %s; skipping station detection", STATION_MAPPING_PATH)
        return None
    return load_station_mapping(STATION_MAPPING_PATH)


def _keywords_from_env() -> list[str]:
    raw = os.getenv("THREADS_KEYWORDS", "")
    return [part.strip() for part in raw.split(",") if part.strip()]


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    os.environ.setdefault("LOG_LEVEL", "INFO")
    logging.basicConfig(level=os.environ["LOG_LEVEL"].upper(), format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Scrape Threads (via Apify) for Kelana Jaya LRT posts.")
    parser.add_argument("-k", "--keywords", nargs="+", default=None, help="Search keywords (defaults to THREADS_KEYWORDS env or built-in list)")
    parser.add_argument("--actor", default=os.getenv("THREADS_ACTOR_ID", DEFAULT_ACTOR_ID), help=f"Apify actor id (default: {DEFAULT_ACTOR_ID})")
    parser.add_argument("--max-results", type=int, default=int(os.getenv("THREADS_MAX_RESULTS_PER_QUERY", "50")), help="Max results per query")
    parser.add_argument("--include-replies", action="store_true", help="Include reply posts in results")
    parser.add_argument("--db", default=os.getenv("LRT_DATABASE_PATH", "data/lrt_monitor.db"), help="SQLite database path")
    parser.add_argument("--output-dir", default=os.getenv("THREADS_OUTPUT_DIR", "data/processed"), help="Export directory for JSON/CSV copies")
    args = parser.parse_args(list(argv) if argv is not None else None)

    keywords = args.keywords or _keywords_from_env() or list(DEFAULT_KEYWORDS)

    client = build_client()
    items = run_threads_search(
        client,
        keywords=keywords,
        actor_id=args.actor,
        max_results_per_query=args.max_results,
        include_replies=args.include_replies,
    )
    logger.info("Retrieved %d raw items from Threads search", len(items))

    signals = deduplicate_thread_signals(normalize_thread_items(items, load_default_station_mapping()))
    if not signals:
        logger.warning("No LRT-related Threads posts were found.")
        return 0

    store_thread_signals(signals, args.db)
    json_path, csv_path = export_thread_signals(signals, args.output_dir)
    logger.info("Stored %d signals in %s", len(signals), args.db)
    logger.info("Exported JSON -> %s", json_path)
    logger.info("Exported CSV  -> %s", csv_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())