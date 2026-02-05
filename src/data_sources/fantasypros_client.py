"""FantasyPros ADP data client.

Fetches Average Draft Position (ADP) data from FantasyPros for multiple scoring formats.
Provides historical ADP data for building draft recommendations.
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
import json

logger = logging.getLogger(__name__)


@dataclass
class Player:
    """Represents a player with ADP information."""
    player_name: str
    position: str
    team: str
    adp_overall: float
    adp_by_position: int
    round: int
    scoring_format: str
    updated_at: datetime


class FantasyProsClient:
    """Client for fetching FantasyPros ADP data.

    Supports multiple scoring formats (PPR, Standard, Half-PPR).
    Data can be fetched via web scraping or cached locally.
    """

    SCORING_FORMATS = ["ppr", "standard", "half_ppr"]
    BASE_URL = "https://www.fantasypros.com/nfl/rankings"

    def __init__(self):
        """Initialize the FantasyPros client."""
        self.data_cache: Dict[str, List[Player]] = {}
        self.last_updated: Dict[str, datetime] = {}

    def fetch_adp_data(self, scoring_format: str) -> List[Player]:
        """Fetch ADP data from FantasyPros for the given scoring format.

        Args:
            scoring_format: One of "ppr", "standard", "half_ppr"

        Returns:
            List of Player objects with ADP information

        Raises:
            ValueError: If scoring_format is not supported
            Exception: If fetching fails
        """
        if scoring_format not in self.SCORING_FORMATS:
            raise ValueError(
                f"Unsupported scoring format: {scoring_format}. "
                f"Must be one of {self.SCORING_FORMATS}"
            )

        # Check cache first
        if scoring_format in self.data_cache:
            logger.info(f"Returning cached ADP data for {scoring_format}")
            return self.data_cache[scoring_format]

        # Fetch from FantasyPros
        logger.info(f"Fetching ADP data from FantasyPros for {scoring_format}")
        players = self._scrape_adp_data(scoring_format)

        # Cache the data
        self.data_cache[scoring_format] = players
        self.last_updated[scoring_format] = datetime.utcnow()

        return players

    def _scrape_adp_data(self, scoring_format: str) -> List[Player]:
        """Scrape ADP data from FantasyPros website.

        Note: FantasyPros uses JavaScript to render rankings. This method uses Selenium
        to render the page. If Selenium is unavailable, it falls back to basic requests
        (which may not work if content is dynamically loaded).

        Requirements: selenium, beautifulsoup4, requests

        Args:
            scoring_format: One of "ppr", "standard", "half_ppr"

        Returns:
            List of Player objects
        """
        try:
            import requests
            from bs4 import BeautifulSoup
        except ImportError:
            logger.error(
                "requests and beautifulsoup4 required for ADP scraping. "
                "Install with: pip install requests beautifulsoup4"
            )
            return []

        # Map format to URL parameter (cheatsheets pages)
        format_map = {
            "ppr": "ppr-cheatsheets.php",
            "standard": "standard-cheatsheets.php",
            "half_ppr": "half-ppr-cheatsheets.php"
        }

        url = f"{self.BASE_URL}/{format_map[scoring_format]}"

        try:
            # Try to fetch with Selenium for JavaScript rendering
            html_content = self._fetch_with_selenium(url)
            if not html_content:
                # Fallback to basic requests
                logger.info("Selenium unavailable, trying basic requests fetch")
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                html_content = response.content

            soup = BeautifulSoup(html_content, "html.parser")
            players = self._parse_adp_table(soup, scoring_format)

            logger.info(f"Fetched {len(players)} players from FantasyPros for {scoring_format}")
            return players

        except Exception as e:
            logger.error(f"Failed to fetch FantasyPros ADP data: {e}")
            return []

    def _fetch_with_selenium(self, url: str) -> Optional[str]:
        """Fetch page content using Selenium for JavaScript rendering.

        Selenium renders the page with a headless Chrome browser to load dynamically
        generated content. This is required for FantasyPros cheatsheets pages.

        Args:
            url: URL to fetch

        Returns:
            HTML content as string, or None if Selenium unavailable or fails
        """
        try:
            from selenium import webdriver
            from selenium.webdriver.common.by import By
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
        except ImportError:
            logger.debug("Selenium not installed, skipping JavaScript rendering")
            return None

        try:
            logger.debug(f"Fetching {url} with Selenium for JavaScript rendering")

            # Configure headless browser
            options = webdriver.ChromeOptions()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")

            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(30)

            try:
                driver.get(url)

                # Wait for ranking table to load
                wait = WebDriverWait(driver, 10)
                wait.until(EC.presence_of_element_located((By.ID, "ranking-table")))

                # Get rendered HTML
                html_content = driver.page_source
                logger.debug("Successfully rendered page with Selenium")
                return html_content

            finally:
                driver.quit()

        except Exception as e:
            logger.debug(f"Selenium fetch failed: {e}")
            return None

    def _parse_adp_table(self, soup, scoring_format: str) -> List[Player]:
        """Parse the ADP table from FantasyPros HTML.

        The cheatsheets page uses a table with id="ranking-table" and class containing "player-table".
        Table structure: Rank | Player | Team/Pos | ADP | vs ADP | etc.

        Args:
            soup: BeautifulSoup object of the page
            scoring_format: The scoring format being parsed

        Returns:
            List of Player objects
        """
        players = []

        # Look for the main ranking table by id
        table = soup.find("table", {"id": "ranking-table"})

        if not table:
            logger.warning("Could not find ranking table on FantasyPros page")
            return []

        rows = table.find_all("tr")[1:]  # Skip header

        for idx, row in enumerate(rows, 1):
            try:
                cols = row.find_all("td")
                if len(cols) < 7:  # Need at least up to col 6 for ADP
                    continue

                # Validate rank is numeric (skip tier rows and header rows)
                rank_text = cols[0].text.strip()
                try:
                    int(rank_text)
                except (ValueError, IndexError):
                    # Skip non-numeric rank rows (tier headers, etc.)
                    continue

                # Extract player information from known column positions
                # Structure: Rank | Checkbox | Player(Team) | Position | Pos_Rank | Bye | ADP | vs_ADP | ...
                player_info = cols[2].text.strip()
                if not player_info:
                    continue

                # Position designation is in col 3 (e.g., "WR1", "RB2")
                pos_designation = cols[3].text.strip()  # e.g., "WR1", "RB2"

                # Extract position from designation
                position = self._extract_position(pos_designation)

                # Extract team from player info (format: "Player Name (TEAM)")
                team = self._extract_team_from_player_info(player_info)

                # ADP is in col 6 (0-indexed)
                try:
                    adp_overall = float(cols[6].text.strip())
                except (ValueError, IndexError):
                    continue

                # Validate ADP is in reasonable range
                if not (1 <= adp_overall <= 500):
                    continue

                # Calculate round from ADP (assuming 12-team league)
                round_num = int((adp_overall - 1) // 12) + 1

                # Calculate position rank
                adp_by_position = self._calculate_position_rank(players, position)

                player = Player(
                    player_name=player_info,
                    position=position,
                    team=team,
                    adp_overall=adp_overall,
                    adp_by_position=adp_by_position,
                    round=round_num,
                    scoring_format=scoring_format,
                    updated_at=datetime.utcnow()
                )

                players.append(player)
                logger.debug(
                    f"Parsed player: {player_info} ({position}) - ADP: {adp_overall:.1f}"
                )

            except (ValueError, IndexError) as e:
                logger.debug(f"Skipped row {idx}: {e}")
                continue

        return players

    def _extract_position(self, team_pos_str: str) -> str:
        """Extract position from team/position string.

        Args:
            team_pos_str: String like "SF - RB" or "KC - WR"

        Returns:
            Position string (QB, RB, WR, TE, K, DEF)
        """
        # Typical format: "TEAM - POS" or "POS"
        positions = ["QB", "RB", "WR", "TE", "K", "DEF"]
        for pos in positions:
            if pos in team_pos_str.upper():
                return pos
        return "UNKNOWN"

    def _extract_team(self, team_pos_str: str) -> str:
        """Extract team from team/position string.

        Args:
            team_pos_str: String like "SF - RB" or "KC - WR"

        Returns:
            Team abbreviation
        """
        # Typical format: "TEAM - POS"
        parts = team_pos_str.split("-")
        return parts[0].strip()[:3].upper() if parts else "UNK"

    def _extract_team_from_player_info(self, player_info: str) -> str:
        """Extract team from player info string.

        Args:
            player_info: String like "Ja'Marr Chase (CIN)" or "Player Name (TB)"

        Returns:
            Team abbreviation (e.g., "CIN", "TB")
        """
        # Format: "Player Name (TEAM)"
        if "(" in player_info and ")" in player_info:
            start = player_info.rfind("(")
            end = player_info.rfind(")")
            if start >= 0 and end > start:
                team = player_info[start + 1 : end].strip().upper()
                return team[:3]  # Limit to 3 chars
        return "UNK"

    def _calculate_position_rank(self, players: List[Player], position: str) -> int:
        """Calculate the positional rank (e.g., RB5, WR12).

        Args:
            players: List of players already processed
            position: Position to rank

        Returns:
            1-indexed position rank
        """
        count = sum(1 for p in players if p.position == position)
        return count + 1

    def load_from_file(self, filepath: str, scoring_format: str) -> List[Player]:
        """Load ADP data from a local JSON file.

        Args:
            filepath: Path to JSON file with ADP data
            scoring_format: Scoring format key

        Returns:
            List of Player objects
        """
        try:
            with open(filepath, "r") as f:
                data = json.load(f)

            players = [
                Player(
                    player_name=p["player_name"],
                    position=p["position"],
                    team=p["team"],
                    adp_overall=p["adp_overall"],
                    adp_by_position=p["adp_by_position"],
                    round=p["round"],
                    scoring_format=scoring_format,
                    updated_at=datetime.fromisoformat(p["updated_at"])
                )
                for p in data
            ]

            self.data_cache[scoring_format] = players
            self.last_updated[scoring_format] = datetime.utcnow()

            return players

        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.error(f"Failed to load ADP data from {filepath}: {e}")
            return []

    def save_to_file(self, filepath: str, scoring_format: str) -> bool:
        """Save cached ADP data to a local JSON file.

        Args:
            filepath: Path to save JSON file
            scoring_format: Scoring format key

        Returns:
            True if successful, False otherwise
        """
        if scoring_format not in self.data_cache:
            logger.warning(f"No cached data for {scoring_format}")
            return False

        try:
            players = self.data_cache[scoring_format]
            data = [
                {
                    "player_name": p.player_name,
                    "position": p.position,
                    "team": p.team,
                    "adp_overall": p.adp_overall,
                    "adp_by_position": p.adp_by_position,
                    "round": p.round,
                    "scoring_format": p.scoring_format,
                    "updated_at": p.updated_at.isoformat()
                }
                for p in players
            ]

            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)

            logger.info(f"Saved {len(players)} players to {filepath}")
            return True

        except IOError as e:
            logger.error(f"Failed to save ADP data to {filepath}: {e}")
            return False

    def get_cached_data(self, scoring_format: str) -> Optional[List[Player]]:
        """Get cached ADP data if available.

        Args:
            scoring_format: One of "ppr", "standard", "half_ppr"

        Returns:
            List of Player objects or None if not cached
        """
        return self.data_cache.get(scoring_format)

    def clear_cache(self, scoring_format: Optional[str] = None) -> None:
        """Clear cached ADP data.

        Args:
            scoring_format: Specific format to clear, or None to clear all
        """
        if scoring_format:
            self.data_cache.pop(scoring_format, None)
            self.last_updated.pop(scoring_format, None)
        else:
            self.data_cache.clear()
            self.last_updated.clear()
