from __future__ import annotations

from pathlib import Path

import pytest

from src.collectors.threads_scraper import (
    deduplicate_thread_signals,
    normalize_thread_item,
    normalize_thread_items,
    run_threads_search,
)
from src.models import PublicSignal, SignalCategory
from src.processing.station_mapping import load_station_mapping

STATIONS = Path(__file__).parents[1] / "data" / "external" / "kelana_jaya_stations.csv"


class _FakeDataset:
    def __init__(self, items: list[dict[str, object]]) -> None:
        self._items = items

    def iterate_items(self):
        return iter(self._items)


class _FakeActor:
    def __init__(self) -> None:
        self.last_input: dict[str, object] | None = None

    def call(self, run_input: dict[str, object]) -> dict[str, str]:
        self.last_input = run_input
        return {"defaultDatasetId": "dataset-default-1", "status": "SUCCEEDED"}


class _FakeClient:
    def __init__(self, items: list[dict[str, object]]) -> None:
        self._items = items
        self.actor_id: str | None = None

    def actor(self, actor_id: str) -> _FakeActor:
        self.actor_id = actor_id
        return _FakeActor()

    def dataset(self, dataset_id: str) -> _FakeDataset:
        return _FakeDataset(self._items)


def test_run_threads_search_returns_dataset_items() -> None:
    client = _FakeClient([{"postId": "A1", "text": "hello"}])
    items = run_threads_search(client, keywords=["lrt kelana jaya"], actor_id="actor/threads", max_results_per_query=10)
    assert items == [{"postId": "A1", "text": "hello"}]
    assert client.actor_id == "actor/threads"


def test_normalize_item_drops_non_lrt_posts() -> None:
    item = {"caption": "makan malam sedap banget", "username": "foodie", "timestamp": "2026-08-20T12:00:00Z"}
    assert normalize_thread_item(item) is None


def test_normalize_item_nested_caption_shape() -> None:
    mapping = load_station_mapping(STATIONS)
    item = {
        "post": {"caption": {"text": "LRT KJ14 sangat sesak pagi ini"}, "user": {"username": "commuter_kl"}},
        "timestamp": "2026-08-20T12:00:00Z",
    }
    signal = normalize_thread_item(item, station_mapping=mapping)
    assert signal is not None
    assert signal.category.value == "crowding"
    assert signal.station == "KJ14"
    assert signal.source == "threads"
    assert signal.author_id == "commuter_kl"
    assert signal.observed_at.year == 2026


def test_normalize_items_and_deduplicate() -> None:
    items = [
        {"caption": "LRT kelana jaya delay 10 minit", "username": "rider1", "timestamp": "2026-08-20T12:00:00Z"},
        {"caption": "LRT kelana jaya delay 10 minit", "username": "rider1", "timestamp": "2026-08-20T12:00:01Z"},
    ]
    signals = deduplicate_thread_signals(normalize_thread_items(items))
    assert len(signals) == 1
    assert signals[0].category == SignalCategory.DELAY


def test_normalize_item_accepts_int_timestamp() -> None:
    item = {"text": "benci kena tunggu lrt kj", "author": "rider2", "timestamp": 1784700000}
    signal = normalize_thread_item(item)
    assert signal is not None
    assert signal.observed_at.tzinfo is not None


def test_misspelled_alias_is_kept() -> None:
    item = {"text": "kuala kaya line lagi delay", "username": "rider3", "timestamp": "2026-08-20T12:00:00Z"}
    assert normalize_thread_item(item) is not None


def test_build_client_requires_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    from src.collectors.threads_scraper import build_client

    with pytest.raises(Exception):
        build_client()