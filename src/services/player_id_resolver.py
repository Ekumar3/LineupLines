"""Maps FantasyPros player names to Sleeper player IDs using name+position matching."""

import logging
import re
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# FantasyPros -> Sleeper team abbreviation differences
TEAM_ALIASES = {"JAC": "JAX"}

FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}


def normalize_fantasypros_name(name: str) -> str:
    """Normalize a FantasyPros player name to match Sleeper's search_full_name format.

    Sleeper's search_full_name is lowercase, no spaces, no punctuation, no suffixes.
    E.g., "Ja'Marr Chase (CIN)" -> "jamarrchase"
    """
    if not name:
        return ""
    name = name.lower().strip()
    # Remove team abbreviation in parentheses
    if "(" in name:
        name = name[: name.rfind("(")].strip()
    # Remove common punctuation
    name = re.sub(r"['\.\-]", "", name)
    # Remove common suffixes
    for suffix in [" ii", " iii", " iv", " jr", " sr"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    # Remove all spaces to match Sleeper's search_full_name format
    name = name.replace(" ", "")
    return name


class PlayerIDResolver:
    """Resolves FantasyPros player names to Sleeper player IDs."""

    def __init__(self, sleeper_players: Dict[str, dict]):
        # Index: (search_full_name, position) -> sleeper_player_id
        # Secondary index with team for disambiguation: (search_full_name, position, team) -> sleeper_player_id
        self._index: Dict[tuple, str] = {}
        self._index_with_team: Dict[tuple, str] = {}
        self._collisions: set = set()

        for player_id, player in sleeper_players.items():
            search_name = player.get("search_full_name", "")
            if not search_name:
                continue

            positions = player.get("fantasy_positions") or []
            team = (player.get("team") or "").upper()

            for pos in positions:
                if pos not in FANTASY_POSITIONS:
                    continue

                key = (search_name, pos)
                if key in self._index:
                    self._collisions.add(key)
                self._index[key] = player_id

                if team:
                    self._index_with_team[(search_name, pos, team)] = player_id

        logger.info(
            f"PlayerIDResolver built index with {len(self._index)} entries, "
            f"{len(self._collisions)} name+position collisions"
        )

    def resolve(self, fp_player_name: str, position: str, team: str = None) -> Optional[str]:
        """Resolve a FantasyPros player to a Sleeper player ID.

        Args:
            fp_player_name: FantasyPros player name, e.g. "Ja'Marr Chase (CIN)"
            position: Position code, e.g. "WR"
            team: Optional team abbreviation for disambiguation

        Returns:
            Sleeper player_id string, or None if no match found.
        """
        normalized = normalize_fantasypros_name(fp_player_name)
        if not normalized:
            return None

        key = (normalized, position)

        # If there's a collision on name+position, use team to disambiguate
        if key in self._collisions and team:
            resolved_team = TEAM_ALIASES.get(team.upper(), team.upper())
            team_key = (normalized, position, resolved_team)
            result = self._index_with_team.get(team_key)
            if result:
                return result

        return self._index.get(key)
