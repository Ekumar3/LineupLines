"""FantasyPros ADP scraping source.

Wraps the existing src/data_sources/fantasypros_client.py (vendored into
include/vendored_src/) rather than re-implementing the scrape/parse logic.
"""

from src.data_sources.fantasypros_client import FantasyProsClient
from src.analytics.adp_service import adp_service

from adp_sources.base import BaseADPScraper


class FantasyProsSource(BaseADPScraper):
    source_name = "fantasypros"
    supported_formats = FantasyProsClient.SCORING_FORMATS

    def __init__(self) -> None:
        self._client = FantasyProsClient()

    def scrape(self, scoring_format: str) -> list[dict[str, object]]:
        players = self._client.fetch_adp_data(scoring_format)
        return [
            {
                "name": adp_service.normalize_player_name(p.player_name),
                "position": p.position,
                "team": p.team,
                "adp": p.adp_overall,
            }
            for p in players
        ]
