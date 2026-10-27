{{ config(materialized='table') }}
-- Primary key: (season, week, team)
-- Composite 0-100 OL grade per (team, season, week), built from the trailing
-- pass-protection and run-blocking percentiles. Percentile ranks are computed
-- within each (season, week) snapshot across all teams, so "90" means this
-- team's trailing metric is better than 90% of the league at this point in the
-- season. Grade scale: 0-100, 50 = league average, higher = better OL.
--
-- Weights: pass protection = 60% of OL grade, run blocking = 40%.
--   pass_protection_grade = 0.40*inv_pressure + 0.25*inv_sack + 0.35*pass_epa
--   run_blocking_grade    = 0.40*ypc + 0.35*run_epa + 0.25*inv_stuff

with pass_m as (
    select season, week, team, pressure_rate_trailing, sack_rate_trailing, pass_epa_per_dropback_trailing, games_trailing
    from {{ ref('int_team_pass_metrics') }}
    where side = 'off'
),
run_m as (
    select season, week, team, stuff_rate_trailing, yards_per_carry_trailing, run_epa_per_carry_trailing
    from {{ ref('int_team_run_metrics') }}
    where side = 'off'
),

ranked as (
    select
        p.season, p.week, p.team,
        p.games_trailing,
        -- inverse percentiles: lower pressure/sack = better protection = higher pct
        (1 - percent_rank() over (partition by p.season, p.week order by p.pressure_rate_trailing)) * 100 as p_inv_pressure,
        (1 - percent_rank() over (partition by p.season, p.week order by p.sack_rate_trailing)) * 100 as p_inv_sack,
        percent_rank() over (partition by p.season, p.week order by p.pass_epa_per_dropback_trailing) * 100 as p_pass_epa,
        percent_rank() over (partition by p.season, p.week order by r.yards_per_carry_trailing) * 100 as r_ypc,
        percent_rank() over (partition by p.season, p.week order by r.run_epa_per_carry_trailing) * 100 as r_run_epa,
        (1 - percent_rank() over (partition by p.season, p.week order by r.stuff_rate_trailing)) * 100 as r_inv_stuff
    from pass_m p
    join run_m r using (season, week, team)
)

select
    season, week, team,
    -- pass protection sub-grade (60% of OL); run blocking sub-grade (40%)
    round(0.40 * p_inv_pressure + 0.25 * p_inv_sack + 0.35 * p_pass_epa, 2) as pass_protection_grade,
    round(0.40 * r_ypc + 0.35 * r_run_epa + 0.25 * r_inv_stuff, 2) as run_blocking_grade,
    round(0.60 * (0.40 * p_inv_pressure + 0.25 * p_inv_sack + 0.35 * p_pass_epa)
        + 0.40 * (0.40 * r_ypc + 0.35 * r_run_epa + 0.25 * r_inv_stuff), 2) as ol_grade,
    games_trailing  -- from the joined metrics, for transparency
from ranked
