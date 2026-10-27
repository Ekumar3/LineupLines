{{ config(materialized='view') }}
-- Primary key: (season, week, team, side)
-- One row per team-game-perspective. 'off' = team on offense (OL view);
-- 'def' = team on defense (DL view). dropbacks = pass attempts + sacks + scrambles.
--
-- Rolling trailing average: expanding current-season window, prior-season
-- fallback. No future leak — only (season, week) strictly before the target
-- contribute to each row's trailing averages.

with plays as (
    select
        season, week, game_id, posteam, defteam,
        play_type, sack, qb_hit, qb_scramble, pass_attempt, rush_attempt, epa
    from {{ ref('stg_pbp') }}
    where play_type in ('pass', 'run')
      and (pass_attempt = 1 or rush_attempt = 1 or sack = 1 or qb_scramble = 1)
),

-- Offensive perspective: team is posteam (their OL is protecting)
off_game as (
    select
        season, week, posteam as team,
        sum(case when pass_attempt = 1 or sack = 1 or qb_scramble = 1 then 1 else 0 end) as dropbacks,
        sum(sack) as sacks,
        sum(qb_hit) as qb_hits,
        sum(case when epa is not null and (pass_attempt = 1 or sack = 1) then epa end) as pass_epa
    from plays
    group by season, week, posteam
),

-- Defensive perspective: team is defteam (their DL is rushing)
def_game as (
    select
        season, week, defteam as team,
        sum(case when pass_attempt = 1 or sack = 1 or qb_scramble = 1 then 1 else 0 end) as dropbacks,
        sum(sack) as sacks,
        sum(qb_hit) as qb_hits,
        -- negative EPA allowed = good DL; store raw, invert at grade time
        sum(case when epa is not null and (pass_attempt = 1 or sack = 1) then epa end) as pass_epa
    from plays
    group by season, week, defteam
),

team_game as (
    select 'off' as side, * from off_game
    union all
    select 'def' as side, * from def_game
),

per_game as (
    select
        season, week, team, side,
        dropbacks,
        sacks,
        qb_hits,
        cast(dropbacks as double) as _db,
        case when dropbacks > 0 then cast(sacks as double) / dropbacks else 0 end as sack_rate,
        case when dropbacks > 0 then cast(sacks + qb_hits as double) / dropbacks else 0 end as pressure_rate,
        case when dropbacks > 0 then pass_epa / dropbacks else 0 end as pass_epa_per_dropback
    from team_game
)

-- Rolling trailing average: expanding current-season window, prior-season
-- fallback. No future leak — only (season, week) strictly before the target.
select
    t.season, t.week, t.team, t.side,
    -- Final `0` fallback covers the earliest week in the dataset, where no
    -- prior current-season game and no prior-season game exist. Matches the
    -- per-game `else 0` neutral-baseline convention above and keeps a row for
    -- every team-week with no future leak (games_trailing stays 0 there).
    coalesce(
        avg(g.pressure_rate) filter (where g.season = t.season),
        avg(g.pressure_rate) filter (where g.season = t.season - 1),
        0
    ) as pressure_rate_trailing,
    coalesce(
        avg(g.sack_rate) filter (where g.season = t.season),
        avg(g.sack_rate) filter (where g.season = t.season - 1),
        0
    ) as sack_rate_trailing,
    coalesce(
        avg(g.pass_epa_per_dropback) filter (where g.season = t.season),
        avg(g.pass_epa_per_dropback) filter (where g.season = t.season - 1),
        0
    ) as pass_epa_per_dropback_trailing,
    coalesce(
        count(*) filter (where g.season = t.season),
        count(*) filter (where g.season = t.season - 1)
    ) as games_trailing
from per_game t
left join per_game g
    on g.team = t.team and g.side = t.side
    and (g.season, g.week) < (t.season, t.week)
group by t.season, t.week, t.team, t.side
