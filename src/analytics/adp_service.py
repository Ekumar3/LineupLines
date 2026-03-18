"""ADP Service - Manages ADP data fetching and caching for draft recommendations.

This service layer coordinates ADP data from FantasyPros with player availability
to calculate value scores and enhance draft recommendations.
"""

import logging
from typing import Dict, List, Optional
from datetime import datetime, timedelta

from src.data_sources.fantasypros_client import FantasyProsClient
from src.analytics.adp_analyzer import ADPAnalyzer

logger = logging.getLogger(__name__)


class ADPService:
    """Service for managing ADP data lifecycle.

    Handles:
    - Fetching and caching ADP data by scoring format (24-hour TTL)
    - Looking up individual player ADP values
    - Calculating value deltas (actual pick vs. ADP)
    - Computing positional value scores combining scarcity and individual value
    """

    def __init__(self):
        """Initialize ADP service with dependencies."""
        self.fp_client = FantasyProsClient()
        self.analyzers: Dict[str, ADPAnalyzer] = {}  # Format -> Analyzer
        self.last_refresh: Dict[str, datetime] = {}
        self.cache_duration = timedelta(hours=24)

    def get_adp_data(self, scoring_format: str, force_refresh: bool = False) -> Optional[List]:
        """Get ADP data for a scoring format, using cache if available.

        Args:
            scoring_format: One of "ppr", "half_ppr", "standard"
            force_refresh: Force fetch from FantasyPros, bypassing cache

        Returns:
            List of Player objects with ADP data, or None if fetch fails
        """
        # Check cache freshness
        if not force_refresh and scoring_format in self.last_refresh:
            age = datetime.utcnow() - self.last_refresh[scoring_format]
            if age < self.cache_duration:
                cached = self.fp_client.get_cached_data(scoring_format)
                if cached:
                    logger.info(f"Using cached ADP data for {scoring_format} (age: {age.total_seconds():.0f}s)")
                    return cached

        # Fetch fresh data
        logger.info(f"Fetching fresh ADP data for {scoring_format}")
        try:
            players = self.fp_client.fetch_adp_data(scoring_format)

            if players:
                self.last_refresh[scoring_format] = datetime.utcnow()

                # Run analysis to populate analyzer with tier data
                analyzer = ADPAnalyzer()
                analyzer.analyze(players)
                self.analyzers[scoring_format] = analyzer

                logger.info(f"Successfully fetched {len(players)} players for {scoring_format} ADP")

            return players
        except Exception as e:
            logger.error(f"Failed to fetch ADP data for {scoring_format}: {e}")
            return None

    def get_analyzer(self, scoring_format: str) -> Optional[ADPAnalyzer]:
        """Get ADP analyzer for a scoring format.

        Ensures data is loaded before returning analyzer.

        Args:
            scoring_format: One of "ppr", "half_ppr", "standard"

        Returns:
            ADPAnalyzer instance or None if data unavailable
        """
        # Ensure data is loaded
        if scoring_format not in self.analyzers:
            self.get_adp_data(scoring_format)

        return self.analyzers.get(scoring_format)

    def get_adp_lookup(self, scoring_format: str) -> Dict[str, float]:
        """Build a normalized name -> ADP lookup dict for fast bulk lookups.

        Args:
            scoring_format: One of "ppr", "half_ppr", "standard"

        Returns:
            Dict mapping lowercase player name to ADP overall value
        """
        players = self.get_adp_data(scoring_format)
        if not players:
            return {}

        lookup = {}
        for player in players:
            name = getattr(player, "player_name", None)
            if not name:
                continue
            normalized = name.lower().strip()
            if "(" in normalized:
                normalized = normalized[: normalized.rfind("(")].strip()
            adp = getattr(player, "adp_overall", None)
            if adp is not None:
                lookup[normalized] = adp
        return lookup

    def get_player_adp(self, player_name: str, scoring_format: str) -> Optional[float]:
        """Get ADP for a specific player by name.

        Performs case-insensitive matching on player names.
        Handles both "Player Name" and "Player Name (TEAM)" formats.

        Args:
            player_name: Player's full name (e.g., "Christian McCaffrey" or "Christian McCaffrey (SF)")
            scoring_format: Scoring format (ppr, half_ppr, standard)

        Returns:
            ADP overall pick number (e.g., 3.5) or None if not found
        """
        try:
            players = self.get_adp_data(scoring_format)
            if not players:
                return None

            # Normalize search name - remove team if present
            normalized_name = player_name.lower().strip()
            # Remove team abbreviation in parentheses if present
            if "(" in normalized_name:
                normalized_name = normalized_name[: normalized_name.rfind("(")].strip()

            for player in players:
                player_match_name = getattr(player, "player_name", None)
                if not player_match_name:
                    continue

                # Normalize database name - remove team abbreviation
                db_name = player_match_name.lower().strip()
                if "(" in db_name:
                    db_name = db_name[: db_name.rfind("(")].strip()

                # Match if names are equal
                if db_name == normalized_name:
                    return getattr(player, "adp_overall", None)

            logger.debug(f"Player '{player_name}' not found in {scoring_format} ADP data")
            return None
        except Exception as e:
            logger.error(f"Error looking up ADP for {player_name}: {e}")
            return None

    def calculate_value_delta(self, current_pick: int, player_adp: float) -> float:
        """Calculate value delta (position relative to ADP).

        Returns positive number if player typically goes later (good value).
        Returns negative number if reaching (player typically goes earlier).

        Args:
            current_pick: Current pick number in draft
            player_adp: Player's ADP overall pick

        Returns:
            Delta in picks (ADP - current_pick)
            Positive = value (picking earlier than ADP)
            Negative = reach (picking later than ADP)
        """
        return player_adp - current_pick

    def calculate_positional_value(
        self,
        position: str,
        current_pick: int,
        available_players: List[Dict],
        scoring_format: str
    ) -> float:
        """Calculate positional value score.

        Combines position scarcity with best available value at position.
        Higher score = better value opportunity at this position.

        Formula: (Scarcity * 50) + Best Value Delta
        - Scarcity ranges 0-1, multiplied by 50 to make comparable to pick deltas
        - Value delta can be large positive (great value) or negative (reaching)

        Args:
            position: Position code (QB, RB, WR, TE, K, DEF)
            current_pick: Current pick number in draft
            available_players: List of dicts with "name" key for players at this position
            scoring_format: Scoring format (ppr, half_ppr, standard)

        Returns:
            Value score (higher = better value opportunity)
            Typical range: -20 to 50+ (negative = reaches, >30 = exceptional value)
        """
        # Ensure ADP data and analyzer are loaded
        analyzer = self.get_analyzer(scoring_format)
        if not analyzer:
            logger.warning(f"No analyzer available for {scoring_format}")
            return 0.0

        if not available_players:
            return 0.0

        # Check top 5 available players at position for best value
        best_value = 0.0
        for player in available_players[:5]:
            try:
                player_name = player.get("name", "")
                if not player_name:
                    continue

                adp = self.get_player_adp(player_name, scoring_format)
                if adp:
                    value_delta = self.calculate_value_delta(current_pick, adp)
                    if value_delta > best_value:
                        best_value = value_delta
                        logger.debug(f"Found {position} value: {player_name} ({value_delta:.1f} picks ahead)")
            except Exception as e:
                logger.debug(f"Error checking value for player in {position}: {e}")
                continue

        # Get position scarcity (0-1 range)
        try:
            scarcity = analyzer.get_positional_scarcity(position, len(available_players))
        except Exception as e:
            logger.warning(f"Could not calculate scarcity for {position}: {e}")
            scarcity = 0.5

        # Combine: scarcity * 50 + value_delta
        # This makes scarcity comparable to ~5 round ADP delta
        final_value_score = (scarcity * 50) + best_value

        logger.debug(
            f"{position} value score: {final_value_score:.1f} "
            f"(scarcity={scarcity:.2f}, best_value={best_value:.1f})"
        )

        return final_value_score


# Global singleton instance
adp_service = ADPService()
