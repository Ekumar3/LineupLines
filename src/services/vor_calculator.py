"""
Value Over Replacement (VOR) Calculator for Fantasy Football Draft

VOR measures how much better a player is compared to a "replacement level" player.
This helps identify which positions offer the most value at different draft stages.

--- Projection-based VOR (preferred, when projections are available) ---
Formula:  VOR = player_projected_pts - next_player_projected_pts
Sorted by projected PPR points descending, so the "next player" is the best player
still available at that position who scores fewer projected points.

--- ADP-based VOR (fallback when no projection exists) ---
Formula:  VOR = next_player_adp - player_adp
Sorted by ADP ascending; the "next player" is the one right below in draft order.

In both cases a higher VOR means a bigger gap to the next option at this position.
"""

import json
import logging
from typing import List, Dict, Optional
from pathlib import Path
from statistics import median, quantiles

logger = logging.getLogger(__name__)


class VORCalculator:
    def __init__(self, players_file: str):
        """
        Initialize VOR calculator with player ADP data.

        Args:
            players_file: Path to players JSON file (e.g., data/players/ppr_20260205_163143_players.json)
        """
        self.players = self._load_players(players_file)
        self.position_groups = self._group_by_position()
        # Populated by load_projections(); maps position -> players sorted by proj pts desc
        self.projection_groups: Dict[str, List[Dict]] = {}
        
    def _load_players(self, file_path: str) -> List[Dict]:
        """Load and validate player data from JSON."""
        with open(file_path, 'r') as f:
            players = json.load(f)
        
        # Ensure all players have required fields
        required_fields = ['player_name', 'position', 'adp_overall']
        for player in players:
            for field in required_fields:
                if field not in player:
                    raise ValueError(f"Missing {field} in player data: {player}")
        
        return players
    
    def _group_by_position(self) -> Dict[str, List[Dict]]:
        """Group all players by position."""
        groups = {}
        for player in self.players:
            pos = player['position']
            if pos not in groups:
                groups[pos] = []
            groups[pos].append(player)
        
        # Sort each position by ADP
        for pos in groups:
            groups[pos].sort(key=lambda p: p['adp_overall'])
        
        return groups
    
    # ------------------------------------------------------------------
    # Projection support
    # ------------------------------------------------------------------

    def load_projections(self, projections_client) -> int:
        """
        Enrich the player pool with season projection data.

        Annotates each player in self.players with 'projected_pts' and builds
        self.projection_groups (position -> players sorted by projected_pts desc).

        Args:
            projections_client: A ProjectionsClient instance.

        Returns:
            Number of players successfully matched to a projection.
        """
        matched = 0
        for player in self.players:
            pts = projections_client.get_projected_points(
                player["player_name"],
                player["position"],
                team=player.get("team", ""),
                scoring="ppr",
            )
            if pts is not None:
                player["projected_pts"] = pts
                matched += 1
            else:
                player.pop("projected_pts", None)

        # Build projection_groups: only include players that have a projection
        groups: Dict[str, List[Dict]] = {}
        for player in self.players:
            if "projected_pts" not in player:
                continue
            pos = player["position"]
            groups.setdefault(pos, []).append(player)

        for pos in groups:
            groups[pos].sort(key=lambda p: p["projected_pts"], reverse=True)

        self.projection_groups = groups

        stats = {pos: len(v) for pos, v in groups.items()}
        logger.info(
            f"VORCalculator projections loaded: {matched} matched, "
            f"projection_groups coverage: {stats}"
        )
        return matched

    def get_next_projected_pts(
        self,
        position: str,
        player_pts: float,
        remaining_players: Optional[List[Dict]] = None,
    ) -> float:
        """
        Return projected points of the next available player below this one.

        Players are ordered by projected_pts descending (best first).  The
        "next" player is the first one whose projection is strictly less than
        player_pts.

        Args:
            position:         Player position.
            player_pts:       Projected PPR points for the player being evaluated.
            remaining_players: If provided, restrict to this undrafted pool.

        Returns:
            Projected points of the next player, or player_pts - 1.0 if this is
            the last player at the position (giving a VOR of 1.0 as a floor).
        """
        if remaining_players is not None:
            pool = [
                p for p in remaining_players
                if p.get("position") == position and "projected_pts" in p
            ]
            pool.sort(key=lambda p: p["projected_pts"], reverse=True)
        else:
            pool = self.projection_groups.get(position, [])

        for p in pool:
            if p["projected_pts"] < player_pts:
                return p["projected_pts"]

        return player_pts - 1.0  # floor: no one left to compare against

    def get_replacement_level(self, position: str, replacement_percentile: int = 50) -> float:
        """
        Calculate replacement level for a position.
        
        Args:
            position: Player position (e.g., 'WR', 'RB', 'TE', 'QB')
            replacement_percentile: Which percentile to use (50 = median, 25 = bottom quartile)
        
        Returns:
            ADP value representing replacement level
        """
        players_at_pos = self.position_groups.get(position, [])
        if not players_at_pos:
            raise ValueError(f"No players found for position {position}")
        
        adp_values = [p['adp_overall'] for p in players_at_pos]
        
        if replacement_percentile == 50:
            return median(adp_values)
        else:
            # Use quantiles for other percentiles
            # quantiles expects value between 0 and 1
            percentile_val = replacement_percentile / 100.0
            quants = quantiles(adp_values, n=100)  # 100 divisions = percentiles
            idx = int(percentile_val * (len(quants) - 1))
            return quants[idx]
    
    def get_next_player_adp(
        self,
        position: str,
        player_adp: float,
        remaining_players: Optional[List[Dict]] = None
    ) -> float:
        """
        Return the ADP of the next available player at this position after player_adp.

        This is the replacement level used for VOR: how much value do you lose
        if you skip this player and take the next one at this position?

        Args:
            position: Player position (e.g. 'TE', 'WR')
            player_adp: ADP of the player being evaluated
            remaining_players: If provided, only consider undrafted players

        Returns:
            ADP of the next player at the same position, or player_adp + 1.0
            if this is the last player at the position (no gain from waiting).
        """
        if remaining_players is not None:
            pool = [p for p in remaining_players if p['position'] == position]
        else:
            pool = self.position_groups.get(position, [])

        # Sort ascending by ADP (lower = earlier pick = better)
        sorted_pool = sorted(pool, key=lambda p: p['adp_overall'])

        # Find the first player whose ADP is strictly greater than player_adp
        for p in sorted_pool:
            if p['adp_overall'] > player_adp:
                return p['adp_overall']

        # Last player at position — no one to fall back to
        return player_adp + 1.0

    def calculate_vor(
        self,
        position: str,
        adp: float,
        projected_pts: Optional[float] = None,
        remaining_players: Optional[List[Dict]] = None,
        replacement_percentile: int = 50,  # kept for API compatibility, unused
    ) -> float:
        """
        Calculate VOR for a specific player.

        If projected_pts is provided (and projection_groups are loaded), uses
        projection-based VOR:
            VOR = player_projected_pts - next_player_projected_pts

        Otherwise falls back to ADP-based VOR:
            VOR = next_player_adp - player_adp

        In both cases a higher score means a bigger gap to the next option.

        Args:
            position:         Player position.
            adp:              Player's ADP (always required; used as fallback).
            projected_pts:    Player's projected PPR season points (optional).
            remaining_players: Undrafted players for live-draft mode.
            replacement_percentile: Unused; kept for backwards compatibility.

        Returns:
            VOR score (positive = gap to next player).
        """
        if projected_pts is not None and self.projection_groups:
            next_pts = self.get_next_projected_pts(position, projected_pts, remaining_players)
            return projected_pts - next_pts

        # ADP-based fallback
        replacement_level = self.get_next_player_adp(position, adp, remaining_players)
        return replacement_level - adp
    
    def get_vor_for_draft_scenario(
        self,
        position: str,
        round_num: int,
        replacement_percentile: int = 50
    ) -> Dict:
        """
        Get VOR info for a typical player drafted in a given round/position.
        
        Args:
            position: Player position
            round_num: Draft round (1-based)
            replacement_percentile: Replacement level percentile (50 = median)
        
        Returns:
            Dict with VOR analysis for that round/position combo
        """
        players_at_pos = self.position_groups.get(position, [])
        if not players_at_pos:
            raise ValueError(f"No players found for position {position}")
        
        # Find typical player in this round for this position
        typical_adp = round_num * 10  # Rough: round 1 = picks 1-10, round 2 = 11-20, etc.
        
        # Find closest match
        closest = min(players_at_pos, key=lambda p: abs(p['adp_overall'] - typical_adp))
        
        # Get replacement level
        replacement_level = self.get_replacement_level(position, replacement_percentile)
        vor = self.calculate_vor(position, closest['adp_overall'], replacement_percentile=replacement_percentile)
        
        return {
            'position': position,
            'round': round_num,
            'typical_player': closest['player_name'],
            'typical_adp': closest['adp_overall'],
            'replacement_level_adp': replacement_level,
            'vor_score': vor,
            'interpretation': self._interpret_vor(vor)
        }
    
    def _interpret_vor(self, vor: float, basis: str = "adp") -> str:
        """Interpret VOR score for user understanding.

        Args:
            vor:   VOR score.
            basis: "projection" (points gap) or "adp" (pick-number gap).
        """
        if basis == "projection":
            # Gaps are in projected fantasy points (e.g. 58 pts = Kittle→LaPorta cliff)
            if vor < 5:
                return "At replacement level (no gap)"
            elif vor < 20:
                return "Slight value (small gap)"
            elif vor < 40:
                return "Moderate value (decent gap)"
            elif vor < 70:
                return "Strong value (notable gap)"
            else:
                return "Elite value (major cliff)"
        else:
            # ADP-based: gaps are in pick numbers
            if vor < 2:
                return "At replacement level (no gap)"
            elif vor < 8:
                return "Slight value (small gap)"
            elif vor < 20:
                return "Moderate value (decent gap)"
            elif vor < 35:
                return "Strong value (notable gap)"
            else:
                return "Elite value (major cliff)"
    
    def print_vor_by_round(
        self,
        position: str,
        rounds: List[int],
        replacement_percentile: int = 50
    ):
        """
        Print VOR analysis for multiple rounds at a position.
        
        Args:
            position: Player position
            rounds: List of round numbers to analyze (e.g., [1, 5, 10, 15])
            replacement_percentile: Replacement level percentile
        """
        print(f"\n📊 VOR Analysis for {position} (Replacement = {replacement_percentile}th percentile)")
        print("=" * 80)
        print(f"{'Round':<8} {'Typical Player':<25} {'ADP':<8} {'Repl. Lvl':<12} {'VOR':<8} {'Value':<25}")
        print("-" * 80)
        
        for round_num in rounds:
            scenario = self.get_vor_for_draft_scenario(position, round_num, replacement_percentile)
            print(
                f"{scenario['round']:<8} "
                f"{scenario['typical_player']:<25} "
                f"{scenario['typical_adp']:<8.1f} "
                f"{scenario['replacement_level_adp']:<12.1f} "
                f"{scenario['vor_score']:<8.1f} "
                f"{scenario['interpretation']:<25}"
            )


def main():
    """Test VOR calculator with example scenarios."""
    # Load data
    import os
    players_file = os.path.expanduser("~/LineupLines/data/players/ppr_20260205_163143_players.json")
    vor = VORCalculator(players_file)
    
    print("\n🎯 VOR Draft Value Analysis")
    print("Using 50th percentile (median) replacement level\n")
    
    # Analyze key positions across draft
    positions = ['QB', 'RB', 'WR', 'TE']
    rounds = [1, 5, 10, 15]
    
    for pos in positions:
        try:
            vor.print_vor_by_round(pos, rounds, replacement_percentile=50)
        except ValueError as e:
            print(f"⚠️  {pos}: {e}")
    
    # Example: Calculate VOR for a specific player
    print("\n\n💡 Example: VOR for Ja'Marr Chase")
    print("-" * 50)
    chase_vor = vor.calculate_vor('WR', adp=1.9, replacement_percentile=50)
    replacement = vor.get_replacement_level('WR', replacement_percentile=50)
    print(f"Player: Ja'Marr Chase")
    print(f"Position: WR")
    print(f"ADP: 1.9")
    print(f"Replacement Level (median WR): {replacement:.1f}")
    print(f"VOR Score: {chase_vor:.1f}")
    print(f"Interpretation: {vor._interpret_vor(chase_vor)}")


if __name__ == "__main__":
    main()
