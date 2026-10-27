"""Waiver wire recommendations: FA pool ranking + drop/add optimization.

Phase 1 (Task 11/12): rank free agents by projected points, augmented with
Sleeper trending-adds. The free-agent pool is every projected player minus
every player rostered anywhere in the league.
Phase 2 (Task 14): VOR/replacement-level delta between each bench player
(drop candidate) and each FA (add candidate); rank drop/add pairs by net
projected points gained. NOT implemented here — the class is structured so
Task 14 can add ``drop_add_optimization`` without reworking Phase 1.

Every public method degrades gracefully: missing projections or unreachable
Sleeper endpoints yield an empty list rather than an exception, mirroring the
defensive posture of ``SleeperClient`` and ``projections_store``.
"""

import logging
from dataclasses import dataclass
from typing import List, Optional, Set

from src.data_sources.projections_store import load_projections
from src.data_sources.sleeper_client import SleeperClient, roster_bench

logger = logging.getLogger(__name__)


@dataclass
class WaiverRec:
    """One ranked free-agent recommendation for a (season, week, format)."""

    player_id: str
    player_name: str
    position: str
    team: str
    projected_points: Optional[float]
    trending_add_count: Optional[int] = None
    rank: int = 0


@dataclass
class DropAddRec:
    """One ranked drop/add pair: swap a bench player for a free agent.

    ``net_gain`` is ``add_projected_points - drop_projected_points`` and is
    always strictly positive for returned pairs (upgrades only).
    """

    drop_player_id: str
    drop_player_name: str
    drop_projected_points: float
    add_player_id: str
    add_player_name: str
    add_projected_points: float
    position: str
    net_gain: float
    rank: int = 0


class WaiverService:
    """Waiver wire recommendations backed by projections + Sleeper rosters.

    Accepts a ``SleeperClient`` via dependency injection so it can be wired to
    the app's singleton in production and mocked in tests.
    """

    def __init__(self, sleeper_client: SleeperClient) -> None:
        self._sleeper = sleeper_client

    # -- internal helpers --------------------------------------------------

    def _rostered_player_ids(self, league_id: str) -> Set[str]:
        """All player_ids on any roster in the league.

        Union of every roster's ``players`` (which already includes starters +
        bench) and ``reserve`` (IR/TAXI). Degrades to an empty set when rosters
        cannot be fetched — in that case the FA pool is simply the full
        projection set.
        """
        rostered: Set[str] = set()
        for roster in self._sleeper.get_league_rosters(league_id):
            rostered.update(roster.players)
            rostered.update(roster.reserve)
        return rostered

    @staticmethod
    def _projected_points(value: Optional[object]) -> Optional[float]:
        """Coerce a projection cell to float, or None when absent/invalid."""
        if value is None:
            return None
        try:
            return float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return None

    # -- phase 1: free agent ranking --------------------------------------

    def free_agent_ranking(
        self,
        league_id: str,
        season: int,
        week: int,
        scoring_format: str,
        position: Optional[str] = None,
        limit: int = 50,
    ) -> List[WaiverRec]:
        """Phase 1: rank FAs by projected points, augmented with trending adds.

        Precondition: projections loaded for (season, week, scoring_format).
        Postcondition: results sorted by ``projected_points`` descending
            (tiebreak ``trending_add_count`` descending); the FA pool excludes
            every player_id rostered anywhere in ``league_id``; a position
            filter (when provided) is applied; ``limit`` caps the result size;
            ``rank`` is 1-indexed; ``trending_add_count`` is populated when
            Sleeper trending data is available.

        Degrades gracefully: when no projections exist for the slate the result
        is an empty list rather than an error.
        """
        projections = load_projections(season, week, scoring_format)
        if projections is None or projections.is_empty():
            logger.info(
                "No projections for season=%s week=%s format=%s; "
                "returning empty FA ranking",
                season, week, scoring_format,
            )
            return []

        rostered = self._rostered_player_ids(league_id)

        # Trending-add counts are optional context. Build a lookup, tolerating
        # an unreachable endpoint (empty list -> empty map).
        trending_map = {
            item.get("player_id"): item.get("count")
            for item in self._sleeper.get_trending_players(type="add")
            if item.get("player_id")
        }

        # Build the FA pool from projection rows, excluding rostered players and
        # applying the optional position filter.
        recs: List[WaiverRec] = []
        for row in projections.to_dicts():
            player_id = str(row.get("player_id"))
            if player_id in rostered:
                continue

            row_position = row.get("position") or "UNKNOWN"
            if position is not None and row_position != position:
                continue

            trending_count = trending_map.get(player_id)
            recs.append(
                WaiverRec(
                    player_id=player_id,
                    player_name=row.get("player_name") or player_id,
                    position=row_position,
                    team=row.get("team") or "FA",
                    projected_points=self._projected_points(row.get("projected_points")),
                    trending_add_count=(
                        int(trending_count) if trending_count is not None else None
                    ),
                )
            )

        # Rank by projected points desc, tiebreak trending-add count desc.
        # None sorts last for both keys (treat as -inf).
        recs.sort(
            key=lambda r: (
                r.projected_points if r.projected_points is not None else float("-inf"),
                r.trending_add_count if r.trending_add_count is not None else float("-inf"),
            ),
            reverse=True,
        )

        ranked = recs[: max(limit, 0)]
        for i, rec in enumerate(ranked):
            rec.rank = i + 1
        return ranked

    # -- phase 2: drop/add optimization -----------------------------------

    def drop_add_optimization(
        self,
        league_id: str,
        user_id: str,
        season: int,
        week: int,
        scoring_format: str,
        limit: int = 20,
    ) -> List["DropAddRec"]:
        """Phase 2: rank drop/add pairs by net projected points gained.

        Drop candidates are the user's **bench** players only (``roster_bench``
        = players - starters - reserve): never a starter, never on IR/TAXI.
        Add candidates are the league-wide free-agent pool (every projected
        player not rostered anywhere). For every (bench-drop, FA-add) pair the
        net gain is ``add_projected - drop_projected``; only strictly positive
        gains (true upgrades) are returned.

        Precondition: projections loaded for (season, week, scoring_format);
            the user owns a roster in ``league_id``.
        Postcondition: every add player is an FA (not rostered league-wide);
            every drop player is on the user's bench (not starter/reserve);
            ``net_gain = add_projected - drop_projected`` and is > 0; results
            sorted by ``net_gain`` descending, tie-broken to prefer
            same-position swaps; ``limit`` caps the result size; ``rank`` is
            1-indexed.

        Degrades gracefully: missing projections, a missing user roster, or an
        empty bench all yield an empty list rather than an error.
        """
        projections = load_projections(season, week, scoring_format)
        if projections is None or projections.is_empty():
            logger.info(
                "No projections for season=%s week=%s format=%s; "
                "returning empty drop/add optimization",
                season, week, scoring_format,
            )
            return []

        # Locate the user's roster by owner_id. Missing roster -> empty.
        rosters = self._sleeper.get_league_rosters(league_id)
        user_roster = next(
            (r for r in rosters if str(r.owner_id) == str(user_id)), None
        )
        if user_roster is None:
            logger.info(
                "No roster for user_id=%s in league=%s; "
                "returning empty drop/add optimization",
                user_id, league_id,
            )
            return []

        drop_ids = [str(pid) for pid in roster_bench(user_roster)]
        if not drop_ids:
            return []

        # Index every projection row by player_id for O(1) lookup.
        proj_by_id = {}
        for row in projections.to_dicts():
            proj_by_id[str(row.get("player_id"))] = row

        # Build drop candidates from the bench, keeping only those we can
        # project (a player with no projection cannot be scored for a swap).
        drop_candidates = []
        for pid in drop_ids:
            row = proj_by_id.get(pid)
            if row is None:
                continue
            points = self._projected_points(row.get("projected_points"))
            if points is None:
                continue
            drop_candidates.append(
                {
                    "player_id": pid,
                    "player_name": row.get("player_name") or pid,
                    "position": row.get("position") or "UNKNOWN",
                    "points": points,
                }
            )
        if not drop_candidates:
            return []

        # FA pool = every projected player not rostered anywhere league-wide.
        # Reuse the FA ranking (no position filter, generous cap) so the add
        # side stays consistent with Phase 1.
        fa_pool = self.free_agent_ranking(
            league_id=league_id,
            season=season,
            week=week,
            scoring_format=scoring_format,
            position=None,
            limit=500,
        )
        # Only FAs we can actually project are valid add candidates.
        add_candidates = [
            fa for fa in fa_pool if fa.projected_points is not None
        ]
        if not add_candidates:
            return []

        # Step 3: build positive-net-gain pairs.
        pairs: List[DropAddRec] = []
        for drop in drop_candidates:
            for add in add_candidates:
                net_gain = add.projected_points - drop["points"]
                if net_gain <= 0:
                    continue
                pairs.append(
                    DropAddRec(
                        drop_player_id=drop["player_id"],
                        drop_player_name=drop["player_name"],
                        drop_projected_points=drop["points"],
                        add_player_id=add.player_id,
                        add_player_name=add.player_name,
                        add_projected_points=add.projected_points,
                        # Report the add's position (the slot being upgraded).
                        position=add.position,
                        net_gain=net_gain,
                    )
                )

        # Step 4: rank by net_gain desc; tiebreak prefers same-position swaps
        # (drop.position == add.position). position_match is 1 for a matching
        # swap, 0 otherwise; higher sorts first.
        drop_position = {d["player_id"]: d["position"] for d in drop_candidates}
        pairs.sort(
            key=lambda p: (
                p.net_gain,
                1 if drop_position.get(p.drop_player_id) == p.position else 0,
            ),
            reverse=True,
        )

        ranked = pairs[: max(limit, 0)]
        for i, rec in enumerate(ranked):
            rec.rank = i + 1
        return ranked
