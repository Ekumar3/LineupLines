"""DraftSharks ADP + tier scraping source.

Wraps src/data_sources/draft_sharks_client.py rather than re-implementing the
scrape/parse logic.
"""

from src.data_sources.draft_sharks_client import DraftSharksClient
from src.analytics.adp_service import adp_service

from adp_sources.base import BaseADPScraper


class DraftSharksSource(BaseADPScraper):
    source_name = "draftsharks"
    supported_formats = DraftSharksClient.SCORING_FORMATS

    def __init__(self) -> None:
        self._client = DraftSharksClient()

    def scrape(self, scoring_format: str) -> list[dict[str, object]]:
        players = self._client.fetch_adp_data(scoring_format)
        return [
            {
                "name": adp_service.normalize_player_name(p.player_name),
                "position": p.position,
                "team": p.team,
                "adp": p.adp_overall,
                "tier": p.tier,
                "positional_tier": p.positional_tier,
            }
            for p in players
        ]
