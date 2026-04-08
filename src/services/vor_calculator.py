"""
Value Over Replacement (VOR) Calculator for Fantasy Football Draft

VOR measures how much better a player is compared to a "replacement level" player.
This helps identify which positions offer the most value at different draft stages.

Formula: VOR = player_adp - replacement_level_adp
Higher VOR = more value at that stage

Replacement Level: Median ADP of remaining players at the same position
This gives a stable baseline that adjusts as the draft progresses.
"""

import json
from typing import List, Dict, Optional
from pathlib import Path
from statistics import median, quantiles


class VORCalculator:
    def __init__(self, players_file: str):
        """
        Initialize VOR calculator with player ADP data.
        
        Args:
            players_file: Path to players JSON file (e.g., data/players/ppr_20260205_163143_players.json)
        """
        self.players = self._load_players(players_file)
        self.position_groups = self._group_by_position()
        
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
    
    def calculate_vor(
        self,
        position: str,
        adp: float,
        remaining_players: Optional[List[Dict]] = None,
        replacement_percentile: int = 50
    ) -> float:
        """
        Calculate VOR for a specific player.
        
        Lower ADP is better (picked earlier).
        VOR = replacement_level_adp - player_adp (positive = above replacement/elite)
        
        Args:
            position: Player position
            adp: Player's ADP value
            remaining_players: Players still available (for dynamic replacement level)
                             If None, uses static replacement level
            replacement_percentile: Which percentile (50 = median)
        
        Returns:
            VOR score (positive = above replacement, negative = below)
        """
        if remaining_players:
            # Dynamic: calculate replacement level from remaining players only
            remaining_at_pos = [p for p in remaining_players if p['position'] == position]
            if not remaining_at_pos:
                raise ValueError(f"No remaining players at position {position}")
            
            remaining_adp = [p['adp_overall'] for p in remaining_at_pos]
            if replacement_percentile == 50:
                replacement_level = median(remaining_adp)
            else:
                percentile_val = replacement_percentile / 100.0
                quants = quantiles(remaining_adp, n=100)
                idx = int(percentile_val * (len(quants) - 1))
                replacement_level = quants[idx]
        else:
            # Static: use pre-draft replacement level
            replacement_level = self.get_replacement_level(position, replacement_percentile)
        
        # VOR = how much earlier this player is picked than replacement level
        # Higher VOR = picked much earlier = more elite
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
    
    def _interpret_vor(self, vor: float) -> str:
        """Interpret VOR score for user understanding."""
        if vor < 5:
            return "Below replacement (avoid)"
        elif vor < 15:
            return "At replacement level (neutral)"
        elif vor < 30:
            return "Moderate value (decent pick)"
        elif vor < 60:
            return "Strong value (good pick)"
        else:
            return "Elite value (excellent pick)"
    
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
