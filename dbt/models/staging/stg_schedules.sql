-- Staging model: game schedules with Vegas lines from nflverse.
--
-- Reads schedules parquet, filters to regular season, and casts columns.
-- The spread_line and total_line columns drive the implied team totals
-- (Vegas-implied points per team) used by the environment delta in the
-- projection model. home_score/away_score are used for DEF fantasy scoring
-- in the backtest and for computing points-allowed in the matchup context.
--
-- Primary key: game_id

{{ config(materialized='view') }}

with source as (
    select *
    from read_parquet('{{ var("raw_data_path") }}/schedules_*.parquet')
)

select
    cast(game_id as varchar)      as game_id,
    cast(season as integer)       as season,
    cast(game_type as varchar)    as game_type,
    cast(week as integer)         as week,
    cast(gameday as date)         as gameday,
    cast(weekday as varchar)      as weekday,
    cast(gametime as varchar)     as gametime,
    cast(away_team as varchar)    as away_team,
    cast(home_team as varchar)    as home_team,
    cast(away_score as double)    as away_score,
    cast(home_score as double)    as home_score,
    cast(spread_line as double)    as spread_line,
    cast(total_line as double)     as total_line,
    cast(roof as varchar)         as roof,
    cast(surface as varchar)      as surface
from source
where game_type = 'REG'
