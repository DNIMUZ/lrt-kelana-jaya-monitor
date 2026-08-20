from ..models import OfficialFact


def fetch_train_positions() -> OfficialFact:
    """Adapter boundary for an approved GTFS-Realtime or official feed."""
    return OfficialFact()
