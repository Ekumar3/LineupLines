-- Singular test: no future leak in int_team_pass_metrics trailing averages.
--
-- For each (season, week, team, side) target row the current-season trailing
-- average must be reproducible from ONLY the per-game rows whose
-- (season, week) is strictly before the target. We independently recompute
-- games_trailing for the current season from the plays and confirm it matches
-- the model's games_trailing whenever the model used the current season (i.e.
-- at least one prior current-season game existed). Any mismatch means the
-- trailing window either pulled in the target week itself (future leak) or
-- dropped a valid prior game.
--
-- This test passes when it returns zero rows.

with plays as (
    select
        season, week, posteam, defteam, sack, qb_scramble, pass_attempt, rush_attempt
    from {{ ref('stg_pbp') }}
    where play_type in ('pass', 'run')
      and (pass_attempt = 1 or rush_attempt = 1 or sack = 1 or qb_scramble = 1)
),

off_game as (
    select season, week, posteam as team, 'off' as side
    from plays group by season, week, posteam
),
def_game as (
    select season, week, defteam as team, 'def' as side
    from plays group by season, week, defteam
),
per_game as (
    select * from off_game
    union all
    select * from def_game
),

-- recompute current-season trailing game count from strictly-prior games only
expected as (
    select
        t.season, t.week, t.team, t.side,
        count(g.week) as expected_current_games
    from per_game t
    left join per_game g
        on g.team = t.team and g.side = t.side
        and g.season = t.season
        and (g.season, g.week) < (t.season, t.week)
    group by t.season, t.week, t.team, t.side
)

select
    m.season, m.week, m.team, m.side,
    m.games_trailing,
    e.expected_current_games
from {{ ref('int_team_pass_metrics') }} m
join expected e
    on e.season = m.season and e.week = m.week
   and e.team = m.team and e.side = m.side
-- only assert when the model fell back on the current season (prior games exist)
where e.expected_current_games > 0
  and m.games_trailing <> e.expected_current_games
