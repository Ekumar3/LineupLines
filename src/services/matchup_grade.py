"""Serves the OL/DL matchup grade for a (team, opponent, season, week) query.

Reads ``mart_matchup_grade`` via ``projections_store`` and answers point
lookups: "how does this offense's line match up against this defense's front
this week?". The mart is loaded lazily and cached on the first lookup so the
DuckDB/S3 read happens once per service instance.

Graceful degradation is the core guarantee: when the mart hasn't been built
yet, or there's no scheduled game for the (team, opponent, season, week), the
service returns a NEUTRAL default (all signals ``"neutral"``, all grades
``0.0``) instead of raising. Callers (the roster/recommendation endpoints) can
always render something sensible.
"""

from dataclasses import dataclass
from typing import Optional

import polars as pl

from src.data_sources.projections_store import load_mart


@dataclass
class MatchupGrade:
    """OL vs DL matchup grade for one offense team against one defense.

    Matchup fields are ``offense_sub_grade - defense_sub_grade`` per channel, so
    a positive value means the offense is favored. Signals bucket those deltas
    into ``favorable | neutral | unfavorable``.
    """

    team: str
    opponent: str
    season: int
    week: int
    pass_matchup: Optional[float]  # ol.pass_protection - dl.pass_rush
    rush_matchup: Optional[float]  # ol.run_blocking - dl.run_defense
    overall_matchup: Optional[float]  # ol.ol_grade - dl.dl_grade
    pass_signal: str  # favorable | neutral | unfavorable
    rush_signal: str
    overall_signal: str
    ol_grade: Optional[float]  # offense OL composite 0-100
    dl_grade: Optional[float]  # defense DL composite 0-100


def _neutral(team: str, opponent: str, season: int, week: int) -> MatchupGrade:
    """A neutral-default grade for when no mart row is available."""
    return MatchupGrade(
        team=team,
        opponent=opponent,
        season=season,
        week=week,
        pass_matchup=0.0,
        rush_matchup=0.0,
        overall_matchup=0.0,
        pass_signal="neutral",
        rush_signal="neutral",
        overall_signal="neutral",
        ol_grade=None,
        dl_grade=None,
    )


class MatchupGradeService:
    """Lazy-loading, cached reader for ``mart_matchup_grade``."""

    def __init__(self) -> None:
        self._cache: Optional[pl.DataFrame] = None  # lazy-load the mart once

    def _load(self) -> pl.DataFrame:
        if self._cache is None:
            self._cache = load_mart("mart_matchup_grade")
        return self._cache

    def grade_for(self, team: str, opponent: str, season: int, week: int) -> MatchupGrade:
        """Return the matchup grade, or a neutral default if unavailable.

        Precondition: ``team`` and ``opponent`` are NFL team abbreviations.
        Postcondition: ``result.{pass,rush,overall}_signal`` is one of
            ``{favorable, neutral, unfavorable}``; when the mart is empty or no
            row matches the query, all signals are ``"neutral"`` and the matchup
            grades are ``0.0``. Never raises.
        """
        df = self._load()
        if df.is_empty():
            return _neutral(team, opponent, season, week)

        row = df.filter(
            (pl.col("team") == team)
            & (pl.col("opponent") == opponent)
            & (pl.col("season") == season)
            & (pl.col("week") == week)
        )
        if row.is_empty():
            return _neutral(team, opponent, season, week)

        r = row.to_dicts()[0]
        return MatchupGrade(
            team=team,
            opponent=opponent,
            season=season,
            week=week,
            pass_matchup=r.get("pass_matchup"),
            rush_matchup=r.get("rush_matchup"),
            overall_matchup=r.get("overall_matchup"),
            pass_signal=r.get("pass_signal") or "neutral",
            rush_signal=r.get("rush_signal") or "neutral",
            overall_signal=r.get("overall_signal") or "neutral",
            ol_grade=r.get("ol_grade"),
            dl_grade=r.get("dl_grade"),
        )


__all__ = ["MatchupGrade", "MatchupGradeService"]
