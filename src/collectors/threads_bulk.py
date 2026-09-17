from __future__ import annotations

import argparse
import json
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import pandas as pd
from apify_client import ApifyClient
from dotenv import load_dotenv

from ..nlp.keyword_filter import is_lrt_related
from ..processing.station_mapping import load_station_mapping
from .threads_scraper import (
    build_client,
    deduplicate_thread_signals,
    export_thread_signals,
    normalize_thread_items,
    store_thread_signals,
)

logger = logging.getLogger(__name__)

STATION_MAPPING_PATH = Path(__file__).resolve().parents[2] / "data" / "external" / "kelana_jaya_stations.csv"
DEFAULT_ACTOR_ID = "santamaria-automations/threads-search-scraper"

LINE_TERMS = (
    "lrt",
    "lrt kelana jaya",
    "kelana jaya line",
    "kelana jaya lrt",
    "lrt kj line",
    "lrt kj",
    "kj line",
    "rapid kl lrt",
    "rapid kl",
    "rapidkl",
    "kuala kaya line",
    "#kelanajayaline",
    "#lrt",
    "#lrtkelanajaya",
    "#rapidkl",
    "lrt line",
    "naik lrt",
    "lrt pagi ini",
    "lrt petang ini",
    "lrt service",
)

COMMUTE_TERMS = (
    "lrt sesak",
    "lrt crowded",
    "sesak lrt",
    "lrt delay",
    "delay lrt",
    "lrt lambat",
    "lambat lrt",
    "lrt rosak",
    "rosak lrt",
    "lrt problem",
    "lrt ganggu",
    "lrt tergendala",
    "lrt tutup",
    "lrt breakdown",
    "stesen lrt",
    "escalator lrt",
    "lift lrt",
    "lrt crew",
    "lrt officials",
    "last train lrt",
    "lrt kad",
    "touch n go lrt",
    "lrt crowd",
    "lrt jam",
)


OTHER_LINE_TERMS = (
    "mrt",
    "mrt kajang",
    "kajang line",
    "mrt putrajaya",
    "putrajaya line",
    "ampang line",
    "sri petaling line",
    "shah alam line",
    "kl monorail",
    "monorail kl",
    "monorel",
    "lrt ampang",
    "lrt sri petaling",
    "komuter",
    "ktm komuter",
    "ktm",
    "ets",
    "klia transit",
    "klia express",
    "rail transit",
    "perkhidmatan komuter",
)

GENERAL_TRANSIT_TERMS = (
    "train",
    "keretapi",
    "kereta api",
    "stesen keretapi",
    "stesen",
    "platform train",
    "transit kl",
    "kl transit",
    "public transport",
    "pengangkutan awam",
    "naik mrt",
    "naik monorel",
    "naik komuter",
    "naik train",
    "mrt sesak",
    "sesak mrt",
    "mrt delay",
    "mrt lambat",
    "mrt problem",
    "mrt rosak",
    "monorel sesak",
    "komuter delay",
    "train delay",
    "train rosak",
    "train problem",
    "kereta api delay",
    "rapid mrt",
    "rapid komuter",
    "rapid monorel",
    "prasarana lebih ramai",
    "jom naik transit",
    "sesak pagi isnin",
    "isnin pagi sesak",
)

EXTRA_STATIONS = (
    "hang tuah",
    "bukit bintang",
    "plaza rakyat",
    "bandaraya",
    "pudu",
    "putrajaya sentral",
    "imbi",
    "medan tuanku",
    "titiwangsa",
    "phileo damansara",
    "ttdi",
    "bandar utama",
    "kota damansara",
    "mutiara damansara",
    "kajang",
    "cheras",
    "bangsar",
    "mid valley",
    "seputeh",
    "salak selatan",
    "bukit jalil",
    "arik",
    "sri petaling",
    "ampang",
    "chan sow lin",
    "masjid negara",
    "kuala lumpur sentral",
    "bank negara",
    "pasir seni",
    "kelebor",
)

EVENT_TERMS = (
    "lrt terkandas",
    "lrt berhenti",
    "lrt tak jalan",
    "lrt tidak beroperasi",
    "lrt services affected",
    "lrt update",
    "lrt status",
    "lrt viral",
    "lrt heboh",
    "lrt kemalangan",
    "lrt berita",
    "lrt announcement",
    "lrt henti",
    "lrt bertukar",
    "lrt pindah platform",
    "lrt signal fault",
    "lrt isyarat",
    "lrt semboyan",
    "lrt overhaul",
    "lrt naik taraf",
    "lrt jam",
    "lrt terlalu ramai",
    "lrt tak cukup",
    "lrt tak ramai",
    "lrt kurang",
    "lrt takde",
    "lrt breakdown",
    "lrt panic",
    "lrt hampir",
    "lrt hampir langgar",
    "kelana jaya station",
    "suspend lrt",
)


def clean_station_name(stop_name: str) -> str:
    """Strip sponsor suffixes like 'KL SENTRAL - REDONE' -> 'kl sentral'."""
    return stop_name.split(" - ")[0].casefold()


def build_queries() -> list[str]:
    queries: list[str] = []
    for term in LINE_TERMS:
        queries.append(term)
    for term in COMMUTE_TERMS:
        queries.append(term)
    for term in OTHER_LINE_TERMS:
        queries.append(term)
    for term in GENERAL_TRANSIT_TERMS:
        queries.append(term)
    if STATION_MAPPING_PATH.exists():
        mapping = load_station_mapping(STATION_MAPPING_PATH)
        station_names = sorted({clean_station_name(name) for name in mapping["stop_name"]})
        for name in station_names:
            queries.append(f"{name} lrt")
            queries.append(f"lrt {name}")
        for name in ("masjid jamek", "pasar seni", "kl sentral", "kelana jaya", "putra heights"):
            queries.append(f"stesen {name}")
            queries.append(f"station {name}")
    for name in EXTRA_STATIONS:
        queries.append(f"{name} lrt")
        queries.append(f"{name} mrt")
        queries.append(f"{name} station")
    for term in EVENT_TERMS:
        queries.append(term)
    return queries


def build_client_chunk(token: str) -> ApifyClient:
    return ApifyClient(token)


def run_chunk(
    client: ApifyClient,
    queries: Sequence[str],
    actor_id: str,
    max_posts_per_query: int,
    raw_dir: Path,
    index: int,
    retries: int = 3,
) -> list[dict[str, object]]:
    chunk_path = raw_dir / f"chunk_{index:03d}_{hash(tuple(queries)):08x}.json"
    if chunk_path.exists():
        with open(chunk_path, encoding="utf-8") as handle:
            return json.load(handle)
    last_error: RuntimeError | None = None
    for attempt in range(1, retries + 1):
        try:
            run = client.actor(actor_id).call(
                run_input={
                    "searchQueries": list(queries),
                    "maxPostsPerQuery": int(max_posts_per_query),
                    "maxResults": 0,
                }
            )
            dataset_id = (run or {}).get("defaultDatasetId")
            if not dataset_id:
                raise RuntimeError("Actor run did not return a default dataset")
            items = list(client.dataset(dataset_id).iterate_items())
            with open(chunk_path, "w", encoding="utf-8") as handle:
                json.dump(items, handle, ensure_ascii=False)
            return items
        except Exception as exc:  # noqa: BLE001 - network/actor flakes; retry
            last_error = exc
            logger.warning("Chunk %d attempt %d failed: %s", index, attempt, exc)
            time.sleep(10 * attempt)
    raise RuntimeError(f"Chunk {index} failed after {retries} retries: {last_error}")


def scrape_bulk(
    *,
    actor_id: str = DEFAULT_ACTOR_ID,
    queries: Sequence[str] | None = None,
    max_posts_per_query: int = 30,
    chunk_size: int = 20,
    concurrency: int = 3,
    sleep_between_chunks: float = 15.0,
    fresh: bool = False,
    raw_dir: str | Path = "data/raw",
) -> list[dict[str, object]]:
    raw_dir = Path(raw_dir)
    raw_dir.mkdir(parents=True, exist_ok=True)
    if fresh:
        for stale in raw_dir.glob("chunk_*.json"):
            stale.unlink()
    token = os.getenv("APIFY_TOKEN")
    if not token:
        raise RuntimeError("Missing Apify token: set APIFY_TOKEN in .env")

    query_list = list(queries) if queries is not None else build_queries()
    chunks = [query_list[i : i + chunk_size] for i in range(0, len(query_list), chunk_size)]
    logger.info("Scraping %d queries in %d chunks (actor=%s, maxPostsPerQuery=%d)", len(query_list), len(chunks), actor_id, max_posts_per_query)

    def launch(index: int, chunk: list[str]) -> list[dict[str, object]]:
        result = run_chunk(build_client_chunk(token), chunk, actor_id, max_posts_per_query, raw_dir, index)
        time.sleep(sleep_between_chunks)
        return result

    all_items: list[dict[str, object]] = []
    if concurrency > 1:
        with ThreadPoolExecutor(max_workers=concurrency) as pool:
            futures = {pool.submit(launch, index, chunk): index for index, chunk in enumerate(chunks)}
            for future in as_completed(futures):
                index = futures[future]
                items = future.result()
                all_items.extend(items)
                logger.info("Chunk %d done: %d raw items (running total %d)", index, len(items), len(all_items))
    else:
        for index, chunk in enumerate(chunks):
            items = launch(index, chunk)
            all_items.extend(items)
            logger.info("Chunk %d done: %d raw items (running total %d)", index, len(items), len(all_items))
    return all_items


def _raw_text(item: dict[str, object]) -> str:
    for key in ("text", "caption", "full_text", "post_text"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


def _raw_author(item: dict[str, object]) -> str:
    for key in ("author_username", "username", "author", "authorUsername"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


def _raw_timestamp(item: dict[str, object]) -> str:
    for key in ("posted_at", "timestamp", "taken_at", "created_at", "published_at"):
        value = item.get(key)
        if value:
            return str(value)
    return ""


def deduplicate_raw(items: Sequence[dict[str, object]]) -> list[dict[str, object]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, object]] = []
    for item in items:
        key = (_raw_author(item).casefold(), _raw_text(item).casefold())
        if not key[1] or key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def export_raw(items: Sequence[dict[str, object]], output_dir: str | Path) -> tuple[Path, Path]:
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    json_path = output_dir / f"threads_raw_{stamp}.json"
    csv_path = output_dir / f"threads_raw_{stamp}.csv"
    records = [
        {
            "text": _raw_text(item),
            "author_id": _raw_author(item),
            "posted_at": _raw_timestamp(item),
            "post_url": item.get("post_url") or item.get("postUrl") or "",
            "like_count": item.get("like_count") or item.get("likes") or 0,
            "reply_count": item.get("reply_count") or 0,
            "repost_count": item.get("repost_count") or 0,
            "has_media": item.get("has_media") or False,
            "search_query": item.get("search_query") or "",
        }
        for item in items
    ]
    with open(json_path, "w", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)
    pd.DataFrame(records).to_csv(csv_path, index=False)
    return json_path, csv_path


def main(argv: Sequence[str] | None = None) -> int:
    load_dotenv()
    os.environ.setdefault("LOG_LEVEL", "INFO")
    logging.basicConfig(level=os.environ["LOG_LEVEL"].upper(), format="[%(asctime)s] [%(levelname)s] %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="Bulk-scrape Threads for Kelana Jaya LRT posts (2000+ goal).")
    parser.add_argument("--actor", default=os.getenv("THREADS_ACTOR_ID", DEFAULT_ACTOR_ID), help="Apify actor id")
    parser.add_argument("--max-posts", type=int, default=30, help="maxPostsPerQuery")
    parser.add_argument("--chunk-size", type=int, default=20, help="Queries per actor run")
    parser.add_argument("--concurrency", type=int, default=3, help="Parallel actor runs (lower to avoid rate limits)")
    parser.add_argument("--sleep", type=float, default=15.0, help="Seconds to sleep between chunk launches")
    parser.add_argument("--fresh", action="store_true", help="Ignore cached chunk files and re-scrape everything")
    parser.add_argument("--raw-dir", default="data/raw", help="Chunk checkpoint cache")
    parser.add_argument("--db", default=os.getenv("LRT_DATABASE_PATH", "data/lrt_monitor.db"), help="SQLite database path")
    parser.add_argument("--output-dir", default="data/processed", help="Export directory")
    parser.add_argument("--scrape-only", action="store_true", help="Scrape and export raw only; skip signal pipeline")
    args = parser.parse_args(list(argv) if argv is not None else None)

    items = scrape_bulk(
        actor_id=args.actor,
        max_posts_per_query=args.max_posts,
        chunk_size=args.chunk_size,
        concurrency=args.concurrency,
        sleep_between_chunks=args.sleep,
        fresh=args.fresh,
        raw_dir=args.raw_dir,
    )
    unique = deduplicate_raw(items)
    logger.info("Raw uniqueness: %d deduplicated across %d raw items", len(unique), len(items))

    raw_json, raw_csv = export_raw(unique, args.output_dir)
    logger.info("Exported raw JSON -> %s", raw_json)
    logger.info("Exported raw CSV  -> %s", raw_csv)

    if args.scrape_only:
        return 0

    mapping = load_station_mapping(STATION_MAPPING_PATH) if STATION_MAPPING_PATH.exists() else None
    signals = deduplicate_thread_signals(normalize_thread_items(unique, mapping))
    logger.info("LRT-related signals: %d", len(signals))

    if signals:
        store_thread_signals(signals, args.db)
        signal_json, signal_csv = export_thread_signals(signals, args.output_dir)
        logger.info("Stored %d signals in %s", len(signals), args.db)
        logger.info("Exported signal JSON -> %s", signal_json)
        logger.info("Exported signal CSV  -> %s", signal_csv)
    else:
        logger.warning("No LRT-related signals found across %d raw posts.", len(unique))

    logger.info("DONE: %d raw unique posts, %d LRT signals", len(unique), len(signals))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())