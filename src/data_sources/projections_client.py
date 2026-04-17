"""
Client for loading and querying SportsData.io player season projections.

Projections are read from a local JSON file downloaded by scripts/fetch_projections.py.
The client indexes players by normalized name (and optionally team) so that FantasyPros
player names can be matched even with apostrophes, dots, suffixes, etc.
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SKILL_POSITIONS = {"QB", "RB", "WR", "TE", "K"}

# Scoring format -> field name in the SportsData.io response
SCORING_FIELD = {
    "ppr": "FantasyPointsPPR",
    "half_ppr": "FantasyPointsPPR",   # SportsData has no half-PPR field; PPR is closest
    "standard": "FantasyPoints",
}


def _normalize_name(name: str) -> str:
    """Lowercase, strip punctuation and common suffixes — mirrors normalize_fantasypros_name()."""
    if not name:
        return ""
    name = name.lower().strip()
    # Remove team abbreviation in parentheses (FantasyPros format)
    if "(" in name:
        name = name[: name.rfind("(")].strip()
    # Remove common punctuation
    name = re.sub(r"['\.\-]", "", name)
    # Remove common suffixes
    for suffix in [" ii", " iii", " iv", " jr", " sr"]:
        if name.endswith(suffix):
            name = name[: -len(suffix)].strip()
    return name.replace(" ", "")


class ProjectionsClient:
    """
    Loads player season projections from a local JSON file and provides fast lookups.

    Index keys:
      (normalized_name, position)            -> projected points
      (normalized_name, position, team)      -> projected points  (tiebreaker)
    """

    def __init__(self, projections_file: str):
        self._index: dict[tuple, float] = {}
        self._index_with_team: dict[tuple, float] = {}
        self._collisions: set[tuple] = set()
        self._raw: list[dict] = []
        self._load(projections_file)

    def _load(self, file_path: str) -> None:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Projections file not found: {file_path}")

        with open(path) as f:
            players = json.load(f)

        loaded = 0
        for p in players:
            name = p.get("Name", "")
            pos = p.get("Position", "")
            team = (p.get("Team") or "").upper()

            if pos not in SKILL_POSITIONS or not name:
                continue

            # Store every scoring format's value
            pts_ppr = p.get("FantasyPointsPPR") or 0.0
            pts_std = p.get("FantasyPoints") or 0.0
            if pts_ppr <= 0 and pts_std <= 0:
                continue  # No meaningful projection — skip

            norm = _normalize_name(name)
            entry = {
                "ppr": pts_ppr,
                "standard": pts_std,
                "name": name,
                "team": team,
                "position": pos,
            }

            key = (norm, pos)
            if key in self._index:
                self._collisions.add(key)
            self._index[key] = entry

            if team:
                self._index_with_team[(norm, pos, team)] = entry

            self._raw.append(entry)
            loaded += 1

        logger.info(
            f"ProjectionsClient: loaded {loaded} players, "
            f"{len(self._collisions)} name+position collisions"
        )

    def get_projected_points(
        self,
        player_name: str,
        position: str,
        team: str = "",
        scoring: str = "ppr",
    ) -> Optional[float]:
        """
        Look up projected season fantasy points for a player.

        Args:
            player_name: Player name in any format (FantasyPros names work fine).
            position:    Position code, e.g. "WR".
            team:        Optional team abbreviation for disambiguation.
            scoring:     One of "ppr", "half_ppr", "standard".

        Returns:
            Projected season fantasy points, or None if the player isn't found.
        """
        norm = _normalize_name(player_name)
        if not norm:
            return None

        pos = position.upper()
        field = "ppr" if scoring in ("ppr", "half_ppr") else "standard"

        key = (norm, pos)
        if key in self._collisions and team:
            team_key = (norm, pos, team.upper())
            entry = self._index_with_team.get(team_key)
            if entry:
                return entry[field] or None
            # Fall through to unambiguous lookup if team didn't help

        entry = self._index.get(key)
        if entry is None:
            return None
        val = entry[field]
        return val if val and val > 0 else None

    def coverage_stats(self) -> dict:
        """Return a quick summary of what's in the index (for logging/debugging)."""
        by_pos: dict[str, int] = {}
        for entry in self._raw:
            by_pos[entry["position"]] = by_pos.get(entry["position"], 0) + 1
        return {"total": len(self._raw), "by_position": by_pos}
