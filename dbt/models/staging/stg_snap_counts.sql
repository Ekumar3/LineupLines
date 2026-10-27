-- Staging model: weekly snap counts from nflverse.
--
-- Reads snap_counts parquet, filters to regular season, and casts columns.
-- The offense_pct column feeds the opportunity delta in the projection model
-- (how much of the offense's snaps a player is on the field for).
--
-- Primary key: (player, season, week)  — nflverse snap counts key on the
-- display name, not a stable player_id; the research model joins on a
-- normalized name (see research/model.py _normalize_name).

{{ config(materialized='view') }}

with source as (
    select *
    from read_parquet('{{ var("raw_data_path") }}/snap_counts_*.parquet')
)

select
    cast(season as integer)        as season,
    cast(week as integer)          as week,
    cast(game_type as varchar)     as game_type,
    cast(team as varchar)          as team,
    cast(opponent as varchar)      as opponent_team,
    cast(player as varchar)        as player,
    cast(position as varchar)     as position,
    cast(offense_snaps as double)  as offense_snaps,
    cast(offense_pct as double)    as offense_pct,
    cast(defense_snaps as double)  as defense_snaps,
    cast(defense_pct as double)    as defense_pct
from source
where game_type = 'REG'
