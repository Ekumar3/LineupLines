from fastapi.testclient import TestClient
import pytest

from src.api.main import app


def test_health():
    client = TestClient(app)
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_lines_latest_returns_data(monkeypatch):
    sample = {"sport": "americanfootball_nfl", "results": [{"sport_key": "x"}]}

    monkeypatch.setattr("src.api.storage.get_latest_lines", lambda: sample)
    client = TestClient(app)

    r = client.get("/lines/latest")
    assert r.status_code == 200
    assert r.json()["sport"] == "americanfootball_nfl"


def test_lines_latest_404(monkeypatch):
    def raise_not_found():
        raise FileNotFoundError()

    monkeypatch.setattr("src.api.storage.get_latest_lines", raise_not_found)
    client = TestClient(app)
    r = client.get("/lines/latest")
    assert r.status_code == 404
