-- Singular test: matchup signals match the grade-difference thresholds.
--
-- For each of the pass, rush, and overall channels the signal must be derived
-- strictly from its matchup value:
--   favorable   <=> matchup >  10
--   unfavorable <=> matchup < -10
--   neutral     <=> matchup between -10 and 10 (inclusive), OR matchup is null
--                   (null = a scheduled game whose OL/DL grade is unavailable).
--
-- Any row whose signal disagrees with its matchup value under these rules is a
-- violation. This test passes when it returns zero rows.

with m as (
    select
        season, week, team, opponent,
        pass_matchup, rush_matchup, overall_matchup,
        pass_signal, rush_signal, overall_signal
    from {{ ref('mart_matchup_grade') }}
),

violations as (
    -- pass channel
    select season, week, team, opponent, 'pass' as channel, pass_matchup as matchup, pass_signal as signal
    from m
    where (pass_matchup >  10 and pass_signal <> 'favorable')
       or (pass_matchup < -10 and pass_signal <> 'unfavorable')
       or (pass_matchup between -10 and 10 and pass_signal <> 'neutral')
       or (pass_matchup is null and pass_signal <> 'neutral')

    union all

    -- rush channel
    select season, week, team, opponent, 'rush' as channel, rush_matchup as matchup, rush_signal as signal
    from m
    where (rush_matchup >  10 and rush_signal <> 'favorable')
       or (rush_matchup < -10 and rush_signal <> 'unfavorable')
       or (rush_matchup between -10 and 10 and rush_signal <> 'neutral')
       or (rush_matchup is null and rush_signal <> 'neutral')

    union all

    -- overall channel
    select season, week, team, opponent, 'overall' as channel, overall_matchup as matchup, overall_signal as signal
    from m
    where (overall_matchup >  10 and overall_signal <> 'favorable')
       or (overall_matchup < -10 and overall_signal <> 'unfavorable')
       or (overall_matchup between -10 and 10 and overall_signal <> 'neutral')
       or (overall_matchup is null and overall_signal <> 'neutral')
)

select * from violations
