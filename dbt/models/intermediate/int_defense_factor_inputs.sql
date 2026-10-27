{{ config(materialized='table') }}
-- Primary key: (season, week, team, opponent_team)
--
-- Team-game yardage by channel — the input matrix the Python ridge regression
-- reads. Mirrors research/defense.py::team_games. One row per team-game with
-- the passing and rushing yards that team's QB/RB/WR/TE produced against the
-- opponent that week.

select
    season, week, team, opponent_team,
    sum(passing_yards) as passing_yards,
    sum(rushing_yards) as rushing_yards
from {{ ref('stg_player_stats') }}
where position in ('QB', 'RB', 'WR', 'TE')
group by season, week, team, opponent_team
