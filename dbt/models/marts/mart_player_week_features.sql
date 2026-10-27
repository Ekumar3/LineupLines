{{ config(materialized='table') }}
-- Primary key: (player_id, season, week)
--
-- Ports research/model.py::build_feature_table to SQL. One row per
-- (player, season, week) for QB/RB/WR/TE, carrying the 9-component stat line
-- plus every input the delta model needs. Snap counts join on a normalized
-- display name (same _normalize_name logic as the research model: lowercase,
-- strip apostrophes/periods/hyphens, strip ii/iii/iv/jr/sr suffixes, collapse
-- whitespace); implied team totals come from stg_schedules.

with stats as (
    select * from {{ ref('stg_player_stats') }}
    where position in ('QB', 'RB', 'WR', 'TE')
),

team_carries as (
    select season, week, team, sum(carries) as team_carries
    from stats group by season, week, team
),

snaps as (
    select
        season, week, team,
        lower(regexp_replace(regexp_replace(
            regexp_replace(player, '[''\.\-]', '', 'g'), '\s+(ii|iii|iv|jr|sr)$', '', 'g'
        ), '\s+', ' ', 'g')) as _norm_name,
        offense_pct
    from {{ ref('stg_snap_counts') }}
),

stats_named as (
    select
        s.*,
        lower(regexp_replace(regexp_replace(
            regexp_replace(s.player_display_name, '[''\.\-]', '', 'g'),
            '\s+(ii|iii|iv|jr|sr)$', '', 'g'
        ), '\s+', ' ', 'g')) as _norm_name,
        tc.team_carries
    from stats s
    left join team_carries tc using (season, week, team)
),

implied as (
    -- implied_home = (total + spread) / 2 ; implied_away = (total - spread) / 2
    select season, week, home_team as team,
           (total_line + spread_line) / 2.0 as implied_team_total
    from {{ ref('stg_schedules') }}
    union all
    select season, week, away_team as team,
           (total_line - spread_line) / 2.0 as implied_team_total
    from {{ ref('stg_schedules') }}
)

select
    s.season, s.week, s.player_id, s.player_display_name, s.position, s.team,
    s.opponent_team,
    coalesce(s.passing_yards, 0) as passing_yards,
    coalesce(s.passing_tds, 0) as passing_tds,
    coalesce(s.passing_interceptions, 0) as interceptions,
    coalesce(s.rushing_yards, 0) as rushing_yards,
    coalesce(s.rushing_tds, 0) as rushing_tds,
    coalesce(s.receptions, 0) as receptions,
    coalesce(s.receiving_yards, 0) as receiving_yards,
    coalesce(s.receiving_tds, 0) as receiving_tds,
    coalesce(s.fumbles_lost_total, 0) as fumbles_lost,
    coalesce(s.target_share, 0) as target_share,
    coalesce(s.carries, 0) as carries,
    coalesce(s.team_carries, 0) as team_carries,
    coalesce(s.targets, 0) as targets,
    coalesce(s.attempts, 0) as attempts,
    coalesce(sn.offense_pct, 0) as offense_pct,
    coalesce(im.implied_team_total, 0) as implied_team_total,
    coalesce(s.passing_epa, 0) as passing_epa,
    coalesce(s.rushing_epa, 0) as rushing_epa,
    coalesce(s.receiving_epa, 0) as receiving_epa
from stats_named s
left join snaps sn
    on sn.season = s.season and sn.week = s.week
   and sn.team = s.team and sn._norm_name = s._norm_name
left join implied im
    on im.season = s.season and im.week = s.week and im.team = s.team
