from __future__ import annotations

from datetime import datetime, timezone

from src.models import PublicSignal, SignalCategory
from src.storage import SignalRepository


def _signal(text: str, author: str, category: SignalCategory = SignalCategory.OTHER) -> PublicSignal:
    return PublicSignal(
        text=text,
        category=category,
        station=None,
        observed_at=datetime(2026, 9, 1, 1, 0, tzinfo=timezone.utc),
        source="threads",
        independent_author=True,
        author_id=author,
    )


def test_add_signal_deduplicates_on_author_and_text(tmp_path) -> None:
    repo = SignalRepository(str(tmp_path / "signals.db"))
    repo.add_signal(_signal("lrt kelana jaya problem", "ali"))
    repo.add_signal(_signal("lrt kelana jaya problem", "ali"))  # duplicate
    repo.add_signal(_signal("lrt kelana jaya problem", "ALI"))  # case-variant duplicate
    repo.add_signal(_signal("lrt kelana jaya problem", "abu"))  # different author = new
    all_rows = repo.all_signals()
    assert len(all_rows) == 2


def test_recent_signals_typed_round_trips(tmp_path) -> None:
    repo = SignalRepository(str(tmp_path / "signals.db"))
    repo.add_signal(_signal("lrt rosak", "cikgu", SignalCategory.DISRUPTION))
    typed = repo.recent_signals_typed(5)
    assert len(typed) == 1
    assert typed[0].category == SignalCategory.DISRUPTION
    assert typed[0].author_id == "cikgu"