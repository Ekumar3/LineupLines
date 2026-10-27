-- Staging model: weekly player stat lines from nflverse.
--
-- Reads player_stats parquet, filters to regular season, and casts columns
-- to consistent types. The column names match what the existing research
-- model (research/model.py) expects; the defense model and projection service
-- will read from the downstream feature mart (Task 9).
--
-- Primary key: (player_id, season, week)

{{ config(materialized='view') }}

with source as (
    select *
    from read_parquet('{{ var("raw_data_path") }}/player_stats_*.parquet')
)

select
    cast(player_id as varchar)         as player_id,
    cast(player_display_name as varchar) as player_display_name,
    cast(position as varchar)          as position,
    cast(season as integer)             as season,
    cast(week as integer)               as week,
    cast(season_type as varchar)        as season_type,
    cast(team as varchar)               as team,
    cast(opponent_team as varchar)      as opponent_team,
    cast(attempts as double)            as attempts,
    cast(passing_yards as double)       as passing_yards,
    cast(passing_tds as double)          as passing_tds,
    cast(passing_interceptions as double) as passing_interceptions,
    cast(passing_epa as double)         as passing_epa,
    cast(carries as double)             as carries,
    cast(rushing_yards as double)       as rushing_yards,
    cast(rushing_tds as double)          as rushing_tds,
    cast(rushing_epa as double)         as rushing_epa,
    cast(receptions as double)          as receptions,
    cast(targets as double)             as targets,
    cast(receiving_yards as double)     as receiving_yards,
    cast(receiving_tds as double)        as receiving_tds,
    cast(receiving_epa as double)       as receiving_epa,
    cast(target_share as double)        as target_share,
    cast(fumbles_lost_total as double)  as fumbles_lost_total,
    cast(fantasy_points as double)      as fantasy_points
from source
where season_type = 'REG'
  and player_id is not null
