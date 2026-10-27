{{ config(materialized='table') }}
-- Primary key: (season, week, team)
-- The defensive mirror of mart_ol_grade. Same structure, but side = 'def' and
-- the percentile directions flip: higher pressure/sack = better DL, lower EPA
-- allowed and lower yards allowed = better DL. Grade scale: 0-100, 50 = league
-- average, higher = better DL.
--
-- Weights: pass rush = 60% of DL grade, run defense = 40%.
--   pass_rush_grade    = 0.40*pressure + 0.25*sack + 0.35*inv_epa
--   run_defense_grade  = 0.40*inv_ypc + 0.35*inv_run_epa + 0.25*stuff

with pass_m as (
    select season, week, team, pressure_rate_trailing, sack_rate_trailing, pass_epa_per_dropback_trailing
    from {{ ref('int_team_pass_metrics') }}
    where side = 'def'
),
run_m as (
    select season, week, team, stuff_rate_trailing, yards_per_carry_trailing, run_epa_per_carry_trailing
    from {{ ref('int_team_run_metrics') }}
    where side = 'def'
),

ranked as (
    select
        p.season, p.week, p.team,
        percent_rank() over (partition by p.season, p.week order by p.pressure_rate_trailing) * 100 as p_pressure,
        percent_rank() over (partition by p.season, p.week order by p.sack_rate_trailing) * 100 as p_sack,
        (1 - percent_rank() over (partition by p.season, p.week order by p.pass_epa_per_dropback_trailing)) * 100 as p_inv_epa,
        (1 - percent_rank() over (partition by p.season, p.week order by r.yards_per_carry_trailing)) * 100 as r_inv_ypc,
        (1 - percent_rank() over (partition by p.season, p.week order by r.run_epa_per_carry_trailing)) * 100 as r_inv_run_epa,
        percent_rank() over (partition by p.season, p.week order by r.stuff_rate_trailing) * 100 as r_stuff
    from pass_m p
    join run_m r using (season, week, team)
)

select
    season, week, team,
    round(0.40 * p_pressure + 0.25 * p_sack + 0.35 * p_inv_epa, 2) as pass_rush_grade,
    round(0.40 * r_inv_ypc + 0.35 * r_inv_run_epa + 0.25 * r_stuff, 2) as run_defense_grade,
    round(0.60 * (0.40 * p_pressure + 0.25 * p_sack + 0.35 * p_inv_epa)
        + 0.40 * (0.40 * r_inv_ypc + 0.35 * r_inv_run_epa + 0.25 * r_stuff), 2) as dl_grade
from ranked
