import nflreadpy as nfl

# look at the columns that exist in the weekly player data
# weekly = nfl.load_player_stats([2025])
# print(weekly.columns)
# print(weekly.head())

# # look at pbp
# pbp = nfl.load_pbp([2025])
# print(pbp.columns)

# # snap counts
# snaps = nfl.load_snap_counts([2025])
# print(snaps.columns)

ftn = nfl.load_ftn_charting([2025])
print(ftn.columns)
print(ftn.head())