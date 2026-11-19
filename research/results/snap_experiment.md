# Snap-aware baseline experiment

Season 2025, 500 simulated rosters, 9000 roster-weeks. Same rosters, weeks and lineup solver as `backtest.md` (same seed). Variants change only the BASELINE; defense factors and the Vegas environment multiplier are identical to production v2.

## Points per roster-week

| Strategy | pts/roster-week | % of hindsight | vs v2 | vs naive |
|---|---|---|---|---|
| naive (trailing 3-wk avg) | 141.26 | 85.50% | +0.23 |  |
| v2 (production) | 141.03 | 85.36% |  | -0.23 |
| snap_role (rate 6g x snaps 3g) | 141.13 | 85.42% | +0.10 | -0.12 |
| snap_role + blowout adj | 141.15 | 85.43% | +0.11 | -0.11 |
| snap_r4s2 (rate 4g x snaps 2g) | 141.74 | 85.79% | +0.71 | +0.48 |
| snap_r8s3 (rate 8g x snaps 3g) | 140.95 | 85.31% | -0.08 | -0.31 |
| hindsight-optimal | 165.22 | 100.00% |  |  |

## Paired tests

`roster-week` treats every roster-week as independent (optimistic: rosters share players and a week's outcomes are correlated). `week-clustered` averages within each week first and tests the weekly means, the more conservative read. `weeks better` counts weeks where the first strategy beat the second.

| Comparison | mean diff | t (roster-week) | p | t (week-clustered) | p | weeks better |
|---|---|---|---|---|---|---|
| v2 - naive | -0.226 | -1.69 | 0.0918 | -0.34 | 0.7393 | 10/18 |
| snap_role - v2 | +0.102 | 1.02 | 0.3092 | 0.27 | 0.7905 | 7/18 |
| snap_role_blowout - v2 | +0.114 | 1.12 | 0.2646 | 0.29 | 0.7733 | 9/18 |
| snap_r4s2 - v2 | +0.708 | 7.41 | 0.0000 | 1.79 | 0.0906 | 11/18 |
| snap_r8s3 - v2 | -0.083 | -0.74 | 0.4596 | -0.20 | 0.8448 | 7/18 |
| snap_role - naive | -0.124 | -0.82 | 0.4097 | -0.13 | 0.8975 | 10/18 |
| snap_role_blowout - naive | -0.112 | -0.75 | 0.4521 | -0.12 | 0.9058 | 10/18 |
| snap_r4s2 - naive | +0.482 | 3.34 | 0.0008 | 0.61 | 0.5468 | 13/18 |
| snap_r8s3 - naive | -0.309 | -1.99 | 0.0469 | -0.37 | 0.7140 | 10/18 |

## MAE and bias by position (expected vs actual PPR points)

bias = mean(expected - actual); positive = over-projecting.

| Position | naive MAE | v2 MAE | snap_role MAE | snap_role_blowout MAE | snap_r4s2 MAE | snap_r8s3 MAE | naive bias | v2 bias | snap_role bias | snap_role_blowout bias | snap_r4s2 bias | snap_r8s3 bias |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| QB | 6.68 | 6.89 | 6.64 | 6.63 | 6.81 | 6.53 | -1.46 | -0.79 | -0.55 | -0.60 | -0.70 | -0.44 |
| RB | 7.52 | 7.52 | 7.23 | 7.23 | 7.27 | 7.18 | -1.79 | -1.49 | -1.18 | -1.17 | -1.36 | -1.13 |
| WR | 7.47 | 7.94 | 7.71 | 7.65 | 7.85 | 7.73 | -1.30 | -0.52 | -0.49 | -0.56 | -0.46 | -0.50 |
| TE | 5.71 | 5.90 | 5.63 | 5.63 | 5.83 | 5.64 | -0.83 | -0.84 | -0.81 | -0.81 | -0.82 | -0.79 |

## Blowout coefficients (fit on 2024 only)

Change in a player's snap share per point of extra pregame favorite margin, relative to the games his recent snap average came from. Negative = plays fewer snaps when his team is more heavily favored.

| Position | beta (snap share / spread pt) | effect of +10 pt spread | observations |
|---|---|---|---|
| QB | -0.00175 | -1.75 pct-pts of snaps | 424 |
| RB | +0.00021 | +0.21 pct-pts of snaps | 485 |
| WR | -0.00314 | -3.14 pct-pts of snaps | 1264 |
| TE | -0.00024 | -0.24 pct-pts of snaps | 616 |

## Worked example

Live example: 2026 week 10, built from games strictly before week 10.

| Player | Team | Opp | Fav margin | naive | v2 | snap_role | snap_role + blowout |
|---|---|---|---|---|---|---|---|
| Parker Washington | JAX | TEN | +10.5 | 8.8 | 12.4 | 14.1 | 13.9 |
| Germie Bernard | PIT | CIN | -3.5 | 12.6 | 16.4 | 16.2 | 16.5 |

- Parker Washington games used: wk1: 61% snaps / 19.3 pts, wk2: 81% snaps / 16.8 pts, wk3: 81% snaps / 13.0 pts, wk4: 80% snaps / 2.0 pts, wk5: 82% snaps / 30.4 pts, wk6: 73% snaps / 10.4 pts, wk8: 67% snaps / 3.6 pts, wk9: 68% snaps / 14.1 pts
- Germie Bernard games used: wk2: 79% snaps / 7.5 pts, wk3: 27% snaps / 2.4 pts, wk4: 40% snaps / 3.1 pts, wk5: 92% snaps / 14.4 pts, wk6: 94% snaps / 25.7 pts, wk7: 91% snaps / 5.7 pts, wk8: 85% snaps / 8.0 pts

## Integrity checks

- Helper that applies v2's defense x Vegas stage to a given baseline reproduced production v2 to within 0.00e+00 stat-line units over 500 player-weeks.
- Blowout coefficients were fit on the season BEFORE the test season, so the test season is out-of-sample.
