"""Shared Hypothesis strategies for the in-season-matchup-recommendations
property tests.

This module factors out the common generators the individual property-test
files each (re)define, so new property tests can import a single, consistent
set of synthetic-data builders instead of copy-pasting composites:

- :func:`feature_row` / :func:`features_frame` — ``mart_player_week_features``
  shaped polars rows/frames (synthetic NFL projection feature inputs).
- :func:`defense_input_rows` — ``int_defense_factor_inputs`` shaped rows for
  defense-factor fitting.
- :func:`projections_frame` — a waiver/recommendations projections polars frame.
- :func:`league_roster` / :func:`league_rosters` — Sleeper ``Roster`` objects
  with starters/bench(players)/reserve drawn from a shared id space.
- :func:`roster_positions` — a league ``roster_positions`` config array mixing
  starting and bench slots.
- :func:`scoring_settings` — a scoring settings dict over the 9 stat components.
- :func:`trending_payload` — a Sleeper trending-add payload (player_id -> count).

Design intent
-------------
The signatures are kept general (every generator accepts bounds / id-space
knobs with sensible defaults) so a caller can constrain the input space to
match whatever invariant it is checking. The existing property-test files are
intentionally left untouched — refactoring a passing test to import from here
would risk regressing it for no behavioural gain. New tests should prefer these
shared strategies; see ``README.md`` for the property -> test coverage matrix.

Nothing here touches disk or the network: frames are built in-memory as polars
DataFrames and rosters as plain dataclasses, so importing this module is cheap
and side-effect free.
"""

from __future__ import annotations

from typing import Optional, Sequence

import polars as pl
from hypothesis import strategies as st

from src.data_sources.sleeper_client import Roster
from src.services.projection_service import STAT_COMPONENTS

# ---------------------------------------------------------------------------
# Shared vocabulary
# ---------------------------------------------------------------------------

#: Fantasy positions the in-season feature reasons about (start/sit + waivers).
POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE", "K", "DEF")

#: Positions the projection model actually fits (QB/RB/WR/TE only).
MODELED_POSITIONS: tuple[str, ...] = ("QB", "RB", "WR", "TE")

#: Named starting slots plus the flex-type slots the lineup optimizer knows.
NAMED_SLOTS: tuple[str, ...] = ("QB", "RB", "WR", "TE", "K", "DEF")
FLEX_SLOTS: tuple[str, ...] = ("FLEX", "SUPER_FLEX", "REC_FLEX", "WRRB_FLEX")
STARTING_SLOT_CHOICES: tuple[str, ...] = NAMED_SLOTS + FLEX_SLOTS

#: Non-starting slots filtered out of the starting lineup.
NON_STARTING_SLOT_CHOICES: tuple[str, ...] = ("BN", "IR", "TAXI")

#: Team codes (incl. the "FA" free-agent sentinel used in projection rows).
TEAMS: tuple[str, ...] = ("AAA", "BBB", "CCC", "DDD", "FA")

#: Injury statuses: a mix of excluded (OUT/DOUBTFUL/IR) and retained values.
INJURY_STATUSES: tuple[Optional[str], ...] = (
    None,
    "QUESTIONABLE",
    "OUT",
    "DOUBTFUL",
    "IR",
)

#: Columns of a waiver/recommendations projections frame.
PROJ_COLUMNS: tuple[str, ...] = (
    "player_id",
    "player_name",
    "position",
    "team",
    "projected_points",
)

#: Default shared id space so rosters and projections overlap meaningfully.
DEFAULT_ID_SPACE = st.integers(min_value=1, max_value=60).map(str)


# ---------------------------------------------------------------------------
# Projection-service feature frames (mart_player_week_features shaped)
# ---------------------------------------------------------------------------

def feature_row(
    season: int,
    week: int,
    player_id: str,
    position: str,
    team: str,
    opponent: Optional[str],
    stats: Optional[dict] = None,
    implied_team_total: Optional[float] = None,
    name: Optional[str] = None,
) -> dict:
    """Build one ``mart_player_week_features``-shaped record.

    All 9 stat components default to ``0.0`` and are overridden by ``stats``.
    This mirrors the private ``_feature_row`` helper in
    ``test_projection_service_properties.py`` but is importable for reuse.
    """
    row = {c: 0.0 for c in STAT_COMPONENTS}
    if stats:
        row.update(stats)
    row.update(
        {
            "season": int(season),
            "week": int(week),
            "player_id": str(player_id),
            "player_display_name": name or str(player_id),
            "position": position,
            "team": team,
            "opponent_team": opponent,
            "implied_team_total": implied_team_total,
        }
    )
    return row


def features_frame(rows: Sequence[dict]) -> pl.DataFrame:
    """Build a feature polars frame from :func:`feature_row` records."""
    return pl.DataFrame(list(rows))


@st.composite
def stat_line(
    draw,
    components: Sequence[str] = STAT_COMPONENTS,
    min_value: float = 0.0,
    max_value: float = 400.0,
) -> dict:
    """A bounded, finite stat line over the given components."""
    return {
        c: draw(
            st.floats(
                min_value=min_value,
                max_value=max_value,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        for c in components
    }


@st.composite
def player_feature_history(
    draw,
    player_id: str = "p1",
    position: str = "WR",
    team: str = "AAA",
    opponent: str = "ZZZ",
    min_weeks: int = 4,
    max_weeks: int = 10,
    season_min: int = 2021,
    season_max: int = 2026,
):
    """A single player's trailing feature rows across one season.

    Returns ``(season, rows)``. Useful for no-future-leak / baseline-window
    style properties that need a contiguous per-player history.
    """
    season = draw(st.integers(min_value=season_min, max_value=season_max))
    n_weeks = draw(st.integers(min_value=min_weeks, max_value=max_weeks))
    rows = []
    for wk in range(1, n_weeks + 1):
        rows.append(
            feature_row(
                season,
                wk,
                player_id,
                position,
                team,
                opponent,
                stats=draw(stat_line()),
                implied_team_total=draw(
                    st.floats(
                        min_value=14.0,
                        max_value=35.0,
                        allow_nan=False,
                        allow_infinity=False,
                    )
                ),
            )
        )
    return season, rows


# ---------------------------------------------------------------------------
# Defense-factor inputs (int_defense_factor_inputs shaped)
# ---------------------------------------------------------------------------

#: A small team pool for defense-factor round-robin schedules.
DEFENSE_TEAMS: tuple[str, ...] = tuple(f"T{i:02d}" for i in range(8))


@st.composite
def defense_input_rows(
    draw,
    teams: Sequence[str] = DEFENSE_TEAMS,
    min_weeks: int = 6,
    max_weeks: int = 12,
    season_min: int = 2022,
    season_max: int = 2026,
):
    """A defense-input matrix: a round-robin schedule over ``teams`` with
    bounded passing/rushing yardage per team-game.

    Enough team-games are generated to clear ``MIN_GAMES_TO_FIT`` at a late
    snapshot, so downstream factor fits actually run.
    """
    season = draw(st.integers(min_value=season_min, max_value=season_max))
    n_weeks = draw(st.integers(min_value=min_weeks, max_value=max_weeks))
    teams = list(teams)
    n = len(teams)
    rows = []
    for wk in range(1, n_weeks + 1):
        # rotate pairings so each team faces a mix of opponents
        order = teams[:1] + teams[1:][wk % (n - 1):] + teams[1:][: wk % (n - 1)]
        for i in range(n // 2):
            a, b = order[i], order[n - 1 - i]
            for off, d in ((a, b), (b, a)):
                rows.append(
                    {
                        "season": season,
                        "week": wk,
                        "team": off,
                        "opponent_team": d,
                        "passing_yards": draw(
                            st.floats(
                                min_value=0.0,
                                max_value=600.0,
                                allow_nan=False,
                                allow_infinity=False,
                            )
                        ),
                        "rushing_yards": draw(
                            st.floats(
                                min_value=0.0,
                                max_value=400.0,
                                allow_nan=False,
                                allow_infinity=False,
                            )
                        ),
                    }
                )
    return rows


# ---------------------------------------------------------------------------
# Scoring settings
# ---------------------------------------------------------------------------

@st.composite
def scoring_settings(
    draw,
    components: Sequence[str] = STAT_COMPONENTS,
    min_value: float = -10.0,
    max_value: float = 10.0,
):
    """A scoring settings dict mapping each stat component to a coefficient.

    Defaults span negative-to-positive so that ``projected_points`` can be any
    sign (matches Property 18's scoring-correctness input space).
    """
    return {
        c: draw(
            st.floats(
                min_value=min_value,
                max_value=max_value,
                allow_nan=False,
                allow_infinity=False,
            )
        )
        for c in components
    }


def unit_scoring(components: Sequence[str] = STAT_COMPONENTS) -> dict:
    """A scoring dict of all ``1.0`` — handy for no-future-leak style tests."""
    return {c: 1.0 for c in components}


# ---------------------------------------------------------------------------
# Projections frame (waiver / recommendations)
# ---------------------------------------------------------------------------

@st.composite
def projections_frame(
    draw,
    id_space=DEFAULT_ID_SPACE,
    positions: Sequence[str] = POSITIONS,
    teams: Sequence[str] = TEAMS,
    min_rows: int = 0,
    max_rows: int = 25,
    allow_none_points: bool = True,
) -> pl.DataFrame:
    """A projections polars frame with unique ``player_id``s over ``id_space``.

    ``projected_points`` may be ``None`` (the waiver service tolerates missing
    projections) when ``allow_none_points`` is set. Ids are drawn from the
    shared id space so rosters built from the same space overlap.
    """
    n = draw(st.integers(min_value=min_rows, max_value=max_rows))
    ids = draw(st.lists(id_space, min_size=n, max_size=n, unique=True))
    points_strategy = st.floats(
        min_value=0.0, max_value=500.0, allow_nan=False, allow_infinity=False
    )
    if allow_none_points:
        points_strategy = st.one_of(st.none(), points_strategy)

    rows = []
    for pid in ids:
        rows.append(
            {
                "player_id": pid,
                "player_name": f"Player {pid}",
                "position": draw(st.sampled_from(list(positions))),
                "team": draw(st.sampled_from(list(teams))),
                "projected_points": draw(points_strategy),
            }
        )
    if not rows:
        # polars needs an explicit schema for an empty frame.
        return pl.DataFrame(schema={c: pl.Utf8 for c in PROJ_COLUMNS})
    return pl.DataFrame(rows)


# ---------------------------------------------------------------------------
# League rosters
# ---------------------------------------------------------------------------

@st.composite
def league_roster(
    draw,
    roster_id,
    owner_id,
    id_space=DEFAULT_ID_SPACE,
    max_players: int = 12,
    max_reserve: int = 4,
) -> Roster:
    """A single :class:`Roster` drawn from ``id_space``.

    ``starters`` and ``reserve`` are disjoint subsets of ``players`` so the
    derived bench (``players - starters - reserve``) matches real Sleeper
    shape.
    """
    players = draw(st.lists(id_space, min_size=0, max_size=max_players, unique=True))
    if players:
        starters = draw(
            st.lists(
                st.sampled_from(players),
                min_size=0,
                max_size=len(players),
                unique=True,
            )
        )
        remaining = [p for p in players if p not in starters]
        reserve = (
            draw(
                st.lists(
                    st.sampled_from(remaining) if remaining else st.nothing(),
                    min_size=0,
                    max_size=min(len(remaining), max_reserve),
                    unique=True,
                )
            )
            if remaining
            else []
        )
    else:
        starters = []
        reserve = []
    return Roster(
        roster_id=str(roster_id),
        owner_id=str(owner_id),
        starters=starters,
        players=players,
        reserve=reserve,
    )


@st.composite
def league_rosters(
    draw,
    id_space=DEFAULT_ID_SPACE,
    min_rosters: int = 0,
    max_rosters: int = 4,
    target_owner_id: Optional[str] = None,
):
    """A list of :class:`Roster` objects drawn from a shared id space.

    When ``target_owner_id`` is given, roster 0 is always owned by that id (so
    a target-user lookup always resolves); the remaining rosters get synthetic
    owner ids. Otherwise all owner ids are synthetic.
    """
    if target_owner_id is not None:
        rosters = [
            draw(league_roster(roster_id=1, owner_id=target_owner_id, id_space=id_space))
        ]
        n_extra = draw(st.integers(min_value=0, max_value=max(0, max_rosters - 1)))
        for i in range(n_extra):
            rosters.append(
                draw(
                    league_roster(
                        roster_id=i + 2, owner_id=str(2000 + i), id_space=id_space
                    )
                )
            )
        return rosters

    n = draw(st.integers(min_value=min_rosters, max_value=max_rosters))
    return [
        draw(league_roster(roster_id=i + 1, owner_id=str(1000 + i), id_space=id_space))
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# League roster_positions config
# ---------------------------------------------------------------------------

@st.composite
def roster_positions(
    draw,
    starting_choices: Sequence[str] = STARTING_SLOT_CHOICES,
    bench_choices: Sequence[str] = NON_STARTING_SLOT_CHOICES,
    max_starting: int = 12,
    max_bench: int = 6,
):
    """A league ``roster_positions`` array mixing starting and bench slots.

    Starting and bench slots are drawn independently then shuffled, matching
    how Sleeper reports an arbitrary slot order.
    """
    starters = draw(
        st.lists(st.sampled_from(list(starting_choices)), max_size=max_starting)
    )
    bench = draw(st.lists(st.sampled_from(list(bench_choices)), max_size=max_bench))
    combined = list(starters) + list(bench)
    draw(st.randoms()).shuffle(combined)
    return combined


# ---------------------------------------------------------------------------
# Sleeper trending-add payload
# ---------------------------------------------------------------------------

@st.composite
def trending_payload(
    draw,
    id_space=DEFAULT_ID_SPACE,
    max_entries: int = 10,
    max_count: int = 100_000,
):
    """A Sleeper trending-add payload: a list of ``{player_id, count}`` dicts."""
    n = draw(st.integers(min_value=0, max_value=max_entries))
    return [
        {
            "player_id": draw(id_space),
            "count": draw(st.integers(min_value=0, max_value=max_count)),
        }
        for _ in range(n)
    ]
