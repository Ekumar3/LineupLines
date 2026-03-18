"""Sleeper Fantasy Football API client.

Provides integration with Sleeper's public API for live draft tracking
and league data retrieval.
"""

import logging
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from datetime import datetime
import time

logger = logging.getLogger(__name__)


@dataclass
class DraftPick:
    """Represents a single draft pick."""
    pick_no: int
    draft_id: str
    user_id: str
    player_id: str
    player_name: str
    position: str
    team: str
    round: int
    timestamp: datetime


@dataclass
class DraftStatus:
    """Current status of a draft."""
    draft_id: str
    league_id: str
    status: str  # "pre_draft", "in_progress", "complete"
    current_pick: int
    total_picks_made: int
    is_live: bool
    settings: Dict[str, Any]


class SleeperClient:
    """Client for Sleeper Fantasy Football API.

    Provides methods for:
    - Fetching live draft picks
    - Getting draft metadata
    - Retrieving player universe
    - Accessing league information
    """

    BASE_URL = "https://api.sleeper.app/v1"
    RATE_LIMIT_DELAY = 0.1  # Seconds between requests (1000/min = 16.7/sec)

    def __init__(self, rate_limit_delay: float = 0.1):
        """Initialize the Sleeper client.

        Args:
            rate_limit_delay: Minimum delay between API requests (seconds)
        """
        self.rate_limit_delay = rate_limit_delay
        self.last_request_time = 0
        self._player_cache: Optional[Dict[str, Dict[str, Any]]] = None
        self._player_cache_time: Optional[datetime] = None
        self._scoring_format_cache: Dict[str, Optional[str]] = {}

    def get_draft_picks(self, draft_id: str) -> List[DraftPick]:
        """Fetch all picks from a draft.

        Args:
            draft_id: The draft ID from Sleeper

        Returns:
            List of DraftPick objects, ordered by pick number

        Raises:
            Exception: If API request fails
        """
        logger.info(f"Fetching picks for draft {draft_id}")

        try:
            response = self._make_request(f"/draft/{draft_id}/picks")
            picks = response if isinstance(response, list) else []

            draft_picks = []
            for pick_data in picks:
                if pick_data.get("player_id") is None:
                    continue  # Skip unpicked slots

                # Get user_id from picked_by field (comes as int or str from Sleeper)
                user_id = pick_data.get("picked_by")
                user_id_str = str(user_id) if user_id else ""

                pick = DraftPick(
                    pick_no=pick_data.get("pick_no", 0),
                    draft_id=draft_id,
                    user_id=user_id_str,
                    player_id=pick_data.get("player_id", ""),
                    player_name=self._get_player_name(pick_data.get("player_id", "")),
                    position=self._get_player_position(pick_data.get("player_id", "")),
                    team=self._get_player_team(pick_data.get("player_id", "")),
                    round=pick_data.get("round", self._calculate_round(pick_data.get("pick_no", 0))),
                    timestamp=datetime.fromisoformat(
                        pick_data.get("timestamp", datetime.now().isoformat()).rstrip("Z")
                    ) if pick_data.get("timestamp") else datetime.now()
                )
                draft_picks.append(pick)

            logger.info(f"Fetched {len(draft_picks)} picks from draft {draft_id}")
            return draft_picks

        except Exception as e:
            logger.error(f"Failed to fetch draft picks: {e}")
            return []

    def get_draft_status(self, draft_id: str) -> Optional[DraftStatus]:
        """Get the current status of a draft.

        Args:
            draft_id: The draft ID from Sleeper

        Returns:
            DraftStatus object or None if fetch fails
        """
        logger.info(f"Fetching status for draft {draft_id}")

        try:
            response = self._make_request(f"/draft/{draft_id}")

            if not response:
                return None

            # Determine draft status
            status_str = response.get("status", "pre_draft")
            picks_made = len(
                [p for p in response.get("draft_order", []) if p is not None]
            )

            draft_status = DraftStatus(
                draft_id=draft_id,
                league_id=response.get("league_id", ""),
                status=status_str,
                current_pick=response.get("draft_order", []).index(None) if None in response.get("draft_order", []) else 0,
                total_picks_made=picks_made,
                is_live=status_str == "in_progress",
                settings={
                    "rounds": response.get("settings", {}).get("rounds", 15),
                    "teams": response.get("settings", {}).get("teams", 12),
                    "type": response.get("type", "")
                }
            )

            return draft_status

        except Exception as e:
            logger.error(f"Failed to fetch draft status: {e}")
            return None

    def get_draft_details(self, draft_id: str) -> Optional[Dict[str, Any]]:
        """Get complete draft details including roster mapping.

        Args:
            draft_id: The draft ID from Sleeper

        Returns:
            Dict with draft details (draft_order, settings, metadata, etc.) or None if fetch fails
        """
        logger.info(f"Fetching details for draft {draft_id}")

        try:
            response = self._make_request(f"/draft/{draft_id}")

            if not response:
                return None

            # Normalize all IDs to strings for consistency across the API
            # Sleeper API returns draft_order with user_ids (int or str),
            # and slot_to_roster_id with roster_ids (int), so we normalize to strings
            raw_draft_order = response.get("draft_order", [])
            
            draft_order = [""] * response.get("settings", {}).get("teams", 12)  # Default empty slots
            for user_id, slot_index in raw_draft_order.items():
                draft_order[int(slot_index) - 1] = str(user_id)

            # Build roster_to_user mapping: roster_id (str) -> user_id (str)
            # slot_to_roster_id from Sleeper: slot_num (str) -> roster_id (int)
            # draft_order from Sleeper: list indexed by slot_num with user_ids
            roster_to_user = {}

            for slot_id_str, roster_id_int in response.get("slot_to_roster_id", {}).items():
                slot_index = int(slot_id_str)  # Convert slot string to list index
                if slot_index < len(draft_order):
                    user_at_slot = draft_order[slot_index]
                    if user_at_slot:
                        # Store as: roster_id (string) -> user_id (string)
                        roster_to_user[str(roster_id_int)] = user_at_slot

            return {
                "draft_id": draft_id,
                "league_id": response.get("league_id", ""),
                "status": response.get("status", "pre_draft"),
                "settings": {
                    "teams": response.get("settings", {}).get("teams", 12),
                    "rounds": response.get("settings", {}).get("rounds", 15),
                    "reversal_round": response.get("settings", {}).get("reversal_round"),
                    "type": response.get("type", ""),
                },
                "metadata": {
                    "name": response.get("metadata", {}).get("name"),
                    "scoring_type": response.get("metadata", {}).get("scoring_type"),
                },
                "draft_order": draft_order,
                "roster_to_user": roster_to_user,
            }

        except Exception as e:
            logger.error(f"Failed to fetch draft details: {e}")
            return None

    def poll_draft_picks(
        self,
        draft_id: str,
        poll_interval: float = 5.0,
        max_polls: Optional[int] = None
    ) -> None:
        """Poll a draft for new picks (for live tracking).

        Args:
            draft_id: The draft ID from Sleeper
            poll_interval: Seconds to wait between polls
            max_polls: Maximum number of polls, or None for infinite
        """
        logger.info(f"Starting live draft polling for {draft_id}")

        picks_seen = 0
        poll_count = 0

        try:
            while max_polls is None or poll_count < max_polls:
                picks = self.get_draft_picks(draft_id)
                new_picks = picks[picks_seen:]

                if new_picks:
                    logger.info(f"[LIVE] {len(new_picks)} new picks:")
                    for pick in new_picks:
                        logger.info(
                            f"  Pick {pick.pick_no} (Round {pick.round}): "
                            f"{pick.player_name} ({pick.position}) "
                            f"drafted by roster {pick.roster_id}"
                        )
                    picks_seen = len(picks)

                status = self.get_draft_status(draft_id)
                if status and status.status == "complete":
                    logger.info("Draft is complete, stopping poll")
                    break

                poll_count += 1
                time.sleep(poll_interval)

        except KeyboardInterrupt:
            logger.info("Live draft polling stopped by user")
        except Exception as e:
            logger.error(f"Error during draft polling: {e}")

    def get_user(self, username: str) -> Optional[Dict[str, Any]]:
        """Get user information by username.

        Args:
            username: Sleeper username

        Returns:
            Dictionary with user data (includes user_id) or None if fetch fails

        Example response structure:
        {
            "user_id": "123456789",
            "username": "sleeperuser",
            "display_name": "Sleeper User",
            "avatar": "https://...",
            "verified": False
        }
        """
        logger.info(f"Fetching user info for username: {username}")

        try:
            response = self._make_request(f"/user/{username}")
            return response if isinstance(response, dict) else None
        except Exception as e:
            logger.error(f"Failed to fetch user info for {username}: {e}")
            return None

    def get_league_info(self, league_id: str) -> Optional[Dict[str, Any]]:
        """Get league information.

        Args:
            league_id: The league ID from Sleeper

        Returns:
            Dictionary with league data or None if fetch fails
        """
        try:
            return self._make_request(f"/league/{league_id}")
        except Exception as e:
            logger.error(f"Failed to fetch league info: {e}")
            return None

    def get_scoring_format(self, league_id: str) -> Optional[str]:
        """Determine scoring format from league settings.

        Maps Sleeper's reception points to standard scoring formats:
        - 1.0 points per reception = PPR
        - 0.5 points per reception = Half-PPR
        - 0.0 points per reception = Standard

        Args:
            league_id: The league ID from Sleeper

        Returns:
            One of "ppr", "half_ppr", "standard", or None if cannot determine
        """
        if league_id in self._scoring_format_cache:
            return self._scoring_format_cache[league_id]

        league_info = self.get_league_info(league_id)
        if not league_info:
            self._scoring_format_cache[league_id] = None
            return None

        scoring_settings = league_info.get("scoring_settings", {})
        rec_points = scoring_settings.get("rec", 0)

        # Map reception points to format
        if rec_points == 1.0:
            result = "ppr"
        elif rec_points == 0.5:
            result = "half_ppr"
        elif rec_points == 0.0:
            result = "standard"
        else:
            # Custom scoring - default to closest match
            if rec_points > 0.75:
                result = "ppr"
            elif rec_points > 0.25:
                result = "half_ppr"
            else:
                result = "standard"

        self._scoring_format_cache[league_id] = result
        return result

    def get_league_drafts(self, league_id: str) -> List[Dict[str, Any]]:
        """Get all drafts for a league.

        Args:
            league_id: The league ID from Sleeper

        Returns:
            List of draft metadata dictionaries
        """
        try:
            response = self._make_request(f"/league/{league_id}/drafts")
            return response if isinstance(response, list) else []
        except Exception as e:
            logger.error(f"Failed to fetch league drafts: {e}")
            return []

    def get_user_drafts(
        self, user_id: str, sport: str = "nfl", season: str = "2026"
    ) -> List[Dict[str, Any]]:
        """Get all drafts for a user in a specific sport and season.

        Args:
            user_id: Sleeper user ID
            sport: Sport type (default: "nfl")
            season: Season year (default: "2026")

        Returns:
            List of draft objects with metadata, or empty list on error

        Example response structure:
        [
            {
                "draft_id": "123456789",
                "league_id": "987654321",
                "status": "in_progress",
                "type": "snake",
                "sport": "nfl",
                "season": "2026",
                "start_time": 1735689600000,
                "settings": {"teams": 12, "rounds": 15},
                "metadata": {"name": "My League", "scoring_type": "ppr"}
            }
        ]
        """
        logger.info(f"Fetching drafts for user {user_id} (sport={sport}, season={season})")

        try:
            endpoint = f"/user/{user_id}/drafts/{sport}/{season}"
            response = self._make_request(endpoint)
            return response if isinstance(response, list) else []
        except Exception as e:
            logger.error(f"Failed to fetch user drafts for {user_id}: {e}")
            return []

    def get_players(self, force_refresh: bool = False) -> Dict[str, Dict[str, Any]]:
        """Get the complete NFL player universe.

        Results are cached for 24 hours.

        Args:
            force_refresh: If True, bypass cache and fetch fresh data

        Returns:
            Dictionary mapping player_id to player data
        """
        # Check cache
        if (
            not force_refresh
            and self._player_cache is not None
            and self._player_cache_time is not None
        ):
            age_seconds = (datetime.now() - self._player_cache_time).total_seconds()
            if age_seconds < 86400:  # 24 hours
                logger.info("Using cached player universe")
                return self._player_cache

        logger.info("Fetching player universe from Sleeper")

        try:
            response = self._make_request("/players/nfl")

            if isinstance(response, dict):
                self._player_cache = response
                self._player_cache_time = datetime.now()
                logger.info(f"Cached {len(response)} players")
                return response

            return {}

        except Exception as e:
            logger.error(f"Failed to fetch player universe: {e}")
            return self._player_cache or {}

    def _get_player_name(self, player_id: str) -> str:
        """Get player name from cached universe."""
        if not self._player_cache:
            self.get_players()

        if self._player_cache and player_id in self._player_cache:
            player = self._player_cache[player_id]
            first = player.get("first_name", "")
            last = player.get("last_name", "")
            return f"{first} {last}".strip() or f"Player {player_id}"

        return f"Player {player_id}"

    def _get_player_position(self, player_id: str) -> str:
        """Get player position from cached universe."""
        if not self._player_cache:
            self.get_players()

        if self._player_cache and player_id in self._player_cache:
            position = self._player_cache[player_id].get("position")
            return position if position else "UNKNOWN"

        return "UNKNOWN"

    def _get_player_team(self, player_id: str) -> str:
        """Get player team from cached universe."""
        if not self._player_cache:
            self.get_players()

        if self._player_cache and player_id in self._player_cache:
            team = self._player_cache[player_id].get("team")
            return team if team else "FA"

        return "FA"

    def _calculate_round(self, pick_no: int) -> int:
        """Calculate round number from pick number (assumes 12 teams)."""
        if pick_no <= 0:
            return 0
        return ((pick_no - 1) // 12) + 1

    def _make_request(self, endpoint: str, timeout: float = 30) -> Any:
        """Make a GET request to the Sleeper API.

        Args:
            endpoint: API endpoint (e.g., "/draft/123")
            timeout: Request timeout in seconds

        Returns:
            Parsed JSON response

        Raises:
            Exception: If request fails
        """
        # Rate limiting
        elapsed = time.time() - self.last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)

        url = f"{self.BASE_URL}{endpoint}"

        try:
            import requests

            response = requests.get(url, timeout=timeout)
            response.raise_for_status()

            self.last_request_time = time.time()

            return response.json() if response.text else None

        except ImportError:
            logger.error("requests library required. Install with: pip install requests")
            raise

        except Exception as e:
            logger.error(f"API request failed to {url}: {e}")
            raise

    def clear_cache(self) -> None:
        """Clear cached data (player universe)."""
        self._player_cache = None
        self._player_cache_time = None
        logger.info("Cleared Sleeper client cache")
