import os
import json
import pytest
from src.vegas_pipeline.fetchers.the_odds_api import fetch_odds, SAMPLE_RESPONSE


def test_fetch_without_key_returns_sample(monkeypatch):
    monkeypatch.delenv("ODDS_API_KEY", raising=False)
    res = fetch_odds(sport="americanfootball_nfl")
    assert isinstance(res, list)
    assert res == SAMPLE_RESPONSE


class DummyResp:
    def __init__(self, status_code, json_data):
        self.status_code = status_code
        self._json = json_data
        self.text = json.dumps(json_data)

    def json(self):
        return self._json


def test_fetch_with_api_key_requests(monkeypatch):
    monkeypatch.setenv("ODDS_API_KEY", "fake-key")

    def fake_get(url, params, timeout):
        assert "apiKey" in params
        return DummyResp(200, [{"sport_key": "test"}])

    monkeypatch.setattr("requests.get", fake_get)
    res = fetch_odds(sport="test_sport")
    assert isinstance(res, list)
    assert res[0]["sport_key"] == "test"
