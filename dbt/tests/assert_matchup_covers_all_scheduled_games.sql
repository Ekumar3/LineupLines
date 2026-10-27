-- Singular test: every scheduled (season, week, team) has a matchup row.
--
-- mart_matchup_grade explodes each scheduled game into two offensive
-- perspectives, so every team that appears in stg_schedules (as home_team or
-- away_team) must have at least one row (as the offense `team`) in
-- mart_matchup_grade for that (season, week). Any scheduled team-week missing
-- from the matchup mart is a coverage gap.
--
-- This test passes when it returns zero rows.

with scheduled_team_weeks as (
    select season, week, home_team as team from {{ ref('stg_schedules') }}
    union
    select season, week, away_team as team from {{ ref('stg_schedules') }}
),

matchup_team_weeks as (
    select distinct season, week, team from {{ ref('mart_matchup_grade') }}
)

select s.season, s.week, s.team
from scheduled_team_weeks s
left join matchup_team_weeks m
    on m.season = s.season and m.week = s.week and m.team = s.team
where m.team is null
