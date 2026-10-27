{{ config(materialized='table') }}
-- Primary key: (season, week, team, opponent)
-- Joins the offense team's OL grade vs the opponent's DL grade per channel,
-- then joins to stg_schedules so every scheduled game has a matchup row. One
-- row per (team, opponent, season, week) from the offense's perspective — each
-- game produces two rows (home offense vs away defense, away offense vs home
-- defense). Positive channel grades mean the offense is favored.
--
-- Signals: favorable when matchup > 10, unfavorable when matchup < -10,
-- neutral otherwise — for pass, rush, and overall channels.

with games as (
    -- explode every scheduled game into two offensive perspectives
    select season, week, home_team as team, away_team as opponent from {{ ref('stg_schedules') }}
    union all
    select season, week, away_team as team, home_team as opponent from {{ ref('stg_schedules') }}
),

matchup as (
    select
        g.season, g.week, g.team, g.opponent,
        ol.pass_protection_grade, ol.run_blocking_grade, ol.ol_grade,
        dl.pass_rush_grade, dl.run_defense_grade, dl.dl_grade,
        -- channel grades: offense sub-grade minus defense sub-grade (positive = offense favored)
        round(ol.pass_protection_grade - dl.pass_rush_grade, 2) as pass_matchup,
        round(ol.run_blocking_grade - dl.run_defense_grade, 2) as rush_matchup,
        round(ol.ol_grade - dl.dl_grade, 2) as overall_matchup
    from games g
    left join {{ ref('mart_ol_grade') }} ol
        on ol.season = g.season and ol.week = g.week and ol.team = g.team
    left join {{ ref('mart_dl_grade') }} dl
        on dl.season = g.season and dl.week = g.week and dl.team = g.opponent
)

select
    *,
    case
        when pass_matchup >  10 then 'favorable'
        when pass_matchup < -10 then 'unfavorable'
        else 'neutral'
    end as pass_signal,
    case
        when rush_matchup >  10 then 'favorable'
        when rush_matchup < -10 then 'unfavorable'
        else 'neutral'
    end as rush_signal,
    case
        when overall_matchup >  10 then 'favorable'
        when overall_matchup < -10 then 'unfavorable'
        else 'neutral'
    end as overall_signal
from matchup
