"""DraftSharks ADP data client.

Fetches Average Draft Position (ADP) data and expert tiers from DraftSharks for
multiple scoring formats. Provides ADP + tier data for building draft
recommendations.
"""

import logging
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime
import json
import re
from pathlib import Path

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


@dataclass
class Player:
    """Represents a player with ADP and tier information."""
    player_name: str
    position: str
    team: str
    adp_overall: float
    adp_by_position: int
    round: int
    scoring_format: str
    updated_at: datetime
    tier: int = 0
    positional_tier: int = 0


class DraftSharksClient:
    """Client for fetching DraftSharks ADP + tier data.

    Supports multiple scoring formats (PPR, Standard, Half-PPR).
    Data can be fetched via web scraping or cached locally.
    """

    SCORING_FORMATS = ["ppr", "standard", "half_ppr"]
    BASE_URL = "https://www.draftsharks.com/rankings"

    def __init__(self):
        """Initialize the DraftSharks client."""
        self.data_cache: Dict[str, List[Player]] = {}
        self.last_updated: Dict[str, datetime] = {}

    def fetch_adp_data(self, scoring_format: str) -> List[Player]:
        """Fetch ADP data from DraftSharks for the given scoring format.

        Args:
            scoring_format: One of "ppr", "standard", "half_ppr"

        Returns:
            List of Player objects with ADP and tier information

        Raises:
            ValueError: If scoring_format is not supported
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

        # Try to load from static file first (avoids slow scraping)
        players = self._load_saved_players(scoring_format)
        if players:
            logger.info(f"Loaded {len(players)} players from saved file")
        else:
            # Fall back to scraping if no saved file exists
            logger.info(f"No saved ADP file found, fetching from DraftSharks for {scoring_format}")
            players = self._scrape_adp_data(scoring_format)

        # Cache the data
        self.data_cache[scoring_format] = players
        self.last_updated[scoring_format] = datetime.utcnow()

        return players

    def _load_saved_players(self, scoring_format: str) -> Optional[List[Player]]:
        """Load previously saved players from JSON file.

        Searches for the most recent {scoring_format}_*_players.json file,
        first in data/players/ then in debug_html/ as fallback.

        Args:
            scoring_format: The scoring format (ppr, half_ppr, standard)

        Returns:
            List of Player objects from saved file, or None if not found
        """
        try:
            pattern = f"{scoring_format}_*_players.json"
            files = []

            # Search data/players/ first (primary location)
            data_dir = PROJECT_ROOT / "data" / "players"
            if data_dir.exists():
                files = sorted(data_dir.glob(pattern), reverse=True)

            # Fall back to debug_html/
            if not files:
                debug_dir = PROJECT_ROOT / "debug_html"
                if debug_dir.exists():
                    files = sorted(debug_dir.glob(pattern), reverse=True)

            if not files:
                logger.debug(f"No saved players file found for {scoring_format}")
                return None

            latest_file = files[0]
            logger.debug(f"Loading saved players from: {latest_file.name}")

            with open(latest_file, "r", encoding="utf-8") as f:
                players_data = json.load(f)

            players = [
                Player(
                    player_name=p["player_name"],
                    position=p["position"],
                    team=p["team"],
                    adp_overall=p["adp_overall"],
                    adp_by_position=p["adp_by_position"],
                    round=p["round"],
                    scoring_format=p["scoring_format"],
                    updated_at=datetime.utcnow(),
                    tier=p.get("tier", 0),
                    positional_tier=p.get("positional_tier", 0),
                )
                for p in players_data
            ]

            logger.info(f"Loaded {len(players)} saved players from {latest_file.name}")
            return players

        except Exception as e:
            logger.debug(f"Failed to load saved players: {e}")
            return None

    def _scrape_adp_data(self, scoring_format: str) -> List[Player]:
        """Scrape ADP + tier data from the DraftSharks rankings page.

        Note: DraftSharks renders its rankings table with Alpine.js. All ~250
        ranked players are present in the DOM on initial load (hidden via
        `display:none`/`x-show` until scrolled into view) rather than being
        lazy-loaded via a follow-up API call, so no scroll loop is required -
        we just need to wait for the Alpine app to finish rendering rows.

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

        # "standard" has no URL suffix - it's the bare /rankings page, not /rankings/standard.
        format_map = {
            "ppr": "ppr",
            "standard": "",
            "half_ppr": "half-ppr",
        }

        suffix = format_map[scoring_format]
        url = f"{self.BASE_URL}/{suffix}" if suffix else self.BASE_URL

        try:
            html_content = self._fetch_with_selenium(url)
            if not html_content:
                logger.info("Selenium unavailable, trying basic requests fetch")
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                html_content = response.content

            soup = BeautifulSoup(html_content, "html.parser")
            players = self._parse_adp_table(soup, scoring_format)

            logger.info(f"Fetched {len(players)} players from DraftSharks for {scoring_format}")
            return players

        except Exception as e:
            logger.error(f"Failed to fetch DraftSharks ADP data: {e}")
            return []

    def _fetch_with_selenium(self, url: str) -> Optional[str]:
        """Fetch page content using Selenium for JavaScript rendering.

        DraftSharks only renders the first ~25 players on initial load; the
        rest are lazy-loaded as the table is scrolled. We repeatedly scroll
        the table container to the bottom and wait for the player-row tbody
        count to stop growing (capped at MAX_PLAYERS) before returning.

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

            options = webdriver.ChromeOptions()
            options.add_argument("--headless")
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-dev-shm-usage")
            options.add_argument("--disable-gpu")
            options.add_argument("--disable-extensions")
            options.add_argument("--disable-plugins")
            options.add_argument("--disable-sync")
            options.add_argument("--disable-background-networking")
            options.add_argument("--disable-breakpad")
            options.add_argument("--disable-client-side-phishing-detection")

            driver = webdriver.Chrome(options=options)
            driver.set_page_load_timeout(45)
            driver.set_script_timeout(45)

            try:
                logger.debug("Navigating to URL...")
                driver.get(url)
                logger.debug("Page loaded, waiting for player rows to render...")

                table_found = False
                try:
                    wait = WebDriverWait(driver, 20)
                    wait.until(
                        EC.presence_of_element_located(
                            (By.CSS_SELECTOR, "#rankingsTable tbody[data-player-row]")
                        )
                    )

                    row_count = self._scroll_to_load_all_rows(driver)
                    logger.debug(f"Player rows stabilized: {row_count} rows")
                    table_found = True
                except Exception as wait_error:
                    logger.warning(
                        f"Table timeout after 20s: {type(wait_error).__name__}. Attempting fallback..."
                    )

                html_content = driver.page_source
                if html_content and len(html_content) > 5000:
                    logger.debug(
                        f"Got page HTML ({len(html_content)} bytes)"
                        + (" - table found" if table_found else " - table not found, but returning anyway")
                    )
                    return html_content
                else:
                    logger.warning(f"Page HTML too small ({len(html_content)} bytes), likely blank or error")
                    return None

            except Exception as e:
                logger.error(f"Selenium page navigation failed: {type(e).__name__}: {e}")
                try:
                    html = driver.page_source
                    if len(html) > 1000:
                        logger.info(f"Last resort: returning partial HTML ({len(html)} bytes)")
                        return html
                except Exception:
                    pass
                return None

            finally:
                driver.quit()

        except Exception as e:
            logger.error(f"Selenium initialization/fetch failed: {type(e).__name__}: {e}")
            return None

    def _scroll_to_load_all_rows(
        self,
        driver,
        required_stable_reads: int = 4,
        poll_interval: float = 1.0,
        max_total_wait: float = 45.0,
    ) -> int:
        """Trigger DraftSharks' lazy-loaded player rows and wait for them to settle.

        A single scroll trigger appears to cause the site to render its full
        player list (observed ~980 rows across all positions incl. IDP)
        client-side in one batch, but that render isn't always instantaneous -
        polling for a fixed "did it grow in N seconds" was unreliable because
        it could catch the count mid-batch. Instead we poll the row count on
        an interval and require several consecutive identical reads before
        trusting it's finished, re-scrolling each time it hasn't stabilized
        yet, bounded by max_total_wait as a safety net.

        Args:
            driver: Active Selenium webdriver
            required_stable_reads: Consecutive identical counts needed to finish
            poll_interval: Seconds between polls
            max_total_wait: Overall time budget before giving up

        Returns:
            Final count of loaded player-row tbodies
        """
        from selenium.webdriver.common.by import By
        import time

        selector = "#rankingsTable tbody[data-player-row]"
        # rankingsTableContainer has a "hide-scrollbars" class, indicating it's
        # an internally-scrollable div (its own overflow), not the page body -
        # scroll it directly rather than relying solely on window.scrollTo.
        scroll_container_ids = ["rankingsTableContainer", "table-container"]

        def _trigger_scroll():
            for container_id in scroll_container_ids:
                driver.execute_script(
                    "var el = document.getElementById(arguments[0]); "
                    "if (el) { el.scrollTop = el.scrollHeight; }",
                    container_id,
                )
            driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

        _trigger_scroll()

        deadline = time.monotonic() + max_total_wait
        last_count = -1
        stable_reads = 0

        while time.monotonic() < deadline:
            count = len(driver.find_elements(By.CSS_SELECTOR, selector))
            stable_reads = stable_reads + 1 if count == last_count else 0
            last_count = count

            if stable_reads >= required_stable_reads:
                break

            _trigger_scroll()
            time.sleep(poll_interval)

        return last_count

    def _save_players_json(self, players: List[Player], scoring_format: str) -> None:
        """Save parsed players to JSON file for debugging.

        Args:
            players: List of Player objects that were parsed
            scoring_format: The scoring format (ppr, half_ppr, standard)
        """
        try:
            debug_dir = PROJECT_ROOT / "debug_html"
            debug_dir.mkdir(exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = debug_dir / f"{scoring_format}_{timestamp}_players.json"

            players_data = [
                {
                    "player_name": p.player_name,
                    "position": p.position,
                    "team": p.team,
                    "adp_overall": p.adp_overall,
                    "adp_by_position": p.adp_by_position,
                    "round": p.round,
                    "scoring_format": p.scoring_format,
                    "tier": p.tier,
                    "positional_tier": p.positional_tier,
                }
                for p in players
            ]

            with open(filename, "w", encoding="utf-8") as f:
                json.dump(players_data, f, indent=2)

            logger.info(f"Saved {len(players)} players to: {filename}")
        except Exception as e:
            logger.debug(f"Failed to save players JSON file: {e}")

    def _save_html_debug(self, html_content: str, scoring_format: str, filename_suffix: str = "") -> None:
        """Save HTML content to a local file for debugging.

        Args:
            html_content: The HTML to save
            scoring_format: The scoring format (ppr, half_ppr, standard)
            filename_suffix: Optional suffix for the filename
        """
        try:
            debug_dir = PROJECT_ROOT / "debug_html"
            debug_dir.mkdir(exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            suffix = f"_{filename_suffix}" if filename_suffix else ""
            filename = debug_dir / f"{scoring_format}_{timestamp}{suffix}.html"

            with open(filename, "w", encoding="utf-8") as f:
                f.write(html_content)

            logger.info(f"Saved HTML debug file: {filename}")
        except Exception as e:
            logger.debug(f"Failed to save HTML debug file: {e}")

    def _parse_adp_table(self, soup, scoring_format: str) -> List[Player]:
        """Parse the ADP + tier table from DraftSharks HTML.

        DraftSharks renders one `<tbody data-player-row ...>` per player, with
        the player's overall and positional tier already attached as
        `data-tier-overall`/`data-tier-positional` attributes on that same
        tbody - so unlike FantasyPros's flat "tier-row" dividers, no stateful
        tier-tracking is needed while walking the rows. Non-player tbodies
        (tier dividers) lack `data-player-row` and are skipped outright.

        Args:
            soup: BeautifulSoup object of the page
            scoring_format: The scoring format being parsed

        Returns:
            List of Player objects
        """
        players: List[Player] = []

        table = soup.find("table", {"id": "rankingsTable"})
        if not table:
            logger.warning("Could not find rankingsTable on DraftSharks page")
            return []

        player_rows = table.find_all("tbody", attrs={"data-player-row": True})
        if not player_rows:
            logger.warning("Could not find any player rows in rankingsTable")
            return []

        for tbody in player_rows:
            try:
                player_name = tbody.get("data-player-name")
                position = tbody.get("data-fantasy-position")
                if not player_name or not position:
                    continue

                tier = int(tbody.get("data-tier-overall", 0) or 0)
                positional_tier = int(tbody.get("data-tier-positional", 0) or 0)

                team_el = tbody.find(class_="player-details-group__team-name")
                team = team_el.text.strip().upper() if team_el else "UNK"

                adp_cell = tbody.find("td", attrs={"data-attribute": "adp"})
                if not adp_cell or not adp_cell.get("data-value"):
                    continue
                round_num, adp_overall = self._parse_round_pick_adp(adp_cell["data-value"])

                if adp_overall is None or not (1 <= adp_overall <= 500):
                    continue

                adp_by_position = self._extract_positional_rank(tbody, position)

                player = Player(
                    player_name=player_name,
                    position=position,
                    team=team,
                    adp_overall=adp_overall,
                    adp_by_position=adp_by_position,
                    round=round_num,
                    scoring_format=scoring_format,
                    updated_at=datetime.utcnow(),
                    tier=tier,
                    positional_tier=positional_tier,
                )

                players.append(player)
                logger.debug(
                    f"Parsed player: {player_name} ({position}) - ADP: {adp_overall:.1f} "
                    f"- Tier: {tier} - Positional Tier: {positional_tier}"
                )

            except (ValueError, TypeError, KeyError) as e:
                logger.debug(f"Skipped player row: {e}")
                continue

        return players

    LEAGUE_SIZE = 12

    def _parse_round_pick_adp(self, raw_value: str) -> tuple:
        """Convert DraftSharks' "round.pick" ADP notation to (round, overall_pick).

        DraftSharks encodes ADP as Round.Pick for a 12-team league (e.g. "1.04"
        is round 1, pick 4; "2.01" is round 2, pick 1 - the pick component
        rolls over to the next round after 12, per LEAGUE_SIZE). This is not a
        straight overall pick number, so it must be converted before use as
        Player.adp_overall - the ADP-delta convention elsewhere in this app
        assumes a true overall pick value.

        Args:
            raw_value: The raw "data-value" string from the ADP cell, e.g. "2.1"

        Returns:
            (round_num, overall_pick) as (int, float), or (None, None) if unparseable
        """
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return None, None

        round_num = int(value)
        pick_in_round = round((value - round_num) * 100)
        overall_pick = (round_num - 1) * self.LEAGUE_SIZE + pick_in_round

        return round_num, float(overall_pick)

    def _extract_positional_rank(self, tbody, position: str) -> int:
        """Extract positional rank (e.g. 1 from "WR1") from a player's tbody.

        Args:
            tbody: The player's `<tbody data-player-row>` element
            position: The player's position, used to strip the leading letters

        Returns:
            1-indexed positional rank, or 0 if it can't be parsed
        """
        pill = tbody.find("pos-roster-spot")
        if not pill:
            return 0

        match = re.search(r"(\d+)\s*$", pill.text.strip())
        return int(match.group(1)) if match else 0

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
                    updated_at=datetime.fromisoformat(p["updated_at"]),
                    tier=p.get("tier", 0),
                    positional_tier=p.get("positional_tier", 0),
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
                    "updated_at": p.updated_at.isoformat(),
                    "tier": p.tier,
                    "positional_tier": p.positional_tier,
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
