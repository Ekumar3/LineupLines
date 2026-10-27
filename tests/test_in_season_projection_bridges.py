"""Unit tests for the serving-layer bridges between Sleeper and the projection/
matchup data.

Two helpers in src/api/main.py bridge the id/opponent gaps that otherwise left
a live Sleeper roster with null projections and neutral matchups:

- ``_gsis_to_sleeper_map`` / ``_load_week_projections`` translate the
  nflverse-id-keyed projection parquet to Sleeper-id-keyed points (the roster
  uses Sleeper ids), stripping the stray leading space nflverse ids carry in
  the Sleeper universe's ``gsis_id`` field.
- ``_opponent_for`` resolves a team's weekly opponent from the cached
  ``mart_matchup_grade`` (schedule-backed, so it covers unplayed weeks).

These are the fixes for: projected_points coming back null and matchup grades
always neutral when hitting the recommendations endpoint for an upcoming week.
"""

from unittest.mock import patch

import polars as pl

from src.api import main


# ---------------------------------------------------------------------------
# _gsis_to_sleeper_map
# ---------------------------------------------------------------------------


class TestGsisToSleeperMap:
    def test_maps_gsis_to_sleeper_and_strips_whitespace(self):
        """nflverse gsis_id -> Sleeper id, with the leading space stripped."""
        universe = {
            "4034": {"gsis_id": "00-0033280", "first_name": "Christian", "last_name": "McCaffrey"},
            # Sleeper sometimes stores gsis_id with a stray leading space.
            "6462": {"gsis_id": " 00-0035057", "first_name": "Ellis", "last_name": "Richardson"},
        }
        mapping = main._gsis_to_sleeper_map(universe)

        assert mapping["00-0033280"] == "4034"
        # Leading space must be stripped so the key matches the parquet id.
        assert mapping["00-0035057"] == "6462"
        assert " 00-0035057" not in mapping

    def test_skips_players_without_gsis_id(self):
        """Players with no / empty gsis_id are omitted (no NFL mapping)."""
        universe = {
            "1": {"gsis_id": "00-0011111"},
            "2": {"gsis_id": None},
            "3": {"gsis_id": ""},
            "4": {"gsis_id": "   "},  # whitespace-only -> empty after strip
            "5": {"first_name": "No", "last_name": "Gsis"},  # missing field
        }
        mapping = main._gsis_to_sleeper_map(universe)

        assert mapping == {"00-0011111": "1"}

    def test_handles_empty_or_none_universe(self):
        assert main._gsis_to_sleeper_map({}) == {}
        assert main._gsis_to_sleeper_map(None) == {}

    def test_ignores_non_dict_entries(self):
        """Malformed universe entries are skipped, never raise."""
        universe = {"1": {"gsis_id": "00-0011111"}, "2": "garbage", "3": None}
        mapping = main._gsis_to_sleeper_map(universe)
        assert mapping == {"00-0011111": "1"}


# ---------------------------------------------------------------------------
# _load_week_projections — id translation
# ---------------------------------------------------------------------------


class TestLoadWeekProjectionsTranslation:
    @staticmethod
    def _proj_df():
        """A projection parquet keyed by nflverse ids (as written on disk)."""
        return pl.DataFrame(
            [
                {"player_id": "00-0033280", "projected_points": 22.5},
                {"player_id": "00-0035057", "projected_points": 8.1},
                # An nflverse id with no Sleeper counterpart -> dropped.
                {"player_id": "00-9999999", "projected_points": 99.0},
            ]
        )

    @property
    def _universe(self):
        return {
            "4034": {"gsis_id": "00-0033280"},
            "6462": {"gsis_id": " 00-0035057"},
        }

    def test_rekeys_projections_to_sleeper_ids(self):
        """With a universe, projections are keyed by Sleeper id, not nflverse id."""
        with patch(
            "src.data_sources.projections_store.load_projections",
            return_value=self._proj_df(),
        ):
            proj = main._load_week_projections(2026, 7, "ppr", self._universe)

        # Keyed by Sleeper id now.
        assert proj == {"4034": 22.5, "6462": 8.1}
        # The unmapped nflverse id was dropped (no Sleeper counterpart).
        assert "00-9999999" not in proj

    def test_without_universe_stays_nflverse_keyed(self):
        """Back-compat: no universe -> dict stays keyed by the parquet id."""
        with patch(
            "src.data_sources.projections_store.load_projections",
            return_value=self._proj_df(),
        ):
            proj = main._load_week_projections(2026, 7, "ppr")

        assert proj["00-0033280"] == 22.5
        assert proj["00-0035057"] == 8.1

    def test_empty_projection_file_returns_empty(self):
        with patch(
            "src.data_sources.projections_store.load_projections",
            return_value=pl.DataFrame(),
        ):
            assert main._load_week_projections(2026, 7, "ppr", self._universe) == {}

    def test_name_position_fallback_when_gsis_missing(self):
        """A player with no gsis_id is matched by normalized name + position.

        Many players (notably recent draftees) have gsis_id=None on Sleeper even
        though nflverse has them. The projection carries player_name + position,
        so the fallback bridges them. Normalization must handle suffixes and
        punctuation ("Ollie Gordon II" <-> "Ollie Gordon", "Smith-Njigba").
        """
        proj_df = pl.DataFrame(
            [
                {"player_id": "00-0039999", "player_name": "Ollie Gordon II", "position": "RB", "projected_points": 15.8},
                {"player_id": "00-0038888", "player_name": "Jaxon Smith-Njigba", "position": "WR", "projected_points": 20.3},
            ]
        )
        universe = {
            # No gsis_id on either -> must fall back to name+position.
            "12495": {"first_name": "Ollie", "last_name": "Gordon", "position": "RB"},
            "9488": {"first_name": "Jaxon", "last_name": "Smith-Njigba", "position": "WR"},
        }
        with patch(
            "src.data_sources.projections_store.load_projections",
            return_value=proj_df,
        ):
            proj = main._load_week_projections(2026, 7, "ppr", universe)

        assert proj == {"12495": 15.8, "9488": 20.3}

    def test_gsis_match_takes_precedence_over_name(self):
        """When gsis_id matches, it wins and the name fallback isn't consulted.

        Guards against a wrong-player name collision overriding an exact id hit.
        """
        proj_df = pl.DataFrame(
            [
                {"player_id": "00-0033280", "player_name": "WRONG NAME", "position": "RB", "projected_points": 22.5},
            ]
        )
        universe = {
            "4034": {"gsis_id": "00-0033280", "first_name": "Christian", "last_name": "McCaffrey", "position": "RB"},
        }
        with patch(
            "src.data_sources.projections_store.load_projections",
            return_value=proj_df,
        ):
            proj = main._load_week_projections(2026, 7, "ppr", universe)

        # Matched by exact gsis_id despite the mismatched name in the parquet.
        assert proj == {"4034": 22.5}


# ---------------------------------------------------------------------------
# _opponent_for
# ---------------------------------------------------------------------------


class _FakeMatchupService:
    """Stand-in exposing the same ._load() cached-mart seam the real service has."""

    def __init__(self, df):
        self._df = df

    def _load(self):
        return self._df


def _matchup_df():
    return pl.DataFrame(
        [
            {"season": 2026, "week": 7, "team": "KC", "opponent": "SEA"},
            {"season": 2026, "week": 7, "team": "DAL", "opponent": "PHI"},
            {"season": 2026, "week": 8, "team": "KC", "opponent": "BUF"},
        ]
    )


class TestOpponentFor:
    def test_resolves_opponent_for_team_week(self):
        svc = _FakeMatchupService(_matchup_df())
        assert main._opponent_for("KC", 2026, 7, svc) == "SEA"
        assert main._opponent_for("DAL", 2026, 7, svc) == "PHI"
        # Same team, different week -> different opponent.
        assert main._opponent_for("KC", 2026, 8, svc) == "BUF"

    def test_returns_none_when_no_scheduled_game(self):
        svc = _FakeMatchupService(_matchup_df())
        # Team not scheduled that week.
        assert main._opponent_for("SF", 2026, 7, svc) is None

    def test_returns_none_for_fa_or_missing_team(self):
        svc = _FakeMatchupService(_matchup_df())
        assert main._opponent_for("FA", 2026, 7, svc) is None
        assert main._opponent_for(None, 2026, 7, svc) is None

    def test_returns_none_when_service_unavailable(self):
        assert main._opponent_for("KC", 2026, 7, None) is None

    def test_returns_none_on_empty_mart(self):
        svc = _FakeMatchupService(pl.DataFrame())
        assert main._opponent_for("KC", 2026, 7, svc) is None
