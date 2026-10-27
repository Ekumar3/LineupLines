{{ config(materialized='view') }}
-- Primary key: (season, week, team, side)
-- stuff = run stopped at or behind LOS (yards_gained <= 0).
--
-- Rolling trailing average: expanding current-season window, prior-season
-- fallback. No future leak — only (season, week) strictly before the target
-- contribute to each row's trailing averages.

with run_plays as (
    select season, week, posteam, defteam, yards_gained, epa
    from {{ ref('stg_pbp') }}
    where play_type = 'run' and rush_attempt = 1
),

off_game as (
    select
        season, week, posteam as team,
        count(*) as carries,
        sum(yards_gained) as yards,
        sum(case when yards_gained <= 0 then 1 else 0 end) as stuffs,
        sum(epa) as run_epa
    from run_plays
    group by season, week, posteam
),

def_game as (
    select
        season, week, defteam as team,
        count(*) as carries,
        sum(yards_gained) as yards,
        sum(case when yards_gained <= 0 then 1 else 0 end) as stuffs,
        sum(epa) as run_epa
    from run_plays
    group by season, week, defteam
),

team_game as (
    select 'off' as side, * from off_game
    union all
    select 'def' as side, * from def_game
),

per_game as (
    select
        season, week, team, side, carries, yards,
        case when carries > 0 then cast(stuffs as double) / carries else 0 end as stuff_rate,
        case when carries > 0 then yards / cast(carries as double) else 0 end as yards_per_carry,
        case when carries > 0 then run_epa / cast(carries as double) else 0 end as run_epa_per_carry
    from team_game
)

select
    t.season, t.week, t.team, t.side,
    -- Final `0` fallback covers the earliest week in the dataset, where no
    -- prior current-season game and no prior-season game exist. Matches the
    -- per-game `else 0` neutral-baseline convention above and keeps a row for
    -- every team-week with no future leak (games_trailing stays 0 there).
    coalesce(
        avg(g.stuff_rate) filter (where g.season = t.season),
        avg(g.stuff_rate) filter (where g.season = t.season - 1),
        0
    ) as stuff_rate_trailing,
    coalesce(
        avg(g.yards_per_carry) filter (where g.season = t.season),
        avg(g.yards_per_carry) filter (where g.season = t.season - 1),
        0
    ) as yards_per_carry_trailing,
    coalesce(
        avg(g.run_epa_per_carry) filter (where g.season = t.season),
        avg(g.run_epa_per_carry) filter (where g.season = t.season - 1),
        0
    ) as run_epa_per_carry_trailing,
    coalesce(
        count(*) filter (where g.season = t.season),
        count(*) filter (where g.season = t.season - 1)
    ) as games_trailing
from per_game t
left join per_game g
    on g.team = t.team and g.side = t.side
    and (g.season, g.week) < (t.season, t.week)
group by t.season, t.week, t.team, t.side
