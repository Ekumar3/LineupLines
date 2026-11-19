# Backtest Results — Start/Sit Model, v1 vs v2

Season: 2025  
Simulated rosters: 500  
Roster-weeks evaluated: 9000  
Hindsight-optimal average: 165.2 pts/roster-week

| Strategy | What it is |
|---|---|
| v1 | v1 (four-delta scalar) |
| v2 | v2 (defense factors x Vegas) |
| naive | naive (trailing 3-wk avg) |
| hindsight | hindsight-optimal |

## Bottom line

- **v1 beats naive**: +0.82 pts/roster-week (t=6.29, p=0.0000)
- **v2 vs naive: no significant difference** (-0.23 pts/roster-week, t=-1.69, p=0.0918)
- **v2 LOSES to v1**: -1.04 pts/roster-week (t=-8.68, p=0.0000)

Naive leaves 24.0 pts/roster-week on the table vs. hindsight. v1 recovers +0.82 of that, v2 recovers -0.23. Most of the remainder is TD variance no pregame projection recovers.

## % of hindsight-optimal points captured

| Strategy | pts/roster-week | % of optimal |
|---|---|---|
| v1 | 142.07 | 85.99% |
| v2 | 141.03 | 85.36% |
| naive | 141.26 | 85.50% |
| hindsight | 165.22 | 100.00% |

### By starting slot

| Slot | Hindsight pts | v1 % | v2 % | naive % | v2 − v1 (pts) |
|---|---|---|---|---|---|
| QB | 191455 | 86.7% | 85.6% | 83.7% | -2171 |
| RB | 377580 | 87.4% | 88.0% | 88.1% | +2403 |
| WR | 519214 | 84.7% | 82.9% | 83.7% | -9209 |
| TE | 125413 | 83.5% | 82.5% | 83.3% | -1359 |
| FLEX | 182781 | 83.4% | 83.9% | 84.0% | +951 |
| K | 76964 | 99.5% | 99.5% | 99.5% | +0 |
| DEF | 13582 | 66.5% | 66.5% | 66.5% | +0 |

K and DEF are identical across v1/v2/naive by construction (see module docstring).

## Paired tests across roster-weeks

| Comparison | mean diff (pts) | t | p | n |
|---|---|---|---|---|
| v1 − naive | +0.817 | 6.294 | 0.0000 | 9000 |
| v2 − naive | -0.226 | -1.686 | 0.0918 | 9000 |
| v2 − v1 | -1.043 | -8.678 | 0.0000 | 9000 |

## MAE and bias (expected vs. actual PPR points), by position

bias = mean(expected − actual); positive = over-projecting.

| Position | v1 MAE | v2 MAE | naive MAE | v1 bias | v2 bias | naive bias | n |
|---|---|---|---|---|---|---|---|
| QB | 6.78 | 6.89 | 6.68 | -1.22 | -0.79 | -1.46 | 15555 |
| RB | 7.78 | 7.52 | 7.52 | -1.58 | -1.49 | -1.79 | 32894 |
| WR | 7.62 | 7.94 | 7.47 | -1.00 | -0.52 | -1.30 | 40295 |
| TE | 5.91 | 5.90 | 5.71 | -1.00 | -0.84 | -0.83 | 15466 |
| K | 4.85 | 4.85 | 4.85 | +0.78 | +0.78 | +0.78 | 8918 |
| DEF | 2.36 | 2.36 | 2.36 | -0.06 | -0.06 | -0.06 | 9000 |

All three share the same unshrunk trailing baseline, so the ~2 pt over-projection is common to all of them and does not affect the relative comparison. K/DEF rows reflect the trailing-average-only estimate, not either model.

## v2 diagnostic: does the defense factor predict the residual?

For each modeled player-week, residual = actual − baseline PPR points from that channel's components only. If the opponent-adjusted factor carries real signal, residual should rise with the factor (defenses that allow more → players beat their baseline more).

| Channel | Pearson r (log factor, residual) | n |
|---|---|---|
| pass | 0.078 | 104210 |
| rush | 0.062 | 104210 |

**pass channel, by factor quintile**

| Quintile | mean factor | mean residual (pts) | n |
|---|---|---|---|
| Q1 | 0.905 | -0.30 | 20842 |
| Q2 | 0.957 | +1.33 | 20842 |
| Q3 | 1.001 | +0.98 | 20842 |
| Q4 | 1.036 | +0.62 | 20842 |
| Q5 | 1.108 | +1.96 | 20842 |

**rush channel, by factor quintile**

| Quintile | mean factor | mean residual (pts) | n |
|---|---|---|---|
| Q1 | 0.873 | -0.02 | 20842 |
| Q2 | 0.945 | +0.20 | 20842 |
| Q3 | 0.997 | +0.41 | 20842 |
| Q4 | 1.059 | +0.82 | 20842 |
| Q5 | 1.146 | +1.05 | 20842 |

## v1 error attribution: correlation of each delta with prediction error

error = actual_points_ppr − expected_points_ppr (QB/RB/WR/TE only)

| Delta term | Pearson r vs. error | n |
|---|---|---|
| delta_opportunity | -0.139 | 104210 |
| delta_environment | -0.139 | 104210 |
| delta_efficiency | -0.038 | 104210 |
| delta_matchup | -0.033 | 104210 |

## Configuration

v1 weights (untouched):

```json
{
  "delta_opportunity": 0.45,
  "delta_environment": 0.25,
  "delta_efficiency": 0.2,
  "delta_matchup": 0.1
}
```

v2 config:

```json
{
  "environment_weight": 0.25,
  "ridge_lambda": 4.0,
  "prior_season_weight": 0.3,
  "factor_clamp": [
    0.75,
    1.25
  ]
}
```
