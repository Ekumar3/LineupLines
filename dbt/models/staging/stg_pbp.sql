-- Staging model: play-by-play data from nflverse.
--
-- Reads the column-selected parquet files written by scripts/ingest_nflverse.py
-- and applies light cleaning: type casts, regular-season filter, and a
-- consistent column set. No joins, no aggregation — that happens in the
-- intermediate and marts layers.
--
-- Primary key: (game_id, play_id)

{{ config(materialized='view') }}

with source as (
    select *
    from read_parquet('{{ var("raw_data_path") }}/pbp_*.parquet')
)

select
    cast(play_id as bigint)         as play_id,
    cast(game_id as varchar)        as game_id,
    cast(season as integer)         as season,
    cast(week as integer)           as week,
    cast(season_type as varchar)    as season_type,
    cast(game_date as date)         as game_date,
    cast(home_team as varchar)      as home_team,
    cast(away_team as varchar)      as away_team,
    cast(posteam as varchar)        as posteam,
    cast(defteam as varchar)        as defteam,
    cast(play_type as varchar)      as play_type,
    cast(yards_gained as double)    as yards_gained,
    cast(down as integer)           as down,
    cast(ydstogo as integer)         as ydstogo,
    cast(yardline_100 as integer)    as yardline_100,
    cast(qtr as integer)            as qtr,
    cast(sack as integer)           as sack,
    cast(qb_hit as integer)         as qb_hit,
    cast(qb_scramble as integer)    as qb_scramble,
    cast(pass_attempt as integer)   as pass_attempt,
    cast(rush_attempt as integer)   as rush_attempt,
    cast(complete_pass as integer)  as complete_pass,
    cast(incomplete_pass as integer) as incomplete_pass,
    cast(interception as integer)   as interception,
    cast(air_yards as double)       as air_yards,
    cast(yards_after_catch as double) as yards_after_catch,
    cast(passing_yards as double)   as passing_yards,
    cast(rushing_yards as double)   as rushing_yards,
    cast(receiving_yards as double) as receiving_yards,
    cast(epa as double)             as epa,
    cast(success as integer)        as success,
    cast(run_location as varchar)   as run_location,
    cast(run_gap as varchar)        as run_gap,
    cast(passer_player_id as varchar)  as passer_player_id,
    cast(receiver_player_id as varchar) as receiver_player_id,
    cast(rusher_player_id as varchar)  as rusher_player_id,
    cast(penalty as integer)        as penalty,
    cast(penalty_team as varchar)   as penalty_team
from source
where season_type = 'REG'
  and posteam is not null
  and defteam is not null
