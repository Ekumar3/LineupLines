"""Sleeper Projections Client — native player projections and ADP from Sleeper.

Uses Sleeper's undocumented but stable season-projections endpoint:
  GET https://api.sleeper.app/projections/nfl/{year}?season_type=regular&...

Returns season-total projected points and ADP values, both in Sleeper's native
player_id space — no name-matching required.  Results are cached for 24 hours
since pre-draft projections change infrequently.
"""

import logging
import time
from dataclasses import dataclass
from typing import Dict, Optional

import requests

logger = logging.getLogger(__name__)

# Which stats field to use for projected points / ADP per scoring format
_PTS_FIELD: Dict[str, str] = {
    "ppr": "pts_ppr",
    "half_ppr": "pts_half_ppr",
    "standard": "pts_std",
}

_ADP_FIELD: Dict[str, str] = {
    "ppr": "adp_ppr",
    "half_ppr": "adp_half_ppr",
    "standard": "adp_std",
}

SKILL_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}


@dataclass
class PlayerProjection:
    """Season-projection data for a single player from Sleeper."""

    player_id: str
    player_name: str
    position: str
    team: str
    projected_pts: float  # season-total projected points
    avg_ppg: float        # projected_pts / gp  (used for VOR)
    adp: float            # ADP for the requested scoring format
    gp: float             # projected games played


class SleeperProjectionsClient:
    """Fetches player projections and ADP from Sleeper's native API.

    The endpoint is undocumented but has been stable across seasons and is
    the same source Sleeper's own draft interface uses, so numbers match
    what users see when drafting.

    Usage::

        client = SleeperProjectionsClient()
        proj = client.fetch_projections(2025, "ppr")
        # proj["4046"].avg_ppg  → Saquon Barkley projected PPG
    """

    BASE_URL = "https://api.sleeper.app/projections/nfl"
    CACHE_TTL = 86_400   # 24 hours
    REQUEST_TIMEOUT = 15

    def __init__(self) -> None:
        self._cache: Dict[str, Dict[str, PlayerProjection]] = {}
        self._cache_times: Dict[str, float] = {}

    def fetch_projections(
        self, year: int, scoring_format: str = "ppr"
    ) -> Dict[str, PlayerProjection]:
        """Fetch season-long player projections and ADP from Sleeper.

        Args:
            year: NFL season year (e.g. 2025).
            scoring_format: "ppr", "half_ppr", or "standard".

        Returns:
            Dict mapping Sleeper player_id → PlayerProjection.
            Players without ADP data for the requested format are excluded
            (they're depth-chart scrubs with no draft relevance).
        """
        scoring_format = scoring_format.lower()
        cache_key = f"{year}:{scoring_format}"
        now = time.time()

        if cache_key in self._cache:
            if now - self._cache_times[cache_key] < self.CACHE_TTL:
                logger.debug("Sleeper projections cache hit: %s", cache_key)
                return self._cache[cache_key]

        pts_field = _PTS_FIELD.get(scoring_format, "pts_ppr")
        adp_field = _ADP_FIELD.get(scoring_format, "adp_ppr")

        position_params = "&".join(
            f"position[]={pos}" for pos in sorted(SKILL_POSITIONS)
        )
        url = (
            f"{self.BASE_URL}/{year}"
            f"?season_type=regular&{position_params}&order_by={pts_field}"
        )

        logger.info(
            "Fetching Sleeper projections: year=%s format=%s", year, scoring_format
        )
        resp = requests.get(url, timeout=self.REQUEST_TIMEOUT)
        resp.raise_for_status()
        raw: list = resp.json()

        result: Dict[str, PlayerProjection] = {}
        for entry in raw:
            player_data = entry.get("player") or {}
            stats = entry.get("stats") or {}

            # player_id lives at the top level of each entry, not inside player{}
            player_id = str(entry.get("player_id") or "")
            if not player_id:
                continue

            position = player_data.get("position") or ""
            if position not in SKILL_POSITIONS:
                continue

            adp = stats.get(adp_field)
            if adp is None:
                continue  # no ADP → not draft-relevant

            pts = float(stats.get(pts_field) or 0.0)
            gp = float(stats.get("gp") or 17.0)
            avg_ppg = pts / gp if gp > 0 else 0.0

            first = player_data.get("first_name", "")
            last = player_data.get("last_name", "")
            name = f"{first} {last}".strip()

            result[player_id] = PlayerProjection(
                player_id=player_id,
                player_name=name,
                position=position,
                team=player_data.get("team") or "FA",
                projected_pts=pts,
                avg_ppg=avg_ppg,
                adp=float(adp),
                gp=gp,
            )

        logger.info(
            "Sleeper projections fetched: %d players (year=%s format=%s)",
            len(result),
            year,
            scoring_format,
        )
        self._cache[cache_key] = result
        self._cache_times[cache_key] = now
        return result
