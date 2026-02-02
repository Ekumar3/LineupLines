"""Minimal wrapper for The Odds API (https://the-odds-api.com)."""
import os
import requests
import logging
from typing import List, Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BASE = "https://api.the-odds-api.com/v4"


class OddsAPIError(Exception):
    pass


SAMPLE_RESPONSE = [{
    "sport_key": "americanfootball_nfl",
    "sport_nice": "NFL",
    "commence_time": 1601510400,
    "home_team": "NE Patriots",
    "away_team": "NY Jets",
    "bookmakers": [],
}]


def fetch_odds(sport: str = "americanfootball_nfl", regions: str = "us", markets: str = "spreads,totals,player_props") -> List[Any]:
    """Fetch odds for a given sport. Returns parsed JSON (or SAMPLE_RESPONSE on missing key)."""
    api_key = os.environ.get("ODDS_API_KEY")
    if not api_key:
        logger.warning("ODDS_API_KEY not set; returning sample payload for local testing")
        return SAMPLE_RESPONSE

    url = f"{BASE}/sports/{sport}/odds"
    params = {
        "apiKey": api_key,
        "regions": regions,
        "markets": markets,
        "oddsFormat": "american",
    }

    resp = requests.get(url, params=params, timeout=10)
    if resp.status_code != 200:
        logger.error("Odds API returned %s: %s", resp.status_code, resp.text)
        raise OddsAPIError(f"HTTP {resp.status_code}: {resp.text}")

    data = resp.json()
    logger.info("Fetched %d events for sport %s", len(data), sport)
    return data
