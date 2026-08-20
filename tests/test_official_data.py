from pathlib import Path

from src.collectors import official_data


class FakeResponse:
    content = b"gtfs zip bytes"

    def raise_for_status(self) -> None:
        return None


def test_prasarana_gtfs_download_uses_documented_endpoint(monkeypatch, tmp_path: Path) -> None:
    captured: dict[str, object] = {}

    def fake_get(url: str, **kwargs: object) -> FakeResponse:
        captured["url"] = url
        captured.update(kwargs)
        return FakeResponse()

    monkeypatch.setattr(official_data.requests, "get", fake_get)
    target = official_data.download_prasarana_gtfs(tmp_path / "prasarana.zip")

    assert captured["url"] == official_data.PRASARANA_GTFS_URL
    assert captured["params"] == {"category": "rapid-rail-kl"}
    assert target.read_bytes() == b"gtfs zip bytes"