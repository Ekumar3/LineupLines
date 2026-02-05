"""ADP analyzer for generating draft recommendations.

Processes Average Draft Position data to identify patterns, archetypes,
and value opportunities.
"""

import logging
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from collections import defaultdict
from src.data_sources.fantasypros_client import Player

logger = logging.getLogger(__name__)


@dataclass
class RoundPattern:
    """Pattern data for a specific round."""
    round_num: int
    position_frequencies: Dict[str, int]  # {"QB": 1, "RB": 8, "WR": 2, "TE": 1}
    top_picks: List[str]  # Top player names for this round
    average_adp: float


@dataclass
class PositionalTier:
    """Represents a tier break in positional draft."""
    position: str
    tier_num: int
    pick_range: Tuple[int, int]  # (start_pick, end_pick)
    avg_adp_gap: float


@dataclass
class ValueRound:
    """Round with particular value for a position."""
    round_num: int
    position: str
    value_score: float  # Higher = more valuable
    reasoning: str


class ADPAnalyzer:
    """Analyzes ADP data to generate draft recommendations."""

    POSITIONS = ["QB", "RB", "WR", "TE", "K", "DEF"]
    STANDARD_ROUNDS = 15
    TEAMS_PER_LEAGUE = 12

    def __init__(self):
        """Initialize the ADP analyzer."""
        self.adp_data: Optional[List[Player]] = None
        self.round_patterns: Dict[int, RoundPattern] = {}
        self.positional_tiers: Dict[str, List[PositionalTier]] = {}
        self.value_rounds: List[ValueRound] = []

    def analyze(self, players: List[Player]) -> None:
        """Run complete analysis on ADP data.

        Args:
            players: List of Player objects with ADP data
        """
        if not players:
            logger.warning("No players to analyze")
            return

        self.adp_data = players
        logger.info(f"Starting analysis of {len(players)} players")

        self._calculate_round_patterns()
        self._identify_positional_tiers()
        self._calculate_value_rounds()

        logger.info("Analysis complete")

    def _calculate_round_patterns(self) -> None:
        """Calculate which positions are drafted in each round."""
        if not self.adp_data:
            return

        round_data: Dict[int, Dict[str, List[Player]]] = defaultdict(
            lambda: defaultdict(list)
        )

        # Group players by round and position
        for player in self.adp_data:
            round_data[player.round][player.position].append(player)

        # Calculate patterns for each round
        for round_num in range(1, self.STANDARD_ROUNDS + 1):
            players_in_round = round_data.get(round_num, {})

            position_frequencies = {}
            top_picks = []

            for position in self.POSITIONS:
                position_players = players_in_round.get(position, [])
                position_frequencies[position] = len(position_players)

                # Get top players for this position in this round
                if position_players:
                    top_picks.extend([p.player_name for p in position_players[:2]])

            # Calculate average ADP for round
            all_round_players = [
                p for pos_players in players_in_round.values()
                for p in pos_players
            ]
            avg_adp = (
                sum(p.adp_overall for p in all_round_players) / len(all_round_players)
                if all_round_players
                else 0
            )

            self.round_patterns[round_num] = RoundPattern(
                round_num=round_num,
                position_frequencies=position_frequencies,
                top_picks=top_picks[:5],
                average_adp=avg_adp
            )

    def _identify_positional_tiers(self) -> None:
        """Identify tier breaks in positional drafts."""
        if not self.adp_data:
            return

        for position in self.POSITIONS:
            position_players = [
                p for p in self.adp_data if p.position == position
            ]

            if not position_players:
                continue

            # Sort by ADP
            position_players.sort(key=lambda p: p.adp_overall)

            tiers = []
            tier_num = 1
            prev_adp = 0

            for i, player in enumerate(position_players):
                adp_gap = player.adp_overall - prev_adp

                # Define tier break when ADP gap > 5 picks or every 10 players
                if (adp_gap > 5 or (i > 0 and i % 10 == 0)) and i > 0:
                    tier = PositionalTier(
                        position=position,
                        tier_num=tier_num,
                        pick_range=(
                            int(position_players[i - 1].adp_overall),
                            int(player.adp_overall)
                        ),
                        avg_adp_gap=adp_gap
                    )
                    tiers.append(tier)
                    tier_num += 1

                prev_adp = player.adp_overall

            # Add final tier
            if position_players:
                tiers.append(
                    PositionalTier(
                        position=position,
                        tier_num=tier_num,
                        pick_range=(
                            int(position_players[-1].adp_overall),
                            int(position_players[-1].adp_overall) + 5
                        ),
                        avg_adp_gap=0
                    )
                )

            self.positional_tiers[position] = tiers

    def _calculate_value_rounds(self) -> None:
        """Identify rounds with value picks by position."""
        if not self.adp_data or not self.round_patterns:
            return

        value_rounds = []

        for round_num, pattern in self.round_patterns.items():
            for position in self.POSITIONS:
                freq = pattern.position_frequencies.get(position, 0)

                # Calculate value score
                # High frequency = more value (players available in this round)
                # Flat ADP in round = more value (more similar players)
                position_freq = sum(
                    1 for p in self.adp_data
                    if p.position == position and p.round == round_num
                )

                if position_freq == 0:
                    continue

                # Value score: how many top players available in this round
                max_freq = max(pattern.position_frequencies.values()) if pattern.position_frequencies else 0
                value_score = position_freq / max(max_freq, 1)

                # Scarcity bonus: round with few of this position is also valuable
                if position_freq < 2:
                    value_score *= 1.5

                reasoning = self._generate_value_reasoning(
                    round_num, position, value_score, position_freq
                )

                if value_score > 0.5:  # Only include significant value rounds
                    value_rounds.append(
                        ValueRound(
                            round_num=round_num,
                            position=position,
                            value_score=round(value_score, 2),
                            reasoning=reasoning
                        )
                    )

        # Sort by value score descending
        self.value_rounds = sorted(
            value_rounds, key=lambda v: v.value_score, reverse=True
        )

    def _generate_value_reasoning(
        self, round_num: int, position: str, value_score: float, player_count: int
    ) -> str:
        """Generate human-readable reasoning for a value round."""
        if value_score > 1.2:
            return (
                f"Strong value: {player_count} top {position}(s) typically drafted "
                f"in round {round_num}"
            )
        elif value_score > 0.8:
            return (
                f"Good value: Multiple {position} options available in round {round_num}"
            )
        else:
            return f"Decent depth for {position} in round {round_num}"

    def get_round_pattern(self, round_num: int) -> Optional[RoundPattern]:
        """Get the draft pattern for a specific round.

        Args:
            round_num: Round number (1-15)

        Returns:
            RoundPattern or None
        """
        return self.round_patterns.get(round_num)

    def get_position_tiers(self, position: str) -> List[PositionalTier]:
        """Get tier breaks for a specific position.

        Args:
            position: Position code (QB, RB, WR, TE, K, DEF)

        Returns:
            List of PositionalTier objects
        """
        return self.positional_tiers.get(position, [])

    def get_value_rounds_for_position(self, position: str) -> List[ValueRound]:
        """Get value rounds for a specific position.

        Args:
            position: Position code

        Returns:
            List of ValueRound objects, sorted by value_score descending
        """
        return [v for v in self.value_rounds if v.position == position]

    def get_position_frequency_by_round(self, round_num: int) -> Dict[str, int]:
        """Get position drafting frequency for a round.

        Args:
            round_num: Round number

        Returns:
            Dictionary mapping position to count
        """
        pattern = self.get_round_pattern(round_num)
        return pattern.position_frequencies if pattern else {}

    def get_positional_scarcity(self, position: str, picks_available: int) -> float:
        """Calculate scarcity score for a position.

        Args:
            position: Position code
            picks_available: Number of top-tier players still available

        Returns:
            Scarcity score 0-1 (1 = very scarce)
        """
        tiers = self.get_position_tiers(position)
        if not tiers:
            return 0.5

        # If fewer than tier 1 remaining, it's very scarce
        if picks_available < 5:
            return 0.9

        # If fewer than tier 2 remaining, it's moderately scarce
        if picks_available < 12:
            return 0.6

        # Otherwise, reasonable depth
        return 0.3

    def get_analysis_summary(self) -> Dict[str, any]:
        """Get a summary of the analysis results.

        Returns:
            Dictionary with analysis summary
        """
        return {
            "total_players_analyzed": len(self.adp_data) if self.adp_data else 0,
            "rounds_analyzed": len(self.round_patterns),
            "positions_with_tiers": len(self.positional_tiers),
            "value_rounds_identified": len(self.value_rounds),
            "top_value_round": (
                self.value_rounds[0] if self.value_rounds else None
            )
        }
