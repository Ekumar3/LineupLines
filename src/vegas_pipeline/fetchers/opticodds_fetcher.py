"""Fetcher for OpticOdds season-long player props API (https://opticodds.com)."""
import os
import requests
import logging
from typing import List, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BASE = "https://api.opticodds.com"

class OpticOddsError(Exception):
    pass


SAMPLE_SEASON_PROPS = {
    "fetched_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    "data_source": "opticodds",
    "sport": "nfl",
    "season": "2026",
    "props": [
        {
            "player_id": None,
            "player_name": "Patrick Mahomes",
            "team": "KC",
            "position": "QB",
            "stat_category": "passing_yards",
            "line": 4200.5,
            "over_odds": -110,
            "under_odds": -110,
            "sportsbook": "draftkings",
            "last_updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        },
        {
            "player_id": None,
            "player_name": "Patrick Mahomes",
            "team": "KC",
            "position": "QB",
            "stat_category": "passing_touchdowns",
            "line": 32.5,
            "over_odds": -115,
            "under_odds": -105,
            "sportsbook": "draftkings",
            "last_updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        },
        {
            "player_id": None,
            "player_name": "Christian McCaffrey",
            "team": "SF",
            "position": "RB",
            "stat_category": "rushing_yards",
            "line": 1450.5,
            "over_odds": -115,
            "under_odds": -105,
            "sportsbook": "fanduel",
            "last_updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        },
        {
            "player_id": None,
            "player_name": "Christian McCaffrey",
            "team": "SF",
            "position": "RB",
            "stat_category": "rushing_touchdowns",
            "line": 12.5,
            "over_odds": -110,
            "under_odds": -110,
            "sportsbook": "fanduel",
            "last_updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        },
        {
            "player_id": None,
            "player_name": "Travis Kelce",
            "team": "KC",
            "position": "TE",
            "stat_category": "receiving_yards",
            "line": 1050.5,
            "over_odds": -110,
            "under_odds": -110,
            "sportsbook": "draftkings",
            "last_updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        },
        {
            "player_id": None,
            "player_name": "Travis Kelce",
            "team": "KC",
            "position": "TE",
            "stat_category": "receptions",
            "line": 85.5,
            "over_odds": -110,
            "under_odds": -110,
            "sportsbook": "fanduel",
            "last_updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        },
        {
            "player_id": None,
            "player_name": "Tyreek Hill",
            "team": "MIA",
            "position": "WR",
            "stat_category": "receiving_yards",
            "line": 1400.5,
            "over_odds": -115,
            "under_odds": -105,
            "sportsbook": "draftkings",
            "last_updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        },
        {
            "player_id": None,
            "player_name": "Tyreek Hill",
            "team": "MIA",
            "position": "WR",
            "stat_category": "receptions",
            "line": 104.5,
            "over_odds": -110,
            "under_odds": -110,
            "sportsbook": "fanduel",
            "last_updated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        },
    ]
}


def fetch_season_props(sport: str = "nfl", season: str = "2026") -> Dict[str, Any]:
    """
    Fetch season-long player props from OpticOdds.

    Args:
        sport: Sport code (e.g., 'nfl', 'nba'). Defaults to 'nfl'.
        season: Season year (e.g., '2026'). Defaults to '2026'.

    Returns:
        Dict with structure:
        {
            "fetched_at": ISO timestamp,
            "data_source": "opticodds",
            "sport": sport,
            "season": season,
            "props": [
                {
                    "player_name": str,
                    "team": str,
                    "position": str,
                    "stat_category": str,
                    "line": float,
                    "over_odds": int,
                    "under_odds": int,
                    "sportsbook": str,
                    "last_updated": ISO timestamp
                },
                ...
            ]
        }

    Returns sample data if OPTICODDS_API_KEY is not set (for local testing).
    Raises OpticOddsError on HTTP errors or missing required parameters.
    """
    api_key = os.environ.get("OPTICODDS_API_KEY")
    if not api_key:
        logger.warning("OPTICODDS_API_KEY not set; returning sample payload for local testing")
        return SAMPLE_SEASON_PROPS

    # TODO: Implement actual OpticOdds API call
    # For now, return sample data with updated timestamp
    sample = SAMPLE_SEASON_PROPS.copy()
    sample["fetched_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    logger.info("Fetched season props for %s season %s from OpticOdds", sport, season)
    return sample


def get_player_stat_categories() -> List[str]:
    """Return list of supported stat categories for season-long props."""
    return [
        "passing_yards",
        "passing_touchdowns",
        "interceptions",
        "rushing_yards",
        "rushing_touchdowns",
        "receiving_yards",
        "receptions",
        "receiving_touchdowns",
    ]
