"""Registry contract for ADP scraping sources.

Adding a new scraped source means writing one class implementing
BaseADPScraper and appending an instance to REGISTERED_SOURCES in
__init__.py — the DAG iterates that list and never hardcodes a source name.
"""

from abc import ABC, abstractmethod


class BaseADPScraper(ABC):
    source_name: str
    supported_formats: list[str]

    @abstractmethod
    def scrape(self, scoring_format: str) -> list[dict[str, object]]:
        """Scrape ADP data for one scoring format.

        Returns a list of records: {"name": normalized_name, "position": str,
        "team": str, "adp": float}. Position is required downstream to
        disambiguate same-named players across positions when cross-
        referencing against the Sleeper player universe.
        """
        raise NotImplementedError
