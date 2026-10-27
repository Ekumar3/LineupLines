-- Singular test: monotonic (season, week) ordering per (team, side).
--
-- The trailing window is an expanding current-season window with a
-- prior-season fallback. Within a single season, as (season, week) advances
-- for a given (team, side), the number of games contributing to the trailing
-- average (games_trailing) must never decrease — every later week sees at
-- least as many prior games as every earlier week. A decrease would signal a
-- future-leak or windowing bug.
--
-- This test passes when it returns zero rows.

with ordered as (
    select
        season, week, team, side, games_trailing,
        lag(games_trailing) over (
            partition by team, side, season
            order by week
        ) as prev_games_trailing
    from {{ ref('int_team_run_metrics') }}
)

select *
from ordered
where prev_games_trailing is not null
  and games_trailing < prev_games_trailing
